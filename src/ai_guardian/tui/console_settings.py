#!/usr/bin/env python3
"""
Console Settings Panel

Manage console preferences: editor color theme, UI color theme, preferred UI toolkit.
"""

import logging
import json

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static, Select, Label

from ai_guardian.config.utils import get_config_dir
from ai_guardian.tui.schema_defaults import (
    SchemaDefaultsMixin,
    save_global_config_field,
)

logger = logging.getLogger(__name__)

THEME_OPTIONS = [
    ("Monokai", "monokai"),
    ("VS Code Dark", "vscode_dark"),
    ("Dracula", "dracula"),
    ("GitHub Light", "github_light"),
]

DEFAULT_THEME = "monokai"

UI_TOOLKIT_OPTIONS = [
    ("Auto (cascade)", "auto"),
    ("Tkinter (native)", "tkinter"),
    ("NiceGUI (browser)", "nicegui"),
    ("Textual (terminal)", "textual"),
    ("Headless (no UI)", "headless"),
]

DEFAULT_UI_TOOLKIT = "auto"

COLOR_THEME_OPTIONS = [
    ("Default (Blue)", "default"),
    ("Classic Green", "classic_green"),
    ("High Contrast", "high_contrast"),
    ("Solarized", "solarized"),
]

DEFAULT_COLOR_THEME = "default"


def load_editor_theme() -> str:
    """Load the editor theme from config. Returns default if not set."""
    config_dir = get_config_dir()
    config_path = config_dir / "ai-guardian.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            theme = config.get("console", {}).get("editor_theme", DEFAULT_THEME)
            valid_themes = [t[1] for t in THEME_OPTIONS]
            if theme in valid_themes:
                return theme
        except Exception as e:
            logger.warning("Failed to read config: %s", e)
    return DEFAULT_THEME


def load_preferred_ui() -> str:
    """Load the preferred UI toolkit from config. Returns default if not set."""
    config_dir = get_config_dir()
    config_path = config_dir / "ai-guardian.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            val = config.get("console", {}).get("preferred_ui", DEFAULT_UI_TOOLKIT)
            valid = [t[1] for t in UI_TOOLKIT_OPTIONS]
            if val in valid:
                return val
        except Exception as e:
            logger.warning("Failed to read config: %s", e)
    return DEFAULT_UI_TOOLKIT


def load_preferred_color_theme() -> str:
    """Load the preferred color theme from config. Returns default if not set."""
    config_dir = get_config_dir()
    config_path = config_dir / "ai-guardian.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            val = config.get("console", {}).get("preferred_theme", DEFAULT_COLOR_THEME)
            valid = [t[1] for t in COLOR_THEME_OPTIONS]
            if val in valid:
                return val
        except Exception as e:
            logger.warning("Failed to read config: %s", e)
    return DEFAULT_COLOR_THEME


def save_preferred_ui(value: str) -> tuple:
    """Save the preferred UI toolkit to config. Returns (success, error_message)."""
    return save_global_config_field("console", "preferred_ui", value)


def save_editor_theme(theme: str) -> tuple:
    """Save the editor theme to config. Returns (success, error_message)."""
    return save_global_config_field("console", "editor_theme", theme)


def save_preferred_color_theme(theme: str) -> tuple:
    """Save the preferred color theme to config. Returns (success, error_message)."""
    return save_global_config_field("console", "preferred_theme", theme)


