"""SSH process ownership, bounded probes, TLS identity and port reuse races."""

from dataclasses import replace
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock

import pytest

from ai_guardian.daemon.rest_transport import DaemonConnectionError, TLSOptions
from ai_guardian.daemon.ssh_probe import PROBE_SCRIPT
from ai_guardian.daemon.ssh_storage import SSHConnectionError, SSHStore
from ai_guardian.daemon.ssh_tunnel import (
    HTTPS_REQUIRED,
    METADATA_ERROR,
    OFFLINE_ERROR,
    SSH_ERROR,
    SSH_MISSING,
    STOPPED_ERROR,
    SSHPairing,
    SSHTunnel,
    probe_destination,
    ssh_command,
)
from tests.fixtures.daemon_tls import make_identity, serve_endpoint
from tests.fixtures.ssh_daemon import make_pairing


@pytest.fixture
def sample(tmp_path):
    return make_pairing(tmp_path)


def test_system_ssh_uses_config_agent_and_strict_keys():
    with mock.patch("shutil.which", return_value="/usr/bin/ssh"):
        args, host = ssh_command("user@alias")
    assert host == "user@alias"
    for option in (
        "BatchMode=yes",
        "StrictHostKeyChecking=yes",
        "UpdateHostKeys=no",
        "ControlPath=none",
        "ForkAfterAuthentication=no",
        "StdinNull=no",
        "ForwardAgent=no",
        "GatewayPorts=no",
    ):
        assert option in args
    assert "-F" not in args  # Do not discard the user's configured aliases/agent.
    with (
        mock.patch("shutil.which", return_value=None),
        pytest.raises(SSHConnectionError) as error,
    ):
        ssh_command("alias")
    assert str(error.value) == SSH_MISSING


def test_probe_uses_fixed_stdin_and_never_echoes_output(sample):
    pairing, metadata, _ = sample

    def run(args, **kwargs):
        assert args[-3:] == ["--", pairing.profile.destination, "python3 -"]
        assert "ClearAllForwardings=yes" in args
        process = mock.Mock(returncode=0)
        process.poll.return_value = 0

        def communicate(data, *, timeout):
            assert data == PROBE_SCRIPT.encode()
            assert timeout == 10
            kwargs["stdout"].write(json.dumps(metadata).encode())

        process.communicate.side_effect = communicate
        return process

    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch("subprocess.Popen", side_effect=run),
    ):
        assert probe_destination(pairing.profile.destination) == pairing


@pytest.mark.parametrize(
    "failure", ["exit", "timeout", "missing", "invalid", "oversize", "deep_json"]
)
def test_probe_errors_are_bounded_and_credential_free(failure, sample):
    pairing, _, _ = sample

    def run(_args, **kwargs):
        if failure == "missing":
            raise OSError(pairing.profile.token)
        kwargs["stdout"].write(
            b"[" * 10000 + b"]" * 10000
            if failure == "deep_json"
            else b"x" * (524289 if failure == "oversize" else 5)
        )
        process = mock.Mock(returncode=1 if failure == "exit" else 0)
        process.poll.return_value = None if failure == "timeout" else process.returncode
        if failure == "timeout":
            process.communicate.side_effect = subprocess.TimeoutExpired(
                "private-command", 10, output=pairing.profile.token
            )
        return process

    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch("subprocess.Popen", side_effect=run),
        pytest.raises(SSHConnectionError) as error,
    ):
        probe_destination("alias")
    assert str(error.value) == (
        METADATA_ERROR if failure in {"invalid", "oversize", "deep_json"} else SSH_ERROR
    )
    assert pairing.profile.token not in str(error.value)


def test_probe_registers_owned_process_and_reaps_it_on_timeout():
    process = mock.Mock()
    process.poll.return_value = None
    process.communicate.side_effect = subprocess.TimeoutExpired("ssh", 10)
    on_process = mock.Mock()
    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch("subprocess.Popen", return_value=process),
        pytest.raises(SSHConnectionError),
    ):
        probe_destination("alias", on_process=on_process)
    assert on_process.call_args_list == [
        mock.call(process, True),
        mock.call(process, False),
    ]
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=1)


def test_closed_generation_cannot_start_a_new_ssh_process(tmp_path, sample):
    tunnel = SSHTunnel(sample[0], SSHStore(tmp_path / "connections"))
    tunnel.close()
    with (
        mock.patch("subprocess.Popen") as process,
        pytest.raises(SSHConnectionError) as error,
    ):
        tunnel.start()
    assert str(error.value) == OFFLINE_ERROR
    process.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"port": True},
        {"port": 0},
        {"port": 65536},
        {"host": "0.0.0.0"},
        {"host": "public.example"},
        {"version": True},
        {"version": 2},
        {"name": "bad\nname"},
        {"certificate": "invalid"},
        {"ca_pem": "invalid"},
        {"token": "bad\rheader"},
        {"server_name": "https://other"},
    ],
)
def test_remote_metadata_is_untrusted(sample, changes):
    _, metadata, _ = sample
    with pytest.raises(ValueError):
        SSHPairing.from_metadata("alias", {**metadata, **changes})


