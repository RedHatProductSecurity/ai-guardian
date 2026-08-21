# AI Guardian SDK

Programmatic security checking for Python agent programs.

## Overview

AI Guardian's hook-based protection covers IDE sessions (Claude Code, Cursor, VS Code). The SDK extends this protection to **programmatic use cases** — custom agents, LangChain pipelines, direct LLM API calls, and any Python program that processes untrusted content.

The SDK is **additive protection**. It cannot bypass or weaken existing hook-based enforcement. Hooks remain the enforcement layer for IDE sessions; the SDK serves programs where hooks don't apply.

## Installation

The SDK is included with ai-guardian. No additional installation required.

```bash
pip install ai-guardian
```

## Quick Start

```python
from ai_guardian.sdk import monitor

# Check content for threats (secrets, prompt injection, context poisoning)
with monitor() as session:
    session.check_content(user_input)
    session.check_file("/path/to/config.json")
    session.check_command("curl http://example.com")
```

## LLM Client Integration

The `guarded()` wrapper automatically intercepts LLM API calls and scans prompts and responses — no manual `check_content()` calls needed.

### Installation

```bash
pip install ai-guardian[anthropic]    # Anthropic SDK support
pip install ai-guardian[openai]       # OpenAI SDK support
```

### Usage

**Auto-detect from environment** (simplest — no provider import needed):

```python
from ai_guardian.integrations import guarded

# Auto-creates Anthropic client from environment variables:
#   ANTHROPIC_API_KEY            → Anthropic()
#   ANTHROPIC_VERTEX_PROJECT_ID  → AnthropicVertex()
#   ANTHROPIC_BEDROCK_BASE_URL   → AnthropicBedrock()
client = guarded()
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": user_input}],
)
```

**Explicit Anthropic client**:

```python
from anthropic import Anthropic
from ai_guardian.integrations import guarded

client = guarded(Anthropic())
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": user_input}],
)
```

**Vertex AI**:

```python
from anthropic import AnthropicVertex
from ai_guardian.integrations import guarded

client = guarded(
    AnthropicVertex(project_id="my-project", region="us-east5"),
)
response = client.messages.create(
    model="claude-sonnet-4@20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": user_input}],
)
```

**AWS Bedrock**:

```python
from anthropic import AnthropicBedrock
from ai_guardian.integrations import guarded

client = guarded(AnthropicBedrock())
response = client.messages.create(
    model="anthropic.claude-sonnet-4-20250514-v1:0",
    max_tokens=1024,
    messages=[{"role": "user", "content": user_input}],
)
```

**OpenAI**:

```python
from openai import OpenAI
from ai_guardian.integrations import guarded

client = guarded(OpenAI())
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": user_input}],
)
```

**Azure OpenAI**:

```python
from openai import AzureOpenAI
from ai_guardian.integrations import guarded

client = guarded(
    AzureOpenAI(azure_endpoint="https://my-resource.openai.azure.com"),
)
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": user_input}],
)
```

### OpenAI-Compatible Providers

Any LLM server that exposes an OpenAI-compatible `/v1/chat/completions` endpoint works with `guarded()` and `GuardedAgent` — no code changes needed. Point the standard `OpenAI` client at the provider's URL.

**Ollama**:

```python
from openai import OpenAI
from ai_guardian.integrations import guarded

client = guarded(
    OpenAI(base_url="http://localhost:11434/v1", api_key="ollama"),
)
response = client.chat.completions.create(
    model="llama3.1",
    messages=[{"role": "user", "content": user_input}],
)
```

`api_key="ollama"` is required by the OpenAI client but ignored by the Ollama server.

**llama.cpp**:

```python
client = guarded(
    OpenAI(base_url="http://localhost:8080/v1", api_key="not-needed"),
)
response = client.chat.completions.create(
    model="local-model",
    messages=[{"role": "user", "content": user_input}],
)
```

**vLLM**:

```python
client = guarded(
    OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed"),
)
response = client.chat.completions.create(
    model="meta-llama/Llama-3.1-8B-Instruct",
    messages=[{"role": "user", "content": user_input}],
)
```

**LiteLLM** (proxy that routes to any provider):

```python
client = guarded(
    OpenAI(base_url="http://localhost:4000/v1", api_key="not-needed"),
)
```

**Mistral** (via OpenAI-compatible endpoint):

```python
client = guarded(
    OpenAI(base_url="https://api.mistral.ai/v1", api_key=os.environ["MISTRAL_API_KEY"]),
)
response = client.chat.completions.create(
    model="mistral-large-latest",
    messages=[{"role": "user", "content": user_input}],
)
```

#### GuardedAgent with Local Models

`GuardedAgent` works with OpenAI-compatible providers via the `strategy` parameter:

```python
from openai import OpenAI
from ai_guardian.integrations.anthropic import GuardedAgent
from ai_guardian.integrations.openai import OpenAILoopStrategy

agent = GuardedAgent(
    client=OpenAI(base_url="http://localhost:11434/v1", api_key="ollama"),
    model="llama3.1",
    tools="coding",
    strategy=OpenAILoopStrategy(),
)
result = agent.run("find bugs in this file")
```

#### Config Profile for Local Models

Use named agent profiles in `ai-guardian.json` to avoid hardcoding connection details:

```json
{
    "sdk": {
        "agents": {
            "local-reviewer": {
                "model": "llama3.1",
                "max_turns": 10
            }
        }
    }
}
```

```python
agent = GuardedAgent(
    client=OpenAI(base_url="http://localhost:11434/v1", api_key="ollama"),
    name="local-reviewer",
)
```

#### Caveats

| Topic | Details |
|-------|---------|
| **Tool calling** | Requires a model with tool/function calling support (llama3.1, qwen2.5, mistral-large). Models without it will fail in `GuardedAgent` |
| **Streaming** | Delta format may differ between providers. Not all implement SSE identically |
| **Stop reasons** | Providers may return different `finish_reason` values. `GuardedAgent` checks for `"stop"` (OpenAI standard) |
| **Security scanning** | ai-guardian scans identically regardless of provider — secrets, PII, prompt injection all work the same |
| **Install** | Requires `pip install ai-guardian[openai]` |

### `create_client(*, provider, provider_config, **kwargs)`

Auto-detect and create an LLM client from environment variables.

