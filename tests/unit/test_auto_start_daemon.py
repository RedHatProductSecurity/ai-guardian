"""Tests for daemon auto-start on CLI commands (Issue #680, #775)."""

import sys
import time
from unittest import mock

import pytest

from ai_guardian.cli import _ensure_daemon_started, _is_stop_requested


class TestEnsureDaemonStarted:
    def test_starts_when_not_running(self):
        with (
            mock.patch("ai_guardian.cli._is_stop_requested", return_value=False),
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=False
            ),
            mock.patch(
                "ai_guardian.daemon.client.start_daemon_background"
            ) as mock_start,
        ):
            _ensure_daemon_started()

        mock_start.assert_called_once()

    def test_skips_when_already_running(self):
        with (
            mock.patch("ai_guardian.cli._is_stop_requested", return_value=False),
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                "ai_guardian.daemon.client.start_daemon_background"
            ) as mock_start,
        ):
            _ensure_daemon_started()

        mock_start.assert_not_called()

    def test_silences_runtime_errors(self):
        with (
            mock.patch("ai_guardian.cli._is_stop_requested", return_value=False),
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running",
                side_effect=RuntimeError("fail"),
            ),
        ):
            _ensure_daemon_started()

    def test_skips_when_stop_requested(self):
        """Issue #775: auto-start skipped when daemon was recently stopped."""
        with (
            mock.patch("ai_guardian.cli._is_stop_requested", return_value=True),
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=False
            ) as mock_check,
            mock.patch(
                "ai_guardian.daemon.client.start_daemon_background"
            ) as mock_start,
        ):
            _ensure_daemon_started()

        mock_check.assert_not_called()
        mock_start.assert_not_called()


