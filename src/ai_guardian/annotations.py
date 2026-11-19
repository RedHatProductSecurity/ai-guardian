"""
Annotation-based suppression for ai-guardian scanning.

Supports inline and block annotations to suppress violations on specific lines.
Hardcoded markers (always active):
  - ai-guardian:allow         (inline, all file-content findings)
  - ai-guardian:begin-allow   (block start, all file-content findings)
  - ai-guardian:end-allow     (block end, all violations)

Configurable aliases (extend defaults, never replace):
  - inline_allow:             user aliases that suppress all file findings
  - inline_allow_secrets:     user aliases that suppress secrets only (default: gitleaks:allow, notsecret)
  - block_begin / block_end:  user aliases for block markers
"""

import logging
import mimetypes
import os
import re
import stat
from typing import Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

INLINE_MARKER = "ai-guardian:allow"
BLOCK_BEGIN_MARKER = "ai-guardian:begin-allow"
BLOCK_END_MARKER = "ai-guardian:end-allow"

DEFAULT_INLINE_ALLOW_ALIASES: List[str] = []
DEFAULT_SECRET_ALIASES: List[str] = ["gitleaks:allow"]
DEFAULT_BLOCK_BEGIN_ALIASES: List[str] = []
DEFAULT_BLOCK_END_ALIASES: List[str] = []
MAX_ANNOTATION_SOURCE_CHARS = 4 * 1024 * 1024

_SCANNER_TYPE_ALIASES = {
    "secret": "secret_scanning",
    "pii": "scan_pii",
    "config_file": "config_file_scanning",
    "config_exfil": "config_file_scanning",
    "code_security": "code_scanning",
    "scan_offensive": "offensive_language",
    "image": "image_scanning",
    "ssrf": "ssrf_protection",
    "canary": "canary_detection",
    "unicode": "unicode_detection",
}
_SCANNER_TYPES = frozenset(
    {
        "secret_scanning",
        "password_likelihood",
        "scan_pii",
        "prompt_injection",
        "context_poisoning",
        "ssrf_protection",
        "config_file_scanning",
        "code_scanning",
        "supply_chain",
        "offensive_language",
        "exfil_detection",
        "canary_detection",
        "unicode_detection",
        "image_scanning",
        "command_credential_scanning",
        "http_request_credential_scanning",
        "directory_rules",
    }
    | set(_SCANNER_TYPE_ALIASES)
)


