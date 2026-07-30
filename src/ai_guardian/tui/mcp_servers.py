#!/usr/bin/env python3
"""
MCP Servers Tab Content

Manage MCP server permissions (allow/deny rules for MCP server tools).
"""

import json
from typing import Dict

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Static, Input, Select, Label
from textual.screen import ModalScreen
from textual.binding import Binding

from ai_guardian.tui.schema_defaults import ConfigSaveMixin


class MCPPermissionCard(Container):
    """Display a single MCP server permission rule."""

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


class AddMCPPermissionModal(ModalScreen):
    """Modal for adding/editing MCP server permission rules."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Cancel", show=False),
    ]

    CSS = """
    AddMCPPermissionModal {
        align: center middle;
    }

    #modal-container {
        width: 70;
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

    /* Focus indicators */
    Input:focus {
        border-left: heavy $accent;
        text-style: bold;
    }

    Button:focus {
        border-left: heavy $accent;
        text-style: bold;
    }

    Select:focus {
        border-left: heavy $accent;
        text-style: bold;
    }
    """

    def __init__(self, rule: Dict = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rule = rule or {}
        self.is_edit = bool(rule)

    def compose(self) -> ComposeResult:
        """Compose the modal."""
        with Container(id="modal-container"):
            title = (
                "Edit MCP Server Permission"
                if self.is_edit
                else "Add MCP Server Permission"
            )
            yield Static(f"[bold]{title}[/bold]", id="modal-header")

            with Container(classes="modal-field"):
                yield Label("Server Matcher (e.g., mcp__notebooklm-mcp__* or mcp__*):")
                yield Input(
                    value=self.rule.get("matcher", ""),
                    placeholder="mcp__server-name__*",
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
                yield Label("Tool Patterns (comma-separated, or * for all):")
                patterns = self.rule.get("patterns", [])
                patterns_str = ", ".join(patterns) if patterns else ""
                yield Input(
                    value=patterns_str,
                    placeholder="*, notebook_*, chat_*",
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
            patterns_str = self.query_one("#input-patterns", Input).value.strip()

            # Validate
            if not matcher or not matcher.startswith("mcp__"):
                self.app.notify("Matcher must start with 'mcp__'", severity="error")
                return

            if not patterns_str:
                self.app.notify("At least one pattern is required", severity="error")
                return

            # Parse patterns
            patterns = [p.strip() for p in patterns_str.split(",") if p.strip()]

            # Build rule
            rule = {"matcher": matcher, "mode": mode, "patterns": patterns}

            self.dismiss(rule)

        elif event.button.id == "cancel-permission":
            self.dismiss(None)


class MCPServersContent(ConfigSaveMixin, Container):
    """Content widget for MCP Servers tab."""

    CONFIG_SECTION = "mcp_server"

    CSS = """
    MCPServersContent {
        height: 100%;
    }

    #mcp-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    MCPPermissionCard {
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

    #mcp-actions {
        margin: 1 0;
        height: auto;
    }

    #mcp-actions Button {
        margin: 0 1 0 0;
    }

    #proactive-label {
        margin: 1 0 0 0;
    }

    #proactive-level {
        margin: 0 0 1 0;
        width: 50;
    }

    #support-section {
        border: solid $primary;
        margin: 1 0;
        padding: 1;
        background: $panel;
    }

    #support-section Static {
        margin: 0 0 0 0;
    }

    #support-section Input {
        margin: 0 0 1 0;
    }

    #support-actions {
        margin: 1 0 0 0;
        height: auto;
    }

    #support-actions Button {
        margin: 0 1 0 0;
    }

    .empty-state {
        margin: 2;
        padding: 2;
        text-align: center;
        color: $text-muted;
    }

    /* Focus indicators */
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
        """Compose the MCP servers tab content."""
        yield Static("[bold]MCP Server Permissions[/bold]", id="mcp-header")

        # Proactive level selector (Issue #477)
        yield Static("Proactive Level:", id="proactive-label")
        yield Select(
            [
                ("low — check only when asked", "low"),
                ("medium — check unfamiliar paths/commands", "medium"),
                ("high — check everything", "high"),
            ],
            value="low",
            id="proactive-level",
        )

        # Support Bundle config (Issue #477)
        with Container(id="support-section"):
            yield Static("[bold]Support Bundle Export[/bold]")
            yield Static(
                "[dim]Destination for sanitized diagnostic bundles (local path or s3://...)[/dim]"
            )
            yield Input(
                placeholder="e.g., ~/support-bundles or s3://bucket/prefix/",
                id="support-destination",
            )
            yield Static("[dim]Bundle TTL (minutes before auto-expiry):[/dim]")
            yield Input(
                placeholder="30",
                id="support-ttl",
            )
            with Horizontal(id="support-actions"):
                yield Button("Save", id="support-save", variant="primary")

        yield Static(
            "[dim]Manage MCP server tool permissions (e.g., mcp__notebooklm-mcp__*). "
            "Press 'a' to add new permission.[/dim]",
            classes="permission-detail",
        )

        yield VerticalScroll(id="mcp-list")

    def on_mount(self) -> None:
        """Load permissions, proactive level, and support config when mounted."""
        self._load_proactive_level()
        self._load_support_config()
        self.load_permissions()

    def refresh_content(self) -> None:
        """Refresh permissions (called by parent app)."""
        self.load_permissions()

    def load_permissions(self) -> None:
        """Load and display MCP server permission rules."""
        permissions = []
        try:
            config = self._load_full_config()
            # NEW unified structure in v1.4.0
            permissions_obj = config.get("permissions", {})
            if isinstance(permissions_obj, dict):
                all_permissions = permissions_obj.get("rules", [])
            else:
                all_permissions = (
                    permissions_obj if isinstance(permissions_obj, list) else []
                )
            # Filter only MCP permissions
            permissions = [
                p for p in all_permissions if p.get("matcher", "").startswith("mcp__")
            ]
        except Exception as e:
            self.app.notify(f"Error loading permissions: {e}", severity="error")

        # Get the permissions list container
        permissions_list = self.query_one("#mcp-list", VerticalScroll)
        permissions_list.remove_children()

        if not permissions:
            permissions_list.mount(
                Static(
                    "No MCP server permissions defined.\n\n"
                    "[dim]Press 'a' to add permissions for MCP server tools.\n"
                    "Example: mcp__notebooklm-mcp__*[/dim]",
                    classes="empty-state",
                )
            )
            return

        # Add permission cards
        for idx, rule in enumerate(permissions):
            permissions_list.mount(MCPPermissionCard(rule, idx))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses (only edit/delete on permission cards)."""
        button_id = event.button.id

        if button_id == "support-save":
            self._save_support_config()
        elif button_id and button_id.startswith("edit-"):
            idx = int(button_id.replace("edit-", ""))
            self.edit_permission(idx)
        elif button_id and button_id.startswith("delete-"):
            idx = int(button_id.replace("delete-", ""))
            self.delete_permission(idx)

    def _load_proactive_level(self) -> None:
        """Load proactive level from config."""
        config = self._load_full_config()
        level = config.get("mcp_server", {}).get("proactive_level", "low")
        try:
            select = self.query_one("#proactive-level", Select)
            select.value = level
        except Exception:
            pass

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle proactive level change."""
        if event.select.id == "proactive-level" and event.value != Select.BLANK:
            self._save_config_field("proactive_level", event.value)
            self.app.notify(f"Proactive level: {event.value}", severity="information")

    def _load_support_config(self) -> None:
        """Load support config values into the input fields."""
        config = self._load_full_config()
        support = config.get("support", {})

        try:
            dest_input = self.query_one("#support-destination", Input)
            dest_input.value = support.get("export_destination", "")
            ttl_input = self.query_one("#support-ttl", Input)
            ttl_val = support.get("bundle_ttl_minutes", 30)
            ttl_input.value = str(ttl_val)
        except Exception:
            pass

    def _save_support_config(self) -> None:
        """Save support config from input fields."""
        config = self._load_full_config()

        if "support" not in config:
            config["support"] = {}

        try:
            dest_input = self.query_one("#support-destination", Input)
            config["support"]["export_destination"] = dest_input.value.strip()

            ttl_input = self.query_one("#support-ttl", Input)
            try:
                config["support"]["bundle_ttl_minutes"] = int(
                    ttl_input.value.strip() or "30"
                )
            except ValueError:
                config["support"]["bundle_ttl_minutes"] = 30
        except Exception:
            pass

        self._write_full_config(config)

        self.app.notify("Support bundle config saved", severity="information")

    def action_add_permission(self) -> None:
        """Add new MCP permission (triggered by 'a' key)."""
        self.add_permission()

    def add_permission(self) -> None:
        """Show modal to add a new MCP server permission rule."""

        def handle_result(rule: Dict) -> None:
            if rule:
                self.save_permission(rule)

        self.app.push_screen(AddMCPPermissionModal(), handle_result)

    def edit_permission(self, index: int) -> None:
        """Show modal to edit an existing MCP server permission rule."""
        try:
            config = self._load_full_config()
            if not config:
                self.app.notify("Config file not found", severity="error")
                return

            # NEW unified structure in v1.4.0
            permissions_obj = config.get("permissions", {})
            if isinstance(permissions_obj, dict):
                all_permissions = permissions_obj.get("rules", [])
            else:
                all_permissions = (
                    permissions_obj if isinstance(permissions_obj, list) else []
                )
            mcp_permissions = [
                p for p in all_permissions if p.get("matcher", "").startswith("mcp__")
            ]

            if index >= len(mcp_permissions):
                self.app.notify("Permission not found", severity="error")
                return

            rule = mcp_permissions[index]

            def handle_result(updated_rule: Dict) -> None:
                if updated_rule:
                    # Find the actual index in the full permissions list
                    mcp_count = 0
                    for i, perm in enumerate(all_permissions):
                        if perm.get("matcher", "").startswith("mcp__"):
                            if mcp_count == index:
                                all_permissions[i] = updated_rule
                                break
                            mcp_count += 1

                    # Save back to new structure
                    if isinstance(config.get("permissions"), dict):
                        config["permissions"]["rules"] = all_permissions
                    else:
                        config["permissions"] = {
                            "enabled": True,
                            "rules": all_permissions,
                        }

                    self._write_full_config(config)

                    self.load_permissions()
                    self.app.notify("MCP server permission updated", severity="success")

            self.app.push_screen(AddMCPPermissionModal(rule), handle_result)

        except Exception as e:
            self.app.notify(f"Error editing permission: {e}", severity="error")

    def delete_permission(self, index: int) -> None:
        """Delete an MCP server permission rule."""
        try:
            config = self._load_full_config()
            if not config:
                self.app.notify("Config file not found", severity="error")
                return

            # NEW unified structure in v1.4.0
            permissions_obj = config.get("permissions", {})
            if isinstance(permissions_obj, dict):
                all_permissions = permissions_obj.get("rules", [])
            else:
                all_permissions = (
                    permissions_obj if isinstance(permissions_obj, list) else []
                )

            # Find and remove the MCP permission
            mcp_count = 0
            for i, perm in enumerate(all_permissions):
                if perm.get("matcher", "").startswith("mcp__"):
                    if mcp_count == index:
                        all_permissions.pop(i)
                        break
                    mcp_count += 1

            # Save back to new structure
            if isinstance(config.get("permissions"), dict):
                config["permissions"]["rules"] = all_permissions
            else:
                config["permissions"] = {"enabled": True, "rules": all_permissions}

            self._write_full_config(config)

            self.load_permissions()
            self.app.notify("MCP server permission deleted", severity="success")

        except Exception as e:
            self.app.notify(f"Error deleting permission: {e}", severity="error")

    def save_permission(self, rule: Dict) -> None:
        """Save a new MCP server permission rule to config (merges with existing if matcher+mode match)."""
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

            # Check if a rule with same matcher+mode already exists
            existing_rule = None
            for perm in all_permissions:
                if perm.get("matcher") == rule.get("matcher") and perm.get(
                    "mode"
                ) == rule.get("mode"):
                    existing_rule = perm
                    break

            if existing_rule:
                new_patterns = rule.get("patterns", [])
                existing_patterns = existing_rule.get("patterns", [])
                merged_patterns = list(set(existing_patterns + new_patterns))
                existing_rule["patterns"] = merged_patterns
                message = "MCP server permission updated (patterns merged)"
            else:
                all_permissions.append(rule)
                message = "MCP server permission added"

            if is_dict_format:
                config["permissions"]["rules"] = all_permissions
            else:
                config["permissions"] = all_permissions

            self._write_full_config(config)

            self.load_permissions()
            self.app.notify(message, severity="success")

        except Exception as e:
            self.app.notify(f"Error saving permission: {e}", severity="error")
