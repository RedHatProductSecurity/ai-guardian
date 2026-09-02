"""Tests for the trace viewer module (daemon/traces.py)."""

import json
import os
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from ai_guardian.daemon.traces import (
    _STALE_THRESHOLD_SECONDS,
    _finalize_stale_trace,
    _meta_path,
    build_trace_doc,
    compute_token_summary,
    estimate_cost,
    group_traces_by_run,
    list_traces,
    pushed_trace_to_summary,
    read_trace_detail,
    validate_filename,
    write_trace_file,
    write_trace_meta,
)


@pytest.fixture
def trace_dir(tmp_path):
    """Create a temporary trace directory with sample files."""
    d = tmp_path / "agents-trace"
    d.mkdir()
    return d


def _write_trace(trace_dir, filename, doc):
    filepath = trace_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    return filepath


def _sample_trace_doc(
    agent_name="test-agent",
    model="claude-sonnet-5",
    stop_reason="end_turn",
    turns=2,
):
    trace = []
    for i in range(turns):
        steps = [
            {"type": "input", "step": 0, "messages_count": 1},
            {
                "type": "response",
                "step": 1,
                "text": f"Response {i}",
                "model_signal": "end_turn",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 10,
                    "cache_creation_input_tokens": 5,
                },
            },
            {
                "type": "scan",
                "step": 2,
                "scanned": "response",
                "violations": [],
            },
        ]
        trace.append({"turn": i, "steps": steps})

    return {
        "agent_name": agent_name,
        "model": model,
        "started_at": "2026-08-13T10:30:00+00:00",
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": 200,
            "output_tokens": 100,
            "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 10,
        },
        "trace": trace,
    }


