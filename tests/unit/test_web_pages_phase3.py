"""Tests for Web Console Phase 3 pages (Prompt Injection & Threat Detection)."""

import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


class TestPageImports:

    def test_pi_detection_page_exists(self):
        from ai_guardian.web.pages.pi_detection import create_pi_detection_page

        assert callable(create_pi_detection_page)

    def test_pi_patterns_page_exists(self):
        from ai_guardian.web.pages.pi_patterns import create_pi_patterns_page

        assert callable(create_pi_patterns_page)

    def test_pi_jailbreak_page_exists(self):
        from ai_guardian.web.pages.pi_jailbreak import create_pi_jailbreak_page

        assert callable(create_pi_jailbreak_page)

    def test_pi_unicode_page_exists(self):
        from ai_guardian.web.pages.pi_unicode import create_pi_unicode_page

        assert callable(create_pi_unicode_page)

    def test_ssrf_page_exists(self):
        from ai_guardian.web.pages.ssrf import create_ssrf_page

        assert callable(create_ssrf_page)

    def test_config_scanner_page_exists(self):
        from ai_guardian.web.pages.config_scanner import (
            create_config_scanner_page,
        )

        assert callable(create_config_scanner_page)

    def test_scan_pii_page_exists(self):
        from ai_guardian.web.pages.scan_pii import create_scan_pii_page

        assert callable(create_scan_pii_page)

    def test_annotations_page_exists(self):
        from ai_guardian.web.pages.annotations import create_annotations_page

        assert callable(create_annotations_page)


class TestRouteSidebarConsistency:

    PHASE3_ROUTES = [
        "/pi-detection",
        "/pi-patterns",
        "/pi-jailbreak",
        "/pi-unicode",
        "/ssrf",
        "/config-scanner",
        "/scan-pii",
        "/annotations",
    ]

    def test_all_routes_registered_in_app(self):
        import inspect
        from ai_guardian.web.app import WebConsole

        source = inspect.getsource(WebConsole._register_pages)
        for route in self.PHASE3_ROUTES:
            assert route in source, f"Route {route} not found in app.py"

    def test_all_routes_in_sidebar(self):
        from ai_guardian.web.components.header import NAV_GROUPS

        all_suffixes = [suffix for _, items in NAV_GROUPS for _, suffix in items]
        for route in self.PHASE3_ROUTES:
            assert (
                route in all_suffixes
            ), f"Route {route} not found in sidebar navigation"


class TestPIDetectionHelpers:

    def test_parse_duration_minutes(self):
        from ai_guardian.web.pages.pi_detection import _parse_duration

        result = _parse_duration("30m")
        assert result == timedelta(minutes=30)

    def test_parse_duration_hours(self):
        from ai_guardian.web.pages.pi_detection import _parse_duration

        result = _parse_duration("2h")
        assert result == timedelta(hours=2)

    def test_parse_duration_days(self):
        from ai_guardian.web.pages.pi_detection import _parse_duration

        result = _parse_duration("1d")
        assert result == timedelta(days=1)

    def test_parse_duration_combined(self):
        from ai_guardian.web.pages.pi_detection import _parse_duration

        result = _parse_duration("1d2h30m")
        assert result == timedelta(days=1, hours=2, minutes=30)

    def test_parse_duration_plain_number(self):
        from ai_guardian.web.pages.pi_detection import _parse_duration

        result = _parse_duration("45")
        assert result == timedelta(minutes=45)

    def test_parse_duration_invalid(self):
        from ai_guardian.web.pages.pi_detection import _parse_duration

        assert _parse_duration("abc") is None

    def test_parse_duration_zero(self):
        from ai_guardian.web.pages.pi_detection import _parse_duration

        assert _parse_duration("0d0h0m") is None

    def test_parse_enabled_bool(self):
        from ai_guardian.web.pages.pi_detection import _parse_enabled

        is_temp, until_dt, reason, is_enabled = _parse_enabled(True)
        assert not is_temp
        assert until_dt is None
        assert is_enabled is True

    def test_parse_enabled_false(self):
        from ai_guardian.web.pages.pi_detection import _parse_enabled

        _, _, _, is_enabled = _parse_enabled(False)
        assert is_enabled is False

    def test_parse_enabled_dict_simple(self):
        from ai_guardian.web.pages.pi_detection import _parse_enabled

        is_temp, _, _, is_enabled = _parse_enabled({"value": True})
        assert not is_temp
        assert is_enabled is True

    def test_parse_enabled_dict_temp_disabled(self):
        from ai_guardian.web.pages.pi_detection import _parse_enabled

        future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        raw = {"value": False, "disabled_until": future, "reason": "testing"}
        is_temp, until_dt, reason, is_enabled = _parse_enabled(raw)
        assert is_temp is True
        assert until_dt is not None
        assert reason == "testing"
        assert is_enabled is False

    def test_parse_enabled_dict_expired(self):
        from ai_guardian.web.pages.pi_detection import _parse_enabled

        raw = {
            "value": False,
            "disabled_until": "2020-01-01T00:00:00Z",
        }
        is_temp, _, _, is_enabled = _parse_enabled(raw)
        assert is_temp is False
        assert is_enabled is False


