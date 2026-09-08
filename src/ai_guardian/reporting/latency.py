"""Hook latency tracking — per-hook and per-violation-type timing.

Records timing data to latency.jsonl for performance analysis.
Disabled by default; enable via latency_tracking.enabled in ai-guardian.json.
"""

import json
import logging
import math
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class _CheckTimer:
    """Accumulate per-check timings within a single process_hook_data() call.

    When enabled=False, check() is a no-op pass-through with zero overhead.
    """

    __slots__ = ("_timings", "_start_total", "_enabled", "_ask_wait_ms")

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._timings: Dict[str, float] = {}
        self._start_total = time.perf_counter() if enabled else 0.0
        self._ask_wait_ms = 0.0

    @contextmanager
    def check(self, name: str):
        if not self._enabled:
            yield
            return
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            self._timings[name] = self._timings.get(name, 0.0) + elapsed_ms

    def add_ask_wait(self, ms: float) -> None:
        if self._enabled and ms > 0:
            self._ask_wait_ms += ms

    def total_ms(self) -> float:
        if not self._enabled:
            return 0.0
        return (time.perf_counter() - self._start_total) * 1000

    def processing_ms(self) -> float:
        return max(0.0, self.total_ms() - self._ask_wait_ms)

    @property
    def ask_wait_total_ms(self) -> float:
        return self._ask_wait_ms

    def to_dict(self) -> Dict[str, float]:
        return dict(self._timings)


