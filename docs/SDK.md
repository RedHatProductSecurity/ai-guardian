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
with monitor(action="block") as session:
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
client = guarded(action="block")
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

client = guarded(Anthropic(), action="block")
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
    action="block",
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

client = guarded(AnthropicBedrock(), action="block")
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

client = guarded(OpenAI(), action="block")
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
    action="block",
)
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": user_input}],
)
```

### `create_client(**kwargs)`

Auto-detect and create an Anthropic client from environment variables.

```python
from ai_guardian.integrations import create_client

# Returns the right client type based on which env var is set
client = create_client()

# Pass kwargs to the underlying client constructor
client = create_client(timeout=30.0)
```

Raises `ValueError` if multiple conflicting env vars are set, or if none are set.

### `guarded(client, *, name, action, mode, config, extractor, scan_input, scan_output, response_parser, before_call, after_call)`

Wraps an LLM client with automatic security scanning.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `client` | object | *(auto-detect)* | LLM provider client. If omitted, auto-created from env vars. |
| `name` | str | `None` | Profile name linking to `sdk.clients.<name>` in `ai-guardian.json`. Config values override code-provided parameters |
| `action` | str | `"block"` | `"block"` raises `SecurityViolation`, `"warn"` emits warning, `"log"` records silently |
| `mode` | str | `"direct"` | `"direct"` runs checks in-process, `"rest"` delegates to daemon |
| `config` | dict | `None` | Config override. If `None`, loads from `ai-guardian.json` |
| `extractor` | ProviderExtractor | `None` | Explicit extractor (skips auto-detection) |
| `scan_input` | bool | `True` | Scan prompts before sending to LLM |
| `scan_output` | bool | `True` | Scan responses after receiving from LLM |
| `response_parser` | callable | `None` | `(client_type: str, response) -> Any` — transforms native responses into a caller-defined format. If `None`, native response returned unchanged. |
| `before_call` | callable | `None` | `(method_name: str, args: tuple, kwargs: dict) -> None` — called before each API call |
| `after_call` | callable | `None` | `(method_name: str, response: Any) -> None` — called after each successful API call. Not called on `SecurityViolation` |

**Returns:** A wrapped client proxy. Use it exactly like the original client. If `response_parser` is set, calls return the parser's output instead of the native response.

**Raises:**

- `ValueError` if no extractor matches the client type and none provided explicitly
- `SecurityViolation` when `action="block"` and a threat is detected. If `response_parser` is set, the exception's `sanitized_parsed` attribute contains the parser applied to the violating response.

### What Gets Scanned

**Input** (before API call): system prompt, all message content — checked for secrets, prompt injection, context poisoning, PII.

**Output** (after API call): response text content blocks — same checks.

### Streaming

For `messages.stream()`, input is scanned before the stream starts. Output is scanned on the accumulated final message when the stream context exits — individual chunks are not scanned.

```python
client = guarded(Anthropic(), action="block")

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
client = guarded(Anthropic(), action="block")
response = client.messages.create(...)  # returns Anthropic Message object

# With parser — caller's unified format
client = guarded(Anthropic(), action="block", response_parser=my_parser)
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
    action="block",
    before_call=on_call,
    after_call=on_response,
)
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
    action="block",
)
result = agent.run("Find and fix the bug described in JIRA-123")
print(result["output"])
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

- **Client tools** (`bash`, `text_editor`, `read_file`, `grep`, `glob`): GuardedAgent executes these locally in the agent's `cwd`. Tool output (results) is scanned by ai-guardian before returning to the model.
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
| `grep` | Search for a regex pattern in files (uses system `grep -rn`, skips common non-code directories) |
| `glob` | List files matching a glob pattern (skips common non-code directories) |

##### Input Schemas

**`read_file`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Absolute or relative path to the file to read |
| `offset` | integer | no | Line number to start reading from (0-based) |
| `limit` | integer | no | Maximum number of lines to read |

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

#### Presets

| Preset | Tools | Use when |
|--------|-------|----------|
| `"coding"` | `bash` + `text_editor` + `grep` + `glob` | Agent needs to read, write, and execute code |
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

