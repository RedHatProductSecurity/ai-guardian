#!/usr/bin/env python3
"""
AI Guardian Audit — compliance report generation.

Generates formal compliance reports from the violations.jsonl log file.
Builds on MetricsComputer for data reading; adds trend comparison,
resolution analytics, compliance posture, and HTML export.

Usage:
    ai-guardian audit                          # Human-readable summary
    ai-guardian audit --html > report.html     # Self-contained HTML
    ai-guardian audit --json > report.json     # Machine-readable JSON
    ai-guardian audit --csv > report.csv       # Tabular CSV
    ai-guardian audit --since 30d              # Time range
    ai-guardian audit --since 2026-04-01 --until 2026-05-01
    ai-guardian audit --type secret_detected   # Filter by type
    ai-guardian audit --severity critical      # Filter by severity
"""

import csv
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, TextIO, Tuple

from ai_guardian.reporting.metrics import (
    MetricsComputer,
    _parse_since,
    _parse_timestamp,
)

logger = logging.getLogger(__name__)

VIOLATION_TYPE_TO_FEATURE = {
    "secret_detected": "secret_scanning",
    "command_credential_detected": "command_credential_scanning",
    "http_request_credential_detected": "http_request_credential_scanning",
    "secret_redaction": "secret_redaction",
    "pii_detected": "scan_pii",
    "prompt_injection": "prompt_injection",
    "jailbreak_detected": "prompt_injection",
    "ssrf_blocked": "ssrf_protection",
    "config_file_exfil": "config_file_scanning",
    "directory_blocking": "permissions",
    "tool_permission": "permissions",
    "secret_in_transcript": "transcript_scanning",
    "pii_in_transcript": "transcript_scanning",
    "prompt_injection_in_transcript": "transcript_scanning",
    "image_secret_detected": "image_scanning",
    "image_pii_detected": "image_scanning",
    "annotation_suppressed": "permissions",
}

POSTURE_LABELS = {
    "GOOD": "All scanning features enabled, no unresolved critical violations",
    "FAIR": "Most scanning features enabled or minor unresolved violations",
    "NEEDS ATTENTION": "Key features disabled or unresolved critical violations",
}


@dataclass
class AuditReport:
    """Holds all sections of a compliance audit report."""

    generated_at: str = ""
    time_range_start: str = ""
    time_range_end: str = ""
    total_violations: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    session_count: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_action: Dict[str, int] = field(default_factory=dict)
    top_files: List[Tuple[str, int]] = field(default_factory=list)
    top_tools: List[Tuple[str, int]] = field(default_factory=list)
    top_types: List[Tuple[str, int]] = field(default_factory=list)
    time_trend: List[Dict] = field(default_factory=list)
    prev_period_total: int = 0
    trend_change_pct: Optional[float] = None
    resolution_pct: float = 0.0
    avg_resolution_seconds: Optional[float] = None
    compliance_features: Dict[str, bool] = field(default_factory=dict)
    violations_per_feature: Dict[str, int] = field(default_factory=dict)
    security_posture: str = ""


@dataclass
class _AggregateResult:
    """Single-pass aggregation over violations list."""

    resolved_count: int = 0
    critical_unresolved: int = 0
    sessions: set = field(default_factory=set)
    by_type: Counter = field(default_factory=Counter)
    by_severity: Counter = field(default_factory=Counter)
    by_action: Counter = field(default_factory=Counter)
    files: Counter = field(default_factory=Counter)
    tools: Counter = field(default_factory=Counter)
    dates: Counter = field(default_factory=Counter)
    resolution_deltas: List[float] = field(default_factory=list)
    per_feature: Counter = field(default_factory=Counter)


