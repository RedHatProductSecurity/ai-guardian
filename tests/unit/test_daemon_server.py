"""Tests for daemon server."""

import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Daemon server tests require Unix sockets (AF_UNIX)",
)

from ai_guardian.daemon.protocol import (
    decode_message,
    encode_message,
    make_hook_request,
    make_ping,
    make_shutdown,
    make_status_request,
    make_subscribe,
)
from ai_guardian.daemon.server import DaemonServer
from ai_guardian.daemon.state import DaemonState


def _wait_server_ready(server, timeout=3.0):
    """Wait until the daemon server is accepting connections."""
    if not server._ready_event.wait(timeout=timeout):
        raise RuntimeError(f"Server not ready after {timeout}s")


def _connect(sock_path, timeout=2.0):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(str(sock_path))
    return sock


@pytest.fixture
def running_server(monkeypatch):
    """Shared fixture: start a DaemonServer in a temp dir, wait for readiness."""
    d = tempfile.mkdtemp(prefix="ag")
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", d)

    server = DaemonServer(idle_timeout=30, enable_rest_api=False)
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()

    sock_path = Path(d) / "daemon.sock"
    _wait_server_ready(server)

    yield server, sock_path

    server.stop()
    thread.join(timeout=3)
    import shutil

    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def short_state_dir(monkeypatch):
    """Use a short temp directory to avoid AF_UNIX path length limits."""
    with tempfile.TemporaryDirectory(prefix="ag") as d:
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", d)
        yield d


