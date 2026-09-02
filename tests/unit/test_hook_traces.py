"""Tests for unified hook session traces (#2190)."""

import json
import time
from unittest.mock import patch

from ai_guardian.constants import HookEvent
from ai_guardian.daemon.state import DaemonState
from ai_guardian.daemon.traces import HookTraceWriter
from ai_guardian.hook_adapters.base import NormalizedHookInput


def _normalized(event, **kwargs):
    return NormalizedHookInput(event=event, session_id="session-123", **kwargs)


def test_hook_trace_writer_uses_sdk_format_and_run_id(tmp_path):
    writer = HookTraceWriter(
        "session-123",
        adapter_name="Claude Code",
        project_name="my-project",
        trace_dir=str(tmp_path),
        run_id="pipeline-123",
    )
    writer.record(
        {"session_name": "fix-auth-bug", "model": "claude-sonnet-5"},
        _normalized(HookEvent.PROMPT, prompt_text="Fix the authentication bug"),
        {"exit_code": 0},
    )
    writer.record(
        {},
        _normalized(
            HookEvent.PRE_TOOL_USE,
            tool_name="Read",
            tool_input={"file_path": "src/auth.py"},
        ),
        {"exit_code": 0},
    )
    writer.finalize({"input_tokens": 10, "output_tokens": 5})

    trace_file = next(
        p for p in tmp_path.glob("*.json") if not p.name.endswith(".meta.json")
    )
    doc = json.loads(trace_file.read_text())
    assert doc["agent_name"] == "fix-auth-bug"
    assert doc["session_id"] == "session-123"
    assert doc["run_id"] == "pipeline-123"
    assert doc["model"] == "claude-sonnet-5"
    assert doc["source"] == "hook"
    assert doc["stop_reason"] == "session_end"
    assert doc["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert doc["trace"][0]["steps"][0]["type"] == "prompt"
    assert doc["trace"][0]["steps"][2]["type"] == "tool_call"
    assert doc["trace"][0]["steps"][3]["type"] == "scan"
    assert "ended_at" in doc


def test_hook_trace_records_blocked_scan(tmp_path):
    writer = HookTraceWriter(
        "session-123", project_name="my-project", trace_dir=str(tmp_path)
    )
    writer.record(
        {},
        _normalized(
            HookEvent.PRE_TOOL_USE,
            tool_name="Bash",
            tool_input={"command": "example"},
        ),
        {"_blocked": True, "_violation_type": "secret", "exit_code": 2},
    )

    trace_file = next(
        p for p in tmp_path.glob("*.json") if not p.name.endswith(".meta.json")
    )
    doc = json.loads(trace_file.read_text())
    scan = doc["trace"][0]["steps"][1]
    assert doc["trace"][0]["steps"][0]["input"] == "[redacted: secret]"
    assert scan["violations"] == [{"type": "secret", "action": "block"}]


def test_daemon_state_falls_back_to_environment_run_id(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_RUN_ID", "pipeline-from-env")
    sessions_file = tmp_path / "sessions.json"
    pause_file = tmp_path / "pause.json"
    state = DaemonState(sessions_file=sessions_file, pause_file=pause_file)

    with patch("ai_guardian.config.utils.get_sdk_trace_dir", return_value=tmp_path):
        state.record_hook_trace_event(
            {"cwd": str(tmp_path)},
            _normalized(HookEvent.SESSION_START, working_dir=str(tmp_path)),
            {"exit_code": 0},
        )
        state.record_hook_trace_event(
            {"prompt": "hello"},
            _normalized(HookEvent.PROMPT, prompt_text="hello"),
            {"exit_code": 0},
        )
        state.finalize_hook_trace("session-123")

    trace_files = [p for p in tmp_path.glob("*.json") if p != sessions_file]
    doc = json.loads(
        next(p for p in trace_files if not p.name.endswith(".meta.json")).read_text()
    )
    assert doc["run_id"] == "pipeline-from-env"
    assert doc["trace"][0]["steps"][0]["text"] == "hello"


def test_daemon_state_prefers_hook_run_id(tmp_path, monkeypatch):
    """Each hook session keeps its agent's run ID, not the daemon's value."""
    monkeypatch.setenv("AI_GUARDIAN_RUN_ID", "daemon-fallback")
    state = DaemonState(
        sessions_file=tmp_path / "sessions.json",
        pause_file=tmp_path / "pause.json",
    )

    with patch("ai_guardian.config.utils.get_sdk_trace_dir", return_value=tmp_path):
        state.record_hook_trace_event(
            {"cwd": str(tmp_path), "_ai_guardian_run_id": "agent-run"},
            _normalized(HookEvent.PROMPT, prompt_text="hello"),
            {"exit_code": 0},
        )
        state.finalize_hook_trace("session-123")

    trace_files = [
        path
        for path in tmp_path.glob("*.json")
        if path.name != "sessions.json" and not path.name.endswith(".meta.json")
    ]
    doc = json.loads(trace_files[0].read_text())
    assert doc["run_id"] == "agent-run"


def test_explicit_hook_run_id_overrides_forwarded_environment(tmp_path, monkeypatch):
    """A run ID supplied by the IDE event has the highest precedence."""
    monkeypatch.setenv("AI_GUARDIAN_RUN_ID", "daemon-run")
    state = DaemonState(
        sessions_file=tmp_path / "sessions.json",
        pause_file=tmp_path / "pause.json",
    )

    with patch("ai_guardian.config.utils.get_sdk_trace_dir", return_value=tmp_path):
        state.record_hook_trace_event(
            {
                "run_id": "explicit-run",
                "_ai_guardian_run_id": "forwarded-run",
            },
            _normalized(HookEvent.PROMPT, prompt_text="hello"),
            {"exit_code": 0},
        )
        state.finalize_hook_trace("session-123")

    trace_file = next(
        path
        for path in tmp_path.glob("*.json")
        if path.name != "sessions.json" and not path.name.endswith(".meta.json")
    )
    assert json.loads(trace_file.read_text())["run_id"] == "explicit-run"


def test_session_run_id_survives_daemon_restart(tmp_path, monkeypatch):
    """A persisted session binding outranks later process environments."""
    monkeypatch.delenv("AI_GUARDIAN_RUN_ID", raising=False)
    sessions_file = tmp_path / "sessions.json"
    pause_file = tmp_path / "pause.json"
    first_state = DaemonState(sessions_file=sessions_file, pause_file=pause_file)

    with patch("ai_guardian.config.utils.get_sdk_trace_dir", return_value=tmp_path):
        first_state.record_hook_trace_event(
            {"run_id": "persisted-run"},
            _normalized(HookEvent.PROMPT, prompt_text="before restart"),
            {"exit_code": 0},
        )
        first_state.flush_sessions()

        monkeypatch.setenv("AI_GUARDIAN_RUN_ID", "new-daemon-run")
        second_state = DaemonState(sessions_file=sessions_file, pause_file=pause_file)
        second_state.record_hook_trace_event(
            {"_ai_guardian_run_id": "new-hook-run"},
            _normalized(HookEvent.PROMPT, prompt_text="after restart"),
            {"exit_code": 0},
        )
        second_state.finalize_hook_trace("session-123")

    docs = [
        json.loads(path.read_text())
        for path in tmp_path.glob("*.json")
        if path.name not in {"sessions.json", "pause.json"}
        and not path.name.endswith(".meta.json")
    ]
    resumed_doc = next(
        doc
        for doc in docs
        if doc["trace"][0]["steps"][0].get("text") == "after restart"
    )
    assert resumed_doc["run_id"] == "persisted-run"


def test_hook_trace_recording_can_be_disabled(tmp_path):
    """Disabling tracing does not create a hook trace writer or file."""
    config_path = tmp_path / "ai-guardian.json"
    config_path.write_text(json.dumps({"tracing": {"enabled": False}}))
    state = DaemonState(
        config_path=config_path,
        sessions_file=tmp_path / "sessions.json",
        pause_file=tmp_path / "pause.json",
    )

    with patch("ai_guardian.config.utils.get_sdk_trace_dir", return_value=tmp_path):
        state.record_hook_trace_event(
            {},
            _normalized(HookEvent.PROMPT, prompt_text="hello"),
            {"exit_code": 0},
        )

    assert state._hook_trace_writers == {}
    assert not list(tmp_path.glob("*.meta.json"))


def test_daemon_periodically_finalizes_stale_hook_writer(tmp_path):
    state = DaemonState(
        sessions_file=tmp_path / "sessions.json",
        pause_file=tmp_path / "pause.json",
    )

    with patch("ai_guardian.config.utils.get_sdk_trace_dir", return_value=tmp_path):
        state.record_hook_trace_event(
            {},
            _normalized(HookEvent.PROMPT, prompt_text="hello"),
            {"exit_code": 0},
        )
        writer = state._hook_trace_writers["session-123"]
        writer._last_activity = time.monotonic() - 301
        expected_ended_at = writer.last_recorded_at.isoformat()

        assert state.cleanup_stale_hook_traces() == 1

    assert state._hook_trace_writers == {}
    trace_file = next(
        path
        for path in tmp_path.glob("*.json")
        if path.name != "sessions.json" and not path.name.endswith(".meta.json")
    )
    doc = json.loads(trace_file.read_text())
    assert doc["stop_reason"] == "timeout"
    assert doc["ended_at"] == expected_ended_at
    assert doc["usage"] == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


def test_normal_session_end_flow_remains_unchanged(tmp_path):
    writer = HookTraceWriter(
        "session-123", project_name="my-project", trace_dir=str(tmp_path)
    )
    writer.record(
        {},
        _normalized(HookEvent.PROMPT, prompt_text="hello"),
        {"exit_code": 0},
    )
    writer.finalize({"input_tokens": 7, "output_tokens": 3})

    trace_file = next(
        path for path in tmp_path.glob("*.json") if not path.name.endswith(".meta.json")
    )
    doc = json.loads(trace_file.read_text())
    assert doc["stop_reason"] == "session_end"
    assert doc["usage"] == {"input_tokens": 7, "output_tokens": 3}
