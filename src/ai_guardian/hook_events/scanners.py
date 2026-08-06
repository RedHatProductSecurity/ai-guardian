"""Scanner runner functions extracted from hook_processing.py (Phase 5d, #1491)."""

import fnmatch
import logging
import os
from datetime import datetime, timezone

import ai_guardian.config.loaders as _loaders
from ai_guardian.config.utils import get_project_dir, is_feature_enabled
from ai_guardian.constants import HookEvent
from ai_guardian.project_init import get_language_allowlist_patterns
from ai_guardian.reporting.latency import _CheckTimer
from ai_guardian.scanners.scan_result import ScanResult

logger = logging.getLogger(__name__)

_NULL_TIMER = _CheckTimer(enabled=False)

import ai_guardian.config.loaders as _loaders
import ai_guardian.scanners.secret_scanning as _secret_scanning_mod

# --- Conditional imports for scanner modules ---

try:
    from ai_guardian.scanners.prompt_injection import (
        check_prompt_injection,
        PromptInjectionDetector,
    )

    HAS_PROMPT_INJECTION = True
except ImportError:
    HAS_PROMPT_INJECTION = False

try:
    from ai_guardian.scanners.context_poisoning import ContextPoisoningDetector

    HAS_CONTEXT_POISONING = True
except ImportError:
    HAS_CONTEXT_POISONING = False

try:
    from ai_guardian.scanners.config_scanner import (
        check_config_file_threats,
        check_bash_command_threats,
    )

    HAS_CONFIG_SCANNER = True
except ImportError:
    HAS_CONFIG_SCANNER = False

try:
    from ai_guardian.scanners.supply_chain import SupplyChainScanner

    HAS_SUPPLY_CHAIN = True
except ImportError:
    HAS_SUPPLY_CHAIN = False

try:
    from ai_guardian.scanners.offensive_language import OffensiveLanguageScanner

    HAS_OFFENSIVE_LANGUAGE = True
except ImportError:
    HAS_OFFENSIVE_LANGUAGE = False

try:
    from ai_guardian.scanners.canary_detection import CanaryTokenScanner

    HAS_CANARY_DETECTION = True
except ImportError:
    HAS_CANARY_DETECTION = False

try:
    from ai_guardian.scanners.exfil_detection import ExfilDetectionScanner

    HAS_EXFIL_DETECTION = True
except ImportError:
    HAS_EXFIL_DETECTION = False

try:
    from ai_guardian.scanners.image_scanner import (
        ImageDetector,
        scan_image,
        ImageRedactor,
    )

    HAS_IMAGE_SCANNER = True
except ImportError:
    HAS_IMAGE_SCANNER = False


# ---------------------------------------------------------------------------
# Language overlay helper
# ---------------------------------------------------------------------------


def apply_language_overlays(config: dict, scanner_name: str) -> dict:
    """Merge auto-detected language false positive patterns into scanner config.

    Returns a shallow copy of *config* with ``allowlist_patterns`` extended,
    or the original dict unchanged if no patterns apply.
    """
    project_dir = get_project_dir()
    auto_patterns = (
        get_language_allowlist_patterns(project_dir, scanner_name)
        if project_dir
        else []
    )
    if auto_patterns:
        existing = config.get("allowlist_patterns", [])
        config = {**config, "allowlist_patterns": existing + auto_patterns}
    return config


def _load_overlaid_config(entry):
    """Load scanner config and apply language overlays if the entry supports it.

    Uses ``entry.config_section`` to load from ai-guardian.json, so no
    per-scanner loader function is needed.  Returns the (possibly overlaid)
    config dict, or ``None`` when the entry does not support overlays, has
    no ``config_section``, or when the section is absent/empty.
    """
    if not entry or not entry.supports_language_overlay or not entry.config_section:
        return None
    config, config_error = _loaders._load_config_section(
        entry.config_section, merge_ignore=True
    )
    if config_error:
        logger.warning("Config load warning for %s: %s", entry.name.value, config_error)
    if not config:
        return None
    return apply_language_overlays(config, entry.name.value)


# ---------------------------------------------------------------------------
# Scanner runner functions
# ---------------------------------------------------------------------------


