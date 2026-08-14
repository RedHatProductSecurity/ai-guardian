"""
MCP Security Audit Panel

Displays MCP server configurations with trust status and security findings.
Uses MCPAuditor from ai_guardian.mcp.audit.

Issue #468
"""

import logging

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer
from textual.widgets import Static, Button

logger = logging.getLogger(__name__)

_SEVERITY_MARKUP = {
    "critical": "[bold red]CRITICAL[/bold red]",
    "high": "[red]HIGH[/red]",
    "medium": "[yellow]MEDIUM[/yellow]",
    "low": "[dim]LOW[/dim]",
    "info": "[dim]INFO[/dim]",
}


class MCPSecurityContent(ScrollableContainer):
    """MCP Security panel showing server configs and audit findings."""

    CSS = """
    MCPSecurityContent {
        overflow-x: hidden;
    }

    #mcp-sec-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    #mcp-sec-summary {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    #mcp-sec-servers {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    #mcp-sec-findings {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    #mcp-sec-actions {
        margin: 1 0;
        height: auto;
    }

    #mcp-sec-actions Button {
        margin: 0 2 0 0;
    }

    #mcp-sec-footer {
        margin: 1 0;
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]MCP Security Audit[/bold]  "
            "[dim]Audit MCP server configurations for security issues[/dim]",
            id="mcp-sec-header",
        )
        yield Static("[dim]Running audit...[/dim]", id="mcp-sec-summary")
        yield Container(id="mcp-sec-servers")
        yield Container(id="mcp-sec-findings")
        with Horizontal(id="mcp-sec-actions"):
            yield Button("Run Audit", id="mcp-sec-refresh-btn", variant="primary")
        yield Static(
            "[dim]For deep source code scanning, run: ai-guardian mcp scan[/dim]",
            id="mcp-sec-footer",
        )

    def on_mount(self) -> None:
        self._run_audit()

    def refresh_content(self) -> None:
        self._run_audit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "mcp-sec-refresh-btn":
            self._run_audit()
            self.app.notify("MCP audit refreshed", severity="information")

    def _run_audit(self) -> None:
        """Run MCP config audit and update the display."""
        try:
            from ai_guardian.mcp.audit import MCPAuditor

            auditor = MCPAuditor()
            servers = auditor.discover_servers()
            report = auditor.audit_config(servers)
            self._display_results(servers, report)
        except Exception as e:
            logger.error("MCP audit error: %s", e)
            summary = self.query_one("#mcp-sec-summary", Static)
            summary.update(f"[red]Error running audit: {e}[/red]")

    def _display_results(self, servers, report) -> None:
        """Update display with audit results."""
        trusted = sum(1 for s in servers if s.is_trusted)
        untrusted = len(servers) - trusted

        summary = self.query_one("#mcp-sec-summary", Static)
        if not servers:
            summary.update(
                "[dim]No MCP servers found in IDE configuration files.[/dim]"
            )
            return

        finding_text = ""
        if report.findings:
            critical = sum(1 for f in report.findings if f.severity == "critical")
            high = sum(1 for f in report.findings if f.severity == "high")
            medium = sum(1 for f in report.findings if f.severity == "medium")
            parts = []
            if critical:
                parts.append(f"[bold red]{critical} critical[/bold red]")
            if high:
                parts.append(f"[red]{high} high[/red]")
            if medium:
                parts.append(f"[yellow]{medium} medium[/yellow]")
            finding_text = f"  Findings: {', '.join(parts)}"
        else:
            finding_text = "  [green]No issues found[/green]"

        summary.update(
            f"Servers: {len(servers)} total, "
            f"[green]{trusted} trusted[/green], "
            f"[red]{untrusted} untrusted[/red]"
            f"{finding_text}  "
            f"[dim]({report.scan_time_ms}ms)[/dim]"
        )

        # Server list
        servers_container = self.query_one("#mcp-sec-servers", Container)
        servers_container.remove_children()
        servers_container.mount(Static("[bold]Servers[/bold]\n"))

        lines = []
        for s in sorted(servers, key=lambda x: x.name):
            trust = "[green]Trusted[/green]" if s.is_trusted else "[red]Untrusted[/red]"
            ide_configs = getattr(s, "ide_configs", []) or []
            if ide_configs:
                for i, ic in enumerate(ide_configs):
                    env_count = len(ic.env_var_names)
                    env_text = f"{env_count} env" if env_count else "no env"
                    cmd = ic.command
                    if len(cmd) > 12:
                        cmd = cmd.rsplit("/", 1)[-1][:12]
                    if i == 0:
                        lines.append(
                            f"  {s.name:<24s}  {ic.ide:<12s}  {cmd:<12s}  {trust:<22s}  {env_text}"
                        )
                    else:
                        lines.append(
                            f"  {'':<24s}  {ic.ide:<12s}  {cmd:<12s}  {'':<22s}  {env_text}"
                        )
            else:
                from ai_guardian.mcp.audit import MCPAuditor

                ide_names = ", ".join(
                    sorted({MCPAuditor.ide_label(p) for p in s.config_sources})
                )
                env_count = len(s.env_var_names)
                env_text = f"{env_count} env" if env_count else "no env"
                lines.append(
                    f"  {s.name:<24s}  {ide_names:<12s}  {s.command:<12s}  {trust:<22s}  {env_text}"
                )

        if lines:
            servers_container.mount(Static("\n".join(lines)))

        # Findings
        findings_container = self.query_one("#mcp-sec-findings", Container)
        findings_container.remove_children()

        if report.findings:
            findings_container.mount(Static("[bold]Findings[/bold]\n"))
            finding_lines = []
            for f in report.findings:
                sev = _SEVERITY_MARKUP.get(f.severity, f.severity.upper())
                finding_lines.append(f"  {sev}  {f.server_name}: {f.message}")
            findings_container.mount(Static("\n".join(finding_lines)))
