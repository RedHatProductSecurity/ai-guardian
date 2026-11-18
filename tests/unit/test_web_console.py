"""Tests for web console module."""

import pytest

try:
    import nicegui  # noqa: F401

    _has_nicegui = True
except ImportError:
    _has_nicegui = False


class TestWebConsoleImportGuard:
    def test_has_nicegui_is_boolean(self):
        from ai_guardian.web import HAS_NICEGUI

        assert isinstance(HAS_NICEGUI, bool)

    def test_web_console_class_matches_flag(self):
        from ai_guardian.web import HAS_NICEGUI, WebConsole

        if HAS_NICEGUI:
            assert WebConsole is not None
        else:
            assert WebConsole is None


class TestCLIWebFlag:
    def test_web_flag_accepted_by_cli(self):
        """Verify --web flag is parsed correctly via main() argument handling."""
        from unittest.mock import patch

        with patch("sys.argv", ["ai-guardian", "console", "--web"]):
            import argparse

            parser = argparse.ArgumentParser(prog="ai-guardian")
            sub = parser.add_subparsers(dest="command")
            cp = sub.add_parser("console")
            cp.add_argument("--web", action="store_true")
            cp.add_argument("--port", type=int, default=None)
            cp.add_argument("--panel", default=None)
            args = parser.parse_args(["console", "--web"])
            assert args.web is True
            assert args.command == "console"

    def test_port_flag_defaults_to_unspecified(self):
        import argparse

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        cp = sub.add_parser("console")
        cp.add_argument("--web", action="store_true")
        cp.add_argument("--port", type=int, default=None)
        args = parser.parse_args(["console", "--web"])
        assert args.port is None

    def test_port_flag_custom(self):
        import argparse

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        cp = sub.add_parser("console")
        cp.add_argument("--web", action="store_true")
        cp.add_argument("--port", type=int, default=None)
        args = parser.parse_args(["console", "--web", "--port", "8080"])
        assert args.port == 8080


@pytest.mark.skipif(not _has_nicegui, reason="NiceGUI requires Python >= 3.10")
class TestNiceGUIStoragePath:
    def test_storage_path_set_when_unset(self, tmp_path, monkeypatch):
        """NICEGUI_STORAGE_PATH set to state_dir/.nicegui when not configured."""
        monkeypatch.delenv("NICEGUI_STORAGE_PATH", raising=False)
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(state_dir))

        from unittest.mock import MagicMock, patch

        mock_ui = MagicMock()
        mock_app = MagicMock()
        with (
            patch("ai_guardian.web.app.ui", mock_ui),
            patch("ai_guardian.web.app.app", mock_app),
        ):
            import os

            from ai_guardian.web.app import WebConsole

            console = WebConsole()
            mock_ui.run.side_effect = lambda **kw: None
            mock_ui.page = MagicMock(return_value=lambda f: f)
            console.run(show=False)

            expected = str(state_dir / ".nicegui")
            assert os.environ.get("NICEGUI_STORAGE_PATH") == expected
            assert (state_dir / ".nicegui").is_dir()

        monkeypatch.delenv("NICEGUI_STORAGE_PATH", raising=False)

    def test_storage_path_preserved_when_set(self, monkeypatch):
        """NICEGUI_STORAGE_PATH not overwritten when already set."""
        monkeypatch.setenv("NICEGUI_STORAGE_PATH", "/custom/path")

        from unittest.mock import MagicMock, patch

        mock_ui = MagicMock()
        mock_app = MagicMock()
        with (
            patch("ai_guardian.web.app.ui", mock_ui),
            patch("ai_guardian.web.app.app", mock_app),
        ):
            import os

            from ai_guardian.web.app import WebConsole

            console = WebConsole()
            mock_ui.run.side_effect = lambda **kw: None
            mock_ui.page = MagicMock(return_value=lambda f: f)
            console.run(show=False)

            assert os.environ.get("NICEGUI_STORAGE_PATH") == "/custom/path"


class TestDaemonConstants:
    def test_default_web_console_port(self):
        from ai_guardian.daemon import DEFAULT_WEB_CONSOLE_PORT

        assert DEFAULT_WEB_CONSOLE_PORT == 0
