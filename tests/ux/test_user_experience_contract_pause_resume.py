"""User experience contracts for tray-independent pause/resume commands (#2427)."""

import sys
from unittest import mock

from ai_guardian.cli import main


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


def test_pause_command_reports_unreachable_daemon(capsys):
    """
    USER EXPERIENCE: Daemon unavailable -> fail clearly without auto-starting.

    The command must not silently launch a daemon or pretend that scanning was
    paused when the existing daemon cannot be reached.
    """
    with (
        mock.patch.object(sys, "argv", ["ai-guardian", "pause"]),
        mock.patch("ai_guardian.cli._ensure_daemon_started") as auto_start,
        mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=False),
    ):
        result = main()

    auto_start.assert_not_called()
    assert result == 1
    assert capsys.readouterr().err == "ai-guardian daemon is not running\n"
