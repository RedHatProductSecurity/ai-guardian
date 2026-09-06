"""Tests for Stop/SessionEnd/PostCompact hook handling (Issue #765, #1007)."""

import json
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from ai_guardian.constants import ALL_HOOK_EVENTS, HookEvent
from ai_guardian.hook_adapters.base_agent import BaseAgentAdapter
from ai_guardian.hook_adapters.base import HookAdapter


class TestHookEventStop(TestCase):
    """HookEvent.STOP enum tests."""

    def test_stop_enum_exists(self):
        assert HookEvent.STOP == "stop"

    def test_stop_in_all_hook_events(self):
        assert "stop" in ALL_HOOK_EVENTS

    def test_stop_is_str(self):
        assert isinstance(HookEvent.STOP, str)


class TestHookEventSessionEnd(TestCase):
    """HookEvent.SESSION_END enum tests (Issue #1007)."""

    def test_session_end_enum_exists(self):
        assert HookEvent.SESSION_END == "sessionend"

    def test_session_end_in_all_hook_events(self):
        assert "sessionend" in ALL_HOOK_EVENTS

    def test_post_compact_enum_exists(self):
        assert HookEvent.POST_COMPACT == "postcompact"

    def test_post_compact_in_all_hook_events(self):
        assert "postcompact" in ALL_HOOK_EVENTS


class TestClaudeCodeStopDetection(TestCase):
    """Claude Code adapter handles Stop event."""

    def test_can_handle_stop(self):
        assert BaseAgentAdapter.can_handle({"hook_event_name": "Stop"})

    def test_can_handle_session_end(self):
        assert BaseAgentAdapter.can_handle({"hook_event_name": "SessionEnd"})

    def test_can_handle_post_compact(self):
        assert BaseAgentAdapter.can_handle({"hook_event_name": "PostCompact"})

    def test_can_handle_still_handles_existing_events(self):
        assert BaseAgentAdapter.can_handle({"hook_event_name": "PreToolUse"})
        assert BaseAgentAdapter.can_handle({"hook_event_name": "PostToolUse"})
        assert BaseAgentAdapter.can_handle({"hook_event_name": "UserPromptSubmit"})

    def test_normalize_stop_event(self):
        adapter = BaseAgentAdapter()
        normalized = adapter.normalize_input(
            {
                "hook_event_name": "Stop",
                "session_id": "sess-123",
            }
        )
        assert normalized.event == HookEvent.STOP
        assert normalized.session_id == "sess-123"

    def test_normalize_session_end_event(self):
        adapter = BaseAgentAdapter()
        normalized = adapter.normalize_input(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "sess-456",
            }
        )
        assert normalized.event == HookEvent.SESSION_END
        assert normalized.session_id == "sess-456"

    def test_normalize_post_compact_event(self):
        adapter = BaseAgentAdapter()
        normalized = adapter.normalize_input(
            {
                "hook_event_name": "PostCompact",
                "session_id": "sess-789",
            }
        )
        assert normalized.event == HookEvent.POST_COMPACT
        assert normalized.session_id == "sess-789"


class TestClaudeCodeCamelCaseDetection(TestCase):
    """BaseAgentAdapter handles hookEventName (camelCase) sent by Claude Code (#1522)."""

    def test_can_handle_session_start_camel_case(self):
        assert BaseAgentAdapter.can_handle({"hookEventName": "SessionStart"})

    def test_can_handle_session_end_camel_case(self):
        assert BaseAgentAdapter.can_handle({"hookEventName": "SessionEnd"})

    def test_can_handle_stop_camel_case(self):
        assert BaseAgentAdapter.can_handle({"hookEventName": "Stop"})

    def test_can_handle_pre_tool_use_camel_case(self):
        assert BaseAgentAdapter.can_handle({"hookEventName": "PreToolUse"})

    def test_can_handle_post_tool_use_camel_case(self):
        assert BaseAgentAdapter.can_handle({"hookEventName": "PostToolUse"})

    def test_can_handle_user_prompt_submit_camel_case(self):
        assert BaseAgentAdapter.can_handle({"hookEventName": "UserPromptSubmit"})

    def test_normalize_session_start_camel_case(self):
        adapter = BaseAgentAdapter()
        normalized = adapter.normalize_input({"hookEventName": "SessionStart"})
        assert normalized.event == HookEvent.SESSION_START

    def test_normalize_session_end_camel_case(self):
        adapter = BaseAgentAdapter()
        normalized = adapter.normalize_input({"hookEventName": "SessionEnd"})
        assert normalized.event == HookEvent.SESSION_END

    def test_normalize_pre_tool_use_camel_case(self):
        adapter = BaseAgentAdapter()
        normalized = adapter.normalize_input({"hookEventName": "PreToolUse"})
        assert normalized.event == HookEvent.PRE_TOOL_USE


