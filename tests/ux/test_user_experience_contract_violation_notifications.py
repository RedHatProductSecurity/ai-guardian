"""UX contract for privacy-safe local and remote violation alerts (#2634).

Scenario:
1. A user selects desktop alerts, email alerts, or both independently of history.
2. A daemon alerts with only a fixed category, severity and daemon identity.
3. For a remote daemon, the local tray relays only channels not confirmed delivered
   by the source; retries must not create duplicate local sends.

Expected experience:
- Fresh setup enables notifications and desktop alerts, with email opt-in.
- Turning notifications off does not turn off violation logging or detection.
- Email has a separate alert recipient and requires configured TLS SMTP.
- Neither channel includes secrets, PII, prompts, commands, paths or scan content.
- Remote attribution identifies the originating daemon, and an ambiguous send is
  not retried locally.

Manual verification:
1. Open the daemon's Violation Logging page and confirm the distinct global
   Violation Notifications card and privacy explanation.
2. Turn the master switch off and confirm history logging remains unchanged; then
   re-enable it and independently toggle desktop/email.
3. Hover the (?) beside **Alert email recipient** and confirm it points to global
   `support.email` SMTP settings, lists TLS ports, and rejects plaintext SMTP.
4. Configure a TLS SMTP host and alert recipient, generate a synthetic violation,
   and verify only category, severity and daemon identity arrive in the message.
5. Generate one violation on a paired remote daemon. Confirm its selected channel
   sends once; make that channel fail and confirm local fallback occurs once.
   Confirm a remotely delivered or uncertain channel does not produce a duplicate.
"""

import inspect
from concurrent.futures import ThreadPoolExecutor
import copy
import threading

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.violations.notifications import ViolationNotificationService
from ai_guardian.web.pages import violation_logging


def test_fresh_configuration_defaults_to_desktop_only_alerts():
    """USER EXPERIENCE: fresh installs alert without opting into email."""
    from ai_guardian.setup.config import _get_default_config_template

    config = _get_default_config_template(permissive=False)
    assert config["violation_notifications"] == {
        "enabled": True,
        "channels": {"desktop": True, "email": False},
        "email": {"recipient": ""},
    }


def test_console_explains_independent_privacy_safe_channel_controls():
    """USER EXPERIENCE: users can control each alert channel explicitly."""
    page_source = inspect.getsource(violation_logging.create_violation_logging_page)
    save_source = inspect.getsource(violation_logging._save_notification_config)

    assert '"Violation Notifications"' in page_source
    assert '"Enable violation notifications"' in page_source
    assert '"OS desktop notifications"' in page_source
    assert '"Email notifications"' in page_source
    assert '"Alert email recipient"' in page_source
    assert 'field_help_icon("violation_notifications.email.recipient")' in page_source
    assert "independent of violation logging and detection" in page_source
    assert "detected values and scanned content are never included" in page_source
    assert "TLS SMTP settings" in page_source
    assert "load_web_config_global()" in save_source
    assert 'scope="global"' in save_source
    assert '"support"' not in save_source


def test_notification_preferences_preserve_history_and_support_settings(monkeypatch):
    """USER EXPERIENCE: alert saves do not mutate logging or support recipients."""
    config = {
        "violation_logging": {"enabled": True, "max_entries": 100},
        "support": {"email": {"to": "support@example.org"}},
        "violation_notifications": {
            "enabled": True,
            "channels": {"desktop": True, "email": False},
            "email": {"recipient": ""},
        },
    }
    saved = {}
    monkeypatch.setattr(
        "ai_guardian.web.config_helpers.load_web_config_global",
        lambda: config,
    )

    def capture_save(updated, *, scope=None):
        saved["config"] = updated
        saved["scope"] = scope
        return True

    monkeypatch.setattr("ai_guardian.web.config_helpers.save_web_config", capture_save)

    assert violation_logging._save_notification_config(
        {
            "enabled": False,
            "channels": {"email": True},
            "email": {"recipient": "alerts@example.org"},
        }
    )

    assert saved["scope"] == "global"
    assert saved["config"]["violation_logging"] == {
        "enabled": True,
        "max_entries": 100,
    }
    assert saved["config"]["support"] == {"email": {"to": "support@example.org"}}
    assert saved["config"]["violation_notifications"] == {
        "enabled": False,
        "channels": {"desktop": True, "email": True},
        "email": {"recipient": "alerts@example.org"},
    }


def test_rapid_channel_changes_do_not_overwrite_each_other(monkeypatch):
    """USER EXPERIENCE: quick independent changes persist together."""
    state = {
        "config": {
            "violation_notifications": {
                "enabled": True,
                "channels": {"desktop": True, "email": False},
                "email": {"recipient": ""},
            }
        }
    }
    state_lock = threading.Lock()
    two_reads = threading.Event()
    reads = 0

    def load_config():
        nonlocal reads
        with state_lock:
            snapshot = copy.deepcopy(state["config"])
            reads += 1
            if reads == 2:
                two_reads.set()
        two_reads.wait(timeout=0.05)
        return snapshot

    def save_config(config, *, scope=None):
        assert scope == "global"
        with state_lock:
            state["config"] = copy.deepcopy(config)
        return True

    monkeypatch.setattr(
        "ai_guardian.web.config_helpers.load_web_config_global", load_config
    )
    monkeypatch.setattr("ai_guardian.web.config_helpers.save_web_config", save_config)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                violation_logging._save_notification_config, {"enabled": False}
            ),
            executor.submit(
                violation_logging._save_notification_config,
                {"channels": {"email": True}},
            ),
        ]
        assert all(future.result() for future in futures)

    assert state["config"]["violation_notifications"] == {
        "enabled": False,
        "channels": {"desktop": True, "email": True},
        "email": {"recipient": ""},
    }


def test_alert_summary_has_no_raw_finding_or_tool_fields():
    """USER EXPERIENCE: the delivered envelope is safe to show outside the daemon."""
    service = ViolationNotificationService(
        {"enabled": False}, daemon_name="source-daemon", background=False
    )
    event = service._make_event(
        "viol_0123456789abcdef",
        "secret_detected",
        "high",
        "source-daemon",
        "2026-11-02T12:00:00Z",
    )

    assert event == {
        "id": "viol_0123456789abcdef",
        "timestamp": "2026-11-02T12:00:00Z",
        "category": "Sensitive finding",
        "severity": "high",
        "source_daemon": "source-daemon",
    }
    assert not {"blocked", "context", "suggestion", "path", "command"} & event.keys()
    assert "secret value" not in repr(event)


def test_tray_relays_remote_events_and_uses_bounded_notification_projection():
    """USER EXPERIENCE: remote alerts use source status and safe event summaries."""
    from ai_guardian.daemon import notification_relay
    from ai_guardian.tray import app

    relay_source = inspect.getsource(
        notification_relay.relay_remote_violation_notifications
    )
    poll_source = inspect.getsource(app.DaemonTray._start_remote_violation_mirror_poll)
    projection_source = inspect.getsource(
        ViolationNotificationService.relay_remote_event
    )

    assert '"notification_events"' in relay_source
    assert "is_mirrored_violation(record)" in relay_source
    assert "relay_remote_violation_notifications" in poll_source
    assert '"pending"' in projection_source
    assert '"delivered"' in projection_source
    assert '"uncertain"' in projection_source
    assert "source_daemon" in projection_source
    assert "blocked" not in projection_source
