"""GuardedAgent — tool-use agent loop with security scanning."""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from ai_guardian.integrations.anthropic.tools import (
    execute_tool,
    is_server_tool,
    resolve_tools,
    validate_tools,
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
            "allowed_paths",
            "follow_symlinks",
            "trace_dir",
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
        allowed_paths: Optional[List[str]] = None,
        follow_symlinks: bool = False,
    ):
        self._name = name
        self._trace_dir = trace_dir
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

        if strategy is not None:
            self._strategy = strategy
            self._client = client or strategy.create_default_client()
        elif client is not None:
            self._client = client
            self._strategy = _strategy_registry.detect(client)
        else:
            self._strategy = AnthropicLoopStrategy()
            self._client = self._strategy.create_default_client()

        code_trace_dir = self._trace_dir
        tools = self._apply_config_profile(tools)

        if self._trace_dir and not os.path.isabs(self._trace_dir):
            base = self._cwd
            if code_trace_dir is None:
                from ai_guardian.config.loaders import _sdk_profile_key_base_dir

                config_base = _sdk_profile_key_base_dir(
                    "agents", self._name, "trace_dir"
                )
                if config_base is not None:
                    base = config_base
            self._trace_dir = os.path.join(base, self._trace_dir)

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

        for param, config_value in profile.items():
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

    def _persist_trace(
        self, result: Dict[str, Any], started_at: datetime, session: Any
    ) -> None:
        try:
            agent_name = self._name or "agent"
            timestamp = started_at.strftime("%Y%m%d-%H%M%S")
            unique = uuid.uuid4().hex[:8]
            filename = f"{agent_name}_{timestamp}_{unique}.json"

            middle = ""
            if self._trace_path_fn:
                ctx = {
                    "model": self._model,
                    "stop_reason": result.get("stop_reason"),
                    "usage": result.get("usage"),
                    "turn_count": sum(
                        1
                        for turn_obj in result.get("trace", [])
                        for step in turn_obj.get("steps", [])
                        if step.get("type") == "response"
                    ),
                }
                middle = self._trace_path_fn(agent_name, ctx) or ""

            if middle.endswith("/"):
                filepath = os.path.join(self._trace_dir, middle, filename)
            else:
                filepath = os.path.join(self._trace_dir, middle + filename)

            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            sanitized_trace = self._sanitize_trace(result.get("trace", []), session)

            trace_doc = {
                "agent_name": agent_name,
                "model": self._model,
                "started_at": started_at.isoformat(),
                "stop_reason": result.get("stop_reason"),
                "usage": result.get("usage"),
                "trace": sanitized_trace,
            }
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(trace_doc, fh, indent=2, default=str)
            logger.debug("Trace written to %s", filepath)
        except Exception:
            logger.warning("Failed to persist trace", exc_info=True)

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
        with monitor(mode=self._mode, config=self._config, cwd=self._cwd) as session:
            try:
                return self._run_loop_inner(
                    prompt, strategy, trace, _emit, session, started_at
                )
            except BaseException as exc:
                exc.trace = trace
                if self._trace_dir:
                    partial = {"trace": trace, "stop_reason": "error"}
                    self._persist_trace(partial, started_at, session)
                raise

    def _run_loop_inner(
        self,
        prompt: str,
        strategy: AgentLoopStrategy,
        trace: List[Dict[str, Any]],
        _emit: Callable,
        session: Any,
        started_at: datetime,
    ) -> Dict[str, Any]:
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
            session.check_content(self._system_prompt, filename="system_prompt")
            _emit(0, TurnEvent(type="scan", scanned="system_prompt"))
        if self._scanning:
            session.check_content(prompt, filename="user_prompt")
            _emit(0, TurnEvent(type="scan", scanned="user_prompt"))

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
            did_compact = False
            compact_result = None

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

            response = strategy.call_api(self._client, create_kwargs)
            parsed = strategy.parse_response(response)

            turn_usage = {_f: getattr(parsed, _f, 0) for _f in _USAGE_TOKEN_FIELDS}
            for _f, _v in turn_usage.items():
                usage_totals[_f] += _v
            last_input_tokens = parsed.input_tokens
            total_input = turn_usage.get("input_tokens", 0)
            cached = turn_usage.get("cache_read_input_tokens", 0)
            trace_usage = {
                "total_input_tokens": total_input,
                "cached_tokens": cached,
                "new_input_tokens": total_input - cached,
                "output_tokens": turn_usage.get("output_tokens", 0),
            }
            _emit(
                turn_num,
                TurnEvent(
                    type="response",
                    text=parsed.text,
                    stop_reason=parsed.stop_reason,
                    usage=trace_usage,
                ),
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
                    if scan_result.detected:
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
                                    "type": exc.result.violation_type,
                                    "message": exc.result.message,
                                }
                            ],
                        ),
                    )
                    exc.response = response
                    exc.sanitized_text = _try_sanitize_text(session, parsed.text)
                    raise

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
                                "your structured output. Do not respond with "
                                "plain text."
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
                        if self._scanning:
                            session.check_content(
                                hook_result,
                                filename="between_turns_injection",
                            )
                        strategy.append_assistant_message(messages, parsed.raw_content)
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

                    result_text = execute_tool(
                        tc.name,
                        tc.input,
                        self._cwd,
                        self._allowed_paths,
                        self._follow_symlinks,
                    )

                    _emit(
                        turn_num,
                        TurnEvent(type="tool_result", name=tc.name, output=result_text),
                    )

                    if self._scanning and result_text:
                        bash_cmd = (
                            tc.input.get("command") if tc.name == "Bash" else None
                        )
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
                        if scan_result.detected:
                            sanitized = _try_sanitize_text(session, result_text)
                            if sanitized:
                                result_text = sanitized

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

                if self._between_turns:
                    hook_result = self._between_turns(messages, response, _turn)
                    if hook_result is False:
                        final_text = parsed.text
                        stop_reason = "hook_early_stop"
                        break
                    if isinstance(hook_result, str):
                        if self._scanning:
                            session.check_content(
                                hook_result,
                                filename="between_turns_injection",
                            )
                        strategy.inject_user_text_after_results(messages, hook_result)
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
        }

        if self._trace_dir:
            self._persist_trace(result, started_at, session)

        return result
