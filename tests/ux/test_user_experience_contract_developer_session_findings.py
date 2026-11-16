"""UX contract for trusted developer-session non-blocking findings (#2755)."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai_guardian.constants import ActionMode, ViolationType
from ai_guardian.hook_processing import process_hook_data
from ai_guardian.scanners.scan_result import ScanResult


@pytest.fixture
def isolated_hook_config(monkeypatch):
    """Explicit scanner and permission settings; never load user configuration."""
    disabled = {
        "prompt_injection": {"enabled": False},
        "config_scanner": {"enabled": False},
        "permissions": {"enabled": False, "rules": []},
        "secret_scanning": {"enabled": False},
        "secret_redaction": {"enabled": False},
        "transcript_scanning": {"enabled": False},
        "annotations": {"enabled": False},
        "image_scanning": {"enabled": False},
        "security_instructions": {"enabled": False},
        "context_poisoning": {"enabled": False},
        "supply_chain": {"enabled": False},
        "code_scanning": {"enabled": False},
        "offensive_language": {"enabled": False},
        "canary_detection": {"enabled": False},
        "exfil_detection": {"enabled": False},
    }

    for name, config in disabled.items():
        monkeypatch.setattr(
            "ai_guardian.config.loaders._load_" + name + "_config",
            lambda config=config: (config, None),
        )

    pii_config = {
        "enabled": True,
        "pii_types": ["ssn"],
        "action": "block",
        "ignore_files": [],
    }
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_pii_config",
        lambda: (pii_config, None),
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._get_on_scan_error_action",
        lambda: ActionMode.BLOCK,
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_pattern_server_config", lambda: None
    )

    violation_logger = MagicMock()
    monkeypatch.setattr("ai_guardian.hook_processing.HAS_VIOLATION_LOGGER", True)
    violation_logger_factory = MagicMock(return_value=violation_logger)
    monkeypatch.setattr(
        "ai_guardian.hook_processing.ViolationLogger", violation_logger_factory
    )
    return pii_config, violation_logger, violation_logger_factory


def test_sensitive_prompt_finding_remains_blocked_when_input_cannot_be_replaced(
    isolated_hook_config, monkeypatch
):
    """
    USER EXPERIENCE: sensitive prompt findings stay blocked if input cannot be redacted.

    Scenario:
    1. A prompt contains synthetic PII and PII scanning is configured to block.
    2. The trusted daemon snapshot has the separate non-blocking option enabled.
    3. The hook protocol cannot replace prompt input with sanitized content.

    Expected User Experience:
    - The prompt is blocked rather than passing raw PII to the model.
    - The scanner diagnostic remains visible.
    - The PII violation is still persisted.
    """
    pii_config, violation_logger, violation_logger_factory = isolated_hook_config
    hook = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Synthetic SSN: 123-45-6789",
    }
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        lambda: True,
    )
    import ai_guardian.scanners.post_scan_filters as post_scan_filters

    log_scan_violation = MagicMock(wraps=post_scan_filters.log_scan_violation)
    monkeypatch.setattr(post_scan_filters, "log_scan_violation", log_scan_violation)

    result = process_hook_data(hook)
    response = json.loads(result["output"])
    message = response.get("systemMessage", "")

    assert pii_config["action"] == "block"
    assert result["_blocked"] is True
    assert response.get("decision") == "block"
    assert "PII" in message
    assert "non-blocking findings option" not in message
    assert "123-45-6789" not in json.dumps(response)
    violation_logger_factory.assert_called_once_with()
    assert log_scan_violation.call_count == 1
    assert log_scan_violation.call_args.args[2].violation_logger is violation_logger
    violation_logger.log_sensitive_finding.assert_called_once()
    assert violation_logger.log_sensitive_finding.call_args.kwargs[
        "violation_type"
    ] == (ViolationType.PII_DETECTED.value)


def test_normal_session_still_blocks_same_block_finding(
    isolated_hook_config,
):
    """USER EXPERIENCE: the default normal session still blocks the same finding."""
    hook = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Synthetic SSN: 123-45-6789",
    }

    result = process_hook_data(
        hook,
    )
    response = json.loads(result["output"])

    assert result["_blocked"] is True
    assert response.get("decision") == "block"
    assert "non-blocking findings option is enabled" not in json.dumps(response)


def test_daemon_without_option_snapshot_fails_closed(isolated_hook_config, monkeypatch):
    """An uncaptured daemon option never reads a live setting mid-session."""
    live_setting = MagicMock(return_value=True)
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        live_setting,
    )
    hook = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Synthetic SSN: 123-45-6789",
    }

    result = process_hook_data(
        hook,
        daemon_state=SimpleNamespace(developer_session_enabled=True),
    )
    response = json.loads(result["output"])

    live_setting.assert_not_called()
    assert result["_blocked"] is True
    assert response.get("decision") == "block"


def test_fail_closed_scanner_error_is_not_downgraded(isolated_hook_config, monkeypatch):
    """USER EXPERIENCE: on_scan_error=block remains fail-closed in trusted sessions."""
    scan_error = "synthetic prompt scanner failure"
    error_result = ScanResult(
        detected=False,
        violation_type=ViolationType.PROMPT_INJECTION,
        error_message=scan_error,
        extra={
            "scan_error": scan_error,
            "scanner_name": "prompt_injection",
        },
    )
    monkeypatch.setattr(
        "ai_guardian.scanners.pipeline.scan_content",
        lambda *args, **kwargs: [error_result],
    )
    hook = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "A clean synthetic prompt",
    }
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        lambda: True,
    )

    result = process_hook_data(hook)
    response = json.loads(result["output"])

    assert result["_blocked"] is True
    assert response.get("decision") == "block"
    assert "on_scan_error=block" in response.get("systemMessage", "")
    assert "non-blocking findings option is enabled" not in json.dumps(response)


def test_prompt_secret_stays_blocked_when_hook_cannot_replace_input(
    isolated_hook_config, monkeypatch
):
    """Secret prompt findings remain blocked rather than reaching the model raw."""
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_scanning_config",
        lambda: ({"enabled": True}, None),
    )
    secret_value = "synthetic-secret-marker-2755"
    message = "Synthetic secret-scanner diagnostic"
    result = ScanResult(
        detected=True,
        violation_type=ViolationType.SECRET_DETECTED,
        should_block=True,
        error_message=message,
        matched_text=secret_value,
        extra={"action": "block", "scanner_name": "secret"},
    )
    monkeypatch.setattr(
        "ai_guardian.scanners.pipeline.scan_content",
        lambda *args, **kwargs: [result],
    )
    hook = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": f"Please inspect this value: {secret_value}",
    }

    response = process_hook_data(hook)
    payload = json.loads(response["output"])

    assert response["_blocked"] is True
    assert payload.get("decision") == "block"
    assert message in payload.get("systemMessage", "")
    assert secret_value not in json.dumps(payload)


def test_opencode_prompt_secret_is_redacted_and_diagnostic_remains_visible(
    isolated_hook_config, monkeypatch
):
    """USER EXPERIENCE: OpenCode submits only sanitized prompt text and a diagnostic."""
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_scanning_config",
        lambda: ({"enabled": True}, None),
    )
    secret_value = "synthetic-secret-marker-2755"
    diagnostic = "Synthetic secret-scanner diagnostic"
    monkeypatch.setattr(
        "ai_guardian.scanners.pipeline.scan_content",
        lambda *args, **kwargs: [
            ScanResult(
                detected=True,
                violation_type=ViolationType.SECRET_DETECTED,
                should_block=True,
                error_message=diagnostic,
                matched_text=secret_value,
                extra={"action": "block", "scanner_name": "secret"},
            )
        ],
    )
    submitted_prompt = f"Please inspect this value: {secret_value}"
    hook = {
        "hook_event_name": "message.submit",
        "opencode_version": "2.0.22",
        "hook_source": "opencode",
        "prompt": submitted_prompt,
        "session_id": "synthetic-opencode-session",
        "cwd": "/tmp",
    }

    result = process_hook_data(hook)
    payload = json.loads(result["output"])

    assert result.get("_blocked") is not True
    assert payload.get("updatedPrompt") == "Please inspect this value: [REDACTED]"
    assert diagnostic in payload.get("systemMessage", "")
    assert "non-blocking findings option" in payload.get("systemMessage", "")
    assert submitted_prompt not in json.dumps(payload)
    assert secret_value not in json.dumps(payload)


def test_opencode_prompt_pii_is_redacted_when_trusted_session_is_enabled(
    isolated_hook_config, monkeypatch
):
    """USER EXPERIENCE: OpenCode submits only redacted PII prompt text."""
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        lambda: True,
    )
    pii_value = "123-45-6789"
    submitted_prompt = f"Please check this synthetic SSN: {pii_value}"
    hook = {
        "hook_event_name": "message.submit",
        "opencode_version": "2.0.22",
        "hook_source": "opencode",
        "prompt": submitted_prompt,
        "session_id": "synthetic-opencode-session",
        "cwd": "/tmp",
    }

    result = process_hook_data(hook)
    payload = json.loads(result["output"])

    assert result.get("_blocked") is not True
    assert "[REDACTED]" in payload.get("updatedPrompt", "")
    assert pii_value not in payload.get("updatedPrompt", "")
    assert "PII" in payload.get("systemMessage", "")
    assert "non-blocking findings option" in payload.get("systemMessage", "")
    assert pii_value not in json.dumps(payload)


def test_trusted_post_tool_secret_is_redacted_and_keeps_scanner_diagnostic(
    isolated_hook_config, monkeypatch
):
    """USER EXPERIENCE: trusted PostToolUse allows only sanitized secret output."""
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_scanning_config",
        lambda: ({"enabled": True, "ignore_files": [], "ignore_tools": []}, None),
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_redaction_config",
        lambda: ({"enabled": False, "action": "block"}, None),
    )
    secret_value = "synthetic-secret-marker-2755"
    tool_output = f"OPENAI_API_KEY={secret_value}"
    diagnostic = "Synthetic secret-scanner diagnostic"
    monkeypatch.setattr(
        "ai_guardian.hook_events.post_tool_use.run_secret_scan",
        lambda *args, **kwargs: ScanResult(
            detected=True,
            violation_type=ViolationType.SECRET_DETECTED,
            should_block=True,
            error_message=diagnostic,
            matched_text=secret_value,
            extra={"action": "block"},
        ),
    )
    redactor = MagicMock()
    redactor.redact.return_value = {
        "redacted_text": tool_output.replace(secret_value, "[HIDDEN]"),
        "redactions": [{"type": "Synthetic API key"}],
    }
    redactor_factory = MagicMock(return_value=redactor)
    monkeypatch.setattr(
        "ai_guardian.scanners.secret_redactor.SecretRedactor", redactor_factory
    )
    hook = {
        "hook_event_name": "PostToolUse",
        "tool_use": {"name": "Read", "input": {"file_path": "config.txt"}},
        "tool_response": {"output": tool_output},
    }

    result = process_hook_data(hook)
    response = json.loads(result["output"])

    assert result.get("_blocked", False) is False
    assert response["systemMessage"].endswith(diagnostic)
    assert secret_value not in json.dumps(response)
    assert "[HIDDEN]" in json.dumps(response)
    assert "non-blocking findings option" not in response["systemMessage"]
    assert redactor_factory.call_args.args[0]["enabled"] is True
    redactor.redact.assert_called_once_with(tool_output)


def test_trusted_post_tool_secret_remains_blocked_for_unsupported_bash_replacement(
    isolated_hook_config, monkeypatch
):
    """Claude Code currently ignores updatedToolOutput for Bash results."""
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_scanning_config",
        lambda: ({"enabled": True, "ignore_files": [], "ignore_tools": []}, None),
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_redaction_config",
        lambda: ({"enabled": False, "action": "block"}, None),
    )
    secret_value = "synthetic-bash-secret-2755"
    tool_output = f"value={secret_value}"
    diagnostic = "Synthetic secret-scanner diagnostic"
    monkeypatch.setattr(
        "ai_guardian.hook_events.post_tool_use.run_secret_scan",
        lambda *args, **kwargs: ScanResult(
            detected=True,
            violation_type=ViolationType.SECRET_DETECTED,
            should_block=True,
            error_message=diagnostic,
            matched_text=secret_value,
            extra={"action": "block"},
        ),
    )
    redactor = MagicMock()
    redactor.redact.return_value = {
        "redacted_text": tool_output.replace(secret_value, "[HIDDEN]"),
        "redactions": [{"type": "Synthetic API key"}],
    }
    monkeypatch.setattr(
        "ai_guardian.scanners.secret_redactor.SecretRedactor",
        MagicMock(return_value=redactor),
    )
    hook = {
        "hook_event_name": "PostToolUse",
        "tool_use": {"name": "Bash", "input": {"command": "cat config"}},
        "tool_response": {"output": tool_output},
    }

    result = process_hook_data(hook)
    response = json.loads(result["output"])

    assert result["_blocked"] is True
    assert response.get("decision") == "block"
    assert diagnostic in response.get("systemMessage", "")
    assert "updatedToolOutput" not in json.dumps(response)
    redactor.redact.assert_not_called()


def test_trusted_post_tool_secret_blocks_if_redaction_cannot_be_verified(
    isolated_hook_config, monkeypatch
):
    """A redactor no-op does not allow sensitive output through."""
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_scanning_config",
        lambda: ({"enabled": True, "ignore_files": [], "ignore_tools": []}, None),
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_redaction_config",
        lambda: ({"enabled": False, "action": "block"}, None),
    )
    secret_value = "synthetic-unmatched-secret-2755"
    tool_output = f"value={secret_value}"
    diagnostic = "Synthetic secret-scanner diagnostic"
    monkeypatch.setattr(
        "ai_guardian.hook_events.post_tool_use.run_secret_scan",
        lambda *args, **kwargs: ScanResult(
            detected=True,
            violation_type=ViolationType.SECRET_DETECTED,
            should_block=True,
            error_message=diagnostic,
            extra={"action": "block"},
        ),
    )
    redactor = MagicMock()
    redactor.redact.return_value = {"redacted_text": tool_output, "redactions": []}
    monkeypatch.setattr(
        "ai_guardian.scanners.secret_redactor.SecretRedactor",
        MagicMock(return_value=redactor),
    )
    hook = {
        "hook_event_name": "PostToolUse",
        "tool_use": {"name": "Bash", "input": {"command": "cat config"}},
        "tool_response": {"output": tool_output},
    }

    result = process_hook_data(hook)
    response = json.loads(result["output"])

    assert result["_blocked"] is True
    assert response.get("decision") == "block"
    assert diagnostic in response.get("systemMessage", "")


def test_post_tool_pii_finding_is_advisory_but_still_logged(
    isolated_hook_config, monkeypatch
):
    """USER EXPERIENCE: a successful PostToolUse PII finding remains visible."""
    _, violation_logger, _ = isolated_hook_config
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_scanning_config",
        lambda: ({"enabled": True, "ignore_files": [], "ignore_tools": []}, None),
    )
    monkeypatch.setattr(
        "ai_guardian.hook_events.post_tool_use.run_secret_scan",
        lambda *args, **kwargs: ScanResult.clean("secret_detected"),
    )
    hook = {
        "hook_event_name": "PostToolUse",
        "tool_use": {"name": "Read", "input": {"file_path": "data.txt"}},
        "tool_response": {"output": "Synthetic SSN: 123-45-6789"},
    }

    result = process_hook_data(hook)
    response = json.loads(result["output"])
    message = response.get("systemMessage", "")

    assert result.get("_blocked", False) is False
    assert response.get("decision") != "block"
    assert "PII" in message
    assert "Found 1 PII item(s)" in message
    updated_output = response["hookSpecificOutput"]["updatedToolOutput"]
    assert "123-45-6789" not in json.dumps(updated_output)
    violation_logger.log_sensitive_finding.assert_called_once()


def test_post_tool_pii_scan_error_remains_blocked(isolated_hook_config, monkeypatch):
    """USER EXPERIENCE: a PII scan failure is not downgraded as a finding."""
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_scanning_config",
        lambda: ({"enabled": True, "ignore_files": [], "ignore_tools": []}, None),
    )
    monkeypatch.setattr(
        "ai_guardian.hook_events.post_tool_use.run_secret_scan",
        lambda *args, **kwargs: ScanResult.clean("secret_detected"),
    )
    error = "synthetic PII scan failure"
    monkeypatch.setattr(
        "ai_guardian.hook_events.post_tool_use.run_pii_scan",
        lambda *args, **kwargs: ScanResult(
            detected=True,
            violation_type=ViolationType.PII_DETECTED,
            error_message=error,
            redactions=[],
            extra={"action": "block", "scan_error": error},
        ),
    )
    hook = {
        "hook_event_name": "PostToolUse",
        "tool_use": {"name": "Bash", "input": {"command": "cat data.txt"}},
        "tool_response": {"output": "Clean synthetic output"},
    }

    result = process_hook_data(hook)
    response = json.loads(result["output"])

    assert result["_blocked"] is True
    assert response.get("decision") == "block"
    assert error in json.dumps(response)
    assert "non-blocking findings option is enabled" not in json.dumps(response)


def test_sensitive_output_replacement_requires_verified_host_and_tool():
    """USER EXPERIENCE: unsupported replacement contracts fail closed."""
    from ai_guardian.hook_events.post_tool_use import (
        _supports_safe_post_output_replacement,
    )

    assert _supports_safe_post_output_replacement("claude_code", "Read")
    assert not _supports_safe_post_output_replacement("claude_code", "Bash")
    assert _supports_safe_post_output_replacement("cursor", "mcp__server__tool")
    assert not _supports_safe_post_output_replacement("cursor", "Read")
    assert _supports_safe_post_output_replacement("aiderdesk", "Read")
    assert _supports_safe_post_output_replacement("opencode", "Bash")
    assert _supports_safe_post_output_replacement("pi", "bash")
    assert not _supports_safe_post_output_replacement("gemini", "Read")
    assert not _supports_safe_post_output_replacement("cline", "Read")
    assert not _supports_safe_post_output_replacement("unknown", "Read")


@pytest.mark.parametrize(
    "scanner,violation_type",
    [
        ("run_prompt_injection_scan", ViolationType.PROMPT_INJECTION),
        ("run_context_poisoning_scan", ViolationType.CONTEXT_POISONING),
        ("run_offensive_language_scan", ViolationType.OFFENSIVE_LANGUAGE),
    ],
)
def test_post_tool_block_scanner_findings_are_advisory_and_logged(
    isolated_hook_config, monkeypatch, scanner, violation_type
):
    """USER EXPERIENCE: PostToolUse block findings remain visible and logged."""
    _, violation_logger, _ = isolated_hook_config
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_scanning_config",
        lambda: ({"enabled": True, "ignore_files": [], "ignore_tools": []}, None),
    )
    monkeypatch.setattr(
        "ai_guardian.hook_events.post_tool_use.run_secret_scan",
        lambda *args, **kwargs: ScanResult.clean("secret_detected"),
    )
    monkeypatch.setattr(
        "ai_guardian.hook_events.post_tool_use.run_pii_scan",
        lambda *args, **kwargs: ScanResult.clean(ViolationType.PII_DETECTED),
    )
    for clean_scanner in (
        "run_prompt_injection_scan",
        "run_context_poisoning_scan",
        "run_offensive_language_scan",
    ):
        monkeypatch.setattr(
            f"ai_guardian.hook_events.post_tool_use.{clean_scanner}",
            lambda *args, **kwargs: ScanResult.clean(ViolationType.PROMPT_INJECTION),
        )

    diagnostic = f"Synthetic {violation_type.value} finding"
    monkeypatch.setattr(
        f"ai_guardian.hook_events.post_tool_use.{scanner}",
        lambda *args, **kwargs: ScanResult(
            detected=True,
            violation_type=violation_type,
            should_block=True,
            error_message=diagnostic,
            extra={"action": "block"},
        ),
    )
    hook = {
        "hook_event_name": "PostToolUse",
        "tool_use": {"name": "Bash", "input": {"command": "printf safe"}},
        "tool_response": {"output": "Safe-looking synthetic output"},
    }

    result = process_hook_data(hook)
    response = json.loads(result["output"])
    message = response.get("systemMessage", "")

    assert result.get("_blocked", False) is False
    assert response.get("decision") != "block"
    assert diagnostic in message
    assert (
        "trusted developer session's non-blocking findings option is enabled" in message
    )
    violation_logger.log_violation.assert_called_once()
    decision = violation_logger.log_violation.call_args.kwargs["policy_decision"]
    assert decision.decision == "allow"
