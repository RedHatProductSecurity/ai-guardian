"""Per-provider normalization for OpenAI-compatible LLM servers.

Different providers (Ollama, llama.cpp, vLLM) have varying capabilities.
This module normalizes request kwargs so the OpenAI strategy works
uniformly across all of them.
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderCaps:
    """Capability flags for an OpenAI-compatible provider."""

    flatten_content: bool = False
    supports_tools: bool = True
    text_tool_parsing: bool = False


_PROVIDER_CAPS: Dict[str, ProviderCaps] = {
    "openai": ProviderCaps(),
    "azure": ProviderCaps(),
    "openai-compatible": ProviderCaps(),
    "ollama": ProviderCaps(flatten_content=True, text_tool_parsing=True),
    "mlx": ProviderCaps(flatten_content=True, text_tool_parsing=True),
    "llamacpp": ProviderCaps(flatten_content=True, text_tool_parsing=True),
    "vllm": ProviderCaps(text_tool_parsing=True),
    "lm-studio": ProviderCaps(),
}


def get_provider_caps(provider: Optional[str] = None) -> ProviderCaps:
    """Return capabilities for *provider*, defaulting to standard OpenAI."""
    if provider is None:
        return _PROVIDER_CAPS["openai"]
    return _PROVIDER_CAPS.get(provider, _PROVIDER_CAPS["openai"])


def normalize_request_kwargs(
    kwargs: Dict[str, Any], caps: ProviderCaps
) -> Dict[str, Any]:
    """Normalize chat-completion request *kwargs* for a provider's capabilities.

    Returns a shallow copy with provider-incompatible fields transformed:

    * ``flatten_content`` — structured content blocks
      (``[{"type": "text", "text": "..."}]``) become plain strings.
    * ``supports_tools=False`` — ``tools`` and ``tool_choice`` keys are
      removed so the provider doesn't reject unknown parameters.
    """
    if not caps.flatten_content and caps.supports_tools:
        return kwargs

    result = dict(kwargs)

    if caps.flatten_content:
        messages = result.get("messages")
        if messages:
            result["messages"] = [_flatten_message(msg) for msg in messages]

    if not caps.supports_tools:
        removed = result.pop("tools", None)
        result.pop("tool_choice", None)
        if removed:
            logger.debug(
                "Stripped %d tool definition(s) — provider does not support tools",
                len(removed),
            )

    return result


def _flatten_content(content: Any) -> str:
    """Convert structured content blocks to a plain string.

    Handles OpenAI's content formats:
    * ``str`` — returned as-is
    * ``list[dict]`` — text blocks joined with newlines
    * ``list[str]`` — joined with newlines
    * ``None`` — returns ``""``
    """
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text", "")
                if text:
                    parts.append(text)
        return "\n".join(parts) if parts else ""
    return str(content)


def _flatten_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten structured content in a single message dict."""
    content = msg.get("content")
    if content is None or isinstance(content, str):
        return msg
    return dict(msg, content=_flatten_content(content))


# ---------------------------------------------------------------------------
# Text-as-tool-call extraction
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


def try_parse_json_flexible(text: str) -> Any:
    """Try JSON parsing with fallbacks for common model output quirks.

    Attempts: strict JSON, single-quote replacement, newline-separated
    JSON objects.  Returns the parsed value or ``None``.
    """
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    if "'" in text:
        try:
            return json.loads(text.replace("'", '"'))
        except (json.JSONDecodeError, ValueError):
            pass
    lines = text.strip().split("\n")
    if len(lines) > 1:
        objects: List[Any] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                objects.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                return None
        return objects if objects else None
    return None


def _maybe_tool_call(
    obj: Dict[str, Any],
    known_tool_names: Optional[List[str]],
) -> Optional[Dict[str, Any]]:
    """Check if *obj* looks like a tool call and normalise it."""
    name = obj.get("name")
    if not isinstance(name, str) or not name:
        return None

    if known_tool_names is not None and name not in known_tool_names:
        return None

    arguments = obj.get("arguments", obj.get("input"))
    if arguments is None:
        return None

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, ValueError):
            return None

    if not isinstance(arguments, dict):
        return None

    return {
        "id": f"text_tc_{uuid.uuid4().hex[:12]}",
        "name": name,
        "arguments": arguments,
    }


def _extract_from_parsed(
    parsed: Any,
    known_tool_names: Optional[List[str]],
) -> List[Dict[str, Any]]:
    """Extract tool call dicts from a parsed JSON structure."""
    if isinstance(parsed, dict):
        tc = _maybe_tool_call(parsed, known_tool_names)
        return [tc] if tc else []
    if isinstance(parsed, list):
        results: List[Dict[str, Any]] = []
        for item in parsed:
            if isinstance(item, dict):
                tc = _maybe_tool_call(item, known_tool_names)
                if tc:
                    results.append(tc)
        return results
    return []


def extract_tool_calls_from_text(
    text: str,
    known_tool_names: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Extract tool calls written as plain text in a model response.

    Returns a list of ``{"id", "name", "arguments"}`` dicts, or ``[]``
    if no tool-call patterns are found.
    """
    if not text or not text.strip():
        return []

    candidates: List[str] = []

    for match in _JSON_FENCE_RE.finditer(text):
        candidates.append(match.group(1).strip())

    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        candidates.append(stripped)

    for candidate in candidates:
        parsed = try_parse_json_flexible(candidate)
        if parsed is not None:
            extracted = _extract_from_parsed(parsed, known_tool_names)
            if extracted:
                return extracted

    return []
