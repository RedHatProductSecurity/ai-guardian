"""Allowlisted projections of tool diagnostics for Console and agent output.

Persisted records are not trusted: never forward arbitrary reasons, argument
keys/values, session titles, or extra stored diagnostic fields to an agent.
"""

import re
from typing import Any, Dict, Optional

from ai_guardian.tools.input import (
    ARGUMENT_KEYS_BY_TOOL,
    DIAGNOSTIC_SUBREASONS,
    INPUT_FAILURE_LABELS,
    JSON_TYPES,
    NATIVE_TOOL_NAMES,
)

INPUT_FAILURE_GUIDANCE = (
    "The tool input could not be validated. Review the argument diagnostics; "
    "the operation was blocked before execution."
)
WORKSPACE_SOURCES = frozenset({"session", "hook", "request", "unknown"})


def safe_version(value: Any) -> Optional[str]:
    if (
        isinstance(value, str)
        and len(value) <= 64
        and re.fullmatch(
            r"\d{1,4}(?:\.\d{1,4}){0,3}(?:-(?:dev|alpha|beta|rc)(?:\.?\d{1,6})?)?",
            value,
            re.ASCII,
        )
    ):
        return value
    return None


def safe_input_diagnostics(value: Any) -> Optional[Dict]:
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
    ):
        return None
    subreason = value.get("subreason")
    if not isinstance(subreason, str) or subreason not in DIAGNOSTIC_SUBREASONS:
        return None
    canonical = value.get("canonical_tool_name")
    canonical = (
        canonical
        if isinstance(canonical, str) and canonical in ARGUMENT_KEYS_BY_TOOL
        else None
    )
    native = value.get("native_tool_name")
    native = native if isinstance(native, str) and native in NATIVE_TOOL_NAMES else None
    shape = value.get("argument_shape")
    recognized = ARGUMENT_KEYS_BY_TOOL.get(canonical or "", ())
    shape = {
        key: shape[key]
        for key in recognized
        if isinstance(shape, dict)
        and isinstance(shape.get(key), str)
        and shape[key] in JSON_TYPES
    }
    count = value.get("unrecognized_argument_count")
    expected = value.get("expected_field")
    input_type = value.get("input_type")
    return {
        "schema_version": 1,
        "subreason": subreason,
        "native_tool_name": native,
        "canonical_tool_name": canonical,
        "expected_field": (
            expected
            if isinstance(expected, str)
            and expected in {"path", "filePath", "file_path", "command"}
            else None
        ),
        "input_type": (
            input_type
            if isinstance(input_type, str) and input_type in JSON_TYPES
            else "unknown"
        ),
        "argument_shape": shape,
        "unrecognized_argument_count": (
            min(10000, max(0, count)) if type(count) is int else None
        ),
        "target_status": (
            "known" if value.get("target_status") == "known" else "unknown"
        ),
    }


def violation_input_diagnostics(violation: Dict) -> Optional[Dict]:
    if violation.get("violation_type", violation.get("type")) != "tool_permission":
        return None
    blocked = violation.get("blocked")
    if not isinstance(blocked, dict):
        return None
    result = safe_input_diagnostics(blocked.get("input_diagnostics"))
    if result is not None:
        return result
    # Exact legacy label only, never arbitrary stored reasons or placeholders.
    if (
        violation.get("violation_type") == "tool_permission"
        and blocked.get("reason") == "missing required parameter"
    ):
        return safe_input_diagnostics(
            {
                "schema_version": 1,
                "subreason": "missing_argument",
                "expected_field": "file_path",
            }
        )
    return None


def safe_tool_correlation(violation: Dict) -> Dict:
    context = violation.get("context")
    context = context if isinstance(context, dict) else {}
    patterns = {
        "id": r"viol_[a-fA-F0-9]{8,64}",
        "session_id": r"(?:ses_[A-Za-z0-9]{8,64}|session-[A-Za-z0-9_-]{1,80}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12})",
        "tool_use_id": r"(?:call_|toolu_|tool-use-)[A-Za-z0-9_-]{1,100}",
        "message_id": r"msg_[A-Za-z0-9]{1,100}",
    }
    result: Dict[str, Any] = {}
    for key, pattern in patterns.items():
        value = violation.get(key) if key == "id" else context.get(key)
        result[key] = (
            value
            if isinstance(value, str)
            and len(value) <= 128
            and re.fullmatch(pattern, value, re.ASCII)
            else None
        )
    for key in ("host_version", "integration_version"):
        result[key] = safe_version(context.get(key))
    source = context.get("workspace_source")
    result["workspace_source"] = (
        source if isinstance(source, str) and source in WORKSPACE_SOURCES else "unknown"
    )
    return result


