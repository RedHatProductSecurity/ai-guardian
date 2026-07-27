# Violation Logging

AI Guardian automatically logs all blocked operations in JSON format, providing a complete audit trail for security review and compliance.

## What is Violation Logging?

**Violation Logging** automatically records when AI Guardian blocks an operation:
- 📝 **Complete audit trail** - Every blocked action is logged
- 🔍 **Security insights** - Understand attack patterns
- ✅ **Compliance proof** - Evidence of security controls
- 🐛 **Debug assistance** - Troubleshoot false positives

All logs use **JSONL format** (JSON Lines) - one JSON object per line for easy parsing and streaming.

> **Note:** SARIF format is available for secret scanning results via `ai-guardian scan --sarif-output`.

---

## What Gets Logged

Every time AI Guardian blocks something, it creates a log entry:

| Violation Type | What Triggered It | Log Details |
|----------------|-------------------|-------------|
| **Tool Permission** | Blocked command execution | Command, tool name, policy rule |
| **Directory Blocking** | Restricted path access | File path, requested operation |
| **Secret Detected** | Secret found in commit/file | Secret type, file location, line/column number |
| **Secret Redaction** | Secret masked in output | Secret type, masking strategy |
| **Prompt Injection** | Malicious prompt detected | Pattern matched, confidence score |
| **SSRF Protection** | Dangerous network request | URL, reason (private IP, metadata, etc.) |
| **Config File Threat** | Exfiltration in config file | Pattern, file, line/column number |
| **Unicode Attack** | Hidden characters detected | Character type, line/column position, Unicode code point |

---

## Log File Location

Logs are stored in your AI Guardian state directory:

```
~/.local/state/ai-guardian/violations.jsonl
```

**Format:** JSONL (one JSON object per line)

**Retention:** Last 1000 entries (configurable), 30 days max (configurable)

---

## Log Format

Each violation is logged as a single JSON object per line (JSONL format).

### Example Log Entry (Blocked Command)

```json
{
  "timestamp": "2024-04-27T08:30:15Z",
  "violation_type": "tool_permission",
  "severity": "warning",
  "blocked": {
    "tool": "Bash",
    "command": "rm -rf /tmp/*",
    "reason": "Destructive command pattern"
  },
  "context": {
    "project_path": "/home/user/projects/myapp",
    "ide_type": "vscode",
    "tool_name": "Bash",
    "source": "PreToolUse",
    "file_path": null
  },
  "suggestion": {
    "action": "add_allow_rule",
    "pattern": "rm -rf /tmp/myapp-cache/*"
  },
  "resolved": false,
  "resolved_at": null,
  "resolved_action": null
}
```

### Example Log Entry (Secret Detected)

```json
{
  "timestamp": "2024-04-27T08:35:42Z",
  "violation_type": "secret_detected",
  "severity": "high",
  "blocked": {
    "secret_type": "GitHub Personal Token",
    "file": "config/settings.py",
    "line": 42,
    "column": 15,
    "scanner": "gitleaks"
  },
  "context": {
    "project_path": "/home/user/projects/webapp",
    "git_branch": "feature/auth",
    "tool_name": "Write",
    "source": "PostToolUse",
    "file_path": "config/settings.py"
  },
  "suggestion": {
    "action": "use_environment_variable",
    "example": "GITHUB_TOKEN=ghp_... in .env"
  },
  "resolved": false,
  "resolved_at": null,
  "resolved_action": null
}
```

### Example Log Entry (Directory Blocked)

```json
{
  "timestamp": "2024-04-27T08:40:10Z",
  "violation_type": "directory_blocking",
  "severity": "warning",
  "blocked": {
    "file": "/home/user/.ssh/id_rsa",
    "operation": "read",
    "pattern": "~/.ssh/*"
  },
  "context": {
    "tool": "Read",
    "project_path": "/home/user/projects",
    "tool_name": "Read",
    "source": "PreToolUse",
    "file_path": "/home/user/.ssh/id_rsa"
  },
  "suggestion": {
    "action": "use_safe_location",
    "message": "SSH keys should not be accessed"
  },
  "resolved": false,
  "resolved_at": null,
  "resolved_action": null
}
```

