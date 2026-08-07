"""Conversation compaction for agent loops approaching context limits."""

import copy
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_NON_DEFAULT_LIMITS: Dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
}

DEFAULT_CONTEXT_LIMIT = 200_000

_CODE_BLOCK_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)

_PRE_CHECK_FACTOR = 0.75


def get_context_limit(model: str) -> int:
    if model in _NON_DEFAULT_LIMITS:
        return _NON_DEFAULT_LIMITS[model]
    for prefix, limit in _NON_DEFAULT_LIMITS.items():
        if model.startswith(prefix):
            return limit
    return DEFAULT_CONTEXT_LIMIT


@dataclass
class CompactionResult:
    compacted: bool
    messages: List[Dict[str, Any]]
    tokens_before: int
    tokens_after: int
    method: str


def should_compact(
    last_input_tokens: int,
    context_limit: int,
    threshold: float,
) -> bool:
    if last_input_tokens <= 0 or context_limit <= 0:
        return False
    return last_input_tokens / context_limit >= threshold * _PRE_CHECK_FACTOR


def estimate_tokens(text: str) -> int:
    return len(text) // 4 if text else 0


def estimate_messages_tokens(
    messages: List[Dict[str, Any]],
    system: str = "",
) -> int:
    total = estimate_tokens(system)
    for msg in messages:
        total += _estimate_message_tokens(msg)
    return total


def compact_messages(
    messages: List[Dict[str, Any]],
    *,
    context_limit: int,
    threshold: float = 0.8,
    keep_first: int = 1,
    keep_last: int = 5,
    max_tool_result_lines: int = 50,
) -> CompactionResult:
    if len(messages) < 4:
        tokens_before = estimate_messages_tokens(messages)
        return CompactionResult(
            compacted=False,
            messages=messages,
            tokens_before=tokens_before,
            tokens_after=tokens_before,
            method="none",
        )

    tokens_before = estimate_messages_tokens(messages)

    cutoff = max(0, len(messages) - keep_last * 2)
    result = [copy.deepcopy(m) for m in messages[:cutoff]] + messages[cutoff:]

    methods = []
    prev_tokens = tokens_before

    _truncate_tool_results(result, keep_last, max_tool_result_lines)
    _strip_code_blocks(result, keep_last)

    after_content = estimate_messages_tokens(result)
    if after_content < prev_tokens:
        methods.append("truncate_and_strip")

    target = int(context_limit * threshold * 0.9)
    if after_content > target:
        result = _drop_middle_turns(result, keep_first, keep_last)
        methods.append("drop_middle_turns")

    tokens_after = estimate_messages_tokens(result)
    method = "+".join(methods) if methods else "none"
    compacted = tokens_after < tokens_before

    return CompactionResult(
        compacted=compacted,
        messages=result,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        method=method,
    )


def _sum_text_tokens(obj: Any) -> int:
    if isinstance(obj, str):
        return estimate_tokens(obj)
    if isinstance(obj, dict):
        return sum(_sum_text_tokens(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_sum_text_tokens(item) for item in obj)
    return estimate_tokens(str(obj))


def _estimate_message_tokens(msg: Dict[str, Any]) -> int:
    return _sum_text_tokens(msg.get("content", ""))


def _truncate_tool_results(
    messages: List[Dict[str, Any]],
    keep_last_pairs: int,
    max_lines: int,
) -> None:
    cutoff = max(0, len(messages) - keep_last_pairs * 2)
    for i in range(cutoff):
        msg = messages[i]
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_result":
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


def _drop_middle_turns(
    messages: List[Dict[str, Any]],
    keep_first: int,
    keep_last: int,
) -> List[Dict[str, Any]]:
    first_msg = messages[0]
    turn_messages = messages[1:]

    pairs = [turn_messages[i : i + 2] for i in range(0, len(turn_messages), 2)]

    if len(pairs) <= keep_first + keep_last:
        return messages

    head = pairs[:keep_first]
    tail = pairs[-keep_last:]
    dropped = len(pairs) - keep_first - keep_last

    boundary_assistant = {
        "role": "assistant",
        "content": [
            {
                "type": "text",
                "text": (
                    f"[Conversation compacted: {dropped} turn(s) removed "
                    f"to stay within context window]"
                ),
            }
        ],
    }
    boundary_user = {
        "role": "user",
        "content": "Continue from the remaining context.",
    }

    result = [first_msg]
    for pair in head:
        result.extend(pair)
    result.append(boundary_assistant)
    result.append(boundary_user)
    for pair in tail:
        result.extend(pair)

    return result


def _strip_code_blocks(
    messages: List[Dict[str, Any]],
    keep_last_pairs: int,
) -> None:
    cutoff = max(0, len(messages) - keep_last_pairs * 2)
    for i in range(cutoff):
        msg = messages[i]
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            messages[i]["content"] = _CODE_BLOCK_RE.sub("[code block removed]", content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if "```" in text:
                        block["text"] = _CODE_BLOCK_RE.sub("[code block removed]", text)
