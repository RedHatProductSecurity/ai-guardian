"""Public support UX contracts. Never read personal config or publish live data.

Manual desktop verification:
0. Choose Contact supports immediately above About, including with no running daemon.
   It opens a native modal, never a shell; it must not auto-submit.
   When GitHub is the configured/default destination, the first screen has a
   read-only Destination dropdown: Create ZIP only (default), Gist + Discussion.
   Changing it does not advance. Click Next for the selected review page, or Cancel.
   Without GitHub credentials, selecting Gist + Discussion disables Next, with an
   explanation. Switching back to ZIP enables Next without GitHub authentication.
1. Verify the dialog opens normally in the foreground, not minimized. doctor.json
   comes first and is checked for new lists; remaining files are alphabetical and
   unchecked. Saved selections, including an unchecked Doctor, are preserved.
   The Discussion title starts blank. Title and Your message are required; whitespace
   does not count. Create ZIP / Send stays disabled until all required fields and
   at least one file are provided; clearing a field disables it again.
   Use Select all / Deselect all and
   check the selected count;
   View each protected file and leave unwanted files unchecked.
   Toggle Wrap lines: wrapped text has no horizontal bar; unwrapped text has a
   horizontal scrollbar. Wrapping survives page changes and never edits the copy.
   Only the log can say Truncated; it contains only the last 12 hours, keeping
   the newest data.
   Violations include every complete sanitized record from the last 12 hours.
   Configuration/structured files stay complete. View pages reach the final fields;
   sending never applies an additional size crop.
2. Select Bug Reports or Q&A. Send: check the real GitHub account and exact
   sanitized Gist description/filenames/contents. Create Gist starts disabled;
   only its separate unchecked consent box and click authorize upload.
3. Cancel before upload: no Gist/Discussion exists and the bundle is still local.
   Approve upload: files go into an unlisted Gist owned by that account. The next
   dialog shows the actual Gist link in the exact Discussion, not inline files.
   The original sanitized user message remains in its own section.
4. Inspect that actual link and exact Discussion. Unlisted is not private.
   Publish publicly starts disabled; the hint explains that explicit consent is
   required. The consent checkbox stays visible above the action buttons,
   even in a smaller window. Check it to enable publication. Publishing should
   return Discussion and Gist URLs. Cancel here: no Discussion is created, but
   the Gist remains uploaded; Open Gist lets you manage/delete it. Deletion cannot
   retract copies/forks. Retry reuses the same verified Gist without re-upload.
5. Re-send that bundle: it must return the same URL without another Discussion.
6. With a saved local/S3/GCS/email destination, Contact supports honors that
   destination, without a GitHub selector or modifying that saved setting.
   For ZIP only, review/edit the message and select files, then Create ZIP.
   The result shows a retained local archive, no upload, no Discussion/email,
    and warns that the ZIP is not encrypted. Choosing ZIP never uploads a Gist.
   Click Open destination folder: the native file browser opens the archive's
   containing directory, without opening/extracting the ZIP or sending anything.
   The result remains visible; Close dismisses it. A browser-launch failure must
   leave the archive intact and explain how to find the directory manually.
7. Using the standalone CLI with an explicit local destination, export a reviewed
   bundle. It must say no support submission was made.
   Run `ai-guardian support send` in another terminal: it must find the retained
   reviewed copy, not report "No pending bundle" or restore deleted files.
Headless, authentication/category failures, changed files, and uncertain results
must never silently publish or switch destinations.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_guardian.reporting import github_support as gh
from ai_guardian.reporting import support_bundle as bundles


@pytest.fixture
def support(monkeypatch, tmp_path, support_github_transport):
    monkeypatch.setattr(
        bundles, "_get_support_config", lambda: {"export_destination": gh.DESTINATION}
    )
    root = tmp_path / "review"
    root.mkdir()
    (root / gh.CONTEXT_FILE).write_text(
        json.dumps(
            {
                "title": "Unexpected behavior",
                "description": "Test context",
                "category": "bug-reports",
            }
        )
    )
    (root / "diagnostics.txt").write_text("safe diagnostic text")
    bundle = {
        "destination": gh.DESTINATION,
        "temp_path": str(root),
        "created": datetime.now(timezone.utc).isoformat(),
        "ttl_minutes": 30,
        "files": [
            {"name": p.name, "redactions": 2 if p.suffix == ".txt" else 0}
            for p in root.iterdir()
        ],
    }
    client = Mock()
    client.discover.return_value = {
        "account_id": "U_verified",
        "login": "verified-user",
        "repository_id": "R_support",
        "categories": {"bug-reports": "D_bug", "q-a": "D_help"},
    }
    client.scrub.side_effect = lambda text: text
    client.create.return_value = f"{gh.REPOSITORY_URL}/discussions/42"
    support_github_transport(client)
    monkeypatch.setattr(gh, "GitHubClient", lambda: client)
    return root, bundle, client


@pytest.mark.parametrize("category", ["bug-reports", "q-a"])
def test_user_sees_restricted_category_account_and_exact_publication(
    support, monkeypatch, category
):
    """USER EXPERIENCE: Select Bug Reports or Q&A, then see exact public consent."""
    root, bundle, client = support

    def dialog(request):
        assert request["account"] == "verified-user"
        assert request["repository"] == "RedHatProductSecurity/ai-guardian"
        assert request["categories"] == {"bug-reports": "Bug Reports", "q-a": "Q&A"}
        if request["mode"] == "upload":
            assert (
                request["destination"]
                == "https://gist.github.com/verified-user (unlisted Gist)"
            )
            assert "Unlisted is not private" in request["warning"]
            assert "safe diagnostic text" in request["body"]
            return {"request_id": request["request_id"], "approved": True}
        assert request["destination"] == f"{gh.REPOSITORY_URL}/discussions"
        assert request["warning"] == (
            "This repository is public. Sanitization is not a guarantee of confidentiality. "
            "Publishing exposes your message and the diagnostic Gist link; unlisted is not private. "
            "Review the exact title, body, and selected diagnostic files before proceeding."
        )
        if request["mode"] == "edit":
            assert request["context"]["category"] == "bug-reports"
            assert request["include_files"] == []
            return {
                "request_id": request["request_id"],
                **request["context"],
                "category": category,
                "include_files": ["diagnostics.txt"],
            }
        assert request["title"] == "Unexpected behavior"
        assert request["category"] == gh.CATEGORIES[category]
        assert "safe diagnostic text" not in request["body"]
        assert "https://gist.github.com/verified-user/" in request["body"]
        assert (
            next(f for f in request["files"] if f["name"] == "diagnostics.txt")[
                "redactions"
            ]
            == 2
        )
        return {"request_id": request["request_id"], "approved": True}

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = gh.send_discussion("support-ux", bundle)
    assert bundles._format_send_human(result) == (
        f"✓ Sent: Discussion created: {gh.REPOSITORY_URL}/discussions/42\n"
        f"You own the diagnostic Gist and can manage or delete it: {result['gist_url']}"
    )
    assert result["discussion_url"] == client.create.return_value
    assert root.exists()


def test_unchecked_diagnostics_are_absent_from_public_preview_and_publication(
    support, monkeypatch
):
    """USER EXPERIENCE: Uncheck a file → no content/name sent, prepared copy unchanged."""
    root, bundle, client = support
    (root / "omit.txt").write_text("Do not share this diagnostic")
    bundle["files"].append({"name": "omit.txt", "redactions": 0})

    def dialog(request):
        if request["mode"] == "edit":
            assert {item["name"] for item in request["files"]} == {
                "diagnostics.txt",
                "omit.txt",
            }
            return {
                "request_id": request["request_id"],
                **request["context"],
                "include_files": ["diagnostics.txt"],
            }
        assert ("safe diagnostic text" in request["body"]) is (
            request["mode"] == "upload"
        )
        assert "Do not share" not in request["body"]
        assert "omit.txt" not in request["body"]
        assert [item["name"] for item in request["files"]] == ["diagnostics.txt"]
        return {"request_id": request["request_id"], "approved": True}

    monkeypatch.setattr(gh, "review_dialog", dialog)
    assert gh.send_discussion("support-exclusion-ux", bundle)["status"] == "sent"
    assert "Do not share" not in client.create.call_args.args[3]
    assert (root / "omit.txt").read_text() == "Do not share this diagnostic"


@pytest.mark.parametrize("delivery", ["zip", "discussion"])
def test_no_files_selected_cannot_create_zip_or_publish(support, monkeypatch, delivery):
    """USER EXPERIENCE: New lists are opt-in; a message alone cannot enable Send.

    The native action stays disabled until at least one file is checked. Even an
    invalid empty-selection reply cannot create an archive or open final consent.
    All prepared copies remain intact and no support submission is claimed.
    """
    root, bundle, client = support
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    monkeypatch.setattr(bundles, "_active_bundles", {"support-opt-in-ux": bundle})
    stages = []

    def dialog(request):
        stages.append(request["mode"])
        if request["mode"] == "delivery":
            return {"request_id": request["request_id"], "delivery": delivery}
        assert request["mode"] == ("bundle" if delivery == "zip" else "edit")
        assert request["include_files"] == []
        return {
            "request_id": request["request_id"],
            **request.get("context", {}),
            "send": True,
            "description": "A message is not a diagnostic file selection.",
            "include_files": [],
        }

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = bundles.send_bundle("support-opt-in-ux")
    assert result["status"] == "error"
    assert result["delivery_status"] == (
        "not_sent" if delivery == "zip" else "not_published"
    )
    if delivery == "discussion":
        assert (
            result["message"] == "Select at least one diagnostic file before sending."
        )
    else:
        client.discover.assert_not_called()
    assert stages == ["delivery", "bundle" if delivery == "zip" else "edit"]
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    assert "zip_path" not in result and "discussion_url" not in result
    client.create.assert_not_called()


def test_manual_email_export_does_not_claim_a_support_submission(support, monkeypatch):
    """USER EXPERIENCE: No SMTP → attach the selected ZIP yourself, never a sent claim."""
    from ai_guardian.tray import support as tray_support

    _, bundle, client = support
    bundle["destination"] = "mailto:help@example.com"
    monkeypatch.setattr(bundles, "_active_bundles", {"support-manual-ux": bundle})
    monkeypatch.setattr(
        bundles, "prepare_bundle", lambda **kwargs: {"bundle_id": "support-manual-ux"}
    )
    monkeypatch.setattr(bundles, "_get_support_config", lambda: {"email": {}})
    monkeypatch.setattr(bundles.webbrowser, "open", Mock())

    def dialog(request):
        if request["mode"] == "bundle":
            assert request["destination"] == "mailto:help@example.com"
            assert request["local_only"] is False
            assert "categories" not in request
            return {
                "request_id": request["request_id"],
                "send": True,
                "include_files": ["diagnostics.txt"],
                "description": "Please investigate this issue.",
            }
        assert request["mode"] == "result"
        assert request["message"].startswith("Manual email delivery required:")
        assert "AI Guardian has not sent an email." in request["message"]
        assert "✓ Sent:" not in request["message"]
        return None

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = tray_support.run_support_flow(destination=bundle["destination"])
    try:
        assert result["delivery_status"] == "manual_required"
        assert Path(result["zip_path"]).is_file()
        client.create.assert_not_called()
    finally:
        Path(result["zip_path"]).unlink(missing_ok=True)


@pytest.mark.parametrize("delivery", ["zip", "discussion"])
def test_no_github_credentials_leaves_zip_available_but_public_workflow_unavailable(
    support, monkeypatch, delivery
):
    """USER EXPERIENCE: No credentials → Next disabled for public selection; ZIP works.

    There is no automatic login, scope upgrade or network request. A forged
    response for the unavailable public selection is also rejected by the backend.
    """
    _, bundle, client = support
    monkeypatch.setattr(gh, "credentials_available", lambda: False)
    monkeypatch.setattr(bundles, "_active_bundles", {"support-no-auth-ux": bundle})

    def dialog(request):
        if request["mode"] == "delivery":
            assert request["github_available"] is False
            return {"request_id": request["request_id"], "delivery": delivery}
        assert delivery == "zip" and request["mode"] == "bundle"
        return {
            "request_id": request["request_id"],
            "send": True,
            "include_files": ["diagnostics.txt"],
            "description": "Please investigate this issue.",
        }

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = bundles.send_bundle("support-no-auth-ux")
    if delivery == "zip":
        assert result["delivery_status"] == "zip_only"
        assert Path(result["zip_path"]).is_file()
    else:
        assert result["error_code"] == "authentication"
        assert result["message"] == (
            "Gist + Discussion requires authenticated GitHub credentials. Authenticate your own GitHub CLI account and reopen support, or choose Create ZIP only."
        )
    client.discover.assert_not_called()
    client.gist_request.assert_not_called()
    client.create.assert_not_called()


@pytest.mark.parametrize("delivery", ["zip", "discussion"])
@pytest.mark.parametrize("saved", [None, [], ["diagnostics.txt"]])
def test_doctor_is_first_and_checked_only_for_new_diagnostic_lists(
    support, monkeypatch, delivery, saved
):
    """USER EXPERIENCE: Doctor first/default-on; alphabetical files; saved choices win.

    The user can uncheck Doctor. Reopening a reviewed bundle must not re-check it.
    A blank prepared title/message stays editable, never becomes a generated title.
    """
    root, bundle, client = support
    context = {"title": "", "description": "", "category": "bug-reports"}
    (root / gh.CONTEXT_FILE).write_text(json.dumps(context))
    for name in ("z-last.txt", "doctor.json", "a-first.json"):
        (root / name).write_text("{}")
        bundle["files"].append({"name": name, "redactions": 0})
    if saved is not None:
        bundle["include_files"] = saved
    monkeypatch.setattr(bundles, "_active_bundles", {"support-doctor-ux": bundle})

    def dialog(request):
        if request["mode"] == "delivery":
            return {"request_id": request["request_id"], "delivery": delivery}
        assert request["mode"] == ("edit" if delivery == "discussion" else "bundle")
        assert request["include_files"] == (["doctor.json"] if saved is None else saved)
        names = [item["name"] for item in request["files"]]
        assert names[0] == "doctor.json"
        assert names[1:] == sorted(names[1:])
        if delivery == "discussion":
            assert request["context"] == context
        return None

    monkeypatch.setattr(gh, "review_dialog", dialog)
    assert bundles.send_bundle("support-doctor-ux")["error_code"] == "cancelled"
    client.gist_request.assert_not_called()
    client.create.assert_not_called()


@pytest.mark.parametrize(
    "delivery,field",
    [("discussion", "title"), ("discussion", "description"), ("zip", "description")],
)
@pytest.mark.parametrize("value", ["", " \n\t "])
def test_title_and_message_are_required_before_any_diagnostic_upload(
    support, monkeypatch, delivery, field, value
):
    """USER EXPERIENCE: Checked diagnostics cannot substitute for a title or message.

    Title/message whitespace is not valid. No ZIP or Gist is created; the local
    bundle stays available. Native fields also keep the action disabled until valid.
    """
    root, bundle, client = support
    (root / "doctor.json").write_text("{}")
    bundle["files"].append({"name": "doctor.json", "redactions": 0})
    monkeypatch.setattr(bundles, "_active_bundles", {"support-required-ux": bundle})

    def dialog(request):
        if request["mode"] == "delivery":
            return {"request_id": request["request_id"], "delivery": delivery}
        return {
            "request_id": request["request_id"],
            "send": True,
            "title": "A user-written title",
            "description": "How to reproduce the issue.",
            "category": "bug-reports",
            "include_files": ["doctor.json"],
            field: value,
        }

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = bundles.send_bundle("support-required-ux")
    assert result["error_code"] == "context"
    assert result["message"] == (
        "A non-empty, single-line support title is required."
        if field == "title"
        else "A support message is required."
    )
    assert root.is_dir()
    assert not (root / "support-message.txt").exists()
    client.gist_request.assert_not_called()
    client.create.assert_not_called()


@pytest.mark.parametrize("advance", [False, True])
@pytest.mark.parametrize(
    "label,next_mode", [("Create ZIP only", "bundle"), ("Gist + Discussion", "edit")]
)
def test_destination_dropdown_requires_next_and_next_is_not_upload_consent(
    support, monkeypatch, advance, label, next_mode
):
    """USER EXPERIENCE: Select a destination → wait for Next, never upload or publish.

    The first screen defaults to local ZIP. Selecting either destination does not
    authenticate, close the screen, or grant either upload/publication consent.
    Next opens its review page; cancelling leaves the prepared bundle intact.
    """
    import sys
    from types import SimpleNamespace
    from ai_guardian.ui import support_review

    root_path, bundle, client = support
    monkeypatch.setattr(bundles, "_active_bundles", {"support-next-page-ux": bundle})
    root = Mock()
    ttk = SimpleNamespace(
        Frame=Mock(), Label=Mock(), Button=Mock(), Combobox=Mock(), Style=Mock()
    )
    tk = SimpleNamespace(Tk=Mock(return_value=root), ttk=ttk, TclError=RuntimeError)
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(
        sys.modules, "tkinter.scrolledtext", SimpleNamespace(ScrolledText=Mock())
    )
    selector = ttk.Combobox.return_value
    selector.set.side_effect = lambda value: setattr(
        selector.get, "return_value", value
    )
    stages = []

    def interact():
        assert selector.get() == "Create ZIP only"
        assert ttk.Combobox.call_args.kwargs["values"] == [
            "Create ZIP only",
            "Gist + Discussion",
        ]
        assert ttk.Combobox.call_args.kwargs["state"] == "readonly"
        selector.get.return_value = label
        selector.bind.call_args.args[1]()
        assert stages == ["delivery"]
        root.destroy.assert_not_called()
        client.discover.assert_not_called()
        button = next(
            call.kwargs
            for call in ttk.Button.call_args_list
            if call.kwargs["text"] == ("Next" if advance else "Cancel")
        )
        button["command"]()

    def dialog(request):
        stages.append(request["mode"])
        return (
            support_review.show_review(request)
            if request["mode"] == "delivery"
            else None
        )

    root.mainloop.side_effect = interact
    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = bundles.send_bundle("support-next-page-ux")
    assert result["error_code"] == "cancelled"
    assert stages == (["delivery", next_mode] if advance else ["delivery"])
    assert root_path.is_dir()
    if advance and next_mode == "edit":
        client.discover.assert_called_once_with()
    else:
        client.discover.assert_not_called()
    client.gist_request.assert_not_called()
    client.create.assert_not_called()


@pytest.mark.parametrize("stage", ["edit", "upload", "approve"])
def test_cancel_explains_whether_a_gist_was_already_uploaded(
    support, monkeypatch, stage
):
    """USER EXPERIENCE: Cancel → no Discussion; an already uploaded Gist stays yours."""
    root, bundle, client = support

    def dialog(request):
        if request["mode"] == stage:
            return None
        if request["mode"] != "edit":
            return {"request_id": request["request_id"], "approved": True}
        return {
            "request_id": request["request_id"],
            **request["context"],
            "include_files": ["diagnostics.txt"],
        }

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = gh.send_discussion("support-ux", bundle)
    if stage == "approve":
        assert result["delivery_status"] == "gist_only"
        assert result["gist_url"] in result["message"]
        assert "already uploaded" in result["message"] and "delete" in result["message"]
        assert "No discussion was created" in result["message"]
    else:
        assert result["delivery_status"] == "not_published"
        assert "gist_url" not in result
        client.gist_request.assert_not_called()
    assert root.exists()
    client.create.assert_not_called()


def test_headless_error_does_not_prompt_agent_for_approval(support):
    """USER EXPERIENCE: Missing trusted desktop review → fail closed, keep bundle."""
    root, bundle, client = support
    result = gh.send_discussion("support-ux", bundle)
    assert (
        result["message"]
        == "Public publication requires the native user review dialog on your desktop. No discussion was created; retain the local bundle for manual review."
    )
    assert result["error_code"] == "review_unavailable"
    assert root.exists()
    client.create.assert_not_called()


def test_auth_error_is_actionable_without_credential_values(support, monkeypatch):
    """USER EXPERIENCE: Auth fails before review → safe actionable message, no send."""
    root, bundle, client = support
    client.discover.side_effect = gh.GitHubError(
        "Authenticate your own GitHub CLI account for github.com with permission to create Gists and write public Discussions.",
        code="authentication",
    )
    result = gh.send_discussion("support-ux", bundle)
    assert (
        result["message"]
        == "Authenticate your own GitHub CLI account for github.com with permission to create Gists and write public Discussions."
    )
    assert "private diagnostic" not in json.dumps(result)
    assert root.exists()
    client.create.assert_not_called()


def test_manual_delivery_is_not_reported_as_completed(support, monkeypatch):
    """USER EXPERIENCE: Binary diagnostics → no fake attachment or success URL."""
    root, bundle, client = support
    (root / "diagnostics.txt").write_bytes(b"\xffbinary")
    # The chooser opens first so the user could exclude the binary. Keeping it
    # selected must still produce a manual-delivery error, never partial success.
    monkeypatch.setattr(
        gh,
        "review_dialog",
        lambda request: {
            "request_id": request["request_id"],
            **request["context"],
            "include_files": ["diagnostics.txt"],
        },
    )
    result = gh.send_discussion("support-ux", bundle)
    assert result["error_code"] == "manual_required"
    assert result["delivery_status"] == "not_published"
    assert result["message"] == gh.MANUAL_MESSAGE
    assert "discussion_url" not in result
    assert bundles._format_send_human(result).startswith("✗ No discussion was created.")
    client.create.assert_not_called()


def test_oversized_configuration_is_complete_in_view_and_never_silently_sent(
    support, monkeypatch
):
    """USER EXPERIENCE: Full config too large for GitHub → no crop or partial post.

    View shows the complete sanitized configuration, including its final fields.
    Send explains the size limit and suggests fewer files or a separately arranged
    private channel. No final publication or upload occurs, and the copy is intact.
    """
    from ai_guardian.ui.support_review import read_preview

    root, bundle, client = support
    name = "ai-guardian.json"
    original = json.dumps(
        {
            "diagnostics": "One ordinary configuration detail. " * 33_000,
            "last_field": "still present",
        }
    )
    (root / name).write_text(original, encoding="utf-8")
    bundle["files"].append({"name": name, "redactions": 0})

    def dialog(request):
        assert request["mode"] == "edit"
        names = [item["name"] for item in request["files"]]
        first = read_preview(request["temp_path"], name, names)
        assert first.next_offset is not None
        last = read_preview(request["temp_path"], name, names, offset=first.next_offset)
        assert first.text + last.text == original
        return {
            "request_id": request["request_id"],
            **request["context"],
            "include_files": names,
        }

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = gh.send_discussion("support-complete-config-ux", bundle)
    assert result["error_code"] == "manual_required"
    assert result["delivery_status"] == "not_published"
    assert result["message"] == gh.MANUAL_MESSAGE
    assert "No files were shortened during sending" in result["message"]
    assert "private support channel" in result["message"]
    assert (root / name).read_text(encoding="utf-8") == original
    client.create.assert_not_called()


def test_replaced_context_is_not_sent_as_stale_diagnostics(support, monkeypatch):
    """USER EXPERIENCE: Edit context → discarded wording is never published."""
    _, bundle, client = support

    def dialog(request):
        if request["mode"] == "edit":
            return {
                "request_id": request["request_id"],
                **request["context"],
                "description": "Revised context",
                "include_files": ["diagnostics.txt"],
            }
        assert ("Revised context" in request["body"]) is (request["mode"] == "approve")
        assert "Test context" not in request["body"]
        assert gh.CONTEXT_FILE not in request["body"]
        assert all(item["name"] != gh.CONTEXT_FILE for item in request["files"])
        return {"request_id": request["request_id"], "approved": True}

    monkeypatch.setattr(gh, "review_dialog", dialog)
    assert gh.send_discussion("support-ux", bundle)["status"] == "sent"
    client.create.assert_called_once()


def test_prepare_summary_documents_local_review_and_public_warning():
    """USER EXPERIENCE: Preparation summary exposes no diagnostic contents."""
    summary = {
        "temp_path": "/review/path",
        "files": [{"name": "diagnostics.txt", "redactions": 3}],
        "public_warning": gh.PUBLIC_WARNING,
    }
    text = bundles._format_prepare_human(summary)
    assert gh.PUBLIC_WARNING in text
    assert "3 items redacted" in text
    assert (
        "Categories: Bug Reports (default), Q&A. Preparation has not published anything."
        in text
    )
    assert "Publication requires native user review; --yes cannot approve it." in text
    assert (
        "Delete any files you do not want to send from this directory before continuing."
        in text
    )
    assert "Deleted files will not be collected again." in text
    assert "After reviewing the files, run:" in text


def test_tray_configured_github_sanitizes_the_user_message(
    support, monkeypatch, tmp_path
):
    """USER EXPERIENCE: Contact supports → GitHub groups and an editable safe message.

    Saved CLI exports are not changed. The user types a message and selects one
    diagnostic; Send opens the exact sanitized preview, not an immediate post.
    Only the subsequent public-consent click publishes that description/file.
    """
    from ai_guardian.tray import support as tray_support

    _, info, client = support
    saved = {"export_destination": gh.DESTINATION}
    existing = {"destination": str(tmp_path / "legacy-exports")}
    bundle_id = "support-new-tray-report"
    monkeypatch.setattr(bundles, "_get_support_config", lambda: saved)
    monkeypatch.setattr(bundles, "_active_bundles", {"support-existing": existing})

    def prepare(**kwargs):
        assert kwargs == {}
        bundles._active_bundles[bundle_id] = info
        return {"bundle_id": bundle_id, **info}

    monkeypatch.setattr(bundles, "prepare_bundle", prepare)
    monkeypatch.setattr(
        gh,
        "public_text",
        lambda text: (
            text.replace("private example", "[REDACTED]"),
            int("private example" in text),
        ),
    )
    stages = []

    def dialog(request):
        stages.append(request["mode"])
        if request["mode"] == "delivery":
            client.discover.assert_not_called()
            return {"request_id": request["request_id"], "delivery": "discussion"}
        if request["mode"] == "edit":
            assert request["categories"] == {"bug-reports": "Bug Reports", "q-a": "Q&A"}
            assert request["include_files"] == []
            return {
                "request_id": request["request_id"],
                "title": "How do I resolve this?",
                "description": "My private example needs investigation.",
                "category": "q-a",
                "include_files": ["diagnostics.txt"],
            }
        if request["mode"] == "upload":
            assert "safe diagnostic text" in request["body"]
            return {"request_id": request["request_id"], "approved": True}
        if request["mode"] == "approve":
            client.create.assert_not_called()
            assert "My [REDACTED] needs investigation." in request["body"]
            assert "private example" not in request["body"]
            assert "safe diagnostic text" not in request["body"]
            assert "https://gist.github.com/verified-user/" in request["body"]
            assert request["context_redactions"] == 1
            assert [item["name"] for item in request["files"]] == ["diagnostics.txt"]
            assert request["category"] == "Q&A"
            return {"request_id": request["request_id"], "approved": True}
        assert request["mode"] == "result"
        return None

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = tray_support.run_support_flow()
    assert result["discussion_url"] == client.create.return_value
    assert stages == ["delivery", "edit", "upload", "approve", "result"]
    assert saved == {"export_destination": gh.DESTINATION}
    assert existing["destination"] == str(tmp_path / "legacy-exports")
    client.create.assert_called_once()


def test_tray_local_export_remains_available_to_subsequent_terminal_send(
    support, monkeypatch, tmp_path, capsys
):
    """USER EXPERIENCE: Tray export → a later CLI send finds the reviewed copy."""
    import sys
    from ai_guardian import cli
    from ai_guardian.tray import support as tray_support

    root, info, client = support
    monkeypatch.setattr(bundles, "_active_bundles", {})
    destination = tmp_path / "retained-local-bundles"
    info["destination"] = str(destination)
    monkeypatch.setattr(
        bundles, "_get_support_config", lambda: {"export_destination": str(destination)}
    )
    unwanted = root / "cli-example-user-settings.json"
    unwanted.write_text('{"configuration": {"model": "test-model"}}')
    info["files"].append({"name": unwanted.name, "redactions": 0})
    bundle_id = "support-20261022-feed1234"

    def prepare(**kwargs):
        bundles._active_bundles[bundle_id] = info
        bundles._persist_bundle_ref(bundle_id, info)
        return {"bundle_id": bundle_id, **info}

    monkeypatch.setattr(bundles, "prepare_bundle", prepare)
    monkeypatch.setattr(
        cli,
        "_ensure_daemon_started",
        Mock(side_effect=AssertionError("No daemon needed")),
    )
    monkeypatch.setitem(sys.modules, "mcp", None)
    monkeypatch.setitem(sys.modules, "ai_guardian.mcp.server", None)
    modes = []

    def dialog(request):
        modes.append(request["mode"])
        if request["mode"] == "bundle":
            assert request["destination"] == str(destination / bundle_id)
            assert request["local_only"] is True
            assert "categories" not in request
            return {
                "request_id": request["request_id"],
                "send": True,
                "include_files": [
                    item["name"]
                    for item in request["files"]
                    if item["name"] != unwanted.name
                ],
                "description": "Please investigate this issue.",
            }
        assert request["mode"] == "result"
        assert (
            "No files were sent to support. No Discussion was created."
            in request["message"]
        )
        assert "✓ Sent:" not in request["message"]
        return None

    monkeypatch.setattr(gh, "review_dialog", dialog)
    monkeypatch.setattr(
        "ai_guardian.daemon.multi_client._launch_in_terminal",
        Mock(side_effect=AssertionError("No shell")),
    )
    assert tray_support.run_support_flow()["delivery_status"] == "local_only"
    assert modes == ["bundle", "result"]
    retained = destination / bundle_id
    assert not (retained / unwanted.name).exists()

    bundles._active_bundles.clear()  # Separate terminal process.
    monkeypatch.setattr(sys, "argv", ["ai-guardian", "support", "send", "--yes"])
    assert cli.main() == 0
    second = capsys.readouterr()
    assert "No pending bundle" not in second.err
    assert str(retained) in second.out
    assert unwanted.name not in second.out
    assert not (retained / unwanted.name).exists()
    client.discover.assert_not_called()
    client.create.assert_not_called()


@pytest.mark.parametrize("approve", [False, True])
def test_tray_support_preserves_explicit_public_review(support, monkeypatch, approve):
    """USER EXPERIENCE: Tray opens local support; only final user consent sends."""
    import sys
    from ai_guardian import cli
    from ai_guardian.tray import support as tray_support

    root, bundle, client = support
    bundle_id = "support-from-tray"
    bundles._active_bundles[bundle_id] = bundle
    monkeypatch.setattr(
        bundles,
        "prepare_bundle",
        lambda **kwargs: {
            "bundle_id": bundle_id,
            **bundle,
            "public_warning": gh.PUBLIC_WARNING,
        },
    )
    daemon = Mock(side_effect=AssertionError("Tray support must not start a daemon"))
    monkeypatch.setattr(cli, "_ensure_daemon_started", daemon)
    monkeypatch.setitem(sys.modules, "mcp", None)
    monkeypatch.setitem(sys.modules, "ai_guardian.mcp.server", None)
    modes = []

    def dialog(request):
        modes.append(request["mode"])
        if request["mode"] == "delivery":
            client.discover.assert_not_called()
            return {"request_id": request["request_id"], "delivery": "discussion"}
        if request["mode"] == "result":
            assert "https://gist.github.com/verified-user/" in request["message"]
            if approve:
                assert client.create.return_value in request["message"]
            return None
        if request["mode"] == "edit":
            assert request["categories"] == {"bug-reports": "Bug Reports", "q-a": "Q&A"}
            assert request["destination"] == f"{gh.REPOSITORY_URL}/discussions"
            return {
                "request_id": request["request_id"],
                **request["context"],
                "include_files": ["diagnostics.txt"],
            }
        if request["mode"] == "upload":
            assert "safe diagnostic text" in request["body"]
            return {"request_id": request["request_id"], "approved": True}
        client.create.assert_not_called()
        assert request["warning"] == gh.PUBLIC_WARNING
        assert "safe diagnostic text" not in request["body"]
        assert "https://gist.github.com/verified-user/" in request["body"]
        return (
            {"request_id": request["request_id"], "approved": True} if approve else None
        )

    monkeypatch.setattr(gh, "review_dialog", dialog)

    monkeypatch.setattr(
        "ai_guardian.daemon.multi_client._launch_in_terminal",
        Mock(side_effect=AssertionError("No shell")),
    )
    monkeypatch.setattr(
        "builtins.input", Mock(side_effect=AssertionError("No terminal prompt"))
    )
    try:
        result = tray_support.run_support_flow()
        assert modes == ["delivery", "edit", "upload", "approve", "result"]
        assert root.exists()
        daemon.assert_not_called()
        if approve:
            client.create.assert_called_once()
            assert result["discussion_url"] == client.create.return_value
        else:
            client.create.assert_not_called()
            assert result["delivery_status"] == "gist_only"
            assert result["gist_url"] in result["message"]
            assert "already uploaded" in result["message"]
    finally:
        bundles._active_bundles.pop(bundle_id, None)


def test_missing_desktop_reports_that_nothing_was_sent(support, monkeypatch):
    """USER EXPERIENCE: No desktop → notification, no shell fallback or send."""
    from ai_guardian.tray import menu

    _, _, client = support
    prepare = Mock()
    notify = Mock()
    monkeypatch.setattr(bundles, "prepare_bundle", prepare)
    monkeypatch.setattr("ai_guardian.ui.display.get_preferred_ui", lambda: "headless")
    monkeypatch.setattr(
        "ai_guardian.daemon.multi_client._launch_in_terminal",
        Mock(side_effect=AssertionError("No shell fallback")),
    )
    monkeypatch.setattr("ai_guardian.tray.support.show_notification", notify)

    assert menu.launch_support() is False
    assert notify.call_args.args == (
        "AI Guardian Support",
        "The support dialog needs a native desktop. Run 'ai-guardian support send --prepare' in your own terminal for the standalone workflow. Nothing was sent.",
    )
    prepare.assert_not_called()
    client.discover.assert_not_called()
    client.create.assert_not_called()


def test_standalone_terminal_support_when_agent_is_unavailable(
    support, monkeypatch, capsys
):
    """USER EXPERIENCE: Agent/MCP unavailable → direct CLI review still works."""
    import sys
    from ai_guardian import cli

    root, bundle, client = support
    bundle_id = "support-offline-agent"
    bundles._active_bundles[bundle_id] = bundle
    monkeypatch.setattr(
        bundles, "prepare_bundle", lambda: {"bundle_id": bundle_id, **bundle}
    )
    daemon = Mock(
        side_effect=AssertionError("Must not start the component being diagnosed")
    )
    monkeypatch.setattr(cli, "_ensure_daemon_started", daemon)
    monkeypatch.setitem(sys.modules, "mcp", None)
    monkeypatch.setitem(sys.modules, "ai_guardian.mcp.server", None)
    monkeypatch.setattr(sys, "argv", ["ai-guardian", "support", "send", "--prepare"])
    monkeypatch.setattr(gh, "review_dialog", lambda request: None)
    try:
        assert cli.main() == 1
        assert (
            "Support cancelled. Nothing was sent; prepared files remain local."
            in capsys.readouterr().out
        )
        assert root.exists()
        daemon.assert_not_called()
        client.create.assert_not_called()
    finally:
        bundles._active_bundles.pop(bundle_id, None)


@pytest.mark.parametrize("title", [None, "My supplied support title"])
def test_standalone_prepare_has_no_generated_title_but_keeps_an_explicit_proposal(
    support, monkeypatch, capsys, title
):
    """USER EXPERIENCE: No title proposal → blank native field; explicit proposals survive."""
    import sys
    from ai_guardian import cli

    _, _, client = support
    prepare = Mock(return_value={"bundle_id": "support-blank-title"})
    daemon = Mock(
        side_effect=AssertionError("Support preparation must not start a daemon")
    )
    monkeypatch.setattr(bundles, "prepare_bundle", prepare)
    monkeypatch.setattr(cli, "_ensure_daemon_started", daemon)
    argv = ["ai-guardian", "support", "prepare", "--json"]
    if title is not None:
        argv.extend(["--title", title])
    monkeypatch.setattr(sys, "argv", argv)
    assert cli.main() == 0
    assert prepare.call_args.kwargs["title"] == (title or "")
    assert prepare.call_args.kwargs["description"] == ""
    assert json.loads(capsys.readouterr().out)["bundle_id"] == "support-blank-title"
    daemon.assert_not_called()
    client.discover.assert_not_called()
    client.gist_request.assert_not_called()
    client.create.assert_not_called()


@pytest.mark.parametrize("entrypoint", ["tray", "standalone"])
def test_zip_only_is_complete_fully_viewable_and_never_uploaded(
    support, monkeypatch, capsys, entrypoint
):
    """USER EXPERIENCE: Choose Create ZIP only → reviewed local archive, not support delivery.

    Works without an agent, MCP, daemon or GitHub authentication. All fields of a
    large configuration are reachable using View pages and exported unchanged.
    Unchecked files stay out of the ZIP, and the result explains no upload and no
    encryption. Only the prepared log has a marked excerpt. Sending later still
    finds the same reviewed bundle with its configured GitHub destination intact.
    """
    import sys
    import zipfile
    from ai_guardian import cli
    from ai_guardian.tray import support as tray_support
    from ai_guardian.ui.support_review import read_preview

    root, bundle, client = support
    name = "ai-guardian.json"
    original = json.dumps(
        {
            "details": "Ordinary complete configuration detail. " * 30_000,
            "last_field": "END",
        }
    )
    (root / name).write_text(original, encoding="utf-8")
    (root / "ai-guardian.log").write_text(
        "[Truncated: older content omitted; showing newest data.]\nRECENT\n",
        encoding="utf-8",
    )
    bundle["files"].extend(
        [
            {"name": name, "redactions": 0},
            {"name": "ai-guardian.log", "redactions": 0, "truncated": True},
        ]
    )
    bid = "support-zip-only-ux"
    monkeypatch.setattr(bundles, "_active_bundles", {bid: bundle})
    monkeypatch.setattr(
        bundles, "prepare_bundle", lambda **kwargs: {"bundle_id": bid, **bundle}
    )
    monkeypatch.setattr(
        gh,
        "GitHubClient",
        Mock(side_effect=AssertionError("No GitHub credentials needed")),
    )
    monkeypatch.setattr(
        cli,
        "_ensure_daemon_started",
        Mock(side_effect=AssertionError("No daemon needed")),
    )
    monkeypatch.setitem(sys.modules, "mcp", None)
    modes = []

    def dialog(request):
        modes.append(request["mode"])
        if request["mode"] == "delivery":
            return {"request_id": request["request_id"], "delivery": "zip"}
        if request["mode"] == "bundle":
            assert request["zip_export"] is True and request["local_only"] is True
            assert "categories" not in request and "account" not in request
            allowed = [item["name"] for item in request["files"]]
            text = []
            offset = 0
            while True:
                page = read_preview(request["temp_path"], name, allowed, offset=offset)
                text.append(page.text)
                if page.next_offset is None:
                    break
                offset = page.next_offset
            assert len(text) > 1 and "".join(text) == original
            return {
                "request_id": request["request_id"],
                "send": True,
                "include_files": [name, "ai-guardian.log"],
                "description": "Please investigate this issue.",
            }
        assert request["mode"] == "result"
        assert "No files were uploaded or sent to support" in request["message"]
        archive = Path(request["zip_path"])
        assert archive.is_file() and archive.suffix == ".zip"
        assert (
            "not encrypted" in request["message"]
            and "✓ Sent:" not in request["message"]
        )
        return None

    monkeypatch.setattr(gh, "review_dialog", dialog)
    if entrypoint == "tray":
        result = tray_support.run_support_flow()
        archive = Path(result["zip_path"])
        assert modes == ["delivery", "bundle", "result"]
    else:
        monkeypatch.setattr(
            sys, "argv", ["ai-guardian", "support", "send", "--prepare"]
        )
        assert cli.main() == 0
        output = capsys.readouterr().out
        assert "ZIP created locally" in output and "✓ Sent:" not in output
        from ai_guardian.config.utils import get_state_dir

        archive = next((get_state_dir() / "support-exports").rglob("*.zip"))
        assert modes == ["delivery", "bundle"]
    with zipfile.ZipFile(archive) as contents:
        assert set(contents.namelist()) == {
            name,
            "ai-guardian.log",
            "support-message.txt",
        }
        assert contents.read(name).decode("utf-8") == original
        assert (
            contents.read("ai-guardian.log") == (root / "ai-guardian.log").read_bytes()
        )
        assert contents.read("support-message.txt") == b"Please investigate this issue."
    bundles._active_bundles.clear()
    assert bundles._load_last_bundle() == bid
    assert bundles._active_bundles[bid]["destination"] == gh.DESTINATION
    client.discover.assert_not_called()
    client.create.assert_not_called()
