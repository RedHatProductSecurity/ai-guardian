"""Tests for the LLM client integration wrapper."""

import logging
import os
import sys
import warnings
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.integrations.base import (
    AgentLoopStrategy,
    ParsedResponse,
    ProviderExtractor,
    ToolCall,
    _GuardedClient,
    _MethodChainProxy,
    _StreamProxy,
    _extractor_registry,
    _strategy_registry,
    guarded,
)
from ai_guardian.integrations.anthropic import (
    AnthropicExtractor,
    AnthropicLoopStrategy,
    create_client,
)
from ai_guardian.integrations.openai import OpenAIExtractor, OpenAILoopStrategy
from ai_guardian.sdk import SecurityViolation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_anthropic_client():
    """Build a mock object that looks like anthropic.Anthropic()."""
    mock_create = MagicMock(name="messages.create")
    mock_stream = MagicMock(name="messages.stream")
    messages = SimpleNamespace(create=mock_create, stream=mock_stream)
    client = SimpleNamespace(messages=messages, api_key="sk-test-key")
    return client, mock_create, mock_stream


def _make_mock_response(texts):
    """Build a mock Anthropic Message response with text content blocks."""
    blocks = []
    for t in texts:
        blocks.append(SimpleNamespace(type="text", text=t))
    return SimpleNamespace(content=blocks, model="claude-sonnet-4-20250514")


def _fake_anthropic_module():
    """Create a fake anthropic module with all Anthropic client classes."""
    mod = SimpleNamespace()
    mod.Anthropic = type("Anthropic", (), {})
    mod.AsyncAnthropic = type("AsyncAnthropic", (), {})
    mod.AnthropicVertex = type("AnthropicVertex", (), {})
    mod.AsyncAnthropicVertex = type("AsyncAnthropicVertex", (), {})
    mod.AnthropicBedrock = type("AnthropicBedrock", (), {})
    mod.AsyncAnthropicBedrock = type("AsyncAnthropicBedrock", (), {})
    mod.AnthropicFoundry = type("AnthropicFoundry", (), {})
    mod.AsyncAnthropicFoundry = type("AsyncAnthropicFoundry", (), {})
    return mod


# ============================================================================
# TestProviderExtractor
# ============================================================================


class TestProviderExtractor:
    """ProviderExtractor ABC contract."""

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            ProviderExtractor()

    def test_concrete_subclass_works(self):
        class Dummy(ProviderExtractor):
            @classmethod
            def detect(cls, client):
                return False

            def methods_to_wrap(self):
                return []

            def extract_input(self, method_name, args, kwargs):
                return []

            def extract_output(self, method_name, response):
                return []

        d = Dummy()
        assert d.methods_to_wrap() == []


# ============================================================================
# TestRegistry
# ============================================================================


class TestRegistry:
    """Extractor registration and detection."""

    def test_anthropic_extractor_registered(self):
        for name in AnthropicExtractor._CLIENT_NAMES:
            key = f"anthropic.{name}"
            assert key in _extractor_registry, f"{key} not registered"
            assert _extractor_registry[key] is AnthropicExtractor

    def test_detect_raises_for_unknown_client(self):
        with pytest.raises(ValueError, match="No extractor found"):
            _extractor_registry.detect({"not": "a client"})

    def test_register_custom_extractor(self):
        class FakeExtractor(ProviderExtractor):
            @classmethod
            def detect(cls, client):
                return True

            def methods_to_wrap(self):
                return ["chat"]

            def extract_input(self, method_name, args, kwargs):
                return []

            def extract_output(self, method_name, response):
                return []

        _extractor_registry.register("test_pkg.FakeClient", FakeExtractor)
        assert "test_pkg.FakeClient" in _extractor_registry
        del _extractor_registry["test_pkg.FakeClient"]


# ============================================================================
# TestAnthropicExtractor
# ============================================================================


class TestAnthropicExtractor:
    """AnthropicExtractor detection and text extraction."""

    def test_detect_true_when_anthropic_imported(self):
        fake_mod = _fake_anthropic_module()
        client = fake_mod.Anthropic()
        with patch.dict(sys.modules, {"anthropic": fake_mod}):
            assert AnthropicExtractor.detect(client) is True

    def test_detect_true_for_async_client(self):
        fake_mod = _fake_anthropic_module()
        client = fake_mod.AsyncAnthropic()
        with patch.dict(sys.modules, {"anthropic": fake_mod}):
            assert AnthropicExtractor.detect(client) is True

    def test_detect_true_for_subclass(self):
        fake_mod = _fake_anthropic_module()
        AnthropicVertex = type("AnthropicVertex", (fake_mod.Anthropic,), {})
        client = AnthropicVertex()
        with patch.dict(sys.modules, {"anthropic": fake_mod}):
            assert AnthropicExtractor.detect(client) is True

    def test_detect_true_for_vertex_client(self):
        fake_mod = _fake_anthropic_module()
        client = fake_mod.AnthropicVertex()
        with patch.dict(sys.modules, {"anthropic": fake_mod}):
            assert AnthropicExtractor.detect(client) is True

    def test_detect_true_for_async_vertex_client(self):
        fake_mod = _fake_anthropic_module()
        client = fake_mod.AsyncAnthropicVertex()
        with patch.dict(sys.modules, {"anthropic": fake_mod}):
            assert AnthropicExtractor.detect(client) is True

    def test_detect_true_for_bedrock_client(self):
        fake_mod = _fake_anthropic_module()
        client = fake_mod.AnthropicBedrock()
        with patch.dict(sys.modules, {"anthropic": fake_mod}):
            assert AnthropicExtractor.detect(client) is True

    def test_detect_true_for_foundry_client(self):
        fake_mod = _fake_anthropic_module()
        client = fake_mod.AnthropicFoundry()
        with patch.dict(sys.modules, {"anthropic": fake_mod}):
            assert AnthropicExtractor.detect(client) is True

    def test_detect_false_when_anthropic_not_imported(self):
        with patch.dict(sys.modules, {}, clear=False):
            sys.modules.pop("anthropic", None)
            assert AnthropicExtractor.detect(object()) is False

    def test_detect_false_for_non_anthropic_client(self):
        fake_mod = _fake_anthropic_module()
        with patch.dict(sys.modules, {"anthropic": fake_mod}):
            assert AnthropicExtractor.detect("not a client") is False

    def test_methods_to_wrap(self):
        ext = AnthropicExtractor()
        assert ext.methods_to_wrap() == ["messages.create", "messages.stream"]

    def test_extract_input_string_content(self):
        ext = AnthropicExtractor()
        kwargs = {
            "messages": [{"role": "user", "content": "hello world"}],
        }
        result = ext.extract_input("messages.create", (), kwargs)
        assert result == ["hello world"]

    def test_extract_input_content_blocks(self):
        ext = AnthropicExtractor()
        kwargs = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "block one"},
                        {"type": "image", "source": {}},
                        {"type": "text", "text": "block two"},
                    ],
                }
            ],
        }
        result = ext.extract_input("messages.create", (), kwargs)
        assert result == ["block one", "block two"]

    def test_extract_input_with_system_string(self):
        ext = AnthropicExtractor()
        kwargs = {
            "system": "You are helpful.",
            "messages": [{"role": "user", "content": "hi"}],
        }
        result = ext.extract_input("messages.create", (), kwargs)
        assert result == ["You are helpful.", "hi"]

    def test_extract_input_with_system_list(self):
        ext = AnthropicExtractor()
        kwargs = {
            "system": [
                {"type": "text", "text": "rule one"},
                {"type": "text", "text": "rule two"},
            ],
            "messages": [],
        }
        result = ext.extract_input("messages.create", (), kwargs)
        assert result == ["rule one", "rule two"]

    def test_extract_input_empty_messages(self):
        ext = AnthropicExtractor()
        result = ext.extract_input("messages.create", (), {"messages": []})
        assert result == []

    def test_extract_input_no_messages_key(self):
        ext = AnthropicExtractor()
        result = ext.extract_input("messages.create", (), {})
        assert result == []

    def test_extract_output_text_blocks(self):
        ext = AnthropicExtractor()
        response = _make_mock_response(["hello", "world"])
        result = ext.extract_output("messages.create", response)
        assert result == ["hello", "world"]

    def test_extract_output_tool_use_only(self):
        ext = AnthropicExtractor()
        block = SimpleNamespace(type="tool_use", id="123", name="fn", input={})
        response = SimpleNamespace(content=[block])
        result = ext.extract_output("messages.create", response)
        assert result == []

    def test_extract_output_no_content(self):
        ext = AnthropicExtractor()
        response = SimpleNamespace()
        result = ext.extract_output("messages.create", response)
        assert result == []


# ============================================================================
# TestGuardedFunction
# ============================================================================


class TestGuardedFunction:
    """The guarded() factory function."""

    def test_raises_value_error_for_unknown_client(self):
        with pytest.raises(ValueError, match="No extractor found"):
            guarded({"not": "a client"})

    def test_auto_detects_anthropic(self):
        fake_mod = _fake_anthropic_module()
        client = fake_mod.Anthropic()
        client.messages = SimpleNamespace(create=lambda: None, stream=lambda: None)
        with patch.dict(sys.modules, {"anthropic": fake_mod}):
            wrapped = guarded(client)
        assert isinstance(wrapped, _GuardedClient)

    def test_explicit_extractor_skips_detection(self):
        class CustomExt(ProviderExtractor):
            @classmethod
            def detect(cls, client):
                return False

            def methods_to_wrap(self):
                return ["do_thing"]

            def extract_input(self, method_name, args, kwargs):
                return []

            def extract_output(self, method_name, response):
                return []

        wrapped = guarded(object(), extractor=CustomExt())
        assert isinstance(wrapped, _GuardedClient)

    def test_action_and_mode_passed_through(self):
        class CustomExt(ProviderExtractor):
            @classmethod
            def detect(cls, client):
                return False

            def methods_to_wrap(self):
                return []

            def extract_input(self, method_name, args, kwargs):
                return []

            def extract_output(self, method_name, response):
                return []

        wrapped = guarded(object(), extractor=CustomExt(), action="warn", mode="rest")
        assert wrapped._action == "warn"
        assert wrapped._mode == "rest"


# ============================================================================
# TestGuardedClientProxy
# ============================================================================


class TestGuardedClientProxy:
    """_GuardedClient proxy interception and scanning."""

    @patch("ai_guardian.integrations.base.monitor")
    def test_intercepts_messages_create(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        mock_create.return_value = _make_mock_response(["response text"])

        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="log")
        result = wrapped.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": "test input"}],
        )

        assert mock_session.check_content.call_count == 2
        input_call = mock_session.check_content.call_args_list[0]
        assert input_call[0][0] == "test input"
        assert input_call[1]["filename"] == "llm_input"
        output_call = mock_session.check_content.call_args_list[1]
        assert output_call[0][0] == "response text"
        assert output_call[1]["filename"] == "llm_output"
        assert result.model == "claude-sonnet-4-20250514"

    def test_non_wrapped_attributes_pass_through(self):
        client, _, _ = _make_mock_anthropic_client()
        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext)
        assert wrapped.api_key == "sk-test-key"

    @patch("ai_guardian.integrations.base.monitor")
    def test_block_raises_on_input_threat(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        mock_session.check_content.side_effect = SecurityViolation(
            CheckResult(
                blocked=True,
                detected=True,
                violation_type="secret",
                message="Secret detected",
            )
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="block")

        with pytest.raises(SecurityViolation, match="Secret detected"):
            wrapped.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                messages=[{"role": "user", "content": "my secret key"}],
            )
        mock_create.assert_not_called()

    @patch("ai_guardian.integrations.base.monitor")
    def test_block_raises_on_output_threat(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        call_count = [0]

        def check_side_effect(text, filename="input"):
            call_count[0] += 1
            if filename == "llm_output":
                raise SecurityViolation(
                    CheckResult(
                        blocked=True,
                        detected=True,
                        violation_type="secret",
                        message="Secret in response",
                    )
                )
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        mock_create.return_value = _make_mock_response(["leaked secret"])
        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="block")

        with pytest.raises(SecurityViolation, match="Secret in response"):
            wrapped.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                messages=[{"role": "user", "content": "safe input"}],
            )
        mock_create.assert_called_once()

    @patch("ai_guardian.integrations.base.monitor")
    def test_output_violation_attaches_response_and_sanitized_text(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()

        def check_side_effect(text, filename="input"):
            if filename == "llm_output":
                raise SecurityViolation(
                    CheckResult(
                        blocked=True,
                        detected=True,
                        violation_type="secret",
                        message="Secret in response",
                    )
                )
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_session.sanitize.return_value = {"sanitized_text": "[REDACTED]"}
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        original_response = _make_mock_response(["leaked secret"])
        mock_create.return_value = original_response
        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="block")

        with pytest.raises(SecurityViolation) as exc_info:
            wrapped.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                messages=[{"role": "user", "content": "safe input"}],
            )

        exc = exc_info.value
        assert exc.response is original_response
        assert exc.sanitized_text == "[REDACTED]"
        mock_session.sanitize.assert_called_once_with("leaked secret")

    @patch("ai_guardian.integrations.base.monitor")
    def test_input_violation_has_no_response(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        mock_session.check_content.side_effect = SecurityViolation(
            CheckResult(
                blocked=True,
                detected=True,
                violation_type="secret",
                message="Secret in input",
            )
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="block")

        with pytest.raises(SecurityViolation) as exc_info:
            wrapped.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                messages=[{"role": "user", "content": "my secret"}],
            )

        exc = exc_info.value
        assert exc.response is None
        assert exc.sanitized_text is None

    @patch("ai_guardian.integrations.base.monitor")
    def test_log_action_no_exception(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=True
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        mock_create.return_value = _make_mock_response(["output"])
        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="log")

        result = wrapped.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": "test"}],
        )
        assert result is not None

    @patch("ai_guardian.integrations.base.monitor")
    def test_scan_input_false_skips_input(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        mock_create.return_value = _make_mock_response(["output"])
        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="log", scan_input=False)

        wrapped.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": "test"}],
        )
        assert mock_session.check_content.call_count == 1
        assert mock_session.check_content.call_args[1]["filename"] == "llm_output"

    @patch("ai_guardian.integrations.base.monitor")
    def test_scan_output_false_skips_output(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        mock_create.return_value = _make_mock_response(["output"])
        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="log", scan_output=False)

        wrapped.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": "test"}],
        )
        assert mock_session.check_content.call_count == 1
        assert mock_session.check_content.call_args[1]["filename"] == "llm_input"

    @patch("ai_guardian.integrations.base.monitor")
    def test_stream_method_returns_stream_proxy(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, _, mock_stream_method = _make_mock_anthropic_client()
        mock_stream_ctx = MagicMock()
        mock_stream_method.return_value = mock_stream_ctx

        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="log")

        result = wrapped.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": "test"}],
        )
        assert isinstance(result, _StreamProxy)


# ============================================================================
# TestStreamProxy
# ============================================================================


