#!/usr/bin/env python3
"""
Prompt Injection Tab Content

View and configure prompt injection detection settings.
"""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static, Button, Input, Label, Select, Checkbox

from ai_guardian.tui.schema_defaults import (
    ConfigSaveMixin,
    SchemaDefaultsMixin,
    default_indicator,
    default_placeholder,
    select_options_with_default,
)
from ai_guardian.tui.widgets import TimeBasedToggle, format_local_time


class PromptInjectionContent(ConfigSaveMixin, SchemaDefaultsMixin, Container):
    """Content widget for Prompt Injection tab."""

    CONFIG_SECTION = "prompt_injection"
    SCHEMA_SECTION = "prompt_injection"
    SCHEMA_FIELDS = [
        ("detector-select", "detector", "select"),
        ("sensitivity-select", "sensitivity", "select"),
        ("score-threshold-input", "max_score_threshold", "input"),
    ]

    CSS = """
    PromptInjectionContent {
        height: 100%;
    }

    #prompt-injection-header {
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

    #allowlist-patterns, #custom-patterns {
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
        """Compose the prompt injection tab content."""
        yield Static(
            "[bold]Prompt Injection Detection Settings[/bold]",
            id="prompt-injection-header",
        )

        with VerticalScroll():
            # Detection toggle section (standalone)
            yield TimeBasedToggle(
                title="Prompt Injection Detection",
                config_key="prompt_injection_enabled",
                current_value=True,
                help_text="Protects against prompt injection attacks that try to manipulate AI behavior",
                id="prompt_injection_enabled_toggle",
            )

            # Detection configuration section
            with Container(classes="section"):
                yield Static(
                    "[bold]Detection Configuration[/bold]", classes="section-title"
                )

                with Horizontal(classes="setting-row"):
                    yield Label("Detector:")
                    yield Select(
                        select_options_with_default(
                            [
                                ("Heuristic (fast, local)", "heuristic"),
                                ("ML (onnxruntime model)", "ml"),
                                ("Hybrid (heuristic + ML)", "hybrid"),
                            ],
                            "prompt_injection.detector",
                        ),
                        value="heuristic",
                        id="detector-select",
                    )
                    yield Static("[dim](Press 's' to save)[/dim]")

                with Horizontal(classes="setting-row"):
                    yield Label("Sensitivity:")
                    yield Select(
                        select_options_with_default(
                            [("Low", "low"), ("Medium", "medium"), ("High", "high")],
                            "prompt_injection.sensitivity",
                        ),
                        value="medium",
                        id="sensitivity-select",
                    )
                    yield Static("[dim](Press 's' to save)[/dim]")

                with Horizontal(classes="setting-row"):
                    yield Label("Score Threshold:")
                    yield Input(
                        placeholder=default_placeholder(
                            "prompt_injection.max_score_threshold"
                        ),
                        id="score-threshold-input",
                    )
                    yield Static(
                        f"[dim]0.0-1.0 (Press Enter to save)[/dim] "
                        f"{default_indicator('prompt_injection.max_score_threshold')}"
                    )

            # Unicode Attack Detection section
            with Container(classes="section"):
                yield Static(
                    "[bold]Unicode Attack Detection[/bold]", classes="section-title"
                )
                yield Static(
                    "[dim]Detect Unicode-based attacks that bypass pattern matching[/dim]",
                    classes="setting-row",
                )

                with Horizontal(classes="setting-row"):
                    yield Label("Detect Zero-Width Chars:")
                    yield Checkbox("", id="detect-zero-width-checkbox", value=True)
                    yield Static(
                        "[dim]Invisible characters that break pattern matching[/dim]"
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("Detect Bidi Override:")
                    yield Checkbox("", id="detect-bidi-override-checkbox", value=True)
                    yield Static(
                        "[dim]Text display reversal for visual deception[/dim]"
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("Detect Tag Characters:")
                    yield Checkbox("", id="detect-tag-chars-checkbox", value=True)
                    yield Static(
                        "[dim]Hidden data encoding in deprecated Unicode tags[/dim]"
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("Detect Homoglyphs:")
                    yield Checkbox("", id="detect-homoglyphs-checkbox", value=True)
                    yield Static(
                        "[dim]Look-alike character substitution (Cyrillic/Greek)[/dim]"
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("Allow RTL Languages:")
                    yield Checkbox("", id="allow-rtl-languages-checkbox", value=True)
                    yield Static(
                        "[dim]Allow legitimate right-to-left text (Arabic, Hebrew)[/dim]"
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("Allow Emoji:")
                    yield Checkbox("", id="allow-emoji-checkbox", value=True)
                    yield Static("[dim]Allow emoji characters in prompts[/dim]")

            # Allowlist patterns section
            with Container(classes="section"):
                yield Static("[bold]Allowlist Patterns[/bold]", classes="section-title")
                yield Static(
                    "Regex patterns to ignore (e.g., for documentation):",
                    classes="setting-row",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="allowlist-patterns")
                yield Input(
                    placeholder="Enter pattern to allowlist (press 'a' to add)",
                    id="new-allowlist-input",
                )

            # Custom patterns section
            with Container(classes="section"):
                yield Static(
                    "[bold]Custom Detection Patterns[/bold]", classes="section-title"
                )
                yield Static(
                    "Additional regex patterns to detect as injection:",
                    classes="setting-row",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="custom-patterns")
                yield Input(
                    placeholder="Enter custom pattern to detect (press 'c' to add)",
                    id="new-custom-input",
                )

            # Ignore files section
            with Container(classes="section"):
                yield Static("[bold]Ignore Files[/bold]", classes="section-title")
                yield Static(
                    "[dim]Glob patterns for files to skip during prompt injection detection.[/dim]",
                    classes="section-title",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="pi-ignore-files-list")
                yield Input(
                    placeholder="Enter glob pattern (e.g. **/.claude/skills/*/SKILL.md)",
                    id="pi-ignore-file-input",
                )

            # Ignore tools section
            with Container(classes="section"):
                yield Static("[bold]Ignore Tools[/bold]", classes="section-title")
                yield Static(
                    "[dim]Tool name patterns to skip during prompt injection detection.[/dim]",
                    classes="section-title",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="pi-ignore-tools-list")
                yield Input(
                    placeholder="Enter tool pattern (e.g. Skill:code-review)",
                    id="pi-ignore-tool-input",
                )

            # Statistics section
            with Container(classes="section"):
                yield Static(
                    "[bold]Detection Statistics[/bold]", classes="section-title"
                )
                yield Static("", id="detection-stats")

    def on_mount(self) -> None:
        """Load configuration when mounted."""
        self.load_config()
        self._apply_tooltips()

    def _apply_tooltips(self) -> None:
        """Set Textual tooltips from CONFIG_FIELD_HELP on key widgets."""
        try:
            from ai_guardian.help_content import CONFIG_FIELD_HELP
        except Exception:
            return
        _tip = {
            "prompt_injection_enabled_toggle": CONFIG_FIELD_HELP.get(
                "prompt_injection"
            ),
        }
        for widget_id, help_text in _tip.items():
            if help_text:
                try:
                    self.query_one(f"#{widget_id}").tooltip = help_text
                except Exception:
                    pass

    def refresh_content(self) -> None:
        """Refresh configuration (called by parent app)."""
        self.load_config()

    def load_config(self) -> None:
        """Load and display prompt injection detection configuration."""
        config = self._load_full_config()

        # Prompt injection settings
        pi_config = config.get("prompt_injection", {})
        enabled_value = pi_config.get("enabled", True)
        detector = pi_config.get("detector", "heuristic")
        sensitivity = pi_config.get("sensitivity", "medium")
        score_threshold = pi_config.get("max_score_threshold", 0.75)
        allowlist = pi_config.get("allowlist_patterns", [])
        custom = pi_config.get("custom_patterns", [])

        # Unicode detection settings
        unicode_config = pi_config.get("unicode_detection", {})
        detect_zero_width = unicode_config.get("detect_zero_width", True)
        detect_bidi_override = unicode_config.get("detect_bidi_override", True)
        detect_tag_chars = unicode_config.get("detect_tag_chars", True)
        detect_homoglyphs = unicode_config.get("detect_homoglyphs", True)
        allow_rtl_languages = unicode_config.get("allow_rtl_languages", True)
        allow_emoji = unicode_config.get("allow_emoji", True)

        # Update widgets
        try:
            toggle = self.query_one("#prompt_injection_enabled_toggle", TimeBasedToggle)
            toggle.load_value(enabled_value)

            self.query_one("#detector-select", Select).value = detector
            self.query_one("#sensitivity-select", Select).value = sensitivity
            self.query_one("#score-threshold-input", Input).value = str(score_threshold)

            # Update unicode detection checkboxes
            self.query_one("#detect-zero-width-checkbox", Checkbox).value = (
                detect_zero_width
            )
            self.query_one("#detect-bidi-override-checkbox", Checkbox).value = (
                detect_bidi_override
            )
            self.query_one("#detect-tag-chars-checkbox", Checkbox).value = (
                detect_tag_chars
            )
            self.query_one("#detect-homoglyphs-checkbox", Checkbox).value = (
                detect_homoglyphs
            )
            self.query_one("#allow-rtl-languages-checkbox", Checkbox).value = (
                allow_rtl_languages
            )
            self.query_one("#allow-emoji-checkbox", Checkbox).value = allow_emoji
        except Exception:
            pass  # Widgets may not be fully mounted yet

        # Update allowlist patterns (supports time-based patterns)
        if allowlist:
            from datetime import datetime, timezone

            pattern_lines = []
            for pattern in allowlist:
                if isinstance(pattern, dict):
                    # Time-based pattern
                    pattern_str = pattern.get("pattern", "")
                    valid_until = pattern.get("valid_until", "")

                    if valid_until:
                        try:
                            expiry_dt = datetime.fromisoformat(
                                valid_until.replace("Z", "+00:00")
                            )
                            now = datetime.now(timezone.utc)

                            if expiry_dt <= now:
                                # Expired
                                pattern_lines.append(
                                    f"  • {pattern_str} [status-error][EXPIRED][/status-error]"
                                )
                            else:
                                # Check if expiring soon (within 24 hours)
                                time_remaining = expiry_dt - now
                                if time_remaining.total_seconds() < 86400:  # 24 hours
                                    pattern_lines.append(
                                        f"  • {pattern_str} [status-warn][expires {format_local_time(valid_until)}][/status-warn]"
                                    )
                                else:
                                    pattern_lines.append(
                                        f"  • {pattern_str} [dim][until {format_local_time(valid_until)}][/dim]"
                                    )
                        except Exception:
                            pattern_lines.append(
                                f"  • {pattern_str} [dim][until {format_local_time(valid_until)}][/dim]"
                            )
                    else:
                        pattern_lines.append(f"  • {pattern_str}")
                else:
                    # Simple string pattern
                    pattern_lines.append(f"  • {pattern}")

            patterns_text = "\n".join(pattern_lines)
        else:
            patterns_text = "[dim]No allowlist patterns configured[/dim]"
        self.query_one("#allowlist-patterns", Static).update(patterns_text)

        # Update custom patterns
        if custom:
            custom_text = "\n".join(f"  • {pattern}" for pattern in custom)
        else:
            custom_text = "[dim]No custom patterns configured[/dim]"
        self.query_one("#custom-patterns", Static).update(custom_text)

        # Update ignore files list
        ignore_files = pi_config.get("ignore_files", [])
        try:
            if ignore_files:
                ignore_files_text = "\n".join(f"  {f}" for f in ignore_files)
            else:
                ignore_files_text = "[dim]No ignore patterns configured[/dim]"
            self.query_one("#pi-ignore-files-list", Static).update(ignore_files_text)
        except Exception:
            pass

        # Update ignore tools list
        ignore_tools = pi_config.get("ignore_tools", [])
        try:
            if ignore_tools:
                ignore_tools_text = "\n".join(f"  {t}" for t in ignore_tools)
            else:
                ignore_tools_text = "[dim]No ignored tools configured[/dim]"
            self.query_one("#pi-ignore-tools-list", Static).update(ignore_tools_text)
        except Exception:
            pass

        self._apply_default_indicators(pi_config)

        # Get violation stats
        from ai_guardian.violations.logger import ViolationLogger

        violation_logger = ViolationLogger()
        violations = violation_logger.get_recent_violations(
            limit=1000, violation_type="prompt_injection", resolved=None
        )
        total = len(violations)
        unresolved = len([v for v in violations if not v.get("resolved", False)])

        stats_text = (
            f"Total prompt injection violations: {total}\nUnresolved: {unresolved}"
        )
        self.query_one("#detection-stats", Static).update(stats_text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press - save toggle state immediately."""
        bid = event.button.id
        if bid and "prompt_injection_enabled" in bid:
            toggle = self.query_one("#prompt_injection_enabled_toggle", TimeBasedToggle)
            if toggle.current_mode == "temp_disabled":
                return
            value = toggle.get_value()
            self.save_field("enabled", value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields."""
        input_id = event.input.id

        # Handle TimeBasedToggle inputs
        if input_id and "prompt_injection_enabled" in input_id:
            toggle = self.query_one("#prompt_injection_enabled_toggle", TimeBasedToggle)
            value = toggle.get_value()
            self.save_field("enabled", value)
        elif event.input.id == "score-threshold-input":
            try:
                threshold = float(event.value)
                if 0.0 <= threshold <= 1.0:
                    self.save_field("max_score_threshold", threshold)
                else:
                    self.app.notify(
                        "Threshold must be between 0.0 and 1.0", severity="error"
                    )
            except ValueError:
                self.app.notify("Threshold must be a number", severity="error")
        elif event.input.id == "new-allowlist-input":
            self.add_allowlist_pattern()
        elif event.input.id == "new-custom-input":
            self.add_custom_pattern()
        elif event.input.id == "pi-ignore-file-input":
            self._add_ignore_item("ignore_files", event.input)
        elif event.input.id == "pi-ignore-tool-input":
            self._add_ignore_item("ignore_tools", event.input)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox changes - save unicode detection settings immediately."""
        checkbox_id = event.checkbox.id

        # Map checkbox IDs to config keys
        unicode_setting_map = {
            "detect-zero-width-checkbox": "detect_zero_width",
            "detect-bidi-override-checkbox": "detect_bidi_override",
            "detect-tag-chars-checkbox": "detect_tag_chars",
            "detect-homoglyphs-checkbox": "detect_homoglyphs",
            "allow-rtl-languages-checkbox": "allow_rtl_languages",
            "allow-emoji-checkbox": "allow_emoji",
        }

        if checkbox_id in unicode_setting_map:
            config_key = unicode_setting_map[checkbox_id]
            self.save_unicode_detection_field(config_key, event.value)

    def action_update_sensitivity(self) -> None:
        """Update sensitivity and detector settings (triggered by 's' key)."""
        self.update_settings()

    def action_add_pattern(self) -> None:
        """Add allowlist pattern (triggered by 'a' key)."""
        self.add_allowlist_pattern()

    def action_add_custom(self) -> None:
        """Add custom pattern (triggered by 'c' key)."""
        self.add_custom_pattern()

    def action_refresh(self) -> None:
        """Refresh configuration (triggered by 'r' key)."""
        self.load_config()
        self.app.notify(
            "Prompt injection configuration refreshed", severity="information"
        )

    def save_field(self, field: str, value) -> None:
        """Save a prompt injection field to config."""
        try:
            config = self._load_full_config()

            if "prompt_injection" not in config:
                config["prompt_injection"] = {}

            config["prompt_injection"][field] = value

            self._write_full_config(config)

            self.app.notify(f"✓ Saved {field}", severity="success")

        except Exception as e:
            self.app.notify(f"Error saving {field}: {e}", severity="error")

    def save_unicode_detection_field(self, field: str, value: bool) -> None:
        """Save a unicode detection field to config."""
        try:
            config = self._load_full_config()

            if "prompt_injection" not in config:
                config["prompt_injection"] = {}

            if "unicode_detection" not in config["prompt_injection"]:
                config["prompt_injection"]["unicode_detection"] = {}

            config["prompt_injection"]["unicode_detection"][field] = value

            self._write_full_config(config)

            # Convert field name to human-readable
            field_name = field.replace("_", " ").title()
            self.app.notify(
                f"✓ Unicode detection: {field_name} = {value}", severity="success"
            )

        except Exception as e:
            self.app.notify(
                f"Error saving unicode detection {field}: {e}", severity="error"
            )

    def update_settings(self) -> None:
        """Update detector and sensitivity settings."""
        detector = self.query_one("#detector-select", Select).value
        sensitivity = self.query_one("#sensitivity-select", Select).value

        try:
            config = self._load_full_config()

            if "prompt_injection" not in config:
                config["prompt_injection"] = {}

            config["prompt_injection"]["detector"] = detector
            config["prompt_injection"]["sensitivity"] = sensitivity

            self._write_full_config(config)

            self.load_config()
            self.app.notify(
                f"✓ Updated detector: {detector}, sensitivity: {sensitivity}",
                severity="success",
            )

        except Exception as e:
            self.app.notify(f"Error updating settings: {e}", severity="error")

    def add_allowlist_pattern(self) -> None:
        """Add a pattern to the allowlist."""
        pattern = self.query_one("#new-allowlist-input", Input).value.strip()

        if not pattern:
            self.app.notify("Please enter a pattern", severity="error")
            return

        try:
            config = self._load_full_config()

            if "prompt_injection" not in config:
                config["prompt_injection"] = {}

            if "allowlist_patterns" not in config["prompt_injection"]:
                config["prompt_injection"]["allowlist_patterns"] = []

            # Check if pattern already exists
            if pattern in config["prompt_injection"]["allowlist_patterns"]:
                self.app.notify("Pattern already in allowlist", severity="warning")
                return

            config["prompt_injection"]["allowlist_patterns"].append(pattern)

            self._write_full_config(config)

            # Clear input
            self.query_one("#new-allowlist-input", Input).value = ""

            self.load_config()
            self.app.notify(
                f"✓ Added pattern to allowlist: {pattern}", severity="success"
            )

        except Exception as e:
            self.app.notify(f"Error adding pattern: {e}", severity="error")

    def add_custom_pattern(self) -> None:
        """Add a custom detection pattern."""
        pattern = self.query_one("#new-custom-input", Input).value.strip()

        if not pattern:
            self.app.notify("Please enter a pattern", severity="error")
            return

        try:
            config = self._load_full_config()

            if "prompt_injection" not in config:
                config["prompt_injection"] = {}

            if "custom_patterns" not in config["prompt_injection"]:
                config["prompt_injection"]["custom_patterns"] = []

            # Check if pattern already exists
            if pattern in config["prompt_injection"]["custom_patterns"]:
                self.app.notify("Pattern already exists", severity="warning")
                return

            config["prompt_injection"]["custom_patterns"].append(pattern)

            self._write_full_config(config)

            # Clear input
            self.query_one("#new-custom-input", Input).value = ""

            self.load_config()
            self.app.notify(f"✓ Added custom pattern: {pattern}", severity="success")

        except Exception as e:
            self.app.notify(f"Error adding pattern: {e}", severity="error")

    def _add_ignore_item(self, field: str, input_widget: Input) -> None:
        """Add an item to prompt_injection.ignore_files or ignore_tools."""
        value = input_widget.value.strip()
        if not value:
            self.app.notify("Please enter a pattern", severity="error")
            return

        try:
            config = self._load_full_config()

            if "prompt_injection" not in config:
                config["prompt_injection"] = {}
            if field not in config["prompt_injection"]:
                config["prompt_injection"][field] = []

            if value in config["prompt_injection"][field]:
                self.app.notify("Pattern already exists", severity="warning")
                return

            config["prompt_injection"][field].append(value)

            self._write_full_config(config)

            input_widget.value = ""
            self.load_config()
            self.app.notify(f"Added: {value}", severity="success")

        except Exception as e:
            self.app.notify(f"Error adding pattern: {e}", severity="error")
