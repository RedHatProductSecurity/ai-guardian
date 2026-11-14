"""Credential-free contracts for optional release documentation replacement.

All CLI, Git and publication I/O is mocked. Never contact a Google notebook.
"""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SKILL_DIR = Path(__file__).resolve().parents[2] / ".claude/skills/release"
sys.path.insert(0, str(SKILL_DIR))
import notebooklm_release as refresh_module
import release_helper

OLD_ID = "11111111-1111-4111-8111-111111111111"
NEW_ID = "22222222-2222-4222-8222-222222222222"
OTHER_ID = "33333333-3333-4333-8333-333333333333"
EXPORT = b"# Finalized release documentation\nVersion 1.2.3\n"


def source(source_id, title="notebooklm-export.md", status=2, **fields):
    return {
        "id": source_id,
        "title": title,
        "type": "uploaded_file",
        "url": None,
        "status": status,
        **fields,
    }


@pytest.fixture
def notebook_io(tmp_path, monkeypatch):
    """Model the audited nlm JSON interface, including mutations with lost replies."""
    repo = tmp_path / "checkout"
    repo.mkdir()
    common = repo / ".git"
    common.mkdir()
    io = SimpleNamespace(
        repo=repo,
        common=common,
        calls=[],
        sources=[source(OLD_ID), source(OTHER_ID, "unrelated-export.md")],
        version="nlm version 0.16.2\nYou are on the latest version.\n",
        help="NotebookLM Tools - Unified CLI for Google NotebookLM",
        auth="Authentication valid!\n  Profile: default\n  Account: private@example.invalid\n",
        export=EXPORT,
        failures={},
        outputs={},
        uploaded=False,
        deleted=False,
        status=2,
        title="AI Guardian",
        apply_rename=True,
        verify=Mock(),
    )

    def run(command, **kwargs):
        command = [str(item) for item in command]
        io.calls.append(command)
        assert kwargs.get("timeout", 0) > 0
        assert kwargs.get("cwd") == str(repo) or kwargs.get("cwd") == repo
        assert kwargs.get("stdin") == subprocess.DEVNULL
        if command[0] == "git":
            if "show" in command:
                assert command[-1] == "v1.2.3:docs/notebooklm-export.md"
                if "export" in io.failures:
                    return subprocess.CompletedProcess(
                        command, 1, b"", b"private error"
                    )
                return subprocess.CompletedProcess(command, 0, io.export, b"")
            assert command[-1] == "--git-common-dir"
            return subprocess.CompletedProcess(command, 0, str(common) + "\n", "")

        assert command[0] == "/mock/bin/nlm"
        assert kwargs["capture_output"] is True
        assert kwargs["env"]["NOTEBOOKLM_DISABLE_HEADLESS_REFRESH"] == "1"
        assert kwargs["env"]["NLM_NO_COLOR"] == "1"
        args = command[1:]
        stage = args[0] if args[0].startswith("--") else " ".join(args[:2])
        if stage == "source add":
            io.uploaded = True
            uploaded_file = Path(args[args.index("--file") + 1])
            assert uploaded_file.name == "notebooklm-export.md"
            assert uploaded_file.read_bytes() == io.export
            assert "--wait" in args and "--wait-timeout" in args and "--json" in args
            io.sources.append(source(NEW_ID, status=io.status))
        elif stage == "source delete":
            io.deleted = True
            assert args[2] == OLD_ID
            assert "--confirm" in args and "--json" in args
            io.sources = [entry for entry in io.sources if entry["id"] != OLD_ID]
        elif stage == "notebook rename":
            assert args[2:4] == [refresh_module.NOTEBOOK_ID, "AI Guardian v1.2.3"]
            assert args[-2:] == ["--profile", "default"]
            assert (
                "--json" not in args
            ), "The audited notebook rename has no --json option"
            assert OLD_ID not in [entry["id"] for entry in io.sources]
            assert source(NEW_ID) in io.sources
            if io.apply_rename:
                io.title = args[3]
        elif stage == "notebook get":
            assert args[2:] == [
                refresh_module.NOTEBOOK_ID,
                "--json",
                "--profile",
                "default",
            ]
        if stage.startswith("source "):
            assert args[-2:] == ["--profile", "default"]
            if stage != "source delete":
                assert args[2] == refresh_module.NOTEBOOK_ID
        failure = io.failures.get(stage)
        if callable(failure):
            failure = failure()
        if isinstance(failure, BaseException):
            raise failure
        if failure:
            return subprocess.CompletedProcess(command, 1, failure, "private stderr")
        output = io.outputs.get(stage)
        if output is None:
            output = {
                "--version": io.version,
                "--help": io.help,
                "login --check": io.auth,
                "source list": json.dumps(io.sources),
                "source add": json.dumps(
                    {
                        "source_type": "file",
                        "source_id": NEW_ID,
                        "title": "notebooklm-export.md",
                    }
                ),
                "source delete": json.dumps(
                    {
                        "status": "success",
                        "deleted_source_ids": [OLD_ID],
                        "deleted_count": 1,
                    }
                ),
                "notebook get": json.dumps(
                    {"notebook_id": refresh_module.NOTEBOOK_ID, "title": io.title}
                ),
                "notebook rename": "Renamed notebook (private output)",
            }[stage]
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(refresh_module.subprocess, "run", run)
    monkeypatch.setattr(refresh_module.shutil, "which", lambda name: "/mock/bin/nlm")
    io.refresher = refresh_module.NotebookLMRefresher("1.2.3", str(repo), io.verify)
    return io


