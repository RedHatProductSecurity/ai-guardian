"""Utilities for violation detection and analysis."""

import tempfile
import os


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
        "/tmp",
        "/var/tmp",
        tempfile.gettempdir(),
        os.path.expandvars("%TEMP%"),
        os.path.expandvars("%TMP%"),
    ]
    return any(path.startswith(td) for td in temp_dirs)
