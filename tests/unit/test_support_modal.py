"""User-only tray modal, file inclusion, and inert previews; never live support."""

import os
import sys
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from ai_guardian.reporting import github_support as gh
from ai_guardian.reporting import support_bundle as bundles
from ai_guardian.tray import support as tray_support
from ai_guardian.ui import support_review


@pytest.fixture
def bundle(monkeypatch, tmp_path):
    root = tmp_path / "reviewed"
    root.mkdir()
    (root / ".ai-read-deny").touch()
    (root / "keep.txt").write_text("included diagnostic")
    (root / "leave-out.txt").write_text("excluded diagnostic")
    info = {
        "temp_path": str(root),
        "destination": str(tmp_path / "exports"),
        "created": datetime.now(timezone.utc).isoformat(),
        "ttl_minutes": 30,
        "files": [
            {"name": name, "redactions": 0} for name in ("keep.txt", "leave-out.txt")
        ],
        "preserve_directory": True,
    }
    bundle_id = "support-20261022-modal123"
    monkeypatch.setattr(bundles, "_active_bundles", {bundle_id: info})
    monkeypatch.setattr(
        bundles,
        "_get_support_config",
        lambda: {"export_destination": info["destination"]},
    )
    monkeypatch.setattr(
        bundles, "prepare_bundle", lambda **kwargs: {"bundle_id": bundle_id, **info}
    )
    return bundle_id, root, info


def test_selection_persists_without_changing_reviewed_originals(bundle):
    bundle_id, root, info = bundle
    bundles._set_file_selection(bundle_id, info, ["keep.txt"])
    bundles._active_bundles.clear()
    assert bundles._load_last_bundle() == bundle_id
    result = bundles.send_bundle(bundle_id)
    exported = Path(result["destination"])
    assert (exported / "keep.txt").read_text() == "included diagnostic"
    assert not (exported / "leave-out.txt").exists()
    assert (root / "leave-out.txt").read_text() == "excluded diagnostic"
    assert (root / "keep.txt").exists()


@pytest.mark.parametrize(
    "selection",
    [["../outside.txt"], ["unknown.txt"], "keep.txt", ["keep.txt", "keep.txt"]],
)
def test_invalid_file_selection_cannot_send_or_modify_files(bundle, selection):
    bundle_id, root, info = bundle
    with pytest.raises(ValueError):
        bundles._set_file_selection(bundle_id, info, selection)
    assert "include_files" not in info
    assert (root / "leave-out.txt").exists()


def test_file_choices_must_be_saved_before_they_can_authorize_export(
    bundle, monkeypatch
):
    bundle_id, root, info = bundle
    monkeypatch.setattr(bundles, "_persist_bundle_ref", Mock(return_value=False))
    with pytest.raises(ValueError, match="could not be saved"):
        bundles._set_file_selection(bundle_id, info, ["keep.txt"])
    assert "include_files" not in info
    assert (root / "leave-out.txt").exists()


@pytest.mark.parametrize(
    "destination", ["s3://support-bucket/prefix/", "gs://support-bucket/prefix/"]
)
def test_selected_legacy_upload_uses_only_checked_files(
    bundle, monkeypatch, destination
):
    bundle_id, root, info = bundle
    info["destination"] = destination
    bundles._set_file_selection(bundle_id, info, ["keep.txt"])
    backend = "_send_to_s3" if destination.startswith("s3:") else "_send_to_gcs"

    def send(bid, outgoing, dest):
        assert bid == bundle_id and dest == destination
        assert outgoing != root
        assert (outgoing / "keep.txt").read_text() == "included diagnostic"
        assert not (outgoing / "leave-out.txt").exists()
        return {"status": "error", "message": "Synthetic upload failure"}

    monkeypatch.setattr(bundles, backend, send)
    assert bundles.send_bundle(bundle_id)["status"] == "error"
    assert (root / "leave-out.txt").exists()
    assert bundles._active_bundles[bundle_id]["include_files"] == ["keep.txt"]


def test_public_selection_is_bound_to_final_approval(
    bundle, monkeypatch, support_github_transport
):
    bundle_id, root, info = bundle
    info["destination"] = gh.DESTINATION
    # The user can deselect an otherwise unsupported file before body building.
    (root / "leave-out.txt").write_bytes(b"\xffbinary")
    client = Mock()
    client.discover.return_value = {
        "account_id": "U_test",
        "login": "reporter",
        "repository_id": "R_support",
        "categories": {"bug-reports": "D_bug", "q-a": "D_qa"},
    }
    client.scrub.side_effect = lambda text: text
    client.create.return_value = f"{gh.REPOSITORY_URL}/discussions/123"
    support_github_transport(client)
    monkeypatch.setattr(gh, "GitHubClient", lambda: client)

    def dialog(request):
        if request["mode"] == "delivery":
            return {"request_id": request["request_id"], "delivery": "discussion"}
        if request["mode"] == "upload":
            assert "included diagnostic" in request["body"]
            return {"request_id": request["request_id"], "approved": True}
        assert request["destination"] == f"{gh.REPOSITORY_URL}/discussions"
        if request["mode"] == "edit":
            assert {item["name"] for item in request["files"]} == {
                "keep.txt",
                "leave-out.txt",
            }
            return {
                "request_id": request["request_id"],
                **request["context"],
                "category": "q-a",
                "title": "A usage question",
                "description": "Steps to reproduce the issue.",
                "include_files": ["keep.txt"],
            }
        assert "included diagnostic" not in request["body"]
        assert "https://gist.github.com/reporter/" in request["body"]
        assert "leave-out.txt" not in request["body"]
        assert request["category"] == "Q&A"
        # A changed selection after exact approval cannot smuggle other content.
        (root / "leave-out.txt").write_text("not approved")
        info["include_files"] = ["keep.txt", "leave-out.txt"]
        return {"request_id": request["request_id"], "approved": True}

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = bundles.send_bundle(bundle_id)
    assert result["error_code"] == "changed"
    client.create.assert_not_called()
    assert (root / "leave-out.txt").exists()


def test_tray_flow_shows_destination_selection_and_result_without_shell(
    bundle, monkeypatch
):
    bundle_id, root, info = bundle
    modes = []

    def dialog(request):
        modes.append(request["mode"])
        if request["mode"] == "bundle":
            assert request["destination"] == str(Path(info["destination"]) / bundle_id)
            assert request["local_only"] is True
            assert "categories" not in request
            return {
                "request_id": request["request_id"],
                "send": True,
                "include_files": ["keep.txt"],
                "description": "Steps to reproduce the issue.",
            }
        assert request["mode"] == "result"
        assert "Exported locally" in request["message"]
        assert "No files were sent to support" in request["message"]
        return None

    monkeypatch.setattr(gh, "review_dialog", dialog)
    monkeypatch.setattr(
        "builtins.input", Mock(side_effect=AssertionError("No terminal prompt"))
    )
    monkeypatch.setattr(
        "ai_guardian.daemon.multi_client._launch_in_terminal",
        Mock(side_effect=AssertionError("No shell")),
    )
    result = tray_support.run_support_flow()
    assert modes == ["bundle", "result"]
    assert result["delivery_status"] == "local_only"
    assert not (Path(result["destination"]) / "leave-out.txt").exists()
    assert (root / "leave-out.txt").exists()


