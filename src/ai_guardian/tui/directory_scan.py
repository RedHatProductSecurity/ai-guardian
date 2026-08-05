"""
Directory Scan Panel

Scan directories for security issues (secrets, SSRF, Unicode attacks,
config file threats) with Allow Always per finding and bulk Allow All
of Type.
"""

import json
import os
import threading
import time

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import (
    Container,
    Horizontal,
    ScrollableContainer,
    VerticalScroll,
)
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Input, Checkbox, Label, Select, TextArea

from ai_guardian.constants import RULE_ID_LABELS
from ai_guardian.tui.utils import quiet_logging

FORMAT_OPTIONS = [
    ("JSON", "json"),
    ("SARIF", "sarif"),
]


class ExportModal(ModalScreen):
    """Modal for choosing export destination and format."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = """
    ExportModal {
        align: center middle;
    }

    #export-container {
        width: 64;
        height: auto;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }

    #export-header {
        margin: 0 0 1 0;
        text-align: center;
    }

    .export-field {
        margin: 1 0;
    }

    .export-field Input,
    .export-field Select {
        width: 100%;
    }

    #export-actions {
        margin: 1 0 0 0;
        height: auto;
    }

    #export-actions Button {
        margin: 0 1 0 0;
    }
    """

    def __init__(self, default_dir: str = ".", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._default_dir = default_dir

    def compose(self) -> ComposeResult:
        with Container(id="export-container"):
            yield Static("[bold]Export Scan Results[/bold]", id="export-header")

            with Container(classes="export-field"):
                yield Label("Format:")
                yield Select(
                    FORMAT_OPTIONS,
                    value="json",
                    id="export-format",
                    allow_blank=False,
                )

            with Container(classes="export-field"):
                yield Label("Destination file:")
                default_path = os.path.join(self._default_dir, "scan-results.json")
                yield Input(
                    value=default_path,
                    placeholder="/path/to/output-file",
                    id="export-path",
                )

            with Horizontal(id="export-actions"):
                yield Button("Export", id="do-export", variant="success")
                yield Button("Cancel", id="cancel-export", variant="error")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "export-format":
            fmt = event.value
            path_input = self.query_one("#export-path", Input)
            current = path_input.value
            if fmt == "sarif" and current.endswith(".json"):
                path_input.value = current.rsplit(".json", 1)[0] + ".sarif"
            elif fmt == "json" and current.endswith(".sarif"):
                path_input.value = current.rsplit(".sarif", 1)[0] + ".json"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "do-export":
            fmt = self.query_one("#export-format", Select).value
            path = self.query_one("#export-path", Input).value.strip()
            if not path:
                self.notify("Enter a destination file path", severity="error")
                return
            self.dismiss({"format": fmt, "path": path})
        elif event.button.id == "cancel-export":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ScanPatternEditorModal(ModalScreen):
    """Modal for editing and saving an allowlist pattern from a scan finding."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
    ]

    CSS = """
    ScanPatternEditorModal {
        align: center middle;
    }

    #scan-pe-container {
        width: 80;
        height: 80%;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }

    #scan-pe-content {
        height: 1fr;
        background: $surface;
    }
    """

    def __init__(self, matched_text: str, config_section: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.matched_text = matched_text
        self.config_section = config_section

        from ai_guardian.tui.pattern_editor import (
            get_pattern_type_for_section,
        )

        self.ptype = get_pattern_type_for_section(config_section)

    def compose(self) -> ComposeResult:
        from ai_guardian.tui.pattern_editor import (
            suggest_pattern,
            generate_config_preview,
            PATTERN_TYPES,
        )

        ptype_label = PATTERN_TYPES.get(self.ptype, self.ptype)
        suggested = (
            suggest_pattern(self.matched_text, self.config_section)
            if self.matched_text
            else ""
        )

        with Container(id="scan-pe-container"):
            yield Static(
                "[bold]Allow Always — Edit Pattern[/bold]",
                id="modal-header",
            )
            yield Static(
                f"\n[bold]Matched text:[/bold]\n{escape(self.matched_text[:200])}\n"
            )
            yield Static(f"[bold]Pattern ({ptype_label}):[/bold]")

            yield Input(value=suggested, id="pattern-input")
            yield Static("", id="pattern-status")
            yield Static("[bold]Config preview:[/bold]")

            preview = (
                generate_config_preview(suggested, self.config_section)
                if suggested
                else ""
            )
            yield TextArea(preview, id="pattern-preview", read_only=True)

            with Horizontal(id="modal-actions"):
                yield Button("Test Pattern", id="test-pattern", variant="default")
                yield Button(
                    "Add to Allowlist",
                    id="confirm-pattern",
                    variant="success",
                )
                yield Button("Cancel", id="cancel-pattern", variant="primary")

    def on_mount(self) -> None:
        self._do_test()

    def _do_test(self):
        from ai_guardian.tui.pattern_editor import (
            validate_pattern,
            generate_config_preview,
        )

        pattern_input = self.query_one("#pattern-input", Input)
        pat = pattern_input.value.strip()
        valid, msg = validate_pattern(pat, self.ptype, self.matched_text)

        status = self.query_one("#pattern-status", Static)
        if valid:
            status.update(f"[green]PASS: {msg}[/green]")
            preview = generate_config_preview(pat, self.config_section)
            self.query_one("#pattern-preview", TextArea).load_text(preview)
        else:
            status.update(f"[red]FAIL: {msg}[/red]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "test-pattern":
            self._do_test()
        elif event.button.id == "confirm-pattern":
            self._confirm()
        elif event.button.id == "cancel-pattern":
            self.dismiss()

    def _confirm(self):
        from ai_guardian.tui.pattern_editor import validate_pattern

        pattern_input = self.query_one("#pattern-input", Input)
        pat = pattern_input.value.strip()
        valid, msg = validate_pattern(pat, self.ptype, self.matched_text)
        if not valid:
            status = self.query_one("#pattern-status", Static)
            status.update("[red]FAIL: Fix the pattern first[/red]")
            return

        self.app.push_screen(ScanConfigEditorModal(pat, self.config_section))


class ScanConfigEditorModal(ModalScreen):
    """Modal for reviewing and saving the full config with inserted pattern."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
    ]

    CSS = """
    ScanConfigEditorModal {
        align: center middle;
    }

    #config-editor-container {
        width: 90;
        height: 90%;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }

    #config-editor-area {
        height: 1fr;
    }
    """

    def __init__(self, pattern: str, config_section: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pattern = pattern
        self.config_section = config_section
        self._selected_config_path = None

    def compose(self) -> ComposeResult:
        from ai_guardian.tui.pattern_editor import (
            prepare_config_with_pattern,
            get_config_scope_options,
        )

        scope_options = get_config_scope_options()
        self._selected_config_path = scope_options[0][1]
        self._scope_options = scope_options

        json_text, line_number = prepare_config_with_pattern(
            self.pattern,
            self.config_section,
            config_path=self._selected_config_path,
        )

        with Container(id="config-editor-container"):
            yield Static(
                "[bold]Config Editor — ai-guardian.json[/bold]\n"
                "[dim]Review and save the config with the new pattern.[/dim]"
            )
            if len(scope_options) > 1:
                from textual.widgets import RadioSet, RadioButton

                yield Static("[bold]Save to:[/bold]")
                with RadioSet(id="config-scope-select"):
                    for i, (label, path_str) in enumerate(scope_options):
                        yield RadioButton(f"{label} ({path_str})", value=i == 0)
            yield TextArea(
                json_text,
                id="config-editor-area",
                language="json",
                show_line_numbers=True,
            )
            yield Static("[green]Valid JSON[/green]", id="config-editor-status")
            with Horizontal():
                yield Button("Save", id="save-config", variant="success")
                yield Button("Cancel", id="cancel-config", variant="primary")

    def on_radio_set_changed(self, event) -> None:
        if event.radio_set.id == "config-scope-select":
            from ai_guardian.tui.pattern_editor import prepare_config_with_pattern

            idx = event.index
            opts = getattr(self, "_scope_options", [])
            if idx < len(opts):
                self._selected_config_path = opts[idx][1]
                json_text, line_number = prepare_config_with_pattern(
                    self.pattern,
                    self.config_section,
                    config_path=self._selected_config_path,
                )
                try:
                    area = self.query_one("#config-editor-area", TextArea)
                    area.load_text(json_text)
                    area.cursor_location = (line_number - 1, 0)
                    area.scroll_cursor_visible(center=True)
                except Exception:
                    pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-config":
            self._save()
        elif event.button.id == "cancel-config":
            self.dismiss()

    def _save(self):
        text = self.query_one("#config-editor-area", TextArea).text
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            status = self.query_one("#config-editor-status", Static)
            status.update(f"[red]Invalid JSON: {exc}[/red]")
            return

        from ai_guardian.tui.ask_dialog import _write_config_text

        if _write_config_text(text, config_path_str=self._selected_config_path):
            self.app.notify("Pattern saved to config", severity="information")
            self.dismiss()
            for screen in list(self.app.screen_stack):
                if isinstance(screen, ScanPatternEditorModal):
                    screen.dismiss()
                    break
        else:
            status = self.query_one("#config-editor-status", Static)
            status.update("[red]Failed to write config file[/red]")


class DirectoryScanContent(ScrollableContainer):
    """Interactive directory scanner with Allow Always support."""

    CSS = """
    DirectoryScanContent {
        overflow-x: hidden;
    }

    #ds-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    .ds-section {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    .ds-section-title {
        margin: 0 0 1 0;
        text-style: bold;
    }

    .ds-row {
        margin: 0 0 1 0;
        height: auto;
    }

    #ds-path-input {
        margin: 0 0 1 0;
    }

    #ds-scan-btn {
        margin: 0 2 0 0;
    }

    #ds-summary {
        margin: 0 0 1 0;
    }

    #ds-details-scroll {
        max-height: 30;
        margin: 0 0 1 0;
    }

    #ds-details {
        margin: 0;
    }

    .ds-export-row {
        margin: 1 0 0 0;
        height: auto;
    }

    .ds-group-header {
        margin: 1 0 0 0;
        padding: 0 1;
        background: $primary-darken-2;
    }

    .ds-finding-row {
        margin: 0;
        padding: 0 1;
        height: auto;
    }

    .ds-finding-row Button {
        margin: 0 0 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Directory Scan[/bold]  "
            "[dim]Scan for security issues with Allow Always[/dim]",
            id="ds-header",
        )

        with Container(id="ds-input-section", classes="ds-section"):
            yield Static("Scan Settings", classes="ds-section-title")

            yield Static(
                "[dim]Path — file or directory to scan[/dim]",
                classes="ds-row",
            )
            yield Input(
                value=str(Path.home()),
                placeholder="File or directory path to scan",
                id="ds-path-input",
            )

            with Horizontal(classes="ds-row"):
                yield Checkbox(
                    "Recursive",
                    id="ds-recursive",
                    value=True,
                )
                yield Checkbox(
                    "Config files only",
                    id="ds-config-only",
                    value=False,
                )

            with Horizontal(classes="ds-row"):
                yield Button("Scan", variant="primary", id="ds-scan-btn")
                yield Button("Stop", variant="error", id="ds-stop-btn")

        with Container(id="ds-results-section", classes="ds-section"):
            yield Static("Results", classes="ds-section-title")
            yield Static("", id="ds-summary")
            with VerticalScroll(id="ds-details-scroll"):
                yield Static("", id="ds-details")
            with Horizontal(classes="ds-export-row"):
                yield Button(
                    "Export",
                    variant="default",
                    id="ds-export-btn",
                )

    def on_mount(self) -> None:
        self.query_one("#ds-results-section").display = False
        self.query_one("#ds-stop-btn").display = False
        self._findings: List[Dict[str, Any]] = []
        self._cancel_event = threading.Event()
        self._scan_path: str = "."
        self._file_count: int = 0

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "ds-scan-btn":
            self._run_scan()
        elif bid == "ds-stop-btn":
            self._cancel_event.set()
        elif bid == "ds-export-btn":
            self._open_export_modal()
        elif bid.startswith("allow-finding-"):
            idx = int(bid.split("-")[-1])
            self._allow_finding(idx)
        elif bid.startswith("allow-all-type-"):
            rule_id = bid[len("allow-all-type-") :]
            self._allow_all_of_type(rule_id)
        elif bid.startswith("suppress-source-"):
            idx = int(bid.split("-")[-1])
            self._suppress_source_finding(idx)
        elif bid.startswith("ignore-file-"):
            idx = int(bid.split("-")[-1])
            self._ignore_file_finding(idx)
        elif bid.startswith("ignore-all-files-type-"):
            rule_id = bid[len("ignore-all-files-type-") :]
            self._ignore_all_files_of_type(rule_id)

    def refresh_content(self) -> None:
        self._clear_results()

    def action_refresh(self) -> None:
        self.refresh_content()

    def _clear_results(self):
        self.query_one("#ds-results-section").display = False
        self.query_one("#ds-summary", Static).update("")
        self.query_one("#ds-details", Static).update("")
        self._findings = []

    def _show_running(self):
        section = self.query_one("#ds-results-section")
        section.display = True
        self.query_one("#ds-summary", Static).update("[yellow]Scanning...[/yellow]")
        self.query_one("#ds-details", Static).update("")

    def _update_progress(self, file_path: str, index: int, total: int):
        try:
            short = file_path
            if len(short) > 60:
                short = "..." + short[-57:]
            self.query_one("#ds-summary", Static).update(
                f"[yellow]Scanning {index}/{total}[/yellow]  " f"[dim]{short}[/dim]"
            )
        except Exception:
            pass

    def _load_config(self) -> Dict[str, Any]:
        try:
            from ai_guardian.config.loaders import load_scanner_config

            return load_scanner_config()
        except Exception:
            return {}

    def _run_scan(self):
        path = self.query_one("#ds-path-input", Input).value.strip()
        if not path:
            self._show_error("Enter a path to scan.")
            return

        resolved = Path(path).resolve()
        if not resolved.exists():
            self._show_error(f"Path does not exist: {path}")
            return

        self._scan_path = str(resolved)
        config_only = self.query_one("#ds-config-only", Checkbox).value
        self._cancel_event.clear()
        self._show_running()
        self.query_one("#ds-scan-btn").disabled = True
        self.query_one("#ds-stop-btn").display = True

        def worker():
            try:
                with quiet_logging():
                    from ai_guardian.scanners.file_scanner import FileScanner
                    from ai_guardian.tui.pattern_editor import (
                        config_section_for_rule_id,
                    )

                    def on_progress(file_path, index, total):
                        if index % 20 == 0 or index == total:
                            self.app.call_from_thread(
                                self._update_progress, file_path, index, total
                            )

                    config = self._load_config()
                    scanner = FileScanner(config=config)

                    start_ms = time.monotonic_ns() // 1_000_000
                    findings = scanner.scan_directory(
                        path=self._scan_path,
                        config_only=config_only,
                        progress_callback=on_progress,
                        cancel_event=self._cancel_event,
                    )
                    elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms
                    cancelled = self._cancel_event.is_set()

                    for f in findings:
                        f["config_section"] = config_section_for_rule_id(
                            f.get("rule_id", "")
                        )

                    file_count = (
                        len(scanner._discover_files(resolved, None, None, False))
                        if resolved.is_dir()
                        else 1
                    )

                    self.app.call_from_thread(
                        self._display_results,
                        findings,
                        file_count,
                        elapsed_ms,
                        cancelled,
                    )
            except Exception as exc:
                self.app.call_from_thread(self._show_error, str(exc))
            finally:
                self.app.call_from_thread(self._scan_finished)

        threading.Thread(target=worker, daemon=True).start()

    def _scan_finished(self):
        try:
            self.query_one("#ds-scan-btn").disabled = False
            self.query_one("#ds-stop-btn").display = False
        except Exception:
            pass

    def _display_results(
        self,
        findings: List[Dict[str, Any]],
        file_count: int,
        elapsed_ms: int,
        cancelled: bool = False,
    ):
        self._findings = findings
        self._file_count = file_count

        section = self.query_one("#ds-results-section")
        section.display = True

        violation_count = len(findings)
        incomplete = (
            "  [yellow]SCAN INCOMPLETE — stopped by user[/yellow]" if cancelled else ""
        )

        if violation_count == 0:
            self.query_one("#ds-summary", Static).update(
                f"[green]No issues found[/green]  "
                f"[dim]{file_count} files scanned ({elapsed_ms}ms)[/dim]"
                f"{incomplete}"
            )
            self.query_one("#ds-details", Static).update("")
            return

        self.query_one("#ds-summary", Static).update(
            f"[bold]{file_count}[/bold] files scanned, "
            f"[red]{violation_count} violation"
            f"{'s' if violation_count != 1 else ''}[/red]  "
            f"[dim]({elapsed_ms}ms)[/dim]"
            f"{incomplete}"
        )

        groups = defaultdict(list)
        for i, f in enumerate(findings):
            f["_index"] = i
            groups[f.get("rule_id", "unknown")].append(f)

        lines = []
        for rule_id, group_findings in sorted(groups.items()):
            label = RULE_ID_LABELS.get(rule_id, rule_id)
            config_section = group_findings[0].get("config_section")

            lines.append(
                f"\n[bold]{label}[/bold] "
                f"({len(group_findings)} finding"
                f"{'s' if len(group_findings) != 1 else ''})"
            )

            for f in group_findings:
                severity = f.get("severity", "warning")
                severity_color = "red" if severity == "error" else "yellow"
                icon = "[red]![/red]" if severity == "error" else "[yellow]![/yellow]"

                fpath = f.get("file_path", "")
                line_num = f.get("line_number")
                location = fpath
                if line_num:
                    location += f":{line_num}"

                msg = f.get("message", "")
                snippet = f.get("snippet", "")

                parts = [
                    f"  {icon} [{severity_color}]{escape(location)}[/{severity_color}]"
                ]
                parts.append(f"    [bold]{escape(rule_id)}[/bold] — {escape(msg)}")
                if snippet:
                    parts.append(f"    [dim]{escape(snippet[:200])}[/dim]")

                lines.append("\n".join(parts))

        details_static = self.query_one("#ds-details", Static)
        details_static.update("\n".join(lines))

        scroll = self.query_one("#ds-details-scroll", VerticalScroll)
        try:
            for child in list(scroll.children):
                if isinstance(child, (Horizontal, Button)) and child.id != "ds-details":
                    child.remove()
        except Exception:
            pass

        for rule_id, group_findings in sorted(groups.items()):
            config_section = group_findings[0].get("config_section")
            if config_section:
                row_buttons = [
                    Button(
                        f"Allow All {RULE_ID_LABELS.get(rule_id, rule_id)}",
                        id=f"allow-all-type-{rule_id}",
                        variant="success",
                    ),
                ]
                has_files = any(f.get("file_path") for f in group_findings)
                if has_files:
                    row_buttons.append(
                        Button(
                            "Ignore All Files",
                            id=f"ignore-all-files-type-{rule_id}",
                            variant="warning",
                        )
                    )
                scroll.mount(Horizontal(*row_buttons, classes="ds-finding-row"))

                for f in group_findings:
                    idx = f["_index"]
                    finding_buttons = []
                    if f.get("snippet"):
                        finding_buttons.append(
                            Button(
                                f"Allow #{idx + 1}",
                                id=f"allow-finding-{idx}",
                                variant="default",
                            )
                        )
                    if f.get("file_path"):
                        from ai_guardian.tui.source_annotator import get_comment_prefix

                        if get_comment_prefix(f["file_path"]) is not None:
                            finding_buttons.append(
                                Button(
                                    f"Suppress #{idx + 1}",
                                    id=f"suppress-source-{idx}",
                                    variant="warning",
                                )
                            )
                        finding_buttons.append(
                            Button(
                                f"Ignore File #{idx + 1}",
                                id=f"ignore-file-{idx}",
                                variant="warning",
                            )
                        )
                    if finding_buttons:
                        scroll.mount(
                            Horizontal(*finding_buttons, classes="ds-finding-row")
                        )

    def _allow_finding(self, index: int):
        """Open pattern editor for a single finding."""
        if index >= len(self._findings):
            return
        finding = self._findings[index]
        config_section = finding.get("config_section")
        snippet = finding.get("snippet", "")

        if not config_section:
            self.app.notify(
                "No allowlist section for this finding type",
                severity="warning",
            )
            return
        if not snippet:
            self.app.notify(
                "No matched text available",
                severity="warning",
            )
            return

        self.app.push_screen(ScanPatternEditorModal(snippet, config_section))

    def _allow_all_of_type(self, rule_id: str):
        """Open pattern editor for all findings of a type."""
        matching = [f for f in self._findings if f.get("rule_id") == rule_id]
        if not matching:
            return

        config_section = matching[0].get("config_section")
        if not config_section:
            self.app.notify(
                "No allowlist section for this finding type",
                severity="warning",
            )
            return

        snippets = [f.get("snippet", "") for f in matching if f.get("snippet")]
        first_snippet = snippets[0] if snippets else ""
        if not first_snippet:
            self.app.notify("No matched text available", severity="warning")
            return

        self.app.push_screen(ScanPatternEditorModal(first_snippet, config_section))

    def _suppress_source_finding(self, index: int):
        """Insert annotation in source for a single finding."""
        if index >= len(self._findings):
            return
        finding = self._findings[index]
        file_path = finding.get("file_path", "")
        line_number = finding.get("line_number", 1) or 1

        from ai_guardian.tui.source_annotator import prepare_annotation

        result = prepare_annotation(file_path, line_number)
        if result is None:
            self.app.notify("Cannot annotate this file type", severity="warning")
            return

        modified_content, _hl, annotation_type = result
        from ai_guardian.tui.source_editor_modals import SourceAnnotationEditorModal

        self.app.push_screen(
            SourceAnnotationEditorModal(
                file_path,
                modified_content,
                annotation_type,
                "",
                line_number=line_number,
            )
        )

    def _ignore_file_finding(self, index: int):
        """Add file to .aiguardignore.toml for a single finding."""
        if index >= len(self._findings):
            return
        finding = self._findings[index]
        file_path = finding.get("file_path", "")
        config_section = finding.get("config_section", "")
        if not file_path or not config_section:
            self.app.notify("No file path or config section", severity="warning")
            return

        from ai_guardian.tui.ignore_file_modals import IgnoreFileEditorModal

        self.app.push_screen(IgnoreFileEditorModal(file_path, config_section))

    def _ignore_all_files_of_type(self, rule_id: str):
        """Add all files of a rule type to .aiguardignore.toml."""
        matching = [
            f
            for f in self._findings
            if f.get("rule_id") == rule_id and f.get("file_path")
        ]
        if not matching:
            return

        config_section = matching[0].get("config_section", "")
        if not config_section:
            self.app.notify("No config section for this type", severity="warning")
            return

        file_path = matching[0]["file_path"]
        from ai_guardian.tui.ignore_file_modals import IgnoreFileEditorModal

        self.app.push_screen(IgnoreFileEditorModal(file_path, config_section))

    def _open_export_modal(self):
        if not self._findings:
            self.app.notify("No results to export", severity="warning")
            return

        default_dir = str(Path.cwd())
        self.app.push_screen(ExportModal(default_dir=default_dir), self._do_export)

    def _do_export(self, result: Optional[Dict]) -> None:
        if result is None:
            return

        fmt = result["format"]
        out_file = result["path"]

        try:
            parent = Path(out_file).parent
            parent.mkdir(parents=True, exist_ok=True)

            if fmt == "sarif":
                from ai_guardian import __version__
                from ai_guardian.reporting.sarif import SARIFFormatter

                formatter = SARIFFormatter(version=__version__)
                formatter.write_sarif_file(
                    self._findings, out_file, scan_path=self._scan_path
                )
            else:
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(self._findings, f, indent=2)

            self.app.notify(
                f"Exported to {out_file}",
                severity="information",
            )
        except Exception as exc:
            self.app.notify(f"Export failed: {exc}", severity="error")

    def _show_error(self, msg: str):
        section = self.query_one("#ds-results-section")
        section.display = True
        self.query_one("#ds-summary", Static).update(f"[red]{msg}[/red]")
        self.query_one("#ds-details", Static).update("")
