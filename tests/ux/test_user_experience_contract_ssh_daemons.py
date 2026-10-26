"""SSH enrollment/offline/privacy/remote-prompt user experience contracts.

Manual qualification (requires an explicitly authorized disposable POSIX VM):
1. Configure a loopback HTTPS daemon and verify its SSH host key independently.
2. Select Add daemon via SSH in the tray; enter the existing SSH alias. Auto uses
   Native → Tkinter → NiceGUI through the shared dispatcher, not the Web Console.
3. Check the destination, SAN identity and fingerprint; Cancel must save nothing.
4. Repeat, explicitly confirm trust, then restart the tray: it reconnects.
   Cancel/Close or a later-step failure must never open a different toolkit.
5. Drop SSH connectivity, occupy the old local port, and restore connectivity:
   offline/backoff is visible; no unrelated listener receives daemon credentials.
6. Trigger a remote ask prompt and decide in the tray without inbound callbacks.
7. Change the daemon certificate: saved trust must not change automatically.
8. Remove the saved target; only owned tunnels/credentials disappear, not the VM
   daemon. Repeat native Windows-client/DPAPI and macOS UI qualification separately.

Automated tests use synthetic certificates, explicit storage and mock SSH only;
they never load the user's configuration or contact a live SSH destination.
"""

import json
from types import SimpleNamespace
from unittest import mock

import pytest

from ai_guardian.daemon.rest_api import _RestHandler
from ai_guardian.daemon.ssh_storage import (
    DESTINATION_ERROR,
    SSHConnectionError,
    SSHStore,
)
from ai_guardian.daemon.ssh_tunnel import (
    HTTPS_REQUIRED,
    IDENTITY_CHANGED,
    METADATA_ERROR,
    OFFLINE_ERROR,
    POLLING_ERROR,
    SSH_ERROR,
    STOPPED_ERROR,
    SSHPairing,
    probe_destination,
)
from ai_guardian.daemon.state import DaemonState
from tests.fixtures.ssh_daemon import make_pairing


@pytest.fixture
def pairing(tmp_path):
    return make_pairing(tmp_path)[0]


@pytest.mark.parametrize(
    "status,message",
    [
        (
            "https_required",
            "SSH-managed connections require a running HTTPS daemon with certificate metadata. Upgrade or configure the remote daemon before pairing; HTTP was not selected.",
        ),
        (
            "stopped",
            "The remote daemon is stopped. Start it as the SSH user, then reconnect.",
        ),
        (
            "unavailable",
            "Remote daemon metadata is unavailable or invalid; check the installation and the SSH user's configuration and state directories.",
        ),
        (
            "missing_config",
            "Remote AI Guardian configuration is missing. Complete setup as the SSH user before pairing.",
        ),
        (
            "unsafe_metadata",
            "Remote daemon storage has unsafe ownership, permissions, or symbolic links. Check the SSH user's configuration/state files and their ancestor directories; no credentials were returned.",
        ),
        (
            "rest_unavailable",
            "The remote daemon process is running, but its REST listener is unavailable. Run daemon status as the SSH user to see the startup precondition.",
        ),
    ],
)
def test_user_sees_specific_remote_state_without_plaintext_downgrade(status, message):
    with pytest.raises(SSHConnectionError) as error:
        SSHPairing.from_metadata("known-alias", {"status": status})
    assert str(error.value) == message


def test_unknown_or_changed_ssh_host_key_is_not_accepted_or_echoed(pairing):
    """USER EXPERIENCE: SSH rejects authentication/host key → actionable safe text."""

    def failed(_args, **kwargs):
        kwargs["stderr"].write(pairing.profile.token.encode())
        process = mock.Mock(returncode=255)
        process.poll.return_value = 255
        return process

    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch("subprocess.Popen", side_effect=failed),
        pytest.raises(SSHConnectionError) as error,
    ):
        probe_destination("known-alias")
    assert (
        str(error.value)
        == "SSH connection failed. Check the host alias, agent authentication, and known host key using your SSH client. No identities were accepted automatically."
    )
    assert pairing.profile.token not in str(error.value)


def test_offline_and_identity_change_messages_are_explicit():
    assert (
        POLLING_ERROR
        == "Remote daemon does not support polling-only tray registration; upgrade the daemon to use SSH permission prompts."
    )
    assert (
        OFFLINE_ERROR
        == "SSH daemon offline; reconnecting with backoff. No daemon credentials are sent without an active, verified tunnel."
    )
    assert (
        IDENTITY_CHANGED
        == "The saved daemon identity or credential has changed. Independently verify the remote daemon, then remove and pair the connection again. Saved trust was not replaced."
    )
    assert (
        DESTINATION_ERROR
        == "Enter a known SSH host or alias, optionally as user@host; SSH options, URLs, and shell commands are not accepted."
    )


