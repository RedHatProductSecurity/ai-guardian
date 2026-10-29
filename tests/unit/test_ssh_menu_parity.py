"""Shared menu layouts and selected-connection action binding."""

from unittest import mock

import pytest

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.tray.ssh_connections import target_action
from ai_guardian.tray.pause import PauseSnapshot
from tests.fixtures.tray_pause import pause_values
from tests.fixtures.ssh_tray import build, find, make_tray, visible


@pytest.fixture
def remote():
    return DaemonTarget(
        "ssh-vm",
        "ssh",
        status="running",
        ssh_id="vm-id",
        ssh_tunnel=mock.Mock(),
        ssh_commands=mock.Mock(cli={"python": "/remote/venv/bin/python"}),
        stats={
            "request_count": 42,
            "version": "1.21.0",
            "mcp_installed": True,
            "mcp_proactive_level": "high",
        },
    )


@pytest.mark.parametrize("multi", [False, True])
def test_standard_menu_structure_and_cached_selected_vm_statistics(remote, multi):
    tray = make_tray(([DaemonTarget("local", "local")] if multi else []) + [remote])
    menu = build(tray)
    if multi:
        menu = visible(menu)[1].submenu
    labels = [item.label for item in visible(menu)]
    standard = [
        "Status",
        *([] if multi else ["Pause..."]),
        "Terminal",
        "Console",
        "Violations",
        "Metrics & Audit",
        "Statistics",
    ]
    assert [label for label in labels if label in standard] == standard
    assert find(build(tray), "Pause...").submenu is None
    assert "Maintenance" in labels
    assert "MCP Proactive: high" in labels
    assert "Manage SSH connection..." in labels
    assert "Web Console" not in labels
    assert find(find(menu, "Statistics").submenu, "Requests: 42")
    tray._multi_client.get_status.assert_not_called()


@pytest.mark.parametrize(
    "panel,page",
    [("Console", ""), ("Violations", "violations"), ("Metrics & Audit", "metrics")],
)
def test_navigation_bound_after_reorder_and_never_autostarts_workstation(
    remote, panel, page
):
    local = DaemonTarget("local", "local")
    tray = make_tray([local, remote])
    menu = visible(build(tray))[1].submenu
    tray._targets.reverse()
    with (
        mock.patch("ai_guardian.tray.ssh_connections.threading.Thread") as thread,
        mock.patch(
            "ai_guardian.tray.dialog_placement._get_tray_screen_bounds",
            return_value=None,
        ),
        mock.patch("ai_guardian.tray.menu.open_web_console") as open_console,
    ):
        find(menu, panel).action(None, None)
        open_console.assert_not_called()
        thread.call_args.kwargs["target"]()
    open_console.assert_called_once_with(remote.name, page)
    tray._check_and_autostart_daemon.assert_not_called()


def test_pause_worker_keeps_clicked_tunnel_and_reports_failure(remote):
    tray = make_tray([remote])
    remote.stats["paused"] = False
    tray._multi_client.get_status.side_effect = lambda _: remote.stats
    snapshot = PauseSnapshot(tray)
    selection = snapshot.resolve(pause_values(snapshot))
    old = remote.ssh_tunnel
    tray._multi_client.send_pause.return_value = False
    remote.ssh_tunnel = mock.Mock()
    assert selection[0].target.ssh_tunnel is old
    assert "connection changed" in snapshot.request(*selection)
    tray._multi_client.send_pause.assert_not_called()


def test_removed_connection_cannot_retarget_another_vm(remote):
    tray = make_tray([remote])
    callback = mock.Mock()
    with (
        mock.patch("ai_guardian.tray.ssh_connections.threading.Thread") as thread,
        mock.patch(
            "ai_guardian.tray.dialog_placement._get_tray_screen_bounds",
            return_value=None,
        ),
        mock.patch("ai_guardian.tray.plugins.show_dialog") as dialog,
    ):
        target_action(tray, remote, callback)()
        tray._targets = [DaemonTarget("replacement", "ssh")]
        thread.call_args.kwargs["target"]()
    callback.assert_not_called()
    assert "removed" in dialog.call_args.args[1]


@pytest.mark.parametrize(
    "stats,label",
    [
        ({}, "MCP Proactive: unavailable"),
        ({"mcp_installed": False}, "MCP: not installed"),
    ],
)
def test_missing_remote_mcp_fields_never_use_workstation_state(remote, stats, label):
    remote.stats = stats
    tray = make_tray([remote])
    menu = find(build(tray), label)
    assert not find(menu.submenu, "high").enabled
    assert "reconnect or upgrade" in visible(menu.submenu)[0].label


