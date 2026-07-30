"""Tests for ConfigSaveMixin — verify unrelated config sections survive saves.

Issue #1745: TUI pages used direct json.dump which risked dropping config
sections. All pages now use ConfigSaveMixin. This test verifies the mixin
preserves all sections during save operations.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai_guardian.tui.schema_defaults import ConfigSaveMixin


class FakeMixin(ConfigSaveMixin):
    """Minimal ConfigSaveMixin subclass for testing."""

    CONFIG_SECTION = "test_section"

    def __init__(self, config_path: Path):
        self._test_config_path = config_path
        self.app = SimpleNamespace(config_scope="global")

    def _get_config_path(self) -> Path:
        return self._test_config_path

    def load_config(self):
        pass


SEED_CONFIG = {
    "secret_scanning": {"enabled": True, "action": "block"},
    "permissions": {
        "enabled": True,
        "rules": [{"mode": "allow", "matcher": "Bash", "patterns": ["ls"]}],
    },
    "prompt_injection": {"enabled": True, "allowlist_patterns": ["test.*"]},
    "test_section": {"enabled": False, "some_list": ["a", "b"]},
}


@pytest.fixture()
def config_file(tmp_path):
    path = tmp_path / "ai-guardian.json"
    path.write_text(json.dumps(SEED_CONFIG, indent=2), encoding="utf-8")
    return path


@pytest.fixture()
def mixin(config_file):
    m = FakeMixin(config_file)
    m.app.notify = MagicMock()
    return m


class TestConfigSaveMixin:
    def test_save_config_field_preserves_all_sections(self, mixin, config_file):
        mixin._save_config_field("action", "warn")

        result = json.loads(config_file.read_text(encoding="utf-8"))
        assert result["test_section"]["action"] == "warn"
        assert result["secret_scanning"] == SEED_CONFIG["secret_scanning"]
        assert result["permissions"] == SEED_CONFIG["permissions"]
        assert result["prompt_injection"] == SEED_CONFIG["prompt_injection"]

    def test_save_config_updates_preserves_all_sections(self, mixin, config_file):
        mixin._save_config_updates({"enabled": True, "new_key": "value"})

        result = json.loads(config_file.read_text(encoding="utf-8"))
        assert result["test_section"]["enabled"] is True
        assert result["test_section"]["new_key"] == "value"
        assert result["test_section"]["some_list"] == ["a", "b"]
        assert result["secret_scanning"] == SEED_CONFIG["secret_scanning"]
        assert result["permissions"] == SEED_CONFIG["permissions"]

    def test_add_config_list_item_preserves_all_sections(self, mixin, config_file):
        mixin._add_config_list_item("some_list", "c")

        result = json.loads(config_file.read_text(encoding="utf-8"))
        assert result["test_section"]["some_list"] == ["a", "b", "c"]
        assert result["secret_scanning"] == SEED_CONFIG["secret_scanning"]
        assert result["permissions"] == SEED_CONFIG["permissions"]
        assert result["prompt_injection"] == SEED_CONFIG["prompt_injection"]

    def test_add_config_list_item_dedup(self, mixin, config_file):
        result = mixin._add_config_list_item("some_list", "a")
        assert result is False
        mixin.app.notify.assert_called()

    def test_write_full_config_preserves_all_sections(self, mixin, config_file):
        config = mixin._load_full_config()
        config["test_section"]["new_field"] = 42
        mixin._write_full_config(config)

        result = json.loads(config_file.read_text(encoding="utf-8"))
        assert result["test_section"]["new_field"] == 42
        assert result["secret_scanning"] == SEED_CONFIG["secret_scanning"]
        assert result["permissions"] == SEED_CONFIG["permissions"]
        assert result["prompt_injection"] == SEED_CONFIG["prompt_injection"]

    def test_save_to_cross_section_preserves_all(self, mixin, config_file):
        mixin._save_config_field("action", "ask", section="secret_scanning")

        result = json.loads(config_file.read_text(encoding="utf-8"))
        assert result["secret_scanning"]["action"] == "ask"
        assert result["secret_scanning"]["enabled"] is True
        assert result["test_section"] == SEED_CONFIG["test_section"]
        assert result["permissions"] == SEED_CONFIG["permissions"]

    def test_save_creates_new_section_preserves_existing(self, mixin, config_file):
        mixin._save_config_field("enabled", True, section="brand_new_section")

        result = json.loads(config_file.read_text(encoding="utf-8"))
        assert result["brand_new_section"]["enabled"] is True
        assert result["secret_scanning"] == SEED_CONFIG["secret_scanning"]
        assert result["permissions"] == SEED_CONFIG["permissions"]
        assert result["test_section"] == SEED_CONFIG["test_section"]

    def test_load_full_config_empty_file(self, tmp_path):
        path = tmp_path / "empty.json"
        m = FakeMixin(path)
        assert m._load_full_config() == {}

    def test_write_full_config_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "ai-guardian.json"
        m = FakeMixin(path)
        m._write_full_config({"test": True})
        assert path.exists()
        assert json.loads(path.read_text())["test"] is True
