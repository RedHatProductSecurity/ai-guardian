---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS - ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-10-24

---

## Issue #2568 / PR #2577 second CI follow-up — 2026-10-24

- User published the prior follow-up as `78a8811` on branch `2568`; started clean.
  Latest Tests `40122958805` and Smoke `40122958830` now fail only three Windows
  prerequisite-preservation cases: native PowerShell's
  `AppData/Local/Microsoft/PowerShell/StartupProfileData-NonInteractive` changes.
  Linux/macOS smoke jobs pass; macOS logs confirm actual five-host package-first
  registration recovery passed. This does not qualify live host failure behavior.
- The previous directory-only cache fix missed Windows' .NET known-folder API.
  Primary PowerShell/CoreCLR source confirms it ignores LOCALAPPDATA for startup
  profiles. A shared test/lifecycle environment factory now requires hexadecimal
  `7FFFFFFF` CPUs for only that optional JIT profile, and removes inherited
  case-insensitive aliases before child overrides. No product/security changes.
  Selected HOME/USERPROFILE/config/state and complete home snapshots are unchanged;
  do not add startup-cache exceptions to the snapshots.
- Added four inherited-value/case-alias regressions and one native child probe;
  those plus the lifecycle contract failed before correction. **218 related
  recovery/wrapper/policy/complete-UX tests pass, no skips**, using verified native
  PowerShell 7.6.8 on Linux. Shared helper import defines functions only; the actual
  package-removal main remains guarded and was not run locally. Recovery engine
  unchanged; coverage **92%**, `/tmp/opencode/guardian-2568-ci-second-fixes.coverage`.
- Black py310, Ruff, Pylint E and project/helper Mypy (308 files) pass. Reviewed
  simplification by sharing the factory rather than keeping separate settings.
  Updated changelog, cerebrum and bug log; OpenWolf owns anatomy/memory updates.
- DAF note saved; latest diagnosis/local validation and pending Windows checklist:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2568#issuecomment-6388656026.
- **Next:** user publishes these local/uncommitted fixes via the external DAF
  workflow, then reruns native Windows Tests/Smoke and its actual package-first
  lifecycle. Do not claim Windows CI is green before that run.
- No live cleanup, package removal, process signaling, security changes,
  full-suite/container/integration execution, commit or push.

## Issue #2568 / PR #2577 CI follow-up — 2026-10-24

- User published the prior implementation as `83610b0` on branch `2568`, PR
  https://github.com/RedHatProductSecurity/ai-guardian/pull/2577, then reported
  failed CI. Current follow-up changes are local/uncommitted; DAF initialization
  and the one qualified ticket lookup were already completed. Preserve earlier
  handoffs below as history, including their pre-publication state.
- Inspected failed Tests `40116274118` and Smoke `40116274125`: Windows recovery
  compared path/handle ctime values with different CPython semantics; PowerShell
  startup caches polluted preservation snapshots on Linux/macOS. Fixed with
  separate same-API before/after metadata checks and isolated shell runtime dirs.
  Regression tests still reject real handle/path changes. CI-only package-first
  lifecycle snapshots exclude only the separate shell runtime, not selected homes.
- Windows Python 3.10 REST auth test also had an early-close/unread-body race.
  Use zero-body missing/incorrect-auth requests; assert exact 401 JSON and no body
  parsing/hook processing. No production REST/auth behavior was changed.
- **Validation: 285 distinct related tests pass, no skips** (213 recovery, wrapper,
  policy and complete affected UX tests; 72 REST unit tests). Verified portable MIT
  PowerShell 7.6.8 archive SHA-256 and exercised native PowerShell on Linux from
  `/tmp/opencode/guardian-2568-pwsh.NVTAmUQ8/runtime`. Recovery engine coverage
  **92%**: `/tmp/opencode/guardian-2568-ci-fixes.coverage`. Dev dependencies omit
  pytest-cov/coverage; use ephemeral `uv run --with coverage==7.17.0` coverage CLI.
- Black py310, Ruff, Pylint E, project/helper Mypy (308 files), Bash syntax and
  whitespace checks pass. Simplification review kept the patch narrow. Updated
  changelog, cerebrum and bug log. OpenWolf owns anatomy/memory auto-updates.
- DAF progress note saved; CI diagnosis/local validation and pending checklist:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2568#issuecomment-6387849835.
- **Next:** publish these local fixes through the user's external DAF workflow,
  then rerun Tests/Smoke and the Linux/macOS/native-Windows lifecycle matrix.
  Native Windows/macOS fixes and actual package-first removal are not locally
  qualified; do not claim CI is green or live host failure behavior is verified.
