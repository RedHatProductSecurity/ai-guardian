"""SDK Settings panel — scanning and secret redaction toggles."""

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Checkbox, Static

from ai_guardian.tui.schema_defaults import ConfigSaveMixin


class SDKSettingsContent(ConfigSaveMixin, Container):
    """Content widget for SDK Settings panel."""

    CONFIG_SECTION = "sdk"

    DEFAULT_CSS = """
    SDKSettingsContent {
        height: 100%;
    }
    #sdk-settings-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }
    #sdk-settings-status {
        margin: 1 2;
        padding: 0 1;
    }
    .sdk-toggle {
        margin: 1 2;
    }
    #sdk-redaction-note {
        margin: 0 2;
        padding: 1;
        color: $text-muted;
    }
    #sdk-settings-info {
        margin: 2 2;
        padding: 1;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]SDK Settings[/bold]", id="sdk-settings-header")

        with VerticalScroll():
            yield Checkbox(
                "Scanning enabled",
                value=True,
                id="sdk-scanning-toggle",
                classes="sdk-toggle",
            )
            yield Checkbox(
                "Secret redaction (SDK)",
                value=False,
                id="sdk-redaction-toggle",
                classes="sdk-toggle",
            )
            yield Static(
                "[dim italic]SDK defaults secret redaction to OFF — "
                "redacting content in the agentic loop breaks code. "
                "Traces are always sanitized regardless.[/dim italic]",
                id="sdk-redaction-note",
            )
            yield Static("", id="sdk-settings-status")
            yield Static(
                "[bold]About SDK Settings[/bold]\n\n"
                "  [bold]Scanning[/bold] — Global enable/disable for all SDK "
                "scanning. When off, SDK skips all input/output scanning.\n\n"
                "  [bold]Secret Redaction[/bold] — Redact detected secrets in "
                "live SDK content. Off by default because redaction breaks "
                "code in the agentic loop. Traces are always sanitized "
                "independently of this flag.",
                id="sdk-settings-info",
            )

    def on_mount(self) -> None:
        pass

    def refresh_content(self) -> None:
        self._load_config()

    def _load_config(self) -> None:
        config = self._load_full_config()
        sdk = config.get("sdk", {})
        scanning = sdk.get("scanning", True)
        redaction = sdk.get("secret_redaction", {})
        redaction_enabled = (
            redaction.get("enabled", False) if isinstance(redaction, dict) else False
        )

        try:
            self.query_one("#sdk-scanning-toggle", Checkbox).value = bool(scanning)
        except Exception:
            pass
        try:
            self.query_one("#sdk-redaction-toggle", Checkbox).value = bool(
                redaction_enabled
            )
        except Exception:
            pass

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        config = self._load_full_config()
        sdk = config.setdefault("sdk", {})

        if event.checkbox.id == "sdk-scanning-toggle":
            sdk["scanning"] = event.value
            if self._write_full_config(config):
                state = "enabled" if event.value else "disabled"
                self._set_status(f"SDK scanning {state}", "success")
                self.app.notify(f"SDK scanning {state}", severity="information")
            else:
                self._set_status("Save failed", "error")
        elif event.checkbox.id == "sdk-redaction-toggle":
            sr = sdk.setdefault("secret_redaction", {})
            sr["enabled"] = event.value
            if self._write_full_config(config):
                state = "enabled" if event.value else "disabled"
                self._set_status(f"SDK secret redaction {state}", "success")
                self.app.notify(f"SDK secret redaction {state}", severity="information")
            else:
                self._set_status("Save failed", "error")

    def _set_status(self, message: str, level: str) -> None:
        try:
            status = self.query_one("#sdk-settings-status", Static)
            if level == "error":
                status.update(f"[red]{message}[/red]")
            else:
                status.update(f"[green]{message}[/green]")
        except Exception:
            pass

    def action_refresh(self) -> None:
        self._load_config()
        self.app.notify("SDK settings refreshed", severity="information")
