"""Centralized help content for all AI Guardian scanner pages.

Used by both the TUI HelpModal and the web console help panel.
"""

_GITHUB_DOCS = "https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs"

SCANNER_HELP = {
    "secret_scanning": {
        "title": "Secret Scanning",
        "summary": (
            "Scans AI tool inputs and outputs for leaked API keys, tokens, passwords, "
            "and other credentials using pattern-based scanner engines (Gitleaks, BetterLeaks, LeakTK)."
        ),
        "catches": [
            "AWS access keys (AKIA…)",
            "GitHub personal access tokens (ghp_…)",
            "OpenAI API keys (sk-…)",
            "Stripe, Twilio, SendGrid, Slack tokens",
            "Private keys (RSA, EC, PGP)",
            "High-entropy strings matching known key formats",
        ],
        "does_not_catch": [
            "Low-entropy canary tokens — use Canary Detection instead",
            "Secrets in image content — use Image Scanning",
            "Secrets already redacted by Secret Redaction",
        ],
        "config_summary": (
            "secret_scanning.enabled — toggle on/off\n"
            "secret_scanning.allowlist_patterns — regex allowlist for false positives"
        ),
        "doc_url": f"{_GITHUB_DOCS}/security/SECRET_SCANNING.md",
    },
    "scan_pii": {
        "title": "PII Detection",
        "summary": (
            "Detects personally identifiable information in prompts, file reads, "
            "and tool outputs to assist GDPR/CCPA compliance."
        ),
        "catches": [
            "US Social Security Numbers (XXX-XX-XXXX)",
            "Credit card numbers (Visa, Mastercard, Amex, Discover)",
            "US and international phone numbers",
            "Email addresses",
            "US passport numbers",
            "IBANs (International Bank Account Numbers)",
        ],
        "does_not_catch": [
            "Non-US national IDs (use custom patterns for jurisdiction-specific IDs)",
            "Names and addresses (no NLP — pattern-based only)",
            "PII embedded inside binary or image files",
        ],
        "config_summary": (
            "scan_pii.enabled — toggle on/off\n"
            "scan_pii.action — block | redact | warn | log-only\n"
            "scan_pii.pii_types — list of types to detect (ssn, credit_card, email, …)\n"
            "scan_pii.ignore_files — glob patterns to skip"
        ),
        "doc_url": f"{_GITHUB_DOCS}/CONFIGURATION.md",
    },
    "prompt_injection": {
        "title": "Prompt Injection Detection",
        "summary": (
            "Detects jailbreak attempts, obfuscation, Unicode attacks, and injected "
            "instructions in user prompts and tool outputs. Protects against LLM01/LLM04 attacks."
        ),
        "catches": [
            "Role-play jailbreaks (DAN mode, 'pretend you have no restrictions')",
            "Constraint removal ('ignore your previous instructions')",
            "System prompt extraction attempts",
            "Unicode zero-width character smuggling",
            "BiDi text direction manipulation",
            "Homoglyph substitution attacks",
        ],
        "does_not_catch": [
            "Injections in file binary content (only text is scanned)",
            "Injections requiring semantic understanding (heuristic mode limitation)",
        ],
        "config_summary": (
            "prompt_injection.enabled — toggle on/off\n"
            "prompt_injection.detector — heuristic | ml | hybrid\n"
            "prompt_injection.sensitivity — low | medium | high\n"
            "prompt_injection.action — block | warn | log-only | ask"
        ),
        "doc_url": f"{_GITHUB_DOCS}/security/PROMPT_INJECTION.md",
    },
    "ssrf_protection": {
        "title": "SSRF Protection",
        "summary": (
            "Blocks Server-Side Request Forgery attacks by preventing Bash commands "
            "and tool outputs from making requests to internal networks, cloud metadata "
            "endpoints, and sensitive IP ranges."
        ),
        "catches": [
            "Requests to private IP ranges (10.x, 172.16-31.x, 192.168.x)",
            "Localhost and loopback addresses (127.x, ::1)",
            "Cloud metadata endpoints (169.254.169.254 — AWS/GCP/Azure IMDS)",
            "Internal DNS names (.internal, .local, .corp)",
            "Dangerous URL schemes (file://, gopher://, dict://)",
        ],
        "does_not_catch": [
            "SSRF via DNS rebinding (IP checked at scan time, not resolution time)",
            "Requests in encrypted payloads",
            "SSRF in non-Bash tools (only Bash commands are checked by default)",
        ],
        "config_summary": (
            "ssrf_protection.enabled — toggle on/off\n"
            "ssrf_protection.action — block | warn | log-only\n"
            "ssrf_protection.allowed_domains — regex allowlist for trusted internal hosts"
        ),
        "doc_url": f"{_GITHUB_DOCS}/CONFIGURATION.md",
    },
    "context_poisoning": {
        "title": "Context Poisoning Detection",
        "summary": (
            "Detects attempts to inject persistent malicious instructions into conversation "
            "context (LLM03). Looks for phrases that try to permanently alter the AI's behavior."
        ),
        "catches": [
            "Persistent instruction injection ('from now on, always…')",
            "System prompt hijacking attempts",
            "Persistent + dangerous action combos (exfil, ignore rules)",
        ],
        "does_not_catch": [
            "Single-turn jailbreaks — use Prompt Injection Detection for those",
            "Context poisoning in binary file content",
        ],
        "config_summary": (
            "context_poisoning.enabled — toggle on/off\n"
            "context_poisoning.sensitivity — low | medium | high\n"
            "context_poisoning.action — block | warn | log-only"
        ),
        "doc_url": f"{_GITHUB_DOCS}/security/CONTEXT_POISONING.md",
    },
    "supply_chain": {
        "title": "Supply Chain Scanning",
        "summary": (
            "Detects malicious patterns in agent hook configurations, MCP server "
            "command definitions, and plugin/extension files."
        ),
        "catches": [
            "Hook commands that make network requests on trigger",
            "MCP server configs that auto-install packages (npx -y)",
            "Plugin files that access system credentials",
            "Unpinned or suspicious package references in agent configs",
        ],
        "does_not_catch": [
            "Runtime behavior of installed packages — only static config scanning",
            "Malicious packages uploaded to npm/PyPI (use dependency scanning for that)",
        ],
        "config_summary": (
            "supply_chain.enabled — toggle on/off\n"
            "supply_chain.action — block | warn | log-only\n"
            "supply_chain.allowlist_paths — paths to skip"
        ),
        "doc_url": None,
    },
    "config_file_scanning": {
        "title": "Config File Scanner",
        "summary": (
            "Detects attempts to read or exfiltrate sensitive configuration files "
            "via AI tool outputs. Catches when CLAUDE.md, .env, SSH keys, etc. "
            "appear in file reads or network requests."
        ),
        "catches": [
            "CLAUDE.md, .cursorrules, .github/copilot-* agent instructions",
            ".env, .env.local, .env.production credential files",
            "SSH private keys (~/.ssh/id_rsa, id_ed25519, etc.)",
            "Cloud credentials (~/.aws/credentials, ~/.config/gcloud/)",
            "Database connection strings and API key files",
        ],
        "does_not_catch": [
            "Config file access that doesn't match the protected patterns",
            "Config files in explicitly allowed paths (add to ignore_files)",
        ],
        "config_summary": (
            "config_file_scanning.enabled — toggle on/off\n"
            "config_file_scanning.action — block | warn | log-only\n"
            "config_file_scanning.additional_protected_files — extra files to protect\n"
            "config_file_scanning.ignore_files — glob patterns to skip"
        ),
        "doc_url": f"{_GITHUB_DOCS}/CONFIGURATION.md",
    },
    "code_scanning": {
        "title": "Code Security Scanning (Bandit)",
        "summary": (
            "Scans Python code written by the AI for common security vulnerabilities "
            "using Bandit: eval/exec usage, shell injection, weak crypto, SQL injection, "
            "hardcoded credentials, and more."
        ),
        "catches": [
            "eval() and exec() with user input (B307, B102)",
            "subprocess with shell=True (B602, B603)",
            "Weak crypto: MD5, SHA1 for passwords (B303, B324)",
            "SQL string formatting / injection risk (B608)",
            "assert statements in production code (B101)",
            "Hardcoded passwords and default key sizes (B105, B107)",
        ],
        "does_not_catch": [
            "Security issues in non-Python languages",
            "Logic errors and business logic flaws",
            "Runtime-only vulnerabilities (e.g., race conditions)",
        ],
        "config_summary": (
            "code_scanning.enabled — toggle on/off\n"
            "code_scanning.action — block | warn | log-only\n"
            "code_scanning.severity — LOW | MEDIUM | HIGH (minimum level to flag)\n"
            "code_scanning.confidence — LOW | MEDIUM | HIGH"
        ),
        "doc_url": None,
    },
    "offensive_language": {
        "title": "Offensive Language Scanner",
        "summary": (
            "Detects profanity, slurs, and non-inclusive terminology in code comments, "
            "variable names, and generated text. Disabled by default — context-dependent."
        ),
        "catches": [
            "Profanity — explicit swear words",
            "Slurs — racial, ethnic, gender, ableist slurs",
            "Non-inclusive language — master/slave, blacklist/whitelist, dummy (optional)",
        ],
        "does_not_catch": [
            "Context-aware usage (e.g., a legitimate use of 'master branch' if enabled)",
            "Offensive language in non-text file formats",
        ],
        "config_summary": (
            "scan_offensive.enabled — toggle on/off\n"
            "scan_offensive.categories — [profanity, slurs, inclusive_language]\n"
            "scan_offensive.action — block | warn | log-only\n"
            "scan_offensive.ignore_files — glob patterns to skip"
        ),
        "doc_url": None,
    },
    "canary_detection": {
        "title": "Canary Token Detection",
        "summary": (
            "Detects user-registered tripwire values in AI output. Plant a secret value "
            "in a sensitive file, register it here — if the AI ever outputs that value, "
            "data exfiltration is caught before it leaves."
        ),
        "catches": [
            "Any user-registered exact string (value=) — case-sensitive match",
            "Any user-registered regex pattern (pattern=) — e.g. CANARY_[A-Z0-9]{8}",
            "Low-entropy strings that secret scanners would miss",
        ],
        "does_not_catch": [
            "Tokens not registered in the config",
            "Encoded variants of canary values (base64, hex) unless registered as regex",
        ],
        "config_summary": (
            "canary_detection.enabled — toggle on/off (disabled by default)\n"
            "canary_detection.action — block | warn | log-only\n"
            "canary_detection.tokens — list of {value: '...'} or {pattern: '...'} entries"
        ),
        "doc_url": None,
    },
    "exfil_detection": {
        "title": "Exfiltration Behavior Detection",
        "summary": (
            "Detects bash command patterns that indicate credential theft: curl/wget "
            "uploading token variables, base64 encoding of secret files, SSH key "
            "piped to network tools, and cloud credential exfiltration."
        ),
        "catches": [
            "curl/wget with $TOKEN, $API_KEY, $SECRET env vars (credential_theft)",
            "env|nc, printenv|socat, $() subshell variable dumps (env_collection)",
            "cat ~/.ssh/id_rsa | curl ... (key_file_exfil)",
            "base64 ~/.aws/credentials (base64_encoding)",
            "curl 169.254.169.254/... — IMDS metadata theft (cloud_credential_exfil)",
            ".netrc, .npmrc, keychain extraction (secret_collection)",
        ],
        "does_not_catch": [
            "Exfiltration via non-bash tools (Python, Node.js scripts)",
            "Exfiltration using allowed patterns (add to allowlist_patterns)",
        ],
        "config_summary": (
            "exfil_detection.enabled — toggle on/off\n"
            "exfil_detection.action — block | warn | log-only\n"
            "exfil_detection.allowlist_patterns — regex patterns for legitimate commands"
        ),
        "doc_url": None,
    },
    "global_settings": {
        "title": "Global Settings",
        "summary": (
            "Master control panel for all AI Guardian security features. "
            "Toggle features on/off, set actions, and configure fail-open vs fail-closed behavior."
        ),
        "catches": [
            "All active scanners and their current status",
            "on_scan_error — what happens when a scanner itself crashes",
        ],
        "does_not_catch": [],
        "config_summary": (
            "on_scan_error:\n"
            "  allow (default) — fail-open: log warning, let operation through\n"
            "  block           — fail-closed: block operation if any scanner fails\n\n"
            "Security tradeoff:\n"
            "  'block' is safer but a scanner bug = blocked workflow.\n"
            "  Recommend: 'allow' for dev, 'block' for production/compliance environments.\n"
            "  Applies to ALL scanners: secret, PII, prompt injection, Bandit, canary, etc."
        ),
        "doc_url": f"{_GITHUB_DOCS}/CONFIGURATION.md",
    },
    "secret_redaction": {
        "title": "Secret Redaction",
        "summary": (
            "Automatically replaces detected secrets with placeholder values before "
            "they reach the AI model. Complements secret scanning — scanning blocks, "
            "redaction masks and allows through."
        ),
        "catches": [
            "All patterns matched by the configured secret scanner engines",
            "Redacts in tool output before the AI model sees the content",
        ],
        "does_not_catch": [
            "Secrets that the scanner engines don't detect",
            "Secrets in user prompts (redaction is PostToolUse only by default)",
        ],
        "config_summary": (
            "secret_redaction.enabled — toggle on/off\n"
            "secret_redaction.action — warn | log-only\n"
            "secret_redaction.preserve_format — mask with same character count\n"
            "secret_redaction.log_redactions — log each redaction for audit"
        ),
        "doc_url": f"{_GITHUB_DOCS}/security/SECRET_SCANNING.md",
    },
    "tool_permissions": {
        "title": "Tool Permissions",
        "summary": (
            "Controls which Claude Code tools, skills (slash commands), and MCP server "
            "tools are allowed or denied. Uses ordered allow/deny rules with glob matching."
        ),
        "catches": [
            "Unauthorized tool invocations not in any allow rule",
            "Explicitly denied tools in deny rules",
            "MCP server tool calls not in the allowlist",
        ],
        "does_not_catch": [
            "Tools allowed by a broader rule — be specific with deny rules",
        ],
        "config_summary": (
            "permissions.enabled — toggle enforcement on/off\n"
            "permissions.rules[] — ordered list of {pattern, action, scope} entries\n"
            "permissions.default_action — allow | deny (default: allow)"
        ),
        "doc_url": f"{_GITHUB_DOCS}/TOOL_POLICY.md",
    },
}

