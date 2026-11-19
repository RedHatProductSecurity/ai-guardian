"""Shared content scanning pipeline for SDK and hooks.

Single detection pipeline that both SDK and hook paths use, ensuring
consistent config handling, allowlists, language overlays, and
per-scanner action modes.  See issue #1927 (original), #1932 (registry migration).
"""

import logging
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import ai_guardian.config.loaders as _loaders
from ai_guardian.hook_events.scanners import (
    apply_language_overlays,
    run_bash_exfil_scan,
    run_directory_check,
    run_exfil_detection_scan,
)
from ai_guardian.scanners.scan_result import ScanResult
from ai_guardian.scanners.scanner_registry import ScannerName
from ai_guardian.scanners.base64_text import (
    DecodedBase64Text,
    iter_decoded_base64_text,
)

logger = logging.getLogger(__name__)

# Scanners that scan text content (not commands, images, or directories).
# Used as fallback when no hook_event is provided (SDK path).
_CONTENT_SCANNER_NAMES = frozenset(
    {
        ScannerName.PROMPT_INJECTION,
        ScannerName.CONTEXT_POISONING,
        ScannerName.SUPPLY_CHAIN,
        ScannerName.OFFENSIVE_LANGUAGE,
        ScannerName.CANARY_DETECTION,
        ScannerName.CONFIG_FILE,
        ScannerName.SECRET,
        ScannerName.PASSWORD_LIKELIHOOD,
        ScannerName.PII,
    }
)

_BASE64_TEXT_SCANNER_NAMES = frozenset(
    {
        ScannerName.PROMPT_INJECTION,
        ScannerName.CONTEXT_POISONING,
        ScannerName.SECRET,
        ScannerName.PII,
    }
)

_BASE64_DETECTION_MESSAGES = {
    ScannerName.PROMPT_INJECTION: (
        "Prompt injection detected in decoded Base64 text; content withheld."
    ),
    ScannerName.CONTEXT_POISONING: (
        "Context poisoning detected in decoded Base64 text; content withheld."
    ),
    ScannerName.SECRET: "Secret detected in decoded Base64 text; value withheld.",
    ScannerName.PII: "PII detected in decoded Base64 text; value withheld.",
}

_BASE64_SCAN_ERROR = "Decoded Base64 text scan failed; details withheld."