class TestDaemonServerLifecycle:
    def test_server_creates_socket_file(self, short_state_dir, monkeypatch):
        server = DaemonServer(idle_timeout=5)

        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()

        _wait_server_ready(server)
        assert (Path(short_state_dir) / "daemon.sock").exists()
        server.stop()
        thread.join(timeout=3)

    def test_server_creates_pid_file(self, short_state_dir, monkeypatch):

        server = DaemonServer(idle_timeout=5)

        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()

        _wait_server_ready(server)
        pid_path = Path(short_state_dir) / "daemon.pid"
        pid_info = json.loads(pid_path.read_text())
        assert pid_info["pid"] == os.getpid()

        server.stop()
        thread.join(timeout=3)

    def test_server_cleans_up_on_stop(self, short_state_dir, monkeypatch):

        server = DaemonServer(idle_timeout=5)

        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()

        _wait_server_ready(server)
        server.stop()
        thread.join(timeout=3)

        assert not (Path(short_state_dir) / "daemon.sock").exists()
        assert not (Path(short_state_dir) / "daemon.pid").exists()

    def test_server_rejects_duplicate_start(self, short_state_dir, monkeypatch):

        pid_path = Path(short_state_dir) / "daemon.pid"
        pid_path.write_text(json.dumps({"pid": os.getpid()}))

        server = DaemonServer(idle_timeout=5)
        with mock.patch.object(server, "_is_old_daemon_responsive", return_value=True):
            with pytest.raises(RuntimeError, match="already running"):
                server.start()

    def test_server_cleans_stale_pid_with_recycled_pid(self, short_state_dir):
        """PID file references a live process that is NOT the daemon (recycled PID).

        In containers, PIDs recycle quickly. _cleanup_stale() should verify
        socket connectivity, not just PID liveness.
        """

        pid_path = Path(short_state_dir) / "daemon.pid"
        # Use current process PID — it's alive but not a daemon
        pid_path.write_text(json.dumps({"pid": os.getpid()}))
        # No socket file exists, so the daemon is not actually running

        server = DaemonServer(idle_timeout=5, enable_rest_api=False)
        # Should NOT raise RuntimeError — should clean up stale PID
        server._cleanup_stale()
        assert not pid_path.exists()

    def test_server_cleans_stale_pid_with_dead_process(self, short_state_dir):
        """PID file references a dead process — straightforward stale case."""

        pid_path = Path(short_state_dir) / "daemon.pid"
        pid_path.write_text(json.dumps({"pid": 99999999}))

        server = DaemonServer(idle_timeout=5, enable_rest_api=False)
        server._cleanup_stale()
        assert not pid_path.exists()

    def test_server_cleans_stale_socket_file(self, short_state_dir):
        """Stale socket file from crashed daemon is cleaned up."""

        sock_path = Path(short_state_dir) / "daemon.sock"
        sock_path.write_text("")  # Create a stale socket file

        server = DaemonServer(idle_timeout=5, enable_rest_api=False)
        server._cleanup_stale()
        assert not sock_path.exists()

    def test_stop_is_idempotent(self, short_state_dir, monkeypatch):
        """Calling stop() twice must not raise."""
        server = DaemonServer(idle_timeout=5, enable_rest_api=False)

        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()

        _wait_server_ready(server)
        server.stop()
        server.stop()  # second call must be a no-op
        thread.join(timeout=3)

    def test_cleanup_state_files_deletes_pid_before_socket(self, short_state_dir):
        """PID file must be deleted before socket file (#1425).

        The client-side dev-restart loop uses PID file absence as the
        authoritative signal that the old daemon is fully gone. If socket is
        deleted first, the loop can fire start_daemon_background() while the
        PID file still exists, triggering a false 'PID recycled' path in
        _cleanup_stale() and orphaning the new daemon.
        """

        delete_order = []
        pid_path = Path(short_state_dir) / "daemon.pid"
        sock_path = Path(short_state_dir) / "daemon.sock"

        pid_path.write_text(json.dumps({"pid": os.getpid()}))
        sock_path.write_text("")

        original_unlink = Path.unlink

        def tracking_unlink(self_path, missing_ok=False):
            if self_path.name in ("daemon.pid", "daemon.sock"):
                delete_order.append(self_path.name)
            return original_unlink(self_path, missing_ok=missing_ok)

        server = DaemonServer(idle_timeout=5, enable_rest_api=False)
        with mock.patch.object(Path, "unlink", tracking_unlink):
            server._cleanup_state_files()

        assert "daemon.pid" in delete_order, "PID file was not deleted"
        assert "daemon.sock" in delete_order, "Socket file was not deleted"
        pid_idx = delete_order.index("daemon.pid")
        sock_idx = delete_order.index("daemon.sock")
        assert (
            pid_idx < sock_idx
        ), f"PID must be deleted before socket (got order: {delete_order})"

    def test_stop_cleans_lock_file(self, short_state_dir, monkeypatch):
        """Lock file is deleted when daemon stops."""

        server = DaemonServer(idle_timeout=5, enable_rest_api=False)

        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()

        _wait_server_ready(server)
        lock_path = Path(short_state_dir) / "daemon.pid.lock"
        assert lock_path.exists(), "Lock file should exist while running"

        server.stop()
        thread.join(timeout=3)

        # Poll briefly — server thread's finally:stop() may still be
        # cleaning up if the test's stop() raced with _running (#1295)
        for _ in range(10):
            if not lock_path.exists():
                break
            time.sleep(0.1)

        assert not lock_path.exists()

    def test_pid_file_not_written_before_socket(self, short_state_dir, monkeypatch):
        """PID file must not exist before the socket is ready (#1154)."""

        pid_path = Path(short_state_dir) / "daemon.pid"
        sock_path = Path(short_state_dir) / "daemon.sock"

        server = DaemonServer(idle_timeout=5, enable_rest_api=False)

        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()

        _wait_server_ready(server)
        assert pid_path.exists()
        pid_info = json.loads(pid_path.read_text())
        assert pid_info["pid"] == os.getpid()
        assert sock_path.exists()

        server.stop()
        thread.join(timeout=3)


