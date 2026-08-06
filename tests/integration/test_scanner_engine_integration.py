#!/usr/bin/env python3
"""
Tests for scanner engine integration in secret scanning.

Tests the integration of flexible scanner engines with the main scanning flow.
"""

import unittest
import sys
import os
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_guardian import check_secrets


class TestScannerEngineIntegration(unittest.TestCase):
    """Tests for scanner engine integration."""

    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_scanner_not_found_warns(self, mock_load_config, mock_select_engine):
        """Test that missing scanner warns instead of blocking (Issue #343)."""
        # Mock configuration with leaktk
        mock_load_config.return_value = ({"engines": ["leaktk"]}, None)

        # Mock select_engine to raise RuntimeError (no scanner found)
        mock_select_engine.side_effect = RuntimeError(
            "No secret scanner found. Install one of:\n"
            "  • Gitleaks: brew install gitleaks\n"
            "  • BetterLeaks: brew install betterleaks\n"
            "  • LeakTK: brew install leaktk/tap/leaktk"
        )

        # Should return warning (not blocking)
        has_secrets, error_msg = check_secrets(
            "aws_key=AKIAIOSFODNN7EXAMPLE", filename="test.txt"
        )

        # Verify it warns but does NOT block
        self.assertFalse(
            has_secrets, "Should NOT block when scanner not found (Issue #343)"
        )
        self.assertIsNotNone(error_msg, "Warning message should be returned")
        self.assertIn("WARNING", error_msg, "Should indicate warning")
        self.assertIn(
            "ai-guardian scanner install leaktk",
            error_msg,
            "Should suggest installing configured scanner",
        )
        self.assertIn("you may leak secrets", error_msg, "Should warn about risk")
        # Issue #384: Context-aware message
        self.assertIn(
            "No secret scanning available", error_msg, "Should use context-aware title"
        )
        self.assertIn("['leaktk']", error_msg, "Should list tried engines")

    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @patch("ai_guardian.scanners.secret_scanning.run_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_scanner_engine_used_when_available(
        self, mock_load_config, mock_run_single, mock_select_all, mock_select_engine
    ):
        """Test that configured scanner engine is used when available."""
        from ai_guardian.scanners.strategies import ScanResult

        # Mock configuration with betterleaks
        mock_load_config.return_value = ({"engines": ["betterleaks", "gitleaks"]}, None)

        # Mock engine selection
        mock_engine = MagicMock()
        mock_engine.type = "betterleaks"
        mock_engine.file_patterns = None
        mock_engine.ignore_files = None
        mock_select_engine.return_value = mock_engine
        mock_select_all.return_value = [mock_engine]

        # Mock single engine run (no secrets)
        mock_run_single.return_value = ScanResult(
            has_secrets=False, secrets=[], engine="betterleaks", scan_time_ms=10.0
        )

        # Run scan
        has_secrets, error_msg = check_secrets(
            "clean content", filename="test.txt"
        )

        # Verify select_all_engines was called (strategy framework + first-match prep)
        self.assertTrue(mock_select_all.called)

        # Verify no secrets found
        self.assertFalse(has_secrets)
        self.assertIsNone(error_msg)

    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", False)
    @patch("ai_guardian.scanners.secret_scanning.subprocess.run")
    def test_legacy_fallback_when_scanner_engine_unavailable(self, mock_run):
        """Test that legacy gitleaks is used when scanner engine module unavailable."""
        # Mock gitleaks run (no secrets)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        # Run scan
        has_secrets, error_msg = check_secrets(
            "clean content", filename="test.txt"
        )

        # Verify gitleaks command was used (legacy fallback)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "gitleaks")

        # Verify no secrets found
        self.assertFalse(has_secrets)
        self.assertIsNone(error_msg)

    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_unexpected_error_fails_open(self, mock_load_config, mock_select_engine):
        """Test that unexpected errors fail open (allow operation)."""
        # Mock configuration
        mock_load_config.return_value = ({"engines": ["gitleaks"]}, None)

        # Mock select_engine to raise unexpected error
        mock_select_engine.side_effect = Exception("Unexpected error")

        # Should fail open
        has_secrets, error_msg = check_secrets(
            "some content", filename="test.txt"
        )

        # Verify it fails open (allows operation)
        self.assertFalse(has_secrets, "Should fail open on unexpected errors")
        self.assertIsNone(error_msg)

    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @patch("ai_guardian.scanners.secret_scanning.run_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_gitleaks_exit_code_1_not_treated_as_success(
        self, mock_load_config, mock_run_single, mock_select_all, mock_select_engine
    ):
        """Exit code 1 from gitleaks with findings must block (Issue #411).

        Gitleaks exit code 1 is its default 'secrets found' code when --exit-code
        is not specified or not honored. When actual findings exist in the report,
        the operation must be blocked.
        """
        from ai_guardian.scanners.strategies import ScanResult, SecretMatch

        mock_load_config.return_value = ({"engines": ["gitleaks"]}, None)

        mock_engine = MagicMock()
        mock_engine.type = "gitleaks"
        mock_engine.file_patterns = None
        mock_engine.ignore_files = None
        mock_select_engine.return_value = mock_engine
        mock_select_all.return_value = [mock_engine]

        # Mock run_single_engine to return secrets found
        mock_run_single.return_value = ScanResult(
            has_secrets=True,
            secrets=[
                SecretMatch(
                    rule_id="generic-api-key",
                    description="API Key",
                    file="test.txt",
                    line_number=1,
                    engine="gitleaks",
                )
            ],
            engine="gitleaks",
            scan_time_ms=10.0,
        )

        has_secrets, error_msg = check_secrets(
            "AWS_ACCESS_KEY=AKIAIOSFODNN7TESTKEY", filename="test.txt"  # notsecret
        )

        self.assertTrue(
            has_secrets,
            "Exit code 1 from gitleaks must mean secrets found, not success (Issue #411)",
        )
        self.assertIsNotNone(error_msg)

    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @patch("ai_guardian.scanners.secret_scanning.run_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_gitleaks_exit_code_42_blocks_operation(
        self, mock_load_config, mock_run_single, mock_select_all, mock_select_engine
    ):
        """Exit code 42 (custom) from gitleaks must be treated as secrets found."""
        from ai_guardian.scanners.strategies import ScanResult, SecretMatch

        mock_load_config.return_value = ({"engines": ["gitleaks"]}, None)

        mock_engine = MagicMock()
        mock_engine.type = "gitleaks"
        mock_engine.file_patterns = None
        mock_engine.ignore_files = None
        mock_select_engine.return_value = mock_engine
        mock_select_all.return_value = [mock_engine]

        # Mock run_single_engine to return secrets found
        mock_run_single.return_value = ScanResult(
            has_secrets=True,
            secrets=[
                SecretMatch(
                    rule_id="aws-access-token",
                    description="AWS Key",
                    file="test.txt",
                    line_number=1,
                    engine="gitleaks",
                )
            ],
            engine="gitleaks",
            scan_time_ms=10.0,
        )

        has_secrets, error_msg = check_secrets(
            "AWS_ACCESS_KEY=AKIAIOSFODNN7TESTKEY", filename="test.txt"  # notsecret
        )

        self.assertTrue(
            has_secrets, "Exit code 42 from gitleaks must block the operation"
        )
        self.assertIsNotNone(error_msg)
        self.assertIn("Secret Detected", error_msg)

    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning.build_scanner_command")
    @patch("ai_guardian.scanners.secret_scanning.get_parser")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    @patch("ai_guardian.scanners.secret_scanning.subprocess.run")
    def test_gitleaks_exit_code_0_allows_operation(
        self,
        mock_run,
        mock_load_config,
        mock_get_parser,
        mock_build_command,
        mock_select_engine,
    ):
        """Exit code 0 from gitleaks means no secrets found — allow operation."""
        mock_load_config.return_value = ({"engines": ["gitleaks"]}, None)

        mock_engine = MagicMock()
        mock_engine.type = "gitleaks"
        mock_engine.output_parser = "gitleaks"
        mock_engine.secrets_found_exit_code = 42
        mock_engine.success_exit_code = 0
        mock_select_engine.return_value = mock_engine

        mock_build_command.return_value = ["gitleaks", "detect", "..."]

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        mock_parser = MagicMock()
        mock_parser.parse.return_value = {
            "has_secrets": False,
            "findings": [],
            "total_findings": 0,
        }
        mock_get_parser.return_value = mock_parser

        has_secrets, error_msg = check_secrets(
            "clean content without secrets", filename="test.txt"
        )

        self.assertFalse(has_secrets, "Exit code 0 should allow the operation")
        self.assertIsNone(error_msg)

    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @patch("ai_guardian.scanners.secret_scanning.run_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_betterleaks_exit_code_1_not_treated_as_success(
        self, mock_load_config, mock_run_single, mock_select_all, mock_select_engine
    ):
        """Exit code 1 from betterleaks with findings must block (Issue #411)."""
        from ai_guardian.scanners.strategies import ScanResult, SecretMatch

        mock_load_config.return_value = ({"engines": ["betterleaks"]}, None)

        mock_engine = MagicMock()
        mock_engine.type = "betterleaks"
        mock_engine.file_patterns = None
        mock_engine.ignore_files = None
        mock_select_engine.return_value = mock_engine
        mock_select_all.return_value = [mock_engine]

        # Mock run_single_engine to return secrets found
        mock_run_single.return_value = ScanResult(
            has_secrets=True,
            secrets=[
                SecretMatch(
                    rule_id="generic-api-key",
                    description="Key",
                    file="test.txt",
                    line_number=1,
                    engine="betterleaks",
                )
            ],
            engine="betterleaks",
            scan_time_ms=10.0,
        )

        has_secrets, error_msg = check_secrets(
            "AWS_ACCESS_KEY=AKIAIOSFODNN7TESTKEY", filename="test.txt"  # notsecret
        )

        self.assertTrue(
            has_secrets,
            "Exit code 1 from betterleaks must mean secrets found (Issue #411)",
        )
        self.assertIsNotNone(error_msg)