```python
from ai_guardian.integrations import create_client

# Auto-detect from env vars (default — raises ValueError on conflict)
client = create_client()

# Explicit provider — resolves env var conflicts
client = create_client(provider="vertex")

# OpenAI-compatible local server
client = create_client(
    provider="openai-compatible",
    provider_config={"base_url": "http://localhost:8080/v1"},
)

# Custom env var for API key
client = create_client(
    provider="direct",
    provider_config={"api_key_env": "MY_CUSTOM_KEY"},
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `provider` | str | `None` | Provider to use. Anthropic: `direct`/`anthropic`, `vertex`, `bedrock`, `foundry`. OpenAI-compatible: `openai`, `azure`, `openai-compatible` (canonical), `ollama`, `mlx`, `llamacpp`, `vllm`, `lm-studio`. If `None`, auto-detects from env vars. |
| `provider_config` | dict | `None` | Provider-specific overrides: `base_url`, `base_url_env`, `api_key_env`, `project_id_env`, `region_env`. |

Raises `ValueError` if multiple conflicting env vars are set (and no `provider` specified), or if no credentials are found.

**Default auth env vars per provider:**

| Provider | Client | Default env vars |
|----------|--------|------------------|
| `direct` / `anthropic` | `Anthropic()` | `ANTHROPIC_API_KEY` |
| `vertex` | `AnthropicVertex()` | `ANTHROPIC_VERTEX_PROJECT_ID`, `CLOUD_ML_REGION` |
| `bedrock` | `AnthropicBedrock()` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` |
| `foundry` | `AnthropicFoundry()` | Foundry credentials |
| `openai` | `OpenAI()` | `OPENAI_API_KEY` |
| `azure` | `AzureOpenAI()` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` |
| `openai-compatible` | `OpenAI(base_url=...)` | None (local server) |
| `ollama` | `OpenAI(base_url=...)` | None (alias for `openai-compatible`) |
| `mlx` | `OpenAI(base_url=...)` | None (alias for `openai-compatible`) |
| `llamacpp` | `OpenAI(base_url=...)` | None (alias for `openai-compatible`) |
| `vllm` | `OpenAI(base_url=...)` | None (alias for `openai-compatible`) |
| `lm-studio` | `OpenAI(base_url=...)` | None (alias for `openai-compatible`) |

Use `provider_config` fields to override these defaults:

| Field | Description |
|-------|-------------|
| `base_url` | Server endpoint (required for local servers) |
| `base_url_env` | Env var name holding the server endpoint URL |
| `api_key_env` | Env var name holding the API key (overrides default) |
| `project_id_env` | Env var name for GCP project ID (vertex, default: `ANTHROPIC_VERTEX_PROJECT_ID`) |
| `region_env` | Env var name for region (vertex, default: `CLOUD_ML_REGION`) |

**Config-driven:** Set `sdk.provider` and `sdk.provider_config` in `ai-guardian.json` to avoid passing these in code:

```json
{
  "sdk": {
    "provider": "vertex",
    "provider_config": {
      "project_id_env": "MY_GCP_PROJECT",
      "region_env": "MY_GCP_REGION"
    }
  }
}
```

**Environment variable overrides** (highest precedence):

| Env var | Overrides |
|---------|-----------|
| `AI_GUARDIAN_SDK_PROVIDER` | `sdk.provider` config and code `provider=` argument |
| `AI_GUARDIAN_SDK_BASE_URL` | `sdk.provider_config.base_url` and `base_url_env` |

### `guarded(client, *, name, mode, config, extractor, response_parser, before_call, after_call)`

Wraps an LLM client with automatic security scanning.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `client` | object | *(auto-detect)* | LLM provider client. If omitted, auto-created from env vars. |
| `name` | str | `None` | Profile name linking to `sdk.agents.<name>` in `ai-guardian.json`. Config values override code-provided parameters |
| `mode` | str | `"direct"` | `"direct"` runs checks in-process, `"rest"` delegates to daemon |
| `config` | dict | `None` | Config override. If `None`, loads from `ai-guardian.json` |
| `extractor` | ProviderExtractor | `None` | Explicit extractor (skips auto-detection) |
| `response_parser` | callable | `None` | `(client_type: str, response) -> Any` — transforms native responses into a caller-defined format. If `None`, native response returned unchanged. |
| `before_call` | callable | `None` | `(method_name: str, args: tuple, kwargs: dict) -> None` — called before each API call |
| `after_call` | callable | `None` | `(method_name: str, response: Any) -> None` — called after each successful API call. Not called on `SecurityViolation` |

**Returns:** A wrapped client proxy. Use it exactly like the original client. If `response_parser` is set, calls return the parser's output instead of the native response.

**Raises:**

- `ValueError` if no extractor matches the client type and none provided explicitly
- `SecurityViolation` when a blocked finding is detected (per-scanner `action` in global config controls what is blocked). If `response_parser` is set, the exception's `sanitized_parsed` attribute contains the parser applied to the violating response. Detected-but-not-blocked findings emit `warnings.warn`.

### What Gets Scanned

**Input** (before API call): system prompt, all message content — checked for secrets, prompt injection, context poisoning, PII.

**Output** (after API call): response text content blocks — same checks.

### Streaming

For `messages.stream()`, input is scanned before the stream starts. Output is scanned on the accumulated final message when the stream context exits — individual chunks are not scanned.

```python
client = guarded(Anthropic())

with client.messages.stream(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": user_input}],
) as stream:
    for text in stream.text_stream:
        print(text, end="")
# Output scanned here on context exit
```

### Supported Providers

| Provider | Client Types | Methods Wrapped |
|----------|-------------|-----------------|
| Anthropic | `Anthropic`, `AsyncAnthropic`, `AnthropicVertex`, `AnthropicBedrock`, `AnthropicFoundry` (+ async variants) | `messages.create`, `messages.stream` |
| OpenAI | `OpenAI`, `AsyncOpenAI`, `AzureOpenAI`, `AsyncAzureOpenAI` | `chat.completions.create` |
| OpenAI-compatible | Ollama, llama.cpp, vLLM, LiteLLM, Mistral — via `OpenAI(base_url=...)` | `chat.completions.create` |

### Tested Providers

| Provider | Status | Tools | Notes |
|----------|--------|-------|-------|
| Anthropic (direct) | Verified | Full | Primary provider |
| Vertex AI | Verified | Full | |
| Bedrock | Verified | Full | |
| OpenAI | Verified | Full | |
| Azure OpenAI | Untested | Expected full | Same API as OpenAI |
| Ollama | In progress | Model-dependent | Needs content normalization (#2083) |
| llama.cpp | Untested | Limited | Needs testing |
| vLLM | Untested | Expected full | Needs testing |
| Foundry | Untested | Unknown | New provider |

### Tool Support by Provider

Not all providers and models support tool calling. Without tool support, `GuardedAgent` cannot execute actions — only `guarded()` works for scan-only protection.

| Provider | Tool calling | Models with tools |
|----------|-------------|-------------------|
| Anthropic | All models | claude-sonnet-\*, claude-opus-\*, claude-haiku-\* |
| OpenAI | Most models | gpt-4, gpt-4o, gpt-4o-mini |
| Ollama | Model-dependent | llama3.1, qwen2.5-coder, mistral-large — NOT llama3, phi3 |
| llama.cpp | Model + grammar dependent | Varies |
| vLLM | Model-dependent | Most instruction-tuned models |

### Custom Extractors

Implement `ProviderExtractor` to support any LLM client:

```python
from ai_guardian.integrations import ProviderExtractor, guarded

class MyExtractor(ProviderExtractor):
    @classmethod
    def detect(cls, client):
        return isinstance(client, MyLLMClient)

    def methods_to_wrap(self):
        return ["generate"]

    def extract_input(self, method_name, args, kwargs):
        return [kwargs.get("prompt", "")]

    def extract_output(self, method_name, response):
        return [response.text]

client = guarded(MyLLMClient(), extractor=MyExtractor())
```

### Response Parser

Use `response_parser` to transform native LLM responses into a unified format. This is useful when your application works with multiple providers and needs a consistent response shape.

```python
from ai_guardian.integrations import guarded

def my_parser(client_type: str, response) -> dict:
    if client_type == "anthropic":
        return {
            "text": response.content[0].text,
            "tokens_in": response.usage.input_tokens,
            "tokens_out": response.usage.output_tokens,
            "model": response.model,
        }
    elif client_type == "openai":
        return {
            "text": response.choices[0].message.content,
            "tokens_in": response.usage.prompt_tokens,
            "tokens_out": response.usage.completion_tokens,
            "model": response.model,
        }

# Without parser — native response (default, backward compatible)
client = guarded(Anthropic())
response = client.messages.create(...)  # returns Anthropic Message object

# With parser — caller's unified format
client = guarded(Anthropic(), response_parser=my_parser)
result = client.messages.create(...)  # returns my_parser's dict
print(result["text"])
```

The `client_type` string is derived from the extractor class name: `AnthropicExtractor` → `"anthropic"`, `OpenAIExtractor` → `"openai"`. Custom extractors can override the `provider_name` property.

When `response_parser` is set and an output violation occurs, the `SecurityViolation` exception includes a `sanitized_parsed` attribute with the parser applied to the violating response:

```python
try:
    result = client.messages.create(...)
except SecurityViolation as e:
    e.response          # raw native response (always available)
    e.sanitized_text    # redacted text (always available)
    e.sanitized_parsed  # parser applied to the violating response
```

### Hooks

Use `before_call` and `after_call` for per-call observability:

```python
def on_call(method_name, args, kwargs):
    print(f"Calling {method_name}")

def on_response(method_name, response):
    print(f"{method_name}: {response.usage.output_tokens} tokens")

