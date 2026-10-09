# OpenShell Supervisor Middleware

AI Guardian's OpenShell middleware is an **external Rust supervisor service**.
It is not an `ai-guardian` subcommand and it is not part of sandbox creation.
OpenShell-savvy operators manage the service, gateway registration, and policy
with their normal service manager and the `openshell` CLI.

This follows OpenShell's documented custom-service sequence:

1. Start the gRPC service where the gateway and supervisors can reach it.
2. Register the service in the gateway TOML.
3. Restart the gateway so it discovers and validates the service.
4. Attach the registration name to selected hosts in sandbox policy.

The service supervisor is only deployment plumbing for step 1, not an
OpenShell installation command. For a local test, launching the compiled Rust
binary directly is sufficient.
This is the same ownership model described in OpenShell's
[Supervisor Middleware Configuration](https://docs.nvidia.com/openshell/latest/extensibility/supervisor-middleware/configure).

## Ownership boundary

| Concern | Owner |
| --- | --- |
| Build and run the middleware process | Rust binary + systemd, launchd, Kubernetes, or another service manager |
| Register the service | OpenShell gateway `gateway.toml` |
| Attach or remove the service | OpenShell `network_middlewares` policy |
| Create, start, connect to, and delete a sandbox | Native OpenShell commands, or the ordinary `ai-guardian sandbox` wrapper |
| Scan and audit backend | The ordinary AI Guardian daemon used by the Rust service |

AI Guardian's sandbox command deliberately has no middleware flags. It can
still create an ordinary OpenShell sandbox with the AI Guardian image, hooks,
daemon, and related defaults. Creating a sandbox through either path neither
checks whether middleware is deployed nor changes middleware policy. A sandbox
can be created before or after the service is installed.

AI Guardian exposes no middleware lifecycle command. There is also no implicit
bootstrap, attach, detach, start, stop, or pause operation hidden inside
`ai-guardian sandbox`.

## Architecture

```text
                         openshell CLI / tray
                                  |
                 gateway.toml + network_middlewares policy
                                  v
                    +---------------------------+
                    | OpenShell gateway         |
                    | registration + policy     |
                    +-------------+-------------+
                                  |
                    creates/manages sandbox
                                  v
                    +---------------------------+
                    | OpenShell sandbox         |
                    | supervisor                |
                    +-------------+-------------+
                                  |
                    per-request middleware RPCs
                                  v
                    +---------------------------+
                    | External Rust middleware  |
                    | service                   |
                    +-------------+-------------+
                                  |
                         scan/audit requests
                                  v
                    +---------------------------+
                    | AI Guardian daemon        |
                    | host Unix socket or       |
                    | configured remote URL/IP  |
                    +---------------------------+

     +---------------------------+    +-------------------------------+
     | Native OpenShell sandbox  |    | AI Guardian OpenShell wrapper |
     | no AI Guardian hooks or   |    | hooks + in-sandbox daemon     |
     | daemon required           |    | for hook processing           |
     +---------------------------+    +-------------------------------+
```

The bottom two boxes are alternative sandbox contents. The external Rust
service and its daemon backend are outside both sandbox variants. The daemon
inside the AI Guardian wrapper is for that sandbox's hooks; it is separate from
the daemon endpoint used by the external middleware unless an operator
deliberately configures them to be the same reachable service.
At gateway startup, OpenShell also calls the Rust service for capability and
protocol validation before accepting the registration.

## Prerequisites

- OpenShell v0.1.2 or a later qualified v0.1.x patch release.
- A healthy, authenticated OpenShell gateway.
- A host address reachable by both the gateway and OpenShell supervisors.
- The Rust middleware binary built from this repository or obtained from the
  deployment artifact.
- An AI Guardian daemon reachable by the Rust process. The default deployment
  uses the same user's protected Unix socket.

The Rust service is plaintext-only in the current OpenShell contract. Bind it
to a restricted, reachable host address; do not use `0.0.0.0` or another
wildcard address. Put TLS or an authenticated private network boundary in front
of the service if the deployment requires transport protection.

The daemon connection belongs to the external Rust service, not to the
OpenShell sandbox. `AI_GUARDIAN_MIDDLEWARE_BIND` is the middleware listener
address; it is different from the daemon address. Keep
`AI_GUARDIAN_DAEMON_SOCKET` when the middleware and daemon share a host, or set
`AI_GUARDIAN_DAEMON_URL` and its authentication token when the daemon runs at a
provided remote IP. The native OpenShell sandbox itself does not need an AI
Guardian daemon or hooks for middleware scanning.

## 1. Build the Rust service

```bash
cargo build --release --manifest-path rust/openshell-middleware/Cargo.toml
```

The binary owns the OpenShell gRPC boundary, protocol negotiation, provider
request/response/WebSocket handling, daemon-backed scanning, redaction, and
fail-closed behavior. Python gRPC bindings and a Python middleware runtime are
not required.

## 2. Start the external service

Start the ordinary AI Guardian daemon separately if it is not already running.
The middleware process is then managed like any other OpenShell supervisor
extension—not by an AI Guardian lifecycle command.

For a local qualification, run the binary directly in one terminal:

```bash
OPENSHELL_VERSION="$(openshell --version | awk '{print $2}')"
test -n "$OPENSHELL_VERSION"
MIDDLEWARE_HOST="${MIDDLEWARE_HOST:?Set MIDDLEWARE_HOST to an IP assigned to this host and reachable from OpenShell}"

AI_GUARDIAN_OPENSHELL_VERSION="$OPENSHELL_VERSION" \
AI_GUARDIAN_MIDDLEWARE_BIND="$MIDDLEWARE_HOST:50051" \
AI_GUARDIAN_MIDDLEWARE_REGISTRATION=content-guard \
  rust/openshell-middleware/target/release/ai-guardian-openshell-middleware
```

Keep that process running while the gateway is restarted and the policy is
applied. Set `MIDDLEWARE_HOST` to an address assigned to the middleware host,
not a documentation or wildcard address. The same reachable address must be
used by the gateway registration.

For a development build, the equivalent command is:

```bash
OPENSHELL_VERSION="$(openshell --version | awk '{print $2}')"
test -n "$OPENSHELL_VERSION"
MIDDLEWARE_HOST="${MIDDLEWARE_HOST:?Set MIDDLEWARE_HOST to an IP assigned to this host and reachable from OpenShell}"

AI_GUARDIAN_OPENSHELL_VERSION="$OPENSHELL_VERSION" \
AI_GUARDIAN_MIDDLEWARE_BIND="$MIDDLEWARE_HOST:50051" \
AI_GUARDIAN_MIDDLEWARE_REGISTRATION=content-guard \
  cargo run --release --manifest-path rust/openshell-middleware/Cargo.toml
```

For a long-running deployment, use the host's existing service manager
(systemd, launchd, Kubernetes, or equivalent) to run that same command. This
is optional deployment plumbing, not an OpenShell installation step. The
service must be running before the gateway is restarted because OpenShell
contacts it during gateway startup.

For example, after installing an operator-owned **systemd user unit** named
`ai-guardian-openshell-middleware.service`, start and inspect it with:

```bash
systemctl --user start ai-guardian-openshell-middleware.service
systemctl --user status ai-guardian-openshell-middleware.service
```

The unit name is an example chosen by the operator; these commands do nothing
until a matching unit has been installed. Use the service manager's equivalent
commands for launchd, Homebrew, or Kubernetes.

The binary requires `AI_GUARDIAN_OPENSHELL_VERSION` so a direct deployment
cannot accidentally run against an unqualified OpenShell release. Check the
installed CLI with `openshell --version` before setting the service variable.
It defaults to the daemon Unix socket; set `AI_GUARDIAN_DAEMON_URL` and an
authenticated token only for a deliberately remote daemon deployment.

Useful runtime variables:

| Variable | Purpose |
| --- | --- |
| `AI_GUARDIAN_OPENSHELL_VERSION` | Qualified OpenShell release marker; required |
| `AI_GUARDIAN_MIDDLEWARE_BIND` | Restricted listener address; default `127.0.0.1:50051` |
| `AI_GUARDIAN_MIDDLEWARE_REGISTRATION` | Gateway registration name; default `content-guard-test` |
| `AI_GUARDIAN_MIDDLEWARE_MAX_PAYLOAD_BYTES` | Bounded payload size |
| `AI_GUARDIAN_DAEMON_SOCKET` | Daemon Unix socket override |
| `AI_GUARDIAN_DAEMON_URL` | Explicit remote daemon REST endpoint |
| `AI_GUARDIAN_DAEMON_TOKEN_FILE` | Token file for the remote daemon |
| `AI_GUARDIAN_DAEMON_TOKEN` | Token override for the remote daemon |
| `RUST_LOG` | Rust service logging filter |

## 3. Register it in the OpenShell gateway

Registration is static and operator-owned. Add the service to the gateway's
`gateway.toml`. For the usual user-level OpenShell installation, this file is
`$XDG_CONFIG_HOME/openshell/gateway.toml`, or
`~/.config/openshell/gateway.toml` when `XDG_CONFIG_HOME` is unset. If the
gateway was started with `--config` or `OPENSHELL_GATEWAY_CONFIG`, edit the
file selected by that override instead. Common OpenShell 0.1.2 locations are:

| Installation | Usual gateway TOML location |
| --- | --- |
| Debian/Ubuntu or Fedora/RHEL user service | `~/.config/openshell/gateway.toml` |
| Homebrew | `$XDG_CONFIG_HOME/openshell/gateway.toml`, or a Homebrew prefix path such as `/opt/homebrew/var/openshell/gateway.toml` |
| Snap | `/var/snap/openshell/common/gateway.toml` |

The gateway's effective configuration is always the file selected by its
`--config`/`OPENSHELL_GATEWAY_CONFIG` override or, without an override, by its
package/default lookup.

The OpenShell 0.1.2 gateway configuration reference lists the package paths in
detail:
[Gateway Configuration File](https://docs.nvidia.com/openshell/v0.1.2/how-it-works/gateways/configuration).

```toml
[openshell]
version = 2

[[openshell.supervisor.middleware]]
name = "content-guard"
grpc_endpoint = "http://host.openshell.internal:50051"
allow_insecure_transport = true
max_payload_bytes = 262144
timeout = "500ms"
```

The `name` must match `AI_GUARDIAN_MIDDLEWARE_REGISTRATION`. The endpoint must
be reachable from the gateway and the sandbox supervisors. Restart the
operator-managed gateway after editing the file, then verify the live
registration:

Use `host.openshell.internal` when it resolves to the middleware host in the
OpenShell environment. Otherwise replace it with the same real host address
used in `MIDDLEWARE_HOST`; never use `192.0.2.10`, which is documentation-only.

```bash
# Linux: Debian/Ubuntu and Fedora/RHEL package installs use a systemd user service.
systemctl --user restart openshell-gateway

# macOS/Homebrew: the OpenShell formula runs the gateway as a Homebrew service.
brew services restart openshell

# Confirm that the restarted gateway is reachable.
openshell gateway info
```

If OpenShell was installed with Snap, restart its system service instead:
`sudo snap restart openshell.gateway`. For a custom installation, use the
service manager that starts that gateway process. Restarting is required after
editing `gateway.toml` because middleware registration is loaded at gateway
startup.

OpenShell recommends a TLS endpoint for a remote service. The current AI
Guardian Rust binary intentionally supports only restricted plaintext
transport, so this example uses `http://` and explicitly opts into
`allow_insecure_transport`. Keep that listener on a trusted private network
until TLS support is added.

OpenShell v0.1.2 has no arbitrary external-middleware installation command.
The service process and static gateway registration are intentionally separate.

## 4. Create an ordinary sandbox

Choose either sandbox creation path. Middleware is not coupled to either one,
and neither command checks whether the middleware service is running.

### Option A: native OpenShell sandbox

This creates the OpenShell template as-is. It does **not** add the AI Guardian
image, hooks, daemon, or AI Guardian-specific environment:

```bash
openshell sandbox create --name mw-proof --template <template> -- /bin/true
```

That is sufficient when the external middleware uses the daemon configured on
its own host or at a separate reachable daemon address. The sandbox only needs
to reach the OpenShell gateway/supervisor path; it does not need to run an AI
Guardian daemon.

### Option B: OpenShell sandbox with AI Guardian hooks

This uses AI Guardian's ordinary sandbox wrapper. The wrapper delegates the
sandbox lifecycle to OpenShell, but selects the AI Guardian OpenShell image and
adds the hooks, daemon, labels, and selected CLI setup. It still does not start
or attach the Rust middleware:

```bash
ai-guardian sandbox create \
  --runtime openshell \
  --name mw-proof \
  --cli codex \
  --repo .
```

The daemon included by this wrapper serves the in-sandbox AI Guardian hooks. It
is not a requirement for the external middleware, which uses the daemon
endpoint configured for the Rust service unless an operator deliberately
exposes and selects another daemon endpoint.

Use the native OpenShell lifecycle commands or the wrapper's ordinary sandbox
lifecycle commands as appropriate. In both options, apply the middleware in
the next step with native `openshell policy` when the sandbox was not created
with `--policy`.

## 5. Attach middleware with OpenShell policy

OpenShell activates a registered service through a `network_middlewares` policy
entry. The policy must be a complete policy appropriate for the target
sandbox; a small fragment is not a safe replacement for its existing
filesystem, provider, and network controls.

Create the policy file used for `mw-proof`:

```bash
cat >> /tmp/mw-proof-policy.yaml <<'EOF'
version: 1

network_middlewares:
  content-guard:
    name: AI Guardian content guard
    middleware: content-guard
    order: 10
    on_error: fail_closed
    config:
      response_redaction: true
      scanner_ownership:
        default: hooks
        prompt_injection: middleware
        context_poisoning: middleware
        secret_scanning: middleware
        scan_pii: middleware
        secret_redaction: middleware
    endpoints:
      include:
        - api.openai.com
        - chatgpt.com
        - ab.chatgpt.com
EOF
```

The `>>` form creates the file when it does not exist and appends when it
does. Run it once for a fresh file, or remove the old `/tmp` file before
repeating the example.

The nested `middleware` value must match the gateway registration name. The map
key is the stable policy-local identity; using `content-guard` for both keeps
the example easy to inspect. For Codex OAuth, retain all three OpenAI hosts.
Apply the complete policy to a single live sandbox with OpenShell:

```bash
openshell policy set mw-proof \
  --policy /tmp/mw-proof-policy.yaml \
  --wait
openshell policy get mw-proof --full
```

When the policy is ready before sandbox creation, OpenShell can apply it during
the ordinary create operation instead:

```bash
openshell sandbox create \
  --name mw-proof \
  --policy /tmp/mw-proof-policy.yaml \
  -- /bin/true
```

For the AI Guardian-hooked sandbox, the equivalent create-time form is:

```bash
ai-guardian sandbox create \
  --runtime openshell \
  --name mw-proof \
  --cli codex \
  --repo . \
  --policy /tmp/mw-proof-policy.yaml
```

Here `--policy` is the general OpenShell-policy option, not a middleware-
specific AI Guardian flag. The wrapper composes the supplied policy with its
ordinary AI Guardian sandbox defaults and passes the resulting policy to
OpenShell. The middleware service must already be running and registered
before creation, because OpenShell validates the policy against the
registered service.

This is the explicit activation point. If the middleware service is stopped,
the OpenShell policy remains attached and the fail-closed path applies; use
your service manager to restart the service.

### Gateway-wide activation

OpenShell can apply a complete policy globally:

```bash
openshell policy set --global \
  --policy ./gateway-policy.yaml \
  --yes
```

Use this only when every sandbox should receive the same policy. A global
policy replaces sandbox/provider policy control for the gateway; do not use a
middleware-only fragment as a global policy. Review the complete policy and
the confirmation prompt before applying it.

## 6. Remove or change middleware

To deactivate middleware for one sandbox, remove `network_middlewares.content-guard`
from that sandbox's complete policy and apply the revised policy through
OpenShell:

```bash
openshell policy set mw-proof \
  --policy ./mw-proof-policy-without-middleware.yaml \
  --wait
```

The sandbox remains intact. No AI Guardian middleware command or sandbox
recreation is involved.

When no policy references the registration, remove the registration from the
gateway TOML and restart the gateway. Stop the directly launched process with
Ctrl-C, or stop it through the service manager used for the deployment.

Stop the directly launched Rust process with Ctrl-C, or use the host's
existing process supervisor for a long-running deployment. Then delete the
sandbox only when the workload itself is no longer needed:

```bash
openshell sandbox delete mw-proof
```

## Failure, pause, and audit behavior

- The OpenShell policy should use `on_error: fail_closed`.
- The Rust service fails closed when daemon scanning or protocol validation is
  unavailable.
- Pausing or stopping the external process is a service-manager/OpenShell
  decision; there is no middleware-specific AI Guardian pause command.
- Rust middleware audit records use the normal AI Guardian daemon audit path:
  `${AI_GUARDIAN_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/ai-guardian}/violations.jsonl`.
- Run the daemon, Rust service, and Console under compatible users and state
  directories when the Console should display those records.

The middleware only sees traffic selected by OpenShell policy. It does not
replace AI Guardian hooks for filesystem reads, process execution, directory
rules, or arbitrary tool output outside the selected provider boundary.

## Compatibility and validation

The qualified contract is stored in
`src/ai_guardian/middleware/openshell/compatibility.json`: OpenShell `0.1.x`
from `0.1.2` onward and supervisor protocol `1.0`. The Rust binary embeds and
validates this contract before listening.

Run the repository checks before deploying a new binary:

```bash
python scripts/check_openshell_compatibility.py
cargo test --manifest-path rust/openshell-middleware/Cargo.toml
```

Credential-free CI can validate the binary, protocol, policy, and Codex
installation. OAuth account/workspace routing still requires a manual local
qualification with the operator's OpenShell credentials.

## Clean reset for a new middleware test

Keep middleware cleanup separate from sandbox cleanup:

1. Remove the middleware entry with `openshell policy set` and verify the
   effective policy with `openshell policy get --full`.
2. Delete the sandbox only if the workload should be removed:
   `openshell sandbox delete NAME`.
3. Stop the Rust service:
   - If it was started in a terminal, return to that terminal and press
     `Ctrl-C`.
   - If it is a systemd user service, run
     `systemctl --user stop ai-guardian-openshell-middleware.service` if you
     gave the unit that name. The unit name is operator-defined; a direct
     binary launch has no systemd unit.
   - If it is a Homebrew service, use the actual formula name shown by
     `brew services list`. AI Guardian does not currently ship a Homebrew
     middleware formula, and `openshell` refers to the OpenShell gateway, not
     this middleware. For launchd, stop the label used by the service's plist.
   - If it is deployed in Kubernetes, scale the middleware deployment to zero
     or delete the operator-managed workload.
4. Remove the gateway registration from `gateway.toml` only when it is no
   longer needed, then restart the gateway.
5. Confirm `openshell gateway info` no longer lists the registration.

There is intentionally no `ai-guardian openshell-middleware stop`, `start`,
`restart`, or `status` command. The Rust process is an external OpenShell
service, so its lifecycle belongs to the terminal, service manager, or
deployment platform that started it. This also prevents two independent
middleware control planes from disagreeing about the listener and gateway
registration.

Do not remove OpenShell-managed containers directly while the sandbox resource
still exists.
