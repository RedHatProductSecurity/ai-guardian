"""
Configuration loading functions for AI Guardian.

Handles loading and caching of ai-guardian.json configuration sections.
All _load_*_config() functions share a single mtime-based cache to avoid
redundant file reads within the same hook invocation.
"""

import copy
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ai_guardian.config.utils import (
    get_config_dir,
    get_project_config_path,
    get_project_dir,
    _clear_project_config_cache,
    _dedup_list,
    deep_merge,
    is_feature_enabled,
)

try:
    from ai_guardian import aiguardignore as _aiguardignore_cfg

    HAS_AIGUARDIGNORE = True
except ImportError:
    HAS_AIGUARDIGNORE = False

logger = logging.getLogger(__name__)


def _merge_aiguardignore(scanner_config, scanner_type, project_root=None):
    """Merge .aiguardignore.toml paths into a scanner config dict's ignore_files."""
    if not HAS_AIGUARDIGNORE:
        return scanner_config
    extra = _aiguardignore_cfg.get_ignore_paths(scanner_type, project_root=project_root)
    if not extra:
        return scanner_config
    if scanner_config is None:
        return {"ignore_files": list(extra)}
    result = dict(scanner_config)
    result["ignore_files"] = list(result.get("ignore_files", [])) + list(extra)
    return result


@dataclass
class _ConfigCacheEntry:
    """Cached config state to avoid redundant file reads."""

    result: Any = None  # (config_dict, error_msg) tuple or None
    global_mtime: Optional[float] = None
    project_mtime: Optional[float] = None
    global_path: Optional[Path] = None
    project_path: Optional[Path] = None
    overlay_mtime: Optional[float] = None
    overlay_path: Optional[str] = None
    inline_overlay_value: Optional[str] = None
    sdk_overlay_id: Optional[int] = None
    last_accessed: float = 0.0


# Per-project cache to avoid cross-project contamination (#1227)
_caches: dict[str, _ConfigCacheEntry] = {}  # cache_key -> entry

# SDK config overlay — set via configure() or env vars (#1139)
_sdk_overlay: Optional[Dict[str, Any]] = None


def _clear_config_cache(project_key: Optional[str] = None):
    """Clear the config file cache, forcing a re-read on next call.

    Args:
        project_key: If provided, clear only this project's entry.
                     If None, clear all entries (backward compat).
    """
    if project_key is not None:
        _caches.pop(project_key, None)
    else:
        _caches.clear()
    _clear_project_config_cache()


def configure(overlay: Optional[Dict[str, Any]] = None) -> None:
    """Set a programmatic SDK config overlay.

    The overlay is deep-merged on top of the resolved config
    (global + project), with the overlay winning for non-immutable fields.

    Unlike project configs, the SDK overlay CAN set global-only sections
    (daemon, mcp_server, etc.) since it represents the automation layer.

    Args:
        overlay: Dict to deep-merge on top of resolved config, or None to clear.
    """
    global _sdk_overlay
    _sdk_overlay = overlay
    _clear_config_cache()


def _resolve_sdk_overlay() -> Optional[Dict[str, Any]]:
    """Resolve the effective SDK overlay from all sources.

    Priority (highest to lowest):
    1. configure(overlay=dict) — programmatic API
    2. AI_GUARDIAN_CONFIG_INLINE env var — inline JSON string
    3. AI_GUARDIAN_CONFIG_OVERLAY env var — path to JSON file

    Higher-priority sources are deep-merged on top of lower-priority ones.

    Returns:
        Merged overlay dict, or None if no overlay is active.
    """
    result = None

    file_path = os.environ.get("AI_GUARDIAN_CONFIG_OVERLAY")
    if file_path:
        p = Path(file_path).expanduser()
        file_overlay, err = _load_json_config(p)
        if file_overlay is not None:
            result = file_overlay
        elif err:
            logger.warning("AI_GUARDIAN_CONFIG_OVERLAY error: %s", err)

    inline_json = os.environ.get("AI_GUARDIAN_CONFIG_INLINE")
    if inline_json:
        try:
            inline_overlay = json.loads(inline_json)
            if isinstance(inline_overlay, dict):
                if result is not None:
                    result = deep_merge(
                        result, inline_overlay, global_only_sections=frozenset()
                    )
                else:
                    result = inline_overlay
            else:
                logger.warning("AI_GUARDIAN_CONFIG_INLINE must be a JSON object")
        except json.JSONDecodeError as e:
            logger.warning("AI_GUARDIAN_CONFIG_INLINE parse error: %s", e)

    if _sdk_overlay is not None:
        if result is not None:
            result = deep_merge(result, _sdk_overlay, global_only_sections=frozenset())
        else:
            result = copy.deepcopy(_sdk_overlay)

    return result


