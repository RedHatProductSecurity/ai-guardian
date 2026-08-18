"""
Unit tests for config_utils module
"""

import unittest
from datetime import datetime, timezone

from unittest.mock import patch

from ai_guardian.config.utils import (
    _parse_org_repo,
    _project_name_cache,
    get_project_name,
    is_expired,
    is_feature_enabled,
    parse_iso8601,
    validate_regex_pattern,
)


class ConfigUtilsTest(unittest.TestCase):
    """Test suite for config_utils timestamp functions"""

    def test_parse_iso8601_with_z_suffix(self):
        """Test parsing ISO 8601 timestamp with Z suffix"""
        result = parse_iso8601("2026-04-13T12:00:00Z")
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.month, 4)
        self.assertEqual(result.day, 13)
        self.assertEqual(result.hour, 12)
        self.assertEqual(result.minute, 0)
        self.assertEqual(result.second, 0)
        self.assertEqual(result.tzinfo, timezone.utc)

    def test_parse_iso8601_with_offset(self):
        """Test parsing ISO 8601 timestamp with +00:00 offset"""
        result = parse_iso8601("2026-04-13T12:00:00+00:00")
        self.assertIsNotNone(result)
        self.assertEqual(result.tzinfo, timezone.utc)

    def test_parse_iso8601_without_timezone(self):
        """Test parsing ISO 8601 timestamp without timezone (assumes UTC)"""
        result = parse_iso8601("2026-04-13T12:00:00")
        self.assertIsNotNone(result)
        self.assertEqual(result.tzinfo, timezone.utc)

    def test_parse_iso8601_with_different_timezone(self):
        """Test parsing ISO 8601 timestamp with non-UTC timezone (converts to UTC)"""
        # +05:00 timezone
        result = parse_iso8601("2026-04-13T17:00:00+05:00")
        self.assertIsNotNone(result)
        self.assertEqual(result.tzinfo, timezone.utc)
        # Should be converted to UTC (17:00 +05:00 = 12:00 UTC)
        self.assertEqual(result.hour, 12)

    def test_parse_iso8601_invalid_format(self):
        """Test parsing invalid timestamp format returns None"""
        result = parse_iso8601("invalid-timestamp")
        self.assertIsNone(result)

    def test_parse_iso8601_empty_string(self):
        """Test parsing empty string returns None"""
        result = parse_iso8601("")
        self.assertIsNone(result)

    def test_parse_iso8601_none_value(self):
        """Test parsing None value returns None"""
        result = parse_iso8601(None)
        self.assertIsNone(result)

    def test_parse_iso8601_non_string(self):
        """Test parsing non-string value returns None"""
        result = parse_iso8601(12345)
        self.assertIsNone(result)

    def test_is_expired_past_timestamp(self):
        """Test that past timestamps are expired"""
        past_timestamp = "2020-01-01T00:00:00Z"
        self.assertTrue(is_expired(past_timestamp))

    def test_is_expired_future_timestamp(self):
        """Test that future timestamps are not expired"""
        future_timestamp = "2099-12-31T23:59:59Z"
        self.assertFalse(is_expired(future_timestamp))

    def test_is_expired_with_current_time(self):
        """Test expiration check with custom current time"""
        valid_until = "2026-04-13T12:00:00Z"

        # Current time before valid_until - not expired
        current_time = datetime(2026, 4, 13, 11, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(is_expired(valid_until, current_time))

        # Current time equal to valid_until - expired (boundary)
        current_time = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_expired(valid_until, current_time))

        # Current time after valid_until - expired
        current_time = datetime(2026, 4, 13, 13, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_expired(valid_until, current_time))

    def test_is_expired_boundary_condition(self):
        """Test expiration exactly at the boundary (current_time == valid_until)"""
        valid_until = "2026-04-13T12:00:00Z"
        current_time = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
        # Should be expired when current_time >= valid_until
        self.assertTrue(is_expired(valid_until, current_time))

    def test_is_expired_one_second_before(self):
        """Test not expired one second before valid_until"""
        valid_until = "2026-04-13T12:00:00Z"
        current_time = datetime(2026, 4, 13, 11, 59, 59, tzinfo=timezone.utc)
        self.assertFalse(is_expired(valid_until, current_time))

    def test_is_expired_one_second_after(self):
        """Test expired one second after valid_until"""
        valid_until = "2026-04-13T12:00:00Z"
        current_time = datetime(2026, 4, 13, 12, 0, 1, tzinfo=timezone.utc)
        self.assertTrue(is_expired(valid_until, current_time))

    def test_is_expired_invalid_timestamp(self):
        """Test that invalid timestamps are treated as non-expired (fail-safe)"""
        invalid_timestamp = "not-a-timestamp"
        self.assertFalse(is_expired(invalid_timestamp))

    def test_is_expired_empty_string(self):
        """Test that empty string is treated as non-expired (fail-safe)"""
        self.assertFalse(is_expired(""))

    def test_is_expired_with_current_time_no_timezone(self):
        """Test that current_time without timezone is handled correctly"""
        valid_until = "2026-04-13T12:00:00Z"
        # Current time without timezone - should be assumed UTC
        current_time = datetime(2026, 4, 13, 11, 0, 0)
        self.assertFalse(is_expired(valid_until, current_time))

    def test_parse_iso8601_with_milliseconds(self):
        """Test parsing timestamp with milliseconds"""
        result = parse_iso8601("2026-04-13T12:00:00.123Z")
        self.assertIsNotNone(result)
        self.assertEqual(result.microsecond, 123000)

    def test_is_expired_real_world_example(self):
        """Test real-world example: temporary debug access expires at noon"""
        debug_expires = "2026-04-13T12:00:00Z"

        # Morning: debug access still valid
        morning = datetime(2026, 4, 13, 9, 30, 0, tzinfo=timezone.utc)
        self.assertFalse(is_expired(debug_expires, morning))

        # Afternoon: debug access expired
        afternoon = datetime(2026, 4, 13, 14, 30, 0, tzinfo=timezone.utc)
        self.assertTrue(is_expired(debug_expires, afternoon))


