"""Ask-mode dialog helpers extracted from hook_processing.py (Phase 5c, #1491)."""

import logging
import os
import time
from typing import Dict, Optional  # noqa: F401

from ai_guardian.constants import ViolationType, ActionMode, parse_ask_action
from ai_guardian.config.utils import get_project_dir

logger = logging.getLogger(__name__)

try:
    from ai_guardian.tools.policy import ToolPolicyChecker

    HAS_TOOL_POLICY = True
except ImportError:
    HAS_TOOL_POLICY = False

try:
    from ai_guardian.violations.logger import ViolationLogger

    HAS_VIOLATION_LOGGER = True
except ImportError:
    HAS_VIOLATION_LOGGER = False

from ai_guardian.scanners.transcript import (
    _finding_fingerprint,
    _extract_secret_type_from_error,
)


def _get_directory_action_from_config():
    """Return the directory_rules.action string from config (defaults to 'block')."""
    try:
        if HAS_TOOL_POLICY:
            policy_checker = ToolPolicyChecker()
            dr = policy_checker.config.get("directory_rules", {})
            if isinstance(dr, dict):
                return dr.get("action", ActionMode.BLOCK)
    except Exception:
        pass  # intentionally silent — best-effort operation
    return ActionMode.BLOCK


def _build_permission_matched_text(tool_name, tool_input, tool_identifier):
    """Build a display string for a permission violation's matched text.

    Returns "matcher:value" format for the pattern editor pre-fill.
    """
    if not tool_input:
        return tool_identifier or tool_name or ""
    if tool_name == "Skill":
        skill_name = tool_input.get("skill", "")
        if skill_name:
            return f"Skill:{skill_name}"
    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        if command:
            return f"Bash:{command[:200]}"
    elif tool_name in ("Read", "Write", "Edit"):
        fp = tool_input.get("file_path") or tool_input.get("path", "")
        if fp:
            return f"{tool_name}:{fp}"
    return tool_identifier or tool_name or ""


def _handle_ask_mode(
    action_str,
    violation_type,
    matched_text,
    config_section,
    error_msg,
    file_path=None,
    line_number=None,
    start_column=None,
    matched_pattern="",
    latency_timer=None,
    hook_context=None,
    finding_index=None,
    total_findings=None,
):
    """Handle 'ask' action mode by showing an interactive dialog.

    Returns an AskResult if action is 'ask', or None if action is not 'ask'.
    When the dialog is shown, also writes allowlist patterns if the user
    chooses "Allow Always".
    """
    primary_action, fallback_action = parse_ask_action(action_str)
    if primary_action != ActionMode.ASK:
        return None

    try:
        from ai_guardian.tui.ask_dialog import (
            show_ask_dialog,
            AskViolationInfo,
            AskDecision,
            format_hook_label,
        )

        import re as _re

        display_text = matched_text or ""
        display_line = line_number

        if error_msg and not matched_text:
            display_text = ""

        if not display_text and file_path and error_msg:
            try:
                loc_match = _re.search(r"Location:\s*[^:]+:(\d+)", error_msg)
                if loc_match:
                    display_line = int(loc_match.group(1))
            except (ValueError, AttributeError):
                pass  # intentionally silent — best-effort operation

        if not display_text and file_path and display_line:
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if i == display_line:
                            display_text = line.rstrip("\n\r")
                            break
            except (OSError, UnicodeDecodeError):
                pass  # intentionally silent — best-effort operation

        if not display_text:
            try:
                type_match = _re.search(r"Secret Type:\s*(.+)", error_msg or "")
                if type_match:
                    display_text = type_match.group(1).strip()
            except (AttributeError, IndexError):
                pass  # intentionally silent — best-effort operation

        summary_lines = []
        if error_msg:
            for prefix in ("Secret Type:", "Scanner:"):
                m = _re.search(rf"{prefix}\s*(.+)", error_msg)
                if m:
                    summary_lines.append(f"{prefix} {m.group(1).strip()}")
        summary = (
            " | ".join(summary_lines)
            if summary_lines
            else (error_msg[:200] if error_msg else str(violation_type))
        )

        hctx = hook_context or {}
        violation_info = AskViolationInfo(
            violation_type=violation_type,
            summary=summary,
            matched_text=display_text,
            config_section=config_section,
            error_message=error_msg or "",
            matched_pattern=matched_pattern,
            file_path=file_path,
            line_number=display_line,
            start_column=start_column,
            project_path=hctx.get("project_path") or get_project_dir(),
            session_id=hctx.get("session_id"),
            tool_name=hctx.get("tool_name"),
            hook_event=format_hook_label(hctx.get("hook_event"), hctx.get("tool_name")),
            finding_index=finding_index,
            total_findings=total_findings,
        )

        _dialog_t0 = time.perf_counter()
        result = show_ask_dialog(violation_info, fallback_action=fallback_action)
        _dialog_elapsed_ms = (time.perf_counter() - _dialog_t0) * 1000
        result.dialog_wait_ms = _dialog_elapsed_ms
        if latency_timer is not None:
            latency_timer.add_ask_wait(_dialog_elapsed_ms)

        if result.decision == AskDecision.ALLOW_ALWAYS and result.allowlist_pattern:
            if not getattr(result, "config_saved", False):
                from pathlib import Path as _Path
                from ai_guardian.config.writer import save_ask_pattern

                cp = (
                    _Path(result.config_path)
                    if getattr(result, "config_path", None)
                    else None
                )
                save_ask_pattern(
                    config_section, result.allowlist_pattern, config_path=cp
                )
            from ai_guardian.config.loaders import _clear_config_cache

            _clear_config_cache(project_key=hctx.get("project_path") or os.getcwd())

        if result.decision == AskDecision.IGNORE_FILE and result.ignore_path:
            if not getattr(result, "config_saved", False):
                from ai_guardian.tui.ask_dialog import _save_ignore_path

                _save_ignore_path(result.ignore_path, result.ignore_scanner_types)
            from ai_guardian.config.loaders import _clear_config_cache

            _clear_config_cache(project_key=hctx.get("project_path") or os.getcwd())

        return result

    except Exception as e:
        logger.warning(f"Ask dialog error, falling back to {fallback_action}: {e}")
        from ai_guardian.tui.ask_dialog import (
            AskResult,
            AskDecision,
            _map_fallback_to_decision,
        )

        return AskResult(decision=_map_fallback_to_decision(fallback_action))


