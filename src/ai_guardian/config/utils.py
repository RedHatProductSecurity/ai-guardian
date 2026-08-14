#!/usr/bin/env python3
"""
Configuration utilities for ai-guardian.

Shared utilities for configuration directory resolution and timestamp handling.
"""

import copy
import json
import logging
import os
import platform
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional

logger = logging.getLogger(__name__)

ACTION_SEVERITY = {"allow": 0, "log-only": 1, "warn": 2, "redact": 3, "block": 4}
SENSITIVITY_SEVERITY = {"low": 0, "medium": 1, "high": 2}


def _ordinal_comparator(severity_map):
    def compare(base, override):
        b, o = severity_map.get(base), severity_map.get(override)
        if b is not None and o is not None:
            return o >= b
        return False

    return compare


def _enabled_comparator(base, override):
    if isinstance(base, bool) and isinstance(override, bool):
        if not base and override:
            return True
        if base and not override:
            return False
    return base == override


_TIGHTENING_COMPARATORS = {
    "action": _ordinal_comparator(ACTION_SEVERITY),
    "sensitivity": _ordinal_comparator(SENSITIVITY_SEVERITY),
    "enabled": _enabled_comparator,
}

# Sections that only make sense at the user/system level.
# Project-level configs cannot override these.
GLOBAL_ONLY_SECTIONS: FrozenSet[str] = frozenset(
    {
        "daemon",
        "mcp_server",
        "support",
        "security_instructions",
        "on_scan_error",
        "remote_configs",
    }
)

_project_config_path_cache: Optional[Path] = None
_project_config_path_cached = False

_thread_local = threading.local()


def set_project_dir_override(project_dir):
    """Set per-thread project directory override (for daemon use).

    When set, get_project_config_path() discovers config from this directory
    instead of using git root or CWD. Bypasses the module-level cache.
    """
    _thread_local.project_dir = project_dir


def clear_project_dir_override():
    """Clear per-thread project directory override."""
    _thread_local.project_dir = None


def get_project_dir() -> str:
    """Return the hook's actual project directory.

    Uses the per-thread daemon override when set, falls back to os.getcwd().
    """
    return getattr(_thread_local, "project_dir", None) or os.getcwd()


def _clear_project_config_cache():
    """Clear the project config path cache."""
    global _project_config_path_cache, _project_config_path_cached
    _project_config_path_cache = None
    _project_config_path_cached = False


def _find_config_in_dir(root: Path) -> Optional[Path]:
    """Find ai-guardian config file in a directory.

    Checks .ai-guardian/ai-guardian.json first (new location),
    then ai-guardian.json at root (legacy, deprecated).

    Returns:
        Path to config file if found, None otherwise.
    """
    new_path = root / ".ai-guardian" / "ai-guardian.json"
    if new_path.exists():
        return new_path
    legacy_path = root / "ai-guardian.json"
    if legacy_path.exists():
        return legacy_path
    return None


def get_project_config_path() -> Optional[Path]:
    """
    Get project-level ai-guardian.json path.

    Discovery order:
    1. AI_GUARDIAN_PROJECT_CONFIG env var (explicit override for testing/CI)
    2. Thread-local project dir override (daemon use)
    3. Git repo root / ai-guardian.json
    4. CWD / ai-guardian.json (fallback if not in git repo)

    Returns:
        Path to project config if it exists, None otherwise.
    """
    global _project_config_path_cache, _project_config_path_cached

    override_dir = getattr(_thread_local, "project_dir", None)
    if override_dir:
        return _discover_project_config_path()

    if _project_config_path_cached:
        return _project_config_path_cache

    result = _discover_project_config_path()
    _project_config_path_cache = result
    _project_config_path_cached = True
    return result