@pytest.mark.parametrize(
    "status,message",
    [
        ("https_required", HTTPS_REQUIRED),
        ("stopped", STOPPED_ERROR),
        ("unavailable", METADATA_ERROR),
    ],
)
def test_remote_states_do_not_assume_default_port(status, message):
    with pytest.raises(SSHConnectionError) as error:
        SSHPairing.from_metadata("alias", {"status": status})
    assert str(error.value) == message


def test_bootstrap_retains_only_certificate_blocks_and_literal_loopback(sample):
    pairing, metadata, _ = sample
    metadata["ca_pem"] += "\ncomment that must not be saved as certificate material\n"
    metadata["host"] = "localhost"
    result = SSHPairing.from_metadata("alias", metadata)
    assert result.profile.ca_pem == pairing.profile.ca_pem
    assert result.host == "127.0.0.1"


def test_rest_read_has_a_total_deadline_not_only_an_idle_timeout(tmp_path, sample):
    tunnel = SSHTunnel(sample[0], SSHStore(tmp_path / "connections"))
    tunnel.port = 12345
    tunnel.process = mock.Mock()
    tunnel.process.poll.return_value = None
    response = mock.MagicMock()
    response.__enter__.return_value.read1.return_value = b" "
    with (
        mock.patch(
            "ai_guardian.daemon.ssh_tunnel.open_daemon_request", return_value=response
        ),
        mock.patch(
            "ai_guardian.daemon.ssh_tunnel.time.monotonic", side_effect=[0, 1, 6]
        ),
        pytest.raises(SSHConnectionError),
    ):
        tunnel.request("GET", "/api/stats")
    assert response.__enter__.return_value.read1.call_count == 1
    tunnel.close()


def test_close_interrupts_transport_before_waiting_for_request_lock(tmp_path, sample):
    tunnel = SSHTunnel(sample[0], SSHStore(tmp_path / "connections"))
    process = mock.Mock()
    process.poll.return_value = None
    tunnel.process = process
    lock = mock.MagicMock()
    lock.__enter__.side_effect = lambda: process.terminate.assert_called_once()
    tunnel._lock = lock
    tunnel.close()
    assert not tunnel.active


@pytest.mark.parametrize("failure", ["incomplete", "deep_json"])
def test_malformed_response_is_a_safe_actionable_error(tmp_path, sample, failure):
    from ai_guardian.daemon.ssh_tunnel import REQUEST_ERROR

    tunnel = SSHTunnel(sample[0], SSHStore(tmp_path / "connections"))
    tunnel.port = 12345
    tunnel.process = mock.Mock()
    tunnel.process.poll.return_value = None
    response = mock.MagicMock()
    if failure == "incomplete":
        response.__enter__.return_value.read1.side_effect = http.client.IncompleteRead(
            sample[0].profile.token.encode()
        )
    else:
        response.__enter__.return_value.read1.side_effect = [
            b"[" * 10000 + b"]" * 10000,
            b"",
        ]
    try:
        with (
            mock.patch(
                "ai_guardian.daemon.ssh_tunnel.open_daemon_request",
                return_value=response,
            ),
            pytest.raises(SSHConnectionError) as error,
        ):
            tunnel.request("GET", "/api/stats")
        assert str(error.value) == REQUEST_ERROR
        assert sample[0].profile.token not in str(error.value)
    finally:
        tunnel.close()


def test_san_identity_can_be_bootstrapped_without_client_fields(sample):
    _, metadata, _ = sample
    metadata.pop("server_name")
    assert (
        SSHPairing.from_metadata("alias", metadata).profile.server_name == "daemon.test"
    )


def test_tunnel_readiness_is_unauthenticated_and_loopback_only(tmp_path, sample):
    pairing, _, _ = sample
    store = SSHStore(tmp_path / "connections")
    process = mock.Mock()
    process.poll.return_value = None
    response = mock.MagicMock()
    response.__enter__.return_value.read1.side_effect = [b'{"status":"ok"}', b""]
    tunnel = SSHTunnel(pairing, store)
    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch("subprocess.Popen", return_value=process) as popen,
        mock.patch(
            "ai_guardian.daemon.ssh_tunnel.open_daemon_request", return_value=response
        ) as request,
    ):
        tunnel.start()
        args = popen.call_args.args[0]
        assert (
            args[args.index("-L") + 1]
            == f"127.0.0.1:{tunnel.port}:127.0.0.1:{pairing.port}"
        )
        assert "ExitOnForwardFailure=yes" in args
        assert pairing.profile.token not in repr(args)
        assert request.call_args.args[0].get_header("Authorization") is None
        assert request.call_args.kwargs["tls"].server_name == "daemon.test"
        ca = Path(tunnel.tls.ca_file)
        assert ca.exists()
        tunnel.close()
        assert not ca.exists()
    process.terminate.assert_called_once()


