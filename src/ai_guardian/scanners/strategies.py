"""
Execution strategies for running multiple secret scanner engines.

Provides different strategies for combining results from multiple scanners:
- FirstMatchStrategy: Use first available engine (default, backward compatible)
- AnyMatchStrategy: Run all engines, block if ANY finds secrets
- ConsensusStrategy: Block only if multiple engines agree (reduces false positives)
"""

import fnmatch
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple, Callable

from ai_guardian.scanners.engine_builder import resolve_engine_config_path


@dataclass
class SecretMatch:
    """Single secret detection result."""

    rule_id: str
    description: str
    file: str
    line_number: int
    end_line: Optional[int] = None
    start_column: Optional[int] = None  # 0-based column
    end_column: Optional[int] = None  # 0-based column
    commit: Optional[str] = None
    secret: Optional[str] = None  # Redacted or None
    engine: str = ""  # Which engine found it
    confidence: float = 1.0  # 0.0-1.0 confidence score
    verified: bool = False  # For engines that support verification
    validation_status: str = (
        "unverified"  # "verified", "inactive", or "unverified" (Issue #971)
    )
    category: Optional[str] = (
        None  # Pattern category for violation routing (Issue #984)
    )


@dataclass
class ScanResult:
    """Result from a secret scanner."""

    has_secrets: bool
    secrets: List[SecretMatch]
    engine: str
    error: Optional[str] = None
    scan_time_ms: float = 0.0


