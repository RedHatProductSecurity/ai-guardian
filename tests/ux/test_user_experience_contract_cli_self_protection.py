"""UX contracts for immutable agent-originated AI Guardian CLI protection (#2428)."""

import json
import os
from io import StringIO
from unittest.mock import patch

import ai_guardian
from ai_guardian.developer_session import DEVELOPER_SESSION_ENV
from ai_guardian.tools.policy import ToolPolicyChecker
from tests.fixtures.mock_mcp_server import create_hook_data


def _run_hook(
    hook_data, *, permissions_enabled=True, rules=None, developer_session=False
):
    config = {
        "permissions": {
            "enabled": permissions_enabled,
            "rules": rules or [],
        }
    }
    with (
        patch.dict(
            os.environ,
            {DEVELOPER_SESSION_ENV: "1" if developer_session else "0"},
        ),
        patch(
            "ai_guardian.hook_processing.ToolPolicyChecker",
            side_effect=lambda **kwargs: ToolPolicyChecker(
                config=config,
                **kwargs,
            ),
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


def test_trusted_developer_session_allows_cli_without_changing_user_experience():
    """
    USER EXPERIENCE: Explicit developer session -> CLI shell access is allowed.

    The opt-in is supplied by the trusted process environment before the
    session starts; hook payload fields and permission rules are not involved.
    """
    result = _run_hook(
        create_hook_data(
            tool_name="Bash",
            tool_input={"command": "ai-guardian status"},
        ),
        developer_session=True,
    )

    response = json.loads(result.get("output") or "{}")
    assert response.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"


def test_hook_payload_cannot_enable_developer_session():
    """An agent-supplied session flag does not change the default deny boundary."""
    hook_data = create_hook_data(
        tool_name="Bash",
        tool_input={"command": "ai-guardian status"},
    )
    hook_data["_developer_session"] = True
    hook_data["_ai_guardian_developer_session"] = True

    result = _run_hook(hook_data)

    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_disabled_permissions_do_not_enable_other_shell_policy_checks():
    """The immutable CLI guard does not change existing disabled-permission behavior."""
    result = _run_hook(
        create_hook_data(
            tool_name="Bash",
            tool_input={"command": "curl http://192.168.1.1/admin"},
        ),
        permissions_enabled=False,
    )

    response = json.loads(result.get("output") or "{}")
    assert response.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"


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