class TestEventDetection(TestCase):
    """_detect_event_from_all_formats maps stop/session-end events."""

    def test_stop_event(self):
        result = HookAdapter._detect_event_from_all_formats({"hook_event_name": "Stop"})
        assert result == HookEvent.STOP

    def test_session_idle_event(self):
        result = HookAdapter._detect_event_from_all_formats(
            {"hook_event_name": "session.idle"}
        )
        assert result == HookEvent.STOP

    def test_session_end_event_dot_format(self):
        result = HookAdapter._detect_event_from_all_formats(
            {"hook_event_name": "session.end"}
        )
        assert result == HookEvent.STOP

    def test_sessionend_event(self):
        result = HookAdapter._detect_event_from_all_formats(
            {"hook_event_name": "SessionEnd"}
        )
        assert result == HookEvent.SESSION_END

    def test_postcompact_event(self):
        result = HookAdapter._detect_event_from_all_formats(
            {"hook_event_name": "PostCompact"}
        )
        assert result == HookEvent.POST_COMPACT

    def test_existing_events_unchanged(self):
        assert (
            HookAdapter._detect_event_from_all_formats(
                {"hook_event_name": "UserPromptSubmit"}
            )
            == HookEvent.PROMPT
        )
        assert (
            HookAdapter._detect_event_from_all_formats(
                {"hook_event_name": "PreToolUse"}
            )
            == HookEvent.PRE_TOOL_USE
        )
        assert (
            HookAdapter._detect_event_from_all_formats(
                {"hook_event_name": "PostToolUse"}
            )
            == HookEvent.POST_TOOL_USE
        )

    def test_session_start_camel_case(self):
        result = HookAdapter._detect_event_from_all_formats(
            {"hookEventName": "SessionStart"}
        )
        assert result == HookEvent.SESSION_START

    def test_session_end_camel_case(self):
        result = HookAdapter._detect_event_from_all_formats(
            {"hookEventName": "SessionEnd"}
        )
        assert result == HookEvent.SESSION_END

    def test_stop_camel_case(self):
        result = HookAdapter._detect_event_from_all_formats({"hookEventName": "Stop"})
        assert result == HookEvent.STOP

    def test_pre_tool_use_camel_case(self):
        result = HookAdapter._detect_event_from_all_formats(
            {"hookEventName": "PreToolUse"}
        )
        assert result == HookEvent.PRE_TOOL_USE


