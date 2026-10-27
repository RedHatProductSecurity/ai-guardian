"""SSH maintenance uses the paired destination and the daemon's interpreter."""

import shlex
import threading
from pathlib import PurePosixPath, PureWindowsPath
from unittest import mock

import pytest

from ai_guardian.daemon.ssh_storage import SSHConnectionError
from tests.fixtures.ssh_daemon import make_pairing


@pytest.fixture
def commands(tmp_path):
    from ai_guardian.daemon.ssh_commands import SSHCommands

    pairing = make_pairing(tmp_path)[0]
    store = mock.Mock()
    store.contains.return_value = True
    return SSHCommands(
        pairing.profile,
        store,
        threading.Event(),
        {
            "python": "/home/test/custom venv/bin/python",
            "config_dir": "/home/test/config",
            "state_dir": "/home/test/state",
        },
    )


def test_cli_uses_remote_virtualenv_and_context_not_local_python(commands):
    with mock.patch("shutil.which", return_value="/usr/bin/ssh"):
        argv = commands.command(["ai-guardian", "daemon", "restart"])
    assert argv[-2] == commands.profile.destination
    remote = shlex.split(argv[-1])
    assert remote[0] == "PATH=/home/test/custom venv/bin:$PATH"
    assert remote[1] == "env"
    assert "AI_GUARDIAN_CONFIG_DIR=/home/test/config" in remote
    assert "AI_GUARDIAN_STATE_DIR=/home/test/state" in remote
    assert remote[-5:] == [
        "/home/test/custom venv/bin/python",
        "-m",
        "ai_guardian",
        "daemon",
        "restart",
    ]
    assert "StrictHostKeyChecking=yes" in argv
    assert "ForwardAgent=no" in argv
    assert commands.profile.token not in str(argv)


def test_shell_available_without_cli_metadata_and_forces_remote_tty(commands):
    commands.cli = None
    with mock.patch("shutil.which", return_value="ssh"):
        argv = commands.command(interactive=True)
    assert "-tt" in argv
    assert "-T" not in argv
    assert argv[-2] == commands.profile.destination
    assert '"${SHELL:-/bin/sh}"' in argv[-1]
    with pytest.raises(SSHConnectionError, match="installation context"):
        commands.command(["ai-guardian", "doctor"])


@pytest.mark.parametrize("saved", [None, "", "/vm/explicit project"])
@pytest.mark.parametrize(
    "workstation_home",
    [PurePosixPath("/workstation/home"), PureWindowsPath("C:/Users/workstation")],
    ids=["posix-home", "windows-home"],
)
def test_discovery_never_uses_workstation_home_as_ssh_working_directory(
    tmp_path, commands, saved, workstation_home
):
    import json

    from ai_guardian.daemon.discovery import DaemonTarget
    from ai_guardian.daemon.multi_client import MultiDaemonClient
    from tests.fixtures.ssh_tray import make_tray

    target = DaemonTarget(
        "ssh-vm", "ssh", ssh_commands=commands, working_dir=str(workstation_home)
    )
    local = DaemonTarget("local", "local")
    if saved is not None:
        (tmp_path / "working_dir.json").write_text(json.dumps({target.name: saved}))
    tray = make_tray([local, target])
    with (
        mock.patch(
            "ai_guardian.daemon.working_dir.get_state_dir", return_value=tmp_path
        ),
        mock.patch("pathlib.Path.home", return_value=workstation_home),
    ):
        tray._menu._apply_working_dirs()
        tray._menu._apply_working_dirs()  # repeated discovery must preserve remote home
    assert local.working_dir == str(workstation_home)
    assert target.working_dir == (saved or None)
    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch(
            "ai_guardian.daemon.multi_client._launch_in_terminal", return_value=True
        ) as launch,
    ):
        assert MultiDaemonClient().open_shell(target)
    command = launch.call_args.args[0][-1]
    assert str(workstation_home) not in command
    assert workstation_home.as_posix() not in command
    assert ("cd " in command) is bool(saved)
    if saved:
        assert shlex.quote(saved) in command


@pytest.mark.parametrize("removed", [False, True])
def test_removed_or_invalidated_connection_never_launches(commands, removed):
    if removed:
        commands.store.contains.return_value = False
    else:
        commands.cancelled.set()
    with mock.patch("subprocess.run") as run:
        with pytest.raises(SSHConnectionError):
            commands.run(["ai-guardian", "daemon", "stop"])
    run.assert_not_called()


def test_execution_reports_nonzero_status_and_timeout_without_local_fallback(commands):
    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch(
            "subprocess.run",
            return_value=mock.Mock(returncode=2, stdout="", stderr="failed"),
        ) as run,
    ):
        success, output = commands.run(["ai-guardian", "doctor"])
    assert not success
    assert output == "failed"
    assert run.call_args.args[0][0] == "ssh"


@pytest.mark.parametrize(
    "value", [{}, {"python": "python3"}, {"python": "/bin/python\nno"}]
)
def test_invalid_cli_context_is_not_executable(commands, value):
    from ai_guardian.daemon.ssh_commands import validate_cli_context

    assert validate_cli_context(value) is None


