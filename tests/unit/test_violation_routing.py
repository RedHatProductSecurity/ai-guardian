"""Tests for violation routing based on finding category (Issue #984).

Verifies that _log_finding_violation routes findings to the correct
ViolationType based on the category field in secret_details.
"""

from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.constants import ViolationType
from ai_guardian.scanners.strategies import SecretMatch


class TestCategoryViolationRouting:
    """Test _log_finding_violation routes to correct violation type."""

    @pytest.fixture(autouse=True)
    def _patch_logger(self):
        with patch("ai_guardian.scanners.secret_scanning.HAS_VIOLATION_LOGGER", True):
            yield

    def _call_log_finding(self, category, rule_id="test-rule", engine="toml-patterns"):
        from ai_guardian.scanners.secret_scanning import _log_finding_violation

        mock_logger = MagicMock()
        details = {
            "rule_id": rule_id,
            "engine": engine,
            "category": category,
            "line_number": 1,
        }
        _log_finding_violation("test.py", {}, details, violation_logger=mock_logger)
        return mock_logger

    def test_pii_category_routes_to_pii_detected(self):
        mock_logger = self._call_log_finding("pii", rule_id="pii-ssn")
        mock_logger.log_sensitive_finding.assert_called_once()
        assert (
            mock_logger.log_sensitive_finding.call_args.kwargs["violation_type"]
            == "pii_detected"
        )
        mock_logger.log_violation.assert_not_called()

    def test_pii_persistence_omits_engine_and_rule_details(self):
        mock_logger = self._call_log_finding("pii", rule_id="pii-ssn")
        kwargs = mock_logger.log_sensitive_finding.call_args.kwargs
        assert set(kwargs) == {"violation_type", "severity", "violation_id"}
        assert "toml-patterns" not in str(kwargs)
        assert "pii-ssn" not in str(kwargs)

    def test_secrets_category_routes_to_secret_detected(self):
        mock_logger = self._call_log_finding("secrets", rule_id="openai-api-key")
        mock_logger.log_sensitive_finding.assert_called_once()
        assert (
            mock_logger.log_sensitive_finding.call_args.kwargs["violation_type"]
            == "secret_detected"
        )
        mock_logger.log_violation.assert_not_called()

    def test_none_category_routes_to_secret_detected(self):
        mock_logger = self._call_log_finding(None, rule_id="some-rule")
        mock_logger.log_sensitive_finding.assert_called_once()
        assert (
            mock_logger.log_sensitive_finding.call_args.kwargs["violation_type"]
            == "secret_detected"
        )

    def test_prompt_injection_category_routes_correctly(self):
        mock_logger = self._call_log_finding(
            "prompt_injection", rule_id="pi-critical-001"
        )
        call_kwargs = mock_logger.log_violation.call_args
        assert call_kwargs.kwargs["violation_type"] == ViolationType.PROMPT_INJECTION

    def test_unicode_category_routes_to_prompt_injection(self):
        mock_logger = self._call_log_finding("unicode", rule_id="zw-space")
        call_kwargs = mock_logger.log_violation.call_args
        assert call_kwargs.kwargs["violation_type"] == ViolationType.PROMPT_INJECTION

    def test_config_exfil_category_routes_correctly(self):
        mock_logger = self._call_log_finding(
            "config_exfil", rule_id="curl_with_env_vars"
        )
        call_kwargs = mock_logger.log_violation.call_args
        assert call_kwargs.kwargs["violation_type"] == ViolationType.CONFIG_FILE_EXFIL

    def test_ssrf_category_routes_correctly(self):
        mock_logger = self._call_log_finding("ssrf", rule_id="ssrf-private-class-a")
        call_kwargs = mock_logger.log_violation.call_args
        assert call_kwargs.kwargs["violation_type"] == ViolationType.SSRF_BLOCKED

    def test_unknown_category_falls_back_to_secret(self):
        mock_logger = self._call_log_finding("unknown_category", rule_id="test")
        assert (
            mock_logger.log_sensitive_finding.call_args.kwargs["violation_type"]
            == "secret_detected"
        )


