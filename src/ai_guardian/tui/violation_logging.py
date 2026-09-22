#!/usr/bin/env python3
"""
Violation Logging Tab Content

View and configure violation logging settings.
Controls what gets logged, retention, and log types.
"""

import json
from typing import Dict, Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static, Button, Input, Label, Checkbox

from ai_guardian.tui.schema_defaults import (
    ConfigSaveMixin,
    SchemaDefaultsMixin,
    default_indicator,
    default_placeholder,
)
from ai_guardian.tui.widgets import TimeBasedToggle

ALL_LOG_TYPES = [
    ("tool_permission", "Tool Permission — blocked tool/skill invocations"),
    ("directory_blocking", "Directory Blocking — protected directory access"),
    ("secret_detected", "Secret Detected — API keys, tokens, credentials"),
    ("secret_redaction", "Secret Redaction — redacted secrets in output"),
    ("prompt_injection", "Prompt Injection — injection/obfuscation attacks"),
    ("jailbreak_detected", "Jailbreak Detected — jailbreak and role-play attempts"),
    ("ssrf_blocked", "SSRF Blocked — requests to private IPs/metadata"),
    ("config_file_exfil", "Config File Exfil — config exfiltration attempts"),
    ("pii_detected", "PII Detected — personal identifiable information"),
    ("secret_in_transcript", "Secret in Transcript — secrets from ! shell commands"),
    ("pii_in_transcript", "PII in Transcript — PII from ! shell commands"),
    (
        "prompt_injection_in_transcript",
        "Injection in Transcript — prompt injection from ! shell commands",
    ),
    ("annotation_suppressed", "Annotation Suppressed — inline suppression applied"),
    ("image_secret_detected", "Image Secret — secrets found in images via OCR"),
    ("image_pii_detected", "Image PII — PII found in images via OCR"),
]