class TestPIPatternsHelpers:

    def test_format_expiration_none(self):
        from ai_guardian.web.pages.pi_patterns import _format_expiration

        assert _format_expiration(None) is None

    def test_format_expiration_empty(self):
        from ai_guardian.web.pages.pi_patterns import _format_expiration

        assert _format_expiration("") is None

    def test_format_expiration_expired(self):
        from ai_guardian.web.pages.pi_patterns import _format_expiration

        result = _format_expiration("2020-01-01T00:00:00Z")
        assert result is not None
        assert result[0] == "EXPIRED"
        assert result[1] == "red"

    def test_format_expiration_future(self):
        from ai_guardian.web.pages.pi_patterns import _format_expiration

        future = (datetime.now(timezone.utc) + timedelta(days=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        result = _format_expiration(future)
        assert result is not None
        assert "expires" in result[0]
        assert result[1] == "amber"

    def test_get_pattern_text_string(self):
        from ai_guardian.web.pages.pi_patterns import _get_pattern_text

        assert _get_pattern_text("foo.*bar") == "foo.*bar"

    def test_get_pattern_text_dict(self):
        from ai_guardian.web.pages.pi_patterns import _get_pattern_text

        entry = {"pattern": "test\\d+", "valid_until": "2030-01-01T00:00:00Z"}
        assert _get_pattern_text(entry) == "test\\d+"


class TestPIJailbreakData:

    def test_builtin_categories_exist(self):
        from ai_guardian.web.pages.pi_jailbreak import BUILTIN_JAILBREAK_CATEGORIES

        assert isinstance(BUILTIN_JAILBREAK_CATEGORIES, dict)
        assert len(BUILTIN_JAILBREAK_CATEGORIES) >= 3


class TestPIUnicodeData:

    def test_unicode_checks_defined(self):
        from ai_guardian.web.pages.pi_unicode import UNICODE_CHECKS

        assert isinstance(UNICODE_CHECKS, list)
        assert len(UNICODE_CHECKS) == 6

    def test_unicode_checks_structure(self):
        from ai_guardian.web.pages.pi_unicode import UNICODE_CHECKS

        for entry in UNICODE_CHECKS:
            assert len(entry) == 4
            key, default, label, desc = entry
            assert isinstance(key, str)
            assert isinstance(default, bool)
            assert isinstance(label, str)
            assert isinstance(desc, str)


class TestSSRFData:

    def test_core_protections_defined(self):
        from ai_guardian.web.pages.ssrf import CORE_PROTECTIONS

        assert isinstance(CORE_PROTECTIONS, dict)
        assert "Private IP Ranges" in CORE_PROTECTIONS
        assert "0.0.0.0/8" in CORE_PROTECTIONS["Private IP Ranges"]
        assert "Cloud Metadata Endpoints" in CORE_PROTECTIONS
        assert "Dangerous URL Schemes" in CORE_PROTECTIONS


class TestConfigScannerData:

    def test_default_scanned_files_defined(self):
        from ai_guardian.web.pages.config_scanner import DEFAULT_SCANNED_FILES

        assert isinstance(DEFAULT_SCANNED_FILES, dict)
        assert "AI Agent Config" in DEFAULT_SCANNED_FILES
        assert "Skill Files" in DEFAULT_SCANNED_FILES


class TestScanPIIData:

    def test_phase1_pii_types(self):
        from ai_guardian.web.pages.scan_pii import PHASE1_PII_TYPES

        assert isinstance(PHASE1_PII_TYPES, list)
        assert len(PHASE1_PII_TYPES) >= 7
        keys = [k for k, _ in PHASE1_PII_TYPES]
        assert "ssn" in keys
        assert "credit_card" in keys
        assert "email" in keys

    def test_phase2_pii_types(self):
        from ai_guardian.web.pages.scan_pii import PHASE2_PII_TYPES

        assert isinstance(PHASE2_PII_TYPES, list)
        assert len(PHASE2_PII_TYPES) >= 6
        keys = [k for k, _ in PHASE2_PII_TYPES]
        assert "medical_id" in keys
        assert "address" in keys

    def test_all_pii_types_combined(self):
        from ai_guardian.web.pages.scan_pii import ALL_PII_TYPES

        assert len(ALL_PII_TYPES) >= 13


class TestConfigLoadSavePhase3:

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
        config_file.write_text('{"prompt_injection": {"enabled": true}}')

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
            assert result["prompt_injection"]["enabled"] is True

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
