---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS - ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-10-15

---

## Issue #2549 scoped tray Pause/Resume — 2026-10-14

- Native follow-up (2026-10-15 UTC): user saw current sessions/directories but
  indefinite session Pause and About selections did nothing. DBus trace showed
  KDE root `closed` arriving ~3 ms before the selected item's `clicked`; immediate
  pending refresh deleted its native action ID. Keep the guard through a 150 ms
  GLib click-delivery grace period and invalidate old close callbacks on reopen.
  Deterministic unit/UX regressions reproduce the pre-fix loss. The user restarted
  only the tray and reported it working afterward. No agent-run live controls.
- Implemented coherent per-target menu stats for headers, Status, and scoped
  controls. Scoped operations require explicit acknowledgements, invalidate
  cached state, and request refresh without optimistic flags or broader fallback.
  Retain rendered stable keys/project paths/targets across list/discovery changes.
- Idle refresh detection includes session metadata/pause and directory/global
  state for local, remote, and container targets. Linux still ignores countdown
  noise and defers native replacement while open; closing renders fresh state.
  Single-remote global sync now reads the selected daemon, not host stats.
- Preserve all three scopes, layered hook enforcement, persistence/lifetimes,
  CLI/SDK/configuration and API contracts, older-daemon directory/global controls,
  and AI-session self-protection. Updated tray docs, changelog, and UX contracts.
- Validation: final six-file run passes 1,028 related tests (944 tray/client unit
  tests and 84 tests in both complete affected UX files). Another 119 related
  daemon state/server pause/session tests passed earlier; 1,147 distinct related
  tests overall. Ruff, Black (`--target-version py310`), Pylint, Mypy in the uv
  dev environment, and diff checks pass. Changed-source statement coverage is
  100% (123/123 executable lines), not a full-project coverage estimate. Artifacts:
  `/tmp/opencode/guardian-2549-followup.coverage` and
  `/tmp/opencode/guardian-2549-followup-coverage.json`.
- Coverage (Apache-2.0) was used only as a transient validation dependency; no
  project dependency was added. No full suite, integration/container scenarios,
  live daemon/tray controls by the agent, installed integration changes, commits,
  or PRs ran. Native traces were read-only; harmless About tests and tray restart
  were performed by the user.
- Branch `2549` is ready for the user's `daf complete` outside this session.
  User reported the Linux native retest working after restart. Broader native
  timing/desktop coverage and macOS/Windows manual QA remain unverified;
  unit/UX coverage simulates the relevant platform and popup contracts.

## PR #2550 CI follow-up — 2026-10-14

- Run `38622505163` failed five Python/OS jobs at head `76c8b1b5`. All failures
  came from new CLI UX transport mocks counting background tray subscriber
  connections, not production pause/resume behavior.
- Added an opt-in test-thread transport fixture that declines background
  connections without counting them or feeding them into the in-memory server.
  Retained exact CLI call assertions; global UX now uses real wire framing.
  Session timers replace only daemon-state's clock namespace, not process time.
- Deterministic background-connection and process-clock regressions failed
  before the fix. All 552 related unit/UX tests, including both complete affected
  UX files, pass. Ruff, Black (`--target-version py310`), Pylint, uv-environment
  Mypy, and diff checks pass. No full suite or container scenarios ran locally.
- Changes are test-only plus OpenWolf bookkeeping, local on branch `2547`.
  The user explicitly authorized direct commit and push to existing PR #2550.
  Publication uses branch `2547`; CI must validate the corrected head. No old-head
  rerun, full-suite run, or local container validation is needed for this fix.

## Issue #2547 scoped top-level pause/resume — 2026-10-14

- Implemented mutually exclusive `--dir DIRECTORY` and `--session SESSION_KEY`
  selectors for the short pause/resume commands through a shared parser helper.
  Empty/whitespace selectors fail before dispatch in both short and nested forms.
  Global syntax, positional durations, existing daemon handlers/transports,
  normalized directories, stable identities, pause lifetimes, and self-protection
  remain unchanged.
- Added parser/handler/self-protection regressions and complete scoped UX
  contracts, including in-memory real client/protocol/server-state routing.
  Covered shared-directory isolation, timers/lifecycles, layered resume, unknown
  or expired identities, unsupported requests, and no auto-start/offline writes.
