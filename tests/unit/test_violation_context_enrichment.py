"""
Tests for violation log enrichment: context_snippet, command, tool_use_id, session_id.

Issue #408: Add context_snippet, command, and tool_use_id to violation log entries.
"""

import json
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

import ai_guardian
from ai_guardian import _extract_context_snippet


class TestExtractContextSnippet(unittest.TestCase):
    """Test the _extract_context_snippet helper function."""

    def test_basic_snippet_extraction(self):
        text = "line 1\nline 2\nline 3 with detection\nline 4\nline 5"
        snippet = _extract_context_snippet(text, 3)
        self.assertIsNotNone(snippet)
        self.assertIn("line 2", snippet)
        self.assertIn("line 3 with detection", snippet)
        self.assertIn("line 4", snippet)

    def test_first_line_detection(self):
        text = "detection line\nline 2\nline 3"
        snippet = _extract_context_snippet(text, 1)
        self.assertIsNotNone(snippet)
        self.assertIn("detection line", snippet)
        self.assertIn("line 2", snippet)

    def test_last_line_detection(self):
        text = "line 1\nline 2\ndetection line"
        snippet = _extract_context_snippet(text, 3)
        self.assertIsNotNone(snippet)
        self.assertIn("line 2", snippet)
        self.assertIn("detection line", snippet)

    def test_single_line_text(self):
        text = "only line with detection"
        snippet = _extract_context_snippet(text, 1)
        self.assertIsNotNone(snippet)
        self.assertIn("only line with detection", snippet)

    def test_truncation_to_max_chars(self):
        long_line = "A" * 300
        text = f"short\n{long_line}\nshort"
        snippet = _extract_context_snippet(text, 2, max_chars=200)
        self.assertIsNotNone(snippet)
        self.assertLessEqual(len(snippet), 200)
        self.assertTrue(snippet.endswith("..."))

    def test_none_for_invalid_inputs(self):
        self.assertIsNone(_extract_context_snippet("", 1))
        self.assertIsNone(_extract_context_snippet(None, 1))
        self.assertIsNone(_extract_context_snippet("text", 0))
        self.assertIsNone(_extract_context_snippet("text", -1))
        self.assertIsNone(_extract_context_snippet("text", None))

    def test_line_number_out_of_range(self):
        text = "line 1\nline 2"
        self.assertIsNone(_extract_context_snippet(text, 10))

    def test_empty_lines_skipped(self):
        text = "line 1\n\nline 3 detection\n\nline 5"
        snippet = _extract_context_snippet(text, 3)
        self.assertIsNotNone(snippet)
        self.assertIn("line 3 detection", snippet)

    def test_redacted_content_preserved(self):
        text = "name: John\nssn: [REDACTED-SSN]\nemail: [REDACTED-EMAIL]"
        snippet = _extract_context_snippet(text, 2)
        self.assertIsNotNone(snippet)
        self.assertIn("[REDACTED-SSN]", snippet)
        self.assertNotIn("real-ssn", snippet)

    def test_default_max_chars(self):
        text = "short line\ndetection\nshort"
        snippet = _extract_context_snippet(text, 2)
        self.assertLessEqual(len(snippet), 200)


