"""Tests for the browser console command."""

from unittest.mock import patch

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


class TestConsoleCommand:
    @patch("ai_guardian.web.WebConsole")
    def test_console_does_not_require_a_tty(self, mock_console_cls):
        from ai_guardian.cli import main

        with (
            patch("ai_guardian.cli._load_config_file", return_value=(None, None)),
            patch("sys.argv", ["ai-guardian", "console"]),
        ):
            result = main()

        assert result == 0
        mock_console_cls.return_value.run.assert_called_once_with(
            host="127.0.0.1", port=0, show=True
        )

    @patch("ai_guardian.web.WebConsole")
    def test_console_supports_no_open(self, mock_console_cls):
        from ai_guardian.cli import main

        with (
            patch("ai_guardian.cli._load_config_file", return_value=(None, None)),
            patch(
                "sys.argv",
                ["ai-guardian", "console", "--port", "8123", "--no-open"],
            ),
        ):
            result = main()

        assert result == 0
        mock_console_cls.return_value.run.assert_called_once_with(
            host="127.0.0.1", port=8123, show=False
        )

    @patch("ai_guardian.web.WebConsole")
    def test_console_uses_configured_web_settings(self, mock_console_cls):
        from ai_guardian.cli import main

        config = {"console": {"web": {"host": "0.0.0.0", "port": 8088}}}
        with (
            patch("ai_guardian.cli._load_config_file", return_value=(config, None)),
            patch("sys.argv", ["ai-guardian", "console"]),
        ):
            result = main()

        assert result == 0
        mock_console_cls.return_value.run.assert_called_once_with(
            host="0.0.0.0", port=8088, show=True
        )

    @patch("ai_guardian.web.WebConsole")
    def test_explicit_port_overrides_configured_port(self, mock_console_cls):
        from ai_guardian.cli import main

        config = {"console": {"web": {"host": "0.0.0.0", "port": 8088}}}
        with (
            patch("ai_guardian.cli._load_config_file", return_value=(config, None)),
            patch("sys.argv", ["ai-guardian", "console", "--port", "8123"]),
        ):
            result = main()

        assert result == 0
        mock_console_cls.return_value.run.assert_called_once_with(
            host="0.0.0.0", port=8123, show=True
        )

    @patch("ai_guardian.web.WebConsole")
    def test_explicit_zero_port_overrides_configured_port(self, mock_console_cls):
        from ai_guardian.cli import main

        config = {"console": {"web": {"host": "0.0.0.0", "port": 8088}}}
        with (
            patch("ai_guardian.cli._load_config_file", return_value=(config, None)),
            patch("sys.argv", ["ai-guardian", "console", "--port", "0"]),
        ):
            result = main()

        assert result == 0
        mock_console_cls.return_value.run.assert_called_once_with(
            host="0.0.0.0", port=0, show=True
        )

    @patch("ai_guardian.web.WebConsole")
    def test_tui_alias_uses_browser_console(self, mock_console_cls):
        from ai_guardian.cli import main

        with (
            patch("ai_guardian.cli._load_config_file", return_value=(None, None)),
            patch("sys.argv", ["ai-guardian", "tui"]),
        ):
            result = main()

        assert result == 0
        mock_console_cls.return_value.run.assert_called_once_with(
            host="127.0.0.1", port=0, show=True
        )
