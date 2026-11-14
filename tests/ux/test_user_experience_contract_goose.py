"""Goose CLI hook enforcement versus advisory/observation boundaries (#2723).

Manual QA (disposable HOME/repository, Goose v1.59.0 on Linux/macOS):
install user hooks, restart Goose, request a clean shell command and a denied
configuration mutation. The first executes; the latter returns the generic
native policy denial before execution. A failed/missing hook executable or
timeout must prevent the tool. Prompt and post-tool notifications cannot
withhold content or replace results. Desktop/native Windows are unqualified.
With enforcement active, repeat control-file mutation checks in a workspace
without an installed Goose plugin: the reserved controls still deny mutations.
"""

import json
import sys
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
            "ai_guardian.hook_processing._load_agent_config_protection_config",
            return_value=(
                config.get("agent_config_protection", {"enabled": True}),
                None,
            ),
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


def test_native_image_read_obeys_directory_rules_without_ordinary_permissions(
    isolated_goose,
):
    """USER EXPERIENCE: a native file read is denied before exposing a blocked path."""
    _, project = isolated_goose
    blocked = project / "blocked-fixture"
    blocked.mkdir()
    image = blocked / "synthetic.png"
    image.write_text("synthetic fixture", encoding="utf-8")
    clean = project / "clean.png"
    clean.write_text("synthetic fixture", encoding="utf-8")
    config = {
        "permissions": {"enabled": False},
        "directory_rules": {
            "action": "block",
            "rules": [{"mode": "deny", "paths": [str(blocked)]}],
        },
    }
    result = run_hook(hook("read_image", {"source": str(image)}), config)
    assert json.loads(result["output"]) == {
        "decision": "block",
        "reason": "Operation blocked by ai-guardian: directory access blocked",
    }
    assert result["_violation_type"] == "directory_blocking"
    allowed = run_hook(hook("read_image", {"source": str(clean)}), config)
    assert json.loads(allowed["output"]) == {"decision": "allow"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink traversal contract")
def test_native_path_keeps_link_parent_traversal_for_the_directory_guard(
    isolated_goose, tmp_path
):
    """USER EXPERIENCE: linked/.. must not hide the actual denied directory."""
    _, project = isolated_goose
    blocked = tmp_path / "blocked"
    child = blocked / "child"
    child.mkdir(parents=True)
    (blocked / "synthetic.png").write_text("synthetic fixture", encoding="utf-8")
    (project / "linked").symlink_to(child, target_is_directory=True)
    config = {
        "permissions": {"enabled": False},
        "directory_rules": {
            "action": "block",
            "rules": [{"mode": "deny", "paths": [str(blocked)]}],
        },
    }
    result = run_hook(hook("read_image", {"source": "linked/../synthetic.png"}), config)
    assert json.loads(result["output"])["decision"] == "block"
    assert result["_violation_type"] == "directory_blocking"


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


@pytest.mark.parametrize("installed_scope", [None, "user", "project"])
@pytest.mark.parametrize(
    "control", ["user-config", "user-settings", "project-settings", "local-settings"]
)
@pytest.mark.parametrize("tool", ["write", "edit", "shell"])
def test_reserved_plugin_controls_remain_protected_before_and_after_installation(
    isolated_goose, installed_scope, control, tool
):
    """USER EXPERIENCE: reserved controls deny mutations regardless of installation.

    Ordinary permissions and the broader configuration preference do not remove
    this immutable boundary. The model sees only the generic denial, not paths
    or control contents. This does not claim that an absent plugin enforces hooks.
    """
    home, project = isolated_goose
    if installed_scope:
        root = home if installed_scope == "user" else project
        (root / ".agents/plugins/ai-guardian-goose").mkdir(parents=True)
    target = {
        "user-config": home / "config/config.yaml",
        "user-settings": home / ".config/goose/settings.json",
        "project-settings": project / ".config/goose/settings.json",
        "local-settings": project / ".config/goose/settings.local.json",
    }[control]
    config = {
        "agent_config_protection": {"enabled": False},
        "permissions": {"enabled": False},
    }
    args = (
        {"command": f"rm -f '{target.as_posix()}'"}
        if tool == "shell"
        else {
            "path": str(target),
            "content": "changed",
            "before": "old",
            "after": "new",
        }
    )
    result = run_hook(hook(tool, args), config)
    assert json.loads(result["output"]) == {
        "decision": "block",
        "reason": "Operation blocked by ai-guardian: tool permission denied",
    }
    assert result["_blocked"] is True
    assert result["exit_code"] == 0
    assert not target.exists()


@pytest.mark.parametrize(
    "path",
    [
        ".goosehints",
        ".agents/plugins/other/hooks/hooks.json",
        ".config/goose/preferences.json",
        "clean.py",
    ],
)
def test_reserved_controls_do_not_expand_to_unrelated_files(path):
    """USER EXPERIENCE: the narrow immutable scope leaves unrelated files alone."""
    config = {
        "agent_config_protection": {"enabled": False},
        "permissions": {"enabled": False},
    }
    result = run_hook(hook("write", {"path": path, "content": "safe notes"}), config)
    assert json.loads(result["output"]) == {"decision": "allow"}
