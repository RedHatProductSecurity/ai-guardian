"""Tests for ai_guardian.constants module."""

from ai_guardian.constants import (
    ActionMode,
    ViolationType,
    HookEvent,
    ALL_VIOLATION_TYPES,
    ALL_HOOK_EVENTS,
    ALL_ACTION_MODES,
    CRUSH_HOOK_EVENTS,
    ALL_HOOK_EVENT_DISPLAY_NAMES,
)


class TestActionMode:
    def test_values(self):
        assert ActionMode.BLOCK == "block"
        assert ActionMode.WARN == "warn"
        assert ActionMode.LOG_ONLY == "log-only"
        assert ActionMode.REDACT == "redact"

    def test_str_mixin(self):
        assert isinstance(ActionMode.BLOCK, str)
        assert ActionMode.BLOCK == "block"
        assert "block" == ActionMode.BLOCK

    def test_all_action_modes(self):
        assert set(ALL_ACTION_MODES) == {"block", "warn", "log-only", "redact", "ask"}


class TestViolationType:
    def test_values(self):
        assert ViolationType.SECRET_DETECTED == "secret_detected"
        assert ViolationType.PII_DETECTED == "pii_detected"
        assert ViolationType.DIRECTORY_BLOCKING == "directory_blocking"
        assert ViolationType.TOOL_PERMISSION == "tool_permission"
        assert ViolationType.PROMPT_INJECTION == "prompt_injection"
        assert ViolationType.JAILBREAK_DETECTED == "jailbreak_detected"
        assert ViolationType.SSRF_BLOCKED == "ssrf_blocked"
        assert ViolationType.CONFIG_FILE_EXFIL == "config_file_exfil"
        assert ViolationType.SECRET_REDACTION == "secret_redaction"
        assert ViolationType.SECRET_IN_TRANSCRIPT == "secret_in_transcript"
        assert ViolationType.PII_IN_TRANSCRIPT == "pii_in_transcript"

    def test_str_mixin(self):
        assert isinstance(ViolationType.SECRET_DETECTED, str)
        assert ViolationType.SECRET_DETECTED == "secret_detected"

    def test_all_violation_types_complete(self):
        assert len(ALL_VIOLATION_TYPES) == len(ViolationType)
        for vt in ViolationType:
            assert vt.value in ALL_VIOLATION_TYPES

    def test_usable_in_list_membership(self):
        choices = list(ViolationType)
        assert "secret_detected" in choices
        assert "pii_detected" in choices


class TestHookEvent:
    def test_values(self):
        assert HookEvent.PROMPT == "prompt"
        assert HookEvent.PRE_TOOL_USE == "pretooluse"
        assert HookEvent.PERMISSION_REQUEST == "permissionrequest"
        assert HookEvent.POST_TOOL_USE == "posttooluse"
        assert HookEvent.PRE_COMPACT == "precompact"
        assert HookEvent.BEFORE_READ_FILE == "beforereadfile"
        assert HookEvent.INTERRUPT == "interrupt"
        assert HookEvent.SUBAGENT_START == "subagentstart"
        assert HookEvent.SUBAGENT_STOP == "subagentstop"

    def test_str_mixin(self):
        assert isinstance(HookEvent.PROMPT, str)
        assert HookEvent.PROMPT == "prompt"

    def test_all_hook_events(self):
        assert set(ALL_HOOK_EVENTS) == {
            "prompt",
            "pretooluse",
            "permissionrequest",
            "posttooluse",
            "precompact",
            "beforereadfile",
            "stop",
            "interrupt",
            "sessionstart",
            "sessionend",
            "postcompact",
            "subagentstart",
            "subagentstop",
        }

    def test_usable_in_tuple_membership(self):
        events = (HookEvent.PRE_TOOL_USE, HookEvent.BEFORE_READ_FILE)
        assert "pretooluse" in events
        assert "beforereadfile" in events
        assert "prompt" not in events


class TestCrushHookEvents:
    def test_is_tuple(self):
        assert isinstance(CRUSH_HOOK_EVENTS, tuple)

    def test_contains_pretooluse(self):
        assert "PreToolUse" in CRUSH_HOOK_EVENTS

    def test_all_are_valid_display_names(self):
        for event in CRUSH_HOOK_EVENTS:
            assert event in ALL_HOOK_EVENT_DISPLAY_NAMES