client = guarded(
    Anthropic(),
    before_call=on_call,
    after_call=on_response,
)
```

## `guarded()` vs `GuardedAgent`

Both provide security scanning but serve different use cases.

| Feature | `guarded()` | `GuardedAgent` |
|---------|------------|----------------|
| **What it does** | Wraps an LLM client to scan input/output | Full agent loop with tool execution and per-step scanning |
| **Agent loop** | None — caller manages the conversation | Built-in tool-use loop with configurable turns |
| **Scanning scope** | Input prompts, output responses | Input, output, system prompt, tool results, intermediate responses |
| **Tool execution** | None — caller handles tools | Built-in executors for bash, text_editor, read_file, grep, glob, MCP |
| **Setup complexity** | One line — `client = guarded(Anthropic())` | Configuration for tools, cwd, max_turns, etc. |
| **Streaming** | Supported (scans on stream exit) | Not directly exposed (internal API calls) |
| **Custom extractors** | Supported — extend to any LLM client | Uses `guarded()` internally |
| **Response parser** | Supported — transform responses | Not applicable (returns structured result dict) |
| **Structured output** | Not built-in | `output_schema` parameter |
| **Callbacks** | `before_call`, `after_call` | `before_call`, `after_call`, `pre_run`, `post_run`, `between_turns`, `on_turn` |
| **Tracing** | None | Full per-step trace with OTEL export |
| **Auto-compaction** | None — caller manages context | Built-in context window management |
| **Provider support** | Anthropic, OpenAI, any via custom extractor | Anthropic, OpenAI (via strategy parameter) |

### When to Use `guarded()`

- Adding security scanning to an existing LLM integration
- Building your own agent loop with custom control flow
- Single request/response patterns (chatbots, one-shot generation)
- Streaming responses to users in real time
- Custom LLM providers via `ProviderExtractor`

### When to Use `GuardedAgent`

- Need a complete agent with tool execution (bash, file editing, code search)
- Want security scanning at every interaction point without building it yourself
- Multi-turn agentic workflows (code review, bug fixing, analysis)
- Need structured output, auto-compaction, or trace logging
- Running agents in CI/CD or containers

### Combining Both

`GuardedAgent` uses `guarded()` internally. If you need both standalone scanned calls and an agent loop:

```python
from ai_guardian.integrations import guarded
from ai_guardian.integrations.anthropic import GuardedAgent

# Standalone scanned calls
client = guarded()
response = client.messages.create(model="claude-sonnet-5", ...)

# Agent with full tool loop
agent = GuardedAgent(model="claude-sonnet-5", tools="coding")
result = agent.run("fix the bug")
```

## GuardedAgent

`GuardedAgent` provides a tool-use agent loop on top of `guarded()`. Every message — prompts, tool results, intermediate responses — is scanned for prompt injection, secrets, and PII. Supports Anthropic and OpenAI providers.

### Usage

```python
from ai_guardian.integrations.anthropic import GuardedAgent

agent = GuardedAgent(
    model="claude-sonnet-5",
    system_prompt="You are a code analysis agent.",
    tools=["bash", "text_editor", "grep", "glob"],
    cwd="/path/to/repo",
    max_turns=100,
)
result = agent.run("Find and fix the bug described in JIRA-123")
print(result["output"])
```

### Target Project Allowlists

When the agent operates on code from a different repo, use `target_dir` to load that project's suppression config (allowlists, ignore patterns):

```python
agent = GuardedAgent(
    model="claude-sonnet-5",
    tools=["bash", "text_editor"],
    cwd="/workspace/target-repo",        # where to run tools
    target_dir="/workspace/target-repo",  # whose allowlists to trust
)
```

`target_dir` auto-discovers config files from the target directory:
- `.ai-guardian/ai-guardian.json` — per-scanner allowlist patterns
- `.aiguardignore.toml` — per-scanner file ignore paths
- `.gitleaks.toml` — secret scanning path allowlist

Only suppression data is merged (allowlist patterns, ignore files/tools). Scanner settings like `enabled`, `action`, and `sensitivity` are never imported from the target. Dangerous patterns (e.g., `.*`) are blocked by validation.

`target_dir` is separate from `cwd` — `cwd` controls where tools execute, `target_dir` controls whose allowlists are applied. Both can point to the same directory. `target_dir` requires direct mode (the default); in REST mode the parameter is accepted but allowlists are not merged.

The `monitor()` context manager also accepts `target_dir`:

```python
with monitor(target_dir="/path/to/target-repo") as session:
    session.check_content(text)
```

### Backend Auto-Detection

Same as `guarded()` — detected from environment variables, or pass an explicit client:

```python
from anthropic import AnthropicVertex

agent = GuardedAgent(
    client=AnthropicVertex(project_id="my-project", region="us-east5"),
    model="claude-sonnet-5",
    tools=["bash", "text_editor"],
)
```

### Tools

#### Tool Execution Model

Tools fall into two categories based on where they run:

- **Client tools** (`bash`, `text_editor`, `read_file`, `write`, `notebook_edit`, `grep`, `glob`): GuardedAgent executes these locally in the agent's `cwd`. Tool output (results) is scanned by ai-guardian before returning to the model.
- **Server tools** (`web_search`, `web_fetch`, `code_execution`): Anthropic executes these on their infrastructure. Results pass through ai-guardian output scanning when returned.
- **`computer`**: Declared as a client tool but requires external desktop integration to execute. GuardedAgent passes it to the API but has no built-in executor — typically used with the `"browser"` preset in environments that provide screenshot/input handling.

#### Anthropic Built-In Tools

| Name | Anthropic Type | Description |
|------|---------------|-------------|
| `bash` | `bash_YYYYMMDD` | Execute shell commands in the agent's working directory |
| `text_editor` | `text_editor_YYYYMMDD` | View, create, and edit files (`view`, `create`, `str_replace`, `insert` commands) |
| `computer` | `computer_YYYYMMDD` | Interact with a desktop environment via screenshots and mouse/keyboard |
| `web_search` | `web_search_YYYYMMDD` | Search the web (server-side, Anthropic executes) |
| `web_fetch` | `web_fetch_YYYYMMDD` | Fetch content from a URL (server-side, Anthropic executes) |
| `code_execution` | `code_execution_YYYYMMDD` | Run code in a sandboxed container (server-side, Anthropic executes) |

Tool type versions are auto-detected from the installed Anthropic SDK. Override with `tool_types`:

```python
agent = GuardedAgent(
    tools=["bash"],
    tool_types={"bash": "bash_20260301"},
)
```

#### Custom Tools

These are lightweight tools implemented by GuardedAgent itself (not Anthropic built-ins). They are executed in-process and their schemas are sent to the model as standard tool definitions.

| Name | Description |
|------|-------------|
| `read_file` | Read a file from the local filesystem (with optional offset/limit) |
| `write` | Write content to a file, creating parent directories if needed |
| `notebook_edit` | Edit a Jupyter notebook: replace, insert, or delete cells |
| `grep` | Search for a regex pattern in files (uses system `grep -rn`, skips common non-code directories) |
| `glob` | List files matching a glob pattern (skips common non-code directories) |

##### Input Schemas

**`read_file`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Absolute or relative path to the file to read |
| `offset` | integer | no | Line number to start reading from (0-based) |
| `limit` | integer | no | Maximum number of lines to read |

**`write`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | string | yes | Absolute or relative path to the file to write |
| `content` | string | yes | The content to write to the file |

Creates parent directories automatically. Overwrites existing files.

**`notebook_edit`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `notebook_path` | string | yes | Path to the `.ipynb` notebook file |
| `command` | string | yes | Operation: `edit`, `insert_before`, `insert_after`, or `delete` |
| `cell_number` | integer | yes | 0-based cell index to operate on |
| `new_source` | string | no | New source content (required for `edit`/`insert_*` commands) |
| `cell_type` | string | no | Cell type for insert commands: `code` (default) or `markdown` |

**`grep`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pattern` | string | yes | Regex pattern to search for |
| `path` | string | no | Directory or file to search in (defaults to cwd) |
| `include` | string | no | Glob pattern to filter files (e.g. `'*.py'`) |

