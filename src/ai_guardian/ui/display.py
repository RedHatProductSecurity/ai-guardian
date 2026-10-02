"""Shared display tier detection for prompt and tray dialogs.

Complex-dialog cascade: tkinter -> NiceGUI (browser) -> headless.
Simple/actionable tray dialogs may use the platform-native provider first.

``AI_GUARDIAN_NO_TKINTER=1`` skips tkinter even when it is installed.
"""

import json
import logging
import os
import platform
from typing import Tuple

logger = logging.getLogger(__name__)

VALID_PREFERRED_UI = {"auto", "tkinter", "nicegui", "headless"}


def get_preferred_ui() -> str:
    """Return the preferred UI toolkit from env var or config."""
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
            # Existing configs may contain the removed terminal provider.
            if val == "textual":
                val = "nicegui"
            if val in VALID_PREFERRED_UI:
                return val
    except Exception:
        pass  # intentionally silent — optional config

    return "auto"


def _tkinter_available() -> bool:
    """Return True if tkinter can be imported."""
    if os.environ.get("AI_GUARDIAN_NO_TKINTER"):
        return False
    try:
        import tkinter  # noqa: F401

        return True
    except ImportError:
        return False


def select_ui_provider(
    dialog_type: str = "simple",
    *,
    screen_bounds=None,
) -> str:
    """Select the first usable provider for a tray dialog.

    NiceGUI is a required dependency, so selecting it does not perform an
    availability probe. A missing installation is an installation error that
    doctor reports rather than a reason to reintroduce a terminal UI.
    """
    preferred = get_preferred_ui()
    system = platform.system()
    native_available = system in {"Darwin", "Linux", "Windows"}
    candidates: Tuple[str, ...]

    if preferred == "headless":
        return "headless"

    if preferred == "tkinter":
        candidates = ("tkinter", "native", "nicegui")
        if dialog_type not in {"simple", "action"}:
            candidates = ("tkinter", "nicegui")
    elif preferred == "nicegui":
        candidates = ("nicegui", "native")
        if dialog_type not in {"simple", "action"}:
            candidates = ("nicegui",)
    elif dialog_type in {"simple", "action"}:
        if system == "Darwin" and screen_bounds is None:
            candidates = ("native", "tkinter", "nicegui")
        elif system == "Darwin":
            candidates = ("tkinter", "native", "nicegui")
        elif dialog_type == "action":
            candidates = ("tkinter", "nicegui")
        else:
            candidates = ("native", "tkinter", "nicegui")
    else:
        candidates = ("tkinter", "nicegui")

    for provider in candidates:
        if provider == "native" and native_available:
            return provider
        if provider == "tkinter" and _tkinter_available():
            return provider
        if provider == "nicegui":
            return provider

    return "headless"


def is_interactive_available() -> bool:
    """Return True when an interactive dialog tier is configured."""
    return get_preferred_ui() != "headless"


def _ensure_tcl_library() -> None:
    """Set TCL_LIBRARY when a Python runtime cannot find its Tcl/Tk files."""
    if os.environ.get("TCL_LIBRARY"):
        return

    import pathlib
    import sys

    candidates = [
        pathlib.Path(sys.executable).resolve().parent.parent / "lib" / "tcl8.6"
    ]
    if platform.system() == "Darwin":
        candidates += [
            pathlib.Path("/opt/homebrew/Cellar/tcl-tk@8") / "8.6.18" / "lib" / "tcl8.6",
            pathlib.Path("/opt/homebrew/opt/tcl-tk@8/lib/tcl8.6"),
            pathlib.Path("/opt/homebrew/opt/tcl-tk/lib/tcl8.6"),
            pathlib.Path("/usr/local/opt/tcl-tk/lib/tcl8.6"),
        ]
        import glob

        candidates.extend(
            pathlib.Path(match)
            for match in glob.glob("/opt/homebrew/Cellar/tcl-tk@8/*/lib/tcl8.6")
        )
    elif platform.system() == "Linux":
        candidates += [
            pathlib.Path("/usr/lib/tcl8.6"),
            pathlib.Path("/usr/share/tcltk/tcl8.6"),
        ]

    for path in candidates:
        if (path / "init.tcl").exists():
            os.environ["TCL_LIBRARY"] = str(path)
            return
