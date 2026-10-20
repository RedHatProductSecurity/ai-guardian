---
description: session handoff, regenerate with /handoff when a quest finishes
budget_tokens: 1000
---
# STATUS - ai-guardian

> Single source of truth for resuming work. Read this FIRST when starting a session.
> Last updated: 2026-10-20

---

## Issue #2556 Codex candidate qualification — 2026-10-19

### Current: deferred to 1.22.0; awaiting upstream-supported Codex integration

- USER DIRECTION (2026-10-20): stop the additional executable-policy fix and
  qualification; prefer waiting for upstream OpenShell integration support.
  This supersedes the preceding Prepare fix selection. Do not implement a
  cached-daemon authorization, resume probes, or change live resources unless
  explicitly asked. Preserve the original identity fix and other uncommitted
  work on `2556`; default Codex pin remains `0.160.0` and #2556 stays open.
- User explicitly authorized publishing the neutral upstream report:
  https://github.com/NVIDIA/OpenShell/issues/4751
  It is a concrete documentation/integration request, not a confirmed core bug.
  Verified its body contains no AI Guardian branding and retains custom-image/
  wrapper context, no default-image reproduction, and no live v0.1.4 claim.
- User requested a current-issue comment and deferral to 1.22 while retaining
  branch `2556` for a later retry. Posted the upstream link and deferred status:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2556#issuecomment-6295221104
  Created the missing `1.22.0` release label using the repository convention;
  replaced only `1.20.0` with `1.22.0` on #2556. Verified OPEN and other labels
  unchanged. Branch and all local/uncommitted work remain untouched; no commit,
  push, PR, branch cleanup, live resource change, or qualification resume.
- Security correction before publication: tagged OpenShell `identity.rs`
  implements SHA-256 trust-on-first-use caching and rejects later changed hashes
  at pinned paths. Earlier blanket same-path replacement statements were too
  broad. Both the upstream report and current-issue comment acknowledge existing
  integrity checks and focus on package provenance/supported update handling.
- Existing project issue updated with sanitized paused-qualification evidence:
  https://github.com/RedHatProductSecurity/ai-guardian/issues/2556#issuecomment-6294479693
- User then requested a read-only upstream issue lookup. As of 2026-10-20,
  searches across NVIDIA/OpenShell issues/PRs (including comments) for the
  managed app-server path, denial code, candidate version, and broader Codex
  terms found no exact matching report/fix. Do not assert none can exist or
  promise a planned release. #440 is an older closed policy-path discussion
  explicitly calling binary+endpoint denial expected; it does not track this
  managed-daemon layout. #4214/#4215 concern the earlier fixed identity issue,
   not this executable authorization gap. No report was created at that lookup;
   the subsequently authorized publication is linked above.
- Current guidance lookup: both OpenShell `v0.1.4` and `main` reference Codex
  profiles still list launcher/npm paths and explicitly require operator edits
  to match the image's real binary paths. #440 collaborator comments recommend
  a base-policy update for its older case; its port-forward advice concerns old
  sign-in, not our already-working OAuth routing. No specific secure managed-
  daemon-cache recommendation/fix was found. Explain generic configuration
  guidance separately from version-specific support; do not promise a gateway
   upgrade resolves this. User's initial "ok" approved drafting, not publishing;
   the later explicit publication request has now been completed.
  Current draft: `/tmp/opencode/openshell-codex-managed-daemon-issue-draft.md`;
   now published as #4751. User requested no AI Guardian mentions in the report.
  Removed branding and implementation-specific service version, while retaining
  the custom image/wrapper and external-middleware context. Do not claim native
  upstream reproduction or omit relevant custom-environment limitations.
- Version follow-up: fetched tagged sources confirm `providers/codex.yaml` is
  byte-for-byte identical in `v0.1.3` and `v0.1.4`; it omits the observed managed
  daemon path. Reviewed v0.1.4 release notes and comparison commits: no specific
  managed-daemon authorization fix identified. This is source/document evidence,
  not a live v0.1.4 reproduction. Do not claim every runtime behavior is unchanged
  or that a v0.1.4 failure was reproduced. Upgrade alone is not an established
  solution; keep the upstream draft's observed runtime version at 0.1.3.

