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
- Issue #2424 migrated the supported interactive UI from Textual/TUI to the NiceGUI Web Console.
- Shared dialog, tray, clipboard, selector, and hook-simulator helpers now live under `src/ai_guardian/ui/`.
- The `src/ai_guardian/tui/` package, Textual dependency, TUI plugin template, and TUI-only tests were removed.
- The `tui` CLI command remains as a browser-console compatibility alias; persisted `textual` dialog settings migrate to `nicegui`.
- Installers, schema, example config, doctor output, current documentation, developer guidance, and scanner checklist were updated.
- Compile checks, packaging, affected tests, schema/setup tests, ruff, Black, pylint, mypy, and diff checks pass.
- The wheel build succeeded and contains `ui/` and `web/` packages without `tui/` or Textual artifacts.

## Next Quest

- Review the complete diff for final scope and user-owned changes.
- If approved, commit and push through the DAF workflow; no commit or PR has been created in this session.

## Context

- Working directory: `/home/itdove/development/ai/ai-guardian`
- Branch: `2424`
- HEAD: `d710aa8a`
- Worktree is intentionally dirty with the issue #2424 changes.
- NiceGUI is a core dependency; `uv.lock` is ignored by this repository and was regenerated locally.
- Do not regenerate `docs/notebooklm-export.md` during development.

## Validation

```bash
uv run --extra dev python -m pytest tests/unit/test_cli_console.py -q
uv run --extra dev python -m pytest tests/unit/test_setup.py tests/unit/test_json_schema.py tests/unit/test_config_validation.py -q
ruff check src/ai_guardian/ tests/
black --target-version py310 --check src/ai_guardian/ tests/
mypy src/ai_guardian/
```

## References

- `.wolf/cerebrum.md` - user preferences and project learnings
- `.wolf/buglog.json` - known bugs and fixes
- `AGENTS.md` - repository contribution rules
