"""#2612: safe suspected-secret outcomes, NOT live host-enforcement evidence.

Manual model-boundary protocol and unqualified hosts are documented in
docs/security/PASSWORD_LIKELIHOOD.md. These tests only qualify our hook response.
"""

import json
from unittest.mock import patch

import pytest

from ai_guardian.hook_processing import process_hook_data
from ai_guardian.scanners.password_likelihood import (
    INCOMPLETE_MESSAGE,
    MAX_INPUT_CHARS,
    MESSAGE,
)
from tests.fixtures.password_likelihood_corpus import TEXT, VALUE, isolated_policy


@pytest.fixture
def hook_policy():
    policy = isolated_policy("block")
    with (
        patch(
            "ai_guardian.config.loaders._load_config_file",
            side_effect=lambda *a, **kw: (policy, None),
        ),
        patch(
            "ai_guardian.hook_processing._load_pattern_server_config",
            return_value=(None, None),
        ),
    ):
        yield policy


def invoke(event, text, **extra):
    data = {"hook_event_name": event, "session_id": "synthetic-password-ux", **extra}
    if event == "UserPromptSubmit":
        data["prompt"] = text
    elif event == "PostToolUse":
        data.update(
            tool_name="Bash",
            tool_input={"command": "synthetic-fixture"},
            tool_response={"stdout": text},
        )
    else:
        data.update(
            tool_name="Write",
            tool_input={"file_path": "/synthetic/note.txt", "content": text},
        )
    return process_hook_data(data)


@pytest.mark.parametrize(
    "event", ["UserPromptSubmit", "PreToolUse", "PermissionRequest", "PostToolUse"]
)
def test_contextual_block_request_is_generic_and_contains_no_password(
    hook_policy, event
):
    """USER EXPERIENCE: opted-in block -> generic denial request, no partial hints.

    Host compliance is a separate manual release gate, especially PostToolUse.
    """
    result = invoke(event, TEXT)
    serialized = json.dumps(result)
    assert MESSAGE in result["output"]
    assert VALUE not in serialized and VALUE[:4] not in serialized
    output = json.loads(result["output"])
    specific = output.get("hookSpecificOutput", {})
    assert (
        output.get("decision") == "block"
        or specific.get("permissionDecision") == "deny"
        or specific.get("decision", {}).get("behavior") == "deny"
    )


@pytest.mark.parametrize("event", ["UserPromptSubmit", "PreToolUse", "PostToolUse"])
def test_warning_is_explicitly_advisory_not_prevention(hook_policy, event):
    hook_policy["password_likelihood"]["action"] = "warn"
    result = invoke(event, TEXT)
    assert "Advisory only; content was not blocked." in result["output"]
    assert VALUE not in json.dumps(result)
    assert json.loads(result["output"]).get("decision") != "block"


@pytest.mark.parametrize(
    "event", ["UserPromptSubmit", "PreToolUse", "PermissionRequest", "PostToolUse"]
)
@pytest.mark.parametrize("allow", [False, True])
def test_ask_default_waits_for_one_private_operation_scoped_decision(
    hook_policy, event, allow
):
    """USER EXPERIENCE: opt in → Allow Once / Block; no candidate or persistent exception.

    Manual: use synthetic text only, verify both local and remote tray dialogs,
    cancellation/timeout/disconnect, and the actual host payload boundary. These
    mocked responses alone do not prove a model never received the original text.
    """
    from ai_guardian.ui.ask_dialog import AskDecision, AskResult

    hook_policy["password_likelihood"].pop("action")
    decision = AskDecision.ALLOW_ONCE if allow else AskDecision.BLOCK
    with patch(
        "ai_guardian.ui.ask_dialog.show_ask_dialog", return_value=AskResult(decision)
    ) as dialog:
        result = invoke(event, TEXT + "\n" + TEXT)
    dialog.assert_called_once()
    assert dialog.call_args.args[0].decision_only
    output = json.loads(result["output"])
    denied = (
        output.get("decision") == "block"
        or output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        or output.get("hookSpecificOutput", {}).get("decision", {}).get("behavior")
        == "deny"
    )
    assert denied is not allow
    assert VALUE not in json.dumps(result) + repr(dialog.call_args)


@pytest.mark.parametrize("event", ["UserPromptSubmit", "PreToolUse", "PostToolUse"])
def test_allow_once_does_not_approve_later_hooks(hook_policy, event):
    from ai_guardian.ui.ask_dialog import AskDecision, AskResult

    hook_policy["password_likelihood"]["action"] = "ask"
    with patch(
        "ai_guardian.ui.ask_dialog.show_ask_dialog",
        return_value=AskResult(AskDecision.ALLOW_ONCE),
    ) as dialog:
        invoke(event, TEXT)
        invoke(event, TEXT)
    assert dialog.call_count == 2


