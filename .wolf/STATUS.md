---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS - ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-10-04

---

## Done

- Issue #2493 now normalizes the sandbox create form's Initial config choice to
  `Host/default` for fresh and invalid state, preserves an explicit Latest saved
  snapshot selection during upload-cancel reopen, and aligns Tkinter/NiceGUI
  choice rendering with regression coverage.
- Focused sandbox validation passes: 151 tests, Ruff, Black, Pylint error checks,
  and Mypy. Changes remain uncommitted on branch `2493` for `daf complete`.
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
- Addressed the CodeRabbit review findings for #2470: cached OpenCode version
  probes, robust V2 database-path discovery, safe V2 error-event handling, and
  the current Codex-only OpenShell registry expectation. Commit `815ed01a` is
  pushed to `origin/2470`.
- Review-fix validation passes: 122 OpenCode/transcript/registry tests, 276
  doctor/daemon/IDE UX tests, Ruff, Black, Pylint, Mypy, and diff checks.
- The first post-review CI run failed uniformly because
  `tests/unit/test_cli_version_check.py` still expected the removed
  `PI_VERSION` OpenShell pin. The test contract now matches the Codex-only
  image in commit `50df159f`, which is pushed to `origin/2470`.
- PR #2495 is open and ready for review. Build, lint, smoke, container, and
  integration checks are rerunning for the CI correction.
- Issue #2496 now uses a two-step Later flow for IDE/CLI setup prompts across
  Tkinter, NiceGUI, macOS Cocoa, and Linux native fallbacks. Closing defaults
  to a one-hour snooze while explicit Don't Ask Again remains permanent.
- Issue #2496 coverage includes provider-specific unit tests, IDE setup UX
  contracts, changelog documentation, and a passing focused validation set.
- Issue #2494 now makes plain `ai-guardian setup` reuse installed integration
  detection and integrity checks, skip healthy integrations, select some/all
  pending targets interactively, and support `--yes`, `--json`, profiles, and
  config creation across the selected integrations.

## Next Quest

- Run `daf complete` outside the active agent session when ready to commit and
  publish the #2493 implementation.
- The prior #2494 handoff remains in the historical context below; its changes
  are not part of the active #2493 worktree.

## Context

- Working directory: `/home/itdove/development/ai/ai-guardian`
- Branch: `2493`
- HEAD: `6841ef54`; issue #2493 source and test changes are uncommitted on this
  feature branch.
- Structured Linux setup prompts now remain on Tkinter/NiceGUI so native
  zenity/kdialog fallbacks cannot drop IDE/profile choices; setup and upgrade
  prompt workers share a non-blocking serialization lock.
- Focused validation: 153 setup/tray/proactive unit and UX tests (152 passed,
  1 skipped), plus 338 setup unit tests with seven unrelated OpenCode contract
  tests deselected; Ruff, Black, Pylint, Mypy, and `git diff --check` pass.
- The prior issue #2470 implementation, tests, documentation, workflow,
  container, policy changes, doctor reporting, daemon routing, review fixes,
  and CI test-contract correction remain committed and pushed to `origin/2470`;
  PR #2495 is open.
- NiceGUI is a core dependency; `uv.lock` is ignored by this repository and was regenerated locally.
- Do not regenerate `docs/notebooklm-export.md` during development.

## Validation

```bash
uv run --extra dev python -m pytest tests/unit/test_proactive_prompt.py tests/unit/test_tray_plugins.py tests/ux/test_user_experience_contract_ide_setup.py -q
ruff check src/ai_guardian/ tests/
black --target-version py310 --check src/ai_guardian/ tests/
mypy src/ai_guardian/
pylint src/ai_guardian/ --disable=all --enable=E --disable=E1101,E0611,E2515,E2502,E0602,E0601,E1123,E1120,E0213,E0102,E0203,E1129,E0401 --output-format=text

# Prior #2470 validation
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
- GitHub issue: `https://github.com/RedHatProductSecurity/ai-guardian/issues/2496`
- Prior GitHub issue: `https://github.com/RedHatProductSecurity/ai-guardian/issues/2470`
- Current GitHub issue: `https://github.com/RedHatProductSecurity/ai-guardian/issues/2493`
