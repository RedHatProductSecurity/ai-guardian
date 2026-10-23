"""Owned Gist upload consent, exact public linking and safe retry (synthetic only)."""

import json
import os
import subprocess
from datetime import datetime, timezone
from http.client import IncompleteRead
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError, URLError

import pytest

from ai_guardian.reporting import github_support as gh
from ai_guardian.reporting import github_gist as gist
from ai_guardian.reporting import support_bundle as bundles


@pytest.fixture
def flow(monkeypatch, tmp_path, support_github_transport):
    root = tmp_path / "reviewed"
    root.mkdir()
    (root / "diagnostic.json").write_text('{"detail":"Selected diagnostic only"}')
    (root / "omit.txt").write_text("Do not upload this")
    context = {
        "title": "A support question",
        "description": "My message stays here.",
        "category": "bug-reports",
    }
    (root / gh.CONTEXT_FILE).write_text(json.dumps(context))
    bundle = {
        "temp_path": str(root),
        "destination": gh.DESTINATION,
        "created": datetime.now(timezone.utc).isoformat(),
        "ttl_minutes": 30,
        "files": [{"name": path.name, "redactions": 0} for path in root.iterdir()],
    }
    client = Mock()
    client.discover.return_value = {
        "account_id": "U_test",
        "login": "reporter",
        "repository_id": "R_test",
        "categories": {"bug-reports": "D_bug", "q-a": "D_help"},
    }
    client.scrub.side_effect = lambda value: value
    client.create.return_value = f"{gh.REPOSITORY_URL}/discussions/42"
    remote = support_github_transport(client)
    monkeypatch.setattr(gh, "GitHubClient", lambda: client)
    requests = []

    def dialog(request):
        requests.append(request)
        if request["mode"] == "edit":
            return {
                "request_id": request["request_id"],
                **context,
                "include_files": ["diagnostic.json"],
            }
        return {"request_id": request["request_id"], "approved": True}

    monkeypatch.setattr(gh, "review_dialog", dialog)
    return SimpleNamespace(
        root=root,
        bundle=bundle,
        client=client,
        remote=remote,
        requests=requests,
        dialog=dialog,
    )


def test_gist_upload_is_separately_approved_and_only_linked_in_discussion(
    flow, monkeypatch
):
    def dialog(request):
        if request["mode"] == "upload":
            flow.client.gist_request.assert_not_called()
            flow.client.create.assert_not_called()
            assert "Selected diagnostic only" in request["body"]
            assert "Do not upload this" not in request["body"]
            assert (
                "unlisted" in request["warning"] and "not private" in request["warning"]
            )
        elif request["mode"] == "approve":
            assert flow.remote and flow.remote["public"] is False
            assert flow.remote["html_url"] in request["body"]
            assert "My message stays here." in request["body"]
            assert "Selected diagnostic only" not in request["body"]
            assert "Do not upload this" not in request["body"]
        return flow.dialog(request)

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = gh.send_discussion("support-owned-gist", flow.bundle)
    assert result["status"] == "sent"
    assert result["gist_url"] == flow.remote["html_url"]
    assert [request["mode"] for request in flow.requests] == [
        "edit",
        "upload",
        "approve",
    ]
    assert len(flow.remote["files"]) == 1
    assert gh.CONTEXT_FILE not in flow.remote["files"]
    assert "Selected diagnostic only" not in flow.client.create.call_args.args[3]


@pytest.mark.parametrize("stage", ["edit", "upload", "approve"])
def test_cancellation_reports_whether_files_have_already_been_uploaded(
    flow, monkeypatch, stage
):
    def dialog(request):
        return None if request["mode"] == stage else flow.dialog(request)

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = gh.send_discussion("support-owned-gist", flow.bundle)
    assert result["error_code"] == "cancelled"
    flow.client.create.assert_not_called()
    if stage == "approve":
        assert result["delivery_status"] == "gist_only"
        assert result["gist_url"] == flow.remote["html_url"]
        assert "already uploaded" in result["message"] and "delete" in result["message"]
        assert "Nothing was sent" not in result["message"]
    else:
        flow.client.gist_request.assert_not_called()
        assert "gist_url" not in result


