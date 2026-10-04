"""OpenCode runtime generation and version helpers."""

import os
import re
import shutil
import subprocess
from typing import Any, Dict, Optional, Tuple

_VERSION_PATTERN = re.compile(r"(?<!\d)v?(\d+)\.(\d+)\.(\d+)(?!\d)")
_VERSION_CACHE: Dict[
    Tuple[Optional[str], Optional[str], Optional[str]], Optional[str]
] = {}


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


def clear_opencode_version_cache() -> None:
    """Clear cached CLI version probes, primarily for tests and upgrades."""
    _VERSION_CACHE.clear()


def detect_opencode_version(executable: Optional[str] = None) -> Optional[str]:
    """Read the installed OpenCode CLI version without raising on failures."""
    # The override is useful for isolated version-matrix tests. Normal setup,
    # doctor, and console health checks leave it unset and inspect the active
    # ``opencode`` executable instead.
    configured = os.environ.get("AI_GUARDIAN_OPENCODE_VERSION")
    if configured:
        binary = None
    else:
        binary = executable or shutil.which("opencode")

    cache_key = (executable, binary, configured)
    if cache_key in _VERSION_CACHE:
        return _VERSION_CACHE[cache_key]

    if configured:
        version = parse_opencode_version(configured)
    elif not binary:
        version = None
    else:
        try:
            result = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            version = None
        else:
            version = parse_opencode_version(
                "\n".join(filter(None, (result.stdout, result.stderr)))
            )

    _VERSION_CACHE[cache_key] = version
    return version


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
    "clear_opencode_version_cache",
    "detect_opencode_runtime",
    "detect_opencode_version",
    "opencode_generation",
    "parse_opencode_version",
]
