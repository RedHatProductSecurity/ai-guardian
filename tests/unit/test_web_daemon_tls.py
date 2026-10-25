"""Global-only HTTPS settings do not load remote keys on the Console host."""

from unittest import mock

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.daemon.rest_transport import DaemonConnectionError
from ai_guardian.web.pages.global_settings import (
    _create_rest_tls_settings,
    _set_rest_tls_config,
)


def test_tls_form_preserves_unrelated_settings_without_accessing_paths():
    config = {"daemon": {"rest_host": "127.0.0.1"}, "name": "example"}
    tls = {
        "enabled": True,
        "cert_file": "/remote/server.pem",
        "key_file": "/remote/private.pem",
        "client": {"server_name": "daemon.test"},
    }
    with mock.patch(
        "pathlib.Path.read_bytes",
        side_effect=AssertionError("Must not read remote files"),
    ):
        assert _set_rest_tls_config(config, tls) is config
    assert config["daemon"]["rest_host"] == "127.0.0.1"
    assert config["name"] == "example"
    assert config["daemon"]["rest_tls"] == tls


@pytest.mark.parametrize(
    "tls",
    [
        {"enabled": True, "cert_file": "", "key_file": ""},
        {"enabled": "true", "cert_file": "cert", "key_file": "key"},
        {
            "enabled": False,
            "cert_file": "",
            "key_file": "",
            "client": {"certificate_sha256": "bad"},
        },
    ],
)
def test_invalid_form_is_not_saved(tls):
    config = {"daemon": {"rest_host": "127.0.0.1"}}
    with pytest.raises(DaemonConnectionError):
        _set_rest_tls_config(config, tls)
    assert config == {"daemon": {"rest_host": "127.0.0.1"}}


@pytest.mark.parametrize("editable", [True, False])
def test_tls_form_defaults_and_scope(editable):
    with mock.patch("ai_guardian.web.pages.global_settings.ui") as ui:
        _create_rest_tls_settings({}, editable=editable)
    ui.switch.assert_called_once_with("Enable native HTTPS", value=False)
    assert ui.input.call_count == 5
    assert bool(ui.switch.return_value.disable.call_count) is not editable
    assert bool(ui.button.return_value.disable.call_count) is not editable


@pytest.mark.parametrize("stats", [None, {"request_count": 1}])
def test_connection_card_displays_actionable_tls_error_as_text(stats):
    from ai_guardian.daemon.discovery import DaemonTarget
    from ai_guardian.daemon.rest_transport import TLS_PIN_ERROR
    from ai_guardian.web.components.daemon_card import daemon_card

    target = DaemonTarget(
        name="vm", runtime="manual", status="error", error_message=TLS_PIN_ERROR
    )
    with mock.patch("ai_guardian.web.components.daemon_card.ui") as ui:
        daemon_card(target, stats)
    ui.label.assert_any_call(TLS_PIN_ERROR)
