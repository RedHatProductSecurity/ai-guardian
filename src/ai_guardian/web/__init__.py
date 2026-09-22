"""
Web-based Console for AI Guardian (NiceGUI).

Provides a browser-based dashboard as an alternative to the TUI console.
Connects to daemons via their REST APIs using MultiDaemonClient.

Requires NiceGUI (Python >= 3.10).
"""

from typing import Any, Optional, Type

WebConsole: Optional[Type[Any]] = None

try:
    from ai_guardian.web.app import WebConsole as _WebConsole

    WebConsole = _WebConsole
    HAS_NICEGUI = True
except ImportError:
    HAS_NICEGUI = False

__all__ = ["WebConsole", "HAS_NICEGUI"]
