"""Tests that all violation log entries include file_path and line_number fields (Issue #349)."""

import json
import os
import tempfile
from unittest import mock


class TestToolPermissionViolationFilePath:
    """Test that tool_permission violations include file_path for file-path tools."""

    @mock.patch("ai_guardian.tools.policy.ViolationLogger")
    @mock.patch("ai_guardian.tools.policy.HAS_VIOLATION_LOGGER", True)
    def test_file_path_present_for_read_tool(self, mock_vl_class):
        from ai_guardian.tools.policy import ToolPolicyChecker

        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        checker = ToolPolicyChecker(
            config={"permissions": {"enabled": True, "rules": []}}
        )
        checker._log_violation(
            tool_name="Read",
            check_value="/home/user/secret.txt",
            reason="blocked by policy",
            matcher="Read",
            hook_data={},
        )
        mock_logger.log_violation.assert_called_once()
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert blocked["file_path"] == "/home/user/secret.txt"

    @mock.patch("ai_guardian.tools.policy.ViolationLogger")
    @mock.patch("ai_guardian.tools.policy.HAS_VIOLATION_LOGGER", True)
    def test_file_path_present_for_write_tool(self, mock_vl_class):
        from ai_guardian.tools.policy import ToolPolicyChecker

        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        checker = ToolPolicyChecker(
            config={"permissions": {"enabled": True, "rules": []}}
        )
        checker._log_violation(
            tool_name="Write",
            check_value="/home/user/config.json",
            reason="blocked by policy",
            matcher="Write",
            hook_data={},
        )
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert blocked["file_path"] == "/home/user/config.json"

    @mock.patch("ai_guardian.tools.policy.ViolationLogger")
    @mock.patch("ai_guardian.tools.policy.HAS_VIOLATION_LOGGER", True)
    def test_file_path_present_for_edit_tool(self, mock_vl_class):
        from ai_guardian.tools.policy import ToolPolicyChecker

        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        checker = ToolPolicyChecker(
            config={"permissions": {"enabled": True, "rules": []}}
        )
        checker._log_violation(
            tool_name="Edit",
            check_value="/home/user/main.py",
            reason="blocked by policy",
            matcher="Edit",
            hook_data={},
        )
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert blocked["file_path"] == "/home/user/main.py"

    @mock.patch("ai_guardian.tools.policy.ViolationLogger")
    @mock.patch("ai_guardian.tools.policy.HAS_VIOLATION_LOGGER", True)
    def test_file_path_present_for_notebook_edit_tool(self, mock_vl_class):
        from ai_guardian.tools.policy import ToolPolicyChecker

        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        checker = ToolPolicyChecker(
            config={"permissions": {"enabled": True, "rules": []}}
        )
        checker._log_violation(
            tool_name="NotebookEdit",
            check_value="/home/user/notebook.ipynb",
            reason="blocked by policy",
            matcher="NotebookEdit",
            hook_data={},
        )
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert blocked["file_path"] == "/home/user/notebook.ipynb"

    @mock.patch("ai_guardian.tools.policy.ViolationLogger")
    @mock.patch("ai_guardian.tools.policy.HAS_VIOLATION_LOGGER", True)
    def test_file_path_none_for_bash_tool(self, mock_vl_class):
        from ai_guardian.tools.policy import ToolPolicyChecker

        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        checker = ToolPolicyChecker(
            config={"permissions": {"enabled": True, "rules": []}}
        )
        checker._log_violation(
            tool_name="Bash",
            check_value="rm -rf /",
            reason="blocked by policy",
            matcher="Bash",
            hook_data={},
        )
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert blocked["file_path"] is None

    @mock.patch("ai_guardian.tools.policy.ViolationLogger")
    @mock.patch("ai_guardian.tools.policy.HAS_VIOLATION_LOGGER", True)
    def test_file_path_none_for_skill_tool(self, mock_vl_class):
        from ai_guardian.tools.policy import ToolPolicyChecker

        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        checker = ToolPolicyChecker(
            config={"permissions": {"enabled": True, "rules": []}}
        )
        checker._log_violation(
            tool_name="Skill",
            check_value="some-skill",
            reason="blocked by policy",
            matcher="Skill",
            hook_data={},
        )
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert blocked["file_path"] is None


