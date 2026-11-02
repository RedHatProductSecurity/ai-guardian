"""Utilities for violation detection and analysis."""

import os
import re
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


def is_mirrored_violation(violation: object) -> bool:
    """Return whether a record is an explicitly read-only remote mirror."""
    if not isinstance(violation, dict):
        return False
    mirror = violation.get("mirror")
    return isinstance(mirror, dict) and mirror.get("read_only") is True


def safe_mirror_metadata(value: object) -> dict | None:
    """Project only display-safe mirror attribution fields for REST responses."""
    if not isinstance(value, dict) or value.get("read_only") is not True:
        return None
    result: dict[str, object] = {"read_only": True}
    source_name = value.get("source_daemon")
    if isinstance(source_name, str) and len(source_name) <= 128:
        printable_name = "".join(char for char in source_name if char.isprintable())
        if printable_name:
            result["source_daemon"] = printable_name
    source_id = value.get("source_violation_id")
    if isinstance(source_id, str) and re.fullmatch(
        r"viol_[0-9a-fA-F]{8,64}", source_id, re.ASCII
    ):
        result["source_violation_id"] = source_id
    runtime = value.get("source_runtime")
    if isinstance(runtime, str) and runtime in {
        "container",
        "kubernetes",
        "manual",
        "ssh",
    }:
        result["source_runtime"] = runtime
    for key in ("source_key", "source_event_key"):
        field_value = value.get(key)
        if isinstance(field_value, str) and re.fullmatch(r"[0-9a-f]{64}", field_value):
            result[key] = field_value
    mirrored_at = value.get("mirrored_at")
    if isinstance(mirrored_at, str) and len(mirrored_at) <= 64:
        result["mirrored_at"] = mirrored_at
    return result
