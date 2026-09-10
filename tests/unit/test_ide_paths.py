"""Regression coverage for IDE-specific home and config path resolution."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ai_guardian.hook_adapters.codex import CodexAdapter
from ai_guardian.hook_adapters.copilot import CopilotAdapter
from ai_guardian.ide_paths import get_ide_home
from ai_guardian.mcp.audit import MCPAuditor
from ai_guardian.scanners.supply_chain import SupplyChainScanner
from ai_guardian.sessions.adapters import (
    ClaudeSessionAdapter,
    ClineSessionAdapter,
    CodexSessionAdapter,
    GeminiSessionAdapter,
    KiroSessionAdapter,
)
from ai_guardian.setup.hooks import IDESetup
from ai_guardian.setup.mcp import get_mcp_config_path

IDE_ENV_VARS = (
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "CURSOR_CONFIG_DIR",
    "COPILOT_HOME",
    "GEMINI_CLI_HOME",
    "CLINE_DATA_DIR",
    "CLINE_STORAGE_DIR",
    "KIRO_HOME",
    "KIRO_SESSIONS_DIR",
    "JUNIE_HOME",
    "AIDER_DESK_DIR",
    "AIDER_DESK_HOME_DIR",
    "OPENCLAW_STATE_DIR",
    "OPENCLAW_HOME",
    "OPENCLAW_CONFIG_PATH",
    "OPENCODE_CONFIG_DIR",
    "OPENCODE_CONFIG",
    "CRUSH_GLOBAL_CONFIG",
    "HOME",
    "USERPROFILE",
)

BASH_INSTALLER_TEST = pytest.mark.skipif(
    sys.platform == "win32",
    reason="install.sh is POSIX-only; Windows installer coverage uses install.ps1",
)


@pytest.fixture(autouse=True)
def clear_ide_environment(monkeypatch):
    """Prevent a developer's CLI environment from affecting path tests."""
    for env_var in IDE_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)


@pytest.mark.parametrize(
    ("ide_type", "env_var", "suffix"),
    [
        ("claude", "CLAUDE_CONFIG_DIR", ()),
        ("codex", "CODEX_HOME", ()),
        ("cursor", "CURSOR_CONFIG_DIR", ()),
        ("copilot", "COPILOT_HOME", ()),
        ("gemini", "GEMINI_CLI_HOME", (".gemini",)),
        ("cline", "CLINE_DATA_DIR", ()),
        ("zoocode", "CLINE_DATA_DIR", ()),
        ("kiro", "KIRO_HOME", ()),
        ("junie", "JUNIE_HOME", ()),
        ("aiderdesk", "AIDER_DESK_DIR", ()),
        ("openclaw", "OPENCLAW_STATE_DIR", ()),
        ("opencode", "OPENCODE_CONFIG_DIR", ()),
    ],
)
def test_get_ide_home_honors_documented_environment_variables(
    monkeypatch, tmp_path, ide_type, env_var, suffix
):
    configured_root = tmp_path / f"{ide_type}-root"
    monkeypatch.setenv(env_var, str(configured_root))

    assert get_ide_home(ide_type) == configured_root.joinpath(*suffix)


def test_home_variable_precedence(monkeypatch, tmp_path):
    aider_dir = tmp_path / "aider-dir"
    aider_home_dir = tmp_path / "aider-home-dir"
    monkeypatch.setenv("AIDER_DESK_HOME_DIR", str(aider_home_dir))
    monkeypatch.setenv("AIDER_DESK_DIR", str(aider_dir))

    assert get_ide_home("aiderdesk") == aider_dir
    monkeypatch.delenv("AIDER_DESK_DIR")
    assert get_ide_home("aiderdesk") == aider_home_dir

    state_dir = tmp_path / "openclaw-state"
    home_root = tmp_path / "openclaw-home"
    monkeypatch.setenv("OPENCLAW_HOME", str(home_root))
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))

    assert get_ide_home("openclaw") == state_dir
    monkeypatch.delenv("OPENCLAW_STATE_DIR")
    assert get_ide_home("openclaw") == home_root / ".openclaw"


