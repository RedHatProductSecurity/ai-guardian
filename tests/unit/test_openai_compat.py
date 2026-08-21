"""Tests for per-provider normalization in openai_compat."""

import unittest

from ai_guardian.integrations.openai_compat import (
    ProviderCaps,
    _flatten_content,
    _flatten_message,
    extract_tool_calls_from_text,
    get_provider_caps,
    normalize_request_kwargs,
    try_parse_json_flexible,
)


class TestGetProviderCaps(unittest.TestCase):
    def test_none_returns_openai_defaults(self):
        caps = get_provider_caps(None)
        self.assertFalse(caps.flatten_content)
        self.assertTrue(caps.supports_tools)
        self.assertFalse(caps.text_tool_parsing)

    def test_openai(self):
        caps = get_provider_caps("openai")
        self.assertFalse(caps.flatten_content)
        self.assertTrue(caps.supports_tools)
        self.assertFalse(caps.text_tool_parsing)

    def test_ollama(self):
        caps = get_provider_caps("ollama")
        self.assertTrue(caps.flatten_content)
        self.assertTrue(caps.supports_tools)
        self.assertTrue(caps.text_tool_parsing)

    def test_llamacpp(self):
        caps = get_provider_caps("llamacpp")
        self.assertTrue(caps.flatten_content)
        self.assertTrue(caps.supports_tools)
        self.assertTrue(caps.text_tool_parsing)

    def test_vllm(self):
        caps = get_provider_caps("vllm")
        self.assertFalse(caps.flatten_content)
        self.assertTrue(caps.supports_tools)
        self.assertTrue(caps.text_tool_parsing)

    def test_azure(self):
        caps = get_provider_caps("azure")
        self.assertFalse(caps.flatten_content)
        self.assertTrue(caps.supports_tools)
        self.assertFalse(caps.text_tool_parsing)

    def test_openai_compatible_canonical(self):
        caps = get_provider_caps("openai-compatible")
        self.assertFalse(caps.flatten_content)
        self.assertTrue(caps.supports_tools)
        self.assertFalse(caps.text_tool_parsing)

    def test_mlx(self):
        caps = get_provider_caps("mlx")
        self.assertTrue(caps.flatten_content)
        self.assertTrue(caps.supports_tools)
        self.assertTrue(caps.text_tool_parsing)

    def test_lm_studio(self):
        caps = get_provider_caps("lm-studio")
        self.assertFalse(caps.flatten_content)
        self.assertTrue(caps.supports_tools)
        self.assertFalse(caps.text_tool_parsing)

    def test_unknown_provider_returns_openai_defaults(self):
        caps = get_provider_caps("some-future-provider")
        self.assertFalse(caps.flatten_content)
        self.assertTrue(caps.supports_tools)
        self.assertFalse(caps.text_tool_parsing)


class TestFlattenContent(unittest.TestCase):
    def test_string_passthrough(self):
        self.assertEqual(_flatten_content("hello"), "hello")

    def test_none_returns_empty(self):
        self.assertEqual(_flatten_content(None), "")

    def test_text_blocks(self):
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]
        self.assertEqual(_flatten_content(content), "Hello\nWorld")

    def test_string_list(self):
        content = ["Hello", "World"]
        self.assertEqual(_flatten_content(content), "Hello\nWorld")

    def test_mixed_blocks(self):
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "image_url", "image_url": {"url": "http://example.com"}},
            {"type": "text", "text": "World"},
        ]
        self.assertEqual(_flatten_content(content), "Hello\nWorld")

    def test_empty_list(self):
        self.assertEqual(_flatten_content([]), "")

    def test_block_with_empty_text(self):
        content = [{"type": "text", "text": ""}]
        self.assertEqual(_flatten_content(content), "")

    def test_non_list_non_string(self):
        self.assertEqual(_flatten_content(42), "42")