class TestProcessHookDataStop(TestCase):
    """process_hook_data handles Stop event as no-op (Issue #1007)."""

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_stop_returns_allow(self, mock_pattern_config, mock_redaction_config):
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        from ai_guardian.hook_processing import process_hook_data

        result = process_hook_data(
            {
                "hook_event_name": "Stop",
                "session_id": "test-session-123",
            }
        )

        assert result["exit_code"] == 0
        assert result["output"] is None

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_stop_without_session_id(self, mock_pattern_config, mock_redaction_config):
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        from ai_guardian.hook_processing import process_hook_data

        result = process_hook_data({"hook_event_name": "Stop"})

        assert result["exit_code"] == 0
        assert result["output"] is None

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.hook_events.session_events._advance_transcript_position")
    def test_stop_does_not_call_session_cleanup(
        self, mock_advance, mock_pattern_config, mock_redaction_config
    ):
        """Stop is per-turn — must NOT clean up session state (#1007)."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        from ai_guardian.hook_processing import process_hook_data

        result = process_hook_data(
            {
                "hook_event_name": "Stop",
                "session_id": "test-session-123",
            }
        )

        assert result["exit_code"] == 0
        assert result["output"] is None
        mock_advance.assert_not_called()

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_stop_with_opencode_session_end(
        self, mock_pattern_config, mock_redaction_config
    ):
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        from ai_guardian.hook_processing import process_hook_data

        result = process_hook_data(
            {
                "hook_event_name": "session.end",
                "opencode_version": "1.0.0",
                "hook_source": "opencode",
                "session_id": "oc-session-456",
            }
        )

        assert result["exit_code"] == 0
        assert result["output"] is None


class TestProcessHookDataSessionEnd(TestCase):
    """process_hook_data handles SessionEnd event with cleanup (Issue #1007)."""

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.hook_events.session_events._advance_transcript_position")
    def test_session_end_calls_cleanup(
        self, mock_advance, mock_pattern_config, mock_redaction_config
    ):
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        from ai_guardian.hook_processing import process_hook_data

        hook_data = {
            "hook_event_name": "SessionEnd",
            "session_id": "test-session",
            "transcript_path": "/tmp/test-transcript.jsonl",
        }
        result = process_hook_data(hook_data)

        assert result["exit_code"] == 0
        mock_advance.assert_called_once_with(hook_data)

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch(
        "ai_guardian.hook_events.session_events._advance_transcript_position",
        side_effect=OSError("disk full"),
    )
    def test_session_end_fail_open_on_error(
        self, mock_advance, mock_pattern_config, mock_redaction_config
    ):
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        from ai_guardian.hook_processing import process_hook_data

        result = process_hook_data(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "test-session",
            }
        )

        assert result["exit_code"] == 0


class TestProcessHookDataPostCompact(TestCase):
    """process_hook_data handles PostCompact event (Issue #1007)."""

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_post_compact_returns_allow(
        self, mock_pattern_config, mock_redaction_config
    ):
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        from ai_guardian.hook_processing import process_hook_data

        result = process_hook_data(
            {
                "hook_event_name": "PostCompact",
                "session_id": "test-session-123",
            }
        )

        assert result["exit_code"] == 0
        assert result["output"] is None


class TestCodexLifecycleEvents(TestCase):
    """Codex lifecycle events are installed but not treated as content hooks."""

    @patch("ai_guardian.hook_processing._handle_bootstrap_scan", return_value=None)
    def test_lifecycle_notifications_return_allow_without_scanning(
        self, mock_bootstrap
    ):
        from ai_guardian.hook_processing import process_hook_data

        for event_name in (
            "PreCompact",
            "Stop",
            "Interrupt",
            "SubagentStart",
            "SubagentStop",
        ):
            result = process_hook_data(
                {
                    "hook_event_name": event_name,
                    "model": "gpt-5-codex",
                    "session_id": "codex-session",
                }
            )
            assert result == {"output": None, "exit_code": 0}

        mock_bootstrap.assert_not_called()

    @patch("ai_guardian.hook_processing._handle_bootstrap_scan", return_value=None)
    @patch("ai_guardian.hook_processing._load_permissions_config")
    @patch("ai_guardian.hook_processing.ToolPolicyChecker")
    def test_permission_request_can_deny_with_codex_decision(
        self, mock_policy_class, mock_permissions, mock_bootstrap
    ):
        from ai_guardian.hook_processing import process_hook_data

        mock_permissions.return_value = ({"enabled": True}, None)
        checker = mock_policy_class.return_value
        checker.check_tool_allowed.return_value = (
            False,
            "Blocked by permission policy",
            "Bash",
        )
        checker.last_deny_action = "block"

        result = process_hook_data(
            {
                "hook_event_name": "PermissionRequest",
                "model": "gpt-5-codex",
                "permission_mode": "default",
                "tool_name": "Bash",
                "tool_input": {"command": "echo hello"},
            }
        )

        payload = json.loads(result["output"])
        assert payload["hookSpecificOutput"]["hookEventName"] == "PermissionRequest"
        assert payload["hookSpecificOutput"]["decision"]["behavior"] == "deny"
        assert result["_blocked"] is True
        mock_bootstrap.assert_called_once()

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_post_compact_flags_reinject(
        self, mock_pattern_config, mock_redaction_config
    ):
        """PostCompact must flag session for security re-injection (#1007)."""
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        from ai_guardian.hook_processing import process_hook_data
        from ai_guardian.session_state import SessionStateManager

        with patch.object(
            SessionStateManager, "mark_security_reinject"
        ) as mock_reinject:
            result = process_hook_data(
                {
                    "hook_event_name": "PostCompact",
                    "session_id": "compact-session-456",
                }
            )

            assert result["exit_code"] == 0
            mock_reinject.assert_called_once_with("compact-session-456")

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_post_compact_without_session_id(
        self, mock_pattern_config, mock_redaction_config
    ):
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        from ai_guardian.hook_processing import process_hook_data

        result = process_hook_data({"hook_event_name": "PostCompact"})

        assert result["exit_code"] == 0


