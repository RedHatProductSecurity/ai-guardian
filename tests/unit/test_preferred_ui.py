"""Tests for preferred_ui config option (Issue #1135).

Covers: get_preferred_ui(), cascade logic in cli_handlers, tray_prompt,
and ask_dialog headless shortcut.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestGetPreferredUi:
    """Tests for get_preferred_ui() in display.py."""

    def test_default_is_auto(self):
        from ai_guardian.tui.display import get_preferred_ui

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_GUARDIAN_PREFERRED_UI", None)
            with patch("ai_guardian.config.utils.get_config_dir") as mock_dir:
                mock_dir.return_value = Path("/nonexistent")
                assert get_preferred_ui() == "auto"

    @pytest.mark.parametrize(
        "value", ["auto", "tkinter", "nicegui", "textual", "headless"]
    )
    def test_env_var_valid_values(self, value):
        from ai_guardian.tui.display import get_preferred_ui

        with patch.dict(os.environ, {"AI_GUARDIAN_PREFERRED_UI": value}):
            assert get_preferred_ui() == value

    def test_env_var_case_insensitive(self):
        from ai_guardian.tui.display import get_preferred_ui

        with patch.dict(os.environ, {"AI_GUARDIAN_PREFERRED_UI": "HEADLESS"}):
            assert get_preferred_ui() == "headless"

    def test_env_var_invalid_falls_to_config(self, tmp_path):
        from ai_guardian.tui.display import get_preferred_ui

        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"console": {"preferred_ui": "nicegui"}}))
        with patch.dict(os.environ, {"AI_GUARDIAN_PREFERRED_UI": "invalid"}):
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ):
                assert get_preferred_ui() == "nicegui"

    def test_reads_from_config_file(self, tmp_path):
        from ai_guardian.tui.display import get_preferred_ui

        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"console": {"preferred_ui": "textual"}}))
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_GUARDIAN_PREFERRED_UI", None)
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ):
                assert get_preferred_ui() == "textual"

    def test_invalid_config_value_falls_to_auto(self, tmp_path):
        from ai_guardian.tui.display import get_preferred_ui

        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(
            json.dumps({"console": {"preferred_ui": "invalid_value"}})
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_GUARDIAN_PREFERRED_UI", None)
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ):
                assert get_preferred_ui() == "auto"

    def test_missing_console_section(self, tmp_path):
        from ai_guardian.tui.display import get_preferred_ui

        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"secret_scanning": {}}))
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_GUARDIAN_PREFERRED_UI", None)
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ):
                assert get_preferred_ui() == "auto"

    def test_env_var_overrides_config(self, tmp_path):
        from ai_guardian.tui.display import get_preferred_ui

        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"console": {"preferred_ui": "nicegui"}}))
        with patch.dict(os.environ, {"AI_GUARDIAN_PREFERRED_UI": "headless"}):
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ):
                assert get_preferred_ui() == "headless"


class TestSelectUiProvider:
    """Tests for tray dialog provider precedence."""

    def test_macos_auto_prefers_native_for_simple_dialogs(self):
        from ai_guardian.tui.display import select_ui_provider

        with (
            patch("ai_guardian.tui.display.get_preferred_ui", return_value="auto"),
            patch("ai_guardian.tui.display.platform.system", return_value="Darwin"),
            patch("ai_guardian.tui.display._tkinter_available", return_value=False),
            patch("ai_guardian.tui.display._nicegui_available", return_value=False),
            patch("ai_guardian.tui.display._textual_installed", return_value=False),
        ):
            assert select_ui_provider("simple") == "native"

    def test_macos_auto_uses_available_tk_for_placed_action(self):
        from ai_guardian.tui.display import select_ui_provider

        with (
            patch("ai_guardian.tui.display.get_preferred_ui", return_value="auto"),
            patch("ai_guardian.tui.display.platform.system", return_value="Darwin"),
            patch("ai_guardian.tui.display._tkinter_available", return_value=True),
        ):
            assert select_ui_provider("action", screen_bounds=(0, 0, 100, 100)) == (
                "tkinter"
            )

    def test_headless_never_checks_optional_providers(self):
        from ai_guardian.tui.display import select_ui_provider

        with (
            patch("ai_guardian.tui.display.get_preferred_ui", return_value="headless"),
            patch("ai_guardian.tui.display._tkinter_available") as tkinter,
            patch("ai_guardian.tui.display._nicegui_available") as nicegui,
        ):
            assert select_ui_provider("form") == "headless"
            tkinter.assert_not_called()
            nicegui.assert_not_called()

    def test_nicegui_preference_does_not_fall_back_to_tk(self):
        from ai_guardian.tui.display import select_ui_provider

        with (
            patch("ai_guardian.tui.display.get_preferred_ui", return_value="nicegui"),
            patch("ai_guardian.tui.display._nicegui_available", return_value=True),
            patch("ai_guardian.tui.display._tkinter_available", return_value=True),
        ):
            assert select_ui_provider("form") == "nicegui"


class TestAskDialogHeadless:
    """Tests for show_ask_dialog() headless shortcut."""

    def test_headless_skips_daemon_and_subprocess(self):
        from ai_guardian.tui.ask_dialog import (
            show_ask_dialog,
            AskViolationInfo,
            AskDecision,
        )

        violation = AskViolationInfo(
            violation_type="secret_detected",
            summary="test",
            matched_text="***",
            config_section="secret_scanning",
            error_message="found secret",
        )
        with patch("ai_guardian.tui.display.get_preferred_ui", return_value="headless"):
            with patch("ai_guardian.tui.ask_dialog._show_via_daemon") as mock_daemon:
                with patch(
                    "ai_guardian.tui.ask_dialog._show_via_subprocess"
                ) as mock_sub:
                    result = show_ask_dialog(violation, fallback_action="block")
                    mock_daemon.assert_not_called()
                    mock_sub.assert_not_called()
                    assert result.decision == AskDecision.BLOCK

    def test_headless_warn_fallback(self):
        from ai_guardian.tui.ask_dialog import (
            show_ask_dialog,
            AskViolationInfo,
            AskDecision,
        )

        violation = AskViolationInfo(
            violation_type="secret_detected",
            summary="test",
            matched_text="***",
            config_section="secret_scanning",
            error_message="found secret",
        )
        with patch("ai_guardian.tui.display.get_preferred_ui", return_value="headless"):
            result = show_ask_dialog(violation, fallback_action="warn")
            assert result.decision == AskDecision.ALLOW_ONCE

    def test_auto_tries_daemon_first(self):
        from ai_guardian.tui.ask_dialog import (
            show_ask_dialog,
            AskViolationInfo,
            AskResult,
            AskDecision,
        )

        violation = AskViolationInfo(
            violation_type="secret_detected",
            summary="test",
            matched_text="***",
            config_section="secret_scanning",
            error_message="found secret",
        )
        mock_result = AskResult(decision=AskDecision.ALLOW_ONCE)
        with patch("ai_guardian.tui.display.get_preferred_ui", return_value="auto"):
            with patch(
                "ai_guardian.tui.ask_dialog._show_via_tray_forwarding",
                return_value=None,
            ):
                with patch(
                    "ai_guardian.tui.ask_dialog._is_headless_env", return_value=False
                ):
                    with patch(
                        "ai_guardian.tui.ask_dialog._show_via_daemon",
                        return_value=mock_result,
                    ) as mock_daemon:
                        result = show_ask_dialog(violation)
                        mock_daemon.assert_called_once()
                        assert result.decision == AskDecision.ALLOW_ONCE


class TestIsHeadlessEnv:
    """Tests for _is_headless_env() TTY and container detection (Issue #1448)."""

    def _call(
        self,
        preferred="auto",
        display=None,
        wayland=None,
        platform="linux",
        isatty=False,
        dockerenv=False,
        containerenv=False,
    ):
        from ai_guardian.tui.ask_dialog import _is_headless_env

        env = {}
        if display:
            env["DISPLAY"] = display
        if wayland:
            env["WAYLAND_DISPLAY"] = wayland

        with patch("ai_guardian.tui.display.get_preferred_ui", return_value=preferred):
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("DISPLAY", None)
                os.environ.pop("WAYLAND_DISPLAY", None)
                if display:
                    os.environ["DISPLAY"] = display
                if wayland:
                    os.environ["WAYLAND_DISPLAY"] = wayland
                with patch("sys.platform", platform):
                    with (
                        patch("sys.stdin") as mock_stdin,
                        patch("sys.stdout") as mock_stdout,
                    ):
                        mock_stdin.isatty = lambda: isatty
                        mock_stdout.isatty = lambda: isatty
                        with patch(
                            "os.path.exists",
                            side_effect=lambda p: (p == "/.dockerenv" and dockerenv)
                            or (p == "/run/.containerenv" and containerenv),
                        ):
                            return _is_headless_env()

    def test_explicit_headless_preferred(self):
        assert self._call(preferred="headless") is True

    def test_explicit_non_auto_non_headless(self):
        assert self._call(preferred="textual") is False

    def test_non_linux_returns_false(self):
        assert self._call(platform="darwin") is False

    def test_display_set_returns_false(self):
        assert self._call(display=":0") is False

    def test_wayland_set_returns_false(self):
        assert self._call(wayland="wayland-0") is False

    def test_no_display_no_tty_no_container_returns_true(self):
        assert self._call(isatty=False) is True

    def test_no_display_with_tty_not_container_returns_false(self):
        # SSH session / local terminal without DISPLAY — Textual can run
        assert self._call(isatty=True) is False

    def test_no_display_with_tty_dockerenv_returns_true(self):
        # Container with -it flag — no user watching container terminal
        assert self._call(isatty=True, dockerenv=True) is True

    def test_no_display_with_tty_containerenv_returns_true(self):
        # Podman/OCI container with -it flag
        assert self._call(isatty=True, containerenv=True) is True

    def test_no_display_no_tty_dockerenv_returns_true(self):
        # Container without TTY
        assert self._call(isatty=False, dockerenv=True) is True


class TestCliHandlerPreferredUi:
    """Tests for _handle_prompt_ask() with preferred_ui."""

    def _make_args(self, violation_data):
        args = MagicMock()
        args.violation = json.dumps(violation_data)
        args.fallback = "block"
        args.timeout = 300
        args.output_file = None
        return args

    def test_headless_skips_all_ui(self):
        from ai_guardian.cli_handlers import _handle_prompt_ask

        args = self._make_args(
            {
                "violation_type": "secret_detected",
                "summary": "test",
                "matched_text": "***",
                "config_section": "secret_scanning",
                "error_message": "found",
            }
        )
        with patch("ai_guardian.tui.display.get_preferred_ui", return_value="headless"):
            with patch("ai_guardian.tui.display._tkinter_available") as mock_tk:
                with patch("ai_guardian.tui.display._nicegui_available") as mock_ng:
                    result = _handle_prompt_ask(args)
                    mock_tk.assert_not_called()
                    mock_ng.assert_not_called()
                    assert result == 0

    def test_tkinter_preference_only_tries_tkinter(self):
        from ai_guardian.cli_handlers import _handle_prompt_ask
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        args = self._make_args(
            {
                "violation_type": "secret_detected",
                "summary": "test",
                "matched_text": "***",
                "config_section": "secret_scanning",
                "error_message": "found",
            }
        )
        mock_result = AskResult(decision=AskDecision.BLOCK)
        mock_dialog = MagicMock()
        mock_dialog.run.return_value = mock_result
        with patch("ai_guardian.tui.display.get_preferred_ui", return_value="tkinter"):
            with patch("ai_guardian.tui.display._tkinter_available", return_value=True):
                with patch(
                    "ai_guardian.tui.ask_dialog._TkinterAskDialog",
                    return_value=mock_dialog,
                ):
                    with patch("ai_guardian.tui.display._nicegui_available") as mock_ng:
                        _handle_prompt_ask(args)
                        mock_ng.assert_not_called()

    def test_auto_cascade(self):
        from ai_guardian.cli_handlers import _handle_prompt_ask

        args = self._make_args(
            {
                "violation_type": "secret_detected",
                "summary": "test",
                "matched_text": "***",
                "config_section": "secret_scanning",
                "error_message": "found",
            }
        )
        with patch("ai_guardian.tui.display.get_preferred_ui", return_value="auto"):
            with patch(
                "ai_guardian.tui.display._tkinter_available", return_value=False
            ):
                with patch(
                    "ai_guardian.tui.display._nicegui_available", return_value=False
                ):
                    result = _handle_prompt_ask(args)
                    assert result == 0


class TestTrayPromptPreferredUi:
    """Tests for TrayPromptApp with preferred_ui."""

    def test_headless_raises(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        with patch(
            "ai_guardian.tui.tray_prompt.get_preferred_ui", return_value="headless"
        ):
            app = TrayPromptApp([], "echo", "terminal")
            assert app.needs_terminal is False
            with pytest.raises(RuntimeError, match="headless"):
                app.run()

    def test_needs_terminal_textual(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        with patch(
            "ai_guardian.tui.tray_prompt.get_preferred_ui", return_value="textual"
        ):
            app = TrayPromptApp([], "echo", "terminal")
            assert app.needs_terminal is True

    def test_needs_terminal_tkinter(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        with patch(
            "ai_guardian.tui.tray_prompt.get_preferred_ui", return_value="tkinter"
        ):
            app = TrayPromptApp([], "echo", "terminal")
            assert app.needs_terminal is False

    def test_needs_terminal_auto_fallback(self):
        from ai_guardian.tui.tray_prompt import TrayPromptApp

        with patch("ai_guardian.tui.tray_prompt.get_preferred_ui", return_value="auto"):
            with patch(
                "ai_guardian.tui.tray_prompt._tkinter_available", return_value=False
            ):
                with patch(
                    "ai_guardian.tui.tray_prompt._nicegui_available", return_value=False
                ):
                    app = TrayPromptApp([], "echo", "terminal")
                    assert app.needs_terminal is True


class TestConsoleSettingsPreferredUi:
    """Tests for load/save preferred_ui in console_settings."""

    def test_load_default(self, tmp_path):
        from ai_guardian.tui.console_settings import load_preferred_ui

        with patch(
            "ai_guardian.tui.console_settings.get_config_dir", return_value=tmp_path
        ):
            assert load_preferred_ui() == "auto"

    def test_load_from_config(self, tmp_path):
        from ai_guardian.tui.console_settings import load_preferred_ui

        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({"console": {"preferred_ui": "headless"}}))
        with patch(
            "ai_guardian.tui.console_settings.get_config_dir", return_value=tmp_path
        ):
            assert load_preferred_ui() == "headless"

    def test_save_creates_console_section(self, tmp_path):
        from ai_guardian.tui.console_settings import save_preferred_ui

        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(json.dumps({}))
        with (
            patch(
                "ai_guardian.tui.console_settings.get_config_dir", return_value=tmp_path
            ),
            patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=tmp_path,
            ),
        ):
            success, error = save_preferred_ui("nicegui")
            assert success is True
            config = json.loads(config_path.read_text())
            assert config["console"]["preferred_ui"] == "nicegui"

    def test_save_preserves_other_settings(self, tmp_path):
        from ai_guardian.tui.console_settings import save_preferred_ui

        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text(
            json.dumps(
                {
                    "console": {"editor_theme": "dracula"},
                    "secret_scanning": {"enabled": True},
                }
            )
        )
        with (
            patch(
                "ai_guardian.tui.console_settings.get_config_dir", return_value=tmp_path
            ),
            patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=tmp_path,
            ),
        ):
            success, _ = save_preferred_ui("textual")
            assert success is True
            config = json.loads(config_path.read_text())
            assert config["console"]["editor_theme"] == "dracula"
            assert config["console"]["preferred_ui"] == "textual"
            assert config["secret_scanning"]["enabled"] is True