def _get_mtime(path):
    """Get file mtime, or None if the file doesn't exist."""
    if not path:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _dedup_config_lists(config):
    """Deduplicate list values in config sections (defensive cleanup for existing configs)."""
    if not isinstance(config, dict):
        return config
    for section_key, section_val in config.items():
        if isinstance(section_val, dict):
            for field_key, field_val in section_val.items():
                if isinstance(field_val, list) and len(field_val) > 0:
                    deduped = _dedup_list(field_val)
                    if len(deduped) < len(field_val):
                        logger.debug(
                            "Config dedup: %s.%s reduced from %d to %d items",
                            section_key,
                            field_key,
                            len(field_val),
                            len(deduped),
                        )
                        section_val[field_key] = deduped
    return config


def _normalize_permissions(config):
    """Normalize old list-format permissions to new dict format before merge.

    Converts ``"permissions": [...]`` (deprecated) to
    ``"permissions": {"enabled": true, "rules": [...]}``.
    """
    if config is None:
        return config
    permissions = config.get("permissions")
    if isinstance(permissions, list):
        logger.warning(
            "DEPRECATED: permissions as array format detected. "
            'Update to: {"permissions": {"enabled": true, "rules": [...]}}'
        )
        config = dict(config)
        config["permissions"] = {
            "enabled": True,
            "rules": permissions,
        }
    return config


def _warn_deprecated_action_on_allow(config):
    """Warn about deprecated action field on allow permission rules."""
    if config is None:
        return
    permissions = config.get("permissions")
    if isinstance(permissions, dict):
        rules = permissions.get("rules", [])
    elif isinstance(permissions, list):
        rules = permissions
    else:
        return
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if rule.get("mode") == "allow" and rule.get("action"):
            logger.warning(
                'DEPRECATED: "action": "%s" on allow rule (matcher=%s). '
                'Remove "action" or split into separate deny + allow rules.',
                rule.get("action"),
                rule.get("matcher", "?"),
            )


