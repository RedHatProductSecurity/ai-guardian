"""Real loopback TLS unit tests: verify identity before transmitting HTTP data."""

import json
import logging
import os
import ssl
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from ai_guardian.daemon.rest_api import DaemonRestAPI
from ai_guardian.daemon.rest_transport import (
    DaemonConnectionError,
    TLSOptions,
    create_server_context,
    open_daemon_request,
)
from tests.fixtures.daemon_tls import (
    client_config,
    listener_config,
    make_identity,
    serve_endpoint,
)


@pytest.fixture
def identity(tmp_path):
    return make_identity(tmp_path / "identity")


@pytest.fixture
def tls_api(identity):
    state = mock.Mock()
    state.get_stats.return_value = {"paused": False}
    state.get_config.return_value = {}
    state.get_pause_status.return_value = {}
    api = DaemonRestAPI(
        state, auth_token="unit-only-token", tls=listener_config(identity)
    )
    api.start()
    yield api, state
    api.stop()


def test_https_auth_and_separate_identity(tls_api, identity):
    api, state = tls_api
    request = Request(
        f"https://127.0.0.1:{api.port}/api/resume", data=b"", method="POST"
    )
    options = TLSOptions.from_config(client_config(identity))
    with pytest.raises(HTTPError) as error:
        open_daemon_request(request, tls=options)
    assert error.value.code == 401
    error.value.close()
    state.resume.assert_not_called()
    request.add_header("Authorization", "Bearer unit-only-token")
    with open_daemon_request(request, tls=options) as response:
        assert json.load(response)["status"] == "resumed"
    state.resume.assert_called_once()


@pytest.mark.parametrize("failure", ["ca", "identity", "pin"])
def test_unverified_endpoint_receives_no_http_credentials(
    tls_api, identity, tmp_path, failure
):
    api, state = tls_api
    config = client_config(identity)
    if failure == "ca":
        config["ca_file"] = make_identity(tmp_path / "other")["cert_file"]
    elif failure == "identity":
        config["server_name"] = "other.test"
    else:
        config["certificate_sha256"] = "00" * 32
    request = Request(
        f"https://127.0.0.1:{api.port}/api/resume", data=b"", method="POST"
    )
    request.add_header("Authorization", "Bearer unit-only-token")
    with pytest.raises(DaemonConnectionError, match="No daemon credentials were sent"):
        open_daemon_request(request, tls=TLSOptions.from_config(config))
    state.resume.assert_not_called()


@pytest.mark.parametrize("config", [{"enabled": True}, {"enabled": "false"}, []])
def test_invalid_server_configuration_does_not_bind(config):
    api = DaemonRestAPI(mock.Mock(), tls=config)
    with mock.patch("ai_guardian.daemon.rest_api._ThreadedHTTPServer") as server:
        with pytest.raises(DaemonConnectionError):
            api.start()
        server.assert_not_called()
    assert api.port == 0


def test_expired_server_certificate_is_rejected_before_bind(tmp_path):
    identity = make_identity(tmp_path / "expired", days=-1)
    with pytest.raises(DaemonConnectionError, match="expired"):
        create_server_context(listener_config(identity))


def test_mismatched_key_and_certificate_are_rejected(identity, tmp_path):
    other = make_identity(tmp_path / "other")
    config = listener_config(identity)
    config["key_file"] = other["key_file"]
    with pytest.raises(DaemonConnectionError):
        create_server_context(config)


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX modes; Windows uses administrator-managed ACLs"
)
def test_private_key_permissions(identity):
    from pathlib import Path

    Path(identity["key_file"]).chmod(0o644)
    with pytest.raises(DaemonConnectionError, match="permissions"):
        create_server_context(listener_config(identity))


def test_tls_context_minimum_version(identity):
    context = create_server_context(listener_config(identity))
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert (
        context.verify_mode == ssl.CERT_NONE
    )  # Server TLS does not implicitly enable mTLS.


def test_pin_never_replaces_ca_validation(tls_api, identity):
    api, state = tls_api
    config = client_config(identity)
    config["ca_file"] = ""
    with pytest.raises(DaemonConnectionError, match="certificate verification failed"):
        open_daemon_request(
            Request(f"https://127.0.0.1:{api.port}/api/health"),
            tls=TLSOptions.from_config(config),
        )


def test_tls_configuration_on_http_is_rejected(identity):
    with pytest.raises(DaemonConnectionError, match="requires HTTPS"):
        open_daemon_request(
            Request("http://127.0.0.1:1/api/health"),
            tls=TLSOptions.from_config(client_config(identity)),
        )


