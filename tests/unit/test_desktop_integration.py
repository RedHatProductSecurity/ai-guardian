"""Tests for desktop shortcut and autostart integration."""

import stat
import sys
from unittest import mock

import pytest

from ai_guardian.daemon.desktop import (
    LinuxDesktop,
    MacOSDesktop,
    WindowsDesktop,
    _UnsupportedDesktop,
    _get_executable_command,
    _prepare_icon,
    _prepare_ico,
    get_desktop_integration,
)


class TestGetDesktopIntegration:
    def test_returns_linux_on_linux(self):
        with mock.patch(
            "ai_guardian.daemon.desktop.platform.system", return_value="Linux"
        ):
            result = get_desktop_integration()
        assert isinstance(result, LinuxDesktop)

    def test_returns_macos_on_darwin(self):
        with mock.patch(
            "ai_guardian.daemon.desktop.platform.system", return_value="Darwin"
        ):
            result = get_desktop_integration()
        assert isinstance(result, MacOSDesktop)

    def test_returns_windows_on_windows(self):
        with mock.patch(
            "ai_guardian.daemon.desktop.platform.system", return_value="Windows"
        ):
            result = get_desktop_integration()
        assert isinstance(result, WindowsDesktop)

    def test_returns_unsupported_on_unknown(self):
        with mock.patch(
            "ai_guardian.daemon.desktop.platform.system", return_value="FreeBSD"
        ):
            result = get_desktop_integration()
        assert isinstance(result, _UnsupportedDesktop)


class TestGetExecutableCommand:
    def test_uses_current_interpreter_even_when_path_has_another_install(self):
        with (
            mock.patch("sys.executable", "/venv/bin/python"),
            mock.patch("shutil.which", return_value="/old/bin/ai-guardian") as which,
        ):
            result = _get_executable_command()
        assert result == ["/venv/bin/python", "-m", "ai_guardian"]
        which.assert_not_called()


class TestPrepareIcon:
    def test_returns_cached_icon_if_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        cached = tmp_path / "icon-256.png"
        cached.write_text("fake")
        result = _prepare_icon(256)
        assert result == cached

    def test_returns_none_when_no_source_icon(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        with mock.patch(
            "ai_guardian.daemon.desktop._find_banner_icon", return_value=None
        ):
            result = _prepare_icon(256)
        assert result is None

    def test_generates_icon_from_source(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))

        from PIL import Image

        source_img = Image.new("RGBA", (320, 175), (100, 100, 200, 255))
        source_path = tmp_path / "source.png"
        source_img.save(str(source_path))

        with mock.patch(
            "ai_guardian.daemon.desktop._find_banner_icon",
            return_value=str(source_path),
        ):
            result = _prepare_icon(256)

        assert result is not None
        assert result.exists()
        generated = Image.open(str(result))
        assert generated.size == (256, 256)


class TestPrepareIco:
    def test_returns_cached_ico_if_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        cached = tmp_path / "icon.ico"
        cached.write_text("fake")
        result = _prepare_ico()
        assert result == cached

    def test_returns_none_when_no_png(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        with mock.patch("ai_guardian.daemon.desktop._prepare_icon", return_value=None):
            result = _prepare_ico()
        assert result is None


class TestUnsupportedDesktop:
    def test_shortcut_exists_is_false(self):
        d = _UnsupportedDesktop()
        assert d.shortcut_exists() is False

    def test_install_shortcut_returns_false(self):
        d = _UnsupportedDesktop()
        assert d.install_shortcut() is False

    def test_uninstall_shortcut_returns_false(self):
        d = _UnsupportedDesktop()
        assert d.uninstall_shortcut() is False


class TestLinuxDesktop:
    @pytest.fixture
    def linux(self, tmp_path):
        d = LinuxDesktop()
        d.SHORTCUT_DIR = tmp_path / "applications"
        d.AUTOSTART_DIR = tmp_path / "autostart"
        return d

    def test_shortcut_exists_false_when_missing(self, linux):
        assert linux.shortcut_exists() is False

    def test_install_shortcut_creates_file(self, linux):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                result = linux.install_shortcut()

        assert result is True
        assert linux.shortcut_path.exists()

    def test_shortcut_exists_true_after_install(self, linux):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                linux.install_shortcut()

        assert linux.shortcut_exists() is True

    def test_shortcut_content_has_required_fields(self, linux, tmp_path):
        icon = tmp_path / "icon.png"
        icon.write_text("fake")
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=icon
            ):
                linux.install_shortcut()

        content = linux.shortcut_path.read_text()
        assert "[Desktop Entry]" in content
        assert "Type=Application" in content
        assert "Name=AI Guardian Tray" in content
        assert "Exec=/usr/bin/ai-guardian tray start" in content
        assert "Terminal=false" in content
        assert f"Icon={icon}" in content

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Unix executable bit not applicable on Windows"
    )
    def test_shortcut_is_executable(self, linux):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                linux.install_shortcut()

        mode = linux.shortcut_path.stat().st_mode
        assert mode & stat.S_IXUSR

    def test_install_autostart_creates_file(self, linux):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                result = linux.install_autostart()

        assert result is True
        assert linux.autostart_path.exists()

    def test_autostart_content_has_gnome_flag(self, linux):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                linux.install_autostart()

        content = linux.autostart_path.read_text()
        assert "X-GNOME-Autostart-enabled=true" in content

    def test_uninstall_shortcut_removes_file(self, linux):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                linux.install_shortcut()

        result = linux.uninstall_shortcut()
        assert result is True
        assert not linux.shortcut_path.exists()

    def test_uninstall_shortcut_returns_false_when_not_installed(self, linux):
        assert linux.uninstall_shortcut() is False

    def test_uninstall_autostart_removes_file(self, linux):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                linux.install_autostart()

        result = linux.uninstall_autostart()
        assert result is True
        assert not linux.autostart_path.exists()

    def test_uninstall_autostart_returns_false_when_not_installed(self, linux):
        assert linux.uninstall_autostart() is False

    def test_shortcut_no_icon_line_when_icon_missing(self, linux):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                linux.install_shortcut()

        content = linux.shortcut_path.read_text()
        assert "Icon=" not in content