def scan_content(
    text: Optional[str],
    *,
    config: Optional[Dict[str, Any]] = None,
    cwd: Optional[str] = None,
    filename: str = "input",
    source_type: str = "file_content",
    source_command: Optional[str] = None,
    file_path: Optional[str] = None,
    tool_name: Optional[str] = None,
    hook_event: Optional[str] = None,
    tool_identifier: Optional[str] = None,
    latency_timer: Optional[Any] = None,
    content_overrides: Optional[Dict[ScannerName, str]] = None,
    scanner_kwargs: Optional[Dict[ScannerName, Dict[str, Any]]] = None,
    registry: Optional[Any] = None,
    scanner_names: Optional[Set[ScannerName]] = None,
    decoded_only: bool = False,
) -> List[ScanResult]:
    """Run all enabled content scanners on *text*.

    Config resolution per scanner:
      - If *config* is provided, the scanner's section is extracted from it
        (e.g. ``config["prompt_injection"]``).
      - If the section is missing or *config* is ``None``, the scanner loads
        its own config from ``ai-guardian.json`` via the standard loaders.
      - Language auto-detection overlays are applied for scanners that have
        ``supports_language_overlay=True`` in their registry entry.

    When *hook_event* is provided, the scanner registry filters scanners
    applicable to that event.  Without it (SDK path), all content scanners
    are eligible, filtered by available inputs (*file_path*, etc.).

    *content_overrides* maps ``ScannerName`` → alternative text for that
    scanner (e.g., scanner-scoped annotation-suppressed file content).

    *scanner_kwargs* maps ``ScannerName`` → dict of extra keyword arguments
    for that scanner (e.g., ``context``, ``ignore_files`` for secrets).

    *scanner_names* restricts the content pipeline to selected registry entries.
    It is used by daemon-backed middleware ownership routing.

    *decoded_only* skips scanning the original source and inspects only bounded
    Base64 text candidates. This is used when a caller already scanned the
    original source through a specialized hook path.

    Returns only ``ScanResult`` objects where a detection occurred, plus
    any error results (``extra["scan_error"]`` set) so callers can apply
    fail-closed logic.  Each scanner is wrapped in try/except for
    fail-open behaviour by default.
    """
    if not text:
        return []

    if registry is None:
        from ai_guardian.scanners.scanner_registry import get_default_registry

        registry = get_default_registry()

    pipeline = _get_content_pipeline(
        registry,
        hook_event=hook_event,
        file_path=file_path,
        scanner_names=scanner_names,
    )

    results: List[ScanResult] = []
    overrides = dict(content_overrides or {})

    # SDK/file-scan callers share the same source annotation behavior as hooks.
    # User prompts and content without a verified file path remain unfiltered.
    if source_type == "file_content" and file_path and hook_event is None:
        from ai_guardian.annotations import (
            canonical_scanner_type,
            process_annotations_by_scanner,
        )
        from ai_guardian.config.utils import is_feature_enabled

        if isinstance(config, dict) and isinstance(config.get("annotations"), dict):
            annotation_config = config["annotations"]
        else:
            annotation_config, annotation_error = _loaders._load_annotations_config()
            if annotation_error:
                logger.warning("Could not load annotation configuration")

        if isinstance(annotation_config, dict) and is_feature_enabled(
            annotation_config.get("enabled"), default=True
        ):
            content_by_scanner, _, _ = process_annotations_by_scanner(
                text,
                (entry.name.value for entry in pipeline),
                file_path=file_path,
                config=annotation_config,
            )
            for entry in pipeline:
                annotation_type = canonical_scanner_type(entry.name.value)
                if annotation_type in content_by_scanner:
                    overrides.setdefault(
                        entry.name, content_by_scanner[annotation_type]
                    )

    extra_kwargs = dict(scanner_kwargs) if scanner_kwargs else {}
    decoded_candidates = (
        list(iter_decoded_base64_text(text))
        if any(entry.name in _BASE64_TEXT_SCANNER_NAMES for entry in pipeline)
        else []
    )
    scanner_invocations = {}

    # Build source_command context for secret scanning (SDK path)
    if source_command and filename.startswith("tool_result:"):
        if ScannerName.SECRET not in extra_kwargs:
            extra_kwargs[ScannerName.SECRET] = {}
        if "secret_context" not in extra_kwargs.get(ScannerName.SECRET, {}):
            try:
                from ai_guardian.hook_events.post_tool_use import (
                    _sanitize_source_command,
                )

                extra_kwargs.setdefault(ScannerName.SECRET, {})["secret_context"] = {
                    "source_command": _sanitize_source_command(source_command)
                }
            except Exception:  # intentionally silent — import guard + sanitize fallback
                pass

    for entry in pipeline:
        scanner_name = entry.name
        scan_text = overrides.get(scanner_name, text)
        scanner_config = None

        try:
            scanner_config = _resolve_scanner_config_for_entry(config, entry, cwd=cwd)

            per_scanner = extra_kwargs.get(scanner_name)
            if per_scanner:
                merged_kwargs = dict(per_scanner)
                scanner_config = merged_kwargs.pop("config", scanner_config)
            else:
                merged_kwargs = {}

            scanner_invocations[scanner_name] = (
                entry,
                scanner_config,
                dict(merged_kwargs),
                scan_text,
            )

            result = None
            if not decoded_only:
                result = entry.run_fn(
                    scan_text,
                    config=scanner_config,
                    file_path=file_path,
                    filename=filename,
                    tool_name=tool_name,
                    tool_identifier=tool_identifier,
                    source_type=source_type,
                    hook_event=hook_event,
                    latency_timer=latency_timer,
                    **merged_kwargs,
                )
            if result is not None and scanner_name == ScannerName.PASSWORD_LIKELIHOOD:
                from ai_guardian.scanners.password_likelihood import (
                    exclude_credential_overlaps,
                )

                result = exclude_credential_overlaps(result, results)
            if result is not None:
                result.extra.setdefault("scanner_name", scanner_name.value)
                if (
                    result.detected
                    or result.error_message
                    or result.extra.get("skipped")
                ):
                    results.append(result)
        except Exception as exc:
            if scanner_name == ScannerName.PASSWORD_LIKELIHOOD:
                from ai_guardian.scanners.password_likelihood import (
                    incomplete_password_scan,
                )

                logger.warning("Password-likelihood stage failed; details withheld")
                results.append(incomplete_password_scan(scanner_config))
                continue
            logger.warning(
                "%s scan error (fail-open)", scanner_name.value, exc_info=True
            )
            error_result = ScanResult(
                detected=False,
                violation_type=entry.violation_type.value,
                error_message=str(exc),
                extra={"scan_error": str(exc), "scanner_name": scanner_name.value},
            )
            results.append(error_result)

    if decoded_candidates:
        results.extend(
            _scan_decoded_base64_candidates(
                decoded_candidates,
                text,
                scanner_invocations,
                filename=filename,
                source_type=source_type,
                file_path=file_path,
                tool_name=tool_name,
                tool_identifier=tool_identifier,
                hook_event=hook_event,
                latency_timer=latency_timer,
            )
        )

    return results


