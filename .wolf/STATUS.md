---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS - ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-10-10

---

## Current Quest: Issue #2527

- Added tray workflows for OpenShell middleware readiness, explicit native vs
  AI Guardian-hooked sandbox creation, policy profile discovery/validation, and
  complete-policy replacement for existing OpenShell sandboxes.
- Kept service-manager ownership of the external Rust process and OpenShell
  ownership of gateway registration and `network_middlewares` activation.
- Added the shipped middleware policy overlay with `api.openai.com`,
  `chatgpt.com`, and `ab.chatgpt.com`, plus operator-boundary documentation.
- Tray readiness now reads registered gRPC endpoints from gateway TOML and calls
  `SupervisorMiddleware/Describe`. It reports Running only after the configured
  endpoint responds with `ai-guardian/rust-middleware` and a version; gateway
  extension activation is reported separately. No endpoint or registration
  input is required in the tray.
- The initial readiness failure was caused by the tray runtime missing `grpcio`
  while gateway metadata still reported the extension active. After refreshing
  the tray installation, the user confirmed the readiness check works.
- Added grpcio/protobuf runtime dependencies, deployment guidance, and unit/UX
  coverage. Missing tray-runtime dependencies now direct operators to refresh
  the AI Guardian installation and restart the tray. The directly affected suite
  passes 110 tests; full Ruff, Black,
  Pylint, Mypy, and diff checks pass. Mypy reports no issues across 302 files.
- User confirmed readiness works after refreshing the AI Guardian tray
  environment; the prior `grpcio` import failure is resolved.
- Improved the **Apply policy to sandbox** form: the policy-profile selector is
  wider for long choices, and its help explains that the selected profile is an
  overlay. The merged policy is editable; **Replace policy** validates the YAML,
  preserves required base controls, and applies the edited document. Invalid YAML
  reopens the editor with the user's text preserved.
- Removed policy-preparation and repository-upload preflight progress
  interstitials, and kept successful sandbox operation details open until the
  user closes the dialog, preventing fast modals from flashing and disappearing.
- The full directly affected sandbox/middleware suite passes (124 tests).
- Ruff, Black, Pylint, Mypy (302 source files), JSON validation, and
  `git diff --check` pass.
- PR #2530's Read the Docs failure came from `pymdown-extensions` 12.2 being
  resolved against `mkdocstrings==1.0.6`. Pinned `pymdown-extensions==11.0.1`
  locally; the isolated MkDocs build passes on Python 3.14. The fix remains
  uncommitted and must be sent to the PR before RTD can rerun.

## Done

- Issue #2523 scanner ownership documentation and regression coverage were
  already present in the #2525 working tree; the active completion target is
  now #2525.

- Superseded the earlier issue #2507 coupled sandbox/middleware flow: generated
  middleware state, gateway bootstrap, middleware startup, and sandbox
  middleware flags were removed in favor of the native OpenShell operator flow.
  Added focused unit/UX coverage and updated the OpenShell/Sandbox guides.

- OpenShell Codex authentication is now explicit in the tray Create sandbox
  form: OAuth maps to the managed `ai-guardian-codex` provider and API key maps
  to `ai-guardian-openai`. The same choice is available through
  `--openshell-auth`, while an optional provider override remains available for
  existing gateway instances. Provider setup docs and regression tests now
  distinguish `codex`/`openai` profiles from the prefixed instances.
- Reworked `docs/Sandbox.md` into short, case-based setup recipes with
  prerequisites for Container OAuth/API-key, OpenShell OAuth/API-key, and tray
  creation; lifecycle, options, snapshots, and troubleshooting now follow the
  first-use paths.
- Committed the sandbox/authentication and documentation work as `4e9e78ba`,
  pushed `docs/restore-openshell-sandbox-setup`, and opened PR #2514.
- Addressed both CodeRabbit findings in `d822f60e`: provider refresh now
  requires credentials matching the selected provider type, and the API-key
  test isolates `CODEX_HOME`; the focused sandbox/tray suite now passes 155
  tests.
- Restored the missing OpenShell provider-instance setup commands to
  `docs/Sandbox.md` on branch `docs/restore-openshell-sandbox-setup`; the
  documentation now covers both Codex OAuth and API-key provider creation
  before `ai-guardian sandbox create --provider`, and records the tray's
  automatic provider selection behavior. The first-create sequence now enables
  Providers v2/imports profiles, and missing-profile errors link directly to it.
  It also documents the official local gateway installer, Linux/macOS service
  checks, rootless Podman socket startup, and remote gateway registration. The
  fresh-machine recipe now pins the installer and provider manifests to the
  same OpenShell v0.1.2 release and explains newer-setting compatibility.
- PR #2513 review follow-up is implemented and pushed in commit `15644bf1`.
  OpenCode V2 setup now refuses to rewrite configuration when an unrelated
  local TypeScript plugin file would be migrated implicitly, preserves the
  original file, documents explicit migration, and adds regression coverage.
  Focused OpenCode, setup, integration, UX, Pi, Black, Ruff, Pylint, Mypy,
  JSON, and diff checks pass locally.
- Issue #2510 now removes the legacy `implicit_optional` Mypy compatibility
  override and makes nullable defaults explicit with Python 3.10 typing across
  scanner, setup, daemon, policy, hook, and configuration-scope APIs.
