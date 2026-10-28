# Password likelihood (experimental, opt-in)

Issue #2612 adds an **offline suspected-password heuristic**, independent of
credential-engine selection. It is **off by default in every profile**, including
strict. It does not access a vault, browser, account database, remote classifier,
credential-validation service or password-training corpus. No dependency is added.

**Release qualification is pending.** A string's randomness or apparent strength
does not establish that it is a password. Do not advertise this feature as
universal password recognition or qualified pre-model leak prevention.

## Existing capabilities and reuse decision

- Bundled service/assignment rules already detect recognizable credentials and
  many password assignments. They remain unchanged.
- `TomlPatternsScanner` performs pattern matching **before** entropy/stopword
  filtering. Those filters do not extract arbitrary standalone candidates.
- The optional `detect-secrets` engine includes Base64/hex entropy plugins, but
  their default extraction is quoted/alphabet-specific, not general mixed-symbol
  or contextual passphrase recognition. Its supported default CLI path is not
  qualified as offline: upstream plugins can perform network verification. Do not
  activate its entire plugin set to implement this feature.
- Reviewed upstream [v1.5.0 license](https://github.com/Yelp/detect-secrets/blob/v1.5.0/LICENSE)
  (Apache-2.0), [entropy plugins](https://github.com/Yelp/detect-secrets/blob/v1.5.0/detect_secrets/plugins/high_entropy_strings.py),
  and [documentation](https://github.com/Yelp/detect-secrets/tree/v1.5.0).
  No upstream code or additional package is incorporated. The implementation
  reuses the existing local `shannon_entropy()` helper, plus bounded structural
  checks. No dictionary/model license, download or language data is introduced.

## Trusted controls and outcomes

The Web Console's **Secret Detection Settings** page has a separate experimental
card. Its enable checkbox and outcome selector **save automatically when changed**;
there is no separate Save button. Changing the outcome does not enable analysis,
and merely opening the page never saves or opts in. Each change saves only that
field in the selected daemon's global configuration, preserving the other control
and unrelated policy. Read-only configuration cannot be changed, and failed saves
show an error notification instead of success.
Project scope cannot activate, deactivate or change this stage. Tool inputs are
data, never configuration. A trusted SDK application may pass explicit policy;
an absent section in an explicit SDK config means off, not workstation fallback.

| Outcome | Behavior |
|---|---|
| Default/off | Existing scanning behavior; no heuristic analysis |
| `ask` (default once enabled) + contextual candidate | Hold the applicable hook decision for private **Allow Once / Block** approval; no approval means denial |
| `ask` + ambiguous candidate | Advisory only; no approval prompt |
| Incomplete/error + `ask` | Ask with an explicit incomplete-analysis warning, not a positive password claim; no approval means denial |
| `warn` | Generic advisory finding; **does not prevent a leak** |
| `block` + contextual candidate | Request denial at applicable hook/SDK boundary |
| `block` + ambiguous candidate | Advisory only, not a universal random-string blocker |
| Incomplete/error + `block` | Request denial without claiming a positive password match |
| Incomplete/error + `warn` | Explicit incomplete-analysis warning; no prevention assurance |

Malformed opted-in outcomes fail conservatively to block; only literal boolean
opt-in enables the stage. Configured secret engines, fallback ordering, language
overlays, project exclusions and annotation processing do not control it.
Existing credential findings are never downgraded by heuristic negative scores.
The shared content pipeline removes a heuristic finding only when reliable
coordinates establish full coverage by a stronger blocking credential finding.
When coordinates are missing, both independently labeled findings may remain.

Ask reuses the existing local/remote daemon → workstation tray → decision path,
including SSH's authenticated poll-only transport. A remote daemon does not need
its own display. An explicit headless preference remains non-interactive and
denies unresolved Ask; a missing/disconnected tray, cancellation, timeout or UI
failure never silently approves. A queued remote timeout is terminal, not a new
local prompt. The existing modal dispatcher retains Tkinter → NiceGUI eligibility,
exclusive toolkit preferences and startup-only fallback.

One approval covers only this operation, including its repeated contextual spans;
it never approves a later hook or changes another scanner's decision. Candidate
values are withheld from the dialog payload, subprocess arguments, queue and audit.
This dialog offers **Allow Once / Block** only: no source recovery, View File,
persistent exception, source annotation or ignore-file editor. Existing explicitly
saved `warn`/`block` outcomes are preserved; missing outcomes now default to `ask`.
SDK and static scans never open a UI. Enforcing SDK checks reject unresolved Ask;
the trusted application must handle that denial rather than assume approval.
The trusted violation Details view offers private review guidance, not a copyable
source/persistent-exception snippet. Static reports retain only validated numeric
locations and fixed class labels; they do not copy arbitrary fields from findings.

## Initial supported classes and limits

| Candidate class | Initial treatment |
|---|---|
| Mixed-symbol or alphanumeric random-looking ASCII spans | Ambiguous without credential context; advisory only |
| A bounded value immediately following explicit password/passphrase prose | Contextual suspicion, not known-value identity |
| Joined lower-case word-like, CamelCase, separator-delimited values | Contextual only; no dictionary segmentation or language claim |
| Quoted, spaced word sequences | Contextual only, bounded single-line value |
| Arbitrary context-free joined words, ordinary sentences | **Not reliably recognized; deferred** |
| Multilingual segmentation, escaped/multiline quoted passphrases | **Not qualified; deferred** |

Context is deliberately narrow, not any credential-related word anywhere in a
document. Confusable identifiers, URLs, UUID-like values, digests and encoded data
reduce only context-free heuristic scores. They are not global exclusions from
stronger scanners, and explicit credential context can still flag such forms.
Short/common passwords and unsupported layouts can be missed. Numeric confidence
probabilities and strength estimates are intentionally not reported.

Fixed work limits: 262,144 input characters, 128 characters per candidate, 4,096
candidate examinations and 128 reported findings. Tool-argument traversal also
limits depth to 16 and aggregate characters/nodes. Over-budget work is explicitly
incomplete, never silently clean. Unicode is bounded but not linguistically
classified. There is no unbounded segmentation or input-controlled regex.

## Privacy, sanitization and interception

Findings contain fixed class labels and character offsets/line/column locations,
not candidate values, hints, surrounding text or candidate hashes. Exceptions
and audit failures withhold exception text/tracebacks. This violation type never
creates a deferred allowlist snippet/hash or copies arbitrary command/context
overrides. CLI/SARIF, SDK, daemon, MCP retrieval and diagnostic/support paths use
these safe records; no new candidate retrieval API or persistent store is added.

Explicit text sanitization, including batch/trace/support sanitization, honors
trusted opt-in and replaces **every complete matched span** (including ambiguous,
repeated and overlapping spans). No password prefix/suffix is retained. Incomplete
sanitization withholds the entire text rather than leave an unexamined suffix.
This does not retroactively erase already disclosed input. Existing scanners may
still operate within their existing trusted input/staging boundary; the heuristic
does not create candidate files or change existing scanner telemetry settings.

The new PostToolUse path does **not** claim automatic safe output transformation:
it resolves Ask or requests a block for contextual candidates before the existing
pattern-redaction path. Approval and warnings must not bypass stronger credential checks.
Clean pre-tool context never skips analysis of a different tool result.

Tool-argument locations refer to string values joined by newlines in traversal
order, not JSON-escaped command text. SDK content/file/command checks and daemon
content checks use the independent stage. Static CLI scans are retrospective and
advisory, even when policy selects block. Transcript-only detection and MCP-only
advice are **not** preventive. See [host limitations](../AGENT_SUPPORT.md#password-likelihood-boundary-qualification).

### Scanner checklist decisions

The scanner/violation, shared pipeline, argument/result paths, static findings,
schema/setup/example/all profiles, existing Secrets page, help/status, SDK/daemon
and release-readiness checks are synchronized. No new engine preset, dependency,
installer/image download or dependency doctor check is needed. No new modal or
navigation page is introduced. The scanner name is registered in ignore-file
tooling/schema, but this global-only experimental stage deliberately does **not**
consume project `.aiguardignore.toml`, target allowlists or language overlays:
project data must not silently weaken the human's choice.
Broader trusted exception controls would require a separately reviewed design.
Ask extends the existing decision dialog with a private, decision-only variant;
it does not introduce another modal dispatcher or remote approval system.

## Qualification budgets (declared before results)

Run `uv run --extra dev python scripts/qualify_password_likelihood.py` in a source
checkout. It prints aggregate counts only; it does not read real user settings or
passwords, make network calls, persist candidate text, or invoke external engines.

- Frozen held-out seed, 1,000 synthetic samples per class; report class counts,
  character volumes, detection/contextual counts and incomplete analyses.
- Supported-class recall **at least 95% per class**, not just overall.
- Labeled benign false-positive budgets per class: **at most 1% advisory** and
  **at most 0.1% contextual/block-eligible**.
- Contextual precision **at least 99% in the declared balanced synthetic corpus**;
  this is prevalence-dependent, not a population precision estimate.
- 4-KiB typical-input p95 **at most 25 ms**; bounded adversarial-input worst time
  **at most 250 ms**; peak traced allocations **at most 8 MiB**. Record platform
  and Python version; no universal hardware/latency guarantee is implied.
- Fixed repository source/documentation windows are reported **unadjudicated**,
  not assumed benign. Independently labeled representative code/prose/log/config,
  identifiers, versions, UUIDs, checksums and encoded/binary-like corpora, with
  reported sizes and class-specific results, remain a **release gate**.
- Synthetic test success cannot substitute for actual model-boundary evidence.
  Keep broad passphrase recognition deferred and the v1.21.0 prevention claim
  gated until both real-corpus and applicable host-boundary evidence qualify.

### Preliminary measurements — 2026-10-28

Linux, Python 3.14.7, frozen seed `26122026`, 1,000 generated samples per
positive class (8,000 total), and six benign template classes (6,000 total):

| Synthetic class | Detections / samples |
|---|---|
| Standalone alphanumeric | 986 / 1,000, all advisory |
| Standalone mixed-symbol | 987 / 1,000, all advisory |
| Contextual alphanumeric | 986 / 1,000 |
| Contextual mixed-symbol | 1,000 / 1,000 |
| Contextual joined / CamelCase / separated / spaced | 1,000 / 1,000 **each** |
| Benign code / prose / logs / config / digest / URL templates | 0 / 1,000 **each** |

There were no incomplete synthetic analyses. Contextual precision in this
constructed dataset was 100%; **repeated templates are not 6,000 independently
sampled real-world documents**, and that result is not population precision.
The measured 4-KiB p95 was 0.94 ms, bounded adversarial worst time 15.28 ms, and
peak traced allocations 2,858,268 bytes (not total process RSS). These local
synthetic/performance checks passed their declared budgets.

The separate unadjudicated repository probe had **3 / 11 source windows** (39,131
characters) and **3 / 9 documentation windows** (32,915 characters) with advisory
findings. None were contextual/block-eligible; none were incomplete. These six
flagged windows are **not** evidence of acceptable benign false-positive rates.
They require independent adjudication and a representative held-out evaluation;
do not label the real-world quality gate passed or tune against these samples and
then call them held-out. Keep experimental status and the release/prevention
gates open. Broad context-free passphrase recognition remains deferred.

### Manual host evidence (not yet performed)

For **each claimed host/version/platform and event**:

1. Use a disposable project/account/configuration and synthetic values only;
   separately verify opt-out, warn, contextual block and ambiguous behavior.
2. Observe the actual request sent to a disposable local model/transport recorder
   (not just the hook JSON). Check prompts, Read, Write/Edit/Bash arguments and
   tool results independently. Identify which inputs were already model-visible.
3. Verify the complete original value, including repetitions/overlaps, never
   reaches the model on a claimed preventive path. A warning, transcript finding,
   generic hook denial or replacement text alone is **not sufficient evidence**.
4. Exercise scanner failures/limits, ignored host responses, missing events and
   existing credential redaction simultaneously. Unsupported transformations,
   post-consumption callbacks and observation-only events remain non-preventive.
5. Record artifact/version, host/platform, recorder method, event, observed model
   payload (redacted evidence), cancellation/failure behavior and limitations.
   No production passwords, runtime enrollment or workstation vault access.

Until that evidence exists, all real-host pre-model prevention cells for this
feature remain **unqualified**, irrespective of older scanner support ratings.
