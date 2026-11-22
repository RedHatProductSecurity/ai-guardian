"""Tests for ChatGPT desktop's advisory local-plugin integration."""

import json
import shutil
from pathlib import Path

import pytest

from ai_guardian.setup import (
    IDESetup,
    _MCP_IDE_CONFIGS,
    _handle_mcp_setup,
    setup_hooks,
)
from ai_guardian.setup import mcp


class BackupSetup:
    """Minimal setup double that records byte-for-byte backups."""

    _last_backup_error = None

    def backup_config(self, config_path: Path) -> Path:
        backup_path = config_path.with_name(f"{config_path.name}.backup")
        shutil.copyfile(config_path, backup_path)
        return backup_path


@pytest.fixture
def chatgpt_plugin_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        mcp,
        "_resolved_mcp_command",
        lambda: ["/opt/ai-guardian/bin/ai-guardian", "mcp-server"],
    )
    monkeypatch.setattr(mcp, "_register_mcp_identity", lambda _binary: True)
    return home


def _paths(home):
    plugin_dir = home / ".agents" / "plugins" / "ai-guardian-chatgpt"
    return {
        "plugin_dir": plugin_dir,
        "manifest": plugin_dir / "plugin.json",
        "mcp": plugin_dir / "mcp.json",
        "marketplace": home / ".agents" / "plugins" / "marketplace.json",
    }


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_from_text(value):
    return json.loads(value)


