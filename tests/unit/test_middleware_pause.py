"""Tests for shared daemon/standalone middleware pause state."""

from __future__ import annotations

import json

from ai_guardian.middleware.pause import (
    MiddlewarePauseStore,
    effective_pause_status,
)


def test_standalone_pause_is_idempotent_and_expires(monkeypatch, tmp_path):
    pause_file = tmp_path / "middleware.paused"
    store = MiddlewarePauseStore(pause_file)
    now = 1_000.0
    monkeypatch.setattr("ai_guardian.middleware.pause.time.time", lambda: now)

    first = store.pause(5)
    second = store.pause(5)

    assert first.paused
    assert second.paused
    assert second.source == "middleware"
    assert second.scope == "global"
    assert second.remaining_seconds == 300

    monkeypatch.setattr("ai_guardian.middleware.pause.time.time", lambda: now + 301)
    assert not store.status().paused
    assert not effective_pause_status(middleware_pause_file=pause_file).paused


def test_project_pause_does_not_pause_other_projects(tmp_path):
    pause_file = tmp_path / "middleware.paused"
    store = MiddlewarePauseStore(pause_file)
    project_a = str(tmp_path / "project-a")
    project_b = str(tmp_path / "project-b")

    store.pause(project_dir=project_a)

    assert store.status(project_a).paused
    assert not store.status(project_b).paused
    assert not store.status().paused

    store.resume(project_dir=project_a)
    store.resume(project_dir=project_a)
    assert not pause_file.exists()


def test_daemon_pause_has_precedence_over_standalone_pause(tmp_path):
    daemon_file = tmp_path / "daemon.paused"
    middleware_file = tmp_path / "middleware.paused"
    daemon_file.write_text(
        json.dumps({"global": {"paused": True, "until": 0.0}}),
        encoding="utf-8",
    )
    MiddlewarePauseStore(middleware_file).pause()

    status = effective_pause_status(
        daemon_pause_file=daemon_file,
        middleware_pause_file=middleware_file,
    )

    assert status.paused
    assert status.source == "daemon"
    assert status.reason == "operator" or status.reason is None
