"""
Scanner engine configuration and command building.

Provides flexible support for multiple secret scanner engines:
- Gitleaks (industry standard)
- BetterLeaks (faster, by original Gitleaks maintainers)
- LeakTK (auto-pattern management)
- Custom scanners

Supports automatic fallback and configuration-driven selection.
"""

import copy
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Any, Optional

logger = logging.getLogger(__name__)


class _PatternServerUnset:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __deepcopy__(self, memo):
        return self

    def __copy__(self):
        return self

    def __repr__(self):
        return "PATTERN_SERVER_UNSET"


PATTERN_SERVER_UNSET = _PatternServerUnset()


@dataclass
class EngineConfig:
    """
    Configuration for a scanner engine.

    Attributes:
        type: Engine type identifier (e.g., 'gitleaks', 'betterleaks', 'leaktk', 'python')
        binary: Binary name or path for the scanner (use "__python__" for Python scanners)
        command_template: Command template with placeholders for building commands
        config_flag: Optional flags for specifying config file
        extra_flags: Optional additional command-line flags
        success_exit_code: Exit code indicating no secrets found
        secrets_found_exit_code: Exit code indicating secrets were detected
        output_parser: Parser type to use for output ('gitleaks' or 'leaktk')
        ignore_files: Per-engine glob patterns for files to skip scanning
        pattern_server: Per-engine pattern server configuration override
        file_patterns: File extensions this engine should handle for file type routing
        python_scanner: Instantiated Python Scanner object (for type="python" engines)
    """

    type: str
    binary: str
    command_template: List[str]
    config_flag: Optional[List[str]] = None
    extra_flags: Optional[List[str]] = None
    success_exit_code: int = 0
    secrets_found_exit_code: int = 42
    output_parser: str = "gitleaks"
    ignore_files: Optional[List[str]] = None
    pattern_server: Any = field(default_factory=lambda: PATTERN_SERVER_UNSET)
    file_patterns: Optional[List[str]] = None
    requires_consent: bool = False
    api_key_env: Optional[str] = None
    python_scanner: Optional[Any] = None
    supports_listen_mode: bool = False
    version_hint: Optional[str] = None


# Built-in engine presets
ENGINE_PRESETS = {
    "gitleaks": EngineConfig(
        type="gitleaks",
        binary="gitleaks",
        command_template=[
            "{binary}",
            "detect",
            "--no-git",
            "--verbose",
            "--redact=100",
            "--report-format",
            "json",
            "--report-path",
            "{report_file}",
            "--exit-code",
            "42",
            "--source",
            "{source_file}",
        ],
        config_flag=["--config", "{config_path}"],
        output_parser="gitleaks",
        success_exit_code=0,
        secrets_found_exit_code=42,
    ),
    "betterleaks": EngineConfig(
        type="betterleaks",
        binary="betterleaks",
        command_template=[
            "{binary}",
            "dir",
            "--verbose",
            "--redact=100",
            "--report-format",
            "json",
            "--report-path",
            "{report_file}",
            "--exit-code",
            "42",
            "--validation=false",
            "{source_file}",
        ],
        config_flag=["--config", "{config_path}"],
        output_parser="gitleaks",  # Same format as gitleaks
        success_exit_code=0,
        secrets_found_exit_code=42,
    ),
    "leaktk": EngineConfig(
        type="leaktk",
        binary="leaktk",
        command_template=[
            "{binary}",
            "scan",
            "--kind",
            "Files",
            "--format",
            "json",
            "{source_file}",
        ],
        config_flag=None,  # LeakTK auto-manages patterns
        output_parser="leaktk",  # v0.3.x writes JSON to stdout
        success_exit_code=0,
        secrets_found_exit_code=1,
        supports_listen_mode=True,
        version_hint="leaktk >= 0.3.0 required; run 'ai-guardian scanner install leaktk' to upgrade",
    ),
    "trufflehog": EngineConfig(
        type="trufflehog",
        binary="trufflehog",
        command_template=[
            "{binary}",
            "filesystem",
            "{source_file}",
            "--json",
            "--no-verification",
            "--no-update",
        ],
        config_flag=None,  # TruffleHog uses built-in detectors
        output_parser="trufflehog",
        success_exit_code=0,
        secrets_found_exit_code=183,  # TruffleHog exits with 183 when secrets found
    ),
    "detect-secrets": EngineConfig(
        type="detect-secrets",
        binary="detect-secrets",
        command_template=["{binary}", "scan", "{source_file}"],
        config_flag=None,
        output_parser="detect-secrets",
        success_exit_code=0,
        secrets_found_exit_code=1,
    ),
    "secretlint": EngineConfig(
        type="secretlint",
        binary="secretlint",
        command_template=["{binary}", "{source_file}", "--format", "json"],
        config_flag=["--secretlintrc", "{config_path}"],
        output_parser="secretlint",
        success_exit_code=0,
        secrets_found_exit_code=1,
    ),
    "gitguardian": EngineConfig(
        type="gitguardian",
        binary="ggshield",
        command_template=[
            "{binary}",
            "secret",
            "scan",
            "path",
            "{source_file}",
            "--json",
            "--exit-zero",
        ],
        config_flag=None,
        output_parser="gitguardian",
        success_exit_code=0,
        secrets_found_exit_code=1,
        requires_consent=True,
        api_key_env="GITGUARDIAN_API_KEY",
    ),
}

