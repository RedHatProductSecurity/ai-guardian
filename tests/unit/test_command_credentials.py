"""Synthetic contract tests for command-aware credential argument parsing."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from ai_guardian.scanners.command_credentials import (
    CREDENTIAL_REFERENCE,
    INLINE_LITERAL,
    INTERACTIVE_AUTH,
    UNSUPPORTED_PARSE,
    analyze_command_credentials,
    run_command_credential_scan,
)
from ai_guardian.scanners.scan_result import ScanResult


def _classes(command, *, shell=None):
    return [
        finding.finding_class
        for finding in analyze_command_credentials(command, shell=shell).findings
    ]


def test_curl_user_password_separate_attached_and_equals_forms():
    commands = (
        "curl --user 'demo:FAKE_SAMPLE_PASSWORD_42' https://example.invalid",
        "curl --user=demo:FAKE_SAMPLE_PASSWORD_42 https://example.invalid",
        "curl -udemo:FAKE_SAMPLE_PASSWORD_42 https://example.invalid",
        "curl -fsSu demo:FAKE_SAMPLE_PASSWORD_42 https://example.invalid",
    )
    for command in commands:
        assert INLINE_LITERAL in _classes(command)


def test_curl_user_with_username_only_is_not_a_literal_credential():
    assert _classes("curl -u demo-user https://example.invalid") == [INTERACTIVE_AUTH]


def test_curl_headers_and_url_userinfo_find_literals_without_retaining_values():
    value = "FAKE_BEARER_SAMPLE_23"
    for command in (
        f"curl -H 'Authorization: Bearer {value}' https://example.invalid",
        f"curl https://demo:{value}@example.invalid/path",
    ):
        result = run_command_credential_scan(command, config={})
        assert result is not None and result.should_block
        assert value not in result.error_message
        assert value not in repr(result.findings)
        assert result.matched_text == ""


def test_violation_record_allowlists_command_metadata_and_drops_untrusted_values():
    value = "SYNTHETIC_PRIVATE_COMMAND_VALUE_2699"
    result = ScanResult(
        detected=True,
        violation_type="command_credential_detected",
        should_block=True,
        matched_text=value,
        matched_pattern=value,
        findings=[
            {
                "command_index": 0,
                "argument_index": 2,
                "command_family": "curl",
                "option": value,
                "finding_class": INLINE_LITERAL,
                "raw_value": value,
            }
        ],
        extra={"action": "block", "command": value},
    )

    blocked = result.to_blocked_dict(extra_fields={"command": value})
    assert blocked["findings"] == [
        {
            "command_index": 0,
            "argument_index": 2,
            "command_family": "curl",
            "option": "unsupported-option",
            "finding_class": INLINE_LITERAL,
        }
    ]
    assert value not in repr(blocked)
    result.findings[0]["finding_class"] = []
    result.findings[0]["command_family"] = []
    result.findings[0]["option"] = []
    assert result.to_blocked_dict()["findings"] == []


def test_violation_logger_discards_command_and_allowlist_payloads():
    from ai_guardian.violations.log_violation import ScanContext, log_violation

    class CaptureLogger:
        entry = None

        def log_violation(self, **kwargs):
            self.entry = kwargs

    value = "SYNTHETIC_PRIVATE_COMMAND_VALUE_2699"
    result = ScanResult(
        detected=True,
        violation_type="command_credential_detected",
        should_block=True,
        matched_text=value,
        matched_pattern=value,
        findings=[
            {
                "command_index": 0,
                "argument_index": 2,
                "command_family": "curl",
                "option": "--user",
                "finding_class": INLINE_LITERAL,
                "raw_value": value,
            }
        ],
        extra={"action": "block", "command": value},
    )
    capture = CaptureLogger()
    log_violation(
        result,
        ScanContext(
            hook_event="PreToolUse",
            tool_name="Bash",
            allowlist_content=value,
            allowlist_sensitive_values=[value],
        ),
        violation_logger=capture,
        blocked_overrides={"command": value},
        context_overrides={"command": value},
        suggestion={"command": value},
    )

    assert capture.entry is not None
    assert capture.entry["blocked"]["findings"][0]["option"] == "--user"
    assert capture.entry["context"].get("tool_name") is None
    assert capture.entry["suggestion"] == {}
    assert value not in repr(capture.entry)


def test_command_violation_persistence_failure_hides_exception_details(caplog):
    from ai_guardian.violations.log_violation import ScanContext, log_violation

    value = "SYNTHETIC_PRIVATE_COMMAND_EXCEPTION_2699"
    result = run_command_credential_scan(
        f"curl --user demo:{value} https://example.invalid/", config={}
    )
    violation_logger = Mock()
    violation_logger.log_violation.side_effect = RuntimeError(value)
    caplog.set_level(logging.CRITICAL, logger="ai_guardian.violations.log_violation")

    log_violation(
        result,
        ScanContext(hook_event="PreToolUse", tool_name="Bash"),
        violation_logger=violation_logger,
    )

    assert "Failed to persist command-credential violation" in caplog.text
    assert value not in caplog.text


def test_violation_notifications_include_command_credentials_as_safe_category():
    from ai_guardian.violations.notifications import (
        NOTIFICATION_TYPE_LABELS,
        VIOLATION_NOTIFICATION_TYPES,
    )

    assert "command_credential_detected" in VIOLATION_NOTIFICATION_TYPES
    assert (
        NOTIFICATION_TYPE_LABELS["command_credential_detected"]
        == "Command credential detected"
    )


def test_violation_logger_uses_fixed_command_credential_category():
    from ai_guardian.violations.logger import _safe_violation_label

    assert _safe_violation_label("command_credential_detected") == (
        "command_credential_detected"
    )


def test_violations_page_never_returns_command_argument_text_for_patterns():
    pytest.importorskip("nicegui", reason="NiceGUI is required by web components")
    from ai_guardian.web.pages.violations import (
        DETAIL_FIELDS,
        _extract_matched_from_violation,
    )

    value = "SYNTHETIC_PRIVATE_COMMAND_VALUE_2699"
    violation = {
        "violation_type": "command_credential_detected",
        "blocked": {"matched_text": value, "context_snippet": value},
    }
    assert _extract_matched_from_violation(violation) == ""
    assert DETAIL_FIELDS["command_credential_detected"] == [
        ("Action", "action"),
        ("Findings", "total_findings"),
        ("Reason", "reason"),
    ]


def test_console_command_policy_save_preserves_sibling_settings(monkeypatch):
    pytest.importorskip("nicegui", reason="NiceGUI is required by web components")
    from ai_guardian.web.pages import secrets

    saved = {}
    monkeypatch.setattr(secrets, "is_web_config_read_only", lambda: False)
    monkeypatch.setattr(
        secrets,
        "load_web_config_global",
        lambda: {
            "unrelated": {"enabled": True},
            "command_credential_scanning": {"enabled": True, "action": "block"},
        },
    )

    def save(config, *, scope):
        saved["config"] = config
        saved["scope"] = scope
        return True

    monkeypatch.setattr(secrets, "save_web_config", save)
    assert secrets._save_command_credential_setting("action", "warn")
    assert saved["scope"] == "global"
    assert saved["config"]["unrelated"] == {"enabled": True}
    assert saved["config"]["command_credential_scanning"] == {
        "enabled": True,
        "action": "warn",
    }
    assert not secrets._save_command_credential_setting("action", "ignore")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "value", "success"),
    [("enabled", False, True), ("action", "warn", False)],
)
async def test_console_command_controls_autosave_human_changes(key, value, success):
    pytest.importorskip("nicegui", reason="NiceGUI is required by web components")
    from ai_guardian.web.pages import secrets

    ui = MagicMock()
    save = MagicMock()
    io = AsyncMock(return_value=success)
    with (
        patch.object(secrets, "ui", ui),
        patch.object(secrets, "is_web_config_read_only", return_value=False),
        patch.object(secrets, "add_help_button"),
        patch.object(secrets, "field_help_icon"),
        patch.object(secrets, "_save_command_credential_setting", save),
        patch.object(secrets.run, "io_bound", io),
    ):
        secrets._render_command_credential_scanning({})
        io.assert_not_awaited()
        widget = (
            ui.checkbox.return_value if key == "enabled" else ui.select.return_value
        )
        await widget.on_value_change.call_args.args[0](SimpleNamespace(value=value))
    io.assert_awaited_once_with(save, key, value)
    ui.notify.assert_called_once_with(
        (
            "Global command credential settings saved"
            if success
            else "Could not save global command credential settings"
        ),
        type="positive" if success else "negative",
    )


def test_wget_password_and_header_forms_are_detected():
    assert INLINE_LITERAL in _classes(
        "wget --password=FAKE_SAMPLE_PASSWORD_42 https://example.invalid"
    )
    assert INLINE_LITERAL in _classes(
        "wget --header 'X-API-Key: FAKE_SAMPLE_KEY_42' https://example.invalid"
    )


def test_credential_file_options_are_references_not_inline_values():
    for command in (
        "curl --netrc-file ~/.netrc https://example.invalid",
        "curl --config $HOME/.curlrc https://example.invalid",
        "wget --password-file $CREDENTIAL_FILE https://example.invalid",
    ):
        assert CREDENTIAL_REFERENCE in _classes(command)
        result = run_command_credential_scan(command, config={})
        assert result is not None and not result.should_block


def test_variable_references_are_not_expanded_or_reported_as_literals():
    command = 'curl --user "demo:${API_PASSWORD}" https://example.invalid'
    result = run_command_credential_scan(command, config={})
    assert result is not None
    assert CREDENTIAL_REFERENCE in _classes(command)
    assert not result.should_block
    assert "API_PASSWORD" not in repr(result)


def test_mixed_variable_and_literal_secret_value_is_not_misclassified_as_reference():
    assert INLINE_LITERAL in _classes(
        'curl --oauth2-bearer "hardcoded${TOKEN_SUFFIX}" https://example.invalid'
    )
    # Percent syntax is not a variable reference in the supported Bash/PowerShell
    # command modes and must not turn a literal into an advisory finding.
    assert INLINE_LITERAL in _classes(
        "curl --oauth2-bearer %SYNTHETIC_TOKEN% https://example.invalid"
    )


def test_shell_comments_are_not_scanned_as_executable_arguments():
    command = (
        "curl https://example.invalid/ # --user demo:SYNTHETIC_COMMENT_VALUE\n"
        "echo complete"
    )
    assert analyze_command_credentials(command).findings == ()


def test_common_placeholders_and_auth_mode_flags_are_benign():
    for command in (
        "curl --user 'demo:<password>' https://example.invalid",
        "curl --header 'Authorization: Bearer YOUR_TOKEN' https://example.invalid",
        "curl --basic https://example.invalid",
        "wget --auth-no-challenge https://example.invalid",
    ):
        assert analyze_command_credentials(command).findings == ()


def test_powershell_headers_and_plaintext_securestring_are_supported():
    command = (
        "Invoke-RestMethod -Uri 'https://example.invalid' "
        "-Headers @{ Authorization = 'Bearer FAKE_SAMPLE_TOKEN_42' }"
    )
    assert INLINE_LITERAL in _classes(command, shell="powershell")

    secure_string = (
        "Invoke-WebRequest -Authentication Basic -Credential "
        "(New-Object PSCredential('demo', "
        "(ConvertTo-SecureString -String 'FAKE_SAMPLE_PASSWORD_42' "
        "-AsPlainText -Force)))"
    )
    assert INLINE_LITERAL in _classes(secure_string, shell="powershell")


def test_powershell_credential_reference_and_interactive_auth_are_advisory():
    reference = "Invoke-WebRequest -Authentication Basic -Credential $credential"
    interactive = "Invoke-WebRequest -Credential (Get-Credential)"
    assert _classes(reference, shell="powershell") == [CREDENTIAL_REFERENCE]
    assert _classes(interactive, shell="powershell") == [INTERACTIVE_AUTH]
    assert not run_command_credential_scan(
        reference, config={}, shell="powershell"
    ).should_block
    assert not run_command_credential_scan(
        interactive, config={}, shell="powershell"
    ).should_block


def test_powerShell_assignment_of_supported_command_fails_closed_as_incomplete():
    command = (
        "$response = Invoke-WebRequest -Headers "
        "@{ Authorization = 'Bearer SYNTHETIC_LITERAL_2699' }"
    )
    result = run_command_credential_scan(command, config={}, shell="powershell")
    assert result is not None and result.should_block
    assert UNSUPPORTED_PARSE in _classes(command, shell="powershell")
    assert "SYNTHETIC_LITERAL_2699" not in repr(result)


def test_missing_option_value_and_unsupported_wrapper_are_incomplete():
    assert UNSUPPORTED_PARSE in _classes("curl --user")
    assert UNSUPPORTED_PARSE in _classes(
        "sudo curl --user demo:FAKE_SAMPLE_PASSWORD_42"
    )
    result = run_command_credential_scan("curl --user", config={})
    assert result is not None and result.should_block
    assert "credential is confirmed" in result.error_message


def test_malformed_quoting_fails_closed_without_echoing_command_text():
    value = "FAKE_SAMPLE_PASSWORD_42"
    command = f"curl --user 'demo:{value}"
    result = run_command_credential_scan(command, config={})
    assert result is not None and result.should_block
    assert UNSUPPORTED_PARSE in _classes(command)
    assert value not in result.error_message
    assert value not in repr(result)


def test_configured_actions_apply_to_literal_findings_only():
    command = "curl --user demo:FAKE_SAMPLE_PASSWORD_42 https://example.invalid"
    assert run_command_credential_scan(command, config={}).should_block
    ask = run_command_credential_scan(command, config={"action": "ask"})
    assert ask is not None and ask.should_block
    assert ask.extra["action"] == "ask"
    assert "Approve Once" in ask.error_message
    assert not run_command_credential_scan(
        command, config={"action": "warn"}
    ).should_block
    assert run_command_credential_scan(
        command, config={"action": "warn"}
    ).error_message.startswith("Inline credential argument detected")
    assert (
        run_command_credential_scan(
            command, config={"action": "log-only"}
        ).error_message
        == ""
    )
    # Malformed policy never weakens the default block.
    assert run_command_credential_scan(
        command, config={"action": "unknown"}
    ).should_block
    assert run_command_credential_scan(command, config={"action": []}).should_block


def test_disabled_scanner_and_unrelated_commands_are_clean():
    assert (
        run_command_credential_scan(
            "curl --user demo:FAKE_SAMPLE_PASSWORD_42",
            config={"enabled": False},
        )
        is None
    )
    assert analyze_command_credentials("echo 'curl --user demo:example'").findings == ()
    assert analyze_command_credentials("python -m pytest -q").findings == ()


def test_command_scanner_defaults_and_project_config_cannot_weaken_it():
    from ai_guardian.config.loaders import _load_command_credential_scanning_config
    from ai_guardian.config.utils import (
        GLOBAL_ONLY_SECTIONS,
        deep_merge,
        get_feature_flags,
    )
    from ai_guardian.setup.config import _get_default_config_template

    schema_path = (
        Path(__file__).resolve().parents[2]
        / "src/ai_guardian/schemas/ai-guardian-config.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    expected = {"enabled": True, "action": "block"}
    generated = _get_default_config_template()["command_credential_scanning"]
    jsonschema = pytest.importorskip("jsonschema")

    with patch(
        "ai_guardian.config.loaders._load_config_file",
        return_value=(None, None),
    ):
        assert _load_command_credential_scanning_config()[0] == expected
    assert generated["enabled"] is True
    assert generated["action"] == "block"
    assert (
        schema["properties"]["command_credential_scanning"]["properties"]["action"][
            "default"
        ]
        == "block"
    )
    jsonschema.validate({"command_credential_scanning": generated}, schema)
    root = Path(__file__).resolve().parents[2]
    for profile in ("minimal", "standard", "strict", "moderator"):
        profile_config = json.loads(
            (root / "src/ai_guardian/templates/profiles" / f"{profile}.json").read_text(
                encoding="utf-8"
            )
        )
        assert profile_config["command_credential_scanning"]["enabled"] is True
        assert profile_config["command_credential_scanning"]["action"] == "block"
    example = json.loads(
        (root / "ai-guardian-example.json").read_text(encoding="utf-8")
    )
    assert example["command_credential_scanning"]["action"] == "block"
    assert "command_credential_scanning" in GLOBAL_ONLY_SECTIONS
    assert get_feature_flags({})["command_credential_scanning"] is True
    assert (
        get_feature_flags({"command_credential_scanning": {"enabled": False}})[
            "command_credential_scanning"
        ]
        is False
    )

    base = {"command_credential_scanning": expected}
    for override in (
        {"enabled": False},
        {"action": "warn"},
        {"action": "log-only"},
    ):
        assert deep_merge(base, {"command_credential_scanning": override}) == base
        assert deep_merge({}, {"command_credential_scanning": override}) == {}


def test_command_credential_ask_is_private_and_operation_scoped():
    from ai_guardian.ask_mode import _format_ask_info_message, _handle_ask_mode_auto
    from ai_guardian.scanners.post_scan_filters import (
        PostScanContext,
        apply_post_scan_pipeline,
    )
    from ai_guardian.scanners.scanner_registry import (
        ScannerName,
        get_default_registry,
    )
    from ai_guardian.ui.ask_dialog import AskDecision, AskResult

    value = "SYNTHETIC_PRIVATE_COMMAND_VALUE_2699"
    result = run_command_credential_scan(
        f"curl --user demo:{value} https://example.invalid/",
        config={"action": "ask"},
    )
    audit = Mock()
    with patch(
        "ai_guardian.ui.ask_dialog.show_ask_dialog",
        return_value=AskResult(AskDecision.ALLOW_ONCE),
    ) as dialog:
        decision = apply_post_scan_pipeline(
            get_default_registry().get(ScannerName.COMMAND_CREDENTIAL_SCANNING),
            result,
            PostScanContext(
                handle_ask_mode_auto=_handle_ask_mode_auto,
                log_ask_decision=Mock(),
                format_ask_info_message=_format_ask_info_message,
                hook_event="PreToolUse",
                violation_logger=audit,
            ),
        )

    assert not decision.should_block
    info = dialog.call_args.args[0]
    assert info.decision_only
    assert info.config_section == "command_credential_scanning"
    assert info.matched_text == ""
    assert value not in repr(info)
    assert value not in repr(audit.log_violation.call_args)


def test_sdk_command_scan_pipeline_returns_separate_command_finding():
    from ai_guardian.scanners.pipeline import scan_command

    command = (
        "curl --user demo:SYNTHETIC_COMMAND_PASSWORD_2699 https://example.invalid/"
    )
    results = scan_command(
        command,
        config={
            "command_credential_scanning": {},
            "password_likelihood": {"enabled": False},
            "config_scanner": {"enabled": False},
            "exfil_detection": {"enabled": False},
        },
    )

    command_findings = [
        result
        for result in results
        if result.violation_type == "command_credential_detected"
    ]
    assert len(command_findings) == 1
    assert command_findings[0].should_block
    assert command_findings[0].rule_id == "COMMAND-CREDENTIAL-001"


def test_advisory_reference_keeps_info_severity_through_post_scan_pipeline():
    from ai_guardian.ask_mode import _format_ask_info_message, _handle_ask_mode_auto
    from ai_guardian.scanners.post_scan_filters import (
        PostScanContext,
        apply_post_scan_pipeline,
    )
    from ai_guardian.scanners.scanner_registry import (
        ScannerName,
        get_default_registry,
    )

    audit = Mock()
    reference = run_command_credential_scan(
        "curl --user demo:$CREDENTIAL_PASSWORD https://example.invalid/",
        config={},
    )
    outcome = apply_post_scan_pipeline(
        get_default_registry().get(ScannerName.COMMAND_CREDENTIAL_SCANNING),
        reference,
        PostScanContext(
            handle_ask_mode_auto=_handle_ask_mode_auto,
            log_ask_decision=Mock(),
            format_ask_info_message=_format_ask_info_message,
            hook_event="PreToolUse",
            violation_logger=audit,
        ),
        severity_override=reference.severity,
    )

    assert not outcome.should_block
    assert audit.log_violation.call_args.kwargs["severity"] == "info"


def test_shell_segments_scan_supported_commands_without_expansion():
    command = (
        "echo ready; curl --user demo:FAKE_SAMPLE_PASSWORD_42 https://example.invalid"
    )
    result = analyze_command_credentials(command)
    assert result.findings
    assert result.findings[0].command_index == 1
    assert result.findings[0].finding_class == INLINE_LITERAL


@pytest.mark.parametrize("tool_name", ("Bash", "Shell"))
def test_pretool_hook_blocks_synthetic_inline_command_credential_value(tool_name):
    from ai_guardian.hook_processing import process_hook_data
    from tests.fixtures.mock_mcp_server import create_hook_data

    value = "SYNTHETIC_PRIVATE_COMMAND_VALUE_2699"
    hook_data = create_hook_data(
        tool_name=tool_name,
        tool_input={"command": f"curl --user demo:{value} https://example.invalid/"},
    )
    with (
        patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=({}, None),
        ),
        patch(
            "ai_guardian.config.loaders._load_command_credential_scanning_config",
            return_value=({"enabled": True, "action": "block"}, None),
        ),
        patch(
            "ai_guardian.config.loaders._load_password_likelihood_config",
            return_value=({"enabled": False, "action": "ask"}, None),
        ),
    ):
        response = process_hook_data(hook_data)

    output = response["output"]
    parsed = json.loads(output)
    assert parsed["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert parsed["systemMessage"] == (
        "Inline credential argument detected; command execution was blocked. "
        "Values are withheld. This cannot retract command text already seen by the model."
    )
    assert value not in output


def test_oversized_supported_command_is_incomplete_and_unrelated_is_ignored():
    long_curl = "curl --user demo:FAKE_SAMPLE_PASSWORD_42 " + ("x" * 33_000)
    long_wrapped_curl = "sudo curl --user demo:FAKE_SAMPLE_PASSWORD_42 " + (
        "x" * 33_000
    )
    assert UNSUPPORTED_PARSE in _classes(long_curl)
    assert UNSUPPORTED_PARSE in _classes(long_wrapped_curl)
    assert analyze_command_credentials("echo " + ("x" * 33_000)).findings == ()
