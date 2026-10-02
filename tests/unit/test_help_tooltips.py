"""Tests for per-field help tooltips (Issue #1472).

Verifies:
- CONFIG_FIELD_HELP is populated from _comment_* fields in setup.py
- Key field entries are present
- field_help_icon() renders without errors when keys exist or are missing
"""

import pytest

from ai_guardian.help_content import CONFIG_FIELD_HELP, _build_field_help


class TestConfigFieldHelp:
    def test_non_empty(self):
        assert len(CONFIG_FIELD_HELP) > 0

    def test_top_level_section_keys_present(self):
        # Only keys that have _comment_* entries in setup.py are expected.
        # context_poisoning has no _comment_ in setup.py so it is absent.
        expected = [
            "secret_scanning",
            "prompt_injection",
            "ssrf_protection",
            "scan_pii",
            "secret_redaction",
            "supply_chain",
            "code_scanning",
            "canary_detection",
            "exfil_detection",
            "on_scan_error",
            "violation_logging",
            "permissions",
            "security_instructions",
        ]
        for key in expected:
            assert key in CONFIG_FIELD_HELP, f"Missing key: {key!r}"

    def test_nested_section_field_keys_present(self):
        expected_nested = [
            "secret_scanning.entropy",
            "secret_scanning.stopwords",
            "secret_scanning.validate_secrets",
            "secret_scanning.engines",
            "ssrf_protection.allowed_domains",
        ]
        for key in expected_nested:
            assert key in CONFIG_FIELD_HELP, f"Missing nested key: {key!r}"

    def test_values_are_non_empty_strings(self):
        for key, val in CONFIG_FIELD_HELP.items():
            assert isinstance(val, str), f"Key {key!r} has non-string value"
            assert len(val) > 0, f"Key {key!r} has empty value"

    def test_build_field_help_idempotent(self):
        result1 = _build_field_help()
        result2 = _build_field_help()
        assert result1 == result2

    def test_no_comment_keys_in_output(self):
        for key in CONFIG_FIELD_HELP:
            assert not key.startswith("_comment_"), f"Raw comment key leaked: {key!r}"

    def test_on_scan_error_text_mentions_allow_and_block(self):
        text = CONFIG_FIELD_HELP.get("on_scan_error", "")
        assert "allow" in text.lower() or "fail-open" in text.lower()
        assert "block" in text.lower() or "fail-closed" in text.lower()

    def test_secret_scanning_action_key_absent(self):
        assert "secret_scanning.action" not in CONFIG_FIELD_HELP


nicegui = pytest.importorskip("nicegui", reason="NiceGUI not available")


class TestFieldHelpIconFunction:
    """Smoke tests that field_help_icon() doesn't raise outside NiceGUI context."""

    def test_returns_none_for_missing_key(self):
        from unittest.mock import patch

        with patch.dict(
            "ai_guardian.help_content.CONFIG_FIELD_HELP",
            {},
            clear=True,
        ):
            from ai_guardian.web.components.help_panel import field_help_icon

            result = field_help_icon("nonexistent.key")
            assert result is None

    def test_function_exists_and_is_callable(self):
        from ai_guardian.web.components.help_panel import field_help_icon

        assert callable(field_help_icon)
