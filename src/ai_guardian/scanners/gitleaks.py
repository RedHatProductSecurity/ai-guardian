"""
Parse project .gitleaks.toml allowlists for engine-agnostic secret filtering.

When ai-guardian scans content it writes to a temp file outside the project
tree, so the scanner engine never picks up .gitleaks.toml natively.  This
module reads .gitleaks.toml once, caches the result, and exposes helpers
that check_secrets() calls as post-processing.
"""

import fnmatch
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ai_guardian.config.utils import get_project_dir, validate_regex_pattern
from ai_guardian.utils.path_matching import match_ignore_pattern

logger = logging.getLogger(__name__)

try:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore
    HAS_TOML = True
except ImportError:
    HAS_TOML = False

DANGEROUS_PATTERNS = [".*", ".+", r"[\s\S]*", r"[\s\S]+"]
MIN_STOPWORD_LENGTH = 3

# Module-level caches — per-project to avoid cross-project contamination (#1227)
_project_roots: Dict[str, Optional[Path]] = {}  # cwd_str -> project_root
_cached_allowlists: Dict[Path, tuple] = (
    {}
)  # project_root -> (toml_path, mtime, GitleaksAllowlist)
_cache_last_accessed: Dict[str, float] = {}  # cwd_str -> monotonic timestamp


@dataclass
class RuleAllowlist:
    """Per-rule allowlist from [[rules]] entries."""

    paths: List[str] = field(default_factory=list)
    regexes: List[re.Pattern] = field(default_factory=list)
    stopwords: List[str] = field(default_factory=list)


@dataclass
class GitleaksAllowlist:
    """Parsed .gitleaks.toml allowlist data."""

    paths: List[str] = field(default_factory=list)
    regexes: List[re.Pattern] = field(default_factory=list)
    stopwords: List[str] = field(default_factory=list)
    rule_allowlists: Dict[str, RuleAllowlist] = field(default_factory=dict)


def find_project_root(cwd: Optional[str] = None) -> Optional[Path]:
    """Return the git repository root, falling back to cwd.

    Args:
        cwd: Working directory to resolve from. When called from the daemon,
             pass the client's CWD so git rev-parse runs in the correct project.
             Defaults to os.getcwd().
    """
    cache_key = str(cwd) if cwd else get_project_dir()

    if cache_key in _project_roots:
        _cache_last_accessed[cache_key] = time.monotonic()
        return _project_roots[cache_key]

    try:
        raw = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            timeout=5,
            cwd=cwd,
        )
        result = Path(raw.decode().strip())
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
        OSError,
    ):
        result = Path(cache_key)

    _project_roots[cache_key] = result
    _cache_last_accessed[cache_key] = time.monotonic()
    return result


def _compile_regexes(raw: List[str]) -> List[re.Pattern]:
    compiled = []
    for pattern_str in raw:
        if pattern_str in DANGEROUS_PATTERNS:
            logger.warning(f"Blocked dangerous .gitleaks.toml regex '{pattern_str}'")
            continue
        if not validate_regex_pattern(pattern_str):
            logger.warning(f"Blocked invalid .gitleaks.toml regex '{pattern_str}'")
            continue
        try:
            compiled.append(re.compile(pattern_str, re.IGNORECASE))
        except re.error as exc:
            logger.warning(
                f"Failed to compile .gitleaks.toml regex '{pattern_str}': {exc}"
            )
    return compiled


def _clean_stopwords(raw: List[str]) -> List[str]:
    cleaned = []
    for word in raw:
        if len(word) < MIN_STOPWORD_LENGTH:
            logger.warning(
                f"Ignoring short .gitleaks.toml stopword '{word}' "
                f"(min {MIN_STOPWORD_LENGTH} chars)"
            )
            continue
        cleaned.append(word.lower())
    return cleaned


def _validate_paths(raw: List[str]) -> List[str]:
    from ai_guardian.config.utils import validate_path_list

    return validate_path_list(raw, source=".gitleaks.toml")


def _parse_rule_allowlist(rule_data: dict) -> Optional[RuleAllowlist]:
    al = rule_data.get("allowlist")
    if not al or not isinstance(al, dict):
        return None
    return RuleAllowlist(
        paths=_validate_paths(al.get("paths", [])),
        regexes=_compile_regexes(al.get("regexes", [])),
        stopwords=_clean_stopwords(al.get("stopwords", [])),
    )


