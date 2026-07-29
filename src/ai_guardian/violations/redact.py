"""Redact sensitive matched_text values before persisting violation records."""

REDACT_VIOLATION_TYPES = frozenset(
    {"secret_detected", "image_secret_detected", "pii_detected"}
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
