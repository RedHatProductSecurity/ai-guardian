"""Tests for the OTEL GenAI trace exporter."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.scanners.otel_exporter import (
    HookOtelEmitter,
    OtelSpanEmitter,
    _derive_end_nano,
    _iso_to_unix_nano,
    _make_attribute,
    _make_root_span,
    _make_span,
    _make_step_spans,
    _make_turn_span,
    _resolve_headers,
    _truncate_span_id,
    handle_trace_command,
    trace_to_otlp_json,
)

from ai_guardian.config.loaders import _load_otel_config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_TRACE_DOC = {
    "agent_name": "test-agent",
    "model": "claude-sonnet-4-20250514",
    "started_at": "2026-08-14T10:00:00+00:00",
    "ended_at": "2026-08-14T10:01:00+00:00",
    "stop_reason": "end_turn",
    "usage": {
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_creation_input_tokens": 200,
        "cache_read_input_tokens": 800,
    },
    "max_tokens": 16000,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
    "duration_ms": 60000,
    "trace": [],
}


def _make_full_trace():
    """Build a multi-turn trace doc with all step types."""
    return {
        "agent_name": "triage-agent",
        "model": "claude-sonnet-4-20250514",
        "started_at": "2026-08-14T10:00:00+00:00",
        "ended_at": "2026-08-14T10:02:00+00:00",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 5000,
            "output_tokens": 2000,
            "cache_creation_input_tokens": 500,
            "cache_read_input_tokens": 3000,
        },
        "max_tokens": 16000,
        "trace_id": "aaaa1111bbbb2222cccc3333dddd4444",
        "duration_ms": 120000,
        "trace": [
            {
                "turn": 0,
                "steps": [
                    {
                        "type": "system",
                        "step": 0,
                        "system_prompt": "You are a triage agent.",
                        "user_prompt": "Analyze this CVE.",
                    },
                    {
                        "type": "scan",
                        "step": 1,
                        "scanned": "system_prompt",
                        "violations": [],
                    },
                ],
                "trace_id": "aaaa1111bbbb2222cccc3333dddd4444",
                "span_id": "1111111111111111aaaaaaaaaaaaaaaa",
                "parent_span_id": "ffffffffffffffff0000000000000000",
                "started_at": "2026-08-14T10:00:00+00:00",
                "ended_at": "2026-08-14T10:00:01+00:00",
                "duration_ms": 1000,
            },
            {
                "turn": 1,
                "steps": [
                    {
                        "type": "input",
                        "step": 0,
                        "messages_count": 3,
                        "compacted": False,
                    },
                    {
                        "type": "response",
                        "step": 1,
                        "text": "I'll search for information.",
                        "model_signal": "tool_use",
                        "usage": {
                            "input_tokens": 2000,
                            "output_tokens": 100,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 1500,
                        },
                        "latency_ms": 3200,
                    },
                    {
                        "type": "tool_call",
                        "step": 2,
                        "name": "bash",
                        "input": {"command": "grep -r CVE src/"},
                    },
                    {
                        "type": "tool_result",
                        "step": 3,
                        "name": "bash",
                        "output": "src/scanner.py:CVE-2024-1234",
                        "latency_ms": 150,
                        "output_bytes": 32,
                    },
                    {
                        "type": "scan",
                        "step": 4,
                        "scanned": "tool_result:bash",
                        "violations": [
                            {"type": "secret_detected", "message": "API key found"}
                        ],
                    },
                ],
                "trace_id": "aaaa1111bbbb2222cccc3333dddd4444",
                "span_id": "2222222222222222bbbbbbbbbbbbbbbb",
                "parent_span_id": "ffffffffffffffff0000000000000000",
                "started_at": "2026-08-14T10:00:01+00:00",
                "ended_at": "2026-08-14T10:00:05+00:00",
                "duration_ms": 4000,
            },
            {
                "turn": 2,
                "steps": [
                    {
                        "type": "input",
                        "step": 0,
                        "messages_count": 5,
                        "compacted": True,
                    },
                    {
                        "type": "compaction",
                        "step": 1,
                        "tokens_before": 50000,
                        "tokens_after": 25000,
                        "method": "summary",
                    },
                    {
                        "type": "response",
                        "step": 2,
                        "text": "Here is my analysis.",
                        "model_signal": "end_turn",
                        "usage": {
                            "input_tokens": 3000,
                            "output_tokens": 1900,
                            "cache_creation_input_tokens": 500,
                            "cache_read_input_tokens": 1500,
                        },
                        "latency_ms": 5000,
                    },
                ],
                "trace_id": "aaaa1111bbbb2222cccc3333dddd4444",
                "span_id": "3333333333333333cccccccccccccccc",
                "parent_span_id": "ffffffffffffffff0000000000000000",
                "started_at": "2026-08-14T10:00:05+00:00",
                "ended_at": "2026-08-14T10:02:00+00:00",
                "duration_ms": 115000,
            },
        ],
    }


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------


class TestTruncateSpanId:
    def test_truncates_32_to_16(self):
        assert (
            _truncate_span_id("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6") == "a1b2c3d4e5f6a7b8"
        )

    def test_short_id_unchanged(self):
        assert _truncate_span_id("abcd1234") == "abcd1234"


class TestIsoToUnixNano:
    def test_valid_utc(self):
        result = _iso_to_unix_nano("2026-08-14T10:00:00+00:00")
        assert result != "0"
        nano = int(result)
        assert nano > 0
        # Round-trip: convert back and verify date
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(nano / 1_000_000_000, tz=timezone.utc)
        assert dt.year == 2026
        assert dt.month == 8
        assert dt.day == 14

    def test_none_returns_zero(self):
        assert _iso_to_unix_nano(None) == "0"

    def test_empty_returns_zero(self):
        assert _iso_to_unix_nano("") == "0"

    def test_invalid_returns_zero(self):
        assert _iso_to_unix_nano("not-a-date") == "0"

    def test_naive_datetime_treated_as_utc(self):
        result = _iso_to_unix_nano("2026-08-14T10:00:00")
        assert result != "0"


class TestDeriveEndNano:
    def test_valid_iso_used_directly(self):
        result = _derive_end_nano(
            "2026-08-14T10:01:00+00:00",
            "1000000000000000000",
            duration_ms=60000,
        )
        assert result != "0"
        assert result != "1000000000000000000"

    def test_missing_iso_falls_back_to_duration_ms(self):
        start = "1000000000000000000"
        result = _derive_end_nano("", start, duration_ms=5000)
        expected = str(int(start) + 5000 * 1_000_000)
        assert result == expected

    def test_missing_iso_falls_back_to_output_tokens(self):
        start = "1000000000000000000"
        result = _derive_end_nano("", start, output_tokens=300)
        start_int = int(start)
        estimated_ms = (300 / 30) * 1000
        expected = str(start_int + int(estimated_ms * 1_000_000))
        assert result == expected

    def test_missing_iso_no_fallback_uses_1ms(self):
        start = "1000000000000000000"
        result = _derive_end_nano("", start)
        expected = str(int(start) + 1_000_000)
        assert result == expected

    def test_zero_start_returns_zero(self):
        assert _derive_end_nano("", "0") == "0"

    def test_duration_ms_takes_priority_over_tokens(self):
        start = "1000000000000000000"
        result = _derive_end_nano("", start, duration_ms=5000, output_tokens=300)
        expected = str(int(start) + 5000 * 1_000_000)
        assert result == expected


class TestMakeAttribute:
    def test_string(self):
        attr = _make_attribute("key", "value")
        assert attr == {"key": "key", "value": {"stringValue": "value"}}

    def test_int(self):
        attr = _make_attribute("key", 42)
        assert attr == {"key": "key", "value": {"intValue": "42"}}

    def test_bool(self):
        attr = _make_attribute("key", True)
        assert attr == {"key": "key", "value": {"boolValue": True}}

    def test_list(self):
        attr = _make_attribute("key", ["a", "b"])
        assert attr["value"]["arrayValue"]["values"] == [
            {"stringValue": "a"},
            {"stringValue": "b"},
        ]

    def test_none_returns_none(self):
        assert _make_attribute("key", None) is None

    def test_float_to_int(self):
        attr = _make_attribute("key", 3.14)
        assert attr == {"key": "key", "value": {"intValue": "3"}}


# ---------------------------------------------------------------------------
# Unit tests — span builders
# ---------------------------------------------------------------------------


class TestMakeRootSpan:
    def test_basic_root_span(self):
        span = _make_root_span(MINIMAL_TRACE_DOC, MINIMAL_TRACE_DOC["trace_id"])
        assert span["name"] == "gen_ai.agent"
        assert span["traceId"] == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        assert "parentSpanId" not in span
        assert span["status"]["code"] == 1  # OK

    def test_root_span_attributes(self):
        span = _make_root_span(MINIMAL_TRACE_DOC, MINIMAL_TRACE_DOC["trace_id"])
        attr_map = {a["key"]: a["value"] for a in span["attributes"]}
        assert attr_map["gen_ai.system"]["stringValue"] == "anthropic"
        assert attr_map["gen_ai.agent.name"]["stringValue"] == "test-agent"
        assert (
            attr_map["gen_ai.request.model"]["stringValue"]
            == "claude-sonnet-4-20250514"
        )

    def test_root_span_no_derivable_totals(self):
        doc = _make_full_trace()
        span = _make_root_span(doc, doc["trace_id"])
        attr_keys = {a["key"] for a in span["attributes"]}
        for key in [
            "gen_ai.usage.input_tokens",
            "gen_ai.usage.output_tokens",
            "gen_ai.usage.cache_read_input_tokens",
            "gen_ai.usage.cache_creation_input_tokens",
            "gen_ai.agent.turn_count",
            "gen_ai.agent.compaction_count",
            "gen_ai.agent.violation_count",
            "gen_ai.agent.violation_types",
            "gen_ai.agent.violation_ids",
        ]:
            assert key not in attr_keys, f"{key} should not be on root span"

    def test_root_span_session_id(self):
        doc = {**MINIMAL_TRACE_DOC, "session_id": "sess-abc"}
        span = _make_root_span(doc, doc["trace_id"])
        attr_map = {a["key"]: a["value"] for a in span["attributes"]}
        assert attr_map["ai_guardian.session_id"]["stringValue"] == "sess-abc"

    def test_root_span_project_name(self):
        doc = {**MINIMAL_TRACE_DOC, "project_name": "my-project"}
        span = _make_root_span(doc, doc["trace_id"])
        attr_map = {a["key"]: a["value"] for a in span["attributes"]}
        assert attr_map["ai_guardian.project.name"]["stringValue"] == "my-project"

    def test_root_span_no_session_id_when_absent(self):
        span = _make_root_span(MINIMAL_TRACE_DOC, MINIMAL_TRACE_DOC["trace_id"])
        attr_keys = {a["key"] for a in span["attributes"]}
        assert "ai_guardian.session_id" not in attr_keys
        assert "ai_guardian.project.name" not in attr_keys

    def test_root_span_hostname(self):
        import platform

        span = _make_root_span(MINIMAL_TRACE_DOC, MINIMAL_TRACE_DOC["trace_id"])
        attr_map = {a["key"]: a["value"] for a in span["attributes"]}
        expected = platform.node()
        if expected:
            assert attr_map["gen_ai.agent.hostname"]["stringValue"] == expected

    def test_error_status(self):
        doc = {**MINIMAL_TRACE_DOC, "stop_reason": "error"}
        span = _make_root_span(doc, doc["trace_id"])
        assert span["status"]["code"] == 2  # ERROR

    def test_root_span_id_from_parent_span_id(self):
        doc = {
            **MINIMAL_TRACE_DOC,
            "trace": [
                {
                    "turn": 0,
                    "steps": [],
                    "parent_span_id": "ffffffffffffffff0000000000000000",
                }
            ],
        }
        span = _make_root_span(doc, doc["trace_id"])
        assert span["spanId"] == "ffffffffffffffff"


class TestMakeTurnSpan:
    def test_turn_span_with_steps(self):
        trace = _make_full_trace()
        turn = trace["trace"][1]  # turn 1 — response + tool_call + tool_result + scan
        spans = _make_turn_span(turn, trace["trace_id"], "rootrootrootrootx")

        # 1 turn span + 1 response + 1 tool_call + 1 tool_result + 1 scan = 5
        assert len(spans) == 5
        assert spans[0]["name"] == "gen_ai.turn"
        assert spans[0]["parentSpanId"] == "rootrootrootrootx"

        names = [s["name"] for s in spans]
        assert "gen_ai.chat" in names
        assert "tool:bash" in names
        assert "tool_result:bash" in names
        assert "gen_ai.security_scan" in names

    def test_turn_span_attributes(self):
        trace = _make_full_trace()
        turn = trace["trace"][1]
        spans = _make_turn_span(turn, trace["trace_id"], "rootrootrootrootx")
        turn_span = spans[0]
        attr_map = {a["key"]: a["value"] for a in turn_span["attributes"]}
        assert attr_map["gen_ai.turn.number"]["intValue"] == "1"
        assert attr_map["gen_ai.turn.messages_count"]["intValue"] == "3"
        assert attr_map["gen_ai.turn.compacted"]["boolValue"] is False

    def test_turn_span_messages_count_growth(self):
        trace = _make_full_trace()
        turn = trace["trace"][2]  # turn 2: messages_count=5
        spans = _make_turn_span(
            turn, trace["trace_id"], "rootrootrootrootx", prev_messages_count=3
        )
        turn_span = spans[0]
        attr_map = {a["key"]: a["value"] for a in turn_span["attributes"]}
        assert attr_map["gen_ai.turn.messages_count_growth"]["intValue"] == "2"

    def test_turn_span_no_growth_without_prev(self):
        trace = _make_full_trace()
        turn = trace["trace"][1]
        spans = _make_turn_span(turn, trace["trace_id"], "rootrootrootrootx")
        turn_span = spans[0]
        attr_keys = {a["key"] for a in turn_span["attributes"]}
        assert "gen_ai.turn.messages_count_growth" not in attr_keys

    def test_system_and_input_steps_skipped_as_child_spans(self):
        trace = _make_full_trace()
        turn = trace["trace"][0]  # turn 0 — system + scan
        spans = _make_turn_span(turn, trace["trace_id"], "rootrootrootrootx")
        names = [s["name"] for s in spans]
        assert "gen_ai.turn" in names
        assert "gen_ai.security_scan" in names
        # system step should NOT produce a child span
        assert all("system" not in n for n in names[1:])


class TestMakeStepSpans:
    def test_response_step(self):
        step = {
            "type": "response",
            "text": "Hello",
            "model_signal": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "latency_ms": 1000,
        }
        spans = _make_step_spans(
            step,
            "trace123456789012345678901234",
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "2026-08-14T10:00:01+00:00",
        )
        assert len(spans) == 1
        assert spans[0]["name"] == "gen_ai.chat"
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["gen_ai.usage.input_tokens"]["intValue"] == "100"
        assert attr_map["gen_ai.response.finish_reasons"]["arrayValue"]["values"] == [
            {"stringValue": "end_turn"}
        ]

    def test_response_step_text_length(self):
        step = {
            "type": "response",
            "text": "Hello world",
            "model_signal": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "latency_ms": 1000,
        }
        spans = _make_step_spans(
            step,
            "trace123456789012345678901234",
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "2026-08-14T10:00:01+00:00",
        )
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["gen_ai.response.text_length"]["intValue"] == "11"

    def test_response_step_text_length_explicit(self):
        step = {
            "type": "response",
            "text_length": 42,
            "model_signal": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        spans = _make_step_spans(
            step,
            "trace123456789012345678901234",
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "2026-08-14T10:00:01+00:00",
        )
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["gen_ai.response.text_length"]["intValue"] == "42"

    def test_response_step_tool_call_count(self):
        step = {
            "type": "response",
            "text": "Using tools",
            "model_signal": "tool_use",
            "tool_call_count": 3,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        spans = _make_step_spans(
            step,
            "trace123456789012345678901234",
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "2026-08-14T10:00:01+00:00",
        )
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["gen_ai.response.tool_call_count"]["intValue"] == "3"

    def test_tool_call_step(self):
        step = {
            "type": "tool_call",
            "name": "read_file",
            "input": {"path": "/etc/passwd"},
        }
        spans = _make_step_spans(
            step,
            "trace123456789012345678901234",
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "2026-08-14T10:00:01+00:00",
        )
        assert len(spans) == 1
        assert spans[0]["name"] == "tool:read_file"
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["tool.name"]["stringValue"] == "read_file"
        assert "path" in attr_map["tool.input"]["stringValue"]

    def test_tool_result_step(self):
        step = {
            "type": "tool_result",
            "name": "bash",
            "output": "ok",
            "latency_ms": 50,
            "output_bytes": 2,
        }
        spans = _make_step_spans(
            step,
            "trace123456789012345678901234",
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "2026-08-14T10:00:01+00:00",
        )
        assert len(spans) == 1
        assert spans[0]["name"] == "tool_result:bash"
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["tool.output_bytes"]["intValue"] == "2"

    def test_tool_result_output_truncated(self):
        step = {
            "type": "tool_result",
            "name": "bash",
            "output": "ok",
            "latency_ms": 50,
            "output_bytes": 2,
            "output_truncated": True,
        }
        spans = _make_step_spans(
            step,
            "trace123456789012345678901234",
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "2026-08-14T10:00:01+00:00",
        )
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["tool.output_truncated"]["boolValue"] is True

    def test_tool_result_output_not_truncated(self):
        step = {
            "type": "tool_result",
            "name": "bash",
            "output": "ok",
            "latency_ms": 50,
            "output_bytes": 2,
            "output_truncated": False,
        }
        spans = _make_step_spans(
            step,
            "trace123456789012345678901234",
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "2026-08-14T10:00:01+00:00",
        )
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["tool.output_truncated"]["boolValue"] is False

    def test_scan_step_with_violations(self):
        step = {
            "type": "scan",
            "scanned": "agent_response",
            "violations": [
                {"type": "prompt_injection", "message": "Injection detected"}
            ],
        }
        spans = _make_step_spans(
            step,
            "trace123456789012345678901234",
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "2026-08-14T10:00:01+00:00",
        )
        assert len(spans) == 1
        assert spans[0]["name"] == "gen_ai.security_scan"
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert (
            attr_map["gen_ai.security_scan.target"]["stringValue"] == "agent_response"
        )
        assert "gen_ai.security_scan.violation_count" not in attr_map
        assert "gen_ai.security_scan.violation_types" not in attr_map
        assert "gen_ai.security_scan.violation_ids" not in attr_map

    def test_compaction_step(self):
        step = {
            "type": "compaction",
            "tokens_before": 50000,
            "tokens_after": 25000,
            "method": "summary",
        }
        spans = _make_step_spans(
            step,
            "trace123456789012345678901234",
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "2026-08-14T10:00:01+00:00",
        )
        assert len(spans) == 1
        assert spans[0]["name"] == "gen_ai.compaction"
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["gen_ai.compaction.tokens_before"]["intValue"] == "50000"
        assert attr_map["gen_ai.compaction.tokens_after"]["intValue"] == "25000"
        assert attr_map["gen_ai.compaction.method"]["stringValue"] == "summary"

    def test_unknown_step_type_produces_no_spans(self):
        step = {"type": "unknown_type"}
        spans = _make_step_spans(
            step,
            "trace123456789012345678901234",
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "2026-08-14T10:00:01+00:00",
        )
        assert spans == []


# ---------------------------------------------------------------------------
# Integration test — full trace conversion
# ---------------------------------------------------------------------------


class TestTraceToOtlpJson:
    def test_minimal_trace(self):
        result = trace_to_otlp_json(MINIMAL_TRACE_DOC)
        assert "resourceSpans" in result
        rs = result["resourceSpans"]
        assert len(rs) == 1
        assert "scopeSpans" in rs[0]
        spans = rs[0]["scopeSpans"][0]["spans"]
        # Only root span for empty trace
        assert len(spans) == 1
        assert spans[0]["name"] == "gen_ai.agent"

    def test_full_trace_span_count(self):
        doc = _make_full_trace()
        result = trace_to_otlp_json(doc)
        spans = result["resourceSpans"][0]["scopeSpans"][0]["spans"]
        # 1 root + 3 turns + steps:
        #   turn0: 1 scan = 1 step span
        #   turn1: 1 response + 1 tool_call + 1 tool_result + 1 scan = 4 step spans
        #   turn2: 1 compaction + 1 response = 2 step spans
        # Total: 1 + 3 + 1 + 4 + 2 = 11
        assert len(spans) == 11

    def test_trace_id_consistent(self):
        doc = _make_full_trace()
        result = trace_to_otlp_json(doc)
        spans = result["resourceSpans"][0]["scopeSpans"][0]["spans"]
        expected = "aaaa1111bbbb2222cccc3333dddd4444"
        for span in spans:
            assert span["traceId"] == expected

    def test_span_hierarchy(self):
        doc = _make_full_trace()
        result = trace_to_otlp_json(doc)
        spans = result["resourceSpans"][0]["scopeSpans"][0]["spans"]

        root = spans[0]
        assert root["name"] == "gen_ai.agent"
        root_id = root["spanId"]
        assert "parentSpanId" not in root

        turn_spans = [s for s in spans if s["name"] == "gen_ai.turn"]
        for ts in turn_spans:
            assert ts["parentSpanId"] == root_id

        step_spans = [
            s for s in spans if s["name"] not in ("gen_ai.agent", "gen_ai.turn")
        ]
        for ss in step_spans:
            assert ss["parentSpanId"] in [ts["spanId"] for ts in turn_spans]

    def test_resource_attributes(self):
        result = trace_to_otlp_json(MINIMAL_TRACE_DOC, service_name="my-service")
        res_attrs = result["resourceSpans"][0]["resource"]["attributes"]
        attr_map = {a["key"]: a["value"] for a in res_attrs}
        assert attr_map["service.name"]["stringValue"] == "my-service"

    def test_scope_name(self):
        result = trace_to_otlp_json(MINIMAL_TRACE_DOC)
        scope = result["resourceSpans"][0]["scopeSpans"][0]["scope"]
        assert scope["name"] == "ai-guardian"

    def test_missing_trace_id_generates_one(self):
        doc = {k: v for k, v in MINIMAL_TRACE_DOC.items() if k != "trace_id"}
        result = trace_to_otlp_json(doc)
        spans = result["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans[0]["traceId"]) == 32

    def test_resource_attributes_param(self):
        result = trace_to_otlp_json(
            MINIMAL_TRACE_DOC,
            resource_attributes={
                "team.name": "AT",
                "pipeline.name": "ao-exterminator",
                "deployment.environment": "dev",
            },
        )
        res_attrs = result["resourceSpans"][0]["resource"]["attributes"]
        attr_map = {a["key"]: a["value"] for a in res_attrs}
        assert attr_map["team.name"]["stringValue"] == "AT"
        assert attr_map["pipeline.name"]["stringValue"] == "ao-exterminator"
        assert attr_map["deployment.environment"]["stringValue"] == "dev"
        assert "service.name" in attr_map
        assert "service.version" in attr_map

    def test_messages_count_growth_across_turns(self):
        doc = _make_full_trace()
        result = trace_to_otlp_json(doc)
        spans = result["resourceSpans"][0]["scopeSpans"][0]["spans"]
        turn_spans = [s for s in spans if s["name"] == "gen_ai.turn"]

        # turn 0: no input step → no messages_count → no growth
        t0_attrs = {a["key"] for a in turn_spans[0]["attributes"]}
        assert "gen_ai.turn.messages_count_growth" not in t0_attrs

        # turn 1: messages_count=3, prev=None → no growth
        t1_attrs = {a["key"] for a in turn_spans[1]["attributes"]}
        assert "gen_ai.turn.messages_count_growth" not in t1_attrs

        # turn 2: messages_count=5, prev=3 → growth=2
        t2_map = {a["key"]: a["value"] for a in turn_spans[2]["attributes"]}
        assert t2_map["gen_ai.turn.messages_count_growth"]["intValue"] == "2"

    def test_output_is_json_serializable(self):
        doc = _make_full_trace()
        result = trace_to_otlp_json(doc)
        serialized = json.dumps(result)
        assert isinstance(serialized, str)
        roundtrip = json.loads(serialized)
        assert roundtrip == result


class TestEndTimeNanoSynthesis:
    """Verify endTimeUnixNano is never '0' when startTimeUnixNano is valid (#1980)."""

    def test_root_span_missing_ended_at_uses_duration_ms(self):
        doc = {
            **MINIMAL_TRACE_DOC,
            "ended_at": None,
            "duration_ms": 60000,
        }
        span = _make_root_span(doc, doc["trace_id"])
        assert span["endTimeUnixNano"] != "0"
        start = int(span["startTimeUnixNano"])
        end = int(span["endTimeUnixNano"])
        assert end == start + 60000 * 1_000_000

    def test_root_span_missing_ended_at_falls_back_to_tokens(self):
        doc = {
            **MINIMAL_TRACE_DOC,
            "ended_at": None,
            "duration_ms": None,
        }
        span = _make_root_span(doc, doc["trace_id"])
        assert span["endTimeUnixNano"] != "0"
        assert int(span["endTimeUnixNano"]) > int(span["startTimeUnixNano"])

    def test_turn_span_missing_ended_at_uses_duration_ms(self):
        turn = {
            "turn": 1,
            "steps": [],
            "span_id": "aaaa111122223333aaaa111122223333",
            "started_at": "2026-08-14T10:00:00+00:00",
            "ended_at": None,
            "duration_ms": 5000,
        }
        spans = _make_turn_span(turn, "trace" * 8, "root12345678root")
        turn_span = spans[0]
        assert turn_span["endTimeUnixNano"] != "0"
        start = int(turn_span["startTimeUnixNano"])
        end = int(turn_span["endTimeUnixNano"])
        assert end == start + 5000 * 1_000_000

    def test_step_without_latency_gets_synthetic_end(self):
        step = {
            "type": "tool_call",
            "name": "bash",
            "input": {"command": "ls"},
        }
        spans = _make_step_spans(
            step,
            "trace" * 8,
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "",
        )
        assert len(spans) == 1
        start = int(spans[0]["startTimeUnixNano"])
        end = int(spans[0]["endTimeUnixNano"])
        assert end == start + 1_000_000  # 1ms synthetic

    def test_response_step_without_latency_estimates_from_tokens(self):
        step = {
            "type": "response",
            "text": "Hello world",
            "model_signal": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 300},
        }
        spans = _make_step_spans(
            step,
            "trace" * 8,
            "parent1234567890",
            "2026-08-14T10:00:00+00:00",
            "",
        )
        assert len(spans) == 1
        start = int(spans[0]["startTimeUnixNano"])
        end = int(spans[0]["endTimeUnixNano"])
        estimated_ms = (300 / 30) * 1000
        assert end == start + int(estimated_ms * 1_000_000)

    def test_full_trace_no_ended_at_all_spans_have_valid_end(self):
        """End-to-end: trace with no ended_at produces zero '0' endTimeUnixNano."""
        doc = _make_full_trace()
        doc["ended_at"] = None
        for turn in doc["trace"]:
            turn["ended_at"] = None
        result = trace_to_otlp_json(doc)
        spans = result["resourceSpans"][0]["scopeSpans"][0]["spans"]
        for span in spans:
            assert (
                span["endTimeUnixNano"] != "0"
            ), f"Span '{span['name']}' has endTimeUnixNano=0"

    def test_make_span_guard_fixes_zero_end(self):
        """_make_span itself prevents endTimeUnixNano=0 when start is valid."""
        span = _make_span(
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id="",
            name="test",
            start_nano="1000000000000000000",
            end_nano="0",
            attributes=[],
        )
        assert span["endTimeUnixNano"] != "0"
        assert int(span["endTimeUnixNano"]) == 1000000000000000000 + 1_000_000

    def test_make_span_guard_skips_when_start_also_zero(self):
        span = _make_span(
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id="",
            name="test",
            start_nano="0",
            end_nano="0",
            attributes=[],
        )
        assert span["endTimeUnixNano"] == "0"


