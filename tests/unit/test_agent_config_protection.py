"""Tests for the canonical supported-agent configuration inventory."""

from pathlib import Path

import pytest

from ai_guardian.agent_config_protection import (
    AgentConfigInventory,
    ProtectedAgentPath,
    build_agent_config_inventory,
    is_agent_config_protection_enabled,
)
from ai_guardian.ide_registry import SUPPORTED_IDE_REGISTRY


def test_missing_and_malformed_protection_values_fail_closed():
    assert is_agent_config_protection_enabled({}) is True
    assert (
        is_agent_config_protection_enabled(
            {"agent_config_protection": {"enabled": "false"}}
        )
        is True
    )
    assert (
        is_agent_config_protection_enabled(
            {"agent_config_protection": {"enabled": {"value": False}}}
        )
        is True
    )
    assert (
        is_agent_config_protection_enabled(
            {"agent_config_protection": {"enabled": False}}
        )
        is False
    )


def test_inventory_resolves_project_paths_without_home_relocation(
    monkeypatch, tmp_path
):
    project = tmp_path / "workspace"
    project.mkdir()
    relocated = tmp_path / "cursor-home"
    monkeypatch.setenv("CURSOR_CONFIG_DIR", str(relocated))

    inventory = build_agent_config_inventory(str(project))

    assert inventory.match_path(str(project / ".cursor" / "hooks.json"))
    assert inventory.match_path(str(project / ".cursor" / "mcp.json"))
    assert inventory.match_path(str(relocated / "hooks.json"))
    assert inventory.match_path(str(relocated / "plugins" / "custom.js"))
    assert inventory.match_path(str(project / "src" / "main.py")) is None


def test_global_agent_configuration_roots_are_recursive(monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("OPENCODE_CONFIG_DIR", raising=False)
    inventory = build_agent_config_inventory()

    assert inventory.match_path(str(Path.home() / ".claude" / "hooks" / "custom.sh"))
    assert inventory.match_path(
        str(Path.home() / ".config" / "opencode" / "plugins" / "custom.ts")
    )


def test_grok_global_and_project_configuration_roots_are_protected(
    monkeypatch, tmp_path
):
    grok_home = tmp_path / "grok-home"
    project = tmp_path / "workspace"
    project.mkdir()
    monkeypatch.setenv("GROK_HOME", str(grok_home))

    inventory = build_agent_config_inventory(str(project))

    for path in (
        grok_home / "config.toml",
        grok_home / "hooks" / "ai-guardian.json",
        project / ".grok" / "config.toml",
        project / ".grok" / "hooks" / "ai-guardian.json",
    ):
        assert inventory.match_path(str(path)), path


def test_grok_global_and_project_shell_mutations_match_protected_inventory(
    monkeypatch, tmp_path
):
    grok_home = tmp_path / "grok-home"
    project = tmp_path / "workspace"
    project.mkdir()
    monkeypatch.setenv("GROK_HOME", str(grok_home))
    inventory = build_agent_config_inventory(str(project))

    assert inventory.match_mutation(
        "Bash", {"command": "printf '%s' value > \"$GROK_HOME/config.toml\""}
    )
    assert inventory.match_mutation(
        "Bash", {"command": "rm -f .grok/hooks/ai-guardian.json"}
    )


def test_inventory_covers_explicit_config_files_and_managed_bridges(
    monkeypatch, tmp_path
):
    project = tmp_path / "workspace"
    project.mkdir()
    opencode_config = tmp_path / "profiles" / "opencode.jsonc"
    openclaw_config = tmp_path / "profiles" / "openclaw.json"
    monkeypatch.setenv("OPENCODE_CONFIG", str(opencode_config))
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(openclaw_config))

    inventory = build_agent_config_inventory(str(project))

    assert inventory.match_path(str(opencode_config))
    assert inventory.match_path(str(opencode_config.parent / "plugins" / "custom.ts"))
    assert inventory.match_path(
        str(opencode_config.parent / "ai-guardian" / "bridge.ts")
    )
    assert inventory.match_path(str(openclaw_config))


@pytest.mark.parametrize(
    "command",
    [
        "printf '%s' value > .cursor/hooks.json",
        "sed -i 's/old/new/' .codex/config.toml",
        "rm -f .opencode/plugins/example.ts",
        "mv .crush.json .crush.json.bak",
        "python -c \"from pathlib import Path; Path('.pi/extensions/ai-guardian/index.ts').write_text('x')\"",
    ],
)
def test_shell_mutations_match_project_agent_configuration(command, tmp_path):
    inventory = build_agent_config_inventory(str(tmp_path))

    assert inventory.match_mutation("Bash", {"command": command}) is not None


def test_shell_reads_do_not_match_agent_configuration(tmp_path):
    inventory = build_agent_config_inventory(str(tmp_path))

    assert (
        inventory.match_mutation("Bash", {"command": "cat .cursor/hooks.json"}) is None
    )


@pytest.mark.parametrize(
    ("tool_name", "tool_input"),
    [
        ("Edit", {"file_path": ".claude/settings.local.json"}),
        ("Delete", {"path": ".cursor/settings.json"}),
        ("Move", {"source": ".codex/config.toml", "destination": "config.bak"}),
        ("Rename", {"old_path": ".opencode/opencode.jsonc", "new_path": "old"}),
        ("Copy", {"source_path": ".pi/extensions/example.ts", "target_path": "old"}),
        (
            "search_replace",
            {"filePath": ".grok/config.toml", "oldText": "a", "newText": "b"},
        ),
    ],
)
def test_direct_mutation_tools_match_project_agent_configuration(
    tmp_path, tool_name, tool_input
):
    inventory = build_agent_config_inventory(str(tmp_path))

    assert inventory.match_mutation(tool_name, tool_input) is not None


def test_windows_path_spelling_matches_relative_project_artifact(tmp_path):
    project = str(tmp_path)
    inventory = AgentConfigInventory(
        (
            ProtectedAgentPath(
                path=(Path(project) / ".cursor").as_posix().casefold(),
                integration="cursor",
                scope="project",
                recursive=True,
            ),
        ),
        project,
    )

    assert inventory.match_path(".cursor\\hooks.json") is not None


def test_inventory_has_a_project_artifact_root_for_every_supported_integration():
    inventory = build_agent_config_inventory("C:\\workspace")

    for integration in SUPPORTED_IDE_REGISTRY:
        assert any(
            item.integration == integration.key and item.scope == "project"
            for item in inventory.paths
        )
    assert inventory.match_path(r"C:\\workspace\\.cursor\\hooks.json") is not None
