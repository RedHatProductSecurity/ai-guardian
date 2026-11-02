"""Tests for opt-in, read-only remote violation mirroring."""

import copy
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.daemon.violation_mirroring import (
    MirrorIndex,
    _source_key,
    is_remote_mirroring_enabled,
    mirror_remote_violations,
)
from ai_guardian.violations.identity import stable_violation_id
from ai_guardian.violations.logger import ViolationLogger
from ai_guardian.violations.utils import is_mirrored_violation, safe_mirror_metadata
from ai_guardian.web.components.violation_mirror import mirror_source_link
from ai_guardian.web.pages.violations import (
    _sort_violation_sources,
    _violation_source_identity,
    _violation_timestamp_rank,
)


def _logger(path, *, max_entries=100):
    return ViolationLogger(
        log_path=path,
        config={
            "enabled": True,
            "max_entries": max_entries,
            "retention_days": 30,
            "log_types": [],
        },
    )


def _remote_record(**overrides):
    record = {
        "id": "viol_0123456789abcdef",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "violation_type": "secret_detected",
        "severity": "high",
        "file": "src/example.py",
        "line": 17,
        "blocked": {"value": "private-blocked-content"},
        "context": {"prompt": "private-context-content"},
        "suggestion": {"text": "private-suggestion-content"},
        "session_id": "private-session-content",
        "policy_decision": {
            "repository": "private-repository-content",
            "correlation_id": "private-correlation-content",
        },
    }
    record.update(overrides)
    return record


class _Client:
    def __init__(self, records=None, failures=()):
        self.records = records or []
        self.failures = set(failures)
        self.calls = []

    def get_violations(self, target, limit):
        self.calls.append((target.name, limit))
        if target.name in self.failures:
            raise RuntimeError("transport details must not be logged")
        return {"violations": self.records, "count": len(self.records)}


def _target(name="remote", runtime="manual", status="running"):
    return DaemonTarget(
        name=name,
        runtime=runtime,
        status=status,
        url=f"https://{name}.example",
    )


def test_mirroring_is_default_off_and_requires_explicit_true():
    assert is_remote_mirroring_enabled({}) is False
    assert (
        is_remote_mirroring_enabled({"violation_logging": {"enabled": True}}) is False
    )
    assert (
        is_remote_mirroring_enabled(
            {"violation_logging": {"mirror_remote_violations": True}}
        )
        is True
    )
    assert (
        is_remote_mirroring_enabled(
            {"violation_logging": {"mirror_remote_violations": 1}}
        )
        is False
    )


def test_generated_config_and_bundled_profiles_default_mirroring_off():
    from ai_guardian.setup import _get_default_config_template

    project_root = Path(__file__).resolve().parents[2]
    generated = _get_default_config_template(permissive=False)
    assert generated["violation_logging"]["mirror_remote_violations"] is False

    schema = json.loads(
        (
            project_root / "src/ai_guardian/schemas/ai-guardian-config.schema.json"
        ).read_text()
    )
    mirror_schema = schema["properties"]["violation_logging"]["properties"][
        "mirror_remote_violations"
    ]
    assert mirror_schema["type"] == "boolean"
    assert mirror_schema["default"] is False

    for profile in ("minimal", "standard", "strict", "moderator"):
        profile_config = json.loads(
            (
                project_root / f"src/ai_guardian/templates/profiles/{profile}.json"
            ).read_text()
        )
        assert profile_config["violation_logging"]["mirror_remote_violations"] is False


