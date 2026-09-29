"""Regression tests for the Web Console audit logging page."""

import inspect
from pathlib import Path

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


def test_export_helper_uses_audit_export_path(monkeypatch, tmp_path):
    from ai_guardian.violations import audit as audit_module
    from ai_guardian.web.pages.audit_logging import _export_audit_log

    calls = []

    class FakeAuditLogger:
        log_path = tmp_path / "audit.jsonl"

        def __init__(self, config=None):
            self.config = config

        def get_export_path(self, export_format):
            return self.log_path.with_suffix(f".{export_format}")

        def export(self, export_path, export_format=None):
            calls.append((export_path, export_format))
            Path(export_path).write_text("[]\n", encoding="utf-8")
            return True

    monkeypatch.setattr(audit_module, "AuditLogger", FakeAuditLogger)

    export_path = _export_audit_log("csv")

    assert export_path == str(tmp_path / "audit.csv")
    assert calls == [(tmp_path / "audit.csv", "csv")]


def test_audit_page_contains_context_controls_and_safe_export_boundary():
    from ai_guardian.web.pages.audit_logging import create_audit_logging_page

    source = inspect.getsource(create_audit_logging_page)
    assert "include_context" in source
    assert "Export audit trail" in source
    assert "remote_target" in source
    assert "Raw prompts and tool output are never persisted" in source
