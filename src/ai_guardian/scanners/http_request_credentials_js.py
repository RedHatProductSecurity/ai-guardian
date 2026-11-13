"""Static, value-free analysis of JavaScript and TypeScript HTTP credentials.

Tree-sitter parses source only; this module never imports or executes analyzed
code. Resolution is deliberately limited to simple values and aliases within
one lexical scope. Unsupported clients and interprocedural flows are outside
the analysis boundary.
"""

from __future__ import annotations

import importlib
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional, TypeAlias, cast
from urllib.parse import parse_qsl, unquote, urlsplit

from ai_guardian.scanners.http_request_credentials import (
    INCOMPLETE_ANALYSIS,
    INLINE_LITERAL,
    MAX_AST_NODES,
    MAX_BRANCH_ALTERNATIVES,
    MAX_CONTAINER_TRAVERSAL,
    MAX_FINDINGS,
    MAX_RESOLVED_STRING_CHARS,
    MAX_RESOLUTION_DEPTH,
    MAX_RESOLUTION_OPERATIONS,
    MAX_SOURCE_CHARS,
    MAX_STATE_SNAPSHOT_ENTRIES,
    MAX_TOTAL_RESOLVED_STRING_CHARS,
    MAX_TOTAL_URL_PARSE_CHARS,
    HttpRequestCredentialAnalysis,
    HttpRequestCredentialFinding,
)

logger = logging.getLogger(__name__)

