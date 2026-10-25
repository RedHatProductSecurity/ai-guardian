"""TLS config surfaces stay synchronized and listener startup fails closed."""

import json
from pathlib import Path
from unittest import mock

import jsonschema
import pytest

from ai_guardian.daemon.discovery import DaemonDiscovery
from ai_guardian.daemon.server import DaemonServer
from ai_guardian.setup.config import _get_default_config_template
from tests.fixtures.daemon_tls import client_config, listener_config, make_identity

ROOT = Path(__file__).resolve().parents[2]


def clean_comments(value):
    return (
        {
            key: clean_comments(item)
            for key, item in value.items()
            if not key.startswith("_comment")
        }
        if isinstance(value, dict)
        else value
    )


def test_schema_setup_and_example_have_identical_tls_defaults():
    schema = json.loads(
        (ROOT / "src/ai_guardian/schemas/ai-guardian-config.schema.json").read_text()
    )
    tls_schema = schema["definitions"]["daemon"]["properties"]["rest_tls"]
    # Validate the actual documented configurations, including comment metadata.
    # Stripping comments first would hide invalid setup/example output.
    setup_tls = _get_default_config_template()["daemon"]["rest_tls"]
    example_tls = json.loads((ROOT / "ai-guardian-example.json").read_text())["daemon"][
        "rest_tls"
    ]
    jsonschema.validate(setup_tls, tls_schema)
    jsonschema.validate(example_tls, tls_schema)
    example = clean_comments(example_tls)
    default = clean_comments(setup_tls)
    assert (
        default
        == example
        == {
            "enabled": False,
            "cert_file": "",
            "key_file": "",
            "client": {"ca_file": "", "server_name": "", "certificate_sha256": ""},
        }
    )
    jsonschema.validate(default, tls_schema)
    for key in ("enabled", "cert_file", "key_file"):
        assert tls_schema["properties"][key]["default"] == default[key]
    for key, value in default["client"].items():
        assert tls_schema["properties"]["client"]["properties"][key]["default"] == value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"enabled": True}, tls_schema)
    for invalid in ({"unknown": True}, {"client": {"unknown": True}}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, tls_schema)


def test_setup_create_config_output_contains_disabled_tls_defaults():
    from ai_guardian.setup.config import create_default_config

    success, rendered = create_default_config(json_output=True)
    assert success
    tls = json.loads(rendered)["daemon"]["rest_tls"]
    assert tls["enabled"] is False
    assert set(tls["client"]) == {"ca_file", "server_name", "certificate_sha256"}


@pytest.mark.parametrize(
    "tls",
    [
        None,
        [],
        {"enabled": "false"},
        {"enabled": True},
        {"enabled": True, "unknown": True},
    ],
)
def test_invalid_tls_never_binds_or_retries_plaintext(tls, caplog):
    server = DaemonServer(enable_rest_api=False)
    with (
        mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=({"daemon": {"rest_tls": tls}}, None),
        ),
        mock.patch.object(server, "_ensure_auth_token", return_value="unit-only-token"),
        mock.patch("ai_guardian.daemon.rest_api._ThreadedHTTPServer") as listener,
    ):
        server._start_rest_api()
    assert server._rest_port == 0
    listener.assert_not_called()
    assert "REST listener was not started" in caplog.text
    assert "unit-only-token" not in caplog.text


def test_config_read_error_cannot_start_plaintext_fallback(caplog):
    server = DaemonServer(enable_rest_api=False)
    with (
        mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            side_effect=OSError("unit-sensitive-text"),
        ),
        mock.patch("ai_guardian.daemon.rest_api.DaemonRestAPI") as listener,
    ):
        server._start_rest_api()
    listener.assert_not_called()
    assert "configuration could not be loaded" in caplog.text
    assert "unit-sensitive-text" not in caplog.text


def test_https_preserves_explicit_bind_and_pid_compatibility(tmp_path):
    identity = make_identity(tmp_path / "identity")
    server = DaemonServer(enable_rest_api=False)
    config = {
        "daemon": {
            "rest_host": "127.0.0.1",
            "rest_port": 0,
            "rest_tls": listener_config(identity),
        }
    }
    with (
        mock.patch(
            "ai_guardian.config.loaders._load_config_file", return_value=(config, None)
        ),
        mock.patch.object(server, "_ensure_auth_token", return_value="unit-only-token"),
    ):
        try:
            server._start_rest_api()
            assert server._rest_port > 0
            assert server._rest_api._host == "127.0.0.1"
            server._write_pid_file()
            from ai_guardian.daemon import get_pid_path

            metadata = json.loads(get_pid_path().read_text())
            assert metadata["rest_scheme"] == "https"
            assert metadata["rest_port"] == server._rest_port
            assert not any(
                key in metadata for key in ("auth_token", "key_file", "cert_file")
            )
        finally:
            if server._rest_api:
                server._rest_api.stop()


