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
