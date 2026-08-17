#!/usr/bin/env python3
"""
Main Console Application

Provides interactive text-based interface for AI Guardian configuration.
Sidebar tree navigation with grouped sections and content switching.
"""

import base64
import subprocess
import sys
from typing import Optional, Tuple

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import (
    Footer,
    Header,
    Tree,
    ContentSwitcher,
    Button,
    Input,
    Static,
)
from textual.screen import ModalScreen
from textual.binding import Binding
from textual import events

from ai_guardian import theme as _theme


def copy_osc52(text: str) -> bool:
    """Copy to clipboard via OSC 52 escape sequence.

    Works in terminals that support it (iTerm2, kitty, alacritty, WezTerm,
    foot, Windows Terminal). Does NOT work in macOS Terminal.app or older
    GNOME Terminal.
    """
    try:
        encoded = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        sys.stdout.write(f"\033]52;c;{encoded}\a")
        sys.stdout.flush()
        return True
    except Exception:
        return False


def _try_clipboard_command(cmd: list, text: str, encoding: str = "utf-8") -> bool:
    """Try a clipboard command, returning True on success."""
    try:
        subprocess.run(
            cmd,
            input=text.encode(encoding),
            check=True,
            capture_output=True,
            timeout=5,
        )
        return True
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return False


