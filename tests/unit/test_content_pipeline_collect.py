"""Tests for _collect() refactoring in content_pipeline (#2049).

Regression tests ensuring each scanner branch through _collect()
preserves the original behavior: correct error messages, log gating,
non-block warning fallthrough, and tracking flag side-effects.
"""

from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.constants import HookEvent, ViolationType
from ai_guardian.hook_events.content_pipeline import run_content_pipeline
from ai_guardian.response_format import IDEType
from ai_guardian.scanners.post_scan_filters import PostScanContext, PostScanDecision
from ai_guardian.scanners.scan_result import ScanResult
from ai_guardian.scanners.scanner_registry import (
    ScannerName,
    get_default_registry,
)


def _make_adapter():
    adapter = MagicMock()
    adapter.format_response.side_effect = lambda **kw: {
        "output": kw.get("error_message", ""),
        "exit_code": 1 if kw.get("has_secrets") else 0,
        "_blocked": kw.get("has_secrets", False),
        "_violation_type": str(kw.get("violation_type", "")),
        "_warning_message": kw.get("warning_message"),
    }
    return adapter


def _make_post_scan_ctx():
    ctx = MagicMock(spec=PostScanContext)
    ctx.hook_event = HookEvent.PRE_TOOL_USE
    ctx.hook_session_id = "test-session"
    ctx.hook_tool_use_id = "test-tool-use"
    ctx.tool_name = "Write"
    ctx.ide_type_value = "claude_code"
    ctx.violation_logger = MagicMock()
    ctx.latency_timer = MagicMock()
    ctx.invocation_allowed_findings = None
    ctx.daemon_state = None
    return ctx


def _run_pipeline(scan_results, pipeline_side_effect, **overrides):
    """Helper to call run_content_pipeline with common defaults."""
    with (
        patch(
            "ai_guardian.config.loaders._load_secret_scanning_config",
            return_value=(
                {
                    "enabled": True,
                    "ignore_files": [],
                    "ignore_tools": [],
                    "allowlist_patterns": [],
                },
                None,
            ),
        ),
        patch(
            "ai_guardian.scanners.pipeline.scan_content",
            return_value=scan_results,
        ),
        patch(
            "ai_guardian.hook_events.content_pipeline.apply_post_scan_pipeline",
            side_effect=pipeline_side_effect,
        ),
    ):
        kwargs = dict(
            content_to_scan="test content",
            filename="test.py",
            file_path="/tmp/test.py",
            secret_content_to_scan=None,
            pii_content_to_scan=None,
            tool_identifier="Write",
            tool_name="Write",
            warning_messages=[],
            log_only_count=0,
            _registry=get_default_registry(),
            _post_scan_ctx=_make_post_scan_ctx(),
            hook_event=HookEvent.PRE_TOOL_USE,
            adapter=_make_adapter(),
            ide_type=IDEType.CLAUDE_CODE,
            now=None,
            hook_session_id="s1",
            hook_tool_use_id="t1",
            context_mgr=None,
            _latency_timer=MagicMock(),
            security_message=None,
            _invocation_allowed=set(),
            hook_data={},
        )
        kwargs.update(overrides)
        return run_content_pipeline(**kwargs)


