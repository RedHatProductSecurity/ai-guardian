#!/usr/bin/env python3
"""
Violations Tab Content

Display all recent violations with filtering and resolution instructions.
"""

import json
from typing import Dict

from ai_guardian.constants import HookEvent, VIOLATION_FILTER_TYPES
from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Static, TabbedContent, Tab, TabPane
from textual.screen import ModalScreen
from textual.binding import Binding
from textual import events

from ai_guardian.violations.logger import ViolationLogger
from ai_guardian.violations.guidance import get_resolution_instructions
from ai_guardian.tui.widgets import format_local_time
from ai_guardian.tui.pattern_editor import (
    config_section_for_violation,
    validate_pattern,
    generate_config_preview,
    suggest_pattern,
    get_pattern_type_for_section,
    prepare_config_with_pattern,
    PATTERN_TYPES,
)

_TUI_SLUGS = {
    "tool_permission": ("tool-permission", "tool"),
    "secret_detected": ("secret", "secret"),
    "secret_redaction": ("redaction", "redaction"),
    "directory_blocking": ("directory", "directory"),
    "prompt_injection": ("injection", "injection"),
    "jailbreak_detected": ("jailbreak", "jailbreak"),
    "ssrf_blocked": ("ssrf", "ssrf"),
    "config_file_exfil": ("config-exfil", "config-exfil"),
    "pii_detected": ("pii", "pii"),
    "secret_in_transcript": ("transcript-secret", "transcript-secret"),
    "pii_in_transcript": ("transcript-pii", "transcript-pii"),
    "prompt_injection_in_transcript": ("transcript-pi", "transcript-pi"),
    "annotation_suppressed": ("annotation", "annotation"),
    "image_secret_detected": ("image-secret", "image-secret"),
    "image_pii_detected": ("image-pii", "image-pii"),
    "code_security": ("code-security", "code-security"),
    "offensive_language": ("offensive-language", "offensive-language"),
    "canary_detected": ("canary-detected", "canary-detected"),
    "exfil_detection": ("exfil-detection", "exfil-detection"),
}

_VIOLATION_TAB_TYPES = [("filter-all", "All", None, "#violations-list-all")] + [
    (
        f"filter-{_TUI_SLUGS[vt][0]}",
        label,
        vt,
        f"#violations-list-{_TUI_SLUGS[vt][1]}",
    )
    for label, vt, _tooltip in VIOLATION_FILTER_TYPES
]

_ALLOWLIST_TYPES = frozenset(
    {
        "secret_detected",
        "pii_detected",
        "prompt_injection",
        "jailbreak_detected",
        "directory_blocking",
        "ssrf_blocked",
        "config_file_exfil",
        "context_poisoning",
        "supply_chain",
        "code_security",
        "offensive_language",
        "canary_detected",
        "exfil_detection",
        "tool_permission",
    }
)


def _extract_matched_from_violation(violation: dict) -> str:
    """Extract matched text directly from violation data without rescanning.

    Returns the best available text for pattern editor pre-population.
    For file-based violations where no text is stored (e.g. secret_detected),
    returns "" so the caller falls through to a file rescan.
    """
    blocked = violation.get("blocked", {})
    if not isinstance(blocked, dict):
        blocked = {}
    vtype = violation.get("violation_type", "")

    if blocked.get("matched_text"):
        return str(blocked["matched_text"])

    if blocked.get("context_snippet"):
        return str(blocked["context_snippet"])

    if blocked.get("pattern_hint"):
        return str(blocked["pattern_hint"])

    if vtype == "tool_permission":
        tool = blocked.get("tool_name", "")
        value = blocked.get("tool_value", "")
        if tool and value:
            return f"{tool}:{value}"
        return tool or value or ""

    if vtype == "ssrf_blocked":
        url = blocked.get("tool_value", "") or blocked.get("url", "")
        if not url:
            reason = blocked.get("reason", "")
            import re

            m = re.search(r"https?://\S+", reason)
            if m:
                url = m.group(0)
        return url

    if vtype == "directory_blocking":
        return blocked.get("denied_directory", "") or blocked.get("file_path", "")

    if vtype in (
        "prompt_injection",
        "jailbreak_detected",
        "context_poisoning",
        "supply_chain",
    ):
        return blocked.get("pattern", "")

    if vtype == "code_security":
        return blocked.get("rule_id", "") or blocked.get("file_path", "")

    if vtype == "offensive_language":
        return blocked.get("matched_text", "") or blocked.get("rule_id", "")

    if vtype == "canary_detected":
        return blocked.get("matched_text", "") or blocked.get("token", "")

    if vtype == "exfil_detection":
        return blocked.get("matched_text", "") or blocked.get("pattern", "")

    if vtype == "pii_detected":
        pii_types = blocked.get("pii_types", [])
        if isinstance(pii_types, list) and pii_types:
            return ", ".join(str(t) for t in pii_types)
        return ""

    return ""


