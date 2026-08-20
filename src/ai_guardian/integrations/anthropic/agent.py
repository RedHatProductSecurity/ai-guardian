"""GuardedAgent — tool-use agent loop with security scanning."""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from ai_guardian.integrations.anthropic.tools import (
    MCP_TOOL_PREFIX,
    execute_tool,
    is_server_tool,
    resolve_tools,
    validate_tools,
)
from ai_guardian.integrations.mcp_client import (
    MCPClientManager,
    is_mcp_tool,
    parse_mcp_tool_name,
)
from ai_guardian.integrations.base import (
    AgentLoopStrategy,
    ParsedResponse,
    ToolCall,
    TurnEvent,
    _PREAMBLE_PREFIX,
    _USAGE_TOKEN_FIELDS,
    _try_sanitize_batch,
    _try_sanitize_text,
    _strategy_registry,
)
from ai_guardian.sdk import SecurityViolation, monitor

logger = logging.getLogger(__name__)


def _get_usage_field(usage: Any, field: str) -> int:
    return getattr(usage, field, 0) if usage else 0


# ---------------------------------------------------------------------------
# Anthropic loop strategy
# ---------------------------------------------------------------------------


class AnthropicLoopStrategy(AgentLoopStrategy):
    """Agent loop strategy for Anthropic's messages API."""

    _valid_cache_ttls = frozenset({0, "5m", "1h"})

    @property
    def api_method_name(self) -> str:
        return "messages.create"

    def create_default_client(self) -> Any:
        from ai_guardian.integrations.anthropic._extractor import create_client

        return create_client()

    def resolve_tools(
        self,
        tools: Union[str, List[Any]],
        tool_types: Optional[Dict[str, str]] = None,
    ) -> List[Any]:
        return resolve_tools(tools, tool_types)

    def format_submit_result_tool(
        self, output_schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "name": "submit_result",
            "description": (
                "Submit the final structured result. "
                "Call this as your last action when the task is complete."
            ),
            "input_schema": output_schema,
        }

    def inject_preamble(self, kwargs: Dict[str, Any], preamble: str) -> None:
        prefix = f"{_PREAMBLE_PREFIX}{preamble}\n\n"
        if "system" not in kwargs:
            return
        sys_val = kwargs["system"]
        if isinstance(sys_val, str):
            kwargs["system"] = prefix + sys_val
        elif isinstance(sys_val, list):
            kwargs["system"] = [{"type": "text", "text": prefix}] + list(sys_val)

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
        kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "tools": tools,
            "messages": messages,
        }
        if system:
            if cache_ttl:
                cache_block: Dict[str, str] = {"type": "ephemeral"}
                if cache_ttl == "1h":
                    cache_block["ttl"] = "1h"
                kwargs["system"] = [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": cache_block,
                    }
                ]
            else:
                kwargs["system"] = system

        self._apply_message_cache_breakpoints(messages, cache_ttl)
        return kwargs

    def _apply_message_cache_breakpoints(
        self,
        messages: List[Dict[str, Any]],
        cache_ttl: Optional[Union[str, int]],
    ) -> None:
        """Set cache_control on the second-to-last message (sliding breakpoint).

        Anthropic caches everything up to and including the last
        ``cache_control`` marker.  By sliding it to ``messages[-2]``,
        only the newest message is billed as new input each turn.
        """
        if not cache_ttl or len(messages) < 2:
            return

        cache_block: Dict[str, str] = {"type": "ephemeral"}
        if cache_ttl == "1h":
            cache_block["ttl"] = "1h"

        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block.pop("cache_control", None)
                    elif hasattr(block, "cache_control"):
                        block.cache_control = None

        target = messages[-2]
        content = target.get("content")
        if isinstance(content, list) and content:
            last_block = content[-1]
            if isinstance(last_block, dict):
                last_block["cache_control"] = cache_block
            else:
                last_block.cache_control = cache_block
        elif isinstance(content, str):
            target["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": cache_block,
                }
            ]

    def call_api(self, client: Any, kwargs: Dict[str, Any]) -> Any:
        return client.messages.create(**kwargs)

    def parse_response(self, response: Any) -> ParsedResponse:
        content = getattr(response, "content", [])
        stop = getattr(response, "stop_reason", "end_turn")
        usage = getattr(response, "usage", None)

        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        for block in content:
            bt = getattr(block, "type", None)
            if bt == "text":
                t = getattr(block, "text", "")
                if t:
                    text_parts.append(t)
            elif bt == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=getattr(block, "id", ""),
                        name=getattr(block, "name", ""),
                        input=getattr(block, "input", {}),
                    )
                )

        return ParsedResponse(
            stop_reason=stop,
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            raw_content=content,
            **{f: _get_usage_field(usage, f) for f in _USAGE_TOKEN_FIELDS},
        )

    def format_tool_result(
        self,
        tool_call_id: str,
        content: str,
        is_error: bool = False,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": content,
        }
        if is_error:
            result["is_error"] = True
        return result

    def append_assistant_and_results(
        self,
        messages: List[Dict[str, Any]],
        raw_content: Any,
        tool_results: List[Dict[str, Any]],
    ) -> None:
        messages.append({"role": "assistant", "content": raw_content})
        messages.append({"role": "user", "content": tool_results})

    def inject_user_text_after_results(
        self,
        messages: List[Dict[str, Any]],
        text: str,
    ) -> None:
        last_content = messages[-1]["content"]
        if isinstance(last_content, list):
            last_content.append({"type": "text", "text": text})
        else:
            messages.append({"role": "user", "content": text})

    def default_cache_ttl(self, max_turns: int) -> Union[str, int]:
        return 0 if max_turns <= 1 else "5m"

    def count_tokens(
        self,
        client: Any,
        model: str,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Any],
    ) -> Optional[int]:
        try:
            kwargs: Dict[str, Any] = {"model": model, "messages": messages}
            if system:
                kwargs["system"] = system
            if tools:
                kwargs["tools"] = tools
            result = client.messages.count_tokens(**kwargs)
            return getattr(result, "input_tokens", None)
        except Exception:
            logger.debug(
                "count_tokens failed, falling back to estimation", exc_info=True
            )
            return None

    def is_server_tool(self, tool_name: str) -> bool:
        return is_server_tool(tool_name)

    @classmethod
    def detect(cls, client: Any) -> bool:
        return hasattr(client, "messages")


