"""Detached worker for delivering a persisted direct-hook notification."""

import logging
import sys
from typing import Optional, Sequence

from ai_guardian.violations.notifications import (
    _SAFE_EVENT_ID_RE,
    ViolationNotificationService,
)

logger = logging.getLogger(__name__)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Deliver pending channels for the supplied opaque outbox event ID."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1 or not _SAFE_EVENT_ID_RE.fullmatch(arguments[0]):
        return 2
    try:
        ViolationNotificationService.from_global_config().dispatch_pending_local_event(
            arguments[0]
        )
    except Exception:
        logger.warning("Detached violation notification worker failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