**`glob`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pattern` | string | yes | Glob pattern (e.g. `'**/*.py'`) |
| `path` | string | no | Base directory (defaults to cwd) |

#### Symlinked Directories

Built-in tools reject files whose real path resolves outside `cwd`. When `cwd` contains symlinks to external directories (common in pipelines that symlink source repos), two options:

**Option 1: `follow_symlinks=True`** — trust all symlinks inside `cwd`:

```python
agent = GuardedAgent(
    cwd="/project/data/",
    tools="readonly",
    follow_symlinks=True,
)
# Any symlink inside data/ is followed, even if target is outside
```

**Option 2: `allowed_paths`** — whitelist specific external directories:

```python
agent = GuardedAgent(
    cwd="/project/data/",
    tools="readonly",
    allowed_paths=["/other/path/my-repo"],
)
# Only /other/path/my-repo is accessible through symlinks
```

Both are configurable via `ai-guardian.json`:

```json
{
    "sdk": {
        "agents": {
            "my-agent": {
                "follow_symlinks": true,
                "allowed_paths": ["/other/path/my-repo"]
            }
        }
    }
}
```

#### MCP Servers

GuardedAgent can connect to MCP (Model Context Protocol) servers, making their tools available to the agent. Configure MCP servers in `ai-guardian.json` under `sdk.agents.*.mcpServers`:

```json
{
  "sdk": {
    "agents": {
      "*": {
        "mcpServers": {
          "jira": {
            "command": "python",
            "args": ["-m", "jira_mcp_server"],
            "env": {"JIRA_URL": "https://jira.example.com"},
            "timeout": 60
          },
          "remote-api": {
            "url": "https://mcp.internal/sse",
            "headers": {"Authorization": "Bearer ..."},
            "startup_timeout": 15
          }
        }
      }
    }
  }
}
```

**Standard MCP parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `command` | string | Command to start server (stdio transport) |
| `args` | list | Command arguments |
| `env` | dict | Environment variables for server process |
| `url` | string | SSE endpoint URL (SSE transport) |
| `headers` | dict | HTTP headers for SSE connection |

**Operational parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enabled` | bool | `true` | Enable/disable this server |
| `timeout` | int | `30` | Tool call timeout in seconds |
| `startup_timeout` | int | `10` | Max seconds to wait for server to initialize |
| `trust` | string | `"check"` | Trust level: `trusted` (skip scanning), `check` (scan results), `untrusted` (scan results) |
| `scan_results` | bool | `true` | Scan tool results through ai-guardian |
| `defer_loading` | bool | `false` | Defer server startup until first tool call. Tools are discovered via a brief probe at agent start, then the server shuts down and reconnects lazily on the first call. Useful for servers that are expensive to keep running but may not be needed every run. |

MCP tools are named `mcp__{server_name}__{tool_name}` following Claude Code convention. Security scanning of tool results follows the same pipeline as built-in tools unless the server is marked as `trusted` or has `scan_results: false`.

Requires Python >= 3.10 and the `mcp` package (included in ai-guardian dependencies).

#### Presets

| Preset | Tools | Use when |
|--------|-------|----------|
| `"coding"` | `bash` + `text_editor` + `write` + `grep` + `glob` | Agent needs to read, write, and execute code |
| `"readonly"` | `read_file` + `grep` + `glob` | Agent should only read and search code, not modify it |
| `"browser"` | `computer` + `bash` | Agent needs to interact with a GUI/desktop |

```python
agent = GuardedAgent(tools="coding")
```

Mix presets, names, and raw tool dicts:

```python
tools=["coding", "web_search", {"name": "my_tool", "input_schema": {...}}]
```

#### Adding Custom Tools

Pass raw tool dicts alongside built-in names to define additional tools the model can call. GuardedAgent dispatches tool calls by name — built-in names (`bash`, `text_editor`, `read_file`, `write`, `notebook_edit`, `grep`, `glob`) route to their executors; unknown names return `"Error: no executor for tool 'name'"` as the tool result.

Custom tool dicts are sent to the Anthropic API as standard tool definitions, so the model can call them. However, GuardedAgent has no executor for them — the error result is what gets sent back to the model. To properly execute custom tools, you have two options:

**Option 1: Subclass GuardedAgent** and override the tool execution path. This gives full control but requires understanding the internals.

**Option 2: Use `between_turns`** to correct the error result. The hook fires after tool execution (including the error result for unknown tools), giving you a chance to inject the real result as a follow-up message:

```python
def handle_custom_tools(messages, response, turn):
    for block in response.content:
        if block.type == "tool_use" and block.name == "my_tool":
            result = my_tool_executor(block.input)
            return f"Tool result for my_tool: {result}"
    return None

agent = GuardedAgent(
    tools=["bash", {"name": "my_tool", "description": "...", "input_schema": {...}}],
    between_turns=handle_custom_tools,
)
```

> **Note:** The injected string becomes the next user message, not a proper `tool_result` block. For production use cases requiring custom tools, consider using `guarded()` with your own agent loop instead of `GuardedAgent`.

### Structured Output

```python
agent = GuardedAgent(
    model="claude-sonnet-5",
    tools=["bash", "text_editor"],
    output_schema={"type": "object", "properties": {"findings": {"type": "array"}}},
)
result = agent.run("Analyze this code")
print(result["output"])  # validated structured object
```

### What Gets Scanned

| Content | `guarded()` | `GuardedAgent` |
|---------|------------|----------------|
| Initial prompt | Scanned | Scanned |
| System prompt | Not scanned | **Scanned** |
| Tool results (file contents, bash output) | N/A | **Scanned** |
| Intermediate responses | N/A | **Scanned** |
| Final response | Scanned | Scanned |