def _build_alias_lists(
    config: Optional[Dict] = None,
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """Build merged alias lists from defaults + user config."""
    if config is None:
        config = {}

    inline_allow = list(DEFAULT_INLINE_ALLOW_ALIASES)
    for alias in config.get("inline_allow", []):
        if alias not in inline_allow:
            inline_allow.append(alias)

    secret_aliases = list(DEFAULT_SECRET_ALIASES)
    for alias in config.get("inline_allow_secrets", []):
        if alias not in secret_aliases:
            secret_aliases.append(alias)

    block_begin = list(DEFAULT_BLOCK_BEGIN_ALIASES)
    for alias in config.get("block_begin", []):
        if alias not in block_begin:
            block_begin.append(alias)

    block_end = list(DEFAULT_BLOCK_END_ALIASES)
    for alias in config.get("block_end", []):
        if alias not in block_end:
            block_end.append(alias)

    return inline_allow, secret_aliases, block_begin, block_end


def _is_block_begin(line: str, block_begin_aliases: List[str]) -> bool:
    if BLOCK_BEGIN_MARKER in line:
        return True
    return any(alias in line for alias in block_begin_aliases)


def _is_block_end(line: str, block_end_aliases: List[str]) -> bool:
    if BLOCK_END_MARKER in line:
        return True
    return any(alias in line for alias in block_end_aliases)


def _is_inline_allow(line: str, inline_allow_aliases: List[str]) -> bool:
    """Check for inline all-violation suppression (not block markers)."""
    if BLOCK_BEGIN_MARKER in line or BLOCK_END_MARKER in line:
        return False
    if INLINE_MARKER in line:
        return True
    return any(alias in line for alias in inline_allow_aliases)


def _is_secret_only(line: str, secret_aliases: List[str]) -> bool:
    return any(alias in line for alias in secret_aliases)


def canonical_scanner_type(scanner_type: Optional[str]) -> Optional[str]:
    """Normalize public scanner names and accepted annotation aliases."""
    if scanner_type is None:
        return None
    return _SCANNER_TYPE_ALIASES.get(scanner_type, scanner_type)


def find_source_excerpt_line_offset(source_content: str, excerpt: str) -> Optional[int]:
    """Locate a unique, whole-line excerpt in its source and return its first line.

    Ambiguous, partial-line, or non-matching excerpts are deliberately not
    mapped, so source annotations cannot suppress findings based on a guess.
    The returned offset is zero-based.
    """
    if not excerpt:
        return None
    if excerpt == source_content:
        return 0

    start = source_content.find(excerpt)
    if start < 0 or source_content.find(excerpt, start + 1) >= 0:
        return None
    if start and source_content[start - 1] not in "\r\n":
        return None

    end = start + len(excerpt)
    if (
        end < len(source_content)
        and source_content[end] not in "\r\n"
        and not excerpt.endswith(("\r", "\n"))
    ):
        return None

    prefix = source_content[:start]
    return prefix.count("\n") + prefix.count("\r") - prefix.count("\r\n")


def read_annotation_source(file_path: Optional[str]) -> Optional[str]:
    """Read a small regular text source for excerpt annotation context.

    Large, non-regular, binary, and unreadable paths are ignored so annotation
    context lookup stays bounded and falls back to scanning the supplied text.
    """
    if not isinstance(file_path, str) or not file_path:
        return None
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type and (
        mime_type.startswith(("image/", "audio/", "video/"))
        or mime_type == "application/pdf"
    ):
        return None
    try:
        metadata = os.stat(file_path)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > MAX_ANNOTATION_SOURCE_CHARS
        ):
            return None
        with open(file_path, "r", encoding="utf-8", errors="replace") as source:
            content = source.read(MAX_ANNOTATION_SOURCE_CHARS + 1)
        return content if len(content) <= MAX_ANNOTATION_SOURCE_CHARS else None
    except OSError:
        logger.debug("Could not load source context for annotations")
        return None


def _get_scanner_scope(line: str, marker: str) -> Optional[Set[str]]:
    """Return recognized scanner qualifiers following a hardcoded marker."""
    matches = list(re.finditer(re.escape(marker), line))
    if not matches:
        return None

    scope: Set[str] = set()
    for index, match in enumerate(matches):
        suffix_end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(line)
        )
        suffix = line[match.end() : suffix_end].strip()
        for comment_end in ("-->", "*/"):
            suffix = suffix.removesuffix(comment_end).strip()
        suffix = suffix.rstrip("#/").strip()
        if not suffix:
            # One unqualified marker makes the whole line unqualified.
            return None

        scanner_types = re.split(r"[\s,]+", suffix)
        if not scanner_types or any(
            scanner_type not in _SCANNER_TYPES for scanner_type in scanner_types
        ):
            # Preserve legacy behavior for annotations followed by explanatory text.
            return None
        scope.update(
            canonical_scanner_type(scanner_type) or scanner_type
            for scanner_type in scanner_types
        )

    return scope


def _scope_applies(scope: Optional[Set[str]], scanner_type: Optional[str]) -> bool:
    """Unqualified markers apply globally; qualified markers need a known match."""
    if scope is None:
        return True
    if scanner_type is None:
        return False
    return canonical_scanner_type(scanner_type) in scope