@pytest.mark.parametrize("event", ["UserPromptSubmit", "PreToolUse", "PostToolUse"])
def test_incomplete_ask_requires_approval_without_claiming_a_positive(
    hook_policy, event
):
    from ai_guardian.ui.ask_dialog import AskDecision, AskResult

    hook_policy["password_likelihood"]["action"] = "ask"
    with patch(
        "ai_guardian.ui.ask_dialog.show_ask_dialog",
        return_value=AskResult(AskDecision.BLOCK),
    ) as dialog:
        result = invoke(event, "x" * (MAX_INPUT_CHARS + 1))
    dialog.assert_called_once()
    assert INCOMPLETE_MESSAGE in result["output"]
    assert MESSAGE not in result["output"]


def test_ask_allow_does_not_override_stronger_posttool_credential_block(hook_policy):
    from ai_guardian.ui.ask_dialog import AskDecision, AskResult
    from ai_guardian.scanners.scan_result import ScanResult

    hook_policy["password_likelihood"]["action"] = "ask"
    hook_policy["secret_scanning"]["enabled"] = True
    hook_policy["secret_redaction"] = {"enabled": False}
    strong = ScanResult(
        detected=True,
        violation_type="secret_detected",
        should_block=True,
        error_message="Existing credential detection.",
    )
    with (
        patch(
            "ai_guardian.ui.ask_dialog.show_ask_dialog",
            return_value=AskResult(AskDecision.ALLOW_ONCE),
        ),
        patch(
            "ai_guardian.hook_events.post_tool_use.run_secret_scan", return_value=strong
        ),
    ):
        result = invoke("PostToolUse", TEXT)
    assert json.loads(result["output"]).get("decision") == "block"
    assert "Existing credential detection." in result["output"]


def test_remote_ask_timeout_is_terminal_not_a_second_local_dialog(
    hook_policy, monkeypatch
):
    """USER EXPERIENCE: remote tray disconnects/times out → deny; no local retry."""
    from unittest.mock import Mock

    hook_policy["password_likelihood"]["action"] = "ask"
    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    state = Mock()
    state.is_tray_registered.return_value = True
    pending = state.queue_prompt.return_value
    pending.decision_event.wait.return_value = False
    pending.result = None
    with (
        patch("ai_guardian.daemon.get_daemon_state", return_value=state),
        patch("ai_guardian.ui.ask_dialog._is_headless_env", return_value=False),
        patch("ai_guardian.ui.ask_dialog._show_via_daemon") as local,
        patch("ai_guardian.ui.ask_dialog._show_via_subprocess") as child,
    ):
        result = invoke("UserPromptSubmit", TEXT)
    assert json.loads(result["output"]).get("decision") == "block"
    state.queue_prompt.assert_called_once()
    local.assert_not_called()
    child.assert_not_called()


@pytest.mark.parametrize("preference", ["auto", "tkinter", "nicegui", "headless"])
@pytest.mark.parametrize("startup_failure", [False, True])
def test_private_ask_retains_shared_provider_order_and_terminal_cancellation(
    monkeypatch, capsys, preference, startup_failure
):
    """USER EXPERIENCE: private Ask keeps full controls and the chosen UI contract.

    Only a proven pre-display failure permits auto Tk → NiceGUI fallback. Close,
    Escape, timeout or a terminal no-result denies without another provider.
    """
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    from argparse import Namespace
    from ai_guardian.cli_handlers import _handle_prompt_ask
    from ai_guardian.ui.modal import UIUnavailable

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", preference)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    args = Namespace(
        violation=json.dumps(
            {"violation_type": "suspected_password", "matched_text": VALUE}
        ),
        fallback="block",
        timeout=30,
        output_file=None,
    )
    with (
        patch("ai_guardian.ui.ask_dialog._TkinterAskDialog") as tkinter,
        patch("ai_guardian.ui.ask_dialog._NiceGuiAskDialog") as browser,
    ):
        tkinter.return_value.run.side_effect = (
            UIUnavailable() if startup_failure else None
        )
        tkinter.return_value.run.return_value = None
        browser.return_value.run.return_value = None
        assert _handle_prompt_ask(args) == 0
    assert tkinter.call_count == int(preference in ("auto", "tkinter"))
    assert browser.call_count == int(
        preference == "nicegui" or (preference == "auto" and startup_failure)
    )
    for provider in (tkinter, browser):
        if provider.called:
            assert provider.call_args.args[0].decision_only
            assert VALUE not in repr(provider.call_args)
    output = capsys.readouterr().out
    assert json.loads(output)["decision"] == "block"
    assert VALUE not in output


