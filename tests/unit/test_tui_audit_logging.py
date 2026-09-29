"""Regression tests for the compliance audit logging TUI panel."""

from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult

from ai_guardian.tui.audit_logging import AuditLoggingContent


class _AuditContentApp(App):
    """Minimal Textual app used to mount the audit settings panel."""

    def compose(self) -> ComposeResult:
        yield AuditLoggingContent()


@pytest.mark.asyncio
async def test_audit_panel_exposes_context_controls_and_export_action():
    config = {"audit_logging": {"include_context": {"session_id": False}}}
    with patch.object(AuditLoggingContent, "_load_full_config", return_value=config):
        async with _AuditContentApp().run_test() as pilot:
            for checkbox_id, _key, _label in AuditLoggingContent.CONTEXT_FIELDS:
                assert pilot.app.query_one(f"#{checkbox_id}") is not None
            assert pilot.app.query_one("#audit-export-btn") is not None
            assert pilot.app.query_one("#audit-export-status") is not None

            assert pilot.app.query_one("#audit-context-session-id").value is False
            assert pilot.app.query_one("#audit-context-user-id").value is True


def test_context_flag_updates_nested_audit_config():
    content = AuditLoggingContent()
    with (
        patch.object(content, "_load_full_config", return_value={}),
        patch.object(content, "_write_full_config", return_value=True) as write_config,
    ):
        assert content._save_context_flag("tool_parameters", False) is True

    saved_config = write_config.call_args.args[0]
    assert saved_config["audit_logging"]["include_context"] == {
        "tool_parameters": False
    }
