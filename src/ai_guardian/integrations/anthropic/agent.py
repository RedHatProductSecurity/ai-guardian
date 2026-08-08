"""GuardedAgent — tool-use agent loop with security scanning."""

import logging
import os
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
    _try_sanitize_text,
    _strategy_registry,
)
from ai_guardian.sdk import SecurityViolation, monitor

logger = logging.getLogger(__name__)

_USAGE_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


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
        return kwargs

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

    def format_tool_result(self, tool_call_id: str, content: str) -> Dict[str, Any]:
        return {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": content,
        }

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

    def __init__(
        self,
        model: str = "claude-sonnet-5",
        system_prompt: str = "",
        tools: Union[str, List[Any]] = "coding",
        cwd: Optional[str] = None,
        max_turns: int = 100,
        max_tokens: int = 16000,
        max_budget_tokens: int = -1,
        action: str = "block",
        client: Any = None,
        mode: str = "direct",
        config: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        tool_types: Optional[Dict[str, str]] = None,
        scan_input: bool = True,
        scan_output: bool = True,
        before_call: Optional[Callable[[str, tuple, dict], None]] = None,
        after_call: Optional[Callable[[str, Any], Any]] = None,
        pre_run: Optional[Callable[[str, dict], None]] = None,
        post_run: Optional[Callable[[dict], None]] = None,
        between_turns: Optional[Callable[[list, Any, int], Any]] = None,
        strategy: Optional[AgentLoopStrategy] = None,
        cache_ttl: Optional[Union[str, int]] = None,
        auto_compact: bool = True,
        compact_threshold: float = 1.0,
        compact_keep_turns: int = 5,
        compact_keep_first: int = 1,
    ):
        self._model = model
        self._system_prompt = system_prompt
        self._cwd = cwd or os.getcwd()
        self._max_turns = max_turns
        self._max_tokens = max_tokens
        self._max_budget_tokens = max_budget_tokens
        self._action = action
        self._mode = mode
        self._config = config
        self._output_schema = output_schema
        self._tool_types = tool_types
        self._scan_input = scan_input
        self._scan_output = scan_output
        self._before_call = before_call
        self._after_call = after_call
        self._pre_run = pre_run
        self._post_run = post_run
        self._between_turns = between_turns
        self._auto_compact = auto_compact
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

        if cache_ttl is not None:
            self._strategy.validate_cache_ttl(cache_ttl)
            self._cache_ttl = cache_ttl
        else:
            self._cache_ttl = self._strategy.default_cache_ttl(max_turns)

        self._resolved_tools = self._strategy.resolve_tools(tools, tool_types)
        validate_tools(self._resolved_tools, model)

        if output_schema:
            self._resolved_tools.append(
                self._strategy.format_submit_result_tool(output_schema)
            )

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
            return messages, False

        if self._compact_threshold >= 1.0:
            raise RuntimeError(
                f"Context window nearly exhausted: "
                f"{last_input_tokens:,} / {context_limit:,} tokens. "
                f"Enable auto-compaction with "
                f"GuardedAgent(compact_threshold=0.8) to continue "
                f"long conversations."
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
            return result.messages, True
        return messages, False

    def _run_loop(self, prompt: str) -> Dict[str, Any]:
        strategy = self._strategy

        with monitor(
            action=self._action, mode=self._mode, config=self._config
        ) as session:
            if self._scan_input and self._system_prompt:
                session.check_content(self._system_prompt, filename="system_prompt")
            if self._scan_input:
                session.check_content(prompt, filename="user_prompt")

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
                if self._auto_compact and _turn > 0:
                    messages, did_compact = self._maybe_compact(
                        strategy, messages, last_input_tokens
                    )
                    if did_compact:
                        compaction_count += 1

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

                for _f in _USAGE_TOKEN_FIELDS:
                    usage_totals[_f] += getattr(parsed, _f, 0)
                last_input_tokens = parsed.input_tokens

                if self._scan_output and parsed.text:
                    try:
                        session.check_content(
                            parsed.text, filename="assistant_response"
                        )
                    except SecurityViolation as exc:
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
                            if self._scan_input:
                                session.check_content(
                                    hook_result,
                                    filename="between_turns_injection",
                                )
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
                            tool_results.append(
                                strategy.format_tool_result(tc.id, "Result submitted.")
                            )
                            continue

                        if strategy.is_server_tool(tc.name):
                            continue

                        result_text = execute_tool(tc.name, tc.input, self._cwd)

                        if self._scan_output and result_text:
                            session.check_content(
                                result_text,
                                filename=f"tool_result:{tc.name}",
                            )

                        tool_results.append(
                            strategy.format_tool_result(tc.id, result_text)
                        )

                    if tool_results:
                        strategy.append_assistant_and_results(
                            messages, parsed.raw_content, tool_results
                        )

                    if structured_output is not None:
                        stop_reason = "end_turn"
                        break

                    if self._between_turns:
                        hook_result = self._between_turns(messages, response, _turn)
                        if hook_result is False:
                            final_text = parsed.text
                            stop_reason = "hook_early_stop"
                            break
                        if isinstance(hook_result, str):
                            if self._scan_input:
                                session.check_content(
                                    hook_result,
                                    filename="between_turns_injection",
                                )
                            strategy.inject_user_text_after_results(
                                messages, hook_result
                            )

                    continue

                logger.warning("Unknown stop_reason: %s", parsed.stop_reason)
                final_text = parsed.text
                stop_reason = parsed.stop_reason
                break

            output: Any = final_text
            if structured_output is not None:
                output = structured_output

            return {
                "output": output,
                "messages": messages,
                "stop_reason": stop_reason,
                "usage": usage_totals,
                "compaction_count": compaction_count,
            }
