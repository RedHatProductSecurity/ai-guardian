"""Unit coverage for Pi extension, transcript, and session support."""

import json
from pathlib import Path
from unittest import mock

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters import detect_adapter, get_adapter_by_ide_type
from ai_guardian.hook_adapters.pi import PiAdapter
from ai_guardian.response_format import IDEType
from ai_guardian.scanners.transcript.pi import (
    PiTranscriptAdapter,
    _extract_text_from_pi_entry,
)
from ai_guardian.sessions.adapters import PiSessionAdapter
from ai_guardian.setup.hooks import IDESetup, _PI_EXTENSION_TS


def test_pi_detection_and_identity():
    adapter = detect_adapter({"pi_version": "0.1.0"})

    assert isinstance(adapter, PiAdapter)
    assert adapter.name == "Pi"
    assert adapter.agent_type == "pi"
    assert adapter.ide_type is IDEType.PI
    assert isinstance(get_adapter_by_ide_type(IDEType.PI), PiAdapter)


def test_pi_detection_accepts_hook_source_and_environment(monkeypatch):
    assert isinstance(detect_adapter({"hook_source": "pi"}), PiAdapter)

    monkeypatch.setenv("AI_GUARDIAN_IDE_TYPE", "pi")
    assert isinstance(detect_adapter({}), PiAdapter)


def test_pi_normalizes_shared_pascal_case_events():
    adapter = PiAdapter()
    prompt = adapter.normalize_input(
        {
            "hook_event_name": "UserPromptSubmit",
            "pi_version": "0.1.0",
            "prompt": "inspect this project",
            "cwd": "/tmp/project",
            "session_id": "session-1",
        }
    )
    pre_tool = adapter.normalize_input(
        {
            "hook_event_name": "PreToolUse",
            "pi_version": "0.1.0",
            "tool_name": "Bash",
            "tool_use": {"input": {"command": "printf hello"}},
            "tool_use_id": "tool-1",
        }
    )
    post_tool = adapter.normalize_input(
        {
            "hook_event_name": "PostToolUse",
            "pi_version": "0.1.0",
            "tool_name": "Bash",
            "tool_response": {"output": "hello"},
        }
    )

    assert prompt.event is HookEvent.PROMPT
    assert prompt.prompt_text == "inspect this project"
    assert prompt.working_dir == "/tmp/project"
    assert pre_tool.event is HookEvent.PRE_TOOL_USE
    assert pre_tool.tool_input == {"command": "printf hello"}
    assert pre_tool.tool_use_id == "tool-1"
    assert post_tool.event is HookEvent.POST_TOOL_USE
    assert post_tool.tool_response == {"output": "hello"}


def test_pi_uses_shared_response_contract():
    adapter = PiAdapter()
    blocked = adapter.format_response(
        has_secrets=True,
        error_message="Secret detected",
        hook_event=HookEvent.PRE_TOOL_USE,
    )
    redacted = adapter.format_response(
        has_secrets=False,
        hook_event=HookEvent.POST_TOOL_USE,
        modified_output="[REDACTED]",
        tool_name="Bash",
    )

    blocked_body = json.loads(blocked["output"])
    redacted_body = json.loads(redacted["output"])
    assert blocked["_blocked"] is True
    assert blocked_body["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert redacted_body["hookSpecificOutput"]["updatedToolOutput"] == {
        "stdout": "[REDACTED]",
        "stderr": "",
        "interrupted": False,
    }


def test_pi_setup_writes_extension_to_relocated_agent_home(tmp_path, monkeypatch):
    agent_home = tmp_path / "pi-agent"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_home))
    setup = IDESetup()

    with mock.patch.object(
        setup, "verify_gitleaks_installed", return_value=(True, "ok")
    ):
        success, message = setup.setup_ide_hooks("pi", force=True)

    extension = agent_home / "extensions" / "ai-guardian.ts"
    assert success is True
    assert extension.is_file()
    assert "Pi" in message
    verification = setup.verify_hooks_for_ide("pi")
    assert verification["healthy"] is True, verification
    content = extension.read_text(encoding="utf-8")
    assert 'AI_GUARDIAN_IDE_TYPE: "pi"' in content
    assert 'pi.on("tool_call"' in content
    assert 'pi.on("tool_result"' in content


def test_pi_project_setup_remains_project_local(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent-home"))
    project = tmp_path / "project"
    project.mkdir()

    setup = IDESetup()
    assert Path(
        setup.get_config_path("pi", scope="project", project_dir=str(project))
    ) == (project / ".pi" / "extensions")

    with mock.patch.object(
        setup, "verify_gitleaks_installed", return_value=(True, "ok")
    ):
        success, _ = setup.setup_ide_hooks(
            "pi", scope="project", project_dir=str(project), force=True
        )

    assert success is True
    assert (project / ".pi" / "extensions" / "ai-guardian.ts").is_file()
    assert not (tmp_path / "agent-home" / "extensions" / "ai-guardian.ts").exists()


def test_pi_extension_template_contains_all_managed_events():
    for event_name in (
        'pi.on("input"',
        'pi.on("before_provider_request"',
        'pi.on("tool_call"',
        'pi.on("tool_result"',
        'pi.on("message_end"',
        'pi.on("user_bash"',
        'pi.on("session_start"',
        'pi.on("session_shutdown"',
    ):
        assert event_name in _PI_EXTENSION_TS
    assert "providerPayloadForScan" in _PI_EXTENSION_TS
    assert "restoreProviderCredentials" in _PI_EXTENSION_TS


def test_pi_transcript_text_extraction():
    entry = {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "visible response"},
                {"type": "thinking", "thinking": "internal reasoning"},
                {
                    "type": "toolCall",
                    "name": "write",
                    "arguments": {"path": "secret.txt"},
                },
            ],
        },
    }

    extracted = _extract_text_from_pi_entry(entry)
    assert "visible response" in extracted
    assert "internal reasoning" in extracted
    assert "secret.txt" in extracted


def test_pi_transcript_adapter_requires_pi_adapter():
    transcript = PiTranscriptAdapter()
    assert transcript.can_scan({}, PiAdapter()) is True
    assert transcript.can_scan({}, None) is False


def test_pi_session_adapter_reads_tree_shaped_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(tmp_path))
    path = tmp_path / "session.jsonl"
    entries = [
        {
            "type": "session",
            "id": "session-1",
            "cwd": str(tmp_path),
            "timestamp": "2026-09-19T10:00:00Z",
        },
        {
            "type": "message",
            "timestamp": "2026-09-19T10:01:00Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "create a file"}],
            },
        },
        {
            "type": "message",
            "timestamp": "2026-09-19T10:02:00Z",
            "message": {
                "role": "assistant",
                "model": "test-model",
                "content": [{"type": "text", "text": "I will create it."}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")

    adapter = PiSessionAdapter()
    sessions = adapter.discover(project_path=str(tmp_path))
    details = adapter.read_detail({"file_path": str(path)})

    assert sessions[0]["session_id"] == "session-1"
    assert sessions[0]["project_path"] == str(tmp_path)
    assert any(step["type"] == "user" for step in details)
    assert any(step["type"] == "assistant" for step in details)
