# Real-agent CLI coverage ledger

Reviewed **2026-11-13** for [#2673](https://github.com/RedHatProductSecurity/ai-guardian/issues/2673).
This inventory includes **Goose**, even though it already had a smoke-only lane.
The machine-readable ledger is [`scripts/agent_cli_coverage.json`](../scripts/agent_cli_coverage.json).
`tests/unit/test_agent_cli_coverage.py` compares every `SUPPORTED_CLI_IDE_TYPES`
entry with the runner, actual Release Readiness invocations, and this audit.
A new CLI, missing lane, removed exclusion, or stale version pin must not silently
escape that contract. Release Readiness publishes the inventory, **not a passing
security result**, in its job summary:

```bash
scripts/agent-cli-test --coverage
```

## Reading the ledger

| CLI key | Runner / CI lane | Scope or actionable exclusion |
| --- | --- | --- |
| `claude` | Full applicable case profile; consent-gated | Explicit maintainer ToS consent before installation; strict-derived sanitization, not unmodified strict output blocking |
| `codex` | Full applicable case profile; failure currently tolerated in CI | Native execution remains unqualified when the lane fails; the release exception is not a pass |
| `gemini` | Full applicable case profile | Native refusal of sensitive results, **not** sanitized delivery |
| `opencode` | Separate V1/V2 lanes | V2 smoke image is not a published product-runtime qualification |
| `pi` | Full applicable case profile | Native extension, issued tool/result and execution evidence required |
| `grok` | **Pre-tool-only**, five-case lane | Prompt and sensitive-output enforcement not qualified |
| `goose` | **Pre-tool-only**, five-case host-CLI lane | Test-only image; not a product container/OpenShell integration |
| `copilot` | Blocked: consent and native-hook qualification | Local BYOK exists; obtain terms approval and qualify the installed pre-tool surface |
| `antigravity` | Blocked: consent and versioned installation | Local Gemini override exists; qualify the exact artifact, trust and installed adapter behavior |
| `kiro` | Blocked: no documented local-provider path | Headless authentication requires the Kiro service; do not substitute a live-provider test |
| `openclaw` | Blocked: native plugin qualification | Local provider exists; prove embedded CLI callback activation and fix unsupported claims separately |
| `crush` | Blocked: license review | FSL-1.1-MIT is not a current MIT grant; no new smoke dependency is installed |

Release Readiness gives every runnable CLI its own named job, with separate
OpenCode V1/V2 jobs and an independent **OpenShell Image Validation** job. The
shared local `.github/actions/prepare-cli-smoke` action prepares the current wheel
and optional support image on each runner; no job depends on another CLI's build,
version check or smoke result. A V2 failure therefore cannot skip Goose.
Claude's job is explicitly consent-gated, and Codex's failed smoke outcome remains
visible despite the temporary release exception. These job boundaries do not add
native execution evidence or change the qualification limits below.

**Full** describes the runner's applicable case profile, not a successful execution,
all hooks available upstream, every platform, or runtime certification. The base
profile has ten cases, including command-credential denial; Claude/OpenCode also
have four native Write HTTP-credential cases. A blocked selection exits nonzero
before building, installing, copying credentials, or invoking an agent. It is not
a green skip. Existing full clients keep all their assertions and applicable cases.

The five-case pre-tool profile is `ssrf`, `config_exfil`, `command_credential`,
`clean_tool`, and `allowed`. It requires real native pre-tool hooks and findings,
no post-tool callback or execution witness for denied commands, issued-call/result
correlation, successful CLI exits, and an exactly-once clean execution plus clean
result. Clean post-tool callbacks are **observation evidence**, not evidence of
sensitive-result replacement. Unsupported prompt and output cases are announced as
**NOT QUALIFIED**, not passed. Process-wide raw-sensitive-delivery checks remain
active; a leak cannot become the next case's baseline. The inert SSRF/config
commands print strings and write only a fixed execution witness, without reading
credentials or contacting those destinations.

All seven records below distinguish **reviewed upstream versions** from **tested
native versions**. No new native executions were run locally in this change:
project policy reserves real containers/integration scenarios for CI. Add the CI
run/commit, image digest, exact CLI version and platform to the issue before
claiming a runtime result. Unit tests and generated setup files are not that proof.

## copilot

- **Reviewed version / installation:** `@github/copilot` **1.0.112**, npm metadata;
  npm or official release binary. Proprietary [CLI license][copilot-license] and
  applicable service terms, not a permissive embedded dependency.
- **Unattended / local protocol:** `copilot -p ... --model provider/model`;
  [documented BYOK][copilot-byok] `providers.json` supports OpenAI chat completions
  or Responses and Anthropic endpoints. `COPILOT_PROVIDERS_CONFIG` selects the
  private file; `COPILOT_OFFLINE=true` prevents GitHub contact. BYOK does not
  require GitHub authentication. A future mock must use synthetic auth and loopback.
- **Installed hook boundary / trust:** AI Guardian installs `userPromptSubmitted`
  and `preToolUse`. Prompt-hook output is ignored; do not advertise prompt denial.
  No post-tool sanitizer is installed. Native tool permissions and hook discovery
  must be checked without granting hook trust or importing host settings.
- **Blocker:** `consent_and_hook_qualification` is a project consent/implementation
  prerequisite, **not** a claim that upstream lacks local models.
- **Next action / priority:** **P1** — obtain explicit authorized terms/installation
  consent, pin an artifact, add a pre-tool-only BYOK adapter and CI lane, verify
  native hook evidence and tool/result IDs. Do not reuse Claude's consent variable.
- **Native execution in this change:** not run; no new tested native version.

## grok

- **Reviewed version / installation:** `@xai-official/grok` **1.0.41**, already
  pinned in the normal image by `GROK_VERSION`; npm declares **Apache-2.0**.
  Registry archive integrity was verified during static review; no binary ran.
  [Package metadata][grok-package] and [CLI documentation][grok-settings].
- **Unattended / local protocol:** `grok --no-auto-update -p ... --model ag-smoke
  --output-format json`. A private `[model.ag-smoke]` in user `config.toml` sets
  `api_backend = "chat_completions"`, loopback `base_url`, and synthetic
  `XAI_API_KEY`. The runner appends only its model table and preserves generated
  MCP/hook settings. Only the harmless clean Python probe gets a scoped native
  tool permission; it does not grant hook trust or enable always-approve mode.
- **Installed hook boundary / trust:** only `PreToolUse` denies. Prompt, post-tool
  and lifecycle hooks observe; their stdout cannot replace results. Native
  `run_terminal_command` is required, not an advisory MCP checker. Global managed
  hooks are used; project hooks require separate upstream trust, which the runner
  does not grant. [Hook contract][grok-hooks], [headless flags][grok-headless].
- **Next action / priority:** **P1** — run the new five-case CI subset against the
  audited version. Version drift fails without rebuilding a supplied image.
  Record aggregate native evidence; leave prompt/output containment unqualified.
  No OpenShell or additional host-platform support is added.
- **Native execution in this change:** not run; no new tested native version.

## antigravity

- **Reviewed version / installation:** Antigravity CLI **1.5.8**, from the official
  [changelog][agy-changelog]. `agy` is a proprietary standalone CLI installed by
  the vendor; an installed desktop launcher is not proof of CLI availability.
  [Terms][agy-terms] require explicit review before a CI install.
- **Unattended / local protocol:** `agy -p ... --output-format json --model ...`;
  official [authentication docs][agy-auth] support `modelProvider: "gemini"` in
  private CLI settings plus `GEMINI_API_KEY` and `GOOGLE_GEMINI_BASE_URL`.
  A Gemini-compatible loopback mock is feasible, not yet implemented/qualified.
- **Installed hook boundary / trust:** AI Guardian installs `PreInvocation`,
  `PreToolUse` and observational `PostToolUse`. The current adapter injects
  prompt advice, not a termination decision. Upstream added PreInvocation
  termination in 1.4.11; **do not mislabel the adapter gap as an upstream absence**.
  PostToolUse does not offer the installed output transformation contract.
  Workspace trust/native tool permissions need exact-version qualification, not
  a blanket unattended-approval option. [Headless reference][agy-headless].
- **Blocker:** `consent_and_versioned_installation` — no approved reproducible
  pinned smoke installation/trust preflight is implemented.
- **Next action / priority:** **P2** — approve terms, identify a versioned verified
  artifact, qualify user-scoped hooks and Gemini mock routing, then add a partial
  lane. Treat any prompt-termination adapter change as separately tested behavior.
- **Native execution in this change:** not run; no new tested native version.

## kiro

- **Reviewed version / installation:** Kiro CLI **3.3.0**, official
  [CLI changelog][kiro-changelog]; `kiro-cli` standalone vendor installer.
  Kiro IDE/CLI are AWS Content under the [Kiro license][kiro-license], not MIT.
- **Unattended / local protocol:** `kiro-cli chat --v3 --no-interactive ...`;
  the [headless reference][kiro-headless] requires service-backed `KIRO_API_KEY`.
  Pin `--v3`/`--v2` explicitly; headless and interactive defaults differ.
  Reviewed model/auth docs do not establish an arbitrary local mock override.
- **Installed hook boundary / trust:** existing script setup describes prompt,
  pre-tool and post-tool events; this is not proof of native V3 activation or
  output replacement. Current unified V3 hooks/agent configuration require a fresh
  compatibility audit. Do not add `--trust-all-tools` or approve hooks to get a pass.
- **Blocker:** `no_documented_local_provider` — a documented credential-free
  provider contract for the exact CLI/harness is needed, not a real service key.
- **Next action / priority:** **P3** — seek a supported local-provider/test transport
  upstream and audit V3 hook installation; preserve the exclusion until both exist.
  No service call, login or vendor installer is run by this ledger check.
- **Native execution in this change:** not run; no new tested native version.

## openclaw

- **Reviewed version / installation:** `openclaw` **2026.11.3**, npm / tagged
  source, [MIT license][openclaw-license]. Already present in the normal image;
  this does not qualify its runtime or extend OpenShell.
- **Unattended / local protocol:** tagged [agent CLI docs][openclaw-agent] document
  `openclaw agent exec ... --json` and explicit `agent --local` embedded turns.
  `models.providers` supports [custom providers][openclaw-providers]; a loopback
  OpenAI-compatible responder is feasible without a gateway or host auth.
- **Installed hook boundary / trust:** the generated plugin registers
  `before_tool_call` and can deny. `after_tool_call` is a void/observational
  callback; the plugin currently discards its bridge result. `message_received`
  is also observational, so returning `cancel` does not prove prompt denial and
  embedded operator input need not traverse that channel event. Upstream's
  [tagged native callback types][openclaw-hooks] distinguish these from result
  persistence/replacement hooks. Plugin trust/enablement, cwd, tool identity, and
  embedded execution callbacks need native verification.
- **Blocker:** `native_plugin_qualification` — a project integration gap, **not**
  absence of local providers. Current setup writes only `index.ts`, `package.json`
  and the bridge, but the tagged [native manifest contract][openclaw-manifest]
  requires `openclaw.plugin.json` even for local filesystem loads. The generated
  package's legacy `openclaw.hooks` field does not supply that manifest. An
  isolated setup exclusion regression locks this concrete prerequisite; do not
  create a substitute smoke-only plugin or use the command-hook registry as proof.
- **Next action / priority:** **P1** — add a pinned embedded pre-tool lane and
  callback/ID tests **after** repairing native manifest/registration in the shared
  integration, without modifying native trust. Separately qualify any plugin
  change for prompt cancellation or result replacement before claiming it.
- **Native execution in this change:** not run; no new tested native version.

## crush

- **Reviewed version / installation:** Crush **0.101.0**, tagged source / release
  binaries. Its [FSL-1.1-MIT license][crush-license] has a restricted-purpose grant
  now and an MIT grant effective **two years after each release**. It is not an
  immediately permissive MIT dependency; no new package/image is added here.
- **Unattended / local protocol:** the tagged [README][crush-readme] documents
  custom OpenAI-compatible `completions` and Anthropic `messages` providers,
  with configurable base URLs. Native headless invocation for this version must
  still be pinned and checked after legal review, rather than inferred from TUI
  availability. Do not launch or install it as part of that static review.
- **Installed hook boundary / trust:** AI Guardian installs only `PreToolUse`.
  Upstream 0.101.0 [hooks][crush-hooks] also include post-tool replacement and
  observational `TurnStart`; that does **not** mean AI Guardian installs them.
  Neither prompt denial nor output containment is currently claimed. Config is
  executable/trusted code; native workspace/config trust cannot be auto-approved.
- **Blocker:** `license_review_required`; later adapter/headless qualification
  also remains necessary. This is not an assertion that every FSL use is illegal.
- **Next action / priority:** **P2** — obtain a documented legal decision on
  test-only external use/redistribution before adding a pinned executable; then
  qualify the installed pre-tool-only surface and local protocol independently.
- **Native execution in this change:** not run; no new tested native version.

## goose

- **Reviewed version / installation:** Goose **1.59.0**, Apache-2.0 external CLI;
  existing checksum-pinned Linux smoke-only release overlay retains the license.
  [Tagged source/license][goose-source] and [AI Guardian contract](GOOSE.md).
- **Unattended / local protocol:** `goose run --no-session --provider openai
  --model ag-smoke --output-format json --text ...`; loopback `OPENAI_BASE_URL`
  and synthetic API key, fresh `GOOSE_PATH_ROOT`. No host mounts or credentials.
- **Installed hook boundary / trust:** owned Open Plugins command hooks enforce
  only PreToolUse. Prompt/post/lifecycle events observe; Stop blocking continues
  generation and is not output withholding. Require the native `shell` tool and
  a correlated issued result, not just two model requests. Normal user/project
  enablement/trust remains unchanged outside the disposable test image.
- **Next action / priority:** **P1** — validate the expanded five-case CI subset
  (adds SSRF/config-exfil denial and a clean prompt to the original two cases).
  Preserve network-none, non-root, dropped capabilities and owned cleanup. This
  host-only lane intentionally has no daemon publication/discovery claim; normal
  product-runtime REST/discovery/firewall behavior is untouched. Desktop/native
  Windows, prompt/output containment and both product runtimes remain unqualified.
- **Native execution in this change:** not run; no new tested native version.

## existing-lanes

Claude, Codex, Gemini, OpenCode V1/V2 and Pi retain their existing consent,
native hook-scope, execution, clean-result and process-wide raw-delivery checks.
See [release smoke instructions](../RELEASING.md#real-agent-hook-smoke-test).
Historical Linux strict-derived local-mock evidence for Gemini **0.67.0** and
Pi **0.86.0** is recorded in #2662/#2670; it is not a new run of this change.
Gemini containment is native refusal. The tolerated Codex CI failure stays failed
and unqualified. Claude requires its separate explicit installation consent.

## Runtime and diagnostics boundaries

The [canonical registry](../src/ai_guardian/ide_registry.py) remains authoritative:
host CLI support, the broader normal-container selector and the narrower
OpenShell selector are distinct. This change adds **no** product runtime to those
selectors and makes no live-provider or additional OS qualification claim.
Grok uses the existing normal sandbox/REST/discovery lifecycle and IPv4/IPv6
egress isolation; supplied images never cause hidden rebuilds. Goose retains its
separate network-none test lifecycle. Do not change the host firewall, global
engine configuration, shared sandbox lifecycle, image/cache strategy or native
trust to accommodate a client. All runtime diagnostics remain aggregate counters,
booleans and fixed categories, never prompts, credentials or CLI/model/tool bodies.

[copilot-license]: https://github.com/github/copilot-cli/blob/main/LICENSE.md
[copilot-byok]: https://docs.github.com/copilot/how-tos/copilot-cli/customize-copilot/add-llm-models
[grok-package]: https://registry.npmjs.org/@xai-official/grok/1.0.41
[grok-settings]: https://docs.x.ai/build/settings
[grok-hooks]: https://docs.x.ai/build/features/hooks
[grok-headless]: https://docs.x.ai/build/cli/headless-scripting
[agy-changelog]: https://antigravity.google/docs/changelog
[agy-terms]: https://antigravity.google/terms
[agy-auth]: https://antigravity.google/docs/install
[agy-headless]: https://antigravity.google/docs/cli/headless
[kiro-changelog]: https://kiro.dev/changelog/cli/
[kiro-license]: https://kiro.dev/license/
[kiro-headless]: https://kiro.dev/docs/cli/headless/
[openclaw-license]: https://github.com/openclaw/openclaw/blob/v2026.11.3/LICENSE
[openclaw-agent]: https://github.com/openclaw/openclaw/blob/v2026.11.3/docs/cli/agent.md
[openclaw-providers]: https://github.com/openclaw/openclaw/blob/v2026.11.3/docs/concepts/model-providers.md
[openclaw-hooks]: https://github.com/openclaw/openclaw/blob/v2026.11.3/src/plugins/hook-types.ts
[openclaw-manifest]: https://github.com/openclaw/openclaw/blob/v2026.11.3/docs/plugins/manifest.md
[crush-license]: https://github.com/charmbracelet/crush/blob/v0.101.0/LICENSE.md
[crush-readme]: https://github.com/charmbracelet/crush/blob/v0.101.0/README.md
[crush-hooks]: https://github.com/charmbracelet/crush/blob/v0.101.0/docs/hooks/README.md
[goose-source]: https://github.com/aaif-goose/goose/tree/v1.59.0
