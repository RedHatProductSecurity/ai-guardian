"""Private storage and IPC-only startup UX (#2584).

Manual qualification on a disposable POSIX account, never the user's storage:
1. With umask 0002 and absent application storage, complete setup then start.
2. Inspect directory/file modes without displaying token or configuration contents.
3. Verify daemon status reports IPC running and REST available; pair using HTTPS.
4. Separately provision an existing 0775 ancestor. Setup must name that path and
   refuse to write config. Startup must not publish a token or start REST; if IPC
   starts, status must identify the unavailable listener and exact precondition.
5. Verify shared-directory modes/content stay unchanged. Missing config, unsafe
   metadata and a live process without REST must have distinct SSH pairing errors.

Automated tests isolate all storage/configuration and use loopback listeners only.
They do not qualify the reporter VM, live SSH, desktop rendering or Windows ACLs.
"""

import json
import os
import socket
import sys
import threading
from types import SimpleNamespace
from unittest import mock

import pytest

from ai_guardian.cli_handlers import _handle_daemon_command
from ai_guardian.daemon.protocol import (
    decode_message,
    encode_message,
    make_status_request,
)
from ai_guardian.daemon.server import DaemonServer
from ai_guardian.setup.config import create_default_config


@pytest.fixture(autouse=True)
def isolated_configuration():
    with mock.patch(
        "ai_guardian.config.loaders._load_config_file", return_value=({}, None)
    ):
        yield


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX storage modes")
def test_setup_names_existing_writable_ancestor_without_changing_it(
    tmp_path, monkeypatch
):
    """USER EXPERIENCE: unsafe existing XDG parent → exact path/mode, no repair."""
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o775)
    shared.chmod(0o775)
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(shared / "ai-guardian"))
    success, message = create_default_config()
    assert not success
    assert message == (
        f"Error creating default config: Application storage {str(shared)!r}: "
        "group/other-writable directory (mode 0775)"
    )
    assert not (shared / "ai-guardian.json").exists()
    assert shared.stat().st_mode & 0o777 == 0o775


@pytest.mark.parametrize(
    "stats,expected",
    [
        (
            {"rest_status": "available", "rest_port": 12345},
            "REST API: available (port 12345)",
        ),
        (
            {
                "rest_status": "unavailable",
                "rest_error": "Storage precondition not satisfied",
            },
            "REST API: unavailable",
        ),
        ({"rest_status": "disabled"}, "REST API: disabled"),
        ({}, "REST API: unknown (older daemon)"),
    ],
)
def test_status_separates_ipc_liveness_from_rest_readiness(stats, expected, capsys):
    """USER EXPERIENCE: running IPC alone is not advertised as a working REST API."""
    with (
        mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True),
        mock.patch(
            "ai_guardian.daemon.client.send_status_request",
            return_value={"request_count": 1, **stats},
        ),
        mock.patch("ai_guardian.cli_handlers._get_client_timeout", return_value=2),
    ):
        assert _handle_daemon_command(SimpleNamespace(daemon_command="status")) == 0
    output = capsys.readouterr().out
    assert "IPC: running" in output
    assert expected in output
    if stats.get("rest_error"):
        assert "REST startup: Storage precondition not satisfied" in output


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX storage modes")
@pytest.mark.parametrize("unsafe", [False, True])
def test_actual_startup_publishes_truthful_ipc_and_pid_status(
    tmp_path, monkeypatch, capsys, unsafe
):
    """USER EXPERIENCE: IPC works even when REST fails, and reports the safe reason."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    if unsafe:
        state.chmod(0o775)
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(state))
    monkeypatch.delenv("AI_GUARDIAN_REST_PORT", raising=False)
    config = {"daemon": {"rest_host": "127.0.0.1", "rest_port": 0}}
    server = DaemonServer(use_tcp=True)
    errors = []

    def start():
        try:
            server.start()
        except Exception as error:
            errors.append(type(error).__name__)

    with (
        mock.patch(
            "ai_guardian.config.loaders._load_config_file", return_value=(config, None)
        ),
        mock.patch.object(server.state, "get_stats", return_value={"request_count": 0}),
    ):
        thread = threading.Thread(target=start, daemon=True)
        thread.start()
        try:
            assert server._ready_event.wait(timeout=5), errors
            with socket.create_connection(
                ("127.0.0.1", server._tcp_port), timeout=2
            ) as client:
                client.sendall(encode_message(make_status_request()))
                status = decode_message(client, timeout=2)["data"]
            metadata = json.loads((state / "daemon.pid").read_text())
            assert metadata["pid"] == os.getpid()
            assert (
                status["rest_status"]
                == metadata["rest_status"]
                == ("unavailable" if unsafe else "available")
            )
            assert "unit-sensitive-token" not in json.dumps(status)
            if unsafe:
                expected = (
                    f"Application storage {str(state)!r}: group/other-writable directory "
                    "(mode 0775). REST listener was not started."
                )
                assert status["rest_error"] == metadata["rest_error"] == expected
                assert (
                    f"IPC: running; REST API: unavailable — {expected}"
                    in capsys.readouterr().out
                )
                assert not (state / "daemon.token").exists()
                assert server._rest_api is None
            else:
                assert status["rest_port"] == server._rest_port > 0
                assert status["rest_error"] == ""
                assert (state / "daemon.token").stat().st_mode & 0o777 == 0o600
        finally:
            server.stop()
            thread.join(timeout=3)
    assert not errors
    assert not thread.is_alive()
