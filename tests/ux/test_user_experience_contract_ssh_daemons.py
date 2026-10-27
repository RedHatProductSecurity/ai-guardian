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
9. With discovery off and no enrolled daemons, choose Discover SSH aliases... next
   to Add daemon via SSH in the tray. Check the current enable value, Continue,
   edit the optional literal prefix, then Save. Cancel/Close at either step must
   save nothing. Try an invalid prefix and correct it without changing toolkit.
   A custom guardian- prefix or an empty prefix requires no alias renaming. The
   next refresh, without a restart, shows SSH aliases available to pair as a count,
   not targets. Restart and reopen: values persist. The local Web Console picker
   reads/writes the same settings; its untouched fields follow tray changes while
   unsaved browser edits are retained. Discovery off/zero matches hides candidates,
   never the tray settings entry; existing pairings/tunnels remain usable.
10. Review discovered daemon opens full identity review directly, with no host
    entry. Cancel saves nothing. Refresh never opens unsolicited trust dialogs.
11. Edit the synthetic user SSH config; added aliases appear on refresh. Dismiss
    an alias or remove a paired daemon and restart: it is not re-offered. Explicit
    manual Add remains available. Missing config does not erase saved pairings.
12. Verify unsupported/conditional includes show a safe notice without executing
    Match exec, contacting hosts, opening private keys or changing SSH config.
13. Repeat discovery settings with auto, tkinter, nicegui and headless preferences.
    Missing native/Tk startup may advance before display only. Cancel, Escape,
    title-bar Close or a later-step failure must not reopen in another provider;
    headless opens nothing and saves nothing. Saving never contacts a host or
     grants trust. Qualify macOS, Windows, GNOME/zenity and KDE/kdialog separately.
14. Keep a local daemon and an enrolled VM connected simultaneously. Local is
    first; other names sort alphabetically ignoring case. Verify the VM's Console,
    Violations, Metrics & Audit, Statistics, Terminal, Maintenance, MCP and About.
    CLI/scanner actions must affect only the VM's actual virtualenv installation.
    Reorder/refresh, stop/start the VM, reconnect and remove it while a menu/dialog
    is open: callbacks must not move to the workstation or another daemon. Missing
    old-daemon capabilities and command failures must have explicit explanations.
    With just the VM, the same applicable items use the flat single-daemon layout.
    Force an SSH login failure and open Terminal: its actual error must remain
    readable until dismissal, with no workstation-shell fallback. Upgrade and
    restart a remote daemon from main: its existing global config API still gives
    MCP state even without new stats fields. Linux procfs proves an older running
    daemon's venv interpreter; no guessed PATH installation may be executed.
15. Select the VM's Working Dir. It is an optional absolute VM path, not a desktop
    directory picker. Retry a relative path, then Save an absolute path; Cancel,
    Close and headless save nothing. Repeat native/Tk/NiceGUI and pre-display
    startup failure; never switch provider after validation or cancellation.
    With no saved directory, Terminal uses the SSH user's home, never the
    workstation home. Repeat discovery and reset to empty; explicitly saved VM
    directories survive, and their labels do not use workstation-home shortening.
16. Enable alias discovery with zero unpaired aliases. No greyed `(0)` entry is
    shown; Discover SSH aliases... remains. A discovery warning remains accessible
    as SSH alias discovery notice without inventing a pairing candidate.

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