@pytest.mark.parametrize(
    "method,verb", [("send_stop", "stop"), ("send_restart", "restart")]
)
def test_lifecycle_routes_through_paired_ssh_context(commands, method, verb):
    from ai_guardian.daemon.discovery import DaemonTarget
    from ai_guardian.daemon.multi_client import MultiDaemonClient

    target = DaemonTarget("ssh-vm", "ssh", ssh_commands=commands)
    with mock.patch.object(commands, "run", return_value=(True, "done")) as run:
        assert getattr(MultiDaemonClient(), method)(target)
    run.assert_called_once_with(
        ["ai-guardian", "daemon", verb], timeout=60, python=False
    )


def test_pip_and_terminal_use_remote_python_and_destination(commands):
    from ai_guardian.daemon.discovery import DaemonTarget
    from ai_guardian.daemon.multi_client import MultiDaemonClient

    target = DaemonTarget(
        "ssh-vm", "ssh", ssh_commands=commands, working_dir="/remote/project"
    )
    client = MultiDaemonClient()
    with mock.patch.object(commands, "run", return_value=(True, "done")) as run:
        assert client.check_pip_available(target)
        run.assert_called_with(["-m", "pip", "--version"], timeout=10, python=True)
        assert client.run_pip_upgrade(target, "1.21.0") == (True, "done")
        run.assert_called_with(
            ["-m", "pip", "install", "ai-guardian==1.21.0"], timeout=120, python=True
        )
    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch(
            "ai_guardian.daemon.multi_client._launch_in_terminal", return_value=True
        ) as terminal,
    ):
        assert client.open_shell(target)
        argv = terminal.call_args.args[0]
        assert argv[-2] == commands.profile.destination
        assert "cd /remote/project" in argv[-1]
        assert terminal.call_args.kwargs["keep_open"] is True
        assert client.open_doctor(target)
        assert "/home/test/custom venv/bin/python" in terminal.call_args.args[0][-1]
        assert "doctor" in terminal.call_args.args[0][-1]


def test_old_daemon_cannot_silently_run_cli_on_workstation():
    from ai_guardian.daemon.discovery import DaemonTarget
    from ai_guardian.daemon.multi_client import MultiDaemonClient

    target = DaemonTarget("old-vm", "ssh")
    with mock.patch("subprocess.run") as run:
        assert not MultiDaemonClient().send_restart(target)
        assert not MultiDaemonClient().check_pip_available(target)
    run.assert_not_called()
    assert "installation context" in target.error_message


def test_timeout_is_not_success_and_has_no_local_retry(commands):
    import subprocess

    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 1)
        ) as run,
    ):
        success, message = commands.run(["ai-guardian", "doctor"], timeout=1)
    assert not success
    assert "timed out" in message
    run.assert_called_once()


@pytest.mark.parametrize(
    "result", [None, {}, {"error": "unsupported"}, {"status": "error"}]
)
def test_ssh_pause_requires_real_acknowledgement(result):
    from ai_guardian.daemon.discovery import DaemonTarget
    from ai_guardian.daemon.multi_client import MultiDaemonClient

    with mock.patch.object(MultiDaemonClient, "_rest_request", return_value=result):
        assert not MultiDaemonClient().send_pause(DaemonTarget("vm", "ssh"), 5)


@pytest.mark.parametrize("authenticated", [False, True])
def test_cli_context_published_only_after_remote_identity_and_authentication(
    tmp_path, commands, authenticated
):
    from dataclasses import replace
    from ai_guardian.daemon.ssh_connections import SSHConnectionManager

    pairing = replace(make_pairing(tmp_path)[0], cli=dict(commands.cli))
    store = mock.Mock()
    store.load.return_value = [pairing.profile]
    manager = SSHConnectionManager(store)
    with mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread"):
        target = manager.refresh()[0]
    connection = manager._connections[pairing.profile.id]
    tunnel = mock.Mock()
    if authenticated:
        tunnel.request.return_value = {"paused": False}
    else:
        tunnel.request.side_effect = SSHConnectionError("Authentication failed")

    def stop(_delay):
        connection.stop.set()
        return True

    with (
        mock.patch.object(manager, "prepare", return_value=pairing),
        mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel", return_value=tunnel),
        mock.patch.object(connection.stop, "wait", side_effect=stop),
    ):
        manager._run(connection)
    assert target.ssh_commands.cli == (commands.cli if authenticated else None)
    manager.close()


def test_pid_metadata_preserves_actual_virtualenv_without_credentials(tmp_path):
    import json
    from types import SimpleNamespace
    from ai_guardian.daemon.server import DaemonServer

    daemon = DaemonServer.__new__(DaemonServer)
    daemon._rest_port = 45231
    daemon._enable_rest_api = True
    daemon._rest_error = None
    daemon._use_tcp = False
    daemon.state = SimpleNamespace(_source_mtime=0)
    pid = tmp_path / "daemon.pid"
    with (
        mock.patch("ai_guardian.daemon.server.get_pid_path", return_value=pid),
        mock.patch(
            "ai_guardian.daemon.get_executable_command",
            return_value=["/vm/actual venv/bin/python", "-m", "ai_guardian"],
        ),
        mock.patch(
            "ai_guardian.config.utils.get_config_dir", return_value=tmp_path / "config"
        ),
        mock.patch(
            "ai_guardian.config.utils.get_state_dir", return_value=tmp_path / "state"
        ),
    ):
        daemon._write_pid_file()
    context = json.loads(pid.read_text())["cli"]
    assert context["python"] == "/vm/actual venv/bin/python"
    assert context["config_dir"] == str(tmp_path / "config")
    assert context["state_dir"] == str(tmp_path / "state")
    assert not {"token", "auth_token", "certificate", "ca_pem"}.intersection(context)