class TestPromptInjectionViolationFilePath:
    """Test that prompt_injection violations include file_path from context."""

    def test_file_path_from_context(self):

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                with mock.patch(
                    "ai_guardian.hook_events.post_tool_use.HAS_VIOLATION_LOGGER", True
                ):
                    from ai_guardian import _log_prompt_injection_violation

                    with mock.patch(
                        "ai_guardian.hook_events.post_tool_use.ViolationLogger"
                    ) as mock_vl_class:
                        mock_logger = mock.MagicMock()
                        mock_vl_class.return_value = mock_logger

                        _log_prompt_injection_violation(
                            "malicious.md",
                            context={
                                "ide_type": "claude_code",
                                "hook_event": "pretooluse",
                                "file_path": "/full/path/malicious.md",
                            },
                            attack_type="injection",
                        )
                        mock_logger.log_violation.assert_called_once()
                        blocked = mock_logger.log_violation.call_args[1]["blocked"]
                        assert blocked["file_path"] == "/full/path/malicious.md"

    def test_file_path_falls_back_to_filename(self):
        with mock.patch(
            "ai_guardian.hook_events.post_tool_use.HAS_VIOLATION_LOGGER", True
        ):
            from ai_guardian import _log_prompt_injection_violation

            with mock.patch(
                "ai_guardian.hook_events.post_tool_use.ViolationLogger"
            ) as mock_vl_class:
                mock_logger = mock.MagicMock()
                mock_vl_class.return_value = mock_logger

                _log_prompt_injection_violation(
                    "malicious.md",
                    context={"ide_type": "claude_code", "hook_event": "pretooluse"},
                    attack_type="injection",
                )
                blocked = mock_logger.log_violation.call_args[1]["blocked"]
                assert blocked["file_path"] == "malicious.md"

    def test_file_path_none_for_user_prompt(self):
        with mock.patch(
            "ai_guardian.hook_events.post_tool_use.HAS_VIOLATION_LOGGER", True
        ):
            from ai_guardian import _log_prompt_injection_violation

            with mock.patch(
                "ai_guardian.hook_events.post_tool_use.ViolationLogger"
            ) as mock_vl_class:
                mock_logger = mock.MagicMock()
                mock_vl_class.return_value = mock_logger

                _log_prompt_injection_violation(
                    "user_prompt",
                    context={"ide_type": "claude_code", "hook_event": "prompt"},
                    attack_type="injection",
                )
                blocked = mock_logger.log_violation.call_args[1]["blocked"]
                assert blocked["file_path"] is None


class TestJailbreakViolationFilePath:
    """Test that jailbreak_detected violations include file_path from context."""

    def test_file_path_from_context(self):
        with mock.patch(
            "ai_guardian.hook_events.post_tool_use.HAS_VIOLATION_LOGGER", True
        ):
            from ai_guardian import _log_prompt_injection_violation

            with mock.patch(
                "ai_guardian.hook_events.post_tool_use.ViolationLogger"
            ) as mock_vl_class:
                mock_logger = mock.MagicMock()
                mock_vl_class.return_value = mock_logger

                _log_prompt_injection_violation(
                    "evil.py",
                    context={
                        "ide_type": "claude_code",
                        "hook_event": "pretooluse",
                        "file_path": "/repo/evil.py",
                    },
                    attack_type="jailbreak",
                )
                call_kwargs = mock_logger.log_violation.call_args[1]
                assert call_kwargs["violation_type"] == "jailbreak_detected"
                assert call_kwargs["blocked"]["file_path"] == "/repo/evil.py"