class TestStreamProxy:
    """_StreamProxy accumulates and scans on context exit."""

    def test_scans_on_exit(self):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        ext = AnthropicExtractor()

        final_msg = _make_mock_response(["streamed text"])
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.get_final_message = MagicMock(return_value=final_msg)

        proxy = _StreamProxy(mock_stream, ext, "messages.stream", mock_session)
        with proxy:
            pass

        mock_session.check_content.assert_called_once_with(
            "streamed text", filename="llm_output"
        )

    def test_no_scan_on_exception(self):
        mock_session = MagicMock()
        ext = AnthropicExtractor()

        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.get_final_message = MagicMock()

        proxy = _StreamProxy(mock_stream, ext, "messages.stream", mock_session)
        with pytest.raises(RuntimeError):
            with proxy:
                raise RuntimeError("boom")

        mock_stream.get_final_message.assert_not_called()
        mock_session.check_content.assert_not_called()

    def test_passthrough_attributes(self):
        mock_stream = MagicMock()
        mock_stream.some_attr = "value"
        ext = AnthropicExtractor()
        proxy = _StreamProxy(mock_stream, ext, "messages.stream", MagicMock())
        assert proxy.some_attr == "value"

    def test_violation_attaches_response_and_sanitized_text(self):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        mock_session.check_content.side_effect = SecurityViolation(
            CheckResult(
                blocked=True,
                detected=True,
                violation_type="secret",
                message="Secret in stream",
            )
        )
        mock_session.sanitize.return_value = {"sanitized_text": "[REDACTED]"}
        ext = AnthropicExtractor()

        final_msg = _make_mock_response(["leaked secret"])
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.get_final_message = MagicMock(return_value=final_msg)

        proxy = _StreamProxy(mock_stream, ext, "messages.stream", mock_session)
        with pytest.raises(SecurityViolation) as exc_info:
            with proxy:
                pass

        exc = exc_info.value
        assert exc.response is final_msg
        assert exc.sanitized_text == "[REDACTED]"


# ============================================================================
# TestCreateClient
# ============================================================================


_CLEAN_ANTHROPIC_ENV = {
    "ANTHROPIC_API_KEY": "",
    "ANTHROPIC_VERTEX_PROJECT_ID": "",
    "ANTHROPIC_BEDROCK_BASE_URL": "",
    "CLOUD_ML_REGION": "",
}


class TestCreateClient:
    """Auto-detect Anthropic client from env vars."""

    def _mock_anthropic(self):
        mock_mod = MagicMock()
        mock_mod.Anthropic.return_value = MagicMock()
        mock_mod.AnthropicVertex.return_value = MagicMock()
        mock_mod.AnthropicBedrock.return_value = MagicMock()
        return mock_mod

    @patch.dict("os.environ", {**_CLEAN_ANTHROPIC_ENV, "ANTHROPIC_API_KEY": "sk-test"})
    def test_creates_direct_client(self):
        mock_mod = self._mock_anthropic()
        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            result = create_client()
        mock_mod.Anthropic.assert_called_once_with()
        assert result is mock_mod.Anthropic.return_value

    @patch.dict(
        "os.environ",
        {
            **_CLEAN_ANTHROPIC_ENV,
            "ANTHROPIC_VERTEX_PROJECT_ID": "my-project",
            "CLOUD_ML_REGION": "us-east5",
        },
    )
    def test_creates_vertex_client(self):
        mock_mod = self._mock_anthropic()
        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            result = create_client()
        mock_mod.AnthropicVertex.assert_called_once_with(
            project_id="my-project", region="us-east5"
        )
        assert result is mock_mod.AnthropicVertex.return_value

    @patch.dict(
        "os.environ",
        {**_CLEAN_ANTHROPIC_ENV, "ANTHROPIC_VERTEX_PROJECT_ID": "my-project"},
    )
    def test_vertex_default_region(self):
        mock_mod = self._mock_anthropic()
        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            create_client()
        call_kwargs = mock_mod.AnthropicVertex.call_args[1]
        assert call_kwargs["region"] == "us-east5"

    @patch.dict(
        "os.environ",
        {
            **_CLEAN_ANTHROPIC_ENV,
            "ANTHROPIC_BEDROCK_BASE_URL": "https://bedrock.us-east-1.amazonaws.com",
        },
    )
    def test_creates_bedrock_client(self):
        mock_mod = self._mock_anthropic()
        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            result = create_client()
        mock_mod.AnthropicBedrock.assert_called_once_with()
        assert result is mock_mod.AnthropicBedrock.return_value

    @patch.dict(
        "os.environ",
        {
            **_CLEAN_ANTHROPIC_ENV,
            "ANTHROPIC_API_KEY": "sk-test",
            "ANTHROPIC_VERTEX_PROJECT_ID": "my-project",
        },
    )
    def test_raises_on_conflicting_env_vars(self):
        with pytest.raises(ValueError, match="Multiple Anthropic provider env vars"):
            create_client()

    @patch.dict("os.environ", _CLEAN_ANTHROPIC_ENV)
    def test_raises_when_no_env_vars(self):
        with pytest.raises(ValueError, match="No Anthropic credentials found"):
            create_client()

    @patch.dict(
        "os.environ",
        {**_CLEAN_ANTHROPIC_ENV, "ANTHROPIC_VERTEX_PROJECT_ID": "my-project"},
    )
    def test_kwargs_forwarded(self):
        mock_mod = self._mock_anthropic()
        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            create_client(timeout=30.0)
        call_kwargs = mock_mod.AnthropicVertex.call_args[1]
        assert call_kwargs["timeout"] == 30.0


# ============================================================================
# TestGuardedAutoClient
# ============================================================================


class TestGuardedAutoClient:
    """guarded() with no client arg auto-creates from env."""

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=False)
    def test_guarded_no_client_auto_creates(self):
        fake_mod = _fake_anthropic_module()
        mock_client = fake_mod.Anthropic()
        mock_client.messages = SimpleNamespace(create=lambda: None, stream=lambda: None)
        with patch.dict(sys.modules, {"anthropic": fake_mod}):
            with patch(
                "ai_guardian.integrations.anthropic.create_client",
                return_value=mock_client,
            ):
                wrapped = guarded(action="log")
        assert isinstance(wrapped, _GuardedClient)


# ============================================================================
# Helpers — OpenAI
# ============================================================================


def _fake_openai_module():
    """Create a fake openai module with all OpenAI client classes."""
    mod = SimpleNamespace()
    mod.OpenAI = type("OpenAI", (), {})
    mod.AsyncOpenAI = type("AsyncOpenAI", (), {})
    mod.AzureOpenAI = type("AzureOpenAI", (), {})
    mod.AsyncAzureOpenAI = type("AsyncAzureOpenAI", (), {})
    return mod


def _make_mock_openai_client():
    """Build a mock object that looks like openai.OpenAI()."""
    mock_create = MagicMock(name="chat.completions.create")
    completions = SimpleNamespace(create=mock_create)
    chat = SimpleNamespace(completions=completions)
    client = SimpleNamespace(chat=chat, api_key="sk-test-key")
    return client, mock_create


def _make_openai_response(texts):
    """Build a mock OpenAI ChatCompletion response."""
    choices = []
    for t in texts:
        msg = SimpleNamespace(role="assistant", content=t)
        choices.append(SimpleNamespace(message=msg, index=len(choices)))
    return SimpleNamespace(choices=choices, model="gpt-4o")


# ============================================================================
# TestOpenAIExtractor
# ============================================================================


class TestOpenAIExtractor:
    """OpenAIExtractor detection and text extraction."""

    def test_detect_true_when_openai_imported(self):
        fake_mod = _fake_openai_module()
        client = fake_mod.OpenAI()
        with patch.dict(sys.modules, {"openai": fake_mod}):
            assert OpenAIExtractor.detect(client) is True

    def test_detect_true_for_async_client(self):
        fake_mod = _fake_openai_module()
        client = fake_mod.AsyncOpenAI()
        with patch.dict(sys.modules, {"openai": fake_mod}):
            assert OpenAIExtractor.detect(client) is True

    def test_detect_true_for_azure_client(self):
        fake_mod = _fake_openai_module()
        client = fake_mod.AzureOpenAI()
        with patch.dict(sys.modules, {"openai": fake_mod}):
            assert OpenAIExtractor.detect(client) is True

    def test_detect_true_for_async_azure_client(self):
        fake_mod = _fake_openai_module()
        client = fake_mod.AsyncAzureOpenAI()
        with patch.dict(sys.modules, {"openai": fake_mod}):
            assert OpenAIExtractor.detect(client) is True

    def test_detect_false_when_openai_not_imported(self):
        with patch.dict(sys.modules, {}, clear=False):
            sys.modules.pop("openai", None)
            assert OpenAIExtractor.detect(object()) is False

    def test_detect_false_for_non_openai_client(self):
        fake_mod = _fake_openai_module()
        with patch.dict(sys.modules, {"openai": fake_mod}):
            assert OpenAIExtractor.detect("not a client") is False

    def test_methods_to_wrap(self):
        ext = OpenAIExtractor()
        assert ext.methods_to_wrap() == ["chat.completions.create"]

    def test_extract_input_string_content(self):
        ext = OpenAIExtractor()
        kwargs = {
            "messages": [{"role": "user", "content": "hello world"}],
        }
        result = ext.extract_input("chat.completions.create", (), kwargs)
        assert result == ["hello world"]

    def test_extract_input_system_message(self):
        ext = OpenAIExtractor()
        kwargs = {
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hi"},
            ],
        }
        result = ext.extract_input("chat.completions.create", (), kwargs)
        assert result == ["You are helpful.", "hi"]

    def test_extract_input_content_blocks(self):
        ext = OpenAIExtractor()
        kwargs = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe this"},
                        {"type": "image_url", "image_url": {"url": "http://..."}},
                    ],
                }
            ],
        }
        result = ext.extract_input("chat.completions.create", (), kwargs)
        assert result == ["describe this"]

    def test_extract_input_empty_messages(self):
        ext = OpenAIExtractor()
        result = ext.extract_input("chat.completions.create", (), {"messages": []})
        assert result == []

    def test_extract_input_no_messages_key(self):
        ext = OpenAIExtractor()
        result = ext.extract_input("chat.completions.create", (), {})
        assert result == []

    def test_extract_output_single_choice(self):
        ext = OpenAIExtractor()
        response = _make_openai_response(["hello world"])
        result = ext.extract_output("chat.completions.create", response)
        assert result == ["hello world"]

    def test_extract_output_multiple_choices(self):
        ext = OpenAIExtractor()
        response = _make_openai_response(["answer one", "answer two"])
        result = ext.extract_output("chat.completions.create", response)
        assert result == ["answer one", "answer two"]

    def test_extract_output_no_content(self):
        ext = OpenAIExtractor()
        msg = SimpleNamespace(role="assistant", content=None)
        choice = SimpleNamespace(message=msg, index=0)
        response = SimpleNamespace(choices=[choice])
        result = ext.extract_output("chat.completions.create", response)
        assert result == []

    def test_extract_output_no_choices(self):
        ext = OpenAIExtractor()
        response = SimpleNamespace(choices=[])
        result = ext.extract_output("chat.completions.create", response)
        assert result == []

    def test_registered_in_registry(self):
        for name in OpenAIExtractor._CLIENT_NAMES:
            key = f"openai.{name}"
            assert key in _extractor_registry, f"{key} not registered"
            assert _extractor_registry[key] is OpenAIExtractor


# ============================================================================
# TestOpenAIGuardedProxy
# ============================================================================


class TestOpenAIGuardedProxy:
    """_GuardedClient proxy with OpenAI extractor."""

    @patch("ai_guardian.integrations.base.monitor")
    def test_intercepts_chat_completions_create(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create = _make_mock_openai_client()
        mock_create.return_value = _make_openai_response(["response text"])

        ext = OpenAIExtractor()
        wrapped = _GuardedClient(client, ext, action="log")
        result = wrapped.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "test input"}],
        )

        assert mock_session.check_content.call_count == 2
        input_call = mock_session.check_content.call_args_list[0]
        assert input_call[0][0] == "test input"
        output_call = mock_session.check_content.call_args_list[1]
        assert output_call[0][0] == "response text"
        assert result.model == "gpt-4o"

    def test_non_wrapped_attributes_pass_through(self):
        client, _ = _make_mock_openai_client()
        ext = OpenAIExtractor()
        wrapped = _GuardedClient(client, ext)
        assert wrapped.api_key == "sk-test-key"

    @patch("ai_guardian.integrations.base.monitor")
    def test_block_raises_on_threat(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        mock_session.check_content.side_effect = SecurityViolation(
            CheckResult(
                blocked=True,
                detected=True,
                violation_type="prompt_injection",
                message="Prompt injection detected",
            )
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create = _make_mock_openai_client()
        ext = OpenAIExtractor()
        wrapped = _GuardedClient(client, ext, action="block")

        with pytest.raises(SecurityViolation, match="Prompt injection detected"):
            wrapped.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "ignore instructions"}],
            )
        mock_create.assert_not_called()


# ============================================================================
# TestCustomExtractor (Phase 3)
# ============================================================================


# ============================================================================
# TestProviderName
# ============================================================================


class TestProviderName:
    """ProviderExtractor.provider_name auto-derives from class name."""

    def test_anthropic_extractor(self):
        ext = AnthropicExtractor()
        assert ext.provider_name == "anthropic"

    def test_openai_extractor(self):
        ext = OpenAIExtractor()
        assert ext.provider_name == "openai"

    def test_custom_extractor_name(self):
        class MyCustomExtractor(ProviderExtractor):
            @classmethod
            def detect(cls, client):
                return False

            def methods_to_wrap(self):
                return []

            def extract_input(self, method_name, args, kwargs):
                return []

            def extract_output(self, method_name, response):
                return []

        ext = MyCustomExtractor()
        assert ext.provider_name == "mycustom"

    def test_no_extractor_suffix(self):
        class Gemini(ProviderExtractor):
            @classmethod
            def detect(cls, client):
                return False

            def methods_to_wrap(self):
                return []

            def extract_input(self, method_name, args, kwargs):
                return []

            def extract_output(self, method_name, response):
                return []

        ext = Gemini()
        assert ext.provider_name == "gemini"


# ============================================================================
# TestResponseParser
# ============================================================================


