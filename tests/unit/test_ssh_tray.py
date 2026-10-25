"""Tray SSH callbacks never wait on network or spawn an interactive shell."""

from types import SimpleNamespace
from unittest import mock

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
    with mock.patch("ai_guardian.tray.app.threading.Thread") as thread:
        tray._on_add_ssh_daemon()
    assert thread.call_args.kwargs["target"] is ssh_connections.open_enrollment
    thread.return_value.start.assert_called_once()


def test_enrollment_opens_local_web_picker_without_daemon_control():
    tray = mock.Mock()
    tray._ensure_web_console_ready.return_value = True
    with mock.patch("ai_guardian.tray.menu.open_web_console") as open_console:
        ssh_connections.open_enrollment(tray)
    open_console.assert_called_once_with()
    tray._check_and_autostart_daemon.assert_not_called()


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