def _load_config_file():
    """
    Load ai-guardian.json configuration with project-level and SDK overlays.

    Loads the global config from ``~/.config/ai-guardian/ai-guardian.json``,
    merges a project-level ``ai-guardian.json`` on top, then applies any
    SDK overlay (env vars or ``configure()``).  Each layer wins for
    non-immutable fields; the SDK overlay also bypasses global-only
    section restrictions.

    Uses mtime-based caching to avoid redundant file reads when multiple
    _load_*_config() functions are called within the same hook invocation.

    Returns:
        tuple: (config_dict or None, error_message or None)
    """
    try:
        # Resolve paths
        config_dir = get_config_dir()
        global_path = config_dir / "ai-guardian.json"

        if _get_mtime(global_path) is None:
            global_path = None

        project_path = get_project_config_path()

        # Legacy fallback: if no global AND no project config, try CWD/.ai-guardian.json
        # DEPRECATED: will be removed in v2.0.0 — use .ai-guardian/ai-guardian.json instead
        if global_path is None and project_path is None:
            legacy_path = Path.cwd() / ".ai-guardian.json"
            if legacy_path.exists():
                logger.warning(
                    "DEPRECATED: Using legacy '.ai-guardian.json' in project root. "
                    "Move to '.ai-guardian/ai-guardian.json' instead. "
                    "Legacy support will be removed in v2.0.0."
                )
                global_path = legacy_path

        # Cache key: per-project path or global-only sentinel
        cache_key = str(project_path) if project_path else "__global__"

        # Resolve overlay state for cache comparison
        overlay_env_path = os.environ.get("AI_GUARDIAN_CONFIG_OVERLAY")
        overlay_file_mtime = None
        if overlay_env_path:
            overlay_file_mtime = _get_mtime(Path(overlay_env_path).expanduser())
        inline_value = os.environ.get("AI_GUARDIAN_CONFIG_INLINE")
        current_sdk_id = id(_sdk_overlay) if _sdk_overlay is not None else None

        # No config files and no overlay at all
        if (
            global_path is None
            and project_path is None
            and not overlay_env_path
            and not inline_value
            and _sdk_overlay is None
        ):
            _caches[cache_key] = _ConfigCacheEntry(
                result=(None, None),
                last_accessed=time.monotonic(),
            )
            return _caches[cache_key].result

        # Check mtime cache
        global_mtime = _get_mtime(global_path)
        project_mtime = _get_mtime(project_path)

        cached = _caches.get(cache_key)
        if (
            cached is not None
            and cached.result is not None
            and cached.global_path == global_path
            and cached.project_path == project_path
            and cached.global_mtime == global_mtime
            and cached.project_mtime == project_mtime
            and cached.overlay_path == overlay_env_path
            and cached.overlay_mtime == overlay_file_mtime
            and cached.inline_overlay_value == inline_value
            and cached.sdk_overlay_id == current_sdk_id
        ):
            cached.last_accessed = time.monotonic()
            return cached.result

        # Load global config
        global_config = None
        if global_path:
            global_config, error_msg = _load_json_config(global_path)
            if error_msg:
                entry = _ConfigCacheEntry(
                    result=(None, error_msg),
                    global_mtime=global_mtime,
                    project_mtime=project_mtime,
                    global_path=global_path,
                    project_path=project_path,
                    last_accessed=time.monotonic(),
                )
                _caches[cache_key] = entry
                return entry.result

        # Load project config
        project_config = None
        if project_path:
            project_config, error_msg = _load_json_config(project_path)
            if error_msg:
                logger.warning(f"Ignoring invalid project config: {error_msg}")
                project_config = None

        # Normalize permissions format before merge (list → dict)
        global_config = _normalize_permissions(global_config)
        project_config = _normalize_permissions(project_config)

        # Warn about deprecated action on allow rules
        _warn_deprecated_action_on_allow(global_config)
        _warn_deprecated_action_on_allow(project_config)

        # Merge (use `is not None` — empty dict {} is a valid config)
        if global_config is not None and project_config is not None:
            logger.debug(f"Config merge: global={global_path}, project={project_path}")
            effective = deep_merge(global_config, project_config)
        elif global_config is not None:
            effective = global_config
        elif project_config is not None:
            effective = project_config
        else:
            effective = None

        # Apply SDK overlay (highest priority, no global_only restriction)
        overlay = _resolve_sdk_overlay()
        if overlay is not None:
            if effective is not None:
                effective = deep_merge(
                    effective, overlay, global_only_sections=frozenset()
                )
            else:
                effective = copy.deepcopy(overlay)
            logger.debug("Config merge: SDK overlay applied")

        if effective is not None:
            effective = _dedup_config_lists(effective)

        entry = _ConfigCacheEntry(
            result=(effective, None),
            global_mtime=global_mtime,
            project_mtime=project_mtime,
            global_path=global_path,
            project_path=project_path,
            overlay_mtime=overlay_file_mtime,
            overlay_path=overlay_env_path,
            inline_overlay_value=inline_value,
            sdk_overlay_id=current_sdk_id,
            last_accessed=time.monotonic(),
        )
        _caches[cache_key] = entry
        return entry.result

    except Exception as e:
        error_msg = f"⚠️  Configuration Error: {str(e)}"
        logger.error(f"Unexpected error loading config: {e}")
        return None, error_msg


def cleanup_stale_entries(max_age: float = 86400.0):
    """Remove cache entries not accessed within max_age seconds."""
    now = time.monotonic()
    stale_keys = [
        k for k, entry in _caches.items() if now - entry.last_accessed > max_age
    ]
    for key in stale_keys:
        _caches.pop(key, None)
    if stale_keys:
        logger.debug(f"Pruned {len(stale_keys)} stale config_loaders cache entries")


