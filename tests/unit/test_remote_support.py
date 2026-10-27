"""Source isolation, inert wire validation and desktop-owned support imports."""

import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from ai_guardian.reporting import remote_support as remote
from ai_guardian.reporting import support_bundle as bundles
from tests.fixtures.support_remote import diagnostic, diagnostics


@pytest.fixture
def desktop(monkeypatch, tmp_path):
    monkeypatch.setattr(
        bundles,
        "_get_support_config",
        lambda: {
            "export_destination": str(tmp_path / "desktop-export"),
        },
    )
    monkeypatch.setattr(bundles, "_active_bundles", {})
    monkeypatch.setattr(bundles, "_persist_bundle_ref", Mock(return_value=True))
    return tmp_path


def test_import_uses_desktop_destination_and_retains_bound_source(desktop):
    prepared = remote.import_diagnostics(diagnostics(), "VM one (ssh)")
    root = Path(prepared["temp_path"])
    try:
        assert prepared["destination"] == str(desktop / "desktop-export")
        assert prepared["source"] == "VM one (ssh)"
        assert (root / ".ai-read-deny").is_file()
        source = json.loads((root / remote.PROVENANCE_FILE).read_text())
        assert source["selected_source"] == "VM one (ssh)"
        assert (
            json.loads((root / "ai-guardian.json").read_text())["diagnostic_marker"]
            == "remote-only"
        )
        if os.name != "nt":
            assert root.stat().st_mode & 0o777 == 0o700
            assert (root / "ai-guardian.json").stat().st_mode & 0o777 == 0o600
    finally:
        bundles._cleanup_bundle(prepared["bundle_id"])


@pytest.mark.parametrize(
    "name",
    [
        "../outside.json",
        "/absolute.json",
        "C:\\outside.json",
        "projects/../../x.json",
        "projects\\x.json",
        ".github-gist.json",
        ".ai-read-deny",
        "support-context.json",
        "CON.json",
        "lpt1.log",
        "odd\x00.json",
        "file.json/extra",
        "file:stream.json",
    ],
)
def test_unsafe_names_never_allocate_a_review_directory(monkeypatch, name):
    payload = diagnostics()
    payload["files"][0]["name"] = name
    allocate = Mock(side_effect=AssertionError("No file writes before validation"))
    monkeypatch.setattr(remote.tempfile, "mkdtemp", allocate)
    with pytest.raises(remote.SupportCollectionError, match="malformed, unsafe"):
        remote.import_diagnostics(payload, "VM (manual)")
    allocate.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(destination="https://untrusted.invalid"),
        lambda p: p.update(schema=True),
        lambda p: p["files"].append(p["files"][0]),
        lambda p: p["files"].append({**p["files"][0], "name": "AI-GUARDIAN.json"}),
        lambda p: p["files"][0].update(sha256="incorrect"),
        lambda p: p["files"][0].update(data="not base64"),
        lambda p: p["files"][0].update(type="symlink", target="/outside"),
        lambda p: p["files"][0].update(truncated=True),
        lambda p: p["files"].pop(),
        lambda p: p["files"].append(diagnostic("broken.json", '{"cropped":')),
        lambda p: p["files"].append(diagnostic("binary.log", "safe", redactions=-1)),
    ],
)
def test_malformed_or_authority_bearing_envelopes_are_rejected(change):
    payload = diagnostics()
    change(payload)
    with pytest.raises(remote.SupportCollectionError):
        remote.validate_diagnostics(payload)


@pytest.mark.parametrize(
    "limit", ["MAX_FILE_BYTES", "MAX_TOTAL_BYTES", "MAX_WIRE_BYTES", "MAX_FILES"]
)
def test_transfer_limits_refuse_without_cropping(monkeypatch, limit):
    payload = diagnostics()
    monkeypatch.setattr(remote, limit, 1)
    with pytest.raises(remote.SupportCollectionError):
        remote.validate_diagnostics(payload)


def test_receipt_resanitizes_credential_fields_and_keeps_complete_json(desktop):
    payload = diagnostics()
    payload["files"].append(
        diagnostic(
            "extra.json",
            {
                "auth_token": "synthetic-credential-value",
                "last_field": "complete",
                "credentials": {"opaque": "synthetic-private-value"},
            },
        )
    )
    prepared = remote.import_diagnostics(payload, "VM (manual)")
    try:
        value = json.loads((Path(prepared["temp_path"]) / "extra.json").read_text())
        assert value == {
            "auth_token": "[REDACTED]",
            "last_field": "complete",
            "credentials": "[REDACTED]",
        }
    finally:
        bundles._cleanup_bundle(prepared["bundle_id"])


