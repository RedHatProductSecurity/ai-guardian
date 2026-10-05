# OpenShell Supervisor Middleware

AI Guardian can run as an external [OpenShell v0.1.2 supervisor
middleware](https://docs.nvidia.com/openshell/latest/extensibility/overview)
service. The service is operator-managed and owns semantic provider-content
scanning only. OpenShell remains authoritative for filesystem, network/SSRF,
process, credential injection, provider routing, and middleware attachment.

This integration is not an OpenShell plugin installed into a sandbox. Start the
AI Guardian service separately, register its gRPC endpoint in the OpenShell
gateway, and attach that registration from an OpenShell sandbox policy.

## Install and start

Install the optional transport dependencies in the environment that runs the
service:

```bash
python -m pip install 'ai-guardian[middleware]'
```

Create an operator-owned configuration such as
`/etc/ai-guardian/openshell-middleware.yaml`:

```yaml
profile_id: strict
openshell_version: 0.2.1  # optional; otherwise detect `openshell --version`
registration_name: content-guard
provider_endpoints:
  - api.openai.com
  - api.anthropic.com
scanner_ownership:
  default: auto
  secret_scanning: middleware
  prompt_injection: middleware
  secret_redaction: middleware
max_payload_bytes: 262144
timeout_ms: 500
response_redaction: true
require_effective_policy: true

tls:
  cert_file: /etc/ai-guardian/tls/server.crt
  key_file: /etc/ai-guardian/tls/server.key
jwt:
  public_key_file: /etc/openshell/jwt/public.pem
  issuer: openshell-gateway:openshell
  audience: urn:openshell:extension:middleware:content-guard
  algorithms: [EdDSA]
```

The configuration can also use a `policy:` object when server settings and
middleware policy need to be kept in separate sections. `profile_id` selects an
existing AI Guardian profile (`minimal`, `standard`, `strict`, or `moderator`)
and only its semantic scanner sections are projected into the service. Hook,
filesystem, network, process, credential, and interactive-dialog settings are
not imported. Profiles containing an interactive `ask` action are rejected.

The middleware uses versioned OpenShell adapters. It selects the newest
adapter not newer than the configured or installed release when the release's
first version component matches the adapter family. Therefore OpenShell
`0.2.1` falls back to the checked-in `0.1.2` adapter, while `1.0.0` is rejected
until a compatible adapter is added. Protocol and capability negotiation still
validates the fallback at runtime and fails closed on an incompatible contract.
Use `--openshell-version VERSION` to override local CLI detection.

Start the external service:

```bash
ai-guardian openshell-middleware \
  --config /etc/ai-guardian/openshell-middleware.yaml \
  --bind 192.168.93.100:50051
```

Replace `192.168.93.100` with the specific host or service interface reachable
by the OpenShell gateway and sandbox supervisors. `0.0.0.0` is a wildcard
listener, not a broadcast address; it exposes every host interface. Plaintext
mode refuses wildcard binds, so use a specific trusted interface for local
testing. A loopback bind is appropriate only when every caller runs on the
same host.

The normal `openshell-middleware` command is a convenience launcher and validator;
it does not edit the OpenShell gateway, create a sandbox, or install an
OpenShell extension. Use a service manager (systemd, a container supervisor,
or a Kubernetes Deployment) to keep it running before the gateway starts.
The previous `middleware-server` spelling remains an alias.

For quick local operation, it also supports daemon-like lifecycle flags:

```bash
ai-guardian openshell-middleware --background --config /tmp/middleware.yaml
ai-guardian openshell-middleware --status
ai-guardian openshell-middleware --restart --config /tmp/middleware.yaml
ai-guardian openshell-middleware --stop
```

Background processes use private PID and log files in the AI Guardian state
directory by default. Override them with `--pid-file` and `--log-file`. For
production, prefer the systemd or container supervisor examples below so the
service is restarted and monitored by the deployment platform.

### Explicit local bootstrap

For local development, `--bootstrap-openshell` can perform the repetitive file
setup in one launch. It idempotently adds or verifies the named registration in
the gateway TOML and writes a sandbox policy; it does not restart the gateway or
modify an existing sandbox:

```bash
ai-guardian openshell-middleware \
  --config /tmp/middleware.yaml \
  --bind 192.168.93.100:50051 \
  --bootstrap-openshell \
  --gateway-config ~/.config/openshell/gateway.toml \
  --policy-out /tmp/content-guard-policy.yaml
```

The gateway and policy paths default to `~/.config/openshell/gateway.toml` and
`openshell-policy.yaml` beside the middleware config. Conflicting existing
settings fail safely; use `--bootstrap-force` only when intentionally replacing
the named registration and generated policy. Restart the gateway if its TOML
changed, then create the sandbox with the generated policy:

```bash
systemctl --user restart openshell-gateway
openshell sandbox create --name guarded --policy /tmp/content-guard-policy.yaml
```

A systemd user or system service can use a unit like this (adjust paths and the
service account for the host):

```ini
[Unit]
Description=AI Guardian OpenShell supervisor middleware
After=network-online.target openshell-gateway.service
Wants=network-online.target

[Service]
User=ai-guardian
  ExecStart=/usr/local/bin/ai-guardian openshell-middleware --config /etc/ai-guardian/openshell-middleware.yaml --bind 192.168.93.100:50051
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadOnlyPaths=/etc/ai-guardian /etc/openshell

[Install]
WantedBy=multi-user.target
```

For Kubernetes, mount the middleware YAML, TLS certificate/key, and OpenShell
public verification key from Secrets or projected volumes; expose the service
through a ClusterIP or another address reachable by both the gateway and
supervisors; and set a readiness probe that checks the gRPC listener. Binding
to `0.0.0.0` can be appropriate inside an isolated pod network when TLS/JWT
and Kubernetes NetworkPolicy protect the service. Keep the OpenShell gateway
registration's `grpc_endpoint` and `tls_ca_cert_path` consistent with the
Service DNS name and mounted CA.

For local-only development, both sides may explicitly opt into plaintext and
no bearer token. Do not use this mode on a shared network:

```yaml
allow_insecure_transport: true
```

```toml
allow_insecure_transport = true
```

For this development-only mode, bind to a specific interface, for example:

```bash
ai-guardian openshell-middleware \
  --config /tmp/middleware.yaml \
  --bind 192.168.93.100:50051
```

Also restrict the host firewall to the OpenShell gateway and supervisor
network. A specific interface narrows exposure but does not authenticate
clients; use TLS/JWT for any shared or production network.

Production deployments should use the gateway's EdDSA public verification key,
the exact issuer and audience, and HTTPS. OpenShell's extension token type is
`openshell-ext+jwt`; accepted tokens require `iss`, `aud`, `sub`, `iat`, `exp`,
`jti`, and `caller_kind` claims. Supervisor callers also require `sandbox_id`.
Tokens longer than one hour are rejected.

## Register the service with OpenShell

Add the service to the gateway TOML. The registration is static and operator
owned; restart the gateway after changing it. The following fields match the
OpenShell v0.1.2 gateway contract:

```toml
[openshell]
version = 2

[[openshell.supervisor.middleware]]
name = "content-guard"
grpc_endpoint = "https://host.openshell.internal:50051"
tls_ca_cert_path = "/etc/openshell/certs/content-guard-ca.pem"
audience = "urn:openshell:extension:middleware:content-guard"
max_payload_bytes = 262144
timeout = "500ms"
```

The gateway calls `Describe` and `ValidateConfig` before accepting the
registration or persisting an attached policy. Check the negotiated,
non-secret state with:

```bash
openshell gateway info
```

The gRPC endpoint must be reachable from the gateway and sandbox supervisors.
Use a shared address such as `host.openshell.internal` where necessary. The
gateway validates the TLS hostname and the service validates the exact JWT
audience; neither a matching service name nor mTLS alone grants sandbox
identity.

## Attach it to a sandbox policy

Reference the operator registration name from the sandbox policy. The
`middleware` value is the registration name, not the diagnostic name returned
by the service:

```yaml
version: 1

network_middlewares:
  content-guard-attachment:
    name: AI Guardian semantic guard
    middleware: content-guard
    order: 10
    config:
      profile_id: strict
    on_error: fail_closed
    endpoints:
      include:
        - api.openai.com
        - api.anthropic.com
```

Create or update the sandbox using the normal OpenShell CLI:

```bash
openshell sandbox create --name guarded --policy policy.yaml
```

There is no `openshell middleware install` command in OpenShell v0.1.2. Normal
operation keeps the external service, gateway registration, and policy
attachment as separate operator actions; the explicit AI Guardian bootstrap
only combines generation of the two files and still leaves gateway restart and
sandbox creation to the operator.

## Scanner ownership and fail-closed behavior

`scanner_ownership` accepts these modes for each semantic scanner:

| Mode | Behavior |
|---|---|
| `middleware` | The external service owns the scanner; missing capability, invalid attachment, or outage denies the operation. |
| `hooks` | The local AI Guardian hook surface owns the scanner; this service does not scan it. |
| `auto` | Use middleware only after protocol, capability, and effective-policy validation; otherwise fall back to hooks when the configured hook capability exists. |
| `both` | Run both surfaces only with a shared request correlation ID and pre-persistence deduplication; otherwise deny. |

The default is `auto`. Effective-policy validation checks the operator
registration name and target provider hostname before scanning. Request-level
configuration cannot replace the operator profile, disable effective-policy
validation, change the provider endpoint set, or weaken the payload/time
limits. Invalid policy, unsupported protocol/capability negotiation, malformed
payloads, scanner errors, and oversized payloads fail closed.

When a scanner is routed to `hooks` or `both`, list the corresponding
`openshell.middleware.scanner.*` capability in `hooks_capabilities`. A missing
hook capability is treated as an unavailable owner rather than silently
skipping the scanner.

The service scans textual leaves throughout JSON provider payloads, including
nested messages, tool calls, tool results, files, and shell content. Response
secret/PII findings may be redacted before delivery when
`response_redaction` is enabled. Raw payloads, matched text, bearer tokens, and
secret values are not placed in middleware diagnostics.

## Ownership boundary

Use OpenShell policies for:

- filesystem and process isolation;
- network allowlists, DNS/SSRF protections, and endpoint routing;
- credential injection and provider credentials;
- sandbox lifecycle, workload identity, and failure policy; and
- deciding which provider endpoints receive this middleware.

Use AI Guardian hooks or this service for semantic content controls:

- secrets and PII in provider content;
- prompt injection, context poisoning, supply-chain, offensive-language, and
  canary content scanners where configured; and
- response redaction.

Do not treat middleware as a replacement for OpenShell network or credential
policy. A request that never reaches the middleware can still be governed by
OpenShell's authoritative controls, and a middleware allow decision does not
authorize a destination or credential.

## Compatibility and operations

- The protobuf contracts are vendored from OpenShell v0.1.2 under
  `src/ai_guardian/middleware/openshell/v0_1_2/proto/`; the adapter registry can
  reuse that implementation for later compatible releases without duplicating
  the code. The runtime dependency is optional for normal hook and SDK
  installations.
- Keep the service and gateway on compatible extension protocol major versions.
- Advertise at least the OpenShell gateway's required capabilities during
  `Describe`; unsupported requirements are rejected before traffic is served.
- Keep the service running before restarting the gateway. Registration startup
  validation is intentionally fail-closed.
- Set `max_payload_bytes` and `timeout_ms` no higher than the gateway
  registration values. The gateway's effective limit is authoritative.
- Use `on_error: fail_closed` in the OpenShell policy for semantic enforcement.