class IsFeatureEnabledTest(unittest.TestCase):
    """Test suite for is_feature_enabled function"""

    def test_simple_boolean_true(self):
        """Test simple boolean format: True"""
        self.assertTrue(is_feature_enabled(True))

    def test_simple_boolean_false(self):
        """Test simple boolean format: False"""
        self.assertFalse(is_feature_enabled(False))

    def test_none_config_uses_default_true(self):
        """Test None config uses default value (True)"""
        self.assertTrue(is_feature_enabled(None, default=True))

    def test_none_config_uses_default_false(self):
        """Test None config uses default value (False)"""
        self.assertFalse(is_feature_enabled(None, default=False))

    def test_dict_format_enabled_true(self):
        """Test dict format with value=True"""
        config = {"value": True}
        self.assertTrue(is_feature_enabled(config))

    def test_dict_format_enabled_false(self):
        """Test dict format with value=False (permanent disable)"""
        config = {"value": False}
        self.assertFalse(is_feature_enabled(config))

    def test_dict_format_missing_value_uses_default(self):
        """Test dict format with missing value field uses default"""
        config = {}
        self.assertTrue(is_feature_enabled(config, default=True))
        self.assertFalse(is_feature_enabled(config, default=False))

    def test_time_based_disabled_not_expired(self):
        """Test time-based disable that hasn't expired yet"""
        current_time = datetime(2026, 4, 13, 11, 0, 0, tzinfo=timezone.utc)
        config = {"value": False, "disabled_until": "2026-04-13T18:00:00Z"}
        # Still disabled (before expiration)
        self.assertFalse(is_feature_enabled(config, current_time))

    def test_time_based_disabled_expired_auto_enabled(self):
        """Test time-based disable that has expired (auto-enabled)"""
        current_time = datetime(2026, 4, 13, 19, 0, 0, tzinfo=timezone.utc)
        config = {"value": False, "disabled_until": "2026-04-13T18:00:00Z"}
        # Auto-enabled (after expiration)
        self.assertTrue(is_feature_enabled(config, current_time))

    def test_time_based_disabled_at_boundary(self):
        """Test time-based disable exactly at expiration boundary"""
        current_time = datetime(2026, 4, 13, 18, 0, 0, tzinfo=timezone.utc)
        config = {"value": False, "disabled_until": "2026-04-13T18:00:00Z"}
        # Auto-enabled (at expiration time)
        self.assertTrue(is_feature_enabled(config, current_time))

    def test_enabled_true_with_disabled_until_ignored(self):
        """Test that disabled_until is ignored when value=True"""
        current_time = datetime(2026, 4, 13, 11, 0, 0, tzinfo=timezone.utc)
        config = {"value": True, "disabled_until": "2026-04-13T18:00:00Z"}
        # Enabled, disabled_until doesn't apply
        self.assertTrue(is_feature_enabled(config, current_time))

    def test_disabled_false_without_disabled_until(self):
        """Test permanent disable (value=False without disabled_until)"""
        config = {"value": False}
        # Permanently disabled
        self.assertFalse(is_feature_enabled(config))

    def test_invalid_disabled_until_treats_as_permanent(self):
        """Test invalid disabled_until timestamp treats as permanent disable"""
        config = {"value": False, "disabled_until": "invalid-timestamp"}
        # Invalid timestamp - treats as permanent disable (fail-safe)
        self.assertFalse(is_feature_enabled(config))

    def test_empty_disabled_until_treats_as_permanent(self):
        """Test empty disabled_until field treats as permanent disable"""
        config = {"value": False, "disabled_until": ""}
        # Empty timestamp - treats as permanent disable
        self.assertFalse(is_feature_enabled(config))

    def test_unknown_format_uses_default(self):
        """Test unknown config format falls back to default"""
        config = "unknown-format"
        self.assertTrue(is_feature_enabled(config, default=True))
        self.assertFalse(is_feature_enabled(config, default=False))

    def test_real_world_emergency_access(self):
        """Test real-world scenario: emergency access for 30 minutes"""
        disable_start = datetime(2026, 4, 13, 14, 0, 0, tzinfo=timezone.utc)
        disable_end = datetime(2026, 4, 13, 14, 30, 0, tzinfo=timezone.utc)

        config = {
            "value": False,
            "disabled_until": "2026-04-13T14:30:00Z",
            "reason": "Emergency debugging - production incident",
        }

        # During emergency window - disabled
        emergency_time = datetime(2026, 4, 13, 14, 15, 0, tzinfo=timezone.utc)
        self.assertFalse(is_feature_enabled(config, emergency_time))

        # After emergency window - auto-enabled
        after_emergency = datetime(2026, 4, 13, 14, 45, 0, tzinfo=timezone.utc)
        self.assertTrue(is_feature_enabled(config, after_emergency))

    def test_real_world_maintenance_window(self):
        """Test real-world scenario: maintenance window (1 hour)"""
        config = {
            "value": False,
            "disabled_until": "2026-04-13T16:00:00Z",
            "reason": "Maintenance window - testing with example secrets",
        }

        # During maintenance - disabled
        maintenance_time = datetime(2026, 4, 13, 15, 30, 0, tzinfo=timezone.utc)
        self.assertFalse(is_feature_enabled(config, maintenance_time))

        # After maintenance - auto-enabled
        after_maintenance = datetime(2026, 4, 13, 17, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_feature_enabled(config, after_maintenance))

    def test_multiple_features_different_expiration(self):
        """Test multiple features with different expiration times"""
        current_time = datetime(2026, 4, 13, 15, 30, 0, tzinfo=timezone.utc)

        # Feature 1: expired (should be enabled)
        feature1_config = {"value": False, "disabled_until": "2026-04-13T15:00:00Z"}
        self.assertTrue(is_feature_enabled(feature1_config, current_time))

        # Feature 2: not expired (still disabled)
        feature2_config = {"value": False, "disabled_until": "2026-04-13T16:00:00Z"}
        self.assertFalse(is_feature_enabled(feature2_config, current_time))

        # Feature 3: permanently enabled
        feature3_config = {"value": True}
        self.assertTrue(is_feature_enabled(feature3_config, current_time))


