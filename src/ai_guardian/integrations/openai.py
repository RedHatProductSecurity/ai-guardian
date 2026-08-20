"""OpenAI provider extractor and agent loop strategy for ai-guardian."""

import json
import sys
from typing import Any, Dict, List, Optional, Union

from ai_guardian.integrations.base import (
    AgentLoopStrategy,
    ParsedResponse,
    ProviderExtractor,
    ToolCall,
    _CODE_BLOCK_RE,
    _PREAMBLE_PREFIX,
    _extractor_registry,
    _strategy_registry,
)


class OpenAIExtractor(ProviderExtractor):
    """Extracts text from OpenAI SDK chat completions API calls."""

    _CLIENT_NAMES = (
        "OpenAI",
        "AsyncOpenAI",
        "AzureOpenAI",
        "AsyncAzureOpenAI",
    )

    @classmethod
    def detect(cls, client: Any) -> bool:
        openai_mod = sys.modules.get("openai")
        if openai_mod is None:
            return False
        client_classes = []
        for name in cls._CLIENT_NAMES:
            klass = getattr(openai_mod, name, None)
            if klass is not None:
                client_classes.append(klass)
        if not client_classes:
            return False
        return isinstance(client, tuple(client_classes))

    def methods_to_wrap(self) -> List[str]:
        return ["chat.completions.create"]

    def extract_input(self, method_name: str, args: tuple, kwargs: dict) -> List[str]:
        parts: List[str] = []
        messages = kwargs.get("messages", [])
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, str) and content:
                parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            parts.append(text)
                    elif isinstance(block, str) and block:
                        parts.append(block)
        return parts

    def extract_output(self, method_name: str, response: Any) -> List[str]:
        parts: List[str] = []
        choices = getattr(response, "choices", None)
        if not isinstance(choices, list):
            return parts
        for choice in choices:
            message = getattr(choice, "message", None)
            if message is None:
                continue
            content = getattr(message, "content", None)
            if isinstance(content, str) and content:
                parts.append(content)
        return parts


for _name in OpenAIExtractor._CLIENT_NAMES:
    _extractor_registry.register(f"openai.{_name}", OpenAIExtractor)


# ---------------------------------------------------------------------------
# OpenAI agent loop strategy
# ---------------------------------------------------------------------------


def _anthropic_tool_to_openai(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an Anthropic-format custom tool dict to OpenAI function format."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {}),
        },
    }


def _build_openai_tools() -> Dict[str, Dict[str, Any]]:
    """Build OpenAI tool defs, deriving grep/glob from Anthropic schemas."""
    from ai_guardian.integrations.anthropic.tools import _CUSTOM_TOOL_SCHEMAS

    tools: Dict[str, Dict[str, Any]] = {
        "bash": {
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Run a bash command and return its output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The bash command to execute.",
                        },
                        "restart": {
                            "type": "boolean",
                            "description": "Restart the shell session.",
                        },
                    },
                    "required": ["command"],
                },
            },
        },
        "text_editor": {
            "type": "function",
            "function": {
                "name": "str_replace_based_edit_tool",
                "description": (
                    "View, create, or edit files. Commands: view, create, "
                    "str_replace, insert."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "enum": ["view", "create", "str_replace", "insert"],
                            "description": "The operation to perform.",
                        },
                        "path": {
                            "type": "string",
                            "description": "Relative file path.",
                        },
                        "file_text": {
                            "type": "string",
                            "description": "File content for create command.",
                        },
                        "old_str": {
                            "type": "string",
                            "description": "Text to find for str_replace.",
                        },
                        "new_str": {
                            "type": "string",
                            "description": "Replacement text.",
                        },
                        "insert_line": {
                            "type": "integer",
                            "description": "Line number for insert command.",
                        },
                        "view_range": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "[start_line, end_line] for view.",
                        },
                    },
                    "required": ["command", "path"],
                },
            },
        },
    }
    for name, schema in _CUSTOM_TOOL_SCHEMAS.items():
        tools[name] = _anthropic_tool_to_openai(schema)
    return tools