# ---------------------------------------------------------------------------
# CLI handler tests
# ---------------------------------------------------------------------------


class TestHandleTraceCommand:
    def test_export_json_to_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as src:
            json.dump(MINIMAL_TRACE_DOC, src)
            src_path = src.name

        with tempfile.NamedTemporaryFile(suffix=".otlp.json", delete=False) as dst:
            dst_path = dst.name

        try:
            args = MagicMock()
            args.file = src_path
            args.format = "otlp-json"
            args.output = dst_path
            args.endpoint = None
            args.service_name = "ai-guardian"
            args.trace_command = "export"

            result = handle_trace_command(args, MagicMock())
            assert result == 0

            with open(dst_path, "r") as fh:
                otlp = json.load(fh)
            assert "resourceSpans" in otlp
        finally:
            os.unlink(src_path)
            os.unlink(dst_path)

    def test_export_json_to_stdout(self, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as src:
            json.dump(MINIMAL_TRACE_DOC, src)
            src_path = src.name

        try:
            args = MagicMock()
            args.file = src_path
            args.format = "otlp-json"
            args.output = None
            args.endpoint = None
            args.service_name = "ai-guardian"
            args.trace_command = "export"

            result = handle_trace_command(args, MagicMock())
            assert result == 0

            captured = capsys.readouterr()
            otlp = json.loads(captured.out)
            assert "resourceSpans" in otlp
        finally:
            os.unlink(src_path)

    def test_export_file_not_found(self):
        args = MagicMock()
        args.file = "/nonexistent/trace.json"
        args.format = "otlp-json"
        args.output = None
        args.endpoint = None
        args.service_name = "ai-guardian"
        args.trace_command = "export"

        result = handle_trace_command(args, MagicMock())
        assert result == 1

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_export_to_endpoint(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_requests.post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as src:
            json.dump(MINIMAL_TRACE_DOC, src)
            src_path = src.name

        try:
            args = MagicMock()
            args.file = src_path
            args.format = "otlp-json"
            args.output = None
            args.endpoint = "http://localhost:4318"
            args.service_name = "ai-guardian"
            args.trace_command = "export"

            result = handle_trace_command(args, MagicMock())
            assert result == 0
            mock_requests.post.assert_called_once()
            call_kwargs = mock_requests.post.call_args
            assert "/v1/traces" in call_kwargs[0][0]
        finally:
            os.unlink(src_path)

    def test_export_dir_json(self):
        with tempfile.TemporaryDirectory() as src_dir:
            for i in range(3):
                path = os.path.join(src_dir, f"trace_{i}.json")
                with open(path, "w") as fh:
                    doc = {**MINIMAL_TRACE_DOC, "agent_name": f"agent-{i}"}
                    json.dump(doc, fh)

            with tempfile.TemporaryDirectory() as out_dir:
                args = MagicMock()
                args.dir = src_dir
                args.format = "otlp-json"
                args.output = out_dir
                args.service_name = "ai-guardian"
                args.trace_command = "export-dir"

                result = handle_trace_command(args, MagicMock())
                assert result == 0

                out_files = os.listdir(out_dir)
                assert len(out_files) == 3
                for f in out_files:
                    assert f.endswith(".otlp.json")

    def test_no_subcommand_prints_help(self):
        args = MagicMock()
        args.trace_command = None
        parser = MagicMock()

        result = handle_trace_command(args, parser)
        assert result == 0
        parser.print_help.assert_called_once()


# ---------------------------------------------------------------------------
# OtelSpanEmitter tests
# ---------------------------------------------------------------------------


class TestResolveHeaders:
    def test_no_env_no_config(self):
        assert _resolve_headers(None) == {}

    def test_config_headers_only(self):
        result = _resolve_headers({"Authorization": "Bearer tok123"})
        assert result == {"Authorization": "Bearer tok123"}

    def test_env_var_only(self, monkeypatch):
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer envtok,X-Custom=val"
        )
        result = _resolve_headers(None)
        assert result["Authorization"] == "Bearer envtok"
        assert result["X-Custom"] == "val"

    def test_config_overrides_env(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer envtok")
        result = _resolve_headers({"Authorization": "Bearer cfgtok"})
        assert result["Authorization"] == "Bearer cfgtok"

    def test_env_endpoint_override(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://custom:4318")
        emitter = OtelSpanEmitter(
            {"enabled": True, "endpoint": "http://default:4318"},
            "trace123",
            "agent",
            "model",
        )
        assert emitter._endpoint == "http://custom:4318"

    def test_env_service_name_override(self, monkeypatch):
        monkeypatch.setenv("OTEL_SERVICE_NAME", "my-custom-svc")
        emitter = OtelSpanEmitter(
            {"enabled": True},
            "trace123",
            "agent",
            "model",
        )
        assert emitter._service_name == "my-custom-svc"


class TestOtelSpanEmitter:
    def test_disabled_is_noop(self):
        emitter = OtelSpanEmitter({"enabled": False}, "trace123", "agent", "model")
        emitter.on_turn_complete({"turn": 1, "steps": []})
        emitter.on_run_complete(MINIMAL_TRACE_DOC)

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_on_turn_complete_posts(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = OtelSpanEmitter(
            {
                "enabled": True,
                "endpoint": "http://localhost:4318",
                "service_name": "test-svc",
            },
            "aaaa1111bbbb2222cccc3333dddd4444",
            "test-agent",
            "test-model",
        )

        turn_data = _make_full_trace()["trace"][1]
        emitter.on_turn_complete(turn_data)

        mock_requests.post.assert_called_once()
        call_kwargs = mock_requests.post.call_args
        assert "/v1/traces" in call_kwargs[0][0]
        payload = call_kwargs[1]["json"]
        assert "resourceSpans" in payload

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_on_run_complete_posts_root(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = OtelSpanEmitter(
            {
                "enabled": True,
                "endpoint": "http://collector:4318",
            },
            MINIMAL_TRACE_DOC["trace_id"],
            "test-agent",
            "test-model",
        )

        emitter.on_run_complete(MINIMAL_TRACE_DOC)

        mock_requests.post.assert_called_once()
        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans) == 1
        assert spans[0]["name"] == "gen_ai.agent"
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["ai_guardian.span_type"]["stringValue"] == "agent_run"

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_failure_does_not_raise(self, mock_requests):
        mock_requests.post.side_effect = Exception("connection refused")
        emitter = OtelSpanEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"},
            "trace123",
            "agent",
            "model",
        )
        emitter.on_run_complete(MINIMAL_TRACE_DOC)

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_resource_attributes_in_flush(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = OtelSpanEmitter(
            {
                "enabled": True,
                "endpoint": "http://localhost:4318",
                "resource_attributes": {
                    "team.name": "AT",
                    "deployment.environment": "dev",
                },
            },
            "trace123",
            "test-agent",
            "test-model",
        )
        emitter.on_run_complete(MINIMAL_TRACE_DOC)

        payload = mock_requests.post.call_args[1]["json"]
        res_attrs = payload["resourceSpans"][0]["resource"]["attributes"]
        attr_map = {a["key"]: a["value"] for a in res_attrs}
        assert attr_map["team.name"]["stringValue"] == "AT"
        assert attr_map["deployment.environment"]["stringValue"] == "dev"
        assert "service.name" in attr_map

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_metadata_fn_on_turn_complete(self, mock_requests):
        mock_requests.post.return_value = MagicMock()

        def metadata_fn(agent_name, ctx):
            return {"case.id": "AAP-85065", "attempt": ctx["turn"]}

        emitter = OtelSpanEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"},
            "aaaa1111bbbb2222cccc3333dddd4444",
            "test-agent",
            "test-model",
            metadata_fn=metadata_fn,
        )

        turn_data = _make_full_trace()["trace"][1]
        emitter.on_turn_complete(
            turn_data, usage_totals={"input_tokens": 100, "output_tokens": 50}
        )

        payload = mock_requests.post.call_args[1]["json"]
        turn_span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attr_map = {a["key"]: a["value"] for a in turn_span["attributes"]}
        assert attr_map["case.id"]["stringValue"] == "AAP-85065"
        assert attr_map["attempt"]["intValue"] == "1"

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_metadata_fn_on_run_complete(self, mock_requests):
        mock_requests.post.return_value = MagicMock()

        def metadata_fn(agent_name, ctx):
            return {"case.id": "AAP-99999", "final": True}

        emitter = OtelSpanEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"},
            MINIMAL_TRACE_DOC["trace_id"],
            "test-agent",
            "test-model",
            metadata_fn=metadata_fn,
        )
        emitter.on_run_complete(MINIMAL_TRACE_DOC)

        payload = mock_requests.post.call_args[1]["json"]
        root_span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attr_map = {a["key"]: a["value"] for a in root_span["attributes"]}
        assert attr_map["case.id"]["stringValue"] == "AAP-99999"
        assert attr_map["final"]["boolValue"] is True

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_metadata_fn_receives_correct_context(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        captured_contexts = []

        def metadata_fn(agent_name, ctx):
            captured_contexts.append((agent_name, dict(ctx)))
            return {}

        emitter = OtelSpanEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"},
            "trace123",
            "my-agent",
            "claude-sonnet-5",
            metadata_fn=metadata_fn,
        )

        turn_data = _make_full_trace()["trace"][1]
        emitter.on_turn_complete(
            turn_data, usage_totals={"input_tokens": 500, "output_tokens": 200}
        )

        assert len(captured_contexts) == 1
        name, ctx = captured_contexts[0]
        assert name == "my-agent"
        assert ctx["model"] == "claude-sonnet-5"
        assert ctx["turn"] == 1
        assert ctx["usage"] == {"input_tokens": 500, "output_tokens": 200}
        assert "stop_reason" not in ctx

        emitter.on_run_complete(MINIMAL_TRACE_DOC)

        assert len(captured_contexts) == 2
        name, ctx = captured_contexts[1]
        assert name == "my-agent"
        assert ctx["turn"] == 0
        assert ctx["stop_reason"] == "end_turn"
        assert ctx["usage"]["input_tokens"] == 1000

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_metadata_fn_error_does_not_raise(self, mock_requests):
        mock_requests.post.return_value = MagicMock()

        def bad_fn(agent_name, ctx):
            raise ValueError("boom")

        emitter = OtelSpanEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"},
            "trace123",
            "agent",
            "model",
            metadata_fn=bad_fn,
        )
        emitter.on_turn_complete(_make_full_trace()["trace"][1])
        emitter.on_run_complete(MINIMAL_TRACE_DOC)

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_emitter_tracks_messages_count_growth(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = OtelSpanEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"},
            "aaaa1111bbbb2222cccc3333dddd4444",
            "test-agent",
            "test-model",
        )

        trace = _make_full_trace()
        # Send turn 1 (messages_count=3) — no prev → no growth
        emitter.on_turn_complete(trace["trace"][1])
        payload1 = mock_requests.post.call_args[1]["json"]
        turn1_span = payload1["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        t1_keys = {a["key"] for a in turn1_span["attributes"]}
        assert "gen_ai.turn.messages_count_growth" not in t1_keys

        # Send turn 2 (messages_count=5) — prev=3 → growth=2
        emitter.on_turn_complete(trace["trace"][2])
        payload2 = mock_requests.post.call_args[1]["json"]
        turn2_span = payload2["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        t2_map = {a["key"]: a["value"] for a in turn2_span["attributes"]}
        assert t2_map["gen_ai.turn.messages_count_growth"]["intValue"] == "2"

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_metadata_fn_none_is_noop(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = OtelSpanEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"},
            MINIMAL_TRACE_DOC["trace_id"],
            "test-agent",
            "test-model",
            metadata_fn=None,
        )
        emitter.on_run_complete(MINIMAL_TRACE_DOC)

        payload = mock_requests.post.call_args[1]["json"]
        root_span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attr_keys = {a["key"] for a in root_span["attributes"]}
        assert "case.id" not in attr_keys


# ---------------------------------------------------------------------------
# HookOtelEmitter tests
# ---------------------------------------------------------------------------


class TestHookOtelEmitter:
    def test_disabled_is_noop(self):
        emitter = HookOtelEmitter({"enabled": False})
        assert not emitter.enabled
        emitter.record_violation("secret_detected")
        emitter.record_block("Bash", reason="secret in command")
        emitter.flush(session_id="s1")

    def test_enabled_creates_trace(self):
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        assert emitter.enabled
        assert len(emitter._trace_id) == 32
        assert len(emitter._root_span_id) == 16

    def test_record_violation_adds_child_span(self):
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.record_violation(
            "secret_detected",
            severity="critical",
            tool_name="Bash",
            violation_id="vid-123",
            scanner="secret_scanning",
        )
        assert len(emitter._child_spans) == 1
        span = emitter._child_spans[0]
        assert span["name"] == "ai_guardian.violation"
        attr_map = {a["key"]: a["value"] for a in span["attributes"]}
        assert (
            attr_map["ai_guardian.violation_type"]["stringValue"] == "secret_detected"
        )
        assert attr_map["ai_guardian.severity"]["stringValue"] == "critical"
        assert attr_map["tool.name"]["stringValue"] == "Bash"
        assert emitter._violation_count == 1

    def test_record_block_adds_child_span(self):
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.record_block(
            "Bash", reason="secret in command", scanner="secret_scanning"
        )
        assert len(emitter._child_spans) == 1
        span = emitter._child_spans[0]
        assert span["name"] == "ai_guardian.block"
        attr_map = {a["key"]: a["value"] for a in span["attributes"]}
        assert attr_map["tool.name"]["stringValue"] == "Bash"
        assert attr_map["ai_guardian.reason"]["stringValue"] == "secret in command"
        assert emitter._block_count == 1

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_posts_all_spans(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.record_violation("prompt_injection", tool_name="Read")
        emitter.record_block("Bash", reason="exfil detected")
        emitter.flush(session_id="session-abc", adapter_name="Claude Code")

        mock_requests.post.assert_called_once()
        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans) == 3  # root + violation + block

        root = spans[0]
        assert root["name"] == "ai_guardian.session"
        attr_map = {a["key"]: a["value"] for a in root["attributes"]}
        assert attr_map["ai_guardian.session_id"]["stringValue"] == "session-abc"
        assert attr_map["ai_guardian.adapter"]["stringValue"] == "Claude Code"
        assert attr_map["ai_guardian.violation_count"]["intValue"] == "1"
        assert attr_map["ai_guardian.block_count"]["intValue"] == "1"

        assert spans[1]["name"] == "ai_guardian.violation"
        assert spans[2]["name"] == "ai_guardian.block"
        assert emitter._child_spans == []

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_empty_session(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.flush(session_id="empty-session")

        mock_requests.post.assert_called_once()
        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans) == 1
        assert spans[0]["name"] == "ai_guardian.session"

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_failure_is_silent(self, mock_requests):
        mock_requests.post.side_effect = ConnectionError("refused")
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.record_violation("secret_detected")
        emitter.flush(session_id="s1")

    def test_env_var_overrides(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://custom:9999")
        monkeypatch.setenv("OTEL_SERVICE_NAME", "custom-svc")
        emitter = HookOtelEmitter({"enabled": True})
        assert emitter._endpoint == "http://custom:9999"
        assert emitter._service_name == "custom-svc"

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_resource_attributes_included(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {
                "enabled": True,
                "endpoint": "http://localhost:4318",
                "resource_attributes": {"team.name": "security"},
            }
        )
        emitter.flush(session_id="s1")

        payload = mock_requests.post.call_args[1]["json"]
        res_attrs = payload["resourceSpans"][0]["resource"]["attributes"]
        attr_map = {a["key"]: a["value"] for a in res_attrs}
        assert attr_map["team.name"]["stringValue"] == "security"

    def test_record_violation_with_details(self):
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.record_violation(
            "code_security",
            details={"file_path": "/tmp/bad.py", "line_number": 42},
        )
        span = emitter._child_spans[0]
        attr_map = {a["key"]: a["value"] for a in span["attributes"]}
        assert attr_map["ai_guardian.detail.file_path"]["stringValue"] == "/tmp/bad.py"
        assert attr_map["ai_guardian.detail.line_number"]["intValue"] == "42"

    def test_record_session_start_stores_adapter(self):
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.record_session_start(adapter_name="Claude Code")
        assert emitter._adapter_name == "Claude Code"

    def test_record_session_start_stores_project_name(self):
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.record_session_start(project_name="my-project")
        assert emitter._project_name == "my-project"

    def test_record_session_start_disabled_is_noop(self):
        emitter = HookOtelEmitter({"enabled": False})
        emitter.record_session_start(adapter_name="Claude Code")
        assert not hasattr(emitter, "_adapter_name") or emitter._adapter_name is None

    def test_record_hook_event_increments_count(self):
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        assert emitter._hook_event_count == 0
        emitter.record_hook_event()
        emitter.record_hook_event()
        assert emitter._hook_event_count == 2

    def test_record_hook_event_disabled_is_noop(self):
        emitter = HookOtelEmitter({"enabled": False})
        emitter.record_hook_event()

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_uses_stored_adapter_name(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.record_session_start(adapter_name="Gemini CLI")
        emitter.flush(session_id="s1")

        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        root = spans[0]
        attr_map = {a["key"]: a["value"] for a in root["attributes"]}
        assert attr_map["ai_guardian.adapter"]["stringValue"] == "Gemini CLI"

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_explicit_adapter_overrides_stored(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.record_session_start(adapter_name="stored")
        emitter.flush(session_id="s1", adapter_name="explicit")

        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        root = spans[0]
        attr_map = {a["key"]: a["value"] for a in root["attributes"]}
        assert attr_map["ai_guardian.adapter"]["stringValue"] == "explicit"

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_includes_hook_event_count(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.record_hook_event()
        emitter.record_hook_event()
        emitter.record_hook_event()
        emitter.flush(session_id="s1")

        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        root = spans[0]
        attr_map = {a["key"]: a["value"] for a in root["attributes"]}
        assert attr_map["ai_guardian.hook_event_count"]["intValue"] == "3"

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_clean_session_produces_root_span(self, mock_requests):
        """Clean session (no violations) should still flush a root span."""
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.record_session_start(adapter_name="Claude Code")
        emitter.record_hook_event()
        emitter.flush(session_id="clean-session")

        mock_requests.post.assert_called_once()
        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans) == 1
        root = spans[0]
        assert root["name"] == "ai_guardian.session"
        attr_map = {a["key"]: a["value"] for a in root["attributes"]}
        assert attr_map["ai_guardian.session_id"]["stringValue"] == "clean-session"
        assert attr_map["ai_guardian.adapter"]["stringValue"] == "Claude Code"
        assert attr_map["ai_guardian.violation_count"]["intValue"] == "0"
        assert attr_map["ai_guardian.block_count"]["intValue"] == "0"
        assert attr_map["ai_guardian.hook_event_count"]["intValue"] == "1"

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_includes_project_name(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.record_session_start(
            adapter_name="Claude Code", project_name="ai-guardian"
        )
        emitter.flush(session_id="s1")

        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        root = spans[0]
        attr_map = {a["key"]: a["value"] for a in root["attributes"]}
        assert attr_map["ai_guardian.project.name"]["stringValue"] == "ai-guardian"

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_no_project_name_when_not_set(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.flush(session_id="s1")

        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        root = spans[0]
        attr_keys = {a["key"] for a in root["attributes"]}
        assert "ai_guardian.project.name" not in attr_keys


# ---------------------------------------------------------------------------
# Config loader reads from top-level otel (#1998)
# ---------------------------------------------------------------------------


class TestLoadOtelConfigTopLevel:
    @patch("ai_guardian.config.loaders._load_config_file")
    def test_reads_top_level_otel(self, mock_load):
        mock_load.return_value = (
            {"otel": {"enabled": True, "endpoint": "http://grafana:4318"}},
            None,
        )
        result = _load_otel_config()
        assert result["enabled"] is True
        assert result["endpoint"] == "http://grafana:4318"

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_returns_default_when_no_otel(self, mock_load):
        mock_load.return_value = ({"sdk": {}}, None)
        result = _load_otel_config()
        assert result == {"enabled": False}

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_returns_default_on_error(self, mock_load):
        mock_load.return_value = (None, "file not found")
        result = _load_otel_config()
        assert result == {"enabled": False}

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_ignores_sdk_otel(self, mock_load):
        """Old sdk.otel path should no longer be read."""
        mock_load.return_value = (
            {"sdk": {"otel": {"enabled": True}}},
            None,
        )
        result = _load_otel_config()
        assert result == {"enabled": False}


# ---------------------------------------------------------------------------
# DaemonState OTEL integration (#1998)
# ---------------------------------------------------------------------------


class TestDaemonStateOtel:
    @patch("ai_guardian.config.loaders._load_config_file")
    def test_get_otel_emitter_creates_emitter(self, mock_load):
        mock_load.return_value = (
            {"otel": {"enabled": True, "endpoint": "http://localhost:4318"}},
            None,
        )
        from ai_guardian.daemon.state import DaemonState

        state = DaemonState.__new__(DaemonState)
        state._lock = __import__("threading").Lock()
        state._otel_emitters = {}
        state._session_open_counts = {}

        emitter = state.get_otel_emitter("session-1")
        assert emitter is not None
        assert emitter.enabled
        assert emitter._session_sequence == 1
        assert state.get_otel_emitter("session-1") is emitter

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_get_otel_emitter_returns_none_when_disabled(self, mock_load):
        mock_load.return_value = ({"otel": {"enabled": False}}, None)
        from ai_guardian.daemon.state import DaemonState

        state = DaemonState.__new__(DaemonState)
        state._lock = __import__("threading").Lock()
        state._otel_emitters = {}
        state._session_open_counts = {}

        assert state.get_otel_emitter("session-1") is None

    @patch("ai_guardian.scanners.otel_exporter.requests")
    @patch("ai_guardian.config.loaders._load_config_file")
    def test_flush_otel_emitter(self, mock_load, mock_requests):
        mock_load.return_value = (
            {"otel": {"enabled": True, "endpoint": "http://localhost:4318"}},
            None,
        )
        mock_requests.post.return_value = MagicMock()
        from ai_guardian.daemon.state import DaemonState

        state = DaemonState.__new__(DaemonState)
        state._lock = __import__("threading").Lock()
        state._otel_emitters = {}
        state._session_open_counts = {}

        emitter = state.get_otel_emitter("session-1")
        emitter.record_violation("secret_detected")
        state.flush_otel_emitter("session-1", adapter_name="Claude Code")

        mock_requests.post.assert_called_once()
        assert "session-1" not in state._otel_emitters

    @patch("ai_guardian.scanners.otel_exporter.requests")
    @patch("ai_guardian.config.loaders._load_config_file")
    def test_session_sequence_increments_on_reopen(self, mock_load, mock_requests):
        mock_load.return_value = (
            {"otel": {"enabled": True, "endpoint": "http://localhost:4318"}},
            None,
        )
        mock_requests.post.return_value = MagicMock()
        from ai_guardian.daemon.state import DaemonState

        state = DaemonState.__new__(DaemonState)
        state._lock = __import__("threading").Lock()
        state._otel_emitters = {}
        state._session_open_counts = {}

        em1 = state.get_otel_emitter("session-1")
        assert em1._session_sequence == 1
        state.flush_otel_emitter("session-1")

        em2 = state.get_otel_emitter("session-1")
        assert em2._session_sequence == 2
        assert em2 is not em1

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_includes_session_sequence(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"},
            session_sequence=3,
        )
        emitter.flush(session_id="s1")

        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        root = spans[0]
        attr_map = {a["key"]: a["value"] for a in root["attributes"]}
        assert attr_map["ai_guardian.session_sequence"]["intValue"] == "3"


# ---------------------------------------------------------------------------
# HookOtelEmitter token usage from transcript (#2011)
# ---------------------------------------------------------------------------


class TestHookOtelEmitterTokenUsage:
    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_includes_token_usage(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        token_usage = {
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_read_input_tokens": 800,
            "cache_creation_input_tokens": 200,
        }
        emitter.flush(session_id="s1", token_usage=token_usage)

        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        root = spans[0]
        attr_map = {a["key"]: a["value"] for a in root["attributes"]}
        assert attr_map["gen_ai.usage.input_tokens"]["intValue"] == "1000"
        assert attr_map["gen_ai.usage.output_tokens"]["intValue"] == "500"
        assert attr_map["gen_ai.usage.cache_read_input_tokens"]["intValue"] == "800"
        assert attr_map["gen_ai.usage.cache_creation_input_tokens"]["intValue"] == "200"

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_without_token_usage_has_no_gen_ai_attrs(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        emitter.flush(session_id="s1")

        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        root = spans[0]
        attr_keys = {a["key"] for a in root["attributes"]}
        assert "gen_ai.usage.input_tokens" not in attr_keys

    @patch("ai_guardian.scanners.otel_exporter.requests")
    def test_flush_with_partial_token_usage(self, mock_requests):
        mock_requests.post.return_value = MagicMock()
        emitter = HookOtelEmitter(
            {"enabled": True, "endpoint": "http://localhost:4318"}
        )
        token_usage = {"input_tokens": 100, "output_tokens": 50}
        emitter.flush(session_id="s1", token_usage=token_usage)

        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        root = spans[0]
        attr_map = {a["key"]: a["value"] for a in root["attributes"]}
        assert attr_map["gen_ai.usage.input_tokens"]["intValue"] == "100"
        assert attr_map["gen_ai.usage.output_tokens"]["intValue"] == "50"
        assert "gen_ai.usage.cache_read_input_tokens" not in attr_map

    @patch("ai_guardian.scanners.otel_exporter.requests")
    @patch("ai_guardian.config.loaders._load_config_file")
    def test_daemon_state_passes_token_usage(self, mock_load, mock_requests):
        mock_load.return_value = (
            {"otel": {"enabled": True, "endpoint": "http://localhost:4318"}},
            None,
        )
        mock_requests.post.return_value = MagicMock()
        from ai_guardian.daemon.state import DaemonState

        state = DaemonState.__new__(DaemonState)
        state._lock = __import__("threading").Lock()
        state._otel_emitters = {}
        state._session_open_counts = {}

        emitter = state.get_otel_emitter("session-1")
        token_usage = {"input_tokens": 2000, "output_tokens": 300}
        state.flush_otel_emitter(
            "session-1", adapter_name="Claude Code", token_usage=token_usage
        )

        payload = mock_requests.post.call_args[1]["json"]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        root = spans[0]
        attr_map = {a["key"]: a["value"] for a in root["attributes"]}
        assert attr_map["gen_ai.usage.input_tokens"]["intValue"] == "2000"
        assert attr_map["gen_ai.usage.output_tokens"]["intValue"] == "300"


class TestParseTranscriptTokenUsage:
    def test_sums_usage_from_jsonl(self, tmp_path):
        from ai_guardian.scanners.transcript.common import parse_transcript_token_usage

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "cache_read_input_tokens": 80,
                            "cache_creation_input_tokens": 20,
                        }
                    },
                }
            ),
            json.dumps({"type": "human", "message": {"content": "hello"}}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "usage": {
                            "input_tokens": 200,
                            "output_tokens": 100,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 50,
                        }
                    },
                }
            ),
        ]
        transcript.write_text("\n".join(lines))

        result = parse_transcript_token_usage(str(transcript))
        assert result == {
            "input_tokens": 300,
            "output_tokens": 150,
            "cache_read_input_tokens": 80,
            "cache_creation_input_tokens": 70,
        }

    def test_returns_none_for_missing_file(self):
        from ai_guardian.scanners.transcript.common import parse_transcript_token_usage

        assert parse_transcript_token_usage("/nonexistent/path.jsonl") is None

    def test_returns_none_for_no_usage_data(self, tmp_path):
        from ai_guardian.scanners.transcript.common import parse_transcript_token_usage

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps({"type": "human", "message": {"content": "hi"}})
        )
        assert parse_transcript_token_usage(str(transcript)) is None

    def test_handles_top_level_usage(self, tmp_path):
        from ai_guardian.scanners.transcript.common import parse_transcript_token_usage

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps({"usage": {"input_tokens": 42, "output_tokens": 10}})
        )
        result = parse_transcript_token_usage(str(transcript))
        assert result["input_tokens"] == 42
        assert result["output_tokens"] == 10

    def test_skips_zero_values(self, tmp_path):
        from ai_guardian.scanners.transcript.common import parse_transcript_token_usage

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "usage": {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                        }
                    },
                }
            )
        )
        assert parse_transcript_token_usage(str(transcript)) is None

    def test_handles_malformed_lines(self, tmp_path):
        from ai_guardian.scanners.transcript.common import parse_transcript_token_usage

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            "not json",
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"usage": {"input_tokens": 50, "output_tokens": 25}},
                }
            ),
            "",
        ]
        transcript.write_text("\n".join(lines))
        result = parse_transcript_token_usage(str(transcript))
        assert result["input_tokens"] == 50
        assert result["output_tokens"] == 25

    def test_returns_none_for_empty_path(self):
        from ai_guardian.scanners.transcript.common import parse_transcript_token_usage

        assert parse_transcript_token_usage("") is None
        assert parse_transcript_token_usage(None) is None
