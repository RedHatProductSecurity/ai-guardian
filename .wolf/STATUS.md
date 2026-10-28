---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS - ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-10-28 (UTC)

---

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
