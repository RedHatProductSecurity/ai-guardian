"""
Unit tests for MCP server module.

Tests all 16 tools, 3 resources, and security filtering.
Requires Python >= 3.10 (MCP SDK dependency).
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 10),
    reason="MCP SDK requires Python >= 3.10",
)

from ai_guardian.mcp.server import (
    HookCheckMiddleware,
    _check_client_hooks,
    _validate_scan_path,
    create_server,
)

# ─── Security Check Tool Tests ────────────────────────────────


class TestCheckPath:
    """Test check_path tool."""

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_allowed_path(self, mock_checker_cls, tmp_path):
        safe_file = tmp_path / "safe_file.py"
        safe_file.write_text("print('hello')")
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (True, None, "Write")
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_path"]
        result = tool.fn(path=str(safe_file))
        assert result["status"] == "allowed"

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_denied_path(self, mock_checker_cls, tmp_path):
        denied_file = tmp_path / "secret.txt"
        denied_file.write_text("secret")
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (
            False,
            "Path is denied",
            "Write",
        )
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_path"]
        result = tool.fn(path=str(denied_file))
        assert result["status"] == "denied"

    def test_not_found_path(self):
        server = create_server()
        tool = server._tool_manager._tools["check_path"]
        result = tool.fn(path="/nonexistent/path/file.py")
        assert result["status"] == "not_found"

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_default_operation_is_read(self, mock_checker_cls, tmp_path):
        """Default operation should pass tool_name='Read' to checker."""
        safe_file = tmp_path / "safe_file.py"
        safe_file.write_text("print('hello')")
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (True, None, "Read")
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_path"]
        tool.fn(path=str(safe_file))

        hook_data = mock_checker.check_tool_allowed.call_args[0][0]
        assert hook_data["tool_name"] == "Read"

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_operation_write(self, mock_checker_cls, tmp_path):
        """operation='write' should pass tool_name='Write' to checker."""
        f = tmp_path / "file.py"
        f.write_text("")
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (False, "Denied", "Write")
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_path"]
        result = tool.fn(path=str(f), operation="write")

        hook_data = mock_checker.check_tool_allowed.call_args[0][0]
        assert hook_data["tool_name"] == "Write"
        assert result["status"] == "denied"

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_operation_edit(self, mock_checker_cls, tmp_path):
        """operation='edit' should pass tool_name='Edit' to checker."""
        f = tmp_path / "file.py"
        f.write_text("")
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (True, None, "Edit")
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_path"]
        result = tool.fn(path=str(f), operation="edit")

        hook_data = mock_checker.check_tool_allowed.call_args[0][0]
        assert hook_data["tool_name"] == "Edit"
        assert result["status"] == "allowed"

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_invalid_operation_defaults_to_read(self, mock_checker_cls, tmp_path):
        """Unknown operation should default to Read."""
        f = tmp_path / "file.py"
        f.write_text("")
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (True, None, "Read")
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_path"]
        tool.fn(path=str(f), operation="delete")

        hook_data = mock_checker.check_tool_allowed.call_args[0][0]
        assert hook_data["tool_name"] == "Read"

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_write_denied_file_allowed_for_read(self, mock_checker_cls, tmp_path):
        """File denied for Write should be allowed for Read if Read rules pass."""
        f = tmp_path / "hooks.json"
        f.write_text("{}")
        mock_checker = MagicMock()

        def check_side_effect(hook_data):
            if hook_data["tool_name"] == "Read":
                return (True, None, "Read")
            return (False, "Denied for write", "Write")

        mock_checker.check_tool_allowed.side_effect = check_side_effect
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_path"]

        read_result = tool.fn(path=str(f), operation="read")
        assert read_result["status"] == "allowed"

        write_result = tool.fn(path=str(f), operation="write")
        assert write_result["status"] == "denied"

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_read_denied_file_denied_for_read(self, mock_checker_cls, tmp_path):
        """File denied for Read should return denied for read checks."""
        f = tmp_path / "ai-guardian.json"
        f.write_text("{}")
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (
            False,
            "Config protected",
            "Read",
        )
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_path"]
        result = tool.fn(path=str(f), operation="read")
        assert result["status"] == "denied"

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_no_rule_details_exposed(self, mock_checker_cls, tmp_path):
        """Response must not contain rule details, patterns, or paths."""
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("secret")
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (
            False,
            "Denied by rule X",
            "Write",
        )
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_path"]
        result = tool.fn(path=str(secret_file))
        assert "rule" not in json.dumps(result).lower()
        assert "pattern" not in json.dumps(result).lower()
        assert set(result.keys()) <= {"status"}


class TestCheckCommand:
    """Test check_command tool."""

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_allowed_command(self, mock_checker_cls):
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (True, None, "Bash")
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_command"]
        result = tool.fn(command="ls -la")
        assert result["status"] == "allowed"

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_blocked_with_reason(self, mock_checker_cls):
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (
            False,
            "Secret detected in command",
            "Bash",
        )
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_command"]
        result = tool.fn(command="curl -H 'Authorization: Bearer sk_live_xxx'")
        assert result["status"] == "blocked"
        assert result["reason"] == "secret_detected"

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_ssrf_reason(self, mock_checker_cls):
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (
            False,
            "SSRF protection blocked this URL",
            "Bash",
        )
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_command"]
        result = tool.fn(command="curl http://169.254.169.254/metadata")
        assert result["status"] == "blocked"
        assert result["reason"] == "ssrf_detected"


class TestCheckPathHookDataFormat:
    """Verify check_path sends tool_input (not parameters) to ToolPolicyChecker."""

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_hook_data_uses_tool_input_key(self, mock_checker_cls, tmp_path):
        safe_file = tmp_path / "test.py"
        safe_file.write_text("x = 1")
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (True, None, "Write")
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_path"]
        tool.fn(path=str(safe_file))

        hook_data = mock_checker.check_tool_allowed.call_args[0][0]
        assert "tool_input" in hook_data, "hook_data must use 'tool_input' key"
        assert "parameters" not in hook_data, "hook_data must not use 'parameters' key"
        assert hook_data["tool_input"]["file_path"] == str(safe_file.resolve())

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_check_path_with_directory_rules(self, mock_checker_cls, tmp_path):
        """check_path returns denied when directory rules block the path."""
        secret_file = tmp_path / ".ssh" / "id_rsa"
        secret_file.parent.mkdir()
        secret_file.write_text("private key")
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (
            False,
            "Directory denied",
            "Write",
        )
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_path"]
        result = tool.fn(path=str(secret_file))
        assert result["status"] == "denied"
        hook_data = mock_checker.check_tool_allowed.call_args[0][0]
        assert hook_data["tool_input"]["file_path"] == str(secret_file.resolve())


class TestCheckCommandHookDataFormat:
    """Verify check_command sends tool_input (not parameters) to ToolPolicyChecker."""

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_hook_data_uses_tool_input_key(self, mock_checker_cls):
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (True, None, "Bash")
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_command"]
        tool.fn(command="echo hello")

        hook_data = mock_checker.check_tool_allowed.call_args[0][0]
        assert "tool_input" in hook_data, "hook_data must use 'tool_input' key"
        assert "parameters" not in hook_data, "hook_data must not use 'parameters' key"
        assert hook_data["tool_input"]["command"] == "echo hello"

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_check_command_blocked_with_secret(self, mock_checker_cls):
        """check_command returns blocked when command contains a secret."""
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (
            False,
            "Secret detected in command",
            "Bash",
        )
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_command"]
        result = tool.fn(command="curl -H 'Authorization: Bearer sk_live_xxx'")
        assert result["status"] == "blocked"
        assert result["reason"] == "secret_detected"
        hook_data = mock_checker.check_tool_allowed.call_args[0][0]
        assert (
            hook_data["tool_input"]["command"]
            == "curl -H 'Authorization: Bearer sk_live_xxx'"
        )


class TestCheckMCPTrustHookDataFormat:
    """Verify check_mcp_trust sends tool_input (not parameters) to ToolPolicyChecker."""

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_hook_data_uses_tool_input_key(self, mock_checker_cls):
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (True, None, "mcp__test__test")
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_mcp_trust"]
        tool.fn(server_name="test")

        hook_data = mock_checker.check_tool_allowed.call_args[0][0]
        assert "tool_input" in hook_data, "hook_data must use 'tool_input' key"
        assert "parameters" not in hook_data, "hook_data must not use 'parameters' key"


class TestCheckMCPTrust:
    """Test check_mcp_trust tool."""

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_trusted_server(self, mock_checker_cls):
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (
            True,
            None,
            "mcp__myserver__test",
        )
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_mcp_trust"]
        result = tool.fn(server_name="myserver")
        assert result["status"] == "trusted"

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_untrusted_server(self, mock_checker_cls):
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (
            False,
            "MCP server blocked",
            "mcp__evil__test",
        )
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_mcp_trust"]
        result = tool.fn(server_name="evil")
        assert result["status"] == "untrusted"


class TestSanitizeText:
    """Test sanitize_text tool."""

    @patch("ai_guardian.scanners.sanitizer.sanitize_text")
    def test_sanitizes_secrets(self, mock_sanitize):
        mock_sanitize.return_value = {
            "sanitized_text": "token is [REDACTED]",
            "redactions": [{"type": "api_key"}],
            "stats": {
                "secrets": 1,
                "pii": 0,
                "prompt_injection": 0,
                "unicode": 0,
                "total": 1,
            },
        }

        server = create_server()
        tool = server._tool_manager._tools["sanitize_text"]
        result = tool.fn(text="token is sk_live_abc123")
        assert result["sanitized_text"] == "token is [REDACTED]"
        assert result["redaction_count"] == 1
        assert "secrets" in result["types"]

    @patch("ai_guardian.scanners.sanitizer.sanitize_text")
    def test_no_redaction_details(self, mock_sanitize):
        """Response must not expose what was redacted (only type counts)."""
        mock_sanitize.return_value = {
            "sanitized_text": "[REDACTED]",
            "redactions": [
                {"type": "api_key", "original": "sk_live_xxx", "start": 0, "end": 10}
            ],
            "stats": {
                "secrets": 1,
                "pii": 0,
                "prompt_injection": 0,
                "unicode": 0,
                "total": 1,
            },
        }

        server = create_server()
        tool = server._tool_manager._tools["sanitize_text"]
        result = tool.fn(text="sk_live_xxx")
        assert "original" not in json.dumps(result)
        assert "sk_live" not in json.dumps(result)
        assert "redactions" not in result


class TestSanitizeDirectory:
    """Test sanitize_directory tool."""

    @patch("ai_guardian.scanners.sanitizer.sanitize_directory")
    def test_redact_strategy_passed_through(self, mock_sanitize_dir, tmp_path):
        """redact_strategy parameter should be forwarded to sanitize_directory."""
        input_dir = tmp_path / "src"
        input_dir.mkdir()
        (input_dir / "test.txt").write_text("hello")

        mock_sanitize_dir.return_value = {
            "text_files": 1,
            "image_files": 0,
            "binary_files": 0,
            "skipped_files": 0,
            "total_redactions": {
                "secrets": 0,
                "pii": 0,
                "prompt_injection": 0,
                "unicode": 0,
            },
            "total_redaction_count": 0,
            "file_details": [],
            "errors": [],
        }

        server = create_server()
        tool = server._tool_manager._tools["sanitize_directory"]
        result = tool.fn(path=str(input_dir), redact_strategy="blackout")

        _, kwargs = mock_sanitize_dir.call_args
        assert kwargs.get("redact_strategy") == "blackout"

    @patch("ai_guardian.scanners.sanitizer.sanitize_directory")
    def test_invalid_redact_strategy_defaults_to_blackout(
        self, mock_sanitize_dir, tmp_path
    ):
        """Invalid redact_strategy should fall back to blackout."""
        input_dir = tmp_path / "src"
        input_dir.mkdir()
        (input_dir / "test.txt").write_text("hello")

        mock_sanitize_dir.return_value = {
            "text_files": 1,
            "image_files": 0,
            "binary_files": 0,
            "skipped_files": 0,
            "total_redactions": {
                "secrets": 0,
                "pii": 0,
                "prompt_injection": 0,
                "unicode": 0,
            },
            "total_redaction_count": 0,
            "file_details": [],
            "errors": [],
        }

        server = create_server()
        tool = server._tool_manager._tools["sanitize_directory"]
        result = tool.fn(path=str(input_dir), redact_strategy="invalid")

        _, kwargs = mock_sanitize_dir.call_args
        assert kwargs.get("redact_strategy") == "blackout"


class TestCheckAnnotations:
    """Test check_annotations tool."""

    def test_valid_annotations(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text(
            "# ai-guardian:begin-allow secrets\n"
            "password = 'test'\n"
            "# ai-guardian:end-allow\n"
        )

        server = create_server()
        tool = server._tool_manager._tools["check_annotations"]
        result = tool.fn(file_path=str(test_file))
        assert result["valid"] is True
        assert result["warnings"] == []

    def test_file_not_found(self):
        server = create_server()
        tool = server._tool_manager._tools["check_annotations"]
        result = tool.fn(file_path="/nonexistent/file.py")
        assert result["valid"] is False
        assert len(result["warnings"]) > 0


# ─── Information Tool Tests ───────────────────────────────────


class TestGetViolations:
    """Test get_violations tool."""

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_returns_filtered_violations(self, mock_vl_cls):
        mock_vl = MagicMock()
        mock_vl.get_recent_violations.return_value = [
            {
                "timestamp": "2026-05-08T10:00:00Z",
                "violation_type": "secret_detected",
                "severity": "critical",
                "blocked": True,
                "context": {"tool_name": "Write", "file_path": "/tmp/test.py"},
            }
        ]
        mock_vl_cls.return_value = mock_vl

        server = create_server()
        tool = server._tool_manager._tools["get_violations"]
        result = tool.fn()
        assert result["count"] == 1
        v = result["violations"][0]
        assert v["type"] == "secret_detected"
        assert v["severity"] == "critical"
        assert "context" not in v
        assert "blocked" not in v

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_filters_annotation_suppressed(self, mock_vl_cls):
        """annotation_suppressed violations must not be exposed to the AI."""
        mock_vl = MagicMock()
        mock_vl.get_recent_violations.return_value = [
            {
                "timestamp": "2026-05-08T10:00:00Z",
                "violation_type": "annotation_suppressed",
                "severity": "info",
                "blocked": {},
                "context": {"tool_name": "Read"},
            },
            {
                "timestamp": "2026-05-08T10:01:00Z",
                "violation_type": "secret_detected",
                "severity": "critical",
                "blocked": {},
                "context": {"tool_name": "Write"},
            },
        ]
        mock_vl_cls.return_value = mock_vl

        server = create_server()
        tool = server._tool_manager._tools["get_violations"]
        result = tool.fn()
        assert result["count"] == 1
        assert result["violations"][0]["type"] == "secret_detected"
        assert all(v["type"] != "annotation_suppressed" for v in result["violations"])

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_violations_include_safe_suggestions(self, mock_vl_cls):
        """Each violation entry must include a safe-only fix suggestion."""
        violation_types = [
            "secret_detected",
            "pii_detected",
            "directory_blocking",
            "tool_permission",
            "prompt_injection",
            "ssrf_blocked",
            "config_file_exfil",
            "jailbreak_detected",
        ]
        mock_vl = MagicMock()
        mock_vl.get_recent_violations.return_value = [
            {
                "timestamp": f"2026-05-18T10:0{i}:00Z",
                "violation_type": vtype,
                "severity": "high",
                "blocked": {},
                "context": {"tool_name": "Bash"},
            }
            for i, vtype in enumerate(violation_types)
        ]
        mock_vl_cls.return_value = mock_vl

        server = create_server()
        tool = server._tool_manager._tools["get_violations"]
        result = tool.fn()
        assert result["count"] == len(violation_types)
        for v in result["violations"]:
            assert "suggestion" in v, f"Missing suggestion for {v['type']}"
            assert len(v["suggestion"]) > 10, f"Suggestion too short for {v['type']}"

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_suggestions_contain_no_bypass_hints(self, mock_vl_cls):
        """Suggestions must never include bypass instructions."""
        mock_vl = MagicMock()
        mock_vl.get_recent_violations.return_value = [
            {
                "timestamp": "2026-05-18T10:00:00Z",
                "violation_type": vtype,
                "severity": "high",
                "blocked": {},
                "context": {"tool_name": "Write"},
            }
            for vtype in [
                "secret_detected",
                "pii_detected",
                "directory_blocking",
                "tool_permission",
                "prompt_injection",
                "ssrf_blocked",
                "config_file_exfil",
                "jailbreak_detected",
                "unknown_type",
            ]
        ]
        mock_vl_cls.return_value = mock_vl

        server = create_server()
        tool = server._tool_manager._tools["get_violations"]
        result = tool.fn()
        for v in result["violations"]:
            s = v["suggestion"].lower()
            assert "allowlist" not in s
            assert "annotation" not in s
            assert "disable" not in s
            assert "! " not in v["suggestion"]
            assert ".ai-read-deny" not in s

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_violations_include_tool_from_blocked(self, mock_vl_cls):
        """tool field reads from blocked['tool'] when context lacks tool_name."""
        mock_vl = MagicMock()
        mock_vl.get_recent_violations.return_value = [
            {
                "timestamp": "2026-07-27T10:00:00Z",
                "violation_type": "secret_redaction",
                "severity": "critical",
                "blocked": {
                    "tool": "Read",
                    "file_path": "/tmp/secrets.env",
                    "line_number": 5,
                },
                "context": {"hook_event": "PostToolUse"},
            }
        ]
        mock_vl_cls.return_value = mock_vl

        server = create_server()
        tool = server._tool_manager._tools["get_violations"]
        result = tool.fn()
        v = result["violations"][0]
        assert v["tool"] == "Read"
        assert v["file"] == "/tmp/secrets.env"
        assert v["line"] == 5

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_violations_include_tool_from_context(self, mock_vl_cls):
        """tool field reads from context['tool_name'] with priority."""
        mock_vl = MagicMock()
        mock_vl.get_recent_violations.return_value = [
            {
                "timestamp": "2026-07-27T10:00:00Z",
                "violation_type": "secret_detected",
                "severity": "critical",
                "blocked": {"tool": "Read"},
                "context": {
                    "tool_name": "Bash",
                    "file_path": "/tmp/test.py",
                    "source": "scanner",
                },
            }
        ]
        mock_vl_cls.return_value = mock_vl

        server = create_server()
        tool = server._tool_manager._tools["get_violations"]
        result = tool.fn()
        v = result["violations"][0]
        assert v["tool"] == "Bash"
        assert v["file"] == "/tmp/test.py"
        assert v["source"] == "scanner"

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_violations_source_field_distinguishes_redaction(self, mock_vl_cls):
        """source field distinguishes redaction from scanner violations."""
        mock_vl = MagicMock()
        mock_vl.get_recent_violations.return_value = [
            {
                "timestamp": "2026-07-27T10:00:00Z",
                "violation_type": "secret_redaction",
                "severity": "critical",
                "blocked": {"tool": "Read"},
                "context": {"source": "redaction", "tool_name": "Read"},
            },
            {
                "timestamp": "2026-07-27T10:01:00Z",
                "violation_type": "secret_detected",
                "severity": "critical",
                "blocked": {},
                "context": {"source": "scanner", "tool_name": "Write"},
            },
        ]
        mock_vl_cls.return_value = mock_vl

        server = create_server()
        tool = server._tool_manager._tools["get_violations"]
        result = tool.fn()
        assert result["count"] == 2
        assert result["violations"][0]["source"] == "redaction"
        assert result["violations"][1]["source"] == "scanner"

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_violations_file_fallback_to_context(self, mock_vl_cls):
        """file field falls back to context['file_path'] when blocked lacks it."""
        mock_vl = MagicMock()
        mock_vl.get_recent_violations.return_value = [
            {
                "timestamp": "2026-07-27T10:00:00Z",
                "violation_type": "secret_detected",
                "severity": "critical",
                "blocked": {},
                "context": {"file_path": "/tmp/from_context.py"},
            }
        ]
        mock_vl_cls.return_value = mock_vl

        server = create_server()
        tool = server._tool_manager._tools["get_violations"]
        result = tool.fn()
        assert result["violations"][0]["file"] == "/tmp/from_context.py"


class TestGetConfig:
    """Test get_config tool."""

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_returns_feature_booleans(self, mock_config):
        mock_config.return_value = (
            {
                "secret_scanning": {"enabled": True},
                "prompt_injection": {"enabled": False, "action": "warn"},
                "scan_pii": {"enabled": True},
                "security_instructions": {"inject_on_prompt": True},
                "action": "block",
                "mcp_server": {"proactive_level": "low"},
            },
            None,
        )

        server = create_server()
        tool = server._tool_manager._tools["get_config"]
        result = tool.fn()
        features = result["features"]
        assert features["secret_scanning"] is True
        assert features["prompt_injection"] is False
        assert features["security_instructions"] is True
        assert "action_mode" not in features
        scanner_actions = features["scanner_actions"]
        assert "secret_scanning" not in scanner_actions
        assert scanner_actions["prompt_injection"] == "warn"
        assert scanner_actions["scan_pii"] == "block"  # falls back to global

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_no_rules_or_patterns_exposed(self, mock_config):
        """Config response must not contain regex patterns, allowlists, or deny rules."""
        mock_config.return_value = (
            {
                "secret_scanning": {"enabled": True, "allowlist_patterns": ["test.*"]},
                "permissions": {
                    "enabled": True,
                    "rules": [
                        {"matcher": "Write", "pattern": "*.py", "action": "allow"}
                    ],
                },
                "prompt_injection": {"enabled": True, "sensitivity": "high"},
            },
            None,
        )

        server = create_server()
        tool = server._tool_manager._tools["get_config"]
        result = tool.fn()
        result_str = json.dumps(result)
        assert "allowlist" not in result_str
        assert "rules" not in result_str
        assert "matcher" not in result_str
        assert "regex" not in result_str
        assert "pattern" not in result_str


class TestGetScannerStatus:
    """Test get_scanner_status tool."""

    @patch("ai_guardian.scanners.manager.ScannerManager")
    def test_returns_installed_scanners(self, mock_sm_cls):
        from ai_guardian.scanners.manager import InstalledScanner

        mock_sm = MagicMock()
        mock_sm.list_installed.return_value = [
            InstalledScanner(
                name="gitleaks",
                version="8.30.1",
                path="/usr/bin/gitleaks",
                is_default=True,
            ),
        ]
        mock_sm_cls.return_value = mock_sm

        server = create_server()
        tool = server._tool_manager._tools["get_scanner_status"]
        result = tool.fn()
        assert result["count"] == 1
        assert result["scanners"][0]["name"] == "gitleaks"
        assert "path" not in result["scanners"][0]


class TestGetScannerSupported:
    """Test get_scanner_supported tool."""

    def test_returns_supported_list(self):
        server = create_server()
        tool = server._tool_manager._tools["get_scanner_supported"]
        result = tool.fn()
        assert "gitleaks" in result["scanners"]
        assert len(result["scanners"]) > 0


class TestGetPatternsList:
    """Test get_patterns_list tool."""

    @patch("ai_guardian.patterns.lister.PatternLister")
    def test_returns_counts_only(self, mock_pl_cls):
        mock_cat = MagicMock()
        mock_cat.name = "Prompt Injection"
        mock_group = MagicMock()
        mock_group.count = 15
        mock_cat.built_in_groups = [mock_group]
        mock_pl = MagicMock()
        mock_pl.get_categories.return_value = [mock_cat]
        mock_pl_cls.return_value = mock_pl

        server = create_server()
        tool = server._tool_manager._tools["get_patterns_list"]
        result = tool.fn()
        assert result["categories"]["Prompt Injection"] == 15

    @patch("ai_guardian.patterns.lister.PatternLister")
    def test_no_regex_exposed(self, mock_pl_cls):
        """Pattern counts only, no regex patterns."""
        mock_cat = MagicMock()
        mock_cat.name = "Test"
        mock_group = MagicMock()
        mock_group.count = 5
        mock_cat.built_in_groups = [mock_group]
        mock_pl = MagicMock()
        mock_pl.get_categories.return_value = [mock_cat]
        mock_pl_cls.return_value = mock_pl

        server = create_server()
        tool = server._tool_manager._tools["get_patterns_list"]
        result = tool.fn()
        result_str = json.dumps(result)
        assert "regex" not in result_str.lower()
        assert "\\\\" not in result_str


class TestGetMetrics:
    """Test get_metrics tool."""

    @patch("ai_guardian.reporting.metrics.MetricsComputer")
    def test_returns_metrics(self, mock_mc_cls):
        mock_report = MagicMock()
        mock_report.total_violations = 10
        mock_report.by_type = {"secret_detected": 5, "prompt_injection": 5}
        mock_report.by_severity = {"critical": 3, "high": 7}
        mock_report.resolved_count = 4
        mock_report.unresolved_count = 6
        mock_mc = MagicMock()
        mock_mc.compute.return_value = mock_report
        mock_mc_cls.return_value = mock_mc

        server = create_server()
        tool = server._tool_manager._tools["get_metrics"]
        result = tool.fn()
        assert result["total_violations"] == 10
        assert result["by_type"]["secret_detected"] == 5


class TestDoctor:
    """Test doctor tool."""

    @patch("ai_guardian.doctor.Doctor")
    def test_returns_check_results(self, mock_doc_cls):
        from ai_guardian.doctor import CheckResult, CheckStatus, DoctorReport

        mock_report = DoctorReport(
            checks=[
                CheckResult(
                    name="config", status=CheckStatus.PASS, message="Config OK"
                ),
                CheckResult(
                    name="scanner",
                    status=CheckStatus.WARN,
                    message="No scanner installed",
                ),
            ],
            version="1.7.0-dev",
        )
        mock_doc = MagicMock()
        mock_doc.run_all.return_value = mock_report
        mock_doc_cls.return_value = mock_doc

        server = create_server()
        tool = server._tool_manager._tools["doctor"]
        result = tool.fn()
        assert len(result["checks"]) == 2
        assert result["checks"][0]["status"] == "pass"
        assert result["has_warnings"] is True


# ─── Resource Tests ───────────────────────────────────────────


class TestResources:
    """Test MCP resources."""

    @patch("ai_guardian.config.loaders._load_config_file")
    @patch("ai_guardian.scanners.manager.ScannerManager")
    def test_security_posture_resource(self, mock_sm_cls, mock_config):
        mock_config.return_value = ({"secret_scanning": {"enabled": True}}, None)
        mock_sm = MagicMock()
        mock_sm.list_installed.return_value = []
        mock_sm_cls.return_value = mock_sm

        server = create_server()
        resources = server._resource_manager._resources
        resource = resources.get("ai-guardian://security-posture")
        if resource:
            result = resource.fn()
            data = json.loads(result)
            assert "features" in data

    def test_protected_paths_resource(self, tmp_path):
        deny_dir = tmp_path / "secrets"
        deny_dir.mkdir()
        (deny_dir / ".ai-read-deny").touch()

        with mock.patch("ai_guardian.mcp.server.Path") as mock_path_cls:
            mock_path_cls.cwd.return_value = tmp_path
            server = create_server()

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_recent_violations_resource(self, mock_vl_cls):
        mock_vl = MagicMock()
        mock_vl.get_recent_violations.return_value = []
        mock_vl_cls.return_value = mock_vl

        server = create_server()
        resources = server._resource_manager._resources
        resource = resources.get("ai-guardian://recent-violations")
        if resource:
            result = resource.fn()
            data = json.loads(result)
            assert "violations" in data


# ─── Support Bundle Tests ─────────────────────────────────────


class TestPrepareSupportBundle:
    """Test prepare_support_bundle tool."""

    @patch("ai_guardian.reporting.support_bundle.prepare_bundle")
    def test_returns_bundle_info(self, mock_prepare):
        mock_prepare.return_value = {
            "bundle_id": "support-20260509-abc123",
            "temp_path": "/tmp/ai-guardian-support-abc123",
            "destination": "~/support-bundles",
            "files": [
                {
                    "name": "config.json",
                    "sanitized": True,
                    "redactions": 3,
                    "note": "3 sensitive values redacted",
                },
                {
                    "name": "metrics.json",
                    "sanitized": False,
                    "redactions": 0,
                    "note": "Aggregate stats only",
                },
            ],
        }

        server = create_server()
        tool = server._tool_manager._tools["prepare_support_bundle"]
        result = tool.fn()
        assert result["bundle_id"] == "support-20260509-abc123"
        assert len(result["files"]) == 2
        assert result["files"][0]["sanitized"] is True


class TestSendSupportBundle:
    """Test send_support_bundle tool."""

    @patch("ai_guardian.reporting.support_bundle.send_bundle")
    def test_send_with_valid_id(self, mock_send):
        mock_send.return_value = {
            "status": "sent",
            "destination": "~/support-bundles/support-20260509-abc123",
            "message": "Bundle copied to ~/support-bundles/support-20260509-abc123",
        }

        server = create_server()
        tool = server._tool_manager._tools["send_support_bundle"]
        result = tool.fn(bundle_id="support-20260509-abc123")
        assert result["status"] == "sent"

    @patch("ai_guardian.reporting.support_bundle.send_bundle")
    def test_send_with_invalid_id(self, mock_send):
        mock_send.return_value = {
            "status": "error",
            "message": "Bundle 'invalid' not found or expired.",
        }

        server = create_server()
        tool = server._tool_manager._tools["send_support_bundle"]
        result = tool.fn(bundle_id="invalid")
        assert result["status"] == "error"


# ─── Path Validation Tests ───────────────────────────────────


class TestValidateScanPath:
    """Test _validate_scan_path helper."""

    def test_valid_directory(self, tmp_path):
        valid, err, resolved = _validate_scan_path(str(tmp_path))
        assert valid is True
        assert err == ""
        assert resolved == tmp_path.resolve()

    def test_nonexistent_path(self):
        valid, err, _ = _validate_scan_path("/nonexistent/path/abc123")
        assert valid is False
        assert "does not exist" in err

    def test_file_not_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello")
        valid, err, _ = _validate_scan_path(str(f))
        assert valid is False
        assert "not a directory" in err

    @pytest.mark.skipif(
        sys.platform == "win32", reason="/etc does not exist on Windows"
    )
    def test_blocks_etc(self):
        valid, err, _ = _validate_scan_path("/etc")
        assert valid is False
        assert "not allowed" in err

    @pytest.mark.skipif(
        sys.platform == "win32", reason="/dev does not exist on Windows"
    )
    def test_blocks_sys(self):
        valid, err, _ = _validate_scan_path("/dev")
        assert valid is False
        assert "not allowed" in err


# ─── Scanning Tool Tests ─────────────────────────────────────


class TestScanDirectory:
    """Test scan_directory tool."""

    def test_scan_empty_directory(self, tmp_path):
        server = create_server()
        tool = server._tool_manager._tools["scan_directory"]
        result = tool.fn(path=str(tmp_path))
        assert result["violations"] == 0
        assert result["scanned_files"] >= 0
        assert "scan_time_ms" in result

    @patch("ai_guardian.scanners.file_scanner.FileScanner.scan_directory")
    @patch("ai_guardian.scanners.file_scanner.FileScanner._discover_files")
    @patch("ai_guardian.config.loaders.load_scanner_config")
    def test_scan_with_findings(self, mock_config, mock_discover, mock_scan, tmp_path):
        mock_config.return_value = {}
        mock_discover.return_value = [tmp_path / "a.py", tmp_path / "b.py"]
        mock_scan.return_value = [
            {
                "rule_id": "SECRET-001",
                "message": "Secret detected",
                "file_path": "a.py",
                "line_number": 10,
                "snippet": "password = 'super_secret_value'",
            },
            {
                "rule_id": "SSRF-001",
                "message": "SSRF detected",
                "file_path": "b.py",
                "line_number": 5,
            },
        ]

        server = create_server()
        tool = server._tool_manager._tools["scan_directory"]
        result = tool.fn(path=str(tmp_path))

        assert result["violations"] == 2
        assert result["by_type"]["SECRET-001"] == 1
        assert result["by_type"]["SSRF-001"] == 1
        assert "files_with_violations" not in result

    @patch("ai_guardian.scanners.file_scanner.FileScanner.scan_directory")
    @patch("ai_guardian.scanners.file_scanner.FileScanner._discover_files")
    @patch("ai_guardian.config.loaders.load_scanner_config")
    def test_no_secret_values_exposed(
        self, mock_config, mock_discover, mock_scan, tmp_path
    ):
        """Response must not contain actual secret/snippet values or file paths."""
        mock_config.return_value = {}
        mock_discover.return_value = []
        mock_scan.return_value = [
            {
                "rule_id": "SECRET-001",
                "message": "API key found",
                "file_path": "config.py",
                "line_number": 42,
                "snippet": "api_key = 'AKIAIOSFODNN7EXAMPLE'",
            },
        ]

        server = create_server()
        tool = server._tool_manager._tools["scan_directory"]
        result = tool.fn(path=str(tmp_path))

        result_str = json.dumps(result)
        assert "AKIAIOSFODNN7EXAMPLE" not in result_str
        assert "snippet" not in result_str
        assert "api_key" not in result_str
        assert "config.py" not in result_str
        assert "files_with_violations" not in result_str

    @pytest.mark.skipif(
        sys.platform == "win32", reason="/etc does not exist on Windows"
    )
    def test_system_path_blocked(self):
        server = create_server()
        tool = server._tool_manager._tools["scan_directory"]
        result = tool.fn(path="/etc")
        assert result["status"] == "error"
        assert "not allowed" in result["message"]

    def test_nonexistent_path(self):
        server = create_server()
        tool = server._tool_manager._tools["scan_directory"]
        result = tool.fn(path="/nonexistent/path/xyz")
        assert result["status"] == "error"
        assert "does not exist" in result["message"]


class TestScanDirectoryReport:
    """Test scan_directory_report tool."""

    @patch("ai_guardian.scanners.file_scanner.FileScanner.scan_directory")
    @patch("ai_guardian.config.loaders.load_scanner_config")
    def test_generates_json_report(self, mock_config, mock_scan, tmp_path):
        mock_config.return_value = {}
        mock_scan.return_value = [
            {"rule_id": "SECRET-001", "message": "Secret", "file_path": "a.py"},
        ]

        server = create_server()
        tool = server._tool_manager._tools["scan_directory_report"]
        result = tool.fn(path=str(tmp_path), format="json")

        assert result["violations"] == 1
        assert result["format"] == "json"
        assert result["report_path"].endswith("scan-results.json")
        assert Path(result["report_path"]).exists()

    @patch("ai_guardian.scanners.file_scanner.FileScanner.scan_directory")
    @patch("ai_guardian.config.loaders.load_scanner_config")
    def test_generates_sarif_report(self, mock_config, mock_scan, tmp_path):
        mock_config.return_value = {}
        mock_scan.return_value = []

        server = create_server()
        tool = server._tool_manager._tools["scan_directory_report"]
        result = tool.fn(path=str(tmp_path), format="sarif")

        assert result["format"] == "sarif"
        assert result["report_path"].endswith("scan-results.sarif")
        assert Path(result["report_path"]).exists()

    @patch("ai_guardian.scanners.file_scanner.FileScanner.scan_directory")
    @patch("ai_guardian.config.loaders.load_scanner_config")
    def test_report_path_only_no_content(self, mock_config, mock_scan, tmp_path):
        """Response must contain path but not the report content."""
        mock_config.return_value = {}
        mock_scan.return_value = [
            {
                "rule_id": "SECRET-001",
                "message": "Secret",
                "file_path": "a.py",
                "snippet": "password = 'supersecret123'",
            },
        ]

        server = create_server()
        tool = server._tool_manager._tools["scan_directory_report"]
        result = tool.fn(path=str(tmp_path))

        result_str = json.dumps(result)
        assert "supersecret123" not in result_str
        assert "snippet" not in result_str
        assert "report_path" in result

    @pytest.mark.skipif(
        sys.platform == "win32", reason="/etc does not exist on Windows"
    )
    def test_system_path_blocked(self):
        server = create_server()
        tool = server._tool_manager._tools["scan_directory_report"]
        result = tool.fn(path="/etc")
        assert result["status"] == "error"
        assert "not allowed" in result["message"]

    def test_unsupported_format(self, tmp_path):
        server = create_server()
        tool = server._tool_manager._tools["scan_directory_report"]
        result = tool.fn(path=str(tmp_path), format="xml")
        assert result["status"] == "error"
        assert "Unsupported format" in result["message"]


# ─── Server Creation Tests ────────────────────────────────────


class TestServerCreation:
    """Test server setup."""

    def test_create_server_returns_mcp_server(self):
        server = create_server()
        assert server is not None

    def test_server_has_17_tools(self):
        server = create_server()
        tools = server._tool_manager._tools
        expected = {
            "check_path",
            "check_command",
            "check_mcp_trust",
            "sanitize_text",
            "sanitize_directory",
            "check_annotations",
            "get_violations",
            "get_config",
            "get_scanner_status",
            "get_scanner_supported",
            "get_patterns_list",
            "get_metrics",
            "doctor",
            "prepare_support_bundle",
            "send_support_bundle",
            "scan_directory",
            "scan_directory_report",
        }
        assert expected == set(
            tools.keys()
        ), f"Missing: {expected - set(tools.keys())}, Extra: {set(tools.keys()) - expected}"

    def test_skill_instructions_contain_violation_guidance(self):
        """Skill instructions must tell the AI to call get_violations() for block reasons."""
        from ai_guardian.mcp.server import _load_skill_instructions

        instructions = _load_skill_instructions()
        assert "get_violations" in instructions
        assert "Do NOT" in instructions

    def test_skill_instructions_no_bypass_content(self):
        """Skill instructions must not teach bypass methods."""
        from ai_guardian.mcp.server import _load_skill_instructions

        instructions = _load_skill_instructions()
        assert "! cat" not in instructions
        assert "! curl" not in instructions
        assert "! head" not in instructions

    def test_server_has_3_resources(self):
        server = create_server()
        resources = server._resource_manager._resources
        expected_uris = {
            "ai-guardian://security-posture",
            "ai-guardian://protected-paths",
            "ai-guardian://recent-violations",
        }
        assert expected_uris == set(
            resources.keys()
        ), f"Missing: {expected_uris - set(resources.keys())}"

    def test_server_has_hook_check_middleware(self):
        server = create_server()
        has_hook_mw = any(isinstance(m, HookCheckMiddleware) for m in server.middleware)
        assert has_hook_mw, "HookCheckMiddleware not found in server middleware"


# ─── Hook Check Tests ────────────────────────────────────────


class TestCheckClientHooks:
    """Test _check_client_hooks function."""

    def test_unknown_client_returns_none(self):
        assert _check_client_hooks("unknown-agent") is None

    def test_empty_client_returns_none(self):
        assert _check_client_hooks("") is None

    def test_hooks_present_returns_none(self):
        mock_setup = MagicMock()
        mock_setup.IDE_CONFIGS = {
            "claude": {"name": "Claude Code", "mcp_client_name": "claude-code"}
        }
        mock_setup.supports_hooks.return_value = True
        mock_setup.check_hooks_for_ide.return_value = (True, "Claude Code: configured")

        MockIDESetup = MagicMock(return_value=mock_setup)
        MockIDESetup.get_ide_for_mcp_client.return_value = "claude"
        with patch("ai_guardian.setup.IDESetup", MockIDESetup):
            result = _check_client_hooks("claude-code")

        assert result is None

    def test_hooks_missing_returns_warning(self):
        mock_setup = MagicMock()
        mock_setup.IDE_CONFIGS = {
            "claude": {"name": "Claude Code", "mcp_client_name": "claude-code"}
        }
        mock_setup.supports_hooks.return_value = True
        mock_setup.check_hooks_for_ide.return_value = (
            False,
            "Claude Code: not configured",
        )

        MockIDESetup = MagicMock(return_value=mock_setup)
        MockIDESetup.get_ide_for_mcp_client.return_value = "claude"
        with patch("ai_guardian.setup.IDESetup", MockIDESetup):
            result = _check_client_hooks("claude-code")

        assert result is not None
        assert "Claude Code" in result
        assert "ai-guardian setup" in result
        assert "WARNING" in result

    def test_hooks_missing_sends_notification(self):
        mock_setup = MagicMock()
        mock_setup.IDE_CONFIGS = {
            "claude": {"name": "Claude Code", "mcp_client_name": "claude-code"}
        }
        mock_setup.supports_hooks.return_value = True
        mock_setup.check_hooks_for_ide.return_value = (
            False,
            "Claude Code: not configured",
        )

        MockIDESetup = MagicMock(return_value=mock_setup)
        MockIDESetup.get_ide_for_mcp_client.return_value = "claude"
        with (
            patch("ai_guardian.setup.IDESetup", MockIDESetup),
            patch("ai_guardian.tray.notifications.show_notification") as mock_notify,
        ):
            _check_client_hooks("claude-code")

        mock_notify.assert_called_once()
        args = mock_notify.call_args
        assert (
            "hooks not installed" in args[0][0].lower() or "hooks" in args[0][0].lower()
        )
        assert "Claude Code" in args[0][1]

    def test_hooks_missing_notification_failure_silent(self):
        mock_setup = MagicMock()
        mock_setup.IDE_CONFIGS = {
            "claude": {"name": "Claude Code", "mcp_client_name": "claude-code"}
        }
        mock_setup.supports_hooks.return_value = True
        mock_setup.check_hooks_for_ide.return_value = (
            False,
            "Claude Code: not configured",
        )

        MockIDESetup = MagicMock(return_value=mock_setup)
        MockIDESetup.get_ide_for_mcp_client.return_value = "claude"
        with (
            patch("ai_guardian.setup.IDESetup", MockIDESetup),
            patch(
                "ai_guardian.tray.notifications.show_notification",
                side_effect=RuntimeError("notification failed"),
            ),
        ):
            result = _check_client_hooks("claude-code")

        assert result is not None
        assert "WARNING" in result

    def test_hooks_present_no_notification(self):
        mock_setup = MagicMock()
        mock_setup.IDE_CONFIGS = {
            "claude": {"name": "Claude Code", "mcp_client_name": "claude-code"}
        }
        mock_setup.supports_hooks.return_value = True
        mock_setup.check_hooks_for_ide.return_value = (True, "Claude Code: configured")

        MockIDESetup = MagicMock(return_value=mock_setup)
        MockIDESetup.get_ide_for_mcp_client.return_value = "claude"
        with (
            patch("ai_guardian.setup.IDESetup", MockIDESetup),
            patch("ai_guardian.tray.notifications.show_notification") as mock_notify,
        ):
            result = _check_client_hooks("claude-code")

        assert result is None
        mock_notify.assert_not_called()

    def test_mcp_only_ide_returns_none(self):
        mock_setup = MagicMock()
        mock_setup.IDE_CONFIGS = {
            "junie": {"name": "Junie", "mcp_only": True, "mcp_client_name": "junie-cli"}
        }
        mock_setup.supports_hooks.return_value = False

        MockIDESetup = MagicMock(return_value=mock_setup)
        MockIDESetup.get_ide_for_mcp_client.return_value = "junie"
        with patch("ai_guardian.setup.IDESetup", MockIDESetup):
            result = _check_client_hooks("junie-cli")

        assert result is None

    def test_setup_exception_returns_none(self):
        with patch(
            "ai_guardian.setup.IDESetup",
            side_effect=ImportError("no setup"),
        ):
            result = _check_client_hooks("claude-code")

        assert result is None


class TestHookCheckMiddleware:
    """Test HookCheckMiddleware."""

    def test_appends_warning_on_initialize(self):
        middleware = HookCheckMiddleware()
        ctx = MagicMock()
        ctx.method = "initialize"
        ctx.params = {"clientInfo": {"name": "claude-code"}}

        async def call_next(c):
            return {
                "instructions": "base instructions",
                "protocolVersion": "2025-11-05",
            }

        warning = "\n\n⚠️ WARNING: hooks missing"
        with patch("ai_guardian.mcp.server._check_client_hooks", return_value=warning):
            result = asyncio.run(middleware(ctx, call_next))

        assert result["instructions"] == "base instructions" + warning

    def test_no_warning_when_hooks_present(self):
        middleware = HookCheckMiddleware()
        ctx = MagicMock()
        ctx.method = "initialize"
        ctx.params = {"clientInfo": {"name": "claude-code"}}

        async def call_next(c):
            return {"instructions": "base", "protocolVersion": "2025-11-05"}

        with patch("ai_guardian.mcp.server._check_client_hooks", return_value=None):
            result = asyncio.run(middleware(ctx, call_next))

        assert result["instructions"] == "base"

    def test_non_initialize_passthrough(self):
        middleware = HookCheckMiddleware()
        ctx = MagicMock()
        ctx.method = "tools/list"
        ctx.params = {}

        expected = {"tools": []}

        async def call_next(c):
            return expected

        result = asyncio.run(middleware(ctx, call_next))

        assert result == expected

    def test_no_client_info_no_warning(self):
        middleware = HookCheckMiddleware()
        ctx = MagicMock()
        ctx.method = "initialize"
        ctx.params = {}

        async def call_next(c):
            return {"instructions": "base", "protocolVersion": "2025-11-05"}

        result = asyncio.run(middleware(ctx, call_next))

        assert result["instructions"] == "base"

    def test_none_params_no_warning(self):
        middleware = HookCheckMiddleware()
        ctx = MagicMock()
        ctx.method = "initialize"
        ctx.params = None

        async def call_next(c):
            return {"instructions": "base", "protocolVersion": "2025-11-05"}

        result = asyncio.run(middleware(ctx, call_next))

        assert result["instructions"] == "base"

    def test_adds_instructions_when_none(self):
        middleware = HookCheckMiddleware()
        ctx = MagicMock()
        ctx.method = "initialize"
        ctx.params = {"clientInfo": {"name": "cursor"}}

        async def call_next(c):
            return {"protocolVersion": "2025-11-05"}

        warning = "\n\n⚠️ WARNING: hooks missing"
        with patch("ai_guardian.mcp.server._check_client_hooks", return_value=warning):
            result = asyncio.run(middleware(ctx, call_next))

        assert result["instructions"] == warning