class TestSharedTraceHelpers:
    def test_build_trace_doc_includes_common_fields_and_extras(self):
        trace = [{"turn": 1, "steps": []}]

        doc = build_trace_doc(
            agent_name="test-agent",
            model="test-model",
            started_at="2026-09-02T12:00:00+00:00",
            stop_reason="end_turn",
            usage=None,
            project_name="my-project",
            trace=trace,
            ended_at="2026-09-02T12:01:00+00:00",
            run_id="run-123",
        )

        assert doc == {
            "agent_name": "test-agent",
            "model": "test-model",
            "started_at": "2026-09-02T12:00:00+00:00",
            "stop_reason": "end_turn",
            "usage": {},
            "project_name": "my-project",
            "trace": trace,
            "ended_at": "2026-09-02T12:01:00+00:00",
            "run_id": "run-123",
        }

    def test_write_trace_file_atomically_writes_trace_and_meta(self, tmp_path):
        filepath = tmp_path / "nested" / "trace.json"
        doc = _sample_trace_doc()
        doc["serialized_at"] = datetime(2026, 9, 2, tzinfo=timezone.utc)

        with patch("ai_guardian.daemon.traces.os.replace", wraps=os.replace) as replace:
            write_trace_file(str(filepath), doc)

        replace.assert_called_once_with(str(filepath) + ".tmp", str(filepath))
        assert not (tmp_path / "nested" / "trace.json.tmp").exists()
        with open(filepath, "r", encoding="utf-8") as fh:
            written = json.load(fh)
        assert written["agent_name"] == "test-agent"
        assert written["serialized_at"] == "2026-09-02 00:00:00+00:00"

        with open(_meta_path(str(filepath)), "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        assert meta["agent_name"] == "test-agent"
        assert meta["total_turns"] == 2

    def test_write_trace_file_replaces_existing_file(self, tmp_path):
        filepath = tmp_path / "trace.json"
        filepath.write_text("stale", encoding="utf-8")

        write_trace_file(str(filepath), _sample_trace_doc(agent_name="replacement"))

        with open(filepath, "r", encoding="utf-8") as fh:
            assert json.load(fh)["agent_name"] == "replacement"


class TestValidateFilename:
    def test_valid_filename(self):
        assert validate_filename("my-agent_20260813-103000_a1b2c3d4.json")

    def test_valid_with_underscores(self):
        assert validate_filename("test_agent_20260813-103000_abcdef12.json")

    def test_rejects_path_traversal(self):
        assert not validate_filename("../etc/passwd")

    def test_rejects_absolute_path(self):
        assert not validate_filename("/etc/passwd")

    def test_accepts_subdir_path(self):
        assert validate_filename("subdir/my-agent_20260813-103000_a1b2c3d4.json")

    def test_rejects_backslash(self):
        assert not validate_filename("subdir\\trace.json")

    def test_rejects_empty(self):
        assert not validate_filename("")

    def test_rejects_none(self):
        assert not validate_filename(None)

    def test_rejects_non_json(self):
        assert not validate_filename("my-agent_20260813-103000_a1b2c3d4.txt")


class TestListTraces:
    def test_empty_directory(self, trace_dir):
        result = list_traces(str(trace_dir))
        assert result == []

    def test_nonexistent_directory(self, tmp_path):
        result = list_traces(str(tmp_path / "nonexistent"))
        assert result == []

    def test_lists_valid_traces(self, trace_dir):
        doc = _sample_trace_doc()
        _write_trace(trace_dir, "test-agent_20260813-103000_a1b2c3d4.json", doc)

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        assert result[0]["agent_name"] == "test-agent"
        assert result[0]["model"] == "claude-sonnet-5"
        assert result[0]["stop_reason"] == "end_turn"
        assert result[0]["is_active"] is False
        assert result[0]["total_turns"] == 2

    def test_filters_by_agent_name(self, trace_dir):
        doc1 = _sample_trace_doc(agent_name="agent-a")
        doc2 = _sample_trace_doc(agent_name="agent-b")
        _write_trace(trace_dir, "agent-a_20260813-103000_a1b2c3d4.json", doc1)
        _write_trace(trace_dir, "agent-b_20260813-104000_b2c3d4e5.json", doc2)

        result = list_traces(str(trace_dir), agent_name="agent-a")
        assert len(result) == 1
        assert result[0]["agent_name"] == "agent-a"

    def test_sorted_by_started_at_descending(self, trace_dir):
        doc1 = _sample_trace_doc(agent_name="first")
        doc1["started_at"] = "2026-08-13T10:00:00+00:00"
        doc2 = _sample_trace_doc(agent_name="second")
        doc2["started_at"] = "2026-08-13T11:00:00+00:00"

        _write_trace(trace_dir, "first_20260813-100000_a1b2c3d4.json", doc1)
        _write_trace(trace_dir, "second_20260813-110000_b2c3d4e5.json", doc2)

        result = list_traces(str(trace_dir))
        assert len(result) == 2
        assert result[0]["agent_name"] == "second"
        assert result[1]["agent_name"] == "first"

    def test_skips_invalid_json(self, trace_dir):
        (trace_dir / "bad_20260813-103000_a1b2c3d4.json").write_text("not json")
        doc = _sample_trace_doc()
        _write_trace(trace_dir, "good_20260813-103000_b2c3d4e5.json", doc)

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        assert result[0]["agent_name"] == "test-agent"

    def test_active_trace(self, trace_dir):
        doc = _sample_trace_doc(stop_reason="in_progress")
        _write_trace(trace_dir, "active_20260813-103000_a1b2c3d4.json", doc)

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        assert result[0]["is_active"] is True

    def test_multiple_directories(self, tmp_path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        doc1 = _sample_trace_doc(agent_name="from-dir1")
        doc2 = _sample_trace_doc(agent_name="from-dir2")
        _write_trace(dir1, "agent1_20260813-100000_a1b2c3d4.json", doc1)
        _write_trace(dir2, "agent2_20260813-110000_b2c3d4e5.json", doc2)

        result = list_traces([str(dir1), str(dir2)])
        assert len(result) == 2

    def test_deduplicates_across_directories(self, tmp_path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        doc = _sample_trace_doc()
        filename = "same_20260813-103000_a1b2c3d4.json"
        _write_trace(dir1, filename, doc)
        _write_trace(dir2, filename, doc)

        result = list_traces([str(dir1), str(dir2)])
        assert len(result) == 1

    def test_counts_violations(self, trace_dir):
        doc = _sample_trace_doc()
        doc["trace"][0]["steps"][2]["violations"] = [
            {"type": "secret_detected", "message": "API key found"}
        ]
        _write_trace(trace_dir, "v_20260813-103000_a1b2c3d4.json", doc)

        result = list_traces(str(trace_dir))
        assert result[0]["violation_count"] == 1

    def test_scans_subdirectories(self, trace_dir):
        subdir = trace_dir / "run-001"
        subdir.mkdir()
        doc = _sample_trace_doc(agent_name="nested")
        _write_trace(subdir, "nested_20260813-103000_a1b2c3d4.json", doc)

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        assert result[0]["agent_name"] == "nested"
        assert "run-001" in result[0]["filename"]

    def test_limit_truncates_results(self, trace_dir):
        for i in range(5):
            doc = _sample_trace_doc(agent_name=f"agent-{i}")
            doc["started_at"] = f"2026-08-13T1{i}:00:00+00:00"
            _write_trace(trace_dir, f"agent-{i}_20260813-1{i}0000_a{i}b2c3d4.json", doc)

        result = list_traces(str(trace_dir), limit=3)
        assert len(result) == 3
        assert result[0]["agent_name"] == "agent-4"

    def test_limit_none_returns_all(self, trace_dir):
        for i in range(3):
            doc = _sample_trace_doc(agent_name=f"agent-{i}")
            _write_trace(trace_dir, f"agent-{i}_20260813-10{i}000_a{i}b2c3d4.json", doc)

        result = list_traces(str(trace_dir), limit=None)
        assert len(result) == 3

    def test_limit_larger_than_count_returns_all(self, trace_dir):
        doc = _sample_trace_doc()
        _write_trace(trace_dir, "only_20260813-103000_a1b2c3d4.json", doc)

        result = list_traces(str(trace_dir), limit=100)
        assert len(result) == 1


class TestReadTraceDetail:
    def test_reads_full_trace(self, trace_dir):
        doc = _sample_trace_doc()
        _write_trace(trace_dir, "test-agent_20260813-103000_a1b2c3d4.json", doc)

        result = read_trace_detail(
            str(trace_dir), "test-agent_20260813-103000_a1b2c3d4.json"
        )
        assert result is not None
        assert result["agent_name"] == "test-agent"
        assert "computed" in result
        assert "per_turn_tokens" in result["computed"]
        assert "cost_estimate_usd" in result["computed"]
        assert "cache_hit_ratio" in result["computed"]

    def test_returns_none_for_invalid_filename(self, trace_dir):
        result = read_trace_detail(str(trace_dir), "../etc/passwd")
        assert result is None

    def test_returns_none_for_missing_file(self, trace_dir):
        result = read_trace_detail(
            str(trace_dir), "missing_20260813-103000_a1b2c3d4.json"
        )
        assert result is None

    def test_active_flag(self, trace_dir):
        doc = _sample_trace_doc(stop_reason="in_progress")
        _write_trace(trace_dir, "active_20260813-103000_a1b2c3d4.json", doc)

        result = read_trace_detail(
            str(trace_dir), "active_20260813-103000_a1b2c3d4.json"
        )
        assert result["is_active"] is True

    def test_violation_extraction(self, trace_dir):
        doc = _sample_trace_doc()
        doc["trace"][0]["steps"][2]["violations"] = [
            {"type": "secret_detected", "message": "API key found"}
        ]
        _write_trace(trace_dir, "v_20260813-103000_a1b2c3d4.json", doc)

        result = read_trace_detail(str(trace_dir), "v_20260813-103000_a1b2c3d4.json")
        assert result["computed"]["violation_count"] == 1
        assert len(result["computed"]["violations"]) == 1
        assert result["computed"]["violations"][0]["turn"] == 0

    def test_searches_multiple_directories(self, tmp_path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        doc = _sample_trace_doc(agent_name="in-dir2")
        filename = "agent_20260813-103000_a1b2c3d4.json"
        _write_trace(dir2, filename, doc)

        result = read_trace_detail([str(dir1), str(dir2)], filename)
        assert result is not None
        assert result["agent_name"] == "in-dir2"


class TestComputeTokenSummary:
    def test_per_turn_breakdown(self):
        trace = [
            {
                "turn": 0,
                "steps": [
                    {
                        "type": "response",
                        "step": 1,
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "cache_read_input_tokens": 10,
                            "cache_creation_input_tokens": 5,
                        },
                    }
                ],
            }
        ]
        usage = {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 10,
            "cache_creation_input_tokens": 5,
        }
        result = compute_token_summary(trace, usage, "claude-sonnet-5")
        assert len(result["per_turn_tokens"]) == 1
        assert result["per_turn_tokens"][0]["input_tokens"] == 100
        assert result["per_turn_tokens"][0]["output_tokens"] == 50

    def test_cache_hit_ratio(self):
        usage = {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 50,
            "cache_creation_input_tokens": 0,
        }
        result = compute_token_summary([], usage, "claude-sonnet-5")
        assert result["cache_hit_ratio"] == pytest.approx(50 / 150, abs=0.01)

    def test_zero_input_tokens(self):
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        result = compute_token_summary([], usage, "claude-sonnet-5")
        assert result["cache_hit_ratio"] == 0.0


class TestEstimateCost:
    def test_known_model(self):
        usage = {
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        cost = estimate_cost("claude-sonnet-5", usage)
        assert cost == pytest.approx(3.0 + 15.0, abs=0.01)

    def test_unknown_model(self):
        usage = {"input_tokens": 1000, "output_tokens": 500}
        cost = estimate_cost("unknown-model-v1", usage)
        assert cost == 0.0

    def test_cache_pricing(self):
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 1_000_000,
            "cache_creation_input_tokens": 1_000_000,
        }
        cost = estimate_cost("claude-sonnet-5", usage)
        cache_read_cost = 3.0 * 0.1
        cache_create_cost = 3.0 * 1.25
        assert cost == pytest.approx(cache_read_cost + cache_create_cost, abs=0.01)


class TestMetaSidecar:
    def test_meta_path_derivation(self):
        assert _meta_path("/tmp/agent_20260813-103000_abc.json") == (
            "/tmp/agent_20260813-103000_abc.meta.json"
        )

    def test_write_and_read_meta(self, trace_dir):
        doc = _sample_trace_doc()
        filepath = str(_write_trace(trace_dir, "m_20260813-103000_a1b2c3d4.json", doc))
        write_trace_meta(filepath, doc)

        meta_fp = _meta_path(filepath)
        assert os.path.isfile(meta_fp)

        with open(meta_fp, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        assert meta["agent_name"] == "test-agent"
        assert meta["model"] == "claude-sonnet-5"
        assert meta["total_turns"] == 2
        assert meta["violation_count"] == 0
        assert meta["usage"]["input_tokens"] == 200

    def test_list_traces_prefers_meta(self, trace_dir):
        doc = _sample_trace_doc()
        filepath = str(_write_trace(trace_dir, "m_20260813-103000_a1b2c3d4.json", doc))
        write_trace_meta(filepath, doc)

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        assert result[0]["agent_name"] == "test-agent"
        assert result[0]["total_turns"] == 2

    def test_list_traces_falls_back_without_meta(self, trace_dir):
        doc = _sample_trace_doc()
        _write_trace(trace_dir, "n_20260813-103000_a1b2c3d4.json", doc)

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        assert result[0]["agent_name"] == "test-agent"
        assert result[0]["total_turns"] == 2

    def test_meta_not_listed_as_trace(self, trace_dir):
        doc = _sample_trace_doc()
        filepath = str(_write_trace(trace_dir, "x_20260813-103000_a1b2c3d4.json", doc))
        write_trace_meta(filepath, doc)

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        filenames = [r["filename"] for r in result]
        assert not any(".meta.json" in f for f in filenames)

    def test_meta_with_violations(self, trace_dir):
        doc = _sample_trace_doc()
        doc["trace"][0]["steps"][2]["violations"] = [
            {"type": "secret_detected", "message": "key found"}
        ]
        filepath = str(_write_trace(trace_dir, "v_20260813-103000_a1b2c3d4.json", doc))
        write_trace_meta(filepath, doc)

        result = list_traces(str(trace_dir))
        assert result[0]["violation_count"] == 1

    def test_corrupt_meta_falls_back_to_full_parse(self, trace_dir):
        doc = _sample_trace_doc()
        filepath = str(_write_trace(trace_dir, "c_20260813-103000_a1b2c3d4.json", doc))
        meta_fp = _meta_path(filepath)
        with open(meta_fp, "w") as fh:
            fh.write("not json")

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        assert result[0]["agent_name"] == "test-agent"


class TestStaleTraceDetection:
    def test_stale_in_progress_marked_timeout_in_listing(self, trace_dir):
        doc = _sample_trace_doc(stop_reason="in_progress")
        fp = _write_trace(trace_dir, "s_20260813-103000_a1b2c3d4.json", doc)
        stale_time = time.time() - _STALE_THRESHOLD_SECONDS - 60
        os.utime(fp, (stale_time, stale_time))

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        assert result[0]["stop_reason"] == "timeout"
        assert result[0]["is_active"] is False

    def test_fresh_in_progress_stays_active(self, trace_dir):
        doc = _sample_trace_doc(stop_reason="in_progress")
        _write_trace(trace_dir, "f_20260813-103000_a1b2c3d4.json", doc)

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        assert result[0]["stop_reason"] == "in_progress"
        assert result[0]["is_active"] is True

    def test_stale_trace_file_rewritten(self, trace_dir):
        doc = _sample_trace_doc(stop_reason="in_progress")
        fp = _write_trace(trace_dir, "r_20260813-103000_a1b2c3d4.json", doc)
        stale_time = time.time() - _STALE_THRESHOLD_SECONDS - 60
        os.utime(fp, (stale_time, stale_time))

        list_traces(str(trace_dir))

        with open(fp, "r", encoding="utf-8") as fh:
            rewritten = json.load(fh)
        assert rewritten["stop_reason"] == "timeout"
        assert "ended_at" in rewritten
        assert rewritten["usage"]["input_tokens"] == 200
        assert rewritten["usage"]["output_tokens"] == 100

    def test_stale_trace_ends_at_last_step_timestamp(self, trace_dir):
        doc = _sample_trace_doc(stop_reason="in_progress")
        expected = "2026-08-13T10:31:42+00:00"
        doc["trace"][-1]["steps"][-1]["recorded_at"] = expected
        fp = _write_trace(trace_dir, "ts_20260813-103000_a1b2c3d4.json", doc)
        stale_time = time.time() - _STALE_THRESHOLD_SECONDS - 60
        os.utime(fp, (stale_time, stale_time))

        list_traces(str(trace_dir))

        with open(fp, "r", encoding="utf-8") as fh:
            rewritten = json.load(fh)
        assert rewritten["ended_at"] == expected

    def test_stale_meta_sidecar_also_rewritten(self, trace_dir):
        doc = _sample_trace_doc(stop_reason="in_progress")
        fp = _write_trace(trace_dir, "m2_20260813-103000_a1b2c3d4.json", doc)
        write_trace_meta(str(fp), doc)
        stale_time = time.time() - _STALE_THRESHOLD_SECONDS - 60
        os.utime(fp, (stale_time, stale_time))

        list_traces(str(trace_dir))

        meta_fp = _meta_path(str(fp))
        with open(meta_fp, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        assert meta["stop_reason"] == "timeout"
        assert meta["usage"]["input_tokens"] == 200

    def test_finalize_stale_trace_noop_if_not_in_progress(self, trace_dir):
        doc = _sample_trace_doc(stop_reason="end_turn")
        fp = _write_trace(trace_dir, "n_20260813-103000_a1b2c3d4.json", doc)
        _finalize_stale_trace(str(fp))
        with open(fp, "r", encoding="utf-8") as fh:
            reread = json.load(fh)
        assert reread["stop_reason"] == "end_turn"

    def test_stale_detection_in_read_trace_detail(self, trace_dir):
        doc = _sample_trace_doc(stop_reason="in_progress")
        fp = _write_trace(trace_dir, "d_20260813-103000_a1b2c3d4.json", doc)
        stale_time = time.time() - _STALE_THRESHOLD_SECONDS - 60
        os.utime(fp, (stale_time, stale_time))

        result = read_trace_detail(str(trace_dir), "d_20260813-103000_a1b2c3d4.json")
        assert result is not None
        assert result["stop_reason"] == "timeout"
        assert result["is_active"] is False

    def test_fresh_detail_stays_in_progress(self, trace_dir):
        doc = _sample_trace_doc(stop_reason="in_progress")
        _write_trace(trace_dir, "fd_20260813-103000_a1b2c3d4.json", doc)

        result = read_trace_detail(str(trace_dir), "fd_20260813-103000_a1b2c3d4.json")
        assert result is not None
        assert result["stop_reason"] == "in_progress"
        assert result["is_active"] is True


class TestPushedTraceToSummary:
    def test_converts_to_summary(self):
        doc = _sample_trace_doc()
        result = pushed_trace_to_summary("test.json", doc)
        assert result["filename"] == "test.json"
        assert result["agent_name"] == "test-agent"
        assert result["total_turns"] == 2
        assert result["is_active"] is False

    def test_includes_run_id(self):
        doc = _sample_trace_doc()
        doc["run_id"] = "abc123"
        doc["run_sequence"] = 2
        result = pushed_trace_to_summary("test.json", doc)
        assert result["run_id"] == "abc123"
        assert result["run_sequence"] == 2

    def test_omits_run_id_when_absent(self):
        doc = _sample_trace_doc()
        result = pushed_trace_to_summary("test.json", doc)
        assert "run_id" not in result
        assert "run_sequence" not in result


class TestRunIdPropagation:
    def test_list_traces_includes_run_id_from_meta(self, trace_dir):
        doc = _sample_trace_doc()
        doc["run_id"] = "run-aaa"
        doc["run_sequence"] = 1
        filepath = str(_write_trace(trace_dir, "r_20260813-103000_a1b2c3d4.json", doc))
        write_trace_meta(filepath, doc)

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        assert result[0]["run_id"] == "run-aaa"
        assert result[0]["run_sequence"] == 1

    def test_list_traces_includes_run_id_from_full_parse(self, trace_dir):
        doc = _sample_trace_doc()
        doc["run_id"] = "run-bbb"
        doc["run_sequence"] = 3
        _write_trace(trace_dir, "r2_20260813-103000_a1b2c3d4.json", doc)

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        assert result[0]["run_id"] == "run-bbb"
        assert result[0]["run_sequence"] == 3

    def test_list_traces_omits_run_id_when_absent(self, trace_dir):
        doc = _sample_trace_doc()
        _write_trace(trace_dir, "n_20260813-103000_a1b2c3d4.json", doc)

        result = list_traces(str(trace_dir))
        assert len(result) == 1
        assert "run_id" not in result[0]


class TestGroupTracesByRun:
    def test_no_run_ids_returns_unchanged(self):
        traces = [
            {"agent_name": "a", "started_at": "2026-01-01T10:00:00"},
            {"agent_name": "b", "started_at": "2026-01-01T11:00:00"},
        ]
        result = group_traces_by_run(traces)
        assert len(result) == 2
        assert all(item.get("type") != "run_group" for item in result)

    def test_groups_shared_run_id(self):
        traces = [
            {
                "agent_name": "analyzer",
                "run_id": "run-1",
                "run_sequence": 1,
                "started_at": "2026-01-01T10:00:00",
                "duration_seconds": 10.0,
                "violation_count": 0,
            },
            {
                "agent_name": "fixer",
                "run_id": "run-1",
                "run_sequence": 2,
                "started_at": "2026-01-01T10:00:10",
                "duration_seconds": 20.0,
                "violation_count": 1,
            },
        ]
        result = group_traces_by_run(traces)
        assert len(result) == 1
        group = result[0]
        assert group["type"] == "run_group"
        assert group["run_id"] == "run-1"
        assert group["agent_count"] == 2
        assert group["total_violations"] == 1
        assert group["total_duration"] == 30.0
        assert len(group["traces"]) == 2
        assert group["traces"][0]["agent_name"] == "analyzer"
        assert group["traces"][1]["agent_name"] == "fixer"

    def test_single_trace_with_run_id_not_grouped(self):
        traces = [
            {
                "agent_name": "solo",
                "run_id": "run-solo",
                "run_sequence": 1,
                "started_at": "2026-01-01T10:00:00",
                "duration_seconds": 5.0,
                "violation_count": 0,
            },
        ]
        result = group_traces_by_run(traces)
        assert len(result) == 1
        assert result[0].get("type") != "run_group"
        assert result[0]["agent_name"] == "solo"

    def test_mixed_grouped_and_standalone(self):
        traces = [
            {
                "agent_name": "a1",
                "run_id": "run-x",
                "run_sequence": 1,
                "started_at": "2026-01-01T10:00:00",
                "duration_seconds": 5.0,
                "violation_count": 0,
            },
            {
                "agent_name": "a2",
                "run_id": "run-x",
                "run_sequence": 2,
                "started_at": "2026-01-01T10:00:05",
                "duration_seconds": 10.0,
                "violation_count": 0,
            },
            {
                "agent_name": "standalone",
                "started_at": "2026-01-01T11:00:00",
                "duration_seconds": 3.0,
                "violation_count": 0,
            },
        ]
        result = group_traces_by_run(traces)
        assert len(result) == 2
        types = [item.get("type") for item in result]
        assert "run_group" in types

    def test_is_active_propagated(self):
        traces = [
            {
                "agent_name": "a1",
                "run_id": "run-act",
                "run_sequence": 1,
                "started_at": "2026-01-01T10:00:00",
                "duration_seconds": 5.0,
                "violation_count": 0,
                "is_active": False,
            },
            {
                "agent_name": "a2",
                "run_id": "run-act",
                "run_sequence": 2,
                "started_at": "2026-01-01T10:00:05",
                "duration_seconds": 0.0,
                "violation_count": 0,
                "is_active": True,
            },
        ]
        result = group_traces_by_run(traces)
        group = [r for r in result if r.get("type") == "run_group"][0]
        assert group["is_active"] is True

    def test_sorted_descending_by_started_at(self):
        traces = [
            {
                "agent_name": "early",
                "started_at": "2026-01-01T09:00:00",
                "duration_seconds": 5.0,
                "violation_count": 0,
            },
            {
                "agent_name": "g1",
                "run_id": "run-late",
                "run_sequence": 1,
                "started_at": "2026-01-01T12:00:00",
                "duration_seconds": 5.0,
                "violation_count": 0,
            },
            {
                "agent_name": "g2",
                "run_id": "run-late",
                "run_sequence": 2,
                "started_at": "2026-01-01T12:00:05",
                "duration_seconds": 5.0,
                "violation_count": 0,
            },
        ]
        result = group_traces_by_run(traces)
        assert result[0].get("type") == "run_group"
        assert result[1]["agent_name"] == "early"

    def test_cross_daemon_grouping(self):
        """Traces from different daemons sharing run_id group together."""
        traces = [
            {
                "agent_name": "triage-verifier",
                "run_id": "pipeline/AAP-90154",
                "run_sequence": 1,
                "started_at": "2026-01-01T10:00:00",
                "duration_seconds": 30.0,
                "violation_count": 0,
                "daemon_source": "daemon-A",
            },
            {
                "agent_name": "remediation-planner",
                "run_id": "pipeline/AAP-90154",
                "run_sequence": 2,
                "started_at": "2026-01-01T10:00:30",
                "duration_seconds": 60.0,
                "violation_count": 0,
                "daemon_source": "daemon-B",
            },
            {
                "agent_name": "remediation-implementer",
                "run_id": "pipeline/AAP-90154",
                "run_sequence": 3,
                "started_at": "2026-01-01T10:01:30",
                "duration_seconds": 45.0,
                "violation_count": 1,
                "daemon_source": "daemon-B",
            },
        ]
        result = group_traces_by_run(traces)
        assert len(result) == 1
        group = result[0]
        assert group["type"] == "run_group"
        assert group["agent_count"] == 3
        assert group["total_violations"] == 1
        assert group["total_duration"] == 135.0
        sources = {t["daemon_source"] for t in group["traces"]}
        assert sources == {"daemon-A", "daemon-B"}
        assert group["traces"][0]["run_sequence"] == 1
        assert group["traces"][2]["run_sequence"] == 3

    def test_empty_list(self):
        assert group_traces_by_run([]) == []