def test_tray_cancel_never_calls_sender_or_changes_files(bundle, monkeypatch):
    _, root, _ = bundle
    sender = Mock(side_effect=AssertionError("Cancelled"))
    monkeypatch.setattr(bundles, "send_bundle", sender)
    monkeypatch.setattr(gh, "review_dialog", lambda request: None)
    monkeypatch.setattr(tray_support, "show_notification", Mock())
    result = tray_support.run_support_flow()
    assert result["error_code"] == "cancelled"
    sender.assert_not_called()
    assert (root / "leave-out.txt").exists()


def test_result_dialog_failure_never_claims_successful_export_was_unsent(
    bundle, monkeypatch
):
    def dialog(request):
        if request["mode"] == "bundle":
            return {
                "request_id": request["request_id"],
                "send": True,
                "include_files": ["keep.txt"],
                "description": "Steps to reproduce the issue.",
            }
        raise gh.GitHubError("Result window unavailable", code="review_unavailable")

    monkeypatch.setattr(gh, "review_dialog", dialog)
    notify = Mock()
    monkeypatch.setattr(tray_support, "show_notification", notify)
    assert tray_support.run_support_flow()["delivery_status"] == "local_only"
    assert "exported locally" in notify.call_args.args[1]
    assert "Nothing was sent" not in notify.call_args.args[1]


@pytest.fixture
def native(monkeypatch):
    root = Mock()
    booleans = []

    def boolean(*args, value=False, **kwargs):
        variable = Mock()
        variable.get.return_value = value
        variable.set.side_effect = lambda value: setattr(
            variable.get, "return_value", value
        )
        booleans.append(variable)
        return variable

    tk = SimpleNamespace(
        Tk=Mock(return_value=root),
        Toplevel=Mock(),
        BooleanVar=boolean,
        StringVar=Mock(),
        Canvas=Mock(),
        TclError=type("TclError", (Exception,), {}),
    )
    ttk = SimpleNamespace(
        Frame=Mock(),
        Label=Mock(),
        Button=Mock(),
        Checkbutton=Mock(),
        Combobox=Mock(),
        Entry=Mock(),
        LabelFrame=Mock(),
        Scrollbar=Mock(),
        Style=Mock(),
    )
    text = Mock()
    text.return_value.get.return_value = ""
    ttk.Entry.return_value.get.return_value = ""
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    tk.ttk = ttk
    monkeypatch.setitem(
        sys.modules, "tkinter.scrolledtext", SimpleNamespace(ScrolledText=text)
    )
    return root, ttk, text, booleans


@pytest.mark.parametrize("saved", [None, [], ["z-last.txt"], ["doctor.json"]])
def test_diagnostics_are_alphabetical_with_doctor_first_and_only_new_doctor_checked(
    native, saved
):
    _, ttk, _, _ = native
    names = ["z-last.txt", "beta.json", "doctor.json", "Alpha.json", "ai-guardian.json"]
    request = {"files": [{"name": name} for name in names]}
    if saved is not None:
        request["include_files"] = saved
    choices = support_review._file_choices(Mock(), request)
    expected = [
        "doctor.json",
        "ai-guardian.json",
        "Alpha.json",
        "beta.json",
        "z-last.txt",
    ]
    assert list(choices) == expected
    assert [call.kwargs["text"] for call in ttk.Checkbutton.call_args_list] == expected
    assert [name for name, variable in choices.items() if variable.get()] == (
        ["doctor.json"] if saved is None else saved
    )
    assert [item["name"] for item in request["files"]] == names


@pytest.mark.parametrize(
    "mode,zip_export", [("edit", False), ("bundle", False), ("bundle", True)]
)
def test_review_requires_user_title_and_message_even_with_doctor_preselected(
    native, mode, zip_export
):
    root, ttk, text, choices = native
    action = Mock()
    label = "Create ZIP" if zip_export else "Send"
    ttk.Button.side_effect = lambda *args, **kwargs: (
        action if kwargs.get("text") == label else Mock()
    )
    ttk.Combobox.return_value.get.return_value = "Bug Reports"

    def interact():
        assert choices[0].get() is True
        action.configure.assert_called_with(state="disabled")
        button = next(
            call.kwargs
            for call in ttk.Button.call_args_list
            if call.kwargs["text"] == label
        )
        button["command"]()
        root.destroy.assert_not_called()
        if mode == "edit":
            ttk.Entry.return_value.insert.assert_called_once_with(0, "")
            ttk.Entry.return_value.get.return_value = "A user-written title"
            sys.modules["tkinter"].StringVar.return_value.trace_add.call_args.args[1]()
            action.configure.assert_called_with(state="disabled")
        text.return_value.get.return_value = "Steps to reproduce the issue."
        text.return_value.bind.call_args.args[1]()
        action.configure.assert_called_with(state="normal")
        text.return_value.get.return_value = " \n\t "
        text.return_value.bind.call_args.args[1]()
        action.configure.assert_called_with(state="disabled")
        button["command"]()
        root.destroy.assert_not_called()
        assert any(
            call.kwargs.get("text") == "A support message is required."
            for call in ttk.Label.return_value.configure.call_args_list
        )
        text.return_value.get.return_value = "Steps to reproduce the issue."
        if mode == "edit":
            ttk.Entry.return_value.get.return_value = "   "
            sys.modules["tkinter"].StringVar.return_value.trace_add.call_args.args[1]()
            action.configure.assert_called_with(state="disabled")
            button["command"]()
            root.destroy.assert_not_called()
            assert any(
                call.kwargs.get("text") == "A support title is required."
                for call in ttk.Label.return_value.configure.call_args_list
            )
            ttk.Entry.return_value.get.return_value = "A user-written title"
            sys.modules["tkinter"].StringVar.return_value.trace_add.call_args.args[1]()
        text.return_value.bind.call_args.args[1]()
        action.configure.assert_called_with(state="normal")
        button["command"]()

    root.mainloop.side_effect = interact
    result = support_review.show_review(
        {
            "mode": mode,
            "request_id": "required-context",
            "temp_path": "synthetic",
            "zip_export": zip_export,
            "files": [{"name": "doctor.json"}],
            "account": "reporter",
            "warning": gh.PUBLIC_WARNING,
            "categories": dict(gh.CATEGORIES),
            "context": {"title": "", "description": "", "category": "bug-reports"},
        }
    )
    assert result["include_files"] == ["doctor.json"]
    assert result["description"] == "Steps to reproduce the issue."
    if mode == "edit":
        assert result["title"] == "A user-written title"


@pytest.mark.parametrize("message", ["", " \n\t "])
def test_legacy_review_rejects_empty_messages_before_export(
    bundle, monkeypatch, message
):
    bundle_id, root, info = bundle
    monkeypatch.setattr(
        gh,
        "review_dialog",
        lambda request: {
            "request_id": request["request_id"],
            "send": True,
            "include_files": ["keep.txt"],
            "description": message,
        },
    )
    with pytest.raises(gh.GitHubError, match="A support message is required"):
        bundles._review_bundle_selection(bundle_id, info)
    assert not (root / "support-message.txt").exists()
    assert "include_files" not in info