def test_cline_storage_alias_still_relocates_transcript_tasks(monkeypatch, tmp_path):
    storage_dir = tmp_path / "cline-storage"
    monkeypatch.setenv("CLINE_STORAGE_DIR", str(storage_dir))

    assert ClineSessionAdapter().resolve_session_dir() == storage_dir


def test_cline_data_dir_relocates_transcript_tasks_when_storage_alias_is_absent(
    monkeypatch, tmp_path
):
    data_dir = tmp_path / "cline-data"
    monkeypatch.setenv("CLINE_DATA_DIR", str(data_dir))

    assert ClineSessionAdapter().resolve_session_dir() == data_dir


@pytest.mark.parametrize(
    ("ide_type", "env_var", "relative_path"),
    [
        ("claude", "CLAUDE_CONFIG_DIR", "settings.json"),
        ("codex", "CODEX_HOME", "hooks.json"),
        ("cursor", "CURSOR_CONFIG_DIR", "hooks.json"),
        ("copilot", "COPILOT_HOME", "hooks/hooks.json"),
        ("gemini", "GEMINI_CLI_HOME", ".gemini/settings.json"),
        ("aiderdesk", "AIDER_DESK_DIR", "extensions/ai-guardian"),
        ("openclaw", "OPENCLAW_STATE_DIR", "plugins/ai-guardian"),
        ("opencode", "OPENCODE_CONFIG_DIR", "plugins"),
    ],
)
def test_setup_paths_follow_user_home_variables(
    monkeypatch, tmp_path, ide_type, env_var, relative_path
):
    configured_root = tmp_path / f"{ide_type}-root"
    monkeypatch.setenv(env_var, str(configured_root))

    result = Path(IDESetup().get_config_path(ide_type))

    assert result == configured_root / relative_path


def test_opencode_explicit_config_file_relocates_adjacent_plugin_directory(
    monkeypatch, tmp_path
):
    config_file = tmp_path / "opencode-profile" / "settings.jsonc"
    monkeypatch.setenv("OPENCODE_CONFIG", str(config_file))

    assert Path(IDESetup().get_config_path("opencode")) == (
        config_file.parent / "plugins"
    )


@pytest.mark.parametrize(
    "ide_type,env_var",
    [
        ("cursor", "CURSOR_CONFIG_DIR"),
        ("cline", "CLINE_DATA_DIR"),
        ("zoocode", "CLINE_DATA_DIR"),
        ("kiro", "KIRO_HOME"),
        ("junie", "JUNIE_HOME"),
    ],
)
def test_project_hook_paths_are_not_redirected_to_user_home(
    monkeypatch, tmp_path, ide_type, env_var
):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv(env_var, str(tmp_path / "relocated-home"))

    if ide_type == "cursor":
        result = IDESetup().get_config_path(
            ide_type, scope="project", project_dir=str(project)
        )
        expected = str(project / ".cursor" / "hooks.json")
    else:
        result = IDESetup().get_config_path(ide_type)
        expected = {
            "cline": ".clinerules/hooks",
            "zoocode": ".clinerules/hooks",
            "kiro": ".kiro/hooks",
            "junie": ".junie/guidelines",
        }[ide_type]

    assert result == expected


