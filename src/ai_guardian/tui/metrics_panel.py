#!/usr/bin/env python3
"""
Metrics & Audit Tab Content

Display violation statistics, trends, and compliance audit report.
"""

import platform
import subprocess
import tempfile
from pathlib import Path
from typing import TextIO, cast

from ai_guardian.desktop_utils import open_url

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmResetModal(ModalScreen):
    """Modal for confirming counter reset."""

    CSS = """
    ConfirmResetModal {
        align: center middle;
    }

    #modal-container {
        width: 60;
        height: auto;
        background: $panel;
        border: thick $warning;
        padding: 1 2;
    }

    #modal-header {
        margin: 0 0 1 0;
        text-align: center;
        color: $warning;
    }

    #modal-content {
        margin: 1 0;
        text-align: center;
    }

    #modal-actions {
        margin: 1 0 0 0;
        height: auto;
        align: center middle;
    }

    #modal-actions Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="modal-container"):
            yield Static("[bold]Reset Cumulative Counters?[/bold]", id="modal-header")
            yield Static(
                "This will reset all-time counters to the current\n"
                "log file counts and update the tracking start date.",
                id="modal-content",
            )
            with Horizontal(id="modal-actions"):
                yield Button("Reset", id="confirm-reset", variant="warning")
                yield Button("Cancel (ESC)", id="cancel-reset", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-reset":
            self.dismiss(True)
        else:
            self.dismiss(False)


class MetricsContent(Container):
    """Content widget for Metrics & Audit panel."""

    CSS = """
    MetricsContent {
        height: 100%;
    }

    #metrics-header {
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

    #metrics-range-buttons {
        margin: 1 0;
        height: auto;
    }

    #metrics-range-buttons Button {
        margin: 0 1 0 0;
    }

    #metrics-export-buttons {
        margin: 1 0;
        height: auto;
    }

    #metrics-export-buttons Button {
        margin: 0 1 0 0;
    }

    #metrics-body {
        margin: 1 0;
        padding: 1;
        background: $surface;
        min-height: 10;
    }

    Button:focus {
        border-left: heavy $accent;
        text-style: bold;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._retention_days = self._get_retention_days()
        self._since_days = min(30, self._retention_days)
        self._last_export_path: str = ""

    @staticmethod
    def _get_retention_days() -> int:
        try:
            from ai_guardian.violations.logger import ViolationLogger

            vl = ViolationLogger()
            return vl.config.get("retention_days", 30)
        except Exception:
            return 30

    def compose(self) -> ComposeResult:
        yield Static(
            f"[bold]Metrics & Audit[/bold]  "
            f"[dim](log retains {self._retention_days} days)[/dim]",
            id="metrics-header",
        )

        with VerticalScroll():
            with Horizontal(id="metrics-range-buttons"):
                yield Button("7 days", id="metrics-7d", variant="default")
                yield Button(
                    "30 days",
                    id="metrics-30d",
                    variant="primary" if self._retention_days >= 30 else "default",
                    disabled=self._retention_days < 30,
                )
                yield Button(
                    f"All ({self._retention_days}d)",
                    id="metrics-all",
                    variant="default",
                )
                yield Button("Refresh", id="metrics-refresh", variant="success")
                yield Button("Reset Counters", id="metrics-reset", variant="warning")

            with Horizontal(id="metrics-export-buttons"):
                yield Button("Export HTML", id="export-html", variant="default")
                yield Button("Export JSON", id="export-json", variant="default")
                yield Button("Export CSV", id="export-csv", variant="default")
                yield Button(
                    "Open Folder",
                    id="open-export-folder",
                    variant="default",
                    disabled=True,
                )
                yield Static("", id="export-status")

            with Container(classes="section"):
                yield Static("[bold]Security Posture[/bold]", classes="section-title")
                yield Static("", id="metrics-posture")

            with Container(classes="section"):
                yield Static("[bold]Cumulative Totals[/bold]", classes="section-title")
                yield Static("", id="metrics-cumulative")

            with Container(classes="section"):
                yield Static("[bold]Summary[/bold]", classes="section-title")
                yield Static("Loading...", id="metrics-summary")

            with Container(classes="section"):
                yield Static("[bold]Trend[/bold]", classes="section-title")
                yield Static("", id="metrics-trend-comparison")

            with Container(classes="section"):
                yield Static("[bold]By Type[/bold]", classes="section-title")
                yield Static("", id="metrics-by-type")

            with Container(classes="section"):
                yield Static("[bold]By Severity[/bold]", classes="section-title")
                yield Static("", id="metrics-by-severity")

            with Container(classes="section"):
                yield Static("[bold]By Action[/bold]", classes="section-title")
                yield Static("", id="metrics-by-action")

            with Container(classes="section"):
                yield Static("[bold]Top Files[/bold]", classes="section-title")
                yield Static("", id="metrics-top-files")

            with Container(classes="section"):
                yield Static("[bold]Top Tools[/bold]", classes="section-title")
                yield Static("", id="metrics-top-tools")

            with Container(classes="section"):
                yield Static("[bold]Daily Trend[/bold]", classes="section-title")
                yield Static("", id="metrics-trend")

            with Container(classes="section"):
                yield Static("[bold]Resolution Metrics[/bold]", classes="section-title")
                yield Static("", id="metrics-resolution")

            with Container(classes="section"):
                yield Static("[bold]Compliance Summary[/bold]", classes="section-title")
                yield Static("", id="metrics-compliance")

    def on_mount(self) -> None:
        self._load_metrics()

    def refresh_content(self) -> None:
        self._load_metrics()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "metrics-7d":
            self._since_days = 7
        elif btn_id == "metrics-30d":
            self._since_days = 30
        elif btn_id == "metrics-all":
            self._since_days = self._retention_days
        elif btn_id == "metrics-refresh":
            pass
        elif btn_id == "metrics-reset":
            self._confirm_reset()
            return
        elif btn_id == "export-html":
            self._export("html")
            return
        elif btn_id == "export-json":
            self._export("json")
            return
        elif btn_id == "export-csv":
            self._export("csv")
            return
        elif btn_id == "open-export-folder":
            self._open_export_folder()
            return
        else:
            return

        btn_for_days = {
            "metrics-7d": 7,
            "metrics-30d": 30,
            "metrics-all": self._retention_days,
        }
        for bid, days in btn_for_days.items():
            btn = self.query_one(f"#{bid}", Button)
            if not btn.disabled:
                btn.variant = "primary" if days == self._since_days else "default"

        self._load_metrics()

    def _export(self, fmt: str) -> None:
        try:
            from ai_guardian.reporting.audit import (
                AuditComputer,
                format_audit_html,
                format_audit_json,
                format_audit_csv,
            )

            computer = AuditComputer(since=f"{self._since_days}d")

            suffix = {"html": ".html", "json": ".json", "csv": ".csv"}[fmt]
            tmp = tempfile.NamedTemporaryFile(
                prefix="ai-guardian-audit-",
                suffix=suffix,
                delete=False,
                mode="w",
                encoding="utf-8",
            )

            if fmt == "html":
                report = computer.compute()
                tmp.write(format_audit_html(report))
            elif fmt == "json":
                report = computer.compute()
                tmp.write(format_audit_json(report))
            elif fmt == "csv":
                violations = computer._read_violations()
                format_audit_csv(violations, cast(TextIO, tmp.file))

            tmp.close()
            self._last_export_path = tmp.name

            status = self.query_one("#export-status", Static)
            status.update(f"[green]Saved: {self._last_export_path}[/green]")

            folder_btn = self.query_one("#open-export-folder", Button)
            folder_btn.disabled = False

            if fmt == "html":
                open_url(f"file://{self._last_export_path}")

        except Exception as e:
            status = self.query_one("#export-status", Static)
            status.update(f"[red]Export failed: {e}[/red]")

    def _open_export_folder(self) -> None:
        if not self._last_export_path:
            return
        folder = str(Path(self._last_export_path).parent)
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.Popen(["open", folder])
            elif system == "Windows":
                subprocess.Popen(["explorer", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            status = self.query_one("#export-status", Static)
            status.update(f"[red]Could not open folder: {e}[/red]")

    def _confirm_reset(self) -> None:
        def handle_confirm(confirmed: bool) -> None:
            if confirmed:
                try:
                    from ai_guardian.violations.counter import ViolationCounter

                    ViolationCounter().reset_to_current_log()
                except Exception:
                    pass  # intentionally silent — optional dependency
                self._load_metrics()

        self.app.push_screen(ConfirmResetModal(), handle_confirm)

    def _load_metrics(self) -> None:
        try:
            from ai_guardian.reporting.metrics import MetricsComputer

            computer = MetricsComputer(since_days=self._since_days)
            report = computer.compute()
        except Exception as e:
            self.query_one("#metrics-summary", Static).update(
                f"[red]Error loading metrics: {e}[/red]"
            )
            return

        self._load_audit_sections()

        # Cumulative totals
        if report.cumulative_total > 0:
            since_str = (
                report.cumulative_since[:10] if report.cumulative_since else "unknown"
            )
            lines = [
                f"All-time total: [bold]{report.cumulative_total:,}[/bold]",
                f"Tracking since: {since_str}",
            ]
            if report.cumulative_by_type:
                lines.append("")
                for vtype, count in sorted(
                    report.cumulative_by_type.items(), key=lambda x: x[1], reverse=True
                ):
                    lines.append(f"  {vtype:<25s} {count:>5,}")
            self.query_one("#metrics-cumulative", Static).update("\n".join(lines))
        else:
            self.query_one("#metrics-cumulative", Static).update(
                "[dim]No cumulative data yet[/dim]"
            )

        if report.total_violations == 0:
            self.query_one("#metrics-summary", Static).update(
                f"No violations in the last {self._since_days} days."
            )
            for wid in (
                "metrics-by-type",
                "metrics-by-severity",
                "metrics-by-action",
                "metrics-top-files",
                "metrics-top-tools",
                "metrics-trend",
            ):
                self.query_one(f"#{wid}", Static).update("")
            return

        # Summary
        summary = (
            f"[dim]Showing last {self._since_days} days[/dim]\n\n"
            f"Total violations:  [bold]{report.total_violations:,}[/bold]\n"
            f"Resolved:          {report.resolved_count:,}\n"
            f"Unresolved:        {report.unresolved_count:,}\n"
            f"Unique sessions:   {report.session_count:,}"
        )
        self.query_one("#metrics-summary", Static).update(summary)

        # By type
        self._update_breakdown(
            "metrics-by-type", report.by_type, report.total_violations
        )

        # By severity
        self._update_breakdown(
            "metrics-by-severity", report.by_severity, report.total_violations
        )

        # By action
        self._update_breakdown(
            "metrics-by-action", report.by_action, report.total_violations
        )

        # Top files
        if report.top_files:
            lines = []
            for i, (fp, count) in enumerate(report.top_files, 1):
                display = fp if len(fp) <= 50 else "..." + fp[-47:]
                lines.append(f"  {i:>2}. {display}  ({count:,})")
            self.query_one("#metrics-top-files", Static).update("\n".join(lines))
        else:
            self.query_one("#metrics-top-files", Static).update(
                "[dim]No file data[/dim]"
            )

        # Top tools
        if report.top_tools:
            lines = []
            for i, (tool, count) in enumerate(report.top_tools, 1):
                lines.append(f"  {i:>2}. {tool}  ({count:,})")
            self.query_one("#metrics-top-tools", Static).update("\n".join(lines))
        else:
            self.query_one("#metrics-top-tools", Static).update(
                "[dim]No tool data[/dim]"
            )

        # Daily trend
        if report.time_trend:
            max_count = max(t["count"] for t in report.time_trend) or 1
            bar_width = 20
            lines = []
            for entry in report.time_trend[-14:]:
                bar_len = int(entry["count"] / max_count * bar_width)
                bar = "█" * bar_len
                lines.append(f"  {entry['date']}  {entry['count']:>4,}  {bar}")
            self.query_one("#metrics-trend", Static).update("\n".join(lines))
        else:
            self.query_one("#metrics-trend", Static).update("[dim]No trend data[/dim]")

    def _load_audit_sections(self) -> None:
        try:
            from ai_guardian.reporting.audit import AuditComputer

            computer = AuditComputer(since=f"{self._since_days}d")
            audit = computer.compute()
        except Exception:
            for wid in (
                "metrics-posture",
                "metrics-trend-comparison",
                "metrics-resolution",
                "metrics-compliance",
            ):
                self.query_one(f"#{wid}", Static).update("[dim]Unavailable[/dim]")
            return

        # Security posture
        posture = audit.security_posture or "UNKNOWN"
        colors = {
            "GOOD": "green",
            "FAIR": "yellow",
            "NEEDS ATTENTION": "red",
            "UNKNOWN": "dim",
        }
        color = colors.get(posture, "dim")
        self.query_one("#metrics-posture", Static).update(
            f"[{color}][bold]{posture}[/bold][/{color}]"
        )

        # Trend comparison
        lines = []
        if audit.trend_change_pct is not None:
            arrow = "▼" if audit.trend_change_pct < 0 else "▲"
            word = "decrease" if audit.trend_change_pct < 0 else "increase"
            clr = "green" if audit.trend_change_pct < 0 else "red"
            lines.append(
                f"[{clr}]{arrow} {abs(audit.trend_change_pct):.0f}% {word}[/{clr}]"
                f" from previous period ({audit.prev_period_total:,} violations)"
            )
        else:
            lines.append("[dim]No previous period data for comparison[/dim]")
        self.query_one("#metrics-trend-comparison", Static).update("\n".join(lines))

        # Resolution metrics
        res_lines = [
            f"Resolved:      {audit.resolved_count:,}",
            f"Unresolved:    {audit.unresolved_count:,}",
            f"Rate:          {audit.resolution_pct:.1f}%",
        ]
        if audit.avg_resolution_seconds is not None:
            hours = audit.avg_resolution_seconds / 3600
            res_lines.append(f"Avg time:      {hours:.1f}h")
        else:
            res_lines.append("Avg time:      N/A")
        self.query_one("#metrics-resolution", Static).update("\n".join(res_lines))

        # Compliance
        if audit.compliance_features:
            comp_lines = []
            for feature, enabled in audit.compliance_features.items():
                status = (
                    "[green]✓ enabled[/green]" if enabled else "[red]✗ disabled[/red]"
                )
                count = audit.violations_per_feature.get(feature, 0)
                count_str = f"  ({count:,} violations)" if count > 0 else ""
                comp_lines.append(f"  {feature:<25s} {status}{count_str}")
            self.query_one("#metrics-compliance", Static).update("\n".join(comp_lines))
        else:
            self.query_one("#metrics-compliance", Static).update(
                "[dim]No config data[/dim]"
            )

    def _update_breakdown(self, widget_id: str, data: dict, total: int) -> None:
        if data:
            lines = []
            for key, count in data.items():
                pct = (count / total * 100) if total > 0 else 0
                lines.append(f"  {key:<25s} {count:>5,}  ({pct:>5.1f}%)")
            self.query_one(f"#{widget_id}", Static).update("\n".join(lines))
        else:
            self.query_one(f"#{widget_id}", Static).update("[dim]No data[/dim]")
