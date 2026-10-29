# Secret Scanning Configuration Guide

This guide explains how AI Guardian's secret scanning works, including configuration options, pattern server integration, and security measures for secret redaction.

## Table of Contents

- [Overview](#overview)
- [Scanner Engines](#scanner-engines)
- [Configuration](#configuration)
- [Pattern Server Integration](#pattern-server-integration)
- [Secret Redaction Security](#secret-redaction-security)
- [False Positives](#false-positives)
- [Troubleshooting](#troubleshooting)

---

## Overview

AI Guardian provides comprehensive secret scanning to prevent sensitive information from being exposed through AI interactions. The scanning system has two main components:

| Component | Purpose | Controls |
|-----------|---------|----------|
| **`secret_scanning`** | Enable/disable secret scanning | Whether to scan for secrets at all (always blocks when found) |
| **`pattern_server`** | Customize detection patterns | **Which patterns** to use when scanning (enterprise patterns vs defaults) |

**Think of it like this:**
- `secret_scanning` = "Should I scan?" (always blocks secrets when found)
- `pattern_server` = "What secrets should I look for?"

---

## Zero-Install Scanning

**No external scanner required.** ai-guardian ships with a built-in `toml-patterns` engine — a pure Python scanner with 267+ pre-compiled regex patterns covering all major secret types (AWS keys, GitHub tokens, Slack tokens, private keys, and more). It requires no binary installation and works immediately after `pip install ai-guardian`.

External scanners (gitleaks, betterleaks, leaktk) are **optional**. They are tried after `toml-patterns` in the default engine list and gracefully skipped when not installed. Install them only if you want additional pattern coverage or faster scanning on large repos.

```
Default engine order: ["toml-patterns", "gitleaks"]
                           ↑
                     Always available — no install needed
```

---

## Scanner Engines

**NEW in v1.4.0:** AI Guardian now supports multiple scanner engines with automatic fallback.

### Supported Scanners

| Scanner | Speed | Pattern Management | Output Format | Installation |
|---------|-------|-------------------|---------------|--------------|
| **Gitleaks** | Standard | Manual config | JSON | `brew install gitleaks` |
| **BetterLeaks** | 20-40% faster | Manual config | JSON (same as Gitleaks) | `brew install betterleaks` |
| **LeakTK** | Fast (listen mode) | Auto-managed | JSON (custom) | `brew install leaktk/tap/leaktk` |

### Configuration

**Default engine selection:**
```json
{
  "secret_scanning": {
    "enabled": true
    // If engines is omitted, defaults to ["toml-patterns", "gitleaks"]
  }
}
```

An explicit `engines` list replaces that default. For example,
`"engines": ["gitleaks"]` runs Gitleaks only and does not run the built-in
`toml-patterns` engine in this secret-scanning pipeline.

The Console's **Engine Configuration** page shows built-in TOML patterns selected
when the engine list is omitted. Clear **Built-in TOML patterns** to save an
explicit opt-out; the selection remains cleared after using **Reload**. Select it
again to restore built-in pattern scanning.

**External-only example (BetterLeaks with Gitleaks fallback; explicitly opts out
of built-in TOML patterns):**
```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": ["betterleaks", "gitleaks"]
  }
}
```

**Behavior:**
- Tries BetterLeaks first (if installed)
- Falls back to Gitleaks if BetterLeaks not found
- Works on any system (automatic detection)

**Three external scanners (also explicitly opts out of built-in TOML patterns):**
```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": ["leaktk", "betterleaks", "gitleaks"]
  }
}
```

### LeakTK Listen Mode (v1.15.0+)

When the ai-guardian daemon is running and LeakTK (v0.3.3+) is installed, secret scanning uses LeakTK's `listen` mode — a persistent process that stays alive between scans. This eliminates subprocess spawn overhead, reducing per-scan latency from ~200ms to ~5ms.

- **Automatic:** No configuration needed. The daemon detects LeakTK and uses listen mode transparently.
- **Fallback:** If listen mode fails or the daemon is not running (CLI mode), scanning falls back to the standard subprocess path.
- **Config changes:** The listen process restarts automatically when `ai-guardian.json` is modified, picking up new allowlists and settings.
- **Pattern refresh:** LeakTK manages pattern updates internally (default: every 12 hours).

### Detection Techniques (v1.15.0+)

**Prefix-based token detection** — TOML rules can declare `token_prefixes` for fast prefix matching, separate from keyword-based pre-filtering. This enables detection of tokens with known prefixes (e.g., `sk-or-`, `hvs.`, `AIza`) without running the full regex against all content. See [TOML_PATTERNS.md](../TOML_PATTERNS.md) for field documentation.

**Credentials in git remote URLs** — AI Guardian detects credentials embedded in git remote URLs (e.g., `https://user:token@github.com/org/repo`). This pattern catches a common source of credential leaks where tokens are hardcoded into remote URLs instead of using credential helpers. The detection runs automatically as part of the secret scanning pipeline.

### Advanced Configuration

**Custom Binary Path:**
```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": [
      {
        "type": "betterleaks",
        "binary": "/opt/betterleaks/bin/betterleaks",
        "extra_flags": ["--regex-engine=re2"]
      },
      "gitleaks"
    ]
  }
}
```

**Custom Scanner:**
```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": [
      {
        "type": "custom",
        "binary": "my-scanner",
        "command_template": [
          "{binary}", "scan",
          "--input", "{source_file}",
          "--output", "{report_file}",
          "--format", "json"
        ],
        "success_exit_code": 0,
        "secrets_found_exit_code": 1,
        "output_format": "gitleaks-compatible"
      }
    ]
  }
}
```

### Scanner Selection

AI Guardian automatically selects the first available scanner from your `engines` list:

1. **Defaults to toml-patterns:** If no `engines` configured, uses `["toml-patterns", "gitleaks"]` — `toml-patterns` is always available (pure Python, no binary)
2. **Explicit lists replace defaults:** Only engines in `secret_scanning.engines` are selected; a Gitleaks-only list omits `toml-patterns`
3. **Checks availability:** Tries each scanner binary in order
4. **Selects first found:** Uses the first scanner that exists in PATH
5. **Falls back gracefully:** If an external scanner is not installed, the next engine in the list is tried; `toml-patterns` always provides a working fallback when included

`ai-guardian doctor` lists supported engines and indicates which are configured
and installed. It warns when secret scanning is enabled but `toml-patterns` is
not selected.

**Example:**
```bash
# With config: "engines": ["betterleaks", "gitleaks"]

# If betterleaks installed:
$ which betterleaks
/usr/local/bin/betterleaks
# → Uses betterleaks

# If betterleaks NOT installed:
$ which betterleaks
# (not found)
$ which gitleaks
/usr/local/bin/gitleaks
# → Uses gitleaks (fallback)
```

### Error Messages

Error messages now show which scanner detected the secret:

```
======================================================================
🚨 BLOCKED BY POLICY
🔒 SECRET DETECTED
======================================================================

Betterleaks has detected sensitive information in your prompt/file.

Secret Type: aws-access-token
Location: config.py, line 5
Total findings: 1

Detection Source:
  Scanner: betterleaks
  Patterns: Built-in Defaults (100+ rules)

This operation has been blocked for security.
```

---

## Configuration

### Basic Secret Scanning

**Location:** `~/.config/ai-guardian/ai-guardian.json`

```json
{
  "secret_scanning": {
    "enabled": true,           // ← Turn scanning ON/OFF (always blocks when secrets found)
    "ignore_files": [           // ← Files to skip
      "**/tests/fixtures/**",
      "**/.env.example"
    ],
    "ignore_tools": [],         // ← Tools to skip (rarely needed)
    "pattern_server": {         // ← NEW in v1.7.0: Nested here!
      "url": "https://patterns.security.redhat.com",
      "auth": {...}
    }
  }
}
```

### What It Controls

✅ **Global enable/disable** - Turn secret scanning on or off (always blocks when enabled)
✅ **Ignore patterns** - Skip specific files or tools  
✅ **Scanner selection** - Which engine(s) to use (Gitleaks, BetterLeaks, LeakTK, or custom)

**Note:** Secret scanning **always blocks** when secrets are detected. There is no action mode for secret scanning — unlike other features (prompt injection, SSRF, etc.), secrets are always blocked for security reasons.

### Common Configurations

#### Individual Developer (Recommended)

```json
{
  "secret_scanning": {
    "enabled": true
  }
}
```

- Uses Gitleaks default patterns (comprehensive)
- Blocks on secret detection
- No external dependencies

#### Enterprise with Custom Patterns

```json
{
  "secret_scanning": {
    "enabled": true,
    "pattern_server": {
      "url": "https://patterns.company.com",
      "auth": {
        "method": "bearer",
        "token_file": "~/.config/company/pattern-token"
      },
      "cache": {
        "refresh_interval_hours": 12
      }
    }
  }
}
```

- Fetches organization-specific patterns
- Caches patterns locally (refresh every 12h)
- Falls back to defaults if server unavailable

#### Gradual Rollout / Testing

To test secret scanning patterns before full deployment, enable scanning on a subset of projects first, or use `ignore_files` to exclude known false positives while monitoring violations in the Console.

```json
{
  "secret_scanning": {
    "enabled": true,
    "pattern_server": {
      "url": "https://patterns.company.com"
    }
  }
}
```

- Monitor violations in Console to identify false positives
- Adjust `ignore_files` patterns as needed

---

## Pattern Sources

AI Guardian supports multiple pattern sources for secret detection:

### 1. LeakTK Pattern Server (Recommended)

**What is LeakTK?**

[LeakTK](https://github.com/leaktk/patterns) is a community-maintained, open-source collection of secret detection patterns. It provides regularly updated gitleaks patterns for detecting API keys, tokens, passwords, and other credentials.

**Why use LeakTK?**

| Feature | LeakTK Patterns | Gitleaks Defaults |
|---------|----------------|-------------------|
| Rules | 104+ rules | 100+ rules |
| Updates | Community-maintained | Gitleaks releases |
| Cost | Free, no auth | Free |
| Customization | Fork and customize | Requires local file |
| Pattern Quality | Peer-reviewed | Official |

**Configuration:**

```json
{
  "secret_scanning": {
    "pattern_server": {
      "url": "https://raw.githubusercontent.com",
      "patterns_endpoint": "/leaktk/patterns/main/target/patterns/gitleaks/8.27.0",
      "cache": {
        "refresh_interval_hours": 12,
        "expire_after_hours": 168
      }
    }
  }
}
```

**Options:**

- `url`: GitHub raw content URL (no authentication needed)
- `patterns_endpoint`: Path to gitleaks pattern file
  - Use `main` branch for latest patterns
  - Or pin to specific version: `/leaktk/patterns/v1.0.0/target/patterns/gitleaks/8.27.0`
- `cache.refresh_interval_hours`: How often to check for updates (default: 12)
- `cache.expire_after_hours`: When to consider cache stale (default: 168 = 7 days)

**Cache Location:**

Patterns are cached at: `~/.cache/ai-guardian/leaktk-patterns.toml`

**Troubleshooting:**

Check logs for pattern server activity:
```bash
tail -50 ~/.config/ai-guardian/ai-guardian.log | grep -i "pattern"
```

Expected log entries:
```
INFO: Using pattern server config: ~/.cache/ai-guardian/leaktk-patterns.toml
INFO: Pattern server cache is fresh (last updated: 2026-04-20 10:30:00)
```

If you see warnings:
```
WARNING: Pattern server configured at https://raw.githubusercontent.com but patterns unavailable
```

**Possible causes:**
- Network connectivity issues
- GitHub raw content temporarily unavailable
- Invalid patterns_endpoint path

**Fallback behavior:** AI Guardian automatically falls back to gitleaks defaults if pattern server is unavailable.

### 2. Project-Specific .gitleaks.toml

Create a `.gitleaks.toml` in your project root for custom patterns:

```toml
title = "Custom Project Patterns"

[[rules]]
id = "custom-api-key"
description = "Custom API Key"
regex = '''my-api-key-[a-z0-9]{32}'''
```

**Priority:** If both pattern server and `.gitleaks.toml` exist, pattern server takes priority.

### 3. Gitleaks Defaults (Fallback)

If no pattern server or project config, AI Guardian uses gitleaks built-in patterns (100+ rules).

**Priority order:**
1. Pattern server (if configured and reachable)
2. Project `.gitleaks.toml` (if exists)
3. Gitleaks defaults (always available)

## LeakTK Pattern Versions

LeakTK provides patterns for different gitleaks versions:

| Gitleaks Version | Endpoint Path |
|------------------|---------------|
| 8.27.0 | `/leaktk/patterns/main/target/patterns/gitleaks/8.27.0` |
| 8.26.0 | `/leaktk/patterns/main/target/patterns/gitleaks/8.26.0` |
| 8.25.0 | `/leaktk/patterns/main/target/patterns/gitleaks/8.25.0` |

**Check your gitleaks version:**
```bash
gitleaks version
```

**Use matching LeakTK pattern version** for best compatibility.

## Advanced: Custom Pattern Server

You can host your own pattern server:

```json
{
  "secret_scanning": {
    "pattern_server": {
      "url": "https://patterns.mycompany.com",
      "patterns_endpoint": "/patterns/gitleaks/latest.toml",
      "auth": {
        "method": "bearer",
        "token_file": "~/.config/ai-guardian/pattern-server-token"
      }
    }
  }
}
```

**Requirements:**
- Serve gitleaks-compatible `.toml` patterns
- HTTPS endpoint
- Optional: Token-based authentication

## Example Workflow

**1. Start with LeakTK patterns:**
```json
{
  "secret_scanning": {
    "pattern_server": {
      "url": "https://raw.githubusercontent.com",
      "patterns_endpoint": "/leaktk/patterns/main/target/patterns/gitleaks/8.27.0"
    }
  }
}
```

**2. Add project-specific allowlists:**

Create `.gitleaks.toml` in your project:
```toml
# Use LeakTK patterns via pattern server
# This file only adds allowlists

[allowlist]
description = "Allow test fixtures"
paths = [
    '''tests/fixtures/.*''',
    '''examples/.*'''
]
```

**Note:** Project `.gitleaks.toml` is ignored when pattern server is configured. To use both:
- Download LeakTK patterns manually
- Add to project `.gitleaks.toml`
- Remove pattern server config

**3. Verify configuration:**
```bash
# Test detection
echo '{"prompt": "github_pat=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}' | ai-guardian

# Check which patterns are active
tail ~/.config/ai-guardian/ai-guardian.log | grep "pattern"
```

## FAQ

**Q: Can I use LeakTK patterns without internet access?**

A: Yes. Download patterns once, then AI Guardian uses the cache:
```bash
# First run (requires internet)
echo '{"prompt": "test"}' | ai-guardian

# Subsequent runs use cache (works offline for 7 days)
echo '{"prompt": "test"}' | ai-guardian
```

**Q: How do I update to the latest LeakTK patterns?**

A: Either:
1. Wait for auto-refresh (default: 12 hours)
2. Delete cache to force immediate refresh:
   ```bash
   rm ~/.cache/ai-guardian/leaktk-patterns.toml
   ```

**Q: Can I use LeakTK patterns AND project .gitleaks.toml?**

A: Pattern server takes priority. If you need both:
1. Download LeakTK patterns: `curl -o .gitleaks.toml https://raw.githubusercontent.com/leaktk/patterns/main/target/patterns/gitleaks/8.27.0`
2. Add your custom rules to `.gitleaks.toml`
3. Remove pattern server config

**Q: What if GitHub raw content is blocked by my firewall?**

A: Host patterns yourself:
1. Download LeakTK patterns
2. Host on internal server
3. Update config:
   ```json
   {
     "pattern_server": {
       "url": "https://internal-patterns.company.com",
       "patterns_endpoint": "/gitleaks/8.27.0.toml"
     }
   }
   ```

**Q: How do I know if LeakTK patterns are being used?**

A: Check error messages (Issue #153):
```
Detection Source:
  Scanner: gitleaks
  Patterns: LeakTK Pattern Server
  URL: https://raw.githubusercontent.com
  Endpoint: /leaktk/patterns/main/target/patterns/gitleaks/8.27.0
```

## False Positives

When secret scanning flags a value that is not a real secret, you have several options to suppress it. The right choice depends on whether the false positive is a one-off finding, a recurring pattern, or an entire file.

### Quick Reference

| Approach | Best For | Scope |
|----------|----------|-------|
| `.gitleaksignore` | One specific finding by fingerprint | Gitleaks only |
| `allowlist_patterns` | Recurring patterns (test keys, placeholders) | All scanners |
| `ignore_files` | Entire files or directories | All scanners |
| `.aiguardignore.toml` | Project-level file ignores (shared via VCS) | All scanners |
| `.gitleaks.toml` `[allowlist]` | Gitleaks-specific path/regex rules | Gitleaks only |
| Inline annotations | Single lines in source code | All scanners |

### .gitleaksignore

Create a `.gitleaksignore` file at your project root to ignore specific findings by fingerprint hash:

```
# .gitleaksignore — one fingerprint per line
# Get fingerprints from gitleaks output or ai-guardian violation logs

a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
f6e5d4c3b2a1f6e5d4c3b2a1f6e5d4c3b2a1f6e5d4c3b2a1f6e5d4c3b2a1f6e5

# Comments start with #
# Blank lines are ignored
```

**Finding fingerprints:**

```bash
# From gitleaks output
gitleaks detect --source . --verbose 2>&1 | grep Fingerprint

# From ai-guardian violation logs
ai-guardian violations --type secret_detected --limit 10
```

**Limitations:** `.gitleaksignore` only works with the Gitleaks engine. For BetterLeaks or LeakTK, use `allowlist_patterns` or `ignore_files`.

### Allowlist Patterns

Suppress recurring false positives across all scanners with regex patterns in `ai-guardian.json`:

```json
{
  "secret_scanning": {
    "allowlist_patterns": [
      "YOUR_TOKEN_HERE",
      "EXAMPLE_API_KEY",
      "pk_test_[A-Za-z0-9]{24,}",
      "\\$\\{[A-Z_]+\\}",
      "<your-.*-here>"
    ]
  }
}
```

Common scenarios:
- **Placeholder values**: `"YOUR_TOKEN_HERE"`, `"REPLACE_ME"`, `"changeme"`
- **Environment variable references**: `"\\$\\{[A-Z_]+\\}"`, `"\\$[A-Z_]+"`
- **Test/public keys**: `"pk_test_[A-Za-z0-9]{24,}"`
- **Template placeholders**: `"<your-.*-here>"`
- **Masked values**: `"x{8,}"`

Supports time-limited patterns — see [COOKBOOK.md](../COOKBOOK.md#how-do-i-add-a-time-limited-allowlist-pattern).

### Inline Annotations

Suppress a single line with an inline comment:

```python
API_KEY = "pk_test_example123456789012"  # ai-guardian:allow
```

**Built-in aliases** (work out of the box):

| Alias | Suppresses |
|-------|-----------|
| `ai-guardian:allow` | Secrets + PII |
| `gitleaks:allow` | Secrets only |

These are the only aliases available by default. To use other keywords (e.g., `notsecret`, `nosec`), configure them in `ai-guardian.json`:

```json
{
  "annotations": {
    "inline_allow": ["nosec"],
    "inline_allow_secrets": ["notsecret"]
  }
}
```

- `inline_allow` — adds custom aliases suppressing secrets + PII (extends built-in `ai-guardian:allow`)
- `inline_allow_secrets` — adds custom aliases suppressing secrets only (extends built-in `gitleaks:allow`)

Custom aliases are additive — built-in aliases always remain active.

Block annotations use `ai-guardian:begin-allow` / `ai-guardian:end-allow` (also configurable via `block_begin` / `block_end`):

```python
# ai-guardian:begin-allow
TEST_DATA = {
    "token": "ghp_faketoken1234567890123456789012345",
    "key": "AKIAIOSFODNN7EXAMPLE",
}
# ai-guardian:end-allow
```

See [Annotations](../ANNOTATIONS.md) for the full configuration reference.

### Recommended Workflow

1. **Investigate** — check `ai-guardian violations` to confirm the finding is a false positive
2. **Choose scope** — use the quick reference table above to pick the narrowest suppression
3. **Apply** — add the suppression rule
4. **Verify** — re-run scanning to confirm the false positive is suppressed
5. **Commit** — check `.gitleaksignore` and `.aiguardignore.toml` into version control so the team benefits

For detailed examples and common false-positive scenarios, see [COOKBOOK.md — Handling False Positives](../COOKBOOK.md#handling-false-positives).

## Pattern Server Integration

### Overview

**Purpose:** Fetch custom secret detection patterns from an enterprise pattern server instead of using Gitleaks default patterns or LeakTK.

**Location:** `~/.config/ai-guardian/ai-guardian.json`

**NEW in v1.7.0:** Nested under `secret_scanning` (was at root level)

### Configuration

```json
{
  "secret_scanning": {
    "enabled": true,
    "pattern_server": {         // ← Nested under secret_scanning (v1.7.0+)
      "url": "https://patterns.security.redhat.com",  // ← Presence = enabled!
      "patterns_endpoint": "/patterns/gitleaks/8.27.0",
      "auth": {
        "method": "bearer",
        "token_env": "AI_GUARDIAN_PATTERN_TOKEN",
        "token_file": "~/.config/rh-gitleaks/auth.jwt"
      },
      "cache": {
        "path": "~/.cache/ai-guardian/patterns.toml",
        "refresh_interval_hours": 12,
        "expire_after_hours": 168
      }
    }
  }
}
```

**Simplified in v1.7.0:**
- ✅ **No `enabled` field needed** - presence of section = enabled
- ✅ **Logical nesting** - pattern_server clearly part of secret scanning
- ✅ **Easier to understand** - all secret scanning config in one place

### What It Controls

✅ **Pattern source** - Where to get detection patterns  
✅ **Enterprise patterns** - Organization-specific secret types  
✅ **Pattern caching** - Local cache with refresh intervals  
✅ **Authentication** - Token-based access to pattern server

### How to Enable/Disable

**Enable pattern server** (v1.7.0+ simplified):
```json
{
  "secret_scanning": {
    "pattern_server": {
      "url": "https://patterns.company.com"  // ← Presence = enabled
    }
  }
}
```

**Disable pattern server:**
```json
{
  "secret_scanning": {
    "pattern_server": null  // ← Explicit disable
  }
}
```

**Or simply don't configure it:**
```json
{
  "secret_scanning": {
    "enabled": true
    // No pattern_server = use defaults
  }
}
```

### Pattern Priority Order

When scanning for secrets, AI Guardian uses patterns in this priority:

```
1. Pattern Server (if configured and available)
   - Enterprise/organization-specific patterns
   - Cached for 7 days if server becomes unavailable
   ↓
2. Scanner Engines (first available from engines list)
   - Example: ["betterleaks", "gitleaks", "leaktk"]
   - Tries each scanner in order until one is found
   - Automatically uses .gitleaks.toml if scanner supports it
   ↓
3. BLOCK if no scanner is available
```

**Key Changes:**
- ✅ Always falls back to scanner engines when pattern server fails
- ✅ Scanner engines automatically detect and use `.gitleaks.toml` if present
- ✅ No configuration needed - fallback is automatic
- ✅ Clear logging at each fallback step

**Example Scenarios:**

**Scenario 1: Pattern server available**
```bash
# Your setup
~/.config/ai-guardian/ai-guardian.json  # pattern_server configured
/your/project/.gitleaks.toml            # exists

# Result: Uses Pattern Server patterns
# .gitleaks.toml is IGNORED (pattern server takes priority)
```

**Scenario 2: Pattern server down, gitleaks installed**
```bash
# Your setup
~/.config/ai-guardian/ai-guardian.json  # pattern_server configured
/your/project/.gitleaks.toml            # exists
$ which gitleaks
/usr/local/bin/gitleaks

# Result:
# 1. Pattern server unavailable (logged warning)
# 2. Falls back to gitleaks scanner
# 3. Gitleaks automatically uses .gitleaks.toml (if present)
# 4. Or uses built-in patterns (if .gitleaks.toml not found)
```

**Scenario 3: No pattern server, has .gitleaks.toml**
```bash
# Your setup
~/.config/ai-guardian/ai-guardian.json  # no pattern_server
/your/project/.gitleaks.toml            # exists

# Result:
# 1. Uses gitleaks scanner (no pattern server configured)
# 2. Gitleaks automatically detects and uses .gitleaks.toml
```

### Pattern Server Workflow

```
User triggers scan (prompt, file read, tool output)
    ↓
secret_scanning.enabled == true?
    YES ↓
        ↓
    pattern_server configured?
        YES ↓
            ↓
        Fetch patterns from server → Cache locally
            ↓
        Use server patterns for scanning
            ↓
        Find secret → BLOCKED (secrets always block)
        
        NO ↓
            ↓
        Use .gitleaks.toml or defaults
            ↓
        Find secret → BLOCKED (secrets always block)
```

### How secret_scanning and pattern_server Work Together

#### Example 1: Pattern Server with Enterprise Patterns

```json
{
  "secret_scanning": {
    "enabled": true,
    "pattern_server": {  // ← Controls WHICH secrets to look for
      "url": "https://patterns.security.redhat.com"
    }
  }
}
```

**Behavior:**
1. User pastes content with AWS key
2. ai-guardian fetches patterns from Red Hat pattern server
3. Pattern server includes AWS key pattern
4. Secret detected → **BLOCKED** (secrets always block)
5. Error shown to user

#### Example 2: No Pattern Server, Default Patterns

```json
{
  "secret_scanning": {
    "enabled": true
  }
}
```

**Behavior:**
1. User pastes content with AWS key
2. ai-guardian uses Gitleaks built-in patterns (no pattern server)
3. Built-in patterns include AWS key detection
4. Secret detected → **BLOCKED** (secrets always block)

### Important Notes

#### Pattern Server Provides Patterns, Not Policy

⚠️ **Note:** Pattern server only provides detection patterns, not policy decisions. Secret scanning always blocks when secrets are detected.

```json
{
  "secret_scanning": {
    "enabled": true,
    "pattern_server": {
      "url": "https://patterns.company.com"
    }
  }
}
```

**Why?** Pattern server provides WHICH secrets to detect. When a secret is detected, it is always blocked — there is no configurable action mode for secret scanning.

#### Pattern Completeness Warning

If pattern server returns fewer than 50 rules, you'll see:

```
WARNING: Pattern server returned only 12 rules. 
Standard Gitleaks has 100+ rules.
Your pattern server may be missing common secret types (AWS keys, RSA keys, etc.).
Ensure your pattern server includes both organization-specific AND default Gitleaks patterns.
```

**What to do:**
1. Check if pattern server includes default Gitleaks patterns
2. Contact pattern server administrator
3. Temporarily disable pattern server to use defaults

#### Pattern Server Unavailable

If pattern server fails:
```
WARNING: Pattern server configured at https://patterns.company.com but patterns unavailable.
Falling back to project config or gitleaks defaults.
Common causes: missing/invalid auth token, network error, server down.
Check token at ~/.config/company/token or see ~/.config/ai-guardian/ai-guardian.log
```

**Behavior:**
- Falls back to project `.gitleaks.toml` (if exists)
- Otherwise uses Gitleaks defaults
- Scanning continues (fail-safe)

---

## Secret Redaction Security

AI Guardian implements **defense-in-depth** for secret value redaction to ensure that actual secret values are **never** exposed in error messages, logs, or temporary files.

### Security Layers

#### Layer 1: Gitleaks `--redact` Flag

**Location**: `src/ai_guardian/__init__.py:1537`

```python
cmd = [
    'gitleaks',
    'detect',
    '--no-git',
    '--verbose',
    '--redact',        # Defense-in-depth: redact Match/Secret fields in JSON
    '--report-format', 'json',
    '--report-path', report_file,
    '--source', tmp_file_path,
]
```

**What it does**:
- Gitleaks replaces all secret values with `"REDACTED"` in its JSON output
- Both `Match` and `Secret` fields show `"REDACTED"` instead of actual values
- Prevents secrets from appearing in Gitleaks stdout/stderr

**Important Note**:
- ai-guardian **never extracts** the `Match` or `Secret` fields
- The `--redact` flag is **defense-in-depth** to safeguard against future code changes
- Even without `--redact`, current implementation wouldn't leak secrets
- We keep it as an extra security layer

**Verification**:
```python
# Gitleaks JSON output with --redact:
{
  "RuleID": "slack-bot-token",
  "Match": "REDACTED",      # ← Not the actual token (we don't use this field)
  "Secret": "REDACTED",     # ← Not the actual secret (we don't use this field)
  "File": "test.py",        # ← We extract this
  "StartLine": 2            # ← We extract this
}
```

#### Layer 2: Never Display or Log Secret Values

**What we extract** (safe metadata only):
- ✅ Rule ID (e.g., "slack-bot-token") - secret type, not value
- ✅ File path - where the secret was found
- ✅ Line numbers - location in file
- ✅ Total findings count - how many secrets

**What we DON'T extract** (fields that contain secret values):
- ❌ `Match` field - contains "REDACTED" (or actual secret without --redact flag)
- ❌ `Secret` field - contains "REDACTED" (or actual secret without --redact flag)
- ❌ Any actual secret value - we only use metadata for error messages

#### Layer 3: Error Messages Show Only Metadata

**Example error message** (user sees):
```
======================================================================
🚨 BLOCKED BY POLICY
🔒 SECRET DETECTED
======================================================================

Gitleaks has detected sensitive information in your prompt/file.

Secret Type: slack-bot-token
Location: test.py, line 2
Total findings: 1

This operation has been blocked for security.
Please remove the sensitive information and try again.
```

**Note**: No actual secret value is shown!

#### Layer 4: Logs Only Metadata

**Log output examples**:
```
2026-04-18 16:30:15 - ai_guardian - ERROR - Secret detected: slack-bot-token
2026-04-18 16:30:15 - ai_guardian - WARNING - Secret detected (log mode): aws-access-token - execution allowed
```

**Note**: Only rule_id logged, never the actual secret!

#### Layer 5: Sanitized Gitleaks stderr

**What's logged**:
- ✅ Length of stderr (for debugging)
- ✅ First line only, truncated to 200 chars
- ✅ Only logged at DEBUG level

**What's NOT logged**:
- ❌ Full Gitleaks stderr (could contain sensitive info in edge cases)

#### Layer 6: Violation Log Excludes Secrets

**Violation log entry** (JSONL):
```json
{
  "timestamp": "2026-04-18T16:30:15Z",
  "violation_type": "secret_detected",
  "blocked": {
    "file_path": "test.py",
    "source": "file",
    "secret_type": "slack-bot-token",
    "reason": "Gitleaks detected sensitive information",
    "line_number": 2,
    "total_findings": 1
  },
  "context": {...}
}
```

**Note**: No actual secret value in violation log!

#### Layer 7: KNOWN LIMITATION - UserPromptSubmit Terminal Display

**THE LIMITATION (Claude Code Behavior)**:

When ai-guardian blocks prompts containing secrets using `decision: "block"` in JSON response, Claude Code displays the original prompt in the terminal error message.

**What IS protected:**
- ✅ Secret does NOT reach Claude's API (hook blocks before submission)
- ✅ Secret does NOT appear in conversation history/session
- ✅ Secret does NOT get sent to Anthropic servers
- ✅ Only metadata in our error message (type, file, line)

**What is NOT protected:**
- ❌ Secret visible in user's terminal when blocking occurs
- This is the trade-off for blocking secrets from reaching Claude

**Why we accept this limitation:**
- Preventing secrets from reaching Claude's API is MORE IMPORTANT than hiding from terminal
- The terminal leak is local only (user's screen)
- The alternative (allowing secrets to Claude) is worse
- This is a Claude Code design decision we cannot work around

**IMPACT**:
- ❌ Secrets in direct prompts ARE LEAKED when blocked
- ✅ Secrets in tool outputs (PostToolUse) are NOT leaked (uses JSON)
- ✅ Secrets in file reads (PreToolUse) are NOT leaked (different flow)

**WORKAROUNDS**:
1. **Rely on other detection layers**:
   - PreToolUse hook scans files before reading (blocks file path, not content)
   - PostToolUse hook scans tool outputs (uses JSON, no leak)
   
2. **User education**:
   - Don't paste secrets directly in prompts
   - Use environment variables, config files, or secure vaults

#### Layer 8: Secure File Cleanup

**Content File (Scanned File)**:
```python
# Secure cleanup: overwrite file before deletion
if os.path.exists(tmp_file_path):
    # Make file writable
    os.chmod(tmp_file_path, 0o600)
    
    # Overwrite with zeros to prevent recovery
    file_size = os.path.getsize(tmp_file_path)
    with open(tmp_file_path, 'wb') as f:
        f.write(b'\x00' * file_size)
        f.flush()
        os.fsync(f.fileno())
    
    # Delete the file
    os.unlink(tmp_file_path)
```

**Report File (Gitleaks JSON Output)** - Now securely cleaned up:
```python
# Securely clean up report file (contains Gitleaks findings)
# Even though --redact is used, we securely overwrite as defense in depth
if report_file and os.path.exists(report_file):
    # Overwrite with zeros before deletion
    file_size = os.path.getsize(report_file)
    with open(report_file, 'wb') as f:
        f.write(b'\x00' * file_size)
        f.flush()
        os.fsync(f.fileno())
    
    # Delete the file
    os.unlink(report_file)
```

**Why this matters**:
- Even though Gitleaks redacts secrets, defense in depth requires secure cleanup
- Prevents forensic recovery of temporary files
- Both content and report files are overwritten with zeros before deletion
- Uses `os.fsync()` to ensure writes are committed to disk

### Summary: What Is/Isn't Exposed

**Secret values are NEVER exposed in**:
- ❌ Error messages shown to users
- ❌ Log files (`~/.config/ai-guardian/ai-guardian.log`)
- ❌ Violation logs (`~/.config/ai-guardian/violations.jsonl`)
- ❌ Gitleaks stdout/stderr output
- ❌ Gitleaks JSON report (shows "REDACTED")
- ❌ Temporary files (securely overwritten before deletion)

**What IS exposed** (safe metadata):
- ✅ Secret type (e.g., "slack-bot-token", "aws-access-key")
- ✅ File path where secret was found
- ✅ Line number(s) in file
- ✅ Total count of secrets found

**Defense-in-depth layers**:
1. Gitleaks `--redact` flag
2. Don't extract secret values from Gitleaks output
3. Error messages show only metadata
4. Logs show only rule IDs
5. Sanitized stderr logging
6. Violation logs exclude secrets
7. Secure file cleanup (overwrite + delete)

### Best Practices for Developers

When modifying secret scanning code:

1. **Never log `first_finding.get('Match')` or `first_finding.get('Secret')`**
   - These fields contain "REDACTED" but should never be logged anyway

2. **Never include `result.stdout` or `result.stderr` in user-facing messages**
   - Only use for internal debugging, with sanitization

3. **Always use secure cleanup for temporary files containing secrets**
   - Overwrite with zeros before deletion
   - Use `os.fsync()` to ensure write is committed

4. **Test with real secrets to verify redaction**
   - Use actual secret formats (Slack tokens, AWS keys, etc.)
   - Verify secrets don't appear in output, logs, or files

5. **Document any new fields extracted from Gitleaks output**
   - Ensure they don't contain secret values
   - Update this document with security analysis

---

## Troubleshooting

### Secret scanning doesn't work

**Check:**
```bash
# 1. Is secret_scanning enabled?
cat ~/.config/ai-guardian/ai-guardian.json | jq .secret_scanning.enabled

# 2. Check which scanner engines are active (toml-patterns is built-in, no install needed)
ai-guardian scanner list

# 3. Check logs
tail -f ~/.config/ai-guardian/ai-guardian.log
```

**Note:** `toml-patterns` is always available and requires no external binary. If secret scanning reports no engines, ensure ai-guardian itself is installed correctly.

### Pattern server not being used

**Check:**
```bash
# 1. Is pattern_server configured?
cat ~/.config/ai-guardian/ai-guardian.json | jq .secret_scanning.pattern_server

# 2. Check authentication
cat ~/.config/rh-gitleaks/auth.jwt  # Your token file

# 3. Test pattern server manually
curl -H "Authorization: Bearer $(cat ~/.config/rh-gitleaks/auth.jwt)" \
  https://patterns.security.redhat.com/patterns/gitleaks/8.27.0

# 4. Check cache
ls -la ~/.cache/ai-guardian/patterns.toml
cat ~/.cache/ai-guardian/patterns.toml | head -20
```

### Secrets not detected

**Possible causes:**
1. Pattern server missing default patterns
2. Custom `.gitleaks.toml` doesn't include pattern
3. Secret format not recognized by Gitleaks

**Test manually:**
```bash
# Test with default Gitleaks patterns
echo "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" | gitleaks detect --no-git -v

# Test with your pattern server patterns
gitleaks detect --no-git -v --config ~/.cache/ai-guardian/patterns.toml
```

---

## Summary

### `secret_scanning` - The Scanner

- **Purpose:** Enable/disable scanning
- **Controls:** ON/OFF switch (always blocks when secrets found)
- **Scope:** Global across all hooks and files
- **Action:** Always blocks (no configurable action mode)

### `pattern_server` - The Pattern Source

- **Purpose:** Customize which secrets to detect
- **Controls:** Where patterns come from (enterprise vs defaults)
- **Scope:** Pattern definitions only

### They Work Together

```
secret_scanning.enabled → Should we scan?
    ↓ YES
pattern_server configured? → Which patterns?
    ↓ YES
Fetch patterns from server
    ↓
Scan content with those patterns
    ↓
Secret found?
    ↓ YES
BLOCKED (secrets always block)
```

---

## Related Documentation

- [HOOKS.md](HOOKS.md) - Why log mode doesn't show messages
- [CONSOLE.md](CONSOLE.md) - Using the Console to view violations
- [README.md](../README.md) - Configuration examples
- [CHANGELOG.md](../../CHANGELOG.md) - Feature history
- [Gitleaks --redact](https://github.com/gitleaks/gitleaks#redaction)
- [OWASP Secret Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)

---

**Last Updated:** 2026-04-19  
**Version:** 1.4.0-dev
