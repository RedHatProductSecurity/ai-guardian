# Compliance Audit Logging

AI Guardian can maintain a separate audit trail of final hook decisions. The
existing `violations.jsonl` file remains the record of detected violations;
`audit.jsonl` records allowed, warned, redacted, blocked, and failed hook
decisions when the feature is enabled.

## Enable Audit Logging

Add this section to the global `ai-guardian.json`:

```json
{
  "audit_logging": {
    "enabled": true,
    "log_all_tool_calls": true,
    "compliance_mode": {
      "soc2": true,
      "gdpr": true,
      "hipaa": false
    },
    "retention_days": 90,
    "sensitive_data_masking": true,
    "output_file": "~/.local/state/ai-guardian/audit.jsonl"
  }
}
```

The feature is disabled by default. When `log_all_tool_calls` is false, only
non-allow decisions are recorded.

The settings are also available in the TUI under **Monitoring -> Compliance
Audit Logging** and in the web console at `/audit-logging`.

## Data Protection

Audit entries use normalized hook metadata rather than the raw hook payload:

- Tool parameters are recursively masked for secrets and PII.
- Values under credential-like keys are replaced with `[MASKED]`.
- Long string values are truncated.
- Raw tool output and prompt text are never copied into the audit record.
- The versioned `policy_decision` object contains policy metadata only.

Set `include_context` fields to false when a deployment does not need the
corresponding identifier or metadata. Keep `sensitive_data_masking` enabled
for compliance deployments.

## Log Location And Retention

The default path is:

```text
~/.local/state/ai-guardian/audit.jsonl
```

`output_file` can select another path. Entries older than `retention_days` and
entries over `max_entries` are removed after a write. HIPAA deployments should
set a retention period that matches their approved records policy; the logger
does not silently override the configured retention value.

## Entry Shape

Each line is one JSON object. The record contains the event type, hook type,
decision, identifiers, masking metadata, compliance flags, and the shared
`policy_decision` object. `policy_decision` follows
`schemas/policy-decision.schema.json` and is compatible with the violation,
SARIF, SDK, and OTEL decision records.

Example shape:

```json
{
  "schema_version": "1.0",
  "event_type": "tool_call",
  "hook_type": "PreToolUse",
  "session_id": "session-123",
  "tool_name": "Bash",
  "tool_parameters": {
    "command": "printf '[MASKED]'"
  },
  "decision": "allow",
  "decision_reason": "No policy violations",
  "policy_matched": null,
  "masked_fields": ["tool_parameters.command"],
  "compliance_flags": {
    "soc2_logged": true,
    "gdpr_processing_activity": true,
    "hipaa_access_log": false
  },
  "policy_decision": {
    "schema_version": "1.0",
    "event": "PreToolUse",
    "decision": "allow",
    "reason": "No policy violations",
    "severity": "none"
  }
}
```

## Export

`AuditLogger` supports JSON and CSV exports without changing the JSONL source:

```python
from pathlib import Path

from ai_guardian.violations.audit import AuditLogger

logger = AuditLogger()
logger.export(Path("audit-export.json"), export_format="json")
logger.export(Path("audit-export.csv"), export_format="csv")
```

The configured `export_format` is used when the format is omitted.

## Compliance Mapping

| Mode | Recorded evidence |
| --- | --- |
| SOC 2 | All final decisions, timestamps, rationale, and policy metadata when enabled |
| GDPR Article 30 | Processing activity context, session correlation, tool identity, and decision outcome |
| HIPAA | Access decision records with masking and configurable retention |

Audit logging supports compliance evidence collection but does not replace an
organization's access control, retention, review, or incident-response policy.
