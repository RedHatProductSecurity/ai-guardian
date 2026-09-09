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
from typing import Dict, Iterable, Optional, Set

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

IDE_SETUP_EXCLUSIONS_KEY = "ide_setup_never_install"
IDE_SETUP_STATUS_KEY = "ide_setup_status"
IDE_SETUP_KEY_PREFIX = "ide_setup_"

_PROFILE_NOT_SELECTED = object()


def _state_path() -> Path:
    from ai_guardian.config.utils import get_state_dir

    return get_state_dir() / "proactive_prompts.json"


class ProactivePromptState:
    """Persistent state for proactive prompts.

    IDE setup health and prompt decisions are intentionally independent. The
    ``ide_setup_status`` entry is the current or last verified snapshot, while
    ``ide_setup_<combination>`` entries and ``ide_setup_never_install`` only
    control whether an automatic prompt is eligible to appear. A snooze or
    dismissal must never make an unhealthy integration look configured.
    """

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

    def get_ide_setup_exclusions(self) -> Set[str]:
        """Return IDEs the user has chosen not to configure automatically."""
        value = self.load().get(IDE_SETUP_EXCLUSIONS_KEY, [])
        if isinstance(value, dict):
            value = value.keys()
        elif not isinstance(value, (list, tuple, set)):
            return set()
        return {item for item in value if isinstance(item, str)}

    def update_ide_setup_exclusions(
        self,
        install: Iterable[str] = (),
        never: Iterable[str] = (),
    ) -> None:
        """Persist per-IDE automatic setup choices in the state file."""
        install_set = {item for item in install if isinstance(item, str)}
        never_set = {item for item in never if isinstance(item, str)}
        if not install_set and not never_set:
            return

        with self._lock:
            data = self.load()
            excluded = self.get_ide_setup_exclusions()
            updated = (excluded - install_set) | never_set
            if updated == excluded:
                return
            if updated:
                data[IDE_SETUP_EXCLUSIONS_KEY] = sorted(updated)
            else:
                data.pop(IDE_SETUP_EXCLUSIONS_KEY, None)
            self.save(data)

    def update_ide_setup_status(self, status: Dict) -> None:
        """Persist the latest local IDE/setup reality snapshot."""
        if not isinstance(status, dict):
            return
        with self._lock:
            data = self.load()
            data[IDE_SETUP_STATUS_KEY] = status
            self.save(data)

    def get_ide_setup_status(self) -> Dict:
        """Return the last persisted IDE/setup reality snapshot."""
        status = self.load().get(IDE_SETUP_STATUS_KEY)
        return status if isinstance(status, dict) else {}

    def reset_ide_setup(self, ide_type: str) -> Dict:
        """Clear one IDE's automatic-setup decision history and exclusion."""
        if not isinstance(ide_type, str) or not ide_type:
            return {"path": str(self.path), "error": "IDE type is required"}

        with self._lock:
            data = self.load()
            removed_keys = []
            for key in list(data):
                if not isinstance(key, str) or not key.startswith(IDE_SETUP_KEY_PREFIX):
                    continue
                if key in {
                    IDE_SETUP_EXCLUSIONS_KEY,
                    IDE_SETUP_STATUS_KEY,
                }:
                    continue
                combination = key.removeprefix(IDE_SETUP_KEY_PREFIX).split("_")
                if ide_type in combination:
                    removed_keys.append(key)
                    data.pop(key, None)

            exclusions = self.get_ide_setup_exclusions()
            removed_exclusion = ide_type in exclusions
            exclusions.discard(ide_type)
            if exclusions:
                data[IDE_SETUP_EXCLUSIONS_KEY] = sorted(exclusions)
            else:
                data.pop(IDE_SETUP_EXCLUSIONS_KEY, None)

            status_updated = False
            status = data.get(IDE_SETUP_STATUS_KEY)
            if isinstance(status, dict):
                never_install = status.get("never_install", [])
                if isinstance(never_install, list) and ide_type in never_install:
                    status["never_install"] = [
                        item for item in never_install if item != ide_type
                    ]
                    status_updated = True
                integrations = status.get("integrations", {})
                integration = (
                    integrations.get(ide_type)
                    if isinstance(integrations, dict)
                    else None
                )
                if isinstance(integration, dict) and integration.get("excluded"):
                    integration["excluded"] = False
                    status_updated = True
                if status_updated:
                    data[IDE_SETUP_STATUS_KEY] = status

            changed = bool(removed_keys or removed_exclusion or status_updated)
            if changed:
                self.save(data)

        return {
            "path": str(self.path),
            "ide": ide_type,
            "removed_prompt_keys": sorted(removed_keys),
            "removed_exclusion": removed_exclusion,
            "status_updated": status_updated,
            "changed": changed,
        }