def _scan_decoded_base64_candidates(
    candidates: List[DecodedBase64Text],
    source: str,
    scanner_invocations: Dict,
    *,
    filename: str,
    source_type: str,
    file_path: Optional[str],
    tool_name: Optional[str],
    tool_identifier: Optional[str],
    hook_event: Optional[str],
    latency_timer: Optional[Any],
) -> List[ScanResult]:
    """Run only the applicable content detectors over decoded text candidates."""
    results = []
    secret_state = None
    if ScannerName.SECRET in scanner_invocations:
        from ai_guardian.scanners import secret_scanning

        state_names = (
            "_last_secret_matched_text",
            "_last_secret_line_number",
            "_last_secret_start_column",
            "_last_secret_findings",
        )
        secret_state = (
            secret_scanning,
            {name: getattr(secret_scanning, name) for name in state_names},
        )
    try:
        for candidate in candidates:
            for scanner_name in scanner_invocations:
                if scanner_name not in _BASE64_TEXT_SCANNER_NAMES:
                    continue
                invocation = scanner_invocations.get(scanner_name)
                if invocation is None:
                    continue
                entry, scanner_config, merged_kwargs, scan_text = invocation
                if (
                    not isinstance(scan_text, str)
                    or scan_text[candidate.start : candidate.end] != candidate.encoded
                ):
                    # Annotation/content overrides can suppress a source span.
                    continue

                decoded_kwargs = dict(merged_kwargs)
                if scanner_name == ScannerName.SECRET:
                    secret_context = dict(decoded_kwargs.get("secret_context") or {})
                    secret_context["_allowlist_content"] = candidate.text
                    secret_context["_defer_secret_violation_logging"] = True
                    secret_context["_suppress_secret_violation_logging"] = True
                    secret_context["_suppress_ast_scan"] = True
                    decoded_kwargs["secret_context"] = secret_context
                else:
                    decoded_kwargs["suppress_sensitive_logging"] = True

                try:
                    result = entry.run_fn(
                        candidate.text,
                        config=scanner_config,
                        file_path=file_path,
                        filename=filename,
                        tool_name=tool_name,
                        tool_identifier=tool_identifier,
                        source_type=source_type,
                        hook_event=hook_event,
                        latency_timer=latency_timer,
                        **decoded_kwargs,
                    )
                except Exception:
                    logger.warning(
                        "%s scan failed for decoded Base64 text; details withheld",
                        scanner_name.value,
                    )
                    result = ScanResult(
                        detected=False,
                        violation_type=entry.violation_type.value,
                        error_message=_BASE64_SCAN_ERROR,
                        extra={"scan_error": "decoded_base64_scan_failed"},
                    )

                if result is None:
                    continue
                safe_result = _sanitize_decoded_scan_result(
                    result,
                    candidate,
                    source,
                    scanner_name,
                    file_path=file_path,
                )
                if safe_result is not None:
                    safe_result.extra.setdefault("scanner_name", scanner_name.value)
                    results.append(safe_result)
    finally:
        if secret_state is not None:
            secret_scanning, saved_state = secret_state
            for name, value in saved_state.items():
                setattr(secret_scanning, name, value)
    return results


