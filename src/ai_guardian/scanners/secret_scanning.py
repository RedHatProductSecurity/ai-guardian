"""Secret scanning functions extracted from hook_processing.py (Phase 5a, #1491)."""

import fnmatch
import glob
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional

try:
    from ai_guardian.violations.logger import ViolationLogger

    HAS_VIOLATION_LOGGER = True
except ImportError:
    HAS_VIOLATION_LOGGER = False

try:
    from ai_guardian.scanners import gitleaks as _gitleaks_cfg

    HAS_GITLEAKS_CONFIG = True
except ImportError:
    HAS_GITLEAKS_CONFIG = False

try:
    from ai_guardian.patterns.server import PatternServerClient

    HAS_PATTERN_SERVER = True
except ImportError:
    HAS_PATTERN_SERVER = False

try:
    from ai_guardian.scanners.engine_builder import (
        select_engine,
        select_all_engines,
        build_scanner_command,
        resolve_engine_config_path,
        PATTERN_SERVER_UNSET,
    )
    from ai_guardian.scanners.output_parsers import get_parser
    from ai_guardian.scanners.strategies import (
        get_strategy,
        ScanResult as StrategyScanResult,
        SecretMatch,
    )
    from ai_guardian.scanners.executor import run_single_engine, run_engine

    HAS_SCANNER_ENGINE = True
except ImportError:
    HAS_SCANNER_ENGINE = False

try:
    from ai_guardian.scanners.ast_scanner import extract_scannable_content

    HAS_AST_SCANNER = True
except ImportError:
    HAS_AST_SCANNER = False

from ai_guardian.config.loaders import (
    _load_secret_redaction_config,
    _load_pattern_server_config,
    _load_secret_scanning_config,
    _get_on_scan_error_action,
)
from ai_guardian.constants import ActionMode, ViolationType
from ai_guardian.utils.path_matching import match_leading_doublestar_pattern

logger = logging.getLogger(__name__)

DEFAULT_ENGINES = ["toml-patterns", "gitleaks"]

# Keywords used to classify scanner error messages
_AUTH_ERROR_KEYWORDS = frozenset(
    {
        "401",
        "403",
        "unauthorized",
        "authentication",
        "forbidden",
        "authentication failed",
        "bad credentials",
        "invalid token",
        "access denied",
    }
)
_NETWORK_ERROR_KEYWORDS = frozenset(
    {
        "connection",
        "timeout",
        "network",
        "unreachable",
        "refused",
        "dial tcp",
        "no route",
        "no route to host",
    }
)


def _build_secret_extras(details, context, *, file_path=None):
    """Build blocked overrides for secret/finding violations."""
    extras = {}
    if details.get("end_line") and details["end_line"] != details.get("line_number"):
        extras["end_line"] = details["end_line"]
    if details.get("total_findings"):
        extras["total_findings"] = details["total_findings"]
    if details.get("findings"):
        extras["findings"] = details["findings"]
    if details.get("validation"):
        extras["validation"] = details["validation"]
    extras["secret_type"] = details.get("rule_id", "Unknown")
    if context:
        src_cmd = context.get("source_command")
        fp = file_path or ""
        if src_cmd and str(fp).startswith("tool_result:"):
            extras["source_command"] = src_cmd
    return extras


def _build_false_positive_msg(details, *, for_secret=False):
    """Build false-positive suggestion text from scan details."""
    if details.get("end_line") and details["end_line"] != details.get("line_number"):
        line_num = details.get("line_number")
        end_line = details["end_line"]
        return (
            f"Add '# ai-guardian:allow' at the end of line {line_num}, "
            f"or wrap lines {line_num}-{end_line} with "
            f"ai-guardian:begin-allow / ai-guardian:end-allow"
        )
    if for_secret:
        return "Add '# gitleaks:allow' or '# ai-guardian:allow' at the end of the line"
    return "Add '# ai-guardian:allow' at the end of the line"


def _log_secret_detection_violation(
    filename: str,
    context: Optional[Dict] = None,
    secret_details: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    violation_logger=None,
):
    """Log a secret detection violation via unified ``log_violation``."""
    if not HAS_VIOLATION_LOGGER:
        return

    from ai_guardian.scanners.scan_result import ScanResult, generate_violation_id
    from ai_guardian.violations.log_violation import ScanContext, log_violation

    details = secret_details or {}
    ctx = context or {}
    hctx = hook_context or {}
    engine_name = details.get("engine", "Gitleaks")
    file_path = filename if filename != "user_prompt" else None

    result = ScanResult(
        detected=True,
        violation_type=ViolationType.SECRET_DETECTED,
        id=generate_violation_id(),
        severity="critical",
        file_path=file_path,
        line_number=details.get("line_number"),
        start_column=details.get("start_column"),
        end_column=details.get("end_column"),
        error_message=f"{engine_name} detected sensitive information",
    )

    extras = _build_secret_extras(details, context, file_path=file_path)
    from ai_guardian.violations.redact import sanitize_blocked_for_secret

    sanitize_blocked_for_secret(extras)

    log_violation(
        result,
        ScanContext.from_hook_dicts(context, hook_context),
        violation_logger=violation_logger,
        source="prompt" if filename == "user_prompt" else "file",
        blocked_overrides=extras,
        suggestion={
            "action": "review_and_remove_secret",
            "warning": "Secrets should never be committed to code or shared with AI",
            "false_positive": _build_false_positive_msg(details, for_secret=True),
        },
    )


# Category → (ViolationType, reason template, severity)
_CATEGORY_VIOLATION_MAP = {
    "pii": (ViolationType.PII_DETECTED, "PII detected", "high"),
    "prompt_injection": (
        ViolationType.PROMPT_INJECTION,
        "Prompt injection detected",
        "high",
    ),
    "unicode": (ViolationType.PROMPT_INJECTION, "Unicode attack detected", "high"),
    "config_exfil": (
        ViolationType.CONFIG_FILE_EXFIL,
        "Config exfiltration pattern detected",
        "high",
    ),
    "ssrf": (ViolationType.SSRF_BLOCKED, "SSRF pattern detected", "high"),
}


def _log_finding_violation(
    filename: str,
    context: Optional[Dict] = None,
    secret_details: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    violation_logger=None,
):
    """Route a scanner finding to the correct violation type based on category."""
    details = secret_details or {}
    category = details.get("category")

    if category is None or category == "secrets":
        _log_secret_detection_violation(
            filename, context, secret_details, hook_context, violation_logger
        )
        return

    mapping = _CATEGORY_VIOLATION_MAP.get(category)
    if mapping is None:
        _log_secret_detection_violation(
            filename, context, secret_details, hook_context, violation_logger
        )
        return

    if not HAS_VIOLATION_LOGGER:
        return

    from ai_guardian.scanners.scan_result import ScanResult, generate_violation_id
    from ai_guardian.violations.log_violation import ScanContext, log_violation

    vtype, reason_label, severity = mapping
    engine_name = details.get("engine", "toml-patterns")
    rule_id = details.get("rule_id", "Unknown")
    ctx = context or {}
    hctx = hook_context or {}
    file_path = filename if filename != "user_prompt" else None

    result = ScanResult(
        detected=True,
        violation_type=vtype,
        id=generate_violation_id(),
        severity=severity,
        file_path=file_path,
        line_number=details.get("line_number"),
        start_column=details.get("start_column"),
        end_column=details.get("end_column"),
        error_message=f"{engine_name}: {reason_label} ({rule_id})",
    )

    extras = _build_secret_extras(details, context, file_path=file_path)
    from ai_guardian.violations.redact import (
        REDACT_VIOLATION_TYPES,
        sanitize_blocked_for_secret,
    )

    if vtype.value in REDACT_VIOLATION_TYPES:
        sanitize_blocked_for_secret(extras)

    log_violation(
        result,
        ScanContext.from_hook_dicts(context, hook_context),
        violation_logger=violation_logger,
        source="prompt" if filename == "user_prompt" else "file",
        blocked_overrides=extras,
        suggestion={
            "action": "review_finding",
            "false_positive": _build_false_positive_msg(details),
        },
    )


def _count_gitleaks_patterns(config_path):
    """
    Count the number of rules in a Gitleaks TOML configuration file.

    Args:
        config_path: Path to the Gitleaks config file

    Returns:
        int: Number of [[rules]] sections found, or 0 if unable to count
    """
    try:
        if not config_path or not Path(config_path).exists():
            return 0

        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Count [[rules]] sections (each represents one detection rule)
        rule_count = content.count("[[rules]]")
        return rule_count

    except Exception as e:
        logger.debug(f"Error counting patterns in {config_path}: {e}")
        return 0