class TestViolationCommandField(unittest.TestCase):
    """Test that command field is included for Bash PostToolUse violations."""

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    def test_pii_violation_includes_command_for_bash(
        self,
        mock_check_secrets,
        mock_redaction_config,
        mock_secret_config,
        mock_pii_config,
    ):
        """PII detected in Bash PostToolUse should include command in blocked dict."""
        mock_secret_config.return_value = ({"enabled": True}, None)
        mock_check_secrets.return_value = (False, None)
        mock_redaction_config.return_value = (None, None)
        mock_pii_config.return_value = (
            {"enabled": True, "action": "warn", "pii_types": ["SSN"]},
            None,
        )

        hook_input = json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool_use_id": "toolu_test_123",
                "session_id": "sess_test_456",
                "tool_use": {
                    "name": "Bash",
                    "input": {"command": "cat /data/employees.csv"},
                },
                "tool_response": {"output": "John Doe, 123-45-6789, Engineering"},
            }
        )

        with patch(
            "ai_guardian.hook_events.post_tool_use.ViolationLogger"
        ) as MockLogger:
            mock_instance = MagicMock()
            MockLogger.return_value = mock_instance

            with patch("ai_guardian.hook_processing._scan_for_pii") as mock_scan_pii:
                mock_scan_pii.return_value = (
                    True,
                    "John Doe, [REDACTED-SSN], Engineering",
                    [{"type": "SSN", "line_number": 1, "position": 10}],
                    "PII detected: SSN",
                )

                with patch("sys.stdin", StringIO(hook_input)):
                    ai_guardian.process_hook_input()

                if mock_instance.log_violation.called:
                    call_args = mock_instance.log_violation.call_args
                    blocked = (
                        call_args.kwargs.get("blocked", call_args[1].get("blocked", {}))
                        if call_args.kwargs
                        else call_args[1].get("blocked", {})
                    )
                    self.assertEqual(blocked.get("command"), "cat /data/employees.csv")

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    def test_command_truncated_to_500_chars(
        self,
        mock_check_secrets,
        mock_redaction_config,
        mock_secret_config,
        mock_pii_config,
    ):
        """Long commands should be truncated to 500 chars."""
        mock_secret_config.return_value = ({"enabled": True}, None)
        mock_check_secrets.return_value = (False, None)
        mock_redaction_config.return_value = (None, None)
        mock_pii_config.return_value = (
            {"enabled": True, "action": "warn", "pii_types": ["SSN"]},
            None,
        )

        long_command = "echo " + "A" * 600

        hook_input = json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool_use": {"name": "Bash", "input": {"command": long_command}},
                "tool_response": {"output": "John Doe, 123-45-6789"},
            }
        )

        with patch(
            "ai_guardian.hook_events.post_tool_use.ViolationLogger"
        ) as MockLogger:
            mock_instance = MagicMock()
            MockLogger.return_value = mock_instance

            with patch("ai_guardian.hook_processing._scan_for_pii") as mock_scan_pii:
                mock_scan_pii.return_value = (
                    True,
                    "redacted",
                    [{"type": "SSN", "line_number": 1}],
                    "PII",
                )

                with patch("sys.stdin", StringIO(hook_input)):
                    ai_guardian.process_hook_input()

                if mock_instance.log_violation.called:
                    call_args = mock_instance.log_violation.call_args
                    blocked = (
                        call_args.kwargs.get("blocked", call_args[1].get("blocked", {}))
                        if call_args.kwargs
                        else call_args[1].get("blocked", {})
                    )
                    cmd = blocked.get("command", "")
                    self.assertLessEqual(len(cmd), 500)