- Latest operator result (2026-10-20): creation now works, the operator can connect
  to the rebuilt sandbox, launch Codex, and reports that it reaches the agent/model.
  This is positive operator-reported startup/connectivity evidence after the
  identity fix, not a full qualification. Operator now reports actual runtime
  Codex `0.162.1`, AI Guardian `1.19.0`, and OpenCode `1.19.0`; rebuilt image digest
  is `sha256:cdea12f2ebfb2a1af0ced1b6e40893c9b75cebe8cfa295689f43ac246c0009d7`,
  platform `linux/amd64`. Operator account probe now passes `account/read` with
  ChatGPT auth, present workspace routing, and identity matching bootstrap.
  Operator explicitly confirms the intended identity/context is their personal
  account, completing the account/workspace gate. Gateway now reports healthy
  OpenShell `0.1.3` with registered `content-guard` implementation
  `ai-guardian/rust-middleware 1.20.0-dev` (protocol 1.0). The sandbox effective
  policy is now version 2, submitted and loaded after the operator restarted
  the external service. Effective policy preserves the original controls and
  attaches `content-guard` fail-closed on all three Codex hosts. This resolves
  the earlier ValidateConfig TCP-connect blocker at application time. Clean
  Codex traffic now fails after submitting the prompt with `Reconnecting...
  waiting for network...`. Current direct Describe confirms Running,
  `ai-guardian/rust-middleware 1.20.0-dev`, registration `content-guard`; gateway
  also reports Active. This does not verify the sandbox-to-service route or
  scanner-daemon backend. Normal traffic qualification remains blocked, not a
  successful threat-denial test. Native logs now identify a concrete blocker:
  `transparent_tcp_policy_denied` for the canonical managed app-server daemon
  `/sandbox/.codex/packages/app-server-daemon/releases/0.162.1-x86_64-unknown-linux-musl/bin/codex`
  connecting to chatgpt.com:443. Both Codex rules lack this executable path;
  the denied connection is stopped before content middleware. Tagged upstream
  documentation confirms the managed package layout. User has now stopped the
  additional fix in favor of upstream-supported integration; do not authorize
  a writable `/sandbox` cache or continue live qualification. Preserve policy;
  no restart, credential changes, pin update, or lifecycle/denial testing yet.
- User authorized the compatibility fix. Updated `sandbox.py` to return the
  managed provider's literal account identity from the same credential snapshot,
  validate it before provider mutation, and forward it separately as
  `CODEX_ACCOUNT_ID`. Conflicting overrides fail; duplicate values are removed.
  Raw Codex credential flags (including API keys) stay in the provider process,
  not sandbox arguments. Explicit providers use only explicit identity metadata.
- Updated `container/entrypoint.sh` to use the literal identity for local routing,
  retain opaque access/refresh tokens and the synthetic ID token, and reject
  missing/placeholder/invalid identity or incomplete OAuth without API fallback.
  Preserve atomic auth writes, restrictive permissions, and existing auth on error.
- Added/updated isolated unit and complete UX contracts, sandbox docs, changelog,
  and a credential-free, no-network bootstrap smoke step for release-readiness CI.
  No new project dependency, SDK/config schema change, pin update, or routing
  validation weakening. Codex stays `0.160.0`; retaining it is not qualification.
- Regressions reproduced the mismatch before the fix. All 398 related tests pass
  across sandbox command, container scripts, sandbox tray, the new Codex OAuth UX
  contract, and the existing create/connect UX contract (one existing GI warning).
  Ruff, Black (`--target-version py310`), Pylint, Mypy and diff checks pass.
  Related sandbox statement coverage is 74%; 23/24 changed executable lines are
  covered (the uncovered line is the moved existing Providers-v2 error raise).
  Coverage artifacts: `/tmp/opencode/guardian-2556-compat.coverage` and
  `/tmp/opencode/guardian-2556-compat-coverage.json`. Coverage is a transient
  Apache-2.0 validation tool only. Manual simplification review completed;
  no `/simplify` skill is available in this harness.
- Keep #2556 open. Rebuilt candidate identity/runtime versions and intended
  personal-account selection are recorded; next verify middleware
  registration/version/policy/denial and lifecycle checks.
  Do not retrofit the existing sandbox or copy credentials. No agent live gateway
  controls, credential reads, builds/container scenarios, commits, pushes, or PRs.
- Operator now reports the rebuild passed for
  `localhost/ai-guardian-openshell:codex-0.162.1-identity-fix` using
  `CODEX_VERSION=0.162.1`. Subsequent digest/runtime outputs are recorded above.
  Socket existence/listening were verified and the operator subsequently reports
  successful creation/connect/startup. Account/workspace qualification has since
  passed; middleware and lifecycle qualification are next. Stop on a fresh-login prompt;
  do not reuse or modify the old failed candidate sandbox.
