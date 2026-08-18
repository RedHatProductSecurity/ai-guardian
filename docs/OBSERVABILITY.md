# Observability

AI Guardian exports OpenTelemetry (OTEL) traces for both SDK agent runs and interactive IDE sessions. Traces follow the [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) and work with any OTLP-compatible backend: Grafana Tempo, Jaeger, Datadog, Splunk, Honeycomb.

## Quick Start

### 1. Start a collector

The Grafana LGTM stack (Loki, Grafana, Tempo, Mimir) runs everything in one container:

```bash
docker run -d --name lgtm \
  -p 3000:3000 \
  -p 4317:4317 \
  -p 4318:4318 \
  grafana/otel-lgtm
```

- **3000** — Grafana UI
- **4317** — OTLP gRPC (not used by ai-guardian)
- **4318** — OTLP HTTP (ai-guardian sends here)

### 2. Enable OTEL export

Add to your `ai-guardian.json` (or `.ai-guardian/ai-guardian.json`):

```json
{
  "otel": {
    "enabled": true,
    "endpoint": "http://localhost:4318"
  }
}
```

### 3. View traces

Open Grafana at `http://localhost:3000`, navigate to **Explore > Tempo**, and query:

```
{ resource.service.name = "ai-guardian" }
```

## Configuration

OTEL configuration lives in the top-level `otel` section of `ai-guardian.json`.

```json
{
  "otel": {
    "enabled": true,
    "endpoint": "http://localhost:4318",
    "service_name": "ai-guardian",
    "export_format": "otlp-json",
    "headers": {
      "Authorization": "Bearer <token>"
    },
    "resource_attributes": {
      "team.name": "security",
      "deployment.environment": "dev"
    }
  }
}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `false` | Enable OTEL span export |
| `endpoint` | string | `http://localhost:4318` | OTLP HTTP collector URL |
| `service_name` | string | `ai-guardian` | `service.name` resource attribute |
| `export_format` | string | `otlp-json` | `otlp-json` or `otlp-proto` (proto requires `pip install ai-guardian[otel]`) |
| `headers` | object | `{}` | HTTP headers sent with each export request |
| `resource_attributes` | object | `{}` | Static key-value pairs added as OTEL resource attributes on every span |

### Environment Variable Overrides

| Env Var | Overrides | Format |
|---------|-----------|--------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `endpoint` | URL |
| `OTEL_SERVICE_NAME` | `service_name` | string |
| `OTEL_EXPORTER_OTLP_HEADERS` | `headers` (config takes precedence) | `key1=val1,key2=val2` |

## What Gets Exported

### SDK Agent Runs (GuardedAgent)

Full agent conversation traces with per-turn detail. Exported in two ways:

- **Live export** — each turn is sent to the collector as it completes (via `OtelSpanEmitter`)
- **File export** — trace JSON files written to `~/.local/state/ai-guardian/sdk/traces/`, exportable via CLI

#### Span Hierarchy

```
gen_ai.agent (root)
└── gen_ai.turn (one per conversation turn)
    ├── gen_ai.chat          — LLM response with token usage
    ├── tool:{name}          — tool call (e.g., tool:bash)
    ├── tool_result:{name}   — tool result
    ├── gen_ai.security_scan — security scan result
    └── gen_ai.compaction    — context compaction event
```

#### Root Span Attributes (`gen_ai.agent`)

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.system` | string | Always `"anthropic"` |
| `gen_ai.agent.name` | string | Agent name |
| `gen_ai.request.model` | string | Model ID (e.g., `claude-sonnet-4-20250514`) |
| `gen_ai.request.max_tokens` | int | Max output tokens |
| `gen_ai.agent.stop_reason` | string | `end_turn`, `error`, etc. |
| `gen_ai.agent.duration_ms` | int | Total run duration in milliseconds |
| `gen_ai.agent.hostname` | string | Machine hostname |
| `ai_guardian.session_id` | string | Session identifier (if available) |
| `ai_guardian.project.name` | string | `org/repo` from git remote, or directory basename |
| `ai_guardian.span_type` | string | `"agent_run"` (on live export root spans) |

Token usage totals are **not** on the root span. Per-turn usage lives on `gen_ai.chat` child spans — Grafana can sum them with `sum(gen_ai.usage.input_tokens)`.

#### Chat Span Attributes (`gen_ai.chat`)

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.usage.input_tokens` | int | Input tokens for this turn |
| `gen_ai.usage.output_tokens` | int | Output tokens for this turn |
| `gen_ai.usage.cache_read_input_tokens` | int | Cache read tokens |
| `gen_ai.usage.cache_creation_input_tokens` | int | Cache creation tokens |
| `gen_ai.response.finish_reasons` | array | Stop reason (`end_turn`, `tool_use`) |
| `gen_ai.chat.latency_ms` | int | LLM response latency |
| `gen_ai.response.text_length` | int | Response text length in characters |
| `gen_ai.response.tool_call_count` | int | Number of tool calls in this response |

