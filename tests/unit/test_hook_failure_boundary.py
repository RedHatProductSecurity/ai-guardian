"""Regression tests for hook startup and process-failure handling (#2434)."""

import json
import builtins
import os
from io import StringIO
from unittest.mock import patch

import pytest

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters import BaseAgentAdapter, CodexAdapter, CursorAdapter
from ai_guardian.hook_processing import process_hook_data
from ai_guardian_hook_runtime import (
    HOOK_FAILURE_MESSAGE,
    build_failure_response,
    ensure_hook_response,
    main as runtime_main,
)


def _json_output(result):
    assert isinstance(result.get("output"), str)
    return json.loads(result["output"])


def test_startup_import_failure_uses_cursor_fail_open_response(capsys):
    """A package import error must not strand a Cursor development hook."""
    real_import = builtins.__import__

    def fail_cli_import(name, *args, **kwargs):
        if name == "ai_guardian.cli":
            raise ImportError("synthetic startup failure")
        return real_import(name, *args, **kwargs)

    hook_data = {
        "cursor_version": "0.50.0",
        "hook_event_name": "beforeSubmitPrompt",
        "prompt": "run the tests",
    }
    with (
        patch.dict(
            os.environ, {"AI_GUARDIAN_CONFIG_INLINE": '{"on_scan_error":"allow"}'}
        ),
        patch("sys.argv", ["ai-guardian"]),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
        patch("builtins.__import__", side_effect=fail_cli_import),
    ):
        exit_code = runtime_main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {"continue": True}
    assert captured.err == ""


def test_startup_import_failure_uses_codex_posttooluse_json(capsys):
    """Codex PostToolUse always receives a JSON object on fail-open."""
    real_import = builtins.__import__

    def fail_cli_import(name, *args, **kwargs):
        if name == "ai_guardian.cli":
            raise SyntaxError("synthetic startup failure")
        return real_import(name, *args, **kwargs)

    hook_data = {
        "_ide_type": "codex",
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
    }
    with (
        patch.dict(
            os.environ, {"AI_GUARDIAN_CONFIG_INLINE": '{"on_scan_error":"allow"}'}
        ),
        patch("sys.argv", ["ai-guardian"]),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
        patch("builtins.__import__", side_effect=fail_cli_import),
    ):
        exit_code = runtime_main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {}
    assert captured.err == ""


def test_startup_import_failure_uses_cursor_fail_closed_response(capsys):
    """Strict process policy returns a valid Cursor denial after startup failure."""
    real_import = builtins.__import__

    def fail_cli_import(name, *args, **kwargs):
        if name == "ai_guardian.cli":
            raise ImportError("synthetic startup failure")
        return real_import(name, *args, **kwargs)

    hook_data = {
        "cursor_version": "0.50.0",
        "hook_event_name": "beforeShellExecution",
        "command": "pytest",
    }
    with (
        patch.dict(
            os.environ, {"AI_GUARDIAN_CONFIG_INLINE": '{"on_scan_error":"block"}'}
        ),
        patch("sys.argv", ["ai-guardian"]),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
        patch("builtins.__import__", side_effect=fail_cli_import),
    ):
        exit_code = runtime_main()

    captured = capsys.readouterr()
    response = json.loads(captured.out)
    assert exit_code == 0
    assert response["permission"] == "deny"
    assert response["user_message"] == HOOK_FAILURE_MESSAGE
    assert "synthetic startup failure" not in captured.out


def test_direct_fallback_failure_honors_block_policy():
    """A daemon/direct processing failure must use on_scan_error=block."""
    hook_data = {
        "cursor_version": "0.50.0",
        "hook_event_name": "beforeShellExecution",
        "command": "pytest",
    }
    with (
        patch(
            "ai_guardian.cli._load_config_file",
            return_value=({"on_scan_error": "block"}, None),
        ),
        patch("ai_guardian.daemon.client.is_daemon_running", return_value=False),
        patch("ai_guardian.daemon.client.start_daemon_background", return_value=False),
        patch(
            "ai_guardian.cli.process_hook_data",
            side_effect=RuntimeError("synthetic direct failure"),
        ),
        patch("sys.argv", ["ai-guardian"]),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
    ):
        with pytest.raises(SystemExit) as exc_info:
            from ai_guardian.cli import main

            main()

    assert exc_info.value.code == 0


