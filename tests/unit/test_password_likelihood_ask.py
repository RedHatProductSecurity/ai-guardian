"""Password-likelihood Ask reuses existing transport without exposing candidates."""

import json
import logging
from unittest.mock import Mock, patch

import pytest

from ai_guardian.ask_mode import _handle_ask_mode_auto, _format_ask_info_message
from ai_guardian.scanners.password_likelihood import (
    INCOMPLETE_MESSAGE,
    MAX_INPUT_CHARS,
    MESSAGE,
    run_password_likelihood_scan,
)
from ai_guardian.scanners.post_scan_filters import (
    PostScanContext,
    apply_post_scan_pipeline,
)
from ai_guardian.scanners.scanner_registry import ScannerName, get_default_registry
from ai_guardian.ui.ask_dialog import AskDecision, AskResult, AskViolationInfo
from tests.fixtures.password_likelihood_corpus import TEXT, VALUE, isolated_policy


def apply(result, audit=None):
    return apply_post_scan_pipeline(
        get_default_registry().get(ScannerName.PASSWORD_LIKELIHOOD),
        result,
        PostScanContext(
            handle_ask_mode_auto=_handle_ask_mode_auto,
            log_ask_decision=Mock(),
            format_ask_info_message=_format_ask_info_message,
            hook_event="UserPromptSubmit",
            violation_logger=audit,
        ),
    )


def test_opted_in_missing_action_defaults_to_unresolved_ask_not_allow():
    with patch("ai_guardian.ui.ask_dialog.show_ask_dialog") as dialog:
        result = run_password_likelihood_scan(TEXT, config={"enabled": True})
    assert result.detected and result.should_block
    assert result.extra["action"] == "ask"
    dialog.assert_not_called()  # raw/SDK/static scanning never opens a UI


@pytest.mark.parametrize("incomplete", [False, True])
@pytest.mark.parametrize("allow", [False, True])
def test_shared_pipeline_applies_approval_to_contextual_or_incomplete_analysis(
    incomplete, allow
):
    text = "x" * (MAX_INPUT_CHARS + 1) if incomplete else TEXT + "\n" + TEXT
    result = run_password_likelihood_scan(
        text, config={"enabled": True, "action": "ask"}
    )
    decision = AskDecision.ALLOW_ONCE if allow else AskDecision.BLOCK
    with patch(
        "ai_guardian.ui.ask_dialog.show_ask_dialog", return_value=AskResult(decision)
    ) as show:
        outcome = apply(result)
    assert outcome.should_block is not allow
    assert outcome.policy_decision["decision"] == ("allow" if allow else "block")
    show.assert_called_once()  # one approval for this operation, not one per value
    violation = show.call_args.args[0]
    assert VALUE not in repr(violation)
    assert violation.decision_only
    assert show.call_args.kwargs["fallback_action"] == "block"
    assert (INCOMPLETE_MESSAGE if incomplete else MESSAGE) in violation.error_message
    if allow:
        assert "allowed by user (this time only)" in " ".join(outcome.warnings)


def test_ambiguous_findings_do_not_prompt_even_with_ask_default():
    result = run_password_likelihood_scan(
        VALUE, config={"enabled": True, "action": "ask"}
    )
    with patch("ai_guardian.ui.ask_dialog.show_ask_dialog") as show:
        outcome = apply(result)
    show.assert_not_called()
    assert not outcome.should_block
    assert "Advisory only" in " ".join(outcome.warnings)


@pytest.mark.parametrize(
    "decision",
    [AskDecision.ALLOW_ALWAYS, AskDecision.SUPPRESS_IN_SOURCE, AskDecision.IGNORE_FILE],
)
def test_private_ask_rejects_persistent_exceptions_and_never_recovers_source(decision):
    with (
        patch("builtins.open", side_effect=AssertionError("No source read")) as read,
        patch(
            "ai_guardian.ui.ask_dialog.show_ask_dialog",
            return_value=AskResult(
                decision, allowlist_pattern=VALUE, ignore_path="notes.py"
            ),
        ),
        patch("ai_guardian.config.writer.save_ask_pattern") as save,
        patch("ai_guardian.ui.ask_dialog._save_ignore_path") as ignore,
    ):
        outcome = _handle_ask_mode_auto(
            "ask",
            "suspected_password",
            "password_likelihood",
            MESSAGE,
            file_path="notes.py",
            line_number=1,
        )
    assert outcome.decision == AskDecision.BLOCK
    assert VALUE not in repr(outcome)
    read.assert_not_called()
    save.assert_not_called()
    ignore.assert_not_called()


