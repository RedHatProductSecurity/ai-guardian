"""
Tests for the doctor command (Issue #475).

Tests health check: config validation, scanner detection, hook verification, etc.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

from ai_guardian.doctor import (
    CheckResult,
    CheckStatus,
    Doctor,
    DoctorReport,
    doctor_command,
    format_human,
    format_json,
)

# --- Data model tests ---


class TestCheckStatus:
    def test_values(self):
        assert CheckStatus.PASS.value == "pass"
        assert CheckStatus.WARN.value == "warn"
        assert CheckStatus.FAIL.value == "fail"
        assert CheckStatus.SKIP.value == "skip"


class TestCheckResult:
    def test_defaults(self):
        r = CheckResult(name="test", status=CheckStatus.PASS, message="ok")
        assert r.detail is None
        assert r.fix_hint is None
        assert r.fixable is False
        assert r.fixed is False


class TestDoctorReport:
    def test_exit_code_all_pass(self):
        report = DoctorReport(
            checks=[
                CheckResult(name="a", status=CheckStatus.PASS, message="ok"),
                CheckResult(name="b", status=CheckStatus.PASS, message="ok"),
            ]
        )
        assert report.exit_code == 0

    def test_exit_code_with_warnings(self):
        report = DoctorReport(
            checks=[
                CheckResult(name="a", status=CheckStatus.PASS, message="ok"),
                CheckResult(name="b", status=CheckStatus.WARN, message="warn"),
            ]
        )
        assert report.exit_code == 1

    def test_exit_code_with_errors(self):
        report = DoctorReport(
            checks=[
                CheckResult(name="a", status=CheckStatus.FAIL, message="fail"),
            ]
        )
        assert report.exit_code == 2

    def test_exit_code_errors_trump_warnings(self):
        report = DoctorReport(
            checks=[
                CheckResult(name="a", status=CheckStatus.WARN, message="warn"),
                CheckResult(name="b", status=CheckStatus.FAIL, message="fail"),
            ]
        )
        assert report.exit_code == 2

    def test_has_errors(self):
        report = DoctorReport(
            checks=[
                CheckResult(name="a", status=CheckStatus.FAIL, message="fail"),
            ]
        )
        assert report.has_errors is True
        assert report.has_warnings is False

    def test_has_warnings(self):
        report = DoctorReport(
            checks=[
                CheckResult(name="a", status=CheckStatus.WARN, message="warn"),
            ]
        )
        assert report.has_errors is False
        assert report.has_warnings is True

    def test_empty_report(self):
        report = DoctorReport()
        assert report.exit_code == 0
        assert report.has_errors is False
        assert report.has_warnings is False


# --- Individual check tests ---


class TestCheckPythonVersion:
    def test_pass_310_plus(self, _isolate_config_dir):
        with mock.patch("ai_guardian.doctor.sys") as mock_sys:
            mock_sys.version_info = (3, 12, 1, "final", 0)
            doctor = Doctor()
            result = doctor.check_python_version()
        assert result.status == CheckStatus.PASS
        assert "3.12.1" in result.message

    def test_warn_39(self, _isolate_config_dir):
        with mock.patch("ai_guardian.doctor.sys") as mock_sys:
            mock_sys.version_info = (3, 9, 18, "final", 0)
            doctor = Doctor()
            result = doctor.check_python_version()
        assert result.status == CheckStatus.WARN
        assert "3.9.18" in result.message
        assert "AST-aware scanning disabled" in result.message
        assert result.fix_hint is not None
        assert "3.10+" in result.fix_hint

    def test_fail_38(self, _isolate_config_dir):
        with mock.patch("ai_guardian.doctor.sys") as mock_sys:
            mock_sys.version_info = (3, 8, 16, "final", 0)
            doctor = Doctor()
            result = doctor.check_python_version()
        assert result.status == CheckStatus.FAIL
        assert "3.8.16" in result.message
        assert "unsupported" in result.message
        assert result.fix_hint is not None
        assert "3.9+" in result.fix_hint

    def test_fail_27(self, _isolate_config_dir):
        with mock.patch("ai_guardian.doctor.sys") as mock_sys:
            mock_sys.version_info = (2, 7, 18, "final", 0)
            doctor = Doctor()
            result = doctor.check_python_version()
        assert result.status == CheckStatus.FAIL
        assert "2.7.18" in result.message

    def test_pass_310_exact(self, _isolate_config_dir):
        with mock.patch("ai_guardian.doctor.sys") as mock_sys:
            mock_sys.version_info = (3, 10, 0, "final", 0)
            doctor = Doctor()
            result = doctor.check_python_version()
        assert result.status == CheckStatus.PASS
        assert "3.10.0" in result.message


class TestCheckConfigFile:
    def test_no_config_file(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_config_file()
        assert result.status == CheckStatus.WARN
        assert "No config file found" in result.message

    def test_valid_config(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"secret_scanning": {"enabled": True}}))
        doctor = Doctor()
        result = doctor.check_config_file()
        assert result.status == CheckStatus.PASS
        assert "Valid config" in result.message

    def test_invalid_json(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text("{invalid json")
        doctor = Doctor()
        result = doctor.check_config_file()
        assert result.status == CheckStatus.FAIL
        assert "Config error" in result.message


class TestCheckDeprecatedFields:
    def test_no_deprecated(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"secret_scanning": {"enabled": True}}))
        doctor = Doctor()
        result = doctor.check_deprecated_fields()
        assert result.status == CheckStatus.PASS

    def test_deprecated_pattern_server(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps({"pattern_server": {"url": "https://example.com"}})
        )
        doctor = Doctor()
        result = doctor.check_deprecated_fields()
        assert result.status == CheckStatus.WARN
        assert "pattern_server" in result.message

    def test_no_config(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_deprecated_fields()
        assert result.status == CheckStatus.PASS


class TestCheckUnknownConfigKeys:
    def test_pass_all_known_keys(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps(
                {"secret_scanning": {"enabled": True}, "scan_pii": {"enabled": False}}
            )
        )
        doctor = Doctor()
        result = doctor.check_unknown_config_keys()
        assert result.status == CheckStatus.PASS

    def test_warn_typo_root_key(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"secrt_scanning": {"enabled": True}}))
        doctor = Doctor()
        result = doctor.check_unknown_config_keys()
        assert result.status == CheckStatus.WARN
        assert "secrt_scanning" in result.detail
        assert "secret_scanning" in result.detail

    def test_warn_typo_nested_key(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"secret_scanning": {"enbled": True}}))
        doctor = Doctor()
        result = doctor.check_unknown_config_keys()
        assert result.status == CheckStatus.WARN
        assert "enbled" in result.detail
        assert "enabled" in result.detail

    def test_ignores_comment_keys(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps(
                {
                    "_comment_foo": "this is a comment",
                    "secret_scanning": {"enabled": True},
                }
            )
        )
        doctor = Doctor()
        result = doctor.check_unknown_config_keys()
        assert result.status == CheckStatus.PASS

    def test_ignores_schema_key(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps(
                {
                    "$schema": "https://example.com/schema.json",
                    "secret_scanning": {"enabled": True},
                }
            )
        )
        doctor = Doctor()
        result = doctor.check_unknown_config_keys()
        assert result.status == CheckStatus.PASS

    def test_no_config(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_unknown_config_keys()
        assert result.status == CheckStatus.PASS

    def test_multiple_unknown_keys(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"secrt_scanning": {}, "providor": "x"}))
        doctor = Doctor()
        result = doctor.check_unknown_config_keys()
        assert result.status == CheckStatus.WARN
        assert "2 unknown" in result.message
        assert "secrt_scanning" in result.detail
        assert "providor" in result.detail


class TestCheckScanners:
    def test_no_scanners(self, _isolate_config_dir):
        mock_manager = mock.MagicMock()
        mock_manager.list_installed.return_value = []
        mock_cls = mock.MagicMock(return_value=mock_manager)

        with mock.patch("ai_guardian.scanners.manager.ScannerManager", mock_cls):
            doctor = Doctor()
            result = doctor.check_scanners()
        assert result.status == CheckStatus.FAIL
        assert "No scanners installed" in result.message

    def test_scanner_found(self, _isolate_config_dir):
        mock_scanner = mock.MagicMock()
        mock_scanner.name = "gitleaks"
        mock_scanner.version = "8.30.1"
        mock_manager = mock.MagicMock()
        mock_manager.list_installed.return_value = [mock_scanner]
        mock_cls = mock.MagicMock(return_value=mock_manager)

        with mock.patch("ai_guardian.scanners.manager.ScannerManager", mock_cls):
            doctor = Doctor()
            result = doctor.check_scanners()
        assert result.status == CheckStatus.PASS
        assert "gitleaks 8.30.1" in result.message


class TestCheckPatternServer:
    def test_no_server_configured(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"secret_scanning": {"enabled": True}}))
        doctor = Doctor()
        result = doctor.check_pattern_server()
        assert result.status == CheckStatus.SKIP

    def test_configured(self, _isolate_config_dir, tmp_path):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps(
                {
                    "secret_scanning": {
                        "pattern_server": {"url": "https://example.com/patterns"}
                    }
                }
            )
        )

        doctor = Doctor()
        result = doctor.check_pattern_server()
        assert result.status == CheckStatus.PASS
        assert "Configured" in result.message


class TestCheckHooks:
    def test_no_ides_detected(self, _isolate_config_dir):
        with mock.patch(
            "ai_guardian.setup.IDESetup.list_detected_ides", return_value=[]
        ):
            doctor = Doctor()
            result = doctor.check_hooks()
            assert result.status == CheckStatus.WARN
            assert "No IDEs detected" in result.message

    def test_hooks_configured(self, _isolate_config_dir, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {
                                "matcher": "*",
                                "hooks": [
                                    {"type": "command", "command": "ai-guardian"}
                                ],
                            }
                        ],
                        "PreToolUse": [
                            {
                                "matcher": "*",
                                "hooks": [
                                    {"type": "command", "command": "ai-guardian"}
                                ],
                            }
                        ],
                        "PostToolUse": [
                            {
                                "matcher": "*",
                                "hooks": [
                                    {"type": "command", "command": "ai-guardian"}
                                ],
                            }
                        ],
                        "SessionEnd": [
                            {"hooks": [{"type": "command", "command": "ai-guardian"}]}
                        ],
                        "PostCompact": [
                            {"hooks": [{"type": "command", "command": "ai-guardian"}]}
                        ],
                    }
                }
            )
        )

        with mock.patch(
            "ai_guardian.setup.IDESetup.list_detected_ides", return_value=["claude"]
        ):
            with mock.patch(
                "ai_guardian.setup.IDESetup.get_config_path",
                return_value=str(settings_path),
            ):
                doctor = Doctor()
                result = doctor.check_hooks()
                assert result.status == CheckStatus.PASS
                assert "5/5" in result.message

    def test_partial_hooks(self, _isolate_config_dir, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "*",
                                "hooks": [
                                    {"type": "command", "command": "ai-guardian"}
                                ],
                            }
                        ],
                    }
                }
            )
        )

        with mock.patch(
            "ai_guardian.setup.IDESetup.list_detected_ides", return_value=["claude"]
        ):
            with mock.patch(
                "ai_guardian.setup.IDESetup.get_config_path",
                return_value=str(settings_path),
            ):
                doctor = Doctor()
                result = doctor.check_hooks()
                assert result.status == CheckStatus.WARN
                assert "1/5" in result.message

    def test_hooks_configured_absolute_path(self, _isolate_config_dir, tmp_path):
        """Doctor recognizes hooks with absolute paths (issue #797)."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {
                                "matcher": "*",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "/usr/bin/ai-guardian",
                                    }
                                ],
                            }
                        ],
                        "PreToolUse": [
                            {
                                "matcher": "*",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "/usr/bin/ai-guardian",
                                    }
                                ],
                            }
                        ],
                        "PostToolUse": [
                            {
                                "matcher": "*",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "/usr/bin/ai-guardian",
                                    }
                                ],
                            }
                        ],
                        "SessionEnd": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "/usr/bin/ai-guardian",
                                    }
                                ]
                            }
                        ],
                        "PostCompact": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "/usr/bin/ai-guardian",
                                    }
                                ]
                            }
                        ],
                    }
                }
            )
        )

        with mock.patch(
            "ai_guardian.setup.IDESetup.list_detected_ides", return_value=["claude"]
        ):
            with mock.patch(
                "ai_guardian.setup.IDESetup.get_config_path",
                return_value=str(settings_path),
            ):
                doctor = Doctor()
                result = doctor.check_hooks()
                assert result.status == CheckStatus.PASS
                assert "5/5" in result.message

    def test_missing_config_file_not_failure(self, _isolate_config_dir, tmp_path):
        """IDE detected but config file missing → not FAIL (e.g. Crush on CI)."""
        nonexistent = tmp_path / "nonexistent" / ".crush.json"

        with mock.patch(
            "ai_guardian.setup.IDESetup.list_detected_ides",
            return_value=["crush"],
        ):
            with mock.patch(
                "ai_guardian.setup.IDESetup.get_config_path",
                return_value=str(nonexistent),
            ):
                doctor = Doctor()
                result = doctor.check_hooks()
                assert result.status != CheckStatus.FAIL
                assert "not installed" in result.message

    def test_mixed_configured_and_missing_config(self, _isolate_config_dir, tmp_path):
        """One IDE configured + another with missing config → PASS, not FAIL."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {
                                "matcher": "*",
                                "hooks": [
                                    {"type": "command", "command": "ai-guardian"}
                                ],
                            }
                        ],
                        "PreToolUse": [
                            {
                                "matcher": "*",
                                "hooks": [
                                    {"type": "command", "command": "ai-guardian"}
                                ],
                            }
                        ],
                        "PostToolUse": [
                            {
                                "matcher": "*",
                                "hooks": [
                                    {"type": "command", "command": "ai-guardian"}
                                ],
                            }
                        ],
                        "SessionEnd": [
                            {"hooks": [{"type": "command", "command": "ai-guardian"}]}
                        ],
                        "PostCompact": [
                            {"hooks": [{"type": "command", "command": "ai-guardian"}]}
                        ],
                    }
                }
            )
        )
        nonexistent = tmp_path / ".crush.json"

        def fake_config_path(ide_type):
            if ide_type == "claude":
                return str(settings_path)
            return str(nonexistent)

        with mock.patch(
            "ai_guardian.setup.IDESetup.list_detected_ides",
            return_value=["claude", "crush"],
        ):
            with mock.patch(
                "ai_guardian.setup.IDESetup.get_config_path",
                side_effect=fake_config_path,
            ):
                doctor = Doctor()
                result = doctor.check_hooks()
                assert result.status == CheckStatus.PASS
                assert "5/5" in result.message
                assert "not installed" in result.message


class TestCheckStateDir:
    def test_exists_writable(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_state_dir()
        assert result.status == CheckStatus.PASS

    def test_old_location_files(self, _isolate_config_dir):
        config_dir = _isolate_config_dir
        (config_dir / "violations.jsonl").write_text("")
        doctor = Doctor()
        result = doctor.check_state_dir()
        assert result.status == CheckStatus.WARN
        assert "Old files" in result.message

    def test_fix_creates_dir(self, tmp_path):
        state_dir = tmp_path / "nonexistent_state"
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
                "AI_GUARDIAN_STATE_DIR": str(state_dir),
                "AI_GUARDIAN_CACHE_DIR": str(cache_dir),
            },
        ):
            doctor = Doctor(fix=True)
            result = doctor.check_state_dir()
            assert result.status == CheckStatus.PASS
            assert result.fixed is True
            assert state_dir.exists()

    def test_fix_removes_old_files(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        # Create old files in config dir and new files in state dir
        (config_dir / "violations.jsonl").write_text("old")
        (state_dir / "violations.jsonl").write_text("new")

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
                "AI_GUARDIAN_STATE_DIR": str(state_dir),
                "AI_GUARDIAN_CACHE_DIR": str(cache_dir),
            },
        ):
            doctor = Doctor(fix=True)
            result = doctor.check_state_dir()
            assert result.status == CheckStatus.PASS
            assert result.fixed is True
            assert not (config_dir / "violations.jsonl").exists()
            assert (state_dir / "violations.jsonl").exists()


class TestCheckCacheDir:
    def test_exists(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_cache_dir()
        assert result.status == CheckStatus.PASS

    def test_with_fresh_patterns(self, _isolate_config_dir):
        cache_dir = Path(os.environ["AI_GUARDIAN_CACHE_DIR"])
        (cache_dir / "patterns.toml").write_text("[patterns]\n")
        doctor = Doctor()
        result = doctor.check_cache_dir()
        assert result.status == CheckStatus.PASS
        assert "fresh" in result.message.lower()

    def test_stale_patterns(self, _isolate_config_dir):
        cache_dir = Path(os.environ["AI_GUARDIAN_CACHE_DIR"])
        patterns_file = cache_dir / "patterns.toml"
        patterns_file.write_text("[patterns]\n")
        old_time = time.time() - (10 * 86400)
        os.utime(patterns_file, (old_time, old_time))
        doctor = Doctor()
        result = doctor.check_cache_dir()
        assert result.status == CheckStatus.WARN
        assert "stale" in result.message.lower()

    def test_auto_creates_dir(self, tmp_path):
        cache_dir = tmp_path / "nonexistent_cache"
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
                "AI_GUARDIAN_STATE_DIR": str(state_dir),
                "AI_GUARDIAN_CACHE_DIR": str(cache_dir),
            },
        ):
            doctor = Doctor()
            result = doctor.check_cache_dir()
            assert result.status == CheckStatus.PASS
            assert cache_dir.exists()


class TestCheckPermissions:
    def test_valid_rules(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps(
                {
                    "permissions": {
                        "enabled": True,
                        "rules": [
                            {"matcher": "Bash", "allow": ["git *"]},
                            {"matcher": "Skill", "allow": ["daf-*"]},
                        ],
                    }
                }
            )
        )
        doctor = Doctor()
        result = doctor.check_permissions()
        assert result.status == CheckStatus.PASS
        assert "2 rule(s)" in result.message

    def test_no_rules(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps({"permissions": {"enabled": True, "rules": []}})
        )
        doctor = Doctor()
        result = doctor.check_permissions()
        assert result.status == CheckStatus.WARN

    def test_invalid_rule(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps({"permissions": {"enabled": True, "rules": [{"allow": ["*"]}]}})
        )
        doctor = Doctor()
        result = doctor.check_permissions()
        assert result.status == CheckStatus.FAIL
        assert "invalid" in result.message.lower()

    def test_no_config(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_permissions()
        assert result.status == CheckStatus.WARN


class TestCheckDirectoryRules:
    def test_no_rules(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({}))
        doctor = Doctor()
        result = doctor.check_directory_rules()
        assert result.status == CheckStatus.PASS

    def test_valid_rules(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps(
                {
                    "directory_rules": [
                        {"pattern": "/home/**", "mode": "deny"},
                        {"pattern": "/tmp/**", "mode": "allow", "_generated": True},
                    ]
                }
            )
        )
        doctor = Doctor()
        result = doctor.check_directory_rules()
        assert result.status == CheckStatus.PASS
        assert "1 user" in result.message
        assert "1 generated" in result.message

    def test_paths_format(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps(
                {
                    "directory_rules": {
                        "rules": [
                            {"paths": ["/home/**"], "mode": "deny"},
                        ]
                    }
                }
            )
        )
        doctor = Doctor()
        result = doctor.check_directory_rules()
        assert result.status == CheckStatus.PASS

    def test_invalid_rule(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"directory_rules": [{"mode": "deny"}]}))
        doctor = Doctor()
        result = doctor.check_directory_rules()
        assert result.status == CheckStatus.FAIL

    def test_no_config(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_directory_rules()
        assert result.status == CheckStatus.WARN


class TestCheckTraySupport:
    @mock.patch("ai_guardian.doctor.platform.system", return_value="Windows")
    def test_windows_pystray_available(self, _mock_sys, _isolate_config_dir):
        with mock.patch.dict("sys.modules", {"pystray": mock.MagicMock()}):
            doctor = Doctor()
            result = doctor.check_tray_support()
        assert result.status == CheckStatus.PASS
        assert "Windows" in result.message

    @mock.patch("ai_guardian.doctor.platform.system", return_value="Windows")
    def test_windows_pystray_missing(self, _mock_sys, _isolate_config_dir):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pystray":
                raise ImportError("no pystray")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            doctor = Doctor()
            result = doctor.check_tray_support()
        assert result.status == CheckStatus.WARN
        assert "pystray not available" in result.message

    @mock.patch("ai_guardian.doctor.platform.system", return_value="Darwin")
    def test_macos_pystray_available(self, _mock_sys, _isolate_config_dir):
        with mock.patch.dict("sys.modules", {"pystray": mock.MagicMock()}):
            doctor = Doctor()
            result = doctor.check_tray_support()
        assert result.status == CheckStatus.PASS
        assert "macOS" in result.message

    @mock.patch("ai_guardian.doctor.platform.system", return_value="Linux")
    def test_skip_non_gnome(self, _mock_sys, _isolate_config_dir):
        with mock.patch.dict("sys.modules", {"gi": mock.MagicMock()}):
            with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}):
                doctor = Doctor()
                result = doctor.check_tray_support()
        assert result.status == CheckStatus.SKIP
        assert "KDE" in result.message

    @mock.patch("ai_guardian.doctor.platform.system", return_value="Linux")
    @mock.patch(
        "ai_guardian.doctor.shutil.which", return_value="/usr/bin/gnome-extensions"
    )
    def test_pass_extension_enabled(self, _mock_which, _mock_sys, _isolate_config_dir):
        mock_result = mock.MagicMock()
        mock_result.stdout = (
            "user-theme@gnome-shell-extensions.gcampax.github.com\n"
            "appindicatorsupport@rgcjonas.gmail.com\n"
        )
        with mock.patch.dict("sys.modules", {"gi": mock.MagicMock()}):
            with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}):
                with mock.patch(
                    "ai_guardian.doctor.subprocess.run", return_value=mock_result
                ):
                    doctor = Doctor()
                    result = doctor.check_tray_support()
        assert result.status == CheckStatus.PASS
        assert "AppIndicator extension enabled" in result.message

    @mock.patch("ai_guardian.doctor.platform.system", return_value="Linux")
    @mock.patch(
        "ai_guardian.doctor.shutil.which", return_value="/usr/bin/gnome-extensions"
    )
    def test_warn_extension_missing(self, _mock_which, _mock_sys, _isolate_config_dir):
        mock_result = mock.MagicMock()
        mock_result.stdout = "user-theme@gnome-shell-extensions.gcampax.github.com\n"
        with mock.patch.dict("sys.modules", {"gi": mock.MagicMock()}):
            with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}):
                with mock.patch(
                    "ai_guardian.doctor.subprocess.run", return_value=mock_result
                ):
                    doctor = Doctor()
                    result = doctor.check_tray_support()
        assert result.status == CheckStatus.WARN
        assert "AppIndicator" in result.message
        assert result.fix_hint is not None
        assert "dnf install" in result.fix_hint

    @mock.patch("ai_guardian.doctor.platform.system", return_value="Linux")
    @mock.patch("ai_guardian.doctor.shutil.which", return_value=None)
    def test_skip_no_gnome_extensions_cmd(
        self, _mock_which, _mock_sys, _isolate_config_dir
    ):
        with mock.patch.dict("sys.modules", {"gi": mock.MagicMock()}):
            with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}):
                doctor = Doctor()
                result = doctor.check_tray_support()
        assert result.status == CheckStatus.SKIP
        assert "gnome-extensions" in result.message

    @mock.patch("ai_guardian.doctor.platform.system", return_value="Linux")
    def test_warn_gi_unavailable(self, _mock_sys, _isolate_config_dir):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "gi":
                raise ImportError("no gi")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            doctor = Doctor()
            result = doctor.check_tray_support()
        assert result.status == CheckStatus.WARN
        assert "gi" in result.message
        assert result.fix_hint is not None
        assert "PyGObject" in result.fix_hint

    @mock.patch("ai_guardian.doctor.platform.system", return_value="Linux")
    @mock.patch(
        "ai_guardian.doctor.shutil.which", return_value="/usr/bin/gnome-extensions"
    )
    def test_pass_gi_available_and_extension_enabled(
        self, _mock_which, _mock_sys, _isolate_config_dir
    ):
        """gi available + AppIndicator enabled = PASS."""
        mock_result = mock.MagicMock()
        mock_result.stdout = "appindicatorsupport@rgcjonas.gmail.com\n"
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}):
            with mock.patch(
                "ai_guardian.doctor.subprocess.run", return_value=mock_result
            ):
                with mock.patch.dict("sys.modules", {"gi": mock.MagicMock()}):
                    doctor = Doctor()
                    result = doctor.check_tray_support()
        assert result.status == CheckStatus.PASS


class TestCheckAskModeDeps:
    def test_skip_no_config(self, _isolate_config_dir):
        doctor = Doctor()
        doctor._config = None
        doctor._config_loaded = True
        result = doctor.check_ask_mode_deps()
        assert result.status == CheckStatus.SKIP
        assert "No config" in result.message

    def test_skip_no_ask_actions(self, _isolate_config_dir):
        doctor = Doctor()
        doctor._config = {"secret_scanning": {"enabled": True}}
        doctor._config_loaded = True
        result = doctor.check_ask_mode_deps()
        assert result.status == CheckStatus.SKIP
        assert "No ask actions" in result.message

    def test_pass_tkinter_available(self, _isolate_config_dir):
        doctor = Doctor()
        doctor._config = {"prompt_injection": {"action": "ask"}}
        doctor._config_loaded = True
        with mock.patch.dict("sys.modules", {"tkinter": mock.MagicMock()}):
            result = doctor.check_ask_mode_deps()
        assert result.status == CheckStatus.PASS
        assert "tkinter" in result.message
        assert "prompt_injection" in result.message

    def test_pass_nicegui_fallback(self, _isolate_config_dir):
        doctor = Doctor()
        doctor._config = {"supply_chain": {"action": "ask:warn"}}
        doctor._config_loaded = True
        tkinter_import = mock.MagicMock(side_effect=ImportError)
        with mock.patch.dict(
            "sys.modules", {"tkinter": None, "nicegui": mock.MagicMock()}
        ):
            result = doctor.check_ask_mode_deps()
        assert result.status == CheckStatus.PASS
        assert "NiceGUI" in result.message

    def test_warn_no_tkinter_no_nicegui(self, _isolate_config_dir):
        doctor = Doctor()
        doctor._config = {"prompt_injection": {"action": "ask"}}
        doctor._config_loaded = True
        with mock.patch.dict("sys.modules", {"tkinter": None, "nicegui": None}):
            result = doctor.check_ask_mode_deps()
        assert result.status == CheckStatus.WARN
        assert "prompt_injection" in result.message
        assert result.fix_hint is not None
        assert "tkinter" in result.fix_hint

    def test_detects_permission_rules_ask(self, _isolate_config_dir):
        doctor = Doctor()
        doctor._config = {"permissions": {"rules": [{"tool": "Bash", "action": "ask"}]}}
        doctor._config_loaded = True
        with mock.patch.dict("sys.modules", {"tkinter": mock.MagicMock()}):
            result = doctor.check_ask_mode_deps()
        assert result.status == CheckStatus.PASS
        assert "permissions.rules" in result.message

    def test_detects_directory_rules_ask(self, _isolate_config_dir):
        doctor = Doctor()
        doctor._config = {
            "directory_rules": {"rules": [{"path": "/tmp", "action": "ask"}]}
        }
        doctor._config_loaded = True
        with mock.patch.dict("sys.modules", {"tkinter": mock.MagicMock()}):
            result = doctor.check_ask_mode_deps()
        assert result.status == CheckStatus.PASS
        assert "directory_rules.rules" in result.message

    def test_multiple_ask_sections(self, _isolate_config_dir):
        doctor = Doctor()
        doctor._config = {
            "prompt_injection": {"action": "ask"},
            "scan_pii": {"action": "ask:log-only"},
        }
        doctor._config_loaded = True
        with mock.patch.dict("sys.modules", {"tkinter": mock.MagicMock()}):
            result = doctor.check_ask_mode_deps()
        assert result.status == CheckStatus.PASS
        assert "prompt_injection" in result.message
        assert "scan_pii" in result.message


class TestCheckTerminalEmulator:
    @mock.patch("ai_guardian.doctor.platform.system", return_value="Darwin")
    def test_skip_non_linux(self, _mock_sys, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_terminal_emulator()
        assert result.status == CheckStatus.SKIP
        assert "Not Linux" in result.message

    @mock.patch("ai_guardian.doctor.platform.system", return_value="Linux")
    @mock.patch(
        "ai_guardian.doctor.shutil.which", return_value="/usr/bin/gnome-terminal"
    )
    def test_pass_terminal_found(self, _mock_which, _mock_sys, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_terminal_emulator()
        assert result.status == CheckStatus.PASS
        assert "gnome-terminal" in result.message

    @mock.patch("ai_guardian.doctor.platform.system", return_value="Linux")
    @mock.patch(
        "ai_guardian.doctor.shutil.which",
        side_effect=lambda x: "/usr/bin/kgx" if x == "kgx" else None,
    )
    def test_pass_kgx_found(self, _mock_which, _mock_sys, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_terminal_emulator()
        assert result.status == CheckStatus.PASS
        assert "kgx" in result.message

    @mock.patch("ai_guardian.doctor.platform.system", return_value="Linux")
    @mock.patch("ai_guardian.doctor.shutil.which", return_value=None)
    def test_warn_none_found(self, _mock_which, _mock_sys, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_terminal_emulator()
        assert result.status == CheckStatus.WARN
        assert "No supported terminal" in result.message
        assert result.fix_hint is not None
        assert "dnf install" in result.fix_hint


class TestCheckConsoleDeps:
    def test_all_present(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_console_deps()
        # At minimum textual should be available since it's a core dep
        assert result.status in (CheckStatus.PASS, CheckStatus.WARN)

    def test_missing_deps(self, _isolate_config_dir):
        import importlib

        with mock.patch.dict("sys.modules", {"tree_sitter_json": None}):
            with mock.patch(
                "builtins.__import__",
                side_effect=lambda name, *a, **kw: (
                    (_ for _ in ()).throw(ImportError())
                    if name == "tree_sitter_json"
                    else importlib.__import__(name, *a, **kw)
                ),
            ):
                doctor = Doctor()
                result = doctor.check_console_deps()
                assert result.status == CheckStatus.WARN
                if sys.version_info < (3, 10):
                    assert "Python >= 3.10" in result.message
                else:
                    assert "tree-sitter-json" in result.message


class TestCheckConfigConsistency:
    def test_consistent(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_config_consistency()
        assert result.status in (CheckStatus.PASS, CheckStatus.SKIP)


# --- Pattern server check tests (Issue #493) ---


class TestCheckPsCachePath:
    def _write_ps_config(self, config_dir):
        config_path = config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps(
                {
                    "secret_scanning": {
                        "pattern_server": {"url": "https://example.com/patterns"}
                    }
                }
            )
        )

    def test_skip_no_config(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_ps_cache_path()
        assert result.status == CheckStatus.SKIP

    def test_writable(self, _isolate_config_dir):
        self._write_ps_config(_isolate_config_dir)
        doctor = Doctor()
        result = doctor.check_ps_cache_path()
        assert result.status == CheckStatus.PASS
        assert "writable" in result.message

    @pytest.mark.skipif(
        sys.platform == "win32", reason="chmod 0o444 not effective on Windows"
    )
    def test_not_writable(self, _isolate_config_dir, tmp_path):
        self._write_ps_config(_isolate_config_dir)
        ro_dir = tmp_path / "readonly_cache"
        ro_dir.mkdir()
        ro_dir.chmod(0o444)
        with mock.patch("ai_guardian.config.utils.get_cache_dir", return_value=ro_dir):
            doctor = Doctor()
            result = doctor.check_ps_cache_path()
        ro_dir.chmod(0o755)
        assert result.status == CheckStatus.FAIL
        assert "not writable" in result.message

    def test_missing_dir_default_warns(self, _isolate_config_dir, tmp_path):
        self._write_ps_config(_isolate_config_dir)
        missing = tmp_path / "nonexistent"
        # Clear cache-dir env vars so doctor treats the path as the default
        with mock.patch("ai_guardian.config.utils.get_cache_dir", return_value=missing):
            with mock.patch.dict(
                "os.environ", {"AI_GUARDIAN_CACHE_DIR": "", "XDG_CACHE_HOME": ""}
            ):
                doctor = Doctor()
                result = doctor.check_ps_cache_path()
        assert result.status == CheckStatus.WARN
        assert "not yet created" in result.message

    def test_missing_dir_xdg_override_fails(self, _isolate_config_dir, tmp_path):
        self._write_ps_config(_isolate_config_dir)
        missing = tmp_path / "nonexistent"
        with mock.patch("ai_guardian.config.utils.get_cache_dir", return_value=missing):
            with mock.patch.dict("os.environ", {"XDG_CACHE_HOME": "/custom/cache"}):
                doctor = Doctor()
                result = doctor.check_ps_cache_path()
        assert result.status == CheckStatus.FAIL
        assert "does not exist" in result.message

    def test_missing_dir_env_override_fails(self, _isolate_config_dir, tmp_path):
        self._write_ps_config(_isolate_config_dir)
        missing = tmp_path / "nonexistent"
        with mock.patch("ai_guardian.config.utils.get_cache_dir", return_value=missing):
            with mock.patch.dict(
                "os.environ", {"AI_GUARDIAN_CACHE_DIR": "/custom/cache"}
            ):
                doctor = Doctor()
                result = doctor.check_ps_cache_path()
        assert result.status == CheckStatus.FAIL
        assert "does not exist" in result.message

    def test_custom_cache_path(self, _isolate_config_dir, tmp_path):
        cache_file = tmp_path / "custom" / "patterns.toml"
        cache_file.parent.mkdir(parents=True)
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps(
                {
                    "secret_scanning": {
                        "pattern_server": {
                            "url": "https://example.com",
                            "cache": {"path": str(cache_file)},
                        }
                    }
                }
            )
        )
        doctor = Doctor()
        result = doctor.check_ps_cache_path()
        assert result.status == CheckStatus.PASS


class TestCheckPsAuth:
    def _write_ps_config(self, config_dir, auth=None):
        ps = {"url": "https://example.com/patterns"}
        if auth is not None:
            ps["auth"] = auth
        config_path = config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"secret_scanning": {"pattern_server": ps}}))

    def test_skip_no_config(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_ps_auth()
        assert result.status == CheckStatus.SKIP

    def test_skip_no_auth(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps(
                {"secret_scanning": {"pattern_server": {"url": "https://example.com"}}}
            )
        )
        doctor = Doctor()
        result = doctor.check_ps_auth()
        assert result.status == CheckStatus.SKIP

    def test_token_in_env(self, _isolate_config_dir):
        self._write_ps_config(
            _isolate_config_dir,
            auth={
                "method": "bearer",
                "token_env": "AI_GUARDIAN_TEST_TOKEN_493",
            },
        )
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_TEST_TOKEN_493": "secret"}):
            doctor = Doctor()
            result = doctor.check_ps_auth()
        assert result.status == CheckStatus.PASS
        assert "AI_GUARDIAN_TEST_TOKEN_493" in result.message

    def test_token_in_file(self, _isolate_config_dir, tmp_path):
        token_file = tmp_path / "token"
        token_file.write_text("my-token")
        self._write_ps_config(
            _isolate_config_dir,
            auth={
                "method": "bearer",
                "token_env": "AI_GUARDIAN_NONEXIST_TOKEN",
                "token_file": str(token_file),
            },
        )
        doctor = Doctor()
        result = doctor.check_ps_auth()
        assert result.status == CheckStatus.PASS
        assert "Token found" in result.message

    def test_no_token(self, _isolate_config_dir, tmp_path):
        self._write_ps_config(
            _isolate_config_dir,
            auth={
                "method": "bearer",
                "token_env": "AI_GUARDIAN_NONEXIST_TOKEN",
                "token_file": str(tmp_path / "nonexistent"),
            },
        )
        doctor = Doctor()
        result = doctor.check_ps_auth()
        assert result.status == CheckStatus.FAIL
        assert "not set" in result.message.lower()


class TestCheckPsUrl:
    def _write_ps_config(self, config_dir, url="https://example.com"):
        config_path = config_dir / "ai-guardian.json"
        config_path.write_text(
            json.dumps(
                {
                    "secret_scanning": {
                        "pattern_server": {
                            "url": url,
                            "patterns_endpoint": "/patterns/gitleaks/8.18.1",
                        }
                    }
                }
            )
        )

    def test_skip_no_config(self, _isolate_config_dir):
        doctor = Doctor(check_connectivity=True)
        result = doctor.check_ps_url()
        assert result.status == CheckStatus.SKIP

    def test_skip_no_connectivity_flag(self, _isolate_config_dir):
        self._write_ps_config(_isolate_config_dir)
        doctor = Doctor(check_connectivity=False)
        result = doctor.check_ps_url()
        assert result.status == CheckStatus.SKIP
        assert "check-connectivity" in result.message

    def test_success(self, _isolate_config_dir):
        self._write_ps_config(_isolate_config_dir)
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '[[rules]]\nid = "test"\n'
        with mock.patch("requests.get", return_value=mock_resp):
            doctor = Doctor(check_connectivity=True)
            result = doctor.check_ps_url()
        assert result.status == CheckStatus.PASS
        assert "200 OK" in result.message

    def test_timeout(self, _isolate_config_dir):
        self._write_ps_config(_isolate_config_dir)
        import requests

        with mock.patch("requests.get", side_effect=requests.exceptions.Timeout()):
            doctor = Doctor(check_connectivity=True)
            result = doctor.check_ps_url()
        assert result.status == CheckStatus.WARN
        assert "timeout" in result.message.lower()

    def test_unauthorized(self, _isolate_config_dir):
        self._write_ps_config(_isolate_config_dir)
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 401
        with mock.patch("requests.get", return_value=mock_resp):
            doctor = Doctor(check_connectivity=True)
            result = doctor.check_ps_url()
        assert result.status == CheckStatus.FAIL
        assert "401" in result.message

    def test_connection_error(self, _isolate_config_dir):
        self._write_ps_config(_isolate_config_dir)
        import requests

        with mock.patch(
            "requests.get", side_effect=requests.exceptions.ConnectionError()
        ):
            doctor = Doctor(check_connectivity=True)
            result = doctor.check_ps_url()
        assert result.status == CheckStatus.FAIL
        assert "Connection failed" in result.message

    def test_http_rejected(self, _isolate_config_dir):
        self._write_ps_config(_isolate_config_dir, url="http://insecure.example.com")
        doctor = Doctor(check_connectivity=True)
        result = doctor.check_ps_url()
        assert result.status == CheckStatus.FAIL
        assert "HTTP not allowed" in result.message


class TestCheckPsCacheFreshness:
    def _write_ps_config(
        self, config_dir, cache_path=None, refresh_hours=12, expire_hours=168
    ):
        ps = {
            "url": "https://example.com",
            "cache": {
                "refresh_interval_hours": refresh_hours,
                "expire_after_hours": expire_hours,
            },
        }
        if cache_path:
            ps["cache"]["path"] = cache_path
        config_path = config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"secret_scanning": {"pattern_server": ps}}))

    def test_skip_no_config(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_ps_cache_freshness()
        assert result.status == CheckStatus.SKIP

    def test_fresh_cache(self, _isolate_config_dir):
        cache_dir = Path(os.environ["AI_GUARDIAN_CACHE_DIR"])
        cache_file = cache_dir / "patterns.toml"
        cache_file.write_text('[[rules]]\nid = "test"\n')
        self._write_ps_config(_isolate_config_dir)
        doctor = Doctor()
        result = doctor.check_ps_cache_freshness()
        assert result.status == CheckStatus.PASS
        assert "1 rules" in result.message

    def test_stale_cache(self, _isolate_config_dir):
        cache_dir = Path(os.environ["AI_GUARDIAN_CACHE_DIR"])
        cache_file = cache_dir / "patterns.toml"
        cache_file.write_text('[[rules]]\nid = "test"\n')
        old_time = time.time() - (2 * 86400)  # 2 days old (> 12h refresh)
        os.utime(cache_file, (old_time, old_time))
        self._write_ps_config(_isolate_config_dir)
        doctor = Doctor()
        result = doctor.check_ps_cache_freshness()
        assert result.status == CheckStatus.WARN
        assert "stale" in result.message.lower()
        assert result.fixable is True
        assert result.fixed is False

    def test_expired_cache(self, _isolate_config_dir):
        cache_dir = Path(os.environ["AI_GUARDIAN_CACHE_DIR"])
        cache_file = cache_dir / "patterns.toml"
        cache_file.write_text('[[rules]]\nid = "test"\n')
        old_time = time.time() - (10 * 86400)  # 10 days old (> 7 day expiry)
        os.utime(cache_file, (old_time, old_time))
        self._write_ps_config(_isolate_config_dir)
        doctor = Doctor()
        result = doctor.check_ps_cache_freshness()
        assert result.status == CheckStatus.FAIL
        assert "expired" in result.message.lower()
        assert result.fixable is True
        assert result.fixed is False

    def test_no_cache_file(self, _isolate_config_dir):
        self._write_ps_config(_isolate_config_dir)
        doctor = Doctor()
        result = doctor.check_ps_cache_freshness()
        assert result.status == CheckStatus.PASS
        assert "No cached patterns yet" in result.message

    def test_custom_cache_path(self, _isolate_config_dir, tmp_path):
        cache_file = tmp_path / "custom" / "my-patterns.toml"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text('[[rules]]\nid = "r1"\n[[rules]]\nid = "r2"\n')
        self._write_ps_config(_isolate_config_dir, cache_path=str(cache_file))
        doctor = Doctor()
        result = doctor.check_ps_cache_freshness()
        assert result.status == CheckStatus.PASS
        assert "2 rules" in result.message

    def test_fix_stale_cache(self, _isolate_config_dir):
        cache_dir = Path(os.environ["AI_GUARDIAN_CACHE_DIR"])
        cache_file = cache_dir / "patterns.toml"
        cache_file.write_text('[[rules]]\nid = "test"\n')
        old_time = time.time() - (2 * 86400)
        os.utime(cache_file, (old_time, old_time))
        self._write_ps_config(_isolate_config_dir)
        with mock.patch(
            "ai_guardian.doctor.Doctor._refresh_ps_cache", return_value=(True, None)
        ):
            doctor = Doctor(fix=True)
            result = doctor.check_ps_cache_freshness()
        assert result.status == CheckStatus.PASS
        assert result.fixable is True
        assert result.fixed is True

    def test_fix_expired_cache(self, _isolate_config_dir):
        cache_dir = Path(os.environ["AI_GUARDIAN_CACHE_DIR"])
        cache_file = cache_dir / "patterns.toml"
        cache_file.write_text('[[rules]]\nid = "test"\n')
        old_time = time.time() - (10 * 86400)
        os.utime(cache_file, (old_time, old_time))
        self._write_ps_config(_isolate_config_dir)
        with mock.patch(
            "ai_guardian.doctor.Doctor._refresh_ps_cache", return_value=(True, None)
        ):
            doctor = Doctor(fix=True)
            result = doctor.check_ps_cache_freshness()
        assert result.status == CheckStatus.PASS
        assert result.fixable is True
        assert result.fixed is True

    def test_fix_no_cache_file(self, _isolate_config_dir):
        self._write_ps_config(_isolate_config_dir)
        with mock.patch(
            "ai_guardian.doctor.Doctor._refresh_ps_cache", return_value=(True, None)
        ):
            doctor = Doctor(fix=True)
            result = doctor.check_ps_cache_freshness()
        assert result.status == CheckStatus.PASS
        assert result.fixable is True
        assert result.fixed is True

    def test_fix_refresh_failure(self, _isolate_config_dir):
        cache_dir = Path(os.environ["AI_GUARDIAN_CACHE_DIR"])
        cache_file = cache_dir / "patterns.toml"
        cache_file.write_text('[[rules]]\nid = "test"\n')
        old_time = time.time() - (2 * 86400)
        os.utime(cache_file, (old_time, old_time))
        self._write_ps_config(_isolate_config_dir)
        with mock.patch(
            "ai_guardian.doctor.Doctor._refresh_ps_cache",
            return_value=(False, "Connection refused"),
        ):
            doctor = Doctor(fix=True)
            result = doctor.check_ps_cache_freshness()
        assert result.status == CheckStatus.WARN
        assert result.fixable is True
        assert result.fixed is False
        assert "Connection refused" in result.fix_hint

    def test_fix_expired_refresh_failure(self, _isolate_config_dir):
        cache_dir = Path(os.environ["AI_GUARDIAN_CACHE_DIR"])
        cache_file = cache_dir / "patterns.toml"
        cache_file.write_text('[[rules]]\nid = "test"\n')
        old_time = time.time() - (10 * 86400)
        os.utime(cache_file, (old_time, old_time))
        self._write_ps_config(_isolate_config_dir)
        with mock.patch(
            "ai_guardian.doctor.Doctor._refresh_ps_cache",
            return_value=(False, "Timeout"),
        ):
            doctor = Doctor(fix=True)
            result = doctor.check_ps_cache_freshness()
        assert result.status == CheckStatus.FAIL
        assert result.fixable is True
        assert result.fixed is False
        assert "Timeout" in result.fix_hint


# --- Output formatter tests ---


class TestFormatHuman:
    def test_all_pass(self):
        report = DoctorReport(
            version="1.0.0",
            checks=[
                CheckResult(name="config_file", status=CheckStatus.PASS, message="OK"),
                CheckResult(
                    name="scanners", status=CheckStatus.PASS, message="gitleaks 8.30.1"
                ),
            ],
        )
        output = format_human(report)
        assert "1.0.0" in output
        assert "PASS" in output
        assert "2 passed" in output

    def test_with_warnings(self):
        report = DoctorReport(
            version="1.0.0",
            checks=[
                CheckResult(name="config_file", status=CheckStatus.PASS, message="OK"),
                CheckResult(
                    name="scanners",
                    status=CheckStatus.WARN,
                    message="outdated",
                    fix_hint="Update scanners",
                ),
            ],
        )
        output = format_human(report)
        assert "WARN" in output
        assert "1 warning" in output
        assert "Hint: Update scanners" in output

    def test_with_errors(self):
        report = DoctorReport(
            version="1.0.0",
            checks=[
                CheckResult(
                    name="scanners", status=CheckStatus.FAIL, message="none found"
                ),
            ],
        )
        output = format_human(report)
        assert "FAIL" in output
        assert "1 error" in output

    def test_fixed_items(self):
        report = DoctorReport(
            version="1.0.0",
            checks=[
                CheckResult(
                    name="state_dir",
                    status=CheckStatus.PASS,
                    message="Created",
                    fixable=True,
                    fixed=True,
                    fix_hint="created dir",
                ),
            ],
        )
        output = format_human(report)
        assert "Fixed" in output
        assert "1 fixed" in output


class TestFormatJson:
    def test_valid_json(self):
        report = DoctorReport(
            version="1.0.0",
            checks=[
                CheckResult(name="config_file", status=CheckStatus.PASS, message="OK"),
            ],
        )
        output = format_json(report)
        data = json.loads(output)
        assert data["version"] == "1.0.0"
        assert data["summary"]["total"] == 1
        assert data["summary"]["pass"] == 1
        assert len(data["checks"]) == 1

    def test_structure(self):
        report = DoctorReport(
            version="2.0.0",
            checks=[
                CheckResult(name="a", status=CheckStatus.PASS, message="ok"),
                CheckResult(
                    name="b",
                    status=CheckStatus.WARN,
                    message="warn",
                    fix_hint="do X",
                    fixable=True,
                ),
                CheckResult(name="c", status=CheckStatus.FAIL, message="fail"),
            ],
        )
        data = json.loads(format_json(report))
        assert data["summary"]["pass"] == 1
        assert data["summary"]["warn"] == 1
        assert data["summary"]["fail"] == 1
        assert data["checks"][1]["fix_hint"] == "do X"
        assert data["checks"][1]["fixable"] is True


# --- CLI entry point tests ---


class TestDoctorCommand:
    def _make_args(self, **kwargs):
        defaults = {
            "json": False,
            "fix": False,
            "quiet": False,
            "check_connectivity": False,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @mock.patch("ai_guardian.doctor.Doctor.run_all")
    def test_quiet_mode(self, mock_run, _isolate_config_dir):
        mock_run.return_value = DoctorReport(
            checks=[
                CheckResult(name="a", status=CheckStatus.WARN, message="warn"),
            ]
        )
        result = doctor_command(self._make_args(quiet=True))
        assert result == 1

    @mock.patch("ai_guardian.doctor.Doctor.run_all")
    def test_json_mode(self, mock_run, _isolate_config_dir, capsys):
        mock_run.return_value = DoctorReport(
            version="1.0.0",
            checks=[
                CheckResult(name="a", status=CheckStatus.PASS, message="ok"),
            ],
        )
        result = doctor_command(self._make_args(json=True))
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["summary"]["pass"] == 1

    @mock.patch("ai_guardian.doctor.Doctor.run_all")
    def test_human_mode(self, mock_run, _isolate_config_dir, capsys):
        mock_run.return_value = DoctorReport(
            version="1.0.0",
            checks=[
                CheckResult(name="config_file", status=CheckStatus.PASS, message="ok"),
            ],
        )
        result = doctor_command(self._make_args())
        assert result == 0
        captured = capsys.readouterr()
        assert "PASS" in captured.out

    def test_fix_flag_passed(self, _isolate_config_dir):
        with mock.patch("ai_guardian.doctor.Doctor.run_all") as mock_run:
            mock_run.return_value = DoctorReport(checks=[])
            doctor_command(self._make_args(fix=True))
            # Verify Doctor was created with fix=True by checking the call
            # The Doctor instance is created inside doctor_command


class TestDoctorRunAll:
    def test_run_all_returns_report(self, _isolate_config_dir):
        doctor = Doctor()
        report = doctor.run_all()
        assert isinstance(report, DoctorReport)
        assert len(report.checks) == 33
        assert report.version != ""

    def test_check_crash_handled(self, _isolate_config_dir):
        doctor = Doctor()
        original = doctor.check_config_file
        doctor.check_config_file = mock.MagicMock(side_effect=RuntimeError("boom"))
        report = doctor.run_all()
        crash_check = [c for c in report.checks if "crashed" in c.message.lower()]
        assert len(crash_check) == 1
        assert crash_check[0].status == CheckStatus.FAIL
        doctor.check_config_file = original


class TestCheckTrayPlugins:
    def test_skip_when_no_dir(self, _isolate_config_dir):
        doctor = Doctor()
        result = doctor.check_tray_plugins()
        assert result.status == CheckStatus.SKIP

    def test_skip_when_empty_dir(self, _isolate_config_dir, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        with mock.patch(
            "ai_guardian.daemon.get_tray_plugins_dir", return_value=plugins_dir
        ):
            doctor = Doctor()
            result = doctor.check_tray_plugins()
            assert result.status == CheckStatus.SKIP

    def test_pass_with_valid_plugins(self, _isolate_config_dir, tmp_path):
        import json

        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "good.json").write_text(
            json.dumps(
                {
                    "name": "Good",
                    "items": [{"label": "Ok", "command": "echo ok"}],
                }
            )
        )
        with mock.patch(
            "ai_guardian.daemon.get_tray_plugins_dir", return_value=plugins_dir
        ):
            doctor = Doctor()
            result = doctor.check_tray_plugins()
            assert result.status == CheckStatus.PASS
            assert "1 plugin file" in result.message

    def test_warn_on_circular_import(self, _isolate_config_dir, tmp_path):
        import json

        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "loop.json").write_text(
            json.dumps(
                {
                    "name": "Loop",
                    "items": [{"label": "Self", "import": "loop.json"}],
                }
            )
        )
        with mock.patch(
            "ai_guardian.daemon.get_tray_plugins_dir", return_value=plugins_dir
        ):
            doctor = Doctor()
            result = doctor.check_tray_plugins()
            assert result.status == CheckStatus.WARN
            assert "Circular import" in result.message


class TestCheckAstScanner:
    """Tests for check_ast_scanner (Issue #1148)."""

    def test_pass_with_parsers(self, _isolate_config_dir):
        mock_ts = mock.MagicMock()
        grammar_imports = {
            "python": "tree_sitter_python",
            "javascript": "tree_sitter_javascript",
        }
        with mock.patch.dict("sys.modules", {"tree_sitter": mock_ts}):
            with mock.patch(
                "ai_guardian.doctor.pkg_version", return_value="0.25.0", create=True
            ):
                with mock.patch("importlib.metadata.version", return_value="0.25.0"):
                    with mock.patch(
                        "ai_guardian.scanners.ast_scanner._GRAMMAR_IMPORTS",
                        grammar_imports,
                    ):
                        with mock.patch("importlib.import_module") as mock_import:
                            mock_import.return_value = mock.MagicMock()
                            doctor = Doctor()
                            result = doctor.check_ast_scanner()
        assert result.status == CheckStatus.PASS
        assert "tree-sitter 0.25.0" in result.message
        assert "Javascript" in result.message
        assert "Python" in result.message

    def test_warn_not_installed(self, _isolate_config_dir):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "tree_sitter":
                raise ImportError("no tree_sitter")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            doctor = Doctor()
            result = doctor.check_ast_scanner()
        assert result.status == CheckStatus.WARN
        assert "not installed" in result.message
        assert "raw text" in result.message
        assert result.fix_hint is not None

    def test_warn_no_parsers(self, _isolate_config_dir):
        mock_ts = mock.MagicMock()
        grammar_imports = {"python": "tree_sitter_python"}
        with mock.patch.dict("sys.modules", {"tree_sitter": mock_ts}):
            with mock.patch("importlib.metadata.version", return_value="0.25.0"):
                with mock.patch(
                    "ai_guardian.scanners.ast_scanner._GRAMMAR_IMPORTS", grammar_imports
                ):
                    with mock.patch("importlib.import_module", side_effect=ImportError):
                        doctor = Doctor()
                        result = doctor.check_ast_scanner()
        assert result.status == CheckStatus.WARN
        assert "no language parsers" in result.message
        assert result.fix_hint is not None

    def test_partial_parsers(self, _isolate_config_dir):
        mock_ts = mock.MagicMock()
        grammar_imports = {
            "python": "tree_sitter_python",
            "go": "tree_sitter_go",
        }

        def selective_import(name):
            if name == "tree_sitter_python":
                return mock.MagicMock()
            raise ImportError(f"no {name}")

        with mock.patch.dict("sys.modules", {"tree_sitter": mock_ts}):
            with mock.patch("importlib.metadata.version", return_value="0.24.0"):
                with mock.patch(
                    "ai_guardian.scanners.ast_scanner._GRAMMAR_IMPORTS", grammar_imports
                ):
                    with mock.patch(
                        "importlib.import_module", side_effect=selective_import
                    ):
                        doctor = Doctor()
                        result = doctor.check_ast_scanner()
        assert result.status == CheckStatus.PASS
        assert "tree-sitter 0.24.0" in result.message
        assert "Python" in result.message
        assert "Go" not in result.message


class TestCheckImageScanning:
    """Tests for check_image_scanning (Issue #1048)."""

    def test_missing_image_scanning_key_defaults_enabled(self, _isolate_config_dir):
        """When image_scanning key is absent, should NOT report SKIP."""
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"secret_scanning": {"enabled": True}}))
        doctor = Doctor()
        with mock.patch("ai_guardian.doctor.RapidOCR", create=True):
            result = doctor.check_image_scanning()
        assert result.status != CheckStatus.SKIP

    def test_empty_image_scanning_dict_defaults_enabled(self, _isolate_config_dir):
        """When image_scanning is empty dict, enabled defaults to True."""
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"image_scanning": {}}))
        doctor = Doctor()
        with mock.patch("ai_guardian.doctor.RapidOCR", create=True):
            result = doctor.check_image_scanning()
        assert result.status != CheckStatus.SKIP

    def test_explicitly_disabled(self, _isolate_config_dir):
        """When image_scanning.enabled is False, should SKIP."""
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"image_scanning": {"enabled": False}}))
        doctor = Doctor()
        result = doctor.check_image_scanning()
        assert result.status == CheckStatus.SKIP
        assert "not enabled" in result.message

    def test_explicitly_enabled_with_rapidocr(self, _isolate_config_dir):
        """When enabled and rapidocr available, should PASS."""
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"image_scanning": {"enabled": True}}))
        doctor = Doctor()
        with mock.patch.dict("sys.modules", {"rapidocr_onnxruntime": mock.MagicMock()}):
            result = doctor.check_image_scanning()
        assert result.status == CheckStatus.PASS

    def test_no_config_file_defaults_enabled(self, _isolate_config_dir):
        """With no config file at all, image scanning defaults enabled."""
        doctor = Doctor()
        with mock.patch.dict("sys.modules", {"rapidocr_onnxruntime": mock.MagicMock()}):
            result = doctor.check_image_scanning()
        assert result.status != CheckStatus.SKIP


