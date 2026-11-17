"""Tests for violation copy buttons and markdown formatter."""

import pytest
from unittest.mock import patch

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
        with patch(
            "ai_guardian.violations.command_context._source_text_is_verified_safe",
            return_value=True,
        ):
            md = _format_violation_markdown(v)
        assert "**Type:** sensitive_finding" in md
        assert "**Severity:** critical" in md
        assert "**File:** src/app.py" in md
        assert "**Line:** 42" in md
        assert "**Time:** 2026-06-06T10:45:15" in md
        assert "**Source:**" not in md
        assert "github-pat-fine-grained" not in md

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
        with patch(
            "ai_guardian.violations.command_context._source_text_is_verified_safe",
            return_value=True,
        ):
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
        with patch(
            "ai_guardian.violations.command_context._source_text_is_verified_safe",
            return_value=True,
        ):
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
        assert "**Types:**" not in md

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

    def test_locationless_violation_includes_optional_source_command(self):
        markdown = _format_violation_markdown(
            {
                "violation_type": "exfil_detection",
                "blocked": {
                    "source_command": "printf safe-command",
                    "line_number": 7,
                    "start_column": 2,
                },
            }
        )

        assert "**Source Command:** printf safe-command" in markdown
        assert "**Line:** 7" in markdown

    def test_legacy_violation_without_source_command_stays_readable(self):
        markdown = _format_violation_markdown(
            {
                "violation_type": "exfil_detection",
                "blocked": {"line_number": 7},
            }
        )

        assert "**Line:** 7" in markdown
        assert "Source Command" not in markdown

    def test_sensitive_finding_copy_includes_safe_locator_not_private_values(self):
        private_marker = "synthetic-private-match-marker"
        markdown = _format_violation_markdown(
            {
                "violation_type": "sensitive_finding",
                "severity": "high",
                "blocked": {
                    "file_path": "/repo/data.csv",
                    "line_number": 12,
                    "start_column": 0,
                    "end_column": 8,
                    "matched_text": private_marker,
                    "secret_type": "private-subtype",
                },
            }
        )

        assert "**File:** /repo/data.csv" in markdown
        assert "**Line:** 12" in markdown
        assert "**Column:** 1" in markdown
        assert "**End Column:** 9" in markdown
        assert "**Privacy Note:**" in markdown
        assert private_marker not in markdown
        assert "private-subtype" not in markdown

    def test_flat_daemon_sensitive_locator_is_displayed(self):
        markdown = _format_violation_markdown(
            {
                "type": "sensitive_finding",
                "file": "/repo/remote.csv",
                "line": 6,
                "start_column": 3,
                "end_column": 7,
                "source_context": "Tool input",
            }
        )

        assert "**File:** /repo/remote.csv" in markdown
        assert "**Line:** 6" in markdown
        assert "**Column:** 3" in markdown
        assert "**End Column:** 7" in markdown
        assert "**Source:** Tool input" in markdown

    def test_legacy_sensitive_copy_omits_unverified_path(self):
        with patch(
            "ai_guardian.violations.command_context._source_text_is_verified_safe",
            return_value=False,
        ):
            markdown = _format_violation_markdown(
                {
                    "violation_type": "secret_detected",
                    "blocked": {
                        "file_path": "/private/path/with-unverified-value",
                        "line_number": 4,
                    },
                }
            )

        assert "with-unverified-value" not in markdown
        assert "**File:**" not in markdown
