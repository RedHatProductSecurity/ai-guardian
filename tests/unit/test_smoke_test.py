"""
Tests for the smoke test command (Issue #1815).

Tests canary payload testing against scanners.
"""

import argparse
import json
from unittest import mock

import pytest

from ai_guardian.smoke_test import (
    SmokeTestOutcome,
    SmokeTestReport,
    SmokeTestResult,
    SmokeTestRunner,
    format_smoke_human,
    format_smoke_json,
    smoke_test_command,
)
from ai_guardian.doctor import CheckResult, CheckStatus

# --- Data model tests ---


class TestSmokeTestOutcome:
    def test_values(self):
        assert SmokeTestOutcome.MATCH.value == "match"
        assert SmokeTestOutcome.MISMATCH.value == "mismatch"
        assert SmokeTestOutcome.SKIPPED.value == "skipped"


class TestSmokeTestResult:
    def test_defaults(self):
        r = SmokeTestResult(
            scanner_name="test",
            display_name="Test",
            outcome=SmokeTestOutcome.MATCH,
        )
        assert r.expected_action == ""
        assert r.actual_detected is False
        assert r.message == ""
        assert r.detail is None
        assert r.fix_hint is None
        assert r.elapsed_ms == 0.0


class TestSmokeTestReport:
    def test_exit_code_all_match(self):
        report = SmokeTestReport(
            phase2_results=[
                SmokeTestResult(
                    scanner_name="a",
                    display_name="A",
                    outcome=SmokeTestOutcome.MATCH,
                ),
            ],
            phase1_passed=True,
        )
        assert report.exit_code == 0

    def test_exit_code_mismatch(self):
        report = SmokeTestReport(
            phase2_results=[
                SmokeTestResult(
                    scanner_name="a",
                    display_name="A",
                    outcome=SmokeTestOutcome.MISMATCH,
                ),
            ],
            phase1_passed=True,
        )
        assert report.exit_code == 2

    def test_exit_code_phase1_failed(self):
        report = SmokeTestReport(phase1_passed=False)
        assert report.exit_code == 2

    def test_has_mismatches(self):
        report = SmokeTestReport(
            phase2_results=[
                SmokeTestResult(
                    scanner_name="a",
                    display_name="A",
                    outcome=SmokeTestOutcome.MATCH,
                ),
                SmokeTestResult(
                    scanner_name="b",
                    display_name="B",
                    outcome=SmokeTestOutcome.SKIPPED,
                ),
            ],
            phase1_passed=True,
        )
        assert not report.has_mismatches


# --- Runner tests ---


class TestSmokeTestRunnerPhase1:
    @mock.patch("ai_guardian.smoke_test.Doctor")
    def test_phase1_runs_config_checks(self, mock_doctor_cls):
        doctor_instance = mock.MagicMock()
        mock_doctor_cls.return_value = doctor_instance
        doctor_instance.check_config_file.return_value = CheckResult(
            name="config_file", status=CheckStatus.PASS, message="ok"
        )
        doctor_instance.check_project_config.return_value = CheckResult(
            name="project_config", status=CheckStatus.PASS, message="ok"
        )
        doctor_instance.check_config_overlay.return_value = CheckResult(
            name="config_overlay", status=CheckStatus.PASS, message="ok"
        )
        doctor_instance.check_unknown_config_keys.return_value = CheckResult(
            name="unknown_config_keys", status=CheckStatus.PASS, message="ok"
        )
        doctor_instance.check_config_consistency.return_value = CheckResult(
            name="config_consistency", status=CheckStatus.PASS, message="ok"
        )

        runner = SmokeTestRunner()
        checks, passed = runner.run_phase1()

        assert passed is True
        assert len(checks) == 5

    @mock.patch("ai_guardian.smoke_test.Doctor")
    def test_phase1_fail_fast(self, mock_doctor_cls):
        doctor_instance = mock.MagicMock()
        mock_doctor_cls.return_value = doctor_instance
        doctor_instance.check_config_file.return_value = CheckResult(
            name="config_file", status=CheckStatus.FAIL, message="broken"
        )
        doctor_instance.check_project_config.return_value = CheckResult(
            name="project_config", status=CheckStatus.PASS, message="ok"
        )
        doctor_instance.check_config_overlay.return_value = CheckResult(
            name="config_overlay", status=CheckStatus.PASS, message="ok"
        )
        doctor_instance.check_unknown_config_keys.return_value = CheckResult(
            name="unknown_config_keys", status=CheckStatus.PASS, message="ok"
        )
        doctor_instance.check_config_consistency.return_value = CheckResult(
            name="config_consistency", status=CheckStatus.PASS, message="ok"
        )

        runner = SmokeTestRunner()
        checks, passed = runner.run_phase1()

        assert passed is False


