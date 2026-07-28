"""
Parse project .aiguardignore.toml for per-project ignore_files patterns.

This module reads .aiguardignore.toml from the project root once, caches
the result by mtime, and provides helpers that config loaders call to
merge project-level ignore paths into scanner configurations.

File format (consistent with .gitleaks.toml allowlist style):

    [allowlist]
        paths = ["tests/fixtures/**"]          # all scanners

    [secret_scanning.allowlist]
        paths = ["tests/integration/**"]       # secret scanning only

    [scan_pii.allowlist]
        paths = ["tests/unit/test_pii*.py"]    # PII scanning only

    [prompt_injection.allowlist]
        paths = ["docs/security-patterns.md"]  # prompt injection only

    [config_file_scanning.allowlist]
        paths = ["examples/*.json"]            # config scanning only

    [context_poisoning.allowlist]
        paths = ["docs/instructions.md"]       # context poisoning only

    [supply_chain.allowlist]
        paths = ["scripts/hooks/**"]           # supply chain only

    [image_scanning.allowlist]
        paths = ["tests/fixtures/images/**"]   # image scanning only
"""

import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ai_guardian.scanners.gitleaks import find_project_root

logger = logging.getLogger(__name__)

try:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore
    HAS_TOML = True
except ImportError:
    HAS_TOML = False

try:
    import tomli_w

    HAS_TOML_W = True
except ImportError:
    HAS_TOML_W = False

SCHEMA_HEADER = "#:schema https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/src/ai_guardian/schemas/aiguardignore.schema.json\n"

SCANNER_TYPES = frozenset(
    {
        "secret_scanning",
        "scan_pii",
        "prompt_injection",
        "config_file_scanning",
        "context_poisoning",
        "supply_chain",
        "image_scanning",
        "offensive_language",
        "exfil_detection",
    }
)

# Per-project cache to avoid cross-project contamination (#1227)
_cached_configs: Dict[Path, tuple] = (
    {}
)  # project_root -> (toml_path, mtime, AiguardignoreConfig)
_cache_last_accessed: Dict[Path, float] = {}  # project_root -> monotonic timestamp


@dataclass
class AiguardignoreConfig:
    """Parsed .aiguardignore.toml data."""

    global_paths: List[str] = field(default_factory=list)
    scanner_paths: Dict[str, List[str]] = field(default_factory=dict)


def _validate_paths(raw: List[str]) -> List[str]:
    safe = []
    for p in raw:
        if ".." in p.split("/"):
            logger.warning(f"Blocked .aiguardignore.toml path with '..': '{p}'")
            continue
        safe.append(p)
    return safe


def load_aiguardignore(
    project_root: Optional[Path] = None,
) -> Optional[AiguardignoreConfig]:
    """Load and cache .aiguardignore.toml from the project root.

    Returns None when the file is absent, TOML is unavailable, or parsing fails.
    """
    if not HAS_TOML:
        return None

    root = project_root or find_project_root()
    if root is None:
        return None

    toml_path = root / ".aiguardignore.toml"
    if not toml_path.is_file():
        return None

    try:
        mtime = os.path.getmtime(toml_path)
    except OSError:
        return None

    _cache_last_accessed[root] = time.monotonic()
    cached = _cached_configs.get(root)
    if cached is not None:
        cached_path, cached_mtime, cached_obj = cached
        if cached_path == toml_path and cached_mtime == mtime:
            return cached_obj

    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        logger.warning(f"Failed to parse .aiguardignore.toml: {exc}")
        return None

    # Global allowlist
    al_section = data.get("allowlist", {})
    if not isinstance(al_section, dict):
        al_section = {}
    global_paths = _validate_paths(al_section.get("paths", []))

    # Per-scanner allowlists
    scanner_paths: Dict[str, List[str]] = {}
    for scanner_type in SCANNER_TYPES:
        scanner_section = data.get(scanner_type, {})
        if not isinstance(scanner_section, dict):
            continue
        scanner_al = scanner_section.get("allowlist", {})
        if not isinstance(scanner_al, dict):
            continue
        paths = _validate_paths(scanner_al.get("paths", []))
        if paths:
            scanner_paths[scanner_type] = paths

    result = AiguardignoreConfig(
        global_paths=global_paths,
        scanner_paths=scanner_paths,
    )

    _cached_configs[root] = (toml_path, mtime, result)
    return result


def get_ignore_paths(
    scanner_type: str, project_root: Optional[Path] = None
) -> List[str]:
    """Return combined global + scanner-specific paths for a scanner type.

    Returns an empty list when no .aiguardignore.toml exists or when
    there are no matching paths.
    """
    config = load_aiguardignore(project_root=project_root)
    if config is None:
        return []

    combined = list(config.global_paths)
    scanner_specific = config.scanner_paths.get(scanner_type, [])
    if scanner_specific:
        combined.extend(scanner_specific)
    return combined


def reset_cache():
    """Clear all module-level caches (for testing)."""
    _cached_configs.clear()
    _cache_last_accessed.clear()


def cleanup_stale_entries(max_age: float = 86400.0):
    """Remove cache entries not accessed within max_age seconds."""
    now = time.monotonic()
    stale_keys = [k for k, ts in _cache_last_accessed.items() if now - ts > max_age]
    for key in stale_keys:
        _cached_configs.pop(key, None)
        _cache_last_accessed.pop(key, None)
    if stale_keys:
        logger.debug(f"Pruned {len(stale_keys)} stale aiguardignore cache entries")