def mutations(io):
    return [
        call
        for call in io.calls
        if call[1:3] in (["source", "add"], ["source", "delete"])
    ]


def test_upload_wait_verify_then_delete_only_exact_old_source(notebook_io):
    io = notebook_io
    result = io.refresher.refresh()

    assert result.startswith("updated")
    assert [entry["id"] for entry in io.sources] == [OTHER_ID, NEW_ID]
    assert [call[1:3] for call in mutations(io)] == [
        ["source", "add"],
        ["source", "delete"],
    ]
    upload, delete = map(io.calls.index, mutations(io))
    assert any(
        call[1:3] == ["source", "list"] for call in io.calls[upload + 1 : delete]
    )
    assert io.calls[-1][1:3] == ["notebook", "get"]
    io.verify.assert_called_once_with()
    assert not (
        io.repo / "docs"
    ).exists(), "Read the tag; never regenerate the working export"


def test_absent_export_created_once_and_retry_reuses_verified_source(notebook_io):
    io = notebook_io
    io.sources = [source(OTHER_ID, "notebooklm-export.md.bak")]
    assert io.refresher.refresh().startswith("updated")
    assert io.refresher.refresh().startswith("updated")
    assert len(mutations(io)) == 1
    assert [entry["id"] for entry in io.sources] == [OTHER_ID, NEW_ID]


def test_successful_replacement_retry_does_not_upload_again(notebook_io):
    io = notebook_io
    io.refresher.refresh()
    io.refresher.refresh()
    assert len(mutations(io)) == 2


def test_preview_is_completely_offline_and_does_not_write_state(notebook_io):
    io = notebook_io
    before = sorted(io.common.iterdir())
    result = io.refresher.refresh(dry_run=True)
    assert "dry-run" in result and "would refresh" in result
    assert refresh_module.NOTEBOOK_ID in result
    assert not io.calls
    io.verify.assert_not_called()
    assert sorted(io.common.iterdir()) == before


@pytest.mark.parametrize(
    "version", ["1.2.3-dev", "v1.2.3", "1.2.3-test1", "1.2.3rc1", "01.2.3"]
)
def test_rejects_nonproduction_versions_before_io(version, notebook_io):
    with pytest.raises(ValueError, match="stable release"):
        refresh_module.NotebookLMRefresher(
            version, str(notebook_io.repo), notebook_io.verify
        )
    assert not notebook_io.calls


def test_missing_cli_skips_without_authentication_or_publication(
    monkeypatch, notebook_io
):
    io = notebook_io
    monkeypatch.setattr(refresh_module.shutil, "which", lambda name: None)
    assert "skipped (nlm not installed" in io.refresher.refresh()
    assert not io.calls
    io.verify.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "nlm version 0.16.1"),
        ("version", "nlm version 0.17.0"),
        ("version", "other program 0.16.2"),
        ("help", "Unrelated executable named nlm"),
    ],
)
def test_incompatible_cli_skips_before_authentication(field, value, notebook_io):
    io = notebook_io
    setattr(io, field, value)
    assert "skipped" in io.refresher.refresh()
    assert not any(call[1:3] == ["login", "--check"] for call in io.calls)
    assert not mutations(io)


