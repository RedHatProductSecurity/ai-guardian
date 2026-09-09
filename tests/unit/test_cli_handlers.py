"""Tests for ai_guardian.cli_handlers module."""

import json
import os
from unittest import mock

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


class TestDaemonStatusCommand:
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
                "ai_guardian.tui.display.get_preferred_ui",
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
                "ai_guardian.tui.display.get_preferred_ui",
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
                "ai_guardian.tui.display.get_preferred_ui",
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
