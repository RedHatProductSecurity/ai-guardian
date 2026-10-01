# AI Guardian MCP Tools Reference

## Security Checks (Proactive)

| Tool | Parameters | Returns | When to Use |
|------|-----------|---------|-------------|
| `check_path` | `path: str` | `{status: "allowed"\|"denied"\|"not_found"}` | Before Read/Write/Edit on unfamiliar paths |
| `check_command` | `command: str, project_dir?: str` | `{status: "allowed"\|"blocked", reason?: str}` | Before commands with URLs, credentials, file paths |
| `check_mcp_trust` | `server_name: str` | `{status: "trusted"\|"untrusted"}` | Before suggesting MCP server usage |
| `sanitize_text` | `text: str` | `{sanitized_text, redaction_count, types}` | Before outputting potentially sensitive content |
| `check_annotations` | `file_path: str` | `{valid: bool, warnings: [...]}` | After editing files with ai-guardian annotations |

## Information (Query)

| Tool | Parameters | Returns | When to Use |
|------|-----------|---------|-------------|
| `get_violations` | `violation_type?: str, limit?: int` | `{violations: [...], count}` | "Why was that blocked?" |
| `get_config` | _(none)_ | `{features: {name: bool, ...}}` | "What's my security config?" |
| `get_scanner_status` | _(none)_ | `{scanners: [{name, version, is_default}]}` | "What scanners are installed?" |
| `get_scanner_supported` | _(none)_ | `{scanners: ["gitleaks", ...]}` | "What scanners can I install?" |
| `get_patterns_list` | _(none)_ | `{categories: {name: count}}` | "What patterns are checked?" |
| `get_metrics` | `since_days?: int` | `{total_violations, by_type, by_severity, ...}` | "How many violations this week?" |
| `doctor` | _(none)_ | `{checks: [{name, status, message, detail?, fix_hint?, fixable?}]}` | "Is my setup working?" |

## Reason Values for check_command

| Reason | Meaning |
|--------|---------|
| `secret_detected` | Command contains what appears to be a secret/API key |
| `ssrf_detected` | Command targets a potentially dangerous URL (internal IP, metadata endpoint) |
| `prompt_injection` | Command contains suspected prompt injection |
| `directory_blocked` | Command accesses a protected directory |
| `command_policy_denied` | Command protection policy blocked the command |
| `permission_denied` | Ordinary tool permission blocked the command |
| `identity_failure` | The running built-in MCP process is not currently verified |
| `policy_check_error` | The policy check could not be completed |

When `project_dir` is omitted, the MCP server uses `AI_GUARDIAN_PROJECT_DIR`
when provided, otherwise its launch directory. The server captures the trusted
developer-session setting once at startup. These context rules affect the
advisory result only; the direct hook remains authoritative.

## Violation Types for get_violations

`secret_detected`, `prompt_injection`, `jailbreak_detected`, `tool_permission`, `directory_blocking`, `ssrf_blocked`, `config_file_exfil`, `pii_detected`

## Support Bundle

| Tool | Parameters | Returns | When to Use |
|------|-----------|---------|-------------|
| `prepare_support_bundle` | _(none)_ | `{bundle_id, temp_path, destination, files: [{name, sanitized, redactions, note}]}` | When user asks to send info to support — always call this first |
| `send_support_bundle` | `bundle_id: str` | `{status: "sent"\|"error", destination, message}` | Only after user reviews and approves the prepared bundle |

## Special Responses

All tools may return `{"status": "disabled"}` when ai-guardian MCP is turned off. Proceed without checks — hooks still enforce.

Tools may return `{"status": "error"}` on internal failures. Proceed with caution and let hooks handle enforcement.

## Resources

| URI | Content |
|-----|---------|
| `ai-guardian://security-posture` | Feature status, action modes, scanner status |
| `ai-guardian://protected-paths` | Protected directory list |
| `ai-guardian://recent-violations` | Last 10 violations |