def get_suppressed_lines(
    content: str,
    config: Optional[Dict] = None,
    scanner_type: Optional[str] = None,
) -> Tuple[Set[int], Set[int], List[Dict], List[str]]:
    """
    Find line indices suppressed by annotations for an optional scanner type.

    Returns:
        all_suppressed: 0-based line indices suppressed for matching scanners
        secret_only_suppressed: 0-based line indices suppressed for secrets only
        suppression_info: audit metadata (1-based line numbers for display)
        warnings: annotation warnings (e.g., unmatched begin-allow)
    """
    inline_allow_aliases, secret_aliases, block_begin_aliases, block_end_aliases = (
        _build_alias_lists(config)
    )

    lines = content.splitlines()
    all_suppressed: Set[int] = set()
    secret_only_suppressed: Set[int] = set()
    suppression_info: List[Dict] = []
    warnings: List[str] = []

    scanner_type = canonical_scanner_type(scanner_type)

    # First pass: find matched block pairs
    # Collect all begin/end positions, then pair them (stack-based)
    block_begins: List[Tuple[int, Optional[Set[str]]]] = []
    block_ends: List[int] = []
    for i, line in enumerate(lines):
        if _is_block_begin(line, block_begin_aliases):
            scope = (
                _get_scanner_scope(line, BLOCK_BEGIN_MARKER)
                if BLOCK_BEGIN_MARKER in line
                else None
            )
            block_begins.append((i, scope))
        elif _is_block_end(line, block_end_aliases):
            block_ends.append(i)

    # Pair begin/end markers using a stack
    # Process in order, pairing each end with the most recent unmatched begin
    matched_pairs: List[Tuple[int, int, Optional[Set[str]]]] = []
    stack: List[Tuple[int, Optional[Set[str]]]] = []
    events = [(i, "begin", scope) for i, scope in block_begins] + [
        (i, "end", None) for i in block_ends
    ]
    events.sort(key=lambda x: x[0])

    for idx, event_type, scope in events:
        if event_type == "begin":
            stack.append((idx, scope))
        elif event_type == "end":
            if stack:
                begin_idx, begin_scope = stack.pop()
                matched_pairs.append((begin_idx, idx, begin_scope))
            # Unmatched end-allow: silently ignored

    # Unmatched begin-allow: emit warnings, do NOT suppress
    for remaining, _scope in stack:
        warnings.append(
            f"Warning: Unmatched ai-guardian:begin-allow at line {remaining + 1} — ignored"
        )

    # Mark all lines in matched blocks as suppressed (including begin/end marker lines)
    for begin_idx, end_idx, scope in matched_pairs:
        if not _scope_applies(scope, scanner_type):
            continue
        block_lines = list(range(begin_idx, end_idx + 1))
        all_suppressed.update(block_lines)
        suppression_info.append(
            {
                "type": "block",
                "lines": [ln + 1 for ln in block_lines],
                "annotation_line": begin_idx + 1,
            }
        )

    # Second pass: inline annotations
    for i, line in enumerate(lines):
        if i in all_suppressed:
            # Already suppressed by block — check for secret-only markers too
            if scanner_type in (None, "secret_scanning") and _is_secret_only(
                line, secret_aliases
            ):
                secret_only_suppressed.add(i)
            continue

        if _is_inline_allow(line, inline_allow_aliases):
            scope = (
                _get_scanner_scope(line, INLINE_MARKER)
                if INLINE_MARKER in line
                else None
            )
            if not _scope_applies(scope, scanner_type):
                continue
            all_suppressed.add(i)
            suppressed_display = [i + 1]
            if i + 1 < len(lines):
                all_suppressed.add(i + 1)
                suppressed_display.append(i + 2)
            suppression_info.append(
                {
                    "type": "inline",
                    "lines": suppressed_display,
                    "annotation_line": i + 1,
                }
            )
        elif _is_secret_only(line, secret_aliases):
            if scanner_type not in (None, "secret_scanning"):
                continue
            secret_only_suppressed.add(i)
            suppressed_display = [i + 1]
            if i + 1 < len(lines):
                secret_only_suppressed.add(i + 1)
                suppressed_display.append(i + 2)
            suppression_info.append(
                {
                    "type": "inline_secrets",
                    "lines": suppressed_display,
                    "annotation_line": i + 1,
                }
            )

    return all_suppressed, secret_only_suppressed, suppression_info, warnings


def apply_suppressions(
    content: str, suppressed_lines: Set[int], *, preserve_offsets: bool = False
) -> str:
    """Blank suppressed lines, optionally preserving character offsets."""
    if not suppressed_lines:
        return content
    if not preserve_offsets:
        lines = content.splitlines()
        for i in suppressed_lines:
            if 0 <= i < len(lines):
                lines[i] = ""
        return "\n".join(lines)

    lines = content.splitlines(keepends=True)
    for i in suppressed_lines:
        if 0 <= i < len(lines):
            lines[i] = "".join(char if char in "\r\n" else " " for char in lines[i])
    return "".join(lines)


