#!/usr/bin/env python3
"""
Secrets Tab Content

View secret detection settings and manage configuration.
"""

import json
from pathlib import Path
from typing import Union, Dict, Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static, Button, Input, Label, Checkbox, Select

from ai_guardian.tui.schema_defaults import (
    ConfigSaveMixin,
    default_indicator,
    default_placeholder,
)
from ai_guardian.tui.widgets import (
    TimeBasedToggle,
    sanitize_enabled_value,
    format_local_time,
)


class SecretsContent(ConfigSaveMixin, Container):
    """Content widget for Secrets tab."""

    CONFIG_SECTION = "secret_scanning"

    _PRIVACY_WARNING = (
        "[bold yellow]⚠ Privacy Warning:[/bold yellow] "
        "[yellow]Detected secrets will be sent to external provider "
        "APIs for liveness validation. This happens automatically on "
        "every detection. By enabling this feature you consent to "
        "outbound network calls with sensitive data.[/yellow]"
    )

    CSS = """
    SecretsContent {
        height: 100%;
    }

    #secrets-header {
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
        align: left middle;
    }

    .list-scroll {
        max-height: 10;
        margin: 1 0;
        background: $surface;
        border: solid $primary;
    }

    #secret-allowlist-patterns {
        padding: 1;
        min-height: 2;
    }

    .setting-row Label {
        margin: 0 2 0 0;
        width: 20;
        content-align: right middle;
    }

    .setting-row Input {
        width: 50;
        margin: 0 2 0 0;
    }

    .setting-row Checkbox {
        margin: 0 2 0 0;
    }

    .setting-row Static {
        margin: 0 1 0 0;
    }

    .setting-row Button {
        margin: 0 1 0 0;
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

    Checkbox:focus {
        border-left: heavy $accent;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the secrets tab content."""
        yield Static("[bold]Secret Detection Settings[/bold]", id="secrets-header")

        with VerticalScroll():
            # Secret scanning enable/disable toggle
            yield TimeBasedToggle(
                title="🔍 Secret Scanning",
                config_key="secret_scanning_enabled",
                current_value=True,
                help_text="Controls whether AI Guardian scans for secrets using the configured scanner engine. When disabled, no secret detection is performed. (default: enabled)",
                id="secret_scanning_enabled_toggle",
                classes="section",
            )

            # Gitleaks section
            with Container(classes="section"):
                yield Static("[bold]Scanner Engine[/bold]", classes="section-title")
                yield Static("", id="gitleaks-status")
                yield Static(
                    "[dim]Detection sources (in priority order):\n"
                    "  1. Per-engine pattern server (if configured on Engine Config page)\n"
                    "  2. Project-specific: .gitleaks.toml (if exists)\n"
                    "  3. Built-in: Gitleaks default rules (AWS, GitHub, SSH keys, etc.)[/dim]",
                    id="gitleaks-config",
                )

            # Allowlist patterns section (Issue #357)
            with Container(classes="section"):
                yield Static("[bold]Allowlist Patterns[/bold]", classes="section-title")
                yield Static(
                    "[dim]Regex patterns for known-safe secret values to ignore "
                    "(e.g., test API key prefixes, example tokens). "
                    "Unlike ignore_files, this keeps scanning but skips matching values.[/dim]",
                    classes="section-title",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="secret-allowlist-patterns")
                yield Input(
                    placeholder="Enter regex pattern (e.g., pk_test_[A-Za-z0-9]{24,})",
                    id="secret-allowlist-input",
                )

            # False Positive Filtering section (Issue #1091)
            with Container(classes="section"):
                yield Static(
                    "[bold]False Positive Filtering[/bold]", classes="section-title"
                )
                yield Static(
                    "[dim]Entropy and stopword filters to reduce false positives. "
                    "Higher entropy = more random = more likely a real secret.[/dim]",
                    classes="section-title",
                )

                with Horizontal(classes="setting-row"):
                    yield Label("Min Entropy:")
                    yield Input(placeholder="disabled (null)", id="min-entropy-input")
                    yield Static(
                        "[dim]0.0-8.0, recommended 3.0 (Press Enter to save)[/dim]"
                    )

                yield Static("", id="entropy-info")

                yield Static("[bold]Stopwords[/bold]", classes="section-title")
                yield Static(
                    "[dim]Matched secrets containing these words are suppressed (case-insensitive). "
                    "User words are merged with bundled stopwords — bundled words cannot be removed.[/dim]",
                    classes="section-title",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="stopwords-display")
                yield Input(
                    placeholder="Enter stopword (min 3 chars)",
                    id="stopwords-input",
                )

            # Ignore files section
            with Container(classes="section"):
                yield Static("[bold]Ignore Files[/bold]", classes="section-title")
                yield Static(
                    "[dim]Glob patterns for files to skip during secret scanning.[/dim]",
                    classes="section-title",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="secret-ignore-files-list")
                yield Input(
                    placeholder="Enter glob pattern (e.g. **/tests/fixtures/**)",
                    id="secret-ignore-file-input",
                )

            # Ignore tools section
            with Container(classes="section"):
                yield Static("[bold]Ignore Tools[/bold]", classes="section-title")
                yield Static(
                    "[dim]Tool name patterns to skip during secret scanning.[/dim]",
                    classes="section-title",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="secret-ignore-tools-list")
                yield Input(
                    placeholder="Enter tool pattern (e.g. mcp__*)",
                    id="secret-ignore-tool-input",
                )

            # Secret Validation section (Issue #976)
            with Container(classes="section"):
                yield Static("[bold]Secret Validation[/bold]", classes="section-title")
                yield Static(
                    "[dim]Validate detected secrets against provider APIs to check "
                    "if they are still active. Inactive secrets produce a warning "
                    "instead of blocking.[/dim]",
                    classes="section-title",
                )

                with Horizontal(classes="setting-row"):
                    yield Label("Validate Secrets:")
                    yield Checkbox("", id="validate-secrets-checkbox", value=False)
                    yield Static(
                        f"[dim]Enable secret liveness validation (opt-in)[/dim] "
                        f"{default_indicator('secret_scanning.validate_secrets')}"
                    )

                yield Static(
                    "",
                    id="validate-secrets-privacy-warning",
                )

                with Horizontal(classes="setting-row"):
                    yield Label("Timeout (ms):")
                    yield Input(
                        placeholder=default_placeholder(
                            "secret_scanning.validation_timeout_ms"
                        ),
                        id="validation-timeout-ms",
                    )
                    yield Static(
                        f"[dim]Per-secret HTTP timeout (500-30000, Press Enter to save)[/dim] "
                        f"{default_indicator('secret_scanning.validation_timeout_ms')}"
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("On Inactive:")
                    yield Select(
                        [
                            ("Warn — log warning, skip block", "warn"),
                            ("Allow — silently skip", "allow"),
                        ],
                        value="warn",
                        id="on-inactive-select",
                    )
                    yield Static(
                        f"[dim]Action for revoked/expired secrets[/dim] "
                        f"{default_indicator('secret_scanning.on_inactive')}"
                    )

    def on_mount(self) -> None:
        """Load configuration when mounted."""
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
            "min-entropy-input": CONFIG_FIELD_HELP.get("secret_scanning.entropy"),
            "stopwords-input": CONFIG_FIELD_HELP.get("secret_scanning.stopwords"),
            "validate-secrets-checkbox": CONFIG_FIELD_HELP.get(
                "secret_scanning.validate_secrets"
            ),
            "secret_scanning_enabled_toggle": CONFIG_FIELD_HELP.get("secret_scanning"),
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
        """Load and display secret detection configuration."""
        self._loading = True
        try:
            self._load_config_inner()
        finally:
            self._loading = False

    def _load_config_inner(self) -> None:
        """Inner config loading (guarded by _loading flag)."""
        config_path = self._get_config_path()

        # Load config
        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                self.app.notify(f"Error loading config: {e}", severity="error")

        secret_scanning = config.get("secret_scanning", {})

        # Load secret_scanning.enabled toggle
        scanning_enabled = secret_scanning.get("enabled", True)
        try:
            ss_toggle = self.query_one(
                "#secret_scanning_enabled_toggle", TimeBasedToggle
            )
            ss_toggle.load_value(scanning_enabled)
        except Exception:
            pass

        # Gitleaks status - check for project config
        project_config = Path.cwd() / ".gitleaks.toml"
        if project_config.exists():
            gitleaks_status = (
                f"[status-ok]✓[/status-ok] Using project config: {project_config}"
            )
        else:
            gitleaks_status = "[status-ok]✓[/status-ok] Using Gitleaks built-in rules"

        self.query_one("#gitleaks-status", Static).update(gitleaks_status)

        # Allowlist patterns (Issue #357)
        allowlist = secret_scanning.get("allowlist_patterns", [])
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
            self.query_one("#secret-allowlist-patterns", Static).update(allowlist_text)
        except Exception:
            pass

        # False positive filtering (Issue #1091)
        min_entropy = secret_scanning.get("min_entropy")
        user_stopwords = secret_scanning.get("stopwords", [])

        try:
            entropy_input = self.query_one("#min-entropy-input", Input)
            if min_entropy is not None:
                entropy_input.value = str(min_entropy)
            else:
                entropy_input.value = ""

            entropy_info = self.query_one("#entropy-info", Static)
            entropy_info.update(
                "[dim]Entropy scale: 0.0 = identical chars (XXXX) │ "
                "~1.0 = two chars (abab) │ ~3.3 = lowercase │ "
                "~4.7 = alphanumeric │ Real API keys: 4.0+[/dim]"
            )

            from ai_guardian.patterns import BUNDLED_FILES

            bundled_path = BUNDLED_FILES.get("stopwords")
            bundled_count = 0
            if bundled_path and bundled_path.exists():
                try:
                    import sys

                    if sys.version_info >= (3, 11):
                        import tomllib
                    else:
                        import tomli as tomllib
                    with open(bundled_path, "rb") as pattern_file:
                        data = tomllib.load(pattern_file)
                    bundled_count = len(data.get("stopwords", {}).get("words", []))
                except Exception:
                    pass  # intentionally silent — optional dependency

            if user_stopwords:
                sw_lines = [f"  {w}" for w in user_stopwords]
                sw_text = (
                    f"[dim]Bundled: {bundled_count} words (always active)[/dim]\n"
                    f"User-added ({len(user_stopwords)}):\n" + "\n".join(sw_lines)
                )
            else:
                sw_text = (
                    f"[dim]Bundled: {bundled_count} words (always active)\n"
                    f"No user-added stopwords[/dim]"
                )
            self.query_one("#stopwords-display", Static).update(sw_text)
        except Exception:
            pass

        # Ignore files list
        ignore_files = secret_scanning.get("ignore_files", [])
        try:
            if ignore_files:
                ignore_files_text = "\n".join(f"  {f}" for f in ignore_files)
            else:
                ignore_files_text = "[dim]No ignore patterns configured[/dim]"
            self.query_one("#secret-ignore-files-list", Static).update(
                ignore_files_text
            )
        except Exception:
            pass

        # Ignore tools list
        ignore_tools = secret_scanning.get("ignore_tools", [])
        try:
            if ignore_tools:
                ignore_tools_text = "\n".join(f"  {t}" for t in ignore_tools)
            else:
                ignore_tools_text = "[dim]No ignored tools configured[/dim]"
            self.query_one("#secret-ignore-tools-list", Static).update(
                ignore_tools_text
            )
        except Exception:
            pass

        # Secret validation settings (Issue #976)
        validate_on = secret_scanning.get("validate_secrets", False)
        timeout_ms = secret_scanning.get("validation_timeout_ms", 3000)
        on_inactive = secret_scanning.get("on_inactive", "warn")

        try:
            self.query_one("#validate-secrets-checkbox", Checkbox).value = bool(
                validate_on
            )
            self.query_one("#validation-timeout-ms", Input).value = str(timeout_ms)
            self.query_one("#on-inactive-select", Select).value = on_inactive
        except Exception:
            pass  # Widgets may not be mounted yet

        # Privacy warning — visible only when validation is enabled
        try:
            warning_widget = self.query_one("#validate-secrets-privacy-warning", Static)
            if validate_on:
                warning_widget.update(self._PRIVACY_WARNING)
            else:
                warning_widget.update("")
        except Exception:
            pass

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox toggle."""
        if event.checkbox.id == "validate-secrets-checkbox":
            self._save_secret_scanning_field("validate_secrets", event.value)
            # Update privacy warning visibility
            try:
                warning_widget = self.query_one(
                    "#validate-secrets-privacy-warning", Static
                )
                if event.value:
                    warning_widget.update(self._PRIVACY_WARNING)
                else:
                    warning_widget.update("")
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press in TimeBasedToggle - save immediately."""
        if getattr(self, "_loading", False):
            return
        bid = event.button.id

        if bid and "secret_scanning_enabled" in bid:
            toggle = self.query_one("#secret_scanning_enabled_toggle", TimeBasedToggle)
            if toggle.current_mode == "temp_disabled":
                return
            self._save_secret_scanning_enabled(toggle.get_value())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields - save the value."""
        if getattr(self, "_loading", False):
            return
        input_id = event.input.id

        # Handle secret_scanning_enabled toggle inputs
        if input_id and "secret_scanning_enabled" in input_id:
            toggle = self.query_one("#secret_scanning_enabled_toggle", TimeBasedToggle)
            self._save_secret_scanning_enabled(toggle.get_value())
            return

        if event.input.id == "validation-timeout-ms":
            try:
                val = int(event.value)
                if val < 500 or val > 30000:
                    self.app.notify(
                        "Timeout must be between 500 and 30000 ms",
                        severity="error",
                    )
                    return
                self._save_secret_scanning_field("validation_timeout_ms", val)
            except ValueError:
                self.app.notify("Timeout must be a number", severity="error")
        elif event.input.id == "secret-allowlist-input":
            self._add_allowlist_pattern()
        elif event.input.id == "min-entropy-input":
            raw = event.value.strip()
            if not raw or raw.lower() in ("null", "none", "disabled"):
                self._save_secret_scanning_field("min_entropy", None)
            else:
                try:
                    entropy_value = float(raw)
                    if entropy_value < 0 or entropy_value > 8:
                        self.app.notify(
                            "Entropy must be between 0.0 and 8.0",
                            severity="error",
                        )
                        return
                    self._save_secret_scanning_field("min_entropy", val)
                except ValueError:
                    self.app.notify(
                        "Entropy must be a number or empty to disable", severity="error"
                    )
        elif event.input.id == "stopwords-input":
            self._add_stopword()
        elif event.input.id == "secret-ignore-file-input":
            self._add_ignore_item("ignore_files", event.input)
        elif event.input.id == "secret-ignore-tool-input":
            self._add_ignore_item("ignore_tools", event.input)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle select dropdown changes."""
        if getattr(self, "_loading", False):
            return
        if event.select.id == "on-inactive-select":
            if event.value is not Select.BLANK:
                self._save_secret_scanning_field("on_inactive", event.value)

    def action_refresh(self) -> None:
        """Refresh configuration (triggered by 'r' key)."""
        self.load_config()
        self.app.notify("Secrets configuration refreshed", severity="information")

    def _save_secret_scanning_enabled(self, value: Union[bool, Dict[str, Any]]) -> None:
        """Save secret_scanning.enabled to config."""
        try:
            sanitized = sanitize_enabled_value(value)
            if not self._save_config_field("enabled", value):
                self.app.notify("Error saving config", severity="error")
                return

            value = sanitized
            if isinstance(value, bool):
                status = "enabled" if value else "disabled"
                self.app.notify(f"✓ Secret scanning {status}", severity="success")
            else:
                if value.get("disabled_until"):
                    self.app.notify(
                        f"✓ Secret scanning temporarily disabled until {format_local_time(value['disabled_until'])}",
                        severity="success",
                    )
                else:
                    self.app.notify("✓ Secret scanning disabled", severity="success")

        except Exception as e:
            self.app.notify(f"Error saving config: {e}", severity="error")

    def _save_secret_scanning_field(self, field: str, value) -> None:
        """Save a field under secret_scanning to config."""
        if self._save_config_field(field, value):
            self.app.notify(f"\u2713 Saved {field}", severity="success")
        else:
            self.app.notify(f"Error saving {field}", severity="error")

    def _add_allowlist_pattern(self) -> None:
        """Add a regex pattern to the secret scanning allowlist."""
        input_widget = self.query_one("#secret-allowlist-input", Input)
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
            config = self._load_full_config()
            if "secret_scanning" not in config:
                config["secret_scanning"] = {}
            if "allowlist_patterns" not in config["secret_scanning"]:
                config["secret_scanning"]["allowlist_patterns"] = []

            if pattern in config["secret_scanning"]["allowlist_patterns"]:
                self.app.notify("Pattern already in allowlist", severity="warning")
                return

            config["secret_scanning"]["allowlist_patterns"].append(pattern)
            self._write_full_config(config)

            input_widget.value = ""
            self.load_config()
            self.app.notify(f"Added allowlist pattern: {pattern}", severity="success")

        except Exception as e:
            self.app.notify(f"Error adding pattern: {e}", severity="error")

    def _add_stopword(self) -> None:
        """Add a stopword to the secret scanning stopwords list."""
        input_widget = self.query_one("#stopwords-input", Input)
        word = input_widget.value.strip().lower()

        if not word:
            self.app.notify("Please enter a stopword", severity="error")
            return

        if len(word) < 3:
            self.app.notify("Stopword must be at least 3 characters", severity="error")
            return

        try:
            config = self._load_full_config()
            if "secret_scanning" not in config:
                config["secret_scanning"] = {}
            if "stopwords" not in config["secret_scanning"]:
                config["secret_scanning"]["stopwords"] = []

            existing = [w.lower() for w in config["secret_scanning"]["stopwords"]]
            if word in existing:
                self.app.notify("Stopword already added", severity="warning")
                return

            config["secret_scanning"]["stopwords"].append(word)
            self._write_full_config(config)

            input_widget.value = ""
            self.load_config()
            self.app.notify(f"Added stopword: {word}", severity="success")

        except Exception as e:
            self.app.notify(f"Error adding stopword: {e}", severity="error")

    def _add_ignore_item(self, field: str, input_widget: Input) -> None:
        """Add an item to secret_scanning.ignore_files or ignore_tools."""
        value = input_widget.value.strip()
        if not value:
            self.app.notify("Please enter a pattern", severity="error")
            return

        try:
            config = self._load_full_config()
            if "secret_scanning" not in config:
                config["secret_scanning"] = {}
            if field not in config["secret_scanning"]:
                config["secret_scanning"][field] = []

            if value in config["secret_scanning"][field]:
                self.app.notify("Pattern already exists", severity="warning")
                return

            config["secret_scanning"][field].append(value)
            self._write_full_config(config)

            input_widget.value = ""
            self.load_config()
            self.app.notify(f"Added: {value}", severity="success")

        except Exception as e:
            self.app.notify(f"Error adding pattern: {e}", severity="error")
