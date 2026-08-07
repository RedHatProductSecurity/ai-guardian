"""Anthropic integration — guarded client, agent loop, and tool executors."""

from ai_guardian.integrations.anthropic._extractor import (
    AnthropicExtractor,
    create_client,
    _ENV_DETECTORS,
)
from ai_guardian.integrations.anthropic.agent import (
    AnthropicLoopStrategy,
    GuardedAgent,
)

__all__ = [
    "AnthropicExtractor",
    "AnthropicLoopStrategy",
    "create_client",
    "GuardedAgent",
    "_ENV_DETECTORS",
]