class AuditComputer:
    """Reads violations and computes a full audit report."""

    def __init__(
        self,
        since: Optional[str] = "30d",
        until: Optional[str] = None,
        violation_type: Optional[str] = None,
        severity: Optional[str] = None,
    ):
        self._since_str = since or "30d"
        self._until_str = until
        self._violation_type = violation_type
        self._severity = severity

        self._cutoff = _parse_since(self._since_str)
        if until:
            self._until_dt = _parse_since(until)
        else:
            self._until_dt = datetime.now(timezone.utc)

    def compute(self) -> AuditReport:
        violations = self._read_violations()
        prev_violations = self._read_previous_period()

        now = datetime.now(timezone.utc)
        report = AuditReport(
            generated_at=now.isoformat(),
            time_range_start=self._cutoff.isoformat(),
            time_range_end=self._until_dt.isoformat(),
        )

        if not violations:
            report.compliance_features = self._load_compliance()
            report.security_posture = self._compute_posture(
                report.compliance_features, 0
            )
            return report

        agg = self._aggregate(violations)

        report.total_violations = len(violations)
        report.resolved_count = agg.resolved_count
        report.unresolved_count = report.total_violations - agg.resolved_count
        report.session_count = len(agg.sessions)
        report.by_type = dict(agg.by_type.most_common())
        report.by_severity = dict(agg.by_severity.most_common())
        report.by_action = dict(agg.by_action.most_common())
        report.top_files = agg.files.most_common(10)
        report.top_tools = agg.tools.most_common(10)
        report.top_types = sorted(
            agg.by_type.items(), key=lambda x: x[1], reverse=True
        )[:10]
        report.time_trend = [
            {"date": d, "count": c} for d, c in sorted(agg.dates.items())
        ]

        report.prev_period_total = len(prev_violations)
        if report.prev_period_total > 0:
            change = report.total_violations - report.prev_period_total
            report.trend_change_pct = (change / report.prev_period_total) * 100
        elif report.total_violations > 0:
            report.trend_change_pct = None

        if report.total_violations > 0:
            report.resolution_pct = agg.resolved_count / report.total_violations * 100
        report.avg_resolution_seconds = (
            sum(agg.resolution_deltas) / len(agg.resolution_deltas)
            if agg.resolution_deltas
            else None
        )

        report.compliance_features = self._load_compliance()
        report.violations_per_feature = dict(agg.per_feature.most_common())

        report.security_posture = self._compute_posture(
            report.compliance_features, agg.critical_unresolved
        )

        return report

    @staticmethod
    def _aggregate(violations: List[Dict]) -> _AggregateResult:
        """Single-pass aggregation over the violations list."""
        agg = _AggregateResult()
        for v in violations:
            resolved = v.get("resolved")
            if resolved:
                agg.resolved_count += 1

            severity = v.get("severity")
            if severity == "critical" and not resolved:
                agg.critical_unresolved += 1

            context = v.get("context") or {}
            sid = context.get("session_id")
            if sid:
                agg.sessions.add(sid)

            vtype = v.get("violation_type")
            if vtype:
                agg.by_type[vtype] += 1

            if severity:
                agg.by_severity[severity] += 1

            action = context.get("action")
            if action:
                agg.by_action[action] += 1

            blocked = v.get("blocked") or {}
            fp = blocked.get("file_path")
            if fp:
                agg.files[fp] += 1

            tool = (
                blocked.get("tool_name") or blocked.get("tool") or blocked.get("source")
            )
            if tool:
                agg.tools[tool] += 1

            ts = _parse_timestamp(v.get("timestamp"))
            agg.dates[ts.strftime("%Y-%m-%d")] += 1

            if resolved:
                resolved_at = v.get("resolved_at")
                timestamp = v.get("timestamp")
                if resolved_at and timestamp:
                    ra = _parse_timestamp(resolved_at)
                    if ra > ts:
                        agg.resolution_deltas.append((ra - ts).total_seconds())

            feature = VIOLATION_TYPE_TO_FEATURE.get(vtype or "", "other")
            agg.per_feature[feature] += 1

        return agg

    def _read_violations(self) -> List[Dict]:
        mc = MetricsComputer(
            since_date=self._cutoff.isoformat(),
            violation_type=self._violation_type,
        )
        violations = mc.read_filtered_violations()

        filtered = []
        for v in violations:
            ts = _parse_timestamp(v.get("timestamp"))
            if ts > self._until_dt:
                continue
            if self._severity and v.get("severity") != self._severity:
                continue
            filtered.append(v)
        return filtered

    def _read_previous_period(self) -> List[Dict]:
        period_days = (self._until_dt - self._cutoff).days
        if period_days <= 0:
            period_days = 30
        prev_start = self._cutoff - timedelta(days=period_days)

        mc = MetricsComputer(
            since_date=prev_start.isoformat(),
            violation_type=self._violation_type,
        )
        violations = mc.read_filtered_violations()

        filtered = []
        for v in violations:
            ts = _parse_timestamp(v.get("timestamp"))
            if ts >= self._cutoff:
                continue
            if self._severity and v.get("severity") != self._severity:
                continue
            filtered.append(v)
        return filtered

    @staticmethod
    def _count_by_key(violations: List[Dict], key: str) -> Dict[str, int]:
        counter: Counter = Counter()
        for v in violations:
            val = v.get(key)
            if val:
                counter[val] += 1
        return dict(counter.most_common())

    @staticmethod
    def _count_by_key_as_list(
        violations: List[Dict], key: str, limit: int = 10
    ) -> List[Tuple[str, int]]:
        counts = AuditComputer._count_by_key(violations, key)
        return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]

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
    def _top_items(
        violations: List[Dict], blocked_key: str, limit: int = 10
    ) -> List[Tuple[str, int]]:
        counter: Counter = Counter()
        for v in violations:
            blocked = v.get("blocked") or {}
            val = blocked.get(blocked_key)
            if val:
                counter[val] += 1
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

    @staticmethod
    def _avg_resolution_time(violations: List[Dict]) -> Optional[float]:
        deltas = []
        for v in violations:
            if not v.get("resolved"):
                continue
            resolved_at = v.get("resolved_at")
            timestamp = v.get("timestamp")
            if not resolved_at or not timestamp:
                continue
            ts = _parse_timestamp(timestamp)
            ra = _parse_timestamp(resolved_at)
            if ra > ts:
                deltas.append((ra - ts).total_seconds())
        if not deltas:
            return None
        return sum(deltas) / len(deltas)

    @staticmethod
    def _violations_per_feature(violations: List[Dict]) -> Dict[str, int]:
        counter: Counter = Counter()
        for v in violations:
            vtype = v.get("violation_type", "")
            feature = VIOLATION_TYPE_TO_FEATURE.get(vtype, "other")
            counter[feature] += 1
        return dict(counter.most_common())

    @staticmethod
    def _load_compliance() -> Dict[str, bool]:
        try:
            from ai_guardian.config.loaders import _load_config_file
            from ai_guardian.config.utils import get_feature_flags

            cfg, _ = _load_config_file()
            if not cfg:
                cfg = {}
            return get_feature_flags(cfg)
        except Exception:
            return {}

    @staticmethod
    def _compute_posture(features: Dict[str, bool], critical_unresolved: int) -> str:
        if not features:
            return "UNKNOWN"
        core_features = [
            "secret_scanning",
            "scan_pii",
            "prompt_injection",
            "ssrf_protection",
        ]
        enabled_count = sum(1 for f in core_features if features.get(f, False))
        if enabled_count == len(core_features) and critical_unresolved == 0:
            return "GOOD"
        if enabled_count >= len(core_features) - 1 and critical_unresolved <= 2:
            return "FAIR"
        return "NEEDS ATTENTION"


