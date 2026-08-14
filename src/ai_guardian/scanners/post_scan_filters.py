"""Post-scan filter pipeline for the ScannerRegistry.

Phase 4 of scanner registry refactor (#1254). Provides shared
violation logging and ask-mode handling so scanner blocks in
process_hook_data() can delegate boilerplate to a single pipeline call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ai_guardian.scanners.scan_result import ScanResult, generate_violation_id

logger = logging.getLogger(__name__)

_VIOLATION_LABELS = {
    "prompt_injection": "Prompt injection",
    "context_poisoning": "Context poisoning",
    "secret_detected": "Secret",
    "pii_detected": "PII",
    "ssrf_blocked": "SSRF threat",
    "config_file_exfil": "Config file threat",
    "supply_chain": "Supply chain threat",
    "offensive_language": "Offensive language",
    "canary_detected": "Canary token",
    "code_security": "Code security issue",
    "exfil_detection": "Exfiltration pattern",
    "bash_exfil": "Credential exfiltration",
    "directory_blocking": "Directory access violation",
    "tool_permission": "Tool policy violation",
    "secret_redaction": "Secret redaction",
}


@dataclass
class PostScanContext:
    """Injectable callbacks and state for the post-scan pipeline.

    Created once per process_hook_data() invocation. Callbacks are
    injected from hook_processing to avoid circular imports.
    """

    handle_ask_mode_auto: Callable
    log_ask_decision: Callable
    format_ask_info_message: Callable

    hook_event: str
    hook_session_id: Optional[str] = None
    hook_tool_use_id: Optional[str] = None
    tool_name: Optional[str] = None
    ide_type_value: str = "unknown"
    violation_logger: Any = None
    latency_timer: Any = None
    invocation_allowed_findings: Any = None


@dataclass
class PostScanDecision:
    """Result from apply_post_scan_pipeline()."""

    should_block: bool
    error_message: str = ""
    warnings: List[str] = field(default_factory=list)
    ask_decision: Any = None


def build_detailed_warn_message(
    entry: Any,
    result: ScanResult,
    file_path: Optional[str] = None,
) -> str:
    """Build a detailed user-facing warning with file, line, and pattern info.

    Used for systemMessage (visible to user, not agent) in warn mode.
    """
    label = _VIOLATION_LABELS.get(
        getattr(entry, "violation_type", "") or "", "Security violation"
    )
    parts = [f"{label} detected"]
    fp = result.file_path or file_path
    if fp:
        loc = str(fp)
        if result.line_number is not None:
            loc += f":{result.line_number}"
        parts.append(f"in {loc}")
    detail_bits: List[str] = []
    if result.rule_id:
        detail_bits.append(result.rule_id)
    if result.attack_type:
        detail_bits.append(result.attack_type)
    if detail_bits:
        parts.append(f"({', '.join(detail_bits)})")
    return " ".join(parts) + " — warn mode, execution allowed"


def build_violation_blocked(
    result: ScanResult,
    *,
    source: str = "",
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a standard violation ``blocked`` dict from ScanResult fields."""
    blocked: Dict[str, Any] = {}
    if result.id:
        blocked["violation_id"] = result.id
    if result.file_path:
        blocked["file_path"] = result.file_path
    if result.line_number is not None:
        blocked["line_number"] = result.line_number
    if result.start_column is not None:
        blocked["start_column"] = result.start_column
    if result.end_column is not None:
        blocked["end_column"] = result.end_column
    if result.matched_text:
        from ai_guardian.violations.redact import (
            REDACT_VIOLATION_TYPES,
            redact_secret_hint,
        )

        if result.violation_type in REDACT_VIOLATION_TYPES:
            if not (result.file_path and result.line_number is not None):
                blocked["pattern_hint"] = redact_secret_hint(result.matched_text)
        else:
            blocked["matched_text"] = result.matched_text[:100]
    if result.matched_pattern:
        blocked["pattern"] = result.matched_pattern
    if result.rule_id:
        blocked["rule_id"] = result.rule_id
    if result.attack_type:
        blocked["category"] = result.attack_type
    if result.confidence:
        blocked["confidence"] = result.confidence
    if result.total_findings and result.total_findings > 1:
        blocked["total_findings"] = result.total_findings
    if result.error_message:
        blocked["reason"] = result.error_message
    if source:
        blocked["source"] = source
    if extra_fields:
        blocked.update(extra_fields)
    return blocked


def log_scan_violation(
    entry: Any,
    result: ScanResult,
    ctx: PostScanContext,
    *,
    source: str = "",
    blocked_overrides: Optional[Dict[str, Any]] = None,
    context_overrides: Optional[Dict[str, Any]] = None,
    severity_override: Optional[str] = None,
) -> None:
    """Log a violation using ScannerEntry metadata + ScanResult fields."""
    if ctx.violation_logger is None:
        return
    try:
        blocked = build_violation_blocked(result, source=source)
        if blocked_overrides:
            blocked.update(blocked_overrides)

        from ai_guardian.config.utils import get_project_dir

        violation_ctx: Dict[str, Any] = {
            "ide_type": ctx.ide_type_value,
            "hook_event": ctx.hook_event,
            "project_path": get_project_dir(),
        }
        if ctx.hook_tool_use_id:
            violation_ctx["tool_use_id"] = ctx.hook_tool_use_id
        if ctx.hook_session_id:
            violation_ctx["session_id"] = ctx.hook_session_id
        if context_overrides:
            violation_ctx.update(context_overrides)

        ctx.violation_logger.log_violation(
            violation_type=entry.violation_type,
            blocked=blocked,
            context=violation_ctx,
            suggestion=entry.violation_suggestion or {},
            severity=severity_override or entry.violation_severity,
            violation_id=result.id,
        )
    except Exception as e:
        logger.error("Failed to log %s violation: %s", entry.name, e)


