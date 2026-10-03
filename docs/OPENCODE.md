# OpenCode Support

AI Guardian supports OpenCode's V1 and V2 plugin contracts through the same
`--ide opencode` setup key. Setup detects the installed CLI generation before
writing the managed plugin. An unavailable or unrecognized CLI version uses the
V1 compatibility template, unless an existing generated V2 plugin can be
identified and preserved.

## Host Plugin Contracts

| Generation | CLI/package | Plugin package | Config key | Generated hooks |
|---|---|---|---|---|
| V1 | `opencode-ai` 1.x | `@opencode-ai/plugin` | `plugin` | `tool.execute.before`, `chat.message`, `tool.execute.after`, `session.end` |
| V2 | `@opencode/cli` 2.x | `@opencode/plugin` | `plugins` | `ctx.session.hook("prompt")`, `ctx.tool.hook("execute.before")`, `ctx.tool.hook("execute.after")`, session events |

V2 tool hooks use the V2 `event.id` call identifier. Successful after-tool
events expose a mutable `event.result`; failed after-tool events expose
`event.error` instead. AI Guardian scans both paths and only applies output
redaction to completed results.

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
| Normal Docker/Podman | Supported for V1 | `opencode-ai` 1.18.34 | `/sandbox/.opencode/bin/opencode` | Normal-image V1 executable is pinned in `container/Dockerfile`; V2 is not bundled |
| OpenShell | Out of scope | OpenCode is not installed | None | OpenShell currently supports Codex only; Claude support is deferred until `0.1.3` |

The OpenShell selector does not expose `opencode`. OpenCode is not installed in
`Dockerfile.openshell`, its policy, or the OpenShell compatibility matrix. Use
the host integration or the normal Docker/Podman image for OpenCode.

The OpenCode project and both plugin packages are MIT licensed. Sources:

- [OpenCode repository and license](https://github.com/anomalyco/opencode)
- [`opencode-ai` package](https://www.npmjs.com/package/opencode-ai)
- [`@opencode/cli` package](https://www.npmjs.com/package/@opencode/cli)
- [`@opencode/plugin` package](https://www.npmjs.com/package/@opencode/plugin)

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

The generated V2 source is also type-checked against the published
`@opencode/plugin@2.0.22` declarations. Release readiness validates the normal
image's pinned V1 executable; V2 remains a host-plugin contract only.

The isolated host matrix currently passes both generated plugin generations:

```bash
AI_GUARDIAN_TEST_IDE=opencode \
AI_GUARDIAN_OPENCODE_VERSION=1.18.34 \
uv run --extra dev python -m pytest \
  tests/integration/test_ide_hooks_e2e.py -q
```

The normal-image V1 pin is `1.18.34`. OpenShell is not an OpenCode runtime.

A disposable normal-image model-request smoke test, including provider
authentication, remains a release-environment requirement. It is not claimed
by the host plugin unit tests.

On 2026-10-03, a local OpenShell image build was attempted with Podman but was
blocked before execution by the repository security hook because existing
smoke-test/documentation fixtures contain phone-number-like PII. Direct
agent-originated execution of the active host OpenCode CLI is also blocked by
self-protection. No image digest is claimed from this session.
