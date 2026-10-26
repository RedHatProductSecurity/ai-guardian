"""Shared display tier detection for prompt and tray dialogs.

Automatic cascade: native -> tkinter -> NiceGUI, among capable providers.
Explicit toolkit preferences are exclusive; headless never opens a dialog.

``AI_GUARDIAN_NO_TKINTER=1`` skips tkinter even when it is installed.
"""

import json
import logging
import os
import platform

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
    except (OSError, ValueError, TypeError, AttributeError):
        logger.warning("Unable to read preferred dialog UI; using automatic selection")

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


def ui_provider_order(
    dialog_type: str = "simple",
    *,
    screen_bounds=None,
    preferred=None,
) -> tuple[str, ...]:
    """Return eligible tiers, not a guarantee that a provider can start.

    Native supports messages, confirmations and pickers on all desktop platforms,
    single-field forms on all desktops, actions on Linux/macOS, and complete
    setup controls only on macOS (Cocoa).
    AppleScript cannot place a message/panel on a specified monitor. Rich forms,
    linked messages and streams skip native rather than losing controls.
    Callers intersect these tiers with their actual implementations. See
    docs/MODAL_PROVIDERS.md for the complete inventory and exceptions.
    """
    preferred = preferred or get_preferred_ui()
    system = platform.system()
    if preferred == "headless":
        return ()
    native = system in {"Darwin", "Linux", "Windows"} and dialog_type in {
        "simple",
        "confirmation",
        "picker",
        "basic_form",
    }
    native |= dialog_type == "action" and system in {"Darwin", "Linux"}
    native |= dialog_type == "setup" and system == "Darwin"
    if (
        system == "Darwin"
        and screen_bounds is not None
        and dialog_type in {"simple", "confirmation", "picker"}
    ):
        native = False
    candidates = (
        ("native", "tkinter", "nicegui") if preferred == "auto" else (preferred,)
    )
    return tuple(
        provider
        for provider in candidates
        if (provider == "native" and native)
        or (provider == "tkinter" and _tkinter_available())
        or provider == "nicegui"
    )


def select_ui_provider(dialog_type: str = "simple", *, screen_bounds=None) -> str:
    """Return the first eligible tier; execution must use the modal runner."""
    return next(
        iter(ui_provider_order(dialog_type, screen_bounds=screen_bounds)), "headless"
    )


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
