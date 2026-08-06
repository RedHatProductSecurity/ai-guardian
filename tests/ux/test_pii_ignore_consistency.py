"""
Tests for PII ignore_files and ignore_tools consistency across hooks (Issue #355).

Verifies that:
- PostToolUse PII scanning respects ignore_tools
- PostToolUse PII scanning respects ignore_files
- PreToolUse PII scanning respects ignore_tools (new)
- No regressions: PII is still detected when no ignore patterns match
"""

import json
import os
import tempfile
from io import StringIO
from unittest import TestCase
from unittest.mock import patch

import ai_guardian


class PIIPostToolUseIgnoreToolsTests(TestCase):
    """Test that PostToolUse PII scanning respects ignore_tools (Issue #355)."""

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_posttooluse_pii_ignored_tool_skips_scan(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """
        USER EXPERIENCE: Tool in ignore_tools list -> PII scan SKIPPED

        Scenario:
        1. scan_pii.ignore_tools = ["Bash"]
        2. Bash tool output contains SSN
        3. PII scanning is skipped because tool matches ignore pattern

        Expected User Experience:
        ✅ Output is returned (not blocked)
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "block",
                "ignore_files": [],
                "ignore_tools": ["Bash"],
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
        assert output.get("decision") != "block", "Ignored tool should not be blocked"
        mock_scan.assert_not_called()

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_posttooluse_pii_wildcard_ignore_tools(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """
        USER EXPERIENCE: Tool matches wildcard ignore_tools pattern -> PII scan SKIPPED

        Scenario:
        1. scan_pii.ignore_tools = ["mcp__*"]
        2. MCP tool output contains credit card
        3. PII scanning is skipped because tool matches wildcard pattern

        Expected User Experience:
        ✅ Output is returned (not blocked)
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["credit_card"],
                "action": "block",
                "ignore_files": [],
                "ignore_tools": ["mcp__*"],
            },
            None,
        )

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use": {
                "name": "mcp__notebooklm__notebook_query",
                "input": {},
            },
            "tool_response": {"output": "Card: 4532015112830366"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert (
            output.get("decision") != "block"
        ), "Wildcard-ignored tool should not be blocked"
        mock_scan.assert_not_called()

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_posttooluse_pii_non_matching_tool_still_scans(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """
        USER EXPERIENCE: Tool NOT in ignore_tools list -> PII scan runs normally

        Scenario:
        1. scan_pii.ignore_tools = ["Bash"]
        2. Read tool output contains SSN
        3. PII scanning runs because Read is not in ignore_tools

        Expected User Experience:
        ❌ Output is blocked (PII detected)
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "block",
                "ignore_files": [],
                "ignore_tools": ["Bash"],
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
                "name": "Read",
                "input": {"file_path": "/tmp/data.txt"},
            },
            "tool_response": {"output": "SSN: 123-45-6789"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        mock_scan.assert_called_once()


class PIIPostToolUseIgnoreFilesTests(TestCase):
    """Test that PostToolUse PII scanning respects ignore_files (Issue #355)."""

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_posttooluse_pii_ignored_file_skips_scan(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """
        USER EXPERIENCE: File matching ignore_files in PostToolUse -> PII scan SKIPPED

        Scenario:
        1. scan_pii.ignore_files = ["*.test.txt"]
        2. Read tool reads "data.test.txt" containing SSN
        3. PostToolUse PII scanning is skipped because file matches ignore pattern

        Expected User Experience:
        ✅ Output is returned (not blocked)
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "block",
                "ignore_files": ["*.test.txt"],
                "ignore_tools": [],
            },
            None,
        )

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use": {
                "name": "Read",
                "input": {"file_path": "/tmp/data.test.txt"},
            },
            "tool_response": {"output": "SSN: 123-45-6789"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert (
            output.get("decision") != "block"
        ), "Ignored file should not be blocked in PostToolUse"
        mock_scan.assert_not_called()

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_posttooluse_pii_non_matching_file_still_scans(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """
        USER EXPERIENCE: File NOT matching ignore_files -> PII scan runs

        Scenario:
        1. scan_pii.ignore_files = ["*.test.txt"]
        2. Read tool reads "production.txt" containing SSN
        3. PII scanning runs because file doesn't match ignore pattern

        Expected User Experience:
        ❌ Output is blocked (PII detected)
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "block",
                "ignore_files": ["*.test.txt"],
                "ignore_tools": [],
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
                "name": "Read",
                "input": {"file_path": "/tmp/production.txt"},
            },
            "tool_response": {"output": "SSN: 123-45-6789"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        mock_scan.assert_called_once()


class PIIPreToolUseIgnoreToolsTests(TestCase):
    """Test that PreToolUse PII scanning respects ignore_tools (Issue #355)."""

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_pretooluse_pii_ignored_tool_skips_scan(
        self, mock_ss, mock_gitleaks, mock_pii
    ):
        """
        USER EXPERIENCE: Tool in ignore_tools list -> PII scan SKIPPED on PreToolUse

        Scenario:
        1. scan_pii.ignore_tools = ["Read"]
        2. Claude reads a file containing SSN via Read tool
        3. PII scanning is skipped because Read is in ignore_tools

        Expected User Experience:
        ✅ Read operation is ALLOWED
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "block",
                "ignore_files": [],
                "ignore_tools": ["Read"],
            },
            None,
        )

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
            assert not has_deny, f"Ignored tool should not block: {output}"
        finally:
            os.unlink(tmp_path)

    @patch("ai_guardian.hook_processing._load_permissions_config")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_pretooluse_pii_skill_composite_ignored(
        self, mock_ss, mock_gitleaks, mock_pii, mock_perms
    ):
        """
        USER EXPERIENCE: Skill:* wildcard in ignore_tools -> PII scan SKIPPED

        Scenario:
        1. scan_pii.ignore_tools = ["Skill:*"]
        2. Claude runs a Skill whose input contains PII-like text
        3. PII scanning is skipped because Skill:code-review matches Skill:*

        Expected User Experience:
        ✅ Skill execution is ALLOWED
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "block",
                "ignore_files": [],
                "ignore_tools": ["Skill:*"],
            },
            None,
        )
        mock_perms.return_value = ({"enabled": False}, None)

        hook_data = {
            "hook_event_name": "PreToolUse",
            "tool_use": {
                "name": "Skill",
                "parameters": {"skill": "code-review"},
                "input": {"skill": "code-review", "args": "SSN: 123-45-6789"},
            },
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        has_deny = (
            output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        )
        assert not has_deny, f"Skill:* should skip PII scan: {output}"


class PIIIgnoreRegressionTests(TestCase):
    """Regression tests: PII detection still works with empty ignore lists."""

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_no_ignore_patterns_still_detects_pii(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """
        USER EXPERIENCE: Empty ignore lists -> PII still detected and blocked

        Scenario:
        1. scan_pii.ignore_tools = [], scan_pii.ignore_files = []
        2. Tool output contains SSN
        3. PII scanning runs normally

        Expected User Experience:
        ❌ Output is blocked (PII detected)
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "block",
                "ignore_files": [],
                "ignore_tools": [],
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
                "name": "Read",
                "input": {"file_path": "/tmp/data.txt"},
            },
            "tool_response": {"output": "SSN: 123-45-6789"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        mock_scan.assert_called_once()
        is_blocked = (
            output.get("decision") == "block"
            or output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        )
        assert is_blocked, f"PII should be blocked with empty ignore lists: {output}"

    @patch("ai_guardian.hook_processing._scan_for_pii")
    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_posttooluse_both_ignore_tools_and_files(
        self, mock_ss, mock_gitleaks, mock_pii, mock_scan
    ):
        """
        USER EXPERIENCE: Either ignore_tools or ignore_files match -> PII scan SKIPPED

        Scenario:
        1. scan_pii.ignore_tools = ["Read"], scan_pii.ignore_files = ["*.test.txt"]
        2. Read tool reads a non-test file
        3. PII scan is skipped because tool matches ignore_tools (even if file doesn't match ignore_files)

        Expected User Experience:
        ✅ Output is returned (not blocked)
        """
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["ssn"],
                "action": "block",
                "ignore_files": ["*.test.txt"],
                "ignore_tools": ["Read"],
            },
            None,
        )

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use": {
                "name": "Read",
                "input": {"file_path": "/tmp/production.txt"},
            },
            "tool_response": {"output": "SSN: 123-45-6789"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert (
            output.get("decision") != "block"
        ), "Tool in ignore_tools should skip PII scan"
        mock_scan.assert_not_called()