# Register for all Anthropic client types
for _name in (
    "Anthropic",
    "AsyncAnthropic",
    "AnthropicVertex",
    "AsyncAnthropicVertex",
    "AnthropicBedrock",
    "AsyncAnthropicBedrock",
    "AnthropicFoundry",
    "AsyncAnthropicFoundry",
):
    _strategy_registry.register(f"anthropic.{_name}", AnthropicLoopStrategy)


# ---------------------------------------------------------------------------
# GuardedAgent
# ---------------------------------------------------------------------------


class GuardedAgent:
    """Tool-use agent loop that scans every message for security threats.

    Wraps an LLM API with an agentic tool-use loop.
    Every message — prompts, tool results, intermediate responses — is
    scanned for prompt injection, secrets, and PII via ai-guardian.

    Auto-detects the provider from the *client* type and selects the
    matching loop strategy.  Supports Anthropic (direct, Vertex AI,
    Bedrock) and OpenAI out of the box.
    """

    _TRACE_TEXT_FIELDS = ("text", "system_prompt", "user_prompt", "output", "preamble")

    _OVERRIDABLE_PARAMS = frozenset(
        {
            "max_turns",
            "max_tokens",
            "max_budget_tokens",
            "mode",
            "model",
            "cwd",
            "target_dir",
            "allowed_paths",
            "follow_symlinks",
            "compact_threshold",
            "compact_keep_turns",
            "compact_keep_first",
        }
    )

    def __init__(
        self,
        model: str = "claude-sonnet-5",
        system_prompt: str = "",
        tools: Union[str, List[Any]] = "coding",
        cwd: Optional[str] = None,
        max_turns: int = 100,
        max_tokens: int = 16000,
        max_budget_tokens: int = -1,
        client: Any = None,
        mode: str = "direct",
        config: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        tool_types: Optional[Dict[str, str]] = None,
        before_call: Optional[Callable[[str, tuple, dict], None]] = None,
        after_call: Optional[Callable[[str, Any], Any]] = None,
        pre_run: Optional[Callable[[str, dict], None]] = None,
        post_run: Optional[Callable[[dict], None]] = None,
        between_turns: Optional[Callable[[list, Any, int], Any]] = None,
        on_turn: Optional[Callable[[int, TurnEvent], None]] = None,
        strategy: Optional[AgentLoopStrategy] = None,
        cache_ttl: Optional[Union[str, int]] = None,
        compact_threshold: float = 0.8,
        compact_keep_turns: int = 5,
        compact_keep_first: int = 1,
        name: Optional[str] = None,
        trace_dir: Optional[str] = None,
        trace_path_fn: Optional[Callable[[str, Dict[str, Any]], str]] = None,
        target_dir: Optional[str] = None,
        allowed_paths: Optional[List[str]] = None,
        follow_symlinks: bool = False,
        otel_metadata_fn: Optional[
            Callable[[str, Dict[str, Any]], Dict[str, Any]]
        ] = None,
    ):
        self._name = name
        self._otel_metadata_fn = otel_metadata_fn
        self._target_dir = target_dir
        if trace_dir is not None:
            self._trace_dir = trace_dir
        else:
            from ai_guardian.config.utils import get_sdk_trace_dir

            self._trace_dir = str(get_sdk_trace_dir())
        self._trace_path_fn = trace_path_fn
        self._last_trace: List[Dict[str, Any]] = []
        self._model = model
        self._system_prompt = system_prompt
        self._cwd = cwd or os.getcwd()
        self._allowed_paths = list(allowed_paths) if allowed_paths else None
        self._follow_symlinks = follow_symlinks
        self._max_turns = max_turns
        self._max_tokens = max_tokens
        self._max_budget_tokens = max_budget_tokens
        self._mode = mode
        self._config = config
        self._output_schema = output_schema
        self._tool_types = tool_types
        self._scanning = True
        self._before_call = before_call
        self._after_call = after_call
        self._pre_run = pre_run
        self._post_run = post_run
        self._between_turns = between_turns
        self._on_turn = on_turn
        self._preamble: Optional[str] = None
        self._original_system_prompt = system_prompt
        self._compact_threshold = compact_threshold
        self._compact_keep_turns = compact_keep_turns
        self._compact_keep_first = compact_keep_first
        self._mcp_servers_config: Optional[Dict[str, Any]] = None

        if strategy is not None:
            self._strategy = strategy
            self._client = client or strategy.create_default_client()
        elif client is not None:
            self._client = client
            self._strategy = _strategy_registry.detect(client)
        else:
            self._strategy, self._client = self._create_client_from_profile()

        tools = self._apply_config_profile(tools)

        if self._trace_dir and not os.path.isabs(self._trace_dir):
            self._trace_dir = os.path.join(self._cwd, self._trace_dir)

        if cache_ttl is not None:
            self._strategy.validate_cache_ttl(cache_ttl)
            self._cache_ttl = cache_ttl
        else:
            self._cache_ttl = self._strategy.default_cache_ttl(self._max_turns)

        self._resolved_tools = self._strategy.resolve_tools(tools, tool_types)
        validate_tools(self._resolved_tools, self._model)

        if output_schema:
            self._resolved_tools.append(
                self._strategy.format_submit_result_tool(output_schema)
            )

    def _create_client_from_profile(self):
        """Create client from agent profile provider, falling back to defaults.

        Resolution: agent profile > ``*`` profile > top-level ``sdk.provider``
        > auto-detect from env vars.

        Returns (strategy, client) tuple.
        """
        from ai_guardian.config.loaders import _load_config_file, _load_sdk_profile
        from ai_guardian.integrations.anthropic._extractor import (
            _OPENAI_PROVIDERS,
            create_client,
        )

        provider = None
        provider_config = None

        profile = _load_sdk_profile("agents", self._name)
        if profile:
            provider = profile.get("provider")
            provider_config = profile.get("provider_config")

        if provider is None:
            try:
                cfg, _ = _load_config_file()
                if cfg:
                    sdk_section = cfg.get("sdk") or {}
                    provider = sdk_section.get("provider")
                    if provider_config is None:
                        provider_config = sdk_section.get("provider_config")
            except Exception:
                pass

        if provider and provider in _OPENAI_PROVIDERS:
            from ai_guardian.integrations.openai import OpenAILoopStrategy

            client = create_client(provider=provider, provider_config=provider_config)
            return OpenAILoopStrategy(), client

        client = create_client(provider=provider, provider_config=provider_config)
        return AnthropicLoopStrategy(), client

    def _apply_config_profile(
        self, tools_spec: Union[str, List[Any]]
    ) -> Union[str, List[Any]]:
        """Apply config profile overrides, returning the (possibly updated) tools spec."""
        from ai_guardian.config.loaders import _load_sdk_profile, _sdk_scanning

        if not _sdk_scanning("agents", self._name):
            logger.info(
                "ai-guardian SDK scanning disabled via config — GuardedAgent scanning skipped"
            )
            self._scanning = False
            return tools_spec

        profile = _load_sdk_profile("agents", self._name)
        if not profile:
            return tools_spec

        display_name = self._name or "*"

        mcp_servers = profile.get("mcpServers")
        if mcp_servers and isinstance(mcp_servers, dict):
            self._mcp_servers_config = mcp_servers
            logger.info(
                "GuardedAgent '%s': %d MCP server(s) configured",
                display_name,
                len(mcp_servers),
            )

        for param, config_value in profile.items():
            if param in ("mcpServers", "provider", "provider_config"):
                continue
            if param == "tools":
                if config_value != tools_spec:
                    logger.info(
                        "GuardedAgent '%s': tools=%r "
                        "(config override, code value: %r)",
                        display_name,
                        config_value,
                        tools_spec,
                    )
                tools_spec = config_value
            elif param == "system_prompt_preamble":
                if config_value:
                    self._preamble = config_value
                    self._system_prompt = (
                        f"{_PREAMBLE_PREFIX}{config_value}\n\n" f"{self._system_prompt}"
                    )
                    logger.info(
                        "GuardedAgent '%s': system_prompt_preamble applied "
                        "(%d chars from config)",
                        display_name,
                        len(config_value),
                    )
            elif param in self._OVERRIDABLE_PARAMS:
                code_value = getattr(self, f"_{param}", None)
                if config_value != code_value:
                    logger.info(
                        "GuardedAgent '%s': %s=%r " "(config override, code value: %r)",
                        display_name,
                        param,
                        config_value,
                        code_value,
                    )
                setattr(self, f"_{param}", config_value)

        return tools_spec

    def run(self, prompt: str) -> Dict[str, Any]:
        """Run the agent loop and return the result.

        Returns a dict with:
        - ``output``: final text (or structured object if *output_schema* set)
        - ``messages``: full conversation history
        - ``stop_reason``: why the loop ended
        - ``usage``: cumulative token usage
        """
        run_config = {
            "model": self._model,
            "tools": list(self._resolved_tools),
            "system_prompt": self._system_prompt,
            "max_turns": self._max_turns,
            "max_budget_tokens": self._max_budget_tokens,
        }
        if self._pre_run:
            self._pre_run(prompt, run_config)

        result = None
        try:
            result = self._run_loop(prompt)
            return result
        finally:
            if self._post_run:
                self._post_run(result)

    def _resolve_trace_filepath(self, started_at: datetime) -> str:
        """Compute the trace file path once per run for reuse."""
        agent_name = self._name or "agent"
        timestamp = started_at.strftime("%Y%m%d-%H%M%S")
        unique = uuid.uuid4().hex[:8]
        filename = f"{agent_name}_{timestamp}_{unique}.json"

        middle = ""
        if self._trace_path_fn:
            ctx = {"model": self._model}
            middle = self._trace_path_fn(agent_name, ctx) or ""

        if middle.endswith("/"):
            return os.path.join(self._trace_dir, middle, filename)
        return os.path.join(self._trace_dir, middle + filename)

    def _persist_trace(
        self,
        result: Dict[str, Any],
        started_at: datetime,
        session: Any,
        filepath: Optional[str] = None,
        trace_id: Optional[str] = None,
        run_start_mono: Optional[float] = None,
    ) -> None:
        try:
            if filepath is None:
                filepath = self._resolve_trace_filepath(started_at)

            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            sanitized_trace = self._sanitize_trace(result.get("trace", []), session)

            ended_at = datetime.now(timezone.utc)
            agent_name = self._name or "agent"
            from ai_guardian.config.utils import get_project_name

            project_name = get_project_name(self._cwd)
            trace_doc = {
                "agent_name": agent_name,
                "model": self._model,
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "stop_reason": result.get("stop_reason"),
                "usage": result.get("usage"),
                "max_tokens": self._max_tokens,
                "project_name": project_name,
                "trace": sanitized_trace,
            }
            if trace_id:
                trace_doc["trace_id"] = trace_id
            if run_start_mono is not None:
                trace_doc["duration_ms"] = int(
                    (time.monotonic() - run_start_mono) * 1000
                )
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(trace_doc, fh, indent=2, default=str)

            from ai_guardian.daemon.traces import write_trace_meta

            write_trace_meta(filepath, trace_doc)
            logger.debug("Trace written to %s", filepath)
            import sys

            print(
                f"  [trace] {result.get('stop_reason')} "
                f"turns={len(trace_doc['trace'])} -> {filepath}",
                file=sys.stderr,
                flush=True,
            )

            self._push_trace_to_daemon(os.path.basename(filepath), trace_doc)
        except Exception as exc:
            import sys

            print(
                f"  [trace] FAILED: {exc} -> {filepath}",
                file=sys.stderr,
                flush=True,
            )
            logger.warning("Failed to persist trace", exc_info=True)

    @staticmethod
    def _push_trace_to_daemon(filename: str, trace_doc: Dict[str, Any]) -> None:
        """Push trace document to daemon REST API for container mode viewers."""
        try:
            from ai_guardian.daemon import get_pid_path

            pid_path = get_pid_path()
            if not pid_path.exists():
                return
            pid_info = json.loads(pid_path.read_text())
            rest_port = pid_info.get("rest_port")
            if not rest_port:
                return

            auth_token = pid_info.get("auth_token")
            payload = json.dumps(
                {"filename": filename, "trace_doc": trace_doc}, default=str
            ).encode("utf-8")

            from urllib.request import Request, urlopen

            req = Request(
                f"http://127.0.0.1:{rest_port}/api/traces",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            if auth_token:
                req.add_header("Authorization", f"Bearer {auth_token}")
            urlopen(req, timeout=3)
        except Exception as exc:
            logger.debug("Failed to push trace to daemon: %s", exc)

    @classmethod
    def _sanitize_trace(
        cls, trace: List[Dict[str, Any]], session: Any
    ) -> List[Dict[str, Any]]:
        items: List[tuple] = []
        for ti, turn_obj in enumerate(trace):
            for si, step in enumerate(turn_obj.get("steps", [])):
                for fld in cls._TRACE_TEXT_FIELDS:
                    val = step.get(fld)
                    if val and isinstance(val, str):
                        items.append((ti, si, fld, val))

        if not items:
            return list(trace)

        texts = [val for _, _, _, val in items]
        sanitized_texts = _try_sanitize_batch(session, texts)

        trace_copy: List[Dict[str, Any]] = []
        for turn_obj in trace:
            turn_copy = dict(turn_obj)
            turn_copy["steps"] = [dict(s) for s in turn_obj.get("steps", [])]
            trace_copy.append(turn_copy)

        for (ti, si, fld, original), sanitized in zip(items, sanitized_texts):
            trace_copy[ti]["steps"][si][fld] = sanitized or original
        return trace_copy

    def _maybe_compact(
        self,
        strategy: AgentLoopStrategy,
        messages: List[Dict[str, Any]],
        last_input_tokens: int,
    ) -> tuple:
        from ai_guardian.integrations.compaction import compact_messages

        context_limit = strategy.context_window_tokens(self._model)
        if (
            last_input_tokens <= 0
            or context_limit <= 0
            or last_input_tokens / context_limit < self._compact_threshold
        ):
            return messages, False, None

        if self._compact_threshold >= 1.0:
            raise RuntimeError(
                f"Context window nearly exhausted: "
                f"{last_input_tokens:,} / {context_limit:,} tokens. "
                f"Set compact_threshold < 1.0 (e.g. 0.8) to enable "
                f"compaction for long conversations."
            )

        result = compact_messages(
            messages,
            context_limit=context_limit,
            strategy=strategy,
            threshold=self._compact_threshold,
            keep_first=self._compact_keep_first,
            keep_last=self._compact_keep_turns,
        )
        if result.compacted:
            logger.info(
                "Compacted conversation: %d -> ~%d tokens (%s)",
                result.tokens_before,
                result.tokens_after,
                result.method,
            )
            return result.messages, True, result
        return messages, False, None

    def _start_mcp_servers(self) -> Optional[MCPClientManager]:
        """Start MCP servers if configured, returning the manager."""
        if not self._mcp_servers_config:
            return None
        try:
            manager = MCPClientManager(self._mcp_servers_config)
            manager.start()
            mcp_tools = manager.get_tools()
            if mcp_tools:
                self._resolved_tools.extend(mcp_tools)
                logger.info("Added %d MCP tool(s) to agent", len(mcp_tools))
            return manager
        except Exception as exc:
            logger.error("Failed to start MCP servers: %s", exc)
            return None

    def _run_loop(self, prompt: str) -> Dict[str, Any]:
        strategy = self._strategy
        self._last_trace = []
        trace = self._last_trace

        def _emit(turn_num: int, event: TurnEvent) -> None:
            entry = event.to_dict()
            if not trace or trace[-1]["turn"] != turn_num:
                trace.append({"turn": turn_num, "steps": []})
            current_turn = trace[-1]
            entry["step"] = len(current_turn["steps"])
            current_turn["steps"].append(entry)
            if self._on_turn:
                self._on_turn(turn_num, event)

        started_at = datetime.now(timezone.utc)
        run_start_mono = time.monotonic()
        trace_id = uuid.uuid4().hex
        trace_filepath = None
        if self._trace_dir:
            trace_filepath = self._resolve_trace_filepath(started_at)

        otel_emitter = None
        try:
            from ai_guardian.config.loaders import _load_otel_config
            from ai_guardian.observability.otel_exporter import OtelSpanEmitter

            otel_config = _load_otel_config()
            if otel_config.get("enabled"):
                otel_emitter = OtelSpanEmitter(
                    otel_config,
                    trace_id,
                    self._name or "agent",
                    self._model,
                    metadata_fn=self._otel_metadata_fn,
                )
        except Exception:
            pass

        mcp_manager = self._start_mcp_servers()

        with monitor(
            mode=self._mode,
            config=self._config,
            cwd=self._cwd,
            target_dir=self._target_dir,
        ) as session:
            try:
                return self._run_loop_inner(
                    prompt,
                    strategy,
                    trace,
                    _emit,
                    session,
                    started_at,
                    trace_filepath,
                    trace_id=trace_id,
                    run_start_mono=run_start_mono,
                    otel_emitter=otel_emitter,
                    mcp_manager=mcp_manager,
                )
            except BaseException as exc:
                exc.trace = trace
                if self._trace_dir:
                    partial = {"trace": trace, "stop_reason": "error"}
                    self._persist_trace(
                        partial,
                        started_at,
                        session,
                        trace_filepath,
                        trace_id=trace_id,
                        run_start_mono=run_start_mono,
                    )
                raise
            finally:
                if mcp_manager:
                    mcp_manager.stop()

    def _run_loop_inner(
        self,
        prompt: str,
        strategy: AgentLoopStrategy,
        trace: List[Dict[str, Any]],
        _emit: Callable,
        session: Any,
        started_at: datetime,
        trace_filepath: Optional[str] = None,
        trace_id: Optional[str] = None,
        run_start_mono: Optional[float] = None,
        otel_emitter: Optional[Any] = None,
        mcp_manager: Optional[MCPClientManager] = None,
    ) -> Dict[str, Any]:
        parent_span_id = uuid.uuid4().hex
        _emit(
            0,
            TurnEvent(
                type="system",
                preamble=self._preamble,
                system_prompt=self._original_system_prompt,
                user_prompt=prompt,
            ),
        )

        if self._scanning and self._system_prompt:
            try:
                session.check_content(self._system_prompt, filename="system_prompt")
                _emit(0, TurnEvent(type="scan", scanned="system_prompt"))
            except SecurityViolation as exc:
                _emit(
                    0,
                    TurnEvent(
                        type="scan",
                        scanned="system_prompt",
                        violations=[
                            {
                                "id": exc.result.violation_id,
                                "type": exc.result.violation_type,
                                "message": exc.result.message,
                            }
                        ],
                    ),
                )
                logger.warning(
                    "System prompt blocked by security scan: %s",
                    exc.result.message,
                )
                result = {
                    "output": "",
                    "messages": [],
                    "stop_reason": "security_violation",
                    "usage": {f: 0 for f in _USAGE_TOKEN_FIELDS},
                    "compaction_count": 0,
                    "trace": trace,
                    "error": "System prompt blocked by security scan",
                }
                if self._trace_dir:
                    self._persist_trace(
                        result,
                        started_at,
                        session,
                        trace_filepath,
                        trace_id=trace_id,
                        run_start_mono=run_start_mono,
                    )
                return result

        if self._scanning:
            try:
                session.check_content(prompt, filename="user_prompt")
                _emit(0, TurnEvent(type="scan", scanned="user_prompt"))
            except SecurityViolation as exc:
                _emit(
                    0,
                    TurnEvent(
                        type="scan",
                        scanned="user_prompt",
                        violations=[
                            {
                                "id": exc.result.violation_id,
                                "type": exc.result.violation_type,
                                "message": exc.result.message,
                            }
                        ],
                    ),
                )
                logger.warning(
                    "User prompt blocked by security scan: %s",
                    exc.result.message,
                )
                result = {
                    "output": "",
                    "messages": [],
                    "stop_reason": "security_violation",
                    "usage": {f: 0 for f in _USAGE_TOKEN_FIELDS},
                    "compaction_count": 0,
                    "trace": trace,
                    "error": "User prompt blocked by security scan",
                }
                if self._trace_dir:
                    self._persist_trace(
                        result,
                        started_at,
                        session,
                        trace_filepath,
                        trace_id=trace_id,
                        run_start_mono=run_start_mono,
                    )
                return result

        messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]

        system = self._system_prompt
        if self._output_schema:
            system = (system + "\n\n" if system else "") + (
                "When you have completed the task, call the submit_result "
                "tool with your final structured output."
            )

        usage_totals: Dict[str, int] = {f: 0 for f in _USAGE_TOKEN_FIELDS}
        structured_output = None
        final_text = ""
        stop_reason = "max_turns"
        compaction_count = 0
        last_input_tokens = 0

        for _turn in range(self._max_turns):
            turn_num = _turn + 1
            turn_start_mono = time.monotonic()
            turn_started_at = datetime.now(timezone.utc)
            span_id = uuid.uuid4().hex
            did_compact = False
            compact_result = None

            try:
                if _turn > 0:
                    messages, did_compact, compact_result = self._maybe_compact(
                        strategy, messages, last_input_tokens
                    )
                    if did_compact:
                        compaction_count += 1

                _emit(
                    turn_num,
                    TurnEvent(
                        type="input",
                        messages_count=len(messages),
                        compacted=did_compact,
                    ),
                )

                if did_compact:
                    _emit(
                        turn_num,
                        TurnEvent(
                            type="compaction",
                            tokens_before=compact_result.tokens_before,
                            tokens_after=compact_result.tokens_after,
                            method=compact_result.method,
                        ),
                    )

                create_kwargs = strategy.build_create_kwargs(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    tools=self._resolved_tools,
                    messages=messages,
                    system=system,
                    cache_ttl=self._cache_ttl,
                )

                if self._before_call:
                    self._before_call(strategy.api_method_name, (), create_kwargs)

                api_start = time.monotonic()
                response = strategy.call_api(self._client, create_kwargs)
                api_latency_ms = int((time.monotonic() - api_start) * 1000)
                parsed = strategy.parse_response(response)

                turn_usage = {_f: getattr(parsed, _f, 0) for _f in _USAGE_TOKEN_FIELDS}
                for _f, _v in turn_usage.items():
                    usage_totals[_f] += _v
                last_input_tokens = parsed.input_tokens
                trace_usage = {f: turn_usage.get(f, 0) for f in _USAGE_TOKEN_FIELDS}
                _emit(
                    turn_num,
                    TurnEvent(
                        type="response",
                        text=parsed.text,
                        model_signal=parsed.stop_reason,
                        usage=trace_usage,
                        latency_ms=api_latency_ms,
                    ),
                )

                if trace_filepath:
                    partial = {
                        "trace": trace,
                        "stop_reason": "in_progress",
                        "usage": usage_totals,
                    }
                    self._persist_trace(
                        partial,
                        started_at,
                        session,
                        trace_filepath,
                        trace_id=trace_id,
                        run_start_mono=run_start_mono,
                    )

                if self._scanning and parsed.text:
                    try:
                        scan_result = session.check_content(
                            parsed.text, filename="agent_response"
                        )
                        _emit(
                            turn_num,
                            TurnEvent(type="scan", scanned="agent_response"),
                        )
                        if session.secret_redaction_enabled and scan_result.detected:
                            sanitized = _try_sanitize_text(session, parsed.text)
                            if sanitized:
                                parsed.text = sanitized
                                parsed.raw_content = strategy.replace_response_text(
                                    parsed.raw_content, sanitized
                                )
                    except SecurityViolation as exc:
                        _emit(
                            turn_num,
                            TurnEvent(
                                type="scan",
                                scanned="agent_response",
                                violations=[
                                    {
                                        "id": exc.result.violation_id,
                                        "type": exc.result.violation_type,
                                        "message": exc.result.message,
                                    }
                                ],
                            ),
                        )
                        warning = (
                            f"[ai-guardian] Your response was blocked: "
                            f"{exc.result.violation_type}. "
                            f"Rephrase without the flagged content. "
                            f"Violation ID: {exc.result.violation_id}"
                        )
                        strategy.append_assistant_message(messages, parsed.raw_content)
                        if parsed.tool_calls:
                            blocked_results = [
                                strategy.format_tool_result(
                                    tc.id,
                                    "[ai-guardian] Response blocked "
                                    "— tool execution skipped.",
                                    is_error=True,
                                )
                                for tc in parsed.tool_calls
                            ]
                            blocked_results.append({"type": "text", "text": warning})
                            messages.append(
                                {"role": "user", "content": blocked_results}
                            )
                        else:
                            messages.append({"role": "user", "content": warning})
                        continue

                early_stop = False
                if self._after_call:
                    hook_result = self._after_call(strategy.api_method_name, response)
                    if hook_result is False:
                        early_stop = True

                if self._max_budget_tokens > 0:
                    total_spent = (
                        usage_totals["input_tokens"] + usage_totals["output_tokens"]
                    )
                    if total_spent >= self._max_budget_tokens:
                        final_text = parsed.text
                        stop_reason = "budget_exceeded"
                        break

                if early_stop:
                    final_text = parsed.text
                    stop_reason = "hook_early_stop"
                    break

                if parsed.stop_reason == "end_turn":
                    if self._output_schema and structured_output is None:
                        strategy.append_assistant_message(messages, parsed.raw_content)
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "You must call the submit_result tool with "
                                    "your structured output. Do not respond "
                                    "with plain text."
                                ),
                            }
                        )
                        continue

                    if self._between_turns:
                        hook_result = self._between_turns(messages, response, _turn)
                        if hook_result is False:
                            final_text = parsed.text
                            stop_reason = "hook_early_stop"
                            break
                        if isinstance(hook_result, str):
                            _injection_blocked = False
                            _violation_type = ""
                            _violation_id = ""
                            if self._scanning:
                                try:
                                    session.check_content(
                                        hook_result,
                                        filename="between_turns_injection",
                                    )
                                except SecurityViolation as exc:
                                    _emit(
                                        turn_num,
                                        TurnEvent(
                                            type="scan",
                                            scanned="between_turns_injection",
                                            violations=[
                                                {
                                                    "id": exc.result.violation_id,
                                                    "type": exc.result.violation_type,
                                                    "message": exc.result.message,
                                                }
                                            ],
                                        ),
                                    )
                                    logger.warning(
                                        "between_turns injection blocked by "
                                        "security scan: %s",
                                        exc.result.message,
                                    )
                                    _injection_blocked = True
                                    _violation_type = exc.result.violation_type
                                    _violation_id = exc.result.violation_id
                            if _injection_blocked:
                                strategy.append_assistant_message(
                                    messages, parsed.raw_content
                                )
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": (
                                            "[ai-guardian] Injected content was "
                                            f"blocked: {_violation_type}. "
                                            "The content contained flagged "
                                            "patterns and was not added to "
                                            "context. "
                                            f"Violation ID: {_violation_id}"
                                        ),
                                    }
                                )
                                continue
                            strategy.append_assistant_message(
                                messages, parsed.raw_content
                            )
                            messages.append({"role": "user", "content": hook_result})
                            continue

                    final_text = parsed.text
                    stop_reason = "end_turn"
                    break

                if parsed.stop_reason == "refusal":
                    final_text = parsed.text
                    stop_reason = "refusal"
                    break

                if parsed.stop_reason in ("tool_use", "pause_turn"):
                    tool_results: List[Dict[str, Any]] = []
                    for tc in parsed.tool_calls:
                        if tc.name == "submit_result":
                            structured_output = tc.input
                            _emit(
                                turn_num,
                                TurnEvent(
                                    type="tool_call",
                                    name=tc.name,
                                    input=tc.input,
                                ),
                            )
                            tool_results.append(
                                strategy.format_tool_result(tc.id, "Result submitted.")
                            )
                            continue

                        if strategy.is_server_tool(tc.name):
                            continue

                        _emit(
                            turn_num,
                            TurnEvent(type="tool_call", name=tc.name, input=tc.input),
                        )

                        tool_start = time.monotonic()
                        mcp_parsed = parse_mcp_tool_name(tc.name)
                        if mcp_parsed and mcp_manager:
                            mcp_server, mcp_tool = mcp_parsed
                            result_text = mcp_manager.call_tool(
                                mcp_server, mcp_tool, tc.input
                            )
                        else:
                            result_text = execute_tool(
                                tc.name,
                                tc.input,
                                self._cwd,
                                self._allowed_paths,
                                self._follow_symlinks,
                            )
                        tool_latency_ms = int((time.monotonic() - tool_start) * 1000)
                        tool_output_bytes = (
                            len(result_text.encode("utf-8")) if result_text else 0
                        )

                        _emit(
                            turn_num,
                            TurnEvent(
                                type="tool_result",
                                name=tc.name,
                                output=result_text,
                                latency_ms=tool_latency_ms,
                                output_bytes=tool_output_bytes,
                            ),
                        )

                        _skip_scan = (
                            mcp_manager
                            and mcp_parsed
                            and tc.name in mcp_manager.get_skip_scan_tools()
                        )
                        if self._scanning and result_text and not _skip_scan:
                            bash_cmd = (
                                tc.input.get("command") if tc.name == "Bash" else None
                            )
                            try:
                                scan_result = session.check_content(
                                    result_text,
                                    filename=f"tool_result:{tc.name}",
                                    source_command=bash_cmd,
                                )
                                _emit(
                                    turn_num,
                                    TurnEvent(
                                        type="scan",
                                        scanned=f"tool_result:{tc.name}",
                                    ),
                                )
                                if (
                                    session.secret_redaction_enabled
                                    and scan_result.detected
                                ):
                                    sanitized = _try_sanitize_text(session, result_text)
                                    if sanitized:
                                        result_text = sanitized
                            except SecurityViolation as exc:
                                result_text = (
                                    f"[ai-guardian] Content blocked: "
                                    f"{exc.result.violation_type}. "
                                    f"Try a different approach. "
                                    f"Violation ID: {exc.result.violation_id}"
                                )
                                _emit(
                                    turn_num,
                                    TurnEvent(
                                        type="scan",
                                        scanned=f"tool_result:{tc.name}",
                                        violations=[
                                            {
                                                "id": exc.result.violation_id,
                                                "type": exc.result.violation_type,
                                                "message": exc.result.message,
                                            }
                                        ],
                                    ),
                                )

                        is_error = result_text.startswith("Error: no executor")
                        tool_results.append(
                            strategy.format_tool_result(
                                tc.id, result_text, is_error=is_error
                            )
                        )

                    if tool_results:
                        strategy.append_assistant_and_results(
                            messages, parsed.raw_content, tool_results
                        )

                    if trace_filepath:
                        partial = {
                            "trace": trace,
                            "stop_reason": "in_progress",
                            "usage": usage_totals,
                        }
                        self._persist_trace(
                            partial,
                            started_at,
                            session,
                            trace_filepath,
                            trace_id=trace_id,
                            run_start_mono=run_start_mono,
                        )

                    if self._between_turns:
                        hook_result = self._between_turns(messages, response, _turn)
                        if hook_result is False:
                            final_text = parsed.text
                            stop_reason = "hook_early_stop"
                            break
                        if isinstance(hook_result, str):
                            _injection_blocked = False
                            _violation_type = ""
                            _violation_id = ""
                            if self._scanning:
                                try:
                                    session.check_content(
                                        hook_result,
                                        filename="between_turns_injection",
                                    )
                                except SecurityViolation as exc:
                                    _emit(
                                        turn_num,
                                        TurnEvent(
                                            type="scan",
                                            scanned="between_turns_injection",
                                            violations=[
                                                {
                                                    "id": exc.result.violation_id,
                                                    "type": exc.result.violation_type,
                                                    "message": exc.result.message,
                                                }
                                            ],
                                        ),
                                    )
                                    logger.warning(
                                        "between_turns injection blocked by "
                                        "security scan: %s",
                                        exc.result.message,
                                    )
                                    _injection_blocked = True
                                    _violation_type = exc.result.violation_type
                                    _violation_id = exc.result.violation_id
                            if _injection_blocked:
                                strategy.inject_user_text_after_results(
                                    messages,
                                    "[ai-guardian] Injected content was "
                                    f"blocked: {_violation_type}. "
                                    "The content contained flagged patterns "
                                    "and was not added to context. "
                                    f"Violation ID: {_violation_id}",
                                )
                                structured_output = None
                                continue
                            strategy.inject_user_text_after_results(
                                messages, hook_result
                            )
                            structured_output = None
                            continue

                    if structured_output is not None:
                        stop_reason = "end_turn"
                        break

                    continue

                logger.warning("Unknown stop_reason: %s", parsed.stop_reason)
                final_text = parsed.text
                stop_reason = parsed.stop_reason
                break
            finally:
                if trace and trace[-1].get("turn") == turn_num:
                    turn_end_mono = time.monotonic()
                    trace[-1].update(
                        {
                            "trace_id": trace_id,
                            "span_id": span_id,
                            "parent_span_id": parent_span_id,
                            "started_at": turn_started_at.isoformat(),
                            "ended_at": datetime.now(timezone.utc).isoformat(),
                            "duration_ms": int(
                                (turn_end_mono - turn_start_mono) * 1000
                            ),
                        }
                    )
                    if otel_emitter is not None:
                        try:
                            otel_emitter.on_turn_complete(
                                trace[-1], usage_totals=dict(usage_totals)
                            )
                        except Exception:
                            logger.debug("OTEL turn emit failed", exc_info=True)

        output: Any = final_text
        if structured_output is not None:
            output = structured_output

        result = {
            "output": output,
            "messages": messages,
            "stop_reason": stop_reason,
            "usage": usage_totals,
            "compaction_count": compaction_count,
            "trace": trace,
            "started_at": started_at.isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
        }

        if self._trace_dir:
            self._persist_trace(
                result,
                started_at,
                session,
                trace_filepath,
                trace_id=trace_id,
                run_start_mono=run_start_mono,
            )

        if otel_emitter is not None:
            try:
                otel_emitter.on_run_complete(result)
            except Exception:
                logger.debug("OTEL run emit failed", exc_info=True)

        return result
