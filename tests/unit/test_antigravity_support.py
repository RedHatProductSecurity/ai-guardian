"""Tests for Google Antigravity CLI (agy) support."""

import json

import pytest

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters import detect_adapter, get_adapter_by_ide_type
from ai_guardian.hook_adapters.antigravity import AntigravityAdapter
from ai_guardian.response_format import IDEType
from ai_guardian.setup.hooks import IDESetup
from ai_guardian.tools.policy import ToolPolicyChecker


def _pre_tool_use(name="run_command", args=None):
    return {
        "conversationId": "conv-1",
        "workspacePaths": ["/work"],
        "transcriptPath": "/work/.gemini/antigravity-cli/transcript.jsonl",
        "modelName": "auto",
        "toolCall": {"name": name, "args": args if args is not None else {}},
        "stepIdx": 7,
    }


# ── Detection ────────────────────────────────────────────────────────────


class TestDetection:
    def test_detects_pre_tool_use_payload(self):
        assert isinstance(detect_adapter(_pre_tool_use()), AntigravityAdapter)

    def test_detects_payload_without_tool_call(self):
        data = {"conversationId": "c", "workspacePaths": ["/work"], "stepIdx": 1}
        assert isinstance(detect_adapter(data), AntigravityAdapter)

    def test_ignores_claude_payload(self):
        data = {"hook_event_name": "PreToolUse", "tool_name": "Bash"}
        assert not isinstance(detect_adapter(data), AntigravityAdapter)

    def test_ignores_gemini_payload(self):
        data = {"hook_event_name": "BeforeTool", "transcript_path": "/t.jsonl"}
        assert not isinstance(detect_adapter(data), AntigravityAdapter)

    def test_does_not_claim_payloads_that_name_their_event(self):
        # AntigravityAdapter is first in the detection order; a future agent
        # reusing conversationId but naming its event must not be captured.
        data = {
            "conversationId": "c",
            "workspacePaths": ["/w"],
            "hook_event_name": "PreToolUse",
        }
        assert not isinstance(detect_adapter(data), AntigravityAdapter)

    @pytest.mark.parametrize("alias", ["antigravity", "agy"])
    def test_ide_flag_selects_adapter(self, alias):
        data = {"_ide_type": alias, "hook_event_name": "PreToolUse"}
        assert isinstance(detect_adapter(data), AntigravityAdapter)

    def test_lookup_by_ide_type(self):
        adapter = get_adapter_by_ide_type(IDEType.ANTIGRAVITY)
        assert isinstance(adapter, AntigravityAdapter)


# ── Event inference ──────────────────────────────────────────────────────


