"""Tests for daemon in-memory state management."""

import json
import os
import re
import sys
import time
import threading
from unittest import mock

import pytest

from ai_guardian.daemon.state import DaemonState


class TestCrossHookCorrelation:
    def test_store_and_retrieve_context(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        ctx = {"file_path": "/tmp/test.py", "findings": []}
        state.store_pretooluse_context("session1", "tool1", ctx)
        result = state.get_pretooluse_context("session1", "tool1")
        assert result == ctx

    def test_retrieve_nonexistent_context(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        result = state.get_pretooluse_context("session1", "tool1")
        assert result is None

    def test_context_expiry(self, tmp_path):
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            context_ttl=0.1,  # 100ms TTL
        )
        state.store_pretooluse_context("s1", "t1", {"data": "test"})
        time.sleep(0.15)
        result = state.get_pretooluse_context("s1", "t1")
        assert result is None

    def test_cleanup_expired_contexts(self, tmp_path):
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            context_ttl=0.1,
        )
        state.store_pretooluse_context("s1", "t1", {"data": "old"})
        state.store_pretooluse_context("s2", "t2", {"data": "old2"})
        time.sleep(0.15)
        state.store_pretooluse_context("s3", "t3", {"data": "new"})
        state.cleanup_expired_contexts()

        assert state.get_pretooluse_context("s1", "t1") is None
        assert state.get_pretooluse_context("s2", "t2") is None
        assert state.get_pretooluse_context("s3", "t3") == {"data": "new"}

    def test_none_session_id_ignored(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.store_pretooluse_context(None, "t1", {"data": "test"})
        assert state.get_pretooluse_context(None, "t1") is None

    def test_none_tool_use_id_ignored(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.store_pretooluse_context("s1", None, {"data": "test"})
        assert state.get_pretooluse_context("s1", None) is None


class TestConfigCaching:
    def test_load_config_on_init(self, tmp_path):
        config = {"secret_scanning": {"enabled": True}}
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps(config))

        state = DaemonState(config_path=config_path)
        assert state.get_config() == config

    def test_no_config_file(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        assert state.get_config() is None

    def test_config_reload_on_mtime_change(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"version": 1}))

        state = DaemonState(config_path=config_path)
        assert state.get_config()["version"] == 1

        # Modify config (ensure mtime changes)
        time.sleep(0.05)
        config_path.write_text(json.dumps({"version": 2}))

        result = state.get_config()
        assert result["version"] == 2

    def test_config_reload_clears_pattern_cache(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))

        state = DaemonState(config_path=config_path)
        state.get_compiled_pattern(r"\d+")
        assert state.get_stats()["cached_patterns"] > 0

        time.sleep(0.05)
        config_path.write_text(json.dumps({"v": 2}))
        state.get_config()  # triggers reload

        # Pattern cache should be cleared
        assert len(state._compiled_patterns) == 0

    def test_force_reload_config(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))

        state = DaemonState(config_path=config_path)

        # Modify without waiting for mtime to differ
        config_path.write_text(json.dumps({"v": 2}))
        state.force_reload_config()

        assert state.get_config()["v"] == 2

    def test_force_reload_clears_project_config_cache(self, tmp_path):
        """force_reload_config must clear per-project caches (#1303)."""
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))

        state = DaemonState(config_path=config_path)

        from ai_guardian.config import loaders as config_loaders

        config_loaders._caches["proj-a"] = object()
        config_loaders._caches["proj-b"] = object()

        state.force_reload_config()

        assert len(config_loaders._caches) == 0

    def test_config_file_removed(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))

        state = DaemonState(config_path=config_path)
        assert state.get_config() is not None

        config_path.unlink()
        state.force_reload_config()
        assert state.get_config() is None

    def test_invalid_json_config(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text("valid json")
        config_path.write_text(json.dumps({"v": 1}))

        state = DaemonState(config_path=config_path)
        assert state.get_config()["v"] == 1

        # Write invalid JSON
        time.sleep(0.05)
        config_path.write_text("{invalid")
        state.get_config()  # Should log error but not crash
        # Config should still be old value since reload failed
        assert state._config["v"] == 1


class TestCompiledPatternCache:
    def test_cache_compiled_pattern(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        pattern = state.get_compiled_pattern(r"\d{3}-\d{4}")
        assert isinstance(pattern, re.Pattern)

        # Same pattern returns cached instance
        pattern2 = state.get_compiled_pattern(r"\d{3}-\d{4}")
        assert pattern is pattern2

    def test_invalid_regex_returns_none(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        result = state.get_compiled_pattern(r"[invalid")
        assert result is None


class TestActivityTracking:
    def test_record_activity_resets_idle(self, tmp_path):
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            idle_timeout=0.2,
        )
        time.sleep(0.1)
        state.record_activity()
        assert not state.is_idle_timeout_expired()

    def test_idle_timeout_expires(self, tmp_path):
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            idle_timeout=0.1,
        )
        time.sleep(0.15)
        assert state.is_idle_timeout_expired()

    def test_idle_timeout_disabled(self, tmp_path):
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            idle_timeout=0,
        )
        time.sleep(0.05)
        assert not state.is_idle_timeout_expired()