def sync_ide_setup_state(
    state: Optional[ProactivePromptState] = None,
    setup=None,
    now: Optional[datetime] = None,
    skip_excluded: bool = False,
) -> Dict:
    """Refresh the persisted IDE/setup status from the local configuration.

    The existing ``ide_setup_<combination>`` records are prompt history and
    are deliberately retained. This function adds a current, canonical
    ``ide_setup_status`` snapshot without changing setup hooks or exclusions.
    The tray sets ``skip_excluded`` for automatic monitoring so an IDE marked
    Never install is not rechecked; its last verified result remains visible.
    Explicit manual syncs still verify excluded IDEs by default.
    """
    if state is None:
        state = ProactivePromptState()
    if setup is None:
        from ai_guardian.setup.hooks import IDESetup

        setup = IDESetup()

    try:
        installed = setup.list_installed_ides()
    except Exception as exc:
        logger.warning("Unable to sync IDE setup state: %s", exc)
        return {"path": str(state.path), "error": str(exc)}

    if not isinstance(installed, (list, tuple, set)):
        error = "IDE setup discovery returned an invalid result"
        logger.warning(error)
        return {"path": str(state.path), "error": error}

    installed = [ide for ide in installed if isinstance(ide, str)]
    exclusions = state.get_ide_setup_exclusions()
    ide_configs = getattr(setup, "IDE_CONFIGS", {})
    previous_status = state.get_ide_setup_status()
    previous_integrations = (
        previous_status.get("integrations", {})
        if isinstance(previous_status, dict)
        else {}
    )
    if not isinstance(previous_integrations, dict):
        previous_integrations = {}
    integrations = {}

    for ide_type in installed:
        config = ide_configs.get(ide_type, {})
        previous_verification = previous_integrations.get(ide_type)
        if skip_excluded and ide_type in exclusions:
            if isinstance(previous_verification, dict):
                verification = dict(previous_verification)
            else:
                verification = {
                    "ide": ide_type,
                    "healthy": False,
                    "events": {},
                    "obsolete": [],
                    "verification_skipped": True,
                }
            verification["verification_skipped"] = True
            verification["verification_skip_reason"] = "Never install selected"
        else:
            try:
                verifier = getattr(setup, "verify_ide_setup", None)
                if not callable(verifier):
                    verifier = setup.verify_hooks_for_ide
                verification = verifier(ide_type)
                if not isinstance(verification, dict):
                    verification = {
                        "ide": ide_type,
                        "healthy": False,
                        "events": {},
                        "obsolete": [],
                        "error": "Invalid verification result",
                    }
            except Exception as exc:
                logger.warning("Unable to verify IDE setup for %s: %s", ide_type, exc)
                verification = {
                    "ide": ide_type,
                    "healthy": False,
                    "events": {},
                    "obsolete": [],
                    "error": str(exc),
                }

        current = dict(verification)
        current["name"] = config.get("name", ide_type)
        current["excluded"] = ide_type in exclusions
        integrations[ide_type] = current

    configured = [
        ide_type
        for ide_type, status in integrations.items()
        if status.get("healthy") is True
    ]
    needs_setup = [
        ide_type
        for ide_type, status in integrations.items()
        if status.get("healthy") is not True
    ]
    snapshot = {
        "path": str(state.path),
        "checked_at": (now or datetime.now(timezone.utc))
        .isoformat()
        .replace("+00:00", "Z"),
        "installed": installed,
        "configured": configured,
        "needs_setup": needs_setup,
        "never_install": sorted(exclusions),
        "integrations": integrations,
    }
    state.update_ide_setup_status(snapshot)
    return snapshot


