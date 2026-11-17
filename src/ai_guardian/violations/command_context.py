"""Privacy-aware source context for violation history."""

import logging
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

MAX_ORIGIN_COMMAND_LEN = 500
_MAX_ORIGIN_COMMAND_SCAN_LEN = 65_536
MAX_SENSITIVE_FILE_PATH_LEN = 4096
_ORIGIN_COMMAND_PII_TYPES = (
    "ssn",
    "credit_card",
    "phone",
    "email",
    "us_passport",
    "iban",
    "intl_phone",
    "medical_id",
    "passport",
    "canada_sin",
    "uk_nin",
    "india_aadhaar",
    "address",
)
_SENSITIVE_SOURCE_CONTEXTS = {
    "user_prompt": "User prompt",
    "tool_input": "Tool input",
    "tool_output": "Tool output",
    "file_content": "File content",
    "file_scan": "File scan",
    "command": "Command",
}


@lru_cache(maxsize=1)
def _origin_command_redactor():
    """Build the bundled secret/PII matcher used for source-metadata checks."""
    from ai_guardian.scanners.secret_redactor import SecretRedactor

    return SecretRedactor(
        config={"enabled": True, "log_redactions": False},
        pii_config={"enabled": True, "pii_types": list(_ORIGIN_COMMAND_PII_TYPES)},
    )


def _source_text_is_verified_safe(text: str) -> bool:
    """Verify source text has no detected secrets/PII and complete scanner coverage."""
    try:
        from ai_guardian.scanners.secret_scanning import check_secrets

        has_secrets, scan_error = check_secrets(text, filename="source_context")
        if has_secrets or scan_error:
            return False
    except Exception:
        logger.warning(
            "Could not verify source context; omitting it from violation history"
        )
        return False

    return _bundled_redactor_verifies_safe(text, source_name="source context")


def _bundled_redactor_verifies_safe(text: str, *, source_name: str) -> bool:
    """Check bounded source metadata with bundled secret/PII rules in-process."""
    try:
        redactor = _origin_command_redactor()
        compiled_pii_types = getattr(redactor, "compiled_pii_types", None)
        if not isinstance(compiled_pii_types, set) or not set(
            _ORIGIN_COMMAND_PII_TYPES
        ).issubset(compiled_pii_types):
            logger.warning(
                "PII rules unavailable; omitting %s from violation history",
                source_name,
            )
            return False

        redaction_result = redactor.redact(text)
        if not isinstance(redaction_result, dict):
            return False
        redactions = redaction_result.get("redactions")
        if (
            not isinstance(redactions, list)
            or redactions
            or redaction_result.get("redacted_text") != text
        ):
            return False
    except Exception:
        logger.warning(
            "Could not verify %s; omitting it from violation history", source_name
        )
        return False

    return True


def _source_path_is_verified_safe(file_path: str) -> bool:
    """Verify a file path with bundled rules without spawning scanner processes."""
    return _bundled_redactor_verifies_safe(file_path, source_name="source path")


def sanitize_origin_command(command: object) -> Optional[str]:
    """Return a bounded command only when secret and PII checks verify it safe.

    Commands that are too large to verify, contain detected sensitive values, or
    encounter any scanner error are omitted rather than persisted partially or raw.
    """
    if not isinstance(command, str) or not command.strip():
        return None
    if len(command) > _MAX_ORIGIN_COMMAND_SCAN_LEN:
        return None
    if any(not char.isprintable() and char not in "\t\r\n" for char in command):
        return None
    if not _source_text_is_verified_safe(command):
        return None

    flattened = " ".join(command.split())
    if not flattened:
        return None
    return flattened[:MAX_ORIGIN_COMMAND_LEN]


def has_usable_source_file(file_path: object) -> bool:
    """Whether a file path can anchor a finding's source location."""
    if not isinstance(file_path, str):
        return False
    normalized = file_path.strip()
    if not normalized or normalized.casefold() in {
        "unknown",
        "none",
        "null",
        "n/a",
        "<unknown>",
    }:
        return False
    return not normalized.casefold().startswith("tool_result:")


def sanitize_sensitive_file_path(file_path: object) -> Optional[str]:
    """Return a bounded printable path only when bundled secret/PII checks verify it."""
    if not isinstance(file_path, str) or not has_usable_source_file(file_path):
        return None
    candidate = file_path.strip()
    if len(file_path) > MAX_SENSITIVE_FILE_PATH_LEN or not file_path.isprintable():
        return None
    # PII warning text may contain a shortened display path (".../name"). It is
    # useful for a warning, but is not an exact locator suitable for history.
    if candidate.startswith(("...", "…")):
        return None
    if not _source_path_is_verified_safe(file_path):
        return None
    return file_path


def normalize_sensitive_source_context(value: object) -> Optional[str]:
    """Accept only fixed source-context labels suitable for sensitive history."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "prompt": "user_prompt",
        "userpromptsubmit": "user_prompt",
        "user_prompt_submit": "user_prompt",
        "pretooluse": "tool_input",
        "pre_tool_use": "tool_input",
        "permissionrequest": "tool_input",
        "permission_request": "tool_input",
        "beforereadfile": "tool_input",
        "before_read_file": "tool_input",
        "posttooluse": "tool_output",
        "post_tool_use": "tool_output",
        "afterfileedit": "tool_output",
        "after_file_edit": "tool_output",
        "file": "file_content",
        "scan": "file_scan",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in _SENSITIVE_SOURCE_CONTEXTS else None


def sensitive_source_context_label(value: object) -> Optional[str]:
    """Return a display label for a fixed source-context value."""
    normalized = normalize_sensitive_source_context(value)
    return _SENSITIVE_SOURCE_CONTEXTS.get(normalized) if normalized else None
