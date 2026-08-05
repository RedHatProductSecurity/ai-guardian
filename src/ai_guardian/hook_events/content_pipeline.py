"""Shared content scanning pipeline extracted from hook_processing.py (Phase 5e.3, #1491)."""

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


# Scanner runner functions
from ai_guardian.hook_events.scanners import (
    _load_overlaid_config,
    run_prompt_injection_scan,
    run_context_poisoning_scan,
    run_supply_chain_scan,
    run_offensive_language_scan,
    run_canary_detection_scan,
    run_config_file_scan,
    run_secret_scan,
    run_pii_scan,
)

# Scanner registry
from ai_guardian.scanners.scanner_registry import ScannerName

# Post-scan filters
from ai_guardian.scanners.post_scan_filters import apply_post_scan_pipeline

# Ask mode helpers
from ai_guardian.ask_mode import _compute_pii_transcript_fingerprints

# Conditional imports
try:
    from ai_guardian.scanners.prompt_injection import (
        PromptInjectionDetector,  # noqa: F401
    )

    HAS_PROMPT_INJECTION = True
except ImportError:
    HAS_PROMPT_INJECTION = False

try:
    from ai_guardian.scanners.config_scanner import (
        check_config_file_threats,  # noqa: F401
    )

    HAS_CONFIG_SCANNER = True
except ImportError:
    HAS_CONFIG_SCANNER = False

