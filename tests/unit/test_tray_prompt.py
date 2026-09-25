"""Tests for prompt --mode params (tray plugin parameter form) and CLI handler."""

import os
import tempfile
from unittest import mock

import pytest


class TestHandleTrayPrompt:
    """Tests for _handle_prompt_params CLI handler."""

    def test_rejects_invalid_json(self):
        from ai_guardian.cli_handlers import _handle_prompt_params

        args = mock.MagicMock()
        args.params = "not valid json"
        args.template = "echo"
        args.type = "terminal"
        result = _handle_prompt_params(args)
        assert result == 1

    def test_rejects_non_array_params(self):
        from ai_guardian.cli_handlers import _handle_prompt_params

        args = mock.MagicMock()
        args.params = '{"name": "not-an-array"}'
        args.template = "echo"
        args.type = "terminal"
        result = _handle_prompt_params(args)
        assert result == 1

    def test_handles_import_error(self):
        from ai_guardian.cli_handlers import _handle_prompt_params

        args = mock.MagicMock()
        args.params = '[{"name": "x"}]'
        args.template = "echo {tray.x}"
        args.type = "terminal"
        with mock.patch.dict("sys.modules", {"ai_guardian.tui.tray_prompt": None}):
            result = _handle_prompt_params(args)
        assert result == 1

    def test_rejects_non_tty_when_textual_fallback(self):
        """When tkinter unavailable and no TTY, should reject."""
        from ai_guardian.cli_handlers import _handle_prompt_params

        args = mock.MagicMock()
        args.params = '[{"name": "x"}]'
        args.template = "echo {tray.x}"
        args.type = "terminal"
        mock_app = mock.MagicMock()
        mock_app.needs_terminal = True
        with mock.patch(
            "ai_guardian.tui.tray_prompt.TrayPromptApp", return_value=mock_app
        ):
            with mock.patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = False
                result = _handle_prompt_params(args)
        assert result == 1

    def test_cancel_returns_zero(self):
        from ai_guardian.cli_handlers import _handle_prompt_params

        args = mock.MagicMock()
        args.params = '[{"name": "x"}]'
        args.template = "echo {tray.x}"
        args.type = "background"
        args.output_file = None
        mock_app = mock.MagicMock()
        mock_app.needs_terminal = False
        mock_app.run.return_value = None
        with mock.patch(
            "ai_guardian.tui.tray_prompt.TrayPromptApp", return_value=mock_app
        ):
            result = _handle_prompt_params(args)
        assert result == 0

    def test_screen_bounds_are_forwarded_to_prompt_app(self):
        from ai_guardian.cli_handlers import _handle_prompt_params

        args = mock.MagicMock()
        args.params = "[]"
        args.template = "echo hello"
        args.type = "terminal"
        args.output_file = None
        args.screen_bounds = "[1920, 37, 2560, 1380]"
        mock_app = mock.MagicMock()
        mock_app.needs_terminal = False
        mock_app.run.return_value = None
        with mock.patch(
            "ai_guardian.tui.tray_prompt.TrayPromptApp", return_value=mock_app
        ) as prompt_app:
            result = _handle_prompt_params(args)

        assert result == 0
        assert prompt_app.call_args.kwargs["screen_bounds"] == (
            1920,
            37,
            2560,
            1380,
        )

    def test_cancel_creates_empty_output_file(self):
        from ai_guardian.cli_handlers import _handle_prompt_params

        with tempfile.NamedTemporaryFile(delete=False, suffix=".cmd") as tmp:
            tmp_path = tmp.name
        os.unlink(tmp_path)
        try:
            args = mock.MagicMock()
            args.params = '[{"name": "x"}]'
            args.template = "echo {tray.x}"
            args.type = "terminal"
            args.output_file = tmp_path
            mock_app = mock.MagicMock()
            mock_app.needs_terminal = False
            mock_app.run.return_value = None
            with mock.patch(
                "ai_guardian.tui.tray_prompt.TrayPromptApp", return_value=mock_app
            ):
                result = _handle_prompt_params(args)
            assert result == 0
            assert os.path.exists(tmp_path)
            with open(tmp_path) as f:
                assert f.read() == ""
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_submit_writes_command_to_output_file(self):
        from ai_guardian.cli_handlers import _handle_prompt_params

        with tempfile.NamedTemporaryFile(delete=False, suffix=".cmd") as tmp:
            tmp_path = tmp.name
        os.unlink(tmp_path)
        try:
            args = mock.MagicMock()
            args.params = "[]"
            args.template = "echo hello"
            args.type = "terminal"
            args.output_file = tmp_path
            mock_app = mock.MagicMock()
            mock_app.needs_terminal = False
            mock_app.run.return_value = "echo hello"
            with mock.patch(
                "ai_guardian.tui.tray_prompt.TrayPromptApp", return_value=mock_app
            ):
                result = _handle_prompt_params(args)
            assert result == 0
            with open(tmp_path) as f:
                assert f.read() == "echo hello"
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_submit_prints_to_stdout_without_output_file(self, capsys):
        from ai_guardian.cli_handlers import _handle_prompt_params

        args = mock.MagicMock()
        args.params = "[]"
        args.template = "echo hello"
        args.type = "terminal"
        args.output_file = None
        mock_app = mock.MagicMock()
        mock_app.needs_terminal = False
        mock_app.run.return_value = "echo hello"
        with mock.patch(
            "ai_guardian.tui.tray_prompt.TrayPromptApp", return_value=mock_app
        ):
            result = _handle_prompt_params(args)
        assert result == 0
        assert capsys.readouterr().out.strip() == "echo hello"

    def test_shell_operators_written_to_output_file(self):
        from ai_guardian.cli_handlers import _handle_prompt_params

        with tempfile.NamedTemporaryFile(delete=False, suffix=".cmd") as tmp:
            tmp_path = tmp.name
        os.unlink(tmp_path)
        try:
            args = mock.MagicMock()
            args.params = "[]"
            args.template = "echo a && echo b"
            args.type = "background"
            args.output_file = tmp_path
            mock_app = mock.MagicMock()
            mock_app.needs_terminal = False
            mock_app.run.return_value = "echo a && echo b"
            with mock.patch(
                "ai_guardian.tui.tray_prompt.TrayPromptApp", return_value=mock_app
            ):
                result = _handle_prompt_params(args)
            assert result == 0
            with open(tmp_path) as f:
                assert f.read() == "echo a && echo b"
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestTrayPromptAppCreation:
    """Tests for TrayPromptApp construction (no GUI needed)."""

    def test_app_stores_params(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        params = [{"name": "env", "hint": "Environment", "default": "dev"}]
        app = TrayPromptApp(params, "deploy {tray.env}", "terminal")
        assert app._params == params
        assert app._command_template == "deploy {tray.env}"
        assert app._command_type == "terminal"

    def test_app_stores_tray_screen_bounds(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        bounds = (1920, 37, 2560, 1380)
        app = TrayPromptApp([], "echo", screen_bounds=bounds)

        assert app._screen_bounds == bounds

    def test_app_with_empty_params(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        app = TrayPromptApp([], "echo hello", "background")
        assert app._params == []

    def test_app_with_options_param(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        params = [{"name": "env", "options": ["dev", "staging", "prod"]}]
        app = TrayPromptApp(params, "deploy {tray.env}")
        assert app._params[0]["options"] == ["dev", "staging", "prod"]

    def test_app_stores_typed_params(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        params = [
            {"name": "count", "type": "int", "min": 1, "max": 10},
            {"name": "flag", "type": "boolean", "default": "true"},
            {"name": "branch", "required": True, "pattern": "^[a-z]+$"},
        ]
        app = TrayPromptApp(params, "cmd {tray.count} {tray.flag} {tray.branch}")
        assert app._params[0]["type"] == "int"
        assert app._params[1]["type"] == "boolean"
        assert app._params[2]["required"] is True

    def test_app_with_combobox_param(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        params = [{"name": "tag", "type": "combobox", "options": ["latest", "stable"]}]
        app = TrayPromptApp(params, "deploy --tag {tray.tag}")
        assert app._params[0]["type"] == "combobox"
        assert app._params[0]["options"] == ["latest", "stable"]

    def test_result_defaults_to_none(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        app = TrayPromptApp([], "echo hello")
        assert app._result is None

    def test_extra_vars_stored(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        extra = {"working_dir": "/tmp"}
        app = TrayPromptApp([], "echo", extra_vars=extra)
        assert app._extra_vars == extra

    def test_extra_vars_default_empty(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        app = TrayPromptApp([], "echo")
        assert app._extra_vars == {}

    def test_app_stores_path_file_param(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        params = [{"name": "file", "type": "path-file", "hint": "Pick a file"}]
        app = TrayPromptApp(params, "sanitize {tray.file}")
        assert app._params[0]["type"] == "path-file"

    def test_app_stores_path_dir_param(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        params = [{"name": "dir", "type": "path-dir", "default": "."}]
        app = TrayPromptApp(params, "scan {tray.dir}")
        assert app._params[0]["type"] == "path-dir"
        assert app._params[0]["default"] == "."


class TestTrayPromptFallback:
    """Tests for tkinter → NiceGUI → Textual cascade selection."""

    @pytest.fixture(autouse=True)
    def _enable_ui_cascade(self, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
        monkeypatch.delenv("AI_GUARDIAN_NO_TKINTER", raising=False)
        monkeypatch.delenv("AI_GUARDIAN_NO_NICEGUI", raising=False)

    def test_needs_terminal_false_when_tkinter_available(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        with mock.patch(
            "ai_guardian.tui.tray_prompt._tkinter_available", return_value=True
        ):
            app = TrayPromptApp([], "echo")
            assert app.needs_terminal is False

    def test_needs_terminal_false_when_nicegui_available(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        with mock.patch(
            "ai_guardian.tui.tray_prompt._tkinter_available", return_value=False
        ):
            with mock.patch(
                "ai_guardian.tui.tray_prompt._nicegui_available", return_value=True
            ):
                app = TrayPromptApp([], "echo")
                assert app.needs_terminal is False

    def test_needs_terminal_true_when_both_unavailable(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        with mock.patch(
            "ai_guardian.tui.tray_prompt._tkinter_available", return_value=False
        ):
            with mock.patch(
                "ai_guardian.tui.tray_prompt._nicegui_available", return_value=False
            ):
                app = TrayPromptApp([], "echo")
                assert app.needs_terminal is True

    def test_tkinter_available_returns_bool(self):
        from ai_guardian.tui.tray_prompt import _tkinter_available

        result = _tkinter_available()
        assert isinstance(result, bool)

    def test_nicegui_available_returns_bool(self):
        from ai_guardian.tui.tray_prompt import _nicegui_available

        result = _nicegui_available()
        assert isinstance(result, bool)

    def test_cascade_prefers_tkinter(self):
        """When both tkinter and NiceGUI are available, tkinter is used."""
        from ai_guardian.tui.tray_prompt import TrayPromptApp, _TkinterPromptApp

        with mock.patch(
            "ai_guardian.tui.tray_prompt._tkinter_available", return_value=True
        ):
            with mock.patch(
                "ai_guardian.tui.tray_prompt._nicegui_available", return_value=True
            ):
                with mock.patch.object(
                    _TkinterPromptApp, "run", return_value="echo ok"
                ) as mock_run:
                    app = TrayPromptApp([], "echo ok")
                    result = app.run()
                    mock_run.assert_called_once()
                    assert result == "echo ok"

    def test_cascade_uses_nicegui_when_no_tkinter(self):
        """When tkinter unavailable but NiceGUI available, NiceGUI is used."""
        from ai_guardian.tui.tray_prompt import TrayPromptApp, _NiceGuiPromptApp

        with mock.patch(
            "ai_guardian.tui.tray_prompt._tkinter_available", return_value=False
        ):
            with mock.patch(
                "ai_guardian.tui.tray_prompt._nicegui_available", return_value=True
            ):
                with mock.patch.object(
                    _NiceGuiPromptApp, "run", return_value="echo ng"
                ) as mock_run:
                    app = TrayPromptApp([], "echo ng")
                    result = app.run()
                    mock_run.assert_called_once()
                    assert result == "echo ng"

    def test_cascade_falls_back_to_textual(self):
        """When tkinter and NiceGUI both unavailable, Textual is used."""
        from ai_guardian.tui.tray_prompt import TrayPromptApp, _TextualPromptApp

        with mock.patch(
            "ai_guardian.tui.tray_prompt._tkinter_available", return_value=False
        ):
            with mock.patch(
                "ai_guardian.tui.tray_prompt._nicegui_available", return_value=False
            ):
                with mock.patch.object(
                    _TextualPromptApp, "run", return_value="echo tx"
                ) as mock_run:
                    app = TrayPromptApp([], "echo tx")
                    result = app.run()
                    mock_run.assert_called_once()
                    assert result == "echo tx"

    def test_env_var_suppresses_tkinter(self):
        """AI_GUARDIAN_NO_TKINTER=1 skips tkinter even when importable."""
        from ai_guardian.tui.tray_prompt import _tkinter_available

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_NO_TKINTER": "1"}):
            assert _tkinter_available() is False

    def test_env_var_suppresses_nicegui(self):
        """AI_GUARDIAN_NO_NICEGUI=1 skips NiceGUI even when importable."""
        from ai_guardian.tui.tray_prompt import _nicegui_available

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_NO_NICEGUI": "1"}):
            assert _nicegui_available() is False

    def test_env_var_unset_allows_tkinter(self):
        """Without AI_GUARDIAN_NO_TKINTER, tkinter availability is based on import."""
        from ai_guardian.tui.tray_prompt import _tkinter_available

        env = os.environ.copy()
        env.pop("AI_GUARDIAN_NO_TKINTER", None)
        with mock.patch.dict(os.environ, env, clear=True):
            result = _tkinter_available()
            assert isinstance(result, bool)

    def test_env_var_unset_allows_nicegui(self):
        """Without AI_GUARDIAN_NO_NICEGUI, NiceGUI availability is based on import."""
        from ai_guardian.tui.tray_prompt import _nicegui_available

        env = os.environ.copy()
        env.pop("AI_GUARDIAN_NO_NICEGUI", None)
        with mock.patch.dict(os.environ, env, clear=True):
            result = _nicegui_available()
            assert isinstance(result, bool)

    def test_tkinter_available_true_when_importable(self):
        """_tkinter_available() returns True when tkinter can be imported."""
        from ai_guardian.tui.tray_prompt import _tkinter_available

        mock_tk = mock.MagicMock()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_GUARDIAN_NO_TKINTER", None)
            with mock.patch.dict("sys.modules", {"tkinter": mock_tk}):
                assert _tkinter_available() is True

    def test_tkinter_available_false_on_import_error(self):
        """_tkinter_available() returns False when tkinter can't be imported."""
        from ai_guardian.tui.tray_prompt import _tkinter_available

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_GUARDIAN_NO_TKINTER", None)
            with mock.patch.dict("sys.modules", {"tkinter": None}):
                assert _tkinter_available() is False

    def test_cascade_falls_through_on_tkinter_runtime_error(self):
        """When tkinter check passes but run() crashes, falls back to NiceGUI."""
        from ai_guardian.tui.tray_prompt import (
            TrayPromptApp,
            _NiceGuiPromptApp,
            _TkinterPromptApp,
        )

        with mock.patch(
            "ai_guardian.tui.tray_prompt._tkinter_available", return_value=True
        ):
            with mock.patch(
                "ai_guardian.tui.tray_prompt._nicegui_available", return_value=True
            ):
                with mock.patch.object(
                    _TkinterPromptApp,
                    "run",
                    side_effect=Exception("TclError"),
                ):
                    with mock.patch.object(
                        _NiceGuiPromptApp,
                        "run",
                        return_value="echo ng",
                    ) as ng_run:
                        app = TrayPromptApp([], "echo ng")
                        result = app.run()
                        ng_run.assert_called_once()
                        assert result == "echo ng"

    def test_cascade_falls_through_to_textual_on_both_failure(self):
        """When tkinter crashes and NiceGUI unavailable, falls back to Textual."""
        from ai_guardian.tui.tray_prompt import (
            TrayPromptApp,
            _TextualPromptApp,
            _TkinterPromptApp,
        )

        with mock.patch(
            "ai_guardian.tui.tray_prompt._tkinter_available", return_value=True
        ):
            with mock.patch(
                "ai_guardian.tui.tray_prompt._nicegui_available", return_value=False
            ):
                with mock.patch.object(
                    _TkinterPromptApp,
                    "run",
                    side_effect=Exception("TclError"),
                ):
                    with mock.patch.object(
                        _TextualPromptApp,
                        "run",
                        return_value="echo tx",
                    ) as tx_run:
                        app = TrayPromptApp([], "echo tx")
                        result = app.run()
                        tx_run.assert_called_once()
                        assert result == "echo tx"


class TestNativeFilePicker:
    """Tests for _native_file_picker (platform-native dialogs)."""

    def test_returns_path_on_macos(self):
        from ai_guardian.tui.tray_prompt import _native_file_picker

        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "/Users/test/file.txt\n"
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch("subprocess.run", return_value=mock_result) as mock_run:
                path = _native_file_picker(pick_directory=False)
                assert path == "/Users/test/file.txt"
                cmd = mock_run.call_args[0][0]
                assert cmd[0] == "osascript"
                assert "choose file" in cmd[2]

    def test_returns_dir_on_macos(self):
        from ai_guardian.tui.tray_prompt import _native_file_picker

        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "/Users/test/\n"
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch("subprocess.run", return_value=mock_result):
                path = _native_file_picker(pick_directory=True)
                assert path == "/Users/test/"

    def test_returns_none_on_cancel(self):
        from ai_guardian.tui.tray_prompt import _native_file_picker

        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch("subprocess.run", return_value=mock_result):
                assert _native_file_picker() is None

    def test_returns_none_on_timeout(self):
        import subprocess as sp
        from ai_guardian.tui.tray_prompt import _native_file_picker

        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch(
                "subprocess.run", side_effect=sp.TimeoutExpired("cmd", 120)
            ):
                assert _native_file_picker() is None

    def test_returns_none_on_missing_tool(self):
        from ai_guardian.tui.tray_prompt import _native_file_picker

        with mock.patch("platform.system", return_value="Linux"):
            with mock.patch("subprocess.run", side_effect=FileNotFoundError):
                assert _native_file_picker() is None

    def test_linux_uses_zenity(self):
        from ai_guardian.tui.tray_prompt import _native_file_picker

        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "/home/test/file.txt\n"
        with mock.patch("platform.system", return_value="Linux"):
            with mock.patch("subprocess.run", return_value=mock_result) as mock_run:
                path = _native_file_picker(pick_directory=False)
                assert path == "/home/test/file.txt"
                cmd = mock_run.call_args[0][0]
                assert "zenity" in cmd
                assert "--directory" not in cmd

    def test_linux_zenity_directory_flag(self):
        from ai_guardian.tui.tray_prompt import _native_file_picker

        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "/home/test/\n"
        with mock.patch("platform.system", return_value="Linux"):
            with mock.patch("subprocess.run", return_value=mock_result) as mock_run:
                _native_file_picker(pick_directory=True)
                cmd = mock_run.call_args[0][0]
                assert "--directory" in cmd


class TestNiceGuiPromptAppCreation:
    """Tests for _NiceGuiPromptApp construction (no GUI needed)."""

    def test_stores_params(self):
        from ai_guardian.tui.tray_prompt import _NiceGuiPromptApp

        params = [{"name": "env", "hint": "Environment", "default": "dev"}]
        app = _NiceGuiPromptApp(params, "deploy {tray.env}", "terminal")
        assert app._params == params
        assert app._command_template == "deploy {tray.env}"
        assert app._command_type == "terminal"

    def test_default_title(self):
        from ai_guardian.tui.tray_prompt import _NiceGuiPromptApp

        app = _NiceGuiPromptApp([], "echo")
        assert app._title == "Plugin Parameters"

    def test_custom_title(self):
        from ai_guardian.tui.tray_prompt import _NiceGuiPromptApp

        app = _NiceGuiPromptApp([], "echo", title="My Form")
        assert app._title == "My Form"

    def test_extra_vars_stored(self):
        from ai_guardian.tui.tray_prompt import _NiceGuiPromptApp

        extra = {"working_dir": "/tmp"}
        app = _NiceGuiPromptApp([], "echo", extra_vars=extra)
        assert app._extra_vars == extra

    def test_extra_vars_default_empty(self):
        from ai_guardian.tui.tray_prompt import _NiceGuiPromptApp

        app = _NiceGuiPromptApp([], "echo")
        assert app._extra_vars == {}

    def test_result_defaults_to_none(self):
        from ai_guardian.tui.tray_prompt import _NiceGuiPromptApp

        app = _NiceGuiPromptApp([], "echo")
        assert app._result is None


class TestTrayPromptResolveDefault:
    """Tests for _resolve_default without launching GUI."""

    def test_plain_string_unchanged(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        app = TrayPromptApp([], "echo", extra_vars={"working_dir": "/home"})
        assert app._resolve_default("hello") == "hello"

    def test_empty_string_unchanged(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        app = TrayPromptApp([], "echo")
        assert app._resolve_default("") == ""

    def test_none_unchanged(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        app = TrayPromptApp([], "echo")
        assert app._resolve_default(None) is None

    def test_no_extra_vars_unchanged(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        app = TrayPromptApp([], "echo")
        assert app._resolve_default("{tray.working_dir}") == "{tray.working_dir}"