def test_source_collection_uses_source_roots_projects_and_explicit_omissions(
    monkeypatch, tmp_path
):
    source_config = tmp_path / "source-config"
    source_state = tmp_path / "source-state"
    project = tmp_path / "source-project" / ".ai-guardian" / "ai-guardian.json"
    project.parent.mkdir(parents=True)
    project.write_text(json.dumps({"project_marker": "SOURCE PROJECT"}))
    source_config.mkdir()
    source_state.mkdir()
    (source_config / "ai-guardian.json").write_text(
        json.dumps(
            {
                "root_marker": "SOURCE ROOT",
                "daemon": {"auth_token": "synthetic-private-value"},
            }
        )
    )
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(source_config))
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(source_state))
    monkeypatch.setattr(bundles, "collect_cli_configs", lambda root: [])
    monkeypatch.setattr(
        bundles,
        "_get_support_config",
        Mock(side_effect=AssertionError("Never read remote publication settings")),
    )
    monkeypatch.setattr(
        bundles,
        "_persist_bundle_ref",
        Mock(side_effect=AssertionError("Never save remote review references")),
    )
    monkeypatch.setattr(
        "ai_guardian.doctor.Doctor.run_all",
        Mock(side_effect=RuntimeError("unavailable")),
    )
    monkeypatch.setattr(
        "ai_guardian.smoke_test.SmokeTestRunner.run",
        lambda self: SimpleNamespace(phase1_passed=True, phase2_results=[]),
    )
    monkeypatch.setattr(bundles, "_get_sanitized_log", lambda: ("", 0))
    monkeypatch.setattr(bundles, "_get_recent_support_violations", lambda: [])
    payload = remote.collect_diagnostics(
        "Source VM", [project], daemon_version="source-running-version"
    )
    files = {
        item["name"]: base64.b64decode(item["data"]).decode()
        for item in payload["files"]
    }
    assert "SOURCE ROOT" in files["ai-guardian.json"]
    assert "SOURCE PROJECT" in files["projects/project-001.json"]
    assert "synthetic-private-value" not in json.dumps(payload)
    assert "support-context.json" not in files
    provenance = json.loads(files[remote.PROVENANCE_FILE])
    assert provenance["daemon_name"] == "Source VM"
    assert provenance["version"] == "source-running-version"
    assert provenance["collector_version"]
    assert any("doctor.json" in note for note in provenance["omissions"])
    assert str(source_config) in provenance["config_root"]


def test_two_sources_remain_distinct_and_cannot_set_desktop_context(
    desktop, monkeypatch
):
    monkeypatch.setattr(bundles, "_get_support_config", lambda: {})
    first = remote.import_diagnostics(diagnostics("one"), "One (ssh)")
    second = remote.import_diagnostics(diagnostics("two"), "Two (kubernetes)")
    try:
        assert first["bundle_id"] != second["bundle_id"]
        for prepared, marker in [(first, "one"), (second, "two")]:
            root = Path(prepared["temp_path"])
            assert (
                json.loads((root / "ai-guardian.json").read_text())["diagnostic_marker"]
                == marker
            )
            assert (
                json.loads((root / "support-context.json").read_text())["title"] == ""
            )
            assert prepared["destination"] == "github-discussions"
    finally:
        bundles._cleanup_bundle(first["bundle_id"])
        bundles._cleanup_bundle(second["bundle_id"])


def test_import_reference_failure_does_not_register_partial_data(desktop, monkeypatch):
    monkeypatch.setattr(bundles, "_persist_bundle_ref", lambda *args: False)
    with pytest.raises(remote.SupportCollectionError, match="Nothing was sent"):
        remote.import_diagnostics(diagnostics(), "VM (ssh)")
    assert bundles._active_bundles == {}


