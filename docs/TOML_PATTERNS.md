# TOML Pattern Engine

AI Guardian ships with 267 built-in detection patterns stored in TOML files. These patterns are loaded automatically at startup — **no configuration required**. All detection features (secret redaction, PII scanning, prompt injection, unicode attacks, SSRF, config exfiltration) use the bundled TOML patterns as their primary source.

## Zero-Config Usage

The TOML patterns work out of the box. All detection modules load them automatically:
- **Secret redaction** (PostToolUse) — loads `secrets.toml`
- **PII detection** — loads `pii.toml`
- **Prompt injection** — loads `prompt-injection.toml`
- **Unicode attacks** — loads `unicode.toml`
- **Config exfiltration** — loads `config-exfil.toml`
- **SSRF protection** — loads `ssrf.toml`

## Scanner SDK Engine (Optional)

For the secret scanning PreToolUse pipeline, `toml-patterns` is also available as a Scanner SDK engine. This is useful if you want to run it instead of (or alongside) gitleaks:

```json
{
  "secret_scanning": {
    "engines": ["toml-patterns"]
  }
}
```

Or use alongside external scanners:

```json
{
  "secret_scanning": {
    "engines": ["toml-patterns", "gitleaks"]
  }
}
```

## Bundled Pattern Files

AI Guardian ships with 267 pre-compiled rules across 6 categories:

| File | Category | Rules | Description |
|------|----------|-------|-------------|
| `secrets.toml` | Secret detection | 44 | API keys, tokens, credentials, connection strings |
| `pii.toml` | PII detection | 13 | SSN, credit cards, phone numbers, email, passports |
| `prompt-injection.toml` | Prompt injection | 73 | Jailbreaks, instruction override, exfiltration |
| `unicode.toml` | Unicode attacks | 107 | Homoglyphs, zero-width chars, bidi overrides |
| `config-exfil.toml` | Config exfiltration | 8 | Credential theft via curl, wget, aws s3 |
| `ssrf.toml` | SSRF protection | 25 | Private/reserved IPs, cloud metadata, dangerous schemes |

## Match Types

TOML rules support five match types:

| Type | Use Case | Example |
|------|----------|---------|
| `regex` | Secrets, PII, prompt injection | `regex = '''(sk-[A-Za-z0-9]{20,})'''` |
| `literal` | Homoglyph character mappings | `source = "а"`, `target = "a"` |
| `cidr` | SSRF IP ranges | `cidr = "10.0.0.0/8"` |
| `range` | Unicode codepoint ranges | `start = 917504`, `end = 917631` |
| `glob` | File ignore patterns | `glob = "**/node_modules/**"` |

## TOML Rule Format

```toml
[[rules]]
id = "openai-api-key"
match_type = "regex"
regex = '''(sk-[A-Za-z0-9]{20,})'''
redaction_strategy = "preserve_prefix_suffix"
description = "OpenAI API Key"
keywords = ["sk-"]
```

### Common Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique rule identifier |
| `match_type` | Yes | One of: regex, literal, cidr, range, glob |
| `description` | No | Human-readable description |
| `tier` | No | `immutable` or `overridable` (for pattern server merge) |
| `redaction_strategy` | No | How to mask matched text (secrets/PII only) |
| `validation` | No | Post-match validator: `luhn` or `iban` |
| `keywords` | No | Keyword pre-filter — rule only runs if content contains a keyword |
| `entropy` | No | Minimum Shannon entropy for matched text (rejects low-entropy matches) |
| `pii_type` | No | PII category for `scan_pii.types` filtering |
| `group` | No | Confidence group for prompt injection rules |
| `skip_file_types` | No | Array of file extensions to skip for this rule (e.g., `[".py", ".go"]`). The scanner executor skips the rule entirely when the scanned file matches any listed extension. |
| `token_prefixes` | No | Array of known token prefixes for prefix-based detection (e.g., `["sk-or-", "hvs.", "AIza"]`). Used for fast prefix matching separate from keyword pre-filtering. |

## Pattern Servers

Each violation type can load patterns from one or more remote servers. Servers are configured per section and support different TOML formats.

### Secret Scanning

