"""Google Gemini provider extractor and agent loop strategy for ai-guardian."""

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


class GeminiExtractor(ProviderExtractor):
    """Extracts text from Google Gemini SDK generate_content calls."""

    @classmethod
    def detect(cls, client: Any) -> bool:
        genai_mod = sys.modules.get("google.genai")
        if genai_mod is None:
            return False
        client_cls = getattr(genai_mod, "Client", None)
        if client_cls is None:
            return False
        return isinstance(client, client_cls)

    def methods_to_wrap(self) -> List[str]:
        return ["models.generate_content"]

    def extract_input(self, method_name: str, args: tuple, kwargs: dict) -> List[str]:
        parts: List[str] = []

        config = kwargs.get("config")
        if config is not None:
            si = None
            if isinstance(config, dict):
                si = config.get("system_instruction")
            else:
                si = getattr(config, "system_instruction", None)
            if isinstance(si, str) and si:
                parts.append(si)

        contents = kwargs.get("contents")
        if contents is None and args:
            contents = args[1] if len(args) > 1 else args[0]

        if isinstance(contents, str):
            if contents:
                parts.append(contents)
        elif isinstance(contents, list):
            for item in contents:
                parts.extend(_extract_text_from_content(item))

        return parts

    def extract_output(self, method_name: str, response: Any) -> List[str]:
        parts: List[str] = []
        text = getattr(response, "text", None)
        if isinstance(text, str) and text:
            return [text]
        candidates = getattr(response, "candidates", None)
        if isinstance(candidates, list):
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                if content is None:
                    continue
                content_parts = getattr(content, "parts", None)
                if not isinstance(content_parts, list):
                    continue
                for part in content_parts:
                    t = getattr(part, "text", None)
                    if isinstance(t, str) and t:
                        parts.append(t)
        return parts


_extractor_registry.register("google.genai.Client", GeminiExtractor)


def _extract_text_from_content(item: Any) -> List[str]:
    """Extract text strings from a Gemini content item."""
    if isinstance(item, str):
        return [item] if item else []

    if isinstance(item, dict):
        item_parts = item.get("parts", [])
        if isinstance(item_parts, list):
            texts = []
            for p in item_parts:
                if isinstance(p, dict):
                    t = p.get("text", "")
                    if t:
                        texts.append(t)
                elif isinstance(p, str) and p:
                    texts.append(p)
            return texts
        text = item.get("text", "")
        return [text] if text else []

    content_parts = getattr(item, "parts", None)
    if isinstance(content_parts, list):
        texts = []
        for p in content_parts:
            t = getattr(p, "text", None) if not isinstance(p, str) else p
            if isinstance(t, str) and t:
                texts.append(t)
        return texts
    return []


# ---------------------------------------------------------------------------
# Gemini agent loop strategy
# ---------------------------------------------------------------------------

_GEMINI_STOP_MAP: Dict[str, str] = {
    "STOP": "end_turn",
    "MAX_TOKENS": "end_turn",
    "SAFETY": "refusal",
    "RECITATION": "refusal",
    "BLOCKLIST": "refusal",
    "PROHIBITED_CONTENT": "refusal",
    "SPII": "refusal",
}