- No live integration cleanup, installed-package removal, process signaling,
  security-policy edits, local lifecycle/container/full-suite runs, commit or push.

## Issue #2568 orphaned-integration recovery — 2026-10-24

- Managed DAF `open`, existing initially clean branch `2568`; qualified issue
  read once, initialization complete. Current work is local/uncommitted. Preserve
  prior handoffs below and OpenWolf's automatic anatomy/memory updates.
- Added independent stdlib-only Python 3.11+ `scripts/ai_guardian_recovery.py`,
  shared by revised Bash and native PowerShell wrappers. Supports explicit user,
  project and both scopes, exact selected projects (never implicit cwd/crawling),
  preview, unique backups, ownership checks, partial failure and idempotency.
  Covers Pi managed/legacy sources, Codex/Grok TOML MCP, relocated homes,
  OpenCode JSONC/V2 nested MCP/legacy plugin artifacts, Copilot top-level hooks,
  Antigravity and selected project registrations. Keeps unrelated settings/history.
- Recognized agent lifecycle invocations are denied even in trusted developer
  sessions. Existing genuine security denials, strict host settings and surviving
  launcher startup-failure contracts were not relaxed. Normal POSIX process
  cleanup now checks an owned launch, not a command substring.
- Added `docs/UNINSTALL.md`, source documentation/navigation/checklist/changelog,
  full recovery UX and related regressions, and shared Linux/macOS/native-Windows
  CI gate through smoke/release readiness. The five-host actual package-first
  scenario in `tests/lifecycle/orphan_recovery.py` is **CI-only, not run locally**.
  Windows recovery requires local companion files; backups inherit directory ACLs.
  Normal Windows package uninstall intentionally has fewer features than POSIX;
  custom/ambiguous sources and dependency caches remain retained/documented.
- **Validation: 519 related tests pass, 6 PowerShell-dependent skips**. Complete
  directly affected CLI-self-protection/recovery/hook-failure UX files pass.
  Engine coverage **92%**, `/tmp/opencode/guardian-2568-recovery.coverage`.
  Black py310, Ruff, Pylint E, project/helper Mypy (308 files), Bash syntax,
  documentation links/navigation, bug-log JSON and whitespace checks pass.
  MkDocs uses tagged extension values: inspect nav with BaseLoader/compose, not
  SafeLoader or unsafe Python-tag construction. No local MkDocs build required.
- DAF progress saved; issue progress and remaining checklist posted at
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2568#issuecomment-6386364010.
  **Next:** code review, then new CI matrix/package-first scenario; exact live
  host/platform/event outcomes for missing executable/interpreter/module remain
  explicitly **unverified** in the lifecycle matrix. Do not mark qualification
  complete, close the issue, or treat configured CI as a completed run.
- No live user configuration cleanup, installed-package removal, process signal,
  settings/security-policy change, local container/full-suite/integration run,
  commit, push or PR. Defer git publication to the user's external DAF workflow.

## Issue #2573 ServiceNow BYOG documentation — 2026-10-24

- Initialized managed DAF `open` session on existing, initially clean branch
  `2573`. Read the qualified ticket once; hierarchical context markdown/skills
  were absent. No temporary-clone sync was needed.
- Added `docs/POTENTIAL_INTEGRATIONS.md`: ServiceNow BYOG is potential,
  unimplemented, untested, unsupported, and unvalidated. Describes request/response
  adaptation, authenticated/protected communication, enforcement validation, and
  a suitable ServiceNow development/test environment. Includes vendor/repository
  references and #2572 for contributor interest and future validation.
- No development is planned without interest and a suitable test environment;
  the proposal is not an implementation or delivery commitment. Separate index
  and MkDocs Reference entries keep it outside supported IDE integrations.
  Updated the changelog; all five issue criteria are checked and DAF notes saved.
- Local-link/reference/index/YAML-navigation/whitespace checks and
  `git diff --check` pass. Documentation-only: no code tests, linters or local
  MkDocs build were required. The vendor URL returned only a JavaScript app shell
  to the text fetcher; no ServiceNow specification or interoperability validation
  is claimed.
- Changes remain local and uncommitted for review and the user's external
  `daf complete`. No integration code, runtime/configuration change, installation,
  commit, push, PR or issue closure. Earlier handoffs remain historical/preserved.

## Issue #2569 Linux tray message lifecycle — 2026-10-23

- Managed DAF `open` session `RedHatProductSecurity-ai-guardian-2569`, branch
  `2569`, initially clean. Read the qualified ticket once; hierarchical context
  markdown/skills absent. No temporary-clone sync needed. Preserve earlier handoffs.
