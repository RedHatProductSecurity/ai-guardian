# Cerebrum

> OpenWolf's learning memory. Updated automatically as the AI learns from interactions.
> Do not edit manually unless correcting an error.
> Last updated: 2026-10-29

## User Preferences

- **2026-10-29 — Tray pause hierarchy (#2620):** Keep the familiar daemon →
  project directory → session hierarchy inside one modal, with an inline
  Pause/Resume action at every level. Do not replace it with separate scope/target
  dropdowns. Latest correction: replace the separate Pause buttons/shared duration
  selector with a duration/Resume dropdown on each row. Selecting a duration is
  the explicit pause action. Increase the default window and fit/wrap row labels
  to the viewport so action controls are visible without horizontal scrolling.
  Inert initial dropdown values must not act; inherited pauses remain explicit.
  Screenshot follow-up: keep detailed instructions/lifetime notes collapsed under
  Show help/Help so the initial view shows daemon/project/session controls first.

- **2026-10-28 — Doctor scanner inventory:** List all supported secret engines with
  configured/installed status. Warn only when secret scanning is enabled and the
  built-in `toml-patterns` engine is omitted; show other optional unselected engines
  informationally to avoid turning ordinary intentional choices into warnings.
  In the Console, preserve embedded newlines in diagnostic details so each engine
  status renders on its own line rather than collapsing into one label line.
  The Engine Tester is intentionally narrower: list only explicitly configured
  engines, do not auto-add built-in or installed engines, and explain this in the UI.
  Pattern-server inventories should render one entry per line with
  `patterns_endpoint` included. In Engine Configuration, provide auto-saving
  checkboxes for the selected daemon's installed external engines and a distinct
  built-in TOML option; preserve advanced JSON edits and settings.

- **2026-10-28 — #2612 Console auto-save:** Global-only policy does not need a
  special Save button. Follow the Console's existing auto-save-on-change behavior
  for password-likelihood enable/outcome controls. Viewing the page is not consent;
  changing outcome must not enable analysis. Save only the changed field to the
  selected daemon's global policy, retain read-only/failure guards and serialize
  rapid changes in the same card so the two controls do not overwrite each other.

- **2026-10-28 — #2588:** Secret-source integrations must be optional and
  disabled by default, with explicit human opt-in; do not infer vault/account
  database access authorization from discussion of possible providers.

- **Per-daemon support (#2597/#2614):** Keep the local tray-host Contact supports
  action only when no daemon targets are discovered. With targets present, show
  exactly one source-bound action in each daemon menu (including the local daemon)
  and no duplicate root host action. Remote diagnostics use the source environment,
  while destination choice, per-file review, ZIP export and both public consent
  stages stay on the desktop. The local daemon retains its bundled Maintenance
  submenu in multi-daemon mode.

- Tray target ordering: keep local daemons first, then sort all other displayed
  daemon names alphabetically ignoring case. An empty SSH alias `(0)` indicator
  should disappear; retain discovery warnings and the always-available settings.

- New modal entry points must reuse a shared dispatcher, never repeat the
  Native → Tkinter → NiceGUI cascade locally. Keep the implementation checklist
  in `AGENTS.md` and the reusable recipe in `docs/MODAL_PROVIDERS.md` so future
  modals follow it. The tray's Add daemon via SSH must not jump straight to the
  Web Console; implement its complete native interaction first.

- About must show **Author: Dominique Vernier (ITDoVe)**, with the compact
  **(ITDoVe)** link targeting the user-confirmed **https://github.com/itdove**.
  Do not display the full profile URL or infer a different author name from the
  package's team attribution or the profile handle.

- Support submission must have a standalone AI Guardian CLI path because the
  agent CLI/MCP integration itself may be broken; do not require or auto-start
  the daemon for `support` commands. Also expose it as a global tray menu entry,
  available independently of daemon health.
- Support bundles should include sanitized CLI configurations, and explicitly
  invite users to delete unwanted prepared files before sending. A tray-prepared
  or locally exported bundle must still be findable by a subsequent terminal
  `support send`; explain local export versus actual support submission plainly.
- Tray support must open a native modal, not a shell: per-file View buttons and
  include checkboxes, GitHub-only category selection, read-only final destination,
  and Cancel/Send actions. Keep result details open until the user closes them;
  preserve the separate exact-publication consent for GitHub.
- Latest support UX: call the tray action **Contact supports**, immediately above
  **About**. Provide Your message, Select all / Deselect all, selected-file count,
  and aligned scrollable file rows rather than uneven embedded text widgets.
- **Newest support correction (#2567), superseding default-none:** sort files
  alphabetically (case-insensitive), but keep doctor.json first and checked by
  default for new lists. All other files start unchecked. Respect saved explicit
  choices, including an unchecked Doctor; never re-check after user deselection.
  Remove the generated title. GitHub requires a non-whitespace title and message;
  ZIP/legacy review requires a message. Require at least one file too before
  Create ZIP / Send is enabled. Draft preparation may leave fields blank for
  native user completion; enforce mandatory fields before creating ZIP/upload.
  Retain explicit reviewed choices when reopening the same bundle. Do not permit
  message-only ZIP/publication. Contact supports must open normally in front,
  not minimized; request restore/raise/focus for all support dialog modes.
- ZIP completion must offer **Open destination folder** in the native file
  browser. File View needs **Wrap lines** and a horizontal scrollbar when
  unwrapped. Keep the final public-consent checkbox visible and explain why
  Publish publicly is disabled; never auto-check consent to enable publication.
- **Latest destination decision (#2567) supersedes the tray override:** tray,
  CLI and MCP respect explicit local/S3/GCS/email recipients. Empty/missing
  destinations default to GitHub. Its native chooser offers **Create ZIP only**
  or **Gist + Discussion**. The latter requires configured GitHub credentials;
  explain when none exist, but keep ZIP available.
  Never automatically initiate login or escalate permissions.
  **Newest first-screen correction:** use a read-only Destination dropdown and
  a **Next** button, not individual destination buttons, so more destinations can
  be added later. Default to local ZIP. Selection alone must not advance; Next
  opens the chosen review page, never authorizes upload/publication. For missing
  GitHub credentials, disable Next for that selection but allow switching to ZIP.
  ZIP creation is local-only, is not encrypted, and never rewrites the saved
  destination or means support was contacted. Retain the original bundle for
  a later `support send`; the ZIP itself survives temporary-bundle cleanup.
- Logs **and violations** cover only the last 12 hours. Include every complete
  sanitized violation record in that window; do not impose a newest-100 count
  or byte crop. Only log copies may be truncated. All collected non-log files
  stay complete and fully viewable through next/previous pages, not a size refusal.
  View/ZIP/Send must not apply different size crops.
- The user is concerned that public diagnostic posts will discourage reports.
  Explain GitHub access/visibility accurately; diagnostics are now opt-in with
  at least one selected file required. Do not implement
  a new private destination or permission scheme without agreement. The user
   has now approved user-owned unlisted Gists instead of inline diagnostics:
   approve exact upload first, then the exact Discussion with the actual link in
   a separate Diagnostics section. Preserve the user message. Unlisted is not
   private; deletion cannot retract copies/forks. After upload, cancellation or
   failure must show the Gist URL for management/deletion; reuse verified receipts
   on retry, never silently upload duplicates or fall back to inline content.
- Dev install must use `uv tool install --editable .` — `uv tool install --force .` copies a snapshot; subsequent source changes are NOT reflected in the binary.
- When DAF metadata labels a repository issue as JIRA but the user identifies it as GitHub, use the repository-qualified `gh issue view` flow.
- Pi OpenShell remains unqualified; local v0.1.2 validation must use supported Codex or OpenCode paths instead.
- Sandbox documentation should lead with short, case-based setup recipes and
  prerequisites for each runtime/authentication path; keep lifecycle and
  advanced reference details below the first-use steps.
- OpenShell middleware documentation should lead with the OpenShell operator
  boundary: run the external Rust service, register it in the gateway, apply a
  complete `network_middlewares` policy with OpenShell, and create ordinary
  sandboxes independently. AI Guardian must not expose middleware lifecycle
  commands or sandbox middleware flags.
- OpenShell sandbox create tests should pass an explicit non-interactive command
  such as `-- /bin/true`; omitting it intentionally attaches an interactive
  shell, so use `sandbox connect` only after create returns.
- The tray's **Apply policy to sandbox** profile selector should be wide enough
  to distinguish long discovered profile summaries; its help should explain
  that the selected profile is an overlay. Let users edit the full merged YAML
  in the review dialog; validate edits, preserve required base controls, and
  require explicit Replace policy approval before applying. Avoid
  progress-window interstitials for fast preparation steps, and keep successful
  sandbox operation details open until the user closes them.
- In sandbox target menus, place **Connect** and **Manage sandbox** immediately
  after **Pause...**.
- Tray sandbox initial configuration uses one exclusive source choice:
  Host/default, Profile, Host config directory, or Latest saved snapshot. Show
  only the matching profile/directory input.

<!-- How the user likes things done. Code style, tools, patterns, communication. -->

## Key Learnings

- **2026-10-29 — Inline pause layout/dropdowns:** Content-sized scroll canvases
  plus fixed label widths can push row controls offscreen when monitor placement
  clamps a window. Use opt-in `tk_scrollable_content(..., fit_width=True)` with
  labels wrapping to their actual widget width; keep existing two-axis behavior
  for other callers. Row dropdowns need inert initial values and explicit selection
  events only. NiceGUI must check `event.value is not None`, not truthiness,
  because `0` is the valid indefinite-pause choice. Resume remains row-local.

- **2026-10-29 — macOS validation baseline (#2620):** In this Mac/Python 3.12.11
  environment, project-uv Mypy reports existing `clipboard.py:39` missing return
  and `ask_dialog.py:530` unreachable code. Both reproduce against an unmodified
  HEAD archive with the same interpreter/dependencies. The daemon variant of
  support's linked-project-configuration UX test also reproduces its
  `ValueError: Linked configuration omitted` using baseline sources. Do not weaken
  safe file-reading checks or change these unrelated files to make pause-modal
  validation appear green. Standalone `pylint` is installed; the project dev extra
  does not provide its module on this machine.
- **2026-10-29 — Local OpenWolf CLI:** This Mac installation exposes `scan` and
  `bug search`, but no `memory log` or bug-add command in help. The earlier Linux
  memory-log guidance is installation-specific; do not invent unsupported CLI
  commands. Preserve existing metadata when applying the protocol's manual notes.

- **2026-10-29 — JSON Schema test fragments:** When a nested schema contains
  references to root-level definitions, validate the test instance through the
  full root schema; validating only the fragment loses the reference scope.

- **2026-10-29 — DAF issue labels:** `daf git update --labels` replaces the
  entire label set. Preserve existing labels when adding a status label, or
  feature/milestone labels can be removed.

- **2026-10-29 — NiceGUI Engine Config callbacks:** `update:model-value` editor
  callbacks are synchronous, while value-change callbacks may be async. UX fakes
  should call the editor callback directly and await only async control handlers.

- **2026-10-28 — OpenCode prompt diagnostics:** MCP `sanitize_text` exercises
  SecretRedactor, not the prompt hook's `check_secrets` backend. A successful
  sanitizer redaction does not prove the admitted prompt was scanned/detected.
  Doctor verifies generated files, not runtime hook activation; tool refusals
  likewise do not establish prompt enforcement. A paused proactive MCP check
  explicitly leaves mandatory hooks active, so do not conflate the two.

- **2026-10-28 — Cross-agent secret-leak triage:** If both Codex and OpenCode leak,
  compare the shared scanner/config/runtime path before blaming one adapter. A
  direct positive-control scan proves backend capability only, not that either
  application's prompt hook ran; an absent violation cannot distinguish hook
  delivery failure from a value-specific miss. Verify current remote-main ancestry
  before calling a branch change a regression. A profile-directory mismatch is not
  itself causal when the active and canonical prompt-hook code is identical. Do
  not restart a service attached to the live session; use a fresh non-secret
  controlled prompt or correlated event evidence.

- **2026-10-28 — Distinct daemon pause states:** MCP proactive action-gating can be
  paused while hook scanning remains active, but `DaemonState.paused` is a separate
  global pause that makes `DaemonServer._handle_hook_request()` return its
  security-instructions-only response before content scanning. Check local daemon
  status, not only MCP `proactive_level`; `mcp_proactive_level=low` can coexist with
  global `paused=true`. HTTPS on the local REST listener does not route hook
  requests over HTTPS: absent `AI_GUARDIAN_DAEMON_URL`, hook CLI uses local IPC.
  A pause observed after a user's unpaused test is not evidence of pause during the
  prompt; use timestamped event metadata. Direct scanner probes may create persisted
  `secret_detected` violations with unknown IDE identity, so don't mistake them for
  app-hook evidence or run further probes against user state without isolation.

- **2026-10-28 — Explicit secret engine list overrides defaults:**
  `secret_scanning.DEFAULT_ENGINES` is `toml-patterns` then Gitleaks, but a saved
  `engines` array replaces that list. The internal TOML scanner contains the
  OpenAI `sk-proj-` rule. If one workstation explicitly selects Gitleaks only and
  another selects TOML patterns/LeakTK/Gitleaks, same branch does not mean same
  detection coverage. Compare engine selection and availability before blaming OS
  or hook transport. Built-in TOML patterns need no external scanner install.

- **2026-10-28 — #2613 CI capture/guidance:** A sanitizer CLI test disables global
  logging, so new privacy tests must establish pytest-managed caplog levels and
  assert the safe diagnostic is actually emitted. Reproduce by putting
  `TestSanitizeCommand::test_file_not_found` first; do not alter runtime logging to
  hide test-order state. Adding a violation enum also affects both complete
  guidance contracts: suspected-password findings need specific private review,
  explicitly no persistent-exception snippet, not a generic config example.
- **2026-10-28 — #2613 CodeQL metadata sources:** SARIF traces can start at enum
  labels or factories/notices whose names resemble raw credential variables.
  Inspect source-to-sink flows before changing logging or declaring a leak. Use
  accurate diagnostic/location names, validate report metadata to numeric locations
  and fixed labels, preserve external type/rule strings and test no-value output.
  Avoid analyzer suppressions. Delimiter splitting avoids repeated phrase regex
  analysis without changing the existing ASCII candidate-class acceptance.
  Only a fresh GitHub analysis establishes CodeQL success.
- **2026-10-28 — GitHub job logs:** `gh run view --log-failed` waits for the entire
  workflow even when an individual job is complete. Raw `gh api .../logs` can be
  refused for terminal control sequences; preserve that safeguard and use the
  normal run-log renderer after completion. Investigate independent check-run
  annotations/SARIF while the remaining jobs finish.

- **2026-10-28 — #2612 private Ask boundaries:** Reusing generic Ask needs more
  than registry opt-in: it can read a source line when matched text is empty and
  can persist exception patterns. Password-likelihood uses a value-withheld,
  operation-scoped Allow Once / Block variant, no source/editor controls, and
  rejects persistent decisions before writer/cache callbacks. Raw Ask remains
  fail-closed for SDK/static checks without UI. Incomplete analysis is not a
  positive finding but still needs the selected approval/deny outcome. Callers
  must honor the resolved decision rather than the original should_block flag;
  private canonical audit must likewise record the resolved state.
- **2026-10-28 — Ask remote display and timeout:** Explicit headless must prohibit
  all dialogs/forwarding; automatically detecting no local display must NOT skip
  a registered workstation tray. Separate preference from display eligibility.
  Once a remote prompt is queued, timeout is a terminal security fallback, not
  pre-display unavailability that permits another local prompt. Mocked remote
  queue/decision and SSH contracts do not establish actual pre-model prevention.

- **2026-10-28 — #2612 remote Ask reuse:** The user pointed out that existing
  Ask already supports remote daemons. Verified `ui/ask_dialog.py` queues remote
  prompts and `tray/app.py` polls/displays/returns decisions for container,
  Kubernetes, manual and SSH targets; SSH uses authenticated poll-only registration
  in `daemon/multi_client.py`. Reuse this flow rather than design another remote
  approval system. Password likelihood currently declares `supports_ask_mode=False`;
  adding Ask/default-Ask needs scanner-specific privacy/enforcement wiring and
  tests, not a new transport. Source/contract evidence is not live host qualification.

- **2026-10-28 — #2612 integration boundaries:** The shared content pipeline
  covers prompts/file content, not arbitrary Write/Edit/Bash argument values.
  Use bounded nested string traversal rather than JSON serialization (which
  escapes contextual quotes), and never treat a tool's policy-shaped data as
  trusted configuration. Explicit SDK null/missing policy must not fall through
  to global opt-in. Distinguish an incomplete analysis from positive detection
  while still warning or enforcing the deliberately selected outcome.
- **2026-10-28 — #2612 privacy/budgets:** Enforce finding caps during extraction
  for both contextual and ambiguous spans, not just when emitting sorted results;
  otherwise same-line overlap work grows unnecessarily. A logging wrapper cannot
  protect exception privacy if the underlying ViolationLogger swallows and logs
  the raw exception first; test real persistence failures as well as mock raises.
  Guard the actual save callback's read-only state, not only button eligibility.
- **2026-10-28 — scanner mock import order:** `test_scan_pipeline` imported
  PostToolUse while scanner decorators were active in its source-command test,
  retaining a mocked `run_secret_scan` in the module. Reproduced 11 failures when
  the existing PostToolUse UX file ran afterward. Import the consuming module at
  collection, then patch its attribute with `patch.object`; do not change or
  silence credential behavior to hide test-order contamination. Static config
  sections sharing a page also need an explicit section-to-route mapping because
  the constants module otherwise assumes one section per slug.
- **2026-10-28 — #2612 qualification:** The frozen synthetic/template and local
  performance gates pass, but 6/20 unadjudicated repository windows have advisory
  flags (none block-eligible). Do not claim representative benign quality, zero
  false positives or prevention based on those constructed datasets or hook JSON.
  Keep experimental/default-off status, independently adjudicated held-out corpus
  and actual model-boundary host/version/platform evidence as open release gates.

- **2026-10-28 — detect-secrets packaging:** PyPI 1.5.0 is a roughly 120 KB
  universal wheel with Requests/PyYAML base dependencies already present in the
  project requirements; optional gibberish/word-list extras are separate. Verified
  Apache-2.0 at upstream `v1.5.0/LICENSE` (the unprefixed tag URL does not exist).
  Default installation and default activation are separate decisions. Conditional
  bundling after #2612 qualification is not permission to install now or turn on
  the whole backend; verify offline behavior, compatibility, false positives and
  model-boundary handling first. Latest PyPI release date alone is not proof of
  either compatibility, maintenance quality or a security defect.

- **2026-10-28 — #2612 wording:** Distinguish AI Guardian's present internal
  `scanners/engine_builder.py` from the optional third-party `detect-secrets`
  package/executable it registers. Only that optional backend was absent from
  the checked development venv/PATH, not the builder source or built-in engine.
  State the exact checked environment; do not imply a live daemon was inspected.

- **2026-10-28 — heuristic versus entropy filter:** Bundled `TomlPatternsScanner`
  runs pattern matching before Shannon-entropy filtering; existing entropy support
  is not a standalone arbitrary-password detector. Synthetic five-style probes
  found assignment/JSON password cases but not standalone/natural-language
  examples. This is illustrative coverage, not a recall estimate. A supported
  `detect-secrets` backend already offers upstream entropy heuristics, but was not
  installed/tested here; evaluate existing capabilities before duplicating them.
  Joined-word password strength does not imply detectable password identity.
  User then authorized issue creation only, not code: #2612 targets 1.21.0
  subject to evidence gates and is independent of the backlog known-value/source
  epic. #2588's eight children/dependencies remain unchanged; #2612 is related
  but has no parent/blocker dependency.

- **2026-10-28 — #2588 approved decomposition:** Published native parent #2588
  and children #2604-#2611 with `known-secret-protection` and backlog, no 1.21.0
  target/replacement release. Actual dependency edges are design #2604 -> core
  #2605 -> five providers #2606-#2610, plus Linux #2606 -> remote #2611.
  `gh issue create --parent ... --blocked-by ...` supports both relationships in
  this installed CLI; verified through GraphQL, not merely textual references.
- **2026-10-28 — user source refinements:** Remote known-secret matching may
  consume a source reachable in that runtime only through separately opted-in,
  human-provided supported access/permissions; do not forward workstation values,
  indexes or unlock sessions. Bitwarden #2609 starts with portable password-
  protected encrypted JSON snapshots. Official docs distinguish account-
  restricted exports tied to the account key; those are excluded initially.
  Documentation of encryption is not qualification of an automated decryption
  SDK/license. Retain ciphertext only as the user-owned source, never decrypted
  files/index caches; snapshot reload must not masquerade as live-vault refresh.

- **2026-10-28 — #2588 design-review boundary:** The current issue starts with
  Bitwarden Password Manager, not an OS-native provider, and already requires
  ephemeral state, human authorization, full-span redaction, safe sinks and
  fail-closed required egress. The OS-native-first split was initially a review
  suggestion and is now explicitly approved/published as recorded above. Native credential stores do not
  automatically cover Firefox/Bitwarden vaults; provider enumeration, item
  accessibility and user-session/lock behavior must be qualified separately.
  Fingerprints do not automatically solve embedded-value matching, and
  encrypting memory with a same-process key does not defeat runtime compromise.

- **Published-artifact documentation gate (#2585):** On 2026-10-28 production
  PyPI still reported 1.20.0; its SHA-256-verified wheel lacked native TLS/SSH
  modules and TLS schema. Keep the Ubuntu VM guide explicitly upcoming with a
  provisional 1.21 constraint and unconfirmed first published version; recheck
  PyPI before removing that gate. #2591/#2592 are merged development UI, not yet
  published features. Source walkthroughs, shell checks and synthetic TLS cannot
  qualify a fresh PyPI VM **and workstation**, live tunnel lifecycle or desktops.
- **Synthetic TLS documentation fixtures (#2585):** Send explicit Content-Length
  so current curl does not depend on abrupt TLS EOF to delimit HTTP/1.0 bodies.
  Consume complete successful responses; record expected disconnects only during
  deliberately failing SAN/untrusted-certificate checks, not on positive paths.

- **Release announcements (#2595):** Dispatch announcement preview/retry before
  constructing `ReleaseHelper`: version auto-detection can write its configuration.
  Use an explicit stable version, exact public Release and production PyPI
  wheel/sdist availability, not warning-only shell completion, as publication proof.
  Resolve category IDs and exhaust Discussion pagination through existing `gh`;
  ambiguous create responses permit read-only reconciliation, never blind reposts.
  Keep this maintainer flow separate from support categories/consent.
- **Release-helper typing (#2595):** Standard source-only checks exclude the
  hidden helper, so run Mypy/Pylint on it explicitly too. Do not reuse an exception
  alias as a later loop variable in the same CLI function; Python deletes that
  alias after `except`, and Mypy rejects the shared binding. Use a distinct
  validation-error name and retain exact existing CLI message tests.

- **Tray monitor origin (#2581):** Freeze display-only identity/work area before
  worker dispatch; retain it in child payloads and every follow-up, then resolve
  current geometry by identity rather than a later pointer/focus or stale offset.
  pystray's GTK widget is `_menu_handle`, not abstract `_menu`; keyboard activation
  can use local `_status_icon` geometry, but a remote AppIndicator may expose none.
  Use explicit manual-move guidance for unknown origins/Wayland/browser reuse.
  Cocoa inventory/placement should unwrap `NSScreenNumber`; keep AppKit out of a
  Tk child before Tk initialization. Native children must revalidate after startup.
- **Small-screen review (#2581):** Clamping the outer window is insufficient if
  fields or consent are clipped. Shared scrollable body + reserved footer keeps
  actions and full wrapped, initially unchecked support consent reachable. Support
  can load stdlib-only display helpers from the installed sibling path with runpy;
  never include credentials, approval objects or monitor metadata in diagnostics.
- **Targeted UI coverage/toolchain (#2581):** The default coverage config omits
  `src/ai_guardian/ui/*`; `--source=ai_guardian.ui.monitor` alone still collects no
  data. Use a dedicated coverage configuration for this helper (91% verified).
  Run project Mypy through `uv run --extra dev`; standalone global Requests stubs
  can produce unrelated errors absent from the declared project environment.
- **OpenWolf session summary:** Use supported `openwolf memory log` instead of
  manually editing the hook-owned memory file. It requires `--session` explicitly;
  obtain the active native agent ID from `daf info`, not an invented ID or another
  session's most recent conversation.

- **Support path checks / CodeQL (#2597, PR #2600):** The local project-config
  branch must use the same unlinked-regular-file reader as source collection.
  Reject links in the original path/ancestors before lexical normalization can
  hide a linked `..` component. Use pure lexical `os.path.abspath`, then check
  directory containment with a trailing separator (reject sibling-prefix matches).
  Do NOT resolve untrusted file/parent paths while computing this guard:
  `Path.resolve` dereferences the filesystem and CodeQL flags those pre-validation
  calls too (#324/#325), even when the eventual open is correctly guarded (#323
  fixed). Upstream Python CodeQL models string `startswith` guards, not
  `Path.is_relative_to`; consume the checked absolute string for the eventual
  open rather than leaving a parallel unchecked Path flow. Keep local files
  complete with an explicit optional byte limit; remote/CLI/import callers still
  supply their bounds. All unit/lint passes do not establish a green CodeQL gate;
  get the latest annotations/SARIF and verify the newly published commit.
- **Coverage environment, verified recovery:** `uv run --extra dev --with coverage
  python -m coverage ...` runs the complete related suite with pytest-asyncio
  without changing project dependencies/lockfiles. Coverage is Apache-2.0.
  The global coverage command still lacks the project's async plugin; do not
  weaken/skip async tests to make that mismatched environment appear green.

- **SSH support connection timing (#2597 reporter follow-up):** The connection
  manager retains the same target object while replacing `ssh_tunnel` on initial
  connect and reconnect. A menu-render-time copy can retain None/a closed tunnel
  while the current status poll displays a filled circle. Bind the displayed
  saved identity at render, capture its current verified tunnel at click, and then
  freeze that generation before worker dispatch. Require the original object and
  saved ID still to match; never substitute a replacement by display name. Cover
  offline-to-connected, reconnect, reordering, removal and in-flight reconnect.
- **Collection subprocess import roots (#2597):** Isolated Python omits user-site
  dependencies needed by editable/user installs. Anchor the package to `__file__`
  and restore only the running interpreter's enabled user-site path. Do not use an
  unrestricted `importlib.metadata.distribution()` search: project .dist-info can
  select an attacker-controlled dependency directory. Exercise the bootstrap with
  actual isolated Python, hostile cwd/metadata, enabled and disabled user sites.
- **Nested test patch teardown (#2597):** A fixture's `patch()` context and a
  test's `monkeypatch` of the same collector can unwind in the wrong order,
  leaving the fixture mock installed for later tests. Use the shared monkeypatch
  restoration stack for both. Run the real-collector source-isolation regression
  after the fixture tests as well as alone; isolated success misses this leak.
- **Remote support wire boundary (#2597):** Transfer only sanitized complete text
  with narrow inert file names, hashes, strict metadata and byte/file-count limits;
  do not extract source archives or accept destination/context/consent objects.
  Validate before desktop writes, re-sanitize into a new protected directory and
  bound JSON pretty-print expansion too. Record source omissions/provenance and
  running/collector versions. Fail large collections rather than crop structured
  data. Headless sources never need the desktop's publication credentials.

- **Windows SSH cwd regression test (#2592 / PR #2596):** Workstation paths use
  native separators; `str(Path("/workstation/home"))` is not a POSIX string on
  Windows. Keep remote VM expectations POSIX, but compare local defaults against
  the mocked home value. Parametrize that value with `PurePosixPath` and
  `PureWindowsPath` so Linux runs reproduce Windows-style assertions without
  changing global `os.name` or constructing unsupported concrete Windows paths.
  Check both native and slash-normalized workstation-home strings are absent
  from SSH commands. All three Windows CI versions failed this test-only mistake;
  the production directory isolation did not need changes.

- **SSH menu compatibility and working directories (#2592):** A healthy remote
  daemon from main does not publish new feature-branch stats or PID fields.
  Asking the user to upgrade main cannot add them. Read missing MCP state from
  that VM's existing authenticated `/api/config?scope=global`, not workstation
  settings or the daemon's active project overlay. Keep optional capability-query
  failures separate from daemon connectivity. The fixed read-only Linux probe can
  identify the same-user daemon interpreter from procfs argv/executable identity;
  preserve its venv link, never guess PATH or publish context before TLS/auth.
  `get_working_dir(name)` defaults to **workstation** `Path.home()`: SSH must load
  only explicit saved selections and otherwise retain `None`/remote home, including
  after repeated discovery or resetting to empty. Display remote paths literally,
  never shorten against workstation home. Keep SSH terminals open after exit so
  diagnostics can be read. Mock tests without the discovery step missed this bug.

- **Tray SSH discovery settings (#2591):** Keep the narrow workstation-global
  writer in `daemon/ssh_config.py`; Web service entry points still enforce the
  loopback boundary before delegating. `run_form_flow` can retain full native
  support without a new renderer by using an optional enable checkbox/Continue,
  then optional prefix/Save; do not mark the checkbox required or reject an empty
  prefix. No mutation before Save, no manager/probe access in settings, and only
  signal the existing refresh event afterward. An open Web settings panel must
  follow external saves only while its fields equal its last displayed/saved
  snapshot; capture submitted values before awaiting I/O so edits during Save
  remain unsaved. A one-time `settings_loaded` flag leaves those controls stale.

- **SSH alias inventory boundaries (#2587):** Use a deliberately bounded local
  parser, not `ssh -G` or a library that evaluates config predicates. Process
  unconditional Include files as an inline stream; a Host/Match in a fragment
  changes later scope. `glob.iglob` still materializes directory entries, so bound
  `os.scandir` explicitly as well as file, byte, depth, pattern and alias counts.
  Keep candidates out of DaemonTarget/registration and persist hostname-digest
  dismissals separately from pairing credentials. Local picker settings must not
  inherit a remote daemon/project route or replace malformed unrelated config.
  Timer-refreshed NiceGUI candidate rows must not own identity dialogs; use a
  stable container and review-token ownership so old hide events cannot release
  a newer review. `preferred_ui` supports auto/tkinter/nicegui/headless, not a
  separately saved native preference; auto supplies native-first ordering.

- **POSIX storage creation precedes daemon startup (#2584):** Package import
  initializes logging and may migrate state before `_setup_unix_socket` runs.
  Fix creation there too; `mkdir(mode=0o700, parents=True)` does not restrict
  intermediate parents or repair an existing `0775` directory. Create each
  missing component explicitly, but keep creation separate from credential-path
  validation so an existing unsafe ancestor can produce truthful IPC-only status.
  Never chmod existing XDG/shared parents. Human and JSON setup had independent
  writers; route both through the same private atomic publisher. Test umasks in
  subprocesses **before importing the package**, with disposable HOME/config/state
  paths. Do not mock a nonexistent IDE discovery method: setup's current seam is
  `_discover_unconfigured_ides`. PID status fallback must tolerate valid non-object
  JSON, and exclusive temporary PID/token publication must preserve collision files.
  Preview non-mutation tests must snapshot the initial fixture state: the shared
  autouse fixture already creates `auto_config`, `auto_state` and `auto_cache`.
  PR #2586 repeated the known sanitizer logging-order failure in both storage
  error cases: explicitly call `caplog.set_level(ERROR, logger="ai_guardian")`
  before asserting logs. Validate with sanitizer first, not just the storage file
  alone; keep exact-message/privacy checks and production logging unchanged.

- **Windows CI / modal test isolation (#2580, PR #2583):** The native action
  prompt is eligible on Linux/macOS, not Windows. Mocking only native while
  requesting auto UI lets Windows enter a real Tk mainloop. Cover platform and
  tray/non-tray combinations and mock every reachable renderer. For fake GUI
  modules, use `monkeypatch.setitem(sys.modules, ...)`, not a whole-dictionary
  `patch.dict`: restoring the latter removes lazily imported modules but leaves
  package attributes pointing at stale objects, so later dotted mocks can miss
  the actual browser opener. Reversed related-test order exposed this leak.
- **PowerShell missing-interpreter discovery (#2583):** Executing a nonexistent
  bare Python name can enter module discovery. Exact-name `Get-Command` still
  imports matching modules with `-CommandType Application` or `-ListImported`;
  a locally scoped autoload preference did not prevent this in the probe.
  `$ExecutionContext.InvokeCommand.GetCommands(name, Application, false)` enumerates
  only executables without module imports. Take its first PATH result, invoke the
  resolved `.Path`, and keep the existing version/error/non-mutation contract.
  A synthetic manifest/module marker proves absence of imports; test both absolute
  interpreter paths and names on PATH. Portable PowerShell under `/tmp/opencode`
  can run these isolated unit tests on Linux, but does not qualify Windows. Its
  official `hashes.sha256` asset uses UTF-16; decode the BOM before verification.

- **Reusable simple-form flows / SSH follow-up (#2580):** `ui/forms.py` binds
  renderers to the existing `run_modal` dispatcher; it does not introduce another
  order. Latch visibility after a completed child step so later startup failures
  cannot restart host input elsewhere. `NativeForm` pins zenity/kdialog after the
  first result; Cocoa/WinForms scripts distinguish startup failure from later
  failure with an envelope separate from user field values. Their UTF-8 stdin
  transport must not change locale decoding for existing native commands. Kdialog
  uses `--ok-label` for input/checklist buttons, not `--yes-label`; escape backend
  metadata for Qt's rich-text auto-detection. Only display-safe identity text goes
  to renderers; keep pairing credentials in the tray-owned manager. Management
  remains an explicit Web Console page. Mocked contracts and JXA syntax checks do
  not qualify actual macOS/Windows/GNOME/KDE desktop behavior.

- **Modal policy and lifecycle (#2580):** `ui/display.py:ui_provider_order`
  selects Native → Tkinter → NiceGUI only among complete implementations;
  explicit preferences are exclusive. `ui/modal.py:run_modal` retries only
  explicit pre-display unavailability. None/false, cancellation, unknown errors
  and post-display failures are terminal. Native command stderr alone is not
  startup proof. Keep support's native user-only consent outside this cascade.
- **Visibility and browser ownership (#2580):** A withdrawn Tk parent never
  maps when its owned file panel opens: latch possible visibility before entering
  that panel. Capture the lifecycle in the browser-startup closure, since callback
  context can differ, and latch before requesting a tab. Cocoa's own startup
  status must become terminal before makeKeyAndOrderFront/runModal, including
  failures in Later. Isolate each tray sandbox/proactive browser server in a fresh
  child. Full reviews/logs can exceed argv limits; stdin with explicit UTF-8 pipes
  preserves complete content. Build NiceGUI's second snooze dialog directly in
  the active client's event handler, not through another ui.run/server restart.
- **Modal regression isolation (#2580):** When adding fallback tiers, replace
  every reachable desktop/browser implementation in tests; mocking only the
  former first provider can open real Tk panels and hang. Patch shared policy
  selection rather than old module-local imports. Pass subprocess input explicitly
  rather than expanding a string-typed kwargs dict that breaks Mypy's overload
  resolution. Unit/UX mocks and JavaScript syntax checks do not qualify actual
  native appearance, focus, monitor placement or support publication consent.

- **SSH connection boundaries (#2552):** Pair a user-entered OpenSSH alias only
  after explicit local Web Console confirmation; probe metadata is private
  protocol data, never diagnostic text. Reuse `rest_transport` CA/SAN/validity
  verification plus a paired leaf pin on each actual request socket. A local
  forwarded port or process liveness check cannot establish remote identity.
  Save credentials/trust outside exported config, with owner-only POSIX files
  or whole-record current-user Windows DPAPI. Do not patch global `os.name` in
  Linux Windows-path tests: patch the module's platform flag/DPAPI seam instead.
- **SSH shutdown and remote prompts (#2552):** Track probe Popen handles and
  readiness/enrollment tunnels before publishing targets. Invalidate before
  termination, interrupt the transport before waiting for its request lock, and
  refuse authentication/persistence after cancellation. Snapshot the SSH target
  before prompt fetch/display; decisions stay on that generation. A forward can
  survive a daemon restart, so prompt IDs also need a per-instance nonce, not a
  resettable counter alone. Poll-only registration never sends a workstation
  callback address/credential. Mock a tray menu's locally imported dialog before
  building its callbacks, not just before invoking them. Live VM and native
  desktop qualification remain separate from mocked SSH/loopback TLS tests.

- **TLS CI parity and log isolation (#2551 / PR #2578):** Include `rest_tls`
  defaults and byte-identical comment metadata in all four built-in profiles,
  not just setup/example output. Validate raw TLS objects against the schema
  before stripping comments: listener and client objects allow only string
  `_comment*` metadata in addition to their known settings, not arbitrary keys.
  `test_sanitizer.py::TestSanitizeCommand::test_file_not_found` alone reproduces
  the full-suite TLS UX failures by leaving `logging.disable(CRITICAL)` active.
  Use `caplog.set_level(WARNING, logger="ai_guardian")` in that UX module's
  fixture; pytest enables capture and restores the previous global disable
  threshold during teardown. Do not drop exact-message/privacy assertions or
  change production TLS behavior to accommodate test-order state.

- **Single-PC HTTPS recipe validation (#2582):** OpenSSL 3.5.8's self-signed
  `CA:FALSE` server certificate works as explicit dedicated trust for both curl
  and `TLSOptions` on Python 3.14. Keep both localhost DNS/127.0.0.1 IP SANs,
  server-auth usage and SKI/AKI extensions in the documented recipe. Extract its
  shell blocks for validation in a disposable HOME against the real native REST
  listener on an ephemeral loopback port; never restart/reconfigure the installed
  daemon just to validate documentation. Console fields require absolute paths,
  not shell-variable expansion. Fresh private mktemp directories avoid overwrites.

- **Daemon REST TLS foundation (#2551; prerequisite for #2552):** Reuse
  `daemon/rest_transport.py`: `TLSOptions` carries `ca_file`, `server_name` and
  an optional additional `certificate_sha256` leaf pin. The URL is only the TCP
  address; TLS SNI/SAN verification uses the explicit identity. CA, validity and
  hostname checks remain mandatory even with a pin. Compare pins in the actual
  connection's `connect()` before HTTP headers/body, not in a separate preflight
  connection. Never learn trust from discovery, follow redirects, or use proxy
  transports. TLS failures are terminal for trace transport selection as well.
  `daemon.rest_tls` configures the listener; its `client` subobject is explicit
  local REST trust. Manual targets carry their own `tls` object. PID metadata
  adds only `rest_scheme`; missing means legacy HTTP, never a discovered trust
  anchor. Listener/certificate reload requires restart; clients load trust anew.
- **TLS/config test boundaries (#2551):** The daemon schema is under
  `schema["definitions"]["daemon"]`, not the root properties reference. Mock
  daemon states need `get_pause_status()` returning JSON data. Own explicit SSL
  context attributes in HTTPS subclasses: the stdlib private `_context` field
  is absent from type stubs. NiceGUI cards are not disableable containers; disable
  individual controls, with a backend scope guard. Token reuse/empty-file fixtures
  must create owner-only files. Host-resolution tests must stub token provisioning:
  patching `os.path.exists` globally also changes `Path.exists` on Python 3.14,
  otherwise falsely claiming a missing token exists. Do not weaken material
  checks to accommodate these mocks. New token files use exclusive 0600 temporary
  creation and atomic replacement, and preserve pre-existing collision files.

- **Windows setup launch parity (#2568 / PR #2577):** `_resolve_binary_path()`
  returns a `pythonw.exe -m ai_guardian` string on Windows, not necessarily the
  console executable. JSON/TOML MCP writers store that string as `command`, and
  OpenCode historically embeds the whole launch in argv element zero. Recovery
  must recognize the windowed interpreter and this exact legacy module form,
  while reusing compound/quote rejection and refusing to split arbitrary argv
  executable strings. Template-only bare-command parity missed both this MCP
  failure and silently retained Windows hooks. Exercise real MCP writers with a
  Windows-resolved launch for Claude/Cursor/Codex/Grok/OpenCode, and run all hook
  schemas through `_substitute_command`. Assert preview immutability, exact
  backups, third-party retention, idempotence and unknown-module/compound denial.
- **Native Windows cache correction (#2568 / PR #2577):** The earlier directory-only
  isolation is insufficient: PowerShell's `Platform.CacheDirectory` uses .NET
  `GetFolderPath(LocalApplicationData)` on Windows and ignores child `LOCALAPPDATA`
  overrides for startup optimization. Share the environment factory between unit
  tests and the CI-only lifecycle. For test children only, set
  `DOTNET_MultiCoreJitMinNumCpus=7FFFFFFF`: CoreCLR parses this DWORD as hexadecimal
  and declines the optional startup profile below that unattainable CPU count.
  A decimal max-int string can overflow and restore defaults. Keep the selected
  HOME/USERPROFILE/config/state and complete file snapshots unchanged. Remove
  case-insensitive inherited aliases before setting child overrides; Windows
  `os.environ` uppercases keys, so a plain mixed-case dict update can duplicate
  them. No product startup or security settings need changing. Primary sources:
  PowerShell `CorePsPlatform.cs`/`ConsoleHost.cs`, dotnet/runtime
  `multicorejit.cpp`, `clrconfigvalues.h`, and `clrconfig.cpp` (hex parsing and
  DOTNET-before-COMPlus precedence). New regression assertions must cover inherited
  values, upper/mixed-case names and an actual child environment/home snapshot.
- **Windows recovery metadata / PowerShell CI (#2568):** CPython can expose file
  creation time through Windows `lstat().st_ctime_ns` but metadata-change time
  through `fstat()` (python/cpython#157671). Compare before/after handle snapshots
  and before/after path snapshots separately; do not drop timestamp or identity
  checks. Native PowerShell writes its own startup/module caches even with
  `-NoProfile`; isolate those in a separate disposable runtime directory rather
  than filtering files inside selected configuration homes out of preservation
  checks. An early HTTP auth rejection with an unread POST body can reset Windows
  clients; use a zero-body auth regression and assert no parsing/hook processing.
  Local dev dependencies omit pytest-cov/coverage: use the ephemeral coverage CLI
  for focused reports, without adding a project dependency.
- **Standalone orphan recovery (#2568):** Lifecycle recovery must not import
  `ai_guardian` or depend on its pinned executable/interpreter surviving. The
  companion `scripts/ai_guardian_recovery.py` uses Python 3.11+ stdlib TOML parsing;
  keep its finite user/project inventory aligned with setup via parity tests.
  Copilot stores managed events at top level; Codex MCP is TOML, and OpenCode V2
  uses `mcp.servers`. Verify surgical edits against the complete parsed document,
  and make versioned-host E2E assertions generation-aware rather than applying
  one registry key to every version. Retain ambiguous sources, and never convert
  ordinary security denials into cleanup. Empty project arguments must not expand
  to cwd. Native PowerShell
  `Write-Error` with Stop throws before a later `exit 2`; use explicit stderr for
  prerequisite diagnostics. Windows backups inherit directory ACLs (0600 is
  POSIX-only). Use separate missing-runtime evidence, not launcher-import tests,
  for live-host claims; native Windows and actual host qualification remain CI/QA.
- **MkDocs navigation checks:** `mkdocs.yml` contains intentional tagged extension
  formatter names. PyYAML SafeLoader rejects these tags before reaching nav;
  inspect with `yaml.compose` or BaseLoader without constructing/importing them.
  This needs no MkDocs build and is not a defect in the existing site config.

- **ServiceNow BYOG proposals (#2572/#2573):** Keep potential platform
  integrations in `docs/POTENTIAL_INTEGRATIONS.md`, separate from supported IDE
  integrations. Existing REST/scanning building blocks are not a validated BYOG
  connector. No integration development is planned until there is interest and a
  suitable ServiceNow test environment. The vendor documentation URL returns a
  JavaScript application shell to a text fetcher; a successful HTTP response is
  not specification or interoperability validation.

- **Linux tray message lifecycle (#2569):** A message-provider process remains
  alive while the user reads; its runtime is not a startup timeout. Remove
  reading deadlines for shared Linux/Tk messages, and treat native exit 1 with
  empty stderr as ordinary dismissal rather than launching another provider.
  The isolated Tk child reports its completed root's first Map event with a
  captured readiness marker: only failures before mapping permit native fallback;
  later failure/interrupted waits are terminal. Log provider/stage/exit status,
  not raw child output or exception text that can echo the message. Current About
  uses Tk for its author link; the older ticket's native-only trace predates that
  change. Mocked lifecycle tests in a TTY do not prove the original desktop
  rendering/decorations flash is resolved; obtain actual desktop details/recording.

- **About foreground handoff (#2567):** On the user's KDE Wayland/XWayland
  desktop, the reported immediate minimization corresponded to a still-Normal
  About window. Do not infer actual iconification from appearance alone. Its
  initial focus request preceded safe mapping and clearing topmost did not raise
  it again. Build withdrawn, finish layout/set a temporary hint, deiconify/lift,
  then focus/grab after idle and restore once more when clearing the hint at
  200ms. Guard late callbacks and unsupported hints with TclError handling; no
  repeating focus loop or permanent topmost. A synthetic mapped window remained
  Normal/viewable/focused at 75/300/700/1100ms with topmost off after 200ms;
  actual tray-click handoff still needs the user's confirmation.

- **Support draft/required fields (#2567):** preparation/CLI/MCP default the title
  to blank and allow an incomplete sanitized draft for native completion. Validate
  required title/message only on reviewed submission, before ZIP or Gist creation.
  Distinguish absent/None selection from an explicit saved empty list: preselect
  only available doctor.json for a new list, never override a saved deselection.
  Sort case-insensitively with a Doctor-first key across collector/review/Gist
  lists. Use an Entry StringVar write trace and Text <<Modified>> event (resetting
  the flag) so typing, paste, and clearing update action state, not just checkbox
  changes. Real ttk cget("state") may return a Tcl object; assert semantic state
  with instate([...]) in hidden Tk tests rather than comparing it to a Python str.

- **Gist support/credential gating (#2567):** `gh auth status` does network
  validation and the installed CLI has no `--no-refresh` flag. Use local,
  captured `gh auth token --hostname github.com` only for availability, and verify
  the pinned account via discovery after the public route is chosen. No login,
  refresh, token output or permission escalation. Classic/OAuth scope headers
  can reject known missing `gist` access; GitHub enforces the actual operations.
  Separate upload and Discussion journals prevent duplicate non-idempotent
  mutations across processes, retain known Gist URLs on partial failure, and
  must not be included as diagnostics. Check regular files/link counts before
  truncating receipt updates. Annotate the initially empty nested Gist payload
  dict before using it in the bounded-content sum so project Mypy can infer it.
- **Support View/result controls (#2567):** `ui/file_opener.py` prefers editors,
  so it is wrong for opening the ZIP's containing folder. The isolated stdlib-only
  child uses click-only os.startfile on Windows, open on macOS, xdg-open on Linux,
  passing an absolute existing ZIP's parent as one argv element without a shell;
  suppress launcher output so it cannot corrupt the JSON response. Preserve ZIP
  and result on startup failure. Reserve preview navigation/consent rows before
  expanding text. For ScrolledText, put its frame and horizontal scrollbar in a
  weighted grid; grid_remove/grid toggles the bar without losing placement.
  Wrap state persists across page renders, and rendering never edits the source.
- **Support selection/focus (#2567 latest):** None/missing inclusion state means
  only Doctor is initially checked (new correction), not every file. Start
  Create ZIP/Send disabled until required text and file selection are complete; update from
  individual and bulk callbacks, and validate actual remaining diagnostics in the
  backend before adding the message. Keep saved explicit selections and public
  consent separate. Build Tk withdrawn, finish layout, deiconify/lift, request
  focus after idle, and clear the temporary topmost hint; tolerate rejected hints
  and closed-window callbacks. Mocked activation checks and hidden real-Tk state
  tests do not establish actual compositor/macOS activation. Update old public
  test responders to select files explicitly, and give megabyte payload parameters
  short pytest IDs to avoid enormous failure output.
- **Project type-check environment:** use `uv run --extra dev python -m mypy`.
  The standalone global executable has different Requests stubs and reports
  unrelated errors in untouched skill_discovery/secret_validator; project Mypy
  passes all 306 files without changing those modules or suppressing checks.
  Black is installed as a standalone executable, not in the dev extra. Global
  coverage lacks pytest-asyncio: run the complete related suite (including Web
  settings) in the project uv environment, and focus global coverage on the
  synchronous reporting/native/MCP/UX files rather than changing async tests.
- **Support excerpts (#2567 latest correction):** Never share a truncation budget
  across configuration/structured files: it invalidates JSON and drops important
  final fields. Only .log copies may be shortened, preserving collector metadata.
  Complete non-log files take priority over the remaining public log budget; if
  complete selected files exceed GitHub limits, fail clearly without shortening
  them. View uses bounded UTF-8 pages to reach the whole prepared copy, never
  refuses a complete file for size or shows a smaller excerpt than Send. Final public redaction/preview
  remain separate. Do not reverse/truncate violation diagnostics as if they were
  the ai-guardian.log text stream. Original files are unchanged.
- **Public support privacy (#2567):** GitHub discussions inherit repository
  visibility; there is no private category/report in a public repository. Normal
  creation requires a signed-in viewer, not org membership, subject to interaction,
  announcement-category and API-credential restrictions. Private-repo access is
  not private per-customer ticket isolation. Redaction does not hide every private
  hostname, permission rule or infrastructure detail; no silent alternate upload.
- **ZIP choice and paging (#2567):** Offer local ZIP before constructing a
  GitHubClient, with native file selection and sanitized message. Stage checked
  registered files using safe regular-file reads, preserve nested names and full
  bytes, create a private no-overwrite archive outside temporary staging, and
  return zip_only without claiming delivery. Public consent remains separate.
  Reuse the shared bundle review for legacy tray routes. Pager offsets must
  reflect consumed UTF-8 bytes (not characters); preserve partial codepoints for
  the next page, validate actual EOF strictly and keep previous-page navigation.
  Synthetic hidden Tk construction verifies widgets, not mapped visual QA.
- **Violation window (#2567):** Support must read/filter the canonical audit log
  by timestamp, not call the newest-100 UI listing before filtering. Stream JSONL,
  keep all valid records inside inclusive UTC cutoffs, exclude future/undated/
  malformed records, sanitize copies and leave the source unchanged. Preserve
  newest-first review ordering without cutting individual records or JSON.
- **Size-limit fixtures (#2567):** A long repeated no-whitespace string may be
  sanitized down to a short redaction, so it does not reliably exercise body size.
  Use benign ordinary prose for real-sanitizer size UX tests; do not mistake the
  resulting unexpected approval stage for a broken size check.
- **Tk selection callbacks (#2567 latest):** A bulk/count callback closes over
  an initially empty choices dict, so Mypy needs `dict[str, tk.BooleanVar]`.
  Hidden real-Tk construction checks catch Tcl/style errors but do not establish
  mapped layout, visual quality, desktop activation, authentication or consent.
- **Support local-export hand-off (#2567 follow-up):** Do not clean up a local
  export as a completed support submission while leaving its persisted ref at a
  deleted temp directory. Rebind to the protected retained copy, keep destination
  and original TTL, and never restore removed files. Recover old exact exports
  only within their original TTL; explicit `--bundle` can reuse retained files.
  Legacy `status: sent` denotes transport completion; `delivery_status: local_only`
  and human **Exported locally** messaging must distinguish it from a ticket.
  Match confirmation wording to legacy email-routing precedence, including `@`.
- **Support CLI config copies (#2567 follow-up):** Reuse setup path resolution,
  not an independent recursive home-directory crawl or CLI/MCP calls. Flat,
  individually removable JSON diagnostic copies work with legacy transports too.
  Redact nested credential containers/env/header values before text sanitization,
  and omit unsafe input without echoing parser errors or raw text. Claude's
  `.claude.json` contains account/history state: select only its MCP mapping.
  An explicitly heterogeneous sanitizer dict needs `dict[Any, Any]` so Mypy does
  not infer every value as a header dictionary from its first assignment.

- **Tray support modal (#2567 follow-up, supersedes terminal launcher):** Use a
  single-flight background worker and installed isolated Tk child, not Tk inside
  the tray process or a shell. View only bounded registered prepared files as
  inert text. Persist validated inclusion choices before sending, stage only
  checked files for legacy transports, and bind public choices to final consent.
  Open the chooser before binary/size validation so unwanted files can be
  excluded. Preserve original configurations and don't claim a narrower local
  selection overwrote an existing retained export. Failure guidance must point
  to retained originals, not removed staging. A mailto hand-off prepares a ZIP,
  not a sent email; retain legacy status but expose manual_required honestly.
  Keep the action global and collect local tray-host diagnostics only.
- **Native modal tests/tooling (#2567 follow-up):** Patch notifications where
  imported in `tray.support`, not just their defining module. HTTP response
  context managers need MagicMock. Use `functools.partial` for per-row callbacks
  to avoid strict Mypy's lambda inference failure. Black is installed as its own
  CLI, not as a module in the uv dev environment. Measure UI coverage explicitly:
  project coverage defaults omit `ui/*`; use a separate no-config report and
  name only the directly related modules. No real desktop was exercised.

- **Reviewed support (#2567, latest correction supersedes tray override):**
  Empty/missing destinations use GitHub, offering local ZIP or Discussion. Tray
  honors explicit configured recipients, just like CLI/MCP, without changing
  saved settings or older bundle routes.
  The standalone recipe is `ai-guardian support send --prepare`, independent of
  MCP/daemon startup; public posting always retains trusted native final consent.
- **GitHub Discussions delivery (#2567):** GraphQL `DiscussionCategory` exposes
  `slug`, repository membership, and `isAnswerable`. Q&A must be answerable;
  Bug Reports need not be. `createDiscussion` accepts title/body, not a ZIP
  upload, and `clientMutationId` does not guarantee idempotency. Bound inline
  delivery and persist pre-mutation intent for duplicate/uncertain outcomes.
- **Support proposal replacement (#2567):** Local `support-context.json` is a
  proposal, not an additional diagnostic attachment. Publish only the edited
  context, while retaining original metadata in the approval fingerprint;
  otherwise text the user removed can reappear in a duplicate diagnostic block.
- **Support approval/import isolation (#2567):** Launch the installed native
  review script by absolute path with isolated Python, and keep that child
  stdlib-only. Exact-content approval stays private to the backend; no terminal
  or client-supplied approval is an equivalent trusted-user event.
- **Bundle test isolation (#2567):** Mock Doctor and SmokeTestRunner collectors
  in bundle unit tests. Real optional OCR/scanner imports can emit native
  diagnostics into captured CLI JSON depending on test collection order. Keep
  deterministic clocks module-local, not on shared `time.monotonic`.

- **Release 1.20 preflight (#2563):** `release.sh` calculates from the latest
  production tag and requires clean main or a release branch; even a dry run
  rejects a DAF issue branch. The user launches it outside the agent after
  preparation review/merge. Test tags route `publish.yml` to TestPyPI without
  changing metadata; changing only the tag cannot replace an uploaded version.
  Match workflow evidence to source/tag SHA and require a successful conclusion
  (`gh run watch --exit-status`). Final script completion can follow verification
  warnings and is not publication proof. Rust version checks require an explicit
  `--version`, including `--check`. Preserve the release issue until every gate
  and deliverable is verified.

- **OpenShell maturity versus qualification (#2564):** Upstream `0.x`/pre-1.0
  maturity, supported release/protocol ranges, and exact client/provider live
  qualification are distinct. Keep experimental notices alongside preferred/default
  recommendations and before setup; do not interpret range support or middleware
  readiness as a production-stability guarantee or relax security requirements.

- **OpenShell pending-operation deletion (2026-10-20):** On v0.1.3, `ag-codex`
  deletion was refused with a persisted `driver_operation_pending` flag and null
  deadlines. NVIDIA/OpenShell#4409 reports the exact symptom after lost driver
  ownership, including graceful shutdown/startup-recovery interruptions. The
  installed CLI has no force-delete flag. A missing backend container does not
  prove a pending external request cannot still complete; do not blindly clear
  the claim or recommend restart loops. Separate a matched symptom from a proven
  local root cause, and obtain approval before gateway downtime/state repair.

- **Classifier log privacy (PR #2562):** CodeQL can trace scanned content into
  SSRF hostname diagnostics. Even parsed IP text is not inherently safe logging
  metadata: IPv6 scope IDs retain arbitrary input. Use a constant diagnostic for
  the policy decision, without raw/decoded destinations or configured ranges;
  test actual DEBUG records for all embedded formats and synthetic scope text.
  Do not dismiss the alert or change analyzer settings to address a log sink.

- **Embedded SSRF destinations (#2559):** `_is_ip_blocked` is shared by literal,
  resolved-destination, and redirect checks. Classify the native IPv6 address
  plus protocol-defined mapped/6to4 endpoints and both Teredo roles; the server
  can receive control traffic, while the client is the tunneled endpoint.
  Reuse explicit policy, not `is_private` (whose prefix classifications vary
  across Python versions), and keep numeric metadata singletons consistent with
  literal host checks. Compare `ipaddress` objects in fixed-layout tests: newer
  Python renders mapped addresses using dotted IPv4, older versions use hex.
  No-network regression matrices establish classification, not routing or a
  population-wide false-positive rate.

- **CodeQL bundled-path false positive (PR #2561):** A test lookup of
  `BUNDLED_FILES["secrets"]` is heuristically classified as a credential source;
  the Python SARIF trace then follows that file path into parser logs. For
  bundled-file test fixtures, use the explicit `DATA_DIR / "secrets.toml"` path
  like the existing bundled TOML tests. Inspect source-to-sink traces before
  changing runtime code or interpreting a logging alert as a real token leak.

- **NuGet/Sonar pattern fixtures (#2558):** NuGet V4 encodes its identifier
  and GUID password separately; concatenating bytes before base32 encoding
  produces the wrong layout. Use scoped ASCII case folding for token alphabets
  while leaving identifier boundaries Unicode-aware. The pattern-server loader
  used by secret scanning returns an optional dict, not a `(config, error)`
  pair. Scanner-runner results expose `error_message`. Normal SecretRedactor
  preserves six leading/four trailing characters; PatternCache's similarly
  named strategy preserves four/four, so test the correct component's contract.

- **Pattern research evidence (#2554):** Review path-specific commit histories,
  not repository push timestamps. OWASP's general LLM Top 10 landing page still
  lists 2025 while its separate 2026 resource page is current. Distinguish a
  bundled-engine standalone credential gap from generic assignment detection or
  external-engine coverage. A no-network address-classification probe is not
  proof of live network exploitability. Do not infer a fixed credential layout
  from inconsistent vendor examples; keep those candidates deferred.

- **Support-image CLI pin maintenance (#2555):** Both support Dockerfiles now
  bundle pinned OpenCode V1. Update the version-check fixtures, manual-report
  expectations, both container README tables, and `docs/OPENCODE.md` runtime
  rows together. Documentation consistency regressions guard these surfaces.
  Codex candidate installation/version/help success does not qualify OAuth
  `account/read` workspace routing or middleware denials; require the operator's
  successful local qualification before advancing its pin.
  When splitting that deferred update into a follow-up, move the
  `openshell-cli-version-update` label with it: the version-health workflow
  selects an open issue by that label, so retaining it on both creates ambiguity.

- **KDE closed-before-clicked delivery (#2549 follow-up):** Native DBus tracing
  showed root `closed` preceding the selected item's `clicked` by about 3 ms.
  Immediate refresh on close can remove the exported action ID, silently losing
  any selection (even About), not just scoped pauses. Keep the refresh guard
  through a short GLib click-delivery grace period and invalidate older close
  callbacks when a popup reopens. Root open/close events were present; expanding
  observation to every descendant was not the missing fix. Regression tests
  must model native-ID removal and closed-before-clicked order, not only invoke
  descriptor callbacks directly.

- **Scoped tray menu state (#2549):** Headers, Status, and scoped controls must
  share one target stats cache. Invalidate it before actual native rendering and
  after scoped requests; deferred AppIndicator refreshes must fetch fresh state
  after close. Snapshot stable session metadata/pause flags and directory state,
  excluding Linux countdowns and last-activity noise. A nonempty REST response or
  completed socket exchange is not success: require the matching scoped status
  and no error. An error field with `None` is not itself an error.
- **Rendered tray targeting (#2549):** Do not re-resolve a selected scope by its
  list slot on click: expiry, new sessions/projects, and discovery can reorder
  lists while the old popup remains open. Retain the rendered stable key/path
  and daemon target until the native menu renders again; never broaden failure.
- **Scoped tray UX registries (#2549):** Direct session registration does not
  populate `active_project_dirs`; initialize project tracking separately with
  `check_project_config`. For hook enforcement tests, obtain canonical stable
  keys with `track_hook_session`, not a guessed adapter class prefix borrowed
  from CLI fixtures. Otherwise a hook creates a different session and appears
  to ignore the selected pause. Keep deterministic clocks module-local.

- **Scoped CLI UX isolation (PR #2550):** Process-wide `_connect` mocks also
  intercept leaked/background tray subscriber threads during full-suite CI.
  Bind the opt-in test transport to the owning thread and return no connection
  to other threads; retain strict foreground call-count assertions. Use real
  protocol framing rather than globally mocking encode/decode. Replace the
  daemon-state module's clock namespace, not the shared standard-library
  `time.monotonic`, so unrelated thread deadlines keep using the real clock.
- **Numeric GitHub branches:** `gh pr view 2547` interprets the value as a PR
  number, not the numeric branch name. Discover the PR with `gh pr list --head
  2547` first, then use its actual PR number for CI diagnostics.

- **Scoped short CLI controls (#2547):** Share mutually exclusive scope options
  between top-level and nested pause/resume parsers. Reject empty and
  whitespace-only values before dispatch: the existing handler treats falsey
  selectors as global control. Preserve exact non-empty paths and stable keys;
  reuse daemon normalization, transports, state, and lifetimes.
- **Release hook-session registration (#2547):** `send_hook_request()` always
  supplies `_daemon_cwd` from the caller's actual working directory. A payload
  `cwd` alone does not put registered sessions in a synthetic project. Change
  into the isolated project for registration, restore cwd in `finally`, and
  assert the status-reported project directories before scoped CLI checks.
- **Local Mypy environments (#2547):** The declared `uv --extra dev` environment
  passes the source check. The standalone executable still reports the known
  14 request-stub errors in unchanged `skill_discovery.py:522` and
  `scanners/secret_validator.py:288`; distinguish tool environments rather than
  expanding an unrelated change to fix baseline diagnostics.

- **ggshield startup probes (PR #2548 CI):** The bundled Python runtime can
  exceed five seconds under QEMU. `ggshield` supports `--version`, not the
  `version` subcommand; two short probes caused a checksum-verified ARM64 image
  build to fail after ten seconds. Installation verification and version
  discovery now share one bounded 60-second probe; other scanners keep their
  five-second fallback behavior. Checksums and successful exits remain required.

- **Win32 tray title rendering (PR #2548 review):** pystray passes menu text
  directly to `MENUITEMINFO.dwTypeData`; single ampersands become mnemonic
  markers. Escape only final Windows menu text, preserving stored titles and
  stable control keys. Test doubled ampersands and non-Windows literal strings;
  raw-string collision tests alone do not cover native rendering.
- **New daemon helper dependencies (PR #2548 review):** Adding a daemon import
  of an isolated shared helper also requires reviewing `_DAEMON_SOURCE_PATHS`.
  `sessions/base.py` is now tracked for editable-install stale-code warnings;
  unrelated session readers remain excluded. Inventory tests live in
  `tests/unit/test_daemon_client.py::TestGetPackageMaxMtime`.

- **Tray session titles (#2546):** `active_sessions.session_title` is optional
  display metadata; control routing and pause state still use the adapter-issued
  `session_key`. Invalid/omitted titles preserve the last usable name. Wrap a
  scalar metadata value in a candidate list when using `resolve_session_title`,
  otherwise a malformed list-valued field is mistaken for valid candidates.
  OpenCode V2 `ctx.session.get` returns metadata directly and accepts a request
  abort signal; cache exact-session lookups/misses and bound both time and size.
  Do not call native session summary readers just for a label: some load messages.
- **Session test isolation (#2546):** OpenCode V2 database discovery precedes
  the legacy `resolve_session_dir` path; discovery fixtures must set `OPENCODE_DB`
  to their temporary database. Tray local status comes from `_get_stats`, remote
  status from the multi-client; REST `/api/stats`, not `/api/status`, contains the
  full active-session list. Generic Claude hooks use `BaseAgentAdapter` keys.

- **OpenCode runtime selection (#2470):** User-facing setup, CLI doctor, and
  Console health checks do not require an AI Guardian-specific environment
  variable. They resolve the active `opencode` executable and run
  `opencode --version`; if V1 and V2 are intentionally installed under
  different command names, the executable resolved first on `PATH` is the
  target for that invocation. The version environment variable is retained
  only as an isolated test-matrix override.

- **Doctor CLI version reporting:** Doctor enriches installed CLI-capable hook
  integration records with best-effort `cli` metadata and appends the same
  version text to the existing integration message. Probe failures never alter
  hook health status; OpenCode reuses its runtime resolver and reports `v1` or
  `v2` generation when recognized.

- **Console health runtime context:** The local Web Console can outlive the
  tray and retain a stale `PATH`. When a local daemon REST endpoint is
  available, `MultiDaemonClient.get_health_check()` must query that daemon
  first; only use the Console-process Doctor fallback when the endpoint is
  unavailable.

- **OpenCode review hardening:** Cache version probes by executable and test
  override context; V2 database discovery must accept a direct existing path
  before regex fallback and must not let a legacy `OPENCODE_HOME` path hide
  the active V2 database. V2 error hooks must handle missing or scalar errors.

- **OpenShell version checks:** When an image is intentionally narrowed to one
  CLI, update both the Dockerfile-derived version-check fixture and registry
  lookup fixtures. The checker correctly ignores packages not explicitly
  installed by that image.

- **OpenShell middleware Rust split (#2525):** Keep `main.rs` as a thin binary
  entrypoint. Compatibility loading belongs in `compatibility.rs`, daemon IPC
  and pause state in `daemon.rs`, scanner routing/evaluation in `policy.rs` and
  `evaluation.rs`, and protocol capabilities in `http.rs`, `response.rs`, and
  `websocket.rs`. Contract checks must follow the dedicated compatibility
  module rather than assuming the fixture include remains in `main.rs`.

- **OpenShell middleware deployment (#2525):** There is no Python bootstrap or
  sandbox coupling. Operators run the Rust binary with a service manager,
  register it in the gateway TOML, and apply a complete OpenShell policy.

- **OpenShell middleware readiness auto-discovery (#2527):**
  Gateway extension metadata is not process liveness and may remain active after
  the middleware stops. Read configured gRPC endpoints from gateway TOML and
  call `SupervisorMiddleware/Describe`; report running only when the endpoint
  responds with `ai-guardian/rust-middleware` and a version. Keep this direct
  endpoint result separate from gateway-reported activation. No binary path,
  endpoint, or registration input belongs in the tray form. Updating
  `pyproject.toml` does not refresh an already-installed tray environment; when
  the probe reports missing `grpcio`, refresh AI Guardian and restart the tray.

- **OpenShell middleware pause semantics (#2525):** A daemon pause suspends
  content inspection and passes provider traffic through for HTTP, response,
  and WebSocket stages while retaining pause metadata; daemon/control-plane
  outages remain fail-closed. Rebuilding the Rust release binary replaces its
  inode, so a directly launched service continues running the old `(deleted)`
  binary until its operator-owned process is restarted.

- **OpenShell policy naming (#2525):** The `network_middlewares` map key is the
  stable policy-local identity; the nested `middleware` value references the
  operator gateway registration name. Using the same value for both is the
  clearest default, but OpenShell permits distinct names.

- **OpenShell OAuth coverage (#2525):** Codex OAuth provider traffic uses
  `chatgpt.com` and `ab.chatgpt.com`, not only `api.openai.com`. Middleware
  policy generation must include those hosts when OAuth is selected; explicit
  endpoint overrides intentionally replace the defaults.

- **OpenShell compatibility (#2525):** The Rust binary validates the explicit
  `AI_GUARDIAN_OPENSHELL_VERSION` against the shared fixture before binding;
  the OpenShell gateway then validates the supervisor protocol and capability
  handshake. Keep the release fixture and Rust embedded contract synchronized.

- **OpenShell release binaries (#2522):** The Python middleware runtime was
  already removed before binary distribution work. Publish the external Rust
  service as versioned GitHub Release archives for Linux x86_64/arm64 and macOS
  Intel/Apple Silicon; keep both `Cargo.toml` and `Cargo.lock` aligned with the
  AI Guardian release tag so locked builds and capability version reporting stay
  compatible.

- **OpenCode hook normalization (#2425):** OpenCode built-in tools arrive as lowercase names (`read`, `write`, `edit`, `bash`) with camelCase arguments such as `filePath`; normalize both adapter input and raw policy calls before immutable protection evaluates them.

- **IDE detection must separate installation evidence from protection status:** Project metadata such as OpenWolf's `.cursor/rules/` is not proof of an IDE installation. Require an IDE-owned config file or artifact for discovery, then use structured hook/MCP verification to determine whether AI Guardian is configured.

- **Never call `format_response(ide_type, ...)` wrapper from hook_processing.py:** The wrapper in `response_format.py` re-creates an adapter via `get_adapter_by_ide_type(ide_type)`, which maps `IDEType` enum → adapter class. Adapters that inherit from `BaseAgentAdapter` (Windsurf, Augment, Codex, OpenCode) share `IDEType.CLAUDE_CODE`, so the wrapper always returns `BaseAgentAdapter` — the subclass's `format_response()` is never called. Use `_format_response(adapter, ...)` instead, which calls the already-detected adapter directly.

- **NiceGUI `ui.timer` callbacks lose client context for dialog creation:** `ui.timer(0.1, lambda: create_dialog(), once=True)` creates UI elements that aren't attached to the right client page — dialog renders but is invisible. Call dialog creation functions directly from event handlers (sync or async) where NiceGUI's client context is preserved. Also: programmatically setting `select.value` triggers `on_value_change`, so guard against re-entrant handler calls causing unintended side effects (e.g., page reload).

- **NiceGUI `app.storage.user` does NOT work from `run.io_bound()` thread pool:** Both `contextvars` and `app.storage.user` fail from thread pool threads. Use module-level variables in `config_helpers.py` for state that must be accessible from `run.io_bound()` calls (e.g., `_current_daemon_name`). The existing `_get_current_scope()` using `app.storage.user` silently fails and returns default "global" — it was never actually reading session state from threads.

- **Web console violation stats pages should use `load_web_violations()` not `ViolationLogger` directly:** `ViolationLogger` reads local filesystem. `load_web_violations()` routes through DaemonService which handles local vs remote internally. The limit should come from `violation_logging.max_entries` config, not hardcoded.

- **Compliance audit logging (#266):** The new root `audit_logging` section is distinct from the existing `secret_scanning.audit_logging` scan-audit boolean; preserve both in the schema and profiles. Web Console forms are explicitly coded rather than generated from the schema, so configurable sections require navigation, page, and default-state updates there.

- **Audit console export scope (#266):** Pass the effective audit section into `AuditLogger(config=...)` when exporting from the Web Console; constructing a default logger can select the wrong output path for project-scoped settings. Web export must be disabled for remote daemon targets unless a daemon export API is added, because local filesystem export would otherwise return the Web Console host's trail.

- **All daemons (local and remote) support project scope via header selector (#1354):** The header shows a project dropdown for ALL daemons, populated from `/api/stats` `active_project_dirs`. Selection stored in `app.storage.user["project_dir"]` and mirrored to module-level `_current_project_dir`, which is shared across sessions and can be overwritten by another session. Config workers must receive the requesting session's `project_dir` explicitly or use session-bound state. All config load/save/provenance calls route through DaemonService for both local and remote targets — DaemonService internally handles local (filesystem) vs remote (REST) routing. When scope is "project" and a project is selected, `config_helpers.py` passes `project_dir` to `get_config_scoped()` and `write_config_bulk()`. Without a project selected, falls back to global scope. The fallback local-filesystem path in config_helpers only runs when no DaemonService is available (e.g., standalone mode without daemon).

- **glab mr diff uses different header format than git/gh:** `glab mr diff` outputs `+++ path/to/file` (no `b/` prefix), while `git diff` and `gh pr diff` output `+++ b/path/to/file`. The `_DIFF_FILE_HEADER` regex must use `(?:b/)?` to handle both.

- **Both SSRF and config_file_scanning have immutable core patterns that always block regardless of action mode (block/warn/log-only):** Metadata endpoints (169.254.169.254) and credential exfil patterns (`cat ~/.aws/credentials | curl ...`) always block even when `ssrf_protection.action=warn` or `config_file_scanning.action=warn`. Private IPs (192.168.1.1) and other configurable patterns DO respect the action mode. This distinction matters for scenario `expect` values in the minimal profile.

- **SSRF immutable vs configurable action modes:** SSRFProtector has `action` config (block/warn/log-only) that applies to user-configurable patterns. Immutable core patterns (CORE_BLOCKED_IP_RANGES, CORE_BLOCKED_DOMAINS, DANGEROUS_SCHEMES) always block regardless of action mode. The `_check_url` method returns `(is_ssrf, reason, is_immutable)` 3-tuple.

- **Config exfil scanning has two paths:** (1) ConfigFileScanner.scan() for file content (gated on `_is_config_file()`), (2) ConfigFileScanner.check_command() for Bash commands (bypasses config file gate). Both reuse `_check_exfil_patterns()`.

- **Immutable violation UX requires explicit metadata (#2457):** Carry
  `is_immutable: true` through `ScanResult.to_blocked_dict()` and unified
  logging; do not infer immutability from violation type or reason because
  legacy records must retain configurable remediation behavior. When a scanner
  can report multiple findings, aggregate the marker across all findings.

- **Directory scan provenance (#2457):** `run_directory_check()` may load the
  effective config when none is supplied. Reuse that loaded config when checking
  `_immutable` directory rules, or immutable metadata is lost in the scan path.

- **Display tier detection (#2424):** Shared dialog selection lives in `ui/display.py`; it supports Tkinter, NiceGUI, and headless mode. Existing persisted `textual` values migrate to NiceGUI. When mocking provider selection, set `AI_GUARDIAN_PREFERRED_UI=auto` explicitly because the suite-wide fixture forces headless mode.

- **Linux tray proactive setup prompts (#2497):** Native zenity/kdialog dialogs
  support only the simple action flow. Structured IDE/profile setup must stay on
  one rich provider for both the setup and snooze steps; returning native
  default selections silently loses user choices. Tray setup and upgrade
  workers also share a non-blocking prompt lock so periodic refreshes do not
  open competing modals.

- **Browser target selection (#2424):** `tray-target-select` launches the NiceGUI selector and must not require `stdin.isatty()`, because tray and remote invocations may have no controlling terminal. Tests should set `args.output_file = None` when using `MagicMock` CLI arguments.

- **Windows test patterns:** (1) `open(f, 'a')` writes `\r\n` on Windows — use `'ab'` mode with `.encode('utf-8')` for byte-accurate position tracking. (2) `patch.dict('os.environ', {}, clear=True)` removes USERPROFILE/HOMEDRIVE/HOMEPATH on Windows — preserve home-related vars with a `_minimal_env()` helper. (3) `tempfile.NamedTemporaryFile(dir="/tmp")` fails on Windows — omit `dir` to use platform default. (4) Tests relying on `/etc`, `/dev`, `HOME` env var, or XDG paths need `skipif(sys.platform == "win32")`. (5) `_read_shell_path()` checks `SHELL` env var which is unset on Windows — tests must `monkeypatch.setenv("SHELL", "/bin/bash")`.
- **Windows process liveness:** Do not use `os.kill(pid, 0)` for MCP identity checks; reuse `ai_guardian.daemon.is_pid_alive()`, whose Windows branch uses `OpenProcess` and avoids console-interrupt behavior.

- **Pi tray health must preserve structured MCP states:** Pi's managed extension verifier returns `mcp_registration="extension"` plus distinct states such as `missing_dependencies`, `identity_missing`, and `disabled`. Tray notifications should use that marker to retain the state-specific diagnostic and managed extension path instead of collapsing every `mcp_installed=false` result into generic MCP missing.

- **Pi SDK setup policy:** The managed extension should automatically run `npm install --ignore-scripts --no-audit --no-fund` when npm is available. If npm is unavailable or the install fails, preserve hook protection and expose the retry command; a later setup without `--force` must retry pending SDK states. Setup and check commands may resolve different `ai-guardian` executables, so executable-pin diagnostics must remain distinct from missing SDK dependencies.
- **Pi MCP bridge policy boundary (#2440):** Pi registers the managed server's tools as `mcp__ai-guardian__*` and sends them through its normal `tool_call` hook. A live identity attestation is the authorization boundary: scanners and immutable protections still run, but ordinary host MCP permission rules must not block the verified security advisor.

- **MCP command-check context (#2471):** `check_command` runs outside the daemon, so project policy must be selected through an explicit `project_dir` or `AI_GUARDIAN_PROJECT_DIR`; otherwise the server launch directory is the documented fallback. Capture the developer-session trust state at MCP startup, keep identity failures fail-closed, and have managed Pi pass `ctx.cwd` automatically.

- **MCP paused responses (#2472):** A skipped action-gating check must not carry normalized `policy_decision.decision="allow"`, because consumers may treat it as authorization; omit policy metadata when no decision was evaluated. Diagnostic tools that report effective directory state must accept the same explicit `project_dir` context as the action check.

- **Windows path assertions:** Tests around MCP project context must use `tmp_path` or another platform-native `Path` and assert its resolved string; hard-coded POSIX paths are converted by `Path.resolve()` on Windows and fail otherwise-correct behavior.

- **Grok Build setup paths (#2446):** Grok's relocated user hook target is `<GROK_HOME>/hooks/ai-guardian.json`, not directly under `GROK_HOME`; shared path resolution must pass the `hooks` subdirectory alongside the filename. Project hooks and MCP remain under `.grok/`.

- **Host CLI config diagnostics (#2461):** Malformed or structurally invalid
  JSON/JSONC/TOML/YAML files belong to the host CLI integration, not
  `ai-guardian.json`. Setup, doctor, and tray health must use one format-aware
  loader across every supported integration, preserve the existing file, and
  surface the path/format-specific diagnostic before any write.

- **OpenCode Doctor status:** OpenCode must bypass the marker-only hook fast
  path so V1/V2 runtime and plugin generation mismatches are detected. When
  that full verification is healthy, `check_hooks_for_ide()` must still return
  `OpenCode: configured`; otherwise the generic empty-detail fallback reports
  the misleading `configuration unreadable` warning even with healthy MCP.

- **OpenCode V2 plugin migration:** V2's `plugins` configuration accepts
  packages or plugin directories, not direct TypeScript files. During setup,
  remove only AI Guardian's stale direct entry; if another local `.ts` entry is
  present, leave the host configuration unchanged and require explicit user
  migration.

- **Runtime-specific container entrypoints (#2446):** The normal and OpenShell images share `container/entrypoint.sh`; when a CLI is intentionally normal-container-only, the OpenShell image must set an explicit runtime marker and the entrypoint must filter that CLI from its supported arrays.

- **OpenShell provider credential types:** OpenShell `0.1.2` codex providers
  accept the OAuth credential set, while Codex API-key sessions use the
  `openai` profile. Automatic setup must keep `ai-guardian-codex` and
  `ai-guardian-openai` as separate provider instances; updating an OAuth
  provider with `OPENAI_API_KEY` fails with an invalid-argument error.

- **OpenShell provider setup:** Importing a provider profile does not create a
  provider instance. An explicit `--provider` passed to `ai-guardian sandbox
  create` requires a matching `openshell provider create` instance, while
  staged setup can create or reuse one when matching local credentials exist.

- **OpenShell tray provider flow:** The tray Create sandbox form leaves its
  OpenShell provider value empty and relies on staged setup; Codex OAuth maps to
  `ai-guardian-codex`, while a local Codex `OPENAI_API_KEY` maps to
  `ai-guardian-openai`. The separate Pi provider field is disabled for
  OpenShell.

- **OpenShell gateway setup:** The official installer provisions and starts a
  local gateway. On Linux, check/restart the `openshell-gateway` systemd user
  service and start `podman.socket` for rootless Podman; on macOS, use the
  Homebrew `openshell` service. The old `/openshell/get-started/quickstart`
  documentation URL is stale; use `/openshell/latest/about/installation`.

- **OpenShell release pinning:** For a deterministic AI Guardian fresh-machine
  setup, install the qualified baseline with
  `OPENSHELL_VERSION=v0.1.3` and import provider manifests from `v0.1.3`. The
  `providers_v2_enabled` setting is legacy v0.1.2-only and absent in v0.1.3;
  OpenShell v0.1.2 and earlier are below the current AI Guardian baseline.

- **OpenShell v0.1.3 qualification (#2531):** The release restores
  supervisor-backed GCP metadata discovery and its patch-train protobuf check
  protects the v0.1.2 protocol boundary. Live native Codex OAuth qualification
  passed with CLI and gateway v0.1.3 against the pinned AI Guardian 1.19.0 image;
  creation, service, agent, detection, restart, reconnect, and cleanup passed.
  Claude Code/Vertex were still awaiting a separate credential-bound
  implementation and manual qualification at that point. When extracting the gateway version from `openshell
  status`, parse its explicit `Version:` field; the earlier generic numeric
  matcher incorrectly treated the gateway's IPv4 endpoint as `127.0.0`.

- **OpenShell native Vertex auth (#2473):** Use the imported endpointless
  `google-cloud` profile and a gateway provider created from host ADC; never
  upload or mount the ADC file or pass token values to the workload. Compose
  credential bindings for regional, global, and replicated Vertex endpoints,
  and probe `127.0.0.1:8174` before model qualification. OpenCode's built-in
  Vertex provider ID is `google-vertex`, with `GOOGLE_CLOUD_PROJECT` and
  `VERTEX_LOCATION`; explicit sandbox environment aliases must take precedence
  over ambient tray/CLI values. Capture-and-discard agent output in both smoke
  and qualification modes, including partial output on timeout. Live
  Claude/OpenCode model qualification remains manual. Keep Vertex network
  policy regional endpoints exact rather than wildcarding the first DNS label;
  retain only the fixed global and replicated endpoints alongside the selected
  location. Claude Console and OAuth operations require `platform.claude.com`,
  and sign-in can redirect through `claude.com`. Tray form `enabled_when` can be
  a tuple of conditions; Tk and NiceGUI both evaluate the conjunction through
  `_field_enabled` for runtime/mode/CLI-specific controls.

- **OpenShell provider lookup (#2473):** In v0.1.3, `openshell provider get
  NAME` has no `--output` option and prints a human-readable `Type:` row.
  Requesting JSON makes valid existing `google-cloud` providers appear
  unavailable; read the type from supported CLI output instead.

- **OpenShell endpoint TLS policy:** Omit `tls: terminate` from bundled endpoint
  policies; OpenShell rejects that value and automatically terminates TLS when
  the field is absent. Check all policy overlays, not only agent fragments.

- **OpenShell Claude bootstrap:** Claude Code is not bundled in the support image
  because of its redistribution terms. Non-interactive creation needs explicit
  ToS consent; host `ACCEPT_PROPRIETARY_TOS` is not forwarded automatically.
  Tray creation requires a default-unchecked acceptance checkbox when Claude is
  selected and passes the environment value only when checked. Existing sandboxes do not rerun startup;
  update the host tool with `uv tool install --editable .`, restart the tray, and
  create a new sandbox. Image rebuild is not needed for this UI-only change.

- **OpenShell Claude installer egress:** The setup shell downloads a versioned
  native installer under `/sandbox/.claude/downloads/claude-*`; that binary makes
  the release metadata request to `downloads.claude.ai`. Permit that narrow path
  in `claude_install`, not just `/usr/bin/curl`. Installed native launchers
  resolve into `/sandbox/.local/share/claude/versions/**`; include that path in
  both Claude download and Vertex rules, or auto-update/inference can be denied.

- **Tk boolean form clearing:** When a disabled form field has type `bool`, clear
  its `BooleanVar` with `False`, never `""`; an empty string invalidates Tk's
  boolean variable during initial form rendering.

- **macOS Bash nounset tests:** Bash 3.2 with `set -u` aborts when
  `container/run.sh` expands an unset optional `USERNS_ARGS[@]` array. The full
  launcher suite fails before the mocked container engine runs; focused policy
  contract tests remain usable until that separate shell fix is made.

- **OpenShell workload identity:** OpenShell clears supplementary groups before
  capability-free launch. The NVIDIA Ubuntu base's `ubuntu` UID has default
  supplementary groups, so the dedicated image must create/use a separate
  `sandbox` account with only its primary group.

- **Policy must use normalized tool fields:** Hook processing adds canonical
  `tool_name`/`tool_input` fields alongside native payload keys before invoking
  `ToolPolicyChecker`. The checker must prefer those canonical fields, or a
  native tool name such as Grok's `run_terminal_command` can bypass immutable
  host CLI/configuration checks.

- **Anthropic native compaction only preserves a tail:** The provider summarizes
  every message supplied in the compaction request. After compaction, send the
  returned block first and only the untouched recent tail; do not re-add an
  older prefix after the block or later beta requests become invalid.

- **Hook audit logs are multi-process files:** Thread locks do not serialize
  hook subprocesses. Audit writes and rotation need a per-log OS lock, private
  0700/0600 permissions, and atomic replacement of rotated JSONL files.

- **Claude MCP default path differs from settings:** Without
  `CLAUDE_CONFIG_DIR`, Claude's settings are under `~/.claude/` but its global
  MCP file is `~/.claude.json`; with relocation, the MCP file is adjacent to
  the relocated settings directory.

- **Self-protection Python launch detection:** Inline Python can invoke the
  protected CLI through a path-qualified executable string (for example,
  `/usr/local/bin/ai-guardian`), so matching must normalize an optional path
  prefix rather than only matching the bare executable name. Package imports
  remain intentionally protected because they can reach the CLI/runtime APIs.

- **Doctor scanner defaults and schema:** When no config exists, doctor must
  use the runtime default engine set (`toml-patterns` plus `gitleaks`) so a
  built-in scanner is recognized. Scanner validation must also accept the
  documented object forms for `custom` and `python`, while rejecting missing
  required fields.

- **Permission assertions are platform-specific:** Audit log permission-bit
  tests are POSIX-only; skip those assertions on Windows rather than assuming
  `os.chmod` exposes equivalent mode bits there.

- **Release-readiness workflow contracts must parse YAML:** Text regex checks
  can miss an indentation error that changes a GitHub Actions matrix value.
  Parse the workflow in the contract test and compare the actual matrix list to
  the canonical IDE registry. OpenShell image smoke checks must only require
  CLIs packaged in the image; Claude is intentionally installed at runtime
  after ToS consent.

- **OpenShell base-image labels have one source of truth:** The compatibility
  assertion in release readiness must match `Dockerfile.openshell`'s `BASE_IMAGE`
  digest. Keep a contract test comparing the workflow value to the Dockerfile
  instead of manually maintaining two independent digests.

- **Python support transition:** The 1.19 line still supports Python 3.9, while
  1.20.0 now requires Python 3.10+. The last stable 3.9-compatible release is
  1.19.0; keep upgrade guidance and the `ai-guardian<1.20` pin documented for
  users who cannot upgrade their runtime.

- **Multi-architecture OCI validation needs artifact cleanup:** The Ubuntu
  compatibility workflow exports normal and OpenShell images as large OCI
  tarballs on the same runner. Remove the first artifact before exporting the
  second, especially when a new normal-container-only CLI increases image size.

- **Full-suite CI timeout triage:** When a CI run times out at an existing test and the current diff creates no threads or processes, compare with the preceding passing PR and rerun the canceled jobs before changing production code. The Python 3.9/3.12 timeout on PR #2438 passed on rerun with no source changes.

- **OpenCode V2 plugin API:** `@opencode/plugin@2.0.22` tool hook events use
  `id`, not the V1-style `callID`; `execute.after` is a completed/error union,
  so generated hooks must narrow before reading or mutating `result`. Validate
  generated TypeScript against the published declarations, not only string
  contract tests. The local ignored `.opencode/package.json` now carries both
  the V1 and V2 plugin pins. V2 `ctx.session.hook('prompt')` is a transform-only
  admission hook with no typed denial result; throwing prevents admission. Its
  owned mutable `event.prompt` draft contains text, files, agent mentions, and
  skills. When a blocked first prompt must leave a usable turn in the same
  session, replace the draft with a fixed safe notice and clear every attachment/
  selection field. OpenCode then admits that safe user input and may run the model
  on the notice; this is preferable to leaking original data or rejecting the
  admission, but is not a true model-turn cancellation. Other generated prompt
  adapters inspected (Pi, OpenClaw, AiderDesk) use host-specific handled/cancel/
  blocked return values instead of throwing from a transform-only admission hook;
  this failure mode appears OpenCode-specific, though those agents still need
  their own runtime qualification for session behavior.

- **OpenShell middleware lifecycle UX:** Do not add an AI Guardian middleware
  lifecycle command. The Rust binary is an external service; OpenShell owns
  registration and `network_middlewares` policy activation, and systemd/launchd
  or Kubernetes owns process lifecycle.

- **OpenShell gateway registration reload:** Operator-run middleware
  registrations are static in the gateway TOML. Run the documented gateway
  config preflight and restart the gateway only when the registration changed;
  restarting the external middleware process alone does not require a gateway
  restart.

- **Middleware Console audit visibility:** The external middleware can write
  directly to the same `violations.jsonl` selected by `ViolationLogger`; use
  `AI_GUARDIAN_STATE_DIR`, then `XDG_STATE_HOME/ai-guardian`, then the default
  `~/.local/state/ai-guardian`, and keep the Console on the same environment and
  Unix account. An explicit `/tmp` violation log is intentionally isolated from
  the Console.

- **OpenShell middleware documentation:** Keep the qualification instructions
  linear: external Rust service, gateway registration, ordinary sandbox
  creation, complete OpenShell policy activation, and service-manager cleanup.

- **OpenShell scanner ownership (#2523):** `scanner_ownership` routes checks at
  the provider boundary; it is not an exclusive switch that disables host
  hooks. The Rust v0.1.2 runtime rejects explicit `both`, so the supported
  defense-in-depth shape is `default: hooks` with explicit provider-capable
  scanners set to `middleware`; Python `both` requires correlation and
  pre-persistence deduplication, but that deduplicator does not merge
  independently persisted host-hook records.

- **Tray menu organization (#2529):** Keep single-daemon `Pause...` directly
  below **Status**, matching multi-daemon menus, while preserving its existing
  pause/resume actions. Keep middleware readiness standalone; put policy apply
  under the selected OpenShell target's **Manage sandbox** menu and scope the
  form to that target. Do not show the OpenShell policy action for regular
  container targets.

## Do-Not-Repeat

- [2026-10-29] `place_tk_window` intentionally applies no geometry when monitor
  context is absent. Passing larger requested dimensions alone does not enlarge
  a single-monitor dialog. Explicitly set initial geometry within `window.maxsize()`
  before placement, and assert the actual `window.geometry(...)` call before
  mainloop in tests—not only the arguments passed to the placement helper.

- [2026-10-28] Placement changes affect provider eligibility. Mock every reachable
  provider in UX tests, not only the previously first native implementation:
  native-only Linux fixtures can open real Tk and hang. Exercise Cocoa/WinForms
  and Tk contracts separately while preserving complete controls/cancel semantics.

- [2026-10-06] Do not place `exit` in copy-paste guards intended for an
  interactive shell; use a subshell or an `if/else` block so missing optional
  artifacts do not terminate the user's session.

- [2026-06-30] DO NOT call `_show_via_subprocess` from the tray's `_handle_remote_prompt` without first trying NiceGUI in-process. On macOS Sonoma+ (14+), `activateIgnoringOtherApps_` is deprecated so tkinter subprocess windows spawn invisible behind other apps — dialog blocks for 300s then auto-dismisses, making the tray appear stuck. Fix: in `_show_and_respond`, call `_NiceGuiAskDialog(violation, timeout).run()` first if NiceGUI is available; it opens a browser tab which is always visible. Only fall back to `_show_via_subprocess` if NiceGUI is unavailable.

<!-- Mistakes made and corrected. Each entry prevents the same mistake recurring. -->
<!-- Format: [YYYY-MM-DD] Description of what went wrong and what to do instead. -->
- [2026-08-19] Python 3.9 support was retained through the 1.19.x line; do not
  reintroduce 3.9-specific support claims into the 1.20.0+ metadata, installer,
  CI, or documentation surfaces.
- [2026-07-15] Always run `black --target-version py39` (not bare `black`). On Python < 3.15, black's safety check silently skips reformatting without `--target-version`, producing "files left unchanged" even when formatting is wrong. CI runs Python 3.15 where black reformats correctly, causing CI failure.
- [2026-06-24] During release, update README install URLs to the release tag BEFORE creating the git tag. The tag snapshot is what PyPI publishes as the package README. In v1.12.0, URLs were updated after the tag, so PyPI shows `main` URLs instead of `v1.12.0`. Correct order: bump version → update CHANGELOG → update install URLs → commit → tag → push.
- [2026-06-24] `cursor-verify-setup` in release_helper.py places debug hooks at the JSON top level instead of inside the `hooks:{}` object. Cursor only reads from `hooks:{}`. The cleanup also looks at top level. Both functions need fixing to operate inside `hooks:{}`. **FIXED in v1.12.2** — `_add_debug_hooks()` and `cleanup()` now operate on `settings["hooks"]`.
- [2026-06-26] `publish.yml` tag trigger `v*` matches test tags like `v1.12.2-test1`, causing production PyPI publish on test releases. **FIXED** — merged publish.yml and publish-test.yml into single workflow; tag format detection routes `v*-test*` → TestPyPI, clean `v*` → PyPI. PyPI does NOT allow re-uploading same version, so this bug burns a version number.
- [2026-06-24] ALWAYS run `black src/ai_guardian/ tests/` and `ruff check --fix src/ai_guardian/ tests/` BEFORE committing. AGENTS.md lines 397-419 require this. CI lint job will fail otherwise.
- [2026-06-18] When adding `_comment_*` keys to `setup.py` `_create_default_config()`, ALSO add them to ALL profile templates in `src/ai_guardian/templates/profiles/{minimal,standard,strict}.json`. The `test_standard_matches_default_template` test compares `_get_default_config_template()` output against `@standard` profile JSON — they must match exactly.
- [2026-06-17] `process_annotations()` returns `(str, str, list, list)` — the first two values are already-suppressed CONTENT STRINGS, NOT sets of line indices. DO NOT pass them to `apply_suppressions()` (which expects `Set[int]`). Use the content strings directly. Check the 3rd return value (suppression_info list) for truthiness to determine if any suppressions were found. The PostToolUse path at hook_processing.py:3822 had this exact bug.
- [2026-06-17] `FileScanner._scan_file()` in scanner.py is a SEPARATE scan path from hook_processing.py's `process_hook`. Any new annotation/suppression feature added to the hook path must ALSO be added to FileScanner — it's used by `ai-guardian scan` CLI, daemon `/api/scan`, and TUI/web scan pages.
- [2026-06-13] DO NOT run tkinter ask dialogs in the daemon REST API handler (`rest_api.py:_handle_prompt`). On macOS, tk.Tk() MUST run on the main thread — calling it in a background thread hangs the daemon's socket accept loop, orphaning the process. Use `_show_via_subprocess()` instead, which spawns `ai-guardian prompt --mode ask` as an isolated process. NiceGUI CAN run in-process (browser-based, no main-thread requirement), but currently uses subprocess for consistency and isolation (see #1152 for future optimization). Textual MUST use subprocess (daemon has no controlling terminal).
- [2026-06-13] DO NOT delete PID/socket files in `_cleanup_stale()` when the daemon process is alive and the socket exists. This orphans a hung but recoverable daemon. Only delete files when: (1) process is dead, OR (2) process is alive but socket missing (PID recycled). If process is alive AND socket exists BUT unresponsive, raise RuntimeError instructing user to kill the hung process manually.
- [2026-06-13] DO NOT call TrayPromptApp (tkinter) directly in the tray process. pystray already owns NSApplication.sharedApplication() on macOS — calling tk.Tk() in the same process crashes because NSApplication was created before Tk. Only NiceGUI (browser-based) can run in-process. tkinter must spawn a subprocess.
- [2026-06-10] PyGObject CANNOT be a core dependency in pyproject.toml — it requires C compilation with system headers (gobject-introspection-devel, libcairo2-dev, etc.) which are not present on CI runners or most dev machines. Adding `PyGObject>=3.42.0; sys_platform == 'linux'` breaks all ubuntu CI jobs. Use optional-dependencies `[tray-linux]` instead, and install PyGObject separately in install.sh after system headers are in place.

- [2026-06-09] tkinter availability and macOS AppKit interaction: (1) `_tkinter_available()` uses subprocess to test `tkinter.Tk()` — isolates crashes (SIGABRT from broken Tcl/Tk on uv). (2) In `_TkinterPromptApp.run()`, AppKit `NSApplication.sharedApplication()` MUST be called AFTER `tk.Tk()`, not before. PyObjC creates a wrapper NSApplication that lacks Tk's `macOSVersion` category method — if created first, `tk.Tk()` crashes with `NSInvalidArgumentException`. (3) `tkinter.Tcl().eval('package require Tk')` too strict for uv (missing pkgIndex.tcl). (4) Calling `tkinter.Tk()` in availability check creates macOS dock icon and can hang from daemon.

- [2026-06-07] When adding new Claude Code hook events (e.g., "Stop"), also add them to GeminiCLIAdapter.can_handle() exclusion list. Gemini's can_handle matches on `transcript_path` presence + NOT being a Claude Code event — if the new event isn't excluded, Gemini adapter wins when transcript_path is present, and normalizes the event incorrectly.
- [2026-06-08] When changing `_check_url` return signature (2-tuple→3-tuple), check ALL callers across the codebase with `grep -rn "_check_url" src/`. External caller in `secret_validator.py` broke because it expected 2-tuple.

- [2026-07-02] When adding a new scanner, adding `"supply_chain"` to `FEATURE_PAGE_SLUGS` in dashboard.py was wrong — supply_chain was intentionally absent (test explicitly asserts it's NOT there). Only add genuinely new page slugs.

- [2026-07-27] When checking if a dict response contains an error, use `result_dict.get("error") is not None`, NOT `"error" in result_dict`. The `in` operator checks key existence — if the key exists with value `None`, `"error" in dict` is True. This caused `_try_daemon_engine_test` to silently fall back to subprocess even when the daemon returned a successful result with `error: None`.

- [2026-07-02] `test_standard_matches_default_template` compares `_get_default_config_template()` vs `standard.json` using `sort_keys=True` JSON serialization — even a trailing sentence difference in `_comment_*` fields fails the test. The comment in setup.py and standard.json must be byte-for-byte identical.

- [2026-08-05] **Empty dict is falsy — `run_*_scan(config={})` returns None:** All `run_*_scan()` functions in `hook_events/scanners.py` have `if not config: return None` early-exit. Passing `config={}` (empty dict from user config) triggers this — scanner skips entirely. Fix: pass `config or None` so scanner loads its own config internally via `_loaders._load_*_config()`.

- [2026-08-07] **caplog + propagate=False on ai_guardian logger:** PR #1823 set `propagate=False` on `logging.getLogger("ai_guardian")`. pytest 9.x handles non-propagating loggers automatically in `catching_logs`, but pytest 8.x (Python 3.9 CI) doesn't — caplog handler stays on root and never sees messages. Fix: autouse `_capture_package_logs` fixture in `tests/conftest.py` adds caplog handler directly to the `ai_guardian` logger. Checks `already_attached` to avoid double-adding on pytest 9.x.
- [2026-09-30] Explicit `headless` UI mode must short-circuit tray forwarding; otherwise a registered tray can open modal dialogs during tests despite `AI_GUARDIAN_PREFERRED_UI=headless`.
- [2026-09-30] OpenShell v0.1.2 removes Community-image/inference-route assumptions; update container tests with the implementation when changing base-image, provider, or entrypoint behavior.

- [2026-08-05] **Canary payload selection for smoke tests:** (1) `AKIAIOSFODNN7EXAMPLE` is in gitleaks allowlist — use `sk-proj-...` format instead for secret scanning. (2) Context poisoning requires BOTH persistence pattern (`from now on`, `remember`) AND dangerous pattern (`delete`, `ignore security`) — single-category text won't trigger. (3) ExfilDetectionScanner matches credential-specific patterns (credential_theft, key_file_exfil, base64_encoding, etc.), NOT general curl uploads — use `base64 ~/.aws/credentials` not `curl -d @/etc/passwd`. (4) Bandit does NOT flag `subprocess.call(input())` — use `os.system(input())` which triggers B605. (5) Secret redaction has its own patterns separate from gitleaks — `AKIAIOSFODNN7EXAMPLE` IS redacted even though gitleaks skips it.

## Decision Log

- [2026-10-29] **Inline pause UI (#2620):** Use the shared `run_modal("form", ...)`
  dispatcher with complete isolated Tk/NiceGUI implementations; simple native
  forms are ineligible. A persistent JSON-lines child channel carries only display
  snapshots and narrow row/action/duration events. Keep connections and credentials
  in the parent, refresh row tokens after every response, and revalidate the
  original connection and stable scope key before sending any explicit action.

- [2026-10-11] Keep targeted CLI overwrite confirmation aligned with the exact
  guard in `IDESetup.setup_ide_hooks`: share the existing-config classifier so
  healthy managed hooks prompt for force while partial event hooks remain
  repairable without force. Keep the prompt in interactive `setup_hooks`; tray,
  `--yes`, and JSON callers retain their existing non-interactive behavior.

- [2026-07-01] **Allow Once scoped to invocation-level set, not daemon_state** (#1439): `_record_allowed_for_transcript` now accepts a plain `set` (called `result_set`) instead of `daemon_state`+`session_id`. `_log_ask_decision` gains `invocation_allowed_findings: Optional[set]` param; call sites in `process_hook_data` pass `_invocation_allowed = set()` created fresh each invocation. Transcript scanners read `_invocation_allowed` directly. This scopes dedup to the current invocation only, so "Allow Once" no longer persists across hook invocations.
- [2026-07-02] When adding a new scanner, update ALL count-assertion tests: `test_tui.py` (NAV_GROUPS leaf count), `test_tui_global_settings.py` (FEATURES count, FEATURE_ACTIONS count), `test_web_sidebar_search.py` (NAV_GROUPS item count), `test_aiguardignore_writer.py` (scanner types schema). Also update `aiguardignore.schema.json` to include the new scanner type.

- [2026-07-02] `ExfilDetectionScanner` pattern: `base64 file` hits `base64_encoding` category, not `key_file_exfil` (the key_file_exfil patterns only match when piped to curl/wget/nc/socat). When writing tests, match the pattern category order in `_PATTERN_CATEGORIES` dict.

- [2026-07-09] **setup.py split into focused modules (#1493):** `setup.py` is now a thin orchestrator with re-exports. Real code lives in: `setup_utils.py` (helpers), `setup_config.py` (default config template), `setup_mcp.py` (MCP install/remove), `setup_rules.py` (guidelines files), `setup_hooks.py` (IDESetup class + pre-commit + templates). When mocking setup internals in tests, target the canonical module (`setup_mcp`, `setup_hooks`, `setup_utils`) not `setup`. All `from ai_guardian.setup import X` still works via re-exports.

- [2026-07-09] **ScannerRegistry Phase 3 (#1253):** `scanner_registry.py` provides `ScannerName` enum, `ScannerEntry` dataclass, and `ScannerRegistry` class. `get_default_registry()` returns a lazy singleton with all 13 scanners. `_build_default_registry()` uses deferred imports from `hook_processing` to avoid circular imports. In `process_hook_data()`, the content-scanning section (PI, CP, SC, OL, canary, config_file, secret, PII) is gated by `_pipeline_names` — a set built from `registry.get_pipeline()`. Each scanner block sets result to `None` early if not in pipeline; existing `if result is not None:` checks handle the skip. PostToolUse is NOT migrated (too many special cases). Cross-hook context saving derives `secrets_scanned`/`prompt_injection_scanned` from `_pipeline_names`.

- [2026-07-09] **tray.py split into focused modules (#1492):** Pure/static functions extracted to: `tray_icons.py` (icon image ops), `tray_notifications.py` (notification/version helpers), `tray_menu.py` (menu labels/launchers/constants). Plugin command execution moved to `tray_plugins.py`.

- [2026-07-09] **tray.py state + method extraction (#1542):** Removed 27 `@staticmethod` wrappers. Extracted state + methods into 4 new classes: `TrayIconManager` in `tray_animation.py` (8 animation state vars + 11 methods), `TrayHealthMonitor` in `tray_health.py` (10 state vars + 12 methods), `TrayPluginMenuBuilder` in `tray_plugin_runner.py` (4 state vars + 15 methods), `TrayMenuBuilder` in `tray_menu_builder.py` (20 menu builder methods). DaemonTray reduced from 4063→1262 lines. Tests mock at `tray._anim`, `tray._health`, `tray._plugins`, `tray._menu` for extracted state. pystray mocks need triple target: `tray.pystray`, `tray_menu_builder.pystray`, `tray_plugin_runner.pystray`.

- [2026-07-09] **ScannerRegistry Phase 4a — post-scan filter pipeline (#1254):** `ScannerEntry` gains `supports_ask_mode`, `config_section`, `violation_severity`, `violation_suggestion` fields. New `post_scan_filters.py` module provides `PostScanContext` (dependency injection for hook_processing callbacks), `PostScanDecision` (return type), `build_violation_blocked()` (generic blocked dict from ScanResult), `log_scan_violation()` (generic violation logging), and `apply_post_scan_pipeline()` (orchestrates violation logging + ask mode). Five scanner blocks migrated in PreToolUse: PI, CP, SC, OL, CD. PostToolUse NOT migrated (per Phase 3 decision).

- [2026-07-09] **ScannerRegistry Phase 4b — remaining scanners (#1545):** Migrated 6 more scanners to `apply_post_scan_pipeline()`: BASH_EXFIL, EXFIL_DETECTION, CONFIG_FILE, CODE_SECURITY (via `log_scan_violations_per_finding()` + `skip_violation_log=True`), SECRET (`skip_violation_log=True` since `run_secret_scan` already logs), PII (with `blocked_overrides` for pii_count/pii_types/line_number and `finding_fingerprints` for transcript dedup). DIRECTORY and IMAGE exempt (documented in scanner_registry.py). PostScanContext gains `invocation_allowed_findings` field; `apply_post_scan_pipeline` gains `skip_violation_log`, `finding_fingerprints` params. Registry + PostScanContext construction hoisted before BASH_EXFIL block. Deleted 4 dead helpers: `_log_supply_chain_violation`, `_log_canary_detection_violation`, `_log_exfil_detection_violation`, `_log_code_security_violation`. PII `line_number` must be set from `pii_redactions[0]` before pipeline call (ScanResult.from_pii_scan doesn't set it).

- [2026-07-14] **Transcript scanning refactored to TranscriptAdapter pattern (#936):** `scanners/transcript/` subpackage with `base.py` (ABC), `common.py` (shared scanning/dedup), `jsonl.py` (JSONL adapter), `opencode.py` (OpenCode SQLite), `cursor.py` (Cursor SQLite). Content pipeline uses `TRANSCRIPT_ADAPTERS` list + polymorphic `can_scan()`/`scan_incremental()` loop. When mocking transcript scanning in tests, target the *defining* module (`common.check_secrets_with_gitleaks`, `cursor._scan_transcript_text`) not the re-exporting `__init__.py`.

- [2026-07-15] **Shared transcript helpers extracted (#1604):** `common.py` gains `_scan_with_position_tracking(pos_key, reader_fn, ...)` → `str` (returns combined text or `""` to skip) and `_discover_path(env_var, default, check, env_suffix)` for directory/file discovery. Base `TranscriptAdapter.can_scan()` is now concrete — matches `adapter.name == self.name` + no transcript_path; JSONL overrides. No `adapter_name` class attr — `can_scan` uses the `name` property directly. All 5 adapters use `_scan_with_position_tracking`; Windsurf/OpenCode/Cursor use `_discover_path`; Cline keeps custom env-var logic. When adding a new adapter: just define `name` property and `scan_incremental()` — base `can_scan()` handles matching automatically.

- [2026-07-14] **Cursor state.vscdb schema:** `cursorDiskKV` table (key TEXT UNIQUE, value BLOB). Conversations indexed by `composerHeaders` table. Messages stored as `bubbleId:<composerId>:<bubbleId>` keys → JSON blobs with `type` (1=user, 2=assistant), `text`, `toolFormerData.output`/`rawArgs`. Position tracking uses set of seen bubble IDs (JSON list), not timestamps. DB path: `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` (macOS).

- [2026-07-14] **Backward compat policy updated:** Only SDK (`ai_guardian.sdk`) and configuration (`ai-guardian.json`) require backward compat. Internal modules can be freely reorganized without shims. Added to AGENTS.md.

- [2026-07-15] **Windsurf transcript adapter (#938):** `scanners/transcript/windsurf.py` — Windsurf stores Cascade transcripts as JSONL at `~/.windsurf/transcripts/{trajectory_id}.jsonl`. Each line has `type` + `status` + type-named sub-dict. Known types: `user_input` (`.user_response`), `planner_response` (`.response`), `code_action` (`.new_content`). Unknown types: walk sub-dict string values. Position tracking uses line count with `windsurf:{trajectory_id}` key. `can_scan()` activates when `adapter.name == "Windsurf"` and no top-level `transcript_path` in hook_data. Registered before `JsonlTranscriptAdapter` in `TRANSCRIPT_ADAPTERS` to get priority.

- [2026-07-20] **Kiro transcript adapter (#939):** `scanners/transcript/kiro.py` — Kiro CLI stores session transcripts as JSONL at `~/.kiro/sessions/cli/<uuid>.jsonl`. Each line has `type` field. Known types: `user_message` (`.content`), `agent_message_chunk` (`.content`), `tool_call` (`.arguments` dict/string), `tool_result` (`.content` or `.output`). Unknown types: fall back to `.content`. Position tracking uses line count with `kiro:{session_id}` key. Session discovery: `KIRO_SESSIONS_DIR` env var → `~/.kiro/sessions/cli/` default. Falls back to most-recent `.jsonl` file if `session_id` not in hook_data. Registered before `WindsurfTranscriptAdapter` in `TRANSCRIPT_ADAPTERS`.

- [2026-07-20] **Augment Code transcript scanning not feasible (#941):** Augment Code (Auggie CLI) stores conversation sessions server-side, not as local files. Only local files under `~/.augment/` are auth (`session.json`), settings (`settings.json`), commands, and rules. Augment does not implement UserPromptSubmit hook (only PreToolUse, PostToolUse, Stop, SessionStart, SessionEnd). Transcript scanning requires PROMPT event to trigger (`content_pipeline.py:668`). Closed as not planned. Can be revisited if Augment adds UserPromptSubmit or exposes local session files.

- [2026-07-20] **AiderDesk and OpenClaw transcript adapters (#942):** `scanners/transcript/aiderdesk.py` — AiderDesk/Aider stores Markdown chat history at `.aider.chat.history.md` in project root (env: `AIDER_CHAT_HISTORY_FILE`). Format: `# aider chat started at ...` session headers, `####` H4 = user messages, bare text = assistant, `> Tokens:/Cost:` = system (filtered out). Position tracking: byte offset (append-only file). `scanners/transcript/openclaw.py` — OpenClaw stores JSONL at `~/.openclaw/transcripts/YYYY-MM-DD/<session>/transcript.jsonl` (env: `OPENCLAW_STATE_DIR`). Standard JSONL with `content`/`output`/`arguments` fields. Position tracking: line count. Both adapters use custom `can_scan()` checking `AI_GUARDIAN_IDE_TYPE` env var (not adapter name) because both share the KiroAdapter (name="Kiro"). Registered first in `TRANSCRIPT_ADAPTERS` list (before Cline) for env-var-priority matching.

- [2026-07-20] **Copilot Chat (VS Code) transcript adapter (#940):** `scanners/transcript/copilot_chat.py` — VS Code stores Copilot Chat sessions as JSONL delta journal files in `workspaceStorage/*/chatSessions/*.jsonl` and `globalStorage/emptyWindowChatSessions/*.jsonl`. Uses delta journal format: `kind:0` (base snapshot with `v.requests[]`), `kind:1` (set mutation at path `k`), `kind:2` (array append). Text extracted from `requests[].message` (text/prompt/content fields) and `requests[].response` (value/result/text fields, nested response parts). `kind:1/2` deltas walk all string values recursively. Position tracking uses line count with `copilot-chat:{session_id}` key. Session discovery: `COPILOT_CHAT_DATA_DIR` env var, or glob `workspaceStorage/*/chatSessions/` for session files by `sessionId` or most-recent mtime. Opens files with `utf-8-sig` encoding to handle BOM. Registered before `WindsurfTranscriptAdapter` in `TRANSCRIPT_ADAPTERS`; `name` = `"GitHub Copilot"` matches `CopilotAdapter.name`.

- [2026-08-13] **Detector caching (#1952):** `prompt_injection.py` provides `get_cached_detector(config)` and `get_cached_unicode_detector(config)` — keyed by SHA-256 of JSON-serialized config dict. `detect()` resets per-call mutable state (`last_*`, `findings`) at entry so cached instances are reuse-safe. `invalidate_detector_cache()` clears both caches — called from `tests/conftest.py` autouse fixture to prevent cross-test leaks. Tests that previously mocked `PromptInjectionDetector` constructor must now mock `get_cached_detector` at the consuming module's namespace (e.g., `ai_guardian.scanners.file_scanner.get_cached_detector`).

- [2026-08-18] **Object-form updatedToolOutput for Bash redaction (#2042):** `updatedToolOutput` for Bash tool requires `{"stdout": text, "stderr": "", "interrupted": false}` — bare string is silently ignored. `BaseAgentAdapter._wrap_tool_output(tool_name, text)` wraps output per tool; Bash gets object form, others bare string. Secret redaction path in `post_tool_use.py` now uses `modified_output` (allow + updatedToolOutput) instead of `redacted_output` (block + additionalContext workaround). `format_response()` across all adapters gains `tool_name: Optional[str] = None` param. `updatedMCPToolOutput` stays bare string (MCP tools have their own protocol). When testing `updatedToolOutput` for Bash, assert it's a dict and check `.get("stdout", "")`.

- [2026-08-18] **Unified violation logging (#2020):** `violations/log_violation.py` provides `ScanContext` dataclass and `log_violation(result, context)` function. All 10 `_log_*_violation()` functions now delegate to `log_violation()` — custom dict building replaced by `ScanResult.to_blocked_dict()` + `blocked_overrides` for scanner-specific keys. `post_scan_filters.py:log_scan_violation()` delegates via `_scan_context_from_post_scan()`. SDK path (`sdk.py`) now logs violations after `scan_content()` via `_log_scan_results()` helper (fixes #2019 gap). When mocking violation logging in tests, mock at `ai_guardian.violations.logger.ViolationLogger` (canonical module) — the old per-module mock targets (`ai_guardian.hook_processing.ViolationLogger`, `ai_guardian.tools.policy.ViolationLogger`, etc.) no longer work since all logging routes through `log_violation()` which imports `ViolationLogger` from its canonical module.

- [2026-08-19] **Normalized scanner signatures — _dispatch_scanner eliminated (#2050):** All 8 content `run_*_scan()` functions now accept `**_kwargs` to absorb unused common params. Positional args normalized to keyword-only: `run_supply_chain_scan(content, *, file_path=None, filename=None, ...)`, `run_canary_detection_scan(content, *, file_path=None, filename=None, ...)`, `run_config_file_scan(content, *, file_path=None, ...)`, `run_secret_scan(content, *, filename=..., secret_context=None, ...)`. `context` param renamed to `secret_context`. `_dispatch_scanner()` deleted — `scan_content()` calls `entry.run_fn(text, config=..., file_path=..., ...)` directly. Adding a new scanner now requires only 1 edit (registry definition) instead of 3 (registry + dispatcher + post-processing). Tests mock at `ai_guardian.hook_events.scanners.run_*_scan` (not `pipeline.run_*_scan`) with `reset_default_registry()` autouse fixture so the registry rebuilds with mocked functions.

- [2026-08-20] **Per-provider request normalization for OpenAI-compat (#2083):** `openai_compat.py` defines `ProviderCaps(flatten_content, supports_tools)` and `normalize_request_kwargs()`. `_build_openai_client()` tags each client with `_ai_guardian_provider` attribute. `OpenAILoopStrategy.call_api()` reads the tag, gets caps via `get_provider_caps()`, and normalizes kwargs before the API call. Ollama/llama.cpp get `flatten_content=True` — structured content blocks (`[{"type":"text","text":"..."}]`) become plain strings. All providers keep `supports_tools=True` by default (Ollama tool support is model-dependent). vLLM/OpenAI/Azure pass through unchanged. The `_GuardedClient` proxy path (low-level `guarded()`) does NOT normalize — users manage their own message format there.

- [2026-08-19] **Config-driven provider selection (#2079):** `create_client()` in `_extractor.py` now accepts `provider` and `provider_config` kwargs. `provider` selects the LLM backend (Anthropic family: `direct`/`anthropic`/`vertex`/`bedrock`/`foundry`; OpenAI-compatible: `openai`/`azure`/`ollama`/`llamacpp`/`vllm`). `provider_config` dict overrides env var names (`api_key_env`, `base_url`, `project_id_env`, `region_env`). `AI_GUARDIAN_SDK_PROVIDER` env var overrides both code arg and config. `guarded()` reads `sdk.provider` + `sdk.provider_config` from merged config and passes to `create_client()`. OpenAI-compatible providers create `openai.OpenAI()` (or `AzureOpenAI` for azure) with `base_url` from `provider_config`. Anthropic family providers create the corresponding Anthropic SDK client. For local servers (ollama/llamacpp/vllm), `api_key` defaults to `"not-needed"` unless `api_key_env` is set.

- [2026-08-12] **ScannerRegistry Phase 5 — unified scan_content() (#1932):** `scanners/pipeline.py:scan_content()` now registry-driven with 8 content scanners (PI, CP, SC, OL, CD, CFS, Secret, PII) instead of hardcoded 3. Calls `entry.run_fn()` directly (dispatcher eliminated in #2050). `_get_content_pipeline()` filters registry entries by hook_event (when provided) or by `_CONTENT_SCANNER_NAMES` + input availability (SDK path). New params: `hook_event`, `tool_identifier`, `latency_timer`, `content_overrides` (per-scanner text substitution), `scanner_kwargs` (per-scanner extra kwargs), `registry` (injectable). `content_pipeline.py:run_content_pipeline()` now calls `scan_content()` for raw detection, then iterates results for post-processing (apply_post_scan_pipeline, response formatting, PII redaction, transcript scanning, context saving). Config resolution via `_resolve_scanner_config_for_entry()` uses `entry.config_section` + `_load_config_section()` generically. `scan_file()` simplified: calls `scan_content()` with file_path (SC/CFS now included automatically). Results include non-detected items with error_message (for scanner-not-installed warnings). Error results have `extra["scan_error"]` for fail-closed handling.

- **PEP 508 platform-release markers:** Do not compare `platform_release` numerically in project dependencies. pip versions can evaluate every branch on Linux and parse kernel strings such as `6.17.0-1022-azure` as invalid PEP 440 versions. Use safe string gates and test the exact runner release; build smoke tests must install the checked-out wheel rather than stale PyPI metadata.

- **Ubuntu runner migration (#2491):** Once Ubuntu 26.04 is available, all GitHub Actions Linux jobs use the explicit `ubuntu-26.04` label. The former compatibility workflow is intentionally repurposed as `container-build-validation.yml` so release readiness retains scanner, scenario, QEMU, Buildx, and multi-architecture coverage without duplicating the supported Python matrix.

- [2026-10-03] **Rootless Podman host-config mounts:** A host `0600` config bind-mounted into an image running as UID 1000 appears as UID 0 without `--userns=keep-id`, causing entrypoint staging to fail. Apply the flag only to Podman commands; do not weaken host permissions or add a writable host copy.

- [2026-10-03] **OpenShell Codex credential selection:** The sandbox creator intentionally selects the `openai` gateway profile for Codex API-key credentials and `codex` for local OAuth. Do not silently fall back between credential types when a profile is missing; the active gateway must have the matching imported profile or the user must select an existing provider explicitly.

- [2026-10-03] **OpenShell 0.1.2 gateway migration:** The RPM upgrade preserves an existing schema-v1 `~/.config/openshell/gateway.toml` and refuses to start until it is manually migrated to `[openshell] version = 2` with scalar `compute_driver`. Keep a backup before changing the user config.

- [2026-10-03] **OpenShell provider credential verification:** Provider-backed
  credentials appear in the sandbox as opaque placeholders. A raw `curl`
  request without an explicit bearer header returns missing authentication; when
  the placeholder is supplied from `OPENAI_API_KEY` in the header, `/v1/models`
  returns HTTP 200. Codex therefore reaches OpenAI correctly; its remaining
  failure, `You have no credits remaining`, is an account billing/quota issue.

- [2026-10-03] **Host Codex auth comparison:** The host Codex reports
  `auth_mode=chatgpt` with OAuth tokens (`codex-cli 0.157.0`) and no API key in
  `~/.codex/auth.json`. The OpenShell sandbox intentionally uses API-key auth
  (`0.154.0`), so a working host session is not evidence that the API-key
  organization has inference credits.

- [2026-10-04] **CLI setup auto-detection (#2494):** Plain setup must use
  `IDESetup.list_installed_ides()` plus `check_hooks_for_ide(..., integrity=True)`
  like the tray, so healthy integrations are never rewritten. Non-interactive
  setup configures all pending integrations; interactive multi-setup defaults to
  all but accepts a numbered subset or skip. Keep legacy `--create-config`-only
  behavior isolated from hook setup unless an integration target is selected.

- [2026-10-04] **Sandbox form choice defaults (#2493):** Reopened tray forms can
  carry an empty or invalid choice value between providers. Normalize the
  initial-config choice before rendering and make Tkinter/NiceGUI use the same
  first-choice fallback while preserving an explicit snapshot selection.

- [2026-10-04] **OpenShell Codex pin maintenance (#2478):** The issue's
  generated `0.159.3` target was superseded by npm's `0.160.0` release before
  implementation. Check the live version monitor before pinning maintenance
  updates; the OpenShell image was Codex-only at that time (Vertex clients were
  added by #2473).

- [2026-10-05] **OpenShell supervisor middleware (#2484):** External services
  use the v0.1.2 `Describe`/`ValidateConfig`/HTTP/WebSocket contracts and are
  registered by gateway TOML plus sandbox policy, not an OpenShell install
  command. Extension JWTs require the exact `openshell-ext+jwt` type, opaque
  audience, gateway issuer, and the complete `iss`/`aud`/`sub`/`iat`/`exp`/
  `jti`/`caller_kind` claim set; only supervisor callers carry `sandbox_id`.

- [2026-10-06] **OpenShell middleware clean-workload qualification (#2484):** A
  provider-backed policy is required for the tested OpenShell v0.1.2 delegated
  workload, while the middleware can reject a keyless `curl` request during
  pre-credential evaluation. A short-lived sandbox transitions to `Completed`
  when its main process exits even if managed Podman containers remain briefly.

- [2026-10-06] **Provider-content diagnostic privacy:** Passing
  `source_type="provider_content"` must suppress matched text and Unicode
  details in every prompt-injection diagnostic path, including debug logs; only
  source, confidence, and rule metadata may be logged.

- [2026-10-06] **Documentation privacy:** OpenShell examples must use neutral
   host/interface placeholders such as `middleware.example.internal`, never a
   developer-specific private IP address.

- [2026-10-06] **OpenShell policy composition:** Middleware policy is an
  OpenShell operator artifact. Apply a complete policy with `openshell policy
  set`; do not hide policy composition inside AI Guardian sandbox creation.

- [2026-10-06] **OpenShell Codex sandbox path:** Raw Community-image sandbox
  creation does not stage provider placeholders into Codex `auth.json`. For a
  usable Codex sandbox, verify Providers v2 and use AI Guardian's managed
  `sandbox create --runtime openshell --cli codex --provider` flow.

- [2026-10-06] **OpenShell supervisor reachability:** On this macOS Homebrew /
  Podman setup, the supervisor cannot reach host loopback. AI Guardian's
  macOS plaintext relay keeps grpcio on loopback while exposing the selected
  host interface address; remote gateways require TLS/reachable deployment.

- [2026-10-06] **Middleware relay lifetime:** The macOS TCP relay must keep
  HTTP/2 connections open across Describe, ValidateConfig, and evaluations;
  never impose a short per-connection join timeout. Track active sockets and
  close them only during relay shutdown.

- [2026-10-06] **OpenShell sandbox provider activation:** A sandbox can accept
  policy while `DesiredConfigurationReady=False` if its attached provider has
  no installed credentials. Later traffic reports the misleading
  `middleware_failed: binding_not_described`; inspect provider status and run
  `openshell provider update NAME --credential OPENAI_API_KEY --wait` before
  debugging middleware bindings.

- [2026-10-06] **Managed sandbox provider selection:** Passing explicit
  `--provider ai-guardian-codex` bypasses AI Guardian's API-key provider refresh.
  With `OPENAI_API_KEY`, omit `--provider` so sandbox setup selects or refreshes
  `ai-guardian-openai`; use the Codex provider only for OAuth credentials.

- [2026-10-07] **Rust OpenShell middleware runtime:** The Rust service owns
  OpenShell gRPC and uses the daemon Unix socket by default; explicit remote
  deployments use `AI_GUARDIAN_DAEMON_URL` plus an authenticated token. Codex
  uses WebSocket transport, so the Rust manifest must advertise the text-
  WebSocket binding or provider prompts bypass request scanning.
- [2026-10-07] **Codex middleware denial UX:** OpenShell closes denied
  WebSocket messages with code 1008, and Codex retries that stream before HTTP
  fallback. HTTP middleware denials are immediate 403 `middleware_denied`; a
  Codex custom Responses provider with `supports_websockets=false` avoids the
  retry loop.
- [2026-10-11] **Session-scoped pause identity:** Build a daemon session key only
  from an adapter-normalized stable session ID; never infer one from cwd or a
  time bucket, since concurrent sessions can share a project directory. Keep
  session pause state in memory and clear it on SessionEnd, inactivity expiry,
  or daemon restart. Expose only known stable-ID sessions and direct other
  callers to global or directory-wide controls.