class TestHandleSessionEnd(TestCase):
    """Direct tests for _handle_session_end function."""

    def test_basic_cleanup(self):
        from ai_guardian.hook_processing import _handle_session_end

        adapter = MagicMock()
        adapter.name = "TestAdapter"

        result = _handle_session_end(
            hook_data={"session_id": "s1"},
            daemon_state=None,
            session_id="s1",
            adapter=adapter,
        )

        assert result == {"output": None, "exit_code": 0}

    def test_cleanup_with_no_adapter(self):
        from ai_guardian.hook_processing import _handle_session_end

        result = _handle_session_end(
            hook_data={"session_id": "s1"},
            daemon_state=None,
            session_id="s1",
            adapter=None,
        )

        assert result == {"output": None, "exit_code": 0}

    def test_cleanup_with_no_session_id(self):
        from ai_guardian.hook_processing import _handle_session_end

        adapter = MagicMock()
        adapter.name = "TestAdapter"

        result = _handle_session_end(
            hook_data={},
            daemon_state=None,
            session_id=None,
            adapter=adapter,
        )

        assert result == {"output": None, "exit_code": 0}

    @patch("ai_guardian.hook_events.session_events._advance_transcript_position")
    def test_calls_advance_transcript(self, mock_advance):
        from ai_guardian.hook_processing import _handle_session_end

        hook_data = {"session_id": "s1", "transcript_path": "/tmp/t.jsonl"}
        _handle_session_end(hook_data, None, "s1", MagicMock(name="Test"))

        mock_advance.assert_called_once_with(hook_data)


class TestHookContextManagerCleanupSession(TestCase):
    """HookContextManager.cleanup_session tests."""

    def test_cleanup_session_daemon_mode(self):
        from ai_guardian.hook_context import HookContextManager

        daemon_state = MagicMock()
        daemon_state.cleanup_session_contexts.return_value = 3

        mgr = HookContextManager(session_id="sess-1", daemon_state=daemon_state)
        count = mgr.cleanup_session()

        assert count == 3
        daemon_state.cleanup_session_contexts.assert_called_once_with("sess-1")

    def test_cleanup_session_file_mode(self, tmp_path=None):
        from ai_guardian.hook_context import HookContextManager

        with patch("ai_guardian.hook_context.get_state_dir") as mock_dir:
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                mock_dir.return_value = Path(tmpdir)

                mgr = HookContextManager(session_id="test-session")
                mgr.save_pretool_context("tool-1", {"file_path": "/test.py"})

                assert mgr._context_file.exists()

                count = mgr.cleanup_session()

                assert count >= 1
                assert not mgr._context_file.exists()

    def test_cleanup_session_no_file(self):
        from ai_guardian.hook_context import HookContextManager

        with patch("ai_guardian.hook_context.get_state_dir") as mock_dir:
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                mock_dir.return_value = Path(tmpdir)

                mgr = HookContextManager(session_id="nonexistent")
                count = mgr.cleanup_session()

                assert count == 0

    def test_cleanup_session_no_session_id(self):
        from ai_guardian.hook_context import HookContextManager

        mgr = HookContextManager(session_id=None)
        count = mgr.cleanup_session()

        assert count == 0


