# AI Guardian Container Image

The published image is a UBI-based Docker/Podman support image with
ai-guardian and the supported agent integrations. Headless-capable CLIs are
bundled; GUI-only integrations receive their hooks when the container starts.

OpenShell uses a separate image definition, `Dockerfile.openshell`, based on
the [OpenShell Community sandbox base image](https://github.com/NVIDIA/OpenShell-Community/tree/main/sandboxes/base).
That base supplies the OpenShell-compatible filesystem layout, networking
tools, and agent runtime. The dedicated OpenShell image is published in its
own primary Quay repository as
`quay.io/redhatproductsecurity/ai-guardian-openshell:latest` on successful
merges and as `:<version>` for releases. Build it locally only when testing a
change to the image; `ai-guardian sandbox create --runtime openshell` uses the
published OpenShell image by default. The OpenShell image is not published in
the normal image repository.
The normal UBI image remains published to
[quay.io/redhatproductsecurity/ai-guardian](https://quay.io/redhatproductsecurity/ai-guardian)
on every merge and release.

## Recommended runtime

Use OpenShell when it is available, especially for provider-backed Claude or
Codex sessions. OpenShell keeps provider credentials in the gateway rather
than mounting them into the agent sandbox, and adds deny-by-default network
and filesystem policy, provider-backed inference, repository isolation, and
per-sandbox gateway services. OpenShell support is experimental, but it is the
preferred security boundary for the tested provider workflows.

The plain Docker/Podman container is a simpler fallback and is useful for
local development or environments without an OpenShell gateway. Its Vertex
ADC file or direct API-key environment is available inside the container, so
the selected agent may be able to read that credential material.

## What's Included

| Component | License | Installed |
|-----------|---------|-----------|
| ai-guardian | Apache 2.0 | Build time |
| Gitleaks, BetterLeaks | MIT | Build time |
| LeakTK | Apache 2.0 | Build time |
| detect-secrets | Apache 2.0 | Build time |
| Secretlint | MIT | Build time |
| GitGuardian ggshield CLI | MIT (service terms apply) | Build time |
| OpenCode | MIT | Build time |
| Gemini CLI | Apache 2.0 | Build time |
| Codex CLI | Apache 2.0 | Build time |
| OpenClaw | MIT | Build time |
| rapidocr-onnxruntime | Apache 2.0 | Build time |
| Claude Code | Proprietary (Anthropic) | **Runtime — ToS consent required** |
| Kiro CLI | Proprietary (AWS) | **Runtime — ToS consent required** |

Claude Code and Kiro CLI are proprietary and redistribution-restricted. They are not
bundled in the image. Instead, the container installs them at first start after
prompting the user to accept the respective Terms of Service.

See [Proprietary CLI Consent](#proprietary-cli-consent) below.

## Pull

```bash
# Latest build from main branch
podman pull quay.io/redhatproductsecurity/ai-guardian:latest

# Specific release version
podman pull quay.io/redhatproductsecurity/ai-guardian:1.17.1
```

Tag conventions:
- `:latest` — tracks main branch (updated on every merge)
- `:<version>` — pinned stable release (e.g. `1.17.1`)

## Build Locally

```bash
# Default (latest release)
podman build -t ai-guardian container/

# Specific version
podman build --build-arg AI_GUARDIAN_VERSION=1.17.1 -t ai-guardian container/

# Local wheel (copy the wheel into container/vendor/ first)
WHEEL_PATH=dist/ai_guardian-1.17.1-py3-none-any.whl
WHEEL_NAME="$(basename "$WHEEL_PATH")"
cp "$WHEEL_PATH" "container/vendor/$WHEEL_NAME"
podman build --build-arg "AI_GUARDIAN_VERSION=$WHEEL_NAME" \
    -t ai-guardian container/

# Multi-arch
podman build --platform linux/amd64,linux/arm64 -t ai-guardian container/

# Dedicated OpenShell BYOC image (the sandbox command uses the published image by default)
podman build -f container/Dockerfile.openshell \
    -t localhost/ai-guardian-openshell:latest container/
```

## Run

Using `run.sh` (recommended):

```bash
./container/run.sh                                    # defaults: Codex
./container/run.sh --agent opencode                   # select agent
./container/run.sh --profile @strict                  # select profile
./container/run.sh --config-dir "$HOME/.config/ai-guardian"
./container/run.sh --repo ~/myproject                 # mount a repo
./container/run.sh --api-key sk-ant-...               # Anthropic API auth
./container/run.sh --agent gemini --profile @minimal  # combine options
./container/run.sh -- ai-guardian doctor              # run a command
```

Vertex AI auth is auto-detected from environment variables (see [Authentication](#authentication)).

At startup the sandbox command configures only the selected `--cli`; configuring
other integrations is unnecessary when the sandbox runs one CLI. To opt into
broader setup, set
`AI_GUARDIAN_SETUP_SCOPE=cli` for all supported CLI agents or
`AI_GUARDIAN_SETUP_SCOPE=all` for every supported integration.

### CLI lifecycle management

The `ai-guardian sandbox` subcommand provides named lifecycle operations for
both supported runtimes. Container creation is detached; OpenShell creation
connects to the sandbox shell after setup, like native OpenShell:

```bash
# Docker/Podman (defaults to podman; set CONTAINER_ENGINE=docker if needed)
ai-guardian sandbox create --runtime container --name guardian-codex --repo .
ai-guardian sandbox list
ai-guardian sandbox status guardian-codex
ai-guardian sandbox stop guardian-codex
ai-guardian sandbox start guardian-codex
ai-guardian sandbox connect guardian-codex
ai-guardian sandbox exec guardian-codex -- ai-guardian doctor
ai-guardian sandbox logs guardian-codex --follow
ai-guardian sandbox config save guardian-codex
ai-guardian sandbox delete guardian-codex

# OpenShell (uses OPENSHELL_CLI or the openshell executable on PATH)
# Create; policy files are repeatable.
ai-guardian sandbox create \
    --runtime openshell \
    --name guardian-claude \
    --cli claude \
    --repo . \
    --policy ./container/openshell-github-readonly-policy.yaml

# List managed OpenShell sandboxes.
ai-guardian sandbox list --runtime openshell

# Inspect status; runtime is auto-detected by name.
ai-guardian sandbox status guardian-claude

# Open an independent interactive shell.
ai-guardian sandbox connect guardian-claude

# Execute a command without replacing the sandbox process.
ai-guardian sandbox exec guardian-claude -- ai-guardian doctor

# Stream logs.
ai-guardian sandbox logs guardian-claude --follow

# Save and inspect configuration snapshots.
ai-guardian sandbox config save guardian-claude
ai-guardian sandbox config list guardian-claude

# Stop, start, or restart.
ai-guardian sandbox stop guardian-claude
ai-guardian sandbox start guardian-claude
ai-guardian sandbox restart guardian-claude

# Permanently delete.
ai-guardian sandbox delete guardian-claude
```

For multiple policy overlays, repeat the option in the same create command:

```bash
ai-guardian sandbox create --runtime openshell --name guardian-claude \
    --cli claude --repo . \
    --policy ./policy-one.yaml \
    --policy ./policy-two.yaml
```

Runtime selection can also appear before the lifecycle verb, as in
`ai-guardian sandbox --runtime openshell list`. New sandbox creation defaults to
OpenShell, including the tray create form; pass `--runtime container` explicitly
to use Docker/Podman. For named lifecycle commands, omit the runtime and the
CLI probes AI Guardian labels/metadata to choose Docker/Podman or OpenShell. An
unqualified `list` combines managed resources from both runtimes. `list` is
limited to resources created through this command's `ai-guardian.managed=true`
label. The sandbox command also owns provider setup, policy composition,
host-config snapshots, and OpenShell upload bootstrapping; no separate
OpenShell script is required.

For OpenShell, the following lifecycle commands map directly to the native CLI
and preserve its exit status and terminal behavior, except for `connect`, which
uses an independent exec session so leaving the shell does not terminate the
sandbox:

| AI Guardian command | Native OpenShell command |
| --- | --- |
| `ai-guardian sandbox status NAME` | `openshell sandbox get NAME` |
| `ai-guardian sandbox start NAME` | `openshell sandbox start NAME` |
| `ai-guardian sandbox stop NAME` | `openshell sandbox stop NAME` |
| `ai-guardian sandbox connect NAME` | `openshell sandbox exec --name NAME --tty -- /bin/bash -l` |
| `ai-guardian sandbox delete NAME` | `openshell sandbox delete NAME` |
| `ai-guardian sandbox exec NAME -- CMD` | `openshell sandbox exec --name NAME -- CMD` |
| `ai-guardian sandbox logs NAME` | `openshell logs NAME` |

`sandbox restart` implements the convenient stop-then-start sequence because
OpenShell has no separate restart command. `sandbox create` adds AI Guardian
image, environment, and labeling defaults; `sandbox list` adds the managed
label selector, so those two commands are not plain aliases. See the full
[Sandbox CLI guide](../docs/Sandbox.md) for create options and lifecycle
details. Upload-based OpenShell creation bootstraps the entrypoint
non-interactively, exposes the gateway-managed `ai-guardian` service, and then
connects to the sandbox shell. Exiting that shell returns to the host while
`sandbox connect` remains
available for later sessions. A container created without an explicit command
keeps a login shell with an allocated TTY as its main process, so it remains
available for
`connect` and `exec`; start the selected agent from that shell or with
`sandbox exec`. A supplied `--name` is also recorded for tray and NiceGUI
display, preventing a runtime-generated container ID from being shown.

Use `ai-guardian sandbox config save NAME` to preserve changes made inside a
running sandbox. The newest timestamped snapshot can be used when recreating
the sandbox with `sandbox create --name NAME --restore-config latest`; snapshots
are stored in the host XDG state directory and never overwrite the host config.

### OpenShell

The OpenShell sandbox command uses the dedicated `Dockerfile.openshell` image
rather than the normal UBI image. Build it once from the repository root:

The normal `run.sh` container still defaults to Codex. The OpenShell sandbox
command defaults to Claude, matching OpenShell's first-class default-policy
coverage; select another CLI explicitly with `--cli`.

OpenShell integration is experimental. The documented workflows have been
tested with Claude Code through Google Vertex AI, Codex through its OpenShell
provider, and OpenCode using Claude through Vertex AI. Claude
marketplace/plugin installation has also been tested with the read-only GitHub
overlay described below.

```bash
podman build -f container/Dockerfile.openshell \
    -t localhost/ai-guardian-openshell:latest container/
```

To use that local build for one run, pass it explicitly:

```bash
ai-guardian sandbox create --runtime openshell --base localhost/ai-guardian-openshell:latest
```

The published image can be pulled explicitly as well:

```bash
podman pull quay.io/redhatproductsecurity/ai-guardian-openshell:latest
```

Set `AI_GUARDIAN_OPEN_SHELL_IMAGE` to use another OpenShell-compatible image,
or pass `--base IMAGE`/`--image IMAGE` on one invocation. The explicit
`AI_GUARDIAN_IMAGE` variable remains the highest-priority image override. The
subcommand uses the OpenShell-supported `--from`, `--env`, and `--upload`
options, then exposes the daemon's sandbox-local REST port through the
gateway-managed `ai-guardian` service. The gateway gives each sandbox its own
service URL, so multiple sandboxes can use internal port `63152` concurrently.

`Dockerfile.openshell` pins the tested Community base by digest rather than
using the mutable `:latest` tag. To refresh it deliberately, pull the desired
base, inspect its digest, review the inherited agent/policy changes, update the
`BASE_IMAGE` default, rebuild, and rerun the OpenShell smoke tests. A one-off
override is also possible:

```bash
podman build \
    --build-arg BASE_IMAGE=ghcr.io/nvidia/openshell-community/sandboxes/base@sha256:<reviewed-digest> \
    -f container/Dockerfile.openshell \
    -t localhost/ai-guardian-openshell:latest container/
```

The pinned base includes older versions of some bundled Node-based CLIs, so
`Dockerfile.openshell` replaces only Codex and OpenCode with explicit,
independently overridable versions. Claude Code and GitHub Copilot remain
inherited from the base image:

| Build argument | Package | Default |
|----------------|---------|---------|
| `CODEX_VERSION` | `@openai/codex` | `0.154.0` |
| `OPENCODE_VERSION` | `opencode-ai` | `1.18.31` |

These are pinned rather than installed through a mutable `latest` tag so an
image can be reproduced and rolled back. The Dockerfile verifies that Claude
Code and GitHub Copilot are supplied by the base image but does not download,
modify, or version-pin them. Override either managed version deliberately when
testing another release. Rebuild the image and recreate the sandbox after
changing one; existing sandboxes retain the client versions from their
original image.

```bash
podman build -f container/Dockerfile.openshell \
    --build-arg CODEX_VERSION=0.154.0 \
    --build-arg OPENCODE_VERSION=1.18.31 \
    -t localhost/ai-guardian-openshell:latest container/
```

For development, build and launch the local image in one workflow from the
repository root. The repository snapshot is uploaded to the sandbox, and the
read/write GitHub policy is applied to the selected Codex agent:

```bash
podman build -f container/Dockerfile.openshell \
    --build-arg CODEX_VERSION=0.154.0 \
    -t localhost/ai-guardian-openshell:dev \
    container/

ai-guardian sandbox create --runtime openshell \
    --base localhost/ai-guardian-openshell:dev \
    --cli codex \
    --policy ./container/openshell-github-readwrite-policy.yaml \
    --provider ai-guardian-codex \
    --repo .
```

Use a different `CODEX_VERSION` build argument when testing a specific Codex
release. Rebuild the image and recreate the sandbox after changing the source
wheel or a bundled CLI version.

#### CLI scope and image contents

AI Guardian has 15 public integrations. OpenShell is terminal-first, so its
agent selector contains only these eight CLI-capable integrations:
`claude`, `copilot`, `codex`, `gemini`, `kiro`, `openclaw`, `opencode`, and
`crush`. The seven GUI/editor integrations—`cursor`, `windsurf`, `cline`,
`zoocode`, `aiderdesk`, `augment`, and `junie`—remain available to the normal
container setup but are intentionally excluded from the OpenShell selector.

The current OpenShell Community base supplies Claude, Codex, OpenCode, and
Copilot. This derived image leaves Claude and Copilot unchanged and explicitly
refreshes the two managed CLIs shown above. Gemini, OpenClaw, Crush, and Kiro
are not installed by this default image; selecting one requires a custom image
that supplies its command, and Kiro retains its runtime consent flow. The
version monitor checks the two explicit npm pins. Only the selected CLI is
configured by default; set
`AI_GUARDIAN_SETUP_SCOPE=cli` when one sandbox will run multiple CLI agents.
Other installed CLIs are not removed, but they still need a compatible
provider and network policy before they are useful in the sandbox.

#### License and redistribution

There is no blanket license clearance for the complete derived image. The
OpenShell Community repository is Apache-2.0, but its
[third-party notices](https://github.com/NVIDIA/OpenShell-Community/blob/main/THIRD-PARTY-NOTICES)
also cover inherited system components and their separate licenses. Codex is
Apache-2.0 and OpenCode is MIT; GitHub Copilot and Claude Code remain subject
to their own licenses and service terms. They are inherited unchanged from the
base image, so the OpenShell Dockerfile does not download or modify them; users
still need their own authorized account or API access. Review the exact
package and base image notices before making a Quay repository public or
redistributing the image. The build workflow deliberately publishes OpenShell
only to the dedicated primary Quay repository and does not mirror it to
`itdove`.
For OpenShell installation and first-time setup, see the official
[OpenShell quickstart](https://docs.nvidia.com/openshell/get-started/quickstart).
For policy fields and validation rules, see the official
[policy schema reference](https://docs.nvidia.com/openshell/reference/policy-schema)
and [policy customization guide](https://docs.nvidia.com/openshell/sandboxes/policies).

OpenShell prerequisites are:

- The OpenShell CLI installed on the host.
- A reachable OpenShell gateway.
- A gateway compute driver configured for Docker, Podman, MicroVM, or
  Kubernetes.

The sandbox command requires an OpenShell CLI and gateway new enough to support
`sandbox create --env` and the upload-based staging workflow. Install or
update OpenShell on the host, then refresh the shell command and verify both
the client and gateway:

```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
hash -r
openshell --version
openshell status
```

On Fedora/Linux, the installer provides the CLI and a systemd user service:

```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
systemctl --user status openshell-gateway
openshell status
```

If the Linux gateway uses rootless Podman, it also needs the
rootless Podman API socket. Start it as the same user that runs the gateway:

```bash
systemctl --user enable --now podman.socket
test -S "${XDG_RUNTIME_DIR}/podman/podman.sock"
systemctl --user restart openshell-gateway
openshell status
```

On macOS, the installer uses Homebrew and manages the gateway with a Homebrew
service:

```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
brew services list
brew services restart openshell
openshell status
```

If macOS still reports an older version after updating, check which executable
is being used with `type -a openshell`; the shell may be finding an older
installation first. Updating the AI Guardian branch does not update the
OpenShell CLI or gateway, and provider profiles remain local to each gateway.

If the gateway reports that `/run/user/<uid>/podman/podman.sock` is missing,
the socket is stopped or the gateway is pinned to the wrong path. Omit
`socket_path` from `[openshell.drivers.podman]` to use OpenShell auto-detection,
or set it to the active `${XDG_RUNTIME_DIR}/podman/podman.sock` path in
`$HOME/.config/openshell/gateway.toml`, then restart the gateway. Do not use
`sudo` with the rootless `systemctl --user` command.

If `openshell status` reports `Connection refused`, inspect the gateway before
retrying the sandbox command:

```bash
systemctl --user is-active openshell-gateway
journalctl --user -u openshell-gateway --no-pager -n 100
```

On SELinux-enabled systems, inspect the recent AVC records for the denied
path or operation instead of disabling enforcement or installing a broad local
allow rule:

```bash
sudo ausearch -m avc -ts recent -i
```

For a gateway hosted elsewhere, register its reachable endpoint instead:

```bash
openshell gateway add https://gateway.example.com --name production
openshell status
```

For a containerized gateway, see OpenShell's [container gateway
guide](https://docs.nvidia.com/openshell/about/container-gateway).

Before the first sandbox command call, enable OpenShell Providers v2 on the active
gateway. This is required for the sandbox command’s provider-backed Claude, Codex,
and Vertex AI flows:

```bash
openshell settings set --global --key providers_v2_enabled --value true
```

```bash
ai-guardian sandbox create --runtime openshell        # opens a shell; Claude is selected
ai-guardian sandbox create --runtime openshell --cli opencode --agent claude --repo .
ai-guardian sandbox create --runtime openshell --profile @strict --policy ./container/openshell-github-readwrite-policy.yaml
ai-guardian sandbox create --runtime openshell --config-dir "$HOME/.config/ai-guardian"
```

The OpenShell sandbox command opens `/bin/bash` by default. When `--repo` is supplied,
the shell starts in the uploaded repository at `/sandbox/repo`; otherwise it
starts in `/sandbox`. The selected `--cli` controls the AI Guardian setup,
policy fragment, and automatic provider selection. With `--cli opencode`,
`--agent` is required and selects the OpenCode agent profile. When a `--policy`
overlay is supplied, it also selects the matching CLI policy fragment. Without
an overlay, the sandbox command still applies the shared base policy and the
selected CLI policy, but no GitHub policy is added. The sandbox command does
not start the CLI automatically.

Provider profiles belong to the active OpenShell gateway; they are not stored
in the repository, image, or Git branch. When `--provider` is omitted, the
sandbox command asks that gateway for a provider profile matching the selected CLI
and may create or reuse the corresponding `ai-guardian-<cli>` provider from
local credentials. If the gateway does not advertise a Codex profile, a
launch selecting `--cli codex` fails with an error such as “the active
OpenShell gateway has no provider profile for codex.” Configure a Codex
provider on that gateway first, or pass an already configured provider
explicitly:

```bash
ai-guardian sandbox create --runtime openshell \
    --base localhost/ai-guardian-openshell:latest \
    --cli codex \
    --provider ai-guardian-codex \
    --repo .
```

Use `openshell provider get ai-guardian-codex` to verify that the named
provider exists on the currently active gateway. Provider setup must be
repeated for each gateway or laptop; `git pull` only updates the sandbox command and
policy files.

The `--provider` option attaches an existing provider instance and does not
create one. In Claude Vertex mode, the sandbox command also refreshes that provider's
project/region configuration and uses it for the workspace inference route.
To let the sandbox command create
`ai-guardian-codex` from local Codex credentials, omit `--provider` and ensure
the active gateway lists the `codex` profile:

```bash
openshell provider list-profiles
ai-guardian sandbox create --runtime openshell \
    --base localhost/ai-guardian-openshell:latest \
    --cli codex \
    --repo .
```

Provider creation requires a matching gateway profile and credentials
available to the sandbox command. If `codex` is absent from `list-profiles`, update or
reconfigure the active OpenShell gateway before retrying.

```bash
ai-guardian sandbox create --runtime openshell \
    --cli codex \
    --policy ./container/openshell-github-readwrite-policy.yaml \
    --provider ai-guardian-codex \
    --provider ai-guardian-github \
    --repo .
```

The sandbox command runs setup before opening the shell. You can launch the selected
CLI from that shell; when the CLI exits, you return to the shell and can
inspect, commit, and push changes. The repository is still an OpenShell
snapshot, so commits and other file changes are made in the sandbox copy. With
the read/write GitHub policy and an attached GitHub provider, `git push` goes
to GitHub through the gateway; it does not modify the host checkout. To launch
the selected CLI immediately instead, pass it after `--`, for example
`-- codex`.

From the shell, launch and exit the selected CLI as often as needed:

```bash
codex
git status
git add .
git commit -m "Your change"
git push
```

The OpenShell sandbox command exposes the daemon's sandbox-local port `63152`
through the gateway-managed `ai-guardian` service:

```bash
openshell service expose NAME 63152 ai-guardian
openshell service get NAME ai-guardian
```

The gateway assigns a unique URL such as
`http://NAME--ai-guardian.openshell.localhost:PORT/`. The same internal port
can be exposed by multiple sandboxes, and tray/NiceGUI discovery queries each
sandbox's URL. `--port` is only supported for container sandboxes; OpenShell
does not use a host-side forward process.

#### Claude Code with Google Vertex AI

To run Claude Code through Google Vertex AI, select Claude and provide a GCP
project. The sandbox command automatically creates or updates the gateway-local
`ai-guardian-google-vertex-ai` provider, including its required project and
region configuration. No GitHub policy is needed for model inference:

```bash
export ANTHROPIC_VERTEX_PROJECT_ID=my-gcp-project
export CLOUD_ML_REGION=global

ai-guardian sandbox create --runtime openshell \
    --base localhost/ai-guardian-openshell:latest \
    --cli claude \
    --model claude-sonnet-4-6 \
    --repo .
```

When using a locally built image, rebuild it after pulling this change because
the provider-backed inference environment fallback is installed by the image
entrypoint.

Providers v2 must be enabled on the active gateway before the first sandbox command
call so the provider-owned Vertex network policy is included:

```bash
openshell settings set --global --key providers_v2_enabled --value true
```

The sandbox command attaches the gateway Vertex provider, configures the
workspace's OpenShell `inference.local` route, and passes Claude only the
non-secret client settings it requires:

```text
ANTHROPIC_BASE_URL=https://inference.local
ANTHROPIC_API_KEY=unused
```

The key is only a protocol placeholder; `--bare` skips Claude's OAuth login
flow and uses `ANTHROPIC_API_KEY` directly. The placeholder does not reach
Vertex AI: `inference.local` strips it and injects the attached provider's
refreshed GCP access token before forwarding the request. The create command
suppresses OpenShell's plain-environment credential warning for this known
placeholder. From the resulting shell, start Claude explicitly with the
OpenShell-documented `--bare` flag:

```bash
claude --bare
```

AI Guardian does not install a persistent shell wrapper. For an explicit
automated `claude --print ...` command passed during creation, the entrypoint
adds `--bare` when it is missing. Administrative commands such as `claude
plugin` and `claude doctor` are passed through unchanged. Do not set
`CLAUDE_CODE_USE_VERTEX=1` inside an OpenShell sandbox. That mode makes Claude
try to discover GCP credentials directly inside the sandbox, where the host
ADC file is intentionally not mounted. The OpenShell sandbox command uses
gateway-managed inference instead. Use `--model MODEL` to select the gateway
model; the default is `claude-sonnet-4-6`.

Claude's background self-updater is disabled in OpenShell because the image
installation is read-only. To update Claude Code, rebuild the OpenShell image
and create a new sandbox; the sandbox command sets `DISABLE_AUTOUPDATER=1`
automatically.

#### OpenCode through OpenShell inference

OpenCode is a CLI with its own agent profiles and model/provider selection.
The `--agent` profile is required when `--cli opencode` is selected. Use the
explicit two-level form when an OpenCode profile should use Claude:

```bash
ai-guardian sandbox create --runtime openshell \
    --cli opencode \
    --agent claude \
    --model claude-sonnet-4-6 \
    --provider vertex-provider \
    --repo .
```

This `opencode` + `claude` + Claude/Vertex combination has been tested. The
`--cli` value selects OpenCode, `--agent claude` selects the tested profile,
and `--model` plus `--provider` select the inference backend.

Here `--agent claude` is an OpenCode agent profile and `--model` selects the
OpenShell inference model. OpenCode's `build` and `plan` names are profiles,
not providers: with the default `claude-sonnet-4-6` model they use the same
Claude-compatible route, while an explicitly non-Claude model leaves generic
OpenCode provider handling unchanged. The tested Claude route enables:

```text
ANTHROPIC_BASE_URL=https://inference.local/v1
ANTHROPIC_API_KEY=unused
```

Generic OpenCode providers are left unchanged. OpenCode has no Claude-style
`--bare` flag; run `opencode --agent NAME` normally. Configure the gateway
route first with `openshell inference set` and the provider/model you want to
use.

The Claude/Vertex policy does not grant GitHub access by default. The command
above is sufficient for Claude requests, Vertex inference, and an ordinary
Claude session. Marketplace or plugin installation and refresh are different:
you must add the read-only GitHub overlay because the Anthropic marketplace is
fetched from GitHub. Without this overlay, model requests still work but
marketplace installation or refresh fails due to OpenShell's deny-by-default
network policy. The read/write GitHub policy and GitHub provider are not
required for the public catalog.

This uses OpenShell's [Vertex provider](https://docs.nvidia.com/openshell/providers/google-vertex-ai)
and [inference routing](https://docs.nvidia.com/openshell/sandboxes/inference-routing)
features. The effective sandbox policy should show a provider-derived
`_provider_ai_guardian_google_vertex_ai` entry for the Google Vertex hosts.

Keep `--cli claude` when using Vertex AI. `claude` selects the Claude Code
CLI; Vertex is the provider backend, not a separate CLI, so
`--cli claude-vertex` is not a valid selector. The expected provider name is
`ai-guardian-google-vertex-ai`.

The sandbox command uses Google Application Default Credentials (ADC) while creating
or refreshing the provider. Set `GOOGLE_APPLICATION_CREDENTIALS` to a
service-account JSON file when it is not at the standard gcloud ADC location,
or authenticate with gcloud first. The credential file is consumed by the
gateway and is not uploaded into the sandbox:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-credentials.json
export ANTHROPIC_VERTEX_PROJECT_ID=my-gcp-project
export CLOUD_ML_REGION=global

ai-guardian sandbox create --runtime openshell --cli claude --repo .
```

The active gateway must expose the `google-vertex-ai` provider profile. If the
sandbox command reports that the profile is missing, update or reconfigure the
active OpenShell gateway. For direct Anthropic access instead, use
`ANTHROPIC_API_KEY` and omit the Vertex project variables.

If a provider created by an older sandbox command shows no config keys, rerunning the
sandbox command updates it with `VERTEX_AI_PROJECT_ID` and `VERTEX_AI_REGION`. The
equivalent manual repair is:

```bash
openshell provider update ai-guardian-google-vertex-ai \
    --config VERTEX_AI_PROJECT_ID="$ANTHROPIC_VERTEX_PROJECT_ID" \
    --config VERTEX_AI_REGION="${CLOUD_ML_REGION:-global}"
```

The Vertex policy is separate from Claude plugin marketplace access. The
default Claude policy intentionally does not allow GitHub. To install or
refresh the public Claude plugin marketplace, you must add the read-only
GitHub overlay. A read/write GitHub policy or GitHub credential provider is
not required for the public catalog:

```bash
ai-guardian sandbox create --runtime openshell \
    --base localhost/ai-guardian-openshell:latest \
    --cli claude \
    --policy ./container/openshell-github-readonly-policy.yaml \
    --repo .
```

Claude's diagnostics may report that the first-party `api.anthropic.com`
provider, Claude.ai OAuth, and Remote Control are unavailable. Those checks
are for direct Anthropic/Claude.ai sessions and are expected when Claude is
running through Vertex AI. The relevant test is whether Claude can complete a
model request through the configured Vertex project.

OpenShell discovers common agent credentials through its provider mechanism.
When no profile is selected, an existing host `ai-guardian.json` is uploaded
as the initial configuration snapshot. The sandbox-local config still takes
precedence when it already exists, and the host file is never written. A
selected profile always takes precedence and prevents that full-config upload.
OpenShell's `--upload` gives the sandbox a writable copy, matching the
Docker/Podman sandbox command, which stages the host file with a read-only bind mount
before copying it into the writable active config path.

Agent credential directories are deliberately not mounted or uploaded. For
Codex, the sandbox command reads `$CODEX_HOME/auth.json` (falling back to
`$HOME/.codex/auth.json`) only while creating the OpenShell provider, and
passes the OAuth fields or API key to the provider command without printing
them. The
provider then supplies sandbox-scoped credential placeholders. At sandbox
startup, the entrypoint writes those placeholders into the selected
`$CODEX_HOME/auth.json` in Codex's native ChatGPT format; it never writes the
host's real OAuth tokens into the sandbox. A synthetic JWT-shaped ID token is
used only because Codex parses that field locally. With a gateway that
advertises the `codex` profile and has Providers v2 enabled, Codex should
start without showing its sign-in menu and a separate OpenAI API key is not
required. Enable the gateway feature once with:

```bash
openshell settings set --global --key providers_v2_enabled --value true
```

For API-key authentication, the entrypoint instead runs `codex login
--with-api-key` with the provider-injected `OPENAI_API_KEY` placeholder, so
Codex writes its native API-key `auth.json` without putting the real key in the
sandbox filesystem. This is required even though the provider already exposes
the placeholder as an environment variable.

If Codex still shows the sign-in menu, the provider-backed auth bootstrap was
not available to that process. Start a fresh sandbox with this command rather
than launching `codex` from an unrelated shell, and verify that
`openshell provider get ai-guardian-codex` reports either the four Codex OAuth
credential keys or `OPENAI_API_KEY`, as appropriate. Do not copy the host
`auth.json` into an OpenShell sandbox; use its provider mechanism instead.

When Providers v2 is unset or disabled, OpenShell 0.0.116 falls back to legacy
`codex` discovery, which only recognizes `OPENAI_API_KEY`; the sandbox command reports
this prerequisite instead of asking for an API key that is not needed by a
Codex OAuth login. If the profile is unavailable, use an explicit compatible
provider with `--provider NAME`.

Codex also needs a writable local state database before it can display its
prompt. The sandbox command sets `CODEX_HOME=/sandbox/.codex` and initializes that
directory. The OpenShell policy gives `/sandbox` to the sandbox user, and
keeping Codex state there also lets Codex create its helper binaries instead
of rejecting them as temporary `/tmp` files. If you connect to the sandbox and
run `codex` manually, run the sandbox command first so this environment and directory
are present.

Codex is configured with `sandbox_mode = "danger-full-access"` inside the
OpenShell sandbox. This prevents Codex from trying to create a nested
bubblewrap/user-namespace sandbox; OpenShell remains the outer security and
network boundary. The setting is written only to the sandbox-local
`$CODEX_HOME/config.toml`. Regular Docker/Podman launches keep Codex's normal
inner sandbox behavior. This follows the pattern in OpenShell's official
[Codex sandbox example](https://github.com/NVIDIA/OpenShell/blob/main/examples/agent-driven-policy-management/sandbox-agent.sh).

The configured `ai-guardian` MCP server is a local stdio process and therefore
does not need a network-policy endpoint. Codex's separate `codex_apps` remote
MCP, when enabled by Codex, does need its provider/profile endpoint and can be
allowed through the selected Codex policy.

OpenShell 0.0.116 does not allow `--upload` and a trailing canonical command in
the same `sandbox create` invocation. When a config, profile, repository, or
credential snapshot is needed, this command creates a named detached staging
sandbox, uploads the snapshot, and then explicitly invokes the image entrypoint
with `openshell sandbox exec`. This is required because detached OpenShell
creation starts its own shell instead of reliably running the image Docker
entrypoint. For `claude`, `codex`, `copilot`,
and `opencode` when the active gateway advertises a matching profile, the
sandbox command creates or reuses an `ai-guardian-<agent>` provider from existing
local credentials when `--provider` is not supplied. Pass `--provider NAME`
for an agent or gateway that does not advertise an automatic provider profile.

The default image build is pinned to the latest stable PyPI release at the
time the image definition is updated. At startup, the entrypoint checks the
installed package's advertised setup choices: integrations that exist only in
a newer development checkout are reported as skipped, while selecting one of
those integrations fails with a clear compatibility error.

When building this image from the development checkout, pass the wheel built
from the same checkout if you need unreleased setup behavior. The current
development package registers Codex's AI Guardian MCP server in
`$CODEX_HOME/config.toml`; older released packages may instead write the
legacy `codex.json` file in the working directory. `ai-guardian setup` installs
the MCP entry by default in both cases.

```bash
WHEEL_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ai-guardian-wheel.XXXXXX")"
uv build --wheel --out-dir "$WHEEL_DIR"
WHEEL_PATH="$(printf '%s\n' "$WHEEL_DIR"/ai_guardian-*.whl | head -n 1)"
WHEEL_NAME="$(basename "$WHEEL_PATH")"
cp "$WHEEL_PATH" "container/vendor/$WHEEL_NAME"
podman build \
    --build-arg "AI_GUARDIAN_VERSION=${WHEEL_NAME}" \
    -f container/Dockerfile.openshell \
    -t localhost/ai-guardian-openshell:latest container/
```

`WHEEL_PATH` includes the temporary build directory, while `WHEEL_NAME` is only
the filename. The `AI_GUARDIAN_VERSION` build argument must use `WHEEL_NAME`,
since the Dockerfile looks for the wheel by filename under `container/vendor/`.
Using a fresh output directory avoids accidentally selecting an older wheel
left in `dist/`.

#### OpenShell policy composition

OpenShell network access is deny-by-default. The repository keeps the policy
in composable pieces:

- `policies/base.yaml`: shared filesystem and Landlock restrictions.
- [Read-only main overlay](openshell-github-readonly-policy.yaml): GitHub REST reads
  and HTTPS `git clone`/`git fetch` only.
- [Read/write main overlay](openshell-github-readwrite-policy.yaml): GitHub REST operations and
  HTTPS `git clone`/`git fetch`/`git push`.
- `policies/agents/<agent>.yaml`: the network capability for the selected CLI.

When `--policy` is supplied, it may be repeated. The sandbox command always composes
one final policy in this order:

```text
policies/base.yaml
  + every --policy overlay (left to right)
  + policies/agents/<selected-cli>.yaml
```

Only the selected CLI fragment is added; the other CLI policies are not
enabled. YAML mappings are merged and lists are replaced by later overlays.
The resulting temporary file is passed as the single OpenShell `--policy`
argument and removed after OpenShell has consumed it. If no `--policy` overlay
is given, the result contains only the shared base policy and the selected
CLI policy; it does not grant GitHub API or Git access.

#### Bundled scanner engines

Both support images preinstall pinned Gitleaks, BetterLeaks, LeakTK,
detect-secrets, Secretlint, and the GitGuardian `ggshield` CLI. Their versions
come from the scanner configuration bundled with AI Guardian, so host, profile,
restored, and sandbox-local configurations can select them without startup
downloads or an OpenShell policy for downloading scanner binaries.

Secretlint scans locally. Using the GitGuardian engine sends scan data to its
cloud service and still requires configured consent and an API key; an
OpenShell sandbox also needs policy access to that service. Installing the CLI
in the image does not add runtime network access. Pattern-server access remains
governed by the selected configuration and policy.

TruffleHog is not included in the stock images. Its AGPL-3.0 installation path
requires interactive license acknowledgement, which cannot be collected during
an image build. A configuration that selects TruffleHog therefore cannot use it
in these images; use one of the bundled engines or provide it in a derived image
after reviewing and acknowledging its license. Custom scanner binaries and
Python scanner packages are outside the current pinned image set and must be
added to a derived image when needed.

The CLI fragments are intentionally conservative. Kiro and OpenClaw have no
single default LLM endpoint, while OpenCode and Crush support additional
providers beyond the examples in their fragments. Attach a compatible
OpenShell provider or add a custom policy overlay for those providers.

Providers v2 can add provider-owned credential and network-policy entries to
the effective sandbox policy, but only for providers attached to that
sandbox. See the official [Providers v2
guide](https://docs.nvidia.com/openshell/sandboxes/providers-v2). Do not attach
unrelated providers when a narrower sandbox is intended.

#### GitHub access and providers

Use it when creating a sandbox:

```bash
ai-guardian sandbox create --runtime openshell \
    --cli codex \
    --policy ./container/openshell-github-readonly-policy.yaml \
    --repo .
```

For a workflow that needs to create or update GitHub content, use the
read/write policy explicitly:

```bash
ai-guardian sandbox create --runtime openshell \
    --cli codex \
    --policy ./container/openshell-github-readwrite-policy.yaml \
    --provider ai-guardian-codex \
    --provider ai-guardian-github \
    --repo .
```

For private repositories, create an OpenShell GitHub provider from a host
token and attach it to the sandbox. The token is injected by OpenShell at
runtime; it is not stored in this policy file:

```bash
export GITHUB_TOKEN=<token-with-the-required-repository-access>
openshell provider create \
    --name ai-guardian-github \
    --type github \
    --from-existing

ai-guardian sandbox create --runtime openshell \
    --cli codex \
    --provider ai-guardian-codex \
    --provider ai-guardian-github \
    --policy ./container/openshell-github-readwrite-policy.yaml \
    --repo .
```

To apply the policy to an existing sandbox, use:

```bash
policy_tmp_dir="$(mktemp -d)"
python3 ./container/compose_openshell_policy.py \
    --output "${policy_tmp_dir}/policy.yaml" \
    ./container/policies/base.yaml \
    ./container/openshell-github-readwrite-policy.yaml \
    ./container/policies/agents/codex.yaml
openshell policy set <sandbox-name> \
    --policy "${policy_tmp_dir}/policy.yaml" \
    --wait
rm -rf -- "${policy_tmp_dir}"
```

When updating an existing sandbox, compose the selected-CLI policy first;
`openshell policy set` accepts one final YAML document and does not perform
the sandbox command-side composition automatically. The official [policy
customization guide](https://docs.nvidia.com/openshell/sandboxes/policies)
documents incremental updates and full policy replacement.

The read/write policy grants the network operations required by standard
GitHub API and HTTPS Git workflows, but the GitHub provider still controls
which repositories and account permissions are available. `--provider` is
repeatable; when Codex OAuth and private GitHub access are both needed, attach
both `ai-guardian-codex` and `ai-guardian-github` as shown above. For narrower
access, use the read-only policy or follow OpenShell's
[GitHub sandbox tutorial](https://docs.nvidia.com/openshell/get-started/tutorials/github-sandbox)
to tailor the allowed repositories and methods.

#### Daemon REST port and tray

The sandbox command exposes sandbox-local port `63152` as the gateway-managed
`ai-guardian` service. To inspect the service URL for one sandbox:

```bash
openshell service get ai-guardian-codex ai-guardian
```

The OpenShell network policy controls sandbox egress. The example policy
includes the bundled Codex egress endpoints; add the selected CLI's provider
endpoints when using another CLI. The gateway service handles access to the
daemon endpoint, and AI Guardian discovery asks the gateway for the URL of each
managed sandbox. No local forward-state directory or host-side forwarding
process is required.

```json
{
  "daemons": [
    {
      "name": "openshell-codex",
      "url": "http://127.0.0.1:63152",
      "token": "the-daemon-auth-token"
    }
  ]
}
```

Save this as `$HOME/.config/ai-guardian/tray-targets.json` (or the active
ai-guardian config directory) and start the tray normally. `/api/health` is
unauthenticated, but status and control operations require the daemon token.
The forwarded port is the daemon REST API, not a NiceGUI page: check it with
`/api/health`; the NiceGUI console runs on the host and uses this endpoint
through the tray client. For a stable tray connection, set
`daemon.auth_token` in the shared config snapshot and use the same token in a
manual target. Use HTTPS rather than plain HTTP when the daemon is reachable
beyond loopback.

<details>
<summary>Manual container run (podman / docker)</summary>

```bash
# Default (Codex hooks)
podman run -it -p 63152 ai-guardian

# Select agent
podman run -it -p 63152 -e AI_GUARDIAN_AGENT=opencode ai-guardian opencode

# Seed the sandbox config from the host when no sandbox-local config exists
podman run -it -p 63152 \
    -v "$HOME/.config/ai-guardian/ai-guardian.json:/sandbox/.config/ai-guardian.host.json:ro,z" \
    -e AI_GUARDIAN_HOST_CONFIG_MOUNTED=true \
    -e AI_GUARDIAN_HOST_CONFIG_PATH=/sandbox/.config/ai-guardian.host.json \
    ai-guardian

# Select configuration profile
podman run -it -p 63152 -e AI_GUARDIAN_PROFILE=@strict ai-guardian

# Authenticate with Anthropic API
podman run -it -p 63152 -e ANTHROPIC_API_KEY=sk-ant-... ai-guardian

# Authenticate with Vertex AI
podman run -it -p 63152 \
    -e CLAUDE_CODE_USE_VERTEX=1 \
    -e ANTHROPIC_VERTEX_PROJECT_ID=my-gcp-project \
    -e CLOUD_ML_REGION=global \
    -e GOOGLE_APPLICATION_CREDENTIALS=/sandbox/gcp-key.json \
    -v ~/gcp-key.json:/sandbox/gcp-key.json:ro \
    ai-guardian

# Mount a repo to test
podman run -it -p 63152 -v ~/myrepo:/sandbox/repo ai-guardian

# Run doctor
podman run -it ai-guardian ai-guardian doctor
```

</details>

## Container Engine

By default, `run.sh` uses Podman. To use Docker instead:

```bash
CONTAINER_ENGINE=docker ./container/run.sh
# or export for the session:
export CONTAINER_ENGINE=docker
./container/run.sh --ide claude
```

Both engines support the same `-p` syntax for port mapping. Use `docker port <container>` (instead of `podman port`) to find the mapped host port when using Docker.

## Agent Selection

Set `AI_GUARDIAN_AGENT` (or compatibility alias `AI_GUARDIAN_IDE`) to choose
which CLI/agent command is started. All rows are configured at startup:

| Value | Agent | Installed in image |
|-------|-------|--------------------|
| `codex` (default) | OpenAI Codex (CLI + Desktop) | Yes |
| `claude` | Claude Code | **Runtime — ToS consent** |
| `opencode` | OpenCode | Yes |
| `gemini` | Gemini CLI | Yes |
| `kiro` | Kiro CLI | **Runtime — ToS consent** |
| `openclaw` | OpenClaw | Yes |
| `crush` | Crush | No (hooks only; license/packaging varies) |
| `cursor` | Cursor | No (hooks only) |
| `copilot` | GitHub Copilot | No (hooks only) |
| `windsurf` | Windsurf | No (hooks only) |
| `augment` | Augment | No (hooks only) |
| `cline` | Cline | No (hooks only) |
| `zoocode` | ZooCode | No (hooks only) |
| `junie` | Junie | No (hooks only) |
| `aiderdesk` | AiderDesk | No (hooks only) |
| `dummy-agent` | Dummy Agent (fake IDE for hook testing) | Yes — no LLM required |

Agents marked "hooks only" are not installed in the image (they require a GUI
or are not redistributed here), but ai-guardian hooks are configured for them.
Mount or install an agent binary separately if needed.

## Proprietary CLI Consent

Claude Code (Anthropic) and Kiro CLI (AWS) are proprietary with redistribution
restrictions. They are not bundled in the image. When `AI_GUARDIAN_AGENT=claude`
or `AI_GUARDIAN_AGENT=kiro` is selected, the container prompts for ToS
acceptance at first start and installs the CLI if the user agrees.

### Interactive (default)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Claude Code requires accepting its Terms of Service:
  https://www.anthropic.com/legal/consumer-terms
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Install Claude Code and accept the ToS? [y/N]
```

Answer `y` to install, `N` (or Enter) to skip.

### Non-interactive / CI

Set `ACCEPT_PROPRIETARY_TOS=true` to bypass the prompt and install
automatically. By setting this variable you confirm you have read and accept
the relevant Terms of Service.

```bash
# Claude Code — non-interactive
podman run -it -p 63152 \
    -e ACCEPT_PROPRIETARY_TOS=true \
    -e ANTHROPIC_API_KEY=sk-ant-... \
    quay.io/redhatproductsecurity/ai-guardian:latest

# Kiro CLI — non-interactive
podman run -it -p 63152 \
    -e AI_GUARDIAN_AGENT=kiro \
    -e ACCEPT_PROPRIETARY_TOS=true \
    quay.io/redhatproductsecurity/ai-guardian:latest kiro
```

The `run.sh` helper passes `ACCEPT_PROPRIETARY_TOS` through from the host
environment automatically if it is set.

### Already installed

If the binary is already present in `$HOME/.local/bin/` (e.g. from a mounted
volume), the consent prompt is skipped.

## Configuration and Profiles

With no profile selected, `run.sh` checks the host configuration directory and
stages only `ai-guardian.json` as the initial snapshot when it exists. The
image keeps all other XDG state, cache, scanner, and agent directories
sandbox-local. If a sandbox-local config already exists, it wins and is not
overwritten. If the host file is absent, startup creates a sandbox-local
configuration.

Set `AI_GUARDIAN_PROFILE` or pass `--profile` to apply a security profile at
container start. Profile mode never mounts the host's complete config:

| Value | Description |
|-------|-------------|
| (unset) | Use an existing sandbox-local config; otherwise copy the host config as a writable initial snapshot, or create a sandbox-local standard config |
| `@minimal` | Minimal — fewer checks, lower false positive rate |
| `@standard` | Standard — balanced security and usability |
| `@strict` | Strict — maximum security, all checks enabled |
| `@moderator` | Moderator — all scanner actions set to `ask` for human-in-the-loop review |

You can also pass a custom profile name or path if you have saved custom profiles.

The host config directory is selected in this order:

1. `--config-dir` (or `--guardian-home`)
2. `AI_GUARDIAN_CONFIG_DIR`
3. `AI_GUARDIAN_HOME`
4. `XDG_CONFIG_HOME/ai-guardian`
5. `HOME/.config/ai-guardian`

When `HOME` is not exported, the sandbox command can infer its parent from a
supported agent home variable such as `CODEX_HOME`, `CLAUDE_CONFIG_DIR`,
`CURSOR_CONFIG_DIR`, `GEMINI_CLI_HOME`, `KIRO_HOME`, `JUNIE_HOME`, or
`OPENCODE_CONFIG_DIR`. These variables are used only to locate the host
ai-guardian config; agent homes and caches are not mounted into the sandbox.

If a custom profile file is given, it is mounted read-only by `run.sh` at a
sandbox-local profile path. A missing explicit profile file is an error. A
missing host `ai-guardian.json` is not an error when no profile is selected;
the sandbox command reports the fallback and creates a local config. `--profile` and
host-config sharing are mutually exclusive. When the host config is effective,
the sandbox edits its own copy; the TUI, NiceGUI, and REST config APIs never
write back to the host file.

## Authentication

Pass authentication credentials as environment variables at runtime. The
normal Docker/Podman image does not mount or read the host `~/.codex` directory,
so Codex ChatGPT/OAuth login is performed inside the sandbox rather than being
inherited automatically.

`run.sh` forwards the common agent variables (`OPENAI_API_KEY`,
`OPENROUTER_API_KEY`, `GEMINI_API_KEY`, AWS Bedrock variables, Azure OpenAI
variables, and the existing Anthropic/Vertex variables). Both `run.sh` and
`ai-guardian sandbox create --runtime container` detect Vertex settings and
mount the host ADC file read-only when it is available. The OpenShell sandbox
command relies on OpenShell providers for credentials: its `--api-key` option
is used only while creating an Anthropic provider, and Vertex ADC credentials
are consumed while creating the `google-vertex-ai` provider. Neither provider
credential value nor the ADC file is passed to the OpenShell sandbox.

When both an Anthropic API-key environment variable and Vertex project
settings are present, the container launchers select Vertex and omit the
inherited API key. Pass `--api-key` explicitly when direct Anthropic
authentication is intended.

### Codex CLI in a Docker/Podman sandbox

For a named sandbox, connect to it and authenticate Codex from inside:

```bash
ai-guardian sandbox create \
    --runtime container \
    --name guardian-codex \
    --cli codex \
    --repo .
ai-guardian sandbox connect guardian-codex

# Inside the container:
codex login
```

On a headless container, `codex login --device-auth` requires device-code
authorization to be enabled in ChatGPT's **Settings → Security**. If that
option is unavailable, use a real OpenAI Platform API key:

```bash
export OPENAI_API_KEY="<your-openai-api-key>"
ai-guardian sandbox create \
    --runtime container \
    --name guardian-codex \
    --cli codex \
    --repo .
ai-guardian sandbox connect guardian-codex

# Inside the container:
printenv OPENAI_API_KEY | codex login --with-api-key
```

`auth.json` from a ChatGPT OAuth login contains OAuth credentials, not a
Platform API key. Do not paste its access or refresh token into the API-key
login. If necessary, the user can authenticate on a host with a browser and
manually copy the complete file into a persistent named container:

```bash
podman cp ~/.codex/auth.json guardian-codex:/sandbox/.codex/auth.json
```

Use `docker cp` with Docker. AI Guardian does not inspect this file, but it is
then present inside the sandbox; treat it like a password and never commit or
share it. The detailed container-sandbox flow is also documented in the
[Sandbox CLI guide](../docs/Sandbox.md#codex-authentication-in-container-sandboxes).

> **Tested configurations:** Anthropic API key and Google Vertex AI have been
> validated with this image. Other providers (AWS Bedrock, Azure, self-hosted)
> may require additional environment variables or volume mounts — consult the
> IDE's documentation for the required configuration.

### Anthropic API (direct)

```bash
podman run -it -p 63152 \
    -e ANTHROPIC_API_KEY=sk-ant-... \
    ai-guardian
```

### Google Vertex AI ✓ tested

```bash
podman run -it -p 63152 \
    -e CLAUDE_CODE_USE_VERTEX=1 \
    -e ANTHROPIC_VERTEX_PROJECT_ID=my-gcp-project \
    -e CLOUD_ML_REGION=global \
    -e GOOGLE_APPLICATION_CREDENTIALS=/sandbox/gcp-key.json \
    -v ~/my-gcp-key.json:/sandbox/gcp-key.json:ro \
    ai-guardian
```

### Other providers (untested)

Other Claude-compatible providers may work by passing the appropriate env vars.
The container does not pre-configure any provider-specific tooling beyond
Claude Code, so extra setup (CLI login, credential files, proxy config) may be
needed inside the container after startup.

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key (direct API access) |
| `CLAUDE_CODE_USE_VERTEX` | Set to `1` to use Google Vertex AI |
| `ANTHROPIC_VERTEX_PROJECT_ID` | GCP project ID (with Vertex AI) |
| `CLOUD_ML_REGION` | GCP region, e.g. `global` (with Vertex AI) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to GCP service account JSON key file (with Vertex AI) |

## Web Console

The ai-guardian daemon starts automatically and binds to `0.0.0.0` inside the
container (auto-detected via `/.dockerenv` / `/run/.containerenv`).

Access from the host: `http://localhost:63152`

## Build Args

| Arg | Default | Description |
|-----|---------|-------------|
| `AI_GUARDIAN_VERSION` | `1.17.1` | PyPI version or `.whl` filename |
| `AI_GUARDIAN_REST_PORT` | `63152` | Daemon REST API / web console port |
| `UV_VERSION` | `0.11.16` | uv package manager version |
| `OPENCODE_VERSION` | `1.17.3` | OpenCode version for the normal image |

## Test Image (Dockerfile.test)

The test image extends the base image with bundled dummy-agent scenarios for hook regression testing. Not for distribution — local CI only.

### Build

```bash
# Build base image first
podman build -t ai-guardian container/

# Build test image on top
podman build -f container/Dockerfile.test -t ai-guardian-test container/
```

### Run

```bash
# Run all bundled scenarios (CI mode)
podman run --rm ai-guardian-test /sandbox/run-scenarios.sh

# Run a specific scenario
podman run --rm ai-guardian-test \
  ai-guardian dummy-agent --script /sandbox/scenarios/basic-secret.yaml

# Interactive REPL
podman run -it ai-guardian-test ai-guardian dummy-agent
```

### Bundled scenarios

| Scenario | What it tests |
|---|---|
| `basic-secret.yaml` | AWS key detection → block |
| `pii-detection.yaml` | Credit card, passport detection |
| `ask-dialog.yaml` | Ask dialog forwarding to tray |
| `tool-policy.yaml` | Directory rules, tool blocking |

## Expected Doctor Warnings

In a container, `ai-guardian doctor` will show expected warnings for:

- **System tray**: Not available (no display server)
- **Terminal emulator**: Not detected (no desktop)
- **tkinter**: Not installed (no GUI needed)

All security-critical checks (config, hooks, scanners, daemon) should pass.
