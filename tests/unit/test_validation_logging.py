"""Tests for validation status in violation data (Issue #983).

Verifies that:
1. _apply_secret_validation returns validation_info when enabled
2. _apply_secret_validation returns None when disabled
3. Validation info is included in violation logged data
4. Inactive secrets still produce a violation log entry
"""

from unittest.mock import MagicMock, patch
from dataclasses import dataclass
from enum import Enum

import pytest


class MockValidationStatus(str, Enum):
    VERIFIED = "verified"
    INACTIVE = "inactive"
    UNVERIFIED = "unverified"


@dataclass
class MockValidationResult:
    status: MockValidationStatus
    rule_id: str
    message: str = ""
    response_code: int = None
    elapsed_ms: float = 0.0


class TestApplySecretValidationReturnType:
    """Test _apply_secret_validation returns dict with validation_info."""

    def test_returns_none_when_disabled(self):
        from ai_guardian.scanners.secret_scanning import _apply_secret_validation

        result = _apply_secret_validation(
            {"validate_secrets": False},
            [{"rule_id": "test", "line_number": 1}],
            "content",
        )
        assert result is None

    def test_returns_none_when_no_config(self):
        from ai_guardian.scanners.secret_scanning import _apply_secret_validation

        result = _apply_secret_validation(
            None, [{"rule_id": "test", "line_number": 1}], "content"
        )
        assert result is None

    def test_returns_none_when_no_secrets(self):
        from ai_guardian.scanners.secret_scanning import _apply_secret_validation

        result = _apply_secret_validation({"validate_secrets": True}, [], "content")
        assert result is None

    @patch("ai_guardian.hook_processing.logger")
    def test_returns_unverified_when_no_validators(self, mock_logging):
        """When validate_secrets=true but no validator exists for the rule."""
        mock_validator = MagicMock()
        mock_validator.enabled = True
        mock_validator.has_validator.return_value = False

        with patch.dict(
            "sys.modules", {"ai_guardian.scanners.secret_validator": MagicMock()}
        ):
            with patch(
                "ai_guardian.scanners.secret_scanning._apply_secret_validation"
            ) as mock_fn:
                # Test the actual logic by importing fresh
                pass

        # Test directly with the function
        from ai_guardian.scanners.secret_scanning import _apply_secret_validation

        mock_module = MagicMock()
        mock_module.SecretValidator.return_value = mock_validator
        mock_module.ValidationStatus = MockValidationStatus

        with patch.dict(
            "sys.modules", {"ai_guardian.scanners.secret_validator": mock_module}
        ):
            result = _apply_secret_validation(
                {"validate_secrets": True},
                [{"rule_id": "unknown-rule", "line_number": 1}],
                "some content",
            )

        assert result is not None
        assert result["skip_block"] is False
        assert result["validation_info"]["status"] == "unverified"
        assert "No validator" in result["validation_info"]["message"]

    @patch("ai_guardian.hook_processing.logger")
    def test_returns_inactive_with_skip_block(self, mock_logging):
        """When all secrets are inactive, skip_block=True with validation_info."""
        mock_validator = MagicMock()
        mock_validator.enabled = True
        mock_validator.has_validator.return_value = True
        mock_validator.on_inactive = "warn"

        inactive_result = MockValidationResult(
            status=MockValidationStatus.INACTIVE,
            rule_id="github-personal-token",
            message="Token returned 401",
            elapsed_ms=150.0,
        )
        mock_validator.validate_secrets.return_value = [inactive_result]
        mock_validator.filter_inactive.return_value = (
            [],
            [{"rule_id": "github-personal-token"}],
        )

        mock_module = MagicMock()
        mock_module.SecretValidator.return_value = mock_validator
        mock_module.ValidationStatus = MockValidationStatus

        from ai_guardian.scanners.secret_scanning import _apply_secret_validation

        with patch.dict(
            "sys.modules", {"ai_guardian.scanners.secret_validator": mock_module}
        ):
            result = _apply_secret_validation(
                {"validate_secrets": True},
                [{"rule_id": "github-personal-token", "line_number": 1}],
                "ghp_testtoken123",
            )

        assert result is not None
        assert result["skip_block"] is True
        assert result["validation_info"]["status"] == "inactive"
        assert result["validation_info"]["message"] == "Token returned 401"
        assert result["validation_info"]["elapsed_ms"] == 150.0

    @patch("ai_guardian.hook_processing.logger")
    def test_returns_verified_with_no_skip(self, mock_logging):
        """When secret is active, skip_block=False with status=verified."""
        mock_validator = MagicMock()
        mock_validator.enabled = True
        mock_validator.has_validator.return_value = True

        verified_result = MockValidationResult(
            status=MockValidationStatus.VERIFIED,
            rule_id="github-personal-token",
            message="Token is active (HTTP 200)",
            elapsed_ms=200.0,
        )
        mock_validator.validate_secrets.return_value = [verified_result]
        mock_validator.filter_inactive.return_value = (
            [{"rule_id": "github-personal-token"}],
            [],
        )

        mock_module = MagicMock()
        mock_module.SecretValidator.return_value = mock_validator
        mock_module.ValidationStatus = MockValidationStatus

        from ai_guardian.scanners.secret_scanning import _apply_secret_validation

        with patch.dict(
            "sys.modules", {"ai_guardian.scanners.secret_validator": mock_module}
        ):
            result = _apply_secret_validation(
                {"validate_secrets": True},
                [{"rule_id": "github-personal-token", "line_number": 1}],
                "ghp_testtoken123",
            )

        assert result is not None
        assert result["skip_block"] is False
        assert result["validation_info"]["status"] == "verified"
        assert result["validation_info"]["message"] == "Token is active (HTTP 200)"
        assert result["validation_info"]["elapsed_ms"] == 200.0

    @patch("ai_guardian.hook_processing.logger")
    def test_returns_error_on_exception(self, mock_logging):
        """On validation exception, return status=error instead of None."""
        mock_module = MagicMock()
        mock_module.SecretValidator.side_effect = RuntimeError("connection refused")
        mock_module.ValidationStatus = MockValidationStatus

        from ai_guardian.scanners.secret_scanning import _apply_secret_validation

        with patch.dict(
            "sys.modules", {"ai_guardian.scanners.secret_validator": mock_module}
        ):
            result = _apply_secret_validation(
                {"validate_secrets": True},
                [{"rule_id": "github-personal-token", "line_number": 1}],
                "ghp_testtoken123",
            )

        assert result is not None
        assert result["skip_block"] is False
        assert result["validation_info"]["status"] == "error"
        assert "connection refused" in result["validation_info"]["message"]