def test_crush_project_path_ignores_global_config_override(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CRUSH_GLOBAL_CONFIG", str(tmp_path / "global-crush.json"))

    assert get_mcp_config_path("crush", scope="project", project_dir=str(project)) == (
        project / ".crush.json"
    )


@pytest.mark.parametrize(
    ("ide_type", "env_var", "relative_path"),
    [
        ("claude", "CLAUDE_CONFIG_DIR", ".claude.json"),
        ("cursor", "CURSOR_CONFIG_DIR", "mcp.json"),
        ("copilot", "COPILOT_HOME", "mcp-config.json"),
        ("codex", "CODEX_HOME", "config.toml"),
        ("gemini", "GEMINI_CLI_HOME", ".gemini/settings.json"),
        ("cline", "CLINE_DATA_DIR", "mcp_settings.json"),
        ("zoocode", "CLINE_DATA_DIR", "mcp_settings.json"),
        ("kiro", "KIRO_HOME", "settings/mcp.json"),
        ("junie", "JUNIE_HOME", "mcp.json"),
        ("aiderdesk", "AIDER_DESK_DIR", "settings.json"),
        ("openclaw", "OPENCLAW_STATE_DIR", "settings.json"),
    ],
)
def test_mcp_paths_follow_user_home_variables(
    monkeypatch, tmp_path, ide_type, env_var, relative_path
):
    configured_root = tmp_path / f"{ide_type}-root"
    monkeypatch.setenv(env_var, str(configured_root))

    result = get_mcp_config_path(ide_type)

    assert result == configured_root / relative_path


def test_mcp_file_overrides_take_precedence(monkeypatch, tmp_path):
    openclaw_config = tmp_path / "openclaw" / "config.json"
    crush_config = tmp_path / "crush" / "config.json"
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path / "openclaw-home"))
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(openclaw_config))
    monkeypatch.setenv("CRUSH_GLOBAL_CONFIG", str(crush_config))

    assert get_mcp_config_path("openclaw") == openclaw_config
    assert get_mcp_config_path("crush") == crush_config


def test_default_paths_remain_unchanged_without_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    assert IDESetup().get_config_path("claude") == "~/.claude/settings.json"
    assert IDESetup().get_config_path("codex") == "~/.codex/hooks.json"
    assert get_mcp_config_path("claude") == tmp_path / ".claude.json"
    assert get_mcp_config_path("codex") == tmp_path / ".codex" / "config.toml"


@pytest.mark.parametrize(
    ("adapter", "env_var", "expected_suffix"),
    [
        (ClaudeSessionAdapter(), "CLAUDE_CONFIG_DIR", ("projects",)),
        (CodexSessionAdapter(), "CODEX_HOME", ("sessions",)),
        (GeminiSessionAdapter(), "GEMINI_CLI_HOME", (".gemini", "tmp")),
        (KiroSessionAdapter(), "KIRO_HOME", ("sessions", "cli")),
    ],
)
def test_session_discovery_uses_relocated_home(
    monkeypatch, tmp_path, adapter, env_var, expected_suffix
):
    configured_root = tmp_path / "session-root"
    monkeypatch.setenv(env_var, str(configured_root))

    assert adapter.resolve_session_dir() == configured_root.joinpath(*expected_suffix)


def test_hook_adapters_use_relocated_transcript_homes(monkeypatch, tmp_path):
    copilot_home = tmp_path / "copilot"
    copilot_transcript = copilot_home / "session-state" / "events.jsonl"
    copilot_transcript.parent.mkdir(parents=True)
    copilot_transcript.touch()
    monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
    assert CopilotAdapter().get_default_transcript_paths() == [str(copilot_transcript)]

    codex_home = tmp_path / "codex"
    codex_sessions = codex_home / "sessions" / "2026" / "09" / "10"
    codex_sessions.mkdir(parents=True)
    codex_transcript = codex_sessions / "session.jsonl"
    codex_transcript.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    assert CodexAdapter().get_default_transcript_paths() == [str(codex_transcript)]


def test_mcp_audit_uses_relocated_paths_and_labels(monkeypatch, tmp_path):
    cursor_home = tmp_path / "cursor"
    monkeypatch.setenv("CURSOR_CONFIG_DIR", str(cursor_home))

    paths = {Path(path).expanduser() for path in MCPAuditor()._get_config_paths()}

    assert cursor_home / "mcp.json" in paths
    assert MCPAuditor.ide_label(str(cursor_home / "mcp.json")) == "Cursor"