# Built-in Python scanner presets (no binary required)
_PYTHON_SCANNER_PRESETS = {"toml-patterns"}


def _build_python_preset(
    preset_name: str,
    scanner_config: Optional[dict] = None,
    parent_config: Optional[dict] = None,
) -> Optional[EngineConfig]:
    """Build an EngineConfig for a built-in Python scanner preset.

    Args:
        preset_name: Name of the preset (e.g. "toml-patterns").
        scanner_config: Per-engine scanner configuration overrides.
        parent_config: Top-level secret_scanning config — used to pass
            ``allowlist_patterns`` and ``ignore_files`` to the scanner
            when not set in *scanner_config*.
    """
    if preset_name == "toml-patterns":
        try:
            from ai_guardian.scanners.toml_patterns import TomlPatternsScanner

            scanner = TomlPatternsScanner()
            effective_config = dict(scanner_config) if scanner_config else {}
            if parent_config:
                for key in ("allowlist_patterns", "ignore_files"):
                    if key not in effective_config and key in parent_config:
                        effective_config[key] = parent_config[key]
            if effective_config:
                scanner.configure(effective_config)
            return EngineConfig(
                type="python",
                binary="__python__",
                command_template=[],
                python_scanner=scanner,
            )
        except Exception as e:
            logger.warning(f"Failed to load toml-patterns scanner: {e}")
            return None
    logger.warning(f"Unknown Python scanner preset: {preset_name}")
    return None


def _build_engine_config(
    engine_spec: Any,
    parent_config: Optional[dict] = None,
) -> Optional[EngineConfig]:
    """
    Build an EngineConfig from a specification.

    Args:
        engine_spec: Engine specification — either a string (preset name)
            or a dict (preset with overrides or custom engine)
        parent_config: Top-level secret_scanning config passed to Python
            scanner presets for allowlist/ignore_files support.

    Returns:
        EngineConfig if spec is valid, None otherwise
    """
    if isinstance(engine_spec, str):
        if engine_spec in _PYTHON_SCANNER_PRESETS:
            return _build_python_preset(engine_spec, parent_config=parent_config)
        if engine_spec not in ENGINE_PRESETS:
            logger.warning(f"Unknown engine preset: {engine_spec}")
            return None
        return copy.deepcopy(ENGINE_PRESETS[engine_spec])

    # Dictionary: preset with overrides or custom engine
    engine_type = engine_spec.get("type")
    if engine_type in _PYTHON_SCANNER_PRESETS:
        return _build_python_preset(
            engine_type,
            scanner_config=engine_spec.get("scanner_config"),
            parent_config=parent_config,
        )
    if engine_type in ENGINE_PRESETS:
        engine_config = copy.deepcopy(ENGINE_PRESETS[engine_type])
        if "binary" in engine_spec:
            engine_config.binary = engine_spec["binary"]
        if "extra_flags" in engine_spec:
            engine_config.extra_flags = engine_spec["extra_flags"]
        if "config_flag" in engine_spec:
            engine_config.config_flag = engine_spec["config_flag"]
    elif engine_type == "python":
        try:
            from ai_guardian.scanners.python_loader import load_python_scanner

            scanner = load_python_scanner(engine_spec)
            engine_config = EngineConfig(
                type="python",
                binary="__python__",
                command_template=[],
                python_scanner=scanner,
            )
        except Exception as e:
            logger.warning(f"Failed to load Python scanner: {e}")
            return None
    elif engine_type == "custom":
        engine_config = EngineConfig(
            type="custom",
            binary=engine_spec["binary"],
            command_template=engine_spec["command_template"],
            config_flag=engine_spec.get("config_flag"),
            extra_flags=engine_spec.get("extra_flags"),
            success_exit_code=engine_spec.get("success_exit_code", 0),
            secrets_found_exit_code=engine_spec.get("secrets_found_exit_code", 1),
            output_parser=engine_spec.get("output_format", "gitleaks"),
        )
    else:
        logger.warning(f"Unknown engine type: {engine_type}")
        return None

    # Apply per-engine configuration
    if isinstance(engine_spec, dict):
        if "ignore_files" in engine_spec:
            engine_config.ignore_files = engine_spec["ignore_files"]
        if "pattern_server" in engine_spec:
            engine_config.pattern_server = engine_spec["pattern_server"]
        if "file_patterns" in engine_spec:
            engine_config.file_patterns = engine_spec["file_patterns"]
        if "requires_consent" in engine_spec:
            engine_config.requires_consent = engine_spec["requires_consent"]
        if "api_key_env" in engine_spec:
            engine_config.api_key_env = engine_spec["api_key_env"]

    return engine_config


