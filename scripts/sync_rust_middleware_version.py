#!/usr/bin/env python3
"""Keep the Rust OpenShell middleware version aligned with an AI Guardian release."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
MANIFEST_PACKAGE_SECTION_PATTERN = re.compile(
    r"(?ms)^\[package\]\s*\n(?P<body>.*?)(?=^\[|\Z)"
)
LOCK_PACKAGE_SECTION_PATTERN = re.compile(
    r"(?ms)^\[\[package\]\]\s*\n(?P<body>.*?)(?=^\[\[|\Z)"
)
PACKAGE_NAME_PATTERN = re.compile(r'(?m)^name\s*=\s*"([^"]+)"\s*$')
PACKAGE_VERSION_PATTERN = re.compile(r'(?m)^version\s*=\s*"([^"]+)"\s*$')
MIDDLEWARE_PACKAGE_NAME = "ai-guardian-openshell-middleware"


class MiddlewareVersionError(ValueError):
    """Raised when the Rust middleware manifest has an unexpected layout."""


def _manifest_path(repo_path: Path) -> Path:
    return repo_path / "rust" / "openshell-middleware" / "Cargo.toml"


def _lock_path(repo_path: Path) -> Path:
    return repo_path / "rust" / "openshell-middleware" / "Cargo.lock"


def _validate_version(version: str) -> None:
    if not VERSION_PATTERN.fullmatch(version):
        raise MiddlewareVersionError(f"Expected a semantic version, got: {version}")


def _package_version_span(manifest: str) -> tuple[int, int, str]:
    package = MANIFEST_PACKAGE_SECTION_PATTERN.search(manifest)
    if package is None:
        raise MiddlewareVersionError("Cargo.toml is missing its [package] section")

    match = PACKAGE_VERSION_PATTERN.search(package.group("body"))
    if match is None:
        raise MiddlewareVersionError(
            "Cargo.toml [package] section is missing its version"
        )
    start = package.start("body") + match.start(1)
    end = package.start("body") + match.end(1)
    return start, end, match.group(1)


def _lock_version_span(lock: str) -> tuple[int, int, str]:
    for package in LOCK_PACKAGE_SECTION_PATTERN.finditer(lock):
        name = PACKAGE_NAME_PATTERN.search(package.group("body"))
        if name is None or name.group(1) != MIDDLEWARE_PACKAGE_NAME:
            continue
        match = PACKAGE_VERSION_PATTERN.search(package.group("body"))
        if match is None:
            raise MiddlewareVersionError(
                f"Cargo.lock package {MIDDLEWARE_PACKAGE_NAME!r} is missing its version"
            )
        start = package.start("body") + match.start(1)
        end = package.start("body") + match.end(1)
        return start, end, match.group(1)

    raise MiddlewareVersionError(
        f"Cargo.lock is missing package {MIDDLEWARE_PACKAGE_NAME!r}"
    )


def read_version(repo_path: Path) -> str:
    """Read the Rust package version from the repository manifest."""
    manifest_path = _manifest_path(repo_path)
    try:
        manifest = manifest_path.read_text(encoding="utf-8")
    except OSError as error:
        raise MiddlewareVersionError(
            f"Could not read {manifest_path}: {error}"
        ) from error

    _, _, version = _package_version_span(manifest)
    return version


def sync_version(repo_path: Path, version: str, check: bool = False) -> bool:
    """Update or verify the Rust middleware package version.

    Returns ``True`` when the manifest differs from ``version``. In update
    mode the manifest is rewritten; in check mode it is left untouched.
    """
    _validate_version(version)
    manifest_path = _manifest_path(repo_path)
    lock_path = _lock_path(repo_path)
    try:
        manifest = manifest_path.read_text(encoding="utf-8")
        lock = lock_path.read_text(encoding="utf-8")
    except OSError as error:
        raise MiddlewareVersionError(
            f"Could not read Rust middleware version files: {error}"
        ) from error

    manifest_start, manifest_end, manifest_version = _package_version_span(manifest)
    lock_start, lock_end, lock_version = _lock_version_span(lock)
    if manifest_version == version and lock_version == version:
        return False

    updated_manifest = manifest[:manifest_start] + version + manifest[manifest_end:]
    updated_lock = lock[:lock_start] + version + lock[lock_end:]
    if not check:
        try:
            if manifest_version != version:
                manifest_path.write_text(updated_manifest, encoding="utf-8")
            if lock_version != version:
                lock_path.write_text(updated_lock, encoding="utf-8")
        except OSError as error:
            raise MiddlewareVersionError(
                f"Could not write Rust middleware version files: {error}"
            ) from error
    return True


def main(argv: list[str] | None = None) -> int:
    """Run the middleware version synchronizer."""
    parser = argparse.ArgumentParser(
        description="Synchronize or verify the Rust OpenShell middleware version"
    )
    parser.add_argument(
        "--repo",
        default=".",
        type=Path,
        help="Repository path (default: current directory)",
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Expected semantic version",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the manifest does not already use --version",
    )
    args = parser.parse_args(argv)

    repo_path = args.repo.resolve()
    try:
        changed = sync_version(repo_path, args.version, check=args.check)
        if args.check and changed:
            actual = read_version(repo_path)
            lock_version = _lock_version_span(
                _lock_path(repo_path).read_text(encoding="utf-8")
            )[2]
            print(
                "Rust middleware version is stale: "
                f"expected {args.version}, found {actual} in Cargo.toml "
                f"and {lock_version} in Cargo.lock",
                file=sys.stderr,
            )
            return 1
    except MiddlewareVersionError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    action = "verified" if args.check else "updated"
    print(f"Rust middleware version {action}: {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
