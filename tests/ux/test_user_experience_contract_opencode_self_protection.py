"""UX contracts for OpenCode immutable configuration protection (#2425)."""

import json
from io import StringIO
from unittest.mock import patch

import pytest

import ai_guardian
from ai_guardian.tools.policy import ToolPolicyChecker


def _run_opencode_hook(tool_name, tool_input, *, permissions_enabled=True):
    config = {
        "permissions": {"enabled": permissions_enabled, "rules": []},
        "agent_config_protection": {"enabled": True},
    }
    hook_data = {
        "hook_event_name": "tool.execute.before",
        "opencode_version": "1.0.0",
        "hook_source": "opencode",
        "tool_use": {"name": tool_name, "input": tool_input},
    }
    with (
        patch(
            "ai_guardian.hook_processing._load_permissions_config",
            return_value=({"enabled": permissions_enabled, "rules": []}, None),
        ),
        patch(
            "ai_guardian.hook_processing._load_agent_config_protection_config",
            return_value=({"enabled": True}, None),
        ),
        patch(
            "ai_guardian.hook_processing.ToolPolicyChecker",
            side_effect=lambda **kwargs: ToolPolicyChecker(config=config, **kwargs),
        ),
        patch(
            "ai_guardian.hook_processing._load_pattern_server_config",
            return_value=None,
        ),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
    ):
        return ai_guardian.process_hook_input()


@pytest.mark.parametrize(
    "tool_name,tool_input",
    [
        (
            "read",
            {"filePath": "/home/user/.config/ai-guardian/ai-guardian.json"},
        ),
        (
            "read",
            {"filePath": "/home/user/project/.ai-guardian.json"},
        ),
        (
            "write",
            {
                "filePath": "/home/user/project/.ai-guardian.json",
                "content": "{}",
            },
        ),
        (
            "edit",
            {
                "filePath": "/home/user/project/.ai-guardian.json",
                "oldString": "{}",
                "newString": '{"changed": true}',
            },
        ),
    ],
)
def test_opencode_protected_configuration_is_denied(tool_name, tool_input):
    """
    USER EXPERIENCE: Native OpenCode config access -> denied before execution.

    OpenCode uses lowercase tool names and camelCase arguments. The hook must
    canonicalize those fields before immutable protection evaluates the path.
    """
    result = _run_opencode_hook(tool_name, tool_input)

    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "blocked" in response["systemMessage"].lower()


def test_opencode_safe_file_read_remains_allowed():
    """Safe OpenCode file operations continue through the hook."""
    result = _run_opencode_hook("read", {"filePath": "/tmp/project/README.md"})

    response = json.loads(result.get("output") or "{}")
    assert response.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"
