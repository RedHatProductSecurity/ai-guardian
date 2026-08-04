"""Default configuration creation for ai-guardian."""

import json
from importlib.resources import files
from pathlib import Path
from typing import Dict, Optional, Tuple

from ai_guardian.config.utils import get_cache_dir, get_config_dir
from ai_guardian.setup.utils import _strip_deprecated_config_keys


def create_default_config(
    permissive: bool = False,
    dry_run: bool = False,
    json_output: bool = False,
    profile: Optional[str] = None,
    force: bool = False,
) -> Tuple[bool, str]:
    """
    Create default ai-guardian.json config file.

    Args:
        permissive: If True, use permissive config (permissions disabled)
        dry_run: If True, show what would be created without writing
        json_output: If True, output only the raw JSON config
        profile: Optional security profile name to apply
        force: If True, overwrite existing config file

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        config_dir = get_config_dir()
        config_path = config_dir / "ai-guardian.json"

        # Generate config based on mode
        if profile:
            from ai_guardian.profile_manager import load_profile, ProfileNotFoundError

            try:
                config = load_profile(profile)
            except ProfileNotFoundError as e:
                return False, str(e)
            except json.JSONDecodeError as e:
                return False, f"Invalid JSON in profile: {e}"
        else:
            config = _get_default_config_template(permissive)

        config = _strip_deprecated_config_keys(config)

        if json_output:
            return True, json.dumps(config, indent=2)

        # Check if config already exists
        if config_path.exists() and not dry_run:
            if not force:
                return True, f"✓ Config already exists, preserving: {config_path}"

        if dry_run:
            message = f"[DRY RUN] Would create {config_path}:\n\n"
            message += json.dumps(config, indent=2)
            return True, message

        # Ensure directory exists
        config_dir.mkdir(parents=True, exist_ok=True)
        get_cache_dir().mkdir(parents=True, exist_ok=True)

        # Write config
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
            f.write("\n")

        if profile:
            message = f"✓ Created config from profile '{profile}': {config_path}\n"
            pi_sensitivity = config.get("prompt_injection", {}).get(
                "sensitivity", "medium"
            )
            on_error = config.get("on_scan_error", "allow")
            perms = config.get("permissions", {}).get("enabled", True)
            message += "\n  Security settings:\n"
            message += f"  • Prompt injection sensitivity: {pi_sensitivity}\n"
            message += f"  • On scan error: {on_error}\n"
            message += f"  • Permissions: {'Enabled' if perms else 'Disabled'}\n"
        else:
            message = f"✓ Created default config: {config_path}\n"
            message += "\n  Security settings:\n"
            message += "  • Secret scanning: Enabled (LeakTK patterns)\n"
            message += "  • Prompt injection: Enabled (medium sensitivity)\n"
            message += "  • SSRF protection: Enabled (blocks private IPs, metadata endpoints)\n"

            if permissive:
                message += "  • Permissions: Disabled (all tools allowed)\n"
            else:
                message += "  • Permissions: Enabled (Skills/MCP blocked by default)\n"

        message += "\n  Next steps:\n"
        message += "  1. Run 'ai-guardian console' to configure allowed skills\n"
        message += f"  2. Or edit {config_path} manually\n"

        return True, message

    except Exception as e:
        return False, f"Error creating default config: {e}"


def _get_default_config_template(permissive: bool = False) -> Dict:
    """
    Get default config template based on mode.

    Args:
        permissive: If True, return permissive config (permissions disabled)

    Returns:
        dict: Default configuration
    """
    schema_path = files("ai_guardian") / "schemas" / "ai-guardian-config.schema.json"
    schema_uri = Path(str(schema_path)).as_uri()

    config = {
        "$schema": schema_uri,
        "_comment_project_overlay": "Project-level .ai-guardian/ai-guardian.json at repo root merges on top of this global config. Use immutable arrays to lock fields from project override.",
        "_comment_secret_scanning": "Scan for secrets (API keys, tokens, passwords). Detection always blocks — use allowlist_patterns for false positives. Supported engines: gitleaks, betterleaks, leaktk, trufflehog, detect-secrets, secretlint, gitguardian",
        "secret_scanning": {
            "enabled": True,
            "ignore_files": [],
            "ignore_tools": [],
            "allowlist_patterns": [],
            "_comment_engines": "Engines tried in order. Built-in: gitleaks, betterleaks, leaktk, trufflehog, detect-secrets, secretlint, gitguardian. Python-based custom scanners: {type: python, module/path: ..., class: ...}. Cloud engines (gitguardian) require consent: ai-guardian engine consent gitguardian",
            "engines": [
                {"type": "toml-patterns"},
                {
                    "type": "gitleaks",
                    "binary": "gitleaks",
                    "pattern_server": {
                        "url": "https://raw.githubusercontent.com/leaktk/patterns/main/target",
                        "patterns_endpoint": "/patterns/gitleaks/8.27.0",
                        "warn_on_failure": True,
                        "cache": {
                            "refresh_interval_hours": 12,
                            "expire_after_hours": 168,
                        },
                    },
                },
            ],
            "_comment_strategy": "Strategies: first-match (default), any-match (block if ANY finds secrets), consensus (block only if N agree)",
            "execution_strategy": "first-match",
            "consensus_threshold": 2,
            "_comment_cache": "Result caching: skip re-scanning unchanged content (v1.7.0+)",
            "cache_results": False,
            "cache_ttl_hours": 24,
            "_comment_incremental": "Incremental scanning: only scan files whose content changed (v1.7.0+, requires cache_results)",
            "incremental": False,
            "_comment_audit": "Audit logging: log all scan operations for compliance (v1.7.0+)",
            "audit_logging": False,
            "_comment_validate_secrets": "Secret liveness validation: check if detected secrets are still active (v1.11.0+). PRIVACY: sends secrets to provider APIs. Requires explicit opt-in.",
            "validate_secrets": False,
            "validation_timeout_ms": 3000,
            "on_inactive": "warn",
            "_comment_entropy": "Minimum Shannon entropy for secret matches. Range: 0.0 (identical chars) to ~6.0 (fully random). 3.0 filters placeholders while keeping real secrets (4.0+). Set to null to disable.",
            "min_entropy": 3.0,
            "_comment_stopwords": "Additional stopwords MERGED with bundled list (example, test, sample, placeholder, etc.). Never replaces bundled words. Case-insensitive substring match. Min word length: 3.",
            "stopwords": [],
        },
        "_comment_prompt_injection": "Detect and block prompt injection attacks that try to manipulate AI behavior",
        "prompt_injection": {
            "enabled": True,
            "action": "block",
            "detector": "heuristic",
            "sensitivity": "medium",
            "max_score_threshold": 0.75,
            "allowlist_patterns": [],
            "custom_patterns": [],
            "jailbreak_patterns": [],
            "ignore_tools": [],
            "ignore_files": [],
            "unicode_detection": {
                "enabled": True,
                "detect_zero_width": True,
                "detect_bidi_override": True,
                "detect_tag_chars": True,
                "detect_homoglyphs": True,
                "allow_rtl_languages": True,
                "allow_emoji": True,
            },
            "_comment_auto_download_model": "Automatically download ML models when the daemon starts and ml_engines is configured. Set to false to disable outbound downloads.",
            "auto_download_model": True,
        },
        "_comment_secret_redaction": "Redact secrets from tool outputs instead of blocking (NEW in v1.5.0, Phase 4)",
        "secret_redaction": {
            "enabled": True,
            "action": "warn",
            "preserve_format": True,
            "log_redactions": True,
            "additional_patterns": [],
        },
        "_comment_scan_pii": "PII detection for GDPR/CCPA compliance (v1.6.0+). Phase 1: SSN, credit card, phone, US passport, IBAN, international phone. Phase 2 defaults (v1.10.0): medical_id, passport, uk_nin. Opt-in: canada_sin, india_aadhaar, address, email.",
        "scan_pii": {
            "enabled": True,
            "pii_types": [
                "ssn",
                "credit_card",
                "phone",
                "us_passport",
                "iban",
                "intl_phone",
                "medical_id",
                "passport",
                "uk_nin",
            ],
            "action": "block",
            "ignore_files": [],
            "ignore_tools": [],
            "allowlist_patterns": [],
            "pattern_server": None,
        },
        "_comment_scan_offensive": "Offensive language scanner (NEW in v1.13.0, Issue #1417). Detects profanity, slurs, and non-inclusive terminology. Disabled by default — opt in via enabled: true. Use categories to enable only the checks you need.",
        "scan_offensive": {
            "enabled": False,
            "action": "log",
            "categories": ["profanity", "slurs", "inclusive_language"],
            "ignore_files": [],
            "ignore_tools": [],
            "allowlist_patterns": [],
        },
        "_comment_image_scanning": "OCR-based image scanning for secrets and PII (NEW in v1.10.0, Issue #720). Scans image files for embedded secrets before they reach the AI model.",
        "image_scanning": {
            "enabled": True,
            "action": "block",
            "scan_types": ["secrets", "pii"],
            "max_processing_ms": 1500,
            "min_confidence": 0.5,
            "redaction_method": "blur",
            "qr_scanning": False,
            "face_detection": False,
            "ignore_files": [],
            "ignore_tools": [],
            "max_image_size_mb": 10,
        },
        "_comment_ssrf_protection": "Prevent SSRF attacks by blocking access to private networks, metadata endpoints, and dangerous URL schemes (NEW in v1.5.0)",
        "ssrf_protection": {
            "enabled": True,
            "action": "block",
            "additional_blocked_ips": [],
            "additional_blocked_domains": [],
            "allow_localhost": False,
            "allowed_domains": [],
            "_comment_allowed_domains": "Domain allow-list. Supports exact strings, subdomain matching, and regex patterns (e.g., '.*\\.example\\.com', 'localhost:19200')",
            "_comment_path_based_rules": "Path-based filtering for granular access control (NEW in v1.6.0) - Allow/block specific URL paths on domains",
            "path_based_rules": [],
            "ignore_files": [],
            "ignore_tools": [],
        },
        "_comment_config_file_scanning": "Detect credential exfiltration commands in AI config files (CLAUDE.md, AGENTS.md, etc.) - Phase 3 of Hermes integration (NEW in v1.5.0)",
        "config_file_scanning": {
            "enabled": True,
            "action": "block",
            "additional_files": [],
            "ignore_files": [],
            "ignore_tools": [],
            "additional_patterns": [],
        },
        "_comment_supply_chain": "Detect malicious patterns in agent config files — hooks, MCP servers, and plugin files (NEW in v1.11.0, Issue #1055)",
        "supply_chain": {
            "enabled": True,
            "action": "block",
            "scan_hooks": True,
            "scan_mcp_configs": True,
            "scan_plugins": True,
            "allowlist_paths": [],
        },
        "_comment_code_scanning": "Python code security scanning with Bandit — detects insecure patterns (eval, subprocess shell injection, weak crypto, SQL injection, etc.) (NEW in v1.13.0, Issue #828)",
        "code_scanning": {
            "enabled": True,
            "action": "warn",
            "severity_threshold": "MEDIUM",
            "allowlist": [],
            "ignore_files": [],
        },
        "_comment_canary_detection": "Canary token detection — detects user-registered tripwire values in AI output to catch data exfiltration (NEW in v1.14.0, Issue #1392). Disabled by default — add your own tokens to enable.",
        "canary_detection": {
            "enabled": False,
            "action": "block",
            "tokens": [],
        },
        "_comment_exfil_detection": "Exfiltration behavior detection — detects bash commands that steal credentials: curl/wget with token vars, base64 encoding of secrets, key file theft, cloud credential exfil (NEW in v1.14.0, Issue #1393).",
        "exfil_detection": {
            "enabled": True,
            "action": "block",
            "allowlist_patterns": [],
        },
        "_comment_permissions": "Control which tools (Skills, MCP servers, Bash, etc.) are allowed to run. Rules evaluated in order, last match wins.",
        "permissions": {
            "enabled": not permissive,
            "auto_directory_rules": {"enabled": False, "allow_symlinks": True},
            "rules": (
                [
                    {
                        "_comment": "Allow all tools — minimal profile has no restrictions",
                        "matcher": "*",
                        "mode": "allow",
                        "patterns": ["*"],
                    }
                ]
                if permissive
                else [
                    {
                        "_comment": "Allow all tools by default (built-in tools like Bash, Read, Write, Edit)",
                        "matcher": "*",
                        "mode": "allow",
                        "patterns": ["*"],
                    },
                    {
                        "_comment": "Warn on unknown MCP servers (new servers allowed with warning)",
                        "matcher": "mcp__*",
                        "mode": "deny",
                        "patterns": ["*"],
                        "action": "warn",
                    },
                    {
                        "_comment": "Allow ai-guardian MCP server (no warning needed)",
                        "matcher": "mcp__ai-guardian__*",
                        "mode": "allow",
                        "patterns": ["*"],
                    },
                    {
                        "_comment": "Warn on unknown Skills",
                        "matcher": "Skill",
                        "mode": "deny",
                        "patterns": ["*"],
                        "action": "warn",
                    },
                ]
            ),
        },
        "_comment_permissions_directories": "OPTIONAL/ADVANCED: Auto-discover tool permissions from directories/GitHub repos. Scans for permission files and merges discovered rules into permissions.rules. Most users should use remote_configs instead.",
        "_permissions_directories_example": [
            {
                "_comment": "Example: scan local skills directory to auto-allow discovered skills",
                "matcher": "Skill",
                "mode": "allow",
                "url": "~/.claude/skills",
            },
            {
                "_comment": "Example: scan GitHub repository for skills",
                "matcher": "Skill",
                "mode": "allow",
                "url": "https://github.com/your-org/skills/tree/main/skills",
                "token_env": "GITHUB_TOKEN",
            },
        ],
        "_comment_directory_rules": "OPTIONAL: Control AI access to specific directories (e.g., block ~/.ssh). Last-match-wins evaluation order. See ai-guardian-example.json for examples.",
        "directory_rules": {"action": "block", "rules": []},
        "_comment_remote_configs": "Load additional policies from remote URLs (for enterprise/team policies)",
        "remote_configs": {"urls": []},
        "_comment_console": "Console settings (editor theme, web console)",
        "console": {
            "editor_theme": "monokai",
            "preferred_theme": "default",
            "web": {"port": 0, "host": "127.0.0.1"},
        },
        "_comment_transcript_scanning": "Scan conversation transcript for secrets, PII, and prompt injection from ! shell commands (NEW in v1.7.0, Issue #430)",
        "transcript_scanning": {
            "enabled": True,
        },
        # ai-guardian:begin-allow
        "_comment_annotations": "Inline annotation suppression for secrets and PII (NEW in v1.8.0, Issue #481). "
        "Hardcoded: ai-guardian:allow (inline), ai-guardian:begin-allow/end-allow (block). "
        "Configurable aliases: inline_allow (secrets+PII), inline_allow_secrets (secrets only). "
        "Prompt injection, jailbreak, config exfil always scanned. "
        "Set enabled to false for strict compliance environments.",
        # ai-guardian:end-allow
        "annotations": {
            "enabled": True,
            "inline_allow": [],
            "inline_allow_secrets": ["gitleaks:allow"],
            "block_begin": [],
            "block_end": [],
        },
        "_comment_latency_tracking": "Hook latency tracking — records per-hook timing to latency.jsonl for performance analysis. Disabled by default. (NEW in v1.11.0, Issue #1057)",
        "latency_tracking": {
            "enabled": False,
            "max_entries": 5000,
            "retention_days": 30,
        },
        "_comment_violation_logging": "Log blocked operations for audit and review (NEW in v1.1.0)",
        "violation_logging": {
            "enabled": True,
            "max_entries": 1000,
            "retention_days": 30,
            "log_types": [
                "tool_permission",
                "directory_blocking",
                "secret_detected",
                "secret_redaction",
                "prompt_injection",
                "jailbreak_detected",
                "ssrf_blocked",
                "config_file_exfil",
                "pii_detected",
                "secret_in_transcript",
                "pii_in_transcript",
                "prompt_injection_in_transcript",
                "annotation_suppressed",
                "image_secret_detected",
                "image_pii_detected",
                "supply_chain",
            ],
        },
        "_comment_daemon": "Background daemon for faster hook processing. Auto-starts on any command, falls back to direct if unavailable.",
        "daemon": {
            "idle_timeout_minutes": 0,
            "client_timeout_seconds": 2.0,
            "tray": {
                "enabled": True,
                "auto_install": True,
                "_comment_terminal_app": "Preferred terminal for tray menu actions. macOS: app name (iTerm, Warp, alacritty). Linux: binary (alacritty, kitty). Windows: exe (wt). Omit for auto-detect.",
            },
        },
        "_comment_on_scan_error": "Global behavior when a scanner encounters an error. 'allow' (default, fail-open): log warning, allow operation. 'block' (fail-closed): block operation if any scanner fails. For strict compliance environments. (NEW in v1.7.0, Issue #461)",
        "on_scan_error": "allow",
        "_comment_security_instructions": "Security rule injection into AI context via systemMessage. Injected on first UserPromptSubmit per session and re-injected after blocks. Customize with custom_rules or replace_defaults. Disable only for ai-guardian development. (v1.7.0 #580, v1.8.0 #584, v1.13.0 #1460)",
        "security_instructions": {
            "inject_on_prompt": True,
            "inject_trigger": "first_per_session",
            "custom_rules": [],
            "replace_defaults": False,
        },
        "_comment_mcp_server": "MCP security advisor server. Exposes read-only security tools for AI agents. Installed by default during setup. Use --no-mcp to skip. (NEW in v1.7.0, Issue #477)",
        "mcp_server": {
            "proactive_level": "low",
        },
        "_comment_support": "Support bundle export. Two-step process: prepare (sanitize + review) then send (with user approval). Destination: local path, S3 URI, GCS URI (gs://bucket-name/), or email (mailto:support@company.com). (NEW in v1.7.0, Issue #477; email: Issue #932)",
        "support": {
            "export_destination": "",
            "auth": {
                "method": "none",
                "token_env": "",
            },
            "_comment_email": "SMTP email settings for mailto: destinations. Zero new dependencies (Python stdlib only).",
            "email": {
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_tls": True,
                "from": "",
                "subject_prefix": "[AI Guardian Support]",
                "auth": {
                    "method": "none",
                    "username_env": "",
                    "password_env": "",
                },
            },
            "bundle_ttl_minutes": 30,
        },
    }

    return config
