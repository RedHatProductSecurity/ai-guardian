"""
Web-based Console for AI Guardian (NiceGUI).

Provides the browser-based dashboard console.
Connects to daemons via their REST APIs using MultiDaemonClient.

Requires NiceGUI (Python >= 3.10).
"""

from ai_guardian.web.app import WebConsole

HAS_NICEGUI = True

__all__ = ["WebConsole", "HAS_NICEGUI"]
