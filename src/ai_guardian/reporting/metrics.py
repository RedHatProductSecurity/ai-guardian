#!/usr/bin/env python3
"""
AI Guardian Metrics — violation statistics command.

Computes statistics from the violations.jsonl log file.
No daemon or infrastructure needed — reads local log directly.

Usage:
    ai-guardian metrics              # Human-readable summary
    ai-guardian metrics --json       # Machine-readable JSON
    ai-guardian metrics --since 7d   # Last 7 days
    ai-guardian metrics --type secret_detected  # Filter by type
    ai-guardian metrics --csv        # Export as CSV
"""

import csv
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, TextIO, Tuple

logger = logging.getLogger(__name__)


def _parse_timestamp(timestamp_str: Optional[str]) -> datetime:
    """Parse ISO timestamp string to datetime."""
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
    """Parse --since argument into a cutoff datetime.

    Accepts:
        "Nd" — N days ago (e.g. "30d", "7d")
        ISO date — specific date (e.g. "2026-05-01")
    """
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
class MetricsReport:
    """Holds computed violation statistics."""

    total_violations: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    session_count: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_action: Dict[str, int] = field(default_factory=dict)
    top_files: List[Tuple[str, int]] = field(default_factory=list)
    top_tools: List[Tuple[str, int]] = field(default_factory=list)
    time_trend: List[Dict] = field(default_factory=list)
    time_range_start: str = ""
    time_range_end: str = ""
    cumulative_total: int = 0
    cumulative_by_type: Dict[str, int] = field(default_factory=dict)
    cumulative_since: str = ""