def _load_json_config(config_path):
    """
    Load and parse a single JSON config file.

    Returns:
        tuple: (config_dict or None, error_message or None)
    """
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        return config, None
    except json.JSONDecodeError as e:
        error_msg = (
            f"⚠️  Configuration Error: Failed to parse {config_path}\n"
            f"JSON Error: {e.msg} (line {e.lineno}, column {e.colno})\n"
            f"Using default configuration. Please fix the config file."
        )
        logger.error(f"JSON parse error in {config_path}: {e}")
        print(error_msg, file=sys.stderr)
        return None, error_msg
    except Exception as e:
        error_msg = (
            f"⚠️  Configuration Error: Failed to read {config_path}\n"
            f"Error: {str(e)}\n"
            f"Using default configuration."
        )
        logger.error(f"Error reading config {config_path}: {e}")
        return None, error_msg


def _load_pattern_server_config():
    """
    Load pattern server configuration from ai-guardian.json.

    NEW in v1.7.0: Checks secret_scanning.pattern_server first (new location),
    then falls back to root-level pattern_server (deprecated, backward compatibility).

    Returns:
        dict: Pattern server configuration or None
    """
    try:
        config, error_msg = _load_config_file()
        if error_msg or config is None:
            return None

        secret_scanning = config.get("secret_scanning", {})
        if "pattern_server" in secret_scanning:
            pattern_config = secret_scanning["pattern_server"]

            logger.warning(
                "DEPRECATED: 'secret_scanning.pattern_server' is a global setting "
                "but only applies to gitleaks. Move to per-engine format:\n"
                '  "secret_scanning": {\n'
                '    "engines": [\n'
                '      {"type": "gitleaks", "pattern_server": {...}}\n'
                "    ]\n"
                "  }\n"
                "Run: ai-guardian setup --migrate-pattern-server\n"
                "Global pattern_server support will be removed in v2.0.0."
            )

            if pattern_config is None:
                logger.debug(
                    "Pattern server explicitly disabled (secret_scanning.pattern_server = null)"
                )
                return None

            if isinstance(pattern_config, dict):
                if "enabled" in pattern_config:
                    if not is_feature_enabled(pattern_config["enabled"]):
                        logger.debug("Pattern server disabled via enabled field")
                        return None

                if pattern_config.get("url"):
                    logger.debug(
                        "Using pattern server from secret_scanning.pattern_server"
                    )
                    return pattern_config
                else:
                    logger.debug("Pattern server section present but no URL configured")
                    return None

        if "pattern_server" in config:
            pattern_config = config["pattern_server"]

            logger.warning(
                "DEPRECATED: Root-level 'pattern_server' configuration. "
                "Move to 'secret_scanning.pattern_server' instead. "
                "Example:\n"
                '  "secret_scanning": {\n'
                '    "enabled": true,\n'
                '    "pattern_server": {...}\n'
                "  }\n"
                "Root-level support will be removed in v2.0.0."
            )

            if isinstance(pattern_config, dict):
                if "enabled" in pattern_config:
                    if not is_feature_enabled(pattern_config["enabled"]):
                        logger.debug("Pattern server disabled via enabled field")
                        return None

                if pattern_config.get("url"):
                    return pattern_config

        return None

    except Exception as e:
        logger.debug(f"Error loading pattern server config: {e}")
        return None


def _load_config_section(key, defaults=None, merge_ignore=False):
    """Load a config section from ai-guardian.json with optional defaults and .aiguardignore merge."""
    config, error_msg = _load_config_file()
    if error_msg:
        return (defaults or None), error_msg
    if config is None:
        return (defaults or None), None
    if defaults:
        section = dict(defaults)
        user_section = config.get(key)
        if user_section and isinstance(user_section, dict):
            section.update(user_section)
    else:
        section = config.get(key)
    if merge_ignore and section is not None:
        section = _merge_aiguardignore(
            section, key, project_root=Path(get_project_dir())
        )
    return section, None


