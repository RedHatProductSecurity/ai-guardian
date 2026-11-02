"""Opt-in, read-only mirroring of curated remote violation summaries."""

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit

from ai_guardian.storage import check_storage_file, make_private_directory
from ai_guardian.violations.identity import stable_violation_id
from ai_guardian.violations.logger import ViolationLogger
from ai_guardian.violations.utils import is_mirrored_violation

logger = logging.getLogger(__name__)

REMOTE_RUNTIMES = frozenset({"container", "kubernetes", "manual", "ssh"})
REMOTE_VIOLATION_FETCH_LIMIT = 10_000
_SAFE_SOURCE_ID_RE = re.compile(r"^viol_[0-9a-fA-F]{8,64}$", re.ASCII)
_SYNC_LOCK = threading.Lock()


def is_remote_mirroring_enabled(config: Optional[dict] = None) -> bool:
    """Read the global destination opt-in; errors and missing values fail closed."""
    if config is None:
        try:
            from ai_guardian.config.writer import load_scoped_config

            config = load_scoped_config("global")
        except Exception:
            logger.warning("Could not read remote violation mirroring setting")
            return False
    section = config.get("violation_logging") if isinstance(config, dict) else None
    return isinstance(section, dict) and section.get("mirror_remote_violations") is True


class MirrorIndex:
    """Persist opaque source/event keys so log rotation cannot cause re-imports."""

    def __init__(self, path: Optional[Path] = None):
        if path is None:
            from ai_guardian.config.utils import get_state_dir

            path = get_state_dir() / "remote-violation-mirror.sqlite3"
        self.path = Path(path)
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        make_private_directory(self.path.parent)
        try:
            fd = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except FileExistsError:
            check_storage_file(self.path, private=True)
        else:
            os.close(fd)
            check_storage_file(self.path, private=True)

        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS imported_events ("
            "source_key TEXT NOT NULL, event_key TEXT NOT NULL, imported_at REAL NOT NULL, "
            "PRIMARY KEY (source_key, event_key))"
        )
        connection.commit()
        return connection

    def get_seen(self, source_key: str) -> set[str]:
        """Return imported event digests for one source."""
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT event_key FROM imported_events WHERE source_key = ?",
                    (source_key,),
                )
                return {row[0] for row in rows}
            finally:
                connection.close()

    def mark_seen(self, source_key: str, event_key: str, retention_days: int) -> None:
        """Persist an opaque event digest and bound old index rows by retention."""
        retention = max(365, retention_days)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute(
                    "INSERT OR IGNORE INTO imported_events "
                    "(source_key, event_key, imported_at) VALUES (?, ?, ?)",
                    (source_key, event_key, time.time()),
                )
                connection.execute(
                    "DELETE FROM imported_events WHERE imported_at < ?",
                    (time.time() - retention * 86400,),
                )
                connection.commit()
            finally:
                connection.close()