class TestEventInference:
    def test_tool_call_means_pre_tool_use(self):
        adapter = AntigravityAdapter()
        assert adapter.normalize_input(_pre_tool_use()).event == HookEvent.PRE_TOOL_USE

    def test_step_idx_without_tool_call_means_post_tool_use(self):
        adapter = AntigravityAdapter()
        data = {"conversationId": "c", "workspacePaths": ["/w"], "stepIdx": 5}
        assert adapter.normalize_input(data).event == HookEvent.POST_TOOL_USE

    def test_invocation_num_means_prompt(self):
        adapter = AntigravityAdapter()
        data = {"conversationId": "c", "workspacePaths": ["/w"], "invocationNum": 2}
        assert adapter.normalize_input(data).event == HookEvent.PROMPT

    def test_termination_reason_means_stop(self):
        adapter = AntigravityAdapter()
        data = {
            "conversationId": "c",
            "workspacePaths": ["/w"],
            "terminationReason": "model_stop",
        }
        assert adapter.normalize_input(data).event == HookEvent.STOP

    def test_post_tool_use_payload_carries_tool_call(self):
        # Antigravity's PostToolUse payload includes toolCall, contrary to its
        # documented contract; only "error" separates it from PreToolUse.
        adapter = AntigravityAdapter()
        data = _pre_tool_use()
        data["error"] = ""
        assert adapter.normalize_input(data).event == HookEvent.POST_TOOL_USE

    def test_post_tool_use_with_error_text(self):
        adapter = AntigravityAdapter()
        data = _pre_tool_use()
        data["error"] = "exit status 1"
        n = adapter.normalize_input(data)
        assert n.event == HookEvent.POST_TOOL_USE
        assert n.tool_response == "exit status 1"

    def test_env_var_overrides_inference(self, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_HOOK_EVENT", "PostToolUse")
        adapter = AntigravityAdapter()
        assert adapter.normalize_input(_pre_tool_use()).event == HookEvent.POST_TOOL_USE

    def test_stamped_event_survives_daemon_forwarding(self, monkeypatch):
        # The daemon is a separate process, so the declared event must travel
        # inside the payload rather than the environment.
        monkeypatch.delenv("AI_GUARDIAN_HOOK_EVENT", raising=False)
        data = _pre_tool_use()
        data["_hook_event"] = "PostToolUse"
        assert AntigravityAdapter().normalize_input(data).event == (
            HookEvent.POST_TOOL_USE
        )

    def test_stamped_event_beats_stale_env(self, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_HOOK_EVENT", "PreToolUse")
        data = {"conversationId": "c", "workspacePaths": ["/w"], "invocationNum": 1}
        data["_hook_event"] = "PreInvocation"
        assert AntigravityAdapter().normalize_input(data).event == HookEvent.PROMPT


# ── Normalization ────────────────────────────────────────────────────────


class TestNormalization:
    def test_run_command_maps_to_bash_with_command_key(self):
        n = AntigravityAdapter().normalize_input(
            _pre_tool_use("run_command", {"CommandLine": "rm -rf /tmp/x"})
        )
        assert n.tool_name == "Bash"
        assert n.tool_input["command"] == "rm -rf /tmp/x"
        assert n.tool_input["CommandLine"] == "rm -rf /tmp/x"

    def test_view_file_maps_to_read_with_file_path(self):
        n = AntigravityAdapter().normalize_input(
            _pre_tool_use("view_file", {"AbsolutePath": "/etc/passwd"})
        )
        assert n.tool_name == "Read"
        assert n.file_path == "/etc/passwd"
        assert n.tool_input["file_path"] == "/etc/passwd"

    def test_propose_code_uses_target_file(self):
        n = AntigravityAdapter().normalize_input(
            _pre_tool_use("propose_code", {"TargetFile": "/work/app.py"})
        )
        assert n.tool_name == "Edit"
        assert n.file_path == "/work/app.py"

    def test_unknown_tool_name_passes_through(self):
        n = AntigravityAdapter().normalize_input(_pre_tool_use("some_new_tool", {}))
        assert n.tool_name == "some_new_tool"

    def test_camel_case_metadata_is_mapped(self):
        n = AntigravityAdapter().normalize_input(_pre_tool_use())
        assert n.session_id == "conv-1"
        assert n.working_dir == "/work"
        assert n.transcript_path.endswith("transcript.jsonl")
        assert n.tool_use_id == "7"

    def test_missing_args_yields_empty_tool_input(self):
        data = {"conversationId": "c", "workspacePaths": ["/w"], "toolCall": {}}
        n = AntigravityAdapter().normalize_input(data)
        assert n.tool_input == {}
        assert n.file_path is None


# ── Response formatting ──────────────────────────────────────────────────


class TestResponseFormatting:
    def _payload(self, result):
        return json.loads(result["output"])

    def test_pre_tool_use_block_uses_flat_deny(self):
        result = AntigravityAdapter().format_response(
            True,
            "secret detected",
            hook_event=HookEvent.PRE_TOOL_USE,
            violation_type="secret_detected",
        )
        assert self._payload(result) == {
            "decision": "deny",
            "reason": "secret detected",
        }
        assert result["_blocked"] is True
        assert result["_violation_type"] == "secret_detected"
        assert result["exit_code"] == 0

    def test_prompt_warning_injects_ephemeral_message(self):
        result = AntigravityAdapter().format_response(
            False,
            hook_event=HookEvent.PROMPT,
            security_message="rules",
        )
        assert self._payload(result) == {"injectSteps": [{"ephemeralMessage": "rules"}]}

    def test_warn_text_rides_along_on_ask(self):
        # Antigravity shows the reason at the prompt; dropping it would leave
        # the user with an unexplained permission request.
        result = AntigravityAdapter().format_response(
            False,
            hook_event=HookEvent.PRE_TOOL_USE,
            warning_message="possible secret in command",
        )
        payload = self._payload(result)
        assert payload["decision"] == "ask"
        assert "possible secret" in payload["reason"]

    def test_post_tool_use_returns_empty_object(self):
        result = AntigravityAdapter().format_response(
            False,
            hook_event=HookEvent.POST_TOOL_USE,
            warning_message="heads up",
        )
        assert self._payload(result) == {}

    def test_post_tool_use_cannot_replace_output(self):
        result = AntigravityAdapter().format_response(
            False,
            hook_event=HookEvent.POST_TOOL_USE,
            modified_output="redacted",
        )
        assert self._payload(result) == {}

    def test_clean_pre_tool_use_defers_to_antigravity(self):
        # Antigravity denies any PreToolUse response without a decision, so a
        # clean check must explicitly hand the choice back to its own prompt.
        result = AntigravityAdapter().format_response(
            False, hook_event=HookEvent.PRE_TOOL_USE
        )
        assert self._payload(result) == {"decision": "ask"}
        assert "_blocked" not in result

    def test_clean_non_pre_tool_use_stays_silent(self):
        result = AntigravityAdapter().format_response(
            False, hook_event=HookEvent.POST_TOOL_USE
        )
        assert self._payload(result) == {}

    def test_block_outside_pre_tool_use_does_not_emit_decision(self):
        result = AntigravityAdapter().format_response(
            True,
            "secret detected",
            hook_event=HookEvent.POST_TOOL_USE,
            violation_type="secret_detected",
        )
        assert "decision" not in self._payload(result)
        assert result["_blocked"] is True


# ── Policy layer ─────────────────────────────────────────────────────────


class TestMcpNaming:
    def test_call_mcp_tool_keeps_mcp_prefix(self):
        n = AntigravityAdapter().normalize_input(
            _pre_tool_use(
                "call_mcp_tool",
                {"ServerName": "ai-guardian", "ToolName": "get_config"},
            )
        )
        assert n.tool_name == "mcp__ai-guardian__get_config"

    def test_policy_layer_agrees_on_mcp_name(self):
        checker = ToolPolicyChecker()
        name, _ = checker._extract_tool_info(
            _pre_tool_use(
                "call_mcp_tool",
                {"ServerName": "ai-guardian", "ToolName": "get_config"},
            )
        )
        assert name == "mcp__ai-guardian__get_config"

    def test_mcp_without_names_is_still_restricted(self):
        n = AntigravityAdapter().normalize_input(_pre_tool_use("call_mcp_tool", {}))
        assert n.tool_name.startswith("mcp__")


class TestContentExtraction:
    def test_write_content_reaches_scanner_keys(self):
        n = AntigravityAdapter().normalize_input(
            _pre_tool_use(
                "write_blob", {"TargetFile": "/w/a.py", "Content": "import os"}
            )
        )
        assert n.tool_input["content"] == "import os"
        assert n.tool_input["new_string"] == "import os"

    def test_replacement_chunks_are_joined(self):
        n = AntigravityAdapter().normalize_input(
            _pre_tool_use(
                "propose_code",
                {
                    "TargetFile": "/w/a.py",
                    "ReplacementChunks": [
                        {"targetContent": "line one"},
                        {"targetContent": "line two"},
                    ],
                },
            )
        )
        assert n.tool_input["content"] == "line one\nline two"

    def test_no_content_leaves_keys_absent(self):
        n = AntigravityAdapter().normalize_input(
            _pre_tool_use("view_file", {"AbsolutePath": "/w/a.py"})
        )
        assert "content" not in n.tool_input


class TestEventTagging:
    def test_setup_tags_each_command_with_its_event(self):
        from ai_guardian.setup.hooks import _tag_antigravity_events

        tagged = _tag_antigravity_events(IDESetup.IDE_CONFIGS["antigravity"]["hooks"])
        spec = tagged["ai-guardian"]
        assert spec["PreToolUse"][0]["hooks"][0]["command"].endswith(
            "--hook-event PreToolUse"
        )
        assert spec["PostToolUse"][0]["hooks"][0]["command"].endswith(
            "--hook-event PostToolUse"
        )
        assert spec["PreInvocation"][0]["command"].endswith(
            "--hook-event PreInvocation"
        )

    def test_tagged_command_is_still_recognized_as_ai_guardian(self):
        # doctor/setup detect installed hooks by parsing the command's first
        # token, so the binary must stay in front.
        from ai_guardian.setup.hooks import _tag_antigravity_events
        from ai_guardian.setup.utils import _is_ai_guardian_command

        tagged = _tag_antigravity_events(
            {
                "ai-guardian": {
                    "PreToolUse": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {"command": "/usr/bin/ai-guardian --ide antigravity"}
                            ],
                        }
                    ]
                }
            }
        )
        cmd = tagged["ai-guardian"]["PreToolUse"][0]["hooks"][0]["command"]
        assert _is_ai_guardian_command(cmd)

    def test_tagging_does_not_mutate_the_template(self):
        from ai_guardian.setup.hooks import _tag_antigravity_events

        template = IDESetup.IDE_CONFIGS["antigravity"]["hooks"]
        before = template["ai-guardian"]["PreToolUse"][0]["hooks"][0]["command"]
        _tag_antigravity_events(template)
        after = template["ai-guardian"]["PreToolUse"][0]["hooks"][0]["command"]
        assert before == after

    def test_tagging_is_idempotent(self):
        from ai_guardian.setup.hooks import _tag_antigravity_events

        once = _tag_antigravity_events(IDESetup.IDE_CONFIGS["antigravity"]["hooks"])
        twice = _tag_antigravity_events(once)
        assert twice == once


