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
    run_id: Optional[str] = None
    run_sequence: Optional[int] = None
    # Private, in-memory source data used to build safe deferred-resolution
    # metadata.  These fields are deliberately excluded from ``to_dict``.
    allowlist_content: Optional[str] = None
    allowlist_file_path: Optional[str] = None
    allowlist_sensitive_values: Optional[List[str]] = None
    allowlist_context: Optional[Dict[str, Any]] = None

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
            allowlist_content=ctx.get(
                "_allowlist_content", hctx.get("_allowlist_content")
            ),
            allowlist_file_path=ctx.get(
                "_allowlist_file_path", hctx.get("_allowlist_file_path")
            ),
            allowlist_sensitive_values=ctx.get(
                "_allowlist_sensitive_values",
                hctx.get("_allowlist_sensitive_values"),
            ),
            allowlist_context=ctx.get(
                "_allowlist_context", hctx.get("_allowlist_context")
            ),
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
        if self.run_id:
            ctx["run_id"] = self.run_id
        if self.run_sequence is not None:
            ctx["run_sequence"] = self.run_sequence
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
    allowlist_context: Optional[Dict[str, Any]] = None,
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
        allowlist_context: Pre-built safe source metadata, if available.
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

        metadata = allowlist_context or context.allowlist_context
        if metadata is None and context.allowlist_content is not None:
            from ai_guardian.violations.allowlist_context import (
                build_allowlist_context,
            )

            metadata = build_allowlist_context(
                context.allowlist_content,
                context.allowlist_file_path or result.file_path,
                result.line_number,
                rule_id=(
                    result.rule_id
                    or blocked.get("rule_id")
                    or blocked.get("secret_type")
                    or result.violation_type
                ),
                project_path=context.project_path,
                sensitive_values=(
                    context.allowlist_sensitive_values
                    or ([result.matched_text] if result.matched_text else None)
                ),
            )

        log_kwargs = {
            "violation_type": result.violation_type,
            "blocked": blocked,
            "context": ctx,
            "suggestion": suggestion or {},
            "severity": result.severity,
            "violation_id": result.id,
        }
        if metadata:
            log_kwargs["allowlist_context"] = metadata
        violation_logger.log_violation(**log_kwargs)
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
