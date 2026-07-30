#!/usr/bin/env python3
"""
Regex Tester Panel

Interactive regex pattern testing with ReDoS validation
and config integration for allowlist patterns.
"""

import re
from typing import List, Tuple

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static, Input, Button, Select, Checkbox, TextArea

from ai_guardian.config.utils import validate_regex_pattern
from ai_guardian.tui.schema_defaults import ConfigSaveMixin

MAX_MATCHES_DISPLAYED = 100

CONFIG_SECTIONS = {
    "prompt_injection": ("prompt_injection", "allowlist_patterns"),
    "context_poisoning": ("context_poisoning", "allowlist_patterns"),
    "scan_pii": ("scan_pii", "allowlist_patterns"),
    "secret_scanning": ("secret_scanning", "allowlist_patterns"),
}


def find_matches(
    pattern: str,
    text: str,
    flags: int = 0,
    max_matches: int = MAX_MATCHES_DISPLAYED,
) -> Tuple[bool, str, List[dict]]:
    """Find regex matches in text.

    Args:
        pattern: Regex pattern string.
        text: Text to search.
        flags: re flags (e.g. re.IGNORECASE | re.MULTILINE).
        max_matches: Maximum matches to return.

    Returns:
        (is_valid, error_message, matches_list)
        matches_list items have keys: text, start, end, line.
    """
    if not pattern:
        return True, "", []

    if not validate_regex_pattern(pattern):
        return False, "Pattern failed ReDoS safety check", []

    try:
        compiled = re.compile(pattern, flags)
    except re.error as e:
        return False, f"Invalid regex: {e}", []

    if not text:
        return True, "", []

    lines = text.split("\n")
    line_starts = []
    pos = 0
    for line in lines:
        line_starts.append(pos)
        pos += len(line) + 1

    def _line_for_pos(p: int) -> int:
        for i in range(len(line_starts) - 1, -1, -1):
            if p >= line_starts[i]:
                return i + 1
        return 1

    matches = []
    for i, match in enumerate(compiled.finditer(text)):
        if i >= max_matches:
            break
        matches.append(
            {
                "text": match.group(),
                "start": match.start(),
                "end": match.end(),
                "line": _line_for_pos(match.start()),
            }
        )

    return True, "", matches


