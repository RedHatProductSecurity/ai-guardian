"""Tests for per-provider normalization in openai_compat."""

import unittest

from ai_guardian.integrations.openai_compat import (
    ProviderCaps,
    _flatten_content,
    _flatten_message,
    get_provider_caps,
    normalize_request_kwargs,
)


class TestGetProviderCaps(unittest.TestCase):
    def test_none_returns_openai_defaults(self):
        caps = get_provider_caps(None)
        self.assertFalse(caps.flatten_content)
        self.assertTrue(caps.supports_tools)

    def test_openai(self):
        caps = get_provider_caps("openai")
        self.assertFalse(caps.flatten_content)
        self.assertTrue(caps.supports_tools)

    def test_ollama(self):
        caps = get_provider_caps("ollama")
        self.assertTrue(caps.flatten_content)
        self.assertTrue(caps.supports_tools)

    def test_llamacpp(self):
        caps = get_provider_caps("llamacpp")
        self.assertTrue(caps.flatten_content)
        self.assertTrue(caps.supports_tools)

    def test_vllm(self):
        caps = get_provider_caps("vllm")
        self.assertFalse(caps.flatten_content)
        self.assertTrue(caps.supports_tools)

    def test_azure(self):
        caps = get_provider_caps("azure")
        self.assertFalse(caps.flatten_content)
        self.assertTrue(caps.supports_tools)

    def test_unknown_provider_returns_openai_defaults(self):
        caps = get_provider_caps("some-future-provider")
        self.assertFalse(caps.flatten_content)
        self.assertTrue(caps.supports_tools)


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


if __name__ == "__main__":
    unittest.main()