def copy_to_system_clipboard(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Copy text to the system clipboard using platform-native commands.

    Returns a (error, method) tuple:
      - On success: (None, method_name) e.g. (None, "pbcopy")
      - On failure: (error_message, None)
    """
    if sys.platform == "darwin":
        if _try_clipboard_command(["pbcopy"], text):
            return (None, "pbcopy")
    elif sys.platform == "win32":
        if _try_clipboard_command(["clip"], text, encoding="utf-16le"):
            return (None, "clip")
    elif sys.platform.startswith("linux"):
        if _try_clipboard_command(
            ["xclip", "-selection", "clipboard"],
            text,
        ):
            return (None, "xclip")
        if _try_clipboard_command(
            ["xsel", "--clipboard", "--input"],
            text,
        ):
            return (None, "xsel")
        if _try_clipboard_command(["wl-copy"], text):
            return (None, "wl-copy")
        return (
            "Copied via terminal escape sequence. "
            "For reliable clipboard, install xclip, xsel, or wl-copy",
            None,
        )
    else:
        if copy_osc52(text):
            return (None, "OSC 52")
        return ("Clipboard not supported on this platform", None)

    if copy_osc52(text):
        return (None, "OSC 52")
    return ("Clipboard command failed", None)


PANEL_TO_CONFIG_SECTION = {
    "panel-secrets": "secret_scanning",
    "panel-secret-engines": "secret_scanning",
    "panel-secret-redaction": "secret_redaction",
    "panel-scan-pii": "scan_pii",
    "panel-pi-detection": "prompt_injection",
    "panel-pi-ml-engines": "prompt_injection",
    "panel-pi-patterns": "prompt_injection",
    "panel-pi-jailbreak": "prompt_injection",
    "panel-pi-unicode": "prompt_injection",
    "panel-ssrf": "ssrf_protection",
    "panel-config-scanner": "config_file_scanning",
    "panel-context-poisoning": "context_poisoning",
    "panel-supply-chain": "supply_chain",
    "panel-code-security": "code_scanning",
    "panel-offensive-language": "scan_offensive",
    "panel-canary-detection": "canary_detection",
    "panel-exfil-detection": "exfil_detection",
    "panel-annotations": "annotations",
    "panel-skills": "permissions",
    "panel-directory-rules": "directory_rules",
    "panel-violation-logging": "violation_logging",
    "panel-performance": "latency_tracking",
}


def _is_feature_enabled(config, section_key):
    """Check if a feature/scanner is enabled in config."""
    section = config.get(section_key, {})
    if isinstance(section, dict):
        enabled = section.get("enabled", True)
        if isinstance(enabled, dict):
            return bool(enabled.get("value", True))
        return bool(enabled)
    return True


# ai-guardian:begin-allow
NAV_GROUPS = [
    (
        "Security Overview",
        [
            ("Security Dashboard", "panel-security-dashboard"),
            ("Global Settings", "panel-global-settings"),
            ("Health Check", "panel-health-check"),
        ],
    ),
    (
        "Monitoring",
        [
            ("Violations", "panel-violations"),
            ("Violation Logging", "panel-violation-logging"),
            ("Metrics & Audit", "panel-metrics"),
            ("Performance", "panel-performance"),
            ("Logs", "panel-logs"),
        ],
    ),
    (
        "AI Sessions",
        [
            ("IDE Sessions", "panel-ide-sessions"),
            ("SDK Traces", "panel-traces"),
            ("OTEL Export", "panel-otel-settings"),
        ],
    ),
    (
        "SDK",
        [
            ("Agent Profiles", "panel-sdk-agents"),
            ("SDK Settings", "panel-sdk-settings"),
        ],
    ),
    (
        "Permissions",
        [
            ("Skills", "panel-skills"),
            ("MCP Servers", "panel-mcp"),
            ("Permissions Discovery", "panel-permissions-discovery"),
            ("Auto Directory Rules", "panel-auto-directory-rules"),
            ("Directory Rules", "panel-directory-rules"),
        ],
    ),
    (
        "Secrets",
        [
            ("Secret Scanning", "panel-secrets"),
            ("Engine Configuration", "panel-secret-engines"),
            ("Secret Redaction", "panel-secret-redaction"),
        ],
    ),
    (
        "Prompt Injection",
        [
            ("Detection Settings", "panel-pi-detection"),
            ("ML Engines", "panel-pi-ml-engines"),
            ("Patterns", "panel-pi-patterns"),
            ("Jailbreak", "panel-pi-jailbreak"),
            ("Unicode Detection", "panel-pi-unicode"),
        ],
    ),
    (
        "Threat Detection",
        [
            ("SSRF Protection", "panel-ssrf"),
            ("Context Poisoning", "panel-context-poisoning"),
            ("Supply Chain", "panel-supply-chain"),
            ("Config Scanner", "panel-config-scanner"),
            ("PII Detection", "panel-scan-pii"),
            ("Code Security", "panel-code-security"),
            ("Offensive Language", "panel-offensive-language"),
            ("Canary Detection", "panel-canary-detection"),
            ("Exfil Detection", "panel-exfil-detection"),
            ("Annotations", "panel-annotations"),
        ],
    ),
    (
        "Configuration",
        [
            ("Security Instructions", "panel-security-instructions"),
            ("Remote Configs", "panel-remote-configs"),
            ("Config Cache", "panel-cache-status"),
            ("Config File", "panel-config-file"),
            ("Config Editor", "panel-config-editor"),
            ("Console Settings", "panel-console-settings"),
            ("Effective Config", "panel-config-effective"),
            ("Daemon", "panel-daemon"),
            ("About", "panel-about"),
        ],
    ),
    (
        "Tools",
        [
            ("Detection Patterns", "panel-detection-patterns"),
            ("Regex Tester", "panel-regex-tester"),
            ("Hook Simulator", "panel-hook-simulator"),
            ("Engine Tester", "panel-engine-tester"),
            ("Directory Scan", "panel-directory-scan"),
            ("Scan Configure", "panel-scan-configure"),
            ("MCP Security", "panel-mcp-security"),
        ],
    ),
]


HELP_DOCS = {
    # Category-level help
    "Security Overview": (
        "[bold]Security Overview[/bold]\n\n"
        "Central hub for monitoring and configuring AI Guardian's "
        "security posture.\n\n"
        "[bold]Sections:[/bold]\n"
        "  [bold]Security Dashboard[/bold] — At-a-glance status of all "
        "security features with violation analytics\n"
        "  [bold]Global Settings[/bold] — Master toggles for permissions "
        "enforcement and secret scanning\n"
        "  [bold]Health Check[/bold] — System health checks "
        "(ai-guardian doctor) with auto-fix support"
    ),
    "Permissions": (
        "[bold]Permissions[/bold]\n\n"
        "Control what Claude Code is allowed to do. Permissions are "
        "evaluated as allow/deny rules matched against tool names "
        "and directory paths.\n\n"
        "[bold]Sections:[/bold]\n"
        "  [bold]Skills[/bold] — Manage allow/deny patterns for Claude "
        "Code skills (slash commands)\n"
        "  [bold]MCP Servers[/bold] — Manage permissions for MCP server "
        "tool invocations\n"
        "  [bold]Permissions Discovery[/bold] — Review tool calls that "
        "don't match any existing rule\n"
        "  [bold]Directory Rules[/bold] — Control which file paths "
        "Claude Code can access (allow/deny)"
    ),
    "Threat Detection": (
        "[bold]Threat Detection[/bold]\n\n"
        "Detect and block malicious content in prompts, tool inputs, "
        "and tool outputs.\n\n"
        "[bold]Sections:[/bold]\n"
        "  [bold]Prompt Injection[/bold] — Detect jailbreak attempts, "
        "obfuscation, and Unicode attacks\n"
        "  [bold]SSRF Protection[/bold] — Block requests to private IPs, "
        "internal networks, and cloud metadata\n"
        "  [bold]Config Scanner[/bold] — Detect exfiltration of sensitive "
        "config files (CLAUDE.md, .env, etc.)"
    ),
    "Secrets": (
        "[bold]Secrets[/bold]\n\n"
        "Prevent secret leakage in AI-assisted development.\n\n"
        "[bold]Sections:[/bold]\n"
        "  [bold]Secret Scanning[/bold] — Scan tool outputs for API keys, "
        "tokens, and credentials using scanner engines\n"
        "  [bold]Secret Redaction[/bold] — Automatically redact detected "
        "secrets before they reach the AI model"
    ),
    "Monitoring": (
        "[bold]Monitoring[/bold]\n\n"
        "Track security events and review audit logs.\n\n"
        "[bold]Sections:[/bold]\n"
        "  [bold]Violations[/bold] — Browse, filter, and approve recent "
        "security violations\n"
        "  [bold]Metrics[/bold] — Violation statistics, trends, and "
        "breakdowns by type, severity, and action\n"
        "  [bold]Logs[/bold] — View AI Guardian's runtime log output"
    ),
    "Configuration": (
        "[bold]Configuration[/bold]\n\n"
        "Manage AI Guardian's configuration files and settings.\n\n"
        "[bold]Sections:[/bold]\n"
        "  [bold]Remote Configs[/bold] — Manage remote configuration "
        "sources (URLs, update schedules)\n"
        "  [bold]Config File[/bold] — View raw JSON config files\n"
        "  [bold]Config Editor[/bold] — Edit config with syntax "
        "highlighting and validation\n"
        "  [bold]Console Settings[/bold] — Editor theme and display "
        "preferences\n"
        "  [bold]Effective Config[/bold] — View resolved runtime "
        "configuration"
    ),
    "Tools": (
        "[bold]Tools[/bold]\n\n"
        "Utility tools for testing and debugging AI Guardian "
        "security patterns.\n\n"
        "[bold]Sections:[/bold]\n"
        "  [bold]Regex Tester[/bold] — Interactively test regex "
        "patterns with ReDoS validation and config integration\n"
        "  [bold]Hook Simulator[/bold] — Test detection rules against "
        "simulated hook events without triggering real hooks\n"
        "  [bold]Engine Tester[/bold] — Test strings against individual "
        "scanner engines to compare detection results\n"
        "  [bold]Directory Scan[/bold] — Scan directories for security "
        "issues with interactive results and export\n"
        "  [bold]MCP Security[/bold] — Audit MCP server configurations "
        "for credential exposure and supply chain risks"
    ),
    # Panel-level help
    "panel-security-dashboard": (
        "[bold]Security Dashboard[/bold]\n\n"
        "Overview of all security features and their current status.\n\n"
        "[bold]Features:[/bold]\n"
        "  - Feature status cards showing enabled/disabled state\n"
        "  - Recent violation summary with counts by category\n"
        "  - Quick enable/disable toggles for each feature\n\n"
        "[bold]⚠ Known Limitation:[/bold]\n"
        "  Commands run with the '!' prefix in Claude Code bypass all\n"
        "  ai-guardian hooks. Do not use '!' to display secrets or read\n"
        "  untrusted files. Enable transcript_scanning for detection.\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Refresh dashboard data"
    ),
    "panel-global-settings": (
        "[bold]Global Settings[/bold]\n\n"
        "Master toggles for core security features. These control "
        "whether AI Guardian enforces permissions and scans for "
        "secrets globally.\n\n"
        "[bold]Toggles:[/bold]\n"
        "  [bold]permissions_enabled[/bold] — Enable/disable tool "
        "permission enforcement\n"
        "  [bold]secret_scanning[/bold] — Enable/disable secret "
        "detection scanning\n\n"
        "Each toggle supports three modes:\n"
        "  - Permanently Enabled\n"
        "  - Permanently Disabled\n"
        "  - Temporarily Disabled (with auto re-enable timestamp)\n\n"
        "[bold]on_scan_error:[/bold]\n"
        "  Controls what happens when a scanner itself crashes.\n\n"
        "  [bold]allow[/bold] (default) — fail-open: log warning, "
        "let operation through\n"
        "  [bold]block[/bold]           — fail-closed: block if any "
        "scanner fails\n\n"
        "  [yellow]Security tradeoff:[/yellow] 'block' is safer "
        "but a scanner bug = blocked workflow.\n"
        "  Recommend: 'allow' for dev, 'block' for production/compliance.\n"
        "  Applies to ALL scanners: secret, PII, prompt injection, "
        "Bandit, canary, exfil, etc."
    ),
    "panel-skills": (
        "[bold]Skills Permissions[/bold]\n\n"
        "Manage allow and deny patterns for Claude Code skills "
        "(slash commands like /release, /review, etc.).\n\n"
        "[bold]How patterns work:[/bold]\n"
        "  - Patterns use glob matching: [bold]daf-*[/bold] matches "
        "all daf skills\n"
        "  - [bold]*[/bold] matches everything\n"
        "  - Deny rules take precedence over allow rules\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]a[/bold]  Add allow pattern\n"
        "  [bold]d[/bold]  Add deny pattern\n"
        "  [bold]r[/bold]  Refresh list"
    ),
    "panel-mcp": (
        "[bold]MCP Server Permissions[/bold]\n\n"
        "Control which MCP (Model Context Protocol) server tools "
        "Claude Code is allowed to invoke.\n\n"
        "[bold]Pattern format:[/bold]\n"
        "  [bold]mcp__servername__toolname[/bold]\n"
        "  Example: [bold]mcp__notebooklm-mcp__*[/bold] allows all "
        "NotebookLM tools\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]a[/bold]  Add permission\n"
        "  [bold]r[/bold]  Refresh list"
    ),
    "panel-mcp-security": (
        "[bold]MCP Security Audit[/bold]\n\n"
        "Audit MCP server configurations for security issues.\n\n"
        "[bold]Checks performed:[/bold]\n"
        "  - Credential env vars passed to untrusted servers\n"
        "  - npx -y running unvetted packages (auto-install)\n"
        "  - Unpinned package versions\n"
        "  - Suspicious URLs and raw IP addresses\n\n"
        "[bold]Trust model:[/bold]\n"
        "  MCP servers with matching allow rules in permissions.rules\n"
        "  are trusted. Others are flagged for credential exposure.\n\n"
        "[bold]Deep scanning:[/bold]\n"
        "  For source code analysis, use CLI:\n"
        "  ai-guardian mcp scan [server-name]\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Refresh audit results"
    ),
    "panel-permissions-discovery": (
        "[bold]Permissions Discovery[/bold]\n\n"
        "Review tool calls that were attempted but didn't match any "
        "existing allow or deny rule.\n\n"
        "Use this to discover new tools being used and decide whether "
        "to create rules for them. Each unmatched call shows:\n"
        "  - Tool name and parameters\n"
        "  - Timestamp and frequency\n"
        "  - Quick-add buttons for allow/deny rules"
    ),
    "panel-auto-directory-rules": (
        "[bold]Auto Directory Rules[/bold]\n\n"
        "Auto-generate directory access rules from skill permissions.\n\n"
        "When enabled, AI Guardian scans standard skill directories for\n"
        "installed skills and creates directory rules for those matching\n"
        "your Skill permission allow patterns.\n\n"
        "[bold]Settings:[/bold]\n"
        "  [bold]Enabled[/bold]     Toggle auto-generation on/off\n"
        "  [bold]Symlinks[/bold]    Follow symlinks during skill discovery\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Refresh discovery results"
    ),
    "Prompt Injection": (
        "[bold]Prompt Injection[/bold]\n\n"
        "Detect and block prompt injection attacks in tool inputs "
        "and outputs. Protects against jailbreaks, obfuscation, "
        "and Unicode-based attacks.\n\n"
        "[bold]Sections:[/bold]\n"
        "  [bold]Detection Settings[/bold] — Engine, sensitivity, "
        "action, ignore files/tools\n"
        "  [bold]Patterns[/bold] — Allowlist and custom detection "
        "patterns\n"
        "  [bold]Jailbreak[/bold] — Custom jailbreak-specific "
        "patterns\n"
        "  [bold]Unicode Detection[/bold] — Zero-width, BiDi, "
        "tag chars, homoglyphs"
    ),
    "panel-pi-detection": (
        "[bold]Detection Settings[/bold]\n\n"
        "Core prompt injection detection configuration.\n\n"
        "[bold]Settings:[/bold]\n"
        "  [bold]Detector[/bold] — heuristic (fast, local), ml "
        "(DeBERTa via daemon), hybrid (heuristic + ML)\n"
        "  [bold]Sensitivity[/bold] — low, medium, high\n"
        "  [bold]Score Threshold[/bold] — 0.0-1.0 confidence for "
        "blocking\n"
        "  [bold]Action[/bold] — block, warn, or log-only\n\n"
        "[bold]Ignore lists:[/bold]\n"
        "  Glob patterns for files and tool names to skip\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]s[/bold]  Save detector/sensitivity settings"
    ),
    "panel-pi-ml-engines": (
        "[bold]ML Prompt Injection Engines[/bold]\n\n"
        "Configure ML-based prompt injection detection engines.\n\n"
        "[bold]Settings:[/bold]\n"
        "  [bold]Strategy[/bold] — first-match, any-match, consensus\n"
        "  [bold]Fallback[/bold] — heuristic, block, allow\n"
        "  [bold]Engines[/bold] — JSON array of ML engine configs\n\n"
        "[bold]Each engine requires:[/bold]\n"
        "  type: llm-guard\n"
        "  model: model name from registry\n"
        "  threshold: 0.0-1.0 (optional, default 0.85)\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]Ctrl+S[/bold]  Save engines\n"
        "  [bold]Ctrl+R[/bold]  Reload from disk"
    ),
    "panel-pi-patterns": (
        "[bold]Allowlist & Custom Patterns[/bold]\n\n"
        "Manage patterns for prompt injection detection.\n\n"
        "[bold]Allowlist patterns:[/bold]\n"
        "  Regex patterns to ignore — use for false positive "
        "exclusions. Supports time-based expiration.\n\n"
        "[bold]Custom detection patterns:[/bold]\n"
        "  Additional regex patterns to detect as injection.\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]a[/bold]  Add allowlist pattern\n"
        "  [bold]c[/bold]  Add custom pattern"
    ),
    "panel-pi-jailbreak": (
        "[bold]Jailbreak Patterns[/bold]\n\n"
        "Manage jailbreak-specific detection patterns.\n\n"
        "[bold]Built-in detection:[/bold]\n"
        "  - Role-play attacks (DAN mode, sudo mode)\n"
        "  - Identity manipulation ('pretend you are')\n"
        "  - Constraint removal ('ignore rules')\n"
        "  - Hypothetical framing ('fictional scenario')\n"
        "  - System prompt extraction\n\n"
        "[bold]Custom patterns:[/bold]\n"
        "  Add regex patterns for additional jailbreak techniques. "
        "Matched against user prompts only."
    ),
    "panel-pi-unicode": (
        "[bold]Unicode Attack Detection[/bold]\n\n"
        "Detect Unicode-based attacks that bypass text pattern "
        "matching.\n\n"
        "[bold]Detection types:[/bold]\n"
        "  [bold]Zero-width chars[/bold] — Invisible characters "
        "(ZWSP, ZWNJ, ZWJ)\n"
        "  [bold]BiDi override[/bold] — Text direction manipulation\n"
        "  [bold]Tag characters[/bold] — Deprecated Unicode tags for "
        "hidden data\n"
        "  [bold]Homoglyphs[/bold] — Look-alike character "
        "substitution\n\n"
        "[bold]Allow settings:[/bold]\n"
        "  RTL languages — Arabic, Hebrew (safe)\n"
        "  Emoji — Standard emoji characters (safe)"
    ),
    "panel-ssrf": (
        "[bold]SSRF Protection[/bold]\n\n"
        "Block Server-Side Request Forgery attacks by preventing "
        "requests to internal networks and sensitive endpoints.\n\n"
        "[bold]What is blocked:[/bold]\n"
        "  - Private IP ranges (10.x, 172.16-31.x, 192.168.x)\n"
        "  - Localhost and loopback addresses\n"
        "  - Cloud metadata endpoints (169.254.169.254)\n"
        "  - Internal DNS names\n\n"
        "[bold]Actions:[/bold]\n"
        "  [bold]block[/bold] — Reject the request entirely\n"
        "  [bold]warn[/bold] — Allow but log a warning\n"
        "  [bold]log-only[/bold] — Silent logging\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]s[/bold]  Save settings"
    ),
    "panel-context-poisoning": (
        "[bold]Context Poisoning Detection (LLM03)[/bold]\n\n"
        "Detect attempts to inject persistent malicious instructions\n"
        "into conversation context.\n\n"
        "[bold]Detection tiers:[/bold]\n"
        "  [bold]Low confidence[/bold] — Persistence keywords only\n"
        "  [bold]High confidence[/bold] — Persistence + dangerous action\n\n"
        "[bold]Actions:[/bold]\n"
        "  [bold]warn[/bold] — Allow but show warning (recommended)\n"
        "  [bold]block[/bold] — Reject the operation\n"
        "  [bold]log-only[/bold] — Silent logging\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]s[/bold]  Save settings"
    ),
    "panel-supply-chain": (
        "[bold]Supply Chain Scanning[/bold]\n\n"
        "Detect malicious patterns in agent hooks, MCP server configs, "
        "and plugin files.\n\n"
        "[bold]Scan targets:[/bold]\n"
        "  [bold]Hooks[/bold] — Hook configuration files (hooks.json, settings.json)\n"
        "  [bold]MCP Configs[/bold] — MCP server command configurations\n"
        "  [bold]Plugins[/bold] — Plugin/extension files for dangerous APIs\n\n"
        "[bold]Note:[/bold]\n"
        "  This panel is read-only. Use the web console or edit\n"
        "  ai-guardian.json to change supply chain settings.\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Refresh panel data"
    ),
    "panel-config-scanner": (
        "[bold]Config File Scanner[/bold]\n\n"
        "Detect attempts to read or exfiltrate sensitive configuration "
        "files.\n\n"
        "[bold]Protected files:[/bold]\n"
        "  - CLAUDE.md, .cursorrules, .github/copilot-*\n"
        "  - .env, .env.local, .env.production\n"
        "  - Credential files, SSH keys, cloud configs\n\n"
        "[bold]Configuration:[/bold]\n"
        "  - Additional files to protect\n"
        "  - Files to ignore (e.g., *.example.md)\n"
        "  - Custom detection patterns\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]s[/bold]  Save settings"
    ),
    "panel-scan-pii": (
        "[bold]PII Detection[/bold]\n\n"
        "Detect personally identifiable information in user prompts, "
        "file reads, and tool outputs for GDPR/CCPA compliance.\n\n"
        "[bold]PII types detected:[/bold]\n"
        "  - Social Security Numbers (XXX-XX-XXXX)\n"
        "  - Credit Card Numbers (Visa, MC, Amex, etc.)\n"
        "  - Phone Numbers (US and international)\n"
        "  - Email Addresses\n"
        "  - US Passport Numbers\n"
        "  - IBANs (International Bank Account Numbers)\n\n"
        "[bold]Actions:[/bold]\n"
        "  [bold]block[/bold] — Reject the operation entirely\n"
        "  [bold]redact[/bold] — Mask PII in output, block in input\n"
        "  [bold]warn[/bold] — Allow with warning notification\n"
        "  [bold]log-only[/bold] — Silent logging only\n\n"
        "[bold]Configuration:[/bold]\n"
        "  - Enable/disable individual PII types\n"
        "  - Ignore files via glob patterns (e.g., tests/**)"
    ),
    "panel-code-security": (
        "[bold]Code Security Scanning (Bandit)[/bold]\n\n"
        "Detect insecure Python code patterns: eval/exec, subprocess shell "
        "injection, weak crypto, SQL injection, hardcoded credentials, etc.\n\n"
        "[bold]Severity levels:[/bold]\n"
        "  HIGH   — Critical vulnerabilities (shell injection, eval)\n"
        "  MEDIUM — Important issues (weak crypto, unsafe deserialization)\n"
        "  LOW    — Minor concerns (bare except, debug mode)\n\n"
        "[bold]Suppression:[/bold]\n"
        "  # nosec           — Suppress all Bandit checks on a line\n"
        "  # nosec B101      — Suppress a specific check\n"
        "  # ai-guardian:allow — Suppress all ai-guardian checks on a line\n\n"
        "[bold]Note:[/bold]\n"
        "  This panel is read-only. Use the web console or edit\n"
        "  ai-guardian.json to change code security settings."
    ),
    "panel-offensive-language": (
        "[bold]Offensive Language Scanner[/bold]\n\n"
        "Detect profanity, slurs, and non-inclusive terminology in code,\n"
        "comments, and variable names. Disabled by default.\n\n"
        "[bold]Categories:[/bold]\n"
        "  profanity          — Explicit profanity\n"
        "  slurs              — Racial, ethnic, gender, ableist slurs\n"
        "  inclusive_language — master/slave, blacklist, dummy (opt-in)\n\n"
        "[bold]Suppression:[/bold]\n"
        "  # ai-guardian:allow — Suppress on a specific line\n"
        "  scan_offensive.allowlist_patterns — Regex allowlist\n"
        "  scan_offensive.ignore_files — File glob exclusions\n\n"
        "[bold]Note:[/bold]\n"
        "  This panel is read-only. Edit ai-guardian.json to\n"
        "  configure scan_offensive settings."
    ),
    "panel-canary-detection": (
        "[bold]Canary Token Detection[/bold]\n\n"
        "Register tripwire values in sensitive files. If the AI ever\n"
        "outputs those values, data exfiltration is detected.\n\n"
        "[bold]Token Types:[/bold]\n"
        "  value   — exact string match (low-entropy values secret scanner misses)\n"
        "  pattern — regex match (e.g. CANARY_[A-Z0-9]{8})\n\n"
        "[bold]Why not secret scanning?[/bold]\n"
        "  Secret scanner filters low-entropy strings. Canary detection\n"
        "  uses exact user-registered values, bypassing entropy checks.\n\n"
        "[bold]Note:[/bold]\n"
        "  Disabled by default. Enable after adding at least one token.\n"
        "  Edit ai-guardian.json → canary_detection section."
    ),
    "panel-exfil-detection": (
        "[bold]Exfiltration Behavior Detection[/bold]\n\n"
        "Detect bash commands that steal credentials: curl/wget with token\n"
        "variables, base64 encoding of secrets, SSH key file theft, cloud\n"
        "credential exfil, and environment variable collection.\n\n"
        "[bold]Pattern categories:[/bold]\n"
        "  credential_theft    — curl/wget with token/key/secret env vars\n"
        "  env_collection      — env|nc, printenv|socat, subshell dumps\n"
        "  key_file_exfil      — cat id_rsa|curl, SSH key piped to network\n"
        "  base64_encoding     — base64 encoding of credential files\n"
        "  cloud_credential_exfil — IMDS endpoint, AWS credentials\n"
        "  secret_collection   — .netrc, .npmrc, keychain extracts\n\n"
        "[bold]Note:[/bold]\n"
        "  This panel is read-only. Use the web console or edit\n"
        "  ai-guardian.json → exfil_detection section."
    ),
    "panel-annotations": (
        "[bold]Annotation Suppression[/bold]\n\n"
        "Suppress secrets and PII on specific lines using inline or "
        "block annotations in source code comments.\n\n"
        "[bold]Hardcoded markers (always active):[/bold]\n"
        "  [bold]# ai-guardian:allow[/bold] — Suppress secrets + PII "
        "on the line\n"
        "  [bold]# ai-guardian:begin-allow[/bold] / "
        "[bold]# ai-guardian:end-allow[/bold] — Block suppression\n\n"
        "[bold]Configurable aliases:[/bold]\n"
        "  [bold]Inline allow[/bold] — Custom markers for secrets + PII\n"
        "  [bold]Inline allow secrets[/bold] — Secrets only "
        "(default: gitleaks:allow)\n"
        "  [bold]Block begin/end[/bold] — Custom block markers\n\n"
        "[bold]Security:[/bold]\n"
        "  - Prompt injection, jailbreak, config exfil always scanned\n"
        "  - Only applies to file content (not prompts or tool output)\n"
        "  - Unmatched begin-allow is ignored (fail-safe)\n"
        "  - All suppressions logged for audit trail"
    ),
    "panel-secrets": (
        "[bold]Secret Scanning[/bold]\n\n"
        "Scan tool outputs for leaked API keys, tokens, passwords, "
        "and other credentials.\n\n"
        "[bold]Scanner engines:[/bold]\n"
        "  - Gitleaks — Fast, regex-based secret detection\n"
        "  - BetterLeaks — Enhanced detection with fewer false positives\n"
        "  - LeakTK — Pattern server with community-maintained rules\n\n"
        "[bold]Configuration:[/bold]\n"
        "  - Scanner selection and priority\n"
        "  - Custom allowlist for known false positives"
    ),
    "panel-secret-engines": (
        "[bold]Engine Configuration[/bold]\n\n"
        "Configure multiple secret scanner engines and execution strategies.\n\n"
        "[bold]Strategies:[/bold]\n"
        "  [bold]first-match[/bold] — Use first available engine (default)\n"
        "  [bold]any-match[/bold] — Block if ANY engine finds secrets\n"
        "  [bold]consensus[/bold] — Block only if N engines agree\n\n"
        "[bold]Per-engine options:[/bold]\n"
        "  - ignore_files — File exclusions per engine\n"
        "  - pattern_server — Per-engine pattern server\n"
        "  - file_patterns — Route file types to engines\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]Ctrl+S[/bold]  Save changes\n"
        "  [bold]Ctrl+R[/bold]  Reload from disk"
    ),
    "panel-secret-redaction": (
        "[bold]Secret Redaction[/bold]\n\n"
        "Automatically replace detected secrets with placeholder "
        "values before they reach the AI model.\n\n"
        "[bold]Redaction modes:[/bold]\n"
        "  [bold]block[/bold] — Block the entire tool output\n"
        "  [bold]log-only[/bold] — Log but don't modify output\n\n"
        "[bold]Options:[/bold]\n"
        "  - Preserve format (keep secret structure, replace chars)\n"
        "  - Log redactions for audit trail\n"
        "  - Additional custom patterns\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]s[/bold]  Save settings"
    ),
    "panel-violations": (
        "[bold]Violations Log[/bold]\n\n"
        "Browse and manage security violations detected by AI Guardian.\n\n"
        "[bold]Filter tabs:[/bold]\n"
        "  All — Every violation type\n"
        "  Tool Permission — Blocked tool/skill invocations\n"
        "  Secrets — Detected API keys, tokens, credentials\n"
        "  Secret Redaction — Redacted secrets in tool output\n"
        "  Directories — Protected directory access attempts\n"
        "  Prompt Injection — Injection/obfuscation attacks\n"
        "  Jailbreak — Jailbreak and role-play attempts\n"
        "  SSRF Blocked — Blocked requests to private IPs\n"
        "  Config Exfil — Config file exfiltration attempts\n"
        "  PII Detected — Personal identifiable information\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]1[/bold]  All  [bold]2[/bold]  Tool Permission  "
        "[bold]3[/bold]  Secrets  [bold]4[/bold]  Directories  "
        "[bold]5[/bold]  Prompt Injection\n\n"
        "[bold]Actions:[/bold]\n"
        "  - Click a violation to view full details\n"
        "  - Approve violations to add allow rules\n"
        "  - Clear violation history"
    ),
    "panel-violation-logging": (
        "[bold]Violation Logging Settings[/bold]\n\n"
        "Configure how AI Guardian logs security violations for "
        "audit and review.\n\n"
        "[bold]Settings:[/bold]\n"
        "  [bold]Max Entries[/bold] — Maximum log entries to retain "
        "(default: 1000)\n"
        "  [bold]Retention Days[/bold] — Days to keep entries "
        "(default: 30)\n\n"
        "[bold]Log Types:[/bold]\n"
        "  Enable/disable logging for each violation category:\n"
        "  tool_permission, directory_blocking, secret_detected,\n"
        "  secret_redaction, prompt_injection, jailbreak_detected,\n"
        "  ssrf_blocked, config_file_exfil, pii_detected\n\n"
        "[bold]Note:[/bold] Empty type selection logs all types."
    ),
    "panel-metrics": (
        "[bold]Metrics & Audit[/bold]\n\n"
        "Violation statistics, trends, and compliance audit.\n\n"
        "[bold]Metrics:[/bold]\n"
        "  [bold]Summary[/bold] — Total, resolved, unresolved, sessions\n"
        "  [bold]By Type/Severity/Action[/bold] — Breakdowns with %\n"
        "  [bold]Top Files/Tools[/bold] — Most affected paths and tools\n"
        "  [bold]Daily Trend[/bold] — Violations per day bar chart\n\n"
        "[bold]Audit:[/bold]\n"
        "  [bold]Security Posture[/bold] — GOOD / FAIR / NEEDS ATTENTION\n"
        "  [bold]Trend[/bold] — Comparison with previous period\n"
        "  [bold]Resolution[/bold] — Rate and average time\n"
        "  [bold]Compliance[/bold] — Feature status and violation counts\n\n"
        "[bold]Export:[/bold]\n"
        "  Use the Export HTML / JSON / CSV buttons, or CLI:\n"
        "  ai-guardian audit --html > report.html"
    ),
    "panel-performance": (
        "[bold]Performance — Hook Latency[/bold]\n\n"
        "Per-hook and per-violation-type timing statistics.\n\n"
        "[bold]Tables:[/bold]\n"
        "  [bold]Hook Latency Overview[/bold] — Avg, StdDev, P95 per hook event\n"
        "  [bold]Per-Check Breakdown[/bold] — Timing per violation check type\n\n"
        "[bold]Enable:[/bold]\n"
        "  Set latency_tracking.enabled = true in ai-guardian.json\n\n"
        "[bold]CLI:[/bold]\n"
        "  ai-guardian metrics --latency"
    ),
    "panel-logs": (
        "[bold]Runtime Logs[/bold]\n\n"
        "View AI Guardian's runtime log output for debugging and "
        "monitoring.\n\n"
        "[bold]Log levels:[/bold]\n"
        "  - ERROR — Security failures and critical issues\n"
        "  - WARNING — Suspicious activity and policy violations\n"
        "  - INFO — Normal operations and status updates\n"
        "  - DEBUG — Detailed diagnostic information\n\n"
        "[bold]Features:[/bold]\n"
        "  - Auto-refresh with live log streaming\n"
        "  - Filter by log level\n"
        "  - Clear log display"
    ),
    "panel-traces": (
        "[bold]Trace Viewer[/bold]\n\n"
        "View conversation traces from GuardedAgent runs.\n\n"
        "[bold]Features:[/bold]\n"
        "  - List all trace files with agent name, model, status\n"
        "  - Active conversations marked with green indicator\n"
        "  - Per-turn token breakdown and violation highlights\n\n"
        "[bold]Trace location:[/bold]\n"
        "  ~/.local/state/ai-guardian/sdk/traces/\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Refresh trace list"
    ),
    "AI Sessions": (
        "[bold]AI Sessions[/bold]\n\n"
        "Browse and inspect conversations from IDE coding agents.\n\n"
        "[bold]Sections:[/bold]\n"
        "  [bold]IDE Sessions[/bold] — Multi-IDE conversation browser "
        "(Claude, Cursor, Copilot, etc.)\n"
        "  [bold]SDK Traces[/bold] — Conversation traces from "
        "GuardedAgent runs\n"
        "  [bold]OTEL Export[/bold] — Send traces to Grafana/Jaeger"
    ),
    "panel-ide-sessions": (
        "[bold]IDE Sessions[/bold]\n\n"
        "Browse conversations from AI coding assistants.\n\n"
        "Supports: Claude Code, Cursor, Copilot, Codex, Windsurf, "
        "Gemini, Cline, Kiro.\n\n"
        "[bold]Features:[/bold]\n"
        "  - IDE selector dropdown\n"
        "  - Session list with title, model, token usage\n"
        "  - Filter by project path, text search\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Refresh session list"
    ),
    "SDK": (
        "[bold]SDK[/bold]\n\n"
        "Configure the AI Guardian SDK for programmatic security "
        "checking (GuardedAgent, guarded() wrapper).\n\n"
        "[bold]Sections:[/bold]\n"
        "  [bold]Agent Profiles[/bold] — Per-agent configuration "
        "(model, max_turns, tools, mode)\n"
        "  [bold]SDK Settings[/bold] — Global scanning and secret "
        "redaction toggles"
    ),
    "panel-sdk-agents": (
        "[bold]Agent Profiles[/bold]\n\n"
        "Configure GuardedAgent profiles. The '*' profile provides "
        "defaults applied to all agents. Named profiles override "
        "wildcard values.\n\n"
        "[bold]Profile fields:[/bold]\n"
        "  [bold]Model[/bold] — LLM model ID override\n"
        "  [bold]Max Turns[/bold] — Maximum tool-use loop iterations\n"
        "  [bold]Tools[/bold] — Tool preset (coding, readonly) or list\n"
        "  [bold]Mode[/bold] — Scanning mode (direct or rest)\n"
        "  [bold]Compact Threshold[/bold] — Context compaction trigger "
        "(0.0-1.0)\n\n"
        "[bold]Actions:[/bold]\n"
        "  Add Profile — Create a new named profile\n"
        "  Delete Profile — Remove selected (cannot delete *)"
    ),
    "panel-sdk-settings": (
        "[bold]SDK Settings[/bold]\n\n"
        "Global SDK scanning and secret redaction toggles.\n\n"
        "[bold]Settings:[/bold]\n"
        "  [bold]Scanning[/bold] — Global enable/disable for all SDK "
        "scanning. When off, SDK skips all input/output scanning.\n"
        "  [bold]Secret Redaction[/bold] — Redact detected secrets in "
        "live SDK content. Off by default because redaction breaks "
        "code in the agentic loop.\n\n"
        "[bold]Note:[/bold]\n"
        "  Traces are always sanitized independently of the secret "
        "redaction toggle."
    ),
    "panel-otel-settings": (
        "[bold]OTEL Export Settings[/bold]\n\n"
        "Configure OpenTelemetry live span export during agent runs.\n\n"
        "[bold]Features:[/bold]\n"
        "  - Enable/disable live OTEL export\n"
        "  - Set collector endpoint and auth headers\n"
        "  - Test connection to collector\n\n"
        "[bold]Environment variables:[/bold]\n"
        "  OTEL_EXPORTER_OTLP_ENDPOINT — override endpoint\n"
        "  OTEL_SERVICE_NAME — override service name\n"
        "  OTEL_EXPORTER_OTLP_HEADERS — auth headers (key=val,key=val)"
    ),
    "panel-directory-rules": (
        "[bold]Directory Rules[/bold]\n\n"
        "Control which file paths Claude Code can access using "
        "ordered allow/deny rules.\n\n"
        "[bold]How it works:[/bold]\n"
        "  - Rules are evaluated in order (last match wins)\n"
        "  - Each rule specifies allow or deny with path patterns\n"
        "  - If no rules match, access is allowed (default)\n"
        "  - Pattern: deny broad paths, then allow specific ones\n\n"
        "[bold]Common patterns:[/bold]\n"
        "  - Deny ~/.ssh/** — Block SSH private keys\n"
        "  - Deny ~/.aws/** — Block AWS credentials\n"
        "  - Deny ~/** then allow ~/dev/** — Workspace isolation"
    ),
    "panel-security-instructions": (
        "[bold]Security Instructions[/bold]\n\n"
        "View and configure the security rules injected into the agent's "
        "context via systemMessage on UserPromptSubmit.\n\n"
        "[bold]Options:[/bold]\n"
        "  [bold]inject_on_prompt[/bold] — Enable/disable injection\n"
        "  [bold]inject_trigger[/bold] — When to inject (first per session, every prompt, after block)\n"
        "  [bold]custom_rules[/bold] — Additional rules to append or replace built-in rules\n"
        "  [bold]replace_defaults[/bold] — Use only custom rules\n\n"
        "Edit via the web console for the full editor."
    ),
    "panel-remote-configs": (
        "[bold]Remote Configurations[/bold]\n\n"
        "Load AI Guardian configuration from remote sources. Useful "
        "for team-wide policy distribution.\n\n"
        "[bold]Features:[/bold]\n"
        "  - Fetch config from URL endpoints\n"
        "  - Automatic update schedules\n"
        "  - Merge strategy (override vs. merge)\n"
        "  - Configuration validation before applying"
    ),
    "panel-config-file": (
        "[bold]Config File[/bold]\n\n"
        "View the raw JSON configuration files.\n\n"
        "[bold]Config sources:[/bold]\n"
        "  1. User global: ~/.config/ai-guardian/ai-guardian.json\n"
        "  2. Project local: .ai-guardian.json (in project root)\n\n"
        "Shows the merged JSON from all sources with file "
        "locations and existence status."
    ),
    "panel-config-editor": (
        "[bold]Config Editor[/bold]\n\n"
        "Edit ai-guardian.json directly with syntax highlighting, "
        "real-time validation, and schema checking.\n\n"
        "[bold]Features:[/bold]\n"
        "  - JSON syntax highlighting with line numbers\n"
        "  - Real-time validation status bar\n"
        "  - Schema validation warnings on save\n"
        "  - Automatic backup before saving (.bak)\n"
        "  - Undo support (built-in TextArea)\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]Ctrl+S[/bold]  Save with confirmation\n"
        "  [bold]Ctrl+R[/bold]  Reload from disk\n"
        "  [bold]Ctrl+Z[/bold]  Undo"
    ),
    "panel-console-settings": (
        "[bold]Console Settings[/bold]\n\n"
        "Configure console preferences.\n\n"
        "[bold]Settings:[/bold]\n"
        "  [bold]Editor Theme[/bold] — Color theme for the JSON config "
        "editor. Options: Monokai, VS Code Dark, Dracula, GitHub Light\n\n"
        "Changes are saved immediately to console.editor_theme in "
        "your config file."
    ),
    "panel-config-effective": (
        "[bold]Effective Config[/bold]\n\n"
        "View the effective runtime configuration — equivalent to "
        "running `ai-guardian config show --all --json`.\n\n"
        "Shows the fully resolved config including:\n"
        "  - Merged settings from all sources\n"
        "  - Auto-generated directory rules\n"
        "  - Resolved SSRF blocked IPs/domains\n"
        "  - Secret redaction patterns\n"
        "  - Unicode detection settings\n"
        "  - Config file scanning rules"
    ),
    "panel-daemon": (
        "[bold]Daemon[/bold]\n\n"
        "Background daemon service for faster hook processing "
        "and cross-hook state sharing.\n\n"
        "The daemon auto-starts on any CLI command and falls back\n"
        "to direct processing if it cannot start."
    ),
    "panel-about": (
        "[bold]About[/bold]\n\n"
        "Version and system information for AI Guardian.\n\n"
        "[bold]Displays:[/bold]\n"
        "  - AI Guardian version\n"
        "  - Python version and platform\n"
        "  - License information"
    ),
    "panel-cache-status": (
        "[bold]Config Cache Status[/bold]\n\n"
        "Per-project config cache state tracked by the daemon.\n\n"
        "[bold]For each project:[/bold]\n"
        "  - Project directory (CWD)\n"
        "  - Config file path and modification time\n"
        "  - Global vs project override status\n"
        "  - Last seen and cache access timestamps\n\n"
        "[bold]Use case:[/bold]\n"
        "  Debug cross-project config issues — verify which\n"
        "  config files are loaded for each project and when\n"
        "  they were last reloaded.\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Refresh cache status"
    ),
    "panel-detection-patterns": (
        "[bold]Detection Patterns[/bold]\n\n"
        "Read-only view of ALL detection rules across TOML pattern files "
        "and hardcoded self-protection patterns.\n\n"
        "[bold]Features:[/bold]\n"
        "  - Browse ~360 TOML rules + self-protection globs\n"
        "  - Filter by category (secrets, pii, prompt_injection, etc.)\n"
        "  - Search by rule ID, description, or pattern text\n\n"
        "[bold]Pattern sources:[/bold]\n"
        "  - TOML: secrets, pii, prompt-injection, unicode, ssrf,\n"
        "    config-exfil, context-poisoning, supply-chain\n"
        "  - Hardcoded: self-protection patterns (Write, Edit, Read, Bash)\n\n"
        "[bold]Controls:[/bold]\n"
        "  Use the category buttons to filter by type.\n"
        "  Use the search box to find specific rules."
    ),
    "panel-regex-tester": (
        "[bold]Regex Tester[/bold]\n\n"
        "Interactively test regex patterns against sample text "
        "with real-time match results.\n\n"
        "[bold]Features:[/bold]\n"
        "  - Enter a regex pattern and see matches instantly\n"
        "  - ReDoS safety validation via validate_regex_pattern()\n"
        "  - Match count, matched text, and positions\n"
        "  - Toggle IGNORECASE and MULTILINE flags\n"
        "  - Add tested patterns to config sections\n\n"
        "[bold]Config targets:[/bold]\n"
        "  - Prompt Injection allowlist\n"
        "  - PII Detection allowlist\n"
        "  - Secret Scanning allowlist\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Clear and reset the tester"
    ),
    "panel-hook-simulator": (
        "[bold]Hook Simulator[/bold]\n\n"
        "Test AI Guardian's detection pipeline against simulated hook "
        "events without triggering real hooks or logging violations.\n\n"
        "[bold]Features:[/bold]\n"
        "  - Simulate UserPromptSubmit, PreToolUse, and PostToolUse\n"
        "  - Select tool type and file path for tool-use hooks\n"
        "  - View BLOCKED/ALLOWED/WARNING decisions\n"
        "  - See detection details (secrets, PII, prompt injection)\n"
        "  - View redacted output when applicable\n"
        "  - Raw JSON response with IDE format selector\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Clear and reset the simulator"
    ),
    "panel-engine-tester": (
        "[bold]Engine Tester[/bold]\n\n"
        "Test arbitrary text against individual secret scanner engines "
        "to see which engines detect secrets and what rules they match.\n\n"
        "[bold]Features:[/bold]\n"
        "  - Select any installed scanner engine from the dropdown\n"
        "  - Enter multi-line test text (paste API keys, tokens, etc.)\n"
        "  - Toggle pattern server configuration on/off\n"
        "  - View per-engine results: rule ID, line number, scan time\n"
        "  - Test All Engines for side-by-side comparison\n\n"
        "[bold]CLI equivalent:[/bold]\n"
        "  echo 'text' | ai-guardian engine-test --engine gitleaks\n"
        "  echo 'text' | ai-guardian engine-test --compare\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Clear and reset the tester"
    ),
    "panel-directory-scan": (
        "[bold]Directory Scan[/bold]\n\n"
        "Scan directories for security issues — secrets, SSRF patterns, "
        "Unicode attacks, and config file threats.\n\n"
        "[bold]Features:[/bold]\n"
        "  - Enter a directory path and click Scan\n"
        "  - Toggle config-files-only mode for targeted scanning\n"
        "  - Results show file, line, rule ID, and message\n"
        "  - Color-coded severity (red = error, yellow = warning)\n"
        "  - Export results to JSON or SARIF format\n\n"
        "[bold]CLI equivalent:[/bold]\n"
        "  ai-guardian scan [path]\n"
        "  ai-guardian scan --sarif-output results.sarif\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Clear results"
    ),
    "panel-scan-configure": (
        "[bold]Scan Configure[/bold]\n\n"
        "Scan a project to detect false positives and auto-generate "
        "suppression config.\n\n"
        "[bold]Note:[/bold] All scanners run regardless of enabled/disabled "
        "settings to discover all potential false positives upfront.\n\n"
        "[bold]Features:[/bold]\n"
        "  - Scans project with all scanners\n"
        "  - Clusters findings by pattern fingerprint\n"
        "  - Identifies high-frequency patterns as false positives\n"
        "  - Generates .ai-guardian/ai-guardian.json config\n"
        "  - Generates .aiguardignore.toml ignore paths\n"
        "  - Preview before applying\n\n"
        "[bold]CLI equivalent:[/bold]\n"
        "  ai-guardian init-project --scan\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Clear results"
    ),
    "panel-health-check": (
        "[bold]Health Check (Doctor)[/bold]\n\n"
        "Verify your AI Guardian setup is working correctly. "
        "Displays the same checks as 'ai-guardian doctor' CLI.\n\n"
        "[bold]Checks performed:[/bold]\n"
        "  - Config file validity and schema\n"
        "  - Scanner engines installed\n"
        "  - Pattern server connectivity and cache\n"
        "  - IDE hooks configured\n"
        "  - State and cache directories\n"
        "  - Permissions and directory rules\n"
        "  - Console dependencies\n\n"
        "[bold]Features:[/bold]\n"
        "  - Auto-refresh when navigating to the panel\n"
        "  - Color-coded pass/warn/fail/skip indicators\n"
        "  - Click to expand check details and fix hints\n"
        "  - Fix Issues button for auto-fixable problems\n\n"
        "[bold]Keyboard shortcuts:[/bold]\n"
        "  [bold]r[/bold]  Refresh health checks"
    ),
}
# ai-guardian:end-allow


class ProjectDirModal(ModalScreen):
    """Modal for entering a project directory path."""

    CSS = """
    ProjectDirModal {
        align: center middle;
    }

    #project-dir-container {
        width: 72;
        height: auto;
        max-height: 50%;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }

    #project-dir-title {
        margin: 0 0 1 0;
        text-align: center;
        text-style: bold;
        color: $accent;
    }

    #project-dir-input {
        margin: 1 0;
    }

    #project-dir-error {
        color: $error;
        margin: 0 0 1 0;
    }

    #project-dir-footer {
        margin: 1 0 0 0;
        height: auto;
        align: center middle;
    }

    #project-dir-footer Button {
        margin: 0 1 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, current_dir: str = "", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_dir = current_dir

    def compose(self) -> ComposeResult:
        from pathlib import Path

        default = self._current_dir or str(Path.cwd())
        with Container(id="project-dir-container"):
            yield Static(
                "[bold $accent]Select Project Directory[/bold $accent]",
                id="project-dir-title",
            )
            yield Static(
                "Enter the path to a project directory:",
                classes="muted",
            )
            yield Input(
                value=default,
                placeholder="/path/to/project",
                id="project-dir-input",
            )
            yield Static("", id="project-dir-error")
            with Horizontal(id="project-dir-footer"):
                yield Button("Cancel (ESC)", id="cancel-project", variant="default")
                yield Button("Select", id="select-project", variant="primary")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._try_select()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-project":
            self.dismiss(None)
        elif event.button.id == "select-project":
            self._try_select()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _try_select(self) -> None:
        from pathlib import Path

        path_input = self.query_one("#project-dir-input", Input)
        error_label = self.query_one("#project-dir-error", Static)
        value = path_input.value.strip()

        if not value:
            error_label.update("[red]Path cannot be empty[/red]")
            return

        p = Path(value).expanduser().resolve()
        if not p.is_dir():
            error_label.update(f"[red]Not a directory: {p}[/red]")
            return

        self.dismiss(str(p))


