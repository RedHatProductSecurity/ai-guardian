"""Focused tests for the xAI Grok Build integration."""

import json
from unittest.mock import patch

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters.grok import GrokAdapter
from ai_guardian.hook_processing import (
    extract_file_content_from_tool,
    extract_tool_result,
)
from ai_guardian.response_format import IDEType
from ai_guardian.setup import get_mcp_config_path
from ai_guardian.setup.hooks import IDESetup


def test_grok_detects_and_normalizes_camel_case_hook_payload(tmp_path):
    payload = {
        "hookEventName": "PreToolUse",
        "workspaceRoot": str(tmp_path),
        "toolName": "read_file",
        "toolInput": {"path": str(tmp_path / "secret.txt")},
        "sessionId": "session-1",
        "toolUseId": "tool-1",
    }

    adapter = GrokAdapter()
    assert adapter.can_handle(payload)

    normalized = adapter.normalize_input(payload)
    assert normalized.event == HookEvent.PRE_TOOL_USE
    assert normalized.tool_name == "Read"
    assert normalized.tool_input == payload["toolInput"]
    assert normalized.file_path == str(tmp_path / "secret.txt")
    assert normalized.working_dir == str(tmp_path)
    assert normalized.session_id == "session-1"
    assert normalized.tool_use_id == "tool-1"


def test_grok_rejects_generic_pascal_case_payload_without_grok_fields():
    assert not GrokAdapter.can_handle({"hookEventName": "PreToolUse"})


def test_grok_formats_native_pre_tool_denial_and_ignores_passive_output():
    adapter = GrokAdapter()
    blocked = adapter.format_response(
        has_secrets=True,
        error_message="synthetic secret finding",
        hook_event=HookEvent.PRE_TOOL_USE,
        violation_type="secret_detected",
    )
    assert json.loads(blocked["output"]) == {
        "decision": "deny",
        "reason": "synthetic secret finding",
    }
    assert blocked["exit_code"] == 0
    assert blocked["_blocked"] is True

    passive = adapter.format_response(
        has_secrets=False,
        hook_event=HookEvent.POST_TOOL_USE,
        modified_output="must-not-be-emitted",
    )
    assert passive["output"] is None
    assert passive["exit_code"] == 0


def test_shared_pre_tool_file_extraction_accepts_grok_tool_input(tmp_path):
    target = tmp_path / "fixture.txt"
    target.write_text("synthetic fixture", encoding="utf-8")
    payload = {
        "hookEventName": "PreToolUse",
        "toolName": "read_file",
        "toolInput": {"path": str(target)},
    }

    with patch(
        "ai_guardian.hook_processing.check_directory_denied",
        return_value=(False, None, None, None),
    ):
        content, filename, file_path, denied, reason, warning = (
            extract_file_content_from_tool(payload)
        )

    assert content == "synthetic fixture"
    assert filename == "fixture.txt"
    assert file_path == str(target)
    assert denied is False
    assert reason is None
    assert warning is None


def test_shared_post_tool_extraction_accepts_grok_tool_output():
    output, tool_name = extract_tool_result(
        {
            "hookEventName": "PostToolUse",
            "toolName": "run_terminal_command",
            "toolOutput": {"output": "synthetic output"},
        }
    )

    assert output == "synthetic output"
    assert tool_name == "Bash"


def test_grok_setup_and_mcp_paths_support_user_and_project_scope(tmp_path, monkeypatch):
    grok_home = tmp_path / "grok-home"
    project = tmp_path / "project"
    monkeypatch.setenv("GROK_HOME", str(grok_home))

    setup = IDESetup()
    assert setup.get_config_path("grok") == str(
        grok_home / "hooks" / "ai-guardian.json"
    )
    assert setup.get_config_path(
        "grok", scope="project", project_dir=str(project)
    ) == str(project / ".grok" / "hooks" / "ai-guardian.json")
    assert get_mcp_config_path("grok") == grok_home / "config.toml"
    assert get_mcp_config_path("grok", scope="project", project_dir=str(project)) == (
        project / ".grok" / "config.toml"
    )


def test_grok_reports_its_response_identity():
    assert GrokAdapter().ide_type == IDEType.GROK
