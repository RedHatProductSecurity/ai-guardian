---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS - ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-11-12 (UTC)

## Issue #2729 CI regression — 2026-11-12

- Fixed the malformed IDE E2E custom-secret fixture: the secret-scanning rule now
  uses only supported fields, separate from the redaction rule. The old shape caused
  schema warnings on hook stdout, obscuring JSON responses and making deny assertions
  appear to allow blocked paths.
- Added the `secret_scanning.additional_patterns` default and its generated-config
  comment to all four built-in profiles. Added parity checks for every profile.
- **Validation:** 51 profile-manager, 147 TOML-pattern scanner, 29 directory-rule,
  35 hook-processing, and 72 redaction unit tests pass. The E2E fixture passes the
  current JSON schema. Ruff, Black, Pylint, project Mypy, and diff checks pass.
  The integration E2E matrix was not run locally per project guidance; CI confirmation
  remains pending.
- Changes are local on branch `2729`; no commit or push was made. **Next:** review and
  complete through the external DAF workflow after CI confirms the E2E matrix.

## Issue #2721 custom secret detection rules — 2026-11-12

- Formalized `secret_scanning.additional_patterns` for user-managed regex rules.
  The schema and shared Console/runtime validator require a unique safe ID,
  `match_type: regex`, valid RE2-compatible regex, and validate optional description,
  keywords, and flags. Invalid entries are skipped individually with value-free
  warnings; bundled rules remain active.
- Added the empty generated-config default, a synthetic example rule, and a
  structured JSON editor on the Secret Scanning Console page. Documented that the
  rules augment bundled detection, require the built-in `toml-patterns` engine, and
  are distinct from output-only `secret_redaction.additional_patterns`.
- **Validation:** 682 related unit/UX tests pass. Ruff, Black (Python 3.10 target),
  error-level Pylint, project-managed Mypy (337 files), and `git diff --check` pass.
  Bare global Mypy still reports the known 14 errors in untouched
  `skill_discovery.py` and `secret_validator.py`.
- Updated issue #2721 acceptance criteria, added the `done` label and progress
  comments, and saved a DAF note. PR #2727 is open from commit `435629c1`.
- **CodeQL follow-up:** PR comment/alert #355 flags dynamic custom-rule diagnostics
  reaching `logger.warning` at `toml_patterns.py:204`. Replaced the dynamic warning
  with a fixed value-free message; detailed entry errors stay in the Console.
  **198** related scanner/engine/UX tests and Ruff, Black, Pylint, project-managed
  Mypy, and diff checks pass. The follow-up is local and uncommitted; the existing
  PR alert remains until an updated commit is analyzed.
- **Next:** user review, publish the CodeQL follow-up if approved, then external
  `daf complete`.
## Issue #2719 tray MCP proactive pause label — 2026-11-12

- The tray's **MCP Proactive** label now follows the configured level for local
  and selected daemon targets, and appends `(daemon paused)` during a temporary
  daemon scanning pause. An explicitly configured `paused` level still displays
  as paused (with the daemon annotation only when that pause is also active).
- Added local unit coverage and expanded the SSH daemon UX contract for running and
  paused targets with both `medium` and configured `paused` levels; each checks the
  displayed label against the selected radio option. Updated CHANGELOG and buglog.
- **Validation:** all **571** tests in `tests/unit/test_daemon_tray.py` and the
  complete `tests/ux/test_user_experience_contract_ssh_daemons.py` pass. Ruff,
  Black (Python 3.10 target), error-level Pylint, JSON validation, and
  `git diff --check` pass. Package-wide Mypy still reports the known 14 errors in
  untouched `skill_discovery.py` and `scanners/secret_validator.py`.
- GitHub issue #2719 has a completed-criteria comment and the `done` label; a DAF
  note is saved. Changes remain uncommitted on branch `2719`; no PR was created.
  **Next:** user review and external `daf complete`.

## Issue #2716 private LLM documentation export — 2026-11-12

- Added a README link to `docs/notebooklm-export.md`, explaining that it is a
  generated single-file documentation compilation users can upload to an
  organization's approved private NotebookLM or another LLM search tool. Clarified
  that the export is generated during releases and should not be edited directly;
  the generated file itself was left untouched.
- Updated CHANGELOG. Verified the export target exists and `git diff --check`
  passes. No tests were run because this is documentation-only.
- All three GitHub acceptance criteria are checked; the `done` label, progress
  comment, and DAF note are recorded. Changes remain uncommitted on branch `2716`.
  **Next:** user review and external `daf complete`.

## Issue #2713 runtime-organized tray sandbox actions — 2026-11-12

- Grouped OpenShell middleware readiness, create, and stopped-sandbox actions in
  an **OpenShell** submenu; grouped runtime-specific container actions under
  **Containers (Docker/Podman)**. Grouped SSH enrollment, alias discovery settings,
  and discovered aliases under **SSH**. Per-sandbox management and unrelated root
  actions remain in place.
- Runtime create shortcuts reuse the complete existing form and preselect
  `openshell` or `container`; the runtime remains editable in the form.
- Added layout, stopped-target placement, and runtime-default unit coverage; updated
  tray test doubles and CHANGELOG.
- **Validation:** 912 affected unit/UX tests pass. Ruff, Black (Python 3.10 target),
  error-level Pylint, package Mypy (336 source files), buglog JSON, and
  `git diff --check` pass. The initial separator-sentinel test failure and the CI
  regression below are recorded in `.wolf/buglog.json`.
- **CI follow-up:** PR #2715 at `ff1f8fc9` failed the Tests matrix because
  `test_discovered_alias_menu_actions_use_pystray_supported_arity` still searched
  the root for a discovered-alias item moved under **SSH**. Updated the test to
  locate the nested item; the complete affected suite passes locally. Other CI
  workflows passed. The remote PR still needs this local fix published and a fresh
  CI run.
- All five acceptance criteria are met. GitHub issue #2713 and DAF notes are
  updated; PR #2715 remains open. The follow-up test fix is local on branch `2713`.
  **Next:** publish through external DAF completion and verify the new CI run.
## Issue #2699 implementation — 2026-11-12

- Added a default-on, command-aware credential scanner for supported curl, wget,
  and PowerShell web-request arguments, separate from password-likelihood
  heuristics. Inline literals follow the configured block/Ask/warn/log-only
  policy; references remain advisory, and incomplete parsing follows policy.
  The policy is global-only. Values are excluded from findings, logs, and MCP
  responses.
- Integrated native pre-tool enforcement, value-free violation handling, config
  templates/profiles/schema, Doctor, Console, MCP capability metadata, and an
  advisory MCP `check_command` result. Added a synthetic CLI smoke case with an
  execution witness, UX contracts, documentation, changelog, and release-readiness
  coverage.
- **Validation:** 557 focused scanner/config/violation unit tests, 492 MCP/REST/CLI
  unit tests, and 43 affected UX tests pass. Ruff, Black (Python 3.10 target),
  error-level Pylint, package Mypy (337 source files), and `git diff --check` pass.
  No real-agent container smoke was run.