- Current About uses isolated Tk for its author link, unlike the ticket's older
  native-only trace. One action dispatches one worker. This environment is a TTY
  with no DISPLAY/WAYLAND_DISPLAY; zenity/kdialog are installed, but **the original
  graphical opening/style flash has not been reproduced or assigned a cause**.
- Fixed verified lifecycle defects in `tray/plugins.py` and
  `tray/dialog_placement.py`: no Linux/Tk informational reading deadline; ordinary
  native dismissal ends the action. The Tk child's first completed-root Map event
  reports readiness, allowing native fallback only before display. Post-display
  failures/interrupted waits never launch a replacement. Missing/startup failures
  retain fallback; diagnostics exclude raw message/child output/exception text.
- Nineteen red regressions verified the old behavior. **1,108 related tests pass**:
  full About-author, plugin, daemon-tray, proactive and sandbox-tray unit files,
  plus the entire **12-test About UX contract**. Focused coverage: placement 99%,
  plugins 73%, combined 76%; `/tmp/opencode/guardian-2569-dialog.coverage`.
  Black py310, Ruff, Pylint E, project Mypy (307 files) and whitespace checks pass.
- Updated source docs/changelog and manual QA matrix; recorded the learning and
  bug. DAF progress note saved; issue progress/remaining checklist posted at
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2569#issuecomment-6375656068.
  **Next:** obtain distro/desktop/X11-or-Wayland/UI/provider/timing and a
  sanitized screen recording if the flash persists. Manually repeat About/other
  affected shared messages, dismiss via OK/Escape/titlebar, and leave open beyond
  30 seconds on affected desktop; qualify GNOME/zenity and KDE/kdialog where
  available. Do not mark all issue criteria complete before that evidence.
- No live UI/browser, tray/daemon restart, installation, settings/permissions
  change, commit, push or PR. Use the user's external DAF completion flow only
  after review and remaining desktop verification.

## ServiceNow BYOG tickets — 2026-10-23

- Created and cross-linked enhancement #2572 and documentation #2573 in
  `RedHatProductSecurity/ai-guardian`, preserving the user's proposal and draft.
- #2572 is labelled enhancement/backlog/help wanted. No development is planned
  until there is contributor interest and access to a suitable test instance.
- #2573 is documentation-only: BYOG remains potential, unimplemented, untested,
  unsupported, and unvalidated. No integration or source documentation was changed.
- Verified both issue bodies and labels. No tests, commits, pushes, or PRs ran;
  existing local development work and earlier handoffs remain intact.

## About foreground regression — 2026-10-23

- User reported About appearing then immediately minimizing. The existing
  targeted window's WM_STATE was **Normal**, consistent with dropping behind
  rather than confirmed iconification; the original compositor timing was not
  independently captured.
- Fixed `tray/dialog_placement.py`: build withdrawn, finish layout/set a temporary
  raising hint, deiconify/lift, then focus/grab after idle. Clearing topmost at
  200ms also restores normal state/foreground once after the tray handoff. Guard
  closed-window callbacks and unsupported hints; never loop focus or keep topmost.
- Six new regressions failed before the fix. **844 related tests now pass**,
  including the entire five-test About UX contract and tray/plugin unit files.
  Focused `dialog_placement.py` coverage is **92%**, artifact:
  `/tmp/opencode/guardian-2567-about-focus.coverage`. Black py310, Ruff, Pylint E,
  project Mypy (307 files) and whitespace checks pass. Updated docs/changelog,
  learnings, bug log and local DAF note.
- **Real mapped KDE Wayland/XWayland check passed:** synthetic window remained
  Normal, viewable and focused at 75/300/700/1100ms, with topmost off after 200ms.
  It auto-closed at 1250ms; script:
  `/tmp/opencode/guardian-2567-about-focus-smoke.py`. This verifies the standalone
  dialog, not the user's actual tray-click sequence; ask the user to retry About.
  macOS/other desktops remain manual QA.
- All work remains local/uncommitted on `2567`; support work is unchanged. No
  tray/daemon restart, install, browser/profile launch, support upload, saved
  setting/permission change, commit, push or PR occurred.

## About author refinement — 2026-10-23

- User-confirmed final text: **Author: Dominique Vernier (ITDoVe)**. Never show
  the full profile URL in the visible author line; keep **https://github.com/itdove**
  as its click target. Package team attribution is not the requested author name.