class TestFlattenMessage(unittest.TestCase):
    def test_string_content_unchanged(self):
        msg = {"role": "user", "content": "hello"}
        result = _flatten_message(msg)
        self.assertEqual(result, msg)

    def test_none_content_unchanged(self):
        msg = {"role": "assistant", "content": None}
        result = _flatten_message(msg)
        self.assertEqual(result, msg)

    def test_structured_content_flattened(self):
        msg = {
            "role": "user",
            "content": [{"type": "text", "text": "Hello world"}],
        }
        result = _flatten_message(msg)
        self.assertEqual(result["role"], "user")
        self.assertEqual(result["content"], "Hello world")

    def test_original_dict_not_mutated(self):
        original_content = [{"type": "text", "text": "Hello"}]
        msg = {"role": "user", "content": original_content}
        _flatten_message(msg)
        self.assertIsInstance(msg["content"], list)

    def test_preserves_other_keys(self):
        msg = {
            "role": "user",
            "content": [{"type": "text", "text": "Hi"}],
            "name": "alice",
        }
        result = _flatten_message(msg)
        self.assertEqual(result["name"], "alice")
        self.assertEqual(result["content"], "Hi")


class TestNormalizeRequestKwargs(unittest.TestCase):
    def test_no_normalization_needed(self):
        caps = ProviderCaps()
        kwargs = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "function": {"name": "bash"}}],
        }
        result = normalize_request_kwargs(kwargs, caps)
        self.assertIs(result, kwargs)

    def test_flatten_content_for_ollama(self):
        caps = get_provider_caps("ollama")
        kwargs = {
            "model": "llama3",
            "messages": [
                {"role": "system", "content": "Be helpful"},
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "Hello world"}],
                },
                {"role": "assistant", "content": "Hi there"},
            ],
        }
        result = normalize_request_kwargs(kwargs, caps)
        self.assertEqual(result["messages"][0]["content"], "Be helpful")
        self.assertEqual(result["messages"][1]["content"], "Hello world")
        self.assertEqual(result["messages"][2]["content"], "Hi there")

    def test_strip_tools_when_unsupported(self):
        caps = ProviderCaps(supports_tools=False)
        kwargs = {
            "model": "llama3",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "function": {"name": "bash"}}],
            "tool_choice": "auto",
        }
        result = normalize_request_kwargs(kwargs, caps)
        self.assertNotIn("tools", result)
        self.assertNotIn("tool_choice", result)
        self.assertEqual(result["model"], "llama3")

    def test_original_kwargs_not_mutated(self):
        caps = get_provider_caps("ollama")
        original_msgs = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Hello"}],
            }
        ]
        kwargs = {"model": "llama3", "messages": original_msgs}
        normalize_request_kwargs(kwargs, caps)
        self.assertIsInstance(kwargs["messages"][0]["content"], list)

    def test_flatten_and_strip_tools_combined(self):
        caps = ProviderCaps(flatten_content=True, supports_tools=False)
        kwargs = {
            "model": "codellama",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "Write code"}],
                }
            ],
            "tools": [{"type": "function", "function": {"name": "bash"}}],
        }
        result = normalize_request_kwargs(kwargs, caps)
        self.assertEqual(result["messages"][0]["content"], "Write code")
        self.assertNotIn("tools", result)

    def test_no_messages_key(self):
        caps = get_provider_caps("ollama")
        kwargs = {"model": "llama3"}
        result = normalize_request_kwargs(kwargs, caps)
        self.assertEqual(result["model"], "llama3")

    def test_empty_messages(self):
        caps = get_provider_caps("ollama")
        kwargs = {"model": "llama3", "messages": []}
        result = normalize_request_kwargs(kwargs, caps)
        self.assertEqual(result["messages"], [])

    def test_vllm_no_flattening(self):
        caps = get_provider_caps("vllm")
        structured_msg = {
            "role": "user",
            "content": [{"type": "text", "text": "Hello"}],
        }
        kwargs = {"model": "mistral", "messages": [structured_msg]}
        result = normalize_request_kwargs(kwargs, caps)
        self.assertIs(result, kwargs)


class TestTryParseJsonFlexible(unittest.TestCase):
    def test_valid_json(self):
        result = try_parse_json_flexible('{"name": "bash"}')
        self.assertEqual(result, {"name": "bash"})

    def test_single_quotes(self):
        result = try_parse_json_flexible("{'name': 'bash'}")
        self.assertEqual(result, {"name": "bash"})

    def test_invalid_returns_none(self):
        self.assertIsNone(try_parse_json_flexible("hello world"))

    def test_newline_separated_objects(self):
        text = '{"a": 1}\n{"b": 2}'
        result = try_parse_json_flexible(text)
        self.assertEqual(result, [{"a": 1}, {"b": 2}])

    def test_mixed_newline_returns_none(self):
        text = '{"a": 1}\nnot json'
        self.assertIsNone(try_parse_json_flexible(text))

    def test_json_list(self):
        result = try_parse_json_flexible('[{"a": 1}, {"b": 2}]')
        self.assertEqual(result, [{"a": 1}, {"b": 2}])