---

## Configuration

Violation logging is enabled by default:

```json
{
  "violation_logging": {
    "enabled": true,
    "max_entries": 1000,
    "retention_days": 30,
    "log_types": [
      "tool_permission",
      "directory_blocking",
      "secret_detected",
      "secret_redaction",
      "prompt_injection",
      "ssrf_protection",
      "config_file_threat",
      "unicode_attack"
    ]
  }
}
```

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `enabled` | Enable violation logging | `true` |
| `max_entries` | Maximum log entries to keep | `1000` |
| `retention_days` | Delete entries older than N days | `30` |
| `log_types` | Which violation types to log | All types |

---

## Use Cases

### Security Audits

**Question:** "What attacks were blocked last month?"

**Answer:** Query the violation log:
```bash
cat ~/.local/state/ai-guardian/violations.jsonl | \
  jq '.[] | select(.timestamp > "2024-03-01")'
```

**Results:**
- 15 SSRF attempts (metadata endpoint access)
- 8 prompt injection attempts (jailbreak patterns)
- 23 secret detections (API keys in commits)
- 3 credential exfiltration attempts (config files)

### Compliance Reporting

**Requirement:** Prove security controls are active

**Evidence:** Violation logs show:
- ✅ Security features are enabled and working
- ✅ Threats are being detected and blocked
- ✅ Audit trail exists for all security events
- ✅ Timestamps and details for each incident

### Troubleshooting False Positives

**Problem:** Legitimate operation blocked

**Solution:** Check violation log:
1. Find the blocked entry
2. Review the pattern/rule that triggered
3. Adjust configuration to allow legitimate use
4. Verify with test

**Example:**
```json
{
  "violation_type": "secret_detected",
  "message": "GitHub Personal Token detected",
  "details": {
    "file": "docs/SECURITY_EXAMPLES.md",
    "line": 42,
    "column": 8,
    "pattern": "ghp_"
  }
}
```