class HelpModal(ModalScreen):
    """Modal for displaying inline help documentation."""

    CSS = """
    HelpModal {
        align: center middle;
    }

    #help-container {
        width: 72;
        height: auto;
        max-height: 85%;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }

    #help-title {
        margin: 0 0 1 0;
        text-align: center;
        text-style: bold;
        color: $accent;
    }

    #help-body {
        height: auto;
        max-height: 60;
        overflow-y: auto;
        background: $surface;
        padding: 1 2;
        margin: 1 0;
    }

    #help-footer {
        margin: 1 0 0 0;
        height: auto;
        align: center middle;
    }

    #help-footer Button {
        margin: 0 1 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("question_mark", "dismiss", "Close", show=False),
    ]

    def __init__(
        self,
        title: str,
        body: str,
        doc_url: Optional[str] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._title = title
        self._body = body
        self._doc_url = doc_url

    def compose(self) -> ComposeResult:
        with Container(id="help-container"):
            yield Static(
                f"[bold $accent]? {self._title}[/bold $accent]", id="help-title"
            )
            with VerticalScroll(id="help-body"):
                yield Static(self._body)
            with Horizontal(id="help-footer"):
                if self._doc_url:
                    yield Button("Open docs →", id="open-docs", variant="default")
                yield Button("Close (ESC)", id="close-help", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-help":
            self.dismiss()
        elif event.button.id == "open-docs" and self._doc_url:
            import webbrowser

            webbrowser.open(self._doc_url)
            self.dismiss()


class AIGuardianTUI(App):
    """AI Guardian Console Application with sidebar navigation."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from ai_guardian import __version__

        self.title = f"\U0001f6e1️ AI Guardian v{__version__}"
        self._input_original_values = {}
        self.initial_panel = None
        self.config_scope = "global"
        self._show_disabled_scanners = True

    CSS = f"""
    Screen {{
        background: $surface;
    }}

    Footer {{
        background: $panel;
        color: $text;
        dock: bottom;
    }}

    #main-layout {{
        height: 100%;
    }}

    #nav-tree {{
        width: 28;
        dock: left;
        background: {_theme.SURFACE_ALT};
        border-right: solid $primary;
        padding: 1 0;
    }}

    #nav-tree > .tree--cursor {{
        background: $primary;
        color: $background;
        text-style: bold;
    }}

    #nav-tree > .tree--highlight {{
        background: $accent;
    }}

    #nav-tree:focus > .tree--cursor {{
        background: $accent;
        color: $background;
    }}

    #panels {{
        height: 100%;
    }}

    #panels > Container {{
        padding: 1 2;
        height: 100%;
    }}

    /* Empty states */
    .empty-state {{
        color: {_theme.TEXT_MUTED};
        text-align: center;
        padding: 2;
    }}

    /* Status indicators */
    .status-ok {{
        color: {_theme.SUCCESS};
    }}

    .status-warn {{
        color: {_theme.WARNING};
    }}

    .status-error {{
        color: {_theme.ERROR};
    }}

    .status-info {{
        color: {_theme.INFO};
    }}

    /* Muted text */
    .muted {{
        color: {_theme.TEXT_MUTED};
    }}

    /* Input fields */
    Input {{
        border: none;
        background: $surface;
        padding: 0 1;
        margin: 0 1 0 0;
    }}

    Input:focus {{
        border-left: heavy $accent;
        text-style: bold;
        background: $surface;
    }}


    /* Select widget */
    Select {{
        border: none;
        background: $surface;
    }}

    Select:focus {{
        text-style: bold;
        border-left: heavy $accent;
    }}

    /* Checkbox widget */
    Checkbox {{
        border: none;
    }}

    Checkbox:focus {{
        text-style: bold;
        border-left: heavy $accent;
    }}

    /* Changed from default indicator */
    .changed-from-default {{
        border-left: heavy {_theme.WARNING};
    }}

    /* Violations nested filter tabs */
    TabbedContent {{
        height: 100%;
    }}

    TabbedContent > Tabs {{
        background: $surface;
    }}

    TabbedContent > Tabs > Tab {{
        background: $surface;
        color: $text-muted;
    }}

    TabbedContent > Tabs > Tab.-active {{
        background: $primary;
        color: $background;
        text-style: bold;
    }}

    TabbedContent:focus > Tabs > Tab.-active {{
        background: $accent;
        color: $background;
        text-style: bold;
    }}
    """

    TITLE = "AI Guardian Configuration"
    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("r", "refresh_current_tab", "Refresh"),
        Binding("question_mark", "show_help", "Help"),
        Binding("p", "scope_project", "Project", show=True),
        Binding("g", "scope_global", "Global", show=True),
        Binding("escape", "focus_nav", "Navigation", show=False),
        Binding("1", "filter_all", show=False),
        Binding("2", "filter_tool", show=False),
        Binding("3", "filter_secret", show=False),
        Binding("4", "filter_directory", show=False),
        Binding("5", "filter_injection", show=False),
        Binding("a", "add_allow_pattern", "Add", show=True),
        Binding("c", "add_custom", "Custom", show=True),
        Binding("d", "add_deny_pattern", "Deny", show=True),
        Binding("s", "save_setting", "Save", show=True),
        Binding("ctrl+d", "nav_dashboard", "Dashboard", show=False),
        Binding("ctrl+v", "nav_violations", "Violations", show=False),
        Binding("ctrl+l", "nav_logs", "Logs", show=False),
        Binding("ctrl+m", "nav_metrics", "Metrics", show=False),
        Binding("ctrl+h", "toggle_disabled_scanners", "Toggle disabled", show=True),
    ]

    def copy_to_clipboard(self, text: str) -> bool:
        """Copy text to clipboard with platform-native fallback.

        Tries native commands first (pbcopy/xclip/xsel/wl-copy), then
        falls back to Textual's built-in OSC 52 escape sequence.

        Returns True if a native clipboard tool succeeded, False if only
        the OSC 52 fallback was attempted (unverifiable).
        """
        error, method = copy_to_system_clipboard(text)
        if error is None:
            return True
        super().copy_to_clipboard(text)
        self.notify(
            "Clipboard: no native tools — using terminal fallback",
            severity="warning",
        )
        return False

    def on_text_selected(self, event: events.TextSelected) -> None:
        """Auto-copy selected text to clipboard."""
        try:
            selection = self.screen.get_selected_text()
            if selection:
                if self.copy_to_clipboard(selection):
                    self.notify("Copied to clipboard", severity="information")
        except (IndexError, AttributeError):
            pass  # intentionally silent — best-effort operation

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Store original value when Input gets focus."""
        widget = event.widget
        if isinstance(widget, Input):
            self._input_original_values[widget] = widget.value

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()

        with Horizontal(id="main-layout"):
            from ai_guardian import __version__

            tree: Tree[str] = Tree(f"AI Guardian v{__version__}", id="nav-tree")
            tree.root.expand()
            for group_label, items in NAV_GROUPS:
                group_node = tree.root.add(group_label)
                group_node.expand()
                for label, panel_id in items:
                    group_node.add_leaf(label, data=panel_id)
            yield tree

            with ContentSwitcher(id="panels", initial="panel-security-dashboard"):
                with Container(id="panel-security-dashboard"):
                    from ai_guardian.tui.security_dashboard import (
                        SecurityDashboardContent,
                    )

                    yield SecurityDashboardContent()

                with Container(id="panel-global-settings"):
                    from ai_guardian.tui.global_settings import GlobalSettingsContent

                    yield GlobalSettingsContent()

                with Container(id="panel-skills"):
                    from ai_guardian.tui.skills import SkillsContent

                    yield SkillsContent()

                with Container(id="panel-mcp"):
                    from ai_guardian.tui.mcp_servers import MCPServersContent

                    yield MCPServersContent()

                with Container(id="panel-mcp-security"):
                    from ai_guardian.tui.mcp_security import MCPSecurityContent

                    yield MCPSecurityContent()

                with Container(id="panel-permissions-discovery"):
                    from ai_guardian.tui.permissions_discovery import (
                        PermissionsDiscoveryContent,
                    )

                    yield PermissionsDiscoveryContent()

                with Container(id="panel-auto-directory-rules"):
                    from ai_guardian.tui.auto_directory_rules import (
                        AutoDirectoryRulesContent,
                    )

                    yield AutoDirectoryRulesContent()

                with Container(id="panel-pi-detection"):
                    from ai_guardian.tui.pi_detection import PIDetectionContent

                    yield PIDetectionContent()

                with Container(id="panel-pi-ml-engines"):
                    from ai_guardian.tui.pi_ml_engines import PIMLEnginesContent

                    yield PIMLEnginesContent()

                with Container(id="panel-pi-patterns"):
                    from ai_guardian.tui.pi_patterns import PIPatternsContent

                    yield PIPatternsContent()

                with Container(id="panel-pi-jailbreak"):
                    from ai_guardian.tui.pi_jailbreak import PIJailbreakContent

                    yield PIJailbreakContent()

                with Container(id="panel-pi-unicode"):
                    from ai_guardian.tui.pi_unicode import PIUnicodeContent

                    yield PIUnicodeContent()

                with Container(id="panel-ssrf"):
                    from ai_guardian.tui.ssrf import SSRFContent

                    yield SSRFContent()

                with Container(id="panel-context-poisoning"):
                    from ai_guardian.tui.cp_detection import CPDetectionContent

                    yield CPDetectionContent()

                with Container(id="panel-supply-chain"):
                    from ai_guardian.tui.supply_chain import SupplyChainContent

                    yield SupplyChainContent()

                with Container(id="panel-config-scanner"):
                    from ai_guardian.tui.config_scanner import ConfigScannerContent

                    yield ConfigScannerContent()

                with Container(id="panel-scan-pii"):
                    from ai_guardian.tui.scan_pii import ScanPIIContent

                    yield ScanPIIContent()

                with Container(id="panel-code-security"):
                    from ai_guardian.tui.code_security import CodeSecurityContent

                    yield CodeSecurityContent()

                with Container(id="panel-offensive-language"):
                    from ai_guardian.tui.offensive_language import (
                        OffensiveLanguageContent,
                    )

                    yield OffensiveLanguageContent()

                with Container(id="panel-canary-detection"):
                    from ai_guardian.tui.canary_detection import (
                        CanaryDetectionContent,
                    )

                    yield CanaryDetectionContent()

                with Container(id="panel-exfil-detection"):
                    from ai_guardian.tui.exfil_detection import (
                        ExfilDetectionContent,
                    )

                    yield ExfilDetectionContent()

                with Container(id="panel-annotations"):
                    from ai_guardian.tui.annotations import AnnotationsContent

                    yield AnnotationsContent()

                with Container(id="panel-secrets"):
                    from ai_guardian.tui.secrets import SecretsContent

                    yield SecretsContent()

                with Container(id="panel-secret-engines"):
                    from ai_guardian.tui.secret_engines import SecretEnginesContent

                    yield SecretEnginesContent()

                with Container(id="panel-secret-redaction"):
                    from ai_guardian.tui.secret_redaction import SecretRedactionContent

                    yield SecretRedactionContent()

                with Container(id="panel-violations"):
                    from ai_guardian.tui.violations import ViolationsContent

                    yield ViolationsContent()

                with Container(id="panel-violation-logging"):
                    from ai_guardian.tui.violation_logging import (
                        ViolationLoggingContent,
                    )

                    yield ViolationLoggingContent()

                with Container(id="panel-metrics"):
                    from ai_guardian.tui.metrics_panel import MetricsContent

                    yield MetricsContent()

                with Container(id="panel-performance"):
                    from ai_guardian.tui.performance import PerformanceContent

                    yield PerformanceContent()

                with Container(id="panel-logs"):
                    from ai_guardian.tui.logs import LogsContent

                    yield LogsContent()

                with Container(id="panel-sdk-agents"):
                    from ai_guardian.tui.sdk_agents import SDKAgentsContent

                    yield SDKAgentsContent()

                with Container(id="panel-sdk-settings"):
                    from ai_guardian.tui.sdk_settings import SDKSettingsContent

                    yield SDKSettingsContent()

                with Container(id="panel-ide-sessions"):
                    from ai_guardian.tui.ide_sessions import IDESessionsContent

                    yield IDESessionsContent()

                with Container(id="panel-traces"):
                    from ai_guardian.tui.traces import TracesContent

                    yield TracesContent()

                with Container(id="panel-otel-settings"):
                    from ai_guardian.tui.otel_settings import OtelSettingsContent

                    yield OtelSettingsContent()

                with Container(id="panel-directory-rules"):
                    from ai_guardian.tui.directory_rules import DirectoryRulesContent

                    yield DirectoryRulesContent()

                with Container(id="panel-security-instructions"):
                    from ai_guardian.tui.security_instructions import (
                        SecurityInstructionsContent,
                    )

                    yield SecurityInstructionsContent()

                with Container(id="panel-remote-configs"):
                    from ai_guardian.tui.remote_configs import RemoteConfigsContent

                    yield RemoteConfigsContent()

                with Container(id="panel-cache-status"):
                    from ai_guardian.tui.cache_status import CacheStatusContent

                    yield CacheStatusContent()

                with Container(id="panel-config-file"):
                    from ai_guardian.tui.config_viewer import ConfigContent

                    yield ConfigContent()

                with Container(id="panel-config-editor"):
                    from ai_guardian.tui.config_editor import ConfigEditorContent

                    yield ConfigEditorContent()

                with Container(id="panel-console-settings"):
                    from ai_guardian.tui.console_settings import ConsoleSettingsContent

                    yield ConsoleSettingsContent()

                with Container(id="panel-config-effective"):
                    from ai_guardian.tui.config_effective import ConfigEffectiveContent

                    yield ConfigEffectiveContent()

                with Container(id="panel-daemon"):
                    from ai_guardian.tui.daemon_panel import DaemonPanelContent

                    yield DaemonPanelContent()

                with Container(id="panel-about"):
                    from ai_guardian.tui.about import AboutContent

                    yield AboutContent()

                with Container(id="panel-detection-patterns"):
                    from ai_guardian.tui.detection_patterns import (
                        DetectionPatternsContent,
                    )

                    yield DetectionPatternsContent()

                with Container(id="panel-regex-tester"):
                    from ai_guardian.tui.regex_tester import RegexTesterContent

                    yield RegexTesterContent()

                with Container(id="panel-hook-simulator"):
                    from ai_guardian.tui.hook_simulator import HookSimulatorContent

                    yield HookSimulatorContent()

                with Container(id="panel-engine-tester"):
                    from ai_guardian.tui.engine_tester import EngineTesterContent

                    yield EngineTesterContent()

                with Container(id="panel-directory-scan"):
                    from ai_guardian.tui.directory_scan import DirectoryScanContent

                    yield DirectoryScanContent()

                with Container(id="panel-scan-configure"):
                    from ai_guardian.tui.scan_configure import (
                        ScanConfigureContent,
                    )

                    yield ScanConfigureContent()

                with Container(id="panel-health-check"):
                    from ai_guardian.tui.health_check import HealthCheckContent

                    yield HealthCheckContent()

        yield Footer()

    def on_mount(self) -> None:
        self._rebuild_nav_tree()
        if self.initial_panel:
            try:
                switcher = self.query_one("#panels", ContentSwitcher)
                switcher.current = self.initial_panel
            except Exception:
                pass

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Switch panel when a tree leaf is selected."""
        if event.node.data is not None:
            switcher = self.query_one("#panels", ContentSwitcher)
            switcher.current = event.node.data
            panel = self.query_one(f"#{event.node.data}", Container)
            for child in panel.children:
                if hasattr(child, "refresh_content"):
                    child.refresh_content()
                    break

    def _get_current_content(self):
        """Get the content widget from the currently visible panel."""
        switcher = self.query_one("#panels", ContentSwitcher)
        panel_id = switcher.current
        if panel_id is None:
            return None
        panel = self.query_one(f"#{panel_id}", Container)
        for child in panel.children:
            if hasattr(child, "refresh_content") or hasattr(child, "action_refresh"):
                return child
        return panel.children[0] if panel.children else None

    def _get_current_panel_id(self) -> Optional[str]:
        """Get the current panel ID from ContentSwitcher."""
        switcher = self.query_one("#panels", ContentSwitcher)
        return switcher.current

    def check_action(self, action: str, parameters: tuple) -> Optional[bool]:
        """Control which actions are available based on current panel."""
        current_panel = self._get_current_panel_id()

        tab_actions = {
            "panel-skills": ["add_allow_pattern", "add_deny_pattern"],
            "panel-mcp": ["add_allow_pattern"],
            "panel-pi-detection": ["save_setting"],
            "panel-pi-patterns": ["add_allow_pattern", "add_custom"],
            "panel-secrets": [],
            "panel-ssrf": ["save_setting"],
            "panel-config-scanner": ["save_setting"],
            "panel-secret-redaction": ["save_setting"],
        }

        current_tab_actions = tab_actions.get(current_panel, [])
        if action in current_tab_actions:
            return True

        for actions in tab_actions.values():
            if action in actions:
                return False

        return True

    def action_focus_nav(self) -> None:
        """Focus navigation tree (ESC handler)."""
        focused = self.focused
        if isinstance(focused, Input) and focused in self._input_original_values:
            focused.value = self._input_original_values[focused]
            del self._input_original_values[focused]
        self.query_one("#nav-tree", Tree).focus()

    def action_show_help(self) -> None:
        """Show help for the currently highlighted tree node or active panel."""
        from ai_guardian.help_content import PANEL_DOC_URLS

        tree = self.query_one("#nav-tree", Tree)
        cursor_node = tree.cursor_node

        if cursor_node is not None and cursor_node.data is not None:
            panel_id = cursor_node.data
            label = str(cursor_node.label)
        elif cursor_node is not None and cursor_node.data is None:
            label = str(cursor_node.label)
            if label in HELP_DOCS:
                self.push_screen(HelpModal(label, HELP_DOCS[label]))
                return
            self.notify("No help available", severity="warning")
            return
        else:
            panel_id = self._get_current_panel_id()
            if panel_id is None:
                self.notify("No help available", severity="warning")
                return
            label = panel_id

        if panel_id in HELP_DOCS:
            doc_url = PANEL_DOC_URLS.get(panel_id)
            self.push_screen(HelpModal(label, HELP_DOCS[panel_id], doc_url=doc_url))
        else:
            self.notify("No help available", severity="warning")

    def action_refresh_current_tab(self) -> None:
        """Refresh the current panel's content."""
        content = self._get_current_content()
        if content is None:
            self.notify("No panel selected", severity="warning")
            return

        if hasattr(content, "action_refresh"):
            content.action_refresh()
            self.notify("Panel refreshed", severity="information")
        elif hasattr(content, "refresh_content"):
            content.refresh_content()
            self.notify("Panel refreshed", severity="information")
        else:
            self.notify(
                "No refresh method available for this panel", severity="warning"
            )

    def action_filter_all(self) -> None:
        """Filter all violations (only works on Violations panel)."""
        if self._get_current_panel_id() != "panel-violations":
            return
        content = self._get_current_content()
        if content and hasattr(content, "action_filter_all"):
            content.action_filter_all()

    def action_filter_tool(self) -> None:
        """Filter tool violations (only works on Violations panel)."""
        if self._get_current_panel_id() != "panel-violations":
            return
        content = self._get_current_content()
        if content and hasattr(content, "action_filter_tool"):
            content.action_filter_tool()

    def action_filter_secret(self) -> None:
        """Filter secret violations (only works on Violations panel)."""
        if self._get_current_panel_id() != "panel-violations":
            return
        content = self._get_current_content()
        if content and hasattr(content, "action_filter_secret"):
            content.action_filter_secret()

    def action_filter_directory(self) -> None:
        """Filter directory violations (only works on Violations panel)."""
        if self._get_current_panel_id() != "panel-violations":
            return
        content = self._get_current_content()
        if content and hasattr(content, "action_filter_directory"):
            content.action_filter_directory()

    def action_filter_injection(self) -> None:
        """Filter prompt injection violations (only works on Violations panel)."""
        if self._get_current_panel_id() != "panel-violations":
            return
        content = self._get_current_content()
        if content and hasattr(content, "action_filter_injection"):
            content.action_filter_injection()

    def action_add_allow_pattern(self) -> None:
        """Add allow pattern (Skills) or add permission (MCP/Prompt Injection)."""
        panel_id = self._get_current_panel_id()
        content = self._get_current_content()
        if content is None:
            return

        if panel_id == "panel-skills" and hasattr(content, "action_add_allow"):
            content.action_add_allow()
        elif panel_id == "panel-mcp" and hasattr(content, "action_add_permission"):
            content.action_add_permission()
        elif panel_id == "panel-pi-patterns" and hasattr(content, "action_add_pattern"):
            content.action_add_pattern()

    def action_add_custom(self) -> None:
        """Add custom pattern (only works on Prompt Injection panel)."""
        if self._get_current_panel_id() != "panel-pi-patterns":
            return
        content = self._get_current_content()
        if content and hasattr(content, "action_add_custom"):
            content.action_add_custom()

    def action_add_deny_pattern(self) -> None:
        """Add deny pattern (only works on Skills panel)."""
        if self._get_current_panel_id() != "panel-skills":
            return
        content = self._get_current_content()
        if content and hasattr(content, "action_add_deny"):
            content.action_add_deny()

    def action_save_setting(self) -> None:
        """Save setting (works on Prompt Injection panel)."""
        if self._get_current_panel_id() != "panel-pi-detection":
            return
        content = self._get_current_content()
        if content and hasattr(content, "action_update_sensitivity"):
            content.action_update_sensitivity()

    def _navigate_to_panel(self, panel_id: str) -> None:
        """Switch the content switcher to a panel by ID."""
        switcher = self.query_one("#panels", ContentSwitcher)
        switcher.current = panel_id

    def action_nav_dashboard(self) -> None:
        """Navigate to Security Dashboard."""
        self._navigate_to_panel("panel-security-dashboard")

    def action_nav_violations(self) -> None:
        """Navigate to Violations."""
        self._navigate_to_panel("panel-violations")

    def action_nav_logs(self) -> None:
        """Navigate to Logs."""
        self._navigate_to_panel("panel-logs")

    def action_nav_metrics(self) -> None:
        """Navigate to Metrics."""
        self._navigate_to_panel("panel-metrics")

    def check_action(self, action: str, parameters) -> Optional[bool]:
        """Show p when in global scope, g when in project scope."""
        if action == "scope_project":
            return self.config_scope == "global"
        if action == "scope_global":
            return self.config_scope == "project"
        return True

    def action_scope_project(self) -> None:
        """Prompt for project directory, then switch to project scope."""

        def on_result(project_dir: Optional[str]) -> None:
            if project_dir is None:
                return
            from ai_guardian.config.utils import set_project_dir_override

            set_project_dir_override(project_dir)
            self.config_scope = "project"
            self.sub_title = f"[Project: {project_dir}]"
            self.refresh_bindings()
            self._refresh_scope_panels()
            self.notify(f"Scope: Project ({project_dir})", severity="information")

        current = ""
        try:
            from ai_guardian.config.utils import get_project_dir

            current = get_project_dir()
        except Exception:
            pass
        self.push_screen(ProjectDirModal(current_dir=current), on_result)

    def action_scope_global(self) -> None:
        """Switch to global scope."""
        from ai_guardian.config.utils import clear_project_dir_override

        clear_project_dir_override()
        self.config_scope = "global"
        self.sub_title = ""
        self.refresh_bindings()
        self._refresh_scope_panels()
        self.notify("Scope: Global", severity="information")

    def action_toggle_disabled_scanners(self) -> None:
        """Toggle visibility of disabled scanner pages in the nav tree."""
        self._show_disabled_scanners = not self._show_disabled_scanners
        self._rebuild_nav_tree()
        state = "shown" if self._show_disabled_scanners else "hidden"
        self.notify(f"Disabled scanners: {state}", severity="information")

    def _rebuild_nav_tree(self) -> None:
        """Rebuild nav tree, filtering disabled scanner pages."""
        from ai_guardian.config.utils import get_config

        tree = self.query_one("#nav-tree", Tree)
        current_panel = self._get_current_panel_id()

        try:
            config = get_config()
        except Exception:
            config = {}

        tree.root.remove_children()
        for group_label, items in NAV_GROUPS:
            visible_items = []
            for label, panel_id in items:
                config_section = PANEL_TO_CONFIG_SECTION.get(panel_id)
                if config_section:
                    enabled = _is_feature_enabled(config, config_section)
                    if not enabled and not self._show_disabled_scanners:
                        continue
                visible_items.append((label, panel_id))

            if not visible_items:
                continue

            group_node = tree.root.add(group_label)
            group_node.expand()
            for label, panel_id in visible_items:
                group_node.add_leaf(label, data=panel_id)

        if current_panel:
            for node in tree.root.children:
                for leaf in node.children:
                    if leaf.data == current_panel:
                        tree.select_node(leaf)
                        return

    def _refresh_scope_panels(self) -> None:
        """Refresh panels that are scope-aware."""
        content = self._get_current_content()
        if content and hasattr(content, "refresh_content"):
            content.refresh_content()


def run_tui():
    """Run the AI Guardian Console application."""
    app = AIGuardianTUI()
    app.run()
