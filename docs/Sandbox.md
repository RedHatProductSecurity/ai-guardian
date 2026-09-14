# Sandbox CLI

The `ai-guardian sandbox` command manages named AI Guardian sandboxes across
Docker/Podman and NVIDIA OpenShell. Container creation is detached; OpenShell
creation opens an independent interactive shell after setup, matching native
OpenShell behavior while leaving the sandbox available after the shell exits.
Create a sandbox once, then inspect, stop, start, connect to, execute commands
in, stream logs from, or delete it in later shell sessions.

The command is the supported entry point for both lifecycle management and
initial sandbox setup. It composes the OpenShell baseline and selected-agent
policies, prepares gateway providers when required, handles configuration and
repository snapshots, and exposes the daemon through an OpenShell gateway
service endpoint when that runtime is selected.
The tray and web console authenticate this service with a dedicated token
header as well as the standard Bearer header because some OpenShell gateway
versions remove `Authorization` while proxying a service.

## Prerequisites

- For `--runtime container`, install Docker or Podman. The command uses
  `CONTAINER_ENGINE` when set, otherwise it defaults to `podman`.
- For `--runtime openshell`, install the OpenShell CLI and connect it to an
  OpenShell gateway. The command uses `OPENSHELL_CLI` when set, otherwise it
  invokes `openshell`.
- The default images are
  `quay.io/redhatproductsecurity/ai-guardian:latest` for containers and
  `quay.io/redhatproductsecurity/ai-guardian-openshell:latest` for OpenShell.
  Select another image with `--image`.
- OpenShell creation composes `container/policies/base.yaml`, the selected
  agent fragment, and any files passed with `--policy`. Installed wheels carry
  these policy assets with the CLI.