class TestSessionStateManagerCleanupSession(TestCase):
    """SessionStateManager.cleanup_session tests."""

    def test_cleanup_session_daemon_mode(self):
        from ai_guardian.session_state import SessionStateManager

        daemon_state = MagicMock()

        mgr = SessionStateManager(daemon_state=daemon_state)
        mgr.cleanup_session("sess-key-1")

        daemon_state.cleanup_session_state.assert_called_once_with("sess-key-1")

    def test_cleanup_session_file_mode(self):
        from ai_guardian.session_state import SessionStateManager

        with patch("ai_guardian.session_state.get_state_dir") as mock_dir:
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                mock_dir.return_value = Path(tmpdir)

                mgr = SessionStateManager()

                mgr.mark_security_injected("sess-to-remove")
                mgr.mark_security_injected("sess-to-keep")

                mgr.cleanup_session("sess-to-remove")

                data = mgr._read_file()
                assert "sess-to-remove" not in data.get("sessions", {})
                assert "sess-to-keep" in data.get("sessions", {})

    def test_cleanup_session_empty_key(self):
        from ai_guardian.session_state import SessionStateManager

        mgr = SessionStateManager(daemon_state=MagicMock())
        mgr.cleanup_session("")


class TestBaseAgentAdapterSessionStartFormat(TestCase):
    """format_response for SESSION_START block mirrors PreToolUse pattern (#1526).

    Uses systemMessage (full message shown to user) + additionalContext (sanitized,
    no security tips for agent). reason is omitted — it renders separately in Claude
    Code's startup hook error UI causing a duplicate second message.
    """

    def _format(self, **kwargs):
        import json

        adapter = BaseAgentAdapter()
        result = adapter.format_response(**kwargs)
        return json.loads(result["output"])

    def test_block_has_system_message(self):
        resp = self._format(
            has_secrets=True,
            error_message="Secrets detected in bootstrap scan",
            hook_event=HookEvent.SESSION_START,
            violation_type="secret_detected",
        )
        assert resp.get("systemMessage") == "Secrets detected in bootstrap scan"

    def test_block_no_reason(self):
        """reason must be absent — it causes a duplicate display in Claude Code UI."""
        resp = self._format(
            has_secrets=True,
            error_message="Bootstrap error",
            hook_event=HookEvent.SESSION_START,
        )
        assert resp["decision"] == "block"
        assert "reason" not in resp

    def test_block_has_additional_context(self):
        resp = self._format(
            has_secrets=True,
            error_message="Bootstrap error",
            hook_event=HookEvent.SESSION_START,
            violation_type="secret_detected",
        )
        ctx = resp.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "ai-guardian" in ctx

    def test_block_hook_specific_output_event_name(self):
        resp = self._format(
            has_secrets=True,
            error_message="Bootstrap error",
            hook_event=HookEvent.SESSION_START,
        )
        assert resp["hookSpecificOutput"]["hookEventName"] == "SessionStart"

    def test_no_block_passthrough(self):
        """Non-blocking SESSION_START (warn/security_message) unchanged."""
        resp = self._format(
            has_secrets=False,
            hook_event=HookEvent.SESSION_START,
            security_message="Security context injected",
        )
        assert "decision" not in resp
        assert (
            resp["hookSpecificOutput"]["additionalContext"]
            == "Security context injected"
        )


