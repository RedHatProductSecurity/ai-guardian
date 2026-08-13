"""Load and merge allowlists from a target project directory.

When GuardedAgent operates on code from a different repo, the target
repo's suppression config should apply.  This module discovers config
files from a target directory and extracts ONLY allowlist/suppression
fields — never scanner settings like ``enabled``, ``action``, or
``sensitivity``.

Config files discovered from ``target_dir``:
  1. ``.ai-guardian/ai-guardian.json`` — per-scanner allowlist fields
  2. ``.aiguardignore.toml`` — per-scanner ``ignore_files`` paths
  3. ``.gitleaks.toml`` — ``[allowlist].paths`` → ``secret_scanning.ignore_files``
"""

import copy
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCANNER_ALLOWLIST_KEYS: Dict[str, List[str]] = {
    "secret_scanning": ["allowlist_patterns", "ignore_files", "ignore_tools"],
    "prompt_injection": ["allowlist_patterns"],
    "context_poisoning": ["allowlist_patterns"],
    "code_scanning": ["allowlist", "ignore_files"],
    "supply_chain": ["allowlist_paths"],
    "exfil_detection": ["allowlist_patterns"],
    "scan_pii": ["allowlist_patterns", "ignore_files", "ignore_tools"],
    "scan_offensive": ["allowlist_patterns", "ignore_files", "ignore_tools"],
    "image_scanning": ["ignore_files", "ignore_tools"],
}

_BROAD_PATH_PATTERNS = frozenset({"*", "**", "**/*"})


def _validate_path_pattern(pattern: str) -> bool:
    """Return False for overly broad or traversal path patterns."""
    if ".." in pattern.split("/"):
        logger.warning("Blocked target config path with '..': '%s'", pattern)
        return False
    if pattern in _BROAD_PATH_PATTERNS:
        logger.warning("Blocked overly broad target config path: '%s'", pattern)
        return False
    return True