```json
{
  "secret_scanning": {
    "pattern_server": {
      "url": "https://patterns.company.com/secrets",
      "auth": { "token_env": "PATTERN_TOKEN" }
    }
  }
}
```

### PII Detection (v1.9.0+)

PII patterns support the same pattern server architecture. The server must return a TOML file with `[[rules]]` in ai-guardian native format (with `pii_type` fields).

```json
{
  "scan_pii": {
    "pattern_server": {
      "url": "https://pii-patterns.company.com",
      "patterns_endpoint": "/patterns/pii/v1",
      "auth": { "method": "bearer", "token_env": "PII_PATTERNS_TOKEN" },
      "cache": { "refresh_interval_hours": 168, "expire_after_hours": 720 }
    }
  }
}
```

**Server response format** — the endpoint must return a TOML file with `[[rules]]`. Each rule needs `id`, `match_type`, `regex`, `pii_type`, and optionally `redaction_strategy` and `validation`:

```toml
# Example PII pattern server response
# Extends bundled pii.toml with locale-specific patterns

[[rules]]
id = "pii-french-phone"
match_type = "regex"
description = "French phone number"
regex = '''(?:(?:\+33|0033|0)\s?[1-9])(?:[\s.-]?\d{2}){4}'''
redaction_strategy = "full_redact"
pii_type = "phone"

[[rules]]
id = "pii-german-iban"
match_type = "regex"
description = "German IBAN"
regex = '''\bDE\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}\b'''
redaction_strategy = "iban"
pii_type = "iban"
validation = "iban"

[[rules]]
id = "pii-french-name-context"
match_type = "regex"
description = "French contextual name pattern"
regex = '''(?i)(?:je m'appelle|mon nom est|prénom|nom)\s*:?\s*([A-ZÀ-Ö][a-zà-ö]+)'''
redaction_strategy = "full_redact"
pii_type = "person"
re2_compat = false
```

**Key fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier — matching `id` overrides the bundled default |
| `match_type` | Yes | Must be `regex` for PII patterns |
| `regex` | Yes | Python regex pattern (use triple-quotes for readability) |
| `pii_type` | Yes | Category for `scan_pii.pii_types` filtering |
| `redaction_strategy` | No | `full_redact` (default), `credit_card`, `pii_email`, `iban`, `canada_sin` |
| `validation` | No | Post-match validator: `credit_card` (Luhn + IIN) or `iban` (mod-97) |
| `re2_compat` | No | Set `false` for patterns using lookbehinds or other Python-only features |

**Merge strategy**: Server rules with matching `id` override bundled defaults; new rules are appended. Set `metadata.override_mode` to `"replace"` in the server response to replace all defaults instead of extending.

