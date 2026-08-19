"""Anthropic integration — guarded client, agent loop, and tool executors."""

from ai_guardian.integrations.anthropic._extractor import (
    AnthropicExtractor,
    create_client,
    _ANTHROPIC_PROVIDERS,
    _ENV_DETECTORS,
    _OPENAI_PROVIDERS,
    _VALID_PROVIDERS,
)
from ai_guardian.integrations.anthropic.agent import (
    AnthropicLoopStrategy,
    GuardedAgent,
)
from ai_guardian.integrations.base import TurnEvent

__all__ = [
    "AnthropicExtractor",
    "AnthropicLoopStrategy",
    "create_client",
    "GuardedAgent",
    "TurnEvent",
    "_ENV_DETECTORS",
]