class TestMacOSDesktop:
    @pytest.fixture
    def macos(self, tmp_path):
        d = MacOSDesktop()
        d.APP_DIR = tmp_path / "Applications"
        d.LAUNCHD_DIR = tmp_path / "LaunchAgents"
        return d

    def test_shortcut_exists_false_when_missing(self, macos):
        assert macos.shortcut_exists() is False

    def test_install_shortcut_creates_app_bundle(self, macos):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                result = macos.install_shortcut()

        assert result is True
        assert macos.app_path.exists()
        assert (macos.app_path / "Contents" / "MacOS" / "ai-guardian-tray").exists()
        assert (macos.app_path / "Contents" / "Info.plist").exists()

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Unix executable bit not applicable on Windows"
    )
    def test_app_bundle_script_is_executable(self, macos):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                macos.install_shortcut()

        script = macos.app_path / "Contents" / "MacOS" / "ai-guardian-tray"
        mode = script.stat().st_mode
        assert mode & stat.S_IXUSR

    def test_app_bundle_script_content(self, macos):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                macos.install_shortcut()

        script = macos.app_path / "Contents" / "MacOS" / "ai-guardian-tray"
        content = script.read_text()
        assert content.startswith("#!/bin/sh\n")
        assert 'exec /usr/local/bin/ai-guardian tray start "$@"' in content

    def test_app_bundle_uses_current_python_for_launcher(self, macos, tmp_path):
        python = tmp_path / "venv with spaces" / "bin" / "python"
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=[str(python), "-m", "ai_guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                macos.install_shortcut()

        script = macos.app_path / "Contents" / "MacOS" / "ai-guardian-tray"
        content = script.read_text()
        assert f"exec '{python}' -m ai_guardian tray start \"$@\"" in content

    def test_app_bundle_script_augments_path(self, macos):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                macos.install_shortcut()

        script = macos.app_path / "Contents" / "MacOS" / "ai-guardian-tray"
        content = script.read_text()
        assert "/opt/homebrew/bin" in content
        assert "/usr/local/bin" in content
        assert "export PATH" in content
        assert "${PATH:-}" in content

    def test_info_plist_has_lsuielement(self, macos):
        import plistlib

        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                macos.install_shortcut()

        with open(macos.app_path / "Contents" / "Info.plist", "rb") as f:
            plist = plistlib.load(f)

        assert plist["LSUIElement"] is True
        assert plist["CFBundleExecutable"] == "ai-guardian-tray"

    def test_info_plist_has_ns_principal_class(self, macos):
        import plistlib

        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                macos.install_shortcut()

        with open(macos.app_path / "Contents" / "Info.plist", "rb") as f:
            plist = plistlib.load(f)

        assert plist["NSPrincipalClass"] == "NSApplication"

    def test_install_shortcut_copies_icon(self, macos, tmp_path):
        icon = tmp_path / "ai-guardian.icns"
        icon.write_bytes(b"ICNS_DATA")
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            with mock.patch.object(MacOSDesktop, "_find_icns", return_value=str(icon)):
                macos.install_shortcut()

        resources_icon = macos.app_path / "Contents" / "Resources" / "ai-guardian.icns"
        assert resources_icon.exists()

    def test_shortcut_exists_true_after_install(self, macos):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                macos.install_shortcut()

        assert macos.shortcut_exists() is True

    def test_install_autostart_creates_plist(self, macos):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            result = macos.install_autostart()

        assert result is True
        assert macos.plist_path.exists()

    def test_plist_has_run_at_load(self, macos):
        import plistlib

        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            macos.install_autostart()

        with open(macos.plist_path, "rb") as f:
            plist = plistlib.load(f)

        assert plist["RunAtLoad"] is True
        assert plist["Label"] == "com.itdove.ai-guardian.tray"

    def test_plist_has_correct_program_arguments(self, macos):
        import plistlib

        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            macos.install_autostart()

        with open(macos.plist_path, "rb") as f:
            plist = plistlib.load(f)

        assert plist["ProgramArguments"] == [
            "/usr/local/bin/ai-guardian",
            "tray",
            "start",
        ]

    def test_plist_has_environment_variables_with_path(self, macos):
        import plistlib

        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            macos.install_autostart()

        with open(macos.plist_path, "rb") as f:
            plist = plistlib.load(f)

        assert "EnvironmentVariables" in plist
        path_value = plist["EnvironmentVariables"]["PATH"]
        assert "/opt/homebrew/bin" in path_value
        assert "/usr/local/bin" in path_value

    def test_uninstall_shortcut_removes_app_bundle(self, macos):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_icon", return_value=None
            ):
                macos.install_shortcut()

        result = macos.uninstall_shortcut()
        assert result is True
        assert not macos.app_path.exists()

    def test_uninstall_shortcut_returns_false_when_not_installed(self, macos):
        assert macos.uninstall_shortcut() is False

    def test_uninstall_autostart_removes_plist(self, macos):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            macos.install_autostart()

        with mock.patch("ai_guardian.daemon.desktop.subprocess.run"):
            result = macos.uninstall_autostart()

        assert result is True
        assert not macos.plist_path.exists()

    def test_uninstall_autostart_calls_launchctl(self, macos):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["/usr/local/bin/ai-guardian"],
        ):
            macos.install_autostart()

        with mock.patch("ai_guardian.daemon.desktop.subprocess.run") as mock_run:
            macos.uninstall_autostart()

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "launchctl"
        assert args[1] == "unload"

    def test_uninstall_autostart_returns_false_when_not_installed(self, macos):
        assert macos.uninstall_autostart() is False