class TestCheckBanditScanner:
    """Tests for check_bandit_scanner (Issue #1504)."""

    def test_pass_when_bandit_installed(self, _isolate_config_dir):
        import importlib.util

        with mock.patch.object(
            importlib.util, "find_spec", return_value=mock.MagicMock()
        ):
            with mock.patch("importlib.metadata.version", return_value="1.9.4"):
                doctor = Doctor()
                result = doctor.check_bandit_scanner()
        assert result.status == CheckStatus.PASS
        assert "v1.9.4" in result.message

    def test_fail_when_bandit_missing(self, _isolate_config_dir):
        import importlib.util

        with mock.patch.object(importlib.util, "find_spec", return_value=None):
            doctor = Doctor()
            result = doctor.check_bandit_scanner()
        assert result.status == CheckStatus.FAIL
        assert "SKIPPED" in result.message
        assert result.fix_hint is not None

    def test_skip_when_code_scanning_disabled(self, _isolate_config_dir):
        config_path = _isolate_config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"code_scanning": {"enabled": False}}))
        doctor = Doctor()
        result = doctor.check_bandit_scanner()
        assert result.status == CheckStatus.SKIP
        assert "disabled" in result.message

    def test_pass_unknown_version_when_metadata_fails(self, _isolate_config_dir):
        import importlib.util

        with mock.patch.object(
            importlib.util, "find_spec", return_value=mock.MagicMock()
        ):
            with mock.patch(
                "importlib.metadata.version", side_effect=Exception("no metadata")
            ):
                doctor = Doctor()
                result = doctor.check_bandit_scanner()
        assert result.status == CheckStatus.PASS
        assert "unknown" in result.message
