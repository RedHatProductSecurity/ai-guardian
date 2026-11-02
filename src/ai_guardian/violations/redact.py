"""Redact sensitive matched_text values before persisting violation records."""

REDACT_VIOLATION_TYPES = frozenset(
    {"secret_detected", "image_secret_detected", "pii_detected"}
)
_SAFE_BLOCKED_STORAGE_FIELDS = (
    "violation_id",
    "file_path",
    "line_number",
    "end_line",
    "start_column",
    "end_column",
    "total_findings",
    "action",
    "source",
    "is_immutable",
)
_SAFE_FINDING_STORAGE_FIELDS = (
    "file_path",
    "line_number",
    "end_line",
    "start_column",
    "end_column",
)
_SAFE_CONTEXT_STORAGE_FIELDS = (
    "ide_type",
    "hook_event",
    "project_path",
    "tool_use_id",
    "session_id",
    "tool_name",
    "run_id",
    "run_sequence",
    "correlation_id",
    "agent",
    "repository",
    "policy_version",
    "latency_ms",
    "ask_decision",
    "action_taken",
    "dialog_wait_ms",
)
_SAFE_ALLOWLIST_STORAGE_FIELDS = (
    "original_file_path",
    "line_content_hash",
    "git_ref",
    "project_path",
)


def redact_secret_hint(value):
    """Return a redacted hint from a sensitive value.

    Uses ``.*`` as separator so the hint doubles as a usable regex
    pattern in the allowlist editor (``suggest_pattern`` calls
    ``re.escape`` on the input, but ``.*`` is already valid regex).

    >=8 chars: first4.*last4  (e.g. "AKIA.*MPLE")
    4-7 chars: first2.*last2
    <4 or empty: "[redacted]"
    """
    if not value or len(value) < 4:
        return "[redacted]"
    if len(value) >= 8:
        return f"{value[:4]}.*{value[-4:]}"
    return f"{value[:2]}.*{value[-2:]}"


def sanitize_blocked_for_secret(blocked_info):
    """Redact matched_text in a blocked dict for sensitive violation types.

    Mutates *blocked_info* in-place:
    - If file_path + line_number present: removes matched_text entirely
      (position metadata is sufficient; rescan recovers text on demand).
    - Otherwise: replaces matched_text with a pattern_hint.
    - Iterates the findings list and applies the same logic per finding.
    """
    has_position = bool(
        blocked_info.get("file_path") and blocked_info.get("line_number")
    )

    raw = blocked_info.pop("matched_text", None)
    if raw and not has_position:
        blocked_info["pattern_hint"] = redact_secret_hint(raw)

    findings = blocked_info.get("findings")
    if findings:
        findings = [dict(f) for f in findings]
        blocked_info["findings"] = findings
        for f in findings:
            f_has_pos = bool(f.get("line_number") and f.get("start_column"))
            raw_f = f.pop("matched_text", None)
            if raw_f and not f_has_pos:
                f["pattern_hint"] = redact_secret_hint(raw_f)

        if "pattern_hint" not in blocked_info:
            for f in findings:
                hint = f.get("pattern_hint")
                if hint:
                    blocked_info["pattern_hint"] = hint
                    break


def sanitize_blocked_for_storage(blocked_info):
    """Project sensitive blocked data onto location/action metadata only.

    This explicit field projection prevents raw matches, partial hints, scanner
    rule data, and arbitrary nested payloads from reaching persistent history.
    The caller's object is not modified.
    """
    if not isinstance(blocked_info, dict):
        return {}

    sanitized = {}
    for field in _SAFE_BLOCKED_STORAGE_FIELDS:
        if field in blocked_info:
            sanitized[field] = blocked_info[field]

    findings = blocked_info.get("findings")
    if isinstance(findings, list):
        safe_findings = []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            safe_finding = {}
            for field in _SAFE_FINDING_STORAGE_FIELDS:
                if field in finding:
                    safe_finding[field] = finding[field]
            if safe_finding:
                safe_findings.append(safe_finding)
        if safe_findings:
            sanitized["findings"] = safe_findings

    return sanitized


def sanitize_sensitive_violation_context(context):
    """Keep only standard context identifiers for sensitive finding records."""
    if not isinstance(context, dict):
        return {}
    return {
        field: context[field]
        for field in _SAFE_CONTEXT_STORAGE_FIELDS
        if field in context
    }


def sanitize_sensitive_allowlist_context(context):
    """Keep hash/path references, but omit source snippets and scanner rules."""
    if not isinstance(context, dict):
        return {}
    return {
        field: context[field]
        for field in _SAFE_ALLOWLIST_STORAGE_FIELDS
        if field in context
    }