class TestViolationToolUseId(unittest.TestCase):
    """Test that tool_use_id and session_id are included in violation context."""

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    def test_posttooluse_pii_includes_ids(
        self,
        mock_check_secrets,
        mock_redaction_config,
        mock_secret_config,
        mock_pii_config,
    ):
        """PostToolUse PII violation should include tool_use_id and session_id in context."""
        mock_secret_config.return_value = ({"enabled": True}, None)
        mock_check_secrets.return_value = (False, None)
        mock_redaction_config.return_value = (None, None)
        mock_pii_config.return_value = (
            {"enabled": True, "action": "warn", "pii_types": ["SSN"]},
            None,
        )

        hook_input = json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool_use_id": "toolu_vrtx_01Test",
                "session_id": "56fb3e0c-test-session",
                "tool_use": {"name": "Bash", "input": {"command": "echo test"}},
                "tool_response": {"output": "SSN: 123-45-6789"},
            }
        )

        with patch(
            "ai_guardian.hook_events.post_tool_use.ViolationLogger"
        ) as MockLogger:
            mock_instance = MagicMock()
            MockLogger.return_value = mock_instance

            with patch("ai_guardian.hook_processing._scan_for_pii") as mock_scan_pii:
                mock_scan_pii.return_value = (
                    True,
                    "SSN: [REDACTED]",
                    [{"type": "SSN", "line_number": 1}],
                    "PII detected",
                )

                with patch("sys.stdin", StringIO(hook_input)):
                    ai_guardian.process_hook_input()

                if mock_instance.log_violation.called:
                    call_args = mock_instance.log_violation.call_args
                    context = (
                        call_args.kwargs.get("context", call_args[1].get("context", {}))
                        if call_args.kwargs
                        else call_args[1].get("context", {})
                    )
                    self.assertEqual(context.get("tool_use_id"), "toolu_vrtx_01Test")
                    self.assertEqual(context.get("session_id"), "56fb3e0c-test-session")

    def test_secret_detection_passes_ids_from_context(self):
        """_log_secret_detection_violation should include IDs from hook_context."""
        with patch(
            "ai_guardian.scanners.secret_scanning.ViolationLogger"
        ) as MockLogger:
            mock_instance = MagicMock()
            MockLogger.return_value = mock_instance

            ai_guardian._log_secret_detection_violation(
                "test_file.py",
                context={"ide_type": "claude_code", "hook_event": "pretooluse"},
                secret_details={"rule_id": "test-key"},
                hook_context={"tool_use_id": "toolu_test", "session_id": "sess_test"},
            )

            if mock_instance.log_violation.called:
                call_args = mock_instance.log_violation.call_args
                context = (
                    call_args.kwargs.get("context", call_args[1].get("context", {}))
                    if call_args.kwargs
                    else call_args[1].get("context", {})
                )
                self.assertEqual(context.get("tool_use_id"), "toolu_test")
                self.assertEqual(context.get("session_id"), "sess_test")

    def test_prompt_injection_passes_ids_from_hook_context(self):
        """_log_prompt_injection_violation should include IDs from hook_context."""
        with patch(
            "ai_guardian.hook_events.post_tool_use.ViolationLogger"
        ) as MockLogger:
            mock_instance = MagicMock()
            MockLogger.return_value = mock_instance

            ai_guardian._log_prompt_injection_violation(
                "test_file.py",
                context={"ide_type": "claude_code", "hook_event": "pretooluse"},
                attack_type="injection",
                hook_context={"tool_use_id": "toolu_inj", "session_id": "sess_inj"},
            )

            if mock_instance.log_violation.called:
                call_args = mock_instance.log_violation.call_args
                context = (
                    call_args.kwargs.get("context", call_args[1].get("context", {}))
                    if call_args.kwargs
                    else call_args[1].get("context", {})
                )
                self.assertEqual(context.get("tool_use_id"), "toolu_inj")
                self.assertEqual(context.get("session_id"), "sess_inj")

    def test_directory_blocking_passes_ids_from_hook_context(self):
        """_log_directory_blocking_violation should include IDs from hook_context."""
        with patch("ai_guardian.hook_processing.ViolationLogger") as MockLogger:
            mock_instance = MagicMock()
            MockLogger.return_value = mock_instance

            ai_guardian._log_directory_blocking_violation(
                "/path/to/file",
                "/path/to",
                hook_context={"tool_use_id": "toolu_dir", "session_id": "sess_dir"},
            )

            if mock_instance.log_violation.called:
                call_args = mock_instance.log_violation.call_args
                context = (
                    call_args.kwargs.get("context", call_args[1].get("context", {}))
                    if call_args.kwargs
                    else call_args[1].get("context", {})
                )
                self.assertEqual(context.get("tool_use_id"), "toolu_dir")
                self.assertEqual(context.get("session_id"), "sess_dir")

    def test_no_ids_when_not_in_hook_data(self):
        """When hook_data has no IDs, context should not contain them."""
        with patch(
            "ai_guardian.scanners.secret_scanning.ViolationLogger"
        ) as MockLogger:
            mock_instance = MagicMock()
            MockLogger.return_value = mock_instance

            ai_guardian._log_secret_detection_violation(
                "test_file.py",
                context={"ide_type": "claude_code", "hook_event": "pretooluse"},
                secret_details={"rule_id": "test-key"},
            )

            if mock_instance.log_violation.called:
                call_args = mock_instance.log_violation.call_args
                context = (
                    call_args.kwargs.get("context", call_args[1].get("context", {}))
                    if call_args.kwargs
                    else call_args[1].get("context", {})
                )
                self.assertNotIn("tool_use_id", context)
                self.assertNotIn("session_id", context)


