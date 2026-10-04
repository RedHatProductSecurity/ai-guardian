---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS - ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-10-03

---

## Done

- Issue #2470 now supports OpenCode V1 and V2 from the single `opencode` setup
  integration, selecting the plugin contract from the installed CLI version and
  preserving an existing V2 artifact when detection is unavailable.
- Added the V2 `Plugin.define` template with prompt, tool before/after, session
  lifecycle, blocking, and output-redaction behavior; V2 uses `plugins` while
  V1 retains `plugin`.
- Added V2 database discovery through `OPENCODE_DB` and
  `opencode debug paths db`, with legacy V1 fallback and session-viewer support.
- Added isolated V2 CLI/plugin packaging, policy paths, release-readiness checks,
  version monitoring, documentation, and changelog coverage.
- The ignored local `.opencode/package.json` and lockfile now pin both
  `@opencode-ai/plugin` 1.18.32 and `@opencode/plugin` 2.0.22.
- Completed the required CLI/runtime and IDE integration checklist audit. Added
  the versioned OpenCode support record and aligned README, Sandbox,
  container, capability, docs-index, and smoke-test documentation.
- Focused regressions pass: 608 related unit/UX tests, 3 isolated OpenCode V1/V2
  setup E2E tests, and 194 sandbox/container/manual tests. Ruff, Black, Pylint
  error checks, Mypy, YAML parsing, and `git diff --check` pass. Generated V2
  TypeScript type-checks against the published `@opencode/plugin@2.0.22`
  declarations.
- OpenShell `0.1.2` is installed, its gateway is active/authenticated, and
  Podman `5.8.4` is present; local normal and OpenShell images were built from
  the checked-out wheel as
  `localhost/ai-guardian:dev` and `localhost/ai-guardian-openshell:dev`.
  Their embedded smoke commands report AI Guardian `1.20.0-dev`, OpenCode
  `1.18.34`, and Codex `0.154.0`. Host OpenCode CLI execution is blocked by
  self-protection. The version monitor reports V2 pins current and OpenShell
  V1 `1.18.31` behind `1.18.34`.
- Rootless Podman host-config staging now uses `--userns=keep-id`; the real
  `0600` host config was successfully staged by the normal image without
  changing host permissions. Existing containers created before this change
  must be recreated.
- The active OpenShell gateway now exposes both the `codex` and `openai`
  profiles. The current agent shell has no `OPENAI_API_KEY`, but the tray/launcher
  environment successfully created the separate `ai-guardian-openai` provider.
- Automatic Codex API-key setup now selects the `openai` profile and the
  separate `ai-guardian-openai` provider, preserving `ai-guardian-codex` for
  OAuth credentials. Focused sandbox command tests (75) and container/tray
  tests (142) pass.
- OpenShell provisioning now succeeds with the rebuilt image after replacing
  the base `ubuntu` identity with a dedicated no-supplementary-groups
  `sandbox` account. `ag-codex` is `Ready`; in-sandbox checks report
  `uid=1001(sandbox)`, Codex `0.154.0`, and AI Guardian `1.20.0-dev`.
- The provider-backed credential path is live: an OpenAI `/v1/models` request
  returned HTTP 200 from `ag-codex`, and a real Codex request reached OpenAI but
  stopped with `You have no credits remaining`. The remaining API limitation is
  account billing/quota, not key authentication or OpenShell provisioning.
- The host's apparently working Codex session is not using that API key: host
  Codex `0.157.0` reports `auth_mode=chatgpt` with OAuth tokens, while the
  OpenShell image uses Codex `0.154.0` with the API-key provider.
- OpenCode runtime selection was validated without AI Guardian-specific
  environment variables: the active shell `opencode` executable reports V1
  `1.18.34`, while placing the installed V2 executable first on `PATH` reports
  V2 `2.0.22`. Setup and standalone CLI doctor use their own process context;
  daemon-backed Console health now uses the daemon process context.
- The live daemon and tray currently have the V2 runtime context and the daemon
  health endpoint reports `CLI: opencode 2.0.22 (v2)`. A previously reused Web
  Console process retained the V1 context, which is now prevented from changing
  daemon-backed health results.
- Doctor now probes installed CLI-capable integrations for their executable
  version, adds structured `cli` metadata, and shows the same version in CLI,
  JSON, and Console health output. OpenCode includes its detected V1/V2
  generation without changing hook health status.
- PR #2495 is open and ready for review. Build, lint, smoke, container, and
  integration checks passed; the latest Python/Windows matrix state was queued
  or in progress at the last check, while the affected local tests pass.

## Next Quest

- Review the uncommitted doctor CLI-version and daemon-backed Console health
  changes, then commit/push them if they are approved for PR #2495.
- Monitor PR #2495's fresh CI run and investigate any remaining Python/Windows
  matrix failures before merge.
- Either add/check credits for the OpenAI organization and rerun the API-key
  smoke request, or deliberately provision the sandbox with the working Codex
  OAuth provider. No source workaround should be added for the quota error.
- Exercise the ready `ag-codex` sandbox through the tray and complete the
  remaining lifecycle smoke evidence.

## Context

- Working directory: `/home/itdove/development/ai/ai-guardian`
- Branch: `2470`
- HEAD: `76b01e7a`
- The issue #2470 implementation, tests, documentation, workflow, container,
  and policy changes are committed and pushed to `origin/2470`; PR #2495 is
  open. The working tree contains uncommitted doctor CLI-version reporting,
  regression tests, daemon routing, changelog, troubleshooting documentation,
  and buglog updates.
- NiceGUI is a core dependency; `uv.lock` is ignored by this repository and was regenerated locally.
- Do not regenerate `docs/notebooklm-export.md` during development.

## Validation

```bash
uv run --extra dev python -m pytest tests/unit/test_opencode_support.py tests/unit/test_doctor.py tests/unit/test_daemon_multi_client.py tests/unit/test_metrics.py -q
AI_GUARDIAN_TEST_IDE=opencode uv run --extra dev python -m pytest tests/integration/test_ide_hooks_e2e.py -q
uv run --extra dev python -m pytest tests/ux/test_user_experience_contract_ide_setup.py -q
uv run --extra dev python -m pytest tests/unit/test_container_manual.py tests/unit/test_openshell_manual.py tests/unit/test_sandbox_command.py tests/unit/test_sandbox_tray.py tests/unit/test_cli_ide_setup.py -q
ruff check src/ai_guardian/ tests/
black --target-version py310 --check src/ai_guardian/ tests/
mypy src/ai_guardian/
pylint src/ai_guardian/ --disable=all --enable=E --disable=E1101,E0611,E2515,E2502,E0602,E0601,E1123,E1120,E0213,E0102,E0203,E1129,E0401 --output-format=text
uv run --extra dev python -c 'from pathlib import Path; import yaml; [yaml.safe_load(path.read_text(encoding="utf-8")) for path in sorted(Path(".github/workflows").glob("*.yml"))]'
```

## References

- `.wolf/cerebrum.md` - user preferences and project learnings
- `.wolf/buglog.json` - known bugs and fixes
- `AGENTS.md` - repository contribution rules
- GitHub issue: `https://github.com/RedHatProductSecurity/ai-guardian/issues/2470`