def _source_key(target: Any) -> str:
    """Hash configured source identity without persisting endpoint details."""
    runtime = getattr(target, "runtime", "")
    name = getattr(target, "name", "")
    endpoint: Any
    if runtime == "container":
        endpoint = [
            getattr(target, "container_engine", None),
            getattr(target, "container_id", None)
            or getattr(target, "container_name", None)
            or name,
        ]
    elif runtime == "kubernetes":
        endpoint = [
            getattr(target, "context", None),
            getattr(target, "namespace", None),
            getattr(target, "pod_name", None),
            getattr(target, "container_id", None),
        ]
        if not any(endpoint):
            endpoint = name
    elif runtime == "ssh":
        endpoint = getattr(target, "ssh_id", None) or name
    else:
        url = getattr(target, "url", None)
        if url:
            try:
                parsed = urlsplit(url)
                endpoint = [parsed.scheme, parsed.hostname, parsed.port, parsed.path]
            except ValueError:
                endpoint = name
        else:
            host = getattr(target, "host", None)
            port = getattr(target, "port", None)
            endpoint = [host, port] if host and port else name
    identity = json.dumps([runtime, endpoint], separators=(",", ":"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _safe_source_id(value: Any) -> Optional[str]:
    if isinstance(value, str) and _SAFE_SOURCE_ID_RE.fullmatch(value):
        return value
    return None


def _safe_timestamp(value: Any) -> str:
    if isinstance(value, str) and len(value) <= 64:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return value
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _make_mirror_record(
    record: dict, target: Any, source_key: str
) -> Optional[tuple[dict, str]]:
    if not isinstance(record, dict) or is_mirrored_violation(record):
        return None
    violation_type = record.get("violation_type", record.get("type"))
    if (
        not isinstance(violation_type, str)
        or not violation_type
        or len(violation_type) > 128
    ):
        return None

    remote_id = _safe_source_id(record.get("id"))
    event_identity = remote_id or stable_violation_id(record)
    event_key = hashlib.sha256(event_identity.encode("utf-8")).hexdigest()
    mirror_id = (
        "viol_"
        + hashlib.sha256(f"{source_key}\0{event_key}".encode("utf-8")).hexdigest()[:32]
    )
    mirror = {
        "read_only": True,
        "source_daemon": str(getattr(target, "name", "remote"))[:128],
        "source_runtime": getattr(target, "runtime", ""),
        "source_key": source_key,
        "source_event_key": event_key,
        "mirrored_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if remote_id:
        mirror["source_violation_id"] = remote_id

    entry = {
        "id": mirror_id,
        "timestamp": _safe_timestamp(record.get("timestamp")),
        "violation_type": violation_type,
        "severity": (
            record.get("severity")
            if isinstance(record.get("severity"), str) and len(record["severity"]) <= 32
            else "warning"
        ),
        "blocked": {},
        "context": {},
        "suggestion": {},
        "resolved": record.get("resolved") is True,
        "resolved_at": (
            _safe_timestamp(record.get("resolved_at"))
            if record.get("resolved") is True and record.get("resolved_at")
            else None
        ),
        "mirror": mirror,
    }
    for key, maximum in (
        ("tool", 128),
        ("file", 4096),
        ("action", 128),
    ):
        value = record.get(key)
        if isinstance(value, str) and len(value) <= maximum:
            entry[key] = value
    line = record.get("line")
    if isinstance(line, int) and not isinstance(line, bool) and line >= 0:
        entry["line"] = line
    return entry, event_key


def _within_local_retention(timestamp: str, violation_logger: ViolationLogger) -> bool:
    try:
        days = max(1, int(violation_logger.config.get("retention_days", 30)))
        event_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        return event_time >= datetime.now(timezone.utc) - timedelta(days=days)
    except (TypeError, ValueError):
        return True


def mirror_remote_violations(
    client: Any,
    targets: Iterable[Any],
    *,
    enabled: Optional[bool] = None,
    violation_logger: Optional[ViolationLogger] = None,
    mirror_index: Optional[MirrorIndex] = None,
) -> int:
    """Pull curated remote summaries into local history without mutating sources."""
    should_mirror = (
        enabled if enabled is not None else is_remote_mirroring_enabled()
    ) is True

    with _SYNC_LOCK:
        local_logger = violation_logger or ViolationLogger()
        local_logger.cleanup_mirrored_logs()
        if not client or not should_mirror or not local_logger._is_logging_enabled():
            return 0
        index = mirror_index or MirrorIndex()
        try:
            retention_days = max(1, int(local_logger.config.get("retention_days", 30)))
        except (TypeError, ValueError):
            retention_days = 30

        mirrored_count = 0
        for target in targets:
            if getattr(target, "runtime", None) not in REMOTE_RUNTIMES or getattr(
                target, "status", None
            ) not in ("running", "paused"):
                continue
            source_key = _source_key(target)
            try:
                response = client.get_violations(
                    target, limit=REMOTE_VIOLATION_FETCH_LIMIT
                )
            except Exception:
                logger.warning("Remote violation mirror fetch failed; continuing")
                continue
            records = response.get("violations") if isinstance(response, dict) else None
            if not isinstance(records, list):
                continue
            try:
                seen = index.get_seen(source_key)
            except Exception:
                logger.warning("Remote violation mirror index unavailable; continuing")
                continue

            for record in records:
                try:
                    projected = _make_mirror_record(record, target, source_key)
                    if projected is None:
                        continue
                    entry, event_key = projected
                    if event_key in seen:
                        continue
                    if not _within_local_retention(entry["timestamp"], local_logger):
                        index.mark_seen(source_key, event_key, retention_days)
                        seen.add(event_key)
                        continue
                    if local_logger.has_violation_id(entry["id"]):
                        index.mark_seen(source_key, event_key, retention_days)
                        seen.add(event_key)
                        continue
                    if local_logger.append_mirrored_violation(entry):
                        index.mark_seen(source_key, event_key, retention_days)
                        seen.add(event_key)
                        mirrored_count += 1
                except Exception:
                    logger.warning("Could not mirror a remote violation; continuing")
        return mirrored_count