class TestSecretDetectionReasonString:
    """Test secret records do not persist scanner engine/rule details."""

    @pytest.fixture(autouse=True)
    def _patch_logger(self):
        with patch("ai_guardian.scanners.secret_scanning.HAS_VIOLATION_LOGGER", True):
            yield

    def test_engine_name_is_not_persisted(self):
        from ai_guardian.scanners.secret_scanning import _log_secret_detection_violation

        mock_logger = MagicMock()
        details = {"rule_id": "test", "engine": "toml-patterns"}
        _log_secret_detection_violation(
            "test.py", {}, details, violation_logger=mock_logger
        )
        kwargs = mock_logger.log_sensitive_finding.call_args.kwargs
        assert set(kwargs) == {"violation_type", "severity", "violation_id"}
        assert "toml-patterns" not in str(kwargs)

    def test_rule_detail_is_not_persisted(self):
        from ai_guardian.scanners.secret_scanning import _log_secret_detection_violation

        mock_logger = MagicMock()
        details = {"rule_id": "test"}
        _log_secret_detection_violation(
            "test.py", {}, details, violation_logger=mock_logger
        )
        kwargs = mock_logger.log_sensitive_finding.call_args.kwargs
        assert "Gitleaks" not in str(kwargs)


class TestSecretMatchCategory:
    """Test SecretMatch carries category field."""

    def test_category_field_exists(self):
        sm = SecretMatch(
            rule_id="pii-ssn",
            description="SSN",
            file="test.py",
            line_number=1,
            category="pii",
        )
        assert sm.category == "pii"

    def test_category_defaults_to_none(self):
        sm = SecretMatch(
            rule_id="test",
            description="test",
            file="test.py",
            line_number=1,
        )
        assert sm.category is None


class TestErrorBannerCategoryAware:
    """Test _build_secret_detected_message shows category-specific banners."""

    def _build(self, category, rule_id="test-rule"):
        from ai_guardian.scanners.secret_scanning import _build_secret_detected_message

        details = {
            "rule_id": rule_id,
            "file": "test.py",
            "line_number": 1,
            "category": category,
        }
        return _build_secret_detected_message(
            "toml-patterns", details, "Built-in rules"
        )

    def test_pii_banner_title(self):
        msg = self._build("pii", "pii-ssn")
        assert "PII Detected" in msg
        assert "Secret Detected" not in msg

    def test_pii_banner_type_label(self):
        msg = self._build("pii", "pii-ssn")
        assert "PII Type: Social Security Number (SSN)" in msg

    def test_pii_banner_protection_label(self):
        msg = self._build("pii", "pii-ssn")
        assert "PII Scanning" in msg

    def test_prompt_injection_banner_title(self):
        msg = self._build("prompt_injection", "pi-critical-001")
        assert "Prompt Injection Detected" in msg

    def test_unicode_banner_title(self):
        msg = self._build("unicode", "zw-space")
        assert "Unicode Attack Detected" in msg

    def test_config_exfil_banner_title(self):
        msg = self._build("config_exfil", "curl_with_env_vars")
        assert "Config Exfiltration Detected" in msg

    def test_ssrf_banner_title(self):
        msg = self._build("ssrf", "ssrf-private-class-a")
        assert "SSRF Pattern Detected" in msg

    def test_secrets_banner_unchanged(self):
        msg = self._build("secrets", "openai-api-key")
        assert "Secret Detected" in msg
        assert "Secret Type: OpenAI API Key" in msg

    def test_none_category_shows_secret_banner(self):
        msg = self._build(None, "some-rule")
        assert "Secret Detected" in msg

    def test_pii_no_secret_footer(self):
        msg = self._build("pii", "pii-ssn")
        assert "Secret value NOT shown" not in msg

    def test_secrets_has_secret_footer(self):
        msg = self._build("secrets", "test-key")
        assert "Secret value NOT shown" in msg
