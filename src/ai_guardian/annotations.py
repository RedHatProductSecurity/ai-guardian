"""
Annotation-based suppression for ai-guardian scanning.

Supports inline and block annotations to suppress violations on specific lines.
Hardcoded markers (always active):
  - ai-guardian:allow         (inline, all violations)
  - ai-guardian:begin-allow   (block start, all violations)
  - ai-guardian:end-allow     (block end, all violations)

Configurable aliases (extend defaults, never replace):
  - inline_allow:             user aliases that suppress all violations
  - inline_allow_secrets:     user aliases that suppress secrets only (default: gitleaks:allow, notsecret)
  - block_begin / block_end:  user aliases for block markers
"""

import logging
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

INLINE_MARKER = "ai-guardian:allow"
BLOCK_BEGIN_MARKER = "ai-guardian:begin-allow"
BLOCK_END_MARKER = "ai-guardian:end-allow"

DEFAULT_INLINE_ALLOW_ALIASES: List[str] = []
DEFAULT_SECRET_ALIASES: List[str] = ["gitleaks:allow"]
DEFAULT_BLOCK_BEGIN_ALIASES: List[str] = []
DEFAULT_BLOCK_END_ALIASES: List[str] = []


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


def get_suppressed_lines(
    content: str,
    config: Optional[Dict] = None,
) -> Tuple[Set[int], Set[int], List[Dict], List[str]]:
    """
    Find line indices suppressed by annotations.

    Returns:
        all_suppressed: 0-based line indices suppressed for ALL scanners
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

    # First pass: find matched block pairs
    # Collect all begin/end positions, then pair them (stack-based)
    block_begins: List[int] = []
    block_ends: List[int] = []
    for i, line in enumerate(lines):
        if _is_block_begin(line, block_begin_aliases):
            block_begins.append(i)
        elif _is_block_end(line, block_end_aliases):
            block_ends.append(i)

    # Pair begin/end markers using a stack
    # Process in order, pairing each end with the most recent unmatched begin
    matched_pairs: List[Tuple[int, int]] = []
    stack: List[int] = []
    events = [(i, "begin") for i in block_begins] + [(i, "end") for i in block_ends]
    events.sort(key=lambda x: x[0])

    for idx, event_type in events:
        if event_type == "begin":
            stack.append(idx)
        elif event_type == "end":
            if stack:
                begin_idx = stack.pop()
                matched_pairs.append((begin_idx, idx))
            # Unmatched end-allow: silently ignored

    # Unmatched begin-allow: emit warnings, do NOT suppress
    for remaining in stack:
        warnings.append(
            f"Warning: Unmatched ai-guardian:begin-allow at line {remaining + 1} — ignored"
        )

    # Mark all lines in matched blocks as suppressed (including begin/end marker lines)
    for begin_idx, end_idx in matched_pairs:
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
            if _is_secret_only(line, secret_aliases):
                secret_only_suppressed.add(i)
            continue

        if _is_inline_allow(line, inline_allow_aliases):
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


def apply_suppressions(content: str, suppressed_lines: Set[int]) -> str:
    """Replace suppressed lines with empty strings, preserving line count."""
    if not suppressed_lines:
        return content
    lines = content.splitlines()
    for i in suppressed_lines:
        if 0 <= i < len(lines):
            lines[i] = ""
    return "\n".join(lines)


def process_annotations(
    content: str,
    file_path: Optional[str] = None,
    config: Optional[Dict] = None,
) -> Tuple[str, str, List[Dict], List[str]]:
    """
    Process annotations and return two versions of content.

    Returns:
        content_all_suppressed: for PII, prompt injection, config scanners
            (lines with ai-guardian:allow or in blocks are blanked)
        content_secret_suppressed: for secret scanner
            (above + lines with gitleaks:allow/notsecret are also blanked)
        suppression_info: audit metadata
        warnings: annotation warnings
    """
    all_suppressed, secret_only_suppressed, suppression_info, warnings = (
        get_suppressed_lines(content, config)
    )

    if not all_suppressed and not secret_only_suppressed:
        return content, content, [], warnings

    # Add file_path to suppression info entries
    if file_path:
        for info in suppression_info:
            info["file_path"] = file_path

    content_all_suppressed = apply_suppressions(content, all_suppressed)
    content_secret_suppressed = apply_suppressions(
        content, all_suppressed | secret_only_suppressed
    )

    logger.info(
        f"Annotations: {len(all_suppressed)} line(s) fully suppressed, "
        f"{len(secret_only_suppressed)} line(s) secrets-only suppressed"
    )

    return content_all_suppressed, content_secret_suppressed, suppression_info, warnings
