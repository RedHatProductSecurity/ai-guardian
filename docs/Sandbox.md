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
| 5 | Tray | Either runtime | [Tray](#case-5--tray-create-sandbox) |

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

Complete this once for each OpenShell gateway. It is required for Cases 3 and
4.

### Prerequisites

- OpenShell CLI and gateway `0.1.2` or newer.
- A configured OpenShell compute driver.
- Rootless Podman users on Linux must have the Podman socket enabled.

### Step 1 — Install and check the local gateway

Use the pinned release below for the documented AI Guardian path:

```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh \
    | OPENSHELL_VERSION=v0.1.2 sh
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
    https://raw.githubusercontent.com/NVIDIA/OpenShell/v0.1.2/providers/codex.yaml \
    -o /tmp/openshell-codex.yaml
curl -fsSL \
    https://raw.githubusercontent.com/NVIDIA/OpenShell/v0.1.2/providers/openai.yaml \
    -o /tmp/openshell-openai.yaml

openshell provider profile import \
    --file /tmp/openshell-codex.yaml --global
openshell provider profile import \
    --file /tmp/openshell-openai.yaml --global
openshell provider list-profiles
```

The expected profiles are `codex` and `openai`. If import says a profile
already exists, continue; it is already installed.

### Step 3 — Enable Providers v2 on OpenShell 0.1.2

```bash
openshell settings set --global \
    --key providers_v2_enabled \
    --value true
```

If a newer OpenShell release reports `unknown setting key
'providers_v2_enabled'`, skip this step. Do not change another setting.

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
to the sandbox.

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

## Case 5 — Tray Create sandbox

**Prerequisites**

- The tray is running.
- For Container, Docker/Podman is installed.
- For OpenShell, complete [OpenShell provider setup](#openshell-provider-setup).
- For OpenShell OAuth, run `codex login` in the environment used by the tray.
- For OpenShell API key, either start the tray with `OPENAI_API_KEY` available,
  or create `ai-guardian-openai` in the gateway first and enter that name in
  **OpenShell provider override**.

**Steps**

1. Open the tray menu and select **Create sandbox...**.
2. Select **Runtime**: `container` or `openshell`.
3. Select **CLI**: OpenShell currently offers `codex` only.
4. For OpenShell, select **Codex authentication**: **OAuth** or **API key**.
5. Select the repository and click **Create**.

The tray uses the same implementation as the CLI. OAuth selects
`ai-guardian-codex`; API key selects `ai-guardian-openai`.

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
| `--cli NAME` | Select the CLI. OpenShell supports `codex` only. |
| `--repo DIR` | Mount a container repository or upload it to OpenShell. |
| `--name NAME` | Choose the sandbox name. |
| `--profile PROFILE` | Start with a bundled or custom AI Guardian profile. |
| `--policy FILE` | Add an OpenShell policy file; repeatable. |
| `--provider NAME` | Attach an existing OpenShell provider; repeatable. |
| `--openshell-auth {oauth,api-key}` | Select automatic OpenShell Codex authentication. |
| `--middleware` | Start/reuse external AI Guardian middleware and generate its OpenShell attachment; see [middleware sandbox quickstart](OPENSHELL_MIDDLEWARE.md#quickstart-first-class-middleware-sandbox-creation). |
| `--agent-provider NAME` | Select Pi's provider in Container sandboxes. |
| `--opencode-agent-profile NAME` | Select an OpenCode profile in Container sandboxes. |
| `--env KEY=VALUE` | Add an environment variable; repeatable. |
| `--model MODEL` | Select the CLI or OpenShell model. |

For a complete parser-generated list, run:

```bash
ai-guardian sandbox create --help
```

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

You are using a newer OpenShell release. Skip that v0.1.2-only setting and
continue with the imported profiles.

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

## Manual Live Provider Smoke Tests

Live provider calls are opt-in and use personal credentials. See the
[`container/tests/README.md`](../container/tests/README.md) for the qualification
runner and report format:

```bash
python container/tests/test_openshell_agents.py \
    --image localhost/ai-guardian-openshell:dev \
    --case codex
```
