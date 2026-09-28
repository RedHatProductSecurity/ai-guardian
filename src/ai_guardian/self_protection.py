"""Configuration helpers for immutable AI Guardian self-protection."""

from typing import Any, Dict, Optional

SELF_PROTECTION_SECTION = "self_protection"
BLOCK_HOST_AGENT_CLI_KEY = "block_host_agent_cli"


def is_host_agent_cli_protection_enabled(config: Optional[Dict[str, Any]]) -> bool:
    """Return the host-CLI protection setting with a secure default.

    Only an explicit JSON boolean ``false`` disables this protection. Missing,
    malformed, and time-based values remain enabled so invalid configuration
    cannot weaken the agent self-invocation boundary.
    """
    section = config.get(SELF_PROTECTION_SECTION) if isinstance(config, dict) else None
    if not isinstance(section, dict):
        return True
    value = section.get(BLOCK_HOST_AGENT_CLI_KEY)
    return value if isinstance(value, bool) else True


__all__ = [
    "BLOCK_HOST_AGENT_CLI_KEY",
    "SELF_PROTECTION_SECTION",
    "is_host_agent_cli_protection_enabled",
]
