"""IDE session discovery — locate session files for each supported IDE."""

import logging
from typing import Dict, List, Optional

from ai_guardian.sessions.adapters import SESSION_ADAPTERS

logger = logging.getLogger(__name__)

SUPPORTED_IDES = list(SESSION_ADAPTERS.keys())


def get_supported_ides() -> List[str]:
    """Return list of supported IDE identifiers."""
    return list(SESSION_ADAPTERS.keys())


def get_default_ide(config: Optional[Dict] = None) -> str:
    """Resolve default IDE using config -> auto-detect -> fallback.

    Resolution order:
    1. session_viewer.default_ide in config (explicit)
    2. Auto-detect from installed hooks (which IDE has hooks configured)
    3. First IDE with sessions found on disk
    """
    if config:
        explicit = (
            config.get("session_viewer", {}).get("default_ide", "").strip().lower()
        )
        if explicit and explicit in SESSION_ADAPTERS:
            return explicit

    for ide_name, adapter in SESSION_ADAPTERS.items():
        session_dir = adapter.resolve_session_dir()
        if session_dir and session_dir.exists():
            return ide_name

    return "claude"


def discover_sessions(
    ide: str,
    project_path: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Discover sessions for a given IDE.

    Returns list of session metadata dicts sorted by last modified (newest first).
    """
    ide = ide.lower()
    adapter = SESSION_ADAPTERS.get(ide)
    if not adapter:
        logger.warning("Unsupported IDE: %s", ide)
        return []

    return adapter.discover(project_path, limit)
