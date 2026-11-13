"""Goose CLI hook enforcement versus advisory/observation boundaries (#2723).

Manual QA (disposable HOME/repository, Goose v1.59.0 on Linux/macOS):
install user hooks, restart Goose, request a clean shell command and a denied
configuration mutation. The first executes; the latter returns the generic
native policy denial before execution. A failed/missing hook executable or
timeout must prevent the tool. Prompt and post-tool notifications cannot
withhold content or replace results. Desktop/native Windows are unqualified.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_guardian.hook_processing import process_hook_data
from ai_guardian.setup.hooks import IDESetup
from ai_guardian.tools.policy import ToolPolicyChecker


@pytest.fixture(autouse=True)
def isolated_goose(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "repo"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("GOOSE_PATH_ROOT", str(home))
    monkeypatch.setenv("AI_GUARDIAN_IDE_TYPE", "goose")
    monkeypatch.chdir(project)
    return home, project


def hook(tool="shell", args=None, event="PreToolUse", **fields):
    return {
        "_ide_type": "goose",
        "event": event,
        "session_id": "goose-ux",
        "tool_name": tool,
        "tool_input": args or {"command": "pwd"},
        "working_dir": str(Path.cwd()),
        **fields,
    }


def run_hook(data, config=None):
    config = config or {"permissions": {"enabled": False}}
    with (
        patch(
            "ai_guardian.hook_processing._load_pattern_server_config", return_value=None
        ),
        patch(
            "ai_guardian.hook_processing._load_secret_scanning_config",
            return_value=({"enabled": False}, None),
        ),
        patch(
            "ai_guardian.hook_processing._load_permissions_config",
            return_value=({"enabled": False}, None),
        ),
        patch(
            "ai_guardian.hook_processing.ToolPolicyChecker",
            side_effect=lambda **kwargs: ToolPolicyChecker(config=config, **kwargs),
        ),
        patch(
            "ai_guardian.hook_processing.is_trusted_developer_session",
            return_value=False,
        ),
    ):
        return process_hook_data(data)


@pytest.mark.parametrize(
    "command",
    [
        "goose --help",
        "/usr/local/bin/goose run",
        "bash -lc 'goose --help'",
        "uvx goose",
    ],
)
def test_active_goose_cli_is_denied_before_child_execution(command):
    """USER EXPERIENCE: native shell calling the active host -> generic block."""
    result = run_hook(hook(args={"command": command}))
    assert json.loads(result["output"]) == {
        "decision": "block",
        "reason": "Operation blocked by ai-guardian: tool permission denied",
    }
    assert result["_blocked"] is True
    assert result["exit_code"] == 0


@pytest.mark.parametrize(
    "tool,args",
    [
        ("write", {"path": ".goosehints", "content": "changed"}),
        (
            "edit",
            {"path": ".config/goose/settings.json", "before": "old", "after": "new"},
        ),
        ("shell", {"command": "rm -f .agents/plugins/other/hooks/hooks.json"}),
    ],
)
def test_configuration_mutations_are_blocked_with_ordinary_permissions_disabled(
    tool, args
):
    """USER EXPERIENCE: protected settings mutation -> native pre-tool block."""
    result = run_hook(hook(tool, args))
    assert json.loads(result["output"])["decision"] == "block"
    assert not (Path.cwd() / ".goosehints").exists()


@pytest.mark.parametrize(
    "command", ["pwd", "printf '%s' 'goose --help'", "git status --short"]
)
def test_clean_shell_and_documentation_mentions_remain_allowed(command):
    result = run_hook(hook(args={"command": command}))
    assert json.loads(result["output"]) == {"decision": "allow"}
    assert result["exit_code"] == 0


def test_general_config_opt_out_cannot_remove_owned_security_hooks(isolated_goose):
    home, _ = isolated_goose
    target = home / ".agents/plugins/ai-guardian-goose/hooks/hooks.json"
    config = {
        "agent_config_protection": {"enabled": False},
        "permissions": {"enabled": False},
    }
    result = run_hook(
        hook("write", {"path": str(target), "content": "changed"}), config
    )
    assert json.loads(result["output"])["decision"] == "block"
    allowed = run_hook(
        hook("write", {"path": ".goosehints", "content": "safe notes"}), config
    )
    assert json.loads(allowed["output"])["decision"] == "allow"


@pytest.mark.parametrize(
    "event", ["UserPromptSubmit", "PostToolUse", "SessionStart", "SessionEnd"]
)
def test_passive_events_do_not_emit_security_decisions_or_replacement_content(event):
    """USER EXPERIENCE: observation is not a promise to withhold unsafe content."""
    result = run_hook(
        hook(
            event=event,
            message="Describe this project",
            tool_output={"content": [{"type": "text", "text": "clean output"}]},
        )
    )
    assert result["exit_code"] == 0
    assert result["output"] is None
    assert result.get("_blocked") is not True


def test_setup_reports_effective_hooks_and_missing_mcp_without_touching_project(
    isolated_goose, monkeypatch
):
    _, project = isolated_goose
    monkeypatch.setattr("ai_guardian.setup.goose.platform.system", lambda: "Linux")
    setup = IDESetup()
    assert setup.setup_ide_hooks("goose")[0]
    status = setup.verify_ide_setup("goose")
    assert status["hooks_healthy"] is True
    assert status["mcp_installed"] is False
    assert status["healthy"] is False
    assert not (project / ".agents").exists()


@pytest.mark.parametrize("tool", ["write", "edit"])
def test_native_source_write_receives_http_credential_enforcement(tool):
    """USER EXPERIENCE: native file mutation -> shared pre-tool source gate."""
    content = 'import requests\nrequests.get("https://example.test", auth=("demo-user", "goose-synthetic-only"))\n'
    args = {"path": "client.py", "content": content, "before": "old", "after": content}
    with patch(
        "ai_guardian.config.loaders._load_http_request_credential_scanning_config",
        return_value=({"enabled": True, "action": "block"}, None),
    ):
        result = run_hook(hook(tool, args))
    assert json.loads(result["output"]) == {
        "decision": "block",
        "reason": "Operation blocked by ai-guardian: security violation",
    }
    assert result["_violation_type"] == "http_request_credential_detected"
    assert "goose-synthetic-only" not in result["output"]
    assert not (Path.cwd() / "client.py").exists()


def test_installed_plugin_controls_remain_protected_with_general_guard_off(
    isolated_goose,
):
    home, _ = isolated_goose
    (home / ".agents/plugins/ai-guardian-goose").mkdir(parents=True)
    config = {
        "agent_config_protection": {"enabled": False},
        "permissions": {"enabled": False},
    }
    result = run_hook(
        hook("write", {"path": ".config/goose/settings.json", "content": "changed"}),
        config,
    )
    assert json.loads(result["output"])["decision"] == "block"