def test_remote_mcp_write_uses_vm_global_scope_only(remote):
    tray = make_tray([remote])
    tray._multi_client.write_config.return_value = {"status": "ok"}
    level = find(find(build(tray), "MCP Proactive: high").submenu, "medium")
    with (
        mock.patch("ai_guardian.tray.ssh_connections.threading.Thread") as thread,
        mock.patch(
            "ai_guardian.tray.dialog_placement._get_tray_screen_bounds",
            return_value=None,
        ),
    ):
        level.action(None, None)
        tray._multi_client.write_config.assert_not_called()
        thread.call_args.kwargs["target"]()
    args = tray._multi_client.write_config.call_args.args
    assert args[0].ssh_id == remote.ssh_id
    assert args[1:] == ("global", "mcp_server", "proactive_level", "medium")
    assert tray._proactive_level == "low"


@pytest.mark.parametrize("scope", ["dir", "session"])
@pytest.mark.parametrize("resume", [False, True])
def test_scoped_pause_controls_keep_clicked_connection_and_never_broaden(
    remote, scope, resume
):
    tray = make_tray([remote, DaemonTarget("local", "local")])
    verb = "resume" if resume else "pause"
    operation = getattr(tray._multi_client, f"send_{verb}_{scope}")
    operation.return_value = False
    remote.stats.update(
        paused=False,
        active_project_dirs=["/vm/project"],
        paused_dirs={"/vm/project": 0} if resume else {},
        active_sessions=[{"session_key": "stable-vm-session", "paused": resume}],
    )
    tray._multi_client.get_status.side_effect = lambda _: remote.stats
    snapshot = PauseSnapshot(tray)
    identity = "/vm/project" if scope == "dir" else "stable-vm-session"
    selection = snapshot.resolve(
        pause_values(
            snapshot,
            scope=scope,
            identity=identity,
            action="Resume" if resume else "Pause",
        )
    )
    remote.ssh_tunnel = mock.Mock()
    tray._targets.reverse()
    assert "no request was sent" in snapshot.request(*selection)
    operation.assert_not_called()
    tray._multi_client.send_pause.assert_not_called()
    tray._multi_client.send_resume.assert_not_called()


def test_ssh_upgrade_cannot_fall_back_to_workstation_without_transport(remote):
    from ai_guardian.tray.health import TrayHealthMonitor

    tray = make_tray([remote])
    tray._health = TrayHealthMonitor(tray)
    tray._multi_client = None
    with (
        mock.patch("subprocess.run") as run,
        mock.patch("ai_guardian.tray.plugins.send_notification") as notify,
    ):
        tray._health._check_pip_available_for_target(remote)
        tray._health._do_upgrade_daemon(remote)
    run.assert_not_called()
    assert not tray._health._pip_available[(remote.name, "ssh")]
    assert "no workstation upgrade was run" in notify.call_args.args[1]


def test_ssh_upgrade_reports_unconfirmed_restart_without_clearing_version_warning(
    remote,
):
    from ai_guardian.tray.health import TrayHealthMonitor

    tray = make_tray([remote])
    tray._health = TrayHealthMonitor(tray)
    key = (remote.name, "ssh")
    tray._health._version_mismatch_notified.add(key)
    tray._multi_client.run_pip_upgrade.return_value = (True, "updated")
    tray._multi_client.send_restart.return_value = False
    with mock.patch("ai_guardian.tray.plugins.send_notification") as notify:
        tray._health._do_upgrade_daemon(remote)
    assert "restart was not confirmed" in notify.call_args.args[1]
    assert key in tray._health._version_mismatch_notified
    assert key not in tray._health._upgrade_in_progress


def test_offline_vm_keeps_terminal_start_management_and_explicit_status(remote):
    remote.status = "offline"
    remote.stats = None
    remote.error_message = "SSH daemon offline; reconnecting with backoff."
    tray = make_tray([remote])
    menu = build(tray)
    assert find(menu, "Terminal").enabled
    assert find(menu, "Start daemon")
    assert find(menu, "Manage SSH connection...")
    assert not find(menu, "Console").enabled
    assert "Offline" in tray._menu._daemon_status_details(remote)[1]
    assert "backoff" in tray._menu._daemon_status_details(remote)[3]


def test_vm_directory_label_never_shortens_against_workstation_home(remote):
    remote.working_dir = "/workstation/home/project"
    tray = make_tray([remote])
    with mock.patch(
        "ai_guardian.daemon.working_dir.shorten_path", return_value="~/project"
    ) as shorten:
        assert (
            tray._menu._working_dir_menu_label(remote)
            == "Working Dir: /workstation/home/project"
        )
    shorten.assert_not_called()


