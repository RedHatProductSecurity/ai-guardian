#!/usr/bin/env python3
"""
Permissions Discovery Tab Content

Manage permissions_directories configuration for auto-discovering
permissions from local directories or GitHub repositories.
"""

from typing import List, Dict, Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static, Button, Input, Label, Select
from textual.message import Message

from ai_guardian.tui.schema_defaults import ConfigSaveMixin


class DirectoryEntry(Container):
    """Widget for displaying a single directory entry with controls."""

    CSS = """
    DirectoryEntry {
        height: auto;
        margin: 0 0 1 0;
        border: solid $primary;
        padding: 1;
    }

    DirectoryEntry .entry-header {
        width: 100%;
        margin: 0 0 0.5 0;
    }

    DirectoryEntry .entry-details {
        width: 100%;
        color: $text-muted;
        margin: 0 0 0.5 0;
    }

    DirectoryEntry .button-row {
        width: 100%;
        height: auto;
        align: right middle;
    }

    DirectoryEntry Button {
        margin: 0 0 0 1;
    }
    """

    class RemovePressed(Message):
        """Message sent when remove button is pressed."""

        def __init__(self, list_type: str, index: int):
            super().__init__()
            self.list_type = list_type
            self.index = index

    def __init__(self, list_type: str, index: int, entry: Dict[str, Any], **kwargs):
        """
        Initialize directory entry.

        Args:
            list_type: Either "allow" or "deny"
            index: Index of this entry in the list
            entry: The directory entry (matcher, mode, url, token_env)
        """
        super().__init__(**kwargs)
        self.list_type = list_type
        self.index = index
        self.entry = entry

    def compose(self) -> ComposeResult:
        """Compose the directory entry widgets."""
        matcher = self.entry.get("matcher", "")
        mode = self.entry.get("mode", "")
        url = self.entry.get("url", "")
        token_env = self.entry.get("token_env", "")

        # Header with matcher and mode
        badge_color = "status-ok" if mode == "allow" else "status-error"
        yield Static(
            f"[{badge_color}]{mode.upper()}[/{badge_color}] [bold]{matcher}[/bold]",
            classes="entry-header",
        )

        # Details
        details = [f"URL: {url}"]
        if token_env:
            details.append(f"Token: ${token_env}")

        yield Static(" | ".join(details), classes="entry-details")

        with Horizontal(classes="button-row"):
            yield Button(
                "Remove",
                variant="error",
                id=f"remove_{self.list_type}_{self.index}",
                classes="compact",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        event.stop()  # Prevent event bubbling
        if event.button.id.startswith("remove_"):
            self.post_message(self.RemovePressed(self.list_type, self.index))


class PermissionsDiscoveryContent(ConfigSaveMixin, Container):
    """Content widget for Permissions Discovery tab."""

    CONFIG_SECTION = "permissions"

    CSS = """
    PermissionsDiscoveryContent {
        height: auto;
    }

    #permissions-discovery-header {
        margin: 0 0 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    .mode-indicator {
        margin: 0 0 0 1;
        padding: 0 1;
    }

    .section {
        margin: 0 0 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    .section-title {
        margin: 0 0 0 0;
        font-weight: bold;
    }

    .list-container {
        margin: 0 0;
        min-height: 3;
        max-height: 10;
    }

    #add-entry-section {
        margin: 0 0 1 0;
        padding: 1;
        height: auto;
        background: $surface;
        border: solid $accent;
    }

    .input-row {
        margin: 0 0;
        height: auto;
        align: left middle;
    }

    .input-row Label {
        margin: 0 2 0 0;
        width: 20;
        content-align: right middle;
    }

    .input-row Input {
        width: 50;
        margin: 0 1 0 0;
    }

    .input-row Select {
        width: 30;
        margin: 0 1 0 0;
    }

    .input-row Button {
        margin: 0 1 0 0;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the permissions discovery tab content."""
        yield Static(
            "[bold]Permissions Auto-Discovery[/bold]", id="permissions-discovery-header"
        )

        # Status section
        with Container(classes="section"):
            yield Static(
                "[bold]📊 Auto-Discovery Status[/bold]", classes="section-title"
            )
            yield Static("", id="discovery-status")

        # Info section
        with Container(classes="section"):
            yield Static(
                "[bold]ℹ️  How Auto-Discovery Works[/bold]\n"
                "[dim]Scans directories or GitHub repos for skill/MCP definitions and auto-creates permissions.[/dim]\n"
                "  [status-ok]Allow[/status-ok] = discovered tools allowed  "
                "[status-error]Deny[/status-error] = discovered tools blocked  "
                "[dim]💡 Most users should use Remote Configs instead[/dim]"
            )

        # Allow directories section
        with Container(classes="section"):
            yield Static("[bold]Allow Directories[/bold]", classes="section-title")
            yield Static(
                "[dim]Scan these directories and allow discovered tools[/dim]",
                classes="section-title",
            )

            with VerticalScroll(id="allow-list", classes="list-container"):
                yield Static("[dim]No allow directories configured[/dim]")

        # Deny directories section
        with Container(classes="section"):
            yield Static("[bold]Deny Directories[/bold]", classes="section-title")
            yield Static(
                "[dim]Scan these directories and deny discovered tools[/dim]",
                classes="section-title",
            )

            with VerticalScroll(id="deny-list", classes="list-container"):
                yield Static("[dim]No deny directories configured[/dim]")

        # Add new entry section
        with Container(id="add-entry-section"):
            yield Static("[bold]Add New Directory[/bold]", classes="section-title")

            yield Static("", id="selection-indicator", classes="mode-indicator")

            with Horizontal(classes="input-row"):
                yield Label("List Type:")
                yield Select(
                    [("Allow", "allow"), ("Deny", "deny")],
                    value="allow",
                    allow_blank=False,
                    compact=True,
                    id="list-type-select",
                )

            with Horizontal(classes="input-row"):
                yield Label("Matcher:")
                yield Input(placeholder="Skill, mcp__*, etc.", id="matcher-input")
                yield Static("[dim]Tool pattern to match[/dim]")

            with Horizontal(classes="input-row"):
                yield Label("Mode:")
                yield Select(
                    [("Allow", "allow"), ("Deny", "deny")],
                    value="allow",
                    allow_blank=False,
                    compact=True,
                    id="mode-select",
                )

            with Horizontal(classes="input-row"):
                yield Label("URL:")
                yield Input(
                    placeholder="/path/to/dir or https://github.com/user/repo",
                    id="url-input",
                )

            with Horizontal(classes="input-row"):
                yield Label("Token Env Var:")
                yield Input(placeholder="GITHUB_TOKEN (optional)", id="token-env-input")

            with Horizontal(classes="input-row"):
                yield Label("")
                yield Button("Add Directory", variant="success", id="add-entry-button")

    def on_mount(self) -> None:
        """Load configuration when mounted."""
        self.load_config()
        self._update_selection_indicator()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Update the selection indicator when a Select widget changes."""
        if event.select.id in ("list-type-select", "mode-select"):
            self._update_selection_indicator()

    def _update_selection_indicator(self) -> None:
        """Update the visual indicator showing current list-type and mode selections."""
        try:
            indicator = self.query_one("#selection-indicator", Static)
            list_type = self.query_one("#list-type-select", Select).value
            mode = self.query_one("#mode-select", Select).value

            lt_color = "green" if list_type == "allow" else "red"
            lt_icon = "✓" if list_type == "allow" else "✗"
            mode_color = "green" if mode == "allow" else "red"
            mode_icon = "✓" if mode == "allow" else "✗"

            indicator.update(
                f"List: [{lt_color}]{lt_icon} {str(list_type).upper()}[/{lt_color}]  "
                f"Mode: [{mode_color}]{mode_icon} {str(mode).upper()}[/{mode_color}]"
            )
        except Exception:
            pass

    def refresh_content(self) -> None:
        """Refresh configuration (called by parent app)."""
        self.load_config()

    def load_config(self) -> None:
        """Load and display permissions discovery configuration."""
        config = self._load_full_config()

        # Load permissions directories
        perms_dirs = config.get("permissions_directories", {})
        allow_dirs = perms_dirs.get("allow", [])
        deny_dirs = perms_dirs.get("deny", [])

        # Update lists
        self.update_list("allow", allow_dirs)
        self.update_list("deny", deny_dirs)

        # Update status
        self.update_status(allow_dirs, deny_dirs)

    def update_list(self, list_type: str, entries: List[Dict[str, Any]]) -> None:
        """Update a directory list display."""
        try:
            list_container = self.query_one(f"#{list_type}-list", VerticalScroll)

            # Remove all existing children
            list_container.remove_children()

            # Add entries
            if entries:
                for idx, entry in enumerate(entries):
                    list_container.mount(DirectoryEntry(list_type, idx, entry))
            else:
                list_container.mount(
                    Static(f"[dim]No {list_type} directories configured[/dim]")
                )

        except Exception as e:
            self.app.notify(f"Error updating {list_type} list: {e}", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "add-entry-button":
            self.add_entry()

    def on_directory_entry_remove_pressed(
        self, message: DirectoryEntry.RemovePressed
    ) -> None:
        """Handle remove button press on directory entry."""
        self.remove_entry(message.list_type, message.index)

    def add_entry(self) -> None:
        """Add a new directory entry."""
        list_type = self.query_one("#list-type-select", Select).value
        matcher = self.query_one("#matcher-input", Input).value.strip()
        mode = self.query_one("#mode-select", Select).value
        url = self.query_one("#url-input", Input).value.strip()
        token_env = self.query_one("#token-env-input", Input).value.strip()

        # Validate inputs
        if not matcher:
            self.app.notify("Please enter a matcher", severity="error")
            return
        if not url:
            self.app.notify("Please enter a URL or path", severity="error")
            return

        try:
            config = self._load_full_config()

            if "permissions_directories" not in config:
                config["permissions_directories"] = {}
            if list_type not in config["permissions_directories"]:
                config["permissions_directories"][list_type] = []

            # Create entry
            entry = {"matcher": matcher, "mode": mode, "url": url}
            if token_env:
                entry["token_env"] = token_env

            config["permissions_directories"][list_type].append(entry)

            self._write_full_config(config)

            # Clear inputs
            self.query_one("#matcher-input", Input).value = ""
            self.query_one("#url-input", Input).value = ""
            self.query_one("#token-env-input", Input).value = ""

            self.load_config()
            self.app.notify(
                f"✓ Added {list_type} directory: {matcher}", severity="success"
            )

        except Exception as e:
            self.app.notify(f"Error adding entry: {e}", severity="error")

    def remove_entry(self, list_type: str, index: int) -> None:
        """Remove a directory entry."""
        try:
            config = self._load_full_config()
            if not config:
                return

            if (
                "permissions_directories" in config
                and list_type in config["permissions_directories"]
            ):
                entries = config["permissions_directories"][list_type]
                if 0 <= index < len(entries):
                    removed_entry = entries.pop(index)

                    self._write_full_config(config)

                    self.load_config()
                    self.app.notify(
                        f"✓ Removed {list_type} directory: {removed_entry.get('matcher', '')}",
                        severity="success",
                    )

        except Exception as e:
            self.app.notify(f"Error removing entry: {e}", severity="error")

    def update_status(
        self, allow_dirs: List[Dict[str, Any]], deny_dirs: List[Dict[str, Any]]
    ) -> None:
        """Update the status display based on current configuration."""
        try:
            status_widget = self.query_one("#discovery-status", Static)

            total_entries = len(allow_dirs) + len(deny_dirs)

            if total_entries == 0:
                # Disabled - no entries
                status_text = (
                    "[status-error]❌ DISABLED[/status-error] - No directories configured\n\n"
                    "[dim]Auto-discovery is currently inactive. Add an entry below to enable it.[/dim]"
                )
            else:
                # Enabled - has entries
                status_text = (
                    f"[status-ok]✓ ENABLED[/status-ok] - Scanning {total_entries} "
                    f"{'directory' if total_entries == 1 else 'directories'}\n\n"
                )

                if allow_dirs:
                    status_text += f"  • [status-ok]{len(allow_dirs)} Allow list {'entry' if len(allow_dirs) == 1 else 'entries'}[/status-ok]\n"
                if deny_dirs:
                    status_text += f"  • [status-error]{len(deny_dirs)} Deny list {'entry' if len(deny_dirs) == 1 else 'entries'}[/status-error]\n"

                status_text += "\n[dim]Discovered tools will be automatically allowed/denied based on the entries below.[/dim]"

            status_widget.update(status_text)
        except Exception:
            pass  # Widget may not be mounted yet

    def action_refresh(self) -> None:
        """Refresh configuration (triggered by 'r' key)."""
        self.load_config()
        self.app.notify("Permissions discovery refreshed", severity="information")