class TestPolicyExtraction:
    def test_extracts_tool_info_from_tool_call(self):
        checker = ToolPolicyChecker()
        name, tool_input = checker._extract_tool_info(
            _pre_tool_use("run_command", {"CommandLine": "curl http://x"})
        )
        assert name == "Bash"
        assert tool_input["command"] == "curl http://x"

    def test_extracts_file_path_argument(self):
        checker = ToolPolicyChecker()
        name, tool_input = checker._extract_tool_info(
            _pre_tool_use("view_file", {"AbsolutePath": "/etc/passwd"})
        )
        assert name == "Read"
        assert tool_input["file_path"] == "/etc/passwd"

    def test_tool_map_not_applied_to_other_agents(self):
        # "list_dir" must stay untouched for a non-Antigravity payload —
        # remapping it would change which permission rules match.
        checker = ToolPolicyChecker()
        name, _ = checker._extract_tool_info(
            {"tool_name": "list_dir", "tool_input": {}}
        )
        assert name == "list_dir"

    def test_detects_ide_type(self, monkeypatch):
        monkeypatch.delenv("AI_GUARDIAN_IDE_TYPE", raising=False)
        checker = ToolPolicyChecker()
        assert checker._detect_ide_type(_pre_tool_use()) == "antigravity"


# ── Setup ────────────────────────────────────────────────────────────────


