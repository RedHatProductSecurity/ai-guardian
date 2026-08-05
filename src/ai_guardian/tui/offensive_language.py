"""Offensive Language Scanner Tab Content — read-only view of config and violations."""

import logging
import json
from datetime import datetime, timezone
from typing import Any, Dict, Union

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from ai_guardian.config.utils import get_config_dir, get_project_config_path

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


class OffensiveLanguageContent(Container):
    """Content widget for Offensive Language tab (read-only)."""

    CSS = """
    OffensiveLanguageContent {
        height: 100%;
    }

    #ol-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    .ol-section {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    .ol-label {
        color: $text-muted;
    }

    .ol-value {
        color: $text;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Offensive Language Scanner[/bold]\n"
            "[dim]Detects profanity, slurs, and non-inclusive terminology "
            "in code, comments, and variable names.[/dim]",
            id="ol-header",
        )
        yield VerticalScroll(
            Static(id="ol-config-status", classes="ol-section"),
            Static(id="ol-help", classes="ol-section"),
            Static(id="ol-violations", classes="ol-section"),
        )

    def on_mount(self) -> None:
        self._refresh_all()

    def _refresh_all(self) -> None:
        self._load_config_status()
        self._load_help()
        self._load_violations()

    def _load_config(self) -> Dict[str, Any]:
        try:
            project_path = get_project_config_path()
            cfg_path = (
                project_path
                if project_path and project_path.exists()
                else (get_config_dir() / "ai-guardian.json")
            )
            if cfg_path and cfg_path.exists():
                with open(cfg_path) as f:
                    cfg = json.load(f)
                return cfg.get("scan_offensive", {})
        except Exception as e:
            logger.warning(f"Could not load offensive language config: {e}")
        return {}

    def _load_config_status(self) -> None:
        try:
            ol = self._load_config()
            enabled = ol.get("enabled", False)
            action = ol.get("action", "log")
            categories = ol.get("categories", ["profanity", "slurs"])
            ignore_files = ol.get("ignore_files", [])
            ignore_tools = ol.get("ignore_tools", [])

            cats_str = ", ".join(categories) if categories else "(none)"
            ignore_files_str = "\n  ".join(ignore_files) if ignore_files else "(none)"
            ignore_tools_str = ", ".join(ignore_tools) if ignore_tools else "(none)"

            text = (
                "[bold]Configuration[/bold]\n\n"
                f"[dim]Enabled:[/dim]      {_format_enabled(enabled)}\n"
                f"[dim]Action:[/dim]       [cyan]{action}[/cyan]\n"
                f"[dim]Categories:[/dim]   [yellow]{cats_str}[/yellow]\n"
                f"[dim]Ignore files:[/dim] {ignore_files_str}\n"
                f"[dim]Ignore tools:[/dim] {ignore_tools_str}\n\n"
                "[dim]Edit: ai-guardian.json → scan_offensive section[/dim]"
            )
            self.query_one("#ol-config-status", Static).update(text)
        except Exception as e:
            self.query_one("#ol-config-status", Static).update(
                f"[red]Error loading config: {e}[/red]"
            )

    def _load_help(self) -> None:
        text = (
            "[bold]Available Categories[/bold]\n\n"
            "[yellow]profanity[/yellow]         — Explicit profanity (f-word, s-word, etc.)\n"
            "[yellow]slurs[/yellow]             — Racial, ethnic, gender, and ableist slurs\n"
            "[yellow]inclusive_language[/yellow] — Non-inclusive terms (master/slave, blacklist,\n"
            "                      dummy, sanity check, etc.) — opt-in, high FP rate\n\n"
            "[bold]False Positive Handling[/bold]\n\n"
            "• Add [cyan]# ai-guardian:allow[/cyan] inline to suppress a specific line\n"
            "• Add glob patterns to [cyan]scan_offensive.ignore_files[/cyan]\n"
            "• Add regexes to [cyan]scan_offensive.allowlist_patterns[/cyan]\n"
            "• Exclude categories you don't need via [cyan]scan_offensive.categories[/cyan]\n\n"
            "[dim]Self-scan exclusion: add src/ai_guardian/patterns/offensive-*.toml\n"
            "to .aiguardignore.toml to avoid flagging the pattern files themselves.[/dim]"
        )
        self.query_one("#ol-help", Static).update(text)

    def _load_violations(self) -> None:
        try:
            from ai_guardian.violations.logger import ViolationLogger

            vl = ViolationLogger()
            violations = vl.get_violations(
                limit=10, violation_type="offensive_language"
            )
            if not violations:
                self.query_one("#ol-violations", Static).update(
                    "[bold]Recent Violations[/bold]\n\n[dim]No offensive language violations logged.[/dim]"
                )
                return

            lines = ["[bold]Recent Violations[/bold]\n"]
            for v in violations:
                blocked = v.get("blocked", {})
                ts = v.get("timestamp", "")[:19].replace("T", " ")
                rule_id = blocked.get("rule_id", "unknown")
                category = blocked.get("category", "")
                matched = blocked.get("matched_text", "")
                suggestion = blocked.get("suggestion", "")
                fp = blocked.get("file_path", "")

                lines.append(
                    f"[dim]{ts}[/dim] [yellow]{rule_id}[/yellow] "
                    f"[dim]({category})[/dim]\n"
                    + (f"  File: [cyan]{fp}[/cyan]\n" if fp else "")
                    + (f"  Match: [red]{matched[:60]}[/red]\n" if matched else "")
                    + (f"  Suggestion: {suggestion}\n" if suggestion else "")
                )
            self.query_one("#ol-violations", Static).update("\n".join(lines))
        except Exception as e:
            self.query_one("#ol-violations", Static).update(
                f"[bold]Recent Violations[/bold]\n\n[dim]Could not load violations: {e}[/dim]"
            )