def test_retry_reuses_uploaded_gist_but_requires_fresh_final_public_consent(flow):
    flow.client.create.side_effect = gh.GitHubError("Discussion denied.")
    first = gh.send_discussion("support-owned-gist", flow.bundle)
    assert first["delivery_status"] == "gist_only"
    flow.client.create.side_effect = None
    result = gh.send_discussion("support-owned-gist", flow.bundle)
    assert result["status"] == "sent" and result["gist_url"] == first["gist_url"]
    assert (
        sum(call.args[0] == "POST" for call in flow.client.gist_request.call_args_list)
        == 1
    )
    assert [request["mode"] for request in flow.requests].count("approve") == 2


def test_remote_gist_changes_during_final_consent_prevent_discussion(flow, monkeypatch):
    def dialog(request):
        response = flow.dialog(request)
        if request["mode"] == "approve":
            next(iter(flow.remote["files"].values()))["content"] = "Changed remotely"
        return response

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = gh.send_discussion("support-owned-gist", flow.bundle)
    assert result["status"] == "error" and result["gist_url"]
    flow.client.create.assert_not_called()


def test_ambiguous_gist_upload_is_never_retried_or_inlined(flow):
    flow.client.gist_request.side_effect = gh.GitHubError(
        "Unknown upload outcome.", uncertain=True
    )
    for _ in range(2):
        result = gh.send_discussion("support-owned-gist", flow.bundle)
        assert result["delivery_status"] == "uncertain"
    flow.client.gist_request.assert_called_once()
    flow.client.create.assert_not_called()


def test_forged_upload_reply_cannot_authorize_upload(flow, monkeypatch):
    def dialog(request):
        if request["mode"] == "upload":
            return {"request_id": "forged", "approved": True}
        return flow.dialog(request)

    monkeypatch.setattr(gh, "review_dialog", dialog)
    assert (
        gh.send_discussion("support-owned-gist", flow.bundle)["error_code"] == "changed"
    )
    flow.client.gist_request.assert_not_called()
    flow.client.create.assert_not_called()


def test_no_github_credentials_disables_and_backend_rejects_public_workflow(
    flow, monkeypatch
):
    monkeypatch.setattr(gh, "credentials_available", lambda: False)
    monkeypatch.setattr(
        bundles, "_active_bundles", {"support-no-credentials": flow.bundle}
    )

    def dialog(request):
        assert request["mode"] == "delivery" and request["github_available"] is False
        return {"request_id": request["request_id"], "delivery": "discussion"}

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = bundles.send_bundle("support-no-credentials")
    assert result["error_code"] == "authentication"
    flow.client.discover.assert_not_called()
    flow.client.gist_request.assert_not_called()


def test_direct_backend_also_requires_credentials_before_review(flow, monkeypatch):
    monkeypatch.setattr(gh, "credentials_available", lambda: False)
    result = gh.send_discussion("support-owned-gist", flow.bundle)
    assert result["error_code"] == "authentication"
    assert flow.requests == []
    flow.client.discover.assert_not_called()
    flow.client.gist_request.assert_not_called()


@pytest.mark.parametrize(
    "returncode,token,available",
    [
        (0, "synthetic-auth-value", True),
        (1, "", False),
        (0, "", False),
        (0, "not a token", False),
    ],
)
def test_credential_availability_is_local_fixed_host_and_never_prints_values(
    monkeypatch, caplog, capsys, returncode, token, available
):
    command = Mock(
        return_value=SimpleNamespace(
            returncode=returncode, stdout=token, stderr="sensitive failure detail"
        )
    )
    network = Mock(side_effect=AssertionError("Credential availability must be local"))
    monkeypatch.setattr(gh.subprocess, "run", command)
    monkeypatch.setattr(gh, "build_opener", network)
    assert gh.credentials_available() is available
    assert command.call_args.args[0] == [
        "gh",
        "auth",
        "token",
        "--hostname",
        "github.com",
    ]
    assert command.call_args.kwargs["capture_output"] is True
    assert caplog.text == "" and capsys.readouterr().out == ""
    network.assert_not_called()


