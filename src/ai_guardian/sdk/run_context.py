"""RunContext — correlate multiple SDK calls within a program run."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class RunContext:
    """Lightweight context shared across SDK calls in a single program run.

    Args:
        run_id: Links all traces/violations from this run.
            Auto-generated UUID if omitted.
        metadata: Custom key-values attached to every trace and OTEL span.
        parent_trace_id: Link to a parent trace for nested orchestration.
    """

    run_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_trace_id: Optional[str] = None

    def __post_init__(self):
        if not self.run_id:
            self.run_id = uuid.uuid4().hex
        self._sequence: int = 0
        self._lock = threading.Lock()
        self._started_at: Dict[int, str] = {}
        self._ended_at: Dict[int, str] = {}

    def next_sequence(self) -> int:
        """Atomically increment and return the next sequence number."""
        with self._lock:
            self._sequence += 1
            seq = self._sequence
        self._started_at[seq] = datetime.now(timezone.utc).isoformat()
        return seq

    def end_sequence(self, seq: int) -> None:
        """Record the end timestamp for a sequence number."""
        self._ended_at[seq] = datetime.now(timezone.utc).isoformat()

    def ran_concurrently(self, a: int, b: int) -> bool:
        """Check whether two sequences had overlapping time intervals."""
        a_start = self._started_at.get(a)
        a_end = self._ended_at.get(a)
        b_start = self._started_at.get(b)
        b_end = self._ended_at.get(b)
        if not all((a_start, a_end, b_start, b_end)):
            return False
        return a_start < b_end and b_start < a_end
