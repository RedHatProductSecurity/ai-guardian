# Shared Middleware Contract

**Contract:** `ai-guardian.middleware` **v1**

The machine-readable contract is `src/ai_guardian/middleware/contract.json`.
The regression matrix is `tests/fixtures/middleware_contract.json`. OpenShell
and Bifrost adapters must preserve these semantics while translating them into
their native gateway APIs.

## Shared Semantics

- The daemon receives bounded content, selected checks, `action: block`, an
  opaque correlation ID, and trusted operator-mapped project context.
- Credentials, authorization headers, cookies, bearer tokens, and other
  sensitive fields are excluded before the daemon boundary.
- `allow`, `deny`, and `paused` are daemon-authoritative outcomes. A pause
  continues traffic without treating the request as clean evidence.
- A daemon denial is terminal and must not become a provider retry or fallback.
- Daemon unavailability and malformed verdicts follow configured
  `on_scan_error` behavior, defaulting to block. Explicit daemon denials always
  block, even when failure handling is configured to allow.
- Payload limits, unsupported operations, and unavailable capability paths must
  be reported explicitly and fail closed unless the configured failure mode
  applies to a control-plane error.

## Adapter Boundaries

OpenShell maps allow, deny, pause, and redaction to protocol actions
(`Allow`/`PassThrough`, `Deny`, `Skip`, and `Transform`). Its capability
handshake and HTTP/WebSocket phase rules remain OpenShell-specific.

Bifrost maps the same outcomes to hook continuation, terminal security
short-circuits, stream resume/termination, and response handling. Hook ordering,
provider-attempt identity, fallback suppression, and native plugin loading remain
Bifrost-specific. Unsupported Bifrost surfaces must remain explicitly reported,
not silently treated as protected.

Both adapters run the shared regression cases where their native seam supports
the scenario. The fixture is intentionally data-only so each implementation can
retain its own transport and gateway test harness.

## Capability Discovery

Adapters must advertise or verify the capabilities needed by their deployment
before claiming protection. A missing capability, unsupported operation, or
unverified commitment boundary is an unsupported path, not an implicit allow.
See the adapter-specific guides for OpenShell and Bifrost details.
