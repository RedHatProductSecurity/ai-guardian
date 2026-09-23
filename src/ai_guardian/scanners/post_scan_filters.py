"""Post-scan filter pipeline for the ScannerRegistry.

Phase 4 of scanner registry refactor (#1254). Provides shared
violation logging and ask-mode handling so scanner blocks in
process_hook_data() can delegate boilerplate to a single pipeline call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Optional

from ai_guardian.scanners.scan_result import ScanResult, generate_violation_id
from ai_guardian.violations.decision import PolicyDecision
from ai_guardian.violations.log_violation import ScanContext, log_violation

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
    correlation_id: Optional[str] = None
    tool_name: Optional[str] = None
    # Stable agent identity persisted as context.ide_type.  This is separate
    # from the response-protocol IDEType used by hook processing.
    ide_type_value: str = "unknown"
    violation_logger: Any = None
    latency_timer: Any = None
    invocation_allowed_findings: Any = None
    # Raw source is kept only for the duration of this invocation.  The
    # shared logger converts it to hashed/sanitized metadata before writing.
    allowlist_content: Optional[str] = None
    allowlist_file_path: Optional[str] = None
    policy_version: Optional[str] = None


@dataclass
class PostScanDecision:
    """Result from apply_post_scan_pipeline()."""

    should_block: bool
    error_message: str = ""
    warnings: List[str] = field(default_factory=list)
    ask_decision: Any = None
    policy_decision: Optional[Dict[str, Any]] = None


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
    return result.to_blocked_dict(source=source, extra_fields=extra_fields)


def _scan_context_from_post_scan(ctx: PostScanContext) -> ScanContext:
    """Build a lightweight ``ScanContext`` from ``PostScanContext``."""
    from ai_guardian.config.utils import get_project_dir

    return ScanContext(
        ide_type=ctx.ide_type_value,
        hook_event=ctx.hook_event,
        project_path=get_project_dir(),
        session_id=ctx.hook_session_id,
        tool_use_id=ctx.hook_tool_use_id,
        correlation_id=ctx.correlation_id or ctx.hook_session_id,
        tool_name=ctx.tool_name,
        agent=ctx.ide_type_value,
        policy_version=ctx.policy_version,
        allowlist_content=ctx.allowlist_content,
        allowlist_file_path=ctx.allowlist_file_path,
    )


def _effective_scan_result(
    entry: Any,
    result: ScanResult,
    severity_override: Optional[str] = None,
) -> ScanResult:
    """Apply the same configured severity used by the violation logger."""
    if severity_override:
        return replace(result, severity=severity_override)
    entry_severity = getattr(entry, "violation_severity", None)
    if entry_severity:
        return replace(result, severity=entry_severity)
    return result


def _decision_context(
    ctx: PostScanContext,
    context_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    context = _scan_context_from_post_scan(ctx).to_dict()
    if context_overrides:
        context.update(context_overrides)
    return context


def log_scan_violation(
    entry: Any,
    result: ScanResult,
    ctx: PostScanContext,
    *,
    source: str = "",
    blocked_overrides: Optional[Dict[str, Any]] = None,
    context_overrides: Optional[Dict[str, Any]] = None,
    severity_override: Optional[str] = None,
    policy_decision: Optional[PolicyDecision] = None,
) -> None:
    """Log a violation using ScannerEntry metadata + ScanResult fields."""
    if ctx.violation_logger is None:
        return

    result = _effective_scan_result(entry, result, severity_override)

    log_violation(
        result,
        _scan_context_from_post_scan(ctx),
        violation_logger=ctx.violation_logger,
        blocked_overrides=blocked_overrides,
        context_overrides=context_overrides,
        suggestion=(
            entry.violation_suggestion
            if hasattr(entry, "violation_suggestion")
            else None
        ),
        source=source,
        policy_decision=policy_decision,
    )


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

    scan_ctx = _scan_context_from_post_scan(ctx)

    for f in findings:
        finding_id = generate_violation_id()
        rule_id = getattr(f, "rule_id", None) or ""
        description = getattr(f, "description", None) or ""
        severity = getattr(f, "severity", None) or entry.violation_severity
        line_number = getattr(f, "line_number", None)
        start_column = getattr(f, "start_column", None)

        result = ScanResult(
            detected=True,
            violation_type=entry.violation_type,
            id=finding_id,
            severity=severity,
            rule_id=rule_id,
            error_message=description,
            line_number=line_number,
            start_column=start_column,
            file_path=file_path,
        )

        log_violation(
            result,
            scan_ctx,
            violation_logger=ctx.violation_logger,
            suggestion=(
                entry.violation_suggestion
                if hasattr(entry, "violation_suggestion")
                else None
            ),
        )


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

    should_block = result.should_block
    error_msg = result.error_message or ""
    warnings: List[str] = []
    effective_result = _effective_scan_result(entry, result, severity_override)

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
                ide_type=ctx.ide_type_value,
                invocation_allowed_findings=ctx.invocation_allowed_findings,
                finding_fingerprints=finding_fingerprints,
            )

            canonical_decision = PolicyDecision.from_scan_result(
                effective_result,
                _decision_context(ctx, context_overrides),
                source=source,
                decision_override="block" if should_block else "allow",
            )
            if not skip_violation_log:
                log_scan_violation(
                    entry,
                    result,
                    ctx,
                    source=source,
                    blocked_overrides=blocked_overrides,
                    context_overrides=context_overrides,
                    severity_override=severity_override,
                    policy_decision=canonical_decision,
                )

            return PostScanDecision(
                should_block=should_block,
                error_message=error_msg,
                warnings=warnings,
                ask_decision=ask_result,
                policy_decision=canonical_decision.to_dict(),
            )

    if not should_block and error_msg:
        detailed = build_detailed_warn_message(entry, result, file_path)
        warnings.append(detailed)

    canonical_decision = PolicyDecision.from_scan_result(
        effective_result,
        _decision_context(ctx, context_overrides),
        source=source,
        decision_override="block" if should_block else None,
    )
    if not skip_violation_log:
        log_scan_violation(
            entry,
            result,
            ctx,
            source=source,
            blocked_overrides=blocked_overrides,
            context_overrides=context_overrides,
            severity_override=severity_override,
            policy_decision=canonical_decision,
        )

    return PostScanDecision(
        should_block=should_block,
        error_message=error_msg,
        warnings=warnings,
        policy_decision=canonical_decision.to_dict(),
    )
