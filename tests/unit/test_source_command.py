"""Tests for source_command field in tool_result violations (Issue #1903)."""

from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.scanners.secret_scanning import _build_secret_extras


class TestBuildSecretExtrasSourceCommand:
    """Test _build_secret_extras source_command injection."""

    def test_adds_source_command_for_tool_result_file_path(self):
        details = {"rule_id": "test"}
        context = {"source_command": "grep -rn 'pattern' src/"}
        extras = _build_secret_extras(details, context, file_path="tool_result:grep")
        assert extras["source_command"] == "grep -rn 'pattern' src/"

    def test_skips_source_command_for_regular_file_path(self):
        details = {"rule_id": "test"}
        context = {"source_command": "grep -rn 'pattern' src/"}
        extras = _build_secret_extras(details, context, file_path="/home/user/code.py")
        assert "source_command" not in extras

    def test_skips_when_no_context(self):
        details = {"rule_id": "test"}
        extras = _build_secret_extras(details, None)
        assert "source_command" not in extras

    def test_skips_when_no_source_command_in_context(self):
        details = {"rule_id": "test"}
        context = {"ide_type": "claude_code"}
        extras = _build_secret_extras(details, context)
        assert "source_command" not in extras


class TestSanitizeSourceCommand:
    """Test _sanitize_source_command in post_tool_use.py."""

    def test_safe_command_passes_through(self):
        from ai_guardian.hook_events.post_tool_use import _sanitize_source_command

        result = _sanitize_source_command("grep -rn 'pattern' src/")
        assert result == "grep -rn 'pattern' src/"

    def test_truncates_long_commands(self):
        from ai_guardian.hook_events.post_tool_use import (
            _MAX_SOURCE_COMMAND_LEN,
            _sanitize_source_command,
        )

        long_cmd = "x" * 1000
        result = _sanitize_source_command(long_cmd)
        assert len(result) == _MAX_SOURCE_COMMAND_LEN

    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    def test_command_with_secret_is_redacted(self, mock_check):
        from ai_guardian.hook_events.post_tool_use import _sanitize_source_command

        mock_check.return_value = (True, "Secret detected")
        result = _sanitize_source_command(
            'curl -H "Authorization: Bearer sk-secret123" https://api.example.com'
        )
        assert result == "[redacted — command contains secrets]"

    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    def test_safe_command_not_redacted(self, mock_check):
        from ai_guardian.hook_events.post_tool_use import _sanitize_source_command

        mock_check.return_value = (False, None)
        result = _sanitize_source_command("ls -la /tmp")
        assert result == "ls -la /tmp"

    @patch(
        "ai_guardian.scanners.secret_scanning.check_secrets",
        side_effect=Exception("scanner unavailable"),
    )
    def test_scanner_error_falls_through(self, mock_check):
        from ai_guardian.hook_events.post_tool_use import _sanitize_source_command

        result = _sanitize_source_command("some command")
        assert result == "some command"


class TestSourceCommandInViolationDicts:
    """Test that source_command appears in violation dicts for tool_result violations."""

    def test_pii_violation_includes_source_command(self):
        from ai_guardian.scanners.scan_result import ScanResult, generate_violation_id
        from ai_guardian.violations.log_violation import ScanContext, log_violation

        mock_logger = MagicMock()
        result = ScanResult(
            detected=True,
            violation_type="pii_detected",
            id=generate_violation_id(),
            file_path="tool_result:grep",
            line_number=1,
        )
        log_violation(
            result,
            ScanContext(),
            violation_logger=mock_logger,
            blocked_overrides={
                "source_command": "grep -rn 'pattern' src/",
                "command": "grep -rn 'pattern' src/",
            },
        )
        mock_logger.log_violation.assert_called_once()
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert blocked["source_command"] == "grep -rn 'pattern' src/"
        assert blocked["command"] == "grep -rn 'pattern' src/"

    def test_pii_violation_omits_source_command_for_regular_files(self):
        from ai_guardian.scanners.scan_result import ScanResult, generate_violation_id
        from ai_guardian.violations.log_violation import ScanContext, log_violation

        mock_logger = MagicMock()
        result = ScanResult(
            detected=True,
            violation_type="pii_detected",
            id=generate_violation_id(),
            file_path="/home/user/data.txt",
            line_number=1,
        )
        log_violation(
            result,
            ScanContext(),
            violation_logger=mock_logger,
        )
        mock_logger.log_violation.assert_called_once()
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert "source_command" not in blocked
