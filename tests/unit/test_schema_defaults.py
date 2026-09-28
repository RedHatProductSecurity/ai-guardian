#!/usr/bin/env python3
"""Tests for TUI schema defaults utility."""

import unittest

from ai_guardian.tui.schema_defaults import (
    SchemaDefaults,
    SchemaDefaultsMixin,
    _MISSING,
    default_indicator,
    default_placeholder,
    select_options_with_default,
)


class TestMissingSentinel(unittest.TestCase):
    """Tests for the _MISSING sentinel object."""

    def test_repr(self):
        assert repr(_MISSING) == "<MISSING>"

    def test_bool_is_false(self):
        assert not _MISSING

    def test_identity(self):
        assert _MISSING is _MISSING


class TestSchemaDefaults(unittest.TestCase):
    """Tests for the SchemaDefaults singleton."""

    @classmethod
    def setUpClass(cls):
        SchemaDefaults.reset()

    def test_singleton_returns_same_instance(self):
        a = SchemaDefaults.get()
        b = SchemaDefaults.get()
        assert a is b

    def test_schema_loaded(self):
        sd = SchemaDefaults.get()
        assert sd._schema is not None
        assert "properties" in sd._schema

    def test_get_default_boolean_true(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("ssrf_protection.enabled") is True

    def test_get_default_boolean_false(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("ssrf_protection.allow_localhost") is False

    def test_get_default_string(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("ssrf_protection.action") == "block"

    def test_get_default_string_enum(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("prompt_injection.action") == "block"

    def test_get_default_number_float(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("prompt_injection.max_score_threshold") == 0.75

    def test_get_default_number_integer(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("secret_scanning.consensus_threshold") == 2

    def test_get_default_array(self):
        sd = SchemaDefaults.get()
        result = sd.get_default("scan_pii.pii_types")
        assert isinstance(result, list)
        assert "ssn" in result
        assert "credit_card" in result
        assert len(result) == 9

    def test_get_default_array_empty(self):
        sd = SchemaDefaults.get()
        result = sd.get_default("prompt_injection.ignore_files")
        assert result == []

    def test_get_default_nested_path(self):
        sd = SchemaDefaults.get()
        result = sd.get_default(
            "secret_scanning.pattern_server.cache.refresh_interval_hours"
        )
        assert result == 12

    def test_get_default_nested_deep(self):
        sd = SchemaDefaults.get()
        result = sd.get_default(
            "secret_scanning.pattern_server.cache.expire_after_hours"
        )
        assert result == 168

    def test_get_default_missing_path(self):
        sd = SchemaDefaults.get()
        result = sd.get_default("nonexistent.field.path")
        assert result is _MISSING

    def test_get_default_missing_leaf(self):
        sd = SchemaDefaults.get()
        result = sd.get_default("ssrf_protection.nonexistent")
        assert result is _MISSING

    def test_get_default_no_default_key(self):
        sd = SchemaDefaults.get()
        result = sd.get_default("secret_scanning.pattern_server.url")
        assert result is _MISSING

    def test_get_description(self):
        sd = SchemaDefaults.get()
        desc = sd.get_description("ssrf_protection.action")
        assert desc is not None
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_get_description_missing_path(self):
        sd = SchemaDefaults.get()
        desc = sd.get_description("nonexistent.path")
        assert desc is None

    def test_is_default_matches(self):
        sd = SchemaDefaults.get()
        assert sd.is_default("ssrf_protection.action", "block") is True

    def test_is_default_differs(self):
        sd = SchemaDefaults.get()
        assert sd.is_default("ssrf_protection.action", "warn") is False

    def test_is_default_missing_path_returns_true(self):
        sd = SchemaDefaults.get()
        assert sd.is_default("nonexistent.path", "anything") is True

    def test_is_default_boolean(self):
        sd = SchemaDefaults.get()
        assert sd.is_default("ssrf_protection.allow_localhost", False) is True
        assert sd.is_default("ssrf_protection.allow_localhost", True) is False

    def test_prompt_injection_detector_default(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("prompt_injection.detector") == "heuristic"

    def test_prompt_injection_sensitivity_default(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("prompt_injection.sensitivity") == "medium"

    def test_secret_redaction_defaults(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("secret_redaction.enabled") is True
        assert sd.get_default("secret_redaction.action") == "warn"
        assert sd.get_default("secret_redaction.preserve_format") is True
        assert sd.get_default("secret_redaction.log_redactions") is True

    def test_scan_pii_defaults(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("scan_pii.enabled") is True
        assert sd.get_default("scan_pii.action") == "block"

    def test_remote_configs_defaults(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("remote_configs.refresh_interval_hours") == 12
        assert sd.get_default("remote_configs.expire_after_hours") == 168

    def test_host_cli_self_protection_default(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("self_protection.block_host_agent_cli") is True

    def test_secret_scanning_engines_default(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("secret_scanning.engines") == ["gitleaks"]

    def test_secret_scanning_execution_strategy_default(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("secret_scanning.execution_strategy") == "first-match"

    def test_daemon_client_timeout_default(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("daemon.client_timeout_seconds") == 2.0

    def test_daemon_idle_timeout_default(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("daemon.idle_timeout_minutes") == 0

    def test_definitions_console_default(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("console.editor_theme") == "monokai"

    def test_definitions_support_default(self):
        sd = SchemaDefaults.get()
        assert sd.get_default("support.bundle_ttl_minutes") == 30


class TestSelectOptionsWithDefault(unittest.TestCase):
    """Tests for select_options_with_default helper."""

    def test_marks_default_option(self):
        options = [
            ("Block", "block"),
            ("Warn", "warn"),
            ("Log Only", "log-only"),
        ]
        result = select_options_with_default(options, "ssrf_protection.action")
        labels = {v: l for l, v in result}
        assert "(default)" in labels["block"]
        assert "(default)" not in labels["warn"]
        assert "(default)" not in labels["log-only"]

    def test_no_double_marking(self):
        options = [
            ("Block (default)", "block"),
            ("Warn", "warn"),
        ]
        result = select_options_with_default(options, "ssrf_protection.action")
        labels = {v: l for l, v in result}
        assert labels["block"] == "Block (default)"
        assert labels["block"].count("(default)") == 1

    def test_missing_schema_path(self):
        options = [("A", "a"), ("B", "b")]
        result = select_options_with_default(options, "nonexistent.path")
        assert result == options

    def test_no_matching_option(self):
        options = [("Warn", "warn"), ("Log Only", "log-only")]
        result = select_options_with_default(options, "ssrf_protection.action")
        assert all("(default)" not in l for l, _ in result)


class TestDefaultIndicator(unittest.TestCase):
    """Tests for default_indicator helper."""

    def test_boolean_true(self):
        text = default_indicator("ssrf_protection.enabled")
        assert "default: on" in text
        assert "[dim]" in text

    def test_boolean_false(self):
        text = default_indicator("ssrf_protection.allow_localhost")
        assert "default: off" in text

    def test_string_value(self):
        text = default_indicator("ssrf_protection.action")
        assert "default: block" in text

    def test_number_value(self):
        text = default_indicator("prompt_injection.max_score_threshold")
        assert "default: 0.75" in text

    def test_empty_array(self):
        text = default_indicator("prompt_injection.ignore_files")
        assert "default: none" in text

    def test_nonempty_array(self):
        text = default_indicator("scan_pii.pii_types")
        assert "default:" in text
        assert "ssn" in text

    def test_missing_path(self):
        text = default_indicator("nonexistent.path")
        assert text == ""


class TestDefaultPlaceholder(unittest.TestCase):
    """Tests for default_placeholder helper."""

    def test_number(self):
        assert default_placeholder("prompt_injection.max_score_threshold") == "0.75"

    def test_string(self):
        result = default_placeholder("secret_scanning.pattern_server.patterns_endpoint")
        assert result == "/patterns/gitleaks/8.18.1"

    def test_missing_path(self):
        assert default_placeholder("nonexistent.path") == ""


class TestSchemaDefaultsMixin(unittest.TestCase):
    """Tests for SchemaDefaultsMixin methods."""

    def test_get_section_default(self):
        class FakePanel(SchemaDefaultsMixin):
            SCHEMA_SECTION = "ssrf_protection"
            SCHEMA_FIELDS = []

        panel = FakePanel()
        assert panel._get_section_default("action") == "block"
        assert panel._get_section_default("allow_localhost") is False

    def test_get_section_default_missing(self):
        class FakePanel(SchemaDefaultsMixin):
            SCHEMA_SECTION = "ssrf_protection"
            SCHEMA_FIELDS = []

        panel = FakePanel()
        result = panel._get_section_default("nonexistent")
        assert result is _MISSING

    def test_get_section_default_nested_section(self):
        class FakePanel(SchemaDefaultsMixin):
            SCHEMA_SECTION = "prompt_injection"
            SCHEMA_FIELDS = []

        panel = FakePanel()
        assert panel._get_section_default("detector") == "heuristic"
        assert panel._get_section_default("sensitivity") == "medium"


if __name__ == "__main__":
    unittest.main()
