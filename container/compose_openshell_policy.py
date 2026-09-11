#!/usr/bin/env python3
"""Compose OpenShell policy fragments into one schema-valid YAML document."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any, Dict

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised by host setup
    raise SystemExit(
        "Error: policy composition requires PyYAML; "
        "install ai-guardian or run the launcher from its virtual environment."
    ) from exc


Policy = Dict[str, Any]


def _load_policy(path: Path) -> Policy:
    try:
        with path.open("r", encoding="utf-8") as policy_file:
            value = yaml.safe_load(policy_file)
    except OSError as exc:
        raise ValueError(f"cannot read policy fragment {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in policy fragment {path}: {exc}") from exc

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"policy fragment {path} must contain a YAML mapping")
    return value


def _merge(base: Any, overlay: Any) -> Any:
    """Deep-merge mappings; overlay scalar and list values replace the base."""

    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = copy.deepcopy(base)
        for key, value in overlay.items():
            if key in merged:
                merged[key] = _merge(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged
    return copy.deepcopy(overlay)


def compose(paths: list[Path]) -> Policy:
    policy: Policy = {}
    for path in paths:
        policy = _merge(policy, _load_policy(path))

    # Agent and capability fragments may omit version, but the final document
    # must always be an OpenShell policy document.
    policy.setdefault("version", 1)
    if policy["version"] != 1:
        raise ValueError("OpenShell policy version must be 1")

    network_policies = policy.get("network_policies")
    if network_policies is not None and not isinstance(network_policies, dict):
        raise ValueError("network_policies must be a YAML mapping")

    return policy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compose OpenShell policy fragments into one YAML policy."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="path for the composed policy",
    )
    parser.add_argument(
        "policies",
        type=Path,
        nargs="+",
        help="policy fragments, applied from left to right",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        policy = compose(args.policies)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Error: unable to compose OpenShell policy: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