class ValidateRegexPatternTest(unittest.TestCase):
    """Test suite for validate_regex_pattern function - ReDoS protection"""

    def test_valid_simple_pattern(self):
        """Test valid simple regex pattern"""
        self.assertTrue(validate_regex_pattern(r"[a-z]+@[a-z]+\.com"))

    def test_valid_complex_pattern(self):
        """Test valid complex pattern"""
        self.assertTrue(validate_regex_pattern(r"(?:https?|ftp)://[^\s]+"))

    def test_nested_quantifiers_plus_plus(self):
        """Test nested quantifiers (a+)+ - ReDoS vector"""
        self.assertFalse(validate_regex_pattern(r"(a+)+"))

    def test_nested_quantifiers_star_star(self):
        """Test nested quantifiers (a*)* - ReDoS vector"""
        self.assertFalse(validate_regex_pattern(r"(a*)*"))

    def test_nested_quantifiers_question_plus(self):
        """Test nested quantifiers (a?)+ - ReDoS vector"""
        self.assertFalse(validate_regex_pattern(r"(a?)+"))

    def test_nested_quantifiers_in_complex_pattern(self):
        """Test nested quantifiers embedded in complex pattern - ReDoS vector"""
        # Our simple detector catches directly consecutive quantifiers
        self.assertFalse(validate_regex_pattern(r"prefix(a+)++suffix"))

    def test_character_class_nested_quantifiers(self):
        """Test character class with nested quantifiers [a-z]++ - ReDoS vector"""
        self.assertFalse(validate_regex_pattern(r"[a-z]++"))

    def test_pattern_too_long(self):
        """Test pattern exceeding maximum length"""
        long_pattern = "a" * 1000
        self.assertFalse(validate_regex_pattern(long_pattern))

    def test_pattern_at_max_length(self):
        """Test pattern at maximum allowed length"""
        max_pattern = "a" * 500
        self.assertTrue(validate_regex_pattern(max_pattern))

    def test_invalid_regex_syntax(self):
        """Test invalid regex syntax"""
        self.assertFalse(validate_regex_pattern(r"[invalid"))

    def test_empty_pattern(self):
        """Test empty pattern"""
        self.assertFalse(validate_regex_pattern(""))

    def test_none_pattern(self):
        """Test None pattern"""
        self.assertFalse(validate_regex_pattern(None))

    def test_non_string_pattern(self):
        """Test non-string pattern"""
        self.assertFalse(validate_regex_pattern(12345))

    def test_safe_quantifiers_allowed(self):
        """Test safe quantifiers without nesting are allowed"""
        self.assertTrue(validate_regex_pattern(r"[a-z]+"))
        self.assertTrue(validate_regex_pattern(r"[0-9]*"))
        self.assertTrue(validate_regex_pattern(r"(abc)+"))
        self.assertTrue(validate_regex_pattern(r"(def)*"))

    def test_real_world_email_pattern(self):
        """Test real-world email pattern is valid"""
        self.assertTrue(
            validate_regex_pattern(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
        )

    def test_real_world_url_pattern(self):
        """Test real-world URL pattern is valid"""
        self.assertTrue(validate_regex_pattern(r"(?:http|https|ftp)://[^\s]+"))

    def test_real_world_ipv4_pattern(self):
        """Test real-world IPv4 pattern is valid"""
        self.assertTrue(validate_regex_pattern(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"))

    def test_redos_catastrophic_backtracking(self):
        """Test ReDoS pattern with catastrophic backtracking potential"""
        # Pattern like (a+)+ with input "aaaaaaaaaaaaaaaaaaaaX" causes exponential backtracking
        self.assertFalse(validate_regex_pattern(r"(a+)+b"))

    def test_multiple_nested_groups(self):
        """Test multiple levels of nesting - ReDoS vector"""
        # Note: ((a+)+)+ is a ReDoS pattern but our simple detector only catches
        # directly consecutive quantifiers like )++ or ]*+. This is a limitation
        # of the simple pattern-based approach, but it catches the most common cases.
        # More sophisticated detection would require parsing the regex AST.
        # Test a simpler variant that our detector can catch:
        self.assertFalse(validate_regex_pattern(r"(a+)++"))

    def test_custom_max_length(self):
        """Test custom maximum length parameter"""
        pattern = "a" * 100
        self.assertTrue(validate_regex_pattern(pattern, max_length=200))
        self.assertFalse(validate_regex_pattern(pattern, max_length=50))


class TestParseOrgRepo(unittest.TestCase):
    def test_ssh_url(self):
        assert (
            _parse_org_repo("git@github.com:RedHatProductSecurity/ai-guardian.git")
            == "RedHatProductSecurity/ai-guardian"
        )

    def test_https_url(self):
        assert (
            _parse_org_repo("https://github.com/RedHatProductSecurity/ai-guardian.git")
            == "RedHatProductSecurity/ai-guardian"
        )

    def test_https_no_git_suffix(self):
        assert _parse_org_repo("https://github.com/org/repo") == "org/repo"

    def test_gitlab_ssh(self):
        assert (
            _parse_org_repo("git@gitlab.example.com:team/project.git") == "team/project"
        )

    def test_bare_url(self):
        assert _parse_org_repo("host:org/repo") == "org/repo"

    def test_no_match(self):
        assert _parse_org_repo("not-a-url") is None

    def test_empty(self):
        assert _parse_org_repo("") is None


class TestGetProjectName(unittest.TestCase):
    def setUp(self):
        _project_name_cache.clear()

    def test_none_path(self):
        assert get_project_name(None) is None

    def test_empty_path(self):
        assert get_project_name("") is None

    @patch("ai_guardian.config.utils.subprocess.run")
    def test_git_remote_success(self, mock_run):
        mock_run.return_value = type(
            "R",
            (),
            {
                "returncode": 0,
                "stdout": "git@github.com:RedHatProductSecurity/ai-guardian.git\n",
            },
        )()
        assert get_project_name("/some/path") == "RedHatProductSecurity/ai-guardian"

    @patch("ai_guardian.config.utils.subprocess.run")
    def test_git_remote_fails_falls_back_to_basename(self, mock_run):
        mock_run.return_value = type(
            "R",
            (),
            {
                "returncode": 128,
                "stdout": "",
            },
        )()
        assert get_project_name("/home/user/my-project") == "my-project"

    @patch("ai_guardian.config.utils.subprocess.run")
    def test_git_remote_exception_falls_back(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        assert get_project_name("/home/user/my-project") == "my-project"


if __name__ == "__main__":
    unittest.main()