def test_mirror_imports_only_curated_fields_and_preserves_source_identity(tmp_path):
    source = _remote_record()
    source["resolved"] = True
    source["resolved_at"] = datetime.now(timezone.utc).isoformat()
    unchanged = copy.deepcopy(source)
    client = _Client([source])
    local_logger = _logger(tmp_path / "violations.jsonl")

    imported = mirror_remote_violations(
        client,
        [_target()],
        enabled=True,
        violation_logger=local_logger,
        mirror_index=MirrorIndex(tmp_path / "mirror.sqlite3"),
    )

    assert imported == 1
    assert source == unchanged  # source records are never modified
    mirror_files = list((tmp_path / "remote-violations").glob("*.jsonl"))
    assert len(mirror_files) == 1
    assert not (tmp_path / "violations.jsonl").exists()
    mirrored = local_logger.get_recent_violations(limit=10)[0]
    assert mirrored["timestamp"] == source["timestamp"]
    assert mirrored["violation_type"] == "secret_detected"
    assert mirrored["file"] == "src/example.py"
    assert mirrored["mirror"]["read_only"] is True
    assert mirrored["mirror"]["source_daemon"] == "remote"
    assert mirrored["mirror"]["source_violation_id"] == source["id"]
    assert mirrored["resolved"] is True
    assert mirrored["resolved_at"] == source["resolved_at"]
    assert re.fullmatch(r"viol_[0-9a-f]{32}", mirrored["id"])
    serialized = json.dumps(mirrored)
    assert "private-blocked-content" not in serialized
    assert "private-context-content" not in serialized
    assert "private-suggestion-content" not in serialized
    assert "private-session-content" not in serialized
    assert "private-repository-content" not in serialized
    assert "private-correlation-content" not in serialized


def test_each_remote_daemon_has_its_own_jsonl_file(tmp_path):
    logger = _logger(tmp_path / "violations.jsonl")
    imported = mirror_remote_violations(
        _Client([_remote_record()]),
        [
            DaemonTarget(
                name="worker",
                runtime="manual",
                status="running",
                url="https://worker-a.example",
            ),
            DaemonTarget(
                name="worker",
                runtime="manual",
                status="running",
                url="https://worker-b.example",
            ),
        ],
        enabled=True,
        violation_logger=logger,
        mirror_index=MirrorIndex(tmp_path / "mirror.sqlite3"),
    )

    mirror_files = sorted((tmp_path / "remote-violations").glob("*.jsonl"))
    assert imported == 2
    assert len(mirror_files) == 2
    assert all(re.fullmatch(r"[0-9a-f]{64}\.jsonl", path.name) for path in mirror_files)
    if os.name != "nt":
        assert all(path.stat().st_mode & 0o077 == 0 for path in mirror_files)
    entries = logger.get_recent_violations(limit=10)
    assert {entry["mirror"]["source_daemon"] for entry in entries} == {"worker"}
    assert len({entry["mirror"]["source_key"] for entry in entries}) == 2


def test_mirroring_deduplicates_across_polls_and_log_rotation(tmp_path):
    source = _remote_record()
    client = _Client([source])
    log_path = tmp_path / "violations.jsonl"
    local_logger = _logger(log_path, max_entries=1)
    index_path = tmp_path / "mirror.sqlite3"

    assert (
        mirror_remote_violations(
            client,
            [_target()],
            enabled=True,
            violation_logger=local_logger,
            mirror_index=MirrorIndex(index_path),
        )
        == 1
    )
    local_logger.log_violation(
        "middleware_paused",
        blocked={},
        context={},
        violation_id="viol_local000001",
    )

    # A fresh index object models a tray restart. Even after local rotation, the
    # opaque persistent event marker prevents the source row from being re-added.
    assert (
        mirror_remote_violations(
            client,
            [_target()],
            enabled=True,
            violation_logger=local_logger,
            mirror_index=MirrorIndex(index_path),
        )
        == 0
    )
    entries = local_logger.get_recent_violations(limit=10)
    assert len(entries) == 2
    assert (
        sum(entry.get("mirror", {}).get("read_only") is True for entry in entries) == 1
    )
    assert sum(entry["violation_type"] == "middleware_paused" for entry in entries) == 1
    local_log = json.loads(log_path.read_text().splitlines()[0])
    assert local_log.get("mirror") is None
    mirrored_log = next((tmp_path / "remote-violations").glob("*.jsonl"))
    assert (
        json.loads(mirrored_log.read_text().splitlines()[0])["mirror"]["read_only"]
        is True
    )


