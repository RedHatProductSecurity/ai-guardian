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
from typing import Callable, Optional
from ai_guardian.ui.monitor import screen_payload, prepare_tk_display

from ai_guardian.tray.sandbox_dialog import (
    ScreenBounds,
    _get_tray_screen_bounds,
    _place_window_on_screen,
)

logger = logging.getLogger(__name__)
_MESSAGE_READY = "ai-guardian-message-ready"


def show_tkinter_message_subprocess(
    title: str,
    message: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
    links: tuple[tuple[str, str], ...] = (),
) -> Optional[bool]:
    """Show a simple message dialog in an isolated Tk process.

    ``None`` permits native fallback only when Tk failed before display. ``True``
    means normal completion; ``False`` means an interrupted wait or a failure
    after display, neither of which should open a replacement window. There is
    no deadline for reading the message. Explicit links open only on user action.
    """
    payload = json.dumps(
        {
            "title": title,
            "message": message,
            "screen_bounds": screen_payload(screen_bounds),
            "links": links,
        },
        ensure_ascii=False,
    )
    child = (
        "import json, sys; "
        "from ai_guardian.tray.dialog_placement import _show_tkinter_message; "
        "p=json.loads(sys.argv[1]); "
        "_show_tkinter_message(p['title'], p['message'], "
        "screen_bounds=p.get('screen_bounds'), links=p.get('links', ()), "
        f"on_ready=lambda: print({_MESSAGE_READY!r}, flush=True))"
    )
    logger.debug("Starting isolated Tkinter message dialog")
    try:
        result = subprocess.run(
            [sys.executable, "-c", child, payload],
            capture_output=True,
            text=True,
            timeout=None,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # A surrounding runner may interrupt its wait. Visibility is unknown;
        # do not interpret that as permission to open another provider.
        logger.warning(
            "Tkinter message dialog wait interrupted; not opening a replacement"
        )
        return False
    except OSError as exc:
        logger.warning("Tkinter message dialog could not start: %s", type(exc).__name__)
        return None
    if result.returncode != 0:
        displayed = _MESSAGE_READY in (result.stdout or "").splitlines()
        logger.warning(
            "Tkinter message dialog failed %s with exit code %s",
            (
                "after display; not opening a replacement"
                if displayed
                else "before display"
            ),
            result.returncode,
        )
        return False if displayed else None
    logger.debug("Tkinter message dialog dismissed")
    return True


def _show_tkinter_message(
    title: str,
    message: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
    links: tuple[tuple[str, str], ...] = (),
    on_ready: Optional[Callable[[], None]] = None,
) -> None:
    """Show the child-process implementation of a simple message dialog."""
    import tkinter as tk
    from tkinter import ttk

    from ai_guardian.ui.display import _ensure_tcl_library

    _ensure_tcl_library()
    prepare_tk_display()
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

    ready_reported = False

    def mapped(event):
        nonlocal ready_reported
        if event.widget is root and not ready_reported:
            ready_reported = True
            if on_ready is not None:
                on_ready()

    # Child widgets also emit Map events. Report only the completed root, once,
    # so a later child-process failure cannot trigger a different toolkit.
    root.bind("<Map>", mapped, add="+")

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


def show_nicegui_message_subprocess(
    title, message, *, links=(), screen_bounds=None
) -> bool:
    """Keep the browser server outside the tray's GUI process."""
    from ai_guardian.ui.modal import run_modal_subprocess

    child = (
        "import json, sys; "
        "from ai_guardian.tray.dialog_placement import _show_nicegui_message; "
        "from ai_guardian.ui.modal import run_modal_child; "
        "p=json.loads(sys.argv[1]); "
        "run_modal_child(lambda: _show_nicegui_message(**p))"
    )
    result = run_modal_subprocess(
        [
            sys.executable,
            "-c",
            child,
            json.dumps(
                {
                    "title": title,
                    "message": message,
                    "links": links,
                    "screen_bounds": screen_payload(screen_bounds),
                }
            ),
        ]
    )
    return result.returncode == 0


def _show_nicegui_message(title, message, *, links=(), screen_bounds=None) -> bool:
    """Preserve complete text and user-activated links in the browser tier."""
    from nicegui import app, ui
    from ai_guardian.ui.modal import run_nicegui_modal

    def close():
        ui.run_javascript("window.close()")
        ui.timer(0.1, app.shutdown, once=True)

    @ui.page("/")
    def page():
        with ui.card().classes("mx-auto mt-8 max-w-3xl"):
            ui.label(title).classes("text-xl font-bold")
            for line in message.splitlines():
                if not any(anchor and anchor in line for anchor, _url in links):
                    ui.label(line).classes("whitespace-pre-wrap")
                    continue
                with ui.row().classes("gap-0 items-baseline"):
                    remaining = line
                    while remaining:
                        matches = [
                            (remaining.index(anchor), anchor, url)
                            for anchor, url in links
                            if anchor and anchor in remaining
                        ]
                        if not matches:
                            ui.label(remaining).classes("whitespace-pre-wrap")
                            break
                        index, anchor, url = min(matches, key=lambda item: item[0])
                        if index:
                            ui.label(remaining[:index]).classes("whitespace-pre-wrap")
                        ui.link(anchor, url, new_tab=True)
                        remaining = remaining[index + len(anchor) :]
            ui.button("OK", on_click=close)

    run_nicegui_modal(title, screen_bounds=screen_bounds)
    return True


__all__ = [
    "ScreenBounds",
    "_get_tray_screen_bounds",
    "_place_window_on_screen",
    "show_tkinter_message_subprocess",
]
