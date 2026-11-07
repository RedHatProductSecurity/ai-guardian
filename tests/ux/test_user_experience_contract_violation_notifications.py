"""UX contract for per-type privacy-safe violation alerts (#2672).

Scenario:
1. A user independently selects desktop and email alerts for each violation type.
2. Email controls remain unavailable until the recipient and TLS SMTP transport are
   ready; desktop controls remain available.
3. A daemon alerts with only a fixed category, severity and daemon identity.
4. For a remote daemon, local fallback uses the same preference for that exact type.

Expected experience:
- Missing type preferences default to desktop on and email off.
- There is no global notification-enable control; each type has two independent
  channel preferences.
- Legacy global disable migrates to all types disabled; legacy channels become
  defaults for types without explicit preferences.
- Email has a separate alert recipient and requires usable TLS SMTP settings.
- Neither channel includes secrets, PII, prompts, commands, paths or scan content.
- Remote attribution identifies the originating daemon, and an ambiguous send is
  not retried locally.

Manual verification:
1. Open the daemon's Violation Logging page and confirm the distinct global
   Violation Notifications card has one row per violation type and the privacy
   explanation; there is no master switch.
2. Toggle desktop preferences independently and confirm violation history settings
   are unchanged.
3. Without valid TLS SMTP settings, confirm email switches are disabled and cannot
   be enabled through a preference save. Configure the recipient and SMTP settings
   and confirm the email switches become available.
4. Open a legacy config with notifications disabled and save one per-type setting;
   confirm all other types stay disabled.
5. Hover the (?) beside **Alert email recipient** and confirm it points to global
   `support.email` SMTP settings, lists TLS ports, and rejects plaintext SMTP.
6. Configure a TLS SMTP host and alert recipient, generate a synthetic violation,
   and verify only category, severity and daemon identity arrive in the message.
7. Generate one violation on a paired remote daemon. Confirm its selected channel
   sends once; make that channel fail and confirm local fallback occurs once.
   Confirm a remotely delivered or uncertain channel does not produce a duplicate.
8. With the daemon unavailable, trigger a direct-mode hook violation. Confirm the
   hook returns without waiting for delivery, the privacy-safe event is committed
   to the outbox before exit, and the detached worker sends the configured alert.
"""

import inspect
from concurrent.futures import ThreadPoolExecutor
import copy
import threading

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.violations.notifications import (
    VIOLATION_NOTIFICATION_TYPES,
    ViolationNotificationService,
    get_notification_preferences,
)
from ai_guardian.web.pages import violation_logging


def test_fresh_configuration_defaults_to_desktop_only_alerts():
    """USER EXPERIENCE: fresh installs alert without opting into email."""
    from ai_guardian.setup.config import _get_default_config_template

    config = _get_default_config_template(permissive=False)
    assert config["violation_notifications"] == {
        "by_type": {},
        "email": {"recipient": ""},
    }
    preferences = get_notification_preferences(config["violation_notifications"])
    assert set(preferences) == set(VIOLATION_NOTIFICATION_TYPES)
    assert all(
        values == {"desktop": True, "email": False} for values in preferences.values()
    )


def test_console_explains_independent_privacy_safe_channel_controls():
    """USER EXPERIENCE: users can control each alert channel explicitly."""
    page_source = inspect.getsource(violation_logging.create_violation_logging_page)
    save_source = inspect.getsource(violation_logging._save_notification_config)

    assert '"Violation Notifications"' in page_source
    assert '"Enable violation notifications"' not in page_source
    assert '"Desktop"' in page_source
    assert '"Email"' in page_source
    assert "notification_preferences[violation_type]" in page_source
    assert "email_switch.disable()" in page_source
    assert "desktop_switch.disable()" not in page_source
    assert "notification_email_ready" in page_source
    assert '"Alert email recipient"' in page_source
    assert 'field_help_icon("violation_notifications.email.recipient")' in page_source
    assert "independent of violation logging and detection" in page_source
    assert "detected values and scanned content are never included" in page_source
    assert "TLS SMTP settings" in page_source
    assert 'notifications.pop("enabled", None)' in save_source
    assert 'notifications.pop("channels", None)' in save_source
    assert "load_web_config_global()" in save_source
    assert 'scope="global"' in save_source
    assert 'config["support"]' not in save_source

    recipient_source = page_source.split("async def save_alert_recipient", 1)[1].split(
        'recipient_input.on("blur", save_alert_recipient)', 1
    )[0]
    assert recipient_source.rstrip().splitlines()[-1].strip() == "await refresh()"


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
            "by_type": {"secret_detected": {"desktop": False}},
            "email": {"recipient": "alerts@example.org"},
        }
    )

    assert saved["scope"] == "global"
    assert saved["config"]["violation_logging"] == {
        "enabled": True,
        "max_entries": 100,
    }
    assert saved["config"]["support"] == {"email": {"to": "support@example.org"}}
    saved_notifications = saved["config"]["violation_notifications"]
    assert "enabled" not in saved_notifications
    assert "channels" not in saved_notifications
    assert saved_notifications["email"] == {"recipient": "alerts@example.org"}
    preferences = get_notification_preferences(saved_notifications)
    assert preferences["secret_detected"] == {"desktop": False, "email": False}
    assert preferences["prompt_injection"] == {"desktop": True, "email": False}
    assert set(saved_notifications["by_type"]) == set(VIOLATION_NOTIFICATION_TYPES)


