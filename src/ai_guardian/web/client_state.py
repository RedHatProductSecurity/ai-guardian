"""Compatibility helpers for NiceGUI client lifecycle state."""

from typing import Any


def is_client_deleted(client: Any) -> bool:
    """Return whether a NiceGUI client has been deleted.

    NiceGUI 3.0 exposes the lifecycle flag as ``_deleted`` while newer
    releases provide the public ``is_deleted`` property. AI Guardian supports
    NiceGUI >=3.0, so auto-refresh callbacks need to handle both forms.
    """
    try:
        return bool(client.is_deleted)
    except AttributeError:
        return bool(getattr(client, "_deleted", False))


__all__ = ["is_client_deleted"]
