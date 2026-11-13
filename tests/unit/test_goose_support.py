"""Goose v1.59.0 wire protocol and host-only capability contracts."""

import builtins
import json
from io import StringIO
from unittest.mock import patch

import pytest

from ai_guardian.constants import GOOSE_MANAGED_HOOK_EVENTS, HookEvent
from ai_guardian.hook_adapters import detect_adapter, get_adapter_by_ide_type
from ai_guardian.hook_adapters.goose import GooseAdapter
from ai_guardian.hook_processing import (
    extract_tool_result,
    inject_security_only,
    process_hook_data,
)
from ai_guardian.ide_registry import (
    SANDBOX_CLI_IDE_TYPES_BY_RUNTIME,
    get_ide_integration,
)
from ai_guardian.response_format import IDEType
from ai_guardian_hook_runtime import (
    build_failure_response,
    ensure_hook_response,
    main as runtime_main,
)


def payload(event="PreToolUse", **values):
    return {
        "event": event,
        "session_id": "goose-test",
        "tool_call_id": "call-test",
        "tool_name": "shell",
        "tool_input": {"command": "pwd"},
        **values,
    }


@pytest.fixture(autouse=True)
def isolate_agent_identity(monkeypatch):
    monkeypatch.delenv("AI_GUARDIAN_IDE_TYPE", raising=False)
    monkeypatch.delenv("AI_GUARDIAN_HOOK_EVENT", raising=False)


@pytest.mark.parametrize("event", GOOSE_MANAGED_HOOK_EVENTS)
def test_detects_all_managed_events_without_claiming_other_hosts(event, monkeypatch):
    monkeypatch.delenv("AI_GUARDIAN_IDE_TYPE", raising=False)
    data = payload(event)
    assert isinstance(detect_adapter(data), GooseAdapter)
    assert GooseAdapter().normalize_input(data).event == GooseAdapter.EVENTS[event]
    assert not GooseAdapter.can_handle(
        {"hook_event_name": event, "session_id": "claude"}
    )
    assert not GooseAdapter.can_handle({"event": event})


def test_explicit_identity_and_environment_alias_select_goose(monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_IDE_TYPE", "goose")
    assert isinstance(detect_adapter({}), GooseAdapter)
    assert isinstance(get_adapter_by_ide_type(IDEType.GOOSE), GooseAdapter)
    assert GooseAdapter().agent_type == "goose"


@pytest.mark.parametrize(
    "name,args,canonical",
    [
        ("shell", {"command": "pwd"}, "Bash"),
        ("write", {"path": "notes.txt", "content": "safe"}, "Write"),
        ("edit", {"path": "notes.txt", "before": "old", "after": "new"}, "Edit"),
        ("tree", {"path": "."}, "LS"),
        ("read_image", {"source": "image.png"}, "Read"),
        ("read_image", {"source": "https://example.test/image.png"}, "WebFetch"),
        ("database__query", {"sql": "SELECT 1"}, "mcp__database__query"),
    ],
)
def test_native_tools_use_canonical_arguments_and_working_directory(
    tmp_path, name, args, canonical
):
    data = payload(tool_name=name, tool_input=args, working_dir=str(tmp_path))
    normalized = GooseAdapter().normalize_input(data)
    assert normalized.tool_name == canonical
    assert normalized.working_dir == str(tmp_path)
    assert normalized.tool_use_id == "call-test"
    assert normalized.session_id == "goose-test"
    assert normalized.raw_data is data
    assert data["tool_input"] == args
    if name in ("write", "edit", "tree"):
        assert normalized.tool_input["file_path"] == str(
            (tmp_path / args["path"]).resolve()
        )
    if name == "edit":
        assert normalized.tool_input["old_string"] == "old"
        assert normalized.tool_input["new_string"] == "new"
    if canonical == "WebFetch":
        assert normalized.tool_input["url"] == args["source"]


@pytest.mark.parametrize(
    "changes",
    [
        {"event": "unknown"},
        {"event": []},
        {"event": None},
        {"tool_name": 3},
        {"tool_input": "{}"},
        {"tool_input": []},
    ],
)
def test_malformed_pretool_payload_is_rejected_instead_of_scanned_as_empty(changes):
    with pytest.raises(ValueError):
        GooseAdapter().normalize_input(payload(**changes))


def test_prompt_output_and_session_fields_do_not_invent_transcript_support():
    data = payload("UserPromptSubmit", message="Summarize the code", working_dir=3)
    normalized = GooseAdapter().normalize_input(data)
    assert normalized.prompt_text == "Summarize the code"
    assert normalized.working_dir is None
    assert normalized.transcript_path is None
    assert GooseAdapter().get_default_transcript_paths() == []
    integration = get_ide_integration("goose")
    assert integration.transcript_formats == ()
    assert integration.session_support == "none"


def test_pretool_blocks_without_echoing_private_scanner_detail():
    result = GooseAdapter().format_response(
        True,
        "private-detail",
        hook_event=HookEvent.PRE_TOOL_USE,
        violation_type="secret_detected",
        warning_message="private-warning",
    )
    assert json.loads(result["output"]) == {
        "decision": "block",
        "reason": "Operation blocked by ai-guardian: secret detected",
    }
    assert result["exit_code"] == 0
    assert result["_blocked"] is True
    assert "private" not in result["output"]
    allowed = GooseAdapter().format_response(
        False,
        hook_event=HookEvent.PRE_TOOL_USE,
        warning_message="not-consumed",
    )
    assert json.loads(allowed["output"]) == {"decision": "allow"}


@pytest.mark.parametrize(
    "event",
    [
        HookEvent.PROMPT,
        HookEvent.POST_TOOL_USE,
        HookEvent.SESSION_START,
        HookEvent.SESSION_END,
        HookEvent.STOP,
    ],
)
def test_passive_events_cannot_claim_denial_or_output_replacement(event):
    result = GooseAdapter().format_response(
        True,
        "private-detail",
        hook_event=event,
        modified_output="replacement",
        redacted_output="replacement",
        security_message="instructions",
    )
    assert result == {"output": None, "exit_code": 0}
    assert get_ide_integration("goose").post_output_transform is False
    assert "Stop" not in GOOSE_MANAGED_HOOK_EVENTS


@pytest.mark.parametrize("action", ["allow", "block"])
def test_hook_failure_uses_nonzero_undecided_result_for_host_on_failure(action):
    failed = build_failure_response(payload(), action)
    assert failed["exit_code"] == 1
    assert failed["output"] is None
    assert ensure_hook_response(payload(), failed, action) == failed


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {},
        {"output": "not-json", "exit_code": 0},
        {"output": "{}", "exit_code": 0},
        {"output": '{"decision":"deny"}', "exit_code": 0},
        {"output": '{"decision":"allow"}', "exit_code": True},
    ],
)
def test_invalid_daemon_response_does_not_turn_into_a_successful_pretool_hook(response):
    result = ensure_hook_response(payload(), response, "allow")
    assert result["exit_code"] != 0
    assert result["output"] is None