def format_audit_human(report: AuditReport) -> str:
    lines: List[str] = []
    start_display = report.time_range_start[:10] if report.time_range_start else "?"
    end_display = report.time_range_end[:10] if report.time_range_end else "?"

    lines.append("AI Guardian Audit Report")
    lines.append(f"Period: {start_display} to {end_display}")
    lines.append("=" * 50)

    if report.total_violations == 0:
        lines.append("\nNo violations found in the selected time range.")
        _append_compliance_section(lines, report)
        return "\n".join(lines)

    lines.append("")
    lines.append(f"Violations: {report.total_violations:,} total")
    if report.by_type:
        max_count = max(report.by_type.values())
        bar_max = 20
        for vtype, count in report.by_type.items():
            pct = count / report.total_violations * 100
            bar_len = int(count / max_count * bar_max) if max_count > 0 else 0
            bar = "█" * bar_len
            lines.append(f"  ├── {vtype:<25s} {count:>5,} ({pct:>5.1f}%)  {bar}")

    lines.append("")
    lines.append("Severity:")
    if report.by_severity:
        for sev, count in report.by_severity.items():
            bar_len = min(count, 40)
            bar = "█" * bar_len
            lines.append(f"  {sev:<12s} {count:>5,}  {bar}")

    lines.append("")
    lines.append("Actions taken:")
    if report.by_action:
        for action, count in report.by_action.items():
            pct = count / report.total_violations * 100
            lines.append(f"  {action:<12s} {count:>5,} ({pct:>5.1f}%)")

    if report.trend_change_pct is not None:
        direction = "▼" if report.trend_change_pct < 0 else "▲"
        lines.append("")
        lines.append(
            f"Trend: {direction} {abs(report.trend_change_pct):.0f}% "
            f"{'decrease' if report.trend_change_pct < 0 else 'increase'} "
            f"from previous period ({report.prev_period_total:,} violations)"
        )

    if report.top_files:
        lines.append("")
        lines.append("Top files:")
        for i, (fp, count) in enumerate(report.top_files[:5], 1):
            display = fp if len(fp) <= 40 else "..." + fp[-37:]
            lines.append(f"  {i}. {display:<42s} {count:>4,} violations")

    if report.top_tools:
        lines.append("")
        lines.append("Top tools:")
        for i, (tool, count) in enumerate(report.top_tools[:5], 1):
            lines.append(f"  {i}. {tool:<42s} {count:>4,}")

    lines.append("")
    lines.append("Resolution:")
    lines.append(f"  Resolved:     {report.resolved_count:>5,}")
    lines.append(f"  Unresolved:   {report.unresolved_count:>5,}")
    lines.append(f"  Rate:         {report.resolution_pct:>5.1f}%")
    if report.avg_resolution_seconds is not None:
        hours = report.avg_resolution_seconds / 3600
        lines.append(f"  Avg time:     {hours:>5.1f}h")

    _append_compliance_section(lines, report)

    lines.append("")
    lines.append(f"Security posture: {report.security_posture}")
    if report.security_posture in POSTURE_LABELS:
        lines.append(f"  {POSTURE_LABELS[report.security_posture]}")

    return "\n".join(lines)


