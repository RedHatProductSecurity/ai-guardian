"""Tests for first-run auto-setup of tray shortcut, autostart, and tray launch."""

import subprocess
from unittest import mock

import pytest

from ai_guardian.daemon.auto_setup import (
    _is_ci_environment,
    _is_headless,
    _is_auto_install_disabled,
    _is_first_run,
    _start_tray_background,
    auto_setup_tray,
    notify_ide_setup_needed,
)


class TestIsCiEnvironment:
    @pytest.mark.parametrize(
        "var",
        [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ],
    )
    def test_detects_ci_env_var(self, var, monkeypatch):
        for v in [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ]:
            monkeypatch.delenv(v, raising=False)
        monkeypatch.setenv(var, "true")
        assert _is_ci_environment() is True

    def test_not_ci_when_no_vars_set(self, monkeypatch):
        for v in [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ]:
            monkeypatch.delenv(v, raising=False)
        assert _is_ci_environment() is False


class TestIsHeadless:
    def test_linux_no_display_is_headless(self, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        with mock.patch(
            "ai_guardian.daemon.auto_setup.platform.system", return_value="Linux"
        ):
            assert _is_headless() is True

    def test_linux_with_display_not_headless(self, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        with mock.patch(
            "ai_guardian.daemon.auto_setup.platform.system", return_value="Linux"
        ):
            assert _is_headless() is False

    def test_linux_with_wayland_not_headless(self, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        with mock.patch(
            "ai_guardian.daemon.auto_setup.platform.system", return_value="Linux"
        ):
            assert _is_headless() is False

    def test_macos_never_headless(self):
        with mock.patch(
            "ai_guardian.daemon.auto_setup.platform.system", return_value="Darwin"
        ):
            assert _is_headless() is False

    def test_windows_never_headless(self):
        with mock.patch(
            "ai_guardian.daemon.auto_setup.platform.system", return_value="Windows"
        ):
            assert _is_headless() is False


class TestIsAutoInstallDisabled:
    def test_none_config_means_enabled(self):
        assert _is_auto_install_disabled(None) is False

    def test_empty_config_means_enabled(self):
        assert _is_auto_install_disabled({}) is False

    def test_explicitly_true_means_enabled(self):
        config = {"daemon": {"tray": {"auto_install": True}}}
        assert _is_auto_install_disabled(config) is False

    def test_explicitly_false_means_disabled(self):
        config = {"daemon": {"tray": {"auto_install": False}}}
        assert _is_auto_install_disabled(config) is True

    def test_missing_tray_key_means_enabled(self):
        config = {"daemon": {}}
        assert _is_auto_install_disabled(config) is False


class TestIsFirstRun:
    def test_first_run_when_nothing_installed(self):
        desktop = mock.MagicMock()
        desktop.shortcut_exists.return_value = False
        desktop.autostart_exists.return_value = False
        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration", return_value=desktop
        ):
            assert _is_first_run() is True

    def test_not_first_run_when_shortcut_exists(self):
        desktop = mock.MagicMock()
        desktop.shortcut_exists.return_value = True
        desktop.autostart_exists.return_value = False
        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration", return_value=desktop
        ):
            assert _is_first_run() is False

    def test_not_first_run_when_autostart_exists(self):
        desktop = mock.MagicMock()
        desktop.shortcut_exists.return_value = False
        desktop.autostart_exists.return_value = True
        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration", return_value=desktop
        ):
            assert _is_first_run() is False

    def test_not_first_run_when_both_exist(self):
        desktop = mock.MagicMock()
        desktop.shortcut_exists.return_value = True
        desktop.autostart_exists.return_value = True
        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration", return_value=desktop
        ):
            assert _is_first_run() is False

    def test_not_first_run_on_unsupported_desktop(self):
        from ai_guardian.daemon.desktop import _UnsupportedDesktop

        desktop = _UnsupportedDesktop()
        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration", return_value=desktop
        ):
            assert _is_first_run() is False


