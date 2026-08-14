"""
Unit tests for on_scan_error global configuration (Issue #461).

Tests that the on_scan_error setting controls fail-open vs fail-closed
behavior when scanners encounter errors.
"""

import json
from io import StringIO
from unittest import TestCase
from unittest.mock import Mock, patch

import ai_guardian


def _is_blocked(result):
    """Check if a process_hook_data result represents a blocked operation."""
    if result.get("_blocked"):
        return True
    output = result.get("output")
    if output:
        try:
            data = json.loads(output)
            if data.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
                return True
            if data.get("decision") == "block":
                return True
            if data.get("decision") == "deny":
                return True
        except (json.JSONDecodeError, TypeError):
            pass
    return False


# Common mock configuration to disable all scanners except the one under test
DISABLE_ALL_SCANNERS = {
    "ai_guardian.config.loaders._load_secret_scanning_config": (
        {"enabled": False},
        None,
    ),
    "ai_guardian.hook_processing._load_pattern_server_config": None,
    "ai_guardian.config.loaders._load_pii_config": ({"enabled": False}, None),
    "ai_guardian.config.loaders._load_prompt_injection_config": (
        {"enabled": False},
        None,
    ),
    "ai_guardian.config.loaders._load_config_scanner_config": (
        {"enabled": False},
        None,
    ),
    "ai_guardian.hook_processing._load_permissions_config": ({"enabled": False}, None),
    "ai_guardian.config.loaders._load_transcript_scanning_config": (
        {"enabled": False},
        None,
    ),
}


class TestGetOnScanErrorAction(TestCase):
    """Tests for the _get_on_scan_error_action() helper."""

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_default_when_no_config(self, mock_load):
        mock_load.return_value = (None, None)
        self.assertEqual(ai_guardian._get_on_scan_error_action(), "allow")

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_default_when_key_missing(self, mock_load):
        mock_load.return_value = ({"secret_scanning": {"enabled": True}}, None)
        self.assertEqual(ai_guardian._get_on_scan_error_action(), "allow")

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_allow_value(self, mock_load):
        mock_load.return_value = ({"on_scan_error": "allow"}, None)
        self.assertEqual(ai_guardian._get_on_scan_error_action(), "allow")

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_block_value(self, mock_load):
        mock_load.return_value = ({"on_scan_error": "block"}, None)
        self.assertEqual(ai_guardian._get_on_scan_error_action(), "block")

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_invalid_value_defaults_to_allow(self, mock_load):
        mock_load.return_value = ({"on_scan_error": "invalid"}, None)
        self.assertEqual(ai_guardian._get_on_scan_error_action(), "allow")

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_config_load_error_defaults_to_allow(self, mock_load):
        mock_load.return_value = (None, "Config error")
        self.assertEqual(ai_guardian._get_on_scan_error_action(), "allow")


class TestOnScanErrorToolPolicy(TestCase):
    """Tests for on_scan_error behavior in tool policy check."""

    @patch("ai_guardian.hook_processing.extract_file_content_from_tool")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._get_on_scan_error_action")
    @patch("ai_guardian.hook_processing._load_permissions_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_tool_policy_error_allow(
        self,
        mock_pattern,
        mock_secret,
        mock_perms,
        mock_on_error,
        mock_pii,
        mock_extract,
    ):
        """Tool policy error with on_scan_error=allow should fail-open."""
        mock_on_error.return_value = "allow"
        mock_pattern.return_value = None
        mock_secret.return_value = ({"enabled": False}, None)
        mock_perms.return_value = ({"enabled": True, "rules": []}, None)
        mock_pii.return_value = ({"enabled": False}, None)
        mock_extract.return_value = (
            "file content",
            "test.txt",
            "/tmp/test.txt",
            False,
            None,
            None,
        )

        with patch(
            "ai_guardian.hook_processing.ToolPolicyChecker",
            side_effect=Exception("Policy check crashed"),
        ):
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use": {
                    "name": "Read",
                    "parameters": {"file_path": "/tmp/test.txt"},
                },
            }
            result = ai_guardian.process_hook_data(hook_data)
            self.assertFalse(
                _is_blocked(result), "Should fail-open when on_scan_error=allow"
            )

    @patch("ai_guardian.hook_processing.extract_file_content_from_tool")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._get_on_scan_error_action")
    @patch("ai_guardian.hook_processing._load_permissions_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_tool_policy_error_block(
        self,
        mock_pattern,
        mock_secret,
        mock_perms,
        mock_on_error,
        mock_pii,
        mock_extract,
    ):
        """Tool policy error with on_scan_error=block should fail-closed."""
        mock_on_error.return_value = "block"
        mock_pattern.return_value = None
        mock_secret.return_value = ({"enabled": False}, None)
        mock_perms.return_value = ({"enabled": True, "rules": []}, None)
        mock_pii.return_value = ({"enabled": False}, None)
        mock_extract.return_value = (
            "file content",
            "test.txt",
            "/tmp/test.txt",
            False,
            None,
            None,
        )

        with patch(
            "ai_guardian.hook_processing.ToolPolicyChecker",
            side_effect=Exception("Policy check crashed"),
        ):
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use": {
                    "name": "Read",
                    "parameters": {"file_path": "/tmp/test.txt"},
                },
            }
            result = ai_guardian.process_hook_data(hook_data)
            self.assertTrue(
                _is_blocked(result), "Should fail-closed when on_scan_error=block"
            )