def test_ssh_terminal_keeps_failure_output_readable_without_local_shell(pairing):
    """USER EXPERIENCE: SSH exits immediately → error stays until dismissed."""
    import shlex
    import threading

    from ai_guardian.daemon.discovery import DaemonTarget
    from ai_guardian.daemon.multi_client import MultiDaemonClient
    from ai_guardian.daemon.ssh_commands import SSHCommands
    from tests.fixtures.ssh_tray import make_tray

    store = mock.Mock()
    store.contains.return_value = True
    target = DaemonTarget(
        "ssh-vm",
        "ssh",
        ssh_commands=SSHCommands(pairing.profile, store, threading.Event()),
    )
    with (
        mock.patch("shutil.which", return_value="ssh"),
        mock.patch(
            "ai_guardian.daemon.multi_client._get_configured_terminal",
            return_value="gnome-terminal",
        ),
        mock.patch("platform.system", return_value="Linux"),
        mock.patch("subprocess.Popen") as launch,
        mock.patch("ai_guardian.daemon.working_dir.load_working_dirs", return_value={}),
        mock.patch(
            "ai_guardian.daemon.working_dir.get_working_dir",
            return_value="/workstation/home",
        ) as host_directory,
    ):
        make_tray([target])._menu._apply_working_dirs()
        assert MultiDaemonClient().open_shell(target)
    host_directory.assert_not_called()
    command = launch.call_args.args[0]
    assert command[:5] == ["gnome-terminal", "--maximize", "--", "bash", "-c"]
    ssh, hold = command[5].split("; echo; ", 1)
    assert shlex.split(ssh)[0] == "ssh"
    assert shlex.split(ssh)[-2] == pairing.profile.destination
    assert "cd " not in ssh
    assert "/workstation/home" not in ssh
    assert hold == 'read -rp "Press Enter to close..."'
    assert pairing.profile.token not in str(command)


@pytest.mark.parametrize("multi", [False, True])
def test_vm_has_standard_menu_labels_and_only_its_cached_data(multi):
    """USER EXPERIENCE: connected VM → the same applicable flat/nested menu."""
    from ai_guardian.daemon.discovery import DaemonTarget
    from tests.fixtures.ssh_tray import build, find, make_tray, visible

    target = DaemonTarget(
        "ssh-vm",
        "ssh",
        status="running",
        stats={
            "request_count": 2592,
            "mcp_installed": True,
            "mcp_proactive_level": "medium",
        },
    )
    tray = make_tray(([DaemonTarget("local", "local")] if multi else []) + [target])
    menu = visible(build(tray))[1].submenu if multi else build(tray)
    expected = [
        "Status",
        "Pause...",
        "Terminal",
        "Console",
        "Violations",
        "Metrics & Audit",
        "Statistics",
        "MCP Proactive: medium",
        "Maintenance",
        "Manage SSH connection...",
    ]
    labels = [item.label for item in visible(menu)]
    assert all(label in labels for label in expected)
    assert "Web Console" not in labels
    assert find(find(menu, "Statistics").submenu, "Requests: 2,592")
    tray._multi_client.get_status.assert_not_called()


@pytest.mark.parametrize("paused", [False, True])
def test_main_daemon_with_healthy_mcp_does_not_need_unreleased_stats_fields(paused):
    """USER EXPERIENCE: Doctor says MCP healthy → tray reads VM-global settings."""
    from ai_guardian.daemon.discovery import DaemonTarget
    from ai_guardian.daemon.ssh_connections import SSHConnectionManager
    from tests.fixtures.ssh_tray import build, find, make_tray

    stats = {"paused": paused, "mcp_installed": True}
    tunnel = mock.Mock()
    tunnel.request.return_value = {"mcp_server": {"proactive_level": "medium"}}
    target = DaemonTarget(
        "ssh-vm",
        "ssh",
        status="paused" if paused else "running",
        stats=SSHConnectionManager._stats_with_mcp_state(tunnel, stats),
    )
    tray = make_tray([target])
    tray._proactive_level = "high"  # workstation's choice must not leak into VM
    label = "MCP Proactive: paused" if paused else "MCP Proactive: medium"
    menu = find(build(tray), label)
    assert find(menu.submenu, "medium").checked
    assert find(menu.submenu, "medium").enabled
    assert target.stats["mcp_proactive_level"] == "medium"
    tunnel.request.assert_called_once_with("GET", "/api/config?scope=global")


