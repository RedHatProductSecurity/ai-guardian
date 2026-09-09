"""Tests for stable agent attribution independent of hook response format."""

from unittest.mock import MagicMock

import pytest

from ai_guardian.hook_adapters import (
    AugmentAdapter,
    BaseAgentAdapter,
    CodexAdapter,
    CrushAdapter,
    DummyAgentAdapter,
    OpenCodeAdapter,
    WindsurfAdapter,
    detect_adapter,
    get_adapter_by_ide_type,
)
from ai_guardian.response_format import IDEType
from ai_guardian.scanners.scan_result import ScanResult
from ai_guardian.tools.policy import ToolPolicyChecker
from ai_guardian.violations.log_violation import ScanContext, log_violation


def test_codex_keeps_claude_response_protocol_but_has_codex_attribution():
    adapter = CodexAdapter()

    assert adapter.ide_type == IDEType.CLAUDE_CODE
    assert adapter.agent_type == "codex"


@pytest.mark.parametrize(
    ("adapter_cls", "expected_agent_type"),
    [
        (CodexAdapter, "codex"),
        (WindsurfAdapter, "windsurf"),
        (AugmentAdapter, "augment"),
        (OpenCodeAdapter, "opencode"),
        (CrushAdapter, "crush"),
        (DummyAgentAdapter, "dummy_agent"),
    ],
)
def test_claude_compatible_adapters_keep_distinct_attribution(
    adapter_cls, expected_agent_type
):
    adapter = adapter_cls()

    assert adapter.ide_type == IDEType.CLAUDE_CODE
    assert adapter.agent_type == expected_agent_type


def test_ambiguous_payload_uses_unknown_attribution():
    adapter = detect_adapter({})

    assert isinstance(adapter, BaseAgentAdapter)
    assert adapter.ide_type == IDEType.CLAUDE_CODE
    assert adapter.agent_type == "unknown"


def test_unknown_legacy_ide_lookup_uses_unknown_attribution():
    adapter = get_adapter_by_ide_type(IDEType.UNKNOWN)

    assert adapter.ide_type == IDEType.CLAUDE_CODE
    assert adapter.agent_type == "unknown"


def test_tool_policy_uses_adapter_attribution():
    checker = ToolPolicyChecker(config={})

    assert checker._detect_ide_type({"_ide_type": "codex"}) == "codex"
    assert checker._detect_ide_type({}) == "unknown"


def test_violation_context_serializes_attribution_value():
    result = ScanResult(
        detected=True,
        violation_type="tool_permission",
        id="violation-test",
        severity="warning",
        error_message="Tool denied",
    )
    violation_logger = MagicMock()

    log_violation(
        result,
        ScanContext(ide_type="codex", hook_event="PreToolUse"),
        violation_logger=violation_logger,
    )

    context = violation_logger.log_violation.call_args.kwargs["context"]
    assert context["ide_type"] == "codex"