def _handle_ask_mode_multi(
    action_str,
    violation_type,
    findings,
    config_section,
    error_msg,
    file_path=None,
    matched_pattern="",
    latency_timer=None,
    hook_context=None,
):
    """Handle 'ask' action mode for multiple findings.

    Loops through findings sequentially, calling _handle_ask_mode for each.
    BLOCK/BLOCK_ALL on any finding stops the loop immediately.
    Returns the final AskResult (BLOCK if any blocked, ALLOW_ONCE if all allowed).
    Also returns the per-finding results list as result.per_finding_results.
    """
    from ai_guardian.tui.ask_dialog import AskResult, AskDecision
    from ai_guardian.constants import parse_ask_action, ActionMode

    primary_action, _ = parse_ask_action(action_str)
    if primary_action != ActionMode.ASK:
        return None

    # Deduplicate findings by matched_text — the same secret value can appear
    # in both the user message scan and the transcript scan for UserPromptSubmit,
    # or be detected by multiple scanner engines, producing duplicate dialogs.
    if findings and len(findings) > 1:
        seen_values: set = set()
        deduped = []
        for f in findings:
            key = (f.get("matched_text") or "").strip()
            if key not in seen_values:
                seen_values.add(key)
                deduped.append(f)
        findings = deduped

    if not findings or len(findings) <= 1:
        single_finding = findings[0] if findings else {}
        return _handle_ask_mode(
            action_str,
            violation_type,
            matched_text=single_finding.get("matched_text", ""),
            config_section=config_section,
            error_msg=single_finding.get("error_message", error_msg),
            file_path=file_path,
            line_number=single_finding.get("line_number"),
            start_column=single_finding.get("start_column"),
            matched_pattern=single_finding.get("matched_pattern", matched_pattern),
            latency_timer=latency_timer,
            hook_context=hook_context,
        )

    per_finding_results = []
    total = len(findings)
    total_dialog_ms = 0.0

    for idx, finding in enumerate(findings):
        result = _handle_ask_mode(
            action_str,
            violation_type,
            matched_text=finding.get("matched_text", ""),
            config_section=config_section,
            error_msg=finding.get("error_message", error_msg),
            file_path=file_path,
            line_number=finding.get("line_number"),
            start_column=finding.get("start_column"),
            matched_pattern=finding.get("matched_pattern", matched_pattern),
            latency_timer=latency_timer,
            hook_context=hook_context,
            finding_index=idx,
            total_findings=total,
        )

        if result is None:
            return None

        per_finding_results.append(result)
        total_dialog_ms += result.dialog_wait_ms

        if result.decision in (AskDecision.BLOCK, AskDecision.BLOCK_ALL):
            aggregate = AskResult(decision=AskDecision.BLOCK)
            aggregate.dialog_wait_ms = total_dialog_ms
            aggregate.per_finding_results = per_finding_results
            return aggregate

        if result.decision == AskDecision.IGNORE_FILE:
            for skip_finding in findings[idx + 1 :]:
                skipped = AskResult(decision=AskDecision.IGNORE_FILE)
                skipped.dialog_wait_ms = 0.0
                per_finding_results.append(skipped)
            aggregate = AskResult(decision=AskDecision.ALLOW_ONCE)
            aggregate.dialog_wait_ms = total_dialog_ms
            aggregate.per_finding_results = per_finding_results
            return aggregate

    aggregate = AskResult(decision=AskDecision.ALLOW_ONCE)
    aggregate.dialog_wait_ms = total_dialog_ms
    aggregate.per_finding_results = per_finding_results
    return aggregate


