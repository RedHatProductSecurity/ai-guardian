# Pattern Server

AI Guardian can optionally fetch security patterns from a centralized pattern server, enabling enterprise-wide security policy management.

## What is Pattern Server?

**Pattern Server** is an optional feature that allows organizations to:
- 📡 **Centralize security patterns** - One source of truth for all detection rules
- 🔄 **Auto-update patterns** - New threats distributed automatically to all users
- 🏢 **Enforce corporate policies** - Organization-specific security rules
- 🎯 **Custom threat intelligence** - Industry-specific attack patterns

Instead of each user maintaining their own pattern lists, everyone gets the same up-to-date patterns from a central server.

---

## What It Manages

Pattern Server can provide patterns for all detection features:

| Detection Feature | Pattern Type | Example Patterns |
|-------------------|--------------|------------------|
| **Secret Scanning** | Secret regex patterns | API key formats, token patterns |
| **SSRF Protection** | Blocked IPs/domains | Internal networks, metadata endpoints |
| **Unicode Attacks** | Homoglyph mappings | Cyrillic/Greek lookalikes |
| **Config Scanner** | Exfiltration patterns | Credential theft commands |
| **Secret Redaction** | Masking rules | Which secrets to redact, how to mask |

---

## How It Works

### Without Pattern Server (Default)

```
Each AI Guardian installation uses hardcoded patterns:
  
User A: Hardcoded patterns v1.5.0
User B: Hardcoded patterns v1.5.0
User C: Hardcoded patterns v1.5.0
  ↓
New threat discovered!
  ↓
Users must wait for next AI Guardian release
```

### With Pattern Server (Enterprise)

```
All installations fetch from central server:

Pattern Server: Latest patterns (updated daily)
         ↓           ↓           ↓
    User A      User B      User C
         ↓           ↓           ↓
All users get new patterns automatically
```

---

## Benefits

### For Security Teams

✅ **Instant threat response**
- New attack pattern discovered → Update server → All users protected
- No waiting for software releases

✅ **Centralized control**
- Single place to manage all security rules
- Consistent policies across organization

✅ **Custom threat intelligence**
- Add industry-specific patterns
- Block organization-specific threats
- Internal security research integration

### For Users

✅ **Always up-to-date**
- Automatic pattern updates
- No manual configuration needed
- Latest threat protection

✅ **Consistent protection**
- Everyone uses same rules
- No configuration drift
- Compliance with corporate policies

---

## Configuration

Enable pattern server in your config:

```json
{
  "secret_redaction": {
    "pattern_server": {
      "enabled": true,
      "url": "https://patterns.corp.internal/api/v1/secrets",
      "cache_ttl": 3600,
      "fallback_to_defaults": true
    }
  }
}
```

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `enabled` | Enable pattern server | `false` |
| `url` | Pattern server API endpoint | - |
| `cache_ttl` | Cache duration in seconds | `3600` (1 hour) |
| `fallback_to_defaults` | Use hardcoded patterns if server unavailable | `true` |
| `sha256` | Required SHA-256 digest of the exact remote bundle | unset (remote content inactive) |
| `allow_untrusted_host` | Explicitly approve a non-official HTTPS host | `false` |

Remote bundles are accepted only after HTTPS endpoint approval and a matching
`sha256` pin. Bearer tokens are not sent to unapproved or unpinned endpoints.
Cached bundles are reused only when their recorded digest still matches the
configured pin. Operator diagnostics report the active source and verification
state without exposing credentials or pattern contents.

### Per-Feature Configuration

Each detection feature can have its own pattern server:

```json
{
  "secret_redaction": {
    "pattern_server": {
      "url": "https://patterns.corp.internal/api/v1/secrets"
    }
  },
  "ssrf_protection": {
    "pattern_server": {
      "url": "https://patterns.corp.internal/api/v1/ssrf"
    }
  },
  "config_file_scanning": {
    "pattern_server": {
      "url": "https://patterns.corp.internal/api/v1/exfil"
    }
  }
}
```

---

## Caching & Performance

### How Caching Works

```
1. AI Guardian starts
   ↓
2. Check local cache (valid for cache_ttl)
   ↓
3. If expired, fetch from server
   ↓
4. Store in cache
   ↓
5. Use patterns for detection
```

### Cache Behavior

| Scenario | What Happens |
|----------|--------------|
| **First run** | Fetches from server, caches locally |
| **Cache valid** | Uses cached patterns (fast) |
| **Cache expired** | Re-fetches from server, updates cache |
| **Server unreachable** | Uses cached patterns OR hardcoded defaults |
| **No cache + server down** | Falls back to hardcoded patterns |

