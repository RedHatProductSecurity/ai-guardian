# Violation Logging

AI Guardian records blocked operations in JSONL for security review. Sensitive
secret and personal-data findings use a minimal, privacy-preserving audit record;
other violation types retain their normal event details.

## What is Violation Logging?

**Violation Logging** automatically records when AI Guardian blocks an operation:
- 📝 **Privacy-aware audit trail** - Blocked actions are logged with sensitive findings minimized
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
| **Secret / PII Finding** | Secret or personal data detected | Generic category, severity, ID, and timestamp only; no per-finding details |
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

### Unified Policy Decision

Standard entries include a `policy_decision` object. Its versioned schema is defined
in `src/ai_guardian/schemas/policy-decision.schema.json` and is shared by hook,
MCP, SDK, daemon, scanner, and external-inspector paths.

```json
{
  "schema_version": "1.0",
  "timestamp": "2026-09-22T12:00:00Z",
  "event": "PreToolUse",
  "decision": "block",
  "reason": "secret detected",
  "severity": "high",
  "confidence": 0.99,
  "policy_version": "ai-guardian/1.19.0-dev",
  "source": "secret_scanning",
  "agent": "claude_code",
  "repository": "/home/user/projects/example",
  "correlation_id": "agent-run-123",
  "latency_ms": 12.4,
  "violation_id": "viol_1234abcd",
  "violation_type": "secret_detected",
  "rule_id": "generic-api-key"
}
```

The object contains policy metadata only. Raw commands, matched text, snippets,
and scanner payloads are excluded by default. The correlation ID uses an
explicit run ID when available, then the session ID or tool-use ID, so related
checks can be grouped without copying agent content.

The existing top-level JSONL fields remain unchanged for standard violation
types; sensitive findings use the minimal record described below. Consumers that
read older entries can treat a missing `policy_decision` field as a legacy
record. Current REST, SDK, SARIF, and OTEL adapters preserve their existing
shapes and add the normalized record or its safe fields.

### Tool Input Diagnostics

New tool-permission records add optional `blocked.input_diagnostics` with integer
`schema_version: 1`. This distinguishes validation failures from ordinary policy
denials without copying the native tool payload:

```json
{
  "schema_version": 1,
  "subreason": "missing_argument",
  "native_tool_name": "read",
  "canonical_tool_name": "Read",
  "expected_field": "path",
  "input_type": "object",
  "argument_shape": {"limit": "integer"},
  "unrecognized_argument_count": 0,
  "target_status": "unknown"
}
```

Subreasons are fixed labels: `missing_argument`, `empty_argument`,
`invalid_argument`, `conflicting_arguments`, `normalization_failure`,
`workspace_unavailable`, `immutable_protection`, or `permission_denied`.
Recognized keys depend on the tool schema; only JSON type labels are retained.
Unrecognized keys are counted, not persisted, and the count is capped at 10,000.
Argument values, arbitrary keys, file contents, credentials, and session titles
are excluded. A normalization failure can retain a recoverable target in the
existing `blocked.file_path`; unknown/ambiguous targets are `null`, with an empty
string `tool_value` rather than a fabricated file name.

The associated context preserves canonical `tool_name`, existing session/call
correlation, and available `message_id`, `host_version`, `integration_version`,
and `workspace_source`. `project_path` identifies the hook's workspace;
`policy_project_path` identifies the policy request context, while `plugin_cwd`
records an available plugin startup location separately. Missing workspace data
is not replaced by daemon startup CWD. OpenCode's bridge also starts its checker
in the session workspace so its daemon forwarding uses that same directory.

Console Details and copy views revalidate the added diagnostics. MCP returns
only vetted fields, bounded IDs/version strings, and fixed guidance; unavailable
values are `null` or `unknown`. Legacy records without these fields remain valid;
the exact old missing-parameter classification is recognized without treating
arbitrary stored reason text as agent-safe. The existing `policy_decision.reason`
remains the generic safe classification, not a channel for raw details.

