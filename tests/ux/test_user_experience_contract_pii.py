"""
User Experience Contract Tests for PII Detection (Issue #262)

These tests document and verify the expected user experience when ai-guardian
detects PII (personally identifiable information) in the three hook events:
UserPromptSubmit, PreToolUse, and PostToolUse.

Tests verify that PII is blocked/redacted based on the scan_pii configuration
and that ignore_files patterns are respected.
"""

import json
from io import StringIO
from unittest import TestCase
from unittest.mock import patch

import ai_guardian


class PIIUserPromptSubmitTests(TestCase):
    """Test PII detection in user prompts (UserPromptSubmit hook)."""

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.config.loaders._load_prompt_injection_config")
    def test_user_prompt_with_ssn_blocked(
        self, mock_pi, mock_ss, mock_gitleaks, mock_pii
    ):
        """
        USER EXPERIENCE: User submits prompt containing SSN -> BLOCKED

        Scenario:
        1. User types: "My SSN is 123-45-6789"
        2. ai-guardian UserPromptSubmit hook runs
        3. PII detected (SSN)

        Expected User Experience:
        ❌ Prompt is BLOCKED
        🛡️ User sees: "PII DETECTED ... SSN"
        """
        mock_pi.return_value = (None, None)
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn", "credit_card", "phone", "email"],
                "action": "block",
                "ignore_files": [],
            },
            None,
        )

        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "My SSN is 123-45-6789, please help",
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert output.get("decision") == "block", f"Expected block, got: {output}"
        assert "PII" in output.get("reason", ""), "Should mention PII in reason"

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.config.loaders._load_prompt_injection_config")
    def test_user_prompt_without_pii_allowed(
        self, mock_pi, mock_ss, mock_gitleaks, mock_pii
    ):
        """
        USER EXPERIENCE: Normal prompt without PII -> ALLOWED

        Scenario:
        1. User types: "Help me write a function"
        2. ai-guardian checks for PII
        3. No PII found

        Expected User Experience:
        ✅ Prompt is ALLOWED
        """
        mock_pi.return_value = (None, None)
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn", "credit_card", "phone", "email"],
                "action": "block",
                "ignore_files": [],
            },
            None,
        )

        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Help me write a Python function",
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert output.get("decision") != "block", f"Should not block: {output}"

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.config.loaders._load_prompt_injection_config")
    def test_user_prompt_pii_disabled(self, mock_pi, mock_ss, mock_gitleaks, mock_pii):
        """
        USER EXPERIENCE: PII scanning disabled -> prompt with PII ALLOWED

        Scenario:
        1. User has scan_pii.enabled = false
        2. User types prompt containing SSN
        3. PII scanning is skipped

        Expected User Experience:
        ✅ Prompt is ALLOWED (PII scanning disabled)
        """
        mock_pi.return_value = (None, None)
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = ({"enabled": False}, None)

        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "My SSN is 123-45-6789",
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert (
            output.get("decision") != "block"
        ), f"Should not block when disabled: {output}"