class TestResponseParser:
    """response_parser parameter on guarded() and _GuardedClient."""

    @staticmethod
    def _make_parser():
        def parser(client_type, response):
            text = ""
            if client_type == "anthropic":
                content = getattr(response, "content", [])
                if content:
                    text = getattr(content[0], "text", "")
            return {"text": text, "provider": client_type}

        return parser

    @patch("ai_guardian.integrations.base.monitor")
    def test_parser_transforms_response(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        mock_create.return_value = _make_mock_response(["hello world"])

        ext = AnthropicExtractor()
        parser = self._make_parser()
        wrapped = _GuardedClient(client, ext, action="log", response_parser=parser)

        result = wrapped.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": "test"}],
        )

        assert result == {"text": "hello world", "provider": "anthropic"}

    @patch("ai_guardian.integrations.base.monitor")
    def test_no_parser_returns_native_response(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        original_response = _make_mock_response(["hello"])
        mock_create.return_value = original_response

        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="log")

        result = wrapped.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": "test"}],
        )

        assert result is original_response

    @patch("ai_guardian.integrations.base.monitor")
    def test_violation_sets_sanitized_parsed(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()

        def check_side_effect(text, filename="input"):
            if filename == "llm_output":
                raise SecurityViolation(
                    CheckResult(
                        blocked=True,
                        detected=True,
                        violation_type="secret",
                        message="Secret in response",
                    )
                )
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_session.sanitize.return_value = {"sanitized_text": "[REDACTED]"}
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        original_response = _make_mock_response(["leaked secret"])
        mock_create.return_value = original_response

        ext = AnthropicExtractor()
        parser = self._make_parser()
        wrapped = _GuardedClient(client, ext, action="block", response_parser=parser)

        with pytest.raises(SecurityViolation) as exc_info:
            wrapped.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                messages=[{"role": "user", "content": "safe input"}],
            )

        exc = exc_info.value
        assert exc.response is original_response
        assert exc.sanitized_text == "[REDACTED]"
        assert exc.sanitized_parsed == {
            "text": "leaked secret",
            "provider": "anthropic",
        }

    @patch("ai_guardian.integrations.base.monitor")
    def test_violation_no_parser_no_sanitized_parsed(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()

        def check_side_effect(text, filename="input"):
            if filename == "llm_output":
                raise SecurityViolation(
                    CheckResult(
                        blocked=True,
                        detected=True,
                        violation_type="secret",
                        message="Secret",
                    )
                )
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_session.sanitize.return_value = {"sanitized_text": "[REDACTED]"}
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        mock_create.return_value = _make_mock_response(["secret"])

        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="block")

        with pytest.raises(SecurityViolation) as exc_info:
            wrapped.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                messages=[{"role": "user", "content": "test"}],
            )

        exc = exc_info.value
        assert exc.sanitized_parsed is None

    @patch("ai_guardian.integrations.base.monitor")
    def test_parser_error_sets_sanitized_parsed_none(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()

        def check_side_effect(text, filename="input"):
            if filename == "llm_output":
                raise SecurityViolation(
                    CheckResult(
                        blocked=True,
                        detected=True,
                        violation_type="secret",
                        message="Secret",
                    )
                )
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_session.sanitize.return_value = {"sanitized_text": "[REDACTED]"}
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        def bad_parser(client_type, response):
            raise ValueError("parser broke")

        client, mock_create, _ = _make_mock_anthropic_client()
        mock_create.return_value = _make_mock_response(["secret"])

        ext = AnthropicExtractor()
        wrapped = _GuardedClient(
            client, ext, action="block", response_parser=bad_parser
        )

        with pytest.raises(SecurityViolation) as exc_info:
            wrapped.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                messages=[{"role": "user", "content": "test"}],
            )

        assert exc_info.value.sanitized_parsed is None

    def test_guarded_passes_response_parser(self):
        class CustomExt(ProviderExtractor):
            @classmethod
            def detect(cls, client):
                return False

            def methods_to_wrap(self):
                return []

            def extract_input(self, method_name, args, kwargs):
                return []

            def extract_output(self, method_name, response):
                return []

        parser = lambda ct, r: {"parsed": True}
        wrapped = guarded(object(), extractor=CustomExt(), response_parser=parser)
        assert wrapped._response_parser is parser

    def test_guarded_no_parser_default(self):
        class CustomExt(ProviderExtractor):
            @classmethod
            def detect(cls, client):
                return False

            def methods_to_wrap(self):
                return []

            def extract_input(self, method_name, args, kwargs):
                return []

            def extract_output(self, method_name, response):
                return []

        wrapped = guarded(object(), extractor=CustomExt())
        assert wrapped._response_parser is None

    def test_stream_violation_sets_sanitized_parsed(self):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        mock_session.check_content.side_effect = SecurityViolation(
            CheckResult(
                blocked=True,
                detected=True,
                violation_type="secret",
                message="Secret in stream",
            )
        )
        mock_session.sanitize.return_value = {"sanitized_text": "[REDACTED]"}
        ext = AnthropicExtractor()

        parser = self._make_parser()
        final_msg = _make_mock_response(["leaked secret"])
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.get_final_message = MagicMock(return_value=final_msg)

        proxy = _StreamProxy(
            mock_stream, ext, "messages.stream", mock_session, response_parser=parser
        )
        with pytest.raises(SecurityViolation) as exc_info:
            with proxy:
                pass

        exc = exc_info.value
        assert exc.sanitized_parsed == {
            "text": "leaked secret",
            "provider": "anthropic",
        }


