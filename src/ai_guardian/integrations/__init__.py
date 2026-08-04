"""LLM client integrations — automatic security scanning for provider SDKs."""

from ai_guardian.integrations.base import ProviderExtractor, guarded
from ai_guardian.integrations.anthropic import create_client  # noqa: F401

# Import concrete extractors to trigger registration.
# These use lazy sys.modules checks — never import provider SDKs.
from ai_guardian.integrations import anthropic as _anthropic_ext  # noqa: F401
from ai_guardian.integrations import openai as _openai_ext  # noqa: F401

__all__ = ["guarded", "ProviderExtractor", "create_client"]