@pytest.mark.parametrize(
    "answer", [None, {"directory": "/vm/project"}, {"directory": ""}]
)
def test_vm_directory_form_is_native_first_complete_and_cancel_safe(
    monkeypatch, answer
):
    """USER EXPERIENCE: VM path entry → native-first Save, not host folder selection."""
    from ai_guardian.daemon.discovery import DaemonTarget
    from tests.fixtures.ssh_tray import make_tray

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    target = DaemonTarget("ssh-vm", "ssh", working_dir="/vm/current")
    tray = make_tray([target])
    with (
        mock.patch("ai_guardian.ui.forms.NativeForm") as native,
        mock.patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess"
        ) as tk,
        mock.patch("ai_guardian.tray.sandbox_dialog._show_nicegui_form") as browser,
        mock.patch("ai_guardian.daemon.working_dir.choose_directory") as local_picker,
        mock.patch("ai_guardian.daemon.working_dir.set_working_dir") as save,
    ):
        native.return_value.return_value = answer
        tray._menu._pick_working_dir(target, target.working_dir, (0, 0, 1920, 1080))
    native.assert_called_once_with(screen_bounds=(0, 0, 1920, 1080))
    fields = native.return_value.call_args.args[2]
    assert fields == [
        {
            "name": "directory",
            "label": "VM directory (empty uses remote home)",
            "default": "/vm/current",
        }
    ]
    local_picker.assert_not_called()
    tk.assert_not_called()
    browser.assert_not_called()
    if answer is None:
        save.assert_not_called()
        assert target.working_dir == "/vm/current"
    else:
        save.assert_called_once_with("ssh-vm", answer["directory"])
        assert target.working_dir == (answer["directory"] or None)


def test_vm_path_validation_never_restarts_in_another_provider(monkeypatch):
    from ai_guardian.daemon.discovery import DaemonTarget
    from tests.fixtures.ssh_tray import make_tray

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    target = DaemonTarget("ssh-vm", "ssh")
    tray = make_tray([target])
    with (
        mock.patch("ai_guardian.ui.forms.NativeForm") as native,
        mock.patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess"
        ) as tk,
        mock.patch("ai_guardian.tray.sandbox_dialog._show_nicegui_form") as browser,
        mock.patch("ai_guardian.daemon.working_dir.set_working_dir") as save,
    ):
        native.return_value.side_effect = [{"directory": "relative"}, None]
        tray._menu._pick_working_dir(target, None)
    assert native.return_value.call_count == 2
    assert (
        "Choose an absolute directory on the VM"
        in native.return_value.call_args.args[1]
    )
    save.assert_not_called()
    tk.assert_not_called()
    browser.assert_not_called()


def test_removing_vm_while_directory_form_is_open_cannot_save_for_replacement():
    from ai_guardian.daemon.discovery import DaemonTarget
    from tests.fixtures.ssh_tray import make_tray

    target = DaemonTarget("ssh-vm", "ssh")
    tray = make_tray([target])

    def complete(_interaction, **_kwargs):
        tray._targets = [DaemonTarget("ssh-vm", "ssh")]
        return "/vm/project"

    with (
        mock.patch("ai_guardian.ui.forms.run_form_flow", side_effect=complete),
        mock.patch("ai_guardian.daemon.working_dir.set_working_dir") as save,
    ):
        tray._menu._pick_working_dir(target, None)
    save.assert_not_called()
    assert tray._targets[0].working_dir is None


def test_vm_path_startup_failure_can_fall_back_before_display_only(monkeypatch):
    from ai_guardian.daemon.discovery import DaemonTarget
    from ai_guardian.ui.modal import UIUnavailable
    from tests.fixtures.ssh_tray import make_tray

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    target = DaemonTarget("ssh-vm", "ssh")
    with (
        mock.patch("ai_guardian.ui.forms.NativeForm") as native,
        mock.patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess",
            return_value={"directory": "/vm/project"},
        ) as tk,
        mock.patch("ai_guardian.tray.sandbox_dialog._show_nicegui_form") as browser,
        mock.patch("ai_guardian.daemon.working_dir.set_working_dir") as save,
    ):
        native.return_value.side_effect = UIUnavailable("native startup unavailable")
        make_tray([target])._menu._pick_working_dir(target, None)
    tk.assert_called_once()
    browser.assert_not_called()
    save.assert_called_once_with(target.name, "/vm/project")