class TestCustomExtractor:
    """Custom ProviderExtractor passed via extractor= param."""

    def _make_custom_extractor(self):
        class MyExtractor(ProviderExtractor):
            @classmethod
            def detect(cls, client):
                return False

            def methods_to_wrap(self):
                return ["generate"]

            def extract_input(self, method_name, args, kwargs):
                prompt = kwargs.get("prompt", "")
                return [prompt] if prompt else []

            def extract_output(self, method_name, response):
                text = getattr(response, "text", "")
                return [text] if text else []

        return MyExtractor()

    def test_custom_extractor_wraps_client(self):
        ext = self._make_custom_extractor()
        client = SimpleNamespace(generate=MagicMock(), name="my-llm")
        wrapped = guarded(client, extractor=ext, action="log")
        assert isinstance(wrapped, _GuardedClient)
        assert wrapped.name == "my-llm"

    @patch("ai_guardian.integrations.base.monitor")
    def test_custom_extractor_intercepts_method(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        ext = self._make_custom_extractor()
        mock_generate = MagicMock(return_value=SimpleNamespace(text="generated output"))
        client = SimpleNamespace(generate=mock_generate)
        wrapped = guarded(client, extractor=ext, action="log")

        result = wrapped.generate(prompt="hello")

        assert mock_session.check_content.call_count == 2
        assert mock_session.check_content.call_args_list[0][0][0] == "hello"
        assert mock_session.check_content.call_args_list[1][0][0] == "generated output"
        assert result.text == "generated output"

    @patch("ai_guardian.integrations.base.monitor")
    def test_custom_extractor_block_raises(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        mock_session.check_content.side_effect = SecurityViolation(
            CheckResult(
                blocked=True, detected=True, violation_type="secret", message="blocked"
            )
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        ext = self._make_custom_extractor()
        mock_generate = MagicMock()
        client = SimpleNamespace(generate=mock_generate)
        wrapped = guarded(client, extractor=ext, action="block")

        with pytest.raises(SecurityViolation):
            wrapped.generate(prompt="secret data")
        mock_generate.assert_not_called()


# ============================================================================
# TestToolResolution
# ============================================================================


class TestToolResolution:
    """Tool name → Anthropic tool dict resolution."""

    def test_preset_coding(self):
        from ai_guardian.integrations.anthropic.tools import resolve_tools

        tools = resolve_tools("coding")
        names = [t["name"] for t in tools]
        assert names == ["bash", "str_replace_based_edit_tool", "grep", "glob"]

    def test_preset_readonly(self):
        from ai_guardian.integrations.anthropic.tools import resolve_tools

        tools = resolve_tools("readonly")
        names = [t["name"] for t in tools]
        assert names == ["read_file", "grep", "glob"]

    def test_preset_browser(self):
        from ai_guardian.integrations.anthropic.tools import resolve_tools

        tools = resolve_tools("browser")
        names = [t["name"] for t in tools]
        assert names == ["computer", "bash"]
        computer = [t for t in tools if t["name"] == "computer"][0]
        assert "display_width_px" in computer

    def test_single_tool_name(self):
        from ai_guardian.integrations.anthropic.tools import resolve_tools

        tools = resolve_tools("bash")
        assert len(tools) == 1
        assert tools[0]["name"] == "bash"
        assert "bash_" in tools[0]["type"]

    def test_list_of_names(self):
        from ai_guardian.integrations.anthropic.tools import resolve_tools

        tools = resolve_tools(["bash", "grep"])
        assert len(tools) == 2
        assert tools[0]["name"] == "bash"
        assert tools[1]["name"] == "grep"
        assert "input_schema" in tools[1]

    def test_mixed_list_with_dict(self):
        from ai_guardian.integrations.anthropic.tools import resolve_tools

        custom = {"name": "my_tool", "input_schema": {"type": "object"}}
        tools = resolve_tools(["bash", custom])
        assert len(tools) == 2
        assert tools[1] == custom

    def test_preset_in_list(self):
        from ai_guardian.integrations.anthropic.tools import resolve_tools

        tools = resolve_tools(["coding", "web_search"])
        names = [t["name"] for t in tools]
        assert "bash" in names
        assert "web_search" in names

    def test_unknown_tool_raises(self):
        from ai_guardian.integrations.anthropic.tools import resolve_tools

        with pytest.raises(ValueError, match="Unknown tool"):
            resolve_tools("nonexistent_tool")

    def test_tool_type_override(self):
        from ai_guardian.integrations.anthropic.tools import resolve_tools

        tools = resolve_tools(["bash"], tool_types={"bash": "bash_99990101"})
        assert tools[0]["type"] == "bash_99990101"

    def test_server_tool_detection(self):
        from ai_guardian.integrations.anthropic.tools import is_server_tool

        assert is_server_tool("web_search")
        assert is_server_tool("web_fetch")
        assert is_server_tool("code_execution")
        assert not is_server_tool("bash")
        assert not is_server_tool("grep")

    def test_fallback_types_used_without_sdk(self):
        from ai_guardian.integrations.anthropic.tools import (
            _detected_cache,
            get_tool_type,
        )

        _detected_cache.clear()
        result = get_tool_type("bash")
        assert result == "bash_20250124"

    def test_auto_detect_from_sdk(self):
        from ai_guardian.integrations.anthropic.tools import (
            _detected_cache,
            _discover_tool_type,
        )

        _detected_cache.clear()
        fake_types = SimpleNamespace()
        fake_types.ToolBash20250124Param = True
        fake_types.ToolBash20990101Param = True
        fake_anthropic = SimpleNamespace(types=fake_types)

        with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
            result = _discover_tool_type("bash")
            assert result == "bash_20990101"

        _detected_cache.clear()


# ============================================================================
# TestToolValidation
# ============================================================================


class TestToolValidation:
    """Startup tool validation tests."""

    def test_known_tools_no_warnings(self, caplog):
        from ai_guardian.integrations.anthropic.tools import (
            resolve_tools,
            validate_tools,
        )

        tools = resolve_tools("coding")
        with caplog.at_level(logging.WARNING):
            validate_tools(tools, "test-model")
        assert not caplog.records

    def test_unknown_tool_warns(self, caplog):
        from ai_guardian.integrations.anthropic.tools import validate_tools

        tools = [{"name": "bah", "input_schema": {"type": "object"}}]
        with caplog.at_level(logging.WARNING):
            validate_tools(tools, "test-model")
        assert len(caplog.records) == 1
        assert "bah" in caplog.records[0].message
        assert "no registered executor" in caplog.records[0].message

    def test_server_tools_no_warning(self, caplog):
        from ai_guardian.integrations.anthropic.tools import (
            resolve_tools,
            validate_tools,
        )

        tools = resolve_tools(["web_search", "web_fetch", "code_execution"])
        with caplog.at_level(logging.WARNING):
            validate_tools(tools)
        assert not caplog.records

    def test_server_tool_type_prefix_no_warning(self, caplog):
        from ai_guardian.integrations.anthropic.tools import validate_tools

        tools = [{"name": "web_search", "type": "web_search_20260209"}]
        with caplog.at_level(logging.WARNING):
            validate_tools(tools)
        assert not caplog.records

    def test_sdk_version_mismatch_logs_info(self, caplog):
        from ai_guardian.integrations.anthropic.tools import (
            _detected_cache,
            validate_tools,
        )

        _detected_cache.clear()
        tools = [{"name": "bash", "type": "bash_20200101"}]
        fake_types = SimpleNamespace()
        fake_types.ToolBash20250124Param = True
        fake_anthropic = SimpleNamespace(types=fake_types)

        with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
            with caplog.at_level(logging.INFO):
                validate_tools(tools, "test-model")
        assert any(
            "bash_20200101" in r.message and "bash_20250124" in r.message
            for r in caplog.records
        )
        _detected_cache.clear()

    def test_empty_tool_warns(self, caplog):
        from ai_guardian.integrations.anthropic.tools import validate_tools

        with caplog.at_level(logging.WARNING):
            validate_tools([{}])
        assert len(caplog.records) == 1
        assert "no name or type" in caplog.records[0].message

    def test_custom_schema_tools_no_warning(self, caplog):
        from ai_guardian.integrations.anthropic.tools import (
            resolve_tools,
            validate_tools,
        )

        tools = resolve_tools(["grep", "glob", "read_file"])
        with caplog.at_level(logging.WARNING):
            validate_tools(tools)
        assert not caplog.records

    def test_prefix_includes_model(self, caplog):
        from ai_guardian.integrations.anthropic.tools import validate_tools

        tools = [{"name": "nope", "input_schema": {"type": "object"}}]
        with caplog.at_level(logging.WARNING):
            validate_tools(tools, "claude-sonnet-5")
        assert "GuardedAgent(claude-sonnet-5)" in caplog.records[0].message


# ============================================================================
# TestToolExecution
# ============================================================================


class TestToolExecution:
    """Client-side tool executor tests."""

    @pytest.mark.skipif(sys.platform == "win32", reason="bash not available on Windows")
    def test_execute_bash(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        result = execute_tool("bash", {"command": "echo hello"}, str(tmp_path))
        assert "hello" in result

    def test_execute_bash_restart(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        result = execute_tool("bash", {"restart": True}, str(tmp_path))
        assert "restarted" in result.lower()

    @pytest.mark.skipif(sys.platform == "win32", reason="bash not available on Windows")
    def test_execute_bash_timeout(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        with patch("ai_guardian.integrations.anthropic.tools._BASH_TIMEOUT", 0.01):
            result = execute_tool("bash", {"command": "sleep 10"}, str(tmp_path))
            assert "timed out" in result.lower()

    def test_execute_text_editor_view(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        result = execute_tool(
            "text_editor", {"command": "view", "path": "test.txt"}, str(tmp_path)
        )
        assert "line1" in result
        assert "line3" in result

    def test_execute_text_editor_create(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        result = execute_tool(
            "text_editor",
            {"command": "create", "path": "new.txt", "file_text": "content"},
            str(tmp_path),
        )
        assert "Created" in result
        assert (tmp_path / "new.txt").read_text() == "content"

    def test_execute_text_editor_str_replace(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = execute_tool(
            "text_editor",
            {
                "command": "str_replace",
                "path": "test.txt",
                "old_str": "world",
                "new_str": "earth",
            },
            str(tmp_path),
        )
        assert "Replaced" in result
        assert f.read_text() == "hello earth"

    def test_execute_text_editor_path_escape(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        result = execute_tool(
            "text_editor",
            {"command": "view", "path": "../../../etc/passwd"},
            str(tmp_path),
        )
        assert "Error" in result
        assert "escapes" in result

    @pytest.mark.skipif(sys.platform == "win32", reason="grep not available on Windows")
    def test_execute_grep(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        (tmp_path / "a.py").write_text("def hello():\n    pass\n")
        result = execute_tool(
            "grep", {"pattern": "def hello", "path": "."}, str(tmp_path)
        )
        assert "hello" in result

    def test_execute_glob(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.txt").write_text("")
        result = execute_tool("glob", {"pattern": "*.py"}, str(tmp_path))
        assert "a.py" in result
        assert "b.txt" not in result

    def test_execute_text_editor_path_prefix_collision(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        sibling = tmp_path.parent / (tmp_path.name + "bar")
        sibling.mkdir(exist_ok=True)
        secret = sibling / "secret.txt"
        secret.write_text("sensitive data")
        rel = os.path.relpath(str(secret), str(tmp_path))
        result = execute_tool(
            "text_editor", {"command": "view", "path": rel}, str(tmp_path)
        )
        assert "Error" in result
        assert "escapes" in result

    def test_execute_grep_path_escape(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        result = execute_tool(
            "grep", {"pattern": "secret", "path": "../../../etc"}, str(tmp_path)
        )
        assert "Error" in result
        assert "escapes" in result

    def test_execute_glob_path_escape(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        result = execute_tool(
            "glob", {"pattern": "*", "path": "../../../etc"}, str(tmp_path)
        )
        assert "Error" in result
        assert "escapes" in result

    def test_execute_read_file(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        (tmp_path / "hello.txt").write_text("line1\nline2\nline3\n")
        result = execute_tool("read_file", {"path": "hello.txt"}, str(tmp_path))
        assert "line1" in result
        assert "line3" in result

    def test_execute_read_file_offset_limit(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        (tmp_path / "nums.txt").write_text("a\nb\nc\nd\ne\n")
        result = execute_tool(
            "read_file", {"path": "nums.txt", "offset": 1, "limit": 2}, str(tmp_path)
        )
        assert "b" in result
        assert "c" in result
        assert "a" not in result
        assert "d" not in result

    def test_execute_read_file_path_escape(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        result = execute_tool(
            "read_file", {"path": "../../../etc/passwd"}, str(tmp_path)
        )
        assert "Error" in result
        assert "escapes" in result

    def test_execute_read_file_not_found(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        result = execute_tool("read_file", {"path": "nonexistent.txt"}, str(tmp_path))
        assert "Error" in result
        assert "does not exist" in result

    def test_execute_read_file_directory(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "a.txt").write_text("")
        result = execute_tool("read_file", {"path": "subdir"}, str(tmp_path))
        assert "a.txt" in result

    def test_unknown_tool(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        result = execute_tool("unknown_tool", {}, str(tmp_path))
        assert "Error" in result

    def test_unknown_tool_logs_warning(self, tmp_path, caplog):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        with caplog.at_level(logging.WARNING):
            execute_tool("hallucinated_tool", {}, str(tmp_path))
        assert any("hallucinated_tool" in r.message for r in caplog.records)

    def test_format_tool_result_is_error(self):
        from ai_guardian.integrations.anthropic.agent import AnthropicLoopStrategy

        strategy = AnthropicLoopStrategy.__new__(AnthropicLoopStrategy)
        result = strategy.format_tool_result(
            "id-1", "Error: no executor", is_error=True
        )
        assert result["is_error"] is True

    def test_format_tool_result_no_error_by_default(self):
        from ai_guardian.integrations.anthropic.agent import AnthropicLoopStrategy

        strategy = AnthropicLoopStrategy.__new__(AnthropicLoopStrategy)
        result = strategy.format_tool_result("id-1", "hello")
        assert "is_error" not in result


# ============================================================================
# TestGuardedAgent
# ============================================================================


def _make_agent_response(content_blocks, stop_reason="end_turn", usage=None):
    """Build a mock Anthropic response for agent tests."""
    usage = usage or SimpleNamespace(input_tokens=100, output_tokens=50)
    return SimpleNamespace(
        content=content_blocks,
        stop_reason=stop_reason,
        usage=usage,
    )


class TestGuardedAgent:
    """GuardedAgent tool-use loop tests."""

    def _make_agent(self, mock_client=None, **kwargs):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        if mock_client is None:
            mock_create = MagicMock()
            mock_messages = SimpleNamespace(create=mock_create)
            mock_client = SimpleNamespace(messages=mock_messages)

        defaults = {
            "model": "claude-sonnet-5",
            "tools": ["bash"],
            "client": mock_client,
            "action": "log",
        }
        defaults.update(kwargs)
        return GuardedAgent(**defaults), mock_client

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_single_turn_no_tools(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello!")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.return_value = response

        result = agent.run("Hi")

        assert result["output"] == "Hello!"
        assert result["stop_reason"] == "end_turn"
        assert mock_session.check_content.call_count >= 2
        filenames = [
            call.kwargs.get("filename", call.args[0] if len(call.args) > 1 else "")
            for call in mock_session.check_content.call_args_list
        ]
        content_args = [
            call.args[0] for call in mock_session.check_content.call_args_list
        ]
        assert "Hi" in content_args
        assert "Hello!" in content_args

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_tool_use_loop(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="tool_1",
                    input={"command": "echo test"},
                ),
            ],
            stop_reason="tool_use",
        )
        final_response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done!")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.side_effect = [tool_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="test output",
        ):
            result = agent.run("Run echo test")

        assert result["output"] == "Done!"
        assert client.messages.create.call_count == 2
        scanned = [call.args[0] for call in mock_session.check_content.call_args_list]
        assert "test output" in scanned

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_tool_result_scanning(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="tool_1",
                    input={"command": "cat secret.txt"},
                ),
            ],
            stop_reason="tool_use",
        )
        final_response = _make_agent_response(
            [SimpleNamespace(type="text", text="Found it")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.side_effect = [tool_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="sensitive-credential-value",
        ):
            result = agent.run("Read secret")

        scanned_filenames = [
            call.kwargs.get("filename", "")
            for call in mock_session.check_content.call_args_list
        ]
        assert any("tool_result" in f for f in scanned_filenames)

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_max_turns_limit(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="tool_1",
                    input={"command": "echo loop"},
                ),
            ],
            stop_reason="tool_use",
        )

        agent, client = self._make_agent(max_turns=3)
        client.messages.create.return_value = tool_response

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="output",
        ):
            result = agent.run("Loop forever")

        assert result["stop_reason"] == "max_turns"
        assert client.messages.create.call_count == 3

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_refusal_handling(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="I cannot do that.")],
            stop_reason="refusal",
        )

        agent, client = self._make_agent()
        client.messages.create.return_value = response

        result = agent.run("Do something bad")

        assert result["stop_reason"] == "refusal"
        assert "cannot" in result["output"]

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_structured_output(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="submit_result",
                    id="tool_1",
                    input={"findings": ["bug1", "bug2"]},
                ),
            ],
            stop_reason="tool_use",
        )

        schema = {
            "type": "object",
            "properties": {"findings": {"type": "array"}},
        }
        agent, client = self._make_agent(output_schema=schema)
        client.messages.create.return_value = tool_response

        result = agent.run("Find bugs")

        assert result["output"] == {"findings": ["bug1", "bug2"]}

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_structured_output_reprompts_on_text(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        text_response = _make_agent_response(
            [SimpleNamespace(type="text", text="Here are the results...")],
            stop_reason="end_turn",
        )
        tool_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="submit_result",
                    id="tool_1",
                    input={"findings": ["bug1"], "file_count": 1},
                ),
            ],
            stop_reason="tool_use",
        )

        schema = {
            "type": "object",
            "properties": {
                "findings": {"type": "array"},
                "file_count": {"type": "integer"},
            },
            "required": ["findings", "file_count"],
        }
        agent, client = self._make_agent(output_schema=schema)
        client.messages.create.side_effect = [text_response, tool_response]

        result = agent.run("Find bugs")

        assert result["output"] == {"findings": ["bug1"], "file_count": 1}
        assert client.messages.create.call_count == 2
        messages = result["messages"]
        reprompt_msg = messages[2]
        assert reprompt_msg["role"] == "user"
        assert "submit_result" in reprompt_msg["content"]

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_structured_output_max_turns_on_repeated_text(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        text_response = _make_agent_response(
            [SimpleNamespace(type="text", text="I'll just respond with text")],
            stop_reason="end_turn",
        )

        schema = {
            "type": "object",
            "properties": {"findings": {"type": "array"}},
        }
        agent, client = self._make_agent(output_schema=schema, max_turns=3)
        client.messages.create.return_value = text_response

        result = agent.run("Find bugs")

        assert result["stop_reason"] == "max_turns"
        assert client.messages.create.call_count == 3

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_system_prompt_scanned(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(system_prompt="You are a helpful agent.")
        client.messages.create.return_value = response

        agent.run("Hello")

        scanned = [call.args[0] for call in mock_session.check_content.call_args_list]
        assert "You are a helpful agent." in scanned

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_server_tools_not_executed_locally(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="web_search",
                    id="tool_1",
                    input={"query": "test"},
                ),
            ],
            stop_reason="tool_use",
        )
        final_response = _make_agent_response(
            [SimpleNamespace(type="text", text="Found it")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(tools=["bash", "web_search"])
        client.messages.create.side_effect = [tool_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool"
        ) as mock_exec:
            result = agent.run("Search for test")
            mock_exec.assert_not_called()
            assert result["stop_reason"] == "end_turn"
            assert result["output"] == "Found it"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_scan_disabled(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(scan_input=False, scan_output=False)
        client.messages.create.return_value = response

        agent.run("Hi")

        mock_session.check_content.assert_not_called()

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_output_violation_attaches_response(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()

        def check_side_effect(text, filename="input"):
            if filename == "agent_response":
                raise SecurityViolation(
                    CheckResult(
                        blocked=True,
                        detected=True,
                        violation_type="secret",
                        message="Secret in assistant response",
                    )
                )
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_session.sanitize.return_value = {"sanitized_text": "[REDACTED]"}
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="leaked secret")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(action="block")
        client.messages.create.return_value = response

        with pytest.raises(SecurityViolation) as exc_info:
            agent.run("Hi")

        exc = exc_info.value
        assert exc.response is response
        assert exc.sanitized_text == "[REDACTED]"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_usage_accumulation(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo hi"},
                ),
            ],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )
        r2 = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=200, output_tokens=30),
        )

        agent, client = self._make_agent()
        client.messages.create.side_effect = [r1, r2]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="hi",
        ):
            result = agent.run("Test")

        assert result["usage"]["input_tokens"] == 300
        assert result["usage"]["output_tokens"] == 80

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_budget_exceeded_stops_loop(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo hi"},
                ),
            ],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=300, output_tokens=200),
        )
        r2 = _make_agent_response(
            [SimpleNamespace(type="text", text="Still going")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=300, output_tokens=200),
        )

        agent, client = self._make_agent(max_budget_tokens=500)
        client.messages.create.side_effect = [r1, r2]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="hi",
        ):
            result = agent.run("Test budget")

        assert result["stop_reason"] == "budget_exceeded"
        assert result["usage"]["input_tokens"] == 300
        assert result["usage"]["output_tokens"] == 200
        assert client.messages.create.call_count == 1

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_budget_negative_one_no_limit(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo hi"},
                ),
            ],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=500000, output_tokens=500000),
        )
        r2 = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=500000, output_tokens=500000),
        )

        agent, client = self._make_agent(max_budget_tokens=-1, auto_compact=False)
        client.messages.create.side_effect = [r1, r2]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="hi",
        ):
            result = agent.run("Test no limit")

        assert result["stop_reason"] == "end_turn"
        assert client.messages.create.call_count == 2

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_budget_exceeded_preserves_last_text(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Partial answer")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=600, output_tokens=400),
        )

        agent, client = self._make_agent(max_budget_tokens=500)
        client.messages.create.return_value = response

        result = agent.run("Test budget text")

        assert result["stop_reason"] == "budget_exceeded"
        assert result["output"] == "Partial answer"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_budget_exact_boundary(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Exact boundary")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=300, output_tokens=200),
        )

        agent, client = self._make_agent(max_budget_tokens=500)
        client.messages.create.return_value = response

        result = agent.run("Test exact")

        assert result["stop_reason"] == "budget_exceeded"
        assert result["usage"]["input_tokens"] == 300
        assert result["usage"]["output_tokens"] == 200

    def test_auto_client_creation(self):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        with patch(
            "ai_guardian.integrations.anthropic._extractor.create_client"
        ) as mock_create:
            mock_create.return_value = SimpleNamespace(
                messages=SimpleNamespace(create=MagicMock())
            )
            agent = GuardedAgent(tools=["bash"])
            mock_create.assert_called_once()

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_pause_turn_continues(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        pause_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo hi"},
                ),
            ],
            stop_reason="pause_turn",
        )
        final_response = _make_agent_response(
            [SimpleNamespace(type="text", text="All done")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.side_effect = [pause_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="hi",
        ):
            result = agent.run("Test pause")

        assert result["stop_reason"] == "end_turn"
        assert client.messages.create.call_count == 2

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_before_call_hook(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello!")],
            stop_reason="end_turn",
        )

        calls = []

        def on_call(method_name, args, kwargs):
            calls.append({"method": method_name, "model": kwargs.get("model")})

        agent, client = self._make_agent(before_call=on_call)
        client.messages.create.return_value = response

        agent.run("Hi")

        assert len(calls) == 1
        assert calls[0]["method"] == "messages.create"
        assert calls[0]["model"] == "claude-sonnet-5"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_after_call_hook(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello!")],
            stop_reason="end_turn",
        )

        responses = []

        def on_response(method_name, resp):
            responses.append(
                {"method": method_name, "tokens": resp.usage.output_tokens}
            )

        agent, client = self._make_agent(after_call=on_response)
        client.messages.create.return_value = response

        agent.run("Hi")

        assert len(responses) == 1
        assert responses[0]["method"] == "messages.create"
        assert responses[0]["tokens"] == 50

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_after_call_false_stops_loop(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo hi"},
                ),
            ],
            stop_reason="tool_use",
        )

        def stop_after_first(method_name, response):
            return False

        agent, client = self._make_agent(after_call=stop_after_first, max_turns=10)
        client.messages.create.return_value = r1

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="hi",
        ):
            result = agent.run("Test early stop")

        assert result["stop_reason"] == "hook_early_stop"
        assert client.messages.create.call_count == 1

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_after_call_none_continues(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo hi"},
                ),
            ],
            stop_reason="tool_use",
        )
        r2 = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        def noop(method_name, response):
            return None

        agent, client = self._make_agent(after_call=noop)
        client.messages.create.side_effect = [r1, r2]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="hi",
        ):
            result = agent.run("Test continue")

        assert result["stop_reason"] == "end_turn"
        assert client.messages.create.call_count == 2

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_pre_run_hook(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        pre_run_calls = []

        def on_start(prompt, config):
            pre_run_calls.append({"prompt": prompt, "config": config})

        agent, client = self._make_agent(pre_run=on_start, max_turns=5)
        client.messages.create.return_value = response

        agent.run("Hello agent")

        assert len(pre_run_calls) == 1
        assert pre_run_calls[0]["prompt"] == "Hello agent"
        cfg = pre_run_calls[0]["config"]
        assert cfg["model"] == "claude-sonnet-5"
        assert cfg["max_turns"] == 5
        assert cfg["max_budget_tokens"] == -1
        assert "tools" in cfg
        assert "system_prompt" in cfg

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_post_run_hook(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done!")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )

        post_run_calls = []

        def on_end(result):
            post_run_calls.append(result)

        agent, client = self._make_agent(post_run=on_end)
        client.messages.create.return_value = response

        agent.run("Hi")

        assert len(post_run_calls) == 1
        r = post_run_calls[0]
        assert r["stop_reason"] == "end_turn"
        assert r["output"] == "Done!"
        assert r["usage"]["input_tokens"] == 100

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_post_run_called_on_exception(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        mock_session.check_content.side_effect = SecurityViolation(
            CheckResult(
                blocked=True,
                detected=True,
                violation_type="secret",
                message="Secret in prompt",
            )
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        post_run_calls = []

        def on_end(result):
            post_run_calls.append(result)

        agent, client = self._make_agent(post_run=on_end, action="block")

        with pytest.raises(SecurityViolation):
            agent.run("secret data")

        assert len(post_run_calls) == 1
        assert post_run_calls[0] is None

    # -- between_turns hook --

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_none_continues(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello!")],
            stop_reason="end_turn",
        )

        hook = MagicMock(return_value=None)
        agent, client = self._make_agent(between_turns=hook)
        client.messages.create.return_value = response

        result = agent.run("Hi")

        assert result["stop_reason"] == "end_turn"
        assert result["output"] == "Hello!"
        hook.assert_called_once()

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_string_injects_message(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_agent_response(
            [SimpleNamespace(type="text", text="Here is the test code")],
            stop_reason="end_turn",
        )
        r2 = _make_agent_response(
            [SimpleNamespace(type="text", text="Revised test code")],
            stop_reason="end_turn",
        )

        hook = MagicMock(side_effect=["pytest output: 1 failed", None])
        agent, client = self._make_agent(between_turns=hook)
        client.messages.create.side_effect = [r1, r2]

        result = agent.run("Write a test")

        assert result["stop_reason"] == "end_turn"
        assert result["output"] == "Revised test code"
        assert client.messages.create.call_count == 2
        assert hook.call_count == 2
        msgs = result["messages"]
        injected = [m for m in msgs if m.get("content") == "pytest output: 1 failed"]
        assert len(injected) == 1
        assert injected[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[-1] is injected[0]

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_false_stops(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        hook = MagicMock(return_value=False)
        agent, client = self._make_agent(between_turns=hook)
        client.messages.create.return_value = response

        result = agent.run("Do work")

        assert result["stop_reason"] == "hook_early_stop"
        assert client.messages.create.call_count == 1

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_receives_correct_args(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hi")],
            stop_reason="end_turn",
        )

        hook = MagicMock(return_value=None)
        agent, client = self._make_agent(between_turns=hook)
        client.messages.create.return_value = response

        agent.run("Prompt")

        args = hook.call_args[0]
        assert isinstance(args[0], list)
        assert args[0][0] == {"role": "user", "content": "Prompt"}
        assert args[1] is response
        assert args[2] == 0

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_scanned_when_scan_input(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_agent_response(
            [SimpleNamespace(type="text", text="Code")],
            stop_reason="end_turn",
        )
        r2 = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        hook = MagicMock(side_effect=["injected text", None])
        agent, client = self._make_agent(between_turns=hook, scan_input=True)
        client.messages.create.side_effect = [r1, r2]

        agent.run("Go")

        scan_calls = mock_session.check_content.call_args_list
        injected_calls = [
            c
            for c in scan_calls
            if c.kwargs.get("filename") == "between_turns_injection"
        ]
        assert len(injected_calls) == 1
        assert injected_calls[0].args[0] == "injected text"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_not_scanned_when_no_scan_input(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_agent_response(
            [SimpleNamespace(type="text", text="Code")],
            stop_reason="end_turn",
        )
        r2 = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        hook = MagicMock(side_effect=["injected", None])
        agent, client = self._make_agent(
            between_turns=hook, scan_input=False, scan_output=False
        )
        client.messages.create.side_effect = [r1, r2]

        agent.run("Go")

        scan_calls = mock_session.check_content.call_args_list
        injected_calls = [
            c
            for c in scan_calls
            if c.kwargs.get("filename") == "between_turns_injection"
        ]
        assert len(injected_calls) == 0

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_security_violation(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        from ai_guardian.sdk import CheckResult

        mock_session.check_content.side_effect = [
            None,
            None,
            SecurityViolation(
                CheckResult(
                    blocked=True,
                    detected=True,
                    violation_type="secret",
                    message="Secret in injected content",
                )
            ),
        ]

        r1 = _make_agent_response(
            [SimpleNamespace(type="text", text="Code")],
            stop_reason="end_turn",
        )

        hook = MagicMock(return_value="AKIA secret here")
        agent, client = self._make_agent(
            between_turns=hook, scan_input=True, scan_output=False, action="block"
        )
        client.messages.create.return_value = r1

        with pytest.raises(SecurityViolation):
            agent.run("Generate code")

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_false_stops_tool_use(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo hi"},
                ),
            ],
            stop_reason="tool_use",
        )

        hook = MagicMock(return_value=False)
        agent, client = self._make_agent(between_turns=hook)
        client.messages.create.return_value = response

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="hi",
        ):
            result = agent.run("Do work")

        assert result["stop_reason"] == "hook_early_stop"
        assert client.messages.create.call_count == 1
        assert any(m["role"] == "assistant" for m in result["messages"])

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_tool_use_merges(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo hi"},
                ),
            ],
            stop_reason="tool_use",
        )
        r2 = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        hook = MagicMock(side_effect=["extra context", None])
        agent, client = self._make_agent(between_turns=hook)
        client.messages.create.side_effect = [r1, r2]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="hi",
        ):
            result = agent.run("Test tool use")

        assert result["stop_reason"] == "end_turn"
        assert hook.call_count == 2
        user_msg_after_tool = result["messages"][2]
        assert user_msg_after_tool["role"] == "user"
        assert isinstance(user_msg_after_tool["content"], list)
        text_blocks = [
            b for b in user_msg_after_tool["content"] if b.get("type") == "text"
        ]
        assert len(text_blocks) == 1
        assert text_blocks[0]["text"] == "extra context"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_multi_turn(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_agent_response(
            [SimpleNamespace(type="text", text="Attempt 1")],
            stop_reason="end_turn",
        )
        r2 = _make_agent_response(
            [SimpleNamespace(type="text", text="Attempt 2")],
            stop_reason="end_turn",
        )
        r3 = _make_agent_response(
            [SimpleNamespace(type="text", text="Final")],
            stop_reason="end_turn",
        )

        hook = MagicMock(side_effect=["feedback 1", "feedback 2", None])
        agent, client = self._make_agent(between_turns=hook)
        client.messages.create.side_effect = [r1, r2, r3]

        result = agent.run("Start")

        assert result["stop_reason"] == "end_turn"
        assert result["output"] == "Final"
        assert client.messages.create.call_count == 3
        assert hook.call_count == 3

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_not_set(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello!")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.return_value = response

        result = agent.run("Hi")

        assert result["stop_reason"] == "end_turn"
        assert result["output"] == "Hello!"

    # -- between_turns + output_schema interaction (#1870) --

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_fires_with_output_schema(self, mock_monitor):
        """between_turns must fire even when submit_result is called."""
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="submit_result",
                    id="t1",
                    input={"test_code": "assert True"},
                ),
            ],
            stop_reason="tool_use",
        )

        schema = {
            "type": "object",
            "properties": {"test_code": {"type": "string"}},
        }
        hook = MagicMock(return_value=None)
        agent, client = self._make_agent(output_schema=schema, between_turns=hook)
        client.messages.create.return_value = response

        result = agent.run("generate test code")

        hook.assert_called_once()
        assert result["output"] == {"test_code": "assert True"}
        assert result["stop_reason"] == "end_turn"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_string_continues_after_submit_result(self, mock_monitor):
        """Returning a string from between_turns rejects submit_result and continues."""
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="submit_result",
                    id="t1",
                    input={"test_code": "pass"},
                ),
            ],
            stop_reason="tool_use",
        )
        r2 = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="submit_result",
                    id="t2",
                    input={"test_code": "assert 1 + 1 == 2"},
                ),
            ],
            stop_reason="tool_use",
        )

        schema = {
            "type": "object",
            "properties": {"test_code": {"type": "string"}},
        }
        hook = MagicMock(side_effect=["Tests failed, try again", None])
        agent, client = self._make_agent(output_schema=schema, between_turns=hook)
        client.messages.create.side_effect = [r1, r2]

        result = agent.run("generate test code")

        assert hook.call_count == 2
        assert result["output"] == {"test_code": "assert 1 + 1 == 2"}
        assert result["stop_reason"] == "end_turn"
        assert client.messages.create.call_count == 2

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_false_stops_with_output_schema(self, mock_monitor):
        """Returning False from between_turns stops even with submit_result."""
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="submit_result",
                    id="t1",
                    input={"test_code": "assert True"},
                ),
            ],
            stop_reason="tool_use",
        )

        schema = {
            "type": "object",
            "properties": {"test_code": {"type": "string"}},
        }
        hook = MagicMock(return_value=False)
        agent, client = self._make_agent(output_schema=schema, between_turns=hook)
        client.messages.create.return_value = response

        result = agent.run("generate test code")

        hook.assert_called_once()
        assert result["stop_reason"] == "hook_early_stop"