- Issue #2510 validation passes: Mypy, Ruff, Black, Pylint error checks, diff
  checks, and 994 focused unit tests. Six existing OpenCode V1/V2 setup
  assertions remain a documented baseline mismatch and are unrelated.

- OpenShell middleware `restart --config FILE` now preserves saved bootstrap,
  gateway, policy, bind, and audit arguments instead of dropping them. The
  middleware guide now leads with the minimal config → start/bootstrap →
  managed Codex sandbox flow; provider setup, curl probes, and audit
  redirection are explicit/optional sections. Rust now owns OpenShell gRPC and
  uses daemon Unix-socket IPC by default; the live macOS sandbox reports active
  policy and provider credentials. Rust advertises text-WebSocket scanning for
  Codex, unwraps daemon IPC responses, and returns sensitive-content denials
  instead of middleware failures. Focused middleware/daemon tests, 4 Rust
  tests, and the live Codex HTTP/WebSocket checks pass. Commit `6f84e070` is
  pushed to PR #2515. Commit `5bc46714` clarifies Codex retry behavior and
  `4c9969dc` applies valid CodeRabbit hardening findings.

- OpenShell middleware lifecycle now matches the daemon with `start`, `stop`,
  `status`, and `restart` subcommands. Background starts persist sanitized
  restart arguments and the config path in the XDG-backed private state file;
  bare `restart` reuses them without persisting CLI JWT secrets.
- The OpenShell middleware qualification guide was restructured into one linear
  Community-image proof path with shared XDG/Console audit instructions,
  conditional gateway restart guidance, and the one-step sandbox create flow
  without `--tty --detach`.
- Branch `2484` is pushed through commits `9bfcc90f` and `324cc27a`. Focused
  middleware/UX coverage passes (45 tests), as do Ruff, Black, Pylint, Mypy,
  JSON validation, and diff checks.

- Issue #2478 updated the Codex-only OpenShell image from `@openai/codex`
  `0.154.0` to current stable `0.160.0`. The container README, changelog, and
  CLI-version fixtures now match the pin; OpenCode and Pi remain normal-image
  integrations only.
- Rebuilt `localhost/ai-guardian-openshell:2478`. The bundled Codex reports
  `0.160.0`, its OCI label matches, and the image contains no OpenCode, Pi,
  Claude, or Copilot executable. The live version monitor reports all managed
  support-image CLI pins current.
- OpenWolf's OpenCode integration is now on branch `openwolf-plugin-layout` in
  PR #2504. The implementation uses `.opencode/plugins/openwolf/`, adds the
  V2 bridge, preserves V1/V2 event handling, and passes the focused OpenCode
  support tests.
- Addressed all four actionable CodeRabbit findings for PR #2504 in commit
  `36515c65`: stable session usage snapshots, empty-context suppression,
  per-event failure isolation, and PR-specific validation notes. Added focused
  regression coverage and completed the PR template sections.
- Focused OpenShell/version tests pass (93 tests), as do Ruff, Black, Pylint,
  Mypy, and diff checks.
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

- Send the docs dependency pin to existing PR #2530 through the DAF completion
  flow, then verify Read the Docs and any remaining pending checks. JIRA
  acceptance criteria were unavailable because `JIRA_API_TOKEN` was unset.

## Context

- Working directory: `/home/itdove/development/ai/ai-guardian`
- Branch: `2527`
- Current issue: `RedHatProductSecurity/ai-guardian#2527`
- Branch `2527` backs open PR #2530 at `63f2fcb`. Local modifications are
  `docs/requirements.txt` and the OpenWolf-generated `.wolf/anatomy.md` update;
  no commit or push was made.
- Read the Docs uses Python 3.12; the local docs build passed on Python 3.14,
  and no local Python 3.12 interpreter was available.
- The generated `docs/notebooklm-export.md` remains intentionally untouched;
  refresh it only during the release process.
- `uv.lock` is ignored by this repository and was regenerated locally.
- Do not regenerate `docs/notebooklm-export.md` during development.

## Validation

```bash
uv run --extra dev python -m pytest tests/unit/test_openshell_middleware_probe.py tests/unit/test_openshell_middleware_tray.py tests/unit/test_openshell_policy.py tests/unit/test_sandbox_tray.py tests/ux/test_user_experience_contract_sandbox_middleware.py -q  # 115 passed
black --target-version py310 --check src/ai_guardian/ tests/
ruff check src/ai_guardian/ tests/
pylint src/ai_guardian/ --disable=all --enable=E --disable=E1101,E0611,E2515,E2502,E0602,E0601,E1123,E1120,E0213,E0102,E0203,E1129,E0401 --output-format=text  # 10.00/10
mypy src/ai_guardian/  # no issues across 302 files
uv run --extra dev python -m json.tool .wolf/buglog.json > /dev/null
git diff --check
```

## References

- `.wolf/cerebrum.md` - user preferences and project learnings
- `.wolf/buglog.json` - known bugs and fixes
- `AGENTS.md` - repository contribution rules
- Current GitHub issue: `https://github.com/RedHatProductSecurity/ai-guardian/issues/2527`