def _load_prompt_injection_config():
    """Load prompt injection configuration from ai-guardian.json."""
    return _load_config_section("prompt_injection", merge_ignore=True)


def _load_config_scanner_config():
    """Load config file scanning configuration from ai-guardian.json."""
    return _load_config_section("config_file_scanning", merge_ignore=True)


def _load_permissions_config():
    """Load permissions configuration from ai-guardian.json."""
    config, error_msg = _load_config_file()
    if error_msg:
        return None, error_msg
    if config is None:
        return None, None

    permissions = config.get("permissions")
    if isinstance(permissions, dict):
        return {"enabled": permissions.get("enabled", True)}, None

    return {"enabled": True}, None


def _load_secret_scanning_config():
    """Load secret scanning configuration from ai-guardian.json."""
    return _load_config_section("secret_scanning", merge_ignore=True)


def _load_secret_redaction_config():
    """Load secret redaction configuration from ai-guardian.json."""
    return _load_config_section("secret_redaction")


_PII_DEFAULTS = {
    "enabled": True,
    "pii_types": [
        "ssn",
        "credit_card",
        "phone",
        "us_passport",
        "iban",
        "intl_phone",
        "medical_id",
        "passport",
        "uk_nin",
    ],
    "action": "block",
    "ignore_files": [],
    "ignore_tools": [],
    "allowlist_patterns": [],
    "pattern_server": None,
}


def _load_pii_config():
    """Load PII scanning configuration. Returns defaults when scan_pii section is absent."""
    return _load_config_section("scan_pii", defaults=_PII_DEFAULTS, merge_ignore=True)


def _load_transcript_scanning_config():
    """Load transcript scanning configuration. Returns defaults when section is absent."""
    return _load_config_section("transcript_scanning", defaults={"enabled": True})


def _load_annotations_config():
    """Load annotations configuration. Returns defaults when section is absent."""
    return _load_config_section("annotations", defaults={"enabled": True})


_IMAGE_SCANNING_DEFAULTS = {
    "enabled": True,
    "action": "block",
    "scan_types": ["secrets", "pii"],
    "max_processing_ms": 1500,
    "min_confidence": 0.5,
    "redaction_method": "blur",
    "qr_scanning": False,
    "face_detection": False,
    "ignore_files": [],
    "ignore_tools": [],
    "max_image_size_mb": 10,
}


def _load_image_scanning_config():
    """Load image scanning configuration. Returns defaults when section is absent."""
    return _load_config_section(
        "image_scanning", defaults=_IMAGE_SCANNING_DEFAULTS, merge_ignore=True
    )


_CONTEXT_POISONING_DEFAULTS = {
    "enabled": True,
    "action": "warn",
    "allowlist_patterns": [],
    "custom_patterns": [],
    "sensitivity": "medium",
}


def _load_context_poisoning_config():
    """Load context poisoning configuration. Returns defaults when section is absent."""
    return _load_config_section(
        "context_poisoning", defaults=_CONTEXT_POISONING_DEFAULTS, merge_ignore=True
    )


_SUPPLY_CHAIN_DEFAULTS = {
    "enabled": True,
    "action": "block",
    "scan_hooks": True,
    "scan_mcp_configs": True,
    "scan_plugins": True,
    "allowlist_paths": [],
}


def _load_supply_chain_config():
    """Load supply chain scanning configuration. Returns defaults when section is absent."""
    return _load_config_section(
        "supply_chain", defaults=_SUPPLY_CHAIN_DEFAULTS, merge_ignore=True
    )


_CODE_SCANNING_DEFAULTS = {
    "enabled": True,
    "action": "warn",
    "severity_threshold": "MEDIUM",
    "allowlist": [],
    "ignore_files": [],
}


def _load_code_scanning_config():
    """Load code security scanning (Bandit) configuration. Returns defaults when section is absent."""
    return _load_config_section(
        "code_scanning", defaults=_CODE_SCANNING_DEFAULTS, merge_ignore=True
    )


_CANARY_DETECTION_DEFAULTS = {
    "enabled": False,
    "action": "block",
    "tokens": [],
}