class TestDaemonServerProtocol:

    def test_ping_pong(self, running_server):
        server, sock_path = running_server
        sock = _connect(sock_path)
        try:
            sock.sendall(encode_message(make_ping()))
            response = decode_message(sock, timeout=2.0)
            assert response["type"] == "pong"
        finally:
            sock.close()

    def test_status_request(self, running_server):
        server, sock_path = running_server
        sock = _connect(sock_path)
        try:
            sock.sendall(encode_message(make_status_request()))
            response = decode_message(sock, timeout=2.0)
            assert response["type"] == "response"
            data = response["data"]
            assert "request_count" in data
            assert "uptime_seconds" in data
        finally:
            sock.close()

    def test_shutdown_request(self, short_state_dir, monkeypatch):

        server = DaemonServer(idle_timeout=30, enable_rest_api=False)

        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()

        sock_path = Path(short_state_dir) / "daemon.sock"
        _wait_server_ready(server)

        sock = _connect(sock_path)
        try:
            sock.sendall(encode_message(make_shutdown()))
            response = decode_message(sock, timeout=2.0)
            assert response["type"] == "response"
        finally:
            sock.close()

        thread.join(timeout=5)

    def test_unknown_message_type(self, running_server):
        server, sock_path = running_server
        sock = _connect(sock_path)
        try:
            msg = {"version": 1, "type": "unknown_type"}
            sock.sendall(encode_message(msg))
            response = decode_message(sock, timeout=2.0)
            assert response["type"] == "response"
            assert "error" in response["data"]
        finally:
            sock.close()

    def test_hook_request(self, running_server):
        server, sock_path = running_server
        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "hello world",
        }
        sock = _connect(sock_path)
        try:
            sock.sendall(encode_message(make_hook_request(hook_data)))
            response = decode_message(sock, timeout=5.0)
            assert response["type"] == "response"
            data = response["data"]
            assert "exit_code" in data
        finally:
            sock.close()

    def test_hook_request_when_paused_returns_empty_json(self, running_server):
        server, sock_path = running_server
        server.state.pause()

        hook_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }
        sock = _connect(sock_path)
        try:
            sock.sendall(encode_message(make_hook_request(hook_data)))
            response = decode_message(sock, timeout=5.0)
            assert response["type"] == "response"
            data = response["data"]
            assert data["output"] == "{}"
            assert data["exit_code"] == 0
        finally:
            sock.close()
            server.state.resume()

    def test_hook_request_after_resume_processes_normally(self, running_server):
        server, sock_path = running_server
        server.state.pause()
        server.state.resume()

        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "hello world",
        }
        sock = _connect(sock_path)
        try:
            sock.sendall(encode_message(make_hook_request(hook_data)))
            response = decode_message(sock, timeout=5.0)
            assert response["type"] == "response"
            data = response["data"]
            assert "exit_code" in data
        finally:
            sock.close()


class TestDaemonServerSubscriber:
    """Tests for push event subscriber protocol (#650)."""

    def test_subscribe_returns_ack(self, running_server):
        server, sock_path = running_server
        sock = _connect(sock_path)
        try:
            sock.sendall(encode_message(make_subscribe()))
            response = decode_message(sock, timeout=2.0)
            assert response["type"] == "response"
            assert response["data"]["status"] == "subscribed"
        finally:
            sock.close()

    def test_subscriber_receives_event_on_pause(self, running_server):
        server, sock_path = running_server
        sock = _connect(sock_path)
        try:
            sock.sendall(encode_message(make_subscribe()))
            decode_message(sock, timeout=2.0)  # consume ack

            server.state.pause(5)

            event = decode_message(sock, timeout=2.0)
            assert event["type"] == "event"
            assert event["event"] == "paused"
            assert event["data"]["minutes"] == 5
        finally:
            sock.close()

    def test_subscriber_receives_event_on_resume(self, running_server):
        server, sock_path = running_server
        sock = _connect(sock_path)
        try:
            sock.sendall(encode_message(make_subscribe()))
            decode_message(sock, timeout=2.0)

            server.state.pause()
            decode_message(sock, timeout=2.0)  # consume pause event

            server.state.resume()
            event = decode_message(sock, timeout=2.0)
            assert event["type"] == "event"
            assert event["event"] == "resumed"
        finally:
            sock.close()

    def test_dead_subscriber_cleaned_on_broadcast(self, running_server):
        server, sock_path = running_server
        sock = _connect(sock_path)
        sock.sendall(encode_message(make_subscribe()))
        decode_message(sock, timeout=2.0)
        sock.close()

        server.state.pause(5)
        time.sleep(0.2)

        with server._subscribers_lock:
            assert len(server._subscribers) == 0

    def test_multiple_subscribers(self, running_server):
        server, sock_path = running_server
        socks = []
        for _ in range(3):
            s = _connect(sock_path)
            s.sendall(encode_message(make_subscribe()))
            decode_message(s, timeout=2.0)
            socks.append(s)

        server.state.resume()

        for s in socks:
            event = decode_message(s, timeout=2.0)
            assert event["type"] == "event"
            assert event["event"] == "resumed"
            s.close()

    def test_one_shot_client_still_works_with_subscribers(self, running_server):
        server, sock_path = running_server
        sub = _connect(sock_path)
        sub.sendall(encode_message(make_subscribe()))
        decode_message(sub, timeout=2.0)

        ping_sock = _connect(sock_path)
        try:
            ping_sock.sendall(encode_message(make_ping()))
            response = decode_message(ping_sock, timeout=2.0)
            assert response["type"] == "pong"
        finally:
            ping_sock.close()
            sub.close()


