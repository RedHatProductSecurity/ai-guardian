# Agent Support

AI Guardian protects multiple AI coding agents through a unified hook adapter architecture. Each agent gets a dedicated adapter that normalizes its hook format into a common internal model, so the core scanning pipeline stays agent-agnostic.

This document is the capability reference: it records what each integration
supports and where known limitations remain. Use the
[IDE/Agent Integration Checklist](IDE_INTEGRATION_CHECKLIST.md) for the
implementation, test, documentation, and release workflow when adding or
changing an integration.

The canonical cross-cutting registry is
[`SUPPORTED_IDE_REGISTRY`](../src/ai_guardian/ide_registry.py). The executable
parity contract in [`tests/unit/test_ide_registry.py`](../tests/unit/test_ide_registry.py)
checks that this support list agrees with adapter aliases, setup modes,
managed events, MCP/rules and transcript/session registries, installer
surfaces, and release-readiness matrices.

### Codex and ChatGPT desktop scope

`OpenAI Codex (CLI + Desktop)` means Codex CLI and **Codex mode** in the
ChatGPT desktop app. It does not include regular ChatGPT mode in that app.
AI Guardian's Codex lifecycle hooks currently run only for the Codex hook
surface, so regular ChatGPT mode is not protected by those hooks. The ChatGPT
desktop app, Codex CLI, and Codex IDE extension can share MCP configuration,
but shared MCP availability is separate from hook enforcement and does not
extend Codex lifecycle hooks to regular ChatGPT mode. See the official
[Codex environments](https://learn.chatgpt.com/docs/environments/modes),
[Codex hooks](https://learn.chatgpt.com/docs/hooks), and
[MCP](https://learn.chatgpt.com/docs/extend/mcp) documentation for the
upstream distinction.

## Supported Agents

| Agent | Setup Command | Hooks | MCP | Status |
|-------|--------------|-------|-----|--------|
| Claude Code | `--ide claude` | Full | Full | **Complete** |
| Cursor desktop / local CLI | `--ide cursor` | 6 managed events (21 recognized) | User-level `~/.cursor/mcp.json` (`stdio`); Cloud Agents use dashboard/API MCP | **Complete locally; project hooks available for cloud workspaces** |
| GitHub Copilot | `--ide copilot` | Full | N/A | **Complete** |
| OpenAI Codex (CLI + Desktop) | `--ide codex` | 5 managed events (12 recognized) | Global `config.toml` | **Complete for Codex CLI and desktop Codex mode** |
| Windsurf | `--ide windsurf` | Full | N/A | **Complete** |
| Gemini CLI | `--ide gemini` | Full | N/A | **Complete** |
| Cline / ZooCode | `--ide cline` | Full | N/A | **Complete** |
| Kiro (AWS) | `--ide kiro` | Full | N/A | **Complete** |
| Augment Code | `--ide augment` | Full | N/A | **Complete** |
| AiderDesk | `--ide aiderdesk` | Extension | N/A | **Complete** |
| OpenClaw | `--ide openclaw` | Plugin | N/A | **Complete** |
| OpenCode | `--ide opencode` | Plugin | N/A | **Complete** |
| Antigravity CLI (agy) | `--ide antigravity` | Partial | Full | **Complete** |
| Crush (Charmbracelet) | `--ide crush` | Partial | Full | **Complete** |
| Junie (JetBrains) | `--ide junie` | N/A | Full | **MCP-only** |

## Coverage-to-test matrix

This matrix is keyed by the canonical registry rather than by display-name
groupings. Shared implementations still have one row per public key, so a
Cline/ZooCode or Kiro/AiderDesk/OpenClaw change cannot hide a missing setup,
health, or documentation path. The common hook contract includes allow, block,
warning, output transformation, malformed input, timeout/process failure, and
response-shape assertions where the host exposes that surface. The isolated
E2E test invokes every managed event; plugin/extension rows use generated
bridge contracts because their host SDKs are not repository dependencies.

| Registry key | Adapter/setup evidence | Transcript/session evidence | E2E and scope evidence |
|---|---|---|---|
| `claude` | Shared adapter, setup merge/reconciliation, hook pipeline, UX setup contracts | JSONL path supplied by hook; browser session adapter | Isolated all-managed-event matrix; user scope and doctor/tray health |
| `cursor` | Dedicated adapter, six managed events, fail-closed decision hooks, project/cloud setup | Cursor SQLite; browser session adapter | Isolated event matrix plus recognized-event/failure checks; user vs project/cloud MCP scope |
| `copilot` | Dedicated adapter, prompt/pre-tool response contract and no-local-MCP boundary | Copilot CLI JSONL and VS Code delta journal; browser session adapter | Isolated managed-event matrix; command-hook health |
| `codex` | Dedicated adapter, five managed events, layered config/MCP reconciliation, Codex UX contracts | Codex JSONL default-path discovery; browser session adapter | Isolated event matrix; CLI/desktop Codex-mode scope explicitly separated from regular ChatGPT |
| `windsurf` | Dedicated adapter and nine managed command-hook events | Windsurf JSONL; browser session adapter | Isolated all-managed-event matrix; command-hook process I/O |
| `gemini` | Dedicated adapter, SessionStart/BeforeAgent/BeforeTool/AfterTool mapping | Explicit-path JSONL; browser session adapter | Isolated all-managed-event matrix; command-hook health |
| `cline` | Cline adapter and script-hook setup/reconciliation | Cline JSON-array transcript; shared Cline session adapter | Isolated script-event matrix; project-local hook scope |
| `zoocode` | ZooCode key mapped to the shared Cline adapter and script contract | Shared Cline JSON-array/session evidence | Isolated script-event matrix; explicit alias and shared-layout coverage |
| `kiro` | Dedicated Kiro adapter and script-hook setup/reconciliation | Kiro JSONL; browser session adapter | Isolated script-event matrix; project-local hook scope |
| `aiderdesk` | Extension bridge/package registration and shared Kiro response boundary | AiderDesk Markdown transcript; no hook session grouping | Generated bridge/registration E2E boundary; host SDK runtime is an explicit CI exclusion |
| `openclaw` | Plugin bridge/package registration, rules setup, and shared Kiro response boundary | OpenClaw JSONL; no hook session grouping | Generated bridge/registration E2E boundary; plugin SDK runtime is an explicit CI exclusion |
| `opencode` | Plugin bridge, SQLite/session setup, and Claude-compatible response boundary | OpenCode SQLite; browser session adapter | Generated plugin/registration E2E boundary; project/user config reconciliation |
| `augment` | Dedicated adapter/tool-name mapping and Pre/Post command-hook setup | No local transcript; server-side storage documented | Isolated Pre/Post matrix; local-hook and no-local-transcript limitation |
| `crush` | Dedicated adapter and PreToolUse-only setup/response contract | No transcript/session adapter; upstream surface is partial | Isolated PreToolUse matrix; Windows generated-hook structure and partial-surface limitation |
| `junie` | MCP/rules setup and explicit no-hook adapter placeholder | No transcript/session adapter | Isolated MCP-only registration/health boundary; advisory, non-enforcing behavior |

The implementation checklist defines the minimum tests that must be added for
future integrations. For this repository, the main evidence paths are
`tests/unit/test_ide_registry.py`, `tests/unit/test_hook_adapters.py`,
`tests/unit/test_setup.py`, the per-agent support/transcript tests,
`tests/unit/test_auto_setup.py`, `tests/unit/test_cli_ide_setup.py`,
`tests/test_install_script.py`, `tests/ux/`, and
`tests/integration/test_ide_hooks_e2e.py`.

## Hook Capability Matrix

| Agent | SessionStart | UserPromptSubmit | PreToolUse | PostToolUse | BeforeReadFile | PostCompact | SessionEnd |
|-------|-------------|-----------------|------------|-------------|----------------|-------------|------------|
| Claude Code | Yes | Yes | Yes | Yes | N/A | Yes | Yes |
| Cursor | N/A | Yes | Yes | Yes | Yes | N/A | N/A |
| GitHub Copilot | N/A | Yes | Yes | N/A | N/A | N/A | N/A |
| OpenAI Codex (CLI + Desktop) | N/A | Yes | Yes | Yes | N/A | Yes | Yes |
| Windsurf | N/A | Yes | Yes | Yes | Yes | N/A | N/A |
| Gemini CLI | Yes | Yes (BeforeAgent) | Yes | Yes | N/A | N/A | N/A |
| Cline / ZooCode | N/A | Yes | Yes | Yes | N/A | N/A | N/A |
| Kiro | N/A | Yes | Yes | Yes | N/A | N/A | N/A |
| Augment Code | N/A | N/A | Yes | Yes | N/A | N/A | N/A |
| OpenCode | N/A | Yes (chat.message) | Yes | Yes | N/A | N/A | N/A |
| Antigravity CLI | N/A | Yes (PreInvocation) | Yes | Yes (no output) | N/A | N/A | N/A |
| Crush | N/A | N/A | Yes | N/A | N/A | N/A | N/A |
| Junie | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

The Codex row applies to Codex CLI and desktop Codex mode only. Regular
ChatGPT mode does not run these Codex lifecycle hooks.

## Hook Latency Support Matrix

Latency tracking is implemented in the shared hook pipeline after each
adapter normalizes an invocation. When `latency_tracking.enabled` is `true`,
each invocation that reaches `process_hook_data()` produces one entry in
`latency.jsonl`, including lifecycle events that return without content
scanning. Reports store the lower-case enum IDs (for example, `prompt` and
`pretooluse`); source-specific display names are shown in this matrix and the
integration guides.

| Integration | Collection surface | Timed normalized events | Latency status |
|-------------|--------------------|-------------------------|----------------|
| Claude Code | Command hooks | SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, PostCompact, SessionEnd | Supported |
| Cursor desktop / local CLI | Command hooks | 6 managed Cursor events; other upstream events are normalized when explicitly configured | Supported |
| GitHub Copilot | Command hooks | UserPromptSubmit, PreToolUse | Supported |
| OpenAI Codex (CLI + Desktop) | Command hooks | UserPromptSubmit, PreToolUse, PostToolUse, PostCompact, SessionEnd | Supported (five managed events) |
| Windsurf | Command hooks | UserPromptSubmit, BeforeReadFile, PreToolUse, PostToolUse | Supported |
| Gemini CLI | Command hooks | SessionStart, UserPromptSubmit, PreToolUse, PostToolUse | Supported |
| Cline / ZooCode | Script hooks | UserPromptSubmit, PreToolUse, PostToolUse | Supported |
| Kiro | Script hooks | UserPromptSubmit, PreToolUse, PostToolUse | Supported |
| Augment Code | Command hooks | PreToolUse, PostToolUse | Supported |
| Antigravity CLI (agy) | Command hooks | PreInvocation, PreToolUse, PostToolUse | Supported (partial output surface) |
| AiderDesk | Extension | UserPromptSubmit, PreToolUse, PostToolUse | Supported |
| OpenClaw | Plugin | UserPromptSubmit, PreToolUse, PostToolUse, Stop | Supported |
| OpenCode | Plugin | UserPromptSubmit, PreToolUse, PostToolUse, Stop | Supported |
| Crush | Command hooks | PreToolUse | Supported (partial hook surface) |
| Junie | MCP | None | MCP-only; no hook latency |
| Aider CLI | Git pre-commit hook | None | Commit-time scan; no per-interaction hook latency |

Codex setup installs five managed events. The adapter also records timing for
`SessionStart`, `PermissionRequest`, `PreCompact`, `Interrupt`, `SubagentStart`,
`SubagentStop`, and `Stop` when a user-configured hook invokes AI Guardian for
those recognized events. These events are recognized but are not installed or
health-checked by `ai-guardian setup`.

Junie's MCP calls and Aider CLI's commit-time `ai-guardian scan` do not enter
the hook pipeline, so they do not create latency entries. A paused daemon also
does not create entries because it intentionally skips hook processing.

## Protection Level by Hook Availability

| Hooks Available | AI Guardian Capabilities |
|----------------|------------------------|
| **Full hooks** (Prompt + Pre + Post) | Secret scanning, PII detection, prompt injection, SSRF, directory blocking, config scanning, redaction, tool permissions |
| **Pre + Post only** (no Prompt) | All above except prompt scanning and transcript scanning |
| **MCP only** (no hooks) | Advisory checks only — check_path, check_command, check_mcp_trust, sanitize_text. No enforcement (agent must cooperate) |
| **None** | No protection available |

## Violation Type Coverage Matrix

Coverage per agent depends on which hooks are available. This table shows representative agents across the enforcement spectrum: full hooks + MCP, full hooks only, partial hooks, and MCP-only.

Antigravity's PostToolUse fires but carries no tool output, so post-tool redaction (`secret_redaction`) is not available there; pre-tool enforcement is unaffected.

Agents with full hook support not shown individually (Windsurf, Gemini CLI, Cline, Kiro, OpenCode) have the same coverage as Claude Code, minus MCP and minus UserPromptSubmit where applicable — see the [Hook Capability Matrix](#hook-capability-matrix) above. Copilot CLI and Codex support transcript scanning via adapter-resolved default paths (Issue #935).

| Violation Type | Requires | Claude Code | Cursor | Copilot | Antigravity | Junie (MCP) |
|---|---|---|---|---|---|---|
| secret_detected | Pre+Post | Enforce | Enforce | Enforce | Enforce | Advisory |
| secret_redaction | Post | Enforce | Enforce | Enforce | No (no tool output) | No |
| pii_detected | Pre+Post+Prompt | Enforce | Enforce | Partial | Partial | Advisory |
| directory_blocking | Pre | Enforce | Enforce | Enforce | Enforce | Advisory |
| tool_permission | Pre | Enforce | Enforce | Enforce | Enforce | No |
| prompt_injection | Pre+Prompt | Enforce | Enforce | Partial | Partial | Advisory |
| jailbreak_detected | Pre+Prompt | Enforce | Enforce | Partial | Partial | Advisory |
| ssrf_blocked | Pre | Enforce | Enforce | Enforce | Enforce | Advisory |
| config_file_exfil | Pre | Enforce | Enforce | Enforce | Enforce | No |
| secret_in_transcript | Prompt | Enforce | Enforce | Enforce | No | No |
| pii_in_transcript | Prompt | Enforce | Enforce | Enforce | No | No |
| image_secret | Pre | Caution | Caution | Caution | Caution | No |
| image_pii | Pre | Caution | Caution | Caution | Caution | No |
| offensive_language | Pre+Post | Enforce | Enforce | Partial | Partial | Advisory |
| canary_detected | Pre+Post+Prompt | Enforce | Enforce | Partial | Partial | Advisory |
| exfil_detection | Pre (Bash) | Enforce | Enforce | Partial | Enforce | Advisory |

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

### Correlating Hook Sessions with SDK Runs

The **Sessions** console page can group hook-based IDE activity with SDK traces.
SDK agents use the `run_id` from `RunContext`. A hook event may provide the same
value directly in its `run_id` field. Otherwise, a non-SDK agent can start with
the matching value in `AI_GUARDIAN_RUN_ID`:

```bash
export AI_GUARDIAN_RUN_ID="pipeline-123"
my-ide-agent
```

Use one stable, unique value for each logical pipeline. Sessions with matching
values are shown as one run; an unset or different value remains separate. The
**IDE Conversations** page remains the raw, IDE-specific conversation replay.

The daemon persists the resolved value by `session_id`, so later events and
daemon restarts retain the same correlation. Precedence is explicit hook-event
`run_id`, persisted session binding, hook-process `AI_GUARDIAN_RUN_ID`, then the
daemon environment as a legacy fallback. GUI IDEs that do not inherit shell
environment should provide `run_id` in their hook events when supported.

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

Agents not listed above do not have transcript scanning support.

### OpenAI Codex (CLI + Desktop)

The display label is intentionally scoped: AI Guardian supports the documented
Codex hook interface used by Codex CLI and Codex mode in ChatGPT desktop. The
official [Codex hooks documentation](https://learn.chatgpt.com/docs/hooks)
describes the same event names, command-hook payload, and layered discovery
model used by this adapter. Selecting regular ChatGPT mode in the desktop app
does not run these Codex lifecycle hooks, so it is not currently hook-enforced
by AI Guardian.

AI Guardian installs its five managed hooks in the Codex user layer at
`~/.codex/hooks.json`, or at `$CODEX_HOME/hooks.json` when `CODEX_HOME` is set.
Verification also reports the active project layer at `<repo>/.codex/` and
whether either `hooks.json` or inline `hooks` in `config.toml` is present.
Existing matcher groups, non-AI-Guardian commands, and their order are
preserved. Codex loads all matching layers, so project-local hooks remain
active alongside the user layer.

AI Guardian also registers its MCP server in Codex's global `config.toml` at
`~/.codex/config.toml`, or at `$CODEX_HOME/config.toml` when `CODEX_HOME` is
set, following the [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp).
The ChatGPT desktop app, Codex CLI, and IDE extension can share that MCP
configuration, but MCP availability is advisory and separate from lifecycle
hook enforcement. An MCP server being visible in regular ChatGPT mode does not
mean that AI Guardian's Codex hooks run there.
MCP setup is enabled by default and preserves unrelated global and project
configuration. A stale project-root `codex.json` entry is removed after the
global registration is written.
The tray's **Check hooks/MCP installation...** action checks hooks and MCP
registration separately and can repair a missing global MCP entry without
rewriting healthy Codex hooks.

#### Violation attribution

Violation records use `context.ide_type` for the stable integration identity,
independently of the response protocol. Codex CLI and Codex mode in ChatGPT
desktop both record `codex`, while Claude-compatible response formatting is
preserved. This identity does not indicate coverage for regular ChatGPT mode;
that mode is outside the current Codex hook enforcement path. Other adapters
that share Claude-compatible formatting use their own stable values, such as
`windsurf`, `augment`, `opencode`, and `crush`.
Payloads that do not identify an integration use `unknown` rather than being
attributed to Claude Code.

#### Codex event classification

The adapter recognizes every documented Codex lifecycle event. “Managed” means
AI Guardian installs and verifies the event. Other recognized events may be
configured by a user, but are not installed by `ai-guardian setup` and do not
count toward setup health until AI Guardian has a managed setup and enforcement
path for them.

| Codex event | Classification | AI Guardian behavior |
|---|---|---|
| `SessionStart` | Recognized, not managed | If configured by the user, scans active agent configuration files and can block on a detected threat. |
| `UserPromptSubmit` | Managed | Scans prompts, including prompt injection, secrets, PII, and transcript coverage. |
| `PreToolUse` | Managed | Enforces tool permissions and pre-tool content/security scanners. |
| `PermissionRequest` | Recognized, not managed | If configured by the user, applies the permission and security pipeline; denials use Codex’s nested decision shape. |
| `PostToolUse` | Managed | Scans tool results and applies post-tool handling/redaction where supported. |
| `PreCompact` | Recognized, not managed | If configured by the user, acknowledges the lifecycle event without inferring security-enforceable content or a decision. |
| `PostCompact` | Managed | Marks the session for security-context reinjection after compaction. |
| `SubagentStart` | Recognized, not managed | If configured by the user, acknowledges the lifecycle event without inferring security-enforceable content or a decision. |
| `SubagentStop` | Recognized, not managed | If configured by the user, acknowledges the lifecycle event without inferring security-enforceable content or a decision. |
| `Stop` | Recognized, not managed | If configured by the user, acknowledges the lifecycle event without inferring security-enforceable content or a decision. |
| `Interrupt` | Recognized, not managed | If configured by the user, acknowledges the lifecycle event without inferring security-enforceable content or a decision. |
| `SessionEnd` | Managed | Performs session cleanup. |

No event in this table is silently discarded when it is present in a user
configuration. Recognized-but-unmanaged events are intentionally not installed
or counted as required setup because they do not belong to AI Guardian's
managed hook contract.

If the target Codex user `config.toml` already contains inline hooks, or any
active Codex configuration layer is malformed, setup stops with a diagnostic
instead of writing a second competing representation. Fix the reported
configuration and rerun setup.

#### Augment Code — transcript scanning not currently feasible

Augment Code (Auggie CLI) stores conversation sessions server-side, not as local files. The only local files under `~/.augment/` are authentication (`session.json`), settings (`settings.json`), commands, and rules. Augment also does not implement a `UserPromptSubmit` hook event (only PreToolUse, PostToolUse, Stop, SessionStart, SessionEnd), and transcript scanning requires the PROMPT event to trigger. This can be revisited if Augment exposes local session files or adds a UserPromptSubmit-equivalent hook.

### Antigravity CLI (agy) — no tool output in PostToolUse

Antigravity configures hooks in `hooks.json` (`~/.gemini/config/hooks.json` globally,
`<workspace>/.agents/hooks.json` per project, or `plugins/<name>/hooks.json`). Its payload is
protojson camelCase and differs from every other supported agent: the tool call is nested under
`toolCall` (`{"name": ..., "args": {...}}`), and the response is flat
(`{"decision": "allow|deny|ask|force_ask", "reason": ...}`) rather than Claude Code's
`hookSpecificOutput.permissionDecision`.

The implementation follows the [official Antigravity hooks specification](https://www.antigravity.google/docs/hooks/).
AI Guardian does not bundle or link Antigravity code; it invokes the host's documented
command-hook interface. The default installation is user-scoped for hooks and MCP at
`~/.gemini/config/`; workspace hook setup is explicit and does not imply protection for
remote execution. The generated command-hook contract is platform-independent JSON
stdin/stdout, while the isolated runtime matrix executes on Ubuntu and shared setup
tests cover Windows path and script behavior.

**Every PreToolUse response must carry a decision.** Antigravity has no "no opinion" value — an
absent or unrecognised `decision` denies the tool call, and `{"decision": "none"}` is rejected with
`unsupported hook decision`. A clean check therefore returns `{"decision": "ask"}`, which hands the
choice back to Antigravity's own permission prompt and respects its "Always Allow" cache, so
ai-guardian never silently widens the user's existing permissions. The trade-off: in
non-interactive `-p` mode `ask` resolves to a denial, so headless runs need an Antigravity
permission allowlist.

**Event resolution.** Antigravity does not name the event in the payload, and — contrary to its own
documentation, which describes PostToolUse as carrying only `stepIdx` and an optional `error` —
the PreToolUse and PostToolUse payloads are near-identical:

```
PreToolUse   {"stepIdx": 3, "toolCall": {...}}
PostToolUse  {"stepIdx": 3, "toolCall": {...}, "error": ""}
```

The generated hook commands therefore pass `--hook-event <Event>`, which is stamped into the hook
data so it survives forwarding to the ai-guardian daemon (a separate, long-lived process — an
environment variable would neither reach it nor stay correct between invocations). Hand-written
configs fall back to inference, which keys off `error` (present on every PostToolUse payload,
empty string on success).

PostToolUse fires normally, but the payload carries **no tool output** — only the originating
`toolCall` and its arguments. Post-tool output scanning and redaction are therefore not possible
on Antigravity; the command itself can still be inspected. `PreInvocation` (fired before each model
call) carries the security-instruction injection via `injectSteps`.

Antigravity supplies `transcriptPath`, which AI Guardian preserves in the normalized session
input, but no transcript reader is registered: the incremental transcript contract is not part
of the supported integration and transcript scanning is therefore not claimed.

The MCP advisor is registered in the global `~/.gemini/config/mcp_config.json`. Project hook
configuration does not create a project MCP file; any remote or team-level MCP registration
must be managed through Antigravity's own deployment surface.

Tool names are the lowercased `CORTEX_STEP_TYPE_*` enum with the prefix stripped
(`run_command`, `view_file`, `find_by_name`, `list_dir`, `call_mcp_tool`, …) and are mapped onto
canonical Claude Code names so existing pattern and permission rules apply unchanged. MCP calls
arrive as `call_mcp_tool` with the server and tool in the arguments, and are rebuilt as
`mcp__<server>__<tool>` so MCP restriction and `mcp__*` rules keep applying.

Only `matcher: "*"` in the grouped form is honoured for tool-scoped events. An empty matcher, a
named matcher, and the flat handler list documented upstream were all observed not to fire.

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
| Cursor desktop / local CLI | Medium | Desktop behavior retained; managed local CLI/agent events, MCP, failure handling, and setup health are covered by focused tests |
| Copilot | Medium | Tested but limited UserPromptSubmit |
| Gemini CLI | Low | Hook format implemented but limited testing |
| Antigravity CLI | Medium | Tested — PreToolUse blocking, PreInvocation injection and MCP verified against `agy`; no PostToolUse output available |
| Codex | Medium | Five managed hooks are set up and health-checked; the adapter also recognizes the remaining documented lifecycle events when configured by the user |
| Windsurf | Low | Hook format implemented but limited testing |
| Cline / ZooCode | Low | Hook format implemented but limited testing |
| Augment Code | Low | Hook format implemented but limited testing |
| Kiro | Low | Hook format implemented but limited testing |
| Junie | Low | MCP only, no hook enforcement |
| AiderDesk | Low | Extension-based, limited testing |
| OpenClaw | Low | Plugin-based, limited testing |
| OpenCode | Medium | Tested — plugin hooks install and work correctly |
| Crush | Low | Compatible with Claude Code format; only PreToolUse available |

## Community Testing Feedback

For agents marked **Low confidence**, we implemented the hook adapter based on available documentation but could not fully test all scenarios. If you use ai-guardian with these agents, please report:

- Which violation types work correctly
- Which violation types fail or behave unexpectedly
- Any hook format differences from documentation

Report via [GitHub Discussions](https://github.com/RedHatProductSecurity/ai-guardian/discussions) or [Issues](https://github.com/RedHatProductSecurity/ai-guardian/issues).

## Hook Event Name Mapping

Each agent uses different event names. The adapter layer normalizes these.

| Concept | Claude Code | Copilot | Cursor | Windsurf | Gemini CLI | Cline | Kiro | OpenCode | Crush | Antigravity |
|---------|------------|---------|--------|----------|-----------|-------|------|----------|-------|-------------|
| Session start | `SessionStart` | N/A | `sessionStart` (recognized; not installed) | N/A | `SessionStart` | N/A | N/A | N/A | N/A | N/A |
| Before tool | `PreToolUse` | `preToolUse` | `preToolUse`, `beforeShellExecution`, `beforeMCPExecution`, `subagentStart` | `pre_run_command` | `BeforeTool` | `PreToolUse` | `pre_tool_use` | `tool.execute.before` | `PreToolUse` | `PreToolUse` |
| Before file read | N/A | N/A | `beforeReadFile`, `beforeTabFileRead` | `pre_read_code` | N/A | N/A | N/A | N/A | N/A | N/A |
| After tool | `PostToolUse` | `postToolUse` | `postToolUse`, `afterShellExecution`, `afterMCPExecution` | `post_run_command` | `AfterTool` | `PostToolUse` | `post_tool_use` | `tool.execute.after` | N/A (proposed) | `PostToolUse` |
| Tool failure | N/A | N/A | `postToolUseFailure` | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| User prompt | `UserPromptSubmit` | `userPromptSubmitted` | `beforeSubmitPrompt` | `pre_user_prompt` | `BeforeAgent` | `UserPromptSubmit` | `prompt_submit` | `message.submit` | N/A (proposed) | `PreInvocation` |
| After edit | N/A | N/A | `afterFileEdit`, `afterTabFileEdit` | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| Lifecycle / observation | `SessionStart`, `SessionEnd`, `Stop`, `SubagentStop` | N/A | `sessionStart`, `sessionEnd`, `subagentStop`, `preCompact`, `stop`, `afterAgentResponse`, `afterAgentThought`, `workspaceOpen` | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

Cursor's default managed user-level setup installs these six events:
`beforeSubmitPrompt`, `beforeReadFile`, `beforeShellExecution`, `preToolUse`,
`afterShellExecution`, and `postToolUse`. The adapter recognizes additional
documented Cursor events when a user has configured them, but they are not
AI Guardian hooks and are never reported as missing setup.
Cursor command hooks receive JSON on stdin and return JSON on stdout; decision
events use `permission: allow|deny`, while post-tool MCP redaction uses
`updated_mcp_tool_output: {"modified": "..."}`. Failure hooks return an empty
JSON object so error payloads are not echoed.

## Response Format Differences

| Agent | Blocking Mechanism | Block Response |
|-------|-------------------|----------------|
| Claude Code | JSON `hookSpecificOutput.permissionDecision` | `{"hookSpecificOutput": {"permissionDecision": "deny"}}` |
| Cursor desktop / CLI | JSON `permission` field for decision hooks; JSON transform field for MCP post-hooks | `{"permission": "deny", "user_message": "...", "agent_message": "..."}`; MCP output uses `updated_mcp_tool_output` |
| GitHub Copilot | JSON (PreToolUse) or exit code 2 | `{"permissionDecision": "deny"}` |
| Gemini CLI | JSON `decision` field | `{"decision": "deny", "reason": "..."}` |
| Cline | JSON `cancel` field | `{"cancel": true, "reason": "..."}` |
| Kiro | Exit code 2 (PreToolUse) or 1 (other) + stderr | stderr = error message |
| Windsurf | Exit code 2 + stderr | stderr = error message |
| Codex | Same as Claude Code for shared events; `PermissionRequest` uses the Codex nested deny decision | Pre-tool denials use `hookSpecificOutput.permissionDecision`; permission requests use `hookSpecificOutput.decision.behavior = "deny"` |
| OpenCode | Same as Claude Code | Same as Claude Code |
| Crush | Same as Claude Code | Same as Claude Code |
| Antigravity CLI | Flat JSON `decision` field (required — an absent decision denies) | `{"decision": "deny", "reason": "..."}`; a clean check returns `{"decision": "ask"}` |

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
├── codex.py             # OpenAI Codex (CLI + Desktop) (extends ClaudeCodeAdapter)
├── windsurf.py          # Windsurf (extends ClaudeCodeAdapter)
├── gemini.py            # Google Gemini CLI
├── cline.py             # Cline / ZooCode
├── kiro.py              # Kiro + AiderDesk + OpenClaw
├── antigravity.py       # Google Antigravity CLI
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
- `conversationId` + `workspacePaths` or `toolCall` → Antigravity CLI
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

Agent names: `claude`, `cursor`, `copilot`, `codex`, `windsurf`, `gemini`, `antigravity`, `cline`, `zoocode`, `kiro`, `aiderdesk`, `openclaw`, `opencode`, `augment`, `crush`, `junie`

### Config File Locations

| Agent | Config Path |
|-------|------------|
| Claude Code | `~/.claude/settings.json` |
| Cursor desktop / local CLI hooks | `~/.cursor/hooks.json` (AI Guardian install target) |
| Cursor project hooks (explicit cloud setup target) | `<project>/.cursor/hooks.json` |
| Cursor desktop / local CLI MCP | `~/.cursor/mcp.json` (AI Guardian install target) |
| Cursor local project MCP (managed by Cursor, not Cloud setup) | `<project>/.cursor/mcp.json` |
| GitHub Copilot | `~/.github/hooks/hooks.json` |
| OpenAI Codex (CLI + Desktop) | `~/.codex/hooks.json` |
| Windsurf | `~/.codeium/windsurf/hooks.json` |
| Gemini CLI | `~/.gemini/settings.json` |
| Cline / ZooCode | `.clinerules/hooks/` (scripts) |
| Kiro | `.kiro/hooks/` (scripts) |
| Augment Code | `~/.augment/settings.json` |
| AiderDesk | `~/.aider-desk/extensions/ai-guardian/` (extension) |
| OpenClaw | `~/.openclaw/plugins/ai-guardian/` (plugin) |
| OpenCode | `~/.config/opencode/plugins/ai-guardian.ts` (plugin) |
| Crush | `.crush.json` (project) or `~/.config/crush/crush.json` (global) |
| Antigravity CLI | `~/.gemini/config/hooks.json` (global) or `<workspace>/.agents/hooks.json` (project) |
| Junie | `.junie/guidelines` (MCP only) |

### Cursor desktop, CLI, and agent scope

Cursor uses the same command-hook JSON protocol and `hooks.json` event names
for its local desktop Agent and local CLI/headless-agent execution. The normal
configuration scope is the local user level, so the desktop and local CLI share
one installation:

```text
~/.cursor/hooks.json
~/.cursor/mcp.json
```

Project-level files are inspected to explain effective Cursor behavior and are
not changed by the default local setup. For a Cursor Cloud workspace, an
explicit project setup can be requested with:

```bash
ai-guardian setup --ide cursor --project /path/to/workspace
```

The tray exposes the same operation as **Cursor Cloud (project setup)...**
under **Manual setup (specific IDE)** and asks the user to select the project
directory before launching setup. This explicit path creates or updates only
that workspace's `.cursor/hooks.json`; it does not redirect ordinary
desktop/CLI setup away from the user files. Cursor Cloud MCP registration is
managed through Cursor's Cloud Agents dashboard/team settings or API, not the
project `.cursor/mcp.json`. Enterprise/team hooks remain an upstream
deployment option outside this local project flow.

See the upstream [Cursor Hooks documentation](https://cursor.com/docs/hooks)
for the event list, command-hook protocol, and cloud-agent scope rules.

## Per-Agent Deep-Dive Guides

| Agent | Guide | Description |
|-------|-------|-------------|
| GitHub Copilot | [GITHUB_COPILOT.md](GITHUB_COPILOT.md) | Detailed setup, troubleshooting, response format, enterprise deployment |
| Aider (CLI) | [AIDER.md](AIDER.md) | Git pre-commit hook integration (not hook adapter — scans at commit time) |
| AiderDesk | [AIDERDESK.md](AIDERDESK.md) | TypeScript extension setup, npm install, hot reload |

## Adding or Changing an Agent

Follow the [IDE/Agent Integration Checklist](IDE_INTEGRATION_CHECKLIST.md).
It covers the adapter and registry, setup and reconciliation, optional MCP
and transcript surfaces, focused tests, manual acceptance, documentation, and
release-readiness coverage. Keep the capability tables in this document
synchronized with the evidence collected by that checklist.

## Adding a New Violation Type

1. Implement the detector in the appropriate module
2. Add a row to the **Violation Type Coverage Matrix** with the required hooks and per-agent coverage
3. If the violation has agent-specific limitations, add a subsection under **Known Limitations**
4. Add tests covering the new violation type across adapters
