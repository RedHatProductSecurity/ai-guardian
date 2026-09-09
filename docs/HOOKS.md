# Hook Configuration Guide

This guide explains how AI Guardian hooks work with Claude Code and other IDEs, including hook ordering requirements and limitations.

## Table of Contents

- [Hook Ordering Requirements](#hook-ordering-requirements)
- [Hook Types and Warnings](#hook-types-and-warnings)
- [Hook Limitations](#hook-limitations)
- [Setup and Verification](#setup-and-verification)
- [Use Cases for Log Mode](#use-cases-for-log-mode)

---

## Hook Ordering Requirements

### Critical: ai-guardian Must Be First Hook (For Log Mode)

**When using multiple hooks in Claude Code with log-only mode (`action: "log-only"`), ai-guardian MUST be the first hook in each hook type's array.**

#### Why This Matters

Claude Code's hook system runs hooks sequentially, but only the **first hook's `systemMessage`** is displayed to the user. Each hook type displays different log mode warnings via `systemMessage`:

- **PreToolUse**: Tool permissions, directory rules
- **UserPromptSubmit**: Prompt injection  
- **PostToolUse**: (No log mode warnings - secret/prompt-injection/context-poisoning scanning always blocks)

If another hook runs before ai-guardian, warnings are silently suppressed.

#### Wrong Configuration - Warnings Suppressed

```json
{
  "PreToolUse": [
    {
      "matcher": "*",
      "hooks": [
        {
          "command": "other-hook",
          "statusMessage": "Running other hook..."
        },
        {
          "command": "ai-guardian",
          "statusMessage": "🛡️ Checking tool permissions..."
        }
      ]
    }
  ]
}
```

**Result:** ai-guardian warnings are silently suppressed. Users won't see policy violations!

#### Correct Configuration - Warnings Visible

```json
{
  "PreToolUse": [
    {
      "matcher": "*",
      "hooks": [
        {
          "command": "ai-guardian",
          "statusMessage": "🛡️ Checking tool permissions..."
        },
        {
          "command": "other-hook",
          "statusMessage": "Running other hook..."
        }
      ]
    }
  ]
}
```

**Result:** ai-guardian warnings display correctly. Other hooks can still run.

---

## Hook Types and Warnings

### 1. PreToolUse (Required first for log mode)

**Displays:** Tool permissions violations, directory access violations

**Must be first if:** Using `tool_permissions` or `directory_rules` with `action: "log-only"`

Checks tool permissions and directory rules before tools execute. In log mode, violations are displayed via `systemMessage`:

```json
"PreToolUse": [
  {
    "matcher": "*",
    "hooks": [
      { "command": "ai-guardian", "statusMessage": "🛡️ Checking tool permissions..." },
      { "command": "your-other-hook" }
    ]
  }
]
```

**Example warnings:**
```
PreToolUse:Skill says: ⚠️ Policy violation (log mode): Skill(database-migration) not in allow list - execution allowed

PreToolUse:Read says: ⚠️ Directory access violation (log mode): Directory rules matched '~/.claude/skills/unapproved/file.txt' - access allowed
```

### 2. UserPromptSubmit (Required first for prompt injection log mode)

**Displays:** Prompt injection detection warnings

**Must be first if:** Using `prompt_injection` with `action: "log-only"`

**Note:** Secret scanning always blocks (`decision: "block"`) and never uses `systemMessage`, so hook ordering doesn't affect secret detection.

```json
"UserPromptSubmit": [
  {
    "hooks": [
      { "command": "ai-guardian", "statusMessage": "🛡️ Scanning prompt..." },
      { "command": "your-other-hook" }
    ]
  }
]
```

**Example warning:**
```
UserPromptSubmit says: ⚠️ Prompt injection detected (log mode): confidence=0.95 - execution allowed
```

### 3. PostToolUse (Order doesn't matter for log mode)

**Displays:** No log mode warnings (secret scanning always blocks)

**Hook ordering doesn't matter** for log mode warnings because PostToolUse scans tool outputs for secrets, prompt injection, and context poisoning — all of which always block execution regardless of order.

```json
"PostToolUse": [
  {
    "matcher": "*",
    "hooks": [
      { "command": "ai-guardian", "statusMessage": "🛡️ Scanning tool output..." },
      { "command": "your-other-hook" }
    ]
  }
]
```

**Note:** Still recommended to keep ai-guardian first for consistency.

---

## Hook Limitations

### Why Warning Messages Aren't Displayed

**Claude Code hooks don't display non-blocking messages to users.** When a hook exits with code 0 (success), Claude Code discards all stdout and stderr output. This is why ai-guardian uses **"log" mode** instead of "warn" mode - violations are logged for audit but never shown to users during execution.

#### Claude Code Hook Behavior

| Exit Code | stdout/stderr | Behavior |
|-----------|---------------|----------|
| `0` | Any output | **Discarded** - User sees nothing |
| `!= 0` | stderr content | **Displayed** - User sees error message |

**Result:** Non-blocking warnings (exit 0) are invisible to users.

#### Why This Matters

**1. User Experience**
Users never see policy violations in "log mode":
- No visual feedback that a policy was violated
- No notification that activity is being logged
- Silent operation gives false sense that no policy applies

**2. Naming Accuracy**
"Warn mode" implies users are warned, but they aren't:
- ❌ "Warn" suggests user notification
- ✅ "Log" accurately describes behavior (logged but not shown)

**3. Compliance & Audit**
The actual value is in audit logging, not user warnings:
- All violations logged to ViolationLogger
- Visible in Console (`ai-guardian console`)
- Logged at WARNING level for audit
- Perfect for compliance tracking

### What "Log Mode" Does

✅ **Logs violation** at WARNING level  
✅ **Records to ViolationLogger** (visible in Console)  
✅ **Allows execution** (exit 0)  
❌ **Does NOT show message to user** (Claude Code limitation)

### What "Block Mode" Does

✅ **Logs violation** at ERROR level  
✅ **Records to ViolationLogger** (visible in Console)  
✅ **Shows error message to user** (exit != 0, stderr displayed)  
✅ **Prevents execution**

### Comparison with Other IDEs

| IDE | Block Mode Messages | Log Mode Messages | Notes |
|-----|-------------------|-------------------|-------|
| **Claude Code** | ✅ Displayed (exit != 0) | ❌ Not displayed (exit 0) | Logs only |
| **Cursor** | ✅ Displayed (`permission: deny`; legacy `continue: false` is retained for file-read compatibility) | ❌ Not displayed (`permission: allow`) | User-level desktop/CLI hooks |
| **Aider** | ✅ Displayed (exit != 0) | ❌ Not displayed (exit 0) | Same as Claude Code |
| **GitHub Copilot** | ✅ Displayed (deny) | ❌ No log mode support | Binary only |

**Conclusion:** No major IDE currently supports non-blocking warning messages to users. Log mode is for audit logging only.

---

## Setup and Verification

### Setup Command Behavior

The `ai-guardian setup` command automatically configures ai-guardian as the **only** hook for each hook type. This ensures correct ordering.

**If you manually add additional hooks:**
1. Always add them **after** ai-guardian in the array
2. Never insert hooks before ai-guardian in PreToolUse or UserPromptSubmit
3. Test that warnings still display by triggering a log mode violation

### Verification Steps

To verify your hook ordering is correct:

1. Configure a feature in log mode (e.g., tool not in allowlist, directory with deny rule)
2. Trigger the violation (e.g., use the tool, read the file)
3. Check if you see the warning: `PreToolUse:ToolName says: ⚠️ ...` or `UserPromptSubmit says: ⚠️ ...`

**If you don't see warnings:**
- Check `~/.claude/settings.json` hook ordering
- Ensure ai-guardian is first in PreToolUse and UserPromptSubmit hooks arrays
- Restart Claude Code to reload configuration

### Alternative: Separate Matchers

If you need different hooks for different tools, use separate matchers:

```json
"PreToolUse": [
  {
    "matcher": "*",
    "hooks": [
      { "command": "ai-guardian" }
    ]
  },
  {
    "matcher": "SpecificTool",
    "hooks": [
      { "command": "other-hook" }
    ]
  }
]
```

This way each matcher has only one hook, avoiding conflicts.

---

## Use Cases for Log Mode

Since users won't see warnings, log mode is best for:

### 1. Gradual Policy Rollout

```json
{
  "permissions": [{
    "matcher": "Skill",
    "mode": "allow",
    "patterns": ["production-approved-*"],
    "action": "log-only"  // ← Monitor violations before enforcing
  }]
}
```

**Workflow:**
1. Deploy with `action: "log-only"`
2. Monitor violations in Console
3. Identify false positives
4. Adjust patterns
5. Switch to `action: "block"`

### 2. Compliance Audit Mode

```json
{
  "secret_scanning": {
    "enabled": true
  }
}
```

**Use Case:** Security team monitors for secrets. Note: secret scanning always blocks when secrets are detected — there is no log-only mode for security reasons.

### 3. Policy Testing

```json
{
  "prompt_injection": {
    "enabled": true,
    "action": "log-only"  // ← Test detection accuracy
  }
}
```

**Use Case:** Identify false positives before enforcing.

### Viewing Violations

Since users don't see warnings in Claude Code, use these methods:

#### 1. Console (Recommended)
```bash
ai-guardian console
```

Shows all violations with:
- Timestamp
- Violation type
- Details (tool, pattern, file)
- Action taken (blocked/allowed)
- Suggested fixes

#### 2. Log Files
```bash
# Python logging output
tail -f ~/.local/state/ai-guardian/ai-guardian.log

# Look for WARNING level entries
grep "WARNING" ~/.local/state/ai-guardian/ai-guardian.log
```

#### 3. Violation Logger JSON
```bash
# Raw violation records
cat ~/.local/state/ai-guardian/violations.jsonl | jq .
```

---

## Best Practices

### Critical Requirements (Log Mode Only)
- **PreToolUse**: ai-guardian MUST be first (displays tool permissions & directory rules warnings)
- **UserPromptSubmit**: ai-guardian MUST be first if using prompt injection log mode (secret scanning blocks regardless of order)
- **PostToolUse**: Order doesn't matter for log mode (no warnings displayed, blocks secrets/prompt-injection/context-poisoning)

### Do's and Don'ts

✅ **Do:**
- Run `ai-guardian setup` to configure hooks automatically
- Keep ai-guardian first in all hooks arrays for consistency
- Test warning visibility after adding new hooks
- Use separate matchers for different tools if needed
- Use Console to monitor log mode violations

❌ **Don't:**
- Add other hooks before ai-guardian in PreToolUse or UserPromptSubmit when using log mode
- Assume warnings will display if ordering is wrong
- Skip testing after modifying hook configuration
- Generate warning messages in log mode (wasted effort - they won't be shown)
- Use "warn" terminology (misleading - use "log" instead)
- Expect users to see violations in IDE UI

**Security Impact:** Incorrect hook ordering can suppress log mode warnings, eliminating visibility into policy violations. Always verify warnings display correctly.

---

## Technical Details

### Hook Response Formats

**PreToolUse response:**
```json
{
  "hookSpecificOutput": {
    "permissionDecision": "allow",
    "hookEventName": "PreToolUse"
  },
  "systemMessage": "⚠️ Policy violation (log mode): ..."
}
```

**UserPromptSubmit response:**
```json
{
  "systemMessage": "⚠️ Prompt injection detected (log mode): ..."
}
```

Claude Code displays the first hook's `systemMessage` to the user, which is why ordering matters.

### Exit Code Behavior

**Success (exit 0):**
```python
# Hook code
print("⚠️ WARNING: Policy violation", file=sys.stderr)
sys.exit(0)  # Allow execution

# Result: Message printed but Claude Code discards it
# User sees: Nothing
```

**Failure (exit != 0):**
```python
# Hook code
print("🚨 BLOCKED BY POLICY: Violation detected", file=sys.stderr)
sys.exit(2)  # Block execution

# Result: Claude Code displays stderr to user
# User sees: Error message with details
```

---

## Summary

### For Users

✅ **Use log mode for:**
- Gradual policy rollout
- Compliance auditing
- Testing new policies
- Development environments

✅ **Use block mode for:**
- Production enforcement
- Critical security policies
- Zero-trust environments

✅ **Monitor violations via:**
- `ai-guardian console` (best UX)
- Log files (automation)
- ViolationLogger (programmatic access)

### For Developers

✅ **Do:**
- Use "log" terminology consistently
- Document that violations are logged, not shown
- Direct users to Console for violation visibility

❌ **Don't:**
- Generate warning messages in log mode (wasted effort)
- Use "warn" terminology (misleading)
- Expect users to see violations in IDE UI

---

## Hook Latency Tracking

**NEW in v1.11.0** — AI Guardian can record per-hook and per-violation-type timing for performance analysis.

### Enabling Latency Tracking

Add to your `ai-guardian.json`:

```json
{
  "latency_tracking": {
    "enabled": false,
    "max_entries": 5000,
    "retention_days": 30
  }
}
```

### Viewing Latency Data

```bash
ai-guardian metrics --latency          # Human-readable summary
ai-guardian metrics --latency --json   # JSON output for automation
```

Data is stored in `~/.local/state/ai-guardian/latency.jsonl` alongside `violations.jsonl`.

### Console Dashboard

Both the TUI (`ai-guardian console`) and web console (`ai-guardian console --web`) display latency metrics on the Security Dashboard, showing average hook execution time and per-check breakdowns.

### Coverage, configuration, and restart behavior

Latency is collected by the shared hook pipeline after the active IDE adapter
normalizes the input. This makes the setting available in both execution
modes:

- **Direct hook mode** reads the effective configuration for each short-lived
  `ai-guardian` process.
- **Daemon hook mode** checks configuration as part of hook handling. Global
  configuration changes are detected by modification time, and daemon hook
  requests use the project directory supplied by the IDE when resolving a
  project config. The web/REST configuration update and
  `ai-guardian daemon reload` paths can also force an immediate reload.

A daemon or IDE restart is not required for a configuration-only change when
the hooks are already installed. Restart or reload the host application only
when its hook definitions or an extension/plugin installation has changed.

Codex's five managed hooks (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`PostCompact`, and `SessionEnd`) all produce latency entries when they invoke
AI Guardian. Lifecycle events return an allow response without security
content scanning, but are still timed. See the [Hook Latency Support
Matrix](AGENT_SUPPORT.md#hook-latency-support-matrix) for every supported
integration, including the commit-time Aider CLI and MCP-only Junie limits.

The `OpenAI Codex (CLI + Desktop)` label covers Codex CLI and Codex mode in
the ChatGPT desktop app. Regular ChatGPT mode does not run these Codex
lifecycle hooks and is not currently protected by them. The ChatGPT desktop
app, Codex CLI, and Codex IDE extension can share MCP configuration, but MCP
availability is separate from hook enforcement.

### Verifying collection

1. Enable `latency_tracking.enabled` in the global or project configuration,
   or in the Performance page.
2. Trigger a normal prompt or tool hook in the target IDE/agent.
3. Run:

   ```bash
   ai-guardian metrics --latency --since 1d
   ai-guardian metrics --latency --json --since 1d
   ```

4. Confirm that `Invocations` is non-zero (or `invocation_count` in JSON) and
   that the report contains the normalized event for the hook you triggered.
   The log is normally `~/.local/state/ai-guardian/latency.jsonl`; deployments
   using `AI_GUARDIAN_STATE_DIR` use that directory instead.

If Codex still shows no entries, confirm that the daemon is running and not
paused with `ai-guardian daemon status`, then use `ai-guardian daemon reload`
after a configuration edit. Verify that the Codex hook is installed in the
active Codex layer; changing the setting alone does not install a missing
hook. The report groups entries by normalized hook event and check, so it does
not identify the source IDE in each row.

---

## Related Documentation

- [CONSOLE.md](CONSOLE.md) - Using the Console to view violations
- [README.md](../README.md) - Action modes configuration
- [CHANGELOG.md](../CHANGELOG.md) - Version history
- [Claude Code Hooks Documentation](https://code.claude.com/docs/en/hooks)

---

**Last Updated:** 2026-06-11  
**Version:** 1.11.0  
**Cursor Testing:** Desktop and local CLI command hooks use the same JSON
protocol. AI Guardian installs the managed hook set and MCP registration in the
user-level Cursor configuration by default. Use the explicit Cursor Cloud
project setup flow (`ai-guardian setup --ide cursor --project DIR`, or the tray
directory picker) when the remote run needs `<DIR>/.cursor/hooks.json`.
Configure Cursor Cloud MCP separately through Cursor's dashboard/team settings
or Cloud Agents API; `<DIR>/.cursor/mcp.json` is for local Cursor workspaces.