class TestGuardClauseFallthrough(unittest.TestCase):
    """Tests for Issue #538: guard clause must fall through to remaining engines.

    The guard clause path is only reached when a pattern server sets
    gitleaks_config_path, which forces the code through the single-engine
    subprocess path (not the multi-engine strategy framework).
    """

    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    @patch("ai_guardian.scanners.secret_scanning.HAS_PATTERN_SERVER", True)
    @patch("ai_guardian.scanners.secret_scanning.PatternServerClient")
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    @patch("ai_guardian.scanners.secret_scanning.resolve_engine_config_path")
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @patch("ai_guardian.scanners.secret_scanning.run_engine")
    @patch("ai_guardian.scanners.secret_scanning.build_scanner_command")
    @patch("ai_guardian.scanners.secret_scanning.get_parser")
    @patch("ai_guardian.scanners.secret_scanning.subprocess.run")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_guard_clause_falls_through_to_gitleaks(
        self,
        mock_load_config,
        mock_subprocess,
        mock_get_parser,
        mock_build_cmd,
        mock_run_single,
        mock_select_all,
        mock_select_engine,
        mock_resolve_config,
        mock_pattern_config,
        mock_pattern_client_cls,
    ):
        """Guard clause (empty findings) must try remaining engines, not return immediately.

        Scenario: pattern server provides config, betterleaks exits 1 with no
        findings (incompatible config), guard clause should fall through and
        gitleaks should detect the secret.
        """
        from ai_guardian.scanners.strategies import ScanResult, SecretMatch

        mock_pattern_config.return_value = {
            "url": "https://example.com/patterns",
            "version": "1.0",
        }
        mock_client = MagicMock()
        mock_client.get_patterns_path.return_value = "/tmp/pattern_server.toml"
        mock_pattern_client_cls.return_value = mock_client

        mock_load_config.return_value = (
            {
                "engines": ["betterleaks", "gitleaks"],
                "execution_strategy": "first-match",
            },
            None,
        )

        mock_bl_engine = MagicMock()
        mock_bl_engine.type = "betterleaks"
        mock_bl_engine.file_patterns = None
        mock_bl_engine.ignore_files = None
        mock_bl_engine.output_parser = "gitleaks"
        mock_bl_engine.secrets_found_exit_code = 42
        mock_bl_engine.success_exit_code = 0

        mock_gl_engine = MagicMock()
        mock_gl_engine.type = "gitleaks"
        mock_gl_engine.file_patterns = None
        mock_gl_engine.ignore_files = None

        mock_select_engine.return_value = mock_bl_engine
        mock_select_all.return_value = [mock_bl_engine, mock_gl_engine]
        mock_resolve_config.return_value = "/tmp/pattern_server.toml"
        mock_build_cmd.return_value = ["betterleaks", "detect", "..."]

        mock_subprocess.return_value = MagicMock(
            returncode=1, stderr="FTL failed to compile CEL filters"
        )

        mock_parser = MagicMock()
        mock_parser.parse.return_value = {
            "has_secrets": False,
            "findings": [],
            "total_findings": 0,
        }
        mock_get_parser.return_value = mock_parser

        mock_run_single.return_value = ScanResult(
            has_secrets=True,
            secrets=[
                SecretMatch(
                    rule_id="private-key",
                    description="Private Key",
                    file="test.txt",
                    line_number=1,
                    engine="gitleaks",
                )
            ],
            engine="gitleaks",
            scan_time_ms=15.0,
        )

        has_secrets, error_msg = check_secrets(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----",
            filename="test.txt",
        )

        self.assertTrue(
            has_secrets,
            "Gitleaks should catch the secret via guard clause fallthrough (Issue #538)",
        )
        self.assertIn("Secret Detected", error_msg)
        self.assertIn("first-match fallthrough", error_msg)
        mock_run_single.assert_called()

    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    @patch("ai_guardian.scanners.secret_scanning.HAS_PATTERN_SERVER", True)
    @patch("ai_guardian.scanners.secret_scanning.PatternServerClient")
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    @patch("ai_guardian.scanners.secret_scanning.resolve_engine_config_path")
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @patch("ai_guardian.scanners.secret_scanning.run_engine")
    @patch("ai_guardian.scanners.secret_scanning.build_scanner_command")
    @patch("ai_guardian.scanners.secret_scanning.get_parser")
    @patch("ai_guardian.scanners.secret_scanning.subprocess.run")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_guard_clause_returns_clean_when_no_remaining_engines(
        self,
        mock_load_config,
        mock_subprocess,
        mock_get_parser,
        mock_build_cmd,
        mock_run_single,
        mock_select_all,
        mock_select_engine,
        mock_resolve_config,
        mock_pattern_config,
        mock_pattern_client_cls,
    ):
        """Guard clause with single engine returns clean (no fallthrough possible)."""
        mock_pattern_config.return_value = {
            "url": "https://example.com/patterns",
            "version": "1.0",
        }
        mock_client = MagicMock()
        mock_client.get_patterns_path.return_value = "/tmp/pattern_server.toml"
        mock_pattern_client_cls.return_value = mock_client

        mock_load_config.return_value = (
            {"engines": ["betterleaks"], "execution_strategy": "first-match"},
            None,
        )

        mock_bl_engine = MagicMock()
        mock_bl_engine.type = "betterleaks"
        mock_bl_engine.file_patterns = None
        mock_bl_engine.ignore_files = None
        mock_bl_engine.output_parser = "gitleaks"
        mock_bl_engine.secrets_found_exit_code = 42
        mock_bl_engine.success_exit_code = 0

        mock_select_engine.return_value = mock_bl_engine
        mock_select_all.return_value = [mock_bl_engine]
        mock_resolve_config.return_value = "/tmp/pattern_server.toml"
        mock_build_cmd.return_value = ["betterleaks", "detect", "..."]

        mock_subprocess.return_value = MagicMock(
            returncode=1, stderr="FTL failed to compile CEL filters"
        )

        mock_parser = MagicMock()
        mock_parser.parse.return_value = {
            "has_secrets": False,
            "findings": [],
            "total_findings": 0,
        }
        mock_get_parser.return_value = mock_parser

        has_secrets, error_msg = check_secrets(
            "clean content", filename="test.txt"
        )

        self.assertFalse(
            has_secrets, "Single engine with no findings should return clean"
        )
        self.assertIsNone(error_msg)
        mock_run_single.assert_not_called()

    @patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True)
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @patch("ai_guardian.scanners.secret_scanning.run_engine")
    @patch("ai_guardian.scanners.secret_scanning.build_scanner_command")
    @patch("ai_guardian.scanners.secret_scanning.get_parser")
    @patch("ai_guardian.scanners.secret_scanning.subprocess.run")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_fallthrough_uses_none_config_path(
        self,
        mock_load_config,
        mock_subprocess,
        mock_get_parser,
        mock_build_cmd,
        mock_run_single,
        mock_select_all,
        mock_select_engine,
        mock_pattern_config,
    ):
        """Fallthrough engines must use config_path=None (their own default rules).

        When no pattern server is configured, the code enters the multi-engine
        strategy path. The strategy framework's fallthrough must also pass
        config_path=None.
        """
        from ai_guardian.scanners.strategies import ScanResult, SecretMatch

        mock_pattern_config.return_value = None
        mock_load_config.return_value = (
            {
                "engines": ["betterleaks", "gitleaks"],
                "execution_strategy": "first-match",
            },
            None,
        )

        mock_bl_engine = MagicMock()
        mock_bl_engine.type = "betterleaks"
        mock_bl_engine.file_patterns = None
        mock_bl_engine.ignore_files = None
        mock_bl_engine.output_parser = "gitleaks"
        mock_bl_engine.secrets_found_exit_code = 42
        mock_bl_engine.success_exit_code = 0

        mock_gl_engine = MagicMock()
        mock_gl_engine.type = "gitleaks"
        mock_gl_engine.file_patterns = None
        mock_gl_engine.ignore_files = None

        mock_select_engine.return_value = mock_bl_engine
        mock_select_all.return_value = [mock_bl_engine, mock_gl_engine]

        config_paths_received = []

        def tracking_run_single(
            engine_config, source_file, report_file, config_path=None, **kwargs
        ):
            config_paths_received.append(config_path)
            if engine_config.type == "gitleaks":
                return ScanResult(
                    has_secrets=True,
                    secrets=[
                        SecretMatch(
                            rule_id="private-key",
                            description="Private Key",
                            file="test.txt",
                            line_number=1,
                            engine="gitleaks",
                        )
                    ],
                    engine="gitleaks",
                    scan_time_ms=15.0,
                )
            return ScanResult(
                has_secrets=False, secrets=[], engine="betterleaks", scan_time_ms=10.0
            )

        mock_run_single.side_effect = tracking_run_single

        has_secrets, error_msg = check_secrets(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----",
            filename="test.txt",
        )

        self.assertTrue(has_secrets)
        for cp in config_paths_received:
            self.assertIsNone(
                cp, f"Engine received config_path={cp}, expected None (Issue #538)"
            )


if __name__ == "__main__":
    unittest.main()
