"""Session lifecycle event handlers extracted from hook_processing.py (Phase 5e.1, #1491)."""

import logging

import ai_guardian.config.loaders as _loaders
from ai_guardian.config.utils import get_project_dir, get_project_name
from ai_guardian.constants import ViolationType
from ai_guardian.hook_events.scanners import run_config_file_scan
from ai_guardian.hook_events.utils import _format_response
from ai_guardian.scanners.transcript import _advance_transcript_position

logger = logging.getLogger(__name__)

try:
    from ai_guardian.scanners.config_scanner import ConfigFileScanner  # noqa: F401

    HAS_CONFIG_SCANNER = True
except ImportError:
    HAS_CONFIG_SCANNER = False


def _handle_session_end(hook_data, daemon_state, session_id, adapter):
    """Handle true session end (SessionEnd event) with cleanup.

    Performs best-effort cleanup actions:
    1. Advance transcript position to EOF
    2. Clean up hook contexts for this session
    3. Remove session from security injection tracking
    4. Log session summary

    All steps are fail-open: errors are logged but never raised.

    Returns:
        dict: Empty allow response (exit_code 0)
    """
    session_label = (
        (session_id[:16] + "...")
        if session_id and len(session_id) > 16
        else (session_id or "unknown")
    )
    adapter_name = adapter.name if adapter else "unknown"
    logger.info(f"Session ended for {session_label} (adapter: {adapter_name})")

    contexts_cleaned = 0

    try:
        _advance_transcript_position(hook_data)
    except Exception as e:
        logger.debug(
            f"Session end: transcript position advance failed (non-fatal): {e}"
        )

    try:
        from ai_guardian.hook_context import HookContextManager

        context_mgr = HookContextManager(
            session_id=session_id, daemon_state=daemon_state
        )
        contexts_cleaned = context_mgr.cleanup_session()
    except Exception as e:
        logger.debug(f"Session end: hook context cleanup failed (non-fatal): {e}")

    try:
        from ai_guardian.session_state import SessionStateManager, derive_session_key

        session_key = derive_session_key(hook_data)
        state_mgr = SessionStateManager(daemon_state=daemon_state)
        state_mgr.cleanup_session(session_key)
    except Exception as e:
        logger.debug(f"Session end: session state cleanup failed (non-fatal): {e}")

    token_usage = None
    try:
        from ai_guardian.scanners.transcript.common import (
            _get_transcript_path,
            parse_transcript_token_usage,
        )

        _transcript_path = _get_transcript_path(hook_data)
        if _transcript_path:
            token_usage = parse_transcript_token_usage(_transcript_path)
    except Exception as e:
        logger.debug(f"Session end: token usage parsing failed (non-fatal): {e}")

    try:
        if daemon_state:
            daemon_state.flush_otel_emitter(
                session_id,
                adapter_name=(adapter.name if adapter else None),
                token_usage=token_usage,
            )
        else:
            from ai_guardian.config.loaders import _load_otel_config
            from ai_guardian.scanners.otel_exporter import HookOtelEmitter

            _otel_cfg = _load_otel_config()
            if _otel_cfg.get("enabled"):
                _direct_emitter = HookOtelEmitter(_otel_cfg)
                _direct_emitter.flush(
                    session_id=session_id,
                    adapter_name=(adapter.name if adapter else None),
                    token_usage=token_usage,
                )
    except Exception as e:
        logger.debug(f"Session end: OTEL flush failed (non-fatal): {e}")

    logger.info(f"Session cleanup complete: {contexts_cleaned} contexts removed")

    return {"output": None, "exit_code": 0}


