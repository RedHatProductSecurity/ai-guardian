---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS - ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-10-02

---

## Done

- Issue #2419 Python 3.10+ policy and its release-readiness work are complete on the existing development history.
- Issue #2401 now enables strict Mypy soundness checks with documented module-level exceptions for legacy dynamic `ui`, `web`, and `tray` callback bodies.
- Added explicit types and safe narrowing across hook processing, scanners, daemon services, sessions, CLI, and UI boundaries; strict Mypy passes across 299 source files.
- Added the Mypy policy regression test, developer documentation, and changelog entry.
- Focused setup and installer tests pass, along with the complete directly affected regression set covering hooks, daemons, scanners, sessions, and tray code.
- Ruff, Black, Pylint error checks, Mypy, and `git diff --check` pass.
- Created follow-up issue #2491 to promote the Ubuntu 26.04 compatibility path to
  the standard Linux runner, and linked it from closed issue #2341.
- Issue #2491 now migrates all intended GitHub Actions Linux jobs to `ubuntu-26.04`,
  updates runner-policy contracts and current docs, and replaces the temporary
  compatibility workflow with a reusable container-build validation gate.
- Ubuntu 26.04 availability is confirmed by the upstream runner-images notice and
  the existing compatibility run `37063774654` passed on this branch.

## Next Quest

- Run the migrated hosted workflows after DAF completion and link successful runs
  before closing issue #2491.
- Update issue #2491 acceptance criteria and progress after hosted validation.

## Context

- Working directory: `/home/itdove/development/ai/ai-guardian`
- Branch: `2401`
- HEAD: `9b9429e6`
- Worktree contains the uncommitted issue #2491 workflow, documentation, contract,
  and handoff changes on branch `2401`; commits and PR creation remain delegated to
  `daf complete`.
- NiceGUI is a core dependency; `uv.lock` is ignored by this repository and was regenerated locally.
- Do not regenerate `docs/notebooklm-export.md` during development.

## Validation

```bash
uv run --extra dev python -m pytest tests/unit/test_setup.py tests/test_install_script.py -q
uv run --extra dev python -m pytest tests/unit/test_hook_processing.py tests/unit/test_daemon_discovery.py tests/unit/test_daemon_tray.py -q
ruff check src/ai_guardian/ tests/
black --target-version py310 --check src/ai_guardian/ tests/
uv run --extra dev mypy src/ai_guardian/ src/ai_guardian_hook_runtime.py
uv run --extra dev python -m pytest tests/unit/test_workflow_runner_policy.py -q
uv run --extra dev python -c 'from pathlib import Path; import yaml; [yaml.safe_load(path.read_text(encoding="utf-8")) for path in sorted(Path(".github/workflows").glob("*.yml"))]'
```

## References

- `.wolf/cerebrum.md` - user preferences and project learnings
- `.wolf/buglog.json` - known bugs and fixes
- `AGENTS.md` - repository contribution rules
- GitHub follow-up: `https://github.com/RedHatProductSecurity/ai-guardian/issues/2491`