# ============================================================================
# TestGuardedClientHooks
# ============================================================================


class TestGuardedClientHooks:
    """before_call/after_call hooks on _GuardedClient (guarded())."""

    @patch("ai_guardian.integrations.base.monitor")
    def test_before_call_invoked(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        mock_create.return_value = _make_mock_response(["response"])

        calls = []

        def on_call(method_name, args, kwargs):
            calls.append(method_name)

        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="log", before_call=on_call)

        wrapped.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": "test"}],
        )

        assert calls == ["messages.create"]

    @patch("ai_guardian.integrations.base.monitor")
    def test_after_call_invoked(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()
        original_response = _make_mock_response(["response"])
        mock_create.return_value = original_response

        responses = []

        def on_response(method_name, resp):
            responses.append((method_name, resp))

        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="log", after_call=on_response)

        wrapped.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": "test"}],
        )

        assert len(responses) == 1
        assert responses[0][0] == "messages.create"
        assert responses[0][1] is original_response

    @patch("ai_guardian.integrations.base.monitor")
    def test_after_call_not_called_on_input_violation(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        mock_session.check_content.side_effect = SecurityViolation(
            CheckResult(
                blocked=True,
                detected=True,
                violation_type="secret",
                message="Secret",
            )
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        client, mock_create, _ = _make_mock_anthropic_client()

        after_calls = []

        def on_response(method_name, resp):
            after_calls.append(True)

        ext = AnthropicExtractor()
        wrapped = _GuardedClient(client, ext, action="block", after_call=on_response)

        with pytest.raises(SecurityViolation):
            wrapped.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                messages=[{"role": "user", "content": "secret"}],
            )

        assert after_calls == []

    def test_guarded_passes_hooks(self):
        class CustomExt(ProviderExtractor):
            @classmethod
            def detect(cls, client):
                return False

            def methods_to_wrap(self):
                return []

            def extract_input(self, method_name, args, kwargs):
                return []

            def extract_output(self, method_name, response):
                return []

        bc = lambda mn, a, k: None
        ac = lambda mn, r: None
        wrapped = guarded(
            object(), extractor=CustomExt(), before_call=bc, after_call=ac
        )
        assert wrapped._before_call is bc
        assert wrapped._after_call is ac

    def test_guarded_hooks_default_none(self):
        class CustomExt(ProviderExtractor):
            @classmethod
            def detect(cls, client):
                return False

            def methods_to_wrap(self):
                return []

            def extract_input(self, method_name, args, kwargs):
                return []

            def extract_output(self, method_name, response):
                return []

        wrapped = guarded(object(), extractor=CustomExt())
        assert wrapped._before_call is None
        assert wrapped._after_call is None


# ============================================================================
# TestGuardedAgentCompaction
# ============================================================================


class TestGuardedAgentCompaction:
    """Auto-compaction tests for GuardedAgent."""

    def _make_agent(self, mock_client=None, **kwargs):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        if mock_client is None:
            mock_create = MagicMock()
            mock_messages = SimpleNamespace(create=mock_create)
            mock_client = SimpleNamespace(messages=mock_messages)

        defaults = {
            "model": "claude-sonnet-5",
            "tools": ["bash"],
            "client": mock_client,
            "action": "log",
        }
        defaults.update(kwargs)
        return GuardedAgent(**defaults), mock_client

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_auto_compact_disabled(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=190_000, output_tokens=50),
        )
        agent, client = self._make_agent(auto_compact=False)
        client.messages.create.return_value = response

        result = agent.run("Hi")
        assert result["compaction_count"] == 0

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_context_exhausted_raises_without_compaction(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_resp = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo hi"},
                ),
            ],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=200_000, output_tokens=100),
        )
        agent, client = self._make_agent()
        client.messages.create.return_value = tool_resp

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="output",
        ):
            with pytest.raises(RuntimeError, match="compact_threshold"):
                agent.run("Fill context")

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_auto_compact_triggers_on_high_input_tokens(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        big_tool_output = "\n".join(["x" * 200] * 5000)

        def _tool_resp(tid, input_toks):
            return _make_agent_response(
                [
                    SimpleNamespace(
                        type="tool_use",
                        name="bash",
                        id=tid,
                        input={"command": "cat big.log"},
                    ),
                ],
                stop_reason="tool_use",
                usage=SimpleNamespace(input_tokens=input_toks, output_tokens=100),
            )

        final_response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=50_000, output_tokens=50),
        )
        agent, client = self._make_agent(compact_threshold=0.8, compact_keep_turns=1)
        client.messages.create.side_effect = [
            _tool_resp("t1", 130_000),
            _tool_resp("t2", 180_000),
            final_response,
        ]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value=big_tool_output,
        ):
            result = agent.run("Analyze big.log")

        assert result["compaction_count"] >= 1

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_compaction_count_in_result(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hi")],
            stop_reason="end_turn",
        )
        agent, client = self._make_agent()
        client.messages.create.return_value = response

        result = agent.run("Hello")
        assert "compaction_count" in result
        assert result["compaction_count"] == 0

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_loop_continues_after_compaction(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_resp1 = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo 1"},
                ),
            ],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=170_000, output_tokens=100),
        )
        tool_resp2 = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t2",
                    input={"command": "echo 2"},
                ),
            ],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=50_000, output_tokens=100),
        )
        final_resp = _make_agent_response(
            [SimpleNamespace(type="text", text="All done")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=30_000, output_tokens=50),
        )
        agent, client = self._make_agent(compact_threshold=0.8, compact_keep_turns=1)
        client.messages.create.side_effect = [tool_resp1, tool_resp2, final_resp]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="x" * 100_000,
        ):
            result = agent.run("Run two commands")

        assert result["output"] == "All done"
        assert result["stop_reason"] == "end_turn"
        assert client.messages.create.call_count == 3

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_no_compaction_below_threshold(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo hi"},
                ),
            ],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=10_000, output_tokens=50),
        )
        final_response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10_500, output_tokens=50),
        )
        agent, client = self._make_agent()
        client.messages.create.side_effect = [tool_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="small output",
        ):
            result = agent.run("Quick task")

        assert result["compaction_count"] == 0


# ============================================================================
# TestOpenAIGuardedAgent
# ============================================================================


