"""UX contracts for hook startup and process failures (#2434)."""

import json
from io import StringIO
from unittest.mock import patch

from ai_guardian_hook_runtime import main as runtime_main


def test_startup_failure_fail_open_is_a_cursor_noop(capsys):
    """
    USER EXPERIENCE: Temporary hook import failure in development -> allow.

    Expected User Experience:
    - Cursor receives a valid allow response on stdout.
    - The operation is not blocked solely because AI Guardian could not start.
    - Startup exception details are not copied into the host protocol.
    """
    hook_data = {
        "cursor_version": "0.50.0",
        "hook_event_name": "beforeSubmitPrompt",
    }
    real_import = __import__

    def fail_cli_import(name, *args, **kwargs):
        if name == "ai_guardian.cli":
            raise ImportError("temporary source error")
        return real_import(name, *args, **kwargs)

    with (
        patch.dict(
            "os.environ", {"AI_GUARDIAN_CONFIG_INLINE": '{"on_scan_error":"allow"}'}
        ),
        patch("sys.argv", ["ai-guardian"]),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
        patch("builtins.__import__", side_effect=fail_cli_import),
    ):
        exit_code = runtime_main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {"continue": True}
    assert "temporary source error" not in captured.out


def test_startup_failure_fail_closed_is_a_cursor_deny(capsys):
    """
    USER EXPERIENCE: Strict hook process policy -> Cursor denial.

    Expected User Experience:
    - Cursor receives valid JSON with permission=deny.
    - The host operation is blocked without exposing a traceback or source text.
    """
    hook_data = {
        "cursor_version": "0.50.0",
        "hook_event_name": "beforeShellExecution",
    }
    real_import = __import__

    def fail_cli_import(name, *args, **kwargs):
        if name == "ai_guardian.cli":
            raise ImportError("temporary source error")
        return real_import(name, *args, **kwargs)

    with (
        patch.dict(
            "os.environ", {"AI_GUARDIAN_CONFIG_INLINE": '{"on_scan_error":"block"}'}
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
    assert "temporary source error" not in captured.out
