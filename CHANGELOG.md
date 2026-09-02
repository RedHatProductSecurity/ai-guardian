# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **IDE Conversations filters**: Add a searchable IDE dropdown with an "All" option for browsing conversations across every supported IDE (#2207)

- **Published documentation site**: Added MkDocs Material and Read the Docs configuration, searchable navigation, Mermaid support, generated SDK API reference, and release-time verification of versioned documentation.
  - Documentation dependencies: `mkdocs-material` (MIT) and `mkdocstrings` (ISC).

### Fixed

- **Codex conversation titles**: Ignore injected AGENTS.md instruction messages when choosing session titles and omit empty model parentheses from detail headers (#2205)
- **Web console header**: Keep the hamburger menu and header quicklinks interactive on IDE Conversations pages by removing overlapping sticky control layers (#2193)

### Added

- **Unified hook session traces**: Persist IDE hook sessions in the GuardedAgent JSON trace format, including prompts, tool calls, scan outcomes, session metadata, and `AI_GUARDIAN_RUN_ID` correlation for combined SDK and IDE pipeline views (#2190)

- **secrets**: Add credential detection for six AI service providers — Cartesia, LlamaCloud, Voyage AI, fal.ai, Mem0, and Retell AI. Prefix-only detection for distinctive formats (sk_car_, llx-); keyword-context detection for generic shapes (Voyage, fal.ai, Mem0, Retell). Adapted from [Betterleaks](https://github.com/betterleaks/betterleaks) rules (MIT) (#2185)

## [1.17.1] - 2026-08-26

### Added

- **release**: Add git-cliff for automated CHANGELOG generation
- **release**: Add automated release script
- **daemon**: Add auth token discovery for daemon targets

### Documentation

- Generalize schema export and add SDK enhancement docs

### Fixed

- **release**: Use temp file for git-cliff output insertion
- **release**: Source version from git tags for accurate calculation
- **daemon**: Bind localhost in toolbox and distrobox containers

## [1.17.0] - 2026-08-24

### Added

- **Text-as-tool-call parsing for OpenAI-compatible providers** — local models (Ollama, llama.cpp, MLX, vLLM) that write tool calls as plain text are now detected and executed automatically. The SDK extracts JSON tool-call patterns from text responses, including fenced code blocks, Python dict syntax, and multiple tool calls. Enabled by default for known local providers; opt in for others with `text_tool_parsing=True` (#2124)

- **Text-as-structured-output parsing** — when `output_schema` is set and a local model returns valid JSON matching the schema as text instead of calling `submit_result`, the SDK now accepts it directly without nudging (#2124)

- **Configurable schema nudge limit** — new `max_schema_nudges` parameter (default: 3) stops the agent loop after N failed attempts to get the model to call `submit_result`, returning `stop_reason='max_schema_nudges'` instead of burning through `max_turns` (#2124)

- **Configurable API call timeout for GuardedAgent** — new `api_timeout` parameter (constructor and `sdk.agents.*.api_timeout` config) sets per-API-call timeout in seconds. Defaults: 300s for cloud providers (Anthropic, OpenAI, Azure), 600s for local providers (Ollama, llama.cpp, vLLM). On timeout: logs warning, retries once, then stops with `stop_reason='timeout'` and returns partial result. Timeout events emitted in trace (#2097)

- **MCP server support for GuardedAgent** — configure MCP servers in `sdk.agents.*.mcpServers` to give agents access to external tools via the Model Context Protocol. Supports stdio and SSE transports, per-server trust levels and scan controls, and automatic tool discovery. MCP tools use `mcp__{server}__{tool}` naming convention. Requires Python >= 3.10 (#2084)

- **`defer_loading` for MCP servers** — delay MCP server startup until the agent first needs a tool from that server, reducing initial agent startup time when servers are slow to initialize. Configure per-server with `defer_loading: true` in `mcpServers` config (#2090)

- **Google Gemini integration** — new `gemini` provider for GuardedAgent enables using Google Gemini models with full security scanning. Supports both `google-genai` SDK and Vertex AI. Provider-specific content normalization handles Gemini's message format. Configure with `provider='gemini'` or `AI_GUARDIAN_SDK_PROVIDER=gemini` (#1865)

- **Config-driven shell hooks for agent callbacks** — new `sdk.hooks` config section allows running shell commands at agent lifecycle points (`on_start`, `on_turn`, `on_stop`). Commands receive agent context as environment variables. Useful for logging, notifications, and custom integrations (#2087)

- **Inline code annotations for false positive suppression** — suppress specific scanner findings on individual lines using `# ai-guardian:ignore <scanner>` comments. Supports all scanner types. Also available as block annotations with `# ai-guardian:ignore-start` / `# ai-guardian:ignore-end` pairs (#1664)

- **Tray plugin management UI** — manage tray menu plugins from the web console and TUI. Create, edit, delete, and reorder custom menu items. Plugin files stored in project `.ai-guardian/plugins/` directory with JSON format (#1736)

- **OpenCode plugin registration** — `ai-guardian setup` now detects and configures OpenCode IDE with appropriate hook settings (#2139)

- **`--log-violations` flag for `ai-guardian scan`** — writes findings to `violations.jsonl` (the same log used by hooks), enabling unified violation tracking from both hooks and CLI scans. Also available as `ai-guardian setup --pre-commit --log-violations` to include the flag in auto-installed pre-commit hooks (#2068)

- **Pagination with configurable search limit** — traces and IDE sessions pages now support pagination with a configurable page size. API endpoints accept `limit` and `offset` parameters. Default limit configurable via `console.search_limit` (#2125)

- **Pause auto-refresh toggle** — traces and IDE sessions pages have a pause button to stop auto-refresh, allowing text selection and copy operations without interruption (#2119)

- **Copy button on formatted modal views** — content viewer dialogs now include a copy-to-clipboard button for easy extraction of JSON and code content (#2119)

- **Error step tracking in traces** — agent errors are now captured as explicit steps in the trace viewer, showing error messages and stack traces for debugging (#2101)

- **Helpful error messages for missing provider packages** — when a provider SDK package is not installed, the error message now names the specific package to install (e.g., `pip install google-genai`) instead of a generic import error (#2081)

- **Root span at agent start** — traces now emit an initial root span when the agent starts, providing early visibility in trace viewers before the first API call completes (#2104)

### Changed

- **Console agent activity navigation**: Rename SDK Traces to Sessions and IDE Sessions to IDE Conversations, prioritizing the unified security view in the TUI and web console navigation (#2191)
  - Add top-level `tracing` configuration for recording, viewer refresh, and cache retention, with default-enabled recording and deprecated `sdk.trace_viewer` fallback
  - Document how non-SDK agents use `AI_GUARDIAN_RUN_ID` to correlate hook sessions with SDK `RunContext` runs
  - Propagate `AI_GUARDIAN_RUN_ID` from each hook process so correlation does not depend on the daemon's startup environment
  - Persist `session_id` to `run_id` bindings across daemon restarts and prefer explicit hook-event `run_id` values
  - Display stale, unfinalized trace recordings as Interrupted instead of Crashed while preserving the stored status for compatibility

- **AgentResponse for provider-agnostic normalized responses** — all provider strategies now return a unified `AgentResponse` dataclass instead of provider-specific response objects. Standardizes access to `content`, `tool_calls`, `stop_reason`, and `usage` across Anthropic, OpenAI, and Gemini providers (#2128)

- **Structured logging throughout agent lifecycle** — replaced silent `except: pass` patterns with proper `logging.warning()` and `logging.debug()` calls. All SDK exceptions now log context before re-raising or swallowing (#2133)

- **Sanitize violation messages in agent traces** — violation details written to trace files are now sanitized to remove raw secret values, replacing them with redacted placeholders (#2131)

- **Provider compatibility tables in SDK docs** — added feature comparison matrix and provider capability tables to `docs/SDK.md` (#2082)

### Fixed

- **Windows `expanduser` compatibility** — tests now set `USERPROFILE` environment variable for Windows compatibility with `os.path.expanduser()` (#2139)

- **Stale in-progress traces marked as crashed** — traces that remain in `in_progress` state beyond a timeout are now automatically detected and marked as `crashed` in the trace viewer (#2110)

- **Output schema check runs after `between_turns` hook** — previously the schema validation ran before the hook, meaning hook modifications to the response were not validated (#2096)

- **Project browse button in console** — fixed file browser dialog not opening when clicking the project browse button (#2089)

### CI/CD

- **Removed redundant post-merge test runs** — `test.yml`, `lint.yml`, and `integration-tests.yml` no longer trigger on pushes to `main`, eliminating duplicate runs after PR merges. Tests still run on pull requests (#2113)

- **Decoupled scenario tests from Quay** — scenario tests no longer require Quay container registry access, enabling them to run on fork PRs (#2135)

### Compatibility

- Verified Cursor hook compatibility with Cursor v3.17.8

## [1.16.0] - 2026-08-18

- Verified Cursor hook compatibility with Cursor v3.15.19

### Added

#### SDK & Agent Framework

- **GuardedAgent — tool-use agent loop with security scanning** — new `GuardedAgent` class provides a complete tool-use agent loop with built-in security scanning for file reads, shell commands, and tool outputs. Supports Anthropic and OpenAI-compatible providers with auto-detected response extractors. Includes `read_file`, `write_file`, `bash`, and `list_directory` built-in tools with path validation and directory blocking (#1788, #1794)

- **OpenAI provider support** — `GuardedAgent` now supports OpenAI-compatible APIs alongside Anthropic, with automatic provider detection from the client type. Includes auto-compaction for long conversations (#1848)

- **Prompt caching for multi-turn loops** — `GuardedAgent` uses sliding message cache breakpoints to keep recent context in Anthropic's prompt cache, reducing latency and cost for long conversations (#1846)

- **Auto-compaction for long conversations** — when token usage exceeds a configurable `compact_threshold`, `GuardedAgent` automatically summarizes older messages to stay within context limits. Compaction events are recorded in the trace with token metrics (#1848, #1849)

- **`between_turns` hook** — optional callback executed between LLM calls, enabling external code injection (tool results, user input, context updates) into the agent loop. Supports both `end_turn` and `tool_use` code paths (#1829)

- **Lifecycle hooks** — `on_start`, `on_end`, and `on_violation` callbacks for `guarded()` and `GuardedAgent`, enabling custom logging, metrics, and error handling (#1808)

- **`on_turn` callback and trace logging** — per-turn observability callback with structured `TurnEvent` data including model usage, tool calls, and security scan results (#1850)

- **`max_budget_tokens`** — configurable token budget limit for `GuardedAgent` that stops the agent loop when cumulative token usage exceeds the threshold (#1807)

- **Symlink support** — `follow_symlinks=True` trusts all symlinks inside `cwd`; `allowed_paths=[...]` whitelists specific external directories. Both configurable via `sdk.agents.<name>` in `ai-guardian.json` (#1907)

- **`trace_path_fn` callback** — optional callback `(agent_name, context) -> str` for organizing traces by case ID, observation ID, or run context (#1892)

- **`target_dir` for cross-repo allowlist merging** — `GuardedAgent` can load and merge allowlists from a target project directory, enabling shared scanning policies across repositories (#1934)

- **`secret_redaction_enabled` flag** — `GuardSession` now exposes `secret_redaction_enabled` so callers can check whether secret redaction is active. SDK defaults `secret_redaction` to off (hooks default to on) (#1931)

- **SDK config profile overlay** — `sdk.agents.<name>` config sections in `ai-guardian.json` override global settings per agent profile. Global and per-profile `enabled` flag controls whether SDK scanning is active (#1805, #1806)

- **Enriched `SecurityViolation`** — violation objects now include `response` (raw scan result), `sanitized_text` (redacted content), and the violation ID in the error message for cross-referencing with violation logs (#1800, #1964)

- **Violations query API** — `GuardSession.get_violations()` with `tool_use_id` and `session_id` filters for programmatic violation retrieval (#1771, #1785)

- **Trace auto-persistence** — `trace_dir` parameter enables automatic JSON trace logging to disk. Traces default to XDG state directory (`~/.local/state/ai-guardian/traces/`). Filename collision prevention for concurrent runs (#1892, #1961)

- **Nested trace format** — traces restructured into turn objects with step arrays, including `api_call` and `seq` numbering, timing data, span IDs, and enriched metadata for OTEL compatibility (#1928, #1959)

- **Compaction events in traces** — auto-compaction records token-before/token-after metrics in the trace log (#1848)

- **Blocked scans continue loop** — when a security violation is detected during an agent scan, the loop now recovers with a context-injected warning message instead of raising an exception, allowing the LLM to self-correct (#1939)

#### OTEL & Observability

- **OpenTelemetry trace export** — `ai-guardian otel export` CLI command converts agent traces to OTLP JSON format (OpenTelemetry GenAI semantic conventions). Supports Grafana Tempo and other OTLP-compatible backends (#1958)

- **Hook session OTEL export** — interactive IDE sessions now export OTEL traces via `ai-guardian otel export --session`. Works standalone without a running daemon. Session sequence numbering tracks hook invocations (#1998, #2034)

- **OTEL session telemetry** — `HookOtelEmitter` records adapter name, hook event counts, and token usage (parsed from transcripts) on root spans, so even clean sessions produce observable traces (#2010, #2011)

- **OTEL config promoted to top-level** — `otel` config section moved from `sdk.otel` to top-level `otel` for shared use by both SDK and hook exporters (#1998)

- **Custom OTEL metadata** — static metadata from config (`otel.metadata`) and dynamic metadata from callbacks attached to exported spans (#1982)

- **Rich span attributes** — project name/path, session sequence, violation details, and adapter info included in OTEL spans for full observability (#2001, #2015, #2016)

- **OBSERVABILITY.md** — new documentation covering OTEL configuration, Grafana/Tempo integration, and tracing for both SDK and interactive sessions (#2014)

#### Console (TUI & Web)

- **IDE Session viewer** — multi-IDE conversation browser in both TUI and web console. Supports Claude Code, Cursor, GitHub Copilot, Codex, Gemini CLI, and Cline sessions with step-by-step drill-down (#1983)

- **SDK Trace viewer** — live conversation monitor for GuardedAgent runs with auto-refresh, showing turns, tool calls, and security scan results (#1951)

- **Violation badges and links** — violation count badges on turn step headers link directly to the corresponding violation log entries via session_id correlation (#2021, #2022)

- **Violation detail page** — dedicated page with deep-link support (`/violations/<id>`) for cross-referencing from traces and external tools (#2002)

- **Formatted content viewer modal** — JSON and code content in session detail views displayed in a syntax-highlighted modal instead of inline truncation (#2025)

- **Sort order toggle** — ascending/descending sort for SDK Traces and IDE Sessions lists (#1993)

- **Context size display** — input tokens, cache read, and cache creation token breakdown shown in session and trace viewers (#2023)

- **Auto-refresh** — IDE Session list and detail pages auto-refresh to show new sessions and live updates (#2024)

- **SDK nav group** — new sidebar section grouping Agent Profiles and SDK Settings panels (#1957)

- **Project directory picker** — modal directory browser for selecting project scope in undiscovered projects (#1969)

- **MCP audit endpoint** — daemon REST API and console UI for viewing MCP security audit results (#1977)

#### Hooks & Scanning

- **Multi-violation reporting** — content pipeline now reports all detected violations instead of stopping at the first blocker, giving users complete visibility into all security issues in a single scan (#2026)

- **Object-form `updatedToolOutput` for Bash** — secret redaction for Bash tool results now uses the `{"stdout": text, "stderr": "", "interrupted": false}` format required by Claude Code, replacing the `additionalContext` workaround that some IDEs ignored (#2042)

- **Unified scanning pipeline (`scan_content`)** — registry-driven content scanning with 8 scanners (prompt injection, context poisoning, supply chain, output logging, canary detection, config file, secret, PII) replacing hardcoded scanner dispatch. Shared by SDK and hooks (#1927, #1932, #1933)

- **`scan_file` and `scan_command` pipeline functions** — high-level functions for scanning file content and shell commands through the unified pipeline (#1933)

- **Unified violation logging** — single `log_violation()` function replaces 10 per-scanner violation logging functions, ensuring consistent violation records across all scanners (#2020)

- **Unique violation IDs** — every violation record includes a deterministic `violation_id` for cross-referencing between traces, violation logs, and OTEL spans (#1964)

- **Detector caching** — prompt injection and unicode attack detectors are cached by config hash, avoiding re-instantiation per file/event. Reduces scan latency for repeated calls (#1952)

- **`init-project --exclude` flag** — specify additional directory exclusion patterns during project initialization (#1967)

- **`init-project --merge` flag** — deep-merge generated config into existing `ai-guardian.json` instead of overwriting (#1967)

- **Per-secret findings with column positions** — secret scanner reports individual findings with column numbers instead of just line numbers (#1813)

- **End-line tracking** — multi-line pattern matches now report both start and end line numbers (#1813)

- **`source_command` in violation records** — violation log entries include the originating shell command for better traceability (#1903)

#### Daemon

- **Kubernetes REST host env var** — `AI_GUARDIAN_REST_HOST` environment variable controls the REST API bind address, with automatic detection of Kubernetes environments to bind to `0.0.0.0` instead of `127.0.0.1` (#2045)

- **OTEL lifecycle events while paused** — daemon tracks hook events for OTEL export even when scanning is paused, preserving session telemetry continuity (#2034)

#### Security Patterns

- **Cloud & SaaS secret detection rules** — Cloudflare API tokens/keys, Figma personal access tokens, GitLab pipeline/runner/personal tokens, and Salesforce security tokens/connected app secrets (#1986)

- **16 new AI/ML provider API key patterns** — Groq (`gsk_`), xAI (`xai-`), NVIDIA NIM (`nvapi-`), New Relic (`NRAK-`), LangFuse (`sk-lf-`), LangSmith (`lsv2_pt_`/`lsv2_sk_`), Weights & Biases (`wandb_v1_`), Cerebras (`csk-`), Together.ai (`tgp_v1_`), Devin (`apk_user_`/`apk_`), Pinecone (`pcsk_`), RunPod (`rpa_`), MiniMax (`sk-api-`), Azure AD Client Secret (`Q~` marker) (#1777)

- **New AI tool config paths** — `.windsurf/rules`, `.windsurf/cascade.json`, `.openclaw/config.json` added for context file poisoning detection (#1779)

- **New credential paths for exfiltration detection** — `~/.config/gh/hosts.yml`, `~/.copilot/`, `~/.codeium/` added; detection now also catches `nc`, `wget`, `socat` as exfiltration targets (#1779)

- **SSRF IP encoding bypass protection** — normalizes hex, octal, decimal, and mixed-octet IP encodings to dotted-decimal before CIDR matching, blocking bypass attempts (#1778)

#### MCP & Integrations

- **MCP v2 `MCPServer` API** — upgraded to mcp v2 server API for compatibility with latest MCP specification (#1784)

- **Hook-check middleware for MCP clients** — MCP clients can validate that IDE hooks are properly configured before use (#1826)

- **Tray notification for missing hooks** — system tray sends a notification when IDE hooks are not configured (#1844)

#### Configuration & CLI

- **`AI_GUARDIAN_LOG_LEVEL` env var** — control log verbosity without editing config files (#1823)

- **`ai-guardian doctor` smoke-test mode** — validates config and tests all configured scanners in one command (#1818)

- **`get_config()` helper** — simplified config access function in `utils` module (#1840)

- **Matched pattern/text in prompt injection findings** — scan results now include the specific pattern and text that triggered detection (#1813)

#### Documentation

- **Quick Start simplified** — restructured to a clear 3-step flow (install, setup, verify) with console access step (#1963, #1971)

- **Developer Install section** — dedicated instructions for contributors using `uv` and editable installs (#1962)

- **OBSERVABILITY.md** — comprehensive guide for OTEL configuration, Grafana/Tempo integration, and tracing (#2014)

- **SDK comparison table** — Anthropic SDK vs Claude Code SDK feature comparison for GuardedAgent (#1997)

- **SDK docs updates** — OpenAI-compatible provider examples, tool schemas, and `guarded()` name parameter (#1788)

### Changed

- **Secrets always block** — removed configurable `action` mode from secret scanning; secrets now always block regardless of configuration (#1772)

- **SDK API simplified** — removed `action` and `scan` parameters from public SDK API; scanning is now controlled via config profiles (#1805)

- **SDK `_default` profile renamed to `*` wildcard** — config key change for the default agent profile (#1805)

- **Container image: multi-stage Dockerfile** — build optimized with multi-stage Docker build (#1790)

- **Container registry migrated** — images now published to `redhatproductsecurity` org on Quay.io (#1776)

- **Quay.io image cleanup** — replaced manual image cleanup with expiry labels (#1789)

- **Pipeline refactoring** — content scanning delegated to shared `scan_content()` function; blocking violations deferred to end of scan loop for multi-violation support (#1932, #2026)

- **Logging refactored** — module-level loggers replace root logger; routine info messages downgraded to debug level (#1802, #1823)

- **Scanner config loading centralized** — `load_scanner_config()` provides unified scanner configuration loading (#1806)

- **Path validation consolidated** — shared validation utilities extracted to `config/utils.py` (#1953)

- **OTEL architecture simplified** — violation child spans replaced by root span attributes; SDK and hook attribute naming unified (#2008, #2016)

- **OTEL emitter refactored** — file-backed `HookOtelEmitter` with flush from `violations.jsonl` instead of in-memory spans (#2038)

### Fixed

- **SDK: `between_turns` blocked injection now informs LLM** — blocked content now sends a warning message to the agent instead of being silently dropped (#1946)

- **SDK: violation ID included in `SecurityViolation` message** — violation IDs now appear in error messages for cross-referencing (#1991, #2019)

- **SDK: prompt injection violations persisted in direct mode** — violations from direct SDK usage now correctly written to violation log (#2019)

- **Hooks: `updatedToolOutput` for Bash requires object form** — bare string was silently ignored by Claude Code; now uses `{"stdout": ..., "stderr": ..., "interrupted": ...}` format (#2042)

- **OTEL: root span timestamps derived from turns** — when raw timestamps are missing, span start/end times are computed from the first and last turn timestamps instead of showing zero or multi-day durations (#2040)

- **OTEL: session reopen links traces by session_id** — reopened sessions produce linked traces instead of fragmented disconnected spans (#2037)

- **OTEL: export works when daemon is paused** — OTEL trace export no longer requires an active (unpaused) daemon (#2034)

- **OTEL: ISO 8601 Z suffix handled** — timestamp parsing no longer fails on UTC timestamps ending with `Z` (#2040)

- **Console: full content shown in session detail** — long text no longer truncated in IDE session viewer (#1996)

- **Console: empty user entries for tool results** — tool result messages no longer show as blank user entries (#1994)

- **Console: duplicate text in drill-down** — IDE session detail no longer shows the same text twice (#1995)

- **Tray: menu refreshes immediately after resume** — pause/resume menu items update without requiring a manual refresh (#1999)

- **Daemon: REST host env var respected** — `AI_GUARDIAN_REST_HOST` is now properly read for Kubernetes deployments (#2045)

- **Daemon: auto-restart watch lists updated** — file watcher covers current module layout after refactoring (#1940)

- **Daemon: process exit wait** — daemon shutdown waits for process exit instead of using a fixed sleep (#1839)

- **Daemon: pause no longer skips security instruction injection** — paused daemons still inject security instructions into sessions (#1831)

- **Agent: `between_turns` inspects structured output** — structured tool output is now scanned before injection (#1946)

- **Agent: in-loop recovery on violation** — scan violations no longer raise exceptions; agent loop continues with injected warning (#1939)

- **Scanner: directory scan performance** — `os.walk` replaces `rglob` for efficient directory pruning during scans (#1813)

- **Installer: download retry logic** — scanner download retries moved from CI shell scripts into Python installer for reliability (#1942)

### Security

- **SSRF IP encoding bypass protection** — blocks hex, octal, decimal, and mixed-octet IP encoding attacks (#1778)

- **36+ new secret detection patterns** — covers Cloud/SaaS providers (Cloudflare, Figma, GitLab, Salesforce) and AI/ML platforms (Groq, xAI, NVIDIA, Cerebras, etc.) (#1777, #1986)

- **New exfiltration detection targets** — `nc`, `wget`, `socat` now detected as exfil channels; new credential paths covered (#1779)

## [1.15.5] - 2026-08-03

### Fixed

- **Schema validation no longer requires `binary` for built-in scanner engines** — `{"type": "leaktk"}` engine config is now valid without a `binary` field; built-in engines resolve their binary name at runtime (#1760, #1762)

- **Config validation failure no longer silently drops entire config** — schema validation errors in global config now log a warning and load the config anyway instead of silently falling back to defaults, which previously disabled all permission rules, SSRF protection, and other security settings (#1761, #1765)

### Changed

- **SHA-256 checksums added to release artifacts** — GitHub release assets now include a `checksums.txt` file with SHA-256 hashes for all published artifacts (#1768)

## [1.15.4] - 2026-07-31

### Added

- **Deprecation warning for `action` on allow rules** — `ai-guardian doctor` now reports WARN when allow permission rules include a legacy `action` field; config loader emits WARNING log at startup; policy checker log level bumped from INFO to WARNING for visibility (#1752, #1755)

### Fixed

- **Web console project config resolution** — all config-consuming pages now resolve project config using the explicit `project_dir` from the header selector instead of the daemon's last-seen CWD, fixing global config leaking into project view, real project configs being ignored, and phantom configs from unrelated projects appearing (#1753, #1754)

### Changed

- Verified Cursor hook compatibility with Cursor v3.13.21

## [1.15.3] - 2026-07-30

### Added

- **Configurable terminal for tray menu actions** (Issue #1730) — new `daemon.tray.terminal_app` config option with iTerm2, CLI terminal (alacritty/kitty/wezterm), and platform-specific support (#1738)

- **Config file viewer upgrade** — JSON config card now fills available width, permission rules page added to web console (#1746)

- **Secret value redaction in violation records** — `matched_text` field in `violations.json` is now redacted before persisting, preventing plaintext secret storage (#1744)

- **Tray plugin id field** — plugins can now specify a separate `id` field for deduplication independent of display name (#1741)

### Changed

- **Repository migrated to RedHatProductSecurity/ai-guardian** — all 334 references across 40 files updated from `itdove/ai-guardian` to `RedHatProductSecurity/ai-guardian` (#1731, #1732)

- **Permission rule interaction docs** — new examples for additive allows, sandwich patterns, and merge behavior added to TOOL_POLICY.md (#1728, #1735)

- **CI dependency updates** — GitHub Actions group bumped with 6 updates (#1729)

- Verified Cursor hook compatibility with Cursor v3.13.21

### Fixed

- **Project config resolution** — `get_config_scoped()` now correctly resolves project config when `project_dir` is explicitly provided, fixing phantom config display in web console (#1749, #1751)

- **Permission rule legacy fallback** — legacy fallback no longer overrides a prior explicit allow, fixing skills being denied despite global `allow *` (#1748, #1750)

- **TUI ConfigSaveMixin bypass** — 9 TUI pages that bypassed `ConfigSaveMixin` now use the shared save/load pattern, preventing dropped config sections on save (#1745, #1747)

- **Browser auto-open on daemon restart** — web console no longer opens a new browser tab on every daemon restart during development (#1740)

## [1.15.2] - 2026-07-27

### Added

- **Daemon-routed engine testing** — `ai-guardian engine test` now routes through the daemon when running, leveraging listen-mode persistent scanners for faster test execution. New `engine_test` daemon protocol message, `POST /api/engine-test` REST endpoint, and `scan_mode` field in `EngineTestResult` (#1720, #1725)

- **Listen mode scan caching** — scan results are cached by content hash in listen mode, avoiding redundant re-scans of unchanged content for further latency reduction (#1723)

### Fixed

- **Web console engine type validation** — the web UI secret engines page now derives valid engine types from `engine_builder` presets instead of a hardcoded set, fixing rejection of `toml-patterns` and other dynamically-registered engine types (#1719, #1722)

### Changed

- **Permission denied message UX** — directory blocking messages now show all config file locations (global and project-level) and suggest project-level fixes, making it easier to resolve false positives (#1726, #1727)

- Verified Cursor hook compatibility with Cursor v3.13.21

## [1.15.1] - 2026-07-27

### Added

- **Unknown config key detection in doctor** — `ai-guardian doctor` now validates all root and nested config keys against the JSON schema, flags unrecognized keys with WARN status, and offers fuzzy "did you mean?" suggestions via `difflib.get_close_matches` (#1716)

- **Enriched violation context** — violation log entries now include `tool_name`, `source` (hook event), and `file_path` fields in the context object, providing better traceability for security incidents (#1717)

### Changed

- Verified Cursor hook compatibility with Cursor v3.12.30

## [1.15.0] - 2026-07-22

### Added

- **Transcript scanning for 7 new IDEs** — Cursor (SQLite), Cline/ZooCode (JSON), Windsurf (JSONL), Kiro (JSONL), Copilot Chat (VS Code delta journal), AiderDesk (Markdown chat history), and OpenClaw (JSONL). New `scanners/transcript/` subpackage with adapter pattern: `base.py` (ABC), `common.py` (shared scanning/dedup), per-IDE adapters. Content pipeline uses polymorphic `can_scan()`/`scan_incremental()` loop (#936, #937, #938, #939, #940, #942)

- **LeakTK listen mode — 40x scanner latency reduction** — persistent LeakTK process accepts scan requests over stdin/stdout instead of spawning a new process per hook. Reduces secret scan latency from ~200ms to ~5ms. Automatic fallback to one-shot mode if listen mode unavailable. Timeout guard prevents hangs (#1590)

- **`init-project --scan` — auto-generate config from false positive analysis** — scans project with default config, clusters findings by pattern, identifies high-frequency patterns (10+ files) as likely false positives. Generates tuned `.ai-guardian/ai-guardian.json` with allowlist patterns and `.aiguardignore.toml` with per-scanner directory ignores. `--threshold N` flag to control sensitivity. Config generation for all scanner types. TUI and web console UI for interactive configuration (#1584, #1665, #1677)

- **Language-aware false positive suppression** — auto-detects project language (Python, Go, JavaScript, TypeScript, Java, C#, Ruby, Rust, PHP) and injects language-specific overlay patterns to suppress known false positives. Pipeline-level overlay injection via `ScannerEntry` flag. Generalized to all scanners (#1585, #1662, #1674)

- **Per-file-type scanner dispatch (`skip_file_types`)** — pattern rules in secrets.toml can specify file extensions to skip (e.g., skip `.py` for patterns that only match config files). Scanner executor threads original `file_path` through to skip logic (#1586, #1653)

- **ML prompt injection one-command setup** — `ai-guardian ml setup` downloads ONNX model and tokenizer in one step. Auto-detects platform and configures ML detection (#1587)

- **PostToolUse redacted output via `additionalContext`** — when a secret is detected in tool output, redacted content is sent to the AI agent via `additionalContext` since `updatedToolOutput` is silently ignored by some IDEs. Sanitized block reason prevents leaking detection patterns (#1630)

- **Crush (Charmbracelet) IDE hook adapter** — full hook support for Crush IDE including PreToolUse, PostToolUse, Prompt, and Stop events. Config path auto-detection, response formatting, and confidence levels (#928)

- **Event-driven tray updates via push notifications** — daemon server emits SSE events on state changes (violations, stats, pause/resume). Tray client subscribes instead of polling. Reduces CPU usage and provides instant UI updates. Readiness event for deterministic startup detection (#650, #1610)

- **Scan & Configure UI in TUI and web console** — new page for running `init --scan` interactively, viewing analysis results, and applying generated configuration. Shared scan pipeline extracted for reuse (#1677, #1690)

- **Credentials-in-git-URL detection** — new pattern detects credentials embedded in `git remote` URLs (e.g., `https://user:token@github.com/...`) (#1709)

- **`token_prefixes` field in secrets.toml** — separates prefix-based token matching from keyword matching. Prefix regex derived from secrets.toml at load time (#1639)

- **`workspace_files` support and path traversal guards** — hook data can include `workspace_files` for context-aware scanning with protection against path traversal attacks (#1694)

- **30 new secret detection patterns** — coverage for HashiCorp Vault, Confluent Cloud, OpenRouter, Google Gemini API, Databricks, Datadog, DigitalOcean, Elastic, Fastly, Grafana, Linear, Netlify, PlanetScale, Pulumi, Railway, Render, Sentry, Snyk, Supabase, Terraform Cloud, Vercel, and more (#1617, #1618)

- **4 new credential format patterns** — Gemini API keys (AIza prefix), OpenRouter keys (sk-or- prefix), Vault tokens (hvs. prefix), Confluent Cloud API keys (#1633)

- **Cursor preToolUse hook event** — Cursor IDE now fires preToolUse events, enabling pre-execution scanning (#1592)

### Changed

- **Refactor: centralize language overlay config loading** — shared overlay logic moved to pipeline level via `ScannerEntry` flag instead of per-scanner implementation (#1674, #1675, #1696)

- **Refactor: switch transcript scanning to byte-offset tracking** — JSONL adapters use byte offsets instead of line counts for more reliable incremental scanning (#1672, #1695)

- **Refactor: extract shared JSONL scan logic** — `_scan_with_position_tracking()` and `_discover_path()` helpers in `common.py` reduce duplication across transcript adapters (#1604, #1608, #1673)

- **Refactor: extract shared scan pipeline** — `run_scan_pipeline()` in `scan_analyzer.py` extracted from TUI and web console for reuse (#1689, #1702)

- **Refactor: centralize rule ID mappings** — `RULE_ID_LABELS`, `RULE_ID_TO_SLUG`, and related mappings consolidated in `constants.py`. `RULE_ID_TO_SLUG` derived from existing mappings (#1687, #1688, #1699, #1703)

- **Refactor: deduplicate TUI config I/O** — `ConfigSaveMixin` extracted to eliminate repeated save/load boilerplate across TUI pages (#1684, #1697)

- **Refactor: centralize logging suppression** — `quiet_logging()` context manager extracted to shared TUI utility (#1686, #1698)

- **Refactor: centralize violation filter types** — filter type constants consolidated for consistency across TUI and web console (#1707)

- **Refactor: move MCP Security panel to Tools section** — MCP Security nav item relocated under Scanning & Analysis group in console sidebar (#1708)

- **Refactor: remove pattern server from secrets panel** — deprecated global pattern server UI removed (#1680, #1685)

- **Refactor: remove `_hp` delegation shims** — leftover hook_processing delegation wrappers removed after Phase 5 extraction (#1599, #1602)

- **Refactor: derive token prefix regex from secrets.toml** — hardcoded prefix list replaced with data-driven derivation (#1640)

- **Refactor: replace LeakTK hardcoding with capability flags** — `EngineConfig` dataclass gains data-driven capability flags instead of engine name checks (#1644, #1648)

- **Refactor: extract stderr block response into base adapter** — shared error handling moved to `BaseAgentAdapter` (#1638)

- **Refactor: rename nav menu button to Quick Links** (#1646)

- **Refactor: extract Crush hook events constant** — `CURSOR_HOOK_EVENTS` used as single source of truth (#1597, #1598)

### Fixed

- **Doctor: treat missing IDE config as "not installed"** — missing Crush/Cursor config files now report as "not installed" (skip) instead of failure, fixing false failures on CI and systems without those IDEs (#1712, #1713)

- **Daemon: load project config before pause check** — project-specific configuration now loaded before the pause guard, preventing paused daemons from dropping project directory tracking (#1700, #1705)

- **PostToolUse: duplicate block message** — `reason` and `systemMessage` no longer contain the same text when blocking tool output (#1642, #1647)

- **PostToolUse: secret scan misses env var tokens** — TOML patterns now wired into output scanning path (#1624, #1625)

- **UserPromptSubmit: scans task-notifications** — task notification content no longer triggers false positive scans (#1628, #1631)

- **Scanner executor: thread original file_path** — `skip_file_types` now uses the original filename instead of temp file path (#1653, #1668, #1679)

- **Secret scanning: reduce env var false positives** — `ALL_CAPS_IDENTIFIER` pattern no longer triggers on Python constants and shell variable assignments (#1627, #1632)

- **Warn mode: sanitize context sent to AI agents** — detection patterns, confidence scores, and matched text stripped from warn-mode messages (#1642, #1651)

- **LeakTK listen mode: timeout guard** — prevents daemon hangs if LeakTK process becomes unresponsive (#1650)

- **Stats refresh: guard against unhandled exceptions** — stats tick no longer crashes on transient errors (#1614, #1615)

- **Cursor scanner: use raw_prefix for bubble ID extraction** — fixes incorrect position tracking in Cursor SQLite adapter (#1613)

- **Flaky test: thread join instead of sleep** — `test_stats_refresh_normal_tick_no_rebuild` uses deterministic thread join (#1626, #1635)

### Security

- **30 new secret detection patterns** for cloud providers and SaaS platforms (#1617, #1618, #1621)
- **4 new credential format patterns** — Gemini API (AIza prefix), OpenRouter (sk-or-), Vault (hvs.), Confluent Cloud (#1633, #1637)
- **Credentials-in-git-URL detection** — catches `https://user:token@host` in git remote URLs (#1709)
- **Detailed `systemMessage` for warn mode** — user sees full violation details while agent receives sanitized version (#1588, #1651)
- **Verified Cursor hook compatibility with Cursor v3.11.19** — all 6 hook events confirmed firing correctly

## [1.14.0] - 2026-07-13

### Changed

- **Refactor: extract hook_processing.py into per-event modules** — monolithic `hook_processing.py` (~8800 lines) split into focused modules under `hook_events/`: `content_pipeline.py` (shared content scanning pipeline), `post_tool_use.py` (PostToolUse handler), `scanners.py` (scanner runner functions), `session_events.py` (session lifecycle handlers), `ask_mode.py` (ask-mode dialog helpers), `utils.py` (shared utilities). All public symbols re-exported from `hook_processing.py` for backward compatibility (#1491, #1551).

- **Refactor: extract secret and transcript scanning** — `secret_scanning.py` and `transcript_scanning.py` extracted from `hook_processing.py` as standalone modules (Phase 5a-5b, #1491, #1551).

- **Refactor: ScannerRegistry with pipeline-based invocation** — new `scanners/scanner_registry.py` provides declarative scanner metadata (13 scanners), hook event membership, ordering, and ask-mode support. Content scanning blocks in PreToolUse/UserPromptSubmit are now gated by `_pipeline_names` built from the registry (#1253, #1544).

- **Refactor: post-scan filter pipeline** — new `scanners/post_scan_filters.py` provides `apply_post_scan_pipeline()` for generic violation logging and ask-mode dispatch. Migrated 11 scanner blocks to the shared pipeline, deleting 4 dead helpers (#1254, #1546, #1550).

- **Refactor: extract tray into dedicated package** — `daemon/tray.py` (4000+ lines) split into `tray/` package: `app.py`, `animation.py`, `health.py`, `icons.py`, `menu.py`, `menu_builder.py`, `notifications.py`, `plugin_runner.py`, `plugins.py`. Backward-compat shims at old paths (#1543, #1547, #1561).

- **Refactor: extract config modules into subpackage** — `config_utils.py`, `config_display.py`, `config_loaders.py`, `config_writer.py`, `config_inspector.py`, `config_manager.py` moved to `config/` subpackage. Backward-compat shims at old paths (#1562).

- **Refactor: extract scanners into subpackage** — `prompt_injection.py`, `context_poisoning.py`, `secret_redactor.py`, `supply_chain.py`, `config_scanner.py`, `canary_detection.py`, `exfil_detection.py`, `offensive_language.py`, `scan_result.py`, `bandit_scanner.py`, `ast_scanner.py`, `image_scanner.py`, `ml_detection.py` moved to `scanners/` subpackage (#1562).

- **Refactor: extract setup.py into subpackage** — monolithic `setup.py` split into `setup/` package: `config.py` (default config template), `hooks.py` (IDE hook setup), `mcp.py` (MCP configuration), `rules.py` (guidelines files), `utils.py` (helpers). Backward-compat shims at old paths (#1538).

- **Refactor: extract tool patterns** — `IMMUTABLE_DENY_PATTERNS`, `MIXED_SETTINGS_PATTERNS`, `HOOK_INDICATOR_KEYS`, and `_strip_bash_heredoc_content()` extracted from `tool_policy.py` into new `tool_patterns.py` module (#1537).

- **Refactor: shared response methods in base_agent.py** — `_block_response`, `_warn_response`, `_allow_response` extracted to eliminate duplicated `format_response` branches across adapter subclasses (#1535).

- **Refactor: centralize hook event display names** — `HookEvent` enum in `constants.py` now carries `_DISPLAY_NAMES` dict and `ALL_HOOK_EVENT_DISPLAY_NAMES` frozenset. Adapters use the centralized set instead of hardcoded lists (#1549).

### Fixed

- **Config merge list deduplication** — `deep_merge()` now deduplicates list items during config merge (global + project + SDK overlay), preventing duplicate allowlist entries from accumulating (#1560).

- **Hook event fallback for unmapped events** — adapters now fall back to enum value instead of raising KeyError for hook events not in the display names map (#1548).

- **Moderator scenario expectations** — `config-exfil` and `ssrf-protection` moderator scenarios corrected to expect `block` for immutable core patterns that always block regardless of action mode (#1559).

- **CI: SHA-tagged image cleanup** — new cleanup job in `scenario-tests.yml` deletes ephemeral SHA-tagged container images after scenario tests complete (#1564).

- **CI: release readiness secrets passthrough** — `release-readiness.yml` now passes `secrets: inherit` to the `scenario-tests` job so quay.io credentials propagate to the container build step.

- **Docs: stale module paths** — updated 14 references across 6 documentation files to reflect the v1.14.0 package reorganization (mcp_server → mcp/, prompt_injection → scanners/, tool_policy → tools/policy, setup.py → setup/, daemon/tray → tray/, violation_logger → violations/logger).

- **Verified Cursor hook compatibility with Cursor v3.10.20** — `beforeSubmitPrompt`, `beforeReadFile`, and `postToolUse` confirmed firing correctly. Shell execution hooks (`beforeShellExecution`, `afterShellExecution`) verified via #1531 fix in this release.

## [1.13.3] - 2026-07-08

### Added

- **Scenario tests in CI/CD** — new `scenario-tests.yml` workflow runs all YAML-based dummy-agent scenarios (minimal, standard, strict, moderator profiles) in CI on every push and PR. Covers secret detection, PII, SSRF, tool policy, prompt injection, config exfil, and bootstrap scan (#1497).

- **Violations page: directory filter** — dropdown with browse button lets users filter the violations list to a specific daemon project directory (#1503).

- **Per-daemon stale-code indicator in tray** — each daemon entry in the tray menu now shows an orange dot when stale code is detected, making it clear which daemon needs a restart (#1510).

- **In-progress guard and restart polling in tray** — restart actions now show a spinner and poll until the daemon is back online, preventing double-clicks and giving clear feedback (#1512).

- **SessionStart support in dummy-agent** — `ai-guardian dummy-agent` can now emit SessionStart events; includes a new `bootstrap-scan.yaml` scenario demonstrating AGENTS.md poisoning detection (#1517).

- **Rebuild-image hint for remote/container daemons** — stale-code tray indicator for container/Kubernetes daemons now shows a rebuild hint instead of a restart action, which is not applicable to remote daemons (#1521).

### Fixed

- **Cursor shell execution hooks silent failure** — `beforeShellExecution` and `afterShellExecution` events were silently broken: `afterShellExecution` was misrouted to `HookEvent.PROMPT` instead of `POST_TOOL_USE`; top-level `command` field was not extracted so Bash commands were not scanned; `can_handle()` did not recognize these events when sent via `hook_event_name`. Shell commands run by Cursor are now fully scanned by tool policy and secret scanner (#1531).

- **Doctor cache path failure before first hook call** — `ai-guardian setup` now creates the cache directory proactively so `ai-guardian doctor` does not report a false failure before any hook has run (#1499).

- **Bandit silent failure** — `ai-guardian scan` now shows `⚠️  Code security scanner (Bandit) unavailable` instead of silently reporting `✅ No security issues detected` when Bandit is not importable. `ai-guardian doctor` reports `[FAIL] Bandit (code security) not found` with a reinstall hint (#1504).

- **Doctor hook coverage** — `ai-guardian doctor` now checks all 5 hook event types (UserPromptSubmit, PreToolUse, PostToolUse, SessionEnd, PostCompact) instead of only the first 3 (#1505).

- **Bootstrap scan block message formatting** — block and warn messages from bootstrap scanning now use the consistent `🚨 BLOCKED BY POLICY` style matching other violation outputs (#1513).

- **Setup: abort on config failure** — `ai-guardian setup` now exits with an error when global config cannot be written instead of silently continuing; also accepts bare profile names (e.g., `minimal`) in addition to `@minimal` (#1501).

- **SessionStart camelCase detection** — SessionStart events sent by Claude Code use `hookEventName` (camelCase) but the adapter only checked `hook_event_name` (snake_case). Both are now handled (#1522).

- **Transcript secret warnings: per-finding dedup and count** — repeated identical secret findings in a single transcript scan are now deduplicated and reported with a count instead of flooding the output (#1500).

- **SessionStart block: full message shown** — block responses from the SessionStart hook now include `systemMessage` and `additionalContext` fields so the full error message appears in the Claude Code startup hook error UI (#1526).

### Documentation

- **Hook regression testing guide** — new `docs/hook-regression-testing.md` covers dummy-agent container setup, scenario authoring, and CI integration (#1496).

- **Bootstrap scan limitation documented** — Claude Code does not support a true SessionStart hook; bootstrap scanning fires on the first UserPromptSubmit instead. This limitation is now documented in AGENTS.md and the bootstrap-scan config page (#1506).

## [1.13.2] - 2026-07-06

### Fixed

- **Container quick-start docs corrected** — README example now uses `curl` to download `run.sh` (no full repo clone required), pins image to `v1.13.2` instead of `:latest`, and includes required `ANTHROPIC_API_KEY` and `ACCEPT_PROPRIETARY_TOS=true` variables that were missing from the previous example.

## [1.13.1] - 2026-07-06

### Fixed

- **Container image: proprietary CLIs moved to runtime install with ToS consent** — Claude Code (Anthropic, All Rights Reserved) and Kiro CLI (AWS proprietary) were installed at image build time, violating redistribution restrictions. Both CLIs are now installed at container first-start after the user explicitly accepts the respective Terms of Service. Set `ACCEPT_PROPRIETARY_TOS=true` to bypass the interactive prompt in CI/automation. Open-source CLIs (OpenCode, Gemini CLI, Codex CLI, OpenClaw) remain in the Dockerfile (Issue #1495).

## [1.13.0] - 2026-07-06

### Added

- **Bandit and Semgrep code security scanners** — detect insecure code patterns in files being written or edited (hardcoded credentials, `eval()`/`exec()`, weak crypto, SQL injection sinks). Available via optional `[code-security]` extras; scanner auto-detects availability and fails gracefully if missing. New **Code Security** page in TUI and web console shows scanner status and findings. SARIF output for downstream consumers. Enabled in `@strict` profile; disabled in all other profiles (Issue #828).

- **Container image on quay.io** — `quay.io/itdove/ai-guardian:<version>` published on every release tag via new `build-container.yml` CI/CD workflow; `:latest` updated on every merge to `main`. `support/` directory renamed to `container/`; includes smoke-test YAML scenarios for secret detection, PII, ask dialog, and tool policy (Issue #1423).

- **Kubernetes deployment** — Kustomize-based manifests with base + overlays for Kind (local/CI, NodePort), OpenShift (Route CRD), and production (LoadBalancer). Kind overlay includes cluster config for local testing. Docs at `docs/kubernetes.md`. Kind-based CI test validates remote daemon and ask dialog forwarding end-to-end (Issue #1428).

- **Ask dialog forwarding from remote daemon to host tray** — container/Kubernetes daemon queues ask prompts; host tray polls every 2.5s and presents the full dialog locally (NiceGUI browser tab on macOS, auto-select on Linux). Decision returned to daemon via REST; hook continues with user's choice. New REST endpoints: `GET /api/pending-prompts`, `POST /api/prompt-decision`, `POST /api/register-tray` (Issue #1342).

- **Dummy-agent for LLM-free hook testing** — new `ai-guardian dummy-agent` command: interactive REPL that simulates all Claude Code hook events (PreToolUse, PostToolUse, UserPromptSubmit, Stop, Notification) using YAML scenario files, no LLM required. Bundled scenarios for secret detection, PII, tool policy, and ask dialog (Issue #1438).

- **@moderator built-in profile** — all action policies set to `ask`, requiring human-in-the-loop approval before every tool call. Maximum-oversight mode for sensitive workflows. Available via `--profile @moderator` (Issue #1422).

- **MCP server installed by default** — `ai-guardian install` now configures the MCP server automatically; `--mcp` flag removed. All new installations include MCP capabilities out of the box (Issue #1377).

- **Security Instructions page** — new TUI and web console config page for defining agent context injection rules. Each rule specifies triggers and content injected into the agent system prompt at hook time. Profile templates include default security instruction sets (Issue #1460).

- **Bootstrap scanning** — on new session start, ai-guardian scans agent config files (AGENTS.md, agent config JSONs) through the full violation pipeline, catching policy violations and secrets before any agent code runs. Triggers once per session (Issue #1394).

- **ML Engines setup wizard** — step-by-step onboarding wizard on the ML Engines config page in both TUI and web console: dependency check → engine selection → model download. Replaces the previous static form that gave no onboarding guidance (Issue #1474).

- **Per-field help tooltips** — all TUI and web console config pages now show a `(?)` icon next to each section and field. Opens contextual help inline without leaving the page. Centralized in `help_content.py`; reusable `help_panel.py` component for the web console (Issue #1472).

- **Contextual help per scanner page** — each scanner page in the web console includes a "Learn More" help panel; TUI scanner views include a Documentation link. All 12 scanner pages covered via centralized `help_content.py` module (Issue #1463).

- **Daemon REST port auto-retry** — if port 63152 is already bound (e.g. by an orphan daemon), the daemon automatically tries the next 9 consecutive ports (63152–63161). First free port wins. `ai-guardian doctor` probes the actual bound port (Issue #1469).

- **6 new secret patterns** — `huggingface-access-token` (`hf_` prefix, 34 chars), `huggingface-organization-api-token` (`api_org_` prefix), `github-fine-grained-pat` (`github_pat_` + 82 chars), `github-user-token` (`ghu_` prefix), `aws-amazon-bedrock-api-key-long-lived` (`ABSK` prefix, 109–269 base64 chars), `perplexity-api-key` (`pplx-` prefix). Sourced from Gitleaks community config (MIT). Secret count: 53 → 59 (Issue #1482).

- **SSRF: Alibaba Cloud and Oracle Cloud metadata blocking** — `100.100.100.200` (Alibaba Cloud) and `192.0.0.192` (Oracle Cloud/OCI) added as immutable SSRF block patterns. WebFetch tool calls to these IPs also blocked. Legitimate `100.x` public IPs unaffected (Issue #1483).

- **Config exfil: glob pattern support and Copilot/Kiro targets** — `_is_config_file()` now accepts glob patterns for wildcard path matching. `.github/copilot-instructions.md` and `.kiro/steering/*.md` added to `DEFAULT_CONFIG_FILES` as persistence-multiplier targets (Issue #1484).

- **Canary token detection** — new `canary_detection` config section detects user-registered tripwire values in AI output to catch data exfiltration. Supports exact-value and regex matching; bypasses entropy thresholds unlike the secret scanner, making it effective for low-entropy strings. Disabled by default. New `canary_detected` violation type in constants, violations log, TUI, and web console. Wired into PreToolUse, PostToolUse, and UserPromptSubmit hooks (Issue #1392).

- **Offensive language scanner** — new `scan_offensive` config section detects profanity, slurs, and non-inclusive terminology in code, comments, and variable names. Disabled by default. Three categories: `profanity`, `slurs` (on by default when enabled), `inclusive_language` (opt-in). Includes `suggestion` field for inclusive replacements. Works with `.aiguardignore.toml`, ask mode, and allowlists (Issue #1417).


- **Verified Cursor hook compatibility with Cursor v3.10.11** — all 5 hook events (beforeSubmitPrompt, beforeReadFile, beforeShellExecution, afterShellExecution, postToolUse) confirmed firing correctly.

### Changed

- **Dev-mode auto-restart removed** — daemon no longer watches file mtimes and auto-restarts in dev mode. Eliminates orphan daemon processes and partial-write crashes caused by mid-operation restarts. Tray shows a stale-code warning instead (Issue #1465).

### Fixed

- **Allowlist bypassed when scanner returns line_number=0** — hook processing used `line_number` as the key to look up the secret text; `line_number=0` resolved to nothing, so every such finding bypassed the allowlist. Fix falls back to `matched_text` from the scanner result (Issue #1476).

- **Tray restart double-click spawned orphan daemons** — rapid double-click on Restart tray menu item spawned two daemons simultaneously, both binding the same port, leaving both as orphans. Fix disables the menu item on first click and re-enables it after restart completes (Issue #1473).

- **Headless env detection incorrect in SSH sessions** — `_is_headless_env()` returned `True` when no `$DISPLAY` was set, causing Textual TUI to be skipped even in SSH sessions with a real TTY. Fix adds explicit TTY detection; headless path only taken when no TTY is present AND running in a container (Issue #1448).

- **Hook timeout too short for ask mode** — extended from 30s to 300s; fail-closed on timeout (Issue #1445).

- **Allow Once persisted for entire session** — the dedup fix in #1427 over-cached allowed findings, making Allow Once suppress findings for the full session. Fix scopes the allowed-findings cache to the current hook invocation only (Issue #1439).

- **Double ask dialog on UserPromptSubmit** — scanning transcript and message body independently produced duplicate findings for the same secret, presenting two Allow dialogs. Fix deduplicates ask-mode findings by `matched_text` before showing dialogs (Issue #1427).

- **Daemon orphan accumulation in dev mode** — race in `_cleanup_stale()` allowed multiple daemon processes to start concurrently. Fix makes the PID file the authoritative restart signal; only one process can claim it atomically (Issue #1425).

- **Prompt injection settings missing ml and hybrid detector options** — `ml` and `hybrid` detector types were absent from the web console and TUI prompt injection pages, requiring manual JSON edits. All four detector types now selectable in all UI surfaces (Issue #1419).

## [1.12.3] - 2026-06-29

### Fixed

- **SHA hash values trigger false positive secret detection** — added entropy and stopword filtering to prevent SHA-256/SHA-512 commit hashes and checksums from being flagged as secrets (Issue #1378)
- **IGNORE_FILE decision in multi-finding ask mode** — correctly handle "Ignore File" action when multiple findings are present in ask dialog (Issue #1387)
- **Project dir override in prompt-ask handler** — set project directory override in prompt-ask handler so config writes target the correct project scope (Issue #1381)
- **Cursor hook test settings dict key path** — correct the settings dictionary key path in cursor hook test to match actual structure (Issue #1386)

## [1.12.2] - 2026-06-26

### Added


- **Project directory selector in web console header** — dropdown to select active project scope for all daemons, populated from daemon stats (Issue #1359)
- **Half-moon tray icon for partially paused daemons** — shows distinct icon when some directories are paused but daemon is running (Issue #1365)
- **Bug report and feature request issue templates** — structured GitHub issue templates for consistent reporting (Issue #1373)

### Fixed

- **Rich markup escaping in TUI** — escape square brackets in violation text to prevent Rich markup interpretation errors; add warning prefix to warn/log-only messages (Issue #1375)
- **Web console auto-restart when dead** — auto-restart web console process before opening panels if it died unexpectedly (Issue #1372)
- **Performance settings for remote daemons** — performance page now correctly loads/saves latency settings for remote daemon targets (Issue #1369)
- **NiceGUI storage path in read-only containers** — use temp directory for `.nicegui` storage when CWD is read-only (Issue #1368)
- **Concurrent dev daemon restart cooldown** — prevent rapid restart loops when multiple panels trigger daemon restarts simultaneously (Issue #1367)
- **REST endpoints track project directories** — SDK and scan REST endpoints now register project directories for daemon stats (Issue #1362)
- **Web console remote daemon config routing** — config reads/writes correctly route through DaemonService for remote daemons instead of reading host filesystem (Issue #1355)
- **Publish workflow: test tags no longer publish to production PyPI** — merged `publish.yml` and `publish-test.yml` into single workflow that routes to TestPyPI or PyPI based on tag format (`v*-test*` → TestPyPI, `v*` → PyPI)
- **Release skill: cursor-verify-setup places hooks inside `hooks:{}` object** — debug hooks were placed at JSON top level where Cursor ignores them; now correctly added inside the `hooks` object

## [1.12.1] - 2026-06-24

### Changed

- **README install URLs point to release tag** — install commands now reference `v1.12.1` instead of `main` branch, ensuring stable installations from PyPI match the tagged source

### Fixed

- **Release skill: install URL update must happen before tagging** — moved README URL update step before tag creation so PyPI receives correct URLs in package README
- **Release skill: added TestPyPI verification step** — recommended pre-tag check to catch README rendering issues before publishing to production PyPI

## [1.12.0] - 2026-06-24

### Added

- **Exfiltration behavior detection** — new `exfil_detection` config section catches bash commands that steal credentials: curl/wget with token vars, base64 encoding of secrets, SSH key file piped to network, cloud credential exfil (AWS IMDS, GCP metadata), and environment variable collection. 6 pattern categories: credential_theft, env_collection, key_file_exfil, base64_encoding, cloud_credential_exfil, secret_collection. Complements `config_file_scanning` with broader behavioral coverage. New `exfil_detection` violation type in constants, violations log, TUI, and web console. Wired into PreToolUse Bash hook. Also scans shell scripts (.sh/.bash/.zsh) in batch scan mode (Issue #1393).

- **Interactive "ask" action mode** (Issue #1115)
  - New `action: "ask"` config option for secret_scanning, prompt_injection, scan_pii, context_poisoning, ssrf, directory_rules, tool_permissions, supply_chain, and config_scanner
  - When a violation is detected, shows an interactive dialog with Allow Once / Allow Always / Block choices
  - "Allow Always" opens a pattern editor to craft and validate allowlist patterns before adding to config
  - Supports compound syntax `ask:warn` or `ask:log-only` to set headless fallback behavior
  - Three-tier dialog cascade: tkinter (native popup) → NiceGUI (browser) → Textual (terminal) → headless fallback
  - Pattern editor reuses regex tester logic with ReDoS validation and config preview
  - Safe config writer with file locking for concurrent hook subprocess writes
  - Added `action` property to `secret_scanning` config section (previously always blocked)
  - "Allow Always" support for permission rules, supply chain, config file scanning, and directory rules
  - View File button in violation ask dialogs to open file at violation line (Issue #1176)
  - Show hook event (PreToolUse/PostToolUse/Prompt) in ask dialog (Issue #1289)
  - Show tool name and filename in ask dialog title (Issue #1317)
  - Show line numbers in ask dialog file references
  - Unified ask-mode routing via `_handle_ask_mode_auto` dispatcher (Issue #1315)
  - Ask dialog tracking in daemon stats and tray menu
  - Preferred UI toolkit selection via `preferred_ui` config option (Issue #1135)

- **Agent-facing message delivery** (Issue #1337)
  - Hook adapters now deliver sanitized block reasons and security warnings to AI agents
  - Messages routed via `additionalContext` (Claude Code), `agent_message` (Cursor), or equivalent fields per IDE
  - Block reasons sanitized via `_sanitize_block_reason()` to prevent leaking detection patterns (Issue #1341)
  - Warn/log-only messages stripped of regex patterns, confidence scores, and matched text (Issue #1324, #1327)

- **Multi-finding support** (Issue #1296)
  - Accumulate all findings per scan instead of stopping at first match
  - Multi-finding ask dialog shows per-finding decisions with aggregate result
  - PromptInjectionDetector.detect() now collects all matches (Issue #1316)

- **Column position tracking** (Issue #1261, #1280, #1281, #1291)
  - Column-level location info in violation reports across all scanner types
  - Column numbers displayed in ask dialog, web console, and TUI violations view
  - Added to prompt injection, context poisoning, PII, SSRF, config exfil, and supply chain detectors

- **Per-project config caching** (Issue #1227)
  - Each project gets its own config cache keyed by project directory
  - Config cache status dashboard in TUI and web console (Issue #1231)
  - Force reload clears per-project caches (Issue #1310)
  - Config cache invalidated after ask dialog saves patterns (Issue #1309)

- **Effective config display with provenance** (Issue #1259)
  - Deep-merged view of global + project config with per-key source annotations
  - Available in TUI and web console

- **PostToolUse scanning expansion** (Issue #1285, #1284)
  - Prompt injection and context poisoning scanning on PostToolUse output
  - Context poisoning detection extended to file reads (BeforeReadFile events)

- **Supply chain scanning panel** (Issue #1133)
  - New TUI and web console pages for supply chain scanning configuration
  - Toggle enable/disable, action mode, and view violations

- **Violation rescan and allowlist** (Issue #1146)
  - Rescan files at violation location to retrieve matched text
  - "Allow Always" button directly from violations view

- **Source annotation editor** (Issue #1246)
  - Enhanced editor with line numbers and syntax highlighting
  - "Suppress in Source" adds inline `ai-guardian:allow` annotations

- **Scanner filtering** (Issue #1286, #1292)
  - `ignore_tools` and `ignore_files` filtering for all security scanners
  - UI controls in TUI and web console scanner pages

- **Secret scanning enhancements**
  - Keyword, entropy, and stopword filters for secret and pattern scanning
  - Stopword/entropy filtering for external scanner findings (Issue #1245)
  - TOML regex flags honored in secret pattern compilation (Issue #1262)
  - Entropy and stopword settings added to profile templates

- **SSRF protection enhancements** (Issue #1134)
  - Regex pattern support in `allowed_domains` configuration
  - ReDoS validation on regex patterns before compilation

- **Inline text and stdin scanning** (Issue #1260)
  - `ai-guardian scan --text "content"` for inline scanning
  - `echo "content" | ai-guardian scan -` for stdin pipe scanning

- **SDK config overlay** (Issue #1139)
  - Config overlay with deep-merge support via environment variable or inline dict

- **Cursor IDE compatibility** (Issue #1180, #1181, #1198, #1219, #1220)
  - Native Cursor `hooks.json` support instead of shared Claude settings
  - Tool name synthesis for Cursor event-based hooks
  - Hook dedup to prevent double-fire when Cursor reads Claude Code hooks
  - Cursor hook compatibility verification in release workflow
  - Doctor check for stale Cursor hooks
  - Legacy Cursor hook cleanup during Claude setup

- **Daemon improvements**
  - Pause state persistence across daemon restarts (Issue #1319)
  - `daemon reset` command for clean recovery from broken state
  - Auto-restart daemon on source file changes in dev mode
  - Daemon idle timeout disabled by default
  - Atomic PID writes and thread-safe stop
  - Version number display in TUI and web UI

- **Doctor and installer enhancements**
  - AST scanner health check in doctor
  - INSTALL_GOBJECT flag and post-install GObject availability check for Linux
  - JSON schema for `.aiguardignore.toml` with Taplo IDE support

- **MCP server enhancements**
  - `operation` parameter added to `check_path` MCP tool (read/write/edit)
  - Fixed `tool_input` key usage in MCP server hook_data

- **Image scanning** violation type mappings for `.aiguardignore.toml`

### Changed

- **Unified ask-mode routing** (Issue #1318) — single `_handle_ask_mode_auto` dispatcher replaces per-scanner ask handling
- **Refactored ask dialog** — tier implementations extracted into separate modules (`ask_dialog_tk.py`, `ask_dialog_textual.py`, `ask_dialog_nicegui.py`)
- **Unified visual theme** (Issue #1288, #1300) — shared theme constants and helpers across tkinter, NiceGUI, and TUI
- **Unified prompt subcommand** — `tray-prompt` and `ask-prompt` merged into single `prompt` subcommand
- **PII detection removed from TomlPatternsScanner** — PII scanning handled by dedicated PII scanner
- **Regex conversion removed from pattern editor** — patterns written as-is to config sections
- **Log levels audited across codebase** (Issue #1298) — dev-mode restart errors logged at ERROR, consistent levels throughout
- **Tray menu reorganization** — Stop/Restart/Upgrade grouped into Maintenance submenu
- **Documentation** — Claude Code upstream hook limitations documented (Issue #1335), last-match-wins rule evaluation order documented (Issue #1338)

### Fixed

- **Security: warn/log-only message sanitization** (Issue #1324, #1327) — detection patterns, regex, matched text, and confidence scores no longer leaked to AI agents in warn/log-only modes
- **Security: agent-facing message fields** (Issue #1339) — correct field names and block behavior across all IDE adapters
- **Security: logging.disable for Cursor re-enabled** — `logging.disable(logging.CRITICAL)` now properly re-enabled in finally block, preventing permanent logging loss in daemon
- **Security: ask dialog BLOCK honored for secrets** — user clicking "Block" now blocks the operation instead of falling through to redaction
- **Security: SSRF allowed_domains ReDoS validation** — regex patterns in `allowed_domains` validated for ReDoS safety before compilation
- **Security: config writer file locking on Windows** — `msvcrt.locking` fallback when `fcntl` unavailable
- **Security: REST API /api/check sanitization fallback** — no longer returns original content when sanitization fails
- **SecretRedactor position drift** (Issue #1228, #1235) — three-phase redaction engine eliminates position drift in multi-match scenarios
- **Per-project config cache isolation** (Issue #1227, #1307, #1308, #1309, #1310) — correct project directory used instead of daemon CWD, cache invalidated after saves, force reload clears all caches
- **PromptInjectionDetector stops at first match** (Issue #1316) — now collects all subsequent injections
- **Inline-allow suppresses annotated line and next line** (Issue #1243) — correct scoping for multi-line findings
- **Permission patterns merged into existing rules** (Issue #1192) — "Allow Always" merges into existing matcher instead of creating duplicates
- **Config section defaults merged** — defaults merged instead of replaced, preventing loss of existing settings
- **Config show displays auto-generated directory rules** (Issue #1333)
- **Scanner installer Windows path handling** (Issue #1293) — correct path separators for Windows binaries
- **Ask dialog macOS threading** — dialog delegated to subprocess to avoid NSApplication thread hang
- **Ask dialog layout stability** — TK widget packing reordered for stable layout
- **PII text in ask dialog** — actual PII text shown instead of warning message
- **Daemon state cleanup** (Issue #1305) — state files cleaned when stop() called before _running set
- **Daemon lifecycle hardening** — atomic PID writes, thread-safe stop, tray process wait
- **SDK check_file double-append** — `try/finally` ensures results list stays consistent when SecurityViolation raised
- **Latency logger rotation race** — rotation now runs inside lock, preventing data loss under concurrent writes
- **diff_provider timeout handler** — `subprocess.TimeoutExpired` caught in `_detect_default_branch()`
- **Pause persistence wall-clock drift** — remaining duration clamped to prevent negative values on macOS suspend/resume
- **Ask dialog config write safety** — `_write_config_text` now routes through `_atomic_config_update` with JSON validation
- **AskResult dataclass** — `per_finding_results` field declared instead of monkey-patched
- **Cursor pre_tool_use response format** aligned with hook spec
- **Empty hook files deleted during uninstall**
- **Base64 image data stripped** before unicode/injection scanning
- **Annotation pair syntax corrected**
- **PII action set to block** when ask dialog returns Block
- **NiceGUI web tests skipped on Python 3.9**
- **Security: heredoc bypass of immutable Bash deny patterns** (Issue #1350) — raw (un-stripped) command checked against immutable deny patterns to prevent heredoc bypass
- **Ask-mode block decisions logged to violations.jsonl** (Issue #1348) — user block choices in ask dialogs now create violation log entries
- **CI: lint workflow enforces on PRs** (Issue #1349) — correct paths, removed continue-on-error, exit code enforcement
- **Verified Cursor hook compatibility with Cursor v3.8.11**

## [1.11.1] - 2026-06-11

### Added


- **Curl file upload exfiltration detection** (Issue #1101)
  - Detect `curl -F`, `curl --upload-file`, and `curl -T` patterns targeting external hosts
  - New config-exfil patterns for file upload via HTTP

- **Web console: auto-scroll active sidebar item into view** (Issue #1104)
  - Active navigation item scrolls into view on page load

- **Daemon Python resolution and version sync** (Issue #1103)
  - Improved Python executable resolution using `shutil.which` for reliable path discovery
  - Version sync between daemon and tray processes

### Fixed

- **Web console: defer codemirror editor initialization** (Issue #1102)
  - Fix duplicate nicegui-codemirror ESM module assertion error

- **Web console: make sidebar sticky with scrollable navigation** (Issue #1104)
  - Sidebar stays fixed while content scrolls

### Changed

- **README: curl install.sh should reference release tag, not main branch**
  - Install command URLs now point to versioned release tags

- **CI: add release-* branch trigger to workflows** (Issue #1108)

## [1.11.0] - 2026-06-11

### Added


- **Supply Chain Scanning** (Issue #1055)
  - New violation type `SUPPLY-CHAIN-001` for detecting malicious patterns in agent configuration files
  - Scans hooks (Claude, Cursor, Copilot, Codex, Windsurf, Gemini, Augment), MCP server configs, and plugin files (OpenCode, AiderDesk)
  - 8 detection categories: download-and-execute, obfuscation, env hijacking, network exfiltration, MCP suspicious commands, config key hijacking, reverse shells, plugin dangerous APIs
  - Active in all 3 hooks: UserPromptSubmit (pasted config), PreToolUse (write to config), PostToolUse (read poisoned config)
  - CLI: `ai-guardian scan --agent-configs` scans known agent config paths
  - TUI and Web console toggles with block/warn/log-only action modes
  - Self-allowlist: ai-guardian's own plugin files never flagged
  - Default action: `block` (low false-positive risk due to path-specific + pattern-specific targeting)

- **Hook Latency Metrics** (Issue #1057)
  - Per-hook (PreToolUse/PostToolUse/UserPromptSubmit) and per-violation-type timing instrumentation
  - New `latency_tracking` config section (disabled by default, opt-in for debugging)
  - CLI: `ai-guardian metrics --latency` with avg/stddev/P95/min/max statistics
  - Web Console: new "Performance" page under Monitoring with sortable tables and latency threshold highlighting
  - TUI Console: new "Performance" panel with hook latency and per-check breakdown tables
  - Data stored in append-only `latency.jsonl` alongside violations.jsonl with configurable retention

### Changed

- **Docs: prefer uv over pip in install instructions** (Issue #1051)
  - Flipped uv/pip order across README.md, AGENTS.md, and docs/ files
  - uv shown as recommended, pip as alternative — matches install.sh behavior

### Added


- **Hook-pipeline smoke tests for SSRF, config exfil, and password** (Issue #1017)
  - PreToolUse: SSRF detection in Bash commands (`curl` to metadata endpoint)
  - PreToolUse: Config exfiltration in Bash commands (`env | curl` pattern)
  - UserPromptSubmit: Password detection in user prompts via toml-patterns engine

- **Generic password/secret assignment detection** (Issue #1015)
  - New TOML pattern `generic-password-assignment` detects `password = "value"` format
  - Covers: password, passwd, secret, secret_key, api_secret, db_password, db_passwd
  - Case-insensitive matching, supports both single and double quotes
  - Minimum 8-char value length to avoid short-value false positives
  - Uses `env_not_file_path` validator to skip file paths and placeholders

- **Smoke test workflow** (Issue #1006)
  - New `.github/workflows/smoke-tests.yml` covering all 16 violation types
  - Detection tests via `ai-guardian scan`: secrets, PII Phase 1+2, prompt injection, jailbreak, SSRF, config exfil, context poisoning
  - Hook pipeline tests via `process_hook_data()`: PreToolUse (secret deny, directory block), PostToolUse (redaction), UserPromptSubmit (injection)
  - False positive checks: clean Python, env var PATH, pytest tracebacks
  - Triggers: pull_request to main, workflow_call, workflow_dispatch
  - Release-readiness.yml now calls smoke-tests via `workflow_call` instead of inline detection-end-to-end job

- **ML-based prompt injection detection** (Issue #185)
  - Multi-engine ML detection using ONNX models running in daemon process
  - New detector modes: `ml` (ML-only) and `hybrid` (heuristic + ML for uncertain cases)
  - Multi-engine execution strategies: `first-match`, `any-match`, `consensus` (mirrors secret scanning pattern)
  - Configurable `fallback_on_error`: `heuristic` (default), `block`, or `allow`
  - Default model: `protectai/deberta-v3-base-prompt-injection-v2` (DeBERTa v3, ~370 MB)
  - New CLI: `ai-guardian ml download|list|status|verify`
  - New daemon endpoints: socket `ml_detect`, REST `POST /api/ml-detect`, `GET /api/ml-status`
  - Doctor health check for ML dependencies and model availability
  - `tokenizers` moved to main dependencies (Python 3.10+); `onnxruntime` bundled via `rapidocr-onnxruntime` (Python < 3.13)

### Fixed

- **Tray: keep menu items enabled when daemon is idle-stopped** (Issue #999)
  - Console, Violations, Metrics & Audit, Statistics, and About menu items now stay enabled when the daemon is idle-stopped but auto-restart is possible
  - Clicking an enabled item auto-starts the daemon (via existing `_check_and_autostart_daemon()`) then opens the requested view
  - Items remain grayed out when the daemon was explicitly stopped (`daemon.stop-requested` marker) or when running in embedded (non-standalone) mode
  - Added `_can_autostart_daemon()` helper that checks standalone mode and stop-requested marker
  - `_check_and_autostart_daemon()` now returns bool indicating if daemon is ready after the call

- **Replace unmaintained `toml` package with `tomli-w` for TOML writing** (Issue #969)
  - Replaced undeclared `toml` dependency (unmaintained since Dec 2020) with `tomli-w>=1.0.0`
  - TOML reading now uses `tomllib` (stdlib 3.11+) / `tomli` (backport), matching the rest of the codebase
  - TOML writing uses `tomli_w.dump()` with binary mode
  - Removed `toml is None` fallback guards (both libraries are now declared dependencies)

### Added


- **Expand toml-patterns with platform-specific secret rules** (Issue #972)
  - Added 8 new gap-filling rules for platforms not covered by gitleaks/leaktk engines
  - **Payment/Financial**: Square OAuth Secret (`sq0csp-`), PayPal/Braintree Access Token (`access_token$`), PayPal Client Secret (context-based)
  - **CI/CD**: CircleCI API Token, Jenkins API Token (context-based with hex validation)
  - **Database**: MongoDB Atlas API Key (UUID format with context), Supabase Service/Anon Key (JWT with context)
  - **AI/ML**: Replicate API Token (`r8_` prefix)
  - Updated `token_not_placeholder` validator to support `sq0csp-` and `r8_` prefixes
  - Audited all 6 issue categories against gitleaks rule set; 15 platforms already covered by gitleaks skipped
  - secrets.toml now contains 52 rules (up from 44)
  - 24 new tests covering detection, false positive resistance, and placeholder rejection

- **Secret liveness validation** (Issue #971)
  - After pattern-match detection, optionally validate secrets against their provider API to check if they're still active
  - **Built-in validators** for 6 services: GitHub tokens, OpenAI API keys, Anthropic API keys, Slack tokens, GitLab tokens, npm tokens
  - **Custom validators** via TOML pattern rules using `live_validation = { url, auth, expect }` syntax
  - **Result categories**: `verified` (active, block), `unverified` (no validator, block), `inactive` (revoked/expired, warn only)
  - **Opt-in only** (`secret_scanning.validate_secrets: true`) — privacy-sensitive, sends secrets to provider APIs
  - New config options: `validate_secrets`, `validation_timeout_ms`, `on_inactive`
  - Parallel validation with configurable timeout (default 3000ms)
  - Integration at all secret detection paths (strategy, legacy subprocess, fallthroughs)
  - 65 new tests covering all validators, batch validation, filtering, and hook integration
  - New `validation_status` field on `SecretMatch` dataclass

- **Per-directory pause for daemon scanning** (Issue #958)
  - Pause scanning for a specific project directory without affecting other projects
  - `DaemonState`: new `pause_dir()`, `resume_dir()`, `is_dir_paused()`, `get_paused_dirs()` methods
  - CLI: `ai-guardian daemon pause --dir /path [--minutes N]` and `ai-guardian daemon resume --dir /path`
  - CLI: `ai-guardian daemon pause [--minutes N]` and `ai-guardian daemon resume` for global pause/resume
  - Socket protocol: new `pause_dir` / `resume_dir` message types
  - REST API: new `POST /api/pause_dir` and `POST /api/resume_dir` endpoints
  - `daemon status` now displays paused directories with remaining time
  - Global pause takes precedence; per-dir pause is independent
  - Time-limited per-dir pauses auto-expire like global pauses
  - Protocol: new `make_pause_dir()` / `make_resume_dir()` message factories
  - Client: new `send_pause_dir()` / `send_resume_dir()` functions
  - 21 new tests covering state, protocol, and server integration

- **Web and TUI console panel for auto_directory_rules** (Issue #966)
  - New "Auto Directory Rules" page in web console under Permissions sidebar group
  - Toggle enabled/disabled and allow_symlinks settings
  - Read-only preview of discovered skills, matched skills, and generated directory rules
  - Status indicators: directories scanned, skills discovered, skills matched, rules generated
  - Skill permission patterns display (from permissions.rules[Skill] allow rules)
  - Scanned directories listing with all standard IDE skill locations
  - Matching TUI panel with switches, status display, and rules list
  - 33 new tests (14 web, 19 TUI) covering imports, routing, sidebar, generator, and config save

- **Support bundle email destination (SMTP)** (Issue #932)
  - Email as a support bundle destination alongside S3, GCS, and local filesystem
  - `_zip_bundle()` helper zips all bundle files into a single attachment
  - `_send_to_email()` with MIME multipart message and zip attachment
  - Three auth methods: `none` (corporate relay), `env` (environment variables), `inline` (hardcoded, doctor warns)
  - STARTTLS (port 587) and implicit SSL (port 465) support
  - Zip size check with warning when >10 MB
  - Fallback: opens system `mailto:` handler when no SMTP host configured
  - `mailto:` and `@` destination detection in `send_bundle()`
  - Doctor `check_email_auth` warns for inline credentials and missing SMTP host
  - Config schema, setup.py, example config, and all profiles updated
  - Zero new dependencies (Python stdlib: `smtplib`, `email.mime`, `zipfile`)
  - 26 new tests covering all auth methods, TLS modes, errors, and fallback

- **Transcript scanning for Copilot CLI and Codex** (Issue #935)
  - Copilot CLI: scans JSONL transcript at `~/.copilot/session-state/events.jsonl`
  - Codex: discovers and scans JSONL transcripts in `~/.codex/sessions/YYYY/MM/DD/*.jsonl`
  - Added `get_default_transcript_paths()` to `HookAdapter` base class for adapter-resolved paths
  - Reuses existing JSONL incremental reader (`scan_transcript_incremental`)
  - Position tracking and dedup work identically to Claude Code transcript scanning
  - Updated AGENT_SUPPORT.md violation type coverage matrix

- **False positive handling documentation** (Issue #946)
  - Added "Handling False Positives" section to COOKBOOK.md with `.gitleaksignore` format, allowlist patterns, common scenarios, and decision guide
  - Added "False Positives" section to SECRET_SCANNING.md with quick reference table, fingerprint workflow, and recommended workflow

- **Full Windows support** (Issue #872)
  - Script-based hooks (Cline, ZooCode, Kiro) generate `.bat` files on Windows
  - `install.ps1` PowerShell installer mirroring install.sh functionality
  - Windows notification support in tray via PowerShell `ShowBalloonTip`
  - Shell launch uses `COMSPEC`/`cmd.exe` instead of `SHELL`/`/bin/sh` on Windows
  - PATH augmentation includes Windows-specific directories (Chocolatey, Scoop, LOCALAPPDATA)
  - CI test matrix includes `windows-latest` with Python 3.9 and 3.12
  - Fixed `os.fchmod` guards in `session_state.py` and `hook_context.py` (not available on Windows)
  - Changed `os.rename` to `os.replace` across 8 call sites for cross-platform atomic writes

- **OpenCode hook support via plugin adapter** (Issue #819)
  - New `OpenCodeAdapter` in `hook_adapters/opencode.py` (extends ClaudeCodeAdapter)
  - Plugin auto-discovered from `~/.config/opencode/plugins/ai-guardian.ts`
  - Setup: `ai-guardian setup --ide opencode` (installs plugin + configures MCP server)
  - Hook coverage: `tool.execute.before` (PreToolUse), `tool.execute.after` (PostToolUse), `chat.message` (UserPromptSubmit via parts mutation)
  - MCP server configured in `~/.config/opencode/opencode.jsonc` with OpenCode's `type: "local"` format
  - Same security coverage as Claude Code (secrets, PII, SSRF, prompt injection, directory blocking)
  - Updated AGENT_SUPPORT.md with OpenCode in all tables

## [1.10.0] - 2026-06-01

### Changed

- **Expanded default PII types** (Issue #905)
  - Added `medical_id`, `passport`, and `uk_nin` to default `pii_types` list
  - These types have low false-positive risk due to keyword-anchored regexes
  - Updated in setup.py, config_loaders.py, schema, example config, and all profile templates
  - Remaining opt-in types: `canada_sin`, `india_aadhaar`, `address`, `email`

### Added


- **Installer post-install improvements** (Issue #911)
  - Run `ai-guardian doctor` as a non-fatal verification step at the end of install
  - Add `ai-guardian daemon start` and `ai-guardian tray start` to "Next steps" output

- **`--use-pinned` flag for `setup --install-scanner`** (Issue #907)
  - Installs the pinned scanner version from `pyproject.toml` instead of latest
  - Usage: `ai-guardian setup --install-scanner gitleaks --use-pinned`
  - Ensures consistent scanner versions for support reproduction and tested configurations

- **Combined documentation export for single-file upload** (Issue #900)
  - Release checklist now includes generating a combined markdown file from all docs
  - Shell one-liner documented in AGENTS.md for concatenating docs with section headers
  - Suitable for upload to LLM tools that require single-file sources

- **Language-aware prompt injection scanning** (Issue #892)
  - Uses tree-sitter AST parsing to distinguish code from comments/strings
  - Only comments and string literals are scanned for injection in source files
  - Code syntax (function definitions, imports, assignments) never triggers detection
  - Eliminates false positives from patterns like `__init__`, `skip_validation`
  - Supports Python, JavaScript, TypeScript, Go, Rust, Java, Ruby, C/C++, Bash
  - Language auto-detected from file extension
  - Unknown file types fall back to full-text scanning (current behavior)
  - tree-sitter grammar packages added as core dependencies (Python >= 3.10)

- **Tray auto-starts daemon on user interaction** (Issue #889)
  - When the user clicks Console, Violations, Terminal, or other tray menu
    actions, the local daemon is automatically started if it has stopped
    (idle timeout or crash)
  - Paused daemons are NOT restarted — the user intentionally paused them
  - Respects the stop-requested marker from `daemon stop`
  - 5-second cooldown between auto-start attempts
  - Works in both single-daemon and multi-daemon tray modes

- **Compliance audit in metrics** (Issue #476)
  - `ai-guardian metrics` extended with `--html`, `--until`, `--severity` flags
  - `--html` outputs self-contained HTML audit report with inline CSS and SVG charts
  - `--until` enables bounded date ranges (e.g. `--since 2026-04-01 --until 2026-05-01`)
  - `--severity` filters by violation severity level
  - Audit report sections: trend comparison with previous period,
    resolution metrics (rate, avg time), compliance posture, security
    posture assessment (GOOD/FAIR/NEEDS ATTENTION)
  - REST API: `GET /api/audit` endpoint with query parameters
  - TUI/Web: Metrics panel extended to "Metrics & Audit" with security
    posture, trend comparison, resolution metrics, compliance summary,
    and Export HTML/JSON/CSV buttons with Open Folder / browser download
  - Tray menu: "Metrics" renamed to "Metrics & Audit"

### Fixed

- **`doctor --fix` now refreshes stale pattern cache** (Issue #916)
  - `check_ps_cache_freshness` sets `fixable=True` for stale, expired, and missing cache
  - When `--fix` is passed, attempts to fetch fresh patterns from pattern server
  - Reports success/failure with specific error messages

- **Connection string patterns false positive on placeholder passwords** (Issue #919)
  - `mongodb-connection`, `mysql-connection`, `postgres-connection`, and `redis-connection`
    no longer match placeholder passwords like `[HIDDEN]`, `[REDACTED]`, `<password>`, or
    repeated characters (`xxxxxxxx`) in documentation examples
  - New `connection_not_placeholder` validator added to the TOML patterns validation pipeline

- **env-variable pattern false positives on Python code and documentation** (Issue #912)
  - Tightened regex to require 2+ character uppercase env var names (rejects `_ = ...`)
  - Validator now skips values starting with `_` (Python identifiers like `_load_config_file`)
  - Validator now detects placeholder values (`your-...`, `example-...`, `test-...`, etc.)
  - AST-aware scanning for secret detection: tree-sitter extracts only comments and strings
    from code files, skipping code syntax that matches secret patterns

- **Windows: setup uses pythonw.exe to minimize console window flash** (Issue #902)
  - `ai-guardian setup` now uses `pythonw.exe -m ai_guardian` on Windows instead
    of console-mode `ai-guardian.EXE`, avoiding visible window on every hook call
  - Optional VBS wrapper generated during setup for fully hidden execution
  - All agent adapters (Claude Code, Cursor, Copilot, Codex, Windsurf, Gemini, Augment) use pythonw on Windows
  - `_is_ai_guardian_command()` extended to handle Windows backslash paths, `.exe` suffix, and pythonw invocations
  - macOS and Linux behavior is unchanged

- **Remove bypass hints from hook block messages** (Issue #897, #896)
  - Hook responses no longer include annotation syntax, allowlist instructions,
    config paths, or false-positive workaround tips
  - Affected detectors: secret scanning, PII, prompt injection, unicode attack,
    config file exfiltration
  - Remediation tips moved to `suggestion` field in violation log entries
    (violations.jsonl) where they are available to users but not to the AI agent
  - New UX contract test enforces no-bypass-hints policy across all detectors

- **Browser window stays minimized on KDE/GNOME** (Issue #888)
  - On Linux, after opening a URL, attempt to raise the browser window via
    `kdotool` (KDE Wayland), `xdotool` (X11), or `wmctrl` (X11)
  - Graceful degradation: silently continues if none is installed
  - Applies to: Web Console, Violations, Metrics & Audit, HTML export,
    NiceGUI web console startup, and tray-plugin parameter capture
  - macOS and Windows unaffected

- **Aadhaar PII false positive on UUID all-zeros** (Issue #876)
  - Added `aadhaar_check` post-match validator following the credit card validation pattern
  - Rejects numbers starting with 0 or 1 (real Aadhaar starts with 2-9)
  - Rejects all-same-digit patterns (e.g., 0000-0000-0000)
  - PII block messages now include actionable fix guidance for false positives

- **Image redaction too weak** (Issue #870)
  - Pixelate strategy now uses max 2x2 intermediate size (was w/8 x h/8), making text unreadable at any zoom
  - Blur strategy minimum radius increased from 10 to 20, divisor changed from /3 to /2 for stronger blur
  - Default redaction strategy changed from `blur` to `blackout` (safest — fully opaque rectangles)
  - Updated default in CLI, MCP server, and sanitizer to `blackout`

- **Metrics total stuck at 1000** (Issue #853)
  - Added running violation counter (`violation_counters.json`) independent of log rotation
  - Counter increments on every violation and persists across daemon restarts
  - `ai-guardian metrics` now shows cumulative totals alongside time-filtered data
  - `ai-guardian metrics --reset` resets counters to current log file counts (not zero)
  - REST API `/api/metrics` and MCP `get_metrics` include `cumulative_total`, `cumulative_by_type`, `cumulative_since`
  - TUI console: metrics panel shows cumulative totals + reset button with confirmation
  - Web console: metrics page shows cumulative totals + reset button with confirmation

### Added


- **NiceGUI fallback for tray plugin parameter popup** (Issue #862)
  - When tkinter is unavailable, tray plugin forms now open as a browser-based NiceGUI form (Python 3.10+)
  - Cascade order: tkinter (native popup) → NiceGUI (browser form) → Textual (terminal prompt)
  - All parameter types supported: string, int, boolean, choice, combobox, path-file, path-dir
  - NiceGUI runs a local server on a random port and auto-opens the default browser
  - Environment overrides: `AI_GUARDIAN_NO_TKINTER=1` / `AI_GUARDIAN_NO_NICEGUI=1` to skip tiers
  - install.sh updated to document the three-tier fallback

- **Directory sanitization** (Issue #857)
  - `ai-guardian sanitize /path/to/dir --output-dir /path/to/sanitized` recursively sanitizes all files
  - Text files redacted (secrets, PII, threats); image files OCR-scanned and redacted; binary files copied as-is
  - Preserves directory structure in output
  - `--include` / `--exclude` glob patterns for filtering files (repeatable)
  - `--no-images` flag to skip OCR processing (copy images as-is)
  - `--force` flag to write to an existing output directory
  - `--summary` shows per-file redaction counts and totals
  - Skips `.git`, `node_modules`, `__pycache__`, `.venv` directories automatically
  - New `sanitize_directory` MCP tool for AI agent integration
  - Tray quick actions: "Sanitize File..." and "Sanitize Directory..." in global plugin menu

- **`--redact-strategy` flag for image sanitization** (Issue #856)
  - `ai-guardian sanitize image.png --redact-strategy blackout` — choose blur, blackout, or pixelate
  - Default remains `blur` for backward compatibility
  - Supported in CLI, MCP `sanitize_directory` tool, and tray quick-action plugins
  - Tray plugins show a dropdown with the three strategies

- **Image OCR scanning in `scan_directory` and `sanitize`** (Issue #855)
  - `ai-guardian scan` and the `scan_directory` MCP tool now include image files (PNG, JPEG, etc.) via OCR
  - Extracted text is scanned through all existing detectors (secrets, PII, SSRF, prompt injection, unicode)
  - Image findings tagged with `source_type: image_ocr` in details for easy identification
  - Enabled by default when `rapidocr-onnxruntime` is installed; silently skipped otherwise
  - Respects `image_scanning` config section (enabled, max_image_size_mb, ignore_files)
  - `ai-guardian sanitize` now handles image files — OCR detects text regions, redacts those containing secrets/PII
  - Added `--output` / `-o` flag to `sanitize` for writing to a file (required for image output)

- **Default bundled tray plugins** (Issue #831)
  - Ships `default-global.json` and `default-daemon.json` with useful built-in commands
  - Global: Quick Actions submenu (Scan Directory, Check for Updates) + Open Documentation
  - Per-daemon: Maintenance submenu (Reload Config, Install Scanner, View Doctor)
  - Nested submenus for logical grouping
  - All commands work on macOS and Linux (platform maps)
  - Installed automatically on first run, `ai-guardian setup`, or daemon start
  - Users can customize or remove from `~/.config/ai-guardian/tray-plugins/`

- **`--ide` CLI parameter for deterministic adapter selection** (Issue #849)
  - `ai-guardian --ide <name>` explicitly declares which IDE adapter to use
  - Eliminates adapter mis-detection bugs like #847 (field-matching heuristics)
  - `ai-guardian setup` now writes `--ide <name>` into hook commands automatically
  - Re-running `ai-guardian setup --ide <name>` upgrades existing hooks
  - Auto-detection preserved as fallback for backward compatibility
  - Works with both direct CLI and daemon-forwarded hook processing

- **Directional immutable — tighten-only config fields** (Issue #829)
  - New `immutable: "tighten-only"` mode for config sections
  - Lower-level configs can make settings stricter but not more permissive
  - Action severity ordering: block > redact > warn > log-only > allow
  - Supports action, enabled, sensitivity fields and list fields (allowlist_patterns, ignore_files)
  - Warning logged when override blocked; org value used (not a fatal error)
  - Doctor check reports active tighten-only policies
  - Config show indicates tighten-only sections
  - Existing `immutable: true/false/[fields]` behavior unchanged

- **Violation Type Coverage Matrix** in `docs/AGENT_SUPPORT.md` (Issue #833)
  - Per-agent enforcement/advisory/partial/caution/no matrix for all 13 violation types
  - Known limitations section: image scanning caveat, transcript scanning availability, MCP-only constraints
  - Agent confidence level table with testing depth rationale
  - Community testing feedback call for low-confidence agents

- **Configuration Cookbook** (`docs/COOKBOOK.md`) (Issue #809)
  - Practical Q&A pairs for common configuration tasks
  - Covers SSRF, PII, secrets, prompt injection, permissions, directory rules, annotations, project-level config, daemon, scanners, pattern server, image scanning, profiles, and MCP server
  - Designed as NotebookLM source and quick user reference

- **One-line install script** (`install.sh`) for zero-manual-step installation (Issue #813)
  - `curl -fsSL .../install.sh | bash` — checks Python, installs package, creates config, sets up IDE hooks
  - Options: `--venv`, `--ide`, `--profile`, `--version`; extra flags passed through to `ai-guardian setup`
  - Defaults to `@standard` security profile; `--version` accepts a `.whl` file path for local installs

- **Multi-target plugin commands with interactive target selector** (Issue #760)
  - New `target` field on plugin items: `"select"`, `"all"`, or `"containers"`
  - `target: "select"` shows a Textual multi-select modal listing all discovered daemons
  - `target: "all"` runs the command on all discovered targets without prompt
  - `target: "containers"` runs on all container-runtime targets without prompt
  - Omitting `target` preserves existing single-target behavior (backward compatible)
  - Multi-target + params: parameter modal shows once, values applied to all targets
  - New `container_name` field on `DaemonTarget` for disambiguation in the selector
  - New `{container_name}` variable available in plugin command templates
  - New `tray-target-select` CLI subcommand for the target picker TUI
  - Updated JSON schema with `target` property on plugin items

### Changed

- **Removed hardcoded redaction patterns from `secret_redactor.py`** (Issue #841)
  - `PATTERNS` (44 secret patterns) and `PII_PATTERNS` (13 PII patterns) class attributes removed
  - All patterns now loaded exclusively from bundled TOML files (`secrets.toml`, `pii.toml`)
  - `SecretPatternLoader.get_default_patterns()` updated to load from TOML (matching `PIIPatternLoader`)
  - Graceful degradation: when TOML files are missing, redactor has 0 patterns with error logging

- **MCP server installed by default with `ai-guardian setup`** (Issue #808)
  - `ai-guardian setup --ide <any>` now installs hooks + MCP server (previously MCP was opt-in)
  - `--no-mcp` flag skips MCP installation
  - `--mcp` flag accepted for backward compatibility but redundant (MCP is now default)
  - MCP server is read-only and advisory — no risk, better UX

### Fixed

- **GitHub token patterns miss new stateless JWT format** (Issue #839)
  - Updated `ghp_`, `gho_`, `ghr_`, `ghs_` patterns to allow dots, hyphens, and underscores
  - New character class `[A-Za-z0-9._-]{36,}` matches both old stateful and new stateless JWT tokens
  - Updated both `secrets.toml` and legacy `secret_redactor.py` patterns
  - Added 12 tests covering old/new formats, long JWT payloads, and false positive checks

- **Immutable protection too broad — block only hooks section, not entire settings.json** (Issue #807)
  - Claude Code, Gemini CLI, and Augment Code store hooks AND user preferences in `settings.json`
  - Edit tool: content-aware check inspects `old_string`/`new_string` for hook-related keys
  - Write tool: compares `hooks` JSON key between existing file and new content
  - Non-hook settings (permissions, theme, model, MCP) can now be modified by AI agents
  - Hook modifications are still blocked (immutable protection)
  - Hooks-only files (Cursor, Copilot, Codex, etc.) remain fully blocked
  - Bash/PowerShell commands on all settings files remain fully blocked
  - Added Gemini and Augment to Bash/PowerShell immutable deny patterns
  - Fail-closed on invalid JSON or unparseable content

### Added


- **Web-based Console via daemon REST API** (Issue #679)
  - Browser-based dashboard as alternative to TUI console, powered by NiceGUI
  - Launch with `ai-guardian console --web` (auto-assigns free port, opens browser)
  - Multi-daemon overview dashboard with live status auto-refresh
  - Security Dashboard, Global Settings, Violations, Metrics, Logs, and Daemon detail pages
  - Sidebar navigation matching TUI panel groups
  - Daemon control from browser: pause/resume/reload
  - New daemon REST API endpoints: `/api/config`, `/api/violations`, `/api/metrics`
  - `MultiDaemonClient` extended with `get_config()`, `get_violations()`, `get_metrics()`
  - System tray "Web Console" menu item opens browser
  - NiceGUI added as core dependency (Python >= 3.10)
  - Configuration: `console.web.port` and `console.web.host` in schema

- **Web Console Phase 2: Permissions and Secrets pages** (Issue #804)
  - Skills page: manage Skill tool allow/deny patterns with enforcement toggle
  - MCP Servers page: MCP permission rules, proactive level, support bundle config
  - MCP Security page: read-only MCP security audit with findings display
  - Permissions Discovery page: auto-discovery directory management
  - Directory Rules page: file path access rules with JSON editor and validation
  - Secret Scanning page: toggle, allowlist patterns, pattern server config
  - Engine Configuration page: multi-engine strategy, JSON engines editor
  - Secret Redaction page: toggle, action mode, options, custom patterns, stats
  - Sidebar navigation expanded with Permissions and Secrets groups

### Fixed

- **Secret scanning no longer blocks PII types excluded from `pii_types` config** (Issue #903)
  - The `toml-patterns` scanner was unconditionally loading ALL PII patterns from `pii.toml`
  - Email addresses (and other excluded PII types) triggered "Secret Detected" blocks
    even when explicitly excluded from `scan_pii.pii_types`
  - Scanner now reads `pii_types` from the PII config and filters findings accordingly
  - Secret findings (API keys, tokens, etc.) are never affected by this filter

## [1.9.1] - 2026-05-27

### Fixed

- **Cursor adapter misdetection for Gemini beforeReadFile events** (Issue #847)
  - Default `tool_name` to `Read` for `beforeReadFile` events
  - Prevent Gemini adapter from claiming Cursor `beforeReadFile` events

## [1.9.0] - 2026-05-26

### Fixed

- **MCP server entry constant no longer contains bare command name** (Issue #800)
  - Removed bare `"command": "ai-guardian"` from `_MCP_SERVER_ENTRY` constant
  - Command is always resolved to absolute path via `_resolve_binary_path()` at setup time
  - Prevents MCP server startup failures when venv is not activated

- **`daemon status` and `daemon stop` no longer cause daemon auto-restart** (Issue #775)
  - `daemon stop` writes a stop-requested marker that suppresses auto-start
  - `start_daemon_background()` respects the marker as a final guard
  - `daemon start` clears the marker so auto-start resumes after explicit start
  - Prevents background CLI invocations from restarting a stopped daemon

### Changed

- **README install section warns against installing from main branch** (Issue #755)
  - PyPI is the stable channel; main branch contains unreleased dev code
  - CI wheel artifacts renamed from `ai-guardian-wheel` to `ai-guardian-dev-wheel`

- **Tray menu layout reorganization** (Issue #706)
  - Shell in its own separated section above daemon operations
  - Custom plugin menus in their own separated section
  - Pause/Resume and Start/Stop/Restart daemon grouped together (both are daemon operations)

### Added


- **Tag-based tray plugin filtering per daemon** (Issue #790)
  - Plugins can declare `tags` (array of strings) to target specific daemons
  - Daemons declare `menu_tags` (array of strings) in `ai-guardian.json`
  - Untagged plugins always show; tagged plugins only show on daemons with at least one matching tag
  - N-to-N relationship: plugins and daemons can each have multiple tags
  - `menu_tags` exposed via `/api/status` and `/api/stats` for remote daemon support
  - Plugin schema (`tray-plugin.schema.json`) and config schema updated
  - New `filter_plugins_by_tags()` function in `tray_plugins.py`

- **JSON schema for tray plugin files** (Issue #783)
  - New `src/ai_guardian/schemas/tray-plugin.schema.json` validates plugin structure
  - Covers all fields: name, items, label, command (string or platform map), type, run_on_target, params
  - Enables IDE autocompletion and inline validation when `$schema` is referenced in plugin files
  - Schema tests in `tests/unit/test_tray_plugin_schema.py`

- **Plugin commands: built-in target variables and run_on_target flag** (Issue #780)
  - Target variables (`{container_id}`, `{container_engine}`, `{host}`, `{port}`, `{name}`, `{pod_name}`, `{namespace}`) automatically substituted from DaemonTarget
  - `run_on_target` flag wraps commands for the target runtime (container exec, kubectl/oc exec, or local)
  - Container runtime uses `target.container_engine` (podman or docker) for exec wrapping
  - Kubernetes runtime auto-detects `oc` (OpenShift) or falls back to `kubectl`
  - Both features coexist: target vars substituted first, then run_on_target wrapping applied

- **About menu item in system tray** (Issue #766)
  - Shows version, Python, platform, config path, scanner versions, and project URL
  - Displayed via pystray notification for cross-platform support
  - Multi-daemon mode: global About lists connected daemons with versions
  - Per-daemon About in each daemon's submenu shows daemon-specific info
  - New `/api/about` REST endpoint and shared `daemon/about.py` module

- **Version mismatch detection between tray and daemons** (Issue #766)
  - Tray warns when a connected daemon runs an older version
  - OS notification sent once per daemon with upgrade recommendation
  - Daemon status label shows version indicator (⟳) on mismatch
  - Version field added to `DaemonState.get_stats()` and `/api/stats`
  - Backward compatibility contract documented in AGENTS.md

- **Release-readiness CI workflow** (Issue #761)
  - New `release-readiness.yml` workflow with 7 validation jobs
  - Fresh install test across Python 3.9–3.14
  - Upgrade path test from previous stable release (v1.8.1)
  - Multi-agent IDE setup validation (claude, cursor, copilot, gemini, codex, windsurf, cline, augment, kiro)
  - Daemon lifecycle test (start/status/reload/pause/resume/stop + REST API)
  - End-to-end detection test (secrets, PII, prompt injection, false positives)
  - Config validation (profiles, migration, doctor, show-config)
  - MCP server initialization and tool call response test
  - Release skill updated to trigger workflow before releasing

- **Build wheel artifact workflow** (Issue #515)
  - New GitHub Actions workflow builds and uploads a wheel on PRs, merges to main, and on-demand
  - PEP 440 local version identifiers for traceability (`+pr123`, `+main.abc1234`, `+username`)
  - Merges and on-demand builds create `rc-*` pre-releases with wheel as downloadable release asset
  - PR builds upload wheel as Actions artifact only (7-day retention)
  - Fork PRs blocked to prevent abuse; uses `rc-*` tags to avoid triggering PyPI publish

- **Daemon troubleshooting guide** (Issue #737)
  - New `docs/TROUBLESHOOTING.md` covering daemon startup, tray display, container, and general issues
  - Covers stale lock files, port conflicts, config reload, auto-start failures, and container race conditions

- **Built-in Shell menu item in tray** (Issue #706)
  - Opens an interactive terminal shell matching the daemon's runtime type
  - Local daemon: opens user's default shell (`$SHELL` or `/bin/sh`)
  - Container daemon: runs `podman/docker exec -it {container_id} /bin/sh`
  - Kubernetes daemon: runs `kubectl exec -it {pod} -n {namespace} -- /bin/sh`
  - Present in both single-daemon (flat) and multi-daemon (per-daemon submenu) layouts
  - No configuration required — auto-detects runtime from discovery

- **Tray menu plugin system** (Issue #590)
  - Custom menu items via JSON files in `~/.config/ai-guardian/tray-plugins/`
  - Four command types: `terminal`, `background`, `notification`, `clipboard`
  - Interactive parameters with Textual form (text inputs and dropdowns)
  - Platform-aware commands via platform map (`darwin`/`linux`/`windows`/`default`)
  - REST API endpoint `GET /api/tray-plugins` for multi-daemon plugin discovery
  - Local plugins load even when daemon is stopped
  - `_resolve_cli_cmd` now uses `sys.executable` to guarantee same virtualenv as tray
  - AppleScript command escaping fix for double quotes in terminal launches

- **Auto-install tray on first run** (Issue #728)
  - First `ai-guardian` CLI invocation auto-installs desktop shortcut, configures login autostart, and starts tray in background
  - Silent and non-blocking — log messages only, no interactive prompts
  - Skipped on headless servers (no DISPLAY), CI/CD environments, and when pystray is not available
  - Opt-out via config: `{"daemon": {"tray": {"auto_install": false}}}`
  - Works on macOS (LaunchAgent + .app bundle), Linux (.desktop files), and Windows (Start Menu shortcuts)

- **Multi-agent hook adapter architecture** (Issue #633)
  - New `hook_adapters` package with abstract `HookAdapter` base class and `NormalizedHookInput` dataclass
  - Concrete adapters for all 12 supported agents: Claude Code, Cursor, GitHub Copilot, Codex, Windsurf, Gemini CLI, Cline/ZooCode, Kiro, Augment Code, AiderDesk, OpenClaw, Junie
  - Adapter registry with auto-detection from hook input structure and `AI_GUARDIAN_IDE_TYPE` env var override
  - `response_format.py` refactored to delegate to adapters (backward-compatible wrappers preserved)
  - `process_hook_data()` uses single-pass adapter detection and normalization
  - New `docs/AGENT_SUPPORT.md` with full agent capability matrix, hook event mapping, and response format documentation
  - 104 new tests covering detection, normalization, response formatting, and backward compatibility

- **OpenClaw plugin-based integration** (Issue #640)
  - New integration using OpenClaw's TypeScript plugin system (`definePluginEntry`)
  - `ai-guardian setup --ide openclaw` installs plugin to `~/.openclaw/plugins/ai-guardian/`
  - Plugin hooks: before_tool_call (blocking), after_tool_call, message_received, session lifecycle
  - Plugin delegates to `ai-guardian` CLI via child_process, reusing Kiro exit-code response format
  - `AI_GUARDIAN_IDE_TYPE=openclaw` env var override supported
  - MCP server configuration support for OpenClaw
  - SOUL.md security guidelines injection via `--rules` flag
  - Phase 1 only (plugin-level); Phase 2 (`tool:pre` internal hook) pending upstream #12311

- **AiderDesk Extension support** (Issue #639)
  - New integration type: "extension-based" for IDEs using TypeScript/JS extension systems
  - `ai-guardian setup --ide aiderdesk` installs TypeScript extension to `~/.aider-desk/extensions/ai-guardian/`
  - Extension hooks: onToolApproval, onToolCalled, onToolFinished, onPromptStarted, onFilesAdded, onBeforeCommit
  - Extension delegates to `ai-guardian` CLI via child_process, reusing Kiro exit-code response format
  - `AI_GUARDIAN_IDE_TYPE=aiderdesk` env var override supported
  - MCP server configuration support for AiderDesk
  - Note: AiderDesk uses JS/TS extensions (not shell hooks) — requires Node.js and `npm install`

- **Junie (JetBrains) MCP-only integration** (Issue #637)
  - `ai-guardian setup --ide junie --mcp` registers MCP server at `~/.junie/mcp.json`
  - `ai-guardian setup --ide junie --rules` installs security guidelines file at `.junie/guidelines.md`
  - New `--rules` CLI flag for installing AI guidelines/rules files instructing agents to use MCP tools
  - MCP-only: Junie does not support hooks, integration is advisory via MCP tools and guidelines
  - `.junie/guidelines.md` added to config scanner patterns for prompt injection detection

- **Updated CONTRIBUTING.md with contribution paths** (Issue #727)
  - Explain how to contribute via GitHub Discussions (bug reports, feature requests, questions)
  - Explain fork + PR workflow (not affected by interaction limits)
  - Explain how to become a collaborator
  - README.md updated to link to Discussions for bug reports and feature requests

- **Kiro (AWS) hook support** (Issue #636)
  - New `IDEType.KIRO` with exit code-based blocking (exit 0 = allow, exit 1 = block)
  - Kiro sends stdout to agent context on success, stderr on error
  - Auto-detect Kiro via `kiro_hook_type` or `kiro_version` fields in hook input
  - `AI_GUARDIAN_IDE_TYPE=kiro` env var override supported
  - Hook event mapping: `prompt_submit`, `pre_tool_use`, `post_tool_use`, `agent_stop`
  - `ai-guardian setup --ide kiro` generates hook scripts in `.kiro/hooks/`
  - MCP server configuration for Kiro

- **Augment Code hook support** (Issue #638)
  - Auto-detect Augment via `is_mcp_tool` field in hook input
  - Uses Claude Code response format (JSON + exit code 2 for blocking)
  - Tool name mapping: `launch-process` → Bash, `str-replace-editor` → Edit, `save-file` → Write, `view` → Read
  - MCP tool support via `mcp:*` prefix mapping to `mcp__*` convention
  - `ai-guardian setup --ide augment` generates `~/.augment/settings.json` hook config
  - `AI_GUARDIAN_IDE_TYPE=augment` env var override supported
  - Enterprise deployment: system-level `/etc/augment/settings.json` immutable hooks

- **Cline / ZooCode hook support** (Issue #635)
  - Auto-detect Cline via `clineVersion` field in hook input
  - Response format: `{"cancel": true, "reason": "..."}` for blocking
  - Event mapping: PreToolUse, PostToolUse, UserPromptSubmit via `hookName` field
  - `ai-guardian setup --ide cline` installs executable hook scripts in `.clinerules/hooks/`
  - `ai-guardian setup --ide zoocode` supported as alias (same hook format)
  - MCP server configuration for Cline/ZooCode

### Fixed

- **MCP tray check works for remote daemons** (Issue #756)
  - Daemon now self-reports `mcp_installed` status in `/api/stats` and `/api/status` responses
  - Tray queries each daemon for its MCP installation status instead of checking only local filesystem
  - MCP Proactive menu correctly shown/hidden per daemon in multi-daemon mode
  - MCP check also looks in `~/.claude/settings.json` for users who configured MCP there
  - `ai-guardian setup --mcp` now warns if MCP entry found in `~/.claude/settings.json` (hooks file)

- **MCP Proactive menu hidden in multi-daemon tray** (Issue #706)
  - Closure-in-loop bug: visibility lambda closed over `_is_slot_running` name instead of capturing the slot index
  - All daemon submenus referenced the last loop iteration's slot (slot 7), causing `7 < len(targets)` to be False
  - Fixed by capturing slot via default argument: `lambda _i, s=idx: _is_slot_running(_i, s)`

- **Config merge silently drops permissions when user-level and project-level use different formats** (Issue #724)
  - Old list-format permissions (`"permissions": [...]`) now auto-normalized to dict format before merge
  - User-level (list) + project-level (dict) merge preserves both rule sets
  - Deprecation warning logged when old format detected
  - Fixes block-reinject loop that caused security rules to appear on every prompt

- **Daemon start -b silently fails in containers (stale PID file)** (Issue #715)
  - `_cleanup_stale()` now verifies socket connectivity when PID is alive, handling PID recycling in containers
  - `daemon status` cleans up stale PID files when daemon is not running
  - `start_daemon_background()` cleans up stale PID/socket files before spawning
  - New `cleanup_stale_pid()` utility for consistent stale file cleanup

- **Tray icon remains functional after system wake from sleep/hibernate** (Issue #703)
  - Cross-platform wake detection via wall-clock timer gap in stats refresh loop
  - macOS immediate wake handler via `NSWorkspaceDidWakeNotification`
  - Rebuilds icon and menu automatically on wake; graceful degradation if OS APIs unavailable

- **IBAN space-separated format detection** (Issue #677)
  - IBAN regex now matches both compact (`GB29NWBK60161331926819`) and space-separated (`GB29 NWBK 6016 1331 9268 19`) formats
  - IBAN validator already stripped spaces; the fix is in the regex pattern in `pii.toml`

### Added


- **Gemini CLI Hook Support** (Issue #634)
  - `ai-guardian setup --ide gemini` installs hooks to `~/.gemini/settings.json`
  - BeforeAgent, BeforeTool, and AfterTool hooks configured with `.*` matcher
  - Auto-detection via `transcript_path` field (unique to Gemini CLI)
  - Hook event mapping: `BeforeTool` → PRE_TOOL_USE, `AfterTool` → POST_TOOL_USE, `BeforeAgent` → PROMPT
  - New `IDEType.GEMINI_CLI` with structured JSON response format (`decision: "deny"`, `reason`, `systemMessage`)
  - `AI_GUARDIAN_IDE_TYPE=gemini` env var override supported
  - MCP server registration at `~/.gemini/settings.json`

- **Windsurf Hook Support** (Issue #674)
  - `ai-guardian setup --ide windsurf` installs hooks to `~/.codeium/windsurf/hooks.json`
  - All pre-hooks configured: `pre_user_prompt`, `pre_run_command`, `pre_read_code`, `pre_write_code`, `pre_mcp_tool_use`
  - All post-hooks configured: `post_run_command`, `post_read_code`, `post_write_code`, `post_mcp_tool_use`
  - Auto-detection via `agent_action_name` field (unique to Windsurf)
  - Hook event mapping: snake_case Windsurf events → ai-guardian HookEvent enum
  - MCP server registration at `~/.windsurf/mcp.json`
  - Windsurf automatically appears in tray "Local Setup..." submenu

- **Codex Hook Support** (Issue #673)
  - `ai-guardian setup --ide codex` installs hooks to `~/.codex/hooks.json`
  - PreToolUse, PostToolUse, UserPromptSubmit hooks configured with 30s timeout
  - Codex added to tray "Local Setup..." menu automatically via IDE_CONFIGS
  - MCP server registration for Codex projects (project-level `codex.json`)
  - Codex uses Claude Code response format (identical input/output schema)
  - `AI_GUARDIAN_IDE_TYPE=codex` env var override supported
  - `ai-guardian doctor` counts Codex hooks

- **PII pattern server support** (Issue #644)
  - New `PIIPatternLoader` class for loading PII patterns from a remote pattern server
  - `scan_pii.pattern_server` config option with URL, endpoint, auth, and cache settings
  - Three-tier merge: server patterns extend or replace bundled defaults by matching `id`
  - Local `additional_pii_patterns` always additive on top of server/default patterns
  - Same architecture as secret scanning, SSRF, and Unicode pattern servers
  - Fallback chain: pattern server → cache → bundled `pii.toml`

- **Parser Compatibility CI** — weekly GitHub Actions workflow verifying pattern server parser compatibility (Issue #685)
  - `parser-compat-check` job: fetches patterns, parses via `PARSER_REGISTRY`, compiles via `PatternCache`
  - `format-version-check` job: detects schema drift, creates/updates GitHub issues with `parser-compat` label
  - New script: `scripts/check_parser_compat.py` with `--compat-check` and `--format-version-check` modes
  - Fixture: `tests/fixtures/ai_guardian_native_patterns.toml` for ai-guardian native format testing

- **Internal Python scanner with TOML patterns** (Issue #678)
  - New `toml-patterns` scanner engine — runs in-process (~1-5ms), no binary required
  - 267 bundled pattern rules across 6 TOML files: secrets (44), PII (13),
    prompt injection (73), unicode attacks (107), config exfiltration (8), SSRF (22)
  - `PatternCache` class with pre-compiled matchers for regex, literal, CIDR, range, and glob
  - Multi-format pattern server support via `pattern_servers` config array
  - Parser registry with `ai-guardian` and `gitleaks` format parsers (extensible)
  - Luhn and IBAN validators extracted to `patterns/validators.py`
  - RE2 regex compatibility validation at load time
  - All existing config keys preserved (allowlists, ignore files, annotations, action levels)
  - Pattern lister (`ai-guardian patterns list`) now reads counts from TOML files
  - Configure via: `"engines": ["toml-patterns"]` (works without gitleaks/betterleaks installed)

## [1.8.1] - 2026-05-20

### Fixed

- **Credit card PII detection false positives — Luhn check alone is insufficient** (Issue #694)
  - Added IIN/BIN prefix validation after Luhn check in `_redact_credit_card()`
  - Numbers starting with 0, 1, 7, 8, 9 (no major card network) are no longer flagged
  - Valid prefixes retained: Visa (4), Mastercard (51-55, 2221-2720), Amex (34, 37), Discover (6011, 65, 644-649), JCB (35), Diners Club (30, 36, 38, 39)
  - All-zeros and coincidental numeric IDs no longer trigger false positives

- **Pause state not visually indicated — no countdown, no icon change, no CLI remaining time** (Issue #684)
  - Tray icon now dims (50% alpha) when daemon is paused, reverts to normal on resume
  - Tray "Resume" menu item shows live countdown: `Resume (3m 42s left)`
  - Pause/Resume menu items are now mutually exclusive (Pause hidden when paused, Resume hidden when running)
  - `ai-guardian daemon status` now shows remaining time: `(PAUSED — 3m 42s left)` or `(PAUSED — indefinite)`
  - Console TUI daemon panel shows remaining time when paused
  - Connected existing `_start_pause_timer()` infrastructure to pause/resume actions
  - Added `_sync_pause_state()` to detect external pause/resume (e.g., via CLI) during periodic stats refresh

- **macOS .app tray shortcut does not show menu bar icon on macOS 26.5** (Issue #691)
  - Set `NSApplicationActivationPolicyAccessory` explicitly before pystray creates the status bar item
  - Replaced bash wrapper script with Python wrapper to avoid exec chain losing bundle association
  - Added `NSPrincipalClass: NSApplication` to the .app bundle's Info.plist
  - Re-install shortcut with `ai-guardian tray --uninstall && ai-guardian tray --install` to apply

- **Desktop shortcut/autostart launches tray with minimal PATH — scanners not found** (Issue #689)
  - Added `ensure_scanner_path()` utility that augments PATH with common binary locations
  - Probes well-known directories (`/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin`) for scanner binaries
  - Reads user's login shell PATH as fallback for non-standard install locations
  - Called early in both daemon and tray startup
  - Fixed macOS `.app` wrapper script to augment PATH before exec
  - Fixed macOS launchd plist to include `EnvironmentVariables` with augmented PATH

- **Tray pause does not work for local daemon** (Issue #683)
  - Added `pause` and `resume` message handlers to daemon socket protocol in `server.py`
  - Fixed tray routing to use `multi_client` for local daemon targets instead of no-op callback
  - Replaced no-op `pause_callback` lambda in standalone tray with proper socket-based callback
  - Fixed auto-resume timer to route through `multi_client` when available

### Changed

- **Pattern research reminder frequency** (Issue #681)
  - Changed from monthly (1st of month) to twice-monthly (1st and 15th)
  - Updated workflow cron schedule, issue title, and reminder text
  - Updated AGENTS.md documentation to reflect new frequency

## [1.8.0] - 2026-05-19

### Added


- **Desktop shortcut and autostart for tray** (Issue #649)
  - `ai-guardian tray --install` creates a desktop shortcut (Applications menu)
  - `ai-guardian tray --install --autostart` additionally configures launch on login
  - `ai-guardian tray --uninstall` removes shortcut and autostart configuration
  - First-run detection: prompts to create shortcut on first `ai-guardian tray` launch
  - Linux: `.desktop` file in `~/.local/share/applications/` and `~/.config/autostart/`
  - macOS: `.app` wrapper in `~/Applications/` and launchd plist in `~/Library/LaunchAgents/`
  - Windows: Start Menu shortcut and startup folder shortcut (via PowerShell)
  - Shortcut launches tray without requiring a terminal window

- **Monochrome tray icons** (Issue #652)
  - Shield silhouette template images for clean system tray rendering at 16x16, 22x22, 32x32, and 44x44
  - macOS `*Template.png` naming convention for automatic light/dark mode adaptation
  - Platform-specific icon selection: Windows (16px), Linux (22px), macOS (Template @1x/@2x)

- **Multi-Daemon Tray Client with Podman Auto-Discovery** (Issue #527)
  - New discovery engine (`discovery.py`) finds daemons across local, Podman/Docker containers, Kubernetes pods, and manual targets
  - Cascading container discovery: label filter (`ai-guardian.daemon=true`) with port filter fallback
  - New multi-client (`multi_client.py`) routes tray actions to correct daemon via socket, REST API, `podman exec`, or `kubectl exec`
  - New REST API (`rest_api.py`) for cross-network daemon communication (stdlib `http.server`, no new deps)
  - REST API endpoints: `GET /api/status`, `GET /api/stats`, `GET /api/health`, `POST /api/pause`, `POST /api/resume`
  - Tray menu shows discovered daemons with status indicators and supports daemon selection
  - New `ai-guardian tray` CLI subcommand for standalone multi-daemon tray client
  - Configurable REST port (`daemon.rest_port`, default 63152) with container label override (`ai-guardian.rest-port`)
  - Container engine auto-detection (podman preferred) with manual override (`daemon.container_engine`)
  - Kubernetes discovery opt-in (`daemon.tray.discover_kubernetes`) with user-scoped pod filtering
  - Manual targets via `~/.config/ai-guardian/tray-targets.json` with auth token support
  - Instance name (`name` in config, defaults to hostname) displayed in Console banner, tray, REST API, and MCP
  - Daemon is now always headless — tray is a separate process (`ai-guardian tray start/stop`)
  - `ai-guardian tray stop` command to cleanly stop the standalone tray
  - Tray lock file prevents duplicate tray instances across all platforms
  - Auto-selects the first running daemon target (no manual selection needed)

- **Custom Scanner SDK — Python-based scanners** (Issue #474)
  - `Scanner` base class and `Finding` dataclass in `ai_guardian.scanners.sdk`
  - Write custom scanners as Python classes that run in-process (~1ms vs ~50ms subprocess)
  - Registration via config: module path + class name, or file path + class name
  - Registration via pip entry points (`ai_guardian.scanners` group)
  - Auto-discovery from `~/.config/ai-guardian/scanners/` directory
  - Python scanners work alongside subprocess engines in all execution strategies
  - `configure()` method for scanner-specific config from ai-guardian.json
  - Security: module path validation, Scanner subclass verification, startup logging
  - `run_engine()` dispatcher routes between subprocess and in-process scanners

- **Daemon auto-reload for project-level config** (Issue #617)
  - Daemon client sends its CWD to the daemon server on each hook request
  - Thread-local project directory override enables correct project config discovery in daemon context
  - Per-project mtime tracking detects config changes across multiple projects
  - Tray icon flashes yellow on project config changes (same as global config reload)
  - `daemon status` shows project configs tracked and last project config reload time
  - Stale project entries auto-pruned after 24 hours of inactivity

- **`init-project` command with language auto-discovery** (Issue #608)
  - New CLI command: `ai-guardian init-project` detects programming languages and generates project-level prompt injection allowlist
  - Pattern-aware: tests language identifiers against live detection patterns, only generates entries that actually trigger false positives
  - Supports 15 languages: Python, JavaScript, TypeScript, HTML, PHP, Ruby, C/C++, Go, Rust, Java, Kotlin, Swift, Scala, CSS, Shell
  - Python projects: generates allowlist for `__init__`, `__class__`, `__import__`, `__globals__`, `__builtins__`, `__mro__`, `__subclasses__`
  - HTML projects: generates `ignore_files` globs instead of allowlisting XSS-triggering patterns (safer)
  - Options: `--dry-run` (preview), `--force` (overwrite with backup), `--json` (machine-readable), `--dir` (specify project path)

- **Project-level ai-guardian.json config overlay** (Issue #594)
  - Place `.ai-guardian/ai-guardian.json` at repo root to tune scanning rules per-project
  - Deep merge: project config overlays global config (project wins for non-locked fields)
  - `immutable` in global config sections prevents project override (`true` locks entire section, array locks specific fields)
  - Global-only sections (daemon, mcp_server, support, etc.) cannot be overridden by project
  - Self-protection: agent blocked from reading project-level config (existing IMMUTABLE_DENY_PATTERNS)
  - Console: scope toggle (Global/Project) in Settings and Config Editor panels
  - Doctor: new `check_project_config` check reports active project config
  - MCP: `get_config()` reports `project_config` path when active
  - New utilities: `get_project_config_path()`, `deep_merge()`, `GLOBAL_ONLY_SECTIONS`
  - Discovery: `AI_GUARDIAN_PROJECT_CONFIG` env var → git root → CWD

- **Console MCP Security panel shows IDE config file source** (Issue #604)
  - Each MCP server now shows which IDE config file(s) it was found in
  - Multiple IDE configs shown when a server appears in more than one (e.g., Claude + Cursor)
  - IDE labels: Claude, Cursor, Windsurf, Codex
  - Added Windsurf (`~/.windsurf/mcp.json`) and Codex (`codex.json`) config discovery
  - CLI verbose mode (`ai-guardian mcp list -v`) also shows labeled sources

- **MCP server security scanning** (Issue #468)
  - `ai-guardian mcp list` — list MCP servers with trust status
  - `ai-guardian mcp audit` — config audit for credential exposure, unpinned packages, npx auto-install, suspicious URLs
  - `ai-guardian mcp scan [server]` — deep source code scan for outbound HTTP, sensitive file reads, subprocess calls, base64 exfiltration, environment variable harvesting
  - Console panel "MCP Security" under Permissions group
  - Trust derived from `permissions.rules` — no separate config needed

- **Daemon session state persistence** (Issue #592)
  - Persist security injection tracking across daemon restarts
  - Write-behind with debounced writes (2-second delay) to avoid excessive I/O
  - Atomic file writes with secure permissions (0600) for crash safety
  - Auto-prune sessions older than 24 hours on load and persist
  - State file: `~/.local/state/ai-guardian/daemon_sessions.json`
  - Flush pending state on daemon shutdown for clean exit

- **Tray Local Setup submenu for IDE hook configuration** (Issue #669)
  - New "Local Setup" submenu in tray for configuring IDE hooks without terminal
  - Section headers for Hooks, Config, and IDE entries
  - "Create Config" entry generates `ai-guardian.json` if missing

- **Setup preserves existing config with `--force` override** (Issue #668)
  - `ai-guardian setup` no longer overwrites existing `ai-guardian.json`
  - New `--force` flag to explicitly overwrite existing configuration

### Changed

- **BREAKING: Daemon no longer launches system tray automatically** (Issue #527)
  - `ai-guardian daemon start` now runs headless (no tray icon)
  - System tray is a separate process: `ai-guardian tray start`
  - **Migration**: If you relied on the tray appearing automatically with `daemon start`, add `ai-guardian tray start` to your workflow (e.g., login items, shell alias, or startup script)
  - The `--no-tray` flag on `daemon start` is deprecated (daemon is always headless)
  - This separation enables the tray to manage multiple daemons (local + containers) independently

- **Replaced subprocess-based container discovery with Docker Python SDK** (Issues #659, #654, #672)
  - Container discovery now uses `docker` Python SDK (`docker>=7.0,<9`) instead of subprocess calls
  - Multi-engine discovery: scans both Podman and Docker simultaneously instead of picking one
  - Container engine detected via API instead of socket path heuristic
  - Faster and more reliable container detection with native API access

- **Simplified tray menu layout and reordered items** (Issues #655, #656)
  - Single-daemon layout optimized for common case (no daemon submenu when only one daemon)
  - Statistics entries moved below Metrics in Console menu
  - Improved config-aware local daemon discovery

- **Refactored monolithic `__init__.py` into focused modules** (Issues #619, #620, #607)
  - Extracted CLI entry points to `cli.py` and `cli_handlers.py`
  - Extracted hook processing to `hook_processing.py`
  - Extracted config loading to `config_loaders.py`
  - Extracted shared constants to `constants.py` (ActionMode, ViolationType, HookEvent enums)
  - Extracted response formatting to `response_format.py`
  - All public symbols re-exported from `__init__.py` for backward compatibility

- **Python 3.13 and 3.14 support** (Issue #645)
  - Added Python 3.13 and 3.14 to CI test matrix
  - Added PyPI classifiers for Python 3.13 and 3.14

- **PII Detection Phase 2 - Advanced Types** (Issue #329)
  - New PII types (all opt-in, add to `pii_types` to enable):
    - `medical_id`: Medical Record Numbers with context keywords (MRN, Patient ID)
    - `passport`: International Passport Numbers with context keywords
    - `canada_sin`: Canadian Social Insurance Numbers with Luhn validation
    - `uk_nin`: UK National Insurance Numbers
    - `india_aadhaar`: Indian Aadhaar Numbers (12-digit, separated format)
    - `address`: Street Addresses (regex-based, common US suffixes)
  - Enhanced `intl_phone` pattern: now detects formatted international numbers with spaces, dashes, and dots (e.g., `+44 20 7946 0958`)
  - Context-aware detection for medical_id and passport reduces false positives
  - Canadian SIN uses Luhn algorithm validation (same as credit cards)
  - All new types available in Console TUI and JSON schema
  - 64 new tests covering detection, false positive prevention, and validation

- **Safe fix suggestions in MCP `get_violations()` tool** (Issue #627)
  - Each violation now includes a `suggestion` field with safe-only remediation guidance
  - Covers all 8 violation types: secret_detected, pii_detected, directory_blocking, tool_permission, prompt_injection, ssrf_blocked, config_file_exfil, jailbreak_detected
  - Suggestions never include bypass instructions, allowlist syntax, or config disabling hints

- **AGENTS.md bypass-prevention policy** (Issue #627)
  - Documents that AI Guardian must never provide bypass information to AI agents
  - Covers MCP tool responses, skill instructions, error messages, and Console output

- **Block Console in non-interactive AI sessions** (Issue #627)
  - `ai-guardian console` now checks `sys.stdin.isatty()` and refuses to run in non-interactive environments
  - Prevents AI agents from accessing full security configuration, patterns, and allowlists via the Console TUI

- **Simplify CONTRIBUTING.md + create Developer Guide** (Issue #628)
  - Reduced CONTRIBUTING.md from 679 lines to ~50 lines (fork workflow, commit format, checklist)
  - Created `docs/DEVELOPER_GUIDE.md` with architecture overview, development setup, testing, new feature checklist
  - Updated for v1.8.0-dev features: daemon, MCP server, Console, profiles, annotations, custom scanner SDK
  - Removed basic git tutorials and duplicate PR/issue templates from CONTRIBUTING.md

- **Document deny-by-default for MCP servers and Skills** (Issue #606)
  - README: added prominent callout after Quick Start explaining MCP/Skills are blocked by default
  - README: updated Default Behavior table to distinguish built-in tools (allowed) from MCP/Skills (blocked)
  - TOOL_POLICY.md: added "Default Security Posture" section with rationale table
  - Error message for "no permission rule" now explains deny-by-default policy instead of "matches a denied pattern"

- **Performance**: Cache config file reads across `_load_*_config()` calls (Issue #569)
  - Single file read per hook invocation instead of 4-6 redundant reads
  - Uses mtime-based invalidation for automatic cache refresh
  - Refactored `_load_pattern_server_config()` to use shared `_load_config_file()` cache

### Fixed

- **Restore full Security Disclaimer + fix broken PyPI README links** (Issue #624)
  - Restored full Security Disclaimer section with bullet points about limitations and defense-in-depth recommendations
  - Converted all relative links in README.md to absolute GitHub URLs so they work on PyPI

- **Rename desktop entries from "AI Guardian" to "AI Guardian Tray"** (Issue #663)
  - Fixed desktop shortcut and autostart entries to use correct "AI Guardian Tray" name

- **Bug: GNOME system tray icon not visible after AppIndicator extension install** (Issue #602)
  - pystray `setup=` callback prevents icon from appearing on newer GNOME/GTK
  - Replace with timer-based stderr restore so icon displays correctly

- **Bug: Console startup prints MCP permission check messages to terminal** (Issue #600)
  - Suppress stderr logging (INFO/DEBUG) when running `ai-guardian console` or `ai-guardian tui`
  - File logging remains at full verbosity for debugging
  - MCP permission check results still available in Console MCP panel

- **Bug: paused daemon returns `null` causing Claude Code errors** (Issue #618)
  - Return valid JSON string instead of `None` when daemon is paused
  - Prevents "Failed with non-blocking status" errors in Claude Code

- **Bug: tray Console launch fails on macOS before shell init** (Issue #599)
  - Defer tray Console command until after shell initialization on macOS

- **Bug: unlisted MCP servers always blocked** (Issue #595, AAP-75435)
  - Switch permission rules to last-match-wins evaluation (consistent with directory_rules)
  - Rules evaluated in order: broad allow → category deny → specific allow
  - `mode: deny` supports `action: block|warn|log-only` (default: block)
  - New unlisted MCP servers warned instead of blocked with standard profile
  - Backward compatible: old `action` on `mode: allow` rules still works (deprecated)
  - Updated @minimal, @standard, @strict profile defaults
  - Updated default config templates with layered permission rules

## [1.7.0] - 2026-05-13

### Added


- **Daemon service architecture** (Issue #367, Phases 1-3)
  - Long-running daemon process for faster hook processing (~1-5ms vs ~50-100ms per-invocation)
  - Three modes: `"auto"` (default, daemon with local fallback), `"local"` (per-process, for CI/CD), `"daemon"` (require daemon, for testing/compliance)
  - Unix domain socket IPC on macOS/Linux, TCP localhost fallback on Windows
  - In-memory cross-hook state sharing between PreToolUse and PostToolUse via `tool_use_id`
  - Config auto-reload: mtime check per-request + periodic SHA256 checksum verification
  - Compiled regex pattern caching in memory (invalidated on config change)
  - Lazy daemon start: first hook call in `auto` mode starts daemon in background
  - Idle timeout auto-stop (default 30 minutes, configurable)
  - CLI commands: `ai-guardian daemon start|stop|status|restart`
  - System tray icon with status indicator and Pause/Resume menu (pystray + Pillow included as dependencies)
  - Graceful shutdown on SIGTERM/SIGINT with socket/PID file cleanup
  - New config section: `daemon` with `mode`, `idle_timeout_minutes`, `client_timeout_seconds`, `tray.enabled`
  - Environment variable override: `AI_GUARDIAN_DAEMON_MODE=local` for CI/CD
  - Extracted `process_hook_data()` for direct dict-based hook processing (daemon and direct mode)

- **MCP security advisor server** (Issue #477)
  - MCP server with 12 read-only security tools for AI agents via stdio transport
  - Security check tools: `check_path`, `check_command`, `check_mcp_trust`, `sanitize_text`, `check_annotations`
  - Information tools: `get_violations`, `get_config`, `get_scanner_status`, `get_scanner_supported`, `get_patterns_list`, `get_metrics`, `doctor`
  - 3 MCP resources: `security-posture`, `protected-paths`, `recent-violations`
  - Security-limited responses: yes/no answers only, no rule/pattern/allowlist exposure
  - Runtime enable/disable via config flag (no IDE restart needed)
  - CLI: `ai-guardian mcp-server` (start), `ai-guardian mcp enable/disable/status` (toggle)
  - Setup: `ai-guardian setup --mcp` / `--no-mcp` (opt-in, installs MCP config + skill)
  - Tray menu MCP toggle
  - Console MCP enable/disable button
  - AI security awareness skill (`ai-guardian-security`) teaches AI when to use each tool
  - Support bundle export: `prepare_support_bundle` + `send_support_bundle` (sanitized diagnostics with user approval)
  - New dependency: `mcp>=1.8.0` (Python >=3.10 only, MIT license)

- **Security instruction injection via systemMessage** (Issue #580)
  - Injects never-bypass security rules into AI context on every UserPromptSubmit hook
  - Uses generic language — does not name specific bypass mechanisms or config files
  - Configurable via `security_instructions.inject_on_prompt` (default: enabled)
  - Supports time-based disabling for temporary development work
  - Updated SKILL.md and MCP server to remove specific bypass mechanism names

- **Self-Protection: Block Agent Read Access** (Issue #512)
  - Read tool blocked for all ai-guardian config, state, and cache files
  - Bash cat/grep/head/tail/less/more blocked for same files
  - PowerShell Get-Content/Select-String blocked for same files
  - Immutable — cannot be overridden by user config
  - MCP server remains the approved way for agent to query security data
  - Doctor check (`check_self_protection`) verifies read protection is active

- **Multi-engine execution strategies** (Issue #250, Phase 3)
  - Execution strategy support: `first-match` (default), `any-match` (block if ANY engine finds secrets), `consensus` (block only if N engines agree)
  - Parallel engine execution via ThreadPoolExecutor for `any-match` and `consensus` strategies
  - Smart deduplication across engines (prefers verified secrets, highest confidence)
  - Per-engine configuration: `ignore_files`, `pattern_server`, `file_patterns`
  - File type routing: route different file types to specialized engines (e.g., `.env` → TruffleHog, `.py` → Gitleaks)
  - Structured scan metrics logging (engine, duration, findings count)
  - New `run_single_engine()` executor for reusable single-engine subprocess execution
  - New `select_all_engines()` for multi-engine strategies
  - Console "Engine Configuration" panel with JSON editor for engines and strategy dropdown
  - 30 new tests (92% coverage for scanners module)

- **Result caching and incremental scanning** (Issue #250, Phase 3)
  - `ScanResultCache`: File-based cache for scan results keyed by content hash + engine type + config hash
  - Configurable TTL (`cache_ttl_hours`, default 24h) with automatic expiry
  - `FileStateTracker`: Track file states for incremental scanning — skip unchanged files
  - Cache integrates transparently with `run_single_engine()` and all execution strategies
  - Config: `"cache_results": true, "cache_ttl_hours": 24, "incremental": true`

- **Secretlint integration** (Issue #250, Phase 3)
  - New `secretlint` engine preset (MIT license, Node.js-based, plugin architecture)
  - `SecretlintOutputParser` for JSON output (array and newline-delimited formats)
  - Rule ID normalization (extracts short name from `@secretlint/secretlint-rule-*` chains)
  - Install: `npm install -g @secretlint/secretlint-rule-preset-recommend`

- **GitGuardian integration** (Issue #250, Phase 3)
  - New `gitguardian` engine preset (ggshield CLI, 350+ secret types)
  - `GitGuardianOutputParser` with verified secret support (`validity: "valid_data"`)
  - Consent mechanism for cloud engines: `ai-guardian engine consent gitguardian`
  - API key validation via `GITGUARDIAN_API_KEY` environment variable
  - Cloud service warning in Console and documentation
  - License: Proprietary (free tier for individuals)

- **Enterprise features** (Issue #250, Phase 3)
  - Remote engine configuration: fetch engine config from remote URL with caching
  - Merge strategies: remote engines prepended to local (or replace with `immutable: true`)
  - Audit logging: JSONL at `~/.local/state/ai-guardian/scan-audit.jsonl`
  - Compliance reporting: generate reports for HIPAA, PCI-DSS, SOC2 frameworks
  - Export audit data for external audits

- **Per-engine pattern_server config in scanning flow** (Issue #519)
  - Engines can now override the global pattern server via per-engine `pattern_server` config
  - `pattern_server: null` disables patterns for that engine (uses built-in rules)
  - `pattern_server: { url: "..." }` fetches engine-specific patterns from a dedicated server
  - No override (key absent) uses the global pattern server (backward compatible)
  - Added `resolve_engine_config_path()` helper centralizing config_path resolution logic
  - Execution strategies (first-match, any-match, consensus) now resolve config_path per-engine
  - Replaces inline engine-type filtering in `__init__.py` with centralized resolver

- **Directory Scanning MCP Tools** (Issue #544)
  - `scan_directory` tool returns violation summary (counts and types only — no file paths or secret values)
  - `scan_directory_report` tool generates detailed report in temp directory for user review
  - Two-step flow: AI sees summary only, user reviews detailed report directly
  - Path validation blocks system directories
  - Supports JSON and SARIF output formats

- **Engine Tester** (Issue #542)
  - CLI command `ai-guardian engine-test` to test strings against individual scanner engines
  - Flags: `--engine NAME`, `--all`, `--compare`, `--pattern-server`, `--json`
  - Console panel under Tools for interactive engine testing with comparison view
  - Side-by-side engine comparison shows which engines detect a secret and which miss it

- **Security profile templates** (Issue #466)
  - Built-in profiles: `@minimal` (personal, low friction), `@standard` (team, moderate), `@strict` (enterprise SOC2/compliance)
  - CLI: `ai-guardian setup --create-config --profile @strict`
  - Custom profiles: save with `--save-profile my-team`, stored in `~/.config/ai-guardian/profiles/`
  - List all profiles: `ai-guardian setup --list-profiles`
  - File path profiles: `--profile /path/to/profile.json`
  - `@standard` matches existing `--create-config` output (backward compatible)
  - `@strict`: fail-closed (`on_scan_error: block`), high sensitivity, audit logging, annotations disabled
  - `@minimal`: warn-only actions, low sensitivity, permissions disabled, reduced PII types

- **Inline and block annotation suppression** (Issue #481)
  - `ai-guardian:allow` on a line suppresses secrets and PII for that line
  - `ai-guardian:begin-allow` / `ai-guardian:end-allow` suppresses a block of lines
  - `gitleaks:allow` suppresses secrets only (default alias)
  - Configurable aliases: `inline_allow`, `inline_allow_secrets`, `block_begin`, `block_end`
  - User config extends defaults — add custom aliases without losing built-in ones
  - Pre-processing approach: suppressed lines blanked before any scanner runs
  - Suppresses secrets and PII detection (both blocking and redaction)
  - Prompt injection, jailbreak, and config exfil are always scanned (cannot be suppressed)
  - File content only (PreToolUse/beforeReadFile) — never applies to PostToolUse, prompts, or transcripts
  - Fail-safe: unmatched `begin-allow` without `end-allow` is ignored with a warning
  - Language-agnostic: searches for marker string anywhere on a line
  - Audit trail: suppressions logged via ViolationLogger (`annotation_suppressed` type)
  - Configurable: `annotations.enabled` (default: true) to disable for strict compliance
  - Detection messages include annotation hint showing available suppression markers
  - TUI: new Annotations panel under Threat Detection for managing aliases

- **Global `on_scan_error` configuration** (Issue #461)
  - New top-level `on_scan_error` config parameter: `"allow"` (default) or `"block"`
  - Controls fail-open/fail-closed behavior when scanners encounter errors
  - `"allow"`: Current behavior — log warning, allow operation (developer productivity)
  - `"block"`: Block operation if any scanner fails (strict compliance environments)
  - Applies to: tool policy, prompt injection, config scanning, secret scanning, transcript scanning
  - TUI shows new setting in Global Settings panel
  - Default is `"allow"` for backward compatibility

- **Cross-hook context passing** (Issue #366)
  - `HookContextManager` module (`hook_context.py`) for PreToolUse to PostToolUse correlation via `tool_use_id`
  - PostToolUse inherits `file_path` from PreToolUse context for violation entries
  - Skip double-scanning: PostToolUse skips secret scan when PreToolUse already scanned clean
  - `ignore_files` consistency: PostToolUse respects ignore decisions from PreToolUse
  - PII skip consistency: PostToolUse skips PII scan when PreToolUse skipped via `ignore_files`
  - Daemon mode: uses `DaemonState` in-memory store (zero I/O overhead)
  - Local mode: session-scoped temp file with secure `0600` permissions
  - TUI: correlation ID and hook event shown on violation cards
  - TUI: "Correlated" button shows the paired PreToolUse/PostToolUse violation
  - Fail-safe: if context unavailable, PostToolUse processes normally (no regression)

- **Support bundle CLI command** (Issue #511)
  - `ai-guardian support prepare` — create sanitized bundle in temp dir for review
  - `ai-guardian support send` — send prepared bundle to configured destination
  - `ai-guardian support status` — show export destination, auth, and pending bundles
  - Options: `--output PATH`, `--no-log`, `--no-violations`, `--json`, `--prepare`, `--yes`, `--bundle PATH`
  - One-shot mode: `ai-guardian support send --prepare --yes` for CI/automation
  - Shares underlying logic with MCP tools (`prepare_support_bundle`, `send_support_bundle`)
  - Cross-process support: bundle ref persisted to state dir so `prepare` and `send` work in separate terminals

- **GCS bucket support for support bundle export** (Issue #513)
  - `gs://bucket-name/prefix/` destination format supported in config
  - Auto-detects Google Application Default Credentials (Vertex AI or `gcloud auth application-default login`)
  - Falls back to `gcloud auth print-access-token` CLI
  - No additional dependencies required (uses GCS REST API directly)

- **Project-level .aiguardignore.toml** (Issue #497)
  - Per-project `ignore_files` via `.aiguardignore.toml` in project root
  - Global `[allowlist]` paths apply to all scanners
  - Per-scanner sections: `[secret_scanning]`, `[scan_pii]`, `[prompt_injection]`, `[config_file_scanning]`
  - Consistent with `.gitleaks.toml` allowlist structure
  - Merged with JSON config `ignore_files` (both sources apply)
  - Cached with mtime-based invalidation for performance

- **Project .gitleaks.toml allowlist support** (Issue #488)
  - ai-guardian reads `.gitleaks.toml` from the project root and applies its allowlist rules
  - Works with all scanner engines (gitleaks, betterleaks, leaktk, etc.)
  - Supports global allowlists: `paths`, `regexes`, `stopwords`
  - Supports per-rule allowlists via `[[rules]]` sections
  - Path-based early skip (before scanning) and finding-level post-scan filtering
  - Cached with mtime-based invalidation for performance
  - Does not conflict with ai-guardian's own `allowlist_patterns` config

- **Health Check (Doctor) panel in Console** (Issue #502)
  - New panel under Tools section displaying all `ai-guardian doctor` checks
  - Color-coded pass/warn/fail/skip indicators with expandable details
  - Auto-refresh on navigation, manual refresh button
  - Fix Issues button with confirmation dialog for auto-fixable problems
  - Reuses existing Doctor class — same checks as the CLI

- **Pattern server doctor checks** (Issue #493)
  - `ai-guardian doctor` now checks pattern server cache path writability
  - Checks auth token availability (env var or token file)
  - Checks pattern server URL reachability (with `--check-connectivity`)
  - Checks cache freshness against configured refresh/expiry thresholds
  - Each failure includes actionable fix instructions

- **Tray menu status submenu with stats** (Issue #508)
  - Main menu header shows "● AI Guardian — Running/Paused" with status submenu
  - Submenu displays: Requests, Blocked (with percentage), Warned, Logged counts
  - Violations grouped by severity: Critical (blocked) and Warning (warned)
  - Last block type and time-ago display (e.g., "secret_detected 2m ago")
  - All stats from daemon in-memory counters (fast, no file I/O)
  - Numbers formatted with commas for readability
  - No subjective labels — numbers only

- **Terminal emulator support for tray Console on Linux** (Issue #553)
  - Added `kgx` (GNOME Console, Fedora 44+ default) to the terminal fallback chain
  - `ai-guardian doctor` checks for a supported terminal emulator on Linux
  - Documentation: terminal emulator requirement listed in docs/CONSOLE.md

- **GNOME AppIndicator Detection** (Issue #552)
  - `ai-guardian doctor` detects GNOME without AppIndicator extension and shows fix command
  - Daemon logs warning when tray icon cannot start on GNOME (no longer silent)
  - Documentation: GNOME setup steps in docs/CONSOLE.md and README requirements

- **Action field dropdowns in Console Global Settings** (Issue #447)
  - Global Settings panel now shows action dropdowns (block/warn/log-only) for Prompt Injection, PII Detection, SSRF Protection, and Config File Scanning
  - Action changes auto-save to config and stay in sync between global settings and individual panels

- **Documentation: pre-commit hook** (Issue #467)
  - Added pre-commit hook entry to README features table
  - Created `docs/PRE_COMMIT.md` covering `ai-guardian setup --pre-commit`, direct git hook, and pre-commit framework installation methods
  - Updated `docs/README.md` index with new documentation link

- **Documentation: per-engine pattern server auth** (Issue #458)
  - Document that `AI_GUARDIAN_PATTERN_TOKEN` is the default env var for all pattern server sections
  - Document how to override `token_env` per section for multi-server setups
  - Document `token_file` as alternative to env var
  - Example config showing different tokens per pattern server
  - Updated `docs/PATTERN_SERVER.md`, `ai-guardian-example.json`, and `README.md`

### Changed

- **Security rules injected only on first prompt + after blocks** (Issue #584)
  - Previously injected `_SECURITY_SYSTEM_MESSAGE` via `systemMessage` on every `UserPromptSubmit`
  - Now injects only on the first prompt per session and re-injects after any block event
  - Adds `SessionStateManager` with dual-mode support: in-memory (daemon) and file-based (local)
  - Session state included in support bundle for diagnostics
  - Reduces token overhead in long conversations

- **Deprecate `secret_scanning.pattern_server` — migrate to per-engine** (Issue #530)
  - Global `secret_scanning.pattern_server` is deprecated (gitleaks-specific but implied all engines)
  - Per-engine format is now canonical: `engines[{"type": "gitleaks", "pattern_server": {...}}]`
  - Deprecation warning logged when global format detected
  - `ai-guardian doctor` warns about deprecated format (`check_global_pattern_server`)
  - `ai-guardian doctor --fix` auto-migrates to per-engine format
  - `ai-guardian setup --migrate-pattern-server` handles full migration chain (root → global → per-engine)
  - Enhanced per-engine `pattern_server` schema to match full global schema (auth, cache, immutable, etc.)
  - Example config updated to show per-engine pattern_server as the documented format
  - Legacy format still works (backward compatible); removal planned for v2.0.0

- **Quick Start updated with one-liner setup and profiles** (Issue #566)
  - Single command now includes `--create-config`, `--mcp`, and `--install-scanner`
  - Added security profile comparison table (@minimal, @standard, @strict)

- **Simplified README to ~230 lines** (Issue #454)
  - Moved detailed documentation to `docs/` folder with links
  - Created `docs/SECURITY_DESIGN.md` for self-protection architecture details
  - Created `docs/README.md` as documentation index
  - Added documentation guidelines to AGENTS.md (README ~300 line limit)
  - No information lost — all content accessible via docs/ links

- **Support bundle keeps original file names** (Issue #543)
  - `ai-guardian.json` no longer renamed to `config.json` in the bundle
  - `violations.jsonl` no longer renamed to `violations.json` in the bundle

### Removed

- **`mcp_server.enabled` config flag** (Issue #516)
  - MCP server presence is controlled by IDE config (`.claude/settings.json`), not ai-guardian config
  - Removed `enabled` property from schema, example config, setup defaults, and template profiles
  - Removed `_is_mcp_enabled`, `_disabled_check` decorator, and `DISABLED_RESPONSE` from MCP server
  - Removed `ai-guardian mcp enable/disable/status` CLI subcommands
  - Removed MCP enable/disable toggle from Console TUI and tray menu
  - `ai-guardian setup --mcp` / `--no-mcp` remains the install/uninstall mechanism

## [1.6.2] - 2026-05-11

### Fixed

- **Betterleaks JSON parse failure no longer treated as secret detected** (Issue #532)
  - When betterleaks returns malformed JSON output, the scanner now correctly reports "no secrets found" instead of treating the parse error as a secret detection
  - Prevents false-positive security blocks caused by scanner output parsing failures

## [1.6.1] - 2026-05-06

### Fixed

- **Console crashes on MCP Servers panel and Permissions Discovery panel** (Issue #446)
  - Fixed DuplicateIds crash when navigating to MCP Servers panel by removing fixed widget ID from empty-state Static and using CSS class selector instead
  - Fixed WrongType crash when navigating to Permissions Discovery panel by changing panel wrapper from VerticalScroll to Container, consistent with all other panels

- **Clipboard "Copied" notification shown incorrectly in Linux containers** (Issue #452)
  - Console no longer shows "Copied to clipboard" when the copy actually failed
  - `copy_to_clipboard()` now returns a boolean indicating success
  - `on_text_selected` checks the return value before showing the notification
  - Wrapped in try/except to handle IndexError/AttributeError from empty selections

- **Transcript scanner re-flags same content on every prompt** (Issue #462)
  - First scan of a new transcript now initializes position to current file size instead of scanning from byte 0
  - Initial transcript content (system context, tool responses) was already scanned by PreToolUse/PostToolUse hooks — rescanning caused duplicate PII/secret warnings that overshadowed real security events (e.g., jailbreak detection)
  - Truncated/compacted transcripts now skip to current end instead of rescanning from 0
  - Transcript scanning now only catches content from `!` shell commands (its intended purpose)

### Documentation

- **Simplified README to ~230 lines** (Issue #454)
  - Moved detailed documentation to `docs/` folder with links
  - Created `docs/SECURITY_DESIGN.md` for self-protection architecture details
  - Created `docs/README.md` as documentation index
  - No information lost — all content accessible via docs/ links

## [1.6.0] - 2026-05-04

### Changed

- **Renamed all TUI references to Console** (Issue #440)
  - `ai-guardian console` is now the primary documented command
  - `ai-guardian tui` remains as backward-compatible alias
  - Updated all user-facing text, help strings, error messages, and documentation
  - Renamed `docs/TUI.md` to `docs/CONSOLE.md`
  - Renamed GitHub `tui` label to `console`
  - Internal `src/ai_guardian/tui/` directory unchanged (no import breakage)

### Added


- **Sanitize Command** (Issue #443)
  - New `ai-guardian sanitize` command for redacting secrets, PII, and threats from text
  - Neutralizes: secrets, PII, prompt injection patterns, unicode attacks (zero-width chars, bidi overrides, tag chars, homoglyphs)
  - Reads from stdin or file, outputs only redacted text to stdout (pipe-safe)
  - Ignores user config — hardcoded maximum detection, no allowlists, no ignore patterns
  - Flags: `--no-secrets`, `--no-pii`, `--no-threats`, `--summary`, `--exit-code`
  - Designed for cleaning transcripts before sharing with other AI agents

- **OSC 52 terminal escape sequence as clipboard fallback** (Issue #433)
  - Added `wl-copy` support for Wayland environments
  - Added OSC 52 escape sequence as final fallback for containers/SSH/headless
  - Works in UBI 10 containers and SSH sessions without xclip/xsel
  - Fallback chain: xclip → xsel → wl-copy → OSC 52
  - Existing pbcopy (macOS) and clip (Windows) behavior unchanged
  - Extracted `_try_clipboard_command()` helper to reduce duplication

### Documentation

- **Warning about `!` shell command bypass** (Issue #431)
  - Added security note to README.md Known Limitations section
  - Added to AGENTS.md Common Issues section
  - Added top-level comment in ai-guardian-example.json
  - Added recommendation in Console Security Dashboard and help panel
  - `!` commands bypass all ai-guardian hooks; use regular commands instead
  - Transcript scanning (Issue #430) provides after-the-fact detection

### Security

- **Gitleaks exit code 1 treated as "no secrets found" — secrets bypass detection** (Issue #411)
  - Gitleaks exit code 1 (default for "secrets found") was incorrectly added to the success codes list, causing detected secrets to be silently allowed through
  - Now correctly treats exit code 1 as "secrets found" when `--exit-code 42` is specified
  - Added debug logging for scanner command and exit code to aid troubleshooting
  - Bug introduced in v1.4.0 (PR #154)

- **PostToolUse allowed secrets through when secret_redaction was disabled** (Issue #414)
  - When `secret_redaction.enabled = false`, detected secrets were allowed through as an "emergency bypass" instead of being blocked
  - PostToolUse now correctly blocks tool output containing secrets regardless of redaction settings

### Added


- **Transcript Scanning for Secrets, PII, and Prompt Injection** (Issue #430)
  - Incrementally scans conversation transcript on each `UserPromptSubmit` event
  - Detects threats that entered via `! command` shell mode (which bypasses hooks)
  - Scans for secrets (via gitleaks/engines), PII, and prompt injection patterns
  - Detection only: warns via `systemMessage` (cannot block — content already in AI context)
  - IDE-agnostic: supports Claude Code, Cursor, and GitHub Copilot transcript paths
  - New violation types: `secret_in_transcript`, `pii_in_transcript`, `prompt_injection_in_transcript`
  - Position tracking in `~/.local/state/ai-guardian/transcript_positions.json` prevents re-scanning
  - Configurable via `transcript_scanning.enabled` (default: `true`)
  - Performance: reads only new bytes since last scan via byte-offset tracking

- **Multi-Engine Scanner Support — TruffleHog and detect-secrets** (Issue #249)
  - **TruffleHog**: 700+ detectors with entropy analysis and verified secrets detection (`"engines": ["trufflehog"]`)
  - **detect-secrets**: Baseline workflow for CI/CD pipelines with plugin-based detection (`"engines": ["detect-secrets"]`)
  - **Execution Strategies**: `first-match` (default), `any-match` (maximum security), `consensus` (reduce false positives with threshold)
  - Smart deduplication when multiple engines find the same secret
  - License: TruffleHog is AGPL-3.0 (used via subprocess, no AGPL obligations); detect-secrets is Apache-2.0
  - Interactive license notice during `ai-guardian scanner install trufflehog`

- **PII Detection in Tool Outputs** (Issue #262)
  - GDPR/CCPA compliance: detect and redact PII across all three hooks (UserPromptSubmit, PreToolUse, PostToolUse)
  - 7 PII types: SSN, Credit Card (Luhn), US Phone, Email, US Passport, IBAN (mod-97), International Phone (E.164)
  - Top-level `scan_pii` config section with `enabled`, `pii_types`, `action`, `ignore_files`, and `allowlist_patterns`
  - Enabled by default; `action: "redact"` masks PII in PostToolUse, blocks in PreToolUse/UserPromptSubmit

- **Jailbreak Detection Patterns** (Issue #263)
  - 13 built-in patterns across 4 categories: role-play jailbreaks (DAN/sudo/god mode), identity manipulation, constraint removal, hypothetical framing
  - New `jailbreak_patterns` config key for user-defined patterns
  - Error messages distinguish "Jailbreak Attempt Detected" from "Prompt Injection Detected"
  - New `jailbreak_detected` violation logging type
  - Patterns only checked for user prompts (not file content) to minimize false positives

- **Enhanced Prompt Injection Detection — 24 new patterns** (Issue #285)
  - 15 CRITICAL patterns: fake completion, HTML comment injection, chain-of-thought exploitation, instruction replacement, auto-approval manipulation, and more
  - 8 DOCUMENTATION patterns: output format manipulation, workflow chaining, Base64 encoding, delimiter injection
  - Sources: PayloadsAllTheThings, Hermes Security Patterns, Open-Prompt-Injection (USENIX 2024), arXiv 2601.17548
  - All patterns maintain <1ms detection target

- **Allowlist patterns for scan_pii and secret_scanning** (Issue #357)
  - `allowlist_patterns` config option suppresses false positives for known-safe values (e.g., corporate email domains, test API key prefixes)
  - Supports simple string patterns and time-based patterns with expiration (`valid_until`)
  - ReDoS protection and dangerous catch-all pattern blocking
  - Console updated with allowlist pattern editing for both PII and secret scanning

- **Auto-Generate Directory Rules from Skill Permissions** (Issue #144)
  - Auto-generate directory access rules from skill permissions, eliminating duplicate configuration
  - Multi-IDE support: Claude Code, Cursor, VSCode/Copilot, Windsurf
  - Opt-in via `auto_directory_rules.enabled: true`
  - Rule order (last-match-wins): User rules → Generated rules → Immutable rules
  - Generated rules override broad user deny rules for specific permitted skill paths
  - `allow_symlinks` option (default: `true`) for container environments (Issue #324)
  - Plugin cache directory scanning for Claude Code plugins
  - New `ai-guardian config show` command with `--all`, `--section`, `--preview-auto-rules` flags
  - All rules visible with `[USER]`, `[GENERATED]`, `[IMMUTABLE]` labels

- **Hook Simulator panel in Console** (Issue #397)
  - Simulate UserPromptSubmit, PreToolUse, and PostToolUse hook events
  - Test detection rules without triggering real hooks
  - View BLOCKED/ALLOWED/WARNING decisions with detection details
  - IDE format selector (Claude Code, Cursor, GitHub Copilot)

- **JSON Config Editor in Console** (Issue #388, #391)
  - Raw JSON editor for `ai-guardian.json` with syntax highlighting and line numbers
  - Real-time JSON validation with schema validation warnings on save
  - Console Settings panel with theme selector (Monokai, VS Code Dark, Dracula, GitHub Light)
  - New `console` section in schema, setup defaults, and example config
  - New dependencies: `tree-sitter>=0.25.0` and `tree-sitter-json>=0.24.0` (MIT license)

- **Show default values in Console config panels from schema** (Issue #371)
  - Each config field shows its default value from the schema
  - Fields changed from default are highlighted with a yellow left-border
  - Applied to all 11 config panels

- **Copy-to-clipboard support in Console** (Issue #362)
  - Auto-copy on text selection (like Claude Code)
  - Copy button on Violation Details modal
  - Platform-native clipboard fallback for macOS Terminal.app, Linux, Windows (Issue #377)

- **Enriched violation log entries** (Issue #408)
  - `context_snippet`: redacted context around detection (for PII and secret violations)
  - `command`: Bash command that produced flagged output
  - `tool_use_id` and `session_id`: correlation IDs for matching PreToolUse/PostToolUse events

- **`ssrf_blocked` and `config_file_exfil` violation logging types** (Issue #322)
  - SSRF and config exfiltration violations now have dedicated log types instead of being misclassified as `tool_permission`
  - Console tabs and checkboxes for both new types
  - Backward compatible with existing configs

- **Scanner/Pattern-Server Discovery Commands** (Issue #320)
  - `ai-guardian scanner supported` — lists all supported scanners with versions, repos, and licenses
  - `ai-guardian pattern-servers supported` — lists all configured pattern servers
  - `--json` flag for `scanner list`, `scanner info`, `scanner supported`, and `pattern-servers supported`

- **`--json` flag for `setup --create-config`** (Issue #326)
  - Outputs raw JSON only, pipeable to `jq`
  - `$schema` field now uses `file://` URI pointing to bundled schema (works offline)

- **`ai-guardian tui` alias for `ai-guardian console`** (Issue #389)

- **`--yes`/`-y` flag for `violations --clear`** (Issue #360)
  - Skips confirmation prompt for non-interactive use (CI, Claude Code `!` prefix, piped scripts)

- **Dependabot and scanner version monitoring** (Issues #288, #289, #290, #291, #292, #293, #309)
  - Dependabot configuration for automated GitHub Actions and Python package updates (monthly, grouped PRs)
  - Daily scanner version health monitoring via CI (`scripts/check_scanner_versions.py`)
  - Scanner version existence pre-flight checks in CI (fail fast if versions missing)
  - Automated monthly prompt injection pattern research reminders
  - Comprehensive dependency management documentation in AGENTS.md

### Changed

- **Console: Replaced 'Directory Protection' panel with 'Directory Rules' panel** (Issue #426)
  - New panel manages `directory_rules` configuration (allow/deny path access control)
  - Moved from Configuration section to Permissions section in navigation

- **Console violations panel no longer auto-modifies config** (Issue #421)
  - Removed approve/deny action buttons; details modal now shows resolution instructions with copyable config snippets
  - Users must manually edit config via Console panels, JSON editor, or text editor

- **Enhanced error messages across all protection layers** (Issue #287)
  - Consistent `🛡️ [Protection Type]` format (replaced `🚨 BLOCKED BY POLICY`)
  - Shows exact regex pattern, confidence level, and sanitized matched text for prompt injection
  - Shows secret type and location for secret scanning (value NEVER shown)
  - Context-specific recommendations and config paths for all violation types

- **Remove email from default `scan_pii.pii_types` list** (Issue #370)
  - Email PII detection now opt-in (add `"email"` to `pii_types` to re-enable)
  - Existing configs with explicit `"email"` continue to work

- **Remove dev source code patterns from immutable deny rules** (Issue #369)
  - Dev source protection was redundant with git/PR workflow
  - Pip-installed package protection kept; config/cache/hooks/markers unchanged

- **XDG Base Directory compliance** (Issue #352)
  - Logs and violations now stored in `XDG_STATE_HOME/ai-guardian` (default `~/.local/state/ai-guardian`)
  - Cache paths respect `XDG_CACHE_HOME` via centralized `get_cache_dir()`
  - Environment variable overrides: `AI_GUARDIAN_STATE_DIR`, `AI_GUARDIAN_CACHE_DIR`
  - Backward-compatible migration from old config dir on first run

### Fixed

- **Console pattern server toggle no longer destroys configuration** (Issue #418)
  - Toggle modes now only write the `enabled` field; other settings (url, auth, cache) are preserved

- **gitleaks:allow guidance now correctly says "at the end of the line"** (Issue #416)
  - Fixed incorrect placement instructions in block messages and Console help text

- **Prompt injection violation logs show actual pattern details** (Issue #420)
  - Previously hardcoded "Heuristic pattern detected" with confidence 0.95 for all violations
  - Now shows actual matched pattern, matched text, and real confidence score from detector

- **Directory blocking violations report correct reason** (Issue #347)
  - Previously always reported ".ai-read-deny marker found" even for directory rule violations
  - Now correctly distinguishes between marker-based and rule-based blocking with matched pattern

- **PII violations now include line numbers** (Issue #359)
  - PII and secret redaction violation logging populates `line_number` and `column` from redaction results instead of hardcoding `None`

- **Scanner installer respects --use-pinned and --version flags** (Issue #295)
  - After package manager installation, verifies installed version matches target; falls back to direct download if mismatched

- **GitHub Workflows: scanner versions synced with pyproject.toml** (Issue #289)
  - CI now installs exact pinned versions of all three scanners (gitleaks, betterleaks, leaktk) from pyproject.toml

- **Pattern server configuration section name corrected** (PR #318)
  - Integration test workflow now uses `pattern_servers` (plural) instead of incorrect singular form

## [1.5.1] - 2026-04-28

### Security

- **Scanner Installer: SHA-256 Checksum Verification** (Issue #278)
  - **Supply Chain Security**: All scanner binaries are now verified using SHA-256 checksums from GitHub releases
  - **MITM Protection**: Prevents man-in-the-middle attacks during download by validating binary integrity
  - **Automatic Verification**: Downloads checksums file and verifies hash matches before installation
  - **Graceful Degradation**: Installation continues with warning if checksums unavailable (older releases)
  - **Multi-Scanner Support**: Handles scanner-specific naming conventions:
    - gitleaks: `gitleaks_8.30.1_checksums.txt`
    - betterleaks: `checksums.txt`
    - leaktk: `leaktk_0.2.10_checksums.txt`
  - **Security Hardening**:
    - Path traversal protection using `os.path.basename()` sanitization
    - Version format validation (regex `^\d+\.\d+\.\d+$`) prevents URL manipulation
    - Content validation ensures checksum files are not empty or malformed
    - Binary mode indicator support (`*filename` format in checksums)
  - **User Feedback**: Console messages show verification status:
    - `✓ Checksum verification passed for {scanner} {version}` (success)
    - `⚠ Checksum verification skipped - checksums file not available` (graceful degradation)
  - **Implementation**:
    - Added `_download_checksums()` method with HTTP error handling
    - Added `_verify_checksum()` method with SHA-256 computation and validation
    - Added version format validation in `install_from_download()`
    - Added explicit archive format validation (tar.gz, tar.xz, zip)
  - **Test Coverage**: Added 17 comprehensive test cases covering:
    - Scanner-specific checksums file naming conventions
    - Network failures and HTTP errors
    - Empty and malformed checksums files
    - Hash verification (success, mismatch, missing files)
    - Multi-file checksums parsing
    - Case-insensitive hash comparison
    - Binary mode indicator handling (`*filename`)
    - Path traversal sanitization
    - Version format validation (valid/invalid formats)
  - **Total Test Suite**: 49 scanner installer tests, 1,222 full suite tests (all passing)

## [1.5.0] - 2026-04-27

### Added


- **Scanner Installer: Skip Installation if Already Up-to-Date** (Issue #271)
  - **Smart Version Checking**: `ai-guardian scanner install` now checks if scanner is already installed before downloading
  - **Skip When Up-to-Date**: Automatically skips installation if the latest version is already installed
  - **Upgrade Detection**: Automatically upgrades when a newer version is available
  - **Downgrade Protection**: Does not auto-downgrade without explicit `--version` flag
  - **Explicit Control**: `--version` flag allows downgrade or reinstall of specific versions
  - **Clear Messaging**: Shows current version, target version, and action taken
  - **Version Comparison**: Proper semantic version comparison (e.g., 8.30.1 < 8.31.0)
  - **Performance**: Saves bandwidth and time by skipping unnecessary downloads
  - **Implementation**:
    - Added `_get_installed_version()` method to detect currently installed version
    - Added `_compare_versions()` method for semantic version comparison
    - Updated `install()` method with version checking logic
  - **Test Coverage**: Added 10 comprehensive test cases for version checking scenarios
  - **Benefits**: Faster installation, bandwidth-friendly, safe (no auto-downgrades), clear user feedback

- **SSRF Protection: Wildcard Domain Pattern Support** (Issue #253)
  - **New Feature**: Added wildcard pattern matching for `additional_blocked_domains` configuration
  - **Syntax**: Supports `*` (match zero or more characters) and `?` (match exactly one character)
  - **Pattern Examples**:
    - `*.internal.com` - Block all .internal.com domains (api.internal.com, db.internal.com)
    - `admin.*` - Block admin.* with any suffix (admin.example.com, admin.local)
    - `*.corp.*` - Block all .corp. domains (api.corp.internal, db.corp.example.com)
    - `metadata.*` - Block all metadata.* endpoints (metadata.aws.com, metadata.google.internal)
    - `test?.example.com` - Block test1.example.com, test2.example.com, testa.example.com
  - **Use Cases**:
    - Block entire TLDs with single pattern (`*.internal`, `*.local`)
    - Block subdomain patterns (`*.admin.example.com`)
    - Block naming patterns (`metadata.*`, `admin.*`)
    - Enterprise-wide policies with simplified configuration
  - **Backward Compatibility**: Exact domain matching and subdomain matching still work as before
  - **Pattern Validation**: Invalid patterns are rejected at config load time with warnings
  - **Performance**: Patterns stored separately from exact domains for optimal matching
  - **Files Modified**:
    - `src/ai_guardian/ssrf_protector.py`: Added `fnmatch` import, `_blocked_domain_patterns` list, `_is_valid_domain_pattern()` method, pattern matching in `_is_domain_blocked()`
    - `src/ai_guardian/schemas/ai-guardian-config.schema.json`: Updated `additional_blocked_domains` description with wildcard pattern syntax
    - `docs/SSRF_PROTECTION.md`: Comprehensive documentation with wildcard pattern examples and use cases
  - **Tests**: Added 11 comprehensive test cases in `TestWildcardDomainPatterns` class
  - **Impact**: Users can now use flexible wildcard patterns to block domains more efficiently

- **SSRF Protection: URL Allow-List Support** (Issue #252)
  - **New Configuration**: Added `allowed_domains` array to `ssrf_protection` configuration
  - **Purpose**: Allow specific trusted domains/URLs while maintaining core protections
  - **Evaluation Order (Deny-First)**: 
    1. Check immutable core protections (metadata endpoints, dangerous schemes, private IPs)
    2. Check deny-list (`additional_blocked_domains`)
    3. Check allow-list (`allowed_domains`) - can override step 2, NOT step 1
  - **Use Cases**:
    - Allow specific internal APIs while blocking other internal domains
    - Allow development/staging servers without allowing all localhost
    - Allow specific partner domains on restricted networks
    - Provide granular control to override broad domain blocks
  - **Domain Matching**: Supports exact match and subdomain matching
    - `"api.corp.internal"` allows `api.corp.internal` and `v1.api.corp.internal`
  - **Security**: Cannot override immutable core protections
    - Metadata endpoints (169.254.169.254, metadata.google.internal) remain blocked
    - Private IP ranges (RFC 1918) remain blocked
    - Dangerous schemes (file://, gopher://) remain blocked
  - **Files Modified**:
    - `src/ai_guardian/schemas/ai-guardian-config.schema.json`: Added `allowed_domains` property
    - `src/ai_guardian/ssrf_protector.py`: Implemented allow-list logic in `_check_url()`
    - `src/ai_guardian/setup.py`: Added `allowed_domains: []` to default config
    - `ai-guardian-example.json`: Added examples and security warnings
    - `docs/SSRF_PROTECTION.md`: Comprehensive documentation with examples
    - `AGENTS.md`: Enhanced schema change checklist
  - **Tests**: Added 9 comprehensive test cases in `tests/test_ssrf_protection.py`
  - **Impact**: Users can now create exceptions for specific domains while maintaining strong security boundaries

### Security

- **Cascading Priority for Remote Config URLs to Prevent Immutability Bypass** (Issue #255)
  - **Fix**: Implemented first-match-wins cascading for remote config URL sources
  - **Vulnerability**: Users could bypass `immutable: true` enterprise policies by adding their own remote config URLs in local/user configs
  - **Attack Scenario**: Enterprise deploys system config with `immutable: true` SSRF protection, user adds attacker-controlled remote URL that disables it
  - **Solution**: Remote config URLs now follow strict priority hierarchy (system config → env var → user config → local config)
    - **System config** (`/etc/ai-guardian/remote-configs.json`): Highest priority, requires root/admin, blocks all lower sources
    - **Environment variable** (`AI_GUARDIAN_REMOTE_CONFIG_URLS`): Second priority, blocks user/local sources
    - **User config** (`~/.config/ai-guardian/ai-guardian.json`): Third priority, blocks local config
    - **Local config** (`~/.ai-guardian.json`): Lowest priority fallback
  - **Implementation**:
    - Added `_get_system_config_path()`: Returns platform-specific system config path (Linux/macOS: `/etc/ai-guardian/remote-configs.json`, Windows: `C:\ProgramData\ai-guardian\remote-configs.json`)
    - Refactored `_load_remote_configs()`: Implements cascading with early return on first match
    - Added `_fetch_remote_configs()`: Helper to reduce code duplication
  - **Testing**: Added 5 new test cases in `test_immutable_configs.py`:
    - System config blocks user remote URLs
    - Environment variable takes priority over user config
    - User remote URLs work without system config
    - Local config has lowest priority
    - Legacy format (direct list) still works
  - **Backward Compatibility**: ✅ Existing users with remote_configs in user/local files continue working unchanged
  - **Enterprise Deployment**: Enterprises can now deploy one system config file to enforce policies across all users
  - **Impact**: Critical security fix - prevents users from bypassing all enterprise security policies

### Changed

- **Documentation: Clarify SSRF Protection Limitations and Scope** (Issue #256)
  - **Updated docs/SSRF_PROTECTION.md**: Added "Important Limitations" section at the top
    - Clearly explains what SSRF protection CAN and CANNOT protect against
    - Documents pattern-based filtering vs comprehensive network security
    - Added OpenShell integration guide for comprehensive SSRF protection
    - Explains hook-based architecture and why limitations exist
  - **Updated README.md**: SSRF section now includes limitation disclaimers
    - Examples of what CAN be blocked (explicit URLs in Bash/tool parameters)
    - Examples of what CANNOT be blocked (MCP server internal calls)
    - Recommendations for network-level controls and MCP sandboxing
  - **Updated ai-guardian-example.json**: Added comprehensive limitation comments
    - Explains pattern-based filtering cannot replace network security
    - Documents that it cannot detect MCP internal network calls
    - Notes about HTTP redirects and dynamic URL construction
  - **Updated src/ai_guardian/ssrf_protector.py**: Enhanced module docstring
    - Clear architecture explanation (hook-based, not proxy)
    - Defense in depth strategy documentation
    - Usage guidance and limitations
  - **Updated error messages**: SSRF block/warn messages now mention limitations
    - Changed "SSRF ATTACK DETECTED" to "SSRF PATTERN DETECTED"
    - Added note about pattern-based detection
    - Recommends firewall rules and network controls
    - References docs/SSRF_PROTECTION.md
  - **Impact**: Users now have realistic expectations about SSRF protection scope
  - **Key Message**: ai-guardian catches obvious SSRF attempts in command strings but cannot replace network-level security

### Fixed

- **Setup.py Missing permissions_directories in Default Config Template** (Issue #240)
  - **Fix**: Added `permissions_directories` field to `_get_default_config_template()` function in setup.py
  - **Problem**: Users running `ai-guardian setup --create-config` got incomplete configuration files missing the `permissions_directories` option
  - **Root Cause**: When `permissions_directories` was added to the schema, setup.py wasn't updated (violating AGENTS.md configuration consistency guidelines)
  - **Impact**: Generated configs now include `permissions_directories` with comprehensive comments and examples:
    - Local directory scanning example (`~/.claude/skills`)
    - GitHub repository scanning example with token_env
    - Documentation explaining it's OPTIONAL/ADVANCED and most users should prefer remote_configs
  - **Location**: Added to setup.py after permissions section (line 893), before directory_rules
  - **Verification**: Tested via `_get_default_config_template()` and confirmed field appears in generated config

- **JSON Schema Missing Definitions** (Issue #239)
  - **Fix**: Added missing `pattern_server_auth` and `pattern_server_cache` definitions to schema
  - **Problem**: Schema referenced definitions that didn't exist, causing validation failures for pattern_server configurations
  - **Root Cause**: When pattern_server was refactored from root-level to nested under each feature, the auth/cache structures were not extracted into reusable definitions
  - **Impact**: Schema validation now succeeds for configs using pattern_server with auth/cache in:
    - `secret_redaction.pattern_server`
    - `prompt_injection.unicode_detection.pattern_server`
    - `ssrf_protection.pattern_server`
    - `config_file_scanning.pattern_server`
  - **Tests**: Added comprehensive test suite (`test_pattern_server_definitions.py`) validating all pattern_server references

### Added


- **LeakTK Pattern Server Documentation** (Issue #156)
  - Added comprehensive documentation for using LeakTK patterns as a pattern server
  - **README.md**: Added "Using LeakTK Patterns (Recommended)" section with quick start guide
    - Benefits: Free, community-maintained, 104+ rules, no authentication required
    - Configuration example using GitHub raw content URL
    - Verification steps and expected log output
  - **docs/SECRET_SCANNING.md**: Added complete LeakTK integration guide
    - Pattern sources comparison table (LeakTK vs Gitleaks defaults)
    - Configuration options and cache settings
    - Pattern version compatibility table (8.25.0, 8.26.0, 8.27.0)
    - Troubleshooting guide and common issues
    - FAQ section covering offline usage, updates, firewall workarounds
    - Example workflows for combining LeakTK with project-specific patterns
  - **ai-guardian-example.json**: Added LeakTK example configuration
    - Documented free, community-maintained pattern source
    - Reference to LeakTK GitHub repository
  - Feature already implemented and tested - documentation completes the feature
  - LeakTK repository: https://github.com/leaktk/patterns

- **Permissions Comparison Documentation** (Issue #235)
  - Added comprehensive `docs/PERMISSIONS_COMPARISON.md` comparing ai-guardian.json vs settings.json permission systems
  - Covers: architecture diagrams, capabilities comparison, enforcement differences, when to use each
  - Explains Skills are only controllable via ai-guardian.json (not in settings.json)
  - Documents defense-in-depth best practices using both permission systems
  - Includes example configurations for different scenarios (user preferences, enterprise enforcement, defense-in-depth)
  - Cross-referenced from README.md "When to Use" section

### Changed

- **Removed Unused Maintainer Detection Code** (Issue #231)
  - **Change**: Removed ~450 lines of unused GitHub maintainer detection code from `tool_policy.py`
  - **Removed Methods**: 
    - `_get_git_repo_info()` - Extract GitHub repo info from git remote
    - `_get_authenticated_github_user()` - Get GitHub username from gh CLI
    - `_check_github_collaborator()` - Check if user has write access via GitHub API
    - `_get_maintainer_cache()` - Read maintainer status from cache
    - `_cache_maintainer_status()` - Write maintainer status to cache
    - `_is_github_maintainer_cached()` - Main maintainer check with caching
    - `_diagnose_maintainer_bypass()` - Diagnostic helper for bypass issues
  - **Rationale**: 
    - These methods were no longer called in production code since commit `0f6e456` (April 19, 2026)
    - The `_should_skip_immutable_protection()` bypass logic was simplified to allow ALL contributors to edit development source (fork + PR workflow)
    - Maintainer check was removed to enable standard open-source contribution workflow
    - Security relies on PR review process, not role-based permissions
  - **Impact**:
    - Reduced codebase complexity (~450 lines removed)
    - Removed dependency on `gh` CLI for permission checking
    - Eliminated cache file management (`~/.cache/ai-guardian/maintainer-status.json`)
    - Faster hook execution (no GitHub API calls)
  - **Tests Updated**:
    - Renamed `test_maintainer_bypass.py` → `test_development_source_bypass.py`
    - Removed tests for unused GitHub API methods (~400 lines)
    - Kept tests for core bypass logic (`_should_skip_immutable_protection`)
    - Removed `@patch('_is_github_maintainer_cached')` mocks from other test files
  - **No Breaking Changes**: The permission model remains unchanged - all contributors can edit development source, config/hooks/cache remain always protected

- **Secret Redaction Always Redacts (Removed Block Mode)** (Issue #234)
  - **Change**: `secret_redaction.action="block"` mode removed - secrets are now always redacted (never blocked)
  - **New Default**: Changed default action from "log-only" to "warn" for better UX
  - **Valid Actions**: Only "warn" (redact with notification) and "log-only" (redact silently) are now supported
  - **Breaking Change**: Configurations with `action="block"` will fail validation with a helpful error message
  - **Rationale**: 
    - Simpler UX - one behavior, no confusing modes
    - Better DX - AI can still help (sees masked secrets) instead of being completely blocked
    - Same security - real secrets never reach AI
    - Less friction - reading files with secrets doesn't stop work
    - Name matches behavior - "secret_redaction" actually redacts
  - **Migration**: For users who want old "block" behavior, add sensitive files to `.gitleaksignore` to prevent reading them entirely
  - **Impact**: 
    - Schema updated to only allow "warn" and "log-only" 
    - Console dropdown no longer shows "block" option
    - Config validation rejects "block" with migration guidance
    - Default config templates updated to use "warn"
  - **Files Modified**:
    - `src/ai_guardian/schemas/ai-guardian-config.schema.json`: Updated enum and default
    - `src/ai_guardian/secret_redactor.py`: Updated docstring and default
    - `src/ai_guardian/__init__.py`: Simplified to always redact when enabled
    - `src/ai_guardian/config_inspector.py`: Added validation to reject "block"
    - `src/ai_guardian/setup.py`: Changed default from "log-only" to "warn"
    - `src/ai_guardian/tui/secret_redaction.py`: Removed "block" option, default "warn"
  - **Tests Updated**: All tests expecting blocking behavior updated to expect redaction

### Fixed

- **Ignore Files Patterns with Leading `**/` Don't Work** (Issue #232)
  - **Root Cause**: Three different implementations of `ignore_files` pattern matching existed with inconsistent behavior:
    - Secret Scanning (`__init__.py`) - ✅ WORKED - Used custom `_match_leading_doublestar_pattern()` helper
    - Prompt Injection (`prompt_injection.py`) - ❌ BROKEN - Only used `Path.match()` which doesn't properly handle leading `**/`
    - Config Scanner (`config_scanner.py`) - ❌ BROKEN - Used `fnmatch.fnmatch()` which doesn't support `**/`
  - **Fix**: Extracted `_match_leading_doublestar_pattern()` to `src/ai_guardian/utils/path_matching.py` module and updated all three implementations to use it consistently
  - **Impact**: All detectors now properly support leading `**/` patterns for ignoring files in subdirectories
  - **Files Modified**:
    - `src/ai_guardian/utils/path_matching.py`: Created new utility module with `match_leading_doublestar_pattern()` and `match_ignore_pattern()` functions
    - `src/ai_guardian/__init__.py`: Updated to import and use utility function
    - `src/ai_guardian/prompt_injection.py`: Updated `_is_file_ignored()` to use utility function
    - `src/ai_guardian/config_scanner.py`: Updated `_should_ignore_file()` to use utility function
  - **Tests Added**: 
    - `tests/test_unicode_attacks.py::UnicodeDetectorIgnoreFilesTest` - 2 tests for unicode detection ignore patterns
    - `tests/test_config_scanner.py::TestConfigFileScanner::test_ignore_files_leading_double_star_patterns` - 1 test for config scanner

- **Config File Scanner File Path Extraction Bug** (Issue #228)
  - **Problem**: Config File Scanner failed to extract file path from PreToolUse hook data when using the Read tool, allowing malicious config files (CLAUDE.md, AGENTS.md, etc.) to pass through unscanned and potentially exfiltrate credentials
  - **Root Cause**: `extract_file_content_from_tool()` function only checked `tool_use.parameters.file_path` format, but Claude Code actually sends `tool_use.input.file_path`, causing file path extraction to fail with "Could not extract file path from hook data" error
  - **Fix**: Added support for `tool_use.input.file_path` format in file path extraction logic to match Claude Code's actual hook data structure
  - **Impact**: Config File Scanner now properly scans config files for exfiltration patterns (`env | curl`, AWS S3 uploads, etc.) when read via PreToolUse hooks, protecting against persistent credential theft attacks
  - **Affected Versions**: v1.3.0, v1.4.0, v1.4.1, v1.5.0-dev (bug present since Config File Scanner was added in v1.3.0)
  - **Test Added**: 1 new regression test verifying file path extraction from `tool_use.input` format (`tests/test_ai_guardian.py::test_pretooluse_hook_with_tool_use_input_format`)
  - **Files Modified**:
    - `src/ai_guardian/__init__.py`: Added `tool_use.input.file_path` check in `extract_file_content_from_tool()`
    - `tests/test_ai_guardian.py`: Added regression test with actual Claude Code hook format

- **PreToolUse Hook Auto-Approve Bug** (Issue #224)
  - **Problem**: PreToolUse hook was auto-approving all Edit and Write operations when no secrets were detected, bypassing Claude Code's normal permission prompts and removing user control over file modifications
  - **Root Cause**: `format_response()` function returned `permissionDecision: allow` for clean files, which instructed Claude Code to auto-approve the operation
  - **Fix**: PreToolUse now only returns `permissionDecision` when denying operations (secrets/threats detected). For clean operations, returns empty response to allow Claude Code's normal permission system to prompt the user
  - **Impact**: Users now properly see permission prompts for Edit/Write operations, maintaining informed consent for file modifications
  - **Affected Versions**: v1.3.0, v1.4.0, v1.4.1 (bug introduced with GitHub Copilot integration in v1.3.0)
  - **Tests Added**: 
    - **Unit Tests**: 4 new PreToolUse permission tests covering Edit/Write operations for both Claude Code and GitHub Copilot IDE types (`tests/test_hook_processing.py`)
    - **Integration Tests**: 6 new end-to-end tests verifying no auto-approve behavior (`tests/test_pretooluse_no_auto_approve.py`):
      - Edit operations (Claude Code and GitHub Copilot)
      - Write operations (Claude Code and GitHub Copilot)
      - Verification that secrets still trigger deny (no regression)
      - End-to-end workflow showing user sees permission prompts
    - **User Experience Contract Tests**: 5 new tests documenting expected UX (`tests/test_user_experience_contract.py`):
      - Read with secret → Immediate denial (no prompt shown)
      - Edit without secret → Permission prompt shown
      - Comparison test showing different UX for secret vs clean operations
      - Documentation test describing expected behavior for users
      - Manual verification guide for testing in actual Claude Code IDE
    - Updated 3 existing tests to expect correct behavior (no auto-approve)
  - **Files Modified**:
    - `src/ai_guardian/__init__.py`: Updated `format_response()` for both GITHUB_COPILOT and CLAUDE_CODE paths
    - `tests/test_hook_processing.py`: Added `PreToolUsePermissionTests` class with 4 unit tests
    - `tests/test_pretooluse_no_auto_approve.py`: Added 6 integration tests (NEW FILE)
    - `tests/test_ai_guardian.py`: Updated 3 tests to expect correct behavior

### Added


- **Local File Path Support in Remote Configurations** (Issue #223)
  - **Feature**: `remote_configs` now supports local file paths in addition to HTTPS URLs
  - **Supported Formats**:
    - `file://` URLs: `file:///etc/ai-guardian/config.toml`
    - Absolute paths: `/etc/ai-guardian/config.toml`
    - Tilde expansion: `~/team-configs/allowed-tools.toml`
  - **Caching Behavior**:
    - HTTPS URLs: Cached with TTL (default: 12h refresh, 168h expiration)
    - Local files: Always read fresh (bypass cache for immediate updates)
  - **Use Cases**:
    - Development/Testing: Test configs locally without HTTPS server
    - Air-Gapped Environments: Offline systems without internet access
    - Corporate Networks: Shared network drives (NFS, SMB)
    - CI/CD Pipelines: Build environments with local config files
    - Team Configuration: Shared configs in home directories
  - **Security**:
    - Path traversal prevention with `Path.resolve(strict=True)`
    - File type validation (regular files only)
    - Permission checks before reading
    - Symlinks followed safely with warnings
  - **Implementation**:
    - New `RemoteFetcher._fetch_from_local_file()` method
    - Updated `fetch_config()` to bypass caching for local paths
    - Both JSON and TOML formats supported
  - **Tests Added**:
    - **Unit Tests** (`tests/test_remote_fetcher_local.py`): 27 passing tests
      - file:// URLs, absolute paths, tilde expansion
      - JSON/TOML format support
      - Error handling (missing files, permission denied, invalid format)
      - Symlink following and broken symlinks
      - No-caching behavior verification
      - Edge cases (spaces in paths, special characters, UTF-8)
    - **Integration Tests** (`tests/test_integration_local_remote_configs.py`): 10 passing tests
      - Multiple local sources, cache isolation
      - Mixed local and HTTPS URLs
      - File updates reflected immediately
      - Concurrent updates, error recovery
  - **Documentation**:
    - README.md updated with local file path examples and use cases
    - Security features documented
  - **Files Modified**:
    - `src/ai_guardian/remote_fetcher.py`: Added local file path support
    - `README.md`: Added "Local File Paths" section under "Remote Configs vs Directory Discovery"


- **Integration and Use-Case Tests with Mock MCP Server** (Issue #220)
  - **Comprehensive test infrastructure** for MCP tool security testing
  - **Test Fixtures**:
    - `tests/fixtures/mock_mcp_server.py`: Simulates NotebookLM and other MCP tools with controllable responses
    - `tests/fixtures/attack_constants.py`: Comprehensive attack patterns (SSRF, secrets, prompt injection, exfiltration)
    - `tests/conftest.py`: Pytest fixtures for test isolation using `AI_GUARDIAN_CONFIG_DIR`
  - **Integration Tests** (`tests/test_integration_mcp.py`): 24 passing tests
    - MCP Tool Permission Tests (6 tests): Allowlists, blocklists, wildcards, custom servers
    - Secret Scanning Tests (4 tests): Secrets in notebook titles/sources, multiple secret types, false positives
    - Prompt Injection Tests (4 tests): Injection in parameters, role-switching, delimiter escapes
    - SSRF Protection Tests (5 tests): AWS/GCP metadata, private IPs, public URLs, Bash-specific behavior
    - Config Exfiltration Tests (3 tests): Curl exfiltration, credential theft in CLAUDE.md/AGENTS.md
    - Combined Protection Tests (2 tests): Multiple protections working together, defense in depth
  - **PostToolUse Tests** (`tests/test_posttooluse_mcp.py`): 13 passing tests
    - Secret Scanning (5 tests): Bash/Read output with secrets, Write/Edit skipped, clean outputs
    - Content Scanning (3 tests): Documents that PostToolUse only scans secrets, not prompt injection
    - MCP Tool Tests (3 tests): MCP responses, notebook lists, current scanning behavior
    - Redaction Tests (1 test): Secret redaction mode behavior
    - Combined Tests (1 test): Multiple threats in output
  - **Use-Case Tests** (`tests/test_use_cases.py`): 13 passing tests covering realistic scenarios
    - Data Exfiltration Attack (3 tests): Multi-stage attack attempts via Bash, NotebookLM, SSRF
    - Prompt Injection Chain (2 tests): Attempts to disable protections, privilege escalation prevention
    - Legitimate Workflow (2 tests): Normal NotebookLM usage, security code discussion
    - Enterprise Policy (2 tests): Approved MCP servers only, paranoid mode (all MCP blocked)
    - Multi-Stage Attack (2 tests): Combined injection + exfiltration, privilege escalation
    - Real-World Scenarios (2 tests): Developer workflows, documentation discussions
  - **Test Isolation**: All tests run in isolated temporary directories via `isolated_config_dir` fixture
  - **Benefits**:
    - ✅ Validates protections work with real MCP tool calls
    - ✅ Catches integration issues between protection layers
    - ✅ Serves as usage examples for MCP security
    - ✅ Prevents regression in multi-protection scenarios
    - ✅ Documents actual implementation behavior (SSRF only on Bash, PostToolUse only scans secrets)
    - ✅ Tests realistic attack chains and defense-in-depth
    - ✅ Validates enterprise policy enforcement
    - ✅ Ensures legitimate workflows work without false positives
  - **Hook Processing Tests** (`tests/test_hook_processing.py`): 8 passing tests
    - Hook Input Parsing (4 tests): Valid JSON, UserPromptSubmit, PreToolUse, PostToolUse
    - Tool Response Extraction (4 tests): Bash output, Read content, MCP tools, Write/Edit skipped
  - **Advanced Tool Policy Tests** (`tests/test_tool_policy_advanced.py`): 11 passing tests
    - Rule Matching (2 tests): Wildcard patterns, case sensitivity
    - Rule Ordering (2 tests): First-match wins, default behavior
    - Config Variations (4 tests): Disabled permissions, empty rules, no config, invalid rules
    - Edge Cases (3 tests): Empty tool name, null tool name, missing field
  - **End-to-End Workflow Tests** (`tests/test_e2e_workflow.py`): 5 passing tests
    - Legitimate Workflows (3 tests): NotebookLM, Bash, Read→Write workflows
    - Secret Detection (1 test): Secret caught at PostToolUse stage
    - Multi-Tool Sequence (1 test): Multiple tools in realistic workflow
  - **74 new integration and use-case tests** covering all 9 protection layers with MCP tools
  - **Test Coverage**: Core protection modules at 70% (excluding Console/setup: 4,500 statements, 1,359 missing)
  - Part of ongoing MCP security validation effort

- **Pattern Server Support for Security Features** (Issue #206, Epic #186)
  - **OPTIONAL/ADVANCED**: Enterprise pattern server integration for centralized pattern management
  - **Three-tier pattern system**: Immutable core + Pattern server/defaults + Local config additions
  - **Multiple pattern types**: SSRF, Unicode, Config Scanner, Secret Redaction
  - **Fallback chain**: Pattern server → cache → hardcoded defaults (always available)
  - **Features**:
    - `PatternServerClient` extended for multiple pattern types (ssrf, unicode, config-exfil, secrets)
    - New `PatternLoader` base class with feature-specific implementations
    - TOML pattern file format with native comment support
    - Source attribution tracking (IMMUTABLE, SERVER, DEFAULT, LOCAL_CONFIG)
    - Pattern server configuration in JSON schema for all four features
    - Maintains 100% backward compatibility (works without pattern server)
  - **Secret Redaction** (highest value): New secret formats deployed in <24h
    - Override modes: `replace` (server replaces defaults) or `extend` (adds to defaults)  
    - 35+ secret types enterprise-manageable
  - **SSRF Protection** (second priority): RFC 1918 ranges overridable via pattern server
    - Immutable: Cloud metadata endpoints, dangerous URL schemes
    - Overridable: Private IP ranges (enables Docker access for dev teams)
  - **Unicode Detection**: Homoglyph patterns updateable as new scripts emerge
    - Immutable: Zero-width chars, bidi overrides (Unicode spec-based)
    - Overridable: 80+ homoglyph pairs managed via pattern server
  - **Config Scanner**: Enterprise-specific exfiltration patterns
    - Immutable: Core patterns (env|curl, AWS S3, GCP storage)
    - Overridable: Additional pattern server patterns
  - **Implementation**: 6 new files, 4 feature integrations, schema updates
  - **Documentation**: Implementation plan, example patterns (future)
  - **Testing**: Backward compatibility verified, pattern server optional

- **Phase 5: Integration & Polish - CI/CD and Static Analysis** (Issue #198)
  - **New `scan` Command** for static repository scanning
    - Scans files statically without running as a hook
    - Integrates all Phase 1-4 security checks (SSRF, Unicode, Config Scanner, Secret Detection)
    - File discovery with glob patterns: `--include "*.md"`, `--exclude "node_modules/*"`
    - Config-only mode: `--config-only` to scan only AI configuration files
    - Multiple output formats: text (default), JSON (`--json-output`), SARIF (`--sarif-output`)
    - CI/CD ready: `--exit-code` flag exits with code 1 if issues found
    - Usage: `ai-guardian scan . --sarif-output results.sarif --exit-code`
  - **SARIF 2.1.0 Output Format** for CI/CD integration
    - Industry-standard Static Analysis Results Interchange Format
    - GitHub Code Scanning integration: findings appear in Security tab and PR reviews
    - GitLab Security Dashboard support
    - 5 rule definitions: SSRF-001, UNICODE-001, CONFIG-001, SECRET-001, PROMPT-INJECTION-001
    - Complete metadata: file locations, line numbers, code snippets, severity levels
    - Upload to GitHub: `github/codeql-action/upload-sarif@v3`
  - **Pre-commit Hook Templates** for git workflow integration
    - Git hook template: `templates/pre-commit.sh` for direct git integration
    - pre-commit framework template: `templates/.pre-commit-config.yaml`
    - **Safe, non-invasive approach**: `ai-guardian setup --pre-commit` provides templates and instructions WITHOUT auto-installing
    - Detects existing hooks and warns to prevent conflicts with company/team hooks
    - Shows manual integration steps with copy-paste commands
    - Provides snippet for adding to existing pre-commit configurations
    - Scans staged files before commit, blocks commit if issues found
    - Skip with: `git commit --no-verify` (not recommended)
  - **Performance Benchmark Suite** (tests/benchmark_phases.py)
    - Validates all Phase 1-4 features meet performance targets
    - SSRF check: <1ms per URL (measured: ~0.016ms ✅)
    - Unicode detection: <5ms per check
    - Config file scanning: <10ms per file
    - Secret redaction: <5ms per 10KB output
    - Total overhead: <20ms for all features combined
    - Run with: `pytest tests/benchmark_phases.py -v -m benchmark`
  - **Hermes Payload Validation Suite** (tests/test_hermes_payloads.py)
    - Validates 10/10 Hermes Security Framework payloads
    - Phase 1 (SSRF): 2/2 payloads - metadata endpoint, private IP
    - Phase 2 (Unicode): 3/3 payloads - zero-width, bidi override, homoglyphs
    - Phase 3 (Config): 3/3 payloads - env|curl, base64 exfil, AWS S3 upload
    - Phase 4 (Secrets): 2/2 payloads - GitHub tokens, AWS keys
    - Meta-tests: Coverage comparison showing AI Guardian exceeds Hermes framework
    - Run with: `pytest tests/test_hermes_payloads.py -v -m hermes`
  - **GitHub Actions Workflow Example**
    - Ready-to-use workflow for security scanning in CI
    - Automated SARIF upload to GitHub Code Scanning
    - Findings visible in Security tab and PR reviews
  - **Complete documentation updates**
    - Scan command examples in README
    - SARIF output integration guide
    - Pre-commit hook setup instructions
    - Performance benchmarks and targets
  - **Production-ready features**:
    - ✅ Runtime protection (hooks)
    - ✅ Static analysis (scan command)  
    - ✅ CI/CD integration (SARIF output)
    - ✅ Developer workflow (pre-commit hooks)
    - ✅ Performance validated (<20ms overhead)
    - ✅ Hermes framework validated (10/10 payloads)
  - Part of Hermes Security Patterns integration epic (Issue #186)
- **Secret Redaction for Tool Outputs** (Issue #197, Phase 4: Hermes Security Patterns)
  - Redacts secrets from tool outputs instead of blocking them entirely, enabling work to continue while protecting credentials
  - **Defense-in-depth**: Redaction provides a safety net when secrets are unavoidable, complementing existing blocking mechanisms
  - **35+ secret types detected and redacted**:
    - API keys: OpenAI (sk-proj-*), GitHub (ghp_*, gho_*, ghr_*, ghs_*), Anthropic (sk-ant-*), GitLab (glpat-*), Google (AIza*), npm, PyPI
    - Cloud provider keys: AWS (AKIA*, aws_secret_access_key), Azure client secrets, Google OAuth tokens
    - Payment/SaaS: Stripe (sk_live_*, pk_live_*), Twilio (SK*), SendGrid (SG.*), Mailgun (key-*), Slack (xox*)
    - Private keys: RSA, SSH, PGP (full redaction for maximum security)
    - Structured formats: Environment variables, JSON fields, HTTP headers, database connection strings
    - Generic patterns: Long hex strings, Base64 encoded secrets
  - **Multiple masking strategies**:
    - `preserve_prefix_suffix`: Keep first 6 + last 4 characters for debugging (e.g., "sk-pro...1vwx")
    - `full_redact`: Complete replacement with "[HIDDEN TYPE]" for high-sensitivity secrets
    - `env_assignment`: Preserve variable name (e.g., "AWS_SECRET_KEY=[HIDDEN]")
    - `json_field`: Preserve JSON structure (e.g., '{"api_key": "[HIDDEN]"}')
    - `connection_string`: Preserve endpoint info (e.g., "mongodb://user:[HIDDEN]@host:port/db")
  - **Configuration** (`secret_redaction` section):
    - `enabled`: Toggle redaction feature (default: true)
    - `action`: "log-only" (redact silently), "warn" (redact with user warning), "block" (original blocking behavior, default: log-only)
    - `preserve_format`: Enable prefix/suffix preservation (default: true)
    - `log_redactions`: Log all redaction events (default: true)
    - `additional_patterns`: Add custom secret patterns with regex
  - **Real-world scenarios enabled**:
    - ✅ Environment variable debugging: See `AWS_REGION=us-east-1` while `AWS_SECRET_KEY=[HIDDEN]`
    - ✅ Log file analysis: Review 10,000 log lines with buried secrets redacted inline
    - ✅ Config file review: See structure (`host: prod-db.example.com`) with passwords hidden
    - ✅ Git history analysis: View commits with accidentally-committed secrets redacted
  - **Integration**: Works automatically with PostToolUse hook, requires no changes to existing workflows
  - **Performance**: <5ms overhead per tool output (sub-50ms for 10KB text with 35+ patterns)
  - **Logging**: All redactions logged to violation logger with type, position, and count metadata
  - **Testing**: 28 comprehensive test cases covering all secret types, masking strategies, and edge cases
  - Part of Hermes Security Patterns integration (defense-in-depth approach)

- **SSRF (Server-Side Request Forgery) Protection** (Issue #194, Phase 1 of #186)
  - Prevents AI agents from accessing private networks, cloud metadata endpoints, and dangerous URL schemes
  - Immutable core protections (cannot be disabled):
    - Private IP ranges (RFC 1918): 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, 169.254.0.0/16
    - IPv6 private ranges: ::1/128, fc00::/7, fe80::/10
    - Cloud metadata endpoints: 169.254.169.254 (AWS/Azure), metadata.google.internal (GCP), fd00:ec2::254 (AWS IPv6)
    - Dangerous URL schemes: file://, gopher://, ftp://, data://, dict://, ldap://
  - Fast performance: <1ms overhead per Bash command
  - No false positives: Public AWS services (s3.amazonaws.com) are NOT blocked
  - Full IPv6 support for all blocking rules
  - Configurable features:
    - `action` modes: block (default), warn, log-only
    - `additional_blocked_ips`: Add custom IP ranges to block
    - `additional_blocked_domains`: Add custom domains to block
    - `allow_localhost`: Enable for local development (default: false)
  - Comprehensive test suite: 73 tests including 2 validated Hermes Security Framework SSRF payloads
  - Inspired by Hermes Security Framework patterns
  - Documentation: [docs/SSRF_PROTECTION.md](docs/SSRF_PROTECTION.md)

- **Unicode Attack Detection for Prompt Injection** (Issue #195, Phase 2: Hermes Security Patterns)
  - Detects Unicode-based attacks that bypass pattern matching via invisible or look-alike characters
  - **Zero-width character detection** (9 types): U+200B (zero-width space), U+200C (non-joiner), U+200D (joiner), U+FEFF (BOM), U+2060 (word joiner), and 4 more invisible characters
  - **Bidirectional override detection** (2 types): U+202E (RTL override), U+202D (LTR override) for visual deception attacks
  - **Unicode tag character detection**: Deprecated tags (U+E0000 - U+E007F) used for hidden data encoding
  - **Homoglyph detection** (80+ pairs): Cyrillic/Greek/Mathematical look-alikes (e.g., Cyrillic 'е' U+0435 vs Latin 'e' U+0065)
  - **Smart false positive prevention**:
    - Allows emoji with zero-width joiners (e.g., 👨‍👩‍👧‍👦 family emoji) when `allow_emoji: true`
    - Allows RTL languages (Arabic, Hebrew) with legitimate bidi marks when `allow_rtl_languages: true`
    - Context-aware detection using surrounding character analysis
  - **Configuration options** under `prompt_injection.unicode_detection`:
    - `enabled`: Enable/disable all Unicode detection (default: true)
    - `detect_zero_width`: Toggle zero-width character detection (default: true)
    - `detect_bidi_override`: Toggle bidi override detection (default: true)
    - `detect_tag_chars`: Toggle tag character detection (default: true)
    - `detect_homoglyphs`: Toggle homoglyph detection (default: true)
    - `allow_rtl_languages`: Allow legitimate RTL text (default: true)
    - `allow_emoji`: Allow emoji with zero-width joiners (default: true)
  - **Performance**: <5ms overhead per prompt with early exit on first detection
  - **Integration**: Works with existing action modes (block/warn/log-only)
  - **Testing**: 40 comprehensive test cases covering all attack types and false positive scenarios
  - Validates 3/3 Hermes unicode attack payloads (zero-width, bidi override, tag characters)
  - Based on Tirith CLI patterns and Hermes Security Framework
  - New `UnicodeAttackDetector` class in `src/ai_guardian/prompt_injection.py`
  - Updated JSON schema with `unicode_detection` configuration section
  - Updated `setup.py` to include `unicode_detection` in default config template (ensures `ai-guardian setup --create-config` includes new options)

- **Config File Scanner** (Issue #196, Phase 3: Hermes Security Patterns)
  - Detects credential exfiltration commands in AI configuration files that could cause persistent credential theft across ALL AI sessions
  - **The Threat**: Malicious instructions in CLAUDE.md, AGENTS.md, or .cursorrules execute in every AI session, exfiltrating credentials from all developers on the project
  - **Persistence Multiplier**: 1 malicious config file × N developers × M sessions = N×M credential thefts
  - **8 Core Exfiltration Patterns** (immutable, cannot be disabled):
    1. `curl.*\$\{?[A-Z_][A-Z0-9_]*\}?` - curl with environment variables
    2. `wget.*\$\{?[A-Z_][A-Z0-9_]*\}?` - wget with environment variables
    3. `\benv\s*\|.*\bcurl\b` - env piped to curl (credential exfiltration)
    4. `\bprintenv\b.*\|.*\bcurl\b` - printenv exfiltration
    5. `\bcat\s+(?:/etc/|~/\.ssh/|~/\.aws/).*\|.*\bcurl\b` - file exfiltration
    6. `\bbase64\b.*\|.*\bcurl\b` - base64 encoded exfiltration
    7. `\baws\s+s3\s+(?:cp|sync)\b` - AWS S3 upload command
    8. `\bgcloud\s+storage\s+cp\b` - GCP Cloud Storage upload command
  - **Standard Config Files Scanned**: CLAUDE.md, AGENTS.md, .cursorrules, .aider.conf.yml, .github/CLAUDE.md
  - **Context-Aware Detection**: Ignores documentation examples with keywords (example, warning, don't, avoid, dangerous, attack, threat, security)
  - **Configurable Options** under `config_file_scanning`:
    - `enabled`: Enable/disable config file scanning (default: true)
    - `action`: "block" (default), "warn", or "log-only"
    - `additional_files`: Add more config file patterns to scan
    - `ignore_files`: Glob patterns for files to skip (e.g., "**/examples/**", "**/docs/**")
    - `additional_patterns`: Add custom regex patterns to detect
  - **Performance**: <10ms overhead per config file scan with early exit on first match
  - **Testing**: 37 comprehensive test cases including all 3 Hermes config file payloads
  - **Integration**: Runs after prompt injection detection, before secret scanning in PreToolUse hook
  - New `ConfigFileScanner` class in `src/ai_guardian/config_scanner.py`
  - Updated JSON schema with `config_file_scanning` configuration section
  - Updated `setup.py` to include `config_file_scanning` in default config template
  - Inspired by Hermes Security Framework patterns

- **Documented `--create-config` and `--permissive` flags in README** (Issue #199)
  - Quick Start section now shows `ai-guardian setup --create-config` as the recommended way to create config files
  - Explains difference between secure mode (default) and permissive mode (`--permissive` flag)
  - Setup Command section includes `--create-config` examples in Basic Usage
  - Includes dry-run preview example (`--create-config --dry-run`)
  - Makes onboarding easier by highlighting the automated config creation introduced in v1.4.0

- **Version information in all log entries** (Issue #190)
  - Every log line now includes AI Guardian version (e.g., `v1.5.0`)
  - New log format: `YYYY-MM-DD HH:MM:SS - v{VERSION} - logger - LEVEL - message`
  - Version logged explicitly at startup with Python version and platform information
  - Helps correlate bugs with specific releases and verify fixes
  - No manual version strings needed in log statements - automatically injected via custom LogRecord factory
  - Example log output:
    ```
    2026-04-21 18:49:20 - v1.5.0 - root - INFO - AI Guardian v1.5.0 initialized
    2026-04-21 18:49:20 - v1.5.0 - root - INFO - Python 3.12.11
    2026-04-21 18:49:20 - v1.5.0 - root - INFO - Platform: Darwin-25.4.0-arm64
    ```

### Changed
- **Clarified zero-configuration installation in README** (Issue #216)
  - Quick Start section now emphasizes that ai-guardian works immediately after installing gitleaks with zero configuration required
  - Added "Default Behavior (No Configuration File)" section showing which features are enabled by default
  - Added minimal configuration example showing that only specific restrictions need to be configured
  - Reorganized Quick Start to clearly separate zero-config installation from optional advanced configuration
  - Makes it clearer that configuration is only needed for tool/skill restrictions, directory rules, custom patterns, or log-only mode
  - All core protections (secret scanning, prompt injection, SSRF, config file scanning, immutable file protection) work out-of-the-box

### Fixed
- **Setup command now generates complete configuration with violation_logging section** (Issue #214)
  - Fixed missing `violation_logging` section in `ai-guardian setup --create-config` output
  - Added `violation_logging` property to JSON schema with proper validation
  - Users can now discover and configure violation logging from generated config files
  - Includes all log types: tool_permission, directory_blocking, secret_detected, secret_redaction, prompt_injection
  - Improves discoverability of violation logging feature (available since v1.1.0)
- **Overly aggressive self-protection heuristic no longer blocks legitimate content** (Issue #188)
  - Fixed false positives where commands mentioning "ai-guardian" in content were blocked
  - Self-protection patterns are now path-specific, only blocking when targeting actual protected files:
    - Config files: `*ai-guardian.json`, `*/.config/ai-guardian/*`
    - IDE hooks: `*/.claude/settings.json`, `*/.cursor/hooks.json`
    - Package code: `*/site-packages/ai_guardian/*`, `*/ai-guardian/src/ai_guardian/*`
    - Cache files: `*/.cache/ai-guardian/*`
    - Directory markers: `*/.ai-read-deny`
  - Now allows legitimate use cases:
    - Writing code reviews mentioning "ai-guardian" (e.g., `echo "Review mentions ai-guardian" > /tmp/review.md`)
    - Creating documentation about ai-guardian (e.g., `echo "Install ai-guardian using pip" > docs/README.md`)
    - Writing bug reports containing "ai-guardian" text
  - Protection remains strong for actual config/hook files - only the heuristic is more precise
  - Added 9 new test cases to prevent regression

## [1.4.0] - 2026-04-21

### Added

- **Default config creation in setup command** (Issue #178)
  - New `--create-config` flag for `ai-guardian setup` command to create default `ai-guardian.json` config file
  - Two configuration modes:
    - Default (secure): Secret scanning and prompt injection enabled, Skills/MCP blocked by default
    - Permissive (`--permissive`): Same security features, but all tools allowed (permissions disabled)
  - `--dry-run` flag shows config preview without creating file
  - Improves onboarding experience - no manual config file copying required
  - Example usage:
    - `ai-guardian setup --create-config` - Create secure default config
    - `ai-guardian setup --create-config --permissive` - Create permissive config
    - `ai-guardian setup --create-config --dry-run` - Preview config without creating
  - Config includes:
    - Secret scanning with LeakTK patterns
    - Prompt injection detection (medium sensitivity)
    - Permission rules (Skills/MCP blocked by default in secure mode)
    - Empty directory rules (no restrictions)
    - Remote configs section for enterprise policies

- **Improved logging for skill and prompt injection violations** (Issue #168)
  - Tool permission violations now include tool-specific details in logs:
    - Skill tool: Shows skill name and args parameter (e.g., `(skill='daf-jira', args='view PROJ-12345')`)
    - Bash tool: Shows command preview (first 100 chars, e.g., `(command='rm -rf /path/to/file...')`)
    - Read/Write/Edit tools: Shows full file path (e.g., `(file_path='/etc/passwd')`)
  - Prompt injection detection now logs comprehensive details:
    - Source information (file path, tool name, or "user_prompt")
    - Confidence score (e.g., `confidence=0.90`)
    - Matched regex pattern (e.g., `pattern='ignore\s+(all\s+)?(previous|prior|above)...'`)
    - Matched text substring (e.g., `text='Ignore all previous instructions'`)
    - Full prompt context (e.g., `prompt='Please ignore all previous...'`) - up to 200 chars, sanitized
  - **Secret sanitization**: All logged tool parameters and matched text are sanitized to prevent secrets from leaking in logs
    - Redacts API keys, tokens, passwords, and other sensitive values
    - Replaces secrets with `***REDACTED***` or similar placeholders
    - Protects against credential leakage in audit logs
  - All logging modes include full details (block, warn, log-only)
  - Enables faster debugging and better audit trail for security violations

- **Documentation: Clarified configuration section differences** (Issue #150)
  - Added comparison table and FAQ explaining differences between `permissions`, `permissions_directories`, and `directory_rules`
  - Key clarification: `permissions_directories` discovers tool permissions; `directory_rules` blocks filesystem paths

- **Action levels for audit mode and gradual policy rollout** (Issues #84, #88, #159)
  - `action="warn"` - Logs violation + shows warning to user + allows execution
  - `action="log-only"` - Logs violation silently without user warning + allows execution (NEW in #159)
  - `action="block"` - Prevents execution (default)
  - Available for: tool permissions (per-rule), prompt injection (global), directory rules (global)
  - Secret scanning always blocks (no action field for security)
  - Useful for baseline metrics, impact analysis, compliance audits, and passive monitoring
  - All violations logged to Console and violation log regardless of action

- **Flexible scanner engine support** (Issues #153, #154)
  - Support for BetterLeaks (20-40% faster than Gitleaks) and LeakTK (auto-pattern management)
  - Automatic fallback to available scanners via `engines` configuration
  - Custom scanner support with configurable commands and output parsers
  - Enhanced error messages showing scanner type and pattern source
  - Includes fixes for betterleaks command template and validation flags

- **Directory rules system** (Issue #82, #172)
  - Order-based access control with last-match-wins precedence
  - Each rule has `mode: "allow"|"deny"` and `paths: [...]`
  - Supports `action: "warn"|"log-only"|"block"` for audit mode
  - Wildcard support: `**` (recursive), `*` (single-level), combined patterns including leading `**`
  - Can override .ai-read-deny markers with allow rules
  - Backward compatible: `directory_exclusions` auto-converted to allow rules
  - Consistent glob pattern matching with `ignore_files`

- **Ignore patterns for false positive handling** (Issue #84)
  - `ignore_tools`: Skip detection for specific tools (e.g., `"Skill:code-review"`, `"mcp__*"`)
  - `ignore_files`: Skip detection for specific files (e.g., `"**/.claude/skills/*/SKILL.md"`)
  - Works for both prompt injection and secret scanning

- **Pattern server test coverage** (Issue #101)
  - Added 12 comprehensive tests for `warn_on_failure` configuration
  - Pattern server module now has 57% code coverage

- **User-friendly error handling for malformed configuration**
  - Clear JSON parsing errors with file path, line number, column number
  - Fail-open with warning: continues with default configuration when config has errors

- **Enable contributor workflow** (Issue #105)
  - Contributors can now use AI assistance to edit ai-guardian source code in development repos
  - Enables standard fork + PR workflow for external contributors
  - Config/hooks/cache/pip-installed always protected; development source allowed via Edit/Write/Read

### Changed
- **Smart hook ordering in setup command**
  - `ai-guardian setup` ensures ai-guardian is first in all hooks arrays
  - Critical for log mode warning visibility (only first hook's systemMessage is displayed)
  - Preserves existing hooks after ai-guardian

### Fixed
- **Bug #183**: Hardcoded pattern blocks legitimate user scripts
  - Fixed overly broad protection pattern from `*mv*ai-guardian*` to `*mv*ai-guardian.json*`
  - Users can now organize scripts with 'ai-guardian' in filename
  - Config files remain protected

- **Bug #165**: Pattern server silently falls back to defaults when unavailable
  - **SECURITY FIX**: Operations now blocked when pattern server is configured but unavailable
  - Pattern server unavailable + cache expired → BLOCKS operation
  - Pattern server unavailable + cache valid → Uses cached patterns
  - Security impact: **High** - prevents organization-specific secrets from leaking

- **Bug #162**: Pattern server requires authentication for public URLs
  - Pattern server now makes authentication optional for public URLs
  - Only adds Authorization header when token is available
  - Better error messages distinguishing public vs private URL failures

- **Bug #155**: False positives in prompt injection detection for heredoc content
  - Heredoc content is now stripped before pattern matching
  - Prevents false positives when writing security documentation or test fixtures
  - Real injection attempts outside heredocs still detected

- **Bug #113**: Self-protection bypass when file_path parameter is missing
  - File-path tools (Edit, Write, Read, NotebookEdit) now fail-closed when file_path is missing

- **Bug #174**: Misleading warnings when Glob tool is used
  - Removed Glob from FILE_READING_TOOLS list
  - Glob uses `pattern` parameter, not `file_path`
  - Eliminates false warnings about missing file paths

## [1.3.0] - 2026-04-09

### Added

- **Tool output scanning** with PostToolUse hook for Claude Code and Cursor
  - Scans Bash command outputs before sending to AI
  - Scans Read/Grep/WebFetch results for secrets
  - Prevents secrets in tool responses from reaching AI context
  - Claude Code: Hook configured but not firing yet (awaiting IDE activation)
  - Cursor: Full support via `postToolUse` and `afterShellExecution` hooks

- **Maintainer bypass for source code editing**
  - GitHub repository maintainers can edit ai-guardian source files
  - Verified via GitHub CLI and collaborator API check
  - Status cached for 24 hours to avoid rate limits
  - Config files remain protected even for maintainers
  - Prevents cache poisoning attacks

### Changed
- **Tool policy deny patterns** now protect maintainer status cache
  - `*maintainer-status.json` pattern prevents cache manipulation
  - Blocks attempts to fake maintainer status via cache poisoning
  - Config files and hooks remain fully protected

### Fixed
- Removed `.github/ISSUE_TEMPLATE/` from self-protection deny patterns
  - Only protects actual config and source files
  - Allows editing issue templates for project maintenance

## [1.2.0] - 2026-04-02

### Added

- **Prompt injection detection** with heuristic pattern matching
  - Fast, local detection (<1ms, privacy-preserving)
  - Configurable sensitivity levels (low, medium, high)
  - Custom pattern support for organization-specific threats
  - Allowlist patterns for handling false positives
  - Detection categories: instruction override, system manipulation, exfiltration attempts
  - Optional integration points for ML detectors (Rebuff, LLM Guard)

### Changed
- **Enhanced violation logging**
  - All violations logged to rotating file (`~/.config/ai-guardian/violations.log`)
  - Structured JSON format for easy parsing and analysis
  - Includes violation type, timestamp, details, and suggested fixes
  - Perfect for compliance auditing and security monitoring

## [1.1.0] - 2026-03-15

### Added

- **MCP Server & Skill Permissions** system for granular access control
  - Pattern-based allow/deny lists for Skills and MCP servers
  - Wildcard matching support (e.g., `daf-*`, `mcp__notebooklm__*`)
  - Block dangerous command patterns (e.g., `*rm -rf*`)
  - Auto-discovery from GitHub/GitLab skill directories
  - Remote policy configuration for enterprise/team policies
  - Multi-level config: project → user → remote

- **Interactive Console** for managing configuration
  - Tab-based interface for all security features
  - One-click approval of blocked operations from violation log
  - Visual configuration management with validation
  - Prevents AI agents from modifying config (requires manual clicks)

### Changed
- **Self-protecting security architecture** with hardcoded deny patterns
  - AI cannot modify ai-guardian config files
  - AI cannot remove IDE hooks (Claude Code, Cursor)
  - AI cannot edit package source code
  - AI cannot remove directory protection markers (.ai-read-deny)
  - Unbreakable protection loop - tools blocked before execution

## [1.0.0] - 2026-03-01

### Added

- **Secret scanning** with Gitleaks integration
  - Prompt scanning before AI interaction
  - File scanning before AI reads files
  - Comprehensive pattern detection (API keys, tokens, private keys, etc.)
  - Configurable ignore patterns for false positives

- **Directory blocking** with .ai-read-deny markers
  - Recursive protection (blocks directory and all subdirectories)
  - Fast performance (file existence check only)
  - Clear error messages for protected paths

- **Multi-IDE support** with auto-detection
  - Claude Code CLI and VS Code Claude extension
  - Cursor IDE
  - GitHub Copilot
  - Aider (via git hooks)

- **Setup command** for automated IDE configuration
  - Auto-detects IDE type
  - Creates backup before modifying config
  - Preserves existing configuration
  - Interactive and non-interactive modes

[Unreleased]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.17.1...HEAD
[1.17.1]: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.17.1
[1.17.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.16.0...v1.17.0
[1.16.0]: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.16.0
[1.15.5]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.15.4...v1.15.5
[1.15.4]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.15.3...v1.15.4
[1.15.3]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.15.2...v1.15.3
[1.15.2]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.15.1...v1.15.2
[1.15.1]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.15.0...v1.15.1
[1.15.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.14.0...v1.15.0
[1.14.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.13.3...v1.14.0
[1.13.3]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.13.2...v1.13.3
[1.13.2]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.13.1...v1.13.2
[1.13.1]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.13.0...v1.13.1
[1.13.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.12.3...v1.13.0
[1.12.3]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.12.2...v1.12.3
[1.12.2]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.12.1...v1.12.2
[1.12.1]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.12.0...v1.12.1
[1.12.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.11.1...v1.12.0
[1.11.1]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.11.0...v1.11.1
[1.11.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.10.0...v1.11.0
[1.10.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.9.1...v1.10.0
[1.9.1]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.9.0...v1.9.1
[1.9.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.8.1...v1.9.0
[1.8.1]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.8.0...v1.8.1
[1.8.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.6.2...v1.7.0
[1.6.2]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.6.1...v1.6.2
[1.6.1]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.5.1...v1.6.0
[1.5.1]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.0.0
