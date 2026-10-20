# Sandbox CLI

Use the recipe that matches your runtime and authentication method. The quick
recipes below are the supported first-time setup paths. The reference sections
at the end cover lifecycle commands and less common options.

## Choose a case

| Case | Runtime | Authentication | Start here |
| --- | --- | --- | --- |
| 1 | Docker/Podman | Codex OAuth | [Container OAuth](#case-1--dockerpodman--codex-oauth) |
| 2 | Docker/Podman | Codex API key | [Container API key](#case-2--dockerpodman--codex-api-key) |
| 3 | OpenShell | Codex OAuth | [OpenShell OAuth](#case-3--openshell--codex-oauth) |
| 4 | OpenShell | Codex API key | [OpenShell API key](#case-4--openshell--codex-api-key) |
| 5 | OpenShell | Claude Code + Vertex AI | [Claude/Vertex](#case-5--openshell--claude-code--vertex-ai) |
| 6 | OpenShell | OpenCode `claude` agent + Vertex AI | [OpenCode/Vertex](#case-6--openshell--opencode-claude-agent--vertex-ai) |
| 7 | Tray | Either runtime | [Tray](#case-7--tray-create-sandbox) |

All recipes assume that `ai-guardian` is installed and that you run the
commands from the repository you want to protect:

```bash
ai-guardian --version
```

`--repo .` uploads the repository to OpenShell and mounts it into a
Docker/Podman sandbox. Replace `guardian-codex` with any unused sandbox name.

## Codex authentication in container sandboxes

Container sandboxes keep the host's Codex directory isolated. Complete the
login inside the named sandbox.

### Case 1 — Docker/Podman + Codex OAuth

**Prerequisites**

- Docker or Podman is installed.
- The normal AI Guardian image is available; the command pulls it if needed.
- A browser or device-code login is available for Codex.

**Steps**

1. Create the sandbox:

   ```bash
   ai-guardian sandbox create \
       --runtime container \
       --name guardian-codex \
       --cli codex \
       --repo .
   ```

2. Connect to it:

   ```bash
   ai-guardian sandbox connect guardian-codex
   ```

3. Run inside the sandbox:

   ```bash
   codex login
   codex
   ```

For a headless container, use `codex login --device-auth` when device login is
enabled for the ChatGPT account. Exit the shell with `Ctrl-D`; the named
sandbox remains available.

### Case 2 — Docker/Podman + Codex API key

**Prerequisites**

- Docker or Podman is installed.
- An OpenAI Platform API key is available. A ChatGPT OAuth token is not an API
  key.

**Steps**

1. Export the key without putting it in the sandbox command line:

   ```bash
   read -rsp "OpenAI API key: " OPENAI_API_KEY
   echo
   export OPENAI_API_KEY
   ```

2. Create and connect to the sandbox:

   ```bash
   ai-guardian sandbox create \
       --runtime container \
       --name guardian-codex \
       --cli codex \
       --repo .
   ai-guardian sandbox connect guardian-codex
   ```

3. Run inside the sandbox:

   ```bash
   printenv OPENAI_API_KEY | codex login --with-api-key
   codex
   ```

The key is passed to the container because it is present in the environment
when the sandbox is created. Do not commit it or copy it into the repository.

## OpenShell provider setup

Complete this once for each OpenShell gateway. It is required for Cases 3–6.

### Prerequisites

- OpenShell CLI and gateway `0.1.3` or a later `0.1.x` patch release. AI Guardian
  does not qualify `0.1.2` or earlier, or other minor lines.
- A configured OpenShell compute driver.
- Rootless Podman users on Linux must have the Podman socket enabled.

### Step 1 — Install and check the local gateway

Use the pinned release below for the documented AI Guardian path:

```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh \
    | OPENSHELL_VERSION=v0.1.3 sh
hash -r
openshell --version
openshell status
```

`openshell status` must show a connected gateway. On Linux with rootless
Podman, run:

```bash
systemctl --user enable --now podman.socket
systemctl --user restart openshell-gateway
openshell status
```

On macOS, use the Homebrew service:

```bash
brew services restart openshell
openshell status
```

### Step 2 — Import the Codex profiles

```bash
curl -fsSL \
    https://raw.githubusercontent.com/NVIDIA/OpenShell/v0.1.3/providers/codex.yaml \
    -o /tmp/openshell-codex.yaml
curl -fsSL \
    https://raw.githubusercontent.com/NVIDIA/OpenShell/v0.1.3/providers/openai.yaml \
    -o /tmp/openshell-openai.yaml

openshell provider profile import \
    --file /tmp/openshell-codex.yaml --global
openshell provider profile import \
    --file /tmp/openshell-openai.yaml --global
openshell provider list-profiles
```

The expected profiles are `codex` and `openai`. If import says a profile
already exists, continue; it is already installed.

### Additional profile for Vertex AI cases

For Claude Code/Vertex and OpenCode/Vertex, also import the endpointless
`google-cloud` profile. OpenShell 0.1.3 or later provides the supervisor-backed
metadata emulator required for native Google Application Default Credentials:

```bash
curl -fsSL \
    https://raw.githubusercontent.com/NVIDIA/OpenShell/v0.1.3/providers/google-cloud.yaml \
    -o /tmp/openshell-google-cloud.yaml
openshell provider profile import \
    --file /tmp/openshell-google-cloud.yaml --global
```

On the host that runs AI Guardian, configure gateway bootstrap credentials once
with `gcloud auth application-default login`, then provide a non-secret project
ID and Vertex region when creating a sandbox. AI Guardian creates or reuses the
`ai-guardian-google-cloud` provider from host ADC when it does not exist;
OpenShell retains the refresh material at the gateway and the workload receives
only an opaque token placeholder through `GCE_METADATA_HOST=127.0.0.1:8174`.
Do not upload or mount the host ADC file, and do not pass token or refresh values
with `--env`. An existing `--provider NAME` may be used instead if it has type
`google-cloud`.

### Step 3 — Use the v0.1.3 provider profiles

OpenShell v0.1.3 does not expose the legacy `providers_v2_enabled` setting;
there is no gateway setting to enable for the qualified baseline. That setting
was specific to OpenShell v0.1.2, which is below AI Guardian's supported range.

The profiles (`codex` and `openai`) are provider types. AI Guardian creates or
reuses the gateway provider instances `ai-guardian-codex` and
`ai-guardian-openai` as needed.

### Optional — create a provider manually

Manual provider creation is not normally required. If the tray process can
access the local Codex OAuth state or `OPENAI_API_KEY`, its Create sandbox form
automatically creates or reuses the matching provider. The CLI does the same
when using `--openshell-auth oauth` or `--openshell-auth api-key`.

Use the manual flow only when the tray cannot receive the credential
environment, or when you want to attach an existing provider with
`--provider`:

```bash
# OAuth: complete `codex login` first.
openshell provider create \
    --name ai-guardian-codex \
    --type codex \
    --from-existing

# API key: make OPENAI_API_KEY available to this command first.
openshell provider create \
    --name ai-guardian-openai \
    --type openai \
    --credential OPENAI_API_KEY

openshell provider list
```

Then pass the instance name to the CLI:

```bash
ai-guardian sandbox create \
    --runtime openshell \
    --provider ai-guardian-codex \
    --repo .
```

Use `ai-guardian-openai` instead when attaching the API-key provider.

For an explicitly selected OAuth provider, also supply
`--env 'CODEX_ACCOUNT_ID=<matching-account-id>'` with that provider's literal
account/workspace identifier. This is non-bearer identity metadata, not an OAuth
token. AI Guardian does not guess the identity from an unrelated local login or
read credentials back from the selected gateway provider. Missing or placeholder
identity metadata stops OAuth bootstrap; do not upload host authentication files.

## Case 3 — OpenShell + Codex OAuth

**Prerequisites**

- Complete [OpenShell provider setup](#openshell-provider-setup).
- Install the Codex CLI on the host and verify `codex --version`.
- Complete the host OAuth login:

  ```bash
  codex login
  ```

**Steps**

1. Create the sandbox:

   ```bash
   ai-guardian sandbox create \
       --runtime openshell \
       --name guardian-codex \
       --cli codex \
       --openshell-auth oauth \
       --repo .
   ```

2. The command opens a shell after setup. Run Codex inside it:

   ```bash
   codex
   ```

3. After exiting the shell, check the sandbox:

   ```bash
   ai-guardian sandbox status guardian-codex
   ```

The OAuth credentials remain in the OpenShell gateway. They are not uploaded
to the sandbox. AI Guardian supplies the account/workspace identifier separately
as `CODEX_ACCOUNT_ID` from the same local credential snapshot used to create or
refresh the managed provider. Codex needs this literal, non-bearer identifier for
local workspace-routing comparisons; access/refresh tokens remain opaque
OpenShell placeholders, and the local ID token remains synthetic. Treat account
identifiers as private metadata: do not publish auth files or account responses.

This follows the identity separation in
[OpenShell PR #4215](https://github.com/NVIDIA/OpenShell/pull/4215). It requires the
updated AI Guardian creator **and a rebuilt support image** containing the updated
entrypoint; existing images/sandboxes are not retrofitted. A missing or placeholder
identity, or an override conflicting with the managed provider's local identity,
fails before provider mutation or Codex startup rather than changing auth modes.
API-key authentication does not require this identity metadata.

The Codex image pin remains `0.160.0`. This compatibility fix does not qualify a
new CLI version: repeat operator startup, private account/workspace selection,
and actual provider-boundary middleware-denial checks before advancing it.

## Case 4 — OpenShell + Codex API key

**Prerequisites**

- Complete [OpenShell provider setup](#openshell-provider-setup).
- An OpenAI Platform API key is available. A ChatGPT OAuth token is not an API
  key.

**Steps**

1. Export the key in the shell that launches AI Guardian:

   ```bash
   read -rsp "OpenAI API key: " OPENAI_API_KEY
   echo
   export OPENAI_API_KEY
   ```

2. Create the sandbox:

   ```bash
   ai-guardian sandbox create \
       --runtime openshell \
       --name guardian-codex \
       --cli codex \
       --openshell-auth api-key \
       --repo .
   ```

3. The command opens a shell after setup. Run Codex inside it:

   ```bash
   codex
   ```

4. After exiting the shell, check the sandbox:

   ```bash
   ai-guardian sandbox status guardian-codex
   ```

AI Guardian creates or reuses `ai-guardian-openai`; the real key stays in the
gateway and is represented inside the sandbox by an opaque placeholder.

## Case 5 — OpenShell + Claude Code + Vertex AI

**Prerequisites**

- Complete [OpenShell provider setup](#openshell-provider-setup), including the
  `google-cloud` profile.
- Run `gcloud auth application-default login` on the host running AI Guardian.
- Have a Vertex-enabled project, model access, and the Vertex AI User IAM role.
- Accept Claude Code's Terms of Service. The OpenShell image installs Claude
  Code at runtime only after explicit consent.

**Steps**

1. Create the sandbox with non-secret project and region settings:

   ```bash
   ai-guardian sandbox create \
       --runtime openshell \
       --name guardian-claude-vertex \
       --cli claude \
       --env ANTHROPIC_VERTEX_PROJECT_ID=PROJECT_ID \
       --env CLOUD_ML_REGION=us-east5 \
       --env ACCEPT_PROPRIETARY_TOS=true \
       --repo .
   ```

2. The explicit `ACCEPT_PROPRIETARY_TOS=true` setting acknowledges Claude
   Code's Terms of Service for the non-interactive sandbox bootstrap. Start
   Claude Code in Vertex mode and select a model available to your project:

   ```bash
   claude --bare
   ```

When creating the managed OpenShell sandbox from the tray, select **Claude**
and check **I accept Anthropic's Claude Code Terms of Service** after reviewing
the linked terms. This checkbox is required to continue with Claude selected.
The tray passes consent only when checked; without it, non-interactive startup
skips the runtime installation.

The sandbox sets `CLAUDE_CODE_USE_VERTEX=1` and binds regional and replicated
Vertex endpoints to the gateway-owned Google Cloud provider. ADC files and
refresh material stay out of the sandbox.

## Case 6 — OpenShell + OpenCode `claude` agent + Vertex AI

**Prerequisites**

- Complete [OpenShell provider setup](#openshell-provider-setup), including the
  `google-cloud` profile.
- Run `gcloud auth application-default login` on the host running AI Guardian.
- Have a Vertex-enabled project, access to a Claude model, and the Vertex AI User
  IAM role.

**Steps**

1. Create the sandbox with the OpenCode `claude` agent profile:

   ```bash
   ai-guardian sandbox create \
       --runtime openshell \
       --name guardian-opencode-vertex \
       --cli opencode \
       --opencode-agent-profile claude \
       --env GOOGLE_CLOUD_PROJECT=PROJECT_ID \
       --env VERTEX_LOCATION=global \
       --repo .
   ```

2. Select a Vertex-hosted Claude model and run it natively:

   ```bash
   opencode run --agent claude \
       --model google-vertex/MODEL_ID \
       "hello"
   ```

The gateway-owned provider supplies ADC through the metadata emulator; OpenCode
uses Vertex's native endpoint and request format. No ADC file or GCP token is
uploaded to the workload.

## Case 7 — Tray Create sandbox

**Prerequisites**

- The tray is running.
- For Container, Docker/Podman is installed.
- For OpenShell **AI Guardian hooks**, complete [OpenShell provider setup](#openshell-provider-setup).
- For OpenShell **AI Guardian hooks** with OAuth, run `codex login` in the
  environment used by the tray.
- For OpenShell **AI Guardian hooks** with an API key, either start the tray with `OPENAI_API_KEY` available,
  or create `ai-guardian-openai` in the gateway first and enter that name in
  **OpenShell provider override**.
- Native OpenShell mode uses OpenShell's own workload/provider defaults and does
  not require the AI Guardian provider setup above.

**Steps**

1. Open the tray menu and select **Create sandbox...**.
2. Select **Runtime**: `container` or `openshell`.
3. For OpenShell, select **OpenShell sandbox mode**: **AI Guardian hooks** or
   **Native OpenShell**. The native path leaves workload setup to OpenShell.
4. Select **CLI**: `codex`, `claude`, or `opencode`. For OpenCode, select the
   `claude` agent profile to use the Vertex route.
5. For OpenShell **AI Guardian hooks**, Codex authentication offers **OAuth** or
   **API key**. For Claude/Vertex or OpenCode/Vertex, expose the non-secret
   project and region variables to the tray process before creating the sandbox.
   Native OpenShell leaves workload setup to OpenShell.
6. Choose one **Initial config** source: **Host/default**, **Profile**, **Host
   config directory**, or **Latest saved snapshot**. Only the selected source's
   profile or directory field is enabled.
7. Select the repository and click **Create**.

The tray uses the same implementation as the CLI for the hooked path. OAuth
selects `ai-guardian-codex`; API key selects `ai-guardian-openai`.

For OpenShell, **OpenShell sandbox mode** keeps the two supported paths
explicit:

- **AI Guardian hooks** uses the managed support image, hooks, daemon, and
  selected CLI setup.
- **Native OpenShell** delegates image, lifecycle, and workload setup entirely
  to OpenShell. It does not add AI Guardian labels, hooks, or a daemon.

The optional **OpenShell policy profile** selector discovers repository and
configured policy files and shows a validation state and top-level preview.
Selected profiles are passed through the existing OpenShell policy composition
path; custom overlays remain available in **Additional policy files**.

The standalone tray action **Check middleware readiness...** checks the qualified
OpenShell version and gateway health, reads middleware endpoints from the
effective gateway TOML, and calls each endpoint's gRPC `Describe` method. It
reports **Running** only for a responding endpoint that identifies itself as
`ai-guardian/rust-middleware` and supplies a version; gateway-reported extension
activation is shown separately. No binary path, registration name, or endpoint
input is needed. The tray provides operator-owned service-manager and
gateway-TOML guidance but does not install or stop the external Rust service.
For an OpenShell target, use **Manage sandbox → Apply policy to sandbox...**;
the form is scoped to that selected sandbox, exports its round-trippable base
policy, previews the complete replacement, and requires confirmation before
calling `openshell policy set --wait`.

## After creation

Use these commands for any named sandbox:

```bash
ai-guardian sandbox status guardian-codex
ai-guardian sandbox exec guardian-codex -- ai-guardian doctor
ai-guardian sandbox logs guardian-codex --follow
ai-guardian sandbox stop guardian-codex
ai-guardian sandbox start guardian-codex
ai-guardian sandbox delete guardian-codex
```

`connect` opens an interactive shell for containers. OpenShell `create` already
opens an independent shell; use `connect` later when the sandbox is stopped or
when you start a new session:

```bash
ai-guardian sandbox connect guardian-codex
```

## OpenShell command mappings

| AI Guardian | Native OpenShell |
| --- | --- |
| `sandbox status NAME` | `openshell sandbox get NAME` |
| `sandbox start NAME` | `openshell sandbox start NAME` |
| `sandbox stop NAME` | `openshell sandbox stop NAME` |
| `sandbox connect NAME` | `openshell sandbox exec --name NAME --tty -- /bin/bash -l` |
| `sandbox exec NAME -- CMD` | `openshell sandbox exec --name NAME -- CMD` |
| `sandbox logs NAME` | `openshell logs NAME` |
| `sandbox delete NAME` | `openshell sandbox delete NAME` |

## Create options

The most useful options are:

| Option | Use |
| --- | --- |
| `--runtime container` | Use Docker/Podman instead of the OpenShell default. |
| `--cli NAME` | Select the CLI. OpenShell supports `codex`, `claude`, and `opencode`. |
| `--repo DIR` | Mount a container repository or upload it to OpenShell. |
| `--name NAME` | Choose the sandbox name. |
| `--profile PROFILE` | Start with a bundled or custom AI Guardian profile. |
| `--policy FILE` | Add an OpenShell policy file; repeatable. |
| `--provider NAME` | Attach an existing OpenShell provider; repeatable. |
| `--openshell-auth {oauth,api-key}` | Select automatic OpenShell Codex authentication. |
| `--agent-provider NAME` | Select Pi's provider in Container sandboxes. |
| `--opencode-agent-profile NAME` | Select an OpenCode profile in Container or OpenShell sandboxes. |
| `--env KEY=VALUE` | Add an environment variable; repeatable. |
| `--model MODEL` | Select the CLI or OpenShell model. |

For a complete parser-generated list, run:

```bash
ai-guardian sandbox create --help
```

OpenShell middleware is not a sandbox creation option. Register and run it at
the OpenShell gateway, then manage its `network_middlewares` policy through
OpenShell. See the [OpenShell middleware guide](OPENSHELL_MIDDLEWARE.md) for
the gateway boundary and policy requirements.

## Configuration snapshots

Snapshots are stored on the host and never overwrite the host configuration.

```bash
ai-guardian sandbox config save guardian-codex
ai-guardian sandbox config list guardian-codex
ai-guardian sandbox config restore guardian-codex --snapshot latest
```

Recreate a deleted sandbox from its latest snapshot:

```bash
ai-guardian sandbox create \
    --runtime container \
    --name guardian-codex \
    --restore-config latest \
    --repo .
```

## Configuration precedence

For a new sandbox, the first applicable source wins:

1. `--profile`.
2. `--restore-config latest`.
3. An existing sandbox-local `ai-guardian.json`.
4. The selected host configuration.
5. A new default configuration.

The host configuration is copied or staged; changes inside the sandbox do not
modify the host file.

## Listing and lifecycle

```bash
ai-guardian sandbox list
ai-guardian sandbox list --runtime container --json
ai-guardian sandbox list --runtime openshell --json
ai-guardian sandbox status guardian-codex --json
ai-guardian sandbox restart guardian-codex
```

Lifecycle commands detect the runtime from the sandbox name. Add
`--runtime container` or `--runtime openshell` when the same name exists in
both runtimes.

## Troubleshooting

### `no provider profile for 'codex'`

Run [OpenShell provider setup](#openshell-provider-setup), then retry. The
profiles are gateway-local; importing them on another machine is not enough.

### `unknown setting key 'providers_v2_enabled'`

This is expected on OpenShell v0.1.3 and later: `providers_v2_enabled` was a
v0.1.2-only setting and is not needed for the qualified baseline. Continue with
the imported profiles. OpenShell v0.1.2 and earlier are not qualified by AI
Guardian.

### API-key authentication is not found

For Container, export `OPENAI_API_KEY` before `sandbox create`. For OpenShell,
select `--openshell-auth api-key` and export the key before creation, or create
the `ai-guardian-openai` provider explicitly in the active gateway.

### OpenShell reports connection refused

Check the gateway and, on Linux, the user services:

```bash
openshell status
systemctl --user status openshell-gateway
systemctl --user status podman.socket
```

For Claude/Vertex or OpenCode/Vertex, the manual compatibility runner also
reports a `metadata_unavailable` step if the sandbox cannot reach
`127.0.0.1:8174`. Confirm the active gateway is OpenShell 0.1.3 or later and
that a `google-cloud` provider is attached; provider-backed GCE metadata is
served by the supervisor, not by the host's cloud metadata service.

## Manual Live Provider Smoke Tests

Live provider calls are opt-in and use personal credentials. See the
[`container/tests/README.md`](../container/tests/README.md) for the qualification
runner and report format:

```bash
python container/tests/test_openshell_agents.py \
    --image localhost/ai-guardian-openshell:dev \
    --case codex
```
