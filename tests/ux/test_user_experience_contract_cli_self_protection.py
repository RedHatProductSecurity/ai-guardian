"""UX contracts for immutable agent-originated AI Guardian CLI protection (#2428)."""

import json
from io import StringIO
from unittest.mock import patch

import ai_guardian
from ai_guardian.tools.policy import ToolPolicyChecker
from tests.fixtures.mock_mcp_server import create_hook_data


def _run_hook(hook_data, *, permissions_enabled=True, rules=None):
    config = {
        "permissions": {
            "enabled": permissions_enabled,
            "rules": rules or [],
        }
    }
    checker = ToolPolicyChecker(config=config)
    with (
        patch(
            "ai_guardian.hook_processing.ToolPolicyChecker",
            return_value=checker,
        ),
        patch(
            "ai_guardian.hook_processing._load_permissions_config",
            return_value=(
                {"enabled": permissions_enabled},
                None,
            ),
        ),
        patch(
            "ai_guardian.hook_processing._load_pattern_server_config",
            return_value=None,
        ),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
    ):
        return ai_guardian.process_hook_input()


def test_agent_cli_invocation_is_denied_before_execution():
    """
    USER EXPERIENCE: Agent shell invocation of any AI Guardian CLI command -> denied.

    Scenario:
    1. The agent requests a shell tool to run a read-only AI Guardian command.
    2. The PreToolUse hook evaluates the command before the child starts.
    3. Immutable self-protection rejects the request.

    Expected User Experience:
    - The shell child process is not started.
    - Claude Code receives a deny decision.
    - The message explains the self-protection boundary without exposing patterns,
      allowlist instructions, or bypass guidance.
    """
    result = _run_hook(
        create_hook_data(
            tool_name="Bash",
            tool_input={"command": "ai-guardian status"},
        )
    )

    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    message = response["systemMessage"]
    assert "self-protection" in message.lower()
    assert "before the child process started" in message.lower()
    assert "pattern:" not in message.lower()
    assert "allowlist" not in message.lower()
    assert "bypass" not in message.lower()


def test_immutable_cli_guard_remains_active_when_permissions_are_disabled():
    """Disabling ordinary tool permissions cannot disable CLI self-protection."""
    result = _run_hook(
        create_hook_data(
            tool_name="Bash",
            tool_input={"command": "python -m ai_guardian"},
        ),
        permissions_enabled=False,
    )

    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_cursor_shell_payload_uses_cursor_denial_contract():
    """Cursor's root command payload is denied with Cursor's response shape."""
    result = _run_hook(
        {
            "cursor_version": "1",
            "hook_name": "beforeShellExecution",
            "command": "/usr/local/bin/ai-guardian --version",
        }
    )

    response = json.loads(result["output"])
    assert response["permission"] == "deny"
    assert "pattern" not in response.get("user_message", "").lower()


@patch("ai_guardian.tools.policy.verify_active_attestation", return_value=True)
def test_verified_ai_guardian_mcp_advisor_remains_available(mock_attestation):
    """The read-only, attested MCP advisor is outside the shell CLI boundary."""
    result = _run_hook(
        create_hook_data(
            tool_name="mcp__ai-guardian__get_config",
            tool_input={},
        ),
        rules=[
            {
                "matcher": "mcp__ai-guardian__*",
                "mode": "allow",
                "patterns": ["*"],
            }
        ],
    )

    response = json.loads(result.get("output") or "{}")
    assert response.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"
    mock_attestation.assert_called_once_with("ai-guardian")
