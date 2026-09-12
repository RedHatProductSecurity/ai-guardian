#!/usr/bin/env python3
"""Synchronize AI Guardian's active stable-release references.

The package version is intentionally a development version on ``main``, while
the container defaults and pinned examples must continue to point at the most
recent stable release. The generic release helper updates package metadata;
this project-specific companion updates the remaining active references and
can verify them in CI.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

STABLE_VERSION_PATTERN = r"\d+\.\d+\.\d+"
STABLE_VERSION_RE = re.compile(rf"^{STABLE_VERSION_PATTERN}$")
Replacement = Tuple[str, str, str]


class ReleaseReferenceError(ValueError):
    """Raised when an expected active release reference is missing or stale."""


def _validate_stable_version(version: str) -> None:
    if not STABLE_VERSION_RE.fullmatch(version):
        raise ReleaseReferenceError(
            f"Expected a stable semantic version (X.Y.Z), got: {version}"
        )


def latest_stable_version(changelog_path: Path) -> str:
    """Return the first stable release heading in ``CHANGELOG.md``."""
    try:
        content = changelog_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ReleaseReferenceError(
            f"Could not read {changelog_path}: {error}"
        ) from error

    match = re.search(
        rf"^## \[({STABLE_VERSION_PATTERN})\]",
        content,
        flags=re.MULTILINE,
    )
    if not match:
        raise ReleaseReferenceError(
            f"No stable release heading found in {changelog_path}"
        )
    return match.group(1)


def _release_reference_rules(
    stable_version: str,
) -> List[Tuple[str, List[Replacement]]]:
    """Return the active release-reference substitutions for this project."""
    replacement = r"\g<1>" + stable_version
    replacement_with_suffix = r"\g<1>" + stable_version + r"\g<2>"
    return [
        (
            "container/Dockerfile",
            [
                (
                    rf"(AI_GUARDIAN_VERSION=){STABLE_VERSION_PATTERN}",
                    replacement,
                    "normal Dockerfile version references",
                )
            ],
        ),
        (
            "container/Dockerfile.openshell",
            [
                (
                    rf"(AI_GUARDIAN_VERSION=){STABLE_VERSION_PATTERN}",
                    replacement,
                    "OpenShell Dockerfile version reference",
                )
            ],
        ),
        (
            "README.md",
            [
                (
                    rf"(quay\.io/redhatproductsecurity/ai-guardian:v){STABLE_VERSION_PATTERN}",
                    replacement,
                    "root README pinned image references",
                )
            ],
        ),
        (
            "container/README.md",
            [
                (
                    rf"(quay\.io/redhatproductsecurity/ai-guardian:){STABLE_VERSION_PATTERN}",
                    replacement,
                    "container README pinned image references",
                ),
                (
                    rf"(pinned stable release \(e\.g\.\s+`){STABLE_VERSION_PATTERN}(?=`)",
                    replacement,
                    "container README stable-version example",
                ),
                (
                    rf"(AI_GUARDIAN_VERSION=){STABLE_VERSION_PATTERN}",
                    replacement,
                    "container README stable build argument",
                ),
                (
                    rf"(ai_guardian-){STABLE_VERSION_PATTERN}(-py3-none-any\.whl)",
                    replacement_with_suffix,
                    "container README stable wheel references",
                ),
                (
                    rf"(\|\s*`AI_GUARDIAN_VERSION`\s*\|\s*`){STABLE_VERSION_PATTERN}(`\s*\|)",
                    replacement_with_suffix,
                    "container README build-argument table",
                ),
            ],
        ),
        (
            "docs/notebooklm-export.md",
            [
                (
                    rf"(quay\.io/redhatproductsecurity/ai-guardian:v){STABLE_VERSION_PATTERN}",
                    replacement,
                    "generated documentation pinned image references",
                ),
                (
                    rf"(quay\.io/redhatproductsecurity/ai-guardian:){STABLE_VERSION_PATTERN}",
                    replacement,
                    "generated documentation container image references",
                ),
                (
                    rf"(pinned stable release \(e\.g\.\s+`){STABLE_VERSION_PATTERN}(?=`)",
                    replacement,
                    "generated documentation stable-version example",
                ),
                (
                    rf"(AI_GUARDIAN_VERSION=){STABLE_VERSION_PATTERN}",
                    replacement,
                    "generated documentation stable build argument",
                ),
                (
                    rf"(ai_guardian-){STABLE_VERSION_PATTERN}(-py3-none-any\.whl)",
                    replacement_with_suffix,
                    "generated documentation stable wheel references",
                ),
                (
                    rf"(\|\s*`AI_GUARDIAN_VERSION`\s*\|\s*`){STABLE_VERSION_PATTERN}(`\s*\|)",
                    replacement_with_suffix,
                    "generated documentation build-argument table",
                ),
            ],
        ),
    ]


def _rewrite_file(path: Path, replacements: List[Replacement]) -> Tuple[str, str]:
    """Apply replacements and require every expected reference to exist."""
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ReleaseReferenceError(f"Could not read {path}: {error}") from error

    updated = original
    for pattern, replacement, description in replacements:
        updated, count = re.subn(
            pattern,
            replacement,
            updated,
            flags=re.MULTILINE,
        )
        if count == 0:
            raise ReleaseReferenceError(
                f"{path}: no {description} found; release reference layout changed"
            )

    return original, updated


def sync_release_versions(
    repo_path: Path, stable_version: str, check: bool = False
) -> List[Path]:
    """Update or verify active stable references.

    Returns the files changed in update mode, or the files that would need
    changes in check mode. A missing expected reference raises an error so a
    new version-bearing location cannot be silently omitted from releases.
    """
    _validate_stable_version(stable_version)
    changed: List[Path] = []
    pending_writes: List[Tuple[Path, str]] = []

    for relative_path, replacements in _release_reference_rules(stable_version):
        path = repo_path / relative_path
        original, updated = _rewrite_file(path, replacements)
        if original == updated:
            continue

        changed.append(path)
        pending_writes.append((path, updated))

    if not check:
        for path, updated in pending_writes:
            try:
                path.write_text(updated, encoding="utf-8")
            except OSError as error:
                raise ReleaseReferenceError(
                    f"Could not write {path}: {error}"
                ) from error

    return changed


def main() -> int:
    """Run the release-reference synchronizer from the command line."""
    parser = argparse.ArgumentParser(
        description="Synchronize or verify AI Guardian stable release references"
    )
    parser.add_argument(
        "--repo",
        default=".",
        type=Path,
        help="Repository path (default: current directory)",
    )
    parser.add_argument(
        "--stable-version",
        help="Stable version to write; omitted in --check mode to read CHANGELOG.md",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if active references do not match the latest stable changelog entry",
    )
    args = parser.parse_args()

    repo_path = args.repo.resolve()
    try:
        stable_version = args.stable_version
        if stable_version is None:
            if not args.check:
                parser.error("--stable-version is required unless --check is used")
            stable_version = latest_stable_version(repo_path / "CHANGELOG.md")

        changed = sync_release_versions(repo_path, stable_version, check=args.check)
    except ReleaseReferenceError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if args.check:
        if changed:
            print(
                f"Release references are stale for {stable_version}: "
                + ", ".join(str(path.relative_to(repo_path)) for path in changed),
                file=sys.stderr,
            )
            return 1
        print(f"Release references match stable version {stable_version}")
    elif changed:
        print(
            f"Updated release references to {stable_version}: "
            + ", ".join(str(path.relative_to(repo_path)) for path in changed)
        )
    else:
        print(f"Release references already match stable version {stable_version}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
