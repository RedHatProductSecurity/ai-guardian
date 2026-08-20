"""Tests for tray plugin management UI and CRUD helpers (#1736)."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, mock, skipIf


class TestListPluginFiles(TestCase):
    """Tests for list_plugin_files()."""

    def test_empty_dir(self):
        from ai_guardian.tray.plugins import list_plugin_files

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                mock.patch(
                    "ai_guardian.daemon.get_tray_plugins_dir",
                    return_value=Path(tmpdir) / "nonexistent",
                ),
                mock.patch(
                    "ai_guardian.tray.plugins.find_project_plugins_dir",
                    return_value=None,
                ),
                mock.patch(
                    "ai_guardian.tray.plugins._get_bundled_plugins_dir",
                    return_value=None,
                ),
            ):
                result = list_plugin_files()
                assert result == []

    def test_lists_user_plugins(self):
        from ai_guardian.tray.plugins import list_plugin_files

        with tempfile.TemporaryDirectory() as tmpdir:
            user_dir = Path(tmpdir) / "user"
            user_dir.mkdir()
            plugin = {
                "name": "My Plugin",
                "items": [{"label": "Test", "command": "echo"}],
            }
            (user_dir / "my-plugin.json").write_text(json.dumps(plugin))

            with (
                mock.patch(
                    "ai_guardian.daemon.get_tray_plugins_dir",
                    return_value=user_dir,
                ),
                mock.patch(
                    "ai_guardian.tray.plugins.find_project_plugins_dir",
                    return_value=None,
                ),
                mock.patch(
                    "ai_guardian.tray.plugins._get_bundled_plugins_dir",
                    return_value=None,
                ),
            ):
                result = list_plugin_files()
                assert len(result) == 1
                assert result[0]["filename"] == "my-plugin.json"
                assert result[0]["source"] == "user"
                assert result[0]["enabled"] is True
                assert result[0]["plugin_name"] == "My Plugin"

    def test_disabled_plugin_detected(self):
        from ai_guardian.tray.plugins import list_plugin_files

        with tempfile.TemporaryDirectory() as tmpdir:
            user_dir = Path(tmpdir) / "user"
            user_dir.mkdir()
            plugin = {"name": "Disabled", "items": [{"label": "X", "command": "echo"}]}
            (user_dir / "test.json.disabled").write_text(json.dumps(plugin))

            with (
                mock.patch(
                    "ai_guardian.daemon.get_tray_plugins_dir",
                    return_value=user_dir,
                ),
                mock.patch(
                    "ai_guardian.tray.plugins.find_project_plugins_dir",
                    return_value=None,
                ),
                mock.patch(
                    "ai_guardian.tray.plugins._get_bundled_plugins_dir",
                    return_value=None,
                ),
            ):
                result = list_plugin_files()
                assert len(result) == 1
                assert result[0]["enabled"] is False


class TestSaveUserPlugin(TestCase):
    """Tests for save_user_plugin()."""

    def test_save_valid_plugin(self):
        from ai_guardian.tray.plugins import save_user_plugin

        with tempfile.TemporaryDirectory() as tmpdir:
            user_dir = Path(tmpdir) / "plugins"
            with mock.patch(
                "ai_guardian.daemon.get_tray_plugins_dir",
                return_value=user_dir,
            ):
                content = {
                    "name": "Test",
                    "items": [
                        {"label": "Cmd", "command": "echo hello", "type": "terminal"}
                    ],
                }
                ok, msg = save_user_plugin("test-plugin.json", content)
                assert ok is True
                assert (user_dir / "test-plugin.json").exists()
                saved = json.loads((user_dir / "test-plugin.json").read_text())
                assert saved["name"] == "Test"

    def test_reject_invalid_filename(self):
        from ai_guardian.tray.plugins import save_user_plugin

        ok, msg = save_user_plugin("../escape.json", {"name": "bad", "items": []})
        assert ok is False
        assert "Invalid filename" in msg

    def test_reject_missing_name(self):
        from ai_guardian.tray.plugins import save_user_plugin

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "ai_guardian.daemon.get_tray_plugins_dir",
                return_value=Path(tmpdir),
            ):
                ok, msg = save_user_plugin("test.json", {"items": []})
                assert ok is False


class TestDeleteUserPlugin(TestCase):
    """Tests for delete_user_plugin()."""

    def test_delete_existing(self):
        from ai_guardian.tray.plugins import delete_user_plugin

        with tempfile.TemporaryDirectory() as tmpdir:
            user_dir = Path(tmpdir)
            (user_dir / "my.json").write_text("{}")
            with mock.patch(
                "ai_guardian.daemon.get_tray_plugins_dir",
                return_value=user_dir,
            ):
                ok, msg = delete_user_plugin("my.json")
                assert ok is True
                assert not (user_dir / "my.json").exists()

    def test_delete_nonexistent(self):
        from ai_guardian.tray.plugins import delete_user_plugin

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "ai_guardian.daemon.get_tray_plugins_dir",
                return_value=Path(tmpdir),
            ):
                ok, msg = delete_user_plugin("nope.json")
                assert ok is False


class TestToggleUserPlugin(TestCase):
    """Tests for toggle_user_plugin()."""

    def test_disable_plugin(self):
        from ai_guardian.tray.plugins import toggle_user_plugin

        with tempfile.TemporaryDirectory() as tmpdir:
            user_dir = Path(tmpdir)
            (user_dir / "my.json").write_text("{}")
            with mock.patch(
                "ai_guardian.daemon.get_tray_plugins_dir",
                return_value=user_dir,
            ):
                ok, msg = toggle_user_plugin("my.json", enabled=False)
                assert ok is True
                assert (user_dir / "my.json.disabled").exists()
                assert not (user_dir / "my.json").exists()

    def test_enable_plugin(self):
        from ai_guardian.tray.plugins import toggle_user_plugin

        with tempfile.TemporaryDirectory() as tmpdir:
            user_dir = Path(tmpdir)
            (user_dir / "my.json.disabled").write_text("{}")
            with mock.patch(
                "ai_guardian.daemon.get_tray_plugins_dir",
                return_value=user_dir,
            ):
                ok, msg = toggle_user_plugin("my.json", enabled=True)
                assert ok is True
                assert (user_dir / "my.json").exists()
                assert not (user_dir / "my.json.disabled").exists()

    def test_already_enabled(self):
        from ai_guardian.tray.plugins import toggle_user_plugin

        with tempfile.TemporaryDirectory() as tmpdir:
            user_dir = Path(tmpdir)
            (user_dir / "my.json").write_text("{}")
            with mock.patch(
                "ai_guardian.daemon.get_tray_plugins_dir",
                return_value=user_dir,
            ):
                ok, msg = toggle_user_plugin("my.json", enabled=True)
                assert ok is True
                assert "Already enabled" in msg


class TestGetBundledTemplates(TestCase):
    """Tests for get_bundled_templates()."""

    def test_returns_templates(self):
        from ai_guardian.tray.plugins import get_bundled_templates

        templates = get_bundled_templates()
        assert isinstance(templates, list)
        assert len(templates) >= 1
        for t in templates:
            assert "filename" in t
            assert "name" in t
            assert "content" in t


class TestNavRegistration(TestCase):
    """Tests that Tray Plugins appears in nav groups."""

    def test_tui_nav_has_tray_plugins(self):
        from ai_guardian.tui.app import NAV_GROUPS

        config_group = next(
            (items for name, items in NAV_GROUPS if name == "Configuration"),
            None,
        )
        assert config_group is not None
        labels = [label for label, _ in config_group]
        assert "Tray Plugins" in labels

    @skipIf(sys.version_info < (3, 10), "Web console requires Python 3.10+")
    def test_web_nav_has_tray_plugins(self):
        from ai_guardian.web.components.header import NAV_GROUPS

        config_group = next(
            (items for name, items in NAV_GROUPS if name == "Configuration"),
            None,
        )
        assert config_group is not None
        labels = [label for label, _ in config_group]
        assert "Tray Plugins" in labels


class TestRestApiTrayPlugins(TestCase):
    """Tests for REST API tray plugin handlers."""

    def test_handle_tray_plugin_save_missing_fields(self):
        """POST /api/tray-plugins requires filename and content."""
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = mock.MagicMock(spec=_RestHandler)
        handler._send_error = mock.MagicMock()
        _RestHandler._handle_tray_plugin_save(handler, {"filename": "x.json"})
        handler._send_error.assert_called_once()
        assert handler._send_error.call_args[0][0] == 400

    def test_handle_tray_plugin_delete_missing_filename(self):
        """DELETE /api/tray-plugins requires filename."""
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = mock.MagicMock(spec=_RestHandler)
        handler._send_error = mock.MagicMock()
        _RestHandler._handle_tray_plugin_delete(handler, {})
        handler._send_error.assert_called_once()
        assert handler._send_error.call_args[0][0] == 400

    def test_handle_tray_plugin_toggle_missing_enabled(self):
        """POST /api/tray-plugins/toggle requires enabled bool."""
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = mock.MagicMock(spec=_RestHandler)
        handler._send_error = mock.MagicMock()
        _RestHandler._handle_tray_plugin_toggle(
            handler, {"filename": "x.json", "enabled": "yes"}
        )
        handler._send_error.assert_called_once()
        assert handler._send_error.call_args[0][0] == 400