def diagnostic_safe_violation(violation: Dict) -> Dict:
    """Scrub human detail/JSON copies, preserving only safe sensitive locators."""
    violation_type = violation.get("violation_type", violation.get("type", ""))
    if violation_type in {
        "sensitive_finding",
        "secret_detected",
        "image_secret_detected",
        "pii_detected",
    }:
        import copy

        from ai_guardian.violations.command_context import (
            sanitize_sensitive_file_path,
            sanitize_source_url,
            sensitive_source_context_label,
        )

        legacy_sensitive_type = violation_type != "sensitive_finding"
        result = {
            key: copy.deepcopy(violation[key])
            for key in (
                "id",
                "timestamp",
                "violation_type",
                "type",
                "severity",
                "resolved",
                "resolved_at",
                "resolved_action",
            )
            if key in violation
        }
        if violation_type != "sensitive_finding":
            if "violation_type" in result:
                result["violation_type"] = "sensitive_finding"
            if "type" in result:
                result["type"] = "sensitive_finding"
        flat_file = violation.get("file")
        if legacy_sensitive_type:
            flat_file = sanitize_sensitive_file_path(flat_file)
        if (
            isinstance(flat_file, str)
            and 0 < len(flat_file) <= 4096
            and flat_file.isprintable()
        ):
            result["file"] = flat_file
        for key, minimum in (
            ("line", 1),
            ("end_line", 1),
            ("start_column", 1),
            ("end_column", 1),
        ):
            value = violation.get(key)
            if type(value) is int and minimum <= value <= 2**31:
                result[key] = value
        source_context = sensitive_source_context_label(violation.get("source_context"))
        if source_context:
            result["source_context"] = source_context
        raw_blocked = violation.get("blocked")
        raw_blocked = raw_blocked if isinstance(raw_blocked, dict) else {}
        safe_blocked: Dict[str, Any] = {}
        for raw, target in ((violation, result), (raw_blocked, safe_blocked)):
            source_url = sanitize_source_url(raw.get("source_url"))
            if source_url:
                target["source_url"] = source_url
        file_path = raw_blocked.get("file_path")
        if legacy_sensitive_type:
            file_path = sanitize_sensitive_file_path(file_path)
        if (
            isinstance(file_path, str)
            and 0 < len(file_path) <= 4096
            and file_path.isprintable()
        ):
            safe_blocked["file_path"] = file_path
        for key, minimum in (
            ("line_number", 1),
            ("end_line", 1),
            ("start_column", 0),
            ("end_column", 0),
        ):
            value = raw_blocked.get(key)
            if type(value) is int and minimum <= value <= 2**31 - 1:
                safe_blocked[key] = value
        source_context = sensitive_source_context_label(
            raw_blocked.get("source_context")
        )
        if source_context:
            safe_blocked["source_context"] = source_context
        result["blocked"] = safe_blocked
        from ai_guardian.violations.utils import safe_mirror_metadata

        mirror = safe_mirror_metadata(violation.get("mirror"))
        if mirror is not None:
            result["mirror"] = mirror
        return result

    from ai_guardian.violations.command_context import sanitize_source_url_metadata

    violation = sanitize_source_url_metadata(violation)
    for key in ("blocked", "context"):
        if isinstance(violation.get(key), dict):
            violation[key] = sanitize_source_url_metadata(violation[key])
    blocked = violation.get("blocked")
    if not isinstance(blocked, dict) or "input_diagnostics" not in blocked:
        return violation
    result = dict(violation)
    result["blocked"] = {
        **blocked,
        "input_diagnostics": safe_input_diagnostics(blocked["input_diagnostics"]),
    }
    context = violation.get("context")
    if isinstance(context, dict):
        safe = safe_tool_correlation(violation)
        result["context"] = dict(context)
        for key in (
            "message_id",
            "host_version",
            "integration_version",
            "workspace_source",
        ):
            if key in context:
                result["context"][key] = safe[key]
    return result
