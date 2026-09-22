#!/usr/bin/env python3
"""
SSRF Protection Tab Content

View and configure SSRF (Server-Side Request Forgery) protection settings.
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


class SSRFContent(ConfigSaveMixin, SchemaDefaultsMixin, Container):
    """Content widget for SSRF Protection tab."""

    SCHEMA_SECTION = "ssrf_protection"
    SCHEMA_FIELDS = [
        ("action-select", "action", "select"),
        ("allow-localhost-checkbox", "allow_localhost", "checkbox"),
    ]
    CONFIG_SECTION = "ssrf_protection"

    CSS = """
    SSRFContent {
        height: 100%;
    }

    #ssrf-header {
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

    #blocked-ips-list, #blocked-domains-list, #allowed-domains-list {
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
        """Compose the SSRF protection tab content."""
        yield Static("[bold]SSRF Protection Settings[/bold]", id="ssrf-header")

        with VerticalScroll():
            # Protection toggle section (standalone)
            yield TimeBasedToggle(
                title="SSRF Protection",
                config_key="ssrf_protection_enabled",
                current_value=True,
                help_text="Prevents AI agents from accessing private networks, metadata endpoints, and dangerous URL schemes",
                id="ssrf_protection_enabled_toggle",
            )

            # Core protections info section
            with Container(classes="section"):
                yield Static(
                    "[bold]Core Protections (Immutable)[/bold]", classes="section-title"
                )
                yield Static(
                    "[dim]The following protections CANNOT be disabled:\n\n"
                    "Private IP Ranges (RFC 1918):\n"
                    "  • 10.0.0.0/8 (Private network)\n"
                    "  • 172.16.0.0/12 (Private network)\n"
                    "  • 192.168.0.0/16 (Private network)\n"
                    "  • 127.0.0.0/8 (Loopback)\n"
                    "  • 169.254.0.0/16 (Link-local, AWS metadata)\n"
                    "  • ::1/128 (IPv6 loopback)\n"
                    "  • fc00::/7 (IPv6 private)\n"
                    "  • fe80::/10 (IPv6 link-local)\n\n"
                    "Cloud Metadata Endpoints:\n"
                    "  • 169.254.169.254 (AWS/Azure metadata)\n"
                    "  • metadata.google.internal (GCP)\n"
                    "  • fd00:ec2::254 (AWS IPv6)\n\n"
                    "Dangerous URL Schemes:\n"
                    "  • file://, gopher://, ftp://, data://, dict://, ldap://[/dim]",
                    id="core-protections",
                )

            # Action mode section
            with Container(classes="section"):
                yield Static(
                    "[bold]Action on SSRF Detection[/bold]", classes="section-title"
                )

                with Horizontal(classes="setting-row"):
                    yield Label("Action Mode:")
                    yield Select(
                        select_options_with_default(
                            [
                                ("Block", "block"),
                                ("Ask (block if headless)", "ask"),
                                ("Ask (warn if headless)", "ask:warn"),
                                ("Ask (log-only if headless)", "ask:log-only"),
                                ("Warn (allow but notify)", "warn"),
                                ("Log Only (silent)", "log-only"),
                            ],
                            "ssrf_protection.action",
                        ),
                        value="block",
                        id="action-select",
                    )
                    yield Static("[dim](Press 's' to save)[/dim]")

                yield Static(
                    "[dim]  • Block: Prevents execution (recommended)\n"
                    "  • Ask: Prompts user to Allow Once, Allow Always, or Block\n"
                    "  • Warn: Logs violation and shows warning, but allows execution\n"
                    "  • Log Only: Logs violation silently without user warning\n"
                    "  Note: Immutable protections (private IPs, dangerous schemes) always block[/dim]",
                    classes="setting-row",
                )

            # Local development section
            with Container(classes="section"):
                yield Static(
                    "[bold]Local Development Options[/bold]", classes="section-title"
                )

                with Horizontal(classes="setting-row"):
                    yield Label("Allow Localhost:")
                    yield Checkbox("", id="allow-localhost-checkbox", value=False)
                    yield Static(
                        f"[dim]Enable to allow localhost (127.0.0.1, ::1) access for local dev/testing[/dim] "
                        f"{default_indicator('ssrf_protection.allow_localhost')}"
                    )

            # Additional blocked IPs section
            with Container(classes="section"):
                yield Static(
                    "[bold]Additional Blocked IPs[/bold]", classes="section-title"
                )
                yield Static(
                    "Additional IP addresses or CIDR ranges to block:",
                    classes="setting-row",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="blocked-ips-list")
                yield Input(
                    placeholder="Enter IP/CIDR to block (e.g., 203.0.113.0/24)",
                    id="new-blocked-ip-input",
                )
                yield Static(
                    "[dim]Press 'i' to add IP/CIDR[/dim]", classes="setting-row"
                )

            # Additional blocked domains section
            with Container(classes="section"):
                yield Static(
                    "[bold]Additional Blocked Domains[/bold]", classes="section-title"
                )
                yield Static("Additional domain names to block:", classes="setting-row")
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="blocked-domains-list")
                yield Input(
                    placeholder="Enter domain to block (e.g., internal.example.com)",
                    id="new-blocked-domain-input",
                )
                yield Static(
                    "[dim]Press 'd' to add domain[/dim]", classes="setting-row"
                )

            # Allowed domains section (NEW in v1.5.0 - Issue #252)
            with Container(classes="section"):
                yield Static(
                    "[bold]Allowed Domains (Override Deny-List)[/bold]",
                    classes="section-title",
                )
                yield Static(
                    "Domains that override additional_blocked_domains (deny-first approach):",
                    classes="setting-row",
                )
                yield Static(
                    "[dim]⚠️  Cannot override immutable protections (metadata endpoints, private IPs, dangerous schemes)[/dim]",
                    classes="setting-row",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="allowed-domains-list")
                yield Input(
                    placeholder="Enter domain to allow (e.g., api.corp.internal)",
                    id="new-allowed-domain-input",
                )
                yield Static(
                    "[dim]Press 'a' to add allowed domain[/dim]", classes="setting-row"
                )

            # Ignore files section
            with Container(classes="section"):
                yield Static("[bold]Ignore Files[/bold]", classes="section-title")
                yield Static(
                    "[dim]Glob patterns for files to skip during SSRF checks.[/dim]",
                    classes="section-title",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="ssrf-ignore-files-list")
                yield Input(
                    placeholder="Enter glob pattern (e.g. **/tests/**)",
                    id="ssrf-ignore-file-input",
                )

            # Ignore tools section
            with Container(classes="section"):
                yield Static("[bold]Ignore Tools[/bold]", classes="section-title")
                yield Static(
                    "[dim]Tool name patterns to skip during SSRF checks.[/dim]",
                    classes="section-title",
                )
                with VerticalScroll(classes="list-scroll"):
                    yield Static("", id="ssrf-ignore-tools-list")
                yield Input(
                    placeholder="Enter tool pattern (e.g. mcp__*)",
                    id="ssrf-ignore-tool-input",
                )

            # Statistics section
            with Container(classes="section"):
                yield Static(
                    "[bold]Detection Statistics[/bold]", classes="section-title"
                )
                yield Static("", id="ssrf-stats")

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
            "ssrf_protection_enabled_toggle": CONFIG_FIELD_HELP.get("ssrf_protection"),
            "action-select": CONFIG_FIELD_HELP.get("ssrf_protection"),
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
        """Load and display SSRF protection configuration."""
        self._loading = True
        try:
            self._load_config_inner()
        finally:
            self._loading = False

    def _load_config_inner(self) -> None:
        """Inner load logic for SSRF protection configuration."""
        config_path = self._get_config_path()

        # Load config
        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                self.app.notify(f"Error loading config: {e}", severity="error")

        # SSRF protection settings
        ssrf_config = config.get("ssrf_protection", {})
        enabled_value = ssrf_config.get("enabled", True)
        action = ssrf_config.get("action", "block")
        allow_localhost = ssrf_config.get("allow_localhost", False)
        blocked_ips = ssrf_config.get("additional_blocked_ips", [])
        blocked_domains = ssrf_config.get("additional_blocked_domains", [])
        allowed_domains = ssrf_config.get("allowed_domains", [])

        # Update widgets
        try:
            toggle = self.query_one("#ssrf_protection_enabled_toggle", TimeBasedToggle)
            toggle.load_value(enabled_value)

            self.query_one("#action-select", Select).value = action
            self.query_one("#allow-localhost-checkbox", Checkbox).value = (
                allow_localhost
            )
        except Exception:
            pass  # Widgets may not be fully mounted yet

        # Update blocked IPs list
        if blocked_ips:
            ips_text = "\n".join([f"  • {ip}" for ip in blocked_ips])
        else:
            ips_text = "[dim]No additional IPs blocked[/dim]"
        self.query_one("#blocked-ips-list", Static).update(ips_text)

        # Update blocked domains list
        if blocked_domains:
            domains_text = "\n".join([f"  • {domain}" for domain in blocked_domains])
        else:
            domains_text = "[dim]No additional domains blocked[/dim]"
        self.query_one("#blocked-domains-list", Static).update(domains_text)

        # Update allowed domains list
        if allowed_domains:
            allowed_text = "\n".join([f"  • {domain}" for domain in allowed_domains])
        else:
            allowed_text = "[dim]No domains in allow-list[/dim]"
        self.query_one("#allowed-domains-list", Static).update(allowed_text)

        # Update ignore files list
        ignore_files = ssrf_config.get("ignore_files", [])
        try:
            if ignore_files:
                ignore_files_text = "\n".join(f"  {f}" for f in ignore_files)
            else:
                ignore_files_text = "[dim]No ignore patterns configured[/dim]"
            self.query_one("#ssrf-ignore-files-list", Static).update(ignore_files_text)
        except Exception:
            pass

        # Update ignore tools list
        ignore_tools = ssrf_config.get("ignore_tools", [])
        try:
            if ignore_tools:
                ignore_tools_text = "\n".join(f"  {t}" for t in ignore_tools)
            else:
                ignore_tools_text = "[dim]No ignored tools configured[/dim]"
            self.query_one("#ssrf-ignore-tools-list", Static).update(ignore_tools_text)
        except Exception:
            pass

        # Apply schema default indicators
        self._apply_default_indicators(ssrf_config)

        # Load statistics (if available)
        self._load_statistics()

    def _load_statistics(self) -> None:
        """Load and display SSRF detection statistics."""
        try:
            from ai_guardian.violations.logger import ViolationLogger
            from ai_guardian.violations.counter import ViolationCounter

            logger = ViolationLogger()
            stats = ViolationCounter().get_counters()

            # Filter for SSRF violations
            ssrf_count = 0
            total_violations = stats.get("total_violations", 0)

            # Get recent violations
            recent = logger.get_recent_violations(limit=100)
            for v in recent:
                if "SSRF" in v.get("reason", ""):
                    ssrf_count += 1

            stats_text = (
                f"Total SSRF Blocks: {ssrf_count}\n"
                f"Total Violations (All Types): {total_violations}"
            )

            self.query_one("#ssrf-stats", Static).update(stats_text)

        except ImportError:
            self.query_one("#ssrf-stats", Static).update(
                "[dim]Violation logging not available[/dim]"
            )
        except Exception as e:
            self.query_one("#ssrf-stats", Static).update(
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
        return self._save_config_updates(config_updates)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox changes - save immediately."""
        if getattr(self, "_loading", False):
            return
        checkbox_id = event.checkbox.id

        if checkbox_id == "allow-localhost-checkbox":
            self.save_config({"allow_localhost": event.value})
            self._update_default_indicator(
                "allow-localhost-checkbox", "allow_localhost", event.value
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press - save toggle state immediately."""
        if getattr(self, "_loading", False):
            return
        bid = event.button.id
        if bid and "ssrf_protection_enabled" in bid:
            toggle = self.query_one("#ssrf_protection_enabled_toggle", TimeBasedToggle)
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
            self._update_default_indicator("action-select", "action", event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields."""
        if getattr(self, "_loading", False):
            return
        input_id = event.input.id

        # Handle TimeBasedToggle inputs
        if input_id and "ssrf_protection_enabled" in input_id:
            toggle = self.query_one("#ssrf_protection_enabled_toggle", TimeBasedToggle)
            value = toggle.get_value()
            self.save_config({"enabled": value})
        elif input_id == "new-blocked-ip-input":
            self.add_blocked_ip()
        elif input_id == "new-blocked-domain-input":
            self.add_blocked_domain()
        elif input_id == "new-allowed-domain-input":
            self.add_allowed_domain()
        elif input_id == "ssrf-ignore-file-input":
            self._add_ignore_item("ignore_files", event.input)
        elif input_id == "ssrf-ignore-tool-input":
            self._add_ignore_item("ignore_tools", event.input)

    def action_add_ip(self) -> None:
        """Add blocked IP (triggered by 'i' key)."""
        self.add_blocked_ip()

    def action_add_domain(self) -> None:
        """Add blocked domain (triggered by 'd' key)."""
        self.add_blocked_domain()

    def action_add_allowed_domain(self) -> None:
        """Add allowed domain (triggered by 'a' key)."""
        self.add_allowed_domain()

    def action_save_setting(self) -> None:
        """Save settings (triggered by 's' key)."""
        # Already auto-saved on change, just notify
        self.app.notify("Settings auto-saved on change", severity="information")

    def action_refresh(self) -> None:
        """Refresh configuration (triggered by 'r' key)."""
        self.load_config()
        self.app.notify("SSRF configuration refreshed", severity="information")

    def add_blocked_ip(self) -> None:
        """Add an IP or CIDR range to the blocked list."""
        ip_input = self.query_one("#new-blocked-ip-input", Input)
        ip_value = ip_input.value.strip()

        if not ip_value:
            self.app.notify(
                "Please enter an IP address or CIDR range", severity="error"
            )
            return

        # Basic validation - check if it looks like an IP or CIDR
        import re

        ip_pattern = r"^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$"
        if not re.match(ip_pattern, ip_value):
            self.app.notify("Invalid IP address or CIDR format", severity="error")
            return

        try:
            config = self._load_full_config()

            if "ssrf_protection" not in config:
                config["ssrf_protection"] = {}

            if "additional_blocked_ips" not in config["ssrf_protection"]:
                config["ssrf_protection"]["additional_blocked_ips"] = []

            # Check if IP already exists
            if ip_value in config["ssrf_protection"]["additional_blocked_ips"]:
                self.app.notify("IP/CIDR already in blocked list", severity="warning")
                return

            config["ssrf_protection"]["additional_blocked_ips"].append(ip_value)

            self._write_full_config(config)

            # Clear input
            ip_input.value = ""

            self.load_config()
            self.app.notify(f"✓ Added {ip_value} to blocked IPs", severity="success")

        except Exception as e:
            self.app.notify(f"Error adding IP: {e}", severity="error")

    def add_blocked_domain(self) -> None:
        """Add a domain to the blocked list."""
        domain_input = self.query_one("#new-blocked-domain-input", Input)
        domain_value = domain_input.value.strip()

        if not domain_value:
            self.app.notify("Please enter a domain name", severity="error")
            return

        # Basic validation - check if it looks like a domain
        import re

        domain_pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
        if not re.match(domain_pattern, domain_value):
            self.app.notify("Invalid domain format", severity="error")
            return

        try:
            config = self._load_full_config()

            if "ssrf_protection" not in config:
                config["ssrf_protection"] = {}

            if "additional_blocked_domains" not in config["ssrf_protection"]:
                config["ssrf_protection"]["additional_blocked_domains"] = []

            # Check if domain already exists
            if domain_value in config["ssrf_protection"]["additional_blocked_domains"]:
                self.app.notify("Domain already in blocked list", severity="warning")
                return

            config["ssrf_protection"]["additional_blocked_domains"].append(domain_value)

            self._write_full_config(config)

            # Clear input
            domain_input.value = ""

            self.load_config()
            self.app.notify(
                f"✓ Added {domain_value} to blocked domains", severity="success"
            )

        except Exception as e:
            self.app.notify(f"Error adding domain: {e}", severity="error")

    def add_allowed_domain(self) -> None:
        """Add a domain to the allowed list (overrides deny-list)."""
        domain_input = self.query_one("#new-allowed-domain-input", Input)
        domain_value = domain_input.value.strip()

        if not domain_value:
            self.app.notify("Please enter a domain name", severity="error")
            return

        # Basic validation - check if it looks like a domain
        import re

        domain_pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
        if not re.match(domain_pattern, domain_value):
            self.app.notify("Invalid domain format", severity="error")
            return

        try:
            config = self._load_full_config()

            if "ssrf_protection" not in config:
                config["ssrf_protection"] = {}

            if "allowed_domains" not in config["ssrf_protection"]:
                config["ssrf_protection"]["allowed_domains"] = []

            # Check if domain already exists
            if domain_value in config["ssrf_protection"]["allowed_domains"]:
                self.app.notify("Domain already in allow-list", severity="warning")
                return

            config["ssrf_protection"]["allowed_domains"].append(domain_value)

            self._write_full_config(config)

            # Clear input
            domain_input.value = ""

            self.load_config()
            self.app.notify(
                f"✓ Added {domain_value} to allowed domains (overrides deny-list)",
                severity="success",
            )

        except Exception as e:
            self.app.notify(f"Error adding allowed domain: {e}", severity="error")

    def _add_ignore_item(self, field: str, input_widget: Input) -> None:
        """Add an item to ssrf_protection.ignore_files or ignore_tools."""
        value = input_widget.value.strip()
        if not value:
            self.app.notify("Please enter a pattern", severity="error")
            return

        try:
            config = self._load_full_config()

            if "ssrf_protection" not in config:
                config["ssrf_protection"] = {}
            if field not in config["ssrf_protection"]:
                config["ssrf_protection"][field] = []

            if value in config["ssrf_protection"][field]:
                self.app.notify("Pattern already exists", severity="warning")
                return

            config["ssrf_protection"][field].append(value)

            self._write_full_config(config)

            input_widget.value = ""
            self.load_config()
            self.app.notify(f"Added: {value}", severity="success")

        except Exception as e:
            self.app.notify(f"Error adding pattern: {e}", severity="error")
