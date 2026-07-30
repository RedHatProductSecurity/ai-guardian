#!/usr/bin/env python3
"""
Tests for the Regex Tester TUI panel.

Tests the find_matches() helper function and config integration logic.
"""

import json
import re


from ai_guardian.tui.regex_tester import (
    RegexTesterContent,
    find_matches,
    CONFIG_SECTIONS,
    MAX_MATCHES_DISPLAYED,
)


class TestFindMatches:
    """Tests for the find_matches() helper function."""

    def test_valid_pattern_finds_matches(self):
        is_valid, error, matches = find_matches(r"hello", "hello world hello")
        assert is_valid is True
        assert error == ""
        assert len(matches) == 2
        assert matches[0]["text"] == "hello"
        assert matches[0]["start"] == 0
        assert matches[0]["end"] == 5
        assert matches[1]["text"] == "hello"
        assert matches[1]["start"] == 12
        assert matches[1]["end"] == 17

    def test_match_positions_correct(self):
        is_valid, error, matches = find_matches(r"\d+", "abc 123 def 456")
        assert is_valid is True
        assert len(matches) == 2
        assert matches[0]["text"] == "123"
        assert matches[0]["start"] == 4
        assert matches[0]["end"] == 7
        assert matches[1]["text"] == "456"
        assert matches[1]["start"] == 12
        assert matches[1]["end"] == 15

    def test_invalid_regex_syntax_returns_error(self):
        is_valid, error, matches = find_matches(r"[invalid", "test")
        assert is_valid is False
        assert error != ""
        assert matches == []

    def test_redos_pattern_rejected(self):
        is_valid, error, matches = find_matches(r"(a+)+b", "aaa")
        assert is_valid is False
        assert "ReDoS" in error
        assert matches == []

    def test_empty_pattern_no_matches(self):
        is_valid, error, matches = find_matches("", "hello world")
        assert is_valid is True
        assert error == ""
        assert matches == []

    def test_empty_text_no_matches(self):
        is_valid, error, matches = find_matches(r"hello", "")
        assert is_valid is True
        assert error == ""
        assert matches == []

    def test_no_matches_found(self):
        is_valid, error, matches = find_matches(r"xyz", "hello world")
        assert is_valid is True
        assert error == ""
        assert matches == []

    def test_case_insensitive_flag(self):
        is_valid, _, matches = find_matches(
            r"hello", "Hello HELLO hello", flags=re.IGNORECASE
        )
        assert is_valid is True
        assert len(matches) == 3

    def test_case_sensitive_no_flag(self):
        is_valid, _, matches = find_matches(r"hello", "Hello HELLO hello", flags=0)
        assert is_valid is True
        assert len(matches) == 1
        assert matches[0]["text"] == "hello"

    def test_multiline_flag(self):
        text = "hello\nworld\nhello"
        is_valid, _, matches = find_matches(r"^hello$", text, flags=re.MULTILINE)
        assert is_valid is True
        assert len(matches) == 2

    def test_multiline_flag_off(self):
        text = "hello\nworld\nhello"
        is_valid, _, matches = find_matches(r"^hello$", text, flags=0)
        assert is_valid is True
        assert len(matches) == 0

    def test_combined_flags(self):
        text = "Hello\nWorld\nHELLO"
        is_valid, _, matches = find_matches(
            r"^hello$", text, flags=re.IGNORECASE | re.MULTILINE
        )
        assert is_valid is True
        assert len(matches) == 2

    def test_match_count_capped(self):
        text = " ".join(["abc"] * 200)
        is_valid, _, matches = find_matches(r"abc", text, max_matches=100)
        assert is_valid is True
        assert len(matches) == 100

    def test_match_line_numbers(self):
        text = "first\nsecond match\nthird match"
        is_valid, _, matches = find_matches(r"match", text)
        assert is_valid is True
        assert len(matches) == 2
        assert matches[0]["line"] == 2
        assert matches[1]["line"] == 3

    def test_match_line_number_first_line(self):
        text = "hello world"
        is_valid, _, matches = find_matches(r"hello", text)
        assert is_valid is True
        assert matches[0]["line"] == 1

    def test_email_pattern(self):
        text = "Contact user@example.com or admin@test.org for help"
        is_valid, _, matches = find_matches(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
        assert is_valid is True
        assert len(matches) == 2
        assert matches[0]["text"] == "user@example.com"
        assert matches[1]["text"] == "admin@test.org"

    def test_pattern_with_groups(self):
        text = "2026-05-01 and 2026-12-25"
        is_valid, _, matches = find_matches(r"\d{4}-\d{2}-\d{2}", text)
        assert is_valid is True
        assert len(matches) == 2
        assert matches[0]["text"] == "2026-05-01"

    def test_nested_quantifier_variations_rejected(self):
        patterns = [r"(a*)*b", r"(a?)+b", r"([a-z]++)"]
        for pattern in patterns:
            is_valid, error, matches = find_matches(pattern, "test")
            assert is_valid is False, f"Pattern {pattern} should be rejected"
            assert matches == []

    def test_custom_max_matches(self):
        text = "a " * 50
        is_valid, _, matches = find_matches(r"a", text, max_matches=5)
        assert is_valid is True
        assert len(matches) == 5


class TestConfigSections:
    """Tests for config section mapping."""

    def test_config_sections_has_four_entries(self):
        assert len(CONFIG_SECTIONS) == 4

    def test_config_sections_keys(self):
        assert "prompt_injection" in CONFIG_SECTIONS
        assert "context_poisoning" in CONFIG_SECTIONS
        assert "scan_pii" in CONFIG_SECTIONS
        assert "secret_scanning" in CONFIG_SECTIONS

    def test_config_sections_values(self):
        assert CONFIG_SECTIONS["prompt_injection"] == (
            "prompt_injection",
            "allowlist_patterns",
        )
        assert CONFIG_SECTIONS["scan_pii"] == ("scan_pii", "allowlist_patterns")
        assert CONFIG_SECTIONS["secret_scanning"] == (
            "secret_scanning",
            "allowlist_patterns",
        )


class TestConfigIntegration:
    """Tests for adding patterns to config files."""

    def _write_config(self, config_dir, config):
        config_path = config_dir / "ai-guardian.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return config_path

    def _read_config(self, config_dir):
        config_path = config_dir / "ai-guardian.json"
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_add_pattern_to_prompt_injection(self, tmp_path):
        config = {"prompt_injection": {"allowlist_patterns": []}}
        self._write_config(tmp_path, config)

        result = self._read_config(tmp_path)
        result["prompt_injection"]["allowlist_patterns"].append(r"test.*pattern")
        self._write_config(tmp_path, result)

        saved = self._read_config(tmp_path)
        assert r"test.*pattern" in saved["prompt_injection"]["allowlist_patterns"]

    def test_add_pattern_to_scan_pii(self, tmp_path):
        config = {"scan_pii": {"allowlist_patterns": []}}
        self._write_config(tmp_path, config)

        result = self._read_config(tmp_path)
        result["scan_pii"]["allowlist_patterns"].append(r"user@example\.com")
        self._write_config(tmp_path, result)

        saved = self._read_config(tmp_path)
        assert r"user@example\.com" in saved["scan_pii"]["allowlist_patterns"]

    def test_add_pattern_to_secret_scanning(self, tmp_path):
        config = {"secret_scanning": {"allowlist_patterns": []}}
        self._write_config(tmp_path, config)

        result = self._read_config(tmp_path)
        result["secret_scanning"]["allowlist_patterns"].append(r"pk_test_[A-Za-z0-9]+")
        self._write_config(tmp_path, result)

        saved = self._read_config(tmp_path)
        assert r"pk_test_[A-Za-z0-9]+" in saved["secret_scanning"]["allowlist_patterns"]

    def test_creates_missing_section_keys(self, tmp_path):
        config = {}
        self._write_config(tmp_path, config)

        result = self._read_config(tmp_path)
        section_key = "prompt_injection"
        field_key = "allowlist_patterns"
        if section_key not in result:
            result[section_key] = {}
        if field_key not in result[section_key]:
            result[section_key][field_key] = []
        result[section_key][field_key].append(r"new_pattern")
        self._write_config(tmp_path, result)

        saved = self._read_config(tmp_path)
        assert "prompt_injection" in saved
        assert "allowlist_patterns" in saved["prompt_injection"]
        assert r"new_pattern" in saved["prompt_injection"]["allowlist_patterns"]

    def test_duplicate_detection(self, tmp_path):
        config = {"prompt_injection": {"allowlist_patterns": [r"existing"]}}
        self._write_config(tmp_path, config)

        result = self._read_config(tmp_path)
        existing = result["prompt_injection"]["allowlist_patterns"]
        is_duplicate = r"existing" in existing
        assert is_duplicate is True

    def test_duplicate_detection_with_dict_entries(self, tmp_path):
        config = {
            "prompt_injection": {
                "allowlist_patterns": [
                    {"pattern": r"dict_pattern", "valid_until": "2026-12-01T00:00:00Z"}
                ]
            }
        }
        self._write_config(tmp_path, config)

        result = self._read_config(tmp_path)
        existing = result["prompt_injection"]["allowlist_patterns"]
        pattern_to_check = r"dict_pattern"
        is_duplicate = any(
            (entry if isinstance(entry, str) else entry.get("pattern", ""))
            == pattern_to_check
            for entry in existing
        )
        assert is_duplicate is True


class TestRegexTesterContentInit:
    """Tests for RegexTesterContent widget initialization."""

    def test_content_class_exists(self):
        assert RegexTesterContent is not None

    def test_content_has_css(self):
        assert hasattr(RegexTesterContent, "CSS")
        assert len(RegexTesterContent.CSS) > 0

    def test_max_matches_constant(self):
        assert MAX_MATCHES_DISPLAYED == 100
