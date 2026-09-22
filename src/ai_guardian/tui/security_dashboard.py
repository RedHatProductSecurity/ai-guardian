#!/usr/bin/env python3
"""
Security Dashboard Tab Content

Overview of all security features and centralized management.
Provides quick status view, bulk operations, and security analytics.
"""

import json
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll, Grid
from textual.widgets import Static, Button

from textual.widgets import ContentSwitcher

from ai_guardian.config.utils import get_config_dir
from ai_guardian.tui.schema_defaults import ConfigSaveMixin, _ensure_section
from ai_guardian.tui.widgets import format_local_time

FEATURE_GROUPS = [
    (
        "Scanning",
        [
            (
                "secret_scanning",
                "Secret Scanning",
                "Scan for API keys, tokens, credentials",
            ),
            ("scan_pii", "PII Detection", "GDPR/CCPA compliance scanning"),
            (
                "image_scanning",
                "Image Scanning",
                "OCR-based image scanning for secrets and PII",
            ),
            (
                "transcript_scanning",
                "Transcript Scanning",
                "Scan conversation for secrets/PII from ! commands",
            ),
        ],
    ),
    (
        "Threat Detection",
        [
            (
                "prompt_injection",
                "Prompt Injection",
                "Detect and block prompt injection attacks",
            ),
            (
                "ssrf_protection",
                "SSRF Protection",
                "Block requests to private networks and metadata",
            ),
            (
                "config_file_scanning",
                "Config File Scanner",
                "Detect credential exfiltration in config files",
            ),
            (
                "context_poisoning",
                "Context Poisoning",
                "Detect context poisoning attempts",
            ),
            (
                "supply_chain",
                "Supply Chain",
                "Detect malicious hooks, MCP servers, and plugins",
            ),
            (
                "scan_offensive",
                "Offensive Language",
                "Detect profanity, slurs, and non-inclusive terminology",
            ),
        ],
    ),
    (
        "Response Protection",
        [
            (
                "secret_redaction",
                "Secret Redaction",
                "Redact secrets from tool outputs",
            ),
            ("annotations", "Annotations", "Inline suppression for secrets and PII"),
        ],
    ),
    (
        "Access Control",
        [
            ("permissions", "Permissions", "Tool permission enforcement"),
            (
                "security_instructions",
                "Security Instructions",
                "Security rule injection into AI context",
            ),
            (
                "directory_rules",
                "Directory Rules",
                "Block access to protected directories",
            ),
        ],
    ),
    (
        "Monitoring",
        [
            (
                "violation_logging",
                "Violation Logging",
                "Log blocked operations for audit",
            ),
            (
                "latency_tracking",
                "Latency Tracking",
                "Record per-hook timing to latency.jsonl",
            ),
        ],
    ),
]

CARD_PANEL_MAP = {
    "secret-scanning-card": "panel-secrets",
    "scan-pii-card": "panel-scan-pii",
    "prompt-injection-card": "panel-pi-detection",
    "ssrf-card": "panel-ssrf",
    "config-scanner-card": "panel-config-scanner",
    "secret-redaction-card": "panel-secret-redaction",
    "annotations-card": "panel-annotations",
    "permissions-card": "panel-skills",
    "directory-rules-card": "panel-directory-rules",
    "violation-logging-card": "panel-violation-logging",
}

_DEFAULT_ACTIONS = {
    "secret_scanning": "block",
    "transcript_scanning": "scan",
    "annotations": "suppress",
    "permissions": "enforce",
    "security_instructions": "inject",
    "violation_logging": "log",
    "latency_tracking": "log",
}


def _card_id(key):
    return key.replace("_", "-") + "-card"


def _status_id(key):
    return key.replace("_", "-") + "-status"


def _get_feature_status(config, key):
    if key == "permissions":
        return config.get("permissions", {}).get("enabled", True)
    if key == "security_instructions":
        si = config.get("security_instructions", {})
        if isinstance(si, dict):
            return si.get("inject_on_prompt", True)
        return True
    if key == "annotations":
        return config.get("annotations", {}).get("enabled", True)
    if key == "image_scanning":
        return config.get("image_scanning", {}).get("enabled", True)
    section = config.get(key, {})
    if isinstance(section, dict):
        enabled = section.get("enabled", True)
        if isinstance(enabled, dict):
            return enabled
        return enabled
    return True


def _parse_status(status):
    if isinstance(status, dict):
        return status.get("value", True)
    return bool(status)


