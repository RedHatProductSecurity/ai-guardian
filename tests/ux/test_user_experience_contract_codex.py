"""User experience contracts for OpenAI Codex hook responses."""

import json
from io import StringIO
from unittest.mock import patch

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