def _handle_ask_mode_auto(
    action_str,
    violation_type,
    config_section,
    error_msg,
    file_path=None,
    matched_text=None,
    line_number=None,
    start_column=None,
    matched_pattern="",
    latency_timer=None,
    hook_context=None,
    findings=None,
):
    """Route to multi or single ask dialog based on findings count."""
    if findings and len(findings) > 1:
        return _handle_ask_mode_multi(
            action_str,
            violation_type,
            findings,
            config_section,
            error_msg,
            file_path=file_path,
            matched_pattern=matched_pattern,
            latency_timer=latency_timer,
            hook_context=hook_context,
        )
    if findings and len(findings) == 1:
        f = findings[0]
        return _handle_ask_mode(
            action_str,
            violation_type,
            matched_text=f.get("matched_text", ""),
            config_section=config_section,
            error_msg=f.get("error_message", error_msg),
            file_path=file_path,
            line_number=f.get("line_number"),
            start_column=f.get("start_column"),
            matched_pattern=f.get("matched_pattern", matched_pattern),
            latency_timer=latency_timer,
            hook_context=hook_context,
        )
    return _handle_ask_mode(
        action_str,
        violation_type,
        matched_text=matched_text or "",
        config_section=config_section,
        error_msg=error_msg,
        file_path=file_path,
        line_number=line_number,
        start_column=start_column,
        matched_pattern=matched_pattern,
        latency_timer=latency_timer,
        hook_context=hook_context,
    )


_ASK_VIOLATION_LABELS = {
    ViolationType.SECRET_DETECTED: "Secret detection",
    ViolationType.PII_DETECTED: "PII detection",
    ViolationType.TOOL_PERMISSION: "Permission rule",
    ViolationType.DIRECTORY_BLOCKING: "Directory access",
    ViolationType.PROMPT_INJECTION: "Prompt injection",
    ViolationType.CONTEXT_POISONING: "Context poisoning",
    ViolationType.SUPPLY_CHAIN: "Supply chain",
    ViolationType.CODE_SECURITY: "Code security",
    ViolationType.CONFIG_FILE_EXFIL: "Config file scanning",
    ViolationType.SSRF_BLOCKED: "SSRF protection",
    ViolationType.OFFENSIVE_LANGUAGE: "Offensive language",
    ViolationType.CANARY_DETECTED: "Canary token",
    ViolationType.EXFIL_DETECTION: "Exfil detection",
}


def _format_ask_info_message(violation_type, decision, detail=""):
    """Format an informational message for an ask-mode allow decision."""
    from ai_guardian.tui.ask_dialog import AskDecision

    label = _ASK_VIOLATION_LABELS.get(violation_type, str(violation_type))
    if decision == AskDecision.ALLOW_ALWAYS:
        msg = f"ℹ️  {label}: pattern added to allowlist (always allowed)"
    elif decision == AskDecision.SUPPRESS_IN_SOURCE:
        msg = f"ℹ️  {label}: suppressed in source (annotation added)"
    elif decision == AskDecision.IGNORE_FILE:
        msg = f"ℹ️  {label}: file added to .aiguardignore.toml"
    else:
        msg = f"ℹ️  {label}: allowed by user (this time only)"
    if detail:
        msg += f": {detail}"
    return msg


