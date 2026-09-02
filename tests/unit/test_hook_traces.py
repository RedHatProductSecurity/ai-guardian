"""Tests for unified hook session traces (#2190)."""

import json
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


def test_daemon_state_reads_run_id_when_session_starts(tmp_path, monkeypatch):
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
