#!/usr/bin/env python3
"""
Config File Scanner Tab Content

View and configure config file scanning settings.
Detects credential exfiltration commands in AI config files (CLAUDE.md, AGENTS.md, etc.)
"""

import json
from pathlib import Path
from typing import Dict, Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static, Button, Input, Label, Select

from ai_guardian.tui.schema_defaults import (
    ConfigSaveMixin,
    SchemaDefaultsMixin,
    select_options_with_default,
)
from ai_guardian.tui.widgets import TimeBasedToggle, sanitize_enabled_value


class ConfigScannerContent(ConfigSaveMixin, SchemaDefaultsMixin, Container):
    """Content widget for Config File Scanner tab."""

    CONFIG_SECTION = "config_file_scanning"
    SCHEMA_SECTION = "config_file_scanning"
    SCHEMA_FIELDS = [
        ("action-select", "action", "select"),
    ]

    CSS = """
    ConfigScannerContent {
        height: 100%;
    }

    #config-scanner-header {
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

    .setting-row Button {
        margin: 0 0 0 1;
    }

    .list-scroll {
        max-height: 10;
        margin: 1 0;
        background: $surface;
        border: solid $primary;
    }

    #additional-files-list, #ignore-files-list, #additional-patterns-list {
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
        """Compose the config file scanner tab content."""
        yield Static(
            "[bold]Config File Scanner Settings[/bold]", id="config-scanner-header"
        )

        with VerticalScroll():
            # Scanner toggle section (standalone)
            yield TimeBasedToggle(
                title="Config File Scanning",
                config_key="config_file_scanning_enabled",
                current_value=True,
                help_text="Detect credential exfiltration commands in AI config files (CLAUDE.md, AGENTS.md, etc.)",
                id="config_file_scanning_enabled_toggle",
            )

            # Default scanned files info section
            with Container(classes="section"):
                yield Static(
                    "[bold]Default Scanned Files (Immutable)[/bold]",
                    classes="section-title",
                )
                yield Static(
                    "[dim]The following files are ALWAYS scanned:\n\n"
                    "AI Agent Configuration Files:\n"
                    "  • CLAUDE.md\n"
                    "  • AGENTS.md\n"
                    "  • .claude/CLAUDE.md\n"
                    "  • .agents/AGENTS.md\n"
                    "  • .cursorrules\n"
                    "  • .windsurfrules\n"
                    "  • .aider.conf.yml\n\n"
                    "Skill Files:\n"
                    "  • **/.claude/skills/**/*.md\n"
                    "  • **/.agents/skills/**/*.md\n"
                    "  • **/skills/**/*.md\n\n"
                    "These files are scanned for credential exfiltration patterns.[/dim]",
                    id="default-files",
                )

            # Action mode section
            with Container(classes="section"):
                yield Static(
                    "[bold]Action on Detection[/bold]", classes="section-title"
                )

                with Horizontal(classes="setting-row"):
                    yield Label("Action Mode:")
                    yield Select(
                        select_options_with_default(
                            [
                                ("Block", "block"),
                                ("Warn (allow but notify)", "warn"),
                                ("Log Only (silent)", "log-only"),
                            ],
                            "config_file_scanning.action",
                        ),
                        value="block",
                        id="action-select",
                    )
                    yield Static("[dim](Press 's' to save)[/dim]")

                yield Static(
                    "[dim]  • Block: Prevents scanning these config files (recommended)\n"
                    "  • Warn: Logs violation and shows warning, but allows scanning\n"
                    "  • Log Only: Logs violation silently without user warning[/dim]",
                    classes="setting-row",
                )

            # Additional files section
            with Container(classes="section"):
                yield Static(
                    "[bold]Additional Files to Scan[/bold]", classes="section-title"
                )
                yield Static(
                    "Additional config files to monitor:", classes="setting-row"
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="additional-files-list")
                yield Input(
                    placeholder="Enter filename pattern (e.g., .myagent.conf)",
                    id="new-additional-file-input",
                )
                yield Static(
                    "[dim]Press 'f' to add file pattern[/dim]", classes="setting-row"
                )

            # Ignore files section
            with Container(classes="section"):
                yield Static("[bold]Ignore Files[/bold]", classes="section-title")
                yield Static(
                    "File patterns to exclude from scanning:", classes="setting-row"
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="ignore-files-list")
                yield Input(
                    placeholder="Enter ignore pattern (e.g., **/*.example.md)",
                    id="new-ignore-file-input",
                )
                yield Static(
                    "[dim]Press 'g' to add ignore pattern[/dim]", classes="setting-row"
                )

            # Ignore tools section
            with Container(classes="section"):
                yield Static("[bold]Ignore Tools[/bold]", classes="section-title")
                yield Static(
                    "[dim]Tool name patterns to skip during config file scanning.[/dim]",
                    classes="section-title",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="config-ignore-tools-list")
                yield Input(
                    placeholder="Enter tool pattern (e.g. mcp__*)",
                    id="config-ignore-tool-input",
                )

            # Additional patterns section
            with Container(classes="section"):
                yield Static(
                    "[bold]Additional Detection Patterns[/bold]",
                    classes="section-title",
                )
                yield Static(
                    "Custom regex patterns to detect as credential exfiltration:",
                    classes="setting-row",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="additional-patterns-list")
                yield Input(
                    placeholder="Enter custom regex pattern", id="new-pattern-input"
                )
                yield Static(
                    "[dim]Press 'p' to add pattern[/dim]", classes="setting-row"
                )

            # Statistics section
            with Container(classes="section"):
                yield Static(
                    "[bold]Detection Statistics[/bold]", classes="section-title"
                )
                yield Static("", id="scanner-stats")

    def on_mount(self) -> None:
        """Load configuration when mounted."""
        self._loading = False
        self.load_config()

    def refresh_content(self) -> None:
        """Refresh configuration (called by parent app)."""
        self.load_config()

    def load_config(self) -> None:
        """Load and display config file scanner configuration."""
        self._loading = True
        try:
            self._load_config_inner()
        finally:
            self._loading = False

    def _load_config_inner(self) -> None:
        """Inner load logic for config file scanner configuration."""
        config_path = self._get_config_path()

        # Load config
        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                self.app.notify(f"Error loading config: {e}", severity="error")

        # Config file scanning settings
        scanner_config = config.get("config_file_scanning", {})
        enabled_value = scanner_config.get("enabled", True)
        action = scanner_config.get("action", "block")
        additional_files = scanner_config.get("additional_files", [])
        ignore_files = scanner_config.get("ignore_files", [])
        additional_patterns = scanner_config.get("additional_patterns", [])

        # Update widgets
        try:
            toggle = self.query_one(
                "#config_file_scanning_enabled_toggle", TimeBasedToggle
            )
            toggle.load_value(enabled_value)

            self.query_one("#action-select", Select).value = action
        except Exception:
            pass  # Widgets may not be fully mounted yet

        # Update additional files list
        if additional_files:
            files_text = "\n".join([f"  • {file}" for file in additional_files])
        else:
            files_text = "[dim]No additional files configured[/dim]"
        self.query_one("#additional-files-list", Static).update(files_text)

        # Update ignore files list
        if ignore_files:
            ignore_text = "\n".join([f"  • {pattern}" for pattern in ignore_files])
        else:
            ignore_text = "[dim]No ignore patterns configured[/dim]"
        self.query_one("#ignore-files-list", Static).update(ignore_text)

        # Update ignore tools list
        ignore_tools = scanner_config.get("ignore_tools", [])
        try:
            if ignore_tools:
                ignore_tools_text = "\n".join(f"  {t}" for t in ignore_tools)
            else:
                ignore_tools_text = "[dim]No ignored tools configured[/dim]"
            self.query_one("#config-ignore-tools-list", Static).update(
                ignore_tools_text
            )
        except Exception:
            pass

        # Update additional patterns list
        if additional_patterns:
            patterns_text = "\n".join(
                [f"  • {pattern}" for pattern in additional_patterns]
            )
        else:
            patterns_text = "[dim]No additional patterns configured[/dim]"
        self.query_one("#additional-patterns-list", Static).update(patterns_text)

        # Apply schema default indicators
        self._apply_default_indicators(scanner_config)

        # Load statistics
        self._load_statistics()

    def _load_statistics(self) -> None:
        """Load and display config file scanner statistics."""
        try:
            from ai_guardian.violations.logger import ViolationLogger

            logger = ViolationLogger()

            # Get recent violations related to config file scanning
            recent = logger.get_recent_violations(limit=100)
            scanner_count = 0

            for v in recent:
                reason = v.get("reason", "")
                if (
                    "config" in reason.lower()
                    or "CLAUDE.md" in reason
                    or "AGENTS.md" in reason
                ):
                    scanner_count += 1

            stats_text = f"Total Config File Scanner Detections: {scanner_count}"
            self.query_one("#scanner-stats", Static).update(stats_text)

        except ImportError:
            self.query_one("#scanner-stats", Static).update(
                "[dim]Violation logging not available[/dim]"
            )
        except Exception as e:
            self.query_one("#scanner-stats", Static).update(
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
        try:
            if self._save_config_updates(config_updates):
                self.app.notify(
                    "Config file scanner configuration saved",
                    severity="information",
                )
                return True
            return False

        except Exception as e:
            self.app.notify(f"Error saving config: {e}", severity="error")
            return False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press - save toggle state immediately."""
        if getattr(self, "_loading", False):
            return
        bid = event.button.id
        if bid and "config_file_scanning_enabled" in bid:
            toggle = self.query_one(
                "#config_file_scanning_enabled_toggle", TimeBasedToggle
            )
            if toggle.current_mode == "temp_disabled":
                return
            self.save_config({"enabled": toggle.get_value()})

    def on_select_changed(self, event) -> None:
        """Handle select changes - save immediately."""
        if getattr(self, "_loading", False):
            return
        select_id = event.select.id

        if select_id == "action-select":
            self.save_config({"action": event.value})

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields."""
        if getattr(self, "_loading", False):
            return
        input_id = event.input.id

        # Handle TimeBasedToggle inputs
        if input_id and "config_file_scanning_enabled" in input_id:
            toggle = self.query_one(
                "#config_file_scanning_enabled_toggle", TimeBasedToggle
            )
            value = toggle.get_value()
            self.save_config({"enabled": value})
        elif input_id == "new-additional-file-input":
            self.add_additional_file()
        elif input_id == "new-ignore-file-input":
            self.add_ignore_file()
        elif input_id == "new-pattern-input":
            self.add_pattern()
        elif input_id == "config-ignore-tool-input":
            self._add_ignore_tool()

    def action_add_file(self) -> None:
        """Add additional file (triggered by 'f' key)."""
        self.add_additional_file()

    def action_add_ignore(self) -> None:
        """Add ignore pattern (triggered by 'g' key)."""
        self.add_ignore_file()

    def action_add_pattern(self) -> None:
        """Add detection pattern (triggered by 'p' key)."""
        self.add_pattern()

    def action_save_setting(self) -> None:
        """Save settings (triggered by 's' key)."""
        # Already auto-saved on change, just notify
        self.app.notify("Settings auto-saved on change", severity="information")

    def action_refresh(self) -> None:
        """Refresh configuration (triggered by 'r' key)."""
        self.load_config()
        self.app.notify(
            "Config scanner configuration refreshed", severity="information"
        )

    def add_additional_file(self) -> None:
        """Add a file pattern to the additional files list."""
        file_input = self.query_one("#new-additional-file-input", Input)
        file_value = file_input.value.strip()

        if not file_value:
            self.app.notify("Please enter a file pattern", severity="error")
            return

        try:
            if self._add_config_list_item("additional_files", file_value, file_input):
                self.app.notify(
                    f"✓ Added {file_value} to additional files",
                    severity="success",
                )
        except Exception as e:
            self.app.notify(f"Error adding file: {e}", severity="error")

    def add_ignore_file(self) -> None:
        """Add a pattern to the ignore files list."""
        ignore_input = self.query_one("#new-ignore-file-input", Input)
        ignore_value = ignore_input.value.strip()

        if not ignore_value:
            self.app.notify("Please enter an ignore pattern", severity="error")
            return

        try:
            if self._add_config_list_item("ignore_files", ignore_value, ignore_input):
                self.app.notify(
                    f"✓ Added {ignore_value} to ignore patterns",
                    severity="success",
                )
        except Exception as e:
            self.app.notify(f"Error adding ignore pattern: {e}", severity="error")

    def _add_ignore_tool(self) -> None:
        """Add a pattern to the ignore tools list."""
        input_widget = self.query_one("#config-ignore-tool-input", Input)
        value = input_widget.value.strip()

        if not value:
            self.app.notify("Please enter a tool pattern", severity="error")
            return

        try:
            if self._add_config_list_item("ignore_tools", value, input_widget):
                self.app.notify(f"Added: {value}", severity="success")
        except Exception as e:
            self.app.notify(f"Error adding pattern: {e}", severity="error")

    def add_pattern(self) -> None:
        """Add a detection pattern to the additional patterns list."""
        pattern_input = self.query_one("#new-pattern-input", Input)
        pattern_value = pattern_input.value.strip()

        if not pattern_value:
            self.app.notify("Please enter a detection pattern", severity="error")
            return

        import re

        try:
            re.compile(pattern_value)
        except re.error as e:
            self.app.notify(f"Invalid regex pattern: {e}", severity="error")
            return

        try:
            if self._add_config_list_item(
                "additional_patterns", pattern_value, pattern_input
            ):
                self.app.notify("✓ Added detection pattern", severity="success")
        except Exception as e:
            self.app.notify(f"Error adding pattern: {e}", severity="error")