**Performance:** Pattern fetching happens at startup (~100-500ms), not during detection.

---

## Fail-Safe Design

AI Guardian is designed to **fail safely** if pattern server is unavailable:

```
Pattern Server Down?
  ↓
Check Local Cache
  ↓ (expired or missing)
Fallback to Defaults (if enabled)
  ↓
Continue with hardcoded patterns
  ↓
✅ Protection still active (not blocked)
```

**You are always protected** - even if the pattern server goes offline.

---

## Use Cases

### Enterprise Deployment

**Scenario:** 500 developers across multiple teams

**Without Pattern Server:**
- ❌ Each developer configures AI Guardian individually
- ❌ Configuration drift (different patterns per team)
- ❌ Slow threat response (wait for releases)
- ❌ Manual updates required

**With Pattern Server:**
- ✅ Security team controls patterns centrally
- ✅ All developers get same protection
- ✅ New threats blocked instantly (update server)
- ✅ Zero manual updates needed

### Industry-Specific Patterns

**Example: Healthcare**
```json
{
  "secret_redaction": {
    "pattern_server": {
      "url": "https://hipaa-patterns.corp.internal/api/v1/secrets"
    }
  }
}
```

Pattern server provides:
- PHI (Protected Health Information) patterns
- Medical record number formats
- Healthcare-specific API keys
- HIPAA compliance rules

### Compliance Requirements

**Example: Financial Services**
- PCI DSS compliance patterns
- Credit card number detection
- Bank account formats
- Financial API credentials

**Example: Government**
- Classified information markers
- Agency-specific secret formats
- Clearance level indicators
- Government cloud endpoints

---

## Pattern Server API

Pattern server provides patterns via simple HTTP API:

### Example Response (Secrets)

```json
{
  "version": "2024.04.27",
  "patterns": [
    {
      "regex": "sk-proj-[A-Za-z0-9]{20,}",
      "strategy": "preserve_prefix_suffix",
      "secret_type": "OpenAI Project Key"
    },
    {
      "regex": "corp_api_key_[A-Za-z0-9]{32}",
      "strategy": "full_redact",
      "secret_type": "Corporate API Key"
    }
  ]
}
```

### Example Response (SSRF)

```json
{
  "version": "2024.04.27",
  "blocked_ip_ranges": [
    {"cidr": "10.0.0.0/8"},
    {"cidr": "192.168.0.0/16"}
  ],
  "blocked_domains": [
    {"domain": "metadata.google.internal"},
    {"domain": "*.corp.internal"}
  ]
}
```

---

## Authentication

### Default: Single Token for All Pattern Servers

By default, all pattern server sections use the same environment variable for authentication:

```bash
export AI_GUARDIAN_PATTERN_TOKEN="your-token"
```

This works when all pattern servers share the same credentials (the common case).

Each pattern server reads its auth config independently. If `token_env` is not specified in a section's `auth` block, it falls back to `AI_GUARDIAN_PATTERN_TOKEN`.

### Per-Section Auth for Multiple Servers

When different detection features use different pattern servers with different credentials, override `token_env` in each section:

```json
{
  "secret_scanning": {
    "pattern_server": {
      "url": "https://secrets-patterns.internal.com",
      "patterns_endpoint": "/patterns/gitleaks/8.27.0",
      "auth": {
        "method": "bearer",
        "token_env": "AI_GUARDIAN_SECRET_PATTERNS_TOKEN"
      }
    }
  },
  "ssrf_protection": {
    "pattern_server": {
      "url": "https://ssrf-patterns.internal.com",
      "patterns_endpoint": "/patterns/ssrf/v1",
      "auth": {
        "method": "bearer",
        "token_env": "AI_GUARDIAN_SSRF_PATTERNS_TOKEN"
      }
    }
  },
  "config_file_scanning": {
    "pattern_server": {
      "url": "https://exfil-patterns.internal.com",
      "patterns_endpoint": "/patterns/exfil/v1",
      "auth": {
        "method": "bearer",
        "token_env": "AI_GUARDIAN_EXFIL_PATTERNS_TOKEN"
      }
    }
  },
  "secret_redaction": {
    "pattern_server": {
      "url": "https://redaction-patterns.internal.com",
      "auth": {
        "method": "bearer",
        "token_env": "AI_GUARDIAN_REDACTION_PATTERNS_TOKEN"
      }
    }
  }
}
```

