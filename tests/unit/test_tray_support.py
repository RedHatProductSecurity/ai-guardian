"""Tray support entries: native review, never a shell or direct send."""

from types import SimpleNamespace
from unittest.mock import Mock
import threading

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
def test_host_support_entry_is_only_shown_without_daemon_targets(monkeypatch, targets):
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
    bounds = (1920, 0, 1920, 1040)
    capture = Mock(return_value=bounds)
    monkeypatch.setattr(tray._menu, "_capture_tray_screen_bounds", capture)

    rendered = tray._build_tray_menu()
    support = [
        entry
        for entry in rendered
        if getattr(entry, "text", None) == "Contact supports — local tray host"
    ]
    if targets:
        assert support == []
        launch.assert_not_called()
        daemon.assert_not_called()
        return

    assert len(support) == 1
    assert support[0].enabled is True
    labels = [getattr(entry, "text", None) for entry in rendered]
    assert labels.index("Contact supports — local tray host") + 1 == labels.index(
        menu.about_label
    )
    launch.assert_not_called()

    support[0].action(None, support[0])

    launch.assert_called_once_with(screen_bounds=bounds)
    capture.assert_called_once_with(None)
    daemon.assert_not_called()


@pytest.mark.parametrize(
    "runtime", ["local", "container", "kubernetes", "manual", "ssh"]
)
@pytest.mark.parametrize("multi", [False, True])
def test_target_support_is_present_in_flat_and_nested_menus_and_never_retargets(
    monkeypatch, runtime, multi
):
    from tests.fixtures.ssh_tray import Menu, PYSTRAY, build, find, make_tray, visible
    from ai_guardian.tray import menu_builder

    target = DaemonTarget(
        "chosen",
        runtime,
        status="running",
        url="https://source.invalid",
        auth_token="synthetic-source-auth",
    )
    other = DaemonTarget("other", "manual", status="running")
    tray = make_tray([target, other] if multi else [target])
    tray._multi_client.get_status.return_value = {}
    if runtime == "ssh" or multi:
        rendered = build(tray)
        if multi:
            daemon_menus = [entry.submenu for entry in visible(rendered)]
            assert len(daemon_menus) == 2
            for daemon_menu in daemon_menus:
                assert (
                    sum(
                        entry.label == "Contact supports"
                        for entry in visible(daemon_menu)
                    )
                    == 1
                )
            rendered = daemon_menus[0]
    else:
        monkeypatch.setattr(menu_builder, "pystray", PYSTRAY)
        rendered = Menu(*tray._menu._build_single_daemon_menu_items())
    label = "Contact supports" if multi else "Contact supports — chosen (daemon)"
    assert sum(entry.label == label for entry in visible(rendered)) == 1
    action = find(rendered, label)
    launch = Mock()
    monkeypatch.setattr(menu, "launch_support", launch)
    # Reordering, replacing discovery objects and editing names cannot change the
    # rendered action's identity, endpoint, credentials or eventual source label.
    target.name = "renamed"
    target.url = "https://replacement.invalid"
    target.auth_token = "synthetic-other-auth"
    tray._targets = [other]
    action.action(None, None)
    selected = launch.call_args.kwargs["target"]
    assert (selected.name, selected.url, selected.auth_token) == (
        "chosen",
        "https://source.invalid",
        "synthetic-source-auth",
    )
    assert launch.call_args.kwargs["client"] is tray._multi_client
    tray._check_and_autostart_daemon.assert_not_called()


def test_local_daemon_keeps_bundled_maintenance_menu_in_multi_daemon_mode(
    monkeypatch,
):
    from ai_guardian.tray.plugins import _load_bundled_plugins, plugins_to_dict
    from tests.fixtures.ssh_tray import build, find, make_tray, visible

    local = DaemonTarget("local", "local", status="running")
    remote = DaemonTarget("remote", "manual", status="running")
    tray = make_tray([local, remote])
    tray._multi_client._local_plugins.return_value = plugins_to_dict(
        _load_bundled_plugins()
    )
    tray._multi_client.get_plugins.return_value = None
    monkeypatch.setattr(tray._plugins, "_get_daemon_menu_tags", lambda _target: [])
    tray._plugins._poll_plugins()

    local_menu = visible(build(tray))[0].submenu
    maintenance = find(local_menu, "Maintenance")

    assert find(maintenance.submenu, "Stop Daemon")
    assert find(maintenance.submenu, "Restart Daemon")