class TestOnScanErrorPromptInjection(TestCase):
    """Tests for on_scan_error behavior in prompt injection check."""

    @patch("ai_guardian.hook_processing.extract_file_content_from_tool")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._get_on_scan_error_action")
    @patch("ai_guardian.config.loaders._load_prompt_injection_config")
    @patch("ai_guardian.hook_processing._load_permissions_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_prompt_injection_error_allow(
        self,
        mock_pattern,
        mock_secret,
        mock_perms,
        mock_injection,
        mock_on_error,
        mock_pii,
        mock_extract,
    ):
        """Prompt injection error with on_scan_error=allow should fail-open."""
        mock_on_error.return_value = "allow"
        mock_pattern.return_value = None
        mock_secret.return_value = ({"enabled": False}, None)
        mock_perms.return_value = ({"enabled": False}, None)
        mock_injection.return_value = ({"enabled": True, "action": "block"}, None)
        mock_pii.return_value = ({"enabled": False}, None)
        mock_extract.return_value = (
            "file content",
            "test.txt",
            "/tmp/test.txt",
            False,
            None,
            None,
        )

        with (
            patch("ai_guardian.hook_events.scanners.HAS_PROMPT_INJECTION", True),
            patch(
                "ai_guardian.hook_events.scanners.get_cached_detector",
                side_effect=Exception("Injection check crashed"),
            ),
        ):
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use": {
                    "name": "Read",
                    "parameters": {"file_path": "/tmp/test.txt"},
                },
            }
            result = ai_guardian.process_hook_data(hook_data)
            self.assertFalse(
                _is_blocked(result), "Should fail-open when on_scan_error=allow"
            )

    @patch("ai_guardian.hook_processing.extract_file_content_from_tool")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._get_on_scan_error_action")
    @patch("ai_guardian.config.loaders._load_prompt_injection_config")
    @patch("ai_guardian.hook_processing._load_permissions_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_prompt_injection_error_block(
        self,
        mock_pattern,
        mock_secret,
        mock_perms,
        mock_injection,
        mock_on_error,
        mock_pii,
        mock_extract,
    ):
        """Prompt injection error with on_scan_error=block should fail-closed."""
        mock_on_error.return_value = "block"
        mock_pattern.return_value = None
        mock_secret.return_value = ({"enabled": False}, None)
        mock_perms.return_value = ({"enabled": False}, None)
        mock_injection.return_value = ({"enabled": True, "action": "block"}, None)
        mock_pii.return_value = ({"enabled": False}, None)
        mock_extract.return_value = (
            "file content",
            "test.txt",
            "/tmp/test.txt",
            False,
            None,
            None,
        )

        with (
            patch("ai_guardian.hook_events.scanners.HAS_PROMPT_INJECTION", True),
            patch(
                "ai_guardian.hook_events.scanners.get_cached_detector",
                side_effect=Exception("Injection check crashed"),
            ),
        ):
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use": {
                    "name": "Read",
                    "parameters": {"file_path": "/tmp/test.txt"},
                },
            }
            result = ai_guardian.process_hook_data(hook_data)
            self.assertTrue(
                _is_blocked(result), "Should fail-closed when on_scan_error=block"
            )


