"""Tests for the latency_logger module — timer, logger, computer, formatters."""

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from ai_guardian.reporting.latency import (
    LatencyComputer,
    LatencyLogger,
    LatencyReport,
    _CheckTimer,
    _compute_stats,
    _parse_since,
    _parse_timestamp,
    format_latency_human,
    format_latency_json,
)


class TestCheckTimer:
    def test_enabled_records_timing(self):
        timer = _CheckTimer(enabled=True)
        with timer.check("test"):
            time.sleep(0.005)
        timings = timer.to_dict()
        assert "test" in timings
        assert timings["test"] > 1.0

    def test_disabled_records_nothing(self):
        timer = _CheckTimer(enabled=False)
        with timer.check("test"):
            time.sleep(0.005)
        assert timer.to_dict() == {}

    def test_disabled_total_ms_zero(self):
        timer = _CheckTimer(enabled=False)
        assert timer.total_ms() == 0.0

    def test_accumulates_same_check(self):
        timer = _CheckTimer(enabled=True)
        with timer.check("scan"):
            time.sleep(0.005)
        with timer.check("scan"):
            time.sleep(0.005)
        assert timer.to_dict()["scan"] > 5.0

    def test_multiple_checks(self):
        timer = _CheckTimer(enabled=True)
        with timer.check("a"):
            pass
        with timer.check("b"):
            pass
        assert "a" in timer.to_dict()
        assert "b" in timer.to_dict()

    def test_total_ms_positive(self):
        timer = _CheckTimer(enabled=True)
        with timer.check("x"):
            time.sleep(0.005)
        assert timer.total_ms() > 1.0

    def test_exception_still_records(self):
        timer = _CheckTimer(enabled=True)
        with pytest.raises(ValueError):
            with timer.check("fail"):
                raise ValueError("boom")
        assert "fail" in timer.to_dict()
        assert timer.to_dict()["fail"] >= 0.0


class TestCheckTimerAskWait:
    """Tests for ask dialog wait time tracking in _CheckTimer (#1159)."""

    def test_add_ask_wait_accumulates(self):
        timer = _CheckTimer(enabled=True)
        timer.add_ask_wait(100.0)
        timer.add_ask_wait(200.0)
        assert timer.ask_wait_total_ms == 300.0

    def test_processing_ms_excludes_ask_wait(self):
        timer = _CheckTimer(enabled=True)
        time.sleep(0.05)
        total_before = timer.total_ms()
        timer.add_ask_wait(total_before * 0.5)
        processing = timer.processing_ms()
        total = timer.total_ms()
        assert total > 0
        assert processing < total
        assert processing == pytest.approx(total - total_before * 0.5, abs=5.0)

    def test_processing_ms_clamped_to_zero(self):
        """When ask_wait exceeds total (e.g. injected large value), clamp to 0."""
        timer = _CheckTimer(enabled=True)
        timer.add_ask_wait(999999.0)
        assert timer.processing_ms() == 0.0

    def test_ask_wait_zero_by_default(self):
        timer = _CheckTimer(enabled=True)
        assert timer.ask_wait_total_ms == 0.0
        assert timer.processing_ms() == pytest.approx(timer.total_ms(), abs=1.0)

    def test_disabled_timer_ignores_ask_wait(self):
        timer = _CheckTimer(enabled=False)
        timer.add_ask_wait(100.0)
        assert timer.ask_wait_total_ms == 0.0
        assert timer.processing_ms() == 0.0

    def test_negative_ask_wait_ignored(self):
        timer = _CheckTimer(enabled=True)
        timer.add_ask_wait(-50.0)
        assert timer.ask_wait_total_ms == 0.0


def _recent_ts(offset_seconds=0):
    """Generate a recent UTC timestamp string that won't expire from rotation."""
    dt = datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)
    return dt.isoformat().replace("+00:00", "Z")