class TestDaemonServerTCP:
    def test_tcp_mode_binds_localhost(self, short_state_dir, monkeypatch):
        server = DaemonServer(idle_timeout=5, use_tcp=True, enable_rest_api=False)

        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()

        _wait_server_ready(server)
        pid_path = Path(short_state_dir) / "daemon.pid"
        pid_info = json.loads(pid_path.read_text())
        assert "port" in pid_info
        port = pid_info["port"]
        assert port > 0

        # Connect and ping
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(("127.0.0.1", port))
        try:
            sock.sendall(encode_message(make_ping()))
            response = decode_message(sock, timeout=2.0)
            assert response["type"] == "pong"
        finally:
            sock.close()

        server.stop()
        thread.join(timeout=3)


class TestDaemonServerCrossPlatform:
    def test_windows_auto_detects_tcp(self, monkeypatch):
        with mock.patch("platform.system", return_value="Windows"):
            server = DaemonServer(idle_timeout=5)
            assert server._use_tcp is True

    def test_linux_uses_unix_socket(self, monkeypatch):
        with mock.patch("platform.system", return_value="Linux"):
            server = DaemonServer(idle_timeout=5)
            assert server._use_tcp is False


class TestDaemonServerPausedHook:
    """Test that paused daemon returns valid empty JSON to avoid Claude Code errors."""

    def test_handle_hook_request_paused_returns_empty_json(self, short_state_dir):
        server = DaemonServer(idle_timeout=30, enable_rest_api=False)
        server.state.pause()

        result = server._handle_hook_request(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
            }
        )

        assert result["output"] == "{}"
        assert result["exit_code"] == 0

    def test_handle_hook_request_paused_output_is_valid_json(self, short_state_dir):
        server = DaemonServer(idle_timeout=30, enable_rest_api=False)
        server.state.pause()

        result = server._handle_hook_request(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "test",
            }
        )

        parsed = json.loads(result["output"])
        assert isinstance(parsed, dict)

    def test_handle_hook_request_paused_prompt_injects_security(self, short_state_dir):
        server = DaemonServer(idle_timeout=30, enable_rest_api=False)
        server.state.pause()

        result = server._handle_hook_request(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "test",
            }
        )

        parsed = json.loads(result["output"])
        assert "systemMessage" in parsed
        assert "SECURITY RULES" in parsed["systemMessage"]
        assert result["exit_code"] == 0

    def test_handle_hook_request_paused_non_prompt_returns_empty(self, short_state_dir):
        server = DaemonServer(idle_timeout=30, enable_rest_api=False)
        server.state.pause()

        result = server._handle_hook_request(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
            }
        )

        assert result["output"] == "{}"
        assert result["exit_code"] == 0

    def test_handle_hook_request_dir_paused_prompt_injects_security(
        self, short_state_dir
    ):
        server = DaemonServer(idle_timeout=30, enable_rest_api=False)
        test_dir = "/tmp/test_project"
        server.state.pause_dir(test_dir)

        result = server._handle_hook_request(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "test",
                "_daemon_cwd": test_dir,
            }
        )

        parsed = json.loads(result["output"])
        assert "systemMessage" in parsed
        assert "SECURITY RULES" in parsed["systemMessage"]

    def test_handle_hook_request_not_paused_processes_normally(self, short_state_dir):
        server = DaemonServer(idle_timeout=30, enable_rest_api=False)
        assert not server.state.paused

        result = server._handle_hook_request(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "hello",
            }
        )

        assert "exit_code" in result


