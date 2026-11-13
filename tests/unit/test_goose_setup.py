"""Isolated Goose plugin setup, health, scope, and configuration preservation."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_guardian.constants import GOOSE_MANAGED_HOOK_EVENTS
from ai_guardian.goose_support import (
    GOOSE_PLUGIN_NAME,
    goose_config_dir,
    goose_hook_path,
    goose_user_settings_path,
)
from ai_guardian.setup.goose import expected_hooks
from ai_guardian.setup.hooks import IDESetup
from ai_guardian.setup.mcp import (
    _install_mcp_config,
    _remove_mcp_config,
    get_mcp_config_path,
    verify_mcp_config,
)


@pytest.fixture(autouse=True)
def isolated_goose(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "repo"
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("APPDATA", str(home / "AppData/Roaming"))
    monkeypatch.delenv("GOOSE_PATH_ROOT", raising=False)
    monkeypatch.chdir(project)
    monkeypatch.setattr("ai_guardian.setup.goose.platform.system", lambda: "Linux")
    monkeypatch.setattr(
        "ai_guardian.setup.goose._resolve_binary_path",
        lambda: "/opt/guardian tools/ai-guardian",
    )
    monkeypatch.setattr(
        "ai_guardian.setup.mcp._resolve_binary_path",
        lambda: "/opt/guardian tools/ai-guardian",
    )
    monkeypatch.setattr("ai_guardian.setup.mcp._register_mcp_identity", lambda *_: True)
    return home, project


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def install(setup=None, **kwargs):
    setup = setup or IDESetup()
    success, message = setup.setup_ide_hooks("goose", **kwargs)
    assert success, message
    return setup


def test_fresh_setup_is_user_only_and_idempotent(isolated_goose):
    home, project = isolated_goose
    setup = install()
    path = goose_hook_path()
    assert path == home / ".agents/plugins" / GOOSE_PLUGIN_NAME / "hooks/hooks.json"
    config = json.loads(path.read_text())
    assert set(config["hooks"]) == set(GOOSE_MANAGED_HOOK_EVENTS)
    action = config["hooks"]["PreToolUse"][0]["hooks"][0]
    assert action == {
        "type": "command",
        "command": "'/opt/guardian tools/ai-guardian' --ide goose",
        "timeout": 360,
        "on_failure": "block",
    }
    assert "Stop" not in config["hooks"]
    before = {
        target: target.read_bytes()
        for target in path.parent.parent.rglob("*")
        if target.is_file()
    }
    install(setup, force=True)
    assert {target: target.read_bytes() for target in before} == before
    assert not list(path.parent.parent.rglob("*.backup*"))
    assert not (project / ".agents").exists()
    assert setup.verify_hooks_for_ide("goose")["healthy"]


def test_relocation_is_a_process_root_and_does_not_follow_xdg(tmp_path, monkeypatch):
    root = tmp_path / "relocated"
    monkeypatch.setenv("GOOSE_PATH_ROOT", str(root))
    monkeypatch.setattr("ai_guardian.goose_support.sys.platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert goose_config_dir() == root / "config"
    assert (
        goose_hook_path()
        == root / ".agents/plugins" / GOOSE_PLUGIN_NAME / "hooks/hooks.json"
    )
    assert goose_user_settings_path() == root / ".config/goose/settings.json"
    install()
    assert (
        get_mcp_config_path("goose")
        == root / ".agents/plugins" / GOOSE_PLUGIN_NAME / ".mcp.json"
    )
    monkeypatch.setenv("GOOSE_PATH_ROOT", "relative/root")
    assert goose_hook_path().is_relative_to(Path.home())
    assert goose_config_dir() == tmp_path / "xdg/goose"


def test_macos_uses_native_configuration_but_shared_plugin_paths(monkeypatch):
    monkeypatch.setattr("ai_guardian.goose_support.sys.platform", "darwin")
    assert goose_config_dir() == Path.home() / "Library/Application Support/Block/goose"
    assert goose_user_settings_path() == Path.home() / ".config/goose/settings.json"


def test_project_hook_path_is_constructed_without_filesystem_discovery(tmp_path):
    project = tmp_path / "linked" / ".." / "repo"
    expected = project / ".agents/plugins" / GOOSE_PLUGIN_NAME / "hooks/hooks.json"
    with (
        patch.object(
            Path, "resolve", side_effect=AssertionError("premature path lookup")
        ),
        patch.object(
            Path, "expanduser", side_effect=AssertionError("premature path lookup")
        ),
    ):
        assert goose_hook_path("project", str(project)) == expected


@pytest.mark.parametrize("project_dir", ["nested", "~/nested"])
def test_project_hook_path_keeps_relative_and_home_expansion(project_dir):
    parent = Path.home() if project_dir.startswith("~") else Path.cwd()
    expected = (
        parent / "nested/.agents/plugins" / GOOSE_PLUGIN_NAME / "hooks/hooks.json"
    )
    assert goose_hook_path("project", project_dir) == expected


def test_disabled_project_copy_does_not_shadow_enabled_user_plugin(isolated_goose):
    _, project = isolated_goose
    setup = install()
    install(setup, scope="project", project_dir=str(project))
    path = goose_hook_path("project", str(project))
    write_json(
        goose_config_dir() / "config.yaml",
        {"plugins": {str(path.parent.parent): {"enabled": False}}},
    )
    effective = setup.verify_hooks_for_ide("goose", "auto", str(project))
    assert effective["scope"] == "user"
    assert effective["healthy"] is True
    assert not setup.verify_hooks_for_ide("goose", "project", str(project))["healthy"]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX managed plugin symlink contract",
)
def test_setup_refuses_linked_managed_plugin(isolated_goose, tmp_path):
    target = tmp_path / "user-plugin"
    target.mkdir()
    root = goose_hook_path().parent.parent
    root.parent.mkdir(parents=True)
    root.symlink_to(target, target_is_directory=True)
    assert not IDESetup().setup_ide_hooks("goose", force=True)[0]
    assert list(target.iterdir()) == []


def test_project_setup_is_explicit_and_health_uses_effective_plugin(isolated_goose):
    home, project = isolated_goose
    setup = install()
    install(setup, scope="project", project_dir=str(project))
    project_path = goose_hook_path("project", str(project))
    assert project_path.is_file()
    assert goose_hook_path().is_file()
    assert (
        setup.verify_hooks_for_ide("goose", "auto", str(project))["scope"] == "project"
    )
    project_path.write_text("malformed", encoding="utf-8")
    status = setup.verify_hooks_for_ide("goose", "auto", str(project))
    assert status["healthy"] is False
    assert status["config_path"] == str(project_path)
    assert setup.verify_hooks_for_ide("goose", "user")["healthy"]


def test_dry_run_and_invalid_project_scope_are_non_mutating(isolated_goose):
    home, project = isolated_goose
    install(dry_run=True)
    assert not (home / ".agents").exists()
    success, _ = IDESetup().setup_ide_hooks("goose", scope="project")
    assert success is False
    assert not (project / ".agents").exists()


def test_reconcile_preserves_unrelated_rules_and_takes_unique_backups():
    setup = install()
    path = goose_hook_path()
    config = json.loads(path.read_text())
    other = {
        "matcher": "shell",
        "hooks": [{"type": "command", "command": "audit-tool"}],
    }
    config["hooks"]["PreToolUse"].append(other)
    config["hooks"]["Stop"] = [other, expected_hooks()["PreToolUse"][0]]
    del config["hooks"]["SessionStart"]
    config["custom"] = {"unchanged": True}
    write_json(path, config)
    before = path.read_bytes()
    assert setup.verify_hooks_for_ide("goose")["healthy"] is False
    ok, message = setup.reconcile_hooks_for_ide("goose")
    assert ok, message
    repaired = json.loads(path.read_text())
    assert repaired["hooks"]["PreToolUse"][-1] == other
    assert repaired["hooks"]["Stop"] == [other]
    assert repaired["custom"] == config["custom"]
    assert path.with_name("hooks.json.backup").read_bytes() == before
    assert setup.verify_hooks_for_ide("goose")["healthy"]


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"hooks": []},
        {"hooks": {"PreToolUse": {}}},
        {"hooks": {"PreToolUse": [{"hooks": None}]}},
        "malformed",
    ],
)
def test_malformed_plugin_is_not_overwritten(value):
    setup = install()
    path = goose_hook_path()
    if value == "malformed":
        path.write_text(value, encoding="utf-8")
    else:
        write_json(path, value)
    before = path.read_bytes()
    success, _ = setup.setup_ide_hooks("goose", force=True)
    assert success is False
    assert path.read_bytes() == before
    assert setup.verify_hooks_for_ide("goose")["healthy"] is False


@pytest.mark.parametrize("actions", [None, 7])
def test_unowned_malformed_actions_without_manifest_are_rejected_safely(actions):
    from ai_guardian.setup.goose import setup_goose_hooks

    path = goose_hook_path()
    write_json(path, {"hooks": {"PreToolUse": [{"hooks": actions}]}})
    before = path.read_bytes()
    success, _ = setup_goose_hooks(IDESetup(), path)
    assert success is False
    assert path.read_bytes() == before
    assert not (path.parent.parent / "plugin.json").exists()


def test_user_owned_manifest_and_backup_failure_stop_setup():
    setup = install()
    path = goose_hook_path()
    manifest = path.parent.parent / "plugin.json"
    write_json(manifest, {"name": "user-plugin", "custom": True})
    before = manifest.read_bytes()
    assert not setup.setup_ide_hooks("goose", force=True)[0]
    assert manifest.read_bytes() == before
    manifest.unlink()
    with patch.object(
        setup, "_backup_before_write", return_value=(False, None, "backup failed")
    ):
        assert not setup.setup_ide_hooks("goose", force=True)[0]


def test_disabled_and_malformed_enablement_settings_are_not_reported_healthy():
    setup = install()
    settings = goose_user_settings_path()
    write_json(settings, {"disabledPlugins": [GOOSE_PLUGIN_NAME]})
    assert not setup.verify_hooks_for_ide("goose")["healthy"]
    write_json(
        Path.cwd() / ".config/goose/settings.local.json",
        {"enabledPlugins": [GOOSE_PLUGIN_NAME]},
    )
    assert setup.verify_hooks_for_ide("goose")["healthy"]
    settings.write_text("malformed", encoding="utf-8")
    assert not setup.verify_hooks_for_ide("goose")["healthy"]


def test_mcp_merge_health_removal_and_effective_project_shadowing(isolated_goose):
    _, project = isolated_goose
    setup = install()
    path = get_mcp_config_path("goose")
    other = {"command": "other-server", "args": []}
    write_json(path, {"mcpServers": {"other": other}})
    _install_mcp_config(setup, "goose")
    config = json.loads(path.read_text())
    assert config["mcpServers"]["other"] == other
    assert config["mcpServers"]["ai-guardian"]["args"] == ["mcp-server"]
    assert verify_mcp_config("goose")["mcp_installed"] is True
    assert setup.verify_ide_setup("goose")["healthy"]
    assert setup.verify_ide_setup("goose")["scope"] == "user"
    install(setup, scope="project", project_dir=str(project))
    assert (
        setup.verify_ide_setup("goose", "auto", str(project))["mcp_installed"] is False
    )
    _remove_mcp_config(setup, "goose")
    assert json.loads(path.read_text())["mcpServers"] == {"other": other}
    assert goose_hook_path().is_file()


def test_auto_detection_uses_cli_or_actual_config_not_an_empty_shared_directory(
    monkeypatch,
):
    monkeypatch.setattr("ai_guardian.setup.hooks.shutil.which", lambda *_: None)
    assert "goose" not in IDESetup().list_installed_ides()
    (Path.home() / ".agents/plugins").mkdir(parents=True)
    assert "goose" not in IDESetup().list_installed_ides()
    goose_config_dir().mkdir(parents=True, exist_ok=True)
    (goose_config_dir() / "config.yaml").write_text("{}", encoding="utf-8")
    assert "goose" in IDESetup().list_installed_ides()


def test_native_windows_setup_is_explicitly_unqualified(monkeypatch):
    monkeypatch.setattr("ai_guardian.setup.goose.platform.system", lambda: "Windows")
    success, message = IDESetup().setup_ide_hooks("goose")
    assert success is False
    assert "native Windows is not qualified" in message
    assert not goose_hook_path().exists()


def test_optional_rules_are_user_scoped_and_preserve_existing_hints(isolated_goose):
    from ai_guardian.setup.rules import _handle_rules_setup

    _, project = isolated_goose
    path = goose_config_dir() / ".goosehints"
    _handle_rules_setup("goose", dry_run=True)
    assert not path.exists()
    _handle_rules_setup("goose")
    assert "AI Guardian" in path.read_text()
    assert not (project / ".goosehints").exists()
    path.write_text("user hints", encoding="utf-8")
    _handle_rules_setup("goose")
    assert path.read_text() == "user hints"


def test_project_reconciliation_changes_only_explicit_plugin(isolated_goose):
    _, project = isolated_goose
    setup = install()
    install(setup, scope="project", project_dir=str(project))
    user_before = goose_hook_path().read_bytes()
    path = goose_hook_path("project", str(project))
    config = json.loads(path.read_text())
    del config["hooks"]["SessionStart"]
    write_json(path, config)
    assert setup.reconcile_hooks_for_ide(
        "goose", scope="project", project_dir=str(project)
    )[0]
    assert goose_hook_path().read_bytes() == user_before
    assert setup.verify_hooks_for_ide("goose", "project", str(project))["healthy"]


@pytest.mark.parametrize(
    "action",
    [
        None,
        {"type": 4},
        {"command": ["audit"]},
        {"command": "audit", "timeout": "60"},
        {"command": "audit", "timeout": True},
        {"command": "audit", "on_failure": None},
    ],
)
def test_malformed_sibling_actions_cannot_make_an_unloadable_plugin_healthy(action):
    setup = install()
    path = goose_hook_path()
    config = json.loads(path.read_text())
    config["hooks"]["PreToolUse"].append({"hooks": [action]})
    write_json(path, config)
    before = path.read_bytes()
    assert not setup.verify_hooks_for_ide("goose")["healthy"]
    assert not setup.reconcile_hooks_for_ide("goose")[0]
    assert path.read_bytes() == before


def test_owned_invalid_action_can_be_repaired_without_removing_ignored_user_actions():
    setup = install()
    path = goose_hook_path()
    config = json.loads(path.read_text())
    config["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] = "invalid"
    ignored = {"type": "webhook", "command": {"url": "https://example.invalid"}}
    config["hooks"]["PreToolUse"].append({"hooks": [ignored]})
    write_json(path, config)
    assert not setup.verify_hooks_for_ide("goose")["healthy"]
    assert setup.reconcile_hooks_for_ide("goose")[0]
    assert json.loads(path.read_text())["hooks"]["PreToolUse"][-1] == {
        "hooks": [ignored]
    }
    assert setup.verify_hooks_for_ide("goose")["healthy"]


def test_custom_manifest_mcp_layout_is_preserved_and_not_reported_active():
    setup = install()
    _install_mcp_config(setup, "goose")
    path = get_mcp_config_path("goose")
    manifest_path = path.parent / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["mcpServers"] = {"exclusive": True, "paths": ["./custom-mcp.json"]}
    write_json(manifest_path, manifest)
    before = path.read_bytes(), manifest_path.read_bytes()
    assert setup.verify_hooks_for_ide("goose")["healthy"]
    assert verify_mcp_config("goose")["mcp_status"] == "invalid"
    _install_mcp_config(setup, "goose")
    _remove_mcp_config(setup, "goose")
    assert (path.read_bytes(), manifest_path.read_bytes()) == before


@pytest.mark.parametrize(
    "server",
    [
        {"url": "https://example.test"},
        {"command": "audit", "args": "invalid"},
        {"command": "audit", "env": {"KEY": 1}},
        {"command": "audit", "cwd": []},
    ],
)
def test_malformed_mcp_sibling_invalidates_the_entire_goose_document(server):
    setup = install()
    _install_mcp_config(setup, "goose")
    path = get_mcp_config_path("goose")
    config = json.loads(path.read_text())
    config["mcpServers"]["other"] = server
    write_json(path, config)
    status = verify_mcp_config("goose")
    assert status["mcp_status"] == "invalid"
    assert status["mcp_installed"] is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symbolic link contract")
def test_mcp_link_does_not_write_or_remove_unrelated_configuration(tmp_path):
    setup = install()
    path = get_mcp_config_path("goose")
    target = tmp_path / "other-config.json"
    write_json(target, {"mcpServers": {"ai-guardian": {"command": "custom"}}})
    before = target.read_bytes()
    path.symlink_to(target)
    _install_mcp_config(setup, "goose")
    _remove_mcp_config(setup, "goose")
    assert verify_mcp_config("goose")["mcp_status"] == "invalid"
    assert target.read_bytes() == before


def test_doctor_uses_effective_project_hooks_and_mcp_without_launching_goose(
    isolated_goose,
):
    from ai_guardian.doctor import Doctor

    _, project = isolated_goose
    setup = install(scope="project", project_dir=str(project))
    _install_mcp_config(setup, "goose", scope="project", project_dir=str(project))
    assert "goose" in setup.list_installed_ides()
    with patch.object(IDESetup, "list_detected_ides", return_value=["goose"]):
        result = Doctor().check_hooks()
    status = next(item for item in result.integrations if item["ide"] == "goose")
    assert status["status"] == "pass"
    assert "5/5 hooks; MCP: healthy" in status["message"]
    assert "Only PreToolUse enforces" in status["message"]
    assert status["verification"]["scope"] == "project"