@pytest.mark.parametrize("preference", ["tkinter", "nicegui", "headless"])
def test_vm_path_respects_explicit_provider_and_headless(monkeypatch, preference):
    from ai_guardian.daemon.discovery import DaemonTarget
    from tests.fixtures.ssh_tray import make_tray

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", preference)
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    target = DaemonTarget("ssh-vm", "ssh")
    with (
        mock.patch("ai_guardian.ui.forms.NativeForm") as native,
        mock.patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess",
            return_value=None,
        ) as tk,
        mock.patch(
            "ai_guardian.tray.sandbox_dialog._show_nicegui_form", return_value=None
        ) as browser,
        mock.patch("ai_guardian.daemon.working_dir.set_working_dir") as save,
    ):
        make_tray([target])._menu._pick_working_dir(target, None)
    native.assert_not_called()
    assert tk.call_count == int(preference == "tkinter")
    assert browser.call_count == int(preference == "nicegui")
    save.assert_not_called()


def test_unsupported_workstation_plugin_cannot_execute_from_vm_menu():
    """USER EXPERIENCE: unsupported VM plugin → actionable text, never local exec."""
    from ai_guardian.daemon.discovery import DaemonTarget
    from ai_guardian.tray.plugins import execute_plugin_command

    with (
        mock.patch("subprocess.run") as run,
        mock.patch("ai_guardian.tray.plugins.show_dialog") as dialog,
    ):
        execute_plugin_command(
            "echo workstation", "notification", target=DaemonTarget("ssh-vm", "ssh")
        )
    run.assert_not_called()
    assert (
        dialog.call_args.args[1]
        == "Workstation command plugins are unavailable in an SSH daemon menu. Use a workstation/global plugin for local commands, or configure this VM command to run on its target."
    )


@pytest.mark.parametrize("notice", [False, True])
def test_empty_alias_inventory_does_not_show_disabled_zero_candidate_menu(notice):
    from ai_guardian.tray.ssh_connections import build_candidate_items
    from tests.fixtures.ssh_tray import PYSTRAY

    tray = SimpleNamespace(
        _discovery=SimpleNamespace(
            ssh_alias_discovery={
                "enabled": True,
                "aliases": (),
                "notices": (
                    ("A conditional include was not inspected.",) if notice else ()
                ),
            }
        )
    )
    entries = build_candidate_items(tray, PYSTRAY)
    assert [entry.label for entry in entries] == (
        ["SSH alias discovery notice"] if notice else []
    )
    assert all(entry.enabled for entry in entries)


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


@pytest.mark.parametrize("consent", [None, {"trust": False}, {"trust": True}])
def test_discovered_alias_review_skips_host_entry_but_keeps_full_native_confirmation(
    monkeypatch, pairing, consent
):
    """USER EXPERIENCE: click a discovered alias → same complete trust boundary.

    Discovery itself opens nothing. The user-chosen review probes this alias only.
    Cancel/unchecked consent is terminal and never saves or launches another UI.
    """
    from ai_guardian.tray.ssh_connections import open_enrollment
    from ai_guardian.ui.ssh_pairing import TRUST_LABEL

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    tray = mock.Mock()
    tray._discovery.ssh_manager.prepare_discovered.return_value = pairing
    with (
        mock.patch("ai_guardian.ui.forms.NativeForm") as native,
        mock.patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess"
        ) as tk,
        mock.patch("ai_guardian.tray.sandbox_dialog._show_nicegui_form") as browser,
    ):
        native.return_value.side_effect = [consent, {}]
        open_enrollment(tray, alias="existing-vm", screen_bounds=(0, 0, 1920, 1080))
    first = native.return_value.call_args_list[0]
    assert first.args[0] == "Verify SSH daemon identity"
    assert first.args[2] == [
        {
            "name": "trust",
            "label": TRUST_LABEL,
            "type": "bool",
            "default": False,
            "required": True,
        }
    ]
    summary = first.args[1]
    assert pairing.profile.destination in summary
    assert pairing.profile.server_name in summary
    assert pairing.profile.certificate_sha256 in summary
    assert pairing.profile.token not in str(native.return_value.call_args_list)
    assert pairing.profile.ca_pem not in str(native.return_value.call_args_list)
    tray._discovery.ssh_manager.prepare_discovered.assert_called_once_with(
        "existing-vm"
    )
    tray._discovery.ssh_manager.prepare.assert_not_called()
    if consent and consent.get("trust") is True:
        tray._discovery.ssh_manager.enroll.assert_called_once_with(pairing)
        tray._refresh_event.set.assert_called_once()
    else:
        tray._discovery.ssh_manager.enroll.assert_not_called()
    tk.assert_not_called()
    browser.assert_not_called()


