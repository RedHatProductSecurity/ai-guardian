"""PostToolUse event handler extracted from hook_processing.py (Phase 5e.2, #1491)."""

import logging
from typing import Dict, Optional

import ai_guardian.config.loaders as _loaders
import ai_guardian.scanners.secret_scanning as _secret_scanning_mod
from ai_guardian.config.utils import get_project_dir, is_feature_enabled
from ai_guardian.constants import ActionMode, ViolationType, HookEvent
from ai_guardian.hook_events.utils import (
    _format_response,  # noqa: F401
    _extract_pii_matched_text,
    _pii_redactions_to_findings,
    _extract_file_path_from_pii_warning,
)
from ai_guardian.scanners.scan_result import ScanResult
from ai_guardian.scanners.transcript import _advance_transcript_position

from ai_guardian.ask_mode import (
    _handle_ask_mode_auto,
    _format_ask_info_message,
    _log_ask_decision,
    _compute_pii_transcript_fingerprints,
)

from ai_guardian.hook_events.scanners import (
    _load_overlaid_config,
    run_secret_scan,
    run_prompt_injection_scan,
    run_context_poisoning_scan,
    run_offensive_language_scan,
    run_pii_scan,
)
from ai_guardian.scanners.scanner_registry import ScannerName, get_default_registry

logger = logging.getLogger(__name__)


_MAX_REDACTED_CONTEXT_BYTES = 102400
_MAX_SOURCE_COMMAND_LEN = 500


# Deferred-import wrappers for functions defined in hook_processing.py.
# Module-level imports would create a circular dependency.
def extract_tool_result(hook_data):
    from ai_guardian.hook_processing import extract_tool_result as _etr

    return _etr(hook_data)


def _extract_context_snippet(text, line_number):
    from ai_guardian.hook_processing import _extract_context_snippet as _ecs

    return _ecs(text, line_number)


def _sanitize_source_command(command: str) -> str:
    """Sanitize a Bash command through secret scanning before storing."""
    try:
        from ai_guardian.scanners.secret_scanning import check_secrets

        has_secrets, _ = check_secrets(command, filename="source_command")
        if has_secrets:
            return "[redacted — command contains secrets]"
    except Exception:
        pass
    return command[:_MAX_SOURCE_COMMAND_LEN]


# ---------------------------------------------------------------------------
# Conditional imports
# ---------------------------------------------------------------------------

try:
    from ai_guardian.violations.logger import ViolationLogger

    HAS_VIOLATION_LOGGER = True
except ImportError:
    ViolationLogger = None
    HAS_VIOLATION_LOGGER = False


try:
    from ai_guardian.annotations import process_annotations

    HAS_ANNOTATIONS = True
except ImportError:
    HAS_ANNOTATIONS = False


# ---------------------------------------------------------------------------
# Violation logger functions
# ---------------------------------------------------------------------------


def _log_prompt_injection_violation(
    filename: str,
    context: Optional[Dict] = None,
    attack_type: str = "injection",
    hook_context: Optional[Dict] = None,
    matched_pattern: Optional[str] = None,
    matched_text: Optional[str] = None,
    confidence: Optional[float] = None,
    line_number: Optional[int] = None,
    start_column: Optional[int] = None,
    end_column: Optional[int] = None,
    violation_logger=None,
):
    """
    Log a prompt injection or jailbreak violation.

    Args:
        filename: Name of the file/prompt where injection was detected
        context: Optional context dict with ide_type, hook_event, etc.
        attack_type: Type of attack - "injection" or "jailbreak"
        hook_context: Optional dict with tool_use_id, session_id for correlation
        matched_pattern: The regex or pattern name that matched
        matched_text: The text that triggered detection
        line_number: 1-based line number where the match was found
        start_column: 0-based start column within the line
        end_column: 0-based end column within the line
        confidence: Actual confidence score from the detector
    """
    if not HAS_VIOLATION_LOGGER:
        return

    try:
        ctx = context or {}
        vtype = (
            ViolationType.JAILBREAK_DETECTED
            if attack_type == "jailbreak"
            else ViolationType.PROMPT_INJECTION
        )
        reason = (
            "Jailbreak attempt detected"
            if attack_type == "jailbreak"
            else "Prompt injection pattern detected"
        )
        full_path = ctx.get("file_path")
        if not full_path and filename != "user_prompt":
            full_path = filename
        blocked_entry = {
            "file_path": full_path,
            "line_number": line_number,
            "source": "prompt" if filename == "user_prompt" else "file",
            "pattern": matched_pattern or "Unknown",
            "confidence": confidence if confidence is not None else 0.0,
            "method": "heuristic",
            "reason": reason,
        }
        if start_column is not None:
            blocked_entry["start_column"] = start_column
        if end_column is not None:
            blocked_entry["end_column"] = end_column
        if matched_text:
            blocked_entry["matched_text"] = matched_text[:100]
        violation_logger = violation_logger or ViolationLogger()
        violation_logger.log_violation(
            violation_type=vtype,
            blocked=blocked_entry,
            context=_secret_scanning_mod._build_violation_context(
                context, hook_context
            ),
            suggestion={
                "action": "add_allowlist_pattern",
                "note": "If this is legitimate (e.g., documentation), add to allowlist in ai-guardian.json",
            },
            severity="high",
        )
    except Exception as e:
        logger.error(f"Failed to log prompt injection violation: {e}")


