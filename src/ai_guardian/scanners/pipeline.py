"""Shared content scanning pipeline for SDK and hooks.

Single detection pipeline that both SDK and hook paths use, ensuring
consistent config handling, allowlists, language overlays, and
per-scanner action modes.  See issue #1927.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import ai_guardian.config.loaders as _loaders
from ai_guardian.hook_events.scanners import (
    apply_language_overlays,
    run_bash_exfil_scan,
    run_config_file_scan,
    run_context_poisoning_scan,
    run_directory_check,
    run_exfil_detection_scan,
    run_prompt_injection_scan,
    run_secret_scan,
    run_supply_chain_scan,
)
from ai_guardian.scanners.scan_result import ScanResult

logger = logging.getLogger(__name__)


def scan_content(
    text: str,
    *,
    config: Optional[Dict[str, Any]] = None,
    cwd: Optional[str] = None,
    filename: str = "input",
    source_type: str = "file_content",
    source_command: Optional[str] = None,
    file_path: Optional[str] = None,
    tool_name: Optional[str] = None,
) -> List[ScanResult]:
    """Run all enabled content scanners on *text*.

    Config resolution per scanner:
      - If *config* is provided, the scanner's section is extracted from it
        (e.g. ``config["prompt_injection"]``).
      - If the section is missing or *config* is ``None``, the scanner loads
        its own config from ``ai-guardian.json`` via the standard loaders.
      - Language auto-detection overlays are applied for prompt injection
        when *cwd* is set or ``get_project_dir()`` returns a path.

    Returns only ``ScanResult`` objects where a detection occurred.
    Each scanner is wrapped in try/except for fail-open behaviour.
    """
    if not text:
        return []

    results: List[ScanResult] = []

    # --- Prompt injection ---
    try:
        pi_cfg = _resolve_scanner_config(
            config, "prompt_injection", _loaders._load_prompt_injection_config
        )
        if pi_cfg:
            pi_cfg = apply_language_overlays(pi_cfg, "prompt_injection", cwd=cwd)
        result = run_prompt_injection_scan(
            text,
            config=pi_cfg,
            file_path=file_path,
            tool_name=tool_name,
            source_type=source_type,
        )
        if result is not None and result.detected:
            results.append(result)
    except Exception:
        logger.warning("Prompt injection scan error (fail-open)", exc_info=True)

    # --- Context poisoning ---
    try:
        cp_cfg = _resolve_scanner_config(
            config, "context_poisoning", _loaders._load_context_poisoning_config
        )
        result = run_context_poisoning_scan(
            text,
            config=cp_cfg,
            file_path=file_path,
            tool_name=tool_name,
        )
        if result is not None and result.detected:
            results.append(result)
    except Exception:
        logger.warning("Context poisoning scan error (fail-open)", exc_info=True)

    # --- Secret scanning ---
    try:
        secret_cfg = _resolve_scanner_config(
            config, "secret_scanning", _loaders._load_secret_scanning_config
        )
        ctx = None
        if source_command and filename.startswith("tool_result:"):
            try:
                from ai_guardian.hook_events.post_tool_use import (
                    _sanitize_source_command,
                )

                ctx = {"source_command": _sanitize_source_command(source_command)}
            except Exception:  # intentionally silent — import guard + sanitize fallback
                pass
        result = run_secret_scan(
            text,
            filename,
            config=secret_cfg,
            context=ctx,
            file_path=file_path,
            tool_name=tool_name,
        )
        if result is not None and result.detected:
            results.append(result)
    except Exception:
        logger.warning("Secret scan error (fail-open)", exc_info=True)

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
      2. Config file threat scan (when *content* is provided)
      3. Supply chain scan (when *content* is provided)
      4. Content scanning via ``scan_content()`` (when *content* is provided)

    Config resolution follows the same ``_resolve_scanner_config`` pattern
    as ``scan_content``.  Returns only ``ScanResult`` objects where a
    detection occurred.
    """
    if not file_path:
        return []

    results: List[ScanResult] = []

    # --- Directory rules ---
    try:
        result = run_directory_check(file_path, config=config)
        if result is not None and result.detected:
            results.append(result)
    except Exception:
        logger.warning("Directory check error (fail-open)", exc_info=True)

    if content is not None:
        # --- Config file threats ---
        try:
            cfg_scanner_cfg = _resolve_scanner_config(
                config, "config_scanner", _loaders._load_config_scanner_config
            )
            result = run_config_file_scan(file_path, content, config=cfg_scanner_cfg)
            if result is not None and result.detected:
                results.append(result)
        except Exception:
            logger.warning("Config file scan error (fail-open)", exc_info=True)

        # --- Supply chain threats ---
        try:
            sc_cfg = _resolve_scanner_config(
                config, "supply_chain", _loaders._load_supply_chain_config
            )
            result = run_supply_chain_scan(content, file_path, config=sc_cfg)
            if result is not None and result.detected:
                results.append(result)
        except Exception:
            logger.warning("Supply chain scan error (fail-open)", exc_info=True)

        # --- Content scanning (PI, CP, secrets) ---
        try:
            content_results = scan_content(
                content,
                config=config,
                cwd=cwd,
                filename=file_path,
                source_type="file_content",
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

    results: List[ScanResult] = []

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


def _resolve_scanner_config(
    full_config: Optional[Dict[str, Any]],
    section_key: str,
    loader_fn: Callable[[], Tuple[Optional[Dict[str, Any]], Any]],
) -> Optional[Dict[str, Any]]:
    """Extract scanner config from *full_config*, falling back to file.

    Returns ``None`` when the section is absent or empty so that
    ``run_*_scan()`` either loads its own config or skips gracefully.
    """
    if full_config is not None:
        section = full_config.get(section_key)
        # empty dict is falsy — convert to None so scanners don't skip
        # (see cerebrum Do-Not-Repeat 2026-08-05)
        return section or None
    config, _ = loader_fn()
    return config or None