- Created follow-up issue [#2717](https://github.com/RedHatProductSecurity/ai-guardian/issues/2717)
  for static analysis of hard-coded credentials flowing into HTTP request code.
  It scopes a Python-first, non-executing source analysis and value-free
  pre-tool findings; implementation remains separate from #2699.
- Created language follow-up [#2722](https://github.com/RedHatProductSecurity/ai-guardian/issues/2722)
  to extend that analysis to JavaScript and TypeScript HTTP request APIs, with
  explicit source-only, value-free, pre-tool enforcement and language/client
  coverage requirements.
- The repository now has open PR [#2718](https://github.com/RedHatProductSecurity/ai-guardian/pull/2718)
  at `b589921c`. Its first CI run failed because an older MCP integration fixture
  used a curl Authorization header now intercepted by the new scanner, and the
  complete violation-guidance UX contract did not classify this private finding as
  intentionally having no copyable snippet. The Performance Check reused the same
  failing integration test; the 102-test subset itself now passes locally in 8.43s
  (101 passed, 1 skipped). Updated both test contracts; 263 affected tests, Ruff,
  Black and diff checks pass. Changes are local and uncommitted; no commit or push
  was made. **Next:** publish the test-only correction and rerun PR CI after approval.

## Issue #2698 implementation — 2026-11-11

- On the existing managed DAF branch `2698`, replaced the shorter GitHub
  stateless-token example with an exact 520-character synthetic JWT-shaped value.
  The test verifies a GitHub Secret Token match spans all 520 characters and that
  the raw token, payload, and signature do not remain in redacted output. Updated
  the class documentation to reflect the completed October 2, 2026 rollout and
  added an Unreleased changelog entry.
- The existing `ghs_` TOML rule passes the full-length regression, so no detection
  rule change was needed. Legacy stateful-token tests remain unchanged.
- **Validation:** all 72 tests in `tests/unit/test_secret_redaction.py` pass;
  Black, Ruff, error-level Pylint, package Mypy (336 source files), and
  `git diff --check` pass.
- Updated GitHub acceptance criteria, added the `done` label and progress comment,
  and saved a DAF note. Changes remain uncommitted on branch `2698`; no commit or
  PR was created.
- **Next:** user review and external `daf complete`.
## Issue #2709 Read the Docs release versions — 2026-11-11

- On the existing DAF branch `2709`, made release verification inspect both the
  final HTTP status and effective URL, so redirects to `latest` do not count as
  versioned-doc success. Inactive/misrouted and unavailable responses now give
  distinct recovery steps and cause a nonzero final result after merge-back, without
  rolling back publication or inviting a full release rerun.
- Documented the dashboard-only SemVer tag activation rule, Read the Docs version
  selector, and manual recovery. README now defaults to `/en/stable/` and explicitly
  identifies `/en/latest/` as tracking `main`; this follows #2708, merged in PR #2710.
- **Validation:** 44 focused release-script tests pass. Full Ruff, Black (Python
  3.10 target), error-level Pylint, package Mypy (336 files), Bash syntax, and
  `git diff --check` pass.
- Updated #2709's acceptance checklist and progress comment; added a DAF note.
  A read-only live check found `/en/v1.21.1/` and `/en/stable/` currently return
  HTTP 404, while `/en/latest/` serves the docs. Dashboard rule and selector status
  remain unverified without project access, so acceptance criteria 1–2 remain open.
  No commit, push, or PR was created.
- **Next:** maintainer configures/confirms **Admin → Automation Rules** as
  **SemVer versions → Tag → Activate version**, then verifies the active tag and
  all three documentation routes. Do not rerun the release script solely for docs.

## Issue #2708 README landing page — 2026-11-11

- Replaced the 663-line README with a 116-line landing page. Prominent links to
  Read the Docs, the source documentation index, and NotebookLM Q&A appear near
  the top; the Google-account requirement is stated. Kept the three-command quick
  start and security disclaimer, and linked concise feature/setup/configuration
  guidance to the existing docs.
- Updated CHANGELOG. All local README link targets exist and `git diff --check`
  passes; tests were not run because this is documentation-only.
- GitHub acceptance criteria are checked and the `done` label/progress comment
  were added. Changes are local and uncommitted on branch `2708`; no commit or PR.
- **Next:** user review and external `daf complete`.

---

## Issue #2701 implementation — 2026-11-11

- Added `--resume` for the required-CI phase in `scripts/release.sh`. The gate
  persists its attempt under Git metadata, keyed to release type/version/mode,
  source branch and SHA. Each workflow receives a unique attempt input reflected
  in its run name; resume verifies exact workflow/source/input metadata and
  uniqueness before reusing runs. Successful runs are reused, active runs awaited,
  only proven-undispatched workflows started, and uncertain dispatches never
  automatically retried.
- Persisted lifecycle transitions gate release mutations and prevent replay of an
  active/completed release. `--resume` rejects changed identity, failed, stale,
  ambiguous, successful-complete and release-lifecycle states. An intentional
  normal invocation starts a distinct attempt after reviewing failed/stale/
  ambiguous results; an active same-identity attempt must use `--resume`.
- Added attempt inputs/run names to the four required workflows, release guidance,
  changelog notes, and interruption/partial-success/stale/duplicate/empty-field
  contract coverage. **53** `tests/unit/test_release_script.py` tests pass.
- **Validation:** Ruff, Black (Python 3.10 target), error-level Pylint, package
  plus helper Mypy (337 files), Bash syntax, buglog JSON and `git diff --check`
  pass. No live GitHub workflows were dispatched. Changes are local on branch
  `2701`; no commit, push, issue update or PR was made.
- **Next:** review the diff and, if approved, complete the normal DAF/PR workflow.

## Issue #2702 implementation — 2026-11-10

- Verified #2700's fix landed on `release-1.21` in merged PR #2703 (merge
  `e9d67cba`, source `23630a78`). Ported the relevant reliability changes to the
  existing `2702` branch: five-sample median redaction timing with warm-up,
  deterministic recovery state setup and empty-directory assertions, and a pinned
  OpenCode V1 no-runtime test. Added the Unreleased changelog entry; excluded the
  release-branch-only `.wolf/STATUS.md` change.
- **Validation:** both focused unit files pass (**191 passed, 8 skipped**); the
  performance and cancellation tests each pass five repeated runs. Ruff, Black
  (Python 3.10 target), error-level Pylint, package Mypy (336 source files), and
  `git diff --check` pass. This is local Linux/Python 3.14 validation; Windows CI
  remains pending.
- No commit or PR was created. **Next:** create the PR toward `main` with the user,
  then confirm the CI matrix. The exact process that originally initialized the
  recovery state directory remains unidentified; the fixture now establishes it
  before publishing test-home overrides and fails if unexpected files exist.

## Release script post-release merge conflict guard — 2026-11-10

- Published `v1.21.1` and merged `release-1.21` into `main` in commit
  `ade81361`, retaining the `1.22.0-dev` development versions.
- Phase 8 now defers the merge commit until resolution. The new resolver
  sets version-only conflicts to the next dev version, combines main's
  `[Unreleased]` changelog with the release section, keeps main's OpenWolf status,
  and stops for unexpected or broader conflicts.
- Added shell-contract tests and temporary-Git merge regressions. Changes are
  currently uncommitted on `main`.
- **Validation:** 46 related unit tests pass. Ruff, Black, Pylint, Mypy, Bash
  syntax, JSON validation, and diff checks pass.
- **Next:** review the diff; script changes remain uncommitted and unpushed.

---

## PR #2694 review and CI follow-up — 2026-11-10

- Original CI run `42737676198` failed across the Python matrix for two causes:
  the SSH worker test patched `stop.wait` although the retry loop uses
  `retry_now.wait`, so it never exited; and the real pystray import selected an
  Xorg/GTK backend in headless Linux. The Tk sandbox submit gate also ignored
  `enabled_when` for required checkboxes, preventing Codex submission when Claude
  terms were disabled.
- Fixed the SSH test to stop via the retry event and forced pystray's dummy backend
  for the menu contract. Updated the Tk gate to associate required checkboxes with
  field names, ignore disabled controls and refresh on dependency changes. Added
  unit and UX regressions. Also corrected the published-version note in
  `docs/UBUNTU_VM.md` and added docstrings to the new source helpers.
- Follow-up `0769f142` fixed those issues, but CI run `42742503987` found a second
  headless pystray test defect in all five Ubuntu Python jobs. The test replaced
  `tray.app.pystray`, but `menu_builder` and `plugin_runner` retained their own
  import-time `None` references. Fixed by injecting the dummy-backend pystray module
  into all three menu-building modules; with `DISPLAY` unset, all 270 affected unit
  tests now pass locally.
- Pushed `09e2ee26` to `fix/remote-ssh-https-enrollment`; PR #2694 remains open:
  https://github.com/RedHatProductSecurity/ai-guardian/pull/2694. Updated the PR
  description with template sections and test evidence. OpenWolf status commits
  `a338ab70` and `19b41575` are present on the branch.
- **Validation:** 270 affected unit tests and 95 affected UX contracts pass.
  Ruff, Black, Pylint, and project-environment Mypy (336 source files) pass.
  Latest GitHub run `42744431892` is in progress; its initial Ruff, Mypy and scanner
  version checks pass. **Next:** wait for the latest CI matrix before merging.

---

## Remote 1.22-dev reinstall and SSH/HTTPS retest — 2026-11-10

- User completed a full remote AI Guardian reset, cloned branch
  `fix/remote-ssh-https-enrollment`, installed its editable source in a fresh venv,
  and generated a new TLS identity. The fresh daemon initially served HTTP on 63152.
- HTTPS startup failure root cause: the Console had saved a trailing space in both
  `cert_file` and `key_file`. The certificate/key pair, SAN, system clock, ownership
  and permissions were valid. User trimmed the paths; `daemon status` then confirmed
  `REST API: available (HTTPS, port 63152)`. Added save-time stripping of outer
  whitespace from TLS paths and trust fields, with regression coverage.
- User removed the old workstation test key/profile, created a fresh SSH identity,
  restored the `guardian-itdove-rasp` SSH alias, verified BatchMode authentication,
  and successfully paired in the tray. SSH alias and TLS SNI `guardian-lab.test` stay
  separate. Stopping/uninstalling the remote daemon does not remove the workstation
  saved pairing; added that distinction and removal steps to troubleshooting docs.
- Verified the consent dialog uses `run_form_flow` → shared `run_modal` →
  `ui_provider_order`. On Linux auto mode, required-checkbox forms skip Native
  (zenity/KDialog cannot gate submit) and try Tkinter then NiceGUI; macOS/Windows may
  use Native first. Only proven pre-display failure permits fallback.
- Corrected quick-start and remote lifecycle examples to use `daemon start -b` when
  a shell is needed for status/follow-up commands. Scoped HTTPS save and local save
  guidance are also included in the branch.
- **Published:** follow-up commit `8db5556d` pushed on
  `fix/remote-ssh-https-enrollment`; PR #2694 is open against `main`:
  https://github.com/RedHatProductSecurity/ai-guardian/pull/2694. `.wolf` handoff
  files remain local and were not included in the commit.
- **Validation:** 65 related HTTPS/config unit and UX tests pass; SSH unit/UX and REST
  API/Web-service focused suites passed during implementation. Ruff, Black (Python
  3.10 target), error-level Pylint, package Mypy (336 files), and diff checks pass.
  **Next:** wait for PR CI/review. The remote editable clone remains at the earlier
  branch commit until pulled; fetch/pull if the user wants to test save-time trimming
  there. Do not release from this feature branch.

---

## Issue #2689 — 2026-11-08

- Removed generated `docs/notebooklm-export.md` from active release-reference
  synchronization/checking. Historical mentions remain intact; source references
  are still checked. Added regressions for untouched generated history and stale
  active references.
- The fix was already present on `main` at `83e4a6e`. Backported only the fix,
  tests, and changelog to `release-1.21` in PR #2691 (`06421f5a`), which passed all
  CI checks and merged as `505a5d4b8c857de668293b92dd4eff7824d5cf6a`. Closed
  superseded PR #2690.
- **Validation:** 108 related unit tests pass locally. PR CI passed tests across
  supported Python/Windows versions, lint/type checks, integration tests, and the
  multi-architecture Buildx/QEMU validation. Release reference check passes for
  1.21.0.
- Dispatched Build Container Image from `release-1.21` with `image_tag=1.21.0`.
  Run `42532341445` succeeded and pushed both tags. Quay manifest inspection
  verified `linux/amd64` and `linux/arm64` for:
  - `quay.io/redhatproductsecurity/ai-guardian:1.21.0`
  - `quay.io/redhatproductsecurity/ai-guardian-openshell:1.21.0`
- Closed issue #2689 with all acceptance criteria checked. The unrelated local
  `main` checkout was preserved; release work remains in the isolated local
  worktree `/tmp/opencode/ai-guardian-2689-release-backport`.
## Issue #2685 implementation — 2026-11-08

- Implemented on the existing managed DAF branch `2685`. `scripts/release.sh`
  now dispatches and awaits Release Readiness, Tests, Lint, and Integration Tests
  in default preview, explicit `--dry-run`, and `--execute` modes. Each new run
  is correlated against the captured source branch/commit and dispatch event;
  missing, ambiguous, failed, or mismatched results exit nonzero before release
  file preparation or other release mutations.
- Moved execute-mode changelog generation and release-helper validation behind
  the CI gate. Preview explicitly reports GitHub Actions dispatch as its one
  intentional external side effect; it does not make release changes.
- Added safe `workflow_dispatch` entry points to Tests and Lint. Integration
  Tests accepts `release_validation=true` to skip scanner-version issue
  automation while retaining its normal behavior for other manual dispatches.
  Release Readiness remains the only invocation for Smoke Tests, Scenario Tests,
  and Container Build Validation.
- Updated `RELEASING.md`, CHANGELOG, and release-script contracts. **31 focused
  tests pass**; Black, Ruff, error-level Pylint, package Mypy (336 source files),
  Bash syntax, and diff checks pass.
- No live GitHub workflows were dispatched and no commit or push was made.
  Posted the completed acceptance checklist on issue #2685 and added the `done`
  label. **Next:** user review and external `daf complete` on branch `2685`.

## Issue #2675 implementation — 2026-11-07

- On managed DAF branch `2675`, split the `ide-hook-e2e` OpenCode coverage into
  separately named `opencode-v1` and `opencode-v2` matrix variants; all other IDE
  variants remain one each. Each job passes a generation selector to pytest, which
  collects only the matching fixed-version plugin/MCP contract. The generic
  ambient OpenCode setup test is skipped, preventing V2 from silently falling back
  to V1. Shared OpenCode unit/plugin-runtime checks run only once.
- Added workflow-to-collection contract coverage, updated the job-name assertion
  and Unreleased changelog. GitHub acceptance criteria were checked and a progress
  comment was added.
- Release Readiness run `42383624100` failed only at the registry parity step:
  its embedded parser expected the old `matrix.ide` sequence and raised
  `IndexError` after the workflow moved to `matrix.include`. Both OpenCode E2E
  variants passed in that run. Replaced the duplicate parser with the tested
  registry-contract pytest file, installing pytest in the setup job and asserting
  that invocation in the test. The focused file now has **50 passing tests**.
- **Validation:** 150 `test_agent_cli_test.py` tests pass. OpenCode E2E passes for
  V1 and V2 separately and in unfiltered local mode (one expected generic-path
  skip). Full Black, Ruff, error-level Pylint, package Mypy (336 source files),
  and `git diff --check` pass.
- The matrix implementation is committed/pushed as `26b8ebeeb`; the parity-step
  follow-up is local and uncommitted. **Next:** validate the follow-up and rerun
  Release Readiness after publication; no new run has started yet.
## Issue #2682 implementation — 2026-11-07

- Continued on the existing DAF branch `2682` and rebased its two commits onto
  `origin/main` at `1159bc57`. The rebased commits are `4319203a` and `753c5883`.
  Open PR #2684 still points to pre-rebase commit `fc174fb9`; it has not been
  force-updated. No GitHub issue state or DAF completion was changed.
- Audited tray-launched Tk windows and added shared one-shot presentation in
  `ui/modal.py`: withdrawn layout, temporary topmost hint, focus after mapping,
  then clear the hint and deiconify/refocus once after 200 ms. Applied it to tray
  messages, proactive/setup/snooze prompts, plugin/SSH forms, Pause and sandbox
  forms, progress, logs and confirmations. Support review retains its equivalent
  isolated flow.
- Kept native/browser providers unchanged. File/directory pickers remain a special
  case: their Tk owner must not refocus while an OS panel owns focus. Added unit and
  UX coverage and expanded the modal provider/manual verification guidance.
- CI run `42389159624`: six workflows passed; only the Tests workflow failed, with
  the same three About grab-order assertions failing in all eight Python/OS matrix
  jobs. The fix moves optional grab acquisition into the post-map focus callback
  to retain the existing About event order. The 1,151 related unit/UX tests and
  static checks passed before rebase; they have not been rerun since rebasing.
- **Validation:** 1,151 related unit tests and complete modal, support, About, SSH
  and Pause UX contracts pass locally. Ruff, Black (Python 3.10 target), error-level
  Pylint, package Mypy (336 files), and `git diff --check` pass. One existing
  PyGObject deprecation warning remains.
- **Pending:** update the PR branch after approval, rerun CI, and perform actual
  visual verification on the reporter's KDE/Plasma session; distro/version and
  X11/Wayland details were not provided. No push was made during this rebase.

## Issue #2674 implementation — 2026-11-07

- Continued the managed DAF `open` session on existing branch `2674` in the real
  workspace. Preserved the DAF-managed OpenCode title; no branch change or commit.
- Added shared supported-CLI version detection and a non-blocking pre-1.0 advisory
  for successful setup, including non-interactive and JSON setup. Doctor reports
  the detected version and advisory in human and JSON output while leaving hook
  health/status unchanged. Unavailable, unparsable, and >=1.0.0 versions do not
  produce the advisory. Rechecked current upstream stable examples; no dated
  version snapshot was added to user docs.
- Documented the distinction between AI Guardian integration coverage and
  upstream CLI stability in `docs/AGENT_SUPPORT.md` and `docs/TROUBLESHOOTING.md`,
  added the README feature link and Unreleased changelog entry, and covered setup,
  doctor, JSON, and version-boundary behavior.
- **Validation:** 634 related unit/UX tests pass. Ruff, Black (Python 3.10 target),
  error-level Pylint, package Mypy (336 source files), and `git diff --check` pass.
- Updated all five GitHub acceptance criteria in a progress comment, added the
  `done` label without replacing existing labels, and saved a DAF progress note.
- **Next:** user review and external DAF completion. Changes are local and
  uncommitted; no push or PR was created.

## Issue #2672 implementation — 2026-11-07

- Continued on the existing `2672` branch. Added independent desktop/email
  preferences for each supported violation type; unspecified types default to
  desktop on and email off. The notification outbox now carries a safe violation
  type, including a SQLite migration for existing outboxes.
- Preserved legacy `enabled: false` and channel intent at runtime and on Console
  migration. Email selection is rejected unless recipient/TLS SMTP/auth settings
  are usable; remote fallback joins older outbox events to curated records by ID
  and fails closed on ambiguous legacy categories.
- Replaced the Console master/channel controls with a per-type matrix, updated the
  schema, generated config, all profiles, example, help, docs, release-readiness
  assertion and CHANGELOG. Saving a recipient refreshes readiness-dependent email
  controls. OpenWolf buglog records that UI readiness fix.
- **Validation:** 543 directly affected unit/UX tests pass (one existing PyGObject
  deprecation warning). Ruff, Black (Python 3.10 target), error-level Pylint,
  package Mypy (335 source files), JSON/workflow validation and `git diff --check`
  pass. No live Console/SMTP delivery verification was run.
- Changes remain local and uncommitted; no GitHub issue status/comment, commit,
  push or PR was changed. **Next:** user review; preserve branch `2672`.

## Issue #2668 implementation — 2026-11-07

- Added a clearly labeled, copyable expected sandbox name with clipboard success
  and failure feedback in the isolated Tkinter and NiceGUI deletion dialogs. Copy
  leaves the dialog open; exact-name confirmation and cancellation remain intact.
- The confirmation uses the shared rich-form dispatcher, so native one-field
  prompts are ineligible. Updated the modal capability matrix and manual checks.
- Marked all six GitHub acceptance criteria complete, applied the `done` label,
  added a progress comment, and recorded a DAF note.
- **Validation:** 259 related unit tests and all 19 modal UX contract tests pass.
  Ruff, Black (Python 3.10 target), error-level Pylint, package Mypy, JSON parsing,
  and `git diff --check` pass.
- Changes remain local and uncommitted on branch `2668`; ready for user review and
  external `daf complete`. Manual desktop clipboard verification was not run.

## Issue #2667 KDE tray sandbox form focus — 2026-11-06

- On the existing managed DAF `open` session and branch `2667`, added a one-shot
  Tk focus restoration 200 ms after sandbox-form startup. It clears the temporary
  topmost hint first, checks that the window still exists, and does not schedule
  recurring focus grabs. Provider dispatch and complete form controls are unchanged.
- Added a unit regression and modal UX contracts for the KDE handoff, startup-only
  fallback, cancellation/post-display terminal behavior, headless handling and the
  NiceGUI field path. Updated `docs/MODAL_PROVIDERS.md` and CHANGELOG.
- Validation: `tests/unit/test_sandbox_tray.py` **195 passed**; complete affected
  modal/sandbox/monitor/SSH UX contracts **102 passed**; Ruff, Black (py310),
  error-level Pylint, package Mypy (**335 source files**) and `git diff --check`
  pass.
- Manual verification on the reporter's KDE session remains pending because the
  distro, Plasma version and X11/Wayland session were not provided. Changes are
  local and uncommitted; preserve branch `2667` and use external `daf complete`.
## Issue #2671 implementation — 2026-11-06

- Continued managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2671` on existing branch `2671`.
- Default Docker/Podman and OpenShell images omit the GitGuardian CLI; derived
  images opt in with `INCLUDE_GITGUARDIAN=true`. Local engines remain available.
  The executor parses findings from ggshield's `--exit-zero` JSON output and
  treats nonzero, invalid, and error-shaped results as incomplete scans. Failures
  are retained across first-match, any-match and consensus; consensus thresholds
  are unchanged. Safe cloud failure/readiness warnings follow `on_scan_error`.
- Updated container/scanner docs, CHANGELOG, unit tests and the complete scanner
  warning UX contract. Added DAF progress note and GitHub progress comment.
- The implementation was committed as `1e93f38e` on branch `2671` and pushed to
  PR #2677. PR CI failed all eight Python matrix jobs on one outdated assertion:
  `FirstMatchStrategy` now returns attempted engine failures, not the old generic
  no-scanners message. CodeQL also flagged the detailed scanner warning printed to
  stderr.
- Follow-up changes update the test to assert the retained engine error, use fixed
  engine labels, and print only a fixed incomplete-coverage summary to stderr;
  the returned hook warning remains actionable and credential-safe.
- The branch was rebased locally onto `origin/main` at `90a02be2`. Conflict
  resolution preserved both the main-branch KDE entry and #2671's changelog/status
  entries. The user authorized committing and pushing the rebased history to
  PR #2677; publication uses a lease-checked branch update.
- **Post-rebase validation:** 430 related tests pass, 1 skipped, with 3 existing
  dependency deprecation warnings. Ruff, Black (Python 3.10 target), error-level
  Pylint, package Mypy, and `git diff --check` pass.
- CodeQL check `128145447260` reported four clear-text findings for scanner
  messages, positions and snippets. The first follow-up removed those fields, but
  check `128166162972` on `2fb58beb` still flagged a list-derived finding index and
  raw `finding.file_path` in terminal output. The current local fix keeps the
  actionable path: it tracks path metadata independently, displays paths relative
  to the scan root, and substitutes `$HOME` for home prefixes on external absolute
  paths. No CodeQL exception was added.
- Added unit coverage for relative and `$HOME` paths and updated the scan-output UX
  contract. **84 related tests pass**; Ruff, Black, error-level Pylint, package
  Mypy, JSON validation and diff checks pass. The follow-up was committed and
  pushed, but CodeQL check `128178708709` on `b0718c82` reported two
  uncontrolled-data path-expression alerts on `Path.resolve()` in the display-path
  helper.
- Replaced filesystem-resolving calls with lexical `os.path.abspath()` to preserve
  relative paths and `$HOME` display without dereferencing user-controlled paths.
  Added a lexical `..` path regression. **85 related tests pass**; Ruff, Black,
  error-level Pylint, package Mypy, JSON validation and diff checks pass. The fix
  is committed and pushed to PR #2677; fresh CI/CodeQL checks are running.
- **Next:** review the fresh CodeQL result. No container image build or live cloud
  scan was run.

## Issue #2669 implementation — 2026-11-06

- Continued managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2669` on its existing issue branch `2669` in
  the real workspace. Preserved the pre-existing local OpenWolf edits; no branch
  sync or branch change applied.
- The Violations page now has a live, case-insensitive **Filter by daemon** text
  search plus a separate exact-source selector. Exact identity keys continue to
  distinguish same-named mirrored sources. Options show Running, Paused, Offline,
  or Unknown from refreshed daemon status; undiscoverable historical sources stay
  Unknown. Refresh preserves selected filters, and clearing the text search resets
  the source selection without changing type/directory filters.
- Updated the complete affected violation-mirroring UX contract, related unit
  coverage, `docs/VIOLATION_LOGGING.md`, and CHANGELOG. All seven issue acceptance
  criteria are checked in GitHub; added the `done` label, a progress comment and a
  DAF note.
- **Validation:** 9 directly affected unit/UX tests pass. Full Ruff, Black
  (Python 3.10 target), error-level Pylint, targeted Mypy, JSON validation for the
  buglog, and `git diff --check` pass. Full-package Mypy still reports 14 errors in
  untouched `skill_discovery.py` and `scanners/secret_validator.py`.
- Changes remain local and uncommitted; no commit, push, or PR was created.
  **Next:** user review and external `daf complete`.

## Codex PreToolUse denial smoke correction — 2026-11-06

- Release Readiness run `42151399090` passed the exact isolated Codex hook-scope
  preflight but failed tool cases against pre-fix commit `57a7bb39`: expected
  SSRF/config-exfil findings were logged, yet PostToolUse ran and output cases had
  no execution witness. This distinguished the failure from the earlier hook-trust
  issue.
- Current Codex hook docs and parser require a non-empty
  `hookSpecificOutput.permissionDecisionReason` for
  `permissionDecision: "deny"`. `CodexAdapter` now adds the existing sanitized
  violation label for PreToolUse blocks. Clean responses remain
  `{}`; no other adapter, policy, trust state, or smoke assertion changed.
- The uncommitted root-vs-subcommand flag-position probe was removed: the known
  `codex exec --dangerously-bypass-hook-trust` syntax passed scope preflight, and
  the probe addressed the stale-image false lead rather than this deny-format bug.
- Investigated Codex 0.167 hook trust: trust state is a per-hook `trusted_hash`
  under `CODEX_HOME/config.toml` `[hooks.state]`, keyed by source path, event,
  matcher-group index and handler index; Codex recomputes normalized hook identity
  hashes before dispatch. Official docs expose `/hooks` review, not a supported
  `codex hooks trust approve` CLI. The smoke already uses the one-invocation trust
  bypass after exact source validation, and its PreToolUse/PostToolUse deltas show
  hooks ran. Trust is not the remaining tool-execution failure; do not bake
  unsupported/persistent hook hashes into the image.
- Validation: 252 adapter unit tests, 35 hook-processing tests, 148 runner unit
  tests, and all 32 Codex + smoke UX tests pass. The latest diagnostic changes pass
  301 runner/provider/smoke-UX tests. Ruff, Black (py310), error-level Pylint,
  package/script Mypy, and `git diff --check` pass. A current-source Podman
  Codex smoke confirmed the denial fix (all five denial cases pass) but still
  failed the three output-tool execution witnesses. The second run again showed
  tool offers and pre/post hooks but no execution witness or `command_execution`
  item in stdout. The third run found three `error` items and one `agent_message` in
  each output-tool case, with no command event. The runner now classifies those
  error messages into fixed labels only (never emits error text), in addition to
  allowlisted event/item counts and numeric command status/exit codes. The fourth
  through sixth runs still fail the three output-tool execution witnesses. The
  sixth includes the expanded fixed-label classifier but again reports one
  unresolved-tool and two other errors, so error-message matching has not narrowed
  the cause. Seventh smoke confirms Codex was offered `exec_command`, with its
  documented `cmd` string argument shape, but still fails with the same events and
  fixed error categories. Added fixed-label counts for function-call outputs,
  whether their IDs correlate to an issued tool, and output value shape; no payload
  values are retained or printed. Eighth smoke shows one output for a known
  function-call ID, but its value is a string; no output text is retained. Ninth
  smoke narrows the output to `policy_or_sandbox`, still without execution. Source
  comparison then found the mock marked function calls `completed` in
  `output_item.added` while also streaming arguments; Codex's own fixtures complete
  function calls at `output_item.done`. The mock now uses an `in_progress` item with
  empty arguments, streams the deltas, then completes the item. Tenth smoke still
  fails all three output-tool cases with the same `policy_or_sandbox` function
  result category and no execution witness; the stream correction was not
  sufficient. Eleventh smoke narrowed the output to `permission_denied`; the
  twelfth categorized it as `permission_denied_bwrap`. The thirteenth smoke still
  failed after the legacy-Landlock CLI flag with `sandbox_reference`; Codex 0.167's
  Linux sandbox requires Bubblewrap for this filesystem policy and app-server
  socket isolation, so the flag was removed.
- The user authorized matching the regular rootless Podman profile, without
  changing smoke evidence or Codex `workspace-write`. Four current-source retries
  removed the smoke-only capability drop/`no-new-privileges`, matched
  `--userns=keep-id` plus the image's non-root user, and used Podman's default
  network. All still passed the five denial cases and `allowed` but failed all
  three output-tool execution witnesses with `permission_denied_bwrap`.
- A retained failed sandbox reproduced the actionable error with
  `CODEX_HOME=/sandbox/.codex codex sandbox /bin/true`:
  `bwrap: Can't mount devpts on /newroot/dev/pts: Permission denied`. Nested
  user/mount/pid/net/ipc/uts namespace creation and a tmpfs mount succeeded in
  that same container, while a devpts mount failed. Host Podman reports Fedora 44,
  rootless, AppArmor disabled, SELinux and seccomp enabled with the default
  seccomp profile. This narrows the failure to devpts mounting but does not
  identify whether SELinux, seccomp or another kernel/container rule denies it.
  No security policy was changed. The retained container and its temporary files
  were removed after diagnosis.
- Added a fixed, privacy-safe local smoke message for the aggregate
  `permission_denied_bwrap` result, linking to `docs/CODEX_SANDBOX_RUNTIME.md`.
  The failing case remains failed; no raw error is printed and no sandbox or
  isolation assertion is weakened. The doc is indexed in docs/README.md and MkDocs.
- Focused adapter/runner/firewall/provider tests and both complete affected UX
  contracts: **580 passed**. Ruff, Black (py310), error-level Pylint, and
  project-managed `uv run --extra dev mypy` pass. Bare global Mypy still reports
  the known 14 errors in untouched `skill_discovery.py` and `secret_validator.py`;
  the project-managed checker reports no issues. `git diff --check` passes.
- Pushed branch `2662` at `d181d933` (commits `3e050a75` and `d181d933`); local
  `.wolf` records remain excluded. Release Readiness run `42229172707` completed:
  only the Container Images job failed. Codex passed five denial cases and
  `allowed`, but failed `clean_tool`, `tool_output_secret`, and `tool_output_pii`
  because the command item ended failed (exit 1) and no execution witness was
  recorded. Aggregate tool output was `permission_reference`; the event summary
  had one `unresolved_tool` and two `other` errors. Pre/post hooks and a tool offer
  were recorded. The raw Codex message is intentionally unavailable, so this does
  not establish the exact cause and must not be conflated with local Podman's
  `permission_denied_bwrap`/devpts failure.
- Updated all Release Readiness job titles to describe their checked scope. Split
  Codex, Gemini, OpenCode V1, Pi, OpenCode V2, and consent-gated Claude into named
  steps. Each continues after a prior smoke failure only when the shared smoke
  prerequisites succeeded and the run was not cancelled; at that commit any
  failure still failed the job. OpenShell image checks also continue after a CLI
  smoke failure. The later temporary Codex-only exception is documented below.
  Validation: **199** runner/workflow and IDE-registry unit tests pass; Ruff,
  Black (py310), and `git diff --check` pass. Committed the workflow/changelog/test
  edits as `db39a986`, pushed `2662`, and dispatched Release Readiness run
  `42234852481`. It completed with the Real CLI Smoke Matrix failing; other jobs,
  including container scenarios and OpenShell image checks, passed. All five named
  CLI steps ran; each passed the five deny cases and allowed prompt, but failed
  `clean_tool`, `tool_output_secret`, and `tool_output_pii` without an execution
  witness.
- Source-level diagnosis: the host runner created an empty workspace with default
  `0755` permissions but did not pre-create `.agent-cli-smoke-results`. The mock
  tool creates that directory inside the bind mount, while the image runs as
  `sandbox` UID 1000. If host and container UIDs differ, the container can traverse
  but cannot create the witness directory. This explains the shared Docker-runner
  signature; private raw CLI errors were not retained, so a new Actions run is
  still needed to qualify the diagnosis/fix. The local Podman `permission_denied_bwrap`
  devpts failure remains separate and unresolved.
- Local fix: pre-create only the disposable witness directory and grant POSIX
  write/search (`0733`) there; keep the workspace non-writable to other users and
  its temporary parent private. The red lifecycle test failed before the setup
  change, then all **315** related runner/provider/UX tests passed. Ruff, Black
  (py310), Pylint, script Mypy, and `git diff --check` pass. This code/test/changelog
  fix was committed as `3f9fa331`, pushed to `2662`, and Release Readiness run
  `42244579465` was dispatched and completed with Codex still failing (details
  below). OpenWolf state remains uncommitted.
- Follow-up run `42244579465` is complete. The witness-directory change qualified
  the other four CLI smokes: Gemini, OpenCode V1, Pi, and OpenCode V2 all passed,
  as did OpenShell image checks and the other readiness jobs. Codex still passed
  REST, exact hook-scope preflight, five denial cases, and allowed prompt, but its
  three output-tool cases failed without an execution witness. Aggregate Codex
  evidence again reports a tool offer, pre/post hooks, one
   `function_call_output_category_permission_reference`, three error items
   (`unresolved_tool: 1`, `other: 2`), and a failed command execution with exit 1.
   Raw error text was not retained. This confirms the workspace-permission fix for
   the four non-Codex clients but does not diagnose Codex or establish that its
   failure is the same as local Podman's Bubblewrap/devpts denial. Keep the Codex
   smoke result failed and unqualified until execution evidence is present.
- The user authorized a temporary release exception for only the Codex smoke step.
  The workflow now uses step-level `continue-on-error` and adds a warning plus job
  summary when `steps.codex_smoke.outcome` is failure; this allows release readiness
  to continue but does not claim Codex passed. No job-level exception was added;
  all other CLI/OpenShell failures, prerequisites, and cancellation behavior remain
  blocking. The workflow contract test now enforces the narrow exception and report.
  All **150** tests in `tests/unit/test_agent_cli_test.py` pass; Black, Ruff and
  `git diff --check` pass. Committed the workflow/docs/changelog/test changes as
  `48edef4e`, pushed to `2662`, and dispatched Release Readiness run
  `42252905253`; it completed successfully. The Real CLI Smoke Matrix job passed;
  Codex's smoke itself still failed `clean_tool`, `tool_output_secret`, and
  `tool_output_pii` with no execution witness and the prior aggregate
  `permission_reference`/failed-command evidence. The report step emitted the
  warning and job-summary exception text. Gemini, OpenCode V1, Pi, OpenCode V2,
  OpenShell checks, and all other readiness jobs passed. This unblocks the workflow
  but does not qualify Codex. OpenWolf state remains uncommitted.
- Preserve Codex `workspace-write`, approval, firewall, rootless profile,
  admin-capability gate, hooks, execution witness, raw-output checks and clean exit.
  Do not switch to `danger-full-access`, install setuid bwrap, unconfine AppArmor,
  or change seccomp/SELinux policy without authorization. Next: continue Codex
  diagnosis using privacy-safe evidence only; preserve the separate Codex-vs-local
  Podman diagnosis. Upstream Codex issue #35547 is related; do not open a duplicate.
  The local explanation remains at
  `/home/itdove/Downloads/ai-guardian-codex-smoke-explained.md`.

## Codex Release Readiness hook-trust fix — 2026-11-06

- The user explicitly authorized Codex's invocation-only
  `--dangerously-bypass-hook-trust` for this disposable local-mock smoke; do not
  persist trust state or relax evidence. The suggested
  `codex hooks trust approve --source ...` command is not in the official CLI
  reference, so it was not run. Official docs describe `/hooks` for interactive
  review and the one-shot flag for automation that vets sources.
- Smoke creation now pins a dedicated `/sandbox/.codex`. Before starting the mock
  or agent, the runner requires that the installed CLI exposes the flag, plugin
  inventory is valid and empty, `hooks.json` exactly matches the canonical
  AI Guardian hook manifest, and project/system/inline/plugin sources are absent.
  Fail closed on any uncertainty; no persisted trust or approval changes.
- All existing native prompt/tool hook, actual execution, raw-sensitive-output,
  clean-result and zero-exit checks remain mandatory. The flag appears only on the
  Codex invocation.
- Validation: 145 runner unit tests and all 28 smoke UX contracts pass; Ruff,
  Black (py310), error-level Pylint, package/script Mypy and `git diff --check`
  pass. Commit `e57fdc1b` was pushed to `origin/2662`.
- Release Readiness run `42150134386` was superseded by `42151399090`. The latter
  confirms exact hook scope but predates the Codex denial-response correction above;
  neither run qualifies that fix.

## Current Release Readiness Docker REST preflight — 2026-11-05

- Release Readiness run `42095872537` failed on both attempts in
  `Container Images (real-agent smoke checks)`, before Codex cases. The daemon IPC
  and in-container REST health were healthy, but `docker port` returned no host
  binding (`host_port=0`); the runner treated the missing publication as fatal.
- Added a fail-closed Docker-only fallback for Linux local Unix-socket contexts:
  inspect the exact smoke network's private IPv4, probe daemon health without
  redirects/proxies, then require authenticated stats. Reject global/non-private
  addresses, Docker remote contexts and host/context overrides. No network,
  firewall, trust, or egress policy changed; Podman remains on its published-port
  path.
- All **160** directly affected unit and complete smoke UX tests pass. Ruff,
  Black (py310), error-level Pylint, package/script Mypy and diff checks pass.
  The first script Mypy run caught an optional address type; an explicit JSON type
  guard corrected it. No local container/runtime reproduction was performed.
- At the user's request, committed the five code/test/doc files as `87f23706` and
  pushed branch `2662`; remote SHA was verified. Release Readiness was dispatched
  as run `42127127572` against that exact commit. The run failed only at the
  container real-agent smoke job; the other listed jobs passed. Crucially, the new
  Docker route worked: internal health and authenticated host stats both passed.
  Codex then recorded no hook events or violations; its two sensitive-output probes
  reached the mock and failed closed. This is consistent with the previously
  verified untrusted native Codex hooks, not a REST regression. Do not change trust
  or weaken assertions. Docker Desktop/remote contexts and a full Codex smoke pass
  remain unqualified.
- The PR Test matrix on `87f23706` also failed all eight OS/Python jobs on one
  contract: `test_registered_hook_adapters_cover_response_contract[gemini]`.
  Registry metadata inherited `post_output_transform=True`, contradicting the
  already-implemented native AfterTool refusal and UX contract. Set it explicitly
  false, documented the platform contract, and added a metadata regression. All 54
  registry/Gemini unit+UX tests and static checks pass. Pushed as `b5570cd3`.
- PR #2670 checks are green on `b5570cd3`, including all eight Python/OS matrix
  jobs, linters, scenarios, integration tests, Buildx and docs.
- Release Readiness run `42136972874` attempt 1 had a transient minimal-scenario
  base-image fetch failure (curl exit 35, connection reset while downloading
  OpenCode). The job-only retry on attempt 2 passed. Container real-agent smoke is
  the sole remaining failed job: Docker internal health and authenticated host
  REST pass, but Codex records no hook events/findings and sensitive output reaches
  the local mock. Do not change trust or weaken evidence assertions; no source
  change is indicated by the transient image-fetch failure.

## Issue #2662 implementation — 2026-11-04

### Current Gemini / Pi native smoke qualification — 2026-11-05

- **Authorization expanded:** user selected "Fix both (Recommended)" for shared
  Gemini native-output scanning/fail-closed refusal and Pi lazy-first-transcript
  lifecycle fixes. Subsequently selected "Include Pi fix (Recommended)" for its
  exact lowercase native-shell mapping, regressions and full Pi retry. The user
  then explicitly requested commit/push: **published as `0e87601b` on `origin/2662`**.
  All 14 source/test/doc files are committed; local OpenWolf records stay excluded.
- Initial standard-image runs (`e0dbea2f7f`) were Gemini **7/9** and Pi **3/9**.
  Gemini's `tool_response.llmContent` was not extracted; its AfterTool consumer
  ignores `updatedToolOutput`. Pi advertises a session path before persisting the
  first assistant; initial `getsize()` raised FileNotFoundError before reader
  handling. These are confirmed shared integration defects, not auth/network.
- Implemented string/structured Gemini extraction preserving real text-part
  boundaries; unsupported sanitization now returns native `decision: deny`, not
  best-effort replacement or appended warnings. Pi initializes expected absent
  first history at byte zero without fabricating a file, scans eventual content,
  preserves existing baselines and other I/O scan-error handling.
- Fresh standard fixed-source image `localhost/ai-guardian-agent-cli-smoke:fb10d7b60c`
  was explicitly reused for both matrices: **Gemini 0.67.0 9/9 PASS; Pi 0.86.0
  7/9 PASS.** Both clients passed container and authenticated published-host REST
  plus firewall setup; both retry sandboxes were automatically removed. Gemini
  sensitive PASS proves native refusal/containment, not sanitized-result delivery.
- Remaining Pi SSRF/config cases recorded post-tool events and no findings.
  Focused red regressions confirmed native `bash` was not canonical `Bash`, so
  shell checks were missed. Added only the exact mapping in `hook_adapters/pi.py`;
  custom/MCP names remain unchanged. Both real prepared-policy command scanner
  regressions now deny and log their expected categories; canonical permissions,
  clean output and sensitive-output replacement regressions also pass. Policy-deny
  response metadata remains `tool_permission`; specific categories are in records.
- Latest validation: **1090 related unit/complete UX tests PASS, 2 skipped**;
  Ruff, Black py310, error-level Pylint, package Mypy and diff checks pass. All
  **25/25 added executable source lines covered**; focused module coverage is 62%,
  not package-wide coverage. Coverage data: `/tmp/opencode/2662-gemini-pi-native.coverage`.
  Manual simplification/privacy review completed; /simplify is unavailable.
- **Final fresh retry: Gemini 0.67.0 9/9 PASS; Pi 0.86.0 9/9 PASS.** Standard
  current-source image `localhost/ai-guardian-agent-cli-smoke:b55081b8a9` was built
  once after the exact Pi mapping fix, with policy prepared before build, then
  explicitly reused for both matrices. Pi's two pre-tool failures are resolved;
  clean and both sensitive-output cases also pass. Both clients again pass container
  and authenticated published-host REST plus IPv4/IPv6 namespace-firewall setup.
  Both new test sandboxes were automatically removed. No hidden rebuild, image
  deletion, cache-strategy change, hot patch, real-provider call or weakened check.
  Build context/image reference: `/tmp/opencode/2662-pi-native-fc9jh10j/image.txt`.
- **User-requested cleanup completed:** removed the two retained initial failure
  sandboxes `ag-cli-smoke-gemini-ea80dfb3` and `ag-cli-smoke-pi-6c3fd28e` through
  the normal container sandbox-delete lifecycle. The engine escalated each stop
  after its normal grace period, then removed it successfully. A final filtered
  Podman list shows no remaining `ag-cli-smoke-*` containers. Images/build contexts
  and unrelated containers are untouched; no host firewall or global engine edit.
- Fetch confirmed no divergence before commit. Commit/push `0e87601b` updates
  PR #2670; remote-head verification and 0/0 tracking counts confirm sync. Only
  pre-existing/local OpenWolf files remain modified. CI for this commit not checked.
- **User-requested follow-up created:** #2673, "Extend real-agent smoke checks to
  remaining supported CLIs": Copilot, Grok Build, Antigravity, Kiro, OpenClaw and
  Crush. Compared the canonical CLI registry, normal-container selector and actual
  runner/Release Readiness matrix; checked for existing matching open issues.
  The issue requires capability/consent/provider audits, real native evidence,
  explicit partial/observation-only limitations and unchanged isolation/assertions.
  This creates planning scope, not implementation or new runtime qualification.
- Diagnostics stay aggregate-only. A prior code-search result was withheld during
  diagnosis, not smoke execution; the latest violation record did not establish
  its precise cause. User asked to retry after pausing; effective proactive level
  is paused and the same scoped searches now succeed. Hooks remain active.
- Preserve IPv4/IPv6 egress blocking, loopback mocks, normal discovery/REST/tray,
  shared sandbox lifecycle, native trust and all hook/execution/identity/raw-delivery
  and successful clean-exit assertions. External negative-egress, interactive tray,
  macOS, Codex hook approval and unmodified-strict Claude output remain separate
  qualification gaps. Other clients were not requalified in this phase. Local DAF
  notes and bug/learning records are updated. Next: review current PR/CI and plan
  #2673 as requested. No remaining Gemini/Pi nine-case failures on tested Linux.

### Current clean-tool continuation / compaction hypothesis — 2026-11-05

- The user's next retry reports **PASS tool_output_secret, tool_output_pii and
  allowed** after the shared V2 fix. Clean still fails with exit 1, four provider
  requests, no findings, one prompt/pre/post hook each and one execution/offer.
  Sensitive PASS confirms the reported containment checks, not zero CLI exits:
  expected-violation cases intentionally allow nonzero exits. OS/exact V2 patch
  were not included. JSON-result decoding alone did not resolve this clean failure.
- Found the smoke OpenCode model advertises only **8192 context tokens**. Published
  MIT 2.0.24 code estimates the whole request when the mock reports zero token usage;
  native/MCP descriptions can exceed its compaction ceiling. V2 summary compaction
  tries a summary and then one nudge; the mock's fixed OK reply fails both templates.
  Initial title + native tool request + two summaries fits the observed four-request
  signature, but **the actual runtime error/body was not captured**, so this remains
  a source-backed hypothesis rather than a confirmed cause of the user's exit 1.
- Changed only the disposable OpenCode mock model to **128000 context tokens**;
  output limit remains 1024. Preserve existing plugin/MCP, compaction, update and
  unrelated provider settings. Do not disable compaction, fabricate usage, accept
  summary echoes as native evidence, or change normal/global client behavior.
- Nonzero case diagnostics now classify structured CLI errors to a fixed
  `compaction_failed` or `unclassified` category without printing their bodies.
  This is diagnostic only; all existing raw-delivery, identity, exact clean text,
  hook, execution-witness and clean zero-exit requirements remain unchanged.
- Added real isolated configuration-snippet/idempotence coverage, fixed-category
  error/privacy tests, summary-not-native evidence regression and a complete UX
  contract for the reported four-request failure. Red tests caught the old 8K
  value and missing diagnostic; **402 related unit/complete UX tests pass**. Ruff,
  Black (py310), error-level Pylint, package/script Mypy and diff checks pass.
  Runner/mock coverage remains 79%/78%, combined 79%; manual simplification done.
- Updated RELEASING/CHANGELOG and local handoff/bug notes. **Published at the
  user's explicit request** as `6190e42a` on `origin/2662`, including the V2 result
  correction below. Eleven source/test/doc files committed; pre-existing/local
  OpenWolf records remain excluded. Fetch showed no remote divergence before
  commit/push; remote-head verification and 0/0 tracking counts confirm sync.
  No new containers, images, firewall state, native trust or real providers used.
- Next: retry the same pinned V2 smoke with the updated runner. Require clean
  native continuation and exit 0; if it fails, use the fixed category to confirm
  or reject compaction before further changes. Do not claim the 128K correction
  runtime-qualified or request private output. Other clients/Mac tray/negative
  egress/Codex approval and CI qualification remain separate.

### Current OpenCode V2 result-containment correction — 2026-11-05

- After `e1c81262`, the user reports V2 native execution and prompt/pre/post hooks
  now occur, but clean output is not recognized and both sensitive-output probes
  reach the mock. All three tool-output cases report CLI exit code 1; raw-delivery
  counters increase twice for each sensitive probe. Exact reporter patch version
  is not established. Keep these as failures, not protection qualification.
- Published MIT `@opencode/plugin`, `schema`, `core` and `ai` 2.0.24 contracts show
  completed results can carry structured `output`, text/file `content` and
  metadata together. A synthetic Node probe confirmed the shared plugin replaced
  only `output`, leaving raw model-visible `content` intact and assigning a shared
  Claude Bash object to the unrelated native shell output schema.
- **Scope explicitly expanded by the user:** selected “Fix V2 plugin” after being
  asked to authorize the shared V2 plugin plus structured-result regressions.
  This is not approval for the separate Claude adapter gap or other shared runtime,
  tray, sandbox, firewall, build/cache or trust changes.
- The plugin now replaces the complete result with valid content-only V2 text,
  discarding raw output, attachments and metadata. Bash stdout/stderr and native
  text/content replacements become text, not `[object Object]`. Completed blocked
  results are cleared before notification/throw. Clean allowed results are unchanged.
- Separately reproduced a mock clean-evidence false negative for JSON-encoded
  native output. Decode one JSON text layer only inside a result correlated to an
  issued native tool ID. Exact clean marker/output, native hooks, execution witness
  and successful CLI exit remain mandatory; whole-request raw detection is unchanged.
  This is not yet proven to explain the reporter's clean failure; exit code 1 is
  still undiagnosed and cannot be accepted as a clean pass.
- **Validation:** both red regressions failed before the fixes. All **394** related
  unit tests and both complete affected UX files pass, including executable Node
  structured-result/block/refusal tests. Runner/mock coverage is 79%/78%, combined
  79%. Ruff, Black (py310), error-level Pylint, package/scripts Mypy (337 files),
  and diff checks pass. Manual simplification/privacy review completed; `/simplify`
  is unavailable. Published SDK types were inspected, not compiled (`tsc` absent).
- **Published with the continuation correction above:** the user requested push,
  and all eleven source/test/doc files are in `6190e42a` on `origin/2662`.
  Local OpenWolf records remain excluded. No containers, images, firewall state
  or real providers used to publish. New CI has not been checked.
- Next: retry the pinned V2 nine-case local-mock smoke with the new package and
  runner. Obtain only aggregate counters/exit status.
  If clean still exits 1, diagnose without exposing private CLI/provider bodies or
  weakening assertions. Live V1/V2, negative egress, tray UI and Codex approval
  qualification remain separate; CI for `e1c81262` has not been checked.

### Current smoke CLI version selection — 2026-11-05

- User asks for separate OpenCode generation names or a version option. Added
  `--cli-name opencode --cli-version 1.19.0` / `--cli-version 2.0.24`, keeping one
  CLI identity. Accept exact stable 1.x.y/2.x.y only. Omission retains the existing
  image default; no host install or normal auto-update/default changes.
- The runner forwards the pin through the existing OPENCODE_VERSION build arg
  only for its temporary image. Reject other clients, --image and diagnostics
  combinations before side effects; --wheel remains compatible. Verify the exact
  installed version before V1 warm-up/any cases, including rejecting same-core
  prerelease/build variants. Unknown/mismatched versions cannot qualify a pass.
- Docker/Podman build command, cache options, prepared policy, firewall/bootstrap,
  REST, hooks and trust gates remain unchanged. CI keeps its prebuilt images;
  added a build-free help/conflict check and unit test executing that CI snippet.
- Validation: all **258 related unit/complete smoke UX tests pass**; runner 79%,
  mock 78%, combined script coverage 79%. Ruff, Black (py310), error-level Pylint,
  package/scripts Mypy and diff checks pass. Manual simplification/privacy review
  completed (/simplify unavailable). No containers/images/firewalls/providers used.
- **Published at the user's explicit request:** this option and the native-tool
  routing fix below are committed/pushed as `e1c81262` on `2662` (PR #2670).
  Fetch confirmed no remote divergence before publication; after push, HEAD and
  origin/2662 agree. Eight source/test/doc/CI files were committed; pre-existing
  local OpenWolf bookkeeping stays excluded. CI has not yet been checked.
- Real OpenCode Linux/macOS retry remains pending. Version selection supersedes
  the manual retained-context/rebuild workaround previously suggested. No image,
  container, firewall or trust change was made to publish this commit.

### Current OpenCode native-tool routing correction — 2026-11-05

- User reports missing pre-tool events in all five tool cases on Linux, then
  confirms the same on macOS; they identify the CLI as OpenCode (version not
  supplied). A later log confirms the V1 path and a completed ~75-second one-time
  warm-up, not another failure; exact CLI version remains unspecified. The user
  also asks how to test V2. SSRF/config-exfil findings occur, but only prompt hooks and a tool
  offer are recorded; clean/sensitive probes have no execution evidence. These
  must remain failures, not an expected Linux condition or a qualified pass.
- Found a concrete smoke-mock routing defect matching this signature: the mock
  selected the first schema with command/cmd/input, including the advisory MCP
  command checker. A synthetic catalog with that checker before native bash
  reproduced selection of the checker. The checker can log SSRF/config findings
  without executing the intended shell probe. This is not evidence of broken
  native hooks or an OS/network/config-policy issue.
- Fixed only the mock selector: require an advertised, exact supported native
  shell name, still with a usable command schema. Cover OpenCode bash/shell,
  Claude Bash, Codex shell/exec_command/shell_command and Gemini run_shell_command.
  MCP/custom tools cannot count as native offers, and advisory-only preflights do
  not consume the later real offer. Unknown/missing native tools fail closed.
- Added cross-protocol/all-five-case regressions and complete affected smoke UX
  contracts. Findings without pre-tool evidence still fail. All existing event,
  execution-witness, raw-delivery and privacy assertions remain unchanged. No
  shared hook/adapter, prepared config, image recipe, firewall or trust change.
- **Validation:** red regression selected the advisory checker before the fix;
  all 222 related unit/complete smoke UX tests pass afterward. Focused script
  coverage: runner 77%, mock 78%, combined 78%. Full Ruff/Black (py310), error-level
  Pylint, package/script Mypy and diff checks pass. Manual simplification review
  completed (/simplify unavailable); no containers, images or real providers used.
- **Published with version selection above:** the initially local five-file
  routing correction is included in `e1c81262`; OpenWolf work stays local. The
  actual OpenCode Linux/macOS outcome still needs a retry; do not claim live
  qualification from the synthetic catalog regression.
  The previously reported Mac/Claude prepared-config success remains separate.
- Next: check CI and obtain aggregate OpenCode results without copying private
  request bodies or relaxing policy/hook evidence.
  The initial retained-context/rebuild workaround for selecting V2 is superseded
  by the new --cli-version option above. No such build was run locally.

### Current prepared smoke configuration — 2026-11-05

- The user proposed adapting the smoke policy before runtime (preferably at build
  time) or preparing a config directory for `sandbox create --config-dir`, to avoid
  live/read-only config edits. This supersedes the earlier unchanged-strict smoke
  requirement, not the smoke-only implementation boundary. No shared adapter fix
  or bundled-profile change was authorized or made.
- Verified the normal config-dir path stages a source read-only **beside** the
  active config; the original entrypoint copies it to a writable sandbox-owned
  file before daemon startup. No extra image layer/build strategy is needed.
  The runner now prepares `smoke-config/ai-guardian.json` before any build/create.
  Docker passes `--config-dir`; Podman's gated smoke creation uses the same staged
  host-config input contract without touching normal creation or firewall logic.
- The strict-derived disposable config requests secret/PII output sanitization,
  retains strict prompt/pre-tool denial, notification suppression and hook-event
  telemetry. Logs/help/docs explicitly distinguish it from unmodified @strict.
  Raw-delivery checks, all nine cases, native trust and ToS gates are unchanged.
  The unmodified strict Claude post-tool containment gap below remains unresolved;
  a redaction-enabled smoke pass must not be claimed as fixing/qualifying it.
- **Validation:** 178 related unit/complete smoke UX tests pass. Real handler tests
  using only fake config/offline fixtures request output replacement for both
  synthetic probes and retain sensitive-prompt/file-read denial. Tests cover config
  preparation before builds/creation, supplied images and staging away from the
  active path. Focused coverage: runner/provider 77%, combined smoke scripts 78%.
  Full Ruff, Black (py310), error-level Pylint, package/script Mypy and diff checks
  pass. Manual simplification/privacy review performed; /simplify is unavailable.
- **Published:** the user explicitly requested push; the seven source/test/doc/
  CI-comment files are committed/pushed as `54c3b5d0` on `2662`. Fetch confirmed
  no remote divergence first. Pre-existing OpenWolf work stays local/excluded.
  CI for this commit has not been checked. No container, image or firewall was
  changed or started locally. The user's subsequent Mac/Claude retry reports
  **all nine cases PASS**, including both sensitive-output probes, plus internal,
  published and authenticated host REST checks. This qualifies the reported run
  with the prepared smoke config, not unmodified @strict post-tool blocking.
  Tray UI, negative egress qualification and Codex hook approval remain separate.
- Next: check new CI and qualify remaining clients/platforms with approved hooks;
  retain failures rather than masking client/schema limits. No further source
  change was needed after the user's successful retry.

### Current Claude post-tool containment finding — 2026-11-05

- After published reader fix `4c376f52`, the user's reported run passes internal
  health, published health and authenticated host stats. Firewall bootstrap and
  daemon setup complete. Seven cases pass (three prompt probes, two pre-tool
  probes, clean-tool execution and allowed). The two sensitive-output cases fail:
  real execution and pre/post/prompt events occur, a sensitive finding is logged,
  but the mock receives original synthetic output. Preserve these failures.
- Confirmed a real Claude adapter response gap with an aggregate-only local
  formatter probe: both secret/PII PostToolUse block responses return exit 0 and
  `decision: block` **without `updatedToolOutput`**. In
  `src/ai_guardian/hook_adapters/base_agent.py`, `_block_response` only adds feedback;
  the output replacement branch is reached only for allowed modified output.
- Current official Claude hook docs explicitly say PostToolUse `decision: block`
  adds feedback next to the original result; it does not withhold output. A
  schema-valid `updatedToolOutput` is needed. Bash's documented shape includes
  stdout/stderr/interrupted/isImage. Source:
  https://code.claude.com/docs/en/hooks#posttooluse-decision-control
  Do not blame this strict-branch failure on blanket upstream rewrite inability.
  `docs/AGENT_SUPPORT.md` has misleading old guidance suggesting block mode can
  prevent exposure after execution; review it with the eventual runtime fix.
- **No runtime/source change was made for this finding.** The user previously
  restricted this remedy to smoke-only code, so changing the shared Claude adapter
  requires separate approval. Proposed next step: strict-mode output withholding
  via the correctly shaped Claude response, preserving block policy and failed
  provider-boundary assertions—not switching on warn/redaction or skipping cases.
  Review shared adapter inheritance and affected unit/complete UX contracts.
  The user's later smoke-config approach is implemented above instead; this
  runtime adapter gap has not been repaired or qualified by that policy change.
- No real credentials, model calls, containers or firewall state were accessed.
  Host REST succeeds in the reported run; tray UI and negative egress qualification
  are not established by this log. Overall Claude containment remains unqualified.

### Current REST diagnostic reader correction — 2026-11-05

- User's classic-image/Claude smoke build completed firewall installation and
  daemon readiness, then failed `could not read private sandbox diagnostics`.
  They reiterated the intended design: classic container image, add the smoke-only
  egress firewall, run the tests—not another image/network redesign.
- Found a concrete smoke-only interpreter bug: the reader imports `ai_guardian`
  using system `python3`, but the classic Dockerfile installs the wheel only in
  `/opt/uv-tools/ai-guardian`. Readiness uses the working `ai-guardian` executable.
  Changed only this reader to `/opt/uv-tools/ai-guardian/bin/python3`; no image,
  entrypoint, bridge routing, shared lifecycle or firewall behavior was changed.
- A new isolated subprocess regression executes the real reader with fake IPC/HTTP
  and private temporary state. It reproduced the exact generic failure first and
  passes with the tool interpreter. No real daemon token is read or printed.
- **Validation:** 170 related unit/complete smoke UX tests pass; focused script
  coverage remains 77%. Full Ruff, Black (py310), error-level Pylint, package/script
  Mypy and diff checks pass. No containers/images/firewalls were changed or started.
  The user explicitly requested push; the four source/test/doc files are now
  **committed/pushed as `4c376f52` on `2662`**. Pre-existing OpenWolf bookkeeping
  remains local/excluded. CI for this commit has not been checked. Actual Mac
  A subsequent user retry passes internal/published/authenticated REST checks;
  the next failure is Claude output containment, documented above. Tray UI and
  negative egress checks still require separate evidence.
- Next: check new CI and resolve the separately scoped Claude adapter finding
  without relaxing isolation or copying private logs.

### Current hook-stage evidence extension — 2026-11-05

- The user accepted adding clean-tool execution and sensitive tool-output coverage,
  then explicitly requested publication. Committed/pushed as **`b400ba8a` on `2662`**
  in the smoke runner/mock, related
  unit/complete UX tests, release-readiness comments and docs. The matrix now has
  nine cases, adding `clean_tool`, `tool_output_secret`, and `tool_output_pii`.
- Derived smoke profiles retain strict security policy, suppress notifications,
  and enable existing latency telemetry for normalized hook-event counters.
  Prompt cases require prompt events; pre-tool probes require native offers and
  pre-tool events without post-tool events. Output cases require pre/post events
  and a value-free execution witness published only after output is flushed.
  The clean case also needs a correlated native tool result received by the mock.
- Sensitive probes use scanner-verified public synthetic values generated only
  inside the tool; a finding alone cannot pass. The mock inspects all request
  bodies, including token-count preflights, and exports only counters. Any raw
  delivery fails; a prior failure cannot be baselined away. Strict blocks output;
  this does **not** qualify warn-mode redaction. Native trust is never changed.
- **Validation:** all 169 related smoke unit/complete UX tests pass; focused
  script coverage is 77%. Full Ruff, Black (py310), error-level Pylint and
  package/script Mypy pass. Manual simplification/privacy review completed
  (`/simplify` is unavailable). No containers, images or firewall state were changed.
  New real-CLI/Linux/macOS runtime qualification remains pending; do not claim
  that any client has passed the expanded matrix yet.
- Published Windows correction `436bc54e` is now confirmed green: Tests run
  `42021950052` passed all eight OS/Python matrix jobs. All companion workflows
  on that commit passed too. This CI result does not cover the new extension.
  The ten feature/test/doc files were published; pre-existing OpenWolf bookkeeping
  changes remain local and were excluded. CI for `b400ba8a` has not been checked.
- Next: check new CI, then qualify the nine cases with legitimately approved
  native hooks. Mac REST/tray qualification and the
  separate Codex hook-approval prerequisite remain unresolved.

### Current smoke-only firewall and CI follow-up — 2026-11-05

- The user explicitly approved **nftables** (GPL-2.0-only external executable) in
  the generated temporary Podman smoke image and a short-lived `NET_ADMIN`
  namespace helper. This supersedes the earlier design-only/approval-pending
  notes below. Keep the remedy smoke-only; do not change shared runtime behavior.
- Implemented normal-bridge Podman creation, an atomic IPv4/IPv6 egress policy,
  and a startup gate before the original entrypoint. Loopback and replies to
  inbound connections are allowed; new non-loopback egress is dropped. The agent
  container is non-root with **all capabilities dropped** and no-new-privileges,
  including later execs. Only the read-only, one-shot helper gets NET_ADMIN and
  joins the selected sandbox network namespace. No host mounts or host PID use.
- Added `scripts/agent_cli_smoke_firewall.py`, `agent_cli_smoke_gate.py`, runner
  integration, related unit/UX contracts, and RELEASING/CHANGELOG documentation.
  The normal container sources are unchanged. Docker retains its internal
  network. Supplied Podman images without the bootstrap fail before creation,
  without hidden rebuilds; the runner explicitly selects the gate entrypoint.
  Helper failure/timeout never releases setup and stops even a kept sandbox.
  Success with `--keep` retains the firewall. Helper cleanup uses only its recorded
  container ID. Readiness is atomically published after its complete write.
- Completed private internal/host REST diagnostics and read-only retained-sandbox
  `--diagnose-sandbox`. Output contains fixed categories, never auth values,
  response bodies or agent output; stats probes allow bounded larger snapshots.
- Inspected CI on published `8140dd53`: the Tests workflow `41956962417` failed
  in eight matrix jobs. Sampled Linux and Windows logs both show the same **21**
  `test_sandbox_tray.py` failures. Tests still assumed native callbacks fetched
  remote stats. Updated only fixtures/expectations to seed worker snapshots and
  explicitly exercise asynchronous worker refreshes; no tray runtime was edited.
  All 194 tests in that unit file pass. Other latest workflows were successful.
- **Validation:** 375 directly related unit/complete UX tests pass. Smoke-only
  coverage run: 99 tests; runner 73%, firewall helper 93%, gate 92% (74% combined).
  Full Ruff, Black (py310), error-level Pylint, package/script Mypy and diff checks
  pass. `/simplify` is unavailable; manually reviewed bootstrap/order/privacy.
- **Pending:** the new rootless-Podman helper and Mac REST/tray behavior have not
  been runtime-qualified. No containers, images, routes, capabilities or firewall
  state were changed during this implementation/CI follow-up. Do not call this a
  proven Mac fix. The separate older Release Readiness failure `41951306169`
  predates the published Codex profile fix; legitimate native hook approval still
  blocks Codex protection qualification. No trust state was changed.
- The user explicitly authorized **push**. Committed the nine smoke/CI-test/doc
  files as `9f93dc9e` and pushed `2662` to `origin/2662`; fetch confirmed no new
  remote commits first. Pre-existing OpenWolf changes, including the
  hook-maintained anatomy edit, remain local and were excluded from the commit.
  Tests run `42016467216` passed all five Linux jobs but failed all three Windows
  jobs on the same new test: raw marker bytes are CRLF on Windows, not LF.
  Reproduced that failure locally with simulated Windows text writes. The test now
  reads text like the actual gate, retaining the atomic-publication assertion and
  native Windows coverage. All 100 directly related smoke unit/UX tests and full
  linters pass. No container/firewall runtime code was changed for this correction.
  Lint, smoke, integration, scenarios and wheel checks on `9f93dc9e` passed.
  The test-only Windows correction is committed/pushed as `436bc54e`; new Tests
   run `42021950052` and all companion workflows subsequently passed, including
   all three native Windows jobs (confirmed 2026-11-05).
  The user asked about hook-stage coverage: prompts and intended pre-tool block
  probes are present, but the runner has no explicit successful-tool/PostToolUse
  redaction case or event-specific assertions. The clean case avoids tools. This
   was the baseline coverage finding. The user subsequently accepted the extension
   documented above. Linux/macOS Podman runtime qualification and Codex native
   approval still need separate follow-up.

### Gemini and OpenCode generation smoke coverage — 2026-11-04

- Added Gemini CLI to the real-agent smoke runner using a synthetic
  `GEMINI_API_KEY`, loopback-only `GOOGLE_GEMINI_BASE_URL`, local GenerateContent,
  streamGenerateContent, and countTokens responses, with usage statistics disabled
  in the sandbox user's Gemini settings. The mock offers only fixed, harmless
  `printf` tool calls for the SSRF/config-exfil hook probes.
- Gemini names its native command tool `run_shell_command`; its adapter now maps
  that to canonical `Bash`, so shell policy/scanners and immutable CLI protection
  apply. Added direct unit and complete Gemini hook UX coverage.
- Release Readiness runs Gemini on the normal image and OpenCode V1 `1.19.0` plus
  a separate smoke-only V2 `2.0.24` image. V2 is not bundled in either support
  image and this local-mock run does not claim live-provider qualification.
- **Validation:** 1,040 related unit and UX tests pass; Ruff, Black (Python 3.10
  target), error-level Pylint, and package Mypy pass. Current-wheel Podman smoke
  runs passed all six cases for Gemini, OpenCode V1 `1.19.0`, and OpenCode V2
  `2.0.24`; no live provider request was made. Release Readiness now executes
  Gemini and both OpenCode generations.
- Smoke-runner, tray-network, CI fixes, and the OpenCode V1/Claude follow-up are
  committed and pushed on branch `2662` through `53af5747`; the branch tracks
  `origin/2662`. CI rerun `41921048728` passed, including all eight Python test
  matrix jobs. CI for `53af5747` is running as `41927850747` (Tests).

- Preserved the existing preview-by-default release command work on branch `2662`
  and implemented the real-agent CLI smoke runner. It uses `ai-guardian sandbox
  create`, the current-wheel image, a temporary strict-profile copy with
  notifications disabled, isolated temporary workspaces, and a local deterministic
  provider; the runner removes inherited provider credentials and uses a dedicated
  internal network to isolate egress while preserving the published REST port. The
  built-in `@strict` profile keeps notifications enabled, so the derived copy
  avoids side effects without relaxing scanner or policy settings.
- Added Anthropic Messages API non-streaming/SSE responses and Claude Code's
  native `ANTHROPIC_BASE_URL` route. Its `--print` invocation keeps hooks enabled;
  the runner does not use `--bare`. CI only installs/runs Claude when the
  maintainer-controlled `AI_GUARDIAN_CLAUDE_CODE_TOS_ACCEPTED=true` variable is
  explicitly set. To avoid runtime `claude.ai` downloads on the isolated network,
  `--accept-proprietary-tos` now adds Claude only to a runner-built temporary image;
  it is not passed into the sandbox. A supplied image must already contain Claude.
- Release Readiness covers Codex, OpenCode, and Pi by default and conditionally
  covers Claude after that consent gate. Updated `RELEASING.md`, CHANGELOG,
  CLI/runtime and scanner integration checklists, `AGENTS.md`, provider/runner
  unit contracts, and OpenWolf learning/bug records. After a
  Podman-only invocation exposed the hard-coded Docker default and sparse output,
  the runner now auto-detects Docker then Podman (with explicit overrides), prints
  flushed stage/case updates and periodic long-step heartbeats, and still captures
  subprocess output. Podman reported short-name resolution for the generated
  image; references now use `localhost/`. Its next run revealed a second issue:
  isolated HOME selected a different rootless storage path; the runner now
  preserves host `XDG_DATA_HOME`/custom `storage.conf` while keeping AI Guardian
  config isolated. The image pre-creates the writable parent needed for
  read-only profile mounts. The runner waits for sandbox daemon/config readiness
  before starting cases. OpenCode makes an initial provider request without tool
  schemas, so the mock now offers its deterministic command call on the first
  request that includes a command tool. Claude's permission allow rule now uses
  the sandbox-owned `~/.claude/settings.json` instead of the mounted repo. Claude
  also calls `/v1/messages/count_tokens` before inference; the mock now supports
  that preflight. Failed wheel/image builds and provider configuration print
  bounded diagnostics. Use OpenCode `build`, not `smoke`.
- **Validation:** 111 focused runner/release/container tests pass; changed scripts
  pass Ruff, Black (Python 3.10 target), error-level Pylint, and Mypy. A fresh
  Podman/OpenCode `build` sandbox passed all six cases: prompt injection, secret,
  PII, SSRF, config exfiltration, and clean allow. A Podman/Claude sandbox also
  passed all six cases against the local mock after the token-count endpoint fix.
  No live provider request was made. The Mac build failure was not reproducible
  here; its underlying stage output is now surfaced for follow-up.
- OpenCode V1 cases previously each cold-started an instance and MCP integration.
  The runner now starts one `opencode serve` backend and attaches each case. The
  server health endpoint becomes ready before its first MCP request, so a clean
  local-mock warm-up runs before the six case counters. Linux Podman V1 run took
  1m55s total, with the ~75s startup in the warm-up and all six labeled cases
  passing immediately afterward. OpenCode update/model-fetch suppression remains
  smoke-only; no live provider was contacted.
- Claude's earlier `curl` failure came from the entrypoint trying to install the
  CLI from `claude.ai` after joining the egress-isolated network. The runner now
  appends an install step only to its temporary image after explicit consent; the
  runtime sandbox receives no install-consent variable. The Claude image installer
  was not executed locally because no explicit Anthropic ToS acceptance was given.
- Related runner tests: 40 passed; Ruff, Black, and error-level Pylint pass. Package
  Mypy still reports 14 errors in the unchanged `skill_discovery.py` and
  `secret_validator.py` files. Commit `53af5747` contains the smoke/docs/workflow
  changes. Codex and Pi runtime smoke matrices were not run locally.
- Preserve the pre-existing `.wolf/anatomy.md` worktree modification. An
  authorized maintainer may separately enable the Claude CI variable only after
  reviewing and accepting Anthropic's terms.

### Tray REST connection for isolated smoke containers — 2026-11-04

- The user does not want smoke daemons hidden through a discovery exception;
  preserve ordinary tray discovery and investigate network isolation instead.
- The first Podman workaround kept an `--internal` network and attached a
  no-default-route bridge after sandbox creation. The user tested Claude on macOS
  and still saw a Daemon REST error; that approach did not solve Mac reachability.
- Upstream Podman issue #11396 records that macOS published-port forwarding works
  with a bridge network. The runner now uses a single DNS-disabled bridge with
  `no_default_route=true` for Podman and attaches it at container creation, so
  port forwarding is established on the initial network. Docker retains its
  internal-only network. No default IPv4 or IPv6 route is added, and there is no
  post-start network connection.
- Local Podman 5.8.4 validated the single-network path: host HTTP 200, no default
  IPv4/IPv6 routes, and the real OpenCode V1 smoke passed all six cases. This still
  does not qualify macOS gvproxy; the updated path needs a Mac run.
- The user reported OpenCode smoke cases waiting two minutes or more on both Mac
  and Linux. Initial investigation found blocked update/model-catalog checks; the
  V1 runner also cold-started a backend/MCP lifecycle for every case. Disable
  update/model fetch only in smoke, and use one V1 server plus a clean warm-up.
  Normal OpenCode auto-upgrade behavior is unchanged. Linux Podman V2 previously
  passed all six cases in 44.3 seconds; no live provider was contacted.
- CI run `41914912963`: lint, smoke, integration, and scenario workflows passed,
  but all eight Python Test matrix jobs failed. Ubuntu failures were the Gemini
  E2E test helper reading an obsolete hooks-list shape; Windows failures were an
  OpenCode fixture missing `USERPROFILE` and a Bash-wrapper test accidentally
  launching WSL. Local fixes are applied; 124 directly related unit tests plus
  Ruff/Black pass. CI rerun `41921048728` passed the Test matrix and related
  workflows.
- CI run `41927995470` completed successfully, including all eight Python Test
  matrix jobs. The focused runner/contract file passes 43 tests; Ruff, Black,
  error-level Pylint pass. Package Mypy still reports 14 errors in the unchanged
  `skill_discovery.py` and `scanners/secret_validator.py`.
- CI run `41938697614` is still in progress. Its `Container Images (real-agent
  smoke checks)` job failed at the pinned OpenCode V2 version assertion because
  the CLI reports `opencode v2.0.24`, not bare `2.0.24`. The release-readiness
  check now strips that display prefix before comparing; the related unit contract
  asserts normalization. The old run's completed companion jobs were green at
  last inspection; this workflow correction will be validated on the next run.
- The simplified Podman runner passes all 43 focused tests, Ruff, Black, and
  error-level Pylint. A local Podman 5.8.4 probe returned HTTP 200 with no default
  IPv4/IPv6 routes, and OpenCode V1 passed all six smoke cases on this setup.
- The user reports the macOS tray becomes unusable only while the discovered
  `agent-cli-test` daemon is running; unrelated containers do not cause it. The
  menu path synchronously requested remote `/api/stats` from native callbacks and
  the periodic refresh dispatched its remote snapshot work to Cocoa's main thread.
  Snapshot polling now runs on the stats worker and dispatches only native menu
  updates. Remote menu labels, partial-pause checks, and tray pause synchronization
  use the latest `target.stats` instead of making REST requests on the GUI thread.
  Normal discovery and the egress-isolated network are unchanged. Regression
  covers the empty pre-refresh state, cached stats, and worker-thread refresh.
  **Validation:** 489 `test_daemon_tray.py` tests plus 132 SSH-menu/pause tests pass;
  Ruff, Black, error-level Pylint, changed-module Mypy, and `git diff --check` pass.
  Full-package Mypy still has 14 errors in untouched `skill_discovery.py` and
  `scanners/secret_validator.py`. No Mac runtime verification has been performed.
- CI run `41943090396` uses pre-tray-fix head `71e0c21fe2b98ea823c4b55e42558a32d11b7879`.
  The linked `Container Images (real-agent smoke checks)` job failed at
  `codex/smoke`: `config_exfil` did not record its expected hook violation, then
  the clean `allowed` invocation exited nonzero. Image builds and the pinned
  OpenCode V2 version check passed. The overall workflow completed with failure.
  The job log did not include agent stdout/stderr.
- A local source-built-image attempt failed all Codex cases; a kept container
  confirmed Codex `0.166.0` and completed daemon setup, but provided no invocation
  output. Retrying the pre-existing support image with the installed
  `ai-guardian` command failed before sandbox creation because that host entrypoint
  lacks `ai_guardian_hook_runtime`; using the source module instead timed out during
  sandbox readiness, before Codex ran. None is an apples-to-apples reproduction of
  CI, so the cause remains unresolved and is not attributed to tray/network changes.
  Temporary container/network from the retained run were removed; no images were
  deleted.
- The smoke runner now prints aggregate-only failure diagnostics (agent exit code,
  mock-provider request delta, violation deltas), never prompts or raw agent
  stdout/stderr. The two new failure-reporting tests pass; all 45
  `test_agent_cli_test.py` tests pass. Tray validation remains 489 daemon-tray tests
  plus 132 SSH-menu/pause tests; Ruff, Black, error-level Pylint, changed-module
  Mypy, and diff checks pass. No Mac runtime verification has been performed.
- The user authorized committing and pushing the tray fix and aggregate smoke
  diagnostics to existing branch `2662`. Keep the pre-existing
  `.wolf/anatomy.md` edit out of the commit.
- Published the tray fix and aggregate smoke diagnostics as `ea2790d6` on `2662`;
  Release Readiness run `41951306169` completed with failure. Its container smoke job
  `126995637199` failed: all six Codex invocations returned exit code 1 with zero
  provider requests and zero new violations. This is earlier than the prior CI
  failure and indicates failure before observable hook/provider activity.
- Reproduced the startup failure with the existing source-built Podman image
  (`localhost/ai-guardian-agent-cli-smoke:4f620d6c0e`, Codex `0.166.0`) without
  rebuilding it. Codex rejects legacy `[profiles.smoke]` in `config.toml`; current
  native profiles use `smoke.config.toml` with top-level settings. Local code now
  writes the model/provider overlay there, preserving base MCP and hooks byte for
  byte and remaining idempotent. The updated regression failed before the fix;
  all 50 runner tests, Ruff, Black, error-level Pylint, script Mypy, and whitespace
  checks now pass. The profile fix and live build-output change are published as
  `8140dd53` on `2662`, following the user's explicit push request. Remote branch
  verification and `git push origin 2662` confirm it is synchronized. The commit
  appeared during validation; no existing work was reverted or overwritten.
- A full real-Codex smoke rerun after the profile fix passes the clean case, but
  all five protection cases still fail with no recorded violations. Native
  `hooks/list` via Codex app-server confirms five loaded hooks, zero load errors,
  and **all five untrusted**. The hooks feature is enabled. This is a separate
  native approval prerequisite; no trust bypass, trust-state edits, or managed
  policy changes have been made. Unattended qualification needs an explicitly
  approved supported policy for the exact smoke hooks. The earlier partial
  failure in run `41943090396` is not proven to have the same cause.
- Only the temporary Linux diagnostic container
  `ag-cli-smoke-codex-213b9469` and its route-less network were removed. No images
  were built, retagged, or deleted; runtime egress isolation is unchanged.
- The user reports the Linux smoke retry succeeded after an approximately
  150-second image build. The Mac attempt exceeded 330 seconds at **Building the
  temporary smoke image** and was restarted; no Mac smoke/tray runtime result is
  available yet. The image build timeout is 900 seconds, independent of the
  default 180-second runtime-operation timeout. Builds use the full support-image
  recipe, plus Claude installation only after explicit ToS opt-in. At the user's
  request, builds now inherit normal live Docker/Podman stdout/stderr; CLI output
  remains captured. Tests cover both engines, successful/failed build output,
  timeout/environment preservation, and captured-output defaults. Build commands,
  cache strategy, image contents, and runtime networking are unchanged.
- The restarted Mac build subsequently exceeded 450 seconds. The user also
  reports slow container creation from the tray, apparently around image fetch or
  startup. This affects two paths using the same Podman backend; VM resource
  contention, storage operations, and machine health are possibilities, not
  established causes. Image fetch completion and container startup are unconfirmed.
  The user subsequently confirmed that normal containers work on the Mac while
  smoke still does not. Do not assume a generally broken Podman machine; the
  smoke-specific failure and exact failing build step remain unconfirmed. The
  published live-output change is diagnostic visibility, not a proven Mac fix.
- The user is recreating the Mac Podman machine themselves; the agent did not run
  any Mac machine or image changes. The first subsequent build has a cold cache;
  Mac smoke/tray verification remains pending. Do not claim qualification.
- The Mac retry now gets past the earlier problem (user: "it worked now"), but
  the tray status is still wrong/unavailable. The user first described stopped,
  selected "Another container" when asked which entry, then clarified REST error
  during the smoke run and disconnected after keeping the container with
  `--keep`. They suspect the special network. Do not equate these messages with a
  stopped daemon or assume which other container is affected without evidence.
- Source inspection confirms `_wait_for_sandbox_ready` only runs `daemon status`
  through container exec; neither this nor the smoke cases verifies published
  REST access from the Mac host. `--keep` retains the same route-less network.
  The missing-default-route/VM forwarding return path is a plausible hypothesis,
  not a confirmed root cause. Authentication, listener health and the host port
  still need distinguishing. No networking, firewall, image, or container
  operations have been performed during this investigation.
- Local **unfinished/unpublished** diagnostic changes now add an internal REST
  health/auth-token snapshot (captured privately), fixed-category host health and
  authenticated stats probes, a pre-case REST gate, and read-only
  `--diagnose-sandbox NAME` for retained smoke sandboxes. Twelve new regressions
  were shown failing first; all 62 runner unit tests, Ruff and script Mypy pass.
  Formatting, deeper probe/error/privacy tests, affected UX coverage, docs,
  simplification and final validation remain unfinished. Do not ship this WIP as
  a Mac networking fix. No raw credentials or agent output were logged.
- The user suggests keeping normal Podman routing and using an in-container
  egress firewall instead. This is a valid architecture to evaluate, not yet
  authorization to alter host firewall, image dependencies, capabilities or
  networking. Allow loopback/local mocks and established replies to inbound REST;
  deny new non-loopback IPv4/IPv6 egress. The agent must not retain NET_ADMIN or a
  means to remove policy. A separate trusted setup helper sharing the target
  namespace may be safer than granting the agent container that capability,
  especially because later engine execs inherit the container capability spec.
- **Next:** discuss/test the firewall design's rootless-Podman feasibility and
  fail-closed bootstrap before further routing changes. Diagnostic work is paused
  for that decision. Do not build images/change cache strategy or privilege
  settings without approval. Request only aggregate Mac probe outcomes, not
  copied logs. Separately obtain approval for a supported native Codex hook
  policy, then validate all six cases; CI and Mac qualification remain unresolved.
- **Explicit scope clarification:** the next remedy must be smoke-only: runner,
  smoke-specific helper/generated temporary image, and related tests/docs. Do not
  change shared tray/discovery, normal sandbox creation, daemon runtime, host
  firewall or global Podman settings to fix this case. Existing published tray
  responsiveness work is not implicitly authorized for reversion. Propose any
  temporary-image dependency or privilege requirements before implementing them.

## Issue #2663 session initialization — 2026-11-03

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2663`, native conversation
  `ses_e5b9a0e22ffeY3t4J6lwV8DK72`, in the real workspace on existing branch
  `2663`. The worktree is clean; this is not a temporary clone, so no sync or
  branch change applies. Read the repository-qualified GitHub issue once.
- Acceptance criteria: define session liveness beyond the general 24-hour
  retention window; promptly remove ended sessions via supported lifecycle events
  with a documented fallback; show active/recent project targets while retaining
  explicitly paused directories and directory-only caller support; cover active,
  ended, stale, and directory-only targets.
- Read the DAF workflow, project instructions, OpenWolf handoff/protocol and
  cerebrum. No configured hierarchical Markdown contexts or hierarchical skills
  were found; `daf assets --dry-run --agent opencode` reports installed DAF skills
  up to date. The project release skill is unrelated and no OpenCode project
  skill applies. Left the native conversation title DAF-managed.
- The user requested initialization only. No implementation, tests, tracker
  mutations, DAF progress notes, branch changes, commits, or pushes were made.
- **Next:** inspect the session/project activity data path and affected pause
  controls/tests after implementation is authorized; determine the documented
  fallback for agents without reliable session-end events.

## Issue #2663 implementation — 2026-11-04

- Continued on existing branch `2663` in the real workspace. Preserved the modal
  pause-control design introduced by PR #2624 and kept legacy daemon stats and
  their 24-hour retention semantics unchanged.
- Added separate liveness-filtered `pause_control_sessions` and
  `pause_control_project_dirs` stats using a 30-minute hook-activity window.
  Received `SessionEnd` still removes the matching session immediately; stale
  session pauses expire on that same activity window. Directory-only callers
  remain represented, and explicitly paused directories remain available for
  Resume after activity stops. The modal omits inactive/offline daemon targets and
  shows one inert refresh prompt if no daemon is available. Older daemons retain
  the legacy-stats fallback.
- Updated CLI status/help, multi-daemon and agent-support docs, CHANGELOG, and
  regressions for stale/ended sessions, directories, offline daemons and status
  compatibility. Added a test for active-daemon-only modal selection.
- **Validation:** all 1,208 tests across the directly related daemon, tray, CLI,
  and complete affected pause UX files pass. Ruff, Black (Python 3.10 target),
  error-level Pylint (10/10), and `git diff --check` pass. Full-package Mypy still
  reports 14 existing errors in untouched `skill_discovery.py` and
  `scanners/secret_validator.py`. The test run emitted three GLib/Pillow
  deprecation warnings.
- Changes remain uncommitted on branch `2663`; no commit, push, PR, GitHub issue
  mutation, or DAF status update was performed. `/simplify` is not available in
  this harness; implementation and tests were reviewed manually.
- **Next:** user review and any separately authorized tracker/DAF completion.

## Issue #2652 implementation and rebase — 2026-11-03

- Continued managed DAF `open` session `RedHatProductSecurity-ai-guardian-2652`
  on existing branch `2652` in the real workspace. The user authorized
  implementation with **go**.
- Sensitive history filters now accept `secret_detected`,
  `image_secret_detected`, and `pii_detected` as compatibility aliases for
  consolidated `sensitive_finding` records. The canonical filter also finds
  older type-specific history; the privacy-safe persisted envelope remains
  unchanged. Updated MCP/SDK descriptions, security-tool guidance, docs, and
  CHANGELOG; added logger, SDK, MCP, and complete MCP UX regression coverage.
- **Validation:** 293 related unit/UX tests pass; Ruff, Black (Python 3.10),
  error-level Pylint, changed-module Mypy, JSON parsing, and `git diff --check`
  pass. Full-package Mypy retains 14 errors in untouched
  `skill_discovery.py` and `scanners/secret_validator.py`.
- Updated all three GitHub acceptance checkboxes, preserved `bug` and `1.21.0`
  while adding `done`, posted progress comment
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2652#issuecomment-6618043549,
  and saved a DAF progress note.
- Rebased branch `2652` onto `origin/main` at `a1c6d35d`. Autostash reapplication
  conflicted only in CHANGELOG and the generated anatomy index; both were
  resolved preserving upstream and local changes. Re-ran the 293 related tests
  successfully. The autostash remains as a backup. Changes are uncommitted; no
  commit, push, or PR was created.
- **Next:** user review and external DAF completion.

## Issue #2655 implementation — 2026-11-03

- Continued managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2655`, native conversation
  `ses_e5d4cddcfffeZzrglQCeePbX7o`, on its existing branch `2655` in the real
  workspace. The worktree was clean before implementation; no temporary clone
  applies. The DAF-managed conversation title was left unchanged.
- At the user's request, fetched and rebased branch `2655` onto `origin/main` at
  `3184c78b`; the branch had no unique commits relative to its previous base. The
  autostash replay conflicted only in generated `.wolf/anatomy.md`; resolved it
  preserving the updated index and all local work. No source conflicts occurred.
- `DaemonDiscovery.discover_manual()` now skips manual entries whose explicit
  names are null, non-string, or blank, logs a warning without echoing the value,
  and retains valid entries and the existing missing-name fallback. Tray target
  sorting also orders any malformed names safely after valid names.
- Added mixed-entry discovery and direct sorting regressions, documented manual
  target name validation, updated CHANGELOG, and recorded the bug in OpenWolf's
  buglog. **Validation:** all 620 tests in the directly related discovery and tray
  unit files pass. Full Ruff, Black (Python 3.10 target), error-level Pylint,
  package Mypy, buglog JSON parsing, and `git diff --check` pass. The initial
  pre-rebase tray run emitted an unrelated `PytestUnhandledThreadExceptionWarning`
  from the existing wake-detection test's mocked monotonic clock; it did not recur
  in the post-rebase run and was not investigated.
- Updated all three GitHub acceptance checkboxes, preserved `bug` and `1.21.0`
  labels while adding `done`, posted progress comment
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2655#issuecomment-6612727741,
  and saved a DAF progress note plus OpenWolf memory entry. All acceptance
  criteria are met locally. Changes remain uncommitted on branch `2655`; no push,
  PR, issue closure, or live daemon/configuration change was performed.
- **Next:** user review and external DAF completion.

## Issue #2654 implementation — 2026-11-04

- Continued managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2654` on its existing branch `2654` in the
  real workspace. The worktree was clean at initialization; read the
  repository-qualified GitHub issue exactly once. No temporary clone sync or
  branch change applied. The user authorized implementation with **go**.
- Tray menu identity now tracks manual endpoint URL, host, port, and the supported
  TLS CA, server-name, and certificate-pin settings. Equivalent manual targets
  remain stable across discovery-created objects; SSH object-generation identity
  and same-count reorder rebuilding remain intact. No credentials were added to
  logs or display labels.
- Added independent routing/trust identity cases, stable-manual and SSH-generation
  regressions, and an end-to-end discovery refresh proving a menu action receives
  the replacement target. Updated the Unreleased changelog entry.
- **Validation:** all 523 tests in `test_ssh_menu_parity.py` and
  `test_daemon_tray.py` pass. Repository-wide Ruff, Black (Python 3.10 target),
  error-level Pylint, package Mypy, and `git diff --check` pass.
- Updated all three GitHub acceptance criteria, added the `done` label, posted a
  progress comment, and saved a DAF note. Changes remain local and uncommitted;
  no commit, push, PR, or issue closure was performed.
- **Next:** user review and external DAF completion.

## Issue #2651 implementation — 2026-11-03

- Initialized and continued managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2651`, native conversation
  `ses_e5dadbfbbffexZ2Jyf3RrSR2CS`, on existing branch `2651` in the real
  workspace. Initial worktree was clean; no temporary clone sync or branch change
  applied. Read the repository-qualified GitHub issue once and preserved the
  DAF-managed native title.
- Implemented direct-hook notification handoff: during direct CLI fallback,
  synchronously commit the minimal privacy-safe event to the private SQLite outbox,
  then launch a detached worker from the trusted package root with only the opaque
  event ID. Python `-E` ignores path overrides without disabling user-site installs;
  redirected standard streams keep IDE pipes from inheriting the worker. It
  dispatches pending channels without holding the short-lived hook open. The
  existing long-running daemon queue remains asynchronous and alert registration
  remains independent of violation-history logging.
- Added a subprocess regression that exits the direct hook and verifies the
  outbox event was committed before worker launch, plus worker delivery, detached
  launch, and daemon-async regressions. Updated violation-logging docs, the full
  affected notification UX contract, CHANGELOG, and OpenWolf buglog.
- **Validation:** 43 related unit/UX tests pass. Ruff, repository-wide Black
  (Python 3.10 target), error-level Pylint, changed-module Mypy, and
  `git diff --check` pass. Full-package Mypy still reports 14 errors in untouched
  `skill_discovery.py` and `secret_validator.py`. Tests use isolated outbox state
  and mocked delivery; no live desktop/email notification was sent.
- Updated all three GitHub acceptance checkboxes, added `done` without replacing
  existing labels, posted progress comment
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2651#issuecomment-6610775647,
  and saved a DAF progress note. Changes remain uncommitted on branch `2651`; no
  push, PR, or issue closure. Ready for user review and external DAF completion.
- On user request, fetched and rebased the branch onto `origin/main` at
  `005968ec` (the prior branch tip was one commit behind and had no unique local
  commits). Restored all uncommitted implementation files; resolved the sole
  conflict in the generated OpenWolf anatomy index. Re-ran the 43 related unit/UX
  tests successfully after the rebase. No commit or push was created.

## Issue #2653 implementation — 2026-11-03

- Continued managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2653`, native conversation
  `ses_e5d8151aeffeW90m2DJa5hUOKL`, in the real workspace on its existing branch
  `2653`. The worktree was clean at initialization. Read the repository-qualified
  GitHub issue once; no temporary-clone sync or branch change applied. The user
  authorized implementation with **go** after requesting session initialization.
- The immutable AI Guardian CLI classifier now fails closed on PowerShell's
  opaque `-EncodedCommand`, `-e`, and `-ec` startup forms, including `.exe` shell
  names and supported wrapper recursion. The conservative check is scoped to the
  AI Guardian CLI boundary; visible unrelated PowerShell commands and documentation
  mentions remain allowed. Added unit and complete self-protection UX coverage and
  an Unreleased changelog entry.
- **Validation:** all 63 tests in `tests/unit/test_tool_patterns.py` and
  `tests/ux/test_user_experience_contract_cli_self_protection.py` pass. Ruff,
  Black (Python 3.10 target), error-level Pylint, targeted Mypy for
  `tools/patterns.py`, buglog JSON parsing, and `git diff --check` pass. Full-package
  Mypy reports 14 errors in untouched `skill_discovery.py` and
  `scanners/secret_validator.py`. No live Windows PowerShell runtime was available.
- Updated all three GitHub acceptance checkboxes, preserved the `bug` and `1.21.0`
  labels while adding `done`, posted progress comment
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2653#issuecomment-6611874633,
  and saved a DAF progress note. All acceptance criteria are met locally.
- On user request, fetched and rebased branch `2653` onto `origin/main` at
  `ba4f1389`; its prior tip `005968ec` was one commit behind and had no unique
  branch commits. Autostash restoration conflicted only in STATUS and the generated
  anatomy index; preserved the upstream #2651 and this #2653 handoff entries, then
  refreshed the index. Re-ran the 63 focused unit/UX tests and `git diff --check`
  successfully. Changes remain uncommitted; no commit, push, PR, or issue closure.
  **Next:** user review and external DAF completion.

## Issue #2649 implementation — 2026-11-03

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2649`, native conversation
  `ses_e5df9e787ffeWMv94FVRigZ9zn`, in the real workspace on its existing
  branch `2649`. The worktree was clean. Read the repository-qualified GitHub
  issue exactly once; no temporary-clone sync or branch change applies. Left the
  native OpenCode title DAF-managed.
- Acceptance criteria: support IPv6 literals and IPv6-resolved endpoints in TCP
  reachability checks; proceed to the verified REST request for reachable IPv6
  endpoints while rejecting unreachable endpoints; cover IPv6 and IPv4 without
  regressing transport/TLS verification.
- DAF config directory is `/home/itdove/.config/devaiflow`; hierarchical context
  files and skills are absent. `daf assets --dry-run --agent opencode` reports
  installed DAF skills up to date. The project release skill is unrelated and no
  OpenCode project skill applies. Read OpenWolf handoff/protocol and cerebrum;
  buglog search found no existing entry for this reachability failure.
- At initialization, the user requested session setup only; implementation was
  subsequently authorized with **go**.
- Updated `_tcp_reachable()` to resolve with `AF_UNSPEC` and try each address
  using its returned socket family/sockaddr. `_rest_request()` still delegates to
  the existing verified REST transport after a successful preflight. Added
  coverage for IPv4, IPv6 literals, IPv6-resolved names, failed/timed-out connects,
  and reachable/unreachable IPv6 REST requests. Updated CHANGELOG.
- **Validation:** 210 daemon-client and TLS tests pass; Ruff, Black (Python 3.10
  target), error-level Pylint (10/10), changed-module Mypy, and `git diff --check`
  pass. Full-package Mypy reports 14 errors in untouched `skill_discovery.py` and
  `secret_validator.py`. Resolver/socket tests are mocked; no live IPv6 endpoint
  was exercised.
- Updated the GitHub acceptance checklist, added the `done` label and progress
  comment, and saved a DAF note. All acceptance criteria are met locally. Changes
  remain uncommitted on branch `2649`; no commit or push was made.
- **Next:** user review and external DAF completion.

## Issue #2650 implementation — 2026-11-03

- Continued the managed DAF `open` session on its existing issue branch `2650` in
  the real workspace. The worktree was clean at initialization; read the
  repository-qualified GitHub issue exactly once. No temporary-clone sync or
  branch change applied.
- Rebased branch `2650` onto updated `origin/main` at `77d343b9`. Autostash
  restoration conflicted only in OpenWolf's STATUS/index files; resolved them
  preserving both the upstream #2649 handoff and this #2650 work. Re-ran all 318
  related tests successfully, then dropped the redundant autostash. No source
  conflicts occurred.
- Gist URL validation now accepts GitHub's documented ID-only URL and the legacy
  owner-qualified form. Receipt/API URLs remain bound to the Gist ID and, for the
  qualified form, the authenticated login. API owner/account, unlisted visibility,
  description, truncation and exact-file checks remain independent. The native
  **Open Gist** result action uses the shared strict URL validator.
- Added a unit regression and complete support UX contract for the documented API
  response, successful Discussion after a failed attempt, and safe retry reuse
  without a second Gist POST. Added owner-path mismatch coverage and documented the
  API shape in manual verification and CHANGELOG.
- **Validation:** 318 related support unit/UX tests pass. Full Ruff, Black (Python
  3.10 target), error-level Pylint, buglog JSON parsing, and `git diff --check` pass.
  Full-package Mypy reports 14 existing errors in untouched `skill_discovery.py`
  and `scanners/secret_validator.py`.
- Updated issue #2650 acceptance checkboxes, preserved its `bug`/`1.21.0` labels
  while adding `done`, posted progress comment
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2650#issuecomment-6609558733,
  and saved a DAF progress note. All acceptance criteria are met locally. No live
  Gist or Discussion was created; changes remain uncommitted on branch `2650`.
  **Next:** user review and external DAF completion.

## Review since v1.20.0 — 2026-11-03

- Continued the changed-runtime review on `main`; no source files were modified.
- Existing IPv6 reachability issue #2649 remains confirmed. Filed additional
  confirmed findings: #2650 (Gist receipt URL validation), #2651 (notifications
  lost on short-lived direct hooks), #2652 (MCP filters hide consolidated
  `sensitive_finding` records), #2653 (immutable CLI shell classification misses
  opaque interpreter payloads), #2654 (manual endpoint/trust changes do not
  rebuild captured tray actions), and #2655 (non-string manual target names crash
  sorting).
