"""TUI settings for the compliance audit trail."""

from typing import Any, Dict

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from ai_guardian.tui.schema_defaults import (
    ConfigSaveMixin,
    SchemaDefaultsMixin,
    default_indicator,
    default_placeholder,
)
from ai_guardian.tui.widgets import TimeBasedToggle


class AuditLoggingContent(ConfigSaveMixin, SchemaDefaultsMixin, Container):
    """Content widget for compliance audit logging settings."""

    CONFIG_SECTION = "audit_logging"
    SCHEMA_SECTION = "audit_logging"
    SCHEMA_FIELDS = [
        ("audit-max-entries", "max_entries", "input"),
        ("audit-retention-days", "retention_days", "input"),
        ("audit-export-format", "export_format", "select"),
        ("audit-output-file", "output_file", "input"),
    ]
    CONTEXT_FIELDS = (
        ("audit-context-user-id", "user_id", "Include user ID"),
        ("audit-context-session-id", "session_id", "Include session ID"),
        ("audit-context-timestamp", "timestamp", "Include timestamp"),
        (
            "audit-context-tool-parameters",
            "tool_parameters",
            "Include tool parameters",
        ),
        (
            "audit-context-decision-reason",
            "decision_reason",
            "Include decision reason",
        ),
        ("audit-context-hook-type", "hook_type", "Include hook type"),
    )

    CSS = """
    AuditLoggingContent {
        height: 100%;
    }

    #audit-header {
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
        margin: 0.5 0;
        height: auto;
    }

    .setting-row Label {
        margin: 0 1 0 0;
        width: 24;
    }

    .setting-row Input,
    .setting-row Select {
        width: 28;
    }

    .checkbox-row {
        margin: 0.25 0;
        height: auto;
    }

    #audit-warning {
        margin: 1 0;
        padding: 1;
        background: $surface;
    }

    Input:focus,
    Select:focus,
    Button:focus,
    Checkbox:focus {
        border-left: heavy $accent;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Compliance Audit Logging[/bold]", id="audit-header")

        with VerticalScroll():
            yield TimeBasedToggle(
                title="Compliance Audit Logging",
                config_key="audit_logging_enabled",
                current_value=False,
                help_text=(
                    "Record sanitized final hook decisions in a separate audit.jsonl file"
                ),
                id="audit_logging_enabled_toggle",
            )
            yield Static(
                "Raw prompts, tool output, and hook payloads are not persisted. "
                "Keep masking enabled when audit records contain user or tool metadata.",
                id="audit-warning",
            )

            with Container(classes="section"):
                yield Static("[bold]Recording[/bold]", classes="section-title")
                yield Checkbox(
                    "Log allowed tool calls as well as non-allow decisions",
                    id="audit-log-all",
                    value=True,
                )
                yield Checkbox(
                    "Mask secrets and PII before writing records",
                    id="audit-mask",
                    value=True,
                )

            with Container(classes="section"):
                yield Static("[bold]Recorded Context[/bold]", classes="section-title")
                yield Static(
                    "Choose which normalized metadata fields are included in each audit record."
                )
                for checkbox_id, _key, label in self.CONTEXT_FIELDS:
                    yield Checkbox(label, id=checkbox_id, value=True)

            with Container(classes="section"):
                yield Static("[bold]Compliance Markers[/bold]", classes="section-title")
                yield Checkbox("SOC 2", id="audit-soc2", value=False)
                yield Checkbox("GDPR processing activity", id="audit-gdpr", value=False)
                yield Checkbox("HIPAA access log", id="audit-hipaa", value=False)

            with Container(classes="section"):
                yield Static(
                    "[bold]Retention and Export[/bold]", classes="section-title"
                )
                with Horizontal(classes="setting-row"):
                    yield Label("Max Entries:")
                    yield Input(
                        value="10000",
                        placeholder=default_placeholder("audit_logging.max_entries"),
                        id="audit-max-entries",
                    )
                    yield Static(default_indicator("audit_logging.max_entries"))
                with Horizontal(classes="setting-row"):
                    yield Label("Retention Days:")
                    yield Input(
                        value="90",
                        placeholder=default_placeholder("audit_logging.retention_days"),
                        id="audit-retention-days",
                    )
                    yield Static(default_indicator("audit_logging.retention_days"))
                with Horizontal(classes="setting-row"):
                    yield Label("Export Format:")
                    yield Select(
                        [("JSON", "json"), ("CSV", "csv")],
                        value="json",
                        id="audit-export-format",
                    )
                    yield Static(default_indicator("audit_logging.export_format"))
                with Horizontal(classes="setting-row"):
                    yield Label("Output File:")
                    yield Input(
                        placeholder="Defaults to the state directory audit.jsonl",
                        id="audit-output-file",
                    )
                    yield Static("[dim](default: state directory audit.jsonl)[/dim]")
                with Horizontal(classes="setting-row"):
                    yield Button("Export Now", id="audit-export-btn", variant="primary")
                    yield Static("", id="audit-export-status")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._loading = False

    def on_mount(self) -> None:
        self.load_config()

    def refresh_content(self) -> None:
        self.load_config()

    def action_refresh(self) -> None:
        self.load_config()
        self.app.notify("Audit logging configuration refreshed", severity="information")

    def load_config(self) -> None:
        self._loading = True
        try:
            config = self._load_full_config()
            audit_config = config.get("audit_logging", {})
            if not isinstance(audit_config, dict):
                audit_config = {}
            compliance = audit_config.get("compliance_mode", {})
            if not isinstance(compliance, dict):
                compliance = {}
            include_context = audit_config.get("include_context", {})
            if not isinstance(include_context, dict):
                include_context = {}

            self.query_one("#audit_logging_enabled_toggle", TimeBasedToggle).load_value(
                audit_config.get("enabled", False)
            )
            self.query_one("#audit-log-all", Checkbox).value = audit_config.get(
                "log_all_tool_calls", True
            )
            self.query_one("#audit-mask", Checkbox).value = audit_config.get(
                "sensitive_data_masking", True
            )
            self.query_one("#audit-soc2", Checkbox).value = compliance.get(
                "soc2", False
            )
            self.query_one("#audit-gdpr", Checkbox).value = compliance.get(
                "gdpr", False
            )
            self.query_one("#audit-hipaa", Checkbox).value = compliance.get(
                "hipaa", False
            )
            for checkbox_id, key, _label in self.CONTEXT_FIELDS:
                self.query_one(f"#{checkbox_id}", Checkbox).value = include_context.get(
                    key, True
                )
            self.query_one("#audit-max-entries", Input).value = str(
                audit_config.get("max_entries", 10000)
            )
            self.query_one("#audit-retention-days", Input).value = str(
                audit_config.get("retention_days", 90)
            )
            export_format = audit_config.get("export_format", "json")
            if export_format not in ("json", "csv"):
                export_format = "json"
            self.query_one("#audit-export-format", Select).value = export_format
            self.query_one("#audit-output-file", Input).value = str(
                audit_config.get("output_file") or ""
            )
            self._apply_default_indicators(audit_config)
        except Exception as error:
            self.app.notify(f"Error loading audit config: {error}", severity="error")
        finally:
            self._loading = False

    def _save_config(self, updates: Dict[str, Any]) -> bool:
        return self._save_config_updates(updates)

    def _save_compliance_flag(self, key: str, value: bool) -> bool:
        config = self._load_full_config()
        section = config.setdefault("audit_logging", {})
        if not isinstance(section, dict):
            section = {}
            config["audit_logging"] = section
        compliance = section.setdefault("compliance_mode", {})
        if not isinstance(compliance, dict):
            compliance = {}
            section["compliance_mode"] = compliance
        compliance[key] = value
        return self._write_full_config(config)

    def _save_context_flag(self, key: str, value: bool) -> bool:
        config = self._load_full_config()
        section = config.setdefault("audit_logging", {})
        if not isinstance(section, dict):
            section = {}
            config["audit_logging"] = section
        include_context = section.setdefault("include_context", {})
        if not isinstance(include_context, dict):
            include_context = {}
            section["include_context"] = include_context
        include_context[key] = value
        return self._write_full_config(config)

    def _export_audit(self) -> None:
        """Export the local audit trail without modifying the JSONL source."""
        try:
            from ai_guardian.violations.audit import AuditLogger

            format_value = self.query_one("#audit-export-format", Select).value
            export_format = (
                str(format_value) if format_value in ("json", "csv") else "json"
            )
            config = self._load_full_config()
            audit_config = config.get("audit_logging", {})
            if not isinstance(audit_config, dict):
                audit_config = {}
            audit_logger = AuditLogger(config=audit_config)
            export_path = audit_logger.get_export_path(export_format)
            if not audit_logger.export(export_path, export_format=export_format):
                raise OSError("the audit trail could not be exported")
            self.query_one("#audit-export-status", Static).update(
                f"[green]Exported to {export_path}[/green]"
            )
            self.app.notify(
                f"Audit trail exported to {export_path}", severity="information"
            )
        except (OSError, TypeError, ValueError, ImportError) as error:
            self.query_one("#audit-export-status", Static).update(
                f"[red]Export failed: {error}[/red]"
            )
            self.app.notify(f"Audit export failed: {error}", severity="error")

    def on_button_pressed(self, event) -> None:
        if self._loading:
            return
        bid = event.button.id or ""
        if "audit_logging_enabled" in bid:
            toggle = self.query_one("#audit_logging_enabled_toggle", TimeBasedToggle)
            if toggle.current_mode != "temp_disabled":
                self._save_config({"enabled": toggle.get_value()})
        elif bid == "audit-export-btn":
            self._export_audit()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if self._loading:
            return
        checkbox_id = event.checkbox.id or ""
        if checkbox_id == "audit-log-all":
            self._save_config({"log_all_tool_calls": event.value})
        elif checkbox_id == "audit-mask":
            self._save_config({"sensitive_data_masking": event.value})
        else:
            context_key = {
                checkbox_id_value: key
                for checkbox_id_value, key, _label in self.CONTEXT_FIELDS
            }.get(checkbox_id)
            if context_key:
                self._save_context_flag(context_key, event.value)
                return
            compliance_key = {
                "audit-soc2": "soc2",
                "audit-gdpr": "gdpr",
                "audit-hipaa": "hipaa",
            }.get(checkbox_id)
            if compliance_key:
                self._save_compliance_flag(compliance_key, event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._loading:
            return
        input_id = event.input.id or ""
        if input_id in ("audit-max-entries", "audit-retention-days"):
            try:
                value = int(event.input.value.strip())
                if value < 1:
                    raise ValueError
            except ValueError:
                self.app.notify("Value must be a positive integer", severity="error")
                return
            key = "max_entries" if input_id == "audit-max-entries" else "retention_days"
            self._save_config({key: value})
        elif input_id == "audit-output-file":
            self._save_config({"output_file": event.input.value.strip() or None})

    def on_select_changed(self, event: Select.Changed) -> None:
        if self._loading or event.select.id != "audit-export-format":
            return
        if event.value in ("json", "csv"):
            self._save_config({"export_format": event.value})
