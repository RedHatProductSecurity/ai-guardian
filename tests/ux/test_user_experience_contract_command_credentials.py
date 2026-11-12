"""User-visible contract for pre-execution command credential protection."""

import json
from unittest.mock import patch

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
