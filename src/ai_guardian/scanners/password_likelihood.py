"""Bounded, offline suspected-password heuristics, never password identification.

Only locations and fixed labels leave this module. There is no dictionary,
network, file access, candidate cache, strength estimator, or learned model.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Iterable

from ai_guardian.patterns.validators import shannon_entropy
from ai_guardian.scanners.scan_result import ScanResult

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 262_144
MAX_CANDIDATE_CHARS = 128
MAX_CANDIDATES = 4096
MAX_FINDINGS = 128
MESSAGE = (
    "Suspected password-like content detected (heuristic; not a confirmed secret)."
)
INCOMPLETE_MESSAGE = (
    "Password-likelihood analysis incomplete; protection is not assured."
)

_CONTEXT = re.compile(
    r"\b(?:password|passphrase)\b[ \t]{0,8}(?:is[ \t]{1,8}|[:=][ \t]{0,8})",
    re.IGNORECASE | re.ASCII,
)
_TOKENS = re.compile(r"[^\s\"'`]+")
_WORDS = re.compile(r"[A-Za-z]{3,16}")
_CAMEL = re.compile(r"[A-Z][a-z]{2,15}")
_HEX = re.compile(r"[0-9a-fA-F]+")
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


@dataclass(frozen=True)
class PasswordSpan:
    """Zero-based half-open character offsets; line numbers are one-based."""

    start: int
    end: int
    line_number: int
    start_column: int
    end_column: int
    candidate_class: str
    confidence_class: str


@dataclass(frozen=True)
class PasswordAnalysis:
    findings: tuple[PasswordSpan, ...] = ()
    incomplete: bool = False


def _candidate_class(value: str, *, contextual: bool) -> str | None:
    if not 12 <= len(value) <= MAX_CANDIDATE_CHARS or not value.isascii():
        return None
    if not all(32 <= ord(char) < 127 for char in value):
        return None

    # Word-like values are considered ONLY after a narrowly bounded credential
    # cue. These are structural classes, not dictionary/segmentation claims.
    if contextual:
        words = _WORDS.findall(value)
        parts = re.split(r"[ _-]", value)
        if (
            3 <= len(words) <= 8
            and 3 <= len(parts) <= 8
            and all(part.isalpha() for part in parts)
        ):
            return "spaced_passphrase" if " " in value else "separated_passphrase"
        if (
            3 <= len(_CAMEL.findall(value)) <= 8
            and "".join(_CAMEL.findall(value)) == value
        ):
            return "camelcase_passphrase"
        if 18 <= len(value) <= 64 and value.isalpha() and value.islower():
            return "joined_word_like"

    if " " in value or len(value) < 14:
        return None
    lower = any(char.islower() for char in value)
    upper = any(char.isupper() for char in value)
    digit = any(char.isdigit() for char in value)
    symbol = any(not char.isalnum() for char in value)
    diverse = (
        (lower or upper) and (digit or symbol)
        if contextual
        else lower and upper and (digit or symbol)
    )
    if not diverse:
        return None
    if shannon_entropy(value) < 3.6 or len(set(value)) / len(value) < 0.55:
        return None
    if not contextual:
        # Confusable forms lower ONLY this heuristic's score, never a stronger
        # scanner's finding. Credential context can still flag these forms.
        if (
            _HEX.fullmatch(value)
            or _UUID.fullmatch(value)
            or any(char in value for char in "/\\.:=_")
            or value.startswith(("$", "@", "--"))
        ):
            return None
    return "mixed_symbol" if symbol else "random_alphanumeric"


def _locate_spans(spans, offset, line_number) -> list[PasswordSpan]:
    return [
        PasswordSpan(
            offset + start, offset + end, line_number, start, end, kind, confidence
        )
        for (start, end), (kind, confidence) in sorted(spans.items())
    ]


def analyze_password_likelihood(text: str) -> PasswordAnalysis:
    """Analyze supported ASCII spans within fixed work/memory budgets.

    Over-budget input is explicitly incomplete, not silently reported clean.
    Context-free arbitrary words, sentences and multilingual segmentation are
    intentionally unsupported. No caller-supplied policy is parsed from text.
    """
    if len(text) > MAX_INPUT_CHARS:
        return PasswordAnalysis(incomplete=True)
    findings: list[PasswordSpan] = []
    incomplete = False
    examined = 0
    offset = 0
    for line_number, line in enumerate(text.splitlines(keepends=True), 1):
        spans: dict[tuple[int, int], tuple[str, str]] = {}
        for cue in _CONTEXT.finditer(line):
            examined += 1
            if examined > MAX_CANDIDATES:
                return PasswordAnalysis(
                    tuple(findings + _locate_spans(spans, offset, line_number)),
                    incomplete=True,
                )
            start = cue.end()
            if start >= len(line):
                continue
            if line[start] in "\"'`":
                quote = line[start]
                start += 1
                end = line.find(quote, start, start + MAX_CANDIDATE_CHARS + 1)
                if end < 0 or "\\" in line[start:end]:
                    continue  # escaped/multiline quoted values are not qualified
            else:
                token = _TOKENS.match(line, start)
                if token is None:
                    continue
                end = token.end()
            kind = _candidate_class(line[start:end], contextual=True)
            if kind:
                spans[start, end] = (kind, "contextual")
                if len(findings) + len(spans) >= MAX_FINDINGS:
                    # Bound subsequent overlap tests as well as reported output.
                    return PasswordAnalysis(
                        tuple(findings + _locate_spans(spans, offset, line_number)),
                        incomplete=True,
                    )

        for token in _TOKENS.finditer(line):
            examined += 1
            if examined > MAX_CANDIDATES:
                return PasswordAnalysis(
                    tuple(findings + _locate_spans(spans, offset, line_number)),
                    incomplete=True,
                )
            start, end = token.span()
            if end - start > MAX_CANDIDATE_CHARS:
                incomplete = True
                continue
            if any(left <= start and end <= right for left, right in spans):
                continue
            kind = _candidate_class(token.group(), contextual=False)
            if kind:
                spans[start, end] = (kind, "ambiguous")
                if len(findings) + len(spans) >= MAX_FINDINGS:
                    return PasswordAnalysis(
                        tuple(findings + _locate_spans(spans, offset, line_number)),
                        incomplete=True,
                    )

        findings.extend(_locate_spans(spans, offset, line_number))
        offset += len(line)
    return PasswordAnalysis(tuple(findings), incomplete)


def _result(analysis: PasswordAnalysis, action: str) -> ScanResult:
    findings = [asdict(span) for span in analysis.findings]
    contextual = any(f["confidence_class"] == "contextual" for f in findings)
    block = action in ("ask", "block") and (contextual or analysis.incomplete)
    first = findings[0] if findings else {}
    return ScanResult(
        detected=bool(findings),
        violation_type="suspected_password",
        should_block=block,
        severity="medium",
        error_message=(
            INCOMPLETE_MESSAGE if analysis.incomplete else MESSAGE if findings else ""
        ),
        line_number=first.get("line_number"),
        start_column=first.get("start_column"),
        end_column=first.get("end_column"),
        findings=findings,
        total_findings=len(findings),
        engine="local-password-likelihood",
        config_section="password_likelihood",
        extra={
            "action": action if block else "warn",
            "incomplete": analysis.incomplete,
        },
    )


def incomplete_password_scan(config) -> ScanResult:
    """A generic failed analysis, not a positive match or a raw exception."""
    action = config.get("action", "ask") if isinstance(config, dict) else "ask"
    if action not in ("ask", "warn", "block"):
        action = "block"
    return _result(PasswordAnalysis(incomplete=True), action)


def run_password_likelihood_scan(content, *, config=None, file_path=None, **_kwargs):
    """Registry runner. Only literal trusted opt-in activates this stage."""
    if config is None:
        from ai_guardian.config.loaders import _load_password_likelihood_config

        config, _ = _load_password_likelihood_config()
    if not isinstance(config, dict) or config.get("enabled") is not True or not content:
        return None
    action = config.get("action", "ask")
    if action not in ("ask", "warn", "block"):
        action = "block"  # malformed opted-in enforcement must not weaken policy
    try:
        analysis = analyze_password_likelihood(content)
    except Exception:
        # Exception strings/tracebacks can contain the input. Never log them.
        logger.warning("Password-likelihood analysis failed; details withheld")
        analysis = PasswordAnalysis(incomplete=True)
    result = _result(analysis, action)
    result.file_path = file_path
    return result


def exclude_credential_overlaps(
    result: ScanResult, stronger: Iterable[ScanResult]
) -> ScanResult:
    """Remove only spans fully covered by a stronger blocking credential match.

    Missing/uncertain coordinates are NOT evidence of overlap. No stronger
    detection is ever changed, even when a heuristic considers a value benign.
    """
    covered = [
        finding
        for other in stronger
        if other.violation_type == "secret_detected"
        and other.detected
        and other.should_block
        for finding in (other.findings or [])
        if isinstance(finding, dict)
        and isinstance(finding.get("start_column"), int)
        and isinstance(finding.get("end_column"), int)
    ]
    if not covered or not result.findings:
        return result
    remaining = tuple(
        PasswordSpan(**span)
        for span in result.findings
        if not any(
            finding.get("line_number") == span["line_number"]
            and finding["start_column"] <= span["start_column"]
            and finding["end_column"] >= span["end_column"]
            for finding in covered
        )
    )
    filtered = _result(
        PasswordAnalysis(remaining, result.extra.get("incomplete", False)),
        result.extra.get("action", "warn"),
    )
    filtered.file_path = result.file_path
    return filtered


def run_tool_input_password_scan(tool_input):
    """Scan argument string values, not JSON-escaped text or policy-like keys.

    Locations refer to string values joined with newlines in traversal order.
    Traversal, depth, aggregate characters and scanning are independently bounded.
    Never call repr/str on arbitrary tool objects or serialize candidate text.
    """
    from ai_guardian.config.loaders import _load_password_likelihood_config

    config, _ = _load_password_likelihood_config()
    if not isinstance(config, dict) or config.get("enabled") is not True:
        return None
    strings: list[str] = []
    pending = [iter((tool_input,))]
    exhausted = object()
    size = 0
    nodes = 0
    while pending:
        value = next(pending[-1], exhausted)
        if value is exhausted:
            pending.pop()
            continue
        nodes += 1
        if nodes > MAX_CANDIDATES or len(pending) > 16:
            break
        if isinstance(value, str):
            size += len(value) + 1
            if size > MAX_INPUT_CHARS:
                break
            strings.append(value)
        elif isinstance(value, dict):
            pending.append(iter(value.values()))
        elif isinstance(value, (list, tuple)):
            pending.append(iter(value))
    else:
        return run_password_likelihood_scan("\n".join(strings), config=config)
    return incomplete_password_scan(config)


def redact_password_likelihood(text: str, *, config=None):
    """Privacy sanitization, not a claim about a host's model boundary.

    Replace complete unions of all spans, including ambiguous/repeated matches.
    Incomplete analysis withholds the entire text instead of leaving a possibly
    unexamined suffix. Never use legacy prefix/suffix masking for this class.
    """
    result = run_password_likelihood_scan(text, config=config)
    if result is None:
        return text, []
    if result.extra.get("incomplete"):
        return "[CONTENT WITHHELD: PASSWORD-LIKELIHOOD ANALYSIS INCOMPLETE]", [
            {"type": "suspected_password", "position": 0, "strategy": "withhold"}
        ]
    intervals: list[tuple[int, int]] = []
    for span in sorted(result.findings or [], key=lambda item: item["start"]):
        start, end = span["start"], span["end"]
        if intervals and start <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(end, intervals[-1][1]))
        else:
            intervals.append((start, end))
    parts: list[str] = []
    previous = 0
    redactions = []
    for start, end in intervals:
        parts.extend((text[previous:start], "[SUSPECTED PASSWORD REDACTED]"))
        previous = end
        redactions.append(
            {"type": "suspected_password", "position": start, "strategy": "full_span"}
        )
    parts.append(text[previous:])
    return "".join(parts), redactions
