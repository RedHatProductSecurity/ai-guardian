"""UX contracts for session-scoped daemon pause and unsupported identities."""

import os
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

from ai_guardian.daemon.server import DaemonServer
from ai_guardian.daemon.working_dir import shorten_path
from ai_guardian.cli import main
from ai_guardian.setup.hooks import _OPENCODE_PLUGIN_V2_TS
from ai_guardian.tray.menu_builder import TrayMenuBuilder


@pytest.fixture
def isolated_server(tmp_path, monkeypatch):
    """Keep session-pause UX tests isolated from user configuration/state."""
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / "config"))
    return DaemonServer(idle_timeout=0, enable_rest_api=False)


def test_two_sessions_in_one_directory_can_be_paused_independently(
    isolated_server, tmp_path
):
    """
    USER EXPERIENCE: Shared project and title -> pause targets one hook session.

    Scenario:
    1. Two AI sessions report the same title with distinct IDs from one project.
    2. The user pauses the first session from the session list.
    3. Both sessions continue sending hooks from the same project directory.

    Expected User Experience:
    - Hooks from the selected session are allowed without running scanners.
    - The other session continues through normal security scanning.
    - Project-directory sharing does not cause the sessions to share pause state.
    - Duplicate compact titles get distinct short stable-key suffixes. The
      selected session key and project remain accessible in its submenu.
    - Renaming a paused session updates its label without resuming scanning.
    """
    server = isolated_server
    project = tmp_path / "shared-project"
    project.mkdir()

    def hook(session_id, title=None):
        data = {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "_daemon_cwd": str(project),
        }
        if title is not None:
            data["session_title"] = title
        return data

    with mock.patch(
        "ai_guardian.process_hook_data",
        side_effect=lambda *_args, **_kwargs: {
            "output": "scanned",
            "exit_code": 0,
        },
    ) as scan:
        server._handle_hook_request(hook("session-one", "Fix tray labels"))
        server._handle_hook_request(hook("session-two", "Fix tray labels"))
        sessions = {
            session["session_id"]: session
            for session in server.state.get_active_sessions()
        }
        first_key = sessions["session-one"]["session_key"]
        assert sessions["session-one"]["project_dir"] == os.path.realpath(project)
        assert sessions["session-two"]["project_dir"] == os.path.realpath(project)
        tray = SimpleNamespace(_supports_live_pause_countdown=lambda: False)
        menus = SimpleNamespace(
            Menu=lambda *items: SimpleNamespace(items=items),
            MenuItem=lambda label, action=None, **kwargs: SimpleNamespace(
                label=label, action=action, kwargs=kwargs
            ),
        )
        menus.Menu.SEPARATOR = object()
        with mock.patch("ai_guardian.tray.menu_builder.pystray", menus):
            items = TrayMenuBuilder(tray)._build_session_pause_items(
                lambda _: server.state.get_stats(),
                server.state.pause_session,
                server.state.resume_session,
            )
        first, second = items[2:4]
        assert first.label(None).startswith("● Claude Code: Fix tray labels [")
        assert first.label(None) != second.label(None)
        assert first.action.items[0].label(None) == f"Session key: {first_key}"
        assert (
            first.action.items[1].label(None)
            == f"Project: {shorten_path(str(project))}"
        )
        # Until resumed/session end, selected by stable key rather than title.
        first.action.items[7].action(None, None)
        assert server.state.is_session_paused(first_key)

        paused = server._handle_hook_request(hook("session-one", "Renamed session"))
        other = server._handle_hook_request(hook("session-two"))
        assert first.label(None) == "☾ Claude Code: Renamed session"
        assert second.label(None) == "● Claude Code: Fix tray labels"
        assert (
            server.state.get_active_sessions()[1]["session_title"] == "Fix tray labels"
        )

    assert paused["output"] == "{}"
    assert other["output"] == "scanned"
    assert scan.call_count == 3


def test_hook_without_stable_identity_is_not_presented_as_a_session(
    isolated_server, tmp_path
):
    """
    USER EXPERIENCE: Integration has no stable ID -> no false session isolation.

    Scenario:
    1. A hook-capable integration sends a request with only its project directory.
    2. The user checks session controls or supplies a guessed directory-derived key.

    Expected User Experience:
    - The daemon does not invent a session ID from the project directory.
    - Session-scoped pause is unavailable for that request; directory-wide and
      global pause remain the explicit alternatives.
    """
    server = isolated_server
    project = tmp_path / "no-session-id"
    project.mkdir()

    with mock.patch(
        "ai_guardian.process_hook_data",
        return_value={"output": "scanned", "exit_code": 0},
    ):
        server._handle_hook_request(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
                "_daemon_cwd": str(project),
            }
        )

    assert server.state.get_active_sessions() == []
    assert not server.state.pause_session(f"cwd:{project}")


