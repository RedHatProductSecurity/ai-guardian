# AI Guardian Rust OpenShell Middleware

This crate builds the external Rust supervisor middleware used by OpenShell.
It is deployed and managed as an ordinary service. AI Guardian does not expose
a middleware lifecycle command, and sandbox creation does not start or attach
this process.

## Build

```bash
cargo build --release --manifest-path rust/openshell-middleware/Cargo.toml
```

The crate vendors `protoc` through `protoc-bin-vendored`; a system `protoc`
installation is not required.

## Run directly

Run the ordinary AI Guardian daemon separately. Then launch the Rust binary
under systemd, launchd, Kubernetes, or another service supervisor:

```bash
OPENSHELL_VERSION="$(openshell --version | awk '{print $2}')"
test -n "$OPENSHELL_VERSION"

AI_GUARDIAN_OPENSHELL_VERSION="$OPENSHELL_VERSION" \
AI_GUARDIAN_MIDDLEWARE_BIND=192.0.2.10:50051 \
AI_GUARDIAN_MIDDLEWARE_REGISTRATION=content-guard \
  rust/openshell-middleware/target/release/ai-guardian-openshell-middleware
```

Use a real restricted host address reachable by the OpenShell gateway and
supervisors. The plaintext listener must not bind a wildcard address.

The service owns OpenShell gRPC, protocol negotiation, daemon-backed scanning,
request/response/WebSocket inspection, redaction, and fail-closed behavior.
Python gRPC bindings and a Python middleware runtime are not required.

## Environment

| Variable | Default |
|---|---|
| `AI_GUARDIAN_OPENSHELL_VERSION` | Required qualified OpenShell release marker |
| `AI_GUARDIAN_MIDDLEWARE_BIND` | `127.0.0.1:50051` |
| `AI_GUARDIAN_MIDDLEWARE_REGISTRATION` | `content-guard-test` |
| `AI_GUARDIAN_MIDDLEWARE_MAX_PAYLOAD_BYTES` | `262144` |
| `AI_GUARDIAN_DAEMON_SOCKET` | XDG AI Guardian `daemon.sock` |
| `AI_GUARDIAN_DAEMON_URL` | Optional authenticated remote daemon REST endpoint |
| `AI_GUARDIAN_DAEMON_TOKEN_FILE` | Token file for the remote daemon |
| `AI_GUARDIAN_DAEMON_TOKEN` | Token override for the remote daemon |
| `RUST_LOG` | Rust tracing filter |

The default daemon connection is the permission-protected Unix socket. A
remote daemon requires an explicit URL and authentication token. If daemon
scanning fails, the middleware fails closed.

## OpenShell registration and policy

Register the service in the operator-owned gateway TOML and restart the
gateway:

```toml
[[openshell.supervisor.middleware]]
name = "content-guard"
grpc_endpoint = "http://192.0.2.10:50051"
allow_insecure_transport = true
max_payload_bytes = 262144
timeout = "500ms"
```

Then attach the registered name through an OpenShell `network_middlewares`
policy. Use `openshell policy set` for a complete per-sandbox policy or an
intentionally complete gateway-global policy. The middleware binary does not
modify gateway configuration or sandbox policy.

## Compatibility

The binary embeds the shared compatibility contract at
`src/ai_guardian/middleware/openshell/compatibility.json`. It currently
supports OpenShell `0.1.x` from `0.1.2` onward and supervisor protocol `1.0`.
An unsupported release, protocol, or capability negotiation fails before the
service accepts traffic.

## Tests

```bash
cargo test --manifest-path rust/openshell-middleware/Cargo.toml
```
