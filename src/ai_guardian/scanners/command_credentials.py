"""Command-aware detection of literal credentials in supported CLI arguments.

The scanner tokenizes a bounded shell subset without expanding variables,
executing commands, or retaining argument values in its results. It deliberately
reports only the supported command families and credential option semantics.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Callable, Optional

from ai_guardian.scanners.scan_result import ScanResult

logger = logging.getLogger(__name__)

CONFIG_SECTION = "command_credential_scanning"
VIOLATION_TYPE = "command_credential_detected"
ENGINE = "local-command-credential-scanner"

MAX_COMMAND_CHARS = 32_768
MAX_TOKENS = 2_048
MAX_COMMAND_SEGMENTS = 64

INLINE_LITERAL = "inline_literal"
CREDENTIAL_REFERENCE = "credential_reference"
INTERACTIVE_AUTH = "interactive_no_value_authentication"
UNSUPPORTED_PARSE = "unsupported_or_incomplete_parse"

BLOCK_MESSAGE = (
    "Inline credential argument detected; command execution was blocked. "
    "Values are withheld. This cannot retract command text already seen by the model."
)
WARN_MESSAGE = (
    "Inline credential argument detected; this command may proceed because the "
    "configured action is warn. Values are withheld."
)
ASK_MESSAGE = (
    "Inline credential argument detected. Approve Once allows this command only; "
    "the credential value is withheld."
)
REFERENCE_MESSAGE = (
    "A credential reference or interactive authentication option was detected; "
    "no literal credential value was found in the command text. The command may proceed."
)
INCOMPLETE_MESSAGE = (
    "Command credential analysis is incomplete; no credential is confirmed, and "
    "the command could not be qualified."
)
INCOMPLETE_WARN_MESSAGE = (
    INCOMPLETE_MESSAGE
    + " This command may proceed because the configured action is warn."
)
INCOMPLETE_BLOCK_MESSAGE = (
    INCOMPLETE_MESSAGE + " Command execution was blocked by the configured action."
)
INCOMPLETE_ASK_MESSAGE = INCOMPLETE_MESSAGE + " Approve Once allows this command only."

_VARIABLE_PATTERNS = (
    re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}"),
    re.compile(r"\$env:[A-Za-z_][A-Za-z0-9_]*", re.IGNORECASE),
    re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*"),
)
_PLACEHOLDERS = frozenset(
    {
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
    }
)
_AUTH_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "x-auth-token",
        "private-token",
    }
)
_DIRECT_COMMANDS = {
    "curl": "curl",
    "curl.exe": "curl",
    "wget": "wget",
    "wget.exe": "wget",
    "invoke-webrequest": "powershell-web",
    "iwr": "powershell-web",
    "invoke-restmethod": "powershell-web",
    "irm": "powershell-web",
}
_WRAPPERS = frozenset(
    {
        "command",
        "doas",
        "env",
        "exec",
        "nohup",
        "powershell",
        "pwsh",
        "sh",
        "bash",
        "zsh",
        "sudo",
        "time",
        "timeout",
        "cmd",
        "cmd.exe",
    }
)
_VALID_ACTIONS = frozenset({"ask", "block", "warn", "log-only"})


@dataclass(frozen=True)
class _Token:
    """A shell token and the spans that are variable references, not values."""

    value: str
    variable_spans: tuple[tuple[int, int], ...] = ()

    def fragment(self, start: int, end: Optional[int] = None) -> "_Token":
        stop = len(self.value) if end is None else end
        spans = tuple(
            (max(left, start) - start, min(right, stop) - start)
            for left, right in self.variable_spans
            if left < stop and right > start
        )
        return _Token(self.value[start:stop], spans)

    @property
    def is_reference(self) -> bool:
        return bool(self.variable_spans)


@dataclass(frozen=True)
class CommandCredentialFinding:
    """Value-free location and classification for one command argument."""

    command_index: int
    argument_index: int
    command_family: str
    option: str
    finding_class: str


@dataclass(frozen=True)
class CommandCredentialAnalysis:
    findings: tuple[CommandCredentialFinding, ...] = ()
    incomplete: bool = False


def _variable_end(text: str, index: int) -> Optional[int]:
    """Return the end of a supported variable reference without expanding it."""
    for pattern in _VARIABLE_PATTERNS:
        match = pattern.match(text, index)
        if match:
            return match.end()
    return None


def _tokenize(command: str, *, powershell: bool) -> tuple[list[list[_Token]], bool]:
    """Tokenize a deliberately small shell subset; never evaluate expansions."""
    segments: list[list[_Token]] = []
    tokens: list[_Token] = []
    chars: list[str] = []
    variable_spans: list[tuple[int, int]] = []
    quote: Optional[str] = None
    brace_depth = 0
    incomplete = False
    index = 0

    def flush_token() -> None:
        if chars:
            tokens.append(_Token("".join(chars), tuple(variable_spans)))
            chars.clear()
            variable_spans.clear()

    def flush_segment() -> None:
        nonlocal tokens
        flush_token()
        if tokens:
            segments.append(tokens)
            tokens = []

    def append_char(char: str) -> None:
        chars.append(char)

    while index < len(command):
        char = command[index]

        if quote == "'":
            if powershell and command.startswith("''", index):
                append_char("'")
                index += 2
                continue
            if char == "'":
                quote = None
                index += 1
                continue
            append_char(char)
            index += 1
            continue

        if quote == '"':
            escape_char = "`" if powershell else "\\"
            if char == escape_char and index + 1 < len(command):
                escaped = command[index + 1]
                if powershell or escaped in ('"', "\\", "$", "\n"):
                    append_char(escaped)
                    index += 2
                    continue
                append_char(char)
                index += 1
                continue
            if char == '"':
                quote = None
                index += 1
                continue
            if char == "$":
                variable_end = _variable_end(command, index)
                if variable_end:
                    start = len(chars)
                    chars.extend(command[index:variable_end])
                    variable_spans.append((start, len(chars)))
                    index = variable_end
                    continue
                if command.startswith("$(", index):
                    incomplete = True
            append_char(char)
            index += 1
            continue

        if char in ("'", '"'):
            quote = char
            index += 1
            continue

        if char == "`" and powershell:
            if index + 1 >= len(command):
                incomplete = True
                index += 1
                continue
            # PowerShell's escape character prevents expansion of the next char.
            append_char(command[index + 1])
            index += 2
            continue

        if char == "\\" and not powershell:
            if index + 1 < len(command):
                append_char(command[index + 1])
                index += 2
                continue
            incomplete = True
            index += 1
            continue

        if char.isspace():
            flush_token()
            if char == "\n" and brace_depth == 0:
                flush_segment()
            index += 1
            continue

        if char == "#" and (
            index == 0 or command[index - 1].isspace() or command[index - 1] in ";|&"
        ):
            # Shell comments end at the physical line boundary. Do not inspect
            # option-shaped text that is not part of the command.
            flush_token()
            newline = command.find("\n", index)
            if newline < 0:
                break
            index = newline
            continue

        if command.startswith("@{", index) and powershell:
            flush_token()
            tokens.append(_Token("@{"))
            brace_depth += 1
            index += 2
            continue

        if char == "{" and powershell:
            flush_token()
            tokens.append(_Token(char))
            brace_depth += 1
            index += 1
            continue

        if char == "}" and powershell:
            flush_token()
            tokens.append(_Token(char))
            brace_depth -= 1
            if brace_depth < 0:
                incomplete = True
                brace_depth = 0
            index += 1
            continue

        if char in "=," and powershell and brace_depth:
            flush_token()
            tokens.append(_Token(char))
            index += 1
            continue

        if char in "|;&" and brace_depth == 0:
            flush_token()
            while index < len(command) and command[index] == char:
                index += 1
            flush_segment()
            continue

        if char in "()" and powershell:
            flush_token()
            tokens.append(_Token(char))
            index += 1
            continue

        if char == "$":
            variable_end = _variable_end(command, index)
            if variable_end:
                start = len(chars)
                chars.extend(command[index:variable_end])
                variable_spans.append((start, len(chars)))
                index = variable_end
                continue
            if command.startswith("$(", index):
                incomplete = True

        # A bare backtick in a POSIX command is command substitution syntax.
        if char == "`" and not powershell:
            incomplete = True

        append_char(char)
        index += 1

    if quote is not None or brace_depth:
        incomplete = True
    flush_segment()
    if len(segments) > MAX_COMMAND_SEGMENTS or sum(map(len, segments)) > MAX_TOKENS:
        remaining = MAX_TOKENS
        bounded: list[list[_Token]] = []
        for segment in segments[:MAX_COMMAND_SEGMENTS]:
            if remaining <= 0:
                break
            bounded.append(segment[:remaining])
            remaining -= len(bounded[-1])
        return bounded, True
    return segments, incomplete


def _command_name(token: _Token) -> str:
    name = token.value.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return name


def _family_for_segment(
    tokens: list[_Token], *, powershell: bool = False
) -> tuple[Optional[str], bool]:
    """Return a direct family, or whether a supported command is wrapped."""
    if not tokens:
        return None, False
    direct = _DIRECT_COMMANDS.get(_command_name(tokens[0]))
    if direct:
        return direct, False

    first = _command_name(tokens[0])
    if first not in _WRAPPERS and tokens[0].value != "&":
        if powershell and tokens[0].is_reference:
            # PowerShell can assign a command's result (`$r = Invoke-WebRequest`).
            # The bounded parser does not qualify the surrounding expression, so
            # classify the command as incomplete rather than silently skipping it.
            first_token = tokens[0].value
            assigned = first_token.split("=", 1)[1] if "=" in first_token else ""
            candidate = _DIRECT_COMMANDS.get(_command_name(_Token(assigned)))
            if candidate:
                return candidate, True
            if (
                len(tokens) > 2
                and tokens[1].value == "="
                and _command_name(tokens[2]) in _DIRECT_COMMANDS
            ):
                return _DIRECT_COMMANDS[_command_name(tokens[2])], True
        return None, False

    for token in tokens[1:]:
        candidate = _DIRECT_COMMANDS.get(_command_name(token))
        if candidate:
            return candidate, True
        # A shell -c / PowerShell -Command payload is a single opaque token.
        value = token.value.lstrip("& ").casefold()
        for name, family in _DIRECT_COMMANDS.items():
            if value == name or value.startswith(name + " "):
                return family, True
    return None, False


def _is_placeholder(token: _Token) -> bool:
    return token.value.strip().casefold() in _PLACEHOLDERS


def _add_finding(
    findings: list[CommandCredentialFinding],
    command_index: int,
    argument_index: int,
    family: str,
    option: str,
    finding_class: Optional[str],
) -> None:
    if finding_class is None:
        return
    finding = CommandCredentialFinding(
        command_index=command_index,
        argument_index=argument_index,
        command_family=family,
        option=option,
        finding_class=finding_class,
    )
    if finding not in findings:
        findings.append(finding)


def _classify_secret(token: _Token) -> Optional[str]:
    if not token.value.strip():
        return INTERACTIVE_AUTH
    if _reference_spans_cover_value(token):
        return CREDENTIAL_REFERENCE
    if _is_placeholder(token):
        return None
    return INLINE_LITERAL


def _reference_spans_cover_value(token: _Token) -> bool:
    """Whether every non-whitespace character is part of a variable reference."""
    value = token.value.strip()
    if not value or not token.variable_spans:
        return False
    start = token.value.find(value)
    end = start + len(value)
    cursor = start
    for span_start, span_end in sorted(token.variable_spans):
        if span_end <= cursor:
            continue
        if span_start > cursor:
            return False
        cursor = max(cursor, span_end)
        if cursor >= end:
            return True
    return False


def _classify_user_password(token: _Token) -> Optional[str]:
    value = token.value
    if ":" not in value:
        if token.is_reference:
            return CREDENTIAL_REFERENCE
        if _is_placeholder(token):
            return None
        return INTERACTIVE_AUTH

    separator = value.find(":")
    password = token.fragment(separator + 1)
    if not password.value.strip():
        return INTERACTIVE_AUTH
    return _classify_secret(password)


def _classify_header(token: _Token) -> Optional[str]:
    if ":" not in token.value:
        return None
    colon = token.value.find(":")
    header_name = token.value[:colon].strip().casefold()
    if header_name not in _AUTH_HEADERS:
        return None
    value = token.fragment(colon + 1)
    text = value.value.strip()
    if not text:
        return INTERACTIVE_AUTH

    if header_name in ("authorization", "proxy-authorization"):
        parts = text.split(None, 1)
        if len(parts) == 1:
            return INTERACTIVE_AUTH
        value_offset = value.value.find(parts[1])
        credential = value.fragment(value_offset)
        return _classify_secret(credential)
    return _classify_secret(value)


def _classify_url_userinfo(token: _Token) -> Optional[str]:
    value = token.value
    scheme = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value)
    if not scheme:
        return None
    authority_start = scheme.end()
    authority_end = len(value)
    for marker in "/?#":
        position = value.find(marker, authority_start)
        if position >= 0:
            authority_end = min(authority_end, position)
    authority = value[authority_start:authority_end]
    if "@" not in authority:
        return None
    userinfo = authority.rsplit("@", 1)[0]
    separator = userinfo.find(":")
    if separator < 0:
        return INTERACTIVE_AUTH
    password = token.fragment(authority_start + separator + 1, authority_end)
    if not password.value.strip():
        return INTERACTIVE_AUTH
    return _classify_secret(password)


def _add_value_finding(
    findings: list[CommandCredentialFinding],
    token: _Token,
    command_index: int,
    argument_index: int,
    family: str,
    option: str,
    classifier,
) -> None:
    _add_finding(
        findings,
        command_index,
        argument_index,
        family,
        option,
        classifier(token),
    )


def _target_option_value(
    tokens: list[_Token], index: int
) -> tuple[Optional[_Token], int, bool]:
    """Return a separate option value, its index, and missing-value status."""
    value_index = index + 1
    if value_index >= len(tokens) or tokens[value_index].value in (";", "|", "&"):
        return None, value_index, True
    if tokens[value_index].value.startswith("-"):
        return None, value_index, True
    return tokens[value_index], value_index, False


def _scan_http_client(
    tokens: list[_Token],
    *,
    family: str,
    command_index: int,
    findings: list[CommandCredentialFinding],
) -> bool:
    """Scan the documented curl/wget option registry; return incomplete."""
    if family == "curl":
        value_options = {
            "--user": ("user_password", "--user"),
            "--proxy-user": ("user_password", "--proxy-user"),
            "--oauth2-bearer": ("secret", "--oauth2-bearer"),
            "--header": ("header", "--header"),
            "--proxy-header": ("header", "--proxy-header"),
            "--netrc-file": ("reference", "--netrc-file"),
            "--config": ("reference", "--config"),
        }
        short_options = {
            "u": ("user_password", "-u"),
            "U": ("user_password", "-U"),
            "H": ("header", "-H"),
            "K": ("reference", "-K"),
        }
        reference_flags = {"--netrc", "--netrc-optional"}
    else:
        value_options = {
            "--user": ("user", "--user"),
            "--password": ("secret", "--password"),
            "--http-user": ("user", "--http-user"),
            "--http-password": ("secret", "--http-password"),
            "--ftp-user": ("user", "--ftp-user"),
            "--ftp-password": ("secret", "--ftp-password"),
            "--header": ("header", "--header"),
            "--password-file": ("reference", "--password-file"),
            "--config": ("reference", "--config"),
        }
        short_options = {}
        reference_flags = {"--ask-password", "--use-askpass"}

    incomplete = False
    consumed: set[int] = set()
    index = 1
    while index < len(tokens):
        token = tokens[index]
        text = token.value
        if text == "--":
            break
        if text in reference_flags:
            finding_class = (
                INTERACTIVE_AUTH
                if text in ("--ask-password", "--use-askpass")
                else CREDENTIAL_REFERENCE
            )
            _add_finding(
                findings,
                command_index,
                index,
                family,
                text,
                finding_class,
            )
            index += 1
            continue

        option = None
        kind = None
        display = None
        attached: Optional[_Token] = None
        if text.startswith("--"):
            option_name, separator, _ = text.partition("=")
            registered = value_options.get(option_name.casefold())
            if registered:
                option = option_name.casefold()
                kind, display = registered
                if separator:
                    attached = token.fragment(len(option_name) + 1)
        elif text.startswith("-") and len(text) > 1:
            # curl short options may be attached (-uUSER:PASSWORD) or grouped
            # with valueless switches (-fsSuUSER:PASSWORD).
            cluster = text[1:]
            for position, short in enumerate(cluster):
                registered = short_options.get(short)
                if registered:
                    kind, display = registered
                    option = display
                    rest = cluster[position + 1 :]
                    value_offset = position + 2
                    if rest:
                        if rest.startswith("="):
                            rest = rest[1:]
                            value_offset += 1
                        attached = token.fragment(value_offset)
                    break

        if option is None:
            index += 1
            continue

        if kind == "reference" and attached is None:
            value, value_index, missing = _target_option_value(tokens, index)
            if missing:
                incomplete = True
            else:
                consumed.add(value_index)
                _add_finding(
                    findings,
                    command_index,
                    value_index,
                    family,
                    display or option,
                    CREDENTIAL_REFERENCE,
                )
                index = value_index + 1
                continue
        elif attached is not None:
            value = attached
            value_index = index
            missing = not value.value
        else:
            value, value_index, missing = _target_option_value(tokens, index)

        if missing or value is None:
            incomplete = True
            index += 1
            continue
        consumed.add(value_index)
        classifier: Callable[[_Token], Optional[str]]
        if kind == "user_password" or kind == "user":
            classifier = _classify_user_password
        elif kind == "header":
            classifier = _classify_header
        elif kind == "reference":
            classifier = lambda _value: CREDENTIAL_REFERENCE
        else:
            classifier = _classify_secret
        _add_value_finding(
            findings,
            value,
            command_index,
            value_index,
            family,
            display or option,
            classifier,
        )
        index = value_index + 1 if attached is None else index + 1

    for argument_index, token in enumerate(tokens[1:], start=1):
        if argument_index in consumed:
            continue
        _add_finding(
            findings,
            command_index,
            argument_index,
            family,
            "url-userinfo",
            _classify_url_userinfo(token),
        )
    return incomplete


def _parse_powershell_headers(
    tokens: list[_Token],
    start: int,
    *,
    command_index: int,
    findings: list[CommandCredentialFinding],
) -> tuple[int, bool]:
    """Read only a literal hashtable or variable reference; never evaluate it."""
    if start >= len(tokens):
        return start, True
    token = tokens[start]
    value = token.value
    attached_start = (
        value.find("=") + 1 if value.casefold().startswith("-headers=") else 0
    )
    attached_value = token.fragment(attached_start) if attached_start else None
    if attached_value and not attached_value.value and start + 1 < len(tokens):
        next_token = tokens[start + 1]
        if next_token.value == "@{":
            token = next_token
            start += 1
            value = token.value
            attached_value = None
    if attached_value and attached_value.value and attached_value.value != "@{":
        _add_value_finding(
            findings,
            attached_value,
            command_index,
            start,
            "powershell-web",
            "-Headers",
            _classify_header,
        )
        return start + 1, False

    if value == "@{" or (attached_value and attached_value.value == "@{"):
        index = start + 1
        found_end = False
        while index < len(tokens):
            if tokens[index].value == "}":
                found_end = True
                return index + 1, not found_end
            if index + 2 < len(tokens):
                key = tokens[index]
                separator = tokens[index + 1].value
                header_value = tokens[index + 2]
                if (
                    separator in ("=", ":")
                    and key.value.strip("'\"").casefold() in _AUTH_HEADERS
                ):
                    header = _Token(
                        key.value.strip("'\"") + ": " + header_value.value,
                        tuple(
                            (
                                left + len(key.value.strip("'\"") + ": "),
                                right + len(key.value.strip("'\"") + ": "),
                            )
                            for left, right in header_value.variable_spans
                        ),
                    )
                    _add_value_finding(
                        findings,
                        header,
                        command_index,
                        index + 2,
                        "powershell-web",
                        "-Headers",
                        _classify_header,
                    )
                index += 3
                while index < len(tokens) and tokens[index].value == ",":
                    index += 1
                continue
            index += 1
        return len(tokens), True

    if token.is_reference or (attached_value and attached_value.is_reference):
        _add_finding(
            findings,
            command_index,
            start,
            "powershell-web",
            "-Headers",
            CREDENTIAL_REFERENCE,
        )
        return start + 1, False
    if _classify_header(token) is not None:
        _add_value_finding(
            findings,
            token,
            command_index,
            start,
            "powershell-web",
            "-Headers",
            _classify_header,
        )
        return start + 1, False
    return start + 1, True


def _scan_powershell_web(
    tokens: list[_Token],
    *,
    command_index: int,
    findings: list[CommandCredentialFinding],
) -> bool:
    incomplete = False
    consumed_parentheses: set[int] = set()
    index = 1
    while index < len(tokens):
        token = tokens[index]
        option = token.value.casefold()
        if option.startswith("-headers=") or option == "-headers":
            next_index = index + 1 if option == "-headers" else index
            index, failed = _parse_powershell_headers(
                tokens,
                next_index,
                command_index=command_index,
                findings=findings,
            )
            incomplete |= failed
            continue

        if option in ("-token", "-bearertoken"):
            value, value_index, missing = _target_option_value(tokens, index)
            if missing or value is None:
                incomplete = True
            else:
                consumed_parentheses.add(value_index)
                _add_value_finding(
                    findings,
                    value,
                    command_index,
                    value_index,
                    "powershell-web",
                    token.value,
                    _classify_secret,
                )
                index = value_index + 1
                continue

        if option == "-credential":
            if index + 1 >= len(tokens):
                incomplete = True
                index += 1
                continue
            value = tokens[index + 1]
            value_text = value.value.casefold()
            finding_class = None
            consumed = 1
            if value_text == "(" and index + 2 < len(tokens):
                following = tokens[index + 2].value.casefold()
                if following == "get-credential":
                    finding_class = INTERACTIVE_AUTH
                    has_close = (
                        index + 3 < len(tokens) and tokens[index + 3].value == ")"
                    )
                    consumed = 3 if has_close else 2
                    incomplete |= not has_close
                    consumed_parentheses.update(range(index + 1, index + consumed + 1))
                elif (
                    index + 3 < len(tokens)
                    and tokens[index + 2].is_reference
                    and tokens[index + 3].value == ")"
                ):
                    finding_class = CREDENTIAL_REFERENCE
                    consumed = 3
                    consumed_parentheses.update(range(index + 1, index + consumed + 1))
                else:
                    incomplete = True
            elif value_text == "get-credential":
                finding_class = INTERACTIVE_AUTH
            elif value.is_reference:
                finding_class = CREDENTIAL_REFERENCE
            elif value.value.startswith("-"):
                incomplete = True
            else:
                # A string is not a valid PSCredential object. Do not call it a
                # confirmed password; qualify the expression as unsupported.
                incomplete = True
            _add_finding(
                findings,
                command_index,
                index + 1,
                "powershell-web",
                "-Credential",
                finding_class,
            )
            index += consumed + 1
            continue

        if option in ("-uri", "-url"):
            value, value_index, missing = _target_option_value(tokens, index)
            if missing or value is None:
                incomplete = True
            else:
                _add_finding(
                    findings,
                    command_index,
                    value_index,
                    "powershell-web",
                    "url-userinfo",
                    _classify_url_userinfo(value),
                )
                index = value_index + 1
                continue

        # PowerShell's plaintext SecureString constructor is a supported literal
        # credential form only when paired with -AsPlainText in a web request.
        if option == "convertto-securestring":
            window = tokens[index + 1 : min(len(tokens), index + 7)]
            if any(item.value.casefold() == "-asplaintext" for item in window):
                value_index = index + 1
                if value_index < len(tokens) and tokens[
                    value_index
                ].value.casefold() in (
                    "-string",
                    "-asplaintext",
                    "-force",
                ):
                    value_index += 1
                if value_index < len(tokens) and not tokens[
                    value_index
                ].value.startswith("-"):
                    _add_value_finding(
                        findings,
                        tokens[value_index],
                        command_index,
                        value_index,
                        "powershell-web",
                        "ConvertTo-SecureString -AsPlainText",
                        _classify_secret,
                    )
                else:
                    incomplete = True

        index += 1

    for index, token in enumerate(tokens):
        if token.value in ("(", ")") and index not in consumed_parentheses:
            incomplete = True
    for argument_index, token in enumerate(tokens[1:], start=1):
        _add_finding(
            findings,
            command_index,
            argument_index,
            "powershell-web",
            "url-userinfo",
            _classify_url_userinfo(token),
        )
    return incomplete


def analyze_command_credentials(
    command: str, *, shell: Optional[str] = None
) -> CommandCredentialAnalysis:
    """Analyze a command using bounded tokenization and an explicit CLI registry.

    ``shell`` is primarily exposed for deterministic cross-platform tests. Auto
    mode recognizes PowerShell web cmdlets; other supported clients use the
    conservative POSIX/shared-quoting tokenizer. No shell expansion or execution
    is performed.
    """
    if not isinstance(command, str) or not command:
        return CommandCredentialAnalysis()
    if len(command) > MAX_COMMAND_CHARS:
        prefix = command.lstrip()[:4096]
        prefix_powershell = shell == "powershell" or (
            shell is None
            and re.search(
                r"(?i)\b(?:invoke-webrequest|iwr|invoke-restmethod|irm)\b",
                prefix,
            )
            is not None
        )
        prefix_segments, _ = _tokenize(prefix, powershell=prefix_powershell)
        for command_index, tokens in enumerate(prefix_segments):
            family, _wrapped = _family_for_segment(tokens, powershell=prefix_powershell)
            if family:
                return CommandCredentialAnalysis(
                    (
                        CommandCredentialFinding(
                            command_index,
                            0,
                            family,
                            "command-size-limit",
                            UNSUPPORTED_PARSE,
                        ),
                    ),
                    incomplete=True,
                )
        return CommandCredentialAnalysis()

    powershell = shell == "powershell" or (
        shell is None
        and re.search(
            r"(?i)\b(?:invoke-webrequest|iwr|invoke-restmethod|irm)\b", command
        )
        is not None
    )
    segments, tokenizer_incomplete = _tokenize(command, powershell=powershell)
    findings: list[CommandCredentialFinding] = []
    incomplete = False
    recognized_command = False

    for command_index, tokens in enumerate(segments):
        family, wrapped = _family_for_segment(tokens, powershell=powershell)
        if family is None:
            continue
        recognized_command = True
        if wrapped:
            findings.append(
                CommandCredentialFinding(
                    command_index,
                    0,
                    family,
                    "unsupported-wrapper",
                    UNSUPPORTED_PARSE,
                )
            )
            incomplete = True
            continue
        if family == "powershell-web":
            segment_incomplete = _scan_powershell_web(
                tokens,
                command_index=command_index,
                findings=findings,
            )
        else:
            segment_incomplete = _scan_http_client(
                tokens,
                family=family,
                command_index=command_index,
                findings=findings,
            )
        if segment_incomplete or tokenizer_incomplete:
            findings.append(
                CommandCredentialFinding(
                    command_index,
                    0,
                    family,
                    "unsupported-syntax",
                    UNSUPPORTED_PARSE,
                )
            )
            incomplete = True

    if tokenizer_incomplete and recognized_command:
        incomplete = True
    if (
        incomplete
        and recognized_command
        and not any(item.finding_class == UNSUPPORTED_PARSE for item in findings)
    ):
        findings.append(
            CommandCredentialFinding(
                0,
                0,
                next(
                    (
                        item.command_family
                        for item in findings
                        if item.command_family != "unknown"
                    ),
                    "unknown",
                ),
                "unsupported-syntax",
                UNSUPPORTED_PARSE,
            )
        )
    # Bound output even if many commands contain repeated credential options.
    findings = findings[:128]
    return CommandCredentialAnalysis(tuple(findings), incomplete)


def _effective_action(config: object) -> str:
    action = config.get("action", "block") if isinstance(config, dict) else "block"
    return action if isinstance(action, str) and action in _VALID_ACTIONS else "block"


def _result(
    analysis: CommandCredentialAnalysis,
    action: str,
) -> Optional[ScanResult]:
    if not analysis.findings:
        return None
    inline = any(item.finding_class == INLINE_LITERAL for item in analysis.findings)
    incomplete = any(
        item.finding_class == UNSUPPORTED_PARSE for item in analysis.findings
    )
    actionable = inline or incomplete
    should_block = actionable and action in ("block", "ask")
    if inline:
        severity = "high"
        message = (
            ASK_MESSAGE
            if action == "ask"
            else BLOCK_MESSAGE if action == "block" else WARN_MESSAGE
        )
        if action == "log-only":
            message = ""
    elif incomplete:
        severity = "medium"
        message = {
            "block": INCOMPLETE_BLOCK_MESSAGE,
            "ask": INCOMPLETE_ASK_MESSAGE,
            "warn": INCOMPLETE_WARN_MESSAGE,
            "log-only": "",
        }[action]
    else:
        severity = "info"
        message = REFERENCE_MESSAGE

    return ScanResult(
        detected=True,
        violation_type=VIOLATION_TYPE,
        should_block=should_block,
        severity=severity,
        rule_id="COMMAND-CREDENTIAL-001",
        error_message=message,
        engine=ENGINE,
        config_section=CONFIG_SECTION,
        total_findings=len(analysis.findings),
        findings=[asdict(item) for item in analysis.findings],
        extra={
            "action": action if actionable else "warn",
            "analysis_incomplete": incomplete,
            "finding_classes": sorted(
                {item.finding_class for item in analysis.findings}
            ),
        },
    )


def run_command_credential_scan(
    command: str,
    *,
    config: Optional[dict] = None,
    shell: Optional[str] = None,
    **_kwargs,
) -> Optional[ScanResult]:
    """Return a value-free result for a supported command credential argument."""
    try:
        analysis = analyze_command_credentials(command, shell=shell)
    except (TypeError, ValueError, IndexError):
        logger.warning("Command credential analysis failed; command details withheld")
        analysis = CommandCredentialAnalysis(
            (
                CommandCredentialFinding(
                    0, 0, "unknown", "parser-failure", UNSUPPORTED_PARSE
                ),
            ),
            incomplete=True,
        )
    if not analysis.findings:
        return None

    if config is None:
        from ai_guardian.config.loaders import _load_command_credential_scanning_config

        config, _ = _load_command_credential_scanning_config()
    if isinstance(config, dict) and config.get("enabled") is False:
        return None

    action = _effective_action(config)
    return _result(analysis, action)
