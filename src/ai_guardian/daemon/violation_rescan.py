"""Rescan a file at a violation location to retrieve matched text.

Used by the violation detail modal's "Always Allow" flow to get the
current matched text for pattern editor pre-population. The file is
scanned live — nothing is cached or persisted.
"""

import logging
import os
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_LINE_WINDOW = 10


def rescan_violation(
    file_path: str,
    line_number: int,
    violation_type: str,
    sub_type: str = "",
    config: Optional[Dict] = None,
    start_column: Optional[int] = None,
    end_column: Optional[int] = None,
) -> Dict:
    """Rescan a file to find the matched text for a violation.

    Args:
        file_path: Absolute path to the file.
        line_number: Original line number from the violation entry.
        violation_type: Top-level violation type (e.g. "secret_detected").
        sub_type: Sub-type field (e.g. "env-variable", "pii-ssn").
        config: AI Guardian config dict (loaded from daemon state if None).
        start_column: Column offset (0-based) where the match starts.
        end_column: Column offset (0-based) where the match ends.

    Returns:
        Dict with "status" key:
        - {"status": "found", "matched_text": ..., "line_number": ...,
           "violation_type": ..., "secret_type": ...}
        - {"status": "file_not_found", "message": ...}
        - {"status": "not_found", "message": ...}
    """
    if not file_path:
        return {"status": "not_found", "message": "No file path provided"}

    path = Path(file_path).expanduser()
    if not path.exists():
        return {
            "status": "file_not_found",
            "message": "File no longer exists — violation is stale",
        }

    if config is None:
        config = _load_config()

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.debug("Cannot read %s: %s", file_path, e)
        return {"status": "file_not_found", "message": f"Cannot read file: {e}"}

    handler = _SCAN_HANDLERS.get(violation_type)
    if handler is None:
        return {
            "status": "not_found",
            "message": f"Unsupported violation type: {violation_type}",
        }

    return handler(
        content,
        file_path,
        line_number,
        sub_type,
        config,
        start_column=start_column,
        end_column=end_column,
    )


def _load_config() -> Dict:
    try:
        from ai_guardian.config.loaders import _load_config_file

        cfg, _ = _load_config_file()
        return cfg or {}
    except Exception:
        return {}


def _scan_secrets(
    content,
    file_path,
    line_number,
    sub_type,
    config,
    start_column=None,
    end_column=None,
):
    """Rescan for secrets, filter by sub_type near line_number."""
    if start_column is not None and end_column is not None and line_number:
        matched = _extract_at_position(content, line_number, start_column, end_column)
        if matched:
            return {
                "status": "found",
                "matched_text": matched,
                "line_number": line_number,
                "violation_type": "secret_detected",
                "secret_type": sub_type,
            }

    try:
        from ai_guardian.scanners.secret_scanning import check_secrets_with_gitleaks
    except ImportError:
        return {"status": "not_found", "message": "Scanner not available"}

    secret_config = config.get("secret_scanning", {})
    has_secrets, error_msg = check_secrets_with_gitleaks(
        content,
        filename=os.path.basename(file_path),
        file_path=file_path,
        secret_config=secret_config,
    )

    if not has_secrets:
        return {
            "status": "not_found",
            "message": f"Violation no longer present at or near line {line_number}",
        }

    import ai_guardian.scanners.secret_scanning as _ss

    matched = _ss._last_secret_matched_text or ""

    if not matched and error_msg:
        matched = _extract_line_near(content, line_number)

    if matched:
        return {
            "status": "found",
            "matched_text": matched,
            "line_number": line_number,
            "violation_type": "secret_detected",
            "secret_type": sub_type,
        }

    return {
        "status": "not_found",
        "message": f"Violation no longer present at or near line {line_number}",
    }


def _scan_pii(content, file_path, line_number, sub_type, config, **_kwargs):
    """Rescan for PII near line_number."""
    try:
        from ai_guardian.hook_processing import _scan_for_pii
    except ImportError:
        return {"status": "not_found", "message": "PII scanner not available"}

    pii_config = config.get("scan_pii", {})
    if not pii_config.get("enabled", True):
        pii_config["enabled"] = True

    has_pii, _redacted, redactions, _warning = _scan_for_pii(
        content,
        pii_config,
        file_path=file_path,
    )

    if not has_pii or not redactions:
        return {
            "status": "not_found",
            "message": f"Violation no longer present at or near line {line_number}",
        }

    best = _find_nearest_redaction(redactions, line_number, sub_type, content)
    if best:
        return {
            "status": "found",
            "matched_text": best["text"],
            "line_number": best.get("line_number", line_number),
            "violation_type": "pii_detected",
            "secret_type": sub_type,
        }

    first = redactions[0]
    pos = first.get("position", -1)
    length = first.get("original_length", 0)
    text = ""
    if pos >= 0 and length > 0 and pos + length <= len(content):
        text = content[pos : pos + length]
    if not text:
        text = _extract_line_near(content, line_number)

    return {
        "status": "found",
        "matched_text": text,
        "line_number": first.get("line_number", line_number),
        "violation_type": "pii_detected",
        "secret_type": sub_type,
    }


