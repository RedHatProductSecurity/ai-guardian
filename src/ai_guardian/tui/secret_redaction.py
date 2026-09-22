#!/usr/bin/env python3
"""
Secret Redaction Tab Content

View and configure secret redaction settings.
Redacts sensitive information from tool outputs instead of blocking operations.
"""

import json
from typing import Dict, Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static, Button, Input, Label, Select, Checkbox

from ai_guardian.tui.schema_defaults import (
    ConfigSaveMixin,
    SchemaDefaultsMixin,
    default_indicator,
    select_options_with_default,
)
from ai_guardian.tui.widgets import TimeBasedToggle


class SecretRedactionContent(ConfigSaveMixin, SchemaDefaultsMixin, Container):
    """Content widget for Secret Redaction tab."""

    CONFIG_SECTION = "secret_redaction"
    SCHEMA_SECTION = "secret_redaction"
    SCHEMA_FIELDS = [
        ("action-select", "action", "select"),
        ("preserve-format-checkbox", "preserve_format", "checkbox"),
        ("log-redactions-checkbox", "log_redactions", "checkbox"),
    ]

    CSS = """
    SecretRedactionContent {
        height: 100%;
    }

    #secret-redaction-header {
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
        width: auto;
    }

    .setting-row Select {
        width: 30;
    }

    .setting-row Input {
        width: 50;
    }

    .setting-row Checkbox {
        margin: 0 1 0 0;
    }

    .setting-row Button {
        margin: 0 0 0 1;
    }

    .list-scroll {
        max-height: 10;
        margin: 1 0;
        background: $surface;
        border: solid $primary;
    }

    #additional-patterns-list {
        padding: 1;
        min-height: 2;
    }

    #actions {
        margin: 1 0;
        height: auto;
    }

    #actions Button {
        margin: 0 1 0 0;
    }

    /* Focus indicators */
    Input:focus {
        border-left: heavy $accent;
        text-style: bold;
    }

    Button:focus {
        border-left: heavy $accent;
        text-style: bold;
    }

    Select:focus {
        border-left: heavy $accent;
        text-style: bold;
    }

    Checkbox:focus {
        border-left: heavy $accent;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the secret redaction tab content."""
        yield Static(
            "[bold]Secret Redaction Settings[/bold]", id="secret-redaction-header"
        )

        with VerticalScroll():
            # Redaction toggle section (standalone)
            yield TimeBasedToggle(
                title="Secret Redaction",
                config_key="secret_redaction_enabled",
                current_value=True,
                help_text="Redact secrets from tool outputs instead of blocking - allows work to continue while protecting credentials",
                id="secret_redaction_enabled_toggle",
            )

            # Default protected secret types info section
            with Container(classes="section"):
                yield Static(
                    "[bold]Protected Secret Types (35+ patterns)[/bold]",
                    classes="section-title",
                )
                yield Static(
                    "[dim]The following secret types are automatically detected and redacted:\n\n"
                    "API Keys & Tokens:\n"
                    "  • OpenAI API Keys (sk-, sk-proj-)\n"
                    "  • GitHub Tokens (ghp_, gho_, ghr_, ghs_)\n"
                    "  • Anthropic API Keys (sk-ant-)\n"
                    "  • GitLab Tokens (glpat-)\n"
                    "  • Slack Tokens (xox-)\n"
                    "  • Google API Keys, OAuth Tokens\n"
                    "  • npm, PyPI, Azure tokens\n\n"
                    "Cloud Credentials:\n"
                    "  • AWS Access Keys (AKIA*)\n"
                    "  • AWS Secret Keys\n"
                    "  • Azure Client Secrets\n\n"
                    "Payment & Services:\n"
                    "  • Stripe Keys (all types)\n"
                    "  • Twilio API Keys\n"
                    "  • SendGrid, Mailgun Keys\n\n"
                    "Sensitive Data:\n"
                    "  • Private Keys (PEM format)\n"
                    "  • Environment Variables\n"
                    "  • JSON/YAML passwords\n"
                    "  • HTTP Authorization headers[/dim]",
                    id="default-patterns",
                )
            # Action mode section
            with Container(classes="section"):
                yield Static(
                    "[bold]Action on Secret Detection[/bold]", classes="section-title"
                )

                with Horizontal(classes="setting-row"):
                    yield Label("Action Mode:")
                    yield Select(
                        select_options_with_default(
                            [
                                ("Log Only (redact silently)", "log-only"),
                                ("Warn (redact and notify)", "warn"),
                            ],
                            "secret_redaction.action",
                        ),
                        value="warn",
                        id="action-select",
                    )
                    yield Static("[dim](Press 's' to save)[/dim]")

                yield Static(
                    "[dim]  • Log Only: Redacts secrets silently, logs to violation log\n"
                    "  • Warn: Redacts secrets and shows warning notification (default)[/dim]",
                    classes="setting-row",
                )
            # Redaction options section
            with Container(classes="section"):
                yield Static("[bold]Redaction Options[/bold]", classes="section-title")

                with Horizontal(classes="setting-row"):
                    yield Label("Preserve Format:")
                    yield Checkbox("", id="preserve-format-checkbox", value=True)
                    yield Static(
                        f"[dim]Keep prefix/suffix visible for debugging (e.g., sk-***-xyz)[/dim] "
                        f"{default_indicator('secret_redaction.preserve_format')}"
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("Log Redactions:")
                    yield Checkbox("", id="log-redactions-checkbox", value=True)
                    yield Static(
                        f"[dim]Record all redactions in violation log for audit trail[/dim] "
                        f"{default_indicator('secret_redaction.log_redactions')}"
                    )

            # Additional patterns section
            with Container(classes="section"):
                yield Static(
                    "[bold]Additional Redaction Patterns[/bold]",
                    classes="section-title",
                )
                yield Static(
                    "Custom regex patterns to detect and redact:", classes="setting-row"
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="additional-patterns-list")
                yield Input(
                    placeholder="Enter custom regex pattern (e.g., MY_SECRET_[A-Z0-9]+)",
                    id="new-pattern-input",
                )
                yield Static(
                    "[dim]Press 'p' to add pattern[/dim]", classes="setting-row"
                )

            # Statistics section
            with Container(classes="section"):
                yield Static(
                    "[bold]Redaction Statistics[/bold]", classes="section-title"
                )
                yield Static("", id="redaction-stats")

    def on_mount(self) -> None:
        """Load configuration when mounted."""
        self.load_config()

    def refresh_content(self) -> None:
        """Refresh configuration (called by parent app)."""
        self.load_config()

    def load_config(self) -> None:
        """Load and display secret redaction configuration."""
        config_path = self._get_config_path()

        # Load config
        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                self.app.notify(f"Error loading config: {e}", severity="error")

        # Secret redaction settings
        redaction_config = config.get("secret_redaction", {})
        enabled_value = redaction_config.get("enabled", True)
        action = redaction_config.get("action", "warn")
        preserve_format = redaction_config.get("preserve_format", True)
        log_redactions = redaction_config.get("log_redactions", True)
        additional_patterns = redaction_config.get("additional_patterns", [])

        # Update widgets
        try:
            toggle = self.query_one("#secret_redaction_enabled_toggle", TimeBasedToggle)
            toggle.load_value(enabled_value)

            self.query_one("#action-select", Select).value = action
            self.query_one("#preserve-format-checkbox", Checkbox).value = (
                preserve_format
            )
            self.query_one("#log-redactions-checkbox", Checkbox).value = log_redactions
        except Exception:
            pass  # Widgets may not be fully mounted yet

        # Update additional patterns list
        if additional_patterns:
            patterns_text = "\n".join(
                [f"  • {pattern}" for pattern in additional_patterns]
            )
        else:
            patterns_text = "[dim]No additional patterns configured[/dim]"
        self.query_one("#additional-patterns-list", Static).update(patterns_text)

        # Apply schema default indicators
        self._apply_default_indicators(redaction_config)

        # Load statistics
        self._load_statistics()

    def _load_statistics(self) -> None:
        """Load and display secret redaction statistics."""
        try:
            from ai_guardian.violations.logger import ViolationLogger

            logger = ViolationLogger()

            # Get recent violations related to secret redaction
            recent = logger.get_recent_violations(limit=1000)
            redaction_count = 0
            secret_types: dict[str, int] = {}

            for v in recent:
                reason = v.get("reason", "")
                # Look for redaction entries
                if "redact" in reason.lower() or "secret" in reason.lower():
                    redaction_count += 1
                    # Try to extract secret type from reason
                    if ":" in reason:
                        secret_type = reason.split(":")[0].strip()
                        secret_types[secret_type] = secret_types.get(secret_type, 0) + 1

            stats_text = f"Total Secrets Redacted: {redaction_count}\n"

            if secret_types:
                stats_text += "\nTop Secret Types:\n"
                sorted_types = sorted(
                    secret_types.items(), key=lambda x: x[1], reverse=True
                )[:5]
                for secret_type, count in sorted_types:
                    stats_text += f"  • {secret_type}: {count}\n"

            self.query_one("#redaction-stats", Static).update(stats_text.strip())

        except ImportError:
            self.query_one("#redaction-stats", Static).update(
                "[dim]Violation logging not available[/dim]"
            )
        except Exception as e:
            self.query_one("#redaction-stats", Static).update(
                f"[dim]Error loading stats: {e}[/dim]"
            )

    def save_config(self, config_updates: Dict[str, Any]) -> bool:
        """
        Save configuration updates.

        Args:
            config_updates: Dictionary of configuration updates

        Returns:
            bool: True if successful, False otherwise
        """
        if self._save_config_updates(config_updates):
            self.app.notify(
                "Secret redaction configuration saved", severity="information"
            )
            return True
        else:
            self.app.notify("Error saving config", severity="error")
            return False

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox changes - save immediately."""
        checkbox_id = event.checkbox.id

        if checkbox_id == "preserve-format-checkbox":
            self.save_config({"preserve_format": event.value})
        elif checkbox_id == "log-redactions-checkbox":
            self.save_config({"log_redactions": event.value})

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press - save toggle state immediately."""
        bid = event.button.id
        if bid and "secret_redaction_enabled" in bid:
            toggle = self.query_one("#secret_redaction_enabled_toggle", TimeBasedToggle)
            if toggle.current_mode == "temp_disabled":
                return
            self.save_config({"enabled": toggle.get_value()})

    def on_select_changed(self, event) -> None:
        """Handle select changes - save immediately."""
        select_id = event.select.id

        if select_id == "action-select":
            self.save_config({"action": event.value})

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields."""
        input_id = event.input.id

        # Handle TimeBasedToggle inputs
        if input_id and "secret_redaction_enabled" in input_id:
            toggle = self.query_one("#secret_redaction_enabled_toggle", TimeBasedToggle)
            value = toggle.get_value()
            self.save_config({"enabled": value})
        elif input_id == "new-pattern-input":
            self.add_pattern()

    def action_add_pattern(self) -> None:
        """Add custom pattern (triggered by 'p' key)."""
        self.add_pattern()

    def action_save_setting(self) -> None:
        """Save settings (triggered by 's' key)."""
        # Already auto-saved on change, just notify
        self.app.notify("Settings auto-saved on change", severity="information")

    def action_refresh(self) -> None:
        """Refresh configuration (triggered by 'r' key)."""
        self.load_config()
        self.app.notify(
            "Secret redaction configuration refreshed", severity="information"
        )

    def add_pattern(self) -> None:
        """Add a custom redaction pattern."""
        pattern_input = self.query_one("#new-pattern-input", Input)
        pattern_value = pattern_input.value.strip()

        if not pattern_value:
            self.app.notify("Please enter a redaction pattern", severity="error")
            return

        # Try to compile as regex to validate
        import re

        try:
            re.compile(pattern_value)
        except re.error as e:
            self.app.notify(f"Invalid regex pattern: {e}", severity="error")
            return

        try:
            config = self._load_full_config()
            if "secret_redaction" not in config:
                config["secret_redaction"] = {}

            if "additional_patterns" not in config["secret_redaction"]:
                config["secret_redaction"]["additional_patterns"] = []

            # Check if pattern already exists
            if pattern_value in config["secret_redaction"]["additional_patterns"]:
                self.app.notify("Pattern already in list", severity="warning")
                return

            config["secret_redaction"]["additional_patterns"].append(pattern_value)
            self._write_full_config(config)

            # Clear input
            pattern_input.value = ""

            self.load_config()
            self.app.notify("✓ Added redaction pattern", severity="success")

        except Exception as e:
            self.app.notify(f"Error adding pattern: {e}", severity="error")