def _discover_project_config_path() -> Optional[Path]:
    """Internal discovery logic for project config path.

    Discovery order:
    1. Thread-local project dir override (daemon use)
    2. AI_GUARDIAN_PROJECT_CONFIG env var (explicit override for testing/CI)
    3. IDE env vars: CURSOR_PROJECT_PATH, VSCODE_CWD
    4. Git repo root
    5. CWD fallback
    """
    override_dir = getattr(_thread_local, "project_dir", None)
    if override_dir:
        result = _find_config_in_dir(Path(override_dir))
        if result:
            logger.debug(f"Project config from daemon CWD: {result}")
        return result

    env_path = os.environ.get("AI_GUARDIAN_PROJECT_CONFIG")
    if env_path:
        p = Path(env_path).expanduser()
        if p.exists():
            logger.debug(f"Project config from env: {p}")
            return p
        logger.debug(f"AI_GUARDIAN_PROJECT_CONFIG set but file not found: {p}")
        return None

    # Check IDE environment variables (Cursor, VS Code)
    ide_project_path = os.environ.get("CURSOR_PROJECT_PATH") or os.environ.get(
        "VSCODE_CWD"
    )
    if ide_project_path:
        ide_root = Path(ide_project_path)
        result = _find_config_in_dir(ide_root)
        if result:
            logger.debug(f"Project config from IDE env: {result}")
            return result

    project_root = _find_git_root()
    if project_root:
        result = _find_config_in_dir(project_root)
        if result:
            legacy_path = project_root / "ai-guardian.json"
            if result == legacy_path:
                logger.warning(
                    "DEPRECATED: Project config at '%s'. "
                    "Move to '.ai-guardian/ai-guardian.json'. "
                    "Legacy support will be removed in v2.0.0.",
                    legacy_path,
                )
            else:
                logger.debug(f"Project config at git root: {result}")
            return result

    cwd = Path.cwd()
    result = _find_config_in_dir(cwd)
    if result:
        legacy_path = cwd / "ai-guardian.json"
        if result == legacy_path:
            logger.warning(
                "DEPRECATED: Project config at '%s'. "
                "Move to '.ai-guardian/ai-guardian.json'. "
                "Legacy support will be removed in v2.0.0.",
                legacy_path,
            )
        else:
            logger.debug(f"Project config at CWD: {result}")
        return result

    return None