class TestLatencyLogger:
    def test_log_timing_creates_file(self, tmp_path):
        log_path = tmp_path / "latency.jsonl"
        ll = LatencyLogger(
            log_path=log_path,
            config={"enabled": True, "max_entries": 100, "retention_days": 30},
        )
        ll.log_timing(
            {
                "timestamp": _recent_ts(),
                "hook_event": "PreToolUse",
                "tool": "Bash",
                "total_ms": 10.5,
                "checks": {"secret_scanning": 5.2},
            }
        )
        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["hook_event"] == "PreToolUse"
        assert entry["total_ms"] == 10.5

    def test_disabled_skips_write(self, tmp_path):
        log_path = tmp_path / "latency.jsonl"
        ll = LatencyLogger(log_path=log_path, config={"enabled": False})
        ll.log_timing(
            {
                "timestamp": _recent_ts(),
                "hook_event": "PreToolUse",
                "total_ms": 10.0,
                "checks": {},
            }
        )
        assert not log_path.exists()

    def test_default_config_uses_shared_config_loader(self, tmp_path):
        log_path = tmp_path / "latency.jsonl"
        effective_config = {
            "enabled": True,
            "max_entries": 25,
            "retention_days": 7,
        }
        with patch(
            "ai_guardian.config.loaders._load_latency_tracking_config",
            return_value=(effective_config, None),
        ):
            ll = LatencyLogger(log_path=log_path)

        assert ll.config == effective_config
        assert ll._is_enabled()

    def test_project_config_is_used_for_latency_tracking(self, tmp_path):
        from ai_guardian.config.loaders import _clear_config_cache
        from ai_guardian.config.utils import (
            clear_project_dir_override,
            set_project_dir_override,
        )

        project_dir = tmp_path / "project"
        config_path = project_dir / ".ai-guardian" / "ai-guardian.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            json.dumps({"latency_tracking": {"enabled": True}}),
            encoding="utf-8",
        )

        set_project_dir_override(str(project_dir))
        try:
            _clear_config_cache()
            ll = LatencyLogger(log_path=tmp_path / "latency.jsonl")
        finally:
            clear_project_dir_override()
            _clear_config_cache()

        assert ll.config["enabled"] is True
        assert ll.config["max_entries"] == 5000
        assert ll.config["retention_days"] == 30

    def test_read_entries_with_since(self, tmp_path):
        log_path = tmp_path / "latency.jsonl"
        ll = LatencyLogger(
            log_path=log_path,
            config={"enabled": True, "max_entries": 100, "retention_days": 30},
        )
        old_ts = (
            (datetime.now(timezone.utc) - timedelta(days=10))
            .isoformat()
            .replace("+00:00", "Z")
        )
        new_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ll.log_timing(
            {
                "timestamp": old_ts,
                "hook_event": "PreToolUse",
                "total_ms": 1.0,
                "checks": {},
            }
        )
        ll.log_timing(
            {
                "timestamp": new_ts,
                "hook_event": "PostToolUse",
                "total_ms": 2.0,
                "checks": {},
            }
        )

        since = datetime.now(timezone.utc) - timedelta(days=5)
        entries = ll.read_entries(since=since)
        assert len(entries) == 1
        assert entries[0]["hook_event"] == "PostToolUse"

    def test_read_entries_no_filter(self, tmp_path):
        log_path = tmp_path / "latency.jsonl"
        ll = LatencyLogger(
            log_path=log_path,
            config={"enabled": True, "max_entries": 100, "retention_days": 30},
        )
        ll.log_timing(
            {
                "timestamp": _recent_ts(),
                "hook_event": "A",
                "total_ms": 1.0,
                "checks": {},
            }
        )
        ll.log_timing(
            {
                "timestamp": _recent_ts(1),
                "hook_event": "B",
                "total_ms": 2.0,
                "checks": {},
            }
        )
        entries = ll.read_entries()
        assert len(entries) == 2

    def test_rotation_max_entries(self, tmp_path):
        log_path = tmp_path / "latency.jsonl"
        ll = LatencyLogger(
            log_path=log_path,
            config={"enabled": True, "max_entries": 5, "retention_days": 30},
        )
        now = datetime.now(timezone.utc)
        for i in range(10):
            ts = (now - timedelta(seconds=10 - i)).isoformat().replace("+00:00", "Z")
            ll.log_timing(
                {
                    "timestamp": ts,
                    "hook_event": f"E{i}",
                    "total_ms": float(i),
                    "checks": {},
                }
            )
        entries = ll.read_entries()
        assert len(entries) <= 5

    def test_clear_log(self, tmp_path):
        log_path = tmp_path / "latency.jsonl"
        ll = LatencyLogger(
            log_path=log_path,
            config={"enabled": True, "max_entries": 100, "retention_days": 30},
        )
        ll.log_timing(
            {
                "timestamp": _recent_ts(),
                "hook_event": "A",
                "total_ms": 1.0,
                "checks": {},
            }
        )
        assert log_path.exists()
        ll.clear_log()
        assert not log_path.exists()

    def test_read_empty_log(self, tmp_path):
        log_path = tmp_path / "latency.jsonl"
        ll = LatencyLogger(log_path=log_path, config={"enabled": True})
        entries = ll.read_entries()
        assert entries == []