def _get_action(config, key):
    section = config.get(key, {})
    if isinstance(section, dict):
        action = section.get("action")
        if action:
            return action
    return _DEFAULT_ACTIONS.get(key)


class SecurityDashboardContent(ConfigSaveMixin, Container):
    # No CONFIG_SECTION — enable/disable all passes section= per feature.
    # Uses ConfigSaveMixin for scope-aware path (project or global).
    """Content widget for Security Dashboard tab."""

    CSS = """
    SecurityDashboardContent {
        height: 100%;
    }

    #dashboard-header {
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

    .feature-grid {
        grid-size: 2 4;
        grid-gutter: 1;
        height: auto;
        margin: 1 0;
    }

    .feature-card {
        height: 5;
        padding: 1;
        background: $surface;
        border: solid $accent;
    }

    .feature-enabled {
        border: solid green;
    }

    .feature-disabled {
        border: solid red;
    }

    .feature-clickable:hover {
        background: $primary-lighten-3;
    }

    .feature-clickable:focus {
        border: heavy $accent;
    }

    .setting-row {
        margin: 0.5 0;
        height: auto;
    }

    .violation-item {
        margin: 0.5 0;
        padding: 0.5;
        background: $surface;
        border-left: heavy $accent;
    }

    Button {
        margin: 0 1 0 0;
    }

    /* Focus indicators */
    Button:focus {
        border-left: heavy $accent;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the security dashboard tab content."""
        yield Static("[bold]Security Dashboard[/bold]", id="dashboard-header")

        with VerticalScroll():
            for group_name, features in FEATURE_GROUPS:
                with Container(classes="section"):
                    yield Static(f"[bold]{group_name}[/bold]", classes="section-title")

                    cols = min(len(features), 3)
                    rows = (len(features) + cols - 1) // cols
                    with Grid(classes="feature-grid") as grid:
                        grid.styles.grid_size_columns = cols
                        grid.styles.grid_size_rows = rows
                        for key, label, _desc in features:
                            cid = _card_id(key)
                            with Container(classes="feature-card", id=cid):
                                yield Static(f"[bold]{label}[/bold]")
                                yield Static("", id=_status_id(key))

            # Summary
            with Container(classes="section"):
                yield Static("[bold]Summary[/bold]", classes="section-title")
                yield Static("", id="features-overview")
                yield Static("", id="summary-status")

            # Quick actions
            with Container(classes="section"):
                yield Static("[bold]Quick Actions[/bold]", classes="section-title")

                with Horizontal(classes="setting-row"):
                    yield Button(
                        "Enable All Features", id="enable-all-btn", variant="success"
                    )
                    yield Button(
                        "Disable All Features", id="disable-all-btn", variant="error"
                    )
                    yield Button(
                        "Export Security Config",
                        id="export-config-btn",
                        variant="primary",
                    )

            # Recent violations
            with Container(classes="section"):
                yield Static(
                    "[bold]Recent Security Violations (Last 24 Hours)[/bold]",
                    classes="section-title",
                )
                yield Static("", id="recent-violations")

            # Recommendations
            with Container(classes="section"):
                yield Static(
                    "[bold]Security Recommendations[/bold]", classes="section-title"
                )
                yield Static("", id="recommendations")

    def on_mount(self) -> None:
        """Load dashboard data when mounted."""
        for card_id in CARD_PANEL_MAP:
            try:
                card = self.query_one(f"#{card_id}", Container)
                card.add_class("feature-clickable")
                card.can_focus = True
            except Exception:
                pass
        self.load_dashboard()

    def refresh_content(self) -> None:
        """Refresh dashboard (called by parent app)."""
        self.load_dashboard()

    def load_dashboard(self) -> None:
        """Load and display security dashboard data."""
        config_dir = get_config_dir()
        config_path = config_dir / "ai-guardian.json"

        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                self.app.notify(f"Error loading config: {e}", severity="error")

        enabled_count = 0
        total_count = 0

        for _group_name, features in FEATURE_GROUPS:
            for key, _label, _desc in features:
                total_count += 1
                status = _get_feature_status(config, key)
                is_enabled = _parse_status(status)
                action_val = _get_action(config, key)

                if is_enabled:
                    enabled_count += 1

                self._update_feature_card(key, status, action_val)

        summary_text = f"{enabled_count}/{total_count} Enabled"
        try:
            self.query_one("#summary-status", Static).update(summary_text)
        except Exception:
            pass

        overview_text = (
            f"[green]●[/green] Enabled: {enabled_count}    "
            f"[red]●[/red] Disabled: {total_count - enabled_count}"
        )
        try:
            self.query_one("#features-overview", Static).update(overview_text)
        except Exception:
            pass

        self._load_recent_violations()
        self._generate_recommendations(enabled_count, total_count)

    def _update_feature_card(self, key: str, status, action_val=None) -> None:
        """Update a feature card with current status and action badge."""
        try:
            cid = _card_id(key)
            sid = _status_id(key)
            card = self.query_one(f"#{cid}", Container)
            status_widget = self.query_one(f"#{sid}", Static)

            is_enabled = _parse_status(status)

            if is_enabled:
                status_text = "[green]✓ Enabled[/green]"
                card.add_class("feature-enabled")
                card.remove_class("feature-disabled")
            else:
                status_text = "[red]✗ Disabled[/red]"
                card.add_class("feature-disabled")
                card.remove_class("feature-enabled")

            if isinstance(status, dict) and status.get("disabled_until"):
                disabled_until = status.get("disabled_until", "")
                status_text += (
                    f"\n[dim]Until: {format_local_time(disabled_until)}[/dim]"
                )

            if action_val:
                status_text += f"  [dim]({action_val})[/dim]"

            status_widget.update(status_text)

        except Exception:
            pass  # intentionally silent — best-effort operation

    def _load_recent_violations(self) -> None:
        """Load and display recent security violations."""
        try:
            from ai_guardian.violations.logger import ViolationLogger

            logger = ViolationLogger()
            violations = logger.get_recent_violations(limit=100)

            now = datetime.now()
            recent = []

            for v in violations:
                timestamp_str = v.get("timestamp", "")
                try:
                    timestamp = datetime.fromisoformat(
                        timestamp_str.replace("Z", "+00:00")
                    )
                    hours_ago = (
                        now - timestamp.replace(tzinfo=None)
                    ).total_seconds() / 3600

                    if hours_ago <= 24:
                        recent.append(v)
                except Exception:
                    pass  # intentionally silent — best-effort operation

            if recent:
                violation_types: dict[str, int] = {}
                for v in recent:
                    reason = v.get("reason", "Unknown")
                    violation_type = self._categorize_violation(reason)
                    violation_types[violation_type] = (
                        violation_types.get(violation_type, 0) + 1
                    )

                violations_text = f"Total: {len(recent)} violations\n\n"
                for vtype, count in sorted(
                    violation_types.items(), key=lambda x: x[1], reverse=True
                ):
                    violations_text += f"  • {vtype}: {count}\n"

                self.query_one("#recent-violations", Static).update(
                    violations_text.strip()
                )
            else:
                self.query_one("#recent-violations", Static).update(
                    "[dim]No violations in last 24 hours[/dim]"
                )

        except ImportError:
            self.query_one("#recent-violations", Static).update(
                "[dim]Violation logging not available[/dim]"
            )
        except Exception as e:
            self.query_one("#recent-violations", Static).update(
                f"[dim]Error loading violations: {e}[/dim]"
            )

    def _categorize_violation(self, reason: str) -> str:
        """Categorize a violation by its reason."""
        reason_lower = reason.lower()

        if "ssrf" in reason_lower:
            return "SSRF Protection"
        elif "jailbreak" in reason_lower:
            return "Jailbreak Detection"
        elif "prompt injection" in reason_lower or "injection" in reason_lower:
            return "Prompt Injection"
        elif (
            "unicode" in reason_lower
            or "zero-width" in reason_lower
            or "homoglyph" in reason_lower
        ):
            return "Unicode Attack"
        elif (
            "config" in reason_lower
            or "claude.md" in reason_lower
            or "agents.md" in reason_lower
        ):
            return "Config File Scanner"
        elif "pii" in reason_lower:
            return "PII Detection"
        elif "secret" in reason_lower or "redact" in reason_lower:
            return "Secret Redaction"
        elif "image" in reason_lower or "ocr" in reason_lower:
            return "Image Scanning"
        elif "transcript" in reason_lower:
            return "Transcript Scanning"
        elif (
            "permission" in reason_lower
            or "tool" in reason_lower
            or "skill" in reason_lower
        ):
            return "Permissions"
        elif "directory" in reason_lower:
            return "Directory Blocking"
        elif "supply" in reason_lower or "chain" in reason_lower:
            return "Supply Chain"
        elif "context" in reason_lower or "poison" in reason_lower:
            return "Context Poisoning"
        else:
            return "Other"

    def _generate_recommendations(self, enabled_count: int, total_count: int) -> None:
        """Generate security recommendations."""
        recommendations = []

        disabled_count = total_count - enabled_count

        if disabled_count:
            recommendations.append(
                f"⚠ {disabled_count} security feature(s) disabled. "
                "Consider enabling all features for maximum protection."
            )

        try:
            from ai_guardian.violations.logger import ViolationLogger

            logger = ViolationLogger()
            recent = logger.get_recent_violations(limit=1000)

            if len(recent) > 100:
                recommendations.append(
                    f"⚠ {len(recent)} total violations detected. "
                    "Review violation log to identify patterns and adjust configuration."
                )
        except Exception:
            pass  # intentionally silent — optional dependency

        if not recommendations:
            recommendations.append(
                "✓ All security features enabled - good security posture!"
            )
            recommendations.append(
                "💡 Tip: Review the Violations tab regularly to monitor security events."
            )
            recommendations.append(
                "💡 Tip: Use time-based toggles to temporarily disable features during debugging."
            )

        recommendations.append(
            "⚠ Shell mode bypass: Commands run with the '!' prefix in Claude Code "
            "bypass all ai-guardian hooks. Avoid using '!' to display secrets or "
            "untrusted files. Enable transcript_scanning for after-the-fact detection."
        )

        recommendations_text = "\n\n".join(recommendations)
        self.query_one("#recommendations", Static).update(recommendations_text)

    def on_click(self, event) -> None:
        """Handle clicks on feature cards to navigate to detail panels."""
        widget = event.widget
        while widget is not None and widget is not self:
            if hasattr(widget, "id") and widget.id in CARD_PANEL_MAP:
                panel_id = CARD_PANEL_MAP[widget.id]
                try:
                    switcher = self.app.query_one("#panels", ContentSwitcher)
                    switcher.current = panel_id
                    panel = self.app.query_one(f"#{panel_id}", Container)
                    for child in panel.children:
                        if hasattr(child, "refresh_content"):
                            child.refresh_content()
                            break
                except Exception:
                    pass
                return
            widget = widget.parent

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        button_id = event.button.id

        if button_id == "enable-all-btn":
            self.enable_all_features()
        elif button_id == "disable-all-btn":
            self.disable_all_features()
        elif button_id == "export-config-btn":
            self.export_security_config()

    _ALL_FEATURES = [
        "ssrf_protection",
        "prompt_injection",
        "config_file_scanning",
        "secret_redaction",
        "context_poisoning",
        "supply_chain",
        "scan_pii",
        "image_scanning",
        "secret_scanning",
        "directory_rules",
    ]

    def enable_all_features(self) -> None:
        """Enable all security features in a single write."""
        self._set_all_features(True)

    def disable_all_features(self) -> None:
        """Disable all security features in a single write."""
        self._set_all_features(False)

    def _set_all_features(self, enabled: bool) -> None:
        try:
            config = self._load_full_config()
            for feature in self._ALL_FEATURES:
                target = _ensure_section(config, feature)
                target["enabled"] = enabled
            if not self._write_full_config(config):
                self.app.notify("Error saving config", severity="error")
                return
            self.load_dashboard()
            if enabled:
                self.app.notify("✓ All security features enabled", severity="success")
            else:
                self.app.notify("⚠ All security features disabled", severity="warning")
        except Exception as e:
            self.app.notify(f"Error updating features: {e}", severity="error")

    def export_security_config(self) -> None:
        """Export security configuration to a file."""
        config_dir = get_config_dir()
        config_path = config_dir / "ai-guardian.json"

        try:
            if not config_path.exists():
                self.app.notify("No configuration file found", severity="error")
                return

            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            security_config = {}
            for _group_name, features in FEATURE_GROUPS:
                for key, _label, _desc in features:
                    security_config[key] = config.get(key, {})

            export_path = (
                config_dir
                / f"security-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
            )
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(security_config, f, indent=2)

            self.app.notify(
                f"✓ Security config exported to: {export_path.name}", severity="success"
            )

        except Exception as e:
            self.app.notify(f"Error exporting config: {e}", severity="error")

    def action_refresh(self) -> None:
        """Refresh dashboard (triggered by 'r' key)."""
        self.load_dashboard()
        self.app.notify("Security dashboard refreshed", severity="information")
