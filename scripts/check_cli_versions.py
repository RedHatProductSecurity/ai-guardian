#!/usr/bin/env python3
"""Check explicitly managed terminal CLI versions in the support images.

The Dockerfiles are the source of truth for pinned versions. This check reads
their build arguments and compares them with stable versions published in the
npm registry. It intentionally covers only CLI clients explicitly installed
by each image. It does not check the OpenShell gateway release or the
AI Guardian middleware compatibility contract; use
``check_openshell_compatibility.py`` for that.

Exit codes:
    0: All registry checks succeeded and no newer versions were found.
    1: At least one newer stable version is available.
    2: A Dockerfile or registry check could not be completed.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import quote

import requests

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCKERFILE = REPOSITORY_ROOT / "container" / "Dockerfile.openshell"
DEFAULT_NORMAL_DOCKERFILE = REPOSITORY_ROOT / "container" / "Dockerfile"

# Keep each mapping limited to clients whose versions are explicit build
# arguments in that image.
OPENSHELL_CLI_VERSION_SPECS = {
    "CODEX_VERSION": {
        "package": "@openai/codex",
        "name": "Codex CLI",
        "lookup": "@openai/codex",
        "source": "npm registry",
        "registry": "https://www.npmjs.com/package/%40openai/codex",
    },
}

NORMAL_CLI_VERSION_SPECS = {
    "OPENCODE_VERSION": {
        "package": "opencode-ai",
        "name": "OpenCode V1",
        "lookup": "opencode-ai",
        "source": "npm registry",
        "registry": "https://www.npmjs.com/package/opencode-ai",
    },
}

# Backward-compatible public name for callers checking the OpenShell image.
CLI_VERSION_SPECS = OPENSHELL_CLI_VERSION_SPECS

_ARG_PATTERN = re.compile(
    r"^\s*ARG\s+(?P<name>[A-Z][A-Z0-9_]*_VERSION)=(?P<version>[^\s#]+)",
    re.MULTILINE,
)
_SEMVER_PATTERN = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?$"
)


def _specs_for_dockerfile(dockerfile: Path) -> Dict[str, dict]:
    """Return the version specs belonging to a support image."""
    if dockerfile.resolve() == DEFAULT_NORMAL_DOCKERFILE.resolve():
        return NORMAL_CLI_VERSION_SPECS
    return OPENSHELL_CLI_VERSION_SPECS


def load_pinned_versions(
    dockerfile: Path, specs: Optional[Dict[str, dict]] = None
) -> Dict[str, str]:
    """Read explicit CLI version arguments from a support Dockerfile."""
    contents = dockerfile.read_text(encoding="utf-8")
    specs = specs or _specs_for_dockerfile(dockerfile)
    discovered = {
        match.group("name"): match.group("version")
        for match in _ARG_PATTERN.finditer(contents)
    }

    missing = [name for name in specs if name not in discovered]
    if missing:
        missing_args = ", ".join(missing)
        raise ValueError(
            f"Dockerfile is missing CLI version argument(s): {missing_args}"
        )

    return {name: discovered[name] for name in specs}


def _parse_semver(version: str) -> Optional[Tuple[int, int, int, Optional[str]]]:
    match = _SEMVER_PATTERN.fullmatch(version.strip())
    if not match:
        return None
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        match.group("prerelease"),
    )


def compare_versions(first: str, second: str) -> Optional[int]:
    """Compare two npm-style semantic versions.

    Returns ``None`` when either value is not a supported semantic version.
    Stable releases sort after prereleases with the same numeric components.
    """
    first_parsed = _parse_semver(first)
    second_parsed = _parse_semver(second)
    if first_parsed is None or second_parsed is None:
        return None

    first_numbers = first_parsed[:3]
    second_numbers = second_parsed[:3]
    if first_numbers < second_numbers:
        return -1
    if first_numbers > second_numbers:
        return 1

    first_prerelease = first_parsed[3]
    second_prerelease = second_parsed[3]
    if first_prerelease == second_prerelease:
        return 0
    if first_prerelease is None:
        return 1
    if second_prerelease is None:
        return -1
    return -1 if first_prerelease < second_prerelease else 1


def get_latest_npm_version(package: str) -> Optional[str]:
    """Return the stable ``latest`` version for one npm package."""
    registry_url = f"https://registry.npmjs.org/{quote(package, safe='')}/latest"
    try:
        response = requests.get(
            registry_url,
            headers={"Accept": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        version = response.json().get("version")
    except (requests.RequestException, ValueError, AttributeError):
        return None

    return version if isinstance(version, str) and version else None


def get_latest_cli_version(lookup: str) -> Optional[str]:
    """Return the latest stable version for an npm package lookup."""
    return get_latest_npm_version(lookup)


def check_versions(
    dockerfile: Path = DEFAULT_DOCKERFILE,
    output_file: Optional[Path] = None,
    version_lookup: Callable[[str], Optional[str]] = get_latest_cli_version,
) -> Tuple[Dict[str, dict], bool, bool]:
    """Check pinned versions and optionally write a JSON report.

    Returns ``(results, has_updates, has_errors)``.  ``version_lookup`` is
    injectable so unit tests do not require network access.
    """
    specs = _specs_for_dockerfile(dockerfile)
    pinned_versions = load_pinned_versions(dockerfile, specs)
    results: Dict[str, dict] = {}
    has_updates = False
    has_errors = False

    image_name = (
        "normal support image"
        if specs is NORMAL_CLI_VERSION_SPECS
        else "OpenShell support image"
    )
    print(f"Checking {image_name} terminal CLI version updates...\n")
    for build_arg, spec in specs.items():
        pinned_version = pinned_versions[build_arg]
        latest_version = version_lookup(spec["lookup"])
        comparison = (
            compare_versions(pinned_version, latest_version)
            if latest_version is not None
            else None
        )

        if latest_version is None or comparison is None:
            status = "UNKNOWN"
            has_errors = True
        elif comparison < 0:
            status = "OUTDATED"
            has_updates = True
        else:
            status = "OK"

        results[build_arg] = {
            "name": spec["name"],
            "package": spec["package"],
            "source": spec["source"],
            "build_arg": build_arg,
            "pinned_version": pinned_version,
            "latest_version": latest_version or "unknown",
            "is_outdated": status == "OUTDATED",
            "status": status,
            "registry": spec["registry"],
        }

        print(f"Checking {spec['name']} ({spec['package']})...")
        print(f"  Pinned: v{pinned_version}")
        print(f"  Latest: v{latest_version or 'unknown'}")
        print(f"  Status: {status}\n")

    if output_file is not None:
        output_file.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(f"Results written to {output_file}")

    return results, has_updates, has_errors


def check_all_versions(
    output_file: Optional[Path] = None,
    version_lookup: Callable[[str], Optional[str]] = get_latest_cli_version,
) -> Tuple[Dict[str, dict], bool, bool]:
    """Check the OpenShell and normal support-image pins together."""
    combined: Dict[str, dict] = {}
    has_updates = False
    has_errors = False
    for dockerfile in (DEFAULT_DOCKERFILE, DEFAULT_NORMAL_DOCKERFILE):
        results, updates, errors = check_versions(
            dockerfile, version_lookup=version_lookup
        )
        combined.update(results)
        has_updates = has_updates or updates
        has_errors = has_errors or errors

    if output_file is not None:
        output_file.write_text(json.dumps(combined, indent=2) + "\n", encoding="utf-8")
        print(f"Results written to {output_file}")
    return combined, has_updates, has_errors


def main() -> int:
    """Run the command-line version check."""
    parser = argparse.ArgumentParser(description="Check support-image CLI versions")
    parser.add_argument(
        "--dockerfile",
        type=Path,
        default=None,
        help="Specific Dockerfile to check; by default, check both support images",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("cli-versions.json"),
        help="JSON report path",
    )
    args = parser.parse_args()

    try:
        if args.dockerfile is None:
            _, has_updates, has_errors = check_all_versions(args.output)
        else:
            _, has_updates, has_errors = check_versions(args.dockerfile, args.output)
    except (OSError, ValueError) as error:
        print(
            f"Error: unable to check support-image CLI versions: {error}",
            file=sys.stderr,
        )
        return 2

    if has_errors:
        print("\n⚠️  One or more CLI version checks could not be completed")
        return 2
    if has_updates:
        print("\n⚠️  New support-image CLI versions are available")
        return 1

    print("\n✅ All pinned support-image CLI versions are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