def check_engine_consent(engine_config: EngineConfig) -> bool:
    """Check if user has consented to cloud engine usage."""
    if not engine_config.requires_consent:
        return True
    from ai_guardian.config.utils import get_config_dir

    consent_file = get_config_dir() / "consent" / f"{engine_config.type}.consent"
    return consent_file.exists()


def grant_engine_consent(engine_type: str) -> None:
    """Record user consent for a cloud engine."""
    from datetime import datetime, timezone
    from ai_guardian.config.utils import get_config_dir

    consent_dir = get_config_dir() / "consent"
    consent_dir.mkdir(parents=True, exist_ok=True)
    consent_file = consent_dir / f"{engine_type}.consent"
    consent_file.write_text(
        f"Consented to use {engine_type} cloud scanning service.\n"
        f"Content will be sent to external API for analysis.\n"
        f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
    )


def revoke_engine_consent(engine_type: str) -> bool:
    """Revoke user consent for a cloud engine. Returns True if file existed."""
    from ai_guardian.config.utils import get_config_dir

    consent_file = get_config_dir() / "consent" / f"{engine_type}.consent"
    if consent_file.exists():
        consent_file.unlink()
        return True
    return False


def select_engine(
    engines_config: List[Any],
    parent_config: Optional[dict] = None,
) -> EngineConfig:
    """
    Select first available engine from configuration list.

    Tries engines in order, returning the first one whose binary is found
    in the system PATH.

    Args:
        engines_config: List of engine specifications. Each can be:
            - String: name of built-in preset (e.g., "betterleaks")
            - Dict: preset with overrides or custom engine definition
        parent_config: Top-level secret_scanning config passed to Python
            scanner presets for allowlist/ignore_files support.

    Returns:
        EngineConfig: First available engine configuration

    Raises:
        RuntimeError: If no engine is available

    Example:
        >>> config = select_engine(["betterleaks", "gitleaks"])
        >>> print(config.type)
        'betterleaks'  # or 'gitleaks' if betterleaks not installed
    """
    for engine_spec in engines_config:
        engine_config = _build_engine_config(engine_spec, parent_config=parent_config)
        if engine_config is None:
            continue

        if not check_engine_consent(engine_config):
            logger.warning(
                f"Scanner '{engine_config.type}' requires consent. "
                f"Run: ai-guardian engine consent {engine_config.type}"
            )
            continue

        if engine_config.python_scanner is not None:
            logger.debug(
                f"Selected Python scanner: {engine_config.python_scanner.name}"
            )
            return engine_config
        elif shutil.which(engine_config.binary):
            logger.debug(f"Selected scanner engine: {engine_config.type}")
            return engine_config
        else:
            logger.warning(
                f"Scanner '{engine_config.type}' (binary: {engine_config.binary}) "
                f"not available, trying next scanner in list"
            )

    raise RuntimeError(
        "No secret scanner found. Install one of:\n"
        "  • Gitleaks: brew install gitleaks\n"
        "  • BetterLeaks: brew install betterleaks\n"
        "  • LeakTK: brew install leaktk/tap/leaktk"
    )