def test_native_modal_has_view_checkboxes_destination_and_cancel_send(bundle, native):
    _, root_path, info = bundle
    root, ttk, text, booleans = native
    text.return_value.get.return_value = "Please investigate this issue."

    def interact():
        assert len(booleans) == 2
        assert all(not variable.get() for variable in booleans)
        booleans[0].set(True)
        ttk.Checkbutton.call_args_list[0].kwargs["command"]()
        next(
            call for call in ttk.Button.call_args_list if call.kwargs["text"] == "View"
        ).kwargs["command"]()
        assert any(
            call.args == ("1.0", "included diagnostic")
            for call in text.return_value.insert.call_args_list
        )
        next(
            call for call in ttk.Button.call_args_list if call.kwargs["text"] == "Send"
        ).kwargs["command"]()

    root.mainloop.side_effect = interact
    reply = support_review.show_review(
        {
            "mode": "bundle",
            "request_id": "challenge",
            "temp_path": str(root_path),
            "destination": "local final location",
            "local_only": True,
            "files": info["files"],
        }
    )
    assert reply == {
        "request_id": "challenge",
        "send": True,
        "include_files": ["keep.txt"],
        "description": "Please investigate this issue.",
    }
    assert "Cancel" in [call.kwargs["text"] for call in ttk.Button.call_args_list]
    assert any(
        "local final location" in call.kwargs.get("text", "")
        for call in ttk.Label.call_args_list
    )
    ttk.Combobox.assert_not_called()
    assert (root_path / "leave-out.txt").exists()


def test_preview_never_executes_markup_or_reads_outside_the_bundle(bundle):
    _, root, _ = bundle
    assert (
        support_review.read_preview(str(root), "keep.txt", ["keep.txt"]).text
        == "included diagnostic"
    )
    for name in ("../outside.txt", "/etc/passwd", "not-reviewed.txt"):
        assert support_review.read_preview(
            str(root), name, ["keep.txt"]
        ).text.startswith("Cannot preview")
    (root / "keep.txt").write_text("<script>inert text</script>")
    assert (
        support_review.read_preview(str(root), "keep.txt", ["keep.txt"]).text
        == "<script>inert text</script>"
    )


@pytest.mark.skipif(os.name == "nt", reason="Symlink creation needs Windows privileges")
def test_preview_rejects_links(bundle, tmp_path):
    _, root, _ = bundle
    source = tmp_path / "private.txt"
    source.write_text("unreviewed source")
    (root / "linked.txt").symlink_to(source)
    assert (
        "unreviewed source"
        not in support_review.read_preview(str(root), "linked.txt", ["linked.txt"]).text
    )


def test_preview_is_bounded_and_handles_binary_without_raw_fallback(
    bundle, monkeypatch
):
    _, root, _ = bundle
    monkeypatch.setattr(support_review, "MAX_PREVIEW_BYTES", 8)
    page = support_review.read_preview(str(root), "keep.txt", ["keep.txt"])
    assert page.text == "included"
    assert page.next_offset == 8
    (root / "keep.txt").write_bytes(b"\xff")
    assert (
        "UTF-8" in support_review.read_preview(str(root), "keep.txt", ["keep.txt"]).text
    )


def test_launcher_is_single_flight_and_never_opens_terminal(monkeypatch):
    monkeypatch.setattr(tray_support, "_review_lock", threading.Lock())
    monkeypatch.setattr("ai_guardian.ui.display.get_preferred_ui", lambda: "tkinter")
    monkeypatch.delenv("AI_GUARDIAN_NO_TKINTER", raising=False)
    thread = Mock()
    monkeypatch.setattr(tray_support.threading, "Thread", thread)
    flow = Mock()
    monkeypatch.setattr(tray_support, "run_support_flow", flow)
    monkeypatch.setattr(tray_support, "show_notification", Mock())
    assert tray_support.open_support_dialog() is True
    assert tray_support.open_support_dialog() is False
    thread.assert_called_once()
    flow.assert_not_called()
    thread.call_args.kwargs["target"]()
    flow.assert_called_once()
    assert not tray_support._review_lock.locked()


@pytest.mark.parametrize(
    "destination, expected",
    [
        ("s3://bucket/prefix/", "s3://bucket/prefix//support-id/"),
        ("gs://bucket/prefix/", "gs://bucket/prefix/support-id/"),
        ("mailto:help@example.com", "mailto:help@example.com"),
    ],
)
def test_readonly_final_destination_matches_legacy_transport_layout(
    destination, expected
):
    assert (
        bundles._final_destination("support-id", {"destination": destination})
        == expected
    )


def test_selected_nested_files_are_preserved_in_email_zip(bundle, monkeypatch):
    bundle_id, root, info = bundle
    (root / ".ai-guardian").mkdir()
    (root / ".ai-guardian/config.json").write_text('{"safe":true}')
    info["files"].append({"name": ".ai-guardian/config.json", "redactions": 0})
    info["destination"] = "mailto:help@example.com"
    bundles._set_file_selection(
        bundle_id, info, ["keep.txt", ".ai-guardian/config.json"]
    )

    def send(bid, outgoing, destination):
        archive = bundles._zip_bundle(outgoing, bid)
        try:
            with zipfile.ZipFile(archive) as contents:
                assert set(contents.namelist()) == {
                    "keep.txt",
                    ".ai-guardian/config.json",
                }
                assert contents.read(".ai-guardian/config.json") == b'{"safe":true}'
        finally:
            archive.unlink()
        return {"status": "sent", "destination": destination}

    monkeypatch.setattr(bundles, "_send_to_email", send)
    assert bundles.send_bundle(bundle_id)["status"] == "sent"
    assert (root / "leave-out.txt").exists()


def test_s3_includes_nested_prepared_files_without_markers(bundle, monkeypatch):
    _, root, _ = bundle
    (root / "nested").mkdir()
    (root / "nested/config.json").write_text("{}")
    (root / "nested/.ai-read-deny").touch()
    client = Mock()
    monkeypatch.setitem(
        sys.modules, "boto3", SimpleNamespace(client=Mock(return_value=client))
    )
    assert bundles._send_to_s3("bundle", root, "s3://bucket/prefix")["status"] == "sent"
    keys = {call.args[2] for call in client.upload_file.call_args_list}
    assert "prefix/bundle/nested/config.json" in keys
    assert all(".ai-read-deny" not in key for key in keys)


def test_gcs_includes_nested_prepared_files_without_markers(bundle, monkeypatch):
    _, root, _ = bundle
    (root / "nested").mkdir()
    (root / "nested/config.json").write_text("{}")
    (root / "nested/.ai-read-deny").touch()
    monkeypatch.setattr(
        bundles, "_get_gcs_token_from_adc", lambda: "unissued-test-value"
    )
    upload = MagicMock()
    monkeypatch.setattr(bundles, "urlopen", upload)
    assert (
        bundles._send_to_gcs("bundle", root, "gs://bucket/prefix")["status"] == "sent"
    )
    urls = [call.args[0].full_url for call in upload.call_args_list]
    assert any("prefix%2Fbundle%2Fnested%2Fconfig.json" in url for url in urls)
    assert all(".ai-read-deny" not in url for url in urls)


