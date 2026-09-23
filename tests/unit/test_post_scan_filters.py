"""Tests for post-scan filter pipeline (Phase 4, Issue #1254)."""

from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.scanners.post_scan_filters import (
    PostScanContext,
    PostScanDecision,
    apply_post_scan_pipeline,
    build_detailed_warn_message,
    build_violation_blocked,
    log_scan_violation,
    log_scan_violations_per_finding,
)
from ai_guardian.scanners.scan_result import ScanResult


def _make_ctx(**overrides):
    defaults = dict(
        handle_ask_mode_auto=MagicMock(return_value=None),
        log_ask_decision=MagicMock(),
        format_ask_info_message=MagicMock(return_value="info: allowed"),
        hook_event="PreToolUse",
        hook_session_id="sess-1",
        hook_tool_use_id="tu-1",
        tool_name="Read",
        ide_type_value="claude_code",
        violation_logger=MagicMock(),
        latency_timer=None,
    )
    defaults.update(overrides)
    return PostScanContext(**defaults)


def _make_entry(**overrides):
    from ai_guardian.constants import ViolationType

    entry = MagicMock()
    entry.violation_type = overrides.get(
        "violation_type", ViolationType.CANARY_DETECTED
    )
    entry.supports_ask_mode = overrides.get("supports_ask_mode", True)
    entry.config_section = overrides.get("config_section", "canary_detection")
    entry.violation_severity = overrides.get("violation_severity", "high")
    entry.violation_suggestion = overrides.get(
        "violation_suggestion", {"action": "test", "note": "test note"}
    )
    entry.name = overrides.get("name", "canary_detection")
    return entry


def _detected_result(**overrides):
    defaults = dict(
        detected=True,
        violation_type="canary_detected",
        severity="high",
        should_block=True,
        error_message="Canary token detected",
        matched_text="CANARY_abc123",
        matched_pattern="canary_pattern",
        rule_id="canary-1",
        file_path="/tmp/test.py",
        line_number=42,
        start_column=5,
        end_column=20,
        attack_type="data_exfiltration",
        confidence=0.95,
        total_findings=2,
        extra={"action": "block"},
    )
    defaults.update(overrides)
    return ScanResult(**defaults)


# ── build_violation_blocked ────────────────────────────────────


class TestBuildViolationBlocked:
    def test_maps_all_fields(self):
        result = _detected_result()
        blocked = build_violation_blocked(result)
        assert blocked["file_path"] == "/tmp/test.py"
        assert blocked["line_number"] == 42
        assert blocked["start_column"] == 5
        assert blocked["end_column"] == 20
        assert blocked["matched_text"] == "CANARY_abc123"
        assert blocked["pattern"] == "canary_pattern"
        assert blocked["rule_id"] == "canary-1"
        assert blocked["category"] == "data_exfiltration"
        assert blocked["confidence"] == 0.95
        assert blocked["total_findings"] == 2
        assert blocked["reason"] == "Canary token detected"

    def test_truncates_matched_text(self):
        result = _detected_result(matched_text="x" * 200)
        blocked = build_violation_blocked(result)
        assert len(blocked["matched_text"]) == 100

    def test_omits_none_fields(self):
        result = _detected_result(
            start_column=None,
            end_column=None,
            confidence=None,
            total_findings=1,
        )
        blocked = build_violation_blocked(result)
        assert "start_column" not in blocked
        assert "end_column" not in blocked
        assert "confidence" not in blocked
        assert "total_findings" not in blocked

    def test_source_field(self):
        result = _detected_result()
        blocked = build_violation_blocked(result, source="user_prompt")
        assert blocked["source"] == "user_prompt"

    def test_extra_fields_merged(self):
        result = _detected_result()
        blocked = build_violation_blocked(result, extra_fields={"token": "my-canary"})
        assert blocked["token"] == "my-canary"


# ── log_scan_violation ─────────────────────────────────────────


