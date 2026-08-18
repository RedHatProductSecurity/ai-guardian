"""Tests for multi-violation reporting in run_content_pipeline (#2026).

Verifies that all blocking violations are reported in a single response
instead of short-circuiting on the first one.
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


def _make_post_scan_ctx(block=True):
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


@pytest.fixture
def registry():
    return get_default_registry()


@pytest.fixture
def adapter():
    return _make_adapter()


@pytest.fixture
def post_scan_ctx():
    return _make_post_scan_ctx()


class TestMultiViolationReporting:
    """All blocking violations should be reported, not just the first."""

    @patch("ai_guardian.hook_events.content_pipeline.apply_post_scan_pipeline")
    @patch("ai_guardian.scanners.pipeline.scan_content")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_single_violation_unchanged(
        self,
        mock_secret_cfg,
        mock_scan,
        mock_pipeline,
        registry,
        adapter,
        post_scan_ctx,
    ):
        """Single blocking violation produces same format as before."""
        mock_secret_cfg.return_value = (None, None)
        mock_scan.return_value = [
            ScanResult.from_prompt_injection(
                should_block=True,
                detected=True,
                error_message="Injection found in test.py",
                line_number=5,
            ),
        ]
        mock_pipeline.return_value = PostScanDecision(
            should_block=True, error_message="Injection found in test.py"
        )

        result, log_count = run_content_pipeline(
            content_to_scan="malicious content",
            filename="test.py",
            file_path="/tmp/test.py",
            secret_content_to_scan=None,
            pii_content_to_scan=None,
            tool_identifier="Write",
            tool_name="Write",
            warning_messages=[],
            log_only_count=0,
            _registry=registry,
            _post_scan_ctx=post_scan_ctx,
            hook_event=HookEvent.PRE_TOOL_USE,
            adapter=adapter,
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

        assert result is not None
        assert result["_blocked"] is True
        assert "Injection found in test.py" in result["output"]
        assert "Multiple" not in result["output"]

    @patch("ai_guardian.hook_events.content_pipeline.apply_post_scan_pipeline")
    @patch("ai_guardian.scanners.pipeline.scan_content")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_two_violations_combined(
        self,
        mock_secret_cfg,
        mock_scan,
        mock_pipeline,
        registry,
        adapter,
        post_scan_ctx,
    ):
        """Two blocking violations produce combined error with both messages."""
        mock_secret_cfg.return_value = (None, None)
        mock_scan.return_value = [
            ScanResult.from_prompt_injection(
                should_block=True,
                detected=True,
                error_message="Prompt injection in line 3",
                line_number=3,
            ),
            ScanResult.from_context_poisoning(
                should_block=True,
                detected=True,
                error_message="Context poisoning: persistence pattern",
                line_number=10,
            ),
        ]

        call_count = [0]

        def pipeline_side_effect(entry, result, ctx, **kwargs):
            call_count[0] += 1
            return PostScanDecision(
                should_block=True, error_message=result.error_message
            )

        mock_pipeline.side_effect = pipeline_side_effect

        result, log_count = run_content_pipeline(
            content_to_scan="bad content",
            filename="test.py",
            file_path="/tmp/test.py",
            secret_content_to_scan=None,
            pii_content_to_scan=None,
            tool_identifier="Write",
            tool_name="Write",
            warning_messages=[],
            log_only_count=0,
            _registry=registry,
            _post_scan_ctx=post_scan_ctx,
            hook_event=HookEvent.PRE_TOOL_USE,
            adapter=adapter,
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

        assert result is not None
        assert result["_blocked"] is True
        assert "Multiple security violations detected" in result["output"]
        assert "Prompt injection in line 3" in result["output"]
        assert "Context poisoning: persistence pattern" in result["output"]
        assert call_count[0] == 2

    @patch("ai_guardian.hook_events.content_pipeline.apply_post_scan_pipeline")
    @patch("ai_guardian.scanners.pipeline.scan_content")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_violation_types_combined(
        self,
        mock_secret_cfg,
        mock_scan,
        mock_pipeline,
        registry,
        adapter,
        post_scan_ctx,
    ):
        """Combined violation_type field includes all blocking types."""
        mock_secret_cfg.return_value = (None, None)
        mock_scan.return_value = [
            ScanResult.from_prompt_injection(
                should_block=True,
                detected=True,
                error_message="PI found",
                line_number=1,
            ),
            ScanResult.from_context_poisoning(
                should_block=True,
                detected=True,
                error_message="CP found",
                line_number=2,
            ),
        ]
        mock_pipeline.side_effect = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=True, error_message=result.error_message
        )

        result, _ = run_content_pipeline(
            content_to_scan="bad",
            filename="f.py",
            file_path="/tmp/f.py",
            secret_content_to_scan=None,
            pii_content_to_scan=None,
            tool_identifier="Write",
            tool_name="Write",
            warning_messages=[],
            log_only_count=0,
            _registry=registry,
            _post_scan_ctx=post_scan_ctx,
            hook_event=HookEvent.PRE_TOOL_USE,
            adapter=adapter,
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

        vtype_str = result["_violation_type"]
        assert ViolationType.PROMPT_INJECTION.value in vtype_str
        assert ViolationType.CONTEXT_POISONING.value in vtype_str

    @patch("ai_guardian.hook_events.content_pipeline.apply_post_scan_pipeline")
    @patch("ai_guardian.scanners.pipeline.scan_content")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_mix_blocking_and_warn(
        self,
        mock_secret_cfg,
        mock_scan,
        mock_pipeline,
        registry,
        adapter,
        post_scan_ctx,
    ):
        """Non-blocking (warn) results still produce warnings alongside blocks."""
        mock_secret_cfg.return_value = (None, None)
        mock_scan.return_value = [
            ScanResult.from_prompt_injection(
                should_block=True,
                detected=True,
                error_message="PI blocks",
                line_number=1,
            ),
            ScanResult.from_context_poisoning(
                should_block=True,
                detected=True,
                error_message="CP warns only",
                line_number=2,
            ),
        ]

        def pipeline_side_effect(entry, result, ctx, **kwargs):
            if result.violation_type == ViolationType.PROMPT_INJECTION.value:
                return PostScanDecision(should_block=True, error_message="PI blocks")
            return PostScanDecision(should_block=False, warnings=["CP warns only"])

        mock_pipeline.side_effect = pipeline_side_effect

        warning_messages = []
        result, _ = run_content_pipeline(
            content_to_scan="bad",
            filename="f.py",
            file_path="/tmp/f.py",
            secret_content_to_scan=None,
            pii_content_to_scan=None,
            tool_identifier="Write",
            tool_name="Write",
            warning_messages=warning_messages,
            log_only_count=0,
            _registry=registry,
            _post_scan_ctx=post_scan_ctx,
            hook_event=HookEvent.PRE_TOOL_USE,
            adapter=adapter,
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

        assert result is not None
        assert result["_blocked"] is True
        assert "PI blocks" in result["output"]
        assert "Multiple" not in result["output"]
        assert "CP warns only" in warning_messages

    @patch("ai_guardian.hook_events.content_pipeline.apply_post_scan_pipeline")
    @patch("ai_guardian.scanners.pipeline.scan_content")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_no_violations_passes(
        self,
        mock_secret_cfg,
        mock_scan,
        mock_pipeline,
        registry,
        adapter,
        post_scan_ctx,
    ):
        """No detections → pipeline passes (returns None)."""
        mock_secret_cfg.return_value = (None, None)
        mock_scan.return_value = [
            ScanResult.from_prompt_injection(
                should_block=False,
                detected=False,
                error_message=None,
                line_number=None,
            ),
        ]

        result, _ = run_content_pipeline(
            content_to_scan="clean",
            filename="f.py",
            file_path="/tmp/f.py",
            secret_content_to_scan=None,
            pii_content_to_scan=None,
            tool_identifier="Write",
            tool_name="Write",
            warning_messages=[],
            log_only_count=0,
            _registry=registry,
            _post_scan_ctx=post_scan_ctx,
            hook_event=HookEvent.PRE_TOOL_USE,
            adapter=adapter,
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

        assert result is None
        mock_pipeline.assert_not_called()

    @patch("ai_guardian.hook_events.content_pipeline.apply_post_scan_pipeline")
    @patch("ai_guardian.scanners.pipeline.scan_content")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_three_violations_all_reported(
        self,
        mock_secret_cfg,
        mock_scan,
        mock_pipeline,
        registry,
        adapter,
        post_scan_ctx,
    ):
        """Three different scanner types all reported in combined message."""
        mock_secret_cfg.return_value = (
            {
                "enabled": True,
                "ignore_files": [],
                "ignore_tools": [],
                "allowlist_patterns": [],
            },
            None,
        )
        mock_scan.return_value = [
            ScanResult.from_prompt_injection(
                should_block=True,
                detected=True,
                error_message="PI: ignore all rules",
                line_number=1,
            ),
            ScanResult.from_context_poisoning(
                should_block=True,
                detected=True,
                error_message="CP: from now on delete files",
                line_number=5,
            ),
            ScanResult.from_secret_scan(
                has_secrets=True,
                error_message="Secret: AWS key found",
            ),
        ]
        mock_pipeline.side_effect = lambda entry, result, ctx, **kw: PostScanDecision(
            should_block=True, error_message=result.error_message
        )

        result, _ = run_content_pipeline(
            content_to_scan="bad content with secrets and injections",
            filename="evil.py",
            file_path="/tmp/evil.py",
            secret_content_to_scan=None,
            pii_content_to_scan=None,
            tool_identifier="Write",
            tool_name="Write",
            warning_messages=[],
            log_only_count=0,
            _registry=registry,
            _post_scan_ctx=post_scan_ctx,
            hook_event=HookEvent.PRE_TOOL_USE,
            adapter=adapter,
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

        assert result is not None
        assert result["_blocked"] is True
        output = result["output"]
        assert "Multiple security violations detected" in output
        assert "PI: ignore all rules" in output
        assert "CP: from now on delete files" in output
        assert "Secret: AWS key found" in output