def test_source_cli_logs_audit_and_session_state_never_use_desktop_fixtures(
    monkeypatch, tmp_path
):
    """Exercise actual source collectors, with distinct desktop/source markers."""
    from ai_guardian.reporting import cli_diagnostics

    source = tmp_path / "source"
    source.mkdir()
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    for root, marker in [
        (source, "SOURCE DIAGNOSTICS"),
        (desktop, "DESKTOP DIAGNOSTICS"),
    ]:
        (root / "ai-guardian.json").write_text(json.dumps({"marker": marker}))
        timestamp = datetime.now(timezone.utc).isoformat()
        (root / "ai-guardian.log").write_text(f"{timestamp} INFO {marker}\n")
        (root / "violations.jsonl").write_text(
            json.dumps(
                {
                    "timestamp": timestamp,
                    "violation_type": "test",
                    "context": {"marker": marker},
                }
            )
            + "\n"
        )
        (root / "session_state.json").write_text(
            json.dumps({"sessions": {}, "marker": marker})
        )
        (root / "settings.json").write_text(
            json.dumps({"marker": marker, "env": {"AUTH": "synthetic-private-value"}})
        )
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(source))
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(source))
    monkeypatch.setattr(
        cli_diagnostics,
        "_config_sources",
        lambda: [("test", "user", "settings", source / "settings.json")],
    )
    monkeypatch.setattr(
        "ai_guardian.doctor.Doctor.run_all", lambda self: SimpleNamespace(checks=[])
    )
    monkeypatch.setattr(
        "ai_guardian.smoke_test.SmokeTestRunner.run",
        lambda self: SimpleNamespace(phase1_passed=True, phase2_results=[]),
    )
    payload = remote.collect_diagnostics("Source VM", [])
    files = {item["name"]: text for item, text in remote.validate_diagnostics(payload)}
    for name in (
        "ai-guardian.json",
        "cli-test-user-settings.json",
        "ai-guardian.log",
        "violations.jsonl",
        "session_state.json",
    ):
        assert "SOURCE DIAGNOSTICS" in files[name]
    assert "DESKTOP DIAGNOSTICS" not in "\n".join(files.values())
    assert "synthetic-private-value" not in "\n".join(files.values())
    assert json.loads(files[remote.PROVENANCE_FILE])["state_root"] == str(source)


def test_complete_structured_files_and_explicit_log_excerpts_survive_import(desktop):
    complete = {
        "records": ["normal diagnostic text" for _ in range(5000)],
        "last_field": "COMPLETE END",
    }
    payload = diagnostics()
    payload["files"].extend(
        [
            diagnostic("complete.json", complete),
            diagnostic(
                "ai-guardian.log",
                "[Truncated: source log excerpt]\nnewest source log record\n",
                truncated=True,
            ),
        ]
    )
    prepared = remote.import_diagnostics(payload, "Source VM (ssh)")
    try:
        root = Path(prepared["temp_path"])
        assert json.loads((root / "complete.json").read_text()) == complete
        assert (
            root / "ai-guardian.log"
        ).read_text() == "[Truncated: source log excerpt]\nnewest source log record\n"
        assert next(
            item for item in prepared["files"] if item["name"] == "ai-guardian.log"
        )["truncated"]
    finally:
        bundles._cleanup_bundle(prepared["bundle_id"])


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_source_collector_refuses_linked_artifacts_and_cleans_staging(
    monkeypatch, tmp_path, link_kind
):
    root = tmp_path / "prepared"
    root.mkdir()
    external = tmp_path / "external.json"
    external.write_text(json.dumps({"private": "source content must not be followed"}))
    try:
        if link_kind == "symlink":
            (root / "unsafe.json").symlink_to(external)
        else:
            os.link(external, root / "unsafe.json")
    except OSError:
        pytest.skip("This filesystem cannot create the requested link")
    monkeypatch.setattr(
        bundles,
        "prepare_bundle",
        lambda **kwargs: {"temp_path": str(root), "files": [{"name": "unsafe.json"}]},
    )
    with pytest.raises(ValueError, match="configuration"):
        remote.collect_diagnostics("Source VM", [])
    assert not root.exists()
    assert external.is_file()


def test_compact_json_cannot_expand_past_import_limit(desktop, monkeypatch):
    value = {"items": [{"label": "ordinary text"} for _ in range(30)]}
    compact = json.dumps(value, separators=(",", ":"))
    assert len(compact) < 1024 < len(json.dumps(value, indent=2))
    monkeypatch.setattr(remote, "MAX_FILE_BYTES", 1024)
    payload = diagnostics()
    payload["files"].append(diagnostic("compact.json", compact))
    with pytest.raises(remote.SupportCollectionError):
        remote.import_diagnostics(payload, "Source VM (manual)")
    assert bundles._active_bundles == {}


def test_source_configuration_cannot_override_desktop_destination_or_category(
    desktop, monkeypatch
):
    monkeypatch.setattr(bundles, "_get_support_config", lambda: {})
    payload = diagnostics()
    payload["files"][0] = diagnostic(
        "ai-guardian.json",
        {
            "support": {
                "export_destination": "https://untrusted.invalid",
                "github_category": "q-a",
            }
        },
    )
    prepared = remote.import_diagnostics(payload, "Source VM (ssh)")
    try:
        assert prepared["destination"] == "github-discussions"
        context = json.loads(
            (Path(prepared["temp_path"]) / "support-context.json").read_text()
        )
        assert context == {"title": "", "description": "", "category": "bug-reports"}
    finally:
        bundles._cleanup_bundle(prepared["bundle_id"])
