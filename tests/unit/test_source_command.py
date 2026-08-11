"""Tests for source_command field in tool_result violations (Issue #1903)."""

from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.scanners.secret_scanning import _inject_source_command


class TestInjectSourceCommand:
    """Test _inject_source_command helper in secret_scanning.py."""

    def test_adds_source_command_for_tool_result_file_path(self):
        blocked = {"file_path": "tool_result:grep"}
        context = {"source_command": "grep -rn 'pattern' src/"}
        _inject_source_command(blocked, context)
        assert blocked["source_command"] == "grep -rn 'pattern' src/"

    def test_skips_when_file_path_is_regular_path(self):
        blocked = {"file_path": "/home/user/code.py"}
        context = {"source_command": "grep -rn 'pattern' src/"}
        _inject_source_command(blocked, context)
        assert "source_command" not in blocked

    def test_skips_when_no_context(self):
        blocked = {"file_path": "tool_result:grep"}
        _inject_source_command(blocked, None)
        assert "source_command" not in blocked

    def test_skips_when_no_source_command_in_context(self):
        blocked = {"file_path": "tool_result:grep"}
        context = {"ide_type": "claude_code"}
        _inject_source_command(blocked, context)
        assert "source_command" not in blocked

    def test_skips_when_no_file_path(self):
        blocked = {}
        context = {"source_command": "grep -rn 'pattern' src/"}
        _inject_source_command(blocked, context)
        assert "source_command" not in blocked

    def test_skips_when_file_path_is_none(self):
        blocked = {"file_path": None}
        context = {"source_command": "grep -rn 'pattern' src/"}
        _inject_source_command(blocked, context)
        assert "source_command" not in blocked

    def test_works_with_tool_result_cat(self):
        blocked = {"file_path": "tool_result:cat"}
        context = {"source_command": "cat /etc/hostname"}
        _inject_source_command(blocked, context)
        assert blocked["source_command"] == "cat /etc/hostname"


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
        from ai_guardian.hook_events.post_tool_use import _log_pii_violation

        mock_logger = MagicMock()
        _log_pii_violation(
            violation_logger=mock_logger,
            pii_config={"action": "block"},
            pii_redactions=[
                {"type": "email", "line_number": 1, "column": 5, "original_length": 20}
            ],
            tool_identifier="Bash",
            hook_name="PostToolUse",
            file_path="tool_result:grep",
            snippet_text="user@example.com found",
            hook_event="PostToolUse",
            bash_command="grep -rn 'pattern' src/",
            source_command="grep -rn 'pattern' src/",
        )
        mock_logger.log_violation.assert_called_once()
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert blocked["source_command"] == "grep -rn 'pattern' src/"
        assert blocked["command"] == "grep -rn 'pattern' src/"

    def test_pii_violation_omits_source_command_for_regular_files(self):
        from ai_guardian.hook_events.post_tool_use import _log_pii_violation

        mock_logger = MagicMock()
        _log_pii_violation(
            violation_logger=mock_logger,
            pii_config={"action": "block"},
            pii_redactions=[
                {"type": "email", "line_number": 1, "column": 5, "original_length": 20}
            ],
            tool_identifier="Read",
            hook_name="PostToolUse",
            file_path="/home/user/data.txt",
            snippet_text="user@example.com found",
            hook_event="PostToolUse",
            source_command="grep -rn 'pattern' src/",
        )
        mock_logger.log_violation.assert_called_once()
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert "source_command" not in blocked