class ConsoleSettingsContent(SchemaDefaultsMixin, Container):
    """Content widget for Console Settings panel."""

    SCHEMA_SECTION = "console"
    SCHEMA_FIELDS = ["editor_theme", "preferred_ui", "preferred_theme"]

    CSS = """
    ConsoleSettingsContent {
        height: 100%;
    }

    #console-settings-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    .setting-row {
        height: auto;
        margin: 1 2;
        padding: 1;
    }

    .setting-row Label {
        width: 20;
        margin: 0 1 0 0;
    }

    .setting-row Select {
        width: 30;
    }

    #console-info {
        margin: 2 2;
        padding: 1;
        color: $text-muted;
    }

    #console-status {
        margin: 1 2;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Console Settings[/bold]", id="console-settings-header")

        with VerticalScroll():
            with Horizontal(classes="setting-row"):
                yield Label("Color Theme:")
                yield Select(
                    COLOR_THEME_OPTIONS,
                    value=DEFAULT_COLOR_THEME,
                    id="color-theme-select",
                    allow_blank=False,
                )

            with Horizontal(classes="setting-row"):
                yield Label("Editor Theme:")
                yield Select(
                    THEME_OPTIONS,
                    value=DEFAULT_THEME,
                    id="editor-theme-select",
                    allow_blank=False,
                )

            with Horizontal(classes="setting-row"):
                yield Label("Preferred UI:")
                yield Select(
                    UI_TOOLKIT_OPTIONS,
                    value=DEFAULT_UI_TOOLKIT,
                    id="preferred-ui-select",
                    allow_blank=False,
                )

            yield Static("", id="console-status")

            yield Static(
                "[bold]Color Theme Options[/bold]\n\n"
                "  [bold]Default (Blue)[/bold] — Material dark with blue accents (default)\n"
                "  [bold]Classic Green[/bold] — Original AI Guardian green brand palette\n"
                "  [bold]High Contrast[/bold] — WCAG AA accessible, maximum contrast\n"
                "  [bold]Solarized[/bold] — Solarized dark variant with teal accents\n\n"
                "[bold]Editor Theme Options[/bold]\n\n"
                "  [bold]Monokai[/bold] — Dark theme with vibrant colors (default)\n"
                "  [bold]VS Code Dark[/bold] — Dark theme matching VS Code defaults\n"
                "  [bold]Dracula[/bold] — Dark purple-accented theme\n"
                "  [bold]GitHub Light[/bold] — Light theme matching GitHub style\n\n"
                "[bold]UI Toolkit Options[/bold]\n\n"
                "  [bold]Auto[/bold] — Cascade: tkinter → NiceGUI → Textual → headless (default)\n"
                "  [bold]Tkinter[/bold] — Native OS popup (requires Tcl/Tk)\n"
                "  [bold]NiceGUI[/bold] — Browser-based dialog\n"
                "  [bold]Textual[/bold] — Terminal TUI (requires TTY)\n"
                "  [bold]Headless[/bold] — No interactive dialogs; ask actions use fallback\n\n"
                "[dim]Color theme affects TUI, web console, and ask dialogs.\n"
                "Editor theme affects JSON config editors only.\n"
                "Override UI toolkit with env var AI_GUARDIAN_PREFERRED_UI.\n"
                "Changes are saved immediately.[/dim]",
                id="console-info",
            )

    def on_mount(self) -> None:
        self.load_config()

    def refresh_content(self) -> None:
        self.load_config()

    def load_config(self) -> None:
        """Load console settings from config."""
        theme = load_editor_theme()
        try:
            select = self.query_one("#editor-theme-select", Select)
            select.value = theme
        except Exception:
            pass
        ui_pref = load_preferred_ui()
        try:
            select = self.query_one("#preferred-ui-select", Select)
            select.value = ui_pref
        except Exception:
            pass
        color_theme = load_preferred_color_theme()
        try:
            select = self.query_one("#color-theme-select", Select)
            select.value = color_theme
        except Exception:
            pass
        self._set_status(
            f"Color: {color_theme}, Editor: {theme}, UI: {ui_pref}", "success"
        )

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "editor-theme-select":
            theme = str(event.value)
            success, error = save_editor_theme(theme)
            if success:
                self._set_status(f"Editor theme saved: {theme}", "success")
                self.app.notify(f"Editor theme set to {theme}", severity="information")
            else:
                self._set_status(f"Save failed: {error}", "error")
                self.app.notify(f"Failed to save theme: {error}", severity="error")
        elif event.select.id == "preferred-ui-select":
            value = str(event.value)
            success, error = save_preferred_ui(value)
            if success:
                self._set_status(f"Preferred UI saved: {value}", "success")
                self.app.notify(f"Preferred UI set to {value}", severity="information")
            else:
                self._set_status(f"Save failed: {error}", "error")
                self.app.notify(
                    f"Failed to save UI preference: {error}", severity="error"
                )
        elif event.select.id == "color-theme-select":
            value = str(event.value)
            success, error = save_preferred_color_theme(value)
            if success:
                from ai_guardian.theme import set_active_theme

                set_active_theme(value)
                self._set_status(f"Color theme saved: {value}", "success")
                self.app.notify(f"Color theme set to {value}", severity="information")
            else:
                self._set_status(f"Save failed: {error}", "error")
                self.app.notify(
                    f"Failed to save color theme: {error}", severity="error"
                )

    def _set_status(self, message: str, level: str) -> None:
        try:
            status = self.query_one("#console-status", Static)
            if level == "error":
                status.update(f"[red]{message}[/red]")
            else:
                status.update(f"[green]{message}[/green]")
        except Exception:
            pass

    def action_refresh(self) -> None:
        self.load_config()
        self.app.notify("Console settings refreshed", severity="information")