def _append_compliance_section(lines: List[str], report: AuditReport) -> None:
    if not report.compliance_features:
        return
    lines.append("")
    lines.append("Compliance Summary:")
    for feature, enabled in report.compliance_features.items():
        status = "✓ enabled" if enabled else "✗ disabled"
        count = report.violations_per_feature.get(feature, 0)
        count_str = f"{count:,} violations" if count > 0 else ""
        lines.append(f"  {feature:<25s} {status:<14s} {count_str}")


def format_audit_json(report: AuditReport) -> str:
    data = {
        "generated_at": report.generated_at,
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
        "trends": {
            "daily": report.time_trend,
            "previous_period_total": report.prev_period_total,
            "change_pct": report.trend_change_pct,
        },
        "top_violations": {
            "files": [{"path": fp, "count": c} for fp, c in report.top_files],
            "types": [{"type": t, "count": c} for t, c in report.top_types],
            "tools": [{"tool": t, "count": c} for t, c in report.top_tools],
        },
        "resolution": {
            "resolved": report.resolved_count,
            "unresolved": report.unresolved_count,
            "rate_pct": round(report.resolution_pct, 1),
            "avg_time_seconds": (
                round(report.avg_resolution_seconds, 1)
                if report.avg_resolution_seconds is not None
                else None
            ),
        },
        "compliance": {
            "features": report.compliance_features,
            "violations_per_feature": report.violations_per_feature,
        },
        "security_posture": report.security_posture,
    }
    return json.dumps(data, indent=2)


AUDIT_CSV_COLUMNS = [
    "timestamp",
    "violation_type",
    "severity",
    "action",
    "file_path",
    "tool",
    "session_id",
    "resolved",
    "resolved_at",
]


def format_audit_csv(violations: List[Dict], stream: TextIO) -> None:
    writer = csv.writer(stream)
    writer.writerow(AUDIT_CSV_COLUMNS)
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
                v.get("resolved_at", ""),
            ]
        )


