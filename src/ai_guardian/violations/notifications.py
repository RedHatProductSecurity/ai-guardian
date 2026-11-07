"""Privacy-safe, idempotent notifications for violation events."""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import queue
import re
import smtplib
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Iterator, Optional

from ai_guardian.storage import check_storage_file, make_private_directory

logger = logging.getLogger(__name__)

CHANNELS = ("desktop", "email")
DELIVERY_STATUSES = frozenset(
    {
        "pending",
        "delivered",
        "failed",
        "uncertain",
        "not_configured",
        "remote_pending",
        "remote_delivered",
        "remote_failed",
        "remote_uncertain",
        "local_disabled",
    }
)
_SAFE_EVENT_ID_RE = re.compile(r"^viol_[0-9a-fA-F]{8,64}$", re.ASCII)
_SAFE_SOURCE_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$", re.ASCII)
_SAFE_SEVERITIES = frozenset({"info", "warning", "high", "critical"})
_CATEGORY_LABELS = {
    "tool_permission": "Tool permission",
    "directory_blocking": "Directory blocking",
    "secret_detected": "Sensitive finding",
    "image_secret_detected": "Sensitive finding",
    "pii_detected": "Sensitive finding",
    "image_pii_detected": "Sensitive finding",
    "secret_in_transcript": "Sensitive finding",
    "pii_in_transcript": "Sensitive finding",
    "suspected_password": "Suspected password",
    "secret_redaction": "Secret redaction",
    "prompt_injection": "Prompt injection",
    "jailbreak_detected": "Jailbreak detected",
    "ssrf_blocked": "SSRF blocked",
    "config_file_exfil": "Configuration exfiltration",
    "prompt_injection_in_transcript": "Prompt injection",
    "annotation_suppressed": "Annotation suppressed",
    "middleware_paused": "Middleware paused",
    "bash_exfil": "Shell exfiltration",
    "scan_finding": "Scan finding",
    "canary_detection": "Canary detection",
    "context_poisoning": "Context poisoning",
    "supply_chain": "Supply-chain threat",
    "code_security": "Code security",
    "offensive_language": "Offensive language",
    "canary_detected": "Canary detected",
    "exfil_detection": "Exfiltration detected",
    "sensitive_finding": "Sensitive finding",
}
NOTIFICATION_TYPE_LABELS = {
    "tool_permission": "Tool permission",
    "directory_blocking": "Directory blocking",
    "secret_detected": "Secret detected",
    "image_secret_detected": "Image secret detected",
    "pii_detected": "PII detected",
    "image_pii_detected": "Image PII detected",
    "secret_in_transcript": "Secret in transcript",
    "pii_in_transcript": "PII in transcript",
    "suspected_password": "Suspected password",
    "secret_redaction": "Secret redaction",
    "prompt_injection": "Prompt injection",
    "jailbreak_detected": "Jailbreak detected",
    "ssrf_blocked": "SSRF blocked",
    "config_file_exfil": "Configuration file exfiltration",
    "prompt_injection_in_transcript": "Prompt injection in transcript",
    "annotation_suppressed": "Annotation suppressed",
    "middleware_paused": "Middleware paused",
    "bash_exfil": "Shell exfiltration",
    "scan_finding": "Scan finding",
    "canary_detection": "Canary detection",
    "context_poisoning": "Context poisoning",
    "supply_chain": "Supply-chain threat",
    "code_security": "Code security",
    "offensive_language": "Offensive language",
    "canary_detected": "Canary detected",
    "exfil_detection": "Exfiltration detected",
    "sensitive_finding": "Sensitive finding",
}
VIOLATION_NOTIFICATION_TYPES = tuple(NOTIFICATION_TYPE_LABELS)
DEFAULT_NOTIFICATION_PREFERENCES = {"desktop": True, "email": False}
_SAFE_CATEGORY_LABELS = frozenset(_CATEGORY_LABELS.values()) | {"Security violation"}
_MAX_NOTIFICATION_EVENTS = 10_000
_MAX_NOTIFICATION_SOURCES = 1_000
_NOTIFICATION_RETENTION_SECONDS = 30 * 24 * 60 * 60
_LEGACY_POLL_OVERLAP_SECONDS = 60
_DELIVERY_SLOTS = threading.BoundedSemaphore(8)
_NOTIFICATION_QUEUE: queue.Queue[tuple[Any, Any, Any]] = queue.Queue(maxsize=256)
_DISPATCHER_LOCK = threading.Lock()
_DISPATCHER_STARTED = False
_DIRECT_HOOK_HANDOFF: ContextVar[bool] = ContextVar(
    "direct_hook_notification_handoff", default=False
)