def test_supply_chain_paths_follow_relocated_hook_and_plugin_homes(
    monkeypatch, tmp_path
):
    cursor_home = tmp_path / "cursor"
    opencode_home = tmp_path / "opencode"
    monkeypatch.setenv("CURSOR_CONFIG_DIR", str(cursor_home))
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(opencode_home))

    scanner = SupplyChainScanner()

    assert scanner.is_agent_config(str(cursor_home / "hooks.json"))
    assert scanner.is_agent_config(str(opencode_home / "plugins" / "third-party.ts"))


@BASH_INSTALLER_TEST
def test_installer_detection_uses_relocated_directories(tmp_path):
    script = Path(__file__).parents[2] / "install.sh"
    content = script.read_text(encoding="utf-8")
    start = content.index("detect_installed_agents()")
    end = content.index("\n}\n\n# --- Parse arguments ---", start) + 2
    detection_function = content[start:end]

    home = tmp_path / "home"
    custom_dirs = {
        "CURSOR_CONFIG_DIR": tmp_path / "cursor",
        "COPILOT_HOME": tmp_path / "copilot",
        "CODEX_HOME": tmp_path / "codex",
        "GEMINI_CLI_HOME": tmp_path / "gemini",
        "CLINE_DATA_DIR": tmp_path / "cline",
        "KIRO_HOME": tmp_path / "kiro",
        "JUNIE_HOME": tmp_path / "junie",
        "OPENCODE_CONFIG_DIR": tmp_path / "opencode",
        "AIDER_DESK_DIR": tmp_path / "aiderdesk",
        "OPENCLAW_STATE_DIR": tmp_path / "openclaw",
    }
    for directory in custom_dirs.values():
        directory.mkdir(parents=True)
    crush_config = tmp_path / "crush.json"
    crush_config.write_text("{}", encoding="utf-8")

    env = dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR="")
    env.update({name: str(path) for name, path in custom_dirs.items()})
    env["CRUSH_GLOBAL_CONFIG"] = str(crush_config)
    result = subprocess.run(
        ["bash", "-c", detection_function + "\ndetect_installed_agents"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip().split() == [
        "cursor",
        "copilot",
        "codex",
        "gemini",
        "cline",
        "kiro",
        "junie",
        "crush",
        "opencode",
        "aiderdesk",
        "openclaw",
    ]


@BASH_INSTALLER_TEST
def test_installer_detection_uses_explicit_config_files(tmp_path):
    script = Path(__file__).parents[2] / "install.sh"
    content = script.read_text(encoding="utf-8")
    start = content.index("detect_installed_agents()")
    end = content.index("\n}\n\n# --- Parse arguments ---", start) + 2
    detection_function = content[start:end]

    opencode_config = tmp_path / "opencode-profile" / "config.jsonc"
    openclaw_config = tmp_path / "openclaw-profile" / "config.json"
    opencode_config.parent.mkdir()
    openclaw_config.parent.mkdir()

    env = dict(os.environ)
    for env_var in IDE_ENV_VARS:
        env.pop(env_var, None)
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "OPENCODE_CONFIG": str(opencode_config),
            "OPENCLAW_CONFIG_PATH": str(openclaw_config),
        }
    )
    result = subprocess.run(
        ["bash", "-c", detection_function + "\ndetect_installed_agents"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip().split() == ["opencode", "openclaw"]


def test_daemon_mcp_status_uses_custom_copilot_home(monkeypatch, tmp_path):
    from ai_guardian.daemon import is_mcp_installed

    copilot_home = tmp_path / "copilot"
    copilot_home.mkdir()
    (copilot_home / "mcp-config.json").write_text(
        json.dumps({"mcpServers": {"ai-guardian": {}}}), encoding="utf-8"
    )
    monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

    assert is_mcp_installed() is True
