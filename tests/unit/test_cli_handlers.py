"""Tests for ai_guardian.cli_handlers module."""

import json
import os
from unittest import mock

import pytest

from ai_guardian.cli_handlers import (
    _get_daemon_mode,
    _get_client_timeout,
    _set_daemon_mode_in_config,
    _handle_daemon_command,
)


class TestGetDaemonMode:
    def test_always_returns_auto(self):
        assert _get_daemon_mode() == "auto"


class TestGetClientTimeout:
    def test_default(self):
        with mock.patch(
            "ai_guardian.cli_handlers._load_config_file", return_value=(None, None)
        ):
            assert _get_client_timeout() == 2.0

    def test_reads_from_config(self):
        config = {"daemon": {"client_timeout_seconds": 5.0}}
        with mock.patch(
            "ai_guardian.cli_handlers._load_config_file", return_value=(config, None)
        ):
            assert _get_client_timeout() == 5.0

    def test_clamped_low(self):
        config = {"daemon": {"client_timeout_seconds": 0.1}}
        with mock.patch(
            "ai_guardian.cli_handlers._load_config_file", return_value=(config, None)
        ):
            assert _get_client_timeout() == 0.5

    def test_clamped_high(self):
        config = {"daemon": {"client_timeout_seconds": 99.0}}
        with mock.patch(
            "ai_guardian.cli_handlers._load_config_file", return_value=(config, None)
        ):
            assert _get_client_timeout() == 10.0


class TestSetDaemonModeInConfig:
    def test_is_noop(self):
        _set_daemon_mode_in_config("daemon")


class TestDaemonStartCommand:
    def test_daemon_start_refreshes_typescript_integrations(self):
        args = mock.MagicMock()
        args.daemon_command = "start"
        args.background = False
        args.idle_timeout = None

        with (
            mock.patch(
                "ai_guardian.daemon.auto_setup.auto_upgrade_typescript_integrations"
            ) as upgrade,
            mock.patch("ai_guardian.daemon.server.DaemonServer") as daemon_server,
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        upgrade.assert_called_once_with()
        daemon_server.return_value.start.assert_called_once_with()


class TestDaemonReloadCommand:
    def test_reload_when_running(self, capsys):
        args = mock.MagicMock()
        args.daemon_command = "reload"

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                "ai_guardian.daemon.client.send_reload_config", return_value=True
            ),
            mock.patch(
                "ai_guardian.cli_handlers._get_client_timeout", return_value=2.0
            ),
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        assert "config reloaded" in capsys.readouterr().out

    def test_reload_when_not_running(self, capsys):
        args = mock.MagicMock()
        args.daemon_command = "reload"

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=False
            ),
            mock.patch("ai_guardian.daemon.client.send_reload_config") as mock_reload,
        ):
            result = _handle_daemon_command(args)

        assert result == 1
        assert "not running" in capsys.readouterr().err
        mock_reload.assert_not_called()

    def test_reload_send_fails(self, capsys):
        args = mock.MagicMock()
        args.daemon_command = "reload"

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                "ai_guardian.daemon.client.send_reload_config", return_value=False
            ),
            mock.patch(
                "ai_guardian.cli_handlers._get_client_timeout", return_value=2.0
            ),
        ):
            result = _handle_daemon_command(args)

        assert result == 1
        assert "Failed" in capsys.readouterr().err