class ExecutionStrategy(ABC):
    """
    Abstract base class for scanner execution strategies.

    A strategy determines how to execute multiple scanner engines
    and how to combine their results.
    """

    @abstractmethod
    def execute(
        self,
        engine_configs: List[Any],
        scanner_fn: Callable,
        source_file: str,
        report_file_prefix: str,
        config_path: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> ScanResult:
        """
        Execute scanners and combine results.

        Args:
            engine_configs: List of EngineConfig objects
            scanner_fn: Callable(engine_config, source_file, report_file, config_path) -> ScanResult
            source_file: Path to file being scanned
            report_file_prefix: Base path for report files (each engine gets a unique suffix)
            config_path: Optional scanner configuration file path
            context: Optional metadata (ide_type, hook_event, original_file_path, etc.)

        Returns:
            ScanResult with combined findings
        """
        pass

    @staticmethod
    def _filter_engines_for_file(engines: List[Any], filename: str) -> List[Any]:
        """
        Filter engines to those whose file_patterns match the filename.

        Engines without file_patterns handle all files.
        Falls back to all engines if no engine matches.
        """
        applicable = []
        for engine in engines:
            if engine.file_patterns is None:
                applicable.append(engine)
            elif any(fnmatch.fnmatch(filename, pat) for pat in engine.file_patterns):
                applicable.append(engine)

        return applicable if applicable else engines


class FirstMatchStrategy(ExecutionStrategy):
    """
    Try scanners in order, use the first one that finds secrets.

    This is the default strategy, maintaining backward compatibility.
    Tries each scanner in order until one finds secrets. If a scanner
    is unavailable (binary not found), it is skipped. If a scanner
    runs but finds no secrets, the next scanner is tried.
    """

    def execute(
        self,
        engine_configs: List[Any],
        scanner_fn: Callable,
        source_file: str,
        report_file_prefix: str,
        config_path: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> ScanResult:
        filename = context.get("filename", "") if context else ""
        orig_path = context.get("original_file_path") if context else None
        engines = self._filter_engines_for_file(engine_configs, filename)

        last_clean_result = None

        for engine_config in engines:
            report_file = f"{report_file_prefix}_{engine_config.type}.json"
            logger.info(f"FirstMatchStrategy: trying engine {engine_config.type}")

            resolved_path = resolve_engine_config_path(engine_config, config_path)
            result = scanner_fn(
                engine_config,
                source_file,
                report_file,
                resolved_path,
                original_file_path=orig_path,
            )

            if result.error and "not found" in (result.error or "").lower():
                logger.warning(f"Engine {engine_config.type} unavailable, trying next")
                continue

            if result.has_secrets:
                logger.info(
                    f"Strategy 'first-match' complete: engine={engine_config.type} "
                    f"duration_ms={result.scan_time_ms:.1f} "
                    f"has_secrets=True"
                )
                return result

            logger.info(
                f"Engine {engine_config.type} found no secrets, trying next engine"
            )
            last_clean_result = result

        if last_clean_result is not None:
            logger.info(
                f"Strategy 'first-match' complete: all engines clean "
                f"(last={last_clean_result.engine})"
            )
            return last_clean_result

        return ScanResult(
            has_secrets=False, secrets=[], engine="none", error="No scanners available"
        )


class AnyMatchStrategy(ExecutionStrategy):
    """
    Run all scanners, block if ANY finds secrets.

    Provides maximum security by requiring all scanners to pass.
    Uses parallel execution for performance.
    """

    def execute(
        self,
        engine_configs: List[Any],
        scanner_fn: Callable,
        source_file: str,
        report_file_prefix: str,
        config_path: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> ScanResult:
        filename = context.get("filename", "") if context else ""
        engines = self._filter_engines_for_file(engine_configs, filename)

        if not engines:
            return ScanResult(
                has_secrets=False,
                secrets=[],
                engine="none",
                error="No scanners available",
            )

        orig_path = context.get("original_file_path") if context else None
        results = self._run_engines_parallel(
            engines,
            scanner_fn,
            source_file,
            report_file_prefix,
            config_path,
            original_file_path=orig_path,
        )

        all_secrets: List[SecretMatch] = []
        engines_run: List[str] = []
        total_time_ms = 0.0

        for result in results:
            if result.error and "not found" in (result.error or "").lower():
                continue
            engines_run.append(result.engine)
            all_secrets.extend(result.secrets)
            total_time_ms = max(total_time_ms, result.scan_time_ms)

        unique_secrets = self._deduplicate(all_secrets)
        engine_label = f"any-match({','.join(engines_run)})"

        logger.info(
            f"Strategy 'any-match' complete: engines_run={len(engines_run)} "
            f"total_duration_ms={total_time_ms:.1f} "
            f"combined_findings={len(all_secrets)} "
            f"deduplicated={len(unique_secrets)} "
            f"has_secrets={len(unique_secrets) > 0}"
        )

        return ScanResult(
            has_secrets=len(unique_secrets) > 0,
            secrets=unique_secrets,
            engine=engine_label,
            scan_time_ms=total_time_ms,
        )

    @staticmethod
    def _run_engines_parallel(
        engines,
        scanner_fn,
        source_file,
        report_file_prefix,
        config_path,
        original_file_path=None,
    ) -> List[ScanResult]:
        max_workers = min(len(engines), 4)
        results: List[ScanResult] = []

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for engine_config in engines:
                report_file = f"{report_file_prefix}_{engine_config.type}.json"
                resolved_path = resolve_engine_config_path(engine_config, config_path)
                future = pool.submit(
                    scanner_fn,
                    engine_config,
                    source_file,
                    report_file,
                    resolved_path,
                    original_file_path=original_file_path,
                )
                futures[future] = engine_config.type

            for future in as_completed(futures):
                engine_type = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error(f"Engine {engine_type} raised exception: {e}")
                    results.append(
                        ScanResult(
                            has_secrets=False,
                            secrets=[],
                            engine=engine_type,
                            error=str(e),
                        )
                    )

        return results

    @staticmethod
    def _deduplicate(secrets: List[SecretMatch]) -> List[SecretMatch]:
        """
        Deduplicate secrets found by multiple engines.

        Keeps the secret with highest confidence when multiple engines
        find the same secret at the same location. Prefers verified secrets.
        """
        if not secrets:
            return []

        grouped: Dict[Tuple[str, int, str], List[SecretMatch]] = defaultdict(list)
        for secret in secrets:
            key = (secret.file, secret.line_number, secret.rule_id)
            grouped[key].append(secret)

        unique: List[SecretMatch] = []
        for group_secrets in grouped.values():
            verified = [s for s in group_secrets if s.verified]
            if verified:
                best = max(verified, key=lambda s: s.confidence)
            else:
                best = max(group_secrets, key=lambda s: s.confidence)

            engines = {s.engine for s in group_secrets if s.engine}
            best.engine = ",".join(sorted(engines))
            unique.append(best)

        return unique


class ConsensusStrategy(ExecutionStrategy):
    """
    Block only if multiple scanners agree (reduces false positives).

    Requires N engines to find the same secret before blocking.
    """

    def __init__(self, threshold: int = 2):
        self.threshold = threshold

    def execute(
        self,
        engine_configs: List[Any],
        scanner_fn: Callable,
        source_file: str,
        report_file_prefix: str,
        config_path: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> ScanResult:
        filename = context.get("filename", "") if context else ""
        engines = self._filter_engines_for_file(engine_configs, filename)

        if not engines:
            return ScanResult(
                has_secrets=False,
                secrets=[],
                engine="none",
                error="No scanners available",
            )

        orig_path = context.get("original_file_path") if context else None
        results = AnyMatchStrategy._run_engines_parallel(
            engines,
            scanner_fn,
            source_file,
            report_file_prefix,
            config_path,
            original_file_path=orig_path,
        )

        all_secrets: List[SecretMatch] = []
        engines_run: List[str] = []
        total_time_ms = 0.0

        for result in results:
            if result.error and "not found" in (result.error or "").lower():
                continue
            engines_run.append(result.engine)
            all_secrets.extend(result.secrets)
            total_time_ms = max(total_time_ms, result.scan_time_ms)

        consensus_secrets = self._find_consensus(all_secrets)
        engine_label = f"consensus({','.join(engines_run)})"

        logger.info(
            f"Strategy 'consensus' complete: engines_run={len(engines_run)} "
            f"threshold={self.threshold} "
            f"total_duration_ms={total_time_ms:.1f} "
            f"combined_findings={len(all_secrets)} "
            f"consensus_findings={len(consensus_secrets)} "
            f"has_secrets={len(consensus_secrets) > 0}"
        )

        return ScanResult(
            has_secrets=len(consensus_secrets) > 0,
            secrets=consensus_secrets,
            engine=engine_label,
            scan_time_ms=total_time_ms,
        )

    def _find_consensus(self, secrets: List[SecretMatch]) -> List[SecretMatch]:
        """
        Find secrets that meet consensus threshold.

        Groups secrets by file and line number, returns only those
        found by at least threshold engines.
        """
        if not secrets:
            return []

        grouped: Dict[Tuple[str, int], List[SecretMatch]] = defaultdict(list)
        for secret in secrets:
            key = (secret.file, secret.line_number)
            grouped[key].append(secret)

        consensus: List[SecretMatch] = []
        for location_secrets in grouped.values():
            engines = {s.engine for s in location_secrets if s.engine}

            if len(engines) >= self.threshold:
                best = max(location_secrets, key=lambda s: s.confidence)
                best.engine = f"{','.join(sorted(engines))} ({len(engines)} engines)"
                consensus.append(best)

        return consensus


# Strategy registry
EXECUTION_STRATEGIES = {
    "first-match": FirstMatchStrategy,
    "any-match": AnyMatchStrategy,
    "consensus": ConsensusStrategy,
}


def get_strategy(strategy_name: str, **kwargs) -> ExecutionStrategy:
    """
    Get execution strategy instance by name.

    Args:
        strategy_name: Name of strategy ('first-match', 'any-match', 'consensus')
        **kwargs: Strategy-specific configuration (e.g., threshold for consensus)

    Returns:
        Strategy instance

    Raises:
        ValueError: If strategy name is unknown
    """
    if strategy_name not in EXECUTION_STRATEGIES:
        raise ValueError(
            f"Unknown strategy: {strategy_name}. "
            f"Available strategies: {', '.join(EXECUTION_STRATEGIES.keys())}"
        )

    strategy_class = EXECUTION_STRATEGIES[strategy_name]
    return strategy_class(**kwargs)