def format_audit_html(report: AuditReport) -> str:
    start_display = report.time_range_start[:10] if report.time_range_start else "?"
    end_display = report.time_range_end[:10] if report.time_range_end else "?"
    gen_display = report.generated_at[:19] if report.generated_at else ""

    posture_color = {
        "GOOD": "#2e7d32",
        "FAIR": "#f57c00",
        "NEEDS ATTENTION": "#c62828",
        "UNKNOWN": "#757575",
    }.get(report.security_posture, "#757575")

    type_rows = ""
    if report.by_type:
        for vtype, count in report.by_type.items():
            pct = (
                count / report.total_violations * 100 if report.total_violations else 0
            )
            bar_w = int(pct * 2)
            type_rows += (
                f"<tr><td>{_esc(vtype)}</td><td>{count:,}</td>"
                f"<td>{pct:.1f}%</td>"
                f'<td><div style="background:#1976d2;height:16px;'
                f'width:{bar_w}px;border-radius:2px"></div></td></tr>\n'
            )

    severity_rows = ""
    if report.by_severity:
        sev_colors = {"critical": "#c62828", "high": "#e65100", "warning": "#f9a825"}
        for sev, count in report.by_severity.items():
            color = sev_colors.get(sev, "#757575")
            severity_rows += (
                f'<tr><td><span style="color:{color};font-weight:bold">'
                f"{_esc(sev)}</span></td><td>{count:,}</td></tr>\n"
            )

    action_rows = ""
    if report.by_action:
        for action, count in report.by_action.items():
            pct = (
                count / report.total_violations * 100 if report.total_violations else 0
            )
            action_rows += (
                f"<tr><td>{_esc(action)}</td>"
                f"<td>{count:,}</td><td>{pct:.1f}%</td></tr>\n"
            )

    trend_svg = _build_trend_svg(report.time_trend)
    trend_text = ""
    if report.trend_change_pct is not None:
        arrow = "&#9660;" if report.trend_change_pct < 0 else "&#9650;"
        word = "decrease" if report.trend_change_pct < 0 else "increase"
        trend_text = (
            f'<p style="font-size:1.1em">{arrow} '
            f"<strong>{abs(report.trend_change_pct):.0f}%</strong> {word} "
            f"from previous period ({report.prev_period_total:,} violations)</p>"
        )

    top_files_rows = ""
    for i, (fp, count) in enumerate(report.top_files[:10], 1):
        top_files_rows += (
            f"<tr><td>{i}</td><td>{_esc(fp)}</td><td>{count:,}</td></tr>\n"
        )

    top_tools_rows = ""
    for i, (tool, count) in enumerate(report.top_tools[:10], 1):
        top_tools_rows += (
            f"<tr><td>{i}</td><td>{_esc(tool)}</td><td>{count:,}</td></tr>\n"
        )

    avg_time_display = "N/A"
    if report.avg_resolution_seconds is not None:
        hours = report.avg_resolution_seconds / 3600
        avg_time_display = f"{hours:.1f}h"

    compliance_rows = ""
    if report.compliance_features:
        for feature, enabled in report.compliance_features.items():
            icon = "&#10003;" if enabled else "&#10007;"
            color = "#2e7d32" if enabled else "#c62828"
            vcount = report.violations_per_feature.get(feature, 0)
            compliance_rows += (
                f"<tr><td>{_esc(feature)}</td>"
                f'<td style="color:{color};font-weight:bold">{icon}</td>'
                f"<td>{vcount:,}</td></tr>\n"
            )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Guardian Audit Report</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       margin: 0; padding: 20px 40px; background: #fafafa; color: #212121; }}