class TestIsStopRequested:
    """Issue #775: stop-requested marker prevents auto-start after explicit stop."""

    def test_no_marker_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ai_guardian.daemon.get_state_dir", lambda: tmp_path)
        assert _is_stop_requested() is False

    def test_recent_marker_returns_true(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ai_guardian.daemon.get_state_dir", lambda: tmp_path)
        marker = tmp_path / "daemon.stop-requested"
        marker.touch()
        assert _is_stop_requested() is True

    def test_marker_persists_until_cleared(self, tmp_path, monkeypatch):
        """Marker persists indefinitely — cleared only by daemon start."""
        monkeypatch.setattr("ai_guardian.daemon.get_state_dir", lambda: tmp_path)
        marker = tmp_path / "daemon.stop-requested"
        marker.touch()
        # Backdate the marker — should still block auto-start
        old_time = time.time() - 600
        import os

        os.utime(marker, (old_time, old_time))
        assert _is_stop_requested() is True


class TestDaemonCommandsNoAutoStart:
    """Issue #775: daemon status and daemon stop must not auto-start the daemon."""

    def _run_main_with_args(self, argv, mock_ensure):
        """Run main() with given sys.argv and a mocked _ensure_daemon_started."""
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch("ai_guardian.cli._ensure_daemon_started", mock_ensure),
            mock.patch("ai_guardian.cli._handle_daemon_command", return_value=0),
        ):
            from ai_guardian.cli import main

            main()

    def test_daemon_status_no_autostart(self):
        mock_ensure = mock.MagicMock()
        self._run_main_with_args(["ai-guardian", "daemon", "status"], mock_ensure)
        mock_ensure.assert_not_called()

    def test_daemon_stop_no_autostart(self):
        mock_ensure = mock.MagicMock()
        self._run_main_with_args(["ai-guardian", "daemon", "stop"], mock_ensure)
        mock_ensure.assert_not_called()

    def test_daemon_start_no_autostart(self):
        mock_ensure = mock.MagicMock()
        self._run_main_with_args(["ai-guardian", "daemon", "start"], mock_ensure)
        mock_ensure.assert_not_called()

    def test_daemon_restart_no_autostart(self):
        mock_ensure = mock.MagicMock()
        self._run_main_with_args(["ai-guardian", "daemon", "restart"], mock_ensure)
        mock_ensure.assert_not_called()

    @pytest.mark.parametrize(
        "argv, command, minutes",
        [
            (["ai-guardian", "pause"], "pause", 0),
            (["ai-guardian", "pause", "15"], "pause", 15),
            (["ai-guardian", "resume"], "resume", None),
        ],
    )
    def test_top_level_pause_resume_dispatch_without_autostart(
        self, argv, command, minutes
    ):
        mock_ensure = mock.MagicMock()
        handler = mock.MagicMock(return_value=0)

        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch("ai_guardian.cli._ensure_daemon_started", mock_ensure),
            mock.patch("ai_guardian.cli._handle_daemon_command", handler),
        ):
            from ai_guardian.cli import main

            assert main() == 0

        mock_ensure.assert_not_called()
        args = handler.call_args.args[0]
        assert args.daemon_command == command
        if minutes is not None:
            assert args.minutes == minutes

    @pytest.mark.parametrize("minutes", ["-1", "1441", "not-an-integer"])
    def test_top_level_pause_rejects_invalid_duration(self, minutes):
        with (
            mock.patch.object(sys, "argv", ["ai-guardian", "pause", minutes]),
            mock.patch("ai_guardian.cli._ensure_daemon_started") as mock_ensure,
        ):
            from ai_guardian.cli import main

            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2
        mock_ensure.assert_not_called()

    def test_nested_pause_options_remain_supported(self):
        handler = mock.MagicMock(return_value=0)
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "ai-guardian",
                    "daemon",
                    "pause",
                    "--dir",
                    "/tmp/project",
                    "--minutes",
                    "5",
                ],
            ),
            mock.patch("ai_guardian.cli._handle_daemon_command", handler),
        ):
            from ai_guardian.cli import main

            assert main() == 0

        args = handler.call_args.args[0]
        assert args.daemon_command == "pause"
        assert args.dir == "/tmp/project"
        assert args.minutes == 5

    @pytest.mark.parametrize("nested", [False, True])
    @pytest.mark.parametrize(
        "scope, value",
        [
            (None, None),
            ("--dir", "./project with spaces"),
            ("--session", "ClaudeCodeAdapter:session-1"),
        ],
    )
    @pytest.mark.parametrize(
        "command, minutes",
        [
            ("pause", None),
            ("pause", 0),
            ("pause", 15),
            ("pause", 1440),
            ("resume", None),
        ],
    )
    def test_pause_resume_scopes_dispatch_without_autostart(
        self, nested, scope, value, command, minutes
    ):
        argv = ["ai-guardian", "daemon"] if nested else ["ai-guardian"]
        argv.append(command)
        if minutes is not None:
            argv.extend(["--minutes", str(minutes)] if nested else [str(minutes)])
        if scope:
            argv.extend([scope, value])

        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch("ai_guardian.cli._ensure_daemon_started") as auto_start,
            mock.patch(
                "ai_guardian.cli._handle_daemon_command", return_value=0
            ) as handler,
        ):
            from ai_guardian.cli import main

            assert main() == 0

        auto_start.assert_not_called()
        handler.assert_called_once()
        args = handler.call_args.args[0]
        assert args.daemon_command == command
        assert args.dir == (value if scope == "--dir" else None)
        assert args.session == (value if scope == "--session" else None)
        if command == "pause":
            assert args.minutes == (minutes or 0)

    @pytest.mark.parametrize("nested", [False, True])
    @pytest.mark.parametrize("command", ["pause", "resume"])
    @pytest.mark.parametrize(
        "selectors",
        [
            ["--dir", "project", "--session", "Adapter:session"],
            ["--dir"],
            ["--session"],
            ["--dir", ""],
            ["--session", ""],
            ["--dir", " \t"],
            ["--session", " \t"],
        ],
    )
    def test_pause_resume_scopes_reject_invalid_selectors(
        self, nested, command, selectors
    ):
        argv = ["ai-guardian", "daemon"] if nested else ["ai-guardian"]
        with (
            mock.patch.object(sys, "argv", [*argv, command, *selectors]),
            mock.patch("ai_guardian.cli._ensure_daemon_started") as auto_start,
            mock.patch("ai_guardian.cli._handle_daemon_command") as handler,
        ):
            from ai_guardian.cli import main

            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2
        handler.assert_not_called()
        auto_start.assert_not_called()

    @pytest.mark.parametrize("scope", ["--dir", "--session"])
    @pytest.mark.parametrize("minutes", ["-1", "1441", "1.5", "not-an-integer"])
    def test_scoped_top_level_pause_rejects_invalid_duration(
        self, scope, minutes, capsys
    ):
        with (
            mock.patch.object(
                sys, "argv", ["ai-guardian", "pause", minutes, scope, "project-or-key"]
            ),
            mock.patch("ai_guardian.cli._ensure_daemon_started") as auto_start,
            mock.patch("ai_guardian.cli._handle_daemon_command") as handler,
        ):
            from ai_guardian.cli import main

            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2
        handler.assert_not_called()
        auto_start.assert_not_called()
        message = (
            "pause duration must be between 0 and 1440 minutes"
            if minutes in ("-1", "1441")
            else "pause duration must be an integer"
        )
        assert message in capsys.readouterr().err

    @pytest.mark.parametrize("nested", [False, True])
    @pytest.mark.parametrize("command", ["pause", "resume"])
    def test_pause_resume_scope_help(self, nested, command, capsys):
        argv = ["ai-guardian", "daemon"] if nested else ["ai-guardian"]
        with (
            mock.patch.object(sys, "argv", [*argv, command, "--help"]),
            mock.patch("ai_guardian.cli._ensure_daemon_started") as auto_start,
            mock.patch("ai_guardian.cli._handle_daemon_command") as handler,
        ):
            from ai_guardian.cli import main

            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        output = " ".join(capsys.readouterr().out.split())
        assert "--dir DIRECTORY | --session SESSION_KEY" in output
        assert "all sessions using this project directory" in output
        assert "ai-guardian daemon status" in output
        assert "Without a selector" in output
        assert "global" in output
        assert "callers without stable hook identities" in output
        handler.assert_not_called()
        auto_start.assert_not_called()

    def test_other_commands_do_autostart(self):
        mock_ensure = mock.MagicMock()
        with (
            mock.patch.object(sys, "argv", ["ai-guardian", "doctor"]),
            mock.patch("ai_guardian.cli._ensure_daemon_started", mock_ensure),
            mock.patch("ai_guardian.doctor.doctor_command", return_value=0),
        ):
            from ai_guardian.cli import main

            main()
        mock_ensure.assert_called_once()
