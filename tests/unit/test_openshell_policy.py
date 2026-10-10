"""Tests for OpenShell policy discovery and tray update preparation."""

import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ai_guardian.openshell_policy import (
    NO_POLICY_CHOICE,
    discover_openshell_policies,
    policy_choice_values,
    resolve_openshell_policy_choice,
)
from ai_guardian.sandbox import (
    _write_edited_openshell_policy,
    apply_openshell_policy,
    get_openshell_base_policy,
    list_openshell_sandboxes,
    prepare_openshell_policy_update,
)


def test_policy_discovery_exposes_validation_and_summary(tmp_path, monkeypatch):
    valid = tmp_path / "middleware.yaml"
    valid.write_text(
        "version: 1\nnetwork_middlewares:\n  content-guard:\n"
        "    middleware: content-guard\n",
        encoding="utf-8",
    )
    invalid = tmp_path / "broken.yaml"
    invalid.write_text("version: 2\n", encoding="utf-8")

    monkeypatch.delenv("AI_GUARDIAN_OPEN_SHELL_POLICY", raising=False)
    monkeypatch.delenv("AI_GUARDIAN_OPENSHELL_POLICY", raising=False)
    with patch("ai_guardian.openshell_policy._policy_roots", return_value=(tmp_path,)):
        options = discover_openshell_policies()

    valid_option = next(option for option in options if option.path == valid)
    invalid_option = next(option for option in options if option.path == invalid)
    assert valid_option.valid is True
    assert "middleware=content-guard" in valid_option.display
    assert invalid_option.valid is False
    assert "invalid:" in invalid_option.display
    assert policy_choice_values(options)[0] == NO_POLICY_CHOICE
    assert resolve_openshell_policy_choice(valid_option.display, options) == valid


def test_list_openshell_sandboxes_filters_deleted_records():
    payload = {
        "sandboxes": [
            {"name": "ready", "phase": "Ready", "labels": {"team": "security"}},
            {"name": "gone", "phase": "Deleted"},
            {"name": "starting", "status": "Provisioning"},
        ]
    }
    result = SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
    with patch("ai_guardian.sandbox._run_capture", return_value=result):
        sandboxes = list_openshell_sandboxes(SimpleNamespace(openshell_cli="openshell"))

    assert [sandbox["name"] for sandbox in sandboxes] == ["ready", "starting"]
    assert sandboxes[0]["labels"] == {"team": "security"}


def test_prepare_policy_update_preserves_existing_controls(tmp_path):
    current = {
        "version": 1,
        "filesystem_policy": {"read_write": ["/sandbox"]},
        "network_policies": {"codex": {"endpoints": []}},
    }
    result = SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"policy": current}),
        stderr="",
    )
    overlay = tmp_path / "middleware.yaml"
    overlay.write_text(
        "version: 1\nnetwork_middlewares:\n  content-guard:\n"
        "    middleware: content-guard\n    on_error: fail_closed\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(openshell_cli="openshell")
    with patch("ai_guardian.sandbox._run_capture", return_value=result):
        policy_path, temporary_dir, before, after = prepare_openshell_policy_update(
            args, "demo", [overlay]
        )
    try:
        assert before["filesystem_policy"] == current["filesystem_policy"]
        assert after["network_policies"] == current["network_policies"]
        assert after["network_middlewares"]["content-guard"]["middleware"] == (
            "content-guard"
        )
        if sys.platform != "win32":
            assert os.stat(policy_path).st_mode & 0o777 == 0o600
    finally:
        shutil.rmtree(temporary_dir)


def test_prepare_policy_update_rejects_erasing_filesystem_controls(tmp_path):
    current = {
        "version": 1,
        "filesystem_policy": {"read_write": ["/sandbox"]},
        "network_policies": {},
    }
    result = SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"policy": current}),
        stderr="",
    )
    overlay = tmp_path / "unsafe.yaml"
    overlay.write_text("version: 1\nfilesystem_policy: null\n", encoding="utf-8")
    with patch("ai_guardian.sandbox._run_capture", return_value=result):
        with pytest.raises(ValueError, match="filesystem_policy"):
            prepare_openshell_policy_update(
                SimpleNamespace(openshell_cli="openshell"), "demo", [overlay]
            )


def test_edited_policy_is_validated_and_written_to_private_prepared_file(tmp_path):
    current = {
        "version": 1,
        "filesystem_policy": {"read_write": ["/sandbox"]},
        "network_policies": {"codex": {"endpoints": []}},
    }
    policy_path = tmp_path / "prepared.yaml"
    policy_path.write_text("version: 1\n", encoding="utf-8")
    edited = (
        "version: 1\nfilesystem_policy:\n  read_write: [/sandbox]\n"
        "network_policies:\n  github:\n    endpoints: [api.github.com]\n"
        "network_middlewares: {}\n"
    )

    result = _write_edited_openshell_policy(policy_path, "demo", current, edited)

    assert result["network_policies"]["github"]["endpoints"] == ["api.github.com"]
    assert result["filesystem_policy"] == current["filesystem_policy"]
    assert policy_path.read_text(encoding="utf-8").startswith("version: 1\n")
    if sys.platform != "win32":
        assert os.stat(policy_path).st_mode & 0o777 == 0o600


def test_edited_policy_rejects_invalid_yaml_and_removing_base_controls(tmp_path):
    current = {
        "version": 1,
        "filesystem_policy": {"read_write": ["/sandbox"]},
        "network_policies": {},
    }
    policy_path = tmp_path / "prepared.yaml"
    original = "version: 1\nfilesystem_policy: {}\nnetwork_policies: {}\n"
    policy_path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="invalid YAML"):
        _write_edited_openshell_policy(policy_path, "demo", current, "version: [")
    with pytest.raises(ValueError, match="must preserve filesystem_policy"):
        _write_edited_openshell_policy(
            policy_path,
            "demo",
            current,
            "version: 1\nnetwork_policies: {}\n",
        )

    assert policy_path.read_text(encoding="utf-8") == original


def test_policy_validation_rejects_null_control_sections(tmp_path):
    policy = tmp_path / "unsafe.yaml"
    policy.write_text("version: 1\nnetwork_middlewares: null\n", encoding="utf-8")

    with pytest.raises(ValueError, match="network_middlewares"):
        from ai_guardian.openshell_policy import load_openshell_policy

        load_openshell_policy(policy)


def test_apply_openshell_policy_uses_native_complete_policy_command(tmp_path):
    policy_path = tmp_path / "policy.yaml"
    with patch("ai_guardian.sandbox._run", return_value=0) as run:
        result = apply_openshell_policy(
            SimpleNamespace(openshell_cli="openshell"),
            "demo",
            policy_path,
            output=[],
        )

    assert result == 0
    assert run.call_args.args[0] == [
        "openshell",
        "policy",
        "set",
        "demo",
        "--policy",
        str(policy_path),
        "--wait",
    ]


def test_get_base_policy_reports_cli_errors():
    result = SimpleNamespace(returncode=1, stdout="", stderr="sandbox missing")
    with patch("ai_guardian.sandbox._run_capture", return_value=result):
        with pytest.raises(ValueError, match="sandbox missing"):
            get_openshell_base_policy(
                SimpleNamespace(openshell_cli="openshell"), "missing"
            )
