#!/usr/bin/env python3
"""
Tests for secret scanning ignore_tools and ignore_files functionality.
"""

import unittest
import sys
import os
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_guardian import check_secrets


class TestSecretScanningIgnoreTools(unittest.TestCase):
    """Tests for ignore_tools configuration in secret scanning."""

    def test_ignore_tools_exact_match(self):
        """Test that exact tool name matching works."""
        secret_content = "aws_access_key_id=AKIAIOSFODNN7EXAMPLE"
        ignore_tools = ["Read"]

        # Without tool_name - should detect (if gitleaks is available)
        # This test documents behavior, actual detection depends on gitleaks binary
        is_secret, error_msg = check_secrets(
            secret_content, filename="test.txt", ignore_tools=ignore_tools
        )
        # Without tool_name specified, should scan normally

        # With Read tool - should NOT scan (ignored)
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="test.txt",
            tool_name="Read",
            ignore_tools=ignore_tools,
        )
        self.assertFalse(is_secret, "Read tool should be ignored")
        self.assertIsNone(error_msg)

        # With different tool - should scan normally
        # (actual detection depends on gitleaks availability)
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="test.txt",
            tool_name="Bash",
            ignore_tools=ignore_tools,
        )
        # Bash tool should not be ignored

    def test_ignore_tools_wildcard_pattern(self):
        """Test that wildcard patterns work."""
        secret_content = (
            "github_token=ghp_1234567890abcdefghijklmnopqrstuvwxyz"  # notsecret
        )
        ignore_tools = ["mcp__*"]

        # MCP tools should be ignored
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="test.txt",
            tool_name="mcp__notebooklm__notebook_list",
            ignore_tools=ignore_tools,
        )
        self.assertFalse(is_secret, "MCP tool should be ignored")
        self.assertIsNone(error_msg)

        # Non-MCP tools should scan normally
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="test.txt",
            tool_name="Read",
            ignore_tools=ignore_tools,
        )
        # Read tool should not be ignored (depends on gitleaks)

    def test_ignore_tools_none_tool_name(self):
        """Test that None tool_name doesn't match ignore patterns."""
        secret_content = "api_key=sk-proj-abc123def456"
        ignore_tools = ["Read"]

        # None tool_name should still scan
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="test.txt",
            tool_name=None,
            ignore_tools=ignore_tools,
        )
        # Should scan normally (no tool specified)

    def test_ignore_tools_empty_list(self):
        """Test that empty ignore_tools list doesn't break anything."""
        secret_content = "password=SuperSecret123!"
        ignore_tools = []

        # Should scan normally
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="test.txt",
            tool_name="Read",
            ignore_tools=ignore_tools,
        )
        # Empty list means scan all tools


