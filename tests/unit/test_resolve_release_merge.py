"""Tests for safe post-release merge conflict resolution."""

import subprocess
from pathlib import Path

import pytest

from scripts.resolve_release_merge import (
    MergeResolutionError,
    merge_release_changelog,
    resolve_release_merge,
    resolve_version_conflicts,
)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def _create_conflicted_release_repo(repo: Path, unexpected_conflict: bool = False):
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Release Test")
    _git(repo, "config", "user.email", "release-test@example.invalid")
    _git(repo, "config", "merge.conflictStyle", "merge")
    (repo / "rust/openshell-middleware").mkdir(parents=True)
    (repo / "src/ai_guardian").mkdir(parents=True)
    (repo / ".wolf").mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "ai-guardian"\nversion = "1.21.0"\n',
        encoding="utf-8",
    )
    (repo / "src/ai_guardian/__init__.py").write_text(
        '__version__ = "1.21.0"\n', encoding="utf-8"
    )
    (repo / "rust/openshell-middleware/Cargo.toml").write_text(
        '[package]\nname = "middleware"\nversion = "1.21.0"\n',
        encoding="utf-8",
    )
    (repo / "rust/openshell-middleware/Cargo.lock").write_text(
        '[[package]]\nname = "middleware"\nversion = "1.21.0"\n',
        encoding="utf-8",
    )
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n### Added\n- Base change\n\n"
        "## [1.21.0] - 2026-11-01\n\n### Added\n- Previous release\n\n"
        "[Unreleased]: https://example.invalid/compare/v1.21.0...HEAD\n"
        "[1.21.0]: https://example.invalid/releases/tag/v1.21.0\n",
        encoding="utf-8",
    )
    (repo / ".wolf/STATUS.md").write_text("# Status\nbase\n", encoding="utf-8")
    if unexpected_conflict:
        (repo / "src/ai_guardian/conflict.py").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")

    _git(repo, "checkout", "-b", "release-1.21")
    for path in (
        "pyproject.toml",
        "src/ai_guardian/__init__.py",
        "rust/openshell-middleware/Cargo.toml",
        "rust/openshell-middleware/Cargo.lock",
    ):
        file = repo / path
        file.write_text(file.read_text(encoding="utf-8").replace("1.21.0", "1.21.1"))
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "## [1.21.1] - 2026-11-10\n\n### Fixed\n- Release fix\n\n"
        "## [1.21.0] - 2026-11-01\n\n### Added\n- Previous release\n\n"
        "[Unreleased]: https://example.invalid/compare/v1.21.1...HEAD\n"
        "[1.21.1]: https://example.invalid/releases/tag/v1.21.1\n"
        "[1.21.0]: https://example.invalid/releases/tag/v1.21.0\n",
        encoding="utf-8",
    )
    (repo / ".wolf/STATUS.md").write_text(
        "# Status\nrelease handoff\n", encoding="utf-8"
    )
    (repo / "release-only.txt").write_text("keep release code\n", encoding="utf-8")
    if unexpected_conflict:
        (repo / "src/ai_guardian/conflict.py").write_text("release\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "release branch")

    _git(repo, "checkout", "main")
    for path in (
        "pyproject.toml",
        "src/ai_guardian/__init__.py",
        "rust/openshell-middleware/Cargo.toml",
        "rust/openshell-middleware/Cargo.lock",
    ):
        file = repo / path
        file.write_text(
            file.read_text(encoding="utf-8").replace("1.21.0", "1.22.0-dev")
        )
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n### Added\n- Main-only feature\n\n"
        "## [1.21.0] - 2026-11-01\n\n### Added\n- Previous release\n\n"
        "[Unreleased]: https://example.invalid/compare/v1.21.0...HEAD\n"
        "[1.21.0]: https://example.invalid/releases/tag/v1.21.0\n",
        encoding="utf-8",
    )
    (repo / ".wolf/STATUS.md").write_text("# Status\nmain handoff\n", encoding="utf-8")
    if unexpected_conflict:
        (repo / "src/ai_guardian/conflict.py").write_text("main\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "main development")

    merge = _git(
        repo,
        "-c",
        "merge.conflictStyle=merge",
        "merge",
        "--no-commit",
        "--no-ff",
        "release-1.21",
        check=False,
    )
    assert merge.returncode != 0
    return repo


@pytest.mark.parametrize(
    ("path", "ours", "theirs"),
    [
        ("pyproject.toml", 'version = "1.22.0-dev"\n', 'version = "1.21.1"\n'),
        (
            "src/ai_guardian/__init__.py",
            '__version__ = "1.22.0-dev"\n',
            '__version__ = "1.21.1"\n',
        ),
        (
            "rust/openshell-middleware/Cargo.toml",
            'version = "1.22.0-dev"\n',
            'version = "1.21.1"\n',
        ),
        (
            "rust/openshell-middleware/Cargo.lock",
            'version = "1.22.0-dev"\n',
            'version = "1.21.1"\n',
        ),
    ],
)
def test_version_conflicts_are_set_to_next_development_version(path, ours, theirs):
    conflicted = f"<<<<<<< HEAD\n{ours}=======\n{theirs}>>>>>>> release-1.21\n"

    assert resolve_version_conflicts(conflicted, path, "1.22.0-dev") == ours


def test_version_conflict_rejects_non_version_changes():
    conflicted = (
        '<<<<<<< HEAD\nversion = "1.22.0-dev"\ndependency = "main"\n'
        '=======\nversion = "1.21.1"\ndependency = "release"\n'
        ">>>>>>> release-1.21\n"
    )

    with pytest.raises(MergeResolutionError, match="beyond the version value"):
        resolve_version_conflicts(conflicted, "pyproject.toml", "1.22.0-dev")


def test_changelog_merge_keeps_main_unreleased_and_release_entry():
    main = (
        "# Changelog\n\n## [Unreleased]\n\n### Added\n- Main feature\n\n"
        "### Example\n```md\n[Example]: https://example.invalid/example\n```\n\n"
        "## [1.21.0] - 2026-11-01\n\n### Added\n- Previous\n\n"
        "[Unreleased]: https://example.invalid/compare/v1.21.0...HEAD\n"
        "[1.21.0]: https://example.invalid/releases/tag/v1.21.0\n"
    )
    release = (
        "# Changelog\n\n## [Unreleased]\n\n"
        "## [1.21.1] - 2026-11-10\n\n### Fixed\n- Release fix\n\n"
        "## [1.21.0] - 2026-11-01\n\n### Added\n- Previous\n\n"
        "[Unreleased]: https://example.invalid/compare/v1.21.1...HEAD\n"
        "[1.21.1]: https://example.invalid/releases/tag/v1.21.1\n"
        "[1.21.0]: https://example.invalid/releases/tag/v1.21.0\n"
    )

    merged = merge_release_changelog(main, release, "1.21.1")

    assert "- Main feature" in merged
    assert "- Release fix" in merged
    assert merged.index("## [Unreleased]") < merged.index("## [1.21.1]")
    assert merged.index("## [1.21.1]") < merged.index("## [1.21.0]")
    assert "compare/v1.21.1...HEAD" in merged
    assert "[1.21.1]: https://example.invalid/releases/tag/v1.21.1" in merged
    assert "[Example]: https://example.invalid/example" in merged
    assert merged.index("[Unreleased]:") < merged.index("[1.21.1]:")
    assert merged.index("[1.21.1]:") < merged.index("[1.21.0]:")


def test_known_conflicts_resolve_and_preserve_both_branches(tmp_path):
    repo = _create_conflicted_release_repo(tmp_path / "repo")

    resolved = resolve_release_merge(repo, "1.21.1", "1.22.0-dev")

    assert "CHANGELOG.md" in resolved
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout == ""
    assert 'version = "1.22.0-dev"' in (repo / "pyproject.toml").read_text()
    assert (
        '__version__ = "1.22.0-dev"'
        in (repo / "src/ai_guardian/__init__.py").read_text()
    )
    assert (
        'version = "1.22.0-dev"'
        in (repo / "rust/openshell-middleware/Cargo.toml").read_text()
    )
    assert (
        'version = "1.22.0-dev"'
        in (repo / "rust/openshell-middleware/Cargo.lock").read_text()
    )
    changelog = (repo / "CHANGELOG.md").read_text()
    assert "- Main-only feature" in changelog
    assert "- Release fix" in changelog
    assert (repo / ".wolf/STATUS.md").read_text() == "# Status\nmain handoff\n"
    assert (repo / "release-only.txt").read_text() == "keep release code\n"

    _git(repo, "commit", "-m", "Merge release-1.21 into main")
    parents = _git(repo, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
    assert len(parents) == 3


def test_unexpected_conflicts_are_left_for_manual_resolution(tmp_path):
    repo = _create_conflicted_release_repo(tmp_path / "repo", unexpected_conflict=True)
    before = (repo / "pyproject.toml").read_text(encoding="utf-8")

    with pytest.raises(MergeResolutionError, match="src/ai_guardian/conflict.py"):
        resolve_release_merge(repo, "1.21.1", "1.22.0-dev")

    assert (repo / "pyproject.toml").read_text(encoding="utf-8") == before
    unresolved = _git(
        repo, "diff", "--name-only", "--diff-filter=U"
    ).stdout.splitlines()
    assert "src/ai_guardian/conflict.py" in unresolved
