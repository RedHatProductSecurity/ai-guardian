# Agent Support

AI Guardian protects multiple AI coding agents through a unified hook adapter architecture. Each agent gets a dedicated adapter that normalizes its hook format into a common internal model, so the core scanning pipeline stays agent-agnostic.

## Supported Agents

| Agent | Setup Command | Hooks | MCP | Status |
|-------|--------------|-------|-----|--------|
| Claude Code | `--ide claude` | Full | Full | **Complete** |
| Cursor | `--ide cursor` | Full | N/A | **Complete** |
| GitHub Copilot | `--ide copilot` | Full | N/A | **Complete** |
| OpenAI Codex | `--ide codex` | Full | N/A | **Complete** |
| Windsurf | `--ide windsurf` | Full | N/A | **Complete** |
| Gemini CLI | `--ide gemini` | Full | N/A | **Complete** |
| Cline / ZooCode | `--ide cline` | Full | N/A | **Complete** |
| Kiro (AWS) | `--ide kiro` | Full | N/A | **Complete** |
| Augment Code | `--ide augment` | Full | N/A | **Complete** |
| AiderDesk | `--ide aiderdesk` | Extension | N/A | **Complete** |
| OpenClaw | `--ide openclaw` | Plugin | N/A | **Complete** |
| OpenCode | `--ide opencode` | Plugin | N/A | **Complete** |
| Crush (Charmbracelet) | `--ide crush` | Partial | Full | **Complete** |
| Junie (JetBrains) | `--ide junie` | N/A | Full | **MCP-only** |

## Hook Capability Matrix

| Agent | SessionStart | UserPromptSubmit | PreToolUse | PostToolUse | BeforeReadFile | PostCompact | SessionEnd |
|-------|-------------|-----------------|------------|-------------|----------------|-------------|------------|
| Claude Code | Yes | Yes | Yes | Yes | N/A | Yes | Yes |
| Cursor | N/A | Yes | Yes | Yes | Yes | N/A | N/A |
| GitHub Copilot | N/A | Yes | Yes | N/A | N/A | N/A | N/A |
| OpenAI Codex | N/A | Yes | Yes | Yes | N/A | Yes | Yes |
| Windsurf | N/A | Yes | Yes | Yes | Yes | N/A | N/A |
| Gemini CLI | Yes | Yes (BeforeAgent) | Yes | Yes | N/A | N/A | N/A |
| Cline / ZooCode | N/A | Yes | Yes | Yes | N/A | N/A | N/A |
| Kiro | N/A | Yes | Yes | Yes | N/A | N/A | N/A |
| Augment Code | N/A | N/A | Yes | Yes | N/A | N/A | N/A |
| OpenCode | N/A | Yes (chat.message) | Yes | Yes | N/A | N/A | N/A |
| Crush | N/A | N/A | Yes | N/A | N/A | N/A | N/A |
| Junie | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

## Protection Level by Hook Availability

| Hooks Available | AI Guardian Capabilities |
|----------------|------------------------|
| **Full hooks** (Prompt + Pre + Post) | Secret scanning, PII detection, prompt injection, SSRF, directory blocking, config scanning, redaction, tool permissions |
| **Pre + Post only** (no Prompt) | All above except prompt scanning and transcript scanning |
| **MCP only** (no hooks) | Advisory checks only — check_path, check_command, check_mcp_trust, sanitize_text. No enforcement (agent must cooperate) |
| **None** | No protection available |

## Violation Type Coverage Matrix

Coverage per agent depends on which hooks are available. This table shows representative agents across the enforcement spectrum: full hooks + MCP, full hooks only, partial hooks, and MCP-only.