def test_private_dialog_serialization_withholds_text_patterns_and_unsafe_summary():
    from ai_guardian.ui.ask_dialog import _serialize_violation

    violation = AskViolationInfo(
        "suspected_password",
        TEXT,
        VALUE,
        "password_likelihood",
        error_message=TEXT,
        matched_pattern=VALUE,
        file_path="notes.py",
        line_number=2,
    )
    assert violation.decision_only
    assert VALUE not in json.dumps(_serialize_violation(violation))
    assert violation.matched_pattern == ""
    assert violation.error_message == MESSAGE


def test_approved_audit_records_allow_without_values_or_candidate_hashes():
    audit = Mock()
    result = run_password_likelihood_scan(
        TEXT, config={"enabled": True, "action": "ask"}
    )
    with patch(
        "ai_guardian.ui.ask_dialog.show_ask_dialog",
        return_value=AskResult(AskDecision.ALLOW_ONCE),
    ):
        apply(result, audit)
    record = audit.log_violation.call_args.kwargs
    assert record["policy_decision"].to_dict()["decision"] == "allow"
    assert VALUE not in repr(record)
    assert "allowlist_context" not in record


def test_unavailable_ui_fails_closed_and_error_text_is_withheld(caplog):
    caplog.set_level(logging.WARNING, logger="ai_guardian")
    with patch(
        "ai_guardian.ui.ask_dialog.show_ask_dialog", side_effect=RuntimeError(VALUE)
    ):
        result = _handle_ask_mode_auto(
            "ask", "suspected_password", "password_likelihood", MESSAGE
        )
    assert result.decision == AskDecision.BLOCK
    assert "Password-likelihood Ask failed; blocking, details withheld" in caplog.text
    assert VALUE not in caplog.text


def test_explicit_headless_never_launches_local_or_remote_dialog(monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "headless")
    with (
        patch("ai_guardian.ui.ask_dialog._show_via_tray_forwarding") as remote,
        patch("ai_guardian.ui.ask_dialog._show_via_daemon") as daemon,
        patch("ai_guardian.ui.ask_dialog._show_via_subprocess") as child,
    ):
        result = _handle_ask_mode_auto(
            "ask", "suspected_password", "password_likelihood", MESSAGE
        )
    assert result.decision == AskDecision.BLOCK
    for provider in (remote, daemon, child):
        provider.assert_not_called()


@pytest.mark.parametrize("decision", ["allow_once", "block"])
def test_existing_remote_queue_returns_decision_with_no_candidate_payload(
    tmp_path, monkeypatch, decision
):
    from ai_guardian.daemon.state import DaemonState

    state = DaemonState(
        config_path=tmp_path / "config.json",
        sessions_file=tmp_path / "sessions.json",
        pause_file=tmp_path / "paused",
    )
    state.register_tray("127.0.0.1", 0, poll_only=True)
    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    queued = state.queue_prompt

    def resolve(violation, fallback, timeout):
        pending = queued(violation, fallback, timeout)
        assert VALUE not in json.dumps(state.get_pending_prompts())
        assert fallback == "block"
        assert state.resolve_prompt(pending.prompt_id, {"decision": decision})
        return pending

    with (
        patch("ai_guardian.daemon.get_daemon_state", return_value=state),
        patch.object(state, "queue_prompt", side_effect=resolve) as queue,
        patch("ai_guardian.ui.ask_dialog._is_headless_env", return_value=True),
        patch("ai_guardian.ui.ask_dialog._show_via_daemon") as local,
        patch("ai_guardian.ui.ask_dialog._show_via_subprocess") as child,
    ):
        result = apply(
            run_password_likelihood_scan(
                TEXT, config={"enabled": True, "action": "ask"}
            )
        )
    assert result.should_block is (decision == "block")
    queue.assert_called_once()
    local.assert_not_called()
    child.assert_not_called()


def test_sdk_unresolved_ask_is_fail_closed_and_does_not_launch_a_dialog():
    from ai_guardian.sdk import SecurityViolation, monitor

    with (
        patch("ai_guardian.sdk._DirectSession._register_project_with_daemon"),
        patch("ai_guardian.ui.ask_dialog.show_ask_dialog") as dialog,
        monitor(config=isolated_policy("ask")) as session,
    ):
        with pytest.raises(SecurityViolation, match="Suspected password-like"):
            session.check_content(TEXT)
    dialog.assert_not_called()