def run_prompt_injection_scan(
    content,
    *,
    config=None,
    file_path=None,
    tool_name=None,
    source_type="file_content",
    latency_timer=None,
):
    """Run prompt injection scan on content.

    Args:
        content: Text to scan for prompt injection.
        config: Pre-loaded PI config dict, or None to load internally.
        file_path: File path associated with the content (for ignore checks).
        tool_name: Tool identifier (for ignore checks).
        source_type: 'user_prompt' or 'file_content' — controls thresholds.
        latency_timer: Optional _CheckTimer for performance tracking.

    Returns:
        None if scanner unavailable, disabled, or skipped.
        ScanResult with detection details otherwise.
    """
    if not HAS_PROMPT_INJECTION:
        return None
    if not content:
        return None

    now = datetime.now(timezone.utc)
    if config is None:
        config, config_error = _loaders._load_prompt_injection_config()
        if config_error:
            logger.warning(f"PI config error: {config_error}")
    if not config or not is_feature_enabled(config.get("enabled"), now, default=True):
        return None

    detector = PromptInjectionDetector(config)
    with (latency_timer or _NULL_TIMER).check("prompt_injection"):
        should_block, error_msg, detected = detector.detect(
            content,
            file_path=file_path,
            tool_name=tool_name,
            source_type=source_type,
        )

    result = ScanResult.from_prompt_injection(
        should_block=should_block,
        error_message=error_msg,
        detected=detected,
        matched_text=detector.last_matched_text or "",
        matched_pattern=detector.last_matched_pattern or "",
        line_number=detector.last_line_number,
        start_column=detector.last_start_column,
        end_column=detector.last_end_column,
        confidence=detector.last_confidence or 0.0,
        findings=detector.findings if detector.findings else None,
        attack_type=detector.last_attack_type or "",
    )
    result.extra["action"] = config.get("action", "block")
    return result


def run_context_poisoning_scan(
    content,
    *,
    config=None,
    file_path=None,
    tool_name=None,
    tool_identifier=None,
    latency_timer=None,
):
    """Run context poisoning scan on content.

    Args:
        content: Text to scan for context poisoning patterns.
        config: Pre-loaded CP config dict, or None to load internally.
        file_path: File path for ignore checks.
        tool_name: Tool name for ignore checks.
        tool_identifier: Tool identifier for skip checks.
        latency_timer: Optional _CheckTimer for performance tracking.

    Returns:
        None if scanner unavailable, disabled, or skipped.
        ScanResult with detection details otherwise.
    """
    from ai_guardian.hook_processing import _should_skip_context_poisoning

    if not HAS_CONTEXT_POISONING:
        return None
    if not content:
        return None

    now = datetime.now(timezone.utc)
    if config is None:
        config, config_error = _loaders._load_context_poisoning_config()
        if config_error:
            logger.warning(f"CP config error: {config_error}")
    if not config or not is_feature_enabled(config.get("enabled"), now, default=True):
        return None

    if _should_skip_context_poisoning(config, tool_identifier, file_path):
        return None

    detector = ContextPoisoningDetector(config)
    with (latency_timer or _NULL_TIMER).check("context_poisoning"):
        should_block, error_msg, detected = detector.detect(content)

    result = ScanResult.from_context_poisoning(
        should_block=should_block,
        error_message=error_msg,
        detected=detected,
        matched_text=detector.last_matched_text or "",
        matched_pattern=detector.last_matched_pattern or "",
        line_number=detector.last_line_number,
        start_column=detector.last_start_column,
        end_column=detector.last_end_column,
        confidence=detector.last_confidence or 0.0,
        findings=(
            detector.findings
            if hasattr(detector, "findings") and detector.findings
            else None
        ),
    )
    result.extra["action"] = config.get("action", "warn")
    return result