@pytest.mark.parametrize(
    "failure",
    [
        "No saved credentials found",
        "Credentials have expired",
        "network connection failed",
        subprocess.TimeoutExpired("nlm", 60),
    ],
)
def test_authentication_failure_is_nonfatal_and_never_starts_login(
    failure, notebook_io
):
    io = notebook_io
    io.failures["login --check"] = failure
    result = io.refresher.refresh()
    assert result.startswith("skipped")
    assert "no login attempted" in result
    assert not mutations(io)
    assert all(
        call[1:3] == ["login", "--check"] for call in io.calls if call[1:2] == ["login"]
    )


@pytest.mark.parametrize(
    "auth",
    [
        "",
        "Authentication valid!",
        "Profile: default",
        "Authentication valid!\nProfile: -unsafe",
    ],
)
def test_malformed_authentication_output_never_authorizes_mutation(auth, notebook_io):
    io = notebook_io
    io.auth = auth
    assert io.refresher.refresh().startswith("skipped")
    assert not mutations(io)


def test_testpypi_or_unpublished_release_never_mutates_notebook(notebook_io):
    io = notebook_io
    io.verify.side_effect = release_helper.AnnouncementError(
        "Production publication is unavailable"
    )
    with pytest.raises(release_helper.AnnouncementError):
        io.refresher.refresh()
    assert not mutations(io)


@pytest.mark.parametrize("missing", [True, False], ids=["missing", "empty"])
def test_missing_or_empty_tagged_export_preserves_existing_source(missing, notebook_io):
    io = notebook_io
    if missing:
        io.failures["export"] = "missing"
    else:
        io.export = b""
    with pytest.raises(refresh_module.RefreshError, match="export"):
        io.refresher.refresh()
    assert not mutations(io)


@pytest.mark.parametrize(
    "output",
    [
        "not JSON",
        "{}",
        "null",
        '{"error":"inaccessible notebook"}',
        '[{"id":"-alias","title":"notebooklm-export.md"}]',
        json.dumps([source(OLD_ID), source(OLD_ID)]),
    ],
)
def test_invalid_source_discovery_is_not_treated_as_an_empty_notebook(
    output, notebook_io
):
    io = notebook_io
    io.outputs["source list"] = output
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    assert not mutations(io)


@pytest.mark.parametrize(
    "failure", ["notebook not found", "Permission denied", "network connection failed"]
)
def test_inaccessible_notebook_does_not_upload_or_delete(failure, notebook_io):
    io = notebook_io
    io.failures["source list"] = failure
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    assert not mutations(io)


def test_ambiguous_exact_title_leaves_every_source_untouched(notebook_io):
    io = notebook_io
    io.sources.append(source(NEW_ID))
    with pytest.raises(refresh_module.RefreshError, match="ambiguous"):
        io.refresher.refresh()
    assert not mutations(io)


def test_web_source_with_matching_title_is_not_an_uploaded_export(notebook_io):
    io = notebook_io
    io.sources[0].update(type="web_page", url="https://example.invalid/docs")
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    assert not mutations(io)


@pytest.mark.parametrize(
    "failure",
    [
        "Source limit reached",
        "quota exceeded",
        "processing failed",
        "network request failed",
        subprocess.TimeoutExpired("nlm", 720),
        OSError("private credential-like error"),
    ],
)
def test_failed_or_uncertain_upload_never_deletes_or_blindly_reuploads(
    failure, notebook_io
):
    io = notebook_io
    io.failures["source add"] = failure
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    assert not io.deleted
    assert OLD_ID in [entry["id"] for entry in io.sources]
    io.failures.clear()
    with pytest.raises(refresh_module.RefreshError, match="unconfirmed"):
        io.refresher.refresh()
    assert len(mutations(io)) == 1