class TestPausedOtelTracking:
    """Test that OTEL lifecycle events are tracked while daemon is paused (#2034)."""

    def test_paused_session_start_creates_otel_emitter(self, short_state_dir):
        """First hook while paused should create OTEL emitter and record session start."""
        server = DaemonServer(idle_timeout=30, enable_rest_api=False)
        server.state.pause()

        mock_emitter = mock.MagicMock()
        mock_get = mock.patch.object(
            server.state, "get_otel_emitter", return_value=mock_emitter
        )
        with mock_get as patched_get:
            server._handle_hook_request(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "test-session-001",
                    "prompt": "hello",
                    "_daemon_cwd": "/tmp/project",
                }
            )
            patched_get.assert_called_once_with("test-session-001")

        mock_emitter.record_session_start.assert_called_once()

    def test_paused_session_end_flushes_otel_emitter(self, short_state_dir):
        """SessionEnd while paused should flush the OTEL emitter."""
        server = DaemonServer(idle_timeout=30, enable_rest_api=False)
        server.state.pause()

        with mock.patch.object(server.state, "flush_otel_emitter") as mock_flush:
            server._handle_hook_request(
                {
                    "hook_event_name": "SessionEnd",
                    "session_id": "test-session-002",
                }
            )

        mock_flush.assert_called_once()
        call_kwargs = mock_flush.call_args
        assert call_kwargs[0][0] == "test-session-002"

    def test_paused_no_session_id_skips_otel(self, short_state_dir):
        """Hooks without session_id should skip OTEL tracking."""
        server = DaemonServer(idle_timeout=30, enable_rest_api=False)
        server.state.pause()

        with mock.patch.object(server.state, "get_otel_emitter") as mock_get:
            server._handle_hook_request(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                }
            )

        mock_get.assert_not_called()

    def test_paused_otel_disabled_skips_gracefully(self, short_state_dir):
        """When OTEL is disabled, get_otel_emitter returns None — no crash."""
        server = DaemonServer(idle_timeout=30, enable_rest_api=False)
        server.state.pause()

        with mock.patch.object(server.state, "get_otel_emitter", return_value=None):
            result = server._handle_hook_request(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "test-session-004",
                    "prompt": "hello",
                }
            )

        assert result["exit_code"] == 0

    def test_dir_paused_tracks_otel(self, short_state_dir):
        """Per-directory pause should also track OTEL lifecycle."""
        server = DaemonServer(idle_timeout=30, enable_rest_api=False)
        test_dir = "/tmp/test_project"
        server.state.pause_dir(test_dir)

        mock_emitter = mock.MagicMock()
        with mock.patch.object(
            server.state, "get_otel_emitter", return_value=mock_emitter
        ):
            server._handle_hook_request(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "test-session-005",
                    "_daemon_cwd": test_dir,
                }
            )

        mock_emitter.record_session_start.assert_called_once()

    def test_paused_otel_error_is_nonfatal(self, short_state_dir):
        """OTEL errors while paused should not affect the paused response."""
        server = DaemonServer(idle_timeout=30, enable_rest_api=False)
        server.state.pause()

        with mock.patch.object(
            server.state, "get_otel_emitter", side_effect=RuntimeError("boom")
        ):
            result = server._handle_hook_request(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "test-session-006",
                }
            )

        assert result["exit_code"] == 0
        assert result["output"] == "{}"


class TestDaemonServerPauseResumeProtocol:
    """Test socket protocol handlers for pause and resume messages (issue #683)."""

    def test_pause_message_pauses_daemon(self, running_server):
        server, sock_path = running_server
        assert not server.state.paused

        sock = _connect(sock_path)
        try:
            msg = {"version": 1, "type": "pause", "data": {"minutes": 5}}
            sock.sendall(encode_message(msg))
            response = decode_message(sock, timeout=2.0)
            assert response["type"] == "response"
            assert response["data"]["status"] == "paused"
            assert response["data"]["minutes"] == 5
        finally:
            sock.close()

        assert server.state.paused

    def test_resume_message_resumes_daemon(self, running_server):
        server, sock_path = running_server
        server.state.pause(10)
        assert server.state.paused

        sock = _connect(sock_path)
        try:
            msg = {"version": 1, "type": "resume"}
            sock.sendall(encode_message(msg))
            response = decode_message(sock, timeout=2.0)
            assert response["type"] == "response"
            assert response["data"]["status"] == "resumed"
        finally:
            sock.close()

        assert not server.state.paused

    def test_pause_indefinite(self, running_server):
        server, sock_path = running_server
        sock = _connect(sock_path)
        try:
            msg = {"version": 1, "type": "pause", "data": {"minutes": 0}}
            sock.sendall(encode_message(msg))
            response = decode_message(sock, timeout=2.0)
            assert response["data"]["status"] == "paused"
            assert response["data"]["minutes"] == 0
        finally:
            sock.close()

        assert server.state.paused
        assert server.state.pause_remaining_seconds() == 0.0

    def test_pause_then_hook_returns_empty(self, running_server):
        server, sock_path = running_server

        # Pause via socket
        sock = _connect(sock_path)
        try:
            msg = {"version": 1, "type": "pause", "data": {"minutes": 5}}
            sock.sendall(encode_message(msg))
            decode_message(sock, timeout=2.0)
        finally:
            sock.close()

        # Hook request should be bypassed
        sock = _connect(sock_path)
        try:
            sock.sendall(
                encode_message(
                    make_hook_request(
                        {
                            "hook_event_name": "PreToolUse",
                            "tool_name": "Bash",
                            "tool_input": {"command": "ls"},
                        }
                    )
                )
            )
            response = decode_message(sock, timeout=5.0)
            assert response["data"]["output"] == "{}"
            assert response["data"]["exit_code"] == 0
        finally:
            sock.close()

    def test_resume_then_hook_processes_normally(self, running_server):
        server, sock_path = running_server
        server.state.pause(5)

        # Resume via socket
        sock = _connect(sock_path)
        try:
            msg = {"version": 1, "type": "resume"}
            sock.sendall(encode_message(msg))
            decode_message(sock, timeout=2.0)
        finally:
            sock.close()

        # Hook should be processed normally
        sock = _connect(sock_path)
        try:
            sock.sendall(
                encode_message(
                    make_hook_request(
                        {
                            "hook_event_name": "UserPromptSubmit",
                            "prompt": "hello",
                        }
                    )
                )
            )
            response = decode_message(sock, timeout=5.0)
            assert "exit_code" in response["data"]
        finally:
            sock.close()