Agents with full hook support not shown individually (Windsurf, Gemini CLI, Cline, Kiro, OpenCode) have the same coverage as Claude Code, minus MCP and minus UserPromptSubmit where applicable — see the [Hook Capability Matrix](#hook-capability-matrix) above. Copilot CLI and Codex support transcript scanning via adapter-resolved default paths (Issue #935).

| Violation Type | Requires | Claude Code | Cursor | Copilot | Junie (MCP) |
|---|---|---|---|---|---|
| secret_detected | Pre+Post | Enforce | Enforce | Enforce | Advisory |
| secret_redaction | Post | Enforce | Enforce | Enforce | No |
| pii_detected | Pre+Post+Prompt | Enforce | Enforce | Partial | Advisory |
| directory_blocking | Pre | Enforce | Enforce | Enforce | Advisory |
| tool_permission | Pre | Enforce | Enforce | Enforce | No |
| prompt_injection | Pre+Prompt | Enforce | Enforce | Partial | Advisory |
| jailbreak_detected | Pre+Prompt | Enforce | Enforce | Partial | Advisory |
| ssrf_blocked | Pre | Enforce | Enforce | Enforce | Advisory |
| config_file_exfil | Pre | Enforce | Enforce | Enforce | No |
| secret_in_transcript | Prompt | Enforce | Enforce | Enforce | No |
| pii_in_transcript | Prompt | Enforce | Enforce | Enforce | No |
| image_secret | Pre | Caution | Caution | Caution | No |
| image_pii | Pre | Caution | Caution | Caution | No |
| offensive_language | Pre+Post | Enforce | Enforce | Partial | Advisory |
| canary_detected | Pre+Post+Prompt | Enforce | Enforce | Partial | Advisory |
| exfil_detection | Pre (Bash) | Enforce | Enforce | Partial | Advisory |

**Legend:**

- **Enforce** — fully tested and working
- **Advisory** — MCP only, agent must cooperate (no enforcement)
- **Partial** — no UserPromptSubmit, only file content scanned
- **Caution** — known limitations (see [Image scanning](#image-scanning-all-agents) below)
- **No** — not supported

## Known Limitations

### Claude Code upstream issues

These are open issues in the Claude Code runtime that affect ai-guardian's enforcement capabilities. They apply only to Claude Code — other agents are not affected.

#### PostToolUse `updatedToolOutput` not honored for Bash

When ai-guardian redacts secrets or PII from Bash output via the `PostToolUse` hook, the redacted text is returned in `updatedToolOutput`. Claude Code currently ignores this field for Bash tool results, so the unredacted output remains visible to the model.

- **Impact:** Secret and PII redaction in Bash output is bypassed. The model sees the original unredacted content.
- **Workaround:** Use `block` action mode instead of `warn`/`log-only` for secrets and PII to prevent the tool call entirely. Directory rules can also block access to sensitive paths before Bash executes.
- **Upstream:** [anthropics/claude-code#64326](https://github.com/anthropics/claude-code/issues/64326)

#### PreToolUse skips image/binary file reads

When Claude Code reads an image or binary file, the `PreToolUse` hook does not fire or does not include the file content in a scannable format. This prevents ai-guardian from scanning images for embedded secrets or PII.

- **Impact:** Image-based secret and PII scanning (`image_secret`, `image_pii` violation types) cannot enforce on binary reads. The "Caution" rating in the coverage matrix reflects this.
- **Workaround:** None. Use directory rules to block access to directories containing sensitive images.
- **Upstream:** [anthropics/claude-code#62639](https://github.com/anthropics/claude-code/issues/62639)

#### Skill invocations bypass permission hooks

When Claude Code invokes a skill (slash command), the skill's tool calls do not trigger `PreToolUse` hooks. This means ai-guardian's tool permission rules, directory blocking, SSRF protection, and other PreToolUse-based enforcement are bypassed for tool calls made within a skill.

- **Impact:** Tool permission enforcement, directory blocking, SSRF protection, secret scanning, and prompt injection detection are all bypassed for tool calls originating from skill invocations.
- **Workaround:** None. Audit skills installed in the project and limit skill access to trusted sources.
- **Upstream:** [anthropics/claude-code#66446](https://github.com/anthropics/claude-code/issues/66446)

#### Tool result transform hook missing

Claude Code does not provide a hook event that allows modifying tool results before they are shown to the model. The `PostToolUse` hook can inspect output but cannot reliably transform it (see the `updatedToolOutput` issue above for Bash).

- **Impact:** Content sanitization (stripping detection patterns, redacting matched text) cannot be applied to tool results before the model processes them. Warn-mode messages may leak detection patterns into the model context.
- **Workaround:** ai-guardian strips detection patterns from warn/log-only messages (see [#1327](https://github.com/RedHatProductSecurity/ai-guardian/issues/1327)), but this only covers ai-guardian's own messages, not arbitrary tool output.
- **Upstream:** [anthropics/claude-code#18653](https://github.com/anthropics/claude-code/issues/18653)

### Image scanning (all agents)

Claude Code binary file reads bypass hooks — image content may not pass through PreToolUse in a scannable format. Image scanning works best when images are base64-encoded in tool output, not when read as raw binary. See [#801](https://github.com/RedHatProductSecurity/ai-guardian/issues/801) for tracking.

### Transcript scanning availability

Claude Code exposes the conversation transcript to hooks via `UserPromptSubmit` (JSONL file). OpenCode and Cursor store sessions in SQLite databases; Cline stores conversations as JSON arrays in per-task directories; Windsurf stores Cascade transcripts as JSONL step files; ai-guardian reads them directly to scan for secrets and PII. Copilot CLI and Codex store JSONL transcripts at known default locations; ai-guardian discovers these paths via the adapter when the IDE does not provide a `transcript_path` in hook data. Copilot Chat for VS Code stores sessions as JSONL delta journal files in VS Code's `workspaceStorage/*/chatSessions/` directories. AiderDesk stores Markdown chat history at `.aider.chat.history.md` in the project root. OpenClaw stores JSONL transcripts at `~/.openclaw/transcripts/`.

Transcript scanning uses a polymorphic `TranscriptAdapter` interface (`scanners/transcript/base.py`). Each IDE format has its own adapter that implements `can_scan()` and `scan_incremental()`.

| Agent | Format | Default Path |
|-------|--------|-------------|
| Claude Code | JSONL | Provided by IDE in hook data |
| Cursor | SQLite | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` |
| OpenCode | SQLite | `~/.opencode/sessions/*.db` |
| Copilot CLI | JSONL | `~/.copilot/session-state/events.jsonl` |
| Codex | JSONL | `~/.codex/sessions/YYYY/MM/DD/*.jsonl` |
| Cline / ZooCode | JSON array | `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/tasks/<task_id>/api_conversation_history.json` |
| Windsurf | JSONL | `~/.windsurf/transcripts/{trajectory_id}.jsonl` |
| Copilot Chat (VS Code) | JSONL (delta journal) | `~/Library/Application Support/Code/User/workspaceStorage/*/chatSessions/*.jsonl` |
| Kiro | JSONL | `~/.kiro/sessions/cli/{session_id}.jsonl` |
| AiderDesk | Markdown | `.aider.chat.history.md` (project root) |
| OpenClaw | JSONL | `~/.openclaw/transcripts/YYYY-MM-DD/{session}/transcript.jsonl` |
| Copilot Chat (VS Code) | JSONL delta journal | `workspaceStorage/*/chatSessions/*.jsonl` |

Agents not listed above do not have transcript scanning support.

#### Augment Code — transcript scanning not currently feasible

Augment Code (Auggie CLI) stores conversation sessions server-side, not as local files. The only local files under `~/.augment/` are authentication (`session.json`), settings (`settings.json`), commands, and rules. Augment also does not implement a `UserPromptSubmit` hook event (only PreToolUse, PostToolUse, Stop, SessionStart, SessionEnd), and transcript scanning requires the PROMPT event to trigger. This can be revisited if Augment exposes local session files or adds a UserPromptSubmit-equivalent hook.

### Crush (Charmbracelet) — PreToolUse only

Crush currently implements only the `PreToolUse` hook event. PostToolUse, UserPromptSubmit, and other events are proposed but not yet available (see their `docs/hooks/FUTURE.md`). This means post-tool redaction, prompt scanning, and transcript scanning are not enforced. ai-guardian's MCP advisory server provides supplementary coverage.

Crush uses the FSL-1.1-MIT license (Functional Source License) — not OSI-approved open source. The license auto-converts to MIT on the second anniversary of each release. ai-guardian's integration (writing hook configs and adapters) is unaffected.

### MCP-only agents

Junie and any future MCP-only agents rely on the agent voluntarily calling ai-guardian's MCP tools. There is no enforcement mechanism — if the agent ignores the advisory, the violation is not blocked. MCP-only agents also cannot perform post-tool redaction or tool permission enforcement.

## Agent Confidence Levels

Testing depth varies by agent. Confidence reflects how thoroughly the hook adapter has been validated in real-world usage.

| Agent | Confidence | Reason |
|---|---|---|
| Claude Code | High | Extensively tested in production |
| Cursor | High | Extensively tested in production |
| Copilot | Medium | Tested but limited UserPromptSubmit |
| Gemini CLI | Low | Hook format implemented but limited testing |
| Codex | Low | Hook format implemented but limited testing |
| Windsurf | Low | Hook format implemented but limited testing |
| Cline / ZooCode | Low | Hook format implemented but limited testing |
| Augment Code | Low | Hook format implemented but limited testing |
| Kiro | Low | Hook format implemented but limited testing |
| Junie | Low | MCP only, no hook enforcement |
| AiderDesk | Low | Extension-based, limited testing |
| OpenClaw | Low | Plugin-based, limited testing |
| OpenCode | Low | Plugin-based, limited testing |
| Crush | Low | Compatible with Claude Code format; only PreToolUse available |

## Community Testing Feedback

For agents marked **Low confidence**, we implemented the hook adapter based on available documentation but could not fully test all scenarios. If you use ai-guardian with these agents, please report:

- Which violation types work correctly
- Which violation types fail or behave unexpectedly
- Any hook format differences from documentation

Report via [GitHub Discussions](https://github.com/RedHatProductSecurity/ai-guardian/discussions) or [Issues](https://github.com/RedHatProductSecurity/ai-guardian/issues).

## Hook Event Name Mapping

Each agent uses different event names. The adapter layer normalizes these.

| Concept | Claude Code | Copilot | Cursor | Windsurf | Gemini CLI | Cline | Kiro | OpenCode | Crush |
|---------|------------|---------|--------|----------|-----------|-------|------|----------|-------|
| Session start | `SessionStart` | N/A | N/A | N/A | `SessionStart` | N/A | N/A | N/A | N/A |
| Before tool | `PreToolUse` | `preToolUse` | `beforeShellExecution` | `pre_run_command` | `BeforeTool` | `PreToolUse` | `pre_tool_use` | `tool.execute.before` | `PreToolUse` |
| After tool | `PostToolUse` | `postToolUse` | `postToolUse` | `post_run_command` | `AfterTool` | `PostToolUse` | `post_tool_use` | `tool.execute.after` | N/A (proposed) |
| User prompt | `UserPromptSubmit` | `userPromptSubmitted` | `beforeSubmitPrompt` | `pre_user_prompt` | `BeforeAgent` | `UserPromptSubmit` | `prompt_submit` | `message.submit` | N/A (proposed) |

## Response Format Differences

| Agent | Blocking Mechanism | Block Response |
|-------|-------------------|----------------|
| Claude Code | JSON `hookSpecificOutput.permissionDecision` | `{"hookSpecificOutput": {"permissionDecision": "deny"}}` |
| Cursor | JSON `decision`/`permission` field | `{"decision": "deny", "reason": "..."}` |
| GitHub Copilot | JSON (PreToolUse) or exit code 2 | `{"permissionDecision": "deny"}` |
| Gemini CLI | JSON `decision` field | `{"decision": "deny", "reason": "..."}` |
| Cline | JSON `cancel` field | `{"cancel": true, "reason": "..."}` |
| Kiro | Exit code 2 (PreToolUse) or 1 (other) + stderr | stderr = error message |
| Windsurf | Exit code 2 + stderr | stderr = error message |
| Codex | Same as Claude Code | Same as Claude Code |
| OpenCode | Same as Claude Code | Same as Claude Code |
| Crush | Same as Claude Code | Same as Claude Code |

## Agent-Facing Message Delivery

When ai-guardian detects a non-blocking issue (warn/log mode) or injects security rules, the message must reach both the user and the AI agent. Agent-facing fields carry warn/log-only messages and, for PreToolUse deny responses, a sanitized block reason so the agent can report why the operation was blocked.

**PreToolUse deny**: The agent continues after a PreToolUse deny (it tries a different approach), so it receives a sanitized summary via the agent-facing field (e.g., `"Operation blocked by ai-guardian: secret detected"`). The sanitized message contains only the violation type — no patterns, regex, or matched text. PostToolUse and Prompt blocks do NOT inject agent context since the agent stops after those.

| Agent | User-facing field | Agent-facing field | Events | Status |
|-------|------------------|-------------------|--------|--------|
| Claude Code | `systemMessage` | `hookSpecificOutput.additionalContext` | All (incl. PreToolUse deny) | Confirmed |
| Augment | `systemMessage` | `hookSpecificOutput.additionalContext` | All (incl. PreToolUse deny) | Confirmed (inherits Claude Code) |
| Codex | `systemMessage` | `hookSpecificOutput.additionalContext` | All (incl. PreToolUse deny) | Confirmed (inherits Claude Code) |
| OpenCode | `systemMessage` | `hookSpecificOutput.additionalContext` | All (incl. PreToolUse deny) | Best-effort (bridge plugin) |
| Crush | `systemMessage` | `hookSpecificOutput.additionalContext` | PreToolUse (incl. deny) | Best-effort (compatible format) |
| Cursor | `user_message` | `agent_message` | All (incl. PreToolUse deny) | Confirmed |
| Gemini CLI | `systemMessage` | `additionalContext` | Prompt, PostToolUse, PreToolUse deny (best-effort) | Confirmed |
| Cline | `errorMessage` (block) | `contextModification` | All (incl. block) | Confirmed |
| Kiro | stderr (errors) | stdout | Prompt, PreToolUse | Confirmed (process I/O) |
| Copilot | `permissionDecisionReason` (deny) | `additionalContext` | PreToolUse (incl. deny), PostToolUse | Best-effort (see bugs) |
| Windsurf | stderr (exit 2) | stdout (exit 0) | PreToolUse (block) | Limited |

**Confirmed** — documented in the agent's hook protocol and verified to reach the AI model. **Best-effort** — field exists in spec but has known implementation bugs. **Limited** — only blocking responses have a confirmed agent channel.

### Known Limitations

- **Gemini CLI PreToolUse**: `additionalContext` is not supported for BeforeTool responses — only BeforeAgent (Prompt) and AfterTool (PostToolUse). Non-blocking PreToolUse messages display to the user via `systemMessage` only.
- **Copilot CLI**: `additionalContext` is documented for PreToolUse and PostToolUse but is silently dropped due to bugs ([#2585](https://github.com/github/copilot-cli/issues/2585), [#2980](https://github.com/github/copilot-cli/issues/2980)). ai-guardian sends it anyway so it works automatically when the bugs are fixed.
- **Windsurf**: No non-blocking agent-visible channel exists. Only stderr on exit code 2 (blocking) reaches the Cascade agent. Non-blocking warn messages are written to stdout as best-effort.
- **OpenCode**: The bridge plugin translates to Claude Code format, but native OpenCode plugins do not support `additionalContext`. Agent-visible message delivery depends on the bridge implementation.

## Architecture

### Adapter Layer

Each agent has a dedicated adapter class in `src/ai_guardian/hook_adapters/`:

```
hook_adapters/
├── __init__.py          # Registry: detect_adapter(), get_adapter_by_ide_type()
├── base.py              # HookAdapter ABC + NormalizedHookInput dataclass
├── claude_code.py       # Claude Code (default fallback)
├── cursor.py            # Cursor IDE
├── copilot.py           # GitHub Copilot
├── codex.py             # OpenAI Codex (extends ClaudeCodeAdapter)
├── windsurf.py          # Windsurf (extends ClaudeCodeAdapter)
├── gemini.py            # Google Gemini CLI
├── cline.py             # Cline / ZooCode
├── kiro.py              # Kiro + AiderDesk + OpenClaw
├── augment.py           # Augment Code (extends ClaudeCodeAdapter)
├── opencode.py          # OpenCode (extends ClaudeCodeAdapter)
├── crush.py             # Crush (extends ClaudeCodeAdapter)
└── junie.py             # Junie (MCP-only placeholder)
```

### How Detection Works

1. Check `AI_GUARDIAN_IDE_TYPE` environment variable (explicit override)
2. Try each adapter's `can_handle(hook_data)` method in priority order
3. Fall back to Claude Code adapter (handles PascalCase and all unknown formats)

Detection priority checks unique fields:
- `clineVersion` → Cline
- `transcript_path` → Gemini CLI
- `agent_action_name` → Windsurf
- `toolName` → GitHub Copilot
- `cursor_version` → Cursor
- `kiro_hook_type` → Kiro
- `is_mcp_tool` → Augment Code
- `opencode_version` → OpenCode
- `CRUSH` env var or `event`+`tool_input` → Crush

### NormalizedHookInput

All adapters produce a `NormalizedHookInput` dataclass with consistent fields:

| Field | Type | Description |
|-------|------|-------------|
| `event` | `HookEvent` | Normalized event (PROMPT, PRE_TOOL_USE, POST_TOOL_USE) |
| `tool_name` | `str` | Canonical tool name (e.g., "Bash", "Read") |
| `tool_input` | `dict` | Tool parameters |
| `file_path` | `str` | File being accessed |
| `working_dir` | `str` | Working directory |
| `session_id` | `str` | Session correlation ID |
| `tool_use_id` | `str` | Tool use correlation ID |
| `prompt_text` | `str` | User prompt text |
| `tool_response` | `Any` | Tool output (PostToolUse) |
| `transcript_path` | `str` | Path to conversation transcript |
| `raw_data` | `dict` | Original hook data |

## Setup

Install hooks for any supported agent:

```bash
ai-guardian setup --ide <agent-name>
```

Agent names: `claude`, `cursor`, `copilot`, `codex`, `windsurf`, `gemini`, `cline`, `zoocode`, `kiro`, `augment`, `aiderdesk`, `openclaw`, `opencode`, `crush`, `junie`

### Config File Locations

| Agent | Config Path |
|-------|------------|
| Claude Code | `~/.claude/settings.json` |
| Cursor | `~/.cursor/hooks.json` |
| GitHub Copilot | `~/.github/hooks/hooks.json` |
| OpenAI Codex | `~/.codex/hooks.json` |
| Windsurf | `~/.codeium/windsurf/hooks.json` |
| Gemini CLI | `~/.gemini/settings.json` |
| Cline / ZooCode | `.clinerules/hooks/` (scripts) |
| Kiro | `.kiro/hooks/` (scripts) |
| Augment Code | `~/.augment/settings.json` |
| OpenCode | `~/.config/opencode/plugins/ai-guardian.ts` (plugin) |
| Crush | `.crush.json` (project) or `~/.config/crush/crush.json` (global) |
| Junie | `.junie/guidelines` (MCP only) |

## Per-Agent Deep-Dive Guides

| Agent | Guide | Description |
|-------|-------|-------------|
| GitHub Copilot | [GITHUB_COPILOT.md](GITHUB_COPILOT.md) | Detailed setup, troubleshooting, response format, enterprise deployment |
| Aider (CLI) | [AIDER.md](AIDER.md) | Git pre-commit hook integration (not hook adapter — scans at commit time) |
| AiderDesk | [AIDERDESK.md](AIDERDESK.md) | TypeScript extension setup, npm install, hot reload |

## Adding a New Agent

1. Create `src/ai_guardian/hook_adapters/<agent>.py` implementing `HookAdapter`
2. Add the adapter to `ADAPTER_CLASSES` in `hook_adapters/__init__.py`
3. Add setup config to `IDESetup.IDE_CONFIGS` in `setup/hooks.py`
4. Add tests in `tests/unit/test_<agent>_support.py`
5. Update the tables in this document:
   - Supported Agents table
   - Hook Capability Matrix
   - Violation Type Coverage Matrix (or note coverage matches an existing agent)
   - Agent Confidence Levels table
   - Hook Event Name Mapping
   - Response Format Differences
   - Config File Locations

## Adding a New Violation Type

1. Implement the detector in the appropriate module
2. Add a row to the **Violation Type Coverage Matrix** with the required hooks and per-agent coverage
3. If the violation has agent-specific limitations, add a subsection under **Known Limitations**
4. Add tests covering the new violation type across adapters
