"""Shared content scanning pipeline for SDK and hooks.

Single detection pipeline that both SDK and hook paths use, ensuring
consistent config handling, allowlists, language overlays, and
per-scanner action modes.  See issue #1927 (original), #1932 (registry migration).
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import ai_guardian.config.loaders as _loaders
from ai_guardian.hook_events.scanners import (
    apply_language_overlays,
    run_bash_exfil_scan,
    run_canary_detection_scan,
    run_config_file_scan,
    run_context_poisoning_scan,
    run_directory_check,
    run_exfil_detection_scan,
    run_offensive_language_scan,
    run_pii_scan,
    run_prompt_injection_scan,
    run_secret_scan,
    run_supply_chain_scan,
)
from ai_guardian.scanners.scan_result import ScanResult
from ai_guardian.scanners.scanner_registry import ScannerName

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
        ScannerName.PII,
    }
)


def _dispatch_scanner(
    scanner_name,
    text,
    *,
    scanner_config=None,
    file_path=None,
    filename="input",
    tool_name=None,
    tool_identifier=None,
    source_type="file_content",
    hook_event=None,
    latency_timer=None,
    secret_context=None,
    ignore_files=None,
    ignore_tools=None,
    allowlist_patterns=None,
):
    """Dispatch to the correct ``run_*_scan()`` function for *scanner_name*.

    Scanner signatures are not uniform; this function adapts shared
    arguments to each scanner's specific API.  Returns ``Optional[ScanResult]``.
    """
    if scanner_name == ScannerName.PROMPT_INJECTION:
        return run_prompt_injection_scan(
            text,
            config=scanner_config,
            file_path=file_path,
            tool_name=tool_name,
            source_type=source_type,
            latency_timer=latency_timer,
        )
    elif scanner_name == ScannerName.CONTEXT_POISONING:
        return run_context_poisoning_scan(
            text,
            config=scanner_config,
            file_path=file_path,
            tool_identifier=tool_identifier,
            latency_timer=latency_timer,
        )
    elif scanner_name == ScannerName.SUPPLY_CHAIN:
        return run_supply_chain_scan(
            text,
            file_path or filename or "user_prompt",
            config=scanner_config,
            hook_event=hook_event,
            latency_timer=latency_timer,
        )
    elif scanner_name == ScannerName.OFFENSIVE_LANGUAGE:
        return run_offensive_language_scan(
            text,
            config=scanner_config,
            file_path=file_path,
            tool_identifier=tool_identifier,
            latency_timer=latency_timer,
        )
    elif scanner_name == ScannerName.CANARY_DETECTION:
        return run_canary_detection_scan(
            text,
            file_path or filename or "content",
            config=scanner_config,
            latency_timer=latency_timer,
        )
    elif scanner_name == ScannerName.CONFIG_FILE:
        if not file_path:
            return None
        return run_config_file_scan(
            file_path,
            text,
            config=scanner_config,
            latency_timer=latency_timer,
        )
    elif scanner_name == ScannerName.SECRET:
        return run_secret_scan(
            text,
            filename,
            config=scanner_config,
            context=secret_context,
            file_path=file_path,
            tool_name=tool_name,
            ignore_files=ignore_files,
            ignore_tools=ignore_tools,
            allowlist_patterns=allowlist_patterns,
            latency_timer=latency_timer,
        )
    elif scanner_name == ScannerName.PII:
        return run_pii_scan(
            text,
            config=scanner_config,
            file_path=file_path,
            tool_identifier=tool_identifier,
            latency_timer=latency_timer,
        )
    else:
        logger.debug("No dispatcher for scanner %s", scanner_name)
        return None


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
    scanner (e.g., annotation-suppressed content for secrets/PII).

    *scanner_kwargs* maps ``ScannerName`` → dict of extra keyword arguments
    for that scanner (e.g., ``context``, ``ignore_files`` for secrets).

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
        registry, hook_event=hook_event, file_path=file_path
    )

    results = []
    overrides = content_overrides or {}
    extra_kwargs = dict(scanner_kwargs) if scanner_kwargs else {}

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

        try:
            scanner_config = _resolve_scanner_config_for_entry(config, entry, cwd=cwd)

            per_scanner = extra_kwargs.get(scanner_name)
            if per_scanner:
                merged_kwargs = dict(per_scanner)
                scanner_config = merged_kwargs.pop("config", scanner_config)
            else:
                merged_kwargs = {}

            result = _dispatch_scanner(
                scanner_name,
                scan_text,
                scanner_config=scanner_config,
                file_path=file_path,
                filename=filename,
                tool_name=tool_name,
                tool_identifier=tool_identifier,
                source_type=source_type,
                hook_event=hook_event,
                latency_timer=latency_timer,
                **merged_kwargs,
            )
            if result is not None:
                result.extra.setdefault("scanner_name", scanner_name.value)
                if (
                    result.detected
                    or result.error_message
                    or result.extra.get("skipped")
                ):
                    results.append(result)
        except Exception as exc:
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

    return results


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


def _get_content_pipeline(registry, *, hook_event=None, file_path=None):
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
        return [e for e in entries if e.name in _CONTENT_SCANNER_NAMES]

    # SDK fallback: all content scanners, filtered by available inputs
    applicable = []
    for entry in registry.all_entries():
        if entry.name not in _CONTENT_SCANNER_NAMES:
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
