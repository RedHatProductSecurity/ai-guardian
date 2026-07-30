"""
Annotations Tab Content

View and configure inline/block annotation suppression settings.
"""

from typing import Dict, Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static, Button, Input, Label

from ai_guardian.tui.schema_defaults import ConfigSaveMixin, SchemaDefaultsMixin
from ai_guardian.tui.widgets import TimeBasedToggle


class AnnotationsContent(ConfigSaveMixin, SchemaDefaultsMixin, Container):
    """Content widget for Annotations tab."""

    CONFIG_SECTION = "annotations"
    SCHEMA_SECTION = "annotations"
    SCHEMA_FIELDS = []

    CSS = """
    AnnotationsContent {
        height: 100%;
    }

    #annotations-header {
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

    .setting-row Label {
        margin: 0 1 0 0;
        width: auto;
    }

    .setting-row Input {
        width: 50;
    }

    .setting-row Button {
        margin: 0 0 0 1;
    }

    .alias-list {
        padding: 1;
        min-height: 2;
        max-height: 8;
        margin: 0.5 0;
        background: $surface;
        border: solid $primary;
    }

    #actions {
        margin: 1 0;
        height: auto;
    }

    #actions Button {
        margin: 0 1 0 0;
    }

    Input:focus {
        border-left: heavy $accent;
        text-style: bold;
    }

    Button:focus {
        border-left: heavy $accent;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Annotation Suppression Settings[/bold]", id="annotations-header"
        )

        with VerticalScroll():
            yield TimeBasedToggle(
                title="Annotations",
                config_key="annotations_enabled",
                current_value=True,
                help_text="Enable inline/block annotations to suppress secrets and PII on specific lines",
                id="annotations_enabled_toggle",
            )

            with Container(classes="section"):
                yield Static(
                    "[bold]Hardcoded Markers (always active)[/bold]",
                    classes="section-title",
                )
                yield Static(
                    "[dim]These markers are built-in and cannot be disabled:\n\n"
                    "Inline (secrets + PII):\n"
                    "  [bold]# ai-guardian:allow[/bold]\n\n"
                    "Block (secrets + PII):\n"
                    "  [bold]# ai-guardian:begin-allow[/bold]\n"
                    "  ...lines to suppress...\n"
                    "  [bold]# ai-guardian:end-allow[/bold]\n\n"
                    "[yellow]Prompt injection, jailbreak, and config exfiltration\n"
                    "are always scanned and cannot be suppressed.[/yellow][/dim]"
                )

            # Inline allow aliases (all violations)
            with Container(classes="section"):
                yield Static(
                    "[bold]Inline Allow Aliases (secrets + PII)[/bold]",
                    classes="section-title",
                )
                yield Static(
                    "[dim]Additional markers that suppress secrets and PII on a line. User config extends defaults.[/dim]"
                )
                yield Static("", id="inline-allow-list", classes="alias-list")
                with Horizontal(classes="setting-row"):
                    yield Label("Add alias:")
                    yield Input(placeholder="e.g. nosec", id="inline-allow-input")
                    yield Button("Add", id="add-inline-allow", variant="primary")
                    yield Button(
                        "Remove Last", id="remove-inline-allow", variant="error"
                    )

            # Inline allow secrets aliases
            with Container(classes="section"):
                yield Static(
                    "[bold]Inline Allow Secrets Aliases (secrets only)[/bold]",
                    classes="section-title",
                )
                yield Static(
                    "[dim]Markers that suppress secret scanning only (not PII, prompt injection, etc.).[/dim]"
                )
                yield Static("", id="inline-allow-secrets-list", classes="alias-list")
                with Horizontal(classes="setting-row"):
                    yield Label("Add alias:")
                    yield Input(
                        placeholder="e.g. nosec", id="inline-allow-secrets-input"
                    )
                    yield Button(
                        "Add", id="add-inline-allow-secrets", variant="primary"
                    )
                    yield Button(
                        "Remove Last", id="remove-inline-allow-secrets", variant="error"
                    )

            # Block begin aliases
            with Container(classes="section"):
                yield Static(
                    "[bold]Block Begin Aliases[/bold]", classes="section-title"
                )
                yield Static(
                    "[dim]Additional markers for block-begin suppression. Extends hardcoded ai-guardian:begin-allow.[/dim]"
                )
                yield Static("", id="block-begin-list", classes="alias-list")
                with Horizontal(classes="setting-row"):
                    yield Label("Add alias:")
                    yield Input(
                        placeholder="e.g. BEGIN-SUPPRESS", id="block-begin-input"
                    )
                    yield Button("Add", id="add-block-begin", variant="primary")
                    yield Button(
                        "Remove Last", id="remove-block-begin", variant="error"
                    )

            # Block end aliases
            with Container(classes="section"):
                yield Static("[bold]Block End Aliases[/bold]", classes="section-title")
                yield Static(
                    "[dim]Additional markers for block-end suppression. Extends hardcoded ai-guardian:end-allow.[/dim]"
                )
                yield Static("", id="block-end-list", classes="alias-list")
                with Horizontal(classes="setting-row"):
                    yield Label("Add alias:")
                    yield Input(placeholder="e.g. END-SUPPRESS", id="block-end-input")
                    yield Button("Add", id="add-block-end", variant="primary")
                    yield Button("Remove Last", id="remove-block-end", variant="error")

    def on_mount(self) -> None:
        self._loading = False
        self.load_config()

    def refresh_content(self) -> None:
        self.load_config()

    def load_config(self) -> None:
        config = self._load_full_config()

        section = config.get("annotations", {})

        # Update enabled toggle
        try:
            toggle = self.query_one("#annotations_enabled_toggle", TimeBasedToggle)
            toggle.load_value(section.get("enabled", True))
        except Exception:
            pass  # Widgets may not be fully mounted yet

        # Update alias lists
        self._update_alias_display("inline-allow-list", section.get("inline_allow", []))
        self._update_alias_display(
            "inline-allow-secrets-list",
            section.get("inline_allow_secrets", ["gitleaks:allow"]),
        )
        self._update_alias_display("block-begin-list", section.get("block_begin", []))
        self._update_alias_display("block-end-list", section.get("block_end", []))

    def _update_alias_display(self, widget_id: str, aliases: list) -> None:
        widget = self.query_one(f"#{widget_id}", Static)
        if aliases:
            widget.update("\n".join(f"  [bold]{a}[/bold]" for a in aliases))
        else:
            widget.update("[dim]  (none configured)[/dim]")

    def save_config(self, updates: Dict[str, Any]) -> bool:
        config = self._load_full_config()

        if "annotations" not in config:
            config["annotations"] = {}
        config["annotations"].update(updates)

        return self._write_full_config(config)

    def _add_alias(self, config_key: str, input_id: str, list_id: str) -> None:
        input_widget = self.query_one(f"#{input_id}", Input)
        alias = input_widget.value.strip()
        if not alias:
            return

        config = self._load_full_config()
        section = config.get("annotations", {})
        current = list(section.get(config_key, []))
        if alias not in current:
            current.append(alias)
            self.save_config({config_key: current})
            self._update_alias_display(list_id, current)

        input_widget.value = ""

    def _remove_last_alias(self, config_key: str, list_id: str) -> None:
        config = self._load_full_config()
        section = config.get("annotations", {})
        current = list(section.get(config_key, []))
        if current:
            current.pop()
            self.save_config({config_key: current})
            self._update_alias_display(list_id, current)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "add-inline-allow":
            self._add_alias("inline_allow", "inline-allow-input", "inline-allow-list")
        elif button_id == "remove-inline-allow":
            self._remove_last_alias("inline_allow", "inline-allow-list")
        elif button_id == "add-inline-allow-secrets":
            self._add_alias(
                "inline_allow_secrets",
                "inline-allow-secrets-input",
                "inline-allow-secrets-list",
            )
        elif button_id == "remove-inline-allow-secrets":
            self._remove_last_alias("inline_allow_secrets", "inline-allow-secrets-list")
        elif button_id == "add-block-begin":
            self._add_alias("block_begin", "block-begin-input", "block-begin-list")
        elif button_id == "remove-block-begin":
            self._remove_last_alias("block_begin", "block-begin-list")
        elif button_id == "add-block-end":
            self._add_alias("block_end", "block-end-input", "block-end-list")
        elif button_id == "remove-block-end":
            self._remove_last_alias("block_end", "block-end-list")

    def on_time_based_toggle_changed(self, event) -> None:
        if event.config_key == "annotations_enabled":
            self.save_config({"enabled": event.value})
