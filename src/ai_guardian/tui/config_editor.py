#!/usr/bin/env python3
"""
JSON Config Editor Panel

Raw JSON editor for ai-guardian.json with syntax highlighting,
real-time validation, schema checking, and save with backup.
"""

import json
import shutil
from pathlib import Path
from typing import List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Static, Button, TextArea

from ai_guardian.config.utils import (
    CONFIG_READ_ONLY_MESSAGE,
    get_config_dir,
    get_project_config_path,
    is_config_read_only,
)
from ai_guardian.tui.console_settings import load_editor_theme

try:
    from jsonschema import Draft7Validator, ValidationError as JsonSchemaValidationError

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


_schema_validator = None


def _get_schema_validator():
    """Get or create the cached JSON Schema validator."""
    global _schema_validator
    if not HAS_JSONSCHEMA:
        return None
    if _schema_validator is None:
        try:
            schema_path = (
                Path(__file__).parent.parent
                / "schemas"
                / "ai-guardian-config.schema.json"
            )
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            _schema_validator = Draft7Validator(schema)
        except Exception:
            return None
    return _schema_validator


def validate_json_string(text: str) -> tuple:
    """Parse JSON text and return (parsed_dict_or_None, error_message_or_None)."""
    if not text.strip():
        return None, "Empty content"
    try:
        data = json.loads(text)
        return data, None
    except json.JSONDecodeError as e:
        return None, f"Line {e.lineno}, col {e.colno}: {e.msg}"


def validate_against_schema(config: dict) -> List[str]:
    """Validate config dict against the JSON schema. Returns list of warning strings."""
    validator = _get_schema_validator()
    if not validator:
        return []
    warnings = []
    for error in validator.iter_errors(config):
        path = (
            " -> ".join(str(p) for p in error.absolute_path)
            if error.absolute_path
            else "root"
        )
        warnings.append(f"{path}: {error.message}")
    return warnings


