"""Tray SSH callbacks never wait on network or spawn an interactive shell."""

from types import SimpleNamespace
from unittest import mock

import pytest

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.tray.app import DaemonTray
from ai_guardian.tray import ssh_connections


def test_ssh_tray_status_is_cached_without_network():
    tray = DaemonTray.__new__(DaemonTray)
    tray._multi_client = mock.Mock()
    target = DaemonTarget(name="ssh-alias", runtime="ssh", stats={"paused": False})
    tray._active_target = target
    tray._targets = [target]
    assert tray._get_active_stats() == {"paused": False}
    assert tray._get_target_stats(target) == {"paused": False}
    assert not tray._is_single_daemon()
    tray._multi_client.get_status.assert_not_called()


def test_ssh_label_keeps_existing_version_monitoring_without_network():
    from ai_guardian.tray.menu_builder import TrayMenuBuilder

    tray = DaemonTray.__new__(DaemonTray)
    tray._multi_client = mock.Mock()
    target = DaemonTarget(
        name="ssh-alias",
        runtime="ssh",
        status="running",
        stats={"version": "1.0.0", "mcp_installed": True},
    )
    tray._targets = [target]
    tray._ask_forwarding_failed = set()
    tray._mcp_installed_per_daemon = {}
    tray._health = SimpleNamespace(
        _daemon_versions={}, _version_mismatch_notified=set()
    )
    tray._menu = TrayMenuBuilder(tray)
    pystray = SimpleNamespace(
        Menu=lambda *items: list(items),
        MenuItem=lambda text, action, **kwargs: SimpleNamespace(
            text=text, action=action
        ),
    )
    entries = ssh_connections.build_items(tray, pystray)
    assert target.name in entries[0].text(None)
    assert tray._health._daemon_versions[(target.name, "ssh")] == "1.0.0"
    assert tray._mcp_installed_per_daemon[(target.name, "ssh")] is True
    tray._multi_client.get_status.assert_not_called()


def test_add_ssh_dispatches_a_worker_not_a_terminal():
    tray = DaemonTray.__new__(DaemonTray)
    tray._icon = mock.Mock()
    bounds = (1920, 0, 1920, 1080)
    with (
        mock.patch("ai_guardian.tray.app.threading.Thread") as thread,
        mock.patch(
            "ai_guardian.tray.dialog_placement._get_tray_screen_bounds",
            return_value=bounds,
        ) as capture,
    ):
        tray._on_add_ssh_daemon()
    assert thread.call_args.kwargs["target"] is ssh_connections.open_enrollment
    assert thread.call_args.kwargs["kwargs"] == {"screen_bounds": bounds}
    capture.assert_called_once_with(tray._icon)
    thread.return_value.start.assert_called_once()


def test_enrollment_uses_shared_form_flow_not_web_console():
    tray = mock.Mock()
    with (
        mock.patch("ai_guardian.ui.forms.run_form_flow", return_value=False) as flow,
        mock.patch("ai_guardian.tray.menu.open_web_console") as open_console,
    ):
        ssh_connections.open_enrollment(tray)
    flow.assert_called_once()
    open_console.assert_not_called()
    tray._ensure_web_console_ready.assert_not_called()
    tray._check_and_autostart_daemon.assert_not_called()


def test_manage_saved_connection_still_opens_local_web_picker():
    tray = mock.Mock()
    tray._ensure_web_console_ready.return_value = True
    with mock.patch("ai_guardian.tray.menu.open_web_console") as open_console:
        ssh_connections.open_management(tray)
    open_console.assert_called_once_with()


