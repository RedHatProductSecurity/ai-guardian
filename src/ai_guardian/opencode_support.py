"""OpenCode runtime generation and version helpers."""

import os
import re
import shutil
import subprocess
from typing import Any, Dict, Optional

_VERSION_PATTERN = re.compile(r"(?<!\d)v?(\d+)\.(\d+)\.(\d+)(?!\d)")


def parse_opencode_version(output: str) -> Optional[str]:
    """Extract the first semantic version from OpenCode CLI output."""
    match = _VERSION_PATTERN.search(output or "")
    if not match:
        return None
    return ".".join(match.groups())


def opencode_generation(version: Optional[str]) -> str:
    """Return the plugin generation for an OpenCode version."""
    if not version:
        return "unknown"
    try:
        major = int(version.split(".", 1)[0])
    except (AttributeError, TypeError, ValueError):
        return "unknown"
    if major == 1:
        return "v1"
    if major >= 2:
        return "v2"
    return "unknown"


def detect_opencode_version(executable: Optional[str] = None) -> Optional[str]:
    """Read the installed OpenCode CLI version without raising on failures."""
    # The override is useful for isolated version-matrix tests. Normal setup,
    # doctor, and console health checks leave it unset and inspect the active
    # ``opencode`` executable instead.
    configured = os.environ.get("AI_GUARDIAN_OPENCODE_VERSION")
    if configured:
        return parse_opencode_version(configured)

    binary = executable or shutil.which("opencode")
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    return parse_opencode_version(
        "\n".join(filter(None, (result.stdout, result.stderr)))
    )


def detect_opencode_runtime(executable: Optional[str] = None) -> Dict[str, Any]:
    """Return version, generation, and package metadata for the CLI runtime."""
    binary = executable or shutil.which("opencode")
    version = detect_opencode_version(binary)
    generation = opencode_generation(version)
    package = {
        "v1": "opencode-ai",
        "v2": "@opencode/cli",
    }.get(generation)
    return {
        "executable": binary,
        "version": version,
        "generation": generation,
        "package": package,
        "supported": generation in {"v1", "v2"},
    }


__all__ = [
    "detect_opencode_runtime",
    "detect_opencode_version",
    "opencode_generation",
    "parse_opencode_version",
]
