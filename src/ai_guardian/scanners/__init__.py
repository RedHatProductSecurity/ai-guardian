"""
Scanner engine and detection modules.

This package provides:
- Engine infrastructure: engine_builder, output_parsers, strategies, executor, cache
- Detection scanners: prompt_injection, config_scanner, secret_redactor, etc.
- Scanner registry and post-scan filter pipeline

NOTE: Two different ScanResult classes coexist in this package:
- scanners.strategies.ScanResult (engine-level execution result)
- scanners.scan_result.ScanResult (detection-level universal result)
Only the engine-level ScanResult is re-exported from this __init__.py.
Import the detection-level one explicitly: from ai_guardian.scanners.scan_result import ScanResult
"""

from ai_guardian.scanners.engine_builder import (
    EngineConfig,
    ENGINE_PRESETS,
    select_engine,
    select_all_engines,
    build_scanner_command,
    check_engine_consent,
    grant_engine_consent,
    revoke_engine_consent,
)
from ai_guardian.scanners.output_parsers import (
    ScannerOutputParser,
    SecretlintOutputParser,
    GitGuardianOutputParser,
    get_parser,
    OUTPUT_PARSERS,
)
from ai_guardian.scanners.strategies import (
    ExecutionStrategy,
    FirstMatchStrategy,
    AnyMatchStrategy,
    ConsensusStrategy,
    SecretMatch,
    ScanResult,
    EXECUTION_STRATEGIES,
    get_strategy,
)
from ai_guardian.scanners.executor import (
    run_single_engine,
    run_python_scanner,
    run_engine,
)
from ai_guardian.scanners.cache import ScanResultCache, FileStateTracker
from ai_guardian.scanners.audit import ScanAuditLogger
from ai_guardian.scanners.compliance import ComplianceReporter
from ai_guardian.scanners.remote_config import (
    fetch_remote_engine_config,
    merge_engine_configs,
)
from ai_guardian.scanners.sdk import Scanner, Finding
from ai_guardian.scanners.python_loader import (
    load_python_scanner,
    load_from_module,
    load_from_file,
    discover_entry_points,
    discover_scanner_directory,
)
from ai_guardian.scanners.secret_validator import (
    SecretValidator,
    ValidationStatus,
    ValidationResult,
)
from ai_guardian.scanners.code_inspection import (
    ASTInspector,
    AstCodeInspector,
    AstInspector,
    CodeInspectionFinding,
    CodeInspectionManager,
    CodeInspectionResult,
    CodeInspector,
    CodeInspectorManager,
    CodeInspectorTimeoutError,
    CodeInspectorUnavailableError,
    register_code_inspector,
)

__all__ = [
    "EngineConfig",
    "ENGINE_PRESETS",
    "select_engine",
    "select_all_engines",
    "build_scanner_command",
    "check_engine_consent",
    "grant_engine_consent",
    "revoke_engine_consent",
    "ScannerOutputParser",
    "SecretlintOutputParser",
    "GitGuardianOutputParser",
    "get_parser",
    "OUTPUT_PARSERS",
    "ExecutionStrategy",
    "FirstMatchStrategy",
    "AnyMatchStrategy",
    "ConsensusStrategy",
    "SecretMatch",
    "ScanResult",
    "EXECUTION_STRATEGIES",
    "get_strategy",
    "run_single_engine",
    "run_python_scanner",
    "run_engine",
    "ScanResultCache",
    "FileStateTracker",
    "ScanAuditLogger",
    "ComplianceReporter",
    "fetch_remote_engine_config",
    "merge_engine_configs",
    "Scanner",
    "Finding",
    "load_python_scanner",
    "load_from_module",
    "load_from_file",
    "discover_entry_points",
    "discover_scanner_directory",
    "SecretValidator",
    "ValidationStatus",
    "ValidationResult",
    "ASTInspector",
    "AstCodeInspector",
    "AstInspector",
    "CodeInspectionFinding",
    "CodeInspectionManager",
    "CodeInspectionResult",
    "CodeInspector",
    "CodeInspectorManager",
    "CodeInspectorTimeoutError",
    "CodeInspectorUnavailableError",
    "register_code_inspector",
]
