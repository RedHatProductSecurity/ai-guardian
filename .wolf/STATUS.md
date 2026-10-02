---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS — ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-10-01

---

## ✅ Done

- Issue #2482 implementation is complete on branch `2482`; no commit or PR was created.
- SSRF now treats the complete `0.0.0.0/8` range as immutable in bundled and pattern-server paths.
- `SSRFProtector.check_resolved_destination()` revalidates caller-supplied fresh A/AAAA results; `check_redirect_chain()` checks every supplied absolute redirect target.
- Resolved private, reserved, metadata, loopback, link-local, IPv6-local, malformed, or empty destinations fail closed; domain allowlists cannot override immutable resolved addresses.
- The hook remains pattern-only and performs no DNS lookup or redirect; runtime-aware callers and network controls own the remaining TOCTOU boundary.
- TUI, Web Console, schema, setup profiles, example config, docs, changelog, and pattern listing now describe the policy.
- Updated the stale bundled TOML expectation from 24 to 25 SSRF rules and corrected the pattern-count documentation after PR CI exposed the regression.
- Validation passed: 808 bundled/pattern/config tests plus 334 related tests, 3 setup-template tests, and 167 final SSRF/UX tests; Ruff, Black, Pylint, Mypy, JSON validation, and diff checks.
- DAF note and GitHub issue progress comment were recorded; `daf complete` owns commit, push, PR, and issue closure actions.

## 🚀 Next quest

Run `daf complete` for issue #2482 when ready to commit and open the pull request.

Acceptance criteria are complete:

- `0.0.0.0/8` selected as the immutable unspecified IPv4 policy.
- DNS rebinding, redirect, IPv6, allowlist, malformed-result, and bind/listen regressions are covered.
- Runtime/network boundary and no-false-positive behavior are documented.

## Context

- Working directory: `/home/itdove/development/ai/ai-guardian`
- Branch: `2482`; worktree contains the issue changes plus the uncommitted bundled-rule-count correction.
- Routine local validation avoids integration/container scenarios per `AGENTS.md`; pattern-server integration assertions are included for CI.
- Do not regenerate `docs/notebooklm-export.md` during development.

## External blockers

- None. The remaining workflow step is `daf complete`.

## Useful commands

```bash
uv run --extra dev python -m pytest tests/unit/test_ssrf_protection.py tests/ux/test_ssrf_revalidation_contract.py -q
ruff check src/ai_guardian/ tests/
black --target-version py39 --check src/ai_guardian/ tests/
mypy src/ai_guardian/
```

## References

- `.wolf/cerebrum.md` — user preferences and project learnings
- `.wolf/anatomy.md` — token-efficient file index
- `.wolf/buglog.json` — known bugs and fixes
