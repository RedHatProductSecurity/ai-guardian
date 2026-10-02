---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS — ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-10-02

---

## ✅ Done

- Issue #2419 decision is implemented on branch `2419`; PR #2487 is open.
- Release `1.20.0` now requires Python >=3.10. Release `1.19.0` in the `1.19.x` line is documented as the last stable Python 3.9-compatible release.
- Updated package metadata/dependencies, both installers, doctor messaging, tray compatibility branches, CI/release matrices, Ubuntu 26 migration coverage, docs, changelog, and release skill references.
- Retained the TUI as the fallback when the web console cannot start; removed obsolete Python 3.9 version gates and test skips.
- Added release-readiness metadata verification and regression coverage for the minimum version, installer checks, doctor failure behavior, dependency markers, and CI matrices.
- Diagnosed PR #2487's Install/Uninstall Lifecycle failure: pip 25 parsed Linux kernel release `6.17.0-1022-azure` as a PEP 440 version while resolving ONNX Runtime markers.
- Replaced numeric `platform_release` comparisons with safe string gates, added regression coverage, and changed the smoke lifecycle to build/install the checked-out wheel instead of stale PyPI metadata.
- DAF note and GitHub issue progress comment were recorded; `daf complete` owns commit, push, PR, and issue closure actions.

## 🚀 Next quest

Review and commit the uncommitted CI remediation, then push it to PR #2487 and rerun the failed workflow.

Acceptance criteria are complete: the breaking-change policy, last compatible release,
upgrade guidance, runtime metadata, installer/doctor/docs updates, CI matrices,
compatibility audit, and clean-install/upgrade checks are all documented or covered.

## Context

- Working directory: `/home/itdove/development/ai/ai-guardian`
- Branch: `2419`; worktree contains the uncommitted CI remediation in `pyproject.toml`,
  `.github/workflows/smoke-tests.yml`, `CHANGELOG.md`, and two regression test files.
- Pull request: https://github.com/RedHatProductSecurity/ai-guardian/pull/2487
- Routine local validation avoids integration/container scenarios per `AGENTS.md`; pattern-server integration assertions are included for CI.
- Do not regenerate `docs/notebooklm-export.md` during development.

## External blockers

- None. The fix is validated locally; commit/push and the GitHub rerun remain.

## Useful commands

```bash
uv run --extra dev python -m pytest tests/unit/test_doctor.py tests/unit/test_setup.py tests/test_install_script.py -q
uv run --extra dev python -m pytest tests/unit/test_workflow_runner_policy.py -q
ruff check src/ai_guardian/ tests/
black --target-version py310 --check src/ai_guardian/ tests/
mypy src/ai_guardian/
```

## References

- `.wolf/cerebrum.md` — user preferences and project learnings
- `.wolf/anatomy.md` — token-efficient file index
- `.wolf/buglog.json` — known bugs and fixes