def test_ssh_control_menu_dispatches_outside_callback_thread():
    target = DaemonTarget(name="ssh-alias", runtime="ssh", status="running")
    tray = SimpleNamespace(
        _targets=[target], _multi_client=mock.Mock(), _refresh_event=mock.Mock()
    )

    def item(text, action, **kwargs):
        return SimpleNamespace(text=text, action=action, **kwargs)

    pystray = SimpleNamespace(Menu=lambda *items: list(items), MenuItem=item)
    entries = ssh_connections.build_items(tray, pystray)
    pause = next(item for item in entries[0].action if item.text == "Pause...")
    with mock.patch("ai_guardian.tray.ssh_connections.threading.Thread") as thread:
        pause.action[0].action()
        tray._multi_client.send_pause.assert_not_called()
        thread.call_args.kwargs["target"]()
    tray._multi_client.send_pause.assert_called_once_with(target, 5)
    tray._refresh_event.set.assert_called_once()


def test_ssh_prompt_decision_cannot_move_to_a_reconnected_generation():
    from ai_guardian.ui.ask_dialog import AskDecision, AskResult

    tray = DaemonTray.__new__(DaemonTray)
    tray._in_flight_prompts = set()
    tray._multi_client = mock.Mock()
    old = mock.Mock()
    target = DaemonTarget(name="ssh-alias", runtime="ssh", ssh_tunnel=old)
    with mock.patch("ai_guardian.tray.app.threading.Thread") as thread:
        tray._handle_remote_prompt(target, {"prompt_id": "prompt-1", "violation": {}})
        respond = thread.call_args.kwargs["target"]
    target.ssh_tunnel = mock.Mock()  # Reconnect while the permission dialog is open.
    with mock.patch(
        "ai_guardian.ui.ask_dialog._show_via_subprocess",
        return_value=AskResult(AskDecision.BLOCK),
    ):
        respond()
    decision_target = tray._multi_client.send_prompt_decision.call_args.args[0]
    assert decision_target.ssh_tunnel is old
    assert not tray._in_flight_prompts


def test_two_ssh_daemons_can_have_the_same_pending_prompt_id():
    tray = DaemonTray.__new__(DaemonTray)
    tray._in_flight_prompts = set()
    with mock.patch("ai_guardian.tray.app.threading.Thread") as thread:
        for name in ("ssh-first", "ssh-second"):
            target = DaemonTarget(name=name, runtime="ssh", ssh_tunnel=mock.Mock())
            tray._handle_remote_prompt(target, {"prompt_id": "prompt-1"})
        assert thread.call_count == 2


def test_unsupported_prompt_registration_warning_survives_stats_refresh():
    from ai_guardian.daemon.ssh_tunnel import POLLING_ERROR

    target = DaemonTarget(name="ssh-alias", runtime="ssh", status="running")
    tray = SimpleNamespace(_targets=[target], _ask_forwarding_failed={target.name})
    pystray = SimpleNamespace(
        Menu=lambda *items: list(items),
        MenuItem=lambda text, action, **kwargs: SimpleNamespace(
            text=text, action=action
        ),
    )
    with (
        mock.patch("ai_guardian.tray.ssh_connections.threading.Thread") as thread,
        mock.patch("ai_guardian.tray.plugins.show_dialog") as dialog,
    ):
        items = ssh_connections.build_items(tray, pystray)
        items[0].action[0].action()
        thread.call_args.kwargs["target"]()
    assert POLLING_ERROR in dialog.call_args.args[1]


def test_candidate_menu_is_cached_and_direct_review_dispatches_existing_modal():
    discovery = SimpleNamespace(
        ssh_alias_discovery={
            "enabled": True,
            "aliases": ("existing-vm",),
            "notices": (),
        },
        ssh_manager=mock.Mock(),
    )
    tray = SimpleNamespace(
        _discovery=discovery, _on_add_ssh_daemon=mock.Mock(), _refresh_event=mock.Mock()
    )
    pystray = SimpleNamespace(
        Menu=lambda *items: list(items),
        MenuItem=lambda text, action, **kwargs: SimpleNamespace(
            text=text, action=action
        ),
    )
    entry = ssh_connections.build_candidate_items(tray, pystray)[0]
    assert entry.text == "SSH aliases available to pair (1)"
    assert entry.action[0].text == "existing-vm"
    review = entry.action[0].action[0]
    assert review.text == "Review discovered daemon"
    review.action("icon", "item")
    tray._on_add_ssh_daemon.assert_called_once_with("icon", "item", alias="existing-vm")
    discovery.ssh_manager.prepare.assert_not_called()
    discovery.ssh_manager.refresh_aliases.assert_not_called()
    with mock.patch("ai_guardian.tray.ssh_connections.threading.Thread") as thread:
        entry.action[0].action[1].action()
        discovery.ssh_manager.dismiss_alias.assert_not_called()
        thread.call_args.kwargs["target"]()
    discovery.ssh_manager.dismiss_alias.assert_called_once_with("existing-vm")