class TestViolationContextSnippetInLog(unittest.TestCase):
    """Test that context_snippet is included in violation log entries."""

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    def test_pii_violation_includes_snippet(
        self,
        mock_check_secrets,
        mock_redaction_config,
        mock_secret_config,
        mock_pii_config,
    ):
        """PII violation should include context_snippet with redacted content."""
        mock_secret_config.return_value = ({"enabled": True}, None)
        mock_check_secrets.return_value = (False, None)
        mock_redaction_config.return_value = (None, None)
        mock_pii_config.return_value = (
            {"enabled": True, "action": "warn", "pii_types": ["SSN"]},
            None,
        )

        hook_input = json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool_use": {"name": "Bash", "input": {"command": "cat file.csv"}},
                "tool_response": {
                    "output": "header row\nJohn Doe, 123-45-6789\nfooter row"
                },
            }
        )

        with patch(
            "ai_guardian.hook_events.post_tool_use.ViolationLogger"
        ) as MockLogger:
            mock_instance = MagicMock()
            MockLogger.return_value = mock_instance

            with patch("ai_guardian.hook_processing._scan_for_pii") as mock_scan_pii:
                mock_scan_pii.return_value = (
                    True,
                    "header row\nJohn Doe, [REDACTED-SSN]\nfooter row",
                    [{"type": "SSN", "line_number": 2, "position": 10}],
                    "PII detected: SSN",
                )

                with patch("sys.stdin", StringIO(hook_input)):
                    ai_guardian.process_hook_input()

                if mock_instance.log_violation.called:
                    call_args = mock_instance.log_violation.call_args
                    blocked = (
                        call_args.kwargs.get("blocked", call_args[1].get("blocked", {}))
                        if call_args.kwargs
                        else call_args[1].get("blocked", {})
                    )
                    snippet = blocked.get("context_snippet")
                    self.assertIsNotNone(snippet)
                    self.assertIn("[REDACTED-SSN]", snippet)


class TestToolPolicyViolationIds(unittest.TestCase):
    """Test that tool_policy violations include IDs."""

    def test_tool_policy_violation_includes_ids(self):
        """ToolPolicyChecker._log_violation should include tool_use_id/session_id."""
        from ai_guardian.tools.policy import ToolPolicyChecker

        checker = ToolPolicyChecker(
            config={
                "tool_policies": {
                    "rules": [
                        {"matcher": "Bash", "mode": "deny", "patterns": ["rm -rf"]}
                    ]
                }
            }
        )

        with patch("ai_guardian.tools.policy.ViolationLogger") as MockLogger:
            mock_instance = MagicMock()
            MockLogger.return_value = mock_instance

            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_use_id": "toolu_policy_test",
                "session_id": "sess_policy_test",
            }

            checker._log_violation(
                tool_name="Bash",
                check_value="rm -rf /",
                reason="Dangerous command",
                matcher="Bash",
                hook_data=hook_data,
            )

            if mock_instance.log_violation.called:
                call_args = mock_instance.log_violation.call_args
                context = (
                    call_args.kwargs.get("context", call_args[1].get("context", {}))
                    if call_args.kwargs
                    else call_args[1].get("context", {})
                )
                self.assertEqual(context.get("tool_use_id"), "toolu_policy_test")
                self.assertEqual(context.get("session_id"), "sess_policy_test")