- Updated cookbook, tray CLI reference, changelog, and release-readiness checks.
  The workflow registers two sessions from the actual isolated project cwd and
  discovers their stable keys from status; workflow YAML/Python contracts pass.
- Final validation: 549 related unit/UX tests pass, including both full affected
  UX files. New scope helpers have 100% statement coverage. Ruff, Black
  (`--target-version py310`), Pylint, and Mypy in the declared uv dev environment
  pass. Standalone Mypy retains 14 known request-stub errors in two untouched
  files; no unrelated source fixes were made.
- No full-suite, integration/container scenarios, release lifecycle job, live
  daemon controls, installed integration changes, commits, or PRs were run.
  Coverage artifacts are in `/tmp/opencode/guardian-2547*`; no project dependency
  was added. OpenWolf hooks maintain anatomy/memory automatically.
- Branch `2547` is ready for the user's `daf complete` outside this agent session.

## PR #2548 CI follow-up — 2026-10-14

- Failed run `38587480047`, job `115933219257`: OpenShell ARM64 image installed
  GitGuardian with a valid checksum, then exhausted two five-second version
  probes under QEMU. AMD64 installation passed; this is unrelated to tray labels.
- Installer verification and version discovery now share `ggshield --version`
  with a bounded 60-second timeout. Other scanners retain their five-second
  fallback probes. Timeouts/nonzero exits still fail verification.
- The slow-startup regression failed before the fix. All 120 related installer,
  setup-install, and scanner CLI tests pass; focused installer coverage is 72%.
  Ruff, Black (`--target-version py310`), Pylint, Mypy, and diff checks pass.
- Branch `2546` / PR #2548 remains the publication target. Full Buildx/QEMU
  validation is left to CI; no container builds or scenarios were run locally.

## PR #2548 review and fixes — 2026-10-14

- Reviewed head `07291dd64df900ead4d00b323170c1f397449c59`, then fixed both P3
  findings at the user's request. Final Windows session-menu text escapes literal
  ampersands without changing titles, collision comparisons, or pause keys.
  `sessions/base.py` is now included in the daemon dev source inventory.
- Regression tests reproduced both bugs before the fixes. 681 related unit/UX
  tests now pass, including full sandbox tray, daemon client/tray, and session
  pause UX files. Ruff, Black (`--target-version py310`), Pylint, and Mypy pass.
- Updated tray documentation, changelog, and OpenWolf learnings/buglog. Changes
  were committed and pushed as `ccf91624` on branch `2546` to PR #2548.
  Windows rendering is source-confirmed and platform-simulated, not live-tested.

## ✅ Done

- Issue #2546: carry optional `session_title` through hook tracking and the
  live-session registry; retain known titles on missing/invalid metadata and
  preserve stable identity and pause timers through renames. Tray session menus
  prefer safe single-line titles capped at 80 characters, fall back to IDs/keys,
  and disambiguate identical displayed labels with short stable-key fingerprints.
  Label/collision work is bounded to the 16 visible slots; local, remote, and
  container actions continue using the selected target and full session key.
- OpenCode V2 forwards exact-session native title metadata with a 500 ms timeout,
  30-second positive/negative cache, and 128-entry bound; failures never skip
  hook checks, and deletion clears the cached entry. No transcripts are loaded
  for labels. Updated tray/OpenCode docs, changelog, unit tests, and session-pause
  UX contract; fixed two existing discovery fixtures to avoid the host database.
- Validation for #2546: 1028 related unit/UX tests passed; the final 577-test
  tray/UX rerun also passes, including the added visible-slot/overflow regression.
  Ruff, Black, Pylint, Mypy, buglog JSON, and `git diff --check` pass.
  Generated TypeScript passes strict checking against `@opencode/plugin@2.0.22`.
  Temporary compiler dependencies live only in `/tmp/opencode/guardian-2546-ts`.
- No commits, PRs, live tray restarts, or installed integration changes were made
  in this DAF session. The pre-existing `.wolf/anatomy.md` change was preserved;
  OpenWolf hooks also refresh that index as source files change.

