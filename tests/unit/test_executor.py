"""Tests for scanner executor module."""

import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from ai_guardian.scanners.executor import run_single_engine, _parse_secrets_result
from ai_guardian.scanners.engine_builder import EngineConfig, ENGINE_PRESETS


class TestRunSingleEngine(unittest.TestCase):
    """Test run_single_engine() function."""

    def _make_report_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        return path

    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_no_secrets_found(self, mock_run):
        """Test engine returning success (no secrets)."""
        report = self._make_report_file()
        with open(report, "w") as f:
            json.dump([], f)

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        config = ENGINE_PRESETS["gitleaks"]
        result = run_single_engine(config, "/tmp/test.txt", report)

        self.assertFalse(result.has_secrets)
        self.assertEqual(result.engine, "gitleaks")
        self.assertEqual(len(result.secrets), 0)
        self.assertGreaterEqual(result.scan_time_ms, 0)
        os.unlink(report)

    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_secrets_found_gitleaks(self, mock_run):
        """Test gitleaks detecting secrets (exit code 42)."""
        report = self._make_report_file()
        findings = [
            {
                "RuleID": "aws-access-token",
                "File": "test.txt",
                "StartLine": 5,
                "EndLine": 5,
                "Description": "AWS Access Key",
            }
        ]
        with open(report, "w") as f:
            json.dump(findings, f)

        mock_run.return_value = MagicMock(returncode=42, stdout="", stderr="")

        config = ENGINE_PRESETS["gitleaks"]
        result = run_single_engine(config, "/tmp/test.txt", report)

        self.assertTrue(result.has_secrets)
        self.assertEqual(len(result.secrets), 1)
        self.assertEqual(result.secrets[0].rule_id, "aws-access-token")
        self.assertEqual(result.secrets[0].engine, "gitleaks")
        os.unlink(report)

    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_gitleaks_exit_code_1_treated_as_secrets(self, mock_run):
        """Test gitleaks exit code 1 special case (Issue #411)."""
        report = self._make_report_file()
        findings = [
            {
                "RuleID": "generic-api-key",
                "File": "a.py",
                "StartLine": 1,
                "EndLine": 1,
                "Description": "API Key",
            }
        ]
        with open(report, "w") as f:
            json.dump(findings, f)

        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")

        config = ENGINE_PRESETS["gitleaks"]
        result = run_single_engine(config, "/tmp/test.txt", report)

        self.assertTrue(result.has_secrets)
        os.unlink(report)

    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_betterleaks_exit_code_1_treated_as_secrets(self, mock_run):
        """Test betterleaks exit code 1 special case."""
        report = self._make_report_file()
        findings = [
            {
                "RuleID": "generic-api-key",
                "File": "a.py",
                "StartLine": 1,
                "EndLine": 1,
                "Description": "Key",
            }
        ]
        with open(report, "w") as f:
            json.dump(findings, f)

        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")

        config = ENGINE_PRESETS["betterleaks"]
        result = run_single_engine(config, "/tmp/test.txt", report)

        self.assertTrue(result.has_secrets)
        os.unlink(report)

    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_betterleaks_exit_code_1_no_findings_returns_clean(self, mock_run):
        """Test betterleaks exit code 1 with no findings returns clean (Issue #520).

        When betterleaks crashes (e.g., incompatible config), it exits 1 but
        produces no report. The parser should find no findings and return clean.
        """
        report = self._make_report_file()
        # Empty report — betterleaks crashed before writing findings
        with open(report, "w") as f:
            json.dump([], f)

        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="FTL failed to compile CEL filters"
        )

        config = ENGINE_PRESETS["betterleaks"]
        result = run_single_engine(config, "/tmp/test.txt", report)

        self.assertFalse(result.has_secrets)
        self.assertEqual(len(result.secrets), 0)
        os.unlink(report)

    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_betterleaks_exit_code_1_missing_report_returns_clean(self, mock_run):
        """Test betterleaks exit code 1 with missing report file (Issue #520)."""
        report = "/tmp/nonexistent_report_520.json"

        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="FTL failed to compile CEL filters"
        )

        config = ENGINE_PRESETS["betterleaks"]
        result = run_single_engine(config, "/tmp/test.txt", report)

        self.assertFalse(result.has_secrets)

    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_trufflehog_stdout_redirect(self, mock_run):
        """Test TruffleHog output is written from stdout to report file."""
        report = self._make_report_file()
        trufflehog_output = '{"SourceMetadata":{"Data":{"Filesystem":{"file":"t.txt","line":1}}},"DetectorName":"AWS","Verified":false}\n'

        mock_run.return_value = MagicMock(
            returncode=183, stdout=trufflehog_output, stderr=""
        )

        config = ENGINE_PRESETS["trufflehog"]
        result = run_single_engine(config, "/tmp/test.txt", report)

        self.assertTrue(result.has_secrets)
        self.assertEqual(result.secrets[0].rule_id, "aws")
        self.assertEqual(result.secrets[0].engine, "trufflehog")
        os.unlink(report)

    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_detect_secrets_stdout_redirect(self, mock_run):
        """Test detect-secrets output is written from stdout to report file."""
        report = self._make_report_file()
        ds_output = json.dumps(
            {
                "results": {
                    "config.py": [
                        {
                            "type": "AWS Access Key",
                            "line_number": 3,
                            "hashed_secret": "abc",
                        }
                    ]
                },
                "version": "1.0.0",
            }
        )

        mock_run.return_value = MagicMock(returncode=0, stdout=ds_output, stderr="")

        config = ENGINE_PRESETS["detect-secrets"]
        result = run_single_engine(config, "/tmp/test.txt", report)

        # detect-secrets exit code 0 means success, findings are in the output
        # The engine uses exit code 0 for success (no secrets) and 1 for secrets found
        # Since returncode=0 matches success_exit_code, it returns no secrets
        self.assertFalse(result.has_secrets)
        os.unlink(report)

    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_timeout_handling(self, mock_run):
        """Test subprocess timeout is caught gracefully."""
        report = self._make_report_file()
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=30)

        config = ENGINE_PRESETS["gitleaks"]
        result = run_single_engine(config, "/tmp/test.txt", report)

        self.assertFalse(result.has_secrets)
        self.assertIn("Timed out", result.error)
        os.unlink(report)

    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_binary_not_found(self, mock_run):
        """Test FileNotFoundError when binary doesn't exist."""
        report = self._make_report_file()
        mock_run.side_effect = FileNotFoundError("No such file: nonexistent")

        config = EngineConfig(
            type="test",
            binary="nonexistent",
            command_template=["{binary}", "{source_file}"],
        )
        result = run_single_engine(config, "/tmp/test.txt", report)

        self.assertFalse(result.has_secrets)
        self.assertIn("not found", result.error)
        os.unlink(report)

    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_unexpected_exit_code(self, mock_run):
        """Test unexpected exit code returns error."""
        report = self._make_report_file()
        mock_run.return_value = MagicMock(
            returncode=99, stdout="", stderr="Something went wrong"
        )

        config = ENGINE_PRESETS["gitleaks"]
        result = run_single_engine(config, "/tmp/test.txt", report)

        self.assertFalse(result.has_secrets)
        self.assertIn("Unexpected exit code 99", result.error)
        os.unlink(report)

    @patch.dict(os.environ, {}, clear=True)
    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_gitguardian_missing_api_key_is_reported_without_value(self, mock_run):
        report = self._make_report_file()

        result = run_single_engine(
            ENGINE_PRESETS["gitguardian"], "/tmp/test.txt", report
        )

        self.assertFalse(result.has_secrets)
        self.assertIn("API key not set", result.error)
        mock_run.assert_not_called()
        os.unlink(report)

    @patch.dict(os.environ, {"GITGUARDIAN_API_KEY": "synthetic-test-value"})
    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_gitguardian_quota_failure_is_classified_without_raw_output(self, mock_run):
        report = self._make_report_file()
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout='{"error":"workspace quota exceeded; diagnostic=DO_NOT_SHOW_THIS_VALUE"}',
            stderr="",
        )

        result = run_single_engine(
            ENGINE_PRESETS["gitguardian"], "/tmp/test.txt", report
        )

        self.assertFalse(result.has_secrets)
        self.assertIn("quota exhausted or rate-limited", result.error)
        self.assertNotIn("DO_NOT_SHOW_THIS_VALUE", result.error)
        self.assertNotIn("synthetic-test-value", result.error)
        os.unlink(report)

    @patch.dict(os.environ, {"GITGUARDIAN_API_KEY": "synthetic-test-value"})
    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_gitguardian_zero_exit_parses_findings_with_exit_zero(self, mock_run):
        report = self._make_report_file()
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "policy_break_count": 1,
                    "policies": ["Secrets detection"],
                    "policy_breaks": [
                        {
                            "break_type": "Synthetic finding",
                            "validity": "no_checker",
                            "incidents": [
                                {
                                    "location": {
                                        "filename": "test.txt",
                                        "line_start": 2,
                                        "line_end": 2,
                                    },
                                    "type": "synthetic_rule",
                                }
                            ],
                        }
                    ],
                }
            ),
            stderr="",
        )

        result = run_single_engine(
            ENGINE_PRESETS["gitguardian"], "/tmp/test.txt", report
        )

        self.assertTrue(result.has_secrets)
        self.assertEqual(result.secrets[0].rule_id, "synthetic_rule")
        self.assertEqual(result.secrets[0].line_number, 2)
        os.unlink(report)

    @patch.dict(os.environ, {"GITGUARDIAN_API_KEY": "synthetic-test-value"})
    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_gitguardian_zero_exit_parses_a_completed_clean_scan(self, mock_run):
        report = self._make_report_file()
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {"policy_break_count": 0, "policies": [], "policy_breaks": []}
            ),
            stderr="",
        )

        result = run_single_engine(
            ENGINE_PRESETS["gitguardian"], "/tmp/test.txt", report
        )

        self.assertFalse(result.has_secrets)
        self.assertIsNone(result.error)
        os.unlink(report)

    @patch.dict(os.environ, {"GITGUARDIAN_API_KEY": "synthetic-test-value"})
    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_gitguardian_success_without_scan_results_is_not_clean(self, mock_run):
        report = self._make_report_file()
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"error":"workspace quota exceeded; diagnostic=DO_NOT_SHOW_THIS_VALUE"}',
            stderr="",
        )

        result = run_single_engine(
            ENGINE_PRESETS["gitguardian"], "/tmp/test.txt", report
        )

        self.assertFalse(result.has_secrets)
        self.assertIn("quota exhausted or rate-limited", result.error)
        self.assertNotIn("DO_NOT_SHOW_THIS_VALUE", result.error)
        os.unlink(report)

    @patch("ai_guardian.scanners.executor.subprocess.run")
    def test_records_timing(self, mock_run):
        """Test that scan_time_ms is recorded."""
        report = self._make_report_file()
        with open(report, "w") as f:
            json.dump([], f)

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        config = ENGINE_PRESETS["gitleaks"]
        result = run_single_engine(config, "/tmp/test.txt", report)

        self.assertGreaterEqual(result.scan_time_ms, 0)
        os.unlink(report)


