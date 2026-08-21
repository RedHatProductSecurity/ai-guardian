"""Anthropic provider extractor for ai-guardian integrations."""

import os
import sys
from typing import Any, Dict, List, Optional

from ai_guardian.integrations.base import ProviderExtractor, _extractor_registry


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
    _extractor_registry.register(f"anthropic.{_name}", AnthropicExtractor)


# ---------------------------------------------------------------------------
# Auto-detect client from environment
# ---------------------------------------------------------------------------

_ENV_DETECTORS = {
    "vertex": "ANTHROPIC_VERTEX_PROJECT_ID",
    "bedrock": "ANTHROPIC_BEDROCK_BASE_URL",
    "api_key": "ANTHROPIC_API_KEY",
}


_PROVIDER_ALIASES = {
    "anthropic": "api_key",
    "direct": "api_key",
}

_ANTHROPIC_PROVIDERS = frozenset(
    {"vertex", "bedrock", "foundry", "api_key", "direct", "anthropic"}
)

_OPENAI_COMPAT_ALIASES = frozenset(
    {"openai-compatible", "ollama", "mlx", "llamacpp", "vllm", "lm-studio"}
)

_OPENAI_PROVIDERS = frozenset({"openai", "azure"}) | _OPENAI_COMPAT_ALIASES

_GEMINI_PROVIDERS = frozenset({"gemini"})

_VALID_PROVIDERS = _ANTHROPIC_PROVIDERS | _OPENAI_PROVIDERS | _GEMINI_PROVIDERS


def create_client(
    *,
    provider: Optional[str] = None,
    provider_config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Any:
    """Auto-detect and create the right LLM client.

    When *provider* is not set, auto-detects from Anthropic env vars
    (raises ``ValueError`` on conflict or if none are set).

    When *provider* is set, uses that provider directly:

    - Anthropic family (``direct``/``anthropic``/``vertex``/``bedrock``/
      ``foundry``): creates the corresponding Anthropic SDK client.
    - OpenAI-compatible (``openai``/``azure``/``openai-compatible``/
      ``ollama``/``mlx``/``llamacpp``/``vllm``/``lm-studio``): creates
      an OpenAI SDK client (with ``base_url`` from *provider_config*
      for local servers).

    Environment variable overrides (highest precedence):

    - ``AI_GUARDIAN_SDK_PROVIDER`` overrides *provider*
    - ``AI_GUARDIAN_SDK_BASE_URL`` overrides *base_url* in provider_config

    *provider_config* (optional dict) overrides env var names:

    - ``base_url``: server endpoint (required for local servers)
    - ``base_url_env``: env var name holding the base URL
    - ``api_key_env``: env var holding the API key
    - ``project_id_env``: env var for GCP project ID (vertex)
    - ``region_env``: env var for region (vertex/bedrock)

    Any extra ``**kwargs`` are forwarded to the client constructor.
    """
    pcfg = provider_config or {}

    env_provider = os.environ.get("AI_GUARDIAN_SDK_PROVIDER", "").strip()
    if env_provider:
        provider = env_provider

    if provider is not None:
        if provider not in _VALID_PROVIDERS:
            raise ValueError(
                f"Unknown provider {provider!r}. "
                f"Valid values: {', '.join(sorted(_VALID_PROVIDERS))}"
            )
        if provider in _GEMINI_PROVIDERS:
            return _build_gemini_client(pcfg, **kwargs)
        if provider in _OPENAI_PROVIDERS:
            return _build_openai_client(provider, pcfg, **kwargs)
        resolved = _PROVIDER_ALIASES.get(provider, provider)
        return _build_client(resolved, pcfg, **kwargs)

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
            f"Set only one, or pass an explicit client to guarded(), "
            f"or set sdk.provider in ai-guardian.json."
        )

    if not detected:
        raise ValueError(
            "No Anthropic credentials found. Set one of: "
            "ANTHROPIC_API_KEY, ANTHROPIC_VERTEX_PROJECT_ID, "
            "ANTHROPIC_BEDROCK_BASE_URL"
        )

    resolved = next(iter(detected))
    return _build_client(resolved, pcfg, **kwargs)


