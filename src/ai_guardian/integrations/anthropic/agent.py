"""GuardedAgent — tool-use agent loop with security scanning."""

import logging
import os
from typing import Any, Dict, List, Optional, Union

from ai_guardian.integrations.anthropic.tools import (
    execute_tool,
    is_server_tool,
    resolve_tools,
)
from ai_guardian.integrations.base import _try_sanitize_text
from ai_guardian.sdk import SecurityViolation, monitor

logger = logging.getLogger(__name__)


class GuardedAgent:
    """Tool-use agent loop that scans every message for security threats.

    Wraps the Anthropic messages API with an agentic tool-use loop.
    Every message — prompts, tool results, intermediate responses — is
    scanned for prompt injection, secrets, and PII via ai-guardian.

    Supports Anthropic direct, Vertex AI, and Bedrock backends
    (auto-detected from env vars, or pass an explicit *client*).
    """

    def __init__(
        self,
        model: str = "claude-sonnet-5",
        system_prompt: str = "",
        tools: Union[str, List[Any]] = "coding",
        cwd: Optional[str] = None,
        max_turns: int = 100,
        max_tokens: int = 16000,
        action: str = "block",
        client: Any = None,
        mode: str = "direct",
        config: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        tool_types: Optional[Dict[str, str]] = None,
        scan_input: bool = True,
        scan_output: bool = True,
    ):
        self._model = model
        self._system_prompt = system_prompt
        self._cwd = cwd or os.getcwd()
        self._max_turns = max_turns
        self._max_tokens = max_tokens
        self._action = action
        self._mode = mode
        self._config = config
        self._output_schema = output_schema
        self._tool_types = tool_types
        self._scan_input = scan_input
        self._scan_output = scan_output

        self._client = client or self._create_client()
        self._resolved_tools = resolve_tools(tools, tool_types)

        if output_schema:
            self._resolved_tools.append(
                {
                    "name": "submit_result",
                    "description": (
                        "Submit the final structured result. "
                        "Call this as your last action when the task is complete."
                    ),
                    "input_schema": output_schema,
                }
            )

    @staticmethod
    def _create_client() -> Any:
        from ai_guardian.integrations.anthropic._extractor import create_client

        return create_client()

    def run(self, prompt: str) -> Dict[str, Any]:
        """Run the agent loop and return the result.

        Returns a dict with:
        - ``output``: final text (or structured object if *output_schema* set)
        - ``messages``: full conversation history
        - ``stop_reason``: why the loop ended
        - ``usage``: cumulative token usage
        """
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

            usage_totals: Dict[str, int] = {
                "input_tokens": 0,
                "output_tokens": 0,
            }
            structured_output = None
            final_text = ""
            stop_reason = "max_turns"

            for _turn in range(self._max_turns):
                create_kwargs: Dict[str, Any] = {
                    "model": self._model,
                    "max_tokens": self._max_tokens,
                    "tools": self._resolved_tools,
                    "messages": messages,
                }
                if system:
                    create_kwargs["system"] = system

                response = self._client.messages.create(**create_kwargs)

                resp_usage = getattr(response, "usage", None)
                if resp_usage:
                    usage_totals["input_tokens"] += getattr(
                        resp_usage, "input_tokens", 0
                    )
                    usage_totals["output_tokens"] += getattr(
                        resp_usage, "output_tokens", 0
                    )

                content = getattr(response, "content", [])
                resp_stop = getattr(response, "stop_reason", "end_turn")

                try:
                    for block in content:
                        block_type = getattr(block, "type", None)
                        if block_type == "text" and self._scan_output:
                            text = getattr(block, "text", "")
                            if text:
                                session.check_content(
                                    text, filename="assistant_response"
                                )
                except SecurityViolation as exc:
                    exc.response = response
                    exc.sanitized_text = _try_sanitize_text(
                        session, self._extract_text(content)
                    )
                    raise

                if resp_stop == "end_turn":
                    final_text = self._extract_text(content)
                    stop_reason = "end_turn"
                    break

                if resp_stop == "refusal":
                    final_text = self._extract_text(content)
                    stop_reason = "refusal"
                    break

                if resp_stop in ("tool_use", "pause_turn"):
                    tool_results: List[Dict[str, Any]] = []
                    for block in content:
                        block_type = getattr(block, "type", None)
                        if block_type != "tool_use":
                            continue

                        tool_name = getattr(block, "name", "")
                        tool_id = getattr(block, "id", "")
                        tool_input = getattr(block, "input", {})

                        if tool_name == "submit_result":
                            structured_output = tool_input
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": "Result submitted.",
                                }
                            )
                            continue

                        if is_server_tool(tool_name):
                            continue

                        result_text = execute_tool(tool_name, tool_input, self._cwd)

                        if self._scan_output and result_text:
                            session.check_content(
                                result_text, filename=f"tool_result:{tool_name}"
                            )

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": result_text,
                            }
                        )

                    if tool_results:
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": tool_results})

                    if structured_output is not None:
                        stop_reason = "end_turn"
                        break

                    continue

                logger.warning("Unknown stop_reason: %s", resp_stop)
                final_text = self._extract_text(content)
                stop_reason = resp_stop
                break

            output: Any = final_text
            if structured_output is not None:
                output = structured_output

            return {
                "output": output,
                "messages": messages,
                "stop_reason": stop_reason,
                "usage": usage_totals,
            }

    @staticmethod
    def _extract_text(content: Any) -> str:
        parts: List[str] = []
        if isinstance(content, list):
            for block in content:
                if getattr(block, "type", None) == "text":
                    text = getattr(block, "text", "")
                    if text:
                        parts.append(text)
        return "\n".join(parts)