def _sanitize_decoded_scan_result(
    result: ScanResult,
    candidate: DecodedBase64Text,
    source: str,
    scanner_name: ScannerName,
    *,
    file_path: Optional[str],
) -> Optional[ScanResult]:
    """Keep only safe category/action/location data from a decoded scan result."""
    original_extra = result.extra if isinstance(result.extra, dict) else {}
    if original_extra.get("skipped"):
        return None

    has_scan_error = bool(original_extra.get("scan_error"))
    pii_incomplete = (
        scanner_name == ScannerName.PII
        and result.detected
        and not result.redactions
        and bool(result.error_message)
    )
    has_error = (
        has_scan_error
        or pii_incomplete
        or (not result.detected and bool(result.error_message))
    )
    if not result.detected and not has_error:
        return None

    def _mapped_location(
        line_number: Optional[int], column: Optional[int]
    ) -> Tuple[int, int]:
        decoded_offset = candidate.decoded_offset(line_number, column)
        return candidate.source_location(source, decoded_offset)

    def _detection_message(
        line_number: Optional[int], start_column: Optional[int]
    ) -> str:
        message = _BASE64_DETECTION_MESSAGES[scanner_name]
        if scanner_name == ScannerName.PII and redactions:
            pii_types: Set[str] = set()
            for redaction in redactions:
                pii_type = redaction.get("type")
                if isinstance(pii_type, str) and pii_type != "unknown":
                    pii_types.add(pii_type)
            types = sorted(pii_types)
            if types:
                message = (
                    f"PII ({', '.join(types)}) detected in decoded Base64 text; "
                    "value withheld."
                )
        if type(line_number) is int and type(start_column) is int:
            description, _, privacy_note = message.partition("; ")
            message = (
                f"{description} at line {line_number}, column {start_column + 1}; "
                f"{privacy_note}"
            )
        return message

    redactions: Optional[List[Dict[str, Any]]]
    line_number: Optional[int] = None
    start_column: Optional[int] = None
    if scanner_name == ScannerName.PII and result.redactions:
        safe_redactions: List[Dict[str, Any]] = []
        for redaction in result.redactions:
            position = redaction.get("position")
            if (
                isinstance(position, int)
                and not isinstance(position, bool)
                and 0 <= position <= len(candidate.text)
            ):
                decoded_offset = position
            else:
                column_value = redaction.get("column")
                column_offset = (
                    column_value - 1
                    if isinstance(column_value, int)
                    and not isinstance(column_value, bool)
                    else None
                )
                decoded_offset = candidate.decoded_offset(
                    redaction.get("line_number"),
                    column_offset,
                )
            line_number, column = candidate.source_location(source, decoded_offset)
            pii_type = redaction.get("type")
            if not isinstance(pii_type, str) or not pii_type:
                pii_type = "unknown"
            safe_redactions.append(
                {
                    "type": pii_type,
                    "line_number": line_number,
                    "column": column + 1,
                    # Do not retain or reconstruct the decoded value.
                    "position": -1,
                    "original_length": 0,
                }
            )
        redactions = safe_redactions
    else:
        redactions = None

    if redactions:
        line_number = redactions[0]["line_number"]
        start_column = redactions[0]["column"] - 1
    else:
        line_number, start_column = _mapped_location(
            result.line_number, result.start_column
        )

    end_line: Optional[int] = None
    end_column: Optional[int] = None
    if result.end_line is not None or result.end_column is not None:
        end_line, end_column = _mapped_location(
            result.end_line or result.line_number,
            result.end_column,
        )

    action = original_extra.get("action")
    safe_extra: Dict[str, Any] = {"base64_decoded": True}
    safe_extra["base64_source_start"] = candidate.start
    safe_extra["base64_source_end"] = candidate.end
    if isinstance(action, str):
        safe_extra["action"] = action
    if has_scan_error:
        safe_extra["scan_error"] = "decoded_base64_scan_failed"

    safe_result = replace(
        result,
        error_message=(
            _BASE64_SCAN_ERROR
            if has_error
            else _detection_message(line_number, start_column)
        ),
        matched_text="",
        matched_pattern="",
        rule_id="",
        file_path=result.file_path or file_path,
        line_number=line_number,
        end_line=end_line,
        start_column=start_column,
        end_column=end_column,
        attack_type="",
        findings=None,
        redacted_content=None,
        redactions=redactions,
        extra=safe_extra,
    )
    return safe_result