def _scan_prompt_injection(
    content, file_path, line_number, sub_type, config, **_kwargs
):
    """Rescan for prompt injection near line_number."""
    try:
        from ai_guardian.scanners.prompt_injection import check_prompt_injection
    except ImportError:
        return {"status": "not_found", "message": "Injection scanner not available"}

    should_block, error_msg, detected = check_prompt_injection(content, config)

    if not detected:
        return {
            "status": "not_found",
            "message": f"Violation no longer present at or near line {line_number}",
        }

    matched = _extract_line_near(content, line_number)
    return {
        "status": "found",
        "matched_text": matched,
        "line_number": line_number,
        "violation_type": "prompt_injection",
        "secret_type": sub_type,
    }


def _scan_context_poisoning(
    content, file_path, line_number, sub_type, config, **_kwargs
):
    """Rescan for context poisoning."""
    try:
        from ai_guardian.scanners.context_poisoning import check_context_poisoning
    except ImportError:
        return {
            "status": "not_found",
            "message": "Context poisoning scanner not available",
        }

    should_block, error_msg, detected = check_context_poisoning(content, config)
    if not detected:
        return {
            "status": "not_found",
            "message": f"Violation no longer present at or near line {line_number}",
        }

    matched = _extract_line_near(content, line_number)
    return {
        "status": "found",
        "matched_text": matched,
        "line_number": line_number,
        "violation_type": "context_poisoning",
        "secret_type": sub_type,
    }


def _scan_config_exfil(content, file_path, line_number, sub_type, config, **_kwargs):
    """Rescan for config file exfiltration."""
    try:
        from ai_guardian.scanners.config_scanner import ConfigFileScanner
    except ImportError:
        return {"status": "not_found", "message": "Config scanner not available"}

    scanner = ConfigFileScanner(config.get("config_file_scanning", {}))
    is_threat, reason = scanner.scan(file_path, content)
    if not is_threat:
        return {
            "status": "not_found",
            "message": f"Violation no longer present at or near line {line_number}",
        }

    matched = _extract_line_near(content, line_number)
    return {
        "status": "found",
        "matched_text": matched,
        "line_number": line_number,
        "violation_type": "config_file_exfil",
        "secret_type": sub_type,
    }


def _passthrough_violation(
    content, file_path, line_number, sub_type, config, **_kwargs
):
    """For types where the matched text is the file path or line content."""
    matched = _extract_line_near(content, line_number) if line_number else file_path
    return {
        "status": "found",
        "matched_text": matched or file_path,
        "line_number": line_number or 0,
        "violation_type": "directory_blocking",
        "secret_type": sub_type,
    }


def _extract_at_position(
    content: str, line_number: int, start_col: int, end_col: int
) -> str:
    """Extract text at a known line:column range from content.

    Columns are 1-based (as stored by scanners).
    """
    if not content or line_number < 1:
        return ""
    lines = content.splitlines()
    if line_number > len(lines):
        return ""
    line = lines[line_number - 1]
    sc = max(start_col - 1, 0)
    ec = end_col
    if sc < len(line) and ec > sc and ec <= len(line):
        return line[sc:ec]
    if sc < len(line):
        return line[sc:]
    return line.strip()


def _extract_line_near(content: str, line_number: int) -> str:
    """Extract the line at or near line_number from content."""
    if not content or line_number < 1:
        return ""
    lines = content.splitlines()
    if 0 < line_number <= len(lines):
        return lines[line_number - 1].strip()
    if lines:
        return lines[min(line_number - 1, len(lines) - 1)].strip()
    return ""


def _find_nearest_redaction(redactions, target_line, sub_type, content):
    """Find the redaction nearest to target_line, optionally filtered by sub_type."""
    candidates = redactions
    if sub_type:
        filtered = [r for r in redactions if r.get("type", "") == sub_type]
        if filtered:
            candidates = filtered

    best = None
    best_dist = float("inf")
    for r in candidates:
        rline = r.get("line_number")
        if rline is None:
            continue
        dist = abs(rline - target_line)
        if dist < best_dist:
            best_dist = dist
            best = r

    if best is None and candidates:
        best = candidates[0]

    if best is None:
        return None

    pos = best.get("position", -1)
    length = best.get("original_length", 0)
    text = ""
    if pos >= 0 and length > 0 and pos + length <= len(content):
        text = content[pos : pos + length]
    if not text:
        line_num = best.get("line_number")
        if line_num:
            text = _extract_line_near(content, line_num)

    return {"text": text, "line_number": best.get("line_number", target_line)}


_SCAN_HANDLERS = {
    "secret_detected": _scan_secrets,
    "pii_detected": _scan_pii,
    "prompt_injection": _scan_prompt_injection,
    "jailbreak_detected": _scan_prompt_injection,
    "context_poisoning": _scan_context_poisoning,
    "config_file_exfil": _scan_config_exfil,
    "directory_blocking": _passthrough_violation,
    "ssrf_blocked": _passthrough_violation,
    "supply_chain": _passthrough_violation,
    "tool_permission": _passthrough_violation,
}
