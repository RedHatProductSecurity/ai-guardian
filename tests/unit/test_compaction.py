"""Tests for conversation compaction module."""

import copy

from ai_guardian.integrations.anthropic.agent import AnthropicLoopStrategy
from ai_guardian.integrations.compaction import (
    CompactionResult,
    _drop_middle_turns,
    _strip_code_blocks,
    _truncate_tool_results,
    compact_messages,
    estimate_messages_tokens,
    estimate_tokens,
    get_context_limit,
)
from ai_guardian.integrations.openai import OpenAILoopStrategy

_ANTHROPIC = AnthropicLoopStrategy()


def _make_tool_use_block(tool_id, name="bash", inp=None):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": inp or {}}


def _make_tool_result_block(tool_id, content="ok"):
    return {"type": "tool_result", "tool_use_id": tool_id, "content": content}


def _make_text_block(text):
    return {"type": "text", "text": text}


def _make_turn_pair(turn_num, tool_result_content="result output"):
    tool_id = f"tool_{turn_num}"
    assistant = {
        "role": "assistant",
        "content": [_make_tool_use_block(tool_id, "bash", {"command": "echo hi"})],
    }
    user = {
        "role": "user",
        "content": [_make_tool_result_block(tool_id, tool_result_content)],
    }
    return assistant, user


def _make_conversation(num_turns, tool_result_content="short result"):
    messages = [{"role": "user", "content": "Initial prompt"}]
    for i in range(num_turns):
        a, u = _make_turn_pair(i, tool_result_content)
        messages.extend([a, u])
    return messages


class TestGetContextLimit:
    def test_claude_model_returns_default(self):
        assert get_context_limit("claude-sonnet-5") == 200_000

    def test_claude_variant_returns_default(self):
        assert get_context_limit("claude-sonnet-5-20250601") == 200_000

    def test_openai_model(self):
        assert get_context_limit("gpt-4o") == 128_000

    def test_unknown_model_returns_default(self):
        assert get_context_limit("unknown-model-xyz") == 200_000

    def test_prefix_match_gpt(self):
        assert get_context_limit("gpt-4o-2024-08-06") == 128_000


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_rough_accuracy(self):
        text = "hello world this is a test"
        result = estimate_tokens(text)
        assert result > 0
        assert result == len(text) // 4

    def test_none_equivalent(self):
        assert estimate_tokens("") == 0