- Follow-up 2026-10-20: the suggested `ag-codex-2556-identity` name was 22
  characters; OpenShell rejected it with `name exceeds maximum length (22 > 19)`.
  This was an agent guidance error, before Codex startup, not evidence against
  the rebuilt image. Provider refresh was acknowledged persisted with
  `waiting_for_supervisor`; do not treat that as proof all supervisors applied it.
  The unrelated host-config Git-filtering warning also appeared. Retry ordinary
  creation with the shorter `ag-2556-id` (10 characters); no image rebuild or
  production change is needed for this name error. The wrapper intentionally
  preserves OpenShell names and native validation rather than silently truncating.
- The shorter-name retry also failed before Codex startup: the configured
  `/run/user/<uid>/podman/podman.sock` is missing again (`ENOENT`) and failed-create
  cleanup remains pending for `ag-2556-id`. The reason the socket disappeared is
  unknown; do not assume a disabled service or a candidate regression. Provider
  refresh again persisted with `waiting_for_supervisor`; config Git-filtering
  warning remains separate. Ask the operator to check socket enablement, start
  the existing user socket without sudo, confirm active, and inspect only this
  named sandbox. Require `sandbox not found` before retrying; no manual container
  removal, blanket delete, gateway restart, or new image build.
- Operator confirms `podman.socket` is enabled and active after starting it.
  `ag-2556-id` remains `Deleting` / `ConfigurationPending`, with no main process
  or workload activation. A bounded recheck still reported the same phase and
  resource version. Require absence before retrying creation; do not issue
  repeated deletes or manually remove managed containers.
- Checked installed diagnostic help and upstream `v0.1.3` compute reconciliation:
  sweeps are one minute and orphan grace is five minutes from record creation.
  Thus the earlier 30–60-second check alone did not establish a stall. Pruning
  also requires successful backend probes and no pending driver operation;
  none of those runtime conditions is yet proved. No promise of cleanup by six
  minutes or restart recommendation is justified.
- Next operator diagnostics, read-only/no sudo: verify the configured socket's
  file type, show `ActiveState`/`SubState`/`Listen` for `podman.socket`, and inspect
  `openshell logs ag-2556-id --source gateway --level warn --since 1h -n 40`.
  Share only sanitized socket/cleanup/deletion warnings, not full logs. The
  installed CLI supports this sandbox-scoped gateway log query; its doctor
  command is a local development-prerequisite checker, not a cleanup repair.
  If the resource is now absent, confirm by named get before any retry. Socket
  recurrence cause and Codex qualification remain unknown; no live agent controls.
- Prior operator diagnostics: configured path is a socket; the user unit is
  `active` / `listening` and `Listen` matches that path. The sandbox-scoped log
  query now returns `sandbox not found`, suggesting the failed record was pruned.
  Confirm with `openshell sandbox get ag-2556-id`; only if absent, retry ordinary
  creation with the same rebuilt image and explicit OAuth. No rebuild is needed.
  This is prerequisite/cleanup evidence, not Codex startup or middleware evidence.
- Prepared a temporary operator-only account probe at
  `/tmp/opencode/guardian-2556-account-probe.py`; not project/runtime source.
  Upload only that file to `/tmp/guardian-2556-account-probe.py` in `ag-2556-id`,
  then run it from the already-connected sandbox shell. It starts its own local
  Codex app-server, negotiates `experimentalApi` plus explicit gateway OAuth,
  sends `initialized`, and requests `account/read` with `refreshToken: false`.
  It requests no login/model turn or config mutation, suppresses raw RPC/stderr,
  prints status/auth-type/routing-presence/identity-match only, and cleans up only
  its own probe child. A shared 40-second deadline bounds the handshake/read.
  Thirteen synthetic offline checks, Black, and Ruff pass; no real Codex/provider
  or sandbox was invoked by the agent. Fixture:
  `/tmp/opencode/guardian-2556-fake-app-server.py` (do not upload).
  Positive probe output establishes routing matches `CODEX_ACCOUNT_ID`, not that
  the operator intended that workspace. Ask for a separate private intended-host-
  workspace match/mismatch/unknown attestation. Synthetic sandbox email is not
  account identity proof. Operator uploaded and ran the probe successfully:
  `account_read=passed`, `auth_type=chatgpt`, `workspace_routing=present`,
  `identity_matches_bootstrap=yes`. The standalone-file upload warning is expected
  and upload completed. This is positive OAuth/account-read/routing evidence,
  not independent proof of intended selection or middleware enforcement. Ask the
  operator whether the host Codex account/workspace used for creation is the
  intended one: match/mismatch/unknown only; no names, emails, or IDs. Keep the
  default pin unchanged and #2556 open until the remaining gates are complete.