class ViolationLoggingContent(ConfigSaveMixin, SchemaDefaultsMixin, Container):
    """Content widget for Violation Logging tab."""

    CONFIG_SECTION = "violation_logging"
    SCHEMA_SECTION = "violation_logging"
    SCHEMA_FIELDS = [
        ("vlog-max-entries", "max_entries", "input"),
        ("vlog-retention-days", "retention_days", "input"),
    ]

    CSS = """
    ViolationLoggingContent {
        height: 100%;
    }

    #vlog-header {
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
        width: 20;
    }

    .setting-row Input {
        width: 20;
    }

    .log-type-row {
        margin: 0.25 0;
        height: auto;
    }

    .log-type-row Checkbox {
        margin: 0 1 0 0;
    }

    #log-stats {
        margin: 1 0;
        padding: 1;
        background: $surface;
        border: solid $primary;
        min-height: 4;
    }

    Input:focus {
        border-left: heavy $accent;
        text-style: bold;
    }

    Button:focus {
        border-left: heavy $accent;
        text-style: bold;
    }

    Checkbox:focus {
        border-left: heavy $accent;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Violation Logging Settings[/bold]", id="vlog-header")

        with VerticalScroll():
            yield TimeBasedToggle(
                title="Violation Logging",
                config_key="violation_logging_enabled",
                current_value=True,
                help_text="Log blocked operations to JSONL file for audit and review",
                id="violation_logging_enabled_toggle",
            )

            with Container(classes="section"):
                yield Static("[bold]Retention Settings[/bold]", classes="section-title")

                with Horizontal(classes="setting-row"):
                    yield Label("Max Entries:")
                    yield Input(
                        value="1000",
                        placeholder=default_placeholder(
                            "violation_logging.max_entries"
                        ),
                        id="vlog-max-entries",
                    )
                    yield Static(
                        f"[dim]Maximum log entries to retain (press Enter to save)[/dim] "
                        f"{default_indicator('violation_logging.max_entries')}"
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("Retention Days:")
                    yield Input(
                        value="30",
                        placeholder=default_placeholder(
                            "violation_logging.retention_days"
                        ),
                        id="vlog-retention-days",
                    )
                    yield Static(
                        f"[dim]Days to keep log entries (press Enter to save)[/dim] "
                        f"{default_indicator('violation_logging.retention_days')}"
                    )

            with Container(classes="section"):
                yield Static(
                    "[bold]Violation Types to Log[/bold]", classes="section-title"
                )
                yield Static(
                    "[dim]Uncheck types to stop logging specific violation categories. "
                    "Empty selection logs all types.[/dim]",
                    classes="section-title",
                )

                for log_type, description in ALL_LOG_TYPES:
                    with Horizontal(classes="log-type-row"):
                        yield Checkbox(
                            description,
                            id=f"log-type-{log_type}",
                            value=True,
                        )

            with Container(classes="section"):
                yield Static("[bold]Log Statistics[/bold]", classes="section-title")
                yield Static("", id="log-stats")

    def on_mount(self) -> None:
        self.load_config()

    def refresh_content(self) -> None:
        self.load_config()

    def action_refresh(self) -> None:
        self.load_config()
        self.app.notify(
            "Violation logging configuration refreshed", severity="information"
        )

    def load_config(self) -> None:
        config_path = self._get_config_path()

        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                self.app.notify(f"Error loading config: {e}", severity="error")

        vlog_config = config.get("violation_logging", {})
        enabled_value = vlog_config.get("enabled", True)
        max_entries = vlog_config.get("max_entries", 1000)
        retention_days = vlog_config.get("retention_days", 30)
        log_types = vlog_config.get("log_types", [t for t, _ in ALL_LOG_TYPES])

        try:
            toggle = self.query_one(
                "#violation_logging_enabled_toggle", TimeBasedToggle
            )
            toggle.load_value(enabled_value)
        except Exception:
            pass

        try:
            self.query_one("#vlog-max-entries", Input).value = str(max_entries)
            self.query_one("#vlog-retention-days", Input).value = str(retention_days)
        except Exception:
            pass

        for log_type, _ in ALL_LOG_TYPES:
            try:
                cb = self.query_one(f"#log-type-{log_type}", Checkbox)
                cb.value = log_type in log_types
            except Exception:
                pass

        self._apply_default_indicators(vlog_config)
        self._load_statistics()

    def _load_statistics(self) -> None:
        try:
            from ai_guardian.violations.logger import ViolationLogger

            logger = ViolationLogger()
            recent = logger.get_recent_violations(limit=1000)
            total = len(recent)

            type_counts: Dict[str, int] = {}
            for v in recent:
                vtype = v.get("type", "unknown")
                type_counts[vtype] = type_counts.get(vtype, 0) + 1

            stats_text = f"Total logged violations: {total}\n"
            if type_counts:
                stats_text += "\nBy type:\n"
                for vtype, count in sorted(
                    type_counts.items(), key=lambda x: x[1], reverse=True
                ):
                    stats_text += f"  {vtype}: {count}\n"

            self.query_one("#log-stats", Static).update(stats_text.strip())

        except ImportError:
            self.query_one("#log-stats", Static).update(
                "[dim]Violation logger not available[/dim]"
            )
        except Exception as e:
            self.query_one("#log-stats", Static).update(
                f"[dim]Error loading stats: {e}[/dim]"
            )

    def _save_config(self, updates: Dict[str, Any]) -> bool:
        return self._save_config_updates(updates)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid and "violation_logging_enabled" in bid:
            toggle = self.query_one(
                "#violation_logging_enabled_toggle", TimeBasedToggle
            )
            if toggle.current_mode == "temp_disabled":
                return
            self._save_config({"enabled": toggle.get_value()})

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        checkbox_id = event.checkbox.id
        if not checkbox_id:
            return

        if checkbox_id.startswith("log-type-"):
            enabled_types = []
            for log_type, _ in ALL_LOG_TYPES:
                try:
                    cb = self.query_one(f"#log-type-{log_type}", Checkbox)
                    if cb.value:
                        enabled_types.append(log_type)
                except Exception:
                    pass
            self._save_config({"log_types": enabled_types})
            self.app.notify(
                f"Log types updated ({len(enabled_types)} enabled)",
                severity="information",
            )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        input_id = event.input.id

        if input_id == "vlog-max-entries":
            try:
                val = int(event.input.value.strip())
                if val < 1:
                    raise ValueError("Must be >= 1")
                self._save_config({"max_entries": val})
                self.app.notify(f"Max entries set to {val}", severity="information")
            except ValueError:
                self.app.notify(
                    "Max entries must be a positive integer", severity="error"
                )

        elif input_id == "vlog-retention-days":
            try:
                val = int(event.input.value.strip())
                if val < 1:
                    raise ValueError("Must be >= 1")
                self._save_config({"retention_days": val})
                self.app.notify(f"Retention set to {val} days", severity="information")
            except ValueError:
                self.app.notify(
                    "Retention days must be a positive integer", severity="error"
                )

        elif input_id and "violation_logging_enabled" in input_id:
            toggle = self.query_one(
                "#violation_logging_enabled_toggle", TimeBasedToggle
            )
            value = toggle.get_value()
            self._save_config({"enabled": value})