class TestWindowsDesktop:
    @pytest.fixture
    def win(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        return WindowsDesktop()

    def test_shortcut_path_in_start_menu(self, win, tmp_path):
        expected = (
            tmp_path
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "AI Guardian Tray.lnk"
        )
        assert win.shortcut_path == expected

    def test_autostart_path_in_startup(self, win, tmp_path):
        expected = (
            tmp_path
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
            / "AI Guardian Tray.lnk"
        )
        assert win.autostart_path == expected

    def test_shortcut_exists_false_when_missing(self, win):
        assert win.shortcut_exists() is False

    def test_install_shortcut_runs_powershell(self, win):
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=["C:\\Python\\python.exe", "-m", "ai_guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_ico", return_value=None
            ):
                with mock.patch(
                    "ai_guardian.daemon.desktop.shutil.which", return_value=None
                ):
                    with mock.patch(
                        "ai_guardian.daemon.desktop.subprocess.run"
                    ) as mock_run:
                        mock_run.return_value = mock.Mock()
                        win.shortcut_path.parent.mkdir(parents=True, exist_ok=True)
                        win.shortcut_path.write_text("fake lnk")
                        win.install_shortcut()

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "powershell"

    def test_shortcut_uses_pythonw_from_same_interpreter_directory(self, win, tmp_path):
        python_exe = tmp_path / "python.exe"
        pythonw_exe = tmp_path / "pythonw.exe"
        python_exe.touch()
        pythonw_exe.touch()
        with mock.patch(
            "ai_guardian.daemon.desktop._get_executable_command",
            return_value=[str(python_exe), "-m", "ai_guardian"],
        ):
            with mock.patch(
                "ai_guardian.daemon.desktop._prepare_ico", return_value=None
            ):
                with mock.patch(
                    "ai_guardian.daemon.desktop.subprocess.run"
                ) as mock_run:
                    win.shortcut_path.parent.mkdir(parents=True, exist_ok=True)
                    win.shortcut_path.write_text("fake lnk")
                    win.install_shortcut()

        ps_script = mock_run.call_args[0][0][3]
        assert f"$Shortcut.TargetPath = '{pythonw_exe}'" in ps_script
        assert "$Shortcut.Arguments = '-m ai_guardian tray start'" in ps_script

    def test_uninstall_shortcut_removes_file(self, win):
        win.shortcut_path.parent.mkdir(parents=True, exist_ok=True)
        win.shortcut_path.write_text("fake")
        result = win.uninstall_shortcut()
        assert result is True
        assert not win.shortcut_path.exists()

    def test_uninstall_shortcut_returns_false_when_not_installed(self, win):
        assert win.uninstall_shortcut() is False

    def test_uninstall_autostart_removes_file(self, win):
        win.autostart_path.parent.mkdir(parents=True, exist_ok=True)
        win.autostart_path.write_text("fake")
        result = win.uninstall_autostart()
        assert result is True
        assert not win.autostart_path.exists()


class TestCLIInstallUninstall:
    def test_install_flag_calls_handler(self):
        from ai_guardian.cli_handlers import _handle_tray_install

        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration"
        ) as mock_get:
            desktop = mock.Mock()
            desktop.shortcut_exists.return_value = False
            desktop.install_shortcut.return_value = True
            mock_get.return_value = desktop

            result = _handle_tray_install(autostart=False)

        assert result == 0
        desktop.install_shortcut.assert_called_once()

    def test_install_with_autostart(self):
        from ai_guardian.cli_handlers import _handle_tray_install

        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration"
        ) as mock_get:
            desktop = mock.Mock()
            desktop.shortcut_exists.return_value = False
            desktop.install_shortcut.return_value = True
            desktop.autostart_exists.return_value = False
            desktop.install_autostart.return_value = True
            mock_get.return_value = desktop

            result = _handle_tray_install(autostart=True)

        assert result == 0
        desktop.install_shortcut.assert_called_once()
        desktop.install_autostart.assert_called_once()

    def test_install_already_exists(self, capsys):
        from ai_guardian.cli_handlers import _handle_tray_install

        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration"
        ) as mock_get:
            desktop = mock.Mock()
            desktop.shortcut_exists.return_value = True
            mock_get.return_value = desktop

            result = _handle_tray_install(autostart=False)

        assert result == 0
        assert "already exists" in capsys.readouterr().out

    def test_install_failure_returns_1(self):
        from ai_guardian.cli_handlers import _handle_tray_install

        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration"
        ) as mock_get:
            desktop = mock.Mock()
            desktop.shortcut_exists.return_value = False
            desktop.install_shortcut.return_value = False
            mock_get.return_value = desktop

            result = _handle_tray_install(autostart=False)

        assert result == 1

    def test_uninstall_removes_both(self, capsys):
        from ai_guardian.cli_handlers import _handle_tray_uninstall

        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration"
        ) as mock_get:
            desktop = mock.Mock()
            desktop.uninstall_shortcut.return_value = True
            desktop.uninstall_autostart.return_value = True
            mock_get.return_value = desktop

            result = _handle_tray_uninstall()

        assert result == 0
        out = capsys.readouterr().out
        assert "Removed desktop shortcut" in out
        assert "Removed autostart" in out

    def test_uninstall_nothing_found(self, capsys):
        from ai_guardian.cli_handlers import _handle_tray_uninstall

        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration"
        ) as mock_get:
            desktop = mock.Mock()
            desktop.uninstall_shortcut.return_value = False
            desktop.uninstall_autostart.return_value = False
            mock_get.return_value = desktop

            result = _handle_tray_uninstall()

        assert result == 0
        assert "No desktop shortcut or autostart found" in capsys.readouterr().out