@pytest.mark.parametrize(
    "error", [FileNotFoundError(), subprocess.TimeoutExpired("gh", 10)]
)
def test_missing_cli_or_credential_timeout_only_disables_github(monkeypatch, error):
    monkeypatch.setattr(gh.subprocess, "run", Mock(side_effect=error))
    assert gh.credentials_available() is False


def test_missing_known_gist_scope_is_rejected_before_upload():
    client = object.__new__(gh.GitHubClient)
    client._token = "synthetic-auth-value"
    response = MagicMock()
    response.__enter__.return_value.headers = {"X-OAuth-Scopes": "repo, read:org"}
    response.__enter__.return_value.read.return_value = b'{"data":{}}'
    client._opener = Mock()
    client._opener.open.return_value = response
    client._graphql("query {}")
    with pytest.raises(gh.GitHubError, match="lacks Gist permission") as error:
        client.check_gist_permission()
    assert error.value.code == "permissions"


@pytest.mark.parametrize("scopes", [None, "repo, gist, read:org"])
def test_gist_scope_check_tolerates_non_scope_credentials_and_allows_gist(scopes):
    client = object.__new__(gh.GitHubClient)
    client._token = "synthetic-auth-value"
    response = MagicMock()
    response.__enter__.return_value.headers = {"X-OAuth-Scopes": scopes}
    response.__enter__.return_value.read.return_value = b'{"data":{}}'
    client._opener = Mock()
    client._opener.open.return_value = response
    client._graphql("query {}")
    client.check_gist_permission()


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_gist_http_transport_uses_only_pinned_credentials_and_fixed_endpoint(method):
    client = object.__new__(gh.GitHubClient)
    client._token = "synthetic-auth-value"
    client._opener = Mock()
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"id":"aaaaa"}'
    client._opener.open.return_value = response
    payload = {
        "description": "Test",
        "public": False,
        "files": {"file.txt": {"content": "Diagnostic"}},
    }
    actual = client.gist_request(
        method,
        "a" * 32 if method == "GET" else "",
        payload=payload if method == "POST" else None,
    )
    assert actual == {"id": "aaaaa"}
    request = client._opener.open.call_args.args[0]
    assert request.full_url == "https://api.github.com/gists" + (
        "/" + "a" * 32 if method == "GET" else ""
    )
    assert request.get_method() == method
    assert request.get_header("Authorization") == "Bearer synthetic-auth-value"
    if method == "POST":
        assert json.loads(request.data) == payload
    else:
        assert request.data is None


@pytest.mark.parametrize(
    "method,identifier",
    [
        ("DELETE", "a" * 32),
        ("PATCH", "a" * 32),
        ("POST", "a" * 32),
        ("GET", ""),
        ("GET", "https://example.com/123"),
        ("GET", "../123"),
    ],
)
def test_gist_transport_refuses_caller_destinations_or_delete_operations(
    method, identifier
):
    client = object.__new__(gh.GitHubClient)
    client._opener = Mock()
    with pytest.raises(gh.GitHubError):
        client.gist_request(method, identifier)
    client._opener.open.assert_not_called()


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("status", [401, 403, 404, 422, 429, 500])
def test_gist_api_errors_are_credential_free_and_classify_mutation_uncertainty(
    method, status, caplog
):
    client = object.__new__(gh.GitHubClient)
    client._token = "synthetic-auth-value"
    client._opener = Mock()
    client._opener.open.side_effect = HTTPError(
        "https://api.github.com/gists", status, client._token, {}, None
    )
    with pytest.raises(gh.GitHubError) as error:
        client.gist_request(method, "a" * 32 if method == "GET" else "")
    assert client._token not in str(error.value) + caplog.text
    assert error.value.uncertain is (method == "POST" and status == 500)


