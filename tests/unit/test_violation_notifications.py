"""Unit tests for private, at-most-once violation notification delivery."""

from unittest.mock import Mock
from concurrent.futures import ThreadPoolExecutor
import queue
from datetime import datetime, timezone

import pytest

from ai_guardian.violations import notifications
from ai_guardian.violations.notifications import (
    NotificationStore,
    ViolationNotificationService,
    safe_event_id,
)


def _service(
    path,
    *,
    settings=None,
    smtp=None,
    desktop_sender=None,
    background=False,
    daemon_name=None,
):
    return ViolationNotificationService(
        settings
        or {
            "enabled": True,
            "channels": {"desktop": True, "email": False},
            "email": {"recipient": ""},
        },
        smtp or {},
        store=NotificationStore(path),
        desktop_sender=desktop_sender,
        background=background,
        daemon_name=daemon_name or "local-daemon",
    )


def test_local_alert_is_minimal_and_independent_of_history_storage(tmp_path):
    sent = []
    service = _service(
        tmp_path / "notifications.sqlite3",
        desktop_sender=lambda title, message: sent.append((title, message)) or True,
    )

    event_id = service.notify_local(
        "secret_detected", "critical", "viol_0123456789abcdef"
    )

    assert event_id == "viol_0123456789abcdef"
    assert sent == [
        (
            "AI Guardian violation: Sensitive finding",
            "Severity: critical\nOriginating daemon: local-daemon",
        )
    ]
    event = service.store.recent_local_events()[0]
    assert event == {
        "id": "viol_0123456789abcdef",
        "timestamp": event["timestamp"],
        "category": "Sensitive finding",
        "severity": "critical",
        "source_daemon": "local-daemon",
        "delivery": {"desktop": "delivered", "email": "not_configured"},
    }
    assert "blocked" not in event
    assert "context" not in event
    assert "scanned content" not in repr(event)


def test_local_retry_does_not_send_same_channel_twice(tmp_path):
    send = Mock(return_value=True)
    service = _service(tmp_path / "notifications.sqlite3", desktop_sender=send)
    event_id = "viol_abcdef0123456789"

    service.notify_local("tool_permission", "high", event_id)
    service.notify_local("tool_permission", "high", event_id)

    send.assert_called_once()
    assert len(service.store.recent_local_events()) == 1


def test_notification_outbox_prunes_expired_events_on_read(tmp_path):
    service = _service(
        tmp_path / "notifications.sqlite3",
        settings={"enabled": False},
    )
    service.notify_local("tool_permission", "warning", "viol_abcdef0123456789")
    connection = service.store._connect()
    try:
        connection.execute(
            "UPDATE notification_events SET created_at = 0 WHERE event_id = ?",
            ("viol_abcdef0123456789",),
        )
        connection.commit()
    finally:
        connection.close()

    assert service.store.recent_local_events() == []


def test_violation_alert_invocation_is_independent_of_history_logging(
    tmp_path, monkeypatch
):
    from ai_guardian.violations.logger import ViolationLogger

    notify = Mock()
    monkeypatch.setattr(ViolationLogger, "_notify_violation", notify)
    logger = ViolationLogger(
        log_path=tmp_path / "violations.jsonl",
        config={"enabled": False, "log_types": []},
    )

    logger.log_violation(
        "prompt_injection",
        blocked={},
        context={},
        violation_id="viol_abcdef0123456789",
    )

    notify.assert_called_once_with(
        "prompt_injection", "warning", "viol_abcdef0123456789"
    )
    assert not (tmp_path / "violations.jsonl").exists()


def test_remote_success_suppresses_local_duplicate(tmp_path):
    event_id = "viol_0123456789abcdef"
    remote = _service(
        tmp_path / "remote.sqlite3",
        desktop_sender=lambda *_args: True,
        daemon_name="remote-daemon",
    )
    remote.notify_local("directory_blocking", "high", event_id)
    remote_event = remote.store.recent_local_events()[0]

    local_send = Mock(return_value=True)
    local = _service(tmp_path / "local.sqlite3", desktop_sender=local_send)
    assert local.relay_remote_event("a" * 64, remote_event) is False
    assert local.relay_remote_event("a" * 64, remote_event) is False
    local_send.assert_not_called()


def test_remote_failure_falls_back_locally_once(tmp_path):
    event_id = "viol_0123456789abcdef"
    remote = _service(
        tmp_path / "remote.sqlite3",
        desktop_sender=lambda *_args: False,
        daemon_name="remote-daemon",
    )
    remote.notify_local("prompt_injection", "high", event_id)
    remote_event = remote.store.recent_local_events()[0]
    assert remote_event["delivery"]["desktop"] == "failed"

    local_send = Mock(return_value=True)
    local = _service(tmp_path / "local.sqlite3", desktop_sender=local_send)
    assert local.relay_remote_event("b" * 64, remote_event) is True
    assert local.relay_remote_event("b" * 64, remote_event) is False
    local_send.assert_called_once_with(
        "AI Guardian violation: Prompt injection",
        "Severity: high\nOriginating daemon: remote-daemon",
    )


