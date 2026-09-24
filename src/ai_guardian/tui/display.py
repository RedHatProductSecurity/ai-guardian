"""Shared display tier detection for prompt and tray dialogs.

Complex-dialog cascade: tkinter -> NiceGUI (browser) -> Textual (terminal) -> headless.
Simple/actionable tray dialogs may use the platform-native provider first.

Environment overrides (useful for testing or user preference):
  AI_GUARDIAN_NO_TKINTER=1   skip tkinter even when installed
  AI_GUARDIAN_NO_NICEGUI=1   skip NiceGUI even when installed
"""

import json
import logging
import os
import platform
from typing import Tuple

logger = logging.getLogger(__name__)

VALID_PREFERRED_UI = {"auto", "tkinter", "nicegui", "textual", "headless"}


def _textual_installed() -> bool:
    """Return whether Textual can be imported, without requiring this TTY."""
    try:
        import textual  # noqa: F401

        return True
    except ImportError:
        return False


def get_preferred_ui() -> str:
    """Return the preferred UI toolkit from env var or config.

    Priority: AI_GUARDIAN_PREFERRED_UI env var > console.preferred_ui config > "auto".
    """
    env_val = os.environ.get("AI_GUARDIAN_PREFERRED_UI", "").strip().lower()
    if env_val in VALID_PREFERRED_UI:
        return env_val

    try:
        from ai_guardian.config.utils import get_config_dir

        config_path = get_config_dir() / "ai-guardian.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            val = config.get("console", {}).get("preferred_ui", "auto")
            if val in VALID_PREFERRED_UI:
                return val
    except Exception:
        pass  # intentionally silent — optional dependency

    return "auto"


def _tkinter_available():
    """Return True if tkinter can be imported.

    Runtime failures (broken Tcl/Tk, no display, etc.) are caught by
    the try/except cascade in the caller which falls through to
    NiceGUI or Textual automatically.
    """
    if os.environ.get("AI_GUARDIAN_NO_TKINTER"):
        return False
    try:
        import tkinter  # noqa: F401

        return True
    except ImportError:
        return False


def _nicegui_available():
    """Return True if NiceGUI can be imported and is not suppressed."""
    if os.environ.get("AI_GUARDIAN_NO_NICEGUI"):
        return False
    try:
        import nicegui  # noqa: F401

        return True
    except ImportError:
        return False


def _textual_available():
    """Return True if Textual can be imported and a TTY is present."""
    try:
        import textual  # noqa: F401

        return os.isatty(0)
    except ImportError:
        return False


def select_ui_provider(
    dialog_type: str = "simple",
    *,
    screen_bounds=None,
) -> str:
    """Select the first usable provider for a tray dialog.

    ``simple`` and ``action`` dialogs can use the operating system's native
    dialog on every supported desktop.  Forms and streaming output prefer the
    richer toolkit cascade.  Explicit preferences keep their meaning while
    still falling through to a provider that does not require the unavailable
    toolkit; in particular, a Tk opt-out never selects Tk indirectly.
    """
    preferred = get_preferred_ui()
    system = platform.system()
    native_available = system in {"Darwin", "Linux", "Windows"}
    candidates: Tuple[str, ...]

    if preferred == "headless":
        return "headless"

    if preferred == "tkinter":
        candidates = ("tkinter", "native", "nicegui", "textual")
        if dialog_type not in {"simple", "action"}:
            candidates = ("tkinter", "nicegui", "textual")
    elif preferred == "nicegui":
        candidates = ("nicegui", "textual", "native")
        if dialog_type not in {"simple", "action"}:
            candidates = ("nicegui", "textual")
    elif preferred == "textual":
        candidates = ("textual", "native")
        if dialog_type not in {"simple", "action"}:
            candidates = ("textual",)
    elif dialog_type in {"simple", "action"}:
        # Tk remains useful for a dialog tied to a known secondary display,
        # but native macOS dialogs are safer when no placement is required.
        if system == "Darwin" and screen_bounds is None:
            candidates = ("native", "tkinter", "nicegui", "textual")
        elif system == "Darwin":
            candidates = ("tkinter", "native", "nicegui", "textual")
        elif dialog_type == "action":
            # Keep existing Linux/Windows action behavior.  Native fallbacks
            # remain available when explicitly requested or for macOS, where
            # the tray's Tk process can be unsafe or absent.
            candidates = ("tkinter",)
        else:
            candidates = ("native", "tkinter", "nicegui", "textual")
    else:
        candidates = ("tkinter", "nicegui", "textual")

    for provider in candidates:
        if provider == "native" and native_available:
            return provider
        if provider == "tkinter" and _tkinter_available():
            return provider
        if provider == "nicegui" and _nicegui_available():
            return provider
        # A tray callback is often not attached to a TTY.  The caller can
        # open a terminal for Textual, so import availability is sufficient.
        if provider == "textual" and _textual_installed():
            return provider

    return "headless"


def is_interactive_available() -> bool:
    """Return True if any interactive dialog tier is available."""
    return _tkinter_available() or _nicegui_available() or _textual_available()


def _ensure_tcl_library():
    """Set TCL_LIBRARY if not already set, searching common install locations.

    uv/pyenv venvs often can't find the system Tcl/Tk — this resolves the
    "Can't find a usable init.tcl" error at tk.Tk() time.
    """
    if os.environ.get("TCL_LIBRARY"):
        return

    import pathlib
    import sys

    candidates = []
    real_exe = pathlib.Path(sys.executable).resolve()
    candidates.append(real_exe.parent.parent / "lib" / "tcl8.6")

    if platform.system() == "Darwin":
        candidates += [
            pathlib.Path("/opt/homebrew/Cellar/tcl-tk@8") / "8.6.18" / "lib" / "tcl8.6",
            pathlib.Path("/opt/homebrew/opt/tcl-tk@8/lib/tcl8.6"),
            pathlib.Path("/opt/homebrew/opt/tcl-tk/lib/tcl8.6"),
            pathlib.Path("/usr/local/opt/tcl-tk/lib/tcl8.6"),
        ]
        import glob

        for match in glob.glob("/opt/homebrew/Cellar/tcl-tk@8/*/lib/tcl8.6"):
            candidates.append(pathlib.Path(match))
    elif platform.system() == "Linux":
        candidates += [
            pathlib.Path("/usr/lib/tcl8.6"),
            pathlib.Path("/usr/share/tcltk/tcl8.6"),
        ]

    for path in candidates:
        if (path / "init.tcl").exists():
            os.environ["TCL_LIBRARY"] = str(path)
            return
