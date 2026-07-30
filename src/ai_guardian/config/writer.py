"""Safe config file writer with file locking for allowlist pattern management.

Used by the ask dialog to atomically add allowlist patterns to ai-guardian.json
without corrupting the config when multiple hook subprocesses write concurrently.

Also provides scoped config read/write/delete/provenance utilities for the
Global/Project scope selector feature.
"""

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

try:
    import fcntl

    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

from ai_guardian.allowlist_utils import validate_allowlist_patterns
from ai_guardian.config.utils import (
    get_config_dir,
    get_project_config_path,
    GLOBAL_ONLY_SECTIONS,
    _find_git_root,
)

logger = logging.getLogger(__name__)


def _atomic_config_update(
    config_path: Path,
    updater_fn: Callable[[dict], Tuple[bool, str]],
) -> bool:
    """Read config, apply updater_fn, write atomically with file locking.

    Args:
        config_path: Path to ai-guardian.json.
        updater_fn: Called with the config dict. Must mutate it in place and
                    return (already_exists, log_message). If already_exists is
                    True, the file is not rewritten.

    Returns:
        True on success, False on failure.
    """
    lock_path = str(config_path) + ".lock"

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            if HAS_FCNTL:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            elif sys.platform == "win32":
                try:
                    import msvcrt

                    msvcrt.locking(lock_fd, msvcrt.LK_LOCK, 1)
                except (ImportError, OSError):
                    pass

            config = {}
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(f"Could not read config, starting fresh: {e}")
                    config = {}

            already_exists, log_msg = updater_fn(config)

            if already_exists:
                logger.info(log_msg)
                return True

            fd, tmp_path = tempfile.mkstemp(
                dir=str(config_path.parent),
                prefix=".ai-guardian-",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2)
                    f.write("\n")
                os.replace(tmp_path, str(config_path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            try:
                from ai_guardian.config.loaders import _clear_config_cache

                _clear_config_cache()
            except ImportError:
                pass  # intentionally silent — optional dependency

            logger.info(log_msg)
            return True

        finally:
            if HAS_FCNTL:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    except OSError as e:
        logger.error(f"Failed to write config: {e}")
        return False


def _ensure_section(config: dict, section_name: str) -> dict:
    """Ensure config[section_name] exists as a dict. Returns the section."""
    if section_name not in config:
        config[section_name] = {}
    section = config[section_name]
    if not isinstance(section, dict):
        config[section_name] = section = {}
    return section


def _ensure_list(section: dict, key: str) -> list:
    """Ensure section[key] exists as a list. Returns the list."""
    items = section.get(key, [])
    if not isinstance(items, list):
        items = []
    return items


def _parse_permission_pattern(pattern: str) -> Tuple[str, list]:
    """Parse a permission pattern string into (matcher, patterns_list).

    Format: "matcher:value" → ("matcher", ["value"])
    No colon: "matcher" → ("matcher", ["*"])
    """
    if ":" in pattern:
        parts = pattern.split(":", 1)
        return parts[0], [parts[1]]
    return pattern, ["*"]


def add_allowlist_pattern(
    config_section: str,
    pattern: str,
    valid_until: Optional[str] = None,
    config_path: Optional[Path] = None,
) -> bool:
    """Add a pattern to a section's allowlist_patterns array in ai-guardian.json.

    Args:
        config_section: Config section key (e.g. "secret_scanning", "prompt_injection").
        pattern: Regex pattern string to add.
        valid_until: Optional ISO 8601 expiration timestamp.
        config_path: Override config file path (defaults to global config).

    Returns:
        True if pattern was added successfully, False on failure.
    """
    if not pattern or not config_section:
        return False

    if config_path is None:
        config_path = _resolve_config_path("global")

    pattern_entry = pattern
    if valid_until:
        pattern_entry = {"pattern": pattern, "valid_until": valid_until}

    if not validate_allowlist_patterns([pattern_entry]):
        logger.error(f"Pattern rejected by safety validation: {pattern}")
        return False

    def updater(config):
        section = _ensure_section(config, config_section)
        patterns = _ensure_list(section, "allowlist_patterns")
        for existing in patterns:
            existing_str = (
                existing if isinstance(existing, str) else existing.get("pattern", "")
            )
            if existing_str == pattern:
                return (
                    True,
                    f"Pattern already exists in {config_section}.allowlist_patterns",
                )
        patterns.append(pattern_entry)
        section["allowlist_patterns"] = patterns
        return False, f"Added pattern to {config_section}.allowlist_patterns: {pattern}"

    return _atomic_config_update(config_path, updater)


def _add_to_config_list(
    section_name: str,
    list_key: str,
    value: str,
    config_path: Optional[Path] = None,
    normalizer: Optional[Callable[[str], str]] = None,
) -> bool:
    """Add a value to a section's list in ai-guardian.json.

    Generic helper for the common pattern: ensure section exists, ensure list
    exists, dedup-check, append, write atomically.
    """
    if not value:
        return False
    if normalizer:
        value = normalizer(value)
        if not value:
            return False
    if config_path is None:
        config_path = _resolve_config_path("global")

    def updater(config):
        section = _ensure_section(config, section_name)
        items = _ensure_list(section, list_key)
        if value in items:
            return True, f"Value already in {section_name}.{list_key}: {value}"
        items.append(value)
        section[list_key] = items
        return False, f"Added to {section_name}.{list_key}: {value}"

    return _atomic_config_update(config_path, updater)


def add_directory_exclusion(
    pattern: str,
    config_path: Optional[Path] = None,
) -> bool:
    """Add a glob pattern to directory_rules.exclusions in ai-guardian.json."""
    return _add_to_config_list("directory_rules", "exclusions", pattern, config_path)


def add_supply_chain_path(
    pattern: str,
    config_path: Optional[Path] = None,
) -> bool:
    """Add a glob pattern to supply_chain.allowlist_paths in ai-guardian.json."""
    return _add_to_config_list("supply_chain", "allowlist_paths", pattern, config_path)


def add_allowed_domain(
    domain: str,
    config_path: Optional[Path] = None,
) -> bool:
    """Add a domain to ssrf_protection.allowed_domains in ai-guardian.json."""
    return _add_to_config_list(
        "ssrf_protection",
        "allowed_domains",
        domain,
        config_path,
        normalizer=lambda d: d.lower().strip(),
    )


def add_config_ignore_file(
    pattern: str,
    config_path: Optional[Path] = None,
) -> bool:
    """Add a glob pattern to config_file_scanning.ignore_files in ai-guardian.json."""
    return _add_to_config_list(
        "config_file_scanning", "ignore_files", pattern, config_path
    )


def add_permission_rule(
    matcher: str,
    patterns: list,
    config_path: Optional[Path] = None,
) -> bool:
    """Add an allow rule to permissions.rules in ai-guardian.json.

    Args:
        matcher: Tool matcher string (e.g. "Bash", "Skill", "mcp__server__tool").
        patterns: List of pattern strings to allow (e.g. ["npm test"]).
        config_path: Override config file path (defaults to global config).

    Returns:
        True if rule was added successfully, False on failure.
    """
    if not matcher:
        return False
    if not patterns:
        return False

    if config_path is None:
        config_path = _resolve_config_path("global")

    def updater(config):
        section = _ensure_section(config, "permissions")
        rules = _ensure_list(section, "rules")
        for existing in rules:
            if existing.get("mode") == "allow" and existing.get("matcher") == matcher:
                existing_patterns = existing.get("patterns", [])
                new_patterns = [p for p in patterns if p not in existing_patterns]
                if not new_patterns:
                    return True, f"Patterns already in rule for {matcher}"
                existing_patterns.extend(new_patterns)
                existing["patterns"] = existing_patterns
                section["rules"] = rules
                return (
                    False,
                    f"Merged patterns into existing rule for {matcher}: {new_patterns}",
                )
        new_rule = {"mode": "allow", "matcher": matcher, "patterns": patterns}
        rules.append(new_rule)
        section["rules"] = rules
        return False, f"Added permission rule: {new_rule}"

    return _atomic_config_update(config_path, updater)


def save_ask_pattern(
    config_section: str,
    pattern: str,
    config_path: Optional[Path] = None,
) -> bool:
    """Save an ask dialog 'Allow Always' pattern to the correct config location.

    Unified dispatcher — routes to the appropriate writer based on config_section.
    Handles permission pattern parsing ("matcher:value" format).

    Args:
        config_section: The config section that triggered the violation.
        pattern: The allowlist pattern from the ask dialog.
        config_path: Override config file path (defaults to global config).

    Returns:
        True on success, False on failure.
    """
    if config_section == "ssrf_protection":
        return add_allowed_domain(pattern, config_path=config_path)
    elif config_section == "directory_rules":
        return add_directory_exclusion(pattern, config_path=config_path)
    elif config_section == "supply_chain":
        return add_supply_chain_path(pattern, config_path=config_path)
    elif config_section == "config_file_scanning":
        return add_config_ignore_file(pattern, config_path=config_path)
    elif config_section == "permissions":
        matcher, rule_patterns = _parse_permission_pattern(pattern)
        return add_permission_rule(matcher, rule_patterns, config_path=config_path)
    else:
        return add_allowlist_pattern(config_section, pattern, config_path=config_path)


# ---------------------------------------------------------------------------
# Scoped config read / write / delete / provenance
# ---------------------------------------------------------------------------


def _resolve_config_path(scope: str, project_dir: Optional[str] = None) -> Path:
    """Resolve config file path for the given scope."""
    if scope == "project":
        if project_dir:
            root = Path(project_dir)
            standard = root / ".ai-guardian" / "ai-guardian.json"
            if standard.exists():
                return standard
            legacy = root / "ai-guardian.json"
            if legacy.exists():
                return legacy
            return standard
        existing = get_project_config_path()
        if existing:
            return existing
        root = _find_git_root() or Path.cwd()
        return root / ".ai-guardian" / "ai-guardian.json"
    return get_config_dir() / "ai-guardian.json"


def _load_json_file(path: Path) -> dict:
    """Load a JSON file, returning {} on missing/invalid."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Could not read %s: %s", path, e)
        return {}


def load_scoped_config(
    scope: str = "merged",
    project_dir: Optional[str] = None,
) -> dict:
    """Load config for a specific scope.

    Args:
        scope: "merged" (effective), "global" (global only), "project" (overrides only).
        project_dir: Project directory for project scope discovery.

    Returns:
        Config dict for the requested scope.
    """
    if scope == "merged":
        try:
            from ai_guardian.config.loaders import _load_config_file

            result, _ = _load_config_file()
            return result or {}
        except Exception:
            global_cfg = _load_json_file(_resolve_config_path("global"))
            project_cfg = _load_json_file(_resolve_config_path("project", project_dir))
            if project_cfg:
                from ai_guardian.config.utils import deep_merge

                return deep_merge(global_cfg, project_cfg)
            return global_cfg
    elif scope == "global":
        return _load_json_file(_resolve_config_path("global"))
    elif scope == "project":
        return _load_json_file(_resolve_config_path("project", project_dir))
    return {}


def write_scoped_config(
    scope: str,
    section: str,
    key: Optional[str],
    value: Any,
    project_dir: Optional[str] = None,
) -> Tuple[bool, str]:
    """Write a config value to the specified scope.

    Args:
        scope: "global" or "project".
        section: Config section (e.g. "secret_scanning").
        key: Key within section (e.g. "action"). None to set the entire section.
        value: Value to write.
        project_dir: Project directory (required for project scope when no
                     project config exists yet).

    Returns:
        (success, message) tuple.
    """
    if scope == "project" and section in GLOBAL_ONLY_SECTIONS:
        return (
            False,
            f"Section '{section}' is global-only and cannot be set per-project",
        )

    config_path = _resolve_config_path(scope, project_dir)

    def updater(config: dict) -> Tuple[bool, str]:
        sect = _ensure_section(config, section)
        if key is None:
            config[section] = value
        else:
            sect[key] = value
        return False, f"Set {section}.{key} = {value!r} [{scope}]"

    success = _atomic_config_update(config_path, updater)
    if success:
        return True, f"Saved {section}.{key} to {scope} config at {config_path}"
    return False, f"Failed to write {section}.{key} to {scope} config"


def delete_project_override(
    section: str,
    key: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> Tuple[bool, str]:
    """Remove a project-level override, reverting to global default.

    Args:
        section: Config section (e.g. "secret_scanning").
        key: Key to remove. None removes the entire section override.
        project_dir: Project directory for config discovery.

    Returns:
        (success, message) tuple.
    """
    config_path = _resolve_config_path("project", project_dir)
    if not config_path.exists():
        return True, "No project config exists — already using global defaults"

    def updater(config: dict) -> Tuple[bool, str]:
        if section not in config:
            return (
                True,
                f"Section '{section}' not in project config — nothing to remove",
            )
        if key is None:
            del config[section]
            return False, f"Removed project override for entire section '{section}'"
        sect = config[section]
        if isinstance(sect, dict) and key in sect:
            del sect[key]
            if not sect:
                del config[section]
            return False, f"Removed project override for {section}.{key}"
        return True, f"{section}.{key} not in project config — nothing to remove"

    success = _atomic_config_update(config_path, updater)
    if success:
        return True, f"Removed project override for {section}.{key}"
    return False, f"Failed to remove project override for {section}.{key}"


def compute_provenance(
    project_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute per-key provenance showing which scope each value comes from.

    Returns:
        Nested dict mirroring config structure with leaf values of
        "global", "project", or "merged" (for concatenated lists).
    """
    return _compute_provenance_impl(project_dir, detailed=False)


def compute_detailed_provenance(
    project_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute per-key provenance with per-list-item source info.

    Like ``compute_provenance`` but list values return a list of
    ``{"value": item, "source": "global"|"project"}`` dicts instead of
    the string ``"merged"``.
    """
    return _compute_provenance_impl(project_dir, detailed=True)


def _compute_provenance_impl(
    project_dir: Optional[str],
    detailed: bool,
) -> Dict[str, Any]:
    """Shared implementation for compute_provenance / compute_detailed_provenance."""
    global_cfg = _load_json_file(_resolve_config_path("global"))
    project_cfg = _load_json_file(_resolve_config_path("project", project_dir))

    if not project_cfg:
        return _mark_all_provenance(global_cfg, "global", detailed)

    from ai_guardian.config.utils import deep_merge

    merged = deep_merge(global_cfg, project_cfg)
    return _compute_provenance_recursive(global_cfg, project_cfg, merged, detailed)


def _mark_all_provenance(config: dict, source: str, detailed: bool = False) -> dict:
    """Mark all keys in a config dict as coming from the given source."""
    result: Dict[str, Any] = {}
    for key, value in config.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            result[key] = _mark_all_provenance(value, source, detailed)
        elif detailed and isinstance(value, list):
            result[key] = [{"value": item, "source": source} for item in value]
        else:
            result[key] = source
    return result


def _compute_provenance_recursive(
    global_cfg: dict,
    project_cfg: dict,
    merged: dict,
    detailed: bool = False,
) -> Dict[str, Any]:
    """Recursively compute provenance for merged config."""
    result: Dict[str, Any] = {}
    for key in merged:
        if key.startswith("_"):
            continue
        in_global = key in global_cfg
        in_project = key in project_cfg
        m_val = merged[key]

        if in_project and in_global:
            g_val = global_cfg[key]
            p_val = project_cfg[key]
            if (
                isinstance(m_val, dict)
                and isinstance(g_val, dict)
                and isinstance(p_val, dict)
            ):
                result[key] = _compute_provenance_recursive(
                    g_val, p_val, m_val, detailed
                )
            elif isinstance(m_val, list):
                if detailed:
                    g_list = g_val if isinstance(g_val, list) else []
                    g_set = set(str(i) for i in g_list)
                    result[key] = [
                        {
                            "value": item,
                            "source": "global" if str(item) in g_set else "project",
                        }
                        for item in m_val
                    ]
                else:
                    result[key] = "merged"
            else:
                result[key] = "project"
        elif in_project:
            if isinstance(m_val, dict):
                result[key] = _mark_all_provenance(m_val, "project", detailed)
            elif detailed and isinstance(m_val, list):
                result[key] = [{"value": item, "source": "project"} for item in m_val]
            else:
                result[key] = "project"
        else:
            if isinstance(m_val, dict):
                result[key] = _mark_all_provenance(m_val, "global", detailed)
            elif detailed and isinstance(m_val, list):
                result[key] = [{"value": item, "source": "global"} for item in m_val]
            else:
                result[key] = "global"
    return result


# ---------------------------------------------------------------------------
# Text formatters for effective config display
# ---------------------------------------------------------------------------

_PROVENANCE_LABELS = {
    "global": "Global",
    "project": "Project override",
}


def format_provenance_text(
    config: dict,
    provenance: dict,
    indent: int = 0,
) -> str:
    """Render config with per-key provenance annotations.

    Returns a plain-text tree like::

        secret_scanning:
          enabled:            true                    (Global)
          action:             ask                     (Project override)
          allowlist_patterns:
            - .*test.*\\.py                           (Global)
            - YOUR_TOKEN                              (Project override)
    """
    lines: list = []
    prefix = "  " * indent

    for key in sorted(config.keys()):
        if key.startswith("_"):
            continue
        value = config[key]
        prov = provenance.get(key)

        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            if isinstance(prov, dict):
                lines.append(format_provenance_text(value, prov, indent + 1))
            else:
                label = _PROVENANCE_LABELS.get(prov, prov or "")
                for sub_key in sorted(value.keys()):
                    if sub_key.startswith("_"):
                        continue
                    sub_val = _format_scalar(value[sub_key])
                    lines.append(f"{prefix}  {sub_key}: {sub_val:<30s} ({label})")
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}:")
            if isinstance(prov, list):
                for entry in prov:
                    item_val = entry.get("value", "")
                    item_src = entry.get("source", "")
                    label = _PROVENANCE_LABELS.get(item_src, item_src)
                    lines.append(
                        f"{prefix}  - {_format_scalar(item_val):<28s} ({label})"
                    )
            else:
                label = _PROVENANCE_LABELS.get(prov, prov or "")
                for item in value:
                    lines.append(f"{prefix}  - {_format_scalar(item):<28s} ({label})")
        else:
            label = _PROVENANCE_LABELS.get(prov, prov or "")
            lines.append(f"{prefix}{key}: {_format_scalar(value):<30s} ({label})")

    return "\n".join(lines)


def format_diff_text(
    project_cfg: dict,
    provenance: dict,
    indent: int = 0,
) -> str:
    """Render only project overrides (diff from global).

    Shows keys where provenance is "project" or list items sourced from project.
    """
    lines: list = []
    prefix = "  " * indent

    for key in sorted(project_cfg.keys()):
        if key.startswith("_"):
            continue
        value = project_cfg[key]
        prov = provenance.get(key)

        if isinstance(value, dict) and isinstance(prov, dict):
            child_text = format_diff_text(value, prov, indent + 1)
            if child_text.strip():
                lines.append(f"{prefix}{key}:")
                lines.append(child_text)
        elif isinstance(value, list) and isinstance(prov, list):
            project_items = [e for e in prov if e.get("source") == "project"]
            if project_items:
                lines.append(f"{prefix}{key}:")
                for entry in project_items:
                    lines.append(f"{prefix}  - {_format_scalar(entry['value'])}")
        elif prov == "project":
            lines.append(f"{prefix}{key}: {_format_scalar(value)}")

    return "\n".join(lines)


def _format_scalar(value) -> str:
    """Format a scalar config value for display."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return json.dumps(value)
    if value is None:
        return "null"
    return str(value)