def run_supply_chain_scan(
    content,
    file_path,
    *,
    config=None,
    hook_event=None,
    latency_timer=None,
):
    """Run supply chain scan on content.

    Args:
        content: Text to scan for supply chain threats.
        file_path: File path being scanned.
        config: Pre-loaded SC config dict, or None to load internally.
        hook_event: Hook event type (skips on PROMPT).
        latency_timer: Optional _CheckTimer for performance tracking.

    Returns:
        None if scanner unavailable, disabled, or skipped.
        ScanResult with detection details otherwise.
    """
    if not HAS_SUPPLY_CHAIN:
        return None
    if not content:
        return None
    if hook_event == HookEvent.PROMPT:
        return None

    now = datetime.now(timezone.utc)
    if config is None:
        config, config_error = _loaders._load_supply_chain_config()
        if config_error:
            logger.warning(f"Supply chain config error: {config_error}")
    if not config or not is_feature_enabled(config.get("enabled"), now, default=True):
        return None

    scanner = SupplyChainScanner(config)
    scan_path = file_path or "unknown"

    with (latency_timer or _NULL_TIMER).check("supply_chain"):
        should_block, error_msg, detected = scanner.scan(scan_path, content)

    result = ScanResult.from_supply_chain(
        should_block=should_block,
        error_message=error_msg,
        details=(
            {
                "matched_text": scanner.last_matched_text or "",
                "pattern": scanner.last_matched_pattern or "",
                "category": scanner.last_category or "",
                "line_number": scanner.last_line_number,
                "start_column": scanner.last_start_column,
                "end_column": scanner.last_end_column,
            }
            if detected
            else None
        ),
        file_path=scan_path,
    )
    result.extra["action"] = config.get("action", "block")
    return result


def _should_skip_offensive_language_scan(config, tool_identifier=None, file_path=None):
    """Return True if offensive language scan should be skipped for this tool/file."""
    from ai_guardian.hook_processing import _matches_ignore_files

    ignore_tools = config.get("ignore_tools", [])
    if tool_identifier and ignore_tools:
        if any(t.lower() in tool_identifier.lower() for t in ignore_tools):
            return True
    if file_path and _matches_ignore_files(file_path, config.get("ignore_files", [])):
        return True
    return False


def run_offensive_language_scan(
    content,
    *,
    config=None,
    file_path=None,
    tool_name=None,
    tool_identifier=None,
    latency_timer=None,
):
    """Run offensive language scan on content.

    Args:
        content: Text to scan.
        config: Pre-loaded scan_offensive config dict, or None to load internally.
        file_path: File path for ignore checks.
        tool_name: Tool name for ignore checks.
        tool_identifier: Tool identifier for skip checks.
        latency_timer: Optional _CheckTimer for performance tracking.

    Returns:
        None if scanner unavailable, disabled, or skipped.
        ScanResult with detection details otherwise.
    """
    if not HAS_OFFENSIVE_LANGUAGE:
        return None
    if not content:
        return None

    now = datetime.now(timezone.utc)
    if config is None:
        config, config_error = _loaders._load_offensive_language_config()
        if config_error:
            logger.warning(f"Offensive language config error: {config_error}")
    if not config or not is_feature_enabled(config.get("enabled"), now, default=False):
        return None

    if _should_skip_offensive_language_scan(config, tool_identifier, file_path):
        return None

    scanner = OffensiveLanguageScanner(config)
    action = config.get("action", "log")

    with (latency_timer or _NULL_TIMER).check("offensive_language"):
        findings = scanner.scan(content, file_path=file_path)

    result = ScanResult.from_offensive_language(
        findings=findings,
        action=action,
        file_path=file_path,
    )
    return result


def run_canary_detection_scan(
    content,
    source,
    *,
    config=None,
    latency_timer=None,
):
    """Run canary token detection scan on content.

    Args:
        content: Text to scan for canary tokens.
        source: Label for source (file path, tool name, etc.).
        config: Pre-loaded canary_detection config dict, or None to load internally.
        latency_timer: Optional _CheckTimer for performance tracking.

    Returns:
        None if scanner unavailable, disabled, no tokens configured, or no content.
        ScanResult with detection details otherwise.
    """
    if not HAS_CANARY_DETECTION:
        return None
    if not content:
        return None

    now = datetime.now(timezone.utc)
    if config is None:
        config, config_error = _loaders._load_canary_detection_config()
        if config_error:
            logger.warning(f"Canary detection config error: {config_error}")
    if not config or not is_feature_enabled(config.get("enabled"), now, default=False):
        return None
    if not config.get("tokens"):
        return None

    scanner = CanaryTokenScanner(config)

    with (latency_timer or _NULL_TIMER).check("canary_detection"):
        should_block, error_msg, detected = scanner.scan(content, source)

    result = ScanResult.from_canary_detection(
        should_block=should_block,
        error_message=error_msg,
        details=(
            {
                "matched_text": scanner.last_matched_text or "",
                "token": scanner.last_matched_token or "",
                "description": scanner.last_description or "",
                "line_number": scanner.last_line_number,
                "start_column": scanner.last_start_column,
                "end_column": scanner.last_end_column,
            }
            if detected
            else None
        ),
        source=source,
    )
    result.extra["action"] = config.get("action", "block")
    return result


