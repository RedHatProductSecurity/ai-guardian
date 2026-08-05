"""
Engine execution for secret scanning.

Provides:
- run_single_engine(): runs one subprocess-based scanner engine
- run_python_scanner(): runs one Python-based scanner in-process
- run_engine(): dispatcher that routes to the correct executor

These functions are the building blocks that execution strategies use.
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)
import time
from typing import Optional

from ai_guardian.daemon import get_daemon_state as _get_daemon_state
from ai_guardian.scanners.engine_builder import EngineConfig, build_scanner_command
from ai_guardian.scanners.output_parsers import get_parser
from ai_guardian.scanners.strategies import ScanResult, SecretMatch


def _cache_get(cache, content_hash, engine_config, engine_label):
    """Check cache for a previous scan result. Returns (result, cfg_hash) or (None, cfg_hash)."""
    if not (cache and content_hash):
        return None, None
    from ai_guardian.scanners.cache import ScanResultCache

    cfg_hash = ScanResultCache.config_hash(engine_config)
    cached = cache.get(content_hash, engine_label, cfg_hash)
    if cached is not None:
        logger.info(f"Cache hit for {engine_label} (hash={content_hash[:12]})")
    return cached, cfg_hash


def _cache_put(cache, content_hash, engine_label, cfg_hash, result):
    """Store a scan result in the cache if caching is active."""
    if cache and content_hash and cfg_hash is not None:
        cache.put(content_hash, engine_label, cfg_hash, result)


def run_single_engine(
    engine_config: EngineConfig,
    source_file: str,
    report_file: str,
    config_path: Optional[str] = None,
    timeout: int = 30,
    cache=None,
    content_hash: Optional[str] = None,
    original_file_path: Optional[str] = None,
) -> ScanResult:
    """
    Run a single scanner engine and return standardized results.

    Builds the scanner command, executes via subprocess, parses the output,
    and returns a ScanResult with SecretMatch objects.

    Args:
        engine_config: Engine configuration (from ENGINE_PRESETS or custom)
        source_file: Path to the file being scanned
        report_file: Path for scanner output report
        config_path: Optional path to scanner configuration file
        timeout: Subprocess timeout in seconds
        cache: Optional ScanResultCache for result caching
        content_hash: Optional content hash for cache lookups

    Returns:
        ScanResult with findings from this engine
    """
    cached, cfg_hash = _cache_get(
        cache, content_hash, engine_config, engine_config.type
    )
    if cached is not None:
        return cached

    if hasattr(engine_config, "api_key_env") and engine_config.api_key_env:
        if not os.environ.get(engine_config.api_key_env):
            return ScanResult(
                has_secrets=False,
                secrets=[],
                engine=engine_config.type,
                error=f"API key not set: ${engine_config.api_key_env}",
            )

    start_time = time.monotonic()

    try:
        cmd = build_scanner_command(
            engine_config=engine_config,
            source_file=source_file,
            report_file=report_file,
            config_path=config_path,
        )

        logger.debug(f"Engine {engine_config.type}: running {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        elapsed_ms = (time.monotonic() - start_time) * 1000

        # For engines that write to stdout instead of a report file
        # (TruffleHog, detect-secrets), write stdout to the report file
        if "{report_file}" not in " ".join(engine_config.command_template):
            if result.stdout:
                with open(report_file, "w", encoding="utf-8") as f:
                    f.write(result.stdout)

        # Gitleaks/betterleaks exit code 1 special case (Issue #411):
        # when --exit-code flag is not honored, exit 1 means secrets found
        is_gitleaks_like = engine_config.type in ("gitleaks", "betterleaks")
        is_secrets_found = (
            result.returncode == engine_config.secrets_found_exit_code
            or (result.returncode == 1 and is_gitleaks_like)
        )

        if is_secrets_found:
            scan_result = _parse_secrets_result(
                engine_config, report_file, elapsed_ms, original_file_path
            )
            _cache_put(cache, content_hash, engine_config.type, cfg_hash, scan_result)
            return scan_result

        if result.returncode == engine_config.success_exit_code:
            logger.info(
                f"Engine scan complete: engine={engine_config.type} "
                f"duration_ms={elapsed_ms:.1f} findings=0 has_secrets=False"
            )
            clean_result = ScanResult(
                has_secrets=False,
                secrets=[],
                engine=engine_config.type,
                scan_time_ms=elapsed_ms,
            )
            _cache_put(cache, content_hash, engine_config.type, cfg_hash, clean_result)
            return clean_result

        # Unexpected exit code
        stderr_preview = ""
        if result.stderr:
            stderr_lines = [
                line.strip() for line in result.stderr.split("\n") if line.strip()
            ]
            if stderr_lines:
                stderr_preview = stderr_lines[0][:200]

        msg = (
            f"Engine {engine_config.type} returned unexpected exit code "
            f"{result.returncode}: {stderr_preview}"
        )
        if engine_config.version_hint:
            msg += f" ({engine_config.version_hint})"
        logger.warning(msg)
        return ScanResult(
            has_secrets=False,
            secrets=[],
            engine=engine_config.type,
            error=f"Unexpected exit code {result.returncode}: {stderr_preview}",
            scan_time_ms=elapsed_ms,
        )

    except subprocess.TimeoutExpired:
        elapsed_ms = (time.monotonic() - start_time) * 1000
        logger.warning(f"Engine {engine_config.type} timed out after {timeout}s")
        return ScanResult(
            has_secrets=False,
            secrets=[],
            engine=engine_config.type,
            error=f"Timed out after {timeout}s",
            scan_time_ms=elapsed_ms,
        )
    except FileNotFoundError:
        elapsed_ms = (time.monotonic() - start_time) * 1000
        logger.warning(
            f"Engine {engine_config.type} binary not found: {engine_config.binary}"
        )
        return ScanResult(
            has_secrets=False,
            secrets=[],
            engine=engine_config.type,
            error=f"Binary not found: {engine_config.binary}",
            scan_time_ms=elapsed_ms,
        )
    except Exception as e:
        elapsed_ms = (time.monotonic() - start_time) * 1000
        logger.error(f"Engine {engine_config.type} failed: {e}")
        return ScanResult(
            has_secrets=False,
            secrets=[],
            engine=engine_config.type,
            error=str(e),
            scan_time_ms=elapsed_ms,
        )


def run_python_scanner(
    engine_config: EngineConfig,
    source_file: str,
    report_file: str,
    config_path: Optional[str] = None,
    timeout: int = 30,
    cache=None,
    content_hash: Optional[str] = None,
    original_file_path: Optional[str] = None,
) -> ScanResult:
    """
    Run a Python-based scanner in-process and return standardized results.

    Reads content from source_file, calls the scanner's scan() method,
    and converts Finding objects to SecretMatch objects.

    Args:
        engine_config: Engine configuration with python_scanner set
        source_file: Path to the file being scanned
        report_file: Unused for Python scanners (kept for API compatibility)
        config_path: Unused for Python scanners
        timeout: Unused for Python scanners (in-process, no subprocess)
        cache: Optional ScanResultCache for result caching
        content_hash: Optional content hash for cache lookups

    Returns:
        ScanResult with findings from this scanner
    """
    scanner = engine_config.python_scanner
    scanner_name = getattr(scanner, "name", "python")

    cached, cfg_hash = _cache_get(cache, content_hash, engine_config, scanner_name)
    if cached is not None:
        return cached

    start_time = time.monotonic()

    resolved_path = original_file_path or source_file

    try:
        with open(source_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        findings = scanner.scan(content, file_path=resolved_path)
        elapsed_ms = (time.monotonic() - start_time) * 1000

        if not findings:
            logger.info(
                f"Engine scan complete: engine={scanner_name} "
                f"duration_ms={elapsed_ms:.1f} findings=0 has_secrets=False"
            )
            clean_result = ScanResult(
                has_secrets=False,
                secrets=[],
                engine=scanner_name,
                scan_time_ms=elapsed_ms,
            )
            _cache_put(cache, content_hash, scanner_name, cfg_hash, clean_result)
            return clean_result

        secrets = []
        for finding in findings:
            secrets.append(
                SecretMatch(
                    rule_id=finding.rule_id,
                    description=finding.description,
                    file=resolved_path,
                    line_number=finding.line_number,
                    end_line=finding.end_line,
                    start_column=finding.start_column,
                    end_column=finding.end_column,
                    commit=finding.commit,
                    engine=scanner_name,
                    category=finding.category,
                    secret=finding.matched_text,
                )
            )

        logger.info(
            f"Engine scan complete: engine={scanner_name} "
            f"duration_ms={elapsed_ms:.1f} findings={len(secrets)} has_secrets=True"
        )

        result = ScanResult(
            has_secrets=True,
            secrets=secrets,
            engine=scanner_name,
            scan_time_ms=elapsed_ms,
        )
        _cache_put(cache, content_hash, scanner_name, cfg_hash, result)
        return result

    except Exception as e:
        elapsed_ms = (time.monotonic() - start_time) * 1000
        logger.error(f"Python scanner {scanner_name} failed: {e}")
        return ScanResult(
            has_secrets=False,
            secrets=[],
            engine=scanner_name,
            error=str(e),
            scan_time_ms=elapsed_ms,
        )


def _build_scan_result_from_dict(
    engine_type: str,
    result_dict: dict,
    elapsed_ms: float,
    original_file_path: Optional[str] = None,
) -> ScanResult:
    """Convert a standardized findings dict into a ScanResult."""
    if not result_dict or not result_dict.get("has_secrets"):
        return ScanResult(
            has_secrets=False,
            secrets=[],
            engine=engine_type,
            scan_time_ms=elapsed_ms,
        )
    secrets = []
    for finding in result_dict.get("findings", []):
        secrets.append(
            SecretMatch(
                rule_id=finding.get("rule_id", "unknown"),
                description=finding.get("description", "Secret detected"),
                file=original_file_path or finding.get("file", "unknown"),
                line_number=finding.get("line_number", 0),
                end_line=finding.get("end_line"),
                start_column=finding.get("start_column"),
                end_column=finding.get("end_column"),
                commit=finding.get("commit"),
                engine=engine_type,
                verified=finding.get("verified", False),
                secret=finding.get("matched_text"),
            )
        )
    return ScanResult(
        has_secrets=True,
        secrets=secrets,
        engine=engine_type,
        scan_time_ms=elapsed_ms,
    )


def run_engine(
    engine_config: EngineConfig,
    source_file: str,
    report_file: str,
    config_path: Optional[str] = None,
    timeout: int = 30,
    cache=None,
    content_hash: Optional[str] = None,
    original_file_path: Optional[str] = None,
) -> ScanResult:
    """
    Run a scanner engine, dispatching to the correct executor.

    Routes to:
    1. run_python_scanner() for Python-based scanners
    2. Listen mode for engines that support it when the daemon is running (#1590)
    3. run_single_engine() for subprocess-based scanners (default)

    Args:
        engine_config: Engine configuration
        source_file: Path to the file being scanned
        report_file: Path for scanner output report
        config_path: Optional path to scanner configuration file
        timeout: Subprocess timeout in seconds (ignored for Python scanners)
        cache: Optional ScanResultCache for result caching
        content_hash: Optional content hash for cache lookups

    Returns:
        ScanResult with findings from this engine
    """
    if engine_config.python_scanner is not None:
        return run_python_scanner(
            engine_config,
            source_file,
            report_file,
            config_path,
            timeout,
            cache,
            content_hash,
            original_file_path=original_file_path,
        )

    # Try listen mode when the engine supports it and daemon is running (#1590)
    if engine_config.supports_listen_mode:
        cached, cfg_hash = _cache_get(
            cache, content_hash, engine_config, engine_config.type
        )
        if cached is not None:
            return cached
        try:
            daemon_state = _get_daemon_state()
            if daemon_state is not None:
                start = time.monotonic()
                mgr = daemon_state.get_listen_manager()
                result_dict = mgr.scan(engine_config.binary, source_file, config_path)
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.info(
                    "%s listen mode scan: %.1fms, findings=%d",
                    engine_config.type,
                    elapsed_ms,
                    result_dict.get("total_findings", 0),
                )
                result = _build_scan_result_from_dict(
                    engine_config.type, result_dict, elapsed_ms, original_file_path
                )
                _cache_put(cache, content_hash, engine_config.type, cfg_hash, result)
                return result
        except (RuntimeError, OSError, ValueError) as exc:
            logger.warning("Listen mode failed, falling back to subprocess: %s", exc)

    return run_single_engine(
        engine_config,
        source_file,
        report_file,
        config_path,
        timeout,
        cache,
        content_hash,
        original_file_path=original_file_path,
    )


def _parse_secrets_result(
    engine_config: EngineConfig,
    report_file: str,
    elapsed_ms: float,
    original_file_path: Optional[str] = None,
) -> ScanResult:
    """Parse scanner output into ScanResult with SecretMatch objects."""
    try:
        parser = get_parser(engine_config.output_parser)
        parsed = parser.parse(report_file)

        result = _build_scan_result_from_dict(
            engine_config.type, parsed, elapsed_ms, original_file_path
        )
        extra = ""
        if not result.has_secrets:
            extra = " (exit code indicated secrets but parser found none)"
        logger.info(
            f"Engine scan complete: engine={engine_config.type} "
            f"duration_ms={elapsed_ms:.1f} "
            f"findings={len(result.secrets)} "
            f"has_secrets={result.has_secrets}{extra}"
        )
        return result

    except Exception as e:
        logger.error(f"Failed to parse {engine_config.type} output: {e}")
        return ScanResult(
            has_secrets=True,
            secrets=[
                SecretMatch(
                    rule_id="parse-error",
                    description=f"Scanner detected secrets but output parsing failed: {e}",
                    file="unknown",
                    line_number=0,
                    engine=engine_config.type,
                )
            ],
            engine=engine_config.type,
            error=f"Parse error: {e}",
            scan_time_ms=elapsed_ms,
        )