# Maps TUI panel IDs to doc URLs (only panels with dedicated docs)
PANEL_DOC_URLS: dict = {
    k: v["doc_url"]
    for k, v in {
        "panel-secrets": SCANNER_HELP["secret_scanning"],
        "panel-secret-redaction": SCANNER_HELP["secret_redaction"],
        "panel-scan-pii": SCANNER_HELP["scan_pii"],
        "panel-pi-detection": SCANNER_HELP["prompt_injection"],
        "panel-pi-jailbreak": SCANNER_HELP["prompt_injection"],
        "panel-pi-patterns": SCANNER_HELP["prompt_injection"],
        "panel-pi-unicode": SCANNER_HELP["prompt_injection"],
        "panel-ssrf": SCANNER_HELP["ssrf_protection"],
        "panel-context-poisoning": SCANNER_HELP["context_poisoning"],
        "panel-config-scanner": SCANNER_HELP["config_file_scanning"],
        "panel-global-settings": SCANNER_HELP["global_settings"],
        "panel-skills": SCANNER_HELP["tool_permissions"],
        "panel-mcp": SCANNER_HELP["tool_permissions"],
    }.items()
    if v["doc_url"]
}


def _build_field_help() -> dict:
    """Extract per-field help text from _comment_* keys in the default config template."""
    try:
        from ai_guardian.setup import _get_default_config_template

        config = _get_default_config_template()
    except Exception:
        return {}

    result: dict = {}

    def walk(obj: dict, prefix: str = "") -> None:
        for k, v in obj.items():
            if k.startswith("_comment_"):
                field_name = k[len("_comment_") :]
                key = f"{prefix}.{field_name}" if prefix else field_name
                result[key] = str(v)
            elif not k.startswith("_") and isinstance(v, dict):
                walk(v, f"{prefix}.{k}" if prefix else k)

    walk(config)
    return result