class MetricsComputer:
    """Reads violations.jsonl and computes aggregate statistics."""

    def __init__(
        self,
        since_days: Optional[int] = None,
        since_date: Optional[str] = None,
        violation_type: Optional[str] = None,
    ):
        if since_date:
            self._cutoff = _parse_since(since_date)
        elif since_days is not None:
            self._cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        else:
            self._cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        self._violation_type = violation_type

    def compute(self) -> MetricsReport:
        violations = self.read_filtered_violations()
        cumulative = self._load_cumulative()

        if not violations:
            report = MetricsReport(
                time_range_start=self._cutoff.isoformat(),
                time_range_end=datetime.now(timezone.utc).isoformat(),
            )
        else:
            now = datetime.now(timezone.utc)
            report = MetricsReport(
                total_violations=len(violations),
                resolved_count=sum(1 for v in violations if v.get("resolved")),
                unresolved_count=sum(1 for v in violations if not v.get("resolved")),
                session_count=self._count_sessions(violations),
                by_type=self._count_by_key(violations, "violation_type"),
                by_severity=self._count_by_key(violations, "severity"),
                by_action=self._count_by_action(violations),
                top_files=self._top_files(violations),
                top_tools=self._top_tools(violations),
                time_trend=self._time_trend(violations),
                time_range_start=self._cutoff.isoformat(),
                time_range_end=now.isoformat(),
            )

        report.cumulative_total = cumulative.get("total", 0)
        report.cumulative_by_type = cumulative.get("violation_totals", {})
        report.cumulative_since = cumulative.get("since", "")
        return report

    @staticmethod
    def _load_cumulative() -> Dict:
        try:
            from ai_guardian.violations.counter import ViolationCounter

            return ViolationCounter().get_counters()
        except Exception:
            return {"total": 0, "violation_totals": {}, "since": ""}

    def read_filtered_violations(self) -> List[Dict]:
        """Read and filter violations from the JSONL log."""
        from ai_guardian.violations.logger import ViolationLogger

        vl = ViolationLogger()
        if not vl.log_path.exists():
            return []

        violations: List[Dict] = []
        try:
            with open(vl.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    ts = _parse_timestamp(entry.get("timestamp"))
                    if ts < self._cutoff:
                        continue

                    if (
                        self._violation_type
                        and entry.get("violation_type") != self._violation_type
                    ):
                        continue

                    violations.append(entry)
        except Exception as e:
            logger.warning(f"Error reading violations log: {e}")

        return violations

    @staticmethod
    def _count_by_key(violations: List[Dict], key: str) -> Dict[str, int]:
        counter: Counter = Counter()
        for v in violations:
            val = v.get(key)
            if val:
                counter[val] += 1
        return dict(counter.most_common())

    @staticmethod
    def _count_by_action(violations: List[Dict]) -> Dict[str, int]:
        counter: Counter = Counter()
        for v in violations:
            action = (v.get("context") or {}).get("action")
            if action:
                counter[action] += 1
        return dict(counter.most_common())

    @staticmethod
    def _count_sessions(violations: List[Dict]) -> int:
        sessions = set()
        for v in violations:
            sid = (v.get("context") or {}).get("session_id")
            if sid:
                sessions.add(sid)
        return len(sessions)

    @staticmethod
    def _top_files(violations: List[Dict], limit: int = 10) -> List[Tuple[str, int]]:
        counter: Counter = Counter()
        for v in violations:
            blocked = v.get("blocked") or {}
            fp = blocked.get("file_path")
            if fp:
                counter[fp] += 1
        return counter.most_common(limit)

    @staticmethod
    def _top_tools(violations: List[Dict], limit: int = 10) -> List[Tuple[str, int]]:
        counter: Counter = Counter()
        for v in violations:
            blocked = v.get("blocked") or {}
            tool = (
                blocked.get("tool_name") or blocked.get("tool") or blocked.get("source")
            )
            if tool:
                counter[tool] += 1
        return counter.most_common(limit)

    @staticmethod
    def _time_trend(violations: List[Dict]) -> List[Dict]:
        counter: Counter = Counter()
        for v in violations:
            ts = _parse_timestamp(v.get("timestamp"))
            date_str = ts.strftime("%Y-%m-%d")
            counter[date_str] += 1
        return [{"date": d, "count": c} for d, c in sorted(counter.items())]


def format_human(report: MetricsReport) -> str:
    """Format metrics report as human-readable text."""
    lines: List[str] = []

    lines.append("AI Guardian Metrics")
    lines.append("=" * 40)

    # Cumulative totals (independent of log rotation)
    if report.cumulative_total > 0:
        since_display = (
            report.cumulative_since[:10] if report.cumulative_since else "unknown"
        )
        lines.append("")
        lines.append("Cumulative Totals")
        lines.append("-" * 40)
        lines.append(f"  All-time total:    {report.cumulative_total:>6,}")
        lines.append(f"  Tracking since:    {since_display}")
        if report.cumulative_by_type:
            for vtype, count in sorted(
                report.cumulative_by_type.items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"    {vtype:<23s} {count:>5,}")

    if report.total_violations == 0:
        lines.append("\nNo violations found in the selected time range.")
        return "\n".join(lines)

    # Summary
    lines.append("")
    lines.append("Summary")
    lines.append("-" * 40)
    lines.append(f"  Total violations:  {report.total_violations:>6,}")
    lines.append(f"  Resolved:          {report.resolved_count:>6,}")
    lines.append(f"  Unresolved:        {report.unresolved_count:>6,}")
    lines.append(f"  Unique sessions:   {report.session_count:>6,}")

    # By type
    if report.by_type:
        lines.append("")
        lines.append("By Type")
        lines.append("-" * 40)
        total = report.total_violations
        for vtype, count in report.by_type.items():
            pct = (count / total * 100) if total > 0 else 0
            lines.append(f"  {vtype:<25s} {count:>5,}  ({pct:>5.1f}%)")

    # By severity
    if report.by_severity:
        lines.append("")
        lines.append("By Severity")
        lines.append("-" * 40)
        total = report.total_violations
        for sev, count in report.by_severity.items():
            pct = (count / total * 100) if total > 0 else 0
            lines.append(f"  {sev:<25s} {count:>5,}  ({pct:>5.1f}%)")

    # By action
    if report.by_action:
        lines.append("")
        lines.append("By Action")
        lines.append("-" * 40)
        total = report.total_violations
        for action, count in report.by_action.items():
            pct = (count / total * 100) if total > 0 else 0
            lines.append(f"  {action:<25s} {count:>5,}  ({pct:>5.1f}%)")

    # Top files
    if report.top_files:
        lines.append("")
        lines.append("Top Files")
        lines.append("-" * 40)
        for i, (fp, count) in enumerate(report.top_files, 1):
            display_path = fp if len(fp) <= 40 else "..." + fp[-37:]
            lines.append(f"  {i:>2}. {display_path:<40s} {count:>4,}")

    # Top tools
    if report.top_tools:
        lines.append("")
        lines.append("Top Tools")
        lines.append("-" * 40)
        for i, (tool, count) in enumerate(report.top_tools, 1):
            lines.append(f"  {i:>2}. {tool:<40s} {count:>4,}")

    # Daily trend
    if report.time_trend:
        lines.append("")
        lines.append("Daily Trend")
        lines.append("-" * 40)
        max_count = max(t["count"] for t in report.time_trend)
        bar_width = 20
        for entry in report.time_trend[-14:]:
            bar_len = (
                int(entry["count"] / max_count * bar_width) if max_count > 0 else 0
            )
            bar = "█" * bar_len
            lines.append(f"  {entry['date']}  {entry['count']:>4,}  {bar}")

    return "\n".join(lines)


def format_json(report: MetricsReport) -> str:
    """Format metrics report as JSON."""
    data = {
        "time_range": {
            "start": report.time_range_start,
            "end": report.time_range_end,
        },
        "summary": {
            "total": report.total_violations,
            "resolved": report.resolved_count,
            "unresolved": report.unresolved_count,
            "sessions": report.session_count,
        },
        "by_type": report.by_type,
        "by_severity": report.by_severity,
        "by_action": report.by_action,
        "top_files": [{"path": fp, "count": c} for fp, c in report.top_files],
        "top_tools": [{"tool": t, "count": c} for t, c in report.top_tools],
        "time_trend": report.time_trend,
        "cumulative": {
            "total": report.cumulative_total,
            "by_type": report.cumulative_by_type,
            "since": report.cumulative_since,
        },
    }
    return json.dumps(data, indent=2)


CSV_COLUMNS = [
    "timestamp",
    "violation_type",
    "severity",
    "action",
    "file_path",
    "tool",
    "session_id",
    "resolved",
]


def format_csv(violations: List[Dict], stream: TextIO) -> None:
    """Write filtered violations as CSV to stream."""
    writer = csv.writer(stream)
    writer.writerow(CSV_COLUMNS)
    for v in violations:
        blocked = v.get("blocked") or {}
        context = v.get("context") or {}
        tool = (
            blocked.get("tool_name")
            or blocked.get("tool")
            or blocked.get("source")
            or ""
        )
        writer.writerow(
            [
                v.get("timestamp", ""),
                v.get("violation_type", ""),
                v.get("severity", ""),
                context.get("action", ""),
                blocked.get("file_path", ""),
                tool,
                context.get("session_id", ""),
                v.get("resolved", False),
            ]
        )


def metrics_command(args) -> int:
    """CLI entry point for the metrics command.

    Routes to the audit module for --html, --until, --severity flags
    which need the enriched AuditComputer. Basic metrics use MetricsComputer.

    Args:
        args: Parsed argparse.Namespace

    Returns:
        int: Exit code (0 for success, 1 for error)
    """
    if getattr(args, "reset", False):
        return _reset_counters(args)

    if getattr(args, "latency", False):
        from ai_guardian.reporting.latency import (
            LatencyComputer,
            format_latency_human,
            format_latency_json,
        )

        since_value = getattr(args, "since", "30d") or "30d"
        latency_computer = LatencyComputer(since_date=since_value)
        latency_report = latency_computer.compute()
        if getattr(args, "json", False):
            print(format_latency_json(latency_report))
        else:
            print(format_latency_human(latency_report))
        return 0

    use_audit = (
        getattr(args, "html", False)
        or getattr(args, "until", None)
        or getattr(args, "severity", None)
    )

    if use_audit:
        from ai_guardian.reporting.audit import audit_command

        return audit_command(args)

    try:
        since_value = getattr(args, "since", "30d") or "30d"
        cutoff = _parse_since(since_value)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    computer = MetricsComputer(
        since_date=cutoff.isoformat(),
        violation_type=getattr(args, "type", None),
    )

    if getattr(args, "csv", False):
        violations = computer.read_filtered_violations()
        format_csv(violations, sys.stdout)
        return 0

    report = computer.compute()

    if getattr(args, "json", False):
        print(format_json(report))
    else:
        print(format_human(report))

    return 0


def _reset_counters(args) -> int:
    """Handle --reset flag: reset cumulative counters to current log counts."""
    from ai_guardian.violations.counter import ViolationCounter

    counter = ViolationCounter()
    old = counter.get_counters()

    if not getattr(args, "metrics_yes", False):
        print(f"Current cumulative total: {old.get('total', 0):,}")
        since = old.get("since", "")
        if since:
            print(f"Tracking since: {since[:10]}")
        print("This will reset counters to current log file counts.")
        try:
            confirm = input("Reset counters? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 0
        if confirm.strip().lower() != "y":
            print("Cancelled.")
            return 0

    result = counter.reset_to_current_log()
    print(f"Counters reset. New baseline: {result.get('total', 0):,} violations")
    print(f"Since: {result.get('since', 'now')[:19]}Z")
    return 0