class TestOnScanErrorSecretScanning(TestCase):
    """Tests for on_scan_error behavior in secret scanning."""

    @patch("ai_guardian.scanners.secret_scanning._get_on_scan_error_action")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    def test_scanner_unavailable_allow(self, mock_pattern, mock_secret, mock_on_error):
        """Scanner unavailable with on_scan_error=allow should fail-open."""
        mock_on_error.return_value = "allow"
        mock_pattern.return_value = None
        mock_secret.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)

        with (
            patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True),
            patch(
                "ai_guardian.scanners.secret_scanning.select_engine",
                side_effect=RuntimeError("No scanner"),
            ),
        ):
            has_secrets, error_msg = ai_guardian.check_secrets(
                "test content", "test.txt"
            )
            self.assertFalse(has_secrets, "Should fail-open when on_scan_error=allow")

    @patch("ai_guardian.scanners.secret_scanning._get_on_scan_error_action")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    def test_scanner_unavailable_block(self, mock_pattern, mock_secret, mock_on_error):
        """Scanner unavailable with on_scan_error=block should fail-closed."""
        mock_on_error.return_value = "block"
        mock_pattern.return_value = None
        mock_secret.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)

        with (
            patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True),
            patch(
                "ai_guardian.scanners.secret_scanning.select_engine",
                side_effect=RuntimeError("No scanner"),
            ),
        ):
            has_secrets, error_msg = ai_guardian.check_secrets(
                "test content", "test.txt"
            )
            self.assertTrue(has_secrets, "Should fail-closed when on_scan_error=block")
            self.assertIn("BLOCKED", error_msg)


class TestOnScanErrorConfigScanning(TestCase):
    """Tests for on_scan_error behavior in config file scanning."""

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._get_on_scan_error_action")
    @patch("ai_guardian.config.loaders._load_config_scanner_config")
    @patch("ai_guardian.hook_processing._load_permissions_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.hook_processing.extract_file_content_from_tool")
    def test_config_scan_error_allow(
        self,
        mock_extract,
        mock_pattern,
        mock_secret,
        mock_perms,
        mock_config_scanner,
        mock_on_error,
        mock_pii,
    ):
        """Config scanning error with on_scan_error=allow should fail-open."""
        mock_on_error.return_value = "allow"
        mock_pattern.return_value = None
        mock_secret.return_value = ({"enabled": False}, None)
        mock_perms.return_value = ({"enabled": False}, None)
        mock_config_scanner.side_effect = Exception("Config scanner crashed")
        mock_pii.return_value = ({"enabled": False}, None)
        mock_extract.return_value = (
            "file content",
            "CLAUDE.md",
            "/tmp/CLAUDE.md",
            False,
            None,
            None,
        )

        with patch("ai_guardian.hook_events.scanners.HAS_CONFIG_SCANNER", True):
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use": {
                    "name": "Read",
                    "parameters": {"file_path": "/tmp/CLAUDE.md"},
                },
            }
            result = ai_guardian.process_hook_data(hook_data)
            self.assertFalse(
                _is_blocked(result), "Should fail-open when on_scan_error=allow"
            )

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._get_on_scan_error_action")
    @patch("ai_guardian.config.loaders._load_config_scanner_config")
    @patch("ai_guardian.hook_processing._load_permissions_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.hook_processing.extract_file_content_from_tool")
    def test_config_scan_error_block(
        self,
        mock_extract,
        mock_pattern,
        mock_secret,
        mock_perms,
        mock_config_scanner,
        mock_on_error,
        mock_pii,
    ):
        """Config scanning error with on_scan_error=block should fail-closed."""
        mock_on_error.return_value = "block"
        mock_pattern.return_value = None
        mock_secret.return_value = ({"enabled": False}, None)
        mock_perms.return_value = ({"enabled": False}, None)
        mock_config_scanner.side_effect = Exception("Config scanner crashed")
        mock_pii.return_value = ({"enabled": False}, None)
        mock_extract.return_value = (
            "file content",
            "CLAUDE.md",
            "/tmp/CLAUDE.md",
            False,
            None,
            None,
        )

        with patch("ai_guardian.hook_events.scanners.HAS_CONFIG_SCANNER", True):
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use": {
                    "name": "Read",
                    "parameters": {"file_path": "/tmp/CLAUDE.md"},
                },
            }
            result = ai_guardian.process_hook_data(hook_data)
            self.assertTrue(
                _is_blocked(result), "Should fail-closed when on_scan_error=block"
            )