def _make_openai_agent_response(
    content=None,
    tool_calls=None,
    finish_reason="stop",
    usage=None,
):
    """Build a mock OpenAI ChatCompletion response."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    if usage is None:
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50)
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_openai_tool_call(tool_id, name, arguments):
    """Build a mock OpenAI tool_call object."""
    import json

    return SimpleNamespace(
        id=tool_id,
        type="function",
        function=SimpleNamespace(
            name=name,
            arguments=(
                json.dumps(arguments) if isinstance(arguments, dict) else arguments
            ),
        ),
    )


class TestOpenAIGuardedAgent:
    """GuardedAgent tests with OpenAI loop strategy."""

    def _make_agent(self, mock_client=None, **kwargs):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        strategy = OpenAILoopStrategy()
        if mock_client is None:
            mock_create = MagicMock()
            mock_completions = SimpleNamespace(create=mock_create)
            mock_chat = SimpleNamespace(completions=mock_completions)
            mock_client = SimpleNamespace(chat=mock_chat)

        defaults = {
            "model": "gpt-4o",
            "tools": ["bash"],
            "client": mock_client,
            "action": "log",
            "strategy": strategy,
        }
        defaults.update(kwargs)
        return GuardedAgent(**defaults), mock_client

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_single_turn_no_tools(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_openai_agent_response(content="Hello!")

        agent, client = self._make_agent()
        client.chat.completions.create.return_value = response

        result = agent.run("Hi")

        assert result["output"] == "Hello!"
        assert result["stop_reason"] == "end_turn"
        content_args = [
            call.args[0] for call in mock_session.check_content.call_args_list
        ]
        assert "Hi" in content_args
        assert "Hello!" in content_args

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_tool_use_loop(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_openai_agent_response(
            content=None,
            tool_calls=[
                _make_openai_tool_call("call_1", "bash", {"command": "echo test"}),
            ],
            finish_reason="tool_calls",
        )
        final_response = _make_openai_agent_response(content="Done!")

        agent, client = self._make_agent()
        client.chat.completions.create.side_effect = [tool_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="test output",
        ):
            result = agent.run("Run echo test")

        assert result["output"] == "Done!"
        assert client.chat.completions.create.call_count == 2
        scanned = [call.args[0] for call in mock_session.check_content.call_args_list]
        assert "test output" in scanned

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_tool_result_format(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(
            blocked=False, detected=False
        )
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_openai_agent_response(
            content=None,
            tool_calls=[
                _make_openai_tool_call("call_1", "bash", {"command": "echo hi"}),
            ],
            finish_reason="tool_calls",
        )
        final_response = _make_openai_agent_response(content="Done")

        agent, client = self._make_agent()
        client.chat.completions.create.side_effect = [tool_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="hi",
        ):
            result = agent.run("Test")

        msgs = result["messages"]
        tool_result_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert len(tool_result_msgs) == 1
        assert tool_result_msgs[0]["tool_call_id"] == "call_1"
        assert tool_result_msgs[0]["content"] == "hi"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_max_turns_limit(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_openai_agent_response(
            content=None,
            tool_calls=[
                _make_openai_tool_call("call_1", "bash", {"command": "echo loop"}),
            ],
            finish_reason="tool_calls",
        )

        agent, client = self._make_agent(max_turns=3)
        client.chat.completions.create.return_value = tool_response

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="output",
        ):
            result = agent.run("Loop forever")

        assert result["stop_reason"] == "max_turns"
        assert client.chat.completions.create.call_count == 3

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_structured_output(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_openai_agent_response(
            content=None,
            tool_calls=[
                _make_openai_tool_call(
                    "call_1", "submit_result", {"findings": ["bug1", "bug2"]}
                ),
            ],
            finish_reason="tool_calls",
        )

        schema = {
            "type": "object",
            "properties": {"findings": {"type": "array"}},
        }
        agent, client = self._make_agent(output_schema=schema)
        client.chat.completions.create.return_value = tool_response

        result = agent.run("Find bugs")

        assert result["output"] == {"findings": ["bug1", "bug2"]}

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_system_prompt_as_message(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_openai_agent_response(content="OK")

        agent, client = self._make_agent(system_prompt="You are helpful.")
        client.chat.completions.create.return_value = response

        agent.run("Hello")

        call_kwargs = client.chat.completions.create.call_args[1]
        msgs = call_kwargs["messages"]
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are helpful."
        assert msgs[1]["role"] == "user"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_no_server_tools(self, mock_monitor):
        """OpenAI strategy has no server-side tools."""
        strategy = OpenAILoopStrategy()
        assert strategy.is_server_tool("web_search") is False
        assert strategy.is_server_tool("bash") is False

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_scan_disabled(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_openai_agent_response(content="Hello")

        agent, client = self._make_agent(scan_input=False, scan_output=False)
        client.chat.completions.create.return_value = response

        agent.run("Hi")

        mock_session.check_content.assert_not_called()

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_usage_accumulation(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_openai_agent_response(
            content=None,
            tool_calls=[
                _make_openai_tool_call("c1", "bash", {"command": "echo hi"}),
            ],
            finish_reason="tool_calls",
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        )
        r2 = _make_openai_agent_response(
            content="Done",
            usage=SimpleNamespace(prompt_tokens=200, completion_tokens=30),
        )

        agent, client = self._make_agent()
        client.chat.completions.create.side_effect = [r1, r2]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="hi",
        ):
            result = agent.run("Test")

        assert result["usage"]["input_tokens"] == 300
        assert result["usage"]["output_tokens"] == 80

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_budget_exceeded(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_openai_agent_response(
            content="Partial",
            usage=SimpleNamespace(prompt_tokens=600, completion_tokens=400),
        )

        agent, client = self._make_agent(max_budget_tokens=500)
        client.chat.completions.create.return_value = response

        result = agent.run("Test budget")

        assert result["stop_reason"] == "budget_exceeded"
        assert result["output"] == "Partial"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_before_call_hook(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_openai_agent_response(content="Hello!")

        calls = []

        def on_call(method_name, args, kwargs):
            calls.append({"method": method_name, "model": kwargs.get("model")})

        agent, client = self._make_agent(before_call=on_call)
        client.chat.completions.create.return_value = response

        agent.run("Hi")

        assert len(calls) == 1
        assert calls[0]["method"] == "chat.completions.create"
        assert calls[0]["model"] == "gpt-4o"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_string_injects(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_openai_agent_response(content="Code here")
        r2 = _make_openai_agent_response(content="Revised code")

        hook = MagicMock(side_effect=["test output: 1 failed", None])
        agent, client = self._make_agent(between_turns=hook)
        client.chat.completions.create.side_effect = [r1, r2]

        result = agent.run("Write a test")

        assert result["stop_reason"] == "end_turn"
        assert result["output"] == "Revised code"
        assert client.chat.completions.create.call_count == 2
        msgs = result["messages"]
        injected = [m for m in msgs if m.get("content") == "test output: 1 failed"]
        assert len(injected) == 1
        assert injected[0]["role"] == "user"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_false_stops(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_openai_agent_response(content="Done")

        hook = MagicMock(return_value=False)
        agent, client = self._make_agent(between_turns=hook)
        client.chat.completions.create.return_value = response

        result = agent.run("Do work")

        assert result["stop_reason"] == "hook_early_stop"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_between_turns_fires_with_output_schema(self, mock_monitor):
        """between_turns fires when submit_result is called (#1870)."""
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_openai_agent_response(
            content=None,
            tool_calls=[
                _make_openai_tool_call(
                    "call_1",
                    "submit_result",
                    {"test_code": "assert True"},
                ),
            ],
            finish_reason="tool_calls",
        )

        schema = {
            "type": "object",
            "properties": {"test_code": {"type": "string"}},
        }
        hook = MagicMock(return_value=None)
        agent, client = self._make_agent(output_schema=schema, between_turns=hook)
        client.chat.completions.create.return_value = response

        result = agent.run("generate test code")

        hook.assert_called_once()
        assert result["output"] == {"test_code": "assert True"}
        assert result["stop_reason"] == "end_turn"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_output_violation_attaches_response(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()

        def check_side_effect(text, filename="input"):
            if filename == "agent_response":
                raise SecurityViolation(
                    CheckResult(
                        blocked=True,
                        detected=True,
                        violation_type="secret",
                        message="Secret in response",
                    )
                )
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_session.sanitize.return_value = {"sanitized_text": "[REDACTED]"}
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_openai_agent_response(content="leaked secret")

        agent, client = self._make_agent(action="block")
        client.chat.completions.create.return_value = response

        with pytest.raises(SecurityViolation) as exc_info:
            agent.run("Hi")

        exc = exc_info.value
        assert exc.response is response
        assert exc.sanitized_text == "[REDACTED]"


# ============================================================================
# TestStrategyDetection
# ============================================================================


class TestStrategyDetection:
    """Tests for auto-detection of loop strategies."""

    def test_detect_anthropic_strategy(self):
        mock_mod = SimpleNamespace(Anthropic=type("Anthropic", (), {}))
        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            client = mock_mod.Anthropic()
            strategy = _strategy_registry.detect(client)
            assert isinstance(strategy, AnthropicLoopStrategy)

    def test_detect_openai_strategy(self):
        mock_mod = SimpleNamespace(OpenAI=type("OpenAI", (), {}))
        with patch.dict(sys.modules, {"openai": mock_mod}):
            client = mock_mod.OpenAI()
            strategy = _strategy_registry.detect(client)
            assert isinstance(strategy, OpenAILoopStrategy)

    def test_unknown_client_raises(self):
        with pytest.raises(ValueError, match="No loop strategy found"):
            _strategy_registry.detect(object())


# ============================================================================
# TestAgentLoopStrategyBase
# ============================================================================


class TestAgentLoopStrategyBase:
    """Tests for AgentLoopStrategy base class."""

    def test_inject_preamble_raises_not_implemented(self):
        class _MinimalStrategy(AgentLoopStrategy):
            api_method_name = "test"

            def create_default_client(self):
                pass

            def resolve_tools(self, tools, tool_types=None):
                return []

            def format_submit_result_tool(self, schema):
                return {}

            def build_create_kwargs(self, **kw):
                return {}

            def call_api(self, client, kwargs):
                pass

            def parse_response(self, response):
                pass

            def format_tool_result(self, tid, content):
                return {}

            def append_assistant_and_results(self, msgs, raw, results):
                pass

        strategy = _MinimalStrategy()
        with pytest.raises(NotImplementedError, match="must implement inject_preamble"):
            strategy.inject_preamble({}, "preamble")


# ============================================================================
# TestOpenAILoopStrategy
# ============================================================================


class TestOpenAILoopStrategy:
    """Unit tests for OpenAILoopStrategy methods."""

    def test_parse_response_text(self):
        strategy = OpenAILoopStrategy()
        response = _make_openai_agent_response(content="Hello world")
        parsed = strategy.parse_response(response)

        assert parsed.stop_reason == "end_turn"
        assert parsed.text == "Hello world"
        assert parsed.tool_calls == []
        assert parsed.input_tokens == 100
        assert parsed.output_tokens == 50

    def test_parse_response_tool_calls(self):
        strategy = OpenAILoopStrategy()
        response = _make_openai_agent_response(
            content=None,
            tool_calls=[
                _make_openai_tool_call("c1", "bash", {"command": "ls"}),
                _make_openai_tool_call("c2", "grep", {"pattern": "foo"}),
            ],
            finish_reason="tool_calls",
        )
        parsed = strategy.parse_response(response)

        assert parsed.stop_reason == "tool_use"
        assert len(parsed.tool_calls) == 2
        assert parsed.tool_calls[0].name == "bash"
        assert parsed.tool_calls[0].input == {"command": "ls"}
        assert parsed.tool_calls[1].name == "grep"

    def test_format_tool_result(self):
        strategy = OpenAILoopStrategy()
        result = strategy.format_tool_result("call_123", "output text")
        assert result == {
            "role": "tool",
            "tool_call_id": "call_123",
            "content": "output text",
        }

    def test_build_create_kwargs_system_as_message(self):
        strategy = OpenAILoopStrategy()
        kwargs = strategy.build_create_kwargs(
            model="gpt-4o",
            max_tokens=1000,
            tools=[],
            messages=[{"role": "user", "content": "hi"}],
            system="You are helpful.",
        )
        assert kwargs["messages"][0] == {
            "role": "system",
            "content": "You are helpful.",
        }
        assert kwargs["messages"][1] == {"role": "user", "content": "hi"}
        assert "tools" not in kwargs

    def test_build_create_kwargs_no_system(self):
        strategy = OpenAILoopStrategy()
        kwargs = strategy.build_create_kwargs(
            model="gpt-4o",
            max_tokens=1000,
            tools=[{"type": "function", "function": {"name": "bash"}}],
            messages=[{"role": "user", "content": "hi"}],
            system="",
        )
        assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
        assert len(kwargs["tools"]) == 1

    def test_format_submit_result_tool(self):
        strategy = OpenAILoopStrategy()
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        tool = strategy.format_submit_result_tool(schema)
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "submit_result"
        assert tool["function"]["parameters"] is schema

    def test_resolve_tools_preset(self):
        strategy = OpenAILoopStrategy()
        tools = strategy.resolve_tools("coding")
        assert len(tools) == 4
        names = [t["function"]["name"] for t in tools]
        assert "bash" in names
        assert "grep" in names

    def test_inject_user_text_after_results(self):
        strategy = OpenAILoopStrategy()
        messages = [{"role": "tool", "tool_call_id": "c1", "content": "ok"}]
        strategy.inject_user_text_after_results(messages, "extra context")
        assert messages[-1] == {"role": "user", "content": "extra context"}

    def test_append_assistant_and_results(self):
        strategy = OpenAILoopStrategy()
        messages = []
        raw_msg = SimpleNamespace(content="thinking", tool_calls=None)
        tool_results = [
            {"role": "tool", "tool_call_id": "c1", "content": "result"},
        ]
        strategy.append_assistant_and_results(messages, raw_msg, tool_results)
        assert messages[0]["role"] == "assistant"
        assert messages[0]["content"] == "thinking"
        assert messages[1] == tool_results[0]

    def test_validate_cache_ttl_accepts_zero(self):
        strategy = OpenAILoopStrategy()
        strategy.validate_cache_ttl(0)

    def test_validate_cache_ttl_rejects_nonzero(self):
        strategy = OpenAILoopStrategy()
        with pytest.raises(ValueError, match="cache_ttl must be"):
            strategy.validate_cache_ttl("5m")

    def test_default_cache_ttl_always_zero(self):
        strategy = OpenAILoopStrategy()
        assert strategy.default_cache_ttl(1) == 0
        assert strategy.default_cache_ttl(10) == 0

    def test_inject_preamble_system_message(self):
        strategy = OpenAILoopStrategy()
        kwargs = {
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hi"},
            ]
        }
        strategy.inject_preamble(kwargs, "POLICY: no secrets")
        assert kwargs["messages"][0]["content"].startswith(
            "Before processing the following instructions"
        )
        assert "POLICY: no secrets" in kwargs["messages"][0]["content"]
        assert kwargs["messages"][0]["content"].endswith("You are helpful.")
        assert kwargs["messages"][1] == {"role": "user", "content": "Hi"}

    def test_inject_preamble_no_system_message(self):
        strategy = OpenAILoopStrategy()
        kwargs = {"messages": [{"role": "user", "content": "Hi"}]}
        strategy.inject_preamble(kwargs, "POLICY: no secrets")
        assert kwargs["messages"] == [{"role": "user", "content": "Hi"}]

    def test_inject_preamble_empty_messages(self):
        strategy = OpenAILoopStrategy()
        kwargs = {"messages": []}
        strategy.inject_preamble(kwargs, "POLICY: no secrets")
        assert kwargs["messages"] == []


# ============================================================================
# TestAnthropicLoopStrategy
# ============================================================================


class TestAnthropicLoopStrategy:
    """Unit tests for AnthropicLoopStrategy methods."""

    def test_parse_response_text(self):
        strategy = AnthropicLoopStrategy()
        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello")],
            stop_reason="end_turn",
        )
        parsed = strategy.parse_response(response)

        assert parsed.stop_reason == "end_turn"
        assert parsed.text == "Hello"
        assert parsed.tool_calls == []

    def test_parse_response_tool_use(self):
        strategy = AnthropicLoopStrategy()
        response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use", name="bash", id="t1", input={"command": "ls"}
                ),
            ],
            stop_reason="tool_use",
        )
        parsed = strategy.parse_response(response)

        assert parsed.stop_reason == "tool_use"
        assert len(parsed.tool_calls) == 1
        assert parsed.tool_calls[0].name == "bash"
        assert parsed.tool_calls[0].id == "t1"

    def test_format_tool_result(self):
        strategy = AnthropicLoopStrategy()
        result = strategy.format_tool_result("t1", "output")
        assert result == {
            "type": "tool_result",
            "tool_use_id": "t1",
            "content": "output",
        }

    def test_inject_user_text_merges_into_list(self):
        strategy = AnthropicLoopStrategy()
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
                ],
            }
        ]
        strategy.inject_user_text_after_results(messages, "extra")
        last = messages[-1]["content"]
        assert isinstance(last, list)
        assert last[-1] == {"type": "text", "text": "extra"}

    def test_api_method_name(self):
        assert AnthropicLoopStrategy().api_method_name == "messages.create"

    def test_is_server_tool(self):
        strategy = AnthropicLoopStrategy()
        assert strategy.is_server_tool("web_search") is True
        assert strategy.is_server_tool("bash") is False

    def test_validate_cache_ttl_accepts_valid_values(self):
        strategy = AnthropicLoopStrategy()
        for val in (0, "5m", "1h"):
            strategy.validate_cache_ttl(val)

    def test_validate_cache_ttl_rejects_invalid(self):
        strategy = AnthropicLoopStrategy()
        with pytest.raises(ValueError, match="cache_ttl must be"):
            strategy.validate_cache_ttl("10m")

    def test_default_cache_ttl_multi_turn(self):
        strategy = AnthropicLoopStrategy()
        assert strategy.default_cache_ttl(10) == "5m"

    def test_default_cache_ttl_single_turn(self):
        strategy = AnthropicLoopStrategy()
        assert strategy.default_cache_ttl(1) == 0

    def test_build_create_kwargs_cache_ttl_5m(self):
        strategy = AnthropicLoopStrategy()
        kwargs = strategy.build_create_kwargs(
            model="claude-sonnet-5",
            max_tokens=1024,
            tools=[],
            messages=[{"role": "user", "content": "hi"}],
            system="You are helpful.",
            cache_ttl="5m",
        )
        assert kwargs["system"] == [
            {
                "type": "text",
                "text": "You are helpful.",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def test_build_create_kwargs_cache_ttl_1h(self):
        strategy = AnthropicLoopStrategy()
        kwargs = strategy.build_create_kwargs(
            model="claude-sonnet-5",
            max_tokens=1024,
            tools=[],
            messages=[{"role": "user", "content": "hi"}],
            system="You are helpful.",
            cache_ttl="1h",
        )
        assert kwargs["system"] == [
            {
                "type": "text",
                "text": "You are helpful.",
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        ]

    def test_build_create_kwargs_cache_ttl_disabled(self):
        strategy = AnthropicLoopStrategy()
        kwargs = strategy.build_create_kwargs(
            model="claude-sonnet-5",
            max_tokens=1024,
            tools=[],
            messages=[{"role": "user", "content": "hi"}],
            system="You are helpful.",
            cache_ttl=0,
        )
        assert kwargs["system"] == "You are helpful."

    def test_build_create_kwargs_cache_ttl_no_system(self):
        strategy = AnthropicLoopStrategy()
        kwargs = strategy.build_create_kwargs(
            model="claude-sonnet-5",
            max_tokens=1024,
            tools=[],
            messages=[{"role": "user", "content": "hi"}],
            system="",
            cache_ttl="5m",
        )
        assert "system" not in kwargs

    def test_parse_response_cache_tokens(self):
        strategy = AnthropicLoopStrategy()
        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=2000,
            cache_read_input_tokens=1500,
        )
        response = _make_agent_response(
            [SimpleNamespace(type="text", text="cached")],
            stop_reason="end_turn",
            usage=usage,
        )
        parsed = strategy.parse_response(response)
        assert parsed.cache_creation_input_tokens == 2000
        assert parsed.cache_read_input_tokens == 1500

    def test_parse_response_no_cache_tokens(self):
        strategy = AnthropicLoopStrategy()
        usage = SimpleNamespace(input_tokens=100, output_tokens=50)
        response = _make_agent_response(
            [SimpleNamespace(type="text", text="no cache")],
            stop_reason="end_turn",
            usage=usage,
        )
        parsed = strategy.parse_response(response)
        assert parsed.cache_creation_input_tokens == 0
        assert parsed.cache_read_input_tokens == 0

    def test_inject_preamble_system_string(self):
        strategy = AnthropicLoopStrategy()
        kwargs = {"system": "You are helpful."}
        strategy.inject_preamble(kwargs, "POLICY: no secrets")
        assert kwargs["system"].startswith(
            "Before processing the following instructions"
        )
        assert "POLICY: no secrets" in kwargs["system"]
        assert kwargs["system"].endswith("You are helpful.")

    def test_inject_preamble_system_list(self):
        strategy = AnthropicLoopStrategy()
        kwargs = {"system": [{"type": "text", "text": "Original."}]}
        strategy.inject_preamble(kwargs, "POLICY: no secrets")
        assert len(kwargs["system"]) == 2
        assert "POLICY: no secrets" in kwargs["system"][0]["text"]
        assert kwargs["system"][1]["text"] == "Original."

    def test_inject_preamble_no_system_key(self):
        strategy = AnthropicLoopStrategy()
        kwargs = {"messages": [{"role": "user", "content": "Hi"}]}
        strategy.inject_preamble(kwargs, "POLICY: no secrets")
        assert "system" not in kwargs


class TestGuardedAgentCacheTtl:
    """Tests for GuardedAgent cache_ttl parameter."""

    def _make_agent(self, mock_client=None, **kwargs):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        if mock_client is None:
            mock_create = MagicMock()
            mock_messages = SimpleNamespace(create=mock_create)
            mock_client = SimpleNamespace(messages=mock_messages)

        defaults = {
            "model": "claude-sonnet-5",
            "tools": ["bash"],
            "client": mock_client,
            "action": "log",
        }
        defaults.update(kwargs)
        return GuardedAgent(**defaults), mock_client

    def test_default_multi_turn(self):
        agent, _ = self._make_agent(max_turns=10)
        assert agent._cache_ttl == "5m"

    def test_default_single_turn(self):
        agent, _ = self._make_agent(max_turns=1)
        assert agent._cache_ttl == 0

    def test_explicit_1h(self):
        agent, _ = self._make_agent(cache_ttl="1h")
        assert agent._cache_ttl == "1h"

    def test_explicit_disabled(self):
        agent, _ = self._make_agent(cache_ttl=0)
        assert agent._cache_ttl == 0

    def test_explicit_overrides_single_turn_default(self):
        agent, _ = self._make_agent(max_turns=1, cache_ttl="5m")
        assert agent._cache_ttl == "5m"

    def test_invalid_cache_ttl_raises(self):
        with pytest.raises(ValueError, match="cache_ttl must be"):
            self._make_agent(cache_ttl="10m")

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_cache_tokens_in_usage(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=2000,
            cache_read_input_tokens=0,
        )
        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello!")],
            stop_reason="end_turn",
            usage=usage,
        )

        agent, client = self._make_agent(cache_ttl="5m")
        client.messages.create.return_value = response

        result = agent.run("Hi")

        assert result["usage"]["cache_creation_input_tokens"] == 2000
        assert result["usage"]["cache_read_input_tokens"] == 0

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_system_formatted_with_cache_control(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(system_prompt="Be helpful.", cache_ttl="5m")
        client.messages.create.return_value = response

        agent.run("Hi")

        call_kwargs = client.messages.create.call_args[1]
        assert isinstance(call_kwargs["system"], list)
        assert call_kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


# ============================================================================
# TestTurnEvent
# ============================================================================


class TestTurnEvent:
    """TurnEvent dataclass and __str__ formatting."""

    def test_system_event_str(self):
        from ai_guardian.integrations.base import TurnEvent

        ev = TurnEvent(
            type="system",
            preamble="POLICY: be safe",
            system_prompt="You are a code reviewer.",
            user_prompt="Review this code",
        )
        s = str(ev)
        assert "[system]" in s
        assert "preamble:" in s
        assert "prompt:" in s
        assert "user:" in s

    def test_response_event_str(self):
        from ai_guardian.integrations.base import TurnEvent

        ev = TurnEvent(type="response", text="Hello world", stop_reason="end_turn")
        s = str(ev)
        assert "[response]" in s
        assert "Hello world" in s

    def test_response_event_str_truncates(self):
        from ai_guardian.integrations.base import TurnEvent

        ev = TurnEvent(type="response", text="x" * 200)
        s = str(ev)
        assert s.endswith("...")

    def test_tool_call_event_str(self):
        from ai_guardian.integrations.base import TurnEvent

        ev = TurnEvent(type="tool_call", name="bash", input={"command": "ls"})
        s = str(ev)
        assert "[tool_call]" in s
        assert "bash" in s

    def test_tool_result_event_str(self):
        from ai_guardian.integrations.base import TurnEvent

        ev = TurnEvent(type="tool_result", name="bash", output="file1.py\nfile2.py")
        s = str(ev)
        assert "[tool_result]" in s
        assert "bash" in s

    def test_scan_clean_str(self):
        from ai_guardian.integrations.base import TurnEvent

        ev = TurnEvent(type="scan", scanned="agent_response", violations=[])
        s = str(ev)
        assert "[scan]" in s
        assert "clean" in s

    def test_scan_violations_str(self):
        from ai_guardian.integrations.base import TurnEvent

        ev = TurnEvent(
            type="scan",
            scanned="agent_response",
            violations=[{"type": "secret", "message": "AWS key detected"}],
        )
        s = str(ev)
        assert "1 violation" in s

    def test_unknown_type_str(self):
        from ai_guardian.integrations.base import TurnEvent

        ev = TurnEvent(type="custom")
        assert str(ev) == "[custom]"

    def test_to_dict_omits_none(self):
        from ai_guardian.integrations.base import TurnEvent

        ev = TurnEvent(type="response", text="hello", stop_reason="end_turn")
        d = ev.to_dict()
        assert d["type"] == "response"
        assert d["text"] == "hello"
        assert d["stop_reason"] == "end_turn"
        assert "name" not in d
        assert "input" not in d
        assert "preamble" not in d

    def test_to_dict_includes_empty_violations(self):
        from ai_guardian.integrations.base import TurnEvent

        ev = TurnEvent(type="scan", scanned="user_prompt", violations=[])
        d = ev.to_dict()
        assert d["violations"] == []

    def test_print_works_as_on_turn(self):
        from ai_guardian.integrations.base import TurnEvent

        ev = TurnEvent(type="response", text="Hello!")
        output = str(ev)
        assert isinstance(output, str)


# ============================================================================
# TestGuardedAgentTrace
# ============================================================================


class TestGuardedAgentTrace:
    """Trace collection and on_turn callback tests."""

    def _make_agent(self, mock_client=None, **kwargs):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        if mock_client is None:
            mock_create = MagicMock()
            mock_messages = SimpleNamespace(create=mock_create)
            mock_client = SimpleNamespace(messages=mock_messages)

        defaults = {
            "model": "claude-sonnet-5",
            "tools": ["bash"],
            "client": mock_client,
            "action": "log",
        }
        defaults.update(kwargs)
        return GuardedAgent(**defaults), mock_client

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_in_result(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello!")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.return_value = response

        result = agent.run("Hi")

        assert "trace" in result
        assert isinstance(result["trace"], list)
        assert len(result["trace"]) > 0

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_starts_with_system_event(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(system_prompt="You are helpful.")
        client.messages.create.return_value = response

        result = agent.run("Hello")
        trace = result["trace"]

        assert trace[0]["turn"] == 0
        assert trace[0]["type"] == "system"
        assert trace[0]["system_prompt"] == "You are helpful."
        assert trace[0]["user_prompt"] == "Hello"
        assert trace[0].get("preamble") is None

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_system_event_no_system_prompt(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.return_value = response

        result = agent.run("Hello")
        trace = result["trace"]

        assert trace[0]["type"] == "system"
        assert trace[0]["system_prompt"] == ""
        assert trace[0]["user_prompt"] == "Hello"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_has_scan_events(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(system_prompt="Be helpful.")
        client.messages.create.return_value = response

        result = agent.run("Hi")
        trace = result["trace"]

        scan_events = [e for e in trace if e["type"] == "scan"]
        assert len(scan_events) >= 2
        scanned_targets = [e["scanned"] for e in scan_events]
        assert "user_prompt" in scanned_targets
        assert "agent_response" in scanned_targets

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_no_scan_when_disabled(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(scan_input=False, scan_output=False)
        client.messages.create.return_value = response

        result = agent.run("Hi")
        trace = result["trace"]

        scan_events = [e for e in trace if e["type"] == "scan"]
        assert len(scan_events) == 0

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_response_event(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello!")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )

        agent, client = self._make_agent()
        client.messages.create.return_value = response

        result = agent.run("Hi")
        trace = result["trace"]

        resp_events = [e for e in trace if e["type"] == "response"]
        assert len(resp_events) == 1
        assert resp_events[0]["turn"] == 1
        assert resp_events[0]["text"] == "Hello!"
        assert resp_events[0]["stop_reason"] == "end_turn"
        assert resp_events[0]["usage"]["input_tokens"] == 100
        assert resp_events[0]["usage"]["output_tokens"] == 50

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_tool_events(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="tool_1",
                    input={"command": "echo test"},
                ),
            ],
            stop_reason="tool_use",
        )
        final_response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done!")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.side_effect = [tool_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="test output",
        ):
            result = agent.run("Run echo")

        trace = result["trace"]

        tc_events = [e for e in trace if e["type"] == "tool_call"]
        assert len(tc_events) == 1
        assert tc_events[0]["turn"] == 1
        assert tc_events[0]["name"] == "bash"
        assert tc_events[0]["input"] == {"command": "echo test"}

        tr_events = [e for e in trace if e["type"] == "tool_result"]
        assert len(tr_events) == 1
        assert tr_events[0]["turn"] == 1
        assert tr_events[0]["name"] == "bash"
        assert tr_events[0]["output"] == "test output"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_tool_result_scan(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="tool_1",
                    input={"command": "echo hi"},
                ),
            ],
            stop_reason="tool_use",
        )
        final_response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.side_effect = [tool_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="output",
        ):
            result = agent.run("Test")

        trace = result["trace"]
        scan_events = [e for e in trace if e["type"] == "scan"]
        tool_scans = [e for e in scan_events if "tool_result" in e.get("scanned", "")]
        assert len(tool_scans) == 1
        assert tool_scans[0]["scanned"] == "tool_result:bash"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_on_turn_callback_fires(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello!")],
            stop_reason="end_turn",
        )

        events = []

        def handler(turn, event):
            events.append((turn, event))

        agent, client = self._make_agent(on_turn=handler)
        client.messages.create.return_value = response

        agent.run("Hi")

        assert len(events) > 0
        turns_seen = [t for t, _ in events]
        assert 0 in turns_seen
        assert 1 in turns_seen
        types_seen = [e.type for _, e in events]
        assert "system" in types_seen
        assert "response" in types_seen

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_on_turn_receives_turn_event_instances(self, mock_monitor):
        from ai_guardian.integrations.base import TurnEvent

        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        events = []
        agent, client = self._make_agent(on_turn=lambda t, e: events.append(e))
        client.messages.create.return_value = response

        agent.run("Hi")

        for ev in events:
            assert isinstance(ev, TurnEvent)

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_multi_turn(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        r1 = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo 1"},
                ),
            ],
            stop_reason="tool_use",
        )
        r2 = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.side_effect = [r1, r2]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="output",
        ):
            result = agent.run("Test")

        trace = result["trace"]
        resp_events = [e for e in trace if e["type"] == "response"]
        assert len(resp_events) == 2
        assert resp_events[0]["turn"] == 1
        assert resp_events[1]["turn"] == 2

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_server_tools_no_trace_events(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="web_search",
                    id="tool_1",
                    input={"query": "test"},
                ),
            ],
            stop_reason="tool_use",
        )
        final_response = _make_agent_response(
            [SimpleNamespace(type="text", text="Found it")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(tools=["bash", "web_search"])
        client.messages.create.side_effect = [tool_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool"
        ) as mock_exec:
            result = agent.run("Search")
            mock_exec.assert_not_called()

        trace = result["trace"]
        tc_events = [e for e in trace if e["type"] == "tool_call"]
        assert len(tc_events) == 0

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_on_turn_not_set_still_collects_trace(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello!")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.return_value = response

        result = agent.run("Hi")

        assert "trace" in result
        assert len(result["trace"]) > 0

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_event_order(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="t1",
                    input={"command": "echo hi"},
                ),
            ],
            stop_reason="tool_use",
        )
        final_response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.side_effect = [tool_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="output",
        ):
            result = agent.run("Test order")

        types = [e["type"] for e in result["trace"]]
        assert types[0] == "system"
        assert "scan" in types
        assert "response" in types
        assert "tool_call" in types
        assert "tool_result" in types

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_scan_violation_recorded(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()

        def check_side_effect(text, filename="input"):
            if filename == "agent_response":
                raise SecurityViolation(
                    CheckResult(
                        blocked=True,
                        detected=True,
                        violation_type="secret",
                        message="Secret detected",
                    )
                )
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_session.sanitize.return_value = {"sanitized_text": "[REDACTED]"}
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="leaked secret")],
            stop_reason="end_turn",
        )

        events = []
        agent, client = self._make_agent(
            action="block", on_turn=lambda t, e: events.append((t, e))
        )
        client.messages.create.return_value = response

        with pytest.raises(SecurityViolation):
            agent.run("Hi")

        scan_events = [(t, e) for t, e in events if e.type == "scan"]
        violation_scans = [
            (t, e) for t, e in scan_events if e.violations and len(e.violations) > 0
        ]
        assert len(violation_scans) == 1
        assert violation_scans[0][1].scanned == "agent_response"
        assert violation_scans[0][1].violations[0]["type"] == "secret"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_tool_result_sanitized_before_next_turn(self, mock_monitor):
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        mock_session.sanitize.return_value = {"sanitized_text": "[SECRET REDACTED]"}

        def check_side_effect(text, filename="input"):
            if filename.startswith("tool_result:"):
                return CheckResult(blocked=False, detected=True, message="secret found")
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_agent_response(
            [
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="tool_1",
                    input={"command": "cat secret.txt"},
                ),
            ],
            stop_reason="tool_use",
        )
        final_response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.side_effect = [tool_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="AKIA_FAKE_SECRET_KEY",
        ):
            result = agent.run("read the file")

        messages = result["messages"]
        tool_result_msg = messages[2]
        content = tool_result_msg["content"]
        assert isinstance(content, list)
        assert content[0]["content"] == "[SECRET REDACTED]"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_agent_response_sanitized_in_warn_mode(self, mock_monitor):
        """Agent response text with detected violation is sanitized before entering messages (#1880)."""
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        mock_session.sanitize.return_value = {"sanitized_text": "[SECRET REDACTED]"}

        def check_side_effect(text, filename="input"):
            if filename == "agent_response":
                return CheckResult(blocked=False, detected=True, message="secret found")
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        tool_response = _make_agent_response(
            [
                SimpleNamespace(type="text", text="The key is AKIA_FAKE_SECRET"),
                SimpleNamespace(
                    type="tool_use",
                    name="bash",
                    id="tool_1",
                    input={"command": "echo done"},
                ),
            ],
            stop_reason="tool_use",
        )
        final_response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(action="warn")
        client.messages.create.side_effect = [tool_response, final_response]

        with patch(
            "ai_guardian.integrations.anthropic.agent.execute_tool",
            return_value="ok",
        ):
            result = agent.run("show the key")

        messages = result["messages"]
        assistant_msg = messages[1]
        assert assistant_msg["role"] == "assistant"
        content = assistant_msg["content"]
        text_block = next(
            b
            for b in content
            if (b.get("type") if isinstance(b, dict) else getattr(b, "type", None))
            == "text"
        )
        assert text_block["text"] == "[SECRET REDACTED]"
        assert "AKIA_FAKE_SECRET" not in str(content)

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_agent_response_sanitized_output_text(self, mock_monitor):
        """Sanitized agent response text is reflected in output on end_turn (#1880)."""
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        mock_session.sanitize.return_value = {"sanitized_text": "[REDACTED]"}

        def check_side_effect(text, filename="input"):
            if filename == "agent_response":
                return CheckResult(blocked=False, detected=True, message="secret")
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="secret-value-here")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(action="warn")
        client.messages.create.return_value = response
        result = agent.run("tell me")

        assert result["output"] == "[REDACTED]"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_agent_response_block_mode_still_raises(self, mock_monitor):
        """Block mode still raises SecurityViolation for agent response (#1880)."""
        from ai_guardian.sdk import CheckResult, SecurityViolation

        mock_session = MagicMock()

        def check_side_effect(text, filename="input"):
            if filename == "agent_response":
                raise SecurityViolation(
                    CheckResult(blocked=True, detected=True, message="blocked")
                )
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="secret")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(action="block")
        client.messages.create.return_value = response

        with pytest.raises(SecurityViolation):
            agent.run("test")

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_agent_response_trace_records_raw_text(self, mock_monitor):
        """Trace records raw text before sanitization (#1880)."""
        from ai_guardian.sdk import CheckResult

        mock_session = MagicMock()
        mock_session.sanitize.return_value = {"sanitized_text": "[REDACTED]"}

        def check_side_effect(text, filename="input"):
            if filename == "agent_response":
                return CheckResult(blocked=False, detected=True, message="secret")
            return CheckResult(blocked=False, detected=False)

        mock_session.check_content.side_effect = check_side_effect
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="raw-secret-text")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(action="log")
        client.messages.create.return_value = response
        result = agent.run("test")

        trace = result["trace"]
        response_events = [e for e in trace if e.get("type") == "response"]
        assert len(response_events) == 1
        assert response_events[0]["text"] == "raw-secret-text"


