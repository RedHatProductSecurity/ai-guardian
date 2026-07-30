#!/usr/bin/env python3
"""
PII Detection Tab Content

View and configure PII (Personally Identifiable Information) detection settings.
Scans user prompts, file reads, and tool outputs for SSNs, credit cards, etc.
"""

import json
from pathlib import Path
from typing import Dict, Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static, Button, Input, Label, Select, Checkbox

from ai_guardian.config.utils import get_config_dir, get_project_config_path
from ai_guardian.tui.schema_defaults import (
    ConfigSaveMixin,
    SchemaDefaultsMixin,
    select_options_with_default,
)
from ai_guardian.tui.widgets import (
    TimeBasedToggle,
    sanitize_enabled_value,
    format_local_time,
)

PHASE1_PII_TYPES = [
    ("ssn", "Social Security Numbers (XXX-XX-XXXX)"),
    ("credit_card", "Credit Card Numbers (Visa, MC, Amex, etc.)"),
    ("phone", "US Phone Numbers"),
    ("email", "Email Addresses"),
    ("us_passport", "US Passport Numbers"),
    ("iban", "International Bank Account Numbers"),
    ("intl_phone", "International Phone Numbers (+country code)"),
]

PHASE2_PII_TYPES = [
    ("medical_id", "Medical Record Numbers (context-aware)"),
    ("passport", "International Passport Numbers (context-aware)"),
    ("canada_sin", "Canadian Social Insurance Numbers (Luhn-validated)"),
    ("uk_nin", "UK National Insurance Numbers"),
    ("india_aadhaar", "Indian Aadhaar Numbers"),
    ("address", "Street Addresses (regex-based, limited)"),
]

ALL_PII_TYPES = PHASE1_PII_TYPES + PHASE2_PII_TYPES