- Issue #2542: successful tray sandbox creation now adds a Connect button to the
  completion dialog. It invokes the existing interactive connect flow for the
  selected container or OpenShell runtime without rerunning creation. Connect is
  absent while creation is running and on failure; output, Copy, and Close stay
  available. Added unit/UX contracts and changelog entry. A live Tk dialog smoke
  with mocked creation verified the button visibility and click event; no real
  sandbox was created.
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
- Issue #2473: implemented gateway-owned Google Cloud ADC for native Claude
  Code/Vertex and OpenCode's `claude` agent/Vertex path. The sandbox attaches a
  `google-cloud` provider, exposes metadata-emulator discovery without mounting
  ADC or forwarding credentials, and binds only the selected regional plus
  fixed global/replicated Vertex endpoints. OpenCode is bundled; Claude remains
  a runtime install after explicit ToS consent. The OpenShell entrypoint,
  registry, and tray now agree on supported clients. Added metadata readiness
  and sanitized manual qualification rows for both combinations. No live Vertex
  model qualification was run.
- Fixed OpenShell 0.1.3 provider discovery: `provider get` has no `--output` flag
  and emits a human-readable `Type:` row. The sandbox command regression suite
  passes (89 tests).
- Removed unsupported `tls: terminate` from bundled GitHub read-only and
  read/write policies. Both direct policy tests pass; the full container script
  suite has 26 unrelated failures because macOS Bash 3.2 aborts on unset
  `USERNS_ARGS[@]` under `set -u`.
- Tray Create sandbox requires an explicit Anthropic ToS acceptance when
  Claude is selected and forwards `ACCEPT_PROPRIETARY_TOS=true` only when
  checked. Fixed tray form regression: disabled Tk checkbox values clear to
  `False`, avoiding invalid `BooleanVar` initialization. Existing sandbox
  `ag-claude` started without consent; `connect` does not rerun startup. Update
  host tool with `uv tool install --editable .`, restart tray, and create a new
  sandbox; image rebuild is not needed.
- Validation: 100 tray tests and 89 sandbox command tests pass. Ruff, Black, and
  Pylint pass; Mypy reports two errors in untouched UI files.
- Reordered sandbox target actions so **Connect** and **Manage sandbox** appear
  immediately below **Pause...** in single- and multi-daemon menus.
- Reworked tray initial configuration into mutually exclusive Host/default,
  Profile, Host config directory, and Latest saved snapshot sources; only the
  selected source input stays enabled.
- Validation: all 100 `tests/unit/test_sandbox_tray.py` tests pass; Ruff, Black,
  and `git diff --check` pass.
- Fixed Claude installer/update egress: allow its temporary installer binary to
  fetch `downloads.claude.ai`, and its installed versioned binary to reach Claude
  downloads and Vertex endpoints. Host composes this policy; no image rebuild is
  needed. The `ANTHROPIC_VERTEX_PROJECT_ID` setting was detected, so project ID
  is not cause of the reported connection refusal. Three focused policy tests pass.
- Validation: 330 directly related unit tests pass. Black, Ruff, Pylint, Mypy,
  shell syntax, report-schema JSON, buglog JSON, and `git diff --check` pass.
- Follow-up tray/network fixes for #2473: Codex authentication is disabled unless
  runtime is OpenShell, mode is AI Guardian hooks, and CLI is Codex. Add the
  Claude Console/OAuth `platform.claude.com` endpoint and sign-in redirect host
  to its restricted network policy. All 165 tray/container contract tests pass;
  Black, Ruff, Pylint, Mypy, and `git diff --check` pass.

## 🚀 Next quest

- Manually verify #2549 native Linux session/directory controls if available:
  rapid pause/resume, idle external changes/expiry, overlapping scopes, and
  selectable nested Resume. Compare macOS/Windows where available.
- Complete #2549 with `daf complete` outside the agent session; let CI run the
  remaining matrix and non-unit validation.
- Previous handoff follow-ups remain below; they are not part of #2549.
- Monitor PR #2548 CI, particularly the multi-architecture OpenShell build after
  the ggshield startup-timeout fix.
- Optionally verify named/unnamed and renamed OpenCode sessions in the live tray
  after deploying/reloading the updated managed plugin.
- Preserve the pending #2473 manual Claude Code/Vertex and OpenCode/Vertex
  qualification from the previous handoff for follow-up after #2542.

## Context