def test_clear_log_clears_each_daemon_file_without_reimporting_old_records(tmp_path):
    client = _Client([_remote_record()])
    logger = _logger(tmp_path / "violations.jsonl")
    index = MirrorIndex(tmp_path / "mirror.sqlite3")
    target = _target()

    assert (
        mirror_remote_violations(
            client,
            [target],
            enabled=True,
            violation_logger=logger,
            mirror_index=index,
        )
        == 1
    )
    assert list((tmp_path / "remote-violations").glob("*.jsonl"))

    assert logger.clear_log() is True
    assert list((tmp_path / "remote-violations").glob("*.jsonl")) == []
    assert (
        mirror_remote_violations(
            client,
            [target],
            enabled=True,
            violation_logger=logger,
            mirror_index=MirrorIndex(tmp_path / "mirror.sqlite3"),
        )
        == 0
    )
    assert logger.get_recent_violations(limit=10) == []


def test_expired_per_daemon_file_is_pruned_and_removed_from_history(tmp_path):
    logger = _logger(tmp_path / "violations.jsonl")
    logger.config["retention_days"] = 1
    assert (
        mirror_remote_violations(
            _Client([_remote_record()]),
            [_target()],
            enabled=True,
            violation_logger=logger,
            mirror_index=MirrorIndex(tmp_path / "mirror.sqlite3"),
        )
        == 1
    )
    mirror_file = next((tmp_path / "remote-violations").glob("*.jsonl"))
    entry = json.loads(mirror_file.read_text().splitlines()[0])
    entry["timestamp"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    mirror_file.write_text(json.dumps(entry) + "\n")

    assert logger.get_recent_violations(limit=10) == []
    assert not mirror_file.exists()


def test_max_entries_is_applied_independently_per_daemon_file(tmp_path):
    logger = _logger(tmp_path / "violations.jsonl", max_entries=1)
    first = _remote_record(id="viol_11111111")
    second = _remote_record(id="viol_22222222")
    second["timestamp"] = (
        datetime.now(timezone.utc) + timedelta(seconds=1)
    ).isoformat()
    imported = mirror_remote_violations(
        _Client([first, second]),
        [_target()],
        enabled=True,
        violation_logger=logger,
        mirror_index=MirrorIndex(tmp_path / "mirror.sqlite3"),
    )

    mirror_files = list((tmp_path / "remote-violations").glob("*.jsonl"))
    assert imported == 2
    assert len(mirror_files) == 1
    persisted = [json.loads(line) for line in mirror_files[0].read_text().splitlines()]
    assert len(persisted) == 1
    assert persisted[0]["mirror"]["source_violation_id"] == "viol_22222222"


def test_mirror_skips_existing_mirrors_and_local_targets(tmp_path):
    source = _remote_record()
    source["mirror"] = {"read_only": True}
    client = _Client([source])

    imported = mirror_remote_violations(
        client,
        [_target(), _target("local", runtime="local")],
        enabled=True,
        violation_logger=_logger(tmp_path / "violations.jsonl"),
        mirror_index=MirrorIndex(tmp_path / "mirror.sqlite3"),
    )

    assert imported == 0
    assert client.calls == [("remote", 10_000)]


def test_one_remote_failure_does_not_block_other_sources(tmp_path):
    client = _Client([_remote_record()], failures={"offline"})
    logger = _logger(tmp_path / "violations.jsonl")
    imported = mirror_remote_violations(
        client,
        [_target("offline"), _target("available")],
        enabled=True,
        violation_logger=logger,
        mirror_index=MirrorIndex(tmp_path / "mirror.sqlite3"),
    )

    assert imported == 1
    assert (
        logger.get_recent_violations(limit=10)[0]["mirror"]["source_daemon"]
        == "available"
    )


def test_mirroring_does_not_fetch_when_disabled(tmp_path):
    client = _Client([_remote_record()])
    imported = mirror_remote_violations(
        client,
        [_target()],
        enabled=False,
        violation_logger=_logger(tmp_path / "violations.jsonl"),
        mirror_index=MirrorIndex(tmp_path / "mirror.sqlite3"),
    )
    assert imported == 0
    assert client.calls == []


def test_legacy_violation_identity_is_stable_when_resolution_changes():
    record = {
        "timestamp": "2026-10-31T12:00:00Z",
        "violation_type": "tool_permission",
        "blocked": {"tool_name": "Bash"},
    }
    first_id = stable_violation_id(record)
    resolved = {**record, "resolved": True, "resolved_at": "2026-11-01T00:00:00Z"}
    assert stable_violation_id(resolved) == first_id
    assert re.fullmatch(r"viol_[0-9a-f]{32}", first_id)


def test_legacy_untrusted_id_is_not_exposed_as_a_public_violation_id():
    record = {
        "id": "private-id-sentinel",
        "timestamp": "2026-10-31T12:00:00Z",
        "violation_type": "tool_permission",
    }
    public_id = stable_violation_id(record)
    assert public_id != record["id"]
    assert re.fullmatch(r"viol_[0-9a-f]{32}", public_id)


def test_mirrored_metadata_is_curated_and_source_link_requires_reachable_target():
    source_target = DaemonTarget(
        name="remote / one",
        runtime="manual",
        status="running",
        url="https://remote.example",
    )
    mirror = {
        "read_only": True,
        "source_daemon": "remote / one",
        "source_runtime": "manual",
        "source_violation_id": "viol_0123456789abcdef",
        "source_key": _source_key(source_target),
        "source_event_key": "b" * 64,
        "private_extra": "never forwarded",
    }
    violation = {"mirror": mirror}
    assert is_mirrored_violation(violation)
    assert "private_extra" not in safe_mirror_metadata(mirror)

    class Service:
        def __init__(self, status):
            self.target = source_target
            self.target.status = status
            self.targets = [self.target]

        def get_target_by_name(self, name):
            return self.target if name == self.target.name else None

    link = mirror_source_link(violation, Service("running"))
    assert link == "/remote%20%2F%20one/violation-detail?id=viol_0123456789abcdef"
    assert mirror_source_link(violation, Service("stopped")) is None
    assert (
        mirror_source_link({"mirror": {"read_only": True}}, Service("running")) is None
    )


def test_source_link_is_omitted_when_source_name_is_ambiguous():
    class Service:
        targets = [
            DaemonTarget(
                name="worker",
                runtime="manual",
                status="running",
                url="https://worker-a.example",
            ),
            DaemonTarget(
                name="worker",
                runtime="manual",
                status="running",
                url="https://worker-b.example",
            ),
        ]

        def get_target_by_name(self, name):
            return self.targets[0]

    violation = {
        "mirror": {
            "read_only": True,
            "source_daemon": "worker",
            "source_violation_id": "viol_0123456789abcdef",
            "source_key": _source_key(Service.targets[0]),
        }
    }
    assert mirror_source_link(violation, Service()) is None


def test_source_filter_distinguishes_same_named_daemons_by_identity():
    first = {
        "mirror": {
            "read_only": True,
            "source_daemon": "worker",
            "source_runtime": "container",
            "source_key": "a" * 64,
        }
    }
    second = {
        "mirror": {
            "read_only": True,
            "source_daemon": "worker",
            "source_runtime": "container",
            "source_key": "b" * 64,
        }
    }

    first_key, first_label = _violation_source_identity(first, "receiver")
    second_key, second_label = _violation_source_identity(second, "receiver")

    assert first_key != second_key
    assert first_label != second_label
    assert _violation_source_identity({}, "receiver", local_daemon=True) == (
        "daemon:receiver",
        "Local — receiver",
    )


def test_source_dropdown_orders_local_first_then_latest_violation():
    counts = {"remote:older": 1, "daemon:receiver": 1, "remote:newer": 1}
    labels = {
        "remote:older": "older",
        "daemon:receiver": "Local — receiver",
        "remote:newer": "newer",
    }
    latest = {
        "remote:older": _violation_timestamp_rank(
            {"timestamp": "2026-10-30T10:00:00Z"}
        ),
        "daemon:receiver": _violation_timestamp_rank(
            {"timestamp": "2026-10-29T10:00:00Z"}
        ),
        "remote:newer": _violation_timestamp_rank(
            {"timestamp": "2026-11-01T10:00:00+00:00"}
        ),
    }

    assert _sort_violation_sources(
        counts, labels, latest, local_key="daemon:receiver"
    ) == ["daemon:receiver", "remote:newer", "remote:older"]