@pytest.mark.parametrize(
    "config",
    [
        {"certificate_sha256": "bad"},
        {"server_name": "https://host"},
        {"ca_file": False},
        {"unknown": True},
    ],
)
def test_invalid_client_options(config):
    with pytest.raises(DaemonConnectionError):
        TLSOptions.from_config(config)


def test_server_certificate_expiry_warning(identity, caplog):
    with caplog.at_level(logging.WARNING):
        create_server_context(listener_config(identity))
    assert "expires within 30 days" in caplog.text


def test_plain_http_defaults_still_work():
    api = DaemonRestAPI(None)
    try:
        api.start()
        with open_daemon_request(
            Request(f"http://127.0.0.1:{api.port}/api/health")
        ) as response:
            assert json.load(response)["status"] == "ok"
    finally:
        api.stop()


@pytest.mark.parametrize("starts,days", [(-2, -1), (1, 30)])
def test_client_rejects_expired_and_future_certificates(tmp_path, starts, days):
    ca = make_identity(tmp_path / "ca")
    leaf = make_identity(
        tmp_path / "leaf", starts=starts, days=days, issuer=ca["issuer"]
    )
    options = TLSOptions.from_config(
        {**client_config(leaf), "ca_file": ca["cert_file"]}
    )
    with serve_endpoint(leaf) as server:
        request = Request(
            f"https://127.0.0.1:{server.port}/api/health",
            headers={"Authorization": "Bearer unit-only-token"},
        )
        with pytest.raises(DaemonConnectionError, match="expired or is not yet valid"):
            open_daemon_request(request, tls=options)
        assert server.requests == []


def test_ca_signed_identity_and_explicitly_verified_pin(identity, tmp_path):
    leaf = make_identity(tmp_path / "leaf", issuer=identity["issuer"])
    options = TLSOptions.from_config(
        {**client_config(leaf), "ca_file": identity["ca_file"]}
    )
    with serve_endpoint(leaf) as server:
        with open_daemon_request(
            Request(f"https://127.0.0.1:{server.port}/api/health"), tls=options
        ):
            pass
        assert len(server.requests) == 1


@pytest.mark.parametrize("redirect_scheme", ["http", "https"])
def test_redirect_never_forwards_credentials(identity, redirect_scheme):
    with serve_endpoint(
        identity if redirect_scheme == "https" else None
    ) as destination:
        url = f"{redirect_scheme}://127.0.0.1:{destination.port}/api/health"
        with serve_endpoint(identity, redirect=url) as source:
            request = Request(
                f"https://127.0.0.1:{source.port}/api/health",
                headers={
                    "Authorization": "Bearer unit-only-token",
                    "X-AI-Guardian-Token": "unit-only-token",
                },
            )
            with pytest.raises(
                DaemonConnectionError, match="redirects are not allowed"
            ):
                open_daemon_request(
                    request, tls=TLSOptions.from_config(client_config(identity))
                )
            assert source.requests[0]["Authorization"] == "Bearer unit-only-token"
            assert destination.requests == []


def test_environment_proxy_is_never_used(identity, monkeypatch):
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("no_proxy", "")
    with serve_endpoint(identity) as server:
        with open_daemon_request(
            Request(f"https://127.0.0.1:{server.port}/api/health"),
            tls=TLSOptions.from_config(client_config(identity)),
        ):
            pass
        assert len(server.requests) == 1


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX modes; Windows requires protected ACLs"
)
@pytest.mark.parametrize("material", ["file", "directory"])
def test_untrusted_ca_storage_is_rejected_before_network(identity, material):
    from pathlib import Path

    path = Path(identity["ca_file"])
    (path if material == "file" else path.parent).chmod(
        0o666 if material == "file" else 0o777
    )
    with mock.patch("socket.create_connection") as connect:
        with pytest.raises(DaemonConnectionError, match="local file permissions"):
            open_daemon_request(
                Request("https://127.0.0.1:1/api/health"),
                tls=TLSOptions.from_config(client_config(identity)),
            )
    connect.assert_not_called()


def test_remote_hook_client_uses_same_verified_tunnel_identity(identity, monkeypatch):
    from ai_guardian.daemon.client import _is_daemon_running_remote, _send_remote

    with serve_endpoint(identity) as server:
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_URL", f"https://127.0.0.1:{server.port}")
        monkeypatch.setenv("AI_GUARDIAN_AUTH_TOKEN", "unit-only-token")
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_CA_FILE", identity["ca_file"])
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_SERVER_NAME", identity["server_name"])
        monkeypatch.setenv(
            "AI_GUARDIAN_DAEMON_CERT_SHA256", identity["certificate_sha256"]
        )
        assert _send_remote("/api/hook", {"sample": "safe"}) == {}
        assert server.requests[0]["Authorization"] == "Bearer unit-only-token"
        monkeypatch.setenv("AI_GUARDIAN_DAEMON_CERT_SHA256", "00" * 32)
        assert _send_remote("/api/hook", {}) is None
        assert _is_daemon_running_remote() is False
        assert len(server.requests) == 1