- Operator tentatively inferred intended account selection from model access and
  asked whether workspace means the empty `/sandbox` directory. Do not record
  that as independent account-selection confirmation. Clarify: workspace routing
  refers to the ChatGPT personal/organization account context, not filesystem
  content. A valid model reply proves usable authentication; the probe additionally
  proves routing matches bootstrap metadata, not operator intent. The guided
  qualification create omitted `--repo`, so no project upload was requested.
  For OpenShell, `--repo .` at creation uploads to `/sandbox/repo`, not a live
  host bind mount. No recreation/upload is needed for this auth check. Ask only
  whether the host Codex login is the intended account/context; no identity data.
- Operator then explicitly confirmed their intended personal account. Combined
  with the successful account/read and routing-to-bootstrap probe, record the
  account/workspace gate as passed (operator-reported). Next read-only checks:
  `openshell gateway info` for gateway registration/activation and
  `openshell policy get ag-2556-id --full` for effective `network_middlewares`
  attachment, nested registration name, `on_error`, and included Codex hosts.
  Request only these non-secret fields, not raw config/provider responses. The
  tray's standalone Check middleware readiness action can separately report the
  external Rust implementation/version via Describe; sandbox Python package
  version is not service-version evidence. Do not restart services or replace
  policy before inspecting current state; actual middleware denial remains untested.
- Operator supplied gateway and effective-policy evidence: gateway healthy,
  Podman/credential driver `0.1.3`, `content-guard` registered as AI Guardian Rust
  middleware `1.20.0-dev`, protocol 1.0. Keep this external-service version
  distinct from sandbox Python package `1.19.0`. Effective policy revision 1 has
  expected filesystem/provider network rules but no `network_middlewares`, so
  provider-boundary scanning is not yet attached to `ag-2556-id`.
  Next operator-only step: export this sandbox's `--base` policy (not `--full`),
  strip CLI table metadata, append only the `network_middlewares` mapping from
  `container/policies/openshell-middleware.yaml`, review preserved base controls
  and exactly one middleware mapping, then apply the complete file with native
  `openshell policy set ag-2556-id --policy ... --wait`. Use a fresh
  `/tmp/opencode/ag-2556-id-policy.yaml`; no matching file currently exists.
  Never apply the overlay alone or provider-composed effective export. The
  shipped profile matches registration `content-guard`, fails closed, and
  includes api.openai.com/chatgpt.com/ab.chatgpt.com. Confirm effective attachment
  after application; ask only for apply status and the middleware section.
  No image rebuild, gateway restart, or agent-run runtime/policy operation.
- Operator attempted the complete-policy update. OpenShell rejected it with
  `middleware config 'content-guard' is invalid: middleware ValidateConfig failed`
  followed by service-unavailable/TCP-connect/tonic ConnectError. This reports a
  transport failure, not a specific YAML/schema defect or Codex regression.
  The following effective-policy query still shows revision 1, the previous hash,
  and no middleware attachment. The external Rust endpoint is unreachable from
  the gateway; stopped process, wrong listener/address, and other connectivity
  causes remain unverified. Existing gateway extension metadata is not liveness.
  Next ask how the operator runs the external service (terminal, actual user
  unit, other manager/container, unknown), then inspect that process/listener
  with read-only diagnostics; the tray Describe readiness check is available.
  Do not assume the example systemd unit is installed, retry policy repeatedly,
  restart gateway, rebuild images, weaken fail-closed policy, or read credentials.
- Operator answered the launch-method question: the Rust service was started in
  a terminal and may have stopped. Its exit/liveness is not yet confirmed.
  Next: inspect the original terminal; only if it exited, relaunch the existing
  binary with the original registration, bind address/port, OpenShell version,
  and daemon connection settings, and keep that terminal open. Do not start a
  duplicate if it is still running. Once listening, retry the existing complete
  policy once from a second host terminal; on success query effective attachment.
  Keep the same registered endpoint; no gateway restart or rebuild is needed for
  restoring that foreground process. On another error stop and request only its
  sanitized diagnostic, not raw logs, environment dumps, or authentication files.