def test_private_ask_audit_has_no_values_or_transcript_exception(caplog):
    from ai_guardian.ask_mode import _log_ask_decision

    caplog.set_level(logging.WARNING, logger="ai_guardian")
    audit = Mock()
    allowed = set()
    with patch("ai_guardian.ask_mode.ViolationLogger", return_value=audit):
        _log_ask_decision(
            "suspected_password",
            AskDecision.ALLOW_ONCE,
            matched_text=VALUE,
            error_msg=TEXT,
            invocation_allowed_findings=allowed,
            finding_fingerprints=[VALUE],
        )
        assert VALUE not in repr(audit.log_violation.call_args)
        assert not allowed
        audit.log_violation.side_effect = RuntimeError(VALUE)
        _log_ask_decision("suspected_password", AskDecision.BLOCK, matched_text=VALUE)
    assert (
        "Failed to persist password-likelihood Ask decision; details withheld"
        in caplog.text
    )
    assert VALUE not in caplog.text


@pytest.mark.parametrize("action", ["ask", "warn", "block"])
def test_web_save_accepts_all_explicit_outcomes_without_replacing_other_policy(action):
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    from ai_guardian.web.pages import secrets

    with (
        patch.object(secrets, "is_web_config_read_only", return_value=False),
        patch.object(secrets, "load_web_config_global", return_value={"unrelated": 7}),
        patch.object(secrets, "save_web_config", return_value=True) as save,
    ):
        assert secrets._save_password_likelihood_setting("action", action)
    assert save.call_args.args[0] == {
        "unrelated": 7,
        "password_likelihood": {"action": action},
    }
    assert save.call_args.kwargs == {"scope": "global"}


@pytest.mark.parametrize("action", ["warn", "block"])
def test_existing_saved_outcome_is_not_silently_changed_to_ask(action):
    result = run_password_likelihood_scan(
        TEXT, config={"enabled": True, "action": action}
    )
    assert result.extra["action"] == action
    assert result.should_block is (action == "block")


def test_schema_allows_ask_but_not_a_fail_open_compound_fallback():
    from pathlib import Path
    import jsonschema

    path = (
        Path(__file__).resolve().parents[2]
        / "src/ai_guardian/schemas/ai-guardian-config.schema.json"
    )
    schema = json.loads(path.read_text())["properties"]["password_likelihood"]
    assert schema["properties"]["action"]["default"] == "ask"
    jsonschema.validate({"enabled": True, "action": "ask"}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"enabled": True, "action": "ask:warn"}, schema)


@pytest.mark.parametrize("provider", ["tkinter", "nicegui"])
def test_existing_renderers_offer_only_allow_once_and_block(provider, monkeypatch):
    from unittest.mock import MagicMock
    from types import SimpleNamespace
    import sys

    violation = AskViolationInfo(
        "suspected_password",
        MESSAGE,
        VALUE,
        "password_likelihood",
        file_path="notes.py",
        line_number=2,
    )
    monkeypatch.setattr("platform.system", lambda: "Linux")
    if provider == "tkinter":
        from ai_guardian.ui.ask_dialog_tk import _TkinterAskDialog

        ttk = MagicMock()
        tk = SimpleNamespace(ttk=ttk, Label=MagicMock(), Text=MagicMock())
        monkeypatch.setitem(sys.modules, "tkinter", tk)
        with (
            patch("ai_guardian.ui.modal.create_tk_root", return_value=MagicMock()),
            patch("ai_guardian.ui.ask_dialog_tk._ensure_tcl_library"),
            patch("ai_guardian.ui.ask_dialog_tk._configure_theme_styles"),
            patch("ai_guardian.ui.ask_dialog_tk._apply_dark_root"),
        ):
            _TkinterAskDialog(violation).run()
        labels = [call.kwargs["text"] for call in ttk.Button.call_args_list]
    else:
        nicegui = pytest.importorskip(
            "nicegui", reason="NiceGUI requires Python >= 3.10"
        )
        from ai_guardian.web.ask_dialog_nicegui import _NiceGuiAskDialog

        ui = MagicMock()
        pages = []
        ui.page.return_value.side_effect = lambda page: pages.append(page) or page
        ui.run.side_effect = lambda **kwargs: pages[0]()
        with (
            patch.object(nicegui, "ui", ui),
            patch.object(nicegui, "app", MagicMock()),
            patch.object(_NiceGuiAskDialog, "_find_free_port", return_value=12345),
        ):
            _NiceGuiAskDialog(violation).run()
        labels = [call.args[0] for call in ui.button.call_args_list]
    assert labels == ["Allow Once", "Block"]