def _anthropic_tool_to_gemini(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an Anthropic-format tool dict to a Gemini function_declaration."""
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool.get("input_schema", {}),
    }


def _build_gemini_tools() -> Dict[str, Dict[str, Any]]:
    """Build Gemini function_declaration defs from Anthropic tool schemas."""
    from ai_guardian.integrations.anthropic.tools import _CUSTOM_TOOL_SCHEMAS

    tools: Dict[str, Dict[str, Any]] = {
        "bash": {
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
        "text_editor": {
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
    }
    for name, schema in _CUSTOM_TOOL_SCHEMAS.items():
        tools[name] = _anthropic_tool_to_gemini(schema)
    return tools


def _build_gemini_presets(
    available: Dict[str, Any],
) -> Dict[str, List[str]]:
    """Derive Gemini presets from Anthropic presets, filtering unavailable tools."""
    from ai_guardian.integrations.anthropic.tools import _PRESETS

    return {
        preset: [t for t in tool_names if t in available]
        for preset, tool_names in _PRESETS.items()
    }


_GEMINI_CUSTOM_TOOLS: Dict[str, Dict[str, Any]] = _build_gemini_tools()
_GEMINI_PRESETS: Dict[str, List[str]] = _build_gemini_presets(_GEMINI_CUSTOM_TOOLS)


def _resolve_gemini_tools(
    tools: Union[str, List[Any]],
    tool_types: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Resolve a tool specification into Gemini function_declaration format."""
    if isinstance(tools, str):
        names = _GEMINI_PRESETS.get(tools, [tools])
        return [_resolve_gemini_single(n) for n in names]

    result: List[Dict[str, Any]] = []
    for item in tools:
        if isinstance(item, str):
            if item in _GEMINI_PRESETS:
                for name in _GEMINI_PRESETS[item]:
                    result.append(_resolve_gemini_single(name))
            else:
                result.append(_resolve_gemini_single(item))
        elif isinstance(item, dict):
            if "name" in item and "input_schema" in item:
                result.append(_anthropic_tool_to_gemini(item))
            elif "name" in item:
                result.append(item)
            else:
                result.append(item)
        else:
            raise ValueError(f"Invalid tool spec: {item!r}")
    return result


def _resolve_gemini_single(name: str) -> Dict[str, Any]:
    if name in _GEMINI_CUSTOM_TOOLS:
        return dict(_GEMINI_CUSTOM_TOOLS[name])
    raise ValueError(
        f"Unknown tool: {name!r}. "
        f"Known tools: {sorted(_GEMINI_CUSTOM_TOOLS.keys())}"
    )


def _part_to_dict(part: Any) -> Dict[str, Any]:
    """Convert a Gemini Part SDK object to a serializable dict."""
    fc = getattr(part, "function_call", None)
    if fc is not None:
        args = getattr(fc, "args", None)
        if args is not None and not isinstance(args, dict):
            try:
                args = dict(args)
            except (TypeError, ValueError):
                args = {}
        return {
            "function_call": {
                "name": getattr(fc, "name", ""),
                "args": args or {},
            }
        }
    text = getattr(part, "text", None)
    if text is not None:
        return {"text": text}
    return {"text": str(part)}


class GeminiLoopStrategy(AgentLoopStrategy):
    """Agent loop strategy for Google Gemini's generate_content API."""

    @property
    def api_method_name(self) -> str:
        return "models.generate_content"

    def create_default_client(self) -> Any:
        try:
            from google import genai
        except ImportError:
            raise ImportError(
                "The 'google-genai' package is required for Google Gemini. "
                "Install it with: pip install ai-guardian[gemini]"
            ) from None
        return genai.Client()

    def resolve_tools(
        self,
        tools: Union[str, List[Any]],
        tool_types: Optional[Dict[str, str]] = None,
    ) -> List[Any]:
        return _resolve_gemini_tools(tools, tool_types)

    def format_submit_result_tool(
        self, output_schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "name": "submit_result",
            "description": (
                "Submit the final structured result. "
                "Call this as your last action when the task is complete."
            ),
            "parameters": output_schema,
        }

    def inject_preamble(self, kwargs: Dict[str, Any], preamble: str) -> None:
        prefix = f"{_PREAMBLE_PREFIX}{preamble}\n\n"
        config = kwargs.get("config")
        if not isinstance(config, dict):
            return
        si = config.get("system_instruction", "")
        if isinstance(si, str):
            config["system_instruction"] = prefix + si

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
        config: Dict[str, Any] = {
            "max_output_tokens": max_tokens,
        }
        if system:
            config["system_instruction"] = system
        if tools:
            config["tools"] = [{"function_declarations": tools}]
        return {
            "model": model,
            "contents": messages,
            "config": config,
        }

    def call_api(
        self, client: Any, kwargs: Dict[str, Any], timeout: Optional[int] = None
    ) -> Any:
        if timeout is not None:
            kwargs = dict(kwargs, timeout=float(timeout))
        return client.models.generate_content(**kwargs)

    def parse_response(self, response: Any) -> ParsedResponse:
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return ParsedResponse(stop_reason="end_turn", text="")

        candidate = candidates[0]
        finish_reason = getattr(candidate, "finish_reason", None)
        if finish_reason is not None:
            finish_str = (
                finish_reason.name
                if hasattr(finish_reason, "name")
                else str(finish_reason)
            )
        else:
            finish_str = "STOP"

        content = getattr(candidate, "content", None)
        raw_parts = getattr(content, "parts", []) if content else []

        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []

        for i, part in enumerate(raw_parts):
            fc = getattr(part, "function_call", None)
            if fc is not None:
                fc_name = getattr(fc, "name", "")
                fc_args = getattr(fc, "args", None)
                if fc_args is not None and not isinstance(fc_args, dict):
                    try:
                        fc_args = dict(fc_args)
                    except (TypeError, ValueError):
                        fc_args = {}
                fc_id = getattr(fc, "id", None) or f"{fc_name}_{i}"
                tool_calls.append(ToolCall(id=fc_id, name=fc_name, input=fc_args or {}))
            else:
                t = getattr(part, "text", None)
                if isinstance(t, str) and t:
                    text_parts.append(t)

        stop_reason = _GEMINI_STOP_MAP.get(finish_str, finish_str)
        if tool_calls:
            stop_reason = "tool_use"

        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        serialized_parts = [_part_to_dict(p) for p in raw_parts]

        return ParsedResponse(
            stop_reason=stop_reason,
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            raw_content=serialized_parts,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def format_tool_result(
        self,
        tool_call_id: str,
        content: str,
        is_error: bool = False,
    ) -> Dict[str, Any]:
        result_payload: Dict[str, Any] = {"result": content}
        if is_error:
            result_payload["error"] = content
        return {
            "function_response": {
                "name": (
                    tool_call_id.rsplit("_", 1)[0]
                    if "_" in tool_call_id
                    else tool_call_id
                ),
                "response": result_payload,
            }
        }

    def serialize_assistant_content(self, raw_content: Any) -> Any:
        if isinstance(raw_content, list):
            result = []
            for item in raw_content:
                if isinstance(item, dict):
                    result.append(item)
                else:
                    result.append(_part_to_dict(item))
            return result
        return raw_content

    def append_assistant_message(
        self,
        messages: List[Dict[str, Any]],
        raw_content: Any,
    ) -> None:
        messages.append(
            {
                "role": "model",
                "parts": self.serialize_assistant_content(raw_content),
            }
        )

    def replace_response_text(self, raw_content: Any, sanitized_text: str) -> Any:
        if not isinstance(raw_content, list):
            return raw_content
        result = []
        text_replaced = False
        for item in raw_content:
            is_text = False
            if isinstance(item, dict):
                is_text = "text" in item and "function_call" not in item
            else:
                is_text = (
                    getattr(item, "text", None) is not None
                    and getattr(item, "function_call", None) is None
                )
            if is_text and not text_replaced:
                result.append({"text": sanitized_text})
                text_replaced = True
            elif not is_text:
                result.append(item if isinstance(item, dict) else _part_to_dict(item))
        return result if text_replaced else raw_content

    def append_assistant_and_results(
        self,
        messages: List[Dict[str, Any]],
        raw_content: Any,
        tool_results: List[Dict[str, Any]],
    ) -> None:
        messages.append(
            {
                "role": "model",
                "parts": self.serialize_assistant_content(raw_content),
            }
        )
        messages.append({"role": "user", "parts": tool_results})

    def inject_user_text_after_results(
        self,
        messages: List[Dict[str, Any]],
        text: str,
    ) -> None:
        last = messages[-1]
        if last.get("role") == "user" and isinstance(last.get("parts"), list):
            last["parts"].append({"text": text})
        else:
            messages.append({"role": "user", "parts": [{"text": text}]})

    def truncate_tool_result(self, message: Dict[str, Any], max_lines: int) -> None:
        if message.get("role") != "user":
            return
        parts = message.get("parts")
        if not isinstance(parts, list):
            return
        for part in parts:
            if not isinstance(part, dict):
                continue
            fr = part.get("function_response")
            if not isinstance(fr, dict):
                continue
            resp = fr.get("response", {})
            if not isinstance(resp, dict):
                continue
            text = resp.get("result", "")
            if not isinstance(text, str):
                continue
            lines = text.split("\n")
            if len(lines) > max_lines:
                resp["result"] = (
                    f"[truncated: {len(lines) - max_lines} lines removed]\n"
                    + "\n".join(lines[-max_lines:])
                )

    def strip_code_blocks(self, message: Dict[str, Any]) -> None:
        if message.get("role") != "model":
            return
        parts = message.get("parts")
        if not isinstance(parts, list):
            return
        for part in parts:
            if isinstance(part, dict) and "text" in part:
                text = part["text"]
                if "```" in text:
                    part["text"] = _CODE_BLOCK_RE.sub("[code block removed]", text)

    def create_compaction_boundary(self, dropped_count: int) -> List[Dict[str, Any]]:
        return [
            {
                "role": "model",
                "parts": [
                    {
                        "text": (
                            f"[Conversation compacted: {dropped_count} turn(s) "
                            f"removed to stay within context window]"
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "parts": [{"text": "Continue from the remaining context."}],
            },
        ]

    @classmethod
    def detect(cls, client: Any) -> bool:
        return hasattr(client, "models") and hasattr(
            getattr(client, "models", None), "generate_content"
        )


_strategy_registry.register("google.genai.Client", GeminiLoopStrategy)
