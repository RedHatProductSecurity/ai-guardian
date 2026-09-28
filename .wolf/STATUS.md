---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS — ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Update this file at the end of every work phase so the next `/clear` resumes in 1 read.
> Last updated: 2026-09-27

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

## 🚀 Next phase

**Goal:** Run `daf complete` for issue `#2448` after review.

### Open decisions
- No commit or pull request was created; `daf complete` owns those actions.

---

## 📁 Active architecture

- **Stack:** Python 3.9-3.14, pytest, Textual/NiceGUI/Tkinter tray UI.
- **Key modules:** `integrations/anthropic/agent.py`, `integrations/base.py`, `integrations/compaction.py`, `tests/unit/test_compaction.py`, `tests/unit/test_integrations.py`.
- **Patterns:** Shared MCP startup migration; fail-closed identity checks; test UI isolation through environment overrides.

---

## ⚠️ External blockers (don't block coding)

- No active blockers. The remaining workflow step is review/commit of the uncommitted auto-install follow-up.

---

## 🔧 Useful commands

```bash
  uv run --extra dev python -m pytest tests/unit/test_pi_support.py tests/unit/test_setup.py tests/unit/test_proactive_prompt.py -q
  uv run --extra dev python -m pytest tests/ux/test_user_experience_contract_pi.py tests/ux/test_user_experience_contract_ide_setup.py -q
```

---

## 📚 References (read IF needed)

- `.wolf/cerebrum.md` — User Preferences + Do-Not-Repeat + Decision Log
- `.wolf/anatomy.md` — token-efficient file index
- `.wolf/buglog.json` — known bugs + fixes