class LatencyLogger:
    """Append-only JSONL logger for per-hook timing data."""

    _lock = threading.Lock()

    def __init__(self, log_path: Optional[Path] = None, config: Optional[Dict] = None):
        self.config = config if config is not None else self._load_config()
        if log_path is None:
            from ai_guardian.config.utils import get_state_dir

            log_path = get_state_dir() / "latency.jsonl"
        self.log_path = log_path
        if self._is_enabled():
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_timing(self, entry: Dict) -> None:
        if not self._is_enabled():
            return
        try:
            line = json.dumps(entry) + "\n"
            with self._lock:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(line)
                self._rotate_if_needed_locked()
        except Exception as e:
            logger.debug(f"Latency log write failed (non-fatal): {e}")

    def read_entries(self, since: Optional[datetime] = None) -> List[Dict]:
        if not self.log_path.exists():
            return []
        entries: List[Dict] = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if since:
                        ts = _parse_timestamp(entry.get("timestamp"))
                        if ts < since:
                            continue
                    entries.append(entry)
        except Exception as e:
            logger.warning(f"Error reading latency log: {e}")
        return entries

    def clear_log(self) -> bool:
        try:
            if self.log_path.exists():
                self.log_path.unlink()
            return True
        except Exception as e:
            logger.warning(f"Error clearing latency log: {e}")
            return False

    def _is_enabled(self) -> bool:
        from ai_guardian.config.utils import is_feature_enabled

        return is_feature_enabled(self.config.get("enabled"), default=False)

    def _rotate_if_needed(self):
        """Rotate log file if needed (acquires lock)."""
        with self._lock:
            self._rotate_if_needed_locked()

    def _rotate_if_needed_locked(self):
        """Rotate log file if needed (caller must hold self._lock)."""
        try:
            if not self.log_path.exists():
                return
            max_entries = self.config.get("max_entries", 5000)
            retention_days = self.config.get("retention_days", 30)
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

            entries = []
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            entries = [
                e for e in entries if _parse_timestamp(e.get("timestamp")) > cutoff
            ]
            if len(entries) > max_entries:
                entries = entries[-max_entries:]

            with open(self.log_path, "w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug(f"Latency log rotation failed (non-fatal): {e}")

    def _load_config(self) -> Dict:
        from ai_guardian.config.loaders import _load_latency_tracking_config

        config, error_msg = _load_latency_tracking_config()
        if error_msg:
            logger.warning("Error loading latency tracking config: %s", error_msg)
        return config or self._default_config()

    @staticmethod
    def _default_config() -> Dict:
        return {"enabled": False, "max_entries": 5000, "retention_days": 30}


def _parse_timestamp(timestamp_str: Optional[str]) -> datetime:
    if not timestamp_str:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        if timestamp_str.endswith("Z"):
            timestamp_str = timestamp_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(timestamp_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _parse_since(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc) - timedelta(days=30)
    value = value.strip()
    if value.lower().endswith("d"):
        try:
            days = int(value[:-1])
            return datetime.now(timezone.utc) - timedelta(days=days)
        except ValueError:
            pass  # intentionally silent — invalid value uses default
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass  # intentionally silent — invalid value uses default
    raise ValueError(
        f"Invalid --since value: '{value}'. "
        f"Use Nd for days (e.g. 30d) or ISO date (e.g. 2026-05-01)"
    )


@dataclass
class _HookStat:
    hook_event: str = ""
    avg: float = 0.0
    stddev: float = 0.0
    p95: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    count: int = 0


@dataclass
class _CheckStat:
    check_name: str = ""
    avg: float = 0.0
    stddev: float = 0.0
    p95: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    count: int = 0
    hooks: str = ""


@dataclass
class LatencyReport:
    hook_stats: List[Dict] = field(default_factory=list)
    check_stats: List[Dict] = field(default_factory=list)
    invocation_count: int = 0
    time_range_start: str = ""
    time_range_end: str = ""
    ask_dialog_count: int = 0
    ask_dialog_stats: Optional[Dict] = None
    paused: bool = False


def _compute_stats(values: List[float]) -> Dict:
    if not values:
        return {
            "avg": 0.0,
            "stddev": 0.0,
            "p95": 0.0,
            "min": 0.0,
            "max": 0.0,
            "count": 0,
        }
    n = len(values)
    avg = sum(values) / n
    if n < 2:
        stddev = 0.0
    else:
        variance = sum((v - avg) ** 2 for v in values) / (n - 1)
        stddev = math.sqrt(variance)
    sorted_vals = sorted(values)
    p95_idx = int(math.ceil(0.95 * n)) - 1
    p95 = sorted_vals[max(0, p95_idx)]
    return {
        "avg": round(avg, 2),
        "stddev": round(stddev, 2),
        "p95": round(p95, 2),
        "min": round(sorted_vals[0], 2),
        "max": round(sorted_vals[-1], 2),
        "count": n,
    }


class LatencyComputer:
    """Reads latency.jsonl and computes aggregate statistics."""

    def __init__(
        self, since_date: Optional[str] = None, since_days: Optional[int] = None
    ):
        if since_date:
            self._cutoff = _parse_since(since_date)
        elif since_days is not None:
            self._cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        else:
            self._cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    def compute(self) -> LatencyReport:
        paused = _is_latency_paused()
        entries = LatencyLogger().read_entries(since=self._cutoff)
        if not entries:
            return LatencyReport(
                time_range_start=self._cutoff.isoformat(),
                time_range_end=datetime.now(timezone.utc).isoformat(),
                paused=paused,
            )

        hook_totals: Dict[str, List[float]] = {}
        check_totals: Dict[str, List[float]] = {}
        check_hooks: Dict[str, set] = {}
        ask_dialog_values: List[float] = []

        for entry in entries:
            hook_event = entry.get("hook_event", "unknown")
            processing_ms = entry.get("processing_ms", entry.get("total_ms", 0.0))
            hook_totals.setdefault(hook_event, []).append(processing_ms)

            for check_name, ms in (entry.get("checks") or {}).items():
                if ms > 0:
                    check_totals.setdefault(check_name, []).append(ms)
                    check_hooks.setdefault(check_name, set()).add(hook_event)

            ask_ms = entry.get("ask_dialog_ms", 0.0)
            if ask_ms > 0:
                ask_dialog_values.append(ask_ms)

        hook_stats = []
        for hook_event in sorted(hook_totals.keys()):
            stats = _compute_stats(hook_totals[hook_event])
            stats["hook_event"] = hook_event
            hook_stats.append(stats)

        check_stats = []
        for check_name in sorted(check_totals.keys()):
            stats = _compute_stats(check_totals[check_name])
            stats["check_name"] = check_name
            hooks = check_hooks.get(check_name, set())
            stats["hooks"] = "/".join(sorted(hooks))
            check_stats.append(stats)

        check_stats.sort(key=lambda s: s["avg"], reverse=True)

        ask_stats = _compute_stats(ask_dialog_values) if ask_dialog_values else None

        return LatencyReport(
            hook_stats=hook_stats,
            check_stats=check_stats,
            invocation_count=len(entries),
            time_range_start=self._cutoff.isoformat(),
            time_range_end=datetime.now(timezone.utc).isoformat(),
            ask_dialog_count=len(ask_dialog_values),
            ask_dialog_stats=ask_stats,
            paused=paused,
        )


def _is_latency_paused() -> bool:
    """Return whether persisted daemon state is currently paused."""
    try:
        from ai_guardian.daemon.state import DaemonState

        return DaemonState.is_paused_on_disk(cwd=os.getcwd())
    except Exception as e:
        logger.debug("Unable to determine persisted pause state: %s", e)
        return False


def format_latency_human(report: LatencyReport) -> str:
    lines: List[str] = []
    lines.append("Hook Latency Statistics")
    lines.append("=" * 78)

    if not report.hook_stats and not report.check_stats:
        lines.append("")
        lines.append("No latency data found in the selected time range.")
        if report.paused:
            lines.append("Latency collection is paused because the daemon is paused.")
            lines.append("Resume the daemon and trigger a new hook invocation.")
        else:
            lines.append("Enable latency tracking: set latency_tracking.enabled = true")
            lines.append("in ~/.config/ai-guardian/ai-guardian.json")
        return "\n".join(lines)

    lines.append(f"  Invocations: {report.invocation_count:,}")
    lines.append("")

    lines.append("Hook Processing Time (excludes ask dialog wait)")
    lines.append("-" * 78)
    lines.append(
        f"  {'Hook Event':<22s} {'Avg(ms)':>8s} {'StdDev':>8s} "
        f"{'P95(ms)':>8s} {'Min(ms)':>8s} {'Max(ms)':>8s} {'Count':>7s}"
    )
    for s in report.hook_stats:
        lines.append(
            f"  {s['hook_event']:<22s} {s['avg']:>8.1f} {s['stddev']:>8.1f} "
            f"{s['p95']:>8.1f} {s['min']:>8.1f} {s['max']:>8.1f} {s['count']:>7,}"
        )

    if report.check_stats:
        lines.append("")
        lines.append("Per-Violation-Type Breakdown")
        lines.append("-" * 78)
        lines.append(
            f"  {'Check Type':<22s} {'Avg(ms)':>8s} {'StdDev':>8s} "
            f"{'P95(ms)':>8s} {'Min(ms)':>8s} {'Max(ms)':>8s} {'Count':>7s} {'Hook(s)'}"
        )
        for s in report.check_stats:
            lines.append(
                f"  {s['check_name']:<22s} {s['avg']:>8.1f} {s['stddev']:>8.1f} "
                f"{s['p95']:>8.1f} {s['min']:>8.1f} {s['max']:>8.1f} "
                f"{s['count']:>7,} {s.get('hooks', '')}"
            )

    if report.ask_dialog_count > 0 and report.ask_dialog_stats:
        lines.append("")
        lines.append("Ask Dialog Wait Time (excluded from processing stats)")
        lines.append("-" * 78)
        s = report.ask_dialog_stats
        lines.append(
            f"  Dialogs: {report.ask_dialog_count:,}  "
            f"Avg: {s['avg']:.0f}ms  P95: {s['p95']:.0f}ms  "
            f"Min: {s['min']:.0f}ms  Max: {s['max']:.0f}ms"
        )

    return "\n".join(lines)


def format_latency_json(report: LatencyReport) -> str:
    data = {
        "time_range": {
            "start": report.time_range_start,
            "end": report.time_range_end,
        },
        "invocation_count": report.invocation_count,
        "hook_stats": report.hook_stats,
        "check_stats": report.check_stats,
        "ask_dialog_count": report.ask_dialog_count,
        "ask_dialog_stats": report.ask_dialog_stats,
        "paused": report.paused,
    }
    return json.dumps(data, indent=2)