- Latest direct readiness result is Not responding / Describe UNAVAILABLE;
  gateway extension Active is explicitly metadata only. The operator's initial
  belief that the process remained running was withdrawn as uncertain. Before
  any relaunch/retry, request host-only `pgrep -fl` (PID/name, not full arguments)
  for the Rust binary and `ss -ltnp` filtered to Guardian/default-port listeners.
  If there is a live listener, next compare its bind with the effective gateway
  registration (scheme/host/port only); no raw TOML, environment, or logs.
- Operator ran both host diagnostics; `pgrep -fl` for the standard middleware
  binary and `ss` filtered to Guardian/default-port listeners produced no output.
  Report this as no expected process/listener found, not a universal process
  search or proof of a specific exit cause. Guide operator to rerun the original
  launch command for the existing binary with the same endpoint/registration/
  daemon settings, keeping its host terminal open. If that command is unavailable,
  ask only for the configured content-guard endpoint (scheme/host/port) to prepare
  a correct launch; do not guess a bind address or request credentials. After
  startup, request direct tray readiness status/version (or sanitized startup
  error). No policy retry until ready; no gateway restart or rebuild.
- Operator's documented launch attempt stopped at the shell guard because
  `MIDDLEWARE_HOST` was unset/empty; it was not a Codex failure or proof of a
  successful Rust launch. The operator subsequently says the middleware is
  restarted. Treat this as operator start status only, not endpoint reachability.
  Request current direct tray readiness implementation/version. Only if Running
  retry `/tmp/opencode/ag-2556-id-policy.yaml` with native `policy set --wait`;
  only on success inspect effective policy. Stop on an error and share sanitized
  status only. Actual provider-boundary denial and lifecycle gates remain pending.
- Existing `.wolf/STATUS.md` / `cerebrum.md` work was preserved. OpenWolf hooks
  updated the anatomy index automatically; the new UX contract is untracked until
  the external DAF publication workflow stages it with the other changes.

- Operator now reports `Policy version 2 submitted` and `loaded (active version:
  2)`. Effective revision 2 includes `network_middlewares.content-guard` with
  `middleware: content-guard`, `on_error: fail_closed`, response redaction,
  shipped scanner ownership, and api.openai.com/chatgpt.com/ab.chatgpt.com.
  Filesystem and provider network controls remain present. This is successful
  middleware validation/attachment evidence, not an actual inspected/denied
  request. First run a fresh Codex process in the same sandbox and request
  `Reply with OK without using tools.` to establish normal traffic after policy
  activation. Stop on fresh-login prompts/errors; share only sanitized status.
  Then qualify actual provider-boundary denial (not a hook block/model refusal)
  and sandbox lifecycle. No default pin update or agent runtime controls.

- Latest operator result: fresh Codex attempt after policy activation failed to
  connect to the model. Operator suspects middleware; no exact error is supplied,
  so do not assign a root cause or call this expected threat blocking. The
  fail-closed path may also block clean requests on service/backend/inspection
  failures. Request exact sanitized user-visible error (HTTP status/reason_code
  if visible), startup vs after the OK request, and current direct tray readiness.
  Only a correlated reason/status from middleware logs is needed, not raw logs,
  payloads, authentication files, or env dumps. Prior Oct 9 paused-middleware
  denial is logged and fixed, but current evidence does not establish recurrence.
  Keep #2556 open and pin unchanged; clean baseline must pass before continuing.

- Operator clarifies startup succeeded; failure occurs after submitting the
  prompt, shown as `Reconnecting... waiting for network...`. The post-restart
  readiness check now directly confirms AI Guardian Rust middleware `1.20.0-dev`
  Running and gateway registration `content-guard` Active. Need runtime failure
  evidence, not another account/login fix or assumption that the listener died.
  Next operator-only diagnostic: `openshell logs ag-2556-id --source all --level
  warn --since 20m -n 40`; inspect privately and share only matching sanitized
  error/status/reason fields. In Rust terminal, look for request/response/
  WebSocket decision metadata (`blocked`, `reason_code`, finding_count) or control-
  plane-unavailable warning. Say no matching middleware event if none. Local
  source logs decisions at INFO and backend failures at WARN; gateway WARN output
  alone is not proof of no scanner decision. No raw logs/payloads/auth/env output.

