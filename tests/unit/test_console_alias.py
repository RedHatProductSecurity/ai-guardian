"""Tests for the browser console command and its legacy alias."""

import sys
from unittest.mock import MagicMock, patch

import ai_guardian
import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


class TestConsoleAlias:
    @patch("ai_guardian.web.WebConsole")
    def test_console_launches_web_console(self, mock_console_cls):
        mock_app = MagicMock()
        mock_console_cls.return_value = mock_app

        with patch.object(sys, "argv", ["ai-guardian", "console"]):
            result = ai_guardian.main()

        mock_console_cls.assert_called_once()
        mock_app.run.assert_called_once_with(port=0, show=True)
        assert result == 0

    @patch("ai_guardian.web.WebConsole")
    def test_tui_alias_still_launches_web_console(self, mock_console_cls):
        mock_app = MagicMock()
        mock_console_cls.return_value = mock_app

        with patch.object(sys, "argv", ["ai-guardian", "tui"]):
            result = ai_guardian.main()

        mock_console_cls.assert_called_once()
        mock_app.run.assert_called_once_with(port=0, show=True)
        assert result == 0

    def test_help_shows_console_command(self, capsys):
        with patch.object(sys, "argv", ["ai-guardian", "--help"]):
            try:
                ai_guardian.main()
            except SystemExit:
                pass
        captured = capsys.readouterr()
        assert "console" in captured.out

    def test_console_help_mentions_browser_console(self, capsys):
        with patch.object(sys, "argv", ["ai-guardian", "console", "--help"]):
            try:
                ai_guardian.main()
            except SystemExit:
                pass
        captured = capsys.readouterr()
        assert "browser" in captured.out.lower()
