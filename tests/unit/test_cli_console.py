"""Tests for the browser console command."""

from unittest.mock import patch

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


class TestConsoleCommand:
    @patch("ai_guardian.web.WebConsole")
    def test_console_does_not_require_a_tty(self, mock_console_cls):
        from ai_guardian.cli import main

        with patch("sys.argv", ["ai-guardian", "console"]):
            result = main()

        assert result == 0
        mock_console_cls.return_value.run.assert_called_once_with(port=0, show=True)

    @patch("ai_guardian.web.WebConsole")
    def test_console_supports_no_open(self, mock_console_cls):
        from ai_guardian.cli import main

        with patch(
            "sys.argv",
            ["ai-guardian", "console", "--port", "8123", "--no-open"],
        ):
            result = main()

        assert result == 0
        mock_console_cls.return_value.run.assert_called_once_with(port=8123, show=False)

    @patch("ai_guardian.web.WebConsole")
    def test_tui_alias_uses_browser_console(self, mock_console_cls):
        from ai_guardian.cli import main

        with patch("sys.argv", ["ai-guardian", "tui"]):
            result = main()

        assert result == 0
        mock_console_cls.return_value.run.assert_called_once_with(port=0, show=True)