def new_violation_event_id() -> str:
    """Create an opaque identifier suitable for persistence and remote relay."""
    return f"viol_{uuid.uuid4().hex}"


def safe_event_id(value: Any) -> str:
    """Return a stable, non-content-bearing event identifier."""
    if isinstance(value, str) and _SAFE_EVENT_ID_RE.fullmatch(value):
        return value
    if value is None:
        return new_violation_event_id()
    digest = hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()
    return f"viol_{digest[:32]}"


def _category_label(violation_type: Any) -> str:
    value = getattr(violation_type, "value", violation_type)
    if isinstance(value, str):
        return _CATEGORY_LABELS.get(value, "Security violation")
    return "Security violation"


def _safe_violation_type(value: Any) -> str:
    value = getattr(value, "value", value)
    return value if isinstance(value, str) and value in NOTIFICATION_TYPE_LABELS else ""


def _violation_type_from_category(category: Any) -> str:
    raw_type = _safe_violation_type(category)
    if raw_type:
        return raw_type
    if not isinstance(category, str):
        return ""
    matches = [
        violation_type
        for violation_type, label in _CATEGORY_LABELS.items()
        if label == category
    ]
    return matches[0] if len(matches) == 1 else ""


def get_notification_preferences(
    notification_config: Any,
) -> dict[str, dict[str, bool]]:
    """Return complete, validated per-type settings with legacy compatibility.

    A legacy explicit ``enabled: false`` remains a safety gate until a Console
    save migrates the setting to per-type preferences. Legacy channel choices are
    otherwise copied to types without an explicit new preference.
    """
    config = notification_config if isinstance(notification_config, dict) else {}
    by_type = config.get("by_type", {})
    by_type = by_type if isinstance(by_type, dict) else {}
    legacy_channels = config.get("channels", {})
    legacy_channels = legacy_channels if isinstance(legacy_channels, dict) else {}
    has_legacy = "enabled" in config or "channels" in config
    legacy_enabled = config.get("enabled", True) is True
    defaults = (
        {
            "desktop": legacy_enabled and legacy_channels.get("desktop", True) is True,
            "email": legacy_enabled and legacy_channels.get("email", False) is True,
        }
        if has_legacy
        else DEFAULT_NOTIFICATION_PREFERENCES
    )

    preferences: dict[str, dict[str, bool]] = {}
    for violation_type in VIOLATION_NOTIFICATION_TYPES:
        configured = by_type.get(violation_type, {})
        configured = configured if isinstance(configured, dict) else {}
        values = dict(defaults)
        for channel in CHANNELS:
            if isinstance(configured.get(channel), bool):
                values[channel] = configured[channel]
        if "enabled" in config and not legacy_enabled:
            values = {channel: False for channel in CHANNELS}
        preferences[violation_type] = values
    return preferences


def _severity_label(severity: Any) -> str:
    value = getattr(severity, "value", severity)
    if isinstance(value, str) and value.lower() in _SAFE_SEVERITIES:
        return value.lower()
    return "warning"


def _display_name(value: Any, fallback: str = "AI Guardian") -> str:
    if not isinstance(value, str):
        value = ""
    value = " ".join(value.split())
    value = "".join(char for char in value if char.isprintable())[:128]
    return value or fallback


def _safe_timestamp(value: Any = None) -> str:
    if isinstance(value, str) and len(value) <= 64:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return value
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_key(namespace: str, event_id: str) -> str:
    return hashlib.sha256(f"{namespace}\0{event_id}".encode("utf-8")).hexdigest()


