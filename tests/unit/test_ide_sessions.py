"""Tests for IDE session discovery and reading."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_guardian.sessions.adapters import ClaudeSessionAdapter, CodexSessionAdapter
from ai_guardian.sessions.discovery import (
    SUPPORTED_IDES,
    discover_sessions,
    get_default_ide,
    get_supported_ides,
)
from ai_guardian.sessions.reader import (
    match_violations_to_steps,
    read_session_detail,
    read_session_messages,
    read_session_summary,
)


class TestGetSupportedIdes:
    def test_returns_list(self):
        result = get_supported_ides()
        assert isinstance(result, list)
        assert len(result) == 8

    def test_claude_is_first(self):
        assert get_supported_ides()[0] == "claude"

    def test_all_expected_ides_present(self):
        ides = get_supported_ides()
        for expected in ["claude", "cursor", "copilot", "codex", "windsurf", "kiro"]:
            assert expected in ides


class TestGetDefaultIde:
    def test_explicit_config(self):
        config = {"session_viewer": {"default_ide": "cursor"}}
        assert get_default_ide(config) == "cursor"

    def test_invalid_config_value_ignored(self):
        config = {"session_viewer": {"default_ide": "notepad"}}
        result = get_default_ide(config)
        assert result in SUPPORTED_IDES

    def test_empty_config_falls_back(self):
        result = get_default_ide({})
        assert result in SUPPORTED_IDES

    def test_none_config(self):
        result = get_default_ide(None)
        assert result in SUPPORTED_IDES


class TestClaudeDecodeProjectName:
    def test_decode_path(self):
        assert (
            ClaudeSessionAdapter.decode_project_name(
                "-Users-dvernier-development-myproject"
            )
            == "/Users/dvernier/development/myproject"
        )

    def test_decode_no_leading_dash(self):
        result = ClaudeSessionAdapter.decode_project_name("some-project")
        assert isinstance(result, str)


class TestClaudeReadSessionMeta:
    def test_reads_title_and_model(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "ai-title", "aiTitle": "Test Title"}) + "\n")
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "model": "claude-opus-4",
                            "usage": {
                                "input_tokens": 100,
                                "output_tokens": 50,
                                "cache_read_input_tokens": 20,
                                "cache_creation_input_tokens": 10,
                            },
                        },
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n"
            )
            path = Path(f.name)

        try:
            meta = ClaudeSessionAdapter.read_session_meta(path)
            assert meta["title"] == "Test Title"
            assert meta["model"] == "claude-opus-4"
            assert meta["message_count"] == 2
            assert meta["token_usage"]["input_tokens"] == 100
            assert meta["token_usage"]["output_tokens"] == 50
        finally:
            path.unlink()

    def test_handles_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = Path(f.name)

        try:
            meta = ClaudeSessionAdapter.read_session_meta(path)
            assert meta["title"] == ""
            assert meta["message_count"] == 0
        finally:
            path.unlink()

    def test_handles_invalid_json_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("not json\n")
            f.write(json.dumps({"type": "ai-title", "aiTitle": "OK"}) + "\n")
            f.write("{bad json\n")
            path = Path(f.name)

        try:
            meta = ClaudeSessionAdapter.read_session_meta(path)
            assert meta["title"] == "OK"
        finally:
            path.unlink()


class TestClaudeSessionTitlePriority:
    def test_custom_title_wins_over_ai_title(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "ai-title", "aiTitle": "AI Generated"}) + "\n")
            f.write(
                json.dumps({"type": "custom-title", "customTitle": "my-named-session"})
                + "\n"
            )
            path = Path(f.name)

        try:
            meta = ClaudeSessionAdapter.read_session_meta(path)
            assert meta["title"] == "my-named-session"
        finally:
            path.unlink()

    def test_agent_name_wins_over_ai_title(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "ai-title", "aiTitle": "AI Generated"}) + "\n")
            f.write(
                json.dumps({"type": "agent-name", "agentName": "my-agent-session"})
                + "\n"
            )
            path = Path(f.name)

        try:
            meta = ClaudeSessionAdapter.read_session_meta(path)
            assert meta["title"] == "my-agent-session"
        finally:
            path.unlink()

    def test_custom_title_wins_over_agent_name(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps({"type": "agent-name", "agentName": "agent-session"}) + "\n"
            )
            f.write(
                json.dumps({"type": "custom-title", "customTitle": "user-session"})
                + "\n"
            )
            path = Path(f.name)

        try:
            meta = ClaudeSessionAdapter.read_session_meta(path)
            assert meta["title"] == "user-session"
        finally:
            path.unlink()

    def test_ai_title_used_when_no_higher_priority(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "ai-title", "aiTitle": "AI Title"}) + "\n")
            path = Path(f.name)

        try:
            meta = ClaudeSessionAdapter.read_session_meta(path)
            assert meta["title"] == "AI Title"
        finally:
            path.unlink()

    def test_custom_title_in_read_detail(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps({"type": "custom-title", "customTitle": "my-named-session"})
                + "\n"
            )
            path = f.name

        try:
            session = {"ide": "claude", "file_path": path}
            steps = read_session_detail(session)
            title_steps = [s for s in steps if s["type"] == "title"]
            assert len(title_steps) == 1
            assert title_steps[0]["content"] == "my-named-session"
        finally:
            Path(path).unlink()

    def test_agent_name_in_read_detail(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "agent-name", "agentName": "my-agent"}) + "\n")
            path = f.name

        try:
            session = {"ide": "claude", "file_path": path}
            steps = read_session_detail(session)
            title_steps = [s for s in steps if s["type"] == "title"]
            assert len(title_steps) == 1
            assert title_steps[0]["content"] == "my-agent"
        finally:
            Path(path).unlink()


class TestCodexReadSessionMeta:
    @staticmethod
    def _write_session(path, *payloads):
        path.write_text(
            "".join(
                json.dumps({"type": "response_item", "payload": payload}) + "\n"
                for payload in payloads
            ),
            encoding="utf-8",
        )

    def test_skips_injected_instructions_list_content(self, tmp_path):
        path = tmp_path / "session.jsonl"
        self._write_session(
            path,
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "# AGENTS.md instructions for /workspace\n<INSTRUCTIONS>",
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "Fix the session title"}],
            },
        )

        meta = CodexSessionAdapter._read_session_meta(path)

        assert meta["title"] == "Fix the session title"
        assert meta["message_count"] == 2

    def test_skips_injected_instructions_string_content(self, tmp_path):
        path = tmp_path / "session.jsonl"
        self._write_session(
            path,
            {"role": "user", "content": "  # Project instructions\nInjected"},
            {"role": "user", "content": "Show the actual query"},
        )

        meta = CodexSessionAdapter._read_session_meta(path)

        assert meta["title"] == "Show the actual query"

    def test_keeps_normal_markdown_heading(self, tmp_path):
        path = tmp_path / "session.jsonl"
        self._write_session(
            path,
            {"role": "user", "content": "# Fix login failures"},
        )

        meta = CodexSessionAdapter._read_session_meta(path)

        assert meta["title"] == "# Fix login failures"

    def test_has_empty_title_when_only_injected_instructions(self, tmp_path):
        path = tmp_path / "session.jsonl"
        self._write_session(
            path,
            {"role": "user", "content": "# AGENTS.md instructions\nInjected"},
        )

        meta = CodexSessionAdapter._read_session_meta(path)

        assert meta["title"] == ""


class TestDiscoverSessions:
    def test_unsupported_ide_returns_empty(self):
        result = discover_sessions("notepad")
        assert result == []

    def test_discover_claude_with_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = Path(tmpdir) / "-tmp-myproject"
            proj_dir.mkdir()

            session_file = proj_dir / "abc123.jsonl"
            session_file.write_text(
                json.dumps({"type": "ai-title", "aiTitle": "My Session"})
                + "\n"
                + json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "model": "claude-sonnet-4",
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                        },
                    }
                )
                + "\n"
            )

            with patch(
                "ai_guardian.sessions.adapters.ClaudeSessionAdapter.resolve_session_dir",
                return_value=Path(tmpdir),
            ):
                sessions = discover_sessions("claude")

            assert len(sessions) == 1
            assert sessions[0]["session_id"] == "abc123"
            assert sessions[0]["title"] == "My Session"
            assert sessions[0]["model"] == "claude-sonnet-4"

    def test_discover_claude_filters_by_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj1 = Path(tmpdir) / "-tmp-project1"
            proj1.mkdir()
            (proj1 / "s1.jsonl").write_text('{"type": "user"}\n')

            proj2 = Path(tmpdir) / "-tmp-project2"
            proj2.mkdir()
            (proj2 / "s2.jsonl").write_text('{"type": "user"}\n')

            with patch(
                "ai_guardian.sessions.adapters.ClaudeSessionAdapter.resolve_session_dir",
                return_value=Path(tmpdir),
            ):
                all_sessions = discover_sessions("claude")
                assert len(all_sessions) == 2

                filtered = discover_sessions("claude", project_path="/tmp/project1")
                assert len(filtered) == 1


class TestReadSessionSummary:
    def test_enriches_claude_session(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-08-15T10:00:00Z",
                        "message": {"content": "hello"},
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": "hi"}]},
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-08-15T10:05:00Z",
                        "message": {"content": "bye"},
                    }
                )
                + "\n"
            )
            path = f.name

        try:
            session = {"ide": "claude", "file_path": path}
            result = read_session_summary(session)
            assert result["first_timestamp"] == "2026-08-15T10:00:00Z"
            assert result["last_timestamp"] == "2026-08-15T10:05:00Z"
            assert result["user_messages"] == 2
            assert result["assistant_messages"] == 1
        finally:
            Path(path).unlink()


class TestReadSessionMessages:
    def test_reads_claude_messages(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-08-15T10:00:00Z",
                        "message": {"content": "hello world"},
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "model": "claude-sonnet-4",
                            "content": [{"type": "text", "text": "hi there"}],
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                        },
                    }
                )
                + "\n"
            )
            path = f.name

        try:
            session = {"ide": "claude", "file_path": path}
            msgs = read_session_messages(session)
            assert len(msgs) == 2
            assert msgs[0]["role"] == "user"
            assert msgs[0]["content"] == "hello world"
            assert msgs[1]["role"] == "assistant"
            assert msgs[1]["content"] == "hi there"
        finally:
            Path(path).unlink()

    def test_respects_limit(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for i in range(10):
                f.write(
                    json.dumps(
                        {
                            "type": "user",
                            "message": {"content": f"msg {i}"},
                        }
                    )
                    + "\n"
                )
            path = f.name

        try:
            session = {"ide": "claude", "file_path": path}
            msgs = read_session_messages(session, limit=3)
            assert len(msgs) == 3
        finally:
            Path(path).unlink()

    def test_unsupported_ide_returns_empty(self):
        session = {"ide": "notepad", "file_path": "/nonexistent"}
        assert read_session_messages(session) == []

    def test_tool_result_in_user_message_not_shown_as_user(self):
        """Tool results sent as role:user should appear as tool_result, not user."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-08-17T10:00:00Z",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "tool_abc",
                                    "content": "file contents here",
                                }
                            ]
                        },
                    }
                )
                + "\n"
            )
            path = f.name

        try:
            session = {"ide": "claude", "file_path": path}
            msgs = read_session_messages(session)
            assert len(msgs) == 1
            assert msgs[0]["role"] == "tool_result"
            assert "file contents" in msgs[0]["content"]
        finally:
            Path(path).unlink()

    def test_mixed_text_and_tool_result_in_user_message(self):
        """User message with both text and tool_result blocks."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-08-17T10:00:00Z",
                        "message": {
                            "content": [
                                {"type": "text", "text": "Here is context"},
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "tool_xyz",
                                    "content": "result data",
                                },
                            ]
                        },
                    }
                )
                + "\n"
            )
            path = f.name

        try:
            session = {"ide": "claude", "file_path": path}
            msgs = read_session_messages(session)
            roles = [m["role"] for m in msgs]
            assert "tool_result" in roles
            assert "user" in roles
            user_msgs = [m for m in msgs if m["role"] == "user"]
            assert user_msgs[0]["content"] == "Here is context"
        finally:
            Path(path).unlink()


class TestReadSessionDetailToolResults:
    def test_tool_result_in_user_message_parsed_correctly(self):
        """Tool results in role:user messages should emit tool_result steps."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-08-17T10:00:00Z",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "tool_123",
                                    "content": "245 lines read",
                                }
                            ]
                        },
                    }
                )
                + "\n"
            )
            path = f.name

        try:
            session = {"ide": "claude", "file_path": path}
            steps = read_session_detail(session)
            assert len(steps) == 1
            assert steps[0]["type"] == "tool_result"
            assert steps[0]["content"] == "245 lines read"
            assert steps[0]["tool_id"] == "tool_123"
        finally:
            Path(path).unlink()

    def test_empty_user_message_not_emitted(self):
        """User messages with only tool_results should not emit user steps."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "t1",
                                    "content": "ok",
                                },
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "t2",
                                    "content": "done",
                                },
                            ]
                        },
                    }
                )
                + "\n"
            )
            path = f.name

        try:
            session = {"ide": "claude", "file_path": path}
            steps = read_session_detail(session)
            user_steps = [s for s in steps if s["type"] == "user"]
            assert len(user_steps) == 0
            tool_steps = [s for s in steps if s["type"] == "tool_result"]
            assert len(tool_steps) == 2
        finally:
            Path(path).unlink()

    def test_mixed_content_emits_both(self):
        """Mixed text + tool_result in user message emits both types."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-08-17T10:00:00Z",
                        "message": {
                            "content": [
                                {"type": "text", "text": "user typed this"},
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "t1",
                                    "content": "tool output",
                                },
                            ]
                        },
                    }
                )
                + "\n"
            )
            path = f.name

        try:
            session = {"ide": "claude", "file_path": path}
            steps = read_session_detail(session)
            types = [s["type"] for s in steps]
            assert "tool_result" in types
            assert "user" in types
            user_step = [s for s in steps if s["type"] == "user"][0]
            assert user_step["content"] == "user typed this"
        finally:
            Path(path).unlink()

    def test_tool_result_with_list_content(self):
        """Tool result with list content (nested text blocks) is flattened."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "t1",
                                    "content": [
                                        {"type": "text", "text": "line 1"},
                                        {"type": "text", "text": "line 2"},
                                    ],
                                }
                            ]
                        },
                    }
                )
                + "\n"
            )
            path = f.name

        try:
            session = {"ide": "claude", "file_path": path}
            steps = read_session_detail(session)
            assert len(steps) == 1
            assert steps[0]["type"] == "tool_result"
            assert "line 1" in steps[0]["content"]
            assert "line 2" in steps[0]["content"]
        finally:
            Path(path).unlink()


class TestMatchViolationsToSteps:
    def test_empty_steps(self):
        assert (
            match_violations_to_steps([], [{"timestamp": "2026-08-15T10:00:00Z"}]) == {}
        )

    def test_empty_violations(self):
        steps = [{"type": "user", "timestamp": "2026-08-15T10:00:00Z"}]
        assert match_violations_to_steps(steps, []) == {}

    def test_both_empty(self):
        assert match_violations_to_steps([], []) == {}

    def test_single_match(self):
        steps = [
            {"type": "user", "timestamp": "2026-08-15T10:00:00Z", "content": "hello"},
            {"type": "assistant", "content": "hi"},
        ]
        violations = [
            {
                "timestamp": "2026-08-15T10:00:05Z",
                "violation_type": "secret_detected",
                "id": "viol_001",
            },
        ]
        result = match_violations_to_steps(steps, violations)
        assert 0 in result
        assert len(result[0]) == 1
        assert result[0][0]["id"] == "viol_001"

    def test_violation_matches_latest_prior_step(self):
        steps = [
            {"type": "user", "timestamp": "2026-08-15T10:00:00Z"},
            {"type": "assistant", "content": "..."},
            {"type": "user", "timestamp": "2026-08-15T10:05:00Z"},
        ]
        violations = [
            {
                "timestamp": "2026-08-15T10:03:00Z",
                "violation_type": "prompt_injection",
                "id": "viol_002",
            },
        ]
        result = match_violations_to_steps(steps, violations)
        assert 0 in result
        assert result[0][0]["id"] == "viol_002"

    def test_multiple_violations_same_step(self):
        steps = [
            {"type": "user", "timestamp": "2026-08-15T10:00:00Z"},
        ]
        violations = [
            {
                "timestamp": "2026-08-15T10:00:01Z",
                "violation_type": "secret_detected",
                "id": "viol_a",
            },
            {
                "timestamp": "2026-08-15T10:00:02Z",
                "violation_type": "prompt_injection",
                "id": "viol_b",
            },
        ]
        result = match_violations_to_steps(steps, violations)
        assert len(result[0]) == 2

    def test_violations_across_multiple_steps(self):
        steps = [
            {"type": "user", "timestamp": "2026-08-15T10:00:00Z"},
            {"type": "assistant", "content": "..."},
            {"type": "user", "timestamp": "2026-08-15T10:05:00Z"},
            {"type": "assistant", "content": "..."},
        ]
        violations = [
            {
                "timestamp": "2026-08-15T10:01:00Z",
                "violation_type": "secret_detected",
                "id": "viol_1",
            },
            {
                "timestamp": "2026-08-15T10:06:00Z",
                "violation_type": "prompt_injection",
                "id": "viol_2",
            },
        ]
        result = match_violations_to_steps(steps, violations)
        assert 0 in result
        assert result[0][0]["id"] == "viol_1"
        assert 2 in result
        assert result[2][0]["id"] == "viol_2"

    def test_no_timestamped_steps(self):
        steps = [
            {"type": "assistant", "content": "hi"},
            {"type": "tool_use", "tool_name": "Bash"},
        ]
        violations = [
            {"timestamp": "2026-08-15T10:00:00Z", "violation_type": "secret_detected"},
        ]
        assert match_violations_to_steps(steps, violations) == {}

    def test_violation_without_timestamp_skipped(self):
        steps = [
            {"type": "user", "timestamp": "2026-08-15T10:00:00Z"},
        ]
        violations = [
            {"violation_type": "secret_detected", "id": "viol_no_ts"},
        ]
        assert match_violations_to_steps(steps, violations) == {}

    def test_violation_before_first_step_maps_to_first(self):
        steps = [
            {"type": "user", "timestamp": "2026-08-15T10:05:00Z"},
        ]
        violations = [
            {
                "timestamp": "2026-08-15T10:00:00Z",
                "violation_type": "secret_detected",
                "id": "viol_early",
            },
        ]
        result = match_violations_to_steps(steps, violations)
        assert 0 in result
        assert result[0][0]["id"] == "viol_early"

    def test_violation_at_exact_step_timestamp(self):
        steps = [
            {"type": "user", "timestamp": "2026-08-15T10:00:00Z"},
            {"type": "user", "timestamp": "2026-08-15T10:05:00Z"},
        ]
        violations = [
            {
                "timestamp": "2026-08-15T10:05:00Z",
                "violation_type": "secret_detected",
                "id": "viol_exact",
            },
        ]
        result = match_violations_to_steps(steps, violations)
        assert 1 in result
        assert result[1][0]["id"] == "viol_exact"
