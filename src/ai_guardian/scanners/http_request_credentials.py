"""Static, value-free analysis of Python HTTP request credential flows.

Only Python syntax is parsed. The analyzed source is never imported, executed,
or sent anywhere. The deliberately bounded resolver follows simple assignments
within one module/function scope; it does not follow helper calls or runtime
values.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import PurePath
from typing import Any, Optional
from urllib.parse import parse_qsl, unquote, urlsplit

from ai_guardian.scanners.scan_result import ScanResult

logger = logging.getLogger(__name__)

CONFIG_SECTION = "http_request_credential_scanning"
VIOLATION_TYPE = "http_request_credential_detected"
ENGINE = "local-http-request-credential-analyzer"
RULE_ID = "HTTP-REQUEST-CREDENTIAL-001"

MAX_SOURCE_CHARS = 131_072
MAX_AST_NODES = 20_000
MAX_FINDINGS = 128
MAX_RESOLUTION_DEPTH = 12
MAX_RESOLVED_STRING_CHARS = 65_536
MAX_TOTAL_RESOLVED_STRING_CHARS = 131_072
MAX_RESOLUTION_OPERATIONS = 40_000
MAX_CONTAINER_TRAVERSAL = 20_000
MAX_STATE_SNAPSHOT_ENTRIES = 100_000
MAX_URL_CHARS = 16_384
MAX_TOTAL_URL_PARSE_CHARS = 262_144
MAX_BRANCH_ALTERNATIVES = 128

INLINE_LITERAL = "inline_literal"
INCOMPLETE_ANALYSIS = "unsupported_or_incomplete_analysis"
_VALID_ACTIONS = frozenset({"ask", "block", "warn", "log-only"})

BLOCK_MESSAGE = (
    "Hard-coded HTTP request credential detected in Python source; the write was "
    "blocked. Credential values and source snippets are withheld."
)
WARN_MESSAGE = (
    "Hard-coded HTTP request credential detected in Python source. The configured "
    "warn action allows this write; credential values and source snippets are withheld."
)
ASK_MESSAGE = (
    "Hard-coded HTTP request credential detected in Python source. Approve Once "
    "allows this write only; credential values and source snippets are withheld."
)
INCOMPLETE_MESSAGE = (
    "HTTP request credential analysis is incomplete; no credential is confirmed "
    "because the source could not be fully analyzed."
)

_SUPPORTED_MODULES = frozenset({"requests", "httpx", "aiohttp", "urllib.request"})
_REQUEST_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "request"}
)
_REQUEST_CONSTRUCTORS = {
    "requests.Request": "requests",
    "httpx.Request": "httpx",
    "urllib.request.Request": "urllib.request",
}
_CLIENT_CONSTRUCTORS = {
    "requests.Session": "requests",
    "httpx.Client": "httpx",
    "httpx.AsyncClient": "httpx",
    "aiohttp.ClientSession": "aiohttp",
}
_AUTH_CONSTRUCTORS = frozenset(
    {
        "requests.auth.HTTPBasicAuth",
        "httpx.BasicAuth",
        "aiohttp.BasicAuth",
    }
)
_AUTH_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "x-api-key",
        "x-api-token",
        "api-key",
        "x-auth-token",
        "x-access-token",
        "x-auth-key",
        "x-access-key",
        "x-client-token",
        "x-secret-key",
        "private-token",
        "x-client-secret",
    }
)
_CREDENTIAL_FIELDS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "token",
        "access_token",
        "api_token",
        "refresh_token",
        "id_token",
        "api_key",
        "apikey",
        "client_secret",
        "secret",
        "credential",
        "credentials",
        "auth_token",
        "authorization",
        "proxy_authorization",
        "private_token",
        "secret_key",
        "access_key",
        "aws_secret_access_key",
    }
)
_PLACEHOLDERS = frozenset(
    {
        "",
        "<token>",
        "<password>",
        "<secret>",
        "<credential>",
        "<redacted>",
        "your_token",
        "your-token",
        "your token",
        "your_password",
        "your-password",
        "your password",
        "your_api_key",
        "your-api-key",
        "your api key",
        "replace_me",
        "replace-me",
        "redacted",
        "placeholder",
        "example_token",
        "example-token",
        "changeme",
        "change_me",
        "change-me",
        "example",
        "demo",
        "dummy",
        "fake",
        "test",
        "todo",
    }
)
_REQUEST_SOURCE = re.compile(r"(?i)\b(?:requests|httpx|aiohttp|urllib(?:\.request)?)\b")
_CREDENTIAL_SOURCE = re.compile(
    r"(?i)\b(?:auth|headers?|authorization|x-api-key|password|passwd|"
    r"token|secret|api[_-]?key|credential)\b"
)
_URL_USERINFO_SOURCE = re.compile(r"(?i)https?://[^/\s?#\"'<>]*@")


def _has_relevant_source(source: str) -> bool:
    """Search bounded overlapping chunks so oversized suffixes fail closed."""
    overlap = 4096
    stride = MAX_SOURCE_CHARS - overlap
    request_source = False
    has_url_userinfo = _URL_USERINFO_SOURCE.search(source) is not None
    for start in range(0, len(source), stride):
        chunk = source[start : start + MAX_SOURCE_CHARS]
        request_matches = iter(_REQUEST_SOURCE.finditer(chunk))
        credential_matches = iter(_CREDENTIAL_SOURCE.finditer(chunk))
        request_match = next(request_matches, None)
        chunk_has_request = request_match is not None
        credential_match = next(credential_matches, None)
        while request_match is not None and credential_match is not None:
            if abs(request_match.start() - credential_match.start()) <= overlap:
                return True
            if request_match.start() < credential_match.start():
                request_match = next(request_matches, None)
            else:
                credential_match = next(credential_matches, None)
        request_source = request_source or chunk_has_request
        if chunk_has_request and _URL_USERINFO_SOURCE.search(chunk) is not None:
            return True
    # Search the complete source for URL userinfo so a very long authority can
    # cross chunk boundaries without treating unrelated @ characters as evidence.
    return request_source and has_url_userinfo


@dataclass(frozen=True)
class HttpRequestCredentialFinding:
    """Safe finding metadata; never includes source text or credential values."""

    line_number: Optional[int]
    client: str
    sink: str
    finding_class: str


@dataclass(frozen=True)
class HttpRequestCredentialAnalysis:
    findings: tuple[HttpRequestCredentialFinding, ...] = ()
    incomplete: bool = False


@dataclass(frozen=True)
class _Value:
    kind: str
    value: Any = None


_UNKNOWN = _Value("unknown")
_REFERENCE = _Value("reference")


@dataclass
class _AnalysisBudget:
    """Aggregate work limits shared by all scopes and branch snapshots."""

    resolution_operations: int = 0
    container_visits: int = 0
    resolved_string_chars: int = 0
    url_parse_chars: int = 0
    state_snapshot_entries: int = 0
    exhausted: bool = False

    def is_exhausted(self) -> bool:
        """Return the mutable exhaustion state without stale static narrowing."""
        return self.exhausted

    def _consume(self, current: int, amount: int, limit: int) -> bool:
        if self.exhausted or amount < 0 or current + amount > limit:
            self.exhausted = True
            return False
        return True

    def consume_resolution(self, amount: int = 1) -> bool:
        if not self._consume(
            self.resolution_operations, amount, MAX_RESOLUTION_OPERATIONS
        ):
            return False
        self.resolution_operations += amount
        return True

    def consume_container(self) -> bool:
        if not self._consume(self.container_visits, 1, MAX_CONTAINER_TRAVERSAL):
            return False
        self.container_visits += 1
        return True

    def consume_string_chars(self, amount: int) -> bool:
        if amount > MAX_RESOLVED_STRING_CHARS or not self._consume(
            self.resolved_string_chars, amount, MAX_TOTAL_RESOLVED_STRING_CHARS
        ):
            self.exhausted = True
            return False
        self.resolved_string_chars += amount
        return True

    def consume_url_parse_chars(self, amount: int) -> bool:
        if not self._consume(self.url_parse_chars, amount, MAX_TOTAL_URL_PARSE_CHARS):
            return False
        self.url_parse_chars += amount
        return True

    def consume_snapshot_entries(self, amount: int) -> bool:
        if not self._consume(
            self.state_snapshot_entries, amount, MAX_STATE_SNAPSHOT_ENTRIES
        ):
            return False
        self.state_snapshot_entries += amount
        return True


def _alternatives(
    values: tuple[_Value, ...], budget: Optional[_AnalysisBudget] = None
) -> _Value:
    unique: list[_Value] = []
    seen: set[_Value] = set()
    for value in values:
        candidates = value.value if value.kind == "alternatives" else (value,)
        for candidate in candidates:
            if budget is not None and not budget.consume_resolution():
                return _UNKNOWN
            if candidate in seen:
                continue
            if len(unique) >= MAX_BRANCH_ALTERNATIVES:
                if budget is not None:
                    budget.exhausted = True
                return _UNKNOWN
            unique.append(candidate)
            seen.add(candidate)
    if not unique:
        return _UNKNOWN
    if len(unique) == 1:
        return unique[0]
    return _Value("alternatives", tuple(unique))


@dataclass
class _State:
    modules: dict[str, str]
    functions: dict[str, tuple[str, str]]
    constructors: dict[str, str]
    auth_constructors: set[str]
    values: dict[str, _Value]
    instances: dict[str, str]
    shadowed: set[str]
    budget: _AnalysisBudget

    def fork(self) -> "_State":
        entry_count = (
            len(self.modules)
            + len(self.functions)
            + len(self.constructors)
            + len(self.auth_constructors)
            + len(self.values)
            + len(self.instances)
            + len(self.shadowed)
        )
        if not self.budget.consume_snapshot_entries(entry_count):
            return _State({}, {}, {}, set(), {}, {}, set(), self.budget)
        return _State(
            modules=dict(self.modules),
            functions=dict(self.functions),
            constructors=dict(self.constructors),
            auth_constructors=set(self.auth_constructors),
            values=dict(self.values),
            instances=dict(self.instances),
            shadowed=set(self.shadowed),
            budget=self.budget,
        )


def _normalized_name(name: str) -> str:
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.casefold().replace("-", "_").replace(" ", "_")


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().casefold()
    normalized = re.sub(r"^(?:bearer|basic|token)\s+", "", normalized)
    return (
        normalized in _PLACEHOLDERS
        or (normalized.startswith("<") and normalized.endswith(">"))
        or normalized.startswith(("your_", "your-", "your "))
        or re.fullmatch(r"\$[a-z_][a-z0-9_]*|\$\{[a-z_][a-z0-9_]*\}", normalized)
        is not None
        or re.fullmatch(r"\{\{\s*[a-z_][a-z0-9_]*\s*}}", normalized) is not None
    )


def _dotted_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _expanded_name(node: ast.AST, state: _State) -> Optional[str]:
    name = _dotted_name(node)
    if not name:
        return None
    root, separator, suffix = name.partition(".")
    if root in state.shadowed:
        return None
    module = state.modules.get(root)
    if module:
        return module + (f".{suffix}" if separator else "")
    return name


def _module_family(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    for module in _SUPPORTED_MODULES:
        if name == module or name.startswith(module + "."):
            return module
    if name.startswith("urllib."):
        return "urllib.request"
    return None


def _shadow_aliases(name: str, state: _State, *, clear_instance: bool = False) -> None:
    """Remove import/value bindings when Python reuses a name."""
    state.modules.pop(name, None)
    state.functions.pop(name, None)
    state.constructors.pop(name, None)
    state.auth_constructors.discard(name)
    state.values.pop(name, None)
    state.shadowed.add(name)
    if clear_instance:
        state.instances.pop(name, None)


def _target_name(node: ast.AST) -> Optional[str]:
    return _dotted_name(node)


def _resolve_value(node: ast.AST, state: _State, depth: int = 0) -> _Value:
    budget = state.budget
    if budget.exhausted:
        return _UNKNOWN
    if depth > MAX_RESOLUTION_DEPTH:
        budget.exhausted = True
        return _UNKNOWN
    if not budget.consume_resolution():
        return _UNKNOWN
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            if len(node.value) > MAX_RESOLVED_STRING_CHARS:
                budget.exhausted = True
                return _UNKNOWN
            return _Value("literal", node.value)
        if isinstance(node.value, bytes):
            if len(node.value) > MAX_RESOLVED_STRING_CHARS:
                budget.exhausted = True
                return _UNKNOWN
            try:
                return _Value("literal", node.value.decode("ascii"))
            except UnicodeDecodeError:
                return _UNKNOWN
        return _UNKNOWN
    if isinstance(node, ast.Name):
        return state.values.get(node.id, _UNKNOWN)
    if isinstance(node, (ast.Tuple, ast.List)):
        items = []
        for item in node.elts:
            if budget.is_exhausted():
                return _UNKNOWN
            items.append(_resolve_value(item, state, depth + 1))
        return _Value("sequence", tuple(items))
    if isinstance(node, ast.Dict):
        entries = []
        for dictionary_key, dictionary_value in zip(node.keys, node.values):
            if budget.is_exhausted():
                return _UNKNOWN
            resolved_key = (
                _resolve_value(dictionary_key, state, depth + 1)
                if dictionary_key
                else _UNKNOWN
            )
            key_value = (
                resolved_key.value
                if resolved_key.kind == "literal"
                and isinstance(resolved_key.value, str)
                else None
            )
            entries.append(
                (key_value, _resolve_value(dictionary_value, state, depth + 1))
            )
        return _Value("mapping", tuple(entries))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve_value(node.left, state, depth + 1)
        right = _resolve_value(node.right, state, depth + 1)
        if budget.is_exhausted():
            return _UNKNOWN
        if left.kind == right.kind == "literal":
            value_length = len(left.value) + len(right.value)
            if not budget.consume_string_chars(value_length):
                return _UNKNOWN
            return _Value("literal", left.value + right.value)
        if left.kind == "reference" or right.kind == "reference":
            return _REFERENCE
        return _UNKNOWN
    if isinstance(node, ast.JoinedStr):
        parts = []
        total_length = 0
        for item in node.values:
            if budget.is_exhausted():
                return _UNKNOWN
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                total_length += len(item.value)
                if total_length > MAX_RESOLVED_STRING_CHARS:
                    budget.exhausted = True
                    return _UNKNOWN
                parts.append(item.value)
                continue
            if isinstance(item, ast.FormattedValue):
                resolved = _resolve_value(item.value, state, depth + 1)
                if budget.is_exhausted():
                    return _UNKNOWN
                if resolved.kind == "literal":
                    part = str(resolved.value)
                    total_length += len(part)
                    if total_length > MAX_RESOLVED_STRING_CHARS:
                        budget.exhausted = True
                        return _UNKNOWN
                    parts.append(part)
                    continue
                return _REFERENCE if resolved.kind == "reference" else _UNKNOWN
            return _UNKNOWN
        if not budget.consume_string_chars(total_length):
            return _UNKNOWN
        return _Value("literal", "".join(parts))
    if isinstance(node, ast.Subscript):
        container = _resolve_value(node.value, state, depth + 1)
        subscript_key = _resolve_value(node.slice, state, depth + 1)
        if budget.is_exhausted():
            return _UNKNOWN
        if container.kind == "mapping" and subscript_key.kind == "literal":
            for entry_key, entry_value in container.value:
                if not budget.consume_container():
                    return _UNKNOWN
                if entry_key == subscript_key.value:
                    return entry_value
            return _UNKNOWN
        return _REFERENCE
    if isinstance(node, ast.Call):
        if _is_auth_constructor(node, state):
            password = next(
                (
                    keyword.value
                    for keyword in node.keywords
                    if keyword.arg in {"password", "passwd"}
                ),
                node.args[1] if len(node.args) > 1 else None,
            )
            if password is not None:
                return _Value(
                    "authentication",
                    _resolve_value(password, state, depth + 1),
                )
            return _UNKNOWN
        return _REFERENCE
    if isinstance(node, ast.IfExp):
        left = _resolve_value(node.body, state, depth + 1)
        right = _resolve_value(node.orelse, state, depth + 1)
        if budget.is_exhausted():
            return _UNKNOWN
        return _alternatives((left, right), budget)
    return _UNKNOWN


def _register_import(node: ast.AST, state: _State) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            module = alias.name
            bound = alias.asname or module.split(".", 1)[0]
            _shadow_aliases(bound, state, clear_instance=True)
            if module in _SUPPORTED_MODULES or module.startswith("urllib."):
                state.shadowed.discard(bound)
                state.modules[bound] = module if alias.asname else bound
    elif isinstance(node, ast.ImportFrom) and node.module:
        module = node.module
        for alias in node.names:
            _shadow_aliases(alias.asname or alias.name, state, clear_instance=True)
        if module in _SUPPORTED_MODULES or module in {
            "requests.auth",
            "urllib",
        }:
            for alias in node.names:
                bound = alias.asname or alias.name
                full_name = f"{module}.{alias.name}"
                family = _module_family(full_name)
                if alias.name in _REQUEST_METHODS and family in {"requests", "httpx"}:
                    state.shadowed.discard(bound)
                    state.functions[bound] = (family, alias.name)
                elif alias.name == "request" and family == "aiohttp":
                    state.shadowed.discard(bound)
                    state.functions[bound] = (family, alias.name)
                elif alias.name == "urlopen" and family == "urllib.request":
                    state.shadowed.discard(bound)
                    state.functions[bound] = (family, alias.name)
                elif full_name in _REQUEST_CONSTRUCTORS:
                    state.shadowed.discard(bound)
                    state.constructors[bound] = full_name
                elif full_name in _CLIENT_CONSTRUCTORS:
                    state.shadowed.discard(bound)
                    state.constructors[bound] = full_name
                elif full_name in _AUTH_CONSTRUCTORS or alias.name in {
                    "HTTPBasicAuth",
                    "BasicAuth",
                }:
                    state.shadowed.discard(bound)
                    state.auth_constructors.add(bound)
                elif module == "urllib.request" and alias.name == "Request":
                    state.shadowed.discard(bound)
                    state.constructors[bound] = "urllib.request"
                elif module == "urllib" and alias.name == "request":
                    state.shadowed.discard(bound)
                    state.modules[bound] = "urllib.request"


def _expanded_function_name(node: ast.AST, state: _State) -> Optional[str]:
    if isinstance(node, ast.Name):
        if node.id in state.functions:
            family, function = state.functions[node.id]
            return f"{family}.{function}"
        if node.id in state.constructors:
            return state.constructors[node.id]
    name = _expanded_name(node, state)
    if name:
        return name
    return None


def _instance_receiver(node: ast.AST, state: _State) -> Optional[str]:
    target = _target_name(node)
    if target and target in state.instances:
        return state.instances[target]
    if isinstance(node, ast.Call):
        name = _expanded_function_name(node.func, state)
        return _CLIENT_CONSTRUCTORS.get(name or "")
    return None


def _request_call(node: ast.Call, state: _State) -> Optional[str]:
    name = _expanded_function_name(node.func, state)
    request_client = _REQUEST_CONSTRUCTORS.get(name or "")
    if request_client is not None:
        return request_client
    family = _module_family(name)
    if family and name:
        method = name.rsplit(".", 1)[-1]
        if method in _REQUEST_METHODS or (
            family == "urllib.request" and method == "urlopen"
        ):
            return family
    if isinstance(node.func, ast.Attribute) and node.func.attr in _REQUEST_METHODS:
        return _instance_receiver(node.func.value, state)
    return None


def _is_auth_constructor(node: ast.Call, state: _State) -> bool:
    name = _expanded_function_name(node.func, state)
    return name in _AUTH_CONSTRUCTORS or (
        isinstance(node.func, ast.Name) and node.func.id in state.auth_constructors
    )


class _Analyzer:
    def __init__(self) -> None:
        self.budget = _AnalysisBudget()
        self.findings: list[HttpRequestCredentialFinding] = []
        self._seen: set[HttpRequestCredentialFinding] = set()
        self.incomplete = False
        self.pending_scopes: list[tuple[list[ast.stmt], _State]] = []

    def add(self, node: ast.AST, client: str, sink: str, finding_class: str) -> None:
        line_number = getattr(node, "lineno", None)
        finding = HttpRequestCredentialFinding(
            line_number=line_number if type(line_number) is int else None,
            client=client,
            sink=sink,
            finding_class=finding_class,
        )
        if finding in self._seen:
            return
        self._seen.add(finding)
        if len(self.findings) < MAX_FINDINGS - 1:
            self.findings.append(finding)
        elif finding_class == INCOMPLETE_ANALYSIS:
            self.findings.append(finding)
        else:
            self.incomplete = True
            incomplete = HttpRequestCredentialFinding(
                None, "unknown", "unknown", INCOMPLETE_ANALYSIS
            )
            if incomplete not in self._seen:
                self._seen.add(incomplete)
                self.findings.append(incomplete)

    def _check_literal(self, value: _Value, node: ast.AST, client: str, sink: str):
        if value.kind == "literal" and isinstance(value.value, str):
            if not self.budget.consume_string_chars(len(value.value)):
                return
            if not _is_placeholder(value.value):
                self.add(node, client, sink, INLINE_LITERAL)

    def _check_sensitive_value(
        self,
        value: _Value,
        node: ast.AST,
        client: str,
        sink: str,
        *,
        depth: int = 0,
    ) -> None:
        if self.budget.is_exhausted():
            return
        if depth > MAX_RESOLUTION_DEPTH:
            self.budget.exhausted = True
            return
        if not self.budget.consume_container():
            return
        if value.kind == "literal":
            self._check_literal(value, node, client, sink)
        elif value.kind == "alternatives":
            for item in value.value:
                if self.budget.is_exhausted():
                    return
                self._check_sensitive_value(item, node, client, sink, depth=depth + 1)
        elif value.kind == "sequence":
            for item in value.value:
                if self.budget.is_exhausted():
                    return
                if not self.budget.consume_container():
                    return
                self._check_sensitive_value(item, node, client, sink, depth=depth + 1)
        elif value.kind == "mapping":
            for key, item in value.value:
                if self.budget.is_exhausted():
                    return
                if not self.budget.consume_container():
                    return
                if key is not None and _normalized_name(key) in _CREDENTIAL_FIELDS:
                    self._check_sensitive_value(
                        item,
                        node,
                        client,
                        self._field_sink(key),
                        depth=depth + 1,
                    )
                elif key is not None:
                    self._check_sensitive_value(
                        item, node, client, sink, depth=depth + 1
                    )

    def _scan_credential_fields(
        self,
        value: _Value,
        node: ast.AST,
        client: str,
        *,
        depth: int = 0,
    ) -> None:
        """Search request data for explicitly credential-named fields only."""
        if self.budget.is_exhausted():
            return
        if depth > MAX_RESOLUTION_DEPTH:
            self.budget.exhausted = True
            return
        if value.kind not in {"mapping", "sequence", "alternatives"}:
            return
        if not self.budget.consume_container():
            return
        if value.kind == "alternatives":
            for item in value.value:
                if self.budget.is_exhausted():
                    return
                self._scan_credential_fields(item, node, client, depth=depth + 1)
        elif value.kind == "mapping":
            for key, item in value.value:
                if self.budget.is_exhausted():
                    return
                if not self.budget.consume_container():
                    return
                if key is None:
                    continue
                if _normalized_name(key) in _CREDENTIAL_FIELDS:
                    self._check_sensitive_value(
                        item,
                        node,
                        client,
                        self._field_sink(key),
                        depth=depth + 1,
                    )
                elif item.kind in {"mapping", "sequence", "alternatives"}:
                    self._scan_credential_fields(item, node, client, depth=depth + 1)
        elif value.kind == "sequence":
            for item in value.value:
                if self.budget.is_exhausted():
                    return
                if not self.budget.consume_container():
                    return
                self._scan_credential_fields(item, node, client, depth=depth + 1)

    @staticmethod
    def _field_sink(key: str) -> str:
        normalized = _normalized_name(key)
        if "password" in normalized or normalized in {"passwd", "pwd"}:
            return "password_field"
        if "token" in normalized:
            return "token_field"
        if "api_key" in normalized or normalized == "apikey":
            return "api_key_field"
        if "secret" in normalized:
            return "secret_field"
        return "credential_field"

    def _scan_auth(self, node: ast.AST, state: _State, client: str) -> None:
        value = _resolve_value(node, state)
        if value.kind == "authentication":
            self._check_sensitive_value(value.value, node, client, "authentication")
        else:
            self._scan_auth_value(value, node, client)

    def _scan_auth_value(self, value: _Value, node: ast.AST, client: str) -> None:
        if self.budget.is_exhausted():
            return
        if not self.budget.consume_container():
            return
        if value.kind == "authentication":
            self._check_sensitive_value(value.value, node, client, "authentication")
        elif value.kind == "alternatives":
            for item in value.value:
                if self.budget.is_exhausted():
                    return
                self._scan_auth_value(item, node, client)
        elif value.kind == "sequence":
            parts = value.value
            if len(parts) > 1:
                self._check_sensitive_value(
                    parts[1], node, client, "authentication", depth=1
                )
        else:
            self._check_literal(value, node, client, "authentication")

    def _scan_headers(self, node: ast.AST, state: _State, client: str) -> None:
        self._scan_headers_value(_resolve_value(node, state), node, client)

    def _scan_headers_value(self, value: _Value, node: ast.AST, client: str) -> None:
        if self.budget.is_exhausted():
            return
        if value.kind not in {"sequence", "mapping", "alternatives"}:
            return
        if not self.budget.consume_container():
            return
        if value.kind == "alternatives":
            for item in value.value:
                if self.budget.is_exhausted():
                    return
                self._scan_headers_value(item, node, client)
            return
        if value.kind == "sequence":
            for pair in value.value:
                if self.budget.is_exhausted():
                    return
                if not self.budget.consume_container():
                    return
                if pair.kind != "sequence" or len(pair.value) != 2:
                    continue
                key, item = pair.value
                if key.kind != "literal" or not isinstance(key.value, str):
                    continue
                normalized = key.value.casefold().strip()
                if normalized in _AUTH_HEADERS:
                    sink = self._header_sink(normalized)
                    self._check_sensitive_value(item, node, client, sink)
            return
        if value.kind != "mapping":
            return
        for key, item in value.value:
            if self.budget.is_exhausted():
                return
            if not self.budget.consume_container():
                return
            if key is None or key.casefold().strip() not in _AUTH_HEADERS:
                continue
            normalized = key.casefold().strip()
            sink = self._header_sink(normalized)
            self._check_sensitive_value(item, node, client, sink)

    @staticmethod
    def _header_sink(normalized: str) -> str:
        if "api-key" in normalized or normalized == "api-key":
            return "api_key_header"
        if normalized == "cookie":
            return "cookie_header"
        return "authorization_header"

    def _scan_request_options(self, call: ast.Call, state: _State, client: str) -> None:
        for keyword in call.keywords:
            if self.budget.is_exhausted():
                return
            name = keyword.arg.casefold() if isinstance(keyword.arg, str) else None
            if name is None:
                expanded = _resolve_value(keyword.value, state)
                if expanded.kind != "mapping":
                    continue
                for key, value in expanded.value:
                    if self.budget.is_exhausted():
                        return
                    if not self.budget.consume_container():
                        return
                    if key == "auth":
                        self._scan_auth_value(value, keyword.value, client)
                    elif key == "headers":
                        self._scan_headers_value(value, keyword.value, client)
                    elif key in {"data", "json", "params"}:
                        self._scan_credential_fields(value, keyword.value, client)
            elif name == "auth":
                self._scan_auth(keyword.value, state, client)
            elif name == "headers":
                self._scan_headers(keyword.value, state, client)
            elif name in {"data", "json", "params"}:
                self._scan_credential_fields(
                    _resolve_value(keyword.value, state),
                    keyword.value,
                    client,
                )

    def _scan_request_url(self, call: ast.Call, state: _State, client: str) -> None:
        name = _expanded_function_name(call.func, state) or ""
        leaf = (
            call.func.attr
            if isinstance(call.func, ast.Attribute)
            else name.rsplit(".", 1)[-1]
        )
        if leaf == "Request":
            index = 0 if client == "urllib.request" else 1
        elif leaf == "request":
            index = 1
        else:
            index = 0
        value_node = next(
            (keyword.value for keyword in call.keywords if keyword.arg == "url"),
            call.args[index] if len(call.args) > index else None,
        )
        if value_node is None:
            return
        value = _resolve_value(value_node, state)
        self._scan_url_value(value, value_node, client)

    def _scan_url_value(
        self, value: _Value, value_node: ast.AST, client: str, depth: int = 0
    ) -> None:
        if self.budget.is_exhausted():
            return
        if depth > MAX_RESOLUTION_DEPTH:
            self.budget.exhausted = True
            return
        if value.kind == "alternatives":
            for item in value.value:
                if self.budget.is_exhausted():
                    return
                if not self.budget.consume_container():
                    return
                self._scan_url_value(item, value_node, client, depth + 1)
            return
        if value.kind != "literal" or not isinstance(value.value, str):
            return
        if len(value.value) > MAX_URL_CHARS:
            self.budget.exhausted = True
            return
        query_length = len(value.value.partition("?")[2])
        if not self.budget.consume_url_parse_chars(len(value.value) + query_length):
            return
        try:
            parsed = urlsplit(value.value)
        except ValueError:
            return
        if parsed.scheme.casefold() not in {"http", "https", "ws", "wss"}:
            return
        username = unquote(parsed.username) if parsed.username is not None else None
        password = unquote(parsed.password) if parsed.password is not None else None
        if (username is not None and not _is_placeholder(username)) or (
            password is not None and not _is_placeholder(password)
        ):
            self.add(value_node, client, "url_userinfo", INLINE_LITERAL)
        try:
            query_fields = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                max_num_fields=MAX_CONTAINER_TRAVERSAL,
            )
        except ValueError:
            self.budget.exhausted = True
            return
        for key, query_value in query_fields:
            if not self.budget.consume_container():
                return
            if _normalized_name(key) not in _CREDENTIAL_FIELDS:
                continue
            self._check_literal(
                _Value("literal", query_value),
                value_node,
                client,
                self._field_sink(key),
            )

    def _scan_call(self, call: ast.Call, state: _State) -> None:
        client = _request_call(call, state)
        name = _expanded_function_name(call.func, state)
        constructor_family = _CLIENT_CONSTRUCTORS.get(name or "")
        request_client = _REQUEST_CONSTRUCTORS.get(name or "")
        self._scan_session_header_update(call, state)
        if client:
            self._scan_request_url(call, state, client)
            self._scan_request_options(call, state, client)
        elif request_client is not None:
            self._scan_request_url(call, state, request_client)
            self._scan_request_options(call, state, request_client)
        elif constructor_family:
            self._scan_request_options(
                call,
                state,
                constructor_family,
            )

    def _scan_session_header_update(self, call: ast.Call, state: _State) -> None:
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "update":
            return
        headers = call.func.value
        if (
            not isinstance(headers, ast.Attribute)
            or headers.attr.casefold() != "headers"
        ):
            return
        receiver = _target_name(headers.value)
        client = state.instances.get(receiver or "")
        if not client:
            return
        if call.args:
            self._scan_headers(call.args[0], state, client)
        if call.keywords:
            entries = tuple(
                (
                    keyword.arg,
                    _resolve_value(keyword.value, state),
                )
                for keyword in call.keywords
                if isinstance(keyword.arg, str)
            )
            self._scan_headers_value(_Value("mapping", entries), call, client)

    def _scan_header_subscript_assignment(
        self, target: ast.AST, value: ast.AST, state: _State
    ) -> None:
        if not isinstance(target, ast.Subscript) or not isinstance(
            target.value, ast.Attribute
        ):
            return
        headers = target.value
        if headers.attr.casefold() != "headers":
            return
        receiver = _target_name(headers.value)
        client = state.instances.get(receiver or "")
        key = _resolve_value(target.slice, state)
        if (
            not client
            or key.kind != "literal"
            or not isinstance(key.value, str)
            or key.value.casefold().strip() not in _AUTH_HEADERS
        ):
            return
        normalized = key.value.casefold().strip()
        sink = self._header_sink(normalized)
        self._check_sensitive_value(_resolve_value(value, state), value, client, sink)

    def _scan_session_assignment(self, target: ast.AST, value: ast.AST, state: _State):
        target_name = _target_name(target)
        if not target_name:
            return
        constructor = (
            _expanded_function_name(value.func, state)
            if isinstance(value, ast.Call)
            else None
        )
        family = _CLIENT_CONSTRUCTORS.get(constructor or "")
        if family:
            state.instances[target_name] = family
            return
        if isinstance(value, ast.Name) or isinstance(value, ast.Attribute):
            source_name = _target_name(value)
            if source_name in state.instances:
                state.instances[target_name] = state.instances[source_name]
                return
        state.instances.pop(target_name, None)

        if isinstance(target, ast.Attribute) and target.attr.casefold() in {
            "auth",
            "headers",
        }:
            receiver = _target_name(target.value)
            client = state.instances.get(receiver or "")
            if client:
                if target.attr.casefold() == "auth":
                    self._scan_auth(value, state, client)
                else:
                    self._scan_headers(value, state, client)

    @staticmethod
    def _shadow_function_parameters(arguments: ast.arguments, state: _State) -> None:
        parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        if arguments.vararg is not None:
            parameters.append(arguments.vararg)
        if arguments.kwarg is not None:
            parameters.append(arguments.kwarg)
        for parameter in parameters:
            _shadow_aliases(parameter.arg, state, clear_instance=True)

    @staticmethod
    def _merge_state(target: _State, branches: list[_State]) -> None:
        if not branches:
            return

        def possible_mapping(attribute: str) -> dict[Any, Any]:
            mappings = [getattr(branch, attribute) for branch in branches]
            entry_count = sum(len(mapping) for mapping in mappings)
            if not target.budget.consume_resolution(max(1, entry_count)):
                return {}
            names = set().union(*(set(mapping) for mapping in mappings))
            possible: dict[Any, Any] = {}
            for name in names:
                for mapping in mappings:
                    if not target.budget.consume_resolution():
                        return possible
                    if name in mapping:
                        # Any branch may be taken at runtime. Preserve a known
                        # supported binding rather than losing it at the merge.
                        possible[name] = mapping[name]
                        break
            return possible

        target.modules = possible_mapping("modules")
        target.functions = possible_mapping("functions")
        target.constructors = possible_mapping("constructors")
        auth_entries = sum(len(branch.auth_constructors) for branch in branches)
        shadowed_entries = sum(len(branch.shadowed) for branch in branches)
        if target.budget.consume_resolution(max(1, auth_entries)):
            target.auth_constructors = set().union(
                *(set(branch.auth_constructors) for branch in branches)
            )
        else:
            target.auth_constructors = set()
        if target.budget.consume_resolution(max(1, shadowed_entries)):
            target.shadowed = set().union(
                *(set(branch.shadowed) for branch in branches)
            )
        else:
            target.shadowed = set()
        target.shadowed.difference_update(
            target.modules,
            target.functions,
            target.constructors,
            target.auth_constructors,
        )

        value_entries = sum(len(branch.values) for branch in branches)
        if not target.budget.consume_resolution(max(1, value_entries)):
            target.values = {}
            target.instances = {}
            return
        names = set().union(*(set(branch.values) for branch in branches))
        merged_values = {}
        for name in names:
            candidates = []
            for branch in branches:
                if not target.budget.consume_resolution():
                    break
                candidates.append(branch.values.get(name, _UNKNOWN))
            if target.budget.is_exhausted():
                break
            value = _alternatives(tuple(candidates), target.budget)
            if value.kind != "unknown":
                merged_values[name] = value
        target.values = merged_values

        instance_entries = sum(len(branch.instances) for branch in branches)
        if not target.budget.consume_resolution(max(1, instance_entries)):
            target.instances = {}
            return
        instance_names = set().union(*(set(branch.instances) for branch in branches))
        merged_instances = {}
        for name in instance_names:
            if not target.budget.consume_resolution():
                break
            families = set()
            for branch in branches:
                if not target.budget.consume_resolution():
                    break
                if name in branch.instances:
                    families.add(branch.instances[name])
            if target.budget.is_exhausted():
                break
            if len(families) == 1:
                merged_instances[name] = next(iter(families))
        target.instances = merged_instances

    def _scan_expr(self, node: ast.AST, state: _State) -> None:
        if self.budget.is_exhausted():
            return
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
        ):
            return
        if isinstance(node, ast.Call):
            self._scan_call(node, state)
        for child in ast.iter_child_nodes(node):
            if self.budget.is_exhausted():
                return
            self._scan_expr(child, state)

    def _process_suite(self, statements: list[ast.stmt], state: _State) -> None:
        for statement in statements:
            if self.budget.is_exhausted():
                return
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                _register_import(statement, state)
                continue

            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for expression in [
                    *statement.decorator_list,
                    *statement.args.defaults,
                    *statement.args.kw_defaults,
                ]:
                    if expression is not None:
                        self._scan_expr(expression, state)
                function_state = state.fork()
                _shadow_aliases(statement.name, function_state, clear_instance=True)
                self._shadow_function_parameters(statement.args, function_state)
                self.pending_scopes.append((statement.body, function_state))
                _shadow_aliases(statement.name, state, clear_instance=True)
                continue

            if isinstance(statement, ast.ClassDef):
                class_expressions: list[ast.AST] = [
                    *statement.decorator_list,
                    *statement.bases,
                    *statement.keywords,
                ]
                for class_expression in class_expressions:
                    self._scan_expr(class_expression, state)
                self.pending_scopes.append((statement.body, state.fork()))
                _shadow_aliases(statement.name, state, clear_instance=True)
                continue

            if isinstance(statement, ast.Assign):
                self._scan_expr(statement.value, state)
                resolved = _resolve_value(statement.value, state)
                for target in statement.targets:
                    self._scan_session_assignment(target, statement.value, state)
                    self._scan_header_subscript_assignment(
                        target, statement.value, state
                    )
                    if isinstance(target, ast.Name):
                        _shadow_aliases(target.id, state)
                    name = _target_name(target)
                    if name and isinstance(target, ast.Name):
                        state.values[name] = resolved
                continue

            if isinstance(statement, ast.AnnAssign):
                if statement.value is not None:
                    self._scan_expr(statement.value, state)
                    resolved = _resolve_value(statement.value, state)
                    self._scan_session_assignment(
                        statement.target, statement.value, state
                    )
                    self._scan_header_subscript_assignment(
                        statement.target, statement.value, state
                    )
                    name = _target_name(statement.target)
                    if name and isinstance(statement.target, ast.Name):
                        _shadow_aliases(name, state)
                        state.values[name] = resolved
                continue

            if isinstance(statement, ast.AugAssign):
                self._scan_expr(statement.value, state)
                name = _target_name(statement.target)
                if name:
                    _shadow_aliases(name, state, clear_instance=True)
                continue

            if isinstance(statement, ast.If):
                self._scan_expr(statement.test, state)
                body_state = state.fork()
                self._process_suite(statement.body, body_state)
                branches = [body_state]
                if statement.orelse:
                    else_state = state.fork()
                    self._process_suite(statement.orelse, else_state)
                    branches.append(else_state)
                else:
                    branches.append(state.fork())
                self._merge_state(state, branches)
                continue

            if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                self._scan_expr(
                    (
                        statement.iter
                        if isinstance(statement, (ast.For, ast.AsyncFor))
                        else statement.test
                    ),
                    state,
                )
                body_state = state.fork()
                self._process_suite(statement.body, body_state)
                else_state = state.fork()
                self._process_suite(statement.orelse, else_state)
                self._merge_state(state, [state.fork(), body_state, else_state])
                continue

            if isinstance(statement, (ast.With, ast.AsyncWith)):
                for item in statement.items:
                    self._scan_expr(item.context_expr, state)
                    if item.optional_vars is not None:
                        self._scan_session_assignment(
                            item.optional_vars, item.context_expr, state
                        )
                        if isinstance(item.optional_vars, ast.Name):
                            _shadow_aliases(item.optional_vars.id, state)
                self._process_suite(statement.body, state)
                continue

            if isinstance(statement, ast.Try):
                try_state = state.fork()
                self._process_suite(statement.body, try_state)
                self._process_suite(statement.orelse, try_state)
                branches = [try_state]
                for handler in statement.handlers:
                    handler_state = state.fork()
                    if handler.type:
                        self._scan_expr(handler.type, handler_state)
                    self._process_suite(handler.body, handler_state)
                    branches.append(handler_state)
                self._merge_state(state, branches)
                self._process_suite(statement.finalbody, state)
                continue

            if isinstance(statement, ast.Match):
                self._scan_expr(statement.subject, state)
                branches = [state.fork()]
                for case in statement.cases:
                    case_state = state.fork()
                    if case.guard:
                        self._scan_expr(case.guard, case_state)
                    self._process_suite(case.body, case_state)
                    branches.append(case_state)
                self._merge_state(state, branches)
                continue

            self._scan_expr(statement, state)

    def analyze(self, source: str) -> HttpRequestCredentialAnalysis:
        if not isinstance(source, str) or not source:
            return HttpRequestCredentialAnalysis()
        if len(source) > MAX_SOURCE_CHARS:
            return self._incomplete_if_relevant(source)
        try:
            tree = ast.parse(source, mode="exec")
            for node_count, _ in enumerate(ast.walk(tree), start=1):
                if node_count > MAX_AST_NODES:
                    return self._incomplete_if_relevant(source)
        except (SyntaxError, ValueError, TypeError, RecursionError):
            return self._incomplete_if_relevant(source)

        state = _State({}, {}, {}, set(), {}, {}, set(), self.budget)
        self._process_suite(tree.body, state)
        index = 0
        while index < len(self.pending_scopes) and not self.budget.is_exhausted():
            body, outer_state = self.pending_scopes[index]
            index += 1
            self._process_suite(body, outer_state)
        if self.budget.is_exhausted():
            return self._incomplete_if_relevant(source)
        return HttpRequestCredentialAnalysis(tuple(self.findings), self.incomplete)

    def _incomplete_if_relevant(self, source: str) -> HttpRequestCredentialAnalysis:
        if not _has_relevant_source(source):
            return HttpRequestCredentialAnalysis(tuple(self.findings), self.incomplete)
        self.incomplete = True
        self.add(
            ast.Module(body=[], type_ignores=[]),
            "unknown",
            "unknown",
            INCOMPLETE_ANALYSIS,
        )
        return HttpRequestCredentialAnalysis(tuple(self.findings), True)


def analyze_http_request_credentials(source: str) -> HttpRequestCredentialAnalysis:
    """Analyze supported request sinks without evaluating Python source."""
    try:
        return _Analyzer().analyze(source)
    except (TypeError, ValueError, IndexError, RecursionError):
        logger.warning("HTTP request credential analysis failed; source withheld")
        return HttpRequestCredentialAnalysis(
            (
                HttpRequestCredentialFinding(
                    None, "unknown", "unknown", INCOMPLETE_ANALYSIS
                ),
            ),
            incomplete=True,
        )


def _effective_action(config: object) -> str:
    action = config.get("action", "block") if isinstance(config, dict) else "block"
    return action if isinstance(action, str) and action in _VALID_ACTIONS else "block"


def _scan_result(
    analysis: HttpRequestCredentialAnalysis, action: str, file_path: str
) -> Optional[ScanResult]:
    if not analysis.findings:
        return None
    inline = any(item.finding_class == INLINE_LITERAL for item in analysis.findings)
    incomplete = any(
        item.finding_class == INCOMPLETE_ANALYSIS for item in analysis.findings
    )
    should_block = (inline or incomplete) and action in {"block", "ask"}
    if inline:
        severity = "high"
        message = {
            "block": BLOCK_MESSAGE,
            "ask": ASK_MESSAGE,
            "warn": WARN_MESSAGE,
            "log-only": "",
        }[action]
    else:
        severity = "medium"
        message = (
            INCOMPLETE_MESSAGE + " The configured action blocks this write."
            if action == "block"
            else (
                INCOMPLETE_MESSAGE + " Approve Once allows this write only."
                if action == "ask"
                else (
                    INCOMPLETE_MESSAGE
                    + " The configured warn action allows this write."
                    if action == "warn"
                    else ""
                )
            )
        )
    return ScanResult(
        detected=True,
        violation_type=VIOLATION_TYPE,
        should_block=should_block,
        severity=severity,
        rule_id=RULE_ID,
        error_message=message,
        engine=ENGINE,
        config_section=CONFIG_SECTION,
        file_path=file_path,
        total_findings=len(analysis.findings),
        line_number=next(
            (
                finding.line_number
                for finding in analysis.findings
                if finding.line_number
            ),
            None,
        ),
        findings=[asdict(item) for item in analysis.findings],
        matched_text="",
        matched_pattern="",
        extra={
            "action": action,
            "analysis_incomplete": incomplete,
            "finding_classes": sorted(
                {finding.finding_class for finding in analysis.findings}
            ),
        },
    )


def run_http_request_credential_scan(
    source: str,
    *,
    file_path: Optional[str] = None,
    config: Optional[dict] = None,
    **_kwargs,
) -> Optional[ScanResult]:
    """Return a value-free finding for supported Python source request sinks."""
    if not isinstance(file_path, str) or PurePath(file_path).suffix.casefold() != ".py":
        return None
    analysis = analyze_http_request_credentials(source)
    if not analysis.findings:
        return None
    if config is None:
        from ai_guardian.config.loaders import (
            _load_http_request_credential_scanning_config,
        )

        config, _ = _load_http_request_credential_scanning_config()
    if isinstance(config, dict) and config.get("enabled") is False:
        return None
    return _scan_result(analysis, _effective_action(config), file_path)
