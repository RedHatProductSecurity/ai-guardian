"""Tests for extracted hook_processing helper functions."""

from unittest.mock import MagicMock


from ai_guardian.hook_events.utils import strip_system_tags
from ai_guardian.hook_processing import HookEvent
from ai_guardian.scanners.scan_result import ScanResult, generate_violation_id
from ai_guardian.scanners.secret_scanning import _build_secret_detected_message
from ai_guardian.constants import ViolationType
from ai_guardian.violations.log_violation import ScanContext, log_violation

# ---------------------------------------------------------------------------
# strip_system_tags
# ---------------------------------------------------------------------------


class TestStripSystemTags:

    def test_strips_single_task_notification(self):
        content = "hello <task-notification>secret stuff</task-notification> world"
        assert strip_system_tags(content) == "hello  world"

    def test_strips_multiline_task_notification(self):
        content = (
            "before\n"
            "<task-notification>\n"
            "ALL_DETECTION_CASES = NEW_SECRET_DETECTION_CASES\n"
            "line2\n"
            "</task-notification>\n"
            "after"
        )
        result = strip_system_tags(content)
        assert "ALL_DETECTION_CASES" not in result
        assert "before" in result
        assert "after" in result

    def test_strips_multiple_task_notifications(self):
        content = (
            "a <task-notification>x</task-notification>"
            " b <task-notification>y</task-notification> c"
        )
        assert strip_system_tags(content) == "a  b  c"

    def test_strips_task_notification_with_attributes(self):
        content = 'before <task-notification id="abc">data</task-notification> after'
        assert strip_system_tags(content) == "before  after"

    def test_no_tags_passthrough(self):
        content = "normal prompt text with no tags"
        assert strip_system_tags(content) == content

    def test_empty_string(self):
        assert strip_system_tags("") == ""

    def test_none_returns_none(self):
        assert strip_system_tags(None) is None

    def test_preserves_other_xml_tags(self):
        content = "text <other-tag>keep</other-tag> end"
        assert strip_system_tags(content) == content

    def test_strips_system_reminder(self):
        content = "prompt <system-reminder>injected rules</system-reminder> text"
        assert strip_system_tags(content) == "prompt  text"

    def test_strips_mixed_system_tags(self):
        content = (
            "a <task-notification>n1</task-notification>"
            " b <system-reminder>r1</system-reminder> c"
        )
        assert strip_system_tags(content) == "a  b  c"

    def test_fast_path_no_tags(self):
        content = "plain text without any angle brackets"
        assert strip_system_tags(content) is content


# ---------------------------------------------------------------------------
# _build_secret_detected_message
# ---------------------------------------------------------------------------


class TestBuildSecretDetectedMessage:

    SAMPLE_DETAILS = {
        "rule_id": "generic-api-key",
        "file": "config.py",
        "line_number": 42,
        "end_line": 42,
        "commit": "abc1234",
        "total_findings": 1,
    }

    def test_basic_message_structure(self):
        msg = _build_secret_detected_message(
            "gitleaks", self.SAMPLE_DETAILS, "Built-in gitleaks rules"
        )
        assert "Secret Detected" in msg
        assert "Protection: Secret Scanning" in msg
        assert "Secret Type: Generic API Key" in msg
        assert "Location: config.py:42" in msg
        assert "Scanner: gitleaks" in msg
        assert "Patterns: Built-in gitleaks rules" in msg
        assert "Move secrets to environment variables" in msg

    def test_custom_protection_label(self):
        msg = _build_secret_detected_message(
            "gitleaks",
            self.SAMPLE_DETAILS,
            "Built-in gitleaks rules",
            protection_label="Secret Scanning (any-match strategy)",
        )
        assert "Protection: Secret Scanning (any-match strategy)" in msg

    def test_no_line_number(self):
        details = {**self.SAMPLE_DETAILS, "line_number": None}
        msg = _build_secret_detected_message("gitleaks", details, "Built-in rules")
        assert "Location: config.py\n" in msg
        assert ":None" not in msg

    def test_no_secret_details(self):
        msg = _build_secret_detected_message("gitleaks", None, "Built-in rules")
        assert "Secret Type: (multiple or unknown)" in msg
        assert "Common secret types:" in msg
        assert "API keys and tokens" in msg

    def test_with_details_no_common_types_section(self):
        msg = _build_secret_detected_message(
            "gitleaks", self.SAMPLE_DETAILS, "Built-in rules"
        )
        assert "Common secret types:" not in msg

    def test_pattern_description_passthrough(self):
        msg = _build_secret_detected_message(
            "betterleaks",
            self.SAMPLE_DETAILS,
            "LeakTK Pattern Server (https://patterns.example.com)",
        )
        assert "Patterns: LeakTK Pattern Server (https://patterns.example.com)" in msg

    def test_separator_lines(self):
        msg = _build_secret_detected_message("gitleaks", self.SAMPLE_DETAILS, "rules")
        assert msg.startswith(f"\n{'='*70}\n")
        assert msg.endswith(f"{'='*70}\n")