h1 {{ margin-bottom: 4px; }}
.meta {{ color: #757575; margin-bottom: 24px; }}
.cards {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
.card {{ background: #fff; border-radius: 8px; padding: 16px 24px;
         box-shadow: 0 1px 3px rgba(0,0,0,.12); min-width: 140px; }}
.card .label {{ font-size: .85em; color: #757575; margin-bottom: 4px; }}
.card .value {{ font-size: 1.6em; font-weight: 600; }}
.section {{ background: #fff; border-radius: 8px; padding: 20px 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,.12); margin-bottom: 20px; }}
.section h2 {{ margin-top: 0; font-size: 1.1em; border-bottom: 1px solid #e0e0e0;
               padding-bottom: 8px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ text-align: left; padding: 6px 12px; border-bottom: 1px solid #eee; }}
th {{ font-weight: 600; color: #616161; font-size: .85em; text-transform: uppercase; }}
.posture {{ display: inline-block; padding: 4px 12px; border-radius: 4px;
            color: #fff; font-weight: 600; }}
</style>
</head>
<body>
<h1>AI Guardian Audit Report</h1>
<p class="meta">Period: {_esc(start_display)} to {_esc(end_display)} &middot;
Generated: {_esc(gen_display)}</p>

<div class="cards">
  <div class="card"><div class="label">Total Violations</div>
    <div class="value">{report.total_violations:,}</div></div>
  <div class="card"><div class="label">Resolved</div>
    <div class="value">{report.resolved_count:,}</div></div>
  <div class="card"><div class="label">Unresolved</div>
    <div class="value">{report.unresolved_count:,}</div></div>
  <div class="card"><div class="label">Sessions</div>
    <div class="value">{report.session_count:,}</div></div>
  <div class="card"><div class="label">Resolution Rate</div>
    <div class="value">{report.resolution_pct:.0f}%</div></div>
  <div class="card"><div class="label">Posture</div>
    <div class="value"><span class="posture"
      style="background:{posture_color}">{_esc(report.security_posture)}</span></div></div>
</div>

<div class="section">
<h2>Violations by Type</h2>
<table><tr><th>Type</th><th>Count</th><th>%</th><th></th></tr>
{type_rows}</table>
</div>

<div class="section">
<h2>Severity Distribution</h2>
<table><tr><th>Severity</th><th>Count</th></tr>
{severity_rows}</table>
</div>

<div class="section">
<h2>Actions Taken</h2>
<table><tr><th>Action</th><th>Count</th><th>%</th></tr>
{action_rows}</table>
</div>

<div class="section">
<h2>Daily Trend</h2>
{trend_text}
{trend_svg}
</div>

<div class="section">
<h2>Top Files</h2>
<table><tr><th>#</th><th>File</th><th>Violations</th></tr>
{top_files_rows}</table>
</div>

<div class="section">
<h2>Top Tools</h2>
<table><tr><th>#</th><th>Tool</th><th>Violations</th></tr>
{top_tools_rows}</table>
</div>

<div class="section">
<h2>Resolution Metrics</h2>
<table>
<tr><td>Resolved</td><td>{report.resolved_count:,}</td></tr>
<tr><td>Unresolved</td><td>{report.unresolved_count:,}</td></tr>
<tr><td>Resolution rate</td><td>{report.resolution_pct:.1f}%</td></tr>
<tr><td>Average time to resolution</td><td>{_esc(avg_time_display)}</td></tr>
</table>
</div>

<div class="section">
<h2>Compliance Summary</h2>
<table><tr><th>Feature</th><th>Status</th><th>Violations</th></tr>
{compliance_rows}</table>
</div>

<p style="color:#9e9e9e;text-align:center;margin-top:32px;font-size:.85em">
Generated by AI Guardian</p>
</body>
</html>"""


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _build_trend_svg(time_trend: List[Dict]) -> str:
    if not time_trend:
        return '<p style="color:#757575">No trend data available.</p>'

    entries = time_trend[-30:]
    max_count = max((t["count"] for t in entries), default=1)
    if max_count == 0:
        max_count = 1

    bar_width = 18
    gap = 4
    chart_height = 120
    label_height = 40
    svg_width = len(entries) * (bar_width + gap) + 20
    svg_height = chart_height + label_height + 10

    bars = []
    for i, entry in enumerate(entries):
        x = 10 + i * (bar_width + gap)
        bar_h = int(entry["count"] / max_count * chart_height)
        y = chart_height - bar_h
        bars.append(
            f'<rect x="{x}" y="{y}" width="{bar_width}" height="{bar_h}" '
            f'fill="#1976d2" rx="2"/>'
        )
        bars.append(
            f'<text x="{x + bar_width // 2}" y="{y - 4}" text-anchor="middle" '
            f'font-size="10" fill="#616161">{entry["count"]}</text>'
        )
        if i % max(1, len(entries) // 7) == 0:
            label = entry["date"][5:]
            bars.append(
                f'<text x="{x + bar_width // 2}" y="{chart_height + 14}" '
                f'text-anchor="middle" font-size="10" fill="#9e9e9e">'
                f"{label}</text>"
            )

    return (
        f'<svg width="{svg_width}" height="{svg_height}" '
        f'xmlns="http://www.w3.org/2000/svg">\n' + "\n".join(bars) + "\n</svg>"
    )


def audit_command(args) -> int:
    try:
        since_value = getattr(args, "since", "30d") or "30d"
        _parse_since(since_value)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    until_value = getattr(args, "until", None)
    if until_value:
        try:
            _parse_since(until_value)
        except ValueError:
            print(
                f"Error: Invalid --until value: '{until_value}'. "
                f"Use Nd for days (e.g. 30d) or ISO date (e.g. 2026-05-01)",
                file=sys.stderr,
            )
            return 1

    computer = AuditComputer(
        since=getattr(args, "since", "30d"),
        until=until_value,
        violation_type=getattr(args, "type", None),
        severity=getattr(args, "severity", None),
    )

    if getattr(args, "csv", False):
        violations = computer._read_violations()
        format_audit_csv(violations, sys.stdout)
        return 0

    report = computer.compute()

    if getattr(args, "html", False):
        print(format_audit_html(report))
    elif getattr(args, "json", False):
        print(format_audit_json(report))
    else:
        print(format_audit_human(report))

    return 0