class TestDaemonServerPerDirPauseProtocol:
    """Test socket protocol handlers for per-directory pause/resume (#958)."""

    def test_pause_dir_message(self, running_server):
        server, sock_path = running_server
        sock = _connect(sock_path)
        try:
            msg = {
                "version": 1,
                "type": "pause_dir",
                "data": {"dir": "/project/a", "minutes": 30},
            }
            sock.sendall(encode_message(msg))
            response = decode_message(sock, timeout=2.0)
            assert response["type"] == "response"
            assert response["data"]["status"] == "dir_paused"
            assert response["data"]["dir"] == "/project/a"
        finally:
            sock.close()
        assert server.state.is_dir_paused("/project/a")

    def test_resume_dir_message(self, running_server):
        server, sock_path = running_server
        server.state.pause_dir("/project/a")

        sock = _connect(sock_path)
        try:
            msg = {"version": 1, "type": "resume_dir", "data": {"dir": "/project/a"}}
            sock.sendall(encode_message(msg))
            response = decode_message(sock, timeout=2.0)
            assert response["type"] == "response"
            assert response["data"]["status"] == "dir_resumed"
        finally:
            sock.close()
        assert not server.state.is_dir_paused("/project/a")

    def test_pause_dir_missing_dir_returns_error(self, running_server):
        server, sock_path = running_server
        sock = _connect(sock_path)
        try:
            msg = {"version": 1, "type": "pause_dir", "data": {}}
            sock.sendall(encode_message(msg))
            response = decode_message(sock, timeout=2.0)
            assert "error" in response["data"]
        finally:
            sock.close()

    def test_per_dir_pause_does_not_affect_other_dirs(self, running_server):
        """Pausing one dir should not pause another."""
        server, sock_path = running_server
        server.state.pause_dir("/project/a")

        # Hook from /project/b (not paused) should be processed
        assert not server.state.is_dir_paused("/project/b")
        assert server.state.is_dir_paused("/project/a")

    def test_paused_dir_hook_returns_empty(self, running_server):
        """Hook from a paused directory should return empty JSON."""
        server, sock_path = running_server
        server.state.pause_dir("/project/a")

        sock = _connect(sock_path)
        try:
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
                "_daemon_cwd": "/project/a",
            }
            sock.sendall(encode_message(make_hook_request(hook_data)))
            response = decode_message(sock, timeout=5.0)
            assert response["data"]["output"] == "{}"
            assert response["data"]["exit_code"] == 0
        finally:
            sock.close()

    @pytest.mark.parametrize(
        "pause_mode, cwd",
        [("dir", "/project/a"), ("global", "/project/b")],
        ids=["per-dir-pause", "global-pause"],
    )
    def test_paused_still_tracks_project_dir(self, running_server, pause_mode, cwd):
        """Pause (dir or global) still updates _project_dir_last_seen (#1700)."""
        server, sock_path = running_server
        if pause_mode == "dir":
            server.state.pause_dir(cwd)
        else:
            server.state.pause()

        sock = _connect(sock_path)
        try:
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
                "_daemon_cwd": cwd,
            }
            sock.sendall(encode_message(make_hook_request(hook_data)))
            response = decode_message(sock, timeout=5.0)
            assert response["data"]["exit_code"] == 0
        finally:
            sock.close()

        assert cwd in server.state._project_dir_last_seen

    def test_status_includes_paused_dirs(self, running_server):
        server, sock_path = running_server
        server.state.pause_dir("/project/a")

        sock = _connect(sock_path)
        try:
            sock.sendall(encode_message(make_status_request()))
            response = decode_message(sock, timeout=2.0)
            stats = response["data"]
            assert "paused_dirs" in stats
            assert len(stats["paused_dirs"]) == 1
        finally:
            sock.close()