def find_project_root_for_file(file_path: str) -> Optional[Path]:
    """Find the project root by walking up from a file's directory.

    Looks for .git, .aiguardignore.toml, or pyproject.toml as project markers.
    Falls back to find_project_root() if no marker found.
    """
    start = Path(file_path).resolve()
    if start.is_file():
        start = start.parent

    markers = (".git", ".aiguardignore.toml", "pyproject.toml", ".gitignore")
    current = start
    while current != current.parent:
        for marker in markers:
            if (current / marker).exists():
                return current
        current = current.parent

    return find_project_root()


def make_relative_path(abs_path: str, project_root: Optional[Path] = None) -> str:
    """Convert an absolute file path to a project-relative path."""
    root = project_root or find_project_root_for_file(abs_path)
    if root is None:
        return os.path.basename(abs_path)
    try:
        return str(Path(abs_path).relative_to(root))
    except ValueError:
        return os.path.basename(abs_path)


def _load_toml_data(toml_path: Path) -> dict:
    """Load existing TOML data or return empty dict."""
    if not toml_path.is_file():
        return {}
    try:
        with open(toml_path, "rb") as f:
            return tomllib.load(f)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", toml_path, exc)
        return {}


def add_ignore_path(
    path_pattern: str,
    scanner_types: Optional[List[str]] = None,
    project_root: Optional[Path] = None,
) -> bool:
    """Add a path to .aiguardignore.toml atomically.

    Args:
        path_pattern: Relative path or glob pattern.
        scanner_types: List of scanner types to add to, or None for global [allowlist].
        project_root: Project root directory (auto-detected if None).

    Returns:
        True on success, False on failure.
    """
    if not HAS_TOML or not HAS_TOML_W:
        logger.warning("TOML support not available for writing .aiguardignore.toml")
        return False

    validated = _validate_paths([path_pattern])
    if not validated:
        logger.warning("Path rejected by validation: %s", path_pattern)
        return False
    path_pattern = validated[0]

    if path_pattern in ("*", "**", "**/*"):
        logger.warning("Path too broad: %s", path_pattern)
        return False

    root = project_root or find_project_root()
    if root is None:
        logger.warning("Cannot find project root for .aiguardignore.toml")
        return False

    toml_path = root / ".aiguardignore.toml"

    try:
        data = _load_toml_data(toml_path)

        if scanner_types is None:
            section = data.setdefault("allowlist", {})
            paths = section.setdefault("paths", [])
            if path_pattern not in paths:
                paths.append(path_pattern)
        else:
            for scanner_type in scanner_types:
                if scanner_type not in SCANNER_TYPES:
                    logger.warning("Unknown scanner type: %s", scanner_type)
                    continue
                scanner_section = data.setdefault(scanner_type, {})
                al_section = scanner_section.setdefault("allowlist", {})
                paths = al_section.setdefault("paths", [])
                if path_pattern not in paths:
                    paths.append(path_pattern)

        is_new = not toml_path.is_file()
        fd, tmp_path = tempfile.mkstemp(dir=str(root), suffix=".aiguardignore.tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                if is_new:
                    f.write(SCHEMA_HEADER.encode("utf-8"))
                    f.write(b"\n")
                tomli_w.dump(data, f)
            os.replace(tmp_path, str(toml_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # intentionally silent — best-effort operation
            raise

        reset_cache()
        return True
    except Exception as e:
        logger.warning("Failed to write .aiguardignore.toml: %s", e)
        return False


def generate_aiguardignore_preview(
    path_pattern: str,
    scanner_types: Optional[List[str]] = None,
    project_root: Optional[Path] = None,
) -> Tuple[str, int]:
    """Generate a TOML preview with the new path inserted.

    Returns:
        (toml_text, highlight_line) where highlight_line is 1-based.
    """
    if not HAS_TOML_W:
        return (f"# tomli_w not available\n# Would add: {path_pattern}", 1)

    root = project_root or find_project_root()
    toml_path = root / ".aiguardignore.toml" if root else Path(".aiguardignore.toml")

    data = _load_toml_data(toml_path) if toml_path.is_file() else {}

    if scanner_types is None:
        section = data.setdefault("allowlist", {})
        paths = section.setdefault("paths", [])
        if path_pattern not in paths:
            paths.append(path_pattern)
    else:
        for scanner_type in scanner_types:
            if scanner_type not in SCANNER_TYPES:
                continue
            scanner_section = data.setdefault(scanner_type, {})
            al_section = scanner_section.setdefault("allowlist", {})
            paths = al_section.setdefault("paths", [])
            if path_pattern not in paths:
                paths.append(path_pattern)

    toml_text = tomli_w.dumps(data)

    is_new = not toml_path.is_file()
    if is_new:
        toml_text = SCHEMA_HEADER + "\n" + toml_text

    highlight_line = 1
    for i, line in enumerate(toml_text.splitlines(), 1):
        if path_pattern in line:
            highlight_line = i
            break

    return (toml_text, highlight_line)


def write_aiguardignore_text(
    toml_text: str, project_root: Optional[Path] = None
) -> bool:
    """Write TOML text directly to .aiguardignore.toml.

    For use by the editor preview save flow.
    """
    root = project_root or find_project_root()
    if root is None:
        logger.warning("Cannot find project root")
        return False

    toml_path = root / ".aiguardignore.toml"

    if HAS_TOML:
        try:
            tomllib.loads(toml_text)
        except Exception as e:
            logger.warning("Invalid TOML: %s", e)
            return False

    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(root), suffix=".aiguardignore.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(toml_text)
            os.replace(tmp_path, str(toml_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # intentionally silent — best-effort operation
            raise

        reset_cache()
        return True
    except Exception as e:
        logger.warning("Failed to write .aiguardignore.toml: %s", e)
        return False
