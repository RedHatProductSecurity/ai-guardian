#!/usr/bin/env python3
"""
Tests for TUI Config Editor Panel
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


from ai_guardian.tui.config_editor import (
    ConfigEditorContent,
    ConfirmSaveModal,
    validate_json_string,
    validate_against_schema,
)
from ai_guardian.tui.schema_defaults import ConfigSaveMixin
from ai_guardian.config.utils import CONFIG_READ_ONLY_MESSAGE


class TestValidateJsonString:
    """Tests for JSON validation helper."""

    def test_valid_json(self):
        data, error = validate_json_string('{"key": "value"}')
        assert data == {"key": "value"}
        assert error is None

    def test_valid_json_complex(self):
        text = json.dumps(
            {
                "permissions": {"enabled": True},
                "secret_scanning": {"enabled": True, "scanner": "gitleaks"},
            },
            indent=2,
        )
        data, error = validate_json_string(text)
        assert data is not None
        assert error is None
        assert data["permissions"]["enabled"] is True

    def test_invalid_json_syntax(self):
        data, error = validate_json_string('{"key": }')
        assert data is None
        assert error is not None
        assert "Line" in error

    def test_invalid_json_trailing_comma(self):
        data, error = validate_json_string('{"key": "value",}')
        assert data is None
        assert error is not None

    def test_empty_string(self):
        data, error = validate_json_string("")
        assert data is None
        assert error == "Empty content"

    def test_whitespace_only(self):
        data, error = validate_json_string("   \n\t  ")
        assert data is None
        assert error == "Empty content"

    def test_valid_json_array(self):
        data, error = validate_json_string("[1, 2, 3]")
        assert data == [1, 2, 3]
        assert error is None

    def test_valid_json_empty_object(self):
        data, error = validate_json_string("{}")
        assert data == {}
        assert error is None


class TestValidateAgainstSchema:
    """Tests for schema validation."""

    def test_valid_config(self):
        config = {"permissions": {"enabled": True}}
        warnings = validate_against_schema(config)
        assert isinstance(warnings, list)

    def test_empty_config(self):
        warnings = validate_against_schema({})
        assert isinstance(warnings, list)

    def test_returns_warnings_for_invalid_types(self):
        config = {"permissions": "not_a_valid_value"}
        warnings = validate_against_schema(config)
        assert len(warnings) > 0

    @patch("ai_guardian.tui.config_editor._get_schema_validator", return_value=None)
    def test_no_validator_returns_empty(self, _mock):
        warnings = validate_against_schema({"any": "thing"})
        assert warnings == []


class TestConfirmSaveModal:
    """Tests for the save confirmation modal."""

    def test_modal_initialization(self):
        modal = ConfirmSaveModal("/path/to/config.json")
        assert modal._config_path == "/path/to/config.json"
        assert modal._warnings == []

    def test_modal_with_warnings(self):
        warnings = ["root: extra property 'foo'", "permissions: wrong type"]
        modal = ConfirmSaveModal("/path/to/config.json", warnings)
        assert len(modal._warnings) == 2

    def test_modal_with_no_warnings(self):
        modal = ConfirmSaveModal("/path/to/config.json", [])
        assert modal._warnings == []


class TestConfigEditorContent:
    """Tests for the config editor content widget."""

    def test_instantiation(self):
        widget = ConfigEditorContent()
        assert widget is not None

    def test_save_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            original = {"permissions": {"enabled": True}}
            config_path.write_text(json.dumps(original, indent=2), encoding="utf-8")

            widget = ConfigEditorContent()
            widget._config_path = config_path

            new_content = json.dumps({"permissions": {"enabled": False}}, indent=2)
            success, error = widget._write_config(new_content)

            assert success is True
            assert error is None

            backup_path = config_path.with_suffix(".json.bak")
            assert backup_path.exists()
            backup_data = json.loads(backup_path.read_text(encoding="utf-8"))
            assert backup_data == original

            saved_data = json.loads(config_path.read_text(encoding="utf-8"))
            assert saved_data["permissions"]["enabled"] is False

    def test_save_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "subdir" / "ai-guardian.json"

            widget = ConfigEditorContent()
            widget._config_path = config_path

            content = json.dumps({"test": True}, indent=2)
            success, error = widget._write_config(content)

            assert success is True
            assert config_path.exists()
            assert json.loads(config_path.read_text(encoding="utf-8")) == {"test": True}

    def test_save_no_backup_when_no_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"

            widget = ConfigEditorContent()
            widget._config_path = config_path

            content = json.dumps({"new": True}, indent=2)
            success, error = widget._write_config(content)

            assert success is True
            assert config_path.exists()
            backup_path = config_path.with_suffix(".json.bak")
            assert not backup_path.exists()

    @patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_READ_ONLY": "true"})
    def test_host_managed_config_cannot_be_saved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            original = '{"source": "host"}\n'
            config_path.write_text(original, encoding="utf-8")

            widget = ConfigEditorContent()
            widget._config_path = config_path

            success, error = widget._write_config('{"changed": true}\n')

            assert success is False
            assert error == CONFIG_READ_ONLY_MESSAGE
            assert config_path.read_text(encoding="utf-8") == original


class TestConfigSaveMixin:
    @patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_READ_ONLY": "true"})
    def test_host_managed_config_cannot_be_written(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text('{"source": "host"}\n', encoding="utf-8")

        assert (
            ConfigSaveMixin()._write_full_config(
                {"changed": True}, config_path=config_path
            )
            is False
        )
        assert json.loads(config_path.read_text(encoding="utf-8")) == {"source": "host"}


class TestConfigEditorThemeIntegration:
    """Tests for config editor theme loading."""

    def test_editor_uses_load_editor_theme(self):
        """Verify config editor imports and calls load_editor_theme."""
        from ai_guardian.tui.config_editor import load_editor_theme

        assert callable(load_editor_theme)
