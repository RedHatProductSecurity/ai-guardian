"""Tests for the support-image terminal CLI version health check."""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import check_cli_versions as cli_versions  # noqa: E402


def test_load_pinned_versions_reads_openshell_dockerfile():
    pinned = cli_versions.load_pinned_versions(cli_versions.DEFAULT_DOCKERFILE)

    assert pinned == {
        "CODEX_VERSION": "0.160.0",
        "OPENCODE_VERSION": "1.19.0",
    }


def test_load_pinned_versions_reads_normal_opencode_pin():
    pinned = cli_versions.load_pinned_versions(cli_versions.DEFAULT_NORMAL_DOCKERFILE)

    assert pinned == {"OPENCODE_VERSION": "1.19.0"}


def test_support_image_cli_pins_match_documentation():
    pinned = cli_versions.load_pinned_versions(cli_versions.DEFAULT_DOCKERFILE)
    readme = (cli_versions.DEFAULT_DOCKERFILE.parent / "README.md").read_text(
        encoding="utf-8"
    )

    for build_arg, version in pinned.items():
        package = cli_versions.OPENSHELL_CLI_VERSION_SPECS[build_arg]["package"]
        assert f"| `{build_arg}` | `{package}` | `{version}` |" in readme

    normal_pinned = cli_versions.load_pinned_versions(
        cli_versions.DEFAULT_NORMAL_DOCKERFILE
    )
    assert f"| `OPENCODE_VERSION` | `{normal_pinned['OPENCODE_VERSION']}` |" in readme


@pytest.mark.parametrize(
    ("dockerfile", "runtime"),
    [
        (cli_versions.DEFAULT_DOCKERFILE, "OpenShell"),
        (cli_versions.DEFAULT_NORMAL_DOCKERFILE, "Normal Docker/Podman"),
    ],
)
def test_opencode_runtime_record_matches_image_pin(dockerfile, runtime):
    pinned = cli_versions.load_pinned_versions(dockerfile)
    support_record = (cli_versions.REPOSITORY_ROOT / "docs" / "OPENCODE.md").read_text(
        encoding="utf-8"
    )
    row = next(
        line
        for line in support_record.splitlines()
        if line.startswith(f"| {runtime} |")
    )

    assert f" {pinned['OPENCODE_VERSION']} |" in row


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("1.2.3", "1.2.4", -1),
        ("1.2.4", "1.2.3", 1),
        ("1.2.3", "1.2.3", 0),
        ("1.2.3-beta.1", "1.2.3", -1),
        ("not-semver", "1.2.3", None),
    ],
)
def test_compare_versions(first, second, expected):
    assert cli_versions.compare_versions(first, second) == expected


def test_check_versions_writes_report_and_detects_updates(tmp_path):
    latest = {
        "@openai/codex": "0.160.1",
        "opencode-ai": "1.19.0",
    }
    report = tmp_path / "cli-versions.json"

    results, has_updates, has_errors = cli_versions.check_versions(
        output_file=report,
        version_lookup=latest.__getitem__,
    )

    assert has_updates is True
    assert has_errors is False
    assert results["CODEX_VERSION"]["status"] == "OUTDATED"
    assert report.exists()


def test_check_all_versions_includes_normal_opencode(tmp_path):
    latest = {
        "@openai/codex": "0.160.0",
        "opencode-ai": "1.19.0",
    }

    results, has_updates, has_errors = cli_versions.check_all_versions(
        output_file=tmp_path / "cli-versions.json",
        version_lookup=latest.__getitem__,
    )

    assert has_updates is False
    assert has_errors is False
    assert results["OPENCODE_VERSION"]["status"] == "OK"


def test_check_all_versions_reports_only_pending_codex_update():
    latest = {"@openai/codex": "0.162.1", "opencode-ai": "1.19.0"}

    results, has_updates, has_errors = cli_versions.check_all_versions(
        version_lookup=latest.__getitem__,
    )

    assert has_updates is True
    assert has_errors is False
    assert results["CODEX_VERSION"]["pinned_version"] == "0.160.0"
    assert results["CODEX_VERSION"]["status"] == "OUTDATED"
    assert results["OPENCODE_VERSION"]["pinned_version"] == "1.19.0"
    assert results["OPENCODE_VERSION"]["status"] == "OK"


def test_check_versions_marks_registry_failure(tmp_path):
    report = tmp_path / "cli-versions.json"

    def unavailable(_package):
        return None

    _, has_updates, has_errors = cli_versions.check_versions(
        output_file=report,
        version_lookup=unavailable,
    )

    assert has_updates is False
    assert has_errors is True
    assert '"status": "UNKNOWN"' in report.read_text(encoding="utf-8")
