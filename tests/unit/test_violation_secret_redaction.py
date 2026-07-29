"""Tests for secret/PII value redaction in violation records (#1742)."""

from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.violations.redact import (
    REDACT_VIOLATION_TYPES,
    redact_secret_hint,
    sanitize_blocked_for_secret,
)


class TestRedactSecretHint:
    def test_long_value(self):
        assert redact_secret_hint("AKIAIOSFODNN7EXAMPLE") == "AKIA.*MPLE"

    def test_eight_chars(self):
        assert redact_secret_hint("12345678") == "1234.*5678"

    def test_short_value(self):
        assert redact_secret_hint("abcde") == "ab.*de"

    def test_four_chars(self):
        assert redact_secret_hint("abcd") == "ab.*cd"

    def test_three_chars(self):
        assert redact_secret_hint("abc") == "[redacted]"

    def test_empty(self):
        assert redact_secret_hint("") == "[redacted]"

    def test_none(self):
        assert redact_secret_hint(None) == "[redacted]"


class TestSanitizeBlockedForSecret:
    def test_file_based_drops_matched_text(self):
        blocked = {
            "file_path": "/code/main.py",
            "line_number": 42,
            "matched_text": "sk-live-SUPERSECRETKEY123456",
        }
        sanitize_blocked_for_secret(blocked)
        assert "matched_text" not in blocked
        assert "pattern_hint" not in blocked
        assert blocked["file_path"] == "/code/main.py"
        assert blocked["line_number"] == 42

    def test_non_file_adds_pattern_hint(self):
        blocked = {
            "matched_text": "AKIAIOSFODNN7EXAMPLE",
        }
        sanitize_blocked_for_secret(blocked)
        assert "matched_text" not in blocked
        assert blocked["pattern_hint"] == "AKIA.*MPLE"

    def test_non_file_short_secret(self):
        blocked = {"matched_text": "ab"}
        sanitize_blocked_for_secret(blocked)
        assert "matched_text" not in blocked
        assert blocked["pattern_hint"] == "[redacted]"

    def test_no_matched_text_is_noop(self):
        blocked = {"file_path": "/a.py", "line_number": 1}
        sanitize_blocked_for_secret(blocked)
        assert "matched_text" not in blocked
        assert "pattern_hint" not in blocked

    def test_findings_list_redacted(self):
        blocked = {
            "file_path": "/code/main.py",
            "line_number": 10,
            "findings": [
                {
                    "matched_text": "raw-secret-value-one",
                    "line_number": 10,
                    "start_column": 5,
                },
                {
                    "matched_text": "another-secret",
                    "line_number": None,
                    "start_column": None,
                },
            ],
        }
        sanitize_blocked_for_secret(blocked)
        assert "matched_text" not in blocked["findings"][0]
        assert "pattern_hint" not in blocked["findings"][0]
        assert "matched_text" not in blocked["findings"][1]
        assert blocked["findings"][1]["pattern_hint"] == "anot.*cret"

    def test_findings_with_position_data_stripped(self):
        blocked = {
            "file_path": "/a.py",
            "line_number": 5,
            "findings": [
                {
                    "matched_text": "secret123456",
                    "line_number": 5,
                    "start_column": 10,
                }
            ],
        }
        sanitize_blocked_for_secret(blocked)
        assert "matched_text" not in blocked["findings"][0]
        assert "pattern_hint" not in blocked["findings"][0]


class TestRedactViolationTypes:
    def test_secret_detected_in_set(self):
        assert "secret_detected" in REDACT_VIOLATION_TYPES

    def test_image_secret_in_set(self):
        assert "image_secret_detected" in REDACT_VIOLATION_TYPES

    def test_pii_in_set(self):
        assert "pii_detected" in REDACT_VIOLATION_TYPES

    def test_prompt_injection_not_in_set(self):
        assert "prompt_injection" not in REDACT_VIOLATION_TYPES


