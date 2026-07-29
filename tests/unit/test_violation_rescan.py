"""Tests for violation_rescan module (Issue #1146)."""

from unittest.mock import patch, MagicMock


from ai_guardian.daemon.violation_rescan import (
    rescan_violation,
    _extract_line_near,
    _find_nearest_redaction,
)
from ai_guardian.tui.pattern_editor import (
    config_section_for_violation,
)


class TestConfigSectionForViolation:
    """Test the violation type to config section mapping."""

    def test_secret_detected(self):
        assert config_section_for_violation("secret_detected") == "secret_scanning"

    def test_pii_detected(self):
        assert config_section_for_violation("pii_detected") == "scan_pii"

    def test_prompt_injection(self):
        assert config_section_for_violation("prompt_injection") == "prompt_injection"

    def test_jailbreak_detected(self):
        assert config_section_for_violation("jailbreak_detected") == "prompt_injection"

    def test_directory_blocking(self):
        assert config_section_for_violation("directory_blocking") == "directory_rules"

    def test_ssrf_blocked(self):
        assert config_section_for_violation("ssrf_blocked") == "ssrf_protection"

    def test_config_file_exfil(self):
        assert (
            config_section_for_violation("config_file_exfil") == "config_file_scanning"
        )

    def test_context_poisoning(self):
        assert config_section_for_violation("context_poisoning") == "context_poisoning"

    def test_supply_chain(self):
        assert config_section_for_violation("supply_chain") == "supply_chain"

    def test_tool_permission(self):
        assert config_section_for_violation("tool_permission") == "permissions"

    def test_image_secret_detected(self):
        assert config_section_for_violation("image_secret_detected") == "image_scanning"

    def test_image_pii_detected(self):
        assert config_section_for_violation("image_pii_detected") == "image_scanning"

    def test_unknown_type_returns_empty(self):
        assert config_section_for_violation("unknown_type") == ""


class TestExtractLineNear:
    """Test the _extract_line_near helper."""

    def test_extracts_correct_line(self):
        content = "line1\nline2\nline3\n"
        assert _extract_line_near(content, 2) == "line2"

    def test_first_line(self):
        content = "first\nsecond"
        assert _extract_line_near(content, 1) == "first"

    def test_last_line(self):
        content = "first\nlast"
        assert _extract_line_near(content, 2) == "last"

    def test_out_of_range_clamps(self):
        content = "only_line"
        assert _extract_line_near(content, 5) == "only_line"

    def test_empty_content(self):
        assert _extract_line_near("", 1) == ""

    def test_zero_line(self):
        assert _extract_line_near("content", 0) == ""

    def test_strips_whitespace(self):
        content = "  spaced  \n"
        assert _extract_line_near(content, 1) == "spaced"


class TestFindNearestRedaction:
    """Test the _find_nearest_redaction helper."""

    def test_finds_nearest_by_line(self):
        content = "0123456789" * 10
        redactions = [
            {"type": "pii-ssn", "line_number": 5, "position": 0, "original_length": 3},
            {"type": "pii-ssn", "line_number": 10, "position": 5, "original_length": 3},
        ]
        result = _find_nearest_redaction(redactions, 6, "pii-ssn", content)
        assert result is not None
        assert result["line_number"] == 5

    def test_filters_by_sub_type(self):
        content = "abcdef"
        redactions = [
            {
                "type": "pii-phone",
                "line_number": 1,
                "position": 0,
                "original_length": 3,
            },
            {"type": "pii-ssn", "line_number": 2, "position": 3, "original_length": 3},
        ]
        result = _find_nearest_redaction(redactions, 1, "pii-ssn", content)
        assert result is not None
        assert result["line_number"] == 2

    def test_empty_redactions(self):
        result = _find_nearest_redaction([], 1, "", "content")
        assert result is None