class TestDaemonStateCleanupSession(TestCase):
    """DaemonState session cleanup methods."""

    def test_cleanup_session_contexts(self):
        from ai_guardian.daemon.state import DaemonState

        with patch(
            "ai_guardian.daemon.state.DaemonState._default_config_path",
            return_value=None,
        ):
            with patch("ai_guardian.daemon.state.DaemonState._load_sessions"):
                state = DaemonState.__new__(DaemonState)
                state._lock = __import__("threading").Lock()
                state._hook_contexts = {
                    "sess-1:tool-a": {"context": {}, "timestamp": time.monotonic()},
                    "sess-1:tool-b": {"context": {}, "timestamp": time.monotonic()},
                    "sess-2:tool-c": {"context": {}, "timestamp": time.monotonic()},
                }

                count = state.cleanup_session_contexts("sess-1")

                assert count == 2
                assert "sess-2:tool-c" in state._hook_contexts
                assert len(state._hook_contexts) == 1

    def test_cleanup_session_contexts_none(self):
        from ai_guardian.daemon.state import DaemonState

        with patch(
            "ai_guardian.daemon.state.DaemonState._default_config_path",
            return_value=None,
        ):
            with patch("ai_guardian.daemon.state.DaemonState._load_sessions"):
                state = DaemonState.__new__(DaemonState)
                state._lock = __import__("threading").Lock()
                state._hook_contexts = {}

                count = state.cleanup_session_contexts("nonexistent")

                assert count == 0

    def test_cleanup_session_contexts_empty_session_id(self):
        from ai_guardian.daemon.state import DaemonState

        with patch(
            "ai_guardian.daemon.state.DaemonState._default_config_path",
            return_value=None,
        ):
            with patch("ai_guardian.daemon.state.DaemonState._load_sessions"):
                state = DaemonState.__new__(DaemonState)
                state._lock = __import__("threading").Lock()
                state._hook_contexts = {
                    "a:b": {"context": {}, "timestamp": time.monotonic()}
                }

                count = state.cleanup_session_contexts("")

                assert count == 0
                assert len(state._hook_contexts) == 1

    def test_cleanup_session_state(self):
        from ai_guardian.daemon.state import DaemonState

        with patch(
            "ai_guardian.daemon.state.DaemonState._default_config_path",
            return_value=None,
        ):
            with patch("ai_guardian.daemon.state.DaemonState._load_sessions"):
                state = DaemonState.__new__(DaemonState)
                state._lock = __import__("threading").Lock()
                state._security_injected_sessions = {"sess-1", "sess-2"}
                state._security_reinject_sessions = {"sess-1"}
                state._session_last_activity = {
                    "sess-1": time.time(),
                    "sess-2": time.time(),
                }
                state._allowed_findings = {"sess-1": {"fp_a"}}
                state._sessions_dirty = False
                state._debounce_timer = None
                state._sessions_file = None

                state.cleanup_session_state("sess-1")

                assert "sess-1" not in state._security_injected_sessions
                assert "sess-1" not in state._security_reinject_sessions
                assert "sess-1" not in state._session_last_activity
                assert "sess-1" not in state._allowed_findings
                assert "sess-2" in state._security_injected_sessions
                assert "sess-2" in state._session_last_activity

    def test_cleanup_session_state_empty_key(self):
        from ai_guardian.daemon.state import DaemonState

        with patch(
            "ai_guardian.daemon.state.DaemonState._default_config_path",
            return_value=None,
        ):
            with patch("ai_guardian.daemon.state.DaemonState._load_sessions"):
                state = DaemonState.__new__(DaemonState)
                state._lock = __import__("threading").Lock()
                state._security_injected_sessions = {"sess-1"}
                state._security_reinject_sessions = set()
                state._session_last_activity = {}
                state._allowed_findings = {}
                state._sessions_dirty = False
                state._debounce_timer = None
                state._sessions_file = None

                state.cleanup_session_state("")

                assert "sess-1" in state._security_injected_sessions