@pytest.mark.parametrize(
    "response_bytes",
    [b"not json", b"[]", b"x" * (8_000_001)],
    ids=["invalid-json", "wrong-shape", "oversized"],
)
def test_unverifiable_gist_api_response_is_not_a_retryable_upload(response_bytes):
    client = object.__new__(gh.GitHubClient)
    client._token = "synthetic-auth-value"
    client._opener = Mock()
    response = MagicMock()
    response.__enter__.return_value.read.return_value = response_bytes
    client._opener.open.return_value = response
    with pytest.raises(gh.GitHubError) as error:
        client.gist_request("POST", payload={})
    assert error.value.uncertain is True


def test_network_failure_never_mistaken_for_a_safe_gist_retry():
    client = object.__new__(gh.GitHubClient)
    client._token = "synthetic-auth-value"
    client._opener = Mock()
    client._opener.open.side_effect = URLError(client._token)
    with pytest.raises(gh.GitHubError) as error:
        client.gist_request("POST", payload={})
    assert error.value.uncertain is True
    assert client._token not in str(error.value)


@pytest.mark.parametrize(
    "change",
    [
        "owner_id",
        "owner_login",
        "owner_type",
        "owner_missing",
        "url",
        "identifier",
        "public",
        "description",
        "truncated",
        "file_truncated",
        "content",
        "extra_file",
        "not_dict",
    ],
)
def test_unverified_upload_response_blocks_discussion_and_duplicate_gist(flow, change):
    transport = flow.client.gist_request.side_effect

    def request(method, *args, **kwargs):
        data = transport(method, *args, **kwargs)
        if change == "not_dict":
            return None
        if change.startswith("owner_"):
            if change == "owner_missing":
                data["owner"] = None
            else:
                key = {
                    "owner_id": "node_id",
                    "owner_login": "login",
                    "owner_type": "type",
                }[change]
                data["owner"][key] = "other"
        elif change == "url":
            data["html_url"] = "https://example.com/unsafe"
        elif change == "identifier":
            data["id"] = "../invalid"
        elif change == "public":
            data["public"] = True
        elif change == "description":
            data["description"] = "unexpected description"
        elif change == "truncated":
            data["truncated"] = True
        elif change == "file_truncated":
            next(iter(data["files"].values()))["truncated"] = True
        elif change == "content":
            next(iter(data["files"].values()))["content"] = "unexpected file content"
        elif change == "extra_file":
            data["files"]["unexpected.txt"] = {"content": "unreviewed"}
        return data

    flow.client.gist_request.side_effect = request
    first = gh.send_discussion("support-owned-gist", flow.bundle)
    second = gh.send_discussion("support-owned-gist", flow.bundle)
    assert first["delivery_status"] == second["delivery_status"] == "uncertain"
    if change in {
        "public",
        "description",
        "truncated",
        "file_truncated",
        "content",
        "extra_file",
    }:
        assert first["gist_url"] == second["gist_url"] == flow.remote["html_url"]
    else:
        assert "gist_url" not in first and "gist_url" not in second
    assert (
        sum(call.args[0] == "POST" for call in flow.client.gist_request.call_args_list)
        == 1
    )
    flow.client.create.assert_not_called()


@pytest.mark.parametrize("stage", ["upload", "approve"])
def test_expired_consent_cannot_upload_or_publish(flow, monkeypatch, stage):
    clock = [10]
    monkeypatch.setattr(gh, "monotonic", lambda: clock[0])
    monkeypatch.setattr(gist, "monotonic", lambda: clock[0])

    def dialog(request):
        reply = flow.dialog(request)
        if request["mode"] == stage:
            clock[0] += gh.APPROVAL_SECONDS + 1
        return reply

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = gh.send_discussion("support-owned-gist", flow.bundle)
    assert result["error_code"] == "changed"
    if stage == "upload":
        flow.client.gist_request.assert_not_called()
    else:
        assert result["delivery_status"] == "gist_only" and result["gist_url"]
    flow.client.create.assert_not_called()