def load_gitleaks_allowlist(
    project_root: Optional[Path] = None,
) -> Optional[GitleaksAllowlist]:
    """Load and cache .gitleaks.toml from the project root.

    Returns None when the file is absent, TOML is unavailable, or parsing fails.
    """
    if not HAS_TOML:
        return None

    root = project_root or find_project_root()
    if root is None:
        return None

    toml_path = root / ".gitleaks.toml"
    if not toml_path.is_file():
        return None

    try:
        mtime = os.path.getmtime(toml_path)
    except OSError:
        return None

    cached = _cached_allowlists.get(root)
    if cached is not None:
        cached_path, cached_mtime, cached_obj = cached
        if cached_path == toml_path and cached_mtime == mtime:
            return cached_obj

    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        logger.warning(f"Failed to parse .gitleaks.toml: {exc}")
        return None

    al_section = data.get("allowlist", {})
    if not isinstance(al_section, dict):
        al_section = {}

    rule_allowlists: Dict[str, RuleAllowlist] = {}
    for rule in data.get("rules", []):
        if not isinstance(rule, dict):
            continue
        rule_id = rule.get("id")
        if not rule_id:
            continue
        ral = _parse_rule_allowlist(rule)
        if ral:
            rule_allowlists[rule_id] = ral

    result = GitleaksAllowlist(
        paths=_validate_paths(al_section.get("paths", [])),
        regexes=_compile_regexes(al_section.get("regexes", [])),
        stopwords=_clean_stopwords(al_section.get("stopwords", [])),
        rule_allowlists=rule_allowlists,
    )

    _cached_allowlists[root] = (toml_path, mtime, result)
    return result


def _normalize_path(file_path: str, project_root: Path) -> str:
    """Make *file_path* relative to *project_root* when possible."""
    try:
        abs_fp = Path(file_path).expanduser().resolve()
        abs_root = project_root.resolve()
        return str(abs_fp.relative_to(abs_root))
    except (ValueError, OSError):
        return file_path


def should_skip_file(file_path: str, allowlist: GitleaksAllowlist) -> bool:
    """Return True if *file_path* matches any global path pattern."""
    if not allowlist.paths:
        return False

    root = find_project_root(cwd=get_project_dir())
    rel_path = _normalize_path(file_path, root) if root else file_path

    for pattern in allowlist.paths:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if pattern.startswith("**/"):
            abs_path = str(Path(file_path).expanduser().resolve())
            if match_ignore_pattern(abs_path, pattern):
                return True
    return False


def _is_finding_allowlisted(
    finding: dict,
    content_lines: List[str],
    rel_path: Optional[str],
    paths: List[str],
    regexes: List[re.Pattern],
    stopwords: List[str],
) -> bool:
    """Check a single finding against a set of allowlist rules."""
    if rel_path and paths:
        for pattern in paths:
            if fnmatch.fnmatch(rel_path, pattern):
                return True

    line_num = finding.get("line_number", 0)
    if line_num > 0 and line_num <= len(content_lines):
        line_text = content_lines[line_num - 1]

        for rx in regexes:
            if rx.search(line_text):
                return True

        line_lower = line_text.lower()
        for word in stopwords:
            if word in line_lower:
                return True

    return False


def filter_findings(
    findings: List[dict],
    content_lines: List[str],
    file_path: Optional[str],
    allowlist: GitleaksAllowlist,
) -> List[dict]:
    """Return only findings NOT suppressed by the .gitleaks.toml allowlist."""
    root = find_project_root(cwd=get_project_dir())
    rel_path = _normalize_path(file_path, root) if root and file_path else file_path

    remaining = []
    for finding in findings:
        if _is_finding_allowlisted(
            finding,
            content_lines,
            rel_path,
            allowlist.paths,
            allowlist.regexes,
            allowlist.stopwords,
        ):
            continue

        rule_id = finding.get("rule_id", "")
        ral = allowlist.rule_allowlists.get(rule_id)
        if ral and _is_finding_allowlisted(
            finding,
            content_lines,
            rel_path,
            ral.paths,
            ral.regexes,
            ral.stopwords,
        ):
            continue

        remaining.append(finding)

    return remaining


def reset_cache():
    """Clear all module-level caches (for testing)."""
    _project_roots.clear()
    _cached_allowlists.clear()
    _cache_last_accessed.clear()


def cleanup_stale_entries(max_age: float = 86400.0):
    """Remove cache entries not accessed within max_age seconds."""
    now = time.monotonic()
    stale_keys = [k for k, ts in _cache_last_accessed.items() if now - ts > max_age]
    for key in stale_keys:
        root = _project_roots.pop(key, None)
        if root is not None:
            _cached_allowlists.pop(root, None)
        _cache_last_accessed.pop(key, None)
    if stale_keys:
        logger.debug(f"Pruned {len(stale_keys)} stale gitleaks_config cache entries")
