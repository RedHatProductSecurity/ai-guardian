#!/usr/bin/env python3
"""
Tests for the Health Check (Doctor) TUI panel.

Tests the panel integration, helper formatters, and check execution
without running the full Textual app.
"""

from unittest.mock import patch, MagicMock


from ai_guardian.doctor import (
    CheckResult,
    CheckStatus,
    DoctorReport,
    _CHECK_DISPLAY_NAMES,
)
from ai_guardian.tui.health_check import (
    HealthCheckContent,
    format_check_status,
    format_check_detail,
    format_hook_integration_detail,
    format_hook_integration_status,
    format_summary,
)
from ai_guardian.tui.app import NAV_GROUPS, HELP_DOCS


class TestHealthCheckImport:
    """Verify the panel integrates with the TUI app."""

    def test_health_check_content_can_be_imported(self):
        assert HealthCheckContent is not None

    def test_health_check_in_nav_groups(self):
        nav_dict = {name: [pid for _, pid in items] for name, items in NAV_GROUPS}
        assert "panel-health-check" in nav_dict["Security Overview"]

    def test_health_check_has_help_doc(self):
        assert "panel-health-check" in HELP_DOCS
        assert len(HELP_DOCS["panel-health-check"]) > 0

    def test_security_overview_help_mentions_health_check(self):
        assert "Health Check" in HELP_DOCS["Security Overview"]


class TestFormatCheckStatus:
    """Test the format_check_status() helper function."""

    def test_pass_status(self):
        check = CheckResult(
            name="config_file",
            status=CheckStatus.PASS,
            message="Valid config at ~/.config/ai-guardian/ai-guardian.json",
        )
        result = format_check_status(check)
        assert "PASS" in result
        assert "Config file" in result
        assert "Valid config" in result

    def test_warn_status(self):
        check = CheckResult(
            name="scanners",
            status=CheckStatus.WARN,
            message="Some scanners have unknown version",
        )
        result = format_check_status(check)
        assert "WARN" in result
        assert "Scanners" in result

    def test_fail_status(self):
        check = CheckResult(
            name="hooks",
            status=CheckStatus.FAIL,
            message="No hooks configured",
        )
        result = format_check_status(check)
        assert "FAIL" in result
        assert "Hooks" in result

    def test_skip_status(self):
        check = CheckResult(
            name="ps_url",
            status=CheckStatus.SKIP,
            message="Skipped (use --check-connectivity)",
        )
        result = format_check_status(check)
        assert "SKIP" in result

    def test_unknown_check_name_uses_raw_name(self):
        check = CheckResult(
            name="unknown_check",
            status=CheckStatus.PASS,
            message="OK",
        )
        result = format_check_status(check)
        assert "unknown_check" in result

    def test_structured_hooks_omit_aggregate_message(self):
        check = CheckResult(
            name="hooks",
            status=CheckStatus.WARN,
            message="Claude Code: 6/6 hooks; Cursor IDE: Not installed",
            integrations=[
                {
                    "display_name": "Claude Code",
                    "status": "pass",
                    "message": "6/6 hooks",
                }
            ],
        )

        result = format_check_status(check)

        assert "Hooks" in result
        assert ";" not in result

    def test_hook_integration_status_and_detail(self):
        integration = {
            "display_name": "Cursor IDE",
            "status": "warn",
            "message": "6/6 hooks (scope: user; effective: project)",
            "detail": "beforeReadFile, MCP server (missing)",
            "fix_hint": "Run: ai-guardian setup",
        }

        status = format_hook_integration_status(integration)
        detail = format_hook_integration_detail(integration)

        assert "WARN" in status
        assert "Cursor IDE" in status
        assert "scope: user" in status
        assert "beforeReadFile" in detail
        assert "ai-guardian setup" in detail

    def test_all_display_names_mapped(self):
        known_checks = [
            "config_file",
            "deprecated_fields",
            "scanners",
            "pattern_server",
            "ps_cache_path",
            "ps_auth",
            "ps_url",
            "ps_cache_freshness",
            "hooks",
            "state_dir",
            "cache_dir",
            "permissions",
            "directory_rules",
            "console_deps",
            "config_consistency",
        ]
        for name in known_checks:
            assert name in _CHECK_DISPLAY_NAMES


