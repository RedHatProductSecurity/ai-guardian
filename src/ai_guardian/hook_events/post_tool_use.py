"""PostToolUse event handler extracted from hook_processing.py (Phase 5e.2, #1491)."""

import logging
from dataclasses import replace
from typing import Any, Dict, Optional

import ai_guardian.config.loaders as _loaders
from ai_guardian.config.utils import get_project_dir, is_feature_enabled
from ai_guardian.constants import ActionMode, ViolationType, HookEvent
from ai_guardian.developer_session import (
    non_blocking_finding_advisory_message,
    should_downgrade_blocking_finding,
)
from ai_guardian.ide_registry import get_ide_integration_for_agent_type
from ai_guardian.hook_events.utils import (
    _format_response,  # noqa: F401
    _extract_pii_matched_text,
    _pii_redactions_to_findings,
    _extract_file_path_from_pii_warning,
)
from ai_guardian.scanners.scan_result import ScanResult, generate_violation_id
from ai_guardian.violations.log_violation import ScanContext, log_violation
from ai_guardian.violations.command_context import MAX_ORIGIN_COMMAND_LEN
from ai_guardian.scanners.transcript import _advance_transcript_position
from ai_guardian.violations.decision import PolicyDecision

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
from ai_guardian.scanners.post_scan_filters import (
    PostScanContext,
    apply_post_scan_pipeline,
)
from ai_guardian.annotations import apply_suppressions, read_annotation_source

logger = logging.getLogger(__name__)


def _scan_decoded_post_tool_content(
    content,
    scanner_name,
    *,
    scanner_config=None,
    file_path=None,
    tool_identifier=None,
    latency_timer=None,
    scanner_kwargs=None,
):
    """Scan only decoded Base64 candidates for one PostToolUse scanner."""
    from ai_guardian.scanners.pipeline import scan_content

    entry = get_default_registry().get(scanner_name)
    config = (
        {entry.config_section: scanner_config}
        if entry and entry.config_section and scanner_config is not None
        else None
    )
    return scan_content(
        content,
        config=config,
        filename=f"{tool_identifier}_output" if tool_identifier else "tool_output",
        source_type="file_content",
        file_path=file_path,
        tool_name=tool_identifier,
        tool_identifier=tool_identifier,
        hook_event=HookEvent.POST_TOOL_USE,
        latency_timer=latency_timer,
        scanner_kwargs=scanner_kwargs,
        scanner_names={scanner_name},
        decoded_only=True,
    )


def _redact_encoded_source_spans(content, scan_results, existing_result=None):
    """Redact decoded candidates plus any existing PII spans in source content."""
    replacement_spans = []
    existing_redacted = None
    if existing_result is not None:
        if existing_result.extra.get("scan_error") or not existing_result.redactions:
            return None
        existing_redacted = existing_result.redacted_content
        if not isinstance(existing_redacted, str):
            return None

        existing_redactions = sorted(
            existing_result.redactions or [], key=lambda item: item.get("position", -1)
        )
        source_cursor = 0
        redacted_cursor = 0
        for redaction in existing_redactions:
            start = redaction.get("position")
            original_length = redaction.get("original_length")
            redacted_length = redaction.get("redacted_length")
            if (
                type(start) is not int
                or type(original_length) is not int
                or type(redacted_length) is not int
                or start < source_cursor
                or original_length <= 0
                or redacted_length < 0
                or start + original_length > len(content)
            ):
                return None
            unchanged_length = start - source_cursor
            replacement_start = redacted_cursor + unchanged_length
            replacement_end = replacement_start + redacted_length
            if replacement_end > len(existing_redacted):
                return None
            replacement_spans.append(
                (
                    start,
                    start + original_length,
                    existing_redacted[replacement_start:replacement_end],
                    "pii",
                )
            )
            source_cursor = start + original_length
            redacted_cursor = replacement_end

        expected_parts: list[str] = []
        expected_source_cursor = 0
        for start, end, replacement, _kind in replacement_spans:
            expected_parts.extend((content[expected_source_cursor:start], replacement))
            expected_source_cursor = end
        expected_parts.append(content[expected_source_cursor:])
        if "".join(expected_parts) != existing_redacted:
            return None

    for scan_result in scan_results:
        extra = scan_result.extra if isinstance(scan_result.extra, dict) else {}
        candidate_start = extra.get("base64_source_start")
        candidate_end = extra.get("base64_source_end")
        if type(candidate_start) is not int or type(candidate_end) is not int:
            return None
        if (
            candidate_start < 0
            or candidate_end <= candidate_start
            or candidate_end > len(content)
        ):
            return None
        replacement_spans.append(
            (candidate_start, candidate_end, "***REDACTED***", "base64")
        )

    if not replacement_spans:
        return None

    base64_spans = [span for span in replacement_spans if span[3] == "base64"]
    pii_spans = [span for span in replacement_spans if span[3] == "pii"]
    kept_pii_spans = []
    for pii_span in pii_spans:
        pii_start, pii_end, _, _ = pii_span
        contained_by_encoded_span = False
        for base64_start, base64_end, _, _ in base64_spans:
            if pii_start < base64_end and base64_start < pii_end:
                if base64_start <= pii_start and pii_end <= base64_end:
                    contained_by_encoded_span = True
                    break
                return None
        if not contained_by_encoded_span:
            kept_pii_spans.append(pii_span)

    replacement_spans = kept_pii_spans + base64_spans

    replacement_spans.sort(key=lambda span: (span[0], span[1]))
    parts: list[str] = []
    source_cursor = 0
    for start, end, replacement, _kind in replacement_spans:
        if start < source_cursor:
            return None
        parts.extend((content[source_cursor:start], replacement))
        source_cursor = end
    parts.append(content[source_cursor:])
    return "".join(parts)