def select_all_engines(
    engines_config: List[Any],
    parent_config: Optional[dict] = None,
) -> List[EngineConfig]:
    """
    Select all available engines from configuration list.

    Unlike select_engine() which returns only the first available,
    this returns ALL available engines for multi-engine strategies
    (any-match, consensus).

    Args:
        engines_config: List of engine specifications
        parent_config: Top-level secret_scanning config passed to Python
            scanner presets for allowlist/ignore_files support.

    Returns:
        List of available EngineConfig objects

    Raises:
        RuntimeError: If no engines are available
    """
    available = []
    for engine_spec in engines_config:
        engine_config = _build_engine_config(engine_spec, parent_config=parent_config)
        if engine_config is None:
            continue

        if not check_engine_consent(engine_config):
            logger.warning(f"Scanner '{engine_config.type}' requires consent, skipping")
            continue

        if engine_config.python_scanner is not None:
            logger.debug(
                f"Found available Python scanner: {engine_config.python_scanner.name}"
            )
            available.append(engine_config)
        elif shutil.which(engine_config.binary):
            logger.debug(f"Found available scanner engine: {engine_config.type}")
            available.append(engine_config)
        else:
            logger.warning(
                f"Scanner '{engine_config.type}' (binary: {engine_config.binary}) "
                f"not available, skipping"
            )

    if not available:
        raise RuntimeError(
            "No secret scanner found. Install one of:\n"
            "  • Gitleaks: brew install gitleaks\n"
            "  • BetterLeaks: brew install betterleaks\n"
            "  • LeakTK: brew install leaktk/tap/leaktk"
        )

    return available


def build_scanner_command(
    engine_config: EngineConfig,
    source_file: str,
    report_file: str,
    config_path: Optional[str] = None,
) -> List[str]:
    """
    Build scanner command from engine configuration.

    Replaces placeholders in command template:
    - {binary} -> engine_config.binary
    - {source_file} -> source_file
    - {report_file} -> report_file
    - {config_path} -> config_path (if provided)

    Args:
        engine_config: Engine configuration
        source_file: Path to file being scanned
        report_file: Path for output report
        config_path: Optional path to configuration file

    Returns:
        List of command arguments ready for subprocess.run()

    Example:
        >>> config = ENGINE_PRESETS["gitleaks"]
        >>> cmd = build_scanner_command(config, "/tmp/test", "/tmp/report.json")
        >>> print(cmd[0])
        'gitleaks'
    """
    cmd = []

    # Process command template
    for part in engine_config.command_template:
        part = part.replace("{binary}", engine_config.binary)
        part = part.replace("{source_file}", source_file)
        part = part.replace("{report_file}", report_file)
        if "{config_path}" in part and config_path:
            part = part.replace("{config_path}", config_path)
        cmd.append(part)

    # Add config flag if needed
    if config_path and engine_config.config_flag:
        for flag in engine_config.config_flag:
            flag = flag.replace("{config_path}", config_path)
            cmd.append(flag)

    # Add extra flags
    if engine_config.extra_flags:
        cmd.extend(engine_config.extra_flags)

    return cmd


_CONFIG_COMPATIBLE_ENGINES = frozenset(("gitleaks",))


def resolve_engine_config_path(
    engine_config: EngineConfig, global_config_path: Optional[str] = None
) -> Optional[str]:
    """
    Resolve the effective config_path for an engine, considering per-engine
    pattern_server overrides.

    Priority:
      1. Per-engine pattern_server explicitly set to null → None (use built-in rules)
      2. Per-engine pattern_server with URL → fetch engine-specific patterns
      3. No per-engine override → use global_config_path (for compatible engines)

    Args:
        engine_config: Engine configuration (may have per-engine pattern_server)
        global_config_path: Global pattern server config path (from top-level config)

    Returns:
        Resolved config_path string, or None
    """
    if engine_config.pattern_server is not PATTERN_SERVER_UNSET:
        if engine_config.pattern_server is None:
            return None

        ps_config = engine_config.pattern_server
        if isinstance(ps_config, dict) and ps_config.get("url"):
            try:
                from ai_guardian.patterns.server import PatternServerClient

                client = PatternServerClient(ps_config)
                path = client.get_patterns_path()
                if path:
                    return str(Path(path).absolute())
            except Exception as e:
                logger.warning(
                    f"Per-engine pattern server failed for {engine_config.type}: {e}"
                )
            return None

        return None

    if not global_config_path:
        return None

    if engine_config.type in _CONFIG_COMPATIBLE_ENGINES and engine_config.config_flag:
        return str(Path(global_config_path).absolute())

    return None
