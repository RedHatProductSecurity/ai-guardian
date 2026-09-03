"""Reusable proactive prompts for tray-managed user actions.

Prompts are deliberately small and dependency-light so they can be shown from
the tray's worker thread.  A prompt's decision is persisted independently of
the feature that requested it, allowing upgrade prompts and future proactive
notifications to share the same snooze/dismiss behavior.
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

from ai_guardian.tui.display import (
    _nicegui_available,
    _textual_available,
    _tkinter_available,
    get_preferred_ui,
)

logger = logging.getLogger(__name__)

SNOOZE_OPTIONS = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
}


def _state_path() -> Path:
    from ai_guardian.config.utils import get_state_dir

    return get_state_dir() / "proactive_prompts.json"


class ProactivePromptState:
    """Persistent state for proactive prompts."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or _state_path()
        self._lock = threading.Lock()

    def load(self) -> Dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def save(self, data: Dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            logger.warning("Unable to persist proactive prompt state: %s", exc)

    def available(self, key: str, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        entry = self.load().get(key, {})
        if entry.get("status") == "dismissed":
            return False
        if entry.get("status") != "snoozed":
            return True
        try:
            timestamp = entry["snooze_until"]
            if timestamp.endswith("Z"):
                timestamp = timestamp[:-1] + "+00:00"
            snooze_until = datetime.fromisoformat(timestamp)
            if snooze_until.tzinfo is None:
                snooze_until = snooze_until.replace(tzinfo=timezone.utc)
            return snooze_until <= now
        except (KeyError, TypeError, ValueError):
            return True

    def record(self, key: str, result: str, now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
        if result == "action":
            return
        entry = {"status": "dismissed" if result == "dismiss" else "snoozed"}
        if result.startswith("snooze_"):
            option = result.removeprefix("snooze_")
            duration = SNOOZE_OPTIONS.get(option)
            if duration is None:
                return
            entry["snooze_until"] = (now + duration).isoformat().replace("+00:00", "Z")
        with self._lock:
            data = self.load()
            data[key] = entry
            self.save(data)


class ProactivePromptDialog:
    """Prompt with action, snooze, and dismiss choices.

    The UI cascade is tkinter, NiceGUI, Textual, then a log-only fallback.
    ``show`` always returns a stable string, which makes the dialog easy to
    exercise without starting a desktop UI in tests.
    """

    def __init__(
        self,
        title: str,
        message: str,
        action_label: str,
        dismiss_label: str,
        snooze_options: Optional[Iterable[str]] = None,
    ):
        self.title = title
        self.message = message
        self.action_label = action_label
        self.dismiss_label = dismiss_label
        self.snooze_options = tuple(snooze_options or SNOOZE_OPTIONS)

    def show(self, tray_safe: bool = False) -> str:
        preferred = get_preferred_ui()
        tiers = (
            ["tkinter", "nicegui", "textual"] if preferred == "auto" else [preferred]
        )
        for tier in tiers:
            try:
                if tier == "tkinter" and _tkinter_available():
                    if tray_safe:
                        return self._show_tkinter_subprocess()
                    return self._show_tkinter()
                if tier == "nicegui" and _nicegui_available():
                    return self._show_nicegui()
                if tier == "textual" and _textual_available():
                    return self._show_textual()
            except Exception as exc:
                logger.debug("Proactive %s prompt unavailable: %s", tier, exc)
        logger.info("%s: %s", self.title, self.message)
        return "dismiss"

    def _show_tkinter_subprocess(self) -> str:
        """Show Tkinter dialog outside tray process (macOS pystray safety)."""
        import subprocess
        import sys

        payload = json.dumps(
            {
                "title": self.title,
                "message": self.message,
                "action_label": self.action_label,
                "dismiss_label": self.dismiss_label,
                "snooze_options": self.snooze_options,
            }
        )
        child = (
            "import json, sys; "
            "from ai_guardian.tray.proactive_prompt import ProactivePromptDialog; "
            "p=json.loads(sys.argv[1]); "
            "d=ProactivePromptDialog(p['title'], p['message'], "
            "p['action_label'], p['dismiss_label'], p['snooze_options']); "
            "print(d._show_tkinter())"
        )
        try:
            result = subprocess.run(
                [sys.executable, "-c", child, payload],
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip().splitlines()[-1]
        except (OSError, IndexError, subprocess.TimeoutExpired) as exc:
            logger.warning("Tkinter proactive prompt failed: %s", exc)
        return "dismiss"

    def _show_tkinter(self) -> str:
        import tkinter as tk
        from tkinter import ttk

        result = {"value": "dismiss"}
        root = tk.Tk()
        root.title(self.title)
        root.resizable(False, False)
        frame = ttk.Frame(root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text=self.message, justify="left", wraplength=420).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 14)
        )
        snooze = tk.StringVar(
            value=self.snooze_options[0] if self.snooze_options else ""
        )

        def choose(value):
            result["value"] = value
            root.destroy()

        ttk.Button(
            frame, text=self.action_label, command=lambda: choose("action")
        ).grid(row=1, column=0, padx=(0, 8))
        if self.snooze_options:
            ttk.OptionMenu(frame, snooze, snooze.get(), *self.snooze_options).grid(
                row=1, column=1, padx=(0, 8)
            )
            ttk.Button(
                frame,
                text="Later",
                command=lambda: choose("snooze_" + snooze.get()),
            ).grid(row=1, column=2, padx=(0, 8))
        ttk.Button(
            frame, text=self.dismiss_label, command=lambda: choose("dismiss")
        ).grid(row=1, column=3)
        root.protocol("WM_DELETE_WINDOW", lambda: choose("dismiss"))
        root.bind("<Escape>", lambda _event: choose("dismiss"))
        root.lift()
        root.attributes("-topmost", True)
        root.after(100, lambda: root.attributes("-topmost", False))
        root.mainloop()
        return result["value"]

    def _show_nicegui(self) -> str:
        from nicegui import app, ui

        result = {"value": "dismiss"}
        done = threading.Event()

        def choose(value):
            result["value"] = value
            done.set()
            app.shutdown()

        with ui.card():
            ui.label(self.title).classes("text-h6")
            ui.label(self.message)
            with ui.row():
                ui.button(self.action_label, on_click=lambda: choose("action"))
                for option in self.snooze_options:
                    ui.button(
                        f"Later ({option})",
                        on_click=lambda option=option: choose(f"snooze_{option}"),
                    )
                ui.button(self.dismiss_label, on_click=lambda: choose("dismiss"))

        ui.run(title=self.title, reload=False, show=True, port=0)
        done.wait(timeout=3600)
        return result["value"]

    def _show_textual(self) -> str:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Button, Label

        dialog = self

        class PromptApp(App):
            def compose(self) -> ComposeResult:
                with Vertical():
                    yield Label(dialog.title)
                    yield Label(dialog.message)
                    with Horizontal():
                        yield Button(dialog.action_label, id="action")
                        for index, option in enumerate(dialog.snooze_options):
                            yield Button(f"Later ({option})", id=f"snooze_{index}")
                        yield Button(dialog.dismiss_label, id="dismiss")

            def on_button_pressed(self, event: Button.Pressed) -> None:
                button_id = event.button.id or "dismiss"
                if button_id == "action":
                    value = "action"
                elif button_id.startswith("snooze_"):
                    index = int(button_id.rsplit("_", 1)[1])
                    value = f"snooze_{dialog.snooze_options[index]}"
                else:
                    value = "dismiss"
                self.result = value
                self.exit()

        app = PromptApp()
        app.result = "dismiss"
        app.run()
        return app.result