Then set each environment variable:

```bash
export AI_GUARDIAN_SECRET_PATTERNS_TOKEN="token-for-secrets-server"
export AI_GUARDIAN_SSRF_PATTERNS_TOKEN="token-for-ssrf-server"
export AI_GUARDIAN_EXFIL_PATTERNS_TOKEN="token-for-exfil-server"
export AI_GUARDIAN_REDACTION_PATTERNS_TOKEN="token-for-redaction-server"
```

### Auth Options

Each pattern server `auth` block supports:

| Option | Description | Default |
|--------|-------------|---------|
| `method` | Auth method | `"bearer"` |
| `token_env` | Env var containing the token | `"AI_GUARDIAN_PATTERN_TOKEN"` |
| `token_file` | File path containing the token | `"~/.config/ai-guardian/pattern-token"` |

**Token resolution order:**
1. Environment variable (`token_env`) — checked first
2. Token file (`token_file`) — used if env var is not set

**Using `token_file` instead of env vars:**

```json
{
  "secret_scanning": {
    "pattern_server": {
      "url": "https://secrets-patterns.internal.com",
      "auth": {
        "method": "bearer",
        "token_file": "~/.config/ai-guardian/secret-patterns-token"
      }
    }
  }
}
```

Token files are read at runtime. Permissions are restricted to `0600` when written by AI Guardian.

### Which Sections Support Pattern Server?

| Config Section | Pattern Type | Default Token Env |
|----------------|-------------|-------------------|
| `secret_scanning.pattern_server` | Secret detection rules | `AI_GUARDIAN_PATTERN_TOKEN` |
| `secret_redaction.pattern_server` | Secret redaction/masking rules | `AI_GUARDIAN_PATTERN_TOKEN` |
| `ssrf_protection.pattern_server` | Blocked IPs/domains | `AI_GUARDIAN_PATTERN_TOKEN` |
| `config_file_scanning.pattern_server` | Exfiltration patterns | `AI_GUARDIAN_PATTERN_TOKEN` |

All default to `AI_GUARDIAN_PATTERN_TOKEN` unless overridden with `token_env`.

---

## Security Considerations

### Server Authentication

**Recommended:** Use authentication for pattern server:

```json
{
  "pattern_server": {
    "url": "https://patterns.corp.internal/api/v1/secrets",
    "auth": {
      "method": "bearer",
      "token_env": "PATTERN_SERVER_TOKEN"
    }
  }
}
```

AI Guardian sends:
```
GET /api/v1/secrets
Authorization: Bearer <token from PATTERN_SERVER_TOKEN env var>
```

### Pattern Validation

All patterns from the server are validated before use:
- ✅ Regex syntax validation (prevents ReDoS)
- ✅ Pattern complexity analysis
- ✅ Malformed pattern rejection
- ✅ Safe fallback if validation fails

**Protection:** Malicious or broken patterns won't crash AI Guardian.

### Supply Chain Security

**Risk:** Compromised pattern server could weaken detection

**Mitigations:**
1. **TLS/HTTPS required** - Encrypted transport
2. **Endpoint approval** - Official host or explicit reviewed host approval
3. **SHA-256 pinning** - Remote content must match the configured digest
4. **Pattern validation** - Regex safety checks
5. **Immutable secret baseline** - Remote replace mode cannot remove bundled rules
6. **Fallback to defaults** - Unverified or unavailable content stays inactive

---

## See Also

- [Configuration Guide](CONFIGURATION.md) - Full configuration reference
- [Secret Redaction](security/SECRET_REDACTION.md) - Secret masking feature
- [SSRF Protection](security/SSRF_PROTECTION.md) - Network attack prevention
- [Violation Logging](VIOLATION_LOGGING.md) - Audit trail documentation

---

## Summary

**Pattern Server** provides:

🎯 **Centralized management** - One source of truth for all security patterns  
🎯 **Automatic updates** - New threats blocked instantly across organization  
🎯 **Custom patterns** - Industry-specific and corporate security rules  
🎯 **Fail-safe design** - Protection continues even if server is down  
🎯 **Enterprise compliance** - Meet regulatory requirements easily

**Optional feature** for organizations that need centralized security policy management.

---

## Version History

- **v1.5.0** - Initial pattern server support (secrets, SSRF, Unicode, config scanner, redaction)
- **v1.5.1** - Added authentication and cache improvements
- **v1.6.0** - Enhanced validation and audit logging
