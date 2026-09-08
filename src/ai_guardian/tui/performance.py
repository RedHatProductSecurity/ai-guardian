"""Performance (Hook Latency) panel for the TUI console."""

from typing import Any, Dict

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Input, Static

from ai_guardian.tui.schema_defaults import ConfigSaveMixin
from ai_guardian.tui.widgets import TimeBasedToggle, sanitize_enabled_value


def _empty_latency_message(report) -> str:
    """Return the TUI guidance for a latency report with no hook rows."""
    if report.paused:
        return (
            "[dim]Latency collection is paused because the daemon is paused. "
            "Resume the daemon, then trigger a new hook.[/dim]"
        )
    return (
        "[dim]No latency data. Enable in Settings above, then hook "
        "calls will record timing.[/dim]"
    )


class PerformanceContent(ConfigSaveMixin, Container):
    """Content widget for Performance (Hook Latency) panel."""

    CONFIG_SECTION = "latency_tracking"

    CSS = """
    PerformanceContent {
        height: 100%;
    }

    #perf-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    .section {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    .section-title {
        margin: 0 0 1 0;
        font-weight: bold;
    }

    .setting-row {
        height: auto;
        margin: 0 0 1 0;
    }

    .setting-row Static {
        width: 20;
        padding: 1;
    }

    .setting-row Input {
        width: 15;
    }

    #perf-range-buttons {
        margin: 1 0;
        height: auto;
    }

    #perf-range-buttons Button {
        margin: 0 1 0 0;
    }

    #perf-config-buttons {
        margin: 1 0;
        height: auto;
    }

    #perf-config-buttons Button {
        margin: 0 1 0 0;
    }

    Button:focus {
        border-left: heavy $accent;
        text-style: bold;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._retention_days = self._get_retention_days()
        self._since_days = min(30, self._retention_days)

    @staticmethod
    def _get_retention_days() -> int:
        try:
            from ai_guardian.violations.logger import ViolationLogger

            vl = ViolationLogger()
            return vl.config.get("retention_days", 30)
        except Exception:
            return 30

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Performance — Hook Latency[/bold]",
            id="perf-header",
        )

        with VerticalScroll():
            # Settings section
            with Container(classes="section"):
                yield Static("[bold]Settings[/bold]", classes="section-title")

                with Horizontal(classes="setting-row"):
                    yield Static("Enabled")
                    yield TimeBasedToggle(
                        title="Latency Tracking",
                        config_key="latency_tracking",
                        current_value=False,
                        id="perf_enabled_toggle",
                    )

                with Horizontal(classes="setting-row"):
                    yield Static("Max Entries")
                    yield Input(
                        placeholder="5000",
                        id="perf-max-entries",
                        type="integer",
                    )

                with Horizontal(classes="setting-row"):
                    yield Static("Retention Days")
                    yield Input(
                        placeholder="30",
                        id="perf-retention-days",
                        type="integer",
                    )

                with Horizontal(id="perf-config-buttons"):
                    yield Button(
                        "Save Settings", id="perf-save-settings", variant="primary"
                    )
                    yield Button("Clear Log", id="perf-clear-log", variant="warning")

            # Range buttons
            with Horizontal(id="perf-range-buttons"):
                yield Button("7 days", id="perf-7d", variant="default")
                yield Button(
                    "30 days",
                    id="perf-30d",
                    variant="primary" if self._retention_days >= 30 else "default",
                    disabled=self._retention_days < 30,
                )
                yield Button(
                    f"All ({self._retention_days}d)", id="perf-all", variant="default"
                )
                yield Button("Refresh", id="perf-refresh", variant="success")

            with Container(classes="section"):
                yield Static("[bold]Invocations[/bold]", classes="section-title")
                yield Static("Loading...", id="perf-invocations")

            with Container(classes="section"):
                yield Static(
                    "[bold]Hook Latency Overview[/bold]", classes="section-title"
                )
                yield Static("", id="perf-hook-table")

            with Container(classes="section"):
                yield Static(
                    "[bold]Per-Check Breakdown[/bold]", classes="section-title"
                )
                yield Static("", id="perf-check-table")

    def on_mount(self) -> None:
        self._load_config_ui()
        self._load_data()

    def refresh_content(self) -> None:
        self._load_config_ui()
        self._load_data()

    def _load_config_ui(self):
        try:
            from ai_guardian.reporting.latency import LatencyLogger

            cfg = LatencyLogger().config
        except Exception:
            cfg = {"enabled": False, "max_entries": 5000, "retention_days": 30}

        try:
            toggle = self.query_one("#perf_enabled_toggle", TimeBasedToggle)
            toggle.load_value(cfg.get("enabled", False))
        except Exception:
            pass  # intentionally silent — optional dependency

        try:
            self.query_one("#perf-max-entries", Input).value = str(
                cfg.get("max_entries", 5000)
            )
        except Exception:
            pass  # intentionally silent — optional dependency
        try:
            self.query_one("#perf-retention-days", Input).value = str(
                cfg.get("retention_days", 30)
            )
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "perf-7d":
            self._since_days = 7
        elif btn_id == "perf-30d":
            self._since_days = 30
        elif btn_id == "perf-all":
            self._since_days = self._retention_days
        elif btn_id == "perf-refresh":
            self._load_data()
            return
        elif btn_id == "perf-save-settings":
            self._save_settings()
            return
        elif btn_id == "perf-clear-log":
            self._clear_log()
            return
        else:
            return

        btn_for_days = {"perf-7d": 7, "perf-30d": 30, "perf-all": self._retention_days}
        for bid, d in btn_for_days.items():
            try:
                btn = self.query_one(f"#{bid}", Button)
                btn.variant = "primary" if d == self._since_days else "default"
            except Exception:
                pass

        self._load_data()

    def _save_settings(self):
        updates: Dict[str, Any] = {}

        try:
            toggle = self.query_one("#perf_enabled_toggle", TimeBasedToggle)
            updates["enabled"] = sanitize_enabled_value(toggle.get_value())
        except Exception:
            pass

        try:
            val = self.query_one("#perf-max-entries", Input).value
            if val:
                updates["max_entries"] = int(val)
        except (ValueError, Exception):
            pass

        try:
            val = self.query_one("#perf-retention-days", Input).value
            if val:
                updates["retention_days"] = int(val)
        except (ValueError, Exception):
            pass

        if self._save_config(updates):
            self.app.notify("Settings saved", severity="information")
        self._load_data()

    def _clear_log(self):
        try:
            from ai_guardian.reporting.latency import LatencyLogger

            LatencyLogger().clear_log()
            self.app.notify("Latency log cleared", severity="warning")
            self._load_data()
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")

    def _save_config(self, updates: Dict[str, Any]) -> bool:
        return self._save_config_updates(updates)

    def _load_data(self):
        try:
            from ai_guardian.reporting.latency import LatencyComputer

            computer = LatencyComputer(since_days=self._since_days)
            report = computer.compute()
        except Exception as e:
            self.query_one("#perf-invocations", Static).update(f"[red]Error: {e}[/red]")
            return

        self.query_one("#perf-invocations", Static).update(
            f"[bold]{report.invocation_count:,}[/bold] hook invocations"
        )

        if not report.hook_stats:
            self.query_one("#perf-hook-table", Static).update(
                _empty_latency_message(report)
            )
            self.query_one("#perf-check-table", Static).update("")
            return

        self.query_one("#perf-hook-table", Static).update(
            self._format_hook_table(report.hook_stats)
        )
        self.query_one("#perf-check-table", Static).update(
            self._format_check_table(report.check_stats)
        )

    @staticmethod
    def _format_hook_table(stats):
        header = (
            f"  {'Hook Event':<22s} {'Avg':>8s} {'StdDev':>8s} "
            f"{'P95':>8s} {'Min':>8s} {'Max':>8s} {'Count':>7s}"
        )
        lines = [header, "  " + "-" * 73]
        for s in stats:
            p95 = s.get("p95", 0)
            color = "[red]" if p95 > 100 else "[yellow]" if p95 > 50 else ""
            end_color = "[/]" if color else ""
            lines.append(
                f"  {s['hook_event']:<22s} {s['avg']:>8.1f} {s['stddev']:>8.1f} "
                f"{color}{p95:>8.1f}{end_color} {s['min']:>8.1f} {s['max']:>8.1f} "
                f"{s['count']:>7,}"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_check_table(stats):
        if not stats:
            return "[dim]No per-check data[/dim]"
        header = (
            f"  {'Check Type':<22s} {'Avg':>8s} {'StdDev':>8s} "
            f"{'P95':>8s} {'Min':>8s} {'Max':>8s} {'Count':>7s} {'Hook(s)'}"
        )
        lines = [header, "  " + "-" * 80]
        for s in stats:
            p95 = s.get("p95", 0)
            color = "[red]" if p95 > 100 else "[yellow]" if p95 > 50 else ""
            end_color = "[/]" if color else ""
            lines.append(
                f"  {s['check_name']:<22s} {s['avg']:>8.1f} {s['stddev']:>8.1f} "
                f"{color}{p95:>8.1f}{end_color} {s['min']:>8.1f} {s['max']:>8.1f} "
                f"{s['count']:>7,} {s.get('hooks', '')}"
            )
        return "\n".join(lines)
