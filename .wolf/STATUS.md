---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS - ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-10-12

---

## ✅ Done

- Issue #2529: place single- and multi-daemon `Pause...` controls directly below
  **Status**, preserve global pause/resume behavior, and group directory controls
  under `Directories...`.
- Make **Check middleware readiness...** a standalone action; put
  **Apply policy to sandbox...** under the selected OpenShell target's
  **Manage sandbox** menu and lock its form to that sandbox. Regular containers
  correctly omit the OpenShell policy action.
- Update `CHANGELOG.md`, `docs/Sandbox.md`, and `docs/OPENSHELL_MIDDLEWARE.md`;
  add unit and UX coverage. The user confirmed the action appears for OpenShell
  targets.
- 541 affected unit/UX tests pass. Ruff, Black, and Pylint pass. Full Mypy still
  reports 14 existing errors in `skill_discovery.py:522` and
  `secret_validator.py:288`.
- Prior #2527 OpenShell readiness work is on the current base via PR #2530.
- Issue #2532: added AppIndicator DBusMenu open/close tracking and deferred tray
  menu refreshes while the exported menu is open. Routed tray refresh paths
  through the guard and added three regression tests; `test_daemon_tray.py`
  passes all 441 tests.
- Issue #2535: extracted the six AI Guardian-owned TypeScript bridge, extension,
  and plugin templates to `src/ai_guardian/setup/templates/`. Setup loads them
  through `importlib.resources`; rendering substitutions and output paths remain
  unchanged. Added packaged-resource and unresolved-placeholder tests.
- Verified all six resources in built sdist and wheel archives, and imported and
  rendered setup from the wheel contents. The related unit tests pass (516).
  Ruff, Black, and Pylint pass; Mypy retains the same 14 existing errors in
  `skill_discovery.py:522` and `secret_validator.py:288`.
- Issue #2538: interactive targeted setup now identifies integrations whose
  existing hooks require force, asks a default-No overwrite question, and leaves
  the setup untouched when declined or cancelled. Explicit `--force` stays
  prompt-free; non-interactive and JSON paths preserve no-overwrite behavior.
  Added setup unit and UX contract coverage; all 404 related tests pass.
  Ruff, Black, and Pylint pass; Mypy retains the same 14 existing errors.
- Issue #2534: added session-scoped pause/resume using adapter-normalized stable
  hook IDs, independent of project-directory pauses. Added socket, REST, CLI, and
  tray controls; status displays daemon-issued session keys. Session pauses are
  timed or indefinite, clear on SessionEnd, 24-hour inactivity, or daemon
  restart, and never synthesize identity for callers without stable IDs. Updated
  CLI/tray labels, docs, changelog, and UX coverage. All 1095 related unit/UX
  tests pass; Ruff, Black, and Pylint pass.
- Issue #2531: qualified Codex OAuth live on OpenShell CLI and gateway v0.1.3
  using the pinned AI Guardian 1.19.0 image and Codex 0.160.0. Creation, daemon,
  service, agent, deterministic detection, restart, reconnect, and cleanup all
  passed. Sanitized report: `/tmp/opencode/openshell-compatibility-report-2531.json`.
  Claude Code/Vertex remain unsupported pending separate credential-bound
  qualification. Fixed the report parser to read the gateway's explicit version
  field rather than interpreting its IPv4 endpoint as a version. All 14 manual
  qualification-runner unit tests pass; Ruff and Black pass for both changed
  runner/test files.

## 🚀 Next quest

- Issue #2531 implementation and Codex qualification are complete. No commit or
  push was made; use `daf complete` outside the active agent session when ready
  to close the issue. Claude Code/Vertex remain explicitly deferred.

## Context

- Working directory: `/home/itdove/development/ai/ai-guardian`
- Branch/issue: `2531` / `RedHatProductSecurity/ai-guardian#2531`.
- Local desktop: KDE Plasma 6.7.4, Qt 6.11.2, Wayland; AI Guardian tray is
  running. No crash was deliberately triggered on the live desktop.
- The OpenCode JavaScript/TypeScript CodeQL workflow is not configured; the
  unrelated `.opencode/plugins/openwolf/` middleware was not changed.
- Do not regenerate `docs/notebooklm-export.md` during development; release
  workflow refreshes it.

## Validation

```bash
uv run --extra dev python -m pytest tests/unit/test_openshell_compatibility.py tests/unit/test_openshell_middleware_tray.py tests/unit/test_openshell_middleware_probe.py tests/ux/test_user_experience_contract_sandbox_middleware.py -q  # 32 passed
cargo test --manifest-path rust/openshell-middleware/Cargo.toml  # 13 passed
python scripts/check_openshell_compatibility.py  # passed
ruff check src/ai_guardian/ tests/  # passed
black --target-version py310 --check src/ai_guardian/ tests/  # passed
pylint src/ai_guardian/ --disable=all --enable=E --disable=E1101,E0611,E2515,E2502,E0602,E0601,E1123,E1120,E0213,E0102,E0203,E1129,E0401 --output-format=text  # 10.00/10
mypy src/ai_guardian/  # 14 known errors in skill_discovery.py and secret_validator.py
uv run --extra dev python -m pytest tests/unit/test_openshell_manual.py -q  # 14 passed
ruff check container/tests/test_openshell_agents.py tests/unit/test_openshell_manual.py  # passed
black --target-version py310 --check container/tests/test_openshell_agents.py tests/unit/test_openshell_manual.py  # passed
git diff --check  # passed
```

## References

- `.wolf/cerebrum.md` - user preferences and project learnings
- `.wolf/buglog.json` - known bugs and fixes
- `AGENTS.md` - repository contribution rules
- Current GitHub issue: `https://github.com/RedHatProductSecurity/ai-guardian/issues/2531`
