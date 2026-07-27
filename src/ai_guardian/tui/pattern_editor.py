"""Pattern editor for the ask dialog's "Allow Always" flow.

Provides pattern validation, conversion, and preview logic shared across
tkinter, NiceGUI, and Textual editor implementations.

Reuses find_matches() from tui/regex_tester.py and validate_regex_pattern()
from config_utils for pattern safety checks.
"""

import fnmatch
import json
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

from pathlib import Path

from ai_guardian.config.utils import validate_regex_pattern
from ai_guardian.allowlist_utils import DANGEROUS_PATTERNS

PATTERN_TYPES = {
    "string": "Plain string (exact match)",
    "glob": "Glob pattern (*, ?)",
    "regex": "Regex pattern",
}

SECTION_PATTERN_TYPE = {
    "secret_scanning": "regex",
    "prompt_injection": "regex",
    "scan_pii": "regex",
    "context_poisoning": "regex",
    "ssrf_protection": "glob",
    "directory_rules": "glob",
    "supply_chain": "glob",
    "config_file_scanning": "glob",
    "permissions": "string",
}

SECTION_ARRAY_KEY = {
    "ssrf_protection": "allowed_domains",
    "directory_rules": "exclusions",
    "supply_chain": "allowlist_paths",
    "config_file_scanning": "ignore_files",
}

_STRIP_SECTIONS = {"permissions", "supply_chain", "config_file_scanning"}

VIOLATION_TYPE_TO_CONFIG = {
    "secret_detected": "secret_scanning",
    "pii_detected": "scan_pii",
    "prompt_injection": "prompt_injection",
    "jailbreak_detected": "prompt_injection",
    "directory_blocking": "directory_rules",
    "ssrf_blocked": "ssrf_protection",
    "config_file_exfil": "config_file_scanning",
    "context_poisoning": "context_poisoning",
    "supply_chain": "supply_chain",
    "tool_permission": "permissions",
    "image_secret_detected": "image_scanning",
    "image_pii_detected": "image_scanning",
}


def config_section_for_violation(violation_type: str) -> str:
    """Return the config section name for a violation type."""
    return VIOLATION_TYPE_TO_CONFIG.get(violation_type, "")


from ai_guardian.constants import RULE_ID_TO_CONFIG_SECTION


def config_section_for_rule_id(rule_id: str) -> Optional[str]:
    """Return the config section for a scanner rule_id (e.g. SECRET-001)."""
    return RULE_ID_TO_CONFIG_SECTION.get(rule_id)


def get_pattern_type_for_section(config_section: str) -> str:
    """Return the pattern type for a config section."""
    return SECTION_PATTERN_TYPE.get(config_section, "regex")


def convert_to_regex(pattern: str, pattern_type: str) -> str:
    """Convert a pattern to regex format for storage.

    Args:
        pattern: The pattern string.
        pattern_type: One of "string", "glob", "regex".

    Returns:
        A regex pattern string.
    """
    if pattern_type == "string":
        return re.escape(pattern)
    elif pattern_type == "glob":
        return fnmatch.translate(pattern)
    return pattern


def validate_pattern(
    pattern: str,
    pattern_type: str,
    test_text: str,
) -> Tuple[bool, str]:
    """Validate a pattern and check it matches the test text.

    Uses native matching for each type: regex uses re, glob uses fnmatch,
    string uses substring containment.

    Args:
        pattern: The pattern to validate.
        pattern_type: One of "string", "glob", "regex".
        test_text: The original matched text to test against.

    Returns:
        (is_valid, message) tuple.
    """
    if not pattern:
        return False, "Pattern is empty"

    if pattern_type == "glob":
        if pattern == "*":
            return False, "Pattern is too broad — would disable all detection"
        if test_text and not fnmatch.fnmatch(test_text, pattern):
            return False, "Pattern does not match the original text"
        return True, "Pattern is valid and matches"

    if pattern_type == "string":
        if test_text and pattern not in test_text:
            return False, "Pattern does not match the original text"
        return True, "Pattern is valid and matches"

    if pattern in DANGEROUS_PATTERNS:
        return False, "Pattern is too broad — would disable all detection"

    if not validate_regex_pattern(pattern):
        return False, "Pattern failed ReDoS safety check"

    try:
        compiled = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    except re.error as e:
        return False, f"Invalid regex: {e}"

    if test_text and not compiled.search(test_text):
        return False, "Pattern does not match the original text"

    return True, "Pattern is valid and matches"


def _permission_rule_from_pattern(pattern: str) -> dict:
    """Build a permission allow rule dict from a pattern string."""
    from ai_guardian.config.writer import _parse_permission_pattern

    matcher, rule_patterns = _parse_permission_pattern(pattern)
    return {"mode": "allow", "matcher": matcher, "patterns": rule_patterns}