- Targeted reproductions confirmed the policy allow, stale menu identity, and
  sort exception. The worktree was clean before OpenWolf session bookkeeping.
- **Next:** continue the changed-runtime pass if requested; no tests or full-suite
  runs were needed because no source changes were made.

## Issue #2645 implementation — 2026-11-02

- Continued the managed DAF `open` session on its existing issue branch `2645`;
  the initial worktree was clean. Read the repository-qualified GitHub issue once.
- Audited the shared modal dispatch inventory against `ui_provider_order()` and
  `docs/MODAL_PROVIDERS.md`. Pause remains a complete isolated Tk → NiceGUI form;
  native simple forms remain ineligible.
- Updated the Tk Pause window startup to use a brief topmost hint, clear it after
  200 ms, and restore focus after the tray-menu handoff without changing placement.
  Added focused unit and complete Pause UX-contract coverage, provider documentation,
  and an Unreleased changelog entry.
- **Validation:** 125 related unit/UX tests pass. Ruff, Black (Python 3.10 target),
  error-level Pylint (10/10), project Mypy, and `git diff --check` pass.
- **KDE probe:** AI Guardian 1.21.0-dev, Plasma 6.7.4, Wayland session, Tk reports
  X11 windowing, preference `auto`; an isolated empty Pause window selected Tk and
  mapped at 1200 × 848. Shell launch did not make it the active window and is not a
  tray-menu reproduction. No pause/resume action or live daemon state change occurred.
