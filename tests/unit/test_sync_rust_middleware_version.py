"""Tests for the Rust middleware release-version synchronizer."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_rust_middleware_version.py"


def _create_repo(tmp_path: Path, version: str = "1.20.0-dev") -> Path:
    manifest_dir = tmp_path / "rust" / "openshell-middleware"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "Cargo.toml").write_text(
        f'[package]\nname = "ai-guardian-openshell-middleware"\nversion = "{version}"\n\n'
        '[dependencies]\nserde = "1"\n',
        encoding="utf-8",
    )
    (manifest_dir / "Cargo.lock").write_text(
        "[[package]]\n"
        'name = "ai-guardian-openshell-middleware"\n'
        f'version = "{version}"\n\n'
        "[[package]]\n"
        'name = "serde"\n'
        'version = "1.0.0"\n',
        encoding="utf-8",
    )
    return tmp_path


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--repo", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_sync_updates_rust_package_version(tmp_path):
    repo = _create_repo(tmp_path)

    result = _run(repo, "--version", "1.20.0")

    assert result.returncode == 0, result.stderr
    assert 'version = "1.20.0"' in (
        repo / "rust" / "openshell-middleware" / "Cargo.toml"
    ).read_text(encoding="utf-8")
    assert 'version = "1.20.0"' in (
        repo / "rust" / "openshell-middleware" / "Cargo.lock"
    ).read_text(encoding="utf-8")


def test_check_reports_stale_rust_package_version(tmp_path):
    repo = _create_repo(tmp_path)

    result = _run(repo, "--version", "1.20.0", "--check")

    assert result.returncode == 1
    assert "expected 1.20.0, found 1.20.0-dev" in result.stderr


def test_check_accepts_matching_prerelease_version(tmp_path):
    repo = _create_repo(tmp_path, version="1.20.0-dev")

    result = _run(repo, "--version", "1.20.0-dev", "--check")

    assert result.returncode == 0, result.stderr
    assert "verified" in result.stdout