# IDEType for log-gating
from ai_guardian.response_format import IDEType


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

    Returns (response_dict, log_only_count) if blocked, or (None, log_only_count) to continue.
    warning_messages list is mutated in-place with any warnings.
    """
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
    # Tracking variables for PreToolUse context saving (#1285)
    _pretool_pi_detected = False
    _pretool_cp_scanned = False
    _pretool_cp_detected = False

    # Build content-scanning pipeline names from the registry (#1253 Phase 3)
    # _registry and _post_scan_ctx already constructed above (before BASH_EXFIL).
    _content_pipeline = _registry.get_pipeline(
        hook_event,
        has_content=content_to_scan is not None,
        has_file_path=file_path is not None,
    )
    _pipeline_names = {e.name for e in _content_pipeline}

    # Generic overlay pre-compute (#1682): apply language overlays for all
    # flagged scanners so adding a new overlay-enabled scanner requires only
    # setting supports_language_overlay=True on its ScannerEntry.
    overlaid_configs = {
        e.name: oc
        for e in _content_pipeline
        if (oc := _load_overlaid_config(e)) is not None
    }

    # Check for prompt injection BEFORE scanning for secrets
    try:
        pi_result = None
        if ScannerName.PROMPT_INJECTION in _pipeline_names:
            source_type = (
                "user_prompt" if hook_event == HookEvent.PROMPT else "file_content"
            )
            pi_config = overlaid_configs.get(ScannerName.PROMPT_INJECTION)
            pi_result = run_prompt_injection_scan(
                content_to_scan,
                config=pi_config,
                file_path=file_path,
                tool_name=tool_identifier,
                source_type=source_type,
                latency_timer=_latency_timer,
            )

        if pi_result is not None:
            if pi_result.detected:
                _pretool_pi_detected = True
                pi_decision = apply_post_scan_pipeline(
                    _registry.get(ScannerName.PROMPT_INJECTION),
                    pi_result,
                    _post_scan_ctx,
                    file_path=file_path,
                    filename=filename,
                )
                warning_messages.extend(pi_decision.warnings)
                if warn_violation_types is not None and pi_decision.warnings:
                    warn_violation_types.append(ViolationType.PROMPT_INJECTION)
                if pi_decision.should_block:
                    if ide_type != IDEType.CURSOR:
                        if file_path:
                            logger.info(
                                f"Blocking operation for {file_path} due to prompt injection detection"
                            )
                        else:
                            logger.info(
                                "Blocking operation due to prompt injection detection"
                            )
                    combined_warning = (
                        "\n\n".join(warning_messages) if warning_messages else None
                    )
                    return (
                        _format_response(
                            adapter,
                            has_secrets=True,
                            error_message=pi_decision.error_message,
                            hook_event=hook_event,
                            warning_message=combined_warning,
                            violation_type=ViolationType.PROMPT_INJECTION,
                            security_message=security_message,
                        ),
                        log_only_count,
                    )
            else:
                if ide_type != IDEType.CURSOR:
                    logger.info("✓ No prompt injection detected")
        elif HAS_PROMPT_INJECTION and ide_type != IDEType.CURSOR:
            logger.info("⚠️  Prompt injection detection temporarily disabled")
    except Exception as e:
        on_error = _loaders._get_on_scan_error_action()
        if on_error == ActionMode.BLOCK:
            logger.error(
                f"Prompt injection check error (fail-closed, on_scan_error=block): {e}"
            )
            return (
                _format_response(
                    adapter,
                    has_secrets=True,
                    hook_event=hook_event,
                    error_message=f"Prompt injection check failed (blocked by on_scan_error=block): {e}",
                    violation_type=ViolationType.PROMPT_INJECTION,
                    security_message=security_message,
                ),
                log_only_count,
            )
        logger.warning(f"Prompt injection check error (fail-open): {e}")

    # Check for context poisoning (LLM03) — on both user prompts and file reads
    try:
        cp_result = None
        if ScannerName.CONTEXT_POISONING in _pipeline_names:
            cp_result = run_context_poisoning_scan(
                content_to_scan,
                file_path=file_path,
                tool_identifier=tool_identifier,
                latency_timer=_latency_timer,
            )

        if cp_result is not None:
            _pretool_cp_scanned = True
            if cp_result.detected:
                _pretool_cp_detected = True
                cp_decision = apply_post_scan_pipeline(
                    _registry.get(ScannerName.CONTEXT_POISONING),
                    cp_result,
                    _post_scan_ctx,
                    file_path=file_path,
                    filename=filename,
                )
                warning_messages.extend(cp_decision.warnings)
                if warn_violation_types is not None and cp_decision.warnings:
                    warn_violation_types.append(ViolationType.CONTEXT_POISONING)
                if cp_decision.should_block:
                    logger.info("Blocking operation due to context poisoning detection")
                    combined_warning = (
                        "\n\n".join(warning_messages) if warning_messages else None
                    )
                    return (
                        _format_response(
                            adapter,
                            has_secrets=True,
                            error_message=cp_decision.error_message,
                            hook_event=hook_event,
                            warning_message=combined_warning,
                            violation_type=ViolationType.CONTEXT_POISONING,
                            security_message=security_message,
                        ),
                        log_only_count,
                    )

    except Exception as e:
        logger.warning(f"Context poisoning check error (fail-open): {e}")

    # Check for supply chain threats in agent configuration files
    try:
        sc_result = None
        if ScannerName.SUPPLY_CHAIN in _pipeline_names:
            sc_file_path = file_path or filename or "user_prompt"
            sc_result = run_supply_chain_scan(
                content_to_scan,
                sc_file_path,
                hook_event=hook_event,
                latency_timer=_latency_timer,
            )

        if sc_result is not None and sc_result.detected:
            sc_decision = apply_post_scan_pipeline(
                _registry.get(ScannerName.SUPPLY_CHAIN),
                sc_result,
                _post_scan_ctx,
                file_path=sc_file_path,
                filename=filename,
            )
            warning_messages.extend(sc_decision.warnings)
            if warn_violation_types is not None and sc_decision.warnings:
                warn_violation_types.append(ViolationType.SUPPLY_CHAIN)
            if sc_decision.should_block:
                logger.info("Blocking operation due to supply chain threat detection")
                combined_warning = (
                    "\n\n".join(warning_messages) if warning_messages else None
                )
                return (
                    _format_response(
                        adapter,
                        has_secrets=True,
                        error_message=sc_decision.error_message,
                        hook_event=hook_event,
                        warning_message=combined_warning,
                        violation_type=ViolationType.SUPPLY_CHAIN,
                        security_message=security_message,
                    ),
                    log_only_count,
                )
        elif sc_result is not None and sc_result.error_message:
            warning_messages.append(sc_result.error_message)
            if warn_violation_types is not None:
                warn_violation_types.append(ViolationType.SUPPLY_CHAIN)

    except Exception as e:
        logger.warning(f"Supply chain check error (fail-open): {e}")

    # Check for offensive language (profanity, slurs, non-inclusive terms)
    try:
        ol_result = None
        if ScannerName.OFFENSIVE_LANGUAGE in _pipeline_names:
            ol_result = run_offensive_language_scan(
                content_to_scan,
                file_path=file_path,
                tool_identifier=tool_identifier,
                latency_timer=_latency_timer,
            )

        if ol_result is not None and ol_result.detected:
            ol_decision = apply_post_scan_pipeline(
                _registry.get(ScannerName.OFFENSIVE_LANGUAGE),
                ol_result,
                _post_scan_ctx,
                file_path=file_path,
                filename=filename,
            )
            warning_messages.extend(ol_decision.warnings)
            if warn_violation_types is not None and ol_decision.warnings:
                warn_violation_types.append(ViolationType.OFFENSIVE_LANGUAGE)
            if ol_decision.should_block:
                logger.info("Blocking operation due to offensive language detection")
                combined_warning = (
                    "\n\n".join(warning_messages) if warning_messages else None
                )
                return (
                    _format_response(
                        adapter,
                        has_secrets=True,
                        error_message=ol_decision.error_message,
                        hook_event=hook_event,
                        warning_message=combined_warning,
                        violation_type=ViolationType.OFFENSIVE_LANGUAGE,
                        security_message=security_message,
                    ),
                    log_only_count,
                )
        elif ol_result is not None and ol_result.error_message:
            warning_messages.append(ol_result.error_message)
            if warn_violation_types is not None:
                warn_violation_types.append(ViolationType.OFFENSIVE_LANGUAGE)

    except Exception as e:
        logger.warning(f"Offensive language check error (fail-open): {e}")

    # Check for canary tokens (user-registered tripwire values detecting exfiltration)
    try:
        cd_result = None
        if ScannerName.CANARY_DETECTION in _pipeline_names:
            cd_source = file_path or filename or "content"
            cd_result = run_canary_detection_scan(
                content_to_scan,
                cd_source,
                latency_timer=_latency_timer,
            )

        if cd_result is not None and cd_result.detected:
            cd_decision = apply_post_scan_pipeline(
                _registry.get(ScannerName.CANARY_DETECTION),
                cd_result,
                _post_scan_ctx,
                file_path=cd_source,
                filename=filename,
            )
            warning_messages.extend(cd_decision.warnings)
            if warn_violation_types is not None and cd_decision.warnings:
                warn_violation_types.append(ViolationType.CANARY_DETECTED)
            if cd_decision.should_block:
                logger.info("Blocking operation due to canary token detection")
                combined_warning = (
                    "\n\n".join(warning_messages) if warning_messages else None
                )
                return (
                    _format_response(
                        adapter,
                        has_secrets=True,
                        error_message=cd_decision.error_message,
                        hook_event=hook_event,
                        warning_message=combined_warning,
                        violation_type=ViolationType.CANARY_DETECTED,
                        security_message=security_message,
                    ),
                    log_only_count,
                )
        elif cd_result is not None and cd_result.error_message:
            warning_messages.append(cd_result.error_message)
            if warn_violation_types is not None:
                warn_violation_types.append(ViolationType.CANARY_DETECTED)

    except Exception as e:
        logger.warning(f"Canary detection check error (fail-open): {e}")

    # Check for config file threats (credential exfiltration patterns in AI config files)
    if ScannerName.CONFIG_FILE in _pipeline_names:
        try:
            cfs_result = run_config_file_scan(
                file_path,
                content_to_scan,
                latency_timer=_latency_timer,
            )

            if cfs_result is not None:
                if cfs_result.detected:
                    cfs_decision = apply_post_scan_pipeline(
                        _registry.get(ScannerName.CONFIG_FILE),
                        cfs_result,
                        _post_scan_ctx,
                        file_path=file_path,
                        filename=filename,
                        blocked_overrides={
                            "details": cfs_result.extra.get("details"),
                        },
                    )
                    warning_messages.extend(cfs_decision.warnings)
                    if warn_violation_types is not None and cfs_decision.warnings:
                        warn_violation_types.append(ViolationType.CONFIG_FILE_EXFIL)
                    if cfs_decision.should_block:
                        if ide_type != IDEType.CURSOR:
                            logger.info(
                                f"Blocking operation for {file_path} due to config file threat"
                            )
                        combined_warning = (
                            "\n\n".join(warning_messages) if warning_messages else None
                        )
                        result = _format_response(
                            adapter,
                            has_secrets=True,
                            error_message=cfs_result.error_message,
                            hook_event=hook_event,
                            warning_message=combined_warning,
                            violation_type=ViolationType.CONFIG_FILE_EXFIL,
                            security_message=security_message,
                        )
                        return (result, log_only_count)
                    elif cfs_result.error_message:
                        warning_messages.append(cfs_result.error_message)
                        if warn_violation_types is not None:
                            warn_violation_types.append(ViolationType.CONFIG_FILE_EXFIL)
                else:
                    if ide_type != IDEType.CURSOR:
                        logger.debug("✓ No config file threats detected")
            elif HAS_CONFIG_SCANNER and ide_type != IDEType.CURSOR:
                logger.info("⚠️  Config file scanning temporarily disabled")
        except Exception as e:
            on_error = _loaders._get_on_scan_error_action()
            if on_error == ActionMode.BLOCK:
                logger.error(
                    f"Config file scanning error (fail-closed, on_scan_error=block): {e}"
                )
                return (
                    _format_response(
                        adapter,
                        has_secrets=True,
                        hook_event=hook_event,
                        error_message=f"Config file scanning failed (blocked by on_scan_error=block): {e}",
                        violation_type=ViolationType.CONFIG_FILE_EXFIL,
                        security_message=security_message,
                    ),
                    log_only_count,
                )
            logger.warning(f"Config file scanning error (fail-open): {e}")

    # Check for secrets in the content
    secret_config, config_error = _loaders._load_secret_scanning_config()
    if config_error:
        warning_messages.append(config_error)

    if ScannerName.SECRET in _pipeline_names and is_feature_enabled(
        secret_config.get("enabled") if secret_config else None, now, default=True
    ):
        # Extract ignore lists and allowlist from config
        ignore_files = secret_config.get("ignore_files", []) if secret_config else []
        ignore_tools = secret_config.get("ignore_tools", []) if secret_config else []
        secret_allowlist = (
            secret_config.get("allowlist_patterns", []) if secret_config else []
        )

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
        secret_scan_content = (
            secret_content_to_scan
            if secret_content_to_scan is not None
            else content_to_scan
        )
        pre_secret_result = run_secret_scan(
            secret_scan_content,
            filename,
            config=secret_config,
            context=pre_secret_ctx,
            file_path=file_path,
            tool_name=tool_identifier,
            ignore_files=ignore_files,
            ignore_tools=ignore_tools,
            allowlist_patterns=secret_allowlist,
            latency_timer=_latency_timer,
        )

        has_secrets = pre_secret_result.detected if pre_secret_result else False
        error_message = pre_secret_result.error_message if pre_secret_result else None

        if not has_secrets and error_message:
            warning_messages.append(error_message)
            if warn_violation_types is not None:
                warn_violation_types.append(ViolationType.SECRET_DETECTED)

        if has_secrets:
            secret_decision = apply_post_scan_pipeline(
                _registry.get(ScannerName.SECRET),
                pre_secret_result,
                _post_scan_ctx,
                file_path=file_path,
                filename=filename,
                skip_violation_log=True,
            )
            warning_messages.extend(secret_decision.warnings)
            if warn_violation_types is not None and secret_decision.warnings:
                warn_violation_types.append(ViolationType.SECRET_DETECTED)
            has_secrets = secret_decision.should_block

        if has_secrets:
            combined_warning = (
                "\n\n".join(warning_messages) if warning_messages else None
            )
            result = _format_response(
                adapter,
                has_secrets=True,
                error_message=error_message,
                hook_event=hook_event,
                warning_message=combined_warning,
                violation_type=ViolationType.SECRET_DETECTED,
                security_message=security_message,
            )
            return (result, log_only_count)

        # No secrets found, allow operation
        if hook_event == HookEvent.PRE_TOOL_USE:
            if file_path:
                logger.info(f"✓ No secrets detected in file '{filename}' ({file_path})")
            else:
                logger.info(f"✓ No secrets detected in file '{filename}'")
        else:
            logger.info("✓ No secrets detected in prompt")
    elif secret_config and ide_type != IDEType.CURSOR:
        # Secret scanning is temporarily disabled
        logger.info("⚠️  Secret scanning temporarily disabled")

    # PII scanning for UserPromptSubmit and PreToolUse (Issue #262)
    pii_was_skipped = False
    if ScannerName.PII in _pipeline_names and content_to_scan:
        pii_scan_content = (
            pii_content_to_scan if pii_content_to_scan is not None else content_to_scan
        )
        logger.info(
            f"Scanning {'prompt' if hook_event == HookEvent.PROMPT else filename} for PII..."
        )
        pii_result = run_pii_scan(
            pii_scan_content,
            file_path=file_path,
            tool_identifier=tool_identifier,
            latency_timer=_latency_timer,
        )

        if pii_result is not None and pii_result.extra.get("skipped"):
            pii_was_skipped = True
        elif pii_result is not None and pii_result.detected:
            has_pii = True
            pii_redactions = pii_result.redactions
            pii_warning = pii_result.error_message
            pii_action = pii_result.extra.get("action", "block")

            if has_pii and not pii_redactions:
                result = _format_response(
                    adapter,
                    has_secrets=True,
                    error_message=pii_warning,
                    hook_event=hook_event,
                    violation_type=ViolationType.PII_DETECTED,
                    security_message=security_message,
                )
                return (result, log_only_count)

            if has_pii and pii_redactions:
                pii_config_for_log, _ = _loaders._load_pii_config()
                pii_action = (pii_config_for_log or {}).get("action", pii_action)
                pii_types = list(set(r.get("type", "unknown") for r in pii_redactions))
                logger.warning(f"PII detected: {pii_types}")

                pii_result.extra["action"] = pii_action
                if pii_redactions and pii_redactions[0].get("line_number") is not None:
                    pii_result.line_number = pii_redactions[0]["line_number"]
                pii_result.matched_text = _extract_pii_matched_text(
                    pii_redactions, pii_scan_content
                )
                pii_result.findings = _pii_redactions_to_findings(
                    pii_redactions, pii_scan_content, pii_warning
                )

                pii_file_path2 = file_path
                if not pii_file_path2:
                    pii_file_path2 = _extract_file_path_from_pii_warning(pii_warning)
                pii_fps = _compute_pii_transcript_fingerprints(
                    pii_redactions, pii_scan_content
                )

                pii_line_number = (
                    pii_redactions[0].get("line_number") if pii_redactions else None
                )
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
                    combined_warning = (
                        "\n\n".join(warning_messages) if warning_messages else None
                    )
                    final_error = pii_warning
                    if combined_warning:
                        final_error = f"{combined_warning}\n\n{final_error}"
                    result = _format_response(
                        adapter,
                        has_secrets=True,
                        error_message=final_error,
                        hook_event=hook_event,
                        violation_type=ViolationType.PII_DETECTED,
                        security_message=security_message,
                    )
                    return (result, log_only_count)
                elif pii_action == "warn":
                    warning_messages.append(pii_warning)
                    if warn_violation_types is not None:
                        warn_violation_types.append(ViolationType.PII_DETECTED)
                elif pii_action == "log-only":
                    log_only_count += 1
                else:
                    logger.warning(
                        f"Unknown PII action '{pii_action}', allowing through"
                    )

    # Transcript scanning for secrets and PII (Issue #430, #442, #935, #936)
    # Detects threats that entered the transcript via ! shell commands (which bypass hooks).
    # Uses polymorphic TranscriptAdapter — JSONL, OpenCode SQLite, Cursor SQLite.
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
                        f"Scanning {ts_adapter.name} transcript for secrets/PII..."
                    )

                    try:
                        ts_secret_config = secret_config
                    except NameError:
                        ts_secret_config, _ = _loaders._load_secret_scanning_config()
                    try:
                        ts_pii_config = pii_config  # noqa: F821 — NameError fallback
                    except NameError:
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
                            f"✓ No threats detected in {ts_adapter.name} transcript"
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
                    f"{ts_adapter.name} transcript scanning error (fail-open): {e}"
                )
            break

    # Save PreToolUse context for PostToolUse correlation (#366)
    if (
        hook_event in (HookEvent.PRE_TOOL_USE, HookEvent.BEFORE_READ_FILE)
        and context_mgr
        and hook_tool_use_id
    ):
        try:
            # Determine if PII scan was skipped and why
            pii_scanned = False
            pii_skip_reason = None
            if content_to_scan:
                if pii_was_skipped:
                    pii_skip_reason = "ignore_files match"
                else:
                    pii_scanned = True

            # Determine if file matched ignore_files
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
                    "secrets_found": False,  # if we got here, no secrets blocked
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
            logger.info(f"PreToolUse: saved context for tool_use_id={hook_tool_use_id}")
        except Exception as e:
            logger.debug(f"Failed to save PreToolUse context (non-fatal): {e}")

    # No block — pipeline passed
    return (None, log_only_count)
