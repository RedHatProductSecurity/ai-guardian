"""Tests for compliance audit logging (#266)."""

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import ai_guardian
from ai_guardian.constants import HookEvent
from ai_guardian.config import loaders
from ai_guardian.hook_adapters.base import NormalizedHookInput
from ai_guardian.violations.audit import AuditLogger


def _config(**overrides):
    config = {
        "enabled": True,
        "log_all_tool_calls": True,
        "compliance_mode": {"soc2": True, "gdpr": True, "hipaa": False},
        "retention_days": 90,
        "sensitive_data_masking": True,
    }
    config.update(overrides)
    return config


def test_allowed_decision_is_sanitized_and_uses_policy_schema(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    audit = AuditLogger(log_path=log_path, config=_config())

    entry = audit.log_decision(
        HookEvent.PRE_TOOL_USE,
        "allowed",
        {
            "user_id": "person@example.invalid",
            "session_id": "session-1",
            "agent": "claude_code",
            "repository": "/repo",
        },
        tool_name="Bash",
        tool_parameters={
            "api_key": "test-value-not-real",
            "command": "printf '123-45-6789'",
        },
    )

    assert entry is not None
    assert entry["decision"] == "allow"
    assert entry["hook_type"] == "PreToolUse"
    assert entry["session_id"] == "session-1"
    assert entry["compliance_flags"] == {
        "soc2_logged": True,
        "gdpr_processing_activity": True,
        "hipaa_access_log": False,
    }
    serialized = log_path.read_text(encoding="utf-8")
    assert "test-value-not-real" not in serialized
    assert "123-45-6789" not in serialized
    assert entry["policy_decision"]["decision"] == "allow"
    assert entry["policy_decision"]["source"] == "hook"


def test_non_allow_decisions_are_logged_when_tool_call_logging_is_disabled(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    audit = AuditLogger(
        log_path=log_path,
        config=_config(log_all_tool_calls=False),
    )

    assert audit.log_decision("PreToolUse", "allow", {}) is None
    blocked = audit.log_decision(
        "PreToolUse",
        "blocked",
        {"session_id": "session-2"},
        violation_type="tool_permission",
    )

    assert blocked is not None
    assert blocked["decision"] == "block"
    assert len(audit.get_recent_entries()) == 1


def test_disabled_audit_logger_does_not_create_log(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    audit = AuditLogger(log_path=log_path, config={"enabled": False})

    assert audit.log_decision("PreToolUse", "allow", {}) is None
    assert not log_path.exists()


def test_hook_decision_uses_normalized_fields_and_does_not_copy_output(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    adapter = SimpleNamespace(agent_type="opencode", name="OpenCode")
    normalized = NormalizedHookInput(
        event=HookEvent.POST_TOOL_USE,
        tool_name="Bash",
        tool_input={"command": "printf safe"},
        session_id="session-3",
        tool_use_id="tool-3",
        working_dir="/repo",
    )
    audit = AuditLogger(log_path=log_path, config=_config())

    entry = audit.log_hook_decision(
        {"run_id": "run-3", "tool_output": "must-not-be-recorded"},
        {"_blocked": True, "_violation_type": "secret_detected", "output": "raw"},
        adapter=adapter,
        normalized=normalized,
    )

    assert entry is not None
    assert entry["decision"] == "block"
    assert entry["tool_name"] == "Bash"
    serialized = log_path.read_text(encoding="utf-8")
    assert "must-not-be-recorded" not in serialized
    assert '"output"' not in serialized


def test_retention_and_max_entries_are_enforced(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    old_timestamp = (
        (datetime.now(timezone.utc) - timedelta(days=10))
        .isoformat()
        .replace("+00:00", "Z")
    )
    log_path.write_text(
        json.dumps({"timestamp": old_timestamp, "decision": "allow"}) + "\n",
        encoding="utf-8",
    )
    audit = AuditLogger(
        log_path=log_path,
        config=_config(retention_days=1, max_entries=2),
    )

    for _ in range(3):
        audit.log_decision("PreToolUse", "allow", {})

    entries = audit.get_recent_entries(limit=0)
    assert len(entries) == 2
    assert all(entry["decision"] == "allow" for entry in entries)


def test_json_and_csv_exports(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    audit = AuditLogger(log_path=log_path, config=_config())
    audit.log_decision("PreToolUse", "allow", {"session_id": "session-4"})

    json_path = tmp_path / "export.json"
    csv_path = tmp_path / "export.csv"
    assert audit.export(json_path, export_format="json") is True
    assert audit.export(csv_path, export_format="csv") is True

    exported = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(exported) == 1
    with open(csv_path, newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["decision"] == "allow"
    assert rows[0]["session_id"] == "session-4"


def test_include_context_can_omit_optional_fields(tmp_path):
    audit = AuditLogger(
        log_path=Path(tmp_path) / "audit.jsonl",
        config=_config(
            include_context={
                "user_id": False,
                "session_id": False,
                "timestamp": False,
                "tool_parameters": False,
                "decision_reason": False,
                "hook_type": False,
            }
        ),
    )

    entry = audit.log_decision(
        "PreToolUse",
        "allow",
        {"user_id": "person@example.invalid", "session_id": "session-5"},
        tool_parameters={"safe": True},
    )

    assert entry is not None
    assert "user_id" not in entry
    assert "session_id" not in entry
    assert "timestamp" not in entry
    assert "tool_parameters" not in entry
    assert "decision_reason" not in entry
    assert "hook_type" not in entry
    assert entry["policy_decision"]["timestamp"]


def test_process_hook_data_writes_final_decision_to_separate_audit_file(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    audit_path = tmp_path / "audit.jsonl"
    (config_dir / "ai-guardian.json").write_text(
        json.dumps(
            {
                "audit_logging": {
                    "enabled": True,
                    "output_file": str(audit_path),
                    "log_all_tool_calls": True,
                },
                "permissions": {"enabled": False},
                "prompt_injection": {"enabled": False},
                "secret_scanning": {"enabled": False},
                "scan_pii": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(config_dir))
    loaders._clear_config_cache()

    result = ai_guardian.process_hook_data(
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "hello",
            "session_id": "session-boundary",
        }
    )

    assert result["exit_code"] == 0
    entries = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["decision"] == "allow"
    assert entries[0]["session_id"] == "session-boundary"
    assert entries[0]["policy_decision"]["source"] == "hook"