class TestComputeStats:
    def test_empty_list(self):
        stats = _compute_stats([])
        assert stats["count"] == 0
        assert stats["avg"] == 0.0

    def test_single_value(self):
        stats = _compute_stats([42.0])
        assert stats["count"] == 1
        assert stats["avg"] == 42.0
        assert stats["stddev"] == 0.0
        assert stats["p95"] == 42.0

    def test_multiple_values(self):
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        stats = _compute_stats(vals)
        assert stats["count"] == 5
        assert stats["avg"] == 30.0
        assert stats["min"] == 10.0
        assert stats["max"] == 50.0
        assert stats["p95"] == 50.0

    def test_stddev(self):
        vals = [10.0, 10.0, 10.0]
        stats = _compute_stats(vals)
        assert stats["stddev"] == 0.0

    def test_p95_large_set(self):
        vals = list(range(1, 101))
        stats = _compute_stats([float(v) for v in vals])
        assert stats["p95"] == 95.0


class TestLatencyComputer:
    def test_empty_data(self):
        with patch.object(LatencyLogger, "read_entries", return_value=[]):
            computer = LatencyComputer(since_days=7)
            report = computer.compute()
            assert report.invocation_count == 0
            assert report.hook_stats == []
            assert report.check_stats == []

    def test_empty_data_reports_paused_state(self):
        from ai_guardian.daemon.state import DaemonState

        with (
            patch.object(LatencyLogger, "read_entries", return_value=[]),
            patch.object(DaemonState, "is_paused_on_disk", return_value=True),
        ):
            report = LatencyComputer(since_days=7).compute()

        assert report.paused is True

    def test_empty_data_checks_project_pause_state(self):
        from ai_guardian.daemon.state import DaemonState

        with (
            patch.object(LatencyLogger, "read_entries", return_value=[]),
            patch.object(
                DaemonState, "is_paused_on_disk", return_value=True
            ) as mock_is_paused,
        ):
            LatencyComputer(since_days=7).compute()

        mock_is_paused.assert_called_once()
        assert mock_is_paused.call_args.kwargs["cwd"]

    def test_computes_hook_stats(self):
        entries = [
            {
                "timestamp": _recent_ts(),
                "hook_event": "PreToolUse",
                "total_ms": 10.0,
                "checks": {"secret_scanning": 5.0, "permissions": 1.0},
            },
            {
                "timestamp": _recent_ts(1),
                "hook_event": "PreToolUse",
                "total_ms": 20.0,
                "checks": {"secret_scanning": 15.0, "permissions": 2.0},
            },
            {
                "timestamp": "2026-06-10T12:00:02Z",
                "hook_event": "PostToolUse",
                "total_ms": 8.0,
                "checks": {"pii_detection": 4.0},
            },
        ]
        with patch.object(LatencyLogger, "read_entries", return_value=entries):
            computer = LatencyComputer(since_days=1)
            report = computer.compute()
            assert report.invocation_count == 3
            assert len(report.hook_stats) == 2

            pre_stat = next(
                s for s in report.hook_stats if s["hook_event"] == "PreToolUse"
            )
            assert pre_stat["count"] == 2
            assert pre_stat["avg"] == 15.0

            post_stat = next(
                s for s in report.hook_stats if s["hook_event"] == "PostToolUse"
            )
            assert post_stat["count"] == 1
            assert post_stat["avg"] == 8.0

    def test_computes_check_stats(self):
        entries = [
            {
                "timestamp": _recent_ts(),
                "hook_event": "PreToolUse",
                "total_ms": 10.0,
                "checks": {"secret_scanning": 5.0},
            },
            {
                "timestamp": _recent_ts(1),
                "hook_event": "UserPromptSubmit",
                "total_ms": 30.0,
                "checks": {"secret_scanning": 20.0, "prompt_injection": 8.0},
            },
        ]
        with patch.object(LatencyLogger, "read_entries", return_value=entries):
            computer = LatencyComputer(since_days=1)
            report = computer.compute()
            ss = next(
                s for s in report.check_stats if s["check_name"] == "secret_scanning"
            )
            assert ss["count"] == 2
            assert ss["avg"] == 12.5
            assert "PreToolUse" in ss["hooks"]
            assert "UserPromptSubmit" in ss["hooks"]

    def test_zero_ms_checks_excluded(self):
        entries = [
            {
                "timestamp": _recent_ts(),
                "hook_event": "PreToolUse",
                "total_ms": 5.0,
                "checks": {"secret_scanning": 3.0, "prompt_injection": 0.0},
            },
        ]
        with patch.object(LatencyLogger, "read_entries", return_value=entries):
            computer = LatencyComputer(since_days=1)
            report = computer.compute()
            check_names = [s["check_name"] for s in report.check_stats]
            assert "secret_scanning" in check_names
            assert "prompt_injection" not in check_names

    def test_uses_processing_ms_over_total_ms(self):
        """Hook stats should use processing_ms (excludes ask wait) when available."""
        entries = [
            {
                "timestamp": _recent_ts(),
                "hook_event": "PreToolUse",
                "total_ms": 45050.0,
                "processing_ms": 50.0,
                "ask_dialog_ms": 45000.0,
                "checks": {"secret_scanning": 30.0},
            },
        ]
        with patch.object(LatencyLogger, "read_entries", return_value=entries):
            computer = LatencyComputer(since_days=1)
            report = computer.compute()
            hook_stat = report.hook_stats[0]
            assert hook_stat["avg"] == 50.0
            assert report.ask_dialog_count == 1
            assert report.ask_dialog_stats["avg"] == 45000.0

    def test_backward_compat_no_processing_ms(self):
        """Old entries without processing_ms fall back to total_ms."""
        entries = [
            {
                "timestamp": _recent_ts(),
                "hook_event": "PreToolUse",
                "total_ms": 25.0,
                "checks": {},
            },
        ]
        with patch.object(LatencyLogger, "read_entries", return_value=entries):
            computer = LatencyComputer(since_days=1)
            report = computer.compute()
            assert report.hook_stats[0]["avg"] == 25.0
            assert report.ask_dialog_count == 0
            assert report.ask_dialog_stats is None

    def test_ask_dialog_stats_aggregation(self):
        """Multiple ask dialog entries should produce valid aggregate stats."""
        entries = [
            {
                "timestamp": _recent_ts(),
                "hook_event": "PreToolUse",
                "total_ms": 3050.0,
                "processing_ms": 50.0,
                "ask_dialog_ms": 3000.0,
                "checks": {},
            },
            {
                "timestamp": _recent_ts(1),
                "hook_event": "PreToolUse",
                "total_ms": 5040.0,
                "processing_ms": 40.0,
                "ask_dialog_ms": 5000.0,
                "checks": {},
            },
            {
                "timestamp": "2026-06-10T12:00:02Z",
                "hook_event": "PreToolUse",
                "total_ms": 30.0,
                "processing_ms": 30.0,
                "checks": {},
            },
        ]
        with patch.object(LatencyLogger, "read_entries", return_value=entries):
            computer = LatencyComputer(since_days=1)
            report = computer.compute()
            assert report.ask_dialog_count == 2
            assert report.ask_dialog_stats["avg"] == 4000.0
            assert report.ask_dialog_stats["min"] == 3000.0
            assert report.ask_dialog_stats["max"] == 5000.0