class TestFirstRunDetection:
    def test_creates_shortcut_on_yes(self):
        desktop = mock.Mock()
        desktop.shortcut_exists.return_value = False
        desktop.install_shortcut.return_value = True

        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration", return_value=desktop
        ):
            with mock.patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                with mock.patch("builtins.input", side_effect=["y", "n"]):
                    from ai_guardian.cli_handlers import _handle_tray_install

                    result = _handle_tray_install(autostart=False)

        assert result == 0
        desktop.install_shortcut.assert_called_once()

    def test_skips_when_shortcut_exists(self):
        desktop = mock.Mock()
        desktop.shortcut_exists.return_value = True

        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration", return_value=desktop
        ):
            from ai_guardian.cli_handlers import _handle_tray_install

            result = _handle_tray_install(autostart=False)

        assert result == 0
        desktop.install_shortcut.assert_not_called()

    def test_desktop_error_does_not_block_install(self):
        desktop = mock.Mock()
        desktop.shortcut_exists.return_value = False
        desktop.install_shortcut.return_value = False

        with mock.patch(
            "ai_guardian.daemon.desktop.get_desktop_integration", return_value=desktop
        ):
            from ai_guardian.cli_handlers import _handle_tray_install

            result = _handle_tray_install(autostart=False)

        assert result == 1
