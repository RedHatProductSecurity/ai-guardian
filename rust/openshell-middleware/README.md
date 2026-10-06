# AI Guardian Rust OpenShell Middleware

Rust owns OpenShell's external gRPC boundary. Scanner execution remains in the
long-lived AI Guardian daemon through its authenticated loopback REST API.

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
| `AI_GUARDIAN_DAEMON_URL` | Explicit override; otherwise derive port from `daemon.pid` |
| `AI_GUARDIAN_DAEMON_PID_FILE` | XDG AI Guardian `daemon.pid` |
| `AI_GUARDIAN_DAEMON_TOKEN_FILE` | XDG AI Guardian `daemon.token` |
| `AI_GUARDIAN_DAEMON_TOKEN` | Explicit token override |

The Rust service fails closed when daemon REST checks fail. It supports HTTP
request and response bindings; WebSocket bindings are intentionally not
advertised until daemon-backed streaming support is added.