#### Turn Span Attributes (`gen_ai.turn`)

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.turn.number` | int | Turn index (0-based) |
| `gen_ai.turn.messages_count` | int | Number of messages in context |
| `gen_ai.turn.messages_count_growth` | int | Messages added since previous turn |
| `gen_ai.turn.compacted` | bool | Whether context was compacted before this turn |
| `gen_ai.turn.duration_ms` | int | Turn duration |

#### Tool Span Attributes

| Attribute | Type | Span |
|-----------|------|------|
| `tool.name` | string | Both `tool:{name}` and `tool_result:{name}` |
| `tool.input` | string | `tool:{name}` — JSON input (truncated to 1024 chars) |
| `tool.output_bytes` | int | `tool_result:{name}` — output size |
| `tool.output_truncated` | bool | `tool_result:{name}` — whether output was truncated |
| `tool.latency_ms` | int | `tool_result:{name}` — execution time |

### Interactive Sessions (Hooks)

Session-level activity summary exported on `SessionEnd`. Requires the daemon to be running.

#### Span Hierarchy

```
ai_guardian.session (root)
├── ai_guardian.violation  — one per violation detected
├── ai_guardian.block      — one per blocked tool call
└── ai_guardian.scan       — aggregated scan summary
```

#### Session Root Attributes (`ai_guardian.session`)

| Attribute | Type | Description |
|-----------|------|-------------|
| `ai_guardian.session_id` | string | IDE session identifier |
| `ai_guardian.project.name` | string | `org/repo` from git remote, or directory basename |
| `ai_guardian.adapter` | string | IDE adapter name (e.g., `Claude Code`, `Gemini CLI`) |
| `ai_guardian.violation_count` | int | Total violations in session |
| `ai_guardian.block_count` | int | Total blocked tool calls |
| `ai_guardian.hook_event_count` | int | Total hook events processed |
| `ai_guardian.span_type` | string | Always `"session"` |
| `gen_ai.usage.input_tokens` | int | Total input tokens (from transcript, if available) |
| `gen_ai.usage.output_tokens` | int | Total output tokens |
| `gen_ai.usage.cache_read_input_tokens` | int | Total cache read tokens |
| `gen_ai.usage.cache_creation_input_tokens` | int | Total cache creation tokens |

#### Violation Span Attributes (`ai_guardian.violation`)

| Attribute | Type | Description |
|-----------|------|-------------|
| `ai_guardian.violation_type` | string | e.g., `secret_detected`, `prompt_injection` |
| `ai_guardian.severity` | string | `warning`, `critical` |
| `tool.name` | string | Tool that triggered the violation |
| `ai_guardian.violation_id` | string | Unique violation identifier |
| `ai_guardian.scanner` | string | Scanner that detected it |

#### Block Span Attributes (`ai_guardian.block`)

| Attribute | Type | Description |
|-----------|------|-------------|
| `tool.name` | string | Tool that was blocked |
| `ai_guardian.reason` | string | Why the tool call was blocked |
| `ai_guardian.scanner` | string | Scanner that blocked it |

## SDK Dynamic Metadata

`GuardedAgent` accepts an `otel_metadata_fn` callback to add custom attributes to every span:

```python
from ai_guardian.integrations.anthropic import GuardedAgent

def metadata_fn(agent_name: str, ctx: dict) -> dict:
    """Add custom OTEL attributes.

    ctx contains: model, turn, usage, and stop_reason (on run complete).
    Return a dict of key-value pairs.
    """
    return {
        "case.id": "AAP-85065",
        "pipeline.stage": "triage",
    }

agent = GuardedAgent(
    name="triage-agent",
    model="claude-sonnet-4-20250514",
    otel_metadata_fn=metadata_fn,
)
```

The callback is called:
- On each turn completion (with `turn`, `model`, `usage`)
- On run completion (adds `stop_reason` to the context)

Returned key-value pairs are added as OTEL attributes on the turn or root span.

## CLI Export

Export saved trace files to OTLP format or directly to a collector.

### Export a single trace

```bash
# To stdout (OTLP JSON)
ai-guardian trace export trace.json

# To file
ai-guardian trace export trace.json -o trace.otlp.json

