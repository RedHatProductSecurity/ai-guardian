"""SDK Agent Profiles panel for the TUI console."""

import threading
from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Input, Label, Select, Static, Tree

from ai_guardian.tui.schema_defaults import ConfigSaveMixin

_PROFILE_FIELDS = [
    ("model", "Model", "text"),
    ("mode", "Mode", "select"),
    ("max_turns", "Max Turns", "int"),
    ("max_tokens", "Max Tokens", "int"),
    ("tools", "Tools", "text"),
    ("compact_threshold", "Compact Threshold", "float"),
    ("compact_keep_turns", "Compact Keep Turns", "int"),
    ("compact_keep_first", "Compact Keep First", "int"),
    ("cwd", "Working Directory", "text"),
]

_MODE_OPTIONS = [
    ("Direct", "direct"),
    ("REST", "rest"),
]


class SDKAgentsContent(ConfigSaveMixin, Container):
    """Content widget for the SDK Agent Profiles panel."""

    CONFIG_SECTION = "sdk"

    DEFAULT_CSS = """
    SDKAgentsContent {
        height: 100%;
    }
    #sdk-agents-header {
        margin: 1 0;
        padding: 1;
        color: $text;
    }
    #sdk-agents-tree {
        height: 12;
        padding: 1;
        border: solid $primary;
        background: $surface;
    }
    .profile-detail {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }
    .profile-detail .setting-row {
        margin: 0 0 1 0;
        height: auto;
    }
    .profile-detail .setting-row Label {
        width: 22;
        margin: 0 1 0 0;
    }
    .profile-detail .setting-row Input {
        width: 40;
    }
    .profile-detail .setting-row Select {
        width: 40;
    }
    #sdk-agents-actions {
        margin: 1 0;
        height: auto;
    }
    #sdk-agents-actions Button {
        margin: 0 1 0 0;
    }
    #profile-detail-section {
        margin: 1 0;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selected_profile: Optional[str] = None
        self._profiles: Dict[str, Dict[str, Any]] = {}

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]SDK Agent Profiles[/bold]\n"
            "[dim]Configure GuardedAgent profiles. "
            "The '*' profile provides defaults for all agents.[/dim]",
            id="sdk-agents-header",
        )
        with Horizontal(id="sdk-agents-actions"):
            yield Button("Add Profile", id="btn-add-profile", variant="success")
            yield Button("Delete Profile", id="btn-delete-profile", variant="error")
            yield Button("Refresh", id="btn-refresh-agents", variant="default")
        yield Tree("Agent Profiles", id="sdk-agents-tree")

        with VerticalScroll(id="profile-detail-section"):
            with Container(classes="profile-detail", id="profile-detail"):
                yield Static(
                    "[dim]Select a profile above to view details.[/dim]",
                    id="profile-detail-placeholder",
                )

    def on_mount(self) -> None:
        tree = self.query_one("#sdk-agents-tree", Tree)
        tree.show_root = False
        self._load_profiles()

    def refresh_content(self) -> None:
        self._load_profiles()

    def action_refresh(self) -> None:
        self.refresh_content()
        self.app.notify("Agent profiles refreshed")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-refresh-agents":
            self.refresh_content()
        elif event.button.id == "btn-add-profile":
            self._show_add_dialog()
        elif event.button.id == "btn-delete-profile":
            self._delete_selected_profile()
        elif event.button.id == "btn-save-profile":
            self._save_selected_profile()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.node.data is not None:
            self._selected_profile = event.node.data
            self._render_detail(event.node.data)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "add-profile-name":
            name = event.input.value.strip()
            if name:
                self._add_profile(name)
                event.input.value = ""

    def _load_profiles(self) -> None:
        tree = self.query_one("#sdk-agents-tree", Tree)
        tree.clear()
        tree.root.add_leaf("[dim]Loading...[/dim]")

        def _worker():
            config = self._load_full_config()
            sdk = config.get("sdk", {})
            profiles = sdk.get("agents", {})
            if not isinstance(profiles, dict):
                profiles = {}
            self.app.call_from_thread(self._render_profiles, profiles)

        threading.Thread(target=_worker, daemon=True).start()

    def _render_profiles(self, profiles: Dict[str, Dict[str, Any]]) -> None:
        self._profiles = profiles
        tree = self.query_one("#sdk-agents-tree", Tree)
        tree.clear()

        if not profiles:
            tree.root.add_leaf("[dim]No agent profiles configured.[/dim]")
            self._clear_detail()
            return

        sorted_names = sorted(profiles.keys(), key=lambda k: (k != "*", k))
        for name in sorted_names:
            profile = profiles[name]
            model = profile.get("model", "-")
            mode = profile.get("mode", "-")
            max_turns = profile.get("max_turns", "-")
            tools = profile.get("tools", "-")
            if isinstance(tools, list):
                tools = f"[{len(tools)} items]"
            default_marker = (
                " [bold yellow](default)[/bold yellow]" if name == "*" else ""
            )
            label = (
                f"[bold]{name}[/bold]{default_marker}  "
                f"model={model}  mode={mode}  "
                f"max_turns={max_turns}  tools={tools}"
            )
            tree.root.add_leaf(label, data=name)

        if self._selected_profile and self._selected_profile in profiles:
            self._render_detail(self._selected_profile)
        else:
            self._clear_detail()

    def _clear_detail(self) -> None:
        detail = self.query_one("#profile-detail", Container)
        detail.remove_children()
        detail.mount(
            Static(
                "[dim]Select a profile above to view details.[/dim]",
                id="profile-detail-placeholder",
            )
        )

    def _render_detail(self, name: str) -> None:
        profile = self._profiles.get(name, {})
        detail = self.query_one("#profile-detail", Container)
        detail.remove_children()

        header_text = f"[bold]Profile: {name}[/bold]"
        if name == "*":
            header_text += " [yellow](default — applies to all agents)[/yellow]"
        detail.mount(Static(header_text, id="detail-header"))

        for field_key, field_label, field_type in _PROFILE_FIELDS:
            value = profile.get(field_key, "")
            row = Horizontal(classes="setting-row")
            detail.mount(row)

            label_widget = Label(f"{field_label}:")
            row.mount(label_widget)

            if field_type == "select" and field_key == "mode":
                widget = Select(
                    [(lbl, val) for lbl, val in _MODE_OPTIONS],
                    value=str(value) if value else "direct",
                    id=f"profile-field-{field_key}",
                )
            elif field_type == "text":
                display_val = str(value) if value else ""
                if isinstance(value, list):
                    import json

                    display_val = json.dumps(value)
                widget = Input(
                    value=display_val,
                    placeholder=f"Enter {field_label.lower()}",
                    id=f"profile-field-{field_key}",
                )
            elif field_type in ("int", "float"):
                widget = Input(
                    value=str(value) if value != "" else "",
                    placeholder=f"Enter {field_label.lower()}",
                    id=f"profile-field-{field_key}",
                )
            else:
                widget = Input(
                    value=str(value) if value else "",
                    id=f"profile-field-{field_key}",
                )
            row.mount(widget)

        save_row = Horizontal(classes="setting-row")
        detail.mount(save_row)
        save_row.mount(Button("Save Profile", id="btn-save-profile", variant="primary"))

    def _save_selected_profile(self) -> None:
        if not self._selected_profile:
            self.app.notify("No profile selected", severity="warning")
            return

        name = self._selected_profile
        updated: Dict[str, Any] = {}

        for field_key, _, field_type in _PROFILE_FIELDS:
            widget_id = f"profile-field-{field_key}"
            try:
                widget = self.query_one(f"#{widget_id}")
            except Exception:
                continue

            if isinstance(widget, Select):
                raw = widget.value
            elif isinstance(widget, Input):
                raw = widget.value.strip()
            else:
                continue

            if raw == "" or raw == Select.BLANK:
                continue

            if field_type == "int":
                try:
                    updated[field_key] = int(raw)
                except ValueError:
                    self.app.notify(
                        f"Invalid integer for {field_key}", severity="error"
                    )
                    return
            elif field_type == "float":
                try:
                    updated[field_key] = float(raw)
                except ValueError:
                    self.app.notify(f"Invalid number for {field_key}", severity="error")
                    return
            elif field_key == "tools" and raw.startswith("["):
                import json

                try:
                    updated[field_key] = json.loads(raw)
                except json.JSONDecodeError:
                    updated[field_key] = raw
            else:
                updated[field_key] = raw

        config = self._load_full_config()
        sdk = config.setdefault("sdk", {})
        agents = sdk.setdefault("agents", {})
        agents[name] = updated
        if self._write_full_config(config):
            self.app.notify(f"Profile '{name}' saved", severity="information")
            self._load_profiles()
        else:
            self.app.notify("Failed to save config", severity="error")

    def _show_add_dialog(self) -> None:
        detail = self.query_one("#profile-detail", Container)
        detail.remove_children()
        detail.mount(Static("[bold]Add New Agent Profile[/bold]"))
        row = Horizontal(classes="setting-row")
        detail.mount(row)
        row.mount(Label("Profile Name:"))
        row.mount(
            Input(
                placeholder="e.g. triage-verifier",
                id="add-profile-name",
            )
        )
        detail.mount(Static("[dim]Press Enter to create. Uses default settings.[/dim]"))

    def _add_profile(self, name: str) -> None:
        if name in self._profiles:
            self.app.notify(f"Profile '{name}' already exists", severity="warning")
            return

        config = self._load_full_config()
        sdk = config.setdefault("sdk", {})
        agents = sdk.setdefault("agents", {})
        agents[name] = {}
        if self._write_full_config(config):
            self.app.notify(f"Profile '{name}' created", severity="information")
            self._selected_profile = name
            self._load_profiles()
        else:
            self.app.notify("Failed to save config", severity="error")

    def _delete_selected_profile(self) -> None:
        if not self._selected_profile:
            self.app.notify("No profile selected", severity="warning")
            return
        if self._selected_profile == "*":
            self.app.notify("Cannot delete the default (*) profile", severity="error")
            return

        name = self._selected_profile
        config = self._load_full_config()
        sdk = config.get("sdk", {})
        agents = sdk.get("agents", {})
        if name in agents:
            del agents[name]
            if self._write_full_config(config):
                self.app.notify(f"Profile '{name}' deleted", severity="information")
                self._selected_profile = None
                self._load_profiles()
            else:
                self.app.notify("Failed to save config", severity="error")
        else:
            self.app.notify(f"Profile '{name}' not found", severity="warning")
