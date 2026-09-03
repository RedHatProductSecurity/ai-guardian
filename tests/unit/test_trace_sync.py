"""Tests for daemon/trace_sync.py — remote trace cache engine."""

import json
import os
import time
from datetime import datetime, timezone
from unittest import mock

import pytest

from ai_guardian.daemon.trace_sync import (
    _summary_to_meta,
    catchup_pull,
    cleanup_stale_cache,
    get_daemon_cache_dir,
    get_remote_cache_dir,
    list_cached_remote_traces,
    persist_trace,
    persist_trace_meta,
    prune_cache_before_date,
    read_cached_remote_trace,
)


@pytest.fixture
def cache_root(tmp_path, monkeypatch):
    """Redirect remote cache dir to tmp_path."""
    trace_dir = tmp_path / "sdk" / "traces"
    trace_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "ai_guardian.daemon.trace_sync.get_remote_cache_dir",
        lambda: trace_dir / "_remote",
    )
    return trace_dir / "_remote"


def _make_trace_doc(agent="test-agent", started="2026-01-01T10:00:00"):
    return {
        "agent_name": agent,
        "model": "claude-sonnet-4-20250514",
        "started_at": started,
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "trace": [{"turn": 1, "steps": []}],
    }


def _make_summary(agent="test-agent", started="2026-01-01T10:00:00", filename=""):
    return {
        "filename": filename or f"{agent}_20260101-100000_abcd1234.json",
        "agent_name": agent,
        "model": "claude-sonnet-4-20250514",
        "started_at": started,
        "stop_reason": "end_turn",
        "is_active": False,
        "total_turns": 5,
        "total_tokens": {"input_tokens": 100, "output_tokens": 50},
        "violation_count": 0,
    }


class TestGetRemoteCacheDir:
    def test_returns_path_under_traces(self):
        result = get_remote_cache_dir()
        assert result.name == "_remote"
        assert "traces" in str(result.parent)


class TestGetDaemonCacheDir:
    def test_normal_name(self):
        result = get_daemon_cache_dir("my-daemon")
        assert result.name == "my-daemon"

    def test_sanitizes_unsafe_chars(self):
        result = get_daemon_cache_dir("daemon/with:bad\\chars")
        assert "/" not in result.name
        assert "\\" not in result.name
        assert ":" not in result.name

    def test_dots_replaced(self):
        result = get_daemon_cache_dir("..")
        assert result.name == "_unknown"

    def test_empty_name(self):
        result = get_daemon_cache_dir("")
        assert result.name == "_unknown"


class TestPersistTrace:
    def test_writes_json_and_meta(self, cache_root):
        filename = "agent_20260101-100000_abcd1234.json"
        doc = _make_trace_doc()
        result = persist_trace("daemon-a", filename, doc)
        assert result is not None
        assert os.path.isfile(result)
        meta_path = result.rsplit(".json", 1)[0] + ".meta.json"
        assert os.path.isfile(meta_path)

        with open(result) as f:
            stored = json.load(f)
        assert stored["agent_name"] == "test-agent"

    def test_creates_daemon_dir(self, cache_root):
        filename = "agent_20260101-100000_abcd1234.json"
        persist_trace("new-daemon", filename, _make_trace_doc())
        assert (cache_root / "new-daemon").is_dir()

    def test_rejects_invalid_filename(self, cache_root):
        result = persist_trace("daemon", "../evil.json", _make_trace_doc())
        assert result is None


class TestPersistTraceMeta:
    def test_writes_meta_sidecar(self, cache_root):
        filename = "agent_20260101-100000_abcd1234.json"
        summary = _make_summary(filename=filename)
        result = persist_trace_meta("daemon-a", filename, summary)
        assert result is not None
        assert result.endswith(".meta.json")
        assert os.path.isfile(result)

    def test_rejects_invalid_filename(self, cache_root):
        result = persist_trace_meta("daemon", "../../bad.json", _make_summary())
        assert result is None


class TestSummaryToMeta:
    def test_maps_fields(self):
        summary = _make_summary()
        summary["run_id"] = "pipeline/case-1"
        summary["run_sequence"] = 2
        meta = _summary_to_meta(summary)
        assert meta["agent_name"] == "test-agent"
        assert meta["usage"]["input_tokens"] == 100
        assert meta["run_id"] == "pipeline/case-1"
        assert meta["run_sequence"] == 2

    def test_omits_run_id_when_absent(self):
        meta = _summary_to_meta(_make_summary())
        assert "run_id" not in meta