- Shared `daemon/about.py` adds author metadata and formats the compact line even
  for older daemon responses. Global/per-daemon tray About passes explicit links;
  `tray/plugins.py` and `tray/dialog_placement.py` use isolated Tk when available,
  with click/Enter/Space activation only. Native fallback keeps the same text;
  it cannot provide the Tk clickable control. Web Console About shows the name
  and linked **(ITDoVe)**, preserving the repository link and existing information.
- Updated About unit/API regressions, new native-link/Web tests and the complete
  About UX contract, source docs, changelog, user preference and local DAF note.
  Seven red regressions verified the final compact-label correction before fixing it.
- Validation: **842 related tests pass** (838 About/tray/plugins/full About UX,
  plus four API/multi-client About checks). Black py310, Ruff, Pylint E, project
  Mypy (307 files) and whitespace checks pass. The later KDE mapped check above
  verifies foreground handling; actual tray-click/macOS confirmation remains
  manual QA. Unit/UX callbacks open no live windows or browsers.
- Still local/uncommitted on branch `2567`; support work below remains intact.
  No live support submission, browser launch, authentication/configuration change,
  installation/restart, commit, push or PR occurred.

## Issue #2567 reviewed support Gists + Discussions — 2026-10-23

- Local, uncommitted work remains on managed DAF branch `2567`. Ticket already
  read; do not reinitialize. Preserve pre-existing `.wolf/anatomy.md` changes.
- **Newest user approval supersedes inline delivery:** selected sanitized files
  go into one user-owned unlisted Gist. Native upload consent precedes the POST;
  a second exact preview shows the actual Gist link in a separate Diagnostics
  section of the Discussion, without replacing the sanitized user message.
  Neither approval may come from an agent, CLI `--yes`, or client parameters.
- **First screen:** read-only Destination dropdown, default **Create ZIP only**,
  with **Next** and Cancel, not separate destination buttons. Selection alone
  never advances or authorizes upload. Next opens the chosen review page. The
  destination-label mapping can grow without adding action buttons.
- **Newest form correction supersedes default-none:** files are alphabetically
  sorted (case-insensitive), with doctor.json first and checked by default for new
  lists. Other files start unchecked; saved choices, including an unchecked Doctor,
  remain authoritative. Apply ordering to summaries/review lists and Gist files.
  Remove the generated title from preparation/CLI/MCP/fallbacks. Draft fields may
  be blank; GitHub review requires a title and message, ZIP/legacy review a message.
  Whitespace does not count. Require at least one file too, and enforce in callbacks
  and backend before creating ZIPs or uploading. Entry StringVar and text Modified
  events keep action/validation state current across typing, paste and clearing.
- Next is disabled for Gist + Discussion without configured GitHub credentials;
  switching to ZIP re-enables Next. Backend rejects a forged/direct selection too. Availability
  uses captured, local `gh auth token --hostname github.com`, not network status
  or an unsupported `--no-refresh` flag. No automatic login/refresh/scope upgrade.
  Account discovery validates the pinned credential; known missing OAuth `gist`
  scope fails before upload. GitHub enforces actual Gist/Discussion permissions.
- `reporting/github_gist.py` owns sanitized, numbered inert filenames, upload
  preview, owner/visibility/complete-content verification, and Gist receipts.
  `github_support.py` keeps canonical account/repository/category checks and
  exact, expiring, single-use approvals. Public destination remains fixed to
  `RedHatProductSecurity/ai-guardian`, only `bug-reports` and `q-a`.
- Unlisted is **not private**. A public Discussion exposes its Gist link.
  Owners can manage/delete their Gist, but cannot retract copies/forks/caches.
  Cancellation/failure after upload returns `gist_url` and honest `gist_only` or
  uncertain status; tray shows Open Gist even on cancellation. Nothing deletes
  the Gist automatically. Later ZIP/cancellation also preserves its known link.
- Independent pre-mutation Gist/Discussion journals serialize processes and block
  duplicates after uncertain outcomes/restarts. Retry verifies/reuses the same
  Gist and needs fresh final public consent. Changed account/files/remote content
  or deleted Gist never triggers duplicate uploads or silent inline fallback.
  Bounded regular-file receipt reads/writes reject links before truncating;
  separate Gist metadata recovers the URL even if a Discussion receipt is corrupt.
- **Create ZIP only** remains credential-free/local/not encrypted, with complete
  checked files, retained archives and click-only Open destination folder.
  Original bundle/destination/explicit selections remain reusable until expiry.
  Explicit local/S3/GCS/email routes are unchanged; local export/manual email
  must not be reported as a completed support submission. No settings rewritten.
