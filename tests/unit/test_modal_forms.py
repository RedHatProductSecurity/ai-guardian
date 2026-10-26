"""Shared form dispatch and SSH pairing, without a desktop or live destination."""

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from ai_guardian.ui.modal import UIUnavailable
from ai_guardian.tray import ssh_connections
from tests.fixtures.ssh_daemon import make_pairing


@pytest.fixture
def forms(monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    with (
        patch("ai_guardian.ui.forms.NativeForm") as native,
        patch("ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess") as tk,
        patch("ai_guardian.tray.sandbox_dialog._show_nicegui_form") as browser,
    ):
        yield SimpleNamespace(native=native.return_value, tk=tk, browser=browser)


def test_forms_use_native_first_and_do_not_retry_cancel(forms):
    from ai_guardian.ui.forms import run_form_flow

    forms.native.return_value = None
    assert run_form_flow(lambda form: form("Title", "Message", [])) is None
    forms.native.assert_called_once()
    forms.tk.assert_not_called()
    forms.browser.assert_not_called()


def test_forms_advance_native_then_tk_then_browser_only_before_display(forms):
    from ai_guardian.ui.forms import run_form_flow

    forms.native.side_effect = UIUnavailable()
    forms.tk.side_effect = UIUnavailable()
    forms.browser.return_value = {"host": "known-alias"}
    assert run_form_flow(lambda form: form("Title", "Message", [])) == {
        "host": "known-alias"
    }
    forms.native.assert_called_once()
    forms.tk.assert_called_once()
    forms.browser.assert_called_once()


def test_later_form_failure_never_restarts_the_flow(forms):
    from ai_guardian.ui.forms import run_form_flow

    forms.native.side_effect = [{"host": "known-alias"}, UIUnavailable()]

    def flow(form):
        form("Host", "Message", [])
        return form("Trust", "Identity", [])

    assert run_form_flow(flow) is None
    assert forms.native.call_count == 2
    forms.tk.assert_not_called()
    forms.browser.assert_not_called()


@pytest.mark.parametrize("preference", ["tkinter", "nicegui", "headless"])
def test_forms_respect_exclusive_preferences(forms, monkeypatch, preference):
    from ai_guardian.ui.forms import run_form_flow

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", preference)
    forms.tk.return_value = None
    forms.browser.return_value = None
    assert run_form_flow(lambda form: form("Title", "Message", [])) is None
    forms.native.assert_not_called()
    assert forms.tk.call_count == int(preference == "tkinter")
    assert forms.browser.call_count == int(preference == "nicegui")


@pytest.mark.parametrize("consent", [None, {}, {"trust": False}, {"trust": "true"}])
def test_ssh_pairing_needs_a_real_explicit_confirmation(forms, tmp_path, consent):
    pairing = make_pairing(tmp_path)[0]
    tray = Mock()
    tray._discovery.ssh_manager.prepare.return_value = pairing
    forms.native.side_effect = [{"host": "known-alias"}, consent]
    ssh_connections.open_enrollment(tray)
    tray._discovery.ssh_manager.prepare.assert_called_once_with("known-alias")
    tray._discovery.ssh_manager.enroll.assert_not_called()
    forms.tk.assert_not_called()
    forms.browser.assert_not_called()


def test_ssh_success_preserves_identity_checkbox_and_never_serializes_credentials(
    forms, tmp_path
):
    from ai_guardian.ui.ssh_pairing import TRUST_LABEL

    pairing = make_pairing(tmp_path)[0]
    tray = Mock()
    tray._discovery.ssh_manager.prepare.return_value = pairing
    forms.native.side_effect = [{"host": "known-alias"}, {"trust": True}, None]
    bounds = (1920, 0, 1920, 1080)
    ssh_connections.open_enrollment(tray, screen_bounds=bounds)
    tray._discovery.ssh_manager.enroll.assert_called_once_with(pairing)
    tray._refresh_event.set.assert_called_once()
    review = forms.native.call_args_list[1]
    assert review.args[0] == "Verify SSH daemon identity"
    assert pairing.profile.server_name in review.args[1]
    assert pairing.profile.certificate_sha256 in review.args[1]
    assert review.args[2] == [
        {
            "name": "trust",
            "label": TRUST_LABEL,
            "type": "bool",
            "default": False,
            "required": True,
        }
    ]
    assert review.kwargs["submit_label"] == "Trust and add daemon"
    rendered = str(forms.native.call_args_list)
    assert pairing.profile.token not in rendered
    assert pairing.profile.ca_pem not in rendered


def test_ssh_host_cancel_does_not_even_prepare(forms):
    tray = Mock()
    forms.native.return_value = None
    ssh_connections.open_enrollment(tray)
    tray._discovery.ssh_manager.prepare.assert_not_called()
    tray._discovery.ssh_manager.enroll.assert_not_called()


def test_ssh_error_is_shown_in_the_selected_provider_without_replacement(forms):
    from ai_guardian.daemon.ssh_storage import SSHConnectionError
    from ai_guardian.daemon.ssh_tunnel import SSH_ERROR

    tray = Mock()
    tray._discovery.ssh_manager.prepare.side_effect = SSHConnectionError(SSH_ERROR)
    forms.native.side_effect = [{"host": "known-alias"}, None]
    ssh_connections.open_enrollment(tray)
    assert forms.native.call_args.args[1] == SSH_ERROR
    tray._discovery.ssh_manager.enroll.assert_not_called()
    forms.tk.assert_not_called()
    forms.browser.assert_not_called()


@pytest.mark.parametrize("provider", ["native", "tk", "browser"])
def test_unknown_provider_error_is_terminal(forms, monkeypatch, provider):
    from ai_guardian.ui.forms import run_form_flow

    if provider != "native":
        monkeypatch.setenv(
            "AI_GUARDIAN_PREFERRED_UI", "tkinter" if provider == "tk" else "nicegui"
        )
    getattr(forms, provider).side_effect = RuntimeError("Private dialog state")
    assert run_form_flow(lambda form: form("Title", "Message", [])) is None
    assert forms.native.call_count == int(provider == "native")
    assert forms.tk.call_count == int(provider == "tk")
    assert forms.browser.call_count == int(provider == "browser")


@pytest.mark.parametrize("system", ["Darwin", "Windows"])
@pytest.mark.parametrize("value", [{"host": "known-alias"}, None])
def test_native_desktop_forms_send_only_display_payload_over_utf8_stdin(
    monkeypatch, system, value
):
    from ai_guardian.ui.native_form import NativeForm

    monkeypatch.setattr("platform.system", lambda: system)
    with patch(
        "ai_guardian.ui.native_form.run_native_command",
        return_value=subprocess.CompletedProcess(
            [], 0, json.dumps({"modal_status": "complete", "value": value}), ""
        ),
    ) as command:
        bounds = (1920, 0, 1920, 1080)
        assert (
            NativeForm(screen_bounds=bounds)(
                "Title",
                "Complete Unicode review 日本語",
                [{"name": "host", "required": True}],
            )
            == value
        )
    args = command.call_args.args[0]
    assert args[0] == ("osascript" if system == "Darwin" else "powershell")
    assert "Complete Unicode review 日本語" not in str(args)
    payload = json.loads(command.call_args.kwargs["input_text"])
    assert payload["message"] == "Complete Unicode review 日本語"
    assert payload["screen_bounds"] == list(bounds)
    assert payload["field"]["label"] == "host"


@pytest.mark.parametrize("system", ["Darwin", "Windows"])
@pytest.mark.parametrize("status", ["unavailable", "failed"])
def test_native_scripts_distinguish_startup_and_post_display_failures(
    monkeypatch, system, status
):
    from ai_guardian.ui.native_form import NativeForm

    monkeypatch.setattr("platform.system", lambda: system)
    with (
        patch(
            "ai_guardian.ui.native_form.run_native_command",
            return_value=subprocess.CompletedProcess(
                [], 0, json.dumps({"modal_status": status}), ""
            ),
        ),
        pytest.raises(UIUnavailable if status == "unavailable" else RuntimeError),
    ):
        NativeForm()("Title", "Message", [])


@pytest.mark.parametrize("provider", ["zenity", "kdialog"])
@pytest.mark.parametrize("kind", ["message", "text", "bool"])
def test_linux_forms_preserve_field_and_confirmation_controls(
    monkeypatch, provider, kind
):
    from ai_guardian.ui.native_form import NativeForm

    monkeypatch.setattr("platform.system", lambda: "Linux")
    field = {
        "name": "trust" if kind == "bool" else "host",
        "label": "Full label",
        "type": kind,
        "required": True,
    }
    output = "Full label" if provider == "zenity" else "confirmed"
    if kind == "text":
        output = "known-alias"
    fields = [] if kind == "message" else [field]
    with (
        patch(
            "ai_guardian.tray.plugins._linux_dialog_provider_order",
            return_value=(provider,),
        ),
        patch(
            "ai_guardian.ui.native_form.run_native_command",
            return_value=subprocess.CompletedProcess([], 0, output + "\n", ""),
        ) as command,
    ):
        result = NativeForm()(
            "Title",
            "Complete identity review",
            fields,
            submit_label="Trust and add daemon",
        )
    assert result == (
        {}
        if kind == "message"
        else {field["name"]: True if kind == "bool" else "known-alias"}
    )
    args = command.call_args.args[0]
    assert args[0] == provider
    assert "Trust and add daemon" in args
    assert any("Complete identity review" in arg for arg in args)
    if kind == "bool":
        assert "--checklist" in args
        assert ("FALSE" if provider == "zenity" else "off") in args


@pytest.mark.parametrize("provider", ["zenity", "kdialog"])
@pytest.mark.parametrize("exit_code", [0, 1, 5])
def test_linux_unchecked_confirmation_or_cancel_is_not_approval(
    monkeypatch, provider, exit_code
):
    from ai_guardian.ui.native_form import NativeForm

    monkeypatch.setattr("platform.system", lambda: "Linux")
    with (
        patch(
            "ai_guardian.tray.plugins._linux_dialog_provider_order",
            return_value=(provider,),
        ),
        patch(
            "ai_guardian.ui.native_form.run_native_command",
            return_value=subprocess.CompletedProcess([], exit_code, "", ""),
        ) as command,
    ):
        assert (
            NativeForm()(
                "Trust",
                "Identity",
                [{"name": "trust", "type": "bool", "required": True}],
            )
            is None
        )
    command.assert_called_once()


def test_linux_native_tool_is_pinned_across_steps(monkeypatch):
    from ai_guardian.ui.native_form import NativeForm

    monkeypatch.setattr("platform.system", lambda: "Linux")
    with (
        patch(
            "ai_guardian.tray.plugins._linux_dialog_provider_order",
            return_value=("zenity", "kdialog"),
        ),
        patch(
            "ai_guardian.ui.native_form.run_native_command",
            side_effect=[
                UIUnavailable(),
                subprocess.CompletedProcess([], 0, "known-alias", ""),
                UIUnavailable(),
            ],
        ) as command,
    ):
        native = NativeForm()
        assert native("Host", "Message", [{"name": "host"}]) == {"host": "known-alias"}
        with pytest.raises(UIUnavailable):
            native("Trust", "Identity", [])
    assert [call.args[0][0] for call in command.call_args_list] == [
        "zenity",
        "kdialog",
        "kdialog",
    ]


@pytest.mark.parametrize(
    "fields",
    [
        [{"name": "one"}, {"name": "two"}],
        [{"name": "policy", "type": "textarea"}],
        [{"name": "password", "secret": True}],
        [{"name": "choice", "choices": ["one", "two"]}],
    ],
)
def test_incomplete_native_form_is_ineligible_before_any_process(fields):
    from ai_guardian.ui.native_form import NativeForm

    with patch("ai_guardian.ui.native_form.run_native_command") as command:
        with pytest.raises(UIUnavailable):
            NativeForm()("Title", "Message", fields)
    command.assert_not_called()


def test_native_transport_utf8_input_keeps_existing_no_input_locale_behavior():
    from ai_guardian.ui.modal import run_native_command

    with patch(
        "subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")
    ) as command:
        run_native_command(["unused"], input_text="Unicode 日本語")
        assert command.call_args.kwargs["input"] == "Unicode 日本語"
        assert command.call_args.kwargs["encoding"] == "utf-8"
        run_native_command(["unused"])
        assert command.call_args.kwargs["encoding"] is None