class TestGlobalPauseResumeCommands:
    @pytest.fixture(autouse=True)
    def isolated_config(self):
        with mock.patch(
            "ai_guardian.cli_handlers._load_config_file", return_value=({}, None)
        ):
            yield

    @staticmethod
    def _args(command, minutes=0, directory=None, session=None):
        args = mock.MagicMock()
        args.daemon_command = command
        args.minutes = minutes
        args.dir = directory
        args.session = session
        return args

    def test_pause_indefinitely(self, capsys):
        args = self._args("pause")
        sock = mock.MagicMock()

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch("ai_guardian.daemon.client._connect", return_value=sock),
            mock.patch(
                "ai_guardian.daemon.protocol.encode_message", return_value=b"request"
            ) as encode_message,
            mock.patch(
                "ai_guardian.daemon.protocol.decode_message",
                return_value={"type": "response", "data": {"status": "paused"}},
            ),
            mock.patch(
                "ai_guardian.cli_handlers._get_client_timeout", return_value=2.0
            ),
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        assert "scanning paused indefinitely" in capsys.readouterr().out
        request = encode_message.call_args.args[0]
        assert request["type"] == "pause"
        assert request["data"] == {"minutes": 0}
        sock.close.assert_called_once_with()

    def test_pause_for_requested_duration(self, capsys):
        args = self._args("pause", minutes=15)
        sock = mock.MagicMock()

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch("ai_guardian.daemon.client._connect", return_value=sock),
            mock.patch(
                "ai_guardian.daemon.protocol.encode_message", return_value=b"request"
            ) as encode_message,
            mock.patch(
                "ai_guardian.daemon.protocol.decode_message",
                return_value={"type": "response", "data": {"status": "paused"}},
            ),
            mock.patch(
                "ai_guardian.cli_handlers._get_client_timeout", return_value=2.0
            ),
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        assert "scanning paused for 15 minutes" in capsys.readouterr().out
        request = encode_message.call_args.args[0]
        assert request["data"] == {"minutes": 15}

    def test_resume(self, capsys):
        args = self._args("resume")
        sock = mock.MagicMock()

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch("ai_guardian.daemon.client._connect", return_value=sock),
            mock.patch(
                "ai_guardian.daemon.protocol.encode_message", return_value=b"request"
            ) as encode_message,
            mock.patch(
                "ai_guardian.daemon.protocol.decode_message",
                return_value={"type": "response", "data": {"status": "resumed"}},
            ),
            mock.patch(
                "ai_guardian.cli_handlers._get_client_timeout", return_value=2.0
            ),
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        assert "scanning resumed" in capsys.readouterr().out
        assert encode_message.call_args.args[0]["type"] == "resume"
        sock.close.assert_called_once_with()

    def test_unreachable_daemon_reports_failure(self, capsys):
        args = self._args("pause")

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=False
            ),
            mock.patch("ai_guardian.daemon.client._connect") as connect,
        ):
            result = _handle_daemon_command(args)

        assert result == 1
        assert "ai-guardian daemon is not running" in capsys.readouterr().err
        connect.assert_not_called()

    def test_connection_failure_reports_failure(self, capsys):
        args = self._args("resume")

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch("ai_guardian.daemon.client._connect", return_value=None),
        ):
            result = _handle_daemon_command(args)

        assert result == 1
        assert "Failed to connect to daemon" in capsys.readouterr().err

    def test_nested_per_directory_pause_remains_supported(self, tmp_path, capsys):
        directory = str(tmp_path)
        args = self._args("pause", minutes=5, directory=directory)

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                "ai_guardian.daemon.client.send_pause_dir",
                return_value={"status": "dir_paused"},
            ) as send_pause_dir,
            mock.patch(
                "ai_guardian.cli_handlers._get_client_timeout", return_value=2.0
            ),
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        send_pause_dir.assert_called_once_with(directory, 5, timeout=2.0)
        assert capsys.readouterr().out == (
            "ai-guardian daemon: scanning paused for 5 minutes for all sessions "
            f"in {directory}\n"
        )

    def test_nested_per_directory_resume_is_explicitly_bulk(self, tmp_path, capsys):
        directory = str(tmp_path)
        args = self._args("resume", directory=directory)

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                "ai_guardian.daemon.client.send_resume_dir",
                return_value={"status": "dir_resumed"},
            ) as send_resume_dir,
            mock.patch(
                "ai_guardian.cli_handlers._get_client_timeout", return_value=2.0
            ),
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        send_resume_dir.assert_called_once_with(directory, timeout=2.0)
        assert capsys.readouterr().out == (
            "ai-guardian daemon: scanning resumed for all sessions " f"in {directory}\n"
        )

    def test_pause_session_reports_scope_and_duration(self, capsys):
        session_key = "ClaudeAdapter:session-1"
        args = self._args("pause", minutes=15, session=session_key)
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                "ai_guardian.daemon.client.send_pause_session",
                return_value={"status": "session_paused"},
            ) as send_pause_session,
            mock.patch(
                "ai_guardian.cli_handlers._get_client_timeout", return_value=2.0
            ),
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        send_pause_session.assert_called_once_with(session_key, 15, timeout=2.0)
        assert capsys.readouterr().out == (
            "ai-guardian daemon: scanning paused for 15 minutes for hook session "
            f"{session_key}\n"
        )

    def test_resume_session_reports_scope(self, capsys):
        session_key = "ClaudeAdapter:session-1"
        args = self._args("resume", session=session_key)
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                "ai_guardian.daemon.client.send_resume_session",
                return_value={"status": "session_resumed"},
            ) as send_resume_session,
            mock.patch(
                "ai_guardian.cli_handlers._get_client_timeout", return_value=2.0
            ),
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        send_resume_session.assert_called_once_with(session_key, timeout=2.0)
        assert capsys.readouterr().out == (
            "ai-guardian daemon: scanning resumed for hook session " f"{session_key}\n"
        )

    def test_pause_session_explains_missing_stable_identity(self, capsys):
        args = self._args("pause", session="unknown-session")
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                "ai_guardian.daemon.client.send_pause_session", return_value=None
            ),
        ):
            result = _handle_daemon_command(args)

        assert result == 1
        assert (
            "currently active session with a stable identity" in capsys.readouterr().err
        )

    @pytest.mark.parametrize("command", ["pause", "resume"])
    @pytest.mark.parametrize("path_kind", ["relative", "symlink"])
    def test_directory_scope_normalizes_the_project_path(
        self, command, path_kind, tmp_path, monkeypatch, capsys
    ):
        project = tmp_path / "project with spaces"
        project.mkdir()
        monkeypatch.chdir(tmp_path)
        directory = os.path.join(".", project.name, "..", project.name)
        if path_kind == "symlink":
            link = tmp_path / "project-link"
            try:
                link.symlink_to(project, target_is_directory=True)
            except OSError as exc:
                pytest.skip(f"Directory symlinks are unavailable: {exc}")
            directory = str(link)

        args = self._args(command, minutes=15, directory=directory)
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                f"ai_guardian.daemon.client.send_{command}_dir",
                return_value={"status": f"dir_{command}d"},
            ) as send,
            mock.patch("ai_guardian.daemon.client._connect") as global_connect,
            mock.patch(
                f"ai_guardian.daemon.client.send_{command}_session"
            ) as session_send,
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        expected_args = (
            (os.path.realpath(project), 15)
            if command == "pause"
            else (os.path.realpath(project),)
        )
        send.assert_called_once_with(*expected_args, timeout=2.0)
        global_connect.assert_not_called()
        session_send.assert_not_called()
        assert (
            f"for all sessions in {os.path.realpath(project)}"
            in capsys.readouterr().out
        )

    @pytest.mark.parametrize("scope", ["directory", "session"])
    def test_scoped_indefinite_pause_reports_the_existing_lifetime(self, scope, capsys):
        args = self._args(
            "pause",
            directory="project" if scope == "directory" else None,
            session="Adapter:session-1" if scope == "session" else None,
        )
        suffix = "dir" if scope == "directory" else "session"
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                f"ai_guardian.daemon.client.send_pause_{suffix}",
                return_value={"status": f"{suffix}_paused"},
            ) as send,
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        target = (
            os.path.realpath("project") if scope == "directory" else "Adapter:session-1"
        )
        send.assert_called_once_with(target, 0, timeout=2.0)
        lifetime = (
            "indefinitely" if scope == "directory" else "until resume or session end"
        )
        assert lifetime in capsys.readouterr().out

    @pytest.mark.parametrize("command", ["pause", "resume"])
    @pytest.mark.parametrize("scope", ["directory", "session"])
    @pytest.mark.parametrize(
        "response",
        [
            None,
            {},
            {"error": "session is not active"},
            {"error": "unknown message type"},
            {"status": "paused"},
        ],
    )
    def test_failed_scoped_request_never_falls_back_to_another_scope(
        self, command, scope, response, capsys
    ):
        args = self._args(
            command,
            directory="project" if scope == "directory" else None,
            session="unknown-session" if scope == "session" else None,
        )
        suffix = "dir" if scope == "directory" else "session"
        other_suffix = "session" if scope == "directory" else "dir"
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                f"ai_guardian.daemon.client.send_{command}_{suffix}",
                return_value=response,
            ) as send,
            mock.patch(
                f"ai_guardian.daemon.client.send_{command}_{other_suffix}"
            ) as other_send,
            mock.patch("ai_guardian.daemon.client._connect") as global_connect,
        ):
            result = _handle_daemon_command(args)

        assert result == 1
        send.assert_called_once()
        other_send.assert_not_called()
        global_connect.assert_not_called()
        output = capsys.readouterr()
        assert output.out == ""
        if scope == "session":
            assert "currently active session with a stable identity" in output.err
        else:
            assert output.err == f"Failed to {command} directory scanning\n"