def scan_file(
    file_path: str,
    *,
    content: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    cwd: Optional[str] = None,
) -> List[ScanResult]:
    """Run all enabled file scanners on *file_path* (and optionally *content*).

    Scanners executed:
      1. Directory rules check (always)
      2. Content scanning via ``scan_content()`` (when *content* is provided)
         — includes config file, supply chain, PI, CP, secrets, OL, CD, PII

    Config resolution follows the same ``_resolve_scanner_config_for_entry``
    pattern as ``scan_content``.  Returns only ``ScanResult`` objects where a
    detection occurred.
    """
    if not file_path:
        return []

    results = []

    # --- Directory rules ---
    try:
        result = run_directory_check(file_path, config=config)
        if result is not None and result.detected:
            results.append(result)
    except Exception:
        logger.warning("Directory check error (fail-open)", exc_info=True)

    if content is not None:
        # --- Content scanning (all content scanners, registry-driven) ---
        try:
            content_results = scan_content(
                content,
                config=config,
                cwd=cwd,
                filename=file_path,
                source_type="file_content",
                file_path=file_path,
            )
            results.extend(content_results)
        except Exception:
            logger.warning("Content scan error (fail-open)", exc_info=True)

    return results


def scan_command(
    command: str,
    *,
    config: Optional[Dict[str, Any]] = None,
) -> List[ScanResult]:
    """Run all enabled command scanners on *command*.

    Scanners executed:
      1. Bash command exfiltration check (config file exfil patterns)
      2. Exfiltration behaviour detection (credential theft, etc.)

    Returns only ``ScanResult`` objects where a detection occurred.
    """
    if not command:
        return []

    results = []

    # Independent command-semantic scanner. It intentionally does not reuse the
    # experimental password-likelihood heuristic below.
    from ai_guardian.scanners.command_credentials import run_command_credential_scan

    command_credential_config = None
    if isinstance(config, dict):
        command_credential_config = config.get("command_credential_scanning") or {}
    command_credential_result = run_command_credential_scan(
        command, config=command_credential_config
    )
    if command_credential_result is not None and command_credential_result.detected:
        results.append(command_credential_result)

    # Independent password stage; command data never supplies policy.
    from ai_guardian.scanners.password_likelihood import run_password_likelihood_scan

    heuristic_config = (
        config.get("password_likelihood") or {"enabled": False}
        if config is not None
        else None
    )
    heuristic_result = run_password_likelihood_scan(command, config=heuristic_config)
    if heuristic_result is not None and (
        heuristic_result.detected or heuristic_result.error_message
    ):
        results.append(heuristic_result)

    # --- Bash command exfil (config scanner) ---
    try:
        cfg_scanner_cfg = _resolve_scanner_config(
            config, "config_scanner", _loaders._load_config_scanner_config
        )
        result = run_bash_exfil_scan(command, config=cfg_scanner_cfg)
        if result is not None and result.detected:
            results.append(result)
    except Exception:
        logger.warning("Bash exfil scan error (fail-open)", exc_info=True)

    # --- Exfiltration behaviour detection ---
    try:
        exfil_cfg = _resolve_scanner_config(
            config, "exfil_detection", _loaders._load_exfil_detection_config
        )
        result = run_exfil_detection_scan(command, config=exfil_cfg)
        if result is not None and result.detected:
            results.append(result)
    except Exception:
        logger.warning("Exfil detection scan error (fail-open)", exc_info=True)

    return results