def _log_context_poisoning_violation(
    filename: str,
    context: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    matched_pattern: Optional[str] = None,
    matched_text: Optional[str] = None,
    confidence: Optional[float] = None,
    line_number: Optional[int] = None,
    start_column: Optional[int] = None,
    end_column: Optional[int] = None,
    violation_logger=None,
):
    """Log a context poisoning violation."""
    if not HAS_VIOLATION_LOGGER:
        return

    try:
        ctx = context or {}
        blocked_entry = {
            "file_path": ctx.get("file_path"),
            "line_number": line_number,
            "source": "prompt",
            "pattern": matched_pattern or "Unknown",
            "confidence": confidence if confidence is not None else 0.0,
            "method": "heuristic",
            "reason": "Context poisoning attempt detected",
        }
        if start_column is not None:
            blocked_entry["start_column"] = start_column
        if end_column is not None:
            blocked_entry["end_column"] = end_column
        if matched_text:
            blocked_entry["matched_text"] = matched_text[:100]
        violation_logger = violation_logger or ViolationLogger()
        violation_logger.log_violation(
            violation_type=ViolationType.CONTEXT_POISONING,
            blocked=blocked_entry,
            context=_secret_scanning_mod._build_violation_context(
                context, hook_context
            ),
            suggestion={
                "action": "add_allowlist_pattern",
                "note": "If this is a legitimate persistent instruction, add to context_poisoning.allowlist_patterns in ai-guardian.json",
            },
            severity="medium",
        )
    except Exception as e:
        logger.error(f"Failed to log context poisoning violation: {e}")


def _log_offensive_language_violation(
    result,
    hook_name: str,
    hook_event: str,
    tool_identifier: Optional[str] = None,
    hook_tool_use_id: Optional[str] = None,
    hook_session_id: Optional[str] = None,
    violation_logger=None,
):
    """Log an offensive language violation."""
    if not HAS_VIOLATION_LOGGER:
        return
    try:
        findings = result.findings or []
        first = findings[0] if findings else {}
        blocked_entry = {
            "file_path": result.file_path,
            "line_number": result.line_number,
            "rule_id": result.rule_id,
            "category": result.attack_type,
            "matched_text": result.matched_text[:100] if result.matched_text else "",
            "suggestion": first.get("suggestion", ""),
            "total_findings": result.total_findings,
        }
        if result.start_column is not None:
            blocked_entry["start_column"] = result.start_column
        if result.end_column is not None:
            blocked_entry["end_column"] = result.end_column
        ctx = {
            "action": result.extra.get("action", "log"),
            "hook_event": hook_event,
            "hook": hook_name,
            "tool": tool_identifier,
        }
        if hook_tool_use_id:
            ctx["tool_use_id"] = hook_tool_use_id
        if hook_session_id:
            ctx["session_id"] = hook_session_id
        vl = violation_logger or ViolationLogger()
        vl.log_violation(
            violation_type=ViolationType.OFFENSIVE_LANGUAGE,
            blocked=blocked_entry,
            context=ctx,
            suggestion={
                "action": "review_offensive_language",
                "note": (
                    "Replace the term with a neutral alternative. "
                    "Add '# ai-guardian:allow' inline or use scan_offensive.allowlist_patterns "
                    "to suppress known-safe uses."
                ),
            },
        )
    except Exception as e:
        logger.error(f"Failed to log offensive language violation: {e}")


def _log_pii_violation(
    violation_logger,
    pii_config,
    pii_redactions,
    tool_identifier,
    hook_name,
    file_path,
    snippet_text,
    hook_event,
    hook_tool_use_id=None,
    hook_session_id=None,
    bash_command=None,
    pretool_ctx=None,
    source_command=None,
):
    """Log a PII violation and return (pii_action, pii_types)."""
    pii_action = pii_config.get("action", "block")
    pii_types = list(set(r["type"] for r in pii_redactions))
    pii_first_line = pii_redactions[0].get("line_number") if pii_redactions else None

    first_redaction = pii_redactions[0] if pii_redactions else {}
    pii_start_column = first_redaction.get("column")
    if pii_start_column is not None:
        pii_start_column = pii_start_column - 1
    pii_end_column = None
    if pii_start_column is not None:
        orig_len = first_redaction.get("original_length", 0)
        if orig_len:
            pii_end_column = pii_start_column + orig_len

    pii_blocked = {
        "tool": tool_identifier,
        "hook": hook_name,
        "file_path": file_path,
        "line_number": pii_first_line,
        "pii_count": len(pii_redactions),
        "pii_types": pii_types,
    }
    if pii_start_column is not None:
        pii_blocked["start_column"] = pii_start_column
    if pii_end_column is not None:
        pii_blocked["end_column"] = pii_end_column
    if bash_command:
        pii_blocked["command"] = bash_command
    if source_command and file_path and str(file_path).startswith("tool_result:"):
        pii_blocked["source_command"] = source_command
    snippet = _extract_context_snippet(snippet_text, pii_first_line)
    if snippet:
        pii_blocked["context_snippet"] = snippet

    pii_ctx = {"action": pii_action, "hook_event": hook_event}
    if hook_tool_use_id:
        pii_ctx["tool_use_id"] = hook_tool_use_id
    if hook_session_id:
        pii_ctx["session_id"] = hook_session_id
    if pretool_ctx:
        pii_ctx["pretool_context"] = pretool_ctx

    if violation_logger:
        violation_logger.log_violation(
            violation_type=ViolationType.PII_DETECTED,
            blocked=pii_blocked,
            context=pii_ctx,
            suggestion={
                "action": "review_pii_detection",
                "false_positive": (
                    "Allowlist the value in scan_pii.allowlist_patterns, "
                    "disable specific PII types in scan_pii.pii_types, "
                    "or add '# ai-guardian:allow' inline"
                ),
            },
        )

    return pii_action, pii_types


# ---------------------------------------------------------------------------
# PostToolUse handler
# ---------------------------------------------------------------------------


