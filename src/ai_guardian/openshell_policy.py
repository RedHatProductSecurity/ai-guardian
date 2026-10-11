"""OpenShell policy discovery and validation helpers.

The tray needs a small amount of policy intelligence so it can offer useful
choices without exposing policy contents or silently treating an invalid YAML
file as an executable command.  OpenShell remains the authority that accepts
and applies the resulting policy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

NO_POLICY_CHOICE = "No additional policy"
POLICY_FILE_SUFFIXES = {".yaml", ".yml"}
POLICY_PATH_ENV = "AI_GUARDIAN_OPEN_SHELL_POLICY"
POLICY_DIR_ENV = "AI_GUARDIAN_OPEN_SHELL_POLICY_DIR"


@dataclass(frozen=True)
class OpenShellPolicyOption:
    """A safe, display-oriented description of one policy file."""

    path: Path
    label: str
    valid: bool
    summary: str
    error: Optional[str] = None

    @property
    def display(self) -> str:
        """Return the value shown in tray policy selectors."""
        state = "valid" if self.valid else f"invalid: {self.error}"
        return f"{self.label} — {self.summary} — {state}"


def _yaml_module():
    """Import YAML lazily so policy discovery does not affect CLI startup."""
    import yaml

    return yaml


def validate_openshell_policy(
    value: Any, source: Path, *, require_version: bool = True
) -> Dict[str, Any]:
    """Validate the safe structural subset needed before OpenShell accepts it."""
    if not isinstance(value, dict):
        raise ValueError(f"policy must contain a YAML mapping: {source}")

    if require_version and value.get("version") != 1:
        raise ValueError(f"OpenShell policy version must be 1: {source}")
    if "version" in value and value.get("version") != 1:
        raise ValueError(f"OpenShell policy version must be 1: {source}")

    for section in (
        "filesystem_policy",
        "landlock",
        "network_policies",
        "network_middlewares",
    ):
        section_value = value.get(section)
        if section in value and not isinstance(section_value, dict):
            raise ValueError(f"{section} must be a YAML mapping: {source}")

    network_middlewares = value.get("network_middlewares")
    if network_middlewares is not None:
        if not isinstance(network_middlewares, dict):
            raise ValueError(f"network_middlewares must be a YAML mapping: {source}")
        for policy_name, middleware in network_middlewares.items():
            if not isinstance(policy_name, str) or not policy_name.strip():
                raise ValueError(
                    f"network_middlewares contains an empty name: {source}"
                )
            if not isinstance(middleware, dict):
                raise ValueError(
                    f"network_middlewares.{policy_name} must be a YAML mapping: {source}"
                )
            registration = middleware.get("middleware")
            if not isinstance(registration, str) or not registration.strip():
                raise ValueError(
                    f"network_middlewares.{policy_name}.middleware is required: {source}"
                )

    return dict(value)


def load_openshell_policy(
    path: Path, *, require_version: bool = False
) -> Dict[str, Any]:
    """Load and structurally validate one OpenShell policy file."""
    yaml = _yaml_module()
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(
            f"cannot read OpenShell policy fragment {path}: {exc}"
        ) from exc
    except UnicodeError as exc:
        raise ValueError(
            f"cannot decode OpenShell policy fragment {path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(
            f"invalid YAML in OpenShell policy fragment {path}: {exc}"
        ) from exc

    if value is None:
        value = {}
    return validate_openshell_policy(value, path, require_version=require_version)


def summarize_openshell_policy(policy: Dict[str, Any]) -> str:
    """Return a concise, non-sensitive policy preview."""
    sections: List[str] = [
        name
        for name in (
            "filesystem_policy",
            "landlock",
            "network_policies",
            "network_middlewares",
        )
        if name in policy
    ]
    middlewares = policy.get("network_middlewares")
    if isinstance(middlewares, dict) and middlewares:
        names = ", ".join(str(name) for name in middlewares)
        sections.append(f"middleware={names}")
    if not sections:
        return "empty policy"
    return ", ".join(sections)


def _friendly_policy_label(path: Path, policy: Dict[str, Any]) -> str:
    """Build a readable label without exposing policy values."""
    stem = path.stem
    for prefix in ("openshell-", "policy-"):
        if stem.lower().startswith(prefix):
            stem = stem[len(prefix) :]
            break
    label = stem.replace("_", " ").replace("-", " ").strip().title()
    if "network_middlewares" in policy:
        label = (
            f"{label} policy"
            if "middleware" in label.casefold()
            else f"{label} middleware policy"
        )
    return label or path.name


def _configured_policy_paths() -> Iterable[Path]:
    for variable in (POLICY_PATH_ENV, "AI_GUARDIAN_OPENSHELL_POLICY"):
        value = os.environ.get(variable)
        if value:
            yield Path(value).expanduser()


def _policy_roots() -> Iterable[Path]:
    """Return bounded, authoritative policy directories for discovery."""
    repository_root = Path(__file__).resolve().parents[2]
    source_container = repository_root / "container"
    installed_root = Path(__file__).resolve().parent / "sandbox_assets"
    yield source_container
    yield source_container / "policies"
    yield installed_root
    yield installed_root / "policies"

    cwd = Path.cwd()
    yield cwd / "container"
    yield cwd / "openshell-policies"
    yield cwd / ".openshell" / "policies"

    configured_dir = os.environ.get(POLICY_DIR_ENV)
    if configured_dir:
        yield Path(configured_dir).expanduser()

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home is None:
        try:
            xdg_config = Path.home() / ".config"
        except RuntimeError:
            return
    else:
        xdg_config = Path(xdg_config_home)
    try:
        xdg_config = xdg_config.expanduser()
    except RuntimeError:
        return
    yield xdg_config / "ai-guardian" / "openshell" / "policies"


def _iter_policy_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        if root.suffix.lower() in POLICY_FILE_SUFFIXES:
            yield root
        return
    if not root.is_dir():
        return

    repository_root = Path(__file__).resolve().parents[2]
    builtin_roots = {
        repository_root / "container",
        repository_root / "container" / "policies",
        Path(__file__).resolve().parent / "sandbox_assets",
        Path(__file__).resolve().parent / "sandbox_assets" / "policies",
    }
    try:
        is_builtin = root.resolve() in {path.resolve() for path in builtin_roots}
    except OSError:
        is_builtin = False

    # The repository contains top-level OpenShell overlays and a dedicated
    # middleware policy tree.  Do not scan unrelated container scenario YAML
    # files. User-configured directories are intentionally bounded to their own
    # tree, rather than scanning a whole home directory.
    patterns = (
        ("openshell-*.yaml", "openshell-*.yml") if is_builtin else ("*.yaml", "*.yml")
    )
    seen = set()
    for pattern in patterns:
        paths = root.glob(pattern) if is_builtin else root.rglob(pattern)
        for path in sorted(paths):
            if path.is_file() and path.suffix.lower() in POLICY_FILE_SUFFIXES:
                try:
                    identity = path.resolve()
                except OSError:
                    identity = path
                if identity not in seen:
                    seen.add(identity)
                    yield path


def discover_openshell_policies(
    extra_paths: Iterable[Path] = (),
) -> Tuple[OpenShellPolicyOption, ...]:
    """Discover policy files and retain invalid files with visible status."""
    candidates: List[Path] = list(_configured_policy_paths())
    candidates.extend(_policy_roots())
    candidates.extend(extra_paths)

    options: List[OpenShellPolicyOption] = []
    seen = set()
    for root in candidates:
        for path in _iter_policy_files(root):
            try:
                identity = path.resolve()
            except OSError:
                identity = path
            if identity in seen:
                continue
            seen.add(identity)
            try:
                policy = load_openshell_policy(path, require_version=True)
            except (OSError, ValueError, ImportError) as exc:
                options.append(
                    OpenShellPolicyOption(
                        path=path,
                        label=path.stem,
                        valid=False,
                        summary="unavailable",
                        error=str(exc),
                    )
                )
                continue
            options.append(
                OpenShellPolicyOption(
                    path=path,
                    label=_friendly_policy_label(path, policy),
                    valid=True,
                    summary=summarize_openshell_policy(policy),
                )
            )

    return tuple(sorted(options, key=lambda option: (not option.valid, option.display)))


def policy_choice_values(
    options: Iterable[OpenShellPolicyOption],
) -> Tuple[str, ...]:
    """Return values suitable for the tray form choice widget."""
    return (NO_POLICY_CHOICE, *(option.display for option in options))


def resolve_openshell_policy_choice(
    value: Any,
    options: Iterable[OpenShellPolicyOption],
) -> Optional[Path]:
    """Resolve a displayed policy choice or an editable custom path."""
    candidate = str(value or "").strip()
    if not candidate or candidate == NO_POLICY_CHOICE:
        return None
    for option in options:
        if candidate == option.display:
            return option.path
    return Path(candidate).expanduser()


__all__ = [
    "NO_POLICY_CHOICE",
    "OpenShellPolicyOption",
    "discover_openshell_policies",
    "load_openshell_policy",
    "policy_choice_values",
    "resolve_openshell_policy_choice",
    "summarize_openshell_policy",
    "validate_openshell_policy",
]