class ScanPIIContent(ConfigSaveMixin, SchemaDefaultsMixin, Container):
    CONFIG_SECTION = "scan_pii"
    """Content widget for PII Detection tab."""

    SCHEMA_SECTION = "scan_pii"
    SCHEMA_FIELDS = [
        ("pii-action-select", "action", "select"),
    ]

    CSS = """
    ScanPIIContent {
        height: 100%;
    }

    #pii-header {
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
        height: auto;
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
        width: 40;
    }

    .pii-type-check {
        margin: 0 0 0 1;
    }

    .list-scroll {
        max-height: 10;
        margin: 1 0;
        background: $surface;
        border: solid $primary;
    }

    #ignore-files-list, #ignore-tools-list, #pii-allowlist-patterns {
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
        yield Static("[bold]PII Detection Settings[/bold]", id="pii-header")

        with VerticalScroll():
            yield TimeBasedToggle(
                title="PII Detection",
                config_key="scan_pii_enabled",
                current_value=True,
                help_text="Scan prompts, file reads, and tool outputs for personally identifiable information (GDPR/CCPA compliance)",
                id="scan_pii_enabled_toggle",
            )

            with Container(classes="section"):
                yield Static(
                    "[bold]Action on PII Detection[/bold]", classes="section-title"
                )

                with Horizontal(classes="setting-row"):
                    yield Label("Action Mode:")
                    yield Select(
                        select_options_with_default(
                            [
                                ("Block (reject operation)", "block"),
                                ("Ask (block if headless)", "ask"),
                                ("Ask (warn if headless)", "ask:warn"),
                                ("Ask (log-only if headless)", "ask:log-only"),
                                ("Redact (mask PII in output)", "redact"),
                                ("Warn (allow with warning)", "warn"),
                                ("Log Only (silent logging)", "log-only"),
                            ],
                            "scan_pii.action",
                        ),
                        value="block",
                        id="pii-action-select",
                    )

                yield Static(
                    "[dim]  block: Reject the operation entirely\n"
                    "  ask: Interactive prompt (Allow Once/Always/Block)\n"
                    "  redact: Mask PII in PostToolUse, block in PreToolUse/UserPromptSubmit\n"
                    "  warn: Log violation and show warning but allow\n"
                    "  log-only: Log violation silently[/dim]",
                    classes="setting-row",
                )

            with Container(classes="section"):
                yield Static(
                    "[bold]PII Types to Detect[/bold]", classes="section-title"
                )
                yield Static(
                    "[dim]Uncheck types to disable detection for specific PII categories.[/dim]",
                    classes="section-title",
                )

                for pii_type, description in PHASE1_PII_TYPES:
                    yield Checkbox(
                        description,
                        id=f"pii-type-{pii_type}",
                        value=True,
                        classes="pii-type-check",
                    )

            with Container(classes="section"):
                yield Static(
                    "[bold]Phase 2 PII Types (opt-in)[/bold]", classes="section-title"
                )
                yield Static(
                    "[dim]Advanced types — not enabled by default. Add to pii_types to enable.[/dim]",
                    classes="section-title",
                )

                for pii_type, description in PHASE2_PII_TYPES:
                    yield Checkbox(
                        description,
                        id=f"pii-type-{pii_type}",
                        value=False,
                        classes="pii-type-check",
                    )

            with Container(classes="section"):
                yield Static("[bold]Ignore Files[/bold]", classes="section-title")
                yield Static(
                    "[dim]Glob patterns for files to skip during PII scanning "
                    "(e.g., test files with example PII data).[/dim]",
                    classes="section-title",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="ignore-files-list")
                yield Input(
                    placeholder="Enter glob pattern (e.g., tests/**, *.test.py)",
                    id="pii-ignore-file-input",
                )

            with Container(classes="section"):
                yield Static("[bold]Ignore Tools[/bold]", classes="section-title")
                yield Static(
                    "[dim]Tool name patterns to skip during PII scanning "
                    "(e.g., mcp__*, Skill:*, Bash).[/dim]",
                    classes="section-title",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="ignore-tools-list")
                yield Input(
                    placeholder="Enter tool name pattern (e.g., mcp__*, Skill:*)",
                    id="pii-ignore-tool-input",
                )

            with Container(classes="section"):
                yield Static("[bold]Allowlist Patterns[/bold]", classes="section-title")
                yield Static(
                    "[dim]Regex patterns for known-safe PII values to ignore "
                    "(e.g., @anthropic.com emails, @example.com addresses). "
                    "Unlike ignore_files, this keeps scanning but skips matching values.[/dim]",
                    classes="section-title",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="pii-allowlist-patterns")
                yield Input(
                    placeholder="Enter regex pattern (e.g., \\b[\\w.+-]+@example\\.com\\b)",
                    id="pii-allowlist-input",
                )

    def on_mount(self) -> None:
        self._loading = False
        self.load_config()
        self._apply_tooltips()

    def _apply_tooltips(self) -> None:
        """Set Textual tooltips from CONFIG_FIELD_HELP on key widgets."""
        try:
            from ai_guardian.help_content import CONFIG_FIELD_HELP
        except Exception:
            return
        _tip = {
            "scan_pii_enabled_toggle": CONFIG_FIELD_HELP.get("scan_pii"),
            "pii-action-select": CONFIG_FIELD_HELP.get("scan_pii"),
        }
        for widget_id, help_text in _tip.items():
            if help_text:
                try:
                    self.query_one(f"#{widget_id}").tooltip = help_text
                except Exception:
                    pass

    def refresh_content(self) -> None:
        self.load_config()

    def action_refresh(self) -> None:
        self.load_config()
        self.app.notify("PII detection configuration refreshed", severity="information")

    def action_save_setting(self) -> None:
        self.app.notify("Settings auto-saved on change", severity="information")

    def load_config(self) -> None:
        self._loading = True
        try:
            self._load_config_inner()
        finally:
            self._loading = False

    def _load_config_inner(self) -> None:
        config_path = self._get_config_path()

        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                self.app.notify(f"Error loading config: {e}", severity="error")

        pii_config = config.get("scan_pii", {})
        enabled_value = pii_config.get("enabled", True)
        action = pii_config.get("action", "block")
        pii_types = pii_config.get("pii_types", [t for t, _ in ALL_PII_TYPES])
        ignore_files = pii_config.get("ignore_files", [])
        ignore_tools = pii_config.get("ignore_tools", [])

        try:
            toggle = self.query_one("#scan_pii_enabled_toggle", TimeBasedToggle)
            toggle.load_value(enabled_value)
        except Exception:
            pass

        try:
            self.query_one("#pii-action-select", Select).value = action
        except Exception:
            pass

        for pii_type, _ in ALL_PII_TYPES:
            try:
                cb = self.query_one(f"#pii-type-{pii_type}", Checkbox)
                cb.value = pii_type in pii_types
            except Exception:
                pass

        if ignore_files:
            files_text = "\n".join([f"  {f}" for f in ignore_files])
        else:
            files_text = "[dim]No ignore patterns configured[/dim]"
        try:
            self.query_one("#ignore-files-list", Static).update(files_text)
        except Exception:
            pass

        if ignore_tools:
            tools_text = "\n".join([f"  {t}" for t in ignore_tools])
        else:
            tools_text = "[dim]No ignored tools configured[/dim]"
        try:
            self.query_one("#ignore-tools-list", Static).update(tools_text)
        except Exception:
            pass

        allowlist = pii_config.get("allowlist_patterns", [])
        if allowlist:
            pattern_lines = []
            for pattern in allowlist:
                if isinstance(pattern, dict):
                    pattern_str = pattern.get("pattern", "")
                    valid_until = pattern.get("valid_until", "")
                    if valid_until:
                        from datetime import datetime, timezone

                        try:
                            expiry_dt = datetime.fromisoformat(
                                valid_until.replace("Z", "+00:00")
                            )
                            now = datetime.now(timezone.utc)
                            if expiry_dt <= now:
                                pattern_lines.append(f"  {pattern_str} [EXPIRED]")
                            elif (expiry_dt - now).total_seconds() < 86400:
                                pattern_lines.append(
                                    f"  {pattern_str} [expires {format_local_time(valid_until)}]"
                                )
                            else:
                                pattern_lines.append(
                                    f"  {pattern_str} [until {format_local_time(valid_until)}]"
                                )
                        except (ValueError, TypeError):
                            pattern_lines.append(f"  {pattern_str}")
                    else:
                        pattern_lines.append(f"  {pattern_str}")
                else:
                    pattern_lines.append(f"  {pattern}")
            allowlist_text = "\n".join(pattern_lines)
        else:
            allowlist_text = "[dim]No allowlist patterns configured[/dim]"
        try:
            self.query_one("#pii-allowlist-patterns", Static).update(allowlist_text)
        except Exception:
            pass

        self._apply_default_indicators(pii_config)

    def _save_config(self, updates: Dict[str, Any]) -> bool:
        return self._save_config_updates(updates)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if getattr(self, "_loading", False):
            return
        bid = event.button.id
        if bid and "scan_pii_enabled" in bid:
            toggle = self.query_one("#scan_pii_enabled_toggle", TimeBasedToggle)
            if toggle.current_mode == "temp_disabled":
                return
            self._save_config({"enabled": toggle.get_value()})

    def on_select_changed(self, event) -> None:
        if getattr(self, "_loading", False):
            return
        if event.select.id == "pii-action-select":
            self._save_config({"action": event.value})
            self.app.notify(f"PII action set to: {event.value}", severity="information")

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if getattr(self, "_loading", False):
            return
        checkbox_id = event.checkbox.id
        if not checkbox_id:
            return

        if checkbox_id.startswith("pii-type-"):
            enabled_types = []
            for pii_type, _ in ALL_PII_TYPES:
                try:
                    cb = self.query_one(f"#pii-type-{pii_type}", Checkbox)
                    if cb.value:
                        enabled_types.append(pii_type)
                except Exception:
                    pass
            self._save_config({"pii_types": enabled_types})
            self.app.notify(
                f"PII types updated ({len(enabled_types)} enabled)",
                severity="information",
            )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if getattr(self, "_loading", False):
            return
        if event.input.id == "pii-ignore-file-input":
            self._add_ignore_file()
        elif event.input.id == "pii-ignore-tool-input":
            self._add_ignore_tool()
        elif event.input.id == "pii-allowlist-input":
            self._add_allowlist_pattern()
        elif event.input.id and "scan_pii_enabled" in event.input.id:
            toggle = self.query_one("#scan_pii_enabled_toggle", TimeBasedToggle)
            value = toggle.get_value()
            self._save_config({"enabled": value})

    def _add_ignore_file(self) -> None:
        input_widget = self.query_one("#pii-ignore-file-input", Input)
        pattern = input_widget.value.strip()

        if not pattern:
            self.app.notify("Please enter a glob pattern", severity="error")
            return

        try:
            if self._add_config_list_item("ignore_files", pattern, input_widget):
                self.app.notify(f"Added ignore pattern: {pattern}", severity="success")
        except Exception as e:
            self.app.notify(f"Error adding pattern: {e}", severity="error")

    def _add_ignore_tool(self) -> None:
        input_widget = self.query_one("#pii-ignore-tool-input", Input)
        pattern = input_widget.value.strip()

        if not pattern:
            self.app.notify("Please enter a tool name pattern", severity="error")
            return

        try:
            if self._add_config_list_item("ignore_tools", pattern, input_widget):
                self.app.notify(
                    f"Added ignore tool pattern: {pattern}", severity="success"
                )
        except Exception as e:
            self.app.notify(f"Error adding pattern: {e}", severity="error")

    def _add_allowlist_pattern(self) -> None:
        input_widget = self.query_one("#pii-allowlist-input", Input)
        pattern = input_widget.value.strip()

        if not pattern:
            self.app.notify("Please enter a regex pattern", severity="error")
            return

        import re

        try:
            re.compile(pattern)
        except re.error as e:
            self.app.notify(f"Invalid regex: {e}", severity="error")
            return

        try:
            if self._add_config_list_item("allowlist_patterns", pattern, input_widget):
                self.app.notify(
                    f"Added allowlist pattern: {pattern}", severity="success"
                )
        except Exception as e:
            self.app.notify(f"Error adding pattern: {e}", severity="error")
