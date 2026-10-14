"""UX contracts for session-scoped daemon pause and unsupported identities."""

import io
import os
import sys
import threading
import time
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


@pytest.fixture
def pause_clock(monkeypatch):
    clock = mock.Mock(return_value=1000.0)
    monkeypatch.setattr(
        "ai_guardian.daemon.state.time",
        SimpleNamespace(monotonic=clock, time=time.time),
    )
    return clock


@pytest.fixture
def active_cli_sessions(isolated_server, tmp_path, pause_clock):
    """Two stable-ID sessions share a project; a third uses another directory."""
    for session_id, directory in (
        ("first", "shared-project"),
        ("second", "shared-project"),
        ("other", "other-project"),
    ):
        project = tmp_path / directory
        project.mkdir(exist_ok=True)
        isolated_server.state.record_session_activity(
            f"ClaudeCodeAdapter:{session_id}",
            session_id,
            "Claude Code",
            str(project),
            session_title="Shared display name",
        )
    return {
        session["session_id"]: session
        for session in isolated_server.state.get_active_sessions()
    }


@pytest.fixture
def run_scoped_cli(isolated_server, cli_connect):
    """Exercise real CLI/client/protocol/state code over in-memory mock sockets."""

    def connect(timeout):
        response = io.BytesIO()
        client = mock.MagicMock()
        client.gettimeout.return_value = None
        client.recv.side_effect = response.read

        def send(request):
            daemon_client = mock.MagicMock()
            daemon_client.gettimeout.return_value = None
            daemon_client.recv.side_effect = io.BytesIO(request).read
            daemon_client.sendall.side_effect = response.write
            isolated_server._handle_client(daemon_client)
            daemon_client.close.assert_called_once_with()
            response.seek(0)

        client.sendall.side_effect = send
        return client

    cli_connect.side_effect = connect

    def run(arguments):
        cli_connect.reset_mock()
        with (
            mock.patch.object(sys, "argv", ["ai-guardian", *arguments]),
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=True
            ),
            mock.patch(
                "ai_guardian.cli_handlers._load_config_file", return_value=({}, None)
            ),
            mock.patch("ai_guardian.cli._ensure_daemon_started") as auto_start,
        ):
            result = main()
        cli_connect.assert_called_once_with(timeout=2.0)
        auto_start.assert_not_called()
        return result

    return run


def test_scoped_cli_transport_ignores_background_connections(
    active_cli_sessions, run_scoped_cli, monkeypatch
):
    """USER EXPERIENCE: Unrelated tray traffic cannot enter the CLI test transport."""
    from ai_guardian.daemon import client

    original_main = main
    background_connections = []

    def main_with_background_connection():
        def connect_in_background():
            connection = client._connect(timeout=2.0)
            background_connections.append(connection)
            if connection is not None:
                connection.close()

        worker = threading.Thread(target=connect_in_background)
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive()
        return original_main()

    monkeypatch.setattr(sys.modules[__name__], "main", main_with_background_connection)
    key = active_cli_sessions["first"]["session_key"]
    assert run_scoped_cli(["pause", "--session", key]) == 0
    assert background_connections == [None]