def test_local_client_reads_running_scheme_and_private_token(
    tls_api, identity, monkeypatch
):
    from ai_guardian.daemon import get_auth_token_path
    from ai_guardian.daemon.rest_transport import local_daemon_request

    api, state = tls_api
    token_file = get_auth_token_path()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("unit-only-token")
    token_file.chmod(0o600)
    config = {"daemon": {"rest_tls": {"client": client_config(identity)}}}
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_config_file", lambda: (config, None)
    )
    with local_daemon_request(
        "/api/resume", data={}, pid_info={"rest_port": api.port, "rest_scheme": "https"}
    ) as response:
        assert json.load(response)["status"] == "resumed"
    state.resume.assert_called_once()


def test_renewal_requires_restart_and_explicit_pin_update(tmp_path):
    from pathlib import Path

    ca = make_identity(tmp_path / "ca")
    leaf = make_identity(tmp_path / "first", issuer=ca["issuer"])
    renewed = make_identity(tmp_path / "renewed", issuer=ca["issuer"])
    config = client_config(leaf)
    config["ca_file"] = ca["cert_file"]
    options = TLSOptions.from_config(config)
    state = mock.Mock()
    state.get_stats.return_value = {}
    state.get_pause_status.return_value = {}
    api = DaemonRestAPI(state, tls=listener_config(leaf))
    try:
        api.start()
        Path(leaf["cert_file"]).write_bytes(Path(renewed["cert_file"]).read_bytes())
        Path(leaf["key_file"]).write_bytes(Path(renewed["key_file"]).read_bytes())
        with open_daemon_request(
            Request(f"https://127.0.0.1:{api.port}/api/reload", data=b""), tls=options
        ):
            pass
        state.force_reload_config.assert_called_once()
        # Neither replacing files nor reloading config replaces the live identity.
        with open_daemon_request(
            Request(f"https://127.0.0.1:{api.port}/api/health"), tls=options
        ):
            pass
        api.stop()
        api.start()
        with pytest.raises(DaemonConnectionError, match="pin mismatch"):
            open_daemon_request(
                Request(f"https://127.0.0.1:{api.port}/api/health"), tls=options
            )
        config["certificate_sha256"] = renewed["certificate_sha256"]
        with open_daemon_request(
            Request(f"https://127.0.0.1:{api.port}/api/health"),
            tls=TLSOptions.from_config(config),
        ):
            pass
    finally:
        api.stop()


def test_common_name_without_san_is_not_a_verified_identity(tmp_path):
    identity = make_identity(tmp_path / "cn_only", san=False)
    with serve_endpoint(identity) as endpoint:
        with pytest.raises(DaemonConnectionError, match="server identity mismatch"):
            open_daemon_request(
                Request(f"https://127.0.0.1:{endpoint.port}/api/health"),
                tls=TLSOptions.from_config(client_config(identity)),
            )
        assert endpoint.requests == []


@pytest.mark.parametrize("config", [None, {"client": None}])
def test_malformed_local_tls_trust_fails_before_request(config, monkeypatch):
    from ai_guardian.daemon.rest_transport import local_daemon_request

    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_config_file",
        lambda: ({"daemon": {"rest_tls": config}}, None),
    )
    with mock.patch("socket.create_connection") as connect:
        with pytest.raises(
            DaemonConnectionError, match="trust configuration is invalid"
        ):
            local_daemon_request(
                "/api/health", pid_info={"rest_scheme": "https", "rest_port": 1}
            )
    connect.assert_not_called()


def test_rest_request_logs_do_not_echo_tokens_in_urls(tls_api, identity, caplog):
    api, _state = tls_api
    request = Request(
        f"https://127.0.0.1:{api.port}/not-found?token=unit-sensitive-token",
        headers={"Authorization": "Bearer unit-only-token"},
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(HTTPError) as error:
        open_daemon_request(
            request, tls=TLSOptions.from_config(client_config(identity))
        )
    assert error.value.code == 404
    error.value.close()
    assert "unit-sensitive-token" not in caplog.text
    assert "unit-only-token" not in caplog.text


def test_explicit_request_proxy_is_rejected_before_network():
    request = Request("https://daemon.test/api/health")
    request.set_proxy("127.0.0.1:1", "https")
    with mock.patch("socket.create_connection") as connect:
        with pytest.raises(
            DaemonConnectionError, match="proxy connections are not allowed"
        ):
            open_daemon_request(request)
    connect.assert_not_called()