class TestStartTrayBackground:
    def test_starts_tray_process(self):
        with mock.patch(
            "ai_guardian.daemon.get_executable_command",
            return_value=["/usr/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.auto_setup.subprocess.Popen"
            ) as mock_popen:
                with mock.patch(
                    "ai_guardian.daemon.auto_setup.platform.system",
                    return_value="Linux",
                ):
                    result = _start_tray_background()

        assert result is True
        mock_popen.assert_called_once()
        args = mock_popen.call_args
        assert args[0][0] == ["/usr/bin/ai-guardian", "tray", "start"]
        assert args[1]["start_new_session"] is True

    @pytest.mark.skipif(
        not hasattr(subprocess, "DETACHED_PROCESS"),
        reason="Windows-only subprocess flags",
    )
    def test_windows_uses_creation_flags(self):
        with mock.patch(
            "ai_guardian.daemon.get_executable_command",
            return_value=["ai-guardian.exe"],
        ):
            with mock.patch(
                "ai_guardian.daemon.auto_setup.subprocess.Popen"
            ) as mock_popen:
                with mock.patch(
                    "ai_guardian.daemon.auto_setup.platform.system",
                    return_value="Windows",
                ):
                    _start_tray_background()

        args = mock_popen.call_args
        assert "creationflags" in args[1]
        assert args[1]["creationflags"] == (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        )


class TestAutoSetupTray:
    def test_skips_in_ci(self, monkeypatch):
        monkeypatch.setenv("CI", "true")
        desktop = mock.MagicMock()
        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration", return_value=desktop
        ):
            auto_setup_tray()
        desktop.install_shortcut.assert_not_called()

    def test_skips_when_headless(self, monkeypatch):
        for v in [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ]:
            monkeypatch.delenv(v, raising=False)
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        desktop = mock.MagicMock()
        with (
            mock.patch(
                "ai_guardian.daemon.auto_setup.platform.system", return_value="Linux"
            ),
            mock.patch(
                "ai_guardian.daemon.desktop.get_desktop_integration",
                return_value=desktop,
            ),
        ):
            auto_setup_tray()
        desktop.install_shortcut.assert_not_called()

    def test_skips_when_disabled_by_config(self, monkeypatch):
        for v in [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ]:
            monkeypatch.delenv(v, raising=False)
        desktop = mock.MagicMock()
        config = {"daemon": {"tray": {"auto_install": False}}}
        with (
            mock.patch(
                "ai_guardian.daemon.auto_setup._is_headless", return_value=False
            ),
            mock.patch(
                "ai_guardian.config.loaders._load_config_file",
                return_value=(config, None),
            ),
            mock.patch(
                "ai_guardian.daemon.desktop.get_desktop_integration",
                return_value=desktop,
            ),
        ):
            auto_setup_tray()
        desktop.install_shortcut.assert_not_called()

    def test_skips_when_tray_unavailable(self, monkeypatch):
        for v in [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ]:
            monkeypatch.delenv(v, raising=False)
        desktop = mock.MagicMock()
        with (
            mock.patch(
                "ai_guardian.daemon.auto_setup._is_headless", return_value=False
            ),
            mock.patch(
                "ai_guardian.config.loaders._load_config_file", return_value=({}, None)
            ),
            mock.patch("ai_guardian.tray.app.is_tray_available", return_value=False),
            mock.patch(
                "ai_guardian.daemon.desktop.get_desktop_integration",
                return_value=desktop,
            ),
        ):
            auto_setup_tray()
        desktop.install_shortcut.assert_not_called()

    def test_skips_when_not_first_run(self, monkeypatch):
        for v in [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ]:
            monkeypatch.delenv(v, raising=False)
        desktop = mock.MagicMock()
        desktop.shortcut_exists.return_value = True
        desktop.autostart_exists.return_value = True
        with (
            mock.patch(
                "ai_guardian.daemon.auto_setup._is_headless", return_value=False
            ),
            mock.patch(
                "ai_guardian.config.loaders._load_config_file", return_value=({}, None)
            ),
            mock.patch("ai_guardian.tray.app.is_tray_available", return_value=True),
            mock.patch(
                "ai_guardian.daemon.desktop.get_desktop_integration",
                return_value=desktop,
            ),
        ):
            auto_setup_tray()
        desktop.install_shortcut.assert_not_called()

    def test_installs_shortcut_and_autostart_on_first_run(self, monkeypatch):
        for v in [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ]:
            monkeypatch.delenv(v, raising=False)
        desktop = mock.MagicMock()
        desktop.shortcut_exists.return_value = False
        desktop.autostart_exists.return_value = False
        desktop.install_shortcut.return_value = True
        desktop.install_autostart.return_value = True
        with (
            mock.patch(
                "ai_guardian.daemon.auto_setup._is_headless", return_value=False
            ),
            mock.patch(
                "ai_guardian.config.loaders._load_config_file", return_value=({}, None)
            ),
            mock.patch("ai_guardian.tray.app.is_tray_available", return_value=True),
            mock.patch(
                "ai_guardian.daemon.desktop.get_desktop_integration",
                return_value=desktop,
            ),
            mock.patch("ai_guardian.tray.app._is_tray_running", return_value=False),
            mock.patch("ai_guardian.daemon.auto_setup._start_tray_background"),
        ):
            auto_setup_tray()
        desktop.install_shortcut.assert_called_once()
        desktop.install_autostart.assert_called_once()


