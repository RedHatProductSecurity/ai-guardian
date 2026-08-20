"""Tray Plugins panel for the TUI console."""

import json

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, DataTable, Static, TextArea


class TrayPluginsContent(Container):
    """Content widget for Tray Plugins panel."""

    DEFAULT_CSS = """
    TrayPluginsContent {
        height: 100%;
    }
    #tray-plugins-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }
    #tray-plugins-status {
        margin: 1 2;
        padding: 0 1;
    }
    #tray-plugins-table {
        height: 60%;
        margin: 0 2;
    }
    #tray-plugins-editor-container {
        height: 35%;
        margin: 0 2;
        display: none;
    }
    #tray-plugins-editor {
        height: 100%;
    }
    .tray-plugins-btn {
        margin: 0 1;
    }
    #tray-plugins-info {
        margin: 2 2;
        padding: 1;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Tray Plugins[/bold]", id="tray-plugins-header")

        with VerticalScroll():
            with Horizontal(classes="tray-plugins-btn"):
                yield Button("Refresh", id="tray-plugins-refresh", variant="default")
                yield Button("New", id="tray-plugins-new", variant="primary")
                yield Button("Edit", id="tray-plugins-edit", variant="default")
                yield Button("Toggle", id="tray-plugins-toggle", variant="default")
                yield Button("Delete", id="tray-plugins-delete", variant="error")

            yield DataTable(id="tray-plugins-table")
            yield Static("", id="tray-plugins-status")

            with Container(id="tray-plugins-editor-container"):
                yield TextArea(id="tray-plugins-editor", language="json")
                with Horizontal(classes="tray-plugins-btn"):
                    yield Button("Save", id="tray-plugins-save", variant="primary")
                    yield Button(
                        "Cancel Edit", id="tray-plugins-cancel", variant="default"
                    )

            yield Static(
                "[bold]About Tray Plugins[/bold]\n\n"
                "  Tray plugins add custom menu items to the system tray.\n"
                "  Plugin JSON files live in ~/.config/ai-guardian/tray-plugins/.\n\n"
                "  [bold]Source:[/bold]\n"
                "    bundled — shipped with ai-guardian (read-only)\n"
                "    user — your custom plugins (editable)\n"
                "    project — from .ai-guardian/tray-plugins/ (editable)\n\n"
                "  [bold]Actions:[/bold]\n"
                "    New — create a blank plugin file\n"
                "    Edit — modify selected user plugin JSON\n"
                "    Toggle — enable/disable selected user plugin\n"
                "    Delete — remove selected user plugin",
                id="tray-plugins-info",
            )

    def on_mount(self) -> None:
        table = self.query_one("#tray-plugins-table", DataTable)
        table.add_columns("Name", "Source", "Status", "Filename")
        table.cursor_type = "row"
        self._editing_filename = None
        self._load_plugins()

    def refresh_content(self) -> None:
        self._load_plugins()

    def _load_plugins(self) -> None:
        try:
            from ai_guardian.tray.plugins import list_plugin_files

            self._files = list_plugin_files()
        except Exception:
            self._files = []

        table = self.query_one("#tray-plugins-table", DataTable)
        table.clear()
        for f in self._files:
            status = "✓ Enabled" if f["enabled"] else "✗ Disabled"
            table.add_row(
                f["plugin_name"],
                f["source"],
                status,
                f["filename"],
                key=f["filename"],
            )

    def _get_selected_file(self):
        table = self.query_one("#tray-plugins-table", DataTable)
        if table.cursor_row is None or table.cursor_row < 0:
            return None
        if table.cursor_row >= len(self._files):
            return None
        return self._files[table.cursor_row]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button.id
        if btn == "tray-plugins-refresh":
            self._load_plugins()
            self._set_status("Refreshed", "success")
        elif btn == "tray-plugins-new":
            self._create_new_plugin()
        elif btn == "tray-plugins-edit":
            self._edit_selected()
        elif btn == "tray-plugins-toggle":
            self._toggle_selected()
        elif btn == "tray-plugins-delete":
            self._delete_selected()
        elif btn == "tray-plugins-save":
            self._save_editor()
        elif btn == "tray-plugins-cancel":
            self._close_editor()

    def _create_new_plugin(self) -> None:
        from ai_guardian.tray.plugins import save_user_plugin

        template = {
            "name": "New Plugin",
            "items": [
                {
                    "label": "Example Command",
                    "command": "echo hello",
                    "type": "notification",
                }
            ],
        }
        ok, msg = save_user_plugin("new-plugin.json", template)
        if ok:
            self._set_status("Created new-plugin.json — edit to customize", "success")
            self.app.notify("Created new-plugin.json", severity="information")
            self._load_plugins()
        else:
            self._set_status(msg, "error")

    def _edit_selected(self) -> None:
        f = self._get_selected_file()
        if not f:
            self._set_status("Select a plugin first", "error")
            return
        if f["source"] != "user":
            self._set_status("Only user plugins can be edited", "error")
            return

        from ai_guardian.daemon import get_tray_plugins_dir

        path = get_tray_plugins_dir() / f["filename"]
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            self._set_status(f"Read failed: {e}", "error")
            return

        self._editing_filename = f["filename"]
        editor_container = self.query_one("#tray-plugins-editor-container")
        editor_container.styles.display = "block"
        editor = self.query_one("#tray-plugins-editor", TextArea)
        editor.load_text(content)
        self._set_status(f"Editing {f['filename']}", "success")

    def _save_editor(self) -> None:
        if not self._editing_filename:
            return
        editor = self.query_one("#tray-plugins-editor", TextArea)
        text = editor.text
        try:
            content = json.loads(text)
        except json.JSONDecodeError as e:
            self._set_status(f"Invalid JSON: {e}", "error")
            return

        from ai_guardian.tray.plugins import save_user_plugin

        ok, msg = save_user_plugin(self._editing_filename, content)
        if ok:
            self._set_status(msg, "success")
            self.app.notify(msg, severity="information")
            self._close_editor()
            self._load_plugins()
        else:
            self._set_status(msg, "error")

    def _close_editor(self) -> None:
        self._editing_filename = None
        editor_container = self.query_one("#tray-plugins-editor-container")
        editor_container.styles.display = "none"

    def _toggle_selected(self) -> None:
        f = self._get_selected_file()
        if not f:
            self._set_status("Select a plugin first", "error")
            return
        if f["source"] != "user":
            self._set_status("Only user plugins can be toggled", "error")
            return

        from ai_guardian.tray.plugins import toggle_user_plugin

        base = (
            f["filename"][: -len(".disabled")]
            if f["filename"].endswith(".disabled")
            else f["filename"]
        )
        new_enabled = not f["enabled"]
        ok, msg = toggle_user_plugin(base, new_enabled)
        if ok:
            self._set_status(msg, "success")
            self.app.notify(msg, severity="information")
            self._load_plugins()
        else:
            self._set_status(msg, "error")

    def _delete_selected(self) -> None:
        f = self._get_selected_file()
        if not f:
            self._set_status("Select a plugin first", "error")
            return
        if f["source"] != "user":
            self._set_status("Only user plugins can be deleted", "error")
            return

        from ai_guardian.tray.plugins import delete_user_plugin

        ok, msg = delete_user_plugin(f["filename"])
        if ok:
            self._set_status(msg, "success")
            self.app.notify(msg, severity="information")
            self._load_plugins()
        else:
            self._set_status(msg, "error")

    def _set_status(self, message: str, level: str) -> None:
        try:
            status = self.query_one("#tray-plugins-status", Static)
            if level == "error":
                status.update(f"[red]{message}[/red]")
            else:
                status.update(f"[green]{message}[/green]")
        except Exception:
            pass

    def action_refresh(self) -> None:
        self._load_plugins()
        self.app.notify("Tray plugins refreshed", severity="information")
