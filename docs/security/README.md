# Security Features Documentation

This directory contains detailed documentation for AI Guardian's security detection and protection features.

## Available Documentation

### Detection & Prevention

| Feature | Description | File |
|---------|-------------|------|
| **Prompt Injection** | Detect and block jailbreak attempts and instruction override attacks | [PROMPT_INJECTION.md](PROMPT_INJECTION.md) |
| **SSRF Protection** | Detect and block Server-Side Request Forgery attempts in tool calls | [SSRF_PROTECTION.md](SSRF_PROTECTION.md) |
| **Unicode Attacks** | Detect invisible characters, homoglyphs, and bidirectional text attacks | [UNICODE_ATTACKS.md](UNICODE_ATTACKS.md) |
| **Context Poisoning** | Detect persistent malicious instructions injected into conversation context (LLM03) | [CONTEXT_POISONING.md](CONTEXT_POISONING.md) |
| **Credential Exfiltration** | Scan config files for credential theft commands | [CREDENTIAL_EXFILTRATION.md](CREDENTIAL_EXFILTRATION.md) |
| **Command Credential Scanning** | Block literal credentials in supported command arguments before execution | [COMMAND_CREDENTIAL_SCANNING.md](COMMAND_CREDENTIAL_SCANNING.md) |
| **HTTP Request Credential Scanning** | Block hard-coded credentials in supported Python, JavaScript, and TypeScript HTTP request source before file writes | [HTTP_REQUEST_CREDENTIAL_SCANNING.md](HTTP_REQUEST_CREDENTIAL_SCANNING.md) |
| **Directory Rules** | Control which files and directories AI can access | [DIRECTORY_RULES.md](DIRECTORY_RULES.md) |

### Image & Media Scanning

| Feature | Description | File |
|---------|-------------|------|
| **Image Scanning (OCR)** | OCR-based secret/PII detection in images, IDE limitations | [IMAGE_SCANNING.md](IMAGE_SCANNING.md) |

### Secret Management

| Feature | Description | File |
|---------|-------------|------|
| **Secret Scanning** | Prevent secrets from being committed to version control | [SECRET_SCANNING.md](SECRET_SCANNING.md) |
| **Secret Redaction** | Redact secrets from tool outputs while preserving context | [SECRET_REDACTION.md](SECRET_REDACTION.md) |

## Quick Reference

### Prompt Injection Detection
Blocks jailbreak attempts and instruction override:
- Instruction override ("ignore previous instructions")
- Mode manipulation ("enable developer mode")
- Information exfiltration ("reveal your system prompt")
- Constraint bypassing ("disable safety filters")
- Malware generation ("create ransomware")

**Use case:** Prevent AI from being manipulated into bypassing safety guidelines

---

### SSRF Protection
Blocks dangerous network requests to:
- Private IP ranges (10.0.0.0/8, 192.168.0.0/16, etc.)
- Cloud metadata endpoints (169.254.169.254, metadata.google.internal)
- Dangerous URL schemes (file://, gopher://, ftp://)

**Use case:** Prevent AI from accessing internal infrastructure or cloud credentials

---

### Unicode Attacks
Detects 4 types of Unicode-based attacks:
- **Zero-width characters** (9 types) - Invisible characters
- **Bidirectional override** (2 types) - Text reversal
- **Tag characters** - Hidden data encoding
- **Homoglyphs** (80+ pairs) - Look-alike characters

**Use case:** Detect hidden malicious commands and character substitution attacks

---

### Credential Exfiltration
Scans AI config files (CLAUDE.md, .cursorrules, etc.) for:
- `curl`/`wget` with environment variables
- `env | curl` command chains
- File exfiltration (`cat ~/.ssh/id_rsa | curl`)
- Cloud storage uploads (AWS S3, GCP Storage)

**Use case:** Prevent persistent credential theft across all AI sessions

---

### Secret Scanning
Prevents 35+ secret types from being committed:
- API keys (OpenAI, GitHub, Anthropic, AWS, Google, etc.)
- Private keys (RSA, SSH, TLS)
- Database credentials
- Authentication tokens

**Use case:** Stop secrets from entering version control in the first place

---

### Secret Redaction
Redacts secrets from tool outputs using 6 masking strategies:
- Preserve prefix/suffix (API keys, tokens)
- Full redaction (highly sensitive)
- Environment variable masking
- JSON field redaction
- Connection string masking
- Context-aware redaction

**Use case:** Allow work to continue while protecting credentials in outputs

---

## Security Layers

AI Guardian provides **defense in depth** through multiple security layers:

```
┌─────────────────────────────────────────────┐
│ Layer 1: Input Validation                   │
│ - Unicode Attack Detection                  │
│ - SSRF Pattern Detection                    │
│ - Config File Scanning                      │
└─────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────┐
│ Layer 2: Prevention                         │
│ - Block malicious commands                  │
│ - Prevent secret commits                    │
│ - Stop network attacks                      │
└─────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────┐
│ Layer 3: Output Sanitization                │
│ - Secret Redaction                          │
│ - Remove credentials from outputs           │
└─────────────────────────────────────────────┘
```

Each layer catches what previous layers might miss.

---

## Configuration

All security features are configured in `~/.config/ai-guardian/ai-guardian.json`:

```json
{
  "ssrf_protection": {
    "enabled": true,
    "action": "block"
  },
  "prompt_injection": {
    "enabled": true,
    "action": "block",
    "unicode_detection": {
      "enabled": true
    }
  },
  "config_file_scanning": {
    "enabled": true,
    "action": "block"
  },
  "secret_redaction": {
    "enabled": true,
    "action": "warn"
  }
}
```

See individual feature documentation for detailed configuration options.

---

## Common Action Modes

Most features support these action modes:

| Mode | Behavior | Use Case |
|------|----------|----------|
| `block` | Prevents operation | Production, high-security environments |
| `warn` | Shows warning, allows operation | Development, lower risk |
| `log-only` | Silent logging | Monitoring, analysis |

---

## Getting Started

1. **Start with defaults** - All features enabled with sensible defaults
2. **Review detections** - Check logs for any warnings
3. **Tune configuration** - Adjust for your environment
4. **Enable blocking** - Move from `warn` to `block` mode for production

---

## See Also

- [Configuration Guide](../CONFIGURATION.md) - Full configuration reference
- [Hooks Documentation](../HOOKS.md) - Hook system and customization
- [Console Guide](../CONSOLE.md) - Interactive console for configuration

---

## Version History

Security features introduced across versions:
- **v1.5.0** - SSRF Protection, Unicode Attack Detection, Secret Redaction, Config File Scanning, Pattern Server Support
- **v1.6.0** - Multi-engine scanner support, enhanced patterns
- **v1.7.0** - Execution strategies, parallel engine execution, image scanning