class TestCatchupPull:
    def test_fetches_completed_traces(self, cache_root):
        client = mock.MagicMock()
        target = mock.MagicMock()
        target.name = "remote-1"

        fname = "agent_20260101-100000_abcd1234.json"
        client.get_traces.return_value = {"traces": [_make_summary(filename=fname)]}
        client.get_trace_detail.return_value = _make_trace_doc()

        count = catchup_pull(client, target)
        assert count == 1
        assert os.path.isfile(str(cache_root / "remote-1" / fname))

    def test_skips_already_cached(self, cache_root):
        fname = "agent_20260101-100000_abcd1234.json"
        daemon_dir = cache_root / "remote-1"
        daemon_dir.mkdir(parents=True)
        (daemon_dir / fname).write_text("{}")

        client = mock.MagicMock()
        target = mock.MagicMock()
        target.name = "remote-1"
        client.get_traces.return_value = {"traces": [_make_summary(filename=fname)]}

        count = catchup_pull(client, target)
        assert count == 0
        client.get_trace_detail.assert_not_called()

    def test_writes_meta_only_for_active(self, cache_root):
        client = mock.MagicMock()
        target = mock.MagicMock()
        target.name = "remote-1"

        summary = _make_summary()
        summary["stop_reason"] = "in_progress"
        summary["is_active"] = True
        client.get_traces.return_value = {"traces": [summary]}

        count = catchup_pull(client, target)
        assert count == 0
        client.get_trace_detail.assert_not_called()

    def test_respects_max_fetches(self, cache_root):
        client = mock.MagicMock()
        target = mock.MagicMock()
        target.name = "remote-1"

        traces = []
        for i in range(5):
            s = _make_summary(
                filename=f"agent_20260101-10000{i}_abcd123{i}.json",
                started=f"2026-01-01T10:00:0{i}",
            )
            traces.append(s)

        client.get_traces.return_value = {"traces": traces}
        client.get_trace_detail.return_value = _make_trace_doc()

        count = catchup_pull(client, target, max_fetches=2)
        assert count == 2
        assert client.get_trace_detail.call_count == 2

    def test_handles_listing_failure(self, cache_root):
        client = mock.MagicMock()
        target = mock.MagicMock()
        target.name = "broken"
        client.get_traces.side_effect = Exception("timeout")

        count = catchup_pull(client, target)
        assert count == 0


class TestCleanupStaleCache:
    def test_deletes_old_files(self, cache_root):
        daemon_dir = cache_root / "old-daemon"
        daemon_dir.mkdir(parents=True)
        old_file = daemon_dir / "agent_20260101-100000_abcd1234.json"
        old_file.write_text("{}")
        old_meta = daemon_dir / "agent_20260101-100000_abcd1234.meta.json"
        old_meta.write_text("{}")
        old_time = time.time() - (100 * 86400)
        os.utime(str(old_file), (old_time, old_time))
        os.utime(str(old_meta), (old_time, old_time))

        deleted = cleanup_stale_cache(retention_days=90)
        assert deleted == 2
        assert not old_file.exists()

    def test_preserves_young_files(self, cache_root):
        daemon_dir = cache_root / "daemon"
        daemon_dir.mkdir(parents=True)
        new_file = daemon_dir / "agent_20260101-100000_abcd1234.json"
        new_file.write_text("{}")

        deleted = cleanup_stale_cache(retention_days=90)
        assert deleted == 0
        assert new_file.exists()

    def test_removes_empty_dirs(self, cache_root):
        daemon_dir = cache_root / "empty-daemon"
        daemon_dir.mkdir(parents=True)
        f = daemon_dir / "agent_20260101-100000_abcd1234.json"
        f.write_text("{}")
        old_time = time.time() - (100 * 86400)
        os.utime(str(f), (old_time, old_time))

        cleanup_stale_cache(retention_days=90)
        assert not daemon_dir.exists()

    def test_noop_when_no_cache(self, cache_root):
        assert cleanup_stale_cache(retention_days=90) == 0


