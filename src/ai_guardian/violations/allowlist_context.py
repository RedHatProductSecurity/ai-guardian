"""Safe source context retained for deferred violation resolution.

Hook scanners often inspect a temporary copy of content.  This module keeps
enough non-sensitive metadata to locate the original source line later,
without putting the detected value in ``violations.jsonl``.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Any, Dict, Iterable, Optional, Tuple

from ai_guardian.violations.utils import is_temp_path

_CONTEXT_LINES_EACH_SIDE = 2
_MAX_CONTEXT_LINE_CHARS = 500
_MAX_CONTEXT_CHARS = 2000
_PLACEHOLDER_PATHS = frozenset({"", "input", "unknown", "temp_file", "user_prompt"})


def _as_line_number(value: Any) -> Optional[int]:
    """Return a positive integer line number, or ``None``."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _normalise_source_path(path: Any) -> Optional[str]:
    """Return an absolute, non-temporary source path suitable for logging."""
    if not path:
        return None
    try:
        value = os.path.expanduser(str(path))
    except (TypeError, ValueError):
        return None

    if value.startswith("tool_result:") or value.lower() in _PLACEHOLDER_PATHS:
        return None

    absolute = os.path.abspath(value)
    if is_temp_path(absolute):
        return None
    return absolute


def _redact_values(text: str, sensitive_values: Iterable[Any]) -> str:
    """Replace known finding values before and after pattern sanitisation."""
    redacted = text
    values = {
        str(value) for value in sensitive_values if value is not None and str(value)
    }
    for value in sorted(values, key=len, reverse=True):
        redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def _safe_context_line(text: str, sensitive_values: Iterable[Any]) -> str:
    """Sanitise one source line, failing closed if sanitisation is unavailable."""
    redacted = _redact_values(text, sensitive_values)
    try:
        from ai_guardian.scanners.sanitizer import sanitize_text

        sanitized = sanitize_text(redacted).get("sanitized_text")
        if not isinstance(sanitized, str):
            return "[REDACTED]"
        redacted = sanitized
    except Exception:
        # The context is optional; never persist raw source if the safety
        # sanitizer cannot be loaded.
        return "[REDACTED]"

    redacted = _redact_values(redacted, sensitive_values)
    return redacted[:_MAX_CONTEXT_LINE_CHARS]


def _git_ref(project_path: Optional[str]) -> Optional[str]:
    """Return the current commit ref when the project is a Git worktree."""
    if not project_path:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value[:128] if value else None


def build_allowlist_context(
    content: Any,
    original_file_path: Any,
    line_number: Any,
    *,
    rule_id: str = "",
    project_path: Optional[str] = None,
    git_ref: Optional[str] = None,
    sensitive_values: Optional[Iterable[Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Build non-sensitive metadata for locating a source finding later.

    The line hash is calculated from the original line, while the retained
    context is sanitized with bundled rules and any known finding values.
    Temporary paths and prompt/label-only inputs intentionally produce no
    context, preserving the config-only fallback for those violations.
    """
    source_path = _normalise_source_path(original_file_path)
    number = _as_line_number(line_number)
    if source_path is None or number is None or not isinstance(content, str):
        return None

    lines = content.splitlines()
    if number > len(lines):
        return None

    target_index = number - 1
    target_line = lines[target_index]
    values = tuple(sensitive_values or ())
    first = max(0, target_index - _CONTEXT_LINES_EACH_SIDE)
    last = min(len(lines), target_index + _CONTEXT_LINES_EACH_SIDE + 1)
    context_lines = [_safe_context_line(line, values) for line in lines[first:last]]
    surrounding_context = "\n".join(context_lines)[:_MAX_CONTEXT_CHARS]

    project = None
    if project_path:
        try:
            project = os.path.abspath(os.path.expanduser(str(project_path)))
        except (TypeError, ValueError):
            project = None

    return {
        "rule_id": str(rule_id or ""),
        "original_file_path": source_path,
        "line_content_hash": hashlib.sha256(target_line.encode("utf-8")).hexdigest(),
        "surrounding_context": surrounding_context,
        "git_ref": git_ref if git_ref is not None else _git_ref(project),
        "project_path": project,
    }


def resolve_source_location(violation: Dict[str, Any]) -> Optional[Tuple[str, int]]:
    """Resolve a saved allowlist context to the current source line.

    A preferred logged line is accepted when its hash still matches.  If the
    source moved, a unique hash match is accepted; duplicate or changed lines
    are rejected so the UI cannot annotate an unrelated line.
    """
    if not isinstance(violation, dict):
        return None
    metadata = violation.get("allowlist_context")
    if not isinstance(metadata, dict):
        return None

    source_path = _normalise_source_path(metadata.get("original_file_path"))
    expected_hash = metadata.get("line_content_hash")
    if source_path is None or not isinstance(expected_hash, str):
        return None

    try:
        with open(source_path, "r", encoding="utf-8") as source_file:
            lines = source_file.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    matching_lines = [
        index + 1
        for index, line in enumerate(lines)
        if hashlib.sha256(line.encode("utf-8")).hexdigest() == expected_hash
    ]
    if not matching_lines:
        return None

    blocked = violation.get("blocked", {})
    preferred = (
        _as_line_number(blocked.get("line_number"))
        if isinstance(blocked, dict)
        else None
    )
    if preferred in matching_lines:
        return source_path, preferred
    if len(matching_lines) == 1:
        return source_path, matching_lines[0]
    return None


def get_annotation_target(violation: Dict[str, Any]) -> Optional[Tuple[str, int]]:
    """Return the safe source target used by the annotation buttons.

    Older violation records retain the legacy non-temporary path/line pair.
    New records with an ``allowlist_context`` must pass hash verification.
    """
    if not isinstance(violation, dict):
        return None

    if isinstance(violation.get("allowlist_context"), dict):
        return resolve_source_location(violation)

    blocked = violation.get("blocked", {})
    if not isinstance(blocked, dict):
        return None
    path = blocked.get("file_path")
    line_number = _as_line_number(blocked.get("line_number"))
    if not path or line_number is None or is_temp_path(str(path)):
        return None
    return str(path), line_number


__all__ = [
    "build_allowlist_context",
    "get_annotation_target",
    "resolve_source_location",
]