def test_pairing_only_prepares_until_user_confirms_and_no_secret_is_displayed(
    tmp_path, pairing
):
    from ai_guardian.ui.ssh_pairing import pairing_summary, TRUST_LABEL
    from ai_guardian.daemon.ssh_connections import SSHConnectionManager

    manager = SSHConnectionManager(SSHStore(tmp_path / "connections"))
    with mock.patch(
        "ai_guardian.daemon.ssh_connections.probe_destination", return_value=pairing
    ):
        draft = manager.prepare("known-alias")
    assert manager.store.load() == []
    summary = pairing_summary(draft)
    assert (
        TRUST_LABEL == "I confirm this SSH destination and daemon certificate identity"
    )
    assert f"TLS server identity: {pairing.profile.server_name}" in summary
    assert f"Certificate SHA-256: {pairing.profile.certificate_sha256}" in summary
    assert pairing.profile.token not in summary
    assert "PRIVATE KEY" not in summary
    manager.close()


def test_tray_ssh_pairing_uses_native_first_without_opening_console(
    monkeypatch, pairing
):
    """USER EXPERIENCE: Add via SSH → desktop input, full identity, unchecked trust.

    Only explicit Trust and add daemon saves the private server-side draft.
    Canceling identity review ends the flow without Tk/browser replacement.
    """
    from ai_guardian.tray.ssh_connections import open_enrollment
    from ai_guardian.ui.ssh_pairing import TRUST_LABEL

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    tray = mock.Mock()
    tray._discovery.ssh_manager.prepare.return_value = pairing
    with (
        mock.patch("ai_guardian.ui.forms.NativeForm") as native,
        mock.patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess"
        ) as tk,
        mock.patch("ai_guardian.tray.sandbox_dialog._show_nicegui_form") as browser,
        mock.patch("ai_guardian.tray.menu.open_web_console") as console,
    ):
        native.return_value.side_effect = [{"host": "known-alias"}, None]
        open_enrollment(tray)
    review = native.return_value.call_args
    assert review.args[0] == "Verify SSH daemon identity"
    assert review.args[2] == [
        {
            "name": "trust",
            "label": TRUST_LABEL,
            "type": "bool",
            "default": False,
            "required": True,
        }
    ]
    assert pairing.profile.certificate_sha256 in review.args[1]
    assert pairing.profile.token not in str(native.return_value.call_args_list)
    tray._discovery.ssh_manager.enroll.assert_not_called()
    tk.assert_not_called()
    browser.assert_not_called()
    console.assert_not_called()


def test_authenticated_poll_only_registration_needs_no_callback_or_workstation_token(
    tmp_path,
):
    """USER EXPERIENCE: remote ask prompts queue for tray polling, not callbacks."""
    state = DaemonState(
        config_path=tmp_path / "config.json",
        sessions_file=tmp_path / "sessions.json",
        pause_file=tmp_path / "paused",
    )
    handler = _RestHandler.__new__(_RestHandler)
    handler.server = SimpleNamespace(daemon_state=state)
    handler._send_json = mock.Mock()
    handler._send_error = mock.Mock()
    handler._handle_register_tray({"poll_only": True})
    handler._send_json.assert_called_once_with(
        {"status": "registered", "host": "127.0.0.1", "port": 0, "poll_only": True}
    )
    assert state.is_tray_registered()
    assert state._registered_tray["auth_token"] is None
    pending = state.queue_prompt(
        {"summary": "Synthetic remote permission prompt"}, "block", 10
    )
    assert state.get_pending_prompts()[0]["prompt_id"] == pending.prompt_id
    assert state.resolve_prompt(pending.prompt_id, {"decision": "block"})
    assert pending.decision_event.is_set()
    with mock.patch("urllib.request.urlopen") as callback:
        handler._do_forward_trace("synthetic.json", {"events": []})
    callback.assert_not_called()


def test_open_permission_dialog_cannot_approve_a_new_daemon_invocation(tmp_path):
    """USER EXPERIENCE: restart during a dialog → stale approval is rejected."""

    def state():
        return DaemonState(
            config_path=tmp_path / "config.json",
            sessions_file=tmp_path / "sessions.json",
            pause_file=tmp_path / "paused",
        )

    old = state().queue_prompt({"summary": "Old invocation"}, "block", 300)
    restarted = state()
    current = restarted.queue_prompt({"summary": "New invocation"}, "block", 300)
    handler = _RestHandler.__new__(_RestHandler)
    handler.server = SimpleNamespace(daemon_state=restarted)
    handler._send_json = mock.Mock()
    handler._send_error = mock.Mock()
    handler._handle_prompt_decision(
        {"prompt_id": old.prompt_id, "decision": "allow_once"}
    )
    handler._send_error.assert_called_once_with(
        404, "Prompt not found or already resolved"
    )
    assert current.result is None


@pytest.mark.parametrize(
    "body",
    [
        {"poll_only": False},
        {"poll_only": "true"},
        {"poll_only": True, "host": "127.0.0.1"},
        {"poll_only": True, "auth_token": "synthetic-token"},
    ],
)
def test_poll_only_cannot_smuggle_callback_configuration(body):
    handler = _RestHandler.__new__(_RestHandler)
    handler.server = mock.Mock()
    handler._send_json = mock.Mock()
    handler._send_error = mock.Mock()
    handler._handle_register_tray(body)
    handler._send_error.assert_called_once_with(
        400,
        "poll_only registration must be true and contain no callback address or credential",
    )
    handler.server.daemon_state.register_tray.assert_not_called()
