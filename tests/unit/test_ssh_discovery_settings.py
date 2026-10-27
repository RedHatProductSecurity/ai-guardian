"""Shared workstation settings and complete tray flows, without a live desktop."""

import json
from unittest import mock

import pytest

from ai_guardian.daemon import ssh_config
from ai_guardian.daemon.ssh_storage import SSHConnectionError
from ai_guardian.tray import ssh_connections


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "workstation" / "ai-guardian.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "unrelated": "preserve",
                "daemon": {
                    "rest_tls": {"enabled": True},
                    "tray": {
                        "other": "preserve",
                        "ssh_alias_discovery": {
                            "enabled": True,
                            "alias_prefix": "guardian-",
                        },
                    },
                },
            }
        )
    )
    monkeypatch.setattr("ai_guardian.config.utils.get_config_dir", lambda: path.parent)
    return path


@pytest.fixture
def form():
    renderer = mock.Mock(return_value=None)
    with mock.patch(
        "ai_guardian.ui.forms.run_form_flow",
        side_effect=lambda interaction, **_kwargs: interaction(renderer),
    ):
        yield renderer


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("prefix", ["", "guardian-", "Ab_1.example-", "x" * 253])
def test_shared_save_round_trips_only_workstation_settings(
    settings_file, tmp_path, monkeypatch, enabled, prefix
):
    project = tmp_path / "project.json"
    project.write_text('{"daemon":{"tray":{"ssh_alias_discovery":{"enabled":false}}}}')
    before_project = project.read_bytes()
    monkeypatch.setenv("AI_GUARDIAN_PROJECT_CONFIG", str(project))
    ssh_config.save_settings(enabled, prefix)
    assert ssh_config.load_settings() == {"enabled": enabled, "alias_prefix": prefix}
    config = json.loads(settings_file.read_text())
    assert config["unrelated"] == "preserve"
    assert config["daemon"]["rest_tls"] == {"enabled": True}
    assert config["daemon"]["tray"]["other"] == "preserve"
    assert project.read_bytes() == before_project


@pytest.mark.parametrize(
    "enabled,prefix",
    [
        ("true", ""),
        (1, ""),
        (None, ""),
        (True, None),
        (True, "*"),
        (True, "a\n"),
        (True, "a b"),
        (True, "x" * 254),
    ],
)
def test_shared_validation_never_writes_invalid_settings(
    settings_file, enabled, prefix
):
    before = settings_file.read_bytes()
    with (
        mock.patch("ai_guardian.config.writer._atomic_config_update") as write,
        pytest.raises(SSHConnectionError, match="literal SSH alias prefix"),
    ):
        ssh_config.save_settings(enabled, prefix)
    write.assert_not_called()
    assert settings_file.read_bytes() == before


@pytest.mark.parametrize("contents", ["{invalid", "[]", "null"])
def test_shared_save_preserves_unreadable_configuration(settings_file, contents):
    settings_file.write_text(contents)
    with pytest.raises(SSHConnectionError, match="not saved"):
        ssh_config.save_settings(True, "")
    assert settings_file.read_text() == contents


def test_shared_save_reports_read_only_state_without_changes(settings_file):
    before = settings_file.read_bytes()
    with (
        mock.patch("ai_guardian.config.writer.is_config_read_only", return_value=True),
        pytest.raises(SSHConnectionError, match="Could not save local SSH"),
    ):
        ssh_config.save_settings(False, "")
    assert settings_file.read_bytes() == before


def test_shared_save_can_create_missing_configuration(settings_file):
    settings_file.unlink()
    assert ssh_config.load_settings() == ssh_config.DEFAULT_SETTINGS
    ssh_config.save_settings(True, "")
    assert ssh_config.load_settings() == {"enabled": True, "alias_prefix": ""}


@pytest.mark.parametrize("enabled,prefix", [(True, "guardian-"), (False, "")])
def test_tray_flow_loads_current_values_and_only_saves_at_last_step(
    settings_file, form, enabled, prefix
):
    tray = mock.Mock()
    original = settings_file.read_bytes()

    def respond(title, message, fields, *, submit_label):
        if submit_label == "Continue":
            assert fields == [
                {
                    "name": "enabled",
                    "label": "Enable SSH alias discovery",
                    "type": "bool",
                    "default": True,
                }
            ]
            assert settings_file.read_bytes() == original
            return {"enabled": enabled}
        if submit_label == "Save":
            assert fields == [
                {
                    "name": "alias_prefix",
                    "label": "Optional alias prefix (empty lists all supported concrete aliases)",
                    "default": "guardian-",
                }
            ]
            assert settings_file.read_bytes() == original
            return {"alias_prefix": prefix}
        assert submit_label == "Close"
        assert message == (
            "SSH alias discovery settings saved. Candidates refresh automatically; saved trust is unchanged."
        )
        return None

    form.side_effect = respond
    ssh_connections.open_discovery_settings(tray)
    assert ssh_config.load_settings() == {"enabled": enabled, "alias_prefix": prefix}
    tray._refresh_event.set.assert_called_once()
    assert not tray._discovery.mock_calls
    assert not tray._multi_client.mock_calls
    tray._ensure_web_console_ready.assert_not_called()
    tray._check_and_autostart_daemon.assert_not_called()


@pytest.mark.parametrize(
    "responses", [[None], [{"enabled": False}, None], [{"enabled": "true"}], [{}]]
)
def test_tray_cancel_close_or_invalid_checkbox_never_changes_settings(
    settings_file, form, responses
):
    tray = mock.Mock()
    before = settings_file.read_bytes()
    form.side_effect = responses
    ssh_connections.open_discovery_settings(tray)
    assert settings_file.read_bytes() == before
    tray._refresh_event.set.assert_not_called()
    assert not tray._discovery.mock_calls


def test_invalid_prefix_is_kept_with_feedback_and_can_be_cancelled(settings_file, form):
    tray = mock.Mock()
    before = settings_file.read_bytes()
    form.side_effect = [{"enabled": False}, {"alias_prefix": "*"}, None]
    ssh_connections.open_discovery_settings(tray)
    retry = form.call_args_list[2]
    assert "literal SSH alias prefix" in retry.args[1]
    assert retry.args[2][0]["default"] == "*"
    assert retry.kwargs["submit_label"] == "Save"
    assert settings_file.read_bytes() == before
    tray._refresh_event.set.assert_not_called()


def test_validation_can_be_corrected_without_restarting_settings_flow(
    settings_file, form
):
    tray = mock.Mock()
    form.side_effect = [
        {"enabled": False},
        {"alias_prefix": "*"},
        {"alias_prefix": ""},
        None,
    ]
    ssh_connections.open_discovery_settings(tray)
    assert ssh_config.load_settings() == {"enabled": False, "alias_prefix": ""}
    assert form.call_count == 4
    tray._refresh_event.set.assert_called_once()


def test_tray_save_failure_has_feedback_without_refresh_or_mutation(
    settings_file, form
):
    tray = mock.Mock()
    before = settings_file.read_bytes()
    form.side_effect = [{"enabled": False}, {"alias_prefix": ""}, None]
    with mock.patch(
        "ai_guardian.config.writer._atomic_config_update", return_value=False
    ):
        ssh_connections.open_discovery_settings(tray)
    assert "Could not save local SSH alias discovery settings" in form.call_args.args[1]
    assert settings_file.read_bytes() == before
    tray._refresh_event.set.assert_not_called()
