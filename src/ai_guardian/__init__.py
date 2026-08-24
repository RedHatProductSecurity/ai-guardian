#!/usr/bin/env python3
"""
AI IDE Security Hook

AI Guardian provides multi-layered protection for AI IDE interactions:
- Directory blocking with .ai-read-deny markers
- Secret scanning using Gitleaks
- Multi-IDE support (Claude Code, Cursor, VS Code Claude)

Automatically detects IDE type and uses appropriate response format.
"""

__version__ = "1.17.0"

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# Configure logging - will be disabled for Cursor hooks
# Custom log record factory to add version to all log records
_old_factory = logging.getLogRecordFactory()


def _record_factory(*args, **kwargs):
    """Custom log record factory that injects version into all log records."""
    record = _old_factory(*args, **kwargs)
    record.version = __version__
    return record


logging.setLogRecordFactory(_record_factory)

# Set up file handler with rotation
from ai_guardian.config.utils import get_state_dir, migrate_state_files

migrate_state_files()
_log_file = get_state_dir() / "ai-guardian.log"
_log_file.parent.mkdir(parents=True, exist_ok=True)

_file_handler = RotatingFileHandler(
    _log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"  # 5 MB
)
_file_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s - v%(version)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)

# Suppress stderr output when --json is requested or running Console TUI (keep file logging)
_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setFormatter(logging.Formatter("%(message)s"))
_is_tui_mode = any(cmd in sys.argv for cmd in ("console", "tui"))
if _is_tui_mode:
    _stderr_handler.setLevel(logging.CRITICAL + 1)
elif "--json" in sys.argv:
    _stderr_handler.setLevel(logging.WARNING)

# Configure the ai_guardian logger (not root) so that
# getLogger("ai_guardian").setLevel(WARNING) actually suppresses children.
_pkg_logger = logging.getLogger("ai_guardian")
_env_log_level = os.environ.get("AI_GUARDIAN_LOG_LEVEL", "").upper()
if _env_log_level and hasattr(logging, _env_log_level):
    _pkg_logger.setLevel(getattr(logging, _env_log_level))
elif _pkg_logger.level == logging.NOTSET:
    _pkg_logger.setLevel(logging.INFO)
_pkg_logger.addHandler(_stderr_handler)
_pkg_logger.addHandler(_file_handler)
_pkg_logger.propagate = False

# Global logger instance
logger = _pkg_logger

# Log version at startup (suppress for sanitize/mcp-server/setup --json — stdio must be clean)
_suppress_logging = (
    "sanitize" in sys.argv
    or "mcp-server" in sys.argv
    or ("setup" in sys.argv and "--json" in sys.argv)
)
_scan_quiet = (
    "scan" in sys.argv and "--verbose" not in sys.argv and "-v" not in sys.argv
)
_quiet_stderr = "prompt" in sys.argv or "tray-target-select" in sys.argv
if _quiet_stderr:
    _stderr_handler.setLevel(logging.CRITICAL)
    import platform
elif _scan_quiet:
    import platform
elif not _suppress_logging:
    logger.debug(f"AI Guardian v{__version__} initialized")
    logger.debug(f"Python {sys.version.split()[0]}")
    import platform

    logger.debug(f"Platform: {platform.platform()}")
else:
    import platform

    logging.disable(logging.CRITICAL)


# ---------------------------------------------------------------------------
# Backward-compatible re-exports
#
# All symbols that were previously defined in this file are re-exported from
# their new module homes so that existing imports continue to work.
# ---------------------------------------------------------------------------

# --- response_format.py ---
from ai_guardian.response_format import (  # noqa: F401
    _SECURITY_SYSTEM_MESSAGE,
    IDEType,
    detect_ide_type,
    format_response,
    detect_hook_event,
)

# --- config_loaders.py ---
from ai_guardian.config.loaders import (  # noqa: F401
    _ConfigCacheEntry,
    _caches,
    HAS_AIGUARDIGNORE,
    _merge_aiguardignore,
    _clear_config_cache,
    configure,
    _load_config_file,
    _load_pattern_server_config,
    _load_prompt_injection_config,
    _load_config_scanner_config,
    _load_permissions_config,
    _load_secret_scanning_config,
    _load_secret_redaction_config,
    _load_pii_config,
    _load_transcript_scanning_config,
    _load_annotations_config,
    _load_security_instructions_config,
    _get_on_scan_error_action,
)

# --- hook_processing.py ---
from ai_guardian.hook_processing import (  # noqa: F401
    _is_path_excluded,
    _check_directory_rules,
    check_directory_denied,
    extract_tool_result,
    _should_skip_pii_scan,
    _build_directory_denied_message,
    extract_file_content_from_tool,
    _scan_for_pii,
    _extract_block_reason,
    _is_ai_guardian_test_file,
    _annotation_hint,
    _extract_context_snippet,
    _log_directory_blocking_violation,
    inject_security_only,
    process_hook_data,
    process_hook_input,
    # HAS_* flags and conditionally-imported names
    HAS_GITLEAKS_CONFIG,
    HAS_TOOL_POLICY,
    HAS_PATTERN_SERVER,
    HAS_PROMPT_INJECTION,
    HAS_CONFIG_SCANNER,
    HAS_VIOLATION_LOGGER,
    HAS_SCANNER_ENGINE,
    HAS_ANNOTATIONS,
)

# --- scanners.secret_scanning ---
from ai_guardian.scanners.secret_scanning import (  # noqa: F401
    _log_secret_detection_violation,
    _count_gitleaks_patterns,
    _describe_patterns,
    check_secrets,
)

check_secrets_with_gitleaks = check_secrets

# --- scanners.transcript ---
from ai_guardian.scanners.transcript import (  # noqa: F401
    _advance_transcript_position,
    _get_transcript_path,
    _load_transcript_positions,
    _save_transcript_positions,
    _load_seen_findings,
    _save_seen_findings,
    _finding_fingerprint,
    _extract_secret_type_from_error,
    _extract_text_from_transcript_line,
    scan_transcript_incremental,
    _scan_transcript_text,
    scan_aiderdesk_transcript_incremental,
    scan_openclaw_transcript_incremental,
    scan_opencode_transcript_incremental,
    _log_transcript_violation,
)

# --- cli_handlers.py ---
from ai_guardian.cli_handlers import (  # noqa: F401
    _handle_violations_command,
    _get_daemon_mode,
    _get_client_timeout,
    _set_daemon_mode_in_config,
    _handle_daemon_command,
)

# --- sdk.py ---
from ai_guardian.sdk import (  # noqa: F401
    CheckResult,
    SecurityViolation,
    monitor,
)

# --- integrations ---
from ai_guardian.integrations import guarded  # noqa: F401

# --- cli.py ---
from ai_guardian.cli import main  # noqa: F401
