"""Tests for Codex PostToolUse output normalization at the CLI boundary."""

import json

import pytest

from ai_guardian.cli import _normalize_codex_post_tool_use_output

CODEX_POST_TOOL_USE = {
    "_ide_type": "codex",
    "hook_event_name": "PostToolUse",
}


@pytest.mark.parametrize(
    "output",
    [
        "malformed daemon response",
        "[]",
        '"scalar"',
        "42",
        "null",
    ],
)
def test_codex_posttooluse_replaces_malformed_or_non_object_output(output):
    """Codex must receive an empty JSON object for invalid daemon output."""
    normalized = _normalize_codex_post_tool_use_output(CODEX_POST_TOOL_USE, output)

    assert json.loads(normalized) == {}


def test_codex_posttooluse_preserves_valid_object_output():
    """Valid Codex response objects pass through unchanged."""
    output = '{"hookSpecificOutput":{"hookEventName":"PostToolUse"}}'

    assert _normalize_codex_post_tool_use_output(CODEX_POST_TOOL_USE, output) == output


def test_codex_posttooluse_serializes_object_output():
    """Unexpected in-memory response objects remain valid JSON."""
    output = {"hookSpecificOutput": {"hookEventName": "PostToolUse"}}

    assert (
        json.loads(_normalize_codex_post_tool_use_output(CODEX_POST_TOOL_USE, output))
        == output
    )


def test_non_codex_posttooluse_output_is_unchanged():
    """Other hook protocols retain their existing stdout behavior."""
    output = "not JSON"
    hook_data = {
        "_ide_type": "claude",
        "hook_event_name": "PostToolUse",
    }

    assert _normalize_codex_post_tool_use_output(hook_data, output) == output
