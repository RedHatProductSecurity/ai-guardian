"""Tests for violation copy buttons and markdown formatter."""

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.pages.violations import _format_violation_markdown


class TestFormatViolationMarkdown:
    """Verify _format_violation_markdown produces correct output."""

    def test_secret_detected(self):
        v = {
            "violation_type": "secret_detected",
            "severity": "critical",
            "timestamp": "2026-06-06T10:45:15",
            "blocked": {
                "file_path": "src/app.py",
                "line_number": 42,
                "secret_type": "github-pat-fine-grained",
                "source": "gitleaks",
                "total_findings": 1,
            },
        }
        md = _format_violation_markdown(v)
        assert "**Type:** secret_detected" in md
        assert "**Severity:** critical" in md
        assert "**File:** src/app.py" in md
        assert "**Line:** 42" in md
        assert "**Time:** 2026-06-06T10:45:15" in md
        assert "**Source:** gitleaks" in md

    def test_tool_permission_with_suggestion(self):
        v = {
            "violation_type": "tool_permission",
            "severity": "warning",
            "timestamp": "2026-06-06T11:00:00",
            "blocked": {
                "tool_name": "Bash",
                "tool_value": "rm -rf /",
                "reason": "not allowed",
            },
            "suggestion": {
                "rule": {"tool": "Bash", "command": "rm"},
            },
        }
        md = _format_violation_markdown(v)
        assert "**Type:** tool_permission" in md
        assert "**Tool:** Bash" in md
        assert "**Reason:** not allowed" in md
        assert "**Suggested Rule:**" in md
        assert '"tool": "Bash"' in md

    def test_directory_blocking(self):
        v = {
            "violation_type": "directory_blocking",
            "severity": "high",
            "timestamp": "2026-06-06T12:00:00",
            "blocked": {
                "file_path": "/etc/passwd",
                "denied_directory": "/etc",
            },
        }
        md = _format_violation_markdown(v)
        assert "**File:** /etc/passwd" in md
        assert "**Directory:** /etc" in md

    def test_missing_blocked_fields_skipped(self):
        v = {
            "violation_type": "secret_detected",
            "severity": "warning",
            "timestamp": "2026-06-06T12:00:00",
            "blocked": {"file_path": "test.py"},
        }
        md = _format_violation_markdown(v)
        assert "**File:** test.py" in md
        assert "**Line:**" not in md
        assert "**Source:**" not in md

    def test_list_values_joined(self):
        v = {
            "violation_type": "pii_detected",
            "severity": "warning",
            "timestamp": "2026-06-06T12:00:00",
            "blocked": {
                "pii_types": ["ssn", "credit_card", "phone"],
                "pii_count": 3,
            },
        }
        md = _format_violation_markdown(v)
        assert "**Types:** ssn, credit_card, phone" in md

    def test_no_timestamp(self):
        v = {
            "violation_type": "directory_blocking",
            "severity": "warning",
            "blocked": {"file_path": "/tmp/x"},
        }
        md = _format_violation_markdown(v)
        assert "**Time:**" not in md

    def test_non_dict_blocked_handled(self):
        v = {
            "violation_type": "unknown_type",
            "severity": "warning",
            "blocked": "not a dict",
        }
        md = _format_violation_markdown(v)
        assert "**Type:** unknown_type" in md
        assert "**Severity:** warning" in md

    def test_no_suggestion_rule(self):
        v = {
            "violation_type": "tool_permission",
            "severity": "warning",
            "blocked": {},
            "suggestion": {},
        }
        md = _format_violation_markdown(v)
        assert "Suggested Rule" not in md

    def test_prompt_injection(self):
        v = {
            "violation_type": "prompt_injection",
            "severity": "critical",
            "timestamp": "2026-06-06T13:00:00",
            "blocked": {
                "source": "file",
                "file_path": "evil.md",
                "pattern": "ignore previous",
                "matched_text": "ignore previous instructions",
                "method": "regex",
                "confidence": 0.95,
            },
        }
        md = _format_violation_markdown(v)
        assert "**Pattern:** ignore previous" in md
        assert "**Matched:** ignore previous instructions" in md
        assert "**Method:** regex" in md
        assert "**Confidence:** 0.95" in md

    def test_type_fallback_to_type_key(self):
        v = {"type": "ssrf_blocked", "severity": "high", "blocked": {}}
        md = _format_violation_markdown(v)
        assert "**Type:** ssrf_blocked" in md

    def test_tool_input_diagnostics_and_correlation_are_copyable_without_values(self):
        markdown = _format_violation_markdown(
            {
                "id": "viol_2627abcd",
                "violation_type": "tool_permission",
                "blocked": {
                    "tool_name": "Read",
                    "is_immutable": True,
                    "input_diagnostics": {
                        "schema_version": 1,
                        "subreason": "missing_argument",
                        "native_tool_name": "read",
                        "canonical_tool_name": "Read",
                        "expected_field": "path",
                        "input_type": "object",
                        "argument_shape": {
                            "limit": "integer",
                            "PRIVATE_KEY": "PRIVATE_VALUE",
                        },
                        "raw_payload": "PRIVATE_PAYLOAD",
                    },
                },
                "context": {
                    "session_id": "ses_2627test",
                    "tool_use_id": "call_2627test",
                    "message_id": "msg_2627test",
                    "host_version": "2.0.24",
                    "integration_version": "1.21.0-dev",
                    "workspace_source": "session",
                    "project_path": "/workspaces/session",
                    "policy_project_path": "/workspaces/session",
                    "plugin_cwd": "/workspaces/plugin",
                },
            }
        )
        assert "**Input Subreason:** missing_argument" in markdown
        assert "**Native Tool:** read" in markdown
        assert "**Expected Field:** path" in markdown
        assert "**Argument Shape:** limit: integer" in markdown
        for value in (
            "viol_2627abcd",
            "ses_2627test",
            "call_2627test",
            "msg_2627test",
            "2.0.24",
            "/workspaces/session",
            "/workspaces/plugin",
        ):
            assert value in markdown
        assert "PRIVATE_" not in markdown
        assert "Suggested Rule" not in markdown