class TestSecretRedactionViolationFields:
    """Test that secret_redaction violations include file_path and line_number."""

    def test_fields_present(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                vl.log_violation(
                    violation_type="secret_redaction",
                    blocked={
                        "tool": "Read",
                        "file_path": None,
                        "line_number": None,
                        "redaction_count": 2,
                        "redacted_types": ["api_key", "password"],
                    },
                    context={"action": "redacted", "mode": "redact"},
                )
                violations = vl.get_recent_violations(limit=10)
                assert len(violations) == 1
                blocked = violations[0]["blocked"]
                assert "file_path" in blocked
                assert "line_number" in blocked


class TestPIIViolationFilePath:
    """Test that pii_detected violations include file_path and line_number."""

    def test_pretooluse_pii_has_file_path(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                vl.log_violation(
                    violation_type="pii_detected",
                    blocked={
                        "tool": "Read",
                        "hook": "PreToolUse",
                        "file_path": "/home/user/data.csv",
                        "line_number": None,
                        "pii_count": 3,
                        "pii_types": ["email", "phone"],
                    },
                    context={"action": "block", "hook_event": "pretooluse"},
                )
                violations = vl.get_recent_violations(limit=10)
                assert len(violations) == 1
                blocked = violations[0]["blocked"]
                assert blocked["file_path"] == "/home/user/data.csv"
                assert "line_number" in blocked

    def test_posttooluse_pii_has_null_file_path(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                vl.log_violation(
                    violation_type="pii_detected",
                    blocked={
                        "tool": "Bash",
                        "hook": "PostToolUse",
                        "file_path": None,
                        "line_number": None,
                        "pii_count": 1,
                        "pii_types": ["ssn"],
                    },
                    context={"action": "block", "hook_event": "posttooluse"},
                )
                violations = vl.get_recent_violations(limit=10)
                assert len(violations) == 1
                blocked = violations[0]["blocked"]
                assert blocked["file_path"] is None
                assert blocked["line_number"] is None


class TestConfigFileExfilViolationFields:
    """Test that config_file_exfil violations include line_number field."""

    def test_line_number_present(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                vl.log_violation(
                    violation_type="config_file_exfil",
                    blocked={
                        "file_path": "/etc/shadow",
                        "line_number": None,
                        "reason": "config exfiltration",
                        "details": "sensitive config file",
                    },
                    context={"hook_event": "pretooluse"},
                    severity="critical",
                )
                violations = vl.get_recent_violations(limit=10)
                assert len(violations) == 1
                blocked = violations[0]["blocked"]
                assert blocked["file_path"] == "/etc/shadow"
                assert "line_number" in blocked


class TestSecretDetectedViolationFieldsUnchanged:
    """Verify that secret_detected violations still work correctly with existing fields."""

    def test_line_number_preserved(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                vl.log_violation(
                    violation_type="secret_detected",
                    blocked={
                        "file_path": "/repo/config.py",
                        "source": "file",
                        "secret_type": "aws-access-key",
                        "reason": "Gitleaks detected sensitive information",
                        "line_number": 42,
                        "end_line": 42,
                    },
                    context={
                        "ide_type": "claude_code",
                        "hook_event": "pretooluse",
                        "project_path": "/repo",
                    },
                    severity="critical",
                )
                violations = vl.get_recent_violations(limit=10)
                assert len(violations) == 1
                blocked = violations[0]["blocked"]
                assert blocked["file_path"] == "/repo/config.py"
                assert blocked["line_number"] == 42
                assert blocked["end_line"] == 42


class TestAllViolationTypesHaveFilePath:
    """Integration test: every violation type's blocked dict includes file_path."""

    def _log_and_get(self, violation_type, blocked, context=None, severity="warning"):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                vl.log_violation(
                    violation_type=violation_type,
                    blocked=blocked,
                    context=context or {},
                    severity=severity,
                )
                violations = vl.get_recent_violations(limit=10)
                assert len(violations) == 1
                return violations[0]["blocked"]

    def test_tool_permission_has_file_path_key(self):
        blocked = self._log_and_get(
            "tool_permission",
            {
                "tool_name": "Read",
                "tool_value": "/etc/passwd",
                "file_path": "/etc/passwd",
                "matcher": "Read",
                "reason": "denied",
            },
        )
        assert "file_path" in blocked

    def test_directory_blocking_has_file_path_key(self):
        blocked = self._log_and_get(
            "directory_blocking",
            {
                "file_path": "/repo/.secrets/key",
                "denied_directory": "/repo/.secrets",
                "reason": ".ai-read-deny marker found",
                "exclusion_overridden": False,
            },
        )
        assert "file_path" in blocked

    def test_secret_detected_has_file_path_key(self):
        blocked = self._log_and_get(
            "secret_detected",
            {
                "file_path": "/repo/config.py",
                "source": "file",
                "secret_type": "generic",
                "reason": "detected",
                "line_number": 10,
            },
            severity="critical",
        )
        assert "file_path" in blocked
        assert "line_number" in blocked

    def test_prompt_injection_has_file_path_key(self):
        blocked = self._log_and_get(
            "prompt_injection",
            {
                "file_path": "/repo/readme.md",
                "source": "file",
                "pattern": "test",
                "confidence": 0.95,
                "method": "heuristic",
                "reason": "detected",
            },
            severity="high",
        )
        assert "file_path" in blocked

    def test_jailbreak_detected_has_file_path_key(self):
        blocked = self._log_and_get(
            "jailbreak_detected",
            {
                "file_path": "/repo/evil.py",
                "source": "file",
                "pattern": "test",
                "confidence": 0.95,
                "method": "heuristic",
                "reason": "detected",
            },
            severity="high",
        )
        assert "file_path" in blocked

    def test_secret_redaction_has_file_path_key(self):
        blocked = self._log_and_get(
            "secret_redaction",
            {
                "tool": "Read",
                "file_path": None,
                "line_number": None,
                "redaction_count": 1,
                "redacted_types": ["api_key"],
            },
        )
        assert "file_path" in blocked
        assert "line_number" in blocked

    def test_pii_detected_has_file_path_key(self):
        blocked = self._log_and_get(
            "pii_detected",
            {
                "tool": "Read",
                "hook": "PreToolUse",
                "file_path": "/repo/data.csv",
                "line_number": None,
                "pii_count": 1,
                "pii_types": ["email"],
            },
        )
        assert "file_path" in blocked
        assert "line_number" in blocked

    def test_config_file_exfil_has_file_path_key(self):
        blocked = self._log_and_get(
            "config_file_exfil",
            {
                "file_path": "/etc/shadow",
                "line_number": None,
                "reason": "exfil",
                "details": "sensitive",
            },
            severity="critical",
        )
        assert "file_path" in blocked
        assert "line_number" in blocked

    def test_ssrf_blocked_has_file_path_key_via_tool_policy(self):
        blocked = self._log_and_get(
            "ssrf_blocked",
            {
                "tool_name": "Bash",
                "tool_value": "curl http://169.254.169.254",
                "file_path": None,
                "matcher": "Bash",
                "reason": "SSRF",
            },
        )
        assert "file_path" in blocked


class TestSecretRedactorLineNumber:
    """Test that SecretRedactor.redact() includes line_number in redaction entries (Issue #359)."""

    def test_line_number_on_first_line(self):
        """PII on line 1 should return line_number=1."""
        from ai_guardian.scanners.secret_redactor import SecretRedactor

        redactor = SecretRedactor(
            config={"enabled": True},
            pii_config={"enabled": True, "pii_types": ["email"]},
            pii_only=True,
        )
        result = redactor.redact("contact: user@example.com")
        redactions = result.get("redactions", [])
        assert len(redactions) >= 1
        assert redactions[0]["line_number"] == 1
        assert "column" in redactions[0]

    def test_line_number_on_third_line(self):
        """PII on line 3 should return line_number=3."""
        from ai_guardian.scanners.secret_redactor import SecretRedactor

        redactor = SecretRedactor(
            config={"enabled": True},
            pii_config={"enabled": True, "pii_types": ["email"]},
            pii_only=True,
        )
        text = "line one\nline two\ncontact: user@example.com\nline four"
        result = redactor.redact(text)
        redactions = result.get("redactions", [])
        assert len(redactions) >= 1
        assert redactions[0]["line_number"] == 3
        assert redactions[0]["column"] == len("contact: ") + 1

    def test_line_number_multiple_redactions(self):
        """Multiple PII items on different lines should each have correct line_number."""
        from ai_guardian.scanners.secret_redactor import SecretRedactor

        redactor = SecretRedactor(
            config={"enabled": True},
            pii_config={"enabled": True, "pii_types": ["email"]},
            pii_only=True,
        )
        text = "email: alice@example.com\nno pii here\nemail: bob@example.com"
        result = redactor.redact(text)
        redactions = result.get("redactions", [])
        assert len(redactions) >= 2
        line_numbers = [r["line_number"] for r in redactions]
        assert 1 in line_numbers
        assert 3 in line_numbers

    def test_column_position_correct(self):
        """Column should be the 1-based position within the line."""
        from ai_guardian.scanners.secret_redactor import SecretRedactor

        redactor = SecretRedactor(
            config={"enabled": True},
            pii_config={"enabled": True, "pii_types": ["email"]},
            pii_only=True,
        )
        text = "first line\nsecond: user@example.com"
        result = redactor.redact(text)
        redactions = result.get("redactions", [])
        assert len(redactions) >= 1
        r = redactions[0]
        assert r["line_number"] == 2
        assert r["column"] == len("second: ") + 1


class TestPIIWarningMessageFilePathLineNumber:
    """Test that _scan_for_pii warning message includes file_path and line numbers (#1010)."""

    def test_warning_includes_file_path(self):
        from ai_guardian.hook_processing import _scan_for_pii

        text = "My SSN is 123-45-6789"
        pii_config = {"enabled": True, "pii_types": ["ssn"], "action": "block"}
        has_pii, _, _, warning = _scan_for_pii(
            text, pii_config, file_path="/repo/data.csv"
        )
        assert has_pii
        assert "File: /repo/data.csv" in warning

    def test_warning_includes_line_numbers(self):
        from ai_guardian.hook_processing import _scan_for_pii

        text = "line one\nline two\nMy email is user@example.com\nline four"
        pii_config = {"enabled": True, "pii_types": ["email"], "action": "block"}
        has_pii, _, _, warning = _scan_for_pii(
            text, pii_config, file_path="/repo/data.txt"
        )
        assert has_pii
        assert "(line " in warning

    def test_warning_no_file_path_omits_file_line(self):
        from ai_guardian.hook_processing import _scan_for_pii

        text = "My SSN is 123-45-6789"
        pii_config = {"enabled": True, "pii_types": ["ssn"], "action": "block"}
        has_pii, _, _, warning = _scan_for_pii(text, pii_config)
        assert has_pii
        assert "File:" not in warning
        assert "PII DETECTED" in warning

    def test_warning_long_path_truncated(self):
        from ai_guardian.hook_processing import _scan_for_pii

        long_path = "/very/long/" + "x" * 150 + "/data.csv"
        text = "My SSN is 123-45-6789"
        pii_config = {"enabled": True, "pii_types": ["ssn"], "action": "block"}
        has_pii, _, _, warning = _scan_for_pii(text, pii_config, file_path=long_path)
        assert has_pii
        assert "..." in warning
        assert long_path not in warning

    def test_warning_multiple_types_on_different_lines(self):
        from ai_guardian.hook_processing import _scan_for_pii

        text = "SSN: 123-45-6789\nno pii\nemail: user@example.com"
        pii_config = {"enabled": True, "pii_types": ["ssn", "email"], "action": "block"}
        has_pii, _, redactions, warning = _scan_for_pii(
            text, pii_config, file_path="/repo/data.txt"
        )
        assert has_pii
        assert "File: /repo/data.txt" in warning
        assert "(line " in warning


class TestPIIViolationLineNumberPopulated:
    """Test that PII violation logging populates line_number from redactions (Issue #359)."""

    @mock.patch("ai_guardian.config.loaders._load_pii_config")
    @mock.patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @mock.patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @mock.patch("ai_guardian.config.loaders._load_prompt_injection_config")
    def test_pretooluse_pii_line_number_populated(
        self, mock_pi, mock_ss, mock_gitleaks, mock_pii
    ):
        """PreToolUse PII violations should have actual line_number, not None."""
        from io import StringIO

        mock_pi.return_value = (None, None)
        mock_ss.return_value = (None, None)
        mock_gitleaks.return_value = (False, None)
        mock_pii.return_value = (
            {
                "enabled": True,
                "pii_types": ["email"],
                "action": "block",
                "ignore_files": [],
                "ignore_tools": [],
            },
            None,
        )

        file_content = "line one\nline two\ncontact: user@example.com\nline four"
        hook_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/test_data.txt", "content": file_content},
        }

        with mock.patch(
            "ai_guardian.hook_events.post_tool_use.ViolationLogger"
        ) as mock_vl_class:
            mock_logger = mock.MagicMock()
            mock_vl_class.return_value = mock_logger

            with mock.patch(
                "ai_guardian.hook_processing.extract_file_content_from_tool"
            ) as mock_extract:
                mock_extract.return_value = (
                    file_content,
                    "test_data.txt",
                    "/tmp/test_data.txt",
                    False,
                    None,
                    None,
                )

                with mock.patch("sys.stdin", StringIO(json.dumps(hook_data))):
                    import ai_guardian

                    ai_guardian.process_hook_input()

            if mock_logger.log_violation.called:
                for call in mock_logger.log_violation.call_args_list:
                    kwargs = call[1] if call[1] else {}
                    if kwargs.get("violation_type") == "pii_detected":
                        blocked = kwargs["blocked"]
                        assert (
                            blocked["line_number"] is not None
                        ), f"Expected line_number to be populated, got None. blocked={blocked}"
                        assert (
                            blocked["line_number"] == 3
                        ), f"Expected line_number=3, got {blocked['line_number']}"
                        break