**Fix:** Add `docs/SECURITY_EXAMPLES.md` to ignore list (it's documentation).

### Attack Pattern Analysis

**Question:** "What types of attacks are most common?"

**Analysis:**
```bash
cat ~/.local/state/ai-guardian/violations.jsonl | \
  jq -r '.[] | .violation_type' | \
  sort | uniq -c | sort -nr
```

**Results:**
```
23 secret_detected        ← Most common
15 ssrf_protection
8  prompt_injection
5  unicode_attack
3  config_file_threat
```

**Action:** Focus security training on secret management (most violations).

---

## Viewing Logs

### Command Line (JSONL)

```bash
# View all violations
cat ~/.local/state/ai-guardian/violations.jsonl | jq '.'

# Filter by type
cat ~/.local/state/ai-guardian/violations.jsonl | \
  jq 'select(.violation_type == "directory_blocking")'

# Count by type
cat ~/.local/state/ai-guardian/violations.jsonl | \
  jq -r '.violation_type' | sort | uniq -c

# Recent violations (last 24 hours)
cat ~/.local/state/ai-guardian/violations.jsonl | \
  jq 'select(.timestamp > "'$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)'")'

# Unresolved violations only
cat ~/.local/state/ai-guardian/violations.jsonl | \
  jq 'select(.resolved == false)'
```

### AI Guardian CLI

```bash
# List recent violations
ai-guardian violations list

# Show violations by type
ai-guardian violations list --type ssrf_protection

# Export violations for date range
ai-guardian violations export --since 2024-04-01 --format csv
```

---

## Integration with SIEM

Violation logs can be integrated with Security Information and Event Management (SIEM) systems:

### Export to Splunk

```bash
# JSONL is already line-delimited - copy directly
cp ~/.local/state/ai-guardian/violations.jsonl /var/log/splunk/ai-guardian.log
```

### Export to Elasticsearch

```bash
# Bulk upload to Elasticsearch
cat ~/.local/state/ai-guardian/violations.jsonl | \
  jq -c '{"index": {"_index": "ai-guardian-violations"}} , .' | \
  curl -X POST "localhost:9200/_bulk" -H 'Content-Type: application/json' -d @-
```

### Custom Scripts

```python
import json

# Read JSONL violations (one per line)
violations = []
with open('~/.local/state/ai-guardian/violations.jsonl') as f:
    for line in f:
        violations.append(json.loads(line))

# Process violations
for v in violations:
    if v['severity'] in ['high', 'critical']:
        # Send alert
        send_security_alert(v)
```

### SARIF Format (Secret Scanning Only)

For secret scanning results, you can generate SARIF format:

```bash
ai-guardian scan --sarif-output results.sarif
```

SARIF is useful for CI/CD integration with tools like GitHub Code Scanning.

---

## Log Rotation

AI Guardian automatically manages log rotation:

### By Entry Count

When `max_entries` is reached:
1. Oldest entries are removed
2. New entries are appended
3. Log file stays at max size

**Example:** `max_entries: 1000`
- Log has 1000 entries
- New violation occurs
- Oldest entry removed
- New entry added
- Total: still 1000 entries

### By Age

When `retention_days` is exceeded:
1. Entries older than N days are removed
2. Cleanup happens on startup
3. Log file size decreases

**Example:** `retention_days: 30`
- Entries older than 30 days deleted
- Recent entries kept
- Automatic cleanup daily

---

## Privacy Considerations

Violation logs may contain sensitive information:

⚠️ **Logs may include:**
- File paths (may reveal project structure)
- Partial command output
- Secret patterns (but not full secrets)
- URLs attempted

✅ **Logs do NOT include:**
- Actual secret values (redacted)
- Full file contents
- User credentials
- Sensitive environment variables

### Secure Log Storage

**Recommendations:**
1. **Restrict permissions:**
   ```bash
   chmod 600 ~/.local/state/ai-guardian/violations.jsonl
   ```

2. **Encrypt log files** (if needed):
   ```bash
   gpg -c violations.json
   ```

3. **Regular review and cleanup:**
   ```bash
   ai-guardian violations clear --older-than 30d
   ```

---

## Performance Impact

Violation logging is **extremely efficient**:

- **Log write:** ~0.1ms per violation (async, non-blocking)
- **Storage:** ~500 bytes per entry (1000 entries ≈ 500KB)
- **Impact:** Negligible - you won't notice any slowdown

**Logs are written asynchronously** - detection speed is not affected.

---

## See Also

- [Configuration Guide](CONFIGURATION.md) - Full configuration reference
- [Tool Policy](TOOL_POLICY.md) - Command execution controls
- [SSRF Protection](security/SSRF_PROTECTION.md) - Network attack prevention
- [Secret Scanning](security/SECRET_SCANNING.md) - Prevent secret commits

---

## Summary

**Violation Logging** provides:

📝 **Complete audit trail** - Every blocked operation is logged with details  
🔍 **Security insights** - Understand attack patterns and trends  
✅ **Compliance proof** - Evidence that security controls are active  
🐛 **Debug assistance** - Troubleshoot false positives easily  
🔗 **SIEM integration** - Export to Splunk, Elasticsearch, etc.

**Automatic logging** of all security events for audit, compliance, and analysis.

---

## Version History

- **v1.1.0** - Initial violation logging (SARIF format)
- **v1.3.0** - Added retention policies and log rotation
- **v1.5.0** - Extended log types (SSRF, Unicode, config threats)
- **v1.6.0** - Enhanced SIEM integration and export formats
- **v1.12.0** - Added column-level position tracking across all scanner types (#1261)
- **v1.15.1** - Enriched violation context with `tool_name`, `source`, and `file_path` fields (#1717)
