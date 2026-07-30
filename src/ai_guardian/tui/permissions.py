#!/usr/bin/env python3
"""
Permissions Editor Screen

Manage tool permission rules for Skills and MCP servers.
"""

import json
from typing import Dict

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen, ModalScreen
from textual.widgets import Button, Static, Input, Select, Label
from textual.binding import Binding

from ai_guardian.config.utils import get_config_dir
from ai_guardian.tui.schema_defaults import ConfigSaveMixin


class PermissionCard(Container):
    """Display a single permission rule with edit/delete buttons."""

    def __init__(self, rule: Dict, index: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rule = rule
        self.index = index

    def compose(self) -> ComposeResult:
        """Compose the permission card."""
        matcher = self.rule.get("matcher", "Unknown")
        mode = self.rule.get("mode", "allow")
        patterns = self.rule.get("patterns", [])

        # Mode indicator
        mode_icon = "✓" if mode == "allow" else "✗"
        mode_color = "green" if mode == "allow" else "red"

        yield Static(f"[bold]{mode_icon} {matcher}[/bold]", classes="permission-title")
        yield Static(
            f"Mode: [{mode_color}]{mode}[/{mode_color}]", classes="permission-detail"
        )
        yield Static(f"Patterns: {', '.join(patterns)}", classes="permission-detail")

        with Horizontal(classes="permission-actions"):
            yield Button("Edit", id=f"edit-{self.index}")
            yield Button("Delete", id=f"delete-{self.index}", variant="error")


class AddPermissionModal(ModalScreen):
    """Modal for adding/editing permission rules."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = """
    AddPermissionModal {
        align: center middle;
    }

    #modal-container {
        width: 60;
        height: auto;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }

    #modal-header {
        margin: 0 0 1 0;
        text-align: center;
    }

    .modal-field {
        margin: 1 0;
    }

    .modal-field Label {
        margin: 0 0 0 0;
    }

    .modal-field Input,
    .modal-field Select {
        margin: 0 0 0 0;
        width: 100%;
    }

    #modal-actions {
        margin: 1 0 0 0;
        height: auto;
    }

    #modal-actions Button {
        margin: 0 1 0 0;
    }
    """

    def __init__(self, rule: Dict = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rule = rule or {}
        self.is_edit = bool(rule)

    def compose(self) -> ComposeResult:
        """Compose the modal."""
        with Container(id="modal-container"):
            title = "Edit Permission Rule" if self.is_edit else "Add Permission Rule"
            yield Static(f"[bold]{title}[/bold]", id="modal-header")

            with Container(classes="modal-field"):
                yield Label("Matcher (e.g., Skill, mcp__*__):")
                yield Input(
                    value=self.rule.get("matcher", ""),
                    placeholder="Skill or mcp__server-name__*",
                    id="input-matcher",
                )

            with Container(classes="modal-field"):
                yield Label("Mode:")
                yield Select(
                    [(line, line) for line in ["allow", "deny"]],
                    value=self.rule.get("mode", "allow"),
                    id="select-mode",
                )

            with Container(classes="modal-field"):
                yield Label("Action (deny only):")
                yield Select(
                    [
                        ("block", "block"),
                        ("warn", "warn"),
                        ("log-only", "log-only"),
                        ("ask", "ask"),
                        ("ask:warn", "ask:warn"),
                        ("ask:log-only", "ask:log-only"),
                    ],
                    value=self.rule.get("action", "block"),
                    id="select-action",
                )

            with Container(classes="modal-field"):
                yield Label("Patterns (comma-separated):")
                patterns = self.rule.get("patterns", [])
                patterns_str = ", ".join(patterns) if patterns else ""
                yield Input(
                    value=patterns_str,
                    placeholder="daf-*, release",
                    id="input-patterns",
                )

            with Horizontal(id="modal-actions"):
                yield Button("Save", id="save-permission", variant="success")
                yield Button("Cancel", id="cancel-permission", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "save-permission":
            # Get values
            matcher = self.query_one("#input-matcher", Input).value.strip()
            mode = self.query_one("#select-mode", Select).value
            action = self.query_one("#select-action", Select).value
            patterns_str = self.query_one("#input-patterns", Input).value.strip()

            # Validate
            if not matcher:
                self.notify("Matcher is required", severity="error")
                return

            if not patterns_str:
                self.notify("At least one pattern is required", severity="error")
                return

            # Parse patterns
            patterns = [p.strip() for p in patterns_str.split(",") if p.strip()]

            # Build rule
            rule = {"matcher": matcher, "mode": mode, "patterns": patterns}
            if mode == "deny" and action and action != "block":
                rule["action"] = action

            self.dismiss(rule)

        elif event.button.id == "cancel-permission":
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Dismiss modal on ESC key."""
        self.dismiss(None)


