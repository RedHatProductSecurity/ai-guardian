"""
Test security instructions injection via systemMessage.

Issue #580: Inject never-bypass rules via systemMessage.
Issue #584: Inject only on first prompt per session + after blocks.
"""

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import ai_guardian
from ai_guardian import _SECURITY_SYSTEM_MESSAGE, IDEType, format_response


class TestSecurityMessageConstant(TestCase):
    """Verify the security message uses generic language."""

    def test_generic_language_no_specific_bypass_terms(self):
        """The constant must NOT name specific bypass mechanisms."""
        forbidden_terms = [
            ".ai-read-deny",
            ".aiguardignore.toml",
            "ai-guardian.json",
            "annotations",
            "--skip-checksum-verification",
            "--no-verify",
        ]
        for term in forbidden_terms:
            self.assertNotIn(
                term,
                _SECURITY_SYSTEM_MESSAGE,
                f"Security message must not name specific mechanism: {term}",
            )

    def test_contains_security_rules(self):
        """The constant should contain key security rules."""
        self.assertIn("bypass", _SECURITY_SYSTEM_MESSAGE.lower())
        self.assertIn("security", _SECURITY_SYSTEM_MESSAGE.lower())
        self.assertIn("blocked", _SECURITY_SYSTEM_MESSAGE.lower())


class TestFormatResponseSecurityMessage(TestCase):
    """Unit tests for format_response with security_message parameter."""

    def test_security_message_in_prompt_allow(self):
        """Security message appears in systemMessage for Claude Code prompt allow."""
        result = format_response(
            IDEType.CLAUDE_CODE,
            has_secrets=False,
            hook_event="prompt",
            security_message="TEST_SECURITY_RULES",
        )
        output = json.loads(result["output"])
        self.assertIn("systemMessage", output)
        self.assertIn("TEST_SECURITY_RULES", output["systemMessage"])

    def test_security_message_combined_with_warning(self):
        """Security message is prepended to warning_message."""
        result = format_response(
            IDEType.CLAUDE_CODE,
            has_secrets=False,
            hook_event="prompt",
            warning_message="Warning: config error",
            security_message="TEST_SECURITY_RULES",
        )
        output = json.loads(result["output"])
        self.assertIn("systemMessage", output)
        self.assertIn("TEST_SECURITY_RULES", output["systemMessage"])
        self.assertIn("Warning: config error", output["systemMessage"])
        self.assertTrue(
            output["systemMessage"].index("TEST_SECURITY_RULES")
            < output["systemMessage"].index("Warning: config error"),
            "Security rules should come before warnings",
        )

    def test_security_message_not_in_block_response(self):
        """Blocked prompts don't include security message."""
        result = format_response(
            IDEType.CLAUDE_CODE,
            has_secrets=True,
            error_message="Secret detected",
            hook_event="prompt",
            security_message="TEST_SECURITY_RULES",
        )
        output = json.loads(result["output"])
        self.assertEqual(output.get("decision"), "block")
        self.assertNotIn("TEST_SECURITY_RULES", output.get("reason", ""))

    def test_no_security_message_when_none(self):
        """No systemMessage when security_message is None and no warnings."""
        result = format_response(
            IDEType.CLAUDE_CODE,
            has_secrets=False,
            hook_event="prompt",
            security_message=None,
        )
        output = json.loads(result["output"])
        self.assertNotIn("systemMessage", output)

    def test_security_message_delivered_for_pretooluse(self):
        """Security message is delivered for PreToolUse hooks (#1527)."""
        result = format_response(
            IDEType.CLAUDE_CODE,
            has_secrets=False,
            hook_event="pretooluse",
            security_message="TEST_SECURITY_RULES",
        )
        output = json.loads(result["output"])
        self.assertIn("TEST_SECURITY_RULES", output.get("systemMessage", ""))
        self.assertIn(
            "TEST_SECURITY_RULES",
            output.get("hookSpecificOutput", {}).get("additionalContext", ""),
        )

    def test_security_message_delivered_to_cursor_agent(self):
        """Security message is delivered via agent_message for Cursor IDE."""
        result = format_response(
            IDEType.CURSOR,
            has_secrets=False,
            hook_event="prompt",
            security_message="TEST_SECURITY_RULES",
        )
        output = json.loads(result["output"])
        self.assertIn("TEST_SECURITY_RULES", output.get("agent_message", ""))


