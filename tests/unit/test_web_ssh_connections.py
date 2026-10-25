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
    service.refresh_targets.return_value = []
    widgets = {}
    callbacks = {}
    ui = mock.MagicMock()

    def button(label, **kwargs):
        widget = mock.MagicMock()
        widget.bind_enabled_from.return_value = widget
        widgets[label] = widget
        callbacks[label] = kwargs.get("on_click")
        return widget

    async def io_bound(callback, *args):
        return callback(*args)

    ui.button.side_effect = button
    ui.input.return_value.classes.return_value.value = pairing.profile.destination
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
    form.service.remove_ssh_connection.assert_not_called()
    form.callbacks["Cancel"]()
    await form.callbacks["Remove connection"]()
    form.service.remove_ssh_connection.assert_not_called()
    await form.callbacks["Remove..."]()
    await form.callbacks["Remove connection"]()
    await form.callbacks["Remove connection"]()
    form.service.remove_ssh_connection.assert_called_once_with(target.ssh_id)


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
    ):
        with pytest.raises(SSHConnectionError, match="loopback-bound"):
            operation("untrusted")
    service._discovery.ssh_manager.prepare.assert_not_called()
    service.allow_ssh_pairing = True
    service.prepare_ssh_connection("alias")
    service._discovery.ssh_manager.prepare.assert_called_once_with("alias")
    service.close()
    service._discovery.stop.assert_called_once()