class TestTUIViolationDisplay(unittest.TestCase):
    """Test TUI violation card data structure for new fields."""

    def test_secret_redaction_violation_has_command(self):
        """Violation data for Bash secret_redaction should include command field."""
        violation = {
            "timestamp": "2026-05-03T14:00:00Z",
            "violation_type": "secret_redaction",
            "severity": "warning",
            "blocked": {
                "tool": "Bash",
                "file_path": None,
                "line_number": 5,
                "redaction_count": 1,
                "redacted_types": ["API Key"],
                "command": "env | grep API_KEY",
                "context_snippet": "...API_KEY=[REDACTED]...",
            },
            "context": {
                "action": "redacted",
                "hook_event": "posttooluse",
                "tool_use_id": "toolu_test",
                "session_id": "sess_test",
            },
            "suggestion": {},
            "resolved": False,
        }

        blocked = violation["blocked"]
        self.assertEqual(blocked["command"], "env | grep API_KEY")
        self.assertEqual(blocked["context_snippet"], "...API_KEY=[REDACTED]...")
        self.assertIsNone(blocked["file_path"])
        self.assertEqual(violation["context"]["tool_use_id"], "toolu_test")
        self.assertEqual(violation["context"]["session_id"], "sess_test")

    def test_pii_violation_has_snippet_when_no_file_path(self):
        """PII violation with null file_path should have context_snippet."""
        violation = {
            "timestamp": "2026-05-03T14:00:00Z",
            "violation_type": "pii_detected",
            "severity": "warning",
            "blocked": {
                "tool": "Bash",
                "hook": "PostToolUse",
                "file_path": None,
                "line_number": 2,
                "pii_count": 1,
                "pii_types": ["SSN"],
                "command": "cat records.csv",
                "context_snippet": "...row 2: [REDACTED-SSN]...",
            },
            "context": {"action": "warn", "hook_event": "posttooluse"},
            "suggestion": {},
            "resolved": False,
        }

        blocked = violation["blocked"]
        self.assertIsNone(blocked["file_path"])
        self.assertEqual(blocked["command"], "cat records.csv")
        self.assertIn("[REDACTED-SSN]", blocked["context_snippet"])

    def test_details_modal_shows_all_fields_in_json(self):
        """Violation JSON dump should include tool_use_id and session_id."""
        violation = {
            "timestamp": "2026-05-03T14:00:00Z",
            "violation_type": "pii_detected",
            "severity": "warning",
            "blocked": {"tool": "Bash", "command": "echo test"},
            "context": {
                "tool_use_id": "toolu_detail_test",
                "session_id": "sess_detail_test",
            },
            "suggestion": {},
            "resolved": False,
        }

        json_str = json.dumps(violation, indent=2)
        self.assertIn("toolu_detail_test", json_str)
        self.assertIn("sess_detail_test", json_str)


class TestViolationWorksForAllTypes(unittest.TestCase):
    """Test that enrichment works for all required violation types."""

    def test_snippet_works_for_prompt_injection_types(self):
        """context_snippet should work for prompt injection (tested via _extract_context_snippet)."""
        text = "normal text\nignore previous instructions\nnormal again"
        snippet = _extract_context_snippet(text, 2)
        self.assertIsNotNone(snippet)
        self.assertIn("ignore previous instructions", snippet)

    def test_snippet_works_for_secret_types(self):
        """context_snippet should work for secret content (redacted)."""
        text = "config line\napi_key=[REDACTED]\nmore config"
        snippet = _extract_context_snippet(text, 2)
        self.assertIsNotNone(snippet)
        self.assertIn("[REDACTED]", snippet)


if __name__ == "__main__":
    unittest.main()