def test_candidate_review_captures_placement_then_starts_worker():
    tray = DaemonTray.__new__(DaemonTray)
    tray._icon = mock.Mock()
    with (
        mock.patch("ai_guardian.tray.app.threading.Thread") as thread,
        mock.patch(
            "ai_guardian.tray.dialog_placement._get_tray_screen_bounds",
            return_value=(0, 0, 1920, 1080),
        ),
    ):
        tray._on_add_ssh_daemon(alias="existing-vm")
    assert thread.call_args.kwargs["target"] is ssh_connections.open_enrollment
    assert thread.call_args.kwargs["kwargs"] == {
        "screen_bounds": (0, 0, 1920, 1080),
        "alias": "existing-vm",
    }
    thread.return_value.start.assert_called_once()


@pytest.mark.parametrize("enabled,aliases", [(False, ()), (True, ()), (True, ("vm",))])
def test_discovery_settings_entry_is_global_and_building_it_never_reads_config(
    monkeypatch, enabled, aliases
):
    from ai_guardian.tray import app

    class Menu(list):
        SEPARATOR = object()

        def __init__(self, *items):
            super().__init__(items)

    def item(text, action, **kwargs):
        return SimpleNamespace(
            text=text, action=action, enabled=kwargs.get("enabled", True)
        )

    monkeypatch.setattr(app, "pystray", SimpleNamespace(Menu=Menu, MenuItem=item))
    tray = DaemonTray(lambda: {}, lambda: None, lambda minutes: None)
    tray._targets = []  # No local or enrolled remote daemon is required.
    tray._discovery = SimpleNamespace(
        ssh_alias_discovery={
            "enabled": enabled,
            "aliases": aliases,
            "notices": (),
        }
    )
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
    with (
        mock.patch("ai_guardian.daemon.ssh_config.load_settings") as read,
        mock.patch("ai_guardian.daemon.ssh_config.scan_aliases") as scan,
    ):
        entries = tray._build_tray_menu()
    settings = [
        entry
        for entry in entries
        if getattr(entry, "text", "") == "Discover SSH aliases..."
    ]
    assert len(settings) == 1
    assert settings[0].enabled is True
    assert settings[0].action == tray._on_discover_ssh_aliases
    labels = [getattr(entry, "text", "") for entry in entries]
    assert (
        labels.index("Discover SSH aliases...")
        == labels.index("Add daemon via SSH") + 1
    )
    read.assert_not_called()
    scan.assert_not_called()


def test_discovery_settings_captures_monitor_then_dispatches_worker():
    tray = DaemonTray.__new__(DaemonTray)
    tray._icon = mock.Mock()
    bounds = (1920, 0, 1920, 1080)
    with (
        mock.patch("ai_guardian.tray.app.threading.Thread") as thread,
        mock.patch(
            "ai_guardian.tray.dialog_placement._get_tray_screen_bounds",
            return_value=bounds,
        ) as capture,
        mock.patch("ai_guardian.daemon.ssh_config.load_settings") as read,
    ):
        tray._on_discover_ssh_aliases()
    capture.assert_called_once_with(tray._icon)
    read.assert_not_called()
    assert thread.call_args.kwargs["target"] is ssh_connections.open_discovery_settings
    assert thread.call_args.kwargs["kwargs"] == {"screen_bounds": bounds}
    assert thread.call_args.kwargs["args"] == (tray,)
    thread.return_value.start.assert_called_once()
