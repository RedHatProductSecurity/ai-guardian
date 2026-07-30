"""Tests for Web Console Phase 4 pages (Configuration & Tools)."""

import json
from unittest import mock

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


# ---------------------------------------------------------------------------
# Import / existence tests
# ---------------------------------------------------------------------------


class TestPageImports:
    """Verify each Phase 4 page module imports and exposes its create function."""

    def test_remote_configs_page_exists(self):
        from ai_guardian.web.pages.remote_configs import (
            create_remote_configs_page,
        )

        assert callable(create_remote_configs_page)

    def test_config_file_page_exists(self):
        from ai_guardian.web.pages.config_file import create_config_file_page

        assert callable(create_config_file_page)

    def test_config_editor_page_exists(self):
        from ai_guardian.web.pages.config_editor import (
            create_config_editor_page,
        )

        assert callable(create_config_editor_page)

    def test_console_settings_page_exists(self):
        from ai_guardian.web.pages.console_settings import (
            create_console_settings_page,
        )

        assert callable(create_console_settings_page)

    def test_config_effective_page_exists(self):
        from ai_guardian.web.pages.config_effective import (
            create_config_effective_page,
        )

        assert callable(create_config_effective_page)

    def test_regex_tester_page_exists(self):
        from ai_guardian.web.pages.regex_tester import (
            create_regex_tester_page,
        )

        assert callable(create_regex_tester_page)

    def test_hook_simulator_page_exists(self):
        from ai_guardian.web.pages.hook_simulator import (
            create_hook_simulator_page,
        )

        assert callable(create_hook_simulator_page)

    def test_engine_tester_page_exists(self):
        from ai_guardian.web.pages.engine_tester import (
            create_engine_tester_page,
        )

        assert callable(create_engine_tester_page)

    def test_directory_scan_page_exists(self):
        from ai_guardian.web.pages.directory_scan import (
            create_directory_scan_page,
        )

        assert callable(create_directory_scan_page)

    def test_health_check_page_exists(self):
        from ai_guardian.web.pages.health_check import (
            create_health_check_page,
        )

        assert callable(create_health_check_page)


# ---------------------------------------------------------------------------
# Route / sidebar consistency
# ---------------------------------------------------------------------------


class TestRouteSidebarConsistency:
    """Verify every Phase 4 route path appears in app.py and sidebar."""

    PHASE4_ROUTES = [
        "/remote-configs",
        "/config-file",
        "/config-editor",
        "/console-settings",
        "/config-effective",
        "/regex-tester",
        "/hook-simulator",
        "/engine-tester",
        "/directory-scan",
        "/health-check",
    ]

    def test_all_routes_registered_in_app(self):
        import inspect
        from ai_guardian.web.app import WebConsole

        source = inspect.getsource(WebConsole._register_pages)
        for route in self.PHASE4_ROUTES:
            assert route in source, f"Route {route} not found in app.py"

    def test_all_routes_in_sidebar(self):
        from ai_guardian.web.components.header import NAV_GROUPS

        all_suffixes = [suffix for _, items in NAV_GROUPS for _, suffix in items]
        for route in self.PHASE4_ROUTES:
            assert (
                route in all_suffixes
            ), f"Route {route} not found in sidebar navigation"


# ---------------------------------------------------------------------------
# Remote Configs helpers
# ---------------------------------------------------------------------------


class TestRemoteConfigsHelpers:

    def test_normalize_url_entry_string(self):
        from ai_guardian.web.pages.remote_configs import _normalize_url_entry

        result = _normalize_url_entry("https://example.com/config.json")
        assert result["url"] == "https://example.com/config.json"
        assert result["enabled"] is True
        assert result["token_env"] is None

    def test_normalize_url_entry_dict(self):
        from ai_guardian.web.pages.remote_configs import _normalize_url_entry

        entry = {
            "url": "https://example.com/c.json",
            "enabled": False,
            "token_env": "MY_TOKEN",
        }
        result = _normalize_url_entry(entry)
        assert result["url"] == "https://example.com/c.json"
        assert result["enabled"] is False
        assert result["token_env"] == "MY_TOKEN"

    def test_normalize_url_entry_dict_defaults(self):
        from ai_guardian.web.pages.remote_configs import _normalize_url_entry

        result = _normalize_url_entry({"url": "https://x.com"})
        assert result["enabled"] is True
        assert result["token_env"] is None

    def test_normalize_url_entry_non_string(self):
        from ai_guardian.web.pages.remote_configs import _normalize_url_entry

        result = _normalize_url_entry(42)
        assert result["url"] == "42"
        assert result["enabled"] is True