def _log_ask_decision(
    violation_type,
    decision,
    matched_text="",
    error_msg="",
    file_path=None,
    line_number=None,
    dialog_wait_ms=0.0,
    daemon_state=None,
    session_id=None,
    finding_fingerprints=None,
    invocation_allowed_findings=None,
):
    """Log an ask-mode decision (allow or block) to violations.jsonl.

    When an allow decision is made and invocation_allowed_findings is provided,
    records finding fingerprints in that set for transcript scanner dedup within
    the current hook invocation only (#1364, #1439).
    """
    if not HAS_VIOLATION_LOGGER:
        return
    try:
        from ai_guardian.tui.ask_dialog import AskDecision

        from ai_guardian.violations.redact import (
            REDACT_VIOLATION_TYPES,
            redact_secret_hint,
        )

        vlogger = ViolationLogger()

        vtype_str = (
            violation_type.value
            if hasattr(violation_type, "value")
            else str(violation_type)
        )
        if vtype_str in REDACT_VIOLATION_TYPES:
            persisted_text = redact_secret_hint(matched_text) if matched_text else ""
        else:
            persisted_text = matched_text or ""

        blocked_info = {
            "description": (error_msg[:200] if error_msg else str(violation_type)),
        }
        if vtype_str in REDACT_VIOLATION_TYPES:
            if persisted_text and persisted_text != "[redacted]":
                blocked_info["pattern_hint"] = persisted_text
        else:
            blocked_info["matched_text"] = persisted_text
        if file_path:
            blocked_info["file_path"] = file_path
        if line_number:
            blocked_info["line_number"] = line_number
        _DECISION_MAP = {
            AskDecision.BLOCK: ("block", "blocked"),
            AskDecision.BLOCK_ALL: ("block_all", "blocked"),
            AskDecision.ALLOW_ALWAYS: ("allow_always", "allowed"),
            AskDecision.SUPPRESS_IN_SOURCE: ("suppress_in_source", "allowed"),
            AskDecision.IGNORE_FILE: ("ignore_file", "allowed"),
        }
        decision_str, action_taken = _DECISION_MAP.get(
            decision, ("allow_once", "allowed")
        )
        ctx = {"ask_decision": decision_str, "action_taken": action_taken}
        if dialog_wait_ms > 0:
            ctx["dialog_wait_ms"] = round(dialog_wait_ms, 1)
        vlogger.log_violation(
            violation_type=violation_type,
            blocked=blocked_info,
            context=ctx,
            severity="info",
        )

        # Record allowed findings for transcript scanner dedup within this invocation (#1364, #1439).
        # Uses invocation_allowed_findings (local set) so Allow Once does not persist to next invocation.
        if action_taken == "allowed" and invocation_allowed_findings is not None:
            _record_allowed_for_transcript(
                invocation_allowed_findings,
                violation_type,
                error_msg,
                matched_text,
                finding_fingerprints,
            )
    except Exception as e:
        logger.error(f"Failed to log ask decision: {e}")


def _record_allowed_for_transcript(
    result_set,
    violation_type,
    error_msg,
    matched_text,
    finding_fingerprints=None,
):
    """Record allowed finding fingerprints into result_set for transcript dedup.

    Uses pre-computed fingerprints if provided, otherwise auto-computes
    from violation_type and error_msg/matched_text.
    result_set is a plain set() scoped to the current hook invocation (#1439).
    """
    try:
        if finding_fingerprints:
            for fp in finding_fingerprints:
                result_set.add(fp)
            return

        if violation_type in (
            ViolationType.SECRET_DETECTED,
            ViolationType.SECRET_IN_TRANSCRIPT,
        ):
            rule_id = _extract_secret_type_from_error(error_msg)
            if rule_id and rule_id != "unknown":
                fp = _finding_fingerprint("secret", rule_id)
                result_set.add(fp)
    except Exception as e:
        logger.debug(f"Failed to record allowed finding: {e}")


def _compute_pii_transcript_fingerprints(pii_redactions, content):
    """Compute transcript-compatible fingerprints from PII redactions.

    Mirrors the fingerprint logic in _scan_transcript_text() so the
    transcript scanner recognizes allowed PII findings.
    """
    fps = []
    for r in pii_redactions or []:
        pos = r.get("position", 0)
        length = r.get("original_length", 0)
        original_value = (
            content[pos : pos + length] if length and content else r.get("type", "")
        )
        fp = _finding_fingerprint("pii", f"{r['type']}:{original_value}")
        fps.append(fp)
    return fps
