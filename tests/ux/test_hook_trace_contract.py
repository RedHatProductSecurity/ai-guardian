"""User experience contract for unified IDE hook traces (#2190)."""

import json

from ai_guardian.constants import HookEvent
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
