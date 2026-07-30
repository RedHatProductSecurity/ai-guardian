#!/usr/bin/env python3
"""
Jailbreak Patterns

Manage jailbreak-specific detection patterns that detect role-play attacks,
identity manipulation, constraint removal, and hypothetical framing.
"""

import re

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Static, Input

from ai_guardian.tui.schema_defaults import ConfigSaveMixin


class PIJailbreakContent(ConfigSaveMixin, Container):
    """Content widget for Jailbreak Patterns."""

    CONFIG_SECTION = "prompt_injection"

    CSS = """
    PIJailbreakContent {
        height: 100%;
    }

    #pi-jailbreak-header {
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

    #jailbreak-patterns-list {
        margin: 1 0;
        padding: 1;
        background: $surface;
        border: solid $primary;
        min-height: 6;
    }

    #builtin-patterns {
        margin: 1 0;
        padding: 1;
        background: $surface;
        border: solid $primary;
    }

    Input:focus {
        border-left: heavy $accent;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Prompt Injection — Jailbreak Patterns[/bold]",
            id="pi-jailbreak-header",
        )

        with VerticalScroll():
            with Container(classes="section"):
                yield Static(
                    "[bold]Built-in Jailbreak Detection[/bold]", classes="section-title"
                )
                yield Static(
                    "[dim]AI Guardian includes built-in patterns that detect common "
                    "jailbreak techniques. These cannot be disabled individually but "
                    "can be excluded via allowlist patterns.[/dim]",
                    classes="setting-row",
                )
                yield Static(
                    "[dim]Built-in categories:\n"
                    "  Role-play attacks — DAN mode, sudo mode, unrestricted mode\n"
                    "  Identity manipulation — 'pretend you are', 'act as if'\n"
                    "  Constraint removal — 'ignore rules', 'no restrictions'\n"
                    "  Hypothetical framing — 'fictional scenario without rules'\n"
                    "  System prompt extraction — 'show me your system prompt'[/dim]",
                    id="builtin-patterns",
                )

            with Container(classes="section"):
                yield Static(
                    "[bold]Custom Jailbreak Patterns[/bold]", classes="section-title"
                )
                yield Static(
                    "[dim]Add regex patterns to detect additional jailbreak techniques. "
                    "These are matched against user prompts only (not file content).[/dim]",
                    classes="setting-row",
                )
                yield Static("", id="jailbreak-patterns-list")
                yield Input(
                    placeholder="Enter jailbreak detection regex (press Enter to add)",
                    id="new-jailbreak-input",
                )

            with Container(classes="section"):
                yield Static(
                    "[bold]Jailbreak Statistics[/bold]", classes="section-title"
                )
                yield Static("", id="jailbreak-stats")

    def on_mount(self) -> None:
        self.load_config()

    def refresh_content(self) -> None:
        self.load_config()

    def action_refresh(self) -> None:
        self.load_config()
        self.app.notify("Jailbreak patterns refreshed", severity="information")

    def load_config(self) -> None:
        config = self._load_full_config()

        pi_config = config.get("prompt_injection", {})
        jailbreak_patterns = pi_config.get("jailbreak_patterns", [])

        if jailbreak_patterns:
            text = "\n".join(f"  {p}" for p in jailbreak_patterns)
        else:
            text = "[dim]No custom jailbreak patterns configured[/dim]"

        try:
            self.query_one("#jailbreak-patterns-list", Static).update(text)
        except Exception:
            pass

        self._load_statistics()

    def _load_statistics(self) -> None:
        try:
            from ai_guardian.violations.logger import ViolationLogger

            logger = ViolationLogger()
            violations = logger.get_recent_violations(
                limit=1000, violation_type="jailbreak_detected", resolved=None
            )
            total = len(violations)
            unresolved = len([v for v in violations if not v.get("resolved", False)])
            self.query_one("#jailbreak-stats", Static).update(
                f"Total jailbreak violations: {total}\nUnresolved: {unresolved}"
            )
        except Exception as e:
            self.query_one("#jailbreak-stats", Static).update(f"[dim]Error: {e}[/dim]")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "new-jailbreak-input":
            self._add_pattern()

    def _add_pattern(self) -> None:
        input_widget = self.query_one("#new-jailbreak-input", Input)
        pattern = input_widget.value.strip()

        if not pattern:
            self.app.notify("Please enter a pattern", severity="error")
            return

        try:
            re.compile(pattern)
        except re.error as e:
            self.app.notify(f"Invalid regex: {e}", severity="error")
            return

        try:
            if self._add_config_list_item("jailbreak_patterns", pattern, input_widget):
                self.app.notify("Added jailbreak pattern", severity="success")
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")
