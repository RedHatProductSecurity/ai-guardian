---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS — ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Update this file at the end of every work phase so the next `/clear` resumes in 1 read.
> Last updated: 2026-09-26

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

## 🚀 Next phase

**Goal:** Complete issue `#2436`: make Pi tray MCP health state-aware and actionable.

### Acceptance criteria
1. [x] Pi verification reports a missing managed extension diagnostic with its repair path.
2. [x] Tray health distinguishes missing extension, SDK dependencies, identity, disabled, and healthy states.
3. [x] Setup and subsequent manual checks show the pinned SDK action and managed extension path instead of generic MCP missing.
4. [x] Fresh, dependency-pending, healthy, and tray UX regression coverage passes.
5. [x] Pi health verification remains read-only and does not launch the MCP server.

### Open decisions
- The pinned Pi SDK install remains an explicit user action; tray output now provides the command and managed extension directory.
- Commit and PR submission are deferred to `daf complete`.

---

## 📁 Active architecture

- **Stack:** Python 3.9-3.14, pytest, Textual/NiceGUI/Tkinter tray UI.
- **Key modules:** `mcp/identity.py`, `mcp/server.py`, `setup/mcp.py`, `tray/health.py`, `tray/plugins.py`.
- **Patterns:** Shared MCP startup migration; fail-closed identity checks; test UI isolation through environment overrides.

---

## ⚠️ External blockers (don't block coding)

- The latest Windows jobs in run `36140124301` stalled after 5,703 passed tests; the next remote run must verify the Windows-safe identity fix.
- Pi MCP bridge is implemented in the managed extension; npm SDK installation remains an explicit pinned setup step surfaced by tray health.

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