@pytest.mark.parametrize(
    "receipt",
    [
        "{}",
        "not JSON",
        '{"source_type":"file","source_id":"-bad"}',
        json.dumps(
            {
                "source_type": "file",
                "source_id": OLD_ID,
                "title": "notebooklm-export.md",
            }
        ),
    ],
)
def test_invalid_upload_receipt_never_removes_old_source(receipt, notebook_io):
    io = notebook_io
    io.outputs["source add"] = receipt
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    assert not io.deleted


@pytest.mark.parametrize("status", [None, 1, 3, 5, True, "ready"])
def test_processing_must_be_confirmed_before_old_source_is_deleted(status, notebook_io):
    io = notebook_io
    io.status = status
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    assert not io.deleted


def test_processing_retry_reuses_uploaded_id_not_another_upload(notebook_io):
    io = notebook_io
    io.status = 1
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    io.sources[-1]["status"] = 2
    assert io.refresher.refresh().startswith("updated")
    assert len(mutations(io)) == 2


@pytest.mark.parametrize(
    "failure", ["network request failed", subprocess.TimeoutExpired("nlm", 60)]
)
def test_lost_delete_reply_is_reconciled_on_retry_without_upload(failure, notebook_io):
    io = notebook_io
    io.failures["source delete"] = failure
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    io.failures.clear()
    assert io.refresher.refresh().startswith("updated")
    assert len(mutations(io)) == 2
    assert [entry["id"] for entry in io.sources] == [OTHER_ID, NEW_ID]


def test_delete_retry_targets_only_the_still_present_old_id(notebook_io):
    io = notebook_io
    io.outputs["source delete"] = "not JSON"
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    io.sources.insert(
        0, source(OLD_ID)
    )  # Simulate deletion not actually being committed.
    io.outputs.clear()
    assert io.refresher.refresh().startswith("updated")
    assert sum(call[1:3] == ["source", "add"] for call in io.calls) == 1
    assert all(
        call[3] == OLD_ID for call in io.calls if call[1:3] == ["source", "delete"]
    )


def test_journal_has_only_identity_metadata_not_document_or_account_contents(
    notebook_io,
):
    io = notebook_io
    io.refresher.refresh()
    journal = (io.common / refresh_module.STATE_NAME).read_text(encoding="utf-8")
    assert "Finalized release documentation" not in journal
    assert "private@example.invalid" not in journal
    assert "cookies" not in journal
    assert OLD_ID in journal and NEW_ID in journal


def test_corrupt_state_fails_without_remote_mutation(notebook_io):
    io = notebook_io
    (io.common / refresh_module.STATE_NAME).write_text("not JSON")
    with pytest.raises(refresh_module.RefreshError, match="state"):
        io.refresher.refresh()
    assert not mutations(io)


def test_pending_different_release_cannot_be_overwritten(notebook_io):
    io = notebook_io
    io.status = 1
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    io.export = EXPORT + b"changed"
    with pytest.raises(refresh_module.RefreshError, match="pending"):
        io.refresher.refresh()
    assert len(mutations(io)) == 1


