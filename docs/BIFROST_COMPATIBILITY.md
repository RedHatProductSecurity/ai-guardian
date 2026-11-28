# Bifrost Compatibility

**Issue:** [#2414](https://github.com/RedHatProductSecurity/ai-guardian/issues/2414)

**Validation status:** demonstrated compatibility only; this is not a certification
of every Bifrost provider, API, or deployment mode.

## Release Readiness Runtime Gate

Release Readiness invokes the reusable
`.github/workflows/bifrost-runtime-contract.yml` workflow on one canonical Linux
amd64 tuple. The workflow runs inside the pinned `golang:1.27.4-bookworm`
runtime image, checks the matching dynamic plugin load, and executes the local
mock-daemon/provider contract tests. The test lane covers:

- clean allow and explicit daemon denial, including terminal 403 behavior;
- paused-daemon pass-through without a persisted violation;
- daemon-unavailable behavior in fail-open and fail-closed modes;
- buffered streaming enforcement and cancellation/failure handling;
- provider-native credential isolation; and
- supported MCP request, argument, and result enforcement.

The workflow publishes only a value-free JSON test summary. Detailed synthetic
payloads remain inside the ephemeral runner. The architecture-specific
`bifrost-middleware.yml` matrix remains the authority for Linux amd64/arm64
artifact builds and dynamic host/plugin loading; this runtime gate does not
replace that matrix or claim unsupported Bifrost versions and platforms.

## Scope and Architecture

Bifrost is an inference gateway, not an AI coding-agent host. The existing AI
Guardian integrations remain attached to the agent that runs on the developer's
machine. They protect prompts, local tools, filesystem access, MCP calls, and
tool results through the host's hooks or plugin API. The model provider can be
Bifrost without changing those agent integrations.

```text
agent (AI Guardian hooks/plugins) -> Bifrost gateway -> model provider
              |                         |
       local tools and MCP       virtual key / OAuth routing
```

The tested arrangement therefore required no Bifrost-specific AI Guardian
adapter. Bifrost governance (virtual-key model access, provider routing, and
gateway policy) is complementary to, and does not replace, local agent
authorization and scanning.

The optional **AI Guardian Middleware for Bifrost** is a separate, planned
gateway-layer integration. It would use native Bifrost plugin hooks and the AI
Guardian daemon to inspect gateway traffic, including traffic from clients that
have no local AI Guardian integration. It is not required for the compatibility
configuration below and is not installed by the agent setup commands. See
[Bifrost Middleware Architecture](BIFROST_MIDDLEWARE_ARCHITECTURE.md) for the
planned boundary and enforcement contracts.

## Demonstrated Configurations

The following examples show the endpoint and credential placement used during
the investigation. Replace the example key with an operator-created Bifrost
virtual API key. Do not put provider credentials or OAuth tokens in AI Guardian
configuration, plugin logs, or source control.

### Codex CLI

Codex was validated through Bifrost using ChatGPT subscription OAuth passthrough.
The Bifrost provider was configured as an OpenAI-compatible provider at the
`/openai/v1` endpoint and authorized with a Bifrost virtual key. Codex's existing
ChatGPT login supplied the upstream OAuth authentication; an OpenAI API key was
not required by the tested path.

```toml
# ~/.codex/config.toml (representative provider entry)
[model_providers.bifrost]
name = "Bifrost"
base_url = "http://127.0.0.1:8080/openai/v1"
env_key = "BIFROST_API_KEY"

model_provider = "bifrost"
```

```bash
export BIFROST_API_KEY='<operator-created-bifrost-virtual-key>'
# Authenticate Codex using its normal ChatGPT OAuth flow.
codex
```

The exact Codex model/provider field names are upstream-version dependent; the
tested property is the named OpenAI-compatible provider and Bifrost endpoint,
not a new AI Guardian setting.

### OpenCode

OpenCode 2.0.22 was validated with a Bifrost virtual API key, streaming
responses, shell execution, prompt protection, native file-read blocking, and
the existing AI Guardian MCP integration. The tested provider used Bifrost's
OpenAI-compatible endpoint.

```jsonc
// OpenCode provider configuration (representative shape)
{
  "provider": {
    "bifrost": {
      "name": "Bifrost",
      "options": {
        "baseURL": "http://127.0.0.1:8080/openai",
        "apiKey": "{env:BIFROST_API_KEY}"
      }
    }
  }
}
```

```bash
export BIFROST_API_KEY='<operator-created-bifrost-virtual-key>'
opencode
```

Native ChatGPT OAuth endpoint override was unsuccessful in the tested OpenCode
version: OpenCode appeared to ignore the configured inference endpoint when
using its native ChatGPT OAuth authentication. Use the explicit Bifrost
OpenAI-compatible provider and virtual key for the demonstrated OpenCode path.

### Kilo CLI

Kilo CLI was validated through Bifrost using an OpenAI-compatible provider. The
same Bifrost endpoint and virtual-key pattern can be supplied through Kilo's
provider configuration; AI Guardian's Kilo plugin and MCP registration remain
unchanged.

```jsonc
// Kilo/OpenCode-compatible provider configuration (representative shape)
{
  "provider": {
    "bifrost": {
      "name": "Bifrost",
      "options": {
        "baseURL": "http://127.0.0.1:8080/openai",
        "apiKey": "{env:BIFROST_API_KEY}"
      }
    }
  }
}
```

```bash
export BIFROST_API_KEY='<operator-created-bifrost-virtual-key>'
kilo
```

This example describes the demonstrated provider-routing shape, not a claim
that every Kilo release accepts identical JSON fields. Kilo runtime/container
qualification remains separate from this host-level compatibility result.

### Pi Agent

Pi Agent 1.5.2 was validated through Bifrost using ChatGPT subscription OAuth
passthrough. As with Codex, the tested route used Bifrost's OpenAI-compatible
surface and Bifrost-side virtual-key authorization while Pi retained its normal
ChatGPT authentication flow.

```bash
# Supply the Bifrost OpenAI-compatible route through Pi's provider settings.
# The exact settings-file shape is Pi-version dependent.
export BIFROST_BASE_URL="http://127.0.0.1:8080/openai/v1"
export BIFROST_API_KEY='<operator-created-bifrost-virtual-key>'
pi
```

The environment example documents credential placement and endpoint intent;
consult the installed Pi release for the corresponding provider-settings key.
No Bifrost-specific AI Guardian Pi extension was needed.

The investigation also recorded a separate Pi internal MCP authorization issue.
It is not evidence that Bifrost routing failed and is not resolved by this
compatibility page.

## Validation Results

| Surface | Result | Evidence |
| --- | --- | --- |
| Codex CLI 0.165.0 | Demonstrated | Inference through Bifrost with ChatGPT OAuth passthrough |
| Pi Agent 1.5.2 | Demonstrated | Inference through Bifrost with ChatGPT OAuth passthrough |
| OpenCode 2.0.22 | Demonstrated | Virtual-key provider, streaming, shell and tool execution |
| Kilo CLI | Demonstrated | OpenAI-compatible Bifrost provider and existing AI Guardian integration |
| Claude Code | Untested | No compatibility result is claimed |

OpenCode security checks through Bifrost produced the following observed
results:

- sensitive prompt: rejected and replaced;
- shell output containing an API key: sanitized;
- native read of a sensitive file: blocked;
- harmless `pwd`: allowed;
- AI Guardian MCP scanner status: retrieved successfully.

Additional provider experiments demonstrated OpenRouter streaming/tool use,
Groq inference subject to its free-tier TPM limit, Gemini embeddings, and local
Ollama chat and embeddings. Gemini conversational requests also encountered
upstream availability errors, and Mistral was configured but not validated.
These provider outcomes are not claims of universal Bifrost provider support.

## Security Coverage Boundary

Existing agent-level protection is strongest for operations that traverse the
agent hook/plugin surface. The investigation also identified operations that
may happen outside that surface, including:

- background inference or embedding requests;
- Kilo codebase indexing and related embedding traffic; and
- automatic memory generation or maintenance.

Those operations may not produce the same prompt/tool callbacks as an
interactive turn. Their traffic must not be assumed protected merely because
interactive prompts and tools were protected. In particular, the investigation
did not establish complete coverage for background inference, indexing, memory
generation, SDK calls, OpenAI Responses API traffic, remote Bifrost MCP, OAuth
passthrough at every hook, fallback attempts, WebSockets, or every streaming
boundary.

The planned middleware is intended to address gateway-visible traffic where
native Bifrost hooks provide a verified enforcement point. Its coverage and
failure behavior remain implementation work tracked by [#2861](https://github.com/RedHatProductSecurity/ai-guardian/issues/2861),
following the compatibility and contract investigation in [#2862](https://github.com/RedHatProductSecurity/ai-guardian/issues/2862).
The architecture document records the proposed hook, daemon, identity, and
failure boundaries; it does not turn unverified paths into supported ones.

## Limitations and Unverified Configurations

The following were not certified by this investigation:

- Claude Code through Bifrost;
- standard standalone OpenAI API-key authentication in another environment;
- AI Guardian SDK use with Anthropic Messages, OpenAI Chat Completions, or
  OpenAI Responses through Bifrost;
- GuardedAgent against Bifrost's remote `/mcp` endpoint;
- complete Codex or Pi agent-enforcement matrices beyond the demonstrated
  inference paths;
- provider fallback behavior during security denials;
- all streaming, tool-calling, WebSocket, realtime, and OAuth passthrough
  variants;
- remote HTTPS Bifrost deployments, sandbox/runtime integrations, and product
  container qualification; and
- exact configuration syntax across future Codex, OpenCode, Kilo, and Pi
  releases.

Provider quotas, upstream availability, and model-specific behavior can appear
as Bifrost errors without being AI Guardian failures. Bifrost content logging
was disabled during testing, so the original outbound sensitive payload was
not independently inspected; conclusions are based on observed agent behavior
and enforcement outcomes.

## Conclusion

Bifrost can be used as an inference gateway for the demonstrated Codex CLI,
OpenCode, Kilo CLI, and Pi Agent configurations without a dedicated
Bifrost-specific AI Guardian agent integration. Existing agent-level hooks,
plugins, MCP setup, and policy handling remain the supported protection layer.

Gateway-level protection is a separate optional capability, not a prerequisite
for using Bifrost. Continue that work in #2861 and #2862 using the
[middleware architecture](BIFROST_MIDDLEWARE_ARCHITECTURE.md); do not infer
additional compatibility from this page.

Related tracking:

- [#2861: feat: Implement AI Guardian Middleware for Bifrost using native plugin hooks](https://github.com/RedHatProductSecurity/ai-guardian/issues/2861)
- [#2862: spike: Define AI Guardian Middleware for Bifrost architecture, compatibility and enforcement contracts](https://github.com/RedHatProductSecurity/ai-guardian/issues/2862)
- [Bifrost Middleware Architecture](BIFROST_MIDDLEWARE_ARCHITECTURE.md)
