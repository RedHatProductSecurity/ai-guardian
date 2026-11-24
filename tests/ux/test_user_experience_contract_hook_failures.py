"""UX contracts for hook startup and process failures (#2434)."""

import json
from io import StringIO
from unittest.mock import Mock, patch

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


def test_remote_daemon_failure_uses_direct_hook_without_local_start(capsys, caplog):
    """
    USER EXPERIENCE: Remote daemon outage -> direct processing, no local launch.

    Expected User Experience:
    - A configured remote endpoint is never replaced with a local daemon.
    - The hook still returns the direct processing result.
    - Logs identify the remote outage without exposing endpoint or hook content.
    """
    from ai_guardian import cli

    hook_data = {"_ide_type": "codex", "hook_event_name": "PostToolUse"}
    direct = {"output": "{}", "exit_code": 0}
    start = Mock(side_effect=AssertionError("remote hooks must not start locally"))
    with (
        patch.dict("os.environ", {"AI_GUARDIAN_DAEMON_URL": "https://daemon.test"}),
        patch("ai_guardian.cli._load_config_file", return_value=({}, None)),
        patch("ai_guardian.daemon.client.is_daemon_running", return_value=False),
        patch("ai_guardian.daemon.client.start_daemon_background", start),
        patch("ai_guardian.cli.process_hook_data", return_value=direct),
        patch("sys.argv", ["ai-guardian"]),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
    ):
        with patch.object(cli, "_is_stop_requested", return_value=False):
            try:
                cli.main()
            except SystemExit as exc_info:
                assert exc_info.code == 0

    assert json.loads(capsys.readouterr().out) == {}
    start.assert_not_called()
    diagnostic = [
        record.hook_daemon_diagnostic
        for record in caplog.records
        if hasattr(record, "hook_daemon_diagnostic")
    ][-1]
    assert diagnostic == {"reason": "remote_unavailable", "remote": True}


def test_malformed_daemon_response_retries_direct_processing(capsys, caplog):
    """USER EXPERIENCE: Invalid daemon response -> direct result and diagnosis."""
    from ai_guardian import cli

    hook_data = {"_ide_type": "codex", "hook_event_name": "PostToolUse"}
    direct = {"output": "{}", "exit_code": 0}
    with (
        patch("ai_guardian.cli._load_config_file", return_value=({}, None)),
        patch("ai_guardian.daemon.client.is_daemon_running", return_value=True),
        patch(
            "ai_guardian.daemon.client.send_hook_request",
            return_value={"output": "not-json", "exit_code": 0},
        ),
        patch("ai_guardian.cli.process_hook_data", return_value=direct) as process,
        patch("ai_guardian.cli._is_stop_requested", return_value=False),
        patch("sys.argv", ["ai-guardian"]),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
    ):
        try:
            cli.main()
        except SystemExit as exc_info:
            assert exc_info.code == 0

    assert json.loads(capsys.readouterr().out) == {}
    process.assert_called_once_with(hook_data)
    diagnostic = [
        record.hook_daemon_diagnostic
        for record in caplog.records
        if hasattr(record, "hook_daemon_diagnostic")
    ][-1]
    assert diagnostic == {"reason": "malformed_response", "remote": False}