- Operator's native log query returned only `log buffer contains only the last
  40 lines; --since results may be incomplete`, with no warning diagnostic.
  This does not prove absence of errors, middleware events, or scanning. The
  external Rust terminal output has not been supplied. Next request its
  existing-attempt decision/warning metadata only; if it has only startup output,
  report that explicitly. Do not repeat the same WARN query or infer a cause.

- Operator supplied Rust startup and request-only INFO logs. Middleware listened
  on a specific host IP:50051 (do not copy private address to tracked/public docs).
  Logged POSTs to ab.chatgpt.com from 14:37 through 15:01 UTC all have allow
  decisions/zero findings, many at one-minute intervals. No request paths,
  elapsed/deadline/status, or response/WebSocket decisions are supplied; do not
  equate these with the failed generation request or prove scanners actively ran.
  Local response preflight/mode/size rejection branches do not emit the normal
  response-decision INFO log, so their absence is inconclusive. Tagged OpenShell
  v0.1.3 emits native `HTTP_RESPONSE_MIDDLEWARE`, `WEBSOCKET_MIDDLEWARE`, and
  response-failure events with outcome/status/failure metadata. Next operator
  query: retained native logs `--source all -n 300`, no level/time filter, with
  local text filtering to middleware/denial/timeout/upstream/WebSocket/reset
  diagnostics. Share only safe fields, not full lines/payloads/headers/URLs.
  Codex can be exited normally to stop automatic reconnects; do not stop/restart
  sandbox/service or change policy. No new prompt needed for this inspection.

- Concrete network denial supplied: supervisor/OCSF attributes the chatgpt.com
  connection to the managed `app-server-daemon` release executable above, not
  `/usr/bin/codex` or the image npm tree. Neither provider-composed nor base
  `codex_openai` rule includes it. This explains at least one generation blocker;
  no evidence that content middleware rejected those bytes. Official OpenShell
  v0.1.3 provider comments identify ab.chatgpt.com as experiment lookups, so the
  earlier allowed POSTs are not model-success evidence. Tagged Codex README
  documents managed package copying/selection under CODEX_HOME and independent
  daemon lifecycle. Do not blindly add `/sandbox/**` or a mutable-cache wildcard.
  Existing branch changes are preserved; no additional production/policy change
  yet. Ask operator to approve a narrowly scoped trusted-component fix and tests
  before changing executable authorization; qualification and pin remain blocked.

- Stop decision: operator requested the security tradeoff explanation and said
  they prefer an OpenShell-side supported integration rather than proceeding
  with a local executable-policy fix. No second production/policy fix was made.
  Explain that path authorization in writable CODEX_HOME can trust replacement
  bytes at the same path; a broad glob worsens this, while existing endpoint and
  middleware controls still apply. A trusted image-owned read-only package is
  a different boundary. The observed issue is profile/package-layout coverage,
  not proof of incorrect OpenShell core enforcement or the first affected Codex
  version. An upstream change might be a profile/integration update, and an
  upgrade alone may not replace already-imported or locally shipped profiles.
  Do not promise an upstream fix/version or create an upstream issue without
  permission. Record sanitized findings on existing #2556; leave it open.
  No cleanup/revert, commit, push, PR, image build, or further runtime control.

### Qualification history before this local fix

- Initialized managed DAF development session on existing clean branch `2556`;
  read the repository-qualified issue once. No hierarchical context markdown or
  hierarchical skills were present. Loaded applicable DAF/OpenWolf instructions.
- Reviewed stable Codex releases `0.161.0`, `0.162.0`, and `0.162.1`, the tagged
  Apache-2.0 license and NOTICE, and current OpenAI authentication/service terms.
  This is a technical review, not legal approval or acceptance for the operator.
- Default `CODEX_VERSION=0.160.0` remains unchanged. Read-only host probes report
  OpenShell `0.1.3` and Codex `0.160.0`; no agent build or live qualification ran.
- The operator built `localhost/ai-guardian-openshell:codex-0.162.1-qualification`
  and supplied digest
  `sha256:1d8af44690e9b62c5fb5c118d4e88ab2894cdcd26d9a4fecf40e1d610871779d`,
  platform `linux/amd64`, and version output `codex-cli 0.162.1`. This is
  operator-reported image smoke, not independently reproduced OAuth evidence.
- Operator creation of dedicated sandbox `ag-codex-2556` failed before Codex
  startup: the gateway's rootless Podman socket was missing (`ENOENT`), and
  failed-create cleanup remains pending. The ordinary provider refresh persisted;
  no credential values were shared. This is not a candidate Codex regression.
- Operator restored `podman.socket`, confirmed it active, and subsequently
  confirmed `openshell sandbox get ag-codex-2556` returns `sandbox not found`.
  Failed-create cleanup and subsequent creation are operator-confirmed.
- Candidate `codex` then failed during TUI bootstrap with:
  `account/read failed during TUI bootstrap: account/read failed: selected workspace missing from routing discovery (code -32603)`.
  Startup/account/workspace qualification therefore failed; no model reply,
  actual middleware denial, or candidate restart/reconnect qualification passed.
- Static diagnosis: `container/entrypoint.sh:375-379,450-458` intentionally uses
  opaque account placeholders; candidate Codex routing code selects an exactly
  matching account ID from discovery or emits MissingWorkspace. This is consistent
  with an identity-metadata compatibility gap, not proof of the private runtime
  mapping or a universal upstream regression. No auth files/payloads were read.
- Agent read-only image inspection confirms candidate digest/platform and labels:
  Codex `0.162.1`, AI Guardian `1.19.0`, OpenCode `1.19.0`. The explicit gateway
  status field reports `0.1.3` with exit 0. Existing `:dev` differs in Guardian
  (`1.20.0.dev0`) and OpenCode (`1.18.34`), so it is not a controlled A/B baseline.
  Middleware version/registration/policy/denial remain unverified; the prior
  failed-resource policy had no attachment, not proof of the recreated policy.
- Decision: stop qualification at the failed startup gate; retain `0.160.0` and
  leave #2556 open. No login/configuration workaround or routing-check weakening.
  A secure identity-metadata integration and renewed operator qualification are
  required before any pin change. No automatic candidate sandbox deletion.
- Upstream lookup found exact-match NVIDIA/OpenShell #4214, closed as completed
  by merged PR #4215 on 2026-10-06 (commit `5601d71b014545678c9fcb572dad7e6cc09fc448`).
  It reports the same placeholder/discovery mismatch, including Codex `0.160.0`.
  The fix passes literal non-bearer account metadata through Gator's launcher/
  harness while retaining opaque tokens; it is not a generic gateway rewrite.
  GitHub ancestry confirms inclusion in both `v0.1.3` and `v0.1.4`. Our custom
  `container/entrypoint.sh:457` still uses `CODEX_AUTH_ACCOUNT_ID` as account_id,
  with no `CODEX_ACCOUNT_ID` path. This strongly supports adapting our custom
  integration rather than filing a duplicate or assuming a gateway-only upgrade
  resolves it. Keeping the existing pin is not evidence that `0.160.0` works.
  User requested lookup only; no upstream issue/comment or production edit made.
- Existing report caveats: metadata comes from Dockerfile defaults rather than
  the overridden image; `--qualify` runs all three rows including unrelated
  Vertex cases; neither `account/read` nor middleware denial is tested. Record
  actual image metadata and those manual checks separately, not as runner proof.
- Review/progress comment sources: `/tmp/opencode/guardian-2556-review.md` and
  `/tmp/opencode/guardian-2556-candidate-image.md`.
  Infrastructure failure: `/tmp/opencode/guardian-2556-runtime-prerequisite.md`.
  Startup failure: `/tmp/opencode/guardian-2556-startup-failure.md`.
  No agent credential access, live controls, local builds/container scenarios,
  source/pin changes, commits, pushes, or PRs. JSON/diff checks cover bookkeeping;
  no production code changed, so code tests/linters were not required.
- Older handoffs below are historical and outside #2556.

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

- #2556 compatibility fix is local and validated offline; retain Codex `0.160.0`
  and leave the issue open. The operator must rebuild the candidate with the new
  entrypoint, use the patched creator, and create a fresh sandbox. Repeat startup,
  private account/workspace, actual middleware denial, and lifecycle qualification
  before any pin update. Do not treat the old candidate sandbox or the CI-only
  bootstrap smoke as proof of live compatibility. Publish only through the
  external DAF workflow when the user decides; no automatic cleanup or live controls.
- Prior publication/validation tasks below are historical and outside #2556.
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
- Branch/issue: `2556` / `RedHatProductSecurity/ai-guardian#2556`.
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
