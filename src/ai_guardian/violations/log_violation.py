"""Unified violation logging — one function for all scanner types.

Replaces 10 separate ``_log_*_violation()`` functions with a single
``log_violation()`` that accepts a ``ScanResult`` and lightweight
``ScanContext``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ai_guardian.scanners.scan_result import ScanResult

logger = logging.getLogger(__name__)


@dataclass
class ScanContext:
    """Lightweight context for violation logging.

    Unlike ``PostScanContext`` (which carries ask-mode callbacks and
    daemon state), this dataclass holds only the metadata written to
    ``violations.jsonl``.
    """

    ide_type: str = "unknown"
    hook_event: str = ""
    project_path: str = ""
    session_id: Optional[str] = None
    tool_use_id: Optional[str] = None
    tool_name: Optional[str] = None

    @classmethod
    def from_hook_dicts(
        cls,
        context: Optional[Dict[str, Any]] = None,
        hook_context: Optional[Dict[str, Any]] = None,
    ) -> "ScanContext":
        """Build a ScanContext from the standard context/hook_context dict pair."""
        from ai_guardian.config.utils import get_project_dir

        ctx = context or {}
        hctx = hook_context or {}
        return cls(
            ide_type=ctx.get("ide_type", "unknown"),
            hook_event=ctx.get("hook_event", "unknown"),
            project_path=get_project_dir(),
            session_id=hctx.get("session_id"),
            tool_use_id=hctx.get("tool_use_id"),
            tool_name=hctx.get("tool_name"),
        )

    def to_dict(self) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {
            "ide_type": self.ide_type,
            "hook_event": self.hook_event,
            "project_path": self.project_path,
        }
        if self.tool_use_id:
            ctx["tool_use_id"] = self.tool_use_id
        if self.session_id:
            ctx["session_id"] = self.session_id
        if self.tool_name:
            ctx["tool_name"] = self.tool_name
        return ctx


def log_violation(
    result: ScanResult,
    context: ScanContext,
    *,
    violation_logger: Optional[Any] = None,
    blocked_overrides: Optional[Dict[str, Any]] = None,
    context_overrides: Optional[Dict[str, Any]] = None,
    suggestion: Optional[Dict[str, Any]] = None,
    source: str = "",
) -> None:
    """Log a single violation to ``violations.jsonl``.

    Args:
        result: The scan result to log.
        context: Lightweight context (IDE type, hook event, project path, etc.).
        violation_logger: Optional ``ViolationLogger`` instance.
            Created internally when *None*.
        blocked_overrides: Extra keys merged into the ``blocked`` dict.
        context_overrides: Extra keys merged into the ``context`` dict.
        suggestion: Optional suggestion dict for resolving the violation.
        source: Source label (e.g. ``"prompt"``, ``"file"``, ``"transcript"``).
    """
    if violation_logger is None:
        from ai_guardian.violations.logger import ViolationLogger

        violation_logger = ViolationLogger()

    try:
        blocked = result.to_blocked_dict(source=source)
        if blocked_overrides:
            blocked.update(blocked_overrides)

        ctx = context.to_dict()
        if context_overrides:
            ctx.update(context_overrides)

        violation_logger.log_violation(
            violation_type=result.violation_type,
            blocked=blocked,
            context=ctx,
            suggestion=suggestion or {},
            severity=result.severity,
            violation_id=result.id,
        )
    except Exception as e:
        logger.error("Failed to log %s violation: %s", result.violation_type, e)


def log_violations(
    results: List[ScanResult],
    context: ScanContext,
    *,
    violation_logger: Optional[Any] = None,
    source: str = "",
) -> None:
    """Log multiple violations (convenience wrapper around ``log_violation``)."""
    if violation_logger is None:
        from ai_guardian.violations.logger import ViolationLogger

        violation_logger = ViolationLogger()

    for result in results:
        if result.detected:
            log_violation(
                result,
                context,
                violation_logger=violation_logger,
                source=source,
            )