def test_concurrent_remote_retries_claim_only_one_local_delivery(tmp_path):
    send = Mock(return_value=True)
    service = _service(tmp_path / "local.sqlite3", desktop_sender=send)
    event = {
        "id": "viol_0123456789abcdef",
        "timestamp": "2026-11-02T12:00:00Z",
        "category": "Tool permission",
        "severity": "high",
        "source_daemon": "remote-daemon",
        "delivery": {"desktop": "failed", "email": "not_configured"},
    }

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _index: service.relay_remote_event("d" * 64, event),
                range(8),
            )
        )

    assert results.count(True) == 1
    send.assert_called_once()


def test_pending_remote_send_waits_then_falls_back_only_on_known_failure(tmp_path):
    local_send = Mock(return_value=True)
    local = _service(tmp_path / "local.sqlite3", desktop_sender=local_send)
    event = {
        "id": "viol_0123456789abcdef",
        "timestamp": "2026-11-02T12:00:00Z",
        "category": "SSRF blocked",
        "severity": "high",
        "source_daemon": "remote-daemon",
        "delivery": {"desktop": "pending", "email": "not_configured"},
    }

    assert local.relay_remote_event("c" * 64, event) is False
    local_send.assert_not_called()

    event["delivery"]["desktop"] = "failed"
    assert local.relay_remote_event("c" * 64, event) is True
    local_send.assert_called_once()


def test_email_uses_separate_recipient_and_tls_transport(tmp_path, monkeypatch):
    email_sender = Mock(return_value="delivered")
    monkeypatch.setattr(notifications, "_send_email_notification", email_sender)
    smtp = {
        "smtp_host": "mail.example.org",
        "smtp_port": 587,
        "smtp_tls": True,
        "auth": {"method": "none"},
    }
    service = _service(
        tmp_path / "notifications.sqlite3",
        settings={
            "enabled": True,
            "channels": {"desktop": False, "email": True},
            "email": {"recipient": "alerts@example.org"},
        },
        smtp=smtp,
    )

    service.notify_local("ssrf_blocked", "critical", "viol_0123456789abcdef")

    event = email_sender.call_args.args[0]
    assert event["category"] == "SSRF blocked"
    assert event["severity"] == "critical"
    assert event["source_daemon"] == "local-daemon"
    assert email_sender.call_args.args[1] is smtp
    assert email_sender.call_args.args[2] == "alerts@example.org"
    assert service.store.recent_local_events()[0]["delivery"]["email"] == "delivered"


def test_smtp_email_contains_only_the_safe_envelope_and_uses_starttls(monkeypatch):
    from email.message import EmailMessage

    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))

        def starttls(self, context):
            calls.append(("starttls", context.verify_mode, context.check_hostname))

        def send_message(self, message):
            assert isinstance(message, EmailMessage)
            calls.append(("send", message))
            return {}

        def quit(self):
            calls.append(("quit",))

    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    event = {
        "id": "viol_0123456789abcdef",
        "timestamp": "2026-11-02T12:00:00Z",
        "category": "Sensitive finding",
        "severity": "critical",
        "source_daemon": "remote-daemon",
    }
    settings = {
        "smtp_host": "mail.example.org",
        "smtp_port": 587,
        "smtp_tls": True,
        "auth": {"method": "none"},
    }

    assert (
        notifications._send_email_notification(event, settings, "alerts@example.org")
        == "delivered"
    )

    assert calls[0] == ("connect", "mail.example.org", 587, 10)
    assert calls[1][0] == "starttls"
    assert calls[1][1:] == (notifications.ssl.CERT_REQUIRED, True)
    message = calls[2][1]
    assert message["To"] == "alerts@example.org"
    assert message["Subject"] == "AI Guardian violation: Sensitive finding"
    assert message.get_content() == (
        "AI Guardian detected a violation.\n\n"
        "Category: Sensitive finding\n"
        "Severity: critical\n"
        "Originating daemon: remote-daemon\n"
    )
    assert "blocked" not in message.get_content()
    assert "private-scanned-content" not in message.as_string()
    assert calls[-1] == ("quit",)


@pytest.mark.parametrize(
    "smtp,recipient",
    [
        ({}, "alerts@example.org"),
        (
            {
                "smtp_host": "mail.example.org",
                "smtp_port": 587,
                "smtp_tls": False,
                "auth": {"method": "none"},
            },
            "alerts@example.org",
        ),
        (
            {
                "smtp_host": "mail.example.org",
                "smtp_port": 587,
                "smtp_tls": True,
                "auth": {"method": "none"},
            },
            "",
        ),
    ],
)
def test_email_requires_recipient_and_tls_smtp(tmp_path, monkeypatch, smtp, recipient):
    email_sender = Mock()
    monkeypatch.setattr(notifications, "_send_email_notification", email_sender)
    service = _service(
        tmp_path / "notifications.sqlite3",
        settings={
            "enabled": True,
            "channels": {"desktop": False, "email": True},
            "email": {"recipient": recipient},
        },
        smtp=smtp,
    )

    service.notify_local("tool_permission", "warning", "viol_0123456789abcdef")

    email_sender.assert_not_called()
    assert service.store.recent_local_events()[0]["delivery"]["email"] == (
        "not_configured"
    )


