"""Focused tests for violation JSONL append, retention, and recent reads."""

import json
import logging
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


def test_unconfigured_type_diagnostic_does_not_echo_caller_value(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger=violation_logger_module.logger.name)
    logger = ViolationLogger(
        log_path=tmp_path / "violations.jsonl",
        config={"enabled": True, "log_types": ["tool_permission"]},
    )

    logger.log_violation("synthetic_unconfigured_category", blocked={}, context={})

    assert "not configured to be logged" in caplog.text
    assert "synthetic_unconfigured_category" not in caplog.text


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
        "command": sensitive_value,
        "source_command": sensitive_value,
        "rule_id": "synthetic-rule",
        "description": sensitive_value,
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

    context = {"tool_use_id": "safe-tool-id", "raw_input": sensitive_value}
    suggestion = {"warning": sensitive_value}
    allowlist_context = {
        "rule_id": "synthetic-rule",
        "original_file_path": "/repo/config.txt",
        "line_content_hash": "a" * 64,
        "surrounding_context": sensitive_value,
        "git_ref": "synthetic-ref",
        "project_path": "/repo",
    }
    logger.log_violation(
        violation_type,
        blocked=blocked,
        context=context,
        suggestion=suggestion,
        allowlist_context=allowlist_context,
        origin_command=sensitive_value,
    )

    serialized = log_path.read_text(encoding="utf-8")
    stored = json.loads(serialized)
    assert sensitive_value not in serialized
    assert partial_hint not in serialized
    assert stored["id"] is None
    assert stored["timestamp"]
    assert stored["violation_type"] == "sensitive_finding"
    assert stored["severity"] == "warning"
    assert set(stored) == {
        "id",
        "timestamp",
        "violation_type",
        "severity",
        "resolved",
        "resolved_at",
        "resolved_action",
    }
    assert logger.get_recent_violations(violation_type="sensitive_finding")
    for filtered in (
        logger.get_recent_violations(),
        logger.get_recent_violations(violation_type="sensitive_finding"),
        logger.get_recent_violations(violation_type=violation_type),
    ):
        assert len(filtered) == 1
        assert filtered[0]["violation_type"] == "sensitive_finding"
    # Sanitizing persisted data must not alter the caller's in-memory record.
    assert blocked["matched_text"] == sensitive_value
    assert blocked["pattern_hint"] == partial_hint
    assert blocked["findings"][0]["matched_text"] == sensitive_value
    assert context["raw_input"] == sensitive_value
    assert suggestion["warning"] == sensitive_value
    assert allowlist_context["surrounding_context"] == sensitive_value


@pytest.mark.parametrize(
    "legacy_type",
    ["secret_detected", "image_secret_detected", "pii_detected"],
)
def test_sensitive_finding_filters_include_legacy_history(tmp_path, legacy_type):
    log_path = tmp_path / "violations.jsonl"
    legacy_types = ["secret_detected", "image_secret_detected", "pii_detected"]
    entries = [
        {"timestamp": "2026-01-01T00:00:00Z", "violation_type": "sensitive_finding"},
        *[
            {"timestamp": f"2026-01-01T00:00:0{index + 1}Z", "violation_type": vtype}
            for index, vtype in enumerate(legacy_types)
        ],
        {"timestamp": "2026-01-01T00:00:04Z", "violation_type": "tool_permission"},
    ]
    log_path.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )
    logger = _logger(log_path)

    legacy_filtered = logger.get_recent_violations(limit=10, violation_type=legacy_type)
    consolidated_filtered = logger.get_recent_violations(
        limit=10, violation_type="sensitive_finding"
    )

    assert {entry["violation_type"] for entry in legacy_filtered} == {
        "sensitive_finding",
        legacy_type,
    }
    assert {entry["violation_type"] for entry in consolidated_filtered} == {
        "sensitive_finding",
        *legacy_types,
    }