- **Pending:** invoke Pause from the actual tray menu on KDE and confirm visibility,
  foreground handoff and temporary-topmost release. Acceptance criteria for live
  reproduction/fix qualification remain open; changes are local and uncommitted.

## Issue #2593 implementation — 2026-11-02

- Continued the managed DAF `open` session on its existing branch `2593` in the
  real workspace. The worktree was clean at initialization; no branch change or
  temporary-clone sync applied.
- Documented WSL2 as **Experimental** in the README Requirements and scanner
  platform guidance. Explained that installation and optional scanners run
  inside the Linux distribution using Linux packages/binaries, without adding
  scanner or architecture guarantees or changing existing platform status.
- Added Console guidance distinguishing the WSL-hosted Linux server from a
  Windows browser, with desktop-integration caveats. Added no-open/manual
  localhost troubleshooting and explicitly left the initial reported stall
  undiagnosed; retrying is not presented as a guaranteed remedy. WSL1 and
  comprehensive WSL2 CI/platform coverage are excluded.
- Updated CHANGELOG. Verified six WSL2 cross-document links and the README
  system-tray link, checked Console CLI flags with `uv run python -m ai_guardian
  console --help`, and passed `git diff --check`. Tests were not run because this
  is documentation-only; no runtime changes were made.
- All six acceptance criteria are met locally. Updated the GitHub checklist and
  `done` label, posted progress comment
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2593#issuecomment-6588081889,
  and saved a DAF progress note. Changes remain uncommitted; ready for review and
  external DAF completion.

## Issue #2634 session initialization — 2026-11-02

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2634` on its existing issue branch `2634`
  in the real workspace. The worktree is clean; no branch change or temporary
  clone sync applies. Read the repository-qualified GitHub issue exactly once.
- Read the issue's acceptance criteria for default-on, independently disableable
  violation alerts; desktop/email channel selection; per-channel duplicate
  prevention across retries and remote/local fallback; privacy-safe category,
  severity and daemon attribution; failure isolation; and synchronized config,
  docs, unit and UX coverage.
- The issue is explicitly blocked by #2633, which supplies opt-in local persistence
  and source attribution for remote violations. No implementation, tests, tracker
  updates, DAF progress notes, commits or pushes were made during initialization.
  The DAF-managed OpenCode title remains unchanged.

## Issue #2634 implementation — 2026-11-02

- Implemented default-on local violation alerts with independently configurable
  desktop and email channels. Email uses the configured TLS SMTP transport and a
  separate alert recipient. The private SQLite outbox tracks per-channel status
  and deduplicates retries; remote fallback avoids channels already delivered or
  with ambiguous outcomes. Older daemons use a persisted poll cursor and do not
  replay retained history on first connection.
- Added the notification service/relay, logger and tray integration, global-only
  config/schema/profile defaults, Web Console controls including a recipient
  tooltip for global SMTP setup, help text, docs, changelog, release-readiness
  checks, and unit plus full notification UX contract coverage.
- **Validation:** 598 focused feature unit/UX tests pass; 513 tray/SSH regression
  tests pass. Ruff, Black (Python 3.10 target), error-level Pylint (10/10), full
  package Mypy, JSON/YAML parsing, and `git diff --check` pass. Only upstream GLib
  and Pillow deprecation warnings appeared in tray tests. The tooltip follow-up
  also passes its focused 17-test help/notification UX run.
- Added the `done` label and a progress comment to issue #2634:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2634#issuecomment-6586598285
  Follow-up tooltip comment:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2634#issuecomment-6586902395
  DAF progress notes were recorded. PR #2646 is open. The notification and logger
  commits were rebased onto `origin/main` at `fcabf830` and pushed to `origin/2634`
  with a lease-protected history update; remote tip is `d19e8573`.

### PR #2646 CI/CodeQL follow-up — 2026-11-02

- Inspected CodeQL alert 216 and PR checks. Alert 216 is marked fixed on the
  default branch, but the PR's CodeQL check reported a new high
  `py/clear-text-logging-sensitive-data` finding at
  `src/ai_guardian/violations/logger.py:259`, where a debug message interpolated a
  caller-controlled violation category.
- Test run `41520863742` failed six matrix jobs (Linux Python 3.10–3.14 and Windows
  Python 3.14) on the same test,
  `test_full_dispatch_queue_drops_alert_without_raising`. The queue behavior
  passed; prior suite logging configuration suppressed the warning from caplog.
- Locally replaced caller-derived debug messages with fixed diagnostics, added a
  regression test, and set the notification logger level explicitly in the caplog
  test. The affected violation unit suites pass (73 tests); Ruff, Black, error-level
  Pylint (10/10), full package Mypy, and `git diff --check` pass. The CI test run is
  from the previous PR head and has not been rerun; CodeQL must be reevaluated on
  the follow-up commit. Container Build Validation `41520864019` was still running
  at last check.
- Rebase completed with the WSL2 documentation and notification changelog entries
  preserved. The push replaced only the two pre-rebase feature commits after fetch
  confirmed there were no additional remote commits. PR #2646 now points at
  `d19e8573`; fresh CI/CodeQL checks have started and are pending.
- **Next:** review the new PR checks and CodeQL result.

## Issue #2637 implementation — 2026-11-02

- Continued managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2637` on its existing branch `2637` in the
  real workspace. The initial worktree was clean; no branch switch or temporary
  clone sync applied.
- Avoided full-history rotation on routine violation appends. Per-process shared
  bookkeeping runs retention on first append to an existing file, when the
  `max_entries` schedule is due, or after five minutes; mirrored-log sync/history
  reads now use the same bounded maintenance schedule.
- Recent history reads seek backward in 8-KiB chunks, apply filters during
  traversal, and return newest-first. Legacy/mirrored records with detected
  timestamp disorder fall back to the existing full timestamp sort. Resolution
  and unresolution still rewrite JSONL because their state is stored in each
  record; this remaining O(n) cost is documented. Corrupt/non-object lines remain
  skipped during reads and resolution rewrites.
- Added focused append, retention/limit, recent-order/read-volume, corruption, and
  resolution tests plus an Unreleased changelog entry. Updated the issue's six
  acceptance checkboxes and added the `done` label/comment; DAF progress note saved.
- **Validation:** 461 directly related unit/UX tests pass. Ruff, Black (Python
  3.10 target), error-level Pylint, changed-module Mypy, JSON parsing, and
  `git diff --check` pass. Full-package Mypy still reports 14 known errors in
  untouched `skill_discovery.py` and `secret_validator.py`.
- Follow-up for GHAS review on PR #2639 / CodeQL alert #328: commits `203d6521`
  and `9b846b49` retained the high alert at the JSONL append despite helper and
  inline field projections. The user authorized a minimal sensitive-event
  envelope. Secret, image-secret, and PII writes now retain only ID, timestamp,
  severity, fixed generic `sensitive_finding` category, and resolution state;
  no blocked/source/context/suggestion/policy/allowlist fields are persisted.
  Caller objects and type-specific aggregate counters remain unchanged. The
  Console now labels the generic category, explains why details are absent, and
  reads secret aggregate statistics from counters. Docs and regression/UX tests
  were updated. Commit `33a293d3` still reported six flows at the append line;
  the listed sources point to CLI scan findings and Ask-mode test inputs. A local
  follow-up adds an envelope-only `log_sensitive_finding` path and routes Ask-mode,
  shared ScanResult, and CLI scan findings through it before any source details
  are assembled/passed to the generic logger. **Validation:** 620 focused
  unit/UX tests pass; Ruff, Black,
  error-level Pylint, and changed-module Mypy pass. Full-package Mypy remains at
  14 known errors in untouched `skill_discovery.py` and `secret_validator.py`.
  Fresh CodeQL on `93ceeba9` produced two findings; the `33597869` run cleared
  #328 but retained #329 at the generic append. Its source paths included Ask
  matched input, CLI finding message/snippet, and dynamic category/severity
  fields. Local follow-up omits Ask input/error text and CLI message/snippet from
  persistent records, canonicalizes category/severity labels in the top-level and
  policy-decision fields, and leaves caller data/CLI results unchanged. Docs and
  regression tests were updated. **Validation:** 625 focused unit/UX tests pass;
  Ruff, Black, error-level Pylint, changed-module Mypy, and `git diff --check`
  pass. Commit `60630c32` is pushed on branch `2637`. Fresh CodeQL run
  `41490674947` passed with zero Python results and alerts #328/#329 absent from
  the PR's open-alert query. The Python 3.14 job in run `41491648813` then found
  eight test failures: seven outdated expectations for the minimal sensitive
  envelope and one missing fixed label for `middleware_paused`. The tests now
  assert validation details are not persisted while caller data remains intact;
  the label allowlist also preserves `middleware_paused`, `scan_finding`, and
  `canary_detection`. **Validation:** 104 affected unit tests and 40 violation
  guidance/mirroring UX tests pass, with Ruff, Black, Pylint, changed-module Mypy,
  and `git diff --check` passing. Verify fresh PR checks, including CodeQL, on
  this CI-contract correction.
- No SQLite decision/migration or issue closure. Branch `2637` has open draft PR
  #2639; CodeQL was clear on `60630c32`, and the remaining task is to verify the
  resulting PR checks on this follow-up.

## Issue #2633 implementation — 2026-11-02

- Continued on the existing `2633` branch; no branch switch, commit, push, issue
  update, or DAF progress/checklist mutation.
