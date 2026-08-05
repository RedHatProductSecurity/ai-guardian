"""Exfil Detection Tab Content — read-only view of config and violations."""

import logging
import json
from datetime import datetime, timezone

from typing import Any, Dict, Union

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from ai_guardian.tui.schema_defaults import ConfigSaveMixin

logger = logging.getLogger(__name__)


def _format_enabled(value: Union[bool, Dict[str, Any]]) -> str:
    if isinstance(value, dict):
        disabled_until = value.get("disabled_until")
        if disabled_until:
            try:
                until_dt = datetime.fromisoformat(disabled_until.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < until_dt:
                    remaining = until_dt - datetime.now(timezone.utc)
                    total = max(0, int(remaining.total_seconds()))
                    h = total // 3600
                    m = (total % 3600) // 60
                    parts = []
                    if h:
                        parts.append(f"{h}h")
                    if m:
                        parts.append(f"{m}m")
                    time_str = " ".join(parts) if parts else "<1m"
                    reason = value.get("reason", "")
                    reason_str = f" ({reason})" if reason else ""
                    return f"[yellow]Temp disabled — {time_str} remaining{reason_str}[/yellow]"
            except (ValueError, TypeError):
                pass
        return "[green]Yes[/green]" if value.get("value", True) else "[red]No[/red]"
    return "[green]Yes[/green]" if value else "[red]No[/red]"


class ExfilDetectionContent(ConfigSaveMixin, Container):
    """Content widget for Exfil Detection tab (read-only)."""

    CSS = """
    ExfilDetectionContent {
        height: 100%;
    }

    #ed-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    .ed-section {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    .ed-section-title {
        margin: 0 0 1 0;
        font-weight: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Exfiltration Behavior Detection[/bold]", id="ed-header")

        with VerticalScroll():
            with Container(classes="ed-section"):
                yield Static(
                    "[bold]Configuration Status[/bold]",
                    classes="ed-section-title",
                )
                yield Static("", id="ed-status")

            with Container(classes="ed-section"):
                yield Static(
                    "[bold]Allowlist Patterns[/bold]",
                    classes="ed-section-title",
                )
                yield Static("", id="ed-allowlist-patterns")

            with Container(classes="ed-section"):
                yield Static(
                    "[bold]Recent Violations[/bold]",
                    classes="ed-section-title",
                )
                yield Static("", id="ed-violations")

            with Container(classes="ed-section"):
                yield Static(
                    "[dim]To edit exfil detection settings, use the web console:\n"
                    "  ai-guardian web  →  Exfil Detection page\n"
                    "Or edit ai-guardian.json directly (exfil_detection section).[/dim]"
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

        ed = config.get("exfil_detection", {})
        if not isinstance(ed, dict):
            ed = {}

        enabled = ed.get("enabled", True)
        action = ed.get("action", "block")
        enabled_text = _format_enabled(enabled)

        try:
            self.query_one("#ed-status", Static).update(
                f"  Enabled: {enabled_text}\n  Action:  {action}"
            )
        except Exception:
            pass

        patterns = ed.get("allowlist_patterns", [])
        if patterns:
            patterns_text = "\n".join(f"  • {p}" for p in patterns)
        else:
            patterns_text = "[dim]  No allowlist patterns configured[/dim]"

        try:
            self.query_one("#ed-allowlist-patterns", Static).update(patterns_text)
        except Exception:
            pass

        self._load_violations()

    def _load_violations(self) -> None:
        try:
            from ai_guardian.violations.logger import ViolationLogger

            vl = ViolationLogger()
            violations = vl.get_recent_violations(
                limit=10, violation_type="exfil_detection"
            )
            if not violations:
                text = "[dim]  No exfil detection violations detected[/dim]"
            else:
                lines = [f"  {len(violations)} recent violation(s)\n"]
                for v in violations[:10]:
                    ts = v.get("timestamp", "")[:19]
                    blocked = v.get("blocked", {})
                    cat = (
                        blocked.get("category", "") if isinstance(blocked, dict) else ""
                    )
                    cmd = (
                        blocked.get("command", "?")[:60]
                        if isinstance(blocked, dict)
                        else "?"
                    )
                    cat_str = f" [{cat}]" if cat else ""
                    lines.append(f"  {ts}  {cmd}{cat_str}")
                text = "\n".join(lines)
        except Exception:
            text = "[dim]  Violation logging not available[/dim]"

        try:
            self.query_one("#ed-violations", Static).update(text)
        except Exception:
            pass
