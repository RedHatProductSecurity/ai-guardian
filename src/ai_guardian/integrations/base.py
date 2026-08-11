"""Provider-agnostic LLM client wrapper with auto-detected extractors."""

import logging
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, List, Optional, Type, TypeVar, Union

from ai_guardian.sdk import SecurityViolation, monitor

logger = logging.getLogger(__name__)

_CODE_BLOCK_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)


# ---------------------------------------------------------------------------
# Agent loop strategy — dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TurnEvent:
    """Structured event emitted by ``on_turn`` and stored in ``trace``.

    Fields vary by ``type``:

    * ``"system"`` — ``preamble``, ``system_prompt``, ``user_prompt``
    * ``"response"`` — ``text``, ``stop_reason``, ``usage``
    * ``"tool_call"`` — ``name``, ``input``
    * ``"tool_result"`` — ``name``, ``output``
    * ``"scan"`` — ``scanned``, ``violations``
    """

    type: str
    text: Optional[str] = None
    name: Optional[str] = None
    input: Optional[dict] = None
    output: Optional[str] = None
    preamble: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    usage: Optional[dict] = None
    stop_reason: Optional[str] = None
    violations: Optional[list] = field(default_factory=list)
    scanned: Optional[str] = None

    def __str__(self) -> str:
        if self.type == "system":
            parts = []
            if self.preamble:
                parts.append(f"preamble: {self.preamble[:50]}...")
            if self.system_prompt:
                parts.append(f"prompt: {self.system_prompt[:50]}...")
            if self.user_prompt:
                parts.append(f"user: {self.user_prompt[:50]}...")
            return f"[system] {', '.join(parts)}"
        if self.type == "response":
            preview = (self.text or "")[:100]
            ellipsis = "..." if len(self.text or "") > 100 else ""
            return f"[response] {preview}{ellipsis}"
        if self.type == "tool_call":
            return f"[tool_call] {self.name}({self.input})"
        if self.type == "tool_result":
            preview = (self.output or "")[:100]
            ellipsis = "..." if len(self.output or "") > 100 else ""
            return f"[tool_result] {self.name}: {preview}{ellipsis}"
        if self.type == "scan":
            v = self.violations or []
            if v:
                return f"[scan] {self.scanned}: {len(v)} violation(s)"
            return f"[scan] {self.scanned}: clean"
        return f"[{self.type}]"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a trace-ready dict, omitting ``None`` fields."""
        d: Dict[str, Any] = {"type": self.type}
        for attr in (
            "text",
            "name",
            "input",
            "output",
            "preamble",
            "system_prompt",
            "user_prompt",
            "usage",
            "stop_reason",
            "violations",
            "scanned",
        ):
            val = getattr(self, attr)
            if val is not None:
                d[attr] = val
        return d


@dataclass
class ToolCall:
    """Normalized tool call extracted from a provider response."""

    id: str
    name: str
    input: Dict[str, Any]


@dataclass
class ParsedResponse:
    """Provider-normalized response from a single LLM turn.

    ``stop_reason`` uses normalized values:
    ``"end_turn"``, ``"tool_use"``, ``"refusal"``, ``"pause_turn"``,
    or the raw provider value if unmapped.
    """

    stop_reason: str
    text: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw_content: Any = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


_USAGE_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


# ---------------------------------------------------------------------------
# Agent loop strategy — ABC
# ---------------------------------------------------------------------------


class AgentLoopStrategy(ABC):
    """Abstract base for provider-specific agent loop behaviour.

    Each method isolates one protocol difference between providers
    (Anthropic messages API vs OpenAI chat completions, etc.).
    """

    @property
    @abstractmethod
    def api_method_name(self) -> str:
        """Dotted method path shown in hooks (e.g. ``"messages.create"``)."""

    @abstractmethod
    def create_default_client(self) -> Any:
        """Create a provider client from environment variables."""

    @abstractmethod
    def resolve_tools(
        self,
        tools: Union[str, List[Any]],
        tool_types: Optional[Dict[str, str]] = None,
    ) -> List[Any]:
        """Resolve a tool specification into provider-formatted dicts."""

    @abstractmethod
    def format_submit_result_tool(
        self, output_schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return a provider-formatted tool definition for ``submit_result``."""

    @abstractmethod
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
        """Build the kwargs dict for the provider's create/completions call."""

    @abstractmethod
    def call_api(self, client: Any, kwargs: Dict[str, Any]) -> Any:
        """Send the request and return the raw provider response."""

    @abstractmethod
    def parse_response(self, response: Any) -> ParsedResponse:
        """Normalize a raw provider response into a ``ParsedResponse``."""

    @abstractmethod
    def format_tool_result(
        self,
        tool_call_id: str,
        content: str,
        is_error: bool = False,
    ) -> Dict[str, Any]:
        """Format a single tool result for inclusion in the message history."""

    @abstractmethod
    def append_assistant_and_results(
        self,
        messages: List[Dict[str, Any]],
        raw_content: Any,
        tool_results: List[Dict[str, Any]],
    ) -> None:
        """Append the assistant turn and tool results to *messages*."""

    def serialize_assistant_content(self, raw_content: Any) -> Any:
        """Convert a provider response's raw content to a serializable form.

        Default returns *raw_content* unchanged (works for Anthropic).
        Override for providers whose SDK returns non-dict message objects.
        """
        return raw_content

    def replace_response_text(self, raw_content: Any, sanitized_text: str) -> Any:
        """Return *raw_content* with text blocks replaced by *sanitized_text*.

        Default handles Anthropic-style list-of-content-blocks.
        Override for providers with different raw_content formats.
        """
        if not isinstance(raw_content, list):
            return raw_content
        result = []
        text_replaced = False
        for block in raw_content:
            bt = getattr(block, "type", None)
            if bt is None and isinstance(block, dict):
                bt = block.get("type")
            if bt == "text" and not text_replaced:
                result.append({"type": "text", "text": sanitized_text})
                text_replaced = True
            elif bt != "text":
                result.append(block)
        return result if text_replaced else raw_content

    def append_assistant_message(
        self,
        messages: List[Dict[str, Any]],
        raw_content: Any,
    ) -> None:
        """Append just the assistant turn (no tool results) to *messages*."""
        messages.append(
            {
                "role": "assistant",
                "content": self.serialize_assistant_content(raw_content),
            }
        )

    def inject_user_text_after_results(
        self,
        messages: List[Dict[str, Any]],
        text: str,
    ) -> None:
        """Append a user text injection after tool-result messages."""
        messages.append({"role": "user", "content": text})

    _valid_cache_ttls: frozenset = frozenset({0})

    def validate_cache_ttl(self, value: Union[str, int]) -> None:
        """Validate a *cache_ttl* value for this provider.

        Raise ``ValueError`` if the value is not in
        ``_valid_cache_ttls``.  Subclasses override the class attribute
        to widen the accepted set.
        """
        if value not in self._valid_cache_ttls:
            valid = ", ".join(repr(v) for v in sorted(self._valid_cache_ttls, key=str))
            raise ValueError(f"cache_ttl must be one of {valid}, got {value!r}")

    def default_cache_ttl(self, max_turns: int) -> Union[str, int]:
        """Return the default *cache_ttl* for this provider.

        Base implementation returns ``0`` (caching disabled).
        """
        return 0

    def count_tokens(
        self,
        client: Any,
        model: str,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Any],
    ) -> Optional[int]:
        """Count input tokens for the given messages using the provider API.

        Returns ``None`` if the provider doesn't support token counting.
        """
        return None

    def context_window_tokens(self, model: str) -> int:
        """Return the context window size in tokens for *model*."""
        from ai_guardian.integrations.compaction import get_context_limit

        return get_context_limit(model)

    def truncate_tool_result(self, message: Dict[str, Any], max_lines: int) -> None:
        """Truncate tool-result content in *message* in-place.

        Default handles Anthropic's content-block format where tool
        results live inside ``role: user`` messages as
        ``{"type": "tool_result", "content": "..."}`` blocks.
        """
        if message.get("role") != "user":
            return
        content = message.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            text = block.get("content", "")
            if not isinstance(text, str):
                continue
            lines = text.split("\n")
            if len(lines) > max_lines:
                block["content"] = (
                    f"[truncated: {len(lines) - max_lines} lines removed]\n"
                    + "\n".join(lines[-max_lines:])
                )

    def strip_code_blocks(self, message: Dict[str, Any]) -> None:
        """Remove fenced code blocks from *message* content in-place.

        Default handles Anthropic's content-block list and plain-string
        formats for ``role: assistant`` messages.
        """
        if message.get("role") != "assistant":
            return
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = _CODE_BLOCK_RE.sub("[code block removed]", content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if "```" in text:
                        block["text"] = _CODE_BLOCK_RE.sub("[code block removed]", text)

    def create_compaction_boundary(self, dropped_count: int) -> List[Dict[str, Any]]:
        """Return ``[assistant, user]`` boundary messages for compaction.

        Default returns Anthropic content-block format.
        """
        return [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"[Conversation compacted: {dropped_count} turn(s) "
                            f"removed to stay within context window]"
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": "Continue from the remaining context.",
            },
        ]

    def is_server_tool(self, tool_name: str) -> bool:
        """Return True if *tool_name* is executed server-side by the provider."""
        return False

    def inject_preamble(self, kwargs: Dict[str, Any], preamble: str) -> None:
        """Prepend a policy preamble into API call *kwargs* in-place.

        Each provider overrides this to handle its own system-prompt
        format (e.g. Anthropic's ``system`` kwarg vs OpenAI's
        system-role message).
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement inject_preamble()"
        )

    @classmethod
    def detect(cls, client: Any) -> bool:
        """Return True if this strategy handles *client* (duck-typing fallback).

        Called when ``isinstance`` matching via the registry fails (e.g.
        mock clients).  Default returns ``False``.
        """
        return False


# ---------------------------------------------------------------------------
# Generic type registry
# ---------------------------------------------------------------------------

T = TypeVar("T")


def _resolve_class(dotted: str) -> Optional[type]:
    """Resolve ``"pkg.ClassName"`` to the actual class, or *None*."""
    parts = dotted.rsplit(".", 1)
    if len(parts) != 2:
        return None
    mod_name, cls_name = parts
    mod = sys.modules.get(mod_name)
    if mod is None:
        return None
    return getattr(mod, cls_name, None)


class TypeRegistry(Generic[T]):
    """Generic registry mapping dotted client-type paths to handler classes.

    Detection tries ``isinstance`` matching via lazily resolved
    ``sys.modules`` lookups, then falls back to ``cls.detect(client)``
    on each registered class.
    """

    def __init__(self, label: str):
        self._entries: Dict[str, Type[T]] = {}
        self._label = label

    def register(self, client_type_path: str, cls: Type[T]) -> None:
        """Register *cls* for the dotted *client_type_path*."""
        self._entries[client_type_path] = cls

    def detect(self, client: Any) -> T:
        """Return an instance for *client*, or raise ``ValueError``."""
        for dotted, cls in self._entries.items():
            resolved = _resolve_class(dotted)
            if resolved is not None and isinstance(client, resolved):
                return cls()

        seen: set = set()
        for cls in self._entries.values():
            if cls in seen:
                continue
            seen.add(cls)
            if cls.detect(client):
                return cls()

        client_type = f"{type(client).__module__}.{type(client).__qualname__}"
        raise ValueError(
            f"No {self._label} found for {client_type}. "
            f"Pass {self._label.replace(' ', '_')}= explicitly or "
            f"install a supported provider: pip install ai-guardian[anthropic]"
        )

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def __getitem__(self, key: str) -> Type[T]:
        return self._entries[key]

    def __delitem__(self, key: str) -> None:
        del self._entries[key]

    def items(self):
        return self._entries.items()

    def values(self):
        return self._entries.values()


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

_strategy_registry: TypeRegistry[AgentLoopStrategy] = TypeRegistry("loop strategy")


# ---------------------------------------------------------------------------
# Provider extractor interface
# ---------------------------------------------------------------------------


class ProviderExtractor(ABC):
    """Abstract base for provider-specific text extraction."""

    @property
    def provider_name(self) -> str:
        """Short identifier for the provider (e.g. ``"anthropic"``, ``"openai"``)."""
        return type(self).__name__.removesuffix("Extractor").lower()

    @classmethod
    @abstractmethod
    def detect(cls, client: Any) -> bool:
        """Return True if this extractor handles *client*.

        Must use ``sys.modules`` for lazy detection — never import the
        provider SDK directly.
        """

    @abstractmethod
    def methods_to_wrap(self) -> List[str]:
        """Dotted attribute paths to intercept.

        Example: ``["messages.create", "messages.stream"]``
        """

    @abstractmethod
    def extract_input(self, method_name: str, args: tuple, kwargs: dict) -> List[str]:
        """Extract text strings from call arguments."""

    @abstractmethod
    def extract_output(self, method_name: str, response: Any) -> List[str]:
        """Extract text strings from the response object."""


# ---------------------------------------------------------------------------
# Extractor registry
# ---------------------------------------------------------------------------

_extractor_registry: TypeRegistry[ProviderExtractor] = TypeRegistry("extractor")


# ---------------------------------------------------------------------------
# Stream proxy
# ---------------------------------------------------------------------------


class _StreamProxy:
    """Wraps a streaming response to scan accumulated text on completion."""

    def __init__(self, stream, extractor, method_name, session, response_parser=None):
        self._stream = stream
        self._entered = None
        self._extractor = extractor
        self._method_name = method_name
        self._session = session
        self._response_parser = response_parser

    def __enter__(self):
        self._entered = self._stream.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        result = self._stream.__exit__(exc_type, exc_val, exc_tb)
        if exc_type is None:
            target = self._entered if self._entered is not None else self._stream
            final = getattr(target, "get_final_message", None)
            if final is not None:
                msg = final()
                try:
                    for text in self._extractor.extract_output(self._method_name, msg):
                        if text:
                            self._session.check_content(text, filename="llm_output")
                except SecurityViolation as exc:
                    _enrich_violation(
                        exc,
                        msg,
                        self._session,
                        self._extractor,
                        self._method_name,
                        self._response_parser,
                    )
                    raise
        return result

    def __iter__(self):
        target = self._entered if self._entered is not None else self._stream
        return iter(target)

    def __next__(self):
        target = self._entered if self._entered is not None else self._stream
        return next(target)

    def __getattr__(self, name):
        target = self._entered if self._entered is not None else self._stream
        return getattr(target, name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_PREAMBLE_PREFIX = (
    "Before processing the following instructions, apply these policies:\n"
)


def _try_sanitize_text(session, text):
    """Sanitize *text* via *session*, returning ``None`` on failure."""
    if not text:
        return None
    try:
        result = session.sanitize(text)
        sanitized = result.get("sanitized_text", text)
        return sanitized if isinstance(sanitized, str) else None
    except Exception:
        return None


def _try_sanitize_batch(session, texts: List[str]) -> List[str]:
    """Batch-sanitize *texts* via *session*, returning originals on failure."""
    if not texts:
        return []
    try:
        return session.sanitize_batch(texts)
    except Exception:
        return list(texts)


def _sanitize_response_text(session, extractor, method_name, response):
    """Extract all text from *response* and return a sanitized version."""
    try:
        texts = extractor.extract_output(method_name, response)
        combined = "\n".join(t for t in texts if t)
        return _try_sanitize_text(session, combined)
    except Exception:
        return None


def _enrich_violation(exc, response, session, extractor, method_name, response_parser):
    """Attach response, sanitized text, and parsed output to a SecurityViolation."""
    exc.response = response
    exc.sanitized_text = _sanitize_response_text(
        session, extractor, method_name, response
    )
    if response_parser is not None:
        try:
            exc.sanitized_parsed = response_parser(extractor.provider_name, response)
        except Exception:
            exc.sanitized_parsed = None


# ---------------------------------------------------------------------------
# Guarded client proxy
# ---------------------------------------------------------------------------


class _MethodChainProxy:
    """Tracks dotted attribute traversal on the real client."""

    def __init__(self, guarded_client, real_obj, path):
        object.__setattr__(self, "_guarded_client", guarded_client)
        object.__setattr__(self, "_real_obj", real_obj)
        object.__setattr__(self, "_path", path)

    def __getattr__(self, name):
        full_path = f"{self._path}.{name}"
        gc = self._guarded_client
        if full_path in gc._wrapped_methods:
            real_method = getattr(self._real_obj, name)
            return gc._make_guarded_call(full_path, real_method)
        next_obj = getattr(self._real_obj, name)
        if full_path in gc._chain_prefixes:
            return _MethodChainProxy(gc, next_obj, full_path)
        return next_obj


class _GuardedClient:
    """Proxy that intercepts LLM API calls for security scanning."""

    def __init__(
        self,
        client,
        extractor,
        mode="direct",
        config=None,
        response_parser=None,
        before_call=None,
        after_call=None,
        model_override=None,
        max_tokens_override=None,
        system_prompt_preamble=None,
    ):
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_extractor", extractor)
        object.__setattr__(self, "_mode", mode)
        object.__setattr__(self, "_config", config)
        object.__setattr__(self, "_response_parser", response_parser)
        object.__setattr__(self, "_before_call", before_call)
        object.__setattr__(self, "_after_call", after_call)
        object.__setattr__(self, "_model_override", model_override)
        object.__setattr__(self, "_max_tokens_override", max_tokens_override)
        object.__setattr__(self, "_system_prompt_preamble", system_prompt_preamble)

        strategy = None
        if system_prompt_preamble:
            try:
                strategy = _strategy_registry.detect(client)
            except ValueError:
                logger.warning(
                    "system_prompt_preamble configured but no loop strategy "
                    "detected for %s — preamble will not be injected",
                    type(client).__name__,
                )
        object.__setattr__(self, "_strategy", strategy)

        methods = extractor.methods_to_wrap()
        object.__setattr__(self, "_wrapped_methods", set(methods))
        prefixes = set()
        for m in methods:
            parts = m.split(".")
            for i in range(1, len(parts)):
                prefixes.add(".".join(parts[:i]))
        object.__setattr__(self, "_chain_prefixes", prefixes)

    def __getattr__(self, name):
        real_attr = getattr(self._client, name)
        if name in self._chain_prefixes:
            return _MethodChainProxy(self, real_attr, name)
        if name in self._wrapped_methods:
            return self._make_guarded_call(name, real_attr)
        return real_attr

    def _is_stream_method(self, method_name):
        return method_name.endswith(".stream")

    def _make_guarded_call(self, method_name, real_method):
        gc = self

        def wrapper(*args, **kwargs):
            if gc._model_override and "model" in kwargs:
                kwargs["model"] = gc._model_override
            if gc._max_tokens_override and "max_tokens" in kwargs:
                kwargs["max_tokens"] = gc._max_tokens_override
            if gc._system_prompt_preamble and gc._strategy:
                gc._strategy.inject_preamble(kwargs, gc._system_prompt_preamble)

            with monitor(mode=gc._mode, config=gc._config) as session:
                if gc._before_call:
                    gc._before_call(method_name, args, kwargs)

                for text in gc._extractor.extract_input(method_name, args, kwargs):
                    if text:
                        session.check_content(text, filename="llm_input")

                response = real_method(*args, **kwargs)

                if gc._is_stream_method(method_name):
                    return _StreamProxy(
                        response,
                        gc._extractor,
                        method_name,
                        session,
                        response_parser=gc._response_parser,
                    )

                try:
                    for text in gc._extractor.extract_output(method_name, response):
                        if text:
                            session.check_content(text, filename="llm_output")
                except SecurityViolation as exc:
                    _enrich_violation(
                        exc,
                        response,
                        session,
                        gc._extractor,
                        method_name,
                        gc._response_parser,
                    )
                    raise

                if gc._after_call:
                    gc._after_call(method_name, response)

                if gc._response_parser:
                    return gc._response_parser(gc._extractor.provider_name, response)
                return response

        return wrapper


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_MISSING = object()


_OVERRIDABLE_CLIENT_PARAMS = frozenset({"mode"})


def guarded(
    client: Any = _MISSING,
    *,
    name: Optional[str] = None,
    mode: str = "direct",
    config: Optional[Dict[str, Any]] = None,
    extractor: Optional[ProviderExtractor] = None,
    response_parser: Optional[Callable[[str, Any], Any]] = None,
    before_call: Optional[Callable[[str, tuple, dict], None]] = None,
    after_call: Optional[Callable[[str, Any], Any]] = None,
) -> Any:
    """Wrap an LLM client with automatic security scanning.

    Auto-detects the provider from the client type and intercepts
    chat/completion calls to scan prompts and responses.

    If *client* is omitted, auto-creates one from environment variables
    (e.g. ``ANTHROPIC_API_KEY``, ``ANTHROPIC_VERTEX_PROJECT_ID``).

    Args:
        client: An LLM provider client (e.g. ``anthropic.Anthropic()``).
            If omitted, auto-created from env vars.
        name: Optional profile name linking to ``sdk.clients.<name>`` in
            ``ai-guardian.json``.  Config values override code-provided
            parameters.
        mode: ``"direct"`` (in-process) or ``"rest"`` (daemon)
        config: Optional config dict override
        extractor: Explicit ``ProviderExtractor`` instance (skips auto-detect)
        response_parser: Optional callable ``(client_type: str, response) -> Any``
            that transforms native LLM responses into a caller-defined format.
            If ``None`` (default), the native response object is returned unchanged.
        before_call: Optional callback invoked before each API call.
            Signature: ``(method_name: str, args: tuple, kwargs: dict) -> None``.
        after_call: Optional callback invoked after each API call and output
            scanning. Signature: ``(method_name: str, response: Any) -> None``.

    Returns:
        A wrapped client proxy — use exactly like the original client.
        If *response_parser* is set, calls return the parser's output
        instead of the native response.

    Raises:
        ValueError: If no extractor matches and none provided explicitly,
            or if conflicting provider env vars are set.
        SecurityViolation: When a blocked finding is detected.
            If *response_parser* is set, the exception's ``sanitized_parsed``
            attribute contains the parser applied to the violating response.
    """
    if client is _MISSING:
        from ai_guardian.integrations.anthropic import create_client

        client = create_client()

    from ai_guardian.config.loaders import _load_sdk_profile, _sdk_scanning

    if not _sdk_scanning("clients", name):
        logger.info(
            "ai-guardian SDK scanning disabled via config — returning unwrapped client"
        )
        return client

    if extractor is None:
        extractor = _extractor_registry.detect(client)

    model_override = None
    max_tokens_override = None
    preamble = None
    profile = _load_sdk_profile("clients", name)
    if profile:
        display_name = name or "*"
        param_map = {
            "mode": mode,
        }
        for param in _OVERRIDABLE_CLIENT_PARAMS:
            if param in profile:
                config_value = profile[param]
                code_value = param_map[param]
                if config_value != code_value:
                    logger.info(
                        "guarded '%s': %s=%r " "(config override, code value: %r)",
                        display_name,
                        param,
                        config_value,
                        code_value,
                    )
                param_map[param] = config_value
        mode = param_map["mode"]

        if "model" in profile:
            model_override = profile["model"]
            logger.info(
                "guarded '%s': model=%r (config override, injected into API calls)",
                display_name,
                model_override,
            )
        if "max_tokens" in profile:
            max_tokens_override = profile["max_tokens"]
            logger.info(
                "guarded '%s': max_tokens=%r "
                "(config override, injected into API calls)",
                display_name,
                max_tokens_override,
            )

        if profile.get("system_prompt_preamble"):
            preamble = profile["system_prompt_preamble"]
            logger.info(
                "guarded '%s': system_prompt_preamble applied "
                "(%d chars from config)",
                display_name,
                len(preamble),
            )

    return _GuardedClient(
        client,
        extractor,
        mode=mode,
        config=config,
        response_parser=response_parser,
        before_call=before_call,
        after_call=after_call,
        model_override=model_override,
        max_tokens_override=max_tokens_override,
        system_prompt_preamble=preamble,
    )
