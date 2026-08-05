"""Tests for the LLM client integration wrapper."""

import os
import sys
import warnings
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.integrations.base import (
    ProviderExtractor,
    _GuardedClient,
    _MethodChainProxy,
    _StreamProxy,
    _detect_extractor,
    _REGISTRY,
    guarded,
    register_extractor,
)
from ai_guardian.integrations.anthropic import AnthropicExtractor, create_client
from ai_guardian.integrations.openai import OpenAIExtractor
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
            assert key in _REGISTRY, f"{key} not registered"
            assert _REGISTRY[key] is AnthropicExtractor

    def test_detect_raises_for_unknown_client(self):
        with pytest.raises(ValueError, match="No provider extractor found"):
            _detect_extractor({"not": "a client"})

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

        register_extractor("test_pkg.FakeClient", FakeExtractor)
        assert "test_pkg.FakeClient" in _REGISTRY
        del _REGISTRY["test_pkg.FakeClient"]


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
        with pytest.raises(ValueError, match="No provider extractor found"):
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
            assert key in _REGISTRY, f"{key} not registered"
            assert _REGISTRY[key] is OpenAIExtractor


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
        assert names == ["str_replace_based_edit_tool", "grep", "glob"]

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

    def test_unknown_tool(self, tmp_path):
        from ai_guardian.integrations.anthropic.tools import execute_tool

        result = execute_tool("unknown_tool", {}, str(tmp_path))
        assert "Error" in result


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
            if filename == "assistant_response":
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