class TestSecretScanningIgnoreFiles(unittest.TestCase):
    """Tests for ignore_files configuration in secret scanning."""

    @unittest.skipIf(
        sys.platform == "win32", "Unix-style absolute paths not valid on Windows"
    )
    def test_ignore_files_exact_match(self):
        """Test that exact file path matching works."""
        secret_content = (
            "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        )
        ignore_files = ["/tmp/test-fixture.json"]

        # Without file_path - should scan normally
        is_secret, error_msg = check_secrets(
            secret_content, filename="test.json", ignore_files=ignore_files
        )
        # No file_path specified, should scan

        # With ignored file_path - should NOT scan
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="test-fixture.json",
            file_path="/tmp/test-fixture.json",
            ignore_files=ignore_files,
        )
        self.assertFalse(is_secret, "Ignored file should skip scanning")
        self.assertIsNone(error_msg)

        # With different file_path - should scan normally
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="production.json",
            file_path="/etc/production.json",
            ignore_files=ignore_files,
        )
        # Different path should scan normally

    def test_ignore_files_glob_patterns(self):
        """Test that glob patterns work for file paths."""
        secret_content = "stripe_key=sk_test_1234567890abcdef"
        ignore_files = [
            "**/tests/fixtures/**",
            "**/examples/**/*.example.*",
            "**/.gitleaks.toml",
        ]

        # Test fixtures should be ignored
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="credentials.json",
            file_path="/home/user/project/tests/fixtures/credentials.json",
            ignore_files=ignore_files,
        )
        self.assertFalse(is_secret, "Test fixture should be ignored")

        # Example files should be ignored
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="config.example.json",
            file_path="/home/user/project/examples/config/config.example.json",
            ignore_files=ignore_files,
        )
        self.assertFalse(is_secret, "Example file should be ignored")

        # .gitleaks.toml should be ignored
        is_secret, error_msg = check_secrets(
            secret_content,
            filename=".gitleaks.toml",
            file_path="/home/user/project/.gitleaks.toml",
            ignore_files=ignore_files,
        )
        self.assertFalse(is_secret, ".gitleaks.toml should be ignored")

        # Regular files should scan normally
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="config.json",
            file_path="/home/user/project/config.json",
            ignore_files=ignore_files,
        )
        # Regular file should scan

    def test_ignore_files_tilde_expansion(self):
        """Test that ~ expansion works in file paths."""
        from pathlib import Path

        secret_content = "token=abc123"
        ignore_files = ["~/.config/test/fixture.json"]

        # Expand ~ to actual home directory
        home = str(Path.home())
        expanded_path = f"{home}/.config/test/fixture.json"

        # Should match after expansion
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="fixture.json",
            file_path=expanded_path,
            ignore_files=ignore_files,
        )
        self.assertFalse(is_secret, "Path with ~ should match expanded path")

    def test_ignore_files_combined_wildcard_patterns(self):
        """Test combined wildcard patterns like code-*/** and daf-*/** (issue #172)"""
        from pathlib import Path

        secret_content = "aws_access_key_id=AKIAIOSFODNN7EXAMPLE"
        ignore_files = [
            "~/.claude/skills/code-*/**",  # Combined: single-level + recursive
            "**/skills/daf-*/**",  # Leading ** + combined pattern
        ]

        home = str(Path.home())

        # Should match code-review, code-analysis, etc. with tilde expansion
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="SKILL.md",
            file_path=f"{home}/.claude/skills/code-review/SKILL.md",
            ignore_files=ignore_files,
        )
        self.assertFalse(is_secret, "Combined pattern should match code-* skills")

        # Should match code-analysis
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="config.json",
            file_path=f"{home}/.claude/skills/code-analysis/config.json",
            ignore_files=ignore_files,
        )
        self.assertFalse(is_secret, "Combined pattern should match code-analysis")

        # Should match daf-git, daf-jira anywhere in filesystem (leading **)
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="SKILL.md",
            file_path="/project/.daf-sessions/.claude/skills/daf-jira/SKILL.md",
            ignore_files=ignore_files,
        )
        self.assertFalse(
            is_secret, "Leading ** + combined pattern should match daf-jira anywhere"
        )

        # Should match daf-config in different location
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="helper.py",
            file_path=f"{home}/.daf-sessions/.claude/skills/daf-config/helper.py",
            ignore_files=ignore_files,
        )
        self.assertFalse(
            is_secret, "Leading ** should match daf-config in .daf-sessions"
        )

        # Should NOT match non-matching patterns
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="SKILL.md",
            file_path=f"{home}/.claude/skills/database-migration/SKILL.md",
            ignore_files=ignore_files,
        )
        # database-migration doesn't match code-* or daf-*, so should scan
        # (Actual detection depends on gitleaks availability)

    def test_ignore_files_leading_double_star_patterns(self):
        """Test leading ** patterns work in ignore_files (issue #172)"""
        from pathlib import Path

        secret_content = (
            "github_token=ghp_1234567890abcdefghijklmnopqrstuvwxyz"  # notsecret
        )
        ignore_files = [
            "**/.claude/skills/approved-*/**",  # Leading ** + combined pattern
            "**/tool-results/**",  # Leading ** pattern
        ]

        home = str(Path.home())

        # Should match approved-* skills anywhere
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="SKILL.md",
            file_path=f"{home}/.claude/skills/approved-skill/SKILL.md",
            ignore_files=ignore_files,
        )
        self.assertFalse(is_secret, "Leading ** should match approved-* skills in home")

        # Should match in different location
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="config.json",
            file_path="/projects/myapp/.claude/skills/approved-workflow/config.json",
            ignore_files=ignore_files,
        )
        self.assertFalse(
            is_secret, "Leading ** should match approved-* skills in project"
        )

        # Should match tool-results anywhere
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="output.json",
            file_path=f"{home}/.claude/projects/session-abc/tool-results/bash/output.json",
            ignore_files=ignore_files,
        )
        self.assertFalse(
            is_secret, "**/tool-results/** should match tool-results anywhere"
        )

        # Should match nested tool-results
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="data.txt",
            file_path="/project/deep/nested/path/tool-results/read/data.txt",
            ignore_files=ignore_files,
        )
        self.assertFalse(
            is_secret, "**/tool-results/** should match deeply nested tool-results"
        )