OpenShell installation and gateway setup are documented in the official
[OpenShell quickstart](https://docs.nvidia.com/openshell/get-started/quickstart).

On Linux, rootless Podman discovery requires its user socket:

```bash
systemctl --user enable --now podman.socket
```

`podman.service` being `inactive (dead)` is normal when socket activation is in
use; the socket starts the service on demand. Some Podman Desktop versions can
temporarily disconnect or recreate this API socket when the UI closes. The
tray retries discovery and keeps the last-known container targets visible with
an unknown status while the socket is unavailable. If the socket path is
non-standard, set `DOCKER_HOST` to the path reported by
`podman info --format '{{.Host.RemoteSocket.Path}}'`. The tray does not enable
or restart the user service automatically because that is platform- and
user-session-specific.

## Quick start

Create and manage a Docker/Podman sandbox:

```bash
ai-guardian sandbox create --runtime container --name guardian-codex --repo .
ai-guardian sandbox list
ai-guardian sandbox status guardian-codex
ai-guardian sandbox connect guardian-codex
ai-guardian sandbox exec guardian-codex -- ai-guardian doctor
ai-guardian sandbox logs guardian-codex --follow
ai-guardian sandbox config save guardian-codex
ai-guardian sandbox stop guardian-codex
ai-guardian sandbox start guardian-codex
ai-guardian sandbox delete guardian-codex
```

Create and manage an OpenShell sandbox:

```bash
ai-guardian sandbox create --runtime openshell --name guardian-claude --agent claude
ai-guardian sandbox status guardian-claude
ai-guardian sandbox connect guardian-claude
ai-guardian sandbox exec guardian-claude -- /bin/bash
ai-guardian sandbox logs guardian-claude --follow
ai-guardian sandbox config save guardian-claude
ai-guardian sandbox delete guardian-claude
```

The runtime option is optional for lifecycle commands. When supplied, it may
appear before or after the lifecycle verb:

```bash
ai-guardian sandbox --runtime openshell list
ai-guardian sandbox status guardian-claude
```

The runtime must be selected explicitly for `create`. For lifecycle commands
with a name, omit `--runtime` and the command probes the AI Guardian
labels/metadata to select Docker/Podman or OpenShell. If no runtime is supplied
to `list`, it lists managed sandboxes from both runtimes.
`AI_GUARDIAN_SANDBOX_RUNTIME` can still provide the runtime selection when
needed.

## Tray controls

The tray's main menu contains `Create sandbox...`. Creation runs through the
same Python sandbox implementation as the CLI, without opening a terminal;
success is reported with a desktop notification and failures show the
captured runtime log in a modal. After a container or OpenShell sandbox is
discovered, its target menu contains `Manage sandbox` with `Status`, `Start`,
`Stop`, `Restart`, `Exec`, `Logs`, and `Delete`. For ordinary containers, the
`Manage sandbox` submenu also contains `Connect`; OpenShell uses the
top-level `Connect` action described below.
Discovery already provides the complete list of managed sandboxes, so there is
no redundant per-target `List sandboxes` action. Configuration snapshots are grouped under
`Manage sandbox -> Config`, with `Save`, `List`, and `Restore` actions. The
`Delete...` action opens an isolated confirmation modal and requires typing the
exact sandbox name before deletion. Host configuration snapshots are retained.

Status, start, stop, restart, and configuration actions run through the same
Python implementation as the CLI. Status and configuration output, together
with failures from any of these actions, is shown in a scrollable modal rather
than an empty terminal; the modal includes a `Copy` button for the captured
text. `Connect`, `Exec`, and followed `Logs` remain terminal
actions because they are interactive or streaming sessions; one-shot `Logs`
output uses the same log modal.

The `Create sandbox...` form includes folder browsers for the repository and
host configuration directory, plus an optional `Policy files` browser for
OpenShell creation. It also exposes providers, the Vertex inference model,
runtime labels, and additional `KEY=VALUE` environment entries. The policy
chooser supports multiple files; manual entry uses comma-separated paths
(pasted newline-separated paths are also accepted). Each path is passed as a
repeatable `--policy` option. Runtime-specific fields are disabled when the
container runtime is selected. Secret `--api-key` values remain a CLI/env
option rather than being put into the tray form payload. Stopped
container-engine sandboxes, including OpenShell sandboxes, appear in the main
menu under `Start stopped sandbox...`.

## OpenShell command mappings

Most lifecycle operations below are deliberately thin aliases of the native
OpenShell CLI. `connect` is intentionally mapped to an independent interactive
`exec` session: native `openshell sandbox connect` can attach to the sandbox's
main process, so exiting it may terminate the sandbox in some OpenShell
versions. `start` and `restart` additionally ensure the AI Guardian daemon and
gateway service are available; `delete` removes that service before deleting
the native sandbox.

| AI Guardian command | Native OpenShell command |
| --- | --- |
| `ai-guardian sandbox status NAME` | `openshell sandbox get NAME` |
| `ai-guardian sandbox start NAME` | `openshell sandbox start NAME` |
| `ai-guardian sandbox stop NAME` | `openshell sandbox stop NAME` |
| `ai-guardian sandbox connect NAME` | `openshell sandbox exec --name NAME --tty -- /bin/bash -l` |
| `ai-guardian sandbox delete NAME` | `openshell sandbox delete NAME` |
| `ai-guardian sandbox exec NAME -- CMD` | `openshell sandbox exec --name NAME -- CMD` |
| `ai-guardian sandbox logs NAME` | `openshell logs NAME` |

`sandbox restart` is a convenience sequence that runs native `stop` followed
by native `start`; for OpenShell it also ensures that the AI Guardian daemon is
running after the sandbox process is relaunched. OpenShell's lifecycle
documentation does not define a separate restart subcommand; see [Manage
Sandboxes](https://docs.nvidia.com/openshell/sandboxes/manage-sandboxes).

`sandbox create` is not a plain alias: it adds the AI Guardian image, managed
labels, agent environment, optional repository/config uploads, providers,
policies, and the gateway-managed AI Guardian service. `sandbox list` is also
intentionally scoped to
resources carrying the `ai-guardian.managed=true` label.

When `--name` is supplied, the command records that name in the runtime
metadata. The tray and NiceGUI prefer this stable sandbox name over a daemon
hostname that may otherwise be reported as a container ID. Existing OpenShell
sandboxes also use their `openshell.ai/sandbox-name` metadata when available.

For OpenShell log filtering, `--source`, `--level`, and `--since` are forwarded
to `openshell logs`. `--follow` selects OpenShell's streaming `--tail` mode.

## Create options

Common options for `sandbox create` are:

| Option | Purpose |
| --- | --- |
| `--name NAME` | Assign a stable runtime name. |
| `--runtime {container,openshell}` | Select Docker/Podman or OpenShell. Required to choose the runtime explicitly when creating; lifecycle commands auto-detect it by name when omitted. |
| `--container-engine COMMAND` | Override the Docker/Podman executable for this invocation; defaults to `$CONTAINER_ENGINE` or `podman`. |
| `--openshell-cli COMMAND` | Override the OpenShell executable for this invocation; defaults to `$OPENSHELL_CLI` or `openshell`. |
| `--agent NAME` | Select the agent setup; defaults to Codex for containers and Claude for OpenShell. |
| `--image IMAGE` | Override the runtime image. `--base` is an alias. An explicit value is passed through unchanged; an invalid reference fails instead of falling back to the default. |
| `--repo DIR` | Mount the repository into a container or upload it to OpenShell at `/sandbox/repo`. |
| `--port PORT` | Use a specific host port for a container daemon REST endpoint. OpenShell uses the gateway-selected service port. Must be `1-65535`. |
| `--profile PROFILE` | Use a bundled or custom AI Guardian security profile. |
| `--restore-config latest` | Restore the latest saved snapshot for the named sandbox as its initial configuration. Requires `--name`; cannot be combined with `--profile` or `--config-dir`. |
| `--config-dir DIR` | Use `ai-guardian.json` from DIR as the initial config snapshot when no sandbox-local config exists. `--guardian-home` is an alias. |
| `--env KEY=VALUE` | Add an environment value; repeatable. |
| `--provider NAME` | Attach an OpenShell provider; repeatable. |
| `--policy FILE` | Add an OpenShell policy overlay; repeatable. The baseline and selected-agent fragments are included automatically. |
| `--label KEY=VALUE` | Add a runtime label; repeatable. |
| `--model MODEL` | OpenShell Vertex AI inference model; defaults to `$AI_GUARDIAN_OPEN_SHELL_MODEL` or `claude-sonnet-4-6`. |
| `--api-key KEY` | Pass a direct Anthropic key to container setup, or use it only while creating an OpenShell Claude provider. It is never placed in sandbox runtime arguments. |

In the tray's **Create sandbox** form, **Agent / CLI** is a dropdown containing
the CLI-capable sandbox integrations: `claude`, `copilot`, `codex`, `gemini`,
`kiro`, `openclaw`, `opencode`, and `crush`.

The **Image / base** field remains editable for registry references, local
Dockerfile paths, and community sandbox names. Its **Browse...** button lists
local images carrying the `ai-guardian.support-image=true` label from the
configured Docker/Podman engine. Images without that label can still be used by
typing their reference manually. For example, a locally built OpenShell image
uses `localhost/ai-guardian-openshell:dev` (a slash separates the registry name
from the image name).

An optional command can follow `--`:

```bash
ai-guardian sandbox create --runtime container --name guardian-codex -- \
  codex --help
```

Without an explicit command, a container sandbox starts a long-lived login
shell with an allocated TTY so that it remains available for later `connect`
and `exec` calls. It does not launch an interactive agent automatically; start
one from the shell or with `sandbox exec`.

OpenShell's native upload flow cannot reliably combine uploads with a trailing
command. The subcommand handles this by creating the detached sandbox first,
then invoking the image entrypoint through a non-interactive `sandbox exec`
after uploads finish. This bootstrap returns after setup so `create` can expose
the gateway-managed `ai-guardian` service, then the default create opens an
independent interactive
`sandbox exec --tty` shell. Exiting that shell returns to the host while the
named sandbox remains available for a later `connect` or `exec`. If an explicit
command follows `--`, it runs in a separate exec after bootstrap and the create
command returns when that command exits.

When `--provider` is omitted, staged OpenShell setup reuses or creates an
`ai-guardian-<agent>` provider from the active gateway and local credentials
when that agent has a matching provider profile. Existing providers can always
be selected explicitly with repeatable `--provider` options. Claude Vertex AI
setup is selected by `ANTHROPIC_VERTEX_PROJECT_ID` or `VERTEX_AI_PROJECT_ID`; it
creates or updates the gateway Vertex provider and configures the
`inference.local` route. Provider values and credentials are kept out of the
sandbox's `--env` and `--upload` arguments.

## Configuration precedence

Both runtimes use the same configuration precedence:

1. An explicit `--profile` (including `@standard`) creates the sandbox-local
   configuration from that profile.
2. An explicit `--restore-config latest` seeds the sandbox from the newest
   saved snapshot for the logical sandbox name.
3. An existing sandbox-local `ai-guardian.json` is preserved and used.
4. If no local config exists, the selected host config is copied into the
   sandbox as a writable initial snapshot.
5. If neither config exists, AI Guardian creates a sandbox-local default.

The host config is never written back. When it supplies the initial config, the
daemon reports `config_source=host` and `config_read_only=false`; edits made in
the TUI, NiceGUI, or REST API affect only the sandbox's copy. OpenShell uploads
the snapshot, while containers use a read-only bind mount for the staging file
before copying it into the writable active config path.

## Configuration snapshots

Configuration snapshots preserve changes made inside a sandbox without
overwriting the host configuration. The commands contact the running sandbox
daemon, retrieve its active global configuration, and write the result on the
host. Snapshots are stored under `$XDG_STATE_HOME/ai-guardian/sandboxes/` (by
default `~/.local/state/ai-guardian/sandboxes/`) using the logical sandbox name
and a UTC timestamp. The runtime type is recorded as snapshot metadata and is
used to select `latest`, so container and OpenShell snapshots with the same
name cannot be mixed. The logical name remains the snapshot key and
user-facing sandbox identity rather than a runtime-generated container ID or
OpenShell UUID.

Container and OpenShell runtimes have separate native name spaces, so the same
logical name can exist in both. The tray displays the runtime alongside the
name. Lifecycle commands auto-detect a unique match; if both runtimes contain
the name, specify `--runtime container` or `--runtime openshell`.

For OpenShell, stop and start through OpenShell when possible. If its generated
container was stopped directly with Docker/Podman, the tray start action first
tries OpenShell and then recovers by starting the underlying container when
OpenShell reports that its control-plane state is not stopped.

Save and inspect snapshots:

```bash
ai-guardian sandbox config save guardian-codex
ai-guardian sandbox config list guardian-codex
```

Restore the latest snapshot into an existing running sandbox:

```bash
ai-guardian sandbox config restore guardian-codex --snapshot latest
```

Recreate a deleted sandbox with its latest saved configuration:

```bash
ai-guardian sandbox create \
  --runtime container \
  --name guardian-codex \
  --restore-config latest \
  --repo .
```

`--restore-config` is intentionally opt-in and cannot be combined with a
profile or host `--config-dir`. It stages the selected snapshot as input, then
the entrypoint copies it into the writable sandbox configuration. Saving and
restoring never modifies the host config. `config save` and `config restore`
require a running daemon; OpenShell also requires its `ai-guardian` service
endpoint to be available.

In the system tray, the top-level action for an OpenShell target is
`Connect`. It uses the same independent OpenShell `exec` session as
`Manage sandbox -> Connect`; the generic container `Terminal` action is kept
for ordinary container sandboxes.

## Inspecting and listing

Use `status` for one named sandbox and `list` for the resources created by this
command. Named lifecycle commands automatically discover the runtime, so
`--runtime` is only needed when the same name exists in both runtime
namespaces or when you want to force a specific runtime:

```bash
ai-guardian sandbox status guardian-codex
ai-guardian sandbox status --json guardian-claude
ai-guardian sandbox list --json
ai-guardian sandbox list --runtime container --json
ai-guardian sandbox list --runtime openshell --json
```

The `--json` option forwards JSON output to the selected runtime. Container
listing is filtered by the `ai-guardian.managed=true` label; OpenShell listing
uses the equivalent selector.

When `--port` is omitted for a container, Docker/Podman publishes the internal
daemon port `63152` on a runtime-assigned host port. Find that host port with
`podman port NAME` or `docker port NAME`.

For OpenShell, the command exposes the daemon's internal port through the
gateway-managed service named `ai-guardian`:

```bash
openshell service expose NAME 63152 ai-guardian
openshell service get NAME ai-guardian
```

The gateway assigns a unique URL for each sandbox, such as
`http://NAME--ai-guardian.openshell.localhost:PORT/`. This endpoint is durable
and independent for every OpenShell sandbox, so multiple sandboxes can expose
the same internal daemon port. Tray and NiceGUI discovery query the gateway for
each sandbox's service URL. `start` and `restart` reconcile the service after
the daemon is started; `stop` leaves the service definition in place but it is
unreachable while the sandbox is stopped. Deleting an AI Guardian sandbox also
removes its `ai-guardian` service.

## Lifecycle and cleanup

`stop` retains the sandbox so it can be started later. `delete` removes the
runtime resource and its gateway service, while host configuration snapshots
remain available for a later `--restore-config latest`. `connect` opens an
interactive container shell or an independent OpenShell `exec` session, while
`exec` runs a command without replacing the sandbox's main process. The shell
opened automatically by OpenShell `create` uses the same independent `exec`
session, so exiting either shell does not replace or terminate the sandbox's
main process:

```bash
ai-guardian sandbox stop guardian-claude
ai-guardian sandbox start guardian-claude
ai-guardian sandbox restart guardian-claude
ai-guardian sandbox exec guardian-claude -- env
ai-guardian sandbox delete guardian-claude
```

Do not use `delete` when the sandbox may be needed again; use `stop` instead.