class TestSetup:
    def test_ide_config_registered(self):
        config = IDESetup.IDE_CONFIGS["antigravity"]
        assert config["config_path"] == "~/.gemini/config/hooks.json"
        assert "PreToolUse" in config["hooks"]["ai-guardian"]
        assert "PostToolUse" in config["hooks"]["ai-guardian"]

    def test_supports_hooks(self):
        assert IDESetup().supports_hooks("antigravity") is True

    def test_merge_preserves_other_hooks(self):
        setup = IDESetup()
        existing = {"lint-checker": {"PostToolUse": []}}
        merged, warnings = setup.merge_hooks(
            existing,
            IDESetup.IDE_CONFIGS["antigravity"]["hooks"],
            "antigravity",
        )
        assert "lint-checker" in merged
        assert "ai-guardian" in merged
        assert warnings

    def test_merge_is_idempotent(self):
        setup = IDESetup()
        template = IDESetup.IDE_CONFIGS["antigravity"]["hooks"]
        merged, _ = setup.merge_hooks({}, template, "antigravity")
        merged_again, warnings = setup.merge_hooks(merged, template, "antigravity")
        assert merged_again == merged
        assert not warnings

    def test_check_hooks_configured(self, tmp_path):
        config_path = tmp_path / "hooks.json"
        config_path.write_text(
            json.dumps(
                {
                    "ai-guardian": {
                        "PreToolUse": [
                            {
                                "matcher": "*",
                                "hooks": [{"command": "/usr/bin/ai-guardian"}],
                            }
                        ]
                    }
                }
            )
        )
        assert IDESetup().check_hooks_configured(config_path, "antigravity") is True

    def test_check_hooks_configured_false_for_other_tools(self, tmp_path):
        config_path = tmp_path / "hooks.json"
        config_path.write_text(
            json.dumps(
                {
                    "lint-checker": {
                        "PostToolUse": [
                            {"matcher": "*", "hooks": [{"command": "./lint.sh"}]}
                        ]
                    }
                }
            )
        )
        assert IDESetup().check_hooks_configured(config_path, "antigravity") is False
