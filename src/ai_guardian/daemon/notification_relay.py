"""Deliver privacy-safe remote violation alerts through local settings."""

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from ai_guardian.daemon.violation_mirroring import (
    REMOTE_RUNTIMES,
    _source_key,
)
from ai_guardian.violations.notifications import (
    VIOLATION_NOTIFICATION_TYPES,
    ViolationNotificationService,
    safe_event_id,
)
from ai_guardian.violations.utils import is_mirrored_violation

logger = logging.getLogger(__name__)


def _timestamp_epoch(value: Any) -> float | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.timestamp()


def relay_remote_violation_notifications(client: Any, targets: Iterable[Any]) -> int:
    """Use local channel settings for remote events that were not delivered there.

    Newer daemons return their durable notification outbox alongside the existing
    violations response. Earlier outbox events are joined to curated violation
    summaries by ID when they lack a type. Older daemons with no outbox field use
    those summaries only within a persisted, overlapping poll window; the initial
    poll never replays old history.
    """
    if client is None:
        return 0

    service = ViolationNotificationService.from_global_config()
    relayed = 0
    for target in targets:
        if getattr(target, "runtime", None) not in REMOTE_RUNTIMES or getattr(
            target, "status", None
        ) not in ("running", "paused"):
            continue
        source_key = _source_key(target)
        try:
            response = client.get_violations(target, limit=1000)
        except Exception:
            logger.warning("Could not retrieve remote notification events; continuing")
            continue
        if not isinstance(response, dict):
            continue

        events = response.get("notification_events")
        if isinstance(events, list):
            violation_types_by_id: dict[str, str] = {}
            records = response.get("violations")
            if isinstance(records, list):
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    record_id = record.get("id")
                    violation_type = record.get("violation_type", record.get("type"))
                    if (
                        isinstance(record_id, str)
                        and violation_type in VIOLATION_NOTIFICATION_TYPES
                    ):
                        violation_types_by_id[record_id] = violation_type
                        violation_types_by_id[safe_event_id(record_id)] = violation_type
            for event in events:
                try:
                    relay_event = event
                    if (
                        isinstance(event, dict)
                        and event.get("violation_type")
                        not in VIOLATION_NOTIFICATION_TYPES
                    ):
                        inferred_type = violation_types_by_id.get(event.get("id", ""))
                        if inferred_type:
                            relay_event = {**event, "violation_type": inferred_type}
                    if service.relay_remote_event(source_key, relay_event):
                        relayed += 1
                except Exception:
                    logger.warning("Could not relay a remote notification; continuing")
            continue

        # A pre-notification-release daemon cannot have delivered these channels.
        # Use only its already-curated history fields, never blocked/source content.
        if "notification_events" in response:
            continue
        records = response.get("violations")
        if not isinstance(records, list):
            continue
        try:
            legacy_window_start = service.store.advance_legacy_source_cursor(source_key)
        except Exception:
            logger.warning("Could not update legacy remote notification cursor")
            continue
        for record in records:
            if not isinstance(record, dict) or is_mirrored_violation(record):
                continue
            record_timestamp = _timestamp_epoch(record.get("timestamp"))
            if record_timestamp is None or record_timestamp < legacy_window_start:
                continue
            event = {
                "id": record.get("id"),
                "timestamp": record.get("timestamp"),
                "category": record.get("violation_type", record.get("type")),
                "violation_type": record.get("violation_type", record.get("type")),
                "severity": record.get("severity"),
                "source_daemon": getattr(target, "name", "remote"),
                "delivery": {
                    "desktop": "not_configured",
                    "email": "not_configured",
                },
            }
            try:
                if service.relay_remote_event(source_key, event):
                    relayed += 1
            except Exception:
                logger.warning("Could not relay a remote notification; continuing")
    return relayed