def _find_git_root() -> Optional[Path]:
    """Find the root of the current git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass  # intentionally silent — subprocess may fail
    return None


def _dedup_list(combined: list) -> list:
    """Deduplicate a list preserving order. Handles both hashable and dict items."""
    seen_set: set = set()
    seen_unhashable: set = set()
    result = []
    for item in combined:
        if isinstance(item, dict):
            key = json.dumps(item, sort_keys=True)
            if key not in seen_unhashable:
                seen_unhashable.add(key)
                result.append(item)
        else:
            if item not in seen_set:
                seen_set.add(item)
                result.append(item)
    return result


def deep_merge(
    base: Dict,
    override: Dict,
    global_only_sections: Optional[FrozenSet[str]] = None,
) -> Dict:
    """
    Deep merge override config on top of base config.

    Rules:
    - Dicts: recursively merge
    - Lists: concatenate (override items appended to base)
    - Scalars: override wins
    - Keys in global_only_sections are skipped from override
    - ``immutable`` in base sections controls what project configs can override:
      - ``true``: entire section is locked
      - ``"tighten-only"``: overrides can tighten but not loosen settings
      - ``["field1", "field2"]``: only listed fields are locked

    Returns:
        New merged dict (inputs are not mutated).
    """
    if global_only_sections is None:
        global_only_sections = GLOBAL_ONLY_SECTIONS

    result = copy.deepcopy(base)

    for key, value in override.items():
        if key.startswith("_"):
            continue

        if key in global_only_sections:
            logger.debug(f"Project config: skipping global-only section '{key}'")
            continue

        # Check immutable constraints from the base section
        section_locked, locked_fields, tighten_only = _get_immutable_info(base.get(key))

        if section_locked:
            logger.debug(
                f"Project config: section '{key}' is immutable, skipping entirely"
            )
            continue

        if key in result:
            if isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = _deep_merge_section(
                    result[key],
                    value,
                    locked_fields,
                    tighten_only,
                )
            elif isinstance(result[key], list) and isinstance(value, list):
                result[key] = _dedup_list(result[key] + value)
            else:
                result[key] = copy.deepcopy(value)
        else:
            result[key] = copy.deepcopy(value)

    return result


def _get_immutable_info(section) -> tuple:
    """
    Extract immutable constraints from a config section.

    Returns:
        (section_locked: bool, locked_fields: list or None, tighten_only: bool)
        - section_locked=True means entire section cannot be overridden
        - locked_fields is a list of field names that cannot be overridden
        - tighten_only=True means overrides can tighten but not loosen
    """
    if not isinstance(section, dict):
        return False, None, False
    immutable = section.get("immutable")
    if immutable is True:
        return True, None, False
    if immutable == "tighten-only":
        return False, None, True
    if isinstance(immutable, list):
        return False, immutable, False
    return False, None, False


def _is_tightening(key: str, base_value, override_value) -> bool:
    """
    Check if an override value is tighter than (or equal to) the base value.

    Used by tighten-only immutable mode. Returns True if the change is allowed
    (tightening or equal), False if the change would loosen the setting.
    """
    if base_value == override_value:
        return True
    comparator = _TIGHTENING_COMPARATORS.get(key)
    if comparator is None:
        return False
    return comparator(base_value, override_value)


def _deep_merge_section(
    base: Dict,
    override: Dict,
    locked_fields: Optional[List[str]] = None,
    tighten_only: bool = False,
) -> Dict:
    """Recursively merge a config section, respecting locked fields and tighten-only mode."""
    result = copy.deepcopy(base)

    for key, value in override.items():
        if key.startswith("_"):
            continue

        if key == "immutable":
            continue

        if locked_fields and key in locked_fields:
            logger.debug(
                f"Project config: immutable field '{key}' cannot be overridden"
            )
            continue

        if key in result:
            if isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = _deep_merge_section(
                    result[key], value, None, tighten_only
                )
            elif isinstance(result[key], list) and isinstance(value, list):
                if tighten_only:
                    # Tighten-only: can add items but not remove existing ones
                    base_set = set(result[key])
                    override_set = set(value)
                    if base_set <= override_set:
                        result[key] = copy.deepcopy(value)
                    else:
                        removed = base_set - override_set
                        logger.warning(
                            "Config override blocked: %s cannot remove items %s "
                            "(tighten-only policy)",
                            key,
                            removed,
                        )
                        new_items = [v for v in value if v not in base_set]
                        if new_items:
                            result[key] = result[key] + new_items
                else:
                    result[key] = _dedup_list(result[key] + value)
            else:
                if tighten_only:
                    if _is_tightening(key, result[key], value):
                        result[key] = copy.deepcopy(value)
                    else:
                        logger.warning(
                            "Config override blocked: %s cannot be loosened "
                            "from '%s' to '%s' (tighten-only policy)",
                            key,
                            result[key],
                            value,
                        )
                else:
                    result[key] = copy.deepcopy(value)
        else:
            result[key] = copy.deepcopy(value)

    return result


def get_config_dir() -> Path:
    """
    Get ai-guardian configuration directory.

    Priority order:
    1. AI_GUARDIAN_CONFIG_DIR (direct override)
    2. XDG_CONFIG_HOME/ai-guardian (XDG standard)
    3. ~/.config/ai-guardian (default)

    Returns:
        Path: Configuration directory path

    Examples:
        >>> os.environ['AI_GUARDIAN_CONFIG_DIR'] = '/custom/path'
        >>> get_config_dir()
        PosixPath('/custom/path')

        >>> del os.environ['AI_GUARDIAN_CONFIG_DIR']
        >>> os.environ['XDG_CONFIG_HOME'] = '/xdg/config'
        >>> get_config_dir()
        PosixPath('/xdg/config/ai-guardian')

        >>> del os.environ['XDG_CONFIG_HOME']
        >>> get_config_dir()
        PosixPath('~/.config/ai-guardian').expanduser()
    """
    # Priority 1: Check AI_GUARDIAN_CONFIG_DIR environment variable
    config_dir = os.environ.get("AI_GUARDIAN_CONFIG_DIR")
    if config_dir:
        return Path(config_dir).expanduser()

    # Priority 2: Check XDG_CONFIG_HOME
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "ai-guardian"

    # Priority 3: Default fallback (platform-specific)
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "ai-guardian"
        return Path.home() / "AppData" / "Roaming" / "ai-guardian"
    return Path("~/.config/ai-guardian").expanduser()


def get_config() -> dict:
    """Return the merged ai-guardian configuration as a dict."""
    from ai_guardian.config.loaders import _load_config_file

    config, _ = _load_config_file()
    return config or {}


def get_state_dir() -> Path:
    """
    Get ai-guardian state directory (logs, violations).

    Priority order:
    1. AI_GUARDIAN_STATE_DIR (direct override)
    2. XDG_STATE_HOME/ai-guardian (XDG standard)
    3. ~/.local/state/ai-guardian (default)

    Returns:
        Path: State directory path
    """
    state_dir = os.environ.get("AI_GUARDIAN_STATE_DIR")
    if state_dir:
        return Path(state_dir).expanduser()

    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home) / "ai-guardian"

    # Default fallback (platform-specific)
    if platform.system() == "Windows":
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            return Path(localappdata) / "ai-guardian" / "state"
        return Path.home() / "AppData" / "Local" / "ai-guardian" / "state"
    return Path("~/.local/state/ai-guardian").expanduser()


def get_sdk_trace_dir() -> Path:
    """Return the fixed directory for SDK agent trace files.

    ``get_state_dir() / "sdk" / "traces"``
    """
    return get_state_dir() / "sdk" / "traces"


def get_cache_dir() -> Path:
    """
    Get ai-guardian cache directory.

    Priority order:
    1. AI_GUARDIAN_CACHE_DIR (direct override)
    2. XDG_CACHE_HOME/ai-guardian (XDG standard)
    3. ~/.cache/ai-guardian (default)

    Returns:
        Path: Cache directory path
    """
    cache_dir = os.environ.get("AI_GUARDIAN_CACHE_DIR")
    if cache_dir:
        return Path(cache_dir).expanduser()

    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        return Path(cache_home) / "ai-guardian"

    # Default fallback (platform-specific)
    if platform.system() == "Windows":
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            return Path(localappdata) / "ai-guardian" / "cache"
        return Path.home() / "AppData" / "Local" / "ai-guardian" / "cache"
    return Path("~/.cache/ai-guardian").expanduser()


def get_profiles_dir() -> Path:
    """
    Get custom profiles directory.

    Returns the profiles subdirectory inside the config directory.

    Returns:
        Path: Profiles directory path (e.g., ~/.config/ai-guardian/profiles/)
    """
    return get_config_dir() / "profiles"


def migrate_state_files() -> None:
    """
    Migrate state files from old config dir to new state dir.

    For backward compatibility when users upgrade, checks if state files
    exist in the old location (config dir) and copies them to the new
    state dir if the new location doesn't have them yet.
    """
    import shutil

    config_dir = get_config_dir()
    state_dir = get_state_dir()

    if config_dir == state_dir:
        return

    state_files = ["violations.jsonl", "ai-guardian.log"]
    for filename in state_files:
        old_path = config_dir / filename
        new_path = state_dir / filename

        if old_path.exists() and not new_path.exists():
            try:
                state_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(old_path), str(new_path))
                logger.info(f"Migrated {filename} from {config_dir} to {state_dir}")
            except OSError as e:
                logger.warning(f"Failed to migrate {filename}: {e}")


def parse_iso8601(timestamp_str: str) -> Optional[datetime]:
    """
    Parse ISO 8601 timestamp string to datetime object.

    Supports formats:
    - 2026-04-13T12:00:00Z (UTC with Z suffix)
    - 2026-04-13T12:00:00+00:00 (UTC with offset)
    - 2026-04-13T12:00:00 (assumed UTC if no timezone)

    Args:
        timestamp_str: ISO 8601 formatted timestamp string

    Returns:
        datetime object in UTC, or None if parsing fails

    Examples:
        >>> parse_iso8601("2026-04-13T12:00:00Z")
        datetime.datetime(2026, 4, 13, 12, 0, tzinfo=datetime.timezone.utc)

        >>> parse_iso8601("invalid")
        None
    """
    if not timestamp_str or not isinstance(timestamp_str, str):
        return None

    try:
        # Try parsing with fromisoformat (Python 3.7+)
        # Handle Z suffix (not supported by fromisoformat in Python < 3.11)
        if timestamp_str.endswith("Z"):
            timestamp_str = timestamp_str[:-1] + "+00:00"

        dt = datetime.fromisoformat(timestamp_str)

        # If no timezone info, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # Convert to UTC if in different timezone
        elif dt.tzinfo != timezone.utc:
            dt = dt.astimezone(timezone.utc)

        return dt

    except (ValueError, AttributeError) as e:
        logger.debug(f"Failed to parse timestamp '{timestamp_str}': {e}")
        return None


def is_expired(valid_until: str, current_time: Optional[datetime] = None) -> bool:
    """
    Check if a timestamp has expired.

    Args:
        valid_until: ISO 8601 timestamp string
        current_time: Optional current time for testing (defaults to now in UTC)

    Returns:
        True if expired (current_time >= valid_until), False otherwise
        Returns False on parsing errors (fail-safe)

    Examples:
        >>> is_expired("2020-01-01T00:00:00Z")  # Past timestamp
        True

        >>> is_expired("2099-12-31T23:59:59Z")  # Future timestamp
        False

        >>> is_expired("invalid-timestamp")  # Invalid format
        False
    """
    # Parse the valid_until timestamp
    valid_until_dt = parse_iso8601(valid_until)

    # Fail-safe: if parsing fails, treat as non-expired
    if valid_until_dt is None:
        logger.debug(
            f"Could not parse valid_until timestamp '{valid_until}', treating as non-expired"
        )
        return False

    # Use current time or default to now (UTC)
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    elif current_time.tzinfo is None:
        # Ensure current_time has timezone info
        current_time = current_time.replace(tzinfo=timezone.utc)

    # Check if expired: current_time >= valid_until
    return current_time >= valid_until_dt


def is_feature_enabled(
    feature_config, current_time: Optional[datetime] = None, default: bool = True
) -> bool:
    """
    Check if a feature is enabled (not temporarily disabled).

    Supports both simple boolean format (permanent) and extended object format
    with time-based disabling.

    Args:
        feature_config: Feature configuration - can be:
            - bool: Simple enabled/disabled (permanent)
            - dict: Extended format with optional time-based disabling
            - None: Use default value
        current_time: Optional current time for testing (defaults to now in UTC)
        default: Default value if config is None or missing (default: True)

    Returns:
        bool: True if feature should be active, False if disabled

    Examples:
        Simple boolean format (backward compatible):
        >>> is_feature_enabled(True)
        True

        >>> is_feature_enabled(False)
        False

        Extended format without time-based disabling:
        >>> is_feature_enabled({"value": True})
        True

        Extended format with time-based disabling (active):
        >>> config = {"value": False, "disabled_until": "2099-12-31T23:59:59Z"}
        >>> is_feature_enabled(config)  # Still disabled (future date)
        False

        Extended format with expired disable period (auto-enabled):
        >>> config = {"value": False, "disabled_until": "2020-01-01T00:00:00Z"}
        >>> is_feature_enabled(config)  # Auto-enabled (past date)
        True

        Missing config uses default:
        >>> is_feature_enabled(None)
        True

        >>> is_feature_enabled(None, default=False)
        False
    """
    # Handle None - use default
    if feature_config is None:
        return default

    # Simple boolean format (backward compatible)
    if isinstance(feature_config, bool):
        return feature_config

    # Extended format with optional time-based disabling
    if isinstance(feature_config, dict):
        # Get the enabled value (default to True if missing)
        enabled_value = feature_config.get("value", default)

        # If currently disabled, check if it should be auto-re-enabled
        if not enabled_value:
            disabled_until = feature_config.get("disabled_until")
            if disabled_until:
                # Check if disable period has expired
                if is_expired(disabled_until, current_time):
                    # Temporary disable period has expired - re-enable
                    logger.info("Feature auto-enabled (disable period expired)")
                    return True
                else:
                    # Still within disable period
                    logger.debug("Feature disabled (within disable period)")
                    return False

        # Return the enabled value
        return enabled_value

    # Unknown format - fail-safe to default
    logger.warning(
        f"Unknown feature config format: {type(feature_config)}, using default: {default}"
    )
    return default


_FEATURE_KEYS = (
    "secret_scanning",
    "scan_pii",
    "prompt_injection",
    "config_file_scanning",
    "violation_logging",
    "ssrf_protection",
    "secret_redaction",
    "transcript_scanning",
    "image_scanning",
)


def get_feature_flags(cfg: Dict) -> Dict[str, bool]:
    """Extract feature enabled/disabled flags from a config dict.

    Returns a dict mapping feature key to boolean enabled state.
    The ``permissions`` key is included separately.
    """
    features: Dict[str, bool] = {}
    for key in _FEATURE_KEYS:
        section = cfg.get(key)
        if isinstance(section, dict):
            features[key] = is_feature_enabled(section.get("enabled", True))
        else:
            features[key] = bool(section) if section is not None else True
    features["permissions"] = cfg.get("permissions", {}).get("enabled", True)
    return features


def validate_regex_pattern(pattern: str, max_length: int = 500) -> bool:
    """
    Validate a regex pattern for safety before compilation.

    Prevents ReDoS (Regular Expression Denial of Service) attacks from
    untrusted pattern sources (e.g., network-sourced pattern servers).

    Args:
        pattern: Regex pattern string to validate
        max_length: Maximum allowed pattern length (default: 500)

    Returns:
        True if pattern is safe to compile, False if dangerous

    Security checks:
        - Length limit to prevent extremely complex patterns
        - Nested quantifiers detection (e.g., (a+)+, (a*)*) - common ReDoS vector
        - Valid regex syntax

    Examples:
        >>> validate_regex_pattern(r"[a-z]+@[a-z]+\\.com")
        True

        >>> validate_regex_pattern(r"(a+)+b")  # Nested quantifiers - ReDoS vector
        False

        >>> validate_regex_pattern("a" * 1000)  # Too long
        False

        >>> validate_regex_pattern(r"[invalid")  # Invalid syntax
        False
    """
    if not pattern or not isinstance(pattern, str):
        logger.warning("Invalid pattern type or empty pattern")
        return False

    # Check length limit
    if len(pattern) > max_length:
        logger.warning(f"Pattern too long: {len(pattern)} > {max_length}")
        return False

    # Detect nested quantifiers - common ReDoS pattern
    # Matches patterns like: (a+)+, (a*)*, (a?)+, [a-z]+*, etc.
    # These have a quantified expression inside a quantified group/class
    # We need to be careful NOT to match safe patterns like [a-z]+? (non-greedy after char class)
    # or [\s\S]+? (non-greedy match-all)
    # Pattern: closing paren/bracket ) or ] followed by quantifier then another quantifier
    # BUT: allow non-greedy quantifiers which end in ? (those are safe)
    nested_quantifier_patterns = [
        r"\)[+*][+*]",  # Consecutive quantifiers after closing paren like )++ or )+* (not greedy)
        r"\][+*][+*]",  # Consecutive quantifiers after closing bracket like ]++ or ]+* (not greedy)
        r"[+*?]\)[+*]",  # Quantifier before ) then non-greedy after, like +)+
    ]

    for nested_pattern in nested_quantifier_patterns:
        if re.search(nested_pattern, pattern):
            logger.warning(
                f"Nested quantifiers detected in pattern (potential ReDoS): {pattern[:100]}"
            )
            return False

    # Validate regex syntax by attempting to compile
    try:
        re.compile(pattern)
        return True
    except re.error as e:
        logger.warning(f"Invalid regex syntax: {e}, pattern: {pattern[:100]}")
        return False


def get_all_config_paths(project_dir: Optional[str] = None) -> dict:
    """Return all known config file paths keyed by scope.

    Always includes ``"global"``.  Includes ``"project"`` when a project
    config is discoverable or *project_dir* is given explicitly (the file
    need not exist yet).

    Args:
        project_dir: Explicit project root.  Used when the caller already
            knows the project directory (e.g. from hook data) and the
            thread-local override may not be set (subprocess context).

    Returns:
        ``{"global": Path, "project": Path}`` or ``{"global": Path}``.
    """
    paths: dict = {"global": get_config_dir() / "ai-guardian.json"}

    project_path = get_project_config_path()
    if not project_path and project_dir:
        candidate = Path(project_dir) / ".ai-guardian" / "ai-guardian.json"
        if Path(project_dir).resolve() != paths["global"].parent.resolve():
            project_path = candidate

    if project_path:
        paths["project"] = project_path

    return paths


def format_config_paths(project_dir: Optional[str] = None) -> str:
    """Format config locations for user-facing messages.

    Shows project path first (recommended) when available, then global.
    Annotates project path with "(will be created)" if the file does not
    exist on disk.

    Args:
        project_dir: Explicit project root (forwarded to
            :func:`get_all_config_paths`).

    Returns:
        Multi-line string suitable for appending to error/hint messages.
    """
    paths = get_all_config_paths(project_dir)
    lines = []

    if "project" in paths:
        suffix = ""
        if not paths["project"].exists():
            suffix = " (will be created)"
        lines.append(f"  Project: {paths['project']}{suffix} (recommended)")

    lines.append(f"  Global:  {paths['global']}")

    return "\n".join(lines)