def handle_post_tool_use(ctx=None, **kwargs):
    """Handle PostToolUse event — scan tool output before sending to AI.

    Accepts either a HookContext object (ctx) or individual keyword arguments
    for backward compatibility.

    Returns:
        dict: Response with 'output' and 'exit_code'.
    """
    if ctx is not None:
        hook_data = ctx.hook_data
        adapter = ctx.adapter
        ide_type = ctx.ide_type
        hook_event = ctx.hook_event
        hook_tool_use_id = ctx.hook_tool_use_id
        hook_session_id = ctx.hook_session_id
        context_mgr = ctx.context_mgr
        violation_logger = ctx.violation_logger
        _latency_timer = ctx._latency_timer
        _invocation_allowed = ctx._invocation_allowed
        now = ctx.now
    else:
        hook_data = kwargs["hook_data"]
        adapter = kwargs["adapter"]
        ide_type = kwargs["ide_type"]
        hook_event = kwargs["hook_event"]
        hook_tool_use_id = kwargs["hook_tool_use_id"]
        hook_session_id = kwargs["hook_session_id"]
        context_mgr = kwargs["context_mgr"]
        violation_logger = kwargs["violation_logger"]
        _latency_timer = kwargs["_latency_timer"]
        _invocation_allowed = kwargs["_invocation_allowed"]
        now = kwargs["now"]

    logger.info("Processing PostToolUse hook...")

    # Extract tool output
    tool_output, tool_name = extract_tool_result(hook_data)
    logger.info(
        f"PostToolUse: tool_name={tool_name}, has_output={tool_output is not None}"
    )

    if tool_output is None:
        # No output to scan - allow
        _advance_transcript_position(hook_data)
        return _format_response(adapter, has_secrets=False, hook_event=hook_event)

    # Create composite tool identifier for more granular ignore patterns
    # This allows ignore_tools to match both PreToolUse (input) and PostToolUse (output)
    # For Skill tool: "Skill:code-review"
    # For MCP tools: already have composite name like "mcp__notebooklm__chat"
    tool_identifier = tool_name

    # Get tool_input from either tool_use.input or tool_input field
    tool_input = {}
    if "tool_use" in hook_data and isinstance(hook_data["tool_use"], dict):
        tool_input = hook_data["tool_use"].get("input", {})
    elif "tool_input" in hook_data and isinstance(hook_data["tool_input"], dict):
        tool_input = hook_data["tool_input"]

    if tool_name == "Skill" and tool_input.get("skill"):
        tool_identifier = f"Skill:{tool_input['skill']}"
        logger.info(
            f"PostToolUse (with output): Created composite identifier {tool_identifier}"
        )

    logger.info(f"PostToolUse tool_identifier: {tool_identifier}")

    # Extract command for Bash tool (for violation context)
    bash_command = None
    source_command = None
    if tool_name == "Bash":
        raw_cmd = tool_input.get("command", "")
        if raw_cmd:
            bash_command = raw_cmd[:_MAX_SOURCE_COMMAND_LEN]
            source_command = _sanitize_source_command(raw_cmd)

    # Load PreToolUse context for cross-hook correlation (#366)
    pretool_ctx = None
    if context_mgr and hook_tool_use_id:
        pretool_ctx = context_mgr.get_pretool_context(hook_tool_use_id)
        if pretool_ctx:
            logger.info(
                f"PostToolUse: loaded PreToolUse context for {hook_tool_use_id}"
            )
            # Inherit file_path from PreToolUse if not available in PostToolUse
            if not tool_input.get("file_path") and not tool_input.get("path"):
                pretool_file = pretool_ctx.get("file_path")
                if pretool_file:
                    logger.info(f"PostToolUse: inherited file_path={pretool_file}")

    logger.info(f"Scanning {tool_identifier} output for secrets...")

    # Apply annotation suppression for file-reading tools (Issue #481)
    # If PreToolUse was a file read, annotations in the output should be honored
    # to prevent blocking/redaction of suppressed lines
    post_annotations_config = None
    post_secret_content = None
    post_all_suppressed = set()
    post_secret_suppressed = set()
    original_tool_output = tool_output
    if HAS_ANNOTATIONS and pretool_ctx and pretool_ctx.get("file_path") and tool_output:
        post_annotations_config, _ = _loaders._load_annotations_config()
        if post_annotations_config and is_feature_enabled(
            post_annotations_config.get("enabled"), now, default=True
        ):
            post_all_content, post_secret_content_sup, post_ann_info, _ = (
                process_annotations(
                    tool_output,
                    file_path=pretool_ctx.get("file_path"),
                    config=post_annotations_config,
                )
            )
            if post_ann_info:
                tool_output = post_all_content
                post_secret_content = post_secret_content_sup
                total_suppressed = sum(len(s.get("lines", [])) for s in post_ann_info)
                logger.info(
                    f"PostToolUse: annotation suppression applied "
                    f"({total_suppressed} line(s) suppressed)"
                )

    # Load secret scanning config for ignore lists
    secret_config, config_error = _loaders._load_secret_scanning_config()

    # If config has errors, log warning and continue with defaults
    # (ignore lists default to [] when secret_config is None)
    if config_error:
        logger.warning(f"Config error in PostToolUse: {config_error}")

    # Check if secret scanning is enabled (respect disabled_until)
    if secret_config and not is_feature_enabled(
        secret_config.get("enabled", True), now, default=True
    ):
        logger.info("Secret scanning is disabled - skipping PostToolUse scan")
        _advance_transcript_position(hook_data)
        return _format_response(adapter, has_secrets=False, hook_event=hook_event)

    ignore_files = secret_config.get("ignore_files", []) if secret_config else []
    ignore_tools = secret_config.get("ignore_tools", []) if secret_config else []
    secret_allowlist = (
        secret_config.get("allowlist_patterns", []) if secret_config else []
    )

    # Cross-hook optimization: skip secret scan if PreToolUse already scanned clean (#366)
    pretool_scan = pretool_ctx.get("scan_results", {}) if pretool_ctx else {}
    skip_secret_scan = pretool_scan.get("secrets_scanned") and not pretool_scan.get(
        "secrets_found"
    )
    if skip_secret_scan:
        logger.info(
            "PostToolUse: skipping secret scan (PreToolUse already scanned clean)"
        )

    # Cross-hook optimization: respect ignore_files from PreToolUse (#366)
    if pretool_ctx and pretool_ctx.get("ignore_files_matched"):
        logger.info(
            "PostToolUse: skipping scans (file matched ignore_files in PreToolUse)"
        )
        skip_secret_scan = True

    post_secret_ctx = {
        "ide_type": ide_type.value,
        "hook_event": HookEvent.POST_TOOL_USE,
        "tool_name": tool_identifier,
        "source": "scanner",
    }
    file_path_for_ctx = tool_input.get("file_path") or tool_input.get("path")
    if not file_path_for_ctx and pretool_ctx:
        file_path_for_ctx = pretool_ctx.get("file_path")
    if file_path_for_ctx:
        post_secret_ctx["file_path"] = file_path_for_ctx
    if hook_tool_use_id:
        post_secret_ctx["tool_use_id"] = hook_tool_use_id
    if hook_session_id:
        post_secret_ctx["session_id"] = hook_session_id
    if source_command:
        post_secret_ctx["source_command"] = source_command

    if skip_secret_scan:
        has_secrets = False
        error_message = None
    else:
        post_scan_content = (
            post_secret_content if post_secret_content is not None else tool_output
        )
        post_secret_result = run_secret_scan(
            post_scan_content,
            f"{tool_identifier}_output",
            config=secret_config,
            context=post_secret_ctx,
            tool_name=tool_identifier,
            ignore_files=ignore_files,
            ignore_tools=ignore_tools,
            allowlist_patterns=secret_allowlist,
            latency_timer=_latency_timer,
        )
        has_secrets = post_secret_result.detected if post_secret_result else False
        error_message = post_secret_result.error_message if post_secret_result else None

    if not has_secrets and error_message:
        # Scanner not available - display warning but allow operation
        _advance_transcript_position(hook_data)
        return _format_response(
            adapter,
            has_secrets=False,
            hook_event=hook_event,
            warning_message=error_message,
            violation_type=ViolationType.SECRET_DETECTED,
        )

    if has_secrets:
        # Check if redaction is enabled
        redaction_config, redaction_error = _loaders._load_secret_redaction_config()

        if redaction_error:
            logger.warning(f"Config error loading secret_redaction: {redaction_error}")
            # Fall back to blocking
            logger.warning(f"Secrets detected in {tool_identifier} output - blocking")
            result = _format_response(
                adapter,
                has_secrets=True,
                error_message=error_message,
                hook_event=hook_event,
                violation_type=ViolationType.SECRET_DETECTED,
            )
            _advance_transcript_position(hook_data)
            return result

        # Determine action mode (always redact when secrets detected)
        if redaction_config is None:
            redaction_config = {}

        action = redaction_config.get("action", ActionMode.WARN)
        enabled = redaction_config.get("enabled", True)

        if enabled:
            # REDACT instead of block
            logger.info(f"Secret redaction enabled with action={action}")

            try:
                from ai_guardian.scanners.secret_redactor import SecretRedactor

                # Also load PII config so secrets+PII are handled in one pass
                pii_config_for_redactor, _ = _loaders._load_pii_config()
                pii_cfg = (
                    pii_config_for_redactor
                    if pii_config_for_redactor
                    and pii_config_for_redactor.get("enabled", True)
                    else None
                )
                redactor = SecretRedactor(redaction_config, pii_config=pii_cfg)
                with _latency_timer.check("secret_redaction"):
                    result = redactor.redact(tool_output)

                redacted_text = result["redacted_text"]
                redactions = result["redactions"]

                if not redactions:
                    logger.warning(
                        "Secret detected but redactor produced 0 redactions "
                        f"for {tool_identifier} output — falling back to block"
                    )
                    _advance_transcript_position(hook_data)
                    return _format_response(
                        adapter,
                        has_secrets=True,
                        error_message=error_message,
                        hook_event=hook_event,
                        violation_type=ViolationType.SECRET_DETECTED,
                    )

                # Restore original content on annotation-suppressed lines
                if post_all_suppressed or post_secret_suppressed:
                    all_post_suppressed = post_all_suppressed | post_secret_suppressed
                    redacted_lines = redacted_text.splitlines()
                    original_lines = original_tool_output.splitlines()
                    for idx in all_post_suppressed:
                        if 0 <= idx < len(redacted_lines) and idx < len(original_lines):
                            redacted_lines[idx] = original_lines[idx]
                    redacted_text = "\n".join(redacted_lines)

                # Log redaction event
                logger.warning(
                    f"Redacted {len(redactions)} secret(s) from {tool_identifier} output"
                )
                for r in redactions:
                    logger.info(
                        f"  - {r['type']} at position {r['position']} using {r['strategy']}"
                    )

                # Log to violation logger
                first_line = redactions[0].get("line_number") if redactions else None
                blocked_info = {
                    "tool": tool_identifier,
                    "file_path": file_path_for_ctx,
                    "line_number": first_line,
                    "redaction_count": len(redactions),
                    "redacted_types": [r["type"] for r in redactions],
                }
                if bash_command:
                    blocked_info["command"] = bash_command
                if (
                    source_command
                    and file_path_for_ctx
                    and str(file_path_for_ctx).startswith("tool_result:")
                ):
                    blocked_info["source_command"] = source_command
                snippet = _extract_context_snippet(redacted_text, first_line)
                if snippet:
                    blocked_info["context_snippet"] = snippet
                ctx = {
                    "action": "redacted",
                    "mode": action,
                    "hook_event": HookEvent.POST_TOOL_USE,
                    "tool_name": tool_identifier,
                    "source": "redaction",
                }
                if file_path_for_ctx:
                    ctx["file_path"] = file_path_for_ctx
                if hook_tool_use_id:
                    ctx["tool_use_id"] = hook_tool_use_id
                if hook_session_id:
                    ctx["session_id"] = hook_session_id
                if pretool_ctx:
                    ctx["pretool_context"] = pretool_ctx
                if violation_logger:
                    violation_logger.log_violation(
                        violation_type=ViolationType.SECRET_REDACTION,
                        blocked=blocked_info,
                        context=ctx,
                    )

                # Return redacted output (allow, with modifications)
                # For warn mode, include a warning message
                warning_msg = None
                if action == ActionMode.WARN:
                    warning_msg = (
                        f"⚠️  Redacted {len(redactions)} secret(s) from output:\n"
                        + "\n".join([f"  - {r['type']}" for r in redactions[:5]])
                        + ("\n  - ..." if len(redactions) > 5 else "")
                    )
                    logger.warning(f"WARN mode: {warning_msg}")

                # Block output containing detected secrets.
                # Redaction produces correct modified_output, but upstream
                # Claude Code ignores updatedToolOutput (anthropics/claude-code
                # #68951). Block to prevent unredacted output reaching agent.
                # Send redacted output via additionalContext so the agent
                # can continue working with sanitized content (#1630).
                if len(redacted_text) > _MAX_REDACTED_CONTEXT_BYTES:
                    orig_len = len(redacted_text)
                    redacted_text = (
                        redacted_text[:_MAX_REDACTED_CONTEXT_BYTES]
                        + f"\n\n[Truncated: original output was {orig_len} bytes]"
                    )
                logger.info(
                    "Secrets redacted — blocking output, "
                    "sending redacted content via additionalContext"
                )
                result = _format_response(
                    adapter,
                    has_secrets=True,
                    error_message=error_message,
                    hook_event=hook_event,
                    warning_message=warning_msg,
                    violation_type=ViolationType.SECRET_REDACTION,
                    redacted_output=redacted_text,
                )
                result["_warning"] = True
                _advance_transcript_position(hook_data)
                return result

            except Exception as redact_error:
                logger.error(f"Error during secret redaction: {redact_error}")
                import traceback

                logger.error(traceback.format_exc())
                # Fall back to blocking on redaction errors
                logger.warning("Redaction failed, falling back to blocking")
                result = _format_response(
                    adapter,
                    has_secrets=True,
                    error_message=error_message,
                    hook_event=hook_event,
                    violation_type=ViolationType.SECRET_REDACTION,
                )
                _advance_transcript_position(hook_data)
                return result
        else:
            # Redaction disabled - block to prevent secrets from reaching AI model
            logger.warning("Secrets detected and redaction disabled - blocking output")
            result = _format_response(
                adapter,
                has_secrets=True,
                error_message=error_message,
                hook_event=hook_event,
                violation_type=ViolationType.SECRET_DETECTED,
            )
            _advance_transcript_position(hook_data)
            return result

    logger.info(f"✓ No secrets detected in {tool_identifier} output")

    # Accumulate warning messages for PII ask-mode decisions
    warning_messages = []

    # PII scanning in PostToolUse (Issue #262)
    pii_file_path = tool_input.get("file_path") or tool_input.get("path")
    if not pii_file_path and pretool_ctx:
        pii_file_path = pretool_ctx.get("file_path")

    # Cross-hook optimization: skip PII scan if PreToolUse skipped via ignore_files (#366)
    pii_skip_from_pretool = (
        pretool_ctx
        and pretool_ctx.get("scan_results", {}).get("pii_skipped_reason")
        == "ignore_files match"
    )
    if not pii_skip_from_pretool:
        logger.info("Scanning tool output for PII...")
        post_pii_result = run_pii_scan(
            tool_output,
            file_path=pii_file_path,
            tool_identifier=tool_identifier,
            latency_timer=_latency_timer,
        )

        if post_pii_result is not None and not post_pii_result.extra.get("skipped"):
            has_pii = post_pii_result.detected
            redacted_text = post_pii_result.redacted_content
            pii_redactions = post_pii_result.redactions
            pii_warning = post_pii_result.error_message

            # Scan error with on_scan_error=block: block without logging a false violation (#507)
            if has_pii and not pii_redactions:
                result = _format_response(
                    adapter,
                    has_secrets=True,
                    hook_event=hook_event,
                    error_message=pii_warning,
                    violation_type=ViolationType.PII_DETECTED,
                )
                _advance_transcript_position(hook_data)
                return result

            if has_pii and pii_redactions:
                if not pii_file_path:
                    pii_file_path = _extract_file_path_from_pii_warning(pii_warning)
                pii_snippet_text = redacted_text if redacted_text else tool_output
                post_pii_config, _ = _loaders._load_pii_config()
                pii_action, pii_types = _log_pii_violation(
                    violation_logger,
                    post_pii_config
                    or {"action": post_pii_result.extra.get("action", "block")},
                    pii_redactions,
                    tool_identifier,
                    HookEvent.POST_TOOL_USE.display_name,
                    pii_file_path,
                    pii_snippet_text,
                    HookEvent.POST_TOOL_USE,
                    hook_tool_use_id=hook_tool_use_id,
                    hook_session_id=hook_session_id,
                    bash_command=bash_command,
                    pretool_ctx=pretool_ctx,
                    source_command=source_command,
                )
                logger.warning(f"PII detected in {tool_identifier} output: {pii_types}")

                # Build multi-finding list from PII redactions
                pii_matched_text = _extract_pii_matched_text(
                    pii_redactions, tool_output
                )
                pii_findings = _pii_redactions_to_findings(
                    pii_redactions, tool_output, pii_warning
                )

                # Check ask action mode before standard routing
                pii_line_number = (
                    pii_redactions[0].get("line_number") if pii_redactions else None
                )
                pii_ask_result = _handle_ask_mode_auto(
                    pii_action,
                    ViolationType.PII_DETECTED,
                    config_section="scan_pii",
                    error_msg=pii_warning,
                    file_path=pii_file_path,
                    matched_text=pii_matched_text,
                    line_number=pii_line_number,
                    latency_timer=_latency_timer,
                    hook_context={
                        "session_id": hook_session_id,
                        "project_path": get_project_dir(),
                        "hook_event": hook_event,
                        "tool_name": tool_name,
                    },
                    findings=pii_findings,
                )
                if pii_ask_result is not None:
                    from ai_guardian.tui.ask_dialog import AskDecision

                    if pii_ask_result.decision not in (
                        AskDecision.BLOCK,
                        AskDecision.BLOCK_ALL,
                    ):
                        pii_action = "warn"
                        pii_info_msg = _format_ask_info_message(
                            ViolationType.PII_DETECTED, pii_ask_result.decision
                        )
                        warning_messages.append(pii_info_msg)
                        _log_ask_decision(
                            ViolationType.PII_DETECTED,
                            pii_ask_result.decision,
                            matched_text=pii_matched_text,
                            error_msg=pii_warning or "",
                            file_path=pii_file_path,
                            line_number=pii_line_number,
                            dialog_wait_ms=pii_ask_result.dialog_wait_ms,
                            invocation_allowed_findings=_invocation_allowed,
                            finding_fingerprints=_compute_pii_transcript_fingerprints(
                                pii_redactions, tool_output
                            ),
                        )
                    else:
                        pii_action = "block"
                        _log_ask_decision(
                            ViolationType.PII_DETECTED,
                            pii_ask_result.decision,
                            matched_text=pii_matched_text,
                            error_msg=pii_warning or "",
                            file_path=pii_file_path,
                            line_number=pii_line_number,
                            dialog_wait_ms=pii_ask_result.dialog_wait_ms,
                        )

                if pii_action == "block":
                    result = _format_response(
                        adapter,
                        has_secrets=True,
                        hook_event=hook_event,
                        error_message=pii_warning,
                        violation_type=ViolationType.PII_DETECTED,
                    )
                    _advance_transcript_position(hook_data)
                    return result
                elif pii_action == "redact":
                    # Restore original content on annotation-suppressed lines
                    if post_all_suppressed:
                        pii_redacted_lines = redacted_text.splitlines()
                        pii_original_lines = original_tool_output.splitlines()
                        for idx in post_all_suppressed:
                            if 0 <= idx < len(pii_redacted_lines) and idx < len(
                                pii_original_lines
                            ):
                                pii_redacted_lines[idx] = pii_original_lines[idx]
                            redacted_text = "\n".join(pii_redacted_lines)
                    result = _format_response(
                        adapter,
                        has_secrets=False,
                        hook_event=hook_event,
                        warning_message=pii_warning,
                        modified_output=redacted_text,
                        violation_type=ViolationType.PII_DETECTED,
                    )
                    result["_warning"] = True
                    result["_violation_type"] = ViolationType.PII_DETECTED
                    _advance_transcript_position(hook_data)
                    return result
                elif pii_action == "warn":
                    result = _format_response(
                        adapter,
                        has_secrets=False,
                        hook_event=hook_event,
                        warning_message=pii_warning,
                        violation_type=ViolationType.PII_DETECTED,
                    )
                    result["_warning"] = True
                    result["_violation_type"] = ViolationType.PII_DETECTED
                    _advance_transcript_position(hook_data)
                    return result
                elif pii_action == "log-only":
                    result = _format_response(
                        adapter, has_secrets=False, hook_event=hook_event
                    )
                    result["_log_only"] = 1
                    result["_violation_type"] = ViolationType.PII_DETECTED
                    _advance_transcript_position(hook_data)
                    return result
                else:
                    logger.warning(
                        f"Unknown PII action '{pii_action}', allowing through"
                    )
                    _advance_transcript_position(hook_data)
                    return _format_response(
                        adapter, has_secrets=False, hook_event=hook_event
                    )

    # Prompt injection and context poisoning scanning on PostToolUse output (#1285)
    post_warning_messages = []
    post_warn_types: list = []
    post_pi_cp_filename = (
        f"{tool_identifier}_output" if tool_identifier else "tool_output"
    )

    # Generic overlay pre-compute — same pattern as content_pipeline (#1682).
    _ptu_registry = get_default_registry()
    ptu_overlaid_configs = {
        e.name: oc
        for e in _ptu_registry.get_pipeline(hook_event, has_content=True)
        if (oc := _load_overlaid_config(e)) is not None
    }

    if tool_output:
        try:
            # Cross-hook optimization: skip if PreToolUse already scanned clean (#366)
            post_pi_skip = pretool_scan.get(
                "prompt_injection_scanned"
            ) and not pretool_scan.get("prompt_injection_found")
            if pretool_ctx and pretool_ctx.get("ignore_files_matched"):
                post_pi_skip = True

            if post_pi_skip:
                logger.info(
                    "PostToolUse: skipping PI scan (PreToolUse already scanned clean)"
                )
            else:
                post_pi_file = tool_input.get("file_path") or tool_input.get("path")
                if not post_pi_file and pretool_ctx:
                    post_pi_file = pretool_ctx.get("file_path")

                post_pi_config = ptu_overlaid_configs.get(ScannerName.PROMPT_INJECTION)
                post_pi_result = run_prompt_injection_scan(
                    tool_output,
                    config=post_pi_config,
                    file_path=post_pi_file,
                    tool_name=tool_identifier,
                    latency_timer=_latency_timer,
                )

                if post_pi_result is not None:
                    post_pi_detected = post_pi_result.detected
                    post_pi_block = post_pi_result.should_block
                    post_pi_error_msg = post_pi_result.error_message

                    if post_pi_detected:
                        post_pi_hook_ctx = {
                            "hook_event": hook_event,
                            "tool_name": tool_name,
                        }
                        if hook_tool_use_id:
                            post_pi_hook_ctx["tool_use_id"] = hook_tool_use_id
                        if hook_session_id:
                            post_pi_hook_ctx["session_id"] = hook_session_id
                        _log_prompt_injection_violation(
                            post_pi_cp_filename,
                            context={
                                "ide_type": ide_type.value,
                                "hook_event": hook_event,
                                "file_path": post_pi_file,
                            },
                            attack_type=post_pi_result.attack_type,
                            hook_context=(
                                post_pi_hook_ctx if post_pi_hook_ctx else None
                            ),
                            matched_pattern=post_pi_result.matched_pattern,
                            matched_text=post_pi_result.matched_text,
                            confidence=post_pi_result.confidence,
                            line_number=post_pi_result.line_number,
                            start_column=post_pi_result.start_column,
                            end_column=post_pi_result.end_column,
                        )

                    if post_pi_block:
                        post_pi_action = post_pi_result.extra.get("action", "block")
                        post_pi_ask = _handle_ask_mode_auto(
                            post_pi_action,
                            ViolationType.PROMPT_INJECTION,
                            config_section="prompt_injection",
                            error_msg=post_pi_error_msg,
                            file_path=post_pi_file,
                            matched_text=post_pi_result.matched_text,
                            line_number=post_pi_result.line_number,
                            matched_pattern=post_pi_result.matched_pattern,
                            latency_timer=_latency_timer,
                            hook_context={
                                "session_id": hook_session_id,
                                "project_path": get_project_dir(),
                                "hook_event": hook_event,
                                "tool_name": tool_name,
                            },
                            findings=post_pi_result.findings,
                        )
                        if post_pi_ask is not None:
                            from ai_guardian.tui.ask_dialog import AskDecision

                            if post_pi_ask.decision not in (
                                AskDecision.BLOCK,
                                AskDecision.BLOCK_ALL,
                            ):
                                pi_info = _format_ask_info_message(
                                    ViolationType.PROMPT_INJECTION,
                                    post_pi_ask.decision,
                                )
                                post_warning_messages.append(pi_info)
                                post_warn_types.append(ViolationType.PROMPT_INJECTION)
                                post_pi_block = False
                                _log_ask_decision(
                                    ViolationType.PROMPT_INJECTION,
                                    post_pi_ask.decision,
                                    matched_text=post_pi_result.matched_text,
                                    error_msg=post_pi_error_msg or "",
                                    file_path=post_pi_file,
                                    line_number=post_pi_result.line_number,
                                    dialog_wait_ms=post_pi_ask.dialog_wait_ms,
                                )

                        if post_pi_block:
                            logger.info("PostToolUse: blocking due to prompt injection")
                            result = _format_response(
                                adapter,
                                has_secrets=True,
                                error_message=post_pi_error_msg,
                                hook_event=hook_event,
                                violation_type=ViolationType.PROMPT_INJECTION,
                            )
                            _advance_transcript_position(hook_data)
                            return result
                    elif post_pi_detected and post_pi_error_msg:
                        post_warning_messages.append(post_pi_error_msg)
                        post_warn_types.append(ViolationType.PROMPT_INJECTION)

                    if not post_pi_detected:
                        logger.info(
                            "PostToolUse: no prompt injection detected in output"
                        )
        except Exception as e:
            on_error = _loaders._get_on_scan_error_action()
            if on_error == ActionMode.BLOCK:
                logger.error(f"PostToolUse PI check error (fail-closed): {e}")
                result = _format_response(
                    adapter,
                    has_secrets=True,
                    hook_event=hook_event,
                    error_message=f"PostToolUse prompt injection check failed (blocked): {e}",
                    violation_type=ViolationType.PROMPT_INJECTION,
                )
                _advance_transcript_position(hook_data)
                return result
            logger.warning(f"PostToolUse PI check error (fail-open): {e}")

    # Context poisoning scanning on PostToolUse output (#1285)
    if tool_output:
        try:
            # Cross-hook optimization: skip if PreToolUse already scanned clean
            post_cp_skip = pretool_scan.get(
                "context_poisoning_scanned"
            ) and not pretool_scan.get("context_poisoning_found")
            if pretool_ctx and pretool_ctx.get("ignore_files_matched"):
                post_cp_skip = True

            if post_cp_skip:
                logger.info(
                    "PostToolUse: skipping CP scan (PreToolUse already scanned clean)"
                )
            else:
                post_cp_file = tool_input.get("file_path") or tool_input.get("path")
                if not post_cp_file and pretool_ctx:
                    post_cp_file = pretool_ctx.get("file_path")

                post_cp_result = run_context_poisoning_scan(
                    tool_output,
                    file_path=post_cp_file,
                    tool_identifier=tool_identifier,
                    latency_timer=_latency_timer,
                )

                if post_cp_result is not None:
                    post_cp_detected = post_cp_result.detected
                    post_cp_block = post_cp_result.should_block
                    post_cp_error_msg = post_cp_result.error_message

                    if post_cp_detected:
                        post_cp_hook_ctx = {
                            "hook_event": hook_event,
                            "tool_name": tool_name,
                        }
                        if hook_tool_use_id:
                            post_cp_hook_ctx["tool_use_id"] = hook_tool_use_id
                        if hook_session_id:
                            post_cp_hook_ctx["session_id"] = hook_session_id
                        _log_context_poisoning_violation(
                            post_pi_cp_filename,
                            context={
                                "ide_type": ide_type.value,
                                "hook_event": hook_event,
                                "file_path": post_cp_file,
                            },
                            hook_context=(
                                post_cp_hook_ctx if post_cp_hook_ctx else None
                            ),
                            matched_pattern=post_cp_result.matched_pattern,
                            matched_text=post_cp_result.matched_text,
                            confidence=post_cp_result.confidence,
                            line_number=post_cp_result.line_number,
                            start_column=post_cp_result.start_column,
                            end_column=post_cp_result.end_column,
                        )

                    if post_cp_block:
                        cp_action = post_cp_result.extra.get("action", "warn")
                        post_cp_ask = _handle_ask_mode_auto(
                            cp_action,
                            ViolationType.CONTEXT_POISONING,
                            config_section="context_poisoning",
                            error_msg=post_cp_error_msg,
                            file_path=post_cp_file,
                            matched_text=post_cp_result.matched_text,
                            line_number=post_cp_result.line_number,
                            matched_pattern=post_cp_result.matched_pattern,
                            latency_timer=_latency_timer,
                            hook_context={
                                "session_id": hook_session_id,
                                "project_path": get_project_dir(),
                                "hook_event": hook_event,
                                "tool_name": tool_name,
                            },
                        )
                        if post_cp_ask is not None:
                            from ai_guardian.tui.ask_dialog import AskDecision

                            if post_cp_ask.decision not in (
                                AskDecision.BLOCK,
                                AskDecision.BLOCK_ALL,
                            ):
                                cp_info = _format_ask_info_message(
                                    ViolationType.CONTEXT_POISONING,
                                    post_cp_ask.decision,
                                )
                                post_warning_messages.append(cp_info)
                                post_warn_types.append(ViolationType.CONTEXT_POISONING)
                                post_cp_block = False
                                _log_ask_decision(
                                    ViolationType.CONTEXT_POISONING,
                                    post_cp_ask.decision,
                                    matched_text=post_cp_result.matched_text,
                                    error_msg=post_cp_error_msg or "",
                                    file_path=post_cp_file,
                                    line_number=post_cp_result.line_number,
                                    dialog_wait_ms=post_cp_ask.dialog_wait_ms,
                                )

                        if post_cp_block:
                            logger.info(
                                "PostToolUse: blocking due to context poisoning"
                            )
                            result = _format_response(
                                adapter,
                                has_secrets=True,
                                error_message=post_cp_error_msg,
                                hook_event=hook_event,
                                violation_type=ViolationType.CONTEXT_POISONING,
                            )
                            _advance_transcript_position(hook_data)
                            return result
                    elif post_cp_detected and post_cp_error_msg:
                        post_warning_messages.append(post_cp_error_msg)
                        post_warn_types.append(ViolationType.CONTEXT_POISONING)
        except Exception as e:
            logger.warning(f"PostToolUse CP check error (fail-open): {e}")

    # Check for offensive language in PostToolUse output
    try:
        post_ol_result = run_offensive_language_scan(
            tool_output,
            file_path=post_cp_file if "post_cp_file" in dir() else None,
            tool_identifier=(tool_identifier if "tool_identifier" in dir() else None),
            latency_timer=_latency_timer,
        )
        if post_ol_result is not None and post_ol_result.detected:
            _log_offensive_language_violation(
                post_ol_result,
                hook_name=HookEvent.POST_TOOL_USE.display_name,
                hook_event=hook_event,
                hook_tool_use_id=hook_tool_use_id,
                hook_session_id=hook_session_id,
            )
            post_ol_action = post_ol_result.extra.get("action", "log")
            post_ol_should_block = post_ol_result.should_block
            post_ol_error_msg = post_ol_result.error_message
            post_ol_ask = _handle_ask_mode_auto(
                post_ol_action,
                ViolationType.OFFENSIVE_LANGUAGE,
                config_section="scan_offensive",
                error_msg=post_ol_error_msg,
                file_path=post_ol_result.file_path,
                matched_text=post_ol_result.matched_text,
                line_number=post_ol_result.line_number,
                matched_pattern=post_ol_result.matched_pattern,
                latency_timer=_latency_timer,
                hook_context={
                    "session_id": hook_session_id,
                    "project_path": get_project_dir(),
                    "hook_event": hook_event,
                },
            )
            if post_ol_ask is not None:
                from ai_guardian.tui.ask_dialog import AskDecision

                if post_ol_ask.decision not in (
                    AskDecision.BLOCK,
                    AskDecision.BLOCK_ALL,
                ):
                    post_ol_should_block = False
                    post_warning_messages.append(
                        _format_ask_info_message(
                            ViolationType.OFFENSIVE_LANGUAGE,
                            post_ol_ask.decision,
                        )
                    )
                    post_warn_types.append(ViolationType.OFFENSIVE_LANGUAGE)
                    _log_ask_decision(
                        ViolationType.OFFENSIVE_LANGUAGE,
                        post_ol_ask.decision,
                        matched_text=post_ol_result.matched_text,
                        error_msg=post_ol_error_msg or "",
                        file_path=post_ol_result.file_path,
                        line_number=post_ol_result.line_number,
                        dialog_wait_ms=post_ol_ask.dialog_wait_ms,
                    )
            if post_ol_should_block:
                logger.info("PostToolUse: blocking due to offensive language detection")
                result = _format_response(
                    adapter,
                    has_secrets=True,
                    error_message=post_ol_error_msg,
                    hook_event=hook_event,
                    violation_type=ViolationType.OFFENSIVE_LANGUAGE,
                )
                _advance_transcript_position(hook_data)
                return result
            elif post_ol_error_msg:
                post_warning_messages.append(post_ol_error_msg)
                post_warn_types.append(ViolationType.OFFENSIVE_LANGUAGE)
    except Exception as e:
        logger.warning(f"PostToolUse offensive language check error (fail-open): {e}")

    _advance_transcript_position(hook_data)
    if post_warning_messages:
        combined = "\n\n".join(post_warning_messages)
        _vtype = ",".join(str(t) for t in post_warn_types) if post_warn_types else None
        result = _format_response(
            adapter,
            has_secrets=False,
            hook_event=hook_event,
            warning_message=combined,
            violation_type=_vtype,
        )
        result["_warning"] = True
        result["_violation_type"] = _vtype or "mixed"
        return result
    return _format_response(adapter, has_secrets=False, hook_event=hook_event)
