# OpenCode Support

AI Guardian supports OpenCode's V1 and V2 plugin contracts through the same
`--ide opencode` setup key. Setup detects the installed CLI generation before
writing the managed plugin. An unavailable or unrecognized CLI version uses the
V1 compatibility template, unless an existing generated V2 plugin can be
identified and preserved.

`ai-guardian setup --ide opencode`, `ai-guardian doctor`, and the Console health
check all use the same runtime resolver. It runs the active `opencode --version`
command; users do not need to set an AI Guardian environment variable. If V1 and
V2 are both installed under different executable names, the version resolved as
`opencode` first on `PATH` is the active target for that invocation.

## Host Plugin Contracts

| Generation | CLI/package | Local plugin loading | Config key | Generated hooks |
|---|---|---|---|---|
| V1 | `opencode-ai` 1.x | `@opencode-ai/plugin` import | `plugin` | `tool.execute.before`, `chat.message`, `tool.execute.after`, `session.end` |
| V2 | `@opencode/cli` 2.x | Local auto-discovery; direct `{ id, setup }` export | None for this local plugin | `ctx.session.hook("prompt")`, `ctx.tool.hook("execute.before")`, `ctx.tool.hook("execute.after")`, session events |

The V1 plugin replaces every blocked prompt part with one fixed synthetic
refusal notice, retaining only the required part/session/message identifiers.
This avoids an empty turn, removes original text and attachments before model
submission, and lets a safe follow-up remain in the same session. V1 cannot skip
the assistant turn, so OpenCode may process the fixed notice and produce a brief
response; the toast explains the substitution.

The issue reporter confirmed the affected generation is V2 (2.x); the exact patch
version and OS are still unknown. In the previous V2 handler, a block added a
synthetic notice and threw from prompt admission. V2's admission hook has no typed
denial result, so this failed-admission path is consistent with the reported
first-prompt session switch, but still needs live-host confirmation. The generated
V2 plugin now replaces the mutable prompt draft with the fixed refusal notice,
clears file attachments, agent mentions, and skills, and lets the safe input be
admitted into the requested session. The original prompt data is not persisted or
sent to the model. V2 may run the model on the fixed notice and produce a generic
response; it no longer adds a duplicate synthetic entry or rejects admission.

The V2 plugin deliberately omits the documented `@opencode/plugin` import.
OpenCode V2 server builds have been reported to fail resolving that scoped
package from local plugin files, while accepting a plain default-exported
`{ id, setup }` object. The file is loaded from the global `plugins` directory;
the `plugins` config key is for package or plugin-directory entries, not this
single TypeScript file. Setup removes an old explicit AI Guardian file entry
and preserves compatible unrelated configured plugins. If another local
TypeScript file entry is present, setup leaves the configuration unchanged and
asks the user to migrate that entry explicitly before retrying.

V2 tool hooks use the V2 `event.id` call identifier. Successful after-tool
events expose a mutable `event.result`; failed after-tool events expose
`event.error` instead. AI Guardian scans both paths and only applies output
redaction to completed results.

V2 lifecycle events carry the stable session ID in `event.data.sessionID`.
`session.idle` ends a turn and forwards `Stop`; it does not remove the active
session or clear a session-scoped pause. `session.deleted` forwards `SessionEnd`
and clears that session's daemon registration and pause. Unloading the plugin
only closes its event subscription; it does not delete persistent sessions.

V2 prompt, tool, and idle hooks also forward the native title obtained from
`ctx.session.get({ sessionID })` as optional `session_title` display metadata.
Lookup is bounded to 500 ms and cached for 30 seconds per exact session (including
misses, at most 128 entries). Later activity refreshes generated/renamed titles.
Unavailable or invalid metadata never skips hook checks: the tray retains a known
title or uses the stable ID fallback. Deletion clears the cached entry. No
messages or full transcripts are loaded to obtain a title.

Blocked pre-tool calls add a fixed notice saying the tool did not run. Blocked
post-tool results add a notice saying the tool ran but its result was withheld;
the tool's side effects cannot be undone. Both notices avoid tool arguments and
result contents. OpenCode receives a fixed tool error immediately, and the
synthetic transcript notice is available as context on the next model turn.

When the V2 prompt hook blocks a prompt, it replaces the prompt draft with a
fixed AI Guardian refusal notice and clears file attachments, agent mentions,
and selected skills. This avoids a failed admission and keeps the safe turn in
the requested session; the original prompt and detection details are not admitted.
V2 does not expose a typed prompt-denial result, so the model may run on the fixed
notice and produce a generic response. The notice is the admitted user input, not
a separate synthetic transcript entry.

