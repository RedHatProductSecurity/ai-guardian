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
    run_context_poisoning_scan,
    run_prompt_injection_scan,
    run_secret_scan,
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
