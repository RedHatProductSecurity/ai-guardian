"""Inspectable tray descriptors with explicit, isolated state and no GUI."""

from types import SimpleNamespace
from unittest import mock

from ai_guardian.tray.app import DaemonTray
from ai_guardian.tray.menu_builder import TrayMenuBuilder
from ai_guardian.tray.plugin_runner import TrayPluginMenuBuilder
from ai_guardian.tray.plugins import _load_bundled_plugins


class Menu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = items


class Item:
    def __init__(self, text, action=None, **kwargs):
        self.text = text
        self.action = action
        self.kwargs = kwargs

    @property
    def submenu(self):
        return self.action if isinstance(self.action, Menu) else None

    @property
    def label(self):
        return self.text(None) if callable(self.text) else self.text

    @property
    def visible(self):
        value = self.kwargs.get("visible", True)
        return value(None) if callable(value) else value

    @property
    def enabled(self):
        value = self.kwargs.get("enabled", True)
        return value(None) if callable(value) else value

    @property
    def checked(self):
        value = self.kwargs.get("checked", False)
        return value(None) if callable(value) else value


PYSTRAY = SimpleNamespace(Menu=Menu, MenuItem=Item)


def make_tray(targets):
    tray = DaemonTray.__new__(DaemonTray)
    tray._targets = targets
    tray._multi_client = mock.Mock()
    tray._refresh_event = mock.Mock()
    tray._ask_forwarding_failed = set()
    tray._mcp_installed_per_daemon = {}
    tray._mcp_installed_local = True
    tray._proactive_level = "low"
    tray._daemon_about_cache = {}
    tray._get_stats = mock.Mock(return_value={})
    tray._can_autostart_daemon = mock.Mock(return_value=False)
    tray._check_and_autostart_daemon = mock.Mock()
    tray._ensure_web_console_ready = mock.Mock(return_value=True)
    tray._dispatch_to_main = mock.Mock()
    tray._refresh_menu = mock.Mock()
    tray._health = mock.Mock()
    tray._health._daemon_versions = {}
    tray._health._version_mismatch_notified = set()
    tray._health._is_target_stale.return_value = False
    tray._health._is_upgrade_available.return_value = False
    tray._health._restart_in_progress = False
    tray._menu = TrayMenuBuilder(tray)
    tray._plugins = TrayPluginMenuBuilder(tray)
    tray._plugins._MAX_PLUGIN_SLOTS = 2
    tray._plugins._MAX_ITEMS_PER_PLUGIN = 6
    tray._plugins._MAX_SUBMENU_ITEMS = 6
    tray._plugins._MAX_SUBMENU_DEPTH = 1
    for target in targets:
        if target.runtime == "ssh":
            tray._plugins._ssh_plugins[id(target)] = (target, _load_bundled_plugins())
    return tray


def build(tray):
    with (
        mock.patch("ai_guardian.tray.menu_builder.pystray", PYSTRAY),
        mock.patch("ai_guardian.tray.plugin_runner.pystray", PYSTRAY),
    ):
        return Menu(*tray._menu._build_multi_daemon_menu_items())


def visible(menu):
    return [item for item in menu.items if isinstance(item, Item) and item.visible]


def find(menu, label):
    return next(item for item in visible(menu) if item.label == label)