def test_occupied_port_process_failure_never_sends_credentials(tmp_path, sample):
    pairing, _, _ = sample
    process = mock.Mock()
    process.poll.return_value = 255
    tunnel = SSHTunnel(pairing, SSHStore(tmp_path / "connections"))
    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch("subprocess.Popen", return_value=process),
        mock.patch("ai_guardian.daemon.ssh_tunnel.open_daemon_request") as request,
        pytest.raises(SSHConnectionError),
    ):
        tunnel.start()
    request.assert_not_called()
    process.terminate.assert_not_called()  # Never kill an unrelated listener.


@pytest.mark.parametrize("race", ["dead", "unrelated_tls", "plaintext", "removed"])
def test_reused_local_port_never_receives_credentials(tmp_path, sample, race):
    pairing, _, identity = sample
    store = SSHStore(tmp_path / "connections")
    store.create(pairing.profile)
    other = make_identity(tmp_path / "unrelated")
    with serve_endpoint(None if race == "plaintext" else other) as server:
        tunnel = SSHTunnel(pairing, store, saved=True)
        tunnel.port = server.port
        tunnel.tls = TLSOptions(
            identity["ca_file"],
            pairing.profile.server_name,
            pairing.profile.certificate_sha256,
        )
        tunnel.process = mock.Mock()
        tunnel.process.poll.return_value = 255 if race == "dead" else None
        if race == "removed":
            store.remove(pairing.profile.id)
        try:
            with pytest.raises((SSHConnectionError, DaemonConnectionError)):
                tunnel.request("GET", "/api/stats", timeout=0.5)
            assert server.requests == []
        finally:
            tunnel.close()


def test_valid_tls_and_auth_use_same_socket(tmp_path, sample):
    pairing, _, identity = sample
    store = SSHStore(tmp_path / "connections")
    store.create(pairing.profile)
    with serve_endpoint(identity) as server:
        tunnel = SSHTunnel(pairing, store, saved=True)
        tunnel.port = server.port
        tunnel.process = mock.Mock()
        tunnel.process.poll.return_value = None
        tunnel.tls = TLSOptions(
            identity["ca_file"], "daemon.test", pairing.profile.certificate_sha256
        )
        try:
            assert tunnel.request("GET", "/api/stats") == {}
            assert (
                server.requests[0]["Authorization"] == f"Bearer {pairing.profile.token}"
            )
            tunnel.process.poll.return_value = 255
            with pytest.raises(SSHConnectionError) as error:
                tunnel.request("POST", "/api/resume")
            assert str(error.value) == OFFLINE_ERROR
            assert len(server.requests) == 1
        finally:
            tunnel.close()


def test_close_only_owned_process_escalates_once(tmp_path, sample):
    tunnel = SSHTunnel(sample[0], SSHStore(tmp_path))
    process = mock.Mock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("ssh", 1), 0]
    tunnel.process = process
    tunnel.close()
    tunnel.close()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()


@pytest.mark.skipif(
    sys.platform == "win32", reason="The remote probe targets POSIX SSH hosts"
)
@pytest.mark.parametrize(
    "state", ["running", "stopped", "legacy", "wrong_owner_material"]
)
def test_fixed_remote_probe_reads_actual_runtime_metadata(tmp_path, sample, state):
    pairing, _, identity = sample
    config = tmp_path / "config"
    runtime = tmp_path / "state"
    config.mkdir()
    runtime.mkdir()
    config_file = config / "ai-guardian.json"
    config_file.write_text(
        json.dumps(
            {
                "daemon": {
                    "rest_host": "127.0.0.1",
                    "rest_tls": {
                        "enabled": True,
                        "cert_file": identity["cert_file"],
                        "client": {
                            "ca_file": identity["ca_file"],
                            "server_name": "daemon.test",
                        },
                    },
                }
            }
        )
    )
    (runtime / "daemon.pid").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "rest_port": 45678,
                "name": "test",
                **({} if state == "legacy" else {"rest_scheme": "https"}),
            }
        )
    )
    token = runtime / "daemon.token"
    token.write_text(pairing.profile.token)
    token.chmod(0o644 if state == "wrong_owner_material" else 0o600)
    if state == "stopped":
        (runtime / "daemon.pid").unlink()
    env = {
        **os.environ,
        "AI_GUARDIAN_CONFIG_DIR": str(config),
        "AI_GUARDIAN_STATE_DIR": str(runtime),
    }
    result = subprocess.run(
        [sys.executable, "-"],
        input=PROBE_SCRIPT,
        text=True,
        capture_output=True,
        env=env,
        timeout=5,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    data = json.loads(result.stdout)
    if state == "running":
        assert data["port"] == 45678
        assert data["token"] == pairing.profile.token
    else:
        assert data == {
            "status": {
                "stopped": "stopped",
                "legacy": "https_required",
                "wrong_owner_material": "unavailable",
            }[state]
        }
