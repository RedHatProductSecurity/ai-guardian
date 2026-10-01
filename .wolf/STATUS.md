---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS — ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Update this file at the end of every work phase so the next `/clear` resumes in 1 read.
> Last updated: 2026-10-01

---

## ✅ Done

<!-- Move items here from "🚀 Next phase" when finished. Group by area. -->

- MCP identity migration and nonce attestation are implemented for all 13 local MCP integrations.
- Read-only MCP health diagnostics are integrated into setup verification and doctor output.
- Native tray dialogs honor `AI_GUARDIAN_PREFERRED_UI=headless`.
- Pytest defaults disable Tkinter, NiceGUI, and visible UI; provider-specific tests opt into mocked `auto` behavior.
- Popup-related tests: 573 passed. MCP/doctor/UX tests: 287 passed. Setup MCP tests: 41 passed.
- IDE detection now requires IDE-specific config files or installation artifacts; OpenWolf's `.cursor/rules/` is ignored.
- Installed IDE detection is separate from AI Guardian protection verification; unprotected configs remain discoverable for setup.
- Follow-up commit `d282bb87` is pushed to branch `2416` / PR `#2421`.
- Full local suite: 12,422 passed, 4 skipped; Mypy, Pylint, Ruff, and Black passed.
- Windows CI interruption diagnosed: MCP identity liveness used `os.kill(pid, 0)` after `test_genuine_process_passes_nonce_attestation`; all three Windows jobs stalled at the same point.
- Reused `ai_guardian.daemon.is_pid_alive()` for Windows-safe `OpenProcess` checking and added regression coverage. Affected tests and all required linters pass.
- Pi MCP bridge (#2426) is implemented on branch `2426`: managed global/project TypeScript extension, pinned SDK diagnostics, legacy migration, executable pinning, signed identity registration, nonce-attested canonical server launch, and fail-closed tool registration.
- Pi validation: targeted setup/identity/TypeScript/UX/E2E tests pass; real Node runtime handshake/tool call and tampered-identity fail-closed smoke checks pass; Ruff, Black, Pylint, and Mypy pass.

---

## ✅ Issue #2436 Complete

- Pi tray MCP health is state-aware and actionable for missing extensions, SDK dependencies, identity, disabled, stale, executable, and invalid states.
- Commit `b62884bc` is pushed on branch `2436`; PR `#2438` is open.
- Local validation passed: 430 affected tests; Black, Ruff, Pylint, and Mypy passed.
- Initial CI run `36276801561` canceled Python 3.9 and 3.12 during full-suite pytest timeout handling; rerunning the failed jobs passed both, and all PR checks are green.
- Pi setup now attempts automatic pinned SDK installation when npm is available and leaves an actionable retry diagnostic when it is not; 451 related tests pass with all required static checks.

---

## ✅ Issue #2440 Complete

- Verified AI Guardian MCP tools now pass after live identity attestation without ordinary host MCP permission rules blocking them.
- Added a Pi bridge UX regression using the generated `tool_call` payload shape and a deny-all MCP policy.
- Updated MCP security documentation and the unreleased changelog.
- Focused validation: 180 tests passed; Black, Ruff, Pylint, and Mypy passed.
- CI rerun passed across the compatibility matrix and multi-architecture container job; the first Ubuntu 26.04/Python 3.14 cancellation was transient. CodeRabbit review remains pending.

## ✅ Issue #2429 Complete

- Dummy-agent scenarios now cover structured MCP `tools/call` results for standard, strict, minimal, and moderator profiles.
- Scenario schema and runner preserve structured MCP output; PostToolUse serializes MCP results for secret scanning and redaction.
- Focused unit and MCP UX contract tests pass: 57 passed, 1 skipped; related hook tests pass: 176 passed, 1 skipped.
- Scenario schema validation, Black, Ruff, Pylint, and Mypy pass.
- No commit or pull request was created; `daf complete` owns those actions.

## 🚧 Issue #2441 In Progress

- Protected global developer-session configuration and immutable CLI enforcement are implemented.
- Added TUI and Web Console **Configuration & CLI Protection** sections with a global-only Developer Session CLI Access control.
- Project scope displays the global value but cannot edit it; Web saves explicitly target the global config.
- UI/config validation: 111 UI/config tests and 595 self-protection tests pass; Black, Ruff, Pylint, and Mypy pass.
- UI changes are uncommitted; no commit or pull request was created.

## 🚧 Issue #2432 In Progress

- Evaluated provider-native compaction: Anthropic on-demand compaction is usable through the Messages beta API; OpenAI compaction is Responses-API-only while this SDK uses Chat Completions; Gemini and OpenAI-compatible routes retain local compaction.
- Implemented Anthropic native compaction with beta header `compact-2026-09-04`, signed block preservation, configured turn retention, summary scanning, Bedrock exclusion, and deterministic fallback.
- Added strategy hooks, `CompactionResult.summary_text`, lifecycle/security regression tests, SDK documentation, and the Unreleased changelog entry.
- Directly affected tests pass: `tests/unit/test_compaction.py` (55) and `tests/unit/test_integrations.py` (501). Ruff, Black, Pylint, and Mypy pass.
- Changes are uncommitted; no commit or pull request was created.

## ✅ Issue #2448 Complete

- Added a prominent red warning to the Web Console Effective Configuration page
  when the Project selector is `Global only`.
- The warning explains that project-local overrides are excluded and directs
  users to select a project for merged effective configuration.
- The warning is hidden for project scope; page help text and `docs/CONSOLE.md`
  document the selector behavior.
- Added global-only and project-selected scope notice tests.
- Directly affected tests: 125 passed. Black, Ruff, Pylint, Mypy, compileall,
  and annotation checks passed.
- Changes are uncommitted; `daf complete` owns commit and pull request actions.

## Issue #2447 Complete

- Added actionable resolution guidance for every enum-backed violation type and explicit behavior for transcript and annotation audit filters.
- Canary findings are investigation-only and no longer expose suppression or file-ignore actions in the TUI or Web Console.
- Both console list cards now point users to Details for resolution guidance; tool-permission guidance remains shared across both Details views.
- Focused validation: 234 affected tests and 152 violation/MCP regression tests passed; Ruff, Black, Pylint, and Mypy passed.
- Changes are uncommitted; `daf complete` owns commit and pull request actions.

## 🚧 Issue #2444 In Progress

- Agent-originated host CLI self-protection is implemented across supported CLI-capable integrations.
- Added the global-only `self_protection.block_host_agent_cli` setting, secure defaults, profile/schema/example coverage, TUI/Web controls, and global-only scope validation.
- Host CLI detection is adapter-aware and command-position-aware; the existing AI Guardian CLI guard remains independent.
- Focused validation: 1,229 tests passed; Black, Ruff, Pylint, Mypy, JSON validation, and `git diff --check` passed.
- Changes are uncommitted; `daf complete` owns commit and pull request actions.

## ✅ Issue #2457 Complete

- Immutable violations now carry explicit `is_immutable` metadata through direct
  policy, SSRF, config-exfiltration, directory-rule, and scan-pipeline paths.
- TUI and Web Console details show the enforced-protection notice and hide
  resolution snippets, suggested allow rules, Always Allow, source suppression,
  and ignore-file actions only for explicitly immutable records.
- Configurable and legacy records retain their existing remediation behavior.
- Added unit and UX regression coverage for propagation, logging, scanners,
  directory rules, TUI, Web Console, and MCP identity protection.
- Focused tests pass; Ruff, Black, Pylint, Mypy, and `git diff --check` pass.
- Changes are uncommitted; `daf complete` owns commit and pull request actions.

## ✅ Issue #2446 Complete

- Added Grok Build host hooks, camelCase normalization, native PreToolUse deny
  responses, user/project setup, TOML MCP registration, config protection, and
  supply-chain path coverage.
- Added normal Docker/Podman support with pinned `@xai-official/grok` version
  `1.0.41`; OpenShell remains explicitly unsupported with a runtime-specific
  entrypoint boundary.
- Updated installers, release-readiness matrices, container/runtime docs,
  support matrices, and the Unreleased changelog.
- Follow-up audit confirmed Grok host CLI and configuration protection, fixed
  policy precedence for adapter-normalized tool fields, and added explicit
  Grok direct/wrapper/config/UX regression coverage plus the onboarding gate.
- Diagnosed the Ubuntu 26.04 compatibility failure as runner disk quota
  exhaustion while exporting the OpenShell OCI tarball; the workflow now
  removes the unused normal OCI artifact before that export. YAML parsing and
  `git diff --check` pass.
- Validation passed: 814 focused unit/installer tests, 238 container/sandbox
  tests, 24 Grok/E2E tests, 314 focused protection/Grok tests, 103 related
  policy/hook tests, plus Ruff, Black, Pylint, Mypy, YAML parsing,
  `git diff --check`, and annotation checks.
- Changes are uncommitted; `daf complete` owns commit and pull request actions.

## ✅ Issue #2425 Complete

- OpenCode native lowercase tool names and camelCase file arguments are canonicalized before shared immutable policy checks.
- Protected global and project AI Guardian configuration reads and mutations are denied; safe OpenCode file reads remain allowed.
- Added unit and UX contract regression coverage, plus OpenCode E2E validation.
- Focused validation: 638 tests passed; Black, Ruff, Pylint, Mypy, annotation checks, and `git diff --check` passed.
- Changes are uncommitted; `daf complete` owns commit and pull request actions.

## 🚧 Issue #2461 In Progress

- Shared format-aware host CLI config loading now reports malformed JSON, JSONC,
  TOML, and YAML plus root/hook/MCP container schema errors.
- Setup, doctor, and tray verification surface diagnostics; setup refuses to
  rewrite existing invalid host files. Coverage includes OpenCode, Codex,
  Claude, Cursor, Copilot, Gemini, Antigravity, and other shared hook/MCP paths.
- Documentation and the Unreleased changelog were updated.
- Focused setup/doctor/MCP/UX validation: 543 tests passed; Black, Ruff,
  Pylint, Mypy, compileall, and `git diff --check` passed.
- Changes are uncommitted; no commit or pull request was created.

## 🚧 Issue #266 In Progress

- Added opt-in root `audit_logging` configuration and a separate sanitized
  `audit.jsonl` trail for final hook decisions, preserving legacy violation and
  scan-audit logging.
- Added masking, canonical `PolicyDecision` records, SOC 2/GDPR/HIPAA markers,
  retention/max-entry cleanup, JSON/CSV export, schema/profile/example/setup
  coverage, and documentation.
- Integrated audit logging after final hook response normalization and added
  dedicated TUI/Web Console settings, navigation, and route coverage.
- Focused validation: 295 tests passed; Ruff, Black, Pylint, Mypy, and
  `git diff --check` passed. Three existing hook-test deprecation warnings
  remain.
- Fixed the CI regression where `test_tui_global_settings.py` still expected
  15 global settings features after adding `audit_logging`; the affected UI
  and dashboard tests now pass (198 passed).
- Added all six `include_context` controls to the TUI and Web Console, with
  nested-config persistence and safe default handling.
- Added TUI **Export Now** and Web Console **Export audit trail** actions for
  JSON/CSV output without modifying `audit.jsonl`; Web export is disabled for
  remote daemons rather than exporting the Web Console host's local trail.
- Expanded `docs/AUDIT_LOGGING.md` with console navigation, controls, export
  behavior, data-field semantics, and the distinction from legacy
  `secret_scanning.audit_logging`.
- Added console regression coverage; 235 focused tests pass, and Ruff, Black,
  Pylint, Mypy, and `git diff --check` pass.
- Changes are uncommitted; `daf complete` owns commit and pull request actions.

## ✅ Issue #2464 Complete

- Identified `credentials-in-git-url` as producer of false positives caused by
  CR/LF-crossing negated character classes.
- Restricted credential URL components to one physical line and added exact
  cross-line, ordinary HTTPS, and SSH-style regression cases.
- Directly related validation passed: 238 bundled TOML tests and 154 adjacent
  secret validator/parser/redaction tests.
- Changes are uncommitted; `daf complete` owns commit and pull request actions.

## ✅ Issue #2467 Complete

- OpenCode usage is extracted from SQLite `message.data.tokens` records and
  mapped to input, output, cache-read, and cache-creation totals.
- OpenCode session-end hooks now carry the session ID through normalization and
  trace finalization; unavailable usage is persisted explicitly.
- Web and TUI trace viewers no longer present unavailable usage as zero totals.
- Focused validation: 469 tests passed; Ruff, Black, Pylint, Mypy, and
  `git diff --check` passed.
- Changes are uncommitted; `daf complete` owns commit and pull request actions.

## ✅ Issue #2471 Complete

- MCP `check_command` now evaluates the caller's project configuration through
  an explicit `project_dir`, `AI_GUARDIAN_PROJECT_DIR`, or documented launch-
  directory fallback, and captures the trusted developer-session state at
  server startup.
- Added safe, stable command-check categories for command policy, ordinary
  permission, identity, and policy-check failures; verified MCP identity still
  fails closed and remains automatically allowed when attested.
- The managed Pi MCP bridge now forwards its active `ctx.cwd` to the MCP
  server; native clients can pass `project_dir` when they have workspace
  context.
- Added benign `gh` URL/heredoc, project-policy parity, identity, UX, and Pi
  bridge regressions; updated MCP documentation, skill references, and the
  Unreleased changelog.
- Validation: 206 MCP/policy/UX/Pi tests passed, 98 shared-policy/hook tests
  passed, and Ruff, Black, Pylint, Mypy, annotation checks, and diff checks
  passed.
- Changes are uncommitted; no commit or pull request was created.

## ✅ Review Findings Addressed — 2026-09-30

- Fixed both self-protection gaps: transfer-tool mutations (`curl`, `wget`,
  `scp`, `rsync`) and Python `-c` AI Guardian CLI launches now block with
  positive/negative regression coverage.
- Fixed Anthropic native compaction ordering; only the provider-summarized
  block plus untouched recent tail is retained, including repeated compaction.
- Hardened compliance audit logging with OS-level process locking, 0700/0600
  permissions, and atomic rotation replacement.
- Fixed default Claude MCP cleanup (`~/.claude.json`) while preserving relocated
  `CLAUDE_CONFIG_DIR` behavior.
- Doctor now validates configured scanner names and recognizes the built-in
  `toml-patterns` engine, documented `custom`/`python` forms, and runtime
  default engines; CI mypy now includes `src/ai_guardian_hook_runtime.py`.
- Python inline CLI detection also covers path-qualified executables, and the
  audit permission-bit regression test skips on Windows.
- Focused validation: 1,073 tests passed, 1 skipped; Ruff, Black, Pylint,
  Mypy, and `git diff --check` passed.
- Changes remain uncommitted; no commit or pull request was created.

## ✅ CI Failure Follow-up — 2026-10-01

- PR 2476 release-readiness metadata showed two failures in run
  `36826458235`: the OpenShell Pi smoke step and the collapsed IDE E2E matrix.
- Fixed `.github/workflows/release-readiness.yml` by aligning the five
  misindented IDE entries and removing the impossible direct `claude --version`
  assertion from the OpenShell image check; Claude is intentionally runtime
  ToS-gated in `container/Dockerfile.openshell`.
- The follow-up run passed the image checks but exposed a stale compatibility
  assertion; updated the expected OpenShell base-image digest to match the
  Dockerfile's pinned `nvcr.io/nvidia/base/ubuntu` image.
- The next run still failed that assertion because `BASE_IMAGE` was not
  redeclared after the final `FROM`; redeclared it so the `LABEL` expansion
  carries the pinned value into the image.
- Added regression assertions in `tests/unit/test_ide_registry.py` and
  `tests/unit/test_container_scripts.py`, including Dockerfile ARG scope.
- Validation: all five affected IDE E2E cases passed individually, 121 workflow
  and container contract tests passed, YAML parsing passed, Ruff/Black and
  `git diff --check` passed. Docker image execution was not available locally.
- The separate Python 3.9 compatibility failure did not reproduce: the exact
  full-suite command passed locally under CPython 3.9 with 12,158 passed and
  198 skipped. Python 3.9 remains required for the 1.19 line; remove it from
  compatibility matrices only as part of the planned 1.20 support drop.
- A later Tests workflow run cancelled the Python 3.9 coverage step after
  20:51 while all other matrix jobs passed; the exact CI command passed locally
  with coverage in 7:31, so no test-suite change was made.

## ✅ Issue #2472 Complete

- MCP `check_path`, `check_command`, and `check_mcp_trust` now observe persisted global, directory-scoped, and timed daemon pauses without an MCP restart.
- Paused responses explicitly identify skipped action-gating checks while query/diagnostic tools remain available and hooks continue enforcing security.
- Added the `paused` proactive level across schema, generated profiles, example/setup config, TUI, Web Console, tray, MCP skill, documentation, and changelog.
- Focused validation: 1,046 tests passed; Ruff, Black, Pylint, Mypy, annotation checks, and diff checks passed.
- Addressed PR #2480 review findings: paused responses no longer expose an authorizing `policy_decision`, and `get_config(project_dir=...)` now reports directory-scoped pause state consistently.
- Review-fix validation: 363 directly affected tests passed; Ruff, Black, Mypy, annotation checks, and `git diff --check` passed.
- Changes are uncommitted; `daf complete` owns commit and pull request actions.

## 🚀 Next phase

**Goal:** Run `daf complete` for issue #2472 when ready to commit and open the pull request.

### Open decisions
- No commit or PR action has been requested in this session.

---

## 📁 Active architecture

- **Stack:** Python 3.9-3.14, pytest, Textual/NiceGUI/Tkinter tray UI.
- **Key modules:** `mcp/server.py`, `tools/policy.py`, `setup/hooks.py`, `setup/mcp.py`, `ide_registry.py`, `container/entrypoint.sh`, `tests/unit/test_mcp_server.py`, `tests/ux/test_user_experience_contract_mcp_command.py`.
- **Patterns:** Shared MCP startup migration; fail-closed identity checks; test UI isolation through environment overrides.

---

## ⚠️ External blockers (don't block coding)

- No active blockers. The remaining workflow step is `daf complete` for the uncommitted #2472 implementation.

---

## 🔧 Useful commands

```bash
  uv run --extra dev python -m pytest tests/unit/test_grok_support.py tests/unit/test_ide_registry.py tests/unit/test_container_scripts.py -q
  uv run --extra dev python -m pytest tests/integration/test_ide_hooks_e2e.py -q
```

---

## 📚 References (read IF needed)

- `.wolf/cerebrum.md` — User Preferences + Do-Not-Repeat + Decision Log
- `.wolf/anatomy.md` — token-efficient file index
- `.wolf/buglog.json` — known bugs + fixes