def run_code_security_scan(
    content,
    file_path,
    *,
    config=None,
    latency_timer=None,
):
    """Run Bandit code security scan on Python content.

    Called from PreToolUse on Write/Edit tools when the target file is .py.

    Args:
        content: Python source code to scan (new_string for Edit, content for Write).
        file_path: Target file path.
        config: Pre-loaded code_scanning config dict, or None to load internally.
        latency_timer: Optional _CheckTimer for performance tracking.

    Returns:
        None if disabled or no Python file.
        ScanResult with detection details otherwise (one entry per finding).
    """
    if not content:
        return None
    if not file_path or not file_path.endswith(".py"):
        return None

    if config is None:
        try:
            from ai_guardian.config.loaders import _load_code_scanning_config

            config, config_error = _load_code_scanning_config()
            if config_error:
                logger.warning(f"Code scanning config error: {config_error}")
        except ImportError:
            config = {}

    if not config or not is_feature_enabled(config.get("enabled"), default=True):
        return None

    from ai_guardian.scanners.bandit_scanner import BanditScanner

    scanner = BanditScanner(config)

    with (latency_timer or _NULL_TIMER).check("code_security"):
        findings = scanner.scan(content, file_path=file_path)

    if not findings:
        return ScanResult.clean("code_security", file_path=file_path)

    # Wrap first finding; caller iterates all findings from scanner directly.
    # Store full list in extra for multi-finding consumers.
    first = findings[0]
    result = ScanResult(
        detected=True,
        violation_type="code_security",
        should_block=True,
        error_message=f"[{first.rule_id}] {first.description}",
        rule_id=first.rule_id,
        line_number=first.line_number,
        start_column=first.start_column,
        severity=first.severity,
        file_path=file_path,
        total_findings=len(findings),
    )
    result.extra["action"] = config.get("action", "warn")
    result.extra["all_findings"] = findings
    return result


def run_config_file_scan(
    file_path,
    content,
    *,
    config=None,
    latency_timer=None,
):
    """Run config file exfiltration scan on content.

    Args:
        file_path: File path being scanned.
        content: File content to scan.
        config: Pre-loaded config scanner config, or None to load internally.
        latency_timer: Optional _CheckTimer for performance tracking.

    Returns:
        None if scanner unavailable, disabled, or skipped.
        ScanResult with detection details otherwise.
    """
    if not HAS_CONFIG_SCANNER:
        return None
    if not file_path or not content:
        return None

    now = datetime.now(timezone.utc)
    if config is None:
        config, config_error = _loaders._load_config_scanner_config()
        if config_error:
            logger.warning(f"Config scanner config error: {config_error}")
    is_enabled = is_feature_enabled(
        config.get("enabled") if config else None, now, default=True
    )
    if not is_enabled:
        return None

    with (latency_timer or _NULL_TIMER).check("config_file_scanning"):
        should_block, error_msg, details = check_config_file_threats(
            file_path, content, config
        )

    result = ScanResult.from_config_exfil(
        should_block=should_block,
        error_message=error_msg,
        details=details,
        file_path=file_path,
    )
    result.extra["action"] = config.get("action", "block") if config else "block"
    result.extra["details"] = details
    return result


def run_bash_exfil_scan(
    command,
    *,
    config=None,
    latency_timer=None,
):
    """Run bash command exfiltration scan.

    Args:
        command: Bash command string to scan.
        config: Pre-loaded config scanner config, or None to load internally.
        latency_timer: Optional _CheckTimer for performance tracking.

    Returns:
        None if scanner unavailable, disabled, or skipped.
        ScanResult with detection details otherwise.
    """
    if not HAS_CONFIG_SCANNER:
        return None
    if not command:
        return None

    now = datetime.now(timezone.utc)
    if config is None:
        config, config_error = _loaders._load_config_scanner_config()
        if config_error:
            logger.warning(f"Config scanner config error: {config_error}")
    if not config or not is_feature_enabled(config.get("enabled"), now, default=True):
        return None

    with (latency_timer or _NULL_TIMER).check("bash_command_exfil_check"):
        should_block, error_msg, details = check_bash_command_threats(command, config)

    return ScanResult.from_config_exfil(
        should_block=should_block,
        error_message=error_msg,
        details=details,
    )