def test_opencode_idle_keeps_pause_until_the_session_is_deleted(
    isolated_server, tmp_path
):
    """
    USER EXPERIENCE: OpenCode finishes a turn -> its session pause stays active.

    Manual verification:
    1. Pause an active OpenCode V2 session using its daemon-issued session key.
    2. Let the current turn finish, then send another prompt in the same session.
    3. Delete the session in OpenCode and inspect the daemon's active sessions.

    Expected User Experience:
    - session.idle forwards Stop, not SessionEnd; the next turn remains paused.
    - session.deleted forwards SessionEnd and removes that session and its pause.
    - Plugin unloading is not treated as deletion of a persistent session.
    """
    assert (
        "record.type === 'session.deleted' ? 'SessionEnd' : 'Stop'"
        in _OPENCODE_PLUGIN_V2_TS
    )
    assert "const sessionID = textValue(data.sessionID)" in _OPENCODE_PLUGIN_V2_TS
    server = isolated_server
    identity = {
        "hook_source": "opencode",
        "opencode_version": "2.0.22",
        "session_id": "opencode-session",
        "cwd": str(tmp_path),
    }
    with mock.patch(
        "ai_guardian.process_hook_data",
        return_value={"output": "scanned", "exit_code": 0},
    ) as scan:
        server._handle_hook_request(
            {**identity, "hook_event_name": "message.submit", "prompt": "hello"}
        )
        session_key = server.state.get_active_sessions()[0]["session_key"]
        assert server.state.pause_session(session_key)

        stopped = server._handle_hook_request({**identity, "hook_event_name": "Stop"})
        next_turn = server._handle_hook_request(
            {**identity, "hook_event_name": "message.submit", "prompt": "hello again"}
        )

        assert stopped["output"] == "{}"
        # Paused prompts may still receive fixed security instructions, but
        # content scanners must not run on this turn.
        assert next_turn["exit_code"] == 0
        scan.assert_called_once()
        assert server.state.is_session_paused(session_key)
        assert server.state.get_active_sessions()[0]["session_key"] == session_key

        server._handle_hook_request({**identity, "hook_event_name": "SessionEnd"})

    assert server.state.get_active_sessions() == []
    assert not server.state.is_session_paused(session_key)


def test_session_pause_cli_targets_the_status_session_key(capsys):
    """
    USER EXPERIENCE: CLI session pause -> only the selected stable-ID session.

    Scenario:
    1. The user copies a session key from `ai-guardian daemon status`.
    2. The user runs `ai-guardian daemon pause --session KEY --minutes 15`.

    Expected User Experience:
    - The CLI explicitly reports the selected hook session and duration.
    - The command controls the existing daemon without auto-starting it.
    """
    session_key = "ClaudeCodeAdapter:session-1"
    with (
        mock.patch.object(
            sys,
            "argv",
            [
                "ai-guardian",
                "daemon",
                "pause",
                "--session",
                session_key,
                "--minutes",
                "15",
            ],
        ),
        mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True),
        mock.patch(
            "ai_guardian.daemon.client.send_pause_session",
            return_value={"status": "session_paused"},
        ) as send_pause,
        mock.patch("ai_guardian.cli_handlers._get_client_timeout", return_value=2.0),
        mock.patch("ai_guardian.cli._ensure_daemon_started") as auto_start,
    ):
        result = main()

    assert result == 0
    send_pause.assert_called_once_with(session_key, 15, timeout=2.0)
    auto_start.assert_not_called()
    assert capsys.readouterr().out == (
        "ai-guardian daemon: scanning paused for 15 minutes for hook session "
        f"{session_key}\n"
    )


def test_session_resume_cli_targets_the_status_session_key(capsys):
    """
    USER EXPERIENCE: CLI session resume -> resume only the selected session.

    Scenario:
    1. The user copies a session key from `ai-guardian daemon status`.
    2. The user runs `ai-guardian daemon resume --session KEY`.

    Expected User Experience:
    - The CLI explicitly reports which hook session resumed.
    - Other sessions remain independently controlled.
    """
    session_key = "ClaudeCodeAdapter:session-1"
    with (
        mock.patch.object(
            sys, "argv", ["ai-guardian", "daemon", "resume", "--session", session_key]
        ),
        mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True),
        mock.patch(
            "ai_guardian.daemon.client.send_resume_session",
            return_value={"status": "session_resumed"},
        ) as send_resume,
        mock.patch("ai_guardian.cli_handlers._get_client_timeout", return_value=2.0),
    ):
        result = main()

    assert result == 0
    send_resume.assert_called_once_with(session_key, timeout=2.0)
    assert capsys.readouterr().out == (
        "ai-guardian daemon: scanning resumed for hook session " f"{session_key}\n"
    )
