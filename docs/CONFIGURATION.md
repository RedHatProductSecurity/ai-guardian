# Configuration Guide

AI Guardian uses a flexible configuration system with multiple sources and cascading priority rules.

## Tracing

Unified SDK and hook trace recording is configured at the top level:

```json
{
  "tracing": {
    "enabled": true,
    "auto_refresh_interval_seconds": 5,
    "trace_cache_retention_days": 90
  }
}
```

`enabled` defaults to `true`. Setting it to `false` stops new trace recording
but does not disable security scanning, violation logging, OTEL export, or
browsing existing traces. The deprecated `sdk.trace_viewer` location remains a
1.x compatibility fallback; top-level `tracing` values take precedence. It is
scheduled for removal in 2.x (#2194).

## Configuration Files

AI Guardian loads configuration from multiple sources in a specific priority order:

### 1. User Configuration (Default)

**Location**: `~/.config/ai-guardian/ai-guardian.json`

This is where most users configure AI Guardian. It contains:
- Tool/Skill permission rules
- Secret scanning settings
- Prompt injection detection
- SSRF protection rules
- Remote config URLs (user-defined)

### 2. Project-Level Config Overlay (NEW in v1.8.0)

**Location**: `.ai-guardian/ai-guardian.json` in the repository root

A project-level config that merges on top of the global config. Discovered via git root, then CWD. Commit the `.ai-guardian/` directory to version control so the whole team shares the same scanning rules.

**Discovery order**:
1. `AI_GUARDIAN_PROJECT_CONFIG` env var (explicit override)
2. Git repo root / `.ai-guardian/ai-guardian.json`
3. CWD / `.ai-guardian/ai-guardian.json`

**What can be overridden**: Prompt injection, secret scanning, PII, SSRF, permissions, directory rules, annotations, and more.

**Global-only sections** (cannot be overridden): `daemon`, `mcp_server`, `support`, `security_instructions`, `on_scan_error`, `remote_configs`.

**Immutable fields**: Add `immutable` to sections in the global config to lock fields from project override:

```json
{
  "prompt_injection": {
    "enabled": true,
    "immutable": ["enabled"],
    "action": "block"
  }
}
```

Projects cannot override `enabled` but can change `action`.

**Self-protection**: The agent is blocked from reading this file (same protection as the global config).

### 3. Legacy Local Configuration

**Location**: `.ai-guardian.json` (in project directory, hidden file)

Legacy project-specific overrides. Used only when no global config exists. For new setups, use the project-level overlay above instead.

### Project-level .aiguardignore.toml

**Location**: `.aiguardignore.toml` in the project root (next to `.gitleaks.toml`)

A TOML file for declaring which files to skip during scanning, using a structure consistent with `.gitleaks.toml`. Unlike the JSON config's `ignore_files`, this file is designed to be committed to version control so the whole team shares the same ignore rules.

**Format**:

```toml
# Global allowlist — applies to ALL scanners
[allowlist]
    paths = [
        "tests/fixtures/**",
        "tests/unit/test_ai_guardian.py",
    ]

# Per-scanner allowlists
[secret_scanning.allowlist]
    paths = ["tests/integration/test_scanner.py"]

[scan_pii.allowlist]
    paths = ["tests/unit/test_pii_detection.py"]

[prompt_injection.allowlist]
    paths = ["docs/security-patterns.md"]

[config_file_scanning.allowlist]
    paths = ["examples/*.json"]
```

**Behavior**:
- Global `[allowlist]` paths are merged into every scanner's `ignore_files`
- Per-scanner paths only apply to that scanner
- Paths from `.aiguardignore.toml` are **additive** with JSON config `ignore_files` (both apply)
- Cached by mtime — no performance cost for unchanged files
- Paths with `..` are blocked for security

**Relationship to `.gitleaks.toml`**: `.aiguardignore.toml` skips entire files across all scanners. `.gitleaks.toml` filters individual secret findings (regex, stopwords, per-rule allowlists). They are complementary.

**VS Code / Taplo validation**: A [JSON schema](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/src/ai_guardian/schemas/aiguardignore.schema.json) is available for autocompletion and validation. New files created by AI Guardian include a `#:schema` header that Taplo detects automatically. For existing files, add to `.vscode/settings.json`:

```json
{
  "evenBetterToml.schema.associations": {
    ".aiguardignore.toml": "https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/src/ai_guardian/schemas/aiguardignore.schema.json"
  }
}
```

### 3. Remote Configurations

**Location**: Fetched from URLs defined in `remote_configs`

Remote configurations enable centralized policy management. Enterprises can deploy security policies that users automatically receive.

## Security Profiles

Built-in profiles let you apply a complete security posture in one command:

```bash
ai-guardian setup --create-config --profile @minimal        # Personal projects, low friction
ai-guardian setup --create-config --profile @standard       # Team development (default)
ai-guardian setup --create-config --profile @strict         # Enterprise SOC2/compliance
ai-guardian setup --create-config --profile @moderator      # Human-in-the-loop review
ai-guardian setup --list-profiles                           # List all available profiles
```

| Profile | Secrets | PII | Prompt Injection | SSRF | Use case |
|---------|---------|-----|------------------|------|----------|
| `@minimal` | block | warn | low | warn | Personal projects, low friction |
| `@standard` (default) | block | block | medium | block | Team development |
| `@strict` | block | block | high | block | Enterprise SOC2/compliance |
| `@moderator` | ask | ask | medium | ask | Human review, training, onboarding |

### @moderator Profile

The `@moderator` profile sets every scanner action to `ask`, routing each finding through an interactive dialog where the user decides allow or block. It is designed for:

- **New users** learning what ai-guardian catches — see every finding, decide case by case
- **Teams evaluating** detection accuracy before committing to block/allow policies
- **Compliance review** where each finding needs explicit human sign-off
- **Training and onboarding** — understand the tool's coverage interactively

> **Note:** `ask` mode requires the daemon tray for the interactive dialog. Without daemon mode, findings fall back to the `on_scan_error` behavior (`allow` by default). Run `ai-guardian daemon start` before using this profile for the full moderator experience.

## Remote Config URL Cascading Priority (Security Feature)

**⚠️ IMPORTANT**: Remote config URLs use **cascading priority** to prevent users from bypassing enterprise policies.

### How Cascading Priority Works

AI Guardian checks remote config sources in order and **stops at the first one found**:

1. **System Config** (Highest Priority)
   - **Linux/macOS**: `/etc/ai-guardian/remote-configs.json`
   - **Windows**: `C:\ProgramData\ai-guardian\remote-configs.json`
   - **Requires**: Root/Administrator access to create
   - **Effect**: If exists, user/local remote URLs are **completely ignored**

2. **Environment Variable**
   - `AI_GUARDIAN_REMOTE_CONFIG_URLS` (comma-separated URLs)
   - **Effect**: If set, user/local remote URLs are **completely ignored**

3. **User Config**
   - `~/.config/ai-guardian/ai-guardian.json` → `remote_configs.urls`
   - **Effect**: If present, local config remote URLs are **ignored**

4. **Local Config** (Lowest Priority)
   - `~/.ai-guardian.json` → `remote_configs.urls`
   - **Effect**: Only used if no higher priority source exists

### Why Cascading Priority Matters

**Without Cascading (Vulnerable)**:
- Enterprise deploys remote policy: `https://company.com/policy.json`
- User adds their own URL: `https://attacker.com/bypass.json`
- Both load → User can override enterprise security settings ❌

**With Cascading (Secure)**:
- Enterprise deploys system config: `/etc/ai-guardian/remote-configs.json`
- User tries to add their own URL → **Ignored completely** ✅
- Only enterprise URLs load → Security enforced

### Example: Enterprise Deployment

**Step 1: Create system config** (requires root):

```bash
# Linux/macOS
sudo mkdir -p /etc/ai-guardian
sudo tee /etc/ai-guardian/remote-configs.json > /dev/null <<EOF
{
  "urls": [
    "https://security.company.com/ai-guardian/policy.json"
  ]
}
EOF
sudo chmod 644 /etc/ai-guardian/remote-configs.json
```

```powershell
# Windows (requires Administrator)
New-Item -ItemType Directory -Force -Path "C:\ProgramData\ai-guardian"
Set-Content -Path "C:\ProgramData\ai-guardian\remote-configs.json" -Value @"
{
  "urls": [
    "https://security.company.com/ai-guardian/policy.json"
  ]
}
"@
```

**Step 2: Deploy remote policy**:

Host `https://security.company.com/ai-guardian/policy.json`:

```json
{
  "permissions": {
    "enabled": true,
    "rules": [
      {
        "matcher": "Skill",
        "mode": "allow",
        "patterns": ["company-approved-*"],
        "immutable": true
      }
    ]
  },
  "ssrf_protection": {
    "enabled": true,
    "immutable": true
  }
}
```

**Step 3: Users are protected**:

Users who try to add their own remote URLs in `~/.config/ai-guardian/ai-guardian.json` will find them **completely ignored** because the system config takes priority.

### Example: Development Environment

**Without System Config** (flexible):

Developers can configure their own remote URLs:

```json
{
  "remote_configs": {
    "urls": [
      "https://dev-patterns.company.com/ai-guardian.json"
    ]
  }
}
```

### Example: Environment Variable Override

Useful for CI/CD or temporary policy changes:

```bash
# Override remote config for this session
export AI_GUARDIAN_REMOTE_CONFIG_URLS="https://ci.company.com/policy.json"
ai-guardian validate
```

## Configuration Merge Order

Configurations are merged in this order (later sources override earlier ones):

1. **Built-in defaults** (in ai_guardian/setup/config.py)
2. **Remote configs** (from cascading priority URLs)
3. **User config** (`~/.config/ai-guardian/ai-guardian.json`)
4. **Local config** (`~/.ai-guardian.json`)

**Exception**: Fields marked with `"immutable": true` in remote configs **cannot be overridden** by user/local configs.

## Immutability

Remote configurations can mark sections or matchers as immutable:

### Section-Level Immutability

```json
{
  "ssrf_protection": {
    "enabled": true,
    "immutable": true
  }
}
```

Users cannot override ANY settings in the `ssrf_protection` section.

### Matcher-Level Immutability

```json
{
  "permissions": {
    "rules": [
      {
        "matcher": "Skill",
        "mode": "allow",
        "patterns": ["approved-*"],
        "immutable": true
      }
    ]
  }
}
```

Users cannot add/modify Skill permission rules.

## Best Practices

### For Enterprises

1. **Start with Recommendations**
   - Deploy remote configs without system config first
   - Monitor adoption via logging
   - Move to system config after 80%+ adoption

2. **Use Immutability Sparingly**
   - Only mark critical security settings as immutable
   - Allow teams flexibility for non-security settings

3. **Provide Multiple Profiles**
   - Production: Strict security, immutable
   - Development: Relaxed security, overridable

4. **Document Policies**
   - Explain WHY settings are immutable
   - Provide contact info for exceptions

### For Users

1. **Check System Config First**
   - Look for `/etc/ai-guardian/remote-configs.json` (Linux/macOS)
   - If exists, your remote URLs are ignored

2. **Use User Config for Personal Settings**
   - `~/.config/ai-guardian/ai-guardian.json` for personal preferences
   - Won't override enterprise policies

3. **Use Local Config for Project Settings**
   - `~/.ai-guardian.json` for project-specific rules
   - Lowest priority, easily overridden

## Troubleshooting

### Config Key Typos

Run `ai-guardian doctor` to detect unknown or misspelled config keys. The `unknown_config_keys` check validates all root and nested keys against the JSON schema and suggests corrections via fuzzy matching (e.g., `"secrt_scanning"` → did you mean `"secret_scanning"`?).

### My Remote URLs Are Ignored

**Symptom**: URLs in user/local config not loading

**Check**:
1. Does `/etc/ai-guardian/remote-configs.json` exist? (Linux/macOS)
2. Is `AI_GUARDIAN_REMOTE_CONFIG_URLS` set?
3. Do you have remote URLs in a higher priority config?

**Solution**: Remove higher priority sources or contact your administrator.

### How Do I Know Which Config Is Active?

Enable debug logging:

```bash
export AI_GUARDIAN_LOG_LEVEL=DEBUG
ai-guardian validate
```

Look for log messages like:
- `Using 2 enterprise remote URLs (system config)`
- `Using remote URLs from environment variable`
- `Using 1 remote URLs from user config`

### Enterprise Policy Is Too Restrictive

**Do NOT**:
- Try to bypass with local URLs (won't work)
- Modify system config (requires root, against policy)

**Do**:
- Contact your security team
- Request policy exception
- Propose policy changes

## Security Considerations

### System Config Security

- Requires root/admin to modify → Prevents user tampering
- Should be managed via configuration management (Ansible, Puppet, etc.)
- Changes require root access → Audit trail in system logs

### Remote Config Security

- Use HTTPS URLs (required for security)
- Implement authentication via `token_env` for private repos
- Validate remote configs are from trusted sources
- Monitor remote config changes via violation logs

### Immutability Bypass Prevention

The cascading priority system (Issue #255) prevents users from:
- Adding attacker-controlled remote URLs
- Overriding immutable security settings
- Bypassing enterprise policies

This is a critical security feature.

## Supply Chain Scanning

**NEW in v1.11.0** — Detects malicious patterns in agent configuration files.

```json
{
  "supply_chain": {
    "enabled": true,
    "action": "block",
    "scan_hooks": true,
    "scan_mcp_configs": true,
    "scan_plugins": true,
    "allowlist_paths": []
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `true` | Enable supply chain threat detection |
| `action` | `"block"` | `block` / `warn` / `log-only` |
| `scan_hooks` | `true` | Scan hooks.json and settings.json for Claude, Cursor, Copilot, Codex, Windsurf, Gemini, Augment |
| `scan_mcp_configs` | `true` | Scan MCP server command configs for suspicious patterns |
| `scan_plugins` | `true` | Scan OpenCode plugins and AiderDesk extensions for dangerous APIs |
| `allowlist_paths` | `[]` | File paths to skip (supports `~` expansion and globs). AI Guardian's own plugin files are always skipped. |

**Detection categories**: download-and-execute, obfuscation, env hijacking, network exfiltration, MCP suspicious commands, config key hijacking, reverse shells, plugin dangerous APIs.

## Context Poisoning Detection

**NEW in v1.11.0** (OWASP LLM03) — Detects attempts to inject persistent malicious instructions into conversation context.

```json
{
  "context_poisoning": {
    "enabled": true,
    "action": "warn",
    "sensitivity": "medium",
    "allowlist_patterns": [],
    "custom_patterns": []
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `true` | Enable context poisoning detection |
| `action` | `"warn"` | `block` / `warn` / `log-only`. Default is `warn` due to higher false positive risk. |
| `sensitivity` | `"medium"` | `low` (dangerous combinations only) / `medium` (balanced) / `high` (any persistence keyword) |
| `allowlist_patterns` | `[]` | Regex patterns to ignore false positives |
| `custom_patterns` | `[]` | Additional persistence patterns beyond the 13 built-in defaults |

## Per-Scanner Filtering

**NEW in v1.12.0** — Exclude specific tools or file patterns from individual scanners.

Available on: `secret_scanning`, `prompt_injection`, `scan_pii`, `context_poisoning`, `config_scanner`, `supply_chain`.

```json
{
  "secret_scanning": {
    "enabled": true,
    "ignore_tools": ["Read"],
    "ignore_files": ["*.test.py", "docs/*.md"]
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `ignore_tools` | `[]` | Tool names to skip when scanning (glob patterns supported) |
| `ignore_files` | `[]` | File path patterns to skip for this scanner (glob patterns supported) |

These are per-scanner overrides. For project-wide file exclusions shared via version control, see [.aiguardignore.toml](#project-level-aiguardignoretoml) above.

## Secret Liveness Validation

**NEW in v1.11.0** — After detecting a secret, optionally check if it is still active by calling provider APIs.

Configure within the `secret_scanning` section:

```json
{
  "secret_scanning": {
    "validate_secrets": false,
    "validation_timeout_ms": 3000,
    "on_inactive": "warn"
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `validate_secrets` | `false` | Enable liveness validation. Must be explicitly opted in — sends detected secrets to provider APIs. |
| `validation_timeout_ms` | `3000` | Timeout per validation request in milliseconds |
| `on_inactive` | `"warn"` | Action for inactive (revoked/expired) secrets: `warn` (log warning, don't block) or `allow` (silently skip). Verified-active and unverified secrets always block. |

**Built-in validators**: github-personal-token, openai-api-key, anthropic-api-key, slack-token, gitlab-personal-token, npm-token.

## Latency Tracking

**NEW in v1.11.0** — Records per-hook and per-check timing for performance analysis.

```json
{
  "latency_tracking": {
    "enabled": false,
    "max_entries": 5000,
    "retention_days": 30
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `false` | Enable hook latency tracking |
| `max_entries` | `5000` | Maximum entries in `latency.jsonl` |
| `retention_days` | `30` | Auto-prune entries older than this |

View with: `ai-guardian metrics --latency`. Data stored in `~/.local/state/ai-guardian/latency.jsonl`.

## Project Config Generation (v1.15.0+)

### init-project --scan

Auto-generate a project-level config by scanning your codebase for false positives:

```bash
ai-guardian init-project --scan
```

This analyzes your project files, identifies likely false positives, and generates an `.ai-guardian/ai-guardian.json` with appropriate `allowlist_patterns`, `ignore_files`, and `stopwords` entries. Use the `--threshold` flag to control how aggressively patterns are suppressed:

```bash
ai-guardian init-project --scan --threshold 3    # Only suppress patterns seen 3+ times
```

Lower thresholds produce more permissive configs; higher thresholds are more conservative.

### Language Overlay System

AI Guardian auto-detects your project's primary language (Python, Go, JavaScript, etc.) and injects language-specific false positive suppressions. For example, Go projects automatically suppress common Go test patterns, and Python projects suppress Django/Flask placeholder patterns.

Language detection runs during `init-project --scan` and during normal scanning when a project config is present. The overlays are additive — they extend your existing config without replacing user-defined rules.

## Per-Rule File Type Skipping (v1.15.0+)

Individual TOML pattern rules can declare `skip_file_types` to exclude specific file extensions:

```json
{
  "secret_scanning": {
    "engines": ["toml-patterns"]
  }
}
```

The `skip_file_types` field is set per-rule in TOML pattern files (not in `ai-guardian.json`). See [TOML_PATTERNS.md](TOML_PATTERNS.md) for the rule field reference.

---

## Related Documentation

- [MCP Security Advisor](MCP_SERVER.md)
- [SSRF Protection](security/SSRF_PROTECTION.md)
- [Secret Scanning](security/SECRET_SCANNING.md)
- [Permissions System](PERMISSIONS_COMPARISON.md)
- [Hook Configuration](HOOKS.md)