def _load_canary_detection_config():
    """Load canary token detection configuration. Returns defaults when section is absent."""
    return _load_config_section(
        "canary_detection", defaults=_CANARY_DETECTION_DEFAULTS, merge_ignore=True
    )


_EXFIL_DETECTION_DEFAULTS = {
    "enabled": True,
    "action": "block",
    "allowlist_patterns": [],
}


def _load_exfil_detection_config():
    """Load exfil detection configuration. Returns defaults when section is absent."""
    return _load_config_section(
        "exfil_detection", defaults=_EXFIL_DETECTION_DEFAULTS, merge_ignore=True
    )


_OFFENSIVE_LANGUAGE_DEFAULTS = {
    "enabled": False,
    "action": "log",
    "categories": ["profanity", "slurs", "inclusive_language"],
    "ignore_files": [],
    "ignore_tools": [],
    "allowlist_patterns": [],
}


def _load_offensive_language_config():
    """Load offensive language scanning configuration. Returns defaults when section is absent."""
    return _load_config_section(
        "scan_offensive", defaults=_OFFENSIVE_LANGUAGE_DEFAULTS, merge_ignore=True
    )


def _load_security_instructions_config():
    """Load security instructions configuration from ai-guardian.json."""
    return _load_config_section("security_instructions")


_SCANNER_MERGE_SECTIONS = (
    "prompt_injection",
    "config_file_scanning",
    "secret_scanning",
    "scan_pii",
    "image_scanning",
    "context_poisoning",
    "supply_chain",
    "code_scanning",
    "canary_detection",
    "exfil_detection",
    "scan_offensive",
    "ssrf_protection",
)


def load_scanner_config(project_root=None):
    """Load full merged config suitable for FileScanner.

    Loads global + project + SDK overlay config via _load_config_file(),
    then merges .aiguardignore.toml ignore paths into each scanner section.
    Logs a warning on config loading errors but always returns a usable dict.

    Args:
        project_root: Project root for .aiguardignore.toml lookup.
            Defaults to get_project_dir().

    Returns:
        dict: Merged config (empty on failure).
    """
    config, error_msg = _load_config_file()
    if error_msg:
        logger.warning("Config loading issue: %s", error_msg)
        return {}
    if config is None:
        config = {}

    root = Path(project_root) if project_root else Path(get_project_dir())
    for section_key in _SCANNER_MERGE_SECTIONS:
        section = config.get(section_key)
        merged = _merge_aiguardignore(section, section_key, root)
        if merged is not None:
            config[section_key] = merged

    return config


def _load_sdk_profile(section: str, name: Optional[str]) -> Dict[str, Any]:
    """Load an SDK agent or client profile from merged config.

    Resolves ``sdk.<section>`` from the merged config (global + project +
    overlay), then returns the effective profile for *name*.

    Resolution order:
    1. Start with ``_default`` profile (if defined).
    2. Merge the named profile on top (if *name* matches a key).
    3. If *name* is ``None`` or has no matching key, ``_default`` alone.
    4. If neither exists, return ``{}``.

    Args:
        section: ``"agents"`` or ``"clients"``
        name: Profile name, or ``None`` for ``_default`` only.

    Returns:
        Merged profile dict, or empty dict if nothing configured.
    """
    config, error_msg = _load_config_file()
    if error_msg or config is None:
        return {}

    sdk = config.get("sdk")
    if not isinstance(sdk, dict):
        return {}

    profiles = sdk.get(section)
    if not isinstance(profiles, dict):
        return {}

    default_profile = profiles.get("_default", {})
    if not isinstance(default_profile, dict):
        default_profile = {}

    if name and name in profiles:
        named = profiles[name]
        if isinstance(named, dict):
            result = dict(default_profile)
            result.update(named)
            return result

    return dict(default_profile)


def _get_on_scan_error_action() -> str:
    """
    Load the global on_scan_error setting from ai-guardian.json.

    Returns:
        str: "allow" (default, fail-open) or "block" (fail-closed)
    """
    config, _ = _load_config_file()
    if config:
        value = config.get("on_scan_error", "allow")
        if value in ("allow", "block"):
            return value
    return "allow"
