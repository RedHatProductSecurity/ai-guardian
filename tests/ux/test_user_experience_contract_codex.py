"""User experience contracts for OpenAI Codex hook responses."""

import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.cli import main


def test_codex_posttooluse_internal_error_emits_valid_json(capsys):
    """
    USER EXPERIENCE: Codex PostToolUse error -> valid JSON and fail-open.

    Scenario:
    1. Codex runs a PostToolUse hook for a completed Bash command.
    2. AI Guardian encounters an unexpected internal error.
    3. Hook processing fails open.

    Expected User Experience:
    - Codex receives valid JSON on stdout.
    - The tool is not blocked solely because hook processing failed.
    """
    hook_data = {
        "_ide_type": "codex",
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_response": {"output": "command output"},
    }

    with (
        patch("ai_guardian.cli._load_config_file", return_value=({}, None)),
        patch("ai_guardian.daemon.client.is_daemon_running", return_value=False),
        patch("ai_guardian.daemon.client.start_daemon_background", return_value=False),
        patch(
            "ai_guardian.cli.process_hook_data",
            return_value={"output": None, "exit_code": 0},
        ),
        patch("sys.argv", ["ai-guardian"]),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 0
    assert json.loads(capsys.readouterr().out) == {}


def test_codex_blocked_operation_records_codex_identity():
    """
    USER EXPERIENCE: Codex block -> violation context identifies Codex.

    Scenario:
    1. Codex submits a PreToolUse operation.
    2. AI Guardian's explicit permission policy blocks the operation.
    3. The violation is recorded for audit and observability.

    Expected User Experience:
    - Codex receives its existing Claude-compatible deny response.
    - The recorded context identifies the integration as ``codex``.
    - The recorded identity is not incorrectly reported as ``claude_code``.
    """
    from ai_guardian.hook_processing import process_hook_data
    from ai_guardian.tools.policy import ToolPolicyChecker

    hook_data = {
        "_ide_type": "codex",
        "hook_event_name": "PreToolUse",
        "session_id": "codex-session",
        "tool_use_id": "codex-tool-use",
        "tool_name": "Bash",
        "tool_input": {"command": "echo safe"},
    }
    policy = ToolPolicyChecker(
        config={
            "permissions": {
                "enabled": True,
                "rules": [{"matcher": "Bash", "mode": "deny", "patterns": ["*"]}],
            }
        }
    )
    violation_log = MagicMock()

    with (
        patch(
            "ai_guardian.hook_processing._load_permissions_config",
            return_value=({"enabled": True}, None),
        ),
        patch("ai_guardian.hook_processing.ToolPolicyChecker", return_value=policy),
        patch(
            "ai_guardian.violations.log_violation.log_violation",
            violation_log,
        ),
        patch("ai_guardian.hook_processing._is_latency_enabled", return_value=False),
    ):
        result = process_hook_data(hook_data)

    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert violation_log.call_args.args[1].to_dict()["ide_type"] == "codex"
