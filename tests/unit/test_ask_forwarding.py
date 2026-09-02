"""Tests for remote ask dialog forwarding (#1342).

Covers: PendingPrompt lifecycle, tray registration, REST endpoints,
tray forwarding cascade in ask_dialog, and tray prompt polling.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.daemon.state import DaemonState, PendingPrompt
from ai_guardian.tui.ask_dialog import (
    AskDecision,
    AskResult,
    AskViolationInfo,
    _map_fallback_to_decision,
    _serialize_violation,
    _show_via_tray_forwarding,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def daemon_state(tmp_path):
    return DaemonState(
        config_path=tmp_path / "ai-guardian.json",
        sessions_file=tmp_path / "sessions.json",
        pause_file=tmp_path / "daemon.paused",
    )


@pytest.fixture
def violation():
    return AskViolationInfo(
        violation_type="secret_detected",
        summary="AWS API key detected",
        matched_text="FAKE_SECRET_FOR_TESTING",
        config_section="scan_secrets",
        error_message="Secret Type: AWS Access Key ID",
        file_path="/app/main.py",
        line_number=42,
    )


# ---------------------------------------------------------------------------
# PendingPrompt lifecycle
# ---------------------------------------------------------------------------


class TestPendingPromptLifecycle:
    def test_queue_creates_prompt(self, daemon_state):
        pending = daemon_state.queue_prompt(
            {"violation_type": "secret_detected"}, "block", 300
        )
        assert isinstance(pending, PendingPrompt)
        assert pending.prompt_id == "prompt-1"
        assert pending.result is None
        assert not pending.decision_event.is_set()

    def test_queue_increments_counter(self, daemon_state):
        p1 = daemon_state.queue_prompt({}, "block", 300)
        p2 = daemon_state.queue_prompt({}, "block", 300)
        assert p1.prompt_id == "prompt-1"
        assert p2.prompt_id == "prompt-2"

    def test_resolve_sets_result_and_fires_event(self, daemon_state):
        pending = daemon_state.queue_prompt({}, "block", 300)
        decision = {"decision": "allow_once"}
        found = daemon_state.resolve_prompt(pending.prompt_id, decision)
        assert found is True
        assert pending.result == decision
        assert pending.decision_event.is_set()

    def test_resolve_unknown_prompt_returns_false(self, daemon_state):
        assert daemon_state.resolve_prompt("nonexistent", {}) is False

    def test_resolve_already_resolved_returns_false(self, daemon_state):
        pending = daemon_state.queue_prompt({}, "block", 300)
        daemon_state.resolve_prompt(pending.prompt_id, {"decision": "block"})
        assert (
            daemon_state.resolve_prompt(pending.prompt_id, {"decision": "allow_once"})
            is False
        )

    def test_wait_and_resolve_from_another_thread(self, daemon_state):
        pending = daemon_state.queue_prompt({"type": "test"}, "block", 10)
        decision = {"decision": "allow_always", "allowlist_pattern": "test.*"}

        def _resolve_later():
            time.sleep(0.05)
            daemon_state.resolve_prompt(pending.prompt_id, decision)

        t = threading.Thread(target=_resolve_later)
        t.start()
        resolved = pending.decision_event.wait(timeout=2.0)
        t.join()
        assert resolved is True
        assert pending.result == decision


# ---------------------------------------------------------------------------
# PendingPrompt timeout and cleanup
# ---------------------------------------------------------------------------


class TestPendingPromptTimeout:
    def test_get_pending_excludes_expired(self, daemon_state):
        pending = daemon_state.queue_prompt({}, "block", 0)
        pending.created_at = time.monotonic() - 1.0
        assert len(daemon_state.get_pending_prompts()) == 0

    def test_get_pending_includes_active(self, daemon_state):
        daemon_state.queue_prompt({"v": "test"}, "warn", 300)
        prompts = daemon_state.get_pending_prompts()
        assert len(prompts) == 1
        assert prompts[0]["violation"] == {"v": "test"}
        assert prompts[0]["fallback_action"] == "warn"

    def test_get_pending_excludes_resolved(self, daemon_state):
        pending = daemon_state.queue_prompt({}, "block", 300)
        daemon_state.resolve_prompt(pending.prompt_id, {"decision": "block"})
        assert len(daemon_state.get_pending_prompts()) == 0

    def test_cleanup_fires_events_on_expired(self, daemon_state):
        pending = daemon_state.queue_prompt({}, "block", 0)
        pending.created_at = time.monotonic() - 1.0
        daemon_state.cleanup_expired_prompts()
        assert pending.decision_event.is_set()
        assert pending.prompt_id not in daemon_state._pending_prompts

    def test_cleanup_preserves_active(self, daemon_state):
        pending = daemon_state.queue_prompt({}, "block", 300)
        daemon_state.cleanup_expired_prompts()
        assert not pending.decision_event.is_set()
        assert pending.prompt_id in daemon_state._pending_prompts


# ---------------------------------------------------------------------------
# Tray registration
# ---------------------------------------------------------------------------


class TestTrayRegistration:
    def test_register_and_check(self, daemon_state):
        assert not daemon_state.is_tray_registered()
        daemon_state.register_tray("host.docker.internal", 63152)
        assert daemon_state.is_tray_registered()

    def test_unregister(self, daemon_state):
        daemon_state.register_tray("host.docker.internal", 63152)
        daemon_state.unregister_tray()
        assert not daemon_state.is_tray_registered()

    def test_ttl_expiry(self, daemon_state):
        daemon_state._tray_registration_ttl = 0.01
        daemon_state.register_tray("host.docker.internal", 63152)
        time.sleep(0.02)
        assert not daemon_state.is_tray_registered()

    def test_re_registration_refreshes_ttl(self, daemon_state):
        daemon_state._tray_registration_ttl = 0.5
        daemon_state.register_tray("host.docker.internal", 63152)
        time.sleep(0.3)
        daemon_state.register_tray("host.docker.internal", 63152)
        time.sleep(0.3)
        assert daemon_state.is_tray_registered()


# ---------------------------------------------------------------------------
# Serialize violation
# ---------------------------------------------------------------------------


class TestSerializeViolation:
    def test_round_trip(self, violation):
        d = _serialize_violation(violation)
        assert d["violation_type"] == "secret_detected"
        assert d["summary"] == "AWS API key detected"
        assert d["file_path"] == "/app/main.py"
        assert d["line_number"] == 42
        assert d["start_column"] is None


# ---------------------------------------------------------------------------
# _show_via_tray_forwarding
# ---------------------------------------------------------------------------


class TestShowViaTrayForwarding:
    def test_returns_none_when_no_daemon_state(self, violation):
        with patch("ai_guardian.daemon.get_daemon_state", return_value=None):
            result = _show_via_tray_forwarding(violation)
        assert result is None

    def test_returns_none_when_no_tray_registered(self, violation, daemon_state):
        with patch("ai_guardian.daemon.get_daemon_state", return_value=daemon_state):
            result = _show_via_tray_forwarding(violation)
        assert result is None

    def test_returns_result_when_tray_resolves(self, violation, daemon_state):
        daemon_state.register_tray("host.docker.internal", 63152)

        def _resolve_in_background():
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                prompts = daemon_state.get_pending_prompts()
                if prompts:
                    daemon_state.resolve_prompt(
                        prompts[0]["prompt_id"],
                        {"decision": "allow_once"},
                    )
                    return
                time.sleep(0.01)

        t = threading.Thread(target=_resolve_in_background)
        t.start()

        with patch("ai_guardian.daemon.get_daemon_state", return_value=daemon_state):
            result = _show_via_tray_forwarding(violation, timeout_seconds=2)

        t.join()
        assert result is not None
        assert result.decision == AskDecision.ALLOW_ONCE

    def test_returns_none_on_timeout(self, violation, daemon_state):
        daemon_state.register_tray("host.docker.internal", 63152)
        with patch("ai_guardian.daemon.get_daemon_state", return_value=daemon_state):
            result = _show_via_tray_forwarding(violation, timeout_seconds=0.05)
        assert result is None

    def test_allow_always_with_pattern(self, violation, daemon_state):
        daemon_state.register_tray("host.docker.internal", 63152)

        def _resolve():
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                prompts = daemon_state.get_pending_prompts()
                if prompts:
                    daemon_state.resolve_prompt(
                        prompts[0]["prompt_id"],
                        {
                            "decision": "allow_always",
                            "allowlist_pattern": "FAKE_SECRET.*",
                            "config_saved": True,
                        },
                    )
                    return
                time.sleep(0.01)

        t = threading.Thread(target=_resolve)
        t.start()

        with patch("ai_guardian.daemon.get_daemon_state", return_value=daemon_state):
            result = _show_via_tray_forwarding(violation, timeout_seconds=2)

        t.join()
        assert result.decision == AskDecision.ALLOW_ALWAYS
        assert result.allowlist_pattern == "FAKE_SECRET.*"
        assert result.config_saved is True


# ---------------------------------------------------------------------------
# REST endpoint handlers (via DaemonState)
# ---------------------------------------------------------------------------


class TestRestEndpoints:
    def test_register_tray_endpoint(self, daemon_state):
        daemon_state.register_tray("10.0.0.1", 8080)
        assert daemon_state.is_tray_registered()
        assert daemon_state._registered_tray["host"] == "10.0.0.1"
        assert daemon_state._registered_tray["port"] == 8080

    def test_pending_prompts_endpoint(self, daemon_state):
        daemon_state.queue_prompt({"type": "secret"}, "block", 300)
        daemon_state.queue_prompt({"type": "pii"}, "warn", 300)
        prompts = daemon_state.get_pending_prompts()
        assert len(prompts) == 2
        assert prompts[0]["prompt_id"] == "prompt-1"
        assert prompts[1]["prompt_id"] == "prompt-2"

    def test_prompt_decision_endpoint(self, daemon_state):
        pending = daemon_state.queue_prompt({}, "block", 300)
        found = daemon_state.resolve_prompt(pending.prompt_id, {"decision": "block"})
        assert found is True
        assert pending.result["decision"] == "block"


# ---------------------------------------------------------------------------
# cleanup_expired_contexts calls cleanup_expired_prompts
# ---------------------------------------------------------------------------


class TestCleanupIntegration:
    def test_cleanup_expired_contexts_also_cleans_prompts(self, daemon_state):
        pending = daemon_state.queue_prompt({}, "block", 0)
        pending.created_at = time.monotonic() - 1.0
        daemon_state.cleanup_expired_contexts()
        assert pending.decision_event.is_set()


# ---------------------------------------------------------------------------
# Tray polling (_handle_remote_prompt)
# ---------------------------------------------------------------------------


class TestTrayPolling:
    def test_handle_remote_prompt_skips_in_flight(self):
        from ai_guardian.tray.app import DaemonTray

        tray = DaemonTray.__new__(DaemonTray)
        tray._in_flight_prompts = {"prompt-1"}
        tray._multi_client = MagicMock()

        target = MagicMock()
        prompt_data = {"prompt_id": "prompt-1", "violation": {}}
        tray._handle_remote_prompt(target, prompt_data)
        tray._multi_client.send_prompt_decision.assert_not_called()

    def test_handle_remote_prompt_skips_no_id(self):
        from ai_guardian.tray.app import DaemonTray

        tray = DaemonTray.__new__(DaemonTray)
        tray._in_flight_prompts = set()
        tray._multi_client = MagicMock()

        target = MagicMock()
        tray._handle_remote_prompt(target, {"violation": {}})
        tray._multi_client.send_prompt_decision.assert_not_called()

    def test_poll_remote_prompts_iterates_remote_targets(self):
        from ai_guardian.tray.app import DaemonTray

        tray = DaemonTray.__new__(DaemonTray)
        tray._in_flight_prompts = set()
        tray._multi_client = MagicMock()
        tray._multi_client.get_pending_prompts.return_value = []

        local_target = MagicMock()
        local_target.runtime = "local"
        local_target.status = "running"

        remote_target = MagicMock()
        remote_target.runtime = "container"
        remote_target.status = "running"

        tray._targets = [local_target, remote_target]
        tray._poll_remote_prompts()
        tray._multi_client.get_pending_prompts.assert_called_once_with(remote_target)

    def test_register_tray_with_remotes(self):
        from ai_guardian.tray.app import DaemonTray

        tray = DaemonTray.__new__(DaemonTray)
        tray._multi_client = MagicMock()

        local_target = MagicMock()
        local_target.runtime = "local"
        local_target.status = "running"

        remote_target = MagicMock()
        remote_target.runtime = "container"
        remote_target.status = "running"

        tray._targets = [local_target, remote_target]
        with patch.object(DaemonTray, "_get_local_daemon_port", return_value=63152):
            tray._register_tray_with_remotes()
        tray._multi_client.register_tray.assert_called_once_with(
            remote_target, "host.docker.internal", 63152
        )


# ---------------------------------------------------------------------------
# DaemonState accessor
# ---------------------------------------------------------------------------


class TestDaemonStateAccessor:
    def test_set_and_get(self):
        from ai_guardian.daemon import get_daemon_state, set_daemon_state

        original = get_daemon_state()
        try:
            mock_state = MagicMock()
            set_daemon_state(mock_state)
            assert get_daemon_state() is mock_state
        finally:
            set_daemon_state(original)

    def test_default_is_none(self):
        from ai_guardian.daemon import get_daemon_state, set_daemon_state

        original = get_daemon_state()
        try:
            set_daemon_state(None)
            assert get_daemon_state() is None
        finally:
            set_daemon_state(original)