# ---------------------------------------------------------------------------
# Config Editor helpers
# ---------------------------------------------------------------------------


class TestConfigEditorHelpers:

    def test_validate_json_valid(self):
        from ai_guardian.web.pages.config_editor import _validate_json

        parsed, err = _validate_json('{"key": "value"}')
        assert err is None
        assert parsed == {"key": "value"}

    def test_validate_json_invalid_syntax(self):
        from ai_guardian.web.pages.config_editor import _validate_json

        parsed, err = _validate_json("{bad json")
        assert parsed is None
        assert "Invalid JSON" in err

    def test_validate_json_not_object(self):
        from ai_guardian.web.pages.config_editor import _validate_json

        parsed, err = _validate_json("[1, 2, 3]")
        assert parsed is None
        assert "object" in err

    def test_validate_json_empty(self):
        from ai_guardian.web.pages.config_editor import _validate_json

        parsed, err = _validate_json("")
        assert parsed is None
        assert "Empty" in err

    def test_validate_json_nested(self):
        from ai_guardian.web.pages.config_editor import _validate_json

        text = '{"a": {"b": [1, 2, 3]}, "c": true}'
        parsed, err = _validate_json(text)
        assert err is None
        assert parsed["a"]["b"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Console Settings data
# ---------------------------------------------------------------------------


class TestConsoleSettingsData:

    def test_editor_themes_exist(self):
        from ai_guardian.web.pages.console_settings import EDITOR_THEMES

        assert isinstance(EDITOR_THEMES, dict)
        assert len(EDITOR_THEMES) == 4

    def test_editor_themes_keys(self):
        from ai_guardian.web.pages.console_settings import EDITOR_THEMES

        expected = {"monokai", "vscode_dark", "dracula", "github_light"}
        assert set(EDITOR_THEMES.keys()) == expected

    def test_theme_descriptions_exist(self):
        from ai_guardian.web.pages.console_settings import (
            EDITOR_THEMES,
            THEME_DESCRIPTIONS,
        )

        assert isinstance(THEME_DESCRIPTIONS, dict)
        for key in EDITOR_THEMES:
            assert key in THEME_DESCRIPTIONS, f"Missing description for theme {key}"
            assert len(THEME_DESCRIPTIONS[key]) > 10


# ---------------------------------------------------------------------------
# Regex Tester helpers
# ---------------------------------------------------------------------------


class TestRegexTesterHelpers:

    def test_test_regex_simple_match(self):
        from ai_guardian.web.pages.regex_tester import _test_regex

        matches, err = _test_regex(r"\d+", "abc 123 def 456")
        assert err is None
        assert len(matches) == 2
        assert matches[0]["match"] == "123"
        assert matches[1]["match"] == "456"

    def test_test_regex_no_match(self):
        from ai_guardian.web.pages.regex_tester import _test_regex

        matches, err = _test_regex(r"\d+", "no digits here")
        assert err is None
        assert len(matches) == 0

    def test_test_regex_case_insensitive(self):
        from ai_guardian.web.pages.regex_tester import _test_regex

        matches, _ = _test_regex(
            "hello",
            "Hello HELLO hello",
            case_insensitive=True,
        )
        assert len(matches) == 3

    def test_test_regex_case_sensitive(self):
        from ai_guardian.web.pages.regex_tester import _test_regex

        matches, _ = _test_regex(
            "hello",
            "Hello HELLO hello",
            case_insensitive=False,
        )
        assert len(matches) == 1

    def test_test_regex_multiline(self):
        from ai_guardian.web.pages.regex_tester import _test_regex

        text = "line1\nline2\nline3"
        matches, _ = _test_regex(
            r"^line\d",
            text,
            multiline=True,
        )
        assert len(matches) == 3

    def test_test_regex_max_matches(self):
        from ai_guardian.web.pages.regex_tester import _test_regex

        text = " ".join(str(i) for i in range(200))
        matches, _ = _test_regex(r"\d+", text, max_matches=5)
        assert len(matches) == 5

    def test_test_regex_invalid_pattern(self):
        from ai_guardian.web.pages.regex_tester import _test_regex

        matches, err = _test_regex(r"[invalid", "text")
        assert matches == []
        assert "error" in err.lower()

    def test_test_regex_empty_pattern(self):
        from ai_guardian.web.pages.regex_tester import _test_regex

        matches, err = _test_regex("", "text")
        assert matches == []
        assert err is not None

    def test_test_regex_line_numbers(self):
        from ai_guardian.web.pages.regex_tester import _test_regex

        text = "aaa\nbbb\nccc"
        matches, _ = _test_regex(r"[a-c]+", text)
        assert matches[0]["line"] == 1
        assert matches[1]["line"] == 2
        assert matches[2]["line"] == 3

    def test_target_sections_exist(self):
        from ai_guardian.web.pages.regex_tester import TARGET_SECTIONS

        assert isinstance(TARGET_SECTIONS, dict)
        assert "prompt_injection" in TARGET_SECTIONS
        assert "scan_pii" in TARGET_SECTIONS
        assert "secret_scanning" in TARGET_SECTIONS


# ---------------------------------------------------------------------------
# Engine Tester data
# ---------------------------------------------------------------------------


class TestHookSimulatorData:

    def test_ide_options_exist(self):
        from ai_guardian.web.pages.hook_simulator import IDE_OPTIONS

        assert isinstance(IDE_OPTIONS, list)
        assert len(IDE_OPTIONS) >= 6

    def test_ide_options_covers_main_adapters(self):
        from ai_guardian.web.pages.hook_simulator import IDE_OPTIONS

        ide_values = {v for _, v in IDE_OPTIONS}
        assert "claude" in ide_values
        assert "cursor" in ide_values
        assert "copilot" in ide_values
        assert "windsurf" in ide_values
        assert "cline" in ide_values
        assert "kiro" in ide_values


class TestEngineTesterData:

    def test_strategy_options_exist(self):
        from ai_guardian.web.pages.engine_tester import STRATEGY_OPTIONS

        assert isinstance(STRATEGY_OPTIONS, dict)
        assert len(STRATEGY_OPTIONS) == 4

    def test_strategy_options_keys(self):
        from ai_guardian.web.pages.engine_tester import STRATEGY_OPTIONS

        expected = {"from-config", "first-match", "any-match", "consensus"}
        assert set(STRATEGY_OPTIONS.keys()) == expected


# ---------------------------------------------------------------------------
# Directory Scan helpers
# ---------------------------------------------------------------------------


class TestDirectoryScanHelpers:

    def test_format_severity_high(self):
        from ai_guardian.web.pages.directory_scan import _format_severity

        assert _format_severity("high") == "orange-8"

    def test_format_severity_critical(self):
        from ai_guardian.web.pages.directory_scan import _format_severity

        assert _format_severity("critical") == "red-8"

    def test_format_severity_medium(self):
        from ai_guardian.web.pages.directory_scan import _format_severity

        assert _format_severity("medium") == "amber-8"

    def test_format_severity_low(self):
        from ai_guardian.web.pages.directory_scan import _format_severity

        assert _format_severity("low") == "blue-grey-7"

    def test_format_severity_info(self):
        from ai_guardian.web.pages.directory_scan import _format_severity

        assert _format_severity("info") == "blue-grey-7"

    def test_format_severity_unknown(self):
        from ai_guardian.web.pages.directory_scan import _format_severity

        assert _format_severity("unknown") == "blue-grey-7"

    def test_format_severity_case_insensitive(self):
        from ai_guardian.web.pages.directory_scan import _format_severity

        assert _format_severity("HIGH") == "orange-8"
        assert _format_severity("Medium") == "amber-8"

    def test_format_severity_none(self):
        from ai_guardian.web.pages.directory_scan import _format_severity

        assert _format_severity(None) == "blue-grey-7"


# ---------------------------------------------------------------------------
# Health Check data
# ---------------------------------------------------------------------------


class TestHealthCheckData:

    def test_get_status_icons_covers_all(self):
        from ai_guardian.doctor import CheckStatus
        from ai_guardian.web.pages.health_check import _STATUS_ICONS

        for status in CheckStatus:
            assert status.value in _STATUS_ICONS, f"Missing icon for {status.name}"

    def test_get_status_icons_structure(self):
        from ai_guardian.web.pages.health_check import _STATUS_ICONS

        for status, value in _STATUS_ICONS.items():
            assert isinstance(value, tuple), f"{status} is not a tuple"
            assert len(value) == 2, f"{status} tuple wrong length"
            icon, color = value
            assert isinstance(icon, str)
            assert isinstance(color, str)


# ---------------------------------------------------------------------------
# Config load/save
# ---------------------------------------------------------------------------


class TestConfigLoadSavePhase4:

    def test_load_config_missing_file(self, tmp_path):
        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import load_web_config

            assert load_web_config() == {}

    def test_load_config_valid_file(self, tmp_path):
        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"remote_configs": {"urls": []}}')

        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import load_web_config

            result = load_web_config()
            assert result["remote_configs"]["urls"] == []

    def test_save_config_creates_file(self, tmp_path):
        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import save_web_config

            save_web_config({"test": True})
            config_file = tmp_path / "ai-guardian.json"
            assert config_file.exists()
            data = json.loads(config_file.read_text())
            assert data["test"] is True

    def test_save_config_pretty_prints(self, tmp_path):
        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import save_web_config

            save_web_config({"a": 1, "b": 2})
            text = (tmp_path / "ai-guardian.json").read_text()
            assert "\n" in text
            assert text.endswith("\n")