- Added global opt-in `violation_logging.mirror_remote_violations` (default off).
  The tray mirrors curated remote summaries into one private JSONL per source
  identity at `remote-violations/<sha256-source-key>.jsonl`; the local daemon's
  `violations.jsonl` stays separate. Runtime/endpoint identity, not display name,
  keys files so same-named daemons remain distinct.
- Added a searchable **Filter by daemon** dropdown; it lists local history first,
  then remote sources by most recent violation. Same-named remote sources are
  differentiated by runtime and a short key suffix. Mirrors are read-only, omit
  raw blocked values/context/session/policy/suggestion data, retain source/event
  attribution, and link to a source record only when the name maps uniquely to a
  reachable target with the same identity.
- Per-file `max_entries`/`retention_days` rotation runs during tray sync and
  history reads; empty expired source files are deleted, causing inactive sources
  to age out of the dropdown. A private SQLite index prevents re-import after log
  rotation or clearing history.
- Added configuration/schema/profile defaults, docs, changelog, unit and UX
  contracts, and release-readiness checks. **Validation:** 394 focused violation,
  daemon, Console, and UX tests pass; 462 setup/profile tests pass; Ruff, Black
  (Python 3.10 target), error-level Pylint (10/10), Mypy, and `git diff --check`
  pass.
- The feature commit `30391c8a` is pushed on branch `2633`. CI run
  `41377665026` failed because the SSH menu test helper constructs a partial tray
  with `__new__` and did not initialize the new mirror wake Event. The follow-up
  initializes that Event in `tests/fixtures/ssh_tray.py` and asserts discovery
  wakes it. **Validation:** 47 SSH menu/mirroring unit and UX tests pass; the
  focused lint/format/diff checks pass. The fixture follow-up is local and
  uncommitted; no replacement CI run yet. The failure is unrelated to config
  schema/profile defaults, which all include the opt-in as false.
- **Next:** user review/authorization before publishing the CI fixture fix. Issue
  #2633 remains open. No live multi-daemon environment check was run.

## Issue #2628 implementation — 2026-11-01

- Continued the initialized managed DAF session on existing branch `2628` after
  the user's **go**. Preserved existing workspace state; no branch switch, commit,
  push, issue mutation, or DAF progress/checklist update.
- OpenCode MCP verification now recognizes supported V1 flat registrations under
  V2, preferring a native `mcp.servers.ai-guardian` entry when both are present.
  It evaluates known global, explicit `OPENCODE_CONFIG`, explicitly supplied
  project, system, and macOS managed-preference file layers in documented order,
  while distinguishing the user setup target from effective known-file status.
  Result metadata includes source/scope/path and status only; config values are
  not returned. Doctor reports this context, and the tray offers a focused **Set
  Up MCP** prompt when OpenCode plugin files are configured but MCP is unhealthy.
  Plugin runtime activation remains explicitly unverified.
- Added isolated regressions for V1/V2 formats, mixed-layout precedence,
  malformed/disabled registrations, config-layer precedence, system/managed and
  explicit-project sources, Doctor output, and the MCP-only tray flow. Updated
  OpenCode docs and CHANGELOG; OpenWolf buglog/cerebrum updated, anatomy refreshed
  automatically.
- **Validation:** 710 related unit tests and all 39 tests in the complete affected
  IDE setup UX contract pass. Full Ruff, Black (Python 3.10 target), error-level
  Pylint (10/10), and project Mypy pass. JSON and whitespace checks pass.
- An isolated `opencode mcp list` probe using a temporary config and synthetic
  stdio server timed out; it did not inspect or change the user's OpenCode config.
  No live host activation or reporter-machine-specific cause is established.
- **Next:** user review; if host behavior needs qualification, repeat a controlled
  OpenCode runtime check. Keep the issue open and do not claim runtime activation
  or reporter-specific diagnosis from these file/verifier tests. Changes remain
  local and uncommitted.

## Issue #2627 implementation — 2026-10-30

## Issue #2632 session initialization — 2026-11-01

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2632`, native conversation
  `ses_e671e99b2ffe4zwo2u5VWqC1Qz`, in the real workspace
  `/home/itdove/development/ai/ai-guardian` on the existing issue branch `2632`.
  Read the repository-qualified GitHub issue exactly once. This is not a temporary
  clone, so no sync/rebase applies.
- Read the DAF workflow and issue checklist, OpenWolf handoff/protocol, and project
  instructions. DAF context files and hierarchical skills are absent; project
  OpenCode skill discovery found no relevant skill, and `daf assets --dry-run
  --agent opencode` reported installed DAF skills up to date. The release skill is
  unrelated. Leave the native title DAF-managed.
- Issue #2632 requests a twice-monthly security-pattern research review across the
  listed priority sources and scanner categories, evaluating candidates against
  applicability, duplication, false-positive risk, reproducibility, and license
  compatibility, then recording review dates/findings and updating the reminder.
- User initially requested session initialization only, then authorized the review
  with **go**. Completed a research pass for 2026-10-19–2026-11-01 and recorded the
  findings in `AGENTS.md`: precise Baseten, Labelbox/Recursion, and Tailscale
  credential candidates; Supabase default-engine coverage discrepancy; no new
  deterministic PI/context, supply-chain/config-exfil, canary, offensive-language,
  or command-exfil signatures; and SSRF normalization/range gaps confirmed with
  no-network local probes.
- Synthetic credentials were generated in memory only. The bundled TOML scanner
  missed the tested standalone candidate strings; assignment controls generally
  reached the generic environment-variable rule. No live credential validation or
  destination network access was performed. Research does not claim corpus-wide
  false-positive rates.
- No detection code, tests, tracker comments/issues, branch changes, commits, or
  pushes were made. DAF-reported session status and time tracking remain unchanged.
- **Next:** decide whether to open focused follow-up issues for the secret-pattern
  candidates and SSRF canonicalization/address-classification gaps before any
  implementation work.

## Issue #2632 implementation follow-through — 2026-11-01

- User subsequently requested implementation of the recorded findings. Continued
  on existing branch `2632`, preserving the earlier research and local worktree
  changes. No branch switch, tracker update, commit, or push.
- Added eight bundled standalone credential rules: Baseten, Labelbox, Recursion,
  Supabase `sb_secret_`, and typed Tailscale API/auth/client/webhook formats.
  Added display names, deterministic synthetic fixtures, direct scanner and full
  PostToolUse/PreToolUse UX tests, documentation, changelog, and release-readiness
  plus smoke-test canaries. SCIM stays deferred because its key-ID layout is not
  documented; no live validation or population-wide false-positive claim.
- SSRF now canonicalizes a single terminal DNS root dot, immutably blocks
  `198.18.0.0/15` and `::/128`, and applies the existing IPv4 destination policy
  to addresses embedded in the well-known NAT64 `64:ff9b::/96` prefix. Public
  embedded addresses remain allowed. Synchronized bundled TOML, fallback ranges,
  and the separately hardcoded pattern-server immutable set; added no-network
  boundary, redirect/resolution, and UX coverage.
- **Validation:** 1,675 directly related unit/UX tests pass, including the complete
  SSRF revalidation and PostToolUse-secret UX contracts. Ruff, Black (Python 3.10),
  error-level Pylint, JSON parsing, and whitespace checks pass. Full-package Mypy
  still reports 14 errors in untouched `skill_discovery.py` and
  `secret_validator.py`; none are in the changed source modules.
- Changes remain local and uncommitted on `2632`. No full/integration/container
  suite, DAF progress/status/time mutation, tracker comment/issue, commit, or push.
- **Next:** user review; decide separately whether to publish or create tracker
  follow-ups. Do not claim live network reachability or corpus-wide FP qualification.

## Issue #2627 implementation — 2026-10-30

- User authorized implementation with **go**, then explicitly approved the
  additional OpenCode MCP-only tray repair. Continued on existing managed branch
  `2627`; no branch change, commit, push, PR or issue closure.
- Added shared tool-scoped file normalization and bounded, value-free input
  diagnostics. V2 `path`, legacy `filePath` and canonical `file_path` agree across
  adapter and direct policy callers; invalid/conflicting aliases fail closed.
  Verified V2 2.0.24 MIT source semantics for session location, home expansion and
  Windows shell drive aliases; ambiguous Windows drive-relative targets deny.
- Canonical targets now reach directory/content checks as well as policy.
  V2 fetches exact-session metadata afresh per event, deduplicating concurrent
  lookups only; the checker child uses that directory, and logging preserves
  hook/policy/plugin workspace attribution without process-wide chdir.
- MCP and Console/copy views expose vetted input classifications, shape and
  available version/correlation fields. Arbitrary values/keys, titles and stored
  reasons are not forwarded through diagnostics; legacy records and immutable
  action restrictions remain supported. Fixed stage-specific refusals stay intact.
- Added OpenCode to verified-healthy-hook MCP repair, without blanket forced
  replacement. A tray-flow regression reproduces the previous loop and verifies
  a second check stays quiet. The user manually ran setup outside the agent;
  read-only Doctor subsequently reports OpenCode MCP healthy, activation unverified.
- **Validation:** 2,400 directly related unit/UX tests pass; one Windows-only case
  skips locally. All three affected UX files ran completely. Focused branch
  coverage is 95% (adapter 100%, input normalization/diagnostics 94%, safe projection
  97%). Ruff, Black py310, error-level Pylint and targeted Mypy pass; readiness
  YAML/12 test paths and whitespace checks pass. Updated docs and CHANGELOG.
- Full-package Mypy retains existing `ui/clipboard.py:39` missing-return and
  `ui/ask_dialog.py:530` unreachable errors. An unmodified HEAD archive reproduces
  both in the same Mac/Python 3.12.11 environment. No unrelated fixes/suppressions.
  Coverage and baseline artifacts remain in the approved OpenCode temp directory.
- DAF progress note and automated checklist/open gates are saved:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2627#issuecomment-6530664258.
  Manual simplification/privacy review completed; no simplify skill or subagents.
- **Next:** fresh CI (Python/Windows/Node matrix), then actual OpenCode 2.0.24
  verification after loading the generated plugin: safe/protected reads, parallel
  workspaces and session movement. Harness tests do not prove host activation.
  Changes remain uncommitted. No full/integration/container suite, installed
  configuration changes or service restarts were performed by the agent.

### CI follow-up — PR #2629, 2026-11-01

- Inspected failing GitHub Actions run `41130868107` for PR #2629 / head
  `6a103cda67b5e44694aeff14acb8b0a5c3b505e0`. Build, CodeQL, lint, smoke,
  integration, container and scenario workflows passed; six Python/OS test-matrix
  jobs failed on the same UX contract:
  `tests/ux/test_user_experience_contract_agent_config.py::test_grok_project_configuration_mutation_is_denied_before_tool_execution`.
- Root cause: the new shared file-input validation ran before Grok's existing
  native configuration protection. Grok normalizes `write_file` and `path` in
  its adapter, while direct policy extraction must still recognize its
  `toolName`/`toolInput` envelope. The missing-argument branch shadowed the
  intended configuration-protection reason.
- Corrected precedence: OpenCode validates alias agreement before selecting a
  target; other integrations retain immutable CLI, host and agent-configuration
  guard precedence before shared missing-input validation. Do not weaken the
  Grok UX assertion. Expanded it across dict/JSON inputs, `path`/`filePath`/
  `file_path`, `write_file`/`search_replace`, and ordinary permissions on/off.
  Added direct conflict-order regression and included the complete agent-config
  UX file in OpenCode release readiness.
- **Validation after correction:** **1,806 related unit/UX tests pass**, one
  Windows-only skip on this Mac; all three directly affected UX contracts pass.
  Ruff, Black py310, error-level Pylint, targeted Mypy, whitespace and readiness
  YAML/test-path checks pass. Full package Mypy retains the same two unrelated
  UI errors, previously reproduced from an unmodified HEAD archive.
- DAF note and issue progress are recorded below/current GitHub thread. CI still
  describes the original published SHA; this follow-up remains local/uncommitted,
  so do not claim the remote failure is cleared. User must publish through the
  normal DAF completion flow, then fresh CI and live OpenCode 2.0.24 qualification
  remain outstanding. Agent did not commit, push, rerun workflows, or restart apps.
- Corrected PR follow-up comment records the exact CI job/test, root cause and
  local validation: https://github.com/RedHatProductSecurity/ai-guardian/pull/2629#issuecomment-6559806494.

### Betterleaks pin follow-up — 2026-11-01

- User reported a CI failure because Betterleaks `1.3.1` is no longer available
  and directed moving to `1.9.0`. Updated the `pyproject.toml` pin and the
  scanner-installation fallback example; added an Unreleased changelog entry.
- Verified the upstream `v1.9.0` release and both required Linux assets.
  `tests/unit/test_scanner_version_check.py` passes (10 tests), the full pinned
  scanner-asset existence check passes, and `git diff --check` is clean.
- Changes remain uncommitted on branch `2627`; no commit, push or remote CI rerun.

### CI public-release API 403 follow-up — 2026-11-01

- Inspected both latest `Verify Scanner Versions Exist` failures (runs
  `41322881959` and `41322881984`). They fail on the GitHub release-metadata API
  for Betterleaks `v1.9.0`; the logs show a 403 with the Actions `GITHUB_TOKEN`,
  while the other scanner checks pass. The log omits the API response body, so the
  precise cause of the 403 is not proven.
- Unauthenticated release metadata and direct x64/arm64 asset checks return 200
  locally. The checker now retries public GitHub metadata without Authorization
  after an authenticated 403, with a regression test. The fix passes all 11
  scanner-version unit tests, the live pinned-asset check, Ruff, Black and Pylint.
- Full-package Mypy still reports errors in untouched `skill_discovery.py` and
  `secret_validator.py`; standalone Mypy on the checker reports its existing
  `tomllib` import redefinition. Fresh hosted CI is still required to confirm the
  fallback works on the Actions runner.
- Saved DAF progress and issue update:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2627#issuecomment-6560319398.

## Issue #2627 session initialization — 2026-10-30

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2627`, native conversation
  `ses_e72ba525bffeecFsom92yQ8Z8G`, in the real workspace on existing branch
  `2627`. The worktree was clean. Read the repository-qualified GitHub issue
  exactly once; its comments list is empty. No temporary-clone sync applies.
- Loaded all four hierarchical context files from
  `/Users/dvernier/.config/devaiflow`, the installed hierarchical skills, DAF/Git
  guidance, OpenCode V2 guidance, and OpenWolf protocol/handoff/learning context.
  No additional OpenCode project skill was found; the project release skill is
  unrelated. `daf assets --dry-run --agent opencode` reported current generic
  skills and outdated hierarchical assets/configuration; nothing was upgraded.
  Leave the native conversation title DAF-managed.
- **Next:** verify generation/tool-specific effective-target normalization in
  both adapter and direct policy callers. Cover `path`, `filePath`, `file_path`,
  relative paths, missing/empty/malformed inputs and conflicting aliases without
  checking one target while the host executes another; preserve fail-closed and
  immutable protections from #2425.
- Add bounded, vetted input-failure/shape diagnostics and native/canonical tool,
  version and correlation metadata without raw payloads, arbitrary key strings,
  credentials, file contents, policy patterns or protection-suppression advice.
  Investigate trustworthy per-call workspace attribution across parallel sessions;
  the reported attribution mismatch alone does not establish wrong-policy routing.
- Extend MCP tool-name fallback and appropriate safe guidance, plus Console
  detail/copy views and legacy-record compatibility. Add isolated related unit
  tests and complete affected OpenCode/guidance UX contracts; synchronize exact
  wording assertions, relevant documentation and CHANGELOG, then run related
  tests and required linters only when implementation is authorized.
- User requested initialization only. No acceptance criteria have been verified
  or marked complete. No application changes, tests, tracker mutations, runtime
  changes, commits, pushes or PRs; only initialization handoff bookkeeping.

## Issue #2620 implementation — 2026-10-29

- Continued managed DAF `open` session `RedHatProductSecurity-ai-guardian-2620`
  on its existing branch `2620`, native conversation
  `ses_e76cb3961ffeQkM16qJ07YlkJe`. The repository-qualified ticket was read once;
  no temporary clone sync or new branch was needed.
- User clarified the intended layout: mirror the existing daemon → project →
  session hierarchy with Pause/Resume at every level, not scope/target dropdowns.
  Implemented one root Pause... action and a persistent isolated Tk/NiceGUI
  window with inline row actions, full identities, glyph legend, inherited-pause
  explanations, explicit Refresh and non-mutating Close/Escape. Latest user
  feedback replaces Pause buttons/shared duration with a duration/Resume dropdown
  on each row. Tk now requests 1200 × 820 within usable bounds; opt-in width-fitting
  content and responsive label wrapping keep the action column visible.
  A subsequent user screenshot exposed the real no-context sizing bug: placement
  intentionally does not set geometry in that path. The pause UI now explicitly
  applies initial geometry within WM limits before placement, and detailed help
  starts collapsed below the hierarchy in both providers. Initial controls are
  no longer preceded by the full multi-paragraph instructions.
- `tray/pause.py` keeps credentials/connections private, verifies acknowledgement
  and authoritative state, rejects stale/removed/reconnected targets, and never
  broadens failed requests. `ui/pause_controls.py` renders complete controls;
  `ui/modal.py` supplies the reusable persistent JSON-lines child channel with
  startup-only fallback. Removed obsolete native pause builders and slot limits.
- Updated related unit and complete UX contracts, modal/provider and multi-daemon
  docs, changelog and release-readiness coverage. Manual simplification review
  completed; no `/simplify` skill exists in this harness and no agents were delegated.
- **Validation:** 1,243 related unit/UX tests pass; one unrelated support UX test
  still fails on this Mac with `ValueError: Linked configuration omitted` at
  `reporting/cli_diagnostics.py:116`. It reproduces with unmodified HEAD sources.
  Focused branch coverage is 92% across backend/UI/modal modules (97% backend,
  87% UI, 92% shared modal). Coverage data/config are under the approved temporary
  OpenCode directory as `guardian-2620.coverage` / `guardian-2620-coverage.ini`.
- Ruff, Black py310 and standalone error-level Pylint pass. Full project-uv Mypy
  reports the same two baseline errors in `ui/clipboard.py:39` and
  `ui/ask_dialog.py:530`; an unmodified HEAD archive reproduces both with the same
  environment. No unrelated support/typing/security checks were weakened or skipped.
- Saved a DAF progress note and published the automated acceptance checklist and
  remaining validation gates at
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2620#issuecomment-6508859177.
  The issue remains open; existing labels and issue-body text were preserved.
  Latest sizing/dropdown follow-up:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2620#issuecomment-6509343912.
  A final focused rerun of all pause/placement unit and UX files passed 243 tests.
  Latest no-context geometry/help regression run: 316 pause/placement/modal unit
  and complete affected UX tests pass. The earlier broader run and its unrelated
  baseline blockers remain documented above; post-fix desktop confirmation is pending.
  Geometry/help follow-up:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2620#issuecomment-6510099065.
- **Next:** review the inline UI on actual desktops/physical monitors, then fresh
  CI and external DAF completion. The changes are uncommitted; no commit, push,
  PR, issue closure, live pause/resume, security-config change or daemon restart
  was performed. Native visual/focus/placement qualification remains pending.

## Issue #2622 implementation — 2026-10-29

- Continued managed DAF `open` session `RedHatProductSecurity-ai-guardian-2622`
  on its existing branch `2622`; the worktree was clean at initialization. Read
  the repository-qualified GitHub issue exactly once. No temporary-clone sync or
  branch change was applicable.
- OpenCode MCP setup now selects the active runtime generation: V1 retains the
  flat `mcp.ai-guardian` entry and its `enabled` field; V2 writes a valid local
  server at `mcp.servers.ai-guardian` without V1-only fields. Re-setup migrates
  only the owned entry. Verification/Doctor follow the active generation, and
  normal uninstall removes both supported locations while preserving unrelated
  MCP servers/settings.
- Plugin and MCP config paths continue to use the canonical resolver. Added
  isolated coverage across V1/V2, JSON/JSONC, both `OPENCODE_CONFIG` overrides,
  verification, removal, and Doctor UX.
- **Validation:** 636 related unit/UX tests pass, including the complete IDE setup
  UX contract. Ruff, Black (Python 3.10 target), error-level Pylint and Mypy pass.
  OpenCode 2.0.22 `opencode mcp list` reported `✓ ai-guardian connected` using
  the isolated config directory `/tmp/opencode/guardian-2622.L00fM0`. No live user
  configuration was changed.
- Saved a DAF progress note and GitHub progress comment; preserved `bug` and
  `1.21.0` labels while adding `done`. All acceptance criteria are met locally.
  Changes remain uncommitted on branch `2622`; no commit, push or PR was created.

## Issue #2617 implementation — 2026-10-29

- Continued managed DAF `open` session `RedHatProductSecurity-ai-guardian-2617`
  on its existing branch `2617`; the worktree was clean at initialization.
- Aligned the canonical example and schema with the runtime default
  `toml-patterns` + Gitleaks. Fresh setup already emitted TOML first; clarified
  its generated-config comments. Explicit engine lists still replace the default.
- Clarified the Engine Configuration checkbox and documented opt-out behavior.
  Added Console regression coverage showing TOML selected when `engines` is
  omitted, then saved off and still unselected after Reload.
- **Validation:** 446 related unit/UX tests pass; Ruff, Black py310, error-level
  Pylint and project-environment Mypy pass. JSON parsing and `git diff --check`
  pass. Standalone global Mypy reports 14 existing errors in untouched
  `skill_discovery.py` and `scanners/secret_validator.py`; project Mypy is clean.
  An initial schema-fragment test failure was fixed by validating through the
  root schema and recorded in the buglog.
- PR #2621 is open on branch `2617`; the original CI test matrix failed in
  `test_standard_matches_default_template` on all platforms/Python versions
  because setup's updated secret-scanning comments were not copied to built-in
  profiles. Synchronized both comment fields in all four profiles and added a
  parameterized parity regression. The full profile-manager unit file passes
  locally (47 tests); formatting, lint, JSON parsing, and diff checks pass.
- DAF note and GitHub progress comment are saved. Issue #2617 remains open with
  `enhancement`, `1.21.0`, and `done` labels. No issue closure or live config or
  daemon changes. Check PR #2621 for the CI result after this follow-up is pushed.

---

