"""Rendering contracts for hook-originated unified traces (#2190)."""

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.pages.traces import (
    _format_tool_result_output,
    _get_tool_result_output,
    _get_turn_prompt_preview,
    _get_turn_type,
)


def test_hook_turn_with_tools_is_classified_as_tool_use():
    steps = [
        {"type": "prompt", "text": "Inspect the project"},
        {"type": "scan", "scanned": "prompt", "violations": []},
        {"type": "tool_call", "name": "Bash", "input": {"command": "pwd"}},
    ]

    assert _get_turn_type(steps) == "tool_use"


def test_hook_prompt_only_turn_is_classified_as_user():
    steps = [
        {"type": "prompt", "text": "Explain the result"},
        {"type": "scan", "scanned": "prompt", "violations": []},
    ]

    assert _get_turn_type(steps) == "user"
    assert _get_turn_prompt_preview(steps) == "Explain the result"


def test_hook_tool_result_content_is_rendered():
    assert (
        _get_tool_result_output(
            {"type": "tool_result", "name": "Bash", "content": "command output"}
        )
        == "command output"
    )


def test_sdk_tool_result_output_takes_precedence():
    assert (
        _get_tool_result_output(
            {"type": "tool_result", "output": "sdk output", "content": "legacy output"}
        )
        == "sdk output"
    )


def test_tool_result_dict_is_formatted_as_json():
    formatted = _format_tool_result_output({"status": "ok", "count": 2})

    assert formatted == '{\n  "status": "ok",\n  "count": 2\n}'


def test_tool_result_text_is_unchanged():
    assert _format_tool_result_output("command output") == "command output"