def test_native_public_category_is_restricted_and_updates_destination(bundle, native):
    _, directory, info = bundle
    root, ttk, text, choices = native
    ttk.Combobox.return_value.get.return_value = "Q&A"
    ttk.Entry.return_value.get.return_value = "A usage question"
    text.return_value.get.return_value = "Helpful context"

    def interact():
        choices[0].set(True)
        ttk.Checkbutton.call_args_list[0].kwargs["command"]()
        ttk.Combobox.return_value.bind.call_args.args[1]()
        next(
            call for call in ttk.Button.call_args_list if call.kwargs["text"] == "Send"
        ).kwargs["command"]()

    root.mainloop.side_effect = interact
    reply = support_review.show_review(
        {
            "mode": "edit",
            "request_id": "category-review",
            "temp_path": str(directory),
            "destination": f"{gh.REPOSITORY_URL}/discussions",
            "repository": gh.REPOSITORY,
            "account": "reporter",
            "warning": gh.PUBLIC_WARNING,
            "categories": dict(gh.CATEGORIES),
            "context": {
                "category": "bug-reports",
                "title": "Initial title",
                "description": "",
            },
            "files": info["files"],
        }
    )
    assert reply["category"] == "q-a"
    assert ttk.Combobox.call_args.kwargs == {
        "state": "readonly",
        "values": ["Bug Reports", "Q&A"],
    }
    assert any(
        "/categories/q-a" in call.kwargs.get("text", "")
        for call in ttk.Label.return_value.configure.call_args_list
    )


def test_native_bundle_requires_a_click_and_at_least_one_file(bundle, native):
    _, directory, info = bundle
    root, ttk, _, booleans = native
    request = {
        "mode": "bundle",
        "request_id": "review",
        "temp_path": str(directory),
        "destination": "reviewed destination",
        "files": info["files"],
        "send": True,
        "include_files": [],
    }
    assert support_review.show_review(request) is None  # Caller field cannot approve.
    booleans.clear()

    def interact():
        next(
            call
            for call in reversed(ttk.Button.call_args_list)
            if call.kwargs["text"] == "Send"
        ).kwargs["command"]()
        assert root.destroy.call_count == 0
        next(
            call
            for call in reversed(ttk.Button.call_args_list)
            if call.kwargs["text"] == "Cancel"
        ).kwargs["command"]()

    root.mainloop.side_effect = interact
    assert support_review.show_review(request) is None
    assert all(variable.get() is False for variable in booleans)


@pytest.mark.parametrize(
    "url, has_button",
    [
        (f"{gh.REPOSITORY_URL}/discussions/42", True),
        ("https://example.com/untrusted", False),
    ],
)
def test_result_modal_keeps_result_visible_and_only_links_fixed_support(
    native, url, has_button
):
    root, ttk, text, _ = native
    assert (
        support_review.show_review(
            {
                "mode": "result",
                "request_id": "result",
                "message": "Explicit result",
                "discussion_url": url,
            }
        )
        is None
    )
    text.return_value.insert.assert_called_with("1.0", "Explicit result")
    buttons = [call.kwargs["text"] for call in ttk.Button.call_args_list]
    assert ("Open Discussion" in buttons) is has_button
    assert "Close" in buttons
    assert all(
        call.args[0] != 300_000 for call in root.after.call_args_list
    )  # No result expiry.


def test_worker_start_failure_releases_single_flight_guard(monkeypatch):
    monkeypatch.setattr(tray_support, "_review_lock", threading.Lock())
    monkeypatch.setattr("ai_guardian.ui.display.get_preferred_ui", lambda: "tkinter")
    monkeypatch.delenv("AI_GUARDIAN_NO_TKINTER", raising=False)
    monkeypatch.setattr(
        tray_support.threading, "Thread", Mock(side_effect=RuntimeError("not started"))
    )
    notify = Mock()
    monkeypatch.setattr(tray_support, "show_notification", notify)
    assert tray_support.open_support_dialog() is False
    assert not tray_support._review_lock.locked()
    assert "Nothing was sent" in notify.call_args.args[1]


def test_bulk_selection_and_message_use_a_consistent_file_table(bundle, native):
    _, directory, info = bundle
    root, ttk, text, choices = native
    text.return_value.get.return_value = "Please help investigate this issue."

    def click(label):
        next(
            call for call in ttk.Button.call_args_list if call.kwargs["text"] == label
        ).kwargs["command"]()

    def interact():
        click("Deselect all")
        assert all(not item.get() for item in choices)
        click("Select all")
        assert all(item.get() for item in choices)
        click("Send")

    root.mainloop.side_effect = interact
    result = support_review.show_review(
        {
            "mode": "bundle",
            "request_id": "bulk",
            "temp_path": str(directory),
            "destination": "synthetic export",
            "files": info["files"],
        }
    )
    assert result["description"] == "Please help investigate this issue."
    assert result["include_files"] == ["keep.txt", "leave-out.txt"]
    sys.modules["tkinter"].Canvas.assert_called_once()
    ttk.Scrollbar.assert_called_once()
    assert any(
        call.kwargs.get("text") == "Your message"
        for call in ttk.LabelFrame.call_args_list
    )


def test_legacy_export_includes_sanitized_user_message(bundle, monkeypatch):
    bundle_id, root, info = bundle
    monkeypatch.setattr(
        gh,
        "public_text",
        lambda text: (text.replace("private fragment", "[REDACTED]"), 1),
    )

    def dialog(request):
        if request["mode"] == "bundle":
            return {
                "request_id": request["request_id"],
                "send": True,
                "include_files": ["keep.txt"],
                "description": "My message with private fragment",
            }
        return None

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = tray_support.run_support_flow(destination=info["destination"])
    outgoing = Path(result["destination"])
    assert (
        outgoing / "support-message.txt"
    ).read_text() == "My message with [REDACTED]"
    assert not (outgoing / "leave-out.txt").exists()
    assert (root / "leave-out.txt").exists()


@pytest.mark.parametrize(
    "choice,label", [("zip", "Create ZIP only"), ("discussion", "Gist + Discussion")]
)
def test_delivery_dropdown_requires_next_with_configured_credentials(
    native, choice, label
):
    root, ttk, _, _ = native
    selector = ttk.Combobox.return_value
    selector.set.side_effect = lambda value: setattr(
        selector.get, "return_value", value
    )

    def interact():
        selector.set.assert_called_once_with("Create ZIP only")
        assert ttk.Combobox.call_args.kwargs["state"] == "readonly"
        assert ttk.Combobox.call_args.kwargs["values"] == [
            "Create ZIP only",
            "Gist + Discussion",
        ]
        assert not any(
            call.kwargs.get("text", "").startswith("Final destination:")
            for call in ttk.Label.call_args_list
        )
        buttons = {
            call.kwargs["text"]: call.kwargs["command"]
            for call in ttk.Button.call_args_list
        }
        assert set(buttons) == {"Next", "Cancel"}
        selector.get.return_value = label
        assert selector.bind.call_args.args[0] == "<<ComboboxSelected>>"
        selector.bind.call_args.args[1]()
        root.destroy.assert_not_called()  # Selection alone never advances or sends.
        buttons["Next"]()

    root.mainloop.side_effect = interact
    result = support_review.show_review(
        {
            "mode": "delivery",
            "request_id": "delivery",
            "delivery": "discussion",
            "destination": gh.DESTINATION,
            "github_available": True,
        }
    )
    assert result == {"request_id": "delivery", "delivery": choice}