- Global Contact supports stays immediately above About, independent of daemon
  health. Native dialogs never open a shell; requests restore/raise/focus. File
  lists check only Doctor by default and require at least one selection plus
  mandatory fields; saved choices persist.
  Keep aligned rows, View, bulk controls, counts, message/category/destination,
  reserved unchecked consent controls, and wrap/horizontal-scroll/paged View.
- Standalone `ai-guardian support send --prepare` needs no agent/MCP/daemon and
  never auto-starts the daemon. Only local tray-host diagnostics are collected.
  CLI config copies use canonical relocated paths, redact sensitive containers,
  and omit unsafe input; original settings and removed files stay unchanged.
- Logs/violations cover only the last 12 hours. Every included violation stays
  complete, without count cap. Only logs may be shortened; structured diagnostics
  remain complete and fully viewable. View/ZIP/Send have no differing size crop.
  Gist input limit: 1,000,000 bytes / 100 diagnostics. Discussion body separately
  limited to 60,000 UTF-8 bytes; files no longer consume it. Oversize fails clearly.
- Source docs, MCP tool/skill, changelog, defaults/schema/profiles, Web Console
  and readiness checks match. Generated notebooklm export intentionally untouched.
- **Validation:** 576 related unit/UX tests pass, including full 43 support UX,
  89 Gist, 93 modal and 76 GitHub tests. Focused coverage **92%**; Gist/tray/native
  94%, GitHub 92%, bundle 90%. Artifact:
  `/tmp/opencode/guardian-2567-form.coverage`. Coverage's global environment lacks
  pytest-asyncio: exclude Web settings there; all 5 settings cases pass in the
  complete project `uv run --extra dev python -m pytest` run.
  Black py310, Ruff, Pylint E, project Mypy (307 files), and whitespace pass.
  No new project dependencies. Use installed Black executable, project-env Mypy.
- Hidden real-Tk checks pass for dropdown/Next credential gating and required
  text, alphabetical/Doctor defaults, bulk selection and action-state changes in
  five workflows. Script: `/tmp/opencode/guardian-2567-native-form-smoke.py`.
  No windows mapped or credentials/network/browser used. Earlier unchecked
  consent/View/ZIP/focus checks passed. Actual mapped desktop/file browser,
  macOS and explicitly authorized live authentication/publication remain manual QA.
- No real diagnostic collection/upload, Gist/Discussion/email, permission change,
  installation/restart, commit/push/PR occurred. Next: user desktop QA/diff review;
  use external `daf complete` for git publication only when agreed. CI owns
  unrelated/full/matrix/integration tests. Prior ticket progress (not this update):
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2567#issuecomment-6355528471

## Issue #2563 release 1.20.0 preparation — 2026-10-20

- Initialized the managed DAF `open` session on existing branch `2563`; the
  qualified ticket was read once. At preflight, HEAD, main, and origin/main
  matched `63efde002a08380146daa5d38e2783488c703cd7`; the checkout was clean.
- The user will launch `scripts/release.sh`, not the agent. Prepared only
  documentation: curated Unreleased notes, highlighted Python 3.10/Web Console
  migration, reconciled OpenShell support/qualification, and corrected release
  guide/skill TestPyPI routing, artifact-version, CI, and verification guidance.
- #2556 is already deferred by the operator to 1.22.0, linked to
  NVIDIA/OpenShell#4751. Retain Codex 0.160.0 without claiming new compatibility;
  candidate clean middleware traffic, actual denial, and lifecycle remain
  unqualified. Do not resume that stopped qualification or merge its local work.
- No open Dependabot alerts or PRs; release tools are installed and GitHub
  permission is ADMIN. The only open 1.20.0-labelled issue is #2563.
  The version helper calculates 1.19.0 + minor = 1.20.0. Remote release/test tags
  and release-1.20 are absent; both registries returned 404 for package 1.20.0.
- The existing PR #2565 test/lint/smoke matrix passed. Main wheel and CodeQL
  passed; its container run 39476298823 also succeeded at the exact baseline
  SHA. These are baseline results, not validation of the pending documentation
  commit or a substitute for fresh 1.20.0 Release Readiness evidence.
- Validation passes: 15 added local links/anchors, unchanged historical
  changelog, one Unreleased section, current stable-reference/Rust version
  checks, OpenShell compatibility, and diff whitespace. Documentation-only:
  no code tests, linters, MkDocs, local containers, or full suites were run.
- Next: review/land preparation through the user's external DAF workflow,
  keeping #2563 open. From clean, updated main with refreshed tags, the user
  previews `scripts/release.sh --dry-run minor`, confirms exactly 1.20.0 /
  release-1.20 / 1.21.0-dev, then runs `scripts/release.sh minor`.