def test_discovery_opt_in_dismissal_and_removal_do_not_imply_trust(
    tmp_path, monkeypatch, pairing
):
    """USER EXPERIENCE: local candidates are separate, durable dismissal is respected.

    No scanner calls OpenSSH, no alias becomes a target/credential automatically,
    and enabling discovery cannot replace saved trust. Restart preserves removal.
    """
    from ai_guardian.daemon import ssh_config
    from ai_guardian.daemon.discovery import DaemonDiscovery
    from ai_guardian.daemon.ssh_connections import SSHConnectionManager

    config = tmp_path / ".ssh" / "config"
    config.parent.mkdir()
    alias = pairing.profile.destination.rsplit("@", 1)[-1]
    config.write_text(f"Host {alias} other-vm\n")
    before = config.read_bytes()
    monkeypatch.setattr(ssh_config, "user_ssh_config", lambda: config)
    settings = {"enabled": False, "alias_prefix": ""}
    monkeypatch.setattr(
        "ai_guardian.daemon.ssh_connections.load_settings", lambda: dict(settings)
    )
    manager = SSHConnectionManager(SSHStore(tmp_path / "connections"))
    discovery = DaemonDiscovery()
    discovery._ssh_manager = manager
    with (
        mock.patch("ai_guardian.daemon.ssh_connections.probe_destination") as probe,
        mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel") as tunnel,
        mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread") as worker,
    ):
        try:
            assert discovery.discover_ssh() == []
            assert not discovery.ssh_alias_discovery["aliases"]
            settings["enabled"] = True
            assert discovery.discover_ssh() == []
            assert set(discovery.ssh_alias_discovery["aliases"]) == {alias, "other-vm"}
            assert manager.store.load() == []
            manager.dismiss_alias("other-vm")
            manager.store.create(pairing.profile)  # Already independently paired.
            assert len(discovery.discover_ssh()) == 1
            assert not discovery.ssh_alias_discovery["aliases"]
            manager.remove(pairing.profile.id)
        finally:
            manager.close()
        restarted = SSHConnectionManager(manager.store)
        try:
            assert restarted.refresh_aliases()["aliases"] == ()
            assert restarted.refresh() == []
        finally:
            restarted.close()
    assert worker.call_count == 1  # Only the deliberately saved profile.
    probe.assert_not_called()
    tunnel.assert_not_called()
    assert config.read_bytes() == before


@pytest.fixture
def discovery_settings_ui(tmp_path, monkeypatch):
    """Explicit disposable workstation settings and mocks for every reachable UI."""
    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    monkeypatch.setattr("ai_guardian.config.utils.get_config_dir", lambda: tmp_path)
    with (
        mock.patch("ai_guardian.ui.forms.NativeForm") as native,
        mock.patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess"
        ) as tk,
        mock.patch("ai_guardian.tray.sandbox_dialog._show_nicegui_form") as browser,
    ):
        yield SimpleNamespace(
            native=native.return_value,
            tk=tk,
            browser=browser,
            path=tmp_path / "ai-guardian.json",
        )