def _build_openai_presets(
    available: Dict[str, Any],
) -> Dict[str, List[str]]:
    """Derive OpenAI presets from Anthropic presets, filtering unavailable tools."""
    from ai_guardian.integrations.anthropic.tools import _PRESETS

    return {
        preset: [t for t in tool_names if t in available]
        for preset, tool_names in _PRESETS.items()
    }


_OPENAI_CUSTOM_TOOLS: Dict[str, Dict[str, Any]] = _build_openai_tools()
_OPENAI_PRESETS: Dict[str, List[str]] = _build_openai_presets(_OPENAI_CUSTOM_TOOLS)

_OPENAI_STOP_MAP: Dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "end_turn",
    "content_filter": "refusal",
}


def _resolve_openai_tools(
    tools: Union[str, List[Any]],
    tool_types: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Resolve a tool specification into OpenAI function-call format."""
    if isinstance(tools, str):
        names = _OPENAI_PRESETS.get(tools, [tools])
        return [_resolve_openai_single(n) for n in names]

    result: List[Dict[str, Any]] = []
    for item in tools:
        if isinstance(item, str):
            if item in _OPENAI_PRESETS:
                for name in _OPENAI_PRESETS[item]:
                    result.append(_resolve_openai_single(name))
            else:
                result.append(_resolve_openai_single(item))
        elif isinstance(item, dict):
            if "type" not in item and "name" in item:
                result.append(_anthropic_tool_to_openai(item))
            else:
                result.append(item)
        else:
            raise ValueError(f"Invalid tool spec: {item!r}")
    return result


def _resolve_openai_single(name: str) -> Dict[str, Any]:
    if name in _OPENAI_CUSTOM_TOOLS:
        return dict(_OPENAI_CUSTOM_TOOLS[name])
    raise ValueError(
        f"Unknown tool: {name!r}. "
        f"Known tools: {sorted(_OPENAI_CUSTOM_TOOLS.keys())}"
    )


class OpenAILoopStrategy(AgentLoopStrategy):
    """Agent loop strategy for OpenAI's chat completions API."""

    @property
    def api_method_name(self) -> str:
        return "chat.completions.create"

    def create_default_client(self) -> Any:
        import openai

        return openai.OpenAI()

    def resolve_tools(
        self,
        tools: Union[str, List[Any]],
        tool_types: Optional[Dict[str, str]] = None,
    ) -> List[Any]:
        return _resolve_openai_tools(tools, tool_types)

    def format_submit_result_tool(
        self, output_schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "submit_result",
                "description": (
                    "Submit the final structured result. "
                    "Call this as your last action when the task is complete."
                ),
                "parameters": output_schema,
            },
        }

    def inject_preamble(self, kwargs: Dict[str, Any], preamble: str) -> None:
        prefix = f"{_PREAMBLE_PREFIX}{preamble}\n\n"
        messages = kwargs.get("messages")
        if not messages:
            return
        if isinstance(messages[0], dict) and messages[0].get("role") == "system":
            content = messages[0].get("content", "")
            kwargs["messages"] = [dict(messages[0], content=prefix + content)] + list(
                messages[1:]
            )

    def build_create_kwargs(
        self,
        *,
        model: str,
        max_tokens: int,
        tools: List[Any],
        messages: List[Dict[str, Any]],
        system: str,
        cache_ttl: Optional[Union[str, int]] = None,
    ) -> Dict[str, Any]:
        if system:
            full_messages = [{"role": "system", "content": system}] + messages
        else:
            full_messages = messages
        kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": full_messages,
        }
        if tools:
            kwargs["tools"] = tools
        return kwargs

    def call_api(self, client: Any, kwargs: Dict[str, Any]) -> Any:
        from ai_guardian.integrations.openai_compat import (
            get_provider_caps,
            normalize_request_kwargs,
        )

        provider = getattr(client, "_ai_guardian_provider", None)
        caps = get_provider_caps(provider)
        kwargs = normalize_request_kwargs(kwargs, caps)
        return client.chat.completions.create(**kwargs)

    def parse_response(self, response: Any) -> ParsedResponse:
        choices = getattr(response, "choices", [])
        if not choices:
            return ParsedResponse(stop_reason="end_turn", text="")

        choice = choices[0]
        message = getattr(choice, "message", None)
        finish_reason = getattr(choice, "finish_reason", "stop")

        stop_reason = _OPENAI_STOP_MAP.get(finish_reason, finish_reason)

        text = ""
        if message is not None:
            text = getattr(message, "content", "") or ""

        tool_calls: List[ToolCall] = []
        raw_tool_calls = getattr(message, "tool_calls", None) if message else None
        if raw_tool_calls:
            for tc in raw_tool_calls:
                fn = getattr(tc, "function", None)
                if fn is None:
                    continue
                try:
                    args = json.loads(getattr(fn, "arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=getattr(tc, "id", ""),
                        name=getattr(fn, "name", ""),
                        input=args,
                    )
                )

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        return ParsedResponse(
            stop_reason=stop_reason,
            text=text,
            tool_calls=tool_calls,
            raw_content=message,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def format_tool_result(
        self,
        tool_call_id: str,
        content: str,
        is_error: bool = False,
    ) -> Dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        }

    def serialize_assistant_content(self, raw_content: Any) -> Any:
        return self._message_to_dict(raw_content)

    def replace_response_text(self, raw_content: Any, sanitized_text: str) -> Any:
        from types import SimpleNamespace

        ns = SimpleNamespace(content=sanitized_text)
        tool_calls = getattr(raw_content, "tool_calls", None)
        if tool_calls:
            ns.tool_calls = tool_calls
        return ns

    def append_assistant_and_results(
        self,
        messages: List[Dict[str, Any]],
        raw_content: Any,
        tool_results: List[Dict[str, Any]],
    ) -> None:
        messages.append(self._message_to_dict(raw_content))
        for tr in tool_results:
            messages.append(tr)

    def truncate_tool_result(self, message: Dict[str, Any], max_lines: int) -> None:
        if message.get("role") != "tool":
            return
        text = message.get("content", "")
        if not isinstance(text, str):
            return
        lines = text.split("\n")
        if len(lines) > max_lines:
            message["content"] = (
                f"[truncated: {len(lines) - max_lines} lines removed]\n"
                + "\n".join(lines[-max_lines:])
            )

    def strip_code_blocks(self, message: Dict[str, Any]) -> None:
        if message.get("role") != "assistant":
            return
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = _CODE_BLOCK_RE.sub("[code block removed]", content)

    def create_compaction_boundary(self, dropped_count: int) -> List[Dict[str, Any]]:
        return [
            {
                "role": "assistant",
                "content": (
                    f"[Conversation compacted: {dropped_count} turn(s) "
                    f"removed to stay within context window]"
                ),
            },
            {
                "role": "user",
                "content": "Continue from the remaining context.",
            },
        ]

    @classmethod
    def detect(cls, client: Any) -> bool:
        return hasattr(client, "chat")

    @staticmethod
    def _message_to_dict(message: Any) -> Dict[str, Any]:
        """Convert an OpenAI message object to a serializable dict."""
        content = getattr(message, "content", None)
        msg: Dict[str, Any] = {"role": "assistant", "content": content}
        raw_tool_calls = getattr(message, "tool_calls", None)
        if raw_tool_calls:
            msg["tool_calls"] = [
                {
                    "id": getattr(tc, "id", ""),
                    "type": "function",
                    "function": {
                        "name": getattr(getattr(tc, "function", None), "name", ""),
                        "arguments": getattr(
                            getattr(tc, "function", None), "arguments", "{}"
                        ),
                    },
                }
                for tc in raw_tool_calls
            ]
        return msg


for _name in OpenAIExtractor._CLIENT_NAMES:
    _strategy_registry.register(f"openai.{_name}", OpenAILoopStrategy)