class TestGuardedAgentPartialTrace:
    """Tests for partial trace preservation on failure (#1887)."""

    def _make_agent(self, mock_client=None, **kwargs):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        if mock_client is None:
            mock_create = MagicMock()
            mock_messages = SimpleNamespace(create=mock_create)
            mock_client = SimpleNamespace(messages=mock_messages)

        defaults = {
            "model": "claude-sonnet-5",
            "tools": ["bash"],
            "client": mock_client,
            "action": "log",
        }
        defaults.update(kwargs)
        return GuardedAgent(**defaults), mock_client

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_last_trace_available_on_success(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.return_value = response
        result = agent.run("Hi")

        assert agent._last_trace is result["trace"]
        assert len(agent._last_trace) > 0

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_last_trace_preserved_on_api_error(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        agent, client = self._make_agent()
        client.messages.create.side_effect = RuntimeError("API overloaded")

        with pytest.raises(RuntimeError, match="API overloaded") as exc_info:
            agent.run("Hi")

        assert hasattr(exc_info.value, "trace")
        assert len(exc_info.value.trace) > 0
        assert exc_info.value.trace[0]["type"] == "system"
        assert agent._last_trace is exc_info.value.trace

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_last_trace_preserved_on_security_violation(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="secret data")],
            stop_reason="end_turn",
        )

        violation_result = MagicMock()
        violation_result.violation_type = "prompt_injection"
        violation_result.message = "Threat detected"
        mock_session.check_content.side_effect = SecurityViolation(violation_result)

        agent, client = self._make_agent(scan_input=True)
        client.messages.create.return_value = response

        with pytest.raises(SecurityViolation) as exc_info:
            agent.run("Hi")

        assert hasattr(exc_info.value, "trace")
        assert len(exc_info.value.trace) > 0
        assert agent._last_trace is exc_info.value.trace

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_partial_trace_has_turns_before_failure(self, mock_monitor):
        mock_session = MagicMock()
        mock_session.check_content.return_value = MagicMock(detected=False)
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        good_response = _make_agent_response(
            [
                SimpleNamespace(type="text", text="step 1"),
                SimpleNamespace(
                    type="tool_use", id="t1", name="bash", input={"command": "echo hi"}
                ),
            ],
            stop_reason="tool_use",
        )

        call_count = [0]
        original_create = MagicMock()

        def create_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return good_response
            raise RuntimeError("API died on turn 2")

        agent, client = self._make_agent()
        client.messages.create.side_effect = create_side_effect

        with pytest.raises(RuntimeError, match="API died on turn 2") as exc_info:
            agent.run("multi-turn task")

        trace = exc_info.value.trace
        assert any(e["type"] == "system" for e in trace)
        assert any(e["type"] == "response" and e["turn"] == 1 for e in trace)

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_partial_trace_persisted_to_disk(self, mock_monitor, tmp_path):
        import json

        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        agent, client = self._make_agent(
            name="crash-agent", trace_dir=str(tmp_path / "traces")
        )
        client.messages.create.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError):
            agent.run("Hi")

        trace_dir = str(tmp_path / "traces")
        files = os.listdir(trace_dir)
        assert len(files) == 1
        assert files[0].startswith("crash-agent_")

        with open(os.path.join(trace_dir, files[0])) as fh:
            doc = json.load(fh)
        assert doc["stop_reason"] == "error"
        assert len(doc["trace"]) > 0

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_last_trace_reset_each_run(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent()
        client.messages.create.return_value = response

        agent.run("first")
        first_trace = agent._last_trace

        agent.run("second")
        second_trace = agent._last_trace

        assert first_trace is not second_trace
        assert second_trace[0]["user_prompt"] == "second"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_post_run_receives_none_on_failure(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        post_run_args = []

        agent, client = self._make_agent(
            post_run=lambda r: post_run_args.append(r),
        )
        client.messages.create.side_effect = RuntimeError("crash")

        with pytest.raises(RuntimeError):
            agent.run("Hi")

        assert len(post_run_args) == 1
        assert post_run_args[0] is None
        assert len(agent._last_trace) > 0


class TestGuardedAgentTraceDir:
    """Tests for auto-persist trace logs to disk (#1877)."""

    def _make_agent(self, mock_client=None, **kwargs):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        if mock_client is None:
            mock_create = MagicMock()
            mock_messages = SimpleNamespace(create=mock_create)
            mock_client = SimpleNamespace(messages=mock_messages)

        defaults = {
            "model": "claude-sonnet-5",
            "tools": ["bash"],
            "client": mock_client,
            "action": "log",
        }
        defaults.update(kwargs)
        return GuardedAgent(**defaults), mock_client

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_written_to_disk(self, mock_monitor, tmp_path):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello!")],
            stop_reason="end_turn",
        )

        trace_dir = str(tmp_path / "traces")
        agent, client = self._make_agent(name="triage-verifier", trace_dir=trace_dir)
        client.messages.create.return_value = response
        agent.run("Hi")

        files = os.listdir(trace_dir)
        assert len(files) == 1
        assert files[0].startswith("triage-verifier_")
        assert files[0].endswith(".json")

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_file_content(self, mock_monitor, tmp_path):
        import json

        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )

        trace_dir = str(tmp_path / "traces")
        agent, client = self._make_agent(name="my-agent", trace_dir=trace_dir)
        client.messages.create.return_value = response
        agent.run("test prompt")

        files = os.listdir(trace_dir)
        with open(os.path.join(trace_dir, files[0])) as fh:
            doc = json.load(fh)

        assert doc["agent_name"] == "my-agent"
        assert doc["model"] == "claude-sonnet-5"
        assert doc["stop_reason"] == "end_turn"
        assert "started_at" in doc
        assert "usage" in doc
        assert isinstance(doc["trace"], list)
        assert len(doc["trace"]) > 0

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_dir_created_if_missing(self, mock_monitor, tmp_path):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        nested = str(tmp_path / "a" / "b" / "c")
        agent, client = self._make_agent(name="test", trace_dir=nested)
        client.messages.create.return_value = response
        agent.run("Hi")

        assert os.path.isdir(nested)
        assert len(os.listdir(nested)) == 1

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_no_trace_when_trace_dir_none(self, mock_monitor, tmp_path):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(name="test")
        client.messages.create.return_value = response
        result = agent.run("Hi")

        assert "trace" in result

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_write_error_does_not_fail_agent(self, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(
            name="test", trace_dir="/nonexistent/readonly/path"
        )
        client.messages.create.return_value = response
        result = agent.run("Hi")

        assert result["output"] == "OK"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_default_agent_name(self, mock_monitor, tmp_path):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        trace_dir = str(tmp_path / "traces")
        agent, client = self._make_agent(trace_dir=trace_dir)
        client.messages.create.return_value = response
        agent.run("Hi")

        files = os.listdir(trace_dir)
        assert files[0].startswith("agent_")

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_dir_from_config(self, mock_monitor, tmp_path):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        trace_dir = str(tmp_path / "config-traces")
        with (
            patch(
                "ai_guardian.config.loaders._load_sdk_profile",
                return_value={"trace_dir": trace_dir},
            ),
            patch(
                "ai_guardian.config.loaders._sdk_enabled",
                return_value=True,
            ),
        ):
            agent, client = self._make_agent(name="cfg-agent")
            client.messages.create.return_value = response
            agent.run("Hi")

        assert os.path.isdir(trace_dir)
        files = os.listdir(trace_dir)
        assert len(files) == 1
        assert files[0].startswith("cfg-agent_")

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_post_run_still_called_with_trace_dir(self, mock_monitor, tmp_path):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        post_run_called = []
        trace_dir = str(tmp_path / "traces")
        agent, client = self._make_agent(
            name="test",
            trace_dir=trace_dir,
            post_run=lambda r: post_run_called.append(r),
        )
        client.messages.create.return_value = response
        agent.run("Hi")

        assert len(post_run_called) == 1
        assert post_run_called[0]["output"] == "OK"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_content_is_sanitized(self, mock_monitor, tmp_path):
        import json

        mock_session = MagicMock()
        mock_session.sanitize_batch.side_effect = lambda texts: [
            "[REDACTED]" for _ in texts
        ]
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="secret-key-12345")],
            stop_reason="end_turn",
        )

        trace_dir = str(tmp_path / "traces")
        agent, client = self._make_agent(
            name="test",
            trace_dir=trace_dir,
            system_prompt="my system prompt",
        )
        client.messages.create.return_value = response
        agent.run("user prompt with secret")

        files = os.listdir(trace_dir)
        with open(os.path.join(trace_dir, files[0])) as fh:
            doc = json.load(fh)

        for entry in doc["trace"]:
            for field in ("text", "system_prompt", "user_prompt", "output"):
                val = entry.get(field)
                if val:
                    assert val == "[REDACTED]", (
                        f"Field '{field}' not sanitized in "
                        f"trace entry type={entry['type']}"
                    )

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_sanitize_failure_falls_back_to_raw(self, mock_monitor, tmp_path):
        import json

        mock_session = MagicMock()
        mock_session.sanitize_batch.side_effect = Exception("sanitize failed")
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="some text")],
            stop_reason="end_turn",
        )

        trace_dir = str(tmp_path / "traces")
        agent, client = self._make_agent(name="test", trace_dir=trace_dir)
        client.messages.create.return_value = response
        agent.run("Hi")

        files = os.listdir(trace_dir)
        with open(os.path.join(trace_dir, files[0])) as fh:
            doc = json.load(fh)

        response_events = [e for e in doc["trace"] if e["type"] == "response"]
        assert response_events[0]["text"] == "some text"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    def test_trace_relative_dir_resolved_to_cwd(self, mock_monitor, tmp_path):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        response = _make_agent_response(
            [SimpleNamespace(type="text", text="OK")],
            stop_reason="end_turn",
        )

        agent, client = self._make_agent(
            name="test",
            trace_dir="logs/agents",
            cwd=str(tmp_path),
        )
        client.messages.create.return_value = response
        agent.run("Hi")

        expected_dir = tmp_path / "logs" / "agents"
        assert expected_dir.is_dir()
        assert len(list(expected_dir.iterdir())) == 1