def test_chatgpt_setup_installs_official_local_plugin_and_reports_unverified_host(
    chatgpt_plugin_home,
):
    home = chatgpt_plugin_home
    paths = _paths(home)

    assert "chatgpt" in _MCP_IDE_CONFIGS
    assert _handle_mcp_setup(BackupSetup(), "chatgpt") is True

    manifest = _read_json(paths["manifest"])
    mcp_config = _read_json(paths["mcp"])
    marketplace = _read_json(paths["marketplace"])
    plugin_entry = marketplace["plugins"][0]

    assert manifest["$schema"].endswith("/plugin.schema.json")
    assert manifest["name"] == mcp.CHATGPT_PLUGIN_NAME
    assert "hooks" not in manifest["extensions"]["com.openai"]
    assert mcp_config["$schema"].endswith("/mcp.schema.json")
    assert mcp_config["mcpServers"]["ai-guardian"] == {
        "type": "stdio",
        "command": "/opt/ai-guardian/bin/ai-guardian",
        "args": ["mcp-server"],
    }
    assert plugin_entry["name"] == mcp.CHATGPT_PLUGIN_NAME
    assert plugin_entry["source"] == {
        "source": "local",
        "path": "./ai-guardian-chatgpt",
    }
    assert plugin_entry["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }

    verification = mcp.verify_mcp_config("chatgpt")
    assert verification["mcp_status"] == "healthy"
    assert verification["mcp_installed"] is True
    assert verification["mcp_registration"] == "local-plugin"
    assert verification["mcp_host_installation_status"] == "unverified"


def test_chatgpt_setup_preserves_unrelated_marketplace_and_plugin_mcp_entries(
    chatgpt_plugin_home,
):
    paths = _paths(chatgpt_plugin_home)
    paths["marketplace"].parent.mkdir(parents=True)
    prior_marketplace = {
        "name": "personal-marketplace",
        "interface": {"displayName": "My tools", "theme": "dark"},
        "plugins": [
            {
                "name": "other-plugin",
                "source": {"source": "local", "path": "./other-plugin"},
                "policy": {"installation": "AVAILABLE"},
                "category": "Productivity",
            }
        ],
        "custom": {"keep": True},
    }
    paths["marketplace"].write_text(
        json.dumps(prior_marketplace, indent=2) + "\n", encoding="utf-8"
    )
    paths["plugin_dir"].mkdir()
    prior_manifest = {
        "name": mcp.CHATGPT_PLUGIN_NAME,
        "userMetadata": {"keep": True},
        "extensions": {"com.openai": {"interface": {"customField": "keep"}}},
    }
    prior_mcp = {
        "mcpServers": {"other-server": {"type": "stdio", "command": "other"}},
        "custom": "keep",
    }
    paths["manifest"].write_text(json.dumps(prior_manifest), encoding="utf-8")
    paths["mcp"].write_text(json.dumps(prior_mcp), encoding="utf-8")

    assert mcp._install_mcp_config(BackupSetup(), "chatgpt") is True

    marketplace = _read_json(paths["marketplace"])
    assert marketplace["name"] == "personal-marketplace"
    assert marketplace["interface"] == {
        "displayName": "My tools",
        "theme": "dark",
    }
    assert marketplace["custom"] == {"keep": True}
    assert [entry["name"] for entry in marketplace["plugins"]] == [
        "other-plugin",
        mcp.CHATGPT_PLUGIN_NAME,
    ]
    manifest = _read_json(paths["manifest"])
    assert manifest["userMetadata"] == {"keep": True}
    assert manifest["extensions"]["com.openai"]["interface"]["customField"] == "keep"
    assert _read_json(paths["mcp"])["mcpServers"]["other-server"] == {
        "type": "stdio",
        "command": "other",
    }


def test_chatgpt_reinstall_is_idempotent_and_does_not_create_backups(
    chatgpt_plugin_home,
):
    setup = BackupSetup()
    assert mcp._install_mcp_config(setup, "chatgpt") is True
    paths = _paths(chatgpt_plugin_home)
    before = {key: path.read_bytes() for key, path in paths.items() if path.is_file()}

    assert mcp._install_mcp_config(setup, "chatgpt") is True

    assert {
        key: path.read_bytes() for key, path in paths.items() if path.is_file()
    } == before
    assert not list(paths["plugin_dir"].parent.glob("*.backup"))


def test_chatgpt_no_mcp_removes_only_owned_plugin_and_marketplace_entry(
    chatgpt_plugin_home,
):
    home = chatgpt_plugin_home
    paths = _paths(home)
    setup = BackupSetup()
    assert mcp._install_mcp_config(setup, "chatgpt") is True

    mcp_config = _read_json(paths["mcp"])
    mcp_config["mcpServers"]["other-server"] = {
        "type": "stdio",
        "command": "other",
    }
    paths["mcp"].write_text(json.dumps(mcp_config), encoding="utf-8")
    marketplace = _read_json(paths["marketplace"])
    marketplace["plugins"].append(
        {
            "name": "other-plugin",
            "source": {"source": "local", "path": "./other-plugin"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }
    )
    paths["marketplace"].write_text(json.dumps(marketplace), encoding="utf-8")

    assert _handle_mcp_setup(setup, "chatgpt", no_mcp=True) is True

    assert not paths["manifest"].exists()
    assert _read_json(paths["mcp"])["mcpServers"] == {
        "other-server": {"type": "stdio", "command": "other"}
    }
    remaining = _read_json(paths["marketplace"])
    assert [entry["name"] for entry in remaining["plugins"]] == ["other-plugin"]
    assert mcp.verify_mcp_config("chatgpt")["mcp_status"] == "missing"
    assert all(
        Path(f"{path}.backup").is_file()
        for path in (paths["manifest"], paths["mcp"], paths["marketplace"])
    )


def test_chatgpt_removal_preserves_mcp_file_when_an_unrelated_server_remains(
    chatgpt_plugin_home,
):
    paths = _paths(chatgpt_plugin_home)
    setup = BackupSetup()
    assert mcp._install_mcp_config(setup, "chatgpt") is True
    mcp_config = _read_json(paths["mcp"])
    mcp_config["mcpServers"]["other-server"] = {
        "type": "stdio",
        "command": "other",
    }
    paths["mcp"].write_text(json.dumps(mcp_config), encoding="utf-8")

    assert _handle_mcp_setup(setup, "chatgpt", no_mcp=True) is True

    assert _read_json(paths["mcp"]) == {
        "$schema": mcp._CHATGPT_MCP_SCHEMA,
        "mcpServers": {"other-server": {"type": "stdio", "command": "other"}},
    }


def test_chatgpt_dry_run_does_not_create_plugin_or_marketplace(chatgpt_plugin_home):
    paths = _paths(chatgpt_plugin_home)

    assert mcp._install_mcp_config(BackupSetup(), "chatgpt", dry_run=True) is True

    assert not paths["plugin_dir"].exists()
    assert not paths["marketplace"].exists()


@pytest.mark.parametrize(
    ("no_mcp", "expected_status"),
    [(False, "would_install"), (True, "would_remove")],
)
def test_chatgpt_json_dry_run_reports_advisory_plugin_action_without_writes(
    chatgpt_plugin_home, capsys, no_mcp, expected_status
):
    paths = _paths(chatgpt_plugin_home)

    assert (
        setup_hooks(ide_type="chatgpt", no_mcp=no_mcp, dry_run=True, json_output=True)
        is True
    )

    result = _read_json_from_text(capsys.readouterr().out)
    assert result["success"] is True
    assert result["mcp_status"] == expected_status
    assert result["mcp_registration"] == "local-plugin"
    assert result["mcp_host_installation_status"] == "unverified"
    assert not paths["plugin_dir"].exists()
    assert not paths["marketplace"].exists()


def test_chatgpt_json_setup_reports_local_health_and_unverified_host(
    chatgpt_plugin_home, capsys
):
    assert setup_hooks(ide_type="chatgpt", json_output=True) is True

    result = _read_json_from_text(capsys.readouterr().out)
    assert result["success"] is True
    assert result["mcp_status"] == "healthy"
    assert result["mcp_installed"] is True
    assert result["mcp_host_installation_status"] == "unverified"


def test_chatgpt_json_setup_propagates_plugin_write_failure(
    chatgpt_plugin_home, capsys
):
    paths = _paths(chatgpt_plugin_home)
    paths["marketplace"].parent.mkdir(parents=True)
    paths["marketplace"].write_text("{not json", encoding="utf-8")

    assert setup_hooks(ide_type="chatgpt", json_output=True) is False

    result = _read_json_from_text(capsys.readouterr().out)
    assert result["success"] is False
    assert result["mcp_status"] == "invalid"
    assert (
        "Unable to read valid JSON from ChatGPT personal marketplace" in result["error"]
    )
    assert not paths["manifest"].exists()
    assert not paths["mcp"].exists()


def test_chatgpt_setup_fails_closed_on_malformed_marketplace(chatgpt_plugin_home):
    paths = _paths(chatgpt_plugin_home)
    paths["marketplace"].parent.mkdir(parents=True)
    paths["marketplace"].write_text("{not json", encoding="utf-8")

    assert mcp._install_mcp_config(BackupSetup(), "chatgpt") is False

    assert not paths["manifest"].exists()
    assert not paths["mcp"].exists()
    assert paths["marketplace"].read_text(encoding="utf-8") == "{not json"


def test_chatgpt_setup_fails_before_writes_when_existing_marketplace_backup_fails(
    chatgpt_plugin_home,
):
    paths = _paths(chatgpt_plugin_home)
    paths["marketplace"].parent.mkdir(parents=True)
    original = json.dumps({"name": "personal", "plugins": []})
    paths["marketplace"].write_text(original, encoding="utf-8")

    class FailedBackupSetup:
        _last_backup_error = "backup denied"

        @staticmethod
        def backup_config(_path):
            return None

    assert mcp._install_mcp_config(FailedBackupSetup(), "chatgpt") is False

    assert paths["marketplace"].read_text(encoding="utf-8") == original
    assert not paths["manifest"].exists()
    assert not paths["mcp"].exists()


def test_chatgpt_setup_requires_mcp_only_setup_message_and_removal_message():
    setup = IDESetup()

    installed, install_message = setup.setup_ide_hooks("chatgpt")
    removed, remove_message = setup.setup_ide_hooks("chatgpt", enable_mcp=False)

    assert installed is True
    assert removed is True
    assert "does not support hooks" in install_message
    assert "MCP advisor configuration will be installed by default" in install_message
    assert "Use --no-mcp to remove it" in install_message
    assert (
        "Existing AI Guardian MCP advisor configuration will be removed"
        in remove_message
    )
    assert "automatic" not in install_message.lower()
