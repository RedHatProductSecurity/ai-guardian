"""Supply Chain Scanning Tab Content — read-only view of config and violations."""

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
                pass  # intentionally silent — best-effort operation
        return "[green]Yes[/green]" if value.get("value", True) else "[red]No[/red]"
    return "[green]Yes[/green]" if value else "[red]No[/red]"


class SupplyChainContent(ConfigSaveMixin, Container):
    """Content widget for Supply Chain tab (read-only)."""

    CSS = """
    SupplyChainContent {
        height: 100%;
    }

    #sc-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    .sc-section {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    .sc-section-title {
        margin: 0 0 1 0;
        font-weight: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Supply Chain Scanning[/bold]", id="sc-header")

        with VerticalScroll():
            with Container(classes="sc-section"):
                yield Static(
                    "[bold]Configuration Status[/bold]",
                    classes="sc-section-title",
                )
                yield Static("", id="sc-status")

            with Container(classes="sc-section"):
                yield Static("[bold]Scan Targets[/bold]", classes="sc-section-title")
                yield Static("", id="sc-scan-targets")

            with Container(classes="sc-section"):
                yield Static(
                    "[bold]Allowlist Paths[/bold]",
                    classes="sc-section-title",
                )
                yield Static("", id="sc-allowlist-paths")

            with Container(classes="sc-section"):
                yield Static(
                    "[bold]Recent Violations[/bold]",
                    classes="sc-section-title",
                )
                yield Static("", id="sc-violations")

            with Container(classes="sc-section"):
                yield Static(
                    "[dim]To edit supply chain settings, use the web console:\n"
                    "  ai-guardian web  →  Supply Chain page\n"
                    "Or edit ai-guardian.json directly (supply_chain section).[/dim]"
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

        sc = config.get("supply_chain", {})
        if not isinstance(sc, dict):
            sc = {}

        enabled = sc.get("enabled", True)
        action = sc.get("action", "block")
        enabled_text = _format_enabled(enabled)

        try:
            self.query_one("#sc-status", Static).update(
                f"  Enabled: {enabled_text}\n  Action:  {action}"
            )
        except Exception:
            pass

        scan_hooks = sc.get("scan_hooks", True)
        scan_mcp = sc.get("scan_mcp_configs", True)
        scan_plugins = sc.get("scan_plugins", True)

        def _on_off(v: bool) -> str:
            return "[green]ON[/green]" if v else "[red]OFF[/red]"

        try:
            self.query_one("#sc-scan-targets", Static).update(
                f"  Scan Hooks:       {_on_off(scan_hooks)}\n"
                f"  Scan MCP Configs: {_on_off(scan_mcp)}\n"
                f"  Scan Plugins:     {_on_off(scan_plugins)}"
            )
        except Exception:
            pass

        paths = sc.get("allowlist_paths", [])
        if paths:
            paths_text = "\n".join(f"  • {p}" for p in paths)
        else:
            paths_text = "[dim]  No allowlisted paths[/dim]"

        try:
            self.query_one("#sc-allowlist-paths", Static).update(paths_text)
        except Exception:
            pass

        self._load_violations()

    def _load_violations(self) -> None:
        try:
            from ai_guardian.violations.logger import ViolationLogger

            vl = ViolationLogger()
            violations = vl.get_recent_violations(
                limit=10, violation_type="supply_chain"
            )
            if not violations:
                text = "[dim]  No supply chain violations detected[/dim]"
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
                    cat = (
                        blocked.get("category", "") if isinstance(blocked, dict) else ""
                    )
                    cat_str = f" [{cat}]" if cat else ""
                    lines.append(f"  {ts}  {fp}{cat_str}")
                text = "\n".join(lines)
        except Exception:
            text = "[dim]  Violation logging not available[/dim]"

        try:
            self.query_one("#sc-violations", Static).update(text)
        except Exception:
            pass