- Working directory: `/home/itdove/development/ai/ai-guardian`
- Branch/issue: `2549` / `RedHatProductSecurity/ai-guardian#2549`.
- Local desktop: KDE Plasma 6.7.4, Qt 6.11.2, Wayland; AI Guardian tray is
  running. No crash was deliberately triggered on the live desktop.
- The OpenCode JavaScript/TypeScript CodeQL workflow is not configured; the
  unrelated `.opencode/plugins/openwolf/` middleware was not changed.
- Do not regenerate `docs/notebooklm-export.md` during development; release
  workflow refreshes it.

## Validation

For #2546, Ruff, Black (`--target-version py310`), Pylint, Mypy, generated-plugin
TypeScript checking, and `git diff --check` pass. Related tests include the complete
`tests/ux/test_user_experience_contract_session_pause.py` and OpenCode self-protection
UX contract, plus daemon state/server/REST/tray, sandbox tray, IDE-session,
TypeScript bridge runtime, and OpenCode support unit files. Live tray verification
was not performed. Historical validation for prior tasks follows.

```bash
uv run --extra dev python -m pytest tests/unit/test_sandbox_tray.py tests/ux/test_user_experience_contract_sandbox_create_connect.py -q  # 108 passed
ruff check src/ai_guardian/ tests/  # passed
black --target-version py310 --check src/ai_guardian/ tests/  # passed
pylint src/ai_guardian/ --disable=all --enable=E --disable=E1101,E0611,E2515,E2502,E0602,E0601,E1123,E1120,E0213,E0102,E0203,E1129,E0401 --output-format=text  # 10.00/10
mypy src/ai_guardian/  # 14 existing errors in skill_discovery.py and secret_validator.py
git diff --check  # passed
uv run --extra dev python -m pytest tests/unit/test_openshell_compatibility.py tests/unit/test_openshell_middleware_tray.py tests/unit/test_openshell_middleware_probe.py tests/ux/test_user_experience_contract_sandbox_middleware.py -q  # 32 passed
cargo test --manifest-path rust/openshell-middleware/Cargo.toml  # 13 passed
python scripts/check_openshell_compatibility.py  # passed
ruff check src/ai_guardian/ tests/  # passed
black --target-version py310 --check src/ai_guardian/ tests/  # passed
pylint src/ai_guardian/ --disable=all --enable=E --disable=E1101,E0611,E2515,E2502,E0602,E0601,E1123,E1120,E0213,E0102,E0203,E1129,E0401 --output-format=text  # 10.00/10
mypy src/ai_guardian/  # 14 known errors in skill_discovery.py and secret_validator.py
uv run --extra dev python -m pytest tests/unit/test_openshell_manual.py -q  # 14 passed
uv run --extra dev python -m pytest tests/unit/test_sandbox_command.py -q  # 89 passed
uv run --extra dev python -m pytest tests/unit/test_sandbox_tray.py -q  # 100 passed
uv run --extra dev python -m pytest tests/unit/test_container_scripts.py::TestContainerLaunchers::test_github_policy_allows_read_only_api_and_git_operations tests/unit/test_container_scripts.py::TestContainerLaunchers::test_github_readwrite_policy_allows_api_and_git_writes -q  # 2 passed
uv run --extra dev python -m pytest tests/unit/test_container_scripts.py::TestContainerLaunchers::test_agent_policy_fragments_are_scoped_to_one_selected_agent tests/unit/test_container_scripts.py::TestContainerLaunchers::test_policy_composer_merges_only_the_selected_agent_fragment -q  # 2 passed
ruff check container/tests/test_openshell_agents.py tests/unit/test_openshell_manual.py  # passed
black --target-version py310 --check container/tests/test_openshell_agents.py tests/unit/test_openshell_manual.py  # passed
git diff --check  # passed
```

- Follow-up lint/type validation: Ruff, Black, and Pylint pass. Mypy reports two
  existing errors in `src/ai_guardian/ui/clipboard.py:39` and
  `src/ai_guardian/ui/ask_dialog.py:512`.

## References

- `.wolf/cerebrum.md` - user preferences and project learnings
- `.wolf/buglog.json` - known bugs and fixes
- `AGENTS.md` - repository contribution rules
- Current GitHub issue: `https://github.com/RedHatProductSecurity/ai-guardian/issues/2549`