class TestDaemonStateAskDialog:
    """Tests for DaemonState ask dialog tracking (#1159)."""

    def test_record_ask_dialog_increments_count(self, short_state_dir):
        state = DaemonState(idle_timeout=0)
        state.record_ask_dialog(3000.0)
        state.record_ask_dialog(5000.0)
        stats = state.get_stats()
        assert stats["ask_dialog_count"] == 2
        assert stats["ask_dialog_total_ms"] == 8000.0

    def test_ask_dialog_stats_zero_by_default(self, short_state_dir):
        state = DaemonState(idle_timeout=0)
        stats = state.get_stats()
        assert stats["ask_dialog_count"] == 0
        assert stats["ask_dialog_total_ms"] == 0.0

    def test_ask_dialog_total_ms_rounded(self, short_state_dir):
        state = DaemonState(idle_timeout=0)
        state.record_ask_dialog(1234.5678)
        stats = state.get_stats()
        assert stats["ask_dialog_total_ms"] == 1234.6


class TestStartRestApiPortFallback:
    def test_port_fallback_on_oserrror(self, short_state_dir, monkeypatch):
        """_start_rest_api tries next port when configured port is in use."""
        server = DaemonServer(idle_timeout=5, enable_rest_api=False)
        server.state  # init state

        call_count = [0]

        class FakeAPI:
            def __init__(self, **kwargs):
                self.port = kwargs["port"]

            def start(self):
                call_count[0] += 1
                if self.port == 63152:
                    raise OSError("Address already in use")
                return self.port

        with mock.patch("ai_guardian.daemon.rest_api.DaemonRestAPI", FakeAPI):
            with mock.patch(
                "ai_guardian.config.loaders._load_config_file",
                return_value=(None, None),
            ):
                server._start_rest_api()

        assert server._rest_port == 63153
        assert call_count[0] == 2

    def test_port_fallback_logs_warning(self, short_state_dir, monkeypatch, caplog):
        """When fallback port used, a WARNING is logged."""
        import logging

        server = DaemonServer(idle_timeout=5, enable_rest_api=False)

        class FakeAPI:
            def __init__(self, **kwargs):
                self.port = kwargs["port"]

            def start(self):
                if self.port == 63152:
                    raise OSError("Address already in use")
                return self.port

        with mock.patch("ai_guardian.daemon.rest_api.DaemonRestAPI", FakeAPI):
            with mock.patch(
                "ai_guardian.config.loaders._load_config_file",
                return_value=(None, None),
            ):
                with caplog.at_level(
                    logging.WARNING, logger="ai_guardian.daemon.server"
                ):
                    server._start_rest_api()

        assert any("port 63152 in use" in r.message for r in caplog.records)

    def test_all_ports_exhausted_logs_warning(
        self, short_state_dir, monkeypatch, caplog
    ):
        """When all 10 ports fail, WARNING is logged and rest_port stays 0."""
        import logging

        server = DaemonServer(idle_timeout=5, enable_rest_api=False)

        class FakeAPI:
            def __init__(self, **kwargs):
                pass

            def start(self):
                raise OSError("Address already in use")

        with mock.patch("ai_guardian.daemon.rest_api.DaemonRestAPI", FakeAPI):
            with mock.patch(
                "ai_guardian.config.loaders._load_config_file",
                return_value=(None, None),
            ):
                with caplog.at_level(
                    logging.WARNING, logger="ai_guardian.daemon.server"
                ):
                    server._start_rest_api()

        assert server._rest_port == 0
        assert any("REST API failed to bind" in r.message for r in caplog.records)