def log_scan_violations_per_finding(
    entry: Any,
    findings: List[Any],
    ctx: PostScanContext,
    *,
    file_path: Optional[str] = None,
) -> None:
    """Log one violation per finding (e.g. CODE_SECURITY multi-finding results)."""
    if ctx.violation_logger is None or not findings:
        return
    try:
        from ai_guardian.config.utils import get_project_dir

        violation_ctx: Dict[str, Any] = {
            "ide_type": ctx.ide_type_value,
            "hook_event": ctx.hook_event,
            "project_path": get_project_dir(),
        }
        if ctx.hook_tool_use_id:
            violation_ctx["tool_use_id"] = ctx.hook_tool_use_id
        if ctx.hook_session_id:
            violation_ctx["session_id"] = ctx.hook_session_id

        for f in findings:
            finding_id = generate_violation_id()
            blocked: Dict[str, Any] = {"violation_id": finding_id}
            if file_path:
                blocked["file_path"] = file_path
            rule_id = getattr(f, "rule_id", None) or ""
            description = getattr(f, "description", None) or ""
            severity = getattr(f, "severity", None) or entry.violation_severity
            line_number = getattr(f, "line_number", None)
            start_column = getattr(f, "start_column", None)
            if rule_id:
                blocked["rule_id"] = rule_id
            if description:
                blocked["reason"] = description
            if line_number is not None:
                blocked["line_number"] = line_number
            if start_column is not None:
                blocked["start_column"] = start_column

            ctx.violation_logger.log_violation(
                violation_type=entry.violation_type,
                blocked=blocked,
                context=violation_ctx,
                suggestion=entry.violation_suggestion or {},
                severity=severity,
                violation_id=finding_id,
            )
    except Exception as e:
        logger.error("Failed to log per-finding %s violations: %s", entry.name, e)


def apply_post_scan_pipeline(
    entry: Any,
    result: ScanResult,
    ctx: PostScanContext,
    *,
    file_path: Optional[str] = None,
    filename: Optional[str] = None,
    source: str = "",
    blocked_overrides: Optional[Dict[str, Any]] = None,
    context_overrides: Optional[Dict[str, Any]] = None,
    severity_override: Optional[str] = None,
    skip_violation_log: bool = False,
    finding_fingerprints: Optional[List[Any]] = None,
) -> PostScanDecision:
    """Apply standard post-scan filters: violation logging + ask mode.

    Replaces ~50 lines of per-scanner boilerplate in process_hook_data().
    """
    if not result.detected:
        return PostScanDecision(should_block=False)

    if not skip_violation_log:
        log_scan_violation(
            entry,
            result,
            ctx,
            source=source,
            blocked_overrides=blocked_overrides,
            context_overrides=context_overrides,
            severity_override=severity_override,
        )

    should_block = result.should_block
    error_msg = result.error_message or ""
    warnings: List[str] = []

    if entry.supports_ask_mode and should_block:
        action_str = result.extra.get("action", "block") if result.extra else "block"

        from ai_guardian.config.utils import get_project_dir

        ask_result = ctx.handle_ask_mode_auto(
            action_str,
            entry.violation_type,
            config_section=entry.config_section,
            error_msg=error_msg,
            file_path=file_path,
            matched_text=result.matched_text,
            line_number=result.line_number,
            start_column=result.start_column,
            matched_pattern=result.matched_pattern or "",
            latency_timer=ctx.latency_timer,
            hook_context={
                "session_id": ctx.hook_session_id,
                "project_path": get_project_dir(),
                "hook_event": ctx.hook_event,
                "tool_name": ctx.tool_name,
            },
            findings=result.findings,
        )

        if ask_result is not None:
            from ai_guardian.tui.ask_dialog import AskDecision

            if ask_result.decision not in (
                AskDecision.BLOCK,
                AskDecision.BLOCK_ALL,
            ):
                should_block = False
                detail = file_path or filename or ""
                info_msg = ctx.format_ask_info_message(
                    entry.violation_type,
                    ask_result.decision,
                    detail=detail,
                )
                warnings.append(info_msg)

            ctx.log_ask_decision(
                entry.violation_type,
                ask_result.decision,
                matched_text=result.matched_text,
                error_msg=error_msg,
                file_path=file_path,
                line_number=result.line_number,
                dialog_wait_ms=ask_result.dialog_wait_ms,
                invocation_allowed_findings=ctx.invocation_allowed_findings,
                finding_fingerprints=finding_fingerprints,
            )

            return PostScanDecision(
                should_block=should_block,
                error_message=error_msg,
                warnings=warnings,
                ask_decision=ask_result,
            )

    if not should_block and error_msg:
        detailed = build_detailed_warn_message(entry, result, file_path)
        warnings.append(detailed)

    return PostScanDecision(
        should_block=should_block,
        error_message=error_msg,
        warnings=warnings,
    )
