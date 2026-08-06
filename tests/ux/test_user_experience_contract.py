"""
User Experience Contract Tests for PreToolUse Hook Behavior

These tests document and verify the expected user experience when ai-guardian
is configured in Claude Code's PreToolUse hook. They serve as a "contract"
that defines what users should see in the IDE.

While we can't automate the Claude Code UI, these tests verify ai-guardian's
responses that drive the user experience.

Issue #224: PreToolUse should NOT auto-approve clean operations.
"""

import json
from io import StringIO
from unittest import TestCase
from unittest.mock import patch

import ai_guardian
from tests.fixtures.mock_mcp_server import create_hook_data


class UserExperienceContractTests(TestCase):
    """
    Tests documenting the user experience contract.

    These tests verify what users SHOULD see when ai-guardian is configured
    in Claude Code's PreToolUse hook.
    """

    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_user_experience_read_with_secret(self, mock_config, mock_check_secrets):
        """
        USER EXPERIENCE: Read with secret → DENIED immediately, no prompt shown.

        Scenario:
        1. Claude Code's permission setting: "Ask before Read" (user wants to review)
        2. User asks Claude: "Read the config file"
        3. Claude tries to Read file containing secrets
        4. ai-guardian PreToolUse hook runs

        Expected User Experience:
        ❌ Claude Code does NOT show permission prompt
        ❌ Operation is BLOCKED immediately
        🛡️ User sees error: "Secrets detected in file content"

        This is CORRECT behavior - secrets should never be exposed to AI,
        regardless of user permission settings.

        Note: Edit/Write tools don't scan for secrets in PreToolUse (they don't
        read existing file content). Secret detection for Edit/Write happens in
        PostToolUse when scanning command output or via tool policy checks.
        """
        mock_config.return_value = (None, None)
        mock_check_secrets.return_value = (True, "Secret detected: AWS access key")

        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("aws_access_key_id = AKIAIOSFODNN7EXAMPLE")
            temp_path = f.name

        try:
            # Claude Code invokes PreToolUse hook before showing permission prompt
            hook_data = create_hook_data(
                tool_name="Read",
                tool_input={"file_path": temp_path},
                hook_event="PreToolUse",
            )

            with patch("sys.stdin", StringIO(json.dumps(hook_data))):
                result = ai_guardian.process_hook_input()

            # Verify ai-guardian's response
            assert result["exit_code"] == 0  # JSON response format

            response = json.loads(result["output"])

            # CONTRACT: Response MUST contain permissionDecision: deny
            assert (
                "hookSpecificOutput" in response
            ), "Response must include hookSpecificOutput for Claude Code"
            assert (
                response["hookSpecificOutput"]["permissionDecision"] == "deny"
            ), "Must return deny to block operation"
            assert (
                response["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
            ), "Must identify hook event"
            assert (
                "systemMessage" in response
            ), "Must include error message to display to user"
            assert (
                "secret" in response["systemMessage"].lower()
            ), "Error message should mention secret"

            # USER SEES: Error message in Claude Code
            # USER DOES NOT SEE: Permission prompt (operation blocked before prompt)
            # OPERATION: Denied, file not read, secrets not exposed to AI

        finally:
            import os

            os.unlink(temp_path)

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_user_experience_edit_without_secret(
        self, mock_pattern_config, mock_redaction_config
    ):
        """
        USER EXPERIENCE: Edit without secret → Permission prompt shown (if configured).

        Scenario:
        1. Claude Code's permission setting: "Ask before Edit" (user wants to review)
        2. User asks Claude: "Update config.py to set debug=true"
        3. Claude tries to Edit file (no secrets)
        4. ai-guardian PreToolUse hook runs

        Expected User Experience:
        ✅ Claude Code SHOWS permission prompt: "Claude wants to edit config.py"
        ✅ User can review the change
        ✅ User clicks "Allow" or "Deny"

        This is CORRECT behavior - user retains control over file modifications
        when no security threats are detected.

        This is the FIX for issue #224 - previously, ai-guardian returned
        permissionDecision: allow, which bypassed the prompt.
        """
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        # Claude Code invokes PreToolUse hook before showing permission prompt
        hook_data = create_hook_data(
            tool_name="Edit",
            tool_input={
                "file_path": "/tmp/config.py",
                "old_string": "DEBUG = False",
                "new_string": "DEBUG = True",
            },
            hook_event="PreToolUse",
        )

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        # Verify ai-guardian's response
        assert result["exit_code"] == 0  # Operation allowed to proceed

        response = json.loads(result["output"])

        # CONTRACT: Response MUST NOT contain permissionDecision
        # This allows Claude Code to use its own permission system
        if "hookSpecificOutput" in response:
            assert (
                "permissionDecision" not in response["hookSpecificOutput"]
            ), "Must NOT return permissionDecision - this would bypass Claude Code's prompt"

        # Response should be empty or only contain warnings
        assert (
            response == {} or "systemMessage" in response
        ), f"Response should be empty (allows normal prompt), got: {response}"

        # USER SEES: Claude Code permission prompt (because ai-guardian didn't auto-approve)
        # PROMPT SHOWS: "Claude wants to edit /tmp/config.py"
        # USER CHOOSES: Allow or Deny
        # OPERATION: Proceeds only if user approves

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_user_experience_comparison_secret_vs_clean(
        self,
        mock_scan_config,
        mock_check_secrets,
        mock_pattern_config,
        mock_redaction_config,
    ):
        """
        USER EXPERIENCE COMPARISON: Secret vs Clean operations.

        This test demonstrates the difference in user experience between
        operations with secrets (denied) vs clean operations (prompt shown).

        Scenario A: Read with secret
        =============================
        1. User asks: "Read the API key from config"
        2. ai-guardian: DENIES immediately
        3. User sees: Error message "Secrets detected"
        4. User does NOT see: Permission prompt
        5. Result: File NOT read (secrets not exposed to AI)

        Scenario B: Edit without secret
        ================================
        1. User asks: "Set debug=true in config"
        2. ai-guardian: Returns empty response (no auto-approve)
        3. User sees: Permission prompt "Claude wants to edit config.py"
        4. User clicks: "Allow"
        5. Result: File modified (user gave explicit consent)

        This is the CORRECT behavior post-fix for issue #224.
        """
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)
        mock_scan_config.return_value = (None, None)

        # Scenario A: Clean operation (Edit without secret)
        clean_hook = create_hook_data(
            tool_name="Edit",
            tool_input={
                "file_path": "/tmp/config.py",
                "old_string": "DEBUG = False",
                "new_string": "DEBUG = True",
            },
            hook_event="PreToolUse",
        )

        with patch("sys.stdin", StringIO(json.dumps(clean_hook))):
            clean_result = ai_guardian.process_hook_input()

        clean_response = json.loads(clean_result["output"])

        # Scenario A verification: No auto-approve
        assert clean_result["exit_code"] == 0, "Clean operation allowed to proceed"
        if "hookSpecificOutput" in clean_response:
            assert (
                "permissionDecision" not in clean_response["hookSpecificOutput"]
            ), "Clean operation: Must NOT auto-approve"

        # Scenario B: Operation with secret (Read tool scanning file with secret)
        mock_check_secrets.return_value = (True, "Secret detected: API key")

        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("API_KEY = 'sk_live_abc123'")
            temp_path = f.name

        try:
            secret_hook = create_hook_data(
                tool_name="Read",
                tool_input={"file_path": temp_path},
                hook_event="PreToolUse",
            )

            with patch("sys.stdin", StringIO(json.dumps(secret_hook))):
                secret_result = ai_guardian.process_hook_input()

            secret_response = json.loads(secret_result["output"])

            # Scenario B verification: Immediate denial
            assert secret_result["exit_code"] == 0  # JSON format
            assert (
                "hookSpecificOutput" in secret_response
            ), "Secret operation: Must include hookSpecificOutput"
            assert (
                secret_response["hookSpecificOutput"]["permissionDecision"] == "deny"
            ), "Secret operation: Must deny immediately"

        finally:
            import os

            os.unlink(temp_path)

        # SUMMARY: Different user experiences
        # Clean Edit: User sees prompt, chooses to allow/deny
        # Read with Secret: User sees error, operation blocked immediately

    def test_user_experience_documentation(self):
        """
        Documentation test: What users should expect.

        This test always passes but documents the expected behavior
        for users configuring ai-guardian in Claude Code.

        Configuration:
        ==============
        ~/.claude/settings.json:
        {
          "PreToolUse": [
            {
              "matcher": "*",
              "hooks": [
                {
                  "command": "ai-guardian",
                  "statusMessage": "🛡️ AI Guardian checking..."
                }
              ]
            }
          ]
        }

        Expected User Experience:
        ========================

        1. READ WITH SECRETS:
           ❌ BLOCKED immediately (PreToolUse scans file content)
           🛡️ Error shown: "Secrets detected in file"
           ⚠️ No permission prompt (security override)

        2. EDIT/WRITE OPERATIONS:
           ✅ Permission prompt shown (if configured)
           👤 User reviews and approves/denies
           ✅ User maintains control
           ⚠️ Note: Edit/Write don't scan for secrets in PreToolUse
              (they don't read existing file content in PreToolUse)

        3. BASH OUTPUT WITH SECRETS:
           ❌ BLOCKED in PostToolUse (scans command output)
           🛡️ Error shown: "Secrets detected in output"

        4. OTHER TOOLS:
           ✅ Normal permission flow
           👤 User control maintained

        This is the correct behavior after fixing issue #224.
        Previously (v1.3.0-v1.4.1), Edit/Write operations without secrets
        were AUTO-APPROVED, bypassing user permission prompts.
        """
        # This test always passes - it's documentation
        assert True, "See docstring for expected user experience"