class ViolationDetailsModal(ModalScreen):
    """Modal for displaying full violation details."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
    ]

    CSS = """
    ViolationDetailsModal {
        align: center middle;
    }

    #modal-container {
        width: 80;
        height: 80%;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }

    #modal-header {
        margin: 0 0 1 0;
        text-align: center;
    }

    #modal-content {
        height: 1fr;
        background: $surface;
        padding: 1;
        margin: 1 0;
    }

    #modal-content-text {
        color: $success;
    }

    #modal-actions {
        margin: 1 0 0 0;
        height: auto;
        align: center middle;
    }

    #modal-actions Button {
        margin: 0 1 0 0;
    }
    """

    def __init__(self, violation: Dict, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.violation = violation

    def _get_resolution_instructions(self):
        """Return (instructions_text, config_snippet) for this violation type.

        Delegates to the shared violation_guidance module and adds Rich
        markup for TUI display.
        """
        instructions, snippet = get_resolution_instructions(self.violation)

        if not instructions:
            return (
                "No specific resolution instructions available for this violation type.",
                "",
            )

        BOLD_KEYS = [
            "permissions.rules",
            "prompt_injection.allowlist_patterns",
            "secret_scanning.allowlist_patterns",
            "directory_rules.rules",
            "scan_pii.allowlist_patterns",
            "scan_pii.ignore_files",
            "ssrf_protection.additional_allowed_domains",
            "config_file_scanning.ignore_files",
            "image_scanning.ignore_files",
        ]
        for key in BOLD_KEYS:
            instructions = instructions.replace(key, f"[bold]{key}[/bold]")

        instructions = instructions.replace("Option 1:", "[bold]Option 1:[/bold]")
        instructions = instructions.replace("Option 2:", "[bold]Option 2:[/bold]")
        instructions = instructions.replace("Option 3:", "[bold]Option 3:[/bold]")

        if "Tip:" in instructions:
            parts = instructions.rsplit("Tip:", 1)
            instructions = parts[0] + "[dim]Tip:" + parts[1] + "[/dim]"

        return (instructions, snippet)

    def compose(self) -> ComposeResult:
        """Compose the modal."""
        instructions, snippet = self._get_resolution_instructions()

        with Container(id="modal-container"):
            yield Static("[bold]Violation Details[/bold]", id="modal-header")

            details = json.dumps(self.violation, indent=2)
            with VerticalScroll(id="modal-content"):
                yield Static(escape(details), id="modal-content-text")
                yield Static("\n[bold]--- How to Resolve ---[/bold]\n")
                yield Static(instructions)
                if snippet:
                    yield Static(f"\n[bold]Config snippet:[/bold]\n{escape(snippet)}")

            with Horizontal(id="modal-actions"):
                yield Button("Copy Details", id="copy-details", variant="default")
                if snippet:
                    yield Button("Copy Snippet", id="copy-snippet", variant="success")
                vtype = self.violation.get("violation_type", "")
                if vtype in _ALLOWLIST_TYPES:
                    yield Button(
                        "Always Allow...", id="always-allow", variant="warning"
                    )
                blocked = self.violation.get("blocked", {})
                if isinstance(blocked, dict) and blocked.get("file_path"):
                    file_path = blocked["file_path"]
                    line_number = blocked.get("line_number")
                    from ai_guardian.tui.source_annotator import get_comment_prefix

                    if line_number and get_comment_prefix(file_path) is not None:
                        yield Button(
                            "Suppress in Source...",
                            id="suppress-source",
                            variant="warning",
                        )
                    yield Button("Ignore File...", id="ignore-file", variant="warning")
                yield Button("Close (ESC)", id="close-details", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "copy-details":
            details = json.dumps(self.violation, indent=2)
            if self.app.copy_to_clipboard(details):
                self.app.notify(
                    "Violation details copied to clipboard", severity="information"
                )
        elif event.button.id == "copy-snippet":
            _, snippet = self._get_resolution_instructions()
            if snippet:
                if self.app.copy_to_clipboard(snippet):
                    self.app.notify(
                        "Config snippet copied to clipboard", severity="information"
                    )
        elif event.button.id == "always-allow":
            self._on_always_allow()
        elif event.button.id == "suppress-source":
            self._on_suppress_in_source()
        elif event.button.id == "ignore-file":
            self._on_ignore_file()
        elif event.button.id == "close-details":
            self.dismiss()

    def _on_always_allow(self):
        """Extract matched text and open pattern editor."""
        blocked = self.violation.get("blocked", {})
        if not isinstance(blocked, dict):
            blocked = {}

        vtype = self.violation.get("violation_type", "")
        file_path = blocked.get("file_path") or ""
        line_number = blocked.get("line_number", 0)
        sub_type = blocked.get("secret_type", "")
        start_column = blocked.get("start_column")
        end_column = blocked.get("end_column")

        config_section = config_section_for_violation(vtype)
        if not config_section:
            self.app.notify(f"No config section for: {vtype}", severity="warning")
            return

        matched_text = _extract_matched_from_violation(self.violation)

        if not matched_text and file_path:
            from ai_guardian.daemon.violation_rescan import rescan_violation

            try:
                result = rescan_violation(
                    file_path=file_path,
                    line_number=line_number,
                    violation_type=vtype,
                    sub_type=sub_type,
                    start_column=start_column,
                    end_column=end_column,
                )
            except TypeError:
                result = rescan_violation(
                    file_path=file_path,
                    line_number=line_number,
                    violation_type=vtype,
                    sub_type=sub_type,
                )

            status = result.get("status", "")
            if status == "file_not_found":
                self.app.notify(
                    result.get("message", "File no longer exists"),
                    severity="warning",
                )
                return
            if status == "not_found":
                self.app.notify(
                    result.get("message", "Violation no longer present"),
                    severity="warning",
                )
                return
            if status == "found":
                matched_text = result.get("matched_text", "")

        if not matched_text:
            self.app.notify(
                "No matched text available for this violation", severity="warning"
            )
            return

        self.app.push_screen(ViolationPatternEditorModal(matched_text, config_section))

    def _on_suppress_in_source(self):
        """Insert annotation marker in source file."""
        blocked = self.violation.get("blocked", {})
        if not isinstance(blocked, dict):
            return
        file_path = blocked.get("file_path", "")
        line_number = blocked.get("line_number", 1) or 1

        from ai_guardian.tui.source_annotator import prepare_annotation

        result = prepare_annotation(file_path, line_number)
        if result is None:
            self.app.notify("Cannot annotate this file type", severity="warning")
            return

        modified_content, _highlight_line, annotation_type = result
        from ai_guardian.tui.source_editor_modals import SourceAnnotationEditorModal

        self.app.push_screen(
            SourceAnnotationEditorModal(
                file_path,
                modified_content,
                annotation_type,
                preview_snippet="",
                line_number=line_number,
            )
        )

    def _on_ignore_file(self):
        """Add file to .aiguardignore.toml."""
        blocked = self.violation.get("blocked", {})
        if not isinstance(blocked, dict):
            return
        file_path = blocked.get("file_path", "")
        if not file_path:
            return

        vtype = self.violation.get("violation_type", "")
        config_section = config_section_for_violation(vtype)
        if not config_section:
            self.app.notify(f"No config section for: {vtype}", severity="warning")
            return

        from ai_guardian.tui.ignore_file_modals import IgnoreFileEditorModal

        self.app.push_screen(IgnoreFileEditorModal(file_path, config_section))


class ViolationPatternEditorModal(ModalScreen):
    """Modal for editing and saving an allowlist pattern."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
    ]

    CSS = """
    ViolationPatternEditorModal {
        align: center middle;
    }

    #pattern-editor-container {
        width: 80;
        height: 80%;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }

    #pattern-editor-content {
        height: 1fr;
        background: $surface;
    }
    """

    def __init__(self, matched_text: str, config_section: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.matched_text = matched_text
        self.config_section = config_section
        self.ptype = get_pattern_type_for_section(config_section)

    def compose(self) -> ComposeResult:
        ptype_label = PATTERN_TYPES.get(self.ptype, self.ptype)
        suggested = (
            suggest_pattern(self.matched_text, self.config_section)
            if self.matched_text
            else ""
        )

        with Container(id="pattern-editor-container"):
            yield Static("[bold]Allow Always — Edit Pattern[/bold]", id="modal-header")
            yield Static(
                f"\n[bold]Matched text:[/bold]\n{escape(self.matched_text[:200])}\n"
            )
            yield Static(f"[bold]Pattern ({ptype_label}):[/bold]")

            from textual.widgets import Input, TextArea

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
                    "Add to Allowlist", id="confirm-pattern", variant="success"
                )
                yield Button("Cancel", id="cancel-pattern", variant="primary")

    def on_mount(self) -> None:
        self._do_test()

    def _do_test(self):
        from textual.widgets import Input

        pattern_input = self.query_one("#pattern-input", Input)
        pat = pattern_input.value.strip()
        valid, msg = validate_pattern(pat, self.ptype, self.matched_text)

        status = self.query_one("#pattern-status", Static)
        if valid:
            status.update(f"[green]PASS: {msg}[/green]")
            preview = generate_config_preview(pat, self.config_section)
            from textual.widgets import TextArea

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
        from textual.widgets import Input

        pattern_input = self.query_one("#pattern-input", Input)
        pat = pattern_input.value.strip()
        valid, msg = validate_pattern(pat, self.ptype, self.matched_text)
        if not valid:
            status = self.query_one("#pattern-status", Static)
            status.update("[red]FAIL: Fix the pattern first[/red]")
            return

        self.app.push_screen(ViolationConfigEditorModal(pat, self.config_section))