Pass raw tool dicts alongside built-in names to define additional tools the model can call. GuardedAgent dispatches tool calls by name — built-in names (`bash`, `text_editor`, `read_file`, `grep`, `glob`) route to their executors; unknown names return `"Error: no executor for tool 'name'"` as the tool result.

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
| `action` | str | `"block"` | `"block"`, `"warn"`, or `"log"` |
| `client` | Any | `None` | Anthropic or OpenAI client (auto-detected if omitted) |
| `mode` | str | `"direct"` | `"direct"` or `"rest"` for scanning |
| `config` | dict | `None` | ai-guardian config override |
| `output_schema` | dict | `None` | JSON schema for structured output |
| `tool_types` | dict | `None` | Override tool type versions |
| `scan_input` | bool | `True` | Scan prompts before sending |
| `scan_output` | bool | `True` | Scan responses and tool results |
| `before_call` | callable | `None` | `(method_name: str, args: tuple, kwargs: dict) -> None` — called before each `messages.create()` |
| `after_call` | callable | `None` | `(method_name: str, response: Any) -> Optional[bool]` — called after each API call. Return `False` to stop the loop early |
| `pre_run` | callable | `None` | `(prompt: str, config: dict) -> None` — called once before the agent loop starts |
| `post_run` | callable | `None` | `(result: dict) -> None` — called once after the agent loop ends (even on exceptions, with `result=None`) |
| `between_turns` | callable | `None` | `(messages: list, response: Any, turn: int) -> str \| None \| False` — called after each successful assistant turn. Return `str` to inject as next user message, `None` to continue normally, `False` to stop the loop |
| `on_turn` | callable | `None` | `(turn: int, event: TurnEvent) -> None` — live callback fired per event. See [Observability](#observability) |
| `strategy` | AgentLoopStrategy | `None` | Explicit loop strategy. Auto-detected from `client` if omitted. Use `OpenAILoopStrategy()` for OpenAI clients |
| `cache_ttl` | str or int | `None` | Prompt caching TTL. Anthropic: `"5m"` or `"1h"` (auto-enabled for multi-turn). `0` = disabled |
| `auto_compact` | bool | `True` | Enable context-window monitoring. When `True`, checks token usage each turn |
| `compact_threshold` | float | `1.0` | Ratio of input tokens to context window that triggers compaction. `1.0` = no compaction (raises `RuntimeError` when context exhausted). Set to `0.8` to compact at 80% usage |
| `compact_keep_turns` | int | `5` | Number of recent turn pairs to preserve during compaction |
| `compact_keep_first` | int | `1` | Number of initial turn pairs to preserve during compaction |
| `name` | str | `None` | Profile name linking to `sdk.agents.<name>` in `ai-guardian.json`. Config values override code-provided parameters |

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
  ├── pre_run(prompt, config)          ← once, before loop
  ├── Turn 1:
  │     ├── before_call(...)           ← per turn
  │     ├── messages.create()
  │     ├── after_call(...)            ← per turn (return False to stop)
  │     └── between_turns(...)         ← per successful turn (return str to inject)
  ├── Turn 2+:
  │     ├── auto_compact check         ← compacts or raises if context exhausted
  │     ├── before_call(...)
  │     ├── messages.create()
  │     ├── after_call(...)
  │     └── between_turns(...)
  └── post_run(result)                 ← once, after loop (even on exception)
```

The `config` dict passed to `pre_run` contains: `model`, `tools`, `system_prompt`, `max_turns`, `max_budget_tokens`.

### `between_turns` Hook

Runs after each successful assistant turn — both `end_turn` (text response) and `tool_use` (after tool execution). Does **not** fire on refusal, budget exceeded, or output-schema nudges.

| Return | Behavior |
|--------|----------|
| `str` | Injected as next user message, loop continues |
| `None` | Normal loop behavior (tool execution or end) |
| `False` | Stop the loop (`stop_reason: "hook_early_stop"`) |

Injected messages are scanned by ai-guardian when `scan_input=True`.

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

### Auto-Compaction

Long conversations can exceed the model's context window. Auto-compaction shrinks the conversation by truncating old tool results, stripping code blocks, and dropping middle turns.

By default, compaction is **disabled** (`compact_threshold=1.0`). When the context window is exhausted, a `RuntimeError` is raised with instructions to enable compaction.

```python
# Enable compaction at 80% of context window
agent = GuardedAgent(
    model="claude-sonnet-5",
    tools="coding",
    compact_threshold=0.8,
)
```

Compaction preserves the first turn pair (`compact_keep_first`) and the most recent turn pairs (`compact_keep_turns`), dropping everything in between. A boundary message marks where turns were removed.

To fully disable context monitoring (no check, no error), set `auto_compact=False`.

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

Always collected (no opt-in needed). Returned in `run()` result:

```python
result = agent.run("review this code")

result["trace"] = [
    {"turn": 0, "type": "system", "system_prompt": "You are...", "user_prompt": "review this code"},
    {"turn": 1, "type": "response", "text": "I'll start by reading...", "stop_reason": "tool_use",
     "usage": {"input_tokens": 500, "output_tokens": 120}},
    {"turn": 1, "type": "tool_call", "name": "bash", "input": {"command": "grep -rn 'TODO' src/"}},
    {"turn": 1, "type": "tool_result", "name": "bash", "output": "src/main.py:42: # TODO fix auth"},
    {"turn": 1, "type": "scan", "scanned": "assistant_response", "violations": []},
    {"turn": 1, "type": "scan", "scanned": "tool_result:bash", "violations": []},
    {"turn": 2, "type": "response", "text": "Found one issue...", "stop_reason": "end_turn",
     "usage": {"input_tokens": 800, "output_tokens": 200}},
    {"turn": 2, "type": "scan", "scanned": "assistant_response", "violations": []},
]
```

#### Event Types

| Turn | Event type | Fields |
|------|-----------|--------|
| 0 | `system` | `preamble` (from config, once), `system_prompt` (from code, once), `user_prompt` |
| 0 | `scan` | `scanned` (`"system_prompt"` or `"user_prompt"`), `violations` |
| N | `response` | `text`, `stop_reason`, `usage` |
| N | `tool_call` | `name`, `input` |
| N | `tool_result` | `name`, `output` |
| N | `scan` | `scanned` (what was scanned), `violations` (list) |

#### `TurnEvent` Dataclass

```python
@dataclass
class TurnEvent:
    type: str                          # "system" | "response" | "tool_call" | "tool_result" | "scan"
    text: Optional[str] = None
    name: Optional[str] = None
    input: Optional[dict] = None
    output: Optional[str] = None
    preamble: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    usage: Optional[dict] = None
    stop_reason: Optional[str] = None
    violations: Optional[list] = field(default_factory=list)
    scanned: Optional[str] = None
```

### `agent.run(prompt)` Return Value

```python
{
    "output": "...",       # final text or structured object
    "messages": [...],     # full conversation history
    "stop_reason": "...",  # "end_turn", "refusal", "max_turns", "budget_exceeded", "hook_early_stop", or "pause_turn"
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

## API Reference

### `monitor(action, mode, config)`

Context manager that creates a guarded session.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | str | `"block"` | `"block"` raises `SecurityViolation`, `"warn"` emits warning, `"log"` records silently |
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

Exception raised when `action="block"` and a threat is detected.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `result` | `CheckResult` | The check result that triggered the violation |
| `response` | object or None | The original LLM response object (set by `guarded()` and `GuardedAgent` for output violations; `None` for input violations or direct `monitor()` usage) |
| `sanitized_text` | str or None | Redacted version of the response text (`None` if sanitization was unavailable or not applicable) |
| `sanitized_parsed` | Any or absent | Only present when `response_parser` is set on `guarded()`. Contains the parser applied to the violating response, or `None` if the parser raised an error. |

```python
try:
    with monitor(action="block") as session:
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

## Action Modes

### `"block"` (default)

Raises `SecurityViolation` immediately when a threat is detected. Use for strict enforcement.

```python
with monitor(action="block") as session:
    session.check_content(text)  # raises SecurityViolation if threat found
```

### `"warn"`

Emits a Python `UserWarning` when a threat is detected. Execution continues.

```python
import warnings
warnings.filterwarnings("error", category=UserWarning)  # optional: treat as error

with monitor(action="warn") as session:
    session.check_content(text)  # warnings.warn() if threat found
```

### `"log"`

Silently records results. No exceptions, no warnings. Access results via `session.results`.

```python
with monitor(action="log") as session:
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
    with monitor(action="block") as guard:
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

with monitor(action="warn") as guard:
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

with monitor(action="log") as guard:
    for item in documents:
        guard.check_content(item.text)
    
    threats = [r for r in guard.results if r.detected]
    print(f"Found {len(threats)} issues in {len(documents)} documents")
```

## Configuration

The SDK respects `ai-guardian.json` configuration. Features can be enabled/disabled:

```json
{
    "secret_scanning": {"enabled": true},
    "prompt_injection": {"enabled": true, "action": "block"},
    "context_poisoning": {"enabled": true},
    "config_scanner": {"enabled": true},
    "supply_chain": {"enabled": true}
}
```

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

## Security Model

- **Additive only**: The SDK adds protection to programs that have none. It cannot disable or bypass hook-based enforcement.
- **No pattern exposure**: `CheckResult` returns blocked/detected status and a human-readable message, not internal detection patterns or regex rules.
- **Same detection engine**: Both direct and REST modes use the same detection functions as the hook system.
- **Config-gated**: Each detector respects its `enabled` flag in the configuration.
