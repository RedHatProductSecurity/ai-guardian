"""Global tray support entry: native review, never a shell or direct send."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.tray import app, menu


def test_support_launcher_opens_native_review_without_a_shell(
    monkeypatch,
):
    dialog = Mock(return_value=True)
    terminal = Mock(side_effect=AssertionError("Tray support must not open a shell"))
    monkeypatch.setattr("ai_guardian.tray.support.open_support_dialog", dialog)
    monkeypatch.setattr("ai_guardian.daemon.multi_client._launch_in_terminal", terminal)

    assert menu.launch_support() is True

    dialog.assert_called_once_with()
    terminal.assert_not_called()


def test_support_launcher_reports_missing_desktop_without_sending(monkeypatch):
    notify = Mock()
    monkeypatch.setattr("ai_guardian.ui.display.get_preferred_ui", lambda: "headless")
    monkeypatch.setattr("ai_guardian.tray.support.show_notification", notify)

    assert menu.launch_support() is False

    notify.assert_called_once_with(
        "AI Guardian Support",
        "The support dialog needs a native desktop. Run 'ai-guardian support send --prepare' in your own terminal for the standalone workflow. Nothing was sent.",
    )


@pytest.mark.parametrize(
    "targets",
    [
        [],
        [DaemonTarget(name="local", runtime="local", status="stopped")],
        [DaemonTarget(name="local", runtime="local", status="running")],
        [DaemonTarget(name="remote", runtime="container", status="running")],
        [
            DaemonTarget(name="local", runtime="local", status="paused"),
            DaemonTarget(name="remote", runtime="kubernetes", status="running"),
        ],
    ],
)
def test_support_entry_is_global_without_daemon_or_mcp_dependency(monkeypatch, targets):
    class Menu(list):
        SEPARATOR = object()

        def __init__(self, *items):
            super().__init__(items)

    def item(text, action, **kwargs):
        return SimpleNamespace(
            text=text, action=action, enabled=kwargs.get("enabled", True)
        )

    monkeypatch.setattr(app, "pystray", SimpleNamespace(Menu=Menu, MenuItem=item))
    tray = app.DaemonTray(lambda: {}, lambda: None, lambda minutes: None)
    tray._targets = targets
    for method in (
        "_build_single_daemon_menu_items",
        "_build_single_daemon_daemon_items",
        "_build_multi_daemon_menu_items",
        "_build_openshell_middleware_menu_items",
        "_build_sandbox_create_menu_items",
        "_build_sandbox_start_menu_items",
        "_build_ide_setup_menu_items",
    ):
        monkeypatch.setattr(tray._menu, method, lambda: [])
    monkeypatch.setattr(tray._plugins, "_build_single_daemon_plugin_items", lambda: [])
    monkeypatch.setattr(tray._plugins, "_build_global_plugin_items", lambda: [])
    daemon = Mock(side_effect=AssertionError("Support must not auto-start a daemon"))
    monkeypatch.setattr(tray, "_can_autostart_daemon", daemon)
    launch = Mock(return_value=True)
    monkeypatch.setattr(menu, "launch_support", launch)

    rendered = tray._build_tray_menu()
    support = [
        entry
        for entry in rendered
        if getattr(entry, "text", None) == "Contact supports"
    ]
    assert len(support) == 1
    assert support[0].enabled is True
    labels = [getattr(entry, "text", None) for entry in rendered]
    assert labels.index("Contact supports") + 1 == labels.index(menu.about_label)
    launch.assert_not_called()

    support[0].action(None, support[0])

    launch.assert_called_once_with()
    daemon.assert_not_called()