class TestPauseResume:
    def test_default_not_paused(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        assert not state.paused

    def test_pause_indefinite(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.pause()
        assert state.paused
        assert state.pause_remaining_seconds() == 0.0  # indefinite

    def test_pause_with_duration(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.pause(duration_minutes=5)
        assert state.paused
        remaining = state.pause_remaining_seconds()
        assert 290 < remaining <= 301  # ~5 minutes (float precision)

    def test_pause_auto_expires(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        # Pause for a very short duration
        state.pause(duration_minutes=0.002)  # ~0.12 seconds
        assert state.paused
        time.sleep(0.15)
        assert not state.paused  # auto-expired

    def test_resume(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.pause(duration_minutes=30)
        assert state.paused
        state.resume()
        assert not state.paused
        assert state.pause_remaining_seconds() == 0.0


class TestPerDirectoryPause:
    """Tests for per-directory pause/resume (#958)."""

    def test_default_no_dirs_paused(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        assert not state.is_dir_paused("/some/project")
        assert state.get_paused_dirs() == {}

    def test_pause_dir_indefinite(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.pause_dir("/project/a")
        assert state.is_dir_paused("/project/a")
        assert not state.is_dir_paused("/project/b")

    def test_pause_dir_with_duration(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.pause_dir("/project/a", duration_minutes=5)
        assert state.is_dir_paused("/project/a")
        dirs = state.get_paused_dirs()
        assert "/project/a" in dirs or os.path.realpath("/project/a") in dirs

    def test_pause_dir_auto_expires(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.pause_dir("/project/a", duration_minutes=0.002)  # ~0.12 seconds
        assert state.is_dir_paused("/project/a")
        time.sleep(0.15)
        assert not state.is_dir_paused("/project/a")

    def test_resume_dir(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.pause_dir("/project/a")
        assert state.is_dir_paused("/project/a")
        state.resume_dir("/project/a")
        assert not state.is_dir_paused("/project/a")

    def test_resume_dir_not_paused(self, tmp_path):
        """Resuming a directory that is not paused should be a no-op."""
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.resume_dir("/project/nonexistent")  # should not raise

    def test_multiple_dirs(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.pause_dir("/project/a")
        state.pause_dir("/project/b", duration_minutes=10)
        assert state.is_dir_paused("/project/a")
        assert state.is_dir_paused("/project/b")
        assert not state.is_dir_paused("/project/c")

        state.resume_dir("/project/a")
        assert not state.is_dir_paused("/project/a")
        assert state.is_dir_paused("/project/b")

    def test_global_pause_independent_of_dir_pause(self, tmp_path):
        """Global pause and per-dir pause are independent."""
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.pause_dir("/project/a")
        assert not state.paused  # global is not paused
        assert state.is_dir_paused("/project/a")

        state.pause()
        assert state.paused  # global is paused
        assert state.is_dir_paused("/project/a")  # dir still paused

        state.resume()
        assert not state.paused
        assert state.is_dir_paused("/project/a")  # dir still paused

    def test_get_paused_dirs_snapshot(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.pause_dir("/project/a")
        state.pause_dir("/project/b", duration_minutes=10)
        dirs = state.get_paused_dirs()
        a_key = os.path.realpath("/project/a")
        b_key = os.path.realpath("/project/b")
        assert a_key in dirs
        assert dirs[a_key] == 0.0  # indefinite
        assert b_key in dirs
        assert dirs[b_key] > 0  # has remaining seconds

    def test_get_paused_dirs_cleans_expired(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.pause_dir("/project/expire", duration_minutes=0.002)
        time.sleep(0.15)
        dirs = state.get_paused_dirs()
        assert os.path.realpath("/project/expire") not in dirs

    def test_is_dir_paused_with_none(self, tmp_path):
        """is_dir_paused should return False for None directory."""
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        assert not state.is_dir_paused(None)
        assert not state.is_dir_paused("")

    def test_stats_include_paused_dirs(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.pause_dir("/project/a")
        stats = state.get_stats()
        assert "paused_dirs" in stats
        assert len(stats["paused_dirs"]) == 1


class TestPausePersistence:
    """Tests for pause state persistence across restarts (#1319)."""

    def test_persist_global_pause_indefinite(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        state.pause()
        assert pause_file.exists()
        data = json.loads(pause_file.read_text())
        assert data["global"]["paused"] is True
        assert data["global"]["until"] == 0.0

    def test_persist_global_pause_with_duration(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        state.pause(duration_minutes=10)
        data = json.loads(pause_file.read_text())
        assert data["global"]["paused"] is True
        assert data["global"]["until"] > time.time()

    def test_persist_resume_clears_pause(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        state.pause()
        assert pause_file.exists()
        state.resume()
        data = json.loads(pause_file.read_text())
        assert data["global"]["paused"] is False

    def test_persist_dir_pause(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        state.pause_dir("/project/a")
        data = json.loads(pause_file.read_text())
        real_dir = os.path.realpath("/project/a")
        assert real_dir in data["dirs"]
        assert data["dirs"][real_dir]["until"] == 0.0

    def test_persist_dir_resume(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        state.pause_dir("/project/a")
        state.resume_dir("/project/a")
        data = json.loads(pause_file.read_text())
        real_dir = os.path.realpath("/project/a")
        assert real_dir not in data["dirs"]

    def test_load_restores_global_pause(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        data = {
            "global": {"paused": True, "until": 0.0},
            "dirs": {},
        }
        pause_file.write_text(json.dumps(data))
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        assert state.paused is True

    def test_load_restores_timed_pause(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        data = {
            "global": {"paused": True, "until": time.time() + 600},
            "dirs": {},
        }
        pause_file.write_text(json.dumps(data))
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        assert state.paused is True
        assert state.pause_remaining_seconds() > 500

    def test_load_skips_expired_pause(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        data = {
            "global": {"paused": True, "until": time.time() - 10},
            "dirs": {},
        }
        pause_file.write_text(json.dumps(data))
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        assert state.paused is False

    def test_load_restores_dir_pause(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        real_dir = os.path.realpath("/project/a")
        data = {
            "global": {"paused": False, "until": 0.0},
            "dirs": {real_dir: {"until": 0.0}},
        }
        pause_file.write_text(json.dumps(data))
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        assert state.is_dir_paused(real_dir) is True

    def test_load_skips_expired_dir_pause(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        real_dir = os.path.realpath("/project/a")
        data = {
            "global": {"paused": False, "until": 0.0},
            "dirs": {real_dir: {"until": time.time() - 10}},
        }
        pause_file.write_text(json.dumps(data))
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        assert state.is_dir_paused(real_dir) is False

    def test_load_missing_file_no_error(self, tmp_path):
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=tmp_path / "nonexistent.paused",
        )
        assert state.paused is False

    def test_load_corrupt_file_no_error(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        pause_file.write_text("not json{{{")
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        assert state.paused is False

    def test_is_paused_on_disk_global(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        data = {
            "global": {"paused": True, "until": 0.0},
            "dirs": {},
        }
        pause_file.write_text(json.dumps(data))
        assert DaemonState.is_paused_on_disk(pause_file=pause_file) is True

    def test_is_paused_on_disk_expired(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        data = {
            "global": {"paused": True, "until": time.time() - 10},
            "dirs": {},
        }
        pause_file.write_text(json.dumps(data))
        assert DaemonState.is_paused_on_disk(pause_file=pause_file) is False

    def test_is_paused_on_disk_dir(self, tmp_path):
        pause_file = tmp_path / "daemon.paused"
        real_dir = os.path.realpath("/project/a")
        data = {
            "global": {"paused": False, "until": 0.0},
            "dirs": {real_dir: {"until": 0.0}},
        }
        pause_file.write_text(json.dumps(data))
        assert (
            DaemonState.is_paused_on_disk(cwd=real_dir, pause_file=pause_file) is True
        )
        assert (
            DaemonState.is_paused_on_disk(cwd="/other/dir", pause_file=pause_file)
            is False
        )

    def test_is_paused_on_disk_no_file(self, tmp_path):
        assert (
            DaemonState.is_paused_on_disk(pause_file=tmp_path / "nonexistent") is False
        )

    def test_roundtrip_pause_restart(self, tmp_path):
        """Simulate daemon restart: pause, create new state, verify still paused."""
        pause_file = tmp_path / "daemon.paused"
        state1 = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        state1.pause()
        state1.pause_dir("/project/x")
        del state1

        state2 = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            pause_file=pause_file,
        )
        assert state2.paused is True
        assert state2.is_dir_paused(os.path.realpath("/project/x")) is True


class TestStats:
    def test_initial_stats(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        stats = state.get_stats()
        assert stats["request_count"] == 0
        assert stats["blocked_count"] == 0
        assert stats["warning_count"] == 0
        assert stats["log_only_count"] == 0
        assert stats["violation_count"] == 0
        assert stats["critical_count"] == 0
        assert stats["warning_severity_count"] == 0
        assert stats["last_block_type"] is None
        assert stats["last_block_seconds_ago"] is None
        assert stats["active_contexts"] == 0
        assert stats["paused"] is False
        assert "paused_dirs" in stats
        assert stats["paused_dirs"] == {}
        assert "active_project_dirs" in stats
        assert stats["active_project_dirs"] == []
        assert "uptime_seconds" in stats
        assert "started_at" in stats

    def test_stats_include_active_project_dirs(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.check_project_config("/home/user/project-a")
        state.check_project_config("/home/user/project-b")
        stats = state.get_stats()
        dirs = stats["active_project_dirs"]
        assert set(dirs) == {"/home/user/project-a", "/home/user/project-b"}

    def test_active_project_dirs_sorted_by_recency(self, tmp_path):
        """Most recently seen project dir appears first."""
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.check_project_config("/home/user/project-a")
        state.check_project_config("/home/user/project-b")
        state._project_dir_last_seen["/home/user/project-a"] = 300.0
        state._project_dir_last_seen["/home/user/project-b"] = 200.0
        stats = state.get_stats()
        assert stats["active_project_dirs"][0] == "/home/user/project-a"

    def test_most_recent_project_dir_in_stats(self, tmp_path):
        """Stats include most_recent_project_dir field."""
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        assert state.get_stats()["most_recent_project_dir"] is None
        state.check_project_config("/home/user/project-a")
        state.check_project_config("/home/user/project-b")
        state._project_dir_last_seen["/home/user/project-b"] = 200.0
        state._project_dir_last_seen["/home/user/project-a"] = 100.0
        assert state.get_stats()["most_recent_project_dir"] == "/home/user/project-b"
        state._project_dir_last_seen["/home/user/project-a"] = 300.0
        assert state.get_stats()["most_recent_project_dir"] == "/home/user/project-a"

    def test_stats_accumulate(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.record_activity()
        state.record_activity()
        state.record_blocked()
        state.record_warning()
        state.record_warning()
        state.record_log_only()

        stats = state.get_stats()
        assert stats["request_count"] == 2
        assert stats["blocked_count"] == 1
        assert stats["warning_count"] == 2
        assert stats["log_only_count"] == 1
        assert stats["violation_count"] == 4  # 1 + 2 + 1

    def test_severity_counts(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.record_blocked()
        state.record_blocked()
        state.record_warning()

        stats = state.get_stats()
        assert stats["critical_count"] == 2
        assert stats["warning_severity_count"] == 1

    def test_last_block_tracking(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.record_blocked(violation_type="secret_detected")

        stats = state.get_stats()
        assert stats["last_block_type"] == "secret_detected"
        assert stats["last_block_seconds_ago"] is not None
        assert stats["last_block_seconds_ago"] < 2.0

    def test_last_block_updated_on_new_block(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.record_blocked(violation_type="secret_detected")
        state.record_blocked(violation_type="prompt_injection")

        stats = state.get_stats()
        assert stats["last_block_type"] == "prompt_injection"

    def test_blocked_without_violation_type(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.record_blocked()

        stats = state.get_stats()
        assert stats["last_block_type"] is None
        assert stats["last_block_seconds_ago"] is not None
        assert stats["critical_count"] == 1


class TestConfigReloadTracking:
    def test_last_reload_set_on_init(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))
        state = DaemonState(config_path=config_path)
        stats = state.get_stats()
        assert stats["last_config_reload_at"] is not None
        assert stats["last_config_reload_seconds_ago"] is not None
        assert stats["last_config_reload_seconds_ago"] < 2.0

    def test_last_reload_none_without_config(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        stats = state.get_stats()
        assert stats["last_config_reload_at"] is None
        assert stats["last_config_reload_seconds_ago"] is None

    def test_last_reload_updates_on_change(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))
        state = DaemonState(config_path=config_path)
        first_reload = state.get_stats()["last_config_reload_at"]

        time.sleep(0.05)
        config_path.write_text(json.dumps({"v": 2}))
        state.get_config()

        second_reload = state.get_stats()["last_config_reload_at"]
        assert second_reload > first_reload

    def test_callback_fires_on_reload(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))
        fired = []
        state = DaemonState(config_path=config_path)
        state.add_state_observer(
            lambda t, d: fired.append(True) if t == "config_reloaded" else None
        )

        time.sleep(0.05)
        config_path.write_text(json.dumps({"v": 2}))
        state.get_config()

        assert fired == [True]

    def test_callback_fires_on_force_reload(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))
        fired = []
        state = DaemonState(config_path=config_path)
        state.add_state_observer(
            lambda t, d: fired.append(True) if t == "config_reloaded" else None
        )

        state.force_reload_config()
        assert fired == [True]

    def test_callback_not_fired_without_change(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))
        fired = []
        state = DaemonState(config_path=config_path)
        state.add_state_observer(
            lambda t, d: fired.append(True) if t == "config_reloaded" else None
        )

        state.get_config()  # no change, no callback
        assert fired == []

    def test_callback_error_does_not_propagate(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))
        state = DaemonState(config_path=config_path)
        state.add_state_observer(lambda t, d: 1 / 0)

        time.sleep(0.05)
        config_path.write_text(json.dumps({"v": 2}))
        state.get_config()  # should not raise


class TestProjectConfigTracking:
    def test_check_project_config_new_dir(self, tmp_path):
        """First time seeing a project dir — records mtime, no callback."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        config_dir = project_dir / ".ai-guardian"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(json.dumps({"v": 1}))

        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        fired = []
        state.add_state_observer(
            lambda t, d: fired.append(True) if t == "config_reloaded" else None
        )

        state.check_project_config(str(project_dir))

        assert fired == []
        stats = state.get_stats()
        assert stats["project_configs_tracked"] == 1

    def test_check_project_config_changed(self, tmp_path):
        """Mtime change triggers callback and updates reload timestamp."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        config_dir = project_dir / ".ai-guardian"
        config_dir.mkdir()
        config_path = config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))

        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        fired = []
        state.add_state_observer(
            lambda t, d: fired.append(True) if t == "config_reloaded" else None
        )

        state.check_project_config(str(project_dir))
        assert fired == []

        time.sleep(0.05)
        config_path.write_text(json.dumps({"v": 2}))

        state.check_project_config(str(project_dir))
        assert fired == [True]
        stats = state.get_stats()
        assert stats["last_project_config_reload_at"] is not None
        assert stats["last_project_config_reload_seconds_ago"] < 2.0

    def test_check_project_config_no_file(self, tmp_path):
        """Dir without config file — no crash, no tracking."""
        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()

        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.check_project_config(str(project_dir))

        stats = state.get_stats()
        assert stats["project_configs_tracked"] == 0

    def test_check_project_config_created_after_seen(self, tmp_path):
        """Config created after project was seen without one — triggers callback (#891)."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        fired = []
        state.add_state_observer(
            lambda t, d: fired.append(True) if t == "config_reloaded" else None
        )

        # First call: no config file
        state.check_project_config(str(project_dir))
        assert fired == []
        assert state.get_stats()["project_configs_tracked"] == 0

        # Create config file
        config_dir = project_dir / ".ai-guardian"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(json.dumps({"v": 1}))

        # Second call: config now exists — should detect and fire callback
        state.check_project_config(str(project_dir))
        assert fired == [True]
        stats = state.get_stats()
        assert stats["project_configs_tracked"] == 1
        assert stats["last_project_config_reload_at"] is not None

    def test_check_project_config_none_dir(self, tmp_path):
        """None dir — no crash."""
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.check_project_config(None)

        stats = state.get_stats()
        assert stats["project_configs_tracked"] == 0

    def test_stats_include_project_fields(self, tmp_path):
        """Stats include project config tracking fields."""
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        stats = state.get_stats()
        assert "last_project_config_reload_at" in stats
        assert "last_project_config_reload_seconds_ago" in stats
        assert "project_configs_tracked" in stats
        assert stats["last_project_config_reload_at"] is None
        assert stats["last_project_config_reload_seconds_ago"] is None
        assert stats["project_configs_tracked"] == 0

    def test_multiple_project_dirs_tracked(self, tmp_path):
        """Multiple project directories tracked independently."""
        state = DaemonState(config_path=tmp_path / "nonexistent.json")

        for i in range(3):
            project_dir = tmp_path / f"project{i}"
            project_dir.mkdir()
            config_dir = project_dir / ".ai-guardian"
            config_dir.mkdir()
            (config_dir / "ai-guardian.json").write_text(json.dumps({"project": i}))
            state.check_project_config(str(project_dir))

        stats = state.get_stats()
        assert stats["project_configs_tracked"] == 3

    def test_project_config_legacy_location(self, tmp_path):
        """Legacy ai-guardian.json at project root is detected."""
        project_dir = tmp_path / "legacy_project"
        project_dir.mkdir()
        (project_dir / "ai-guardian.json").write_text(json.dumps({"v": 1}))

        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.check_project_config(str(project_dir))

        assert state.get_stats()["project_configs_tracked"] == 1

    def test_callback_error_does_not_propagate(self, tmp_path):
        """Callback error in check_project_config is swallowed."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        config_dir = project_dir / ".ai-guardian"
        config_dir.mkdir()
        config_path = config_dir / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))

        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.add_state_observer(lambda t, d: 1 / 0)

        state.check_project_config(str(project_dir))
        time.sleep(0.05)
        config_path.write_text(json.dumps({"v": 2}))
        state.check_project_config(str(project_dir))  # should not raise


class TestThreadSafety:
    def test_concurrent_context_access(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        errors = []

        def writer(thread_id):
            try:
                for i in range(50):
                    state.store_pretooluse_context(
                        f"s{thread_id}", f"t{i}", {"data": f"thread{thread_id}"}
                    )
            except Exception as e:
                errors.append(e)

        def reader(thread_id):
            try:
                for i in range(50):
                    state.get_pretooluse_context(f"s{thread_id}", f"t{i}")
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=writer, args=(i,)))
            threads.append(threading.Thread(target=reader, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Thread safety errors: {errors}"


class TestSessionPersistence:
    def _make_state(self, tmp_path):
        sessions_file = tmp_path / "daemon_sessions.json"
        return DaemonState(
            config_path=tmp_path / "nonexistent.json",
            sessions_file=sessions_file,
        )

    def test_sessions_persisted_to_file(self, tmp_path):
        state = self._make_state(tmp_path)
        state.mark_security_injected("sess-1")
        state.flush_sessions()

        sessions_file = tmp_path / "daemon_sessions.json"
        assert sessions_file.exists()
        data = json.loads(sessions_file.read_text())
        assert data["version"] == 1
        assert "sess-1" in data["sessions"]
        assert data["sessions"]["sess-1"]["security_injected"] is True
        assert data["sessions"]["sess-1"]["security_reinject"] is False

    def test_sessions_restored_on_init(self, tmp_path):
        sessions_file = tmp_path / "daemon_sessions.json"
        sessions_file.write_text(
            json.dumps(
                {
                    "sessions": {
                        "sess-a": {
                            "security_injected": True,
                            "security_reinject": False,
                            "last_activity": time.time(),
                        }
                    },
                    "version": 1,
                }
            )
        )

        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            sessions_file=sessions_file,
        )
        assert not state.should_inject_security("sess-a")

    def test_sessions_pruned_on_load(self, tmp_path):
        sessions_file = tmp_path / "daemon_sessions.json"
        sessions_file.write_text(
            json.dumps(
                {
                    "sessions": {
                        "old-sess": {
                            "security_injected": True,
                            "security_reinject": False,
                            "last_activity": time.time() - 90000,  # >24h ago
                        },
                        "recent-sess": {
                            "security_injected": True,
                            "security_reinject": False,
                            "last_activity": time.time(),
                        },
                    },
                    "version": 1,
                }
            )
        )

        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            sessions_file=sessions_file,
        )
        assert state.should_inject_security("old-sess")  # pruned, so True
        assert not state.should_inject_security("recent-sess")  # loaded

    def test_sessions_pruned_on_persist(self, tmp_path):
        state = self._make_state(tmp_path)
        state.mark_security_injected("recent-sess")
        # Manually insert an old entry
        with state._lock:
            state._security_injected_sessions.add("old-sess")
            state._session_last_activity["old-sess"] = time.time() - 90000

        state._sessions_dirty = True
        state.flush_sessions()

        sessions_file = tmp_path / "daemon_sessions.json"
        data = json.loads(sessions_file.read_text())
        assert "recent-sess" in data["sessions"]
        assert "old-sess" not in data["sessions"]

    def test_persist_not_called_immediately(self, tmp_path):
        state = self._make_state(tmp_path)
        state.mark_security_injected("sess-1")
        sessions_file = tmp_path / "daemon_sessions.json"
        assert not sessions_file.exists()  # debounce hasn't fired yet

    def test_flush_forces_write(self, tmp_path):
        state = self._make_state(tmp_path)
        state.mark_security_injected("sess-1")
        state.flush_sessions()

        sessions_file = tmp_path / "daemon_sessions.json"
        assert sessions_file.exists()

    def test_reinject_flag_persisted(self, tmp_path):
        sessions_file = tmp_path / "daemon_sessions.json"
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            sessions_file=sessions_file,
        )
        state.mark_security_injected("sess-r")
        state.mark_security_reinject("sess-r")
        state.flush_sessions()

        state2 = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            sessions_file=sessions_file,
        )
        assert state2.should_inject_security("sess-r")  # reinject flag

    def test_corrupt_file_handled_gracefully(self, tmp_path):
        sessions_file = tmp_path / "daemon_sessions.json"
        sessions_file.write_text("{invalid json")

        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            sessions_file=sessions_file,
        )
        assert state.should_inject_security("any-session")

    def test_missing_file_handled(self, tmp_path):
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            sessions_file=tmp_path / "nonexistent_sessions.json",
        )
        assert state.should_inject_security("any-session")

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Unix file permissions not applicable on Windows",
    )
    def test_atomic_write_permissions(self, tmp_path):
        state = self._make_state(tmp_path)
        state.mark_security_injected("sess-perm")
        state.flush_sessions()

        sessions_file = tmp_path / "daemon_sessions.json"
        file_stat = os.stat(sessions_file)
        mode = file_stat.st_mode & 0o777
        assert mode == 0o600


class TestConfigError:
    """Verify config_error tracking in DaemonState (#742)."""

    def test_no_error_on_valid_config(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))
        state = DaemonState(config_path=config_path)
        assert state.get_config_error() is None
        assert state.get_stats()["config_error"] is None

    def test_error_set_on_invalid_json(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text("{invalid json")
        state = DaemonState(config_path=config_path)
        assert state.get_config_error() is not None
        assert (
            "invalid" in state.get_config_error().lower()
            or "expect" in state.get_config_error().lower()
        )
        assert state.get_stats()["config_error"] is not None

    def test_error_cleared_on_valid_reload(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text("{bad")
        state = DaemonState(config_path=config_path)
        assert state.get_config_error() is not None

        time.sleep(0.05)
        config_path.write_text(json.dumps({"v": 2}))
        state.get_config()
        assert state.get_config_error() is None

    def test_no_error_when_config_missing(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        assert state.get_config_error() is None


class TestMcpInstalled:
    def test_mcp_installed_in_stats(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        stats = state.get_stats()
        assert "mcp_installed" in stats
        assert isinstance(stats["mcp_installed"], bool)

    def test_mcp_installed_true_when_config_exists(self, tmp_path):
        config_file = tmp_path / ".claude.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "ai-guardian": {
                            "command": "ai-guardian",
                            "args": ["mcp-server"],
                        }
                    }
                }
            )
        )
        with mock.patch("pathlib.Path.expanduser", return_value=config_file):
            assert DaemonState._check_mcp_installed() is True

    def test_mcp_installed_false_when_no_configs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
        missing = tmp_path / "nonexistent.json"
        with mock.patch("pathlib.Path.expanduser", return_value=missing):
            assert DaemonState._check_mcp_installed() is False

    def test_mcp_installed_refreshed_on_config_reload(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"v": 1}))
        state = DaemonState(config_path=config_path)
        original = state._mcp_installed
        with mock.patch.object(
            DaemonState, "_check_mcp_installed", return_value=not original
        ):
            time.sleep(0.05)
            config_path.write_text(json.dumps({"v": 2}))
            state.force_reload_config()
            assert state._mcp_installed is not original


class TestVersionInStats:
    def test_get_stats_includes_version(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        stats = state.get_stats()
        assert "version" in stats
        assert isinstance(stats["version"], str)
        assert stats["version"] != ""


class TestAllowedFindings:
    """Tests for allowed transcript findings tracking (#1364)."""

    def test_add_and_get(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.add_allowed_finding("sess1", "fp_abc123")
        result = state.get_allowed_findings("sess1")
        assert "fp_abc123" in result

    def test_get_empty_session(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        result = state.get_allowed_findings("nonexistent")
        assert result == set()

    def test_get_none_session(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        result = state.get_allowed_findings(None)
        assert result == set()

    def test_add_none_session_noop(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.add_allowed_finding(None, "fp_abc")
        state.add_allowed_finding("sess1", None)
        assert state.get_allowed_findings("sess1") == set()

    def test_multiple_fingerprints(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.add_allowed_finding("sess1", "fp_a")
        state.add_allowed_finding("sess1", "fp_b")
        state.add_allowed_finding("sess1", "fp_c")
        result = state.get_allowed_findings("sess1")
        assert result == {"fp_a", "fp_b", "fp_c"}

    def test_sessions_isolated(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.add_allowed_finding("sess1", "fp_a")
        state.add_allowed_finding("sess2", "fp_b")
        assert state.get_allowed_findings("sess1") == {"fp_a"}
        assert state.get_allowed_findings("sess2") == {"fp_b"}

    def test_cleanup_clears_allowed(self, tmp_path):
        state = DaemonState(
            config_path=tmp_path / "nonexistent.json",
            sessions_file=tmp_path / "sessions.json",
        )
        state.add_allowed_finding("sess1", "fp_a")
        state.add_allowed_finding("sess1", "fp_b")
        assert len(state.get_allowed_findings("sess1")) == 2
        state.cleanup_session_state("sess1")
        assert state.get_allowed_findings("sess1") == set()

    def test_get_returns_copy(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.add_allowed_finding("sess1", "fp_a")
        result = state.get_allowed_findings("sess1")
        result.add("fp_external")
        assert "fp_external" not in state.get_allowed_findings("sess1")


class TestBootstrapSessionTracking:
    """Tests for DaemonState.is_new_session() used by bootstrap scanning."""

    def test_first_call_returns_true(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        assert state.is_new_session("session-abc", "/project") is True

    def test_second_call_returns_false(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        state.is_new_session("session-abc", "/project")
        assert state.is_new_session("session-abc", "/project") is False

    def test_different_sessions_independent(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        assert state.is_new_session("session-1", "/project") is True
        assert state.is_new_session("session-2", "/project") is True
        assert state.is_new_session("session-1", "/project") is False

    def test_empty_session_id_falls_back_to_cwd(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        assert state.is_new_session("", "/project/a") is True
        assert state.is_new_session("", "/project/a") is False
        assert state.is_new_session("", "/project/b") is True

    def test_none_session_id_falls_back_to_cwd(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        assert state.is_new_session(None, "/project/x") is True
        assert state.is_new_session(None, "/project/x") is False

    def test_separate_states_do_not_share(self, tmp_path):
        state_a = DaemonState(config_path=tmp_path / "nonexistent.json")
        state_b = DaemonState(config_path=tmp_path / "nonexistent.json")
        assert state_a.is_new_session("shared-id", "/project") is True
        assert state_b.is_new_session("shared-id", "/project") is True

    def test_concurrent_calls_thread_safe(self, tmp_path):
        import threading

        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        results = []
        barrier = threading.Barrier(10)

        def call_is_new():
            barrier.wait()
            results.append(state.is_new_session("session-concurrent", "/project"))

        threads = [threading.Thread(target=call_is_new) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1
        assert results.count(False) == 9


class TestStateObserver:
    """Tests for state change observer pattern (#650)."""

    def test_observer_fires_on_pause(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "c.json")
        events = []
        state.add_state_observer(lambda t, d: events.append((t, d)))
        state.pause(5)
        assert len(events) == 1
        assert events[0][0] == "paused"
        assert events[0][1]["minutes"] == 5

    def test_observer_fires_on_resume(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "c.json")
        events = []
        state.add_state_observer(lambda t, d: events.append((t, d)))
        state.pause()
        state.resume()
        assert events[-1][0] == "resumed"

    def test_observer_fires_on_pause_dir(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "c.json")
        project = tmp_path / "project_a"
        project.mkdir()
        events = []
        state.add_state_observer(lambda t, d: events.append((t, d)))
        state.pause_dir(str(project), 10)
        assert events[-1][0] == "dir_paused"
        assert os.path.realpath(str(project)) == events[-1][1]["dir"]

    def test_observer_fires_on_resume_dir(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "c.json")
        project = tmp_path / "project_a"
        project.mkdir()
        events = []
        state.add_state_observer(lambda t, d: events.append((t, d)))
        state.pause_dir(str(project))
        state.resume_dir(str(project))
        assert events[-1][0] == "dir_resumed"

    def test_observer_fires_on_config_reload(self, tmp_path):
        cfg = tmp_path / "ai-guardian.json"
        cfg.write_text("{}")
        state = DaemonState(config_path=cfg)
        events = []
        state.add_state_observer(lambda t, d: events.append((t, d)))
        state.force_reload_config()
        assert any(e[0] == "config_reloaded" for e in events)

    def test_remove_observer(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "c.json")
        events = []
        cb = lambda t, d: events.append((t, d))
        state.add_state_observer(cb)
        state.remove_state_observer(cb)
        state.pause()
        assert len(events) == 0

    def test_observer_error_does_not_crash(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "c.json")
        state.add_state_observer(lambda t, d: 1 / 0)
        state.pause(5)
        assert state.paused

    def test_multiple_observers(self, tmp_path):
        state = DaemonState(config_path=tmp_path / "c.json")
        a, b = [], []
        state.add_state_observer(lambda t, d: a.append(t))
        state.add_state_observer(lambda t, d: b.append(t))
        state.resume()
        assert "resumed" in a
        assert "resumed" in b