class TestExtractToolCallsFromText(unittest.TestCase):
    def test_json_with_name_and_arguments(self):
        text = '{"name": "bash", "arguments": {"command": "ls"}}'
        result = extract_tool_calls_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "bash")
        self.assertEqual(result[0]["arguments"], {"command": "ls"})
        self.assertTrue(result[0]["id"].startswith("text_tc_"))

    def test_json_with_name_and_input(self):
        text = '{"name": "Read", "input": {"path": "src/main.py"}}'
        result = extract_tool_calls_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Read")
        self.assertEqual(result[0]["arguments"], {"path": "src/main.py"})

    def test_code_fence_wrapped(self):
        text = '```json\n{"name": "bash", "arguments": {"command": "pwd"}}\n```'
        result = extract_tool_calls_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "bash")

    def test_code_fence_no_language_tag(self):
        text = '```\n{"name": "bash", "arguments": {"command": "pwd"}}\n```'
        result = extract_tool_calls_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "bash")

    def test_single_quote_python_dict(self):
        text = "{'name': 'bash', 'arguments': {'command': 'ls'}}"
        result = extract_tool_calls_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "bash")

    def test_multiple_tool_calls_list(self):
        text = (
            '[{"name": "bash", "arguments": {"command": "ls"}},'
            ' {"name": "Read", "arguments": {"path": "f.py"}}]'
        )
        result = extract_tool_calls_from_text(text)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "bash")
        self.assertEqual(result[1]["name"], "Read")

    def test_newline_separated_tool_calls(self):
        text = (
            '{"name": "bash", "arguments": {"command": "ls"}}\n'
            '{"name": "Read", "arguments": {"path": "f.py"}}'
        )
        result = extract_tool_calls_from_text(text)
        self.assertEqual(len(result), 2)

    def test_unknown_tool_name_filtered(self):
        text = '{"name": "unknown_tool", "arguments": {"x": 1}}'
        result = extract_tool_calls_from_text(text, known_tool_names=["bash", "Read"])
        self.assertEqual(result, [])

    def test_known_tool_names_none_accepts_any(self):
        text = '{"name": "any_tool", "arguments": {"x": 1}}'
        result = extract_tool_calls_from_text(text, known_tool_names=None)
        self.assertEqual(len(result), 1)

    def test_known_tool_name_accepted(self):
        text = '{"name": "bash", "arguments": {"command": "ls"}}'
        result = extract_tool_calls_from_text(text, known_tool_names=["bash", "Read"])
        self.assertEqual(len(result), 1)

    def test_plain_text_no_extraction(self):
        result = extract_tool_calls_from_text("Hello, how can I help?")
        self.assertEqual(result, [])

    def test_json_without_name_key(self):
        text = '{"foo": "bar", "baz": 42}'
        result = extract_tool_calls_from_text(text)
        self.assertEqual(result, [])

    def test_empty_string(self):
        self.assertEqual(extract_tool_calls_from_text(""), [])
        self.assertEqual(extract_tool_calls_from_text("   "), [])

    def test_arguments_as_json_string(self):
        text = '{"name": "bash", "arguments": "{\\"command\\": \\"ls\\"}"}'
        result = extract_tool_calls_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["arguments"], {"command": "ls"})

    def test_no_arguments_or_input_key(self):
        text = '{"name": "bash", "params": {"command": "ls"}}'
        result = extract_tool_calls_from_text(text)
        self.assertEqual(result, [])

    def test_arguments_not_dict(self):
        text = '{"name": "bash", "arguments": [1, 2, 3]}'
        result = extract_tool_calls_from_text(text)
        self.assertEqual(result, [])

    def test_text_with_surrounding_prose(self):
        text = (
            "I'll run the command:\n"
            '```json\n{"name": "bash", "arguments": {"command": "ls"}}\n```\n'
            "This will list files."
        )
        result = extract_tool_calls_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "bash")


if __name__ == "__main__":
    unittest.main()
