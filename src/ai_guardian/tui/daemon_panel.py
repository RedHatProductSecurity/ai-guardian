"""
Daemon panel for the AI Guardian Console.

Shows daemon status, configuration, and provides controls for
starting/stopping the daemon and changing the mode.
"""

import json
import logging

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Select, Button, Label, Input
from textual.reactive import reactive

from ai_guardian.config.utils import get_config_dir
from ai_guardian.tui.schema_defaults import SchemaDefaults

logger = logging.getLogger(__name__)


class DaemonPanelContent(Static):
    """Daemon configuration and status panel."""

    daemon_status = reactive("checking...")

    def compose(self) -> ComposeResult:
        sd = SchemaDefaults.get()
        config = self._load_daemon_config()
        idle_timeout = config.get("idle_timeout_minutes", 0)
        client_timeout = config.get("client_timeout_seconds", 2.0)
        tray_config = config.get("tray", {})
        tray_enabled = tray_config.get("enabled", True)
        tray_auto_install = tray_config.get("auto_install", True)
        terminal_app = tray_config.get("terminal_app", "")

        yield Static("[bold]Daemon Configuration[/bold]\n", classes="section-header")

        with Vertical(classes="form-group"):
            yield Static(
                "[dim]Daemon auto-starts on any command and falls back to direct if unavailable[/dim]",
                classes="help-text",
            )

        with Vertical(classes="form-group"):
            yield Static("Idle Timeout (minutes)")
            yield Input(
                str(idle_timeout),
                id="daemon-idle-timeout",
                type="integer",
            )
            default_idle = sd.get_default("daemon.idle_timeout_minutes")
            yield Static(
                f"[dim]0 = never auto-stop (default: {default_idle})[/dim]",
                classes="help-text",
            )

        with Vertical(classes="form-group"):
            yield Static("Client Timeout (seconds)")
            yield Input(
                str(client_timeout),
                id="daemon-client-timeout",
                type="number",
            )
            default_client = sd.get_default("daemon.client_timeout_seconds")
            yield Static(
                f"[dim]Max wait for daemon response before fallback (default: {default_client})[/dim]",
                classes="help-text",
            )

        with Vertical(classes="form-group"):
            yield Static("System Tray")
            yield Select(
                [("Enabled", True), ("Disabled", False)],
                value=tray_enabled,
                id="daemon-tray-enabled",
                allow_blank=False,
            )

        with Vertical(classes="form-group"):
            yield Static("Auto-Install Tray")
            yield Select(
                [("Enabled", True), ("Disabled", False)],
                value=tray_auto_install,
                id="daemon-tray-auto-install",
                allow_blank=False,
            )
            yield Static(
                "[dim]Auto-install shortcut and autostart on first CLI run (default: Enabled)[/dim]",
                classes="help-text",
            )

        with Vertical(classes="form-group"):
            yield Static("Terminal App")
            yield Input(
                terminal_app or "",
                id="daemon-terminal-app",
                placeholder="auto-detect",
            )
            yield Static(
                "[dim]macOS: app name (iTerm). Linux: binary (alacritty). "
                "Windows: exe (wt). Empty = auto-detect[/dim]",
                classes="help-text",
            )

        yield Static("")

        with Horizontal(classes="button-group"):
            yield Button("Save", id="daemon-save", variant="primary")
            yield Button("Start", id="daemon-start-btn", variant="success")
            yield Button("Stop", id="daemon-stop-btn", variant="error")
            yield Button("Status", id="daemon-status-btn", variant="default")

        yield Static("")
        yield Static("[bold]Daemon Status[/bold]", classes="section-header")
        yield Label(self.daemon_status, id="daemon-status-label")

    def on_mount(self) -> None:
        self._refresh_status()

    def watch_daemon_status(self, value: str) -> None:
        try:
            self.query_one("#daemon-status-label", Label).update(value)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "daemon-save":
            self._save_config()
        elif event.button.id == "daemon-start-btn":
            self._start_daemon()
        elif event.button.id == "daemon-stop-btn":
            self._stop_daemon()
        elif event.button.id == "daemon-status-btn":
            self._refresh_status()

    def _start_daemon(self):
        try:
            from ai_guardian.daemon.client import (
                is_daemon_running,
                start_daemon_background,
            )

            if is_daemon_running():
                self.app.notify("Daemon is already running", severity="warning")
                return

            if start_daemon_background():
                self.app.notify("Daemon started", severity="information")
            else:
                self.app.notify("Failed to start daemon", severity="error")
        except Exception as e:
            self.app.notify(f"Start failed: {e}", severity="error")
        self._refresh_status()

    def _stop_daemon(self):
        try:
            from ai_guardian.daemon.client import is_daemon_running, send_shutdown

            if not is_daemon_running():
                self.app.notify("Daemon is not running", severity="information")
            elif send_shutdown():
                self.app.notify("Daemon stopped", severity="information")
            else:
                self.app.notify("Failed to stop daemon", severity="error")
        except Exception as e:
            self.app.notify(f"Stop failed: {e}", severity="error")
        self._refresh_status()

    def _save_config(self):
        try:
            idle_input = self.query_one("#daemon-idle-timeout", Input)
            client_input = self.query_one("#daemon-client-timeout", Input)
            tray_select = self.query_one("#daemon-tray-enabled", Select)
            auto_install_select = self.query_one("#daemon-tray-auto-install", Select)
            terminal_app_input = self.query_one("#daemon-terminal-app", Input)

            config_path = get_config_dir() / "ai-guardian.json"
            if config_path.exists():
                full_config = json.loads(config_path.read_text(encoding="utf-8"))
            else:
                full_config = {}

            daemon_config = full_config.get("daemon", {})
            daemon_config["idle_timeout_minutes"] = int(idle_input.value or 0)
            daemon_config["client_timeout_seconds"] = float(client_input.value or 2.0)
            tray_cfg = {
                "enabled": tray_select.value,
                "auto_install": auto_install_select.value,
            }
            term_val = (terminal_app_input.value or "").strip()
            if term_val:
                tray_cfg["terminal_app"] = term_val
            daemon_config["tray"] = tray_cfg
            daemon_config.pop("mode", None)
            full_config["daemon"] = daemon_config

            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(full_config, indent=2) + "\n", encoding="utf-8"
            )

            try:
                from ai_guardian.daemon.client import send_reload_config

                send_reload_config()
            except Exception:
                pass  # intentionally silent — optional dependency

            self.app.notify("Daemon config saved", severity="information")
        except Exception as e:
            self.app.notify(f"Save failed: {e}", severity="error")

    def _refresh_status(self):
        try:
            from ai_guardian.daemon.client import is_daemon_running, send_status_request
            from ai_guardian.daemon import get_socket_path, get_pid_path

            if not is_daemon_running():
                self.daemon_status = "[red]Not running[/red]"
                return

            stats = send_status_request()
            if stats:
                uptime = stats.get("uptime_seconds", 0)
                hours = int(uptime // 3600)
                minutes = int((uptime % 3600) // 60)
                uptime_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"
                paused = ""
                if stats.get("paused"):
                    remaining = stats.get("pause_remaining_seconds", 0)
                    if remaining > 0:
                        mins = int(remaining // 60)
                        secs = int(remaining % 60)
                        paused = f" [yellow](PAUSED — {mins}m {secs}s left)[/yellow]"
                    else:
                        paused = " [yellow](PAUSED — indefinite)[/yellow]"

                pid_path = get_pid_path()
                pid = "?"
                try:
                    pid_info = json.loads(pid_path.read_text())
                    pid = pid_info.get("pid", "?")
                except Exception:
                    pass  # intentionally silent — best-effort operation

                lines = [
                    f"[green]Running[/green] (pid {pid}){paused}",
                    f"Uptime: {uptime_str}",
                    f"Requests: {stats.get('request_count', 0)}",
                    f"Blocked: {stats.get('blocked_count', 0)}",
                    f"Warnings: {stats.get('warning_count', 0)}",
                    f"Log-only: {stats.get('log_only_count', 0)}",
                    f"Violations: {stats.get('violation_count', 0)}",
                    f"Socket: {get_socket_path()}",
                ]
                self.daemon_status = "\n".join(lines)
            else:
                self.daemon_status = (
                    "[yellow]Running but could not fetch stats[/yellow]"
                )
        except Exception as e:
            self.daemon_status = f"[red]Error: {e}[/red]"

    @staticmethod
    def _load_daemon_config():
        try:
            config_path = get_config_dir() / "ai-guardian.json"
            if config_path.exists():
                config = json.loads(config_path.read_text(encoding="utf-8"))
                return config.get("daemon", {})
        except Exception:
            pass  # intentionally silent — best-effort operation
        return {}