@pytest.mark.parametrize("dry_run", [False, True])
def test_refresh_cli_bypasses_version_management_and_prints_safe_status(
    dry_run, notebook_io, monkeypatch, capsys
):
    io = notebook_io
    monkeypatch.setattr(
        release_helper,
        "ReleaseHelper",
        Mock(side_effect=AssertionError("must not initialize")),
    )
    monkeypatch.setattr(
        release_helper.ReleaseAnnouncer, "_verify_publication", io.verify
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "helper",
            "--repo",
            str(io.repo),
            "refresh-notebooklm",
            "1.2.3",
            *(["--dry-run"] if dry_run else []),
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        release_helper.main()
    assert exit_info.value.code == 0
    output = capsys.readouterr()
    assert "updated" in output.out or "dry-run" in output.out
    assert "private@example.invalid" not in output.out + output.err
    assert "Finalized release documentation" not in output.out + output.err


def test_cli_failure_hides_raw_provider_errors_and_never_claims_success(
    notebook_io, monkeypatch, capsys
):
    io = notebook_io
    monkeypatch.setattr(
        release_helper.ReleaseAnnouncer, "_verify_publication", io.verify
    )
    io.failures["source add"] = "quota exceeded: private credential-like error"
    monkeypatch.setattr(
        sys, "argv", ["helper", "--repo", str(io.repo), "refresh-notebooklm", "1.2.3"]
    )
    with pytest.raises(SystemExit) as exit_info:
        release_helper.main()
    assert exit_info.value.code == 1
    output = capsys.readouterr()
    assert "failed/unconfirmed" in output.err
    assert "quota" in output.err
    assert "private credential-like" not in output.out + output.err
    assert "updated" not in output.out


def notebook_renames(io):
    return [call for call in io.calls if call[1:3] == ["notebook", "rename"]]


def test_notebook_title_contains_exact_release_version_after_verified_replacement(
    notebook_io,
):
    io = notebook_io
    assert io.refresher.refresh().startswith("updated")
    assert io.title == "AI Guardian v1.2.3"
    rename = notebook_renames(io)[0]
    delete = next(call for call in io.calls if call[1:3] == ["source", "delete"])
    between = io.calls[io.calls.index(delete) + 1 : io.calls.index(rename)]
    assert any(call[1:3] == ["source", "list"] for call in between)
    assert io.calls[-1][1:3] == ["notebook", "get"]
    assert (io.common / refresh_module.STATE_NAME).is_file()


def test_already_versioned_notebook_is_not_renamed_again(notebook_io):
    io = notebook_io
    io.title = "AI Guardian v1.2.3"
    io.refresher.refresh()
    io.refresher.refresh()
    assert not notebook_renames(io)
    assert len(mutations(io)) == 2


def test_preview_describes_notebook_rename_without_contacting_service(notebook_io):
    io = notebook_io
    assert "AI Guardian v1.2.3" in io.refresher.refresh(dry_run=True)
    assert io.title == "AI Guardian"
    assert not io.calls


def test_failed_upload_does_not_rename_notebook(notebook_io):
    io = notebook_io
    io.failures["source add"] = "quota exceeded"
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    assert not notebook_renames(io)
    assert io.title == "AI Guardian"


@pytest.mark.parametrize("applied", [True, False], ids=["lost-reply", "not-committed"])
def test_notebook_rename_failure_is_recoverable_without_reupload(applied, notebook_io):
    io = notebook_io
    io.apply_rename = applied
    io.failures["notebook rename"] = subprocess.TimeoutExpired("nlm", 60)
    with pytest.raises(refresh_module.RefreshError, match="rename"):
        io.refresher.refresh()
    io.apply_rename = True
    io.failures.clear()
    assert io.refresher.refresh().startswith("updated")
    assert io.title == "AI Guardian v1.2.3"
    assert len(mutations(io)) == 2
    assert len(notebook_renames(io)) == (1 if applied else 2)


@pytest.mark.parametrize(
    "output",
    ["not JSON", "{}", json.dumps({"notebook_id": OTHER_ID, "title": "AI Guardian"})],
)
def test_invalid_notebook_identity_prevents_rename_and_remains_recoverable(
    output, notebook_io
):
    io = notebook_io
    io.outputs["notebook get"] = output
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    assert not notebook_renames(io)
    io.outputs.clear()
    assert io.refresher.refresh().startswith("updated")
    assert len(mutations(io)) == 2


def test_successful_rename_receipt_is_not_sufficient_without_readback(notebook_io):
    io = notebook_io
    io.apply_rename = False
    with pytest.raises(refresh_module.RefreshError, match="title"):
        io.refresher.refresh()
    assert (
        json.loads((io.common / refresh_module.STATE_NAME).read_text())["phase"]
        == "rename_pending"
    )
    assert len(mutations(io)) == 2


@pytest.mark.parametrize("after_delete", [False, True])
def test_discovery_failure_after_upload_or_delete_retries_without_upload(
    after_delete, notebook_io
):
    io = notebook_io
    io.failures["source list"] = lambda: (
        "network failed" if (io.deleted if after_delete else io.uploaded) else None
    )
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    if not after_delete:
        assert not io.deleted
    io.failures.clear()
    assert io.refresher.refresh().startswith("updated")
    assert len(mutations(io)) == 2


def test_concurrent_refresh_does_not_upload(notebook_io):
    io = notebook_io
    with refresh_module._locked(io.common / refresh_module.STATE_NAME):
        with pytest.raises(refresh_module.RefreshError, match="lock"):
            io.refresher.refresh()
    assert not mutations(io)


def test_windows_lock_uses_one_byte_nonblocking_region(notebook_io, monkeypatch):
    """Exercise the Windows boundary with a mock CRT, not Bash or a Windows shell."""
    locking = Mock()
    monkeypatch.setitem(
        sys.modules, "msvcrt", SimpleNamespace(locking=locking, LK_NBLCK=2)
    )
    monkeypatch.setattr(refresh_module, "sys", SimpleNamespace(platform="win32"))
    with refresh_module._locked(notebook_io.common / refresh_module.STATE_NAME):
        pass
    assert locking.call_count == 1
    assert locking.call_args.args[1:] == (2, 1)


def test_state_write_failure_prevents_upload(notebook_io, monkeypatch):
    io = notebook_io
    monkeypatch.setattr(
        io.refresher,
        "_save",
        Mock(side_effect=refresh_module.RefreshError("state write failed")),
    )
    with pytest.raises(refresh_module.RefreshError, match="state"):
        io.refresher.refresh()
    assert not mutations(io)


def test_receipt_persistence_failure_keeps_old_source_and_blocks_blind_retry(
    notebook_io, monkeypatch
):
    io = notebook_io
    original_save = io.refresher._save
    writes = 0

    def save(state_file, state):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise refresh_module.RefreshError("state write failed")
        original_save(state_file, state)

    monkeypatch.setattr(io.refresher, "_save", save)
    with pytest.raises(refresh_module.RefreshError, match="state"):
        io.refresher.refresh()
    assert not io.deleted
    monkeypatch.setattr(io.refresher, "_save", original_save)
    with pytest.raises(refresh_module.RefreshError, match="unconfirmed"):
        io.refresher.refresh()
    assert len(mutations(io)) == 1


@pytest.mark.parametrize(
    "field", ["old_id", "new_id", "baseline", "notebook", "digest", "phase"]
)
def test_incomplete_saved_state_never_authorizes_mutations(field, notebook_io):
    io = notebook_io
    io.refresher.refresh()
    state_file = io.common / refresh_module.STATE_NAME
    state = json.loads(state_file.read_text())
    del state[field]
    state_file.write_text(json.dumps(state))
    before = len(mutations(io))
    with pytest.raises(refresh_module.RefreshError, match="state"):
        io.refresher.refresh()
    assert len(mutations(io)) == before


def test_older_version_retry_does_not_downgrade_notebook(notebook_io):
    io = notebook_io
    io.refresher.refresh()
    state_file = io.common / refresh_module.STATE_NAME
    state = json.loads(state_file.read_text())
    state["version"] = "1.2.4"
    state_file.write_text(json.dumps(state))
    with pytest.raises(refresh_module.RefreshError, match="newer release"):
        io.refresher.refresh()
    assert len(mutations(io)) == 2
    assert len(notebook_renames(io)) == 1


def test_completed_release_export_cannot_silently_change_under_same_tag(notebook_io):
    io = notebook_io
    io.refresher.refresh()
    io.export += b"changed after release"
    with pytest.raises(refresh_module.RefreshError, match="changed"):
        io.refresher.refresh()
    assert len(mutations(io)) == 2


def test_pending_refresh_does_not_switch_to_a_different_profile(notebook_io):
    io = notebook_io
    io.status = 1
    with pytest.raises(refresh_module.RefreshError):
        io.refresher.refresh()
    io.auth = "Authentication valid!\n  Profile: another\n"
    with pytest.raises(refresh_module.RefreshError, match="pending"):
        io.refresher.refresh()
    assert len(mutations(io)) == 1


def test_uncaught_cli_error_is_reported_without_raw_diagnostics(
    notebook_io, monkeypatch, capsys
):
    io = notebook_io
    monkeypatch.setattr(
        refresh_module.NotebookLMRefresher,
        "refresh",
        Mock(side_effect=RuntimeError("private contents")),
    )
    monkeypatch.setattr(sys, "argv", ["helper", "refresh-notebooklm", "1.2.3"])
    with pytest.raises(SystemExit) as exit_info:
        release_helper.main()
    assert exit_info.value.code == 1
    output = capsys.readouterr()
    assert "failed/unconfirmed" in output.err
    assert "private contents" not in output.out + output.err