def run_exfil_detection_scan(
    command,
    *,
    config=None,
    latency_timer=None,
):
    """Run exfiltration behavior detection scan on a bash command.

    Args:
        command: Bash command string to scan.
        config: Pre-loaded exfil detection config, or None to load internally.
        latency_timer: Optional _CheckTimer for performance tracking.

    Returns:
        None if scanner unavailable, disabled, or skipped.
        ScanResult with detection details otherwise.
    """
    if not HAS_EXFIL_DETECTION:
        return None
    if not command:
        return None

    now = datetime.now(timezone.utc)
    if config is None:
        config, config_error = _loaders._load_exfil_detection_config()
        if config_error:
            logger.warning(f"Exfil detection config error: {config_error}")
    if not config or not is_feature_enabled(config.get("enabled"), now, default=True):
        return None

    with (latency_timer or _NULL_TIMER).check("exfil_detection"):
        should_block, error_msg, details = ExfilDetectionScanner(config).check_command(
            command
        )

    result = ScanResult.from_exfil_detection(
        should_block=should_block,
        error_message=error_msg,
        details=details,
    )
    result.extra["action"] = config.get("action", "block")
    result.extra["details"] = details
    return result


def run_image_scan(
    file_path,
    *,
    config=None,
    tool_identifier=None,
    latency_timer=None,
):
    """Run image scanning (OCR text extraction) on an image file.

    Args:
        file_path: Path to image file to scan.
        config: Pre-loaded image scanning config, or None to load internally.
        tool_identifier: Tool identifier for ignore checks.
        latency_timer: Optional _CheckTimer for performance tracking.

    Returns:
        None if scanner unavailable, disabled, skipped, or not an image file.
        Tuple of (extracted_text, image_scan_result) otherwise.
        extracted_text may be empty string if OCR found nothing.
    """
    from ai_guardian.hook_processing import _matches_ignore_files

    if not HAS_IMAGE_SCANNER:
        return None
    if not file_path or not ImageDetector.is_image_file(file_path):
        return None

    now = datetime.now(timezone.utc)
    if config is None:
        config, config_error = _loaders._load_image_scanning_config()
        if config_error:
            logger.warning(f"Image scanning config error: {config_error}")
    if not config or not is_feature_enabled(
        config.get("enabled", True), now, default=True
    ):
        return None

    ignore_files = config.get("ignore_files", [])
    ignore_tools = config.get("ignore_tools", [])
    if _matches_ignore_files(file_path, ignore_files):
        logger.info(f"Image scanning skipped for {file_path} (ignore pattern match)")
        return None
    if tool_identifier and ignore_tools:
        for pattern in ignore_tools:
            if fnmatch.fnmatch(tool_identifier, pattern):
                logger.info(
                    f"Image scanning skipped for {file_path} (ignore pattern match)"
                )
                return None

    logger.info(f"Image file detected: {file_path}, running OCR scan...")
    with open(file_path, "rb") as f:
        image_data = f.read()

    with (latency_timer or _NULL_TIMER).check("image_scanning"):
        result = scan_image(image_data, config)

    logger.info(
        f"OCR extracted {len(result.extracted_text)} chars "
        f"in {result.elapsed_ms:.0f}ms"
    )

    extracted_text = result.extracted_text or ""
    if result.qr_texts:
        qr_text = "\n".join(result.qr_texts)
        extracted_text = f"{extracted_text}\n{qr_text}" if extracted_text else qr_text

    return extracted_text, result


