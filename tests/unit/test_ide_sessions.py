"""Tests for IDE session discovery and reading."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_guardian.sessions.discovery import (
    SUPPORTED_IDES,
    _decode_claude_project_name,
    _read_claude_session_meta,
    discover_sessions,
    get_default_ide,
    get_supported_ides,
)
from ai_guardian.sessions.reader import read_session_messages, read_session_summary


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


class TestDecodeClaudeProjectName:
    def test_decode_path(self):
        assert (
            _decode_claude_project_name("-Users-dvernier-development-myproject")
            == "/Users/dvernier/development/myproject"
        )

    def test_decode_no_leading_dash(self):
        result = _decode_claude_project_name("some-project")
        assert isinstance(result, str)


class TestReadClaudeSessionMeta:
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
            meta = _read_claude_session_meta(path)
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
            meta = _read_claude_session_meta(path)
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
            meta = _read_claude_session_meta(path)
            assert meta["title"] == "OK"
        finally:
            path.unlink()


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
                "ai_guardian.sessions.discovery._resolve_session_dir",
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
                "ai_guardian.sessions.discovery._resolve_session_dir",
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
