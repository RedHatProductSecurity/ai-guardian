"""Shared content scanning pipeline extracted from hook_processing.py (Phase 5e.3, #1491).

Refactored in #1932 to call ``scanners.pipeline.scan_content()`` for raw detection,
then apply post-scan processing (violation logging, ask mode, response formatting)
in a result loop.
"""

import logging

import ai_guardian.config.loaders as _loaders
from ai_guardian.config.utils import is_feature_enabled
from ai_guardian.constants import HookEvent, ViolationType, ActionMode
from ai_guardian.hook_events.utils import (
    _format_response,  # noqa: F401
    _extract_pii_matched_text,
    _pii_redactions_to_findings,
    _extract_file_path_from_pii_warning,
)
from ai_guardian.scanners.scan_result import ScanResult  # noqa: F401 — used by callers

logger = logging.getLogger(__name__)


def _matches_ignore_files(file_path, ignore_files):
    from ai_guardian.hook_processing import _matches_ignore_files as _mif

    return _mif(file_path, ignore_files)


# Scanner registry
from ai_guardian.scanners.scanner_registry import ScannerName

# Post-scan filters
from ai_guardian.scanners.post_scan_filters import apply_post_scan_pipeline

# Ask mode helpers
from ai_guardian.ask_mode import _compute_pii_transcript_fingerprints

# IDEType for log-gating
from ai_guardian.response_format import IDEType

# Scanners that use fail-closed (on_scan_error=block) error handling
_FAIL_CLOSED_SCANNERS = frozenset(
    {ScannerName.PROMPT_INJECTION, ScannerName.CONFIG_FILE}
)

# Derived from registry: violation_type string → ScannerName
_VIOLATION_TYPE_TO_SCANNER = None
_SCANNER_TO_VIOLATION_TYPE = None


def _ensure_violation_maps():
    """Build violation type <-> scanner name mappings from registry (lazy).

    Both globals are built in locals first, then published atomically
    (reverse map before forward map) so concurrent readers never see a
    half-initialized state.
    """
    global _VIOLATION_TYPE_TO_SCANNER, _SCANNER_TO_VIOLATION_TYPE
    if _VIOLATION_TYPE_TO_SCANNER is not None:
        return
    from ai_guardian.scanners.scanner_registry import get_default_registry

    registry = get_default_registry()
    fwd: dict = {}
    for entry in registry.all_entries():
        vtype = entry.violation_type
        if hasattr(vtype, "value"):
            fwd[vtype.value] = entry.name
    rev = {v: ViolationType(k) for k, v in fwd.items()}
    _SCANNER_TO_VIOLATION_TYPE = rev
    _VIOLATION_TYPE_TO_SCANNER = fwd