class TestParseSecretsResult(unittest.TestCase):
    """Test _parse_secrets_result helper."""

    def test_parser_returns_no_findings(self):
        """Test when parser finds no secrets despite exit code."""
        report = tempfile.mktemp(suffix=".json")
        with open(report, "w") as f:
            json.dump([], f)

        config = ENGINE_PRESETS["gitleaks"]
        result = _parse_secrets_result(config, report, 100.0)

        self.assertFalse(result.has_secrets)
        os.unlink(report)

    def test_parser_returns_findings(self):
        """Test when parser finds secrets."""
        report = tempfile.mktemp(suffix=".json")
        findings = [
            {
                "RuleID": "generic-api-key",
                "File": "a.py",
                "StartLine": 1,
                "EndLine": 1,
                "Description": "API Key",
            },
            {
                "RuleID": "aws-key",
                "File": "b.py",
                "StartLine": 5,
                "EndLine": 5,
                "Description": "AWS Key",
            },
        ]
        with open(report, "w") as f:
            json.dump(findings, f)

        config = ENGINE_PRESETS["gitleaks"]
        result = _parse_secrets_result(config, report, 50.0)

        self.assertTrue(result.has_secrets)
        self.assertEqual(len(result.secrets), 2)
        self.assertEqual(result.secrets[0].rule_id, "generic-api-key")
        self.assertEqual(result.secrets[1].rule_id, "aws-key")
        self.assertEqual(result.scan_time_ms, 50.0)
        os.unlink(report)

    def test_parser_failure_returns_no_secrets(self):
        """Test that parser failure on missing file returns no secrets.

        GitleaksOutputParser.parse() returns None for missing files.
        _parse_secrets_result treats None/empty as no secrets found.
        """
        config = ENGINE_PRESETS["gitleaks"]
        result = _parse_secrets_result(config, "/nonexistent/path.json", 10.0)

        self.assertFalse(result.has_secrets)
        self.assertEqual(len(result.secrets), 0)


if __name__ == "__main__":
    unittest.main()
