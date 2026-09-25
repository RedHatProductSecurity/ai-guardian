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
- Windows CI interruption diagnosed: MCP identity liveness used `os.kill(pid, 0)` after `test_genuine_process_passes_nonce_attestation`; all three Windows jobs stalled at the same point.
- Reused `ai_guardian.daemon.is_pid_alive()` for Windows-safe `OpenProcess` checking and added regression coverage. Affected tests and all required linters pass.

---

## 🚀 Next phase

**Goal:** Run `daf complete` to commit and submit issue `#2423` from branch `2423`.

### Acceptance criteria
1. [x] First-time container creation uses generated configuration when no snapshot exists.
2. [x] CLI rejects a missing saved snapshot before invoking the runtime.
3. [x] Tray validates the same snapshot before preparation/runtime work.
4. [x] Regression tests cover the CLI and tray paths.

### Files changed
| Type | File | Content |
|---|---|---|
| changed | `src/ai_guardian/tray/menu_builder.py` | Preflight selected snapshots before tray sandbox creation |
| changed | `tests/unit/test_sandbox_command.py` | CLI missing-snapshot and generated-config regressions |
| changed | `tests/unit/test_sandbox_tray.py` | Tray missing-snapshot regression and valid snapshot setup |

### Closed decisions
- Reuse `_load_snapshot_config()` for tray validation so CLI and tray share the same runtime-scoped snapshot rules and error text.
- Keep the CLI validation as a race-safe backstop after tray preflight.

### Open decisions
- No implementation decisions remain; commits and PR creation are deferred to `daf complete`.

---

## 📁 Active architecture

- **Stack:** Python 3.9-3.14, pytest, Textual/NiceGUI/Tkinter tray UI.
- **Key modules:** `mcp/identity.py`, `mcp/server.py`, `setup/mcp.py`, `tray/plugins.py`.
- **Patterns:** Shared MCP startup migration; fail-closed identity checks; test UI isolation through environment overrides.

---

## ⚠️ External blockers (don't block coding)

- The latest Windows jobs in run `36140124301` stalled after 5,703 passed tests; the next remote run must verify the Windows-safe identity fix.
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
