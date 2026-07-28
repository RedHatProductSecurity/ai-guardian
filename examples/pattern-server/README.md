# Pattern Server Example Files

This directory contains example TOML pattern files for AI Guardian's pattern server feature.

## Overview

Pattern server support (NEW in v1.8.0) enables enterprise security teams to centrally manage detection patterns without requiring code releases. Patterns are fetched from a pattern server, cached locally, and fall back to hardcoded defaults if unavailable.

## Three-Tier Pattern System

1. **Tier 1: IMMUTABLE** - Core security baselines that cannot be disabled
2. **Tier 2: OVERRIDABLE** - Pattern server can replace or modify these
3. **Tier 3: ADDITIONS** - Local config additions (always additive)

## Example Files

### ssrf-patterns.toml
**Feature**: SSRF Protection  
**Endpoint**: `/patterns/ssrf/v1`  
**Use Case**: Override RFC 1918 private ranges while keeping cloud metadata endpoints immutable

- **Immutable**: Cloud metadata endpoints (169.254.169.254, metadata.google.internal), dangerous URL schemes (file://, gopher://)
- **Overridable**: RFC 1918 ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- **Example**: Allow Docker access (172.17.0.0/16) by omitting 172.16.0.0/12 from pattern list

### secrets-patterns.toml
**Feature**: Secret Redaction  
**Endpoint**: `/patterns/secrets/v1`  
**Use Case**: Deploy new secret formats in <24h

- **Immutable**: None (all patterns enterprise-customizable)
- **Overridable**: All 35+ secret types
- **Modes**:
  - `override_mode = "extend"`: Add enterprise patterns to built-in patterns
  - `override_mode = "replace"`: Use only enterprise patterns (ignore built-ins)

### unicode-patterns.toml
**Feature**: Unicode Attack Detection  
**Endpoint**: `/patterns/unicode/v1`  
**Use Case**: Update homoglyph patterns as new scripts emerge

- **Immutable**: Zero-width chars (9 types), bidi overrides, tag characters
- **Overridable**: Homoglyph patterns (80+ character pairs)
- **Example**: Add newly discovered Coptic/Armenian script confusables

### config-exfil-patterns.toml
**Feature**: Config File Scanner  
**Endpoint**: `/patterns/config-exfil/v1`  
**Use Case**: Add organization-specific exfiltration patterns

- **Immutable**: Core patterns (env|curl, aws s3, gcp storage)
- **Overridable**: Additional exfiltration patterns
- **Examples**: Azure Blob, Slack webhooks, Discord webhooks, reverse shells

## Configuration

### 1. Set up Pattern Server

Add pattern_server configuration to `ai-guardian.json`:

```json
{
  "ssrf_protection": {
    "pattern_server": {
      "url": "https://patterns.security.company.com",
      "patterns_endpoint": "/patterns/ssrf/v1",
      "allow_override": true,
      "auth": {
        "token_env": "AI_GUARDIAN_PATTERN_TOKEN",
        "token_file": "~/.config/ai-guardian/pattern-token"
      },
      "cache": {
        "path": "~/.cache/ai-guardian/ssrf-patterns.toml",
        "refresh_interval_hours": 12,
        "expire_after_hours": 168
      }
    }
  },
  "secret_redaction": {
    "pattern_server": {
      "url": "https://patterns.security.company.com",
      "patterns_endpoint": "/patterns/secrets/v1"
    }
  }
}
```

### 2. Deploy Pattern Files

Host these TOML files at the configured endpoints:

```
https://patterns.security.company.com/patterns/ssrf/v1
https://patterns.security.company.com/patterns/unicode/v1
https://patterns.security.company.com/patterns/config-exfil/v1
https://patterns.security.company.com/patterns/secrets/v1
```

### 3. Authentication (Optional)

If your pattern server requires authentication:

```bash
# Environment variable
export AI_GUARDIAN_PATTERN_TOKEN="your-bearer-token"

# Or save to file
echo "your-bearer-token" > ~/.config/ai-guardian/pattern-token
chmod 600 ~/.config/ai-guardian/pattern-token
```

## Fallback Chain

Pattern server implements a robust fallback mechanism:

```
1. Pattern Server (network fetch)
   ├─ SUCCESS → Cache + Use
   └─ FAIL → Try cache...

2. Cached Patterns (local file)
   ├─ EXISTS + NOT EXPIRED (<168h) → Use cache
   └─ EXPIRED/MISSING → Fallback...

3. Hardcoded Defaults (Python code)
   └─ ALWAYS AVAILABLE → Use defaults
```

**Result**: AI Guardian always works, even when pattern server is unavailable.

## Pattern File Format

### TOML Structure

```toml
[metadata]
version = "1.0.0"
updated_at = 2026-04-22T10:00:00Z
override_mode = "replace"  # or "extend"
source = "patterns.security.company.com"
description = "Pattern description"

[[patterns]]  # or [[blocked_ip_ranges]], [[homoglyph_patterns]]
# Pattern-specific fields
```

### Why TOML?

- ✅ Native comment support (document WHY patterns exist)
- ✅ More human-readable than JSON
- ✅ Multiline strings (no escaping needed)
- ✅ Compatible with existing Gitleaks pattern server

## Override Modes

### Replace Mode
Pattern server **replaces** hardcoded defaults:

```toml
[metadata]
override_mode = "replace"

# Only these patterns will be used (immutable patterns still enforced)
```

**Use when**: You want complete control over patterns

### Extend Mode
Pattern server **adds to** hardcoded defaults:

```toml
[metadata]
override_mode = "extend"

# These patterns are added to built-in patterns
```

**Use when**: You want to add organization-specific patterns while keeping defaults

## Best Practices

1. **Document with comments** - Explain WHY each pattern exists
2. **Add metadata** - Use `added`, `rationale` fields for tracking
3. **Version control** - Increment `version` and `updated_at` when changing
4. **Test before deploying** - Validate patterns don't create false positives
5. **Monitor cache** - Check `~/.cache/ai-guardian/` for cached patterns
6. **Audit changes** - Track who made changes and when

## Cache Management

### View cached patterns:
```bash
cat ~/.cache/ai-guardian/ssrf-patterns.toml
cat ~/.cache/ai-guardian/secrets-patterns.toml
```

### Force refresh:
```bash
# Delete cache to force re-fetch
rm ~/.cache/ai-guardian/*-patterns.toml

# Next run will fetch from server
```

### Cache settings:
- `refresh_interval_hours`: How often to check server for updates (default: 12h)
- `expire_after_hours`: When to fall back to defaults if server unavailable (default: 168h = 7 days)

## Pattern Server API

### Endpoints

```
GET /patterns/ssrf/v1          → TOML file with SSRF patterns
GET /patterns/unicode/v1       → TOML file with Unicode patterns
GET /patterns/config-exfil/v1  → TOML file with config scanner patterns
GET /patterns/secrets/v1       → TOML file with secret redaction patterns
```

### Authentication

Pattern server supports Bearer token authentication:

```
GET /patterns/ssrf/v1
Authorization: Bearer <token>
```

### Response Format

HTTP 200 OK with TOML content:
```toml
[metadata]
version = "1.0.0"
...
```

### Error Handling

- **401 Unauthorized**: Invalid/missing auth token
- **403 Forbidden**: Token valid but lacks permission
- **404 Not Found**: Pattern type doesn't exist
- **500 Server Error**: Server error (AI Guardian falls back to cache/defaults)

## Deployment Example

### Simple HTTP Server (Testing)

```python
# pattern_server.py
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

class PatternHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/patterns/ssrf/v1':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            content = Path('ssrf-patterns.toml').read_text()
            self.wfile.write(content.encode())
        else:
            self.send_error(404)

if __name__ == '__main__':
    server = HTTPServer(('localhost', 8000), PatternHandler)
    print('Pattern server running on http://localhost:8000')
    server.serve_forever()
```

### Production Deployment

For production, use:
- Nginx/Apache to serve static TOML files
- AWS S3 + CloudFront with authentication
- Internal API gateway with auth middleware
- GCS buckets with IAM authentication

## Testing

### 1. Test pattern file validity:
```bash
# Install tomli (Python <3.11)
pip install tomli

# Validate TOML syntax
python -c "import tomllib; print(tomllib.load(open('ssrf-patterns.toml', 'rb')))"
```

### 2. Test with AI Guardian:
```json
// ai-guardian.json
{
  "ssrf_protection": {
    "pattern_server": {
      "url": "http://localhost:8000"
    }
  }
}
```

### 3. Verify fallback:
```bash
# Stop pattern server
# AI Guardian should still work (uses cache/defaults)
```

## Troubleshooting

### Pattern server not loading

Check logs for:
```
INFO: SSRF Protection: Loading patterns via pattern server
INFO: Loaded patterns from pattern server/cache/defaults
```

### Authentication errors

```
ERROR: Pattern server authentication failed (401 Unauthorized)
```
→ Check `AI_GUARDIAN_PATTERN_TOKEN` or token file

### Cache issues

```bash
# Clear cache and retry
rm -rf ~/.cache/ai-guardian/*.toml
```

### Validation errors

```
WARNING: Invalid IP range in SSRF config: <range>
```
→ Check TOML file format and CIDR notation

## More Information

- **Implementation Plan**: See `/PATTERN_SERVER_IMPLEMENTATION_PLAN.md`
- **Source Code**: See `/src/ai_guardian/pattern_loader.py`
- **Tests**: See `/tests/test_pattern_*`
- **Schema**: See `/src/ai_guardian/schemas/ai-guardian-config.schema.json`

## Questions?

For issues or questions:
- GitHub Issues: https://github.com/RedHatProductSecurity/ai-guardian/issues
- Tag your issue with `pattern-server` label