- Cursor/manual checks, fresh source-matched Release Readiness, TestPyPI,
  maintainer tag approval, all production deliverables, and merge-back remain
  pending. The script's final message is not sufficient release evidence.
- Package/Cargo versions, image pins, root installer URLs, release script, and
  generated export remain unchanged for the canonical script. No commits,
  pushes, PRs, tags, workflow dispatches, runtime controls, or publishing ran.
  Older handoffs below are historical and outside this release preparation.

## Issue #2564 OpenShell experimental documentation — 2026-10-20

- Initialized managed DAF `open` session on existing branch `2564`; read the
  repository-qualified ticket once. No hierarchical context markdown or skills
  were present. This real-workspace development session needs no temp-clone sync.
- Added matching upstream `0.x`/pre-1.0 notices before setup in the sandbox and
  middleware guides, plus a direct-entry reminder at OpenShell provider setup.
  Qualified README preferred/default recommendations with concise linked warnings
  and marked the middleware feature experimental. Updated the changelog.
- Explained that supported release/protocol ranges do not fully qualify every
  client/provider combination or guarantee production stability. Existing security
  requirements, version guidance, defaults, policies, and pins remain unchanged.
- Documentation consistency, notice placement, local link anchors, and
  `git diff --check` pass. No code tests, linters, MkDocs build, runtime operations,
  commits, pushes, or PR creation were needed or performed.
- All five acceptance criteria are checked on #2564 and DAF notes are updated.
  Changes are local and ready for the user's `daf complete` outside this agent
  session. Pre-existing OpenShell handoff/learnings below remain preserved;
  this documentation task does not resolve the separate sandbox deletion problem.

## OpenShell ag-codex deletion blocked — 2026-10-20

- User requested deletion of `ag-codex` only. Retried the named deletion on
  gateway `openshell`; it failed with the same pending-driver-operation error.
- CLI/gateway/Podman driver report v0.1.3. Sandbox is `Error`, provisioning is
  `ready`, `driver_operation_pending` is true, and both deadlines are null.
  This matches the unresolved upstream report NVIDIA/OpenShell#4409; the exact
  local interruption that left the operation pending is not established.
- CLI delete has no force option. A rootless Podman lookup by the sandbox-id
  label returned no containers, but backend absence alone cannot establish that
  a pending external operation is settled. No matching shutdown/recovery warning
  was found in the bounded, sandbox-scoped gateway log query.
- Deletion remains unresolved. No gateway stop/restart, database access/edit,
  container removal, provider/policy changes, upgrade, or unrelated cleanup ran.
  Obtain approval for gateway downtime before an offline, backed-up recovery
  investigation; do not assume a restart or a cleared flag safely resolves it.
- No product code changed or tests ran. Older handoffs below are historical.

## PR #2562 CodeQL follow-up — 2026-10-19

- The original #2559 change was published externally as `e485b801` on existing
  branch `2559`, PR #2562. The workspace was clean before this follow-up.
- Inspected failed CodeQL check `118227020729`, alert #307, inline comment
  `4317265670`, and Python SARIF analysis `1983068885`. The reported sink is the
  classifier debug f-string at `scanners/ssrf.py:598`, with flows from scanned
  content and synthetic secret fixtures through URL/hostname processing.
- Replaced that log call with a constant, value-free match diagnostic. Parsed
  IPv6 scope IDs can retain arbitrary text, so input-derived addresses are not
  inherently safe log metadata. No classification, immutable decision, API,
  or user-facing message changes; no alert dismissal or analyzer changes.
- Seven deterministic no-network logging regressions failed before the fix.
  All 1,144 related tests pass: the prior 1,133, seven new regressions, and four
  related exfiltration use-case tests. Both affected SSRF/MCP UX files pass in
  full. SSRF statement coverage remains 85%; artifact:
  `/tmp/opencode/guardian-2562-codeql.coverage`.
- Ruff, Black (`--target-version py310`), Pylint, Mypy, and diff checks pass.
  Updated changelog, DAF notes, and replied to the inline review at
  `https://github.com/RedHatProductSecurity/ai-guardian/pull/2562#discussion_r4317345770`.
- The correction is local/uncommitted on `2559`; publish through the external
  `daf complete` workflow for existing PR #2562, then verify CodeQL on the new
  head. The old-head failure cannot validate this correction. No agent-run
  commits, pushes, old-head reruns, full suite, container runs, or live controls.

## Issue #2559 IPv6 embedded SSRF destinations — 2026-10-19

- Initialized managed DAF development session on existing branch `2559`.
  Ticket read once with the qualified GitHub repository. No hierarchical
  ENTERPRISE/ORGANIZATION/TEAM/USER markdown or hierarchical skills were present.
