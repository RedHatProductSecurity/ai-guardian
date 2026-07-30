#!/usr/bin/env python3
"""
Directory Protection Tab Content

Manage directory_exclusions configuration for .ai-read-deny blocking.
"""

import json
from pathlib import Path
from typing import List

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static, Button, Input, Label, Checkbox
from textual.message import Message

from ai_guardian.config.utils import get_config_dir, get_project_config_path
from ai_guardian.tui.schema_defaults import ConfigSaveMixin


class PathEntry(Container):
    """Widget for displaying a single exclusion path with controls."""

    CSS = """
    PathEntry {
        height: auto;
        margin: 0 0 1 0;
        border: solid $primary;
        padding: 1;
    }

    PathEntry .path-text {
        width: 100%;
        color: $accent;
        margin: 0 0 0.5 0;
    }

    PathEntry .button-row {
        width: 100%;
        height: auto;
        align: right middle;
    }

    PathEntry Button {
        margin: 0 0 0 1;
    }
    """

    class RemovePressed(Message):
        """Message sent when remove button is pressed."""

        def __init__(self, index: int):
            super().__init__()
            self.index = index

    def __init__(self, index: int, path: str, **kwargs):
        """
        Initialize path entry.

        Args:
            index: Index of this entry in the list
            path: The exclusion path
        """
        super().__init__(**kwargs)
        self.index = index
        self.path = path

    def compose(self) -> ComposeResult:
        """Compose the path entry widgets."""
        yield Static(f"[bold]{self.path}[/bold]", classes="path-text")

        with Horizontal(classes="button-row"):
            yield Button(
                "Remove", variant="error", id=f"remove_{self.index}", classes="compact"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        event.stop()  # Prevent event bubbling
        if event.button.id.startswith("remove_"):
            self.post_message(self.RemovePressed(self.index))


class DirectoryProtectionContent(ConfigSaveMixin, Container):
    """Content widget for Directory Protection tab."""

    CONFIG_SECTION = "directory_rules"

    CSS = """
    DirectoryProtectionContent {
        height: 100%;
    }

    #directory-protection-header {
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

    .warning-box {
        margin: 1 0;
        padding: 1;
        background: $warning;
        border: solid $error;
    }

    .setting-row {
        margin: 0.5 0;
        height: auto;
        align: left middle;
    }

    .setting-row Label {
        margin: 0 2 0 0;
        width: auto;
    }

    .setting-row Checkbox {
        margin: 0 2 0 0;
    }

    #paths-list {
        margin: 1 0;
        min-height: 8;
        max-height: 16;
    }

    #add-path-section {
        margin: 1 0;
        padding: 1;
        background: $surface;
        border: solid $accent;
    }

    #add-path-section Input {
        width: 60;
        margin: 0 1 0 0;
    }

    #markers-list {
        margin: 1 0;
        padding: 1;
        background: $surface;
        min-height: 8;
    }
    """

    @property
    def _is_project_scope(self) -> bool:
        try:
            return self.app.config_scope == "project"
        except Exception:
            return False

    def _get_config_path(self) -> Path:
        if self._is_project_scope:
            project_path = get_project_config_path()
            if project_path:
                return project_path
            from ai_guardian.config.utils import _find_git_root

            root = _find_git_root() or Path.cwd()
            return root / ".ai-guardian" / "ai-guardian.json"
        return get_config_dir() / "ai-guardian.json"

    def compose(self) -> ComposeResult:
        """Compose the directory protection tab content."""
        yield Static(
            "[bold]Directory Protection & Exclusions[/bold]",
            id="directory-protection-header",
        )

        with VerticalScroll():
            # Warning section
            with Container(classes="warning-box"):
                yield Static(
                    "[bold]⚠️  CRITICAL: .ai-read-deny markers ALWAYS take precedence[/bold]\n\n"
                    "[dim].ai-read-deny marker files CANNOT be overridden by any configuration. "
                    "They provide absolute protection for sensitive directories.[/dim]"
                )

            # Exclusions toggle section
            with Container(classes="section"):
                yield Static(
                    "[bold]Directory Exclusions[/bold]", classes="section-title"
                )

                with Horizontal(classes="setting-row"):
                    yield Label("Exclusions Enabled:")
                    yield Checkbox("", id="exclusions-enabled")

                yield Static(
                    "\n[dim]When enabled, paths in the exclusion list below will bypass .ai-read-deny blocking. "
                    "However, explicit .ai-read-deny markers still block access.[/dim]"
                )

            # Exclusion paths section
            with Container(classes="section"):
                yield Static("[bold]Exclusion Paths[/bold]", classes="section-title")
                yield Static(
                    "[dim]Directories to exclude from .ai-read-deny blocking (supports ~, *, **)[/dim]",
                    classes="section-title",
                )

                with VerticalScroll(id="paths-list"):
                    yield Static("[dim]No exclusion paths configured[/dim]")

            # Add new path section
            with Container(id="add-path-section"):
                yield Static("[bold]Add Exclusion Path[/bold]", classes="section-title")

                with Horizontal(classes="setting-row"):
                    yield Input(
                        placeholder="~/project/build/** or /tmp/*", id="new-path-input"
                    )
                    yield Button("Add Path", variant="success", id="add-path-button")

                yield Static(
                    "\n[dim]Pattern syntax:[/dim]\n"
                    "  • [bold]~[/bold] - Expands to home directory\n"
                    "  • [bold]*[/bold] - Matches single directory level\n"
                    "  • [bold]**[/bold] - Matches recursively\n"
                    "  • Examples: ~/project/build/**, /tmp/*, ~/.cache/**"
                )

            # Active markers section
            with Container(classes="section"):
                yield Static(
                    "[bold]Active .ai-read-deny Markers[/bold]", classes="section-title"
                )
                yield Static(
                    "[dim]Directories with .ai-read-deny files (scanned from current working directory)[/dim]",
                    classes="section-title",
                )

                yield Static("", id="markers-list")
                yield Button(
                    "Scan for Markers", variant="primary", id="scan-markers-button"
                )

    def on_mount(self) -> None:
        """Load configuration when mounted."""
        self.load_config()
        self.scan_markers()

    def refresh_content(self) -> None:
        """Refresh configuration (called by parent app)."""
        self.load_config()
        self.scan_markers()

    def load_config(self) -> None:
        """Load and display directory protection configuration."""
        config_path = self._get_config_path()

        # Load config
        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                self.app.notify(f"Error loading config: {e}", severity="error")
                return

        # Load directory exclusions
        dir_exclusions = config.get("directory_exclusions", {})
        enabled = dir_exclusions.get("enabled", False)
        paths = dir_exclusions.get("paths", [])

        # Update enabled checkbox
        try:
            self.query_one("#exclusions-enabled", Checkbox).value = enabled
        except Exception:
            pass  # Widget may not be mounted yet

        # Update paths list
        self.update_paths_list(paths)

    def update_paths_list(self, paths: List[str]) -> None:
        """Update the exclusion paths list display."""
        try:
            list_container = self.query_one("#paths-list", VerticalScroll)

            # Remove all existing children
            list_container.remove_children()

            # Add path entries
            if paths:
                for idx, path in enumerate(paths):
                    list_container.mount(PathEntry(idx, path))
            else:
                list_container.mount(Static("[dim]No exclusion paths configured[/dim]"))

        except Exception as e:
            self.app.notify(f"Error updating paths list: {e}", severity="error")

    def scan_markers(self) -> None:
        """Scan for .ai-read-deny markers in the current directory."""
        try:
            cwd = Path.cwd()
            markers = []

            # Recursively find .ai-read-deny files
            for marker_file in cwd.rglob(".ai-read-deny"):
                if marker_file.is_file():
                    markers.append(str(marker_file.parent.relative_to(cwd)))

            # Update markers list
            markers_widget = self.query_one("#markers-list", Static)
            if markers:
                markers_text = "\n".join(f"  • ./{path}" for path in sorted(markers))
                markers_widget.update(
                    f"[status-warn]Found {len(markers)} markers:[/status-warn]\n{markers_text}"
                )
            else:
                markers_widget.update(
                    "[dim]No .ai-read-deny markers found in current directory[/dim]"
                )

        except Exception as e:
            self.app.notify(f"Error scanning for markers: {e}", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "add-path-button":
            self.add_path()
        elif event.button.id == "scan-markers-button":
            self.scan_markers()
            self.app.notify(
                "✓ Scanned for .ai-read-deny markers", severity="information"
            )

    def on_path_entry_remove_pressed(self, message: PathEntry.RemovePressed) -> None:
        """Handle remove button press on path entry."""
        self.remove_path(message.index)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox toggle."""
        if event.checkbox.id == "exclusions-enabled":
            self.save_enabled(event.value)

    def add_path(self) -> None:
        """Add a new exclusion path."""
        path = self.query_one("#new-path-input", Input).value.strip()

        if not path:
            self.app.notify("Please enter a path", severity="error")
            return

        try:
            config = self._load_full_config()

            if "directory_exclusions" not in config:
                config["directory_exclusions"] = {}
            if "paths" not in config["directory_exclusions"]:
                config["directory_exclusions"]["paths"] = []

            # Check if path already exists
            if path in config["directory_exclusions"]["paths"]:
                self.app.notify("Path already exists", severity="warning")
                return

            config["directory_exclusions"]["paths"].append(path)

            self._write_full_config(config)

            # Clear input
            self.query_one("#new-path-input", Input).value = ""

            self.load_config()
            self.app.notify(f"✓ Added exclusion path: {path}", severity="success")

        except Exception as e:
            self.app.notify(f"Error adding path: {e}", severity="error")

    def remove_path(self, index: int) -> None:
        """Remove an exclusion path."""
        try:
            config = self._load_full_config()
            if not config:
                return

            if (
                "directory_exclusions" in config
                and "paths" in config["directory_exclusions"]
            ):
                paths = config["directory_exclusions"]["paths"]
                if 0 <= index < len(paths):
                    removed_path = paths.pop(index)

                    self._write_full_config(config)

                    self.load_config()
                    self.app.notify(
                        f"✓ Removed exclusion path: {removed_path}", severity="success"
                    )

        except Exception as e:
            self.app.notify(f"Error removing path: {e}", severity="error")

    def save_enabled(self, enabled: bool) -> None:
        """Save the exclusions enabled state."""
        try:
            config = self._load_full_config()

            if "directory_exclusions" not in config:
                config["directory_exclusions"] = {}

            config["directory_exclusions"]["enabled"] = enabled

            self._write_full_config(config)

            status = "enabled" if enabled else "disabled"
            self.app.notify(f"✓ Directory exclusions {status}", severity="success")

        except Exception as e:
            self.app.notify(f"Error saving enabled state: {e}", severity="error")

    def action_refresh(self) -> None:
        """Refresh configuration (triggered by 'r' key)."""
        self.load_config()
        self.scan_markers()
        self.app.notify("Directory protection refreshed", severity="information")