class TestProcessHookDataSecurityMessage(TestCase):
    """Integration tests for security message injection in process_hook_data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_patcher = patch(
            "ai_guardian.session_state.get_state_dir",
            return_value=Path(self.tmpdir),
        )
        self.state_patcher.start()

    def tearDown(self):
        self.state_patcher.stop()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("ai_guardian.hook_processing._load_security_instructions_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_security_message_injected_on_first_prompt(
        self, mock_pattern_config, mock_redaction_config, mock_si_config
    ):
        """First prompt with default config includes security message."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_si_config.return_value = (None, None)

        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "test-session-first",
            "prompt": "What is the capital of France?",
        }

        result = ai_guardian.process_hook_data(hook_data)
        self.assertEqual(result["exit_code"], 0)
        output = json.loads(result["output"])
        self.assertIn("systemMessage", output)
        self.assertIn("SECURITY RULES", output["systemMessage"])

    @patch("ai_guardian.hook_processing._load_security_instructions_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_security_message_not_injected_on_second_prompt(
        self, mock_pattern_config, mock_redaction_config, mock_si_config
    ):
        """Second prompt in same session should NOT get security message."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_si_config.return_value = (None, None)

        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "test-session-second",
            "prompt": "Hello",
        }

        # First prompt: injects
        result1 = ai_guardian.process_hook_data(hook_data)
        output1 = json.loads(result1["output"])
        self.assertIn("SECURITY RULES", output1.get("systemMessage", ""))

        # Second prompt: should NOT inject
        result2 = ai_guardian.process_hook_data(hook_data)
        output2 = json.loads(result2["output"])
        self.assertNotIn("systemMessage", output2)

    @patch("ai_guardian.hook_processing._load_security_instructions_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_security_message_reinjected_after_block(
        self, mock_pattern_config, mock_redaction_config, mock_si_config
    ):
        """After a block event, next prompt should re-inject security message."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_si_config.return_value = (None, None)

        session_id = "test-session-reinject"
        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session_id,
            "prompt": "Hello",
        }

        # First prompt: injects
        result1 = ai_guardian.process_hook_data(hook_data)
        output1 = json.loads(result1["output"])
        self.assertIn("SECURITY RULES", output1.get("systemMessage", ""))

        # Simulate a block by marking reinject via SessionStateManager
        from ai_guardian.session_state import SessionStateManager

        mgr = SessionStateManager()
        mgr.mark_security_reinject(session_id)

        # Next prompt: should re-inject
        result3 = ai_guardian.process_hook_data(hook_data)
        output3 = json.loads(result3["output"])
        self.assertIn("systemMessage", output3)
        self.assertIn("SECURITY RULES", output3["systemMessage"])

    @patch("ai_guardian.hook_processing._load_security_instructions_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_security_message_not_injected_when_disabled(
        self, mock_pattern_config, mock_redaction_config, mock_si_config
    ):
        """When inject_on_prompt is False, no security message on clean prompts."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_si_config.return_value = ({"inject_on_prompt": False}, None)

        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "test-session-disabled",
            "prompt": "What is the capital of France?",
        }

        result = ai_guardian.process_hook_data(hook_data)
        self.assertEqual(result["exit_code"], 0)
        output = json.loads(result["output"])
        self.assertEqual(output, {})

    @patch("ai_guardian.hook_processing._load_security_instructions_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_security_message_not_injected_for_pretooluse(
        self, mock_pattern_config, mock_redaction_config, mock_si_config
    ):
        """PreToolUse hooks should not get security message injection."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_si_config.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PreToolUse",
            "tool_use": {"name": "Read", "parameters": {"file_path": "/tmp/test.txt"}},
        }

        result = ai_guardian.process_hook_data(hook_data)
        self.assertEqual(result["exit_code"], 0)
        output = json.loads(result["output"])
        self.assertNotIn("SECURITY RULES", json.dumps(output))

    @patch("ai_guardian.hook_processing.detect_adapter")
    @patch("ai_guardian.hook_processing._load_security_instructions_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_security_message_not_injected_for_cursor(
        self,
        mock_pattern_config,
        mock_redaction_config,
        mock_si_config,
        mock_detect_adapter,
    ):
        """Cursor IDE should not get security message injection."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_si_config.return_value = (None, None)
        from ai_guardian.hook_adapters import CursorAdapter

        mock_detect_adapter.return_value = CursorAdapter()

        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "What is the capital of France?",
        }

        result = ai_guardian.process_hook_data(hook_data)
        output = json.loads(result["output"])
        self.assertNotIn("SECURITY RULES", json.dumps(output))

    @patch("ai_guardian.hook_processing._load_security_instructions_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_security_message_not_injected_for_opencode_bridge(
        self, mock_pattern_config, mock_redaction_config, mock_si_config
    ):
        """OpenCode's plugin bridge does not deliver systemMessage to the model."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_si_config.return_value = (None, None)

        result = ai_guardian.process_hook_data(
            {
                "hook_event_name": "message.submit",
                "hook_source": "opencode",
                "opencode_version": "1.19.0",
                "session_id": "opencode-security-rules",
                "cwd": "/tmp/project",
                "prompt": "Hello",
            }
        )

        self.assertNotIn("SECURITY RULES", json.dumps(json.loads(result["output"])))

    @patch("ai_guardian.hook_processing._load_security_instructions_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_security_message_not_injected_for_kilo_plugin(
        self, mock_pattern_config, mock_redaction_config, mock_si_config
    ):
        """Kilo's mutable chat hook has no native model-context field."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_si_config.return_value = (None, None)

        result = ai_guardian.process_hook_data(
            {
                "hook_event_name": "UserPromptSubmit",
                "hook_source": "kilo",
                "kilo_plugin_api": "v1",
                "session_id": "kilo-security-rules",
                "cwd": "/tmp/project",
                "prompt": "Hello",
            }
        )

        self.assertNotIn("SECURITY RULES", json.dumps(json.loads(result["output"])))

    @patch("ai_guardian.hook_processing._load_security_instructions_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_security_message_on_empty_prompt(
        self, mock_pattern_config, mock_redaction_config, mock_si_config
    ):
        """Empty prompt still gets security message injection on first call."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_si_config.return_value = (None, None)

        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "test-session-empty",
            "prompt": "",
        }

        result = ai_guardian.process_hook_data(hook_data)
        self.assertEqual(result["exit_code"], 0)
        output = json.loads(result["output"])
        self.assertIn("systemMessage", output)
        self.assertIn("SECURITY RULES", output["systemMessage"])

    @patch("ai_guardian.hook_processing._load_security_instructions_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_different_sessions_each_get_first_injection(
        self, mock_pattern_config, mock_redaction_config, mock_si_config
    ):
        """Each new session should get security message on its first prompt."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_si_config.return_value = (None, None)

        for session_id in ["session-a", "session-b", "session-c"]:
            hook_data = {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session_id,
                "prompt": "Hello",
            }
            result = ai_guardian.process_hook_data(hook_data)
            output = json.loads(result["output"])
            self.assertIn(
                "SECURITY RULES",
                output.get("systemMessage", ""),
                f"Session {session_id} should get security rules on first prompt",
            )


class TestCursorLoggingRestore(TestCase):
    """Verify logging.disable(CRITICAL) for Cursor is restored after each request.

    Issue #1343: In daemon mode, one Cursor request called logging.disable(CRITICAL)
    but never restored it, killing all logging for subsequent requests from any IDE.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_patcher = patch(
            "ai_guardian.session_state.get_state_dir",
            return_value=Path(self.tmpdir),
        )
        self.state_patcher.start()

    def tearDown(self):
        self.state_patcher.stop()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("ai_guardian.hook_processing.detect_adapter")
    @patch("ai_guardian.hook_processing._load_security_instructions_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_logging_restored_after_cursor_request(
        self,
        mock_pattern_config,
        mock_redaction_config,
        mock_si_config,
        mock_detect_adapter,
    ):
        """logging.disable(CRITICAL) for Cursor must be restored in finally block."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_si_config.return_value = (None, None)
        from ai_guardian.hook_adapters import CursorAdapter

        mock_detect_adapter.return_value = CursorAdapter()

        hook_data = {"hook_event_name": "UserPromptSubmit", "prompt": "Hello"}

        ai_guardian.process_hook_data(hook_data)

        import logging as logging_mod

        root = logging_mod.getLogger()
        self.assertFalse(
            root.manager.disable >= logging_mod.CRITICAL,
            "logging must be re-enabled after Cursor request",
        )

    @patch("ai_guardian.hook_processing.detect_adapter")
    @patch("ai_guardian.hook_processing._load_security_instructions_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_logging_restored_after_cursor_error(
        self,
        mock_pattern_config,
        mock_redaction_config,
        mock_si_config,
        mock_detect_adapter,
    ):
        """logging must be restored even when Cursor request raises an exception."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_si_config.return_value = (None, None)
        from ai_guardian.hook_adapters import CursorAdapter

        adapter = CursorAdapter()
        mock_detect_adapter.return_value = adapter

        hook_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "bash",
            "tool_input": {"command": "echo test"},
        }

        ai_guardian.process_hook_data(hook_data)

        import logging as logging_mod

        root = logging_mod.getLogger()
        self.assertFalse(
            root.manager.disable >= logging_mod.CRITICAL,
            "logging must be re-enabled after Cursor request error",
        )
