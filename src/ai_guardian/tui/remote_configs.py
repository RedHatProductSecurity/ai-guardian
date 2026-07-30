#!/usr/bin/env python3
"""
Remote Configs Tab Content

Manage remote policy configuration URLs for loading
permissions and settings from enterprise/team sources.
"""

import json
from typing import List, Dict, Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static, Button, Input, Label, Checkbox
from textual.message import Message

from ai_guardian.config.utils import get_config_dir
from ai_guardian.tui.schema_defaults import (
    ConfigSaveMixin,
    SchemaDefaultsMixin,
    default_indicator,
    default_placeholder,
)


class RemoteConfigEntry(Container):
    """Widget for displaying a single remote config URL with controls."""

    CSS = """
    RemoteConfigEntry {
        height: auto;
        margin: 0 0 1 0;
        border: solid $primary;
        padding: 1;
    }

    RemoteConfigEntry .url-text {
        width: 100%;
        color: $accent;
        margin: 0 0 0.5 0;
    }

    RemoteConfigEntry .details-row {
        width: 100%;
        height: auto;
        margin: 0 0 0.5 0;
    }

    RemoteConfigEntry .button-row {
        width: 100%;
        height: auto;
        align: right middle;
    }

    RemoteConfigEntry Button {
        margin: 0 0 0 1;
    }

    RemoteConfigEntry Checkbox {
        margin: 0 2 0 0;
    }
    """

    class RemovePressed(Message):
        """Message sent when remove button is pressed."""

        def __init__(self, index: int):
            super().__init__()
            self.index = index

    class TestPressed(Message):
        """Message sent when test button is pressed."""

        def __init__(self, index: int, url: str):
            super().__init__()
            self.index = index
            self.url = url

    def __init__(self, index: int, url_config: Dict[str, Any], **kwargs):
        """
        Initialize remote config entry.

        Args:
            index: Index of this entry in the list
            url_config: The URL configuration (url, enabled, token_env)
        """
        super().__init__(**kwargs)
        self.index = index
        self.url_config = url_config

        # Parse config - handle both string and object formats
        if isinstance(url_config, str):
            self.url = url_config
            self.enabled = True
            self.token_env = ""
        else:
            self.url = url_config.get("url", "")
            self.enabled = url_config.get("enabled", True)
            self.token_env = url_config.get("token_env", "")

    def compose(self) -> ComposeResult:
        """Compose the remote config entry widgets."""
        yield Static(f"[bold]{self.url}[/bold]", classes="url-text")

        with Horizontal(classes="details-row"):
            yield Checkbox("Enabled", value=self.enabled, id=f"enabled_{self.index}")
            if self.token_env:
                yield Static(f"Token: ${self.token_env}", classes="muted")

        with Horizontal(classes="button-row"):
            yield Button(
                "Test", variant="primary", id=f"test_{self.index}", classes="compact"
            )
            yield Button(
                "Remove", variant="error", id=f"remove_{self.index}", classes="compact"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        event.stop()  # Prevent event bubbling
        if event.button.id.startswith("test_"):
            self.post_message(self.TestPressed(self.index, self.url))
        elif event.button.id.startswith("remove_"):
            self.post_message(self.RemovePressed(self.index))


class RemoteConfigsContent(ConfigSaveMixin, SchemaDefaultsMixin, Container):
    """Content widget for Remote Configs tab."""

    CONFIG_SECTION = "remote_configs"
    SCHEMA_SECTION = "remote_configs"
    SCHEMA_FIELDS = [
        ("refresh-interval-input", "refresh_interval_hours", "input"),
        ("expire-after-input", "expire_after_hours", "input"),
    ]

    CSS = """
    RemoteConfigsContent {
        height: 100%;
    }

    #remote-configs-header {
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
        align: left middle;
    }

    .setting-row Label {
        margin: 0 2 0 0;
        width: 25;
        content-align: right middle;
    }

    .setting-row Input {
        width: 20;
        margin: 0 1 0 0;
    }

    .setting-row Button {
        margin: 0 1 0 0;
    }

    #urls-list {
        margin: 1 0;
        min-height: 10;
        max-height: 16;
    }

    #add-url-section {
        margin: 1 0;
        padding: 1;
        background: $surface;
        border: solid $accent;
    }

    #add-url-section Input {
        width: 60;
        margin: 0 1 0 0;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the remote configs tab content."""
        yield Static(
            "[bold]Remote Configuration Management[/bold]", id="remote-configs-header"
        )

        with VerticalScroll():
            # Configuration URLs section
            with Container(classes="section"):
                yield Static("[bold]Remote Config URLs[/bold]", classes="section-title")
                yield Static(
                    "[dim]Load permissions and policies from remote sources (enterprise/team policies)[/dim]",
                    classes="section-title",
                )

                with VerticalScroll(id="urls-list"):
                    yield Static("[dim]No remote configs configured[/dim]")

            # Add new URL section
            with Container(id="add-url-section"):
                yield Static(
                    "[bold]Add New Remote Config[/bold]", classes="section-title"
                )

                with Horizontal(classes="setting-row"):
                    yield Label("URL:")
                    yield Input(
                        placeholder="https://example.com/ai-guardian.json",
                        id="new-url-input",
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("Token Env Var:")
                    yield Input(
                        placeholder="GITHUB_TOKEN (optional)", id="new-token-env-input"
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("")
                    yield Button("Add URL", variant="success", id="add-url-button")

            # Cache settings section
            with Container(classes="section"):
                yield Static("[bold]Cache Settings[/bold]", classes="section-title")

                with Horizontal(classes="setting-row"):
                    yield Label("Refresh Interval:")
                    yield Input(
                        placeholder=default_placeholder(
                            "remote_configs.refresh_interval_hours"
                        ),
                        id="refresh-interval-input",
                    )
                    yield Static(
                        f"[dim]hours (Press Enter to save)[/dim] "
                        f"{default_indicator('remote_configs.refresh_interval_hours')}"
                    )

                with Horizontal(classes="setting-row"):
                    yield Label("Expire After:")
                    yield Input(
                        placeholder=default_placeholder(
                            "remote_configs.expire_after_hours"
                        ),
                        id="expire-after-input",
                    )
                    yield Static(
                        f"[dim]hours (Press Enter to save)[/dim] "
                        f"{default_indicator('remote_configs.expire_after_hours')}"
                    )

    def on_mount(self) -> None:
        """Load configuration when mounted."""
        self.load_config()

    def refresh_content(self) -> None:
        """Refresh configuration (called by parent app)."""
        self.load_config()

    def load_config(self) -> None:
        """Load and display remote configs configuration."""
        config_dir = get_config_dir()
        config_path = config_dir / "ai-guardian.json"

        # Load config
        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                self.app.notify(f"Error loading config: {e}", severity="error")
                return

        # Load remote configs
        remote_configs = config.get("remote_configs", {})
        urls = remote_configs.get("urls", [])
        refresh_interval = remote_configs.get("refresh_interval_hours", 12)
        expire_after = remote_configs.get("expire_after_hours", 168)

        # Update URL list
        self.update_urls_list(urls)

        # Update cache settings
        try:
            self.query_one("#refresh-interval-input", Input).value = str(
                refresh_interval
            )
            self.query_one("#expire-after-input", Input).value = str(expire_after)
        except Exception:
            pass  # Widgets may not be mounted yet

        self._apply_default_indicators(remote_configs)

    def update_urls_list(self, urls: List[Any]) -> None:
        """Update the URLs list display."""
        try:
            list_container = self.query_one("#urls-list", VerticalScroll)

            # Remove all existing children
            list_container.remove_children()

            # Add URL entries
            if urls:
                for idx, url_config in enumerate(urls):
                    list_container.mount(RemoteConfigEntry(idx, url_config))
            else:
                list_container.mount(Static("[dim]No remote configs configured[/dim]"))

        except Exception as e:
            self.app.notify(f"Error updating URLs list: {e}", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "add-url-button":
            self.add_url()

    def on_remote_config_entry_remove_pressed(
        self, message: RemoteConfigEntry.RemovePressed
    ) -> None:
        """Handle remove button press on URL entry."""
        self.remove_url(message.index)

    def on_remote_config_entry_test_pressed(
        self, message: RemoteConfigEntry.TestPressed
    ) -> None:
        """Handle test button press on URL entry."""
        self.test_url(message.url)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox toggle for URL enabled state."""
        if event.checkbox.id and event.checkbox.id.startswith("enabled_"):
            try:
                index = int(event.checkbox.id.split("_")[1])
                self.toggle_url_enabled(index, event.value)
            except Exception:
                pass  # intentionally silent — best-effort operation

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields."""
        if event.input.id == "refresh-interval-input":
            try:
                hours = int(event.value)
                self.save_cache_setting("refresh_interval_hours", hours)
            except ValueError:
                self.app.notify("Refresh interval must be a number", severity="error")
        elif event.input.id == "expire-after-input":
            try:
                hours = int(event.value)
                self.save_cache_setting("expire_after_hours", hours)
            except ValueError:
                self.app.notify("Expire after must be a number", severity="error")

    def add_url(self) -> None:
        """Add a new remote config URL."""
        url = self.query_one("#new-url-input", Input).value.strip()
        token_env = self.query_one("#new-token-env-input", Input).value.strip()

        if not url:
            self.app.notify("Please enter a URL", severity="error")
            return

        # Validate URL format
        if not (
            url.startswith("http://")
            or url.startswith("https://")
            or url.startswith("/")
        ):
            self.app.notify(
                "URL must start with http://, https://, or / (for local files)",
                severity="error",
            )
            return

        try:
            config = self._load_full_config()
            config.setdefault("remote_configs", {}).setdefault("urls", [])

            url_config = {"url": url, "enabled": True}
            if token_env:
                url_config["token_env"] = token_env

            existing_urls = config["remote_configs"]["urls"]
            for existing in existing_urls:
                existing_url = (
                    existing if isinstance(existing, str) else existing.get("url", "")
                )
                if existing_url == url:
                    self.app.notify("URL already exists", severity="warning")
                    return

            config["remote_configs"]["urls"].append(url_config)
            self._write_full_config(config)

            self.query_one("#new-url-input", Input).value = ""
            self.query_one("#new-token-env-input", Input).value = ""

            self.load_config()
            self.app.notify(f"✓ Added remote config: {url}", severity="success")

        except Exception as e:
            self.app.notify(f"Error adding URL: {e}", severity="error")

    def remove_url(self, index: int) -> None:
        """Remove a remote config URL."""
        try:
            config = self._load_full_config()

            if "remote_configs" in config and "urls" in config["remote_configs"]:
                urls = config["remote_configs"]["urls"]
                if 0 <= index < len(urls):
                    removed_url = urls.pop(index)
                    removed_url_str = (
                        removed_url
                        if isinstance(removed_url, str)
                        else removed_url.get("url", "")
                    )

                    self._write_full_config(config)

                    self.load_config()
                    self.app.notify(
                        f"✓ Removed remote config: {removed_url_str}",
                        severity="success",
                    )

        except Exception as e:
            self.app.notify(f"Error removing URL: {e}", severity="error")

    def toggle_url_enabled(self, index: int, enabled: bool) -> None:
        """Toggle the enabled state of a URL."""
        try:
            config = self._load_full_config()

            if "remote_configs" in config and "urls" in config["remote_configs"]:
                urls = config["remote_configs"]["urls"]
                if 0 <= index < len(urls):
                    if isinstance(urls[index], str):
                        urls[index] = {"url": urls[index], "enabled": enabled}
                    else:
                        urls[index]["enabled"] = enabled

                    self._write_full_config(config)

                    status = "enabled" if enabled else "disabled"
                    self.app.notify(f"✓ URL {status}", severity="success")

        except Exception as e:
            self.app.notify(f"Error toggling URL: {e}", severity="error")

    def save_cache_setting(self, field: str, value: int) -> None:
        """Save a cache setting."""
        try:
            self._save_config_field(field, value)
            self.app.notify(f"✓ Saved {field}: {value}", severity="success")
        except Exception as e:
            self.app.notify(f"Error saving {field}: {e}", severity="error")

    def test_url(self, url: str) -> None:
        """Test connection to a remote config URL."""
        try:
            import requests

            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                self.app.notify(f"✓ URL is reachable: {url}", severity="success")
            else:
                self.app.notify(
                    f"URL returned status {response.status_code}", severity="warning"
                )
        except ImportError:
            self.app.notify(
                "requests library not installed - cannot test connection",
                severity="error",
            )
        except Exception as e:
            self.app.notify(f"✗ Cannot connect to URL: {e}", severity="error")

    def action_refresh(self) -> None:
        """Refresh configuration (triggered by 'r' key)."""
        self.load_config()
        self.app.notify("Remote configs refreshed", severity="information")