def test_daemon_timeout_falls_back_to_block_policy(capsys):
    """A daemon timeout followed by a direct failure remains fail-closed."""
    hook_data = {
        "cursor_version": "0.50.0",
        "hook_event_name": "beforeShellExecution",
        "command": "pytest",
    }
    with (
        patch(
            "ai_guardian.cli._load_config_file",
            return_value=({"on_scan_error": "block"}, None),
        ),
        patch("ai_guardian.daemon.client.is_daemon_running", return_value=True),
        patch(
            "ai_guardian.daemon.client.send_hook_request",
            side_effect=TimeoutError("synthetic daemon timeout"),
        ),
        patch(
            "ai_guardian.cli.process_hook_data",
            side_effect=RuntimeError("synthetic direct failure"),
        ),
        patch("sys.argv", ["ai-guardian"]),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
    ):
        with pytest.raises(SystemExit) as exc_info:
            from ai_guardian.cli import main

            main()

    assert exc_info.value.code == 0
    assert json.loads(capsys.readouterr().out)["permission"] == "deny"


def test_malformed_daemon_response_follows_selected_policy():
    """Malformed protocol output is replaced by an allow or block response."""
    hook_data = {
        "_ide_type": "codex",
        "hook_event_name": "PostToolUse",
    }
    allow = ensure_hook_response(
        hook_data,
        {"output": "not-json", "exit_code": 0},
        action="allow",
    )
    block = ensure_hook_response(
        hook_data,
        {"output": "not-json", "exit_code": 0},
        action="block",
    )

    assert _json_output(allow) == {}
    assert _json_output(block)["decision"] == "block"
    assert block["_blocked"] is True


@pytest.mark.parametrize(
    ("protocol", "event", "expected_exit"),
    [
        ("kiro", "pre_tool_use", 2),
        ("kiro", "post_tool_use", 1),
        ("windsurf", "pre_run_command", 2),
    ],
)
def test_stream_protocol_failure_uses_nonzero_block_exit(
    protocol, event, expected_exit
):
    """Kiro and Windsurf retain their documented non-zero blocking exits."""
    result = build_failure_response(
        {"_ide_type": protocol, "hook_event_name": event}, "block"
    )

    assert result["exit_code"] == expected_exit
    assert result["output"] is None
    assert result["_blocked"] is True
    assert result["_failure_message"] == HOOK_FAILURE_MESSAGE


def test_unexpected_pipeline_failure_honors_policy_for_cursor():
    """The outer hook fallback no longer unconditionally fails open."""
    hook_data = {
        "cursor_version": "0.50.0",
        "hook_event_name": "preToolUse",
        "tool_name": "Bash",
    }
    with (
        patch(
            "ai_guardian.hook_processing._ensure_hook_events_imported",
            side_effect=RuntimeError("synthetic pipeline failure"),
        ),
        patch(
            "ai_guardian.hook_processing._get_on_scan_error_action",
            return_value="block",
        ),
    ):
        result = process_hook_data(hook_data)

    response = _json_output(result)
    assert response["permission"] == "deny"
    assert result["_blocked"] is True


@pytest.mark.parametrize(
    ("adapter", "event"),
    [
        (BaseAgentAdapter(), HookEvent.PRE_TOOL_USE),
        (CodexAdapter(), HookEvent.PRE_TOOL_USE),
        (CursorAdapter(), HookEvent.PRE_TOOL_USE),
    ],
)
def test_successful_security_blocks_remain_blocks(adapter, event):
    """Failure handling must not weaken a successfully evaluated detection."""
    result = adapter.format_response(
        has_secrets=True,
        error_message="synthetic security detection",
        hook_event=event,
        violation_type="secret_detected",
    )

    assert result["_blocked"] is True
    if isinstance(adapter, CursorAdapter):
        assert _json_output(result)["permission"] == "deny"
    else:
        assert "deny" in json.dumps(_json_output(result)).lower()