- Centralized native/mapped/6to4/Teredo destination enumeration. Both Teredo
  roles use existing policy: client for tunneled traffic, server for potential
  setup/control traffic. Share existing immutable metadata hosts so numeric
  endpoints also receive consistent resolved/embedded classification.
- Preserve public transition/native IPv6, explicit range policies, supported
  localhost semantics, immutable decisions, domain/action behavior, and return
  contracts. No DNS, redirect following, or network requests added to hooks.
- Unit and UX regressions reproduced the gap before the fix. All 1,133 related
  tests pass, including both complete directly affected SSRF/MCP UX files and
  related validator, warning, column, multi-finding, and Hermes unit tests.
  The bounded policy controls have 0/368 false-positive checks; these are
  synthetic checks across formats/entry points, not independent population data.
- SSRF statement coverage is 85%; all 21 changed executable lines are covered.
  Artifacts: `/tmp/opencode/guardian-2559.coverage` and
  `/tmp/opencode/guardian-2559-coverage.json`. Coverage (Apache-2.0) was a transient
  validation tool only, not a project dependency.
- Ruff, Black (`--target-version py310`), Pylint, Mypy in the uv dev environment,
  and diff checks pass. Updated SSRF docs, research attribution, and changelog.
  No full suite, integration/container scenarios, protected destination requests,
  live exploit qualification, security controls, commits, pushes, or PRs ran.
- All seven issue criteria are checked, DAF notes are updated, and the summary
  is posted at `https://github.com/RedHatProductSecurity/ai-guardian/issues/2559#issuecomment-6273180237`.
  Branch `2559` is ready for the user's external `daf complete` workflow.
  CI owns the remaining platform/matrix validation.
- Older handoffs below are historical and outside #2559.

## PR #2561 CodeQL follow-up — 2026-10-19

- Inspected failing CodeQL check `118148056624` at head `7eb59c1d`. Its two
  high-severity findings point to unchanged parser logging at
  `patterns/toml_parser.py:262,264`, not failed credential detection.
- Python SARIF analysis `1981946486` traces both findings from the new test's
  `BUNDLED_FILES["secrets"]` lookup: CodeQL mistakes a bundled data-file path
  for credential data. No token value flows through the reported path.
- Changed only the unit fixture to resolve `DATA_DIR / "secrets.toml"`, matching
  the existing bundled-pattern tests. Runtime parser/detection/logging and
  analyzer checks remain unchanged; no alerts were dismissed or suppressed.
- All 462 focused unit/UX tests pass, including the complete affected
  PostToolUse contract. Ruff, Black (`--target-version py310`), Pylint, Mypy,
  and diff checks pass. No full suite or container runs were performed locally.
- Fix is local and uncommitted on branch `2558` for existing PR #2561. Publish
  through the user's external `daf complete` workflow and verify CodeQL on the
  new head; the old-head failure cannot validate this fix. Windows/container
  checks were still pending at the latest inspection. No commits or pushes ran.

## Issue #2558 standalone NuGet V4 and Sonar credentials — 2026-10-19

- Added four bounded bundled secret rules with service attribution and normal
  output redaction. NuGet follows the vendor's separately encoded identifier
  and GUID password; Sonar covers user/project/global-analysis prefixes only.
  Generic assignment rules and external engines are unchanged. Legacy
  unprefixed Sonar and Kong Konnect remain out of scope.
- Positive fixtures are deterministic and unissued. Unit/runner UX regressions
  reproduced the standalone gap before the fix. A committed benign corpus of
  20 build/code/documentation samples plus 200 deterministic identifiers has
  0/220 findings; this is not a population-wide false-positive estimate.
- All 791 related unit/UX tests pass, including both complete affected UX files.
  Ruff, Black (`--target-version py310`), Pylint, Mypy in the uv dev environment,
  and diff checks pass. Three existing UX deprecation warnings remain.
- Updated source/license attribution, TOML docs/counts, changelog, and installed
  scanner canaries in both smoke and fresh-install release-readiness workflows.
  Unit contracts parse YAML and compile the new workflow Python blocks.
- No live credentials, verification requests, dependencies, full suite,
  integration/container runs, live protection controls, commits, or PRs.
  Broader CI/matrix and manual native hook validation remain for CI/operator QA.
- All six issue criteria are checked and DAF notes are updated. Branch `2558`
  is ready for the user's `daf complete` outside this agent session.

## Issue #2554 security pattern research — 2026-10-19

