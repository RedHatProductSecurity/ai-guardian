"""Tests for the OpenShell CLI version health check."""

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
        "CODEX_VERSION": "0.154.0",
        "OPENCODE_VERSION": "1.18.30",
        "COPILOT_VERSION": "1.0.83",
    }


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
        "@openai/codex": "0.155.0",
        "opencode-ai": "1.17.12",
        "@github/copilot": "1.0.83",
    }
    report = tmp_path / "cli-versions.json"

    results, has_updates, has_errors = cli_versions.check_versions(
        output_file=report,
        version_lookup=latest.__getitem__,
    )

    assert has_updates is True
    assert has_errors is False
    assert results["CODEX_VERSION"]["status"] == "OUTDATED"
    assert results["OPENCODE_VERSION"]["status"] == "OK"
    assert report.exists()


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
