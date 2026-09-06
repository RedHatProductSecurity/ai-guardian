"""Tests for the NiceGUI proactive prompt state page."""

import json
from unittest.mock import patch

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


class TestProactivePromptPage:
    def test_page_exists(self):
        from ai_guardian.web.pages.proactive_prompts import (
            create_proactive_prompts_page,
        )

        assert callable(create_proactive_prompts_page)

    def test_route_registered_in_app(self):
        import inspect

        from ai_guardian.web.app import WebConsole
        from ai_guardian.web.pages.proactive_prompts import (
            create_proactive_prompts_page,
        )

        source = inspect.getsource(WebConsole._register_pages)
        assert "/proactive-prompts" in source
        assert "Sync with current IDE/CLI configuration" in inspect.getsource(
            create_proactive_prompts_page
        )
        assert "Reset" in inspect.getsource(create_proactive_prompts_page)

    def test_route_in_sidebar(self):
        from ai_guardian.web.components.header import NAV_GROUPS

        suffixes = [suffix for _, items in NAV_GROUPS for _, suffix in items]
        assert "/proactive-prompts" in suffixes


class TestProactivePromptStateViewer:
    def test_missing_file(self, tmp_path):
        from ai_guardian.web.pages.proactive_prompts import (
            _load_proactive_prompt_file,
        )

        path = tmp_path / "proactive_prompts.json"
        with patch("ai_guardian.tray.proactive_prompt._state_path", return_value=path):
            result = _load_proactive_prompt_file()

        assert result["path"] == str(path)
        assert result["exists"] is False
        assert result["content"] is None
        assert result["error"] is None

    def test_valid_file_is_formatted_for_viewing(self, tmp_path):
        from ai_guardian.web.pages.proactive_prompts import (
            _load_proactive_prompt_file,
        )

        path = tmp_path / "proactive_prompts.json"
        expected = {
            "ide_setup_never_install": ["cursor"],
            "upgrade": {"status": "snoozed"},
        }
        path.write_text(json.dumps(expected), encoding="utf-8")

        with patch("ai_guardian.tray.proactive_prompt._state_path", return_value=path):
            result = _load_proactive_prompt_file()

        assert result["exists"] is True
        assert json.loads(result["content"]) == expected
        assert result["error"] is None

    def test_invalid_file_preserves_content_and_reports_error(self, tmp_path):
        from ai_guardian.web.pages.proactive_prompts import (
            _load_proactive_prompt_file,
        )

        path = tmp_path / "proactive_prompts.json"
        raw = "{not valid json"
        path.write_text(raw, encoding="utf-8")

        with patch("ai_guardian.tray.proactive_prompt._state_path", return_value=path):
            result = _load_proactive_prompt_file()

        assert result["exists"] is True
        assert result["content"] == raw
        assert "Invalid JSON" in result["error"]

    def test_non_object_json_is_displayed_without_crashing(self, tmp_path):
        from ai_guardian.web.pages.proactive_prompts import (
            _load_proactive_prompt_file,
        )

        path = tmp_path / "proactive_prompts.json"
        path.write_text("[]", encoding="utf-8")

        with patch("ai_guardian.tray.proactive_prompt._state_path", return_value=path):
            result = _load_proactive_prompt_file()

        assert result["exists"] is True
        assert result["data"] == {}
        assert "JSON object" in result["error"]

    def test_sync_wrapper_uses_shared_state_sync(self):
        from ai_guardian.web.pages.proactive_prompts import (
            _sync_proactive_prompt_file,
        )

        expected = {"installed": ["claude"], "configured": ["claude"]}
        with patch(
            "ai_guardian.web.pages.proactive_prompts.sync_ide_setup_state",
            return_value=expected,
        ) as sync:
            assert _sync_proactive_prompt_file() == expected

        sync.assert_called_once_with()

    def test_reset_wrapper_uses_shared_state_reset(self):
        from ai_guardian.web.pages.proactive_prompts import (
            _reset_proactive_prompt_file,
        )

        expected = {"ide": "claude", "changed": True}
        with patch(
            "ai_guardian.web.pages.proactive_prompts.reset_ide_setup_state",
            return_value=expected,
        ) as reset:
            assert _reset_proactive_prompt_file("claude") == expected

        reset.assert_called_once_with("claude")
