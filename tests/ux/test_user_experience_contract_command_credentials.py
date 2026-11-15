"""User-visible contract for pre-execution command credential protection."""

import json
import os
from unittest.mock import patch

import pytest

from ai_guardian.hook_processing import process_hook_data
from tests.fixtures.mock_mcp_server import create_hook_data


def test_inline_command_credential_is_denied_with_value_free_message():
    """USER EXPERIENCE: a supported literal credential is denied before execution.

    Scenario:
    1. A supported agent offers a native Bash PreToolUse command.
    2. The command contains a synthetic curl user/password argument.
    3. The separate command credential scanner uses its default block action.

    Expected User Experience:
    - The native hook returns permissionDecision=deny; the shell command does not run.
    - The user sees the fixed message that a literal argument was found and withheld.
    - Neither the synthetic value nor the full command appears in the response.

    Manual verification: with a supported CLI and an isolated mock/local endpoint,
    offer `curl --user demo:synthetic_value https://example.invalid/`. Confirm the
    pre-tool hook denies it before execution. Never use a real credential.
    """
    value = "SYNTHETIC_PRIVATE_COMMAND_VALUE_2699"
    hook_data = create_hook_data(
        tool_name="Bash",
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
        result = process_hook_data(hook_data)

    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert response["systemMessage"] == (
        "Inline credential argument detected; command execution was blocked. "
        "Values are withheld. This cannot retract command text already seen by the model."
    )
    assert value not in result["output"]
    assert "curl --user" not in result["output"]


@pytest.mark.parametrize(
    ("argument_name", "argument_is_argv"),
    (("cmd", False), ("input", False), ("cmd", True), ("input", True)),
)
def test_native_shell_argument_aliases_are_denied_without_echoing_values(
    argument_name, argument_is_argv
):
    """USER EXPERIENCE: alternate native shell fields receive the same block."""
    value = "SYNTHETIC_PRIVATE_COMMAND_ALIAS_2699"
    command = f"curl --user demo:{value} https://example.invalid/"
    hook_data = create_hook_data(
        tool_name="Bash",
        tool_input={
            argument_name: ["bash", "-lc", command] if argument_is_argv else command
        },
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
        result = process_hook_data(hook_data)

    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert value not in result["output"]
    assert command not in result["output"]


def test_argv_shell_script_blocks_credential_after_harmless_setup():
    """USER EXPERIENCE: later credentials in shell -c scripts are denied."""
    from scripts.agent_cli_mock_provider import TOOL_COMMANDS

    value = "synthetic_command_credential_2699"
    command = TOOL_COMMANDS["command_credential"]
    hook_data = create_hook_data(
        tool_name="Bash",
        tool_input={"command": ["bash", "-lc", command]},
    )
    latency_entries = []
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
        patch("ai_guardian.hook_processing._is_latency_enabled", return_value=True),
        patch(
            "ai_guardian.reporting.latency.LatencyLogger.log_timing",
            new=lambda _logger, entry: latency_entries.append(entry),
        ),
    ):
        result = process_hook_data(hook_data)

    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert response["systemMessage"] == (
        "Inline credential argument detected; command execution was blocked. "
        "Values are withheld. This cannot retract command text already seen by the model."
    )
    assert value not in result["output"]
    assert "curl --user" not in result["output"]
    assert latency_entries[0]["counts"] == {
        "command_credential_scan_attempts": 1,
        "command_credential_scan_results": 1,
        "command_credential_scan_blocks": 1,
    }
    assert value not in json.dumps(latency_entries[0])


def test_opencode_shell_argv_is_normalized_before_policy_and_credential_scans():
    """USER EXPERIENCE: OpenCode argv reaches immutable policy and credential scan."""
    value = "SYNTHETIC_PRIVATE_OPENCODE_COMMAND_2699"
    command = (
        "mkdir -p /tmp/agent-cli-evidence && "
        "printf 'executed\\n' > /tmp/agent-cli-evidence/command.executed && "
        f"curl --user demo:{value} https://example.invalid/"
    )
    hook_data = {
        "hook_event_name": "PreToolUse",
        "opencode_version": "1.0.0",
        "tool_name": "bash",
        "tool_use": {
            "name": "bash",
            "input": {"command": ["bash", "-lc", command]},
        },
        "tool_use_id": "synthetic-opencode-command",
        "session_id": "synthetic-opencode-command",
        # Supply native absolute workspace metadata; `/tmp` is not an absolute
        # Windows path under Python 3.13+ and triggers the earlier generic deny.
        "cwd": os.getcwd(),
    }
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
        result = process_hook_data(hook_data)

    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert response["systemMessage"] == (
        "Inline credential argument detected; command execution was blocked. "
        "Values are withheld. This cannot retract command text already seen by the model."
    )
    assert value not in result["output"]
    assert "curl --user" not in result["output"]


@pytest.mark.parametrize(
    ("agent", "argument_name", "expected_decision"),
    (("goose", "cmd", "block"), ("grok", "input", "deny")),
)
def test_goose_and_grok_native_shell_aliases_are_denied_before_execution(
    agent, argument_name, expected_decision
):
    """USER EXPERIENCE: native Goose/Grok envelopes scan non-command fields."""
    value = "SYNTHETIC_PRIVATE_NATIVE_COMMAND_2699"
    command = f"curl --user demo:{value} https://example.invalid/"
    if agent == "goose":
        hook_data = {
            "event": "PreToolUse",
            "tool_name": "shell",
            "tool_input": {argument_name: command},
            "session_id": "synthetic-session",
        }
        decision_key = "decision"
    else:
        hook_data = {
            "hookEventName": "PreToolUse",
            "toolName": "run_terminal_command",
            "toolInput": {argument_name: command},
            "sessionId": "synthetic-session",
        }
        decision_key = "decision"

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
        result = process_hook_data(hook_data)

    response = json.loads(result["output"])
    assert response[decision_key] == expected_decision
    assert value not in result["output"]
    assert command not in result["output"]


def test_violation_resolution_guidance_is_private_and_has_no_persistent_exception():
    """The Violations page must not offer a value-bearing allowlist snippet."""
    from ai_guardian.violations.guidance import get_resolution_instructions

    value = "SYNTHETIC_PRIVATE_COMMAND_VALUE_2699"
    instructions, snippet = get_resolution_instructions(
        {
            "violation_type": "command_credential_detected",
            "blocked": {"reason": value, "matched_text": value},
        }
    )
    assert "privately" in instructions
    assert "withheld" in instructions
    assert snippet == ""
    assert value not in instructions


def test_mcp_command_check_reports_advisory_block_without_echoing_literal():
    """USER EXPERIENCE: MCP recommends blocking but cannot enforce execution."""
    from ai_guardian.mcp.server import create_server

    value = "SYNTHETIC_PRIVATE_MCP_COMMAND_VALUE_2699"
    with (
        patch(
            "ai_guardian.config.loaders._load_command_credential_scanning_config",
            return_value=({"enabled": True, "action": "block"}, None),
        ),
        patch("ai_guardian.tools.policy.ToolPolicyChecker") as checker_cls,
    ):
        server = create_server()
        result = server._tool_manager._tools["check_command"].fn(
            command=f"curl --user demo:{value} https://example.invalid/"
        )

    assert result["status"] == "blocked"
    assert result["reason"] == "command_credential_detected"
    assert result["enforcement"] == "advisory"
    assert result["finding"]["finding_classes"] == ["inline_literal"]
    assert "Values are withheld" in result["message"]
    assert value not in repr(result)
    checker_cls.assert_not_called()