@pytest.mark.parametrize(
    ("input_severity", "expected_severity"),
    [
        ("critical", "critical"),
        ("info", "info"),
        ("scanner supplied label", "warning"),
    ],
)
def test_sensitive_finding_severity_is_limited_to_known_labels(
    tmp_path, input_severity, expected_severity
):
    log_path = tmp_path / "violations.jsonl"
    logger = _logger(log_path)

    logger.log_sensitive_finding(
        violation_type="secret_detected",
        severity=input_severity,
    )

    stored = json.loads(log_path.read_text(encoding="utf-8"))
    assert stored["severity"] == expected_severity


def test_non_sensitive_violation_storage_keeps_matched_text(tmp_path):
    log_path = tmp_path / "violations.jsonl"
    logger = _logger(log_path)

    logger.log_violation(
        "prompt_injection",
        blocked={"matched_text": "ignore previous instructions"},
        context={},
        severity="high",
    )

    stored = json.loads(log_path.read_text(encoding="utf-8"))
    assert stored["violation_type"] == "prompt_injection"
    assert stored["severity"] == "high"
    assert stored["blocked"]["matched_text"] == "ignore previous instructions"
    assert stored["policy_decision"]["violation_type"] == "prompt_injection"


def test_non_sensitive_violation_normalizes_unknown_severity(tmp_path):
    log_path = tmp_path / "violations.jsonl"
    logger = _logger(log_path)

    logger.log_violation(
        "prompt_injection",
        blocked={},
        context={},
        severity="scanner supplied label",
    )

    stored = json.loads(log_path.read_text(encoding="utf-8"))
    assert stored["severity"] == "warning"
    assert stored["policy_decision"]["severity"] == "warning"


@pytest.mark.parametrize(
    "violation_type", ["middleware_paused", "scan_finding", "canary_detection"]
)
def test_known_non_enum_violation_labels_are_preserved(tmp_path, violation_type):
    log_path = tmp_path / "violations.jsonl"
    logger = _logger(log_path)

    logger.log_violation(violation_type, blocked={}, context={})

    stored = json.loads(log_path.read_text(encoding="utf-8"))
    assert stored["violation_type"] == violation_type
    assert stored["policy_decision"]["violation_type"] == violation_type


@pytest.fixture
def _safe_origin_command_scanners(monkeypatch):
    from types import SimpleNamespace

    from ai_guardian.violations import command_context
    from ai_guardian.violations.command_context import _ORIGIN_COMMAND_PII_TYPES

    monkeypatch.setattr(
        "ai_guardian.scanners.secret_scanning.check_secrets",
        lambda *_args, **_kwargs: (False, None),
    )
    monkeypatch.setattr(
        command_context,
        "_origin_command_redactor",
        lambda: SimpleNamespace(
            compiled_pii_types=set(_ORIGIN_COMMAND_PII_TYPES),
            redact=lambda command: {
                "redacted_text": command,
                "redactions": [],
            },
        ),
    )


def test_locationless_violation_persists_bounded_sanitized_origin_command(
    tmp_path, _safe_origin_command_scanners
):
    logger = _logger(tmp_path / "violations.jsonl")
    command = "printf safe-command"

    logger.log_violation(
        "exfil_detection",
        blocked={"file_path": "", "line_number": 7, "start_column": 2},
        context={},
        origin_command=command,
    )

    stored = logger.get_recent_violations()[0]
    assert stored["blocked"]["source_command"] == command
    assert stored["blocked"]["line_number"] == 7
    assert stored["blocked"]["start_column"] == 2
    assert "command" not in stored["blocked"]


def test_usable_file_path_takes_precedence_over_origin_command(
    tmp_path, _safe_origin_command_scanners
):
    logger = _logger(tmp_path / "violations.jsonl")

    logger.log_violation(
        "exfil_detection",
        blocked={
            "file_path": "/repo/source.py",
            "line_number": 7,
            "command": "printf safe-command",
        },
        context={},
        origin_command="printf safe-command",
    )

    blocked = logger.get_recent_violations()[0]["blocked"]
    assert blocked["file_path"] == "/repo/source.py"
    assert blocked["line_number"] == 7
    assert "source_command" not in blocked
    assert "command" not in blocked


