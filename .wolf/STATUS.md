---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS - ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-10-11

---

## Current Quest: Issue #2527

- Open PR #2530 is on branch `2527`. Its current head `761ff9ed` includes the
  `pymdown-extensions==11.0.1` pin; Read the Docs now passes.
- The latest CI matrix run exposed two root causes: Windows tests cleared all
  home variables before OpenShell policy discovery, and Ubuntu 26.04/Python 3.14
  loaded incompatible system/PyPI protobuf components in the readiness probe.
- Local fixes skip the optional XDG policy root when no home is available and
  encode/decode the probe's fixed protobuf wire contract directly through gRPC.
- The five affected unit/UX files pass (127 tests). Ruff, Black, Pylint, and
  targeted Mypy pass. Full Mypy has 14 unrelated request-typing errors at
  `skill_discovery.py:522` and `secret_validator.py:288`.
- Changes remain uncommitted and unpushed. JIRA acceptance criteria are
  unavailable because `JIRA_API_TOKEN` is unset.

## Done

- Completed the tray's OpenShell readiness, native-vs-hooked sandbox, policy
  discovery/editing, and operator-owned middleware workflows with unit/UX
  coverage and documentation.
- Fixed the Read the Docs dependency regression; PR #2530's RTD check is green.

## Next Quest

- Use the DAF completion flow to publish the local CI fixes to PR #2530, then
  verify a fresh matrix run. No commit or push has been made in this session.

## Context

- Working directory: `/home/itdove/development/ai/ai-guardian`
- Current branch/issue: `2527` / `RedHatProductSecurity/ai-guardian#2527`.
- The local direct tests ran on Python 3.14.7; CI remains at the older failed
  run until the local changes are sent to the PR.
- Do not regenerate `docs/notebooklm-export.md` during development; it is
  refreshed only during the release process.

## Validation

```bash
uv run --extra dev python -m pytest tests/unit/test_openshell_middleware_probe.py tests/unit/test_openshell_middleware_tray.py tests/unit/test_openshell_policy.py tests/unit/test_sandbox_tray.py tests/ux/test_user_experience_contract_sandbox_middleware.py -q  # 127 passed
ruff check src/ai_guardian/ tests/  # passed
black --target-version py310 --check src/ai_guardian/ tests/  # passed
pylint src/ai_guardian/ --disable=all --enable=E --disable=E1101,E0611,E2515,E2502,E0602,E0601,E1123,E1120,E0213,E0102,E0203,E1129,E0401 --output-format=text  # 10.00/10
mypy --follow-imports=silent src/ai_guardian/openshell_policy.py src/ai_guardian/tray/openshell_middleware_probe.py src/ai_guardian/tray/openshell_middleware.py  # passed
git diff --check
```

## References

- `.wolf/cerebrum.md` - user preferences and project learnings
- `.wolf/buglog.json` - known bugs and fixes
- `AGENTS.md` - repository contribution rules
- Current GitHub issue: `https://github.com/RedHatProductSecurity/ai-guardian/issues/2527`