class TestLogScanViolation:
    def test_calls_violation_logger(self):
        ctx = _make_ctx()
        entry = _make_entry()
        result = _detected_result()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            log_scan_violation(entry, result, ctx)
        ctx.violation_logger.log_violation.assert_called_once()
        call_kwargs = ctx.violation_logger.log_violation.call_args[1]
        assert call_kwargs["violation_type"] == entry.violation_type
        assert call_kwargs["severity"] == "high"
        assert call_kwargs["suggestion"] == {"action": "test", "note": "test note"}

    def test_noop_when_no_logger(self):
        ctx = _make_ctx(violation_logger=None)
        entry = _make_entry()
        result = _detected_result()
        log_scan_violation(entry, result, ctx)

    def test_uses_severity_override(self):
        ctx = _make_ctx()
        entry = _make_entry()
        result = _detected_result()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            log_scan_violation(entry, result, ctx, severity_override="critical")
        call_kwargs = ctx.violation_logger.log_violation.call_args[1]
        assert call_kwargs["severity"] == "critical"

    def test_policy_decision_uses_effective_severity(self):
        ctx = _make_ctx()
        entry = _make_entry(violation_severity="critical")
        result = _detected_result(severity="low")
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            decision = apply_post_scan_pipeline(entry, result, ctx)

        assert decision.policy_decision["severity"] == "critical"
        logged = ctx.violation_logger.log_violation.call_args[1]["policy_decision"]
        assert logged.to_dict()["severity"] == "critical"

    def test_context_includes_hook_ids(self):
        ctx = _make_ctx()
        entry = _make_entry()
        result = _detected_result()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            log_scan_violation(entry, result, ctx)
        call_kwargs = ctx.violation_logger.log_violation.call_args[1]
        vctx = call_kwargs["context"]
        assert vctx["tool_use_id"] == "tu-1"
        assert vctx["session_id"] == "sess-1"
        assert vctx["hook_event"] == "PreToolUse"

    def test_fail_open_on_logger_error(self):
        ctx = _make_ctx()
        ctx.violation_logger.log_violation.side_effect = RuntimeError("boom")
        entry = _make_entry()
        result = _detected_result()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            log_scan_violation(entry, result, ctx)


# ── apply_post_scan_pipeline ───────────────────────────────────


