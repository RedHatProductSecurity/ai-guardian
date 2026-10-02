"""Tests for default bundled tray plugins (Issue #831)."""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_guardian.tray.plugins import load_plugins, load_merged_plugins

_TEMPLATE_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "ai_guardian"
    / "templates"
    / "tray-plugins"
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "ai_guardian"
    / "schemas"
    / "tray-plugin.schema.json"
)


def _load_schema():
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _template_files():
    return sorted(_TEMPLATE_DIR.glob("*.json"))


def _active_daemon_file():
    """Return the default daemon plugin for supported runtimes."""
    return _TEMPLATE_DIR / "default-daemon-web.json"


class TestDefaultPluginSchema:
    """Verify bundled plugin JSONs pass the tray-plugin schema."""

    @pytest.fixture(autouse=True)
    def _load(self):
        jsonschema = pytest.importorskip("jsonschema")
        self.schema = _load_schema()
        self.validate = jsonschema.validate

    @pytest.mark.parametrize("path", _template_files(), ids=lambda p: p.name)
    def test_schema_validation(self, path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.validate(data, self.schema)

    def test_template_files_exist(self):
        templates = _template_files()
        names = {p.name for p in templates}
        assert "default-global.json" in names
        assert "default-daemon-web.json" in names


class TestDefaultPluginContent:
    """Verify structure and content of bundled plugins."""

    @pytest.fixture(autouse=True)
    def _load_data(self):
        self.global_data = json.loads(
            (_TEMPLATE_DIR / "default-global.json").read_text(encoding="utf-8")
        )
        self.daemon_data = json.loads(_active_daemon_file().read_text(encoding="utf-8"))

    def test_global_scope(self):
        assert self.global_data["scope"] == "global"

    def test_daemon_scope(self):
        assert self.daemon_data["scope"] == "daemon"

    def test_global_has_name(self):
        assert self.global_data["name"]

    def test_daemon_has_name(self):
        assert self.daemon_data["name"]

    def test_global_has_items(self):
        assert len(self.global_data["items"]) >= 3

    def test_daemon_has_items(self):
        assert len(self.daemon_data["items"]) >= 1

    def test_global_items_include_scan_directory(self):
        labels = [item["label"] for item in self.global_data["items"]]
        assert "Scan Directory..." in labels

    def test_global_items_include_check_for_updates(self):
        labels = [item["label"] for item in self.global_data["items"]]
        assert "Check for Updates" in labels

    def test_global_items_include_documentation(self):
        labels = [item["label"] for item in self.global_data["items"]]
        assert "Open Documentation" in labels

    def test_documentation_uses_platform_map(self):
        doc = next(
            i for i in self.global_data["items"] if i["label"] == "Open Documentation"
        )
        assert isinstance(doc["command"], dict)
        assert "darwin" in doc["command"]
        assert "linux" in doc["command"]

    def test_daemon_items_include_reload_config(self):
        labels = [item["label"] for item in self.daemon_data["items"]]
        assert "Reload Config" in labels

    def test_daemon_items_include_install_scanner(self):
        labels = [item["label"] for item in self.daemon_data["items"]]
        assert "Install Scanner..." in labels

    def test_daemon_items_include_view_doctor(self):
        labels = [item["label"] for item in self.daemon_data["items"]]
        assert "View Doctor" in labels

    def test_scan_directory_has_params(self):
        scan = next(
            i for i in self.global_data["items"] if i["label"] == "Scan Directory..."
        )
        assert "params" in scan
        assert len(scan["params"]) >= 1
        assert scan["params"][0]["name"] == "directory"

    def test_install_scanner_has_params(self):
        install = next(
            i for i in self.daemon_data["items"] if i["label"] == "Install Scanner..."
        )
        assert "params" in install
        assert len(install["params"]) >= 1
        param = install["params"][0]
        assert param["name"] == "scanner"
        assert "options" in param

    def test_web_variant_uses_background_for_doctor(self):
        data = json.loads(
            (_TEMPLATE_DIR / "default-daemon-web.json").read_text(encoding="utf-8")
        )
        doctor = next(i for i in data["items"] if i["label"] == "View Doctor")
        assert doctor["type"] == "background"
        assert isinstance(doctor["command"], dict)
        assert "health-check" in doctor["command"]["darwin"]


class TestDefaultPluginLoad:
    """Verify bundled plugins load correctly via load_plugins()."""

    def test_load_global_plugin(self, tmp_path):
        shutil.copy(
            _TEMPLATE_DIR / "default-global.json", tmp_path / "default-global.json"
        )
        plugins = load_plugins(tmp_path)
        assert len(plugins) == 1
        assert plugins[0].scope == "global"

    def test_load_daemon_plugin(self, tmp_path):
        shutil.copy(_active_daemon_file(), tmp_path / _active_daemon_file().name)
        plugins = load_plugins(tmp_path)
        assert len(plugins) == 1
        assert plugins[0].scope == "daemon"


class TestBundledPluginVariantSelection:
    """Verify the browser-console plugin is bundled and loaded."""

    def test_web_variant_by_default(self):
        from ai_guardian.tray.plugins import _load_bundled_plugins

        plugins = _load_bundled_plugins()
        names = {p.name for p in plugins}
        assert "Maintenance" in names
        maint = next(p for p in plugins if p.name == "Maintenance")
        doctor = next(i for i in maint.items if i.label == "View Doctor")
        assert isinstance(doctor.command, dict)
        assert "health-check" in doctor.command["darwin"]

    def test_only_one_maintenance_loaded(self):
        from ai_guardian.tray.plugins import _load_bundled_plugins

        plugins = _load_bundled_plugins()
        maintenance_count = sum(1 for p in plugins if p.name == "Maintenance")
        assert maintenance_count == 1


class TestBundledPluginMerge:
    """Verify bundled plugins are loaded via load_merged_plugins()."""

    def test_bundled_plugins_loaded_with_empty_user_dir(self, tmp_path):
        user_dir = tmp_path / "user-plugins"
        user_dir.mkdir()
        with patch("ai_guardian.daemon.get_tray_plugins_dir", return_value=user_dir):
            plugins = load_merged_plugins()
        names = {p.name for p in plugins}
        assert "Quick Actions" in names
        assert "Maintenance" in names

    def test_user_plugin_overrides_bundled(self, tmp_path):
        user_dir = tmp_path / "user-plugins"
        user_dir.mkdir()
        override = {
            "name": "Quick Actions",
            "scope": "global",
            "items": [{"label": "Custom Item", "command": "echo custom"}],
        }
        (user_dir / "custom.json").write_text(json.dumps(override))
        with patch("ai_guardian.daemon.get_tray_plugins_dir", return_value=user_dir):
            plugins = load_merged_plugins()
        qa = next(p for p in plugins if p.name == "Quick Actions")
        assert qa.items[0].label == "Custom Item"

    def test_bundled_plugins_appear_alongside_user_plugins(self, tmp_path):
        user_dir = tmp_path / "user-plugins"
        user_dir.mkdir()
        user_plugin = {
            "name": "My Custom Plugin",
            "items": [{"label": "Hello", "command": "echo hi"}],
        }
        (user_dir / "my-plugin.json").write_text(json.dumps(user_plugin))
        with patch("ai_guardian.daemon.get_tray_plugins_dir", return_value=user_dir):
            plugins = load_merged_plugins()
        names = {p.name for p in plugins}
        assert "My Custom Plugin" in names
        assert "Quick Actions" in names
        assert "Maintenance" in names

    def test_no_user_dir_still_loads_bundled(self, tmp_path):
        missing_dir = tmp_path / "nonexistent"
        with patch("ai_guardian.daemon.get_tray_plugins_dir", return_value=missing_dir):
            plugins = load_merged_plugins()
        assert len(plugins) >= 2