### `GuardedAgent(...)` Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | str | `"claude-sonnet-5"` | Anthropic model ID |
| `system_prompt` | str | `""` | System prompt |
| `tools` | str or list | `"coding"` | Tool preset, list of names/dicts, or mixed |
| `cwd` | str | `os.getcwd()` | Working directory for tool execution |
| `max_turns` | int | `100` | Max tool-use loop iterations |
| `max_tokens` | int | `16000` | Max output tokens per API call |
| `max_budget_tokens` | int | `-1` | Max cumulative tokens (input + output) across all turns. `-1` = no limit |
| `api_timeout` | int | `300`/`600` | Per-API-call timeout in seconds. Default: 300 (cloud providers), 600 (local providers like Ollama/MLX). On timeout: retries once, then stops with `stop_reason='timeout'` |
| `client` | Any | `None` | Anthropic or OpenAI client (auto-detected if omitted) |
| `mode` | str | `"direct"` | `"direct"` or `"rest"` for scanning |
| `config` | dict | `None` | ai-guardian config override |
| `output_schema` | dict | `None` | JSON schema for structured output |
| `tool_types` | dict | `None` | Override tool type versions |
| `before_call` | callable | `None` | `(method_name: str, args: tuple, kwargs: dict) -> None` — called before each `messages.create()` |
| `after_call` | callable | `None` | `(method_name: str, response: Any) -> Optional[bool]` — called after each API call. Return `False` to stop the loop early |
| `pre_run` | callable | `None` | `(prompt: str, config: dict) -> None` — called once before the agent loop starts |
| `post_run` | callable | `None` | `(result: dict) -> None` — called once after the agent loop ends (even on exceptions, with `result=None`) |
| `between_turns` | callable | `None` | `(messages: list, response: Any, turn: int) -> str \| None \| False` — called after each successful assistant turn. Return `str` to inject as next user message, `None` to continue normally, `False` to stop the loop |
| `on_turn` | callable | `None` | `(turn: int, event: TurnEvent) -> None` — live callback fired per event. See [Observability](#observability) |
| `strategy` | AgentLoopStrategy | `None` | Explicit loop strategy. Auto-detected from `client` if omitted. Use `OpenAILoopStrategy()` for OpenAI clients |
| `cache_ttl` | str or int | `None` | Prompt caching TTL. Anthropic: `"5m"` or `"1h"` (auto-enabled for multi-turn). `0` = disabled |
| `compact_threshold` | float | `0.8` | Ratio of input tokens to context window that triggers compaction. `0.8` = compact at 80% usage. `1.0` = disabled (raises `RuntimeError` when context exhausted) |
| `compact_keep_turns` | int | `5` | Number of recent turn pairs to preserve during compaction |
| `compact_keep_first` | int | `1` | Number of initial turn pairs to preserve during compaction |
| `name` | str | `None` | Profile name linking to `sdk.agents.<name>` in `ai-guardian.json`. Config values override code-provided parameters |
| `trace_dir` | str | XDG state dir | Directory for auto-persisted trace logs. Defaults to `~/.local/state/ai-guardian/sdk/traces/`. Pass an explicit path to override (constructor only, not configurable via config file). Relative paths resolve against `cwd` |
| `trace_path_fn` | callable | `None` | Callback `(agent_name: str, context: dict) -> str` that returns a path segment injected between `trace_dir` and the generated filename. Trailing `/` creates a subdirectory; otherwise the return becomes a filename prefix. `context` contains `model`, `stop_reason`, `usage`, `turn_count` |
| `allowed_paths` | list[str] | `None` | Additional directories that built-in tools may access. By default, tools reject any path that resolves outside `cwd` (e.g. symlinks pointing to external directories). List absolute paths here to whitelist them |
| `follow_symlinks` | bool | `False` | When `True`, built-in tools allow access through symlinks inside `cwd` even when the real target is outside `cwd`. The logical (unresolved) path must still be within `cwd`. Simpler than `allowed_paths` when all symlinks in the working tree are trusted |
| `otel_metadata_fn` | callable | `None` | `(agent_name: str, context: dict) -> dict` — returns key-value pairs added as OTEL span attributes. Called once for the root span (turn=0, includes stop_reason) and per turn for turn spans. `context` contains `model`, `turn`, `usage` (cumulative), and `stop_reason` (final call only). Requires `otel.enabled: true` |

### Hooks

```python
agent = GuardedAgent(
    model="claude-sonnet-5",
    tools="coding",
    before_call=lambda method, args, kwargs: print("Turn starting"),
    after_call=lambda method, response: print(f"Tokens: {response.usage.output_tokens}"),
    pre_run=lambda prompt, config: print(f"Agent starting: {prompt[:50]}"),
    post_run=lambda result: print(f"Done: {result['stop_reason']}" if result else "Failed"),
)
```

**Lifecycle:**

```
agent.run("prompt")
  ├── [pre_run.pre_command]            ← shell hook (config)
  ├── pre_run(prompt, config)          ← once, before loop
  ├── [pre_run.post_command]           ← shell hook (config)
  ├── Turn 1:
  │     ├── [on_turn.pre_command]
  │     ├── [before_call.pre_command]
  │     ├── before_call(...)           ← per turn
  │     ├── [before_call.post_command]
  │     ├── messages.create()
  │     ├── [after_call.pre_command]
  │     ├── after_call(...)            ← per turn (return False to stop)
  │     ├── [after_call.post_command]
  │     ├── [between_turns.pre_command]
  │     ├── between_turns(...)         ← per successful turn (return str to inject)
  │     ├── [between_turns.post_command]
  │     └── [on_turn.post_command]
  ├── Turn 2+: (same as Turn 1 with compact check first)
  ├── [post_run.pre_command]
  ├── post_run(result)                 ← once, after loop (even on exception)
  └── [post_run.post_command]
```

The `config` dict passed to `pre_run` contains: `model`, `tools`, `system_prompt`, `max_turns`, `max_budget_tokens`.

### `between_turns` Hook

Runs after each successful assistant turn — both `end_turn` (text response) and `tool_use` (after tool execution). Does **not** fire on refusal, budget exceeded, or output-schema nudges.

| Return | Behavior |
|--------|----------|
| `str` | Injected as next user message, loop continues |
| `None` | Normal loop behavior (tool execution or end) |
| `False` | Stop the loop (`stop_reason: "hook_early_stop"`) |

Injected messages are scanned by ai-guardian. If a scan blocks the
injected content, the LLM receives a warning message
(`[ai-guardian] Injected content was blocked: <violation_type>`) and the
loop continues so the agent can adapt.

**Use case — external execution between turns:**

```python
import subprocess

def run_pytest_between_turns(messages, response, turn):
    """Run pytest on generated test code, feed results back."""
    # Extract test code from the assistant's response
    text = getattr(response.content[0], "text", "")
    if "def test_" not in text:
        return None  # No test code, let the loop end normally

    # Write and run the test
    with open("/tmp/test_generated.py", "w") as f:
        f.write(text)
    result = subprocess.run(
        ["pytest", "/tmp/test_generated.py", "-v"],
        capture_output=True, text=True, timeout=30,
    )

    if result.returncode == 0:
        return False  # Tests pass, stop the loop

    # Tests failed — send output back for revision
    return f"Tests failed. Fix the code:\n{result.stdout}\n{result.stderr}"

agent = GuardedAgent(
    model="claude-sonnet-5",
    tools=[],
    max_turns=5,
    between_turns=run_pytest_between_turns,
)
result = agent.run("Write a pytest test for the calculate_discount function...")
```

### Shell Hooks (Config-Driven)

Run external shell commands before/after each GuardedAgent callback — without code changes. Useful for audit logging, notifications, approval gates, and metrics push.

**Config** (`ai-guardian.json`):

```json
{
    "sdk": {
        "hooks": {
            "before_call": {
                "pre_command": "bash /path/to/audit-log.sh",
                "post_command": "bash /path/to/notify.sh"
            },
            "after_call": {
                "pre_command": "bash /path/to/validate-response.sh"
            },
            "between_turns": {
                "post_command": "bash /path/to/slack-notify.sh"
            },
            "pre_run": {
                "pre_command": "bash /path/to/setup-env.sh"
            },
            "post_run": {
                "post_command": "bash /path/to/cleanup.sh"
            }
        }
    }
}
```

**Execution order per hook point:**

1. `pre_command` (shell) — from config
2. Python callback — from code (`before_call`, `after_call`, etc.)
3. `post_command` (shell) — from config

**Shell command interface:**

Commands receive JSON context via stdin:

```json
{
    "hook": "before_call",
    "phase": "pre",
    "agent_name": "remediation-planner",
    "turn": 3,
    "model": "claude-opus-4-6"
}
```

Exit code `0` = continue. Non-zero = abort (`stop_reason: "hook_abort"`).

**Per-agent hooks** via agent profiles — different agents get different hooks:

```json
{
    "sdk": {
        "agents": {
            "*": {
                "hooks": {"post_run": {"post_command": "bash log.sh"}}
            },
            "remediation-implementer": {
                "hooks": {"before_call": {"pre_command": "bash approve.sh"}}
            }
        }
    }
}
```

**Resolution order** (each layer overrides the previous):

1. `sdk.hooks` — global hooks for all agents
2. `sdk.agents.*.hooks` — wildcard profile hooks
3. `sdk.agents.<name>.hooks` — named profile hooks

### Auto-Compaction

Long conversations can exceed the model's context window. Auto-compaction shrinks the conversation by truncating old tool results, stripping code blocks, and dropping middle turns.

By default, compaction is **enabled** at 80% of the context window (`compact_threshold=0.8`). When context usage exceeds the threshold, older turns are summarized automatically.

```python
# Disable compaction (raises RuntimeError when context exhausted)
agent = GuardedAgent(
    model="claude-sonnet-5",
    tools="coding",
    compact_threshold=1.0,
)
```

Compaction preserves the first turn pair (`compact_keep_first`) and the most recent turn pairs (`compact_keep_turns`), dropping everything in between. A boundary message marks where turns were removed.

When compaction fires, a `type: "compaction"` trace entry is emitted with `tokens_before`, `tokens_after`, and `method` fields. This appears in both the `on_turn` callback and the `trace` list in the result dict.

To fully disable compaction (raises `RuntimeError` when context exhausted), set `compact_threshold=1.0`.

**Provider support:** Compaction handles both Anthropic and OpenAI message formats automatically via the `AgentLoopStrategy`. Anthropic uses content-block lists; OpenAI uses top-level `role: tool` messages and plain string content. The correct format is selected based on the active strategy.

### Observability

`GuardedAgent` provides two observability surfaces: a live `on_turn` callback for interactive use, and a structured `trace` in the `run()` result for post-run debugging/audit.

#### `on_turn` — Live Callback

Fires each turn with a structured `TurnEvent`:

```python
from ai_guardian.integrations.anthropic import GuardedAgent
from ai_guardian.integrations import TurnEvent

def my_handler(turn: int, event: TurnEvent):
    if event.type == "system":
        print(f"[init] prompt: {event.system_prompt[:50]}...")
    elif event.type == "response":
        print(f"[turn {turn}] {event.text[:100]}...")
    elif event.type == "tool_call":
        print(f"[turn {turn}] tool: {event.name}({event.input})")
    elif event.type == "tool_result":
        print(f"[turn {turn}] result: {event.output[:100]}...")
    elif event.type == "scan":
        if event.violations:
            print(f"[turn {turn}] {len(event.violations)} violations")

agent = GuardedAgent(
    name="code-reviewer",
    on_turn=my_handler,
)
```

For quick debugging, `on_turn=print` works — `TurnEvent` has a readable `__str__`.

#### `trace` — Post-Run Log

Always collected (no opt-in needed). Returned in `run()` result as nested turn objects:

```python
result = agent.run("review this code")

result["trace"] = [
    {"turn": 0, "steps": [
        {"step": 0, "type": "system", "system_prompt": "You are...", "user_prompt": "review this code"},
        {"step": 1, "type": "scan", "scanned": "system_prompt", "violations": []},
        {"step": 2, "type": "scan", "scanned": "user_prompt", "violations": []},
    ]},
    {"turn": 1, "steps": [
        {"step": 0, "type": "input", "messages_count": 1, "compacted": False},
        {"step": 1, "type": "response", "text": "I'll start by reading...", "model_signal": "tool_use",
         "usage": {"input_tokens": 500, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 120}},
        {"step": 2, "type": "scan", "scanned": "agent_response", "violations": []},
        {"step": 3, "type": "tool_call", "name": "bash", "input": {"command": "grep -rn 'TODO' src/"}},
        {"step": 4, "type": "tool_result", "name": "bash", "output": "src/main.py:42: # TODO fix auth"},
        {"step": 5, "type": "scan", "scanned": "tool_result:bash", "violations": []},
    ]},
    {"turn": 2, "steps": [
        {"step": 0, "type": "input", "messages_count": 4, "compacted": False},
        {"step": 1, "type": "response", "text": "Found one issue...", "model_signal": "end_turn",
         "usage": {"input_tokens": 800, "cache_read_input_tokens": 500, "cache_creation_input_tokens": 0, "output_tokens": 200}},
        {"step": 2, "type": "scan", "scanned": "agent_response", "violations": []},
    ]},
]
```

Each turn is self-contained: `input` → optional `compaction` → `response` → `scan` → `tool_call`/`tool_result` pairs.

- **`turn`** — on the parent object. `0` = setup, `1`+ = loop iterations (aligns with `max_turns`).
- **`step`** — 0-based index within a turn's `steps` array.
- **`input_tokens`** on `response` = non-cached input tokens (Anthropic's field, not derived). Total context = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`.
- **`compacted: true`** on `input` means context was compressed before this API call.

#### Event Types

| Turn | Event type | Fields |
|------|-----------|--------|
| 0 | `system` | `preamble` (from config, once), `system_prompt` (from code, once), `user_prompt` |
| 0 | `scan` | `scanned` (`"system_prompt"` or `"user_prompt"`) |
| N | `input` | `messages_count`, `compacted` |
| N | `compaction` | `tokens_before`, `tokens_after`, `method` (only when compaction fired) |
| N | `response` | `text`, `model_signal`, `usage` (`input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `output_tokens`) |
| N | `tool_call` | `name`, `input` |
| N | `tool_result` | `name`, `output` |
| N | `scan` | `scanned` (what was scanned), `violations` (list) |

#### `TurnEvent` Dataclass

```python
@dataclass
class TurnEvent:
    type: str                          # "system" | "input" | "response" | "tool_call" | "tool_result" | "scan" | "compaction"
    text: Optional[str] = None
    name: Optional[str] = None
    input: Optional[dict] = None
    output: Optional[str] = None
    preamble: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    usage: Optional[dict] = None
    model_signal: Optional[str] = None
    violations: Optional[list] = None
    scanned: Optional[str] = None
    tokens_before: Optional[int] = None  # compaction only
    tokens_after: Optional[int] = None   # compaction only
    method: Optional[str] = None         # compaction only
    messages_count: Optional[int] = None # input only
    compacted: Optional[bool] = None     # input only
```

#### Auto-Persist Traces to Disk

Traces are auto-persisted to `~/.local/state/ai-guardian/sdk/traces/` by default:

```python
agent = GuardedAgent(
    name="triage-verifier",
    ...
)
result = agent.run(prompt)
# Trace written to: ~/.local/state/ai-guardian/sdk/traces/triage-verifier_20260810-153042_a1b2c3d4.json
```

To override the default location (constructor only, not configurable via config file):

```python
agent = GuardedAgent(
    name="triage-verifier",
    trace_dir="./agents-trace",   # relative to cwd
    ...
)
```

File naming: `<agent-name>_<YYYYMMDD-HHMMSS>_<uuid>.json`

Trace file content:

```json
{
  "agent_name": "triage-verifier",
  "model": "claude-sonnet-5",
  "started_at": "2026-08-10T15:30:42+00:00",
  "stop_reason": "end_turn",
  "usage": {"input_tokens": 12345, "output_tokens": 678},
  "trace": [...]
}
```

Use `trace_path_fn` to organize traces dynamically (e.g., by case ID):

```python
agent = GuardedAgent(
    name="triage-verifier",
    trace_path_fn=lambda name, ctx: f"{case_id}/",
)
# Trace written to: ~/.local/state/ai-guardian/sdk/traces/nexus-focus-lost/triage-verifier_20260811-100338_a1b2c3d4.json
```

| `trace_path_fn` return | Result |
|------------------------|--------|
| `"case-123/"` | Subdirectory: `traces/case-123/triage-verifier_20260811.json` |
| `"case-123_"` | Prefix: `traces/case-123_triage-verifier_20260811.json` |
| `"case-123/obs-456_"` | Both: `traces/case-123/obs-456_triage-verifier_20260811.json` |
| `None` or not set | Default: `traces/triage-verifier_20260811.json` |

The `context` dict passed to `trace_path_fn` contains: `model`, `stop_reason`, `usage`, `turn_count`.

Behavior:
- Traces are always persisted (default: XDG state directory)
- Directory created if it doesn't exist
- Text fields are sanitized (secrets/PII redacted) before writing
- Errors writing the trace are logged but don't fail the agent
- Explicit relative paths resolve against `cwd`

#### OTEL Custom Metadata

For full OTEL configuration (endpoint, headers, resource attributes, span hierarchy) see the [Observability Guide](OBSERVABILITY.md).

The `otel_metadata_fn` callback lets you attach dynamic, per-run attributes to OTEL spans:

```python
agent = GuardedAgent(
    name="remediation-planner",
    otel_metadata_fn=lambda agent_name, ctx: {
        "case.id": case_id,
        "case.severity": severity,
        "attempt": ctx["turn"],
    },
)
```

The callback receives `(agent_name: str, context: dict)` where context contains `model`, `turn` (0 for root span), `usage` (cumulative), and `stop_reason` (final call only). It is called once for the root span and once per turn for turn spans. Dynamic attributes merge on top of static `resource_attributes` from config.

### `agent.run(prompt)` Return Value

```python
{
    "output": "...",       # final text or structured object
    "messages": [...],     # full conversation history
    "stop_reason": "...",  # see stop_reason table below
    "usage": {
        "input_tokens": 1234,
        "output_tokens": 567,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    },
    "compaction_count": 0, # number of times compaction was triggered
    "trace": [...],        # structured event trace (see Observability)
}
```

#### `stop_reason` Values

| Value | Meaning |
|-------|---------|
| `end_turn` | Model returned a text response with no tool calls — natural completion |
| `hook_early_stop` | `after_call` or `between_turns` callback returned `False` to stop the loop |
| `max_turns` | Reached the `max_turns` limit without the model finishing |
| `budget_exceeded` | Total tokens spent reached `max_budget_tokens` |
| `refusal` | Model refused to respond |
| `security_violation` | Response or tool result blocked by a security scan |
| `timeout` | API call timed out on both initial attempt and retry — partial result returned |
| `error` | Exception during the agent loop (partial trace persisted) |
| `in_progress` | Agent is still running (only appears in incremental trace files) |

## API Reference

### `monitor(mode, config)`

Context manager that creates a guarded session. Blocked findings raise `SecurityViolation`; detected-but-not-blocked findings emit `warnings.warn`. Per-scanner `action` settings in the global config control what is blocked vs. warned.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mode` | str | `"direct"` | `"direct"` runs checks in-process, `"rest"` delegates to daemon |
| `config` | dict | `None` | Config override. If `None`, loads from `ai-guardian.json` |

**Yields:** `GuardSession` with the methods below.

### `session.check_content(text, *, filename="input")`

Checks text for:
- **Secrets** — API keys, passwords, tokens (via Gitleaks)
- **Prompt injection** — attempts to override system instructions
- **Context poisoning** — hidden instructions in seemingly benign content

Returns `CheckResult`.

### `session.check_file(file_path, content=None)`

Checks a file path against directory access rules. If `content` is provided, also scans for:
- **Config file exfiltration** — attempts to read sensitive config files
- **Supply chain threats** — suspicious agent configuration patterns
- All content checks (secrets, prompt injection, context poisoning)

Returns `CheckResult`.

### `session.check_command(command)`

Checks a bash command for:
- **Config exfiltration patterns** — commands that attempt to read/send sensitive files

Returns `CheckResult`.

### `session.sanitize(text)`

Redacts secrets, PII, and sensitive patterns from text.

Returns a dict:
```python
{
    "sanitized_text": "...",
    "redactions": [...],
    "stats": {"secrets": 0, "pii": 0, "total": 0}
}
```

### `session.results`

Property that returns all `CheckResult` objects collected during the session.

### `CheckResult`

Dataclass returned by all check methods.

| Field | Type | Description |
|-------|------|-------------|
| `blocked` | bool | Whether the check triggered a block |
| `detected` | bool | Whether any issue was detected |
| `violation_type` | str or None | Type: `secret_detected`, `prompt_injection`, `context_poisoning`, `directory_blocked`, `config_file_exfil`, `supply_chain_threat` |
| `message` | str or None | Human-readable description |
| `details` | dict or None | Additional context from the detector |

### `SecurityViolation`

Exception raised when a blocked finding is detected. Per-scanner `action` settings in the global config control which findings are blocked.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `result` | `CheckResult` | The check result that triggered the violation |
| `response` | object or None | The original LLM response object (set by `guarded()` and `GuardedAgent` for output violations; `None` for input violations or direct `monitor()` usage) |
| `sanitized_text` | str or None | Redacted version of the response text (`None` if sanitization was unavailable or not applicable) |
| `sanitized_parsed` | Any or absent | Only present when `response_parser` is set on `guarded()`. Contains the parser applied to the violating response, or `None` if the parser raised an error. |

```python
try:
    with monitor() as session:
        session.check_content(untrusted_text)
except SecurityViolation as e:
    print(f"Blocked: {e.result.violation_type} — {e.result.message}")
    if e.sanitized_text:
        print(f"Sanitized: {e.sanitized_text}")
```

## Modes

### Direct Mode (default)

Calls detection functions in-process. No daemon required. Best for single-program use.

```python
with monitor(mode="direct") as session:
    session.check_content(text)
```

### REST Mode

Delegates checks to the ai-guardian daemon via socket protocol. Auto-starts the daemon if not running. Best for shared daemon usage across multiple programs.

```python
with monitor(mode="rest") as session:
    session.check_content(text)
```

**Auto-start behavior:**
1. Checks if daemon is running (socket ping)
2. If not, starts it in the background
3. Waits for daemon to become responsive
4. Proceeds with checks via daemon
5. Does **not** stop daemon on session exit (other programs may use it)

## Action Behavior

Actions are controlled per-scanner in the global config (`ai-guardian.json`), not in SDK calls. Each scanner's `action` field determines what happens when that scanner detects a finding:

- **`"block"`** — the SDK raises `SecurityViolation` immediately
- **`"warn"`** — the SDK emits a Python `warnings.warn` and continues execution
- **`"log"`** — silently recorded; access via `session.results`

```python
with monitor() as session:
    session.check_content(text)  # raises SecurityViolation for blocked findings
```

To treat warnings as errors:

```python
import warnings
warnings.filterwarnings("error", category=UserWarning)

with monitor() as session:
    session.check_content(text)  # warnings promoted to exceptions
```

Access all results (including non-blocked detections) via `session.results`:

```python
with monitor() as session:
    session.check_content(text1)
    session.check_content(text2)

for result in session.results:
    if result.detected:
        print(f"Found: {result.violation_type}")
```

## Examples

### Protect a LangChain Agent

```python
from ai_guardian.sdk import monitor, SecurityViolation

def safe_agent_call(prompt):
    with monitor() as guard:
        # Check user input before sending to LLM
        guard.check_content(prompt)
        
        # Call your LLM
        response = llm.invoke(prompt)
        
        # Check LLM output before returning to user
        guard.check_content(response.content, filename="llm_output")
        
        return response.content
```

### Scan Files Before Processing

```python
from ai_guardian.sdk import monitor

with monitor() as guard:
    for path in uploaded_files:
        content = open(path).read()
        result = guard.check_file(path, content=content)
        if result.blocked:
            print(f"Skipping {path}: {result.message}")
```

### Sanitize Output

```python
from ai_guardian.sdk import monitor

with monitor() as guard:
    sanitized = guard.sanitize(potentially_sensitive_text)
    print(sanitized["sanitized_text"])  # secrets and PII redacted
```

### Batch Content Screening

```python
from ai_guardian.sdk import monitor

with monitor() as guard:
    for item in documents:
        guard.check_content(item.text)
    
    threats = [r for r in guard.results if r.detected]
    print(f"Found {len(threats)} issues in {len(documents)} documents")
```

## Configuration

The SDK respects `ai-guardian.json` configuration. SDK-specific settings live under the `sdk` key:

```json
{
    "sdk": {
        "scanning": true,
        "use_global_config": true
    }
}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `sdk.scanning` | bool | `true` | Enable or disable SDK scanning. When `false`, `guarded()` and `GuardedAgent` pass through without scanning |
| `sdk.use_global_config` | bool | `true` | When `true`, the SDK inherits per-scanner settings (including `action`) from the global config. When `false`, uses only the SDK-local config |

Per-scanner features can be enabled/disabled and their action controlled:

```json
{
    "secret_scanning": {"enabled": true},
    "prompt_injection": {"enabled": true, "action": "block"},
    "context_poisoning": {"enabled": true},
    "config_scanner": {"enabled": true},
    "supply_chain": {"enabled": true}
}
```

Scanning always covers both input and output when enabled. There is no option for partial (input-only or output-only) scanning.

Override configuration per-session (full replacement — no merge):

```python
custom_config = {
    "secret_scanning": {"enabled": True},
    "prompt_injection": {"enabled": False},  # skip for this session
}

with monitor(config=custom_config) as session:
    session.check_content(text)
```

## Config Overlay

The SDK supports a config overlay that deep-merges on top of the resolved config (global + project). The overlay wins for non-immutable fields.

Config hierarchy with overlay:

```
global (~/.config/ai-guardian/ai-guardian.json)
  → project (.ai-guardian/ai-guardian.json)
    → SDK overlay (highest priority)
```

### Programmatic API

```python
from ai_guardian import configure

# Set overlay — deep-merges on top of resolved config
configure(overlay={
    "preferred_ui": "headless",
    "prompt_injection": {"action": "block"},
    "supply_chain": {"action": "block"},
})

# All subsequent monitor() sessions use the overlay
with monitor() as session:
    session.check_content(text)

# Clear overlay
configure(overlay=None)
```

### Environment Variables

For CI/CD and automation where code changes are not possible:

```bash
# File-based overlay (path to JSON file)
AI_GUARDIAN_CONFIG_OVERLAY=/path/to/overlay.json ai-guardian scan

# Inline JSON overlay (quick overrides)
AI_GUARDIAN_CONFIG_INLINE='{"preferred_ui":"headless","prompt_injection":{"action":"block"}}' ai-guardian scan
```

#### Logging Control

Suppress ai-guardian's stderr output by setting the log level:

```bash
# Suppress all messages except errors
AI_GUARDIAN_LOG_LEVEL=ERROR python my_agent.py
```

Or programmatically before importing:

```python
import logging
logging.getLogger("ai_guardian").setLevel(logging.ERROR)
from ai_guardian.sdk import monitor  # respects the pre-set level
```

Valid values: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.

### Overlay Priority

When multiple overlay sources are active, they merge in this order (lowest to highest):

1. `AI_GUARDIAN_CONFIG_OVERLAY` env var (file path)
2. `AI_GUARDIAN_CONFIG_INLINE` env var (inline JSON)
3. `configure(overlay=dict)` (programmatic API)

### Merge Semantics

- **Deep merge**: Overlay `{"prompt_injection": {"action": "block"}}` only changes `action`, preserving other `prompt_injection` fields (detectors, patterns, etc.)
- **Immutable fields respected**: If the global config marks a field as immutable, the overlay cannot override it
- **No global-only restriction**: Unlike project configs, overlays CAN set global-only sections (`daemon`, `mcp_server`, etc.)

### CI/CD Example

```json
{
    "preferred_ui": "headless",
    "prompt_injection": { "action": "block" },
    "config_file_scanning": { "action": "block" },
    "supply_chain": { "action": "block" }
}
```

Save as `ci-overlay.json` and set `AI_GUARDIAN_CONFIG_OVERLAY=ci-overlay.json` in your CI environment.

### Doctor Integration

`ai-guardian doctor` reports active overlay sources:

```bash
AI_GUARDIAN_CONFIG_INLINE='{"preferred_ui":"headless"}' ai-guardian doctor
# Shows: ✓ Config overlay    SDK overlay active: inline env var
```

### Limitations

- **REST mode**: When using `mode="rest"` in `monitor()`, the daemon process has its own config. The overlay only affects the calling process. Set overlay env vars in the daemon's environment for daemon-side effects.
- **`monitor(config=...)` is separate**: The `config` parameter to `monitor()` does full replacement (no merge). Use `configure(overlay=...)` for merge behavior.

## REST API (Multi-Language)

For non-Python languages (TypeScript, Go, Java, Rust, etc.), ai-guardian exposes HTTP endpoints on the daemon's REST API. The daemon must be running:

```bash
ai-guardian daemon start
```

The REST API port is shown in `ai-guardian daemon status`. Default: `19200`.

### POST /api/check

Scan content for security threats.

**Request:**

```bash
curl -X POST http://localhost:19200/api/check \
  -H "Content-Type: application/json" \
  -d '{
    "content": "text to scan",
    "checks": ["secrets", "pii", "injection", "context_poisoning"],
    "action": "block",
    "source": "sdk"
  }'
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `content` | string | **required** | Text to scan |
| `checks` | array | all checks | Which checks to run: `secrets`, `pii`, `injection`, `ssrf`, `context_poisoning` |
| `action` | string | `"block"` | Action mode: `block`, `warn`, or `log` (recorded in findings) |
| `source` | string | `"sdk"` | Optional source identifier for audit trail |

**Response:**

```json
{
  "clean": false,
  "findings": [
    {
      "type": "secret_detected",
      "message": "GitHub token detected",
      "action_taken": "block"
    }
  ],
  "redacted": "text with [REDACTED] token",
  "elapsed_ms": 12.3
}
```

| Field | Type | Description |
|-------|------|-------------|
| `clean` | bool | `true` if no threats detected |
| `findings` | array | List of detected threats |
| `redacted` | string or null | Auto-redacted text (only when findings exist) |
| `elapsed_ms` | float | Processing time in milliseconds |

### POST /api/redact

Redact secrets and PII from text without checking for threats.

**Request:**

```bash
curl -X POST http://localhost:19200/api/redact \
  -H "Content-Type: application/json" \
  -d '{"content": "my token is ghp_abc123..."}'
```

**Response:**

```json
{
  "redacted": "my token is [REDACTED]",
  "redaction_count": 1
}
```

### Authentication

If the daemon has `auth_token` configured in `ai-guardian.json`:

```bash
curl -X POST http://localhost:19200/api/check \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "text to scan"}'
```

### Language SDK Examples

Each language SDK is a thin HTTP client wrapper around these endpoints.

**TypeScript/Node:**

```typescript
const response = await fetch('http://localhost:19200/api/check', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ content: text }),
});
const result = await response.json();
if (!result.clean) {
  throw new Error(result.findings[0].message);
}
```

**Go:**

```go
body, _ := json.Marshal(map[string]string{"content": text})
resp, err := http.Post(
    "http://localhost:19200/api/check",
    "application/json",
    bytes.NewReader(body),
)
var result struct {
    Clean    bool `json:"clean"`
    Findings []struct {
        Type    string `json:"type"`
        Message string `json:"message"`
    } `json:"findings"`
}
json.NewDecoder(resp.Body).Decode(&result)
```

**Java:**

```java
HttpClient client = HttpClient.newHttpClient();
String json = "{\"content\": \"" + text + "\"}";
HttpRequest request = HttpRequest.newBuilder()
    .uri(URI.create("http://localhost:19200/api/check"))
    .header("Content-Type", "application/json")
    .POST(HttpRequest.BodyPublishers.ofString(json))
    .build();
HttpResponse<String> response = client.send(request,
    HttpResponse.BodyHandlers.ofString());
```

**Rust:**

```rust
let client = reqwest::Client::new();
let result: serde_json::Value = client
    .post("http://localhost:19200/api/check")
    .json(&serde_json::json!({"content": text}))
    .send().await?
    .json().await?;
```

**Shell (no SDK needed):**

```bash
result=$(curl -s -X POST http://localhost:19200/api/check \
  -H "Content-Type: application/json" \
  -d "{\"content\": \"$TEXT\"}")
clean=$(echo "$result" | jq -r '.clean')
```

## Anthropic SDK vs Claude Code SDK

GuardedAgent uses the Anthropic SDK (Messages API) directly rather than the Claude Code SDK. This section explains the design choice and when each approach is appropriate.

### Why Anthropic SDK?

| Capability | Anthropic SDK (GuardedAgent) | Claude Code SDK |
|-----------|------------------------------|-----------------|
| **Loop control** | Full — every API call, message, tool execution controlled | Opaque — Claude manages the loop internally |
| **Security scanning** | Every point: input, output, tool results, between turns | Hook boundaries only — no mid-loop inspection |
| **Custom tools** | Define tools, validate inputs, control sandboxing | Built-in tools (Bash, Read, Write) — limited customization |
| **Compaction** | Control when, how, what's preserved | Claude decides |
| **Prompt caching** | Place cache breakpoints optimally | Claude manages |
| **Tracing** | Full per-step trace, OTEL export, Grafana integration | Session log (less structured) |
| **Callbacks** | `before_call`, `after_call`, `between_turns`, `on_turn` | Limited |
| **Structured output** | `output_schema` with `submit_result` tool | Not directly supported |
| **Model choice** | Any Anthropic model, OpenAI-compatible, Vertex AI, Bedrock | Claude models only |
| **Multi-provider** | Anthropic + OpenAI-compatible strategies | Claude only |
| **Dependency** | `anthropic` Python package (lightweight) | Claude Code CLI installed (heavy) |
| **Container / CI** | Runs anywhere with an API key | Requires Claude Code installed |

### When to Use Which

**Use GuardedAgent (Anthropic SDK) when:**

- Building custom agent pipelines with multiple stages
- Need full security scanning at every interaction point
- Need structured output, custom tools, or callbacks
- Running in containers or CI/CD (no CLI installation)
- Need OTEL trace export and observability
- Need multi-provider support (Vertex AI, Bedrock, OpenAI-compatible)

**Use Claude Code with hooks when:**

- Interactive development sessions
- Standard coding tasks with built-in tools
- Claude Code CLI is already installed
- Hook-based security is sufficient (no mid-loop scanning needed)

### Key Advantage

Full control over the agentic loop enables full security coverage. With the Claude Code SDK, scanning happens only at hook boundaries — ai-guardian cannot inspect what the agent does between hooks. GuardedAgent scans every message, every tool result, and every intermediate response because it owns the loop.

## Security Model

- **Additive only**: The SDK adds protection to programs that have none. It cannot disable or bypass hook-based enforcement.
- **No pattern exposure**: `CheckResult` returns blocked/detected status and a human-readable message, not internal detection patterns or regex rules.
- **Same detection engine**: Both direct and REST modes use the same detection functions as the hook system.
- **Config-gated**: Each detector respects its `enabled` flag in the configuration.
