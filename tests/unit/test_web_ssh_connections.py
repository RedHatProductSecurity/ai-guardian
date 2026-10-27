"""Local Web Console enrollment controls and browser-side data boundaries."""

from types import SimpleNamespace
from unittest import mock

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.daemon.ssh_storage import SSHConnectionError
from ai_guardian.daemon.ssh_tunnel import SSH_ERROR
from ai_guardian.web.components import ssh_connections as component
from ai_guardian.web.services.daemon_service import DaemonService
from tests.fixtures.ssh_daemon import make_pairing


@pytest.fixture
def form(tmp_path):
    pairing = make_pairing(tmp_path)[0]
    service = mock.Mock(allow_ssh_pairing=True)
    service.prepare_ssh_connection.return_value = pairing
    service.prepare_discovered_ssh_connection.return_value = pairing
    service.refresh_targets.return_value = []
    service.get_ssh_alias_discovery.return_value = {
        "enabled": False,
        "alias_prefix": "ai-guardian-",
        "aliases": (),
        "notices": (),
    }
    widgets = {}
    callbacks = {}
    ui = mock.MagicMock()
    # NiceGUI's fluent props/context-manager methods return the same dialog.
    ui.dialog.return_value.props.return_value = ui.dialog.return_value
    ui.dialog.return_value.__enter__.return_value = ui.dialog.return_value

    def button(label, **kwargs):
        widget = mock.MagicMock()
        widget.bind_enabled_from.return_value = widget
        widgets[label] = widget
        callbacks[label] = kwargs.get("on_click")
        return widget

    def input_field(label, **kwargs):
        widget = mock.MagicMock()
        widget.classes.return_value = widget
        widget.value = kwargs.get("value", pairing.profile.destination)
        widget.set_value.side_effect = lambda value: setattr(widget, "value", value)
        widgets[label] = widget
        return widget

    async def io_bound(callback, *args):
        return callback(*args)

    ui.button.side_effect = button
    ui.input.side_effect = input_field
    ui.switch.return_value.value = False
    ui.switch.return_value.set_value.side_effect = lambda value: setattr(
        ui.switch.return_value, "value", value
    )
    ui.checkbox.return_value.value = False
    with (
        mock.patch.object(component, "ui", ui),
        mock.patch.object(component.run, "io_bound", side_effect=io_bound),
        mock.patch.object(component, "is_client_deleted", return_value=False),
    ):
        component.create_ssh_connections(service)
        yield SimpleNamespace(
            pairing=pairing,
            service=service,
            ui=ui,
            widgets=widgets,
            callbacks=callbacks,
        )


@pytest.mark.asyncio
async def test_prepare_requires_explicit_unchecked_consent_and_does_not_save(form):
    await form.callbacks["Add daemon via SSH"]()
    form.service.prepare_ssh_connection.assert_called_once_with(
        form.pairing.profile.destination
    )
    form.service.enroll_ssh_connection.assert_not_called()
    form.ui.checkbox.assert_called_once_with(component.TRUST_LABEL, value=False)
    form.widgets["Trust and add daemon"].bind_enabled_from.assert_called_once_with(
        form.ui.checkbox.return_value, "value"
    )
    await form.callbacks["Trust and add daemon"]()  # Backend guard, not just disable.
    form.service.enroll_ssh_connection.assert_not_called()
    assert form.pairing.profile.token not in str(form.ui.label.call_args_list)
    assert form.pairing.profile.token not in str(form.ui.input.call_args_list)


@pytest.mark.asyncio
async def test_confirmation_is_single_use_and_cancel_does_not_pair(form):
    await form.callbacks["Add daemon via SSH"]()
    form.callbacks["Cancel"]()
    form.ui.checkbox.return_value.value = True
    await form.callbacks["Trust and add daemon"]()
    form.service.enroll_ssh_connection.assert_not_called()
    await form.callbacks["Add daemon via SSH"]()
    await form.callbacks["Trust and add daemon"]()
    await form.callbacks["Trust and add daemon"]()
    form.service.enroll_ssh_connection.assert_called_once_with(form.pairing)


@pytest.mark.asyncio
async def test_failed_ssh_has_safe_actionable_feedback(form):
    form.service.prepare_ssh_connection.side_effect = SSHConnectionError(SSH_ERROR)
    await form.callbacks["Add daemon via SSH"]()
    form.ui.label.return_value.classes.return_value.set_text.assert_any_call(SSH_ERROR)
    form.service.enroll_ssh_connection.assert_not_called()
    form.widgets["Add daemon via SSH"].enable.assert_called_once()


