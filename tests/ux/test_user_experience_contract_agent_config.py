"""UX contracts for supported agent configuration protection (#2443)."""

import json
from io import StringIO
from unittest.mock import patch

import ai_guardian
from ai_guardian.tools.policy import ToolPolicyChecker
from tests.fixtures.mock_mcp_server import create_hook_data


def _run_hook(*, enabled=True, permissions_enabled=False):
    config = {
        "agent_config_protection": {"enabled": enabled},
        "permissions": {"enabled": permissions_enabled, "rules": []},
    }
    hook_data = create_hook_data(
        tool_name="Write",
        tool_input={"file_path": ".cursor/settings.json"},
    )
    with (
        patch(
            "ai_guardian.hook_processing._load_permissions_config",
            return_value=(
                {"enabled": permissions_enabled, "rules": []},
                None,
            ),
        ),
        patch(
            "ai_guardian.hook_processing._load_agent_config_protection_config",
            return_value=({"enabled": enabled}, None),
        ),
        patch(
            "ai_guardian.hook_processing.ToolPolicyChecker",
            side_effect=lambda **kwargs: ToolPolicyChecker(config=config, **kwargs),
        ),
        patch(
            "ai_guardian.hook_processing._load_pattern_server_config", return_value=None
        ),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
    ):
        return ai_guardian.process_hook_input()


def test_agent_configuration_mutation_is_denied_before_tool_execution():
    """
    USER EXPERIENCE: Supported agent configuration mutation -> denied.

    The denial is independent of ordinary permission settings and does not
    reveal path-pattern or bypass instructions to the agent.
    """
    response = json.loads(_run_hook(permissions_enabled=True)["output"])

    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    message = response["systemMessage"]
    assert "AI Agent Configuration Protection" in message
    assert "blocked" in message.lower()
    assert "allowlist" not in message.lower()
    assert "bypass" not in message.lower()
    assert ".cursor" not in message


def test_agent_configuration_protection_stays_active_when_permissions_are_disabled():
    response = json.loads(_run_hook(permissions_enabled=False)["output"])

    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_explicit_global_opt_out_allows_new_protection_scope():
    response = json.loads(_run_hook(enabled=False)["output"] or "{}")

    assert response.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"