**Note**: No public PII pattern servers exist today. Projects like [PrivAiTe](https://github.com/crp4222/PrivAiTe) provide contextual PII patterns in YAML format — these could be converted to the TOML format above and served via a custom endpoint, but PrivAiTe itself is not a pattern server. [privaite-bench](https://github.com/crp4222/privaite-bench) provides 75 test documents across 5 languages that could be used to validate detection quality.

### Supported Formats

| Format | Description |
|--------|-------------|
| `ai-guardian` | Native format (same as bundled TOML files) |
| `gitleaks` | Gitleaks TOML format (Go RE2 regex, auto-converted) |

The existing singular `pattern_server` key continues to work (treated as a single-entry array with `gitleaks` format).

## False Positive Reduction

Three built-in mechanisms reduce false positives in secret detection (v1.12.0+):

### Keyword Pre-filter

TOML rules can declare `keywords` — strings that must appear in the content for the rule to fire. If no keyword is found, the regex is skipped entirely. This improves performance and prevents spurious matches.

```toml
[[rules]]
id = "openai-api-key"
regex = '''(sk-[A-Za-z0-9]{20,})'''
keywords = ["sk-"]  # Only run regex if "sk-" appears in content
```

Keyword matching is case-insensitive. Rules without `keywords` run against all content.

### Entropy Filtering

Shannon entropy measures the randomness of a string. Real API keys and tokens are generated with high entropy (cryptographically random), while placeholders and test values have low entropy.

| Entropy | Meaning | Example |
|---------|---------|---------|
| 0.0 | All identical characters | `XXXXXXXXXXXXXXXXXXXX` |
| ~1.0 | Two characters, equal frequency | `abababababababababab` |
| ~3.3 | Lowercase alphabet, uniform | `abcdefghijklmnopqrst` |
| ~4.7 | Full alphanumeric, uniform | `aB3kQ9xLm7Zy2pR4wE6t` |
| ~5.2+ | Alphanumeric + special chars | `k#9Lm!xQ2@pR$w7&zN5` |

**Per-rule threshold** — set `entropy` in the TOML rule to reject low-entropy matches:

```toml
[[rules]]
id = "generic-api-key"
regex = '''(?i)api[_-]?key\s*[:=]\s*['"]?([A-Za-z0-9]{20,})['"]?'''
entropy = 3.0  # Reject matches below 3.0 bits/char
```

**Global threshold** — set `min_entropy` in `ai-guardian.json` to apply to all secret rules:

```json
{
  "secret_scanning": {
    "min_entropy": 3.0
  }
}
```

Default: `3.0`. Per-rule `entropy` fields in TOML rules are checked first (in the pattern cache). The global `min_entropy` is checked afterward (in the scanner). Both must pass for a finding to survive. Set to `null` to disable the global check.

### Stopwords

Stopwords are common placeholder words found in test values, documentation examples, and template code. When a matched secret contains a stopword (case-insensitive substring match), the finding is suppressed.

**Bundled stopwords** are always active and include:
`example`, `test`, `sample`, `placeholder`, `dummy`, `fake`, `mock`, `changeme`, `replace`, `insert`, `your`, `todo`, `fixme`, `temp`, `demo`, `default`, `undefined`, `REPLACE_ME`, `YOUR_API_KEY`, `YOUR_SECRET`, `YOUR_TOKEN`, and more.

**User-configured stopwords** are merged with (never replacing) the bundled list:

```json
{
  "secret_scanning": {
    "stopwords": ["mycompany_test", "staging_key"]
  }
}
```

Minimum word length: 3 characters. Words shorter than 3 characters are silently ignored.

Stopwords only filter **secret** findings — PII findings are never affected by stopwords.

### Configuration via Console

Both the TUI console (`ai-guardian console`) and the Web Console include a **False Positive Filtering** section where you can:
- Set or disable the global minimum entropy threshold
- View the bundled stopwords count
- Add or remove user stopwords

## How It Works

1. **Load**: TOML files are parsed at startup (or on config reload)
2. **Compile**: All patterns are compiled into Python objects (regex, IP networks, dict lookups)
3. **Cache**: Compiled matchers are held in memory via `PatternCache`
4. **Scan**: Each hook call uses the pre-compiled cache — no parsing or compilation per request

The same compiled cache serves detection (PreToolUse), redaction (PostToolUse), and prompt scanning (UserPromptSubmit).

## RE2 Compatibility

Patterns are validated for Go RE2 compatibility at load time. Patterns using Python-only regex features are rejected with a warning:

- `\p{L}` (Unicode property escapes) — not supported in RE2
- `(?<=...)` (lookbehinds) — not supported in RE2
- `(?>...)` (atomic groups) — not supported in RE2

Rules can opt out of RE2 validation with `re2_compat = false` (used by some PII patterns that require lookbehinds).

## Performance

| Metric | toml-patterns | External scanner (gitleaks) |
|--------|---------------|----------------------------|
| Scan latency | ~1-5ms | ~50-100ms |
| Binary required | No | Yes |
| Startup cost | One-time TOML parse + compile | None per scan |
| Memory | Compiled regex cache | None |

## Relationship to Other Engines

The `toml-patterns` engine is **additive** — it does not replace gitleaks or betterleaks:

- **gitleaks**: Subprocess-based, uses its own pattern server, unchanged
- **betterleaks**: Subprocess-based, uses built-in rules, unchanged
- **toml-patterns**: In-process Python, uses bundled TOML + optional pattern servers

All engines can be used together via the `engines` list. The scanning strategy (`first-match`, `any-match`, `consensus`) determines how results are combined.
