"""Tray/terminal support hand-off using synthetic, user-reviewable files only."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_guardian.reporting import support_bundle as bundles


@pytest.fixture
def pending(monkeypatch, tmp_path):
    monkeypatch.setattr(bundles, "_active_bundles", {})
    destination = tmp_path / "exports"
    monkeypatch.setattr(
        bundles, "_get_support_config", lambda: {"export_destination": str(destination)}
    )
    root = tmp_path / "temporary-review"
    root.mkdir()
    (root / ".ai-read-deny").touch()
    (root / "diagnostic.txt").write_text("Synthetic diagnostics")
    info = {
        "temp_path": str(root),
        "destination": str(destination),
        "created": datetime.now(timezone.utc).isoformat(),
        "ttl_minutes": 30,
        "files": [{"name": "diagnostic.txt", "redactions": 0}],
    }
    bundle_id = "support-20261022-1234abcd"
    bundles._active_bundles[bundle_id] = info
    bundles._persist_bundle_ref(bundle_id, info)
    return bundle_id, root, destination


@pytest.mark.parametrize("preserve", [False, True])
def test_local_export_remains_sendable_across_processes(pending, preserve):
    bundle_id, root, destination = pending
    bundles._active_bundles[bundle_id]["preserve_directory"] = preserve
    first = bundles.send_bundle(bundle_id)
    exported = destination / bundle_id

    assert first["status"] == "sent"
    assert first["delivery_status"] == "local_only"
    assert exported.is_dir()
    assert (exported / ".ai-read-deny").exists()
    assert root.exists() is preserve
    bundles._active_bundles.clear()  # Subsequent CLI process has no in-memory state.

    assert bundles._load_last_bundle() == bundle_id
    assert bundles._active_bundles[bundle_id]["temp_path"] == str(exported)
    (exported / "diagnostic.txt").unlink()
    second = bundles.send_bundle(bundle_id)

    assert second["status"] == "sent"
    assert second["delivery_status"] == "local_only"
    assert second["destination"] == first["destination"]
    assert not (exported / "diagnostic.txt").exists()  # Never recollect removed files.
    assert exported.exists()


def test_recover_export_created_before_handoff_fix(pending):
    bundle_id, root, destination = pending
    # Reproduce the old flow: copy locally, delete temp, leave the old reference.
    exported = destination / bundle_id
    exported.mkdir(parents=True)
    (exported / "diagnostic.txt").write_text("Previously exported diagnostics")
    (root / "diagnostic.txt").unlink()
    (root / ".ai-read-deny").unlink()
    root.rmdir()
    bundles._active_bundles.clear()

    assert bundles._load_last_bundle() == bundle_id
    assert bundles.send_bundle(bundle_id)["destination"] == str(exported)
    assert (
        exported / "diagnostic.txt"
    ).read_text() == "Previously exported diagnostics"
    assert (exported / ".ai-read-deny").exists()


def test_recovery_does_not_refresh_bundle_expiry(pending):
    bundle_id, root, destination = pending
    exported = destination / bundle_id
    exported.mkdir(parents=True)
    info = bundles._active_bundles[bundle_id]
    info["created"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    bundles._persist_bundle_ref(bundle_id, info)
    bundles._active_bundles.clear()
    assert bundles._load_last_bundle() is None
    assert root.exists()
    assert exported.exists()


def test_local_export_failure_preserves_pending_review(pending, monkeypatch):
    bundle_id, root, _ = pending
    monkeypatch.setattr(
        bundles.shutil, "copy2", Mock(side_effect=OSError("unavailable"))
    )
    result = bundles.send_bundle(bundle_id)
    assert result["status"] == "error"
    assert root.exists()
    assert bundles._load_last_bundle() == bundle_id


def test_support_status_restores_pending_bundle_after_process_restart(pending):
    bundle_id, _, _ = pending
    result = bundles.send_bundle(bundle_id)
    bundles._active_bundles.clear()
    status = bundles._get_bundle_status()
    assert status["pending_bundles"][0]["bundle_id"] == bundle_id
    assert status["pending_bundles"][0]["temp_path"] == result["destination"]


def test_cli_local_prompt_and_result_never_claim_support_delivery(
    pending, monkeypatch, capsys
):
    bundle_id, root, destination = pending
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    confirm = Mock(return_value="yes")
    monkeypatch.setattr("builtins.input", confirm)
    args = SimpleNamespace(support_command="send")

    assert bundles.support_command(args) == 0
    output = capsys.readouterr().out
    assert (
        confirm.call_args.args[0] == f"Export bundle locally to {destination}? [y/N] "
    )
    assert (
        "Delete any files you do not want to send from this directory before continuing."
        in output
    )
    assert "✓ Exported locally:" in output
    assert "No files were sent to support. No Discussion was created." in output
    assert "✓ Sent:" not in output
    assert str(destination / bundle_id) in output
    assert not root.exists()

    bundles._active_bundles.clear()
    assert bundles.support_command(args) == 0
    output = capsys.readouterr()
    assert "No pending bundle" not in output.err
    assert str(destination / bundle_id) in output.out


def test_combined_flow_does_not_tell_user_to_send_again(pending, monkeypatch, capsys):
    bundle_id, _, _ = pending
    monkeypatch.setattr(
        bundles,
        "prepare_bundle",
        lambda: {"bundle_id": bundle_id, **bundles._active_bundles[bundle_id]},
    )
    assert (
        bundles.support_command(
            SimpleNamespace(support_command="send", prepare=True, yes=True)
        )
        == 0
    )
    assert "After reviewing the files, run:" not in capsys.readouterr().out


def test_local_json_result_explicitly_identifies_export_not_submission(pending, capsys):
    assert (
        bundles.support_command(
            SimpleNamespace(support_command="send", yes=True, json=True)
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["delivery_status"] == "local_only"
    assert Path(result["destination"]).is_dir()


def test_expired_reference_explains_explicit_local_copy_reuse(pending, capsys):
    bundle_id, _, _ = pending
    info = bundles._active_bundles[bundle_id]
    info["created"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    bundles._persist_bundle_ref(bundle_id, info)
    bundles._active_bundles.clear()
    assert bundles.support_command(SimpleNamespace(support_command="send")) == 1
    error = capsys.readouterr().err
    assert "expired or been removed" in error
    assert "support send --bundle <exported-directory>" in error


def test_local_export_does_not_overwrite_an_unrelated_directory(pending):
    bundle_id, root, destination = pending
    target = destination / bundle_id
    target.mkdir(parents=True)
    (target / "existing.txt").write_text("User's unrelated file")
    result = bundles.send_bundle(bundle_id)
    assert result["status"] == "error"
    assert (target / "existing.txt").read_text() == "User's unrelated file"
    assert not (target / "diagnostic.txt").exists()
    assert root.exists()


def test_local_label_never_misrepresents_legacy_email_routing():
    assert bundles._is_local_destination("~/support-bundles")
    assert not bundles._is_local_destination("/legacy/support@example.com")
    assert not bundles._is_local_destination("mailto:support@example.com")