class TestListCachedRemoteTraces:
    def test_lists_from_multiple_daemons(self, cache_root):
        for name in ("daemon-a", "daemon-b"):
            d = cache_root / name
            d.mkdir(parents=True)
            fname = "agent_20260101-100000_abcd1234.json"
            doc = _make_trace_doc(agent=f"agent-{name}")
            with open(str(d / fname), "w") as f:
                json.dump(doc, f)
            from ai_guardian.daemon.traces import write_trace_meta

            write_trace_meta(str(d / fname), doc)

        traces = list_cached_remote_traces()
        assert len(traces) == 2
        sources = {t["daemon_source"] for t in traces}
        assert sources == {"daemon-a", "daemon-b"}

    def test_empty_cache(self, cache_root):
        assert list_cached_remote_traces() == []

    def test_filters_by_agent_name(self, cache_root):
        d = cache_root / "daemon"
        d.mkdir(parents=True)
        for i, name in enumerate(("triage", "fixer")):
            fname = f"{name}_20260101-10000{i}_abcd123{i}.json"
            doc = _make_trace_doc(agent=name)
            with open(str(d / fname), "w") as f:
                json.dump(doc, f)
            from ai_guardian.daemon.traces import write_trace_meta

            write_trace_meta(str(d / fname), doc)

        traces = list_cached_remote_traces(agent_name="triage")
        assert len(traces) == 1
        assert traces[0]["agent_name"] == "triage"


class TestReadCachedRemoteTrace:
    def test_reads_cached_trace(self, cache_root):
        d = cache_root / "daemon-x"
        d.mkdir(parents=True)
        fname = "agent_20260101-100000_abcd1234.json"
        doc = _make_trace_doc()
        with open(str(d / fname), "w") as f:
            json.dump(doc, f)

        result = read_cached_remote_trace("daemon-x", fname)
        assert result is not None
        assert result["agent_name"] == "test-agent"

    def test_returns_none_for_missing(self, cache_root):
        result = read_cached_remote_trace(
            "nonexistent", "foo_20260101-100000_abcd1234.json"
        )
        assert result is None


class TestPruneCacheBeforeDate:
    def test_prunes_old_traces(self, cache_root):
        d = cache_root / "daemon"
        d.mkdir(parents=True)
        fname = "agent_20250101-100000_abcd1234.json"
        doc = _make_trace_doc(started="2025-01-01T10:00:00")
        with open(str(d / fname), "w") as f:
            json.dump(doc, f)
        from ai_guardian.daemon.traces import write_trace_meta

        write_trace_meta(str(d / fname), doc)

        deleted = prune_cache_before_date("2026-01-01")
        assert deleted == 1
        assert not (d / fname).exists()

    def test_dry_run_does_not_delete(self, cache_root):
        d = cache_root / "daemon"
        d.mkdir(parents=True)
        fname = "agent_20250101-100000_abcd1234.json"
        doc = _make_trace_doc(started="2025-01-01T10:00:00")
        with open(str(d / fname), "w") as f:
            json.dump(doc, f)
        from ai_guardian.daemon.traces import write_trace_meta

        write_trace_meta(str(d / fname), doc)

        deleted = prune_cache_before_date("2026-01-01", dry_run=True)
        assert deleted == 1
        assert (d / fname).exists()

    def test_invalid_date_returns_zero(self, cache_root):
        assert prune_cache_before_date("not-a-date") == 0


class TestPushTraceToRemoteFallback:
    """Test that direct-mode SDK falls back to AI_GUARDIAN_TRACE_ENDPOINT."""

    def test_pushes_to_remote_when_no_local_daemon(self, monkeypatch):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        monkeypatch.setattr(
            "ai_guardian.integrations.anthropic.agent.GuardedAgent._push_trace_to_remote",
            mock.MagicMock(),
        )
        pid_path = mock.MagicMock()
        pid_path.exists.return_value = False
        monkeypatch.setattr("ai_guardian.daemon.get_pid_path", lambda: pid_path)

        GuardedAgent._push_trace_to_daemon("test_20260101-100000_abcd1234.json", {})
        GuardedAgent._push_trace_to_remote.assert_called_once()

    def test_no_push_when_endpoint_unset(self, monkeypatch):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        monkeypatch.delenv("AI_GUARDIAN_TRACE_ENDPOINT", raising=False)
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            GuardedAgent._push_trace_to_remote("test_20260101-100000_abcd1234.json", {})
            mock_urlopen.assert_not_called()

    def test_pushes_to_endpoint_when_set(self, monkeypatch):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        monkeypatch.setenv("AI_GUARDIAN_TRACE_ENDPOINT", "tray-host:63152")
        monkeypatch.setenv("AI_GUARDIAN_TRACE_AUTH_TOKEN", "trace-token")
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            GuardedAgent._push_trace_to_remote(
                "test_20260101-100000_abcd1234.json", {"agent_name": "test"}
            )
            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            assert "/api/traces/remote" in req.full_url
            assert "tray-host:63152" in req.full_url
            assert req.get_header("Authorization") == "Bearer trace-token"