class ConfirmSaveModal(ModalScreen):
    """Confirmation dialog before saving config."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = """
    ConfirmSaveModal {
        align: center middle;
    }

    #save-modal-container {
        width: 70;
        height: auto;
        max-height: 80%;
        background: $panel;
        border: thick $warning;
        padding: 1 2;
    }

    #save-modal-header {
        margin: 0 0 1 0;
        text-align: center;
        color: $warning;
    }

    #save-modal-content {
        margin: 1 0;
    }

    #save-modal-warnings {
        margin: 1 0;
        padding: 1;
        background: $surface;
        border: solid $warning;
        max-height: 12;
        overflow-y: auto;
    }

    #save-modal-actions {
        margin: 1 0 0 0;
        height: auto;
        align: center middle;
    }

    #save-modal-actions Button {
        margin: 0 1;
    }
    """

    def __init__(self, config_path: str, warnings: Optional[List[str]] = None):
        super().__init__()
        self._config_path = config_path
        self._warnings = warnings or []

    def compose(self) -> ComposeResult:
        with Container(id="save-modal-container"):
            yield Static("[bold]Save Configuration?[/bold]", id="save-modal-header")
            yield Static(
                f"Save changes to:\n{self._config_path}\n\n"
                "A backup will be created (.bak) before saving.",
                id="save-modal-content",
            )
            if self._warnings:
                warning_text = "[bold yellow]Schema Warnings:[/bold yellow]\n"
                for w in self._warnings[:10]:
                    warning_text += f"  [yellow]- {w}[/yellow]\n"
                if len(self._warnings) > 10:
                    warning_text += (
                        f"  [dim]... and {len(self._warnings) - 10} more[/dim]\n"
                    )
                warning_text += "\n[dim]These are non-blocking. The JSON is valid and can be saved.[/dim]"
                yield Static(warning_text, id="save-modal-warnings")
            with Horizontal(id="save-modal-actions"):
                yield Button("Save", id="confirm-save", variant="warning")
                yield Button("Cancel (ESC)", id="cancel-save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-save":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConfigEditorContent(Container):
    """JSON config editor panel with syntax highlighting and validation."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("ctrl+r", "reload", "Reload", show=True),
    ]

    CSS = """
    ConfigEditorContent {
        height: 100%;
    }

    #editor-header {
        height: auto;
        padding: 1;
        background: $primary;
        color: $text;
    }

    #editor-path {
        height: auto;
        padding: 0 1;
        color: $text-muted;
    }

    #config-text-editor {
        height: 1fr;
        min-height: 10;
        border: solid $primary;
    }

    #editor-status {
        height: auto;
        padding: 0 1;
        background: $surface;
    }

    .status-valid {
        color: $success;
    }

    .status-invalid {
        color: $error;
    }

    .status-warning {
        color: $warning;
    }

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._config_path: Optional[Path] = None
        self._schema_warnings: List[str] = []

    def compose(self) -> ComposeResult:
        self._update_config_path_from_app()
        read_only = is_config_read_only()

        header = (
            "[bold]Config Editor[/bold]  "
            "[dim]Ctrl+S[/dim] Save  "
            "[dim]Ctrl+R[/dim] Reload  "
            "[dim]Ctrl+Z[/dim] Undo"
        )
        if read_only:
            header += f"  [yellow]{CONFIG_READ_ONLY_MESSAGE}[/yellow]"

        yield Static(
            header,
            id="editor-header",
        )
        yield Static(f"[dim]{self._config_path}[/dim]", id="editor-path")

        theme = load_editor_theme()
        yield TextArea(
            "",
            language="json",
            theme=theme,
            show_line_numbers=True,
            tab_behavior="indent",
            read_only=read_only,
            id="config-text-editor",
        )

        yield Static("", id="editor-status")

    def _update_config_path_from_app(self) -> None:
        """Update _config_path based on app-level scope."""
        try:
            scope = self.app.config_scope
        except Exception:
            scope = "global"
        if scope == "project":
            project_path = get_project_config_path()
            if project_path:
                self._config_path = project_path
            else:
                from ai_guardian.config.utils import _find_git_root

                root = _find_git_root() or Path.cwd()
                self._config_path = root / ".ai-guardian" / "ai-guardian.json"
        else:
            config_dir = get_config_dir()
            self._config_path = config_dir / "ai-guardian.json"
        try:
            self.query_one("#editor-path", Static).update(
                f"[dim]{self._config_path}[/dim]"
            )
        except Exception:
            pass

    def on_mount(self) -> None:
        self.load_config()

    def on_show(self) -> None:
        """Reload theme when panel becomes visible."""
        self._apply_saved_theme()

    def refresh_content(self) -> None:
        self._update_config_path_from_app()
        self._apply_saved_theme()
        self.load_config()

    def _apply_saved_theme(self) -> None:
        """Read theme from config and apply to the editor."""
        try:
            editor = self.query_one("#config-text-editor", TextArea)
            theme = load_editor_theme()
            if editor.theme != theme:
                editor.theme = theme
        except Exception:
            pass

    def load_config(self) -> None:
        """Load config file into the editor."""
        editor = self.query_one("#config-text-editor", TextArea)
        if self._config_path and self._config_path.exists():
            try:
                content = self._config_path.read_text(encoding="utf-8")
                editor.load_text(content)
                self._update_status(content)
                if is_config_read_only():
                    self._set_status(CONFIG_READ_ONLY_MESSAGE, "status-warning")
            except Exception as e:
                editor.load_text("")
                self._set_status(f"Error loading: {e}", "status-invalid")
        else:
            editor.load_text("{}")
            self._set_status(
                "No config file found — starting with empty config", "status-warning"
            )

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "config-text-editor":
            self._update_status(event.text_area.text)

    def _update_status(self, text: str) -> None:
        """Validate JSON and update the status bar."""
        data, error = validate_json_string(text)
        if error:
            self._schema_warnings = []
            self._set_status(f"Invalid JSON: {error}", "status-invalid")
            return

        self._schema_warnings = validate_against_schema(data)
        if self._schema_warnings:
            self._set_status(
                f"Valid JSON with {len(self._schema_warnings)} schema warning(s)",
                "status-warning",
            )
        else:
            self._set_status("Valid JSON", "status-valid")

    def _set_status(self, message: str, css_class: str) -> None:
        status = self.query_one("#editor-status", Static)
        status.update(message)
        status.remove_class("status-valid", "status-invalid", "status-warning")
        status.add_class(css_class)

    def action_save(self) -> None:
        """Save config with confirmation dialog."""
        if is_config_read_only():
            self.app.notify(CONFIG_READ_ONLY_MESSAGE, severity="warning")
            return
        editor = self.query_one("#config-text-editor", TextArea)
        text = editor.text

        data, error = validate_json_string(text)
        if error:
            self.app.notify(f"Cannot save: {error}", severity="error")
            return

        def handle_confirm(confirmed: bool) -> None:
            if confirmed:
                self._do_save(text)

        self.app.push_screen(
            ConfirmSaveModal(str(self._config_path), self._schema_warnings),
            handle_confirm,
        )

    def _do_save(self, text: str) -> None:
        """Write config to disk with backup and notify."""
        success, error = self._write_config(text)
        if success:
            self.app.notify("Configuration saved", severity="information")
        else:
            self.app.notify(f"Save failed: {error}", severity="error")

    def _write_config(self, text: str) -> tuple:
        """Write config file with backup. Returns (success, error_message)."""
        if is_config_read_only():
            return False, CONFIG_READ_ONLY_MESSAGE
        try:
            if self._config_path.exists():
                backup_path = self._config_path.with_suffix(".json.bak")
                shutil.copy2(self._config_path, backup_path)

            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(text, encoding="utf-8")
            return True, None
        except Exception as e:
            return False, str(e)

    def action_reload(self) -> None:
        """Reload config from disk."""
        self.load_config()
        self.app.notify("Configuration reloaded from disk", severity="information")

    def action_refresh(self) -> None:
        """Refresh (triggered by 'r' key from parent app)."""
        self.load_config()
        self.app.notify("Configuration refreshed", severity="information")
