"""Tests for --log-violations flag on scan command and setup --pre-commit."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class TestLogViolationsFlagScan:
    """Tests for scan --log-violations writing findings to violations.jsonl."""

    def test_log_violations_writes_to_jsonl(self, tmp_path):
        """--log-violations writes each finding to violations.jsonl."""
        from ai_guardian.scanners.file_scanner import _log_scan_findings

        findings = [
            {
                "rule_id": "SECRET-001",
                "message": "AWS key detected",
                "file_path": "app.py",
                "line_number": 10,
                "snippet": "AKIA...",
            },
            {
                "rule_id": "PROMPT-INJECTION-001",
                "message": "Prompt injection detected",
                "file_path": "prompt.txt",
                "line_number": 1,
                "snippet": "ignore previous instructions",
            },
        ]
        args = SimpleNamespace(path=".")

        with patch("ai_guardian.violations.logger.ViolationLogger") as MockLogger:
            mock_instance = MagicMock()
            MockLogger.return_value = mock_instance
            _log_scan_findings(findings, args)

            assert mock_instance.log_violation.call_count == 2

            first_call = mock_instance.log_violation.call_args_list[0]
            assert first_call.kwargs["violation_type"] == "secret_detected"
            assert first_call.kwargs["blocked"]["rule_id"] == "SECRET-001"
            assert first_call.kwargs["context"]["hook_event"] == "scan"
            assert first_call.kwargs["context"]["ide_type"] == "cli"

            second_call = mock_instance.log_violation.call_args_list[1]
            assert second_call.kwargs["violation_type"] == "prompt_injection"

    def test_log_violations_not_called_when_flag_absent(self, tmp_path):
        """Without --log-violations, no violations are logged."""
        from ai_guardian.scanners.file_scanner import scan_command

        test_file = tmp_path / "clean.txt"
        test_file.write_text("nothing here")
        args = SimpleNamespace(
            path=str(tmp_path),
            text=None,
            config=None,
            verbose=False,
            sarif_output=None,
            json_output=None,
            exit_code=False,
            log_violations=False,
            include=None,
            exclude=None,
            config_only=False,
            agent_configs=False,
            diff=False,
            staged=False,
            pr=None,
            mr=None,
            stdin_diff=False,
            changed_lines_only=False,
            base=None,
        )

        with patch("ai_guardian.scanners.file_scanner._log_scan_findings") as mock_log:
            scan_command(args)
            mock_log.assert_not_called()

    def test_violation_type_mapping(self):
        """rule_id prefixes map to correct violation types."""
        from ai_guardian.scanners.file_scanner import _violation_type_from_rule_id

        assert _violation_type_from_rule_id("SECRET-001") == "secret_detected"
        assert (
            _violation_type_from_rule_id("PROMPT-INJECTION-001") == "prompt_injection"
        )
        assert _violation_type_from_rule_id("PII-001") == "pii_detected"
        assert _violation_type_from_rule_id("SSRF-001") == "ssrf_blocked"
        assert _violation_type_from_rule_id("CONFIG-001") == "config_file_exfil"
        assert _violation_type_from_rule_id("EXFIL-DETECTION-001") == "exfil_detection"
        assert _violation_type_from_rule_id("UNICODE-001") == "prompt_injection"
        assert _violation_type_from_rule_id("SUPPLY-CHAIN-001") == "supply_chain"
        assert _violation_type_from_rule_id("canary_detected") == "canary_detection"
        assert _violation_type_from_rule_id("B101") == "code_security"
        assert _violation_type_from_rule_id("B605") == "code_security"
        assert _violation_type_from_rule_id("UNKNOWN-099") == "scan_finding"
        assert _violation_type_from_rule_id("") == "scan_finding"

    def test_log_failures_are_non_fatal(self, tmp_path):
        """ViolationLogger errors don't crash the scan."""
        from ai_guardian.scanners.file_scanner import _log_scan_findings

        findings = [{"rule_id": "SECRET-001", "message": "test", "file_path": "a.py"}]
        args = SimpleNamespace(path=".")

        with patch(
            "ai_guardian.violations.logger.ViolationLogger",
            side_effect=RuntimeError("boom"),
        ):
            _log_scan_findings(findings, args)


class TestLogViolationsFlagSetup:
    """Tests for setup --pre-commit --log-violations."""

    def test_install_precommit_includes_log_violations_in_message(self, tmp_path):
        """--log-violations adds flag to displayed hook commands."""
        from ai_guardian.setup.hooks import install_precommit_hooks

        git_dir = tmp_path / ".git" / "hooks"
        git_dir.mkdir(parents=True)

        with (
            patch(
                "ai_guardian.setup.hooks.subprocess.check_output",
                return_value=str(tmp_path),
            ),
            patch(
                "ai_guardian.setup.hooks.subprocess.run",
                side_effect=FileNotFoundError,
            ),
        ):
            success, message = install_precommit_hooks(
                log_violations=True, dry_run=True
            )
            assert "--log-violations" in message

    def test_install_precommit_without_log_violations(self, tmp_path):
        """Without --log-violations, the flag doesn't appear in output."""
        from ai_guardian.setup.hooks import install_precommit_hooks

        git_dir = tmp_path / ".git" / "hooks"
        git_dir.mkdir(parents=True)

        with (
            patch(
                "ai_guardian.setup.hooks.subprocess.check_output",
                return_value=str(tmp_path),
            ),
            patch(
                "ai_guardian.setup.hooks.subprocess.run",
                side_effect=FileNotFoundError,
            ),
        ):
            success, message = install_precommit_hooks(
                log_violations=False, dry_run=True
            )
            assert "--log-violations" not in message

    def test_auto_install_git_hook_with_log_violations(self, tmp_path):
        """Auto-install injects --log-violations into the git hook script."""
        from ai_guardian.setup.hooks import _auto_install_hook

        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)

        template = tmp_path / "pre-commit.sh"
        template.write_text(
            "#!/bin/bash\nai-guardian scan --diff --staged --exit-code\n"
        )
        yaml_template = tmp_path / ".pre-commit-config.yaml"
        yaml_template.write_text("entry: ai-guardian scan --exit-code\n")

        with patch(
            "ai_guardian.setup.hooks.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            success, message = _auto_install_hook(
                tmp_path, hooks_dir, template, yaml_template, log_violations=True
            )
            assert success

            hook_content = (hooks_dir / "pre-commit").read_text()
            assert "--log-violations" in hook_content
            assert "scan --diff --staged --exit-code --log-violations" in hook_content

    def test_auto_install_git_hook_without_log_violations(self, tmp_path):
        """Auto-install without flag preserves original template."""
        from ai_guardian.setup.hooks import _auto_install_hook

        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)

        template = tmp_path / "pre-commit.sh"
        template.write_text(
            "#!/bin/bash\nai-guardian scan --diff --staged --exit-code\n"
        )
        yaml_template = tmp_path / ".pre-commit-config.yaml"
        yaml_template.write_text("entry: ai-guardian scan --exit-code\n")

        with patch(
            "ai_guardian.setup.hooks.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            success, message = _auto_install_hook(
                tmp_path, hooks_dir, template, yaml_template, log_violations=False
            )

            hook_content = (hooks_dir / "pre-commit").read_text()
            assert "--log-violations" not in hook_content