class TestEstimateMessagesTokens:
    def test_simple_messages(self):
        messages = [
            {"role": "user", "content": "Hello world"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = estimate_messages_tokens(messages)
        assert result > 0

    def test_with_system(self):
        messages = [{"role": "user", "content": "Hi"}]
        with_system = estimate_messages_tokens(messages, system="You are helpful")
        without_system = estimate_messages_tokens(messages)
        assert with_system > without_system

    def test_content_blocks(self):
        messages = [
            {
                "role": "user",
                "content": [
                    _make_tool_result_block("t1", "a" * 100),
                    _make_tool_result_block("t2", "b" * 200),
                ],
            }
        ]
        result = estimate_messages_tokens(messages)
        assert result > 0


class TestTruncateToolResults:
    def test_truncates_old_results(self):
        long_output = "\n".join(f"line {i}" for i in range(100))
        messages = _make_conversation(0)
        a, u = _make_turn_pair(0, long_output)
        messages.extend([a, u])
        a2, u2 = _make_turn_pair(1, "recent")
        messages.extend([a2, u2])

        msgs = copy.deepcopy(messages)
        _truncate_tool_results(msgs, 1, 10, _ANTHROPIC)
        old_content = msgs[2]["content"][0]["content"]
        assert "[truncated:" in old_content
        assert old_content.count("\n") <= 11

    def test_preserves_recent_results(self):
        long_output = "\n".join(f"line {i}" for i in range(100))
        messages = _make_conversation(0)
        a, u = _make_turn_pair(0, "old")
        messages.extend([a, u])
        a2, u2 = _make_turn_pair(1, long_output)
        messages.extend([a2, u2])

        msgs = copy.deepcopy(messages)
        _truncate_tool_results(msgs, 1, 10, _ANTHROPIC)
        recent_content = msgs[4]["content"][0]["content"]
        assert "[truncated:" not in recent_content
        assert recent_content == long_output

    def test_preserves_block_structure(self):
        messages = _make_conversation(3, "output text")
        msgs = copy.deepcopy(messages)
        _truncate_tool_results(msgs, 1, 5, _ANTHROPIC)
        for msg in msgs:
            if msg["role"] == "user" and isinstance(msg["content"], list):
                for block in msg["content"]:
                    assert "type" in block
                    assert block["type"] == "tool_result"

    def test_short_results_unchanged(self):
        messages = _make_conversation(3, "short")
        original = copy.deepcopy(messages)
        msgs = copy.deepcopy(messages)
        _truncate_tool_results(msgs, 1, 50, _ANTHROPIC)
        for i in range(len(msgs)):
            if msgs[i]["role"] == "user" and isinstance(msgs[i]["content"], list):
                for j, block in enumerate(msgs[i]["content"]):
                    if block.get("type") == "tool_result":
                        assert block["content"] == original[i]["content"][j]["content"]


class TestDropMiddleTurns:
    def test_keeps_first_and_last(self):
        messages = _make_conversation(10)
        result = _drop_middle_turns(messages, 2, 2, _ANTHROPIC)
        assert result[0] == messages[0]
        assert result[-1] == messages[-1]
        assert result[-2] == messages[-2]
        assert len(result) < len(messages)

    def test_inserts_boundary_message(self):
        messages = _make_conversation(10)
        result = _drop_middle_turns(messages, 1, 1, _ANTHROPIC)
        boundary_msgs = [
            m
            for m in result
            if m.get("role") == "assistant"
            and isinstance(m.get("content"), list)
            and any(
                "[Conversation compacted:" in b.get("text", "")
                for b in m["content"]
                if isinstance(b, dict)
            )
        ]
        assert len(boundary_msgs) == 1

    def test_maintains_alternation(self):
        messages = _make_conversation(10)
        result = _drop_middle_turns(messages, 2, 2, _ANTHROPIC)
        for i in range(1, len(result)):
            prev_role = result[i - 1]["role"]
            curr_role = result[i]["role"]
            if i == 1:
                continue
            assert (
                prev_role != curr_role
            ), f"Adjacent messages at {i-1},{i} have same role: {curr_role}"

    def test_noop_when_short(self):
        messages = _make_conversation(3)
        result = _drop_middle_turns(messages, 2, 2, _ANTHROPIC)
        assert result == messages

    def test_dropped_count_in_boundary(self):
        messages = _make_conversation(10)
        result = _drop_middle_turns(messages, 1, 1, _ANTHROPIC)
        boundary = [
            m
            for m in result
            if m.get("role") == "assistant"
            and isinstance(m.get("content"), list)
            and any(
                "[Conversation compacted:" in b.get("text", "")
                for b in m["content"]
                if isinstance(b, dict)
            )
        ]
        assert len(boundary) == 1
        text = boundary[0]["content"][0]["text"]
        assert "8 turn(s) removed" in text

    def test_preserves_initial_prompt(self):
        messages = _make_conversation(10)
        messages[0]["content"] = "My important initial prompt"
        result = _drop_middle_turns(messages, 1, 1, _ANTHROPIC)
        assert result[0]["content"] == "My important initial prompt"


class TestStripCodeBlocks:
    def test_strips_old_code_blocks(self):
        msgs = [
            {"role": "user", "content": "prompt"},
            {
                "role": "assistant",
                "content": [
                    _make_text_block(
                        "Here is code:\n```python\nprint('hello')\n```\nDone."
                    )
                ],
            },
            {"role": "user", "content": [_make_tool_result_block("t1", "ok")]},
            {
                "role": "assistant",
                "content": [_make_text_block("Recent message with ```code```")],
            },
            {"role": "user", "content": [_make_tool_result_block("t2", "ok")]},
        ]
        _strip_code_blocks(msgs, 1, _ANTHROPIC)
        old_text = msgs[1]["content"][0]["text"]
        assert "[code block removed]" in old_text
        assert "print('hello')" not in old_text

    def test_preserves_recent_code_blocks(self):
        msgs = [
            {"role": "user", "content": "prompt"},
            {
                "role": "assistant",
                "content": [_make_text_block("old message")],
            },
            {"role": "user", "content": [_make_tool_result_block("t1", "ok")]},
            {
                "role": "assistant",
                "content": [_make_text_block("```python\nimportant_code()\n```")],
            },
            {"role": "user", "content": [_make_tool_result_block("t2", "ok")]},
        ]
        _strip_code_blocks(msgs, 1, _ANTHROPIC)
        recent_text = msgs[3]["content"][0]["text"]
        assert "important_code()" in recent_text

    def test_handles_string_content(self):
        msgs = [
            {"role": "user", "content": "prompt"},
            {
                "role": "assistant",
                "content": "Here:\n```bash\nls\n```\nDone",
            },
            {"role": "user", "content": "next"},
            {"role": "assistant", "content": "recent"},
            {"role": "user", "content": "last"},
        ]
        _strip_code_blocks(msgs, 1, _ANTHROPIC)
        assert "[code block removed]" in msgs[1]["content"]


class TestCompactMessages:
    def test_no_compaction_short_conversation(self):
        messages = _make_conversation(1)
        result = compact_messages(messages, context_limit=200_000, strategy=_ANTHROPIC)
        assert not result.compacted
        assert result.method == "none"
        assert result.messages is messages

    def test_compaction_applied_with_large_content(self):
        big = "x" * 50_000
        messages = _make_conversation(20, tool_result_content=big)
        result = compact_messages(
            messages,
            context_limit=200_000,
            strategy=_ANTHROPIC,
            threshold=0.1,
            keep_last=2,
        )
        assert result.compacted
        assert result.tokens_after < result.tokens_before
        assert len(result.messages) < len(messages)

    def test_preserves_initial_prompt(self):
        big = "x" * 50_000
        messages = _make_conversation(20, tool_result_content=big)
        messages[0]["content"] = "Very important initial prompt"
        result = compact_messages(
            messages,
            context_limit=200_000,
            strategy=_ANTHROPIC,
            threshold=0.1,
            keep_last=2,
        )
        assert result.messages[0]["content"] == "Very important initial prompt"

    def test_truncation_only_when_sufficient(self):
        lines = "\n".join(f"line {i}" for i in range(200))
        messages = _make_conversation(5, tool_result_content=lines)
        result = compact_messages(
            messages,
            context_limit=200_000,
            strategy=_ANTHROPIC,
            threshold=0.01,
            keep_last=2,
        )
        if result.compacted:
            assert "truncate_and_strip" in result.method

    def test_does_not_mutate_original(self):
        big = "x" * 50_000
        messages = _make_conversation(10, tool_result_content=big)
        original_len = len(messages)
        compact_messages(
            messages,
            context_limit=200_000,
            strategy=_ANTHROPIC,
            threshold=0.1,
            keep_last=2,
        )
        assert len(messages) == original_len

    def test_result_dataclass_fields(self):
        messages = _make_conversation(2)
        result = compact_messages(messages, context_limit=200_000, strategy=_ANTHROPIC)
        assert isinstance(result, CompactionResult)
        assert isinstance(result.compacted, bool)
        assert isinstance(result.tokens_before, int)
        assert isinstance(result.tokens_after, int)
        assert isinstance(result.method, str)
        assert isinstance(result.messages, list)


# ---------------------------------------------------------------------------
# OpenAI-format message helpers
# ---------------------------------------------------------------------------


def _make_openai_tool_result(tool_call_id, content="ok"):
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def _make_openai_assistant(text="done", tool_calls=None):
    msg = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _make_openai_tool_call_ref(tool_id, name="bash"):
    return {
        "id": tool_id,
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


def _make_openai_turn_pair(turn_num, tool_result_content="result output"):
    tool_id = f"call_{turn_num}"
    assistant = _make_openai_assistant(
        text=None,
        tool_calls=[_make_openai_tool_call_ref(tool_id)],
    )
    tool_msg = _make_openai_tool_result(tool_id, tool_result_content)
    return assistant, tool_msg


def _make_openai_conversation(num_turns, tool_result_content="short result"):
    messages = [{"role": "user", "content": "Initial prompt"}]
    for i in range(num_turns):
        a, t = _make_openai_turn_pair(i, tool_result_content)
        messages.extend([a, t])
    return messages


# ---------------------------------------------------------------------------
# Strategy method tests — Anthropic (base default)
# ---------------------------------------------------------------------------


class TestAnthropicStrategyTruncateToolResult:
    def setup_method(self):
        self.strategy = _ANTHROPIC

    def test_truncates_long_tool_result_block(self):
        long_output = "\n".join(f"line {i}" for i in range(100))
        msg = {
            "role": "user",
            "content": [_make_tool_result_block("t1", long_output)],
        }
        self.strategy.truncate_tool_result(msg, 10)
        text = msg["content"][0]["content"]
        assert "[truncated:" in text
        assert text.count("\n") <= 11

    def test_ignores_non_user_messages(self):
        msg = {"role": "assistant", "content": [_make_text_block("hello")]}
        original = copy.deepcopy(msg)
        self.strategy.truncate_tool_result(msg, 10)
        assert msg == original

    def test_ignores_short_results(self):
        msg = {
            "role": "user",
            "content": [_make_tool_result_block("t1", "short")],
        }
        self.strategy.truncate_tool_result(msg, 50)
        assert msg["content"][0]["content"] == "short"


class TestAnthropicStrategyStripCodeBlocks:
    def setup_method(self):
        self.strategy = _ANTHROPIC

    def test_strips_code_from_text_block(self):
        msg = {
            "role": "assistant",
            "content": [_make_text_block("```python\nprint()\n```")],
        }
        self.strategy.strip_code_blocks(msg)
        assert "[code block removed]" in msg["content"][0]["text"]
        assert "print()" not in msg["content"][0]["text"]

    def test_strips_code_from_string_content(self):
        msg = {"role": "assistant", "content": "```bash\nls\n```"}
        self.strategy.strip_code_blocks(msg)
        assert "[code block removed]" in msg["content"]

    def test_ignores_non_assistant_messages(self):
        msg = {"role": "user", "content": "```code```"}
        original = copy.deepcopy(msg)
        self.strategy.strip_code_blocks(msg)
        assert msg == original


class TestAnthropicStrategyCreateBoundary:
    def setup_method(self):
        self.strategy = _ANTHROPIC

    def test_returns_two_messages(self):
        boundary = self.strategy.create_compaction_boundary(5)
        assert len(boundary) == 2
        assert boundary[0]["role"] == "assistant"
        assert boundary[1]["role"] == "user"

    def test_assistant_uses_content_block_list(self):
        boundary = self.strategy.create_compaction_boundary(3)
        content = boundary[0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "text"
        assert "3 turn(s) removed" in content[0]["text"]


# ---------------------------------------------------------------------------
# Strategy method tests — OpenAI
# ---------------------------------------------------------------------------


class TestOpenAIStrategyTruncateToolResult:
    def setup_method(self):
        self.strategy = OpenAILoopStrategy()

    def test_truncates_long_tool_message(self):
        long_output = "\n".join(f"line {i}" for i in range(100))
        msg = _make_openai_tool_result("call_1", long_output)
        self.strategy.truncate_tool_result(msg, 10)
        assert "[truncated:" in msg["content"]
        assert msg["content"].count("\n") <= 11

    def test_ignores_non_tool_messages(self):
        msg = {"role": "user", "content": "hello"}
        original = copy.deepcopy(msg)
        self.strategy.truncate_tool_result(msg, 10)
        assert msg == original

    def test_ignores_anthropic_tool_result_blocks(self):
        msg = {
            "role": "user",
            "content": [_make_tool_result_block("t1", "\n".join("x" * 100))],
        }
        original = copy.deepcopy(msg)
        self.strategy.truncate_tool_result(msg, 10)
        assert msg == original

    def test_ignores_short_results(self):
        msg = _make_openai_tool_result("call_1", "short")
        self.strategy.truncate_tool_result(msg, 50)
        assert msg["content"] == "short"


class TestOpenAIStrategyStripCodeBlocks:
    def setup_method(self):
        self.strategy = OpenAILoopStrategy()

    def test_strips_code_from_string_content(self):
        msg = {"role": "assistant", "content": "Here:\n```python\nprint()\n```\nDone."}
        self.strategy.strip_code_blocks(msg)
        assert "[code block removed]" in msg["content"]
        assert "print()" not in msg["content"]

    def test_ignores_non_assistant_messages(self):
        msg = {"role": "user", "content": "```code```"}
        original = copy.deepcopy(msg)
        self.strategy.strip_code_blocks(msg)
        assert msg == original

    def test_no_code_blocks_unchanged(self):
        msg = {"role": "assistant", "content": "plain text"}
        self.strategy.strip_code_blocks(msg)
        assert msg["content"] == "plain text"


class TestOpenAIStrategyCreateBoundary:
    def setup_method(self):
        self.strategy = OpenAILoopStrategy()

    def test_returns_two_messages(self):
        boundary = self.strategy.create_compaction_boundary(5)
        assert len(boundary) == 2
        assert boundary[0]["role"] == "assistant"
        assert boundary[1]["role"] == "user"

    def test_assistant_uses_plain_string(self):
        boundary = self.strategy.create_compaction_boundary(3)
        content = boundary[0]["content"]
        assert isinstance(content, str)
        assert "3 turn(s) removed" in content


# ---------------------------------------------------------------------------
# compact_messages with strategy parameter
# ---------------------------------------------------------------------------


class TestCompactMessagesWithStrategy:
    def test_openai_strategy_truncates_tool_messages(self):
        long_output = "\n".join(f"line {i}" for i in range(200))
        messages = _make_openai_conversation(5, tool_result_content=long_output)
        result = compact_messages(
            messages,
            context_limit=200_000,
            threshold=0.01,
            keep_last=2,
            strategy=OpenAILoopStrategy(),
        )
        if result.compacted:
            old_tool_msgs = [m for m in result.messages[:4] if m.get("role") == "tool"]
            for m in old_tool_msgs:
                assert "[truncated:" in m["content"]

    def test_openai_strategy_boundary_uses_plain_string(self):
        big = "x" * 50_000
        messages = _make_openai_conversation(20, tool_result_content=big)
        result = compact_messages(
            messages,
            context_limit=200_000,
            threshold=0.1,
            keep_last=2,
            strategy=OpenAILoopStrategy(),
        )
        assert result.compacted
        boundary_msgs = [
            m
            for m in result.messages
            if m.get("role") == "assistant"
            and isinstance(m.get("content"), str)
            and "[Conversation compacted:" in m["content"]
        ]
        assert len(boundary_msgs) == 1

    def test_openai_strategy_strips_code_blocks(self):
        messages = [
            {"role": "user", "content": "prompt"},
            {
                "role": "assistant",
                "content": "Here:\n```python\nprint('hello')\n```\nDone.",
            },
            _make_openai_tool_result("call_1", "ok"),
            {"role": "assistant", "content": "Recent with ```code```"},
            _make_openai_tool_result("call_2", "ok"),
        ]
        _strip_code_blocks(messages, 1, OpenAILoopStrategy())
        assert "[code block removed]" in messages[1]["content"]

    def test_openai_full_compaction(self):
        big = "x" * 50_000
        messages = _make_openai_conversation(20, tool_result_content=big)
        result = compact_messages(
            messages,
            context_limit=200_000,
            threshold=0.1,
            keep_last=2,
            strategy=OpenAILoopStrategy(),
        )
        assert result.compacted
        assert result.tokens_after < result.tokens_before
        assert len(result.messages) < len(messages)
