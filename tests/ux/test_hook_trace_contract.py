"""User experience contract for unified IDE hook traces (#2190)."""

import json
from unittest.mock import patch

from ai_guardian.constants import HookEvent
from ai_guardian.daemon.state import DaemonState
from ai_guardian.daemon.traces import HookTraceWriter
from ai_guardian.hook_adapters.base import NormalizedHookInput


def test_ide_session_appears_as_sdk_compatible_trace(tmp_path):
    """
    USER EXPERIENCE: An IDE session ends -> it appears in the shared trace viewer.

    Scenario:
    1. The IDE submits a prompt under a named session.
    2. AI Guardian records the hook scan alongside the prompt.
    3. The IDE sends SessionEnd.

    Expected User Experience:
    The trace uses the GuardedAgent schema, is labelled with the IDE session name,
    and can be grouped with SDK traces by AI_GUARDIAN_RUN_ID.
    """
    writer = HookTraceWriter(
        "ide-session",
        adapter_name="Claude Code",
        project_name="my-project",
        trace_dir=str(tmp_path),
        run_id="release-pipeline",
    )
    normalized = NormalizedHookInput(
        event=HookEvent.PROMPT,
        session_id="ide-session",
        prompt_text="Review the change",
    )
    writer.record({"session_name": "review-change"}, normalized, {"exit_code": 0})
    writer.finalize()

    trace_file = next(
        p for p in tmp_path.glob("*.json") if not p.name.endswith(".meta.json")
    )
    doc = json.loads(trace_file.read_text())
    assert doc["agent_name"] == "review-change"
    assert doc["run_id"] == "release-pipeline"
    assert doc["trace"] == [
        {
            "turn": 1,
            "steps": [
                {"type": "prompt", "text": "Review the change", "step": 0},
                {
                    "type": "scan",
                    "scanned": "prompt",
                    "violations": [],
                    "step": 1,
                },
            ],
        }
    ]


def test_hook_process_run_id_correlates_when_daemon_environment_differs(
    tmp_path, monkeypatch
):
    """
    USER EXPERIENCE: IDE and SDK share a run ID -> one correlated Sessions run.

    Scenario:
    1. An SDK pipeline uses RunContext(run_id="release-pipeline").
    2. A non-SDK agent supplies the matching run_id in its hook event.
    3. The already-running daemon has a different environment.
    4. The hook forwards its run ID with the session event.

    Expected User Experience:
    The IDE trace retains "release-pipeline" and appears with the SDK traces on
    the Sessions page. Restarting or pre-starting the daemon does not determine
    the IDE session's correlation ID.
    """
    monkeypatch.setenv("AI_GUARDIAN_RUN_ID", "daemon-run")
    state = DaemonState(
        sessions_file=tmp_path / "sessions.json",
        pause_file=tmp_path / "pause.json",
    )
    normalized = NormalizedHookInput(
        event=HookEvent.PROMPT,
        session_id="ide-session",
        prompt_text="Review the change",
    )

    with patch("ai_guardian.config.utils.get_sdk_trace_dir", return_value=tmp_path):
        state.record_hook_trace_event(
            {"run_id": "release-pipeline"},
            normalized,
            {"exit_code": 0},
        )
        state.finalize_hook_trace("ide-session")

    trace_file = next(
        path
        for path in tmp_path.glob("*.json")
        if path.name != "sessions.json" and not path.name.endswith(".meta.json")
    )
    assert json.loads(trace_file.read_text())["run_id"] == "release-pipeline"


def test_unfinalized_trace_is_presented_as_interrupted():
    """
    USER EXPERIENCE: Recording misses SessionEnd -> user sees Interrupted.

    Scenario:
    1. A trace remains in progress after a daemon restart or process exit.
    2. AI Guardian records the backward-compatible "crashed" stop reason.
    3. The user opens Sessions.

    Expected User Experience:
    The status reads "INTERRUPTED", not "CRASHED", because the agent itself
    may be healthy and only the recording was not finalized.
    """
    from ai_guardian.tui.traces import _format_trace_label

    label = _format_trace_label(
        {"agent_name": "review-agent", "stop_reason": "crashed"}
    )
    assert "INTERRUPTED" in label
    assert "CRASHED" not in label