def test_pause_clock_does_not_replace_the_process_clock(pause_clock):
    """A deterministic session timer must not alter unrelated tray thread deadlines."""
    assert time.monotonic is not pause_clock


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_two_sessions_in_one_directory_can_be_paused_independently(
    isolated_server, tmp_path, monkeypatch, platform
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
    - Windows renders literal ampersands, not keyboard mnemonic markers; other
      platforms retain their literal menu strings. Stored titles remain unescaped.

    Manual verification:
    1. On Windows, name two sessions "Fix A&B" and "Fix AB".
    2. Open Sessions... and confirm the ampersand is visible and labels differ.
    3. Pause/resume the first session and confirm the second is unaffected.
    """
    monkeypatch.setattr(
        "ai_guardian.tray.menu_builder.sys", SimpleNamespace(platform=platform)
    )
    title = "Fix A&B"
    display_title = "Fix A&&B" if platform == "win32" else title
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
        server._handle_hook_request(hook("session-one", title))
        server._handle_hook_request(hook("session-two", title))
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
        assert first.label(None).startswith(f"● Claude Code: {display_title} [")
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
        assert second.label(None) == f"● Claude Code: {display_title}"
        assert server.state.get_active_sessions()[1]["session_title"] == title

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


@pytest.mark.parametrize("nested", [False, True])
def test_session_pause_cli_targets_the_status_session_key(nested, capsys):
    """
    USER EXPERIENCE: CLI session pause -> only the selected stable-ID session.

    Scenario:
    1. The user copies a session key from `ai-guardian daemon status`.
    2. The user runs `ai-guardian pause 15 --session KEY` (or the nested form).

    Expected User Experience:
    - The CLI explicitly reports the selected hook session and duration.
    - The command controls the existing daemon without auto-starting it.
    """
    session_key = "ClaudeCodeAdapter:session-1"
    with (
        mock.patch.object(
            sys,
            "argv",
            (
                [
                    "ai-guardian",
                    "daemon",
                    "pause",
                    "--session",
                    session_key,
                    "--minutes",
                    "15",
                ]
                if nested
                else ["ai-guardian", "pause", "15", "--session", session_key]
            ),
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


@pytest.mark.parametrize("nested", [False, True])
def test_session_resume_cli_targets_the_status_session_key(nested, capsys):
    """
    USER EXPERIENCE: CLI session resume -> resume only the selected session.

    Scenario:
    1. The user copies a session key from `ai-guardian daemon status`.
    2. The user runs `ai-guardian resume --session KEY` (or the nested form).

    Expected User Experience:
    - The CLI explicitly reports which hook session resumed.
    - Other sessions remain independently controlled.
    """
    session_key = "ClaudeCodeAdapter:session-1"
    with (
        mock.patch.object(
            sys,
            "argv",
            (
                ["ai-guardian", "daemon", "resume", "--session", session_key]
                if nested
                else ["ai-guardian", "resume", "--session", session_key]
            ),
        ),
        mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True),
        mock.patch(
            "ai_guardian.daemon.client.send_resume_session",
            return_value={"status": "session_resumed"},
        ) as send_resume,
        mock.patch("ai_guardian.cli_handlers._get_client_timeout", return_value=2.0),
        mock.patch("ai_guardian.cli._ensure_daemon_started") as auto_start,
    ):
        result = main()

    assert result == 0
    auto_start.assert_not_called()
    send_resume.assert_called_once_with(session_key, timeout=2.0)
    assert capsys.readouterr().out == (
        "ai-guardian daemon: scanning resumed for hook session " f"{session_key}\n"
    )


@pytest.mark.parametrize("minutes", [None, 0, 15, 1440])
def test_top_level_session_pause_is_independent_of_shared_directory_and_title(
    isolated_server, active_cli_sessions, run_scoped_cli, minutes, capsys
):
    """
    USER EXPERIENCE: Copy a stable key from status -> only that session pauses.

    Manual verification:
    1. Open two stable-ID sessions in one project, even with identical titles.
    2. Copy the first session_key from ``ai-guardian daemon status``.
    3. Run ``ai-guardian pause 15 --session KEY``, then resume that same key.
    4. Confirm the second session continues scanning and has independent controls.
    """
    state = isolated_server.state
    first = active_cli_sessions["first"]
    second = active_cli_sessions["second"]
    duration = [] if minutes is None else [str(minutes)]
    assert run_scoped_cli(["pause", *duration, "--session", first["session_key"]]) == 0
    assert state.is_session_paused(first["session_key"])
    assert not state.is_session_paused(second["session_key"])
    assert not state.is_dir_paused(first["project_dir"])
    assert not state.paused
    lifetime = f" for {minutes} minutes" if minutes else " until resume or session end"
    assert capsys.readouterr().out == (
        f"ai-guardian daemon: scanning paused{lifetime} for hook session {first['session_key']}\n"
    )

    assert run_scoped_cli(["pause", "--session", second["session_key"]]) == 0
    assert run_scoped_cli(["resume", "--session", first["session_key"]]) == 0
    assert not state.is_session_paused(first["session_key"])
    assert state.is_session_paused(second["session_key"])


@pytest.mark.parametrize("minutes", [None, 0, 15])
def test_top_level_directory_pause_is_normalized_bulk_control(
    isolated_server,
    active_cli_sessions,
    run_scoped_cli,
    tmp_path,
    monkeypatch,
    minutes,
    capsys,
):
    """
    USER EXPERIENCE: --dir pauses all sessions there, not another project.

    Resume clears only that directory pause; independent session and other
    directory pauses remain. Relative paths use the existing realpath handling.
    """
    state = isolated_server.state
    first = active_cli_sessions["first"]
    second = active_cli_sessions["second"]
    other = active_cli_sessions["other"]
    state.pause_dir(other["project_dir"])
    state.pause_session(second["session_key"])
    monkeypatch.chdir(tmp_path)
    relative = os.path.join("shared-project", "..", "shared-project")
    duration = [] if minutes is None else [str(minutes)]
    assert run_scoped_cli(["pause", "--dir", relative, *duration]) == 0
    assert state.is_dir_paused(first["project_dir"])
    assert state.is_dir_paused(second["project_dir"])
    assert state.is_dir_paused(other["project_dir"])
    assert not state.is_session_paused(first["session_key"])
    assert state.is_session_paused(second["session_key"])
    assert not state.paused
    lifetime = f" for {minutes} minutes" if minutes else " indefinitely"
    assert capsys.readouterr().out == (
        f"ai-guardian daemon: scanning paused{lifetime} for all sessions in {first['project_dir']}\n"
    )

    with mock.patch(
        "ai_guardian.process_hook_data",
        return_value={"output": "scanned", "exit_code": 0},
    ) as scan:
        for session_id in ("first", "second"):
            result = isolated_server._handle_hook_request(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": session_id,
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls"},
                    "_daemon_cwd": first["project_dir"],
                }
            )
            assert result["output"] == "{}"
        scan.assert_not_called()

    assert run_scoped_cli(["resume", "--dir", relative]) == 0
    assert not state.is_dir_paused(first["project_dir"])
    assert state.is_dir_paused(other["project_dir"])
    assert state.is_session_paused(second["session_key"])
    assert capsys.readouterr().out == (
        f"ai-guardian daemon: scanning resumed for all sessions in {first['project_dir']}\n"
    )


@pytest.mark.parametrize("scope", ["global", "directory", "session"])
def test_top_level_resume_removes_only_the_selected_pause_layer(
    isolated_server, active_cli_sessions, run_scoped_cli, scope
):
    """USER EXPERIENCE: Resume one layer -> broader/independent pauses still apply."""
    state = isolated_server.state
    first = active_cli_sessions["first"]
    state.pause()
    state.pause_dir(first["project_dir"])
    state.pause_session(first["session_key"])
    selector = {
        "global": [],
        "directory": ["--dir", first["project_dir"]],
        "session": ["--session", first["session_key"]],
    }[scope]
    assert run_scoped_cli(["resume", *selector]) == 0
    assert state.paused == (scope != "global")
    assert state.is_dir_paused(first["project_dir"]) == (scope != "directory")
    assert state.is_session_paused(first["session_key"]) == (scope != "session")


@pytest.mark.parametrize("scope", ["--dir", "--session"])
def test_top_level_scoped_timer_expires_without_changing_other_pauses(
    isolated_server, active_cli_sessions, run_scoped_cli, pause_clock, scope
):
    """USER EXPERIENCE: Timed pause -> automatic expiry of only the selected scope."""
    state = isolated_server.state
    first = active_cli_sessions["first"]
    other = active_cli_sessions["other"]
    state.pause_session(other["session_key"])
    target = first["project_dir"] if scope == "--dir" else first["session_key"]
    is_paused = state.is_dir_paused if scope == "--dir" else state.is_session_paused
    assert run_scoped_cli(["pause", "1", scope, target]) == 0
    pause_clock.return_value += 59
    assert is_paused(target)
    pause_clock.return_value += 1
    assert not is_paused(target)
    assert state.is_session_paused(other["session_key"])
    assert not state.paused


@pytest.mark.parametrize("lifecycle", ["session-end", "inactivity", "restart"])
def test_top_level_indefinite_session_pause_keeps_existing_lifecycle(
    isolated_server, active_cli_sessions, run_scoped_cli, pause_clock, lifecycle
):
    """USER EXPERIENCE: Omitted duration -> pause until resume or session lifecycle ends."""
    state = isolated_server.state
    key = active_cli_sessions["first"]["session_key"]
    assert run_scoped_cli(["pause", "--session", key]) == 0
    pause_clock.return_value += 60
    assert state.is_session_paused(key)
    if lifecycle == "session-end":
        state.end_session(key)
    elif lifecycle == "inactivity":
        pause_clock.return_value += 24 * 60 * 60
    else:
        state = DaemonServer(idle_timeout=0, enable_rest_api=False).state
    assert not state.is_session_paused(key)


@pytest.mark.parametrize("command", ["pause", "resume"])
@pytest.mark.parametrize(
    "identity", ["unknown", "ended", "expired", "title", "directory", "raw-id"]
)
def test_top_level_session_request_never_infers_or_falls_back(
    isolated_server,
    active_cli_sessions,
    run_scoped_cli,
    pause_clock,
    command,
    identity,
    capsys,
):
    """
    USER EXPERIENCE: Invalid/non-active identity -> non-zero error, no broader control.

    A display name, raw ID, directory, or expired session cannot substitute for
    the active stable session_key listed by daemon status.
    """
    state = isolated_server.state
    first = active_cli_sessions["first"]
    key = first["session_key"]
    if identity == "unknown":
        key = "ClaudeCodeAdapter:not-active"
    elif identity == "ended":
        state.end_session(key)
    elif identity == "expired":
        pause_clock.return_value += 24 * 60 * 60 + 1
    elif identity == "title":
        key = first["session_title"]
    elif identity == "directory":
        key = first["project_dir"]
    elif identity == "raw-id":
        key = first["session_id"]
    assert run_scoped_cli([command, "--session", key]) == 1
    assert not state.paused
    assert state.get_paused_dirs() == {}
    assert not any(session["paused"] for session in state.get_active_sessions())
    output = capsys.readouterr()
    assert output.out == ""
    assert f"Could not {command} that session." in output.err
    assert "currently active session with a stable identity" in output.err