class TestSmokeTestRunnerPhase2:
    def _make_runner(self, config=None):
        runner = SmokeTestRunner()
        runner._config = config or {}
        runner._config_loaded = True
        runner._config_error = None
        return runner

    @mock.patch("ai_guardian.hook_events.scanners.run_prompt_injection_scan")
    def test_prompt_injection_match(self, mock_scan):
        mock_result = mock.MagicMock()
        mock_result.detected = True
        mock_scan.return_value = mock_result

        runner = self._make_runner(
            {"prompt_injection": {"enabled": True, "action": "block"}}
        )
        result = runner._test_prompt_injection({"enabled": True, "action": "block"})

        assert result.outcome == SmokeTestOutcome.MATCH
        assert result.actual_detected is True
        assert result.expected_action == "block"

    @mock.patch("ai_guardian.hook_events.scanners.run_prompt_injection_scan")
    def test_prompt_injection_mismatch(self, mock_scan):
        mock_scan.return_value = None

        runner = self._make_runner({"prompt_injection": {"enabled": True}})
        result = runner._test_prompt_injection({"enabled": True, "action": "block"})

        assert result.outcome == SmokeTestOutcome.MISMATCH
        assert result.actual_detected is False

    def test_scanner_disabled_skipped(self):
        runner = self._make_runner()
        result = runner._test_prompt_injection({"enabled": False})
        assert result.outcome == SmokeTestOutcome.SKIPPED

    @mock.patch("ai_guardian.hook_events.scanners.run_pii_scan")
    def test_pii_match(self, mock_scan):
        mock_result = mock.MagicMock()
        mock_result.detected = True
        mock_scan.return_value = mock_result

        runner = self._make_runner()
        result = runner._test_pii({"enabled": True, "action": "block"})

        assert result.outcome == SmokeTestOutcome.MATCH

    @mock.patch("ai_guardian.scanners.ssrf.SSRFProtector")
    def test_ssrf_match(self, mock_protector_cls):
        mock_protector = mock.MagicMock()
        mock_protector_cls.return_value = mock_protector
        mock_protector.check.return_value = (True, "Blocked: metadata endpoint")

        runner = self._make_runner()
        result = runner._test_ssrf({"enabled": True, "action": "block"})

        assert result.outcome == SmokeTestOutcome.MATCH

    @mock.patch("ai_guardian.hook_events.scanners.run_context_poisoning_scan")
    def test_context_poisoning_match(self, mock_scan):
        mock_result = mock.MagicMock()
        mock_result.detected = True
        mock_scan.return_value = mock_result

        runner = self._make_runner()
        result = runner._test_context_poisoning({"enabled": True, "action": "warn"})

        assert result.outcome == SmokeTestOutcome.MATCH
        assert result.expected_action == "warn"

    @mock.patch("ai_guardian.scanners.secret_redactor.SecretRedactor")
    def test_secret_redaction_match(self, mock_redactor_cls):
        mock_redactor = mock.MagicMock()
        mock_redactor_cls.return_value = mock_redactor
        mock_redactor.redact.return_value = {
            "redacted_text": "AWS_ACCESS_KEY_ID=[REDACTED]",
            "redactions": [{"type": "aws_key"}],
        }

        runner = self._make_runner({"secret_redaction": {"enabled": True}})
        result = runner._test_secret_redaction({})

        assert result.outcome == SmokeTestOutcome.MATCH

    @mock.patch("ai_guardian.hook_events.scanners.run_bash_exfil_scan")
    def test_bash_exfil_match(self, mock_scan):
        mock_result = mock.MagicMock()
        mock_result.detected = True
        mock_scan.return_value = mock_result

        runner = self._make_runner()
        result = runner._test_bash_exfil({"enabled": True, "action": "block"})

        assert result.outcome == SmokeTestOutcome.MATCH

    @mock.patch("ai_guardian.hook_events.scanners.run_exfil_detection_scan")
    def test_exfil_detection_match(self, mock_scan):
        mock_result = mock.MagicMock()
        mock_result.detected = True
        mock_scan.return_value = mock_result

        runner = self._make_runner()
        result = runner._test_exfil_detection({"enabled": True, "action": "block"})

        assert result.outcome == SmokeTestOutcome.MATCH

    def test_canary_detection_no_tokens_skipped(self):
        runner = self._make_runner()
        result = runner._test_canary_detection({"enabled": True, "tokens": []})
        assert result.outcome == SmokeTestOutcome.SKIPPED
        assert "No canary tokens" in result.message

    def test_canary_detection_disabled_skipped(self):
        runner = self._make_runner()
        result = runner._test_canary_detection({"enabled": False})
        assert result.outcome == SmokeTestOutcome.SKIPPED

    @mock.patch("ai_guardian.hook_events.scanners.run_code_security_scan")
    def test_code_scanning_match(self, mock_scan):
        mock_result = mock.MagicMock()
        mock_result.detected = True
        mock_scan.return_value = mock_result

        runner = self._make_runner()
        result = runner._test_code_scanning({"enabled": True, "action": "warn"})

        assert result.outcome == SmokeTestOutcome.MATCH

    def test_offensive_language_disabled_by_default(self):
        runner = self._make_runner()
        result = runner._test_offensive_language({})
        assert result.outcome == SmokeTestOutcome.SKIPPED


