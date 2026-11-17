"""Privacy-aware command context for violation history."""

import logging
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

MAX_ORIGIN_COMMAND_LEN = 500
_MAX_ORIGIN_COMMAND_SCAN_LEN = 65_536
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


@lru_cache(maxsize=1)
def _origin_command_redactor():
    """Build the bundled secret/PII matcher used for command privacy checks."""
    from ai_guardian.scanners.secret_redactor import SecretRedactor

    return SecretRedactor(
        config={"enabled": True, "log_redactions": False},
        pii_config={"enabled": True, "pii_types": list(_ORIGIN_COMMAND_PII_TYPES)},
    )


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

    try:
        from ai_guardian.scanners.secret_scanning import check_secrets

        has_secrets, scan_error = check_secrets(command, filename="origin_command")
        if has_secrets or scan_error:
            return None

        redactor = _origin_command_redactor()
        compiled_pii_types = getattr(redactor, "compiled_pii_types", None)
        if not isinstance(compiled_pii_types, set) or not set(
            _ORIGIN_COMMAND_PII_TYPES
        ).issubset(compiled_pii_types):
            logger.warning(
                "PII rules unavailable; omitting origin command from violation history"
            )
            return None

        redaction_result = redactor.redact(command)
        if not isinstance(redaction_result, dict):
            return None
        redactions = redaction_result.get("redactions")
        if (
            not isinstance(redactions, list)
            or redactions
            or redaction_result.get("redacted_text") != command
        ):
            return None
    except Exception:
        logger.warning(
            "Could not verify origin command; omitting it from violation history"
        )
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