class TestOnScanErrorTranscriptScanning(TestCase):
    """Tests for on_scan_error behavior in transcript scanning."""

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._get_on_scan_error_action")
    @patch("ai_guardian.config.loaders._load_transcript_scanning_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_transcript_scan_error_allow(
        self, mock_pattern, mock_secret, mock_transcript, mock_on_error, mock_pii
    ):
        """Transcript scanning error with on_scan_error=allow should fail-open."""
        mock_on_error.return_value = "allow"
        mock_pattern.return_value = None
        mock_secret.return_value = ({"enabled": False}, None)
        mock_transcript.return_value = ({"enabled": True}, None)
        mock_pii.return_value = ({"enabled": False}, None)

        with (
            patch(
                "ai_guardian.hook_processing._get_transcript_path",
                return_value="/tmp/transcript.jsonl",
            ),
            patch(
                "ai_guardian.scanners.transcript.scan_transcript_incremental",
                side_effect=Exception("Transcript scan crashed"),
            ),
        ):
            hook_data = {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "hello",
                "session_id": "test-session",
            }
            result = ai_guardian.process_hook_data(hook_data)
            self.assertFalse(
                _is_blocked(result), "Should fail-open when on_scan_error=allow"
            )

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._get_on_scan_error_action")
    @patch("ai_guardian.config.loaders._load_transcript_scanning_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_transcript_scan_error_block(
        self, mock_pattern, mock_secret, mock_transcript, mock_on_error, mock_pii
    ):
        """Transcript scanning error with on_scan_error=block should fail-closed."""
        mock_on_error.return_value = "block"
        mock_pattern.return_value = None
        mock_secret.return_value = ({"enabled": False}, None)
        mock_transcript.return_value = ({"enabled": True}, None)
        mock_pii.return_value = ({"enabled": False}, None)

        from ai_guardian.scanners.transcript.jsonl import JsonlTranscriptAdapter

        failing_adapter = JsonlTranscriptAdapter()
        failing_adapter.can_scan = lambda hd, a: True
        failing_adapter.scan_incremental = Mock(
            side_effect=Exception("Transcript scan crashed")
        )

        with patch(
            "ai_guardian.scanners.transcript.TRANSCRIPT_ADAPTERS",
            [failing_adapter],
        ):
            hook_data = {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "hello",
                "session_id": "test-session",
            }
            result = ai_guardian.process_hook_data(hook_data)
            self.assertTrue(
                _is_blocked(result), "Should fail-closed when on_scan_error=block"
            )