def test_next_opens_default_zip_review_without_changing_the_dropdown(native):
    root, ttk, _, _ = native
    selector = ttk.Combobox.return_value
    selector.set.side_effect = lambda value: setattr(
        selector.get, "return_value", value
    )

    def interact():
        assert selector.get() == "Create ZIP only"
        button = next(
            call.kwargs
            for call in ttk.Button.call_args_list
            if call.kwargs["text"] == "Next"
        )
        button["command"]()

    root.mainloop.side_effect = interact
    assert support_review.show_review(
        {"mode": "delivery", "request_id": "default-zip"}
    ) == {"request_id": "default-zip", "delivery": "zip"}


@pytest.mark.parametrize("github_available", [False, None])
def test_next_is_disabled_for_github_without_credentials_but_zip_stays_available(
    native,
    github_available,
):
    root, ttk, _, _ = native
    selector = ttk.Combobox.return_value
    selector.set.side_effect = lambda value: setattr(
        selector.get, "return_value", value
    )
    action = Mock()
    ttk.Button.side_effect = lambda *args, **kwargs: (
        action if kwargs.get("text") == "Next" else Mock()
    )

    def interact():
        buttons = {
            call.kwargs["text"]: call.kwargs for call in ttk.Button.call_args_list
        }
        action.configure.assert_called_with(state="normal")  # Local ZIP is the default.
        selector.get.return_value = "Gist + Discussion"
        selector.bind.call_args.args[1]()
        action.configure.assert_called_with(state="disabled")
        # Even a synthetic direct callback cannot select the unavailable workflow.
        buttons["Next"]["command"]()
        root.destroy.assert_not_called()
        assert any(
            "requires authenticated GitHub credentials" in call.kwargs.get("text", "")
            for call in ttk.Label.call_args_list
        )
        selector.get.return_value = "Create ZIP only"
        selector.bind.call_args.args[1]()
        action.configure.assert_called_with(state="normal")
        buttons["Next"]["command"]()

    root.mainloop.side_effect = interact
    assert support_review.show_review(
        {
            "mode": "delivery",
            "request_id": "no-credentials",
            "github_available": github_available,
        }
    ) == {"request_id": "no-credentials", "delivery": "zip"}


@pytest.mark.parametrize(
    "selection", ["", "Unsupported destination", "Gist + Discussion…"]
)
def test_unknown_destination_cannot_advance_even_with_a_direct_next_callback(
    native, selection
):
    root, ttk, _, _ = native
    selector = ttk.Combobox.return_value
    action = Mock()
    ttk.Button.side_effect = lambda *args, **kwargs: (
        action if kwargs.get("text") == "Next" else Mock()
    )

    def interact():
        selector.get.return_value = selection
        selector.bind.call_args.args[1]()
        action.configure.assert_called_with(state="disabled")
        button = next(
            call.kwargs
            for call in ttk.Button.call_args_list
            if call.kwargs["text"] == "Next"
        )
        button["command"]()
        root.destroy.assert_not_called()

    root.mainloop.side_effect = interact
    assert (
        support_review.show_review(
            {
                "mode": "delivery",
                "request_id": "invalid-selection",
                "github_available": True,
            }
        )
        is None
    )


def test_cancelling_destination_selection_never_returns_a_delivery(native):
    root, ttk, _, _ = native
    selector = ttk.Combobox.return_value
    selector.set.side_effect = lambda value: setattr(
        selector.get, "return_value", value
    )

    def interact():
        selector.get.return_value = "Gist + Discussion"
        selector.bind.call_args.args[1]()
        root.destroy.assert_not_called()
        button = next(
            call.kwargs
            for call in ttk.Button.call_args_list
            if call.kwargs["text"] == "Cancel"
        )
        button["command"]()

    root.mainloop.side_effect = interact
    assert (
        support_review.show_review(
            {
                "mode": "delivery",
                "request_id": "cancel-selection",
                "github_available": True,
                "delivery": "discussion",
            }
        )
        is None
    )


def test_destination_dropdown_is_driven_by_the_destination_list(native, monkeypatch):
    _, ttk, _, _ = native
    monkeypatch.setattr(
        support_review,
        "DELIVERY_DESTINATIONS",
        {
            "Create ZIP only": "zip",
            "Gist + Discussion": "discussion",
            "Future destination": "future",
        },
    )
    support_review.show_review(
        {"mode": "delivery", "request_id": "destination-list", "github_available": True}
    )
    assert ttk.Combobox.call_args.kwargs["values"] == [
        "Create ZIP only",
        "Gist + Discussion",
        "Future destination",
    ]
    assert [call.kwargs["text"] for call in ttk.Button.call_args_list] == [
        "Next",
        "Cancel",
    ]


@pytest.mark.parametrize(
    "mode,label", [("upload", "Create Gist"), ("approve", "Publish publicly")]
)
def test_both_upload_and_discussion_require_fresh_unchecked_consent(
    native, mode, label
):
    root, ttk, _, choices = native
    action = Mock()
    ttk.Button.side_effect = lambda *args, **kwargs: (
        action if kwargs.get("text") == label else Mock()
    )

    def interact():
        button = next(
            call.kwargs
            for call in ttk.Button.call_args_list
            if call.kwargs["text"] == label
        )
        assert button["state"] == "disabled"
        assert choices[-1].get() is False
        button["command"]()
        root.destroy.assert_not_called()
        choices[-1].set(True)
        ttk.Checkbutton.call_args.kwargs["command"]()
        action.configure.assert_called_with(state="normal")
        button["command"]()

    root.mainloop.side_effect = interact
    assert support_review.show_review(
        {
            "mode": mode,
            "request_id": "explicit-consent",
            "account": "reporter",
            "warning": "Reviewed warning",
            "category": "Reviewed category",
            "title": "Reviewed title",
            "body": "Exact content",
            "files": [],
            "context_redactions": 0,
            "approved": True,
        }
    ) == {"request_id": "explicit-consent", "approved": True}


