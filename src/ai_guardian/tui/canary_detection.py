"""Canary Token Detection Tab Content — read-only view of config and violations."""

import json
import logging
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
                pass
        return "[green]Yes[/green]" if value.get("value", True) else "[red]No[/red]"
    return "[green]Yes[/green]" if value else "[red]No[/red]"


class CanaryDetectionContent(Container):
    """Content widget for Canary Detection tab (read-only)."""

    CSS = """
    CanaryDetectionContent {
        height: 100%;
    }

    #cd-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    .cd-section {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    .cd-label {
        color: $text-muted;
    }

    .cd-value {
        color: $text;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Canary Token Detection[/bold]\n"
            "[dim]Detects user-registered tripwire values in AI output "
            "to catch data exfiltration.[/dim]",
            id="cd-header",
        )
        yield VerticalScroll(
            Static(id="cd-config-status", classes="cd-section"),
            Static(id="cd-help", classes="cd-section"),
            Static(id="cd-violations", classes="cd-section"),
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
                return cfg.get("canary_detection", {})
        except Exception as e:
            logger.warning(f"Could not load canary detection config: {e}")
        return {}

    def _load_config_status(self) -> None:
        try:
            cd = self._load_config()
            enabled = cd.get("enabled", False)
            action = cd.get("action", "block")
            tokens = cd.get("tokens", [])

            token_lines = []
            for t in tokens[:10]:
                if "value" in t:
                    desc = t.get("description", "")
                    desc_str = f" — {desc}" if desc else ""
                    token_lines.append(
                        f"  [cyan]exact:[/cyan] {t['value'][:40]}{desc_str}"
                    )
                elif "pattern" in t:
                    desc = t.get("description", "")
                    desc_str = f" — {desc}" if desc else ""
                    token_lines.append(
                        f"  [yellow]regex:[/yellow] {t['pattern'][:40]}{desc_str}"
                    )
            if len(tokens) > 10:
                token_lines.append(f"  [dim]... and {len(tokens) - 10} more[/dim]")
            tokens_str = (
                "\n".join(token_lines)
                if token_lines
                else "  [dim](none configured)[/dim]"
            )

            text = (
                "[bold]Configuration[/bold]\n\n"
                f"[dim]Enabled:[/dim]  {_format_enabled(enabled)}\n"
                f"[dim]Action:[/dim]   [cyan]{action}[/cyan]\n"
                f"[dim]Tokens:[/dim]   {len(tokens)} registered\n"
                f"{tokens_str}\n\n"
                "[dim]Edit: ai-guardian.json → canary_detection section[/dim]"
            )
            self.query_one("#cd-config-status", Static).update(text)
        except Exception as e:
            self.query_one("#cd-config-status", Static).update(
                f"[red]Error loading config: {e}[/red]"
            )

    def _load_help(self) -> None:
        text = (
            "[bold]How Canary Detection Works[/bold]\n\n"
            "Plant a secret value in a sensitive file, then register it here.\n"
            "If the AI ever outputs that value (e.g. in a curl command), "
            "it means data exfiltration is happening.\n\n"
            "[bold]Why not just use secret scanning?[/bold]\n\n"
            "Secret scanner uses entropy + pattern matching — it filters OUT\n"
            "low-entropy strings to reduce false positives.\n"
            "Canary detection uses exact user-registered values, bypassing\n"
            "entropy checks. Works for any string you deliberately plant.\n\n"
            "[bold]Token Types[/bold]\n\n"
            "[cyan]value[/cyan]   — exact string match (case-sensitive)\n"
            "[yellow]pattern[/yellow] — regex match (e.g. CANARY_[A-Z0-9]{8})\n\n"
            "[dim]Config example:\n"
            "canary_detection:\n"
            "  enabled: true\n"
            "  action: block\n"
            "  tokens:\n"
            '    - value: "CANARYTOK_my-db-password"\n'
            '      description: "Production DB canary"[/dim]'
        )
        self.query_one("#cd-help", Static).update(text)

    def _load_violations(self) -> None:
        try:
            from ai_guardian.violations.logger import ViolationLogger

            vl = ViolationLogger()
            violations = vl.get_violations(limit=10, violation_type="canary_detected")
            if not violations:
                self.query_one("#cd-violations", Static).update(
                    "[bold]Recent Violations[/bold]\n\n[dim]No canary token violations logged.[/dim]"
                )
                return

            lines = ["[bold]Recent Violations[/bold]\n"]
            for v in violations:
                blocked = v.get("blocked", {})
                ts = v.get("timestamp", "")[:19].replace("T", " ")
                token = blocked.get("token", "unknown")
                description = blocked.get("description", "")
                matched = blocked.get("matched_text", "")
                fp = blocked.get("file_path", "")

                lines.append(
                    f"[dim]{ts}[/dim] [red]CANARY[/red] "
                    f"[dim]({description})[/dim]\n"
                    + (f"  File: [cyan]{fp}[/cyan]\n" if fp else "")
                    + (f"  Token: [yellow]{token[:60]}[/yellow]\n" if token else "")
                    + (f"  Match: [red]{matched[:60]}[/red]\n" if matched else "")
                )
            self.query_one("#cd-violations", Static).update("\n".join(lines))
        except Exception as e:
            self.query_one("#cd-violations", Static).update(
                f"[bold]Recent Violations[/bold]\n\n[dim]Could not load violations: {e}[/dim]"
            )
