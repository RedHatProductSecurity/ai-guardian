"""
Engine Tester — test strings against individual scanner engines.

Provides functions to run a test string through one or all installed
scanner engines and return structured results.  Used by both the CLI
(``ai-guardian engine-test``) and the Console Engine Tester panel.
"""

import json
import logging
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from ai_guardian.scanners.engine_builder import (
    ENGINE_PRESETS,
    _PYTHON_SCANNER_PRESETS,
    _build_engine_config,
    resolve_engine_config_path,
)
from ai_guardian.scanners.executor import run_engine
from ai_guardian.scanners.strategies import SecretMatch

logger = logging.getLogger(__name__)


@dataclass
class EngineTestResult:
    """Result of testing a string against one scanner engine."""

    engine: str
    found: bool
    secrets: List[SecretMatch] = field(default_factory=list)
    scan_time_ms: float = 0.0
    error: Optional[str] = None
    scan_mode: str = "subprocess"


def get_available_engines() -> List[str]:
    """Return engine names from the user's config, plus the default.

    Reads ``secret_scanning.engines`` from ``ai-guardian.json``.  Each
    entry can be a plain string (``"gitleaks"``) or a dict with a
    ``type`` key.  The default engine (``"gitleaks"``) is appended if
    not already present so there is always at least one entry.
    """
    try:
        from ai_guardian import _load_secret_scanning_config

        scanner_config, _ = _load_secret_scanning_config()
        raw = (
            scanner_config.get("engines", ["gitleaks"])
            if scanner_config
            else ["gitleaks"]
        )
    except Exception:
        raw = ["gitleaks"]

    seen: set = set()
    names: List[str] = []
    for entry in raw:
        name = entry.get("type") if isinstance(entry, dict) else str(entry)
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    if "gitleaks" not in seen:
        names.append("gitleaks")

    return names


def _try_daemon_engine_test(engine_name, text, use_pattern_server):
    """Try to route an engine test through a running daemon.

    When the daemon is running, scanning inside its process benefits
    from listen mode (persistent scanner subprocess).  Returns an
    ``EngineTestResult`` on success, or ``None`` to fall back to the
    local subprocess path.
    """
    from ai_guardian.daemon import get_daemon_state

    if get_daemon_state() is not None:
        return None

    try:
        from ai_guardian.daemon.client import is_daemon_running, send_engine_test

        if not is_daemon_running():
            return None

        result_dict = send_engine_test(engine_name, text, use_pattern_server)
        if result_dict is None or result_dict.get("error") is not None:
            return None

        secrets = [
            SecretMatch(**{k: v for k, v in s.items() if k != "secret"})
            for s in result_dict.get("secrets", [])
        ]
        return EngineTestResult(
            engine=result_dict.get("engine", engine_name),
            found=result_dict.get("found", False),
            secrets=secrets,
            scan_time_ms=result_dict.get("scan_time_ms", 0.0),
            error=result_dict.get("error"),
            scan_mode=result_dict.get("scan_mode", "daemon"),
        )
    except Exception:
        return None


def test_engine(
    engine_name: str,
    text: str,
    use_pattern_server: bool = False,
) -> EngineTestResult:
    """Test *text* against a single scanner engine.

    Args:
        engine_name: Engine preset name (e.g. ``"gitleaks"``).
        text: The string to scan for secrets.
        use_pattern_server: When ``True``, resolve the pattern-server
            config path for engines that support it.

    Returns:
        An :class:`EngineTestResult` with findings.
    """
    if engine_name not in ENGINE_PRESETS and engine_name not in _PYTHON_SCANNER_PRESETS:
        return EngineTestResult(
            engine=engine_name,
            found=False,
            error=f"Unknown engine: {engine_name}",
        )

    daemon_result = _try_daemon_engine_test(engine_name, text, use_pattern_server)
    if daemon_result is not None:
        return daemon_result

    engine_config = _build_engine_config(engine_name)
    if engine_config is None:
        return EngineTestResult(
            engine=engine_name,
            found=False,
            error=f"Failed to build config for engine: {engine_name}",
        )

    config_path: Optional[str] = None
    if use_pattern_server:
        try:
            from ai_guardian import _load_pattern_server_config

            pattern_config = _load_pattern_server_config()
            if pattern_config and isinstance(pattern_config, dict):
                from ai_guardian.patterns.server import PatternServerClient

                client = PatternServerClient(pattern_config)
                global_path = client.get_patterns_path()
            else:
                global_path = None
            config_path = resolve_engine_config_path(engine_config, global_path)
        except Exception as exc:
            logger.warning("Pattern server resolution failed: %s", exc)

    with tempfile.TemporaryDirectory(prefix="aiguardian_engtest_") as tmpdir:
        source_file = str(Path(tmpdir) / "test_input.txt")
        report_file = str(Path(tmpdir) / "report.json")

        Path(source_file).write_text(text, encoding="utf-8")
        Path(report_file).write_text("", encoding="utf-8")

        scan_result = run_engine(
            engine_config=engine_config,
            source_file=source_file,
            report_file=report_file,
            config_path=config_path,
            timeout=30,
        )

    from ai_guardian.daemon import get_daemon_state

    if engine_config.supports_listen_mode and get_daemon_state() is not None:
        scan_mode = "listen"
    else:
        scan_mode = "subprocess"

    return EngineTestResult(
        engine=engine_name,
        found=scan_result.has_secrets,
        secrets=list(scan_result.secrets),
        scan_time_ms=scan_result.scan_time_ms,
        error=scan_result.error,
        scan_mode=scan_mode,
    )