_CATEGORY_BANNER = {
    "pii": {
        "title": "PII Detected",
        "type_label": "PII Type",
        "why": (
            "Personally identifiable information (PII) must not be exposed to AI\n"
            "assistants or committed to version control."
        ),
        "recommendations": [
            "Redact or mask PII before sharing with AI",
            "Use synthetic/test data instead of real PII",
            "Review scan_pii settings in ai-guardian.json",
        ],
        "footer": "",
        "protection": "PII Scanning",
    },
    "prompt_injection": {
        "title": "Prompt Injection Detected",
        "type_label": "Pattern",
        "why": (
            "Prompt injection patterns can manipulate AI assistant behavior\n"
            "and bypass security controls."
        ),
        "recommendations": [
            "Remove or sanitize the injection pattern",
            "Add to allowlist if this is legitimate documentation",
        ],
        "footer": "",
        "protection": "Prompt Injection Detection",
    },
    "unicode": {
        "title": "Unicode Attack Detected",
        "type_label": "Pattern",
        "why": (
            "Invisible or misleading Unicode characters can be used to obfuscate\n"
            "malicious content and bypass text-based security checks."
        ),
        "recommendations": [
            "Remove invisible/zero-width characters",
            "Replace homoglyphs with ASCII equivalents",
            "Add to allowlist if this is legitimate Unicode content",
        ],
        "footer": "",
        "protection": "Unicode Attack Detection",
    },
    "config_exfil": {
        "title": "Config Exfiltration Detected",
        "type_label": "Pattern",
        "why": (
            "This pattern may exfiltrate configuration data, environment variables,\n"
            "or credentials to external services."
        ),
        "recommendations": [
            "Review the command for unintended data exposure",
            "Avoid piping secrets or env vars to external URLs",
        ],
        "footer": "",
        "protection": "Config Exfiltration Detection",
    },
    "ssrf": {
        "title": "SSRF Pattern Detected",
        "type_label": "Pattern",
        "why": (
            "Server-Side Request Forgery (SSRF) patterns target internal networks,\n"
            "cloud metadata endpoints, or private services."
        ),
        "recommendations": [
            "Avoid requests to internal/private IP ranges",
            "Do not access cloud metadata endpoints",
            "Use allowlisted URLs only",
        ],
        "footer": "",
        "protection": "SSRF Protection",
    },
    "offensive_language": {
        "title": "Offensive Language Detected",
        "type_label": "Category",
        "why": (
            "Offensive, discriminatory, or non-inclusive language in code,\n"
            "comments, or variable names can harm team culture and violate\n"
            "enterprise content policies."
        ),
        "recommendations": [
            "Replace offensive terms with neutral alternatives",
            "Check the 'suggestion' field in the violation for recommended replacements",
            "Use scan_offensive.categories to enable only relevant checks",
            "Add '# ai-guardian:allow' inline to suppress known-safe uses",
        ],
        "footer": "",
        "protection": "Offensive Language Scanning",
    },
}


def _build_secret_detected_message(
    scanner_name,
    secret_details,
    pattern_description,
    protection_label="Secret Scanning",
):
    """Build a category-aware detection error banner."""
    category = secret_details.get("category") if secret_details else None
    banner = _CATEGORY_BANNER.get(category) if category else None

    if banner:
        title = banner["title"]
        type_label = banner["type_label"]
        why_text = banner["why"]
        recommendations = banner["recommendations"]
        footer_text = banner["footer"]
        if protection_label == "Secret Scanning":
            protection_label = banner["protection"]
    else:
        title = "Secret Detected"
        type_label = "Secret Type"
        why_text = (
            "Hard-coded secrets in source code can leak to version control\n"
            "and be accessed by unauthorized users."
        )
        recommendations = [
            "Move secrets to environment variables",
            "Use secret management (AWS Secrets Manager, HashiCorp Vault)",
            "Add to .gitignore if in config file",
            "Never commit secrets to git",
        ]
        footer_text = "⚠️  Secret value NOT shown in this message for security\n"

    error_msg = (
        f"\n{'='*70}\n"
        f"🛡️ {title}\n"
        f"{'='*70}\n\n"
        f"Protection: {protection_label}\n"
    )

    if secret_details:
        from ai_guardian.scanners.secret_types import get_secret_type_display

        display_name = get_secret_type_display(secret_details["rule_id"])
        error_msg += f"{type_label}: {display_name}\n"
        if secret_details.get("line_number"):
            _loc = f"{secret_details['file']}:{secret_details['line_number']}"
            if secret_details.get("start_column") is not None:
                _loc += f":{secret_details['start_column'] + 1}"
            error_msg += f"Location: {_loc}\n"
        else:
            error_msg += f"Location: {secret_details['file']}\n"
    else:
        error_msg += f"{type_label}: (multiple or unknown)\n"

    error_msg += f"Scanner: {scanner_name}\n"
    error_msg += f"Patterns: {pattern_description}\n"

    error_msg += (
        f"\nWhy blocked: {why_text}\n\n"
        f"This operation has been blocked for security.\n"
        f"Please remove the flagged content and try again.\n\n"
        f"DO NOT attempt to bypass this protection.\n\n"
        f"Recommendation:\n"
    )
    for rec in recommendations:
        error_msg += f"  • {rec}\n"
    error_msg += "\n"

    if footer_text:
        error_msg += f"{footer_text}\n"

    if not secret_details and not banner:
        error_msg += (
            "Common secret types:\n"
            "  • API keys and tokens\n"
            "  • Private keys (SSH, RSA, PGP)\n"
            "  • Database credentials\n"
            "  • Cloud provider keys (AWS, GCP, Azure)\n\n"
        )

    error_msg += f"{'='*70}\n"
    return error_msg


def _describe_patterns(
    engine_config, resolved_config_path, config_source, pattern_config
):
    """Return a user-facing description of which patterns a scanner engine uses."""
    engine_type = engine_config.type if engine_config else "gitleaks"

    if (
        HAS_SCANNER_ENGINE
        and engine_config
        and engine_config.pattern_server is not PATTERN_SERVER_UNSET
    ):
        if engine_config.pattern_server is None:
            return f"Built-in {engine_type} rules"
        ps = engine_config.pattern_server
        if isinstance(ps, dict) and ps.get("url"):
            return f"{engine_type} Pattern Server ({ps['url']})"
        return f"Built-in {engine_type} rules"

    if resolved_config_path and config_source == "pattern server" and pattern_config:
        return f"LeakTK Pattern Server ({pattern_config.get('url', 'N/A')})"
    if resolved_config_path and config_source == "project config":
        return f"{resolved_config_path}"

    return f"Built-in {engine_type} rules"


def _apply_secret_validation(
    secret_config: Optional[Dict],
    secrets_info: list,
    content: str,
    context: Optional[Dict] = None,
) -> Optional[Dict]:
    """Apply secret liveness validation if enabled (Issue #971, #983).

    Called after detection + allowlist filtering, before the block decision.
    Validates detected secrets against provider APIs to check if they're
    still active.

    Args:
        secret_config: Secret scanning config dict (may contain validate_secrets, etc.)
        secrets_info: List of secret dicts with at least 'rule_id' and 'line_number'.
                      May also contain 'secret' or 'matched_text'.
        content: Full scanned content (for extracting secret values by line number).
        context: Optional context dict for logging.

    Returns:
        None  — validation disabled or not applicable, no validation field in violation
        dict  — {"skip_block": bool, "validation_info": {"status": ..., "message": ..., "elapsed_ms": ...}}
    """
    if not secret_config or not secret_config.get("validate_secrets", False):
        return None  # Validation not enabled

    if not secrets_info:
        return None

    try:
        from ai_guardian.scanners.secret_validator import (
            SecretValidator,
            ValidationStatus,
        )

        validator = SecretValidator(config=secret_config)
        if not validator.enabled:
            return None

        # Check if any secrets have validators
        has_any_validator = any(
            validator.has_validator(s.get("rule_id", "")) for s in secrets_info
        )
        if not has_any_validator:
            return {
                "skip_block": False,
                "validation_info": {
                    "status": "unverified",
                    "message": "No validator for this rule",
                    "elapsed_ms": 0,
                },
            }

        results = validator.validate_secrets(secrets_info, content)
        active_secrets, inactive_secrets = validator.filter_inactive(
            secrets_info, results
        )

        # Build validation_info from first result (matches primary secret in violation)
        primary_result = results[0] if results else None

        if not active_secrets and inactive_secrets:
            # All secrets are inactive — log and skip blocking
            on_inactive = validator.on_inactive
            for result in results:
                if result.status == ValidationStatus.INACTIVE:
                    if on_inactive == "warn":
                        logger.warning(
                            f"Secret '{result.rule_id}' is inactive (revoked/expired): "
                            f"{result.message} [{result.elapsed_ms:.0f}ms]"
                        )
                    else:
                        logger.info(
                            f"Secret '{result.rule_id}' is inactive: {result.message}"
                        )
            logger.info(
                f"All {len(inactive_secrets)} detected secret(s) validated as inactive — "
                f"skipping block (on_inactive={on_inactive})"
            )
            return {
                "skip_block": True,
                "validation_info": {
                    "status": (
                        primary_result.status.value if primary_result else "inactive"
                    ),
                    "message": primary_result.message if primary_result else "",
                    "elapsed_ms": primary_result.elapsed_ms if primary_result else 0,
                },
            }

        # At least one secret is active or unverified — block
        for result in results:
            if result.status == ValidationStatus.VERIFIED:
                logger.warning(
                    f"Secret '{result.rule_id}' VERIFIED ACTIVE "
                    f"[{result.elapsed_ms:.0f}ms]"
                )
            elif result.status == ValidationStatus.INACTIVE:
                logger.info(
                    f"Secret '{result.rule_id}' inactive but other secrets "
                    f"still active — blocking all"
                )

        # Use first active/verified result for validation_info, fall back to primary
        active_result = next(
            (r for r in results if r.status == ValidationStatus.VERIFIED),
            primary_result,
        )
        return {
            "skip_block": False,
            "validation_info": {
                "status": active_result.status.value if active_result else "unverified",
                "message": active_result.message if active_result else "",
                "elapsed_ms": active_result.elapsed_ms if active_result else 0,
            },
        }

    except ImportError:
        logger.debug("Secret validator module not available — skipping validation")
        return None
    except Exception as e:
        logger.warning(f"Secret validation error (fail-closed): {e}")
        return {
            "skip_block": False,
            "validation_info": {
                "status": "error",
                "message": str(e),
                "elapsed_ms": 0,
            },
        }


