"""Tests for tool_use_id and session_id filters on get_recent_violations()."""

import json
import os
import tempfile
from unittest import mock

import pytest

from ai_guardian.violations.logger import ViolationLogger


class TestContextFilters:
    """Test tool_use_id and session_id filtering in get_recent_violations()."""

    def _create_logger_with_violations(self, tmp, violations):
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
            vl = ViolationLogger()
            for v in violations:
                vl.log_violation(
                    violation_type=v.get("violation_type", "secret_detected"),
                    blocked=v.get("blocked", {"reason": "test"}),
                    context=v.get("context", {}),
                )
            return vl

    def test_filter_by_tool_use_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            vl = self._create_logger_with_violations(
                tmp,
                [
                    {"context": {"tool_use_id": "tu_abc", "session_id": "s1"}},
                    {"context": {"tool_use_id": "tu_def", "session_id": "s1"}},
                    {"context": {"tool_use_id": "tu_abc", "session_id": "s2"}},
                ],
            )
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                results = vl.get_recent_violations(tool_use_id="tu_abc")
            assert len(results) == 2
            for r in results:
                assert r["context"]["tool_use_id"] == "tu_abc"

    def test_filter_by_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            vl = self._create_logger_with_violations(
                tmp,
                [
                    {"context": {"tool_use_id": "tu_abc", "session_id": "s1"}},
                    {"context": {"tool_use_id": "tu_def", "session_id": "s2"}},
                    {"context": {"tool_use_id": "tu_ghi", "session_id": "s1"}},
                ],
            )
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                results = vl.get_recent_violations(session_id="s1")
            assert len(results) == 2
            for r in results:
                assert r["context"]["session_id"] == "s1"

    def test_filter_by_both_tool_use_id_and_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            vl = self._create_logger_with_violations(
                tmp,
                [
                    {"context": {"tool_use_id": "tu_abc", "session_id": "s1"}},
                    {"context": {"tool_use_id": "tu_abc", "session_id": "s2"}},
                    {"context": {"tool_use_id": "tu_def", "session_id": "s1"}},
                ],
            )
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                results = vl.get_recent_violations(
                    tool_use_id="tu_abc", session_id="s1"
                )
            assert len(results) == 1
            assert results[0]["context"]["tool_use_id"] == "tu_abc"
            assert results[0]["context"]["session_id"] == "s1"

    def test_filter_no_match_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            vl = self._create_logger_with_violations(
                tmp,
                [
                    {"context": {"tool_use_id": "tu_abc", "session_id": "s1"}},
                ],
            )
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                results = vl.get_recent_violations(tool_use_id="tu_nonexistent")
            assert len(results) == 0

    def test_filter_skips_entries_without_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            vl = self._create_logger_with_violations(
                tmp,
                [
                    {"context": {}},
                    {"context": {"tool_use_id": "tu_abc"}},
                ],
            )
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                results = vl.get_recent_violations(tool_use_id="tu_abc")
            assert len(results) == 1

    def test_filter_combined_with_violation_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            vl = self._create_logger_with_violations(
                tmp,
                [
                    {
                        "violation_type": "secret_detected",
                        "context": {"tool_use_id": "tu_abc", "session_id": "s1"},
                    },
                    {
                        "violation_type": "prompt_injection",
                        "context": {"tool_use_id": "tu_abc", "session_id": "s1"},
                    },
                ],
            )
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                results = vl.get_recent_violations(
                    violation_type="secret_detected", session_id="s1"
                )
            assert len(results) == 1
            assert results[0]["violation_type"] == "secret_detected"

    def test_no_filters_returns_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            vl = self._create_logger_with_violations(
                tmp,
                [
                    {"context": {"tool_use_id": "tu_abc", "session_id": "s1"}},
                    {"context": {"tool_use_id": "tu_def", "session_id": "s2"}},
                ],
            )
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                results = vl.get_recent_violations()
            assert len(results) == 2