@pytest.mark.parametrize(
    "url,allowed",
    [
        ("https://gist.github.com/reporter/" + "a" * 32, True),
        ("https://example.com/reporter/" + "a" * 32, False),
        ("https://gist.github.com/reporter/../../settings", False),
    ],
)
def test_result_opens_only_a_valid_gist_url_on_explicit_click(
    native, monkeypatch, url, allowed
):
    _, ttk, _, _ = native
    browser = Mock()
    monkeypatch.setattr("webbrowser.open", browser)
    support_review.show_review(
        {
            "mode": "result",
            "request_id": "gist-result",
            "message": "The diagnostic Gist is already uploaded",
            "gist_url": url,
        }
    )
    browser.assert_not_called()
    buttons = [
        call.kwargs
        for call in ttk.Button.call_args_list
        if call.kwargs["text"] == "Open Gist"
    ]
    assert bool(buttons) is allowed
    if allowed:
        buttons[0]["command"]()
        browser.assert_called_once_with(url)


def test_partial_gist_result_fallback_notification_keeps_management_link(
    bundle, monkeypatch
):
    _, _, info = bundle
    url = "https://gist.github.com/reporter/" + "a" * 32
    monkeypatch.setattr(
        gh,
        "review_dialog",
        Mock(side_effect=gh.GitHubError("Native result unavailable.")),
    )
    notify = Mock()
    monkeypatch.setattr(tray_support, "show_notification", notify)
    tray_support._show_result(
        {
            "status": "error",
            "delivery_status": "gist_only",
            "gist_url": url,
            "message": "Discussion cancelled; Gist already uploaded.",
        },
        info,
    )
    assert url in notify.call_args.args[1]
    assert "manage or delete" in notify.call_args.args[1]
    assert "Nothing was sent" not in notify.call_args.args[1]


def test_unexpected_tray_failure_after_gist_upload_recovers_known_url(
    bundle, monkeypatch
):
    from ai_guardian.reporting import github_gist as gist

    bundle_id, _, info = bundle
    info["destination"] = gh.DESTINATION
    url = "https://gist.github.com/reporter/" + "a" * 32
    monkeypatch.setattr(gist, "recovery_url", lambda bundle: url)
    monkeypatch.setattr(
        bundles,
        "send_bundle",
        Mock(side_effect=RuntimeError("private diagnostic detail")),
    )
    dialog = Mock()
    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = tray_support.run_support_flow()
    assert result["delivery_status"] == "uncertain" and result["gist_url"] == url
    assert "private diagnostic detail" not in result["message"]
    assert "already uploaded" in result["message"]
    assert dialog.call_args.args[0]["gist_url"] == url


def test_file_viewer_can_reach_the_end_and_go_back_without_truncating(
    bundle, native, monkeypatch
):
    _, directory, info = bundle
    root, ttk, text, _ = native
    source = "BEGIN\n" + "日本語🙂\n" * 30 + "END\n"
    (directory / "keep.txt").write_text(source, encoding="utf-8")
    monkeypatch.setattr(support_review, "MAX_PREVIEW_BYTES", 53)
    support_review._show_file_preview(
        root, {"temp_path": str(directory), "files": info["files"]}, "keep.txt"
    )
    buttons = {
        call.kwargs["text"]: call.kwargs["command"]
        for call in ttk.Button.call_args_list
    }
    for _ in range(30):
        buttons["Next page"]()
    assert "END\n" in text.return_value.insert.call_args.args[1]
    buttons["Previous page"]()
    assert "END\n" not in text.return_value.insert.call_args.args[1]
    assert (directory / "keep.txt").read_text(encoding="utf-8") == source


def test_retained_export_cannot_silently_include_newly_unchecked_files(bundle):
    bundle_id, root, info = bundle
    bundles._set_file_selection(bundle_id, info, ["keep.txt", "leave-out.txt"])
    exported = Path(bundles.send_bundle(bundle_id)["destination"])
    bundles._set_file_selection(bundle_id, info, ["keep.txt"])

    result = bundles.send_bundle(bundle_id)

    # Refuse an in-place overwrite rather than claiming the selected subset was
    # exported while leaving an unchecked file in the same outgoing directory.
    assert result["status"] == "error"
    assert "Existing files were not overwritten" in result["message"]
    assert (exported / "leave-out.txt").exists()
    assert (root / "leave-out.txt").exists()


def test_upload_error_refers_to_retained_review_not_deleted_staging(
    bundle, monkeypatch
):
    bundle_id, root, info = bundle
    info["destination"] = "s3://support-bucket"
    bundles._set_file_selection(bundle_id, info, ["keep.txt"])
    staged = []

    def fail(bid, outgoing, destination):
        staged.append(outgoing)
        return {
            "status": "error",
            "message": f"Upload failed. Bundle files at: {outgoing}",
        }

    monkeypatch.setattr(bundles, "_send_to_s3", fail)
    result = bundles.send_bundle(bundle_id)
    assert str(root) in result["message"]
    assert str(staged[0]) not in result["message"]
    assert result["temp_path"] == str(root)
    assert not staged[0].exists()


def test_email_handoff_is_manual_not_a_sent_notification(bundle, monkeypatch):
    bundle_id, _, info = bundle
    info["destination"] = "mailto:help@example.com"
    bundles._set_file_selection(bundle_id, info, ["keep.txt"])
    monkeypatch.setattr(bundles.webbrowser, "open", Mock())
    result = bundles.send_bundle(bundle_id)
    try:
        assert result["delivery_status"] == "manual_required"
        text = bundles._format_send_human(result)
        assert "Manual email delivery required" in text
        assert "✓ Sent:" not in text
        with zipfile.ZipFile(result["zip_path"]) as archive:
            assert archive.namelist() == ["keep.txt"]
        monkeypatch.setattr(
            gh,
            "review_dialog",
            Mock(side_effect=gh.GitHubError("Unavailable", code="review_unavailable")),
        )
        notify = Mock()
        monkeypatch.setattr(tray_support, "show_notification", notify)
        tray_support._show_result(result, info)
        assert "Attach" in notify.call_args.args[1]
        assert "completed" not in notify.call_args.args[1]
    finally:
        Path(result["zip_path"]).unlink(missing_ok=True)


def test_result_button_bar_is_reserved_before_expanding_content(native):
    _, ttk, _, _ = native
    support_review.show_review(
        {"mode": "result", "request_id": "result", "message": "Ready"}
    )
    assert any(
        call.kwargs.get("side") == "bottom"
        for call in ttk.Frame.return_value.pack.call_args_list
    )


@pytest.mark.parametrize(
    "reply",
    [
        {"request_id": "forged", "send": True, "include_files": ["keep.txt"]},
        {"send": False},
    ],
)
def test_unverified_native_response_never_sends(bundle, monkeypatch, reply):
    sender = Mock()
    monkeypatch.setattr(bundles, "send_bundle", sender)
    monkeypatch.setattr(
        gh,
        "review_dialog",
        lambda request: reply if request["mode"] == "bundle" else None,
    )
    assert tray_support.run_support_flow()["error_code"] == "support"
    sender.assert_not_called()