class TestRescanViolation:
    """Test the rescan_violation function."""

    def test_file_not_found(self):
        result = rescan_violation(
            file_path="/nonexistent/path/file.py",
            line_number=1,
            violation_type="secret_detected",
        )
        assert result["status"] == "file_not_found"

    def test_empty_file_path(self):
        result = rescan_violation(
            file_path="",
            line_number=1,
            violation_type="secret_detected",
        )
        assert result["status"] == "not_found"

    def test_unsupported_violation_type(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("content")
        result = rescan_violation(
            file_path=str(f),
            line_number=1,
            violation_type="unknown_type_xyz",
        )
        assert result["status"] == "not_found"
        assert "Unsupported" in result.get("message", "")

    def test_passthrough_types_return_line_content(self, tmp_path):
        """directory_blocking, ssrf_blocked etc. return line content directly."""
        f = tmp_path / "test.py"
        f.write_text("line1\nblocked_path\nline3\n")
        result = rescan_violation(
            file_path=str(f),
            line_number=2,
            violation_type="directory_blocking",
        )
        assert result["status"] == "found"
        assert result["matched_text"] == "blocked_path"

    @patch("ai_guardian.scanners.secret_scanning.check_secrets_with_gitleaks")
    def test_secret_scan_found(self, mock_scan, tmp_path):
        """Secret rescan returns matched text when scanner finds secrets."""
        mock_scan.return_value = (True, "Secret detected")

        f = tmp_path / "test.py"
        f.write_text("normal\nAPI_KEY=secret123\nnormal\n")

        import ai_guardian.scanners.secret_scanning as ss

        ss._last_secret_matched_text = "API_KEY=secret123"

        result = rescan_violation(
            file_path=str(f),
            line_number=2,
            violation_type="secret_detected",
            sub_type="env-variable",
            config={"secret_scanning": {"enabled": True}},
        )
        assert result["status"] == "found"
        assert "API_KEY" in result["matched_text"]

    @patch("ai_guardian.scanners.secret_scanning.check_secrets_with_gitleaks")
    def test_secret_scan_not_found(self, mock_scan, tmp_path):
        """Secret rescan returns not_found when scanner finds nothing."""
        mock_scan.return_value = (False, None)

        f = tmp_path / "test.py"
        f.write_text("clean content\n")

        result = rescan_violation(
            file_path=str(f),
            line_number=1,
            violation_type="secret_detected",
            config={"secret_scanning": {"enabled": True}},
        )
        assert result["status"] == "not_found"

    @patch("ai_guardian.hook_processing._scan_for_pii")
    def test_pii_scan_found(self, mock_pii, tmp_path):
        """PII rescan returns matched text."""
        mock_pii.return_value = (
            True,
            "***REDACTED***",
            [
                {
                    "type": "pii-ssn",
                    "line_number": 2,
                    "position": 4,
                    "original_length": 11,
                }
            ],
            "PII found",
        )

        f = tmp_path / "test.py"
        f.write_text("name\nssn=078-05-1120\naddr\n")

        result = rescan_violation(
            file_path=str(f),
            line_number=2,
            violation_type="pii_detected",
            sub_type="pii-ssn",
            config={"scan_pii": {"enabled": True}},
        )
        assert result["status"] == "found"
        assert result["violation_type"] == "pii_detected"


class TestExtractMatchedFromViolation:
    """Test matched text extraction from violation data."""

    def _extract(self, violation):
        from ai_guardian.tui.violations import _extract_matched_from_violation

        return _extract_matched_from_violation(violation)

    def test_matched_text_field(self):
        v = {
            "blocked": {"matched_text": "injected payload"},
            "violation_type": "prompt_injection",
        }
        assert self._extract(v) == "injected payload"

    def test_context_snippet(self):
        v = {
            "blocked": {"context_snippet": "+32 56 37 04 17"},
            "violation_type": "pii_detected",
        }
        assert self._extract(v) == "+32 56 37 04 17"

    def test_tool_permission_both_fields(self):
        v = {
            "blocked": {"tool_name": "Bash", "tool_value": "rm -rf"},
            "violation_type": "tool_permission",
        }
        assert self._extract(v) == "Bash:rm -rf"

    def test_tool_permission_only_tool(self):
        v = {
            "blocked": {"tool_name": "mcp__server__tool"},
            "violation_type": "tool_permission",
        }
        assert self._extract(v) == "mcp__server__tool"

    def test_ssrf_tool_value(self):
        v = {
            "blocked": {"tool_value": "http://169.254.169.254"},
            "violation_type": "ssrf_blocked",
        }
        assert self._extract(v) == "http://169.254.169.254"

    def test_ssrf_from_reason(self):
        v = {
            "blocked": {"reason": "SSRF blocked: http://internal.corp/admin"},
            "violation_type": "ssrf_blocked",
        }
        assert "http://internal.corp/admin" in self._extract(v)

    def test_directory_blocking(self):
        v = {
            "blocked": {
                "denied_directory": "/etc/secrets",
                "file_path": "/etc/secrets/key.pem",
            },
            "violation_type": "directory_blocking",
        }
        assert self._extract(v) == "/etc/secrets"

    def test_prompt_injection_pattern(self):
        v = {
            "blocked": {"pattern": r"ignore.*instructions"},
            "violation_type": "prompt_injection",
        }
        assert self._extract(v) == r"ignore.*instructions"

    def test_context_poisoning_pattern(self):
        v = {
            "blocked": {"pattern": r"system_prompt"},
            "violation_type": "context_poisoning",
        }
        assert self._extract(v) == "system_prompt"

    def test_supply_chain_pattern(self):
        v = {
            "blocked": {"pattern": "malicious-package"},
            "violation_type": "supply_chain",
        }
        assert self._extract(v) == "malicious-package"

    def test_pii_types_fallback(self):
        v = {
            "blocked": {"pii_types": ["SSN", "Phone Number"]},
            "violation_type": "pii_detected",
        }
        assert self._extract(v) == "SSN, Phone Number"

    def test_pattern_hint_fallback(self):
        """pattern_hint used when matched_text absent (redacted secrets/PII)."""
        v = {
            "blocked": {"pattern_hint": "AKIA.*MPLE"},
            "violation_type": "secret_detected",
        }
        assert self._extract(v) == "AKIA.*MPLE"

    def test_secret_detected_returns_empty(self):
        """Secrets not stored in violation data — requires file rescan."""
        v = {
            "blocked": {
                "secret_type": "aws-access-token",
                "file_path": "/app/config.py",
            },
            "violation_type": "secret_detected",
        }
        assert self._extract(v) == ""

    def test_empty_blocked(self):
        v = {"blocked": {}, "violation_type": "unknown"}
        assert self._extract(v) == ""

    def test_non_dict_blocked(self):
        v = {"blocked": "not a dict", "violation_type": "secret_detected"}
        assert self._extract(v) == ""


class TestRestEndpoint:
    """Test the REST API endpoint for violation-context."""

    def test_handler_requires_violation_type(self):
        """Handler returns 400 if violation_type missing."""
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = MagicMock(spec=_RestHandler)
        handler.headers = {"Authorization": "Bearer test"}
        handler._read_body = MagicMock(return_value={"file_path": "/tmp/x"})
        handler._send_error = MagicMock()
        handler._send_json = MagicMock()

        _RestHandler._handle_violation_context(handler, {"file_path": "/tmp/x"})
        handler._send_error.assert_called_once_with(400, "violation_type is required")

    def test_handler_calls_rescan(self):
        """Handler calls rescan_violation and returns result."""
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = MagicMock(spec=_RestHandler)
        handler.server = MagicMock()
        handler.server.daemon_state.get_config.return_value = {}
        handler._send_json = MagicMock()

        body = {
            "file_path": "/nonexistent",
            "violation_type": "secret_detected",
            "line_number": 1,
            "secret_type": "env-variable",
        }

        _RestHandler._handle_violation_context(handler, body)
        handler._send_json.assert_called_once()
        result = handler._send_json.call_args[0][0]
        assert result["status"] == "file_not_found"