# ---------------------------------------------------------------------------
# log_violation (unified — replaces _log_pii_violation et al.)
# ---------------------------------------------------------------------------


class TestLogViolationPii:
    """Tests for unified log_violation() with PII-type inputs."""

    def test_calls_violation_logger(self):
        mock_logger = MagicMock()
        result = ScanResult(
            detected=True,
            violation_type=ViolationType.PII_DETECTED,
            id=generate_violation_id(),
            file_path="/tmp/test.py",
            line_number=5,
            error_message="PII detected",
        )
        ctx = ScanContext(
            hook_event=HookEvent.POST_TOOL_USE,
            session_id="sess-456",
            tool_use_id="tu-123",
        )
        log_violation(
            result,
            ctx,
            violation_logger=mock_logger,
            blocked_overrides={"pii_count": 3, "pii_types": ["EMAIL", "PHONE"]},
            context_overrides={"action": "block"},
        )
        mock_logger.log_violation.assert_called_once()
        call_kwargs = mock_logger.log_violation.call_args[1]
        assert call_kwargs["violation_type"] == ViolationType.PII_DETECTED
        blocked = call_kwargs["blocked"]
        assert blocked["file_path"] == "/tmp/test.py"
        assert blocked["pii_count"] == 3
        assert set(blocked["pii_types"]) == {"EMAIL", "PHONE"}
        ctx_dict = call_kwargs["context"]
        assert ctx_dict["tool_use_id"] == "tu-123"
        assert ctx_dict["session_id"] == "sess-456"

    def test_no_logger_creates_default(self, monkeypatch):
        mock_vl_cls = MagicMock()
        monkeypatch.setattr(
            "ai_guardian.violations.logger.ViolationLogger", mock_vl_cls
        )
        result = ScanResult(
            detected=True,
            violation_type=ViolationType.PII_DETECTED,
            id=generate_violation_id(),
        )
        log_violation(result, ScanContext())
        mock_vl_cls.return_value.log_violation.assert_called_once()

    def test_blocked_overrides_merged(self):
        mock_logger = MagicMock()
        result = ScanResult(
            detected=True,
            violation_type=ViolationType.PII_DETECTED,
            id=generate_violation_id(),
        )
        log_violation(
            result,
            ScanContext(),
            violation_logger=mock_logger,
            blocked_overrides={"command": "cat /etc/passwd"},
        )
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert blocked["command"] == "cat /etc/passwd"

    def test_context_overrides_merged(self):
        mock_logger = MagicMock()
        result = ScanResult(
            detected=True,
            violation_type=ViolationType.PII_DETECTED,
            id=generate_violation_id(),
        )
        pretool = {"file_path": "/some/file.py"}
        log_violation(
            result,
            ScanContext(),
            violation_logger=mock_logger,
            context_overrides={"pretool_context": pretool},
        )
        ctx = mock_logger.log_violation.call_args[1]["context"]
        assert ctx["pretool_context"] == pretool

    def test_line_number_in_blocked(self):
        mock_logger = MagicMock()
        result = ScanResult(
            detected=True,
            violation_type=ViolationType.PII_DETECTED,
            id=generate_violation_id(),
            line_number=5,
            file_path="/f.py",
        )
        log_violation(result, ScanContext(), violation_logger=mock_logger)
        blocked = mock_logger.log_violation.call_args[1]["blocked"]
        assert blocked["line_number"] == 5
