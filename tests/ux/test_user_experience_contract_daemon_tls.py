"""HTTPS pairing UX: explicit independent trust, no learned pins or downgrade.

Manual verification:
1. Provision a VM certificate and CA over a verified administrative channel.
2. Keep the VM's REST listener bound to loopback and forward a local port.
3. Add an HTTPS manual target using that port and the certificate's SAN name.
4. Before installing the verified CA, observe the trust error and no API action.
5. Save independently verified CA/pin, refresh targets, and authenticate normally.
6. Test wrong identity, expired certificate and rotated leaf against the old pin.
7. Each failure must show the exact applicable message below, never learn trust,
   retry HTTP, disclose key/token material, or perform the requested API action.
8. Renew, independently verify and explicitly replace any pin; restart the daemon.
"""

import json
from unittest import mock

import pytest

from ai_guardian.daemon.discovery import DaemonDiscovery, DaemonTarget
from ai_guardian.daemon.multi_client import MultiDaemonClient
from tests.fixtures.daemon_tls import client_config, make_identity, serve_endpoint


@pytest.fixture(autouse=True)
def isolated_configuration():
    with mock.patch(
        "ai_guardian.config.loaders._load_config_file", return_value=({}, None)
    ):
        yield


@pytest.mark.parametrize(
    "failure,expected",
    [
        (
            "unpaired",
            "Daemon TLS certificate verification failed; check the trusted CA, certificate validity, and expected server identity. No daemon credentials were sent.",
        ),
        (
            "identity",
            "Daemon TLS server identity mismatch; check the expected server name against the certificate subject alternative names. No daemon credentials were sent.",
        ),
        (
            "pin",
            "Daemon certificate pin mismatch; independently verify the renewed certificate before updating the saved SHA-256 pin. No daemon credentials were sent.",
        ),
        (
            "expired",
            "Daemon TLS certificate has expired or is not yet valid; renew the certificate or check the system clock. No daemon credentials were sent.",
        ),
    ],
)
def test_user_sees_actionable_trust_failure_without_credentials_or_automatic_pairing(
    tmp_path, caplog, failure, expected
):
    """USER EXPERIENCE: unverified identity → no request, clear error, no changed trust."""
    ca = make_identity(tmp_path / "ca")
    leaf = make_identity(
        tmp_path / "leaf", issuer=ca["issuer"], days=-1 if failure == "expired" else 30
    )
    trust = {**client_config(leaf), "ca_file": ca["cert_file"]}
    if failure == "unpaired":
        trust = {"server_name": "daemon.test"}
    elif failure == "identity":
        trust["server_name"] = "different.test"
    elif failure == "pin":
        trust["certificate_sha256"] = "00" * 32
    original = dict(trust)
    with serve_endpoint(leaf) as endpoint:
        target = DaemonTarget(
            name="private-vm",
            runtime="manual",
            url=f"https://127.0.0.1:{endpoint.port}",
            auth_token="unit-sensitive-token",
            tls=trust,
        )
        assert (
            MultiDaemonClient._rest_request(target, "POST", "/api/resume", {}) is None
        )
        assert endpoint.requests == []
    assert target.error_message == expected
    assert expected in caplog.text
    assert target.tls == original
    assert "unit-sensitive-token" not in caplog.text


def test_user_can_pair_with_independently_verified_ca_and_identity_without_public_rest(
    tmp_path,
):
    """USER EXPERIENCE: verified private CA + remote identity through loopback → authenticated request."""
    identity = make_identity(tmp_path / "identity")
    with serve_endpoint(identity) as endpoint:
        target = DaemonTarget(
            name="vm",
            runtime="manual",
            url=f"https://127.0.0.1:{endpoint.port}",
            auth_token="unit-sensitive-token",
            tls=client_config(identity),
        )
        assert MultiDaemonClient._rest_request(target, "POST", "/api/resume", {}) == {}
        assert target.error_message is None
        assert endpoint.requests[0]["Authorization"] == "Bearer unit-sensitive-token"


def test_user_sees_storage_protection_error_instead_of_using_exposed_token(
    tmp_path, monkeypatch
):
    """USER EXPERIENCE: unsafe trust/token file → visible error target, no usable credentials."""
    import os

    if os.name == "nt":
        pytest.skip(
            "POSIX permission contract; Windows uses administrator-managed ACLs"
        )
    path = tmp_path / "targets.json"
    path.write_text(
        json.dumps(
            {
                "daemons": [
                    {
                        "name": "vm",
                        "url": "https://daemon.test",
                        "token": "unit-sensitive-token",
                    }
                ]
            }
        )
    )
    path.chmod(0o644)
    monkeypatch.setattr(
        "ai_guardian.daemon.discovery.get_tray_targets_path", lambda: path
    )
    target = DaemonDiscovery(config={}).discover_manual()[0]
    assert target.status == "error"
    assert (
        target.error_message
        == "Daemon target trust file has unsafe ownership or permissions; restrict it to the owning account before connecting."
    )
    assert target.url is None
    assert target.auth_token is None


def test_invalid_server_key_has_exact_safe_startup_error(caplog):
    """USER EXPERIENCE: missing/invalid key → no plaintext listener and no raw material in errors."""
    from ai_guardian.daemon.server import DaemonServer

    server = DaemonServer(enable_rest_api=False)
    config = {
        "daemon": {
            "rest_tls": {
                "enabled": True,
                "cert_file": "unit-sensitive-certificate-input",
                "key_file": "unit-sensitive-key-input",
            }
        }
    }
    with (
        mock.patch(
            "ai_guardian.config.loaders._load_config_file", return_value=(config, None)
        ),
        mock.patch.object(
            server, "_ensure_auth_token", return_value="unit-sensitive-token"
        ),
        mock.patch("ai_guardian.daemon.rest_api._ThreadedHTTPServer") as listener,
    ):
        server._start_rest_api()
    listener.assert_not_called()
    assert (
        "Daemon TLS configuration is invalid; check certificate, private key, and local file permissions. REST listener was not started."
        in caplog.text
    )
    assert "unit-sensitive" not in caplog.text


def test_exposed_existing_token_prevents_listener_start(caplog):
    """USER EXPERIENCE: exposed stored token → reject, never silently replace or drop authentication."""
    import os
    from ai_guardian.daemon import get_auth_token_path
    from ai_guardian.daemon.server import DaemonServer

    if os.name == "nt":
        pytest.skip("POSIX modes; Windows uses administrator-managed ACLs")
    token_path = get_auth_token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("unit-sensitive-token")
    token_path.chmod(0o644)
    server = DaemonServer(enable_rest_api=False)
    with mock.patch("ai_guardian.daemon.rest_api._ThreadedHTTPServer") as listener:
        server._start_rest_api()
    listener.assert_not_called()
    assert (
        "Daemon authentication token is unavailable or has unsafe permissions. REST listener was not started."
        in caplog.text
    )
    assert token_path.read_text() == "unit-sensitive-token"
    assert "unit-sensitive-token" not in caplog.text