def test_pairing_summary_contains_identity_but_never_credential_or_ca_body(form):
    summary = component.pairing_summary(form.pairing)
    assert form.pairing.profile.server_name in summary
    assert form.pairing.profile.certificate_sha256 in summary
    assert str(form.pairing.port) in summary
    assert form.pairing.profile.token not in summary
    assert form.pairing.profile.ca_pem not in summary


@pytest.mark.asyncio
async def test_removal_needs_fresh_single_use_confirmation(form):
    from ai_guardian.daemon.discovery import DaemonTarget

    target = DaemonTarget(
        name="ssh-alias",
        runtime="ssh",
        ssh_id=form.pairing.profile.id,
        status="offline",
    )
    form.service.refresh_targets.return_value = [target]
    await form.ui.timer.call_args.args[1]()
    await form.callbacks["Remove..."]()
    form.ui.label.assert_any_call(
        "This removes the saved credential and trust, closes owned tunnels, and dismisses this alias from discovery. The remote daemon is not stopped."
    )
    form.service.remove_ssh_connection.assert_not_called()
    form.callbacks["Cancel"]()
    await form.callbacks["Remove connection"]()
    form.service.remove_ssh_connection.assert_not_called()
    await form.callbacks["Remove..."]()
    await form.callbacks["Remove connection"]()
    await form.callbacks["Remove connection"]()
    form.service.remove_ssh_connection.assert_called_once_with(target.ssh_id)
    form.ui.label.return_value.classes.return_value.set_text.assert_any_call(
        "Saved SSH connection removed and alias dismissed. The remote daemon was not stopped."
    )


def test_nonlocal_web_console_has_no_enrollment_surface():
    service = mock.Mock(allow_ssh_pairing=False)
    with mock.patch.object(component, "ui") as ui:
        component.create_ssh_connections(service)
    ui.card.assert_not_called()
    service.prepare_ssh_connection.assert_not_called()


def test_service_enforces_local_only_even_for_direct_calls():
    service = DaemonService()
    service._discovery = mock.Mock()
    for operation in (
        service.prepare_ssh_connection,
        service.enroll_ssh_connection,
        service.remove_ssh_connection,
        service.prepare_discovered_ssh_connection,
        service.dismiss_ssh_alias,
    ):
        with pytest.raises(SSHConnectionError, match="loopback-bound"):
            operation("untrusted")
    with pytest.raises(SSHConnectionError, match="loopback-bound"):
        service.get_ssh_alias_discovery()
    with pytest.raises(SSHConnectionError, match="loopback-bound"):
        service.save_ssh_alias_settings(True, "")
    service._discovery.ssh_manager.prepare.assert_not_called()
    service.allow_ssh_pairing = True
    service.prepare_ssh_connection("alias")
    service._discovery.ssh_manager.prepare.assert_called_once_with("alias")
    service.close()
    service._discovery.stop.assert_called_once()


@pytest.mark.asyncio
async def test_automatic_candidate_list_has_direct_review_without_host_entry(form):
    form.service.get_ssh_alias_discovery.return_value = {
        "enabled": True,
        "alias_prefix": "",
        "aliases": ("existing-vm",),
        "notices": (),
    }
    await form.ui.timer.call_args.args[1]()
    form.service.prepare_discovered_ssh_connection.assert_not_called()
    form.ui.label.assert_any_call("SSH aliases available to pair (1)")
    await form.callbacks["Review discovered daemon"]()
    form.service.prepare_discovered_ssh_connection.assert_called_once_with(
        "existing-vm"
    )
    form.service.prepare_ssh_connection.assert_not_called()
    form.service.enroll_ssh_connection.assert_not_called()
    # Refresh and repeated action do not open another identity prompt.
    await form.ui.timer.call_args.args[1]()
    await form.callbacks["Review discovered daemon"]()
    assert form.service.prepare_discovered_ssh_connection.call_count == 1
    assert form.ui.checkbox.call_args.kwargs["value"] is False
    form.ui.element.assert_called_once_with("div")
    assert form.ui.element.return_value.__enter__.call_count == 1
    form.callbacks["Cancel"]()
    form.ui.checkbox.return_value.value = True
    await form.callbacks["Trust and add daemon"]()
    form.service.enroll_ssh_connection.assert_not_called()


