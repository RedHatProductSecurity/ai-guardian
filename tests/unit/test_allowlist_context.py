"""Tests for safe deferred source resolution metadata."""

import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from ai_guardian.scanners.scan_result import ScanResult
from ai_guardian.violations.allowlist_context import (
    build_allowlist_context,
    get_annotation_target,
    resolve_source_location,
)
from ai_guardian.violations.log_violation import ScanContext, log_violation
from ai_guardian.violations.logger import ViolationLogger


def _violation(path, line_number, metadata):
    return {
        "violation_type": "secret_detected",
        "blocked": {"file_path": path, "line_number": line_number},
        "allowlist_context": metadata,
    }


def test_build_context_hashes_line_and_redacts_known_value():
    content = "before\nsetting = SENSITIVE_VALUE\nafter"
    source_path = str(Path.cwd() / "settings.py")
    with patch(
        "ai_guardian.violations.allowlist_context.is_temp_path", return_value=False
    ):
        context = build_allowlist_context(
            content,
            source_path,
            2,
            rule_id="custom-rule",
            project_path=str(Path.cwd()),
            git_ref="test-ref",
            sensitive_values=["SENSITIVE_VALUE"],
        )

    assert context is not None
    assert context["rule_id"] == "custom-rule"
    assert context["original_file_path"] == source_path
    assert (
        context["line_content_hash"]
        == hashlib.sha256(b"setting = SENSITIVE_VALUE").hexdigest()
    )
    assert "SENSITIVE_VALUE" not in context["surrounding_context"]
    assert "setting =" in context["surrounding_context"]
    assert context["git_ref"] == "test-ref"


def test_build_context_fails_closed_if_sanitizer_fails():
    with (
        patch(
            "ai_guardian.violations.allowlist_context.is_temp_path",
            return_value=False,
        ),
        patch(
            "ai_guardian.scanners.sanitizer.sanitize_text",
            side_effect=RuntimeError("unavailable"),
        ),
    ):
        context = build_allowlist_context(
            "safe-looking source",
            "/workspace/project/app.py",
            1,
            git_ref="test-ref",
        )

    assert context is not None
    assert context["surrounding_context"] == "[REDACTED]"
    assert "safe-looking source" not in json.dumps(context)


def test_build_context_skips_temporary_paths():
    temp_path = str(Path(tempfile.gettempdir()) / "scanner-copy.py")
    assert build_allowlist_context("finding", temp_path, 1) is None


def test_resolve_source_location_prefers_logged_line(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("duplicate\nfinding line\nduplicate\n", encoding="utf-8")
    line_hash = hashlib.sha256(b"finding line").hexdigest()
    metadata = {
        "original_file_path": str(source),
        "line_content_hash": line_hash,
    }

    with patch(
        "ai_guardian.violations.allowlist_context.is_temp_path", return_value=False
    ):
        assert resolve_source_location(_violation(str(source), 2, metadata)) == (
            str(source),
            2,
        )


def test_resolve_source_location_finds_unique_line_after_move(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("header\nheader 2\nfinding line\n", encoding="utf-8")
    line_hash = hashlib.sha256(b"finding line").hexdigest()
    metadata = {
        "original_file_path": str(source),
        "line_content_hash": line_hash,
    }

    with patch(
        "ai_guardian.violations.allowlist_context.is_temp_path", return_value=False
    ):
        assert resolve_source_location(_violation(str(source), 1, metadata)) == (
            str(source),
            3,
        )


def test_resolve_source_location_rejects_changed_line(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("changed\n", encoding="utf-8")
    metadata = {
        "original_file_path": str(source),
        "line_content_hash": hashlib.sha256(b"original").hexdigest(),
    }

    with patch(
        "ai_guardian.violations.allowlist_context.is_temp_path", return_value=False
    ):
        assert resolve_source_location(_violation(str(source), 1, metadata)) is None
        assert get_annotation_target(_violation(str(source), 1, metadata)) is None


def test_legacy_non_temp_location_remains_available():
    violation = {
        "blocked": {"file_path": "/workspace/project/app.py", "line_number": 4}
    }
    with patch(
        "ai_guardian.violations.allowlist_context.is_temp_path", return_value=False
    ):
        assert get_annotation_target(violation) == (
            "/workspace/project/app.py",
            4,
        )


def test_shared_logger_persists_safe_context_only():
    source_path = str(Path.cwd() / "app.py")
    result = ScanResult(
        detected=True,
        violation_type="secret_detected",
        file_path=source_path,
        line_number=1,
        rule_id="custom-rule",
        matched_text="SENSITIVE_VALUE",
    )
    logger_calls = []

    class Logger:
        def log_violation(self, **kwargs):
            logger_calls.append(kwargs)

    context = ScanContext(
        project_path=str(Path.cwd()),
        allowlist_content="value = SENSITIVE_VALUE\n",
        allowlist_file_path=source_path,
        allowlist_sensitive_values=["SENSITIVE_VALUE"],
    )
    with patch(
        "ai_guardian.violations.allowlist_context.is_temp_path", return_value=False
    ):
        log_violation(result, context, violation_logger=Logger())

    assert len(logger_calls) == 1
    metadata = logger_calls[0]["allowlist_context"]
    assert metadata["original_file_path"] == source_path
    assert "SENSITIVE_VALUE" not in json.dumps(metadata)


def test_shared_logger_does_not_persist_private_context_fields():
    result = ScanResult(
        detected=True,
        violation_type="prompt_injection",
        file_path="/workspace/project/app.py",
        line_number=1,
    )
    calls = []

    class Logger:
        def log_violation(self, **kwargs):
            calls.append(kwargs)

    context = ScanContext(
        project_path="/workspace/project",
        allowlist_content="source",
        allowlist_file_path="/workspace/project/app.py",
    )
    with patch(
        "ai_guardian.violations.allowlist_context.is_temp_path", return_value=False
    ):
        log_violation(result, context, violation_logger=Logger())

    assert "_allowlist_content" not in calls[0]["context"]
    assert "source" in calls[0]["allowlist_context"]["surrounding_context"]


def test_violation_logger_writes_allowlist_context_at_top_level(tmp_path):
    log_path = tmp_path / "violations.jsonl"
    logger = ViolationLogger(log_path=log_path, config={"enabled": True})
    metadata = {
        "rule_id": "custom-rule",
        "original_file_path": "/workspace/project/app.py",
        "line_content_hash": "a" * 64,
        "surrounding_context": "safe context",
        "git_ref": "test-ref",
        "project_path": "/workspace/project",
    }

    logger.log_violation(
        "secret_detected",
        blocked={"file_path": "/tmp/scanner-copy.py", "line_number": 1},
        context={"project_path": "/workspace/project"},
        allowlist_context=metadata,
    )

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["allowlist_context"] == metadata