class TestApplyPostScanPipeline:
    def test_clean_result_returns_no_block(self):
        ctx = _make_ctx()
        entry = _make_entry()
        result = ScanResult.clean("canary_detected")
        decision = apply_post_scan_pipeline(entry, result, ctx)
        assert not decision.should_block
        assert decision.warnings == []
        ctx.violation_logger.log_violation.assert_not_called()

    def test_detected_triggers_violation_log(self):
        ctx = _make_ctx()
        entry = _make_entry()
        result = _detected_result()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            apply_post_scan_pipeline(entry, result, ctx, file_path="/tmp/t.py")
        ctx.violation_logger.log_violation.assert_called_once()

    def test_ask_mode_block_preserves_block(self):
        from ai_guardian.tui.ask_dialog import AskDecision

        ask_result = MagicMock()
        ask_result.decision = AskDecision.BLOCK
        ask_result.dialog_wait_ms = 100.0
        ctx = _make_ctx(handle_ask_mode_auto=MagicMock(return_value=ask_result))
        entry = _make_entry()
        result = _detected_result()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            decision = apply_post_scan_pipeline(entry, result, ctx)
        assert decision.should_block

    def test_ask_mode_allow_sets_no_block(self):
        from ai_guardian.tui.ask_dialog import AskDecision

        ask_result = MagicMock()
        ask_result.decision = AskDecision.ALLOW_ONCE
        ask_result.dialog_wait_ms = 50.0
        ctx = _make_ctx(handle_ask_mode_auto=MagicMock(return_value=ask_result))
        entry = _make_entry()
        result = _detected_result()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            decision = apply_post_scan_pipeline(
                entry, result, ctx, file_path="/tmp/t.py"
            )
        assert not decision.should_block
        assert len(decision.warnings) == 1

    def test_ask_mode_skipped_when_not_supported(self):
        ctx = _make_ctx()
        entry = _make_entry(supports_ask_mode=False)
        result = _detected_result()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            decision = apply_post_scan_pipeline(entry, result, ctx)
        assert decision.should_block
        ctx.handle_ask_mode_auto.assert_not_called()

    def test_ask_mode_skipped_when_not_blocking(self):
        ctx = _make_ctx()
        entry = _make_entry()
        result = _detected_result(should_block=False)
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            decision = apply_post_scan_pipeline(entry, result, ctx)
        assert not decision.should_block
        ctx.handle_ask_mode_auto.assert_not_called()
        assert len(decision.warnings) == 1
        assert "warn mode" in decision.warnings[0]

    def test_warnings_on_non_blocking_detection(self):
        ctx = _make_ctx()
        entry = _make_entry()
        result = _detected_result(should_block=False, error_message="OL: slur found")
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            decision = apply_post_scan_pipeline(entry, result, ctx)
        assert len(decision.warnings) == 1
        assert "warn mode" in decision.warnings[0]
        assert "/tmp/test.py:42" in decision.warnings[0]

    def test_ask_decision_returned(self):
        from ai_guardian.tui.ask_dialog import AskDecision

        ask_result = MagicMock()
        ask_result.decision = AskDecision.ALLOW_ALWAYS
        ask_result.dialog_wait_ms = 200.0
        ctx = _make_ctx(handle_ask_mode_auto=MagicMock(return_value=ask_result))
        entry = _make_entry()
        result = _detected_result()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            decision = apply_post_scan_pipeline(entry, result, ctx)
        assert decision.ask_decision is ask_result

    def test_log_ask_decision_called(self):
        from ai_guardian.tui.ask_dialog import AskDecision

        ask_result = MagicMock()
        ask_result.decision = AskDecision.ALLOW_ONCE
        ask_result.dialog_wait_ms = 50.0
        ctx = _make_ctx(handle_ask_mode_auto=MagicMock(return_value=ask_result))
        entry = _make_entry()
        result = _detected_result()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            apply_post_scan_pipeline(entry, result, ctx, file_path="/f.py")
        ctx.log_ask_decision.assert_called_once()
        call_kwargs = ctx.log_ask_decision.call_args[1]
        assert call_kwargs["file_path"] == "/f.py"
        assert call_kwargs["dialog_wait_ms"] == 50.0

    def test_post_scan_decision_dataclass(self):
        d = PostScanDecision(should_block=True, error_message="err")
        assert d.should_block
        assert d.error_message == "err"
        assert d.warnings == []
        assert d.ask_decision is None

    def test_skip_violation_log(self):
        ctx = _make_ctx()
        entry = _make_entry()
        result = _detected_result()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            decision = apply_post_scan_pipeline(
                entry, result, ctx, skip_violation_log=True
            )
        assert decision.should_block
        ctx.violation_logger.log_violation.assert_not_called()

    def test_finding_fingerprints_forwarded(self):
        from ai_guardian.tui.ask_dialog import AskDecision

        ask_result = MagicMock()
        ask_result.decision = AskDecision.ALLOW_ONCE
        ask_result.dialog_wait_ms = 50.0
        ctx = _make_ctx(handle_ask_mode_auto=MagicMock(return_value=ask_result))
        entry = _make_entry()
        result = _detected_result()
        fps = ["fp1", "fp2"]
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            apply_post_scan_pipeline(entry, result, ctx, finding_fingerprints=fps)
        call_kwargs = ctx.log_ask_decision.call_args[1]
        assert call_kwargs["finding_fingerprints"] == fps

    def test_invocation_allowed_forwarded(self):
        from ai_guardian.tui.ask_dialog import AskDecision

        ask_result = MagicMock()
        ask_result.decision = AskDecision.ALLOW_ONCE
        ask_result.dialog_wait_ms = 50.0
        allowed_set = {"hash1", "hash2"}
        ctx = _make_ctx(
            handle_ask_mode_auto=MagicMock(return_value=ask_result),
            invocation_allowed_findings=allowed_set,
        )
        entry = _make_entry()
        result = _detected_result()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            apply_post_scan_pipeline(entry, result, ctx)
        call_kwargs = ctx.log_ask_decision.call_args[1]
        assert call_kwargs["invocation_allowed_findings"] is allowed_set


