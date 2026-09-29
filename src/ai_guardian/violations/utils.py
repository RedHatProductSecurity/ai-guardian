"""Utilities for violation detection and analysis."""

import os
import tempfile


def is_temp_path(path: str) -> bool:
    """Check if path is in system temp directory.

    Args:
        path: File path to check

    Returns:
        True if path is in /tmp, /var/tmp, or system temp dir
    """
    if not path:
        return False

    temp_dirs = [
        d
        for d in (
            "/tmp",
            "/var/tmp",
            "/dev/shm",
            tempfile.gettempdir(),
            os.environ.get("TEMP"),
            os.environ.get("TMP"),
        )
        if d
    ]

    normalized = os.path.normpath(path)
    for temp_dir in temp_dirs:
        normalized_temp_dir = os.path.normpath(temp_dir)
        if normalized == normalized_temp_dir or normalized.startswith(
            normalized_temp_dir + os.sep
        ):
            return True
    return False


def is_immutable_violation(violation: object) -> bool:
    """Return whether a violation explicitly identifies immutable protection.

    Do not infer immutability from the violation type or message. Older records
    do not carry this metadata and must keep their existing configurable UX.
    """
    if not isinstance(violation, dict):
        return False

    if violation.get("is_immutable") is True or violation.get("immutable") is True:
        return True

    blocked = violation.get("blocked")
    return isinstance(blocked, dict) and blocked.get("is_immutable") is True
