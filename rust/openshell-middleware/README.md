# AI Guardian Rust OpenShell Middleware

Rust owns OpenShell's external gRPC boundary. Scanner execution remains in the
long-lived AI Guardian daemon through its authenticated Unix socket by default.

## Build

```bash
cargo build --release --manifest-path rust/openshell-middleware/Cargo.toml
```

The crate vendors `protoc` through `protoc-bin-vendored`; no system `protoc`
installation is required.

## Run

Start AI Guardian daemon first:

```bash
ai-guardian daemon start -b
```

By default, run this daemon and the Rust middleware under the same host/user
environment. The middleware connects to the daemon's permission-protected
`daemon.sock`. A separately hosted daemon requires an explicit
`AI_GUARDIAN_DAEMON_URL` plus `AI_GUARDIAN_DAEMON_TOKEN` or
`AI_GUARDIAN_DAEMON_TOKEN_FILE`.

Then start middleware:

```bash
AI_GUARDIAN_MIDDLEWARE_BIND=127.0.0.1:50051 \
  rust/openshell-middleware/target/release/ai-guardian-openshell-middleware
```

Environment:

| Variable | Default |
|---|---|
| `AI_GUARDIAN_MIDDLEWARE_BIND` | `127.0.0.1:50051` |
| `AI_GUARDIAN_MIDDLEWARE_REGISTRATION` | `content-guard-test` |
| `AI_GUARDIAN_DAEMON_URL` | Explicit remote REST override; otherwise use Unix socket |
| `AI_GUARDIAN_DAEMON_SOCKET` | XDG AI Guardian `daemon.sock` |
| `AI_GUARDIAN_DAEMON_TOKEN_FILE` | REST override token file |
| `AI_GUARDIAN_DAEMON_TOKEN` | Explicit token override |

The Rust service fails closed when daemon checks fail. It supports HTTP request,
HTTP response, and text-WebSocket bindings; all scanner execution remains in
the daemon backend.

OpenShell closes a denied WebSocket message with code `1008`; Codex may retry
that stream before its HTTPS fallback. Configure a Codex custom Responses
provider with `supports_websockets = false` when immediate HTTP
`middleware_denied` feedback is preferred. Codex may still render a temporary
reconnect status while retrying a denied HTTP stream; middleware cannot control
that client-side display.