@pytest.mark.parametrize("change", ["file", "account"])
def test_changes_during_gist_consent_cannot_authorize_upload(flow, monkeypatch, change):
    def dialog(request):
        reply = flow.dialog(request)
        if request["mode"] == "upload":
            if change == "file":
                (flow.root / "diagnostic.json").write_text("changed")
            else:
                flow.client.discover.return_value = {
                    **flow.client.discover.return_value,
                    "login": "other",
                }
        return reply

    monkeypatch.setattr(gh, "review_dialog", dialog)
    assert (
        gh.send_discussion("support-owned-gist", flow.bundle)["error_code"] == "changed"
    )
    flow.client.gist_request.assert_not_called()


def test_definitive_gist_rejection_can_retry_only_with_new_upload_consent(flow):
    transport = flow.client.gist_request.side_effect
    flow.client.gist_request.side_effect = gh.GitHubError(
        "Gist write permission denied.", code="permissions"
    )
    first = gh.send_discussion("support-owned-gist", flow.bundle)
    assert first["delivery_status"] == "not_published" and "gist_url" not in first
    assert not (flow.root / gist.JOURNAL_FILE).exists()
    flow.client.gist_request.side_effect = transport
    assert gh.send_discussion("support-owned-gist", flow.bundle)["status"] == "sent"
    assert [request["mode"] for request in flow.requests].count("upload") == 2


def test_partial_submission_recovers_across_processes_and_preserves_selection(
    flow, monkeypatch
):
    bid = "support-owned-gist"
    monkeypatch.setattr(bundles, "_active_bundles", {bid: flow.bundle})
    flow.client.create.side_effect = gh.GitHubError("Discussion denied.")
    first = gh.send_discussion(bid, flow.bundle)
    bundles._active_bundles.clear()
    assert bundles._load_last_bundle() == bid
    recovered = bundles._active_bundles[bid]
    assert recovered["include_files"] == ["diagnostic.json"]
    flow.client.create.side_effect = None
    assert gh.send_discussion(bid, recovered)["gist_url"] == first["gist_url"]
    assert (
        sum(call.args[0] == "POST" for call in flow.client.gist_request.call_args_list)
        == 1
    )
    assert [request["mode"] for request in flow.requests].count("upload") == 1
    assert gist.JOURNAL_FILE not in gh._read_files(recovered)
    if os.name != "nt":
        assert (flow.root / gist.JOURNAL_FILE).stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("change", ["account", "files", "remote_deleted"])
def test_existing_gist_is_never_reuploaded_when_retry_inputs_change(
    flow, monkeypatch, change
):
    flow.client.create.side_effect = gh.GitHubError("Discussion denied.")
    first = gh.send_discussion("support-owned-gist", flow.bundle)
    if change == "account":
        flow.client.discover.return_value = {
            **flow.client.discover.return_value,
            "login": "other",
        }
    elif change == "files":
        (flow.root / "diagnostic.json").write_text("changed")
    else:
        flow.client.gist_request.side_effect = gh.GitHubError(
            "Gist not found.", code="gist"
        )
    flow.client.create.reset_mock()
    result = gh.send_discussion("support-owned-gist", flow.bundle)
    assert result["status"] == "error" and result["gist_url"] == first["gist_url"]
    assert (
        sum(call.args[0] == "POST" for call in flow.client.gist_request.call_args_list)
        == 1
    )
    flow.client.create.assert_not_called()


def test_a_large_complete_configuration_uses_gist_not_discussion_body(flow):
    text = json.dumps({"details": "Ordinary detail. " * 9000, "last": "END-CONFIG"})
    (flow.root / "diagnostic.json").write_text(text)
    result = gh.send_discussion("support-owned-gist", flow.bundle)
    assert result["status"] == "sent"
    assert next(iter(flow.remote["files"].values()))["content"] == text
    assert "END-CONFIG" not in flow.client.create.call_args.args[3]