class TestFormatLatencyHuman:
    def test_empty_report(self):
        report = LatencyReport()
        output = format_latency_human(report)
        assert "No latency data" in output
        assert "latency_tracking.enabled" in output

    def test_empty_report_explains_paused_state(self):
        output = format_latency_human(LatencyReport(paused=True))
        assert "Latency collection is paused" in output
        assert "trigger a new hook invocation" in output

    def test_with_data(self):
        report = LatencyReport(
            hook_stats=[
                {
                    "hook_event": "PreToolUse",
                    "avg": 12.5,
                    "stddev": 3.0,
                    "p95": 18.0,
                    "min": 5.0,
                    "max": 25.0,
                    "count": 100,
                }
            ],
            check_stats=[
                {
                    "check_name": "secret_scanning",
                    "avg": 8.0,
                    "stddev": 2.0,
                    "p95": 12.0,
                    "min": 1.0,
                    "max": 20.0,
                    "count": 100,
                    "hooks": "PreToolUse",
                }
            ],
            invocation_count=100,
        )
        output = format_latency_human(report)
        assert "Hook Processing Time" in output
        assert "PreToolUse" in output
        assert "secret_scanning" in output
        assert "100" in output

    def test_with_ask_dialog_data(self):
        report = LatencyReport(
            hook_stats=[
                {
                    "hook_event": "PreToolUse",
                    "avg": 50.0,
                    "stddev": 5.0,
                    "p95": 60.0,
                    "min": 40.0,
                    "max": 70.0,
                    "count": 10,
                }
            ],
            check_stats=[],
            invocation_count=10,
            ask_dialog_count=3,
            ask_dialog_stats={
                "avg": 5000.0,
                "stddev": 1000.0,
                "p95": 6500.0,
                "min": 3000.0,
                "max": 7000.0,
                "count": 3,
            },
        )
        output = format_latency_human(report)
        assert "Ask Dialog Wait Time" in output
        assert "excluded from processing stats" in output
        assert "Dialogs: 3" in output

    def test_no_ask_dialog_section_when_zero(self):
        report = LatencyReport(
            hook_stats=[
                {
                    "hook_event": "PreToolUse",
                    "avg": 50.0,
                    "stddev": 5.0,
                    "p95": 60.0,
                    "min": 40.0,
                    "max": 70.0,
                    "count": 10,
                }
            ],
            invocation_count=10,
        )
        output = format_latency_human(report)
        assert "Ask Dialog" not in output