class TestFormatCheckDetail:
    """Test the format_check_detail() helper function."""

    def test_detail_only(self):
        check = CheckResult(
            name="test",
            status=CheckStatus.WARN,
            message="Issue found",
            detail="  - schema error 1\n  - schema error 2",
        )
        result = format_check_detail(check)
        assert "Detail:" in result
        assert "schema error 1" in result

    def test_fix_hint_only(self):
        check = CheckResult(
            name="test",
            status=CheckStatus.FAIL,
            message="Missing",
            fix_hint="Run: ai-guardian setup --create-config",
        )
        result = format_check_detail(check)
        assert "Hint" in result
        assert "ai-guardian setup" in result

    def test_fixed_hint(self):
        check = CheckResult(
            name="test",
            status=CheckStatus.PASS,
            message="Fixed",
            fix_hint="Created directory",
            fixed=True,
        )
        result = format_check_detail(check)
        assert "Fixed" in result

    def test_fixable_not_fixed(self):
        check = CheckResult(
            name="test",
            status=CheckStatus.FAIL,
            message="Missing dir",
            fix_hint="Run doctor --fix",
            fixable=True,
        )
        result = format_check_detail(check)
        assert "auto-fixed" in result

    def test_no_detail_no_hint(self):
        check = CheckResult(
            name="test",
            status=CheckStatus.PASS,
            message="OK",
        )
        result = format_check_detail(check)
        assert "No additional details" in result

    def test_detail_and_hint_combined(self):
        check = CheckResult(
            name="test",
            status=CheckStatus.WARN,
            message="Issue",
            detail="some detail",
            fix_hint="some hint",
        )
        result = format_check_detail(check)
        assert "Detail:" in result
        assert "some detail" in result
        assert "Hint" in result
        assert "some hint" in result


class TestFormatSummary:
    """Test the format_summary() helper function."""

    def test_all_pass(self):
        report = DoctorReport(
            checks=[
                CheckResult(name="a", status=CheckStatus.PASS, message="OK"),
                CheckResult(name="b", status=CheckStatus.PASS, message="OK"),
            ]
        )
        result = format_summary(report)
        assert "2 passed" in result
        assert "error" not in result

    def test_mixed_results(self):
        report = DoctorReport(
            checks=[
                CheckResult(name="a", status=CheckStatus.PASS, message="OK"),
                CheckResult(name="b", status=CheckStatus.WARN, message="Warning"),
                CheckResult(name="c", status=CheckStatus.FAIL, message="Error"),
                CheckResult(name="d", status=CheckStatus.SKIP, message="Skipped"),
            ]
        )
        result = format_summary(report)
        assert "1 passed" in result
        assert "1 error(s)" in result
        assert "1 warning(s)" in result
        assert "1 skipped" in result

    def test_with_fixed(self):
        report = DoctorReport(
            checks=[
                CheckResult(
                    name="a", status=CheckStatus.PASS, message="OK", fixed=True
                ),
            ]
        )
        result = format_summary(report)
        assert "1 fixed" in result

    def test_empty_report(self):
        report = DoctorReport(checks=[])
        result = format_summary(report)
        assert "No checks ran" in result


class TestHealthCheckRunChecks:
    """Test _run_checks calls Doctor correctly."""

    @patch.object(HealthCheckContent, "_update_display")
    @patch("ai_guardian.tui.health_check.Doctor")
    def test_run_checks_calls_doctor(self, mock_doctor_cls, mock_display):
        mock_doctor = MagicMock()
        report = DoctorReport(
            checks=[
                CheckResult(name="config_file", status=CheckStatus.PASS, message="OK"),
            ]
        )
        mock_doctor.run_all.return_value = report
        mock_doctor_cls.return_value = mock_doctor

        content = HealthCheckContent.__new__(HealthCheckContent)
        content._run_checks(fix=False)

        mock_doctor_cls.assert_called_once_with(fix=False)
        mock_doctor.run_all.assert_called_once()
        mock_display.assert_called_once_with(report, fixed=False)

    @patch.object(HealthCheckContent, "_update_display")
    @patch("ai_guardian.tui.health_check.Doctor")
    def test_run_checks_with_fix(self, mock_doctor_cls, mock_display):
        mock_doctor = MagicMock()
        report = DoctorReport(checks=[])
        mock_doctor.run_all.return_value = report
        mock_doctor_cls.return_value = mock_doctor

        content = HealthCheckContent.__new__(HealthCheckContent)
        content._run_checks(fix=True)

        mock_doctor_cls.assert_called_once_with(fix=True)
        mock_display.assert_called_once_with(report, fixed=True)

    @patch.object(HealthCheckContent, "_update_display")
    @patch("ai_guardian.tui.health_check.Doctor")
    def test_run_checks_handles_exception(self, mock_doctor_cls, mock_display):
        mock_doctor_cls.side_effect = RuntimeError("boom")

        content = HealthCheckContent.__new__(HealthCheckContent)
        content._run_checks(fix=False)

        mock_display.assert_called_once()
        report = mock_display.call_args[0][0]
        assert len(report.checks) == 1
        assert report.checks[0].status == CheckStatus.FAIL
        assert "boom" in report.checks[0].message
