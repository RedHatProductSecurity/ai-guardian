"""Unified tracing settings panel for the TUI console."""

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Checkbox, Input, Static

from ai_guardian.config.loaders import resolve_tracing_config
from ai_guardian.tui.schema_defaults import ConfigSaveMixin


class TracingSettingsContent(ConfigSaveMixin, Container):
    """Edit top-level SDK and hook tracing settings."""

    DEFAULT_CSS = """
    TracingSettingsContent { height: 100%; }
    #tracing-settings-header { margin: 1 0; padding: 1; background: $primary; }
    .tracing-setting { margin: 1 2; }
    #tracing-settings-status { margin: 1 2; }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Tracing Settings[/bold]", id="tracing-settings-header")
        with VerticalScroll():
            yield Checkbox(
                "Record SDK and hook traces",
                value=True,
                id="tracing-enabled",
                classes="tracing-setting",
            )
            yield Input(
                value="5",
                placeholder="Auto-refresh interval (seconds)",
                id="tracing-refresh-interval",
                classes="tracing-setting",
                type="integer",
            )
            yield Input(
                value="90",
                placeholder="Remote trace cache retention (days)",
                id="tracing-retention-days",
                classes="tracing-setting",
                type="integer",
            )
            yield Static(
                "Disabling recording does not affect security scanning, OTEL "
                "export, or existing traces.",
                classes="tracing-setting",
            )
            yield Static("", id="tracing-settings-status")

    def refresh_content(self) -> None:
        config = self._load_full_config()
        tracing = resolve_tracing_config(config)
        self.query_one("#tracing-enabled", Checkbox).value = bool(tracing["enabled"])
        self.query_one("#tracing-refresh-interval", Input).value = str(
            tracing["auto_refresh_interval_seconds"]
        )
        self.query_one("#tracing-retention-days", Input).value = str(
            tracing["trace_cache_retention_days"]
        )

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "tracing-enabled":
            self._save_value("enabled", event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        settings = {
            "tracing-refresh-interval": ("auto_refresh_interval_seconds", 1, 300),
            "tracing-retention-days": ("trace_cache_retention_days", 1, 3650),
        }
        setting = settings.get(event.input.id)
        if not setting:
            return
        key, minimum, maximum = setting
        try:
            value = int(event.value)
        except ValueError:
            self._set_status("Enter a whole number", error=True)
            return
        if not minimum <= value <= maximum:
            self._set_status(
                f"Value must be between {minimum} and {maximum}", error=True
            )
            return
        self._save_value(key, value)

    def _save_value(self, key, value) -> None:
        config = self._load_full_config()
        config.setdefault("tracing", {})[key] = value
        if self._write_full_config(config):
            self._set_status("Tracing settings saved")
        else:
            self._set_status("Save failed", error=True)

    def _set_status(self, message: str, error: bool = False) -> None:
        color = "red" if error else "green"
        self.query_one("#tracing-settings-status", Static).update(
            f"[{color}]{message}[/{color}]"
        )