def test_linux_missing_native_commands_are_pre_display_unavailability(monkeypatch):
    from ai_guardian.ui.native_form import NativeForm

    monkeypatch.setattr("platform.system", lambda: "Linux")
    with (
        patch(
            "ai_guardian.tray.plugins._linux_dialog_provider_order",
            return_value=("zenity", "kdialog"),
        ),
        patch(
            "ai_guardian.ui.native_form.run_native_command", side_effect=UIUnavailable()
        ) as command,
        pytest.raises(UIUnavailable),
    ):
        NativeForm()("Title", "Message", [])
    assert command.call_count == 2


@pytest.mark.parametrize(
    "output", ["not-json", "null", "{}", '{"modal_status":"failed"}']
)
def test_malformed_or_failed_native_result_is_never_startup_proof(monkeypatch, output):
    from ai_guardian.ui.native_form import NativeForm

    monkeypatch.setattr("platform.system", lambda: "Windows")
    with patch(
        "ai_guardian.ui.native_form.run_native_command",
        return_value=subprocess.CompletedProcess([], 0, output, ""),
    ):
        with pytest.raises((RuntimeError, ValueError)) as failure:
            NativeForm()("Title", "Message", [])
    assert not isinstance(failure.value, UIUnavailable)


def test_linux_metadata_is_literal_not_markup(monkeypatch):
    from ai_guardian.ui.native_form import NativeForm

    monkeypatch.setattr("platform.system", lambda: "Linux")
    with (
        patch(
            "ai_guardian.tray.plugins._linux_dialog_provider_order",
            return_value=("kdialog",),
        ),
        patch(
            "ai_guardian.ui.native_form.run_native_command",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ) as command,
    ):
        NativeForm()("Identity", "Daemon: <b>untrusted</b>", [])
    text = command.call_args.args[0][-1]
    assert "&lt;b&gt;untrusted&lt;/b&gt;" in text
    assert "<b>untrusted</b>" not in text