def test_public_binary_file_can_be_excluded_before_size_validation(
    bundle, monkeypatch, support_github_transport
):
    bundle_id, root, info = bundle
    info["destination"] = gh.DESTINATION
    (root / "leave-out.txt").write_bytes(b"\xffbinary")
    client = Mock()
    client.discover.return_value = {
        "account_id": "U_test",
        "login": "reporter",
        "repository_id": "R_support",
        "categories": {"bug-reports": "D_bug", "q-a": "D_qa"},
    }
    client.scrub.side_effect = lambda text: text
    client.create.return_value = f"{gh.REPOSITORY_URL}/discussions/123"
    support_github_transport(client)
    monkeypatch.setattr(gh, "GitHubClient", lambda: client)

    def dialog(request):
        if request["mode"] == "delivery":
            return {"request_id": request["request_id"], "delivery": "discussion"}
        if request["mode"] == "edit":
            return {
                "request_id": request["request_id"],
                **request["context"],
                "title": "A usage question",
                "description": "Steps to reproduce the issue.",
                "include_files": ["keep.txt"],
            }
        assert "leave-out.txt" not in request["body"]
        return {"request_id": request["request_id"], "approved": True}

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = bundles.send_bundle(bundle_id)
    assert result["status"] == "sent"
    assert "included diagnostic" not in client.create.call_args.args[3]
    assert "https://gist.github.com/reporter/" in client.create.call_args.args[3]
    assert "leave-out.txt" not in client.create.call_args.args[3]
    assert (root / "leave-out.txt").read_bytes() == b"\xffbinary"


@pytest.mark.parametrize(
    "mode,zip_export", [("bundle", True), ("bundle", False), ("edit", False)]
)
@pytest.mark.parametrize("initial_selection", [None, []])
def test_native_review_without_doctor_requires_a_selection_and_message(
    bundle, native, mode, zip_export, initial_selection
):
    _, directory, info = bundle
    root, ttk, text, choices = native
    text.return_value.get.return_value = "Steps to reproduce the issue."
    action = Mock()
    label = "Create ZIP" if zip_export else "Send"
    ttk.Button.side_effect = lambda *args, **kwargs: (
        action if kwargs.get("text") == label else Mock()
    )
    request = {
        "mode": mode,
        "request_id": "opt-in-files",
        "temp_path": str(directory),
        "files": info["files"],
        "zip_export": zip_export,
        "include_files": initial_selection,
        "account": "synthetic",
        "warning": gh.PUBLIC_WARNING,
        "categories": dict(gh.CATEGORIES),
        "context": {
            "title": "A question",
            "description": "",
            "category": "bug-reports",
        },
    }
    ttk.Combobox.return_value.get.return_value = "Bug Reports"
    ttk.Entry.return_value.get.return_value = "A question"

    def click(text):
        next(
            call for call in ttk.Button.call_args_list if call.kwargs["text"] == text
        ).kwargs["command"]()

    def interact():
        assert choices and all(not variable.get() for variable in choices)
        constructor = next(
            call for call in ttk.Button.call_args_list if call.kwargs["text"] == label
        )
        assert constructor.kwargs["state"] == "disabled"
        # Even invoking the disabled callback cannot bypass the empty-file guard.
        click(label)
        assert root.destroy.call_count == 0
        assert any(
            call.kwargs.get("text") == "Select at least one file to include."
            for call in ttk.Label.return_value.configure.call_args_list
        )
        choices[0].set(True)
        ttk.Checkbutton.call_args_list[0].kwargs["command"]()
        action.configure.assert_called_with(state="normal")
        click("Deselect all")
        action.configure.assert_called_with(state="disabled")
        click("Select all")
        action.configure.assert_called_with(state="normal")
        click(label)

    root.mainloop.side_effect = interact
    result = support_review.show_review(request)
    assert result["include_files"] == ["keep.txt", "leave-out.txt"]


def test_native_review_restores_only_previously_explicit_file_choices(bundle, native):
    _, directory, info = bundle
    _, _, _, choices = native
    support_review.show_review(
        {
            "mode": "bundle",
            "request_id": "saved-selection",
            "temp_path": str(directory),
            "files": info["files"],
            "include_files": ["leave-out.txt"],
        }
    )
    assert [variable.get() for variable in choices] == [False, True]


@pytest.mark.parametrize(
    "mode", ["delivery", "bundle", "edit", "upload", "approve", "result"]
)
def test_native_support_window_is_restored_raised_and_focused(native, mode):
    root, _, _, _ = native
    root.winfo_exists.return_value = True
    support_review.show_review(
        {
            "mode": mode,
            "request_id": "foreground",
            "temp_path": "synthetic",
            "files": [],
            "account": "synthetic",
            "warning": gh.PUBLIC_WARNING,
            "categories": dict(gh.CATEGORIES),
            "context": {
                "title": "Synthetic",
                "description": "",
                "category": "bug-reports",
            },
            "category": "Bug Reports",
            "title": "Synthetic",
            "body": "Synthetic text",
            "context_redactions": 0,
            "message": "Synthetic result",
        }
    )
    root.withdraw.assert_called_once()
    root.update_idletasks.assert_called_once()
    root.deiconify.assert_called_once()
    root.lift.assert_called()
    root.attributes.assert_any_call("-topmost", True)
    root.after_idle.call_args.args[0]()  # Focus after mapping, not before layout.
    root.focus_force.assert_called_once()
    release = next(
        call.args[1] for call in root.after.call_args_list if call.args[0] == 200
    )
    release()
    root.attributes.assert_called_with("-topmost", False)
    calls = [call[0] for call in root.method_calls]
    assert (
        calls.index("withdraw")
        < calls.index("update_idletasks")
        < calls.index("deiconify")
        < calls.index("mainloop")
    )


def test_foreground_hint_rejection_does_not_cancel_native_review(native):
    root, _, _, _ = native
    error = sys.modules["tkinter"].TclError
    root.attributes.side_effect = error("unsupported window hint")
    assert (
        support_review.show_review({"mode": "delivery", "request_id": "hint"}) is None
    )
    root.deiconify.assert_called_once()
    root.after_idle.call_args.args[0]()
    root.focus_force.assert_called_once()
    root.mainloop.assert_called_once()


@pytest.mark.parametrize("delivery_status", ["zip_only", "manual_required"])
def test_zip_result_passes_archive_path_to_native_completion(
    bundle, monkeypatch, delivery_status
):
    _, _, info = bundle
    dialog = Mock()
    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = {
        "status": "sent",
        "delivery_status": delivery_status,
        "message": "ZIP prepared locally; nothing sent.",
        "zip_path": str(Path(info["temp_path"]).parent / "report.zip"),
    }
    tray_support._show_result(result, info)
    assert dialog.call_args.args[0]["zip_path"] == result["zip_path"]


def test_failed_result_does_not_offer_a_zip_folder(bundle, monkeypatch):
    _, _, info = bundle
    dialog = Mock()
    monkeypatch.setattr(gh, "review_dialog", dialog)
    tray_support._show_result(
        {"status": "error", "message": "ZIP failed.", "zip_path": "uncreated.zip"}, info
    )
    assert not dialog.call_args.args[0].get("zip_path")


