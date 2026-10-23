"""Local-only ZIP choice: no GitHub credentials, uploads, or lost diagnostics."""

import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_guardian.reporting import github_support as gh
from ai_guardian.reporting import support_bundle as bundles
from ai_guardian.ui import support_review as review


@pytest.fixture
def support_zip(monkeypatch, tmp_path):
    root = tmp_path / "reviewed"
    root.mkdir()
    (root / ".ai-read-deny").touch()
    (root / "ai-guardian.json").write_text(
        json.dumps(
            {"details": "Ordinary configuration detail. " * 4000, "last_field": "END"}
        ),
        encoding="utf-8",
    )
    (root / "omit.txt").write_text("unwanted diagnostic", encoding="utf-8")
    (root / "ai-guardian.log").write_text(
        "[Truncated: older content omitted; showing newest data.]\nLATEST\n",
        encoding="utf-8",
    )
    (root / "nested").mkdir()
    (root / "nested/settings.json").write_text('{"model":"日本語"}', encoding="utf-8")
    info = {
        "temp_path": str(root),
        "destination": gh.DESTINATION,
        "created": datetime.now(timezone.utc).isoformat(),
        "ttl_minutes": 30,
        "files": [
            {"name": name, "redactions": 0, "note": "synthetic"}
            for name in (
                "ai-guardian.json",
                "omit.txt",
                "ai-guardian.log",
                "nested/settings.json",
            )
        ],
    }
    bid = "support-20261022-ziptest"
    monkeypatch.setattr(bundles, "_active_bundles", {bid: info})
    monkeypatch.setattr(
        "ai_guardian.config.utils.get_state_dir", lambda: tmp_path / "state"
    )
    monkeypatch.setattr(
        gh,
        "GitHubClient",
        Mock(side_effect=AssertionError("ZIP must not authenticate")),
    )
    monkeypatch.setattr(gh, "credentials_available", lambda: False)
    monkeypatch.setattr(
        gh,
        "public_text",
        lambda text: (
            text.replace("private fragment", "[REDACTED]"),
            int("private fragment" in text),
        ),
    )
    publish = Mock(side_effect=AssertionError("ZIP must not publish"))
    monkeypatch.setattr(gh, "send_discussion", publish)
    return bid, root, info, publish


def zip_dialog(request):
    if request["mode"] == "delivery":
        return {"request_id": request["request_id"], "delivery": "zip"}
    assert request["mode"] == "bundle" and request["zip_export"] is True
    assert request["include_files"] == []
    assert "account" not in request and "categories" not in request
    return {
        "request_id": request["request_id"],
        "send": True,
        "include_files": [
            "ai-guardian.json",
            "ai-guardian.log",
            "nested/settings.json",
        ],
        "description": "Please investigate private fragment",
    }


def test_zip_contains_complete_selected_files_and_message_without_any_upload(
    support_zip, monkeypatch
):
    bid, root, info, publish = support_zip
    monkeypatch.setattr(gh, "review_dialog", zip_dialog)
    result = bundles.send_bundle(bid)
    assert result["delivery_status"] == "zip_only"
    archive = Path(result["zip_path"])
    assert archive.exists() and (archive.parent / ".ai-read-deny").exists()
    with zipfile.ZipFile(archive) as contents:
        assert set(contents.namelist()) == {
            "ai-guardian.json",
            "ai-guardian.log",
            "nested/settings.json",
            "support-message.txt",
        }
        for name in ("ai-guardian.json", "ai-guardian.log", "nested/settings.json"):
            assert contents.read(name) == (root / name).read_bytes()
        assert json.loads(contents.read("ai-guardian.json"))["last_field"] == "END"
        assert contents.read("support-message.txt") == b"Please investigate [REDACTED]"
    assert "ZIP created locally" in bundles._format_send_human(result)
    assert "No files were uploaded or sent to support" in bundles._format_send_human(
        result
    )
    assert "not encrypted" in bundles._format_send_human(result)
    assert "✓ Sent:" not in bundles._format_send_human(result)
    assert info["destination"] == gh.DESTINATION and root.exists()
    assert (root / "omit.txt").read_text() == "unwanted diagnostic"
    publish.assert_not_called()
    if os.name != "nt":
        assert archive.stat().st_mode & 0o077 == 0
        assert archive.parent.stat().st_mode & 0o077 == 0
    bundles._active_bundles.clear()
    assert bundles._load_last_bundle() == bid
    assert bundles._active_bundles[bid]["destination"] == gh.DESTINATION


@pytest.mark.parametrize("stage", ["delivery", "bundle"])
def test_zip_cancel_creates_no_archive_and_does_not_send(
    support_zip, monkeypatch, stage
):
    bid, root, info, publish = support_zip
    monkeypatch.setattr(
        gh,
        "review_dialog",
        lambda request: None if request["mode"] == stage else zip_dialog(request),
    )
    result = bundles.send_bundle(bid)
    assert result["error_code"] == "cancelled"
    assert not list(root.parent.rglob("*.zip"))
    assert info["destination"] == gh.DESTINATION
    publish.assert_not_called()


@pytest.mark.parametrize("delivery", ["gist", "", None])
def test_unapproved_delivery_choice_never_uploads_or_creates_zip(
    support_zip, monkeypatch, delivery
):
    bid, root, _, publish = support_zip
    monkeypatch.setattr(
        gh,
        "review_dialog",
        lambda request: {"request_id": request["request_id"], "delivery": delivery},
    )
    assert bundles.send_bundle(bid)["status"] == "error"
    assert not list(root.parent.rglob("*.zip"))
    publish.assert_not_called()