# ---------------------------------------------------------------------------
# Config Editor save with backup
# ---------------------------------------------------------------------------


class TestConfigEditorSaveBackup:

    def test_save_creates_backup(self, tmp_path):
        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"old": true}')

        from ai_guardian.web.pages.config_editor import (
            _save_config_with_backup,
        )

        err = _save_config_with_backup('{"new": true}', str(config_file))
        assert err is None
        assert config_file.exists()
        backup = tmp_path / "ai-guardian.json.bak"
        assert backup.exists()
        assert json.loads(backup.read_text()) == {"old": True}
        assert json.loads(config_file.read_text()) == {"new": True}

    def test_save_invalid_json_returns_error(self, tmp_path):
        from ai_guardian.web.pages.config_editor import (
            _save_config_with_backup,
        )

        err = _save_config_with_backup("{bad", str(tmp_path / "test.json"))
        assert err is not None
        assert "Invalid JSON" in err

    def test_save_no_path_returns_error(self):
        from ai_guardian.web.pages.config_editor import (
            _save_config_with_backup,
        )

        err = _save_config_with_backup('{"a": 1}', None)
        assert err is not None


class TestConfigFilePhantomConfig:
    """Regression tests for #1749 — phantom project config."""

    def test_daemon_config_empty_dict_means_no_project(self):
        """get_config_scoped returning {} should set project_exists=False."""
        from ai_guardian.web.pages.config_file import _load_daemon_config_files

        fake_target = mock.MagicMock()
        fake_target.name = "test-daemon"
        fake_service = mock.MagicMock()
        fake_service.get_config_scoped.return_value = {}

        with (
            mock.patch(
                "ai_guardian.web.pages.config_file._get_current_target",
                return_value=fake_target,
            ),
            mock.patch(
                "ai_guardian.web.pages.config_file._daemon_service",
                fake_service,
            ),
            mock.patch(
                "ai_guardian.web.config_helpers._get_remote_project_dir",
                return_value="/some/project",
            ),
        ):
            result = _load_daemon_config_files(fake_target)
            assert result["project_exists"] is False
            assert result["project_content"] is None

    def test_daemon_config_nonempty_dict_means_project_exists(self):
        """get_config_scoped returning real config should set project_exists=True."""
        from ai_guardian.web.pages.config_file import _load_daemon_config_files

        fake_target = mock.MagicMock()
        fake_target.name = "test-daemon"
        fake_service = mock.MagicMock()
        fake_service.get_config_scoped.return_value = {
            "ssrf_protection": {"action": "warn"}
        }

        with (
            mock.patch(
                "ai_guardian.web.pages.config_file._get_current_target",
                return_value=fake_target,
            ),
            mock.patch(
                "ai_guardian.web.pages.config_file._daemon_service",
                fake_service,
            ),
            mock.patch(
                "ai_guardian.web.config_helpers._get_remote_project_dir",
                return_value="/some/project",
            ),
        ):
            result = _load_daemon_config_files(fake_target)
            assert result["project_exists"] is True
            assert result["project_content"] is not None
