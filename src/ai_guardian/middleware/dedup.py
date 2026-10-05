"""Pre-persistence deduplication for explicit hook/middleware defense-in-depth."""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FindingKey:
    """Stable identity for one finding across hook and middleware surfaces."""

    correlation_id: str
    scanner: str
    phase: str
    direction: str
    segment: str
    rule_id: str = ""

    def digest(self) -> str:
        value = "\x1f".join(
            (
                self.correlation_id,
                self.scanner,
                self.phase,
                self.direction,
                self.segment,
                self.rule_id,
            )
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


class FindingDeduplicator:
    """Bounded TTL set used before a violation is persisted or emitted."""

    def __init__(self, *, ttl_seconds: float = 300.0, max_entries: int = 10_000):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[str, float] = {}
        self._lock = threading.Lock()

    def first_seen(self, key: FindingKey, *, now: Optional[float] = None) -> bool:
        """Return true only for the first non-expired occurrence of *key*."""

        timestamp = time.monotonic() if now is None else now
        digest = key.digest()
        with self._lock:
            self._prune(timestamp)
            if digest in self._entries:
                return False
            self._entries[digest] = timestamp + self.ttl_seconds
            if len(self._entries) > self.max_entries:
                oldest = min(self._entries, key=lambda entry: self._entries[entry])
                self._entries.pop(oldest, None)
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _prune(self, now: float) -> None:
        expired = [key for key, expires in self._entries.items() if expires <= now]
        for key in expired:
            self._entries.pop(key, None)
