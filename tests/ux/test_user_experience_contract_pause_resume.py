"""User experience contracts for tray-independent pause/resume commands (#2427)."""

import sys
from unittest import mock

import pytest

from ai_guardian.cli import main
from ai_guardian.tools.policy import ToolPolicyChecker


@pytest.fixture(autouse=True)
def isolated_cli_config():
    with mock.patch(
        "ai_guardian.cli_handlers._load_config_file", return_value=({}, None)
    ):
        yield


def _run_command(argv, response_data):
    sock = mock.MagicMock()
    with (
        mock.patch.object(sys, "argv", argv),
        mock.patch("ai_guardian.cli._ensure_daemon_started") as auto_start,
        mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True),
        mock.patch("ai_guardian.daemon.client._connect", return_value=sock),
        mock.patch(
            "ai_guardian.daemon.protocol.encode_message", return_value=b"request"
        ),
        mock.patch(
            "ai_guardian.daemon.protocol.decode_message",
            return_value={"type": "response", "data": response_data},
        ),
    ):
        result = main()

    auto_start.assert_not_called()
    sock.close.assert_called_once_with()
    return result


def test_pause_command_controls_existing_daemon_without_tray(capsys):
    """
    USER EXPERIENCE: Tray unavailable -> top-level pause controls the daemon.

    Scenario:
    1. The user runs ``ai-guardian pause 15`` on a headless host.
    2. The existing daemon is reachable through its local socket.
    3. No system tray process is involved and no new daemon is started.

    Expected User Experience:
    - The daemon pauses global scanning for 15 minutes.
    - The user sees a clear success message on stdout.
    """
    result = _run_command(
        ["ai-guardian", "pause", "15"], {"status": "paused", "minutes": 15}
    )

    assert result == 0
    assert (
        capsys.readouterr().out
        == "ai-guardian daemon: scanning paused for 15 minutes\n"
    )


def test_resume_command_controls_existing_daemon_without_tray(capsys):
    """
    USER EXPERIENCE: Tray unavailable -> top-level resume restores scanning.

    Expected User Experience:
    - The existing daemon resumes global scanning.
    - The user sees a clear success message on stdout.
    """
    result = _run_command(["ai-guardian", "resume"], {"status": "resumed"})

    assert result == 0
    assert capsys.readouterr().out == "ai-guardian daemon: scanning resumed\n"


@pytest.mark.parametrize("command", ["pause", "resume"])
@pytest.mark.parametrize(
    "selector", [[], ["--dir", "project"], ["--session", "Adapter:session-1"]]
)
def test_pause_resume_command_reports_unreachable_daemon(
    command, selector, tmp_path, monkeypatch, capsys
):
    """
    USER EXPERIENCE: Daemon unavailable -> fail clearly without auto-starting.

    The command must not silently launch a daemon or pretend that scanning was
    paused when the existing daemon cannot be reached.
    """
    state_dir = tmp_path / "offline-state"
    state_dir.mkdir()
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(state_dir))
    with (
        mock.patch.object(sys, "argv", ["ai-guardian", command, *selector]),
        mock.patch("ai_guardian.cli._ensure_daemon_started") as auto_start,
        mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=False),
        mock.patch("ai_guardian.daemon.client.start_daemon_background") as start,
        mock.patch("ai_guardian.daemon.client._connect") as connect,
    ):
        result = main()

    auto_start.assert_not_called()
    start.assert_not_called()
    connect.assert_not_called()
    assert list(state_dir.iterdir()) == []
    assert result == 1
    assert capsys.readouterr().err == "ai-guardian daemon is not running\n"


@pytest.mark.parametrize("command", ["pause", "resume"])
@pytest.mark.parametrize("scope", ["--dir", "--session"])
def test_empty_scope_is_a_usage_error_not_a_global_operation(command, scope, capsys):
    """
    USER EXPERIENCE: Empty explicit selector -> usage error, never global control.

    Manual verification: Run either command with ``--dir ''`` or ``--session ''``
    in a human terminal; expect exit status 2 and no pause-state change.
    """
    with (
        mock.patch.object(sys, "argv", ["ai-guardian", command, scope, ""]),
        mock.patch("ai_guardian.cli._handle_daemon_command") as handler,
        mock.patch("ai_guardian.cli._ensure_daemon_started") as auto_start,
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 2
    assert (
        f"argument {scope}: scope selector must not be empty" in capsys.readouterr().err
    )
    handler.assert_not_called()
    auto_start.assert_not_called()


@pytest.mark.parametrize("command", ["pause", "resume"])
@pytest.mark.parametrize("scope", ["--dir", "--session"])
def test_ai_cannot_execute_scoped_protection_controls(command, scope):
    """
    USER EXPERIENCE: AI tries a scoped protection command -> immutable denial.

    Scoped forms are human-operated controls, not a new agent or MCP capability.
    """
    checker = ToolPolicyChecker(config={"permissions": []})
    allowed, reason, _ = checker.check_tool_allowed(
        {
            "hook_event_name": "PreToolUse",
            "tool_use": {
                "name": "Bash",
                "input": {"command": f"ai-guardian {command} {scope} project-or-key"},
            },
        }
    )
    assert not allowed
    assert reason