def _handle_bootstrap_scan(
    daemon_state, hook_session_id, adapter, ide_type, hook_event, violation_logger
):
    """Run bootstrap scan if this is a new session. Returns block response or None.

    Called from the SESSION_START handler and from the first-hook path for agents
    that have no dedicated session-start event.
    """
    if not daemon_state:
        return None
    try:
        _bs_cwd = get_project_dir()
        if not daemon_state.is_new_session(hook_session_id, _bs_cwd):
            return None
        logger.info(f"Bootstrap scan: new session detected (cwd={_bs_cwd})")

        _otel_emitter = daemon_state.get_otel_emitter(hook_session_id)
        if _otel_emitter:
            _otel_emitter.record_session_start(
                adapter_name=adapter.name if adapter else None,
                project_name=get_project_name(_bs_cwd),
            )
        _bs_config, _ = _loaders._load_config_scanner_config()
        _bs_results = _run_bootstrap_scan(_bs_cwd, config=_bs_config)
        for _bs_result in _bs_results:
            _bs_action = _bs_result.extra.get("action", "block")
            _bs_file = _bs_result.file_path or _bs_cwd
            _bs_error = _bs_result.error_message or (
                "Agent config file contains credential exfiltration pattern"
            )
            _bs_details = _bs_result.extra.get("details") or {}
            logger.warning(f"Bootstrap scan: threat in {_bs_file}: {_bs_error}")
            if violation_logger:
                try:
                    violation_logger.log_violation(
                        violation_type=ViolationType.CONFIG_FILE_EXFIL,
                        blocked={
                            "violation_id": _bs_result.id,
                            "file_path": _bs_file,
                            "line_number": _bs_details.get("line_number"),
                            "reason": _bs_error,
                            "details": _bs_details,
                        },
                        context={
                            "source": "bootstrap_scan",
                            "ide_type": (
                                ide_type.value
                                if hasattr(ide_type, "value")
                                else str(ide_type)
                            ),
                            "hook_event": hook_event,
                            "project_path": _bs_cwd,
                            "session_id": hook_session_id or "",
                        },
                        suggestion={
                            "action": "review_config_file",
                            "false_positive": (
                                "Move to examples/ directory, or add to "
                                "config_file_scanning.ignore_files"
                            ),
                        },
                        severity="critical",
                        violation_id=_bs_result.id,
                    )
                except Exception:
                    pass
            if _bs_action == "block":
                _bs_formatted = (
                    f"\n{'='*70}\n"
                    f"🚨 BLOCKED BY POLICY\n"
                    f"🛡️ BOOTSTRAP SCAN — SESSION BLOCKED\n"
                    f"{'='*70}\n\n"
                    f"Threat detected in agent config file before session start.\n\n"
                    f"File:   {_bs_file}\n"
                    f"Reason: {_bs_error}\n\n"
                    f"Recommended actions:\n"
                    f"  1. Review the file listed above\n"
                    f"  2. Remove the malicious instruction\n"
                    f"  3. Restart your Claude Code session\n"
                    f"  4. If false positive: add to config_file_scanning.ignore_files\n"
                    f"{'='*70}\n"
                )
                return _format_response(
                    adapter,
                    has_secrets=True,
                    error_message=_bs_formatted,
                    hook_event=hook_event,
                    violation_type=ViolationType.CONFIG_FILE_EXFIL,
                )
            elif _bs_action == "warn":
                _bs_formatted = (
                    f"\n{'='*70}\n"
                    f"⚠️  WARNING — POLICY VIOLATION DETECTED\n"
                    f"🛡️ BOOTSTRAP SCAN — SESSION ALLOWED WITH WARNING\n"
                    f"{'='*70}\n\n"
                    f"Threat detected in agent config file before session start.\n"
                    f"Session is allowed to continue (action=warn).\n\n"
                    f"File:   {_bs_file}\n"
                    f"Reason: {_bs_error}\n\n"
                    f"Recommended actions:\n"
                    f"  1. Review the file listed above\n"
                    f"  2. Remove the malicious instruction\n"
                    f"  3. If false positive: add to config_file_scanning.ignore_files\n"
                    f"{'='*70}\n"
                )
                return _format_response(
                    adapter,
                    warning_message=_bs_formatted,
                    hook_event=hook_event,
                    violation_type=ViolationType.CONFIG_FILE_EXFIL,
                )

    except Exception as _bs_exc:
        logger.debug(f"Bootstrap scan error (non-fatal): {_bs_exc}")
    return None


def _run_bootstrap_scan(cwd: str, config=None) -> list:
    """Scan agent config files in cwd for exfiltration threats at session start.

    Called once per session via DaemonState.is_new_session(). Returns a list of
    ScanResult objects for each config file that triggered a detection.
    """
    if not HAS_CONFIG_SCANNER:
        return []

    from ai_guardian.scanners.config_scanner import ConfigFileScanner
    from pathlib import Path as _Path

    if config is None:
        config, _ = _loaders._load_config_scanner_config()

    scanner = ConfigFileScanner(config)
    cwd_path = _Path(cwd)
    results = []

    for pattern in scanner.DEFAULT_CONFIG_FILES:
        file_path = cwd_path / pattern
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        result = run_config_file_scan(str(file_path), content, config=config)
        if result is not None and result.detected:
            results.append(result)

    return results