# To collector
ai-guardian trace export trace.json --endpoint http://localhost:4318

# With auth header
ai-guardian trace export trace.json \
  --endpoint http://collector:4318 \
  --header 'Authorization=Bearer tok123'

# Protobuf format (requires pip install ai-guardian[otel])
ai-guardian trace export trace.json --format otlp-proto -o trace.pb
```

### Export all traces in a directory

```bash
# Export SDK trace directory (auto-detected)
ai-guardian trace export-dir

# Export specific directory
ai-guardian trace export-dir ~/.local/state/ai-guardian/sdk/traces/ -o ./exported/

# Custom service name
ai-guardian trace export-dir --service-name my-pipeline -o ./exported/
```

Trace files are stored in `~/.local/state/ai-guardian/sdk/traces/` by default (XDG state directory).

## Grafana Setup

### Data Source Configuration

After starting the LGTM stack:

1. Open Grafana at `http://localhost:3000` (default credentials: `admin`/`admin`)
2. Go to **Connections > Data sources > Tempo** (pre-configured in LGTM)
3. Navigate to **Explore > Tempo**

### Useful TraceQL Queries

```
# All traces from ai-guardian
{ resource.service.name = "ai-guardian" }

# Filter by agent name
{ span.gen_ai.agent.name = "triage-agent" }

# Filter by project
{ span.ai_guardian.project.name = "RedHatProductSecurity/ai-guardian" }

# All activity for an org
{ span.ai_guardian.project.name =~ "RedHatProductSecurity/.*" }

# Sessions with violations
{ span.ai_guardian.violation_count > 0 }

# Find specific violation types
{ name = "ai_guardian.violation" && span.ai_guardian.violation_type = "secret_detected" }

# Blocked tool calls
{ name = "ai_guardian.block" }

# Token-heavy turns (> 10k input tokens)
{ name = "gen_ai.chat" && span.gen_ai.usage.input_tokens > 10000 }

# Compaction events
{ name = "gen_ai.compaction" }

# Filter by team (via resource_attributes)
{ resource.team.name = "security" }

# Errors only
{ name = "gen_ai.agent" && status = error }
```

## Trace Viewer (Console)

AI Guardian includes a built-in trace viewer accessible from both the TUI and web console.

### Web Console

Navigate to `http://{daemon-host}:{port}/traces` to browse SDK agent traces. The page shows a list of trace files with:
- Agent name, model, duration
- Turn count and token usage
- A **Send to Collector** button to push traces to the configured OTEL endpoint

### TUI Console

Run `ai-guardian console --web` and navigate to the **SDK Traces** panel for the same functionality in a terminal interface.

## Anthropic Console vs ai-guardian OTEL

| Aspect | Anthropic Console | ai-guardian OTEL |
|--------|-------------------|------------------|
| Level | API-level (per-request) | Agent-level (full conversation) |
| Scope | Single API call | Multi-turn agent run with tool calls |
| Security | Not included | Violations, blocks, scan results |
| Custom metadata | Not supported | `otel_metadata_fn` callback |
| Backend | Anthropic dashboard | Any OTLP backend (Grafana, Jaeger, etc.) |
| Interactive sessions | Not supported | Hook session activity |
| Self-hosted | No | Yes |

Use Anthropic Console for API debugging and rate limit monitoring. Use ai-guardian OTEL for agent-level observability, security auditing, and cross-project analysis.

## Troubleshooting

### Traces not showing in Grafana

- **Check time range** — Grafana defaults to "Last 1 hour". Widen the range or use "Last 15 minutes" for recent traces.
- **Check endpoint** — Verify the collector is running: `curl -s http://localhost:4318/v1/traces -X POST -H 'Content-Type: application/json' -d '{}'`
- **Check config** — Run `ai-guardian config show` and look for the `otel` section.

### Collector not accessible

OTEL export is **fail-open**: if the collector is unreachable, the agent continues normally. Failures are logged at `DEBUG` level. Check logs with:

```bash
AI_GUARDIAN_LOG_LEVEL=DEBUG ai-guardian trace export trace.json --endpoint http://localhost:4318
```

### Daemon not exporting hook sessions

1. Verify OTEL is enabled in config: `ai-guardian config show | grep -A5 otel`
2. Restart the daemon after config changes: `ai-guardian daemon restart`
3. Hook session traces are only flushed on `SessionEnd` — end the IDE session to trigger export.

### Protobuf format errors

The `otlp-proto` format requires additional dependencies:

```bash
pip install ai-guardian[otel]
```

This installs `opentelemetry-proto` and `protobuf`. The default `otlp-json` format requires no extra dependencies.