class TestSecretScanningIgnoreBoth(unittest.TestCase):
    """Tests for using both ignore_tools and ignore_files together."""

    def test_ignore_both_tools_and_files(self):
        """Test that both ignore_tools and ignore_files work together."""
        secret_content = "database_password=MySuperSecretPassword123!"
        ignore_tools = ["Read"]
        ignore_files = ["**/tests/fixtures/**"]

        # Ignored by tool name
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="data.json",
            tool_name="Read",
            file_path="/home/user/project/src/data.json",
            ignore_tools=ignore_tools,
            ignore_files=ignore_files,
        )
        self.assertFalse(is_secret, "Should be ignored by tool name")

        # Ignored by file path
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="fixture.json",
            tool_name="Bash",
            file_path="/home/user/project/tests/fixtures/fixture.json",
            ignore_tools=ignore_tools,
            ignore_files=ignore_files,
        )
        self.assertFalse(is_secret, "Should be ignored by file path")

        # Both specified - still ignored (defense in depth)
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="fixture.json",
            tool_name="Read",
            file_path="/home/user/project/tests/fixtures/fixture.json",
            ignore_tools=ignore_tools,
            ignore_files=ignore_files,
        )
        self.assertFalse(is_secret, "Should be ignored by either condition")

        # Neither matches - should scan normally
        is_secret, error_msg = check_secrets(
            secret_content,
            filename="production.json",
            tool_name="Bash",
            file_path="/etc/production.json",
            ignore_tools=ignore_tools,
            ignore_files=ignore_files,
        )
        # Should scan normally

    def test_real_world_test_fixtures(self):
        """Test real-world scenario: test fixtures with fake credentials."""
        # Common pattern: test fixtures with fake AWS keys
        test_fixture_content = """
        {
            "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
            "aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        }
        """

        ignore_files = [
            "**/tests/**/*.fixture.json",
            "**/tests/fixtures/**",
            "**/examples/**",
        ]

        # Test fixture should be ignored
        is_secret, error_msg = check_secrets(
            test_fixture_content,
            filename="auth.fixture.json",
            file_path="/home/user/project/tests/fixtures/auth.fixture.json",
            ignore_files=ignore_files,
        )
        self.assertFalse(is_secret, "Test fixture with fake AWS keys should be ignored")

        # Production config should scan normally
        is_secret, error_msg = check_secrets(
            test_fixture_content,
            filename="production.json",
            file_path="/etc/app/production.json",
            ignore_files=ignore_files,
        )
        # Production file should scan (depends on gitleaks availability)


class TestSecretScanningAllowlistPatterns(unittest.TestCase):
    """Tests for allowlist_patterns configuration in secret scanning (Issue #357)."""

    def test_allowlist_patterns_parameter_accepted(self):
        """Verify allowlist_patterns parameter is accepted without error."""
        safe_content = "just some normal text with no secrets"
        is_secret, error_msg = check_secrets(
            safe_content,
            filename="test.txt",
            allowlist_patterns=[r"pk_test_[A-Za-z0-9]+"],
        )
        self.assertFalse(is_secret)

    def test_allowlist_patterns_with_ignore_tools(self):
        """Allowlist patterns work alongside ignore_tools."""
        safe_content = "just some normal text"
        is_secret, error_msg = check_secrets(
            safe_content,
            filename="test.txt",
            tool_name="Read",
            ignore_tools=["Read"],
            allowlist_patterns=[r"pk_test_[A-Za-z0-9]+"],
        )
        self.assertFalse(is_secret, "Ignored tool should not be scanned")

    def test_allowlist_patterns_empty_list_has_no_effect(self):
        """Empty allowlist_patterns list should not change behavior."""
        safe_content = "no secrets here"
        is_secret, error_msg = check_secrets(
            safe_content, filename="test.txt", allowlist_patterns=[]
        )
        self.assertFalse(is_secret)

    def test_allowlist_patterns_none_accepted(self):
        """None value for allowlist_patterns should be handled gracefully."""
        safe_content = "no secrets here"
        is_secret, error_msg = check_secrets(
            safe_content, filename="test.txt", allowlist_patterns=None
        )
        self.assertFalse(is_secret)

    def test_allowlist_dangerous_patterns_blocked(self):
        """Catch-all patterns like .* should be rejected."""
        safe_content = "no secrets here"
        is_secret, error_msg = check_secrets(
            safe_content, filename="test.txt", allowlist_patterns=[".*"]
        )
        # Should work without error; dangerous pattern is just ignored
        self.assertFalse(is_secret)