class ViolationConfigEditorModal(ModalScreen):
    """Modal for reviewing and saving the full config with inserted pattern."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
    ]

    CSS = """
    ViolationConfigEditorModal {
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
        from ai_guardian.tui.pattern_editor import get_config_scope_options

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
                "Review the config with the inserted pattern. Save to persist.",
                id="modal-header",
            )

            if len(scope_options) > 1:
                from textual.widgets import RadioSet, RadioButton

                yield Static("[bold]Save to:[/bold]")
                with RadioSet(id="config-scope-select"):
                    for i, (label, path_str) in enumerate(scope_options):
                        yield RadioButton(f"{label} ({path_str})", value=i == 0)

            from textual.widgets import TextArea

            editor = TextArea(json_text, id="config-editor-area", language="json")
            editor.cursor_location = (max(0, line_number - 1), 0)
            yield editor

            yield Static("", id="config-status")

            with Horizontal(id="modal-actions"):
                yield Button("Save", id="save-config", variant="success")
                yield Button("Cancel", id="cancel-config", variant="primary")

    def on_radio_set_changed(self, event) -> None:
        if event.radio_set.id == "config-scope-select":
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
                    from textual.widgets import TextArea

                    area = self.query_one("#config-editor-area", TextArea)
                    area.load_text(json_text)
                    area.cursor_location = (line_number - 1, 0)
                    area.scroll_cursor_visible(center=True)
                except Exception:
                    pass  # intentionally silent — optional dependency

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-config":
            self._save()
        elif event.button.id == "cancel-config":
            self.dismiss()

    def _save(self):
        from textual.widgets import TextArea

        editor = self.query_one("#config-editor-area", TextArea)
        text = editor.text

        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            status = self.query_one("#config-status", Static)
            status.update(f"[red]Invalid JSON: {exc}[/red]")
            return

        from ai_guardian.tui.ask_dialog import _write_config_text

        if _write_config_text(text, config_path_str=self._selected_config_path):
            target = (
                "project"
                if "Project" in (self._selected_config_path or "")
                else "global"
            )
            self.app.notify(f"Pattern saved to {target} config", severity="information")
            self.dismiss()
            parent = self.app.screen
            if isinstance(parent, ViolationPatternEditorModal):
                parent.dismiss()
        else:
            status = self.query_one("#config-status", Static)
            status.update("[red]Failed to write config file[/red]")


