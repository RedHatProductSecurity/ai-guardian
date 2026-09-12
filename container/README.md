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
change to the image; `openshell.sh` uses the published OpenShell image by
default. The OpenShell image is not published in the normal image repository
or mirrored to the legacy `itdove` repository.
The normal UBI image remains published to
[quay.io/redhatproductsecurity/ai-guardian](https://quay.io/redhatproductsecurity/ai-guardian)
on every merge and release.

## What's Included

| Component | License | Installed |
|-----------|---------|-----------|
| ai-guardian | Apache 2.0 | Build time |
| gitleaks, betterleaks | MIT / Apache 2.0 | Build time |
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

# Local wheel (copy wheel into container/ first)
cp dist/ai_guardian-1.17.1-py3-none-any.whl container/vendor/
podman build --build-arg AI_GUARDIAN_VERSION=ai_guardian-1.17.1-py3-none-any.whl \
    -t ai-guardian container/

# Multi-arch
podman build --platform linux/amd64,linux/arm64 -t ai-guardian container/

# Dedicated OpenShell BYOC image (the launcher uses the published image by default)
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

At startup the launcher configures only the selected `--agent`; configuring
other integrations is unnecessary when the sandbox runs one CLI. `--ide`
remains an alias for `--agent`. To opt into broader setup, set
`AI_GUARDIAN_SETUP_SCOPE=cli` for all supported CLI agents or
`AI_GUARDIAN_SETUP_SCOPE=all` for every supported integration.

### OpenShell

The OpenShell launcher uses the dedicated `Dockerfile.openshell` image rather
than the normal UBI image. Build it once from the repository root:

The normal `run.sh` container still defaults to Codex. The OpenShell launcher
defaults to Claude, matching OpenShell's first-class default-policy coverage;
select another agent explicitly with `--agent`.

```bash
podman build -f container/Dockerfile.openshell \
    -t localhost/ai-guardian-openshell:latest container/
```

To use that local build for one run, pass it explicitly:

```bash
./container/openshell.sh --base localhost/ai-guardian-openshell:latest
```

The published image can be pulled explicitly as well:

```bash
podman pull quay.io/redhatproductsecurity/ai-guardian-openshell:latest
```

Set `AI_GUARDIAN_OPEN_SHELL_IMAGE` to use another OpenShell-compatible image,
or pass `--base IMAGE`/`--image IMAGE` on one invocation. The explicit
`AI_GUARDIAN_IMAGE` variable remains the highest-priority image override. The
launcher uses the OpenShell-supported `--from`, `--env`, and `--upload` options,
then uses `openshell forward service` to map the host port to the daemon's
sandbox-local REST port.

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
| `OPENCODE_VERSION` | `opencode-ai` | `1.18.30` |

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
    --build-arg OPENCODE_VERSION=1.18.30 \
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

./container/openshell.sh \
    --base localhost/ai-guardian-openshell:dev \
    --agent codex \
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

The launcher requires an OpenShell CLI and gateway new enough to support
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
retrying the launcher:

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

```bash
./container/openshell.sh                             # opens a shell; Claude is selected
./container/openshell.sh --agent opencode --repo .
./container/openshell.sh --profile @strict --policy ./container/openshell-github-readwrite-policy.yaml
./container/openshell.sh --config-dir "$HOME/.config/ai-guardian"
```

The OpenShell launcher opens `/bin/bash` by default. When `--repo` is supplied,
the shell starts in the uploaded repository at `/sandbox/repo`; otherwise it
starts in `/sandbox`. The selected `--agent` controls ai-guardian setup and
automatic provider selection. When a `--policy` overlay is supplied, it also
selects the matching agent policy fragment. Without an overlay, the launcher
still applies the shared base policy and the selected agent policy, but no
GitHub policy is added. The launcher does not start the CLI automatically.

Provider profiles belong to the active OpenShell gateway; they are not stored
in the repository, image, or Git branch. When `--provider` is omitted, the
launcher asks that gateway for a provider profile matching the selected agent
and may create or reuse the corresponding `ai-guardian-<agent>` provider from
local credentials. If the gateway does not advertise a Codex profile, a
launch with the default `--agent codex` fails with an error such as “the active
OpenShell gateway has no provider profile for codex.” Configure a Codex
provider on that gateway first, or pass an already configured provider
explicitly:

```bash
./container/openshell.sh \
    --base localhost/ai-guardian-openshell:latest \
    --agent codex \
    --provider ai-guardian-codex \
    --repo .
```

Use `openshell provider get ai-guardian-codex` to verify that the named
provider exists on the currently active gateway. Provider setup must be
repeated for each gateway or laptop; `git pull` only updates the launcher and
policy files.

The `--provider` option is lookup-only: it attaches an existing provider
instance and does not create one. To let the launcher create
`ai-guardian-codex` from local Codex credentials, omit `--provider` and ensure
the active gateway lists the `codex` profile:

```bash
openshell provider list-profiles
./container/openshell.sh \
    --base localhost/ai-guardian-openshell:latest \
    --agent codex \
    --repo .
```

Provider creation requires a matching gateway profile and credentials
available to the launcher. If `codex` is absent from `list-profiles`, update or
reconfigure the active OpenShell gateway before retrying.

```bash
./container/openshell.sh \
    --agent codex \
    --policy ./container/openshell-github-readwrite-policy.yaml \
    --provider ai-guardian-codex \
    --provider ai-guardian-github \
    --repo .
```

The launcher runs setup before opening the shell. You can launch the selected
agent from that shell; when the agent exits, you return to the shell and can
inspect, commit, and push changes. The repository is still an OpenShell
snapshot, so commits and other file changes are made in the sandbox copy. With
the read/write GitHub policy and an attached GitHub provider, `git push` goes
to GitHub through the gateway; it does not modify the host checkout. To launch
the selected agent immediately instead, pass it after `--`, for example
`-- codex`.

From the shell, launch and exit the selected CLI as often as needed:

```bash
codex
git status
git add .
git commit -m "Your change"
git push
```

The OpenShell launcher defaults to `--port 0`. OpenShell selects one free host
port through `openshell forward service --local 127.0.0.1:0` and forwards it to
the daemon's sandbox-local port `63152`; the assigned host port is printed in
the startup output. Pass `--port N` to force a specific host port.
Forwarding is enabled by default because it is the channel used by the host
tray and NiceGUI to manage the sandbox daemon.

When the host UI is not needed, disable that host-local REST listener:

```bash
./container/openshell.sh --no-forward
AI_GUARDIAN_OPEN_SHELL_FORWARD=false ./container/openshell.sh
```

The sandbox daemon still runs, but its REST API is not forwarded to the host
and the tray/NiceGUI cannot discover or manage that sandbox. With forwarding
disabled and no explicit `--port`, the daemon uses sandbox-local port `63152`.

#### Claude Code with Google Vertex AI

To run Claude Code through Google Vertex AI, select Claude and provide a GCP
project. The launcher automatically creates or reuses the gateway-local
`ai-guardian-google-vertex-ai` provider; no GitHub policy is needed:

```bash
export ANTHROPIC_VERTEX_PROJECT_ID=my-gcp-project
export CLOUD_ML_REGION=global

./container/openshell.sh \
    --agent claude \
    --repo .
```

No separate Claude-Vertex policy file is required. The selected Claude agent
policy covers Claude Code, while the `google-vertex-ai` provider supplies the
Vertex endpoint and credential binding. Providers v2 must be enabled on the
active gateway so the provider-owned network policy is included:

```bash
openshell settings set --global --key providers_v2_enabled --value true
```

The launcher uses Google Application Default Credentials (ADC) while creating
the provider. Set `GOOGLE_APPLICATION_CREDENTIALS` to a service-account JSON
file when it is not at the standard gcloud ADC location, or authenticate with
gcloud first. The credential file is consumed for provider creation and is not
uploaded into the sandbox:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-credentials.json
export ANTHROPIC_VERTEX_PROJECT_ID=my-gcp-project
export CLOUD_ML_REGION=global

./container/openshell.sh --agent claude --repo .
```

The active gateway must expose the `google-vertex-ai` provider profile. If the
launcher reports that the profile is missing, update or reconfigure the
active OpenShell gateway. For direct Anthropic access instead, use
`ANTHROPIC_API_KEY` and omit the Vertex project variables.

OpenShell discovers common agent credentials through its provider mechanism.
An existing host `ai-guardian.json` is uploaded as a sandbox-local snapshot
when no profile is selected; the host file is never written. A selected
profile always takes precedence and prevents that full-config upload. Unlike
the Docker/Podman launcher, OpenShell's `--upload` is a snapshot rather than a
live read-only bind mount.

Agent credential directories are deliberately not mounted or uploaded. For
Codex, the launcher reads `$CODEX_HOME/auth.json` (falling back to
`$HOME/.codex/auth.json`) only while creating the OpenShell provider, and
passes the OAuth fields to the provider command without printing them. The
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

If Codex still shows the sign-in menu, the provider-backed auth bootstrap was
not available to that process. Start a fresh sandbox with this launcher rather
than launching `codex` from an unrelated shell, and verify that
`openshell provider get ai-guardian-codex` reports the four Codex OAuth
credential keys. Do not copy the host `auth.json` into the sandbox.

When Providers v2 is unset or disabled, OpenShell 0.0.116 falls back to legacy
`codex` discovery, which only recognizes `OPENAI_API_KEY`; the launcher reports
this prerequisite instead of asking for an API key that is not needed by a
Codex OAuth login. If the profile is unavailable, use an explicit compatible
provider with `--provider NAME`.

Codex also needs a writable local state database before it can display its
prompt. The launcher sets `CODEX_HOME=/sandbox/.codex` and initializes that
directory. The OpenShell policy gives `/sandbox` to the sandbox user, and
keeping Codex state there also lets Codex create its helper binaries instead
of rejecting them as temporary `/tmp` files. If you connect to the sandbox and
run `codex` manually, run the launcher first so this environment and directory
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
credential snapshot is needed, this launcher creates a named detached staging
sandbox, uploads the snapshot, and then explicitly invokes the image entrypoint
with `openshell sandbox exec`. This is required because detached OpenShell
creation starts its own shell instead of reliably running the image Docker
entrypoint. For `claude`, `codex`, `copilot`,
and `opencode` when the active gateway advertises a matching profile, the
launcher creates or reuses an `ai-guardian-<agent>` provider from existing
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
uv build --wheel
cp dist/ai_guardian-*.whl container/vendor/
podman build \
    --build-arg AI_GUARDIAN_VERSION=ai_guardian-1.18.0.dev0-py3-none-any.whl \
    -f container/Dockerfile.openshell \
    -t localhost/ai-guardian-openshell:latest container/
```

#### OpenShell policy composition

OpenShell network access is deny-by-default. The repository keeps the policy
in composable pieces:

- `policies/base.yaml`: shared filesystem and Landlock restrictions.
- [Read-only main overlay](openshell-github-readonly-policy.yaml): GitHub REST reads
  and HTTPS `git clone`/`git fetch` only.
- [Read/write main overlay](openshell-github-readwrite-policy.yaml): GitHub REST operations and
  HTTPS `git clone`/`git fetch`/`git push`.
- `policies/agents/<agent>.yaml`: the network capability for the selected CLI.

When `--policy` is supplied, it may be repeated. The launcher always composes
one final policy in this order:

```text
policies/base.yaml
  + every --policy overlay (left to right)
  + policies/agents/<selected-agent>.yaml
```

Only the selected agent fragment is added; the other agent policies are not
enabled. YAML mappings are merged and lists are replaced by later overlays.
The resulting temporary file is passed as the single OpenShell `--policy`
argument and removed after OpenShell has consumed it. If no `--policy` overlay
is given, the result contains only the shared base policy and the selected
agent policy; it does not grant GitHub access.

The agent fragments are intentionally conservative. Kiro and OpenClaw have no
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
./container/openshell.sh \
    --agent codex \
    --policy ./container/openshell-github-readonly-policy.yaml \
    --repo .
```

For a workflow that needs to create or update GitHub content, use the
read/write policy explicitly:

```bash
./container/openshell.sh \
    --agent codex \
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

./container/openshell.sh \
    --agent codex \
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

When updating an existing sandbox, compose the selected-agent policy first;
`openshell policy set` accepts one final YAML document and does not perform
the launcher-side composition automatically. The official [policy
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

The launcher uses `openshell forward service --target-port 63152` for the
daemon REST port. By default it passes `--local 127.0.0.1:0`, allowing OpenShell
to select a free host port; that host port is mapped to sandbox-local port
`63152` and printed in the startup output. To use a stable host port for a tray
target, pass it explicitly:

```bash
./container/openshell.sh --name ai-guardian-codex --port 63152
curl http://127.0.0.1:63152/api/health
```

The OpenShell network policy controls sandbox egress. The example policy
includes the bundled Codex egress endpoints; add the selected agent's provider
endpoints when using another agent. The policy does not need an ingress rule
for the forwarded daemon port. The launcher records each assigned local
`forward service` port under
`$XDG_RUNTIME_DIR/ai-guardian/openshell-forwards` (or the AI Guardian state
directory when no runtime directory is available), because OpenShell does not
list these service forwards in `openshell forward list`. AI Guardian discovery
uses that record only while its forward process is alive. Add a manual target
when using a remote gateway, a host without the launcher state directory, or a
forward that is not running. A sandbox started with `--no-forward` is
intentionally unavailable to the host tray/NiceGUI until it is recreated with
forwarding enabled:

If the tray/NiceGUI runs with a different XDG runtime environment, point both
processes at the same directory with
`AI_GUARDIAN_OPEN_SHELL_FORWARD_STATE_DIR=/path/to/forward-state`.

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

# Keep the host config file read-only and file-only
podman run -it -p 63152 \
    -v "$HOME/.config/ai-guardian/ai-guardian.json:/sandbox/.config/ai-guardian/ai-guardian.json:ro" \
    -e AI_GUARDIAN_HOST_CONFIG_MOUNTED=true \
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
mounts only `ai-guardian.json` read-only when it exists. The image keeps all
other XDG state, cache, scanner, and agent directories sandbox-local. If the
host file is absent, startup creates a sandbox-local configuration.

Set `AI_GUARDIAN_PROFILE` or pass `--profile` to apply a security profile at
container start. Profile mode never mounts the host's complete config:

| Value | Description |
|-------|-------------|
| (unset) | Use the host config if present; otherwise create a sandbox-local standard config |
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

When `HOME` is not exported, the launcher can infer its parent from a
supported agent home variable such as `CODEX_HOME`, `CLAUDE_CONFIG_DIR`,
`CURSOR_CONFIG_DIR`, `GEMINI_CLI_HOME`, `KIRO_HOME`, `JUNIE_HOME`, or
`OPENCODE_CONFIG_DIR`. These variables are used only to locate the host
ai-guardian config; agent homes and caches are not mounted into the sandbox.

If a custom profile file is given, it is mounted read-only by `run.sh` at a
sandbox-local profile path. A missing explicit profile file is an error. A
missing host `ai-guardian.json` is not an error when no profile is selected;
the launcher reports the fallback and creates a local config. `--profile` and
host-config sharing are mutually exclusive.

## Authentication

Pass authentication credentials as environment variables at runtime.

`run.sh` forwards the common agent variables (`OPENAI_API_KEY`,
`OPENROUTER_API_KEY`, `GEMINI_API_KEY`, AWS Bedrock variables, Azure OpenAI
variables, and the existing Anthropic/Vertex variables) without mounting any
agent home directory. The OpenShell launcher relies on OpenShell providers for
credentials: its `--api-key` option is used only while creating an Anthropic
provider, and Vertex ADC credentials are consumed while creating the
`google-vertex-ai` provider. Neither credential value nor the ADC file is
passed to the sandbox.

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