@pytest.mark.parametrize("count", [0, 101])
def test_empty_or_excessive_gist_file_counts_are_rejected(count):
    client = Mock()
    client.scrub.side_effect = lambda text: text
    with pytest.raises(gh.GitHubError) as error:
        gist.prepare_files(
            {f"{index}.txt": b"Ordinary diagnostic" for index in range(count)}, client
        )
    assert error.value.code == "manual_required"


def test_gist_diagnostics_use_the_same_doctor_first_alphabetical_order():
    client = Mock()
    client.scrub.side_effect = lambda text: text
    raw = {
        name: b"{}" for name in ("z-last.txt", "beta.json", "doctor.json", "Alpha.json")
    }
    files, summary = gist.prepare_files(raw, client)
    assert [item["name"] for item in summary] == [
        "doctor.json",
        "Alpha.json",
        "beta.json",
        "z-last.txt",
    ]
    assert list(files) == [
        "001-doctor.json",
        "002-Alpha.json",
        "003-beta.json",
        "004-z-last.txt",
    ]


def test_gist_names_are_inert_unique_and_contents_remain_complete():
    client = Mock()
    client.scrub.side_effect = lambda text: text
    raw = {
        "nested/README.md": b"[Rendered link](https://example.com)",
        "nested_README.md": b"Other full content",
    }
    files, summary = gist.prepare_files(raw, client)
    assert set(files) == {"001-nested_README.md.txt", "002-nested_README.md.txt"}
    assert [files[item["gist_name"]]["content"] for item in summary] == [
        raw[item["name"]].decode() for item in summary
    ]


@pytest.mark.parametrize(
    "journal",
    [
        "{invalid",
        "[]",
        '"scalar"',
        '{"status":"submitting"}',
        '{"status":"ready"}',
        " " * 9000,
    ],
)
def test_corrupt_or_incomplete_gist_receipt_fails_closed_without_upload(flow, journal):
    (flow.root / gist.JOURNAL_FILE).write_text(journal)
    assert (
        gh.send_discussion("support-owned-gist", flow.bundle)["error_code"]
        == "uncertain"
    )
    flow.client.gist_request.assert_not_called()


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_linked_journals_do_not_read_or_truncate_unrelated_files(flow, kind):
    source = flow.root.parent / "outside.txt"
    source.write_text("Unrelated original")
    receipt_path = flow.root / gist.JOURNAL_FILE
    try:
        if kind == "symlink":
            receipt_path.symlink_to(source)
        else:
            os.link(source, receipt_path)
    except OSError:
        pytest.skip("Links unavailable on this platform")
    with pytest.raises(gh.GitHubError):
        gist.receipt(flow.bundle)
    with pytest.raises((ValueError, OSError)):
        gh._write_journal(receipt_path, {"status": "ready"})
    assert source.read_text() == "Unrelated original"


def test_verified_gist_url_is_retained_if_receipt_write_fails(flow, monkeypatch):
    monkeypatch.setattr(
        gh, "_write_journal", Mock(side_effect=OSError("private failure detail"))
    )
    result = gh.send_discussion("support-owned-gist", flow.bundle)
    assert (
        result["delivery_status"] == "uncertain"
        and result["gist_url"] == flow.remote["html_url"]
    )
    assert "private failure detail" not in result["message"]
    assert "already uploaded" in result["message"]
    flow.client.create.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        OSError("private detail"),
        ValueError("private detail"),
        TypeError("private detail"),
    ],
)
def test_unexpected_mutation_failure_stays_uncertain_and_retains_known_gist(
    flow, error
):
    flow.client.create.side_effect = error
    first = gh.send_discussion("support-owned-gist", flow.bundle)
    second = gh.send_discussion("support-owned-gist", flow.bundle)
    assert first["delivery_status"] == second["delivery_status"] == "uncertain"
    assert first["gist_url"] == second["gist_url"] == flow.remote["html_url"]
    assert "private detail" not in first["message"]
    flow.client.create.assert_called_once()


