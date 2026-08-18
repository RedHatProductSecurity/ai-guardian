"""Tests for directory_blocking violation reason differentiation (issue #347).

Verifies that violations triggered by .ai-read-deny markers vs directory rules
log different reason strings and suggestions.
"""

import os
import tempfile
from unittest import mock

import pytest

from ai_guardian import _log_directory_blocking_violation


class TestLogDirectoryBlockingViolationReason:
    """Test that _log_directory_blocking_violation uses correct reason/suggestion."""

    @mock.patch("ai_guardian.violations.logger.ViolationLogger")
    @mock.patch("ai_guardian.hook_processing.HAS_VIOLATION_LOGGER", True)
    def test_default_reason_is_marker_found(self, mock_vl_class):
        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        _log_directory_blocking_violation("/some/file.txt", "/some")

        mock_logger.log_violation.assert_called_once()
        call_kwargs = mock_logger.log_violation.call_args
        blocked = call_kwargs.kwargs.get("blocked", call_kwargs[1].get("blocked"))
        assert blocked["reason"] == ".ai-read-deny marker found"

    @mock.patch("ai_guardian.violations.logger.ViolationLogger")
    @mock.patch("ai_guardian.hook_processing.HAS_VIOLATION_LOGGER", True)
    def test_default_suggestion_is_remove_marker(self, mock_vl_class):
        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        _log_directory_blocking_violation("/some/file.txt", "/some")

        call_kwargs = mock_logger.log_violation.call_args
        suggestion = call_kwargs.kwargs.get(
            "suggestion", call_kwargs[1].get("suggestion")
        )
        assert suggestion["action"] == "remove_deny_marker"
        assert ".ai-read-deny" in suggestion["file_path"]

    @mock.patch("ai_guardian.violations.logger.ViolationLogger")
    @mock.patch("ai_guardian.hook_processing.HAS_VIOLATION_LOGGER", True)
    def test_custom_reason_for_directory_rule(self, mock_vl_class):
        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        _log_directory_blocking_violation(
            "/some/file.txt", "/some", reason="denied by directory rule: ~/.secret/**"
        )

        call_kwargs = mock_logger.log_violation.call_args
        blocked = call_kwargs.kwargs.get("blocked", call_kwargs[1].get("blocked"))
        assert blocked["reason"] == "denied by directory rule: ~/.secret/**"

    @mock.patch("ai_guardian.violations.logger.ViolationLogger")
    @mock.patch("ai_guardian.hook_processing.HAS_VIOLATION_LOGGER", True)
    def test_custom_suggestion_for_directory_rule(self, mock_vl_class):
        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        rule_suggestion = {
            "action": "update_directory_rules",
            "config_file": "ai-guardian.json",
            "warning": "Directory rules deny access (matched pattern: ~/.secret/**)",
        }
        _log_directory_blocking_violation(
            "/some/file.txt",
            "/some",
            reason="denied by directory rule: ~/.secret/**",
            suggestion=rule_suggestion,
        )

        call_kwargs = mock_logger.log_violation.call_args
        suggestion = call_kwargs.kwargs.get(
            "suggestion", call_kwargs[1].get("suggestion")
        )
        assert suggestion["action"] == "update_directory_rules"
        assert "ai-guardian.json" in suggestion["config_file"]

    @mock.patch("ai_guardian.violations.logger.ViolationLogger")
    @mock.patch("ai_guardian.hook_processing.HAS_VIOLATION_LOGGER", True)
    def test_explicit_marker_reason_overrides_default(self, mock_vl_class):
        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        _log_directory_blocking_violation(
            "/some/file.txt", "/some", reason=".ai-read-deny marker found"
        )

        call_kwargs = mock_logger.log_violation.call_args
        blocked = call_kwargs.kwargs.get("blocked", call_kwargs[1].get("blocked"))
        assert blocked["reason"] == ".ai-read-deny marker found"


class TestCheckDirectoryDeniedViolationReason:
    """Integration tests: check_directory_denied passes correct reason to violation logger."""

    @pytest.mark.parametrize(
        "action_mode",
        [
            pytest.param("block", id="block-mode"),
            pytest.param("warn", id="warn-mode"),
        ],
    )
    @mock.patch("ai_guardian.violations.logger.ViolationLogger")
    @mock.patch("ai_guardian.hook_processing.HAS_VIOLATION_LOGGER", True)
    def test_marker_violation_logs_marker_reason(self, mock_vl_class, action_mode):
        """Violation triggered by .ai-read-deny marker should log marker reason."""
        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        from ai_guardian import check_directory_denied

        with tempfile.TemporaryDirectory() as tmpdir:
            denied_dir = os.path.join(tmpdir, "denied")
            os.makedirs(denied_dir)
            marker = os.path.join(denied_dir, ".ai-read-deny")
            with open(marker, "w") as f:
                f.write("")
            test_file = os.path.join(denied_dir, "secret.txt")
            with open(test_file, "w") as f:
                f.write("secret")

            config = {"directory_rules": {"action": action_mode, "rules": []}}
            check_directory_denied(test_file, config)

        mock_logger.log_violation.assert_called_once()
        call_kwargs = mock_logger.log_violation.call_args
        blocked = call_kwargs.kwargs.get("blocked", call_kwargs[1].get("blocked"))
        assert blocked["reason"] == ".ai-read-deny marker found"
        suggestion = call_kwargs.kwargs.get(
            "suggestion", call_kwargs[1].get("suggestion")
        )
        assert suggestion["action"] == "remove_deny_marker"

    @pytest.mark.parametrize(
        "action_mode",
        [
            pytest.param("block", id="block-mode"),
            pytest.param("warn", id="warn-mode"),
            pytest.param("log-only", id="log-only-mode"),
        ],
    )
    @mock.patch("ai_guardian.violations.logger.ViolationLogger")
    @mock.patch("ai_guardian.hook_processing.HAS_VIOLATION_LOGGER", True)
    def test_directory_rule_violation_logs_rule_reason(
        self, mock_vl_class, action_mode
    ):
        """Violations from directory rules should log rule reason with pattern."""
        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        from ai_guardian import check_directory_denied

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "secret.txt")
            with open(test_file, "w") as f:
                f.write("secret")

            config = {
                "directory_rules": {
                    "action": action_mode,
                    "rules": [{"mode": "deny", "paths": [f"{tmpdir}/**"]}],
                }
            }
            check_directory_denied(test_file, config)

        mock_logger.log_violation.assert_called_once()
        call_kwargs = mock_logger.log_violation.call_args
        blocked = call_kwargs.kwargs.get("blocked", call_kwargs[1].get("blocked"))
        assert "denied by directory rule:" in blocked["reason"]
        suggestion = call_kwargs.kwargs.get(
            "suggestion", call_kwargs[1].get("suggestion")
        )
        assert suggestion["action"] == "update_directory_rules"
