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
from functools import partial
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
    links: tuple[tuple[str, str], ...] = (),
) -> Optional[bool]:
    """Show a simple message dialog in an isolated Tk process.

    ``None`` means Tk could not be launched and lets callers retain their
    platform-native fallback.  A boolean result means the dialog process ran
    successfully; OK closes the dialog, so it is ``True``. Explicit links open
    only on mouse/keyboard activation and do not dismiss the About information.
    """
    payload = json.dumps(
        {
            "title": title,
            "message": message,
            "screen_bounds": screen_bounds,
            "links": links,
        },
        ensure_ascii=False,
    )
    child = (
        "import json, sys; "
        "from ai_guardian.tray.dialog_placement import _show_tkinter_message; "
        "p=json.loads(sys.argv[1]); "
        "_show_tkinter_message(p['title'], p['message'], "
        "screen_bounds=p.get('screen_bounds'), links=p.get('links', ()))"
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
    links: tuple[tuple[str, str], ...] = (),
) -> None:
    """Show the child-process implementation of a simple message dialog."""
    import tkinter as tk
    from tkinter import ttk

    from ai_guardian.ui.display import _ensure_tcl_library

    _ensure_tcl_library()
    root = tk.Tk()
    root.withdraw()  # Map once, after layout and the temporary raising hint are ready.
    root.title(title)
    height = max(260, min(640, 100 + 22 * len(message.splitlines()))) if links else 260
    root.geometry(f"560x{height}")
    _place_window_on_screen(root, screen_bounds, 560, height)
    root.minsize(420, 180)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    content = ttk.Frame(frame)
    content.grid(row=0, column=0, sticky="w", pady=(0, 18))
    content.columnconfigure(0, weight=1)

    def open_link(url, _event=None):
        import webbrowser

        webbrowser.open(url)

    for row, line in enumerate(message.splitlines() if links else [message]):
        label = ttk.Label(content, text=line, justify="left", wraplength=510)
        label.grid(row=row, column=0, sticky="w")
        url = next((url for anchor, url in links if anchor and anchor in line), None)
        if url:
            label.configure(foreground="#2563eb", cursor="hand2", takefocus=True)
            for event in ("<Button-1>", "<Return>", "<space>"):
                label.bind(event, partial(open_link, url))

    def close() -> None:
        root.destroy()

    ttk.Button(frame, text="OK", command=close).grid(row=1, column=0, sticky="e")
    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<Escape>", lambda _event: close())

    def focus():
        try:
            if root.winfo_exists():
                root.deiconify()
                root.lift()
                root.focus_force()
                root.grab_set()
        except tk.TclError:
            logger.debug("Message dialog closed or rejected foreground focus")

    def finish_startup():
        try:
            if root.winfo_exists():
                root.attributes("-topmost", False)
        except tk.TclError:
            logger.debug("Message dialog raising hint could not be cleared")
        # Clearing topmost or closing the tray popup can change stacking/focus
        # on KDE/XWayland. Restore once after that handoff, never continuously.
        focus()

    root.update_idletasks()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        logger.debug("Message dialog window manager does not accept a raising hint")
    root.deiconify()
    root.lift()
    root.after_idle(focus)
    root.after(200, finish_startup)
    root.mainloop()


__all__ = [
    "ScreenBounds",
    "_get_tray_screen_bounds",
    "_place_window_on_screen",
    "show_tkinter_message_subprocess",
]