class TestDaemonStatusCommand:
    @pytest.mark.parametrize(
        "content", ["[]", "null", '"unit-metadata"', "invalid-json"]
    )
    def test_status_tolerates_malformed_pid_metadata(
        self, tmp_path, monkeypatch, capsys, content
    ):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        (tmp_path / "daemon.pid").write_text(content)
        args = mock.MagicMock(daemon_command="status")
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                "ai_guardian.daemon.client.send_status_request",
                return_value={"request_count": 1},
            ),
            mock.patch("ai_guardian.cli_handlers._get_client_timeout", return_value=2),
        ):
            assert _handle_daemon_command(args) == 0
        output = capsys.readouterr().out
        assert "REST API: unknown (older daemon)" in output
        assert "unit-metadata" not in output

    @pytest.mark.parametrize(
        "metadata,expected",
        [
            ({"rest_port": 45678}, "REST API: available (port 45678)"),
            (
                {
                    "rest_status": "unavailable",
                    "rest_error": "Listener configuration unavailable",
                },
                "REST API: unavailable",
            ),
        ],
    )
    def test_status_uses_pid_readiness_for_older_ipc_responses(
        self, tmp_path, monkeypatch, capsys, metadata, expected
    ):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        (tmp_path / "daemon.pid").write_text(
            json.dumps({"pid": os.getpid(), **metadata})
        )
        args = mock.MagicMock(daemon_command="status")
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                "ai_guardian.daemon.client.send_status_request",
                return_value={"request_count": 1},
            ),
            mock.patch("ai_guardian.cli_handlers._get_client_timeout", return_value=2),
        ):
            assert _handle_daemon_command(args) == 0
        output = capsys.readouterr().out
        assert expected in output
        if metadata.get("rest_error"):
            assert "REST startup: Listener configuration unavailable" in output

    def test_status_lists_stable_hook_sessions_and_pause_state(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        args = mock.MagicMock()
        args.daemon_command = "status"
        session_key = "ClaudeCodeAdapter:session-1"
        stats = {
            "uptime_seconds": 60,
            "blocked_count": 0,
            "request_count": 1,
            "paused": False,
            "last_config_reload_seconds_ago": None,
            "active_sessions": [
                {
                    "session_key": session_key,
                    "session_id": "session-1",
                    "agent": "Claude Code",
                    "project_dir": "/project",
                    "paused": True,
                    "pause_remaining_seconds": 0,
                }
            ],
            "paused_dirs": {},
        }

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                "ai_guardian.daemon.client.send_status_request", return_value=stats
            ),
            mock.patch(
                "ai_guardian.cli_handlers._get_client_timeout", return_value=2.0
            ),
        ):
            result = _handle_daemon_command(args)

        output = capsys.readouterr().out
        assert result == 0
        assert "Active hook sessions with stable IDs: 1" in output
        assert session_key in output
        assert "Claude Code" in output
        assert "/project" in output
        assert "paused until resume or session end" in output
        assert "also covers callers without stable IDs" in output

    def test_status_not_running(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        args = mock.MagicMock()
        args.daemon_command = "status"

        with mock.patch(
            "ai_guardian.daemon.client.is_daemon_running", return_value=False
        ):
            result = _handle_daemon_command(args)

        assert result == 1
        assert "not running" in capsys.readouterr().out

    def test_status_process_alive_but_unresponsive(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(json.dumps({"pid": os.getpid()}))

        args = mock.MagicMock()
        args.daemon_command = "status"

        with mock.patch(
            "ai_guardian.daemon.client.is_daemon_running", return_value=False
        ):
            result = _handle_daemon_command(args)

        output = capsys.readouterr().out
        assert result == 1
        assert "process alive" in output
        assert "not responsive" in output
        assert pid_path.exists()

    def test_status_stale_pid_reports_not_running(self, tmp_path, monkeypatch, capsys):
        """Stale PID files are left for 'daemon start' to clean up (#1154)."""
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(json.dumps({"pid": 99999999}))

        args = mock.MagicMock()
        args.daemon_command = "status"

        with mock.patch(
            "ai_guardian.daemon.client.is_daemon_running", return_value=False
        ):
            result = _handle_daemon_command(args)

        output = capsys.readouterr().out
        assert result == 1
        assert "not running" in output


class TestDaemonStopCommand:
    """Issue #775: daemon stop must not auto-start and must report not running."""

    def test_stop_not_running(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        args = mock.MagicMock()
        args.daemon_command = "stop"

        with mock.patch(
            "ai_guardian.daemon.client.is_daemon_running", return_value=False
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        assert "not running" in capsys.readouterr().out

    def test_stop_not_running_does_not_start_daemon(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        args = mock.MagicMock()
        args.daemon_command = "stop"

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=False
            ),
            mock.patch(
                "ai_guardian.daemon.client.start_daemon_background"
            ) as mock_start,
        ):
            _handle_daemon_command(args)

        mock_start.assert_not_called()

    def test_status_not_running_does_not_start_daemon(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        args = mock.MagicMock()
        args.daemon_command = "status"

        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=False
            ),
            mock.patch(
                "ai_guardian.daemon.client.start_daemon_background"
            ) as mock_start,
        ):
            _handle_daemon_command(args)

        mock_start.assert_not_called()


class TestDaemonResetCommand:
    """Issue #1155: daemon reset kills processes and cleans up state files."""

    def test_reset_no_daemon_running(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        args = mock.MagicMock()
        args.daemon_command = "reset"

        result = _handle_daemon_command(args)

        assert result == 0
        assert "No daemon state to reset" in capsys.readouterr().out

    def test_reset_stale_files_only(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        (tmp_path / "daemon.pid").write_text('{"pid": 99999}')
        (tmp_path / "daemon.pid.lock").write_text("99999")
        (tmp_path / "daemon.sock").touch()
        (tmp_path / "daemon.stop-requested").touch()

        args = mock.MagicMock()
        args.daemon_command = "reset"

        with mock.patch("ai_guardian.daemon.is_pid_alive", return_value=False):
            result = _handle_daemon_command(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "daemon.pid" in out
        assert "daemon.pid.lock" in out
        assert "daemon.sock" in out
        assert "daemon.stop-requested" in out
        assert "Daemon reset complete" in out
        assert not (tmp_path / "daemon.pid").exists()
        assert not (tmp_path / "daemon.pid.lock").exists()
        assert not (tmp_path / "daemon.sock").exists()
        assert not (tmp_path / "daemon.stop-requested").exists()

    def test_reset_running_daemon_sigterm(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        (tmp_path / "daemon.pid").write_text('{"pid": 12345}')

        args = mock.MagicMock()
        args.daemon_command = "reset"

        call_count = [0]

        def fake_is_alive(pid):
            call_count[0] += 1
            # Alive on first check, dead after SIGTERM
            return call_count[0] <= 1

        with (
            mock.patch("ai_guardian.daemon.is_pid_alive", side_effect=fake_is_alive),
            mock.patch("os.kill") as mock_kill,
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "stopped" in out
        assert "SIGKILL" not in out

    def test_reset_uses_lock_pid_when_pid_file_is_corrupt(
        self, tmp_path, monkeypatch, capsys
    ):
        """Reset can stop a daemon when only its startup lock is readable."""

        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        (tmp_path / "daemon.pid").write_text("{corrupt")
        (tmp_path / "daemon.pid.lock").write_text("12345")

        args = mock.MagicMock()
        args.daemon_command = "reset"

        with (
            mock.patch("ai_guardian.daemon.is_pid_alive", side_effect=[True, False]),
            mock.patch("os.kill") as mock_kill,
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        assert "pid 12345" in capsys.readouterr().out
        mock_kill.assert_called_once()

    def test_reset_running_daemon_sigkill(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        (tmp_path / "daemon.pid").write_text('{"pid": 12345}')

        args = mock.MagicMock()
        args.daemon_command = "reset"

        with (
            mock.patch("ai_guardian.daemon.is_pid_alive", return_value=True),
            mock.patch("os.kill") as mock_kill,
            mock.patch("time.sleep"),
        ):
            result = _handle_daemon_command(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "SIGKILL" in out

    def test_reset_clears_stop_requested(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        (tmp_path / "daemon.stop-requested").touch()

        args = mock.MagicMock()
        args.daemon_command = "reset"

        result = _handle_daemon_command(args)

        assert result == 0
        assert not (tmp_path / "daemon.stop-requested").exists()

    def test_reset_does_not_touch_other_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        (tmp_path / "daemon.pid").write_text('{"pid": 99999}')
        (tmp_path / "ai-guardian.log").write_text("log data")
        (tmp_path / "tray.lock").write_text("11111")

        args = mock.MagicMock()
        args.daemon_command = "reset"

        with mock.patch("ai_guardian.daemon.is_pid_alive", return_value=False):
            result = _handle_daemon_command(args)

        assert result == 0
        assert (tmp_path / "ai-guardian.log").exists()
        assert (tmp_path / "tray.lock").exists()


class TestTrayStopCommand:
    """Issue #1149: tray stop must wait for process exit before returning."""

    def test_stop_not_running(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))

        from ai_guardian.cli_handlers import _handle_tray_stop

        result = _handle_tray_stop()

        assert result == 1
        assert "not running" in capsys.readouterr().out

    def test_stop_waits_for_exit(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        lock_path = tmp_path / "tray.lock"
        lock_path.write_text("12345")

        call_count = [0]

        def fake_is_alive(pid):
            call_count[0] += 1
            return call_count[0] <= 3

        from ai_guardian.cli_handlers import _handle_tray_stop

        with (
            mock.patch("ai_guardian.daemon.is_pid_alive", side_effect=fake_is_alive),
            mock.patch("os.kill") as mock_kill,
            mock.patch("time.sleep"),
        ):
            result = _handle_tray_stop()

        assert result == 0
        assert "stopped" in capsys.readouterr().out
        assert not lock_path.exists()
        mock_kill.assert_called_once_with(12345, mock.ANY)

    def test_stop_force_kills_on_timeout(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        lock_path = tmp_path / "tray.lock"
        lock_path.write_text("12345")

        import signal
        from ai_guardian.cli_handlers import _handle_tray_stop

        monotonic_values = iter([0.0, 5.0, 11.0])

        with (
            mock.patch("ai_guardian.daemon.is_pid_alive", return_value=True),
            mock.patch("os.kill") as mock_kill,
            mock.patch("time.sleep"),
            mock.patch("time.monotonic", side_effect=monotonic_values),
        ):
            result = _handle_tray_stop()

        assert result == 0
        assert not lock_path.exists()
        kill_calls = mock_kill.call_args_list
        assert kill_calls[0] == mock.call(12345, signal.SIGTERM)
        force_sig = getattr(signal, "SIGKILL", signal.SIGTERM)
        assert kill_calls[1] == mock.call(12345, force_sig)

    def test_stop_stale_lock(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        lock_path = tmp_path / "tray.lock"
        lock_path.write_text("12345")

        from ai_guardian.cli_handlers import _handle_tray_stop

        with mock.patch("os.kill", side_effect=ProcessLookupError):
            result = _handle_tray_stop()

        assert result == 1
        assert "stale lock" in capsys.readouterr().out
        assert not lock_path.exists()


class TestTrayRestartCommand:
    """Issue #1149: restart should not use fixed sleep."""

    def test_restart_calls_stop_then_start(self, tmp_path, monkeypatch):
        from ai_guardian.cli_handlers import _handle_tray_command

        args = mock.MagicMock()
        args.tray_command = "restart"
        args.uninstall = False
        args.install = False
        args.background = False

        with (
            mock.patch(
                "ai_guardian.cli_handlers._handle_tray_stop", return_value=0
            ) as mock_stop,
            mock.patch(
                "ai_guardian.cli_handlers._handle_tray_start", return_value=0
            ) as mock_start,
            mock.patch("time.sleep") as mock_sleep,
        ):
            result = _handle_tray_command(args)

        mock_stop.assert_called_once()
        mock_start.assert_called_once()
        mock_sleep.assert_not_called()
        assert result == 0


class TestPromptAskProjectPath:
    """Issue #1379: prompt --mode ask must set project_dir_override from violation."""

    def test_sets_project_dir_override(self, tmp_path):
        """When violation has project_path, set_project_dir_override is called."""
        from ai_guardian.cli_handlers import _handle_prompt_ask

        project_dir = str(tmp_path / "my-project")
        violation_json = json.dumps(
            {
                "violation_type": "secret_detected",
                "summary": "test",
                "matched_text": "SECRET",
                "config_section": "secret_scanning",
                "project_path": project_dir,
            }
        )

        args = mock.MagicMock()
        args.violation = violation_json
        args.fallback = "block"
        args.timeout = 5
        args.output_file = None

        with (
            mock.patch(
                "ai_guardian.ui.display.get_preferred_ui",
                return_value="headless",
            ),
            mock.patch("ai_guardian.config.utils.set_project_dir_override") as mock_set,
            mock.patch(
                "ai_guardian.config.utils.clear_project_dir_override"
            ) as mock_clear,
        ):
            _handle_prompt_ask(args)

        mock_set.assert_called_once_with(project_dir)
        mock_clear.assert_called_once()

    def test_no_override_without_project_path(self):
        """When violation has no project_path, override is not set."""
        from ai_guardian.cli_handlers import _handle_prompt_ask

        violation_json = json.dumps(
            {
                "violation_type": "secret_detected",
                "summary": "test",
                "matched_text": "SECRET",
                "config_section": "secret_scanning",
            }
        )

        args = mock.MagicMock()
        args.violation = violation_json
        args.fallback = "block"
        args.timeout = 5
        args.output_file = None

        with (
            mock.patch(
                "ai_guardian.ui.display.get_preferred_ui",
                return_value="headless",
            ),
            mock.patch("ai_guardian.config.utils.set_project_dir_override") as mock_set,
        ):
            _handle_prompt_ask(args)

        mock_set.assert_not_called()

    def test_override_cleared_on_exception(self, tmp_path):
        """Override is cleared even if dialog raises."""
        from ai_guardian.cli_handlers import _handle_prompt_ask

        project_dir = str(tmp_path / "my-project")
        violation_json = json.dumps(
            {
                "violation_type": "secret_detected",
                "summary": "test",
                "matched_text": "SECRET",
                "config_section": "secret_scanning",
                "project_path": project_dir,
            }
        )

        args = mock.MagicMock()
        args.violation = violation_json
        args.fallback = "block"
        args.timeout = 5
        args.output_file = None

        with (
            mock.patch(
                "ai_guardian.ui.display.get_preferred_ui",
                side_effect=RuntimeError("boom"),
            ),
            mock.patch("ai_guardian.config.utils.set_project_dir_override") as mock_set,
            mock.patch(
                "ai_guardian.config.utils.clear_project_dir_override"
            ) as mock_clear,
        ):
            try:
                _handle_prompt_ask(args)
            except RuntimeError:
                pass

        mock_set.assert_called_once_with(project_dir)
        mock_clear.assert_called_once()


class TestBackwardCompatImports:
    def test_import_from_package_level(self):
        from ai_guardian import _handle_violations_command as hvc
        from ai_guardian import _get_daemon_mode as gdm
        from ai_guardian import _get_client_timeout as gct
        from ai_guardian import _set_daemon_mode_in_config as sdm
        from ai_guardian import _handle_daemon_command as hdc

        assert callable(hvc)
        assert callable(gdm)
        assert callable(gct)
        assert callable(sdm)
        assert callable(hdc)