def run_content_pipeline(
    *,
    ctx=None,
    content_to_scan,
    filename,
    file_path,
    secret_content_to_scan,
    pii_content_to_scan,
    tool_identifier,
    tool_name,
    warning_messages,
    warn_violation_types=None,
    log_only_count,
    _registry,
    _post_scan_ctx,
    # Legacy individual params (used when ctx is None)
    hook_event=None,
    adapter=None,
    ide_type=None,
    now=None,
    hook_session_id=None,
    hook_tool_use_id=None,
    context_mgr=None,
    _latency_timer=None,
    security_message=None,
    _invocation_allowed=None,
    hook_data=None,
):
    """Run shared content scanning pipeline for PreToolUse/UserPromptSubmit.

    Accepts a HookContext (ctx) for shared params, or individual keyword args.

    Calls ``scan_content()`` for raw detection, then iterates results to
    apply ``apply_post_scan_pipeline()``, response formatting, ask mode, etc.

    Returns (response_dict, log_only_count) if blocked, or (None, log_only_count) to continue.
    warning_messages list is mutated in-place with any warnings.
    """
    _ensure_violation_maps()

    if ctx is not None:
        hook_data = ctx.hook_data
        hook_event = ctx.hook_event
        adapter = ctx.adapter
        ide_type = ctx.ide_type
        now = ctx.now
        hook_session_id = ctx.hook_session_id
        hook_tool_use_id = ctx.hook_tool_use_id
        context_mgr = ctx.context_mgr
        _latency_timer = ctx._latency_timer
        security_message = ctx.security_message
        _invocation_allowed = ctx._invocation_allowed

    # --- Pre-scan setup ---

    # Build content overrides for per-scanner text (annotation suppressions)
    content_overrides = {}
    if secret_content_to_scan is not None:
        content_overrides[ScannerName.SECRET] = secret_content_to_scan
    if pii_content_to_scan is not None:
        content_overrides[ScannerName.PII] = pii_content_to_scan

    # Pre-load secret config for config_error warnings and scanner_kwargs
    secret_config, config_error = _loaders._load_secret_scanning_config()
    if config_error:
        warning_messages.append(config_error)

    scanner_kwargs = {}

    # Secret scanner needs pre-loaded config, context, and ignore lists
    if secret_config:
        ignore_files = secret_config.get("ignore_files", [])
        ignore_tools = secret_config.get("ignore_tools", [])
        secret_allowlist = secret_config.get("allowlist_patterns", [])

        pre_secret_ctx = {
            "ide_type": ide_type.value,
            "hook_event": hook_event,
            "tool_name": tool_identifier,
            "source": "scanner",
        }
        if file_path:
            pre_secret_ctx["file_path"] = file_path
        if hook_tool_use_id:
            pre_secret_ctx["tool_use_id"] = hook_tool_use_id
        if hook_session_id:
            pre_secret_ctx["session_id"] = hook_session_id

        scanner_kwargs[ScannerName.SECRET] = {
            "config": secret_config,
            "secret_context": pre_secret_ctx,
            "ignore_files": ignore_files,
            "ignore_tools": ignore_tools,
            "allowlist_patterns": secret_allowlist,
        }

    # --- Call scan_content() for raw detection ---

    from ai_guardian.scanners.pipeline import scan_content

    source_type = "user_prompt" if hook_event == HookEvent.PROMPT else "file_content"

    scan_results = scan_content(
        content_to_scan,
        filename=filename,
        source_type=source_type,
        file_path=file_path,
        tool_name=tool_identifier,
        hook_event=hook_event,
        tool_identifier=tool_identifier,
        latency_timer=_latency_timer,
        content_overrides=content_overrides if content_overrides else None,
        scanner_kwargs=scanner_kwargs if scanner_kwargs else None,
        registry=_registry,
    )

    # Build pipeline names for context saving (derived from registry)
    _content_pipeline = _registry.get_pipeline(
        hook_event,
        has_content=content_to_scan is not None,
        has_file_path=file_path is not None,
    )
    _pipeline_names = {e.name for e in _content_pipeline}

    # Tracking variables for PreToolUse context saving (#1285)
    _pretool_pi_detected = False
    _pretool_cp_scanned = ScannerName.CONTEXT_POISONING in _pipeline_names
    _pretool_cp_detected = False
    _secret_detected = False

    _blocking_violations = []

    # --- Helper: apply post-scan pipeline and collect warnings/blocks ---
    # Closes over shared state to avoid repeating the same 6-line pattern
    # in every scanner branch.

    def _collect(
        scanner_name,
        result,
        vtype,
        *,
        log_message=None,
        log_gate=True,
        error_override=None,
        non_block_warning=False,
        fp_override=None,
        **pipeline_kwargs,
    ):
        decision = apply_post_scan_pipeline(
            _registry.get(scanner_name),
            result,
            _post_scan_ctx,
            file_path=fp_override if fp_override is not None else file_path,
            filename=filename,
            **pipeline_kwargs,
        )
        warning_messages.extend(decision.warnings)
        if warn_violation_types is not None and decision.warnings:
            warn_violation_types.append(vtype)
        if decision.should_block:
            if log_gate and log_message:
                logger.info(log_message)
            error = (
                error_override if error_override is not None else decision.error_message
            )
            _blocking_violations.append((error, vtype))
        elif non_block_warning and result.error_message:
            warning_messages.append(result.error_message)
            if warn_violation_types is not None:
                warn_violation_types.append(vtype)
        return decision

    # --- Post-processing loop over scan results ---

    for result in scan_results:
        scanner_name_str = result.extra.get("scanner_name", result.violation_type)
        scanner_name = _VIOLATION_TYPE_TO_SCANNER.get(result.violation_type)
        if scanner_name is None:
            try:
                scanner_name = ScannerName(scanner_name_str)
            except ValueError:
                scanner_name = None

        if scanner_name is None:
            continue

        # Handle scan errors (fail-closed for PI/CFS)
        scan_error = result.extra.get("scan_error")
        if scan_error:
            if scanner_name in _FAIL_CLOSED_SCANNERS:
                on_error = _loaders._get_on_scan_error_action()
                if on_error == ActionMode.BLOCK:
                    logger.error(
                        f"{scanner_name.value} check error "
                        f"(fail-closed, on_scan_error=block): {scan_error}"
                    )
                    vtype = _SCANNER_TO_VIOLATION_TYPE.get(scanner_name)
                    if vtype is None:
                        entry = _registry.get(scanner_name)
                        vtype = (
                            entry.violation_type
                            if entry
                            else ViolationType.PROMPT_INJECTION
                        )
                    return (
                        _format_response(
                            adapter,
                            has_secrets=True,
                            hook_event=hook_event,
                            error_message=(
                                f"{scanner_name.value} check failed "
                                f"(blocked by on_scan_error=block): {scan_error}"
                            ),
                            violation_type=vtype,
                            security_message=security_message,
                        ),
                        log_only_count,
                    )
            logger.warning(
                f"{scanner_name.value} check error (fail-open): {scan_error}"
            )
            continue

        if not result.detected:
            if result.error_message:
                warning_messages.append(result.error_message)
                vtype = _SCANNER_TO_VIOLATION_TYPE.get(scanner_name)
                if warn_violation_types is not None and vtype:
                    warn_violation_types.append(vtype)
            continue

        # --- Scanner-specific post-processing ---

        vtype = _SCANNER_TO_VIOLATION_TYPE.get(scanner_name)

        if scanner_name == ScannerName.PROMPT_INJECTION:
            _pretool_pi_detected = True
            _collect(
                scanner_name,
                result,
                vtype,
                log_message=(
                    f"Blocking operation for {file_path} "
                    "due to prompt injection detection"
                    if file_path
                    else "Blocking operation due to prompt injection detection"
                ),
                log_gate=(ide_type != IDEType.CURSOR),
            )

        elif scanner_name == ScannerName.CONTEXT_POISONING:
            _pretool_cp_detected = True
            _collect(
                scanner_name,
                result,
                vtype,
                log_message="Blocking operation due to context poisoning detection",
            )

        elif scanner_name == ScannerName.SECRET:
            _secret_detected = True
            _collect(
                scanner_name,
                result,
                vtype,
                skip_violation_log=True,
                error_override=result.error_message,
            )

        elif scanner_name == ScannerName.PII:
            pii_block_msg, pii_log_only = _handle_pii_result(
                result,
                _registry=_registry,
                _post_scan_ctx=_post_scan_ctx,
                file_path=file_path,
                filename=filename,
                warning_messages=warning_messages,
                warn_violation_types=warn_violation_types,
                log_only_count=log_only_count,
                pii_content=(content_overrides.get(ScannerName.PII, content_to_scan)),
            )
            if pii_block_msg is not None:
                _blocking_violations.append((pii_block_msg, ViolationType.PII_DETECTED))
            log_only_count = pii_log_only

        elif scanner_name == ScannerName.CONFIG_FILE:
            _collect(
                scanner_name,
                result,
                vtype,
                blocked_overrides={"details": result.extra.get("details")},
                log_message=(
                    f"Blocking operation for {file_path} " "due to config file threat"
                ),
                log_gate=(ide_type != IDEType.CURSOR),
                error_override=result.error_message,
                non_block_warning=True,
            )

        else:
            _collect(
                scanner_name,
                result,
                vtype,
                fp_override=file_path or filename or "content",
                log_message=(
                    f"Blocking operation due to {scanner_name.value} detection"
                ),
                non_block_warning=True,
            )

    # --- Return combined response if any scanners blocked (#2026) ---
    if _blocking_violations:
        all_errors = [
            err or f"{vt.value if hasattr(vt, 'value') else vt} violation detected"
            for err, vt in _blocking_violations
        ]
        all_vtypes = [vt for _, vt in _blocking_violations]
        if len(all_errors) == 1:
            combined_error = all_errors[0]
            combined_vtype = all_vtypes[0]
        else:
            combined_error = "Multiple security violations detected:\n\n" + "\n\n".join(
                f"• {err}" for err in all_errors
            )
            combined_vtype = ",".join(
                t.value if hasattr(t, "value") else str(t) for t in all_vtypes
            )
        combined_warning = "\n\n".join(warning_messages) if warning_messages else None
        return (
            _format_response(
                adapter,
                has_secrets=True,
                error_message=combined_error,
                hook_event=hook_event,
                warning_message=combined_warning,
                violation_type=combined_vtype,
                security_message=security_message,
            ),
            log_only_count,
        )

    if (
        ScannerName.SECRET in _pipeline_names
        and is_feature_enabled(
            secret_config.get("enabled") if secret_config else None,
            now,
            default=True,
        )
        and not _secret_detected
    ):
        if hook_event == HookEvent.PRE_TOOL_USE:
            if file_path:
                logger.info(f"✓ No secrets detected in file '{filename}' ({file_path})")
            else:
                logger.info(f"✓ No secrets detected in file '{filename}'")
        else:
            logger.info("✓ No secrets detected in prompt")
    elif secret_config and ide_type != IDEType.CURSOR and not _secret_detected:
        logger.info("⚠️  Secret scanning temporarily disabled")

    # --- Transcript scanning (hook-only, PROMPT events) ---
    if hook_event == HookEvent.PROMPT:
        from ai_guardian.scanners.transcript import TRANSCRIPT_ADAPTERS

        for ts_adapter in TRANSCRIPT_ADAPTERS:
            if not ts_adapter.can_scan(hook_data, adapter):
                continue

            try:
                ts_config, ts_error = _loaders._load_transcript_scanning_config()
                if ts_error:
                    logger.warning(f"Transcript scanning config error: {ts_error}")

                if ts_config and is_feature_enabled(
                    ts_config.get("enabled"), now, default=True
                ):
                    logger.info(
                        f"Scanning {ts_adapter.name} transcript " "for secrets/PII..."
                    )

                    ts_secret_config = secret_config
                    ts_pii_config, _ = _loaders._load_pii_config()

                    ts_allowed = _invocation_allowed or None
                    with _latency_timer.check("transcript_scanning"):
                        transcript_warnings = ts_adapter.scan_incremental(
                            hook_data,
                            secret_config=ts_secret_config,
                            pii_config=ts_pii_config,
                            hook_context=(
                                {"session_id": hook_session_id}
                                if hook_session_id
                                else None
                            ),
                            allowed_findings=ts_allowed,
                        )
                    if transcript_warnings:
                        warning_messages.extend(transcript_warnings)
                        if warn_violation_types is not None:
                            warn_violation_types.append(
                                ViolationType.SECRET_IN_TRANSCRIPT
                            )
                        logger.warning(
                            f"{ts_adapter.name} transcript scanning found "
                            f"{len(transcript_warnings)} issue(s)"
                        )
                    else:
                        logger.info(
                            f"✓ No threats detected in " f"{ts_adapter.name} transcript"
                        )
                elif ts_config:
                    logger.info("⚠️  Transcript scanning temporarily disabled")
            except Exception as e:
                on_error = _loaders._get_on_scan_error_action()
                if on_error == ActionMode.BLOCK:
                    logger.error(
                        f"{ts_adapter.name} transcript scanning error "
                        f"(fail-closed, on_scan_error=block): {e}"
                    )
                    return (
                        _format_response(
                            adapter,
                            has_secrets=True,
                            hook_event=hook_event,
                            error_message=(
                                f"{ts_adapter.name} transcript scanning failed "
                                f"(blocked by on_scan_error=block): {e}"
                            ),
                            violation_type=ViolationType.SECRET_DETECTED,
                            security_message=security_message,
                        ),
                        log_only_count,
                    )
                logger.warning(
                    f"{ts_adapter.name} transcript scanning error " f"(fail-open): {e}"
                )
            break

    # --- Save PreToolUse context for PostToolUse correlation (#366) ---
    if (
        hook_event in (HookEvent.PRE_TOOL_USE, HookEvent.BEFORE_READ_FILE)
        and context_mgr
        and hook_tool_use_id
    ):
        try:
            pii_was_skipped = any(
                r.extra.get("scanner_name") == ScannerName.PII.value
                and r.extra.get("skipped")
                for r in scan_results
            )
            pii_scanned = False
            pii_skip_reason = None
            if content_to_scan:
                if pii_was_skipped:
                    pii_skip_reason = "ignore_files match"
                else:
                    pii_scanned = True

            ignore_files_matched = bool(
                file_path
                and secret_config
                and _matches_ignore_files(
                    file_path, secret_config.get("ignore_files", [])
                )
            )

            pretool_context = {
                "file_path": file_path,
                "tool_name": tool_identifier or tool_name,
                "scan_results": {
                    "secrets_scanned": ScannerName.SECRET in _pipeline_names,
                    "secrets_found": False,
                    "pii_scanned": pii_scanned,
                    "pii_skipped_reason": pii_skip_reason,
                    "prompt_injection_scanned": (
                        ScannerName.PROMPT_INJECTION in _pipeline_names
                    ),
                    "prompt_injection_found": _pretool_pi_detected,
                    "context_poisoning_scanned": _pretool_cp_scanned,
                    "context_poisoning_found": _pretool_cp_detected,
                },
                "ignore_files_matched": ignore_files_matched,
            }
            context_mgr.save_pretool_context(hook_tool_use_id, pretool_context)
            logger.info(
                f"PreToolUse: saved context for " f"tool_use_id={hook_tool_use_id}"
            )
        except Exception as e:
            logger.debug(f"Failed to save PreToolUse context (non-fatal): {e}")

    # No block — pipeline passed
    return (None, log_only_count)