@pytest.mark.asyncio
async def test_candidate_dismissal_and_settings_are_explicit_local_actions(form):
    form.service.get_ssh_alias_discovery.return_value = {
        "enabled": True,
        "alias_prefix": "",
        "aliases": ("existing-vm",),
        "notices": (),
    }
    await form.ui.timer.call_args.args[1]()
    await form.callbacks["Dismiss alias"]()
    form.service.dismiss_ssh_alias.assert_called_once_with("existing-vm")
    form.service.prepare_discovered_ssh_connection.assert_not_called()
    form.service.save_ssh_alias_settings.assert_not_called()
    await form.callbacks["Save SSH discovery settings"]()
    form.service.save_ssh_alias_settings.assert_called_once()


def test_settings_write_is_workstation_global_preserves_other_values(tmp_path):
    import json

    service = DaemonService()
    service.allow_ssh_pairing = True
    path = tmp_path / "ai-guardian.json"
    path.write_text(
        json.dumps(
            {"unrelated": "preserve", "daemon": {"rest_tls": {"enabled": False}}}
        )
    )
    with mock.patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path):
        service.save_ssh_alias_settings(True, "")
    result = json.loads(path.read_text())
    assert result["daemon"]["tray"]["ssh_alias_discovery"] == {
        "enabled": True,
        "alias_prefix": "",
    }
    assert result["daemon"]["rest_tls"] == {"enabled": False}
    assert result["unrelated"] == "preserve"
    service.close()


@pytest.mark.parametrize(
    "enabled,prefix", [("true", ""), (True, "*"), (True, "a\n"), (True, "x" * 254)]
)
def test_invalid_settings_never_write(enabled, prefix):
    service = DaemonService()
    service.allow_ssh_pairing = True
    with (
        mock.patch("ai_guardian.config.writer._atomic_config_update") as write,
        pytest.raises(SSHConnectionError, match="literal SSH alias prefix"),
    ):
        service.save_ssh_alias_settings(enabled, prefix)
    write.assert_not_called()
    service.close()


@pytest.mark.parametrize("contents", ["{invalid", "[]", "null"])
def test_settings_never_replace_malformed_existing_configuration(tmp_path, contents):
    service = DaemonService()
    service.allow_ssh_pairing = True
    path = tmp_path / "ai-guardian.json"
    path.write_text(contents)
    with (
        mock.patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
        pytest.raises(SSHConnectionError, match="not saved"),
    ):
        service.save_ssh_alias_settings(True, "")
    assert path.read_text() == contents
    service.close()


def test_network_console_refresh_disables_alias_enumeration_before_discovery():
    service = DaemonService()
    service._discovery = mock.Mock()
    service.refresh_targets()
    assert service._discovery.allow_ssh_alias_discovery is False
    service.close()


def test_candidate_reader_is_cached_not_a_duplicate_scan():
    service = DaemonService()
    service.allow_ssh_pairing = True
    service._discovery = mock.Mock()
    manager = service._discovery.ssh_manager
    manager.alias_discovery = {
        "enabled": True,
        "aliases": ("existing-vm",),
        "notices": (),
    }
    assert service.get_ssh_alias_discovery() == manager.alias_discovery
    manager.refresh_aliases.assert_not_called()
    service.close()


@pytest.mark.asyncio
async def test_discovered_web_confirmation_is_explicit_and_single_use(form):
    form.service.get_ssh_alias_discovery.return_value = {
        "enabled": True,
        "alias_prefix": "",
        "aliases": ("existing-vm",),
        "notices": (),
    }
    await form.ui.timer.call_args.args[1]()
    await form.callbacks["Review discovered daemon"]()
    await form.callbacks["Trust and add daemon"]()
    form.service.enroll_ssh_connection.assert_not_called()
    form.ui.checkbox.return_value.value = True
    await form.callbacks["Trust and add daemon"]()
    await form.callbacks["Trust and add daemon"]()
    form.service.enroll_ssh_connection.assert_called_once_with(form.pairing)
    form.service.prepare_ssh_connection.assert_not_called()


@pytest.mark.asyncio
async def test_late_hide_from_old_review_does_not_unlock_new_review(form):
    await form.callbacks["Add daemon via SSH"]()
    old_finish = form.ui.dialog.return_value.props.return_value.on.call_args.args[1]
    form.callbacks["Cancel"]()
    await form.callbacks["Add daemon via SSH"]()
    old_finish()
    await form.callbacks["Add daemon via SSH"]()
    assert form.service.prepare_ssh_connection.call_count == 2
    form.service.enroll_ssh_connection.assert_not_called()