def _run_secret_validation(secret_config, secrets_list, content, context):
    """Run secret liveness validation and return (validation_info, should_skip).

    Shared helper for the 4 code paths in check_secrets that
    perform secret validation after detection.
    """
    validation_result = _apply_secret_validation(
        secret_config,
        secrets_list,
        content if isinstance(content, str) else str(content),
        context=context,
    )
    validation_info = (
        validation_result.get("validation_info") if validation_result else None
    )
    should_skip = bool(validation_result and validation_result.get("skip_block"))
    return validation_info, should_skip


_last_secret_matched_text = ""
_last_secret_line_number = None
_last_secret_start_column = None
_last_secret_findings = []


def _extract_matched_text_for_ask(secret_details, content):
    """Extract matched text from secret_details or content for ask-mode display."""
    if not secret_details:
        return ""
    mt = secret_details.get("matched_text")
    if mt:
        return mt.strip()
    line_num = secret_details.get("line_number", 0)
    if line_num > 0 and content:
        lines = (content if isinstance(content, str) else str(content)).splitlines()
        if 0 < line_num <= len(lines):
            return lines[line_num - 1].strip()
    return ""


def check_secrets(
    content,
    filename="temp_file",
    context: Optional[Dict] = None,
    file_path: Optional[str] = None,
    tool_name: Optional[str] = None,
    ignore_files: Optional[list] = None,
    ignore_tools: Optional[list] = None,
    allowlist_patterns: Optional[list] = None,
    secret_config: Optional[Dict] = None,
):
    """
    Check content for secrets using Gitleaks binary.

    Scans content for secrets using the open-source Gitleaks tool.
    Uses in-memory temp files on Linux for better performance.

    Supports optional pattern server integration for enhanced detection patterns.

    Multi-engine support (#91): Supports multiple scanner engines via
    secret_scanning.engines config and execution strategies (first-match,
    any-match, consensus). See docs/MULTI_ENGINE_SUPPORT.md for details.

    Args:
        content: The text content to scan for secrets
        filename: Optional filename for context in error messages
        context: Optional context dict for violation logging (ide_type, hook_event, etc.)
        file_path: Optional file path being scanned (for ignore_files matching)
        tool_name: Optional tool name being used (for ignore_tools matching)
        ignore_files: Optional list of glob patterns for files to skip
        ignore_tools: Optional list of tool name patterns to skip
        allowlist_patterns: Optional list of regex patterns for known-safe values to ignore

    Returns:
        tuple: (has_secrets: bool, error_message: str or None)
            - has_secrets: True if secrets detected, False otherwise
            - error_message: Detailed error if secrets found, None otherwise

    """

    global _last_secret_matched_text, _last_secret_line_number, _last_secret_start_column, _last_secret_findings
    _last_secret_matched_text = ""
    _last_secret_line_number = None
    _last_secret_start_column = None
    _last_secret_findings = []
    try:
        # Check if tool should be ignored
        if ignore_tools and tool_name:
            for pattern in ignore_tools:
                if fnmatch.fnmatch(tool_name, pattern):
                    logger.info(
                        f"Skipping secret scanning for ignored tool: {tool_name}"
                    )
                    return False, None

        # Check if file should be ignored
        if ignore_files and file_path:
            # Expand file path (handle ~)
            abs_file_path = str(Path(file_path).expanduser().absolute())

            for pattern in ignore_files:
                matched = False

                # Handle leading ** patterns (e.g., **/.claude/skills/**)
                if pattern.startswith("**/"):
                    matched = match_leading_doublestar_pattern(abs_file_path, pattern)
                else:
                    # For non-leading-** patterns, use Path.match()
                    file_path_obj = Path(abs_file_path)
                    expanded_pattern = os.path.expanduser(pattern)
                    matched = file_path_obj.match(expanded_pattern)

                if matched:
                    logger.info(
                        f"Skipping secret scanning for ignored file: {file_path}"
                    )
                    return False, None

        # Convert content to string if it's not already
        # Agent tool outputs can be lists, dicts, or other types
        if isinstance(content, list):
            content = "\n".join(str(item) for item in content)
        elif not isinstance(content, str):
            content = str(content)

        # Skip scanning if file is a gitleaks config file (path-based check)
        # This prevents false positives when viewing pattern files
        # Use path-based detection instead of content-based to prevent bypass
        if file_path and file_path.endswith(".gitleaks.toml"):
            logger.debug(f"Skipping scan - file is a gitleaks config: {file_path}")
            return False, None

        # Check project .gitleaks.toml path allowlist (Issue #488)
        _gitleaks_allowlist = None
        if HAS_GITLEAKS_CONFIG:
            _gitleaks_allowlist = _gitleaks_cfg.load_gitleaks_allowlist()
            if _gitleaks_allowlist and file_path:
                if _gitleaks_cfg.should_skip_file(file_path, _gitleaks_allowlist):
                    logger.info(
                        f"Skipping secret scanning for .gitleaks.toml allowlisted path: {file_path}"
                    )
                    return False, None

        # AST-aware scanning: for code files, extract only comments and strings
        if HAS_AST_SCANNER and file_path:
            extracted = extract_scannable_content(content, file_path)
            if extracted is not None:
                content = extracted
                if not content.strip():
                    return False, None

        # Use in-memory filesystem on Linux for better performance
        tmp_base_dir = "/dev/shm" if os.path.exists("/dev/shm") else None

        # Create temporary file with content
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=f"_{filename}",
            prefix="aiguardian_",
            dir=tmp_base_dir,
            delete=False,
        ) as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            tmp_file_path = tmp_file.name

        # Load stopwords + entropy threshold for external scanner filtering (#1245)
        from ai_guardian.patterns.validators import (
            load_stopwords,
            filter_findings_by_stopwords_entropy,
            filter_findings_dicts_by_stopwords_entropy,
            filter_findings_by_hash,
            filter_findings_dicts_by_hash,
        )

        _ext_stopwords = load_stopwords(secret_config)
        _ext_min_entropy = (
            float(secret_config.get("min_entropy", 3.0))
            if secret_config and secret_config.get("min_entropy") is not None
            else 3.0
        )

        # Create report file for JSON output
        report_file = None
        try:
            # Determine which Gitleaks configuration to use
            # Priority order:
            # 1. Pattern Server (if enabled and available) - Enterprise policy
            # 2. Scanner Engines (first available from config) - Falls back automatically
            #    - Engines auto-detect .gitleaks.toml if they support it
            # 3. BLOCK if no scanner available
            gitleaks_config_path = None
            config_source = None
            pattern_server_attempted = False
            pattern_server_url = None

            # Priority 1: Pattern server (if enabled and available)
            if HAS_PATTERN_SERVER:
                pattern_config = _load_pattern_server_config()
                if pattern_config:
                    pattern_server_attempted = True
                    pattern_server_url = pattern_config.get("url")
                    try:
                        pattern_client = PatternServerClient(pattern_config)
                        server_patterns = pattern_client.get_patterns_path()
                        if server_patterns:
                            # SUCCESS: Use pattern server
                            gitleaks_config_path = server_patterns
                            config_source = "pattern server"
                            logger.info(
                                f"Using pattern server config: {server_patterns}"
                            )
                        else:
                            # Pattern server failed - will try scanner engines below
                            logger.warning(
                                f"Pattern server unavailable ({pattern_config.get('url')}), "
                                f"falling back to scanner engines"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Pattern server error, trying scanner engines: {e}"
                        )

            # Priority 2: Scanner Engines (if pattern server not used)
            engine_config = None
            execution_strategy_name = "first-match"
            consensus_threshold = 2
            _all_available_engines = None
            if not gitleaks_config_path and HAS_SCANNER_ENGINE:
                try:
                    scanner_config = (
                        secret_config
                        if secret_config
                        else (_load_secret_scanning_config()[0])
                    )
                    engines_list = (
                        scanner_config.get("engines", DEFAULT_ENGINES)
                        if scanner_config
                        else DEFAULT_ENGINES
                    )
                    execution_strategy_name = (
                        scanner_config.get("execution_strategy", "first-match")
                        if scanner_config
                        else "first-match"
                    )
                    consensus_threshold = (
                        scanner_config.get("consensus_threshold", 2)
                        if scanner_config
                        else 2
                    )

                    # Select first available engine (logs warnings for unavailable ones)
                    engine_config = select_engine(
                        engines_list, parent_config=scanner_config
                    )

                    # For first-match strategy, get all available engines for fallthrough
                    _all_available_engines = None
                    if (
                        execution_strategy_name == "first-match"
                        and len(engines_list) > 1
                    ):
                        try:
                            _all_available_engines = select_all_engines(
                                engines_list, parent_config=scanner_config
                            )
                        except RuntimeError:
                            pass  # Only primary engine available

                    # Log context about why we're using scanner engines
                    if pattern_server_attempted:
                        logger.debug(
                            f"Using {engine_config.type} scanner (pattern server unavailable)"
                        )
                    else:
                        logger.debug(f"Using {engine_config.type} scanner")

                    config_source = f"{engine_config.type} defaults"

                except RuntimeError:
                    # NO SCANNER AVAILABLE - WARN (allow operation to continue)
                    default_scanner = engines_list[0] if engines_list else "gitleaks"
                    if pattern_server_attempted:
                        warning_msg = (
                            f"⚠️  WARNING: No secret scanning available\n\n"
                            f"Pattern server: {pattern_server_url} — unavailable\n"
                            f"Scanner engines: {engines_list} — none installed\n\n"
                            f"Please install a scanner with:\n"
                            f"  ai-guardian scanner install {default_scanner}\n\n"
                            f"Until a scanner is installed, you may leak secrets."
                        )
                    else:
                        warning_msg = (
                            f"⚠️  WARNING: No secret scanning available\n\n"
                            f"No scanner engine is installed.\n"
                            f"Tried engines: {engines_list} — none found\n\n"
                            f"Please install a scanner with:\n"
                            f"  ai-guardian scanner install {default_scanner}\n\n"
                            f"Until a scanner is installed, you may leak secrets."
                        )
                    on_error = _get_on_scan_error_action()
                    if on_error == ActionMode.BLOCK:
                        logger.error(
                            "No scanner available (fail-closed, on_scan_error=block)"
                        )
                        return (
                            True,
                            warning_msg
                            + "\n\nOperation BLOCKED (on_scan_error=block).",
                        )
                    logger.warning("No scanner available - warning user")
                    return False, warning_msg

            # Validate pattern completeness if using pattern server
            if config_source == "pattern server" and gitleaks_config_path:
                pattern_count = _count_gitleaks_patterns(gitleaks_config_path)
                if pattern_count > 0 and pattern_count < 50:
                    logger.warning(
                        f"Pattern server returned only {pattern_count} rules. "
                        f"Standard Gitleaks has 100+ rules. "
                        f"Your pattern server may be missing common secret types (AWS keys, RSA keys, etc.). "
                        f"Ensure your pattern server includes both organization-specific AND default Gitleaks patterns."
                    )

            # Create temporary report file for JSON output
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                prefix="scanner_report_",
                dir=tmp_base_dir,
                delete=False,
            ) as rf:
                report_file = rf.name

            # Multi-engine strategy execution path (any-match, consensus)
            # For these strategies, run all engines via the strategy framework
            # and return the combined result directly.
            if (
                execution_strategy_name in ("first-match", "any-match", "consensus")
                and HAS_SCANNER_ENGINE
                and not gitleaks_config_path
            ):
                try:
                    all_engines = select_all_engines(
                        engines_list, parent_config=scanner_config
                    )
                    strategy_kwargs = {}
                    if execution_strategy_name == "consensus":
                        strategy_kwargs["threshold"] = consensus_threshold
                    strategy = get_strategy(execution_strategy_name, **strategy_kwargs)

                    strategy_result = strategy.execute(
                        engine_configs=all_engines,
                        scanner_fn=run_engine,
                        source_file=tmp_file_path,
                        report_file_prefix=report_file.replace(".json", ""),
                        config_path=gitleaks_config_path,
                        context={
                            "filename": filename,
                            "original_file_path": file_path,
                        },
                    )

                    if strategy_result.has_secrets and strategy_result.secrets:
                        # Apply allowlist filtering
                        if allowlist_patterns:
                            from ai_guardian import allowlist_utils

                            compiled_allowlist = allowlist_utils.compile_allowlist(
                                allowlist_patterns
                            )
                            if compiled_allowlist:
                                content_str = (
                                    content
                                    if isinstance(content, str)
                                    else str(content)
                                )
                                content_lines = content_str.splitlines()
                                all_allowlisted = True
                                for secret in strategy_result.secrets:
                                    line_num = secret.line_number
                                    if line_num > 0 and line_num <= len(content_lines):
                                        line_text = content_lines[line_num - 1]
                                    elif hasattr(secret, "secret") and secret.secret:
                                        line_text = secret.secret
                                    else:
                                        all_allowlisted = False
                                        break
                                    if not allowlist_utils.check_allowlist(
                                        line_text, compiled_allowlist
                                    ):
                                        all_allowlisted = False
                                        break
                                if all_allowlisted:
                                    logger.info(
                                        "All strategy findings matched allowlist — skipping"
                                    )
                                    return False, None

                        # Apply .gitleaks.toml allowlist filtering (Issue #488)
                        if _gitleaks_allowlist and strategy_result.secrets:
                            content_str = (
                                content if isinstance(content, str) else str(content)
                            )
                            gl_lines = content_str.splitlines()
                            findings_dicts = [
                                {
                                    "rule_id": s.rule_id,
                                    "line_number": s.line_number,
                                    "file": s.file,
                                }
                                for s in strategy_result.secrets
                            ]
                            remaining = _gitleaks_cfg.filter_findings(
                                findings_dicts, gl_lines, file_path, _gitleaks_allowlist
                            )
                            if not remaining:
                                logger.info(
                                    "All strategy findings matched .gitleaks.toml allowlist — skipping"
                                )
                                return False, None

                        # Filter external scanner findings by stopwords/entropy (#1245)
                        if _ext_stopwords or _ext_min_entropy is not None:
                            strategy_result.secrets, _sw_n, _ent_n = (
                                filter_findings_by_stopwords_entropy(
                                    strategy_result.secrets,
                                    _ext_stopwords,
                                    _ext_min_entropy,
                                )
                            )
                            if _sw_n or _ent_n:
                                logger.info(
                                    f"External scanner: filtered {_sw_n} stopword + "
                                    f"{_ent_n} low-entropy findings (strategy path)"
                                )
                            if not strategy_result.secrets:
                                logger.info(
                                    "All external scanner findings filtered by stopwords/entropy — skipping"
                                )
                                return False, None

                        # Filter hash false positives (#1378)
                        strategy_result.secrets, _hash_n = filter_findings_by_hash(
                            strategy_result.secrets, content
                        )
                        if _hash_n:
                            logger.info(
                                f"External scanner: filtered {_hash_n} hash value findings (strategy path)"
                            )
                        if not strategy_result.secrets:
                            logger.info(
                                "All external scanner findings filtered as hash values — skipping"
                            )
                            return False, None

                        # Secret liveness validation (Issue #971, #983)
                        secrets_for_validation = [
                            {
                                "rule_id": s.rule_id,
                                "line_number": s.line_number,
                                "secret": s.secret,
                            }
                            for s in strategy_result.secrets
                        ]
                        validation_info, should_skip = _run_secret_validation(
                            secret_config,
                            secrets_for_validation,
                            content,
                            context,
                        )

                        first_secret = strategy_result.secrets[0]
                        secret_findings_list = [
                            {
                                "matched_text": (
                                    _extract_matched_text_for_ask(
                                        {
                                            "matched_text": s.secret,
                                            "line_number": s.line_number,
                                        },
                                        content,
                                    )
                                    if content
                                    else s.secret
                                ),
                                "matched_pattern": s.rule_id or "",
                                "rule_id": s.rule_id,
                                "line_number": s.line_number,
                                "start_column": s.start_column,
                                "end_column": s.end_column,
                                "category": s.category,
                            }
                            for s in strategy_result.secrets
                        ]
                        secret_details = {
                            "rule_id": first_secret.rule_id,
                            "file": file_path or filename,
                            "line_number": first_secret.line_number,
                            "end_line": first_secret.end_line or 0,
                            "start_column": first_secret.start_column,
                            "end_column": first_secret.end_column,
                            "commit": first_secret.commit or "N/A",
                            "total_findings": len(strategy_result.secrets),
                            "engine": strategy_result.engine,
                            "category": first_secret.category,
                            "matched_text": first_secret.secret,
                            "findings": secret_findings_list,
                        }
                        if validation_info:
                            secret_details["validation"] = validation_info

                        if should_skip:
                            _log_finding_violation(
                                file_path or filename,
                                context,
                                secret_details,
                                hook_context=context,
                            )
                            logger.info(
                                "All secrets validated as inactive (strategy path) — allowing"
                            )
                            return False, None

                        scanner_name = strategy_result.engine
                        error_msg = _build_secret_detected_message(
                            scanner_name,
                            secret_details,
                            f"Built-in {scanner_name} rules",
                            f"Secret Scanning ({execution_strategy_name} strategy)",
                        )

                        _log_finding_violation(
                            file_path or filename,
                            context,
                            secret_details,
                            hook_context=context,
                        )
                        logger.error(
                            f"Secret detected ({execution_strategy_name}): {first_secret.rule_id}"
                        )
                        _last_secret_matched_text = _extract_matched_text_for_ask(
                            secret_details, content
                        )
                        _last_secret_line_number = secret_details.get("line_number")
                        _last_secret_start_column = secret_details.get("start_column")
                        _last_secret_findings = secret_findings_list
                        return True, error_msg

                    # No secrets found — check for engine errors that need user attention
                    if strategy_result.error:
                        error_lower = (strategy_result.error or "").lower()

                        # Auth errors → block (user can fix credentials)
                        is_auth_error = any(
                            kw in error_lower for kw in _AUTH_ERROR_KEYWORDS
                        )
                        if is_auth_error:
                            error_msg = (
                                f"\n{'='*70}\n"
                                f"🚨 BLOCKED BY POLICY\n"
                                f"🔒 AUTHENTICATION ERROR\n"
                                f"{'='*70}\n\n"
                                f"Scanner authentication failed.\n"
                                f"\nError: {strategy_result.error[:200]}\n"
                                "\nThis operation has been blocked for security.\n\n"
                                "DO NOT attempt to bypass this protection - fix the authentication issue.\n\n"
                                "If using pattern-servers:\n"
                                "  1. Check your authentication token is valid\n"
                                "  2. Update token: export AI_GUARDIAN_PATTERN_TOKEN='your-token'\n"
                                "  3. Or disable pattern-servers in ~/.config/ai-guardian/ai-guardian.json\n\n"
                                "If NOT using pattern-servers:\n"
                                "  1. Check ~/.gitleaks.toml configuration\n"
                                "  2. Try: gitleaks version (to verify installation)\n"
                                f"{'='*70}\n"
                            )
                            return True, error_msg

                        # Network errors → warn but allow (fail-open)
                        is_network_error = any(
                            kw in error_lower for kw in _NETWORK_ERROR_KEYWORDS
                        )
                        if is_network_error:
                            warning_msg = (
                                f"\n{'='*70}\n"
                                f"⚠️  SECRET SCANNING WARNING\n"
                                f"{'='*70}\n"
                                f"Scanner error: {strategy_result.error[:200]}\n"
                                "\n💡 Network or server issue detected.\n"
                                "   If using pattern-servers, the server may be temporarily unavailable.\n"
                                "   You can disable pattern-servers in ~/.config/ai-guardian/ai-guardian.json\n"
                                "\nOperation will continue, but secret scanning may not be functioning.\n"
                                f"{'='*70}\n"
                            )
                            print(warning_msg, file=sys.stderr)
                            on_error = _get_on_scan_error_action()
                            if on_error == ActionMode.BLOCK:
                                return (
                                    True,
                                    warning_msg
                                    + "\nOperation BLOCKED (on_scan_error=block).",
                                )
                            return False, None

                        # Binary not found → warn but allow (fail-open)
                        if "not found" in error_lower or "no scanners" in error_lower:
                            scanner_name = (
                                engines_list[0] if engines_list else "gitleaks"
                            )
                            warning_msg = (
                                f"\n{'='*70}\n"
                                f"⚠️  SECRET SCANNING DISABLED\n"
                                f"{'='*70}\n\n"
                                f"Gitleaks binary not found.\n"
                                f"Secret scanning will not run until Gitleaks is installed.\n\n"
                                f"Install with:\n"
                                f"  brew install {scanner_name}  (macOS)\n"
                                f"\nOperation will continue without secret scanning.\n"
                                f"{'='*70}\n"
                            )
                            print(warning_msg, file=sys.stderr)
                            return False, None

                    return False, None

                except RuntimeError as e:
                    logger.warning(f"Multi-engine strategy failed: {e}")
                    return False, str(e)
                except Exception as e:
                    logger.error(f"Unexpected error in multi-engine strategy: {e}")
                    return False, None

            # If we have pattern server config, select engine for using it
            # (engine_config already set above if using scanner defaults)
            if gitleaks_config_path and not engine_config and HAS_SCANNER_ENGINE:
                try:
                    scanner_config = (
                        secret_config
                        if secret_config
                        else (_load_secret_scanning_config()[0])
                    )
                    engines_list = (
                        scanner_config.get("engines", DEFAULT_ENGINES)
                        if scanner_config
                        else DEFAULT_ENGINES
                    )
                    execution_strategy_name = (
                        scanner_config.get("execution_strategy", "first-match")
                        if scanner_config
                        else "first-match"
                    )
                    engine_config = select_engine(
                        engines_list, parent_config=scanner_config
                    )

                    # For first-match: get all engines for fallthrough (Issue #523)
                    if (
                        execution_strategy_name == "first-match"
                        and len(engines_list) > 1
                    ):
                        try:
                            _all_available_engines = select_all_engines(
                                engines_list, parent_config=scanner_config
                            )
                        except RuntimeError:
                            pass  # intentionally silent — best-effort operation
                except RuntimeError as e:
                    # No scanner found - warn (allow operation to continue)
                    # Path 2: Pattern server succeeded but no engine to run patterns
                    default_scanner = engines_list[0] if engines_list else "gitleaks"
                    warning_msg = (
                        f"⚠️  WARNING: Scanner engine required\n\n"
                        f"Enterprise patterns are available from the pattern server,\n"
                        f"but no scanner engine is installed to use them.\n\n"
                        f"Please install a scanner with:\n"
                        f"  ai-guardian scanner install {default_scanner}\n\n"
                        f"Until a scanner is installed, you may leak secrets."
                    )
                    logger.warning(f"Scanner engine selection failed: {e}")
                    return False, warning_msg
                except Exception as e:
                    logger.error(f"Unexpected error selecting scanner engine: {e}")
                    return False, None

            # Build scanner command
            resolved_config_path = None
            if engine_config and HAS_SCANNER_ENGINE:
                # Use flexible engine builder (Issue #154)
                resolved_config_path = resolve_engine_config_path(
                    engine_config, gitleaks_config_path
                )
                cmd = build_scanner_command(
                    engine_config=engine_config,
                    source_file=tmp_file_path,
                    report_file=report_file,
                    config_path=resolved_config_path,
                )
            else:
                # Legacy fallback: hardcoded gitleaks command
                logger.debug(
                    "Using legacy gitleaks command (scanner engine not available)"
                )
                cmd = [
                    "gitleaks",
                    "detect",
                    "--no-git",  # Don't use git history
                    "--verbose",  # Detailed output
                    "--redact",  # Defense-in-depth: redact Match/Secret fields in JSON
                    # (we don't extract these fields, but safeguard against future changes)
                    "--report-format",
                    "json",  # JSON output for parsing
                    "--report-path",
                    report_file,  # Write JSON to file
                    "--exit-code",
                    "42",  # Custom exit code for found secrets
                    "--source",
                    tmp_file_path,
                ]
                # Add custom config if we have one
                if gitleaks_config_path:
                    cmd.extend(["--config", str(Path(gitleaks_config_path).absolute())])

            # Run scanner
            logger.debug(f"Scanner command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30  # Prevent hanging
            )

            # Determine expected exit codes for secrets found/success
            # Use engine-specific codes if available, otherwise use gitleaks defaults
            expected_secrets_code = (
                engine_config.secrets_found_exit_code if engine_config else 42
            )
            expected_success_codes = (
                [engine_config.success_exit_code] if engine_config else [0]
            )

            logger.debug(
                f"Scanner exit code: {result.returncode}, expected_secrets={expected_secrets_code}, expected_success={expected_success_codes}"
            )

            # Gitleaks/betterleaks use exit code 1 as default "secrets found" code
            # when --exit-code flag is not honored. Treat exit 1 as secrets found
            # for these engines to prevent bypass (Issue #411).
            _is_gitleaks_like = (
                engine_config and engine_config.type in ("gitleaks", "betterleaks")
            ) or not engine_config  # legacy path uses gitleaks
            _is_secrets_found = result.returncode == expected_secrets_code or (
                result.returncode == 1 and _is_gitleaks_like
            )

            # Check exit code
            if _is_secrets_found:  # Secrets found
                # Parse scanner output using appropriate parser (Issue #154)
                secret_details = None
                scan_result = None

                if engine_config and HAS_SCANNER_ENGINE:
                    # Use flexible parser based on engine type
                    try:
                        parser = get_parser(engine_config.output_parser)
                        scan_result = parser.parse(report_file)
                        if scan_result and scan_result.get("has_secrets"):
                            # Convert to legacy format for compatibility
                            first_finding = (
                                scan_result["findings"][0]
                                if scan_result["findings"]
                                else {}
                            )
                            secret_details = {
                                "rule_id": first_finding.get("rule_id", "Unknown"),
                                "file": file_path or filename,
                                "line_number": first_finding.get("line_number", 0),
                                "end_line": first_finding.get("end_line", 0),
                                "start_column": first_finding.get("start_column"),
                                "end_column": first_finding.get("end_column"),
                                "commit": first_finding.get("commit", "N/A"),
                                "total_findings": scan_result.get("total_findings", 0),
                                "matched_text": first_finding.get("matched_text", ""),
                            }
                    except Exception as e:
                        logger.error(
                            f"Failed to parse scanner output with {engine_config.output_parser} parser: {e}"
                        )
                else:
                    # Legacy parser for gitleaks
                    try:
                        if os.path.exists(report_file):
                            with open(report_file, "r", encoding="utf-8") as f:
                                findings = json.load(f)
                            if findings and len(findings) > 0:
                                # Get first finding for details
                                first_finding = findings[0]
                                secret_details = {
                                    "rule_id": first_finding.get("RuleID", "Unknown"),
                                    "file": file_path or filename,
                                    "line_number": first_finding.get("StartLine", 0),
                                    "end_line": first_finding.get("EndLine", 0),
                                    "start_column": first_finding.get("StartColumn"),
                                    "end_column": first_finding.get("EndColumn"),
                                    "commit": first_finding.get("Commit", "N/A"),
                                    "total_findings": len(findings),
                                    "matched_text": first_finding.get("Match", ""),
                                }
                    except Exception as e:
                        logger.debug(f"Failed to parse scanner JSON report: {e}")

                # Guard: exit code said secrets but report is empty/unparseable (Issue #532)
                # Don't return immediately — fall through to first-match fallthrough (Issue #523)
                if secret_details is None and (
                    scan_result is None or not scan_result.get("has_secrets")
                ):
                    logger.warning(
                        f"Scanner exited with secrets-found code ({result.returncode}) "
                        f"but produced no findings — treating as clean"
                    )
                    if (
                        execution_strategy_name == "first-match"
                        and _all_available_engines
                        and len(_all_available_engines) > 1
                    ):
                        remaining = [
                            e
                            for e in _all_available_engines
                            if e.type != engine_config.type
                        ]
                        if remaining:
                            logger.info(
                                f"Engine {engine_config.type} found no secrets, "
                                f"trying remaining engines: {[e.type for e in remaining]}"
                            )
                            strategy = get_strategy("first-match")
                            fallback_result = strategy.execute(
                                engine_configs=remaining,
                                scanner_fn=run_engine,
                                source_file=tmp_file_path,
                                report_file_prefix=report_file.replace(".json", ""),
                                config_path=None,
                                context={
                                    "filename": filename,
                                    "original_file_path": file_path,
                                },
                            )
                            if fallback_result.has_secrets and fallback_result.secrets:
                                # Filter by stopwords/entropy (#1245) — fallthrough path 1
                                if _ext_stopwords or _ext_min_entropy is not None:
                                    fallback_result.secrets, _sw_n, _ent_n = (
                                        filter_findings_by_stopwords_entropy(
                                            fallback_result.secrets,
                                            _ext_stopwords,
                                            _ext_min_entropy,
                                        )
                                    )
                                    if _sw_n or _ent_n:
                                        logger.info(
                                            f"External scanner: filtered {_sw_n} stopword + "
                                            f"{_ent_n} low-entropy findings (fallthrough 1)"
                                        )
                                    if not fallback_result.secrets:
                                        logger.info(
                                            "All fallthrough-1 findings filtered by stopwords/entropy — skipping"
                                        )
                                        return False, None

                                # Filter hash false positives (#1378) — fallthrough path 1
                                fallback_result.secrets, _hash_n = (
                                    filter_findings_by_hash(
                                        fallback_result.secrets, content
                                    )
                                )
                                if _hash_n:
                                    logger.info(
                                        f"External scanner: filtered {_hash_n} hash value findings (fallthrough 1)"
                                    )
                                if not fallback_result.secrets:
                                    logger.info(
                                        "All fallthrough-1 findings filtered as hash values — skipping"
                                    )
                                    return False, None

                                # Secret liveness validation (Issue #971, #983) — fallthrough path 1
                                fb_secrets = [
                                    {
                                        "rule_id": s.rule_id,
                                        "line_number": s.line_number,
                                        "secret": s.secret,
                                    }
                                    for s in fallback_result.secrets
                                ]
                                fb_validation_info, fb_should_skip = (
                                    _run_secret_validation(
                                        secret_config,
                                        fb_secrets,
                                        content,
                                        context,
                                    )
                                )

                                first_secret = fallback_result.secrets[0]
                                secret_details = {
                                    "rule_id": first_secret.rule_id,
                                    "file": file_path or filename,
                                    "line_number": first_secret.line_number,
                                    "end_line": first_secret.end_line or 0,
                                    "start_column": first_secret.start_column,
                                    "end_column": first_secret.end_column,
                                    "commit": first_secret.commit or "N/A",
                                    "total_findings": len(fallback_result.secrets),
                                    "engine": fallback_result.engine,
                                    "category": first_secret.category,
                                    "matched_text": first_secret.secret,
                                }
                                if fb_validation_info:
                                    secret_details["validation"] = fb_validation_info

                                if fb_should_skip:
                                    _log_finding_violation(
                                        file_path or filename,
                                        context,
                                        secret_details,
                                        hook_context=context,
                                    )
                                    logger.info(
                                        "All secrets validated as inactive (fallthrough 1) — allowing"
                                    )
                                    return False, None

                                scanner_name = fallback_result.engine
                                error_msg = _build_secret_detected_message(
                                    scanner_name,
                                    secret_details,
                                    "Built-in Defaults",
                                    "Secret Scanning (first-match fallthrough)",
                                )
                                _log_finding_violation(
                                    file_path or filename,
                                    context,
                                    secret_details,
                                    hook_context=context,
                                )
                                logger.error(
                                    f"Secret detected (first-match fallthrough): {first_secret.rule_id}"
                                )
                                _last_secret_matched_text = (
                                    _extract_matched_text_for_ask(
                                        secret_details, content
                                    )
                                )
                                _last_secret_line_number = secret_details.get(
                                    "line_number"
                                )
                                _last_secret_start_column = secret_details.get(
                                    "start_column"
                                )
                                return True, error_msg
                    return False, None

                # Filter findings through allowlist patterns (Issue #357)
                if allowlist_patterns and secret_details:
                    from ai_guardian import allowlist_utils

                    compiled_allowlist = allowlist_utils.compile_allowlist(
                        allowlist_patterns
                    )
                    if compiled_allowlist:
                        content_str = (
                            content if isinstance(content, str) else str(content)
                        )
                        content_lines = content_str.splitlines()

                        all_allowlisted = True
                        # Check findings from modern parser
                        if scan_result and scan_result.get("findings"):
                            for finding in scan_result["findings"]:
                                line_num = finding.get("line_number", 0)
                                if line_num > 0 and line_num <= len(content_lines):
                                    line_text = content_lines[line_num - 1]
                                elif finding.get("matched_text"):
                                    line_text = finding["matched_text"]
                                else:
                                    all_allowlisted = False
                                    break
                                if not allowlist_utils.check_allowlist(
                                    line_text, compiled_allowlist
                                ):
                                    all_allowlisted = False
                                    break
                        else:
                            # Legacy parser or single finding — check via line number
                            line_num = secret_details.get("line_number", 0)
                            if line_num > 0 and line_num <= len(content_lines):
                                line_text = content_lines[line_num - 1]
                            elif secret_details.get("matched_text"):
                                line_text = secret_details["matched_text"]
                            else:
                                line_text = None
                            if (
                                line_text is None
                                or not allowlist_utils.check_allowlist(
                                    line_text, compiled_allowlist
                                )
                            ):
                                all_allowlisted = False

                        if all_allowlisted:
                            logger.info(
                                "All secret findings matched allowlist patterns — skipping"
                            )
                            return False, None

                # Apply .gitleaks.toml allowlist filtering (Issue #488)
                if _gitleaks_allowlist and secret_details:
                    content_str = content if isinstance(content, str) else str(content)
                    gl_lines = content_str.splitlines()
                    if scan_result and scan_result.get("findings"):
                        gl_remaining = _gitleaks_cfg.filter_findings(
                            scan_result["findings"],
                            gl_lines,
                            file_path,
                            _gitleaks_allowlist,
                        )
                    else:
                        gl_remaining = _gitleaks_cfg.filter_findings(
                            [secret_details], gl_lines, file_path, _gitleaks_allowlist
                        )
                    if not gl_remaining:
                        logger.info(
                            "All secret findings matched .gitleaks.toml allowlist — skipping"
                        )
                        return False, None

                # Filter external scanner findings by stopwords/entropy (#1245) — legacy path
                if secret_details and (_ext_stopwords or _ext_min_entropy is not None):
                    if scan_result and scan_result.get("findings"):
                        _filt, _sw_n, _ent_n = (
                            filter_findings_dicts_by_stopwords_entropy(
                                scan_result["findings"],
                                _ext_stopwords,
                                _ext_min_entropy,
                            )
                        )
                        if _sw_n or _ent_n:
                            logger.info(
                                f"External scanner: filtered {_sw_n} stopword + "
                                f"{_ent_n} low-entropy findings (legacy path)"
                            )
                        if not _filt:
                            logger.info(
                                "All external scanner findings filtered by stopwords/entropy — skipping"
                            )
                            return False, None
                        # Filter hash false positives (#1378) — legacy path (findings)
                        _filt, _hash_n = filter_findings_dicts_by_hash(_filt, content)
                        if _hash_n:
                            logger.info(
                                f"External scanner: filtered {_hash_n} hash value findings (legacy path)"
                            )
                        if not _filt:
                            logger.info(
                                "All legacy findings filtered as hash values — skipping"
                            )
                            return False, None
                        scan_result["findings"] = _filt
                        scan_result["total_findings"] = len(_filt)
                        first_finding = _filt[0]
                        secret_details = {
                            "rule_id": first_finding.get(
                                "rule_id", secret_details.get("rule_id")
                            ),
                            "file": secret_details.get("file"),
                            "line_number": first_finding.get(
                                "line_number", secret_details.get("line_number")
                            ),
                            "end_line": first_finding.get(
                                "end_line", secret_details.get("end_line", 0)
                            ),
                            "start_column": first_finding.get(
                                "start_column", secret_details.get("start_column")
                            ),
                            "end_column": first_finding.get(
                                "end_column", secret_details.get("end_column")
                            ),
                            "commit": first_finding.get(
                                "commit", secret_details.get("commit", "N/A")
                            ),
                            "total_findings": len(_filt),
                            "matched_text": first_finding.get("matched_text", ""),
                        }
                    else:
                        _filt, _sw_n, _ent_n = (
                            filter_findings_dicts_by_stopwords_entropy(
                                [secret_details], _ext_stopwords, _ext_min_entropy
                            )
                        )
                        if _sw_n or _ent_n:
                            logger.info(
                                f"External scanner: filtered {_sw_n} stopword + "
                                f"{_ent_n} low-entropy findings (legacy path)"
                            )
                        if not _filt:
                            logger.info(
                                "All external scanner findings filtered by stopwords/entropy — skipping"
                            )
                            return False, None
                        # Filter hash false positives (#1378) — legacy path (single)
                        _filt, _hash_n = filter_findings_dicts_by_hash(_filt, content)
                        if _hash_n:
                            logger.info(
                                f"External scanner: filtered {_hash_n} hash value findings (legacy single)"
                            )
                        if not _filt:
                            logger.info(
                                "All legacy findings filtered as hash values — skipping"
                            )
                            return False, None

                # Secret liveness validation (Issue #971, #983) — legacy subprocess path
                if secret_details:
                    secrets_for_validation = [secret_details]
                    if scan_result and scan_result.get("findings"):
                        secrets_for_validation = scan_result["findings"]
                    legacy_validation_info, legacy_should_skip = _run_secret_validation(
                        secret_config,
                        secrets_for_validation,
                        content,
                        context,
                    )
                    if legacy_validation_info:
                        secret_details["validation"] = legacy_validation_info

                    if legacy_should_skip:
                        scanner_name = (
                            engine_config.type if engine_config else "Gitleaks"
                        )
                        if secret_details is not None:
                            secret_details.setdefault("engine", scanner_name)
                        _log_finding_violation(
                            file_path or filename,
                            context,
                            secret_details,
                            hook_context=context,
                        )
                        logger.info(
                            "All secrets validated as inactive (legacy path) — allowing"
                        )
                        return False, None

                # Build error message with details if available
                scanner_name = engine_config.type if engine_config else "Gitleaks"
                pattern_config_for_msg = pattern_config if HAS_PATTERN_SERVER else None
                error_msg = _build_secret_detected_message(
                    scanner_name,
                    secret_details,
                    _describe_patterns(
                        engine_config,
                        resolved_config_path,
                        config_source,
                        pattern_config_for_msg,
                    ),
                )

                # Log violation with category-aware routing (Issue #984)
                if secret_details is not None:
                    secret_details.setdefault("engine", scanner_name)
                _log_finding_violation(
                    file_path or filename, context, secret_details, hook_context=context
                )

                logger.error(
                    f"Secret detected: {secret_details.get('rule_id') if secret_details else 'unknown'}"
                )
                _last_secret_matched_text = _extract_matched_text_for_ask(
                    secret_details, content
                )
                _last_secret_line_number = (
                    secret_details.get("line_number") if secret_details else None
                )
                _last_secret_start_column = (
                    secret_details.get("start_column") if secret_details else None
                )
                return True, error_msg

            elif result.returncode in expected_success_codes:
                # No secrets found by primary engine.
                # For first-match: try remaining engines (Issue #523)
                if (
                    execution_strategy_name == "first-match"
                    and _all_available_engines
                    and len(_all_available_engines) > 1
                ):
                    remaining = [
                        e
                        for e in _all_available_engines
                        if e.type != engine_config.type
                    ]
                    if remaining:
                        logger.info(
                            f"Engine {engine_config.type} found no secrets, "
                            f"trying remaining engines: {[e.type for e in remaining]}"
                        )
                        strategy = get_strategy("first-match")
                        fallback_result = strategy.execute(
                            engine_configs=remaining,
                            scanner_fn=run_engine,
                            source_file=tmp_file_path,
                            report_file_prefix=report_file.replace(".json", ""),
                            config_path=None,
                            context={
                                "filename": filename,
                                "original_file_path": file_path,
                            },
                        )
                        if fallback_result.has_secrets and fallback_result.secrets:
                            # Filter by stopwords/entropy (#1245) — fallthrough path 2
                            if _ext_stopwords or _ext_min_entropy is not None:
                                fallback_result.secrets, _sw_n, _ent_n = (
                                    filter_findings_by_stopwords_entropy(
                                        fallback_result.secrets,
                                        _ext_stopwords,
                                        _ext_min_entropy,
                                    )
                                )
                                if _sw_n or _ent_n:
                                    logger.info(
                                        f"External scanner: filtered {_sw_n} stopword + "
                                        f"{_ent_n} low-entropy findings (fallthrough 2)"
                                    )
                                if not fallback_result.secrets:
                                    logger.info(
                                        "All fallthrough-2 findings filtered by stopwords/entropy — skipping"
                                    )
                                    return False, None

                            # Filter hash false positives (#1378) — fallthrough path 2
                            fallback_result.secrets, _hash_n = filter_findings_by_hash(
                                fallback_result.secrets, content
                            )
                            if _hash_n:
                                logger.info(
                                    f"External scanner: filtered {_hash_n} hash value findings (fallthrough 2)"
                                )
                            if not fallback_result.secrets:
                                logger.info(
                                    "All fallthrough-2 findings filtered as hash values — skipping"
                                )
                                return False, None

                            # Secret liveness validation (Issue #971, #983) — fallthrough path 2
                            fb2_secrets = [
                                {
                                    "rule_id": s.rule_id,
                                    "line_number": s.line_number,
                                    "secret": s.secret,
                                }
                                for s in fallback_result.secrets
                            ]
                            fb2_validation_info, fb2_should_skip = (
                                _run_secret_validation(
                                    secret_config,
                                    fb2_secrets,
                                    content,
                                    context,
                                )
                            )

                            first_secret = fallback_result.secrets[0]
                            secret_details = {
                                "rule_id": first_secret.rule_id,
                                "file": file_path or filename,
                                "line_number": first_secret.line_number,
                                "end_line": first_secret.end_line or 0,
                                "start_column": first_secret.start_column,
                                "end_column": first_secret.end_column,
                                "commit": first_secret.commit or "N/A",
                                "total_findings": len(fallback_result.secrets),
                                "engine": fallback_result.engine,
                                "category": first_secret.category,
                                "matched_text": first_secret.secret,
                            }
                            if fb2_validation_info:
                                secret_details["validation"] = fb2_validation_info

                            if fb2_should_skip:
                                _log_finding_violation(
                                    file_path or filename,
                                    context,
                                    secret_details,
                                    hook_context=context,
                                )
                                logger.info(
                                    "All secrets validated as inactive (fallthrough 2) — allowing"
                                )
                                return False, None

                            scanner_name = fallback_result.engine
                            fallback_engine_config = next(
                                (e for e in remaining if e.type == scanner_name), None
                            )
                            fallback_resolved = (
                                resolve_engine_config_path(
                                    fallback_engine_config, gitleaks_config_path
                                )
                                if fallback_engine_config
                                else None
                            )
                            fallback_pattern_desc = _describe_patterns(
                                fallback_engine_config,
                                fallback_resolved,
                                config_source,
                                pattern_config if HAS_PATTERN_SERVER else None,
                            )
                            error_msg = _build_secret_detected_message(
                                scanner_name,
                                secret_details,
                                fallback_pattern_desc,
                                "Secret Scanning (first-match fallthrough)",
                            )
                            _log_finding_violation(
                                file_path or filename,
                                context,
                                secret_details,
                                hook_context=context,
                            )
                            logger.error(
                                f"Secret detected (first-match fallthrough): {first_secret.rule_id}"
                            )
                            _last_secret_matched_text = _extract_matched_text_for_ask(
                                secret_details, content
                            )
                            _last_secret_line_number = secret_details.get("line_number")
                            _last_secret_start_column = secret_details.get(
                                "start_column"
                            )
                            return True, error_msg

                return False, None

            else:
                # Unexpected error - analyze and decide whether to block or warn
                logger.warning(
                    f"Gitleaks returned unexpected exit code: {result.returncode}"
                )

                # Extract error details (sanitized - don't log full stderr to avoid leaking secrets)
                stderr_preview = ""
                if result.stderr:
                    # Only log sanitized error info, not full stderr
                    logger.debug(
                        f"Gitleaks stderr present (length: {len(result.stderr)} chars)"
                    )
                    stderr_lines = [
                        line.strip()
                        for line in result.stderr.split("\n")
                        if line.strip()
                    ]
                    if stderr_lines:
                        # Only show first line (error summary), truncated
                        stderr_preview = stderr_lines[0][:200]

                # Check if this is an authentication/authorization error (user can fix)
                is_auth_error = False
                if result.stderr:
                    stderr_lower = result.stderr.lower()
                    is_auth_error = any(
                        keyword in stderr_lower for keyword in _AUTH_ERROR_KEYWORDS
                    )

                # Check if this is a network error (user cannot fix)
                is_network_error = False
                if result.stderr:
                    stderr_lower = result.stderr.lower()
                    is_network_error = any(
                        keyword in stderr_lower for keyword in _NETWORK_ERROR_KEYWORDS
                    )

                if is_auth_error:
                    # Authentication error - BLOCK (user can fix by updating credentials)
                    error_msg = (
                        f"\n{'='*70}\n"
                        f"🚨 BLOCKED BY POLICY\n"
                        f"🔒 AUTHENTICATION ERROR\n"
                        f"{'='*70}\n\n"
                        f"Gitleaks authentication failed (exit code {result.returncode}).\n"
                    )
                    if stderr_preview:
                        error_msg += f"\nError: {stderr_preview}\n"
                    error_msg += (
                        "\nThis operation has been blocked for security.\n\n"
                        "DO NOT attempt to bypass this protection - fix the authentication issue.\n\n"
                        "If using pattern-servers:\n"
                        "  1. Check your authentication token is valid\n"
                        "  2. Update token: export AI_GUARDIAN_PATTERN_TOKEN='your-token'\n"
                        "  3. Or disable pattern-servers in ~/.config/ai-guardian/ai-guardian.json\n\n"
                        "If NOT using pattern-servers:\n"
                        "  1. Check ~/.gitleaks.toml configuration\n"
                        "  2. Try: gitleaks version (to verify installation)\n"
                        f"{'='*70}\n"
                    )
                    return True, error_msg  # Block operation

                else:
                    # Network error or other issue - WARN but allow (fail-open)
                    warning_msg = (
                        f"\n{'='*70}\n"
                        f"⚠️  SECRET SCANNING WARNING\n"
                        f"{'='*70}\n"
                        f"Gitleaks failed with exit code {result.returncode}.\n"
                    )
                    if stderr_preview:
                        warning_msg += f"Error: {stderr_preview}\n"

                    if is_network_error:
                        warning_msg += (
                            "\n💡 Network or server issue detected.\n"
                            "   If using pattern-servers, the server may be temporarily unavailable.\n"
                            "   You can disable pattern-servers in ~/.config/ai-guardian/ai-guardian.json\n"
                        )

                    warning_msg += (
                        "\nOperation will continue, but secret scanning may not be functioning.\n\n"
                        "Troubleshooting:\n"
                        "  • Check Gitleaks: gitleaks version\n"
                        "  • Review config: ~/.gitleaks.toml (if exists)\n"
                        "  • Reinstall: brew reinstall gitleaks (macOS)\n"
                        f"{'='*70}\n"
                    )

                    # Print to stderr for visibility
                    print(warning_msg, file=sys.stderr)

                    on_error = _get_on_scan_error_action()
                    if on_error == ActionMode.BLOCK:
                        logger.error(
                            "Secret scanning error (fail-closed, on_scan_error=block)"
                        )
                        return (
                            True,
                            warning_msg + "\nOperation BLOCKED (on_scan_error=block).",
                        )
                    return False, None

        finally:
            # Secure cleanup: overwrite file before deletion
            if os.path.exists(tmp_file_path):
                try:
                    # Make file writable
                    os.chmod(tmp_file_path, 0o600)

                    # Overwrite with zeros to prevent recovery
                    file_size = os.path.getsize(tmp_file_path)
                    with open(tmp_file_path, "wb") as f:
                        f.write(b"\x00" * file_size)
                        f.flush()
                        os.fsync(f.fileno())

                    # Delete the file
                    os.unlink(tmp_file_path)

                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to securely cleanup temp file: {cleanup_error}"
                    )
                    # Still try basic deletion
                    try:
                        if os.path.exists(tmp_file_path):
                            os.unlink(tmp_file_path)
                    except Exception:
                        pass  # Silent fail on final cleanup

            # Securely clean up report files (contains scanner findings)
            # Handles both single-engine report and multi-engine strategy report files
            report_files_to_clean = []
            if report_file:
                report_files_to_clean.append(report_file)
                # Multi-engine strategies create per-engine report files
                report_prefix = report_file.replace(".json", "")
                report_files_to_clean.extend(glob.glob(f"{report_prefix}_*.json"))

            for rf_path in report_files_to_clean:
                if os.path.exists(rf_path):
                    try:
                        os.chmod(rf_path, 0o600)
                        file_size = os.path.getsize(rf_path)
                        with open(rf_path, "wb") as f:
                            f.write(b"\x00" * file_size)
                            f.flush()
                            os.fsync(f.fileno())
                        os.unlink(rf_path)
                    except Exception as cleanup_error:
                        logger.debug(
                            f"Failed to securely cleanup report file {rf_path}: {cleanup_error}"
                        )
                        try:
                            if os.path.exists(rf_path):
                                os.unlink(rf_path)
                        except Exception:
                            pass  # intentionally silent — best-effort operation

    except FileNotFoundError:
        # Scanner binary not found - warn but allow (user may not be able to install immediately)
        scanner_name = engine_config.type if engine_config else "scanner"
        logger.warning(f"{scanner_name} binary not found - skipping secret scanning")

        # Print visible warning to stderr
        warning_msg = (
            f"\n{'='*70}\n"
            f"⚠️  SECRET SCANNING DISABLED\n"
            f"{'='*70}\n\n"
            f"{scanner_name.capitalize()} binary not found - secret scanning is currently disabled.\n\n"
            "AI Guardian requires a secret scanner to detect sensitive information like:\n"
            "  • API keys and tokens\n"
            "  • Private keys (SSH, RSA, PGP)\n"
            "  • Database credentials\n"
            "  • Cloud provider keys (AWS, GCP, Azure)\n\n"
            "Install a supported scanner:\n"
            "  Gitleaks:     brew install gitleaks\n"
            "  BetterLeaks:  brew install betterleaks (20-40% faster)\n"
            "  LeakTK:       brew install leaktk/tap/leaktk\n\n"
            "See https://github.com/RedHatProductSecurity/ai-guardian for more information.\n\n"
            "Operation will continue, but secrets will NOT be detected.\n"
            "After installation, restart your IDE.\n"
            f"{'='*70}\n"
        )
        print(warning_msg, file=sys.stderr)

        # Fail open - allow operation to continue
        return False, None

    except subprocess.TimeoutExpired:
        logger.error("Gitleaks scan timed out after 30 seconds")
        return False, None

    except Exception as e:
        logger.error(f"Unexpected error during secret scanning: {e}")
        import traceback

        logger.error(traceback.format_exc())
        # Fail open - don't block on errors
        return False, None