def test_local_first_then_alphabetical_across_remote_transports():
    from ai_guardian.tray.app import DaemonTray

    targets = [
        DaemonTarget("Zulu", "ssh"),
        DaemonTarget("beta", "container"),
        DaemonTarget("workstation", "local"),
        DaemonTarget("Alpha", "manual"),
        DaemonTarget("delta", "kubernetes"),
    ]
    assert [t.name for t in DaemonTray._sort_targets(targets)] == [
        "workstation",
        "Alpha",
        "beta",
        "delta",
        "Zulu",
    ]
    assert targets[0].name == "Zulu"  # discovery's list is not mutated
    assert [t.name for t in DaemonTray._sort_targets(reversed(targets))] == [
        "workstation",
        "Alpha",
        "beta",
        "delta",
        "Zulu",
    ]


def test_container_action_cannot_retarget_vm_when_sort_order_changes(remote):
    container = DaemonTarget(
        "Zulu", "container", status="running", container_id="container-z"
    )
    tray = make_tray([container, remote])
    menu = visible(build(tray))[0].submenu
    tray._targets.reverse()
    find(menu, "Terminal").action(None, None)
    tray._multi_client.open_shell.assert_called_once_with(container)


def test_discovery_sorts_before_plugin_binding_and_preserves_selection(remote):
    remote.name = "Zulu"
    tray = make_tray([remote])
    tray._active_target = remote
    tray._status = "running"
    tray._anim = mock.Mock()
    tray._discovery = mock.Mock(stopped_container_targets=[])
    tray._menu._apply_working_dirs = mock.Mock()
    tray._plugins._poll_plugins = mock.Mock()
    tray._register_tray_with_remotes = mock.Mock()
    tray._catchup_remote_traces = mock.Mock()
    targets = [
        remote,
        DaemonTarget("alpha", "container"),
        DaemonTarget("workstation", "local"),
    ]
    tray._on_targets_updated(targets)
    assert [t.name for t in tray._targets] == ["workstation", "alpha", "Zulu"]
    assert tray._active_target is remote
    tray._plugins._poll_plugins.assert_called_once()


def test_same_count_reorder_rebuilds_descriptors_after_popup_closes(remote):
    tray = make_tray([DaemonTarget("local", "local"), remote])
    tray._menu_target_snapshot = tray._target_menu_identity()
    tray._menu_target_count = 2
    tray._menu_stopped_container_count = 0
    tray._menu_stopped_container_snapshot = ()
    tray._stopped_container_targets = []
    tray._icon = mock.Mock()
    tray._appindicator_menu_open = True
    tray._build_tray_menu = mock.Mock(return_value="replacement-menu")
    tray._schedule_appindicator_menu_watch = mock.Mock()
    tray._targets.reverse()
    # Use the actual implementation, not the fixture's dispatch stub.
    from ai_guardian.tray.app import DaemonTray

    DaemonTray._refresh_menu(tray)
    tray._build_tray_menu.assert_not_called()
    assert tray._menu_refresh_pending
    tray._appindicator_menu_open = False
    DaemonTray._refresh_menu(tray)
    tray._build_tray_menu.assert_called_once()
    assert tray._icon.menu == "replacement-menu"


def test_remote_counter_and_mcp_changes_trigger_native_menu_refresh(remote):
    tray = make_tray([remote])
    tray._status = "running"
    tray._stopped_container_targets = []
    before = tray._build_stats_snapshot()
    assert before is not None
    remote.stats = {**remote.stats, "request_count": 43}
    after = tray._build_stats_snapshot()
    assert after != before
    remote.stats["mcp_proactive_level"] = "low"
    assert tray._build_stats_snapshot() != after


@pytest.mark.parametrize(
    "config,expected",
    [
        ({}, "low"),
        ({"mcp_server": {"proactive_level": "high"}}, "high"),
        ({"mcp_server": None}, "low"),
    ],
)
def test_daemon_publishes_its_own_mcp_menu_state(tmp_path, config, expected):
    from ai_guardian.daemon.state import DaemonState

    state = DaemonState(
        config_path=tmp_path / "config.json",
        sessions_file=tmp_path / "sessions.json",
        pause_file=tmp_path / "paused",
    )
    state._config = config
    state._mcp_installed = True
    stats = state.get_stats()
    assert stats["mcp_installed"] is True
    assert stats["mcp_proactive_level"] == expected
    assert stats["mcp_enabled"] is True