SOURCE_EXTENSIONS = frozenset(
    {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
)

_AUTH_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
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
_HTTP_SOURCE = re.compile(
    r"(?i)\b(?:fetch|axios|XMLHttpRequest|setRequestHeader|node:(?:http|https)|"
    r"https?|new\s+Request)\b"
)
_CREDENTIAL_SOURCE = re.compile(
    r"(?i)\b(?:auth|headers?|authorization|x-api-key|password|passwd|"
    r"token|secret|api[_-]?key|credential)\b"
)
_URL_USERINFO_SOURCE = re.compile(r"(?i)https?://[^/\s?#\"'<>]*@")
_PARSER_CACHE: dict[str, Optional[Any]] = {}


_ValueSequence: TypeAlias = tuple["_Value", ...]
_ValueMapping: TypeAlias = tuple[tuple[Optional[str], "_Value"], ...]
_ValuePayload: TypeAlias = str | _ValueSequence | _ValueMapping | None


@dataclass(frozen=True)
class _Value:
    kind: str
    value: _ValuePayload = None


def _sequence_items(value: _Value) -> tuple[_Value, ...]:
    """Return the resolved child values carried by a sequence-like value."""
    return cast(tuple[_Value, ...], value.value)


def _mapping_items(value: _Value) -> tuple[tuple[Optional[str], _Value], ...]:
    """Return the resolved key/value pairs carried by a mapping value."""
    return cast(tuple[tuple[Optional[str], _Value], ...], value.value)


_UNKNOWN = _Value("unknown")
_REFERENCE = _Value("reference")


@dataclass
class _Budget:
    resolutions: int = 0
    containers: int = 0
    string_chars: int = 0
    url_chars: int = 0
    snapshots: int = 0
    exhausted: bool = False

    def consume(self, attribute: str, amount: int, limit: int) -> bool:
        current = getattr(self, attribute)
        if self.exhausted or amount < 0 or current + amount > limit:
            self.exhausted = True
            return False
        setattr(self, attribute, current + amount)
        return True


@dataclass
class _State:
    modules: dict[str, str]
    functions: dict[str, str]
    values: dict[str, _Value]
    instances: dict[str, str]
    shadowed: set[str]
    budget: _Budget

    def fork(self) -> "_State":
        entry_count = (
            len(self.modules)
            + len(self.functions)
            + len(self.values)
            + len(self.instances)
            + len(self.shadowed)
        )
        if not self.budget.consume(
            "snapshots", entry_count, MAX_STATE_SNAPSHOT_ENTRIES
        ):
            return _State({}, {}, {}, {}, set(), self.budget)
        return _State(
            dict(self.modules),
            dict(self.functions),
            dict(self.values),
            dict(self.instances),
            set(self.shadowed),
            self.budget,
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


def _children(node, *, named: bool = True) -> list:
    return list(node.named_children if named else node.children)


def _field(node, name: str):
    try:
        return node.child_by_field_name(name)
    except (AttributeError, ValueError):
        return None


def _node_text(node, source: bytes) -> str:
    try:
        return source[node.start_byte : node.end_byte].decode("utf-8")
    except (UnicodeDecodeError, AttributeError, IndexError):
        return ""


def _decode_escaped(raw: str) -> Optional[str]:
    """Decode ordinary JS escapes without evaluating source expressions."""
    output: list[str] = []
    index = 0
    simple = {
        "0": "\0",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "\\": "\\",
        "'": "'",
        '"': '"',
        "`": "`",
    }
    while index < len(raw):
        char = raw[index]
        if char != "\\":
            output.append(char)
            index += 1
            continue
        index += 1
        if index >= len(raw):
            return None
        escaped = raw[index]
        if escaped in "\r\n":
            if escaped == "\r" and index + 1 < len(raw) and raw[index + 1] == "\n":
                index += 1
            index += 1
            continue
        if escaped in simple:
            output.append(simple[escaped])
            index += 1
            continue
        if escaped == "x":
            digits = raw[index + 1 : index + 3]
            if len(digits) != 2 or re.fullmatch(r"[0-9a-fA-F]{2}", digits) is None:
                return None
            output.append(chr(int(digits, 16)))
            index += 3
            continue
        if escaped == "u":
            if index + 1 < len(raw) and raw[index + 1] == "{":
                end = raw.find("}", index + 2)
                digits = raw[index + 2 : end] if end >= 0 else ""
                if not digits or len(digits) > 6:
                    return None
                try:
                    codepoint = int(digits, 16)
                    output.append(chr(codepoint))
                except (ValueError, OverflowError):
                    return None
                index = end + 1
                continue
            digits = raw[index + 1 : index + 5]
            if len(digits) != 4 or re.fullmatch(r"[0-9a-fA-F]{4}", digits) is None:
                return None
            output.append(chr(int(digits, 16)))
            index += 5
            continue
        # Identity escapes are valid in non-strict JavaScript strings.
        output.append(escaped)
        index += 1
    return "".join(output)


def _string_value(node, source: bytes) -> Optional[str]:
    if node.type not in {"string", "template_string"}:
        return None
    text = _node_text(node, source)
    if node.type == "template_string" and any(
        child.type == "template_substitution" for child in node.named_children
    ):
        return None
    if len(text) < 2:
        return None
    return _decode_escaped(text[1:-1])


def _static_key(node, source: bytes) -> Optional[str]:
    value = _string_value(node, source)
    if value is not None:
        return value
    if node.type in {
        "identifier",
        "property_identifier",
        "shorthand_property_identifier",
        "shorthand_property_identifier_pattern",
    }:
        return _node_text(node, source)
    if node.type == "computed_property_name" and node.named_children:
        return _static_key(node.named_children[0], source)
    return None


def _static_name(node, state: _State, source: bytes) -> Optional[str]:
    if node is None:
        return None
    if node.type in {"parenthesized_expression", "non_null_expression"}:
        children = node.named_children
        return _static_name(children[0], state, source) if children else None
    if node.type == "identifier":
        name = _node_text(node, source)
        if name in state.shadowed:
            return None
        return state.functions.get(name) or state.modules.get(name) or name
    if node.type in {"member_expression", "optional_member_expression"}:
        obj = _field(node, "object")
        prop = _field(node, "property")
        base = _static_name(obj, state, source)
        property_name = _static_key(prop, source) if prop is not None else None
        if not base or not property_name:
            return None
        if base in {"window", "globalThis", "self"} and property_name == "fetch":
            return "fetch"
        if (
            base in {"window", "globalThis", "self"}
            and property_name == "XMLHttpRequest"
        ):
            return "XMLHttpRequest"
        return f"{base}.{property_name}"
    return None


def _module_family(module_name: Optional[str]) -> Optional[str]:
    if module_name == "axios":
        return "axios"
    if module_name in {"http", "node:http"}:
        return "http"
    if module_name in {"https", "node:https"}:
        return "https"
    if module_name in {"node-fetch", "undici"}:
        return "fetch"
    return None


def _module_from_require(node, source: bytes) -> Optional[str]:
    if node is None or node.type != "call_expression":
        return None
    function = _field(node, "function")
    if function is None or function.type != "identifier":
        return None
    if _node_text(function, source) != "require":
        return None
    arguments = _field(node, "arguments")
    items = arguments.named_children if arguments is not None else ()
    return _string_value(items[0], source) if items else None


def _parser_for(language_name: str) -> Optional[Any]:
    if language_name in _PARSER_CACHE:
        return _PARSER_CACHE[language_name]
    try:
        from tree_sitter import Language, Parser

        if language_name == "javascript":
            grammar = importlib.import_module("tree_sitter_javascript")
            language = Language(grammar.language())
        elif language_name == "typescript":
            grammar = importlib.import_module("tree_sitter_typescript")
            language = Language(grammar.language_typescript())
        else:
            grammar = importlib.import_module("tree_sitter_typescript")
            language = Language(grammar.language_tsx())
        parser = Parser(language)
    except Exception:
        logger.warning("JavaScript/TypeScript credential parser is unavailable")
        parser = None
    _PARSER_CACHE[language_name] = parser
    return parser


def _has_relevant_source(source: str) -> bool:
    overlap = 4096
    stride = MAX_SOURCE_CHARS - overlap
    has_http = False
    has_url_userinfo = _URL_USERINFO_SOURCE.search(source) is not None
    for start in range(0, len(source), stride):
        chunk = source[start : start + MAX_SOURCE_CHARS]
        http_matches = iter(_HTTP_SOURCE.finditer(chunk))
        credential_matches = iter(_CREDENTIAL_SOURCE.finditer(chunk))
        http_match = next(http_matches, None)
        credential_match = next(credential_matches, None)
        while http_match is not None and credential_match is not None:
            if abs(http_match.start() - credential_match.start()) <= overlap:
                return True
            if http_match.start() < credential_match.start():
                http_match = next(http_matches, None)
            else:
                credential_match = next(credential_matches, None)
        has_http = has_http or http_match is not None
        if http_match is not None and _URL_USERINFO_SOURCE.search(chunk):
            return True
    return has_http and has_url_userinfo


class _Analyzer:
    def __init__(self, source: bytes) -> None:
        self.source = source
        self.budget = _Budget()
        self.findings: list[HttpRequestCredentialFinding] = []
        self._seen: set[HttpRequestCredentialFinding] = set()
        self.incomplete = False
        self.pending_functions: list[tuple[object, _State]] = []

    def add(self, node, client: str, sink: str, finding_class: str) -> None:
        row = getattr(getattr(node, "start_point", None), "row", None)
        line = row + 1 if type(row) is int else None
        finding = HttpRequestCredentialFinding(line, client, sink, finding_class)
        if finding in self._seen:
            return
        self._seen.add(finding)
        if len(self.findings) < MAX_FINDINGS - 1:
            self.findings.append(finding)
            return
        self._add_incomplete()

    def _add_incomplete(self) -> None:
        self.incomplete = True
        finding = HttpRequestCredentialFinding(
            None, "unknown", "unknown", INCOMPLETE_ANALYSIS
        )
        if finding not in self._seen:
            self._seen.add(finding)
            self.findings.append(finding)

    def _incomplete_if_relevant(
        self, source_text: str
    ) -> HttpRequestCredentialAnalysis:
        if _has_relevant_source(source_text):
            self._add_incomplete()
        return HttpRequestCredentialAnalysis(tuple(self.findings), self.incomplete)

    def _budget_is_exhausted(self) -> bool:
        return self.budget.exhausted

    def _resolve(self, node, state: _State, depth: int = 0) -> _Value:
        if self._budget_is_exhausted():
            return _UNKNOWN
        if depth > MAX_RESOLUTION_DEPTH:
            self.budget.exhausted = True
            return _UNKNOWN
        if not self.budget.consume("resolutions", 1, MAX_RESOLUTION_OPERATIONS):
            return _UNKNOWN
        if node is None:
            return _UNKNOWN
        kind = node.type
        if kind in {
            "parenthesized_expression",
            "as_expression",
            "satisfies_expression",
            "non_null_expression",
            "type_assertion",
        }:
            children = node.named_children
            return (
                self._resolve(children[0], state, depth + 1) if children else _UNKNOWN
            )
        literal = _string_value(node, self.source)
        if literal is not None:
            if len(literal) > MAX_RESOLVED_STRING_CHARS:
                self.budget.exhausted = True
                return _UNKNOWN
            return _Value("literal", literal)
        if kind in {"identifier", "shorthand_property_identifier"}:
            return state.values.get(_node_text(node, self.source), _UNKNOWN)
        if kind in {"member_expression", "optional_member_expression"}:
            obj = _field(node, "object")
            prop = _field(node, "property")
            base = self._resolve(obj, state, depth + 1)
            key = _static_key(prop, self.source) if prop is not None else None
            if base.kind == "mapping" and key is not None:
                for map_key, map_value in _mapping_items(base):
                    if not self.budget.consume(
                        "containers", 1, MAX_CONTAINER_TRAVERSAL
                    ):
                        return _UNKNOWN
                    if map_key == key:
                        return map_value
            return _REFERENCE
        if kind in {"subscript_expression", "element_access_expression"}:
            children = node.named_children
            if len(children) >= 2:
                base = self._resolve(children[0], state, depth + 1)
                subscript_key = self._resolve(children[-1], state, depth + 1)
                if base.kind == "mapping" and subscript_key.kind == "literal":
                    for map_key, map_value in _mapping_items(base):
                        if not self.budget.consume(
                            "containers", 1, MAX_CONTAINER_TRAVERSAL
                        ):
                            return _UNKNOWN
                        if map_key == subscript_key.value:
                            return map_value
                return _REFERENCE
        if kind in {"array", "array_pattern"}:
            sequence_values: list[_Value] = []
            for child in node.named_children:
                if self.budget.exhausted:
                    return _UNKNOWN
                sequence_values.append(self._resolve(child, state, depth + 1))
            return _Value("sequence", tuple(sequence_values))
        if kind == "object":
            mapping_values: list[tuple[Optional[str], _Value]] = []
            for child in node.named_children:
                if self.budget.exhausted or not self.budget.consume(
                    "containers", 1, MAX_CONTAINER_TRAVERSAL
                ):
                    return _UNKNOWN
                if child.type == "pair":
                    key_node = _field(child, "key")
                    value_node = _field(child, "value")
                    key = _static_key(key_node, self.source) if key_node else None
                    mapping_values.append(
                        (key, self._resolve(value_node, state, depth + 1))
                    )
                elif child.type == "shorthand_property_identifier":
                    key = _node_text(child, self.source)
                    mapping_values.append((key, state.values.get(key, _UNKNOWN)))
                elif child.type == "spread_element" and child.named_children:
                    expanded = self._resolve(child.named_children[-1], state, depth + 1)
                    if expanded.kind == "mapping":
                        mapping_values.extend(_mapping_items(expanded))
            return _Value("mapping", tuple(mapping_values))
        if kind == "template_string":
            parts: list[str] = []
            for child in node.named_children:
                if child.type == "string_fragment":
                    text = _decode_escaped(_node_text(child, self.source))
                    if text is None:
                        return _UNKNOWN
                    parts.append(text)
                elif child.type == "template_substitution":
                    expressions = child.named_children
                    resolved = (
                        self._resolve(expressions[-1], state, depth + 1)
                        if expressions
                        else _UNKNOWN
                    )
                    if resolved.kind != "literal":
                        return _REFERENCE if resolved.kind == "reference" else _UNKNOWN
                    parts.append(str(resolved.value))
                else:
                    return _UNKNOWN
            value = "".join(parts)
            if not self.budget.consume(
                "string_chars", len(value), MAX_TOTAL_RESOLVED_STRING_CHARS
            ):
                return _UNKNOWN
            return _Value("literal", value)
        if kind == "binary_expression":
            children = node.children
            if len(children) >= 3 and _node_text(children[1], self.source) == "+":
                left = self._resolve(_field(node, "left"), state, depth + 1)
                right = self._resolve(_field(node, "right"), state, depth + 1)
                if left.kind == right.kind == "literal":
                    value = str(left.value) + str(right.value)
                    if not self.budget.consume(
                        "string_chars", len(value), MAX_TOTAL_RESOLVED_STRING_CHARS
                    ):
                        return _UNKNOWN
                    return _Value("literal", value)
                if left.kind == "reference" or right.kind == "reference":
                    return _REFERENCE
        if kind == "ternary_expression":
            first = _field(node, "consequence")
            second = _field(node, "alternative")
            if first is not None and second is not None:
                return self._alternatives(
                    (
                        self._resolve(first, state, depth + 1),
                        self._resolve(second, state, depth + 1),
                    )
                )
        if kind == "assignment_expression":
            return self._resolve(_field(node, "right"), state, depth + 1)
        if kind == "new_expression":
            constructor = _static_name(_field(node, "constructor"), state, self.source)
            args = self._arguments(node)
            if (
                constructor in {"Headers", "globalThis.Headers", "window.Headers"}
                and args
            ):
                return self._resolve(args[0], state, depth + 1)
        if kind == "call_expression":
            function = _static_name(_field(node, "function"), state, self.source)
            args = self._arguments(node)
            if function == "JSON.stringify" and args:
                return self._resolve(args[0], state, depth + 1)
            if function == "Object.assign" and len(args) > 1:
                entries: list[tuple[Optional[str], _Value]] = []
                for argument in args[1:]:
                    resolved_argument = self._resolve(argument, state, depth + 1)
                    if resolved_argument.kind == "mapping":
                        entries.extend(_mapping_items(resolved_argument))
                return _Value("mapping", tuple(entries))
        return _UNKNOWN

    def _alternatives(self, values: tuple[_Value, ...]) -> _Value:
        unique: list[_Value] = []
        for value in values:
            candidates = (
                _sequence_items(value) if value.kind == "alternatives" else (value,)
            )
            for candidate in candidates:
                if not self.budget.consume("resolutions", 1, MAX_RESOLUTION_OPERATIONS):
                    return _UNKNOWN
                if candidate not in unique:
                    if len(unique) >= MAX_BRANCH_ALTERNATIVES:
                        self.budget.exhausted = True
                        return _UNKNOWN
                    unique.append(candidate)
        if len(unique) == 1:
            return unique[0]
        return _Value("alternatives", tuple(unique)) if unique else _UNKNOWN

    @staticmethod
    def _arguments(node) -> list:
        args = _field(node, "arguments")
        return list(args.named_children) if args is not None else []

    def _check_literal(self, value: _Value, node, client: str, sink: str) -> None:
        if value.kind != "literal" or not isinstance(value.value, str):
            return
        if not self.budget.consume(
            "string_chars", len(value.value), MAX_TOTAL_RESOLVED_STRING_CHARS
        ):
            return
        if not _is_placeholder(value.value):
            self.add(node, client, sink, INLINE_LITERAL)

    def _scan_sensitive(self, value: _Value, node, client: str, sink: str, depth=0):
        if self.budget.exhausted:
            return
        if depth > MAX_RESOLUTION_DEPTH:
            self.budget.exhausted = True
            return
        if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
            return
        if value.kind == "literal":
            self._check_literal(value, node, client, sink)
        elif value.kind == "alternatives":
            for item in _sequence_items(value):
                if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                    return
                self._scan_sensitive(item, node, client, sink, depth + 1)
        elif value.kind == "sequence":
            parts = _sequence_items(value)
            if len(parts) > 1:
                if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                    return
                self._scan_sensitive(parts[1], node, client, sink, depth + 1)
        elif value.kind == "mapping":
            for key, item in _mapping_items(value):
                if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                    return
                if key is not None and _normalized_name(key) in _CREDENTIAL_FIELDS:
                    self._scan_sensitive(
                        item, node, client, self._field_sink(key), depth + 1
                    )

    def _scan_credential_fields(self, value: _Value, node, client: str, depth=0):
        if self.budget.exhausted:
            return
        if depth > MAX_RESOLUTION_DEPTH:
            self.budget.exhausted = True
            return
        if value.kind == "alternatives":
            for item in _sequence_items(value):
                if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                    return
                self._scan_credential_fields(item, node, client, depth + 1)
        elif value.kind == "mapping":
            for key, item in _mapping_items(value):
                if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                    return
                if key is None:
                    continue
                if _normalized_name(key) in _CREDENTIAL_FIELDS:
                    self._scan_sensitive(
                        item, node, client, self._field_sink(key), depth + 1
                    )
                elif item.kind in {"mapping", "sequence", "alternatives"}:
                    self._scan_credential_fields(item, node, client, depth + 1)
        elif value.kind == "sequence":
            for item in _sequence_items(value):
                if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                    return
                self._scan_credential_fields(item, node, client, depth + 1)

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

    def _scan_headers(self, value: _Value, node, client: str, depth=0):
        if self.budget.exhausted:
            return
        if depth > MAX_RESOLUTION_DEPTH:
            self.budget.exhausted = True
            return
        if value.kind == "alternatives":
            for item in _sequence_items(value):
                if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                    return
                self._scan_headers(item, node, client, depth + 1)
            return
        if value.kind == "sequence":
            for pair in _sequence_items(value):
                if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                    return
                if pair.kind != "sequence":
                    continue
                pair_items = _sequence_items(pair)
                if len(pair_items) != 2:
                    continue
                header_name, header_value = pair_items
                if header_name.kind == "literal" and isinstance(header_name.value, str):
                    normalized = header_name.value.casefold().strip()
                    if normalized in _AUTH_HEADERS:
                        self._scan_sensitive(
                            header_value, node, client, self._header_sink(normalized)
                        )
            return
        if value.kind != "mapping":
            return
        for mapping_key, mapping_value in _mapping_items(value):
            if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                return
            if mapping_key is None:
                continue
            normalized = mapping_key.casefold().strip()
            if normalized in _AUTH_HEADERS:
                self._scan_sensitive(
                    mapping_value, node, client, self._header_sink(normalized)
                )
            elif mapping_value.kind in {"mapping", "sequence", "alternatives"}:
                self._scan_headers(mapping_value, node, client, depth + 1)

    @staticmethod
    def _header_sink(normalized: str) -> str:
        if "api-key" in normalized or normalized == "api-key":
            return "api_key_header"
        if normalized in {"cookie", "set-cookie"}:
            return "cookie_header"
        return "authorization_header"

    def _scan_options(self, value: _Value, node, client: str, depth=0):
        if self.budget.exhausted:
            return
        if depth > MAX_RESOLUTION_DEPTH:
            self.budget.exhausted = True
            return
        if value.kind == "alternatives":
            for item in _sequence_items(value):
                if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                    return
                self._scan_options(item, node, client, depth + 1)
            return
        if value.kind != "mapping":
            return
        for key, item in _mapping_items(value):
            if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                return
            if key is None:
                continue
            normalized = _normalized_name(key)
            if normalized in {"auth", "authentication"}:
                self._scan_sensitive(item, node, client, "authentication")
            elif normalized in {"headers", "header"}:
                self._scan_headers(item, node, client)
            elif normalized in {
                "data",
                "json",
                "body",
                "params",
                "search_params",
                "form",
            }:
                self._scan_credential_fields(item, node, client)
            elif normalized in {"url", "uri"}:
                self._scan_url(item, node, client)
            elif item.kind in {"mapping", "sequence", "alternatives"}:
                # Axios commonly nests method-specific headers under `common`.
                self._scan_options(item, node, client, depth + 1)

    def _scan_url(self, value: _Value, node, client: str, depth=0):
        if self.budget.exhausted:
            return
        if depth > MAX_RESOLUTION_DEPTH:
            self.budget.exhausted = True
            return
        if value.kind == "alternatives":
            for item in _sequence_items(value):
                if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                    return
                self._scan_url(item, node, client, depth + 1)
            return
        if value.kind != "literal" or not isinstance(value.value, str):
            return
        raw = value.value
        if len(raw) > MAX_SOURCE_CHARS // 4:
            self.budget.exhausted = True
            return
        query_length = len(raw.partition("?")[2])
        if not self.budget.consume(
            "url_chars", len(raw) + query_length, MAX_TOTAL_URL_PARSE_CHARS
        ):
            return
        try:
            parsed = urlsplit(raw)
        except ValueError:
            return
        if parsed.scheme.casefold() in {"http", "https", "ws", "wss"}:
            username = unquote(parsed.username) if parsed.username is not None else None
            password = unquote(parsed.password) if parsed.password is not None else None
            if (username is not None and not _is_placeholder(username)) or (
                password is not None and not _is_placeholder(password)
            ):
                self.add(node, client, "url_userinfo", INLINE_LITERAL)
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
            if not self.budget.consume("containers", 1, MAX_CONTAINER_TRAVERSAL):
                return
            if _normalized_name(key) in _CREDENTIAL_FIELDS:
                self._check_literal(
                    _Value("literal", query_value), node, client, self._field_sink(key)
                )

    def _api_name(self, node, state: _State) -> Optional[str]:
        if node is None:
            return None
        if node.type == "identifier":
            name = _node_text(node, self.source)
            if name in state.shadowed:
                return None
            if name in state.functions:
                return state.functions[name]
            if name in state.modules:
                return state.modules[name]
            if name == "fetch":
                return "fetch"
            if name in {"Request", "XMLHttpRequest"}:
                return name
            return None
        static_name = _static_name(node, state, self.source)
        if static_name in {"window.fetch", "globalThis.fetch", "self.fetch"}:
            return "fetch"
        if static_name in {
            "window.XMLHttpRequest",
            "globalThis.XMLHttpRequest",
            "self.XMLHttpRequest",
        }:
            return "XMLHttpRequest"
        return static_name

    def _request_url(self, node, state: _State, client: str, args: list, index: int):
        if len(args) > index:
            self._scan_url(self._resolve(args[index], state), args[index], client)

    def _scan_fetch(self, node, state: _State, args: list):
        self._request_url(node, state, "fetch", args, 0)
        if len(args) > 1:
            self._scan_options(self._resolve(args[1], state), args[1], "fetch")

    def _scan_axios(self, node, state: _State, api: str, args: list):
        method = api.rsplit(".", 1)[1] if "." in api else "request"
        if api == "axios" and args:
            self._scan_url(self._resolve(args[0], state), args[0], "axios")
        elif method != "request" and args:
            self._request_url(node, state, "axios", args, 0)
        if method == "request":
            if args:
                self._scan_options(self._resolve(args[0], state), args[0], "axios")
            if len(args) > 1:
                self._scan_options(self._resolve(args[1], state), args[1], "axios")
            return
        if method in {"post", "put", "patch"}:
            if len(args) > 1:
                self._scan_credential_fields(
                    self._resolve(args[1], state), args[1], "axios"
                )
            if len(args) > 2:
                self._scan_options(self._resolve(args[2], state), args[2], "axios")
        elif len(args) > 1:
            self._scan_options(self._resolve(args[1], state), args[1], "axios")

    def _scan_node_http(self, node, state: _State, client: str, args: list):
        options_index = 0 if args and args[0].type == "object" else 1
        if args and options_index == 1:
            self._request_url(node, state, client, args, 0)
        if len(args) > options_index:
            options_node = args[options_index]
            options = self._resolve(options_node, state)
            self._scan_options(options, options_node, client)
            if options.kind == "mapping":
                for key, resolved_option in _mapping_items(options):
                    if key == "url":
                        self._scan_url(resolved_option, options_node, client)

    def _scan_request_constructor(self, node, state: _State, args: list):
        self._request_url(node, state, "fetch", args, 0)
        if len(args) > 1:
            self._scan_options(self._resolve(args[1], state), args[1], "fetch")

    def _scan_xhr_method(
        self, node, state: _State, client: str, method: str, args: list
    ):
        if method == "open":
            self._request_url(node, state, client, args, 1)
            if len(args) > 4:
                self._scan_sensitive(
                    _Value(
                        "sequence",
                        (self._resolve(args[3], state), self._resolve(args[4], state)),
                    ),
                    node,
                    client,
                    "authentication",
                )
        elif method == "setRequestHeader" or method == "setHeader":
            if len(args) >= 2:
                key = _static_key(args[0], self.source)
                normalized = key.casefold().strip() if key is not None else ""
                if normalized in _AUTH_HEADERS:
                    self._scan_sensitive(
                        self._resolve(args[1], state),
                        args[1],
                        client,
                        self._header_sink(normalized),
                    )
        elif method in {"send", "write", "end"} and args:
            value = self._resolve(args[0], state)
            self._scan_credential_fields(value, args[0], client)

    def _scan_call(self, node, state: _State):
        function = _field(node, "function")
        if node.type == "new_expression":
            function = _field(node, "constructor")
        api = self._api_name(function, state)
        args = self._arguments(node)
        if node.type == "new_expression" and api == "Request":
            self._scan_request_constructor(node, state, args)
        elif node.type == "call_expression" and api == "fetch":
            self._scan_fetch(node, state, args)
        elif node.type == "call_expression" and (
            api == "axios"
            or (
                api
                and api.startswith("axios.")
                and api.rsplit(".", 1)[-1]
                in {
                    "request",
                    "get",
                    "post",
                    "put",
                    "patch",
                    "delete",
                    "head",
                    "options",
                }
            )
        ):
            self._scan_axios(node, state, api or "axios", args)
        elif node.type == "call_expression" and api in {
            "http.request",
            "http.get",
            "https.request",
            "https.get",
        }:
            family = api.split(".", 1)[0]
            self._scan_node_http(node, state, family, args)
        elif node.type == "call_expression" and function is not None:
            if function.type in {"member_expression", "optional_member_expression"}:
                receiver = _field(function, "object")
                method_node = _field(function, "property")
                receiver_name = (
                    _node_text(receiver, self.source) if receiver is not None else ""
                )
                method = _node_text(method_node, self.source) if method_node else ""
                instance_family = state.instances.get(receiver_name)
                if instance_family in {"xhr", "http", "https"}:
                    self._scan_xhr_method(node, state, instance_family, method, args)

    def _register_import(self, node, state: _State):
        source_node = _field(node, "source")
        module_name = _string_value(source_node, self.source) if source_node else None
        family = _module_family(module_name)
        if family is None:
            return
        clause = next(
            (child for child in node.named_children if child.type == "import_clause"),
            None,
        )
        if clause is None:
            return
        for child in clause.named_children:
            if child.type == "identifier":
                local = _node_text(child, self.source)
                state.modules[local] = family
                state.shadowed.discard(local)
            elif child.type == "namespace_import" and child.named_children:
                local = _node_text(child.named_children[-1], self.source)
                state.modules[local] = family
                state.shadowed.discard(local)
            elif child.type == "named_imports":
                for specifier in child.named_children:
                    if specifier.type != "import_specifier":
                        continue
                    imported = _field(specifier, "name")
                    local = _field(specifier, "alias") or imported
                    if imported is None or local is None:
                        continue
                    imported_name = _node_text(imported, self.source)
                    local_name = _node_text(local, self.source)
                    if imported_name == "default":
                        state.modules[local_name] = family
                        state.functions.pop(local_name, None)
                    elif family == "fetch" and imported_name == "fetch":
                        state.modules[local_name] = family
                        state.functions.pop(local_name, None)
                    else:
                        state.functions[local_name] = f"{family}.{imported_name}"
                        state.modules.pop(local_name, None)
                    state.shadowed.discard(local_name)

    def _bind_pattern(self, pattern, value: _Value, state: _State):
        if pattern is None:
            return
        if pattern.type == "identifier":
            name = _node_text(pattern, self.source)
            state.values[name] = value
            state.instances.pop(name, None)
            state.modules.pop(name, None)
            state.functions.pop(name, None)
            state.shadowed.add(name)
            return
        if pattern.type == "object_pattern":
            if value.kind != "mapping":
                return
            for child in pattern.named_children:
                if child.type != "pair_pattern":
                    continue
                key_node = _field(child, "key")
                value_node = _field(child, "value")
                key = _static_key(key_node, self.source) if key_node else None
                if key is None or value_node is None:
                    continue
                found = next(
                    (
                        item
                        for entry_key, item in _mapping_items(value)
                        if entry_key == key
                    ),
                    _UNKNOWN,
                )
                self._bind_pattern(value_node, found, state)

    def _bind_module(self, pattern, module_name: Optional[str], state: _State):
        family = _module_family(module_name)
        if family is None or pattern is None:
            return False
        if pattern.type == "identifier":
            local = _node_text(pattern, self.source)
            state.modules[local] = family
            state.functions.pop(local, None)
            state.values.pop(local, None)
            state.shadowed.discard(local)
            return True
        if pattern.type == "object_pattern":
            for child in pattern.named_children:
                key_node = (
                    _field(child, "key") if child.type == "pair_pattern" else child
                )
                local_node = (
                    _field(child, "value") if child.type == "pair_pattern" else child
                )
                if key_node is None or local_node is None:
                    continue
                imported = _static_key(key_node, self.source)
                local = _node_text(local_node, self.source)
                if imported is None or local_node.type != "identifier":
                    if child.type != "shorthand_property_identifier_pattern":
                        continue
                    imported = _node_text(child, self.source)
                    local = imported
                state.functions[local] = f"{family}.{imported}"
                state.shadowed.discard(local)
            return True
        return False

    def _register_declarator(self, declarator, state: _State):
        pattern = _field(declarator, "name")
        value_node = _field(declarator, "value")
        if pattern is None:
            return
        module_name = _module_from_require(value_node, self.source)
        if self._bind_module(pattern, module_name, state):
            return
        resolved = (
            self._resolve(value_node, state) if value_node is not None else _UNKNOWN
        )
        self._bind_pattern(pattern, resolved, state)
        if pattern.type == "identifier":
            name = _node_text(pattern, self.source)
            api = self._api_name(value_node, state)
            if api in {"axios", "http", "https", "fetch"}:
                state.modules[name] = api
                state.functions.pop(name, None)
                state.shadowed.discard(name)
            elif api and (
                api.startswith("axios.")
                or api in {"http.request", "http.get", "https.request", "https.get"}
            ):
                state.functions[name] = api
                state.modules.pop(name, None)
                state.shadowed.discard(name)
            instance = self._instance_family(value_node, state)
            if instance:
                state.instances[name] = instance
            elif value_node is not None and value_node.type == "identifier":
                source_name = _node_text(value_node, self.source)
                if source_name in state.instances:
                    state.instances[name] = state.instances[source_name]

    def _instance_family(self, node, state: _State) -> Optional[str]:
        if node is None:
            return None
        if node.type == "new_expression":
            name = _static_name(_field(node, "constructor"), state, self.source)
            if name in {
                "XMLHttpRequest",
                "window.XMLHttpRequest",
                "globalThis.XMLHttpRequest",
                "self.XMLHttpRequest",
            }:
                return "xhr"
            if name in {"Headers", "window.Headers", "globalThis.Headers"}:
                return "headers"
        if node.type == "call_expression":
            api = self._api_name(_field(node, "function"), state)
            if api in {"http.request", "http.get", "https.request", "https.get"}:
                return api.split(".", 1)[0]
        return None

    def _parameter_names(self, function_node) -> list[str]:
        parameters = _field(function_node, "parameters")
        if parameters is None:
            return []
        names: list[str] = []
        stack = list(parameters.named_children)
        while stack:
            child = stack.pop()
            if child.type == "identifier":
                names.append(_node_text(child, self.source))
                continue
            if child.type in {"type_annotation", "type_arguments"}:
                continue
            stack.extend(child.named_children)
        return names

    def _queue_function(self, node, state: _State):
        function_state = state.fork()
        name_node = _field(node, "name")
        if name_node is not None:
            name = _node_text(name_node, self.source)
            function_state.modules.pop(name, None)
            function_state.functions.pop(name, None)
            function_state.values.pop(name, None)
            function_state.instances.pop(name, None)
            function_state.shadowed.add(name)
        for parameter in self._parameter_names(node):
            function_state.modules.pop(parameter, None)
            function_state.functions.pop(parameter, None)
            function_state.values.pop(parameter, None)
            function_state.instances.pop(parameter, None)
            function_state.shadowed.add(parameter)
        body = _field(node, "body")
        if body is not None:
            self.pending_functions.append((body, function_state))

    def _scan_expr(self, node, state: _State):
        if self._budget_is_exhausted():
            return
        if node.type in {
            "function_declaration",
            "function_expression",
            "generator_function",
            "generator_function_declaration",
            "arrow_function",
            "method_definition",
        }:
            self._queue_function(node, state)
            return
        if node.type in {"call_expression", "new_expression"}:
            self._scan_call(node, state)
        for child in node.named_children:
            if self.budget.exhausted:
                return
            self._scan_expr(child, state)

    def _merge_branches(self, target: _State, branches: list[_State]):
        # Only merge names already in the enclosing scope; block-local const/let
        # bindings must not escape their block.
        for name in tuple(target.values):
            values = tuple(branch.values.get(name, _UNKNOWN) for branch in branches)
            merged = self._alternatives(values)
            if merged.kind == "unknown":
                target.values.pop(name, None)
            else:
                target.values[name] = merged
        for name in tuple(target.instances):
            families = {branch.instances.get(name) for branch in branches}
            if len(families) != 1 or None in families:
                target.instances.pop(name, None)
        for name in tuple(target.modules):
            aliases = {branch.modules.get(name) for branch in branches}
            if len(aliases) != 1 or None in aliases:
                target.modules.pop(name, None)
        for name in tuple(target.functions):
            aliases = {branch.functions.get(name) for branch in branches}
            if len(aliases) != 1 or None in aliases:
                target.functions.pop(name, None)

    def _process_statement(self, node, state: _State):
        if self.budget.exhausted:
            return
        kind = node.type
        if kind == "import_statement":
            self._register_import(node, state)
            return
        if kind in {
            "function_declaration",
            "generator_function_declaration",
            "class_declaration",
        }:
            if kind != "class_declaration":
                self._queue_function(node, state)
            else:
                body = _field(node, "body")
                if body is not None:
                    for child in body.named_children:
                        self._scan_expr(child, state)
            return
        if kind in {"lexical_declaration", "variable_declaration", "using_declaration"}:
            for declarator in node.named_children:
                if declarator.type != "variable_declarator":
                    self._scan_expr(declarator, state)
                    continue
                value_node = _field(declarator, "value")
                if value_node is not None:
                    self._scan_expr(value_node, state)
                self._register_declarator(declarator, state)
            return
        if kind == "expression_statement":
            expression = node.named_children[0] if node.named_children else None
            if expression is not None:
                self._scan_expr(expression, state)
                if expression.type == "assignment_expression":
                    left = _field(expression, "left")
                    right = _field(expression, "right")
                    if left is not None and left.type == "identifier":
                        self._bind_pattern(left, self._resolve(right, state), state)
                        name = _node_text(left, self.source)
                        api = self._api_name(right, state)
                        if api in {"axios", "http", "https", "fetch"}:
                            state.modules[name] = api
                            state.functions.pop(name, None)
                            state.shadowed.discard(name)
                        elif api and (
                            api.startswith("axios.")
                            or api
                            in {
                                "http.request",
                                "http.get",
                                "https.request",
                                "https.get",
                            }
                        ):
                            state.functions[name] = api
                            state.modules.pop(name, None)
                            state.shadowed.discard(name)
                        instance = self._instance_family(right, state)
                        if instance:
                            state.instances[name] = instance
            return
        if kind == "if_statement":
            condition = _field(node, "condition")
            if condition is not None:
                self._scan_expr(condition, state)
            consequence = _field(node, "consequence")
            alternative = _field(node, "alternative")
            first_state = state.fork()
            if consequence is not None:
                self._process_block(consequence, first_state)
            branches = [first_state]
            if alternative is not None:
                second_state = state.fork()
                self._process_block(alternative, second_state)
                branches.append(second_state)
            else:
                branches.append(state.fork())
            self._merge_branches(state, branches)
            return
        if kind in {
            "for_statement",
            "for_in_statement",
            "while_statement",
            "do_statement",
        }:
            for child in node.named_children:
                if child.type in {"statement_block", "expression_statement"}:
                    continue
                self._scan_expr(child, state)
            branch = state.fork()
            body = next(
                (
                    child
                    for child in reversed(node.named_children)
                    if child.type == "statement_block"
                ),
                None,
            )
            if body is not None:
                self._process_block(body, branch)
                self._merge_branches(state, [state.fork(), branch])
            return
        if kind in {
            "statement_block",
            "switch_body",
            "try_statement",
            "catch_clause",
            "finally_clause",
        }:
            self._process_block(node, state)
            return
        self._scan_expr(node, state)

    def _process_block(self, node, state: _State):
        if node.type in {"statement_block", "program", "switch_body"}:
            for child in node.named_children:
                if self.budget.exhausted:
                    return
                self._process_statement(child, state)
        else:
            self._process_statement(node, state)

    def _analyze_tree(self, root) -> HttpRequestCredentialAnalysis:
        node_count = 0
        stack = [root]
        while stack:
            node = stack.pop()
            node_count += 1
            if node_count > MAX_AST_NODES:
                return self._incomplete_if_relevant(
                    self.source.decode("utf-8", "replace")
                )
            stack.extend(node.children)
        if root.has_error:
            return self._incomplete_if_relevant(self.source.decode("utf-8", "replace"))
        state = _State({}, {}, {}, {}, set(), self.budget)
        # ES imports are scope-wide; register them before scanning function bodies.
        for child in root.named_children:
            if child.type == "import_statement":
                self._register_import(child, state)
        self._process_block(root, state)
        index = 0
        while index < len(self.pending_functions) and not self.budget.exhausted:
            body, function_state = self.pending_functions[index]
            index += 1
            self._process_block(body, function_state)
        if self.budget.exhausted:
            return self._incomplete_if_relevant(self.source.decode("utf-8", "replace"))
        return HttpRequestCredentialAnalysis(tuple(self.findings), self.incomplete)


def analyze_js_ts_http_request_credentials(
    source: str, file_path: str
) -> HttpRequestCredentialAnalysis:
    """Parse and analyze supported JavaScript/TypeScript HTTP request sinks."""
    if not isinstance(source, str) or not source:
        return HttpRequestCredentialAnalysis()
    extension = file_path.rsplit(".", 1)[-1].casefold() if "." in file_path else ""
    if extension not in {item[1:] for item in SOURCE_EXTENSIONS}:
        return HttpRequestCredentialAnalysis()
    language_name = (
        "typescript"
        if extension in {"ts", "mts", "cts"}
        else ("tsx" if extension == "tsx" else "javascript")
    )
    analyzer_source = source
    if len(source) > MAX_SOURCE_CHARS:
        return _Analyzer(b"")._incomplete_if_relevant(source)
    try:
        encoded = source.encode("utf-8")
    except UnicodeEncodeError:
        return _Analyzer(b"")._incomplete_if_relevant(source)
    parser = _parser_for(language_name)
    if parser is None:
        return _Analyzer(encoded)._incomplete_if_relevant(analyzer_source)
    try:
        tree = parser.parse(encoded)
        return _Analyzer(encoded)._analyze_tree(tree.root_node)
    except (TypeError, ValueError, IndexError, RecursionError):
        logger.warning(
            "JavaScript/TypeScript HTTP credential analysis failed; source withheld"
        )
        return _Analyzer(encoded)._incomplete_if_relevant(analyzer_source)
