"""
Shared allowlist pattern utilities for suppressing false positives.

Used by prompt_injection, scan_pii, and secret_scanning modules.
Supports simple string patterns and time-based patterns with expiration.
"""

import re
import logging
from datetime import datetime
from typing import Dict, List, Optional, Union

from ai_guardian.config.utils import is_expired, validate_regex_pattern

logger = logging.getLogger(__name__)

DANGEROUS_PATTERNS = [
    r".*",
    r".+",
    r"[\s\S]*",
    r"[\s\S]+",
]


def extract_pattern_string(pattern_entry: Union[str, Dict]) -> str:
    """Extract the regex string from a pattern entry (string or dict)."""
    if isinstance(pattern_entry, str):
        return pattern_entry
    elif isinstance(pattern_entry, dict) and "pattern" in pattern_entry:
        return pattern_entry["pattern"]
    else:
        return str(pattern_entry)


def is_allowlist_pattern_valid(
    pattern_entry: object, current_time: Optional[datetime] = None
) -> bool:
    """Check if a pattern entry is still valid (not expired).

    Simple string patterns never expire. Dict patterns with a ``valid_until``
    field expire when that timestamp is in the past.
    """
    if isinstance(pattern_entry, str):
        return True

    if isinstance(pattern_entry, dict):
        if "valid_until" not in pattern_entry:
            return True

        valid_until = pattern_entry.get("valid_until")
        if not valid_until:
            return True

        return not is_expired(valid_until, current_time)

    logger.warning(f"Unknown allowlist pattern entry format: {type(pattern_entry)}")
    return True


def validate_allowlist_patterns(
    patterns: List[Union[str, Dict]],
) -> List[Union[str, Dict]]:
    """Validate patterns, blocking catch-all and ReDoS-unsafe entries."""
    safe_patterns = []
    for pattern_entry in patterns:
        pattern_str = extract_pattern_string(pattern_entry)

        if pattern_str in DANGEROUS_PATTERNS:
            logger.error(
                f"Blocked dangerous allowlist pattern '{pattern_str}' - "
                f"this would disable all detection"
            )
            continue

        if not validate_regex_pattern(pattern_str):
            logger.error(
                f"Blocked invalid/dangerous allowlist pattern '{pattern_str}' - "
                f"failed ReDoS validation"
            )
            continue

        safe_patterns.append(pattern_entry)

    return safe_patterns


def filter_valid_patterns(
    patterns: List[Union[str, Dict]], current_time: Optional[datetime] = None
) -> List[Union[str, Dict]]:
    """Filter out expired patterns from a list."""
    valid_patterns = []
    for pattern_entry in patterns:
        if is_allowlist_pattern_valid(pattern_entry, current_time):
            valid_patterns.append(pattern_entry)
        else:
            pattern_str = extract_pattern_string(pattern_entry)
            valid_until = (
                pattern_entry.get("valid_until")
                if isinstance(pattern_entry, dict)
                else None
            )
            logger.info(
                f"Skipping expired allowlist pattern '{pattern_str}' "
                f"(expired: {valid_until})"
            )

    return valid_patterns


def compile_allowlist(
    patterns: List[Union[str, Dict]],
) -> List[re.Pattern]:
    """Validate, filter expired, and compile allowlist patterns to regex objects."""
    safe = validate_allowlist_patterns(patterns)
    valid = filter_valid_patterns(safe)
    compiled = []
    for entry in valid:
        pattern_str = extract_pattern_string(entry)
        try:
            compiled.append(re.compile(pattern_str, re.IGNORECASE | re.MULTILINE))
        except re.error as e:
            logger.warning(f"Failed to compile allowlist pattern '{pattern_str}': {e}")
    return compiled


def check_allowlist(text: str, compiled_patterns: List[re.Pattern]) -> bool:
    """Return True if *text* matches any compiled allowlist pattern."""
    for pattern in compiled_patterns:
        if pattern.search(text):
            return True
    return False