def _handle_pii_result(
    pii_result,
    *,
    _registry,
    _post_scan_ctx,
    file_path,
    filename,
    warning_messages,
    warn_violation_types,
    log_only_count,
    pii_content,
):
    """Handle PII scan result post-processing.

    Returns *(block_error_message, log_only_count)*.  *block_error_message*
    is ``None`` when PII does not block, or an error message string when
    PII blocks.
    """
    if pii_result.extra.get("skipped"):
        return (None, log_only_count)

    if not pii_result.detected:
        return (None, log_only_count)

    pii_redactions = pii_result.redactions
    pii_warning = pii_result.error_message
    pii_action = pii_result.extra.get("action", "block")

    if not pii_redactions:
        return (pii_warning, log_only_count)

    pii_config_for_log, _ = _loaders._load_pii_config()
    pii_action = (pii_config_for_log or {}).get("action", pii_action)
    pii_types = list(set(r.get("type", "unknown") for r in pii_redactions))
    logger.warning(f"PII detected: {pii_types}")

    pii_result.extra["action"] = pii_action
    if pii_redactions and pii_redactions[0].get("line_number") is not None:
        pii_result.line_number = pii_redactions[0]["line_number"]
    pii_result.matched_text = _extract_pii_matched_text(pii_redactions, pii_content)
    pii_result.findings = _pii_redactions_to_findings(
        pii_redactions, pii_content, pii_warning
    )

    pii_file_path2 = file_path
    if not pii_file_path2:
        pii_file_path2 = _extract_file_path_from_pii_warning(pii_warning)
    pii_fps = _compute_pii_transcript_fingerprints(pii_redactions, pii_content)

    pii_line_number = pii_redactions[0].get("line_number") if pii_redactions else None
    pii_blocked_ov = {
        "pii_count": len(pii_redactions),
        "pii_types": pii_types,
    }
    if pii_line_number is not None:
        pii_blocked_ov["line_number"] = pii_line_number

    pii_decision = apply_post_scan_pipeline(
        _registry.get(ScannerName.PII),
        pii_result,
        _post_scan_ctx,
        file_path=pii_file_path2,
        filename=filename,
        blocked_overrides=pii_blocked_ov,
        finding_fingerprints=pii_fps,
    )
    warning_messages.extend(pii_decision.warnings)
    if warn_violation_types is not None and pii_decision.warnings:
        warn_violation_types.append(ViolationType.PII_DETECTED)

    if not pii_decision.should_block:
        pii_action = "warn"

    if pii_action in ("block", "redact"):
        return (pii_warning, log_only_count)
    elif pii_action == "warn":
        warning_messages.append(pii_warning)
        if warn_violation_types is not None:
            warn_violation_types.append(ViolationType.PII_DETECTED)
    elif pii_action == "log-only":
        log_only_count += 1
    else:
        logger.warning(f"Unknown PII action '{pii_action}', allowing through")

    return (None, log_only_count)
