"""Regression tests for privacy-safe PII source coordinates."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from ai_guardian.hook_events import content_pipeline
from ai_guardian.scanners.scan_result import ScanResult


def test_pii_redactor_coordinates_are_normalized_for_sensitive_history(monkeypatch):
    redaction = {
        "type": "email",
        "line_number": 3,
        "column": 6,
        "original_length": 12,
        "position": 25,
    }
    result = ScanResult(
        detected=True,
        violation_type="pii_detected",
        file_path="/repo/data.csv",
        redactions=[redaction],
        extra={"action": "block"},
        error_message="PII detected",
    )
    monkeypatch.setattr(
        content_pipeline._loaders,
        "_load_pii_config",
        lambda: ({"action": "block"}, None),
    )
    monkeypatch.setattr(
        content_pipeline,
        "_extract_pii_matched_text",
        lambda *_args: "synthetic-private-match",
    )
    monkeypatch.setattr(
        content_pipeline,
        "_pii_redactions_to_findings",
        lambda *_args: [{"line_number": 3, "matched_text": "synthetic-private-match"}],
    )
    monkeypatch.setattr(
        content_pipeline, "_compute_pii_transcript_fingerprints", lambda *_args: []
    )
    pipeline_call = MagicMock(
        return_value=SimpleNamespace(should_block=True, warnings=[])
    )
    monkeypatch.setattr(content_pipeline, "apply_post_scan_pipeline", pipeline_call)

    content_pipeline._handle_pii_result(
        result,
        _registry=MagicMock(),
        _post_scan_ctx=SimpleNamespace(non_blocking_findings_enabled=False),
        file_path="/repo/data.csv",
        filename="data.csv",
        warning_messages=[],
        warn_violation_types=None,
        log_only_count=0,
        pii_content="some private source text",
    )

    logged_result = pipeline_call.call_args.args[1]
    assert logged_result.file_path == "/repo/data.csv"
    assert logged_result.line_number == 3
    assert logged_result.start_column == 5
    assert logged_result.end_column == 17
    assert logged_result.matched_text == "synthetic-private-match"