def test_rapid_channel_changes_do_not_overwrite_each_other(monkeypatch):
    """USER EXPERIENCE: quick independent changes persist together."""
    state = {
        "config": {
            "violation_notifications": {
                "by_type": {},
                "email": {"recipient": "alerts@example.org"},
            },
            "support": {
                "email": {
                    "smtp_host": "smtp.example.org",
                    "smtp_port": 587,
                    "smtp_tls": True,
                    "auth": {"method": "none"},
                }
            },
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
                violation_logging._save_notification_config,
                {"by_type": {"secret_detected": {"desktop": False}}},
            ),
            executor.submit(
                violation_logging._save_notification_config,
                {"by_type": {"prompt_injection": {"email": True}}},
            ),
        ]
        assert all(future.result() for future in futures)

    preferences = get_notification_preferences(
        state["config"]["violation_notifications"]
    )
    assert preferences["secret_detected"] == {"desktop": False, "email": False}
    assert preferences["prompt_injection"] == {"desktop": True, "email": True}


def test_legacy_disabled_setting_migrates_without_reenabling_other_types(monkeypatch):
    """USER EXPERIENCE: a Console save preserves a previous global opt-out."""
    config = {
        "violation_notifications": {
            "enabled": False,
            "channels": {"desktop": True, "email": True},
            "email": {"recipient": "alerts@example.org"},
        }
    }
    saved = {}
    monkeypatch.setattr(
        "ai_guardian.web.config_helpers.load_web_config_global", lambda: config
    )
    monkeypatch.setattr(
        "ai_guardian.web.config_helpers.save_web_config",
        lambda updated, *, scope=None: saved.update(config=updated, scope=scope)
        or True,
    )

    assert violation_logging._save_notification_config(
        {"by_type": {"secret_detected": {"desktop": True}}}
    )

    notifications = saved["config"]["violation_notifications"]
    preferences = get_notification_preferences(notifications)
    assert saved["scope"] == "global"
    assert "enabled" not in notifications
    assert "channels" not in notifications
    assert preferences["secret_detected"] == {"desktop": True, "email": False}
    assert preferences["prompt_injection"] == {"desktop": False, "email": False}


def test_email_preferences_cannot_be_saved_without_ready_tls_smtp(monkeypatch):
    """USER EXPERIENCE: server-side saves enforce the disabled UI state."""
    config = {
        "violation_notifications": {
            "by_type": {},
            "email": {"recipient": ""},
        },
        "support": {"email": {"smtp_host": "", "smtp_tls": True}},
    }
    saves = []
    monkeypatch.setattr(
        "ai_guardian.web.config_helpers.load_web_config_global", lambda: config
    )
    monkeypatch.setattr(
        "ai_guardian.web.config_helpers.save_web_config",
        lambda updated, *, scope=None: saves.append((updated, scope)) or True,
    )

    assert not violation_logging._save_notification_config(
        {"by_type": {"secret_detected": {"email": True}}}
    )
    assert saves == []

    config["violation_notifications"]["email"]["recipient"] = "alerts@example.org"
    config["support"]["email"] = {
        "smtp_host": "smtp.example.org",
        "smtp_port": 587,
        "smtp_tls": False,
        "auth": {"method": "none"},
    }
    assert not violation_logging._save_notification_config(
        {"by_type": {"secret_detected": {"email": True}}}
    )
    assert saves == []

    config["support"]["email"]["smtp_tls"] = True
    assert violation_logging._save_notification_config(
        {"by_type": {"secret_detected": {"email": True}}}
    )
    assert len(saves) == 1
    assert (
        saves[0][0]["violation_notifications"]["by_type"]["secret_detected"]["email"]
        is True
    )


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
        "violation_type": "secret_detected",
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