class TestLogSecretDetectionViolationRedacts:
    @patch("ai_guardian.scanners.secret_scanning.ViolationLogger")
    def test_no_raw_secret_in_logged_blocked(self, mock_logger_cls):
        from ai_guardian.scanners.secret_scanning import (
            _log_secret_detection_violation,
        )

        mock_logger = MagicMock()
        raw_secret = "AKIAIOSFODNN7EXAMPLE"
        _log_secret_detection_violation(
            filename="/code/config.py",
            secret_details={
                "rule_id": "aws-access-key",
                "line_number": 10,
                "start_column": 5,
                "end_column": 25,
                "findings": [
                    {
                        "matched_text": raw_secret,
                        "line_number": 10,
                        "start_column": 5,
                    }
                ],
            },
            violation_logger=mock_logger,
        )
        mock_logger.log_violation.assert_called_once()
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert raw_secret not in str(blocked)

    @patch("ai_guardian.scanners.secret_scanning.ViolationLogger")
    def test_non_file_secret_gets_pattern_hint(self, mock_logger_cls):
        from ai_guardian.scanners.secret_scanning import (
            _log_secret_detection_violation,
        )

        mock_logger = MagicMock()
        raw_secret = "AKIAIOSFODNN7EXAMPLE"
        _log_secret_detection_violation(
            filename="user_prompt",
            secret_details={
                "rule_id": "aws-access-key",
                "findings": [{"matched_text": raw_secret}],
            },
            violation_logger=mock_logger,
        )
        mock_logger.log_violation.assert_called_once()
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert raw_secret not in str(blocked)
        findings = blocked.get("findings", [])
        if findings:
            assert findings[0].get("pattern_hint") == "AKIA.*MPLE"


class TestLogAskDecisionRedacts:
    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_secret_type_redacts_matched_text(self, mock_logger_cls):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.constants import ViolationType
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger

        _log_ask_decision(
            violation_type=ViolationType.SECRET_DETECTED,
            decision=AskDecision.BLOCK,
            matched_text="AKIAIOSFODNN7EXAMPLE",
        )
        mock_logger.log_violation.assert_called_once()
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert "AKIAIOSFODNN7EXAMPLE" not in str(blocked)
        assert blocked.get("pattern_hint") == "AKIA.*MPLE"
        assert "matched_text" not in blocked

    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_pii_type_redacts_matched_text(self, mock_logger_cls):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.constants import ViolationType
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger

        _log_ask_decision(
            violation_type=ViolationType.PII_DETECTED,
            decision=AskDecision.BLOCK,
            matched_text="4111111111111111",
        )
        mock_logger.log_violation.assert_called_once()
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert "4111111111111111" not in str(blocked)
        assert blocked.get("pattern_hint") == "4111.*1111"
        assert "matched_text" not in blocked

    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_non_secret_type_keeps_matched_text(self, mock_logger_cls):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.constants import ViolationType
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger

        _log_ask_decision(
            violation_type=ViolationType.TOOL_PERMISSION,
            decision=AskDecision.BLOCK,
            matched_text="rm -rf /",
        )
        mock_logger.log_violation.assert_called_once()
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert blocked["matched_text"] == "rm -rf /"


class TestBuildViolationBlockedRedacts:
    def test_secret_with_file_omits_matched_text(self):
        from ai_guardian.scanners.post_scan_filters import build_violation_blocked
        from ai_guardian.scanners.scan_result import ScanResult

        result = ScanResult(
            detected=True,
            violation_type="secret_detected",
            matched_text="AKIAIOSFODNN7EXAMPLE",
            file_path="/code/main.py",
            line_number=10,
        )
        blocked = build_violation_blocked(result)
        assert "matched_text" not in blocked
        assert "pattern_hint" not in blocked
        assert blocked["file_path"] == "/code/main.py"

    def test_secret_without_file_adds_hint(self):
        from ai_guardian.scanners.post_scan_filters import build_violation_blocked
        from ai_guardian.scanners.scan_result import ScanResult

        result = ScanResult(
            detected=True,
            violation_type="secret_detected",
            matched_text="AKIAIOSFODNN7EXAMPLE",
        )
        blocked = build_violation_blocked(result)
        assert "matched_text" not in blocked
        assert blocked["pattern_hint"] == "AKIA.*MPLE"

    def test_pii_with_file_omits_matched_text(self):
        from ai_guardian.scanners.post_scan_filters import build_violation_blocked
        from ai_guardian.scanners.scan_result import ScanResult

        result = ScanResult(
            detected=True,
            violation_type="pii_detected",
            matched_text="4111111111111111",
            file_path="/code/data.py",
            line_number=5,
        )
        blocked = build_violation_blocked(result)
        assert "matched_text" not in blocked

    def test_non_secret_keeps_matched_text(self):
        from ai_guardian.scanners.post_scan_filters import build_violation_blocked
        from ai_guardian.scanners.scan_result import ScanResult

        result = ScanResult(
            detected=True,
            violation_type="prompt_injection",
            matched_text="ignore previous instructions",
        )
        blocked = build_violation_blocked(result)
        assert blocked["matched_text"] == "ignore previous instructions"