def test_context_file_path_takes_precedence_over_tool_result_pseudo_path(
    tmp_path, _safe_origin_command_scanners
):
    logger = _logger(tmp_path / "violations.jsonl")

    logger.log_violation(
        "exfil_detection",
        blocked={"file_path": "tool_result:grep", "line_number": 7},
        context={"file_path": "/repo/source.py"},
        origin_command="printf safe-command",
    )

    entry = logger.get_recent_violations()[0]
    assert entry["context"]["file_path"] == "/repo/source.py"
    assert "source_command" not in entry["blocked"]


def test_unverifiable_command_is_omitted_and_raw_command_is_removed(
    tmp_path, monkeypatch
):
    secret = "synthetic-sensitive-command-value"
    monkeypatch.setattr(
        "ai_guardian.scanners.secret_scanning.check_secrets",
        lambda *_args, **_kwargs: (True, "finding"),
    )
    logger = _logger(tmp_path / "violations.jsonl")

    logger.log_violation(
        "exfil_detection",
        blocked={"command": secret, "file_path": None},
        context={},
        origin_command=secret,
    )

    serialized = logger.log_path.read_text(encoding="utf-8")
    assert secret not in serialized
    blocked = json.loads(serialized)["blocked"]
    assert "command" not in blocked
    assert "source_command" not in blocked


def test_command_is_omitted_when_secret_scanner_reports_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ai_guardian.scanners.secret_scanning.check_secrets",
        lambda *_args, **_kwargs: (False, "scanner unavailable"),
    )
    logger = _logger(tmp_path / "violations.jsonl")

    logger.log_violation(
        "tool_permission",
        blocked={"tool_name": "Bash", "tool_value": "printf safe-command"},
        context={},
    )

    blocked = logger.get_recent_violations()[0]["blocked"]
    assert "tool_value" not in blocked
    assert "source_command" not in blocked


def test_command_fields_are_never_serialized_from_context(tmp_path):
    secret = "synthetic-context-command-value"
    logger = _logger(tmp_path / "violations.jsonl")

    logger.log_violation(
        "tool_permission",
        blocked={"tool_name": "Read"},
        context={
            "command": secret,
            "source_command": secret,
            "origin_command": secret,
        },
    )

    serialized = logger.log_path.read_text(encoding="utf-8")
    assert secret not in serialized
    assert json.loads(serialized)["context"] == {}


def test_private_command_credential_violation_never_persists_command_fields(
    tmp_path, _safe_origin_command_scanners
):
    logger = _logger(tmp_path / "violations.jsonl")
    command = "curl --user username:synthetic-sensitive-value https://example.test"

    logger.log_violation(
        "command_credential_detected",
        blocked={
            "command": command,
            "source_command": command,
            "origin_command": command,
            "tool_value": command,
            "finding_classes": ["inline_literal"],
        },
        context={},
        origin_command=command,
    )

    serialized = logger.log_path.read_text(encoding="utf-8")
    assert command not in serialized
    blocked = json.loads(serialized)["blocked"]
    assert "command" not in blocked
    assert "source_command" not in blocked
    assert "origin_command" not in blocked
    assert "tool_value" not in blocked


def test_legacy_record_without_optional_command_remains_readable(tmp_path):
    log_path = tmp_path / "violations.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "id": "legacy",
                "timestamp": "2026-01-01T00:00:00Z",
                "violation_type": "tool_permission",
                "blocked": {"tool_name": "Bash"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    entry = _logger(log_path).get_recent_violations()[0]
    assert entry["id"] == "legacy"
    assert entry["blocked"] == {"tool_name": "Bash"}