## Issue #2615 implementation — 2026-10-29

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2615` in the real workspace on its existing
  branch `2615`; the worktree is clean. Read the repository-qualified GitHub
  issue exactly once. No temporary-clone sync or branch change is applicable.
- DAF config directory is `/home/itdove/.config/devaiflow`; hierarchical context
  files and skills are absent. `daf assets --dry-run` reported no changes. Read
  the project handoff/protocol and OpenWolf guidance; no additional relevant
  OpenCode project skill was found. The native title remains DAF-managed.
- Reporter confirmed OpenCode V2 (2.x); exact patch version and OS remain
  unknown. The local CLI is v2.0.22. The V2 source path added a synthetic refusal
  and then threw from `ctx.session.hook('prompt')`. V2 prompt admission has no
  typed denial result; this failed-admission path is consistent with the reported
  session switch but still needs live-host confirmation.
- Updated V2 to replace the mutable prompt draft with one fixed refusal notice,
  clear `files`, `agents`, and `skills`, and complete safe admission into the
  requested session. Original prompt content is not persisted or delivered to the
  model. V2 may run the model on the safe notice and produce a generic response.
  Also hardened V1's analogous empty-parts path by replacing every part with a
  fixed synthetic notice; the toast discloses that V1 may process it.
- Added executable Node plugin-harness tests for V1 and V2 first blocks, a safe
  follow-up, and later blocked prompts, plus unit and complete OpenCode self-
  protection UX contracts. Source review found other generated prompt adapters
  (Pi, OpenClaw, AiderDesk) use host-specific handled/cancel/blocked return
  results rather than the V2 transform-hook exception path. No other-agent source
  was changed or runtime-qualified.
- **Validation:** 79 related unit/UX tests pass; Ruff, Black (Python 3.10 target),
  error-level Pylint, project Mypy, `git diff --check`, and buglog JSON validation
  pass. Runtime plugin harnesses execute both generated templates through first
  block, safe follow-up, and later block; the V2 harness verifies all prompt
  payload fields are removed on block and safe prompts stay unchanged. No live
  OpenCode TUI or other-agent runtime qualification was run.
- **Pending:** Obtain the reporter's exact OpenCode patch version and OS, then
  manually verify the new session remains selected and accepts a safe follow-up
  on that runtime. Keep the ticket open until this host-level behavior is
  confirmed. Changes are uncommitted on existing branch `2615`; no commit or PR
  was created.

## Issue #2614 session initialization — 2026-10-28

- Initialized managed DAF `open` session `RedHatProductSecurity-ai-guardian-2614`
  in the real workspace on existing branch `2614`; the worktree is clean. Read
  the repository-qualified GitHub issue exactly once. No temporary-clone sync is
  applicable, and the DAF-managed OpenCode title was left unchanged.
- Acceptance criteria: preserve the local daemon's Maintenance submenu in
  multi-daemon mode; show exactly one Contact supports entry per daemon and no
  duplicate root-level local-host entry when daemon targets exist; retain one
  Contact supports entry in the single-daemon flat menu and the standalone host
  action when there are no daemon targets; cover zero, one, and multiple targets
  (including local plus another daemon) in unit and UX regression tests.
- DAF config directory is `/home/itdove/.config/devaiflow`; hierarchical context
  files and skills are absent. `daf assets --dry-run` reported no changes. Loaded
  DAF workflow and OpenWolf guidance plus project instructions. No applicable
  additional project skill was found.
- Implemented the menu fix in `src/ai_guardian/tray/app.py`: the standalone
  local-host support action is present only when no daemon targets exist. Added
  zero/single/multiple-target unit and UX coverage, including exactly one support
  action in each daemon menu and bundled Maintenance under the local submenu.
  Updated the complete support UX manual contract, CHANGELOG and this handoff.
- **Validation:** 763 related tray unit tests and the complete support UX contract
  (56 tests) pass. Ruff, Black (Python 3.10 target), error-level Pylint and Mypy
  pass across their configured project scopes. The initial regression reproduced
  the duplicate root action for every non-empty target set; the fix passes all
  target-count cases. No live tray/runtime/configuration changes were made.
- Acceptance criteria are met locally. Changes remain uncommitted on branch `2614`;
  no PR or issue closure was performed. Ready for review and external DAF completion.

## OpenCode pasted-credential diagnostic — 2026-10-28

- User asked why a pasted credential-like assignment reached the model. Initial
  protocol-file read was refused; stopped and retried only after "read again".
- MCP sanitizer redacted the supplied sample once; the original was not returned.
  This uses SecretRedactor, not the hook's `check_secrets` path, so it does not
  establish that the configured prompt scanner detected the original submission.
- Source registers V2 prompt admission and routes it through content scanning.
  Doctor reports configured plugin files, explicitly not verified runtime loading;
  the queried secret-detection violation list is empty. A later tool refusal is
  evidence of tool enforcement, not proof of the original prompt's scan outcome.
- The earlier MCP `check_path` response described paused proactive action-gating
  and said hooks remain active. That is distinct from the daemon's global hook
  pause, which was checked separately below.
- New cross-check: `git ls-remote` confirms remote `main` is the same commit as
  local `origin/main` (`10a41e2d`). The two branch commits only add the
  default-off password-likelihood feature; no secret-scanner, adapter, or OpenCode
  prompt-hook code changed. Effective project config reports secret scanning on,
  password likelihood off; Gitleaks 8.30.1 is installed/default. The project's
  four allowlist entries and zero ignore entries do not mention the OpenAI prefix.
  A generated high-entropy positive control was detected and blocked by the direct
  secret scanner. The existing patterned test fixture's non-detection is not
  evidence about the user's value.
- Process socket metadata confirms current OpenCode client PID 2757870 is connected
  to server PID 497170, launched with `OPENCODE_CONFIG_DIR=~/.config/opencode-v2`.
  The standard and legacy plugin/bridge copies are identical to each other and
  functionally match current templates; both contain the prompt hook. Global
  Codex `UserPromptSubmit` config also contains an AI Guardian handler. Thus the
  legacy-profile mismatch is confirmed but is not yet a demonstrated cause.
- The daemon's current global pause is intentional after the user's tests, not
  evidence that it was paused during them. Safe log aggregates show resume at
  17:09, two prompt-processing/secret-scan entries at 17:10, and pause at 17:12;
  the user identifies these as the unpaused test window. There were no
  `secret_detected` records at 17:10. Both hook paths reached the daemon and invoked
  the prompt scanner, so pause/hook delivery is not the cause of those retries.
  The user disabled daemon REST TLS and restarted it as a comparison; detection
  did not change. App hook clients use local IPC, so REST TLS is unrelated. User
  should restore HTTPS because the setting protects the REST API.
- Four `secret_detected` records at 17:06 match the agent's synthetic direct scanner
  probes; their `ide_type=unknown` context is consistent with that direct call.
  Agent likely caused them and apologized. Do not treat the user's pasted record as
  evidence that either app prompt was blocked; no raw violation contents retained.
- **Likely configuration cause identified:** this machine's global
  `secret_scanning.engines` explicitly selects only `gitleaks`; Mac selects
  `toml-patterns`, `leaktk`, and `gitleaks` (user spelling “tolm-patterns” is
  assumed to mean `toml-patterns`). AI Guardian's default is
  `['toml-patterns', 'gitleaks']`, but an explicit engine list overrides it. The
  bundled TOML rules include `openai-project-key` (`sk-proj-...`) and its
  validator; omitting `toml-patterns` prevents that scanner from running here.
  Local status shows Gitleaks 8.30.1 and Betterleaks 1.2.0 installed, but no
  LeakTK. This is consistent with the same token being detected on Mac but missed
  here; the app hooks themselves reached the daemon. `password_likelihood=false`
  is not relevant to this provider-token case.
- No configuration change has been made. Ask before adding the built-in
  `toml-patterns` engine to the local global engine list; no new dependency is
  needed for it. Do not reuse the real value; rotate it if genuine. Do not restart
  the connected OpenCode service. No application changes or publication.

## Doctor and scanner diagnostics — 2026-10-28

- Added supported secret-engine inventory to `Doctor.check_scanners()`, showing
  configured and installed status for built-in `toml-patterns` and all preset
  engines. Warn only when secret scanning is enabled and TOML patterns are omitted;
  optional engines remain informational to avoid warning noise. Added focused tests.
- Clarified docs that an omitted engine list defaults to TOML patterns + Gitleaks,
  while an explicit list replaces the defaults; Doctor behavior is documented.
- Doctor now lists configured pattern servers one per line with URL and
  `patterns_endpoint`; the supported pattern-server catalog uses the same
  one-line-per-server format.
- Engine Tester lists only engines explicitly present in
  `secret_scanning.engines`; it no longer adds Gitleaks or TOML patterns and the
  Console explains that installed/built-in engines are not added automatically.
- User reported the Console collapsed the multiline engine inventory into one
  visual line. Fixed its diagnostic-detail labels to preserve line breaks with
  `white-space: pre-line`.
- Validation: related Doctor, scanner-manager, Engine Tester, and Web Console
  tests — **311 passed** (161, 35, 53, and 62 respectively). Ruff, Black py310,
  error-level Pylint, and targeted Mypy across all five changed source modules pass.
  The earlier full-package Mypy run reported 14 errors in untouched
  `skill_discovery.py` and `scanners/secret_validator.py`.
- No live user configuration or daemon state was changed. Work remains uncommitted
  on existing branch `2612`. The user should refresh the Console Health Check page
  to verify line-by-line rendering. HTTPS restoration and safe OpenCode profile
  handoff remain unconfirmed; do not restart the connected OpenCode service.
  Earlier credential-triage notes below remain context.

## Console Engine Config checkboxes — 2026-10-28

- Replaced JSON-first engine selection with per-engine checkboxes for the selected
  daemon's installed external scanners, plus a distinct always-available built-in
  TOML patterns option. Check/uncheck writes the selected config scope immediately
  and updates the advanced JSON editor; existing per-engine overrides and unrelated
  settings are preserved. Unsaved advanced JSON prevents checkbox changes rather
  than being silently overwritten, and config writes share a lock.
- Added additive `/api/about` `installed_scanners` names for local/remote daemon
  inventory; no binary paths or versions are exposed in the new field. Older or
  unreachable daemons without that field show an unavailable-inventory notice and
  do not invent the Console host's installed engines.
- **Validation:** 238 related unit/UX tests pass (78 page tests, 158 scanner/API/
  service tests, 2 complete new UX contract tests). Ruff, Black py310, error-level
  Pylint, targeted Mypy, and `git diff --check` pass. One initial UX test-harness
  error awaited a synchronous editor callback; corrected and recorded in buglog.
- A token-like prompt was blocked before delivery as `secret_detected` at prompt
  line 1. Its value was not reused or added to tests. No live config, daemon, or
  OpenCode process was changed. Changes remain uncommitted on existing branch `2612`;
  refresh Engine Config in the Console for visual verification.

## Issue #2612 / PR #2613 CI follow-up — 2026-10-28

- User reported CI failure after publishing `de3f4301` on existing branch `2612`.
  Baseline was clean and tracked `origin/2612`; earlier implementation/auto-save
  changes are now committed by the user, not by this agent. PR:
  https://github.com/RedHatProductSecurity/ai-guardian/pull/2613.
- Test run `40753709484` failed all eight matrix jobs. Inspected Linux 3.10/3.14
  and Windows 3.14 logs: same four failures, no platform-specific cause. The two
  audit failures reproduce with sanitizer CLI file-not-found followed by the tests:
  CLI disables global logging. Tests now explicitly enable pytest-managed capture,
  keep all privacy assertions, and require actual safe diagnostics (no vacuous
  absence-of-secret assertions). Production logging behavior is unchanged.
- Added specific private-review-only guidance for `suspected_password`. Complete
  unit/UX guidance contracts now require no persistent-exception snippet for this
  type and verify candidate values never appear, rather than inventing an unsafe
  configuration example just to satisfy the old all-types assertion.
- Inspected Python CodeQL analysis `2048191684` (8 alerts). Seven traces originate
  in a public enum label, a location-report factory, and notice variables, not raw
  candidates. Clarified internal metadata names without changing public strings,
  rule IDs, SDK/config or wire semantics. Factory now validates numeric locations
  and fixed class labels instead of copying arbitrary span fields. Replaced the
  flagged repeated phrase regex with delimiter splitting and ASCII word checks,
  preserving existing candidate-class acceptance/bounds. No analyzer suppressions
  or CI checks were disabled. **New CodeQL run still required.**
- **Validation:** red reproductions confirmed all four failures; final combined
  **1,091 related unit/UX tests pass**, sanitizer first, including complete password,
  PostToolUse-secret, guidance, modal and SSH contracts. Four existing deprecation
  warnings. Black py310, Ruff, error-level Pylint and Mypy pass. Focused branch
  coverage: detector 93%, report metadata/SARIF 90%, guidance 90% (combined 92%);
  `/tmp/opencode/guardian-2613-ci.coverage`. Readiness YAML/test paths and whitespace
  pass. Updated readiness test list, docs and changelog; manually reviewed changes.
- Fixes remain local/uncommitted; no commit/push, workflow rerun or runtime changes.
  GitHub currently still reports failures for the original commit, not these fixes.
  Python 3.14 is the only supported local interpreter; Windows/3.10–3.13 and actual
  CodeQL confirmation await publication/CI. Original real-corpus/live-host release
  qualification gates remain open; no full suite/integration/container runs locally.

## Issue #2612 Console auto-save follow-up — 2026-10-28

- User corrected the extra global Save-button UX and requested normal auto-save;
  continued after **retry**, without repeating or replacing the existing work.
  Removed the separate button. Enable/outcome now auto-save on human change while
  remaining global-only for the selected daemon, including with a project selected.
- The saver validates and updates one field against fresh global policy. Outcome
  changes do not enable analysis; rendering never writes/opts in. Serialize rapid
  saves within a card, preserve sibling/unrelated settings, retain read-only guards
  and existing success/failure notices. No default/action/enforcement changes.
- Updated every old exact Save-button assertion, the complete password UX contract,
  configuration/security docs, changelog and readiness test list. Added isolated
  auto-save callback/invalid-value/concurrency tests; no real configuration writes.
- **Validation:** **269 related unit/UX tests pass**, including the complete
  password-likelihood and existing PostToolUse-secret UX files, shared Web config
  routing/scope and existing Secrets-page tests. Ruff, Black py310, error-level
  Pylint and Mypy pass; readiness YAML/test paths and whitespace pass. The expected
  red UI tests were fixed rather than skipped. Manual simplification review done.
- Local/uncommitted on `2612`; no runtime config/restart, commit/push/PR/release or
  issue closure. Earlier Ask qualification/coverage and original corpus/live-host/
  platform gates below remain historical evidence/open gates, not newly verified
  prevention. User still must review/qualify the actual installed Console.

## Issue #2612 Ask default follow-up — 2026-10-28

- User explicitly requested implementation after proposing Ask/default-Ask and
  pointing out existing remote Ask support. Continued existing DAF session and
  branch `2612`; preserved the earlier uncommitted implementation and user work.
- **Secrets → Secret Scanning** now offers Ask/Warn/Block. The feature remains
  default-off in every profile; new/missing enabled outcomes default to Ask.
  Existing explicitly saved Warn/Block choices are unchanged. Schema, templates,
  example, loader, help/status, docs/changelog and readiness gate are synchronized.
- Contextual/incomplete hook checks use existing Ask transport and dispatcher,
  including remote/SSH. One value-withheld Allow Once / Block decision covers the
  operation; no persistent exceptions, candidate source recovery, View File,
  annotation/ignore editor or candidate fingerprints. Ambiguous spans stay advisory.
  SDK/static checks do not open UI; unresolved enforcing SDK Ask denies.
- Callers honor resolved decisions (not raw should_block), and safe canonical audit
  records approval correctly. Approval never skips stronger credential checks or
  authorizes another hook. Private dialog/audit failures withhold exception details.
- Reproduced/fixed existing remote display regression: auto-detected display-less
  daemons can forward to registered workstation trays, while explicit headless
  remains noninteractive. A queued remote timeout is terminal security fallback,
  never another local dialog. Existing non-heuristic fallback policy is preserved.
- **Validation:** final combined **1,226 related tests pass**, including all four
  affected password/PostToolUse-secret/modal/SSH UX files and shared Ask/audit/
  transcript/SDK/config regressions. Four existing dependency warnings. Ruff,
  Black py310, error-level Pylint and Mypy pass; JSON/readiness YAML/test paths,
  buglog IDs and whitespace pass. Manual simplification/privacy review completed;
  no simplify skill or delegated agents. Focused branch coverage **79.7%** across
  Ask/pipeline/detector/dispatch modules (detector 93.4%, post-scan 97.5%). Artifact:
  `/tmp/opencode/guardian-2612-ask.coverage`; ephemeral coverage, no dependency change.
- Saved DAF/OpenWolf progress and posted the local-completion/open-gates checklist:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2612#issuecomment-6473579086.
- **Still experimental/not release-qualified:** original held-out real-corpus,
  actual model-boundary/remote-native UI and cross-platform CI gates below remain
  open. Tests establish responses/transport contracts, not live host prevention.
  No full suite/integration/container scenarios, runtime configuration changes,
  installed daemon/tray restart, commit, push, PR, release or issue closure.

## Issue #2612 experimental implementation — 2026-10-28 (before Ask follow-up)

- User authorized implementation with **go**. Continued in managed DAF `open`
  session `RedHatProductSecurity-ai-guardian-2612`, native ID
  `ses_e7d450862ffe4kws4qRmhUJKO4`, existing branch `2612`. The repository-qualified
  ticket was already read once; no repeat remote lookup, new branch or clone sync.
  Preserve the pre-existing STATUS/cerebrum changes and OpenWolf-owned index work.
- Added `scanners/password_likelihood.py`: independent, offline/default-off,
  global-only literal human opt-in; local entropy reuse and bounded structural
  contextual/ambiguous classes. Reviewed detect-secrets v1.5.0 Apache-2.0 and its
  offline limitations; no new application dependency, dictionary/model or vault.
  Arbitrary context-free passphrases, multilingual/escaped/multiline recognition
  and real-host prevention remain unqualified, not universal detection claims.
- Added scanner/violation registration, shared content/file/command integration,
  bounded nested tool-argument traversal and independent PostToolUse inspection.
  Warn is advisory; block requests denial for contextual candidates or incomplete
  analysis, not ambiguous strings. Existing credential warning/block behavior is
  regression-tested; coordinate-based stronger-match dedup applies in the shared
  content pipeline, never downgrading stronger findings. Missing coordinates are
  not overlap proof. Host compliance is not established by response tests.
- Findings use safe locations/fixed labels, not values, partial hints or candidate
  hashes. Explicit sanitization replaces whole repeated/overlapping spans and
  withholds incomplete content. Audit/context overrides and exception text are
  withheld for this violation, including failures swallowed by the underlying
  logger. No automatic heuristic PostToolUse transformation is claimed.
- Synchronized schema/setup/example/all four profiles, global Secrets controls,
  status/help, static/SARIF rule metadata, violation filters/log-type selection,
  SDK/daemon paths, ignore-tooling name/schema, readiness workflow and docs/nav/
  changelog. Project exclusions/annotations/language overlays do not weaken this
  opt-in policy; explicit SDK null/missing policy does not load workstation opt-in.
- **Validation:** 1,558 directly related unit/UX tests passed together (three
  existing deprecation warnings), then 87 targeted tests passed after the final
  control/log-type checks, including both entire affected UX contracts. New
  heuristic module coverage is **94%**; source Ruff/Black (`py310`)/error-level
  Pylint/Mypy pass. JSON/schema/YAML, new doc links and whitespace checks pass.
  Manual simplification/privacy/budget review done; no `/simplify` skill is
  available in this harness, and no subagents were spawned. No full suite,
  integration/container scenarios, MkDocs build or live host tests were run.
- Qualification runner/fixture: `scripts/qualify_password_likelihood.py` and
  `tests/fixtures/password_likelihood_corpus.py`. Frozen seed 26122026: 8,000
  synthetic positives (1,000/class), 6,000 benign **template** samples. Supported
  class recall 98.6–100%; template negatives 0 flags; contextual precision 100%
  **only in this constructed corpus**. No population/zero-FP claim. Linux/Python
  3.14.7: 4-KiB p95 0.94 ms, bounded adversarial worst 15.28 ms, peak traced
  allocations 2,858,268 bytes (not RSS), within predeclared local budgets.
- **Open gates:** the unadjudicated repository sample flags 3/11 source windows
  (39,131 chars) and 3/9 documentation windows (32,915 chars), all ambiguous,
  none contextual/incomplete. This does not qualify real-world false positives.
  Independently adjudicate representative held-out corpora, then qualify actual
  pre-model payloads for each claimed host/version/platform and CI platforms.
  Keep experimental status and the v1.21.0 delivery/prevention claim gated; do not
  close the issue or treat generic hook denial/SDK checks as live host evidence.
- `docs/security/PASSWORD_LIKELIHOOD.md` records scope, measured results and manual
  evidence protocol; `docs/AGENT_SUPPORT.md` explicitly marks real hosts unqualified.
  Aggregate local report: `/tmp/opencode/guardian-2612-qualification.json`;
  focused coverage: `/tmp/opencode/guardian-2612.coverage` (ephemeral coverage tool,
  no project dependency/lock change). Initial red tests and mock/import-order
  contamination were fixed and logged, not skipped or silenced.
- Saved a DAF progress note and posted a completed-local/open-gates checklist:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2612#issuecomment-6472198028.
  No commits/pushes/PRs/releases/issue closure, real password/source access, runtime
  configuration/security changes or installed daemon restarts. Changes are local
  and uncommitted for review, not ready for acceptance/release completion.

## Issue #2612 session initialization — 2026-10-28 (historical)

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2612`; verified this repository and existing
  branch `2612`. Read the repository-qualified GitHub ticket exactly once. This
  real-workspace development session requires no temporary-clone sync.
- Config directory is `/home/itdove/.config/devaiflow`; hierarchical context files
  and hierarchical skills are absent. Loaded DAF workflow/Git/OpenWolf guidance,
  project protocol, handoff and relevant learning constraints. Project release
  skill is unrelated. Leave native titles DAF-managed; defer commits/PR to DAF.
- User requested initialization only; implementation has not started. Preserve
  the pre-existing changes in this handoff and `.wolf/cerebrum.md`.
- Next: read scanner/IDE integration checklists and audit bundled assignments,
  entropy/post-scan filters, optional detect-secrets reuse and SDK/daemon/hook
  boundaries. Select a minimal offline approach with license review before adding
  dependencies, and define class-specific held-out quality/performance budgets.
- Plan an independent default-off heuristic with trusted human opt-in, bounded
  candidate extraction and qualified contextual passphrases. Keep suspected-secret
  confidence distinct from password identity/strength, preserve stronger matches,
  and protect candidate values across every finding, log and diagnostic sink.
- Qualify advisory versus preventive surfaces and full repeated/overlapping-span
  handling; warnings/transcript scans are not leak prevention. Actual pre-model
  host evidence remains a release gate, not something unit hook mocks establish.
- Plan isolated related unit tests and complete affected UX contracts, synchronize
  applicable configuration/profiles/Web controls/registration/status/readiness and
  docs/changelog, and run related tests plus required linters after code work.
  Narrow/defer unqualified passphrase classes rather than claim universal coverage.
- No application changes, dependency installs, tests, tracker updates, vault reads,
  runtime/configuration changes, commits, pushes or PRs. Only this initialization
  handoff was added; OpenWolf owns automatic anatomy/memory bookkeeping. Earlier
  entries are historical, not implementation of the current issue.

## Default detect-secrets dependency discussion — 2026-10-28

- User asks whether the optional package should ship by default; this is a
  packaging discussion, not authorization to install or change application code.
- Current PyPI metadata: detect-secrets 1.5.0, published 2024-05-06, universal
  Python wheel 120341 bytes. Base runtime dependencies are PyYAML and Requests,
  both already core AI Guardian dependencies. Optional gibberish/word-list extras
  add other packages and are not implicitly selected. Verified Apache-2.0 license
  from upstream tag `v1.5.0`; distribution metadata alone had no license field.
- Provisional recommendation: if #2612 qualifies reuse of this detector, bundling
  the dependency can make sense while the new heuristic stays default-off and
  explicitly opt-in. Installation alone does not activate its detectors or extend
  the bundled TOML scanner. Do not blindly replace the existing scanner or enable
  the entire backend. Qualify offline behavior, false positives, supported Python/
  OS versions, security/maintenance and required blocking/redaction capabilities.
- No package installed, application code changed or issue updated for this
  discussion. #2612 remains the evaluation target; vault epic remains backlog.

## Password-heuristic issue #2612 created — 2026-10-28

- Follow-up wording clarification: `scanners/engine_builder.py` is present; it
  registers the optional third-party `detect-secrets` backend. Rechecked that
  backend's module/distribution and `.venv/bin/detect-secrets` are absent from
  this project's test venv, and no executable is on the inherited PATH. This is
  not a missing AI Guardian source module or a prerequisite for the built-in
  TOML scanner; it only limits which backend was exercised. No installation or
  live daemon configuration inspection was performed.
- User explicitly requested **no code changes**, only an issue for a viable
  solution. Created and read-back verified:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2612
  (`[Feature]: Opt-in local password-likelihood heuristics for unstructured text`).
- Labels: enhancement, security, secret-scanning, known-secret-protection,
  **1.21.0**. This is a target gated on quality/performance/pre-model enforcement,
  not a claim that universal password recognition or delivery is guaranteed.
- Scope: optional/default-off, entirely local heuristic candidate/scoring work,
  reuse/evaluate existing entropy/external detectors first, mixed-symbol strings
  plus qualified contextual passphrases, safe confidence-aware enforcement and
  full-span redaction. Includes representative false-positive/precision-recall,
  bounded performance, no-network/privacy and complete affected UX evidence gates.
- Explicit limits: strength/entropy does not prove a string is a password;
  context-free arbitrary joined-word recognition is not promised. No vault/source
  access, candidate persistence or raw-value diagnostics. Existing pattern/exact
  detections must not be weakened by heuristic non-secret scores.
- Independent related issue, not a new child/prerequisite of #2588. Verified
  #2588 stays backlog without 1.21.0 and still has exactly #2604-#2611 as its
  eight native children. #2612 has no parent or blocker dependencies.
- Draft: `/tmp/opencode/guardian-password-heuristics-issue-20261028.md`.
  Published body matched the draft; state/labels/independence verified via API.
  No application code changes, dependency installs, real vault reads or new
  heuristic implementation. Earlier probe results remain illustrative only.

## Password-heuristic capability review — 2026-10-28 (historical)

- User proposes an optional heuristic for random mixed-character passwords and
  joined-word passphrases as a smaller possible 1.21.0 delivery, conditional on
  what AI Guardian already supports. No application implementation or additional
  GitHub issue/dependency/release changes have been made for this proposal.
- Current source already has `shannon_entropy` in `patterns/validators.py`,
  contextual password/secret assignment rules and post-pattern entropy filtering
  in `scanners/toml_patterns.py`. Entropy filters matched candidates; it does not
  independently discover every random-looking standalone value. No dedicated
  general passphrase/word-segmentation detector was found in application source.
- Supported `detect-secrets` preset exists in `scanners/engine_builder.py` and its
  upstream documentation includes high-entropy detectors. Package is absent from
  this project environment; external-engine/adapter behavior was not exercised.
- Synthetic bundled-engine probe: five styles (random alphanumeric, random mixed
  symbols, joined words, CamelCase words, hyphenated words). Standalone 0/5 and
  natural-language examples 0/5 detected; password assignments 5/5 and JSON
  password fields 5/5 detected. Three benign controls produced no findings.
  These illustrate behavior, not measured precision/recall or universal coverage;
  no user vault/configuration or real passwords were supplied to the scanner.
- Recommendation: independent opt-in local password-likelihood candidate/scoring
  improvement, reusing existing entropy support and evaluating external-engine
  reuse first. Qualify mixed-character candidates, contextual passphrases, benign
  code/identifiers/hashes/logs, privacy/full redaction and actual model boundaries.
  Strength/randomness is not proof a value is a password; context-free joined
  words cannot reliably be distinguished from ordinary text/identifiers.
- Proposed 1.21.0 scope must be benchmark/false-positive gated, not a promise of
  universal password detection or a prerequisite for the vault epic. Ask whether
  to create the separate scoped issue; #2588/#2604-#2611 stay backlog unchanged.

## Issue #2588 parent/sub-issue publication — 2026-10-28

- User authorized converting #2588 into a parent, creating the proposed eight
  children with a feature label, adding dependencies and removing the 1.21.0
  target. Explicitly confirmed the full eight-issue/seven-edge proposal before
  publication. No replacement release was selected.
- Published parent: https://github.com/RedHatProductSecurity/ai-guardian/issues/2588
  (`[Epic]: Opt-in known-secret leak prevention before LLM submission`). The
  original Bitwarden-first proposal remains in a clearly historical details block.
- Created native GitHub sub-issues: #2604 design, #2605 shared core/enforcement,
  #2606 Linux Secret Service, #2607 macOS Keychain, #2608 Windows Credential
  Manager, #2609 Bitwarden encrypted exports, #2610 Firefox feasibility/provider,
  #2611 remote-daemon user-provided source access.
- Verified native `blocked by` edges: #2604 -> #2605; #2605 -> #2606, #2607,
  #2608, #2609, #2610; #2606 -> #2611. All eight are open, parented to #2588;
  no circular parent-as-prerequisite dependency or unrelated-provider ordering.
- Created/applied `known-secret-protection`; parent/children also have
  enhancement/security/secret-scanning/backlog. Removed parent `1.21.0` and
  verified no parent/child release milestone or 1.21.0 label remains.
- User clarified remote scope: no workstation secrets/index/session forwarding.
  A remote daemon can use its own reachable source only after separate opt-in,
  with a supported access mechanism and least-privilege permissions provided
  and administered by the human in that remote environment.
- User proposed Bitwarden encrypted exports. #2609 now initially targets portable
  password-protected encrypted JSON, not account-restricted exports or mandatory
  live CLI access. Require qualified/license-compatible authenticated decryption,
  private passphrase handling, no decrypted files/caches, and explicit snapshot
  age/expiry/replacement rules: reloading old ciphertext cannot discover new
  passwords or renew vault currentness. Account-restricted support is excluded.
- **Validation:** offline issue-body/size checks and acyclic eight-node/seven-edge
  topology passed; read-back GraphQL verified all hierarchy/dependency/label/
  scheduling state. Bitwarden official encrypted-export documentation reviewed.
  No application code changes, real vault/export/account reads, decryption
  qualification, runtime/security settings changes, app tests, commits or PRs.
- Scratch publisher/snapshot/journal are under `/tmp/opencode/guardian-2588-*`;
  publication journal is `guardian-2588-publication-20261028.json` (`complete`).
  Standalone task; branch `2585` and its historical task notes are preserved.

## Independent issue #2588 design review — 2026-10-28 (historical)

- Standalone conversational review, not implementation of the existing `2585`
  branch. User corrected the requested issue number from #3588 to #2588; the
  qualified #2588 ticket was read successfully and has no comments.
- Follow-up: user explicitly requires optional, opt-in integrations and asks
  about Linux passwd and cross-platform equivalents. Distinguish account
  authentication databases from saved-secret stores: `/etc/passwd` is not a
  plaintext-password source; `/etc/shadow` holds password verifiers. Recommend
  an opt-in Linux Secret Service provider instead, without reading real account
  databases or promising access to the OS login password.
- The existing proposal starts with Bitwarden Password Manager and already
  requires human consent, ephemeral matching state, safe output sinks,
  fail-closed required protection and no default copying to remote daemons.
- Recommendation for discussion: retain those shared requirements in a parent
  issue, qualify the matcher/security lifecycle first, then separate OS-native
  providers, Bitwarden, Firefox and remote deployment. Native stores do not
  automatically expose browser or third-party vault passwords.
- Prefer no persistent credential cache. Same-process memory encryption does
  not protect a compromised runtime; keyed fingerprints need substring-search
  correctness/performance qualification and do not defeat host compromise.
- No application changes, real vault access, tests, security configuration
  changes or GitHub mutations. Only local review/handoff notes were saved.
  Await user direction before editing #2588 or creating child issues. Existing
  task history below is preserved; this review does not complete #2585.

## Issue #2585 documentation implementation — 2026-10-28

- User authorized implementation with **go** after initialization; continued on
  existing managed branch `2585` and resumed after interrupted responses. The
  qualified ticket was already read once. No clone sync/new branch/commit/push/PR.
- Added `docs/UBUNTU_VM.md`: ordered Ubuntu guest prerequisites, independently
  verified SSH/public-key/agent access, regular-user PyPI/venv install, explicit
  global setup/private storage, optional official OpenCode V2 integration, fresh
  private lab certificate, VM Console bootstrap, exact global HTTPS fields,
  restart/verified health, workstation pairing/discovery, reboot recovery and
  separately owned foreground/background Console-tunnel cleanup. All machine,
  Console, listener, path and pairing boundaries are labeled.
- Updated docs index/MkDocs/configuration/HTTPS/SSH links and discovery-method
  table, plus Unreleased changelog. Existing advanced trust/PKI reference from
  Listener and client configuration onward and generated notebook export remain
  unchanged. OpenWolf-owned anatomy updates are reviewed and retained.
- **Publication gate:** production PyPI checked 2026-10-28 still has latest
  **1.20.0**, no `1.21.*`. Downloaded 1.20.0 wheel matches published SHA-256 and
  lacks native TLS/SSH modules and TLS schema. Guide/nav are explicitly upcoming;
  `>=1.21.0` is provisional/unavailable, not a confirmed first published release.
  #2591/#2592 are now closed/merged **development** UI changes, not yet PyPI
  features; document historical reduced menus versus development parity honestly.
- **Validation:** 21 Bash blocks pass syntax; 11 local guide links/anchors,
  incoming navigation, MkDocs YAML and 14 exact source UI labels pass. Isolated
  SSH-config parsing makes no connection; remote HOME quoting uses a fake binary.
  Exact lab TLS recipe passes 0700/0600 ownership/modes, repeat/no-overwrite,
  90-day validity, SAN/extensions, OpenSSL/Python strict verification, wrong SAN
  and untrusted-certificate rejection. Curl health/401-shaped responses came
  from a **synthetic loopback endpoint**, not daemon authentication qualification.
- Tools: Linux, Python 3.14.7, OpenSSL 3.5.8, curl 8.18.0, OpenSSH 10.2p1.
  Harness `/tmp/opencode/guardian-2585-validate.py`; final record
  `/tmp/opencode/guardian-2585-zs6cih6h/validation.json`. Owned endpoint is stopped.
  Corrected scratch response framing/negative-disconnect handling; recorded
  fixture iterations and publication/validation learnings in buglog/cerebrum.
  Whitespace and buglog JSON/unique IDs pass. Documentation-only: no application
  test suite, linters or local MkDocs build required/run; no new dependency.
- Saved DAF progress note and explicit completed-docs/open-release checklist:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2585#issuecomment-6463406036.
- **Still pending:** first supporting production release per feature, then actual
  fresh PyPI VM **and workstation** walkthrough with exact artifact/version and
  native UI/live SSH/Console/tunnel/reboot observations. Source reporter evidence
  and these synthetic checks do not meet that gate; issue is not marked complete.
  No live SSH/VM, real credential access, installed daemon/tray/Console restart,
  runtime/security settings changes or release publication. Changes remain local
  and uncommitted for review. Earlier entries are historical, not the active task.