@pytest.mark.parametrize(
    "preference,provider",
    [("auto", "native"), ("tkinter", "tk"), ("nicegui", "browser")],
)
def test_discovery_settings_preserve_complete_controls_in_each_provider(
    discovery_settings_ui, monkeypatch, preference, provider
):
    """USER EXPERIENCE: a native-first two-step form, not Web Console navigation.

    Continue changes nothing. Save validates/persists both settings; empty prefix
    is a deliberate value. Connecting and trusting remain separate reviewed acts.
    """
    from ai_guardian.daemon.ssh_config import load_settings
    from ai_guardian.tray.ssh_connections import open_discovery_settings

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", preference)
    renderer = getattr(discovery_settings_ui, provider)
    renderer.side_effect = [{"enabled": True}, {"alias_prefix": ""}, None]
    tray = mock.Mock()
    bounds = (1920, 0, 1920, 1080)
    with mock.patch("ai_guardian.tray.menu.open_web_console") as console:
        open_discovery_settings(tray, screen_bounds=bounds)
    first, second, result = renderer.call_args_list
    assert first.args[0] == "Discover SSH aliases"
    assert (
        "Connecting and trusting a daemon still requires explicit identity review."
        in first.args[1]
    )
    assert first.args[2] == [
        {
            "name": "enabled",
            "label": "Enable SSH alias discovery",
            "type": "bool",
            "default": False,
        }
    ]
    assert first.kwargs["submit_label"] == "Continue"
    assert second.args[2] == [
        {
            "name": "alias_prefix",
            "label": "Optional alias prefix (empty lists all supported concrete aliases)",
            "default": "ai-guardian-",
        }
    ]
    assert second.kwargs["submit_label"] == "Save"
    assert result.args[1] == (
        "SSH alias discovery settings saved. Candidates refresh automatically; saved trust is unchanged."
    )
    assert result.kwargs["submit_label"] == "Close"
    assert load_settings() == {"enabled": True, "alias_prefix": ""}
    if provider != "native":
        assert all(
            call.kwargs["screen_bounds"] == bounds for call in renderer.call_args_list
        )
    for other in {"native", "tk", "browser"} - {provider}:
        getattr(discovery_settings_ui, other).assert_not_called()
    tray._refresh_event.set.assert_called_once()
    assert not tray._discovery.mock_calls
    console.assert_not_called()


@pytest.mark.parametrize("responses", [[None], [{"enabled": True}, None]])
@pytest.mark.parametrize(
    "preference,provider",
    [("auto", "native"), ("tkinter", "tk"), ("nicegui", "browser")],
)
def test_discovery_settings_cancel_close_is_terminal_and_nonmutating(
    discovery_settings_ui, monkeypatch, responses, preference, provider
):
    """USER EXPERIENCE: Cancel/Close on either step → no settings, no replacement."""
    from ai_guardian.tray.ssh_connections import open_discovery_settings

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", preference)
    getattr(discovery_settings_ui, provider).side_effect = responses
    tray = mock.Mock()
    open_discovery_settings(tray)
    assert not discovery_settings_ui.path.exists()
    tray._refresh_event.set.assert_not_called()
    assert not tray._discovery.mock_calls
    for other in {"native", "tk", "browser"} - {provider}:
        getattr(discovery_settings_ui, other).assert_not_called()


def test_discovery_settings_startup_fallback_keeps_all_controls(discovery_settings_ui):
    """USER EXPERIENCE: only proven startup failure advances Native → Tk → browser."""
    from ai_guardian.tray.ssh_connections import open_discovery_settings
    from ai_guardian.ui.modal import UIUnavailable

    discovery_settings_ui.native.side_effect = UIUnavailable()
    discovery_settings_ui.tk.side_effect = UIUnavailable()
    discovery_settings_ui.browser.side_effect = [
        {"enabled": True},
        {"alias_prefix": "guardian-"},
        None,
    ]
    tray = mock.Mock()
    open_discovery_settings(tray)
    discovery_settings_ui.native.assert_called_once()
    discovery_settings_ui.tk.assert_called_once()
    first = discovery_settings_ui.browser.call_args_list[0]
    assert first.args == discovery_settings_ui.native.call_args.args
    assert first.args == discovery_settings_ui.tk.call_args.args
    assert json.loads(discovery_settings_ui.path.read_text())["daemon"]["tray"][
        "ssh_alias_discovery"
    ] == {
        "enabled": True,
        "alias_prefix": "guardian-",
    }
    tray._refresh_event.set.assert_called_once()


@pytest.mark.parametrize("after_save", [False, True])
@pytest.mark.parametrize("error", ["startup", "unknown"])
def test_discovery_settings_later_failure_never_restarts_or_resaves(
    discovery_settings_ui, after_save, error
):
    from ai_guardian.tray.ssh_connections import open_discovery_settings
    from ai_guardian.ui.modal import UIUnavailable

    responses = [{"enabled": True}]
    if after_save:
        responses.append({"alias_prefix": "guardian-"})
    responses.append(UIUnavailable() if error == "startup" else RuntimeError())
    discovery_settings_ui.native.side_effect = responses
    tray = mock.Mock()
    open_discovery_settings(tray)
    assert discovery_settings_ui.path.exists() is after_save
    assert tray._refresh_event.set.call_count == int(after_save)
    discovery_settings_ui.tk.assert_not_called()
    discovery_settings_ui.browser.assert_not_called()


