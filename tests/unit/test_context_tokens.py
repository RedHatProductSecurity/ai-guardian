"""Tests for context token computation and display (#2023)."""

import inspect

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.components.step_render import (
    compute_context_tokens,
    format_token_count,
)


class TestFormatTokenCount:
    """format_token_count produces human-readable k/M suffixes."""

    def test_below_thousand(self):
        assert format_token_count(0) == "0"
        assert format_token_count(669) == "669"
        assert format_token_count(400) == "400"
        assert format_token_count(999) == "999"

    def test_thousands(self):
        assert format_token_count(1000) == "1k"
        assert format_token_count(1300) == "1.3k"
        assert format_token_count(45200) == "45.2k"
        assert format_token_count(132100) == "132.1k"
        assert format_token_count(489800) == "489.8k"

    def test_millions(self):
        assert format_token_count(1_000_000) == "1M"
        assert format_token_count(2_000_000) == "2M"
        assert format_token_count(29_200_000) == "29.2M"
        assert format_token_count(28_700_000) == "28.7M"

    def test_trailing_zero_stripped(self):
        assert format_token_count(5000) == "5k"
        assert format_token_count(3_000_000) == "3M"


class TestComputeContextTokens:
    """compute_context_tokens sums input + cache_read + cache_create."""

    def test_all_fields_present(self):
        tokens = {
            "input_tokens": 669,
            "cache_read_input_tokens": 44100,
            "cache_creation_input_tokens": 400,
        }
        assert compute_context_tokens(tokens) == 45169

    def test_missing_cache_fields(self):
        tokens = {"input_tokens": 1000}
        assert compute_context_tokens(tokens) == 1000

    def test_empty_dict(self):
        assert compute_context_tokens({}) == 0

    def test_zero_values(self):
        tokens = {
            "input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        assert compute_context_tokens(tokens) == 0


class TestWebIdeSessionsContextDisplay:
    """Web IDE Sessions page shows context tokens."""

    def test_session_card_computes_context(self):
        from ai_guardian.web.pages.ide_sessions import _render_session_card

        source = inspect.getsource(_render_session_card)
        assert "compute_context_tokens" in source
        assert "context_tok" in source

    def test_session_summary_shows_context_first(self):
        from ai_guardian.web.pages.ide_sessions import _render_session_summary

        source = inspect.getsource(_render_session_summary)
        assert "context" in source.lower()
        context_pos = source.find("Context:")
        input_pos = source.find("Input:")
        assert context_pos < input_pos, "Context should appear before Input"

    def test_per_turn_shows_context(self):
        from ai_guardian.web.pages.ide_sessions import _render_step

        source = inspect.getsource(_render_step)
        assert "compute_context_tokens" in source
        assert "format_token_count" in source


class TestWebTracesContextDisplay:
    """Web Traces page shows context tokens."""

    def test_trace_card_shows_context(self):
        from ai_guardian.web.pages.traces import _render_trace_card

        source = inspect.getsource(_render_trace_card)
        assert "compute_context_tokens" in source
        assert "context_tok" in source

    def test_trace_summary_shows_context_first(self):
        from ai_guardian.web.pages.traces import _render_token_summary

        source = inspect.getsource(_render_token_summary)
        context_pos = source.find("Context:")
        input_pos = source.find("Input:")
        assert context_pos < input_pos, "Context should appear before Input"

    def test_per_turn_computes_context(self):
        from ai_guardian.web.pages.traces import _render_turn_row

        source = inspect.getsource(_render_turn_row)
        assert "turn_context" in source
        assert "compute_context_tokens" in source

    def test_response_step_shows_context(self):
        from ai_guardian.web.pages.traces import _render_step

        source = inspect.getsource(_render_step)
        assert "compute_context_tokens" in source


class TestTuiContextDisplay:
    """TUI panels show context tokens."""

    def test_tui_session_detail_shows_context(self):
        from ai_guardian.tui.ide_sessions import IDESessionsContent

        source = inspect.getsource(IDESessionsContent._show_session_detail)
        assert "context" in source.lower()
        assert "cache_read" in source
        assert "cache_create" in source

    def test_tui_session_label_shows_context(self):
        from ai_guardian.tui.ide_sessions import _format_session_label

        source = inspect.getsource(_format_session_label)
        assert "context" in source.lower()

    def test_tui_trace_label_shows_context(self):
        from ai_guardian.tui.traces import _format_trace_label

        source = inspect.getsource(_format_trace_label)
        assert "context" in source.lower()
        assert "cache_read" in source
        assert "cache_create" in source

    def test_tui_session_label_output(self):
        from ai_guardian.tui.ide_sessions import _format_session_label

        session = {
            "title": "Test",
            "model": "claude",
            "message_count": 5,
            "modified": 0,
            "token_usage": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_input_tokens": 44000,
                "cache_creation_input_tokens": 200,
            },
        }
        label = _format_session_label(session)
        assert "ctx:45.2k" in label

    def test_tui_trace_label_output(self):
        from ai_guardian.tui.traces import _format_trace_label

        trace = {
            "agent_name": "test-agent",
            "model": "claude",
            "total_turns": 3,
            "started_at": "2026-01-01T00:00:00",
            "stop_reason": "done",
            "is_active": False,
            "total_tokens": {
                "input_tokens": 2000,
                "output_tokens": 500,
                "cache_read_input_tokens": 80000,
                "cache_creation_input_tokens": 300,
            },
            "duration_seconds": 60,
            "violation_count": 0,
        }
        label = _format_trace_label(trace)
        assert "ctx:82.3k" in label
