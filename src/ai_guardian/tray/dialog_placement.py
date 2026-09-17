"""Shared display-aware placement helpers for tray-created dialogs.

The tray callback receives the useful display context while the menu is open.
This module keeps that context as plain geometry so it can safely cross a
short-lived subprocess boundary on macOS, where creating Tk widgets in the
pystray process is unsafe.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import Optional

from ai_guardian.tray.sandbox_dialog import (
    ScreenBounds,
    _get_tray_screen_bounds,
    _place_window_on_screen,
)

logger = logging.getLogger(__name__)


def show_tkinter_message_subprocess(
    title: str,
    message: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> Optional[bool]:
    """Show a simple message dialog in an isolated Tk process.

    ``None`` means Tk could not be launched and lets callers retain their
    platform-native fallback.  A boolean result means the dialog process ran
    successfully; message dialogs only have an OK action, so it is ``True``.
    """
    payload = json.dumps(
        {
            "title": title,
            "message": message,
            "screen_bounds": screen_bounds,
        },
        ensure_ascii=False,
    )
    child = (
        "import json, sys; "
        "from ai_guardian.tray.dialog_placement import _show_tkinter_message; "
        "p=json.loads(sys.argv[1]); "
        "_show_tkinter_message(p['title'], p['message'], "
        "screen_bounds=p.get('screen_bounds'))"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", child, payload],
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("Tkinter message dialog could not be shown: %s", exc)
        return None
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        logger.debug(
            "Tkinter message dialog exited with code %s%s",
            result.returncode,
            f": {detail[:200]}" if detail else "",
        )
        return None
    return True


def _show_tkinter_message(
    title: str,
    message: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> None:
    """Show the child-process implementation of a simple message dialog."""
    import tkinter as tk
    from tkinter import ttk

    from ai_guardian.tui.display import _ensure_tcl_library

    _ensure_tcl_library()
    root = tk.Tk()
    root.title(title)
    root.geometry("560x260")
    _place_window_on_screen(root, screen_bounds, 560, 260)
    root.minsize(420, 180)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(0, weight=1)
    ttk.Label(frame, text=message, justify="left", wraplength=510).grid(
        row=0, column=0, sticky="w", pady=(0, 18)
    )

    def close() -> None:
        root.destroy()

    ttk.Button(frame, text="OK", command=close).grid(row=1, column=0, sticky="e")
    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<Escape>", lambda _event: close())
    root.update_idletasks()
    root.lift()
    root.focus_force()
    try:
        root.grab_set()
        root.attributes("-topmost", True)
        root.after(150, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        # Some desktop environments reject modal window hints; the dialog is
        # still usable as an ordinary window in that case.
        pass
    root.mainloop()


__all__ = [
    "ScreenBounds",
    "_get_tray_screen_bounds",
    "_place_window_on_screen",
    "show_tkinter_message_subprocess",
]