class TestCollectPromptInjection:
    """PI branch: sets _pretool_pi_detected, respects Cursor log gate."""

    def test_pi_block_uses_decision_error(self):
        """PI blocking uses decision.error_message, not result.error_message."""
        results = [
            ScanResult.from_prompt_injection(
                should_block=True,
                detected=True,
                error_message="result msg",
                line_number=1,
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=True, error_message="decision msg"
        )
        resp, _ = _run_pipeline(results, pipeline)
        assert resp is not None
        assert "decision msg" in resp["output"]

    def test_pi_warn_not_block(self):
        """PI non-blocking adds warnings but doesn't block."""
        results = [
            ScanResult.from_prompt_injection(
                should_block=True,
                detected=True,
                error_message="PI detected",
                line_number=1,
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=False, warnings=["PI warning"]
        )
        warnings = []
        resp, _ = _run_pipeline(results, pipeline, warning_messages=warnings)
        assert resp is None
        assert "PI warning" in warnings

    def test_pi_cursor_suppresses_log(self):
        """Cursor IDE suppresses PI block log but still blocks."""
        results = [
            ScanResult.from_prompt_injection(
                should_block=True,
                detected=True,
                error_message="PI found",
                line_number=1,
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=True, error_message="PI found"
        )
        with patch("ai_guardian.hook_events.content_pipeline.logger") as mock_log:
            resp, _ = _run_pipeline(results, pipeline, ide_type=IDEType.CURSOR)
            assert resp is not None
            assert resp["_blocked"] is True
            info_calls = [
                str(c)
                for c in mock_log.info.call_args_list
                if "prompt injection" in str(c)
            ]
            assert len(info_calls) == 0


class TestCollectContextPoisoning:
    """CP branch: sets _pretool_cp_detected."""

    def test_cp_block(self):
        results = [
            ScanResult.from_context_poisoning(
                should_block=True,
                detected=True,
                error_message="CP: persistence pattern",
                line_number=5,
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=True, error_message="CP: persistence pattern"
        )
        resp, _ = _run_pipeline(results, pipeline)
        assert resp is not None
        assert "CP: persistence pattern" in resp["output"]

    def test_cp_warn_only(self):
        results = [
            ScanResult.from_context_poisoning(
                should_block=True,
                detected=True,
                error_message="CP found",
                line_number=5,
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=False, warnings=["CP warn"]
        )
        warnings = []
        resp, _ = _run_pipeline(results, pipeline, warning_messages=warnings)
        assert resp is None
        assert "CP warn" in warnings


class TestCollectSecret:
    """SECRET branch: uses skip_violation_log, error_override=result.error_message."""

    def test_secret_block_uses_result_error(self):
        """SECRET blocking uses result.error_message, not decision.error_message."""
        results = [
            ScanResult.from_secret_scan(
                has_secrets=True,
                error_message="AWS key found in line 3",
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=True, error_message="pipeline says blocked"
        )
        resp, _ = _run_pipeline(results, pipeline)
        assert resp is not None
        assert "AWS key found in line 3" in resp["output"]
        assert "pipeline says blocked" not in resp["output"]

    def test_secret_skip_violation_log_kwarg(self):
        """SECRET passes skip_violation_log=True to apply_post_scan_pipeline."""
        results = [
            ScanResult.from_secret_scan(
                has_secrets=True,
                error_message="secret found",
            ),
        ]
        captured_kwargs = {}

        def pipeline(entry, result, ctx, **kw):
            captured_kwargs.update(kw)
            return PostScanDecision(should_block=True, error_message="blocked")

        _run_pipeline(results, pipeline)
        assert captured_kwargs.get("skip_violation_log") is True

    def test_secret_not_blocked_by_pipeline(self):
        """SECRET allows through when pipeline says should_block=False."""
        results = [
            ScanResult.from_secret_scan(
                has_secrets=True,
                error_message="secret found",
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=False, warnings=["secret warning"]
        )
        warnings = []
        resp, _ = _run_pipeline(results, pipeline, warning_messages=warnings)
        assert resp is None
        assert "secret warning" in warnings


class TestCollectConfigFile:
    """CONFIG_FILE branch: blocked_overrides, Cursor gate, non_block_warning."""

    def test_cfs_block_uses_result_error(self):
        """CONFIG_FILE blocking uses result.error_message."""
        details = {"matched_text": "cat ~/.ssh/id_rsa"}
        results = [
            ScanResult.from_config_exfil(
                should_block=True,
                error_message="Config file exfiltration detected",
                details=details,
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=True, error_message="pipeline error"
        )
        resp, _ = _run_pipeline(results, pipeline)
        assert resp is not None
        assert "Config file exfiltration detected" in resp["output"]

    def test_cfs_passes_blocked_overrides(self):
        """CONFIG_FILE passes details as blocked_overrides."""
        details = {"matched_text": "exfil attempt"}
        result = ScanResult.from_config_exfil(
            should_block=True,
            error_message="CFS blocked",
            details=details,
        )
        results = [result]
        captured_kwargs = {}

        def pipeline(entry, res, ctx, **kw):
            captured_kwargs.update(kw)
            return PostScanDecision(should_block=True, error_message="blocked")

        _run_pipeline(results, pipeline)
        assert "blocked_overrides" in captured_kwargs
        assert captured_kwargs["blocked_overrides"]["details"] == result.extra.get(
            "details"
        )

    def test_cfs_non_block_adds_warning(self):
        """CONFIG_FILE adds result.error_message as warning when not blocked."""
        details = {"matched_text": "suspicious"}
        results = [
            ScanResult.from_config_exfil(
                should_block=False,
                error_message="Config file warning",
                details=details,
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(should_block=False)
        warnings = []
        resp, _ = _run_pipeline(results, pipeline, warning_messages=warnings)
        assert resp is None
        assert "Config file warning" in warnings

    def test_cfs_cursor_suppresses_log(self):
        """Cursor IDE suppresses CONFIG_FILE block log."""
        details = {"matched_text": "cat /etc/passwd"}
        results = [
            ScanResult.from_config_exfil(
                should_block=True,
                error_message="CFS blocked",
                details=details,
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=True, error_message="CFS blocked"
        )
        with patch("ai_guardian.hook_events.content_pipeline.logger") as mock_log:
            resp, _ = _run_pipeline(results, pipeline, ide_type=IDEType.CURSOR)
            assert resp is not None
            info_calls = [
                str(c) for c in mock_log.info.call_args_list if "config file" in str(c)
            ]
            assert len(info_calls) == 0


class TestCollectGenericScanner:
    """Generic else branch: supply_chain, offensive_language, canary_detection."""

    def test_supply_chain_block(self):
        results = [
            ScanResult.from_supply_chain(
                should_block=True,
                error_message="Typosquat detected: reqeusts",
                details={"matched_text": "reqeusts"},
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=True, error_message="Typosquat detected: reqeusts"
        )
        resp, _ = _run_pipeline(results, pipeline)
        assert resp is not None
        assert "Typosquat detected" in resp["output"]

    def test_generic_non_block_adds_warning(self):
        """Generic scanner adds result.error_message as warning when not blocked."""
        results = [
            ScanResult.from_offensive_language(
                findings=[{"text": "bad word", "category": "slur"}],
                action="warn",
            ),
        ]
        results[0].error_message = "Offensive language warning"
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(should_block=False)
        warnings = []
        resp, _ = _run_pipeline(results, pipeline, warning_messages=warnings)
        assert resp is None
        assert "Offensive language warning" in warnings

    def test_generic_uses_fallback_file_path(self):
        """Generic scanner passes file_path or filename or 'content' to pipeline."""
        results = [
            ScanResult.from_supply_chain(
                should_block=True,
                error_message="SC detected",
                details={"matched_text": "bad-pkg"},
            ),
        ]
        captured_kwargs = {}

        def pipeline(entry, result, ctx, **kw):
            captured_kwargs.update(kw)
            return PostScanDecision(should_block=True, error_message="SC detected")

        _run_pipeline(results, pipeline, file_path=None, filename="fallback.py")
        assert captured_kwargs["file_path"] == "fallback.py"

    def test_generic_content_fallback_when_no_path(self):
        """Generic scanner uses 'content' when both file_path and filename are None."""
        results = [
            ScanResult.from_supply_chain(
                should_block=True,
                error_message="SC detected",
                details={"matched_text": "bad-pkg"},
            ),
        ]
        captured_kwargs = {}

        def pipeline(entry, result, ctx, **kw):
            captured_kwargs.update(kw)
            return PostScanDecision(should_block=True, error_message="SC detected")

        _run_pipeline(results, pipeline, file_path=None, filename=None)
        assert captured_kwargs["file_path"] == "content"


class TestCollectWarnViolationTypes:
    """warn_violation_types tracking across branches."""

    def test_warn_types_populated_on_warnings(self):
        """warn_violation_types receives vtype when decision has warnings."""
        results = [
            ScanResult.from_context_poisoning(
                should_block=True,
                detected=True,
                error_message="CP found",
                line_number=1,
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=False, warnings=["CP warned"]
        )
        warn_vtypes = []
        _run_pipeline(results, pipeline, warn_violation_types=warn_vtypes)
        assert ViolationType.CONTEXT_POISONING in warn_vtypes

    def test_warn_types_none_safe(self):
        """warn_violation_types=None doesn't crash."""
        results = [
            ScanResult.from_prompt_injection(
                should_block=True,
                detected=True,
                error_message="PI found",
                line_number=1,
            ),
        ]
        pipeline = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=False, warnings=["PI warned"]
        )
        resp, _ = _run_pipeline(results, pipeline, warn_violation_types=None)
        assert resp is None