class NotificationStore:
    """Private SQLite outbox and per-channel at-most-once delivery ledger."""

    def __init__(self, path: Optional[Path] = None):
        if path is None:
            from ai_guardian.config.utils import get_state_dir

            path = get_state_dir() / "violation-notifications.sqlite3"
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        make_private_directory(self.path.parent)
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except FileExistsError:
            check_storage_file(self.path, private=True)
        else:
            os.close(descriptor)
            check_storage_file(self.path, private=True)

        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS notification_events ("
            "event_key TEXT PRIMARY KEY, namespace TEXT NOT NULL, "
            "event_id TEXT NOT NULL, occurred_at TEXT NOT NULL, "
            "category TEXT NOT NULL, violation_type TEXT NOT NULL DEFAULT '', "
            "severity TEXT NOT NULL, "
            "source_daemon TEXT NOT NULL, created_at REAL NOT NULL)"
        )
        event_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(notification_events)")
        }
        if "violation_type" not in event_columns:
            connection.execute(
                "ALTER TABLE notification_events ADD COLUMN "
                "violation_type TEXT NOT NULL DEFAULT ''"
            )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS notification_deliveries ("
            "event_key TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL, "
            "updated_at REAL NOT NULL, PRIMARY KEY (event_key, channel))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS notification_source_cursors ("
            "source_key TEXT PRIMARY KEY, last_poll REAL NOT NULL)"
        )
        connection.commit()
        return connection

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        event_key: str,
        namespace: str,
        event: dict[str, str],
    ) -> bool:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO notification_events "
            "(event_key, namespace, event_id, occurred_at, category, violation_type, "
            "severity, source_daemon, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_key,
                namespace,
                event["id"],
                event["timestamp"],
                event["category"],
                _safe_violation_type(event.get("violation_type")),
                event["severity"],
                event["source_daemon"],
                time.time(),
            ),
        )
        return cursor.rowcount == 1

    @staticmethod
    def _set_status(
        connection: sqlite3.Connection,
        event_key: str,
        channel: str,
        status: str,
    ) -> None:
        if channel not in CHANNELS or status not in DELIVERY_STATUSES:
            return
        connection.execute(
            "INSERT INTO notification_deliveries (event_key, channel, status, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(event_key, channel) DO UPDATE SET "
            "status=excluded.status, updated_at=excluded.updated_at",
            (event_key, channel, status, time.time()),
        )

    def register_local_event(
        self, event: dict[str, str], statuses: dict[str, str]
    ) -> tuple[str, bool]:
        key = _event_key("local", event["id"])
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            created = self._insert_event(
                connection, event_key=key, namespace="local", event=event
            )
            if created:
                for channel in CHANNELS:
                    self._set_status(
                        connection,
                        key,
                        channel,
                        statuses.get(channel, "not_configured"),
                    )
                self._prune(connection)
            connection.commit()
            return key, created
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def register_remote_event(
        self,
        *,
        namespace: str,
        event: dict[str, str],
        remote_statuses: dict[str, str],
        local_statuses: dict[str, str],
    ) -> tuple[str, list[str]]:
        """Record a remote event and claim only channels needing local fallback."""
        key = _event_key(namespace, event["id"])
        scheduled: list[str] = []
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_event(
                connection, event_key=key, namespace=namespace, event=event
            )
            for channel in CHANNELS:
                row = connection.execute(
                    "SELECT status FROM notification_deliveries "
                    "WHERE event_key = ? AND channel = ?",
                    (key, channel),
                ).fetchone()
                current = row["status"] if row else None

                # A local attempt is terminal, including an uncertain result: an
                # ambiguous remote send must never be retried as a second alert.
                if current in {
                    "pending",
                    "delivered",
                    "failed",
                    "uncertain",
                    "remote_delivered",
                    "remote_uncertain",
                    "not_configured",
                    "local_disabled",
                }:
                    continue

                remote = remote_statuses.get(channel, "not_configured")
                if remote == "delivered":
                    self._set_status(connection, key, channel, "remote_delivered")
                    continue
                if remote in {"pending", "uncertain"}:
                    self._set_status(
                        connection,
                        key,
                        channel,
                        "remote_pending" if remote == "pending" else "remote_uncertain",
                    )
                    continue
                if local_statuses.get(channel) != "pending":
                    self._set_status(connection, key, channel, "not_configured")
                    continue

                self._set_status(connection, key, channel, "pending")
                scheduled.append(channel)
            self._prune(connection)
            connection.commit()
            return key, scheduled
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update_delivery(self, event_key: str, channel: str, status: str) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._set_status(connection, event_key, channel, status)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def pending_local_event(
        self, event_id: str
    ) -> Optional[tuple[str, dict[str, str], list[str]]]:
        """Load one local event and its still-pending delivery channels."""
        if not isinstance(event_id, str) or not _SAFE_EVENT_ID_RE.fullmatch(event_id):
            return None
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT event_key, event_id, occurred_at, category, severity, "
                "source_daemon, violation_type FROM notification_events "
                "WHERE namespace = 'local' AND event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            pending = {
                delivery["channel"]
                for delivery in connection.execute(
                    "SELECT channel FROM notification_deliveries "
                    "WHERE event_key = ? AND status = 'pending'",
                    (row["event_key"],),
                ).fetchall()
            }
            pending_channels = [channel for channel in CHANNELS if channel in pending]
            if not pending_channels:
                return None
            event = {
                "id": row["event_id"],
                "timestamp": row["occurred_at"],
                "category": row["category"],
                "severity": row["severity"],
                "source_daemon": row["source_daemon"],
            }
            safe_type = _safe_violation_type(row["violation_type"])
            if safe_type:
                event["violation_type"] = safe_type
            return row["event_key"], event, pending_channels
        finally:
            connection.close()

    def advance_legacy_source_cursor(self, source_key: str) -> float:
        """Return a replay-safe timestamp window for older daemons without outboxes."""
        if not _SAFE_SOURCE_KEY_RE.fullmatch(source_key):
            raise ValueError("Invalid notification source identity")
        now = time.time()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT last_poll FROM notification_source_cursors WHERE source_key = ?",
                (source_key.lower(),),
            ).fetchone()
            since = (
                now - _LEGACY_POLL_OVERLAP_SECONDS
                if row is None
                else row["last_poll"] - _LEGACY_POLL_OVERLAP_SECONDS
            )
            connection.execute(
                "INSERT INTO notification_source_cursors (source_key, last_poll) "
                "VALUES (?, ?) ON CONFLICT(source_key) DO UPDATE SET "
                "last_poll=excluded.last_poll",
                (source_key.lower(), now),
            )
            connection.commit()
            return since
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def recent_local_events(self, limit: int = 250) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._prune(connection)
            connection.commit()
            rows = connection.execute(
                "SELECT event_key, event_id, occurred_at, category, severity, "
                "source_daemon, violation_type FROM notification_events "
                "WHERE namespace = 'local' "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            events = []
            for row in rows:
                delivery_rows = connection.execute(
                    "SELECT channel, status FROM notification_deliveries "
                    "WHERE event_key = ?",
                    (row["event_key"],),
                ).fetchall()
                delivery = {item["channel"]: item["status"] for item in delivery_rows}
                event = {
                    "id": row["event_id"],
                    "timestamp": row["occurred_at"],
                    "category": row["category"],
                    "severity": row["severity"],
                    "source_daemon": row["source_daemon"],
                    "delivery": {
                        channel: delivery.get(channel, "not_configured")
                        for channel in CHANNELS
                    },
                }
                safe_type = _safe_violation_type(row["violation_type"])
                if safe_type:
                    event["violation_type"] = safe_type
                events.append(event)
            return events
        finally:
            connection.close()

    def _prune(self, connection: sqlite3.Connection) -> None:
        cutoff = time.time() - _NOTIFICATION_RETENTION_SECONDS
        connection.execute(
            "DELETE FROM notification_deliveries WHERE event_key IN "
            "(SELECT event_key FROM notification_events WHERE created_at < ?)",
            (cutoff,),
        )
        connection.execute(
            "DELETE FROM notification_events WHERE created_at < ?", (cutoff,)
        )
        connection.execute(
            "DELETE FROM notification_deliveries WHERE event_key IN ("
            "SELECT event_key FROM notification_events ORDER BY created_at DESC "
            "LIMIT -1 OFFSET ?)",
            (_MAX_NOTIFICATION_EVENTS,),
        )
        connection.execute(
            "DELETE FROM notification_events WHERE event_key NOT IN "
            "(SELECT event_key FROM notification_events ORDER BY created_at DESC "
            "LIMIT ?)",
            (_MAX_NOTIFICATION_EVENTS,),
        )
        connection.execute(
            "DELETE FROM notification_source_cursors WHERE source_key NOT IN "
            "(SELECT source_key FROM notification_source_cursors "
            "ORDER BY last_poll DESC LIMIT ?)",
            (_MAX_NOTIFICATION_SOURCES,),
        )


def _recipient_is_valid(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 254:
        return False
    if "\r" in value or "\n" in value or any(char.isspace() for char in value):
        return False
    parsed = parseaddr(value)[1]
    if parsed != value or parsed.count("@") != 1:
        return False
    local, domain = parsed.rsplit("@", 1)
    return bool(
        local
        and domain
        and not domain.startswith(".")
        and not domain.endswith(".")
        and ".." not in domain
    )


def _smtp_auth_available(email_settings: dict[str, Any]) -> bool:
    auth = email_settings.get("auth", {})
    if not isinstance(auth, dict):
        return False
    method = auth.get("method", "none")
    if method == "none":
        return True
    if method == "env":
        username_env = auth.get("username_env")
        password_env = auth.get("password_env")
        return bool(
            isinstance(username_env, str)
            and username_env
            and isinstance(password_env, str)
            and password_env
            and os.environ.get(username_env)
            and os.environ.get(password_env)
        )
    if method == "inline":
        return bool(auth.get("username") and auth.get("password"))
    return False


def _smtp_ready(email_settings: dict[str, Any], recipient: Any) -> bool:
    host = email_settings.get("smtp_host")
    port = email_settings.get("smtp_port", 587)
    tls_enabled = email_settings.get("smtp_tls", True)
    if (
        not isinstance(host, str)
        or not host.strip()
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65535
        or (port != 465 and tls_enabled is not True)
        or not _recipient_is_valid(recipient)
    ):
        return False
    return _smtp_auth_available(email_settings)


def notification_email_ready(notification_config: Any, smtp_config: Any) -> bool:
    """Whether alert email has a valid recipient and usable TLS SMTP transport."""
    config = notification_config if isinstance(notification_config, dict) else {}
    email = config.get("email", {})
    email = email if isinstance(email, dict) else {}
    smtp = smtp_config if isinstance(smtp_config, dict) else {}
    return _smtp_ready(smtp, email.get("recipient"))


def _smtp_credentials(
    email_settings: dict[str, Any],
) -> tuple[Optional[str], Optional[str]]:
    auth = email_settings.get("auth", {})
    method = auth.get("method", "none") if isinstance(auth, dict) else "none"
    if method == "env":
        return (
            os.environ.get(auth.get("username_env", "")),
            os.environ.get(auth.get("password_env", "")),
        )
    if method == "inline":
        return auth.get("username"), auth.get("password")
    return None, None


def _send_email_notification(
    event: dict[str, str], email_settings: dict[str, Any], recipient: str
) -> str:
    """Send only the safe alert envelope; never attach or quote scan content."""
    host = email_settings["smtp_host"].strip()
    port = int(email_settings.get("smtp_port", 587))
    from_addr = email_settings.get("from")
    if not isinstance(from_addr, str) or "\r" in from_addr or "\n" in from_addr:
        from_addr = ""
    from_addr = parseaddr(from_addr)[1] if from_addr else ""
    if not _recipient_is_valid(from_addr):
        from_addr = "ai-guardian@localhost.localdomain"

    message = EmailMessage()
    message["From"] = from_addr
    message["To"] = recipient
    message["Subject"] = f"AI Guardian violation: {event['category']}"
    message.set_content(
        "AI Guardian detected a violation.\n\n"
        f"Category: {event['category']}\n"
        f"Severity: {event['severity']}\n"
        f"Originating daemon: {event['source_daemon']}\n"
    )

    server: Optional[smtplib.SMTP] = None
    send_started = False
    try:
        context = ssl.create_default_context()
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls(context=context)
        username, password = _smtp_credentials(email_settings)
        if username and password:
            server.login(username, password)
        send_started = True
        refused = server.send_message(message)
        if refused:
            return "failed"
        return "delivered"
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError):
        return "failed"
    except (smtplib.SMTPException, OSError, ValueError, TypeError):
        # Once DATA may have reached the server, retrying locally could duplicate
        # an email whose acceptance response was lost.
        return "uncertain" if send_started else "failed"
    finally:
        if server is not None:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass  # intentionally silent — delivery outcome is already recorded


class ViolationNotificationService:
    """Dispatch local violations and safe remote fallback events."""

    def __init__(
        self,
        notification_config: Optional[dict[str, Any]] = None,
        smtp_config: Optional[dict[str, Any]] = None,
        *,
        store: Optional[NotificationStore] = None,
        desktop_sender: Any = None,
        background: bool = True,
        daemon_name: Optional[str] = None,
    ):
        config = notification_config if isinstance(notification_config, dict) else {}
        self.preferences = get_notification_preferences(config)
        email = config.get("email", {})
        self.alert_email = email if isinstance(email, dict) else {}
        self.smtp_config = smtp_config if isinstance(smtp_config, dict) else {}
        self.store = store or NotificationStore()
        self.desktop_sender = desktop_sender or self._desktop_sender
        self.background = background
        self.daemon_name = _display_name(daemon_name or platform.node())

    @classmethod
    def from_global_config(cls, **kwargs: Any) -> "ViolationNotificationService":
        config: dict[str, Any] = {}
        try:
            from ai_guardian.config.writer import load_scoped_config

            loaded = load_scoped_config("global")
            if isinstance(loaded, dict):
                config = loaded
        except Exception:
            logger.warning("Could not load violation notification settings")
        daemon = config.get("daemon", {})
        daemon_name = daemon.get("name") if isinstance(daemon, dict) else None
        support = config.get("support", {})
        smtp = support.get("email", {}) if isinstance(support, dict) else {}
        return cls(
            config.get("violation_notifications"),
            smtp if isinstance(smtp, dict) else {},
            daemon_name=daemon_name,
            **kwargs,
        )

    @staticmethod
    def _desktop_sender(title: str, message: str) -> bool:
        from ai_guardian.tray.notifications import show_notification

        return show_notification(title, message, wait=True) is True

    def _channel_statuses(self, violation_type: Any) -> dict[str, str]:
        type_key = _safe_violation_type(violation_type)
        preferences = self.preferences.get(type_key, DEFAULT_NOTIFICATION_PREFERENCES)
        desktop_selected = preferences.get("desktop") is True
        email_selected = preferences.get("email") is True
        recipient = self.alert_email.get("recipient")
        email_ready = email_selected and _smtp_ready(self.smtp_config, recipient)
        return {
            "desktop": "pending" if desktop_selected else "not_configured",
            "email": "pending" if email_ready else "not_configured",
        }

    def _make_event(
        self,
        event_id: Any,
        category: Any,
        severity: Any,
        source_daemon: Any,
        timestamp: Any = None,
        violation_type: Any = None,
    ) -> dict[str, str]:
        event = {
            "id": safe_event_id(event_id),
            "timestamp": _safe_timestamp(timestamp),
            "category": (
                category
                if isinstance(category, str) and category in _SAFE_CATEGORY_LABELS
                else _category_label(category)
            ),
            "severity": _severity_label(severity),
            "source_daemon": _display_name(source_daemon, self.daemon_name),
        }
        type_key = _safe_violation_type(
            violation_type
        ) or _violation_type_from_category(category)
        if type_key:
            event["violation_type"] = type_key
        return event

    def notify_local(
        self,
        violation_type: Any,
        severity: Any = "warning",
        violation_id: Any = None,
        *,
        timestamp: Any = None,
        source_daemon: Any = None,
    ) -> str:
        """Persist a minimal outbox event and schedule enabled delivery channels."""
        event, event_key, created, statuses = self._register_local_event(
            violation_type,
            severity,
            violation_id,
            timestamp=timestamp,
            source_daemon=source_daemon,
        )
        if created:
            for channel, status in statuses.items():
                if status == "pending":
                    self._schedule(event_key, channel, event)
        return event["id"]

    def persist_local(
        self,
        violation_type: Any,
        severity: Any = "warning",
        violation_id: Any = None,
        *,
        timestamp: Any = None,
        source_daemon: Any = None,
    ) -> tuple[str, bool, bool]:
        """Commit the safe outbox event without starting in-process delivery."""
        event, _event_key, created, statuses = self._register_local_event(
            violation_type,
            severity,
            violation_id,
            timestamp=timestamp,
            source_daemon=source_daemon,
        )
        return (
            event["id"],
            created,
            any(status == "pending" for status in statuses.values()),
        )

    def _register_local_event(
        self,
        violation_type: Any,
        severity: Any,
        violation_id: Any,
        *,
        timestamp: Any,
        source_daemon: Any,
    ) -> tuple[dict[str, str], str, bool, dict[str, str]]:
        event = self._make_event(
            violation_id,
            _category_label(violation_type),
            severity,
            source_daemon or self.daemon_name,
            timestamp,
            violation_type=violation_type,
        )
        statuses = self._channel_statuses(event.get("violation_type"))
        event_key, created = self.store.register_local_event(event, statuses)
        return event, event_key, created, statuses

    def relay_remote_event(self, source_key: str, remote_event: Any) -> bool:
        """Apply local settings only to remote channels not known to have sent."""
        if not _SAFE_SOURCE_KEY_RE.fullmatch(source_key):
            return False
        if not isinstance(remote_event, dict):
            return False
        event = self._make_event(
            remote_event.get("id"),
            remote_event.get("category"),
            remote_event.get("severity"),
            remote_event.get("source_daemon"),
            remote_event.get("timestamp"),
            violation_type=remote_event.get("violation_type"),
        )
        raw_delivery = remote_event.get("delivery", {})
        raw_delivery = raw_delivery if isinstance(raw_delivery, dict) else {}
        remote_statuses = {
            channel: (
                raw_delivery.get(channel, "not_configured")
                if raw_delivery.get(channel)
                in {"pending", "delivered", "failed", "uncertain", "not_configured"}
                else "not_configured"
            )
            for channel in CHANNELS
        }
        local_type = event.get("violation_type")
        local_statuses = (
            self._channel_statuses(local_type)
            if local_type
            else {channel: "not_configured" for channel in CHANNELS}
        )
        namespace = f"remote:{source_key.lower()}"
        event_key, scheduled = self.store.register_remote_event(
            namespace=namespace,
            event=event,
            remote_statuses=remote_statuses,
            local_statuses=local_statuses,
        )
        for channel in scheduled:
            self._schedule(event_key, channel, event)
        return bool(scheduled)

    def _schedule(self, event_key: str, channel: str, event: dict[str, str]) -> None:
        if not _DELIVERY_SLOTS.acquire(blocking=False):
            self._update_safely(event_key, channel, "failed")
            logger.warning(
                "Violation notification queue is full; channel delivery failed"
            )
            return
        args = (event_key, channel, event)
        if not self.background:
            try:
                self._deliver(*args)
            finally:
                _DELIVERY_SLOTS.release()
            return
        worker = threading.Thread(
            target=self._deliver_and_release,
            args=args,
            name=f"violation-notification-{channel}",
            daemon=True,
        )
        try:
            worker.start()
        except RuntimeError:
            _DELIVERY_SLOTS.release()
            self._update_safely(event_key, channel, "failed")
            logger.warning("Could not start violation notification delivery")

    def _deliver_and_release(
        self, event_key: str, channel: str, event: dict[str, str]
    ) -> None:
        try:
            self._deliver(event_key, channel, event)
        finally:
            _DELIVERY_SLOTS.release()

    def _deliver(self, event_key: str, channel: str, event: dict[str, str]) -> None:
        try:
            if channel == "desktop":
                title = f"AI Guardian violation: {event['category']}"
                message = (
                    f"Severity: {event['severity']}\n"
                    f"Originating daemon: {event['source_daemon']}"
                )
                outcome = (
                    "delivered"
                    if self.desktop_sender(title, message) is True
                    else "failed"
                )
            else:
                recipient = self.alert_email.get("recipient", "")
                if not _smtp_ready(self.smtp_config, recipient):
                    outcome = "failed"
                else:
                    outcome = _send_email_notification(
                        event, self.smtp_config, recipient
                    )
            self._update_safely(event_key, channel, outcome)
            if outcome in {"failed", "uncertain"}:
                logger.warning(
                    "Violation %s notification delivery %s; details withheld",
                    channel,
                    outcome,
                )
        except Exception:
            self._update_safely(event_key, channel, "failed")
            logger.warning(
                "Violation %s notification failed; details withheld", channel
            )

    def _update_safely(self, event_key: str, channel: str, status: str) -> None:
        try:
            self.store.update_delivery(event_key, channel, status)
        except Exception:
            logger.warning("Could not record violation notification delivery status")

    def dispatch_pending_local_event(self, event_id: str) -> bool:
        """Deliver pending channels for one durable local outbox event."""
        pending = self.store.pending_local_event(event_id)
        if pending is None:
            return False
        event_key, event, channels = pending
        for channel in channels:
            self._deliver(event_key, channel, event)
        return True


def notify_violation(
    violation_type: Any,
    severity: Any = "warning",
    violation_id: Any = None,
) -> Optional[str]:
    """Best-effort notification entry point; never affects detection or logging."""
    try:
        return ViolationNotificationService.from_global_config().notify_local(
            violation_type, severity, violation_id
        )
    except Exception:
        logger.warning("Could not queue violation notification; details withheld")
        return None


def _spawn_notification_worker(event_id: str) -> bool:
    """Start a detached worker using only the opaque persisted event ID."""
    if not _SAFE_EVENT_ID_RE.fullmatch(event_id):
        return False
    command = [
        sys.executable,
        "-E",
        "-m",
        "ai_guardian.violations.notification_worker",
        event_id,
    ]
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        # Do not let a repository's current directory shadow the installed worker.
        # Keep user-site installs available; isolated mode (-I) disables them.
        "cwd": str(Path(__file__).resolve().parents[2]),
    }
    if os.name == "nt":
        options["creationflags"] = getattr(
            subprocess, "DETACHED_PROCESS", getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        options["start_new_session"] = True
    try:
        subprocess.Popen(command, **options)
    except (OSError, ValueError, subprocess.SubprocessError):
        logger.warning("Could not start detached violation notification worker")
        return False
    return True


def _persist_and_dispatch_direct_notification(
    violation_type: Any, severity: Any, violation_id: Any
) -> bool:
    """Persist before the short-lived hook exits, then delegate delivery."""
    try:
        service = ViolationNotificationService.from_global_config()
        event_id, created, has_pending_channels = service.persist_local(
            violation_type, severity, violation_id
        )
        if created and has_pending_channels:
            return _spawn_notification_worker(event_id)
        return True
    except Exception:
        logger.warning("Could not persist direct-hook notification; details withheld")
        return False


@contextmanager
def direct_hook_notification_handoff() -> Iterator[None]:
    """Use durable outbox handoff while processing a direct-mode hook."""
    token = _DIRECT_HOOK_HANDOFF.set(True)
    try:
        yield
    finally:
        _DIRECT_HOOK_HANDOFF.reset(token)


def _notification_dispatch_loop() -> None:
    """Process the bounded outbox handoff away from the hook request thread."""
    while True:
        violation_type, severity, violation_id = _NOTIFICATION_QUEUE.get()
        try:
            notify_violation(violation_type, severity, violation_id)
        except Exception:
            logger.warning(
                "Could not dispatch violation notification; details withheld"
            )
        finally:
            _NOTIFICATION_QUEUE.task_done()


def schedule_violation_notification(
    violation_type: Any,
    severity: Any = "warning",
    violation_id: Any = None,
) -> bool:
    """Hand off notification work without blocking scanning or violation logging."""
    if _DIRECT_HOOK_HANDOFF.get():
        return _persist_and_dispatch_direct_notification(
            violation_type, severity, violation_id
        )

    global _DISPATCHER_STARTED
    with _DISPATCHER_LOCK:
        if not _DISPATCHER_STARTED:
            worker = threading.Thread(
                target=_notification_dispatch_loop,
                name="violation-notification-outbox",
                daemon=True,
            )
            try:
                worker.start()
            except RuntimeError:
                logger.warning("Could not start violation notification dispatcher")
                return False
            _DISPATCHER_STARTED = True
        try:
            _NOTIFICATION_QUEUE.put_nowait((violation_type, severity, violation_id))
        except queue.Full:
            logger.warning("Violation notification queue is full; alert was dropped")
            return False
    return True


def get_recent_notification_events(limit: int = 250) -> list[dict[str, Any]]:
    """Return only the privacy-safe local notification outbox envelope."""
    try:
        return NotificationStore().recent_local_events(limit)
    except Exception:
        logger.warning("Could not read violation notification outbox")
        return []