def test_public_choice_still_delegates_to_exact_github_consent(
    support_zip, monkeypatch
):
    bid, _, info, _ = support_zip
    monkeypatch.setattr(gh, "credentials_available", lambda: True)
    publisher = Mock(return_value={"status": "error", "error_code": "cancelled"})
    monkeypatch.setattr(gh, "send_discussion", publisher)
    monkeypatch.setattr(
        gh,
        "review_dialog",
        lambda request: {"request_id": request["request_id"], "delivery": "discussion"},
    )
    assert bundles.send_bundle(bid)["error_code"] == "cancelled"
    publisher.assert_called_once_with(bid, info)


def test_zip_archive_survives_bundle_cleanup(support_zip, monkeypatch):
    bid, root, _, _ = support_zip
    monkeypatch.setattr(gh, "review_dialog", zip_dialog)
    archive = Path(bundles.send_bundle(bid)["zip_path"])
    bundles._cleanup_bundle(bid)
    assert not root.exists()
    assert archive.is_file()


def test_paged_view_reaches_all_multibyte_configuration_content(
    support_zip, monkeypatch
):
    _, root, _, _ = support_zip
    name = "nested/settings.json"
    original = json.dumps(
        {"value": "日本語🙂" * 300, "last": "END"}, ensure_ascii=False
    )
    (root / name).write_text(original, encoding="utf-8")
    monkeypatch.setattr(review, "MAX_PREVIEW_BYTES", 53)
    parts = []
    offset = 0
    while True:
        page = review.read_preview(str(root), name, [name], offset=offset)
        assert "�" not in page.text
        parts.append(page.text)
        if page.next_offset is None:
            break
        assert page.next_offset > offset
        offset = page.next_offset
    assert len(parts) > 1 and "".join(parts) == original


def test_forged_zip_choice_is_rejected_before_export(support_zip, monkeypatch):
    bid, root, _, publish = support_zip
    monkeypatch.setattr(
        gh,
        "review_dialog",
        lambda request: {"request_id": "not-the-request", "delivery": "zip"},
    )
    assert bundles.send_bundle(bid)["status"] == "error"
    assert not list(root.parent.rglob("*.zip"))
    publish.assert_not_called()


def test_zip_io_failure_does_not_claim_success_or_upload(support_zip, monkeypatch):
    bid, root, _, publish = support_zip
    monkeypatch.setattr(gh, "review_dialog", zip_dialog)
    monkeypatch.setattr(
        bundles,
        "_zip_bundle",
        Mock(side_effect=OSError("private diagnostic failure details")),
    )
    result = bundles.send_bundle(bid)
    assert result["status"] == "error" and result["delivery_status"] == "not_sent"
    assert "private diagnostic failure details" not in result["message"]
    assert not list(root.parent.rglob("*.zip"))
    assert (root / "ai-guardian.json").exists()
    publish.assert_not_called()


def test_existing_zip_target_is_never_overwritten(support_zip, tmp_path):
    bid, root, _, _ = support_zip
    target = tmp_path / "existing.zip"
    target.write_bytes(b"previous export")
    with pytest.raises(FileExistsError):
        bundles._zip_bundle(root, bid, output_path=target)
    assert target.read_bytes() == b"previous export"


def test_unexpected_publication_error_does_not_claim_nothing_was_uploaded(
    support_zip, monkeypatch
):
    bid, _, _, _ = support_zip
    monkeypatch.setattr(gh, "credentials_available", lambda: True)
    monkeypatch.setattr(
        gh,
        "review_dialog",
        lambda request: {"request_id": request["request_id"], "delivery": "discussion"},
    )
    monkeypatch.setattr(
        gh, "send_discussion", Mock(side_effect=OSError("synthetic ambiguous result"))
    )
    result = bundles.send_bundle(bid)
    assert result["delivery_status"] == "uncertain"
    assert "Check the repository Discussions before retrying" in result["message"]
    assert "No files were uploaded" not in result["message"]


@pytest.mark.parametrize("offset", [-1, 100_000, "0"])
def test_preview_rejects_invalid_offsets_without_reading_outside_file(
    support_zip, offset
):
    _, root, _, _ = support_zip
    page = review.read_preview(
        str(root), "nested/settings.json", ["nested/settings.json"], offset=offset
    )
    assert page.text.startswith("Cannot preview") and page.next_offset is None


@pytest.mark.parametrize("selection", [[], ["omit.txt"]])
def test_empty_or_removed_zip_selection_never_creates_archive_or_uploads(
    support_zip, monkeypatch, selection
):
    bid, root, _, publish = support_zip

    def dialog(request):
        if request["mode"] == "delivery":
            return {"request_id": request["request_id"], "delivery": "zip"}
        if selection:
            (root / "omit.txt").unlink()
        return {
            "request_id": request["request_id"],
            "send": True,
            "include_files": selection,
            "description": "Message alone is not a file selection",
        }

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = bundles.send_bundle(bid)
    assert result["status"] == "error" and result["delivery_status"] == "not_sent"
    assert (
        not list(root.parent.rglob("*.zip"))
        and not (root / "support-message.txt").exists()
    )
    publish.assert_not_called()


def test_paged_preview_does_not_silently_drop_invalid_utf8_at_eof(
    support_zip, monkeypatch
):
    _, root, _, _ = support_zip
    name = "nested/settings.json"
    (root / name).write_bytes(b"ordinary text" * 10 + b"\xe2\x82")
    monkeypatch.setattr(review, "MAX_PREVIEW_BYTES", 53)
    offset = 0
    while True:
        page = review.read_preview(str(root), name, [name], offset=offset)
        if page.next_offset is None:
            assert "not UTF-8 text" in page.text
            break
        offset = page.next_offset
