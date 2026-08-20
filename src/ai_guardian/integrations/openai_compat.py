"""Per-provider normalization for OpenAI-compatible LLM servers.

Different providers (Ollama, llama.cpp, vLLM) have varying capabilities.
This module normalizes request kwargs so the OpenAI strategy works
uniformly across all of them.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderCaps:
    """Capability flags for an OpenAI-compatible provider."""

    flatten_content: bool = False
    supports_tools: bool = True


_PROVIDER_CAPS: Dict[str, ProviderCaps] = {
    "openai": ProviderCaps(),
    "azure": ProviderCaps(),
    "ollama": ProviderCaps(flatten_content=True),
    "llamacpp": ProviderCaps(flatten_content=True),
    "vllm": ProviderCaps(),
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
