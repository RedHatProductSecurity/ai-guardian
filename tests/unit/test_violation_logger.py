"""Focused tests for violation JSONL append, retention, and recent reads."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from ai_guardian.violations import logger as violation_logger_module
from ai_guardian.violations.logger import ViolationLogger


@pytest.fixture(autouse=True)
def _disable_counter_writes(monkeypatch):
    """Keep these storage tests isolated from the separate lifetime counter."""
    monkeypatch.setattr(
        "ai_guardian.violations.counter.ViolationCounter.increment",
        lambda *_args, **_kwargs: None,
    )


def _logger(path, *, max_entries=1000, retention_days=30):
    return ViolationLogger(
        log_path=path,
        config={
            "enabled": True,
            "log_types": [],
            "max_entries": max_entries,
            "retention_days": retention_days,
        },
    )


def _append(logger, violation_id):
    logger.log_violation(
        "tool_permission",
        blocked={"tool_name": "Bash"},
        context={},
        violation_id=violation_id,
    )


def test_routine_appends_do_not_run_full_rotation(tmp_path, monkeypatch):
    log_path = tmp_path / "violations.jsonl"

    def unexpected_rotation(*_args, **_kwargs):
        pytest.fail("routine appends must not rotate the complete history")

    monkeypatch.setattr(ViolationLogger, "_rotate_log_if_needed", unexpected_rotation)

    for index in range(20):
        # The hook path creates logger instances repeatedly in a long-running
        # daemon, so maintenance state must not live on an individual instance.
        _append(_logger(log_path), f"violation-{index}")

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 20


def test_entry_limit_cleanup_runs_on_a_bounded_append_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(violation_logger_module, "_ROTATION_BATCH_SIZE", 3)
    logger = _logger(tmp_path / "violations.jsonl", max_entries=2)
    original_rotate = logger._rotate_log_if_needed
    rotations = []

    def count_rotations(*args, **kwargs):
        rotations.append(args)
        return original_rotate(*args, **kwargs)

    monkeypatch.setattr(logger, "_rotate_log_if_needed", count_rotations)

    for index in range(6):
        _append(logger, f"violation-{index}")

    entries = [
        json.loads(line)
        for line in (tmp_path / "violations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rotations) == 2
    assert [entry["id"] for entry in entries] == ["violation-4", "violation-5"]


def test_first_append_applies_retention_to_an_existing_history(tmp_path):
    log_path = tmp_path / "violations.jsonl"
    expired = {
        "id": "expired",
        "timestamp": (datetime.now(timezone.utc) - timedelta(days=3))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    log_path.write_text(json.dumps(expired) + "\n", encoding="utf-8")
    logger = _logger(log_path, retention_days=1)

    _append(logger, "current")

    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [entry["id"] for entry in entries] == ["current"]


def test_retention_cleanup_runs_after_a_bounded_time_interval(tmp_path, monkeypatch):
    log_path = tmp_path / "violations.jsonl"
    logger = _logger(log_path, retention_days=1)
    clock = [10.0]
    monkeypatch.setattr(violation_logger_module.time, "monotonic", lambda: clock[0])
    _append(logger, "current-1")

    expired = {
        "id": "expired",
        "timestamp": (datetime.now(timezone.utc) - timedelta(days=3))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(expired) + "\n")

    rotations = []
    original_rotate = logger._rotate_log_if_needed

    def count_rotations(*args, **kwargs):
        rotations.append(args)
        return original_rotate(*args, **kwargs)

    monkeypatch.setattr(logger, "_rotate_log_if_needed", count_rotations)
    clock[0] += 1
    _append(logger, "current-2")
    assert rotations == []

    clock[0] += violation_logger_module._ROTATION_INTERVAL_SECONDS
    _append(logger, "current-3")

    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(rotations) == 1
    assert [entry["id"] for entry in entries] == [
        "current-1",
        "current-2",
        "current-3",
    ]


def test_recent_local_read_tails_file_and_preserves_filters_and_order(
    tmp_path, monkeypatch
):
    log_path = tmp_path / "violations.jsonl"
    first_timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record_count = 500
    with log_path.open("w", encoding="utf-8") as stream:
        for index in range(record_count):
            entry = {
                "id": f"violation-{index}",
                "timestamp": (first_timestamp + timedelta(seconds=index))
                .isoformat()
                .replace("+00:00", "Z"),
                "violation_type": "target" if index % 10 == 0 else "other",
                "context": {
                    "session_id": (
                        "target-session" if index % 10 == 0 else "other-session"
                    )
                },
                "blocked": {"description": "x" * 256},
            }
            stream.write(json.dumps(entry) + "\n")
        stream.write("not valid json\n[]\n")

    logger = _logger(log_path)
    original_loads = violation_logger_module.json.loads
    parsed_lines = 0

    def count_json_loads(value, *args, **kwargs):
        nonlocal parsed_lines
        parsed_lines += 1
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(violation_logger_module.json, "loads", count_json_loads)

    entries = logger.get_recent_violations(
        limit=3, violation_type="target", session_id="target-session"
    )

    assert [entry["id"] for entry in entries] == [
        "violation-490",
        "violation-480",
        "violation-470",
    ]
    assert parsed_lines < record_count


def test_recent_read_falls_back_to_timestamp_order_for_legacy_data(tmp_path):
    log_path = tmp_path / "violations.jsonl"
    timestamps = [
        "2026-01-01T00:00:10Z",
        "2026-01-01T00:00:01Z",
        "2026-01-01T00:00:05Z",
    ]
    log_path.write_text(
        "".join(
            json.dumps({"id": f"item-{index}", "timestamp": timestamp}) + "\n"
            for index, timestamp in enumerate(timestamps)
        ),
        encoding="utf-8",
    )

    entries = _logger(log_path).get_recent_violations(limit=2)

    assert [entry["id"] for entry in entries] == ["item-0", "item-2"]


def test_resolution_rewrites_skip_corrupt_and_non_object_lines(tmp_path):
    log_path = tmp_path / "violations.jsonl"
    first = {"id": "first", "timestamp": "2026-01-01T00:00:00Z"}
    second = {"id": "second", "timestamp": "2026-01-01T00:00:01Z"}
    log_path.write_text(
        "\n".join((json.dumps(first), "not valid json", "[]", json.dumps(second), "")),
        encoding="utf-8",
    )
    logger = _logger(log_path)

    assert logger.mark_resolved(first["timestamp"], action="approved", note="reviewed")
    resolved_entries = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(resolved_entries) == 2
    assert resolved_entries[0]["resolved"] is True
    assert resolved_entries[0]["resolved_action"] == "approved"
    assert resolved_entries[0]["resolved_note"] == "reviewed"
    assert resolved_entries[1] == second

    assert logger.mark_unresolved(first["timestamp"])
    unresolved_entries = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert unresolved_entries[0]["resolved"] is False
    assert "resolved_at" not in unresolved_entries[0]
    assert "resolved_action" not in unresolved_entries[0]
    assert "resolved_note" not in unresolved_entries[0]
    assert unresolved_entries[1] == second


@pytest.mark.parametrize(
    "violation_type",
    ["secret_detected", "image_secret_detected", "pii_detected"],
)
def test_sensitive_violation_storage_omits_values_and_partial_hints(
    tmp_path, violation_type
):
    log_path = tmp_path / "violations.jsonl"
    logger = _logger(log_path)
    sensitive_value = "synthetic-confidential-probe-value"
    partial_hint = "synthetic.*value"
    blocked = {
        "file_path": "/repo/config.txt",
        "line_number": 17,
        "rule_id": "synthetic-rule",
        "matched_text": sensitive_value,
        "pattern_hint": partial_hint,
        "findings": [
            {
                "line_number": 17,
                "matched_text": sensitive_value,
                "pattern_hint": partial_hint,
            }
        ],
    }

    logger.log_violation(
        violation_type,
        blocked=blocked,
        context={"tool_use_id": "safe-tool-id"},
    )

    serialized = log_path.read_text(encoding="utf-8")
    stored = json.loads(serialized)
    assert sensitive_value not in serialized
    assert partial_hint not in serialized
    assert stored["blocked"]["file_path"] == "/repo/config.txt"
    assert stored["blocked"]["line_number"] == 17
    assert stored["blocked"]["rule_id"] == "synthetic-rule"
    assert "matched_text" not in stored["blocked"]
    assert "pattern_hint" not in stored["blocked"]
    assert "matched_text" not in stored["blocked"]["findings"][0]
    assert "pattern_hint" not in stored["blocked"]["findings"][0]
    # Sanitizing persisted data must not alter the caller's in-memory record.
    assert blocked["matched_text"] == sensitive_value
    assert blocked["pattern_hint"] == partial_hint


def test_non_sensitive_violation_storage_keeps_matched_text(tmp_path):
    log_path = tmp_path / "violations.jsonl"
    logger = _logger(log_path)

    logger.log_violation(
        "prompt_injection",
        blocked={"matched_text": "ignore previous instructions"},
        context={},
    )

    stored = json.loads(log_path.read_text(encoding="utf-8"))
    assert stored["blocked"]["matched_text"] == "ignore previous instructions"
