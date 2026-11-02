"""Stable identity helpers for persisted violation records."""

import hashlib
import json
import re
from typing import Any, Dict

_MUTABLE_VIOLATION_FIELDS = {
    "id",
    "resolved",
    "resolved_at",
    "resolved_action",
    "resolved_note",
}
_SAFE_VIOLATION_ID_RE = re.compile(r"^viol_[0-9a-fA-F]{8,64}$", re.ASCII)


def stable_violation_id(violation: Dict[str, Any]) -> str:
    """Return the stored ID or a deterministic ID for a legacy record.

    Older JSONL records may not have an ID, and historic custom IDs may contain
    values that are not suitable for public routes. Derive a public ID from
    immutable record content without rewriting the source log.
    """
    existing_id = violation.get("id")
    if isinstance(existing_id, str) and _SAFE_VIOLATION_ID_RE.fullmatch(existing_id):
        return existing_id

    identity = {
        key: value
        for key, value in violation.items()
        if key not in _MUTABLE_VIOLATION_FIELDS
    }
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"viol_{hashlib.sha256(encoded).hexdigest()[:32]}"
