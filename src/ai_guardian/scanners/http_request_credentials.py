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
_RELEVANT_SOURCE = re.compile(
    r"(?is)\b(?:requests|httpx|aiohttp|urllib(?:\.request)?)\b"
    r".{0,4096}\b(?:auth|headers?|authorization|x-api-key|password|passwd|"
    r"token|secret|api[_-]?key|credential)\b"
    r"|\b(?:auth|headers?|authorization|x-api-key|password|passwd|token|secret|"
    r"api[_-]?key|credential)\b.{0,4096}"
    r"\b(?:requests|httpx|aiohttp|urllib(?:\.request)?)\b"
)


def _has_relevant_source(source: str) -> bool:
    """Search bounded overlapping chunks so oversized suffixes fail closed."""
    if len(source) <= MAX_SOURCE_CHARS:
        return _RELEVANT_SOURCE.search(source) is not None
    overlap = 4096
    stride = MAX_SOURCE_CHARS - overlap
    return any(
        _RELEVANT_SOURCE.search(source[start : start + MAX_SOURCE_CHARS]) is not None
        for start in range(0, len(source), stride)
    )


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
class _State:
    modules: dict[str, str]
    functions: dict[str, tuple[str, str]]
    constructors: dict[str, str]
    auth_constructors: set[str]
    values: dict[str, _Value]
    instances: dict[str, str]

    def fork(self) -> "_State":
        return _State(
            modules=dict(self.modules),
            functions=dict(self.functions),
            constructors=dict(self.constructors),
            auth_constructors=set(self.auth_constructors),
            values=dict(self.values),
            instances=dict(self.instances),
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


def _target_name(node: ast.AST) -> Optional[str]:
    return _dotted_name(node)


def _resolve_value(node: ast.AST, state: _State, depth: int = 0) -> _Value:
    if depth > MAX_RESOLUTION_DEPTH:
        return _UNKNOWN
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return _Value("literal", node.value)
        if isinstance(node.value, bytes):
            try:
                return _Value("literal", node.value.decode("ascii"))
            except UnicodeDecodeError:
                return _UNKNOWN
        return _UNKNOWN
    if isinstance(node, ast.Name):
        return state.values.get(node.id, _UNKNOWN)
    if isinstance(node, (ast.Tuple, ast.List)):
        return _Value(
            "sequence",
            tuple(_resolve_value(item, state, depth + 1) for item in node.elts),
        )
    if isinstance(node, ast.Dict):
        entries = []
        for dictionary_key, dictionary_value in zip(node.keys, node.values):
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
        if left.kind == right.kind == "literal":
            return _Value("literal", str(left.value) + str(right.value))
        if left.kind == "reference" or right.kind == "reference":
            return _REFERENCE
        return _UNKNOWN
    if isinstance(node, ast.JoinedStr):
        parts = []
        for item in node.values:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                parts.append(item.value)
                continue
            if isinstance(item, ast.FormattedValue):
                resolved = _resolve_value(item.value, state, depth + 1)
                if resolved.kind == "literal":
                    parts.append(str(resolved.value))
                    continue
                return _REFERENCE if resolved.kind == "reference" else _UNKNOWN
            return _UNKNOWN
        return _Value("literal", "".join(parts))
    if isinstance(node, ast.Subscript):
        container = _resolve_value(node.value, state, depth + 1)
        subscript_key = _resolve_value(node.slice, state, depth + 1)
        if container.kind == "mapping" and subscript_key.kind == "literal":
            for entry_key, entry_value in container.value:
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
        return left if left == right else _UNKNOWN
    return _UNKNOWN


def _register_import(node: ast.AST, state: _State) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            module = alias.name
            if module in _SUPPORTED_MODULES or module.startswith("urllib."):
                bound = alias.asname or module.split(".", 1)[0]
                state.modules[bound] = module if alias.asname else bound
    elif isinstance(node, ast.ImportFrom) and node.module:
        module = node.module
        if module in _SUPPORTED_MODULES or module in {
            "requests.auth",
            "urllib",
        }:
            for alias in node.names:
                bound = alias.asname or alias.name
                full_name = f"{module}.{alias.name}"
                family = _module_family(full_name)
                if alias.name in _REQUEST_METHODS and family in {"requests", "httpx"}:
                    state.functions[bound] = (family, alias.name)
                elif alias.name == "request" and family == "aiohttp":
                    state.functions[bound] = (family, alias.name)
                elif alias.name == "urlopen" and family == "urllib.request":
                    state.functions[bound] = (family, alias.name)
                elif full_name in _REQUEST_CONSTRUCTORS:
                    state.constructors[bound] = full_name
                elif full_name in _CLIENT_CONSTRUCTORS:
                    state.constructors[bound] = full_name
                elif full_name in _AUTH_CONSTRUCTORS or alias.name in {
                    "HTTPBasicAuth",
                    "BasicAuth",
                }:
                    state.auth_constructors.add(bound)
                elif module == "urllib.request" and alias.name == "Request":
                    state.constructors[bound] = "urllib.request"


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
        if depth > MAX_RESOLUTION_DEPTH:
            return
        if value.kind == "literal":
            self._check_literal(value, node, client, sink)
        elif value.kind == "sequence":
            for item in value.value:
                self._check_sensitive_value(item, node, client, sink, depth=depth + 1)
        elif value.kind == "mapping":
            for key, item in value.value:
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
        if depth > MAX_RESOLUTION_DEPTH:
            return
        if value.kind == "mapping":
            for key, item in value.value:
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
                elif item.kind in {"mapping", "sequence"}:
                    self._scan_credential_fields(item, node, client, depth=depth + 1)
        elif value.kind == "sequence":
            for item in value.value:
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
            self._check_literal(value.value, node, client, "authentication")
        else:
            self._scan_auth_value(value, node, client)

    def _scan_auth_value(self, value: _Value, node: ast.AST, client: str) -> None:
        if value.kind == "sequence":
            parts = value.value
            if len(parts) > 1:
                self._check_literal(parts[1], node, client, "authentication")
        else:
            self._check_literal(value, node, client, "authentication")

    def _scan_headers(self, node: ast.AST, state: _State, client: str) -> None:
        self._scan_headers_value(_resolve_value(node, state), node, client)

    def _scan_headers_value(self, value: _Value, node: ast.AST, client: str) -> None:
        if value.kind == "sequence":
            for pair in value.value:
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
            name = keyword.arg.casefold() if isinstance(keyword.arg, str) else None
            if name is None:
                expanded = _resolve_value(keyword.value, state)
                if expanded.kind != "mapping":
                    continue
                for key, value in expanded.value:
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
        leaf = name.rsplit(".", 1)[-1]
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
        if value.kind != "literal" or not isinstance(value.value, str):
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
        for key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
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

    def _scan_expr(self, node: ast.AST, state: _State) -> None:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
        ):
            return
        if isinstance(node, ast.Call):
            self._scan_call(node, state)
        for child in ast.iter_child_nodes(node):
            self._scan_expr(child, state)

    def _process_suite(self, statements: list[ast.stmt], state: _State) -> None:
        for statement in statements:
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
                self.pending_scopes.append((statement.body, state.fork()))
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
                continue

            if isinstance(statement, ast.Assign):
                self._scan_expr(statement.value, state)
                resolved = _resolve_value(statement.value, state)
                for target in statement.targets:
                    self._scan_session_assignment(target, statement.value, state)
                    self._scan_header_subscript_assignment(
                        target, statement.value, state
                    )
                    name = _target_name(target)
                    if name and isinstance(target, ast.Name):
                        state.values[name] = resolved
                continue

            if isinstance(statement, ast.AnnAssign):
                if statement.value is not None:
                    self._scan_expr(statement.value, state)
                    self._scan_session_assignment(
                        statement.target, statement.value, state
                    )
                    self._scan_header_subscript_assignment(
                        statement.target, statement.value, state
                    )
                    name = _target_name(statement.target)
                    if name and isinstance(statement.target, ast.Name):
                        state.values[name] = _resolve_value(statement.value, state)
                continue

            if isinstance(statement, ast.AugAssign):
                self._scan_expr(statement.value, state)
                name = _target_name(statement.target)
                if name:
                    state.values.pop(name, None)
                    state.instances.pop(name, None)
                continue

            if isinstance(statement, ast.If):
                self._scan_expr(statement.test, state)
                self._process_suite(statement.body, state.fork())
                self._process_suite(statement.orelse, state.fork())
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
                self._process_suite(statement.body, state.fork())
                self._process_suite(statement.orelse, state.fork())
                continue

            if isinstance(statement, (ast.With, ast.AsyncWith)):
                for item in statement.items:
                    self._scan_expr(item.context_expr, state)
                self._process_suite(statement.body, state.fork())
                continue

            if isinstance(statement, ast.Try):
                self._process_suite(statement.body, state.fork())
                for handler in statement.handlers:
                    if handler.type:
                        self._scan_expr(handler.type, state)
                    self._process_suite(handler.body, state.fork())
                self._process_suite(statement.orelse, state.fork())
                self._process_suite(statement.finalbody, state.fork())
                continue

            if isinstance(statement, ast.Match):
                self._scan_expr(statement.subject, state)
                for case in statement.cases:
                    if case.guard:
                        self._scan_expr(case.guard, state)
                    self._process_suite(case.body, state.fork())
                continue

            self._scan_expr(statement, state)

    def analyze(self, source: str) -> HttpRequestCredentialAnalysis:
        if not isinstance(source, str) or not source:
            return HttpRequestCredentialAnalysis()
        if len(source) > MAX_SOURCE_CHARS:
            return self._incomplete_if_relevant(source)
        try:
            tree = ast.parse(source, mode="exec")
            if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
                return self._incomplete_if_relevant(source)
        except (SyntaxError, ValueError, TypeError, RecursionError):
            return self._incomplete_if_relevant(source)

        state = _State({}, {}, {}, set(), {}, {})
        self._process_suite(tree.body, state)
        index = 0
        while index < len(self.pending_scopes):
            body, outer_state = self.pending_scopes[index]
            index += 1
            self._process_suite(body, outer_state)
        return HttpRequestCredentialAnalysis(tuple(self.findings), self.incomplete)

    def _incomplete_if_relevant(self, source: str) -> HttpRequestCredentialAnalysis:
        if not _has_relevant_source(source):
            return HttpRequestCredentialAnalysis()
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