Paths and IDs are operational metadata. Review diagnostic copies before sharing.
Immutable input failures remain blocked and do not gain override actions.

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
  "id": "viol_1234abcd",
  "timestamp": "2026-11-02T08:35:42Z",
  "violation_type": "sensitive_finding",
  "severity": "high",
  "resolved": false,
  "resolved_at": null,
  "resolved_action": null
}
```

For `secret_detected`, `image_secret_detected`, and `pii_detected`, JSONL keeps
only the generic category, ID, timestamp, severity, and resolution state. It does
not retain source paths/positions, matched values, detector metadata, context,
suggestions, policy-decision details, or allowlist snippets. The original finding
remains available to the in-memory caller; the persistent history does not
distinguish which sensitive type was detected. Aggregate secret counts remain
available separately.

Ask-mode history does not store the matched input or scanner error text; it keeps
a fixed description and available source position. CLI scan history stores the
rule ID and source position, but not the finding message or snippet. The original
Ask inputs and complete CLI findings remain available to their in-memory callers
and command output, respectively. Generic records also persist only recognized
violation/severity labels; unknown labels are normalized rather than copied
verbatim.

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
    "mirror_remote_violations": false,
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

## Violation notifications

Privacy-safe alerts are enabled by default and are independent of violation
history logging and detection. Desktop notifications are selected by default;
email is optional. Configure one or both channels in the Web Console's
**Violation Notifications** card or under `violation_notifications`:

```json
{
  "violation_notifications": {
    "enabled": true,
    "channels": {"desktop": true, "email": false},
    "email": {"recipient": "security@example.org"}
  }
}
```

Alerts include only a fixed violation category, severity, and originating daemon.
They never include detected secrets, PII, scanned content, file paths, commands,
or scanner details. Email alerts use the SMTP host and authentication configured
under `support.email`, but use their own `violation_notifications.email.recipient`;
the support-bundle destination is not used. TLS is required (port 465 uses
implicit TLS; other ports use STARTTLS). Environment-variable SMTP credentials
are recommended; credentials and alert content are never written to notification
diagnostics. An email recipient and usable TLS SMTP settings are both required.

Each daemon first attempts its configured channels. The local tray relays remote
events through this host's own notification settings only when a remote channel is
known to be unconfigured or to have failed. A durable private event ledger
deduplicates channel delivery across daemon retries, tray polling, and restarts.
If the remote send outcome is ambiguous, the local host does not retry that
channel, avoiding a possible duplicate. Remote alert relay is separate from the
opt-in remote history mirroring setting. Events are kept in a private outbox for
up to 30 days so the tray can catch up after reconnecting. For older remote
daemons without a notification outbox, the tray uses a persisted overlapping
poll cursor and does not alert on the source's pre-existing history at first
connection.

When a hook falls back to direct processing because the daemon is unavailable,
it commits the privacy-safe event to the outbox before returning its response.
A detached worker delivers selected channels without keeping the short-lived IDE
hook open. Hooks handled by the long-running daemon retain asynchronous dispatch.

## Remote violation history mirroring

Remote mirroring is **off by default**. Enable the receiving daemon's global
`violation_logging.mirror_remote_violations` setting in the Web Console's
**Remote Violation Mirroring** card
to import summaries from reachable container, Kubernetes, manual, or SSH daemons.
The tray polls while the option is enabled and violation logging is active.

Only the violation type, severity, timestamp, and available tool/file/action/line
summary fields are copied. Raw blocked content, tool context, session identifiers,
policy details, and suggestions are not copied. Each local entry retains the source
daemon, event ID, and original event timestamp. Each source daemon is stored separately in
`remote-violations/<sha256-source-key>.jsonl`; the key hashes runtime/endpoint
identity rather than the display name, so same-named daemons do not collide.
Native local entries remain in
`violations.jsonl`. A private local index prevents duplicate imports across polls,
tray restarts, and violation-log rotation. Mirroring does not alter
or delete the source record. Local copies are explicitly **read-only**: the Console
does not offer Always Allow, Ignore File, or Suppress in Source actions for them.
When the source daemon is available and the source record has an ID, the Console
links back to its authoritative detail page. Unavailable daemons do not prevent
other sources from syncing, and existing local mirrors remain visible.
The Violations page's **Filter by daemon** field filters the displayed history as
you type, matching source labels case-insensitively alongside the type and directory
filters. **Select exact source** retains the source options for identity-specific
selection; same-named daemons with different endpoint identities remain distinct.
Options show current **Running**, **Paused**, or **Offline** availability. A source
that is not currently discoverable, or whose status cannot be confirmed, is shown as
**Unknown** rather than inferred offline from its historical records. Refreshing
source/status information keeps the selected filters. Clearing the daemon search
returns to **All Sources** without resetting the type or directory filters. Sources
are listed with the local daemon first, then remote sources by most recent violation.
Each file is rotated independently by the configured
`max_entries` and `retention_days`; cleanup runs during history reads and tray sync,
removing an empty source file so inactive daemons age out of the filter list.

Entries older than the receiving daemon's configured retention window are not
imported. The receiver must also have violation logging enabled. Disable the
setting at any time to stop future imports; already mirrored records remain in
local history until ordinary retention or size rotation removes them. Clearing
violation history removes the local log and all per-daemon mirror logs; the opaque
dedup index remains so previously cleared remote events are not silently restored.

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `enabled` | Enable violation logging | `true` |
| `mirror_remote_violations` | Import curated summaries from reachable remote daemons into this daemon's local history | `false` |
| `max_entries` | Maximum log entries to keep | `1000` |
| `retention_days` | Delete entries older than N days | `30` |
| `log_types` | Which violation types to log | All types |

Notification options are separate from that history configuration:

| Option | Description | Default |
|--------|-------------|---------|
| `violation_notifications.enabled` | Enable alerts independently of logging and detection | `true` |
| `violation_notifications.channels.desktop` | Deliver OS desktop notifications | `true` |
| `violation_notifications.channels.email` | Deliver email when a recipient and TLS SMTP settings are usable | `false` |
| `violation_notifications.email.recipient` | Alert recipient; SMTP transport/auth uses `support.email` | Empty |

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

📝 **Privacy-aware audit trail** - Sensitive finding details are intentionally omitted
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