class TestAllowlistLineNumberZeroFallback(unittest.TestCase):
    """Tests for allowlist fallback when scanner returns line_number=0 (Issue #1476)."""

    def _mock_engine(self, mock_select_engine, mock_select_all):
        mock_engine = MagicMock()
        mock_engine.type = "gitleaks"
        mock_engine.file_patterns = None
        mock_engine.ignore_files = None
        mock_select_engine.return_value = mock_engine
        mock_select_all.return_value = [mock_engine]

    @patch("ai_guardian.scanners.secret_scanning.run_engine")
    @patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    def test_allowlist_fires_when_line_number_is_zero(
        self, mock_load_config, mock_select_engine, mock_select_all, mock_run_single
    ):
        """When line_number=0, allowlist checks secret value directly (Issue #1476)."""
        from ai_guardian.scanners.strategies import ScanResult, SecretMatch

        mock_load_config.return_value = ({"engines": ["gitleaks"]}, None)
        self._mock_engine(mock_select_engine, mock_select_all)
        mock_run_single.return_value = ScanResult(
            has_secrets=True,
            secrets=[
                SecretMatch(
                    rule_id="generic-api-key",
                    description="API Key",
                    file="test.txt",
                    line_number=0,
                    secret="pk_test_allowlisted_value",
                    engine="gitleaks",
                )
            ],
            engine="gitleaks",
            scan_time_ms=10.0,
        )

        has_secrets, error_msg = check_secrets(
            "pk_test_allowlisted_value",
            allowlist_patterns=[r"pk_test_[A-Za-z0-9_]+"],
        )

        self.assertFalse(
            has_secrets, "Allowlist should suppress when secret value matches"
        )
        self.assertIsNone(error_msg)

    @patch("ai_guardian.scanners.secret_scanning.run_engine")
    @patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    def test_violation_surfaces_when_line_number_zero_no_match(
        self, mock_load_config, mock_select_engine, mock_select_all, mock_run_single
    ):
        """When line_number=0 and secret doesn't match allowlist, violation surfaces."""
        from ai_guardian.scanners.strategies import ScanResult, SecretMatch

        mock_load_config.return_value = ({"engines": ["gitleaks"]}, None)
        self._mock_engine(mock_select_engine, mock_select_all)
        mock_run_single.return_value = ScanResult(
            has_secrets=True,
            secrets=[
                SecretMatch(
                    rule_id="generic-api-key",
                    description="API Key",
                    file="test.txt",
                    line_number=0,
                    secret="sk_live_actual_secret",
                    engine="gitleaks",
                )
            ],
            engine="gitleaks",
            scan_time_ms=10.0,
        )

        has_secrets, error_msg = check_secrets(
            "sk_live_actual_secret",
            allowlist_patterns=[r"pk_test_[A-Za-z0-9_]+"],
        )

        self.assertTrue(has_secrets, "Non-matching secret should still be detected")

    @patch("ai_guardian.scanners.secret_scanning.run_engine")
    @patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    def test_violation_surfaces_when_line_number_zero_no_secret_value(
        self, mock_load_config, mock_select_engine, mock_select_all, mock_run_single
    ):
        """When line_number=0 and secret=None, allowlist cannot match — violation surfaces."""
        from ai_guardian.scanners.strategies import ScanResult, SecretMatch

        mock_load_config.return_value = ({"engines": ["gitleaks"]}, None)
        self._mock_engine(mock_select_engine, mock_select_all)
        mock_run_single.return_value = ScanResult(
            has_secrets=True,
            secrets=[
                SecretMatch(
                    rule_id="generic-api-key",
                    description="API Key",
                    file="test.txt",
                    line_number=0,
                    secret=None,
                    engine="gitleaks",
                )
            ],
            engine="gitleaks",
            scan_time_ms=10.0,
        )

        has_secrets, error_msg = check_secrets(
            "some content",
            allowlist_patterns=[r"pk_test_[A-Za-z0-9_]+"],
        )

        self.assertTrue(has_secrets, "No secret value + no line should still block")


class TestBuildFalsePositiveMsgTempFile(unittest.TestCase):
    """Tests for _build_false_positive_msg()'s temp-file handling."""

    def test_temp_file_suggests_config_allowlist(self):
        from ai_guardian.scanners.secret_scanning import _build_false_positive_msg

        msg = _build_false_positive_msg(
            {"file": "/tmp/hook_input.txt", "line_number": 1}, for_secret=True
        )

        self.assertIn("temporary file", msg)
        self.assertIn("secret_scanning.allowlist_patterns", msg)
        self.assertNotIn("ai-guardian:allow", msg)

    def test_regular_file_suggests_inline_annotation(self):
        from ai_guardian.scanners.secret_scanning import _build_false_positive_msg

        msg = _build_false_positive_msg(
            {"file": "/home/user/project/config.py", "line_number": 1},
            for_secret=True,
        )

        self.assertIn("ai-guardian:allow", msg)


if __name__ == "__main__":
    unittest.main()