class ViolationCard(Vertical):
    """Display a single violation with action buttons."""

    DEFAULT_CSS = """
    ViolationCard {
        height: auto;
        margin: 0;
        padding: 1;
        border: round $primary;
        background: $panel;
    }

    ViolationCard > * {
        height: auto;
    }
    """

    def __init__(self, violation: Dict, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.violation = violation

    def compose(self) -> ComposeResult:
        """Compose the violation card."""
        timestamp = self.violation.get("timestamp", "Unknown")
        # Sanitize timestamp for use in IDs (replace invalid chars)
        timestamp_id = timestamp.replace(":", "-").replace(".", "-").replace("T", "-")
        vtype = self.violation.get("violation_type", "unknown")
        severity = self.violation.get("severity", "warning")
        blocked = self.violation.get("blocked", {})
        suggestion = self.violation.get("suggestion", {})
        resolved = self.violation.get("resolved", False)

        from ai_guardian.theme import textual_severity_class, violation_badge

        severity_class = textual_severity_class(severity)
        icon, _ = violation_badge(vtype)

        # Title with color-coded severity and violation icon
        vtype_display = vtype.upper().replace("_", " ")
        title_parts = [
            f"[{severity_class}]{icon}[/{severity_class}]" if severity_class else icon
        ]
        title_parts.append(vtype_display)

        if resolved:
            title_parts.append("[dim](RESOLVED)[/dim]")

        title = " ".join(title_parts)

        yield Static(f"[bold]{title}[/bold]", classes="violation-title")
        yield Static(
            f"[muted]{format_local_time(timestamp)}[/muted]",
            classes="violation-timestamp",
        )

        # Details based on violation type
        if vtype == "tool_permission":
            tool_name = blocked.get("tool_name", "Unknown")
            tool_value = blocked.get("tool_value", "")
            reason = blocked.get("reason", "")
            yield Static(
                f"Tool: {escape(tool_name)}/{escape(tool_value)}",
                classes="violation-detail",
            )
            if blocked.get("file_path"):
                location_text = f"File: {escape(blocked['file_path'])}"
                if blocked.get("line_number"):
                    start_col = blocked.get("start_column")
                    location_text += f" (line {blocked['line_number']}"
                    if start_col is not None:
                        location_text += f", col {start_col + 1}"
                    elif blocked.get("position"):
                        location_text += f", pos {blocked['position']}"
                    location_text += ")"
                yield Static(location_text, classes="violation-detail")
            yield Static(f"Reason: {escape(reason)}", classes="violation-detail")

            # Show suggested rule
            if suggestion and suggestion.get("rule"):
                rule = suggestion["rule"]
                yield Static("\nSuggested rule:", classes="violation-detail")
                yield Static(
                    f"  {escape(json.dumps(rule, indent=2))}",
                    classes="violation-suggestion",
                )

        elif vtype == "directory_blocking":
            file_path = blocked.get("file_path", "Unknown")
            denied_dir = blocked.get("denied_directory", "")
            yield Static(f"File: {escape(file_path)}", classes="violation-detail")
            yield Static(
                f"Denied by: {escape(denied_dir)}/.ai-read-deny",
                classes="violation-detail",
            )

        elif vtype == "secret_detected":
            # Show source/location
            file_path = blocked.get("file_path")
            source = blocked.get("source", "unknown")
            line_number = blocked.get("line_number")
            end_line = blocked.get("end_line")
            secret_type = blocked.get("secret_type", "Unknown")
            total_findings = blocked.get("total_findings")
            source_command = blocked.get("source_command")

            # Location with path and line number
            position = blocked.get("position")
            start_col = blocked.get("start_column")
            if source_command:
                yield Static(
                    f"Command: {escape(source_command[:120])}",
                    classes="violation-detail",
                )
            if file_path:
                location_text = f"File: {escape(file_path)}"
                if line_number:
                    if end_line and end_line != line_number:
                        location_text += f" (lines {line_number}-{end_line}"
                    else:
                        location_text += f" (line {line_number}"
                    if start_col is not None:
                        location_text += f", col {start_col + 1}"
                    elif position:
                        location_text += f", pos {position}"
                    location_text += ")"
                yield Static(location_text, classes="violation-detail")
            elif source == "prompt":
                location_text = "Location: User prompt"
                if line_number:
                    location_text += f" (line {line_number}"
                    if start_col is not None:
                        location_text += f", col {start_col + 1}"
                    elif position:
                        location_text += f", pos {position}"
                    location_text += ")"
                yield Static(location_text, classes="violation-detail")
            else:
                yield Static(f"Location: {escape(source)}", classes="violation-detail")

            # Show secret type (human-readable name)
            if secret_type and secret_type != "Unknown":
                from ai_guardian.scanners.secret_types import get_secret_type_display

                yield Static(
                    f"Type: {get_secret_type_display(secret_type)}",
                    classes="violation-detail",
                )

            # Show detection info
            yield Static("Detected by: Gitleaks scanner", classes="violation-detail")

            # Show total findings if multiple secrets detected
            if total_findings and total_findings > 1:
                yield Static(
                    f"Total findings: {total_findings}", classes="violation-detail"
                )

            # Note about limited detail
            yield Static(
                "[dim]Note: Secret values are redacted for security. "
                "Review the file at the line number shown above.[/dim]",
                classes="violation-detail",
            )

        elif vtype == "prompt_injection":
            source = blocked.get("source", "unknown")
            file_path = blocked.get("file_path")
            line_number = blocked.get("line_number")
            position = blocked.get("position")
            start_col = blocked.get("start_column")
            pattern = blocked.get("pattern", "Unknown")
            matched_text = blocked.get("matched_text")
            confidence = blocked.get("confidence")
            method = blocked.get("method")
            if file_path:
                location_text = f"File: {escape(file_path)}"
                if line_number:
                    location_text += f" (line {line_number}"
                    if start_col is not None:
                        location_text += f", col {start_col + 1}"
                    elif position:
                        location_text += f", pos {position}"
                    location_text += ")"
                yield Static(location_text, classes="violation-detail")
            else:
                yield Static(f"Source: {escape(source)}", classes="violation-detail")
            yield Static(f"Pattern: {escape(pattern)}", classes="violation-detail")
            if matched_text:
                yield Static(
                    f"Matched: {escape(matched_text[:80])}",
                    classes="violation-detail",
                )
            if method:
                yield Static(f"Method: {escape(method)}", classes="violation-detail")
            if confidence:
                yield Static(
                    f"Confidence: {confidence:.2f}", classes="violation-detail"
                )

        elif vtype == "secret_redaction":
            tool = blocked.get("tool", "Unknown")
            file_path = blocked.get("file_path")
            line_number = blocked.get("line_number")
            start_col = blocked.get("start_column")
            position = blocked.get("position")
            redaction_count = blocked.get("redaction_count", 0)
            redacted_types = blocked.get("redacted_types", [])
            command = blocked.get("command")
            source_command = blocked.get("source_command")
            context_snippet = blocked.get("context_snippet")
            yield Static(f"Tool: {escape(tool)}", classes="violation-detail")
            if source_command:
                yield Static(
                    f"Source Command: {escape(source_command[:120])}",
                    classes="violation-detail",
                )
            elif command:
                yield Static(
                    f"Command: {escape(command[:120])}", classes="violation-detail"
                )
            if file_path:
                location_text = f"File: {escape(file_path)}"
                if line_number:
                    location_text += f" (line {line_number}"
                    if start_col is not None:
                        location_text += f", col {start_col + 1}"
                    elif position:
                        location_text += f", pos {position}"
                    location_text += ")"
                yield Static(location_text, classes="violation-detail")
            elif context_snippet:
                yield Static(
                    f"Context: {escape(context_snippet)}",
                    classes="violation-detail",
                )
            yield Static(
                f"Redacted: {redaction_count} secret(s)", classes="violation-detail"
            )
            if redacted_types:
                yield Static(
                    f"Types: {escape(', '.join(redacted_types))}",
                    classes="violation-detail",
                )

        elif vtype == "pii_detected":
            tool = blocked.get("tool", "Unknown")
            hook = blocked.get("hook", "Unknown")
            file_path = blocked.get("file_path")
            line_number = blocked.get("line_number")
            start_col = blocked.get("start_column")
            position = blocked.get("position")
            pii_count = blocked.get("pii_count", 0)
            pii_types = blocked.get("pii_types", [])
            command = blocked.get("command")
            source_command = blocked.get("source_command")
            context_snippet = blocked.get("context_snippet")
            yield Static(f"Hook: {escape(hook)}", classes="violation-detail")
            yield Static(f"Tool: {escape(tool)}", classes="violation-detail")
            if source_command:
                yield Static(
                    f"Source Command: {escape(source_command[:120])}",
                    classes="violation-detail",
                )
            elif command:
                yield Static(
                    f"Command: {escape(command[:120])}", classes="violation-detail"
                )
            if file_path:
                location_text = f"File: {escape(file_path)}"
                if line_number:
                    location_text += f" (line {line_number}"
                    if start_col is not None:
                        location_text += f", col {start_col + 1}"
                    elif position:
                        location_text += f", pos {position}"
                    location_text += ")"
                yield Static(location_text, classes="violation-detail")
            elif context_snippet:
                yield Static(
                    f"Context: {escape(context_snippet)}",
                    classes="violation-detail",
                )
            yield Static(f"PII found: {pii_count} item(s)", classes="violation-detail")
            if pii_types:
                yield Static(
                    f"Types: {escape(', '.join(pii_types))}",
                    classes="violation-detail",
                )

        elif vtype == "jailbreak_detected":
            file_path = blocked.get("file_path")
            line_number = blocked.get("line_number")
            start_col = blocked.get("start_column")
            position = blocked.get("position")
            confidence = blocked.get("confidence", 0.0)
            matched_text = blocked.get("matched_text", "")
            if file_path:
                location_text = f"File: {escape(file_path)}"
                if line_number:
                    location_text += f" (line {line_number}"
                    if start_col is not None:
                        location_text += f", col {start_col + 1}"
                    elif position:
                        location_text += f", pos {position}"
                    location_text += ")"
                yield Static(location_text, classes="violation-detail")
            else:
                tool = blocked.get("tool", "Unknown")
                yield Static(f"Tool: {escape(tool)}", classes="violation-detail")
            if matched_text:
                yield Static(
                    f"Matched: {escape(matched_text[:80])}",
                    classes="violation-detail",
                )
            if confidence:
                yield Static(
                    f"Confidence: {confidence:.2f}", classes="violation-detail"
                )

        elif vtype == "ssrf_blocked":
            tool_name = blocked.get("tool_name", "Unknown")
            tool_value = blocked.get("tool_value", "")
            file_path = blocked.get("file_path")
            line_number = blocked.get("line_number")
            start_col = blocked.get("start_column")
            position = blocked.get("position")
            reason = blocked.get("reason", "")
            yield Static(f"Tool: {escape(tool_name)}", classes="violation-detail")
            if tool_value:
                yield Static(
                    f"Target: {escape(tool_value[:120])}", classes="violation-detail"
                )
            if file_path:
                location_text = f"File: {escape(file_path)}"
                if line_number:
                    location_text += f" (line {line_number}"
                    if start_col is not None:
                        location_text += f", col {start_col + 1}"
                    elif position:
                        location_text += f", pos {position}"
                    location_text += ")"
                yield Static(location_text, classes="violation-detail")
            if reason:
                yield Static(f"Reason: {escape(reason)}", classes="violation-detail")

        elif vtype == "config_file_exfil":
            file_path = blocked.get("file_path", "Unknown")
            reason = blocked.get("reason", "")
            details = blocked.get("details", "")
            yield Static(f"File: {escape(file_path)}", classes="violation-detail")
            if reason:
                yield Static(f"Reason: {escape(reason)}", classes="violation-detail")
            if details:
                yield Static(
                    f"Details: {escape(details[:120])}", classes="violation-detail"
                )

        elif vtype == "secret_in_transcript":
            file_path = blocked.get("file_path")
            secret_type = blocked.get("secret_type", "Unknown")
            source = blocked.get("source", "transcript")
            if file_path:
                yield Static(f"File: {escape(file_path)}", classes="violation-detail")
            from ai_guardian.scanners.secret_types import get_secret_type_display

            yield Static(
                f"Type: {escape(get_secret_type_display(secret_type))}",
                classes="violation-detail",
            )
            yield Static(f"Source: {escape(source)}", classes="violation-detail")

        elif vtype == "pii_in_transcript":
            file_path = blocked.get("file_path")
            pii_count = blocked.get("pii_count", 0)
            pii_types = blocked.get("pii_types", [])
            if file_path:
                yield Static(f"File: {escape(file_path)}", classes="violation-detail")
            yield Static(f"PII found: {pii_count} item(s)", classes="violation-detail")
            if pii_types:
                yield Static(
                    f"Types: {escape(', '.join(pii_types))}",
                    classes="violation-detail",
                )

        elif vtype == "image_secret_detected":
            file_path = blocked.get("file_path", "Unknown")
            secret_type = blocked.get("secret_type", "Unknown")
            yield Static(f"Image: {escape(file_path)}", classes="violation-detail")
            from ai_guardian.scanners.secret_types import get_secret_type_display

            yield Static(
                f"Secret type: {escape(get_secret_type_display(secret_type))}",
                classes="violation-detail",
            )

        elif vtype == "image_pii_detected":
            file_path = blocked.get("file_path", "Unknown")
            pii_count = blocked.get("pii_count", 0)
            pii_types = blocked.get("pii_types", [])
            yield Static(f"Image: {escape(file_path)}", classes="violation-detail")
            yield Static(f"PII found: {pii_count} item(s)", classes="violation-detail")
            if pii_types:
                yield Static(
                    f"Types: {escape(', '.join(pii_types))}",
                    classes="violation-detail",
                )

        # Show correlation ID and button only when correlation data exists (#366)
        context = self.violation.get("context", {})
        tool_use_id = context.get("tool_use_id")
        hook_event = context.get("hook_event", "")
        has_correlation = bool(context.get("pretool_context"))
        if tool_use_id and has_correlation:
            try:
                hook_label = HookEvent(hook_event).display_name
            except ValueError:
                hook_label = hook_event
            yield Static(
                f"[dim]Correlation: {tool_use_id[:16]}... ({hook_label})[/dim]",
                classes="violation-detail",
            )

        # Action buttons
        with Horizontal(classes="violation-actions"):
            yield Button("Details", id=f"details-{timestamp_id}")
            if has_correlation:
                yield Button(
                    "Correlated", id=f"correlated-{timestamp_id}", variant="default"
                )


class ViolationsContent(Container):
    """Content widget for Violations tab."""

    CSS = """
    ViolationsContent {
        height: 100%;
    }

    #violations-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    ViolationCard {
        border: round $primary;
        margin: 0 0 1 0;
        padding: 1;
        background: $panel;
    }

    .violation-actions {
        height: auto;
        margin: 1 0 0 0;
    }

    .violation-actions Button {
        margin: 0 1 0 0;
    }

    #filter-tabs {
        height: 100%;
    }

    VerticalScroll {
        height: 100%;
    }

    VerticalScroll > ViolationCard {
        height: auto;
    }

    #no-violations {
        margin: 2;
        padding: 2;
        text-align: center;
        color: $text-muted;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.violation_logger = ViolationLogger()

    def compose(self) -> ComposeResult:
        """Compose the violations tab content."""
        yield Static("[bold]Recent Violations[/bold]", id="violations-header")
        yield Static(
            "[dim]Historical log of blocked operations. "
            "Use sub-tabs to filter by type. "
            "Click Details on any violation for resolution instructions.[/dim]",
            classes="violation-detail",
        )

        with Horizontal(classes="violation-actions"):
            yield Button(
                "Refresh",
                id="refresh-violations",
                variant="default",
            )
            yield Button(
                "Scan File/Directory",
                id="scan-file-dir",
                variant="primary",
            )

        # Sub-tabs for filtering — driven by _TAB_TYPES
        with TabbedContent(id="filter-tabs"):
            for pane_id, label, _vtype, list_id in self._TAB_TYPES:
                with TabPane(label, id=pane_id):
                    yield VerticalScroll(id=list_id.lstrip("#"))

    def on_mount(self) -> None:
        """Load violations when mounted."""
        self.load_all_filters()

    def refresh_content(self) -> None:
        """Refresh violations (called by parent app)."""
        self.load_all_filters()

    def load_all_filters(self) -> None:
        """Load violations into all filter tabs."""
        type_counts: Dict[str, int] = {}
        total = 0
        for _pane_id, _label, vtype, list_id in self._TAB_TYPES:
            violations = self.violation_logger.get_recent_violations(
                limit=50, violation_type=vtype, resolved=None
            )
            self._populate_list(list_id, violations)
            if vtype is None:
                total = len(violations)
            else:
                type_counts[vtype] = len(violations)

        self._update_tab_counts(type_counts, total)

    def _populate_list(self, list_id: str, violations: list) -> None:
        """Populate a violations list."""
        try:
            violations_list = self.query_one(list_id, VerticalScroll)
            violations_list.remove_children()

            if not violations:
                empty_msg = Static(
                    "No violations found.\n\n"
                    "[dim]Violations appear here when AI Guardian blocks an operation.[/dim]",
                    classes="empty-state",
                )
                violations_list.mount(empty_msg)
                return

            # Add violation cards
            for violation in violations:
                violations_list.mount(ViolationCard(violation))
        except Exception:
            pass

    _TAB_TYPES = _VIOLATION_TAB_TYPES

    def _update_tab_counts(self, type_counts: Dict[str, int], total: int) -> None:
        """Update tab labels with violation counts."""
        for pane_id, label, vtype, _list_id in self._TAB_TYPES:
            try:
                tab = self.query_one(f"#--content-tab-{pane_id}", Tab)
                if vtype is None:
                    tab.label = f"{label} ({total})"
                else:
                    tab.label = f"{label} ({type_counts.get(vtype, 0)})"
            except NoMatches:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses (details and correlated on violation cards)."""
        button_id = event.button.id

        if button_id == "refresh-violations":
            self.load_all_filters()
            self.app.notify("Violations refreshed", severity="information")
            return

        if button_id == "scan-file-dir":
            try:
                from textual.widgets import ContentSwitcher

                switcher = self.app.query_one("#panels", ContentSwitcher)
                switcher.current = "panel-directory-scan"
            except Exception:
                self.app.notify("Directory Scan panel not found", severity="warning")
            return

        if button_id and button_id.startswith("details-"):
            timestamp_id = button_id.replace("details-", "")
            timestamp = self._unsanitize_timestamp(timestamp_id)
            self.show_violation_details(timestamp)

        elif button_id and button_id.startswith("correlated-"):
            timestamp_id = button_id.replace("correlated-", "")
            timestamp = self._unsanitize_timestamp(timestamp_id)
            self.show_correlated_violation(timestamp)

    def _unsanitize_timestamp(self, timestamp_id: str) -> str:
        """Convert sanitized timestamp ID back to original format."""
        # Find matching violation by checking all recent violations
        violations = self.violation_logger.get_recent_violations(
            limit=1000, resolved=None
        )
        for v in violations:
            original = v.get("timestamp", "")
            sanitized = original.replace(":", "-").replace(".", "-").replace("T", "-")
            if sanitized == timestamp_id:
                return original
        # Fallback: return as-is
        return timestamp_id

    def on_key(self, event: events.Key) -> None:
        """Handle arrow key navigation for violation cards."""
        focused = self.app.focused

        # Only handle if we're focused on a button inside a violation card
        if not isinstance(focused, Button):
            return

        # Find the parent ViolationCard
        parent = focused.parent
        while parent and not isinstance(parent, ViolationCard):
            parent = parent.parent

        if not parent:
            return

        # Get all violation cards in the current list
        try:
            active_tab = self.query_one("#filter-tabs", TabbedContent).active
            list_id_map = {
                "filter-all": "#violations-list-all",
                "filter-tool-permission": "#violations-list-tool",
                "filter-secret": "#violations-list-secret",
                "filter-redaction": "#violations-list-redaction",
                "filter-directory": "#violations-list-directory",
                "filter-injection": "#violations-list-injection",
                "filter-jailbreak": "#violations-list-jailbreak",
                "filter-ssrf": "#violations-list-ssrf",
                "filter-config-exfil": "#violations-list-config-exfil",
                "filter-pii": "#violations-list-pii",
                "filter-transcript-secret": "#violations-list-transcript-secret",
                "filter-transcript-pii": "#violations-list-transcript-pii",
                "filter-transcript-pi": "#violations-list-transcript-pi",
                "filter-annotation": "#violations-list-annotation",
                "filter-image-secret": "#violations-list-image-secret",
                "filter-image-pii": "#violations-list-image-pii",
            }
            list_id = list_id_map.get(active_tab)
            if not list_id:
                return

            violations_list = self.query_one(list_id, VerticalScroll)
            cards = list(violations_list.query(ViolationCard))

            if not cards:
                return

            current_index = cards.index(parent)

        except Exception:
            return

        # Handle arrow keys
        if event.key == "down":
            # Move to next violation card
            if current_index < len(cards) - 1:
                next_card = cards[current_index + 1]
                # Focus first button in next card
                buttons = list(next_card.query(Button))
                if buttons:
                    buttons[0].focus()
                    event.prevent_default()
                    event.stop()

        elif event.key == "up":
            # Move to previous violation card
            if current_index > 0:
                prev_card = cards[current_index - 1]
                # Focus first button in previous card
                buttons = list(prev_card.query(Button))
                if buttons:
                    buttons[0].focus()
                    event.prevent_default()
                    event.stop()

        elif event.key == "left":
            # Move to previous button in same card
            buttons = list(parent.query(Button))
            try:
                current_button_index = buttons.index(focused)
                if current_button_index > 0:
                    buttons[current_button_index - 1].focus()
                    event.prevent_default()
                    event.stop()
            except ValueError:
                pass  # intentionally silent — index lookup may fail

        elif event.key == "right":
            # Move to next button in same card
            buttons = list(parent.query(Button))
            try:
                current_button_index = buttons.index(focused)
                if current_button_index < len(buttons) - 1:
                    buttons[current_button_index + 1].focus()
                    event.prevent_default()
                    event.stop()
            except ValueError:
                pass  # intentionally silent — index lookup may fail

    def action_filter_all(self) -> None:
        """Show all violations (triggered by '1' key)."""
        try:
            filter_tabs = self.query_one("#filter-tabs", TabbedContent)
            filter_tabs.active = "filter-all"
        except Exception:
            pass

    def action_filter_tool(self) -> None:
        """Filter tool permission violations (triggered by '2' key)."""
        try:
            filter_tabs = self.query_one("#filter-tabs", TabbedContent)
            filter_tabs.active = "filter-tool-permission"
        except Exception:
            pass

    def action_filter_secret(self) -> None:
        """Filter secret violations (triggered by '3' key)."""
        try:
            filter_tabs = self.query_one("#filter-tabs", TabbedContent)
            filter_tabs.active = "filter-secret"
        except Exception:
            pass

    def action_filter_directory(self) -> None:
        """Filter directory violations (triggered by '4' key)."""
        try:
            filter_tabs = self.query_one("#filter-tabs", TabbedContent)
            filter_tabs.active = "filter-directory"
        except Exception:
            pass

    def action_filter_injection(self) -> None:
        """Filter prompt injection violations (triggered by '5' key)."""
        try:
            filter_tabs = self.query_one("#filter-tabs", TabbedContent)
            filter_tabs.active = "filter-injection"
        except Exception:
            pass

    def action_filter_redaction(self) -> None:
        """Filter secret redaction violations (triggered by '6' key)."""
        try:
            filter_tabs = self.query_one("#filter-tabs", TabbedContent)
            filter_tabs.active = "filter-redaction"
        except Exception:
            pass

    def show_violation_details(self, timestamp: str) -> None:
        """Show detailed information about a violation in a modal."""
        violations = self.violation_logger.get_recent_violations(
            limit=1000, resolved=None
        )
        violation = next(
            (v for v in violations if v.get("timestamp") == timestamp), None
        )

        if violation:
            self.app.push_screen(ViolationDetailsModal(violation))
        else:
            self.app.notify("Violation not found", severity="error")

    def show_correlated_violation(self, timestamp: str) -> None:
        """Show correlated PreToolUse context or paired violation (#366)."""
        violations = self.violation_logger.get_recent_violations(
            limit=1000, resolved=None
        )
        source = next((v for v in violations if v.get("timestamp") == timestamp), None)

        if not source:
            self.app.notify("Violation not found", severity="error")
            return

        source_ctx = source.get("context", {})
        tool_use_id = source_ctx.get("tool_use_id")
        if not tool_use_id:
            self.app.notify("No correlation ID on this violation", severity="warning")
            return

        source_hook = source_ctx.get("hook_event", "")

        # Check for embedded PreToolUse context (saved when PostToolUse logs a violation)
        pretool_ctx = source_ctx.get("pretool_context")
        if pretool_ctx:
            correlated_view = {
                "correlation": "PreToolUse context for this tool invocation",
                "tool_use_id": tool_use_id,
                "pretool_context": pretool_ctx,
            }
            self.app.push_screen(ViolationDetailsModal(correlated_view))
            return

        # Fall back: search for a paired violation with same tool_use_id
        correlated = None
        for v in violations:
            v_ctx = v.get("context", {})
            if (
                v_ctx.get("tool_use_id") == tool_use_id
                and v.get("timestamp") != timestamp
                and v_ctx.get("hook_event") != source_hook
            ):
                correlated = v
                break

        if correlated:
            self.app.push_screen(ViolationDetailsModal(correlated))
        else:
            self.app.notify(
                "No correlated PreToolUse data found",
                severity="information",
            )