def reset_ide_setup_state(
    ide_type: str,
    state: Optional[ProactivePromptState] = None,
) -> Dict:
    """Reset one IDE's setup prompt decisions in the local state file."""
    return (state or ProactivePromptState()).reset_ide_setup(ide_type)


class ProactivePromptDialog:
    """Prompt with action, snooze, and dismiss choices.

    The UI cascade is tkinter, NiceGUI, Textual, then a log-only fallback.
    show returns a stable string for ordinary prompts. When IDE or profile
    choices are provided it returns a mapping containing the selected values.
    """

    def __init__(
        self,
        title: str,
        message: str,
        action_label: str,
        dismiss_label: Optional[str],
        snooze_options: Optional[Iterable[str]] = None,
        ide_choices: Optional[Iterable[Dict[str, str]]] = None,
        profile_choices: Optional[Iterable[Dict[str, str]]] = None,
    ):
        self.title = title
        self.message = message
        self.action_label = action_label
        self.dismiss_label = dismiss_label
        self.snooze_options = tuple(snooze_options or SNOOZE_OPTIONS)
        self.ide_choices = tuple(ide_choices or ())
        self.profile_choices = tuple(profile_choices or ())

    def _profile_options(self):
        """Return valid profile options plus an explicit skip choice."""
        options = []
        seen = set()
        for choice in self.profile_choices:
            if not isinstance(choice, dict):
                continue
            profile = choice.get("profile") or choice.get("name")
            if not isinstance(profile, str) or not profile or profile in seen:
                continue
            seen.add(profile)
            options.append(
                {
                    "profile": profile,
                    "name": str(choice.get("name") or profile),
                    "description": str(choice.get("description") or ""),
                }
            )
        if options:
            options.append(
                {
                    "profile": None,
                    "name": "Skip configuration for now",
                    "description": "Set up hooks without creating a user config",
                }
            )
        return options

    def _default_profile_selection(self):
        """Return the recommended profile, falling back to the first option."""
        options = self._profile_options()
        for option in options:
            if option["profile"] == "@standard":
                return option["profile"]
        return options[0]["profile"] if options else None

    @staticmethod
    def _profile_choice_label(option):
        """Format a profile option for the interactive selectors."""
        label = option["name"]
        description = option.get("description")
        return f"{label} — {description}" if description else label

    def show(self, tray_safe: bool = False) -> object:
        import platform

        preferred = get_preferred_ui()
        if preferred == "auto":
            tiers = ["tkinter", "nicegui", "textual"]
        else:
            tiers = [preferred]

        # pystray owns an NSApplication with accessory activation policy on
        # modern macOS.  Keep the prompt outside that process by using the
        # Tkinter subprocess path first.  NiceGUI is deliberately excluded:
        # starting it in the tray worker can open a browser against the
        # default web-console port before its page is ready, producing an
        # Internal Server Error instead of a setup prompt.
        if tray_safe and platform.system() == "Darwin":
            if preferred == "auto":
                tiers = ["tkinter", "textual"]
            elif preferred == "nicegui":
                tiers = ["tkinter"]
            logger.info(
                "Using subprocess/native UI for tray prompt on macOS; "
                "skipping in-process NiceGUI"
            )

        for tier in tiers:
            try:
                if tier == "tkinter" and _tkinter_available():
                    if tray_safe:
                        result = self._show_tkinter_subprocess()
                        if result is not None:
                            return result
                        continue
                    if self.ide_choices or self._profile_options():
                        return self._show_ide_choices_tkinter()
                    return self._show_tkinter()
                if tier == "nicegui" and _nicegui_available():
                    if self.ide_choices or self._profile_options():
                        return self._show_ide_choices_nicegui()
                    return self._show_nicegui()
                if tier == "textual" and _textual_available():
                    if self.ide_choices or self._profile_options():
                        return self._show_ide_choices_textual()
                    return self._show_textual()
            except Exception as exc:
                logger.debug("Proactive %s prompt unavailable: %s", tier, exc)

        if tray_safe and platform.system() == "Darwin" and preferred != "headless":
            try:
                result = self._show_native_fallback()
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning("Native macOS proactive prompt failed: %s", exc)

        logger.info("%s: %s", self.title, self.message)
        return "dismiss"

    def _show_native_fallback(self) -> Optional[object]:
        """Show an actionable native fallback when tray UI tiers fail."""
        from ai_guardian.tray.plugins import show_action_dialog

        return show_action_dialog(
            self.title,
            self.message,
            self.action_label,
            self.dismiss_label,
            self.snooze_options,
            ide_choices=self.ide_choices,
            profile_choices=self._profile_options(),
        )

    def _show_tkinter_subprocess(self) -> Optional[object]:
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
                "ide_choices": self.ide_choices,
                "profile_choices": self.profile_choices,
            }
        )
        child = (
            "import json, sys; "
            "from ai_guardian.tray.proactive_prompt import ProactivePromptDialog; "
            "p=json.loads(sys.argv[1]); "
            "d=ProactivePromptDialog(p['title'], p['message'], "
            "p['action_label'], p['dismiss_label'], p['snooze_options'], "
            "p.get('ide_choices'), p.get('profile_choices')); "
            "value=(d._show_ide_choices_tkinter() if (p.get('ide_choices') "
            "or p.get('profile_choices')) "
            "else d._show_tkinter()); "
            "print(json.dumps(value) if (p.get('ide_choices') "
            "or p.get('profile_choices')) else value)"
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
                output = (result.stdout or "").strip().splitlines()
                if not output:
                    logger.warning("Tkinter proactive prompt returned no result")
                    return None
                value = output[-1]
                return (
                    json.loads(value)
                    if self.ide_choices or self._profile_options()
                    else value
                )
            stderr = (result.stderr or "").strip()
            detail = f": {stderr}" if stderr else ""
            logger.warning(
                "Tkinter proactive prompt exited with code %s%s",
                result.returncode,
                detail,
            )
        except (
            OSError,
            IndexError,
            json.JSONDecodeError,
            subprocess.TimeoutExpired,
        ) as exc:
            logger.warning("Tkinter proactive prompt failed: %s", exc)
        return None

    def _ide_selection_result(
        self,
        result,
        install: Iterable[str] = (),
        never=None,
        profile=_PROFILE_NOT_SELECTED,
    ):
        """Build the serializable result returned by a setup chooser."""
        selection = {
            "result": result,
            "install": list(install),
            "never": list(never or ()),
        }
        if self._profile_options():
            if profile is _PROFILE_NOT_SELECTED:
                profile = self._default_profile_selection()
            selection["profile"] = profile
        return selection

    def _default_ide_selection(self):
        """Return the default selection for each displayed integration."""
        return self._ide_selection_result(
            "action",
            (choice["ide"] for choice in self.ide_choices),
        )

    def _never_ide_selection(self):
        """Return a completed selection that excludes every displayed IDE."""
        return self._ide_selection_result(
            "action",
            never=(choice["ide"] for choice in self.ide_choices),
            profile=(None if self._profile_options() else _PROFILE_NOT_SELECTED),
        )

    def _show_ide_choices_tkinter(self):
        import tkinter as tk
        from tkinter import ttk

        result = {"value": self._ide_selection_result("dismiss")}
        root = tk.Tk()
        root.title(self.title)
        root.resizable(False, False)
        frame = ttk.Frame(root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text=self.message, justify="left", wraplength=560).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 14)
        )

        row = 1
        profile_var = None
        profile_options = self._profile_options()
        if profile_options:
            ttk.Label(frame, text="Security profile").grid(
                row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
            )
            row += 1
            profile_var = tk.StringVar(value=self._default_profile_selection() or "")
            for option in profile_options:
                value = option["profile"] or ""
                ttk.Radiobutton(
                    frame,
                    text=self._profile_choice_label(option),
                    variable=profile_var,
                    value=value,
                ).grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
                row += 1
            row += 1

        if self.ide_choices:
            ttk.Label(frame, text="Integration").grid(
                row=row, column=0, sticky="w", padx=(0, 24), pady=(0, 4)
            )
            ttk.Label(frame, text="Install now").grid(
                row=row, column=1, sticky="w", padx=(0, 18), pady=(0, 4)
            )
            ttk.Label(frame, text="Never install").grid(
                row=row, column=2, sticky="w", pady=(0, 4)
            )
            row += 1

        install_vars = {}
        never_vars = {}
        defaults = self._default_ide_selection()
        default_install = set(defaults["install"])
        default_never = set(defaults["never"])

        def keep_one_selected(selected, other):
            if selected.get():
                other.set(False)
            elif not other.get():
                selected.set(True)

        for index, choice in enumerate(self.ide_choices, start=row):
            key = choice["ide"]
            label = choice.get("name", key)
            detail = choice.get("detail")
            if detail:
                label += f" — {detail}"
            ttk.Label(frame, text=label, justify="left", wraplength=390).grid(
                row=index, column=0, sticky="w", padx=(0, 24), pady=2
            )
            install_var = tk.BooleanVar(value=key in default_install)
            never_var = tk.BooleanVar(value=key in default_never)
            install_vars[key] = install_var
            never_vars[key] = never_var
            ttk.Checkbutton(
                frame,
                variable=install_var,
                command=lambda k=key: keep_one_selected(install_vars[k], never_vars[k]),
            ).grid(row=index, column=1, sticky="w", pady=2)
            ttk.Checkbutton(
                frame,
                variable=never_var,
                command=lambda k=key: keep_one_selected(never_vars[k], install_vars[k]),
            ).grid(row=index, column=2, sticky="w", pady=2)

        def choose(value):
            if value == "action":
                profile = (
                    profile_var.get()
                    if profile_var is not None
                    else _PROFILE_NOT_SELECTED
                )
                if profile == "":
                    profile = None
                install = [key for key, var in install_vars.items() if var.get()]
                never = [key for key, var in never_vars.items() if var.get()]
                result["value"] = self._ide_selection_result(
                    value, install, never, profile
                )
            else:
                result["value"] = (
                    self._never_ide_selection()
                    if value == "never"
                    else self._ide_selection_result(
                        value,
                        profile=(None if profile_options else _PROFILE_NOT_SELECTED),
                    )
                )
            root.destroy()

        button_row = row + len(self.ide_choices)
        ttk.Button(
            frame,
            text=self.action_label,
            command=lambda: choose("action"),
        ).grid(row=button_row, column=0, padx=(0, 8), pady=(14, 0), sticky="w")
        if self.snooze_options:
            snooze = tk.StringVar(value=self.snooze_options[0])
            ttk.OptionMenu(frame, snooze, snooze.get(), *self.snooze_options).grid(
                row=button_row, column=1, padx=(0, 8), pady=(14, 0), sticky="w"
            )
            ttk.Button(
                frame,
                text="Later",
                command=lambda: choose("snooze_" + snooze.get()),
            ).grid(row=button_row, column=2, padx=(0, 8), pady=(14, 0), sticky="w")
        if self.dismiss_label:
            ttk.Button(
                frame,
                text=self.dismiss_label,
                command=lambda: choose(
                    "never" if self.dismiss_label == "Never" else "dismiss"
                ),
            ).grid(row=button_row + 1, column=0, pady=(8, 0), sticky="w")
        root.protocol("WM_DELETE_WINDOW", lambda: choose("dismiss"))
        root.bind("<Escape>", lambda _event: choose("dismiss"))
        root.lift()
        root.focus_force()
        root.attributes("-topmost", True)
        root.after(50, root.focus_force)
        root.after(150, lambda: root.attributes("-topmost", False))
        root.mainloop()
        return result["value"]

    def _show_ide_choices_nicegui(self):
        from nicegui import app, ui

        result = {"value": self._ide_selection_result("dismiss")}
        done = threading.Event()
        controls = {}
        profile_control = None
        defaults = self._default_ide_selection()
        default_install = set(defaults["install"])
        default_never = set(defaults["never"])
        profile_options = self._profile_options()

        def keep_one_selected(selected, other):
            if selected.value:
                other.value = False
            elif not other.value:
                selected.value = True

        def choose(value):
            if value == "action":
                profile = (
                    profile_control.value
                    if profile_control is not None
                    else _PROFILE_NOT_SELECTED
                )
                if profile == "":
                    profile = None
                install = [
                    key for key, pair in controls.items() if pair["install"].value
                ]
                never = [key for key, pair in controls.items() if pair["never"].value]
                result["value"] = self._ide_selection_result(
                    value, install, never, profile
                )
            else:
                result["value"] = (
                    self._never_ide_selection()
                    if value == "never"
                    else self._ide_selection_result(
                        value,
                        profile=(None if profile_options else _PROFILE_NOT_SELECTED),
                    )
                )
            done.set()
            app.shutdown()

        with ui.card().classes("min-w-[620px]"):
            ui.label(self.title).classes("text-h6")
            ui.label(self.message)
            if profile_options:
                ui.label("Security profile").classes("font-bold")
                profile_control = ui.radio(
                    options={
                        option["profile"] or "": self._profile_choice_label(option)
                        for option in profile_options
                    },
                    value=self._default_profile_selection() or "",
                )
            if self.ide_choices:
                with ui.row().classes("items-center font-bold"):
                    ui.label("Integration").classes("w-80")
                    ui.label("Install now").classes("w-28")
                    ui.label("Never install").classes("w-28")
            for choice in self.ide_choices:
                key = choice["ide"]
                label = choice.get("name", key)
                detail = choice.get("detail")
                if detail:
                    label += f" — {detail}"
                with ui.row().classes("items-center"):
                    ui.label(label).classes("w-80")
                    install = ui.checkbox(value=key in default_install)
                    never = ui.checkbox(value=key in default_never)
                controls[key] = {"install": install, "never": never}
                install.on_value_change(
                    lambda _event, k=key: keep_one_selected(
                        controls[k]["install"], controls[k]["never"]
                    )
                )
                never.on_value_change(
                    lambda _event, k=key: keep_one_selected(
                        controls[k]["never"], controls[k]["install"]
                    )
                )
            with ui.row():
                ui.button(self.action_label, on_click=lambda: choose("action"))
                for option in self.snooze_options:
                    ui.button(
                        f"Later ({option})",
                        on_click=lambda option=option: choose(f"snooze_{option}"),
                    )
                if self.dismiss_label:
                    ui.button(
                        self.dismiss_label,
                        on_click=lambda: choose(
                            "never" if self.dismiss_label == "Never" else "dismiss"
                        ),
                    )

        ui.run(
            title=self.title,
            reload=False,
            show=True,
            port=0,
            host="127.0.0.1",
        )
        done.wait(timeout=3600)
        return result["value"]

    def _show_ide_choices_textual(self):
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Button, Checkbox, Label, Select

        dialog = self

        class ChoiceApp(App):
            def compose(self) -> ComposeResult:
                defaults = dialog._default_ide_selection()
                default_install = set(defaults["install"])
                default_never = set(defaults["never"])
                with Vertical():
                    yield Label(dialog.title)
                    yield Label(dialog.message)
                    profile_options = dialog._profile_options()
                    if profile_options:
                        yield Label("Security profile")
                        yield Select(
                            [
                                (
                                    dialog._profile_choice_label(option),
                                    option["profile"] or "",
                                )
                                for option in profile_options
                            ],
                            value=dialog._default_profile_selection() or "",
                            id="profile",
                        )
                    if dialog.ide_choices:
                        with Horizontal():
                            yield Label("Integration")
                            yield Label("Install now")
                            yield Label("Never install")
                    for index, choice in enumerate(dialog.ide_choices):
                        label = choice.get("name", choice["ide"])
                        detail = choice.get("detail")
                        if detail:
                            label += f" — {detail}"
                        with Horizontal():
                            yield Label(label)
                            yield Checkbox(
                                "",
                                value=choice["ide"] in default_install,
                                id=f"install-{index}",
                            )
                            yield Checkbox(
                                "",
                                value=choice["ide"] in default_never,
                                id=f"never-{index}",
                            )
                    with Horizontal():
                        yield Button(dialog.action_label, id="action")
                        for index, option in enumerate(dialog.snooze_options):
                            yield Button(f"Later ({option})", id=f"snooze-{index}")
                        if dialog.dismiss_label:
                            yield Button(
                                dialog.dismiss_label,
                                id=(
                                    "never"
                                    if dialog.dismiss_label == "Never"
                                    else "dismiss"
                                ),
                            )

            def _selection(self):
                install = []
                never = []
                for index, choice in enumerate(dialog.ide_choices):
                    if self.query_one(f"install-{index}", Checkbox).value:
                        install.append(choice["ide"])
                    if self.query_one(f"never-{index}", Checkbox).value:
                        never.append(choice["ide"])
                profile = _PROFILE_NOT_SELECTED
                if dialog._profile_options():
                    selected = self.query_one("#profile", Select).value
                    profile = (
                        selected if isinstance(selected, str) and selected else None
                    )
                return dialog._ide_selection_result("action", install, never, profile)

            def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
                checkbox_id = event.checkbox.id or ""
                if "-" not in checkbox_id:
                    return
                kind, index = checkbox_id.rsplit("-", 1)
                if kind not in {"install", "never"}:
                    return
                other_kind = "never" if kind == "install" else "install"
                other = self.query_one(f"{other_kind}-{index}", Checkbox)
                if event.checkbox.value:
                    other.value = False
                elif not other.value:
                    event.checkbox.value = True

            def on_button_pressed(self, event: Button.Pressed) -> None:
                button_id = event.button.id or "dismiss"
                if button_id == "action":
                    value = self._selection()
                elif button_id.startswith("snooze-"):
                    index = int(button_id.rsplit("-", 1)[1])
                    value = dialog._ide_selection_result(
                        f"snooze_{dialog.snooze_options[index]}",
                        profile=(
                            None if dialog._profile_options() else _PROFILE_NOT_SELECTED
                        ),
                    )
                else:
                    value = (
                        dialog._never_ide_selection()
                        if button_id == "never"
                        else dialog._ide_selection_result(
                            "dismiss",
                            profile=(
                                None
                                if dialog._profile_options()
                                else _PROFILE_NOT_SELECTED
                            ),
                        )
                    )
                self.result = value
                self.exit()

        app = ChoiceApp()
        app.result = self._ide_selection_result("dismiss")
        app.run()
        return app.result

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
        if self.dismiss_label:
            ttk.Button(
                frame, text=self.dismiss_label, command=lambda: choose("dismiss")
            ).grid(row=1, column=3)
        root.protocol("WM_DELETE_WINDOW", lambda: choose("dismiss"))
        root.bind("<Escape>", lambda _event: choose("dismiss"))
        root.lift()
        root.focus_force()
        root.attributes("-topmost", True)
        root.after(50, root.focus_force)
        root.after(150, lambda: root.attributes("-topmost", False))
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
                if self.dismiss_label:
                    ui.button(self.dismiss_label, on_click=lambda: choose("dismiss"))

        ui.run(
            title=self.title,
            reload=False,
            show=True,
            port=0,
            host="127.0.0.1",
        )
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
                        if dialog.dismiss_label:
                            yield Button(
                                dialog.dismiss_label,
                                id=(
                                    "never"
                                    if dialog.dismiss_label == "Never"
                                    else "dismiss"
                                ),
                            )

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