def _build_client(provider: str, pcfg: dict, **kwargs: Any) -> Any:
    """Create an Anthropic SDK client for the resolved *provider* key."""
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "The 'anthropic' package is required for Anthropic providers. "
            "Install it with: pip install ai-guardian[anthropic]"
        ) from None

    api_key_env = pcfg.get("api_key_env")

    if provider == "vertex":
        pid_env = pcfg.get("project_id_env", "ANTHROPIC_VERTEX_PROJECT_ID")
        region_env = pcfg.get("region_env", "CLOUD_ML_REGION")
        project_id = kwargs.pop("project_id", os.environ.get(pid_env, ""))
        region = kwargs.pop("region", os.environ.get(region_env) or "us-east5")
        return anthropic.AnthropicVertex(project_id=project_id, region=region, **kwargs)

    if provider == "bedrock":
        return anthropic.AnthropicBedrock(**kwargs)

    if provider == "foundry":
        return anthropic.AnthropicFoundry(**kwargs)

    if api_key_env:
        key = os.environ.get(api_key_env, "")
        kwargs.setdefault("api_key", key)
    return anthropic.Anthropic(**kwargs)


def _resolve_base_url(pcfg: dict) -> Optional[str]:
    """Resolve base URL: AI_GUARDIAN_SDK_BASE_URL > base_url_env > base_url."""
    env_override = os.environ.get("AI_GUARDIAN_SDK_BASE_URL", "").strip()
    if env_override:
        return env_override
    base_url_env = pcfg.get("base_url_env")
    if base_url_env:
        val = os.environ.get(base_url_env, "").strip()
        if val:
            return val
    return pcfg.get("base_url")


def _build_openai_client(provider: str, pcfg: dict, **kwargs: Any) -> Any:
    """Create an OpenAI SDK client for OpenAI-compatible providers."""
    try:
        import openai
    except ImportError:
        raise ImportError(
            "The 'openai' package is required for OpenAI-compatible providers "
            "(OpenAI, Azure, Ollama, llama.cpp, vLLM). "
            "Install it with: pip install ai-guardian[openai]"
        ) from None

    base_url = _resolve_base_url(pcfg)
    api_key_env = pcfg.get("api_key_env")

    if provider == "azure":
        if api_key_env:
            kwargs.setdefault("api_key", os.environ.get(api_key_env, ""))
        if base_url:
            kwargs.setdefault("azure_endpoint", base_url)
        client = openai.AzureOpenAI(**kwargs)
        client._ai_guardian_provider = provider  # type: ignore[attr-defined]
        return client

    ctor_kwargs: dict = {}
    if base_url:
        ctor_kwargs["base_url"] = base_url
    if api_key_env:
        ctor_kwargs["api_key"] = os.environ.get(api_key_env, "")
    elif provider in _OPENAI_COMPAT_ALIASES:
        ctor_kwargs.setdefault("api_key", "not-needed")
    ctor_kwargs.update(kwargs)
    client = openai.OpenAI(**ctor_kwargs)
    client._ai_guardian_provider = provider  # type: ignore[attr-defined]
    return client


def _build_gemini_client(pcfg: dict, **kwargs: Any) -> Any:
    """Create a Google Gemini SDK client."""
    try:
        from google import genai
    except ImportError:
        raise ImportError(
            "The 'google-genai' package is required for Google Gemini. "
            "Install it with: pip install ai-guardian[gemini]"
        ) from None

    api_key_env = pcfg.get("api_key_env", "GOOGLE_API_KEY")
    api_key = os.environ.get(api_key_env, "")
    if api_key:
        kwargs.setdefault("api_key", api_key)
    return genai.Client(**kwargs)
