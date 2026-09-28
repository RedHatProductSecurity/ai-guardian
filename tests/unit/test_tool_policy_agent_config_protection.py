"""Policy precedence tests for supported agent configuration protection."""

from unittest.mock import patch

import pytest

from ai_guardian.agent_config_protection import build_agent_config_inventory
from ai_guardian.tools.policy import ToolPolicyChecker


def _hook(tool_name, tool_input):
    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "hook_event_name": "PreToolUse",
    }


def _check(tmp_path, tool_name, tool_input, *, enabled=True, permissions=True):
    config = {
        "agent_config_protection": {"enabled": enabled},
        "permissions": {
            "enabled": permissions,
            "rules": [{"matcher": "*", "mode": "allow", "patterns": ["*"]}],
        },
    }
    inventory = build_agent_config_inventory(str(tmp_path))
    checker = ToolPolicyChecker(config=config)
    with (
        patch(
            "ai_guardian.tools.policy.build_agent_config_inventory",
            return_value=inventory,
        ),
        patch.object(checker, "_log_violation"),
    ):
        return checker.check_tool_allowed(_hook(tool_name, tool_input))


def test_protected_write_precedes_permissive_permissions(tmp_path):
    allowed, message, tool_name = _check(
        tmp_path,
        "Write",
        {"file_path": str(tmp_path / ".cursor" / "settings.json")},
    )

    assert allowed is False
    assert tool_name == "Write"
    assert "AI Agent Configuration Protection" in message
    assert ".cursor" not in message
    assert "allow_patterns" not in message


def test_protected_notebook_edit_and_shell_mutation_are_denied(tmp_path):
    notebook = _check(
        tmp_path,
        "NotebookEdit",
        {"notebook_path": str(tmp_path / ".codex" / "config.toml")},
        permissions=False,
    )
    shell = _check(
        tmp_path,
        "Bash",
        {"command": "mv .opencode/plugins/old.ts .opencode/plugins/new.ts"},
        permissions=False,
    )

    assert notebook[0] is False
    assert shell[0] is False


def test_grok_global_and_project_mutations_are_denied_when_permissions_disabled(
    monkeypatch, tmp_path
):
    grok_home = tmp_path / "grok-home"
    monkeypatch.setenv("GROK_HOME", str(grok_home))

    project_write = _check(
        tmp_path,
        "Write",
        {"file_path": str(tmp_path / ".grok" / "config.toml")},
        permissions=False,
    )
    global_shell = _check(
        tmp_path,
        "Bash",
        {"command": "printf '%s' value > \"$GROK_HOME/config.toml\""},
        permissions=False,
    )

    assert project_write[0] is False
    assert global_shell[0] is False
    assert "AI Agent Configuration Protection" in project_write[1]
    assert "AI Agent Configuration Protection" in global_shell[1]


@pytest.mark.parametrize("action", ["warn", "log-only"])
def test_protected_mutation_ignores_permission_action_modes(tmp_path, action):
    config = {
        "agent_config_protection": {"enabled": True},
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "Write",
                    "mode": "deny",
                    "patterns": ["*"],
                    "action": action,
                }
            ],
        },
    }
    checker = ToolPolicyChecker(config=config)
    inventory = build_agent_config_inventory(str(tmp_path))
    with (
        patch(
            "ai_guardian.tools.policy.build_agent_config_inventory",
            return_value=inventory,
        ),
        patch.object(checker, "_log_violation"),
    ):
        allowed, message, _ = checker.check_tool_allowed(
            _hook("Write", {"file_path": str(tmp_path / ".pi" / "settings.json")})
        )

    assert allowed is False
    assert "AI Agent Configuration Protection" in message


def test_explicit_disable_does_not_disable_unrelated_safe_project_file(tmp_path):
    allowed, message, _ = _check(
        tmp_path,
        "Write",
        {"file_path": str(tmp_path / "src" / "main.py")},
        enabled=False,
        permissions=False,
    )

    assert allowed is True
    assert message is None


def test_explicit_disable_does_not_remove_existing_ai_guardian_protection(tmp_path):
    allowed, message, _ = _check(
        tmp_path,
        "Write",
        {"file_path": str(tmp_path / "ai-guardian.json")},
        enabled=False,
        permissions=False,
    )

    assert allowed is False
    assert message is not None
