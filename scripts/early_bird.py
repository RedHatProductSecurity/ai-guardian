#!/usr/bin/env python3
"""Helpers for the opt-in, public PyPI Early Bird channel."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from packaging.version import InvalidVersion, Version

DEV_VERSION = re.compile(r"^(?P<base>\d+\.\d+\.\d+)\.dev(?P<number>\d+)$")


def development_base(version: str) -> str:
    """Return the planned stable base from an ``X.Y.Z-dev`` project version."""
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:-dev|\.dev\d+)", version)
    if not match:
        raise ValueError(f"Early Bird requires an X.Y.Z-dev project version: {version}")
    return match.group(1)


def next_dev_version(
    base: str, published_versions: list[str], last_build: int = 0
) -> str:
    """Choose a never-reused ``base.devN`` version."""
    try:
        base_version = Version(base)
    except InvalidVersion as error:
        raise ValueError(f"Invalid planned release version: {base}") from error
    if base_version.local or base_version.pre or base_version.post:
        raise ValueError("The planned Early Bird base must be a public X.Y.Z release")
    numbers = [last_build]
    for value in published_versions:
        match = DEV_VERSION.fullmatch(value)
        if match and match.group("base") == base:
            numbers.append(int(match.group("number")))
    return f"{base}.dev{max(numbers) + 1}"


def validate_ordering(base: str) -> None:
    """Assert the resolver ordering policy used in the documentation."""
    stable = Version(base)
    rc = Version(f"{base}rc1")
    dev = Version(f"{base}.dev1")
    if not dev < rc < stable:
        raise ValueError("PEP 440 ordering does not match Early Bird policy")


def prepare_tree(
    source: Path, destination: Path, version: str, source_sha: str
) -> None:
    """Copy source to a build tree and add version/provenance without mutating git."""
    import shutil

    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    project = destination / "pyproject.toml"
    text = project.read_text(encoding="utf-8")
    text = re.sub(r'(?m)^(version\s*=\s*)"[^"]+"$', rf'\g<1>"{version}"', text, count=1)
    if text == project.read_text(encoding="utf-8"):
        raise ValueError("pyproject.toml version was not replaced")
    text = text.replace(
        '"Source Code" = "https://github.com/RedHatProductSecurity/ai-guardian"',
        '"Source Code" = "https://github.com/RedHatProductSecurity/ai-guardian"\n'
        f'"Early Bird Source Commit" = "https://github.com/RedHatProductSecurity/ai-guardian/commit/{source_sha}"',
    )
    text = text.replace(
        '"src/ai_guardian/middleware/openshell/compatibility.json" = '
        '"ai_guardian/middleware/openshell/compatibility.json"',
        '"src/ai_guardian/middleware/openshell/compatibility.json" = '
        '"ai_guardian/middleware/openshell/compatibility.json"\n'
        '"EARLY_BIRD_PROVENANCE" = "ai_guardian/EARLY_BIRD_PROVENANCE"',
    )
    project.write_text(text, encoding="utf-8")
    init = destination / "src" / "ai_guardian" / "__init__.py"
    init_text = init.read_text(encoding="utf-8")
    init_text = re.sub(
        r'(?m)^(__version__\s*=\s*)"[^"]+"$', rf'\g<1>"{version}"', init_text, count=1
    )
    init.write_text(init_text, encoding="utf-8")
    metadata = destination / "EARLY_BIRD_PROVENANCE"
    metadata.write_text(
        f"version={version}\nsource_sha={source_sha}\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    version_parser = subparsers.add_parser("version")
    version_parser.add_argument("--base", required=True)
    version_parser.add_argument("--published", nargs="*", default=[])
    version_parser.add_argument("--last-build", type=int, default=0)
    order_parser = subparsers.add_parser("validate-ordering")
    order_parser.add_argument("--base", required=True)
    args = parser.parse_args()
    if args.command == "version":
        print(next_dev_version(args.base, args.published, args.last_build))
    else:
        validate_ordering(args.base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