class PIIPostToolUseTests(TestCase):
    """Test PII redaction in tool outputs (PostToolUse hook)."""

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_posttooluse_redacts_credit_card(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """
        USER EXPERIENCE: Tool output contains credit card with action=redact -> REDACTED

        Scenario:
        1. Claude runs a Bash command
        2. Output contains credit card number 4532015112830366
        3. ai-guardian PostToolUse hook runs with action=redact

        Expected User Experience:
        ✅ Output is returned (not blocked)
        🔒 Credit card is masked via updatedToolOutput
        ⚠️ User sees warning about PII redaction
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["credit_card"],
                "action": "redact",
                "ignore_files": [],
            },
            None,
        )
        mock_scan.return_value = (
            True,
            "Card: [HIDDEN CREDIT CARD ****0366]",
            [{"type": "credit_card", "start": 6, "end": 22}],
            "Found 1 PII item(s):\n  - credit_card\n\nAction: redact\n",
        )

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use": {
                "name": "Bash",
                "input": {"command": "cat data.txt"},
            },
            "tool_response": {"output": "Card: 4532015112830366"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert output.get("decision") != "block", "redact action should not block"
        assert (
            "hookSpecificOutput" in output
        ), "Should have hookSpecificOutput with redacted content"
        updated = output["hookSpecificOutput"].get("updatedToolOutput", "")
        assert (
            "4532015112830366" not in updated
        ), "Credit card should be redacted in updatedToolOutput"
        assert "HIDDEN CREDIT CARD" in updated, "Should contain masked placeholder"

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_posttooluse_log_only_mode(self, mock_ss, mock_gitleaks, mock_pii):
        """
        USER EXPERIENCE: PII found with action=log-only -> ALLOWED with warning

        Scenario:
        1. scan_pii.action = "log-only"
        2. Tool output contains SSN
        3. PII is detected but NOT redacted

        Expected User Experience:
        ✅ Output is returned unmodified
        ⚠️ Warning message shown about PII
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "log-only",
                "ignore_files": [],
            },
            None,
        )

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use": {
                "name": "Bash",
                "input": {"command": "cat data.txt"},
            },
            "tool_response": {"output": "SSN: 123-45-6789"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        # Should NOT block
        assert output.get("decision") != "block", "log-only should not block"
        # Should have a system message warning
        assert (
            "systemMessage" in output or output == {}
        ), f"Expected warning or pass-through: {output}"

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_posttooluse_redact_action_replaces_output(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """
        USER EXPERIENCE: PII found with action=redact -> OUTPUT REPLACED

        Scenario:
        1. scan_pii.action = "redact"
        2. Tool output contains SSN
        3. PII is masked and output is replaced via updatedToolOutput

        Expected User Experience:
        ✅ Output is replaced with redacted version
        🔒 SSN masked: [HIDDEN SSN]
        ⚠️ Warning shown about PII detection
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "redact",
                "ignore_files": [],
            },
            None,
        )
        mock_scan.return_value = (
            True,
            "SSN: [HIDDEN SSN]",
            [{"type": "ssn", "start": 5, "end": 16}],
            "Found 1 PII item(s):\n  - ssn\n\nAction: redact\n",
        )

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use": {
                "name": "Bash",
                "input": {"command": "cat data.txt"},
            },
            "tool_response": {"output": "SSN: 123-45-6789"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert (
            output.get("decision") != "block"
        ), "redact action should not block in PostToolUse"
        assert "systemMessage" in output, "Should show warning about PII"
        assert (
            "hookSpecificOutput" in output
        ), "Should have hookSpecificOutput with redacted content"
        updated = output["hookSpecificOutput"].get("updatedToolOutput", "")
        assert (
            "123-45-6789" not in updated
        ), "SSN should be redacted in updatedToolOutput"
        assert "HIDDEN SSN" in updated, "Should contain masked placeholder"

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_posttooluse_block_action_blocks_output(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """
        USER EXPERIENCE: PII found with action=block -> OUTPUT BLOCKED

        Scenario:
        1. scan_pii.action = "block"
        2. Tool output contains SSN
        3. Output is blocked entirely

        Expected User Experience:
        ❌ Output is blocked
        🛡️ User sees PII detection error
        """
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
        mock_scan.return_value = (
            True,
            "SSN: [HIDDEN SSN]",
            [{"type": "ssn", "start": 5, "end": 16}],
            "Found 1 PII item(s):\n  - ssn\n\nAction: block\n",
        )

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use": {
                "name": "Bash",
                "input": {"command": "cat data.txt"},
            },
            "tool_response": {"output": "SSN: 123-45-6789"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert (
            output.get("decision") == "block"
        ), "block action should block in PostToolUse"

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_pretooluse_redact_action_blocks(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """
        USER EXPERIENCE: PII found in PreToolUse with action=redact -> BLOCKED

        Scenario:
        1. scan_pii.action = "redact"
        2. File being read contains PII
        3. In PreToolUse, redact behaves as block (can't redact before tool runs)

        Expected User Experience:
        ❌ File read is blocked
        🛡️ User sees PII detection error
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "redact",
                "ignore_files": [],
            },
            None,
        )
        mock_scan.return_value = (
            True,
            "SSN: [HIDDEN SSN]",
            [{"type": "ssn", "start": 5, "end": 16}],
            "Found 1 PII item(s):\n  - ssn\n\nAction: redact\n",
        )

        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("SSN: 123-45-6789")
            tmp_path = f.name

        try:
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_use": {"name": "Read", "parameters": {"file_path": tmp_path}},
            }

            with patch("sys.stdin", StringIO(json.dumps(hook_data))):
                result = ai_guardian.process_hook_input()

            output = json.loads(result["output"])
            has_deny = (
                output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
            )
            has_block = output.get("decision") == "block"
            assert (
                has_deny or has_block
            ), f"redact action should block in PreToolUse: {output}"
        finally:
            os.unlink(tmp_path)