def _extract_allowlists_from_config(
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract only allowlist fields from a full ai-guardian config dict."""
    overlay: Dict[str, Any] = {}

    for section_key, allowlist_keys in SCANNER_ALLOWLIST_KEYS.items():
        section = config.get(section_key)
        if not isinstance(section, dict):
            continue

        extracted: Dict[str, Any] = {}
        for key in allowlist_keys:
            value = section.get(key)
            if not isinstance(value, list) or not value:
                continue
            extracted[key] = list(value)

        if extracted:
            overlay[section_key] = extracted

    return overlay


def _validate_overlay_patterns(overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Validate allowlist_patterns in an overlay, removing dangerous ones.

    Mutates *overlay* in place and returns it.  Callers must pass a dict
    they own (not a shared reference).
    """
    from ai_guardian.allowlist_utils import validate_allowlist_patterns

    for section_key, section in overlay.items():
        if not isinstance(section, dict):
            continue

        for key in ("allowlist_patterns", "allowlist"):
            patterns = section.get(key)
            if not isinstance(patterns, list):
                continue
            safe = validate_allowlist_patterns(patterns)
            if len(safe) < len(patterns):
                logger.warning(
                    "Target config %s.%s: %d of %d patterns blocked by validation",
                    section_key,
                    key,
                    len(patterns) - len(safe),
                    len(patterns),
                )
            section[key] = safe

        for key in ("ignore_files", "ignore_tools", "allowlist_paths"):
            paths = section.get(key)
            if not isinstance(paths, list):
                continue
            safe = [p for p in paths if _validate_path_pattern(p)]
            section[key] = safe

    return overlay


def _load_target_ai_guardian_json(target_dir: Path) -> Dict[str, Any]:
    """Load .ai-guardian/ai-guardian.json from target_dir, extract allowlists."""
    config_path = target_dir / ".ai-guardian" / "ai-guardian.json"
    if not config_path.is_file():
        return {}

    try:
        with open(config_path, "r") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load target config %s: %s", config_path, exc)
        return {}

    if not isinstance(config, dict):
        return {}

    return _extract_allowlists_from_config(config)


def _load_target_aiguardignore(target_dir: Path) -> Dict[str, Any]:
    """Load .aiguardignore.toml from target_dir, return as config overlay."""
    try:
        from ai_guardian.aiguardignore import load_aiguardignore
    except ImportError:
        return {}

    aig = load_aiguardignore(project_root=target_dir)
    if aig is None:
        return {}

    overlay: Dict[str, Any] = {}

    for scanner_type, paths in aig.scanner_paths.items():
        if scanner_type not in SCANNER_ALLOWLIST_KEYS:
            continue
        safe = [p for p in paths if _validate_path_pattern(p)]
        if safe:
            overlay.setdefault(scanner_type, {}).setdefault("ignore_files", []).extend(
                safe
            )

    if aig.global_paths:
        safe_global = [p for p in aig.global_paths if _validate_path_pattern(p)]
        if safe_global:
            for section_key in SCANNER_ALLOWLIST_KEYS:
                if "ignore_files" in SCANNER_ALLOWLIST_KEYS[section_key]:
                    overlay.setdefault(section_key, {}).setdefault(
                        "ignore_files", []
                    ).extend(safe_global)

    return overlay


def _load_target_gitleaks_toml(target_dir: Path) -> Dict[str, Any]:
    """Load .gitleaks.toml allowlist.paths from target_dir."""
    try:
        from ai_guardian.scanners.gitleaks import load_gitleaks_allowlist
    except ImportError:
        return {}

    allowlist = load_gitleaks_allowlist(project_root=target_dir)
    if allowlist is None or not allowlist.paths:
        return {}

    safe = [p for p in allowlist.paths if _validate_path_pattern(p)]
    if not safe:
        return {}

    return {"secret_scanning": {"ignore_files": safe}}


def load_target_allowlists(target_dir: str) -> Dict[str, Any]:
    """Load allowlist/suppression data from a target project directory.

    Discovers and reads config files from *target_dir*, extracts only
    allowlist fields, validates patterns, and returns a config overlay.

    Args:
        target_dir: Path to the target project directory.

    Returns:
        Config overlay dict containing only allowlist fields, ready for
        merging into the base config.  Empty dict if nothing found.
    """
    target = Path(target_dir).resolve()
    if not target.is_dir():
        logger.warning("target_dir is not a directory: %s", target_dir)
        return {}

    from ai_guardian.config.utils import deep_merge

    overlay: Dict[str, Any] = {}
    _no_global_only: frozenset = frozenset()

    ai_guardian_overlay = _load_target_ai_guardian_json(target)
    if ai_guardian_overlay:
        overlay = deep_merge(
            overlay, ai_guardian_overlay, global_only_sections=_no_global_only
        )
        logger.info(
            "Loaded target allowlists from %s/.ai-guardian/ai-guardian.json "
            "(%d scanner sections)",
            target_dir,
            len(ai_guardian_overlay),
        )

    aiguardignore_overlay = _load_target_aiguardignore(target)
    if aiguardignore_overlay:
        overlay = deep_merge(
            overlay, aiguardignore_overlay, global_only_sections=_no_global_only
        )
        logger.info(
            "Loaded target ignore paths from %s/.aiguardignore.toml "
            "(%d scanner sections)",
            target_dir,
            len(aiguardignore_overlay),
        )

    gitleaks_overlay = _load_target_gitleaks_toml(target)
    if gitleaks_overlay:
        overlay = deep_merge(
            overlay, gitleaks_overlay, global_only_sections=_no_global_only
        )
        logger.info(
            "Loaded target gitleaks paths from %s/.gitleaks.toml",
            target_dir,
        )

    if overlay:
        overlay = _validate_overlay_patterns(overlay)

    return overlay


def merge_target_allowlists(
    base_config: Optional[Dict[str, Any]],
    target_dir: str,
) -> Dict[str, Any]:
    """Load target allowlists and merge into a base config.

    Loads suppression data from *target_dir*'s config files and
    deep-merges it into *base_config*.  Only list fields (allowlists,
    ignore patterns) are appended; scanner settings are never changed.

    Args:
        base_config: Base config dict (may be None or empty).
        target_dir: Path to the target project directory.

    Returns:
        Merged config dict.  Returns a copy of *base_config* if no
        target allowlists are found.
    """
    base = copy.deepcopy(base_config) if base_config else {}

    overlay = load_target_allowlists(target_dir)
    if not overlay:
        return base

    for section_key, section_overlay in overlay.items():
        if not isinstance(section_overlay, dict):
            continue
        base_section = base.setdefault(section_key, {})
        for field_key, values in section_overlay.items():
            if not isinstance(values, list):
                continue
            existing = base_section.get(field_key, [])
            if not isinstance(existing, list):
                existing = []
            seen = set(str(v) for v in existing)
            merged = list(existing)
            for v in values:
                if str(v) not in seen:
                    seen.add(str(v))
                    merged.append(v)
            base_section[field_key] = merged

    return base
