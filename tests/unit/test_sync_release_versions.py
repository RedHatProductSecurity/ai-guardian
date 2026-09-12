"""Tests for the project-specific release reference synchronizer."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_release_versions.py"


def _create_release_reference_repo(tmp_path: Path) -> None:
    """Create the active version-bearing files used by the synchronizer."""
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
                "podman pull quay.io/redhatproductsecurity/ai-guardian:v1.0.0",
                "podman run quay.io/redhatproductsecurity/ai-guardian:v1.0.0",
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
                "",
            ]
        ),
        encoding="utf-8",
    )


def _run_sync(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--repo", str(tmp_path), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_sync_updates_all_active_release_references(tmp_path):
    _create_release_reference_repo(tmp_path)

    result = _run_sync(tmp_path, "--stable-version", "1.1.0")

    assert result.returncode == 0, result.stderr
    assert "Updated release references to 1.1.0" in result.stdout
    assert "v1.1.0" in (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "AI_GUARDIAN_VERSION=1.1.0" in (
        tmp_path / "container" / "Dockerfile"
    ).read_text(encoding="utf-8")
    assert "ai_guardian-1.0.0.dev0-py3-none-any.whl" in (
        tmp_path / "container" / "Dockerfile"
    ).read_text(encoding="utf-8")

    container_readme = (tmp_path / "container" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "ai_guardian-1.1.0-py3-none-any.whl" in container_readme
    assert "`AI_GUARDIAN_VERSION` | `1.1.0`" in container_readme
    assert "ai_guardian-1.0.0.dev0-py3-none-any.whl" in container_readme


def test_check_uses_latest_changelog_release_and_detects_stale_references(tmp_path):
    _create_release_reference_repo(tmp_path)

    sync_result = _run_sync(tmp_path, "--stable-version", "1.1.0")
    assert sync_result.returncode == 0, sync_result.stderr
    (tmp_path / "CHANGELOG.md").write_text(
        "## [1.1.0] - 2026-02-01\n## [1.0.0] - 2026-01-01\n",
        encoding="utf-8",
    )

    (tmp_path / "container" / "Dockerfile.openshell").write_text(
        "ARG AI_GUARDIAN_VERSION=0.9.0\n",
        encoding="utf-8",
    )
    check_result = _run_sync(tmp_path, "--check")

    assert check_result.returncode == 1
    assert "container/Dockerfile.openshell" in check_result.stderr


def test_check_rejects_a_missing_active_reference(tmp_path):
    _create_release_reference_repo(tmp_path)
    (tmp_path / "container" / "README.md").write_text(
        "no release reference here\n",
        encoding="utf-8",
    )

    result = _run_sync(tmp_path, "--check")

    assert result.returncode == 1
    assert "release reference layout changed" in result.stderr


def test_update_validates_all_files_before_writing(tmp_path):
    """A layout error must not leave earlier files partially updated."""
    _create_release_reference_repo(tmp_path)
    (tmp_path / "docs" / "notebooklm-export.md").write_text(
        "missing generated references\n",
        encoding="utf-8",
    )

    result = _run_sync(tmp_path, "--stable-version", "1.1.0")

    assert result.returncode == 1
    assert "release reference layout changed" in result.stderr
    assert "v1.0.0" in (tmp_path / "README.md").read_text(encoding="utf-8")