class TestRestApiHostResolution:
    """REST API host resolution: config > env var > container detection > 127.0.0.1."""

    def _run_start_rest_api(self, server):
        """Call _start_rest_api and return the host passed to DaemonRestAPI."""
        captured = {}

        class FakeAPI:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def start(self):
                return captured["port"]

        with mock.patch("ai_guardian.daemon.rest_api.DaemonRestAPI", FakeAPI):
            server._start_rest_api()
        return captured.get("host")

    def test_default_host_is_localhost(self, short_state_dir, monkeypatch):
        monkeypatch.delenv("AI_GUARDIAN_REST_HOST", raising=False)
        server = DaemonServer(idle_timeout=5, enable_rest_api=False)
        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(None, None),
        ):
            with mock.patch("os.path.exists", return_value=False):
                host = self._run_start_rest_api(server)
        assert host == "127.0.0.1"

    def test_env_var_overrides_default(self, short_state_dir, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_REST_HOST", "0.0.0.0")
        server = DaemonServer(idle_timeout=5, enable_rest_api=False)
        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(None, None),
        ):
            with mock.patch("os.path.exists", return_value=False):
                host = self._run_start_rest_api(server)
        assert host == "0.0.0.0"

    def test_config_overrides_env_var(self, short_state_dir, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_REST_HOST", "0.0.0.0")
        server = DaemonServer(idle_timeout=5, enable_rest_api=False)
        cfg = {"daemon": {"rest_host": "10.0.0.1"}}
        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(cfg, None),
        ):
            with mock.patch("os.path.exists", return_value=False):
                host = self._run_start_rest_api(server)
        assert host == "10.0.0.1"

    def test_docker_container_detection(self, short_state_dir, monkeypatch):
        monkeypatch.delenv("AI_GUARDIAN_REST_HOST", raising=False)
        server = DaemonServer(idle_timeout=5, enable_rest_api=False)

        def fake_exists(p):
            return p == "/.dockerenv"

        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(None, None),
        ):
            with mock.patch("os.path.exists", fake_exists):
                host = self._run_start_rest_api(server)
        assert host == "0.0.0.0"

    def test_kubernetes_detection(self, short_state_dir, monkeypatch):
        monkeypatch.delenv("AI_GUARDIAN_REST_HOST", raising=False)
        server = DaemonServer(idle_timeout=5, enable_rest_api=False)

        def fake_exists(p):
            return p == "/var/run/secrets/kubernetes.io/serviceaccount"

        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(None, None),
        ):
            with mock.patch("os.path.exists", fake_exists):
                host = self._run_start_rest_api(server)
        assert host == "0.0.0.0"

    def test_env_var_with_container_detection(self, short_state_dir, monkeypatch):
        """Env var takes precedence over container auto-detection."""
        monkeypatch.setenv("AI_GUARDIAN_REST_HOST", "192.168.1.100")
        server = DaemonServer(idle_timeout=5, enable_rest_api=False)
        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(None, None),
        ):
            with mock.patch("os.path.exists", return_value=True):
                host = self._run_start_rest_api(server)
        assert host == "192.168.1.100"


class TestDaemonServerIdleTimeout:
    def test_idle_timeout_stops_server(self, short_state_dir, monkeypatch):
        server = DaemonServer(idle_timeout=0.5, enable_rest_api=False)

        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()

        _wait_server_ready(server)
        time.sleep(0.6)
        assert server.state.is_idle_timeout_expired()

        server.stop()
        thread.join(timeout=3)


class TestReloadConfigDetectorCache:
    """Regression tests for detector cache invalidation on config reload."""

    def test_reload_invalidates_cache_when_config_exists(self, short_state_dir):
        state = DaemonState(idle_timeout=0)
        config_path = state._config_path
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text('{"prompt_injection": {"enabled": true}}')
        with mock.patch(
            "ai_guardian.daemon.state.DaemonState._invalidate_detector_cache"
        ) as mock_inv:
            state._reload_config()
            mock_inv.assert_called_once()

    def test_reload_invalidates_cache_when_config_removed(self, short_state_dir):
        state = DaemonState(idle_timeout=0)
        with mock.patch(
            "ai_guardian.daemon.state.DaemonState._invalidate_detector_cache"
        ) as mock_inv:
            result = state._reload_config()
            assert result is False
            mock_inv.assert_called_once()

    def test_invalidate_detector_cache_logs_on_import_error(self):
        with mock.patch(
            "ai_guardian.scanners.prompt_injection.invalidate_detector_cache",
            side_effect=ImportError("test"),
        ):
            DaemonState._invalidate_detector_cache()