def process_annotations(
    content: str,
    file_path: Optional[str] = None,
    config: Optional[Dict] = None,
    scanner_type: Optional[str] = None,
) -> Tuple[str, str, List[Dict], List[str]]:
    """
    Process annotations and return filtered content for an optional scanner.

    Returns:
        content_all_suppressed: lines matched by all-scanner or matching
            scanner-qualified annotations are blanked
        content_secret_suppressed: above plus secrets-only aliases when the
            selected scanner is secret scanning
        suppression_info: audit metadata
        warnings: annotation warnings
    """
    scanner_type = canonical_scanner_type(scanner_type)
    all_suppressed, secret_only_suppressed, suppression_info, warnings = (
        get_suppressed_lines(content, config, scanner_type=scanner_type)
    )

    if not all_suppressed and not secret_only_suppressed:
        return content, content, [], warnings

    # Add file_path to suppression info entries
    if file_path:
        for suppression_entry in suppression_info:
            suppression_entry["file_path"] = file_path

    content_all_suppressed = apply_suppressions(content, all_suppressed)
    content_secret_suppressed = (
        apply_suppressions(content, all_suppressed | secret_only_suppressed)
        if scanner_type in (None, "secret_scanning")
        else content_all_suppressed
    )

    logger.info(
        f"Annotations: {len(all_suppressed)} line(s) fully suppressed, "
        f"{len(secret_only_suppressed)} line(s) secrets-only suppressed"
    )

    return content_all_suppressed, content_secret_suppressed, suppression_info, warnings


def process_annotations_by_scanner(
    content: str,
    scanner_types: Iterable[str],
    file_path: Optional[str] = None,
    config: Optional[Dict] = None,
    source_content: Optional[str] = None,
) -> Tuple[Dict[str, str], List[Dict], List[str]]:
    """Return scanner-filtered content, optionally inheriting verified source context.

    When *content* is a unique whole-line excerpt of *source_content*, block and
    inline suppressions are resolved against the full source and projected onto
    the excerpt. Otherwise annotations are parsed only from *content*.
    """
    content_by_scanner: Dict[str, str] = {}
    suppression_info: List[Dict] = []
    warnings: List[str] = []
    seen_info: Set[Tuple[str, int, Tuple[int, ...]]] = set()
    seen_warnings: Set[str] = set()
    suppressed_lines: Set[int] = set()
    secret_suppressed_lines: Set[int] = set()
    source_line_offset = (
        find_source_excerpt_line_offset(source_content, content)
        if source_content is not None
        else None
    )
    if source_content is not None and source_line_offset is not None:
        annotation_content = source_content
    else:
        annotation_content = content
    excerpt_line_count = len(content.splitlines())

    for scanner_type in dict.fromkeys(
        canonical_scanner_type(item) or item for item in scanner_types
    ):
        all_lines, secret_lines, info, scanner_warnings = get_suppressed_lines(
            annotation_content, config, scanner_type=scanner_type
        )
        if source_line_offset is not None:
            source_start = source_line_offset
            source_end = source_start + excerpt_line_count
            all_lines = {
                line - source_start
                for line in all_lines
                if source_start <= line < source_end
            }
            secret_lines = {
                line - source_start
                for line in secret_lines
                if source_start <= line < source_end
            }
            projected_info = []
            for entry in info:
                overlapping_lines = [
                    line for line in entry["lines"] if source_start < line <= source_end
                ]
                if overlapping_lines:
                    projected_entry = dict(entry)
                    projected_entry["lines"] = overlapping_lines
                    projected_info.append(projected_entry)
            info = projected_info

        scanner_suppressions = all_lines
        if scanner_type == "secret_scanning":
            scanner_suppressions = all_lines | secret_lines
            secret_suppressed_lines.update(secret_lines)
        suppressed_lines.update(all_lines)
        content_by_scanner[scanner_type] = apply_suppressions(
            content, scanner_suppressions, preserve_offsets=True
        )

        for item in info:
            key = (
                item["type"],
                item["annotation_line"],
                tuple(item["lines"]),
            )
            if key in seen_info:
                continue
            seen_info.add(key)
            suppression_info.append(dict(item))
        for warning in scanner_warnings:
            if warning not in seen_warnings:
                seen_warnings.add(warning)
                warnings.append(warning)

    if file_path:
        for suppression_entry in suppression_info:
            suppression_entry["file_path"] = file_path

    if suppressed_lines or secret_suppressed_lines:
        logger.info(
            "Annotations: %d line(s) fully suppressed, %d line(s) secrets-only suppressed",
            len(suppressed_lines),
            len(secret_suppressed_lines),
        )

    return content_by_scanner, suppression_info, warnings