class RegexTesterContent(ConfigSaveMixin, Container):
    """Content widget for the Regex Tester panel."""

    CONFIG_SECTION = "prompt_injection"

    CSS = """
    RegexTesterContent {
        height: 100%;
    }

    #regex-header {
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

    .setting-row {
        margin: 0.5 0;
        height: auto;
    }

    .flag-row {
        margin: 0.5 0;
        height: auto;
    }

    #regex-test-text {
        height: 8;
        border: solid $primary;
        background: $surface;
    }

    #regex-match-details {
        margin: 1 0;
        padding: 1;
        background: $surface;
        border: solid $primary;
        min-height: 4;
    }

    Input:focus {
        border-left: heavy $accent;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Regex Tester[/bold]", id="regex-header")

        with VerticalScroll():
            with Container(classes="section"):
                yield Static("[bold]Regex Pattern[/bold]", classes="section-title")
                yield Input(
                    placeholder="Enter regex pattern to test",
                    id="regex-pattern-input",
                )
                yield Static("", id="regex-validation-status")
                with Horizontal(classes="flag-row"):
                    yield Checkbox(
                        "Case Insensitive", value=True, id="regex-flag-ignorecase"
                    )
                    yield Checkbox("Multiline", value=True, id="regex-flag-multiline")

            with Container(classes="section"):
                yield Static("[bold]Sample Text[/bold]", classes="section-title")
                yield Static(
                    "[dim]Paste or type text to test your pattern against.[/dim]",
                    classes="setting-row",
                )
                yield TextArea(id="regex-test-text")

            with Container(classes="section"):
                yield Static("[bold]Match Results[/bold]", classes="section-title")
                yield Static("", id="regex-match-summary")
                yield Static("", id="regex-match-details")

            with Container(classes="section"):
                yield Static("[bold]Add to Config[/bold]", classes="section-title")
                yield Static(
                    "[dim]Add the tested pattern to an allowlist_patterns config section.[/dim]",
                    classes="setting-row",
                )
                yield Select(
                    [
                        ("Prompt Injection Allowlist", "prompt_injection"),
                        ("Context Poisoning Allowlist", "context_poisoning"),
                        ("PII Detection Allowlist", "scan_pii"),
                        ("Secret Scanning Allowlist", "secret_scanning"),
                    ],
                    value="prompt_injection",
                    id="regex-target-section",
                )
                yield Button("Add Pattern to Config", id="regex-add-to-config")

    def on_mount(self) -> None:
        self._run_matching()

    def refresh_content(self) -> None:
        try:
            self.query_one("#regex-pattern-input", Input).value = ""
            self.query_one("#regex-test-text", TextArea).clear()
        except Exception:
            pass
        self._run_matching()

    def action_refresh(self) -> None:
        self.refresh_content()
        self.app.notify("Regex tester reset", severity="information")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "regex-pattern-input":
            self._run_matching()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "regex-test-text":
            self._run_matching()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id in ("regex-flag-ignorecase", "regex-flag-multiline"):
            self._run_matching()

    def _get_flags(self) -> int:
        flags = 0
        try:
            if self.query_one("#regex-flag-ignorecase", Checkbox).value:
                flags |= re.IGNORECASE
        except Exception:
            flags |= re.IGNORECASE
        try:
            if self.query_one("#regex-flag-multiline", Checkbox).value:
                flags |= re.MULTILINE
        except Exception:
            flags |= re.MULTILINE
        return flags

    def _run_matching(self) -> None:
        try:
            pattern = self.query_one("#regex-pattern-input", Input).value.strip()
        except Exception:
            return
        try:
            text = self.query_one("#regex-test-text", TextArea).text
        except Exception:
            text = ""

        if not pattern:
            self._update_status("")
            self._update_results("[dim]Enter a pattern to see results[/dim]", "")
            return

        flags = self._get_flags()
        is_valid, error, matches = find_matches(pattern, text, flags)

        if not is_valid:
            self._update_status(f"[red]{error}[/red]")
            self._update_results(f"[red]{error}[/red]", "")
            return

        self._update_status("[green]Pattern is valid (ReDoS-safe)[/green]")

        if not text:
            self._update_results("[dim]Enter sample text to see matches[/dim]", "")
            return

        count = len(matches)
        if count == 0:
            self._update_results("[yellow]0 matches[/yellow]", "")
            return

        suffix = ""
        if count >= MAX_MATCHES_DISPLAYED:
            suffix = f" (showing first {MAX_MATCHES_DISPLAYED})"
        summary = (
            f"[green]{count} match{'es' if count != 1 else ''} found[/green]{suffix}"
        )

        detail_lines = []
        for i, m in enumerate(matches, 1):
            matched_text = m["text"]
            if len(matched_text) > 80:
                matched_text = matched_text[:77] + "..."
            detail_lines.append(
                f"  {i}. \"{matched_text}\" at line {m['line']}, "
                f"positions {m['start']}-{m['end']}"
            )

        self._update_results(summary, "\n".join(detail_lines))

    def _update_status(self, text: str) -> None:
        try:
            self.query_one("#regex-validation-status", Static).update(text)
        except Exception:
            pass

    def _update_results(self, summary: str, details: str) -> None:
        try:
            self.query_one("#regex-match-summary", Static).update(summary)
        except Exception:
            pass
        try:
            self.query_one("#regex-match-details", Static).update(details)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "regex-add-to-config":
            self._add_pattern_to_config()

    def _add_pattern_to_config(self) -> None:
        try:
            pattern = self.query_one("#regex-pattern-input", Input).value.strip()
        except Exception:
            return

        if not pattern:
            self.app.notify("Please enter a pattern first", severity="error")
            return

        if not validate_regex_pattern(pattern):
            self.app.notify(
                "Pattern is not safe (ReDoS risk or invalid syntax)", severity="error"
            )
            return

        try:
            re.compile(pattern)
        except re.error as e:
            self.app.notify(f"Invalid regex: {e}", severity="error")
            return

        try:
            target = self.query_one("#regex-target-section", Select).value
        except Exception:
            target = "prompt_injection"

        if target not in CONFIG_SECTIONS:
            self.app.notify("Invalid target section", severity="error")
            return

        section_key, field_key = CONFIG_SECTIONS[target]

        try:
            config = self._load_full_config()

            if section_key not in config:
                config[section_key] = {}
            if field_key not in config[section_key]:
                config[section_key][field_key] = []

            existing = config[section_key][field_key]
            for entry in existing:
                entry_str = (
                    entry if isinstance(entry, str) else entry.get("pattern", "")
                )
                if entry_str == pattern:
                    self.app.notify(
                        f"Pattern already in {section_key} {field_key}",
                        severity="warning",
                    )
                    return

            config[section_key][field_key].append(pattern)

            self._write_full_config(config)

            section_labels = {
                "prompt_injection": "Prompt Injection",
                "context_poisoning": "Context Poisoning",
                "scan_pii": "PII Detection",
                "secret_scanning": "Secret Scanning",
            }
            label = section_labels.get(section_key, section_key)
            self.app.notify(
                f"Added to {label} allowlist: {pattern}",
                severity="success",
            )

        except Exception as e:
            self.app.notify(f"Error saving pattern: {e}", severity="error")