- Completed the October 1–19 priority-source review and all nine scanner
  categories. Prior #2481, #2482, and #2322 are closed. Detailed source citations,
  decisions, completed checklists, and research limitations belong to #2554.
- Created #2558 for standalone NuGet V4/prefixed Sonar token recognition and
  #2559 for IPv6 transition-address destination classification. No detection
  change is shipped by this review. Kong Konnect remains deferred because
  compatible vendor examples do not establish a consistent exact layout.
- Isolated probes used synthetic tokens and explicit scanner configuration,
  without credentials, DNS, HTTP, daemon controls, or hook changes. Sanitized
  observations: `/tmp/opencode/guardian-2554-observations.json`. Scanner-level
  results do not demonstrate live routing exploitability or an empirical
  false-positive rate; those implementation gates remain in the follow-ups.
- Updated both research dates, the OWASP current-edition link, review summary,
  and changelog. Changes are documentation-only on branch `2554`; no tests,
  full suite, integration/container scenarios, commits, or PRs are needed here.
- Posted the completed review and checklists to #2554:
  `https://github.com/RedHatProductSecurity/ai-guardian/issues/2554#issuecomment-6268266376`.
  `git diff --check` passes. The session is ready for the user's `daf complete`;
  keep commits, PR creation, and issue closure in that external workflow.
- Older issue handoffs below are historical and outside this review.

## Issue #2555 support-image terminal CLI pins — 2026-10-15

- Updated OpenCode V1 from `1.18.34` to `1.19.0` in both support Dockerfiles.
  Reviewed the stable release notes and MIT license. Synchronized the container
  README, OpenCode runtime record, version-check fixtures, and manual-report
  expectations; added pin/documentation consistency regressions.
- Codex remains at `0.160.0`. The operator confirmed `0.162.1` has **not yet**
  passed the required OAuth startup, `account/read` workspace-routing, and
  middleware-denial qualification. That work now belongs to linked follow-up
  #2556; do not advance the Codex pin before qualification.
- Isolated credential-free Linux x64 smoke passed for OpenCode `1.19.0`
  (GitHub archive SHA-256, version/help/run-help) and Codex `0.162.1`
  (npm install, version/help/exec-help). No credentials were loaded. Report:
  `/tmp/opencode/guardian-2555-smoke-cagntxvh/smoke-report.json`.
- All 104 tests in `test_cli_version_check.py`, `test_container_scripts.py`, and
  `test_openshell_manual.py` pass. Ruff, Black (`--target-version py310`), Pylint,
  Mypy in the uv dev environment, and diff checks pass. No production Python
  logic changed; no full suite, integration/container scenarios, image builds,
  live protection controls, commits, or PRs ran.
- The live registry check reports both OpenCode pins current and only Codex
  outdated (expected exit 1). Report:
  `/tmp/opencode/guardian-2555-cli-versions.json`.
- Branch `2555` contains uncommitted OpenCode-only changes. Image rebuild/runtime
  smoke remains pending for #2555. Operator Codex qualification and its eventual
  pin update are tracked separately in #2556. Both issues remain open.
- With user approval, renamed/narrowed #2555 to OpenCode only and created #2556
  for Codex. Moved the `openshell-cli-version-update` automation label to #2556
  so future version-health comments follow the remaining Codex update.

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

- Publish the local #2559 CodeQL log correction with `daf complete` outside this
  agent session to existing PR #2562, then verify the new head's checks. Let CI
  validate the remaining matrix/non-unit suites. Keep routing and live
  exploitability unverified rather than treating classification as a network test.
- The following completion tasks are historical and outside #2559.
- Publish the local PR #2561 CodeQL fixture correction through the external DAF
  completion workflow, then verify the new head's checks.
- Complete #2558 with `daf complete` outside this agent session; let CI run the
  remaining matrix and non-unit validation. Older handoffs follow below.
- Complete #2554 with `daf complete` outside the agent session. Implement
  #2558/#2559 in separate sessions with isolated unit/UX and false-positive
  validation; do not treat this research review as either fix being shipped.
- For #2555, rebuild and smoke-test both support images in CI or the operator's
  validation environment before closing the OpenCode-only issue.
- For #2556, obtain the operator's Codex `0.162.1` OAuth/OpenShell qualification
  results before advancing its pin. Host CLI help checks are not image or
  credential-backed qualification; keep the follow-up open until complete.
- The following
  desktop and older handoff tasks are historical and outside #2555.
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
- Branch/issue: `2559` / `RedHatProductSecurity/ai-guardian#2559`.
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
- Current GitHub issue: `https://github.com/RedHatProductSecurity/ai-guardian/issues/2559`