class TestNotifyIdeSetupNeeded:
    def _setup(self):
        setup = mock.MagicMock()
        setup.list_detected_ides.return_value = ["cursor"]
        setup.check_hooks_for_ide.return_value = (False, "Cursor IDE: not configured")
        setup.IDE_CONFIGS = {"cursor": {"name": "Cursor IDE"}}
        return setup

    def test_prints_notice_for_tty(self, capsys):
        with (
            mock.patch("ai_guardian.setup.hooks.IDESetup", return_value=self._setup()),
            mock.patch(
                "ai_guardian.daemon.auto_setup.sys.stdin.isatty", return_value=True
            ),
        ):
            notify_ide_setup_needed()

        assert "Cursor IDE" in capsys.readouterr().err

    def test_logs_notice_without_tty(self, caplog):
        with (
            mock.patch("ai_guardian.setup.hooks.IDESetup", return_value=self._setup()),
            mock.patch(
                "ai_guardian.daemon.auto_setup.sys.stdin.isatty", return_value=False
            ),
            caplog.at_level("INFO"),
        ):
            notify_ide_setup_needed()

        assert "IDE setup needed" in caplog.text

    def test_silent_when_all_detected_ides_configured(self, capsys):
        setup = self._setup()
        setup.check_hooks_for_ide.return_value = (True, "Cursor IDE: configured")
        with mock.patch("ai_guardian.setup.hooks.IDESetup", return_value=setup):
            notify_ide_setup_needed()

        assert capsys.readouterr().err == ""

    def test_skips_non_local_runtime(self, capsys):
        with mock.patch("ai_guardian.setup.hooks.IDESetup") as setup_class:
            notify_ide_setup_needed(runtime="container")

        setup_class.assert_not_called()
        assert capsys.readouterr().err == ""

    def test_starts_tray_when_not_running(self, monkeypatch):
        for v in [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ]:
            monkeypatch.delenv(v, raising=False)
        desktop = mock.MagicMock()
        desktop.shortcut_exists.return_value = False
        desktop.autostart_exists.return_value = False
        desktop.install_shortcut.return_value = True
        desktop.install_autostart.return_value = True
        with (
            mock.patch(
                "ai_guardian.daemon.auto_setup._is_headless", return_value=False
            ),
            mock.patch(
                "ai_guardian.config.loaders._load_config_file", return_value=({}, None)
            ),
            mock.patch("ai_guardian.tray.app.is_tray_available", return_value=True),
            mock.patch(
                "ai_guardian.daemon.desktop.get_desktop_integration",
                return_value=desktop,
            ),
            mock.patch("ai_guardian.tray.app._is_tray_running", return_value=False),
            mock.patch(
                "ai_guardian.daemon.auto_setup._start_tray_background"
            ) as mock_start,
        ):
            auto_setup_tray()
        mock_start.assert_called_once()

    def test_skips_tray_start_if_already_running(self, monkeypatch):
        for v in [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ]:
            monkeypatch.delenv(v, raising=False)
        desktop = mock.MagicMock()
        desktop.shortcut_exists.return_value = False
        desktop.autostart_exists.return_value = False
        desktop.install_shortcut.return_value = True
        desktop.install_autostart.return_value = True
        with (
            mock.patch(
                "ai_guardian.daemon.auto_setup._is_headless", return_value=False
            ),
            mock.patch(
                "ai_guardian.config.loaders._load_config_file", return_value=({}, None)
            ),
            mock.patch("ai_guardian.tray.app.is_tray_available", return_value=True),
            mock.patch(
                "ai_guardian.daemon.desktop.get_desktop_integration",
                return_value=desktop,
            ),
            mock.patch("ai_guardian.tray.app._is_tray_running", return_value=12345),
            mock.patch(
                "ai_guardian.daemon.auto_setup._start_tray_background"
            ) as mock_start,
        ):
            auto_setup_tray()
        mock_start.assert_not_called()

    def test_never_raises_on_exception(self):
        with mock.patch(
            "ai_guardian.daemon.auto_setup._is_ci_environment",
            side_effect=RuntimeError("unexpected"),
        ):
            auto_setup_tray()

    def test_never_raises_on_install_failure(self, monkeypatch):
        for v in [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ]:
            monkeypatch.delenv(v, raising=False)
        desktop = mock.MagicMock()
        desktop.shortcut_exists.return_value = False
        desktop.autostart_exists.return_value = False
        desktop.install_shortcut.side_effect = OSError("permission denied")
        with (
            mock.patch(
                "ai_guardian.daemon.auto_setup._is_headless", return_value=False
            ),
            mock.patch(
                "ai_guardian.config.loaders._load_config_file", return_value=({}, None)
            ),
            mock.patch("ai_guardian.tray.app.is_tray_available", return_value=True),
            mock.patch(
                "ai_guardian.daemon.desktop.get_desktop_integration",
                return_value=desktop,
            ),
        ):
            auto_setup_tray()

    def test_no_stdout_output(self, monkeypatch, capsys):
        for v in [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ]:
            monkeypatch.delenv(v, raising=False)
        desktop = mock.MagicMock()
        desktop.shortcut_exists.return_value = False
        desktop.autostart_exists.return_value = False
        desktop.install_shortcut.return_value = True
        desktop.install_autostart.return_value = True
        with (
            mock.patch(
                "ai_guardian.daemon.auto_setup._is_headless", return_value=False
            ),
            mock.patch(
                "ai_guardian.config.loaders._load_config_file", return_value=({}, None)
            ),
            mock.patch("ai_guardian.tray.app.is_tray_available", return_value=True),
            mock.patch(
                "ai_guardian.daemon.desktop.get_desktop_integration",
                return_value=desktop,
            ),
            mock.patch("ai_guardian.tray.app._is_tray_running", return_value=False),
            mock.patch("ai_guardian.daemon.auto_setup._start_tray_background"),
        ):
            auto_setup_tray()
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_handles_config_load_failure(self, monkeypatch):
        for v in [
            "CI",
            "GITHUB_ACTIONS",
            "JENKINS_URL",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "CODEBUILD_BUILD_ID",
            "TF_BUILD",
        ]:
            monkeypatch.delenv(v, raising=False)
        desktop = mock.MagicMock()
        desktop.shortcut_exists.return_value = False
        desktop.autostart_exists.return_value = False
        desktop.install_shortcut.return_value = True
        desktop.install_autostart.return_value = True
        with (
            mock.patch(
                "ai_guardian.daemon.auto_setup._is_headless", return_value=False
            ),
            mock.patch(
                "ai_guardian.config.loaders._load_config_file",
                side_effect=Exception("config error"),
            ),
            mock.patch("ai_guardian.tray.app.is_tray_available", return_value=True),
            mock.patch(
                "ai_guardian.daemon.desktop.get_desktop_integration",
                return_value=desktop,
            ),
            mock.patch("ai_guardian.tray.app._is_tray_running", return_value=False),
            mock.patch("ai_guardian.daemon.auto_setup._start_tray_background"),
        ):
            auto_setup_tray()
        desktop.install_shortcut.assert_called_once()
