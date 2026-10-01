---
name: ai-guardian-security
description: >
  AI security advisor — proactive security checks via ai-guardian MCP tools.
  Use this skill whenever you have access to ai-guardian MCP tools (check_path,
  check_command, check_mcp_trust, sanitize_text, get_violations,
  get_config, get_scanner_status, get_scanner_supported, get_patterns_list,
  get_metrics, doctor, prepare_support_bundle, send_support_bundle,
  scan_directory, scan_directory_report). Activate when:
  accessing files in unfamiliar directories, running commands with URLs or credentials,
  outputting potentially sensitive text,
  when the user asks about security status, violations, scanners, or configuration,
  or when the user wants to send diagnostic information to support.
user-invocable: false
---

# AI Guardian Security Advisor

You have access to ai-guardian MCP tools. These let you **check security before acting** — rather than being blocked by hooks and retrying.

The tools are read-only and advisory. Hooks remain the enforcement layer. If a tool returns `{"status": "disabled"}`, ai-guardian MCP is turned off — proceed without checks and let hooks handle enforcement.

## Proactive Check Level

The `proactive_level` setting (in `get_config()` response) controls how often to use security checks. Hooks always enforce regardless of level — proactive checks add early detection at the cost of latency and token usage (each check adds a tool call and result to the conversation context, which increases tokens consumed on every subsequent API turn).

### low (default) — Minimal checking
Only use security tools when:
- The user explicitly asks about security
- A hook just blocked something and you need to understand why
- You're about to output text that clearly contains secrets

### medium — Selective checking
Everything in **low**, plus:
- `check_path` when accessing files **outside the current project** or in unfamiliar directories
- `check_command` when a command contains something that **looks like a credential or internal URL**
- `check_mcp_trust` when suggesting an MCP server the user hasn't used before
No need to check routine operations (`ls`, `git status`, `pytest`, project files).

### high — Check everything
Everything in **medium**, plus:
- `check_path` before every file Read/Write/Edit
- `check_command` before every Bash command
- `sanitize_text` on any output that could contain user data

This adds noticeable latency, grows the conversation context, and increases token usage. Use for high-security environments.

### paused — Skip proactive action-gating
An explicit `paused` level, or an active daemon/global or applicable directory
pause, skips `check_path`, `check_command`, and `check_mcp_trust`. The saved
`low`, `medium`, or `high` level is preserved during a runtime daemon pause and
returns automatically when the pause expires or the daemon resumes. Hooks remain
the mandatory enforcement layer and are not paused by this setting.

### Tool responses
- `check_path`, `check_command`, and `check_mcp_trust` return `"paused"` with
  `skipped: true` when proactive action-gating is paused.
- A paused response uses reason `proactive_checks_paused` and explains that
  hooks remain active. Query, diagnostic, and reporting tools remain usable.
