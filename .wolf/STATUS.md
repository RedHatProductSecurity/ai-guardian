---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS — ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Update this file at the end of every work phase so the next `/clear` resumes in 1 read.
> Last updated: 2026-09-25

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

---

## 🚀 Next phase

**Goal:** Resolve the remaining CI matrix failures for PR `#2421`.

### Acceptance criteria
1. CI test matrices complete successfully or have a documented external failure.
2. Test runs do not open desktop, browser, or Textual windows.
3. MCP setup, diagnostics, and IDE detection remain regression-free.

### Files to create / edit
| Type | File | Content |
|---|---|---|
| changed | `tests/conftest.py` | Default test-only headless UI environment |
| changed | `src/ai_guardian/tray/plugins.py` | Skip native dialogs in headless mode |
| changed | `src/ai_guardian/setup/hooks.py` | File/artifact-based IDE detection and Cursor layer evidence |
| changed | `tests/unit/test_setup.py` | OpenWolf metadata and installed/protected detection contracts |
| changed | `tests/ux/test_user_experience_contract_ide_setup.py` | No false setup popup for project metadata directories |

### Closed decisions
- Use headless mode for tests rather than auto-closing windows; this prevents blocking and works without a display.
- Keep provider-specific tests explicit and mocked so they still verify backend command construction.

### Open decisions
- Decide whether registry entries for Windsurf/Gemini should remain explicitly MCP-unsupported.

---

## 📁 Active architecture

- **Stack:** Python 3.9-3.14, pytest, Textual/NiceGUI/Tkinter tray UI.
- **Key modules:** `mcp/identity.py`, `mcp/server.py`, `setup/mcp.py`, `tray/plugins.py`.
- **Patterns:** Shared MCP startup migration; fail-closed identity checks; test UI isolation through environment overrides.

---

## ⚠️ External blockers (don't block coding)

- CI run `36134638189` and compatibility run `36134638254` have matrix test failures with only `Process completed with exit code 1` annotations. Local full suite is green; raw logs contain protected Unicode/escape content and were not bypassed.
- Pi MCP remains intentionally unimplemented; issue `#2426` tracks a future managed TypeScript extension bridge.

---

## 🔧 Useful commands

```bash
uv run --extra dev python -m pytest tests/unit/test_sandbox_tray.py -q
uv run --extra dev python -m pytest tests/unit/test_mcp_identity.py tests/unit/test_mcp_server.py tests/unit/test_doctor.py -q
```

---

## 📚 References (read IF needed)

- `.wolf/cerebrum.md` — User Preferences + Do-Not-Repeat + Decision Log
- `.wolf/anatomy.md` — token-efficient file index
- `.wolf/buglog.json` — known bugs + fixes