def test_native_zip_result_opens_destination_only_after_click(
    native, tmp_path, monkeypatch
):
    root, ttk, _, _ = native
    archive = tmp_path / "report.zip"
    archive.write_bytes(b"synthetic archive")
    opener = Mock()
    monkeypatch.setattr(
        support_review, "_open_destination_directory", opener, raising=False
    )

    def interact():
        opener.assert_not_called()
        button = next(
            call
            for call in ttk.Button.call_args_list
            if call.kwargs["text"] == "Open destination folder"
        )
        button.kwargs["command"]()
        root.destroy.assert_not_called()

    root.mainloop.side_effect = interact
    assert (
        support_review.show_review(
            {
                "mode": "result",
                "request_id": "zip-folder",
                "message": "ZIP created locally.",
                "zip_path": str(archive),
            }
        )
        is None
    )
    opener.assert_called_once_with(str(archive))
    assert archive.read_bytes() == b"synthetic archive"


def test_file_browser_failure_keeps_zip_and_result_visible(
    native, tmp_path, monkeypatch, caplog
):
    root, ttk, _, _ = native
    archive = tmp_path / "report.zip"
    archive.write_bytes(b"synthetic archive")
    opener = Mock(side_effect=OSError("private synthetic launcher detail"))
    monkeypatch.setattr(
        support_review, "_open_destination_directory", opener, raising=False
    )

    def interact():
        next(
            call
            for call in ttk.Button.call_args_list
            if call.kwargs["text"] == "Open destination folder"
        ).kwargs["command"]()
        root.destroy.assert_not_called()

    root.mainloop.side_effect = interact
    support_review.show_review(
        {
            "mode": "result",
            "request_id": "folder-failure",
            "message": "ZIP created locally.",
            "zip_path": str(archive),
        }
    )
    assert any(
        call.kwargs.get("text")
        == "Could not open the destination folder. Use the ZIP path above to open it manually."
        for call in ttk.Label.return_value.configure.call_args_list
    )
    assert "private synthetic launcher detail" not in caplog.text
    assert archive.exists()


@pytest.mark.parametrize(
    "platform,command", [("linux", "xdg-open"), ("darwin", "open"), ("win32", None)]
)
def test_archive_folder_uses_native_file_browser_without_shell(
    tmp_path, monkeypatch, platform, command
):
    folder = tmp_path / "report folder;not-a-command"
    folder.mkdir()
    archive = folder / "report.zip"
    archive.write_bytes(b"synthetic archive")
    launch = Mock()
    windows_open = Mock()
    monkeypatch.setattr(support_review, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(support_review, "os", SimpleNamespace(startfile=windows_open))
    monkeypatch.setattr(
        support_review,
        "subprocess",
        SimpleNamespace(Popen=launch, DEVNULL=-3),
        raising=False,
    )
    support_review._open_destination_directory(str(archive))
    if platform == "win32":
        windows_open.assert_called_once_with(str(folder))
        launch.assert_not_called()
    else:
        launch.assert_called_once_with(
            [command, str(folder)], stdin=-3, stdout=-3, stderr=-3, shell=False
        )
        windows_open.assert_not_called()


@pytest.mark.parametrize("kind", ["missing", "relative", "url", "directory", "not_zip"])
def test_archive_folder_rejects_unavailable_or_nonarchive_targets(
    tmp_path, monkeypatch, kind
):
    target = tmp_path / "report.zip"
    if kind == "relative":
        target = Path("relative-report.zip")
    elif kind == "url":
        target = Path("https://example.com/report.zip")
    elif kind == "directory":
        target.mkdir()
    elif kind == "not_zip":
        target = tmp_path / "report.txt"
        target.write_text("not an archive")
    launch = Mock()
    monkeypatch.setattr(
        support_review,
        "subprocess",
        SimpleNamespace(Popen=launch, DEVNULL=-3),
        raising=False,
    )
    with pytest.raises((OSError, ValueError)):
        support_review._open_destination_directory(str(target))
    launch.assert_not_called()


def test_file_view_has_wrap_toggle_and_horizontal_scrollbar(
    bundle, native, monkeypatch
):
    _, directory, info = bundle
    root, ttk, text, variables = native
    monkeypatch.setattr(support_review, "MAX_PREVIEW_BYTES", 8)
    support_review._show_file_preview(
        root, {"temp_path": str(directory), "files": info["files"]}, "keep.txt"
    )
    toggle = next(
        call
        for call in ttk.Checkbutton.call_args_list
        if call.kwargs["text"] == "Wrap lines"
    )
    wrapping = toggle.kwargs["variable"]
    assert wrapping.get() is False
    assert text.call_args.kwargs["wrap"] == "none"
    assert ttk.Scrollbar.call_args.kwargs["orient"] == "horizontal"
    text.return_value.configure.assert_any_call(
        xscrollcommand=ttk.Scrollbar.return_value.set
    )
    ttk.Scrollbar.call_args.kwargs["command"]("moveto", "0.5")
    text.return_value.xview.assert_called_once_with("moveto", "0.5")

    wrapping.set(True)
    toggle.kwargs["command"]()
    text.return_value.configure.assert_called_with(wrap="word")
    ttk.Scrollbar.return_value.grid_remove.assert_called_once()
    before = text.return_value.insert.call_count
    next(
        call for call in ttk.Button.call_args_list if call.kwargs["text"] == "Next page"
    ).kwargs["command"]()
    assert text.return_value.insert.call_count == before + 1
    assert wrapping.get() is True and variables == [wrapping]
    text.return_value.configure.assert_called_with(state="disabled")

    wrapping.set(False)
    toggle.kwargs["command"]()
    text.return_value.configure.assert_called_with(wrap="none")
    ttk.Scrollbar.return_value.grid.assert_called_with()


def test_public_consent_is_visible_and_explains_disabled_publish(native):
    root, ttk, text, variables = native
    events = []

    def make_frame(*args, **kwargs):
        frame = Mock()
        frame.pack.side_effect = lambda **options: events.append((frame, options))
        return frame

    ttk.Frame.side_effect = make_frame
    text.return_value.pack.side_effect = lambda **options: events.append(
        ("body", options)
    )
    support_review.show_review(
        {
            "mode": "approve",
            "request_id": "visible-consent",
            "account": "synthetic",
            "warning": gh.PUBLIC_WARNING,
            "category": "Bug Reports",
            "title": "Synthetic",
            "body": "Synthetic public report",
            "files": [],
            "context_redactions": 0,
        }
    )
    consent = ttk.Checkbutton.call_args
    assert (
        consent.kwargs["text"]
        == "I reviewed the exact publication and approve making it public."
    )
    consent_frame = consent.args[0]
    placement = next(options for frame, options in events if frame == consent_frame)
    assert placement["side"] == "bottom" and placement["fill"] == "x"
    assert next(
        i for i, (frame, _) in enumerate(events) if frame == consent_frame
    ) < next(i for i, (frame, _) in enumerate(events) if frame == "body")
    assert any(
        call.kwargs.get("text")
        == "Check the consent box below to enable Publish publicly."
        for call in ttk.Label.call_args_list
    )
    assert variables[0].get() is False
    publish = next(
        call
        for call in ttk.Button.call_args_list
        if call.kwargs["text"] == "Publish publicly"
    )
    assert publish.kwargs["state"] == "disabled"
    publish.kwargs["command"]()
    root.destroy.assert_not_called()
