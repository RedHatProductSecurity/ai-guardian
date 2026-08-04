"""Anthropic provider extractor for ai-guardian integrations."""

import os
import sys
from typing import Any, List

from ai_guardian.integrations.base import ProviderExtractor, register_extractor


class AnthropicExtractor(ProviderExtractor):
    """Extracts text from Anthropic SDK messages API calls."""

    _CLIENT_NAMES = (
        "Anthropic",
        "AsyncAnthropic",
        "AnthropicVertex",
        "AsyncAnthropicVertex",
        "AnthropicBedrock",
        "AsyncAnthropicBedrock",
        "AnthropicFoundry",
        "AsyncAnthropicFoundry",
    )

    @classmethod
    def detect(cls, client: Any) -> bool:
        anthropic_mod = sys.modules.get("anthropic")
        if anthropic_mod is None:
            return False
        client_classes = []
        for name in cls._CLIENT_NAMES:
            klass = getattr(anthropic_mod, name, None)
            if klass is not None:
                client_classes.append(klass)
        if not client_classes:
            return False
        return isinstance(client, tuple(client_classes))

    def methods_to_wrap(self) -> List[str]:
        return ["messages.create", "messages.stream"]

    def extract_input(self, method_name: str, args: tuple, kwargs: dict) -> List[str]:
        parts: List[str] = []
        system = kwargs.get("system")
        if isinstance(system, str) and system:
            parts.append(system)
        elif isinstance(system, list):
            for block in system:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        parts.append(text)
                elif isinstance(block, str) and block:
                    parts.append(block)

        messages = kwargs.get("messages", [])
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", "")
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
        content = getattr(response, "content", None)
        if isinstance(content, list):
            for block in content:
                text = getattr(block, "text", None)
                if isinstance(text, str) and text:
                    parts.append(text)
        return parts


for _name in AnthropicExtractor._CLIENT_NAMES:
    register_extractor(f"anthropic.{_name}", AnthropicExtractor)


# ---------------------------------------------------------------------------
# Auto-detect client from environment
# ---------------------------------------------------------------------------

_ENV_DETECTORS = {
    "vertex": "ANTHROPIC_VERTEX_PROJECT_ID",
    "bedrock": "ANTHROPIC_BEDROCK_BASE_URL",
    "api_key": "ANTHROPIC_API_KEY",
}


def create_client(**kwargs: Any) -> Any:
    """Auto-detect and create the right Anthropic client from env vars.

    Detection order (by env var presence):

    - ``ANTHROPIC_VERTEX_PROJECT_ID`` → ``AnthropicVertex``
    - ``ANTHROPIC_BEDROCK_BASE_URL`` → ``AnthropicBedrock``
    - ``ANTHROPIC_API_KEY`` → ``Anthropic``

    Raises ``ValueError`` if conflicting env vars are set for multiple
    providers, or if none are set.

    Any extra ``**kwargs`` are forwarded to the client constructor
    (e.g. ``region``, ``project_id``).
    """
    detected = {
        name: env_var
        for name, env_var in _ENV_DETECTORS.items()
        if os.environ.get(env_var)
    }

    if len(detected) > 1:
        vars_found = ", ".join(
            f"{env_var}={name}" for name, env_var in detected.items()
        )
        raise ValueError(
            f"Multiple Anthropic provider env vars detected: {vars_found}. "
            f"Set only one, or pass an explicit client to guarded()."
        )

    if not detected:
        raise ValueError(
            "No Anthropic credentials found. Set one of: "
            "ANTHROPIC_API_KEY, ANTHROPIC_VERTEX_PROJECT_ID, "
            "ANTHROPIC_BEDROCK_BASE_URL"
        )

    import anthropic

    provider = next(iter(detected))

    if provider == "vertex":
        project_id = kwargs.pop("project_id", os.environ["ANTHROPIC_VERTEX_PROJECT_ID"])
        region = kwargs.pop("region", os.environ.get("CLOUD_ML_REGION") or "us-east5")
        return anthropic.AnthropicVertex(project_id=project_id, region=region, **kwargs)

    if provider == "bedrock":
        return anthropic.AnthropicBedrock(**kwargs)

    return anthropic.Anthropic(**kwargs)