class PermissionsScreen(ConfigSaveMixin, Screen):
    """Screen for managing tool permissions."""

    CONFIG_SECTION = "permissions"

    CSS = """
    PermissionsScreen {
        background: $surface;
    }

    #permissions-header {
        margin: 1;
        padding: 1;
        background: $primary;
        color: $text;
    }

    #permissions-container {
        height: 100%;
        padding: 1 2;
    }

    PermissionCard {
        border: solid $primary;
        margin: 1 0;
        padding: 1;
        background: $panel;
    }

    .permission-title {
        margin: 0 0 1 0;
    }

    .permission-detail {
        margin: 0 0 0 2;
        padding: 0;
    }

    .permission-actions {
        margin: 1 0 0 0;
        height: auto;
    }

    .permission-actions Button {
        margin: 0 1 0 0;
    }

    #permissions-actions {
        margin: 1 0;
        height: auto;
    }

    #permissions-actions Button {
        margin: 0 1 0 0;
    }

    #permissions-list {
        max-height: 20;
    }

    #no-permissions {
        margin: 2;
        padding: 2;
        text-align: center;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "pop_screen", "Back"),
        Binding("a", "add_permission", "Add"),
        Binding("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the permissions screen."""
        yield Static("[bold]Tool Permissions[/bold]", id="permissions-header")

        with Container(id="permissions-container"):
            with Horizontal(id="permissions-actions"):
                yield Button("Add Permission", id="add-permission", variant="primary")
                yield Button("Refresh", id="refresh-permissions")

            yield VerticalScroll(id="permissions-list")

    def on_mount(self) -> None:
        """Load permissions when screen is mounted."""
        self.load_permissions()

    def load_permissions(self) -> None:
        """Load and display permission rules."""
        config_dir = get_config_dir()
        config_path = config_dir / "ai-guardian.json"

        permissions = []
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    # NEW unified structure in v1.4.0: permissions is object with rules array
                    permissions_obj = config.get("permissions", {})
                    if isinstance(permissions_obj, dict):
                        permissions = permissions_obj.get("rules", [])
                    else:
                        # Legacy format: permissions is array directly
                        permissions = (
                            permissions_obj if isinstance(permissions_obj, list) else []
                        )
            except Exception as e:
                self.notify(f"Error loading permissions: {e}", severity="error")

        # Get the permissions list container
        permissions_list = self.query_one("#permissions-list", VerticalScroll)
        permissions_list.remove_children()

        if not permissions:
            permissions_list.mount(
                Static("No permission rules defined.", id="no-permissions")
            )
            return

        # Add permission cards
        for idx, rule in enumerate(permissions):
            permissions_list.mount(PermissionCard(rule, idx))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "add-permission":
            self.add_permission()
        elif button_id == "refresh-permissions":
            self.load_permissions()
            self.notify("Permissions refreshed", severity="information")
        elif button_id and button_id.startswith("edit-"):
            idx = int(button_id.replace("edit-", ""))
            self.edit_permission(idx)
        elif button_id and button_id.startswith("delete-"):
            idx = int(button_id.replace("delete-", ""))
            self.delete_permission(idx)

    def add_permission(self) -> None:
        """Show modal to add a new permission rule."""

        def handle_result(rule: Dict) -> None:
            if rule:
                self.save_permission(rule)

        self.app.push_screen(AddPermissionModal(), handle_result)

    def edit_permission(self, index: int) -> None:
        """Show modal to edit an existing permission rule."""
        try:
            config = self._load_full_config()
            if not config:
                self.notify("Config file not found", severity="error")
                return

            # NEW unified structure in v1.4.0
            permissions_obj = config.get("permissions", {})
            if isinstance(permissions_obj, dict):
                permissions = permissions_obj.get("rules", [])
            else:
                permissions = (
                    permissions_obj if isinstance(permissions_obj, list) else []
                )

            if index >= len(permissions):
                self.notify("Permission not found", severity="error")
                return

            rule = permissions[index]

            def handle_result(updated_rule: Dict) -> None:
                if updated_rule:
                    permissions[index] = updated_rule
                    # Save back to new structure
                    if isinstance(config.get("permissions"), dict):
                        config["permissions"]["rules"] = permissions
                    else:
                        config["permissions"] = {"enabled": True, "rules": permissions}

                    self._write_full_config(config)

                    self.load_permissions()
                    self.notify("Permission updated", severity="success")

            self.app.push_screen(AddPermissionModal(rule), handle_result)

        except Exception as e:
            self.notify(f"Error editing permission: {e}", severity="error")

    def delete_permission(self, index: int) -> None:
        """Delete a permission rule."""
        try:
            config = self._load_full_config()
            if not config:
                self.notify("Config file not found", severity="error")
                return

            # NEW unified structure in v1.4.0
            permissions_obj = config.get("permissions", {})
            if isinstance(permissions_obj, dict):
                permissions = permissions_obj.get("rules", [])
            else:
                permissions = (
                    permissions_obj if isinstance(permissions_obj, list) else []
                )

            if index >= len(permissions):
                self.notify("Permission not found", severity="error")
                return

            # Remove the permission
            removed_rule = permissions.pop(index)
            # Save back to new structure
            if isinstance(config.get("permissions"), dict):
                config["permissions"]["rules"] = permissions
            else:
                config["permissions"] = {"enabled": True, "rules": permissions}

            self._write_full_config(config)

            self.load_permissions()
            self.notify(
                f"Deleted permission for {removed_rule.get('matcher')}",
                severity="success",
            )

        except Exception as e:
            self.notify(f"Error deleting permission: {e}", severity="error")

    def save_permission(self, rule: Dict) -> None:
        """Save a new permission rule to config."""
        try:
            config = self._load_full_config()

            permissions_obj = config.get("permissions", {})
            if isinstance(permissions_obj, dict):
                all_permissions = permissions_obj.get("rules", [])
                is_dict_format = True
            elif isinstance(permissions_obj, list):
                all_permissions = permissions_obj
                is_dict_format = False
            else:
                all_permissions = []
                is_dict_format = False

            all_permissions.append(rule)

            if is_dict_format:
                config["permissions"]["rules"] = all_permissions
            else:
                config["permissions"] = all_permissions

            self._write_full_config(config)

            self.load_permissions()
            self.notify("Permission added", severity="success")

        except Exception as e:
            self.notify(f"Error saving permission: {e}", severity="error")

    def action_add_permission(self) -> None:
        """Add permission via keybinding."""
        self.add_permission()

    def action_refresh(self) -> None:
        """Refresh permissions list."""
        self.load_permissions()
        self.notify("Permissions refreshed", severity="information")
