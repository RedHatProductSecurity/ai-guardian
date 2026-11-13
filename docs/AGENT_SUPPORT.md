# Agent Support

AI Guardian protects multiple AI coding agents through a unified hook adapter architecture. Each agent gets a dedicated adapter that normalizes its hook format into a common internal model, so the core scanning pipeline stays agent-agnostic.

This document is the capability reference: it records what each integration
supports and where known limitations remain. Use the
[IDE/Agent Integration Checklist](IDE_INTEGRATION_CHECKLIST.md) for host hooks,
plugins, MCP, transcripts, and IDE setup. Use the
[CLI/Runtime Integration Checklist](CLI_RUNTIME_CHECKLIST.md) for Docker/Podman
and OpenShell distribution, authentication, policies, images, and runtime
behavior.

The canonical cross-cutting registry is
[`SUPPORTED_IDE_REGISTRY`](../src/ai_guardian/ide_registry.py). The executable
parity contract in [`tests/unit/test_ide_registry.py`](../tests/unit/test_ide_registry.py)
checks that this support list agrees with adapter aliases, setup modes,
managed events, MCP/rules and transcript/session registries, installer
surfaces, and release-readiness matrices.

## Upstream CLI maturity

Support status describes AI Guardian's integration coverage, not the upstream
agent CLI's maturity or stability. When setup or `ai-guardian doctor` detects a
CLI version below 1.0.0, it reports a non-blocking advisory because upstream
interfaces may change before 1.0.0. This does not mean the integration is
misconfigured. If the CLI version is unavailable or cannot be parsed, AI Guardian
does not classify it as pre-1.0. See [Troubleshooting](TROUBLESHOOTING.md#general-diagnostics)
for doctor output details.

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
| Grok Build | `--ide grok` | 6 managed events; only `PreToolUse` blocks | Local TOML `config.toml` | **Complete for documented hooks; passive output is observation-only** |
| OpenAI Codex (CLI + Desktop) | `--ide codex` | 5 managed events (12 recognized) | Global `config.toml` | **Complete for Codex CLI and desktop Codex mode** |
| Windsurf | `--ide windsurf` | Full | N/A | **Complete** |
| Gemini CLI | `--ide gemini` | Full | N/A | **Complete** |
| Cline / ZooCode | `--ide cline` | Full | N/A | **Complete** |
| Kiro (AWS) | `--ide kiro` | Full | N/A | **Complete** |
| Augment Code | `--ide augment` | Full | N/A | **Complete** |
| AiderDesk | `--ide aiderdesk` | Extension | N/A | **Complete** |
| OpenClaw | `--ide openclaw` | Plugin | N/A | **Complete** |
| OpenCode V1/V2 | `--ide opencode` | Version-aware plugin | N/A | **Host contracts complete; normal-image V1 supported; OpenShell V1 Vertex path implemented, live qualification manual** |
| Pi | `--ide pi` | Managed extension (hooks + MCP tool bridge; eight callbacks) | Managed extension (`@modelcontextprotocol/sdk` pinned) | **Complete** |
| Antigravity CLI (agy) | `--ide antigravity` | Partial | Full | **Complete** |
| Crush (Charmbracelet) | `--ide crush` | Partial | Full | **Complete** |
| Junie (JetBrains) | `--ide junie` | N/A | Full | **MCP-only** |

## IDE-specific home and configuration paths

For removal and package-first recovery, see [Uninstall and orphan recovery](UNINSTALL.md),
including the explicitly unverified per-host missing-runtime lifecycle matrix.

AI Guardian resolves user-level setup, MCP registration, verification, audit,
and supported session paths from the same environment-variable rules. An
explicit complete-file variable has priority over a home-directory variable;
the first variable listed for an integration wins. A project-scoped operation
always remains project-local, even when the IDE also supports a relocated user
home. With no variables set, the existing defaults below are unchanged.

| Integration | User-home or file variables | Relocated user-level targets | Project/local behavior |
|---|---|---|---|
| Claude Code | `CLAUDE_CONFIG_DIR` | Hooks: `<dir>/settings.json`; MCP: `<dir>/.claude.json`; sessions: `<dir>/projects` | Project `.claude/` and `.mcp.json` paths are not redirected |
| OpenAI Codex | `CODEX_HOME` | Hooks: `<dir>/hooks.json`; MCP: `<dir>/config.toml`; sessions: `<dir>/sessions` | Project `.codex/` layers remain project-local |
| Cursor | `CURSOR_CONFIG_DIR` | User hooks: `<dir>/hooks.json`; user MCP: `<dir>/mcp.json` | Project hooks/MCP remain under the selected project `.cursor/` directory |
| GitHub Copilot CLI | `COPILOT_HOME` | Hooks: `<dir>/hooks/hooks.json`; optional MCP: `<dir>/mcp-config.json`; CLI transcript: `<dir>/session-state/events.jsonl` | Project files are not redirected; without the variable the hook default remains `~/.github/hooks/hooks.json` |
| Grok Build | `GROK_HOME` | Hooks: `<dir>/hooks/ai-guardian.json`; MCP: `<dir>/config.toml` | Project hooks/MCP remain under the selected project `.grok/` directory; no local transcript adapter |
| Gemini CLI | `GEMINI_CLI_HOME` | The effective `.gemini` home is `<dir>/.gemini`; hooks/settings: `<dir>/.gemini/settings.json`; sessions: `<dir>/.gemini/tmp` | Project `.gemini/` paths are not redirected |
| Cline / ZooCode | `CLINE_DATA_DIR` for user MCP; `CLINE_STORAGE_DIR` remains a transcript/storage alias | MCP: `<dir>/mcp_settings.json` | Hook setup remains project-local at `.clinerules/hooks` |
| Kiro | `KIRO_HOME` | MCP: `<dir>/settings/mcp.json`; CLI sessions: `<dir>/sessions/cli` | Hook setup remains project-local at `.kiro/hooks`; the historical no-env MCP default is retained |
| Junie | `JUNIE_HOME` | MCP: `<dir>/mcp.json` | Guidelines remain project-local at `.junie/guidelines`; `JUNIE_CONFIG_LOCATION` is an additive upstream search path, not a replacement selected by AI Guardian |
| AiderDesk | `AIDER_DESK_DIR`, then `AIDER_DESK_HOME_DIR` | Extension: `<dir>/extensions/ai-guardian`; MCP: `<dir>/settings.json` | Project transcript history remains `.aider.chat.history.md` |
| OpenClaw | `OPENCLAW_STATE_DIR`, then `OPENCLAW_HOME`; `OPENCLAW_CONFIG_PATH` is an explicit MCP file | Plugin: `<state>/plugins/ai-guardian`; MCP: the exact `OPENCLAW_CONFIG_PATH`, otherwise `<state>/settings.json` | Explicit config-file selection does not redirect plugin state |
| OpenCode V1/V2 | `OPENCODE_CONFIG` (file), then `OPENCODE_CONFIG_DIR` (directory); V2 may also use `OPENCODE_DB` | Config: selected JSON/JSONC file; plugin: its adjacent `<config-dir>/plugins`; shared bridge: `<config-dir>/ai-guardian`; V2 local discovery: `.opencode/plugins/` | Project-local config remains project-local; V2 database discovery uses `opencode debug paths db` when available |
| Pi | `PI_CODING_AGENT_DIR` for the agent home; `PI_CODING_AGENT_SESSION_DIR` for sessions | Managed extension: `<dir>/extensions/ai-guardian/index.ts` plus `package.json`; sessions: `<session-dir>/*.jsonl` | Project extension remains under `<project>/.pi/extensions/ai-guardian`; MCP is bridged through the managed extension |
| Windsurf | No documented home relocation variable; `WINDSURF_TRANSCRIPTS_DIR` is transcript-only | Existing defaults remain unchanged | Project hooks/settings retain their existing scope |
| Augment Code | No documented home relocation variable | Existing defaults remain unchanged | Project paths retain their existing scope |
| Crush | `CRUSH_GLOBAL_CONFIG` for the global MCP file; `CRUSH_GLOBAL_DATA` is not used for setup | Explicit global MCP file only | Hook and default `.crush.json` setup remain project-local |

These names follow the upstream contracts for [Claude](https://code.claude.com/docs/en/env-vars),
[Codex](https://github.com/openai/codex/blob/main/codex-rs/config/src/loader/mod.rs),
[Cursor](https://prod.cursor.com/docs/cli/reference/configuration),
[Copilot CLI](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference),
[Gemini CLI](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/configuration.md),
[Kiro](https://kiro.dev/docs/cli/reference/settings/),
[Junie](https://junie.jetbrains.com/docs/environment-variables.html),
[Cline](https://github.com/cline/cline/blob/main/docs/cli/cli-reference.mdx),
[OpenClaw](https://github.com/openclaw/openclaw/blob/main/docs/help/environment.md),
[OpenCode](https://dev.opencode.ai/docs/config), and
[Pi](https://github.com/earendil-works/pi). The
[AiderDesk release notes](https://github.com/hotovo/aider-desk/releases) and
[Crush repository](https://github.com/charmbracelet/crush) document their
custom directory/configuration variables. Integrations without a documented
relocation variable deliberately keep their existing defaults.

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
| `grok` | Dedicated camelCase adapter, six managed events, project hook/MCP setup | No local transcript/session adapter | Isolated managed-event matrix; PreToolUse deny contract and passive-event limitation |
| `codex` | Dedicated adapter, five managed events, layered config/MCP reconciliation, Codex UX contracts | Codex JSONL default-path discovery; browser session adapter | Isolated event matrix; CLI/desktop Codex-mode scope explicitly separated from regular ChatGPT |
| `windsurf` | Dedicated adapter and nine managed command-hook events | Windsurf JSONL; browser session adapter | Isolated all-managed-event matrix; command-hook process I/O |
| `gemini` | Dedicated adapter, SessionStart/BeforeAgent/BeforeTool/AfterTool mapping | Explicit-path JSONL; browser session adapter | Isolated all-managed-event matrix; command-hook health |
| `cline` | Cline adapter and script-hook setup/reconciliation | Cline JSON-array transcript; shared Cline session adapter | Isolated script-event matrix; project-local hook scope |
| `zoocode` | ZooCode key mapped to the shared Cline adapter and script contract | Shared Cline JSON-array/session evidence | Isolated script-event matrix; explicit alias and shared-layout coverage |
| `kiro` | Dedicated Kiro adapter and script-hook setup/reconciliation | Kiro JSONL; browser session adapter | Isolated script-event matrix; project-local hook scope |
| `aiderdesk` | Extension bridge/package registration and shared TypeScript process/response boundary | AiderDesk Markdown transcript; no hook session grouping | Generated bridge/registration E2E boundary; host SDK runtime is an explicit CI exclusion |
| `openclaw` | Plugin bridge/package registration, rules setup, and shared TypeScript process/response boundary | OpenClaw JSONL; no hook session grouping | Generated bridge/registration E2E boundary; plugin SDK runtime is an explicit CI exclusion |
| `opencode` | Version-aware V1/V2 plugin bridge, SQLite/session setup, and shared TypeScript process/response boundary | OpenCode SQLite with V1 fallback and V2 runtime path discovery; browser session adapter | Generated plugin/registration E2E boundary; V1/V2 config-key reconciliation |
| `pi` | Dedicated adapter, managed extension/MCP bridge, and Claude-compatible response boundary | Pi JSONL; browser session adapter | Generated extension/registration E2E boundary; project/user trust and pinned SDK dependency diagnostics |
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

This inventory records configured or recognized lifecycle events, not whether a
host enforces each response. The behavior matrix below is authoritative for
blocking, observation, context injection, and output transformation.

| Agent | SessionStart | UserPromptSubmit | PreToolUse | PostToolUse | BeforeReadFile | PostCompact | SessionEnd |
|-------|-------------|-----------------|------------|-------------|----------------|-------------|------------|
| Claude Code | Yes | Yes | Yes | Yes | N/A | Yes | Yes |
| Cursor | N/A | Yes | Yes | Yes | Yes | N/A | N/A |
| GitHub Copilot | N/A | Yes | Yes | N/A | N/A | N/A | N/A |
| Grok Build | Yes | Yes | Yes | Yes (observation) | N/A | Yes | Yes |
| OpenAI Codex (CLI + Desktop) | N/A | Yes | Yes | Yes | N/A | Yes | Yes |
| Windsurf | N/A | Yes | Yes | Yes | Yes | N/A | N/A |
| Gemini CLI | Yes | Yes (BeforeAgent) | Yes | Yes | N/A | N/A | N/A |
| Cline / ZooCode | N/A | Yes | Yes | Yes | N/A | N/A | N/A |
| Kiro | N/A | Yes | Yes | Yes | N/A | N/A | N/A |
| Augment Code | N/A | N/A | Yes | Yes | N/A | N/A | N/A |
| OpenCode V1/V2 | N/A | Yes (chat.message / prompt) | Yes | Yes | N/A | N/A | Yes (V1 session.end; V2 session.deleted) |
| Pi | Yes (`session_start`) | Yes (`input`) | Yes (`tool_call`, `user_bash`) | Yes (`tool_result`) | N/A | N/A | Yes (`session_shutdown`) |
| Antigravity CLI | N/A | Yes (PreInvocation) | Yes | Yes (no output) | N/A | N/A | N/A |
| Crush | N/A | N/A | Yes | N/A | N/A | N/A | N/A |
| Junie | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

Tray session-pause controls remove a session immediately when a normalized
`SessionEnd` event is received. For integrations without a reliable end event,
hook activity within the last 30 minutes is the documented liveness fallback;
this does not inspect whether the IDE process is open. Directory-wide controls
remain available to callers without stable session identities.

The Codex row applies to Codex CLI and desktop Codex mode only. Regular
ChatGPT mode does not run these Codex lifecycle hooks.

### Capability overview

These profiles summarize the **configured integration**, not relative security
or assurance. A gate applies only when the hook is installed, enabled, trusted
where required, and present in the execution scope. Post-tool processing cannot
undo side effects that already occurred. The detailed table below is the source
of truth for host/version limitations and failure behavior.

| Profile | Integrations |
|---|---|
| **Prompt control and pre-tool gate** | Claude Code; Cursor desktop/local CLI; Codex CLI and desktop Codex mode; Windsurf; Gemini CLI; Kiro IDE; AiderDesk; OpenCode V1/V2; Pi. OpenCode replaces the submitted draft with a fixed refusal rather than returning a native prompt denial. |
| **Pre-tool gate; prompt gate absent, advisory, conditional, or unverified** | Copilot command hooks; Grok Build; Antigravity CLI; Cline; Cursor Cloud Agent; Kiro CLI; OpenClaw; ZooCode; Augment; Crush. Copilot's command prompt-hook output is ignored; Antigravity injects advice but does not terminate the model request. |
| **MCP-only advisory checks** | Junie. MCP availability does not itself enforce a check; the agent must call and follow it. |

Post-tool result handling is a separate capability. Claude Code supports
model-visible output replacement, but a post-tool `block` alone leaves the
original result visible. Cursor replacement is documented for supported MCP
results only. Codex can replace a completed result with feedback, not a
sanitized copy of that result. Gemini can withhold a sensitive result using a
fixed refusal. AiderDesk, OpenCode, and Pi have host-side result transformation
paths; OpenCode V1 block behavior is not counted as a verified redaction
guarantee. Other paths are observation/context-only, not installed, or
unverified as detailed below.

### Per-integration behavior matrix

For a compact onboarding view, see the
[README behavior and limitations summary](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/README.md#per-integration-behavior-and-limitations).
Keep that summary synchronized with the detailed reference below when integration
behavior or scope changes.

`UserPromptSubmit` includes the closest host-native equivalent. **Gate** means
the host can stop an action before it starts; **replace** changes what the next
model request receives; **withhold** substitutes a refusal/error; **advice**
adds context without stopping the action; **observe** has no enforced decision
effect; **not installed** means AI Guardian does not register that stage;
**unverified** must not be relied on for enforcement. Output changes happen
after the tool has run. Failure defaults below describe the host contract, not
a guarantee that every installed version behaves identically.

| Registry key | Surface or variant | UserPromptSubmit equivalent | PreToolUse equivalent | PostToolUse equivalent | Protocol, timing, prerequisite, failure behavior, references, and limits |
|---|---|---|---|---|---|
| `claude` | Claude Code in the scope where hooks are configured, including CLI, desktop, or hosted execution | **Gate**; AI Guardian does not rewrite prompts. | **Gate** via permission decision; a clean response leaves Claude's normal permission flow in place. | **Feedback or replace**: `decision: block` alone leaves the original result visible; `updatedToolOutput` can replace supported model-visible results when the returned shape matches the tool. Claude Code currently ignores this replacement for Bash output ([upstream issue #64326](https://github.com/anthropics/claude-code/issues/64326)). | Command hooks exchange JSON on stdin/stdout. Prompt timeout defaults to 30s; most other hooks default to 600s. The generated config does not set `onFailure: block`, so command failures/timeouts generally fail open. Install/configure hooks in the actual execution scope. A post-hook cannot undo tool side effects. [Hooks reference](https://code.claude.com/docs/en/hooks). |
| `cursor` | Desktop and local CLI | **Gate** through `beforeSubmitPrompt`; no in-place prompt rewrite. | **Gate** through permission decisions and before-read hooks. | **Replace only supported MCP results** through `updated_mcp_tool_output`; generic `modifiedToolOutput` is not a documented replacement contract. | Command JSON on stdin/stdout. AI Guardian sets `failClosed: true` on generated prompt/pre-decision hooks; post hooks remain fail-open. No timeout is pinned in AI Guardian config. Install in the local/user or selected project scope. HTTP MCP results running on Cursor's backend can arrive already redacted and cannot be replaced by the local hook. [Hooks reference](https://cursor.com/docs/hooks). |
| `cursor` | Cloud Agent / cloud workspace | **Unavailable**: `beforeSubmitPrompt` runs before the cloud VM exists. | **Conditional gate** only when the applicable project/cloud-workspace hook is present and loaded; local user hooks do not protect a remote run. | Cursor documents replacement for supported MCP results, but backend-hosted HTTP MCP results cannot be replaced; no general built-in result replacement is claimed. | Cloud protection requires explicit workspace/project configuration. Generated decision hooks request fail-closed handling, but the cloud run must actually load that configuration. Timeout is not pinned by AI Guardian. [Hooks reference](https://cursor.com/docs/hooks). |
| `copilot` | Copilot CLI / command-hook configuration | **Observe only**: `userPromptSubmitted` command output, including `modifiedPrompt`, is dropped; exit 2 is a warning and does not block the prompt. | **Gate** via `permissionDecision: deny`. | **Not installed** by AI Guardian. | Command JSON on stdin/stdout. The command prompt event is not an enforcement point; `modifiedPrompt` is honored by SDK programmatic hooks only. For `preToolUse`, non-timeout hook errors fail closed; timeout is fail-open. AI Guardian installs the local Copilot hook configuration, not remote cloud-job hooks. [Hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference). |
| `copilot` | Copilot cloud coding-agent job | **Not installed** by AI Guardian. | **Not installed** by AI Guardian. | **Not installed** by AI Guardian. | The local `COPILOT_HOME`/user command-hook setup does not provision a repository's remote `.github/hooks/` policy. Do not infer cloud enforcement from a local CLI/IDE installation. [Hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference). |
| `grok` | Grok Build command hooks | **Observe only** in AI Guardian; the adapter emits no prompt decision or context. | **Gate** on an explicit deny. | **Observe only**; passive-event output is ignored, so no result replacement. | Command hooks receive event JSON on stdin and return JSON/exit status. AI Guardian does not set a timeout; Grok's documented default is 5s. Only an explicit deny blocks; crashes, malformed output, non-deny exit codes, and timeouts fail open. Project hooks require the project to be trusted. [Hooks reference](https://docs.x.ai/build/features/hooks). |
| `codex` | Codex CLI and desktop **Codex mode** only; not regular ChatGPT mode | **Gate** with a block decision or exit 2; no prompt rewrite. | **Gate**; the deny response includes Codex's required sanitized `permissionDecisionReason`. | **Replace with feedback** when blocked; Codex can substitute the completed result with feedback, but AI Guardian does not claim a sanitized replacement of the original result. | Command hooks use JSON stdin/stdout. Generated timeout is 300s for prompt/pre-tool and 60s for post-tool. Hooks must be reviewed/trusted by Codex; ordinary hook failures continue rather than deny. Post-tool runs after side effects. [Codex hooks](https://learn.chatgpt.com/docs/hooks); [scope note](#codex-and-chatgpt-desktop-scope). |
| `windsurf` | Cascade hooks in the configured user/project scope | **Gate** through `pre_user_prompt` (exit 2). | **Gate** through installed pre-command, pre-read, pre-write, and pre-MCP events (exit 2). | **Observe only**; post-hooks cannot block or replace completed tool results. | Command receives event JSON on stdin; exit 2 blocks pre-hooks, other errors continue. AI Guardian does not set a timeout or `show_output`. Hook files must be present in the actual Cascade scope. [Cascade hooks](https://docs.windsurf.com/windsurf/cascade/hooks). |
| `gemini` | Gemini CLI | **Gate** through `BeforeAgent`; no prompt rewrite. | **Gate** through `BeforeTool`. | **Withhold by refusal** on a sensitive result; Gemini replaces the model-visible result with a fixed refusal, not AI Guardian's sanitized copy. | Command hooks use JSON stdin/stdout. Host default timeout is 60s; exit 2 blocks, while other nonzero exits warn and continue. Requires the generated Gemini settings hook config to be loaded. [Hooks reference](https://geminicli.com/docs/hooks/reference/). |
| `antigravity` | Antigravity CLI (`agy`) | **Advice only** through `PreInvocation`, the closest equivalent; AI Guardian does not set the host's `terminationBehavior: terminate`. | **Gate** on explicit deny; a clean check returns `ask` to preserve the host permission flow. | **Observe only** for tool output: Antigravity's `PostToolUse` payload has no result content. | CamelCase JSON on stdin/stdout. AI Guardian configures 300s for `PreToolUse` and 60s for `PostToolUse`/`PreInvocation`. Requires `~/.gemini/config/hooks.json` (or the configured hook file) and `agy`. Host handling of hook process failure is not relied on; verify the target version. [Hooks reference](https://antigravity.google/docs/hooks/). |
| `cline` | Cline file/script hooks | **Observe only**: the prompt event is delivered, but the documented file-hook response has no prompt-denial or rewrite field; AI Guardian's `cancel` response is not a prompt gate. | **Gate** using the documented `cancel: true` response. | **No verified result replacement**: AI Guardian emits `modifiedResult`, which is not in the documented file-hook output contract; treat the stage as observation-only. | File hooks receive JSON on stdin and return JSON on stdout. The cited file-hook contract does not specify a script timeout or failure default; AI Guardian pins neither. Enable hooks in the intended Cline scope; Cline documents that hooks are disabled in `--yolo` mode. CLI and IDE use different hook paths. Do not infer file-hook behavior from the separate SDK plugin-hook contract. [File hook reference and examples](https://github.com/cline/cline/blob/main/sdk/examples/hooks/README.md). |
| `zoocode` | ZooCode using the shared Cline adapter and `.clinerules/hooks` scripts | **Unverified**: AI Guardian emits the Cline `cancel` response, but this host/version mapping is not independently qualified. | **Intended gate** using the shared Cline `cancel: true` response; verify the exact ZooCode runtime. | **Unverified**: no safe `modifiedResult` replacement is established. | The setup writes Cline-format event scripts; ZooCode's acceptance, timing, and failure semantics are not independently qualified by this integration. Do not rely on prompt denial or result replacement without host-specific verification. [ZooCode hooks](https://zcode.z.ai/en/docs/hooks). |
| `kiro` | Kiro IDE | **Gate**: nonzero command result blocks IDE Prompt Submit; AI Guardian exits 1 on a finding. | **Gate**: AI Guardian exits 2 on a finding. | **Advice/context only**; stdout may be added to agent context, not a result replacement. | Shell command action receives JSON on stdin; successful stdout is context. Default timeout is 60s. For IDE Prompt Submit and Pre Tool Use, a nonzero result blocks; other hook errors are surfaced. Install the project `.kiro/hooks` scripts. [Hook actions](https://kiro.dev/docs/hooks/actions/); [hook triggers](https://kiro.dev/docs/hooks/types/). |
| `kiro` | Kiro CLI (including documented CLI hook surfaces) | **Observe/advice only**: CLI Prompt Submit hooks cannot block, even though the trigger exists. | **Gate** on explicit exit 2. | **Advice/context only**; no safe output replacement. | Command JSON on stdin; default timeout is 60s. CLI Prompt Submit nonzero exits are warnings; Pre Tool Use exit 2 blocks. Standalone hook files and exact event availability vary by CLI generation; verify the installed version. [Hook actions](https://kiro.dev/docs/hooks/actions/); [hook triggers](https://kiro.dev/docs/hooks/types/). |
| `aiderdesk` | AiderDesk extension v0.55.0+ with the AI Guardian extension enabled | **Gate** via `onPromptStarted` returning `{ blocked: true }`. | **Conditional gate** through `onToolApproval`/`onToolCalled`; host execution paths can differ in which callbacks fire. | **Replace output** through `onToolFinished` where that callback runs; tool side effects have already occurred. | Extension callback invokes the shared process bridge synchronously; bridge timeout is 30s. Explicit exit 1/2 findings block; spawn errors/timeouts fail open. Requires the extension and `ai-guardian` executable in the extension environment. [Extension events](https://aiderdesk.dev/docs/extensions/events); [AI Guardian setup](AIDERDESK.md). |
| `openclaw` | OpenClaw Gateway plugin | **Observe only**: AI Guardian scans `message_received`, but that event ignores returned handler values, so `cancel` is not a prompt gate. | **Gate** through `before_tool_call`. | **Observe only**: `after_tool_call` is an observe hook and the plugin discards the scan result. | Plugin calls the shared process bridge synchronously with JSON; 30s timeout. Explicit exit 1/2 findings block pre-tool calls; other bridge failures fail open. Requires the plugin to be loaded by the Gateway. [Hook reference](https://docs.openclaw.ai/plugins/hooks/reference); [AI Guardian setup](#ide-specific-home-and-configuration-paths). |
| `opencode` | OpenCode V1 (`opencode-ai` 1.x) | **Replace** submitted prompt parts with a fixed refusal before model submission; not a native prompt-cancel result. | **Gate** by throwing from `tool.execute.before`. | **Conditional transformation**: the V1 callback applies an explicit returned replacement; a blocked post-hook throws, which is not counted as a verified safe-redaction guarantee. | Plugin invokes shared JSON process bridge; 30s timeout. OpenCode bridge failures and missing workspace identity fail closed. Requires V1 plugin registration and its adjacent bridge. Tool side effects precede post-tool handling. [OpenCode guide](OPENCODE.md); [plugin hooks](https://opencode.ai/docs/plugins/). |
| `opencode` | OpenCode V2 (`@opencode/cli` 2.x) | **Replace** prompt draft with a fixed refusal and clear attachments/mentions; not a native prompt denial. | **Gate** by throwing from `execute.before`. | **Replace/withhold** the completed model-visible result; V2 updates the owned result before reporting a block. | Plugin invokes shared JSON process bridge; 30s timeout. Missing workspace identity and bridge failures fail closed. Requires V2 plugin discovery and V2 artifacts; V1 plugin code does not run in V2. [OpenCode guide](OPENCODE.md); [migration guide](https://opencode.ai/docs/build/plugins/migrate-v1/). |
| `pi` | Pi extension in user or project scope | **Gate** through `input` returning `action: handled`; extension commands handled earlier are outside this event. | **Gate** through `tool_call` and the native `user_bash` callback. | **Replace or mark as error** through `tool_result`; assistant output is also checked at `message_end`. | Extension invokes `ai-guardian` synchronously with JSON and a 30s timeout. Explicit exit 1/2 findings block; other child-process failures/timeouts fail open. Requires the extension to be loaded and the executable available. [Extensions reference](https://pi.dev/docs/latest/extensions). |
| `augment` | Augment/Auggie local command hooks | **Not installed as a gate**: upstream `PromptSubmit` is asynchronous and cannot block or change the prompt. | **Gate** on explicit deny for the installed matcher set. | **Feedback only**; post hooks cannot deny or replace results. | Synchronous command hooks use JSON stdin/stdout; AI Guardian sets a 5s timeout. Only exit 2 or a deny blocks; crashes/timeouts fail open. Installed matchers cover selected process, edit, save, view, and remove-files tools, not every possible tool. [Hooks reference](https://docs.augmentcode.com/cli/hooks). |
| `crush` | Current AI Guardian project hook installs only `PreToolUse` | **Not installed**. | **Gate** using the Claude-compatible deny response or exit 2. | **Not installed** by AI Guardian. | Command receives JSON on stdin; AI Guardian configures a 30s timeout. Only an explicit deny is relied on; other process-failure behavior is not qualified here. This describes AI Guardian's installed surface, not every hook available in newer Crush releases. [Crush hooks](https://github.com/charmbracelet/crush/blob/main/docs/hooks/README.md). |
| `junie` | Junie MCP-only integration | **Not available**. | **Not available**. | **Not available**. | AI Guardian installs no lifecycle hook protocol. MCP checks are advisory and depend on the agent choosing to call and follow them; no hook timing or hook failure default applies. [Junie environment and configuration](https://junie.jetbrains.com/docs/environment-variables.html). |

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
| Grok Build | Command hooks | SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, PostCompact, SessionEnd | Supported; only PreToolUse can block |
| OpenAI Codex (CLI + Desktop) | Command hooks | UserPromptSubmit, PreToolUse, PostToolUse, PostCompact, SessionEnd | Supported (five managed events) |
| Windsurf | Command hooks | UserPromptSubmit, BeforeReadFile, PreToolUse, PostToolUse | Supported |
| Gemini CLI | Command hooks | SessionStart, BeforeAgent, BeforeTool, AfterTool | Supported |
| Cline / ZooCode | Script hooks | UserPromptSubmit, PreToolUse, PostToolUse | Supported |
| Kiro | Script hooks | UserPromptSubmit, PreToolUse, PostToolUse | Supported |
| Augment Code | Command hooks | PreToolUse, PostToolUse | Supported |
| Antigravity CLI (agy) | Command hooks | PreInvocation, PreToolUse, PostToolUse | Supported (partial output surface) |
| AiderDesk | Extension | UserPromptSubmit, PreToolUse, PostToolUse | Supported |
| OpenClaw | Plugin | UserPromptSubmit, PreToolUse, PostToolUse, Stop | Supported |
| OpenCode | Plugin | UserPromptSubmit, PreToolUse, PostToolUse, Stop, SessionEnd | Supported |
| Pi | Extension | SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, SessionEnd | Supported |
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

## Interpreting violation coverage

Scanner coverage depends on the event and on the host actually enforcing the
response. An event listed in the inventory is not automatically a block or a
safe result replacement. Use the [capability overview](#capability-overview)
and [per-integration behavior matrix](#per-integration-behavior-matrix) for
stage behavior; the following table describes violation/scanner coverage.

## Violation Type Coverage Matrix

Coverage per agent depends on which hooks are available. This table shows representative agents across the enforcement spectrum: full hooks + MCP, full hooks only, partial hooks, and MCP-only.

Antigravity's PostToolUse fires but carries no tool output, so post-tool redaction (`secret_redaction`) is not available there; pre-tool enforcement is unaffected.

The Copilot column refers to the installed local CLI/IDE command hooks, not
Copilot's cloud coding-agent jobs. Prompt/transcript findings can be reported,
but command prompt-hook output is not enforced and AI Guardian does not install
a Copilot `PostToolUse` hook.

The detailed behavior matrix intentionally avoids assuming that agents with a
shared adapter or event name have the same enforcement behavior. Gemini refuses
sensitive tool results rather than returning a sanitized copy; Grok's prompt
and post-tool callbacks are observation-only in AI Guardian; Copilot command
prompt output is ignored by the host. Copilot CLI and Codex support transcript
scanning via adapter-resolved default paths (Issue #935).

| Violation Type | Requires | Claude Code | Cursor | Copilot CLI | Antigravity | Junie (MCP) |
|---|---|---|---|---|---|---|
| secret_detected | Pre+Post | Enforce | Partial | Partial | Partial | Advisory |
| suspected_password (opt-in experimental) | Prompt/Pre/Post where exposed | Unqualified* | Unqualified* | Unqualified* | No post output; unqualified* | Advisory only |
| command_credential_detected (supported CLI subset) | Pre (Bash/Shell) or MCP `check_command` | Enforce | Enforce | Enforce | Enforce | Advisory |
| secret_redaction | Post | Partial | Partial | No (PostToolUse not installed) | No (no tool output) | No |
| pii_detected | Pre+Post+Prompt | Enforce | Enforce | Partial | Partial | Advisory |
| directory_blocking | Pre | Enforce | Enforce | Enforce | Enforce | Advisory |
| tool_permission | Pre | Enforce | Enforce | Enforce | Enforce | No |
| prompt_injection | Pre+Prompt | Enforce | Enforce | Partial | Partial | Advisory |
| jailbreak_detected | Pre+Prompt | Enforce | Enforce | Partial | Partial | Advisory |
| ssrf_blocked | Pre | Enforce | Enforce | Enforce | Enforce | Advisory |
| config_file_exfil | Pre | Enforce | Enforce | Enforce | Enforce | No |
| secret_in_transcript | Prompt | Enforce | Enforce | Observe only | No | No |
| pii_in_transcript | Prompt | Enforce | Enforce | Observe only | No | No |
| image_secret | Pre | Caution | Caution | Caution | Caution | No |
| image_pii | Pre | Caution | Caution | Caution | Caution | No |
| offensive_language | Pre+Post | Enforce | Enforce | Partial | Partial | Advisory |
| canary_detected | Pre+Post+Prompt | Enforce | Enforce | Partial | Partial | Advisory |
| exfil_detection | Pre (Bash) | Enforce | Enforce | Partial | Enforce | Advisory |

**Legend:**

- **Enforce** — AI Guardian emits a supported denial/replacement response for the applicable stage; host/version limits still apply
- **Advisory** — MCP only, agent must cooperate (no enforcement)
- **Partial** — enforcement is available at some applicable stages, but one or more required stages are unavailable, observation-only, or limited
- **Observe only** — scanning may run, but the host does not enforce the prompt-hook response
- **Caution** — known limitations (see [Image scanning](#image-scanning-all-agents) below)
- **No** — not supported

## Known Limitations

### Gemini CLI — sensitive tool results are refused, not replaced

Gemini's native `AfterTool` payload exposes model-visible output as
`tool_response.llmContent`, including structured text parts. AI Guardian scans
that content, not just its separate display text. Gemini CLI 0.67.0 ignores
`updatedToolOutput`, so requests to redact/sanitize a result instead return a
native `decision: deny`. Gemini replaces the original model and display results
with a fixed refusal. Clean results are unchanged; this is containment through
refusal, not delivery of sanitized output.

### Password-likelihood boundary qualification

`suspected_password` is a default-off local heuristic, not a known-vault match or
proof that a string is secret. **No real host/version/platform is yet qualified
for pre-model prevention by this feature.** Shared unit/UX response tests do not
establish host compliance. This applies to every supported agent, including those
otherwise shown as having full hooks. In particular, post-tool denials or output
replacement can be ignored, observation-only callbacks are too late, and input
arguments may already have been generated by the model before a pre-tool check.
Antigravity has no post-tool content, MCP-only modes are advisory, and transcript
scans are retrospective. Existing credential support ratings are unchanged.

Once explicitly enabled, the default Ask outcome reuses existing local/remote
tray approval with private Allow Once / Block and denies without approval. The
optional block outcome requests denial for qualified contextual candidate classes
and incomplete analysis; ambiguous candidates stay advisory in every mode. No automatic
heuristic PostToolUse transformation is claimed. Explicit full-span text
sanitization is not itself host-boundary evidence. See the
[scope, budgets and per-host manual evidence protocol](security/PASSWORD_LIKELIHOOD.md).

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

Claude Code exposes the conversation transcript to hooks via `UserPromptSubmit` (JSONL file). OpenCode and Cursor store sessions in SQLite databases; Cline stores conversations as JSON arrays in per-task directories; Windsurf stores Cascade transcripts as JSONL step files; ai-guardian reads them directly to scan for secrets and PII. Copilot CLI and Codex store JSONL transcripts at known default locations; ai-guardian discovers these paths via the adapter when the IDE does not provide a `transcript_path` in hook data. Copilot Chat for VS Code stores sessions as JSONL delta journal files in VS Code's `workspaceStorage/*/chatSessions/` directories. AiderDesk stores Markdown chat history at `.aider.chat.history.md` in the project root. OpenClaw stores JSONL transcripts at `~/.openclaw/transcripts/`. Grok Build does not expose a supported local transcript path.

Transcript scanning uses a polymorphic `TranscriptAdapter` interface (`scanners/transcript/base.py`). Each IDE format has its own adapter that implements `can_scan()` and `scan_incremental()`.

OpenCode token usage uses a separate source from transcript text. The
authoritative records are rows in the SQLite `message` table, where the JSON
in `message.data` stores assistant usage as
`tokens.input`, `tokens.output`, `tokens.cache.read`, and `tokens.cache.write`.
AI Guardian maps those fields to `input_tokens`, `output_tokens`,
`cache_read_input_tokens`, and `cache_creation_input_tokens`. The `part` table
is used for text and tool output scanning only. If no `message.data.tokens`
records are available at session end, the Sessions viewers show token usage as
unavailable rather than displaying zero totals.

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
| OpenCode V1/V2 | SQLite | V1: `~/.local/share/opencode/opencode.db` (or `$OPENCODE_HOME/opencode.db`); V2: `$OPENCODE_DB` or `opencode debug paths db`, with the V1 path as fallback |
| Copilot CLI | JSONL | `~/.copilot/session-state/events.jsonl` |
| Codex | JSONL | `~/.codex/sessions/YYYY/MM/DD/*.jsonl` |
| Cline / ZooCode | JSON array | `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/tasks/<task_id>/api_conversation_history.json` |
| Windsurf | JSONL | `~/.windsurf/transcripts/{trajectory_id}.jsonl` |
| Copilot Chat (VS Code) | JSONL (delta journal) | `~/Library/Application Support/Code/User/workspaceStorage/*/chatSessions/*.jsonl` |
| Kiro | JSONL | `~/.kiro/sessions/cli/{session_id}.jsonl` |
| AiderDesk | Markdown | `.aider.chat.history.md` (project root) |
| OpenClaw | JSONL | `~/.openclaw/transcripts/YYYY-MM-DD/{session}/transcript.jsonl` |
| Pi | JSONL | `~/.pi/agent/sessions/**/*.jsonl` or `$PI_CODING_AGENT_SESSION_DIR` |

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
desktop both record `codex`. Its responses share the Claude-compatible envelope,
with Codex-specific required fields for PreToolUse denials. This identity does not
indicate coverage for regular ChatGPT mode; that mode is outside the current Codex
hook enforcement path. Other adapters that share Claude-compatible formatting use
their own stable values, such as
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

### Pi - managed TypeScript extension

Pi uses a generated `ai-guardian/index.ts` extension rather than a native MCP
configuration file or a Python GuardedAgent loop. The extension is installed
with its pinned dependency manifest globally at
`~/.pi/agent/extensions/ai-guardian/` (or under `$PI_CODING_AGENT_DIR`) or
project-locally at `<project>/.pi/extensions/ai-guardian/`. Pi automatically
discovers extensions in those locations and `/reload` reloads an updated extension.

Pi extensions execute with the host process's permissions. Project-local
extensions are loaded only after Pi's project-trust decision, so project setup
must be treated as trusted code. The generated bridge delegates prompt,
provider-request, tool-call, tool-result, user-bash, session, and assistant-output
checks to the existing `ai-guardian` CLI and preserves unrelated extensions.
The global generated extension is version-stamped and refreshed by the daemon
after an AI Guardian upgrade; project-local extensions remain explicit project
setup targets. The extension launches the resolved local `ai-guardian mcp-server`
executable, discovers its tools with `listTools()`, and registers them under the
`mcp__ai-guardian__*` namespace. Setup installs the pinned MIT-licensed MCP SDK
with `npm install --ignore-scripts --no-audit --no-fund` when npm is available and
registers the existing signed identity manifest; server startup still performs
the existing nonce attestation, and a failed attestation registers no MCP tools.
If npm is unavailable or the install fails, setup leaves the extension in place
and reports the retry command.

Pi can advertise its session transcript path before creating the file. AI Guardian
records byte zero for this expected initial absence without creating a fabricated
transcript, then scans the first persisted content when it appears. Other initial
I/O errors still follow the configured scan-error policy; existing transcript
baselines are unchanged.

Pi's exact native `bash` tool is normalized to canonical `Bash` for shell permissions,
SSRF and configuration-exfiltration checks before execution. Custom and MCP tool
names are not rewritten.

This is agent-level protection for activity routed through a user-controlled Pi
process. It does not enforce policy on activity outside that process; OpenShell
or another outer runtime boundary is required for that enforcement. Pi setup
never creates a fabricated native MCP configuration or launches an arbitrary
MCP package.

### OpenCode, AiderDesk, and OpenClaw - shared TypeScript process bridge

These three generated integrations keep their host-specific lifecycle callbacks
in `ai-guardian.ts` or `index.ts`, and install the same shared
`ai-guardian-bridge.ts`. AiderDesk and OpenClaw keep the bridge adjacent to
their host file. OpenCode stores it outside its auto-discovered plugin
directory because OpenCode V1 loads every direct TypeScript file there. The
shared bridge owns executable invocation with
`--ide`, the 30-second timeout, inherited environment plus
`AI_GUARDIAN_IDE_TYPE`, nested JSON response parsing, block decisions, and
`updatedToolOutput` redaction extraction. Host files retain only callback
registration and the response shape required by their SDK. Generated
TypeScript integrations are stamped with the installed AI Guardian version;
when the daemon starts, previously configured integrations are regenerated if
their artifacts are stale or incomplete. Unconfigured IDE directories are not
populated automatically.

OpenCode setup detects the installed CLI generation before rendering the host
plugin. OpenCode V1 is the `1.x` `opencode-ai` runtime and uses
`@opencode-ai/plugin` plus the singular `plugin` configuration key. OpenCode V2
is the `2.x` `@opencode/cli` runtime. Its local plugin is auto-discovered from
the plugins directory and exports the `{ id, setup }` object directly without
importing the plugin package; some V2 server builds fail to resolve that package
from local plugins. Setup removes a stale explicit file entry from the `plugins`
configuration while preserving other package entries. Doctor verifies the
generated files and reports that server activation is unverified. Unknown or
unavailable CLI versions retain the V1 compatibility fallback; an existing
generated V2 plugin is preserved when the runtime cannot report a version. The
two generations cannot share one active `opencode` executable on the same PATH.
V2 file tools normalize native `path` and compatible legacy file aliases through
the same adapter/direct-policy boundary; malformed or conflicting targets remain
fail-closed. Per-event session metadata supplies the current workspace, and the
OpenCode checker child uses that directory for both direct and daemon-forwarded
policy evaluation. Plugin/server startup directories are not workspace fallbacks.
Safe tool diagnostics distinguish input failures, immutable targets, and ordinary
permission denials without exposing raw tool payloads or stored reasons to MCP.
Both support images bundle OpenCode V1 `1.19.0`. The OpenShell selector exposes
OpenCode with an explicit agent profile; the implemented `claude` profile uses
native Vertex AI with gateway-owned Google Cloud ADC. That path still requires
credential-backed live qualification. OpenCode V2 support is a host integration,
not a bundled OpenShell V2 runtime. See the
[sandbox compatibility limitations](Sandbox.md#openshell-maturity-and-compatibility)
before treating an implemented path as a qualified deployment.

See [OpenCode Support](OPENCODE.md) for the runtime support record, exact
container versions, database path precedence, generated V1/V2 hook contracts,
and validation limitations.

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
| Grok Build | Low | Hook contract and isolated tests are covered; real host and passive-event behavior remain limited |
| Gemini CLI | Medium | Current grouped settings format and hook enforcement covered by the local-mock real-agent smoke matrix; live provider qualification remains manual |
| Antigravity CLI | Low | Hook adapter implemented based on documentation; limited real-world testing |
| Codex | Medium | Five managed hooks are set up and health-checked; the adapter also recognizes the remaining documented lifecycle events when configured by the user |
| Windsurf | Low | Hook format implemented but limited testing |
| Cline / ZooCode | Low | Hook format implemented but limited testing |
| Augment Code | Low | Hook format implemented but limited testing |
| Kiro | Low | Hook format implemented but limited testing |
| Junie | Low | MCP only, no hook enforcement |
| AiderDesk | Low | Extension-based, limited testing |
| OpenClaw | Low | Plugin-based, limited testing |
| OpenCode | Medium | V1/V2 generated contracts, setup reconciliation, and path discovery are tested; real V2 host/container runtime and provider smoke evidence remain pending |
| Pi | Low | Extension-based; generated bridge and session parsing are covered, but host-runtime testing is limited |
| Crush | Low | Compatible with Claude Code format; only PreToolUse available |

## Community Testing Feedback

For agents marked **Low confidence**, we implemented the hook adapter based on available documentation but could not fully test all scenarios. If you use ai-guardian with these agents, please report:

- Which violation types work correctly
- Which violation types fail or behave unexpectedly
- Any hook format differences from documentation

Report via [GitHub Discussions](https://github.com/RedHatProductSecurity/ai-guardian/discussions) or [Issues](https://github.com/RedHatProductSecurity/ai-guardian/issues).

## Hook Event Name Mapping

Each agent uses different event names. The adapter layer normalizes these.

| Concept | Claude Code | Copilot | Cursor | Windsurf | Gemini CLI | Cline | Kiro | OpenCode | Crush | Antigravity | Pi |
|---------|------------|---------|--------|----------|-----------|-------|------|----------|-------|-------------|-----|
| Session start | `SessionStart` | N/A | `sessionStart` (recognized; not installed) | N/A | `SessionStart` | N/A | N/A | N/A | N/A | N/A | `session_start` |
| Before tool | `PreToolUse` | `preToolUse` | `preToolUse`, `beforeShellExecution`, `beforeMCPExecution`, `subagentStart` | `pre_run_command` | `BeforeTool` | `PreToolUse` | `pre_tool_use` | `tool.execute.before` | `PreToolUse` | `PreToolUse` | `tool_call`, `user_bash` |
| Before file read | N/A | N/A | `beforeReadFile`, `beforeTabFileRead` | `pre_read_code` | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| After tool | `PostToolUse` | `postToolUse` | `postToolUse`, `afterShellExecution`, `afterMCPExecution` | `post_run_command` | `AfterTool` | `PostToolUse` | `post_tool_use` | `tool.execute.after` | N/A (proposed) | `PostToolUse` | `tool_result` |
| Tool failure | N/A | N/A | `postToolUseFailure` | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| User prompt | `UserPromptSubmit` | `userPromptSubmitted` | `beforeSubmitPrompt` | `pre_user_prompt` | `BeforeAgent` | `UserPromptSubmit` | `prompt_submit` | `message.submit` | N/A (proposed) | `PreInvocation` | `input` |
| After edit | N/A | N/A | `afterFileEdit`, `afterTabFileEdit` | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| Lifecycle / observation | `SessionStart`, `SessionEnd`, `Stop`, `SubagentStop` | N/A | `sessionStart`, `sessionEnd`, `subagentStop`, `preCompact`, `stop`, `afterAgentResponse`, `afterAgentThought`, `workspaceOpen` | N/A | N/A | N/A | N/A | N/A | N/A | N/A | `session_start`, `session_shutdown` |

Grok Build maps `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`PostCompact`, and `SessionEnd` directly from its `hookEventName` field. Its
payload uses camelCase fields including `toolName`, `toolInput`, `toolOutput`,
`sessionId`, `toolUseId`, and `workspaceRoot`.

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
| Grok Build | JSON decision on PreToolUse | `{"decision": "deny", "reason": "..."}` |
| Gemini CLI | JSON `decision` field | `{"decision": "deny", "reason": "..."}` |
| Cline | JSON `cancel` field | `{"cancel": true, "reason": "..."}` |
| Kiro | Exit code 2 (PreToolUse) or 1 (other) + stderr | stderr = error message |
| Windsurf | Exit code 2 + stderr | stderr = error message |
| Codex | Claude-compatible envelope; `PreToolUse` deny requires `permissionDecisionReason`; `PermissionRequest` uses the Codex nested deny decision | `PreToolUse`: `hookSpecificOutput.permissionDecision = "deny"` plus a non-empty sanitized `permissionDecisionReason`; permission requests use `hookSpecificOutput.decision.behavior = "deny"` |
| OpenCode V1/V2 | V1: Claude-compatible JSON bridge; V2: domain-hook throw/mutation | V1: Claude-compatible JSON bridge; V2: thrown block or mutable `event.result` |
| Pi | Same as Claude Code | Same as Claude Code via the generated extension |
| Crush | Same as Claude Code | Same as Claude Code |
| Antigravity CLI | Flat JSON `decision` field (required — an absent decision denies) | `{"decision": "deny", "reason": "..."}`; a clean check returns `{"decision": "ask"}` |

## Agent-Facing Message Delivery

When ai-guardian detects a non-blocking issue (warn/log mode) or injects security rules, the message must reach both the user and the AI agent. Agent-facing fields carry warn/log-only messages and, for PreToolUse deny responses, a sanitized block reason so the agent can report why the operation was blocked.

**PreToolUse deny**: The agent continues after a PreToolUse deny (it tries a different approach), so it receives a sanitized summary via the agent-facing field (e.g., `"Operation blocked by ai-guardian: secret detected"`). The sanitized message contains only the violation type — no patterns, regex, or matched text. PostToolUse and Prompt blocks do NOT inject agent context since the agent stops after those.

| Agent | User-facing field | Agent-facing field | Events | Status |
|-------|------------------|-------------------|--------|--------|
| Claude Code | `systemMessage` | `hookSpecificOutput.additionalContext` | All (incl. PreToolUse deny) | Confirmed |
| Augment | `systemMessage` | `hookSpecificOutput.additionalContext` | All (incl. PreToolUse deny) | Confirmed (inherits Claude Code) |
| Codex | `systemMessage` | `hookSpecificOutput.additionalContext`; required `permissionDecisionReason` on PreToolUse deny | All (incl. PreToolUse deny) | Supported; Codex-specific reason is sanitized |
| OpenCode | `systemMessage` | `hookSpecificOutput.additionalContext` | All (incl. PreToolUse deny) | Best-effort (bridge plugin) |
| Crush | `systemMessage` | `hookSpecificOutput.additionalContext` | PreToolUse (incl. deny) | Best-effort (compatible format) |
| Cursor | `user_message` | `agent_message` | All (incl. PreToolUse deny) | Confirmed |
| Gemini CLI | `systemMessage` | `additionalContext` | Prompt, PostToolUse, PreToolUse deny (best-effort) | Confirmed |
| Cline | `errorMessage` (block) | `contextModification` | All (incl. block) | Confirmed |
| Kiro | stderr (errors) | stdout | Prompt, PreToolUse | Confirmed (process I/O) |
| Copilot | `permissionDecisionReason` (deny) | `additionalContext` | PreToolUse (incl. deny), PostToolUse | Best-effort (see bugs) |
| Grok Build | `reason` (deny) | `reason` (deny) | PreToolUse only | Limited; passive hook stdout is ignored |
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
├── grok.py              # Grok Build
├── codex.py             # OpenAI Codex (CLI + Desktop) (extends ClaudeCodeAdapter)
├── windsurf.py          # Windsurf (extends ClaudeCodeAdapter)
├── gemini.py            # Google Gemini CLI
├── cline.py             # Cline / ZooCode
├── kiro.py              # Kiro + AiderDesk + OpenClaw
├── antigravity.py       # Google Antigravity CLI
├── augment.py           # Augment Code (extends ClaudeCodeAdapter)
├── opencode.py          # OpenCode (extends ClaudeCodeAdapter)
├── pi.py                # Pi extension (extends ClaudeCodeAdapter)
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
- `hookEventName` plus Grok camelCase fields → Grok Build
- `cursor_version` → Cursor
- `kiro_hook_type` → Kiro
- `is_mcp_tool` → Augment Code
- `opencode_version` → OpenCode
- `pi_version` or `hook_source=pi` → Pi
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

Agent names: `claude`, `cursor`, `copilot`, `grok`, `codex`, `windsurf`, `gemini`, `antigravity`, `cline`, `zoocode`, `kiro`, `aiderdesk`, `openclaw`, `opencode`, `pi`, `augment`, `crush`, `junie`

Running `ai-guardian setup` without `--ide` uses the same local installation
evidence as tray health checks, verifies hook and MCP integrity, and excludes
healthy integrations from setup. If several installed integrations need setup,
the interactive command defaults to all and accepts a comma-separated selection
or `s` to skip. Use `--yes` to configure every pending integration without a
prompt. `--json` is also non-interactive and reports machine-readable setup
results. When combined with automatic setup, `--create-config` (and its
optional `--profile`) is applied once before the selected integrations are
configured.

### Config File Locations

| Agent | Config Path |
|-------|------------|
| Claude Code | `~/.claude/settings.json` |
| Cursor desktop / local CLI hooks | `~/.cursor/hooks.json` (AI Guardian install target) |
| Cursor project hooks (explicit cloud setup target) | `<project>/.cursor/hooks.json` |
| Cursor desktop / local CLI MCP | `~/.cursor/mcp.json` (AI Guardian install target) |
| Cursor local project MCP (managed by Cursor, not Cloud setup) | `<project>/.cursor/mcp.json` |
| GitHub Copilot | `~/.github/hooks/hooks.json` |
| Grok Build | `~/.grok/hooks/ai-guardian.json`; MCP: `~/.grok/config.toml` |
| OpenAI Codex (CLI + Desktop) | `~/.codex/hooks.json` |
| Windsurf | `~/.codeium/windsurf/hooks.json` |
| Gemini CLI | `~/.gemini/settings.json` |
| Cline / ZooCode | `.clinerules/hooks/` (scripts) |
| Kiro | `.kiro/hooks/` (scripts) |
| Augment Code | `~/.augment/settings.json` |
| AiderDesk | `~/.aider-desk/extensions/ai-guardian/` (extension and `ai-guardian-bridge.ts`) |
| OpenClaw | `~/.openclaw/plugins/ai-guardian/` (plugin and `ai-guardian-bridge.ts`) |
| OpenCode | `~/.config/opencode/plugins/ai-guardian.ts` and `~/.config/opencode/ai-guardian/ai-guardian-bridge.ts` |
| Pi | `~/.pi/agent/extensions/ai-guardian/index.ts` with `package.json`, or `<project>/.pi/extensions/ai-guardian/index.ts` |
| Crush | `.crush.json` (project) or `~/.config/crush/crush.json` (global) |
| Antigravity CLI | `~/.gemini/config/hooks.json` (global) or `<workspace>/.agents/hooks.json` (project) |
| Junie | `.junie/guidelines` (MCP only) |

### Malformed host configuration handling

Setup and health verification share format-aware loading for supported host CLI
configuration files. Existing JSON, JSONC, TOML, or YAML files that cannot be
parsed, or that use an invalid hook/MCP container shape, are reported with the
file path and format. `ai-guardian doctor` and tray setup health surface the
diagnostic, while setup stops before rewriting the existing host file. Missing
files remain valid setup targets.

### Host configuration backups and recovery

Before setup or MCP removal rewrites an existing host CLI configuration, AI
Guardian saves the exact original bytes beside the file as
`<config-file>.backup`. Existing backup files are never overwritten; later
snapshots use `.backup.1`, `.backup.2`, and so on. This preserves the original
pre-setup file when one flow performs more than one mutation, including
OpenCode plugin and MCP registration. Backups retain JSONC comments, trailing
commas, and the source file's permissions.

If a backup cannot be created, setup stops before changing that host file and
reports the affected path and failure in the CLI or tray result. New files,
dry runs, and already-correct configurations do not create unnecessary
backups. To recover, stop the affected host CLI, copy the desired numbered
backup back to its original configuration path, and rerun setup only after
confirming the restored file is valid.

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

Follow the applicable
[IDE/Agent Integration Checklist](IDE_INTEGRATION_CHECKLIST.md) and
[CLI/Runtime Integration Checklist](CLI_RUNTIME_CHECKLIST.md). The first
covers host integration surfaces; the second covers normal containers and
OpenShell. Keep the capability tables in this document synchronized with the
evidence collected by both checklists.

## Adding a New Violation Type

1. Implement the detector in the appropriate module
2. Add a row to the **Violation Type Coverage Matrix** with the required hooks and per-agent coverage
3. If the violation has agent-specific limitations, add a subsection under **Known Limitations**
4. Add tests covering the new violation type across adapters