def _get_content_pipeline(
    registry, *, hook_event=None, file_path=None, scanner_names=None
):
    """Return the ordered list of content scanners to run.

    When *hook_event* is provided, uses the registry's event-based filtering.
    Otherwise (SDK path), returns all content scanners applicable to the
    available inputs.
    """
    if hook_event is not None:
        entries = registry.get_pipeline(
            hook_event,
            has_content=True,
            has_file_path=file_path is not None,
            has_command=False,
        )
        return [
            e
            for e in entries
            if e.name in _CONTENT_SCANNER_NAMES
            and (scanner_names is None or e.name in scanner_names)
        ]

    # SDK fallback: all content scanners, filtered by available inputs
    applicable = []
    for entry in registry.all_entries():
        if entry.name not in _CONTENT_SCANNER_NAMES:
            continue
        if scanner_names is not None and entry.name not in scanner_names:
            continue
        if entry.requires_file_path and not file_path:
            continue
        if entry.requires_command:
            continue
        applicable.append(entry)
    applicable.sort(key=lambda e: e.order)
    return applicable


def _resolve_scanner_config_for_entry(full_config, entry, *, cwd=None):
    """Resolve scanner config for a registry entry.

    Uses ``entry.config_section`` to extract from *full_config* or load
    from file.  Applies language overlays when supported.
    """
    section_key = entry.config_section
    if not section_key:
        return None

    if section_key == "password_likelihood":
        # Explicit SDK config is trusted application policy, not scan content.
        # Missing opt-in in that config must NOT fall through to workstation policy.
        if full_config is not None:
            return full_config.get(section_key) or {"enabled": False}
        return _loaders._load_password_likelihood_config()[0]

    if full_config is not None:
        section = full_config.get(section_key)
        cfg = section or None
    else:
        cfg_loaded, _ = _loaders._load_config_section(section_key, merge_ignore=True)
        cfg = cfg_loaded or None

    if cfg and entry.supports_language_overlay:
        cfg = apply_language_overlays(cfg, entry.name.value, cwd=cwd)

    return cfg


def _resolve_scanner_config(
    full_config: Optional[Dict[str, Any]],
    section_key: str,
    loader_fn: Callable[[], Tuple[Optional[Dict[str, Any]], Any]],
) -> Optional[Dict[str, Any]]:
    """Extract scanner config from *full_config*, falling back to file.

    Returns ``None`` when the section is absent or empty so that
    ``run_*_scan()`` either loads its own config or skips gracefully.

    .. deprecated::
        Prefer ``_resolve_scanner_config_for_entry`` for registry-driven
        scanning.  This function is kept for ``scan_command()`` which
        does not use the registry yet.
    """
    if full_config is not None:
        section = full_config.get(section_key)
        # empty dict is falsy — convert to None so scanners don't skip
        # (see cerebrum Do-Not-Repeat 2026-08-05)
        return section or None
    config, _ = loader_fn()
    return config or None
