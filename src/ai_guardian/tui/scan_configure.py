"""
Scan Configure Panel

Scan a project directory to detect false positives and auto-generate
suppression config (.ai-guardian/ai-guardian.json and .aiguardignore.toml).
"""

import json
import threading
from pathlib import Path

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import (
    Container,
    Horizontal,
    ScrollableContainer,
    VerticalScroll,
)
from textual.widgets import Static, Button, Input

from ai_guardian.constants import RULE_ID_LABELS
from ai_guardian.tui.utils import quiet_logging


class ScanConfigureContent(ScrollableContainer):
    """Scan project and auto-generate suppression config."""

    CSS = """
    ScanConfigureContent {
        overflow-x: hidden;
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
        text-style: bold;
    }

    .sc-row {
        margin: 0 0 1 0;
        height: auto;
    }

    #sc-path-input {
        margin: 0 0 1 0;
    }

    #sc-threshold-input {
        margin: 0 0 1 0;
        width: 20;
    }

    #sc-scan-btn {
        margin: 0 2 0 0;
    }

    #sc-summary {
        margin: 0 0 1 0;
    }

    #sc-details-scroll {
        max-height: 40;
        margin: 0 0 1 0;
    }

    #sc-details {
        margin: 0;
    }

    .sc-action-row {
        margin: 1 0 0 0;
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Scan Configure[/bold]  "
            "[dim]Auto-generate suppression config from scan[/dim]",
            id="sc-header",
        )

        yield Static(
            "[dim]All scanners run regardless of enabled/disabled "
            "settings to discover all potential false positives.[/dim]",
            classes="sc-row",
        )

        with Container(id="sc-input-section", classes="sc-section"):
            yield Static("Scan Settings", classes="sc-section-title")

            yield Static(
                "[dim]Project directory to scan[/dim]",
                classes="sc-row",
            )
            yield Input(
                value=str(Path.home()),
                placeholder="Project directory path",
                id="sc-path-input",
            )

            yield Static(
                "[dim]FP threshold — patterns in this many files are "
                "treated as false positives (min: 2)[/dim]",
                classes="sc-row",
            )
            yield Input(
                value="10",
                placeholder="10",
                id="sc-threshold-input",
            )

            with Horizontal(classes="sc-row"):
                yield Button("Run Scan", variant="primary", id="sc-scan-btn")
                yield Button("Stop", variant="error", id="sc-stop-btn")

        with Container(id="sc-results-section", classes="sc-section"):
            yield Static("Results", classes="sc-section-title")
            yield Static("", id="sc-summary")
            with VerticalScroll(id="sc-details-scroll"):
                yield Static("", id="sc-details")
            with Horizontal(classes="sc-action-row"):
                yield Button(
                    "Merge",
                    variant="success",
                    id="sc-merge-btn",
                )
                yield Button(
                    "Overwrite",
                    variant="warning",
                    id="sc-overwrite-btn",
                )
                yield Button(
                    "Discard",
                    variant="error",
                    id="sc-discard-btn",
                )

    def on_mount(self) -> None:
        self.query_one("#sc-results-section").display = False
        self.query_one("#sc-stop-btn").display = False
        self._cancel_event = threading.Event()
        self._scan_result = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sc-scan-btn":
            self._run_scan()
        elif event.button.id == "sc-stop-btn":
            self._cancel_event.set()
        elif event.button.id == "sc-merge-btn":
            self._apply_config(overwrite=False)
        elif event.button.id == "sc-overwrite-btn":
            self._apply_config(overwrite=True)
        elif event.button.id == "sc-discard-btn":
            self._discard()

    def refresh_content(self) -> None:
        self._discard()

    def action_refresh(self) -> None:
        self.refresh_content()

    def _show_error(self, msg: str) -> None:
        summary = self.query_one("#sc-summary", Static)
        summary.update(f"[red]{escape(msg)}[/red]")
        self.query_one("#sc-results-section").display = True

    def _run_scan(self) -> None:
        project_dir = self.query_one("#sc-path-input", Input).value.strip()
        if not project_dir:
            self._show_error("Enter a project directory path.")
            return
        if not Path(project_dir).is_dir():
            self._show_error("Directory does not exist.")
            return

        threshold_str = self.query_one("#sc-threshold-input", Input).value.strip()
        try:
            threshold = max(2, int(threshold_str))
        except (ValueError, TypeError):
            threshold = 10

        self._cancel_event.clear()
        self.query_one("#sc-scan-btn").disabled = True
        self.query_one("#sc-stop-btn").display = True
        self.query_one("#sc-results-section").display = True
        self.query_one("#sc-merge-btn").display = False
        self.query_one("#sc-overwrite-btn").display = False
        self.query_one("#sc-discard-btn").display = False

        summary = self.query_one("#sc-summary", Static)
        summary.update(f"[yellow]Scanning {escape(project_dir)}...[/yellow]")
        self.query_one("#sc-details", Static).update("")

        def worker():
            try:
                with quiet_logging():
                    from ai_guardian.scan_analyzer import run_scan_pipeline

                    def on_phase(msg):
                        self.app.call_from_thread(
                            summary.update,
                            f"[yellow]{escape(msg)}[/yellow]",
                        )

                    def on_file_progress(file_path, index, total):
                        if index % 20 == 0 or index == total:
                            short = file_path
                            if len(short) > 60:
                                short = "..." + short[-57:]
                            self.app.call_from_thread(
                                summary.update,
                                f"[yellow]Scanning {index}/{total}[/yellow]  "
                                f"[dim]{escape(short)}[/dim]",
                            )

                    pipeline_result = run_scan_pipeline(
                        project_dir,
                        threshold,
                        self._cancel_event,
                        on_phase=on_phase,
                        on_file_progress=on_file_progress,
                    )

                    if pipeline_result is None:
                        self.app.call_from_thread(self._scan_cancelled)
                        return

                    self.app.call_from_thread(self._display_results, pipeline_result)

            except Exception as exc:
                self.app.call_from_thread(self._show_error, str(exc))
            finally:
                self.app.call_from_thread(self._scan_finished)

        threading.Thread(target=worker, daemon=True).start()

    def _scan_cancelled(self) -> None:
        self.query_one("#sc-summary", Static).update("[amber]Scan cancelled.[/amber]")

    def _scan_finished(self) -> None:
        self.query_one("#sc-scan-btn").disabled = False
        self.query_one("#sc-stop-btn").display = False

    def _display_results(self, result) -> None:
        self._scan_result = result
        analysis = result.analysis
        findings_count = result.findings_count
        merged_config = result.merged_config

        remaining = findings_count - analysis.suppressed_count

        lang_names = result.language_names
        lang_text = f"  Languages: {', '.join(lang_names)}" if lang_names else ""

        summary_text = (
            f"[bold]Findings:[/bold] {findings_count}  |  "
            f"[green]Suppressed:[/green] {analysis.suppressed_count}  |  "
            f"[{'green' if remaining == 0 else 'amber'}]"
            f"Remaining:[/{'green' if remaining == 0 else 'amber'}] {remaining}"
            f"{lang_text}"
        )
        self.query_one("#sc-summary", Static).update(summary_text)

        lines = []

        if analysis.high_frequency_clusters:
            lines.append("[bold]High-Frequency Clusters (Auto-Suppressed)[/bold]")
            lines.append(
                "[dim]Patterns appearing in many files — likely false positives[/dim]"
            )
            lines.append("")
            for c in analysis.high_frequency_clusters:
                samples = ", ".join(c.sample_files[:3])
                label = RULE_ID_LABELS.get(c.rule_id, c.rule_id)
                lines.append(
                    f"  [bold]{escape(label)}[/bold] "
                    f"[dim]({escape(c.rule_id)})[/dim] "
                    f"[dim]{escape(c.sub_type)}[/dim]  "
                    f"files={c.file_count} total={c.total_count}  "
                    f"[dim]{escape(samples)}[/dim]"
                )
            lines.append("")

        dirs_to_ignore = [
            d for d in analysis.directories_to_ignore if d.all_high_frequency
        ]
        if dirs_to_ignore:
            lines.append("[bold]Directories to Ignore[/bold]")
            lines.append(
                "[dim]All findings in these directories are high-frequency[/dim]"
            )
            lines.append("")
            for d in dirs_to_ignore:
                lines.append(
                    f"  [bold]{escape(d.directory)}/[/bold]  "
                    f"({d.total_findings} findings)"
                )
            lines.append("")

        lines.append("[bold]Config Preview[/bold]")
        lines.append("")

        if merged_config:
            lines.append("[bold]ai-guardian.json changes:[/bold]")
            for line in json.dumps(merged_config, indent=2).split("\n"):
                lines.append(f"  {escape(line)}")
            lines.append("")

        if analysis.recommended_ignore_paths:
            lines.append("[bold].aiguardignore.toml entries:[/bold]")
            for scanner_type, paths in sorted(
                analysis.recommended_ignore_paths.items()
            ):
                lines.append(f"  [{escape(scanner_type)}]")
                paths_str = ", ".join(f'"{p}"' for p in paths)
                lines.append(f"  paths = [{escape(paths_str)}]")
            lines.append("")

        if not merged_config and not analysis.recommended_ignore_paths:
            lines.append("[dim]No config changes needed.[/dim]")

        self.query_one("#sc-details", Static).update("\n".join(lines))

        self.query_one("#sc-merge-btn").display = True
        self.query_one("#sc-overwrite-btn").display = True
        self.query_one("#sc-discard-btn").display = True

    def _apply_config(self, overwrite: bool = False) -> None:
        if not self._scan_result:
            return

        result = self._scan_result
        project_dir = result.project_dir
        merged_config = result.merged_config
        ignore_paths = result.analysis.recommended_ignore_paths

        def worker():
            try:
                with quiet_logging():
                    from ai_guardian.project_init import ProjectInitializer
                    from ai_guardian.scan_analyzer import merge_and_write_config

                    initializer = ProjectInitializer(Path(project_dir))

                    if merged_config:
                        config_path = (
                            Path(project_dir) / ".ai-guardian" / "ai-guardian.json"
                        )
                        if overwrite:
                            config_path.parent.mkdir(parents=True, exist_ok=True)
                            if config_path.exists():
                                import shutil

                                shutil.copy2(
                                    config_path,
                                    config_path.with_suffix(".json.backup"),
                                )
                            config_path.write_text(
                                json.dumps(merged_config, indent=2) + "\n",
                                encoding="utf-8",
                            )
                        else:
                            merge_and_write_config(config_path, merged_config)
                    if ignore_paths:
                        initializer.write_aiguardignore(ignore_paths)

                    mode = "overwritten" if overwrite else "merged"
                    self.app.call_from_thread(
                        self.app.notify,
                        f"Config {mode} successfully",
                        severity="information",
                    )
            except Exception as exc:
                self.app.call_from_thread(self._show_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _discard(self) -> None:
        self._scan_result = None
        self.query_one("#sc-results-section").display = False
        self.query_one("#sc-summary", Static).update("")
        self.query_one("#sc-details", Static).update("")