def test_smtp_authentication_failure_does_not_log_server_details(
    tmp_path, monkeypatch, caplog
):
    def authentication_failure(*_args, **_kwargs):
        raise notifications.smtplib.SMTPAuthenticationError(
            535, b"synthetic-private-auth-detail"
        )

    monkeypatch.setattr(notifications.smtplib, "SMTP", authentication_failure)
    smtp = {
        "smtp_host": "mail.example.org",
        "smtp_port": 587,
        "smtp_tls": True,
        "auth": {"method": "none"},
    }
    service = _service(
        tmp_path / "notifications.sqlite3",
        settings={
            "enabled": True,
            "channels": {"desktop": False, "email": True},
            "email": {"recipient": "alerts@example.org"},
        },
        smtp=smtp,
    )

    service.notify_local("tool_permission", "warning", "viol_0123456789abcdef")

    assert "synthetic-private-auth-detail" not in caplog.text
    assert service.store.recent_local_events()[0]["delivery"]["email"] == "failed"


def test_remote_old_daemon_fallback_uses_only_curated_fields(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from ai_guardian.daemon.notification_relay import (
        relay_remote_violation_notifications,
    )

    send = Mock(return_value=True)
    service = _service(tmp_path / "notifications.sqlite3", desktop_sender=send)
    monkeypatch.setattr(
        ViolationNotificationService,
        "from_global_config",
        classmethod(lambda _cls: service),
    )
    target = SimpleNamespace(
        name="remote-daemon",
        runtime="manual",
        status="running",
        url="https://remote.example",
    )

    class Client:
        def get_violations(self, _target, limit):
            assert limit == 1000
            return {
                "violations": [
                    {
                        "id": "viol_0123456789abcdef",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "violation_type": "secret_detected",
                        "severity": "high",
                        "blocked": {"value": "private-scanned-content"},
                        "context": {"prompt": "private-prompt-content"},
                    }
                ],
                "count": 1,
            }

    assert relay_remote_violation_notifications(Client(), [target]) == 1
    assert send.call_args.args == (
        "AI Guardian violation: Sensitive finding",
        "Severity: high\nOriginating daemon: remote-daemon",
    )
    assert "private-scanned-content" not in repr(send.call_args)
    assert "private-prompt-content" not in repr(send.call_args)
    send.assert_called_once()


def test_legacy_remote_baseline_does_not_replay_old_history(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from ai_guardian.daemon.notification_relay import (
        relay_remote_violation_notifications,
    )

    send = Mock(return_value=True)
    service = _service(tmp_path / "notifications.sqlite3", desktop_sender=send)
    monkeypatch.setattr(
        ViolationNotificationService,
        "from_global_config",
        classmethod(lambda _cls: service),
    )
    target = SimpleNamespace(
        name="old-remote",
        runtime="manual",
        status="running",
        url="https://old-remote.example",
    )

    class Client:
        timestamp = "2020-01-01T00:00:00Z"

        def get_violations(self, _target, limit):
            assert limit == 1000
            return {
                "violations": [
                    {
                        "id": "viol_0123456789abcdef",
                        "timestamp": self.timestamp,
                        "violation_type": "tool_permission",
                        "severity": "high",
                    }
                ]
            }

    client = Client()
    assert relay_remote_violation_notifications(client, [target]) == 0
    send.assert_not_called()

    client.timestamp = datetime.now(timezone.utc).isoformat()
    assert relay_remote_violation_notifications(client, [target]) == 1
    send.assert_called_once()


def test_untrusted_event_ids_are_replaced_with_stable_opaque_ids():
    first = safe_event_id("legacy-id-with-private-value")
    second = safe_event_id("legacy-id-with-private-value")

    assert first == second
    assert first.startswith("viol_")
    assert "private-value" not in first


def test_full_dispatch_queue_drops_alert_without_raising(monkeypatch, caplog):
    full_queue = queue.Queue(maxsize=1)
    full_queue.put_nowait(("tool_permission", "warning", "viol_0"))
    monkeypatch.setattr(notifications, "_NOTIFICATION_QUEUE", full_queue)
    monkeypatch.setattr(notifications, "_DISPATCHER_STARTED", True)

    assert (
        notifications.schedule_violation_notification(
            "tool_permission", "warning", "viol_0123456789abcdef"
        )
        is False
    )
    assert "Violation notification queue is full" in caplog.text
