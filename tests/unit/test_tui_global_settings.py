#!/usr/bin/env python3
"""
Tests for TUI Global Settings

Test the global settings panel's feature mapping and save logic.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


from ai_guardian.tui.global_settings import (
    GlobalSettingsContent,
    FEATURES,
    FEATURE_ACTIONS,
)


class TestFeatureMap:
    """Test FEATURES defines correct mappings."""

    def test_has_twelve_features(self):
        assert len(FEATURES) == 15

    def test_expected_sections(self):
        sections = [s for s, _, _ in FEATURES]
        assert "permissions" in sections
        assert "secret_scanning" in sections
        assert "secret_redaction" in sections
        assert "prompt_injection" in sections
        assert "scan_pii" in sections
        assert "ssrf_protection" in sections
        assert "config_file_scanning" in sections
        assert "context_poisoning" in sections
        assert "supply_chain" in sections
        assert "violation_logging" in sections

    def test_all_have_labels(self):
        for section, config_key, label in FEATURES:
            assert isinstance(label, str) and len(label) > 0

    def test_sections_unique(self):
        sections = [s for s, _, _ in FEATURES]
        assert len(sections) == len(set(sections))

    def test_config_keys_unique(self):
        keys = [k for _, k, _ in FEATURES]
        assert len(keys) == len(set(keys))


class TestSaveLogic:
    """Test _save writes correct config structure."""

    def _do_save(self, section, value, existing_config=None):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            if existing_config:
                with open(config_path, "w") as f:
                    json.dump(existing_config, f)

            content = GlobalSettingsContent()
            content._loading = False

            with (
                patch.object(
                    content,
                    "_get_config_path",
                    return_value=config_path,
                ),
                patch.object(
                    type(content),
                    "app",
                    new_callable=lambda: property(lambda self: MagicMock()),
                ),
            ):
                content._save(section, value, "Test Feature")

            with open(config_path, "r") as f:
                return json.load(f)

    def test_save_enabled(self):
        result = self._do_save("permissions", True)
        assert result["permissions"]["enabled"] is True

    def test_save_disabled(self):
        result = self._do_save("prompt_injection", False)
        assert result["prompt_injection"]["enabled"] is False

    def test_save_temp_disabled(self):
        value = {"value": False, "disabled_until": "2026-12-31T23:59:59Z"}
        result = self._do_save("ssrf_protection", value)
        assert result["ssrf_protection"]["enabled"] == value

    def test_save_preserves_existing(self):
        existing = {"secret_scanning": {"engine": "gitleaks", "enabled": True}}
        result = self._do_save("secret_scanning", False, existing)
        assert result["secret_scanning"]["enabled"] is False
        assert result["secret_scanning"]["engine"] == "gitleaks"

    def test_save_developer_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            content = GlobalSettingsContent()
            content._loading = False

            with (
                patch.object(content, "_get_config_path", return_value=config_path),
                patch.object(
                    type(content),
                    "app",
                    new_callable=lambda: property(lambda self: MagicMock()),
                ),
            ):
                content._save_developer_session(True)

            result = json.loads(config_path.read_text())
            assert result["developer_session"]["enabled"] is True

    def test_project_scope_cannot_save_developer_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            content = GlobalSettingsContent()
            content._loading = False
            app = MagicMock()
            app.config_scope = "project"

            with (
                patch.object(content, "_get_config_path", return_value=config_path),
                patch.object(
                    type(content),
                    "app",
                    new_callable=lambda: property(lambda self: app),
                ),
            ):
                content._save_developer_session(True)

            assert not config_path.exists()
            app.notify.assert_called_once()

    def test_save_all_sections(self):
        for section, _, _ in FEATURES:
            result = self._do_save(section, True)
            assert result[section]["enabled"] is True


class TestFeatureActions:
    """Test FEATURE_ACTIONS defines correct mappings."""

    def test_nine_features_have_actions(self):
        assert len(FEATURE_ACTIONS) == 11

    def test_expected_sections(self):
        assert "secret_redaction" in FEATURE_ACTIONS
        assert "prompt_injection" in FEATURE_ACTIONS
        assert "scan_pii" in FEATURE_ACTIONS
        assert "ssrf_protection" in FEATURE_ACTIONS
        assert "config_file_scanning" in FEATURE_ACTIONS
        assert "context_poisoning" in FEATURE_ACTIONS

    def test_all_have_required_keys(self):
        for section, info in FEATURE_ACTIONS.items():
            assert "schema_path" in info, f"{section} missing schema_path"
            assert "options" in info, f"{section} missing options"
            assert "default" in info, f"{section} missing default"

    def test_default_in_options(self):
        for section, info in FEATURE_ACTIONS.items():
            option_values = [v for _, v in info["options"]]
            assert (
                info["default"] in option_values
            ), f"{section} default '{info['default']}' not in options"

    def test_schema_paths_match_sections(self):
        for section, info in FEATURE_ACTIONS.items():
            assert info["schema_path"].startswith(f"{section}.")


class TestActionSaveLogic:
    """Test _save_action writes correct config structure."""

    def _do_save_action(self, section, value, existing_config=None):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            if existing_config:
                with open(config_path, "w") as f:
                    json.dump(existing_config, f)

            content = GlobalSettingsContent()
            content._loading = False

            with (
                patch.object(
                    content,
                    "_get_config_path",
                    return_value=config_path,
                ),
                patch.object(
                    type(content),
                    "app",
                    new_callable=lambda: property(lambda self: MagicMock()),
                ),
            ):
                content._save_action(section, value, "Test Feature")

            with open(config_path, "r") as f:
                return json.load(f)

    def test_save_action_block(self):
        result = self._do_save_action("prompt_injection", "block")
        assert result["prompt_injection"]["action"] == "block"

    def test_save_action_warn(self):
        result = self._do_save_action("ssrf_protection", "warn")
        assert result["ssrf_protection"]["action"] == "warn"

    def test_save_action_log_only(self):
        result = self._do_save_action("config_file_scanning", "log-only")
        assert result["config_file_scanning"]["action"] == "log-only"

    def test_save_action_preserves_existing(self):
        existing = {"prompt_injection": {"enabled": True, "detector": "heuristic"}}
        result = self._do_save_action("prompt_injection", "warn", existing)
        assert result["prompt_injection"]["action"] == "warn"
        assert result["prompt_injection"]["enabled"] is True
        assert result["prompt_injection"]["detector"] == "heuristic"

    def test_save_action_all_supported_features(self):
        for section in FEATURE_ACTIONS:
            result = self._do_save_action(section, "warn")
            assert result[section]["action"] == "warn"
