"""Provider-agnostic LLM client wrapper with auto-detected extractors."""

import logging
import sys
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Type

from ai_guardian.sdk import SecurityViolation, monitor

logger = logging.getLogger(__name__)

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

_REGISTRY: Dict[str, Type[ProviderExtractor]] = {}


def register_extractor(client_type_path: str, extractor_class: Type[ProviderExtractor]):
    """Register an extractor for a provider client type.

    *client_type_path* is a dotted path like ``"anthropic.Anthropic"``
    used for lazy ``isinstance()`` resolution via ``sys.modules``.
    """
    _REGISTRY[client_type_path] = extractor_class


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


def _detect_extractor(client: Any) -> ProviderExtractor:
    """Return an extractor instance for *client*, or raise ``ValueError``."""
    for dotted, ext_cls in _REGISTRY.items():
        resolved = _resolve_class(dotted)
        if resolved is not None and isinstance(client, resolved):
            return ext_cls()
    client_type = f"{type(client).__module__}.{type(client).__qualname__}"
    raise ValueError(
        f"No provider extractor found for {client_type}. "
        f"Pass extractor= explicitly or install a supported provider: "
        f"pip install ai-guardian[anthropic]"
    )


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


def _try_sanitize_text(session, text):
    """Sanitize *text* via *session*, returning ``None`` on failure."""
    if not text:
        return None
    try:
        result = session.sanitize(text)
        return result.get("sanitized_text", text)
    except Exception:
        return None


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
        action="block",
        mode="direct",
        config=None,
        scan_input=True,
        scan_output=True,
        response_parser=None,
        before_call=None,
        after_call=None,
    ):
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_extractor", extractor)
        object.__setattr__(self, "_action", action)
        object.__setattr__(self, "_mode", mode)
        object.__setattr__(self, "_config", config)
        object.__setattr__(self, "_scan_input", scan_input)
        object.__setattr__(self, "_scan_output", scan_output)
        object.__setattr__(self, "_response_parser", response_parser)
        object.__setattr__(self, "_before_call", before_call)
        object.__setattr__(self, "_after_call", after_call)

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
            with monitor(
                action=gc._action, mode=gc._mode, config=gc._config
            ) as session:
                if gc._before_call:
                    gc._before_call(method_name, args, kwargs)

                if gc._scan_input:
                    for text in gc._extractor.extract_input(method_name, args, kwargs):
                        if text:
                            session.check_content(text, filename="llm_input")

                response = real_method(*args, **kwargs)

                if gc._is_stream_method(method_name):
                    if gc._scan_output:
                        return _StreamProxy(
                            response,
                            gc._extractor,
                            method_name,
                            session,
                            response_parser=gc._response_parser,
                        )
                    return response

                if gc._scan_output:
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


def guarded(
    client: Any = _MISSING,
    *,
    action: str = "block",
    mode: str = "direct",
    config: Optional[Dict[str, Any]] = None,
    extractor: Optional[ProviderExtractor] = None,
    scan_input: bool = True,
    scan_output: bool = True,
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
        action: ``"block"``, ``"warn"``, or ``"log"``
        mode: ``"direct"`` (in-process) or ``"rest"`` (daemon)
        config: Optional config dict override
        extractor: Explicit ``ProviderExtractor`` instance (skips auto-detect)
        scan_input: Scan prompts before sending (default ``True``)
        scan_output: Scan responses after receiving (default ``True``)
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
        SecurityViolation: When ``action="block"`` and a threat is detected.
            If *response_parser* is set, the exception's ``sanitized_parsed``
            attribute contains the parser applied to the violating response.
    """
    if client is _MISSING:
        from ai_guardian.integrations.anthropic import create_client

        client = create_client()
    if extractor is None:
        extractor = _detect_extractor(client)
    return _GuardedClient(
        client,
        extractor,
        action=action,
        mode=mode,
        config=config,
        scan_input=scan_input,
        scan_output=scan_output,
        response_parser=response_parser,
        before_call=before_call,
        after_call=after_call,
    )