class TestOnScanErrorPiiScanning(TestCase):
    """Tests for on_scan_error behavior in PII scanning (Issue #507)."""

    def test_scan_for_pii_error_allow(self):
        """PII scan exception with on_scan_error=allow should fail-open."""
        pii_config = {"enabled": True, "pii_types": ["ssn"], "action": "block"}

        with (
            patch(
                "ai_guardian.config.loaders._get_on_scan_error_action",
                return_value="allow",
            ),
            patch(
                "ai_guardian.scanners.secret_redactor.SecretRedactor",
                side_effect=Exception("PII scan crashed"),
            ),
        ):
            has_pii, text, redactions, warning = ai_guardian._scan_for_pii(
                "test text", pii_config
            )
            self.assertFalse(has_pii, "Should fail-open when on_scan_error=allow")
            self.assertEqual(redactions, [])
            self.assertIsNone(warning)

    def test_scan_for_pii_error_block(self):
        """PII scan exception with on_scan_error=block should fail-closed."""
        pii_config = {"enabled": True, "pii_types": ["ssn"], "action": "block"}

        with (
            patch(
                "ai_guardian.config.loaders._get_on_scan_error_action",
                return_value="block",
            ),
            patch(
                "ai_guardian.scanners.secret_redactor.SecretRedactor",
                side_effect=Exception("PII scan crashed"),
            ),
        ):
            has_pii, text, redactions, warning = ai_guardian._scan_for_pii(
                "test text", pii_config
            )
            self.assertTrue(has_pii, "Should fail-closed when on_scan_error=block")
            self.assertEqual(redactions, [], "Redactions should be empty on scan error")
            self.assertIn("on_scan_error=block", warning)

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_pii_scan_error_no_violation_logged(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """PII scan error should not log a pii_detected violation (Issue #507)."""
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "block",
                "ignore_files": [],
            },
            None,
        )
        # Simulate scan error: has_pii=True but empty redactions
        mock_scan.return_value = (
            True,
            "test text",
            [],
            "PII scan failed (blocked by on_scan_error=block)",
        )

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use": {
                "name": "Agent",
                "input": {},
            },
            "tool_response": {"output": "Some agent output with no PII"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            with patch(
                "ai_guardian.hook_processing.ViolationLogger.log_violation"
            ) as mock_log:
                result = ai_guardian.process_hook_input()
                # Should block (scan error with on_scan_error=block)
                self.assertTrue(
                    _is_blocked(result),
                    "Should block on scan error with on_scan_error=block",
                )
                # Should NOT log a pii_detected violation
                for call in mock_log.call_args_list:
                    self.assertNotEqual(
                        call.kwargs.get(
                            "violation_type", call.args[0] if call.args else None
                        ),
                        "pii_detected",
                        "Should not log pii_detected violation when pii_count=0",
                    )

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_pii_scan_no_pii_no_violation(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """Clean PII scan with no findings should not block or log violations."""
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "block",
                "ignore_files": [],
            },
            None,
        )
        # No PII found
        mock_scan.return_value = (False, "Safe agent output", [], None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use": {
                "name": "Agent",
                "input": {},
            },
            "tool_response": {"output": "Safe agent output"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            with patch(
                "ai_guardian.hook_processing.ViolationLogger.log_violation"
            ) as mock_log:
                result = ai_guardian.process_hook_input()
                self.assertFalse(
                    _is_blocked(result), "Should not block when no PII found"
                )
                for call in mock_log.call_args_list:
                    self.assertNotEqual(
                        call.kwargs.get(
                            "violation_type", call.args[0] if call.args else None
                        ),
                        "pii_detected",
                        "Should not log pii_detected when no PII found",
                    )

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.hook_processing.extract_file_content_from_tool")
    def test_pretooluse_pii_scan_error_no_violation(
        self, mock_extract, mock_pattern, mock_ss, mock_pii, mock_scan
    ):
        """PreToolUse PII scan error should not log a false violation (Issue #507)."""
        mock_pattern.return_value = None
        mock_ss.return_value = ({"enabled": False}, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "block",
                "ignore_files": [],
            },
            None,
        )
        mock_extract.return_value = (
            "file content",
            "test.txt",
            "/tmp/test.txt",
            False,
            None,
            None,
        )
        # Simulate scan error: has_pii=True but empty redactions
        mock_scan.return_value = (
            True,
            "file content",
            [],
            "PII scan failed (blocked by on_scan_error=block)",
        )

        hook_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_use": {"name": "Read", "parameters": {"file_path": "/tmp/test.txt"}},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            with patch(
                "ai_guardian.hook_processing.ViolationLogger.log_violation"
            ) as mock_log:
                result = ai_guardian.process_hook_input()
                self.assertTrue(
                    _is_blocked(result),
                    "Should block on scan error with on_scan_error=block",
                )
                for call in mock_log.call_args_list:
                    self.assertNotEqual(
                        call.kwargs.get(
                            "violation_type", call.args[0] if call.args else None
                        ),
                        "pii_detected",
                        "Should not log pii_detected violation on scan error",
                    )


class TestOnScanErrorBackwardCompatibility(TestCase):
    """Test backward compatibility - default behavior unchanged."""

    @patch("ai_guardian.hook_processing._load_config_file")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    def test_default_behavior_unchanged(self, mock_check_secrets, mock_load_config):
        """Without on_scan_error config, behavior is fail-open (backward compatible)."""
        mock_load_config.return_value = ({"secret_scanning": {"enabled": True}}, None)
        mock_check_secrets.side_effect = Exception("Simulated error")

        hook_input = json.dumps({"prompt": "test", "session_id": "test"})

        with patch("sys.stdin", StringIO(hook_input)):
            response = ai_guardian.process_hook_input()

        self.assertEqual(response["exit_code"], 0, "Default should be fail-open")