def test_dependency_light_startup_failure_respects_installed_fail_closed_contract(
    capsys, monkeypatch
):
    real_import = builtins.__import__

    def failed_import(name, *args, **kwargs):
        if name == "ai_guardian.cli":
            raise ImportError("private startup detail")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("sys.argv", ["ai-guardian", "--ide", "goose"])
    monkeypatch.setattr("sys.stdin", StringIO(json.dumps(payload())))
    with patch("builtins.__import__", side_effect=failed_import):
        assert runtime_main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private startup detail" not in captured.err


def test_malformed_input_at_pipeline_boundary_remains_an_undecided_failure():
    result = process_hook_data(payload(tool_input=[]))
    assert result["exit_code"] == 1
    assert result["output"] is None


def test_paused_daemon_pretool_acknowledgement_is_a_valid_goose_allow():
    result = inject_security_only(payload())
    assert json.loads(result["output"]) == {"decision": "allow"}
    assert ensure_hook_response(payload(), result)["exit_code"] == 0


def test_post_extraction_scans_the_complete_structured_goose_result():
    output = {
        "content": [
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
        ],
        "structuredContent": {"nested": "third"},
        "isError": False,
    }
    text, tool = extract_tool_result(payload("PostToolUse", tool_output=output))
    assert json.loads(text) == output
    assert tool == "Bash"


def test_host_cli_registration_does_not_advertise_unshipped_sandbox_runtimes():
    assert get_ide_integration("goose").cli_capable is True
    for runtime in ("container", "openshell"):
        assert "goose" not in SANDBOX_CLI_IDE_TYPES_BY_RUNTIME[runtime]


@pytest.mark.parametrize("tool", ["write", "edit", "tree"])
def test_native_path_not_unknown_alias_selects_the_real_target(tmp_path, tool):
    result = GooseAdapter().normalize_input(
        payload(
            tool_name=tool,
            tool_input={
                "path": "real.txt",
                "file_path": "different.txt",
                "before": "old",
                "after": "new",
            },
            working_dir=str(tmp_path),
        )
    )
    assert result.file_path == str(tmp_path / "real.txt")
    assert result.tool_input["file_path"] == result.file_path


def test_native_tree_default_and_managed_mcp_identity(tmp_path):
    result = GooseAdapter().normalize_input(
        payload(tool_name="tree", tool_input={}, working_dir=str(tmp_path))
    )
    assert result.file_path == str(tmp_path)
    result = GooseAdapter().normalize_input(
        payload(tool_name="ai-guardian-goose_ai-guardian__get_config")
    )
    assert result.tool_name == "mcp__ai-guardian__get_config"


def test_relative_workspace_is_not_used_to_guess_a_native_file_target():
    with pytest.raises(ValueError, match="working directory must be absolute"):
        GooseAdapter().normalize_input(
            payload(
                tool_name="write",
                tool_input={"path": "notes.txt"},
                working_dir="relative",
            )
        )


@pytest.mark.parametrize("tool", ["write", "edit", "tree", "read_image"])
def test_native_file_tools_keep_tilde_literal_like_the_host(tmp_path, tool):
    normalized = GooseAdapter().normalize_input(
        payload(
            tool_name=tool,
            tool_input={"path": "~/notes.txt", "source": "~/image.png"},
            working_dir=str(tmp_path),
        )
    )
    filename = "image.png" if tool == "read_image" else "notes.txt"
    assert normalized.file_path == str(tmp_path / "~" / filename)


def test_image_file_url_resolves_the_decoded_local_target(tmp_path):
    path = tmp_path / "an image.png"
    normalized = GooseAdapter().normalize_input(
        payload(tool_name="read_image", tool_input={"source": path.as_uri()})
    )
    assert normalized.file_path == str(path)
    with pytest.raises(ValueError, match="Unsupported Goose image file URL"):
        GooseAdapter().normalize_input(
            payload(
                tool_name="read_image",
                tool_input={"source": "file://elsewhere.test/image.png"},
            )
        )
