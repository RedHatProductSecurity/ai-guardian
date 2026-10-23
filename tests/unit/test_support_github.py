"""GitHub support publication: no real credentials, UI, or network requests."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from ai_guardian.reporting import support_bundle as bundles


def test_fresh_default_and_saved_empty_destination(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert bundles._get_support_config()["export_destination"] == "github-discussions"
    from ai_guardian.config.utils import get_config_dir

    config = get_config_dir() / "ai-guardian.json"
    for saved in ({}, {"support": {}}, {"support": {"export_destination": ""}}):
        config.write_text(json.dumps(saved))
        assert (
            bundles._get_support_config()["export_destination"] == "github-discussions"
        )


@pytest.fixture
def github(monkeypatch, tmp_path, support_github_transport):
    from ai_guardian.reporting import github_support as gh

    root = tmp_path / "reviewed"
    root.mkdir()
    (root / "system-info.json").write_text('{"os": "test"}')
    (root / gh.CONTEXT_FILE).write_text(
        json.dumps(
            {
                "title": "A failure",
                "description": "Steps to reproduce",
                "category": "bug-reports",
            }
        )
    )
    info = {
        "temp_path": str(root),
        "destination": gh.DESTINATION,
        "created": datetime.now(timezone.utc).isoformat(),
        "ttl_minutes": 30,
        "files": [{"name": p.name, "redactions": 0} for p in sorted(root.iterdir())],
    }
    identity = {
        "account_id": "U_reporter",
        "login": "actual-reporter",
        "repository_id": "R_canonical",
        "categories": {"bug-reports": "D_bug", "q-a": "D_help"},
    }
    client = Mock()
    client.discover.return_value = identity
    client.scrub.side_effect = lambda text: text
    client.create.return_value = (
        "https://github.com/RedHatProductSecurity/ai-guardian/discussions/123"
    )
    support_github_transport(client)
    monkeypatch.setattr(gh, "GitHubClient", lambda: client)
    calls = []

    def dialog(request):
        calls.append(request)
        if request["mode"] == "delivery":
            return {"request_id": request["request_id"], "delivery": "discussion"}
        if request["mode"] == "edit":
            return {
                "request_id": request["request_id"],
                **request["context"],
                "include_files": [item["name"] for item in request["files"]],
            }
        return {"request_id": request["request_id"], "approved": True}

    monkeypatch.setattr(gh, "review_dialog", dialog)
    return gh, root, info, client, calls


@pytest.mark.parametrize("category", ["bug-reports", "q-a"])
def test_allowed_categories_create_discussion(github, category):
    gh, root, info, client, calls = github
    context = json.loads((root / gh.CONTEXT_FILE).read_text())
    context["category"] = category
    (root / gh.CONTEXT_FILE).write_text(json.dumps(context))
    result = gh.send_discussion("support-test", info)
    assert result["status"] == "sent"
    assert result["discussion_url"].endswith("/discussions/123")
    assert result["destination"] == gh.DESTINATION
    assert calls[-1]["account"] == "actual-reporter"
    assert calls[-1]["repository"] == gh.REPOSITORY
    assert calls[-1]["category"] == gh.CATEGORIES[category]
    assert '"os": "test"' in calls[-2]["body"]
    assert '"os": "test"' not in calls[-1]["body"]
    assert result["gist_url"] in calls[-1]["body"]
    assert "Steps to reproduce" in calls[-1]["body"]
    assert "not prove" in calls[-1]["body"]
    client.create.assert_called_once()
    assert root.exists()


@pytest.mark.parametrize(
    "category",
    [
        "polls",
        "announcements",
        "general",
        "ideas",
        "show-and-tell",
        "D_bug",
        "https://example.com",
    ],
)
def test_disallowed_category_never_publishes(github, category):
    gh, root, info, client, _ = github
    context = json.loads((root / gh.CONTEXT_FILE).read_text())
    context["category"] = category
    (root / gh.CONTEXT_FILE).write_text(json.dumps(context))
    result = gh.send_discussion("support-test", info)
    assert result["status"] == "error"
    client.create.assert_not_called()


def test_cancelled_consent_never_publishes(github, monkeypatch):
    gh, root, info, client, _ = github
    monkeypatch.setattr(gh, "review_dialog", lambda request: None)
    result = gh.send_discussion("support-test", info)
    assert result["status"] == "error"
    assert result["error_code"] == "cancelled"
    assert root.exists()
    client.create.assert_not_called()


def test_edited_context_supersedes_local_proposal(github, monkeypatch):
    gh, _, info, client, _ = github

    def dialog(request):
        if request["mode"] == "edit":
            return {
                "request_id": request["request_id"],
                "title": "Revised support question",
                "description": "Only this revised context should be published",
                "category": "q-a",
                "include_files": [item["name"] for item in request["files"]],
            }
        return {"request_id": request["request_id"], "approved": True}

    monkeypatch.setattr(gh, "review_dialog", dialog)
    assert gh.send_discussion("support-test", info)["status"] == "sent"
    identity, category, title, body = client.create.call_args.args
    assert identity["login"] == "actual-reporter"
    assert category == "q-a"
    assert title == "Revised support question"
    assert "Only this revised context should be published" in body
    assert "Steps to reproduce" not in body
    assert "A failure" not in body
    assert gh.CONTEXT_FILE not in body


def test_reviewed_file_removal_is_respected(github):
    gh, root, info, client, calls = github
    (root / "remaining.txt").write_text("Explicitly included diagnostic")
    info["files"].append({"name": "remaining.txt", "redactions": 0})
    (root / "system-info.json").unlink()
    assert gh.send_discussion("support-test", info)["status"] == "sent"
    assert "system-info.json" not in calls[-1]["body"]
    assert "Explicitly included diagnostic" in calls[-2]["body"]
    assert "Explicitly included diagnostic" not in calls[-1]["body"]
    client.create.assert_called_once()


def test_mutation_after_approval_never_publishes(github, monkeypatch):
    gh, root, info, client, _ = github

    def mutate(request):
        if request["mode"] == "edit":
            return {
                "request_id": request["request_id"],
                **request["context"],
                "include_files": [item["name"] for item in request["files"]],
            }
        (root / "system-info.json").write_text("changed after final preview")
        return {"request_id": request["request_id"], "approved": True}

    monkeypatch.setattr(gh, "review_dialog", mutate)
    result = gh.send_discussion("support-test", info)
    assert result["error_code"] == "changed"
    client.create.assert_not_called()


def test_oversized_bundle_is_not_a_partial_submission(github):
    gh, root, info, client, _ = github
    (root / "system-info.json").write_text("ordinary diagnostic line\n" * 50_000)
    result = gh.send_discussion("support-test", info)
    assert result["status"] == "error"
    assert result["error_code"] == "manual_required"
    assert result["delivery_status"] == "not_published"
    assert "No discussion was created" in result["message"]
    assert root.exists()
    client.create.assert_not_called()


def test_uncertain_outcome_is_not_blindly_retried(github):
    gh, root, info, client, _ = github
    client.create.side_effect = gh.GitHubError("Network failure.", uncertain=True)
    for _ in range(2):
        result = gh.send_discussion("support-test", info)
        assert result["error_code"] == "uncertain"
    client.create.assert_called_once()
    assert root.exists()


def test_success_receipt_prevents_replay_across_processes(github):
    gh, root, info, client, _ = github
    first = gh.send_discussion("support-test", info)
    second = gh.send_discussion("support-test", dict(info))
    assert first["discussion_url"] == second["discussion_url"]
    assert second["already_submitted"] is True
    client.create.assert_called_once()
    assert root.exists()


def test_approval_is_bound_expiring_and_single_use(github, monkeypatch):
    gh, _, _, _, _ = github
    monkeypatch.setattr(gh, "monotonic", lambda: 10)
    approval = gh.Approval("payload-a", 20)
    with pytest.raises(gh.GitHubError):
        approval.consume("payload-b")
    with pytest.raises(gh.GitHubError):
        approval.consume("payload-a")
    expired = gh.Approval("payload-a", 9)
    with pytest.raises(gh.GitHubError):
        expired.consume("payload-a")
    valid = gh.Approval("payload-a", 20)
    valid.consume("payload-a")
    with pytest.raises(gh.GitHubError):
        valid.consume("payload-a")


def discovery_data():
    from ai_guardian.reporting import github_support as gh

    owner = {"id": "R_canonical", "nameWithOwner": gh.REPOSITORY}
    return {
        "viewer": {
            "id": "U_reporter",
            "login": "actual-reporter",
            "__typename": "User",
        },
        "repository": {
            **owner,
            "url": gh.REPOSITORY_URL,
            "hasDiscussionsEnabled": True,
            "discussionCategories": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [
                    {
                        "id": "D_bug",
                        "slug": "bug-reports",
                        "isAnswerable": False,
                        "repository": dict(owner),
                    },
                    {
                        "id": "D_help",
                        "slug": "q-a",
                        "isAnswerable": True,
                        "repository": dict(owner),
                    },
                    {
                        "id": "D_polls",
                        "slug": "polls",
                        "isAnswerable": False,
                        "repository": dict(owner),
                    },
                    {
                        "id": "D_news",
                        "slug": "announcements",
                        "isAnswerable": False,
                        "repository": dict(owner),
                    },
                ],
            },
        },
    }


def test_discovery_filters_extras_and_accepts_nonanswerable_bug_reports():
    from ai_guardian.reporting import github_support as gh

    client = object.__new__(gh.GitHubClient)
    client._graphql = Mock(return_value=discovery_data())
    identity = client.discover()
    assert identity["categories"] == {"bug-reports": "D_bug", "q-a": "D_help"}
    assert identity["login"] == "actual-reporter"


@pytest.mark.parametrize(
    "change",
    [
        "repository",
        "url",
        "disabled",
        "missing",
        "nonanswerable",
        "category_owner",
        "duplicate",
        "bot",
        "pagination",
    ],
)
def test_discovery_rejects_spoofed_or_unavailable_support(change):
    from ai_guardian.reporting import github_support as gh

    data = discovery_data()
    repo = data["repository"]
    nodes = repo["discussionCategories"]["nodes"]
    if change == "repository":
        repo["nameWithOwner"] = "other/repository"
    elif change == "url":
        repo["url"] = "https://example.com/other"
    elif change == "disabled":
        repo["hasDiscussionsEnabled"] = False
    elif change == "missing":
        nodes.pop(0)
    elif change == "nonanswerable":
        nodes[1]["isAnswerable"] = False
    elif change == "category_owner":
        nodes[0]["repository"]["id"] = "R_spoofed"
    elif change == "duplicate":
        nodes.append(dict(nodes[0]))
    elif change == "bot":
        data["viewer"]["__typename"] = "Bot"
    elif change == "pagination":
        repo["discussionCategories"]["pageInfo"]["hasNextPage"] = True
    client = object.__new__(gh.GitHubClient)
    client._graphql = Mock(return_value=data)
    with pytest.raises(gh.GitHubError):
        client.discover()


@pytest.mark.parametrize(
    "change",
    ["identity", "category_id", "category", "title", "description", "removed", "added"],
)
def test_all_postreview_changes_reject_approval(github, monkeypatch, change):
    gh, root, info, client, _ = github

    def mutate(request):
        if request["mode"] == "edit":
            return {
                "request_id": request["request_id"],
                **request["context"],
                "include_files": [item["name"] for item in request["files"]],
            }
        if change in ("identity", "category_id"):
            current = {
                **client.discover.return_value,
                "categories": dict(client.discover.return_value["categories"]),
            }
            if change == "identity":
                current["login"] = "different-account"
            else:
                current["categories"]["bug-reports"] = "D_changed"
            client.discover.return_value = current
        elif change in ("title", "description", "category"):
            path = root / gh.CONTEXT_FILE
            context = json.loads(path.read_text())
            context[change] = "q-a" if change == "category" else "Changed after preview"
            path.write_text(json.dumps(context))
        elif change == "removed":
            (root / "system-info.json").unlink()
        else:
            (root / "new.json").write_text("new data")
        return {"request_id": request["request_id"], "approved": True}

    monkeypatch.setattr(gh, "review_dialog", mutate)
    result = gh.send_discussion("support-test", info)
    assert result["status"] == "error"
    client.create.assert_not_called()


def test_expiry_while_native_review_is_open(github, monkeypatch):
    gh, _, info, client, calls = github
    ticks = iter([10, 10 + gh.APPROVAL_SECONDS + 1])
    monkeypatch.setattr(gh, "monotonic", lambda: next(ticks))
    result = gh.send_discussion("support-test", info)
    assert len(calls) == 2
    assert result["error_code"] == "changed"
    client.create.assert_not_called()


def test_known_api_rejection_retains_files_and_requires_new_approval(github):
    gh, root, info, client, calls = github
    client.create.side_effect = gh.GitHubError("GitHub denied publication.")
    assert gh.send_discussion("support-test", info)["status"] == "error"
    assert root.exists()
    assert not (root / gh.JOURNAL_FILE).exists()
    client.create.side_effect = None
    assert gh.send_discussion("support-test", info)["status"] == "sent"
    assert [request["mode"] for request in calls] == [
        "edit",
        "upload",
        "approve",
        "edit",
        "approve",
    ]


@pytest.mark.parametrize(
    "data", [b"\x00\xff", b"x" * 1_000_001], ids=["binary", "oversized"]
)
def test_binary_or_excessive_diagnostics_require_manual_delivery(github, data):
    gh, root, info, client, _ = github
    (root / "system-info.json").write_bytes(data)
    result = gh.send_discussion("support-test", info)
    assert result["error_code"] == "manual_required"
    client.create.assert_not_called()


def test_symlink_is_never_read_or_published(github, tmp_path):
    gh, root, info, client, _ = github
    outside = tmp_path / "outside"
    outside.write_text("not a reviewed diagnostic")
    target = root / "system-info.json"
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks unavailable on this platform")
    assert gh.send_discussion("support-test", info)["error_code"] == "files"
    client.create.assert_not_called()


def test_supplied_identity_or_repository_is_not_accepted_as_context(github):
    gh, root, info, client, _ = github
    path = root / gh.CONTEXT_FILE
    context = json.loads(path.read_text())
    context.update(
        {
            "username": "maintainer",
            "repository": "attacker/support",
            "category_id": "D_polls",
        }
    )
    path.write_text(json.dumps(context))
    assert gh.send_discussion("support-test", info)["status"] == "error"
    client.create.assert_not_called()


def test_public_sanitization_covers_title_description_and_file_text():
    from ai_guardian.reporting.github_support import public_text, support_context

    # Synthetic generic assignment; not an issued/provider-format credential.
    text = "password = 'synthetic-sensitive-value'"
    context, count = support_context(text, text, "bug-reports")
    assert count >= 2
    assert "synthetic-sensitive-value" not in json.dumps(context)
    safe, count = public_text(text)
    assert "synthetic-sensitive-value" not in safe
    assert count > 0


@pytest.mark.parametrize("field", ["title", "description"])
@pytest.mark.parametrize("value", ["", " \n\t "])
def test_empty_reviewed_title_or_message_is_rejected_before_upload(
    github, monkeypatch, field, value
):
    gh, _, info, client, _ = github

    def dialog(request):
        assert request["mode"] == "edit"
        return {
            "request_id": request["request_id"],
            **request["context"],
            field: value,
            "include_files": ["system-info.json"],
        }

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = gh.send_discussion("support-required-context", info)
    assert result["error_code"] == "context"
    assert result["message"] == (
        "A non-empty, single-line support title is required."
        if field == "title"
        else "A support message is required."
    )
    client.gist_request.assert_not_called()
    client.create.assert_not_called()


def test_missing_context_opens_a_blank_draft_for_user_completion(github, monkeypatch):
    gh, root, info, client, _ = github
    (root / gh.CONTEXT_FILE).unlink()
    info["files"] = [item for item in info["files"] if item["name"] != gh.CONTEXT_FILE]
    dialog = Mock(return_value=None)
    monkeypatch.setattr(gh, "review_dialog", dialog)
    assert (
        gh.send_discussion("support-blank-context", info)["error_code"] == "cancelled"
    )
    assert dialog.call_args.args[0]["context"] == {
        "title": "",
        "description": "",
        "category": "bug-reports",
    }
    client.gist_request.assert_not_called()
    client.create.assert_not_called()


@pytest.mark.parametrize("status", [401, 403, 429, 422, 500])
def test_api_errors_are_credential_free(monkeypatch, caplog, status):
    from urllib.error import HTTPError
    from ai_guardian.reporting import github_support as gh

    client = object.__new__(gh.GitHubClient)
    client._token = "synthetic-auth-value"
    client._opener = Mock()
    client._opener.open.side_effect = HTTPError(
        "https://api.github.com/graphql", status, client._token, {}, None
    )
    with pytest.raises(gh.GitHubError) as error:
        client._graphql("mutation {}", mutation=True)
    assert client._token not in str(error.value)
    assert client._token not in caplog.text
    assert error.value.uncertain is (status == 500)


def test_authentication_uses_fixed_host_and_never_exposes_stderr(monkeypatch, caplog):
    from ai_guardian.reporting import github_support as gh

    command = Mock(
        return_value=SimpleNamespace(
            returncode=1, stdout="", stderr="synthetic-sensitive-error"
        )
    )
    monkeypatch.setattr(gh.subprocess, "run", command)
    with pytest.raises(gh.GitHubError) as error:
        gh.GitHubClient()
    assert command.call_args.args[0] == [
        "gh",
        "auth",
        "token",
        "--hostname",
        "github.com",
    ]
    assert "synthetic-sensitive-error" not in str(error.value) + caplog.text


def test_headless_and_forged_dialog_response_cannot_self_approve(monkeypatch):
    from ai_guardian.reporting import github_support as gh

    command = Mock()
    monkeypatch.setattr(gh.subprocess, "run", command)
    monkeypatch.setattr("ai_guardian.ui.display._ensure_tcl_library", lambda: None)
    with pytest.raises(gh.GitHubError) as error:
        gh.review_dialog({"approved": True})
    assert error.value.code == "review_unavailable"
    command.assert_not_called()
    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "tkinter")
    monkeypatch.delenv("AI_GUARDIAN_NO_TKINTER")
    command.return_value = SimpleNamespace(
        returncode=0, stdout='{"request_id":"wrong", "approved":true}'
    )
    with pytest.raises(gh.GitHubError):
        gh.review_dialog({"request_id": "expected"})
    argv = command.call_args.args[0]
    assert argv[:2] == [sys.executable, "-I"]
    assert (
        Path(argv[2])
        == Path(gh.__file__).resolve().parents[1] / "ui" / "support_review.py"
    )


def test_native_final_review_requires_user_checkbox_and_click(monkeypatch):
    from ai_guardian.ui import support_review
    from ai_guardian.reporting import github_support as gh

    root = Mock()
    consent = Mock()
    consent.get.return_value = False
    tk = SimpleNamespace(
        Tk=Mock(return_value=root),
        BooleanVar=Mock(return_value=consent),
        StringVar=Mock(),
    )
    ttk = SimpleNamespace(
        Frame=Mock(),
        Label=Mock(),
        Button=Mock(),
        Checkbutton=Mock(),
        LabelFrame=Mock(),
        Style=Mock(),
        Scrollbar=Mock(),
    )
    tk.Canvas = Mock()
    tk.ttk = ttk
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(
        sys.modules, "tkinter.scrolledtext", SimpleNamespace(ScrolledText=Mock())
    )
    monkeypatch.setattr("ai_guardian.ui.display._ensure_tcl_library", lambda: None)
    request = {
        "mode": "approve",
        "account": "actual-reporter",
        "category": "Bug Reports",
        "title": "A failure",
        "body": "Exact public content",
        "files": [],
        "context_redactions": 0,
        "request_id": "private-challenge",
        "approved": True,
        "repository": gh.REPOSITORY,
        "categories": dict(gh.CATEGORIES),
        "warning": gh.PUBLIC_WARNING,
    }

    def click_without_consent():
        button = next(
            c
            for c in reversed(ttk.Button.call_args_list)
            if c.kwargs["text"] == "Publish publicly"
        )
        assert button.kwargs["state"] == "disabled"
        button.kwargs["command"]()

    root.mainloop.side_effect = click_without_consent
    assert support_review.show_review(request) is None
    tk.BooleanVar.assert_called_with(value=False)
    consent.get.return_value = True
    assert support_review.show_review(request) == {
        "request_id": "private-challenge",
        "approved": True,
    }
    # The first dialog can only propose context/category, never approve it.
    ttk.Combobox = Mock()
    ttk.Combobox.return_value.get.return_value = "Q&A"
    ttk.Entry = Mock()
    ttk.Entry.return_value.get.return_value = "A usage question"
    sys.modules["tkinter.scrolledtext"].ScrolledText.return_value.get.return_value = (
        "Help context"
    )
    selected = Mock()
    selected.get.return_value = False
    tk.BooleanVar = Mock(return_value=selected)
    edit = {
        **request,
        "mode": "edit",
        "temp_path": "review-location",
        "files": [{"name": "diagnostic.txt"}],
        "context": {
            "title": "Initial title",
            "description": "Initial context",
            "category": "bug-reports",
        },
    }

    def click_preview():
        selected.get.return_value = True
        ttk.Checkbutton.call_args_list[-1].kwargs["command"]()
        button = next(
            c for c in reversed(ttk.Button.call_args_list) if c.kwargs["text"] == "Send"
        )
        button.kwargs["command"]()

    root.mainloop.side_effect = click_preview
    proposal = support_review.show_review(edit)
    assert proposal == {
        "request_id": "private-challenge",
        "category": "q-a",
        "title": "A usage question",
        "description": "Help context",
        "include_files": ["diagnostic.txt"],
    }
    assert ttk.Combobox.call_args.kwargs["values"] == ["Bug Reports", "Q&A"]
    assert ttk.Combobox.call_args.kwargs["state"] == "readonly"
    assert any(
        "Delete any files you do not want to send from this directory before continuing."
        in call.kwargs.get("text", "")
        and "review-location" in call.kwargs["text"]
        for call in ttk.Label.call_args_list
    )


@pytest.mark.parametrize(
    "selection", [None, [], ["support-context.json"], ["system-info.json"]]
)
def test_missing_empty_or_removed_diagnostics_cannot_reach_public_consent(
    github, monkeypatch, selection
):
    gh, root, info, client, _ = github
    stages = []

    def dialog(request):
        stages.append(request["mode"])
        assert request["include_files"] == []
        if selection == ["system-info.json"]:
            (root / "system-info.json").unlink()
        reply = {"request_id": request["request_id"], **request["context"]}
        if selection is not None:
            reply["include_files"] = selection
        return reply

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = gh.send_discussion("support-test", info)
    assert result["error_code"] == "files"
    assert result["message"] == "Select at least one diagnostic file before sending."
    assert stages == ["edit"]
    assert not (root / gh.JOURNAL_FILE).exists()
    client.create.assert_not_called()


def test_public_cli_yes_still_enters_backend_review(github, monkeypatch, capsys):
    gh, _, info, _, _ = github
    from argparse import Namespace

    bundles._active_bundles["support-test"] = info
    monkeypatch.setattr(bundles, "_load_last_bundle", lambda: "support-test")
    backend = Mock(
        return_value={"status": "error", "message": "User approval required"}
    )
    monkeypatch.setattr(gh, "send_discussion", backend)
    try:
        assert (
            bundles.support_command(
                Namespace(support_command="send", yes=True, json=True)
            )
            == 1
        )
        assert json.loads(capsys.readouterr().out)["status"] == "error"
        backend.assert_called_once_with("support-test", info)
    finally:
        bundles._active_bundles.pop("support-test", None)


def test_github_cli_url_in_human_and_json_output(github, monkeypatch, capsys):
    from argparse import Namespace

    gh, _, info, _, _ = github
    bundles._active_bundles["support-test"] = info
    monkeypatch.setattr(bundles, "_load_last_bundle", lambda: "support-test")
    try:
        assert (
            bundles.support_command(
                Namespace(support_command="send", yes=False, json=True)
            )
            == 0
        )
        result = json.loads(capsys.readouterr().out)
        assert result["discussion_url"] in bundles._format_send_human(result)
        assert "support-test" in bundles._active_bundles
    finally:
        bundles._active_bundles.pop("support-test", None)


def test_preparation_does_not_contact_github_and_output_is_the_review_source(
    github, monkeypatch, tmp_path
):
    gh, _, _, client, calls = github
    monkeypatch.setattr(bundles, "collect_cli_configs", lambda output_dir: [])
    monkeypatch.setattr(
        bundles, "_get_support_config", lambda: {"export_destination": gh.DESTINATION}
    )
    monkeypatch.setattr(
        "ai_guardian.doctor.Doctor.run_all", lambda self: SimpleNamespace(checks=[])
    )
    monkeypatch.setattr(
        "ai_guardian.smoke_test.SmokeTestRunner.run",
        lambda self: SimpleNamespace(phase1_passed=True, phase2_results=[]),
    )
    monkeypatch.setattr(
        "ai_guardian.reporting.metrics.MetricsComputer.compute",
        lambda self: SimpleNamespace(
            total_violations=0,
            by_type={},
            by_severity={},
            resolved_count=0,
            unresolved_count=0,
        ),
    )
    result = bundles.prepare_bundle(
        include_log=False,
        include_violations=False,
        output_path=str(tmp_path / "chosen"),
        title="A failure",
        description="Steps to reproduce",
    )
    bundle_id = result["bundle_id"]
    try:
        client.discover.assert_not_called()
        client.create.assert_not_called()
        root = Path(result["temp_path"])
        assert root == tmp_path / "chosen"
        assert (root / ".ai-read-deny").exists()
        (root / "system-info.json").unlink()
        assert bundles.send_bundle(bundle_id)["status"] == "sent"
        assert "system-info.json" not in calls[-1]["body"]
        assert root.exists()
    finally:
        bundles._active_bundles.pop(bundle_id, None)


def test_github_state_survives_process_reload_without_duplicate(github, monkeypatch):
    gh, _, info, client, _ = github
    bundles._active_bundles["support-restart"] = info
    bundles._persist_bundle_ref("support-restart", info)
    try:
        first = bundles.send_bundle("support-restart")
        bundles._active_bundles.pop("support-restart")
        assert bundles._load_last_bundle() == "support-restart"
        second = bundles.send_bundle("support-restart")
        assert first["discussion_url"] == second["discussion_url"]
        client.create.assert_called_once()
    finally:
        bundles._active_bundles.pop("support-restart", None)


def test_legacy_send_failure_keeps_reviewable_files(monkeypatch, tmp_path):
    info = {
        "temp_path": str(tmp_path),
        "destination": "s3://test-support",
        "created": datetime.now(timezone.utc).isoformat(),
    }
    bundles._active_bundles["support-legacy"] = info
    monkeypatch.setattr(
        bundles,
        "_send_to_s3",
        lambda *args: {"status": "error", "message": "Upload failed"},
    )
    try:
        assert bundles.send_bundle("support-legacy")["status"] == "error"
        assert tmp_path.exists()
        assert "support-legacy" in bundles._active_bundles
    finally:
        bundles._active_bundles.pop("support-legacy", None)


@pytest.mark.parametrize(
    "change", [None, "repository", "category", "author", "url", "malformed"]
)
def test_graphql_creation_uses_only_validated_identity_and_category(change):
    from ai_guardian.reporting import github_support as gh

    client = object.__new__(gh.GitHubClient)
    identity = {
        "repository_id": "R_support",
        "categories": {"bug-reports": "D_bug"},
        "login": "actual-reporter",
    }
    discussion = {
        "url": f"{gh.REPOSITORY_URL}/discussions/51",
        "repository": {"id": "R_support", "nameWithOwner": gh.REPOSITORY},
        "category": {"id": "D_bug", "slug": "bug-reports"},
        "author": {"login": "actual-reporter"},
    }
    if change == "repository":
        discussion["repository"]["nameWithOwner"] = "attacker/support"
    elif change == "category":
        discussion["category"]["slug"] = "polls"
    elif change == "author":
        discussion["author"]["login"] = "asserted-reporter"
    elif change == "url":
        discussion["url"] = "https://example.com/discussions/51"
    payload = {"createDiscussion": {"discussion": discussion}}
    if change == "malformed":
        payload = {"createDiscussion": "invalid"}
    client._graphql = Mock(return_value=payload)
    if change is not None:
        with pytest.raises(gh.GitHubError) as error:
            client.create(identity, "bug-reports", "title", "body")
        assert error.value.uncertain is True
    else:
        assert (
            client.create(identity, "bug-reports", "title", "body") == discussion["url"]
        )
    variables = client._graphql.call_args.args[1]["input"]
    assert variables == {
        "repositoryId": "R_support",
        "categoryId": "D_bug",
        "title": "title",
        "body": "body",
    }


def test_http_client_pins_credential_and_fixed_endpoint(monkeypatch):
    from ai_guardian.reporting import github_support as gh

    token = "synthetic-auth-value"
    command = Mock(return_value=SimpleNamespace(returncode=0, stdout=token))
    monkeypatch.setattr(gh.subprocess, "run", command)
    opener = Mock()
    # Use a real context-manager mock, not a live HTTP opener.
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"data": {}}'
    opener.open.return_value = response
    monkeypatch.setattr(gh, "build_opener", lambda *args: opener)
    monkeypatch.setenv("GH_HOST", "attacker.example")
    client = gh.GitHubClient()
    client._graphql("query {}")
    client._graphql("query {}")
    command.assert_called_once()
    for call in opener.open.call_args_list:
        request = call.args[0]
        assert request.full_url == "https://api.github.com/graphql"
        assert request.get_header("Authorization") == f"Bearer {token}"
        assert token not in request.data.decode()
    assert (
        gh._NoRedirect().redirect_request(
            None, None, 302, "", {}, "https://attacker.example"
        )
        is None
    )


def test_authentication_credential_is_scrubbed_even_from_filenames():
    from ai_guardian.reporting import github_support as gh
    from ai_guardian.reporting import github_gist as gist

    client = object.__new__(gh.GitHubClient)
    client._token = "synthetic-auth-value"
    title, body = gh._publication(
        "support-test",
        "https://gist.github.com/reporter/" + "a" * 32,
        {"title": client._token, "description": client._token},
        client,
    )
    files, _ = gist.prepare_files(
        {f"{client._token}.txt": client._token.encode()}, client
    )
    assert client._token not in json.dumps(files)
    assert client._token not in title + body
    assert "[REDACTED]" in title
    obfuscated = client._token[:5] + "\u200b" + client._token[5:]
    text, count = gh._publication_text(client, obfuscated)
    assert client._token not in text
    assert "[REDACTED]" in text
    assert count > 0


@pytest.mark.parametrize("json_output", [False, True])
def test_standalone_cli_works_without_agent_mcp_or_daemon(
    github, monkeypatch, capsys, json_output
):
    from ai_guardian import cli

    gh, _, info, client, dialogs = github
    bundles._active_bundles["support-standalone"] = info
    prepared = {
        "bundle_id": "support-standalone",
        **info,
        "public_warning": gh.PUBLIC_WARNING,
    }
    prepare = Mock(return_value=prepared)
    monkeypatch.setattr(bundles, "prepare_bundle", prepare)
    daemon = Mock(
        side_effect=AssertionError("Standalone support must not start a daemon")
    )
    monkeypatch.setattr(cli, "_ensure_daemon_started", daemon)
    monkeypatch.setitem(sys.modules, "mcp", None)
    monkeypatch.setitem(sys.modules, "ai_guardian.mcp.server", None)
    argv = ["ai-guardian", "support", "send", "--prepare", "--yes"]
    if json_output:
        argv.append("--json")
    monkeypatch.setattr(sys, "argv", argv)
    try:
        assert cli.main() == 0
        output = capsys.readouterr().out
        if json_output:
            assert json.loads(output)["discussion_url"] == client.create.return_value
        else:
            assert gh.PUBLIC_WARNING in output
            assert client.create.return_value in output
        daemon.assert_not_called()
        prepare.assert_called_once_with()
        assert [request["mode"] for request in dialogs] == [
            "delivery",
            "edit",
            "upload",
            "approve",
        ]
        client.create.assert_called_once()
    finally:
        bundles._active_bundles.pop("support-standalone", None)


def test_cli_parser_exposes_only_approved_categories(monkeypatch, capsys):
    from ai_guardian import cli

    prepare = Mock(
        return_value={"bundle_id": "support-parser", "temp_path": "local", "files": []}
    )
    monkeypatch.setattr(bundles, "prepare_bundle", prepare)
    daemon = Mock(side_effect=AssertionError("No daemon should be started"))
    monkeypatch.setattr(cli, "_ensure_daemon_started", daemon)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-guardian",
            "support",
            "prepare",
            "--category",
            "q-a",
            "--title",
            "Help question",
            "--description",
            "How do I configure this?",
            "--json",
        ],
    )
    assert cli.main() == 0
    prepare.assert_called_once_with(
        include_log=True,
        include_violations=True,
        output_path=None,
        title="Help question",
        description="How do I configure this?",
        category="q-a",
    )
    capsys.readouterr()
    prepare.reset_mock()
    for category in ("polls", "announcements", "D_arbitrary"):
        monkeypatch.setattr(
            sys, "argv", ["ai-guardian", "support", "prepare", "--category", category]
        )
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 2
    prepare.assert_not_called()
    daemon.assert_not_called()


def test_imported_github_bundle_is_protected_and_tracks_nested_files(
    github, monkeypatch
):
    gh, root, _, _, calls = github
    nested = root / "nested"
    nested.mkdir()
    (nested / "details.json").write_text('{"details":"reviewed"}')
    monkeypatch.setattr(
        bundles, "_get_support_config", lambda: {"export_destination": gh.DESTINATION}
    )
    bundle_id = bundles._load_bundle_from_path(str(root))
    try:
        assert (root / ".ai-read-deny").exists()
        assert bundles._active_bundles[bundle_id]["ttl_minutes"] == 30
        assert bundles.send_bundle(bundle_id)["status"] == "sent"
        assert "nested_details.json" in calls[-2]["body"]
        assert root.exists()
    finally:
        bundles._active_bundles.pop(bundle_id, None)
