"""Trusted runtime marker for AI Guardian development sessions."""

import os
from typing import Optional

DEVELOPER_SESSION_ENV = "AI_GUARDIAN_DEVELOPER_SESSION"
_ENABLED_VALUES = frozenset({"1", "true"})


def is_trusted_developer_session(value: Optional[str] = None) -> bool:
    """Return whether the process was started with developer CLI access enabled.

    The value is read from the process environment, not hook input, agent
    configuration, or command arguments.  Unknown values fail closed.
    """
    if value is None:
        value = os.environ.get(DEVELOPER_SESSION_ENV)
    return isinstance(value, str) and value.strip().lower() in _ENABLED_VALUES