class ManualVerificationGuide(TestCase):
    """
    Manual verification guide for testing in actual Claude Code.

    These tests document how to manually verify the fix in Claude Code IDE.
    They always pass but provide step-by-step instructions.
    """

    def test_manual_verification_steps(self):
        """
        MANUAL VERIFICATION: How to test this in Claude Code IDE.

        Prerequisites:
        =============
        1. Install ai-guardian: pip install ai-guardian
        2. Configure PreToolUse hook in ~/.claude/settings.json (see above)
        3. Set Claude Code to "Ask before Edit" in permissions

        Test Steps:
        ==========

        TEST 1: Read with secret (should DENY, no prompt)
        --------------------------------------------------
        1. Create test file: /tmp/secret_config.py with content "API_KEY = 'sk_test_abc123'"
        2. Ask Claude: "Read /tmp/secret_config.py"
        3. EXPECTED: Operation blocked, error shown, NO permission prompt
        4. VERIFY: File not read, secrets not exposed to Claude

        TEST 2: Edit without secret (should PROMPT)
        -------------------------------------------
        1. Create test file: /tmp/test_config.py with content "DEBUG = False"
        2. Ask Claude: "Edit /tmp/test_config.py and set DEBUG to True"
        3. EXPECTED: Permission prompt shown: "Claude wants to edit test_config.py"
        4. VERIFY: You can click "Allow" or "Deny"
        5. VERIFY: File only modified if you click "Allow"

        TEST 3: Verify no auto-approve (the bug)
        ----------------------------------------
        1. Complete TEST 2 above
        2. CRITICAL: If you see NO permission prompt and file is modified immediately,
           the bug is present (ai-guardian auto-approved)
        3. CORRECT: Permission prompt appears, you must click "Allow"

        Troubleshooting:
        ===============
        - If no permission prompt for TEST 2: Check Claude Code permission settings
        - If both tests show prompts: ai-guardian might not be running (check logs)
        - Logs: Check ~/.claude/logs/ for ai-guardian output
        """
        # This test always passes - it's a manual testing guide
        assert True, "See docstring for manual verification steps"
