#!/usr/bin/env python3
"""Verify the qualified OpenShell release and protocol contract.

This check is deliberately separate from ``check_cli_versions.py``.  That
script monitors npm terminal clients bundled in support images; this script
checks the OpenShell release/protocol baseline used by the middleware runtime.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUST_SOURCE = (
    REPOSITORY_ROOT / "rust" / "openshell-middleware" / "src" / "compatibility.rs"
)
COMPATIBILITY_PATH = (
    REPOSITORY_ROOT
    / "src"
    / "ai_guardian"
    / "middleware"
    / "openshell"
    / "compatibility.json"
)
RUST_COMPATIBILITY_PATH = (
    "../../../src/ai_guardian/middleware/openshell/compatibility.json"
)


def _load_policy() -> dict:
    if not COMPATIBILITY_PATH.is_file():
        raise ValueError(
            f"missing OpenShell compatibility fixture: {COMPATIBILITY_PATH}"
        )
    try:
        policy = json.loads(COMPATIBILITY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("unable to read OpenShell compatibility fixture") from exc
    if not isinstance(policy, dict):
        raise ValueError("OpenShell compatibility fixture must contain an object")
    release = policy.get("openshell_release")
    protocol = policy.get("supervisor_protocol")
    runtime_version = policy.get("runtime_version")
    if not isinstance(release, dict) or not isinstance(protocol, dict):
        raise ValueError("compatibility fixture is missing release or protocol data")
    if not isinstance(runtime_version, str) or not runtime_version.strip():
        raise ValueError("compatibility fixture is missing runtime_version")
    for section, fields in (
        ("openshell_release", ("major", "minor", "minimum_patch")),
        ("supervisor_protocol", ("major", "minor")),
    ):
        values = policy[section]
        for field in fields:
            value = values.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{section}.{field} must be a non-negative integer")
    return policy


def _parse_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", value.strip())
    if not match:
        raise ValueError(f"invalid OpenShell semantic version: {value}")
    return tuple(int(component) for component in match.groups())


def _validate_release(version: str, policy: dict) -> tuple[int, int, int]:
    parsed = _parse_version(version)
    release = policy["openshell_release"]
    if (
        parsed[0] != release["major"]
        or parsed[1] != release["minor"]
        or parsed[2] < release["minimum_patch"]
    ):
        raise ValueError(
            f"unsupported OpenShell release {version}; middleware supports "
            f"{release['major']}.{release['minor']}.x from "
            f"{release['major']}.{release['minor']}.{release['minimum_patch']}"
        )
    return parsed


def verify_contract() -> str:
    """Validate the shared fixture and Rust include path."""

    rust_source = RUST_SOURCE.read_text(encoding="utf-8")
    if "include_str!" not in rust_source or RUST_COMPATIBILITY_PATH not in rust_source:
        raise ValueError(
            "Rust middleware does not embed the shared compatibility fixture"
        )

    policy = _load_policy()
    release = policy["openshell_release"]
    baseline = f"{release['major']}.{release['minor']}.{release['minimum_patch']}"
    if policy["runtime_version"].strip() != baseline:
        raise ValueError(
            f"runtime version {policy['runtime_version']} disagrees with baseline {baseline}"
        )

    _validate_release(baseline, policy)
    _validate_release(
        f"{release['major']}.{release['minor']}.{release['minimum_patch'] + 1}",
        policy,
    )
    unsupported = f"{release['major']}.{release['minor'] + 1}.0"
    try:
        _validate_release(unsupported, policy)
    except ValueError:
        pass
    else:  # pragma: no cover - defensive contract check
        raise ValueError(f"unsupported OpenShell release was accepted: {unsupported}")

    return (
        f"OpenShell {baseline}+patches in minor {release['major']}."
        f"{release['minor']}; supervisor protocol "
        f"{policy['supervisor_protocol']['major']}."
        f"{policy['supervisor_protocol']['minor']}"
    )


def check_release(version: str) -> str:
    """Validate one explicitly supplied release against the Rust contract."""

    policy = _load_policy()
    _validate_release(version, policy)
    return f"OpenShell {version} is supported by the Rust middleware contract"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the AI Guardian OpenShell compatibility contract"
    )
    parser.add_argument(
        "--version",
        help="Validate one explicit OpenShell release instead of the shared baseline contract",
    )
    args = parser.parse_args(argv)

    try:
        message = check_release(args.version) if args.version else verify_contract()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: OpenShell compatibility check failed: {error}", file=sys.stderr)
        return 2

    print(f"✅ {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
