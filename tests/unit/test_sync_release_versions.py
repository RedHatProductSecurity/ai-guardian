"""Tests for the project-specific release reference synchronizer."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_release_versions.py"
ACTIVE_REFERENCES = {
    "normal-default": (
        "container/Dockerfile",
        "AI_GUARDIAN_VERSION=1.0.0",
    ),
    "openshell-default": (
        "container/Dockerfile.openshell",
        "AI_GUARDIAN_VERSION=1.0.0",
    ),
    "pinned-image": (
        "container/README.md",
        "quay.io/redhatproductsecurity/ai-guardian:1.0.0",
    ),
    "stable-example": (
        "container/README.md",
        "pinned stable release (e.g. `1.0.0`)",
    ),
    "build-argument": (
        "container/README.md",
        "AI_GUARDIAN_VERSION=1.0.0",
    ),
    "stable-wheel": (
        "container/README.md",
        "ai_guardian-1.0.0-py3-none-any.whl",
    ),
    "build-argument-table": (
        "container/README.md",
        "| `AI_GUARDIAN_VERSION` | `1.0.0` |",
    ),
}


def _create_release_reference_repo(tmp_path: Path) -> None:
    """Create active references alongside a landing page and generated history."""
    container_dir = tmp_path / "container"
    container_dir.mkdir()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    (tmp_path / "CHANGELOG.md").write_text(
        "## [1.0.0] - 2026-01-01\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "\n".join(
            [
                "# AI Guardian",
                "[Documentation](docs/README.md)",
                "[Containers](container/README.md)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (container_dir / "Dockerfile").write_text(
        "# AI_GUARDIAN_VERSION=1.0.0\nARG AI_GUARDIAN_VERSION=1.0.0\n"
        "# AI_GUARDIAN_VERSION=ai_guardian-1.0.0.dev0-py3-none-any.whl\n",
        encoding="utf-8",
    )
    (container_dir / "Dockerfile.openshell").write_text(
        "ARG AI_GUARDIAN_VERSION=1.0.0\n",
        encoding="utf-8",
    )
    (container_dir / "README.md").write_text(
        "\n".join(
            [
                "podman pull quay.io/redhatproductsecurity/ai-guardian:1.0.0",
                "- `:<version>` — pinned stable release (e.g. `1.0.0`)",
                "podman build --build-arg AI_GUARDIAN_VERSION=1.0.0 -t ai-guardian container/",
                "cp dist/ai_guardian-1.0.0-py3-none-any.whl container/vendor/",
                "podman build --build-arg AI_GUARDIAN_VERSION=ai_guardian-1.0.0-py3-none-any.whl \\",
                "| `AI_GUARDIAN_VERSION` | `1.0.0` | PyPI version or `.whl` filename |",
                "--build-arg AI_GUARDIAN_VERSION=ai_guardian-1.0.0.dev0-py3-none-any.whl",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (docs_dir / "notebooklm-export.md").write_text(
        "\n".join(
            [
                "podman pull quay.io/redhatproductsecurity/ai-guardian:v1.0.0",
                "podman run quay.io/redhatproductsecurity/ai-guardian:v1.0.0",
                "podman pull quay.io/redhatproductsecurity/ai-guardian:1.0.0",
                "- `:<version>` — pinned stable release (e.g. `1.0.0`)",
                "podman build --build-arg AI_GUARDIAN_VERSION=1.0.0",
                "cp dist/ai_guardian-1.0.0-py3-none-any.whl container/vendor/",
                "podman build --build-arg AI_GUARDIAN_VERSION=ai_guardian-1.0.0-py3-none-any.whl",
                "| `AI_GUARDIAN_VERSION` | `1.0.0` | PyPI version or `.whl` filename |",
                "Historical qualification: ai_guardian-0.9.0-py3-none-any.whl",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _run_sync(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(SYNC_SCRIPT), "--repo", str(tmp_path), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _snapshot_files(repo_path: Path) -> dict[Path, bytes]:
    """Capture a fixture repository so read-only and atomicity checks are exact."""
    return {path: path.read_bytes() for path in repo_path.rglob("*") if path.is_file()}


def test_sync_updates_active_references_without_rewriting_generated_history(tmp_path):
    _create_release_reference_repo(tmp_path)
    landing_page_path = tmp_path / "README.md"
    landing_page_before = landing_page_path.read_bytes()
    export_path = tmp_path / "docs" / "notebooklm-export.md"
    generated_export_before = export_path.read_text(encoding="utf-8")

    result = _run_sync(tmp_path, "--stable-version", "1.1.0")

    assert result.returncode == 0, result.stderr
    assert "Updated release references to 1.1.0" in result.stdout
    assert landing_page_path.read_bytes() == landing_page_before
    assert "ai_guardian-1.0.0.dev0-py3-none-any.whl" in (
        tmp_path / "container" / "Dockerfile"
    ).read_text(encoding="utf-8")

    container_readme = (tmp_path / "container" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "ai_guardian-1.0.0.dev0-py3-none-any.whl" in container_readme
    for relative_path, reference in ACTIVE_REFERENCES.values():
        content = (tmp_path / relative_path).read_text(encoding="utf-8")
        assert reference not in content
        assert reference.replace("1.0.0", "1.1.0") in content
    assert export_path.read_text(encoding="utf-8") == generated_export_before
    assert "Historical qualification: ai_guardian-0.9.0-py3-none-any.whl" in (
        generated_export_before
    )


def test_check_accepts_landing_page_without_writing(tmp_path):
    _create_release_reference_repo(tmp_path)
    before = _snapshot_files(tmp_path)

    result = _run_sync(tmp_path, "--check")

    assert result.returncode == 0, result.stderr
    assert "Release references match stable version 1.0.0" in result.stdout
    assert _snapshot_files(tmp_path) == before


def test_check_accepts_current_repository_layout():
    """Exercise the real release gate, not only synthetic documentation fixtures."""
    result = _run_sync(REPO_ROOT, "--check")

    assert result.returncode == 0, result.stderr
    assert "Release references match stable version" in result.stdout


def test_check_uses_latest_changelog_release_and_detects_stale_references(tmp_path):
    _create_release_reference_repo(tmp_path)

    sync_result = _run_sync(tmp_path, "--stable-version", "1.1.0")
    assert sync_result.returncode == 0, sync_result.stderr
    (tmp_path / "CHANGELOG.md").write_text(
        "## [1.1.0] - 2026-02-01\n## [1.0.0] - 2026-01-01\n",
        encoding="utf-8",
    )

    historical_check_result = _run_sync(tmp_path, "--check")
    assert historical_check_result.returncode == 0, historical_check_result.stderr

    (tmp_path / "container" / "Dockerfile.openshell").write_text(
        "ARG AI_GUARDIAN_VERSION=0.9.0\n",
        encoding="utf-8",
    )
    check_result = _run_sync(tmp_path, "--check")

    assert check_result.returncode == 1
    assert str(Path("container") / "Dockerfile.openshell") in check_result.stderr


@pytest.mark.parametrize(
    "relative_path,reference", ACTIVE_REFERENCES.values(), ids=list(ACTIVE_REFERENCES)
)
def test_check_rejects_each_stale_active_reference(tmp_path, relative_path, reference):
    _create_release_reference_repo(tmp_path)
    path = tmp_path / relative_path
    original = path.read_text(encoding="utf-8")
    assert reference in original
    path.write_text(
        original.replace(reference, reference.replace("1.0.0", "0.9.0")),
        encoding="utf-8",
    )
    before = _snapshot_files(tmp_path)

    result = _run_sync(tmp_path, "--check")

    assert result.returncode == 1
    assert "Release references are stale for 1.0.0" in result.stderr
    assert str(Path(relative_path)) in result.stderr
    assert _snapshot_files(tmp_path) == before


@pytest.mark.parametrize(
    "relative_path,reference", ACTIVE_REFERENCES.values(), ids=list(ACTIVE_REFERENCES)
)
@pytest.mark.parametrize(
    "args",
    [("--check",), ("--stable-version", "1.1.0")],
    ids=["check", "update"],
)
def test_missing_active_reference_fails_without_writing(
    tmp_path, relative_path, reference, args
):
    """Every required source pattern remains strict in both modes; updates are atomic."""
    _create_release_reference_repo(tmp_path)
    path = tmp_path / relative_path
    original = path.read_text(encoding="utf-8")
    assert reference in original
    path.write_text(original.replace(reference, ""), encoding="utf-8")
    before = _snapshot_files(tmp_path)

    result = _run_sync(tmp_path, *args)

    assert result.returncode == 1
    assert "release reference layout changed" in result.stderr
    assert str(path) in result.stderr
    assert _snapshot_files(tmp_path) == before


def test_release_reference_workflow_includes_documentation_only_changes():
    """A lightweight PR/push check must not skip the documentation that drives it."""
    workflow = yaml.load(
        (REPO_ROOT / ".github/workflows/release-references.yml").read_text(
            encoding="utf-8"
        ),
        Loader=yaml.BaseLoader,
    )

    for event in ("pull_request", "push"):
        trigger = workflow["on"][event]
        assert trigger["branches"] == ["main", "release-*"]
        assert "paths" not in trigger
        assert "paths-ignore" not in trigger

    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["release-references"]
    assert "if" not in job
    assert "continue-on-error" not in job
    assert [step["run"] for step in job["steps"] if "run" in step] == [
        "python3 -B scripts/sync_release_versions.py --repo . --check"
    ]
    assert all(
        "if" not in step and "continue-on-error" not in step for step in job["steps"]
    )
    assert {step["uses"].split("@")[0] for step in job["steps"] if "uses" in step} == {
        "actions/checkout",
        "actions/setup-python",
    }


def test_container_publishing_checks_references_before_preparing_either_image():
    """The publishing guard still protects both normal and OpenShell builds."""
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/build-container.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["build-and-push"]["steps"]
    names = [step["name"] for step in steps]
    check_index = names.index("Verify stable release references")

    assert steps[check_index]["run"] == (
        "python3 scripts/sync_release_versions.py --repo . --check"
    )
    for name in (
        "Download dev wheel",
        "Build release wheel",
        "Build and push image",
        "Build and push OpenShell sandbox image",
    ):
        assert check_index < names.index(name)