@pytest.mark.asyncio
async def test_clean_web_settings_follow_changes_saved_from_tray(form):
    refresh = form.ui.timer.call_args.args[1]
    await refresh()
    form.service.get_ssh_alias_discovery.return_value.update(
        enabled=True, alias_prefix="guardian-"
    )
    await refresh()
    assert form.ui.switch.return_value.value is True
    prefix = form.widgets["Optional alias prefix (empty lists all concrete aliases)"]
    assert prefix.value == "guardian-"
    form.service.save_ssh_alias_settings.assert_not_called()


@pytest.mark.asyncio
async def test_external_settings_refresh_does_not_overwrite_unsaved_web_edits(form):
    refresh = form.ui.timer.call_args.args[1]
    await refresh()
    prefix = form.widgets["Optional alias prefix (empty lists all concrete aliases)"]
    prefix.value = "draft-"
    form.service.get_ssh_alias_discovery.return_value.update(
        enabled=True, alias_prefix="guardian-"
    )
    await refresh()
    assert form.ui.switch.return_value.value is False
    assert prefix.value == "draft-"

    def save(enabled, alias_prefix):
        form.service.get_ssh_alias_discovery.return_value.update(
            enabled=enabled, alias_prefix=alias_prefix
        )

    form.service.save_ssh_alias_settings.side_effect = save
    await form.callbacks["Save SSH discovery settings"]()
    form.service.save_ssh_alias_settings.assert_called_once_with(False, "draft-")
    form.service.get_ssh_alias_discovery.return_value.update(
        enabled=True, alias_prefix=""
    )
    await refresh()
    assert form.ui.switch.return_value.value is True
    assert prefix.value == ""


@pytest.mark.asyncio
async def test_failed_web_save_keeps_draft_when_tray_settings_refresh(form):
    refresh = form.ui.timer.call_args.args[1]
    await refresh()
    prefix = form.widgets["Optional alias prefix (empty lists all concrete aliases)"]
    prefix.value = "draft-"
    form.service.save_ssh_alias_settings.side_effect = SSHConnectionError(
        "Could not save local SSH alias discovery settings."
    )
    await form.callbacks["Save SSH discovery settings"]()
    form.service.get_ssh_alias_discovery.return_value.update(
        enabled=True, alias_prefix="guardian-"
    )
    await refresh()
    assert form.ui.switch.return_value.value is False
    assert prefix.value == "draft-"
    form.widgets["Save SSH discovery settings"].enable.assert_called_once()


@pytest.mark.asyncio
async def test_web_edits_during_save_remain_unsaved_not_replaced_by_refresh(form):
    await form.ui.timer.call_args.args[1]()
    prefix = form.widgets["Optional alias prefix (empty lists all concrete aliases)"]
    prefix.value = "save-this-"

    def save(enabled, alias_prefix):
        prefix.value = "newer-edit-"
        form.service.get_ssh_alias_discovery.return_value.update(
            enabled=enabled, alias_prefix=alias_prefix
        )

    form.service.save_ssh_alias_settings.side_effect = save
    await form.callbacks["Save SSH discovery settings"]()
    form.service.save_ssh_alias_settings.assert_called_once_with(False, "save-this-")
    assert prefix.value == "newer-edit-"


def test_tray_and_web_console_reopen_the_same_saved_workstation_values(tmp_path):
    from ai_guardian.daemon.ssh_config import load_settings
    from ai_guardian.tray.ssh_connections import open_discovery_settings

    service = DaemonService()
    service.allow_ssh_pairing = True
    service._discovery = mock.Mock()
    renderer = mock.Mock(
        side_effect=[{"enabled": True}, {"alias_prefix": "guardian-"}, None]
    )
    with (
        mock.patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
        mock.patch(
            "ai_guardian.ui.forms.run_form_flow",
            side_effect=lambda interaction, **_kwargs: interaction(renderer),
        ),
    ):
        open_discovery_settings(mock.Mock())
        assert load_settings() == {"enabled": True, "alias_prefix": "guardian-"}
        service.save_ssh_alias_settings(False, "")
        renderer.reset_mock(side_effect=True)
        renderer.side_effect = [{"enabled": False}, None]
        open_discovery_settings(mock.Mock())
        assert renderer.call_args_list[0].args[2][0]["default"] is False
        assert renderer.call_args_list[1].args[2][0]["default"] == ""
        assert load_settings() == {"enabled": False, "alias_prefix": ""}
    service._discovery.ssh_manager.prepare.assert_not_called()
    service._discovery.ssh_manager.enroll.assert_not_called()
    service.close()