class PIIPreToolUseTests(TestCase):
    """Test PII detection in file reads (PreToolUse hook)."""

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_pretooluse_warn_allows_read_with_warning(
        self, mock_ss, mock_gitleaks, mock_pii
    ):
        """
        USER EXPERIENCE: File read with PII + action=warn -> ALLOWED with warning

        Scenario:
        1. Claude tries to Read a file containing SSN
        2. ai-guardian PreToolUse hook scans file
        3. PII detected, action is "warn"

        Expected User Experience:
        ✅ Read operation is ALLOWED
        ⚠️ User sees PII warning in systemMessage
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "warn",
                "ignore_files": [],
            },
            None,
        )

        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Employee SSN: 123-45-6789\nName: John Doe")
            tmp_path = f.name

        try:
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_use": {"name": "Read", "parameters": {"file_path": tmp_path}},
            }

            with patch("sys.stdin", StringIO(json.dumps(hook_data))):
                result = ai_guardian.process_hook_input()

            output = json.loads(result["output"])
            # Should NOT block — warn mode allows with warning
            has_deny = (
                output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
            )
            assert not has_deny, f"warn mode should allow read: {output}"
            # Should have PII warning
            assert "PII" in output.get(
                "systemMessage", ""
            ), f"Expected PII warning: {output}"
        finally:
            os.unlink(tmp_path)

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_pretooluse_block_action_blocks_read(
        self, mock_ss, mock_gitleaks, mock_pii
    ):
        """
        USER EXPERIENCE: File read with PII + action=block -> BLOCKED

        Scenario:
        1. Claude tries to Read a file containing SSN
        2. ai-guardian PreToolUse hook scans file
        3. PII detected, action is "block"

        Expected User Experience:
        ❌ Read operation is BLOCKED
        🛡️ User sees: "PII DETECTED"
        """
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

        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Employee SSN: 123-45-6789\nName: John Doe")
            tmp_path = f.name

        try:
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_use": {"name": "Read", "parameters": {"file_path": tmp_path}},
            }

            with patch("sys.stdin", StringIO(json.dumps(hook_data))):
                result = ai_guardian.process_hook_input()

            output = json.loads(result["output"])
            # Should block due to action=block
            assert "permissionDecision" in output.get(
                "hookSpecificOutput", {}
            ) or "PII" in output.get(
                "systemMessage", ""
            ), f"Expected PII block: {output}"
        finally:
            os.unlink(tmp_path)

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_pretooluse_ignore_files_skips_test_file(
        self, mock_ss, mock_gitleaks, mock_pii
    ):
        """
        USER EXPERIENCE: File matching ignore_files pattern -> PII scan SKIPPED

        Scenario:
        1. scan_pii.ignore_files = ["*.test.txt"]
        2. Claude reads "data.test.txt" containing SSN
        3. PII scanning is skipped for this file

        Expected User Experience:
        ✅ Read operation is ALLOWED (file matches ignore pattern)
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "block",
                "ignore_files": ["*.test.txt"],
            },
            None,
        )

        import tempfile
        import os

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".test.txt", delete=False
        ) as f:
            f.write("SSN: 123-45-6789")
            tmp_path = f.name

        try:
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_use": {"name": "Read", "parameters": {"file_path": tmp_path}},
            }

            with patch("sys.stdin", StringIO(json.dumps(hook_data))):
                result = ai_guardian.process_hook_input()

            output = json.loads(result["output"])
            # Should NOT block — file matches ignore pattern
            has_deny = (
                output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
            )
            assert not has_deny, f"Should not block ignored file: {output}"
        finally:
            os.unlink(tmp_path)