## Issue #2585 session initialization — 2026-10-28

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2585`; confirmed this repository, existing
  branch `2585` and initially clean worktree. Read the repository-qualified GitHub
  ticket exactly once. This real-workspace session needs no temporary-clone sync.
- Config directory is `/home/itdove/.config/devaiflow`; hierarchical context
  markdown and hierarchical skills are absent. Loaded DAF workflow/Git/OpenWolf
  guidance, project protocol, handoff and user preferences. The project release
  skill is unrelated. Leave native titles DAF-managed; defer commits/PR to DAF.
- User requested initialization only; implementation has not started. Next:
  verify production PyPI availability and which published versions contain native
  HTTPS, SSH enrollment, alias discovery and later menu/settings changes. The
  ticket's last check found only 1.20.0; do not treat that historical observation
  or merged development PRs as current publication/qualification evidence.
- Plan one ordered `docs/UBUNTU_VM.md` guide covering verified SSH, regular-user
  PyPI/venv installation, explicit global setup/private storage, lab TLS identity,
  VM Console bootstrap, listener restart/verified health, workstation enrollment,
  optional alias discovery, reboot recovery and separately owned tunnel cleanup.
  Label machines, paths, Console origins and candidate versus pairing state.
- Match navigation/menu instructions to the published artifact, checking #2591
  and #2592 rather than assuming either pending or shipped. Preserve loopback,
  host-key/TLS verification, explicit trust, daemon authentication and VM-only
  private keys. Link advanced PKI guidance and synchronize docs index, MkDocs,
  configuration/multi-daemon references, discovery table and Unreleased changelog.
- Actual fresh-VM **and workstation** validation against the published PyPI build
  remains an explicit acceptance gate; source-build walkthroughs do not satisfy it.
  If no suitable release exists, label the guide upcoming and keep that gate open.
  Do not regenerate `docs/notebooklm-export.md`; documentation-only tests/builds
  are not required. No code/docs implementation, tests, tracker updates, live SSH,
  runtime/configuration changes, commits, pushes or PRs. Only this handoff changed;
  OpenWolf owns anatomy/memory bookkeeping. Earlier sections are history.

## Issue #2595 implementation — 2026-10-28

- User authorized implementation with **go** after initialization. Continued
  existing managed branch `2595`; the qualified ticket was already read once.
  No clone sync, new branch, commit, push or PR. Changes remain local/uncommitted.
- Added independent `announce-release X.Y.Z [--dry-run]` to the Python helper,
  dispatched before version/config initialization. Verify the exact published
  non-draft/non-prerelease Release and production PyPI exact-version, non-yanked,
  downloadable wheel/sdist before resolving Announcements and checking duplicates.
  Development/test/prerelease versions and TestPyPI are excluded.
- Existing authenticated `gh` resolves IDs and paginates categories/Discussions;
  markers bind identity to repository/tag, with exact-title/link legacy recognition.
  Lookup errors/incomplete pagination fail safely. At most one create is attempted;
  uncertain responses are reconciled read-only, never blindly reposted. URL-only
  successful stdout supports shell capture; errors never claim a successful post.
- Shell Phase 7b runs after verification and before merge-back/dev bump. Dry-run
  previews offline without new mutations. Confirmed URL goes into the release
  summary; an unconfirmed announcement preserves publication, completes merge-back,
  then exits nonzero with announcement-only retry guidance. Retry must be serial;
  GitHub has no transactional unique per-tag Discussion key.
- Updated `RELEASING.md`, release skill, Unreleased changelog and release-readiness
  gate (CLI help plus mocked related tests). Support reporting/category/native
  consent, production workflows, package versions/dependencies and generated docs
  export are unchanged. Simplification reviewed; explicitly validate hidden helper.
- **Validation:** **121 related unit tests pass**, including complete shell
  contracts with fake executables in disposable trees and retained Windows skips.
  Announcement-class coverage **98.6%**, entire helper **78.5%**; data/report:
  `/tmp/opencode/guardian-2595.coverage`, `/tmp/opencode/guardian-2595-coverage.json`.
  Black py310, Ruff, Pylint E and project Mypy (325 source/helper files) pass.
  Recorded fixture/exception-scope corrections and implementation iterations.
- DAF progress note saved; completed implementation checklist and validation scope:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2595#issuecomment-6459237303.
- **Next:** review and external DAF completion, then fresh CI. No real release,
  tag/package publication, Discussion creation, authentication/security-setting
  change, full suite, integration or container scenarios were run. Live publication
  is deliberately not part of mocked validation; do not claim a real announcement
  exists. OpenWolf owns automatic anatomy/memory updates; earlier entries are history.

## Issue #2595 session initialization — 2026-10-28

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2595`; confirmed the active repository,
  existing branch `2595` and initially clean worktree. Read the qualified GitHub
  ticket exactly once. This real-workspace development session needs no clone sync.
- Config directory is `/home/itdove/.config/devaiflow`; hierarchical context
  markdown and hierarchical skills are absent. Loaded DAF workflow/Git/OpenWolf
  and the relevant project release skill, protocol and learning constraints.
  Leave native conversation titles DAF-managed; defer commits/PR to completion.
- User requested initialization only; implementation has not started. Next:
  inspect `.claude/skills/release/release_helper.py`, `scripts/release.sh`,
  `.github/workflows/publish.yml` and their related unit tests before implementing
  an independently retryable exact-version announcement command.
- Plan explicit positive verification of the intended public, non-draft,
  non-prerelease GitHub Release and exact production PyPI version/distributions;
  exclude development/TestPyPI/test-tag releases. Shell completion or warning-only
  verification is not publication proof. Do not run a real release during this work.
- Resolve this repository's Announcements category through authenticated `gh`,
  without stored credentials or automatic permission changes. Include exact-version
  release/PyPI files links. Paginate duplicate lookup by repository/release tag;
  lookup errors fail safely and uncertain creation must never trigger blind reposts.
- Dry-run previews without mutations; retry must not create tags, bump versions,
  republish artifacts or roll back an existing release. Print confirmed existing/new
  Discussion URLs in results and the release summary; distinguish failure/uncertainty.
  Keep support-reporting category restrictions and native consent behavior unchanged.
- Plan mocked helper and shell contracts for publication gating, exclusions,
  pagination/idempotency, dry-run/retry and API/category/permission/uncertain failures;
  retain Windows Bash-only skips. Update `RELEASING.md`, the release `SKILL.md` and
  Unreleased changelog. Run only related tests and required linters after code work.
- No code changes, tests, tracker updates, real release/Discussion publication,
  authentication/configuration changes, commits, pushes or PRs. Only this handoff
  was updated; OpenWolf owns automatic anatomy/memory bookkeeping. Earlier entries
  are history, not the active task.

## Issue #2581 implementation — 2026-10-28

- User authorized implementation with “go” after initialization. Managed DAF
  `RedHatProductSecurity-ai-guardian-2581`, existing branch `2581`; the qualified
  ticket was read once. Keep DAF-managed titles and defer commits/PR to completion.
- Added stdlib-only `ui/monitor.py`: frozen display-only context, JSON restoration,
  action-time Windows Shell/GTK-X11 capture, usable monitor inventory, identity
  revalidation, current-DPI clamping and disconnected-screen primary fallback.
  Extended existing macOS AppKit capture; do not import AppKit before isolated Tk.
- Propagated context through modal lifecycle/children, plugin parameters and Browse,
  target-selector CLI/follow-up output, sandbox windows and delayed source support
  flows including View, separate upload/publication reviews and results. Support
  loads installed placement helpers by anchored path, without package/cwd imports.
  Display metadata never enters diagnostic bundles or grants consent.
- Unpositioned native providers defer to Tk without weakening exclusive preferences,
  complete controls, startup-only fallback or terminal cancellation. Cocoa/WinForms
  revalidate identity inside their child too. Long parameter/support forms use a
  two-axis viewport with reserved actions; wrapped, unchecked consent stays visible.
- Browser, Wayland/XWayland and remote-panel restrictions have explicit manual-move
  guidance, not placement guarantees. Inventory failure discards stale offsets for
  a small resizable WM-positioned recovery window. Single-monitor/scheduled/hook
  defaults remain unchanged. Docs: `docs/MODAL_PROVIDERS.md`, `docs/SUPPORT.md`;
  updated Unreleased changelog and release-readiness CLI/contracts gate.
- **Validation:** **2,230 related unit/UX tests pass**, including complete affected
  SSH/support/modal/about/setup/sandbox contracts; 3 dependency deprecation warnings.
  Focused 54-test rerun measures **91%** for monitor helpers at
  `/tmp/opencode/guardian-2581-monitor.coverage`. Coverage needs a targeted rcfile
  because the normal configuration omits `ui/*`. Black py310, Ruff, Pylint E,
  project `uv run --extra dev mypy` (324 files), CLI help and whitespace pass.
  Standalone global Mypy has unrelated Requests-stub errors; use the project env.
- **Pending:** physical mouse/keyboard multi-monitor qualification across macOS,
  Windows/X11, mixed DPI/taskbars/negative coordinates, delayed/reopened dialogs,
  disconnects and explicit browser/Wayland/remote-panel fallback. Mocks do not prove
  real placement/focus. No deliberate live UI qualification, uploads, settings changes, restart, full
  suite, containers, commit, push or PR. Changes remain uncommitted; OpenWolf's
  generated anatomy changes were reviewed and retained. Added a DAF progress note
  and issue comment `6458179852`, explicitly keeping physical qualification pending;
  logged the session via `openwolf memory log` using DAF's verified native session ID.
  Earlier sections are history.

## PR #2600 repeated CodeQL failure — 2026-10-27

- User reported **CDCI failed again**. The previous fix was published externally
  as `4c625156`; local `2597`/`origin/2597` match it and were clean. This supersedes
  the previous follow-up's uncommitted state below.
- Latest check `122509415215` fails only CodeQL; actual test/lint jobs succeed.
  Read new PR annotations and SARIF analysis `2040663120`: original #323 is fixed,
  but #324/#325 flag `cli_diagnostics.py:118-119`, the two pre-validation
  `Path.resolve()` calls used to compute the root/candidate. Resolve is itself a
  filesystem-access sink, so guarding the later open was insufficient.
- Replaced both with purely lexical `os.path.abspath`. Retain the same
  separator-aware checked absolute string, reject original path/ancestor links
  before normalization can hide linked `..` components, and keep regular-file,
  hardlink/fd checks, complete local files and bounded source reads unchanged.
- Test-first regressions prohibit source resolution for bounded/unbounded reads;
  cover normalized sibling-prefix escape and linked parent traversal. Updated
  docs/changelog and corrected the earlier learning. Simplification reviewed.
- **Validation:** **597 related tests pass** (555 complete support/source/unit/UX
  plus 42 tray/MCP support callers). Reader 96%, bundles 92%, combined **92%**;
  `/tmp/opencode/guardian-2600-prevalidation.coverage`. Black py310, Ruff, Pylint E,
  project Mypy (323 files), buglog JSON/unique IDs and whitespace pass.
- Latest fix remains local/uncommitted. No commit/push/CI rerun, alert dismissal,
  diagnostic collection/upload, live UI, restart or settings changes. The CodeQL
  CLI is absent locally: **do not claim the hosted gate passed**. Next: managed
  publication, then fresh CodeQL validation on that new commit. Earlier live
  remote/native qualification is still pending.

## PR #2600 CodeQL gate follow-up — 2026-10-27

- User requested reading PR comments after the QL gate failed. Current managed
  branch `2597` tracks `origin/2597` at `611e9969`; PR #2600 is open. The initial
  implementation was published externally, superseding the older local-only
  deployment notes below. Worktree was clean before this follow-up.
- Read PR comments/checks, inline security review, alert #323 and its SARIF flow.
  Python analysis succeeded but the finding gate failed: HTTP project cwd reaches
  the local project-config `open` at `reporting/support_bundle.py:393`.
- Test-first reproduced local collection of file/directory symlinks and hard
  links. Both local and daemon project reads now share `_read_config`, rejecting
  linked/nonregular sources and validating canonical directory containment before
  opening. Use a separator-aware canonical string prefix: upstream CodeQL models
  `startswith`, not `Path.is_relative_to`. No alert suppression/dismissal.
- Local reads explicitly allow complete files without remote transfer limits;
  daemon/CLI/import calls remain bounded. Tests cover sibling-prefix escape,
  linked-file omission/provenance, custom local filenames and complete >4 MiB
  local configs. Docs/changelog updated; simplification reviewed.
- **Validation:** **594 related tests pass** (552 support/source/unit/complete UX,
  plus 42 tray/MCP support caller tests). Focused coverage **92%** (reader 96%,
  bundles 92%), `/tmp/opencode/guardian-2600-path-read.coverage`. Black py310,
  Ruff, Pylint E, project Mypy (323 files) and whitespace pass. Initial global
  coverage lacked pytest-asyncio; reran successfully in project dev environment
  with ephemeral Apache-2.0 coverage. No dependency or lockfile changes.
- Follow-up remains local/uncommitted. No commit/push, CI rerun, alert dismissal,
  live remote collection, diagnostic upload, runtime restart or settings changes.
  **Next:** publish through managed DAF workflow, then verify a fresh CodeQL gate
  on the new commit. Live remote/native qualification remains pending below.

## Issue #2597 implementation and SSH reporter follow-up — 2026-10-27

- User authorized implementation with **go** after initialization. Continued
  managed branch `2597`; ticket was already read exactly once. Changes remain
  local/uncommitted. No new branch, commit, push, PR, live remote access,
  diagnostic upload or installed-runtime/security-configuration change.
- Added source-bound support actions in flat/nested local/container/Kubernetes/
  manual HTTPS/enrolled SSH/OpenShell menus, retaining the independent global
  **Contact supports — local tray host** action without requiring a daemon.
  New authenticated collection-only jobs run in the source installation/context;
  bounded retrieval validates inert complete files into protected desktop staging.
  Source provenance/omissions are explicit; no workstation diagnostic fallback.
- Desktop destination authority, per-file View/selection, ZIP-only semantics and
  separate native user-only Gist/Discussion approvals remain unchanged. Updated
  support/modal docs, Unreleased changelog and API release-readiness coverage.
  Simplification reviewed; no new dependencies or generated docs export.
- Reporter saw false **offline** despite a filled SSH status circle. Reproduced:
  support had frozen None/an old tunnel at menu rendering while polling used the
  new generation. Now capture the current verified tunnel for the original saved
  object/ID at click, then freeze it for the worker; never migrate on later
  reconnect or substitute a removed/replaced identity. Unit/UX regressions cover
  initial connect/reconnect/reordering/removal and in-flight replacement.
- Reporter asked whether the VM needs upgrading: **yes, to a build containing
  #2597, followed by a daemon restart**. These uncommitted changes cannot be
  obtained by upgrading to the current published release/main alone. A healthy
  status poll is not API capability. An actual tunnel HTTP-404 regression proves
  older daemons report unsupported collection rather than being marked offline.
- Also fixed collector import-root isolation against project .dist-info and an
  existing collector-test fixture teardown leak. Bugs/iterations/learnings recorded.
- **Validation:** **1,682 related tests pass together**, including complete support,
  SSH, TLS and modal UX contracts plus directly affected unit/menu callers.
  Focused new-module coverage **94%** (source jobs 95%, wire/import 94%; 79 tests),
  data `/tmp/opencode/guardian-2597.coverage`. Black py310, Ruff, Pylint E, project
  Mypy (323 source files), readiness YAML/paths, buglog JSON/IDs and whitespace
  pass. No full-suite/integration/container scenarios; GTK/Pillow deprecations only.
- DAF note saved; implementation/qualification checklist posted at
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2597#issuecomment-6452015942.
- **Next:** user restarts the workstation tray for the click-time fix and retests;
  publish via managed DAF workflow, install the new API on the VM and restart its
  daemon. Actual remote runtimes/native focus/placement/consent are not agent-
  verified; do not claim live acceptance complete. No issue closure. OpenWolf owns
  automatic anatomy/memory updates; initialization and earlier entries are history.

## Issue #2597 session initialization — 2026-10-27

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2597`; confirmed the active repository,
  existing branch `2597` and initially clean worktree. Read the qualified GitHub
  ticket exactly once. This real-workspace session needs no temporary-clone sync.
- Config directory is `/home/itdove/.config/devaiflow`; hierarchical context
  markdown and hierarchical skills are absent. Loaded DAF workflow/Git/OpenWolf
  guidance, project protocol, handoff and relevant support learning constraints.
  The project release skill is unrelated; leave conversation titles DAF-managed.
- User requested initialization only; implementation has not started. Next:
  audit support collection/review, existing authenticated transport and normal/SSH
  tray-menu seams. Plan source-local collection, bounded authenticated retrieval,
  validated protected staging and immutable sanitized source provenance before
  connecting per-daemon actions to the desktop review flow.
- Cover local/container/Kubernetes/manual HTTPS/enrolled SSH/OpenShell targets,
  flat/nested menus and refresh/reordering/removal. Retain an unambiguous global
  tray-host action without requiring or starting a daemon. No remote failure may
  silently fall back to workstation diagnostics or expose connection credentials.
- Preserve complete structured/configuration files, last-12-hours logs/violations,
  explicit omissions/excerpts, local destination authority, per-file review, ZIP
  semantics and separate native user-only Gist/Discussion consent. Keep transport
  work off the GUI thread and use shared modal dispatch for changed interactions.
- Plan isolated related unit tests and the complete support UX contract, including
  unsafe/oversized responses, older/offline daemons, source isolation and consent;
  update support docs/changelog and readiness/modal contracts as applicable.
- No code changes, tests, tracker updates, support collection/upload, live remote
  access, runtime/configuration changes, commits, pushes or PRs. Only this handoff
  was updated; OpenWolf owns automatic anatomy/memory bookkeeping. Earlier entries
  are historical, not the active task.

## Issue #2592 Windows CI fix — 2026-10-27

- Implementation was published externally as PR #2596, branch `2592`, commit
  `d835928210bcf8fb8b8d974f831c1733c2fdb1c4`; checkout was clean before this fix.
  The implementation section below describes the earlier pre-publication state.
- Inspected CI run `40553898922`: Windows Python 3.10/3.13/3.14 each fail only
  three `test_ssh_commands.py` cwd assertions; Linux Python 3.10–3.14 passes.
  The test expects POSIX separators for a native workstation `Path` on Windows.
- Added explicit POSIX/Windows pure-path inputs, reproduced the three Windows
  failures on Linux, then fixed local assertions to use the mocked home value.
  VM paths remain POSIX; SSH commands must exclude native and normalized local
  home strings. Production behavior and all security checks are unchanged.
- Validation: **112 related tests pass**, including complete SSH UX contracts;
  Black py310, Ruff, Pylint E and Mypy (321 source files) pass. Bug and learning
  recorded. No full-suite/integration/container tests run locally.
- Fix is local/uncommitted; no push, workflow rerun or PR/issue update performed.
  Next: publish through the managed workflow and rerun Windows CI. The separate
  live VM/native desktop qualification from the implementation remains pending.

## Issue #2592 implementation and reporter follow-up — 2026-10-27

- User authorized implementation with **go**; all changes remain local/uncommitted
  on existing managed branch `2592`. Original ticket was read once; no clone sync,
  commit, push, PR or installed-runtime/configuration changes by the agent.
- SSH now shares applicable flat/nested per-daemon menus: status/statistics,
  Console/Violations/Metrics, Terminal, Maintenance, scoped pauses, remote MCP,
  About/working directory/upgrade and retained connection management. Cached menu
  rendering stays nonblocking; callbacks retain target/tunnel identity across
  refresh/reordering/removal. Remote CLI uses verified SSH, actual interpreter and
  config/state paths, never workstation fallback. Host-key/TLS/prompt protections
  and managed dynamic-port reconnect are retained.
- Reporter corrections: local daemons first, remaining names alphabetic ignoring
  case; hide empty alias `(0)` but retain warnings/settings; keep terminal errors
  open. Remote main lacks new metadata despite a healthy MCP Doctor result, so
  use its existing authenticated **global** config API for missing MCP state and
  read-only same-user Linux procfs proof for its actual venv interpreter. The
  earlier main-upgrade advice was incomplete and was corrected explicitly.
- Reporter then identified Terminal's erroneous workstation-home `cd`. Fixed
  discovery to apply only explicitly saved SSH directories or remote home, also
  clearing inherited defaults on refresh. Preserve explicit selections, empty
  resets, local behavior and literal remote path labels. New discovery-aware
  regressions reproduced this before the fix and pass afterward.
- Source parity audit, modal matrix/manual steps, changelog and 13-file SSH
  release-readiness gate are updated. Simplification reviewed; new regressions
  include real scoped HTTPS and isolated actual procfs/venv behavior, never live
  VM access. No new project dependency; temporary coverage tool is Apache-2.0.
- **Validation complete:** **1,975 related tests pass**, including complete
  SSH/modal/About/session-pause/MCP-pause UX files and related daemon server,
  state/discovery/tray/client/plugins/working-dir/storage/TLS/Web unit files.
  Coverage: **86.5%** added executable lines, **93.1%** SSH command/connection/
  tunnel core, **70.8%** all selected modules including unchanged code. Artifacts:
  `/tmp/opencode/guardian-2592.coverage` and its `.json` report. Embedded probe is
  exercised by actual isolated Python/procfs tests, not line coverage of its string.
  Black py310, Ruff, Pylint E, Mypy (321 source files), JSON/YAML/readiness paths
  and whitespace checks pass. No full-suite/integration/container scenarios run.
- DAF progress note saved; local validation/remaining qualification checklist:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2592#issuecomment-6449289798.
- **Next:** have user
  restart the workstation tray to load source changes, then confirm actual local
  plus current-main VM menus/MCP/Terminal/Maintenance/reconnect/removal. Native
  macOS/Windows/GNOME/KDE, VM actions and user-reported health state are not
  agent-verified. Do not claim all acceptance/manual qualification complete.
  OpenWolf owns automatic anatomy/memory bookkeeping; earlier sections are history.

## Issue #2592 session initialization — 2026-10-27

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2592`; confirmed the active repository,
  existing branch `2592` and initially clean worktree. Read the qualified GitHub
  ticket exactly once. This real-workspace development session needs no clone sync.
- Config directory is `/home/itdove/.config/devaiflow`; hierarchical context
  markdown and hierarchical skills are absent. Loaded DAF workflow/Git/OpenWolf
  guidance, the project protocol, handoff and relevant learning constraints.
  Project OpenWolf is loaded; release is unrelated. Leave titles DAF-managed.
- User requested initialization only; implementation has not started. Next:
  audit the complete local/container per-daemon menu against SSH, beginning with
  `tray/menu_builder.py`, `tray/ssh_connections.py` and `daemon/multi_client.py`.
  Record applicable parity, intentional runtime differences and explicit unavailable
  states before sharing menu construction and adding transport-aware handlers.
- Cover selected-VM Console/Violations/Metrics navigation, cached status/statistics,
  terminal, lifecycle/reload/diagnostics/scanner maintenance, plugin routing, MCP
  scope, working directory/About/upgrade and retained SSH management/removal.
  Resolve remote executable/virtualenv context; never fall back to workstation
  execution or present unsupported actions as successful.
- Preserve verified SSH destinations/host keys, explicit TLS trust, authenticated
  managed tunnels, dynamic REST ports, generation-safe callbacks and reconnection.
  Keep network/process work off the GUI/menu-building thread, tolerate older-daemon
  fields and offline targets, and reuse shared dispatch for any new modal.
- Plan isolated related unit tests and complete affected UX contracts for labels,
  single/multi layouts, target isolation, plugin routing, capability/offline states,
  refresh/reordering/removal/reconnect and existing local/container behavior.
  Update `docs/MULTI_DAEMON_TRAY.md` and Unreleased changelog, run related tests and
  required linters after implementation, and retain actual local-plus-VM manual
  qualification as a separate explicitly authorized check.
- No code changes, tests, tracker updates, live SSH/credential access, runtime or
  configuration changes, commits, pushes or PRs. Only this handoff was updated;
  OpenWolf owns automatic anatomy/memory bookkeeping. Earlier entries are history.

## Issue #2591 tray SSH discovery settings — locally validated, 2026-10-27

- User authorized implementation with **go** after initialization. Continued
  existing branch `2591`, preserving the initialization handoff and OpenWolf-owned
  updates. The qualified ticket was already read once; no clone sync/new branch.
- Added always-available **Discover SSH aliases...** beside manual pairing, with
  captured-monitor worker dispatch and the existing `run_form_flow` dispatcher.
  All native/Tk/NiceGUI providers retain the complete two-step enable/Continue and
  optional-prefix/Save interaction, current values, feedback and cancellation.
  Only explicit Save mutates; validation/retries/results keep the chosen provider.
- Extracted the existing Web writer into `daemon/ssh_config.py:save_settings`;
  both entry points share global validation/persistence, preserving Web loopback
  gating and unrelated configuration. No new settings store/config key/dependency.
  Saved custom/empty prefixes request normal discovery refresh, not SSH/probing,
  trust, worker replacement or tunnel closure. Existing Review/Dismiss remains.
- Untouched open Web controls follow external settings saves; snapshots preserve
  browser drafts and edits made during an in-flight save. Two regressions proved
  the previous permanently loaded controls stayed stale. Recorded the fix and
  staged implementation/test iterations in cerebrum/buglog.
- **821 related tests pass; one Windows-only DPAPI test skips on Linux.** Includes
  complete SSH/modal UX files, forms, discovery/storage/tunnel/manager/tray/Web,
  daemon service/tray and directly affected menu callers. Focused SSH settings/
  parser and tray-flow coverage is **94%** (95%/92%); including broader tray app,
  combined **77%**. Artifact: `/tmp/opencode/guardian-2591.coverage`.
- Black py310, Ruff, Pylint E and Mypy (320 source files) pass. Source docs/modal
  matrix/manual checklist/changelog and SSH release-readiness gate are updated;
  YAML/all nine SSH test paths and whitespace checks pass. Simplification reviewed.
- DAF progress note saved; implementation checklist and remaining qualification:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2591#issuecomment-6446186160.
- **Next:** user review/external DAF publication, fresh CI and actual macOS,
  Windows, GNOME/zenity and KDE/kdialog desktop qualification. Mocked providers do
  not establish native visual/focus/placement behavior. No live SSH/credential
  access, installed-daemon/tray restart, runtime/security configuration change,
  full-suite/integration/container run, commit, push, PR or issue closure.
  All implementation changes remain local/uncommitted. OpenWolf owns automatic
  anatomy/memory bookkeeping; initialization and earlier entries are history.

## Issue #2591 session initialization — 2026-10-27

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2591`; confirmed the active repository,
  existing branch `2591` and initially clean worktree. Read the qualified GitHub
  ticket exactly once. This real-workspace development session needs no clone sync.
- Config directory is `/home/itdove/.config/devaiflow`; hierarchical context
  markdown and hierarchical skills are absent. Loaded DAF workflow/Git/OpenWolf
  guidance, the project protocol, handoff and relevant learning constraints.
  Project OpenWolf is loaded; release is unrelated. Leave titles DAF-managed.
- User requested initialization only; implementation has not started. Next:
  inspect tray SSH controls, Web discovery settings and the shared form adapter;
  add an always-available **Discover SSH aliases...** settings entry using the
  existing workstation-global validation/persistence and cached discovery refresh.
- Preserve default-off/default-prefix behavior, custom/empty prefixes, complete
  controls, Native → Tkinter → NiceGUI dispatch, startup-only fallback and terminal
  cancellation. Keep configuration I/O/scans off the GUI thread. Saving must not
  probe hosts, run SSH, grant trust, remove pairings or close existing tunnels.
- Plan isolated related unit tests and the complete affected SSH UX contract for
  availability, current values, Save/Cancel/Close, validation, persistence/refresh,
  provider lifecycle and connection preservation; update multi-daemon/modal docs
  and Unreleased changelog. Run related tests and required linters after code work.
- No code changes, tests, tracker updates, live SSH/credential access, runtime or
  configuration changes, commits, pushes or PRs. Only this handoff was updated;
  OpenWolf owns automatic anatomy/memory bookkeeping. Earlier entries are history.

## Issue #2582 single-PC HTTPS quickstart — locally validated, 2026-10-27

- User authorized implementation with **go** after initialization. Continued
  managed DAF `open` session `RedHatProductSecurity-ai-guardian-2582` on existing
  branch `2582`; preserved the initialization handoff and OpenWolf-owned updates.
  Qualified ticket was already read once. No temp-clone sync or new branch.
- Added four-step **Test HTTPS on your own PC** before advanced configuration in
  `docs/MULTI_DAEMON_TRAY.md`, a direct link from `docs/CONFIGURATION.md` and an
  Unreleased changelog entry. Exact Console labels and absolute-path examples;
  loopback-only exposure, private keys, explicit trust/SAN validation, tokens,
  REST versus Console-page HTTPS, restart, expiry and troubleshooting are clear.
  Existing listener/target examples and all advanced VM/CA/SSH/lifecycle content
  remain unchanged; generated `docs/notebooklm-export.md` was not edited.
- Validated exact documented generation/curl blocks on Linux, OpenSSL 3.5.8,
  curl 8.18.0, Python 3.14.7 and AI Guardian 1.21.0-dev. Used a disposable HOME
  and actual native `DaemonRestAPI` on an ephemeral loopback port, stopped after
  validation. Checked 0700/0600 modes, 90-day validity, SANs/extensions, repeat
  generation without overwrites, trusted health, actual client localhost identity,
  unauthenticated 401, untrusted-certificate and plaintext rejection, wrong SAN
  rejection and unsafe-key startup rejection. All checks passed.
- Harness: `/tmp/opencode/guardian-2582-validate.py`; private disposable artifacts:
  `/tmp/opencode/guardian-2582-08vuynzt`. All shell blocks pass Bash syntax checks;
  new links resolve, preservation/scope checks and whitespace checks pass.
  Console labels/save/restart behavior were inspected in source, not a graphical
  walkthrough. No installed daemon/Console/tray restart or configuration change.
- DAF note saved; all seven acceptance criteria and validation scope posted at
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2582#issuecomment-6441947570.
  A shell quoting error occurred before the first comment command executed;
  body-file publication succeeded once. Recorded the tooling/memory insertion
  corrections in buglog and the successful recipe learning in cerebrum.
- **Next:** user review and external DAF completion. All changes remain local and
  uncommitted. Documentation-only: no code tests, linters or local MkDocs build
  required. No live credentials accessed, security settings changed, commits,
  pushes, PRs or issue closure. OpenWolf owns automatic anatomy/memory bookkeeping;
  earlier entries are historical, not the active task.

## Issue #2587 SSH alias discovery — locally validated, 2026-10-27

- User authorized implementation with **go**. Continued existing branch `2587`,
  preserving the initialization handoff and OpenWolf-owned anatomy updates. The
  qualified ticket was already read once; no temp-clone sync or new branch.
- Added `daemon/ssh_config.py`: default-off workstation-global opt-in, optional
  literal prefix (empty includes existing aliases), concrete Host enumeration,
  bounded unconditional local config/`.conf` Includes, cycle/link/nonregular-file
  rejection and explicit Match/conditional limitations. No SSH/config predicate
  execution, IdentityFile reads, SSH config writes or cloud inventory access.
- Manager publishes separate cached candidates, not daemon targets; scans are
  single-flight. Tray pending count/direct review and loopback Web candidates
  reuse existing probe/full identity review, unchecked consent and enrollment.
  Tray retains shared native-first form dispatch and captured monitor placement.
  Browser dialogs use stable parents and per-review ownership across timer refresh.
- Private hostname-digest dismissal markers survive restart. Removal records a
  dismissal before deleting trust/closing owned tunnels; no remote stop. Missing
  config/edited aliases do not rewrite pairings. Manual Add remains deliberate
  recovery for dismissed aliases. Existing SSH/TLS authentication, dynamic ports,
  backoff, polling-only registration and one worker per saved destination remain.
- Synchronized schema/setup/example/all profiles, local picker settings, source
  docs/modal matrix/README/changelog and release-readiness coverage. Narrow local
  settings writes preserve unrelated config and reject malformed existing data.
- **1,025 related tests pass; one native-Windows DPAPI test skips on Linux.**
  Includes complete SSH/modal UX files, transport, manager/storage/tray/Web callers,
  discovery, schema/profile parity and related setup tests. Focused SSH coverage
  **91%**: parser 95%, manager 94%, storage 84%, tray 88%; artifact
  `/tmp/opencode/guardian-2587.coverage` (Web is omitted by project coverage policy).
- Black py310, Ruff, Pylint E, Mypy (320 source files), JSON/YAML/readiness paths
  and whitespace checks pass. Simplification reviewed. Fixed collection inference,
  concurrent shutdown narrowing and one new mock context-manager assertion;
  recorded lifecycle/parser learnings and iteration details in cerebrum/buglog.
- DAF notes saved; progress and pending checklist:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2587#issuecomment-6433069481.
- **Next:** review/publish via external DAF workflow, qualify fresh CI and actual
  macOS/Windows/GNOME/KDE desktop behavior, then explicitly authorized disposable-VM
  enrollment/cancel/restart/reconnect/offline/identity-change/removal. Windows
  OpenSSH/DPAPI and actual native rendering remain unverified locally; do not mark
  all qualification complete or close the issue from mocked contracts alone.
- Changes remain local/uncommitted. No live SSH, real credential retrieval,
  installed-daemon/tray restart, runtime/security configuration change, full-suite,
  integration/container run, commit, push, PR or issue closure. OpenWolf owns
  automatic anatomy/memory bookkeeping. Earlier entries are historical.

## Issue #2587 session initialization — 2026-10-26

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2587`; confirmed the active repository,
  existing branch `2587` and initially clean worktree. Read the qualified GitHub
  ticket exactly once. No temporary-clone sync applies.