def test_remote_launcher_captures_tunnel_before_async_completion(monkeypatch):
    from ai_guardian.tray import support

    old_tunnel = Mock()
    target = DaemonTarget(
        "first VM", "ssh", ssh_tunnel=old_tunnel, tls={"server_name": "source.invalid"}
    )
    monkeypatch.setattr("ai_guardian.ui.display.get_preferred_ui", lambda: "tkinter")
    monkeypatch.delenv("AI_GUARDIAN_NO_TKINTER", raising=False)
    monkeypatch.setattr(support, "_review_lock", threading.Lock())
    thread = Mock()
    flow = Mock()
    monkeypatch.setattr(support.threading, "Thread", thread)
    monkeypatch.setattr(support, "run_support_flow", flow)
    client = Mock()
    assert support.open_support_dialog(target=target, client=client)
    target.ssh_tunnel = Mock()
    target.name = "second VM"
    target.tls["server_name"] = "different.invalid"
    flow.assert_not_called()
    thread.call_args.kwargs["target"]()
    selected = flow.call_args.kwargs["target"]
    assert selected.ssh_tunnel is old_tunnel
    assert selected.name == "first VM"
    assert selected.tls == {"server_name": "source.invalid"}
    assert not support._review_lock.locked()


@pytest.mark.parametrize("before_connect", [False, True])
@pytest.mark.parametrize("multi", [False, True])
def test_ssh_support_captures_current_verified_tunnel_when_clicked(
    monkeypatch, before_connect, multi
):
    from tests.fixtures.ssh_tray import build, find, make_tray, visible

    stale = None if before_connect else Mock(name="closed-tunnel")
    target = DaemonTarget(
        "Chosen VM",
        "ssh",
        ssh_id="saved-vm",
        ssh_tunnel=stale,
        status="offline" if before_connect else "running",
    )
    other = DaemonTarget("Other VM", "ssh", ssh_id="other-vm")
    tray = make_tray([target, other] if multi else [target])
    rendered = build(tray)
    if multi:
        rendered = visible(rendered)[0].submenu
    action = find(
        rendered,
        "Contact supports" if multi else "Contact supports — Chosen VM (daemon)",
    )
    live = Mock(name="current-verified-tunnel")
    target.ssh_tunnel = live
    target.status = "running"
    target.stats = {"version": "1.21.0", "paused": False}
    if multi:
        tray._targets = [other, target]
    launch = Mock()
    monkeypatch.setattr(menu, "launch_support", launch)

    action.action(None, None)

    selected = launch.call_args.kwargs["target"]
    assert selected.ssh_tunnel is live
    assert selected.name == "Chosen VM"
    assert selected.ssh_id == "saved-vm"
    live.request.assert_not_called()  # Nothing runs on the menu/UI thread.
    target.ssh_tunnel = Mock(name="later-reconnect")
    assert selected.ssh_tunnel is live  # The in-flight operation never migrates.


@pytest.mark.parametrize("change", ["removed", "replacement", "saved-id"])
def test_ssh_support_never_reuses_a_removed_or_replaced_connection(monkeypatch, change):
    from tests.fixtures.ssh_tray import build, find, make_tray

    original = Mock(name="original-tunnel")
    target = DaemonTarget("Chosen VM", "ssh", ssh_id="saved-vm", ssh_tunnel=original)
    tray = make_tray([target])
    action = find(build(tray), "Contact supports — Chosen VM (daemon)")
    if change == "removed":
        tray._targets = []
    elif change == "replacement":
        tray._targets = [
            DaemonTarget("Chosen VM", "ssh", ssh_id="saved-vm", ssh_tunnel=Mock())
        ]
    else:
        target.ssh_id = "different-saved-identity"
        target.ssh_tunnel = Mock()
    launch = Mock()
    monkeypatch.setattr(menu, "launch_support", launch)

    action.action(None, None)

    assert launch.call_args.kwargs["target"].ssh_tunnel is None
    original.request.assert_not_called()