def test_manual_trust_is_explicit_and_discovery_does_not_rewrite_it(tmp_path):
    target_path = tmp_path / "targets.json"
    entry = {
        "name": "vm",
        "url": "https://127.0.0.1:64443",
        "token": "unit-only-token",
        "tls": {
            "ca_file": "verified.pem",
            "server_name": "daemon.test",
            "certificate_sha256": "00" * 32,
        },
    }
    target_path.write_text(json.dumps({"daemons": [entry]}))
    target_path.chmod(0o600)
    before = target_path.read_bytes()
    with mock.patch(
        "ai_guardian.daemon.discovery.get_tray_targets_path", return_value=target_path
    ):
        target = DaemonDiscovery(config={}).discover_manual()[0]
    assert target.tls == entry["tls"]
    assert target.host == "127.0.0.1"
    assert target_path.read_bytes() == before
    assert "unit-only-token" not in repr(target)


def test_generated_authentication_token_is_private_from_creation(monkeypatch):
    import os
    from ai_guardian.daemon import get_auth_token_path

    monkeypatch.setattr(
        "secrets.token_urlsafe", lambda _size: "unit-only-generated-token"
    )
    original_open = os.open
    with mock.patch("os.open", wraps=original_open) as opened:
        assert DaemonServer._ensure_auth_token() == "unit-only-generated-token"
    assert all(call.args[2] == 0o600 for call in opened.call_args_list)
    assert DaemonServer._ensure_auth_token() == "unit-only-generated-token"
    assert get_auth_token_path().read_text() == "unit-only-generated-token"


def test_authentication_temp_collision_preserves_existing_file(monkeypatch):
    from ai_guardian.daemon import get_auth_token_path

    token = get_auth_token_path()
    token.parent.mkdir(parents=True, exist_ok=True)
    collision = token.with_name(f".{token.name}.unit-collision.tmp")
    collision.write_text("existing-user-file")
    monkeypatch.setattr("secrets.token_hex", lambda _size: "unit-collision")
    with pytest.raises(FileExistsError):
        DaemonServer._ensure_auth_token()
    assert collision.read_text() == "existing-user-file"


@pytest.mark.parametrize("data", [[], {"daemons": None}, {"daemons": [None]}])
def test_invalid_manual_target_structure_does_not_abort_discovery(tmp_path, data):
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(data))
    with mock.patch(
        "ai_guardian.daemon.discovery.get_tray_targets_path", return_value=path
    ):
        assert DaemonDiscovery(config={}).discover_manual() == []


def test_invalid_manual_url_has_safe_visible_error(tmp_path):
    path = tmp_path / "targets.json"
    path.write_text(
        json.dumps(
            {
                "daemons": [
                    {"name": "vm", "url": "https://unit-sensitive-token@localhost:bad"}
                ]
            }
        )
    )
    with mock.patch(
        "ai_guardian.daemon.discovery.get_tray_targets_path", return_value=path
    ):
        target = DaemonDiscovery(config={}).discover_manual()[0]
    assert target.status == "error"
    assert target.auth_token is None
    assert "unit-sensitive-token" not in target.error_message


def test_local_https_discovery_never_selects_plaintext_probe(tmp_path, monkeypatch):
    from ai_guardian.config.utils import get_config_dir
    from ai_guardian.daemon import get_pid_path
    from tests.fixtures.daemon_tls import serve_endpoint

    identity = make_identity(tmp_path / "identity")
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    trust = client_config(identity)
    (config_dir / "ai-guardian.json").write_text(
        json.dumps({"daemon": {"rest_tls": {"client": trust}}})
    )
    monkeypatch.setattr("ai_guardian.daemon.client.is_daemon_running", lambda: True)
    with serve_endpoint(identity) as endpoint:
        pid_file = get_pid_path()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(
            json.dumps(
                {"pid": 2222, "rest_scheme": "https", "rest_port": endpoint.port}
            )
        )
        with mock.patch.object(DaemonDiscovery, "_probe_daemon") as plaintext_probe:
            target = DaemonDiscovery(config={}).discover_local()
    plaintext_probe.assert_not_called()
    assert target.tls == trust
    assert len(endpoint.requests) == 1
