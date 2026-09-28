"""Tests for OpenCode hook adapter support (Issue #819)."""

import json
import os
from unittest import mock

import pytest

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters import detect_adapter
from ai_guardian.hook_adapters.opencode import OpenCodeAdapter


class TestOpenCodeDetection:
    """Test OpenCode adapter detection."""

    @pytest.fixture(autouse=True)
    def _clear_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AI_GUARDIAN_IDE_TYPE", None)
            yield

    def test_detect_from_opencode_version(self):
        adapter = detect_adapter({"opencode_version": "1.0.0"})
        assert isinstance(adapter, OpenCodeAdapter)

    def test_detect_from_hook_source(self):
        adapter = detect_adapter({"hook_source": "opencode"})
        assert isinstance(adapter, OpenCodeAdapter)

    def test_env_var_override(self):
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "opencode"}):
            adapter = detect_adapter({})
            assert isinstance(adapter, OpenCodeAdapter)

    def test_ide_type_field(self):
        adapter = detect_adapter({"_ide_type": "opencode"})
        assert isinstance(adapter, OpenCodeAdapter)

    def test_name(self):
        assert OpenCodeAdapter().name == "OpenCode"

    def test_can_handle_false_for_empty(self):
        assert OpenCodeAdapter.can_handle({}) is False

    def test_can_handle_true_for_opencode_version(self):
        assert OpenCodeAdapter.can_handle({"opencode_version": "1.0.0"}) is True

    def test_can_handle_true_for_hook_source(self):
        assert OpenCodeAdapter.can_handle({"hook_source": "opencode"}) is True


class TestOpenCodeNormalization:
    """Test OpenCode event normalization."""

    def test_tool_execute_before(self):
        data = {
            "hook_event_name": "tool.execute.before",
            "opencode_version": "1.0.0",
            "tool_name": "Bash",
            "tool_use": {"input": {"command": "ls"}},
            "cwd": "/home/user",
        }
        n = OpenCodeAdapter().normalize_input(data)
        assert n.event == HookEvent.PRE_TOOL_USE
        assert n.tool_name == "Bash"
        assert n.tool_input == {"command": "ls"}
        assert n.working_dir == "/home/user"

    def test_tool_execute_after(self):
        data = {
            "hook_event_name": "tool.execute.after",
            "opencode_version": "1.0.0",
            "tool_name": "Read",
            "tool_response": {"output": "file contents"},
        }
        n = OpenCodeAdapter().normalize_input(data)
        assert n.event == HookEvent.POST_TOOL_USE
        assert n.tool_name == "Read"
        assert n.tool_response == {"output": "file contents"}

    def test_message_submit(self):
        data = {
            "hook_event_name": "message.submit",
            "opencode_version": "1.0.0",
            "prompt": "help me fix the bug",
        }
        n = OpenCodeAdapter().normalize_input(data)
        assert n.event == HookEvent.PROMPT
        assert n.prompt_text == "help me fix the bug"

    def test_file_path_extraction(self):
        data = {
            "hook_event_name": "tool.execute.before",
            "opencode_version": "1.0.0",
            "tool_name": "Read",
            "tool_use": {"input": {"file_path": "/tmp/secret.py"}},
        }
        n = OpenCodeAdapter().normalize_input(data)
        assert n.file_path == "/tmp/secret.py"

    @pytest.mark.parametrize(
        "native_name,canonical_name,tool_input,canonical_key",
        [
            ("read", "Read", {"filePath": "/tmp/secret.py"}, "file_path"),
            ("write", "Write", {"filePath": "/tmp/secret.py"}, "file_path"),
            (
                "edit",
                "Edit",
                {
                    "filePath": "/tmp/secret.py",
                    "oldString": "old",
                    "newString": "new",
                },
                "file_path",
            ),
            ("bash", "Bash", {"command": "printf safe"}, "command"),
        ],
    )
    def test_native_tools_are_canonicalized(
        self, native_name, canonical_name, tool_input, canonical_key
    ):
        data = {
            "hook_event_name": "tool.execute.before",
            "opencode_version": "1.0.0",
            "tool_use": {"name": native_name, "input": tool_input},
        }

        normalized = OpenCodeAdapter().normalize_input(data)

        assert normalized.tool_name == canonical_name
        expected_value = tool_input.get(canonical_key, tool_input.get("filePath"))
        assert normalized.tool_input[canonical_key] == expected_value


class TestOpenCodeResponseFormatting:
    """Test OpenCode response formatting (inherits BaseAgentAdapter format)."""

    def test_pretooluse_block(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=True,
            error_message="Secret found in file",
            hook_event=HookEvent.PRE_TOOL_USE,
        )
        assert result["exit_code"] == 0
        data = json.loads(result["output"])
        assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert result["_blocked"] is True

    def test_pretooluse_allow(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=False,
            hook_event=HookEvent.PRE_TOOL_USE,
        )
        assert result["exit_code"] == 0
        data = json.loads(result["output"])
        assert data == {}

    def test_posttooluse_block(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=True,
            error_message="Secret in output",
            hook_event=HookEvent.POST_TOOL_USE,
        )
        data = json.loads(result["output"])
        assert data["decision"] == "block"
        assert result["_blocked"] is True

    def test_posttooluse_redaction(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=False,
            hook_event=HookEvent.POST_TOOL_USE,
            modified_output="[REDACTED]",
        )
        data = json.loads(result["output"])
        assert data["hookSpecificOutput"]["updatedToolOutput"] == "[REDACTED]"

    def test_prompt_block(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=True,
            error_message="Prompt injection detected",
            hook_event=HookEvent.PROMPT,
        )
        data = json.loads(result["output"])
        assert data["decision"] == "block"

    def test_prompt_security_message(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=False,
            hook_event=HookEvent.PROMPT,
            security_message="SECURITY RULES",
        )
        data = json.loads(result["output"])
        assert "SECURITY RULES" in data["systemMessage"]

    def test_violation_type_metadata(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=True,
            error_message="Secret found",
            hook_event=HookEvent.PRE_TOOL_USE,
            violation_type="secret_detected",
        )
        assert result["_violation_type"] == "secret_detected"
