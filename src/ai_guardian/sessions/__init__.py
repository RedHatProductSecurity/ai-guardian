"""IDE session discovery and reading for multi-IDE conversation browser."""

from ai_guardian.sessions.adapters import SESSION_ADAPTERS
from ai_guardian.sessions.base import SessionAdapter
from ai_guardian.sessions.discovery import (
    discover_sessions,
    get_default_ide,
    get_supported_ides,
)
from ai_guardian.sessions.reader import (
    read_session_detail,
    read_session_detail_page,
    read_session_summary,
)

__all__ = [
    "SESSION_ADAPTERS",
    "SessionAdapter",
    "discover_sessions",
    "get_default_ide",
    "get_supported_ides",
    "read_session_detail",
    "read_session_detail_page",
    "read_session_summary",
]