- Config directory is `/home/itdove/.config/devaiflow`; hierarchical context
  markdown and skills are absent. Loaded DAF workflow/Git/OpenWolf guidance and
  read the project protocol, handoff and learning constraints. The project release
  skill is unrelated. Leave native conversation titles under DAF management.
- User requested initialization only; implementation has not started. Next:
  inspect existing SSH discovery/manager/UI seams, define a bounded local-only
  concrete-alias parser and dismissal semantics, then add opt-in asynchronous
  tray/local-Web discovery and direct review using existing enrollment/tunnels.
- Preserve explicit unchecked trust confirmation, independent SSH/TLS checks,
  cancellation, protected credentials and removal; enumeration must never execute
  SSH predicates or contact destinations. Reuse the shared modal dispatcher.
- Plan isolated parser/manager/tray/Web tests and the complete SSH UX contract,
  then documentation/changelog and synchronized configuration/readiness surfaces
  if adding settings. Run related tests only; leave full/platform/live qualification
  to CI and explicitly authorized manual checks.
- No code changes, tests, tracker updates, live SSH/credential access, runtime or
  configuration changes, commits, pushes or PRs. Only this handoff was updated;
  OpenWolf owns automatic anatomy/memory bookkeeping. Earlier entries are history.

## Issue #2584 / PR #2586 CI follow-up — local test fix, 2026-10-27

- User reported CI failure. Existing branch `2584` is synchronized at
  `feca82bacce1966003497fb072d86df9b7a815bb`; implementation is now committed in
  PR https://github.com/RedHatProductSecurity/ai-guardian/pull/2586, superseding
  the earlier local/uncommitted handoff below.
- Tests run `40407562273` failed the same two storage log assertions on Linux
  Python 3.10-3.14. Windows tests and other workflows passed. The sanitizer CLI
  file-not-found test leaves global logging disabled at CRITICAL; REST correctly
  rejects unsafe storage, but the subsequent storage tests captured no error log.
- Added `caplog.set_level(logging.ERROR, logger="ai_guardian")` in the affected
  storage test with pytest-managed restoration. No production code/security
  behavior or expected message changed; retained all exact-log, no-token, PID and
  permission-preservation assertions. The three-test reproducer failed before
  the fix and passes after it.
- **125 related tests pass** with sanitizer before storage, including complete
  storage, TLS and SSH UX files. Black py310, Ruff, Pylint E and Mypy (319 source
  files), bug-log JSON and whitespace checks pass. No full-suite/integration/container run.
- Next: publish this local test-only follow-up through the external DAF workflow
  and verify fresh CI. Existing live VM/SSH and native-platform qualification
  caveats still apply. No commit, push, CI rerun or runtime configuration change
  performed by this agent. OpenWolf owns automatic anatomy/memory bookkeeping.

## Issue #2584 private storage / REST diagnostics — locally validated, 2026-10-26

- User authorized implementation with **go**. Continued existing branch `2584`;
  preserved initialization and OpenWolf-owned anatomy changes. Ticket was already
  read exactly once; no temporary-clone sync or new branch was needed.
- New `storage.py` creates each missing directory component as `0700`, validates
  configured/resolved ancestry, and privately/atomically publishes configuration
  without clobbering intervening files. Human and JSON setup share that writer.
  Fixed early package logging and migration too: they create state before the
  Unix socket/token code. Existing XDG/shared directory modes stay unchanged.
- Token storage retains `_material_file` checks and adds linked-file/app-leaf,
  ownership and exact ancestor/mode diagnostics. Private token/PID temporaries use
  exclusive `0600` creation and owned-file-only cleanup; collisions are preserved.
  No weakened validation, automatic chmod, new dependency or configuration key.
- PID/IPC/CLI status separates working IPC from available/unavailable/disabled
  REST, with credential-free startup reasons and defensive legacy PID fallback.
  SSH probe/pairing distinguishes missing configuration, unsafe metadata and a
  live process without REST, without echoing remote errors or credential material.
- **926 related unit/UX tests pass** on Linux/Python 3.14 (850 together plus 76
  proactive/setup caller regressions), including complete
  storage, TLS, SSH and IDE-setup UX files. Fresh child processes test package
  import/setup/token/REST startup under umasks `0000`, `0002`, `0022`, `0077`.
  Storage helper coverage **93%**, setup writer **97%**, SSH tunnel **90%**;
  selected combined **92%**, `/tmp/opencode/guardian-2584.coverage`.
- DAF progress notes saved; implementation checklist and remaining qualification:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2584#issuecomment-6426511999.
- Black py310, Ruff, Pylint E, Mypy (319 source files), bug-log JSON and whitespace
  checks pass. Simplification reviewed. Fixed two preview-test assumptions about
  autouse fixture directories; final run validates the final source. One unrelated
  GLib deprecation warning remains. Source docs/changelog and learnings are updated.
- **Next:** review/publish through the external DAF workflow, qualify CI across
  supported platforms/Python, then verify setup/startup and HTTPS enrollment on an
  authorized disposable/reporter VM. Existing `.local` / `.local/state` `0775`
  ancestors require administrator review, not silent application repair. Missing
  configuration remains an independent prerequisite. Live SSH and native Windows
  ACL/macOS qualification are not established by these isolated tests.
- All changes remain local/uncommitted. No installed daemon restart, real remote
  credential retrieval, live SSH, runtime/security configuration change, full-suite,
  integration/container run, commit, push, PR or issue closure. OpenWolf owns
  automatic anatomy/memory bookkeeping; earlier sections remain historical.

## Issue #2584 session initialization — 2026-10-26

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2584`; confirmed existing branch `2584`
  and initially clean worktree. Read the qualified GitHub ticket exactly once,
  including the reporter's clarification about writable ancestors.
- Config directory is `/home/itdove/.config/devaiflow`; hierarchical context
  markdown and hierarchical skills are absent. Loaded DAF workflow/Git/OpenWolf
  guidance and read the project protocol, handoff and learning constraints.
  The project release skill is unrelated; no temp-clone sync applies.
- User requested initialization only; implementation has not started. Next:
  trace setup/state/token creation, provision new application storage with explicit
  secure permissions under supported POSIX umasks, and preserve fail-closed
  ownership, symlink and ancestor checks without altering existing shared paths.
- Also distinguish IPC liveness from REST availability, provide credential-free
  SSH diagnostics for missing configuration versus unsafe/unavailable metadata,
  and add isolated related unit/complete UX coverage for fresh setup/startup,
  unsafe storage, token publication/cleanup and visible failure states.
- The reporter's `.local`, `.local/state` and application state directory are
  all `0775`; fixing only the leaf cannot satisfy ancestor validation. Missing
  configuration is an independent precondition, not proof of this permission bug.
- No code changes, tests, tracker updates, credential access, live SSH, runtime
  or configuration changes, commits, pushes or PRs. Only this handoff was updated;
  OpenWolf owns automatic anatomy/memory bookkeeping. Earlier entries are history.

## Issue #2580 / PR #2583 CI follow-up — local fixes validated, 2026-10-26

- User reported CI failure. Branch `2580` was clean and synchronized at
  `b61d289c20b7afbd20840ec516c315e57985d23c`; prior SSH work is now committed
  upstream, superseding the local/uncommitted notes below. Failed Tests run
  `40376715481`: Windows 3.10/3.13 hung in `test_prompt_uses_native_first`;
  Windows 3.14 hit the recurring missing-Python PowerShell prerequisite timeout.
- Fixed proactive tests: six explicit OS/tray-mode cases mock all providers.
  Windows correctly skips native action/snooze and starts mocked Tk. Replaced
  whole-module-cache GUI patches with per-entry monkeypatches after reversed
  order exposed stale browser-opener mocks. No production modal policy changed.
- `uninstall.ps1` resolves only Python executables via `GetCommands` before
  invocation, avoiding missing-command module discovery. Preserves exit 2,
  error wording, version checks and no-mutation behavior. Regression proves a
  synthetic module is never imported; valid absolute/PATH-name cases work.
- **358 related unit/UX tests pass**, including complete IDE setup/modal/orphan
  UX files and all eight native PowerShell cases. Black py310, Ruff, Pylint E,
  Mypy (318 source files) and whitespace checks pass. Simplification reviewed.
  Portable PowerShell 7.6.9 (MIT, official SHA-256 verified) is isolated at
  `/tmp/opencode/guardian-pwsh-7.6.9/runtime`; no dependency/config changes.
- **Next:** publish local changes through external DAF workflow and verify fresh
  Windows CI. Linux PowerShell validation cannot qualify the hosted Windows
  runner or actual desktop UX. Do not close #2580's desktop qualification gate.
  No commits/pushes, issue closure, installed-tray restart, live SSH, support
  upload, full-suite/integration/container runs or runtime configuration changes.
  OpenWolf owns automatic anatomy/memory bookkeeping. Earlier sections are history.

## Issue #2580 SSH modal follow-up — earlier validation, 2026-10-26

- User found Add daemon via SSH still opening NiceGUI/Web Console and clarified
  Native → Tkinter → NiceGUI, one reusable dispatcher, and durable contributor
  guidance. Continued existing branch `2580`; it was clean at follow-up start.
- `ui/forms.py:run_form_flow` now binds complete simple-form providers to existing
  `run_modal`/`ui_provider_order`; no second ordering policy. `ui/native_form.py`
  implements Cocoa, WinForms and desktop-ordered zenity/kdialog text/checkbox
  controls. All steps retain one provider; Linux also pins its first native tool.
- SSH Add uses the adapter and tray-owned manager, keeps credentials server-side,
  shows full identity and unchecked mandatory trust, and captures monitor bounds
  before worker dispatch. Shared display-only text lives in `ui/ssh_pairing.py`.
  Manage SSH connection still opens the existing explicit Web Console page.
- `AGENTS.md` now requires shared dispatch, complete controls, startup-only retry,
  isolated toolkit state, privacy and regression tests. Modal docs include the
  reusable recipe/matrix/manual SSH checks; multi-daemon docs/changelog match.
- **839 related tests pass** in one final run, including complete affected SSH,
  modal and sandbox UX files. Form adapter coverage **100%**, native Python helper
  **96%**, selected combined **94%**; artifact
  `/tmp/opencode/guardian-2580-ssh-forms.coverage`. Black py310, Ruff, Pylint E,
  Mypy (318 files), JXA syntax, documentation links, buglog JSON and whitespace
  pass. Simplification reviewed. DAF note saved; progress posted at
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2580#issuecomment-6423560732.
  GitHub's POST response timed out, but a read-only comments check confirmed the
  comment exists; no duplicate POST was made.
- **Next:** review/publish the local follow-up through external DAF workflow,
  verify fresh CI, then qualify actual macOS, Windows, GNOME/zenity and KDE/kdialog
  rendering, focus, placement, cancellation/later-step errors and support consent.
  Native appearance and PowerShell runtime were **not** qualified; no live SSH
  destination, support upload, runtime/config change, installed-tray restart,
  full/integration/container run, commit, push, PR or issue closure by this agent.
  OpenWolf owns automatic anatomy/memory bookkeeping. Earlier sections are history.

## Issue #2580 modal policy — earlier implementation, 2026-10-26

- User authorized implementation with **go** after initialization. Reused branch
  `2580`; preserved its handoff and OpenWolf's automatic anatomy changes. The
  qualified ticket was already read once; no repeat lookup or temporary-clone sync.
- Shared `ui/display.py:ui_provider_order` defines capability-aware Native →
  Tkinter → NiceGUI order with exclusive preferences/headless behavior. New
  `ui/modal.py` executes it: only explicit pre-display unavailability advances;
  cancellation/None/false, interrupted waits and unknown/post-display errors stop.
- Applied to messages/About, proactive/setup/profile/snooze, ask CLI, plugin
  parameter forms, working-directory/auxiliary path pickers, target selector and
  sandbox forms/delete/upload/policy/log review. Full kdialog action menus retain
  snooze choices; native deletion explains the exact required name. Rich reviews
  skip native implementations that lose controls/text/errors. Existing support
  native user-only upload/publication consent and #2569's message protocol remain.
- Tk maps, opaque file panels, captured browser-startup state and explicit Cocoa
  startup/late-failure framing prevent a toolkit switch after visibility. Both
  Cocoa steps preserve placement. Proactive and sandbox browser dialogs use fresh
  child servers; sandbox complete review payloads cross UTF-8 stdin. Browser
  Later stays in the active client, not a second server. Progress keeps its
  documented captured-output fallback; target selection remains NiceGUI-only.
- `docs/MODAL_PROVIDERS.md` inventories families, platforms, full-control eligibility,
  placement/preference/host-path/progress/support exceptions and manual desktop
  steps. Source docs, example/schema descriptions, Web settings and changelog match.
  No new preference/config key, dependency or terminal/Textual UI was introduced.
- **Validation: 2,056 distinct related unit/UX/schema tests pass**, including full
  modal/About/setup/sandbox/support UX files. Focused runner coverage **94%**;
  shared policy/runner together **88%**, artifact
  `/tmp/opencode/guardian-2580-modal.coverage`. Black py310, Ruff, Pylint E, project
  Mypy (315 files), JSON, local docs links/nav, JavaScript syntax and whitespace
  pass. Reviewed simplification; recorded lifecycle/fixture/type learnings and bugs.
- **Next:** code review/publication through the external DAF workflow, then fresh
  CI and actual macOS, native Windows, GNOME/zenity and KDE/kdialog desktop checks:
  eligible toolkit ordering, complete controls, cancellation/post-map failures,
  tray focus, secondary-monitor placement and support consent. **These remain
  unqualified; do not mark the whole issue complete or close it from mocked tests.**
- DAF progress note saved; completed local work and remaining checklist posted at
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2580#issuecomment-6420706375.
- All changes remain local/uncommitted. No deliberate desktop qualification,
  support data collection/upload, runtime/security changes, full/integration/container
  runs, installed-daemon restart, commits, pushes or PRs. OpenWolf owns automatic
  anatomy/memory bookkeeping. Early test runs stalled on unintended Tk fallback
  reachability; fixtures now isolate those paths, and inspection found no remaining
  test-created dialog child. This is not visual QA. Earlier handoffs are historical.

## Issue #2580 session initialization — 2026-10-26

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2580`; confirmed existing branch `2580`
  and initially clean worktree. Read the qualified GitHub ticket exactly once.
- Config directory is `/home/itdove/.config/devaiflow`; hierarchical context
  markdown and hierarchical skills are absent. The discovered project release
  skill is unrelated. Loaded DAF workflow/OpenWolf and read the project protocol
  and handoff. This real-workspace development session needs no temp-clone sync.
- User requested initialization only; implementation has not started. Next:
  inventory modal capabilities/platform exceptions, define shared provider order
  and startup-failure outcomes, then address entry points, related unit/complete
  UX contracts, documentation and manual desktop verification instructions.
- Preserve Native → Tkinter → NiceGUI among capable providers, complete controls,
  explicit preferences, safe no-UI outcomes, isolated tray/multi-monitor behavior,
  no toolkit switch after display (#2569), and native user-only support consent.
  NiceGUI/Python 3.10+ remain required; do not reintroduce Textual.
- No code changes, tests, tracker updates, runtime/configuration changes, commits,
  pushes or PRs. Only this handoff was updated; OpenWolf owns automatic
  anatomy/memory bookkeeping. Earlier entries are historical, not active tasks.

## Issue #2552 SSH-managed HTTPS connections — local implementation ready, 2026-10-25

- User said **go** after initialization. Reused branch `2552`; verified #2551
  merged through PR #2578 with successful CI and available locally at
  `29f033f9`. Prior prerequisite/initialization entries below are historical.
- Added `daemon/ssh_probe.py`, `ssh_storage.py`, `ssh_tunnel.py` and
  `ssh_connections.py`: fixed read-only POSIX/Python probe, actual runtime port,
  strict existing OpenSSH host-key/agent configuration, owned loopback forwards,
  explicit TLS identity/CA/validity/leaf-pin verification on each request socket,
  capped reconnect backoff and bounded owned-process cleanup/cancellation.
  No HTTP downgrade, automatic identity replacement, sudo or SSH key storage.
- Tray **Add daemon via SSH** opens local-only Web Console pairing with an
  unchecked, explicit certificate/destination confirmation. Private POSIX files
  or whole-record current-user Windows DPAPI persist credentials/trust outside
  exported config. Removal invalidates saved generations without stopping the VM.
  New tray controls run off the GUI thread and reuse cached version monitoring.
- Poll-only `/api/register-tray` adds no inbound callback/workstation credential;
  prompts/decisions use initiated authenticated HTTPS. Snapshot SSH generations
  and per-daemon-instance prompt IDs prevent stale dialogs approving replacement
  connections/invocations. Updated old exact ID assertions and full UX contracts.
- Source docs/README/changelog and release-readiness SSH checks updated. No new
  dependency, CLI command, schema setting, AWS inventory or generated docs export.
- **Validation: 1,411 related unit/UX tests pass, one Windows-only DPAPI test skips
  on Linux.** Complete SSH/TLS/session-pause UX files pass. Focused SSH
  manager/storage/tunnel/tray coverage is **89%**, data at
  `/tmp/opencode/guardian-2552.coverage` (Web excluded by project coverage config).
  Black py310, Ruff, Pylint E, project-environment Mypy (314 files), workflow YAML,
  bug-log JSON and whitespace checks pass. Reviewed simplification and recorded
  security/fixture/tooling discoveries; OpenWolf owns anatomy/memory bookkeeping.
- DAF note saved. Progress/pending qualification:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2552#issuecomment-6402235207.
- **Next:** review/publish through external DAF completion, qualify CI, then use
  an explicitly authorized disposable VM for enrollment/cancel, restart/reconnect,
  occupied-port loss/recovery, remote decisions, rotation and removal. Native
  Windows DPAPI/client and macOS desktop qualification remain pending; do not
  claim all acceptance criteria or live VM behavior are qualified by unit tests.
- All implementation changes remain local/uncommitted. No live SSH connection,
  real remote credential retrieval, installed-daemon restart/security config
  change, full/integration/container suite, commit, push or PR creation occurred.

## Issue #2552 session initialization — 2026-10-25

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2552`; confirmed existing branch `2552`
  and initially clean worktree. Read the qualified GitHub ticket exactly once.
- Discovered config directory `/home/itdove/.config/devaiflow`; hierarchical
  context markdown and additional hierarchical skills are absent. Loaded relevant
  DAF/OpenWolf skills and project handoff/protocol. No temp-clone sync applies.
- User requested initialization only. Preserve the earlier decision to pause
  implementation until prerequisite #2551 is reviewed/merged and qualified.
  Its current upstream issue/PR status was not rechecked during initialization.
- **Next:** verify that prerequisite, then plan secure SSH enrollment/probing,
  verified loopback tunnel lifecycle, protected persistence and tray integration,
  followed by related unit/complete UX contracts, documentation and quality checks.
- No code changes, tests, live SSH/credential retrieval, runtime/configuration
  changes, tracker updates, commits, pushes or PRs. Only this handoff was updated;
  OpenWolf owns automatic anatomy/memory bookkeeping. Earlier entries are history.

## Issue #2551 / PR #2578 CI follow-up — 2026-10-25

- User published the implementation as `23a05033` on existing branch `2551`;
  started this follow-up with a clean worktree. Inspected Tests run `40204480454`.
- Linux reported seven deterministic failures; Windows 3.10/3.14 reported six
  (one POSIX-only contract skipped). Standard profile omitted TLS defaults, and
  earlier sanitize CLI tests left global logging suppressed before the TLS UX
  contracts. A focused reproducer plus four new parity cases failed 11 tests.
- Synchronized TLS defaults/comments across all four profiles. Raw profile
  validation exposed a related schema bug: `_comment` metadata was rejected.
  Permit string `_comment*` metadata only; unknown TLS settings still fail.
  Tests now validate raw setup/example TLS configs and every built-in profile.
- The complete TLS UX file explicitly establishes pytest-managed WARNING capture
  and restores prior logging state; retained exact-message/privacy/deny assertions.
  No production TLS/authentication changes, broad logging reset or relaxed checks.
- **609 directly related unit/UX tests pass**, including full schema/setup/profile,
  TLS and sanitizer files in reproducing order. Black py310, Ruff, Pylint E,
  project Mypy (308 files) and whitespace checks pass. No full/integration suite.
- **Separate native Windows gap:** Python 3.13 job `121202426797` timed out in
  `tests/unit/test_orphan_recovery.py:587` waiting for pwsh in the missing-Python
  prerequisite case. Other Windows jobs passed that area. Local pwsh is absent;
  the three focused cases skip. No speculative timeout/source workaround.
- **Next:** publish these local/uncommitted fixes through the external DAF flow,
  rerun CI, and verify the separate Windows subprocess stall does not recur.
  Original live private-VM qualification remains pending; #2552 stays paused.
- Updated source docs/changelog, memory and bug log. No live configuration changes,
  restarts, SSH, credential retrieval, commits, pushes, PR creation or CI reruns.
  OpenWolf owns automatic anatomy/memory bookkeeping; previous handoffs are history.

## Issue #2551 native HTTPS/trust — local implementation ready for review, 2026-10-25

- Managed DAF `open` session `RedHatProductSecurity-ai-guardian-2551`, existing
  branch `2551`. Initial worktree contained the #2552 handoff below; preserved it
  and earlier history. No hierarchical context markdown/skills or temp-clone sync.
- Added `daemon/rest_transport.py`: explicit CA/SAN/validity verification, TLS
  identity separate from TCP host/port, and optional additional SHA-256 leaf pins
  checked on the actual request connection before HTTP headers/body. No learned
  trust, redirects, proxies or HTTPS-to-HTTP fallback. Reuse this for #2552.
- Opt-in `daemon.rest_tls` listener leaves existing binds/HTTP defaults and token
  auth unchanged. Startup validates current certificate chain/matching private key
  before binding; warns within 30 days of expiry. Restart, not config reload,
  replaces the live listener/identity. PID adds `rest_scheme`, legacy default HTTP.
  Explicit local REST trust is `rest_tls.client`; manual targets carry `tls`.
- Routed local SDK registration, ask prompts, traces and local HTTPS discovery
  through verified transport. Remote hook/trace clients use the three documented
  trust environment variables. TLS failures never select trace fallback. Tokens
  are atomically created owner-only; unsafe material/token/trust files are rejected
  on POSIX. Windows requires operator-managed restricted ACLs; not locally tested.
- Synchronized schema, setup/default output, example, global-only Web controls,
  dashboard errors, source docs/README/changelog and release-readiness TLS gate.
  Added cryptography >=43.0.0 for certificate lifecycle checks; upstream dual
  Apache-2.0/BSD-3-Clause license verified. No new CLI commands/endpoints/SDK APIs.
- **Validation: 1,572 related unit/UX tests pass, no skips**, including complete
  TLS and session-pause UX files. Transport coverage **92%** at
  `/tmp/opencode/guardian-2551-tls.coverage`. Black py310, Ruff, Pylint E, project
  Mypy (308 files), JSON/YAML gate checks, bug-log JSON and whitespace checks pass.
  Reviewed simplification; recorded fixture/type/permission discoveries in memory.
- **Next:** review and publish through the user's external DAF workflow, then CI
  across supported Python/native platforms and actual private-VM pairing/renewal
  using the documented independently verified administrative channel. Loopback
  tests establish transport behavior, not live SSH/VM or native desktop validation.
  Keep #2552 paused until this prerequisite is reviewed/merged and qualified.
- No live configuration changes, installed daemon restart, SSH/credential
  retrieval, full-suite/container/integration runs, commit, push or PR. OpenWolf
  owns automatic anatomy/memory bookkeeping. Earlier handoffs remain historical.

## Issue #2552 SSH-managed remote daemons — paused for prerequisite, 2026-10-25

- Initialized managed DAF `open` session
  `RedHatProductSecurity-ai-guardian-2552` on existing clean branch `2552`.
  Read the qualified issue once; hierarchical context markdown/skills were absent.
- Confirmed prerequisite #2551 is **OPEN** and missing from this checkout:
  `daemon/rest_api.py` starts an HTTP-only listener; `DaemonTarget` has no TLS
  trust/identity metadata; clients do not separate the remote TLS identity from
  the TCP connection address. Existing HTTPS URL support is not that foundation.
- **User chose a separate prerequisite session.** Pause #2552; complete and merge
  #2551 first, then resume SSH enrollment/tunnel work against its tested TLS/trust
  interfaces. Do not substitute plaintext or disabled certificate verification.
- DAF blocker note saved using the explicit session name; automatic active-session
  note lookup failed while the backend session ID was `pending-capture`.
- No implementation changes, tests, live SSH/credential retrieval, runtime or
  configuration changes, commits, pushes, or PRs. Only this handoff was updated;
  OpenWolf owns automatic anatomy/memory bookkeeping. Earlier handoffs are history.

## Issue #2568 / PR #2577 third CI follow-up — 2026-10-25 UTC

- User published prior fixes as `aa209b3` on branch `2568`; started clean. Latest
  **Tests `40143187399` is green across the full matrix**, as are all other
  workflows except Smoke `40143187400`. Smoke's Linux/macOS jobs pass; Windows
  isolated contracts pass and now reach the actual package-first lifecycle.
- Windows preview after CI package removal retains four MCP entries because
  recovery omitted setup's `pythonw.exe -m ai_guardian` launch. OpenCode embeds
  that whole string in command-array element zero. The same gap silently retained
  Windows hooks. Added real Windows-resolved setup writer regressions for five
  MCP hosts and substituted-launch parity for ten hook schemas; **22 positive
  reproductions failed before the fix**.
- Engine now recognizes windowed Python and only the exact legacy module argv
  prefix, reusing string parsing to preserve compound/quote rejection. Unknown
  modules, mixed commands, malformed quoting/types and ambiguous paths remain
  retained. No broad argv splitting, launcher execution or package dependency.
  New tests verify preview, third-party fields, exact backups and repeated no-op.
- **253 related unit/wrapper/policy/complete-UX tests pass, no skips**, including
  native PowerShell 7.6.8 on Linux. Engine coverage **93%**,
  `/tmp/opencode/guardian-2568-ci-third-fixes.coverage`. Black py310, Ruff, Pylint E
  and project/helper Mypy (308 files) pass. Reviewed simplification; only a small
  ownership-parser change, no setup/runtime refactor. Updated source docs/changelog,
  cerebrum and bug log; OpenWolf owns anatomy/memory updates.
- DAF note saved; latest diagnosis and pending Windows lifecycle checklist:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2568#issuecomment-6391481224.
- **Next:** publish local/uncommitted changes through the user's external DAF
  workflow, rerun Windows actual package-first Smoke lifecycle. This patch is not
  yet qualified on native Windows, and live host behavior remains unverified.
- No local lifecycle/package removal, live cleanup, process signaling, security
  changes, full-suite/container/integration execution, commit or push.

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