# Maps "section.field" (or top-level "field") → help text sourced from _comment_* in setup.py.
CONFIG_FIELD_HELP: dict = _build_field_help()

# Supplement: entries not covered by _comment_* in setup.py.
# Follows same "section.field" key convention.
_FIELD_HELP_SUPPLEMENT: dict = {
    # ── context_poisoning (no _comment_ in setup.py) ────────────────────────
    "context_poisoning": (
        "Detect persistent instruction injection attempts (OWASP LLM03). "
        "Catches phrases that try to permanently alter the AI's behavior "
        "across the whole session."
    ),
    # ── Common action field for every scanner ────────────────────────────────
    "prompt_injection.action": (
        "Action on detection: block (default), warn, log-only, ask "
        "(interactive prompt), ask:warn (ask with warn fallback), ask:log-only."
    ),
    "scan_pii.action": (
        "Action on PII detection: block, redact (replace with [REDACTED]), "
        "ask (interactive prompt), warn, or log-only."
    ),
    "ssrf_protection.action": (
        "Action on SSRF detection: block (default, recommended), warn "
        "(allow with warning), or log-only (silent logging)."
    ),
    "config_file_scanning.action": (
        "Action on detection: block (default), ask (interactive prompt), "
        "warn, or log-only."
    ),
    "supply_chain.action": (
        "Action on supply chain threat detection: block (recommended), "
        "ask (interactive prompt), warn, or log-only."
    ),
    "code_scanning.action": (
        "Action on insecure code detection: block, ask (interactive prompt), "
        "warn (default), or log-only."
    ),
    "canary_detection.action": (
        "Action when a registered canary token is detected in AI output: "
        "block (default), ask, warn, or log-only."
    ),
    "exfil_detection.action": (
        "Action when a credential-stealing command is detected: block (default), "
        "ask (interactive prompt), warn, or log-only."
    ),
    "scan_offensive.action": (
        "Action on offensive language detection: log (default), block, ask, "
        "warn, or log-only."
    ),
    "secret_redaction.action": (
        "Action after redacting a secret: warn (default — notify with warning) "
        "or log-only (silent redaction)."
    ),
    "annotations.action": (
        "Annotations mode. Set enabled: false to disable inline suppression "
        "in strict compliance environments."
    ),
    # ── Common ignore_files / ignore_tools ──────────────────────────────────
    "secret_scanning.ignore_files": (
        "Glob patterns for files to exclude from secret scanning. "
        "Example: ['tests/**', '**/*.md', '.env.example']."
    ),
    "secret_scanning.ignore_tools": (
        "Tool names to skip secret scanning on. "
        "Example: ['Write', 'Edit'] to skip file-write tools."
    ),
    "prompt_injection.ignore_files": (
        "Glob patterns for files to exclude from prompt injection scanning. "
        "Useful to suppress false positives in documentation or test fixtures."
    ),
    "prompt_injection.ignore_tools": (
        "Tool names to skip prompt injection scanning on."
    ),
    "scan_pii.ignore_files": (
        "Glob patterns for files to exclude from PII scanning. "
        "Example: ['tests/**', 'fixtures/**']."
    ),
    "scan_pii.ignore_tools": "Tool names to skip PII scanning on.",
    "ssrf_protection.ignore_files": (
        "Glob patterns for files to exclude from SSRF scanning."
    ),
    "ssrf_protection.ignore_tools": (
        "Tool names to skip SSRF URL checking on. "
        "Example: ['WebFetch'] if you want to allow unrestricted fetches."
    ),
    "config_file_scanning.ignore_files": (
        "Glob patterns for config files to exclude from exfiltration scanning."
    ),
    "config_file_scanning.ignore_tools": (
        "Tool names to skip config file scanning on."
    ),
    "context_poisoning.ignore_files": (
        "Glob patterns for files to exclude from context poisoning detection."
    ),
    "context_poisoning.ignore_tools": (
        "Tool names to skip context poisoning detection on."
    ),
    # ── prompt_injection sub-fields ─────────────────────────────────────────
    "prompt_injection.detector": (
        "Detection engine: heuristic (fast, local, default), rebuff (ML-based, "
        "requires API key), or llm-guard (local ML model)."
    ),
    "prompt_injection.sensitivity": (
        "Detection sensitivity: low (fewer false positives), medium (balanced, "
        "default), high (catches more but may have more false positives)."
    ),
    "prompt_injection.max_score_threshold": (
        "Score cutoff for ML-based detectors (0.0–1.0). Detections above this "
        "threshold are treated as injections. Lower = more sensitive."
    ),
    # ── scan_pii sub-fields ─────────────────────────────────────────────────
    "scan_pii.pii_types": (
        "PII types to detect. Phase 1 defaults: ssn, credit_card, phone, "
        "us_passport, iban, international_phone. Opt-in: email, address, "
        "canada_sin, india_aadhaar, medical_id, passport, uk_nin."
    ),
    "scan_pii.allowlist_patterns": (
        "Regex patterns for known-safe PII-like values to suppress. "
        "Example: test SSNs or placeholder credit card numbers."
    ),
    # ── ssrf_protection sub-fields ──────────────────────────────────────────
    "ssrf_protection.allow_localhost": (
        "Allow requests to localhost/127.0.0.1. Disabled by default — "
        "enable only if your workflow requires local service access."
    ),
    "ssrf_protection.additional_blocked_ips": (
        "Additional IP addresses or CIDR ranges to block, beyond the built-in "
        "private IP ranges and metadata endpoints."
    ),
    "ssrf_protection.additional_blocked_domains": (
        "Custom domain names to block. Useful for internal hostnames that "
        "should not be accessible to the AI agent."
    ),
    # ── code_scanning sub-fields ────────────────────────────────────────────
    "code_scanning.severity": (
        "Minimum Bandit severity level to report: LOW, MEDIUM (default), or HIGH. "
        "Lower values catch more issues but increase false positives."
    ),
    "code_scanning.allowlist": (
        "Bandit test IDs or CWE numbers to suppress. "
        "Example: ['B101'] to suppress assert-usage warnings in tests."
    ),
    # ── canary_detection sub-fields ─────────────────────────────────────────
    "canary_detection.tokens": (
        "List of canary token values to detect. Register unique strings (UUIDs, "
        "fake credentials) that should never appear in AI output. "
        "Detection triggers when the AI echoes back one of these values."
    ),
    # ── scan_offensive sub-fields ───────────────────────────────────────────
    "scan_offensive.categories": (
        "Which categories to scan: profanity, slurs, non_inclusive. "
        "Defaults to all three. Disable individual categories to reduce "
        "false positives in domain-specific contexts."
    ),
    # ── secret_scanning additional sub-fields ───────────────────────────────
    "secret_scanning.allowlist_patterns": (
        "Regex patterns for known-safe secret-like values to suppress. "
        "Example: test API keys, placeholder tokens in fixtures."
    ),
    # ── supply_chain sub-fields ─────────────────────────────────────────────
    "supply_chain.scan_targets": (
        "Which agent config file types to scan: hooks (.claude/settings.json, "
        ".cursor/settings.json), mcp_servers, plugins. Defaults to all."
    ),
    "supply_chain.allowlist_paths": (
        "File paths to exclude from supply chain scanning. "
        "Example: ['vendor/**', '.claude/local-settings.json']."
    ),
    # ── global fields ───────────────────────────────────────────────────────
    "secret_scanning.enabled": (
        "Enable or disable secret scanning globally. "
        "When disabled, no secrets are scanned regardless of action setting."
    ),
    "prompt_injection.enabled": (
        "Enable or disable prompt injection detection. "
        "Disable only in trusted, controlled environments."
    ),
    "scan_pii.enabled": ("Enable or disable PII detection globally."),
    "ssrf_protection.enabled": (
        "Enable or disable SSRF URL checking. "
        "Disable only if your workflow requires unrestricted network access."
    ),
    "context_poisoning.enabled": (
        "Enable or disable context poisoning detection. "
        "Recommended: enabled with 'warn' action to avoid false-positive blocks."
    ),
    "supply_chain.enabled": (
        "Enable or disable supply chain scanning of agent config files."
    ),
    "code_scanning.enabled": (
        "Enable or disable Bandit Python code security scanning."
    ),
    "canary_detection.enabled": (
        "Enable canary token detection. Disabled by default — "
        "register at least one token before enabling."
    ),
    "exfil_detection.enabled": ("Enable or disable exfiltration behavior detection."),
    "scan_offensive.enabled": (
        "Enable offensive language scanning. Disabled by default — "
        "opt in after reviewing false positive rate for your use case."
    ),
    "secret_redaction.enabled": (
        "Enable secret redaction from tool outputs. "
        "When enabled, detected secrets are replaced with [REDACTED] before "
        "they reach the AI agent's context."
    ),
    "config_file_scanning.enabled": (
        "Enable config file exfiltration detection. "
        "Watches for agent configs reading sensitive files like .env or ~/.ssh."
    ),
    "annotations.enabled": (
        "Enable inline annotation-based suppression. "
        "When enabled, developers can use ai-guardian:allow comments to "
        "suppress specific findings in source code."
    ),
    "violation_logging.enabled": (
        "Enable violation logging to disk. "
        "When enabled, all blocked operations are recorded for audit review."
    ),
    "latency_tracking.enabled": (
        "Enable hook latency tracking. "
        "Records per-hook timing to latency.jsonl for performance analysis."
    ),
    "permissions.enabled": (
        "Enable tool permission enforcement. "
        "When enabled, the rules[] list controls which tools the AI can use."
    ),
    # ── violation_logging sub-fields ────────────────────────────────────────
    "violation_logging.log_file": (
        "Path to the violation log file. "
        "Defaults to ~/.config/ai-guardian/violations.jsonl."
    ),
    "violation_logging.max_entries": (
        "Maximum number of violation entries to retain in the log. "
        "Older entries are pruned when the limit is reached."
    ),
    # ── context_poisoning sub-fields ────────────────────────────────────────
    "context_poisoning.sensitivity": (
        "Detection sensitivity: low (fewer false positives), medium (balanced, "
        "default), high (catches more persistent injection patterns)."
    ),
    "context_poisoning.allowlist_patterns": (
        "Regex patterns for known-benign context phrases to suppress. "
        "Useful when your workflow intentionally uses persistent instruction patterns."
    ),
    "context_poisoning.custom_patterns": (
        "Additional regex patterns to detect as context poisoning attempts, "
        "beyond the built-in ruleset."
    ),
}

# Merge supplement into CONFIG_FIELD_HELP (auto-extracted entries take priority
# since they come from the authoritative _comment_* in setup.py).
_FIELD_HELP_SUPPLEMENT.update(CONFIG_FIELD_HELP)
CONFIG_FIELD_HELP = _FIELD_HELP_SUPPLEMENT