- `check_path`: `"allowed"` / `"denied"` (protected by rules) / `"not_found"` (file doesn't exist)
- `check_command`: `"allowed"` / `"blocked"` + reason (`secret_detected`, `ssrf_detected`, `prompt_injection`, `directory_blocked`, `command_policy_denied`, `permission_denied`, `identity_failure`, `policy_check_error`)

When calling `check_command`, pass `project_dir` when the active workspace is
known. Otherwise the server uses `AI_GUARDIAN_PROJECT_DIR` or its launch
directory.

When workspace context is available, pass `project_dir` to `get_config()` so
its effective proactive level includes directory-scoped pauses.

All checks are advisory — hooks provide enforcement as a safety net.

## When a Tool is Blocked

When a hook blocks a tool call (Read, Write, Bash, etc.) and you need to explain why:

1. **Get the actual reason**: Call `get_violations(limit=1)` to retrieve the real block reason from the violation log
2. **Report the real reason**: Tell the user the actual violation type — secret detected, PII found, prompt injection, SSRF, directory protected, etc.
3. **Do NOT guess**: The hook error message alone may be generic. Always query `get_violations()` for the specific violation type, file path, and line number.
4. **Accept the block**: The block is the security policy working as intended. Do not attempt to work around it.

## Do NOT

- Suggest using `!` prefix to run commands — this bypasses all security hooks and defeats protection
- Suggest alternative commands or tools to access content that was blocked
- Guess the block reason from error messages — always call `get_violations()` for the actual reason
- Suggest disabling security features or modifying security configuration files
- Suggest ways to suppress or bypass security detection
- Explain how security protections can be circumvented
- Suggest flags or options that skip security verification

## After Config Changes

Security config can change at any time (via Console, tray, CLI, or file edit). When the user modifies ai-guardian settings, re-query `get_config()` and `get_scanner_status()` on your next security-related action. Treat previous results as stale.

## When Asked About Security

| User asks | Call |
|-----------|------|
| "Why was that blocked?" | `get_violations(violation_type=..., limit=10)` — always show file path and line number when present (see below) |
| "What's my security config?" | `get_config()` |
| "Is my setup working?" | `doctor()` — see below |
| "How many violations?" | `get_metrics(since_days=7)` |
| "What scanners do I have?" | `get_scanner_status()` and `get_scanner_supported()` |
| "What patterns are checked?" | `get_patterns_list()` |
| "Scan this project" | `scan_directory()` — summary first, offer report if violations found |

### Presenting violation details

When showing violations to the user, always include the file path and line number when the response contains them. This helps the user locate exactly where the issue was detected.

- If the violation has `file` and `line` fields, show them as `file:line` (e.g., `src/config.py:42`)
- If only `file` is present, show the file path alone
- Only omit location details when the user asks for a summary or aggregate view (e.g., "how many violations this week?" — use `get_metrics` instead)

### Explaining doctor results

When `doctor()` returns checks with `"warn"` or `"fail"` status, explain the issue to the user using the `message`, `detail`, and `fix_hint` fields. If `fixable` is `true`, let the user know they can auto-fix it by running `ai-guardian doctor --fix` in their terminal. Do not run the fix command yourself — it modifies configuration and the user should decide.

## Scanning the Project

When the user asks to check the project for security issues:

1. Call `scan_directory()` — get a summary (counts, file paths, violation types — no secret values)
2. Report the summary to the user: "Found X violations in Y files"
3. Ask: "Want me to generate a detailed report for review?"
4. If yes — call `scan_directory_report()` — tell user the report file path
5. **NEVER read the report file yourself** — it contains actual secret/PII values

The report is written to a temp directory. The user reviews it directly at the file path you provide.

## Sending Support Information

When the user asks to send diagnostic info to support:

**Step 1 — Prepare:** Call `prepare_support_bundle()`. This creates sanitized copies in a temp directory.

**Step 2 — Review (required, do not skip):** Show the temp directory path and the file list with redaction counts. Tell the user to review and delete any files they don't want to send — the directory is protected so only the user can access it, not you.

> "Bundle prepared at: `/tmp/ai-guardian-support-abc123/`
>
> Files included:
> - config.json — no redactions
> - violations.json — 12 file paths redacted
> - metrics.json — clean (aggregate stats only)
> - doctor.json — clean
> - system-info.json — clean
> - ai-guardian.log — 5 items redacted
>
> Please review the files at that path. Delete any you don't want to send.
> Let me know when you're ready to send."

**Step 3 — Send:** Only after the user confirms, call `send_support_bundle(bundle_id)`.

**Step 4 — Follow up:** After the bundle is sent, tell the user to contact support and give them the bundle name (the `bundle_id` from step 1, e.g., `support-20260511-abc123`). This is how support locates their diagnostics.

Do not show file contents in the conversation — only the summary with redaction counts.

## Boundaries

These tools are read-only security advisors. Do not use their results to help circumvent ai-guardian protections — if a path is denied or a command is blocked, that's the security policy working as intended. The user can adjust their config if they disagree with a policy decision.