def generate_config_preview(pattern: str, config_section: str) -> str:
    """Generate a JSON config snippet showing where the pattern will be added.

    Args:
        pattern: The regex pattern or domain string to add.
        config_section: The config section (e.g., "secret_scanning").

    Returns:
        Formatted JSON string.
    """
    if config_section == "permissions":
        rule = _permission_rule_from_pattern(pattern)
        return json.dumps({"permissions": {"rules": [rule]}}, indent=2)

    array_key = SECTION_ARRAY_KEY.get(config_section, "allowlist_patterns")
    return json.dumps({config_section: {array_key: [pattern]}}, indent=2)


def suggest_domain(url_or_text: str) -> str:
    """Extract a domain from a URL string for SSRF allowlisting.

    Args:
        url_or_text: A URL or text containing a URL.

    Returns:
        The domain string, or the original text if no URL could be parsed.
    """
    text = url_or_text.strip()
    try:
        parsed = urlparse(text)
        if parsed.hostname:
            return parsed.hostname.lower()
    except Exception:
        pass  # intentionally silent — best-effort operation
    url_match = re.search(r"https?://([^/:\s]+)", text)
    if url_match:
        return url_match.group(1).lower()
    return text


def get_config_scope_options(project_dir: str = None) -> list:
    """Return available config scope options as (label, path_str) tuples.

    Always includes global config. Includes project config when one exists
    or when a project directory is known (config will be created on save).

    Args:
        project_dir: Explicit project root directory.  Pass this when the
            caller already knows the project path (e.g. from
            ``AskViolationInfo.project_path``) to avoid relying on
            ``get_project_dir()`` which may return the wrong value in
            subprocess context.
    """
    from ai_guardian.config.utils import get_all_config_paths

    paths = get_all_config_paths(project_dir)

    options = [("Global", str(paths["global"]))]
    if "project" in paths:
        options.insert(0, ("Project", str(paths["project"])))

    return options


def prepare_config_with_pattern(
    pattern: str,
    config_section: str,
    config_path: Optional[str] = None,
) -> tuple:
    """Insert a pattern into config JSON in memory, return (json_text, line_number).

    Loads the current ai-guardian.json, inserts the pattern into the appropriate
    allowlist section, serializes to formatted JSON, and finds the line number
    of the newly inserted pattern.

    Returns:
        (formatted_json_string, 1-based_line_number_of_inserted_pattern)
    """
    from ai_guardian.config.utils import get_config_dir

    resolved = (
        Path(config_path) if config_path else get_config_dir() / "ai-guardian.json"
    )
    config = {}
    if resolved.exists():
        try:
            with open(resolved, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            config = {}

    if config_section == "permissions":
        section = config.setdefault("permissions", {})
        rules = section.get("rules", [])
        new_rule = _permission_rule_from_pattern(pattern)
        search_value = new_rule["patterns"][-1] if new_rule["patterns"] else pattern
        merged = False
        for existing in rules:
            if (
                existing.get("mode") == "allow"
                and existing.get("matcher") == new_rule["matcher"]
            ):
                existing_patterns = existing.get("patterns", [])
                for p in new_rule["patterns"]:
                    if p not in existing_patterns:
                        existing_patterns.append(p)
                existing["patterns"] = existing_patterns
                merged = True
                break
        if not merged:
            rules.append(new_rule)
        section["rules"] = rules
    else:
        search_value = pattern
        array_key = SECTION_ARRAY_KEY.get(config_section, "allowlist_patterns")
        section = config.setdefault(config_section, {})
        items = section.get(array_key, [])
        if pattern not in items:
            items.append(pattern)
        section[array_key] = items

    json_text = json.dumps(config, indent=2) + "\n"

    escaped = json.dumps(search_value)
    line_number = 1
    for i, line in enumerate(json_text.splitlines(), 1):
        if escaped in line:
            line_number = i
    return json_text, line_number


def suggest_pattern(matched_text: str, config_section: str = "") -> str:
    """Suggest an initial pattern based on the matched text.

    For SSRF, extracts the domain from the URL.
    For directory_rules, suggests the directory as a glob pattern.
    For env-variable assignments (KEY=value), suggests KEY\\s*= to match
    the key with any value.
    For other sections, escapes the text for use as a regex.
    """
    if config_section == "ssrf_protection":
        return suggest_domain(matched_text)
    if config_section in _STRIP_SECTIONS:
        return matched_text.strip()
    if config_section == "directory_rules":
        import os

        path = matched_text.strip()
        if os.path.isfile(path):
            return os.path.dirname(path) + "/**"
        return path + "/**" if not path.endswith("/**") else path
    env_match = re.match(r"^([A-Z][A-Z0-9_]+)\s*=", matched_text)
    if env_match:
        return env_match.group(1) + r"\s*="
    return re.escape(matched_text)