def test_all_engines(
    text: str,
    use_pattern_server: bool = False,
) -> List[EngineTestResult]:
    """Test *text* against every configured scanner engine."""
    engines = get_available_engines()
    if not engines:
        return []
    return [
        test_engine(name, text, use_pattern_server=use_pattern_server)
        for name in engines
    ]


def get_configured_strategy() -> str:
    """Return the execution strategy name from the user's config."""
    try:
        from ai_guardian import _load_secret_scanning_config

        scanner_config, _ = _load_secret_scanning_config()
        if scanner_config:
            return scanner_config.get("execution_strategy", "first-match")
    except Exception:
        pass  # intentionally silent — optional dependency
    return "first-match"


@dataclass
class StrategyVerdict:
    """Combined result from running a strategy across engines."""

    strategy: str
    blocked: bool
    total_engines: int
    engines_with_secrets: int
    consensus_threshold: Optional[int] = None


def apply_strategy(
    strategy_name: str,
    results: List[EngineTestResult],
) -> StrategyVerdict:
    """Apply an execution strategy to a set of per-engine results.

    This does not re-run the scanners — it interprets the existing
    per-engine results as the chosen strategy would.
    """
    engines_with_secrets = sum(1 for r in results if r.found)
    total = len(results)

    if strategy_name == "first-match":
        blocked = any(r.found for r in results)
    elif strategy_name == "any-match":
        blocked = any(r.found for r in results)
    elif strategy_name == "consensus":
        try:
            from ai_guardian import _load_secret_scanning_config

            cfg, _ = _load_secret_scanning_config()
            threshold = (cfg or {}).get("consensus_threshold", 2)
        except Exception:
            threshold = 2
        blocked = engines_with_secrets >= threshold
        return StrategyVerdict(
            strategy=strategy_name,
            blocked=blocked,
            total_engines=total,
            engines_with_secrets=engines_with_secrets,
            consensus_threshold=threshold,
        )
    else:
        blocked = any(r.found for r in results)

    return StrategyVerdict(
        strategy=strategy_name,
        blocked=blocked,
        total_engines=total,
        engines_with_secrets=engines_with_secrets,
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_result(result: EngineTestResult) -> str:
    """Human-readable output for a single engine result."""
    if result.error and not result.found:
        return f"  {result.engine}: ERROR — {result.error}"

    status = (
        f"\033[31mFOUND ({len(result.secrets)} secret"
        f"{'s' if len(result.secrets) != 1 else ''})\033[0m"
        if result.found
        else "\033[32mNOT FOUND\033[0m"
    )
    mode = f" [{result.scan_mode}]" if result.scan_mode != "subprocess" else ""
    lines = [f"  {result.engine}: {status}  ({result.scan_time_ms:.0f}ms{mode})"]

    for secret in result.secrets:
        parts = []
        if secret.rule_id:
            parts.append(f"Rule: {secret.rule_id}")
        parts.append(f"Line: {secret.line_number}")
        if secret.description:
            parts.append(secret.description)
        lines.append(f"    {', '.join(parts)}")

    return "\n".join(lines)


def format_comparison(results: List[EngineTestResult]) -> str:
    """Tabular comparison across multiple engines."""
    if not results:
        return "  No engines available."

    name_w = max(len(r.engine) for r in results)
    name_w = max(name_w, 6)  # minimum "Engine" header width

    header = (
        f"  {'Engine':<{name_w}}  {'Result':<12}  "
        f"{'Secrets':>7}  {'Time':>8}  {'Mode':<10}"
    )
    sep = "  " + "─" * (name_w + 12 + 7 + 8 + 10 + 8)
    lines = [header, sep]

    for r in results:
        if r.error and not r.found:
            status = "ERROR"
        elif r.found:
            status = "FOUND"
        else:
            status = "NOT FOUND"
        lines.append(
            f"  {r.engine:<{name_w}}  {status:<12}  "
            f"{len(r.secrets):>7}  {r.scan_time_ms:>6.0f}ms  {r.scan_mode:<10}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def engine_test_command(args) -> int:
    """CLI handler for ``ai-guardian engine-test``."""
    has_engine = getattr(args, "engine", None)
    has_all = getattr(args, "all_engines", False)
    has_compare = getattr(args, "compare", False)
    use_ps = getattr(args, "pattern_server", False)
    use_json = getattr(args, "json", False)

    if not has_engine and not has_all and not has_compare:
        print(
            "Error: specify --engine NAME, --all, or --compare",
            file=sys.stderr,
        )
        return 2

    if sys.stdin.isatty():
        print(
            "Error: pipe text via stdin, e.g.:\n"
            '  echo "AWS_KEY=AKIAIOSFODNN7EXAMPLE" '
            "| ai-guardian engine-test --engine gitleaks",
            file=sys.stderr,
        )
        return 2

    text = sys.stdin.read()
    if not text.strip():
        print("Error: empty input", file=sys.stderr)
        return 2

    if has_engine:
        result = test_engine(has_engine, text, use_pattern_server=use_ps)
        if use_json:
            print(json.dumps(_result_to_dict(result), indent=2))
        else:
            print(format_result(result))
        return 1 if result.found else 0

    # --all or --compare
    results = test_all_engines(text, use_pattern_server=use_ps)
    if use_json:
        print(json.dumps([_result_to_dict(r) for r in results], indent=2))
    elif has_compare:
        print(format_comparison(results))
    else:
        for r in results:
            print(format_result(r))
    return 1 if any(r.found for r in results) else 0


def _result_to_dict(result: EngineTestResult) -> dict:
    """Serialize an :class:`EngineTestResult` to a plain dict."""
    d = asdict(result)
    for s in d.get("secrets", []):
        s.pop("secret", None)
    return d