# ── log_scan_violations_per_finding ───────────────────────────


class TestLogScanViolationsPerFinding:
    def test_logs_each_finding(self):
        ctx = _make_ctx()
        entry = _make_entry()
        findings = [
            MagicMock(
                rule_id="B101",
                description="assert",
                severity="LOW",
                line_number=10,
                start_column=0,
            ),
            MagicMock(
                rule_id="B105",
                description="hardcoded password",
                severity="HIGH",
                line_number=25,
                start_column=4,
            ),
        ]
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            log_scan_violations_per_finding(
                entry, findings, ctx, file_path="/tmp/app.py"
            )
        assert ctx.violation_logger.log_violation.call_count == 2
        first_call = ctx.violation_logger.log_violation.call_args_list[0][1]
        assert first_call["blocked"]["rule_id"] == "B101"
        assert first_call["blocked"]["file_path"] == "/tmp/app.py"
        second_call = ctx.violation_logger.log_violation.call_args_list[1][1]
        assert second_call["blocked"]["rule_id"] == "B105"
        assert second_call["blocked"]["line_number"] == 25

    def test_noop_when_no_logger(self):
        ctx = _make_ctx(violation_logger=None)
        entry = _make_entry()
        log_scan_violations_per_finding(entry, [MagicMock()], ctx)

    def test_noop_when_empty_findings(self):
        ctx = _make_ctx()
        entry = _make_entry()
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            log_scan_violations_per_finding(entry, [], ctx)
        ctx.violation_logger.log_violation.assert_not_called()

    def test_uses_entry_severity_as_fallback(self):
        ctx = _make_ctx()
        entry = _make_entry(violation_severity="medium")
        finding = MagicMock(
            rule_id="B101",
            description="test",
            severity=None,
            line_number=1,
            start_column=None,
        )
        with patch("ai_guardian.config.utils.get_project_dir", return_value="/proj"):
            log_scan_violations_per_finding(entry, [finding], ctx)
        call_kwargs = ctx.violation_logger.log_violation.call_args[1]
        assert call_kwargs["severity"] == "medium"


class TestBuildDetailedWarnMessage:

    def test_includes_file_and_line(self):
        entry = _make_entry(violation_type="prompt_injection")
        result = _detected_result(
            file_path="/src/app.py",
            line_number=42,
            rule_id="pi-001",
            attack_type="Python dunder",
        )
        msg = build_detailed_warn_message(entry, result)
        assert "Prompt injection detected" in msg
        assert "/src/app.py:42" in msg
        assert "pi-001" in msg
        assert "Python dunder" in msg
        assert "warn mode" in msg

    def test_file_path_from_arg(self):
        entry = _make_entry(violation_type="secret_detected")
        result = _detected_result(file_path=None, line_number=None)
        msg = build_detailed_warn_message(entry, result, file_path="/etc/config")
        assert "/etc/config" in msg

    def test_no_file_path(self):
        entry = _make_entry(violation_type="ssrf_blocked")
        result = _detected_result(file_path=None, line_number=None)
        msg = build_detailed_warn_message(entry, result)
        assert "warn mode" in msg
        assert " in " not in msg

    def test_no_rule_id_no_attack_type(self):
        entry = _make_entry(violation_type="prompt_injection")
        result = _detected_result(rule_id="", attack_type="")
        msg = build_detailed_warn_message(entry, result)
        assert "(" not in msg

    def test_unknown_violation_type(self):
        entry = _make_entry(violation_type="new_scanner")
        result = _detected_result(file_path="/f.py", line_number=1)
        msg = build_detailed_warn_message(entry, result)
        assert "Security violation detected" in msg
        assert "/f.py:1" in msg
