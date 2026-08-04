"""OpenAI provider extractor for ai-guardian integrations."""

import sys
from typing import Any, List

from ai_guardian.integrations.base import ProviderExtractor, register_extractor


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
    register_extractor(f"openai.{_name}", OpenAIExtractor)
