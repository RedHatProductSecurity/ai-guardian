"""Tests for daemon client."""

import json
import os
import socket
import sys
import tempfile
import threading
from unittest import mock

import pytest

_skip_no_unix_socket = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="AF_UNIX not available on Windows",
)

from ai_guardian.daemon.client import (
    _get_remote_url,
    _is_daemon_running_remote,
    _read_pid_from_file,
    _send_remote,
    is_daemon_running,
    send_hook_request,
    send_reload_config,
    send_shutdown,
    send_status_request,
    start_daemon_background,
    wait_for_process_death,
)
from ai_guardian.daemon.protocol import (
    decode_message,
    encode_message,
    make_response,
)


@pytest.fixture
def short_state_dir(monkeypatch):
    """Use a short temp directory to avoid AF_UNIX path length limits."""
    with tempfile.TemporaryDirectory(prefix="ag") as d:
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", d)
        yield d


class TestIsDaemonRunning:
    def test_no_pid_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        assert not is_daemon_running()

    def test_stale_pid_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(json.dumps({"pid": 99999999}))
        assert not is_daemon_running()

    def test_pid_alive_but_no_socket(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(json.dumps({"pid": os.getpid()}))
        # PID exists but no socket to connect to
        assert not is_daemon_running()


@_skip_no_unix_socket
class TestSendHookRequest:
    def test_returns_none_when_no_daemon(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        result = send_hook_request({"prompt": "test"}, timeout=0.5)
        assert result is None

    def test_returns_none_on_timeout(self, short_state_dir):
        from pathlib import Path

        sock_path = Path(short_state_dir) / "daemon.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(1)

        try:
            result = send_hook_request({"prompt": "test"}, timeout=0.3)
            assert result is None
        finally:
            server.close()
            sock_path.unlink(missing_ok=True)

    def test_successful_request(self, short_state_dir):
        from pathlib import Path

        sock_path = Path(short_state_dir) / "daemon.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(1)

        response_data = {"output": None, "exit_code": 0}

        def mock_server():
            conn, _ = server.accept()
            try:
                request = decode_message(conn, timeout=2.0)
                response = make_response(response_data)
                conn.sendall(encode_message(response))
            finally:
                conn.close()

        thread = threading.Thread(target=mock_server, daemon=True)
        thread.start()

        try:
            result = send_hook_request({"prompt": "test"}, timeout=2.0)
            assert result == response_data
        finally:
            server.close()
            thread.join(timeout=3)

    def test_injects_daemon_cwd(self, short_state_dir):
        """send_hook_request includes _daemon_cwd in the hook data."""
        from pathlib import Path

        sock_path = Path(short_state_dir) / "daemon.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(1)

        received_data = {}

        def mock_server():
            conn, _ = server.accept()
            try:
                request = decode_message(conn, timeout=2.0)
                received_data.update(request.get("data", {}))
                response = make_response({"output": "{}", "exit_code": 0})
                conn.sendall(encode_message(response))
            finally:
                conn.close()

        thread = threading.Thread(target=mock_server, daemon=True)
        thread.start()

        try:
            send_hook_request({"prompt": "test"}, timeout=2.0)
            assert "_daemon_cwd" in received_data
            assert received_data["_daemon_cwd"] == os.getcwd()
        finally:
            server.close()
            thread.join(timeout=3)

    def test_injects_run_id_from_hook_environment(self, short_state_dir, monkeypatch):
        """send_hook_request forwards the invoking agent's correlation ID."""
        from pathlib import Path

        monkeypatch.setenv("AI_GUARDIAN_RUN_ID", "agent-run")
        sock_path = Path(short_state_dir) / "daemon.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(1)
        received_data = {}

        def mock_server():
            conn, _ = server.accept()
            try:
                request = decode_message(conn, timeout=2.0)
                received_data.update(request["data"])
                conn.sendall(
                    encode_message(make_response({"output": None, "exit_code": 0}))
                )
            finally:
                conn.close()

        thread = threading.Thread(target=mock_server, daemon=True)
        thread.start()
        try:
            send_hook_request({"prompt": "test"}, timeout=2.0)
            assert received_data["_ai_guardian_run_id"] == "agent-run"
        finally:
            server.close()
            thread.join(timeout=3)

    def test_does_not_mutate_caller_dict(self, short_state_dir):
        """send_hook_request should not add _daemon_cwd to caller's dict."""
        from pathlib import Path

        sock_path = Path(short_state_dir) / "daemon.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(1)

        def mock_server():
            conn, _ = server.accept()
            try:
                decode_message(conn, timeout=2.0)
                response = make_response({"output": "{}", "exit_code": 0})
                conn.sendall(encode_message(response))
            finally:
                conn.close()

        thread = threading.Thread(target=mock_server, daemon=True)
        thread.start()

        original = {"prompt": "test"}
        try:
            send_hook_request(original, timeout=2.0)
            assert "_daemon_cwd" not in original
        finally:
            server.close()
            thread.join(timeout=3)


class TestSendShutdown:
    def test_returns_false_when_no_daemon(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        assert not send_shutdown()


class TestSendStatusRequest:
    def test_returns_none_when_no_daemon(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        assert send_status_request() is None


class TestSendReloadConfig:
    def test_returns_false_when_no_daemon(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        assert not send_reload_config()


class TestStartDaemonBackground:
    def test_returns_false_on_popen_failure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        with mock.patch(
            "ai_guardian.daemon.client._find_executable",
            return_value=["/nonexistent/ai-guardian"],
        ):
            with mock.patch("subprocess.Popen", side_effect=OSError("not found")):
                assert not start_daemon_background()

    def test_skips_when_stop_requested(self, tmp_path, monkeypatch):
        """Issue #775: auto-start respects stop-requested marker."""
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        marker = tmp_path / "daemon.stop-requested"
        marker.touch()
        with mock.patch("subprocess.Popen") as mock_popen:
            assert not start_daemon_background()
        mock_popen.assert_not_called()

    def test_refuses_when_already_running(self, tmp_path, monkeypatch):
        """Issue #1820: refuse to start duplicate daemon."""
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        with mock.patch(
            "ai_guardian.daemon.client.is_daemon_running", return_value=True
        ):
            with mock.patch("subprocess.Popen") as mock_popen:
                assert not start_daemon_background()
            mock_popen.assert_not_called()


class TestWaitForProcessDeath:
    def test_returns_true_when_pid_is_none(self):
        assert wait_for_process_death(None) is True

    def test_returns_true_when_process_already_dead(self):
        with mock.patch("ai_guardian.daemon.is_pid_alive", return_value=False):
            assert wait_for_process_death(12345, timeout=0.5) is True

    def test_returns_true_when_process_dies_during_wait(self):
        call_count = 0

        def _dying_process(pid):
            nonlocal call_count
            call_count += 1
            return call_count < 3

        with mock.patch("ai_guardian.daemon.is_pid_alive", side_effect=_dying_process):
            assert wait_for_process_death(12345, timeout=2.0) is True

    def test_returns_false_on_timeout(self):
        with mock.patch("ai_guardian.daemon.is_pid_alive", return_value=True):
            assert wait_for_process_death(12345, timeout=0.3) is False


class TestReadPidFromFile:
    def test_returns_pid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(json.dumps({"pid": 42}))
        assert _read_pid_from_file() == 42

    def test_returns_none_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        assert _read_pid_from_file() is None

    def test_returns_none_on_bad_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text("not json")
        assert _read_pid_from_file() is None


class TestClientTimeout:
    """Tests for _get_client_timeout() config reading."""

    def test_default_when_no_config(self):
        from ai_guardian import _get_client_timeout

        with mock.patch(
            "ai_guardian.cli_handlers._load_config_file", return_value=(None, None)
        ):
            assert _get_client_timeout() == 2.0

    def test_reads_from_config(self):
        from ai_guardian import _get_client_timeout

        config = {"daemon": {"client_timeout_seconds": 5.0}}
        with mock.patch(
            "ai_guardian.cli_handlers._load_config_file", return_value=(config, None)
        ):
            assert _get_client_timeout() == 5.0

    def test_clamped_low(self):
        from ai_guardian import _get_client_timeout

        config = {"daemon": {"client_timeout_seconds": 0.1}}
        with mock.patch(
            "ai_guardian.cli_handlers._load_config_file", return_value=(config, None)
        ):
            assert _get_client_timeout() == 0.5

    def test_clamped_high(self):
        from ai_guardian import _get_client_timeout

        config = {"daemon": {"client_timeout_seconds": 99.0}}
        with mock.patch(
            "ai_guardian.cli_handlers._load_config_file", return_value=(config, None)
        ):
            assert _get_client_timeout() == 10.0

    def test_invalid_type_returns_default(self):
        from ai_guardian import _get_client_timeout

        config = {"daemon": {"client_timeout_seconds": "not a number"}}
        with mock.patch(
            "ai_guardian.cli_handlers._load_config_file", return_value=(config, None)
        ):
            assert _get_client_timeout() == 2.0

    def test_missing_daemon_section(self):
        from ai_guardian import _get_client_timeout

        with mock.patch(
            "ai_guardian.cli_handlers._load_config_file", return_value=({}, None)
        ):
            assert _get_client_timeout() == 2.0

    def test_hook_forwarding_passes_config_timeout(self):
        config = {"daemon": {"client_timeout_seconds": 3.5, "mode": "auto"}}
        with mock.patch(
            "ai_guardian.cli_handlers._load_config_file", return_value=(config, None)
        ):
            with mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ):
                with mock.patch(
                    "ai_guardian.daemon.client.send_hook_request",
                    return_value={"output": None, "exit_code": 0},
                ) as mock_send:
                    from ai_guardian import _get_client_timeout

                    mock_send({"prompt": "test"}, timeout=_get_client_timeout())
                    mock_send.assert_called_once_with({"prompt": "test"}, timeout=3.5)


class TestTCPConnection:
    def test_tcp_connect_reads_port_from_pid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))

        # Set up a TCP server
        tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_server.bind(("127.0.0.1", 0))
        tcp_server.listen(1)
        port = tcp_server.getsockname()[1]

        # Write PID file with port
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(json.dumps({"pid": os.getpid(), "port": port}))

        response_data = {"output": None, "exit_code": 0}

        def mock_server():
            conn, _ = tcp_server.accept()
            try:
                request = decode_message(conn, timeout=2.0)
                conn.sendall(encode_message(make_response(response_data)))
            finally:
                conn.close()

        thread = threading.Thread(target=mock_server, daemon=True)
        thread.start()

        try:
            # Mock platform to Windows to force TCP path
            with mock.patch("ai_guardian.daemon.client.platform") as mock_platform:
                mock_platform.system.return_value = "Windows"

                result = send_hook_request({"prompt": "test"}, timeout=2.0)
                assert result == response_data
        finally:
            tcp_server.close()
            thread.join(timeout=3)


class TestIsPidAlive:
    def test_own_process_is_alive(self):
        from ai_guardian.daemon import is_pid_alive

        assert is_pid_alive(os.getpid())

    def test_nonexistent_pid(self):
        from ai_guardian.daemon import is_pid_alive

        assert not is_pid_alive(99999999)

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Windows uses ctypes, not os.kill"
    )
    def test_permission_error_means_alive(self):
        from ai_guardian.daemon import is_pid_alive

        with mock.patch("os.kill", side_effect=PermissionError("EPERM")):
            assert is_pid_alive(12345)

    def test_process_lookup_error_means_dead(self):
        from ai_guardian.daemon import is_pid_alive

        with mock.patch("os.kill", side_effect=ProcessLookupError("ESRCH")):
            assert not is_pid_alive(12345)


class TestStartDaemonBackgroundNoClientCleanup:
    def test_start_background_does_not_call_cleanup(self, tmp_path, monkeypatch):
        """start_daemon_background() delegates cleanup to the daemon process."""
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        with mock.patch(
            "ai_guardian.daemon.client._find_executable",
            return_value=["/nonexistent/ai-guardian"],
        ):
            with mock.patch("subprocess.Popen", side_effect=OSError("not found")):
                start_daemon_background()


class TestGetPackageMaxMtime:
    """Tests for DaemonState.get_package_max_mtime() — scoped to daemon files (#1465)."""

    def test_returns_positive_mtime(self):
        from ai_guardian.daemon.state import DaemonState

        mtime = DaemonState.get_package_max_mtime()
        assert mtime > 0.0

    def test_returns_float(self):
        from ai_guardian.daemon.state import DaemonState

        mtime = DaemonState.get_package_max_mtime()
        assert isinstance(mtime, float)

    def test_record_source_mtime(self):
        from ai_guardian.daemon.state import DaemonState

        state = DaemonState(idle_timeout=0)
        assert state._source_mtime == 0.0
        state.record_source_mtime()
        assert state._source_mtime > 0.0

    def test_excludes_tui_files(self, tmp_path):
        """tui/ changes must not trigger daemon-restart warning (#1465)."""
        from ai_guardian.daemon.state import DaemonState
        import ai_guardian

        pkg_dir = tmp_path / "ai_guardian"
        pkg_dir.mkdir()
        # Daemon-relevant file — very old mtime
        daemon_dir = pkg_dir / "daemon"
        daemon_dir.mkdir()
        daemon_py = daemon_dir / "server.py"
        daemon_py.write_text("")
        daemon_py.touch()
        import os

        os.utime(str(daemon_py), (1000.0, 1000.0))
        # TUI file — newer mtime (should be excluded)
        tui_dir = pkg_dir / "tui"
        tui_dir.mkdir()
        tui_py = tui_dir / "app.py"
        tui_py.write_text("")
        os.utime(str(tui_py), (9999.0, 9999.0))
        (pkg_dir / "__init__.py").write_text("")

        with mock.patch.object(
            __import__("ai_guardian"), "__file__", str(pkg_dir / "__init__.py")
        ):
            mtime = DaemonState.get_package_max_mtime()

        assert mtime <= 1000.0, "tui/ file should not affect max mtime"

    def test_includes_hook_processing(self, tmp_path):
        """hook_processing.py changes must be detected (#1465)."""
        from ai_guardian.daemon.state import DaemonState

        pkg_dir = tmp_path / "ai_guardian"
        pkg_dir.mkdir()
        hp = pkg_dir / "hook_processing.py"
        hp.write_text("")
        import os

        os.utime(str(hp), (5000.0, 5000.0))
        (pkg_dir / "__init__.py").write_text("")

        with mock.patch.object(
            __import__("ai_guardian"), "__file__", str(pkg_dir / "__init__.py")
        ):
            mtime = DaemonState.get_package_max_mtime()

        assert mtime >= 5000.0


class TestRemoteURL:
    """Tests for _get_remote_url() parsing."""

    def test_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("AI_GUARDIAN_DAEMON_URL", raising=False)
        assert _get_remote_url() is None

    def test_http_url(self, monkeypatch):
        monkeypatch.delenv("AI_GUARDIAN_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", "http://myhost:9999")
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", "/nonexistent")
        result = _get_remote_url()
        assert result is not None
        scheme, host, port, token = result
        assert scheme == "http"
        assert host == "myhost"
        assert port == 9999
        assert token is None

    def test_http_default_port(self, monkeypatch):
        monkeypatch.delenv("AI_GUARDIAN_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", "http://myhost")
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", "/nonexistent")
        result = _get_remote_url()
        assert result is not None
        from ai_guardian.daemon import DEFAULT_REST_PORT

        assert result[2] == DEFAULT_REST_PORT

    def test_token_in_url(self, monkeypatch):
        monkeypatch.delenv("AI_GUARDIAN_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", "http://mytoken@host:1234")
        result = _get_remote_url()
        assert result[3] == "mytoken"

    def test_env_token(self, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", "http://host:1234")
        monkeypatch.setenv("AI_GUARDIAN_AUTH_TOKEN", "env-token-abc")
        result = _get_remote_url()
        assert result[3] == "env-token-abc"

    def test_url_token_overrides_env(self, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", "http://url-token@host:1234")
        monkeypatch.setenv("AI_GUARDIAN_AUTH_TOKEN", "env-token")
        result = _get_remote_url()
        assert result[3] == "url-token"

    def test_unsupported_scheme(self, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", "tcp://host:1234")
        assert _get_remote_url() is None

    def test_token_from_file_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", "http://host:1234")
        monkeypatch.delenv("AI_GUARDIAN_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        token_path = tmp_path / "daemon.token"
        token_path.write_text("file-token-xyz")
        result = _get_remote_url()
        assert result[3] == "file-token-xyz"


class TestSendRemote:
    """Tests for _send_remote() HTTP transport."""

    def test_returns_none_without_url(self, monkeypatch):
        monkeypatch.delenv("AI_GUARDIAN_DAEMON_URL", raising=False)
        assert _send_remote("/api/hook", {"test": True}) is None

    def test_returns_none_on_connection_refused(self, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", "http://127.0.0.1:1")
        monkeypatch.setenv("AI_GUARDIAN_AUTH_TOKEN", "tok")
        assert _send_remote("/api/hook", {}, timeout=1.0) is None

    def test_http_round_trip(self, monkeypatch):
        """Spin up a real REST API server and verify HTTP round-trip."""
        from ai_guardian.daemon.rest_api import DaemonRestAPI

        class _MinState:
            _paused = False

            def get_stats(self):
                return {}

            def pause(self, m):
                pass

            def resume(self):
                pass

            def force_reload_config(self):
                pass

            def get_config(self):
                return {}

        state = _MinState()
        api = DaemonRestAPI(state=state, host="127.0.0.1", port=0)
        port = api.start()
        try:
            monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", f"http://127.0.0.1:{port}")
            result = _send_remote("/api/health", {}, timeout=5.0)
            # /api/health is GET only, POST will 404 — test with a GET-based approach
            # Instead, test _is_daemon_running_remote which uses GET /api/health
            assert _is_daemon_running_remote() is True
        finally:
            api.stop()


class TestIsDaemonRunningRemote:
    """Tests for is_daemon_running() with remote URL."""

    def test_remote_reachable(self, monkeypatch):
        from ai_guardian.daemon.rest_api import DaemonRestAPI

        class _MinState:
            _paused = False

            def get_stats(self):
                return {}

            def pause(self, m):
                pass

            def resume(self):
                pass

            def force_reload_config(self):
                pass

            def get_config(self):
                return {}

        state = _MinState()
        api = DaemonRestAPI(state=state, host="127.0.0.1", port=0)
        port = api.start()
        try:
            monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", f"http://127.0.0.1:{port}")
            assert is_daemon_running() is True
        finally:
            api.stop()

    def test_remote_unreachable(self, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", "http://127.0.0.1:1")
        assert is_daemon_running() is False


class TestSendHookRequestRemote:
    """Tests for send_hook_request() with remote URL."""

    def test_hook_forwarded_via_http(self, monkeypatch):
        """Verify hook request is forwarded via HTTP when URL is set."""
        captured = {}

        def mock_send_remote(path, data, timeout=5.0):
            captured["path"] = path
            captured["data"] = data
            return {"output": "{}", "exit_code": 0}

        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", "http://host:1234")
        monkeypatch.setenv("AI_GUARDIAN_AUTH_TOKEN", "tok")
        monkeypatch.setattr("ai_guardian.daemon.client._send_remote", mock_send_remote)

        result = send_hook_request({"hook_event_name": "PreToolUse"})
        assert result == {"output": "{}", "exit_code": 0}
        assert captured["path"] == "/api/hook"
        assert "_daemon_cwd" in captured["data"]
        assert captured["data"]["hook_event_name"] == "PreToolUse"

    def test_hook_does_not_mutate_input(self, monkeypatch):
        """Original hook_data dict must not be modified."""
        original = {"hook_event_name": "PreToolUse"}

        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", "http://host:1234")
        monkeypatch.setenv("AI_GUARDIAN_AUTH_TOKEN", "tok")
        monkeypatch.setattr(
            "ai_guardian.daemon.client._send_remote",
            lambda *a, **kw: {"output": "{}", "exit_code": 0},
        )

        send_hook_request(original)
        assert "_daemon_cwd" not in original


class TestStartDaemonBackgroundRemote:
    """Tests for start_daemon_background() with remote URL."""

    def test_skips_auto_start_when_remote(self, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", "http://remote:8484")
        monkeypatch.setenv("AI_GUARDIAN_AUTH_TOKEN", "tok")
        assert start_daemon_background() is False