class TestSmokeTestRunnerRun:
    @mock.patch.object(SmokeTestRunner, "run_phase2")
    @mock.patch.object(SmokeTestRunner, "run_phase1")
    @mock.patch("ai_guardian.__version__", "1.0.0-test")
    def test_run_skips_phase2_on_phase1_fail(self, mock_p1, mock_p2):
        mock_p1.return_value = (
            [
                CheckResult(
                    name="config_file",
                    status=CheckStatus.FAIL,
                    message="broken",
                )
            ],
            False,
        )

        runner = SmokeTestRunner()
        report = runner.run()

        assert not report.phase1_passed
        assert report.phase2_results == []
        mock_p2.assert_not_called()

    @mock.patch.object(SmokeTestRunner, "run_phase2")
    @mock.patch.object(SmokeTestRunner, "run_phase1")
    @mock.patch("ai_guardian.__version__", "1.0.0-test")
    def test_run_calls_phase2_on_phase1_pass(self, mock_p1, mock_p2):
        mock_p1.return_value = (
            [
                CheckResult(
                    name="config_file",
                    status=CheckStatus.PASS,
                    message="ok",
                )
            ],
            True,
        )
        mock_p2.return_value = [
            SmokeTestResult(
                scanner_name="prompt_injection",
                display_name="Prompt injection",
                outcome=SmokeTestOutcome.MATCH,
            ),
        ]

        runner = SmokeTestRunner()
        report = runner.run()

        assert report.phase1_passed
        assert len(report.phase2_results) == 1
        mock_p2.assert_called_once()


# --- Formatter tests ---


class TestFormatters:
    def _make_report(self):
        return SmokeTestReport(
            phase1_checks=[
                CheckResult(
                    name="config_file",
                    status=CheckStatus.PASS,
                    message="Valid config",
                ),
            ],
            phase2_results=[
                SmokeTestResult(
                    scanner_name="prompt_injection",
                    display_name="Prompt injection",
                    outcome=SmokeTestOutcome.MATCH,
                    expected_action="block",
                    actual_detected=True,
                    message="Detected canary injection (3ms)",
                    elapsed_ms=3.0,
                ),
                SmokeTestResult(
                    scanner_name="scan_offensive",
                    display_name="Offensive language",
                    outcome=SmokeTestOutcome.SKIPPED,
                    message="Disabled in config",
                ),
            ],
            version="1.0.0-test",
            phase1_passed=True,
        )

    def test_format_human_contains_phases(self):
        output = format_smoke_human(self._make_report())
        assert "Phase 1" in output
        assert "Phase 2" in output
        assert "Prompt injection" in output
        assert "1 matched" in output
        assert "1 skipped" in output

    def test_format_human_phase1_fail_shows_stop(self):
        report = SmokeTestReport(
            phase1_checks=[
                CheckResult(
                    name="config_file",
                    status=CheckStatus.FAIL,
                    message="broken",
                ),
            ],
            phase1_passed=False,
            version="1.0.0-test",
        )
        output = format_smoke_human(report)
        assert "fix config first" in output

    def test_format_json_structure(self):
        output = format_smoke_json(self._make_report())
        data = json.loads(output)
        assert data["version"] == "1.0.0-test"
        assert data["phase1"]["passed"] is True
        assert len(data["phase2"]["results"]) == 2
        assert data["phase2"]["summary"]["match"] == 1
        assert data["phase2"]["summary"]["skipped"] == 1
        assert data["exit_code"] == 0


# --- CLI entry point tests ---


class TestSmokeTestCommand:
    @mock.patch.object(SmokeTestRunner, "run")
    def test_quiet_returns_exit_code(self, mock_run):
        mock_run.return_value = SmokeTestReport(
            phase1_passed=True,
            phase2_results=[
                SmokeTestResult(
                    scanner_name="a",
                    display_name="A",
                    outcome=SmokeTestOutcome.MATCH,
                ),
            ],
            version="1.0.0",
        )
        args = argparse.Namespace(quiet=True, json=False)
        assert smoke_test_command(args) == 0

    @mock.patch("builtins.print")
    @mock.patch.object(SmokeTestRunner, "run")
    def test_json_flag(self, mock_run, mock_print):
        mock_run.return_value = SmokeTestReport(
            phase1_passed=True,
            version="1.0.0",
        )
        args = argparse.Namespace(quiet=False, json=True)
        smoke_test_command(args)
        output = mock_print.call_args[0][0]
        data = json.loads(output)
        assert "phase1" in data
        assert "phase2" in data
