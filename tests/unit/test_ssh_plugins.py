"""VM commands and workstation UI must never share an execution fallback."""

import threading
from unittest import mock

import pytest

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.daemon.ssh_commands import SSHCommands
from ai_guardian.tray import plugins
from tests.fixtures.ssh_daemon import make_pairing
from tests.fixtures.ssh_tray import build, find, make_tray, visible


@pytest.fixture
def target(tmp_path):
    profile = make_pairing(tmp_path)[0].profile
    store = mock.Mock()
    store.contains.return_value = True
    commands = SSHCommands(
        profile,
        store,
        threading.Event(),
        {
            "python": "/vm/venv/bin/python",
            "config_dir": "/vm/config",
            "state_dir": "/vm/state",
            "system": "linux",
        },
    )
    return DaemonTarget(
        "ssh-vm", "ssh", status="running", ssh_commands=commands, stats={}
    )


@pytest.mark.parametrize(
    "item_type", ["terminal", "notification", "modal", "clipboard", "background"]
)
@pytest.mark.parametrize("explicit", [False, True])
def test_maintenance_cli_is_always_remote_even_for_old_plugin_bundles(
    target, item_type, explicit
):
    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch(
            "subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="done", stderr=""),
        ) as run,
        mock.patch(
            "ai_guardian.daemon.multi_client._launch_in_terminal", return_value=True
        ) as terminal,
        mock.patch.object(plugins, "send_notification"),
        mock.patch.object(plugins, "show_dialog"),
        mock.patch.object(plugins, "copy_to_clipboard"),
    ):
        plugins.execute_plugin_command(
            "ai-guardian daemon reload",
            item_type,
            target=target,
            run_on_target=explicit,
        )
    argv = (
        terminal.call_args.args[0] if item_type == "terminal" else run.call_args.args[0]
    )
    assert argv[0] == "ssh"
    assert argv[-2] == target.ssh_commands.profile.destination
    assert "/vm/venv/bin/python -m ai_guardian daemon reload" in argv[-1]
    assert target.ssh_commands.profile.token not in str(argv)


def test_compound_cli_remains_remote_and_uses_remote_virtualenv(target):
    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch(
            "subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="done", stderr=""),
        ) as run,
        mock.patch.object(plugins, "send_notification"),
    ):
        plugins.execute_plugin_command(
            "ai-guardian --version && ai-guardian doctor",
            "notification",
            target=target,
            run_on_target=True,
        )
    argv = run.call_args.args[0]
    assert argv[0] == "ssh"
    assert "PATH=/vm/venv/bin" in argv[-1]
    assert "sh -c" in argv[-1]


@pytest.mark.parametrize("missing", [False, True])
def test_invalidated_or_missing_context_never_falls_back_locally(target, missing):
    if missing:
        target.ssh_commands.cli = None
    else:
        target.ssh_commands.cancelled.set()
    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch("subprocess.run") as run,
        mock.patch.object(plugins, "show_dialog") as dialog,
    ):
        plugins.execute_plugin_command(
            "ai-guardian daemon stop", "notification", target=target
        )
    run.assert_not_called()
    dialog.assert_called_once()


def test_workstation_command_from_remote_definition_is_explicitly_unavailable(target):
    with (
        mock.patch("subprocess.run") as run,
        mock.patch.object(plugins, "show_dialog") as dialog,
    ):
        plugins.execute_plugin_command(
            "echo workstation", "notification", target=target
        )
    run.assert_not_called()
    assert "Workstation command plugins are unavailable" in dialog.call_args.args[1]


def test_bundled_doctor_opens_workstation_console_for_vm_without_shell(target):
    with (
        mock.patch("subprocess.run") as run,
        mock.patch(
            "ai_guardian.tray.menu.open_web_console", return_value=True
        ) as console,
    ):
        plugins.execute_plugin_command(
            "xdg-open http://127.0.0.1:$(cat ~/.local/state/ai-guardian/web-console.port)/{name}/health-check",
            "background",
            target=target,
        )
    console.assert_called_once_with(target.name, "health-check")
    run.assert_not_called()


def test_remote_platform_commands_do_not_use_desktop_platform(target):
    command = {"darwin": "desktop", "linux": "vm"}
    with mock.patch("platform.system", return_value="Darwin"):
        assert plugins.resolve_target_command(command, target, True) == "vm"
        assert plugins.resolve_target_command(command, target, False) == "desktop"


def test_plugin_action_keeps_presented_item_and_target_after_refresh(target):
    tray = make_tray([target])
    maintenance = find(build(tray), "Maintenance")
    stop = find(maintenance.submenu, "Stop Daemon")  # capture rendered definition
    tray._plugins._ssh_plugins[id(target)] = (target, [])
    with (
        mock.patch("ai_guardian.tray.ssh_connections.threading.Thread") as thread,
        mock.patch(
            "ai_guardian.tray.dialog_placement._get_tray_screen_bounds",
            return_value=None,
        ),
        mock.patch.object(plugins, "execute_plugin_command") as execute,
    ):
        stop.action(None, None)
        execute.assert_not_called()
        thread.call_args.kwargs["target"]()
    assert execute.call_args.args[:2] == ("ai-guardian daemon stop", "notification")
    assert execute.call_args.kwargs["target"].ssh_commands is target.ssh_commands


def test_offline_plugins_use_background_loaded_defaults_not_workstation_config(target):
    target.status = "offline"
    tray = make_tray([target])
    tray._plugins._ssh_plugins.clear()
    tray._plugins._poll_plugins()
    tray._multi_client.get_plugins.assert_not_called()
    assert find(build(tray), "Maintenance")


def test_remote_global_plugins_cannot_become_unscoped_workstation_actions(target):
    tray = make_tray([target])
    tray._multi_client.get_plugins.return_value = {
        "plugins": [
            {
                "id": "remote-global",
                "name": "Remote global",
                "scope": "global",
                "items": [{"label": "Run", "command": "echo no"}],
            }
        ]
    }
    tray._plugins._poll_plugins()
    assert tray._plugins._global_plugins == []