def test_discovery_settings_headless_never_loads_or_saves(
    discovery_settings_ui, monkeypatch
):
    from ai_guardian.tray.ssh_connections import open_discovery_settings

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "headless")
    with mock.patch("ai_guardian.daemon.ssh_config.load_settings") as read:
        open_discovery_settings(mock.Mock())
    read.assert_not_called()
    assert not discovery_settings_ui.path.exists()
    for provider in ("native", "tk", "browser"):
        getattr(discovery_settings_ui, provider).assert_not_called()


def test_discovery_settings_validation_is_actionable_without_partial_save(
    discovery_settings_ui,
):
    from ai_guardian.tray.ssh_connections import open_discovery_settings

    discovery_settings_ui.native.side_effect = [
        {"enabled": True},
        {"alias_prefix": "*"},
        None,
    ]
    tray = mock.Mock()
    open_discovery_settings(tray)
    retry = discovery_settings_ui.native.call_args
    assert retry.args[1].endswith(
        "Use a literal SSH alias prefix (letters, numbers, dots, underscores or hyphens), or leave it empty for all concrete aliases."
    )
    assert retry.args[2][0]["default"] == "*"
    assert not discovery_settings_ui.path.exists()
    tray._refresh_event.set.assert_not_called()
    discovery_settings_ui.tk.assert_not_called()
    discovery_settings_ui.browser.assert_not_called()


def test_saved_discovery_settings_refresh_and_restart_preserve_existing_connections(
    discovery_settings_ui, tmp_path, monkeypatch, pairing
):
    """USER EXPERIENCE: change prefix/disable → fresh candidates, same paired worker.

    Save never probes, executes SSH or grants trust. Disabling is not removal;
    saved identity bytes, owned tunnel and worker generation remain untouched.
    """
    from ai_guardian.daemon import ssh_config
    from ai_guardian.daemon.discovery import DaemonDiscovery
    from ai_guardian.daemon.ssh_connections import SSHConnectionManager
    from ai_guardian.tray.ssh_connections import open_discovery_settings

    config = tmp_path / ".ssh" / "config"
    config.parent.mkdir()
    config.write_text("Host guardian-new existing-vm\n")
    monkeypatch.setattr(ssh_config, "user_ssh_config", lambda: config)
    store = SSHStore(tmp_path / "connections")
    store.create(pairing.profile)  # Independently reviewed, existing pairing.
    record = store.path / f"{pairing.profile.id}.json"
    original = record.read_bytes()
    manager = SSHConnectionManager(store)
    discovery = DaemonDiscovery()
    discovery._ssh_manager = manager
    tray = SimpleNamespace(_discovery=discovery, _refresh_event=mock.Mock())
    with (
        mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread") as worker,
        mock.patch("ai_guardian.daemon.ssh_connections.probe_destination") as probe,
        mock.patch("subprocess.Popen") as process,
    ):
        try:
            target = discovery.discover_ssh()[0]
            target.ssh_tunnel = tunnel = mock.Mock()
            connection = manager._connections[pairing.profile.id]
            for enabled, prefix, expected in (
                (True, "guardian-", ("guardian-new",)),
                (True, "", ("existing-vm", "guardian-new")),
                (False, "", ()),
            ):
                discovery_settings_ui.native.side_effect = [
                    {"enabled": enabled},
                    {"alias_prefix": prefix},
                    None,
                ]
                open_discovery_settings(tray)
                assert discovery.discover_ssh() == [target]
                assert discovery.ssh_alias_discovery["aliases"] == expected
                assert manager._connections[pairing.profile.id] is connection
                assert target.ssh_tunnel is tunnel
                assert record.read_bytes() == original
                assert store.load() == [pairing.profile]
                tunnel.close.assert_not_called()
            worker.return_value.start.assert_called_once()
            probe.assert_not_called()
            process.assert_not_called()
            restarted = SSHConnectionManager(SSHStore(store.path))
            try:
                assert restarted.refresh_aliases() == {
                    "enabled": False,
                    "alias_prefix": "",
                    "aliases": (),
                    "notices": (),
                }
            finally:
                restarted.close()
        finally:
            manager.close()