The shared bridge remains outside the direct plugin discovery directory:

```text
<OpenCode config directory>/
├── plugins/ai-guardian.ts
└── ai-guardian/ai-guardian-bridge.ts
```

The bridge invokes `ai-guardian --ide opencode` with a 30-second timeout and
keeps the host plugin free of duplicated process and response handling.

## Database And Paths

| Purpose | V1 | V2 |
|---|---|---|
| Config file | `OPENCODE_CONFIG`, then `OPENCODE_CONFIG_DIR` | Same |
| Plugin directory | Adjacent `<config-dir>/plugins` | Same |
| Transcript database | `OPENCODE_HOME/opencode.db` or `~/.local/share/opencode/opencode.db` | `OPENCODE_DB`, then `opencode debug paths db`, then the V1 fallback |

`OPENCODE_DB=:memory:` disables local database discovery. Explicit database
paths are accepted only when the file exists.

## Runtime Support Record

The host plugin integration and the container CLI runtime are separate support
surfaces.

| Runtime | Status | Version/package | Executable or location | Evidence and limitation |
|---|---|---|---|---|
| Host setup | Supported | V1 and V2 contracts | User OpenCode config directory | Version-aware unit, setup, session, transcript, and isolated structural tests |
| Normal Docker/Podman | Supported for V1 | `opencode-ai` 1.19.0 | `/sandbox/.opencode/bin/opencode` | Normal-image V1 executable is pinned in `container/Dockerfile`; V2 is not bundled |
| OpenShell | Supported for V1 Vertex auth | `opencode` 1.19.0 | `/usr/local/bin/opencode` | OpenShell image includes V1; native Vertex/ADC uses the `google-cloud` provider and metadata emulator; live model qualification is manual |

The OpenShell selector exposes OpenCode with an explicit agent profile. For the
Vertex path, use the `claude` agent profile and a native
`google-vertex/<model>` model ID. OpenCode V2 is not bundled in the
dedicated image. See the [sandbox recipes](Sandbox.md) and the
[manual qualification matrix](../container/tests/README.md).

The OpenCode project and V1 plugin package are MIT licensed. Sources:

- [OpenCode repository and license](https://github.com/anomalyco/opencode)
- [`opencode-ai` package](https://www.npmjs.com/package/opencode-ai)
- [`@opencode/cli` package](https://www.npmjs.com/package/@opencode/cli)
- [OpenCode issue: local V2 plugin resolver cannot load `@opencode/plugin`](https://github.com/anomalyco/opencode/issues/50434)

Account access, provider credentials, service terms, and model availability
remain the responsibility of the user and are not bundled into either image.

## Normal Image Case

The normal image includes the pinned V1 executable. It can be selected through
the regular container runner:

```bash
./container/run.sh --agent opencode
```

The container and host integrations are Linux-tested. Host setup follows
platform-specific config/path handling, but macOS and Windows OpenCode runtime
qualification is not claimed here.

## Validation Evidence

The directly affected local validation command is:

```bash
uv run --extra dev python -m pytest \
  tests/unit/test_opencode_support.py \
  tests/unit/test_opencode_transcript.py \
  tests/unit/test_ide_sessions.py \
  tests/unit/test_cli_version_check.py \
  tests/unit/test_ide_registry.py \
  tests/unit/test_setup.py \
  tests/unit/test_container_scripts.py \
  tests/ux/test_user_experience_contract_opencode_self_protection.py -q
```

Release readiness validates the normal image's pinned V1 executable; V2 remains
a host-plugin contract only. V2 doctor status confirms generated files and
discovery-path configuration, but does not inspect whether a running OpenCode
server successfully activated the plugin.

The isolated host matrix currently passes both generated plugin generations. The
version variable below is a test-only override used to exercise both contracts;
normal users leave it unset:

```bash
AI_GUARDIAN_TEST_IDE=opencode \
AI_GUARDIAN_OPENCODE_VERSION=1.19.0 \
uv run --extra dev python -m pytest \
  tests/integration/test_ide_hooks_e2e.py -q
```

Both support images pin OpenCode V1 to `1.19.0`. Live OpenShell Vertex model
qualification remains manual.

A disposable normal-image model-request smoke test, including provider
authentication, remains a release-environment requirement. It is not claimed
by the host plugin unit tests.

On 2026-10-03, a local OpenShell image build was attempted with Podman but was
blocked before execution by the repository security hook because existing
smoke-test/documentation fixtures contain phone-number-like PII. Direct
agent-originated execution of the active host OpenCode CLI is also blocked by
self-protection. No image digest is claimed from this session.
