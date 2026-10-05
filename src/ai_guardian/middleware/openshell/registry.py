"""OpenShell release-to-adapter selection.

OpenShell releases within the same major release family may reuse the newest
older adapter.  The selected adapter still has to pass the runtime protocol
and capability handshake; release-number fallback is only the dispatch step.
"""

from __future__ import annotations

import importlib
import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping, Optional

import yaml

logger = logging.getLogger(__name__)

_VERSION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])v?(\d+)\.(\d+)\.(\d+)" r"(?:[-+][0-9A-Za-z.-]+)?(?![A-Za-z0-9])"
)


class OpenShellCompatibilityError(ValueError):
    """Raised when no safe adapter exists for an OpenShell release."""


@dataclass(frozen=True, order=True)
class OpenShellVersion:
    """Comparable OpenShell release version without a runtime dependency."""

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> "OpenShellVersion":
        if not isinstance(value, str) or not value.strip():
            raise OpenShellCompatibilityError(
                "OpenShell version must be a semantic version such as 0.1.2"
            )
        match = _VERSION_PATTERN.search(value.strip())
        if match is None:
            raise OpenShellCompatibilityError(
                f"unable to parse OpenShell version: {value!r}"
            )
        return cls(*(int(group) for group in match.groups()[:3]))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class OpenShellAdapterSpec:
    """One checked-in implementation and its baseline OpenShell release."""

    version: OpenShellVersion
    module: str


DEFAULT_OPEN_SHELL_VERSION = OpenShellVersion(0, 1, 2)
ADAPTERS = (
    OpenShellAdapterSpec(
        version=DEFAULT_OPEN_SHELL_VERSION,
        module="ai_guardian.middleware.openshell.v0_1_2.server",
    ),
)


def _version_from_config(path: str | Path | None) -> Optional[OpenShellVersion]:
    if not path:
        return None
    config_path = Path(path).expanduser()
    try:
        text = config_path.read_text(encoding="utf-8")
        raw: Any = (
            json.loads(text)
            if config_path.suffix.lower() == ".json"
            else yaml.safe_load(text)
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        # The authoritative loader will report malformed policy details later.
        # Do not make adapter discovery hide that more useful diagnostic.
        logger.debug(
            "unable to inspect middleware config for OpenShell version: %s", exc
        )
        return None
    if not isinstance(raw, Mapping) or raw.get("openshell_version") is None:
        return None
    return OpenShellVersion.parse(str(raw["openshell_version"]))


def detect_installed_openshell_version(
    executable: str = "openshell",
) -> Optional[OpenShellVersion]:
    """Read the locally installed OpenShell CLI version, when available."""

    command = shutil.which(executable)
    if command is None:
        return None
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("unable to detect installed OpenShell version: %s", exc)
        return None
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    match = _VERSION_PATTERN.search(output)
    if match is None:
        logger.warning("OpenShell CLI did not report a semantic version")
        return None
    return OpenShellVersion.parse(match.group(0))


def resolve_openshell_version(
    explicit: Optional[str] = None,
    *,
    config_path: str | Path | None = None,
) -> tuple[OpenShellVersion, str]:
    """Resolve a release from CLI override, config, CLI detection, or default."""

    if explicit:
        return OpenShellVersion.parse(explicit), "CLI override"
    configured = _version_from_config(config_path)
    if configured is not None:
        return configured, "middleware config"
    detected = detect_installed_openshell_version()
    if detected is not None:
        return detected, "installed OpenShell CLI"
    return DEFAULT_OPEN_SHELL_VERSION, "default supported adapter"


def select_adapter(
    explicit: Optional[str] = None,
    *,
    config_path: str | Path | None = None,
) -> tuple[OpenShellAdapterSpec, OpenShellVersion, str]:
    """Select the newest adapter not newer than the target release.

    Fallback is allowed across minor and patch releases only while the first
    version component is unchanged.  For example, an installed ``0.2.1``
    selects the checked-in ``0.1.2`` adapter.  A ``1.0.0`` release does not.
    """

    target, source = resolve_openshell_version(explicit, config_path=config_path)
    candidates = [
        adapter
        for adapter in ADAPTERS
        if adapter.version.major == target.major and adapter.version <= target
    ]
    if not candidates:
        supported = ", ".join(str(adapter.version) for adapter in ADAPTERS)
        raise OpenShellCompatibilityError(
            f"no OpenShell middleware adapter supports release {target}; "
            f"available baselines: {supported}"
        )
    selected = max(candidates, key=lambda adapter: adapter.version)
    return selected, target, source


def load_adapter(
    explicit: Optional[str] = None,
    *,
    config_path: str | Path | None = None,
) -> tuple[OpenShellAdapterSpec, OpenShellVersion, str, ModuleType]:
    """Resolve and import the selected adapter module."""

    adapter, target, source = select_adapter(explicit, config_path=config_path)
    return adapter, target, source, importlib.import_module(adapter.module)


__all__ = [
    "ADAPTERS",
    "DEFAULT_OPEN_SHELL_VERSION",
    "OpenShellAdapterSpec",
    "OpenShellCompatibilityError",
    "OpenShellVersion",
    "detect_installed_openshell_version",
    "load_adapter",
    "resolve_openshell_version",
    "select_adapter",
]