def _agent_type_value(adapter, ide_type):
    """Return stable agent attribution without changing response semantics."""
    value = getattr(adapter, "agent_type", None)
    if isinstance(value, str) and value:
        return value
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str) and enum_value:
        return enum_value
    ide_value = getattr(ide_type, "value", None)
    if isinstance(ide_value, str) and ide_value:
        return ide_value
    return str(ide_type or "unknown")


_MAX_REDACTED_CONTEXT_BYTES = 102400
_MAX_SOURCE_COMMAND_LEN = MAX_ORIGIN_COMMAND_LEN


def _non_blocking_policy_decision(result, action, enabled, scan_context, source):
    """Record the effective allow decision without hiding the scanner finding."""
    if not result.should_block or not should_downgrade_blocking_finding(
        enabled=enabled,
        action=action,
        detected=result.detected,
        scan_error=result.extra.get("scan_error"),
    ):
        return None
    return PolicyDecision.from_scan_result(
        result,
        scan_context.to_dict(),
        source=source,
        decision_override="allow",
    )


def _log_post_tool_sensitive_outcome(
    scan_result,
    scan_context: ScanContext,
    violation_logger,
    action_taken: str,
    redaction_status: str,
) -> None:
    """Persist a PostToolUse sensitive finding after its effective action is known."""
    if scan_result is None or not scan_result.detected:
        return
    if getattr(scan_result.violation_type, "value", scan_result.violation_type) == (
        ViolationType.SECRET_DETECTED
    ):
        # The legacy secret scanner audit path recorded secrets as critical even
        # though its generic ScanResult wrapper defaults to high severity.
        scan_result = replace(scan_result, severity="critical")
    log_violation(
        scan_result,
        scan_context,
        violation_logger=violation_logger,
        source="tool_output",
        action_taken=action_taken,
        redaction_status=redaction_status,
    )


def _sanitize_non_blocking_secret_output(
    content: str,
    scan_result: ScanResult,
    redaction_config: Optional[Dict],
    latency_timer,
):
    """Return sanitized output and detected values, or None if safe redaction fails.

    A trusted-session override must not send detected credentials to the model.
    Run the normal redactor even when its user-facing feature is disabled, then
    use exact scanner matches as a fallback for formats the redactor does not know.
    """
    if not isinstance(content, str) or not content:
        return None

    sanitizer_config = (
        dict(redaction_config) if isinstance(redaction_config, dict) else {}
    )
    sanitizer_config["enabled"] = True
    pii_config, _ = _loaders._load_pii_config()
    pii_config = (
        pii_config
        if isinstance(pii_config, dict) and pii_config.get("enabled", True)
        else None
    )

    from ai_guardian.scanners.secret_redactor import SecretRedactor

    redactor = SecretRedactor(sanitizer_config, pii_config=pii_config)
    with latency_timer.check("secret_redaction"):
        redaction_result = redactor.redact(content)

    redacted_text = redaction_result.get("redacted_text")
    if not isinstance(redacted_text, str):
        return None

    detected_values = []
    candidates = [scan_result.matched_text]
    for finding in scan_result.findings or []:
        if isinstance(finding, dict):
            candidate = finding.get("matched_text")
            if isinstance(candidate, str):
                candidates.append(candidate)
    for candidate in candidates:
        if len(candidate) >= 4 and candidate not in detected_values:
            detected_values.append(candidate)

    # SecretRedactor handles normal formats and preserves established masking
    # strategies. Exact findings from another engine still need full masking.
    for detected_value in detected_values:
        if detected_value in redacted_text:
            redacted_text = redacted_text.replace(detected_value, "[REDACTED]")

    if redacted_text == content or not detected_values:
        return None
    if any(value in redacted_text for value in detected_values):
        return None

    return redacted_text, detected_values


def _pii_redaction_verified(content: str, redacted_text: Any, redactions: list) -> bool:
    """Confirm every PII value identified by spans is absent from replacement."""
    if not isinstance(redacted_text, str) or redacted_text == content:
        return False

    detected_values = []
    for redaction in redactions:
        if not isinstance(redaction, dict):
            continue
        position = redaction.get("position", -1)
        length = redaction.get("original_length", 0)
        if (
            isinstance(position, int)
            and isinstance(length, int)
            and position >= 0
            and length > 0
            and position + length <= len(content)
        ):
            detected_values.append(content[position : position + length])

    return bool(detected_values) and all(
        value not in redacted_text for value in detected_values
    )


def _supports_safe_post_output_replacement(agent_type: str, tool_name: str) -> bool:
    """Return whether this host/tool pair can replace model-visible output safely."""
    integration = get_ide_integration_for_agent_type(agent_type)
    if integration is None or not integration.safe_post_output_replacement:
        return False

    normalized_tool = (tool_name or "").casefold()
    if integration.key == "claude" and normalized_tool == "bash":
        # Claude Code currently ignores updatedToolOutput for Bash results.
        return False
    if integration.key == "cursor" and not normalized_tool.startswith("mcp__"):
        # Cursor documents replacement only for local MCP tool results.
        return False

    return True


# Deferred-import wrappers for functions defined in hook_processing.py.
# Module-level imports would create a circular dependency.
def extract_tool_result(hook_data):
    from ai_guardian.hook_processing import extract_tool_result as _etr

    return _etr(hook_data)


def _extract_context_snippet(text, line_number):
    from ai_guardian.hook_processing import _extract_context_snippet as _ecs

    return _ecs(text, line_number)


def _sanitize_source_command(command: str) -> Optional[str]:
    """Sanitize a Bash command before making it available to violation logging."""
    from ai_guardian.violations.command_context import sanitize_origin_command

    return sanitize_origin_command(command)