def test_ambiguous_random_candidate_cannot_become_universal_blocker(hook_policy):
    result = invoke("UserPromptSubmit", VALUE)
    assert "Advisory only" in result["output"]
    assert json.loads(result["output"]).get("decision") != "block"


def test_opt_out_preserves_original_behavior_and_payload_cannot_opt_in(hook_policy):
    hook_policy["password_likelihood"]["enabled"] = False
    result = invoke(
        "UserPromptSubmit",
        TEXT,
        config={"password_likelihood": {"enabled": True, "action": "block"}},
    )
    assert "Suspected password" not in result["output"]
    assert json.loads(result["output"]).get("decision") != "block"


@pytest.mark.asyncio
async def test_console_autosaves_human_changes_globally_without_an_extra_save_button():
    """USER EXPERIENCE: change a setting → auto-save to this daemon's global policy.

    Manual: open Secrets → Secret Scanning, including with a project selected.
    There is no Save button. Changing Outcome saves immediately but does not enable
    the feature; checking Enable explicitly opts in. Reopen to verify persistence.
    Read-only policy cannot be saved, and a failed write shows a negative notice.
    """
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    from copy import deepcopy
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from ai_guardian.web.pages import secrets

    policy = {
        "password_likelihood": {"enabled": False, "action": "ask"},
        "unrelated": 7,
    }
    writes = []
    ui = MagicMock()

    def persist(config, *, scope):
        assert scope == "global"
        writes.append(deepcopy(config))
        policy.update(config)
        return True

    async def io(callback, *args):
        return callback(*args)

    with (
        patch.object(secrets, "ui", ui),
        patch.object(secrets, "is_web_config_read_only", return_value=False),
        patch.object(secrets, "add_help_button"),
        patch.object(secrets, "field_help_icon"),
        patch.object(
            secrets, "load_web_config_global", side_effect=lambda: deepcopy(policy)
        ),
        patch.object(secrets, "save_web_config", side_effect=persist),
        patch.object(secrets.run, "io_bound", side_effect=io),
    ):
        secrets._render_password_likelihood(policy)
        assert not writes  # merely viewing the page is never consent
        ui.button.assert_not_called()
        await ui.select.return_value.on_value_change.call_args.args[0](
            SimpleNamespace(value="warn")
        )
        assert policy["password_likelihood"] == {"enabled": False, "action": "warn"}
        await ui.checkbox.return_value.on_value_change.call_args.args[0](
            SimpleNamespace(value=True)
        )
    assert policy == {
        "password_likelihood": {"enabled": True, "action": "warn"},
        "unrelated": 7,
    }
    assert len(writes) == 2


def test_budget_failure_requests_block_without_claiming_a_password_match(hook_policy):
    result = invoke("UserPromptSubmit", "x" * (MAX_INPUT_CHARS + 1))
    assert INCOMPLETE_MESSAGE in result["output"]
    assert MESSAGE not in result["output"]


def test_posttooluse_repeated_contextual_candidates_are_not_partially_redacted(
    hook_policy,
):
    result = invoke("PostToolUse", TEXT + "\n" + TEXT)
    output = json.loads(result["output"])
    assert output.get("decision") == "block"
    assert "updatedToolOutput" not in json.dumps(output)
    assert VALUE not in json.dumps(result)


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("Write", {"file_path": "/synthetic/note.txt", "content": TEXT}),
        (
            "Edit",
            {"file_path": "/synthetic/note.txt", "old_string": "", "new_string": TEXT},
        ),
        ("Bash", {"command": "printf '%s' " + TEXT}),
    ],
)
def test_argument_values_are_checked_before_nonread_tool_shortcuts(
    hook_policy, tool_name, arguments
):
    result = process_hook_data(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "synthetic-arguments",
            "tool_name": tool_name,
            "tool_input": arguments,
        }
    )
    assert MESSAGE in result["output"]
    assert VALUE not in json.dumps(result)
    assert (
        json.loads(result["output"])["hookSpecificOutput"]["permissionDecision"]
        == "deny"
    )


def test_warning_does_not_bypass_existing_posttool_credential_block(hook_policy):
    from ai_guardian.scanners.scan_result import ScanResult

    hook_policy["password_likelihood"]["action"] = "warn"
    hook_policy["secret_scanning"]["enabled"] = True
    hook_policy["secret_redaction"] = {"enabled": False}
    strong = ScanResult(
        detected=True,
        violation_type="secret_detected",
        should_block=True,
        error_message="Existing credential detection.",
    )
    with patch(
        "ai_guardian.hook_events.post_tool_use.run_secret_scan", return_value=strong
    ):
        result = invoke("PostToolUse", TEXT)
    assert json.loads(result["output"]).get("decision") == "block"
    assert "Existing credential detection." in result["output"]
    assert VALUE not in json.dumps(result)