def run_pii_scan(
    content,
    *,
    config=None,
    file_path=None,
    tool_name=None,
    tool_identifier=None,
    latency_timer=None,
):
    """Run PII scan on content.

    Args:
        content: Text to scan for PII.
        config: Pre-loaded PII config dict, or None to load internally.
        file_path: File path for ignore checks and violation context.
        tool_name: Tool name for ignore checks.
        tool_identifier: Tool identifier for skip checks.
        latency_timer: Optional _CheckTimer for performance tracking.

    Returns:
        None if scanner disabled or skipped.
        ScanResult with redacted_content and redactions if scanned.
    """
    from ai_guardian.hook_processing import _should_skip_pii_scan, _scan_for_pii

    if not content:
        return None

    now = datetime.now(timezone.utc)
    if config is None:
        config, config_error = _loaders._load_pii_config()
        if config_error:
            logger.warning(f"PII config error: {config_error}")
    if not config or not is_feature_enabled(config.get("enabled"), now, default=True):
        return None

    if _should_skip_pii_scan(config, tool_identifier, file_path):
        return ScanResult.clean("pii_detected", extra={"skipped": True})

    with (latency_timer or _NULL_TIMER).check("pii_detection"):
        has_pii, redacted_text, redactions, warning = _scan_for_pii(
            content, config, file_path=file_path
        )

    result = ScanResult.from_pii_scan(
        has_pii=has_pii,
        redacted_text=redacted_text,
        redactions=redactions,
        warning_message=warning,
        file_path=file_path,
    )
    result.extra["action"] = config.get("action", "block")
    return result


def run_secret_scan(
    content,
    filename="temp_file",
    *,
    config=None,
    context=None,
    file_path=None,
    tool_name=None,
    ignore_files=None,
    ignore_tools=None,
    allowlist_patterns=None,
    latency_timer=None,
):
    """Run secret scan on content using gitleaks/scanner engines.

    Args:
        content: Text to scan for secrets.
        filename: Label for the content being scanned.
        config: Pre-loaded secret scanning config dict, or None to load.
        context: Additional context dict for violation logging.
        file_path: File path for ignore checks.
        tool_name: Tool name for ignore checks.
        ignore_files: Ignore file patterns (extracted from config if None).
        ignore_tools: Ignore tool patterns (extracted from config if None).
        allowlist_patterns: Secret allowlist patterns (extracted from config if None).
        latency_timer: Optional _CheckTimer for performance tracking.

    Returns:
        None if scanner disabled or no content.
        ScanResult with secret detection details otherwise.
    """
    if not content:
        return None

    now = datetime.now(timezone.utc)
    if config is None:
        config, config_error = _loaders._load_secret_scanning_config()
        if config_error:
            logger.warning(f"Secret scanning config error: {config_error}")
    if config and not is_feature_enabled(config.get("enabled"), now, default=True):
        return None

    if ignore_files is None:
        ignore_files = config.get("ignore_files", []) if config else []
    if ignore_tools is None:
        ignore_tools = config.get("ignore_tools", []) if config else []
    if allowlist_patterns is None:
        allowlist_patterns = config.get("allowlist_patterns", []) if config else []

    with (latency_timer or _NULL_TIMER).check("secret_scanning"):
        has_secrets, error_message = _secret_scanning_mod.check_secrets(
            content,
            filename,
            context=context,
            file_path=file_path,
            tool_name=tool_name,
            ignore_files=ignore_files,
            ignore_tools=ignore_tools,
            allowlist_patterns=allowlist_patterns,
            secret_config=config,
        )

    result = ScanResult.from_secret_scan(
        has_secrets=has_secrets,
        error_message=error_message,
        matched_text=_secret_scanning_mod._last_secret_matched_text or "",
        line_number=_secret_scanning_mod._last_secret_line_number,
        start_column=_secret_scanning_mod._last_secret_start_column,
        findings=(
            _secret_scanning_mod._last_secret_findings
            if _secret_scanning_mod._last_secret_findings
            else None
        ),
        file_path=file_path,
    )
    return result


def run_directory_check(
    file_path,
    *,
    config=None,
):
    """Run directory rules check on a file path.

    Args:
        file_path: File path to check against directory rules.
        config: Pre-loaded config dict, or None to use global config.

    Returns:
        None if no file path provided.
        ScanResult with directory blocking details otherwise.
    """
    from ai_guardian.hook_processing import _check_directory_rules

    if not file_path:
        return None

    decision, action, matched_pattern = _check_directory_rules(file_path, config)
    return ScanResult.from_directory_rules(
        decision=decision,
        action=action,
        matched_pattern=matched_pattern,
        file_path=file_path,
    )
