"""Trusted developer-session configuration."""

import json
import logging
from typing import Any, Mapping, Optional

from ai_guardian.config.utils import get_config_dir

logger = logging.getLogger(__name__)

DEVELOPER_SESSION_SECTION = "developer_session"
NON_BLOCKING_FINDINGS_OPTION = "non_blocking_findings"
NON_BLOCKING_FINDINGS_NOTICE = (
    "The trusted developer session's non-blocking findings option is enabled; "
    "this finding is advisory and did not block the operation."
)


def _is_enabled_value(value: Any) -> bool:
    """Accept only the JSON boolean true; all other values fail closed."""
    return isinstance(value, bool) and value is True


def _load_global_config() -> Optional[Mapping[str, Any]]:
    """Load only the protected global config, excluding overlays."""
    path = get_config_dir() / "ai-guardian.json"
    try:
        with path.open("r", encoding="utf-8") as config_file:
            value = json.load(config_file)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Unable to read trusted developer-session config: %s", exc)
        return None
    return value if isinstance(value, dict) else None


def _is_developer_session_enabled(config: Optional[Mapping[str, Any]]) -> bool:
    """Return whether a parsed config contains the explicit enable flag."""
    if not isinstance(config, Mapping):
        return False
    section = config.get(DEVELOPER_SESSION_SECTION)
    return isinstance(section, Mapping) and _is_enabled_value(section.get("enabled"))


def _is_non_blocking_findings_enabled(config: Optional[Mapping[str, Any]]) -> bool:
    """Require both explicit opt-ins in the protected global configuration."""
    if config is None or not _is_developer_session_enabled(config):
        return False
    section = config.get(DEVELOPER_SESSION_SECTION)
    return isinstance(section, Mapping) and _is_enabled_value(
        section.get(NON_BLOCKING_FINDINGS_OPTION)
    )


def is_trusted_developer_session() -> bool:
    """Return whether protected global config explicitly enables access.

    Only the global ``ai-guardian.json`` is read. Project configs, SDK overlays,
    hook payloads, and command arguments are not trusted sources for this
    setting.
    """
    return _is_developer_session_enabled(_load_global_config())


def is_non_blocking_findings_enabled() -> bool:
    """Return whether trusted developer sessions may allow blocking findings.

    Both booleans are read from the protected global config. Project settings,
    SDK overlays, hook payloads, and agent-supplied values are not trusted.
    """
    return _is_non_blocking_findings_enabled(_load_global_config())


def should_downgrade_blocking_finding(
    *, enabled: bool, action: Any, detected: bool, scan_error: Any = None
) -> bool:
    """Only successful detections with an explicit block action are relaxed."""
    return enabled is True and detected is True and action == "block" and not scan_error


def non_blocking_finding_advisory_message(diagnostic: Optional[str]) -> str:
    """Preserve a finding diagnostic and explain the trusted-session override."""
    parts = [diagnostic] if isinstance(diagnostic, str) and diagnostic else []
    parts.append(NON_BLOCKING_FINDINGS_NOTICE)
    return "\n\n".join(parts)