class TestFormatLatencyJson:
    def test_empty_report(self):
        report = LatencyReport()
        output = format_latency_json(report)
        data = json.loads(output)
        assert data["invocation_count"] == 0
        assert data["hook_stats"] == []
        assert data["paused"] is False

    def test_with_data(self):
        report = LatencyReport(
            hook_stats=[{"hook_event": "PreToolUse", "avg": 10.0}],
            check_stats=[{"check_name": "pii", "avg": 5.0}],
            invocation_count=50,
            time_range_start="2026-06-01",
            time_range_end="2026-06-10",
        )
        output = format_latency_json(report)
        data = json.loads(output)
        assert data["invocation_count"] == 50
        assert len(data["hook_stats"]) == 1
        assert data["time_range"]["start"] == "2026-06-01"


class TestParseSince:
    def test_days_format(self):
        result = _parse_since("7d")
        expected = datetime.now(timezone.utc) - timedelta(days=7)
        assert abs((result - expected).total_seconds()) < 2

    def test_iso_date(self):
        result = _parse_since("2026-06-01")
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 1

    def test_invalid(self):
        with pytest.raises(ValueError):
            _parse_since("invalid")


class TestParseTimestamp:
    def test_z_suffix(self):
        result = _parse_timestamp("2026-06-10T12:00:00Z")
        assert result.year == 2026
        assert result.tzinfo is not None

    def test_none(self):
        result = _parse_timestamp(None)
        assert result.year == 1970

    def test_invalid(self):
        result = _parse_timestamp("not-a-date")
        assert result.year == 1970


class TestCliLatencyRouting:
    def test_latency_flag_routes_correctly(self):
        from types import SimpleNamespace
        from ai_guardian.reporting.metrics import metrics_command

        args = SimpleNamespace(
            latency=True,
            since="30d",
            json=False,
            reset=False,
            html=False,
            until=None,
            severity=None,
        )
        with patch.object(LatencyLogger, "read_entries", return_value=[]):
            result = metrics_command(args)
            assert result == 0

    def test_latency_json_flag(self, capsys):
        from types import SimpleNamespace
        from ai_guardian.reporting.metrics import metrics_command

        args = SimpleNamespace(
            latency=True,
            since="7d",
            json=True,
            reset=False,
            html=False,
            until=None,
            severity=None,
        )
        with patch.object(LatencyLogger, "read_entries", return_value=[]):
            result = metrics_command(args)
            assert result == 0
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert "hook_stats" in data


class TestFailOpen:
    def test_log_timing_survives_write_error(self, tmp_path):
        log_path = tmp_path / "nonexistent_dir" / "sub" / "latency.jsonl"
        ll = LatencyLogger(
            log_path=log_path,
            config={"enabled": True, "max_entries": 100, "retention_days": 30},
        )
        ll.log_timing(
            {
                "timestamp": _recent_ts(),
                "hook_event": "A",
                "total_ms": 1.0,
                "checks": {},
            }
        )

    def test_read_entries_survives_missing_file(self, tmp_path):
        ll = LatencyLogger(
            log_path=tmp_path / "missing.jsonl", config={"enabled": True}
        )
        entries = ll.read_entries()
        assert entries == []