def _redaction_coordinates(redaction: dict, content: str) -> dict:
    """Keep original-response coordinates, with zero-based, exclusive-end columns."""
    coordinates = {"line_number": redaction.get("line_number")}
    start = redaction.get("position")
    length = redaction.get("original_length")
    if (
        type(start) is int
        and type(length) is int
        and start >= 0
        and length > 0
        and start + length <= len(content)
    ):
        end = start + length
        coordinates.update(
            line_number=content.count("\n", 0, start) + 1,
            start_column=start - (content.rfind("\n", 0, start) + 1),
            end_line=content.count("\n", 0, end) + 1,
            end_column=end - (content.rfind("\n", 0, end) + 1),
        )
    return coordinates


# ---------------------------------------------------------------------------
# Conditional imports
# ---------------------------------------------------------------------------

try:
    from ai_guardian.violations.logger import ViolationLogger as _ViolationLogger

    ViolationLogger: Any = _ViolationLogger
    HAS_VIOLATION_LOGGER = True
except ImportError:
    ViolationLogger = None
    HAS_VIOLATION_LOGGER = False


try:
    from ai_guardian.annotations import process_annotations_by_scanner

    HAS_ANNOTATIONS = True
except ImportError:
    HAS_ANNOTATIONS = False


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
        non_blocking_findings_enabled = (
            getattr(ctx, "non_blocking_findings_enabled", False) is True
        )
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
        non_blocking_findings_enabled = (
            kwargs.get("non_blocking_findings_enabled", False) is True
        )
        now = kwargs["now"]

    agent_type = _agent_type_value(adapter, ide_type)

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

    # Reuse the shared normalized input so native aliases such as OpenCode's
    # filePath reach post-tool scanners as the canonical file_path.
    normalized = getattr(ctx, "normalized", None) if ctx is not None else None
    if normalized is None:
        normalized = adapter.normalize_input(hook_data)
    tool_input = normalized.tool_input or {}

    if tool_name == "Skill" and tool_input.get("skill"):
        tool_identifier = f"Skill:{tool_input['skill']}"
        logger.info(
            f"PostToolUse (with output): Created composite identifier {tool_identifier}"
        )

    logger.info(f"PostToolUse tool_identifier: {tool_identifier}")

    # Extract command for Bash tool (for violation context)
    source_command = None
    if tool_name == "Bash":
        raw_cmd = tool_input.get("command", "")
        if raw_cmd:
            source_command = _sanitize_source_command(raw_cmd)

    _scan_ctx = ScanContext(
        ide_type=agent_type,
        hook_event=hook_event,
        project_path=get_project_dir(),
        session_id=hook_session_id,
        tool_use_id=hook_tool_use_id,
        tool_name=tool_name,
        origin_command=source_command,
    )

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

    # Resolve remote locators separately from local files and scan labels.
    from ai_guardian.violations.command_context import sanitize_source_url

    current_tool = str(normalized.tool_name or tool_name).casefold()
    is_url_output = current_tool == "webfetch"
    cached_url = None
    if pretool_ctx and str(pretool_ctx.get("tool_name", "")).casefold() == "webfetch":
        cached_url = pretool_ctx.get("source_url")
        if current_tool == "unknown":
            is_url_output = True
    source_url = (
        sanitize_source_url(
            tool_input.get("url") if "url" in tool_input else cached_url
        )
        if is_url_output
        else None
    )
    if is_url_output:
        _scan_ctx.source_url = source_url
        _scan_ctx.source_context = "tool_output"

    logger.info(f"Scanning {tool_identifier} output for secrets...")

    # Apply annotation suppression for file-reading tools (Issue #481)
    # If PreToolUse was a file read, preserve per-scanner annotation scope.
    post_annotation_contents: Dict[str, str] = {}
    post_suppressed_lines: Dict[str, set[int]] = {}
    original_tool_output = tool_output
    if (
        HAS_ANNOTATIONS
        and not is_url_output
        and pretool_ctx
        and pretool_ctx.get("file_path")
        and tool_output
    ):
        post_annotations_config, _ = _loaders._load_annotations_config()
        if post_annotations_config and is_feature_enabled(
            post_annotations_config.get("enabled"), now, default=True
        ):
            post_annotation_contents, post_ann_info, _ = process_annotations_by_scanner(
                tool_output,
                (
                    "password_likelihood",
                    "secret_scanning",
                    "scan_pii",
                    "prompt_injection",
                    "context_poisoning",
                    "offensive_language",
                ),
                file_path=pretool_ctx.get("file_path"),
                config=post_annotations_config,
                source_content=read_annotation_source(pretool_ctx.get("file_path")),
            )
            if post_ann_info:
                original_lines = original_tool_output.splitlines()
                for scanner_type, filtered_content in post_annotation_contents.items():
                    filtered_lines = filtered_content.splitlines()
                    post_suppressed_lines[scanner_type] = {
                        index
                        for index, original_line in enumerate(original_lines)
                        if index < len(filtered_lines)
                        and original_line != filtered_lines[index]
                        and not filtered_lines[index].strip()
                    }
                total_suppressed = sum(len(s.get("lines", [])) for s in post_ann_info)
                logger.info(
                    f"PostToolUse: annotation suppression applied "
                    f"({total_suppressed} line(s) suppressed)"
                )

    def _post_content_for(scanner_type: str) -> str:
        return post_annotation_contents.get(scanner_type, original_tool_output)

    post_secret_content = _post_content_for("secret_scanning")
    post_pii_content = _post_content_for("scan_pii")
    post_secret_suppressed = post_suppressed_lines.get("secret_scanning", set())
    post_pii_suppressed = post_suppressed_lines.get("scan_pii", set())
    post_sensitive_suppressed = post_secret_suppressed | post_pii_suppressed
    post_sensitive_content = apply_suppressions(
        original_tool_output, post_sensitive_suppressed, preserve_offsets=True
    )

    # File annotations also apply to password-likelihood findings. User prompts
    # and non-file tool outputs have no annotation overrides.
    from ai_guardian.scanners.password_likelihood import run_password_likelihood_scan

    heuristic_notice = None
    password_result = run_password_likelihood_scan(
        _post_content_for("password_likelihood")
    )
    if password_result is not None:
        password_decision = apply_post_scan_pipeline(
            get_default_registry().get(ScannerName.PASSWORD_LIKELIHOOD),
            password_result,
            PostScanContext(
                handle_ask_mode_auto=_handle_ask_mode_auto,
                log_ask_decision=_log_ask_decision,
                format_ask_info_message=_format_ask_info_message,
                hook_event=hook_event,
                hook_session_id=hook_session_id,
                hook_tool_use_id=hook_tool_use_id,
                tool_name=tool_name,
                origin_command=source_command,
                ide_type_value=agent_type,
                violation_logger=violation_logger,
                latency_timer=_latency_timer,
                invocation_allowed_findings=_invocation_allowed,
                non_blocking_findings_enabled=non_blocking_findings_enabled,
            ),
        )
        if password_decision.should_block:
            _advance_transcript_position(hook_data)
            return _format_response(
                adapter,
                has_secrets=True,
                hook_event=hook_event,
                error_message=password_result.error_message,
                violation_type=ViolationType.HEURISTIC_CANDIDATE,
            )
        heuristic_notice = "\n\n".join(password_decision.warnings) or None

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
        return _format_response(
            adapter,
            has_secrets=False,
            hook_event=hook_event,
            warning_message=heuristic_notice,
            violation_type=(
                ViolationType.HEURISTIC_CANDIDATE if heuristic_notice else None
            ),
        )

    ignore_files = secret_config.get("ignore_files", []) if secret_config else []
    ignore_tools = secret_config.get("ignore_tools", []) if secret_config else []
    secret_allowlist = (
        secret_config.get("allowlist_patterns", []) if secret_config else []
    )

    # Cross-hook optimization (#366): a clean URL input says nothing about its response.
    pretool_scan = (
        pretool_ctx.get("scan_results", {}) if pretool_ctx and not is_url_output else {}
    )
    skip_secret_scan = pretool_scan.get("secrets_scanned") and not pretool_scan.get(
        "secrets_found"
    )
    if skip_secret_scan:
        logger.info(
            "PostToolUse: skipping secret scan (PreToolUse already scanned clean)"
        )

    # Cross-hook optimization: respect ignore_files from PreToolUse (#366)
    if not is_url_output and pretool_ctx and pretool_ctx.get("ignore_files_matched"):
        logger.info(
            "PostToolUse: skipping scans (file matched ignore_files in PreToolUse)"
        )
        skip_secret_scan = True

    post_secret_ctx = {
        "ide_type": agent_type,
        "hook_event": HookEvent.POST_TOOL_USE,
        "tool_name": tool_identifier,
        "source": "scanner",
        "source_context": "tool_output",
    }
    file_path_for_ctx = tool_input.get("file_path") or tool_input.get("path")
    if not file_path_for_ctx and pretool_ctx:
        file_path_for_ctx = pretool_ctx.get("file_path")
    if is_url_output:
        file_path_for_ctx = None
        if source_url:
            post_secret_ctx["source_url"] = source_url
    if file_path_for_ctx:
        post_secret_ctx["file_path"] = file_path_for_ctx
    if hook_tool_use_id:
        post_secret_ctx["tool_use_id"] = hook_tool_use_id
    if hook_session_id:
        post_secret_ctx["session_id"] = hook_session_id
    if source_command:
        post_secret_ctx["source_command"] = source_command
    # PostToolUse output is the source file for read tools.  Bash and edit
    # tools may return a summary or fragment whose line numbers do not map to
    # the source file, so do not create an unverifiable source locator for it.
    source_content = (
        original_tool_output if tool_name in ("Read", "read_file", "ReadFile") else None
    )
    post_secret_ctx["_allowlist_content"] = source_content
    post_secret_ctx["_allowlist_file_path"] = file_path_for_ctx
    _scan_ctx.allowlist_content = source_content
    _scan_ctx.allowlist_file_path = file_path_for_ctx

    if skip_secret_scan:
        has_secrets = False
        error_message = None
    else:
        post_scan_content = (
            post_secret_content if post_secret_content is not None else tool_output
        )
        post_secret_result = run_secret_scan(
            post_scan_content,
            filename=f"{tool_identifier}_output",
            config=secret_config,
            secret_context=post_secret_ctx,
            file_path=file_path_for_ctx,
            tool_name=tool_identifier,
            ignore_files=ignore_files,
            ignore_tools=ignore_tools,
            allowlist_patterns=secret_allowlist,
            latency_timer=_latency_timer,
            defer_violation_logging=True,
        )
        decoded_secret_results = _scan_decoded_post_tool_content(
            post_scan_content,
            ScannerName.SECRET,
            scanner_config=secret_config,
            file_path=file_path_for_ctx,
            tool_identifier=tool_identifier,
            latency_timer=_latency_timer,
            scanner_kwargs={
                ScannerName.SECRET: {
                    "secret_context": post_secret_ctx,
                    "ignore_files": ignore_files,
                    "ignore_tools": ignore_tools,
                    "allowlist_patterns": secret_allowlist,
                    "defer_violation_logging": True,
                }
            },
        )
        decoded_secret_result = next(
            (
                scan_result
                for scan_result in decoded_secret_results
                if scan_result.detected
            ),
            None,
        )
        if decoded_secret_result is not None:
            logger.warning("Secret detected in decoded Base64 tool output; blocking")
            _log_post_tool_sensitive_outcome(
                decoded_secret_result,
                _scan_ctx,
                violation_logger,
                "block",
                "not_redacted",
            )
            result = _format_response(
                adapter,
                has_secrets=True,
                error_message=decoded_secret_result.error_message,
                hook_event=hook_event,
                violation_type=ViolationType.SECRET_DETECTED,
            )
            _advance_transcript_position(hook_data)
            return result

        has_secrets = post_secret_result.detected if post_secret_result else False
        error_message = post_secret_result.error_message if post_secret_result else None

    if not has_secrets and error_message:
        # Scanner not available - display warning but allow operation
        _advance_transcript_position(hook_data)
        return _format_response(
            adapter,
            has_secrets=False,
            hook_event=hook_event,
            warning_message="\n\n".join(
                filter(None, (heuristic_notice, error_message))
            ),
            violation_type=ViolationType.SECRET_DETECTED,
        )

    if has_secrets:
        # Check if redaction is enabled
        redaction_config, redaction_error = _loaders._load_secret_redaction_config()

        if redaction_error:
            logger.warning(f"Config error loading secret_redaction: {redaction_error}")
            # Fall back to blocking
            logger.warning(f"Secrets detected in {tool_identifier} output - blocking")
            _log_post_tool_sensitive_outcome(
                post_secret_result, _scan_ctx, violation_logger, "block", "not_redacted"
            )
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
                    result = redactor.redact(post_sensitive_content)

                redacted_text = result["redacted_text"]
                redactions = result["redactions"]

                if not redactions:
                    logger.warning(
                        "Secret detected but redactor produced 0 redactions "
                        f"for {tool_identifier} output — falling back to block"
                    )
                    _log_post_tool_sensitive_outcome(
                        post_secret_result,
                        _scan_ctx,
                        violation_logger,
                        "block",
                        "not_redacted",
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
                if post_sensitive_suppressed:
                    redacted_lines = redacted_text.splitlines()
                    original_lines = original_tool_output.splitlines()
                    for idx in post_sensitive_suppressed:
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
                coordinates = _redaction_coordinates(redactions[0], tool_output)
                first_line = coordinates.get("line_number")
                blocked_info = {
                    "tool": tool_identifier,
                    "file_path": file_path_for_ctx,
                    **coordinates,
                    "redaction_count": len(redactions),
                    "redacted_types": [r["type"] for r in redactions],
                }
                if is_url_output:
                    blocked_info["source_context"] = "tool_output"
                    if source_url:
                        blocked_info["source_url"] = source_url
                if source_command:
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
                    vid = generate_violation_id()
                    blocked_info["violation_id"] = vid
                    violation_logger.log_violation(
                        violation_type=ViolationType.SECRET_REDACTION,
                        blocked=blocked_info,
                        context=ctx,
                        violation_id=vid,
                        policy_decision=PolicyDecision(
                            event=HookEvent.POST_TOOL_USE,
                            decision="allow",
                            reason="secret_redaction",
                            severity="critical",
                            source="redaction",
                            agent=agent_type,
                            repository=_scan_ctx.project_path,
                            correlation_id=hook_tool_use_id,
                            violation_id=vid,
                            violation_type=ViolationType.SECRET_REDACTION,
                        ),
                        action_taken="allow",
                        redaction_status="redacted",
                    )

                _log_post_tool_sensitive_outcome(
                    post_secret_result,
                    _scan_ctx,
                    violation_logger,
                    "allow",
                    "redacted",
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

                if heuristic_notice:
                    warning_msg = "\n\n".join(
                        filter(None, (heuristic_notice, warning_msg))
                    )

                if len(redacted_text) > _MAX_REDACTED_CONTEXT_BYTES:
                    orig_len = len(redacted_text)
                    redacted_text = (
                        redacted_text[:_MAX_REDACTED_CONTEXT_BYTES]
                        + f"\n\n[Truncated: original output was {orig_len} bytes]"
                    )
                logger.info(
                    "Secrets redacted — sending redacted content "
                    "via updatedToolOutput"
                )
                result = _format_response(
                    adapter,
                    has_secrets=False,
                    hook_event=hook_event,
                    warning_message=warning_msg,
                    modified_output=redacted_text,
                    violation_type=ViolationType.SECRET_REDACTION,
                    tool_name=tool_name,
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
                _log_post_tool_sensitive_outcome(
                    post_secret_result,
                    _scan_ctx,
                    violation_logger,
                    "block",
                    "not_redacted",
                )
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
            if should_downgrade_blocking_finding(
                enabled=non_blocking_findings_enabled,
                action="block",
                detected=has_secrets,
                scan_error=(
                    post_secret_result.extra.get("scan_error")
                    if post_secret_result
                    else None
                ),
            ) and _supports_safe_post_output_replacement(agent_type, tool_name):
                try:
                    sanitized = _sanitize_non_blocking_secret_output(
                        post_sensitive_content,
                        post_secret_result,
                        redaction_config,
                        _latency_timer,
                    )
                except Exception:
                    sanitized = None
                    logger.warning(
                        "Failed to sanitize a trusted-session secret finding; "
                        "retaining the block"
                    )

                if sanitized is not None:
                    redacted_text, detected_values = sanitized
                    if post_sensitive_suppressed:
                        redacted_lines = redacted_text.splitlines()
                        original_lines = original_tool_output.splitlines()
                        for index in post_sensitive_suppressed:
                            if index < len(redacted_lines) and index < len(
                                original_lines
                            ):
                                redacted_lines[index] = original_lines[index]
                        redacted_text = "\n".join(redacted_lines)
                    if len(redacted_text) > _MAX_REDACTED_CONTEXT_BYTES:
                        original_length = len(redacted_text)
                        redacted_text = (
                            redacted_text[:_MAX_REDACTED_CONTEXT_BYTES]
                            + f"\n\n[Truncated: original output was {original_length} bytes]"
                        )

                    # Keep the established scanner diagnostic visible; scrub
                    # exact matches defensively if a scanner ever includes one.
                    warning_message = error_message or "Secrets detected in tool output"
                    for detected_value in detected_values:
                        warning_message = warning_message.replace(
                            detected_value, "[REDACTED]"
                        )
                    _log_post_tool_sensitive_outcome(
                        post_secret_result,
                        _scan_ctx,
                        violation_logger,
                        "allow",
                        "redacted",
                    )
                    result = _format_response(
                        adapter,
                        has_secrets=False,
                        hook_event=hook_event,
                        warning_message=warning_message,
                        modified_output=redacted_text,
                        violation_type=ViolationType.SECRET_DETECTED,
                        tool_name=tool_name,
                    )
                    result["_warning"] = True
                    result["_violation_type"] = ViolationType.SECRET_DETECTED
                    _advance_transcript_position(hook_data)
                    return result

                logger.error(
                    "Secret finding could not be sanitized; blocking PostToolUse output"
                )

            logger.warning("Secrets detected and redaction disabled - blocking output")
            _log_post_tool_sensitive_outcome(
                post_secret_result, _scan_ctx, violation_logger, "block", "not_redacted"
            )
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
    warning_messages = [heuristic_notice] if heuristic_notice else []

    # PII scanning in PostToolUse (Issue #262)
    pii_file_path = tool_input.get("file_path") or tool_input.get("path")
    if not pii_file_path and pretool_ctx:
        pii_file_path = pretool_ctx.get("file_path")
    if is_url_output:
        pii_file_path = None

    # Cross-hook optimization: skip PII scan if PreToolUse skipped via ignore_files (#366)
    pii_skip_from_pretool = (
        not is_url_output
        and pretool_ctx
        and pretool_ctx.get("scan_results", {}).get("pii_skipped_reason")
        == "ignore_files match"
    )
    if not pii_skip_from_pretool:
        logger.info("Scanning tool output for PII...")
        post_pii_result = run_pii_scan(
            post_pii_content,
            file_path=pii_file_path,
            tool_identifier=tool_identifier,
            latency_timer=_latency_timer,
        )
        decoded_pii_results = [
            scan_result
            for scan_result in _scan_decoded_post_tool_content(
                post_pii_content,
                ScannerName.PII,
                file_path=pii_file_path,
                tool_identifier=tool_identifier,
                latency_timer=_latency_timer,
            )
            if scan_result.detected
        ]
        if decoded_pii_results:
            redacted_base64_output = _redact_encoded_source_spans(
                post_pii_content,
                decoded_pii_results,
                existing_result=(
                    post_pii_result
                    if post_pii_result is not None and post_pii_result.detected
                    else None
                ),
            )
            if redacted_base64_output is None:
                decoded_pii_result = decoded_pii_results[0]
                _log_post_tool_sensitive_outcome(
                    decoded_pii_result,
                    _scan_ctx,
                    violation_logger,
                    "block",
                    "not_redacted",
                )
                _advance_transcript_position(hook_data)
                return _format_response(
                    adapter,
                    has_secrets=True,
                    error_message=decoded_pii_result.error_message,
                    hook_event=hook_event,
                    violation_type=ViolationType.PII_DETECTED,
                )

            first_decoded_pii = decoded_pii_results[0]
            merged_redactions = [
                redaction
                for scan_result in decoded_pii_results
                for redaction in (scan_result.redactions or [])
            ]
            post_pii_result = replace(
                first_decoded_pii,
                redacted_content=redacted_base64_output,
                redactions=merged_redactions,
                extra={
                    **first_decoded_pii.extra,
                    "base64_candidate_count": len(decoded_pii_results),
                },
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
                if not pii_file_path and not is_url_output:
                    pii_file_path = _extract_file_path_from_pii_warning(pii_warning)
                post_pii_config, _ = _loaders._load_pii_config()
                _pii_cfg = post_pii_config or {
                    "action": post_pii_result.extra.get("action", "block")
                }
                pii_action = _pii_cfg.get("action", "block")
                configured_pii_action = pii_action
                pii_types = list(set(r["type"] for r in pii_redactions))
                _pii_first = pii_redactions[0] if pii_redactions else {}
                _pii_sc = _pii_first.get("column")
                if _pii_sc is not None:
                    _pii_sc = _pii_sc - 1
                _pii_ec = None
                if _pii_sc is not None:
                    _orig_len = _pii_first.get("original_length", 0)
                    if _orig_len:
                        _pii_ec = _pii_sc + _orig_len
                _pii_log_result = ScanResult(
                    detected=True,
                    violation_type=ViolationType.PII_DETECTED,
                    id=generate_violation_id(),
                    file_path=pii_file_path,
                    line_number=_pii_first.get("line_number"),
                    start_column=_pii_sc,
                    end_column=_pii_ec,
                    error_message=pii_warning or "",
                )
                logger.warning(f"PII detected in {tool_identifier} output: {pii_types}")

                # Build multi-finding list from PII redactions
                pii_matched_text = _extract_pii_matched_text(
                    pii_redactions, post_pii_content
                )
                pii_findings = _pii_redactions_to_findings(
                    pii_redactions, post_pii_content, pii_warning
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
                    from ai_guardian.ui.ask_dialog import AskDecision

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
                            ide_type=agent_type,
                            invocation_allowed_findings=_invocation_allowed,
                            finding_fingerprints=_compute_pii_transcript_fingerprints(
                                pii_redactions, post_pii_content
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
                            ide_type=agent_type,
                        )

                if (
                    should_downgrade_blocking_finding(
                        enabled=non_blocking_findings_enabled,
                        action=configured_pii_action,
                        detected=has_pii,
                        scan_error=post_pii_result.extra.get("scan_error"),
                    )
                    and _pii_redaction_verified(
                        tool_output, redacted_text, pii_redactions
                    )
                    and _supports_safe_post_output_replacement(agent_type, tool_name)
                ):
                    pii_action = "warn"
                    pii_session_downgraded = True
                else:
                    pii_session_downgraded = False

                if pii_action == "block":
                    _log_post_tool_sensitive_outcome(
                        _pii_log_result,
                        _scan_ctx,
                        violation_logger,
                        "block",
                        "not_redacted",
                    )
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
                    if post_pii_suppressed:
                        pii_redacted_lines = redacted_text.splitlines()
                        pii_original_lines = original_tool_output.splitlines()
                        for idx in post_pii_suppressed:
                            if 0 <= idx < len(pii_redacted_lines) and idx < len(
                                pii_original_lines
                            ):
                                pii_redacted_lines[idx] = pii_original_lines[idx]
                            redacted_text = "\n".join(pii_redacted_lines)
                    _log_post_tool_sensitive_outcome(
                        _pii_log_result,
                        _scan_ctx,
                        violation_logger,
                        "allow",
                        "redacted",
                    )
                    result = _format_response(
                        adapter,
                        has_secrets=False,
                        hook_event=hook_event,
                        warning_message=pii_warning,
                        modified_output=redacted_text,
                        violation_type=ViolationType.PII_DETECTED,
                        tool_name=tool_name,
                    )
                    result["_warning"] = True
                    result["_violation_type"] = ViolationType.PII_DETECTED
                    _advance_transcript_position(hook_data)
                    return result
                elif pii_action == "warn":
                    _log_post_tool_sensitive_outcome(
                        _pii_log_result,
                        _scan_ctx,
                        violation_logger,
                        "warn",
                        "redacted" if pii_session_downgraded else "not_redacted",
                    )
                    result = _format_response(
                        adapter,
                        has_secrets=False,
                        hook_event=hook_event,
                        warning_message=pii_warning,
                        modified_output=(
                            redacted_text if pii_session_downgraded else None
                        ),
                        violation_type=ViolationType.PII_DETECTED,
                        tool_name=tool_name,
                    )
                    result["_warning"] = True
                    result["_violation_type"] = ViolationType.PII_DETECTED
                    _advance_transcript_position(hook_data)
                    return result
                elif pii_action == "log-only":
                    _log_post_tool_sensitive_outcome(
                        _pii_log_result,
                        _scan_ctx,
                        violation_logger,
                        "log",
                        "not_redacted",
                    )
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
                    _log_post_tool_sensitive_outcome(
                        _pii_log_result,
                        _scan_ctx,
                        violation_logger,
                        "allow",
                        "not_redacted",
                    )
                    _advance_transcript_position(hook_data)
                    return _format_response(
                        adapter, has_secrets=False, hook_event=hook_event
                    )

    # Prompt injection and context poisoning scanning on PostToolUse output (#1285)
    post_warning_messages = [heuristic_notice] if heuristic_notice else []
    post_warn_types: list = (
        [ViolationType.HEURISTIC_CANDIDATE] if heuristic_notice else []
    )
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
            if (
                not is_url_output
                and pretool_ctx
                and pretool_ctx.get("ignore_files_matched")
            ):
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
                post_pi_content = _post_content_for("prompt_injection")
                post_pi_result = run_prompt_injection_scan(
                    post_pi_content,
                    config=post_pi_config,
                    file_path=post_pi_file,
                    tool_name=tool_identifier,
                    latency_timer=_latency_timer,
                )
                if post_pi_result is None or not post_pi_result.detected:
                    decoded_pi_results = _scan_decoded_post_tool_content(
                        post_pi_content,
                        ScannerName.PROMPT_INJECTION,
                        scanner_config=post_pi_config,
                        file_path=post_pi_file,
                        tool_identifier=tool_identifier,
                        latency_timer=_latency_timer,
                    )
                    post_pi_result = next(
                        (
                            scan_result
                            for scan_result in decoded_pi_results
                            if scan_result.detected
                        ),
                        post_pi_result,
                    )

                if post_pi_result is not None:
                    post_pi_detected = post_pi_result.detected
                    post_pi_block = post_pi_result.should_block
                    post_pi_error_msg = post_pi_result.error_message
                    post_pi_action = post_pi_result.extra.get("action", "block")
                    post_pi_downgraded = (
                        post_pi_block
                        and should_downgrade_blocking_finding(
                            enabled=non_blocking_findings_enabled,
                            action=post_pi_action,
                            detected=post_pi_detected,
                            scan_error=post_pi_result.extra.get("scan_error"),
                        )
                    )
                    post_pi_source = (
                        "prompt" if post_pi_cp_filename == "user_prompt" else "file"
                    )

                    if post_pi_detected:
                        log_violation(
                            post_pi_result,
                            _scan_ctx,
                            violation_logger=violation_logger,
                            source=post_pi_source,
                            policy_decision=_non_blocking_policy_decision(
                                post_pi_result,
                                post_pi_action,
                                non_blocking_findings_enabled,
                                _scan_ctx,
                                post_pi_source,
                            ),
                            suggestion={
                                "action": "add_allowlist_pattern",
                                "note": "If this is legitimate (e.g., documentation), add to allowlist in ai-guardian.json",
                            },
                        )

                    if post_pi_block:
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
                            from ai_guardian.ui.ask_dialog import AskDecision

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
                                    ide_type=agent_type,
                                )

                        if post_pi_block and post_pi_downgraded:
                            post_pi_block = False
                            post_warning_messages.append(
                                non_blocking_finding_advisory_message(post_pi_error_msg)
                            )
                            post_warn_types.append(ViolationType.PROMPT_INJECTION)

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
                    elif (
                        post_pi_detected
                        and post_pi_error_msg
                        and not post_pi_downgraded
                    ):
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
            if (
                not is_url_output
                and pretool_ctx
                and pretool_ctx.get("ignore_files_matched")
            ):
                post_cp_skip = True

            if post_cp_skip:
                logger.info(
                    "PostToolUse: skipping CP scan (PreToolUse already scanned clean)"
                )
            else:
                post_cp_file = tool_input.get("file_path") or tool_input.get("path")
                if not post_cp_file and pretool_ctx:
                    post_cp_file = pretool_ctx.get("file_path")

                post_cp_content = _post_content_for("context_poisoning")
                post_cp_result = run_context_poisoning_scan(
                    post_cp_content,
                    file_path=post_cp_file,
                    tool_identifier=tool_identifier,
                    latency_timer=_latency_timer,
                )
                if post_cp_result is None or not post_cp_result.detected:
                    decoded_cp_results = _scan_decoded_post_tool_content(
                        post_cp_content,
                        ScannerName.CONTEXT_POISONING,
                        file_path=post_cp_file,
                        tool_identifier=tool_identifier,
                        latency_timer=_latency_timer,
                    )
                    post_cp_result = next(
                        (
                            scan_result
                            for scan_result in decoded_cp_results
                            if scan_result.detected
                        ),
                        post_cp_result,
                    )

                if post_cp_result is not None:
                    post_cp_detected = post_cp_result.detected
                    post_cp_block = post_cp_result.should_block
                    post_cp_error_msg = post_cp_result.error_message
                    cp_action = post_cp_result.extra.get("action", "warn")
                    post_cp_downgraded = (
                        post_cp_block
                        and should_downgrade_blocking_finding(
                            enabled=non_blocking_findings_enabled,
                            action=cp_action,
                            detected=post_cp_detected,
                            scan_error=post_cp_result.extra.get("scan_error"),
                        )
                    )

                    if post_cp_detected:
                        log_violation(
                            post_cp_result,
                            _scan_ctx,
                            violation_logger=violation_logger,
                            source="prompt",
                            policy_decision=_non_blocking_policy_decision(
                                post_cp_result,
                                cp_action,
                                non_blocking_findings_enabled,
                                _scan_ctx,
                                "prompt",
                            ),
                            suggestion={
                                "action": "add_allowlist_pattern",
                                "note": "If this is a legitimate persistent instruction, add to context_poisoning.allowlist_patterns in ai-guardian.json",
                            },
                        )

                    if post_cp_block:
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
                            from ai_guardian.ui.ask_dialog import AskDecision

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
                                    ide_type=agent_type,
                                )

                        if post_cp_block and post_cp_downgraded:
                            post_cp_block = False
                            post_warning_messages.append(
                                non_blocking_finding_advisory_message(post_cp_error_msg)
                            )
                            post_warn_types.append(ViolationType.CONTEXT_POISONING)

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
                    elif (
                        post_cp_detected
                        and post_cp_error_msg
                        and not post_cp_downgraded
                    ):
                        post_warning_messages.append(post_cp_error_msg)
                        post_warn_types.append(ViolationType.CONTEXT_POISONING)
        except Exception as e:
            logger.warning(f"PostToolUse CP check error (fail-open): {e}")

    # Check for offensive language in PostToolUse output
    try:
        post_ol_result = run_offensive_language_scan(
            _post_content_for("offensive_language"),
            file_path=post_cp_file if "post_cp_file" in dir() else None,
            tool_identifier=(tool_identifier if "tool_identifier" in dir() else None),
            latency_timer=_latency_timer,
        )
        if post_ol_result is not None and post_ol_result.detected:
            post_ol_action = post_ol_result.extra.get("action", "log")
            post_ol_should_block = post_ol_result.should_block
            post_ol_downgraded = (
                post_ol_should_block
                and should_downgrade_blocking_finding(
                    enabled=non_blocking_findings_enabled,
                    action=post_ol_action,
                    detected=post_ol_result.detected,
                    scan_error=post_ol_result.extra.get("scan_error"),
                )
            )
            log_violation(
                post_ol_result,
                _scan_ctx,
                violation_logger=violation_logger,
                context_overrides={
                    "action": post_ol_action,
                },
                policy_decision=_non_blocking_policy_decision(
                    post_ol_result,
                    post_ol_action,
                    non_blocking_findings_enabled,
                    _scan_ctx,
                    "post_tool_use",
                ),
                suggestion={
                    "action": "review_offensive_language",
                    "note": (
                        "Replace the term with a neutral alternative. "
                        "Add '# ai-guardian:allow' inline or use scan_offensive.allowlist_patterns "
                        "to suppress known-safe uses."
                    ),
                },
            )
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
                from ai_guardian.ui.ask_dialog import AskDecision

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
                        ide_type=agent_type,
                    )
            if post_ol_should_block and post_ol_downgraded:
                post_ol_should_block = False
                post_warning_messages.append(
                    non_blocking_finding_advisory_message(post_ol_error_msg)
                )
                post_warn_types.append(ViolationType.OFFENSIVE_LANGUAGE)
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
            elif post_ol_error_msg and not post_ol_downgraded:
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
