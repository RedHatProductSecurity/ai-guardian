"""Code Security (Bandit) TUI panel — configuration and violation view."""

import json
import logging

from typing import Any, Dict, Union

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from ai_guardian.tui.schema_defaults import ConfigSaveMixin

logger = logging.getLogger(__name__)


def _format_enabled(value: Union[bool, Dict[str, Any]]) -> str:
    if isinstance(value, dict):
        return "[green]Yes[/green]" if value.get("value", True) else "[red]No[/red]"
    return "[green]Yes[/green]" if value else "[red]No[/red]"


class CodeSecurityContent(ConfigSaveMixin, Container):
    """Content widget for Code Security (Bandit) tab."""

    CSS = """
    CodeSecurityContent {
        height: 100%;
    }

    #cs-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    .cs-section {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    .cs-section-title {
        margin: 0 0 1 0;
        font-weight: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Code Security Scanning (Bandit)[/bold]", id="cs-header")

        with VerticalScroll():
            with Container(classes="cs-section"):
                yield Static(
                    "[bold]Configuration[/bold]",
                    classes="cs-section-title",
                )
                yield Static("", id="cs-status")

            with Container(classes="cs-section"):
                yield Static(
                    "[bold]Allowlist[/bold]",
                    classes="cs-section-title",
                )
                yield Static("", id="cs-allowlist")

            with Container(classes="cs-section"):
                yield Static(
                    "[bold]Recent Violations[/bold]",
                    classes="cs-section-title",
                )
                yield Static("", id="cs-violations")

            with Container(classes="cs-section"):
                yield Static(
                    "[bold]Bandit Categories Detected[/bold]\n"
                    "[dim]  B1xx  Injection / Injection equivalents\n"
                    "  B2xx  General hardcoded tests\n"
                    "  B3xx  Blacklist calls (weak crypto, eval, exec)\n"
                    "  B4xx  Blacklist imports (Telnet, FTP, etc.)\n"
                    "  B5xx  Cryptography\n"
                    "  B6xx  XML / injection\n"
                    "  B7xx  YAML / subprocess\n\n"
                    "Suppress with:  # nosec  or  # ai-guardian:allow[/dim]"
                )

            with Container(classes="cs-section"):
                yield Static(
                    "[dim]To edit code security settings, use the web console:\n"
                    "  ai-guardian web  →  Code Security page\n"
                    "Or edit ai-guardian.json directly (code_scanning section).[/dim]"
                )

    def on_mount(self) -> None:
        self.load_config()

    def refresh_content(self) -> None:
        self.load_config()

    def load_config(self) -> None:
        config_path = self._get_config_path()

        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                logger.warning("Failed to read config: %s", e)

        cs = config.get("code_scanning", {})
        if not isinstance(cs, dict):
            cs = {}

        enabled = cs.get("enabled", True)
        action = cs.get("action", "warn")
        threshold = cs.get("severity_threshold", "MEDIUM")
        enabled_text = _format_enabled(enabled)

        try:
            self.query_one("#cs-status", Static).update(
                f"  Enabled:            {enabled_text}\n"
                f"  Action:             {action}\n"
                f"  Severity threshold: {threshold}"
            )
        except Exception:
            pass

        allowlist = cs.get("allowlist", [])
        if allowlist:
            lines = []
            for entry in allowlist[:10]:
                tid = entry.get("test_id", "?")
                fp = entry.get("file", "")
                reason = entry.get("reason", "")
                scope = f"  {fp}" if fp else ""
                reason_str = f"  ({reason})" if reason else ""
                lines.append(f"  • {tid}{scope}{reason_str}")
            if len(allowlist) > 10:
                lines.append(f"  [dim]... and {len(allowlist) - 10} more[/dim]")
            allowlist_text = "\n".join(lines)
        else:
            allowlist_text = "[dim]  No allowlist entries[/dim]"

        try:
            self.query_one("#cs-allowlist", Static).update(allowlist_text)
        except Exception:
            pass

        self._load_violations()

    def _load_violations(self) -> None:
        try:
            from ai_guardian.violations.logger import ViolationLogger

            vl = ViolationLogger()
            violations = vl.get_recent_violations(
                limit=10, violation_type="code_security"
            )
            if not violations:
                text = "[dim]  No code security violations detected[/dim]"
            else:
                lines = [f"  {len(violations)} recent violation(s)\n"]
                for v in violations[:10]:
                    ts = v.get("timestamp", "")[:19]
                    blocked = v.get("blocked", {})
                    fp = (
                        blocked.get("file_path", "?")
                        if isinstance(blocked, dict)
                        else "?"
                    )
                    rule = (
                        blocked.get("rule_id", "") if isinstance(blocked, dict) else ""
                    )
                    rule_str = f" [{rule}]" if rule else ""
                    lines.append(f"  {ts}  {fp}{rule_str}")
                text = "\n".join(lines)
        except Exception:
            text = "[dim]  Violation logging not available[/dim]"

        try:
            self.query_one("#cs-violations", Static).update(text)
        except Exception:
            pass