class TestValidationFieldInViolation:
    """Test that sensitive event history omits validation detail."""

    @pytest.fixture(autouse=True)
    def _patch_logger(self):
        with patch("ai_guardian.scanners.secret_scanning.HAS_VIOLATION_LOGGER", True):
            yield

    @staticmethod
    def _assert_sensitive_envelope(mock_logger, expected_type, expected_severity):
        mock_logger.log_sensitive_finding.assert_called_once()
        mock_logger.log_violation.assert_not_called()
        kwargs = mock_logger.log_sensitive_finding.call_args.kwargs
        assert kwargs.keys() == {"violation_type", "severity", "violation_id"}
        assert kwargs["violation_type"] == expected_type
        assert kwargs["severity"] == expected_severity

    def test_secret_violation_omits_validation_from_history(self):
        from ai_guardian.scanners.secret_scanning import _log_secret_detection_violation

        mock_logger = MagicMock()
        details = {
            "rule_id": "github-personal-token",
            "engine": "Gitleaks",
            "line_number": 42,
            "validation": {
                "status": "verified",
                "message": "Token is active (HTTP 200)",
                "elapsed_ms": 156,
            },
        }
        _log_secret_detection_violation(
            "test.py", {}, details, violation_logger=mock_logger
        )
        self._assert_sensitive_envelope(mock_logger, "secret_detected", "critical")
        assert details["validation"]["status"] == "verified"
        assert details["validation"]["elapsed_ms"] == 156

    def test_secret_violation_without_validation_uses_minimal_history(self):
        from ai_guardian.scanners.secret_scanning import _log_secret_detection_violation

        mock_logger = MagicMock()
        details = {
            "rule_id": "github-personal-token",
            "engine": "Gitleaks",
            "line_number": 42,
        }
        _log_secret_detection_violation(
            "test.py", {}, details, violation_logger=mock_logger
        )
        self._assert_sensitive_envelope(mock_logger, "secret_detected", "critical")

    def test_pii_finding_omits_validation_from_history(self):
        from ai_guardian.scanners.secret_scanning import _log_finding_violation

        mock_logger = MagicMock()
        details = {
            "rule_id": "pii-ssn",
            "engine": "toml-patterns",
            "category": "pii",
            "line_number": 10,
            "validation": {
                "status": "unverified",
                "message": "No validator for this rule",
                "elapsed_ms": 0,
            },
        }
        _log_finding_violation("test.py", {}, details, violation_logger=mock_logger)
        self._assert_sensitive_envelope(mock_logger, "pii_detected", "high")
        assert details["validation"]["status"] == "unverified"

    def test_pii_finding_without_validation_uses_minimal_history(self):
        from ai_guardian.scanners.secret_scanning import _log_finding_violation

        mock_logger = MagicMock()
        details = {
            "rule_id": "pii-ssn",
            "engine": "toml-patterns",
            "category": "pii",
            "line_number": 10,
        }
        _log_finding_violation("test.py", {}, details, violation_logger=mock_logger)
        self._assert_sensitive_envelope(mock_logger, "pii_detected", "high")

    def test_inactive_validation_status_is_not_persisted(self):
        """Inactive secrets still produce an envelope without validation text."""
        from ai_guardian.scanners.secret_scanning import _log_secret_detection_violation

        mock_logger = MagicMock()
        details = {
            "rule_id": "github-personal-token",
            "engine": "Gitleaks",
            "line_number": 5,
            "validation": {
                "status": "inactive",
                "message": "Token returned 401",
                "elapsed_ms": 120,
            },
        }
        _log_secret_detection_violation(
            "test.py", {}, details, violation_logger=mock_logger
        )
        self._assert_sensitive_envelope(mock_logger, "secret_detected", "critical")
        assert details["validation"]["status"] == "inactive"
        assert details["validation"]["message"] == "Token returned 401"

    def test_error_validation_status_is_not_persisted(self):
        from ai_guardian.scanners.secret_scanning import _log_secret_detection_violation

        mock_logger = MagicMock()
        details = {
            "rule_id": "github-personal-token",
            "engine": "Gitleaks",
            "line_number": 5,
            "validation": {
                "status": "error",
                "message": "Timeout after 3000ms",
                "elapsed_ms": 0,
            },
        }
        _log_secret_detection_violation(
            "test.py", {}, details, violation_logger=mock_logger
        )
        self._assert_sensitive_envelope(mock_logger, "secret_detected", "critical")
        assert details["validation"]["status"] == "error"
        assert "Timeout" in details["validation"]["message"]