def test_corrupt_discussion_receipt_keeps_separate_verified_gist_management_url(flow):
    flow.client.create.side_effect = gh.GitHubError("Known rejection")
    first = gh.send_discussion("support-owned-gist", flow.bundle)
    (flow.root / gh.JOURNAL_FILE).write_text("{invalid")
    second = gh.send_discussion("support-owned-gist", flow.bundle)
    assert second["delivery_status"] == "uncertain"
    assert second["gist_url"] == first["gist_url"]
    assert gist.recovery_url(flow.bundle) == first["gist_url"]
    flow.client.create.assert_called_once()


@pytest.mark.parametrize("method", ["gist", "discussion"])
def test_incomplete_http_response_is_classified_as_an_uncertain_mutation(method):
    client = object.__new__(gh.GitHubClient)
    client._token = "synthetic-auth-value"
    response = MagicMock()
    response.__enter__.return_value.read.side_effect = IncompleteRead(b"partial")
    client._opener = Mock()
    client._opener.open.return_value = response
    with pytest.raises(gh.GitHubError) as error:
        if method == "gist":
            client.gist_request("POST", payload={})
        else:
            client._graphql("mutation {}", mutation=True)
    assert error.value.uncertain is True


@pytest.mark.parametrize("delivery", ["zip", "cancel"])
def test_later_zip_or_cancellation_does_not_hide_an_earlier_gist(
    flow, monkeypatch, delivery
):
    flow.client.create.side_effect = gh.GitHubError("Known rejection")
    first = gh.send_discussion("support-owned-gist", flow.bundle)
    monkeypatch.setattr(bundles, "_active_bundles", {"support-owned-gist": flow.bundle})

    def dialog(request):
        if request["mode"] == "delivery":
            assert request["gist_url"] == first["gist_url"]
            if delivery == "cancel":
                return None
            return {"request_id": request["request_id"], "delivery": "zip"}
        assert request["mode"] == "bundle"
        return {
            "request_id": request["request_id"],
            "send": True,
            "include_files": ["diagnostic.json"],
            "description": "Please investigate this issue.",
        }

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = bundles.send_bundle("support-owned-gist")
    assert result["gist_url"] == first["gist_url"]
    assert (
        "earlier Gist was not deleted" in result["message"]
        or "existing Gist was not deleted" in result["message"]
    )
    assert "Nothing was sent" not in result["message"]
    assert result["delivery_status"] == (
        "zip_only" if delivery == "zip" else "gist_only"
    )
    assert (
        sum(call.args[0] == "POST" for call in flow.client.gist_request.call_args_list)
        == 1
    )


def test_oversized_discussion_message_is_rejected_before_any_gist_upload(
    flow, monkeypatch
):
    def dialog(request):
        reply = flow.dialog(request)
        reply["description"] = ("Ordinary support context. " * 3000)[
            : gh.MAX_BODY_BYTES - 10
        ]
        return reply

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = gh.send_discussion("support-owned-gist", flow.bundle)
    assert result["error_code"] == "context"
    assert "60,000-byte limit" in result["message"]
    flow.client.gist_request.assert_not_called()
    flow.client.create.assert_not_called()


def test_native_review_unavailable_after_upload_reports_known_gist(flow, monkeypatch):
    def dialog(request):
        if request["mode"] == "approve":
            raise gh.GitHubError(
                "Native review unavailable.", code="review_unavailable"
            )
        return flow.dialog(request)

    monkeypatch.setattr(gh, "review_dialog", dialog)
    result = gh.send_discussion("support-owned-gist", flow.bundle)
    assert result["error_code"] == "review_unavailable"
    assert result["delivery_status"] == "gist_only"
    assert result["gist_url"] == flow.remote["html_url"]
    flow.client.create.assert_not_called()
