"""
Integration tests verifying PreToolUse hook doesn't auto-approve clean operations.

Tests the fix for issue #224: PreToolUse should NOT return permissionDecision
when no threats are detected, allowing Claude Code's normal permission system
to prompt the user instead of auto-approving file modifications.

These tests verify the complete end-to-end behavior, not just the response format.
"""

import json
from io import StringIO
from unittest import TestCase
from unittest.mock import patch

import ai_guardian
from tests.fixtures.mock_mcp_server import create_hook_data


class PreToolUseNoAutoApproveTests(TestCase):
    """Integration tests: PreToolUse doesn't auto-approve clean operations"""

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_edit_operation_no_auto_approve_claude_code(
        self, mock_pattern_config, mock_redaction_config
    ):
        """
        Verify Edit operations don't auto-approve when clean (Claude Code).

        Issue #224: Edit tool was auto-approved when no secrets detected,
        bypassing Claude Code's permission prompts.

        Expected behavior:
        - exit_code=0 (operation allowed to proceed)
        - Response does NOT contain permissionDecision
        - Claude Code will show normal permission prompt to user
        """
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        # Edit tool with clean content
        hook_data = create_hook_data(
            tool_name="Edit",
            tool_input={
                "file_path": "/tmp/config.py",
                "old_string": "old code",
                "new_string": "print('Hello, World!')",
            },
            hook_event="PreToolUse",
        )

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        # Operation should be allowed to proceed
        assert result["exit_code"] == 0, "Clean Edit should be allowed"

        # Parse response
        response = json.loads(result["output"])

        # CRITICAL: Should NOT auto-approve
        if "hookSpecificOutput" in response:
            assert (
                "permissionDecision" not in response["hookSpecificOutput"]
            ), "Edit operations should NOT auto-approve (missing permissionDecision allows Claude Code prompt)"

        # Response should be empty or only contain warnings
        assert (
            response == {} or "systemMessage" in response
        ), f"Response should be empty or only warnings, got: {response}"

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.hook_processing.detect_adapter")
    def test_edit_operation_no_auto_approve_github_copilot(
        self, mock_detect_adapter, mock_pattern_config, mock_redaction_config
    ):
        """
        Verify Edit operations don't auto-approve when clean (GitHub Copilot).

        Issue #224: GitHub Copilot integration introduced auto-approve bug in v1.3.0.

        Expected behavior:
        - exit_code=0 (operation allowed to proceed)
        - Response does NOT contain permissionDecision
        - GitHub Copilot will use its own permission system
        """
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        from ai_guardian.hook_adapters import CopilotAdapter

        mock_detect_adapter.return_value = CopilotAdapter()

        # GitHub Copilot format
        hook_data = {
            "hookEventName": "preToolUse",
            "toolName": "Edit",
            "toolArgs": json.dumps(
                {
                    "file_path": "/tmp/config.py",
                    "old_string": "old code",
                    "new_string": "print('Hello, World!')",
                }
            ),
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        # Operation should be allowed to proceed
        assert result["exit_code"] == 0, "Clean Edit should be allowed"

        # Parse response
        response = json.loads(result["output"])

        # CRITICAL: Should NOT auto-approve
        assert (
            "permissionDecision" not in response
        ), "Edit operations should NOT auto-approve (missing permissionDecision allows normal prompts)"

        # Response should be empty
        assert response == {}, f"Response should be empty, got: {response}"

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_write_operation_no_auto_approve_claude_code(
        self, mock_pattern_config, mock_redaction_config
    ):
        """
        Verify Write operations don't auto-approve when clean (Claude Code).

        Issue #224: Write tool was also affected by auto-approve bug.
        """
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        # Write tool with clean content
        hook_data = create_hook_data(
            tool_name="Write",
            tool_input={"file_path": "/tmp/output.txt", "content": "Hello, World!"},
            hook_event="PreToolUse",
        )

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        # Operation should be allowed to proceed
        assert result["exit_code"] == 0, "Clean Write should be allowed"

        # Parse response
        response = json.loads(result["output"])

        # CRITICAL: Should NOT auto-approve
        if "hookSpecificOutput" in response:
            assert (
                "permissionDecision" not in response["hookSpecificOutput"]
            ), "Write operations should NOT auto-approve"

        assert (
            response == {} or "systemMessage" in response
        ), f"Response should be empty or only warnings, got: {response}"

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.hook_processing.detect_adapter")
    def test_write_operation_no_auto_approve_github_copilot(
        self, mock_detect_adapter, mock_pattern_config, mock_redaction_config
    ):
        """
        Verify Write operations don't auto-approve when clean (GitHub Copilot).
        """
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        from ai_guardian.hook_adapters import CopilotAdapter

        mock_detect_adapter.return_value = CopilotAdapter()

        # GitHub Copilot format
        hook_data = {
            "hookEventName": "preToolUse",
            "toolName": "Write",
            "toolArgs": json.dumps(
                {"file_path": "/tmp/output.txt", "content": "Hello, World!"}
            ),
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        # Operation should be allowed to proceed
        assert result["exit_code"] == 0, "Clean Write should be allowed"

        # Parse response
        response = json.loads(result["output"])

        # CRITICAL: Should NOT auto-approve
        assert (
            "permissionDecision" not in response
        ), "Write operations should NOT auto-approve"

        assert response == {}, f"Response should be empty, got: {response}"

    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_read_with_secret_still_denies(self, mock_config, mock_check_secrets):
        """
        Verify PreToolUse still DENIES when secrets ARE detected.

        This ensures the fix only affects clean operations, not threat detection.
        """
        mock_config.return_value = (None, None)
        mock_check_secrets.return_value = (True, "Secret detected: AWS key")

        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("aws_access_key_id = AKIAIOSFODNN7EXAMPLE")
            temp_path = f.name

        try:
            hook_data = create_hook_data(
                tool_name="Read",
                tool_input={"file_path": temp_path},
                hook_event="PreToolUse",
            )

            with patch("sys.stdin", StringIO(json.dumps(hook_data))):
                result = ai_guardian.process_hook_input()

            # Should still block
            assert result["exit_code"] == 0  # JSON response format

            response = json.loads(result["output"])

            # Should deny when secrets detected
            assert "hookSpecificOutput" in response
            assert (
                response["hookSpecificOutput"]["permissionDecision"] == "deny"
            ), "Should still DENY when secrets detected"
            assert "systemMessage" in response, "Should include error message"
        finally:
            import os

            os.unlink(temp_path)

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_e2e_edit_workflow_user_sees_prompt(
        self, mock_pattern_config, mock_redaction_config
    ):
        """
        End-to-end test: User workflow with Edit tool.

        Scenario:
        1. User asks Claude to edit a file
        2. UserPromptSubmit hook: Allows (no threats in prompt)
        3. PreToolUse hook: Returns empty response (no auto-approve)
        4. Claude Code shows permission prompt to user
        5. User approves (outside this test scope)
        6. Edit executes

        This test verifies step 3: PreToolUse doesn't bypass the permission prompt.
        """
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        # Step 1: UserPromptSubmit
        prompt_data = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Update the config file to set debug=true",
        }

        with patch("sys.stdin", StringIO(json.dumps(prompt_data))):
            result = ai_guardian.process_hook_input()

        assert result["exit_code"] == 0, "Clean prompt should be allowed"

        # Step 2: PreToolUse for Edit
        edit_data = create_hook_data(
            tool_name="Edit",
            tool_input={
                "file_path": "/tmp/config.json",
                "old_string": '"debug": false',
                "new_string": '"debug": true',
            },
            hook_event="PreToolUse",
        )

        with patch("sys.stdin", StringIO(json.dumps(edit_data))):
            result = ai_guardian.process_hook_input()

        # Allowed but NOT auto-approved
        assert result["exit_code"] == 0, "Clean Edit allowed to proceed"

        response = json.loads(result["output"])

        # The key assertion: No auto-approve
        if "hookSpecificOutput" in response:
            assert (
                "permissionDecision" not in response["hookSpecificOutput"]
            ), "PreToolUse must NOT auto-approve - user should see permission prompt"

        assert (
            response == {} or "systemMessage" in response
        ), "Empty response allows Claude Code to show normal permission dialog"
