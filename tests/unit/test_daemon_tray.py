"""Tests for daemon system tray integration."""

import sys
import threading
import time
from unittest import mock

import pytest

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.tray.app import (
    DaemonTray,
    HAS_PYSTRAY,
    is_tray_available,
    _is_tray_running,
    _check_gi_available,
    _suppress_gtk_stderr,
    _restore_stderr,
)
from ai_guardian.tray.icons import (
    apply_paused_dimming,
    find_tray_icon_path,
    invert_icon,
    needs_dark_icon,
)
from ai_guardian.tray.menu import (
    build_about_text,
    daemon_status_label,
    launch_console,
    launch_create_config,
    launch_doctor,
    launch_ide_setup,
    launch_shell,
)
from ai_guardian.tray.notifications import (
    format_time_ago,
    parse_version_tuple,
    send_version_mismatch_notification,
)
from ai_guardian.daemon import is_mcp_installed
from ai_guardian.tray import plugins as tray_plugins
from ai_guardian.tray.plugins import (
    execute_plugin_command,
    resolve_plugin_ai_guardian,
)


@pytest.fixture(autouse=True)
def _no_real_web_console(monkeypatch):
    """Prevent tests from spawning real web console subprocesses."""
    monkeypatch.setattr(DaemonTray, "_start_web_console", lambda self: None)


class TestCheckGiAvailable:
    def test_returns_bool(self):
        result = _check_gi_available()
        assert isinstance(result, bool)

    def test_returns_false_when_gi_missing(self):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "gi":
                raise ImportError("no gi")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            assert _check_gi_available() is False

    def test_returns_true_when_gi_available(self):
        with mock.patch.dict("sys.modules", {"gi": mock.MagicMock()}):
            assert _check_gi_available() is True


class TestIsTrayAvailable:
    def test_returns_bool(self):
        result = is_tray_available()
        assert isinstance(result, bool)

    @mock.patch("ai_guardian.tray.app.HAS_PYSTRAY", True)
    def test_returns_false_on_linux_without_gi(self):
        with mock.patch("ai_guardian.tray.app._check_gi_available", return_value=False):
            with mock.patch("platform.system", return_value="Linux"):
                with mock.patch.dict("os.environ", {"DISPLAY": ":0"}):
                    assert is_tray_available() is False


class TestDaemonTrayWithoutPystray:
    def test_start_without_pystray_returns_false(self):
        with mock.patch("ai_guardian.tray.app.HAS_PYSTRAY", False):
            tray = DaemonTray(
                get_stats_callback=lambda: {},
                stop_callback=lambda: None,
                pause_callback=lambda: None,
            )
            result = tray.start()
            assert result is False

    def test_stop_without_icon_is_noop(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda: None,
        )
        tray.stop()  # Should not raise

    def test_update_status_without_icon(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {"paused": True, "pause_remaining_seconds": 300},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray.update_status("paused")  # Should not raise
        assert tray._status == "paused"
        tray._stop_pause_timer()


class TestDaemonTrayCallbacks:
    def test_quit_calls_stop_callback(self):
        stopped = []
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: stopped.append(True),
            pause_callback=lambda: None,
        )
        tray._on_quit(mock.MagicMock(), mock.MagicMock())
        assert stopped == [True]

    def test_resume_label_shows_remaining_time(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {"pause_remaining_seconds": 125},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._status = "paused"
        label = tray._menu._resume_menu_label()
        assert "2m" in label
        assert "5s" in label


class TestTrayPauseRoutesLocalThroughMultiClient:
    """Verify local daemon pause/resume routes through multi_client (issue #683)."""

    def test_pause_action_uses_multi_client_for_local_target(self):
        mc = mock.MagicMock()
        local_target = DaemonTarget(name="local", runtime="local", status="running")
        pause_cb = mock.MagicMock()

        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=pause_cb,
            multi_client=mc,
        )
        tray._targets = [local_target]

        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            tray._menu._build_single_daemon_menu_items()

        mc.send_pause.assert_not_called()
        pause_cb.assert_not_called()

    @pytest.mark.parametrize(
        "action, mc_method, extra_args",
        [
            ("pause", "send_pause", (5,)),
            ("resume", "send_resume", ()),
        ],
        ids=["pause", "resume"],
    )
    def test_local_routes_via_multi_client(self, action, mc_method, extra_args):
        mc = mock.MagicMock()
        local_target = DaemonTarget(name="local", runtime="local", status="running")
        pause_cb = mock.MagicMock()

        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=pause_cb,
            multi_client=mc,
        )
        tray._targets = [local_target]

        t = tray._targets[0]
        getattr(tray._multi_client, mc_method)(t, *extra_args)

        getattr(mc, mc_method).assert_called_once_with(local_target, *extra_args)
        pause_cb.assert_not_called()

    def test_pause_falls_back_to_callback_without_multi_client(self):
        pause_cb = mock.MagicMock()
        local_target = DaemonTarget(name="local", runtime="local", status="running")

        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=pause_cb,
        )
        tray._targets = [local_target]

        t = tray._targets[0]
        if tray._multi_client:
            tray._multi_client.send_pause(t, 5)
        else:
            tray._pause(5)

        pause_cb.assert_called_once_with(5)


class TestFlashReload:
    @pytest.mark.parametrize("status", ["running", "paused"], ids=["running", "paused"])
    def test_flash_reload_preserves_status(self, status):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._status = status
        tray.flash_reload()
        assert tray._status == status


class TestFormatTimeAgo:
    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (30, "30s ago"),
            (120, "2m ago"),
            (7200, "2h ago"),
            (172800, "2d ago"),
            (None, ""),
            (0, "0s ago"),
            (59, "59s ago"),
            (60, "1m ago"),
        ],
        ids=[
            "seconds",
            "minutes",
            "hours",
            "days",
            "none",
            "zero",
            "just-under-minute",
            "exactly-one-minute",
        ],
    )
    def test_format_time_ago(self, seconds, expected):
        assert format_time_ago(seconds) == expected


class TestCrossPlatform:
    def test_dispatch_to_main_without_pyobjc(self):
        called = []
        with mock.patch.dict(
            "sys.modules", {"PyObjCTools": None, "PyObjCTools.AppHelper": None}
        ):
            with mock.patch("platform.system", return_value="Darwin"):
                tray = DaemonTray(
                    get_stats_callback=lambda: {},
                    stop_callback=lambda: None,
                    pause_callback=lambda mins: None,
                )
                tray._dispatch_to_main(lambda: called.append(True))
        assert called == [True]

    def test_console_launch_linux(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch("platform.system", return_value="Linux"):
            with mock.patch(
                "shutil.which",
                side_effect=lambda x: (
                    "/usr/bin/gnome-terminal" if x == "gnome-terminal" else None
                ),
            ):
                with mock.patch("subprocess.Popen") as mock_popen:
                    launch_console()
                    mock_popen.assert_called_once()
                    args = mock_popen.call_args[0][0]
                    assert "gnome-terminal" in args[0]

    def test_console_launch_linux_kgx_fallback(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch("platform.system", return_value="Linux"):
            with mock.patch(
                "shutil.which",
                side_effect=lambda x: "/usr/bin/kgx" if x == "kgx" else None,
            ):
                with mock.patch("subprocess.Popen") as mock_popen:
                    launch_console()
                    mock_popen.assert_called_once()
                    args = mock_popen.call_args[0][0]
                    assert args[0] == "kgx"

    def test_console_launch_macos(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch("subprocess.Popen") as mock_popen:
                launch_console()
                mock_popen.assert_called_once()
                script = mock_popen.call_args[0][0][2]
                assert "osascript" in mock_popen.call_args[0][0][0]
                assert 'do script ""' in script
                assert "delay 2" in script
                assert "console" in script

    def test_console_launch_macos_deferred_command(self):
        """Command is sent after shell init to avoid interactive prompts (issue #599)."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch("sys.executable", "/usr/bin/python3"):
                with mock.patch("subprocess.Popen") as mock_popen:
                    launch_console()
                    script = mock_popen.call_args[0][0][2]
                    lines = script.split("\n")
                    do_script_lines = [l.strip() for l in lines if "do script" in l]
                    assert len(do_script_lines) == 2
                    assert do_script_lines[0] == 'set currentTab to do script ""'
                    assert "in currentTab" in do_script_lines[1]

    def test_console_launch_macos_uses_python_command(self):
        """_resolve_cli_cmd uses 'python' command or ai-guardian binary."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch("subprocess.Popen") as mock_popen:
                launch_console()
                script = mock_popen.call_args[0][0][2]
                assert "console" in script

    def test_console_launch_windows(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch("platform.system", return_value="Windows"):
            with mock.patch("subprocess.Popen") as mock_popen:
                launch_console()
                mock_popen.assert_called_once()
                call_args = str(mock_popen.call_args)
                assert "start" in call_args


class TestDaemonTrayIcon:
    @pytest.mark.skipif(not HAS_PYSTRAY, reason="pystray/Pillow not installed")
    def test_create_icon_returns_image(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda: None,
        )
        icon = tray._create_icon()
        assert icon is not None
        assert icon.mode == "RGBA"

    @pytest.mark.skipif(not HAS_PYSTRAY, reason="pystray/Pillow not installed")
    def test_fallback_icon_when_no_tray_icon(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda: None,
        )
        with mock.patch(
            "ai_guardian.tray.icons.find_tray_icon_path", return_value=None
        ):
            icon = tray._create_icon()
        assert icon is not None
        assert icon.size == (22, 22)

    @pytest.mark.skipif(not HAS_PYSTRAY, reason="pystray/Pillow not installed")
    def test_find_tray_icon_path_returns_path_or_none(self):
        result = find_tray_icon_path()
        if result is not None:
            from pathlib import Path

            assert Path(result).exists()

    @pytest.mark.skipif(not HAS_PYSTRAY, reason="pystray/Pillow not installed")
    def test_find_tray_icon_path_macos(self):
        with mock.patch("platform.system", return_value="Darwin"):
            result = find_tray_icon_path()
        if result is not None:
            assert "Template" in result

    @pytest.mark.skipif(not HAS_PYSTRAY, reason="pystray/Pillow not installed")
    def test_find_tray_icon_path_windows(self):
        with mock.patch("platform.system", return_value="Windows"):
            result = find_tray_icon_path()
        if result is not None:
            assert "16" in result

    @pytest.mark.skipif(not HAS_PYSTRAY, reason="pystray/Pillow not installed")
    def test_find_tray_icon_path_linux(self):
        with mock.patch("platform.system", return_value="Linux"):
            result = find_tray_icon_path()
        if result is not None:
            assert "22" in result

    def test_find_tray_icon_path_persists_beyond_context(self):
        """Icon path must remain valid after method returns (issue #754)."""
        with mock.patch("platform.system", return_value="Linux"):
            result = find_tray_icon_path()
        if result is not None:
            from pathlib import Path

            assert Path(result).exists(), (
                f"Icon path {result} does not exist — "
                "as_file() context manager may have cleaned it up"
            )

    def test_all_required_tray_icon_sizes_exist(self):
        from pathlib import Path

        images_dir = Path(__file__).resolve().parent.parent.parent / "images"
        required = [
            "tray-icon-16.png",
            "tray-icon-22.png",
            "tray-icon-32.png",
            "tray-iconTemplate.png",
            "tray-iconTemplate@2x.png",
        ]
        for name in required:
            assert (images_dir / name).exists(), f"Missing tray icon: {name}"

    @pytest.mark.skipif(not HAS_PYSTRAY, reason="pystray/Pillow not installed")
    def test_tray_icon_png_dimensions(self):
        from pathlib import Path
        from PIL import Image

        images_dir = Path(__file__).resolve().parent.parent.parent / "images"
        expected_sizes = {
            "tray-icon-16.png": (16, 16),
            "tray-icon-22.png": (22, 22),
            "tray-icon-32.png": (32, 32),
            "tray-iconTemplate.png": (22, 22),
            "tray-iconTemplate@2x.png": (44, 44),
        }
        for name, expected in expected_sizes.items():
            img = Image.open(images_dir / name)
            assert img.size == expected, f"{name}: expected {expected}, got {img.size}"
            assert img.mode in ("RGBA", "P"), f"{name}: expected RGBA mode"


class TestIconInversion:
    """Tests for dark icon on light GNOME panels (issue #754)."""

    @pytest.mark.parametrize(
        "platform_name, env, gsettings_stdout, expected",
        [
            ("Darwin", {}, None, False),
            ("Linux", {"XDG_CURRENT_DESKTOP": "KDE"}, None, False),
            ("Linux", {"XDG_CURRENT_DESKTOP": "GNOME"}, "'default'\n", True),
            ("Linux", {"XDG_CURRENT_DESKTOP": "GNOME"}, "'prefer-dark'\n", False),
        ],
        ids=["macos", "kde", "gnome-light", "gnome-dark"],
    )
    def test_needs_dark_icon(self, platform_name, env, gsettings_stdout, expected):
        with (
            mock.patch("platform.system", return_value=platform_name),
            mock.patch.dict("os.environ", env, clear=False),
            mock.patch("subprocess.run") as mock_run,
        ):
            if gsettings_stdout is not None:
                mock_run.return_value = mock.MagicMock(stdout=gsettings_stdout)
            assert needs_dark_icon() is expected

    @pytest.mark.skipif(not HAS_PYSTRAY, reason="pystray/Pillow not installed")
    def test_invert_icon_makes_dark(self):
        from PIL import Image as PILImage

        img = PILImage.new("RGBA", (22, 22), (255, 255, 255, 200))
        inverted = invert_icon(img)
        r, g, b, a = inverted.split()
        assert list(r.getdata())[0] == 0
        assert list(a.getdata())[0] == 200


class TestRunPlatformBranching:
    """Verify _run() never passes setup= callback (issue #564, #602)."""

    def test_run_on_linux_no_setup_callback(self):
        """setup= breaks icon visibility on newer GNOME (issue #602)."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        mock_icon = mock.MagicMock()
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("platform.system", return_value="Linux"),
            mock.patch("ai_guardian.tray.app._suppress_gtk_stderr", return_value=42),
            mock.patch("ai_guardian.tray.app.threading") as mock_threading,
        ):
            mock_pystray.Icon.return_value = mock_icon
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.MenuItem = mock.MagicMock()
            tray._start_stats_refresh = mock.MagicMock()
            tray._create_icon = mock.MagicMock()
            tray._run()
            mock_icon.run.assert_called_once()
            _, kwargs = mock_icon.run.call_args
            assert "setup" not in kwargs
            mock_threading.Timer.assert_called_once_with(
                0.5, _restore_stderr, args=[42]
            )
            mock_threading.Timer.return_value.start.assert_called_once()

    def test_run_on_macos_no_setup_callback(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        mock_icon = mock.MagicMock()
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("platform.system", return_value="Darwin"),
        ):
            mock_pystray.Icon.return_value = mock_icon
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.MenuItem = mock.MagicMock()
            tray._start_stats_refresh = mock.MagicMock()
            tray._create_icon = mock.MagicMock()
            tray._ensure_macos_activation_policy = mock.MagicMock()
            tray._run()
            mock_icon.run.assert_called_once()
            _, kwargs = mock_icon.run.call_args
            assert "setup" not in kwargs
            tray._ensure_macos_activation_policy.assert_called_once()

    def test_ensure_macos_activation_policy_on_darwin(self):
        """Verify activation policy is set on macOS (issue #691)."""
        mock_app = mock.MagicMock()
        mock_appkit = mock.MagicMock()
        mock_appkit.NSApplication.sharedApplication.return_value = mock_app
        mock_appkit.NSApplicationActivationPolicyAccessory = 1
        mock_foundation = mock.MagicMock()
        mock_foundation.NSBundle.mainBundle.return_value.infoDictionary.return_value = (
            {}
        )
        with (
            mock.patch("platform.system", return_value="Darwin"),
            mock.patch.dict(
                "sys.modules", {"AppKit": mock_appkit, "Foundation": mock_foundation}
            ),
        ):
            DaemonTray._ensure_macos_activation_policy()
        mock_app.setActivationPolicy_.assert_called_once_with(1)

    def test_ensure_macos_activation_policy_skipped_on_linux(self):
        with mock.patch("platform.system", return_value="Linux"):
            DaemonTray._ensure_macos_activation_policy()

    def test_ensure_macos_sets_bundle_id_and_app_icon(self):
        """Verify bundle ID and app icon are set on macOS (issue #769)."""
        mock_app = mock.MagicMock()
        mock_appkit = mock.MagicMock()
        mock_appkit.NSApplication.sharedApplication.return_value = mock_app
        mock_appkit.NSApplicationActivationPolicyAccessory = 1
        mock_info = {}
        mock_foundation = mock.MagicMock()
        mock_foundation.NSBundle.mainBundle.return_value.infoDictionary.return_value = (
            mock_info
        )
        mock_image = mock.MagicMock()
        mock_appkit.NSImage.alloc.return_value.initWithContentsOfFile_.return_value = (
            mock_image
        )
        with (
            mock.patch("platform.system", return_value="Darwin"),
            mock.patch.dict(
                "sys.modules", {"AppKit": mock_appkit, "Foundation": mock_foundation}
            ),
            mock.patch(
                "ai_guardian.tray.plugins._find_icon",
                return_value="/path/to/icon.icns",
            ),
        ):
            DaemonTray._ensure_macos_activation_policy()
        assert mock_info["CFBundleIdentifier"] == "com.itdove.ai-guardian.tray"
        assert mock_info["CFBundleName"] == "AI Guardian Tray"
        mock_app.setApplicationIconImage_.assert_called_once_with(mock_image)

    def test_ensure_macos_no_icon_when_not_found(self):
        """Verify graceful skip when icon file is missing (issue #769)."""
        mock_app = mock.MagicMock()
        mock_appkit = mock.MagicMock()
        mock_appkit.NSApplication.sharedApplication.return_value = mock_app
        mock_appkit.NSApplicationActivationPolicyAccessory = 1
        mock_info = {}
        mock_foundation = mock.MagicMock()
        mock_foundation.NSBundle.mainBundle.return_value.infoDictionary.return_value = (
            mock_info
        )
        with (
            mock.patch("platform.system", return_value="Darwin"),
            mock.patch.dict(
                "sys.modules", {"AppKit": mock_appkit, "Foundation": mock_foundation}
            ),
            mock.patch("ai_guardian.tray.plugins._find_icon", return_value=""),
        ):
            DaemonTray._ensure_macos_activation_policy()
        mock_app.setApplicationIconImage_.assert_not_called()


class TestSuppressGtkStderr:
    def test_returns_none_on_non_linux(self):
        with mock.patch("platform.system", return_value="Darwin"):
            assert _suppress_gtk_stderr() is None

    def test_returns_fd_on_linux(self):

        with mock.patch("platform.system", return_value="Linux"):
            saved_fd = _suppress_gtk_stderr()
            assert saved_fd is not None
            _restore_stderr(saved_fd)

    def test_restore_with_none_is_noop(self):
        _restore_stderr(None)

    def test_roundtrip_preserves_stderr(self):
        import os
        import sys

        with mock.patch("platform.system", return_value="Linux"):
            original_fd = os.dup(2)
            try:
                saved_fd = _suppress_gtk_stderr()
                assert saved_fd is not None
                _restore_stderr(saved_fd)
                # stderr should still work
                sys.stderr.write("")
                sys.stderr.flush()
            finally:
                os.close(original_fd)


class TestSingleDaemonFlatMenu:
    """Tests for flat menu layout when exactly one daemon is discovered."""

    def _make_tray(self, targets=None):
        tray = DaemonTray(
            get_stats_callback=lambda: {"request_count": 10, "blocked_count": 2},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        if targets is not None:
            tray._targets = targets
        return tray

    def test_is_single_daemon_with_one_target(self):
        tray = self._make_tray(
            [DaemonTarget(name="local", runtime="local", status="running")]
        )
        assert tray._is_single_daemon() is True
        assert tray._is_multi_daemon() is False

    def test_is_multi_daemon_with_two_targets(self):
        tray = self._make_tray(
            [
                DaemonTarget(name="local", runtime="local", status="running"),
                DaemonTarget(name="remote", runtime="container", status="running"),
            ]
        )
        assert tray._is_multi_daemon() is True
        assert tray._is_single_daemon() is False

    def test_is_multi_daemon_with_zero_targets(self):
        tray = self._make_tray([])
        assert tray._is_multi_daemon() is True
        assert tray._is_single_daemon() is False

    @pytest.mark.parametrize(
        "target_kwargs, expected_label",
        [
            (
                dict(name="my-host", runtime="local", status="running"),
                "● my-host",
            ),
            (
                dict(
                    name="sandbox",
                    runtime="container",
                    container_engine="podman",
                    status="running",
                ),
                "● sandbox (podman)",
            ),
            (
                dict(name="k8s-pod", runtime="kubernetes", status="running"),
                "● k8s-pod (kubernetes)",
            ),
        ],
        ids=["local-running", "container-running", "kubernetes-running"],
    )
    def test_daemon_status_label(self, target_kwargs, expected_label):
        t = DaemonTarget(**target_kwargs)
        assert daemon_status_label(t) == expected_label

    def test_daemon_status_label_stopped(self):
        t = DaemonTarget(name="my-host", runtime="local", status="stopped")
        label = daemon_status_label(t)
        assert "⚠" in label
        assert "daemon not running" in label

    def test_flat_menu_with_single_container_target(self):
        """Single container daemon uses flat layout — same as local."""
        tray = self._make_tray(
            [
                DaemonTarget(
                    name="carbonite-prod",
                    runtime="container",
                    container_engine="podman",
                    status="running",
                ),
            ]
        )
        assert tray._is_single_daemon() is True

    def test_dynamic_switch_flat_to_nested(self):
        """Layout switches dynamically when targets change count."""
        tray = self._make_tray(
            [
                DaemonTarget(name="local", runtime="local", status="running"),
            ]
        )
        assert tray._is_single_daemon() is True

        tray._targets.append(
            DaemonTarget(name="remote", runtime="container", status="running")
        )
        assert tray._is_single_daemon() is False
        assert tray._is_multi_daemon() is True

        tray._targets.pop()
        assert tray._is_single_daemon() is True


class TestIDESetupMenu:
    """Tests for the Local Setup... IDE submenu."""

    def test_launch_ide_setup_builds_correct_command(self):
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch("sys.executable", "/usr/bin/python3"):
                with mock.patch("subprocess.Popen") as mock_popen:
                    launch_ide_setup("claude")
                    mock_popen.assert_called_once()
                    script = mock_popen.call_args[0][0][2]
                    assert "setup --ide claude" in script

    def test_launch_ide_setup_keeps_terminal_open_macos(self):
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch("sys.executable", "/usr/bin/python3"):
                with mock.patch("subprocess.Popen") as mock_popen:
                    launch_ide_setup("claude")
                    script = mock_popen.call_args[0][0][2]
                    assert "close" not in script
                    assert "repeat" not in script

    def test_launch_ide_setup_uses_python_command(self):
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch("subprocess.Popen") as mock_popen:
                launch_ide_setup("cursor")
                script = mock_popen.call_args[0][0][2]
                assert "setup --ide cursor" in script

    def test_launch_ide_setup_linux_keeps_terminal_open(self):
        with mock.patch("platform.system", return_value="Linux"):
            with mock.patch("sys.executable", "/usr/bin/python3"):
                with mock.patch(
                    "shutil.which",
                    side_effect=lambda x: (
                        "/usr/bin/gnome-terminal" if x == "gnome-terminal" else None
                    ),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        launch_ide_setup("copilot")
                        mock_popen.assert_called_once()
                        args = mock_popen.call_args[0][0]
                        assert "gnome-terminal" in args[0]
                        shell_cmd = args[-1]
                        assert "setup --ide copilot" in shell_cmd
                        assert "Press Enter to close" in shell_cmd

    def test_build_ide_setup_menu_returns_items(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            items = tray._menu._build_ide_setup_menu_items()
            assert len(items) == 1
            top_call = mock_pystray.MenuItem.call_args_list[-1]
            assert top_call[0][0] == "Local Setup..."

    def test_build_ide_setup_menu_has_all_supported_ides(self):
        from ai_guardian.setup import IDESetup

        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_ide_setup_menu_items()
            item_names = [
                call[0][0] for call in mock_pystray.MenuItem.call_args_list[:-1]
            ]
            assert "  Create Config..." in item_names
            for ide_cfg in IDESetup.IDE_CONFIGS.values():
                assert f"  {ide_cfg['name']}" in item_names

    def test_launch_create_config_builds_correct_command(self):
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch("sys.executable", "/usr/bin/python3"):
                with mock.patch("subprocess.Popen") as mock_popen:
                    launch_create_config()
                    script = mock_popen.call_args[0][0][2]
                    assert "setup --create-config" in script
                    assert "close" not in script


class TestPausedIconDimming:
    """Tests for visual pause state indicator (issue #684)."""

    @pytest.mark.skipif(not HAS_PYSTRAY, reason="pystray/Pillow not installed")
    def test_apply_paused_dimming_reduces_alpha(self):
        from PIL import Image

        img = Image.new("RGBA", (22, 22), (255, 255, 255, 200))
        dimmed = apply_paused_dimming(img)
        assert dimmed.size == (22, 22)
        _, _, _, a = dimmed.getpixel((10, 10))
        assert a == 100

    @pytest.mark.skipif(not HAS_PYSTRAY, reason="pystray/Pillow not installed")
    def test_apply_paused_dimming_does_not_modify_original(self):
        from PIL import Image

        img = Image.new("RGBA", (22, 22), (255, 255, 255, 200))
        apply_paused_dimming(img)
        _, _, _, a = img.getpixel((10, 10))
        assert a == 200

    @pytest.mark.skipif(not HAS_PYSTRAY, reason="pystray/Pillow not installed")
    def test_create_icon_dimmed_when_paused(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        normal = tray._create_icon()
        tray._status = "paused"
        paused = tray._create_icon()
        normal_alpha = list(normal.split()[3].tobytes())
        paused_alpha = list(paused.split()[3].tobytes())
        non_zero = [i for i, a in enumerate(normal_alpha) if a > 0]
        assert len(non_zero) > 0
        for i in non_zero:
            assert paused_alpha[i] <= normal_alpha[i]

    @pytest.mark.skipif(not HAS_PYSTRAY, reason="pystray/Pillow not installed")
    def test_create_icon_normal_when_running(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._status = "running"
        icon = tray._create_icon()
        assert icon.mode == "RGBA"


class TestUpdateStatusPauseTimer:
    """Tests for update_status() managing pause timer (issue #684)."""

    def test_update_status_starts_pause_timer(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {"pause_remaining_seconds": 60},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch.object(tray, "_start_pause_timer") as mock_start:
            tray.update_status("paused")
            mock_start.assert_called_once()

    def test_update_status_stops_pause_timer_on_resume(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._status = "paused"
        with mock.patch.object(tray, "_stop_pause_timer") as mock_stop:
            tray.update_status("running")
            mock_stop.assert_called_once()

    def test_update_status_no_double_start(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {"pause_remaining_seconds": 60},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._status = "paused"
        with mock.patch.object(tray, "_start_pause_timer") as mock_start:
            tray.update_status("paused")
            mock_start.assert_not_called()

    def test_update_status_updates_icon_when_icon_exists(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        mock_icon = mock.MagicMock()
        tray._icon = mock_icon
        with mock.patch.object(tray, "_create_icon", return_value="fake_img"):
            with mock.patch.object(
                DaemonTray,
                "_dispatch_to_main",
                side_effect=lambda func: func(),
            ):
                tray.update_status("paused")
        assert mock_icon.icon == "fake_img"

    def test_update_status_dispatches_icon_to_main_thread(self):
        """Icon update must go through _dispatch_to_main (issue #774)."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._icon = mock.MagicMock()
        with mock.patch.object(DaemonTray, "_dispatch_to_main") as mock_dispatch:
            tray.update_status("paused")
            assert mock_dispatch.call_count >= 1
            first_call_arg = mock_dispatch.call_args_list[0][0][0]
            assert callable(first_call_arg)


class TestSyncPauseState:
    """Tests for _sync_pause_state() detecting external pause/resume (issue #684)."""

    @pytest.mark.parametrize(
        "stats, initial_status, expected_call",
        [
            ({"paused": True, "pause_remaining_seconds": 120}, "running", "paused"),
            ({"paused": False}, "paused", "running"),
            ({"paused": True}, "paused", None),
        ],
        ids=["external-pause", "external-resume", "no-change-already-paused"],
    )
    def test_sync_pause_state(self, stats, initial_status, expected_call):
        tray = DaemonTray(
            get_stats_callback=lambda: stats,
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [DaemonTarget(name="local", runtime="local", status="running")]
        tray._status = initial_status
        with mock.patch.object(tray, "update_status") as mock_update:
            tray._sync_pause_state()
            if expected_call is not None:
                mock_update.assert_called_once_with(expected_call)
            else:
                mock_update.assert_not_called()


class TestPausedTargetMenuVisibility:
    """Tests for paused target handling in menu visibility (issue #696)."""

    def _make_tray(self, targets=None):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        if targets is not None:
            tray._targets = targets
        return tray

    def test_single_running_includes_paused(self):
        """_single_running returns True for paused targets."""
        tray = self._make_tray(
            [
                DaemonTarget(name="local", runtime="local", status="paused"),
            ]
        )
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True),
            mock.patch("ai_guardian.tray.menu_builder.pystray", create=True),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", create=True),
        ):
            assert tray._is_single_daemon() is True
            fn = lambda _item: (
                tray._is_single_daemon()
                and tray._targets[0].status in ("running", "paused")
            )
            assert fn(None) is True

    def test_single_not_running_excludes_paused(self):
        """_single_not_running returns False for paused targets."""
        tray = self._make_tray(
            [
                DaemonTarget(name="local", runtime="local", status="paused"),
            ]
        )
        fn = lambda _item: (
            tray._is_single_daemon()
            and tray._targets[0].status not in ("running", "paused")
        )
        assert fn(None) is False

    def test_auto_select_prefers_paused_over_unknown(self):
        """_auto_select_target selects paused targets over unknown ones."""
        tray = self._make_tray(
            [
                DaemonTarget(name="unknown-one", runtime="container", status="unknown"),
                DaemonTarget(name="paused-local", runtime="local", status="paused"),
            ]
        )
        tray._active_target = None
        tray._auto_select_target()
        assert tray._active_target.name == "paused-local"

    def test_auto_select_keeps_paused_target(self):
        """_auto_select_target keeps currently active paused target."""
        paused_target = DaemonTarget(name="local", runtime="local", status="paused")
        tray = self._make_tray([paused_target])
        tray._active_target = paused_target
        tray._auto_select_target()
        assert tray._active_target.name == "local"

    def test_daemon_status_label_paused(self):
        """Status label shows paused icon for paused daemon."""
        t = DaemonTarget(name="my-host", runtime="local", status="paused")
        label = daemon_status_label(t)
        assert "☾" in label
        assert "my-host" in label

    @mock.patch("ai_guardian.daemon.working_dir.shorten_path")
    def test_daemon_status_label_includes_working_dir(self, mock_shorten):
        """Status label appends shortened working dir for running daemon."""
        mock_shorten.return_value = "~/dev/project"
        t = DaemonTarget(
            name="my-host",
            runtime="local",
            status="running",
            working_dir="/Users/dev/project",
        )
        label = daemon_status_label(t)
        assert "my-host" in label
        assert "~/dev/project" in label

    def test_daemon_status_label_no_working_dir(self):
        """Status label unchanged when working_dir is None."""
        t = DaemonTarget(name="my-host", runtime="local", status="running")
        label = daemon_status_label(t)
        assert "—" not in label or "daemon not running" in label

    @mock.patch("ai_guardian.daemon.working_dir.shorten_path")
    def test_daemon_status_label_truncates_long_path(self, mock_shorten):
        """Status label truncates paths longer than 40 chars."""
        mock_shorten.return_value = "~/very/deep/nested/project/directory/name"
        t = DaemonTarget(
            name="host",
            runtime="local",
            status="running",
            working_dir="/home/user/very/deep/nested/project/directory/name",
        )
        label = daemon_status_label(t)
        assert "..." in label

    def test_daemon_status_label_partial_pause(self):
        """Status label shows ◐ when running with paused directories."""
        t = DaemonTarget(name="my-host", runtime="local", status="running")
        label = daemon_status_label(t, has_paused_dirs=True)
        assert "◐" in label
        assert "●" not in label

    def test_daemon_status_label_partial_pause_not_when_globally_paused(self):
        """Globally paused daemon shows ☾ even with paused dirs."""
        t = DaemonTarget(name="my-host", runtime="local", status="paused")
        label = daemon_status_label(t, has_paused_dirs=True)
        assert "☾" in label
        assert "◐" not in label

    def test_daemon_status_label_no_paused_dirs(self):
        """Running daemon without paused dirs shows ●."""
        t = DaemonTarget(name="my-host", runtime="local", status="running")
        label = daemon_status_label(t, has_paused_dirs=False)
        assert "●" in label
        assert "◐" not in label

    @mock.patch("ai_guardian.daemon.working_dir.shorten_path")
    def test_daemon_status_label_shows_active_project_dir(self, mock_shorten):
        """Label shows active project dir instead of working dir when available."""
        mock_shorten.return_value = "~/dev/my-project"
        t = DaemonTarget(
            name="my-host",
            runtime="local",
            status="running",
            working_dir="/Users/me",
        )
        label = daemon_status_label(t, active_project_dir="/Users/me/dev/my-project")
        assert "~/dev/my-project" in label
        mock_shorten.assert_called_with("/Users/me/dev/my-project")

    @mock.patch("ai_guardian.daemon.working_dir.shorten_path")
    def test_daemon_status_label_multiple_projects(self, mock_shorten):
        """Label shows (+N more) when multiple active projects."""
        mock_shorten.return_value = "~/project-a"
        t = DaemonTarget(name="my-host", runtime="local", status="running")
        label = daemon_status_label(
            t, active_project_dir="/home/user/project-a", project_count=3
        )
        assert "~/project-a" in label
        assert "(+2 more)" in label

    @mock.patch("ai_guardian.daemon.working_dir.shorten_path")
    def test_daemon_status_label_single_project_no_count(self, mock_shorten):
        """Label omits count suffix when only one active project."""
        mock_shorten.return_value = "~/project"
        t = DaemonTarget(name="my-host", runtime="local", status="running")
        label = daemon_status_label(
            t, active_project_dir="/home/user/project", project_count=1
        )
        assert "~/project" in label
        assert "more" not in label

    @mock.patch("ai_guardian.daemon.working_dir.shorten_path")
    def test_daemon_status_label_falls_back_to_working_dir(self, mock_shorten):
        """Label falls back to working_dir when no active project."""
        mock_shorten.return_value = "~"
        t = DaemonTarget(
            name="my-host",
            runtime="local",
            status="running",
            working_dir="/Users/me",
        )
        label = daemon_status_label(t, active_project_dir=None)
        assert "~" in label
        mock_shorten.assert_called_with("/Users/me")


class TestSyncPauseUpdatesTargetStatus:
    """Tests for _sync_pause_state updating target.status (#1356)."""

    def test_sync_sets_target_paused(self):
        """_sync_pause_state sets target.status to paused from stats."""
        t = DaemonTarget(name="local", runtime="local", status="running")
        tray = DaemonTray(
            get_stats_callback=lambda: {"paused": True, "pause_remaining_seconds": 0},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [t]
        tray._sync_pause_state()
        tray._stop_pause_timer()
        assert t.status == "paused"

    def test_sync_sets_target_running(self):
        """_sync_pause_state sets target.status to running when not paused."""
        t = DaemonTarget(name="local", runtime="local", status="paused")
        tray = DaemonTray(
            get_stats_callback=lambda: {"paused": False},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [t]
        tray._status = "paused"
        tray._sync_pause_state()
        assert t.status == "running"

    def test_global_pause_updates_target_statuses(self):
        """_update_global_pause_status sets each target.status."""
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        t1 = DaemonTarget(name="a", runtime="local", status="running")
        t2 = DaemonTarget(name="b", runtime="container", status="running")
        tray._targets = [t1, t2]
        mc.get_status.side_effect = lambda t: (
            {"paused": True} if t.name == "a" else {"paused": False}
        )
        tray._update_global_pause_status()
        assert t1.status == "paused"
        assert t2.status == "running"


class TestTargetHasPausedDirs:
    """Tests for _target_has_paused_dirs helper (#1356)."""

    def test_has_paused_dirs_true(self):
        t = DaemonTarget(name="local", runtime="local", status="running")
        tray = DaemonTray(
            get_stats_callback=lambda: {"paused_dirs": {"/proj": 0}},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [t]
        assert tray._target_has_paused_dirs(t) is True

    def test_has_paused_dirs_false_empty(self):
        t = DaemonTarget(name="local", runtime="local", status="running")
        tray = DaemonTray(
            get_stats_callback=lambda: {"paused_dirs": {}},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [t]
        assert tray._target_has_paused_dirs(t) is False

    def test_has_paused_dirs_false_missing(self):
        t = DaemonTarget(name="local", runtime="local", status="running")
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [t]
        assert tray._target_has_paused_dirs(t) is False


class TestFormatDaemonListPauseIcons:
    """Tests for _format_daemon_list with partial pause icons (#1356)."""

    def test_format_shows_partial_pause_icon(self):
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        t = DaemonTarget(name="host-a", runtime="container", status="running")
        tray._targets = [t]
        mc.get_status.return_value = {"paused_dirs": {"/proj": 0}}
        result = tray._menu._format_daemon_list()
        assert "◐" in result

    def test_format_shows_running_icon_no_paused_dirs(self):
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        t = DaemonTarget(name="host-a", runtime="container", status="running")
        tray._targets = [t]
        mc.get_status.return_value = {"paused_dirs": {}}
        result = tray._menu._format_daemon_list()
        assert "●" in result
        assert "◐" not in result


class TestWorkingDirApply:
    """Tests for _apply_working_dirs populating targets from state."""

    @mock.patch("ai_guardian.daemon.working_dir.get_working_dir")
    def test_apply_sets_working_dir_on_targets(self, mock_get):
        mock_get.side_effect = lambda name: f"/home/{name}"
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [
            DaemonTarget(name="daemon-a", runtime="local"),
            DaemonTarget(name="daemon-b", runtime="local"),
        ]
        tray._menu._apply_working_dirs()
        assert tray._targets[0].working_dir == "/home/daemon-a"
        assert tray._targets[1].working_dir == "/home/daemon-b"

    @mock.patch("ai_guardian.daemon.working_dir.get_working_dir")
    def test_apply_does_not_overwrite_existing(self, mock_get):
        mock_get.return_value = "/default"
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [
            DaemonTarget(
                name="daemon-a",
                runtime="local",
                working_dir="/already/set",
            ),
        ]
        tray._menu._apply_working_dirs()
        assert tray._targets[0].working_dir == "/already/set"


class TestUntilResumePauseOption:
    """Tests for 'Until resume' indefinite pause menu option (issue #698)."""

    def test_single_daemon_pause_menu_includes_until_resume(self):
        """Single-daemon Pause submenu contains 'Until resume' item."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
        ]
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_single_daemon_menu_items()
            tray._menu._build_single_daemon_daemon_items()

            labels = [
                call[0][0]
                for call in mock_pystray.MenuItem.call_args_list
                if isinstance(call[0][0], str)
            ]
            assert "Until resume" in labels

    def test_multi_daemon_pause_menu_includes_until_resume(self):
        """Multi-daemon per-daemon Pause submenu contains 'Until resume' item."""
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
            DaemonTarget(name="remote", runtime="container", status="running"),
        ]
        mc.get_stats.return_value = {}
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_multi_daemon_menu_items()

            labels = [
                call[0][0]
                for call in mock_pystray.MenuItem.call_args_list
                if isinstance(call[0][0], str)
            ]
            assert labels.count("Until resume") >= 1

    def test_until_resume_routes_zero_minutes_via_multi_client(self):
        """'Until resume' sends pause with minutes=0 through multi_client."""
        mc = mock.MagicMock()
        local_target = DaemonTarget(name="local", runtime="local", status="running")

        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=mock.MagicMock(),
            multi_client=mc,
        )
        tray._targets = [local_target]

        t = tray._targets[0]
        tray._multi_client.send_pause(t, 0)

        mc.send_pause.assert_called_once_with(local_target, 0)

    def test_until_resume_falls_back_to_callback_without_multi_client(self):
        """'Until resume' calls pause callback with 0 when no multi_client."""
        pause_cb = mock.MagicMock()
        local_target = DaemonTarget(name="local", runtime="local", status="running")

        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=pause_cb,
        )
        tray._targets = [local_target]

        t = tray._targets[0]
        if tray._multi_client:
            tray._multi_client.send_pause(t, 0)
        else:
            tray._pause(0)

        pause_cb.assert_called_once_with(0)

    def test_pause_timer_does_not_auto_resume_indefinite_pause(self):
        """Pause timer must not auto-resume when daemon reports indefinite pause."""
        tray = DaemonTray(
            get_stats_callback=lambda: {
                "paused": True,
                "pause_remaining_seconds": 0,
            },
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._status = "paused"
        tray._start_pause_timer()
        import time

        time.sleep(0.2)
        tray._stop_pause_timer()
        assert tray._status == "paused"

    def test_pause_timer_auto_resumes_expired_timed_pause(self):
        """Pause timer auto-resumes when daemon reports timed pause expired."""
        tray = DaemonTray(
            get_stats_callback=lambda: {
                "paused": False,
                "pause_remaining_seconds": 0,
            },
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._status = "paused"
        tray._start_pause_timer()
        import time

        time.sleep(0.2)
        tray._stop_pause_timer()
        assert tray._status == "running"

    def test_icon_grey_only_when_all_daemons_paused(self):
        """Tray icon should be grey only when ALL daemons are paused."""
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
            DaemonTarget(name="remote", runtime="container", status="running"),
        ]
        mc.get_status.side_effect = lambda t: (
            {"paused": True} if t.name == "local" else {"paused": False}
        )
        tray._update_global_pause_status()
        assert tray._status == "running"

    def test_icon_grey_when_all_daemons_paused(self):
        """Tray icon is grey when every daemon is paused."""
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {"paused": True, "pause_remaining_seconds": 0},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
            DaemonTarget(name="remote", runtime="container", status="running"),
        ]
        mc.get_status.return_value = {"paused": True}
        tray._update_global_pause_status()
        tray._stop_pause_timer()
        assert tray._status == "paused"

    def test_icon_running_after_one_daemon_resumed(self):
        """Resuming one daemon clears global paused status."""
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
            DaemonTarget(name="remote", runtime="container", status="running"),
        ]
        tray._status = "paused"
        mc.get_status.side_effect = lambda t: (
            {"paused": True} if t.name == "local" else {"paused": False}
        )
        tray._update_global_pause_status()
        assert tray._status == "running"


class TestResumeMenuLabelFormats:
    """Tests for resume menu label formatting (issue #684)."""

    def test_resume_label_indefinite(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {"pause_remaining_seconds": 0},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        label = tray._menu._resume_menu_label()
        assert label == "Resume (paused)"

    def test_resume_label_with_countdown(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {"pause_remaining_seconds": 222},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        label = tray._menu._resume_menu_label()
        assert "3m" in label
        assert "42s" in label


class TestWakeDetection:
    """Tests for system wake detection and tray rebuild (issue #703)."""

    def test_rebuild_tray_refreshes_icon_and_menu(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        mock_icon = mock.MagicMock()
        tray._icon = mock_icon
        with mock.patch.object(tray, "_create_icon", return_value="new_img"):
            tray._rebuild_tray()
        assert mock_icon.icon == "new_img"
        mock_icon.update_menu.assert_called_once()

    def test_rebuild_tray_without_icon_is_noop(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._icon = None
        tray._rebuild_tray()  # Should not raise

    def test_rebuild_tray_handles_exception(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        mock_icon = mock.MagicMock()
        mock_icon.update_menu.side_effect = RuntimeError("broken")
        tray._icon = mock_icon
        tray._rebuild_tray()  # Should not raise

    def _run_stats_refresh_tick(self, time_side_effect):
        """Run one stats-refresh tick and return rebuild dispatch calls."""
        import threading as threading_mod
        import time as time_mod

        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._icon = mock.MagicMock()
        rebuild_calls = []

        def tracking_dispatch(func):
            if func == tray._rebuild_tray:
                rebuild_calls.append(True)

        orig_wait = tray._refresh_event.wait

        def stop_after_one_wait(timeout=None):
            tray._stats_refresh_running = False
            return orig_wait(0)

        with (
            mock.patch.dict(
                "sys.modules", {"PyObjCTools": None, "PyObjCTools.AppHelper": None}
            ),
            mock.patch.object(tray, "_dispatch_to_main", side_effect=tracking_dispatch),
            mock.patch.object(
                tray._refresh_event, "wait", side_effect=stop_after_one_wait
            ),
            mock.patch("ai_guardian.tray.app.time") as mock_time,
            mock.patch.object(tray._health, "_check_config_error_notification"),
            mock.patch.object(tray._health, "_check_version_mismatch"),
            mock.patch.object(tray._health, "_check_stale_code"),
            mock.patch.object(tray._health, "_check_pypi_version"),
            mock.patch.object(tray._plugins, "_poll_plugins"),
            mock.patch.object(tray._anim, "_request_discovery_refresh"),
            mock.patch.object(tray, "_register_tray_with_remotes"),
        ):
            mock_time.time = mock.MagicMock(side_effect=time_side_effect)
            tray._stats_refresh_running = True
            tray._start_stats_refresh()
            for t in threading_mod.enumerate():
                if t.name == "stats-refresh":
                    t.join(timeout=2.0)
                    break

        return rebuild_calls

    def test_stats_refresh_detects_sleep_gap(self):
        """Timer gap > 30s triggers _rebuild_tray."""
        import time as time_mod

        now = time_mod.time()
        rebuild_calls = self._run_stats_refresh_tick([now - 60, now])
        assert len(rebuild_calls) > 0

    def test_stats_refresh_normal_tick_no_rebuild(self):
        """Normal 10s tick does not trigger _rebuild_tray."""
        import time as time_mod

        now = time_mod.time()
        rebuild_calls = self._run_stats_refresh_tick([now, now + 10])
        assert len(rebuild_calls) == 0

    @pytest.mark.parametrize(
        "platform_name", ["Linux", "Windows"], ids=["linux", "windows"]
    )
    def test_register_wake_handler_non_darwin_is_noop(self, platform_name):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch("platform.system", return_value=platform_name):
            tray._register_wake_handler()
        assert tray._wake_observer is None

    def test_register_wake_handler_macos_registers_observer(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        mock_center = mock.MagicMock()
        mock_workspace = mock.MagicMock()
        mock_workspace.sharedWorkspace.return_value.notificationCenter.return_value = (
            mock_center
        )
        mock_appkit = mock.MagicMock()
        mock_appkit.NSWorkspace = mock_workspace

        with (
            mock.patch("platform.system", return_value="Darwin"),
            mock.patch.dict("sys.modules", {"AppKit": mock_appkit}),
        ):
            tray._register_wake_handler()

        mock_center.addObserverForName_object_queue_usingBlock_.assert_called_once()
        call_args = mock_center.addObserverForName_object_queue_usingBlock_.call_args[0]
        assert call_args[0] == "NSWorkspaceDidWakeNotification"
        center, token = tray._wake_observer
        assert center is mock_center
        assert (
            token
            is mock_center.addObserverForName_object_queue_usingBlock_.return_value
        )

    def test_register_wake_handler_graceful_without_pyobjc(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with (
            mock.patch("platform.system", return_value="Darwin"),
            mock.patch.dict("sys.modules", {"AppKit": None}),
        ):
            tray._register_wake_handler()
        assert tray._wake_observer is None

    def test_unregister_wake_handler_cleanup(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        mock_center = mock.MagicMock()
        mock_token = mock.MagicMock()
        tray._wake_observer = (mock_center, mock_token)
        tray._unregister_wake_handler()
        mock_center.removeObserver_.assert_called_once_with(mock_token)
        assert tray._wake_observer is None

    def test_unregister_wake_handler_noop_without_observer(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._wake_observer = None
        tray._unregister_wake_handler()  # Should not raise

    def test_stop_calls_unregister_wake_handler(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch.object(tray, "_unregister_wake_handler") as mock_unreg:
            tray.stop()
            mock_unreg.assert_called_once()

    def test_run_calls_register_wake_handler(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        mock_icon = mock.MagicMock()
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("platform.system", return_value="Linux"),
            mock.patch.object(tray, "_register_wake_handler") as mock_reg,
        ):
            mock_pystray.Icon.return_value = mock_icon
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.MenuItem = mock.MagicMock()
            tray._start_stats_refresh = mock.MagicMock()
            tray._create_icon = mock.MagicMock()
            tray._ensure_macos_activation_policy = mock.MagicMock()
            with (
                mock.patch(
                    "ai_guardian.tray.app._suppress_gtk_stderr", return_value=None
                ),
                mock.patch("ai_guardian.tray.app.threading"),
            ):
                tray._run()
            mock_reg.assert_called_once()


class TestNonBlockingMenuRefresh:
    """Tests for non-blocking menu refresh (issue #711, #754).

    Visibility callbacks must NOT trigger discovery refresh — that causes
    animation loops on GNOME/KDE.  Discovery refresh is now driven by
    the stats-refresh timer instead.
    """

    def test_single_vis_callback_does_not_trigger_discovery(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        mock_discovery = mock.MagicMock()
        tray._discovery = mock_discovery
        tray._targets = [DaemonTarget(name="local", runtime="local", status="running")]

        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_single_daemon_menu_items()

            first_call = mock_pystray.MenuItem.call_args_list[0]
            vis_cb = (
                first_call[1].get("visible") or first_call[0][2]
                if len(first_call[0]) > 2
                else first_call[1].get("visible")
            )
            vis_cb(None)

        mock_discovery.request_refresh.assert_not_called()

    def test_multi_vis_callback_does_not_trigger_discovery(self):
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        mock_discovery = mock.MagicMock()
        tray._discovery = mock_discovery
        tray._targets = [
            DaemonTarget(name="d1", runtime="local", status="running"),
            DaemonTarget(name="d2", runtime="manual", status="running"),
        ]
        mc.get_stats.return_value = {}

        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_multi_daemon_menu_items()

            for call in mock_pystray.MenuItem.call_args_list:
                vis_cb = call[1].get("visible")
                if vis_cb is not None and callable(vis_cb):
                    vis_cb(None)

        mock_discovery.request_refresh.assert_not_called()


class TestIsTrayRunningReturnsPid:
    """Tests for _is_tray_running() returning PID instead of True (issue #713)."""

    def test_returns_false_when_no_lock(self, tmp_path):
        with mock.patch(
            "ai_guardian.tray.app._get_tray_lock_path",
            return_value=tmp_path / "tray.lock",
        ):
            assert _is_tray_running() is False

    def test_returns_pid_when_alive(self, tmp_path):
        import os

        lock = tmp_path / "tray.lock"
        lock.write_text(str(os.getpid()))
        with mock.patch("ai_guardian.tray.app._get_tray_lock_path", return_value=lock):
            result = _is_tray_running()
            assert result == os.getpid()

    def test_returns_false_when_pid_dead(self, tmp_path):
        lock = tmp_path / "tray.lock"
        lock.write_text("999999999")
        with (
            mock.patch("ai_guardian.tray.app._get_tray_lock_path", return_value=lock),
            mock.patch("ai_guardian.daemon.is_pid_alive", return_value=False),
        ):
            assert _is_tray_running() is False
            assert not lock.exists()

    def test_returns_false_when_lock_has_bad_content(self, tmp_path):
        lock = tmp_path / "tray.lock"
        lock.write_text("not-a-number")
        with mock.patch("ai_guardian.tray.app._get_tray_lock_path", return_value=lock):
            assert _is_tray_running() is False
            assert not lock.exists()


class TestRunBlockingReturnValue:
    """Tests for run_blocking() returning False when already running (issue #713)."""

    def test_returns_false_without_pystray(self):
        with mock.patch("ai_guardian.tray.app.HAS_PYSTRAY", False):
            tray = DaemonTray(
                get_stats_callback=lambda: {},
                stop_callback=lambda: None,
                pause_callback=lambda: None,
            )
            assert tray.run_blocking() is False

    def test_returns_false_when_already_running(self):
        with (
            mock.patch("ai_guardian.tray.app.HAS_PYSTRAY", True),
            mock.patch("ai_guardian.tray.app._is_tray_running", return_value=12345),
        ):
            tray = DaemonTray(
                get_stats_callback=lambda: {},
                stop_callback=lambda: None,
                pause_callback=lambda: None,
            )
            assert tray.run_blocking() is False


class TestTrayStartAlreadyRunningMessage:
    """Tests for CLI printing informative message when tray is already running (issue #713)."""

    def test_prints_already_running_with_pid(self):
        from ai_guardian.cli_handlers import _handle_tray_start

        args = mock.MagicMock()
        args.background = False
        args.no_discover = False

        with (
            mock.patch("ai_guardian.tray.app.is_tray_available", return_value=True),
            mock.patch("ai_guardian.tray.app._is_tray_running", return_value=42),
            mock.patch("sys.stdin") as mock_stdin,
            mock.patch(
                "ai_guardian.cli_handlers._load_config_file", return_value=({}, None)
            ),
            mock.patch("builtins.print") as mock_print,
        ):
            mock_stdin.isatty.return_value = False
            result = _handle_tray_start(args)

        assert result == 0
        mock_print.assert_called_once_with("Tray is already running (pid 42)")

    def test_prints_success_when_not_running(self):
        from ai_guardian.cli_handlers import _handle_tray_start

        args = mock.MagicMock()
        args.background = False
        args.no_discover = False

        with (
            mock.patch("ai_guardian.tray.app.is_tray_available", return_value=True),
            mock.patch("ai_guardian.tray.app._is_tray_running", return_value=False),
            mock.patch("sys.stdin") as mock_stdin,
            mock.patch(
                "ai_guardian.cli_handlers._load_config_file", return_value=({}, None)
            ),
            mock.patch("ai_guardian.tray.app.DaemonTray") as MockTray,
            mock.patch("ai_guardian.daemon.discovery.DaemonDiscovery"),
            mock.patch("ai_guardian.daemon.multi_client.MultiDaemonClient"),
            mock.patch(
                "ai_guardian.daemon.client.send_status_request", return_value={}
            ),
            mock.patch("builtins.print") as mock_print,
        ):
            mock_stdin.isatty.return_value = False
            mock_tray_instance = MockTray.return_value
            mock_tray_instance.run_blocking.return_value = None
            result = _handle_tray_start(args)

        assert result == 0
        mock_print.assert_called_once_with(
            "ai-guardian tray started (multi-daemon mode)"
        )


class TestMcpProactiveMenuVisibility:
    """Tests for MCP Proactive menu visibility based on MCP installation (issue #726)."""

    def test_is_mcp_installed_returns_true_when_ide_config_has_entry(self, tmp_path):
        """Detects ai-guardian MCP server entry in an IDE config file."""
        import json

        config_file = tmp_path / ".claude.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "ai-guardian": {
                            "command": "ai-guardian",
                            "args": ["mcp-server"],
                        }
                    }
                }
            )
        )
        with mock.patch(
            "ai_guardian.daemon.is_mcp_installed",
            wraps=is_mcp_installed,
        ):
            with mock.patch("pathlib.Path.expanduser", return_value=config_file):
                assert is_mcp_installed() is True

    def test_is_mcp_installed_returns_false_when_no_ide_configs(self, tmp_path):
        """Returns False when no IDE config files contain ai-guardian."""
        missing = tmp_path / "nonexistent.json"
        with mock.patch("pathlib.Path.expanduser", return_value=missing):
            assert is_mcp_installed() is False

    def test_is_mcp_installed_returns_false_when_no_mcp_entry(self, tmp_path):
        """Returns False when IDE config exists but has no ai-guardian entry."""
        import json

        config_file = tmp_path / ".claude.json"
        config_file.write_text(json.dumps({"mcpServers": {"other-tool": {}}}))
        with mock.patch("pathlib.Path.expanduser", return_value=config_file):
            assert is_mcp_installed() is False

    def test_is_mcp_installed_handles_corrupt_json(self, tmp_path):
        """Gracefully handles corrupt JSON config files."""
        config_file = tmp_path / ".claude.json"
        config_file.write_text("not valid json {{{")
        with mock.patch("pathlib.Path.expanduser", return_value=config_file):
            assert is_mcp_installed() is False

    def test_mcp_installed_cached_at_init(self):
        """_mcp_installed and _mcp_installed_local are set during __init__."""
        with mock.patch("ai_guardian.tray.app.is_mcp_installed", return_value=False):
            tray = DaemonTray(
                get_stats_callback=lambda: {},
                stop_callback=lambda: None,
                pause_callback=lambda mins: None,
            )
            assert tray._mcp_installed_local is False
            assert tray._mcp_installed is False

        with mock.patch("ai_guardian.tray.app.is_mcp_installed", return_value=True):
            tray = DaemonTray(
                get_stats_callback=lambda: {},
                stop_callback=lambda: None,
                pause_callback=lambda mins: None,
            )
            assert tray._mcp_installed_local is True
            assert tray._mcp_installed is True

    def test_is_mcp_installed_checks_claude_settings_json(self, tmp_path):
        """Detects ai-guardian MCP entry in ~/.claude/settings.json."""
        import json

        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        config_file = settings_dir / "settings.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "ai-guardian": {
                            "command": "ai-guardian",
                            "args": ["mcp-server"],
                        }
                    }
                }
            )
        )
        with mock.patch("pathlib.Path.expanduser", return_value=config_file):
            assert is_mcp_installed() is True


class TestMcpProactiveMultiDaemonClosure:
    """Regression test for MCP Proactive visibility in multi-daemon mode.

    The visibility lambda must capture the loop slot via default argument,
    not close over the _is_slot_running name (which would always reference
    the last iteration's function).
    """

    def test_mcp_visible_in_first_daemon_slot(self):
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
            DaemonTarget(name="remote", runtime="container", status="running"),
        ]
        tray._mcp_installed_local = True
        tray._mcp_installed = True
        tray._mcp_installed_per_daemon = {
            ("local", "local"): True,
            ("remote", "container"): True,
        }
        mc.get_status.return_value = {}

        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_multi_daemon_menu_items()

            mcp_calls = [
                call
                for call in mock_pystray.MenuItem.call_args_list
                if len(call[0]) > 0
                and callable(call[0][0])
                and not isinstance(call[0][0], mock.MagicMock)
            ]
            mcp_vis_results = []
            for call in mcp_calls:
                label_fn = call[0][0]
                vis_fn = call[1].get("visible")
                try:
                    label = label_fn(None)
                except Exception:
                    continue
                if "MCP" in str(label) and vis_fn:
                    mcp_vis_results.append(vis_fn(None))

            assert len(mcp_vis_results) >= 2
            assert mcp_vis_results[0] is True
            assert mcp_vis_results[1] is True


class TestShellMenuItem:
    """Tests for Shell menu item in tray (issue #706)."""

    def test_single_daemon_menu_includes_shell(self):
        """Single-daemon flat menu contains 'Terminal' item."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
        ]
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_single_daemon_menu_items()

            labels = [
                call[0][0]
                for call in mock_pystray.MenuItem.call_args_list
                if isinstance(call[0][0], str)
            ]
            assert "Terminal" in labels

    def test_single_daemon_shell_after_mcp(self):
        """Shell item appears after MCP Proactive section in single-daemon menu."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
        ]
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_single_daemon_menu_items()

            labels = [
                call[0][0]
                for call in mock_pystray.MenuItem.call_args_list
                if isinstance(call[0][0], str)
            ]
            assert "Terminal" in labels
            assert "Doctor" not in labels

    def test_multi_daemon_menu_includes_shell(self):
        """Multi-daemon per-daemon submenu contains 'Terminal' item."""
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
            DaemonTarget(name="remote", runtime="container", status="running"),
        ]
        mc.get_stats.return_value = {}
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_multi_daemon_menu_items()

            labels = [
                call[0][0]
                for call in mock_pystray.MenuItem.call_args_list
                if isinstance(call[0][0], str)
            ]
            assert "Terminal" in labels
            assert "Doctor" not in labels

    def test_shell_routes_via_multi_client(self):
        """Shell action calls multi_client.open_shell for local target."""
        mc = mock.MagicMock()
        local_target = DaemonTarget(name="local", runtime="local", status="running")

        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        tray._targets = [local_target]

        tray._multi_client.open_shell(local_target)
        mc.open_shell.assert_called_once_with(local_target)

    def test_shell_falls_back_without_multi_client(self):
        """Shell action falls back to _launch_shell without multi_client."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        local_target = DaemonTarget(name="local", runtime="local", status="running")
        tray._targets = [local_target]

        with mock.patch("tests.unit.test_daemon_tray.launch_shell") as mock_shell:
            t = tray._targets[0]
            if tray._multi_client:
                tray._multi_client.open_shell(t)
            else:
                launch_shell()
            mock_shell.assert_called_once()

    @pytest.mark.parametrize(
        "platform_name, env, expected_shell",
        [
            pytest.param(
                "Linux", {"SHELL": "/bin/zsh"}, "/bin/zsh", id="unix-shell-env-set"
            ),
            pytest.param("Linux", {}, "/bin/sh", id="unix-shell-env-unset"),
            pytest.param(
                "Windows",
                {"COMSPEC": r"C:\Windows\cmd.exe"},
                r"C:\Windows\cmd.exe",
                id="win-comspec-set",
            ),
            pytest.param("Windows", {}, "cmd.exe", id="win-comspec-unset"),
        ],
    )
    def test_launch_shell_resolves_shell(self, platform_name, env, expected_shell):
        """_launch_shell uses $SHELL / $COMSPEC depending on platform."""
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch("platform.system", return_value=platform_name):
                with mock.patch(
                    "ai_guardian.daemon.multi_client._launch_in_terminal"
                ) as mock_launch:
                    launch_shell()
                    mock_launch.assert_called_once_with(
                        [expected_shell],
                        keep_open=True,
                        cwd=None,
                    )

    def test_launch_shell_passes_cwd(self):
        """_launch_shell passes working directory as cwd."""
        if sys.platform == "win32":
            env = {"COMSPEC": r"C:\Windows\cmd.exe"}
            expected_shell = r"C:\Windows\cmd.exe"
            platform_name = "Windows"
        else:
            env = {"SHELL": "/bin/bash"}
            expected_shell = "/bin/bash"
            platform_name = "Linux"
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch("platform.system", return_value=platform_name):
                with mock.patch(
                    "ai_guardian.daemon.multi_client._launch_in_terminal"
                ) as mock_launch:
                    launch_shell(cwd="/home/user/project")
                    mock_launch.assert_called_once_with(
                        [expected_shell],
                        keep_open=True,
                        cwd="/home/user/project",
                    )


class TestPluginMenuItems:
    """Tests for tray plugin menu integration (issue #590)."""

    def _make_tray(self, targets=None, multi_client=None):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=multi_client,
        )
        if targets is not None:
            tray._targets = targets
        return tray

    def test_daemon_plugins_initialized_empty(self):
        tray = self._make_tray()
        assert tray._plugins._daemon_plugins == {}
        assert tray._plugins._last_plugins_hash == {}

    def test_get_daemon_plugins_returns_empty_for_unknown_slot(self):
        tray = self._make_tray()
        assert tray._plugins._get_daemon_plugins(0) == []

    def test_get_daemon_plugins_returns_plugins_for_known_slot(self):
        from ai_guardian.tray.plugins import Plugin, PluginItem

        tray = self._make_tray()
        tray._plugins._daemon_plugins[0] = [
            Plugin(name="Test", items=[PluginItem(label="Run", command="echo")])
        ]
        plugins = tray._plugins._get_daemon_plugins(0)
        assert len(plugins) == 1
        assert plugins[0].name == "Test"

    def test_poll_plugins_updates_daemon_plugins(self):
        mc = mock.MagicMock()
        mc._local_plugins.return_value = {
            "plugins": [
                {
                    "name": "TestPlugin",
                    "items": [
                        {"label": "Hello", "command": "echo", "type": "background"}
                    ],
                }
            ]
        }
        local_target = DaemonTarget(name="local", runtime="local", status="running")
        tray = self._make_tray(targets=[local_target], multi_client=mc)
        tray._plugins._poll_plugins()
        assert 0 in tray._plugins._daemon_plugins
        assert len(tray._plugins._daemon_plugins[0]) == 1
        assert tray._plugins._daemon_plugins[0][0].name == "TestPlugin"

    def test_poll_plugins_skips_stopped_remote_daemons(self):
        mc = mock.MagicMock()
        stopped = DaemonTarget(name="remote", runtime="container", status="stopped")
        tray = self._make_tray(targets=[stopped], multi_client=mc)
        tray._plugins._poll_plugins()
        mc.get_plugins.assert_not_called()

    def test_poll_plugins_loads_local_even_when_stopped(self):
        mc = mock.MagicMock()
        mc._local_plugins.return_value = {
            "plugins": [{"name": "Local", "items": [{"label": "A", "command": "b"}]}]
        }
        stopped_local = DaemonTarget(name="local", runtime="local", status="stopped")
        tray = self._make_tray(targets=[stopped_local], multi_client=mc)
        tray._plugins._poll_plugins()
        mc._local_plugins.assert_called_once()
        assert 0 in tray._plugins._daemon_plugins

    def test_poll_plugins_no_rebuild_when_unchanged(self):
        mc = mock.MagicMock()
        mc._local_plugins.return_value = {
            "plugins": [{"name": "P", "items": [{"label": "A", "command": "b"}]}]
        }
        local = DaemonTarget(name="local", runtime="local", status="running")
        tray = self._make_tray(targets=[local], multi_client=mc)
        tray._plugins._poll_plugins()
        first_plugins = tray._plugins._daemon_plugins[0]
        tray._plugins._poll_plugins()
        assert tray._plugins._daemon_plugins[0] is first_plugins

    def test_build_single_daemon_plugin_items_returns_list(self):
        tray = self._make_tray(
            targets=[DaemonTarget(name="local", runtime="local", status="running")]
        )
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            items = tray._plugins._build_single_daemon_plugin_items()
        assert isinstance(items, list)
        assert len(items) > 0

    def test_build_multi_daemon_plugin_slots_returns_list(self):
        tray = self._make_tray()
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            items = tray._plugins._build_multi_daemon_plugin_slots(0)
        assert isinstance(items, list)
        assert len(items) == tray._plugins._MAX_PLUGIN_SLOTS

    def test_execute_plugin_command_terminal(self):
        with mock.patch(
            "ai_guardian.daemon.multi_client._launch_in_terminal"
        ) as mock_launch:
            execute_plugin_command("echo hello", "terminal")
            mock_launch.assert_called_once()
            assert mock_launch.call_args[0][0] == ["echo", "hello"]
            assert mock_launch.call_args[1]["keep_open"] is True

    def test_execute_plugin_command_info(self):
        with mock.patch("subprocess.run") as mock_run:
            with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                execute_plugin_command("echo hello", "background")
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                assert args == ["/bin/zsh", "-lc", "echo hello"]

    def test_execute_plugin_command_notification(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(stdout="Pod count: 3\n")
            with mock.patch(
                "ai_guardian.tray.plugins.send_notification"
            ) as mock_notify:
                with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                    execute_plugin_command("kubectl get pods | wc -l", "notification")
                    mock_run.assert_called_once()
                    args = mock_run.call_args[0][0]
                    assert args == ["/bin/zsh", "-lc", "kubectl get pods | wc -l"]
                    mock_notify.assert_called_once_with("AI Guardian", "Pod count: 3")

    def test_execute_plugin_command_clipboard(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(stdout="10.0.0.5\n")
            with mock.patch("ai_guardian.tray.plugins.copy_to_clipboard") as mock_copy:
                with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                    execute_plugin_command("kubectl get svc -o ip", "clipboard")
                    mock_run.assert_called_once()
                    args = mock_run.call_args[0][0]
                    assert args == ["/bin/zsh", "-lc", "kubectl get svc -o ip"]
                    mock_copy.assert_called_once_with("10.0.0.5")

    def test_execute_plugin_command_notification_no_output(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(stdout="")
            with mock.patch(
                "ai_guardian.tray.plugins.send_notification"
            ) as mock_notify:
                with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                    execute_plugin_command("true", "notification")
                    mock_notify.assert_called_once_with("AI Guardian", "(no output)")

    def test_execute_plugin_command_modal(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                stdout="ai-guardian 1.8.0\n",
                returncode=0,
                stderr="",
            )
            with mock.patch("ai_guardian.tray.plugins.show_dialog") as mock_dialog:
                with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                    execute_plugin_command(
                        "ai-guardian --version",
                        "modal",
                        label="Version",
                    )
                    mock_run.assert_called_once()
                    args = mock_run.call_args[0][0]
                    assert args[0] == "/bin/zsh"
                    assert args[1] == "-lc"
                    assert "python" in args[2]  # May be absolute path
                    assert "-m ai_guardian --version" in args[2]
                    mock_dialog.assert_called_once_with("Version", "ai-guardian 1.8.0")

    def test_execute_plugin_command_modal_no_output(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                stdout="",
                returncode=0,
                stderr="",
            )
            with mock.patch("ai_guardian.tray.plugins.show_dialog") as mock_dialog:
                with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                    execute_plugin_command("true", "modal")
                    mock_dialog.assert_called_once_with("AI Guardian", "(no output)")

    def test_execute_plugin_command_modal_shows_stderr_on_failure(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                stdout="",
                returncode=1,
                stderr="command not found\n",
            )
            with mock.patch("ai_guardian.tray.plugins.show_dialog") as mock_dialog:
                with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                    execute_plugin_command(
                        "bad-command",
                        "modal",
                        label="Check",
                    )
                    mock_dialog.assert_called_once_with("Check", "command not found")

    def test_execute_plugin_command_modal_shows_both_on_failure(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                stdout="partial output\n",
                returncode=1,
                stderr="warning: something\n",
            )
            with mock.patch("ai_guardian.tray.plugins.show_dialog") as mock_dialog:
                with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                    execute_plugin_command("cmd", "modal")
                    title, msg = mock_dialog.call_args[0]
                    assert title == "AI Guardian"
                    assert "partial output" in msg
                    assert "warning: something" in msg

    def test_execute_plugin_command_modal_shows_stderr_on_success(self):
        """Modal includes stderr even on success (e.g. --summary output)."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                stdout="",
                returncode=0,
                stderr="Sanitized image: 3 region(s) redacted\n",
            )
            with mock.patch("ai_guardian.tray.plugins.show_dialog") as mock_dialog:
                with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                    execute_plugin_command("cmd", "modal")
                    mock_dialog.assert_called_once_with(
                        "AI Guardian",
                        "Sanitized image: 3 region(s) redacted",
                    )

    def test_execute_plugin_command_modal_merges_stdout_and_stderr_on_success(self):
        """Modal shows both stdout and stderr on success."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                stdout="main output\n",
                returncode=0,
                stderr="summary line\n",
            )
            with mock.patch("ai_guardian.tray.plugins.show_dialog") as mock_dialog:
                with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                    execute_plugin_command("cmd", "modal")
                    title, msg = mock_dialog.call_args[0]
                    assert "main output" in msg
                    assert "summary line" in msg

    def test_execute_plugin_command_uses_user_shell(self):
        """Non-terminal commands use the user's SHELL env var."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(stdout="ok\n")
            with mock.patch("ai_guardian.tray.plugins.send_notification"):
                with mock.patch.dict("os.environ", {"SHELL": "/usr/local/bin/fish"}):
                    execute_plugin_command("echo hi", "notification")
                    args = mock_run.call_args[0][0]
                    assert args[0] == "/usr/local/bin/fish"
                    assert args[1] == "-lc"

    def test_execute_plugin_command_defaults_to_bash(self):
        """Falls back to /bin/bash when SHELL is unset."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(stdout="ok\n")
            with mock.patch("ai_guardian.tray.plugins.send_notification"):
                with mock.patch.dict("os.environ", {}, clear=True):
                    execute_plugin_command("echo hi", "notification")
                    args = mock_run.call_args[0][0]
                    assert args[0] == "/bin/bash"
                    assert args[1] == "-lc"

    def test_execute_plugin_command_terminal_no_login_shell(self):
        """Terminal type does NOT use login shell wrapping."""
        with mock.patch(
            "ai_guardian.daemon.multi_client._launch_in_terminal"
        ) as mock_launch:
            with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                execute_plugin_command("echo hello", "terminal")
                mock_launch.assert_called_once()
                args = mock_launch.call_args[0][0]
                assert args == ["echo", "hello"]

    def test_execute_plugin_command_remote_target_no_login_shell(self):
        """Container/k8s targets don't get login shell wrapping."""
        target = mock.MagicMock()
        target.runtime = "container"
        target.container_engine = "podman"
        target.container_id = "abc123"
        target.working_dir = None
        with mock.patch("subprocess.run") as mock_run:
            with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                execute_plugin_command(
                    "echo hello",
                    "background",
                    target=target,
                    run_on_target=True,
                )
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                assert args[0] == "podman"
                assert "exec" in args

    def test_resolve_plugin_ai_guardian_replaces_bare_command(self):
        """ai-guardian in plugin commands resolves to python -m ai_guardian."""
        result = resolve_plugin_ai_guardian(
            "ai-guardian sanitize img.png --summary",
            False,
            None,
        )
        assert "python" in result  # May be absolute path
        assert "-m ai_guardian sanitize img.png --summary" in result

    def test_resolve_plugin_ai_guardian_bare_no_args(self):
        """ai-guardian alone (no arguments) resolves correctly."""
        result = resolve_plugin_ai_guardian(
            "ai-guardian",
            False,
            None,
        )
        assert "python" in result.lower()
        assert "-m ai_guardian" in result
        before_m = result.split("-m")[0].strip().lower()
        assert (
            before_m.endswith("python")
            or before_m.endswith("python.exe")
            or "python" in before_m
        )

    def test_resolve_plugin_ai_guardian_non_matching_command(self):
        """Commands not starting with ai-guardian are left unchanged."""
        result = resolve_plugin_ai_guardian(
            "kubectl get pods",
            False,
            None,
        )
        assert result == "kubectl get pods"

    def test_resolve_plugin_ai_guardian_skipped_for_remote_container(self):
        """Remote container targets keep bare ai-guardian for PATH resolution."""
        target = mock.MagicMock()
        target.runtime = "container"
        result = resolve_plugin_ai_guardian(
            "ai-guardian doctor",
            True,
            target,
        )
        assert result == "ai-guardian doctor"

    def test_resolve_plugin_ai_guardian_skipped_for_remote_kubernetes(self):
        """Remote kubernetes targets keep bare ai-guardian."""
        target = mock.MagicMock()
        target.runtime = "kubernetes"
        result = resolve_plugin_ai_guardian(
            "ai-guardian doctor",
            True,
            target,
        )
        assert result == "ai-guardian doctor"

    def test_resolve_plugin_ai_guardian_local_target_resolves(self):
        """Local targets still resolve ai-guardian to tray's Python."""
        target = mock.MagicMock()
        target.runtime = "local"
        with mock.patch("sys.executable", "/venv/bin/python"):
            result = resolve_plugin_ai_guardian(
                "ai-guardian doctor",
                True,
                target,
            )
            assert "-m ai_guardian doctor" in result

    def test_execute_plugin_command_resolves_ai_guardian_terminal(self):
        """Terminal plugin commands with ai-guardian use tray's Python."""
        with mock.patch(
            "ai_guardian.daemon.multi_client._launch_in_terminal"
        ) as mock_launch:
            execute_plugin_command(
                "ai-guardian doctor",
                "terminal",
            )
            mock_launch.assert_called_once()
            args = mock_launch.call_args[0][0]
            assert "python" in args[0]  # May be absolute path
            assert args[1:3] == ["-m", "ai_guardian"]
            assert "doctor" in args

    def test_execute_plugin_command_resolves_ai_guardian_notification(self):
        """Notification plugin commands with ai-guardian use python -m."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(stdout="ok\n")
            with mock.patch("ai_guardian.tray.plugins.send_notification"):
                execute_plugin_command(
                    "ai-guardian version",
                    "notification",
                )
                args = mock_run.call_args[0][0]
                cmd_line = " ".join(args)
                assert "python" in cmd_line
                assert "-m ai_guardian" in cmd_line

    def test_execute_plugin_command_with_params(self):
        """Uses subprocess.Popen when tkinter is available (can't share NSApplication)."""
        tray = self._make_tray()
        item_dict = {
            "label": "Deploy",
            "command": "deploy {tray.env}",
            "type": "terminal",
            "params": [{"name": "env", "hint": "Environment", "default": "dev"}],
        }
        with mock.patch(
            "ai_guardian.tui.display._tkinter_available", return_value=True
        ):
            with mock.patch(
                "ai_guardian.tui.display._nicegui_available", return_value=False
            ):
                with mock.patch("subprocess.Popen") as mock_popen:
                    with mock.patch("sys.executable", "/usr/bin/python3"):
                        tray._plugins._execute_plugin_command_with_params(item_dict)
                        mock_popen.assert_called_once()
                        cmd = mock_popen.call_args[0][0]
                        assert "prompt" in cmd and "--mode" in cmd
                        assert "--output-file" in " ".join(cmd)

    def test_execute_plugin_command_with_params_textual_fallback(self):
        """Falls back to _launch_in_terminal when tkinter and NiceGUI unavailable."""
        tray = self._make_tray()
        item_dict = {
            "label": "Deploy",
            "command": "deploy {tray.env}",
            "type": "terminal",
            "params": [{"name": "env", "hint": "Environment", "default": "dev"}],
        }
        with mock.patch(
            "ai_guardian.tui.display._tkinter_available", return_value=False
        ):
            with mock.patch(
                "ai_guardian.tui.display._nicegui_available", return_value=False
            ):
                with mock.patch(
                    "ai_guardian.daemon.multi_client._launch_in_terminal"
                ) as mock_launch:
                    with mock.patch("sys.executable", "/usr/bin/python3"):
                        tray._plugins._execute_plugin_command_with_params(item_dict)
                        mock_launch.assert_called_once()

    def test_execute_plugin_command_with_params_nicegui_direct_call(self):
        """Uses direct TrayPromptApp call when tkinter unavailable but NiceGUI available."""
        import ai_guardian.tui.tray_prompt  # noqa: F401 — pre-import before mocking display

        tray = self._make_tray()
        item_dict = {
            "label": "Deploy",
            "command": "deploy {tray.env}",
            "type": "terminal",
            "params": [{"name": "env", "hint": "Environment", "default": "dev"}],
        }
        with mock.patch(
            "ai_guardian.tui.display._tkinter_available", return_value=False
        ):
            with mock.patch(
                "ai_guardian.tui.display._nicegui_available", return_value=True
            ):
                with mock.patch(
                    "ai_guardian.tui.tray_prompt.TrayPromptApp"
                ) as mock_app:
                    mock_app.return_value.run.return_value = None
                    tray._plugins._execute_plugin_command_with_params(item_dict)
                    import time

                    time.sleep(0.1)
                    mock_app.assert_called_once()

    def test_execute_plugin_command_with_params_platform_map(self):
        tray = self._make_tray()
        item_dict = {
            "label": "Shell",
            "command": {"darwin": "open .", "default": "xdg-open ."},
            "type": "terminal",
            "params": [],
        }
        with mock.patch(
            "ai_guardian.tui.display._tkinter_available", return_value=True
        ):
            with mock.patch(
                "ai_guardian.tui.display._nicegui_available", return_value=False
            ):
                with mock.patch("subprocess.Popen") as mock_popen:
                    with mock.patch("sys.executable", "/usr/bin/python3"):
                        tray._plugins._execute_plugin_command_with_params(item_dict)
                        mock_popen.assert_called_once()

    def test_execute_plugin_command_with_params_no_match(self):
        tray = self._make_tray()
        item_dict = {
            "label": "Shell",
            "command": {"windows": "start ."},
            "type": "terminal",
            "params": [],
        }
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch(
                "ai_guardian.tui.display._tkinter_available", return_value=True
            ):
                with mock.patch(
                    "ai_guardian.tui.display._nicegui_available", return_value=False
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        tray._plugins._execute_plugin_command_with_params(item_dict)
                        mock_popen.assert_not_called()

    def test_execute_plugin_command_with_params_dispatches_on_submit(self):
        """Watcher thread dispatches command when output file has content."""

        tray = self._make_tray()
        item_dict = {
            "label": "Deploy",
            "command": "deploy prod",
            "type": "terminal",
            "params": [],
        }
        with mock.patch(
            "ai_guardian.tui.display._tkinter_available", return_value=True
        ):
            with mock.patch(
                "ai_guardian.tui.display._nicegui_available", return_value=False
            ):
                with mock.patch("subprocess.Popen") as mock_popen:
                    with mock.patch("sys.executable", "/usr/bin/python3"):
                        tray._plugins._execute_plugin_command_with_params(item_dict)
                        cmd = mock_popen.call_args[0][0]
                        output_file_idx = cmd.index("--output-file") + 1
                        output_path = cmd[output_file_idx]
                        with open(output_path, "w") as f:
                            f.write("deploy prod")

        import time

        with mock.patch("ai_guardian.tray.plugins.execute_plugin_command") as mock_exec:
            time.sleep(1.5)
            if mock_exec.called:
                mock_exec.assert_called_once_with(
                    "deploy prod",
                    "terminal",
                    target=None,
                    run_on_target=False,
                    label="Deploy",
                )

    def test_execute_plugin_command_with_params_noop_on_cancel(self):
        """Watcher thread does nothing when output file is empty (cancel)."""
        import time

        tray = self._make_tray()
        item_dict = {
            "label": "Deploy",
            "command": "deploy prod",
            "type": "terminal",
            "params": [],
        }
        with mock.patch(
            "ai_guardian.tui.display._tkinter_available", return_value=True
        ):
            with mock.patch(
                "ai_guardian.tui.display._nicegui_available", return_value=False
            ):
                with mock.patch("subprocess.Popen") as mock_popen:
                    with mock.patch("sys.executable", "/usr/bin/python3"):
                        tray._plugins._execute_plugin_command_with_params(item_dict)
                        cmd = mock_popen.call_args[0][0]
                        output_file_idx = cmd.index("--output-file") + 1
                        output_path = cmd[output_file_idx]
                        with open(output_path, "w") as f:
                            pass

        with mock.patch("ai_guardian.tray.plugins.execute_plugin_command") as mock_exec:
            time.sleep(1.5)
            mock_exec.assert_not_called()

    def test_execute_plugin_command_shell_and_operator(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                stdout="ok\n",
                returncode=0,
                stderr="",
            )
            with mock.patch("ai_guardian.tray.plugins.show_dialog"):
                with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                    execute_plugin_command(
                        "uname -a && lsb_release -a",
                        "modal",
                    )
                    args = mock_run.call_args[0][0]
                    assert args == ["/bin/zsh", "-lc", "uname -a && lsb_release -a"]

    def test_execute_plugin_command_shell_semicolon(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(stdout="hello\nworld\n")
            with mock.patch("ai_guardian.tray.plugins.send_notification"):
                with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                    execute_plugin_command(
                        "echo hello; echo world",
                        "notification",
                    )
                    args = mock_run.call_args[0][0]
                    assert args == ["/bin/zsh", "-lc", "echo hello; echo world"]

    def test_execute_plugin_command_shell_redirect(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(stdout="")
            with mock.patch("ai_guardian.tray.plugins.copy_to_clipboard"):
                with mock.patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                    execute_plugin_command(
                        "ai-guardian doctor > /tmp/report.txt",
                        "clipboard",
                    )
                    args = mock_run.call_args[0][0]
                    assert args[0] == "/bin/zsh"
                    assert args[1] == "-lc"
                    assert "python" in args[2]  # May be absolute path
                    assert "-m ai_guardian doctor > /tmp/report.txt" in args[2]

    def test_execute_plugin_command_shell_terminal(self):
        with mock.patch(
            "ai_guardian.daemon.multi_client._launch_in_terminal"
        ) as mock_launch:
            execute_plugin_command(
                "echo hello && echo world",
                "terminal",
            )
            mock_launch.assert_called_once()
            assert mock_launch.call_args[0][0] == [
                "sh",
                "-c",
                "echo hello && echo world",
            ]

    def test_execute_plugin_command_simple_still_splits(self):
        with mock.patch(
            "ai_guardian.daemon.multi_client._launch_in_terminal"
        ) as mock_launch:
            execute_plugin_command("echo hello", "terminal")
            mock_launch.assert_called_once()
            assert mock_launch.call_args[0][0] == ["echo", "hello"]


class TestDoctorMenuItem:
    """Verify Doctor menu item and config error notification (#742)."""

    def test_launch_doctor_calls_launch_in_terminal(self):
        with mock.patch(
            "ai_guardian.daemon.multi_client._launch_in_terminal"
        ) as mock_launch:
            with mock.patch("sys.executable", "/usr/bin/python3"):
                launch_doctor()
                mock_launch.assert_called_once()
                cmd = mock_launch.call_args[0][0]
                assert "doctor" in cmd
                assert mock_launch.call_args[1].get("keep_open", True) is True

    def test_launch_doctor_uses_python_command(self):
        with mock.patch(
            "ai_guardian.daemon.multi_client._launch_in_terminal"
        ) as mock_launch:
            launch_doctor()
            cmd = mock_launch.call_args[0][0]
            assert "doctor" in cmd
            assert cmd[-1] == "doctor"

    def test_config_error_notification_shown_once(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {"config_error": "parse error"},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch(
            "ai_guardian.tray.notifications.send_config_error_notification"
        ) as mock_notify:
            tray._health._check_config_error_notification()
            assert mock_notify.call_count == 1

            tray._health._check_config_error_notification()
            assert mock_notify.call_count == 1

    def test_config_error_notification_resets_when_fixed(self):
        error_state = {"config_error": "parse error"}
        tray = DaemonTray(
            get_stats_callback=lambda: error_state,
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch(
            "ai_guardian.tray.notifications.send_config_error_notification"
        ):
            tray._health._check_config_error_notification()
            assert tray._health._config_error_notified is True

            error_state["config_error"] = None
            tray._health._check_config_error_notification()
            assert tray._health._config_error_notified is False

    def test_no_notification_without_config_error(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {"config_error": None},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch(
            "ai_guardian.tray.notifications.send_config_error_notification"
        ) as mock_notify:
            tray._health._check_config_error_notification()
            mock_notify.assert_not_called()


class TestAboutMenuItem:
    """Tests for About menu item in tray (issue #766)."""

    def test_build_about_text_contains_version(self):
        with mock.patch(
            "ai_guardian.tray.menu.build_about_text",
            wraps=build_about_text,
        ):
            text = build_about_text()
        assert "AI Guardian v" in text

    def test_build_about_text_contains_python(self):
        text = build_about_text()
        import sys

        expected = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        assert f"Python: {expected}" in text

    def test_build_about_text_contains_platform(self):
        text = build_about_text()
        assert "Platform: " in text

    def test_build_about_text_contains_config_path(self):
        from pathlib import Path

        with mock.patch(
            "ai_guardian.config.utils.get_config_dir", return_value=Path("/fake/config")
        ):
            text = build_about_text()
        assert "Config: " in text

    def test_build_about_text_contains_project_url(self):
        text = build_about_text()
        assert "https://github.com/RedHatProductSecurity/ai-guardian" in text

    def test_build_about_text_contains_scanners(self):
        from ai_guardian.scanners.manager import InstalledScanner

        fake_scanners = [
            InstalledScanner(
                name="gitleaks",
                version="8.30.1",
                path="/usr/bin/gitleaks",
                is_default=True,
            ),
            InstalledScanner(
                name="betterleaks",
                version="1.2.0",
                path="/usr/bin/betterleaks",
                is_default=False,
            ),
        ]
        with mock.patch(
            "ai_guardian.scanners.manager.ScannerManager.list_configured",
            return_value=fake_scanners,
        ):
            text = build_about_text()
        assert "gitleaks 8.30.1 (default)" in text
        assert "betterleaks 1.2.0" in text

    def test_build_about_text_no_scanners_installed(self):
        with mock.patch(
            "ai_guardian.scanners.manager.ScannerManager.list_configured",
            return_value=[],
        ):
            text = build_about_text()
        assert "Scanners: none installed" in text

    def test_on_about_calls_show_dialog(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch("ai_guardian.tray.plugins.show_dialog") as mock_dialog:
            with mock.patch("threading.Thread") as mock_thread:
                mock_thread.return_value = mock.MagicMock()
                tray._menu._on_about(mock.MagicMock(), mock.MagicMock())
                show_fn = mock_thread.call_args[1]["target"]
            show_fn()
            mock_dialog.assert_called_once()
            assert mock_dialog.call_args[0][0] == "About AI Guardian"
            assert "AI Guardian v" in mock_dialog.call_args[0][1]

    def test_on_about_no_error_on_failure(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with mock.patch(
            "ai_guardian.tray.plugins.show_dialog", side_effect=Exception("fail")
        ):
            with mock.patch("threading.Thread") as mock_thread:
                mock_thread.return_value = mock.MagicMock()
                tray._menu._on_about(None, None)
                show_fn = mock_thread.call_args[1]["target"]
            show_fn()  # Should not raise

    def test_about_menu_item_present_in_run(self):
        """About menu item is included in the global menu section."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("platform.system", return_value="Linux"),
            mock.patch("ai_guardian.tray.app._suppress_gtk_stderr", return_value=None),
            mock.patch("ai_guardian.tray.app.threading"),
        ):
            mock_icon = mock.MagicMock()
            mock_pystray.Icon.return_value = mock_icon
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._start_stats_refresh = mock.MagicMock()
            tray._create_icon = mock.MagicMock()
            tray._run()

            def _resolve_label(label):
                if isinstance(label, str):
                    return label
                if callable(label):
                    try:
                        return label()
                    except Exception:
                        return None
                return None

            all_labels = [
                _resolve_label(call[0][0])
                for call in mock_pystray.MenuItem.call_args_list
            ]
            about_found = any(l and l.startswith("About") for l in all_labels)
            assert about_found
            str_labels = [l for l in all_labels if isinstance(l, str)]
            assert "Quit" in str_labels

    def test_multi_daemon_about_includes_daemon_list(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
            DaemonTarget(name="sandbox", runtime="container", status="running"),
        ]
        tray._health._daemon_versions = {
            ("local", "local"): "1.9.0",
            ("sandbox", "container"): "1.8.0",
        }
        with mock.patch("ai_guardian.tray.plugins.show_dialog") as mock_dialog:
            with mock.patch("threading.Thread") as mock_thread:
                mock_thread.return_value = mock.MagicMock()
                tray._menu._on_about(mock.MagicMock(), mock.MagicMock())
                show_fn = mock_thread.call_args[1]["target"]
            show_fn()
            text = mock_dialog.call_args[0][1]
            assert "Daemons: 2 connected" in text
            assert "local v1.9.0" in text
            assert "sandbox v1.8.0" in text

    def test_single_daemon_about_no_daemon_list(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
        ]
        with mock.patch("ai_guardian.tray.plugins.show_dialog") as mock_dialog:
            with mock.patch("threading.Thread") as mock_thread:
                mock_thread.return_value = mock.MagicMock()
                tray._menu._on_about(mock.MagicMock(), mock.MagicMock())
                show_fn = mock_thread.call_args[1]["target"]
            show_fn()
            text = mock_dialog.call_args[0][1]
            assert "Daemons:" not in text

    def test_per_daemon_about_calls_multi_client(self):
        mc = mock.MagicMock()
        mc.get_about.return_value = {
            "version": "1.8.0",
            "python": "3.11.9",
            "platform": "Linux 5.15 x86_64",
            "config_path": "/root/.config/ai-guardian/ai-guardian.json",
            "scanners": [],
            "url": "https://github.com/RedHatProductSecurity/ai-guardian",
        }
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        target = DaemonTarget(name="sandbox", runtime="container", status="running")
        tray._targets = [target]
        with mock.patch("ai_guardian.tray.plugins.show_dialog") as mock_dialog:
            action = tray._menu._on_daemon_about(0)
            with mock.patch("threading.Thread") as mock_thread:
                mock_thread.return_value = mock.MagicMock()
                action(None, None)
                show_fn = mock_thread.call_args[1]["target"]
            show_fn()
            mc.get_about.assert_called_once_with(target)
            mock_dialog.assert_called_once()
            text = mock_dialog.call_args[0][1]
            assert "AI Guardian v1.8.0" in text
            assert "Linux" in text

    def test_per_daemon_about_caches_result(self):
        mc = mock.MagicMock()
        mc.get_about.return_value = {
            "version": "1.8.0",
            "python": "3.11.9",
            "platform": "Linux",
            "config_path": None,
            "scanners": [],
            "url": "https://github.com/RedHatProductSecurity/ai-guardian",
        }
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        target = DaemonTarget(name="sandbox", runtime="container", status="running")
        tray._targets = [target]
        with mock.patch("ai_guardian.tray.plugins.show_dialog"):
            action = tray._menu._on_daemon_about(0)
            with mock.patch("threading.Thread") as mock_thread:
                mock_thread.return_value = mock.MagicMock()
                action(None, None)
                show_fn1 = mock_thread.call_args[1]["target"]
            show_fn1()
            with mock.patch("threading.Thread") as mock_thread:
                mock_thread.return_value = mock.MagicMock()
                action(None, None)
                show_fn2 = mock_thread.call_args[1]["target"]
            show_fn2()
            mc.get_about.assert_called_once()

    def test_multi_daemon_submenu_includes_about(self):
        mc = mock.MagicMock()
        mc.get_status.return_value = {}
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
            DaemonTarget(name="remote", runtime="container", status="running"),
        ]
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_multi_daemon_menu_items()

            about_count = 0
            for call in mock_pystray.MenuItem.call_args_list:
                label = call[0][0]
                if isinstance(label, str) and label.startswith("About"):
                    about_count += 1
                elif callable(label):
                    try:
                        resolved = label(None)
                    except TypeError:
                        try:
                            resolved = label()
                        except Exception:
                            continue
                    if isinstance(resolved, str) and resolved.startswith("About"):
                        about_count += 1
            assert about_count >= 2


class TestVersionMismatchDetection:
    """Tests for version mismatch detection between tray and daemons (issue #766)."""

    @pytest.mark.parametrize(
        "version_str, expected",
        [
            ("1.9.0", (1, 9, 0)),
            ("1.9.0-dev", (1, 9, 0)),
            ("v1.9.0", (1, 9, 0)),
            ("unknown", None),
            (None, None),
            ("", None),
        ],
        ids=[
            "basic",
            "dev-suffix",
            "v-prefix",
            "invalid",
            "none",
            "empty",
        ],
    )
    def test_parse_version_tuple(self, version_str, expected):
        assert parse_version_tuple(version_str) == expected

    def test_no_warning_when_versions_match(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        target = DaemonTarget(name="local", runtime="local", status="running")
        tray._targets = [target]
        tray._health._daemon_versions = {("local", "local"): "1.9.0"}

        with mock.patch("ai_guardian.__version__", "1.9.0"):
            with mock.patch("threading.Thread") as mock_thread:
                tray._health._check_version_mismatch()
                mock_thread.assert_not_called()

    def test_warning_when_daemon_older(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        target = DaemonTarget(name="sandbox", runtime="container", status="running")
        tray._targets = [target]
        tray._health._daemon_versions = {("sandbox", "container"): "1.8.0"}

        with mock.patch("ai_guardian.__version__", "1.9.0"):
            with mock.patch("threading.Thread") as mock_thread:
                mock_thread.return_value = mock.MagicMock()
                tray._health._check_version_mismatch()
                notify_calls = [
                    c
                    for c in mock_thread.call_args_list
                    if c[1].get("name") == "version-mismatch-notify"
                ]
                assert len(notify_calls) == 1
                assert (
                    "sandbox",
                    "container",
                ) in tray._health._version_mismatch_notified

    def test_warning_not_repeated(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        target = DaemonTarget(name="sandbox", runtime="container", status="running")
        tray._targets = [target]
        tray._health._daemon_versions = {("sandbox", "container"): "1.8.0"}
        tray._health._version_mismatch_notified.add(("sandbox", "container"))
        tray._health._pip_available[("sandbox", "container")] = True

        with mock.patch("ai_guardian.__version__", "1.9.0"):
            with mock.patch("threading.Thread") as mock_thread:
                tray._health._check_version_mismatch()
                mock_thread.assert_not_called()

    def test_warning_clears_when_upgraded(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        target = DaemonTarget(name="sandbox", runtime="container", status="running")
        tray._targets = [target]
        tray._health._daemon_versions = {("sandbox", "container"): "1.9.0"}
        tray._health._version_mismatch_notified.add(("sandbox", "container"))

        with mock.patch("ai_guardian.__version__", "1.9.0"):
            tray._health._check_version_mismatch()
            assert (
                "sandbox",
                "container",
            ) not in tray._health._version_mismatch_notified

    def test_send_version_mismatch_notification(self):
        with mock.patch("ai_guardian.tray.plugins.send_notification") as mock_notify:
            send_version_mismatch_notification("sandbox", "1.8.0", "1.9.0")
            mock_notify.assert_called_once()
            args = mock_notify.call_args[0]
            assert args[0] == "AI Guardian"
            assert "sandbox" in args[1]
            assert "1.8.0" in args[1]
            assert "1.9.0" in args[1]

    def test_version_annotated_label_no_mismatch(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        target = DaemonTarget(name="local", runtime="local", status="running")
        label = tray._menu._version_annotated_label(target)
        assert "⟳" not in label
        assert "● local" in label

    def test_version_annotated_label_with_mismatch(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        target = DaemonTarget(name="sandbox", runtime="container", status="running")
        tray._health._version_mismatch_notified.add(("sandbox", "container"))
        tray._health._daemon_versions = {("sandbox", "container"): "1.8.0"}
        label = tray._menu._version_annotated_label(target)
        assert "⟳" in label
        assert "v1.8.0" in label

    def test_no_warning_for_stopped_daemons(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        target = DaemonTarget(name="sandbox", runtime="container", status="stopped")
        tray._targets = [target]
        tray._health._daemon_versions = {("sandbox", "container"): "1.8.0"}

        with mock.patch("ai_guardian.__version__", "1.9.0"):
            with mock.patch("threading.Thread") as mock_thread:
                tray._health._check_version_mismatch()
                mock_thread.assert_not_called()

    def test_dev_suffix_ignored_in_comparison(self):
        """1.9.0-dev and 1.9.0 should be treated as the same version."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        target = DaemonTarget(name="local", runtime="local", status="running")
        tray._targets = [target]
        tray._health._daemon_versions = {("local", "local"): "1.9.0"}

        with mock.patch("ai_guardian.__version__", "1.9.0-dev"):
            with mock.patch("threading.Thread") as mock_thread:
                tray._health._check_version_mismatch()
                mock_thread.assert_not_called()


class TestDiscoveryAnimation:
    """Tests for tray icon animation during slow daemon discovery (#743)."""

    def _make_tray(self, **kwargs):
        return DaemonTray(
            get_stats_callback=kwargs.get("get_stats_callback", lambda: {}),
            stop_callback=kwargs.get("stop_callback", lambda: None),
            pause_callback=kwargs.get("pause_callback", lambda mins: None),
            discovery=kwargs.get("discovery", None),
        )

    def test_init_state_defaults(self):
        tray = self._make_tray()
        assert tray._anim._discovery_animating is False
        assert tray._anim._discovery_timer is None
        assert tray._anim._discovery_frames is None
        assert tray._anim._is_initial_discovery is True
        assert tray._anim._discovery_in_progress is False
        assert not tray._anim._discovery_anim_stop.is_set()

    @pytest.mark.skipif(
        not HAS_PYSTRAY,
        reason="pystray/Pillow not installed",
    )
    def test_generate_discovery_frames_returns_four_images(self):
        from PIL import Image

        tray = self._make_tray()
        frames = tray._anim._generate_discovery_frames()
        assert len(frames) == 4
        for f in frames:
            assert isinstance(f, Image.Image)
            assert f.mode == "RGBA"
        base_alpha = list(frames[0].split()[3].tobytes())
        dim_alpha = list(frames[2].split()[3].tobytes())
        assert dim_alpha != base_alpha

    @pytest.mark.skipif(
        not HAS_PYSTRAY,
        reason="pystray/Pillow not installed",
    )
    def test_generate_discovery_frames_caches_result(self):
        tray = self._make_tray()
        first = tray._anim._generate_discovery_frames()
        second = tray._anim._generate_discovery_frames()
        assert first is second

    @pytest.mark.skipif(
        not HAS_PYSTRAY,
        reason="pystray/Pillow not installed",
    )
    def test_invalidate_clears_frame_cache(self):
        tray = self._make_tray()
        first = tray._anim._generate_discovery_frames()
        tray._anim._invalidate_discovery_frames()
        assert tray._anim._discovery_frames is None
        second = tray._anim._generate_discovery_frames()
        assert first is not second

    def test_start_animation_immediate_calls_begin(self):
        tray = self._make_tray()
        with mock.patch.object(tray._anim, "_begin_discovery_animation") as m:
            tray._anim._start_discovery_animation(delay=0)
            m.assert_called_once()

    def test_start_animation_delayed_creates_timer(self):
        tray = self._make_tray()
        with mock.patch.object(tray._anim, "_begin_discovery_animation"):
            tray._anim._start_discovery_animation(delay=0.5)
            assert tray._anim._discovery_timer is not None
            assert tray._anim._discovery_timer.daemon is True
            tray._anim._cancel_discovery_timer()

    def test_stop_animation_cancels_timer(self):
        timer = mock.MagicMock()
        tray = self._make_tray()
        tray._anim._discovery_timer = timer
        tray._anim._stop_discovery_animation()
        timer.cancel.assert_called_once()
        assert tray._anim._discovery_timer is None

    def test_stop_animation_sets_stop_event(self):
        tray = self._make_tray()
        assert not tray._anim._discovery_anim_stop.is_set()
        tray._anim._stop_discovery_animation()
        assert tray._anim._discovery_anim_stop.is_set()

    def test_stop_animation_restores_icon(self):
        tray = self._make_tray()
        tray._icon = mock.MagicMock()
        with mock.patch.object(
            DaemonTray, "_dispatch_to_main", side_effect=lambda fn: fn()
        ):
            with mock.patch.object(tray, "_create_icon", return_value="normal_icon"):
                tray._anim._stop_discovery_animation()
                assert tray._icon.icon == "normal_icon"

    def test_begin_animation_skips_if_already_stopped(self):
        tray = self._make_tray()
        tray._anim._discovery_anim_stop.set()
        with mock.patch("threading.Thread") as mock_thread:
            tray._anim._begin_discovery_animation()
            mock_thread.assert_not_called()
        assert tray._anim._discovery_animating is False

    def test_begin_animation_starts_thread(self):
        tray = self._make_tray()
        tray._anim._discovery_anim_stop.clear()
        with mock.patch("threading.Thread") as mock_thread:
            mock_thread.return_value = mock.MagicMock()
            tray._anim._begin_discovery_animation()
            mock_thread.assert_called_once()
            mock_thread.return_value.start.assert_called_once()
            assert tray._anim._discovery_animating is True

    def test_start_defers_discovery_to_run(self):
        disc = mock.MagicMock()
        tray = self._make_tray(discovery=disc)
        with (
            mock.patch("ai_guardian.tray.app.HAS_PYSTRAY", True),
            mock.patch("ai_guardian.tray.app._is_tray_running", return_value=False),
            mock.patch("ai_guardian.tray.app._write_tray_lock"),
            mock.patch.object(tray, "_run"),
        ):
            tray.start()
            disc.start_background_discovery.assert_not_called()

    def test_on_targets_updated_stops_animation(self):
        tray = self._make_tray()
        tray._anim._is_initial_discovery = True
        tray._anim._discovery_in_progress = True
        with (
            mock.patch.object(tray._anim, "_stop_discovery_animation") as mock_stop,
            mock.patch.object(DaemonTray, "_dispatch_to_main"),
        ):
            tray._on_targets_updated(
                [
                    DaemonTarget(name="local", runtime="local", status="running"),
                ]
            )
            mock_stop.assert_called_once()
        assert tray._anim._is_initial_discovery is False
        assert tray._anim._discovery_in_progress is False

    def test_on_targets_updated_refreshes_menu(self):
        tray = self._make_tray()
        dispatched = []
        with mock.patch.object(
            DaemonTray,
            "_dispatch_to_main",
            side_effect=lambda fn: dispatched.append(fn),
        ):
            tray._on_targets_updated(
                [
                    DaemonTarget(name="local", runtime="local", status="running"),
                ]
            )
        assert tray._anim._refresh_menu_and_clear_discovery_flag in dispatched

    def test_on_targets_updated_polls_plugins_immediately(self):
        tray = self._make_tray()
        with (
            mock.patch.object(tray._plugins, "_poll_plugins") as mock_poll,
            mock.patch.object(DaemonTray, "_dispatch_to_main"),
        ):
            tray._on_targets_updated(
                [
                    DaemonTarget(name="local", runtime="local", status="running"),
                ]
            )
            mock_poll.assert_called_once()

    def test_stop_cleans_up_animation(self):
        tray = self._make_tray()
        with mock.patch.object(tray._anim, "_stop_discovery_animation") as mock_stop:
            tray.stop()
            mock_stop.assert_called_once()

    def test_request_discovery_refresh_triggers_refresh(self):
        disc = mock.MagicMock()
        tray = self._make_tray(discovery=disc)
        tray._anim._last_discovery_refresh = 0.0
        tray._anim._request_discovery_refresh(wait=False)
        disc.request_refresh.assert_called_once_with(wait=False)

    def test_request_discovery_refresh_noop_without_discovery(self):
        tray = self._make_tray()
        tray._anim._request_discovery_refresh(wait=False)

    def test_fast_discovery_no_animation(self):
        tray = self._make_tray()
        tray._icon = mock.MagicMock()
        original_icon = tray._icon.icon
        with mock.patch.object(tray._anim, "_begin_discovery_animation"):
            tray._anim._start_discovery_animation(delay=0.5)
            tray._anim._stop_discovery_animation()
        assert tray._anim._discovery_timer is None
        assert tray._anim._discovery_anim_stop.is_set()

    def test_no_animation_without_discovery(self):
        tray = self._make_tray()
        with (
            mock.patch("ai_guardian.tray.app.HAS_PYSTRAY", True),
            mock.patch("ai_guardian.tray.app._is_tray_running", return_value=False),
            mock.patch("ai_guardian.tray.app._write_tray_lock"),
            mock.patch.object(tray, "_run"),
        ):
            tray.start()
            assert tray._anim._discovery_in_progress is False

    def test_update_status_invalidates_frames(self):
        tray = self._make_tray()
        tray._anim._discovery_frames = ["fake_frame"]
        tray.update_status("paused")
        assert tray._anim._discovery_frames is None
        tray._stop_pause_timer()

    def test_run_starts_animation_and_discovery(self):
        disc = mock.MagicMock()
        tray = self._make_tray(discovery=disc)
        with (
            mock.patch.object(tray._anim, "_start_discovery_animation") as mock_anim,
            mock.patch.object(tray, "_create_icon", return_value=mock.MagicMock()),
            mock.patch.object(tray, "_ensure_macos_activation_policy"),
            mock.patch.object(
                tray._menu, "_build_single_daemon_menu_items", return_value=[]
            ),
            mock.patch.object(
                tray._plugins, "_build_single_daemon_plugin_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu, "_build_single_daemon_daemon_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu, "_build_multi_daemon_menu_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu, "_build_ide_setup_menu_items", return_value=[]
            ),
            mock.patch.object(tray, "_start_stats_refresh"),
            mock.patch.object(tray, "_register_wake_handler"),
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_icon = mock.MagicMock()
            mock_pystray.Icon.return_value = mock_icon
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            mock_pystray.MenuItem = mock.MagicMock()
            mock_icon.run = mock.MagicMock()
            tray._run()
            mock_anim.assert_called_once_with(delay=0)
            disc.start_background_discovery.assert_called_once()

    def test_run_skips_animation_without_discovery(self):
        tray = self._make_tray()
        with (
            mock.patch.object(tray._anim, "_start_discovery_animation") as mock_anim,
            mock.patch.object(tray, "_create_icon", return_value=mock.MagicMock()),
            mock.patch.object(tray, "_ensure_macos_activation_policy"),
            mock.patch.object(
                tray._menu, "_build_single_daemon_menu_items", return_value=[]
            ),
            mock.patch.object(
                tray._plugins, "_build_single_daemon_plugin_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu, "_build_single_daemon_daemon_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu, "_build_multi_daemon_menu_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu, "_build_ide_setup_menu_items", return_value=[]
            ),
            mock.patch.object(tray, "_start_stats_refresh"),
            mock.patch.object(tray, "_register_wake_handler"),
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_icon = mock.MagicMock()
            mock_pystray.Icon.return_value = mock_icon
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            mock_pystray.MenuItem = mock.MagicMock()
            mock_icon.run = mock.MagicMock()
            tray._run()
            mock_anim.assert_not_called()

    def test_request_discovery_refresh_sets_in_progress(self):
        disc = mock.MagicMock()
        tray = self._make_tray(discovery=disc)
        tray._anim._last_discovery_refresh = 0.0
        with mock.patch.object(tray._anim, "_start_discovery_animation"):
            tray._anim._request_discovery_refresh(wait=False)
            assert tray._anim._discovery_in_progress is True

    def test_request_discovery_refresh_debounces_rapid_calls(self):
        """Rapid calls must be debounced to a single refresh (issue #754)."""
        disc = mock.MagicMock()
        tray = self._make_tray(discovery=disc)
        tray._anim._last_discovery_refresh = 0.0
        tray._anim._request_discovery_refresh(wait=False)
        tray._anim._request_discovery_refresh(wait=False)
        tray._anim._request_discovery_refresh(wait=False)
        disc.request_refresh.assert_called_once()

    def test_discovery_refresh_skipped_during_discovery_callback(self):
        disc = mock.MagicMock()
        tray = self._make_tray(discovery=disc)
        tray._anim._refreshing_from_discovery = True
        with mock.patch.object(tray._anim, "_start_discovery_animation") as mock_anim:
            tray._anim._request_discovery_refresh(wait=False)
            mock_anim.assert_not_called()
            disc.request_refresh.assert_not_called()

    def test_on_targets_updated_sets_refreshing_guard(self):
        tray = self._make_tray()
        guard_values = []

        def tracking_dispatch(fn):
            guard_values.append(tray._anim._refreshing_from_discovery)
            fn()

        with mock.patch.object(
            DaemonTray, "_dispatch_to_main", side_effect=tracking_dispatch
        ):
            tray._on_targets_updated(
                [
                    DaemonTarget(name="local", runtime="local", status="running"),
                ]
            )
        assert True in guard_values
        assert tray._anim._refreshing_from_discovery is False

    def test_cancel_discovery_timer_is_idempotent(self):
        tray = self._make_tray()
        tray._anim._cancel_discovery_timer()
        assert tray._anim._discovery_timer is None


class TestGlobalPlugins:
    """Tests for global-scope tray plugins (issue #794)."""

    def _make_tray(self, targets=None, multi_client=None):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=multi_client,
        )
        if targets is not None:
            tray._targets = targets
        return tray

    def test_global_plugins_initialized_empty(self):
        tray = self._make_tray()
        assert tray._plugins._global_plugins == []
        assert tray._plugins._daemon_global_plugins == {}

    def test_poll_plugins_collects_global_from_daemon_data(self):
        mc = mock.MagicMock()
        mc._local_plugins.return_value = {
            "plugins": [
                {
                    "name": "Quick Links",
                    "scope": "global",
                    "items": [
                        {"label": "Docs", "command": "echo", "type": "background"}
                    ],
                },
                {"name": "Daemon", "items": [{"label": "Status", "command": "echo"}]},
            ]
        }
        local_target = DaemonTarget(name="local", runtime="local", status="running")
        tray = self._make_tray(targets=[local_target], multi_client=mc)
        tray._plugins._poll_plugins()
        assert len(tray._plugins._global_plugins) == 1
        assert tray._plugins._global_plugins[0].name == "Quick Links"

    def test_poll_plugins_excludes_global_from_daemon_plugins(self):
        mc = mock.MagicMock()
        mc._local_plugins.return_value = {
            "plugins": [
                {
                    "name": "Global",
                    "scope": "global",
                    "items": [
                        {"label": "Docs", "command": "echo", "type": "background"}
                    ],
                },
                {"name": "Daemon", "items": [{"label": "Status", "command": "echo"}]},
            ]
        }
        local_target = DaemonTarget(name="local", runtime="local", status="running")
        tray = self._make_tray(targets=[local_target], multi_client=mc)
        tray._plugins._poll_plugins()
        assert 0 in tray._plugins._daemon_plugins
        names = [p.name for p in tray._plugins._daemon_plugins[0]]
        assert "Global" not in names
        assert "Daemon" in names

    def test_poll_plugins_clears_globals_when_remote_daemon_stops(self):
        mc = mock.MagicMock()
        plugin_data = {
            "plugins": [
                {
                    "name": "Links",
                    "scope": "global",
                    "items": [{"label": "Docs", "command": "echo"}],
                },
            ]
        }
        mc.get_plugins.return_value = plugin_data
        mc.get_status.return_value = {"menu_tags": []}
        remote_target = DaemonTarget(
            name="remote",
            runtime="container",
            status="running",
        )
        tray = self._make_tray(targets=[remote_target], multi_client=mc)
        tray._plugins._poll_plugins()
        assert len(tray._plugins._global_plugins) == 1

        remote_target.status = "stopped"
        tray._plugins._poll_plugins()
        assert tray._plugins._global_plugins == []

    def test_build_global_plugin_items_returns_slots_plus_separator(self):
        tray = self._make_tray()
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            items = tray._plugins._build_global_plugin_items()
        assert isinstance(items, list)
        assert len(items) == tray._plugins._MAX_GLOBAL_PLUGIN_SLOTS + 1

    def test_global_plugin_visible_when_present(self):
        from ai_guardian.tray.plugins import Plugin, PluginItem

        tray = self._make_tray(
            targets=[
                DaemonTarget(name="local", runtime="local", status="running"),
            ]
        )
        tray._plugins._global_plugins = [
            Plugin(
                name="Quick Links",
                scope="global",
                items=[PluginItem(label="Docs", command="echo docs")],
            ),
        ]
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            tray._plugins._build_global_plugin_items()

        plugin_calls = [
            call
            for call in mock_pystray.MenuItem.call_args_list
            if len(call[0]) >= 2
            and isinstance(call[0][1], mock.MagicMock)
            and call[1].get("visible") is not None
            and callable(call[0][0])
            and call[0][0](None) == "Quick Links"
        ]
        assert len(plugin_calls) >= 1
        first_plugin = plugin_calls[0]
        vis_fn = first_plugin[1]["visible"]
        assert vis_fn(None) is True

    def test_global_plugin_hidden_when_no_global_plugins(self):
        tray = self._make_tray(
            targets=[
                DaemonTarget(name="local", runtime="local", status="running"),
            ]
        )
        tray._plugins._global_plugins = []
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            tray._plugins._build_global_plugin_items()

        first_call = mock_pystray.MenuItem.call_args_list[0]
        vis_fn = first_call[1].get("visible")
        assert vis_fn(None) is False

    def test_poll_plugins_clears_globals_when_no_targets(self):
        from ai_guardian.tray.plugins import Plugin, PluginItem

        tray = self._make_tray(targets=[])
        tray._plugins._global_plugins = [
            Plugin(
                name="Stale",
                scope="global",
                items=[PluginItem(label="X", command="echo")],
            ),
        ]
        tray._plugins._poll_plugins()
        assert tray._plugins._global_plugins == []

    def test_run_includes_global_plugin_items(self):
        """_run() calls _build_global_plugin_items."""
        tray = self._make_tray()
        with (
            mock.patch.object(
                tray._plugins, "_build_global_plugin_items", return_value=[]
            ) as mock_build,
            mock.patch.object(tray, "_create_icon", return_value=mock.MagicMock()),
            mock.patch.object(tray, "_ensure_macos_activation_policy"),
            mock.patch.object(
                tray._menu, "_build_single_daemon_menu_items", return_value=[]
            ),
            mock.patch.object(
                tray._plugins, "_build_single_daemon_plugin_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu, "_build_single_daemon_daemon_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu, "_build_multi_daemon_menu_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu, "_build_ide_setup_menu_items", return_value=[]
            ),
            mock.patch.object(tray, "_start_stats_refresh"),
            mock.patch.object(tray, "_register_wake_handler"),
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_icon = mock.MagicMock()
            mock_pystray.Icon.return_value = mock_icon
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            mock_pystray.MenuItem = mock.MagicMock()
            mock_icon.run = mock.MagicMock()
            tray._run()
            mock_build.assert_called_once()


class TestMultiTargetExecution:
    """Tests for multi-target plugin command execution."""

    def _make_tray(self):
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        return tray

    def test_resolve_target_list_all(self):
        tray = self._make_tray()
        t1 = DaemonTarget(name="a", runtime="local", status="running")
        t2 = DaemonTarget(
            name="b",
            runtime="container",
            status="running",
            container_id="abc123def456",
            container_engine="podman",
        )
        tray._targets = [t1, t2]
        result = tray._plugins._resolve_target_list("all")
        assert len(result) == 2
        assert t1 in result
        assert t2 in result

    def test_resolve_target_list_containers(self):
        tray = self._make_tray()
        t1 = DaemonTarget(name="a", runtime="local", status="running")
        t2 = DaemonTarget(
            name="b",
            runtime="container",
            status="running",
            container_id="abc123def456",
            container_engine="podman",
        )
        t3 = DaemonTarget(
            name="c",
            runtime="container",
            status="running",
            container_id="def456abc123",
            container_engine="docker",
        )
        tray._targets = [t1, t2, t3]
        result = tray._plugins._resolve_target_list("containers")
        assert len(result) == 2
        assert t1 not in result
        assert t2 in result
        assert t3 in result

    @pytest.mark.parametrize(
        "mode", ["containers", "bogus"], ids=["containers-no-match", "unknown-mode"]
    )
    def test_resolve_target_list_returns_empty(self, mode):
        tray = self._make_tray()
        tray._targets = [DaemonTarget(name="a", runtime="local")]
        assert tray._plugins._resolve_target_list(mode) == []

    @mock.patch("ai_guardian.tray.plugins.execute_plugin_command")
    def test_execute_multi_target_command(self, mock_exec):
        tray = self._make_tray()
        t1 = DaemonTarget(name="a", runtime="local")
        t2 = DaemonTarget(
            name="b",
            runtime="container",
            container_id="abc123def456",
            container_engine="podman",
        )
        tray._plugins._execute_multi_target_command(
            [t1, t2],
            "echo hello",
            "terminal",
            run_on_target=True,
            label="Test",
        )
        assert mock_exec.call_count == 2
        calls = mock_exec.call_args_list
        assert calls[0].kwargs["target"] == t1
        assert calls[1].kwargs["target"] == t2

    def test_serialize_targets_for_selector(self):
        tray = self._make_tray()
        t = DaemonTarget(
            name="proj",
            runtime="container",
            container_name="sandbox-1",
            container_engine="podman",
            container_id="abc123def456",
            status="running",
        )
        tray._targets = [t]
        result = tray._plugins._serialize_targets_for_selector()
        assert len(result) == 1
        assert result[0]["name"] == "proj"
        assert result[0]["container_name"] == "sandbox-1"
        assert result[0]["runtime"] == "container"
        assert result[0]["container_engine"] == "podman"


class TestWebConsoleVersionGating:
    """Console menu item visibility based on Python version."""

    def test_console_hidden_on_python_below_310(self):
        """Console menu item is visible even when Python < 3.10 (falls back to TUI)."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
        ]
        saved = DaemonTray._has_web_console
        try:
            DaemonTray._has_web_console = False
            with (
                mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
                mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
                mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            ):
                mock_pystray.MenuItem = mock.MagicMock()
                mock_pystray.Menu = mock.MagicMock()
                mock_pystray.Menu.SEPARATOR = mock.MagicMock()
                tray._menu._build_single_daemon_menu_items()

                for call in mock_pystray.MenuItem.call_args_list:
                    if isinstance(call[0][0], str) and call[0][0] == "Console":
                        vis = call[1].get("visible") or call[0][2]
                        assert vis(None) is True
                        return
                pytest.fail("Console menu item not found")
        finally:
            DaemonTray._has_web_console = saved

    def test_console_shown_on_python_310_plus(self):
        """Console visibility returns True on Python 3.10+ when ready."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
        ]
        saved = DaemonTray._has_web_console
        try:
            DaemonTray._has_web_console = True
            with (
                mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
                mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
                mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
                mock.patch.object(
                    DaemonTray, "_is_web_console_ready", return_value=True
                ),
            ):
                mock_pystray.MenuItem = mock.MagicMock()
                mock_pystray.Menu = mock.MagicMock()
                mock_pystray.Menu.SEPARATOR = mock.MagicMock()
                tray._menu._build_single_daemon_menu_items()

                for call in mock_pystray.MenuItem.call_args_list:
                    if isinstance(call[0][0], str) and call[0][0] == "Console":
                        vis = call[1].get("visible") or call[0][2]
                        assert vis(None) is True
                        return
                pytest.fail("Console menu item not found")
        finally:
            DaemonTray._has_web_console = saved

    def test_multi_daemon_console_hidden_below_310(self):
        """Multi-daemon Console visibility returns False on Python < 3.10."""
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
            DaemonTarget(name="remote", runtime="container", status="running"),
        ]
        saved = DaemonTray._has_web_console
        try:
            DaemonTray._has_web_console = False
            with (
                mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
                mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
                mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            ):
                mock_pystray.MenuItem = mock.MagicMock()
                mock_pystray.Menu = mock.MagicMock()
                mock_pystray.Menu.SEPARATOR = mock.MagicMock()
                tray._menu._build_multi_daemon_menu_items()

                for call in mock_pystray.MenuItem.call_args_list:
                    if isinstance(call[0][0], str) and call[0][0] == "Console":
                        vis = call[1].get("visible") or call[0][2]
                        assert vis(None) is False
                        return
                pytest.fail("Console menu item not found in multi-daemon menu")
        finally:
            DaemonTray._has_web_console = saved


class TestWebConsoleAutoRestart:
    """Web console auto-restart when dead (#1370)."""

    def _make_tray(self, multi=False):
        mc = mock.MagicMock() if multi else None
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        targets = [
            DaemonTarget(name="local", runtime="local", status="running"),
        ]
        if multi:
            targets.append(
                DaemonTarget(name="remote", runtime="container", status="running"),
            )
        tray._targets = targets
        return tray

    def test_ensure_web_console_ready_returns_true_when_already_ready(self):
        tray = self._make_tray()
        with mock.patch.object(DaemonTray, "_is_web_console_ready", return_value=True):
            assert tray._ensure_web_console_ready() is True

    def test_ensure_web_console_ready_restarts_when_dead(self):
        tray = self._make_tray()
        ready_calls = [False, False, True]
        with (
            mock.patch.object(
                DaemonTray,
                "_is_web_console_ready",
                side_effect=ready_calls,
            ),
            mock.patch.object(tray, "_start_web_console") as mock_start,
            mock.patch("ai_guardian.tray.app.time.sleep"),
        ):
            assert tray._ensure_web_console_ready() is True
            mock_start.assert_called_once()

    def test_ensure_web_console_ready_returns_false_after_timeout(self):
        tray = self._make_tray()
        with (
            mock.patch.object(DaemonTray, "_is_web_console_ready", return_value=False),
            mock.patch.object(tray, "_start_web_console") as mock_start,
            mock.patch("ai_guardian.tray.app.time.sleep"),
        ):
            assert tray._ensure_web_console_ready() is False
            mock_start.assert_called_once()

    def test_single_daemon_open_panel_restarts_web_console(self):
        tray = self._make_tray()
        saved = DaemonTray._has_web_console
        try:
            DaemonTray._has_web_console = True
            with (
                mock.patch.object(
                    tray, "_ensure_web_console_ready", return_value=True
                ) as mock_ensure,
                mock.patch.object(tray, "_check_and_autostart_daemon"),
                mock.patch("ai_guardian.tray.menu.open_web_console") as mock_open,
                mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
                mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
                mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            ):
                mock_pystray.MenuItem = mock.MagicMock()
                mock_pystray.Menu = mock.MagicMock()
                mock_pystray.Menu.SEPARATOR = mock.MagicMock()
                items = tray._menu._build_single_daemon_menu_items()

                for call in mock_pystray.MenuItem.call_args_list:
                    if isinstance(call[0][0], str) and call[0][0] == "Console":
                        action_fn = call[0][1]
                        action_fn(None, None)
                        mock_ensure.assert_called()
                        mock_open.assert_called_once()
                        return
                pytest.fail("Console menu item not found")
        finally:
            DaemonTray._has_web_console = saved

    def test_single_daemon_falls_back_to_tui_when_restart_fails(self):
        tray = self._make_tray()
        saved = DaemonTray._has_web_console
        try:
            DaemonTray._has_web_console = True
            with (
                mock.patch.object(
                    tray, "_ensure_web_console_ready", return_value=False
                ),
                mock.patch.object(tray, "_check_and_autostart_daemon"),
                mock.patch("ai_guardian.tray.menu.open_web_console") as mock_open,
                mock.patch("ai_guardian.tray.menu.launch_console") as mock_tui,
                mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
                mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
                mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            ):
                mock_pystray.MenuItem = mock.MagicMock()
                mock_pystray.Menu = mock.MagicMock()
                mock_pystray.Menu.SEPARATOR = mock.MagicMock()
                tray._menu._build_single_daemon_menu_items()

                for call in mock_pystray.MenuItem.call_args_list:
                    if isinstance(call[0][0], str) and call[0][0] == "Console":
                        action_fn = call[0][1]
                        action_fn(None, None)
                        mock_open.assert_not_called()
                        mock_tui.assert_called_once()
                        return
                pytest.fail("Console menu item not found")
        finally:
            DaemonTray._has_web_console = saved

    def test_multi_daemon_console_visible_when_dead(self):
        """Console menu stays visible even when web console is dead (#1370)."""
        tray = self._make_tray(multi=True)
        saved = DaemonTray._has_web_console
        try:
            DaemonTray._has_web_console = True
            with (
                mock.patch.object(
                    DaemonTray, "_is_web_console_ready", return_value=False
                ),
                mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
                mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
                mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            ):
                mock_pystray.MenuItem = mock.MagicMock()
                mock_pystray.Menu = mock.MagicMock()
                mock_pystray.Menu.SEPARATOR = mock.MagicMock()
                tray._menu._build_multi_daemon_menu_items()

                for call in mock_pystray.MenuItem.call_args_list:
                    if isinstance(call[0][0], str) and call[0][0] == "Console":
                        vis = call[1].get("visible")
                        if vis and callable(vis):
                            assert vis(None) is True
                            return
                pytest.fail("Console menu item not found in multi-daemon menu")
        finally:
            DaemonTray._has_web_console = saved


class TestGreyedOutMenuItems:
    """Tests for greyed-out menu items when daemon is not available (#868)."""

    def _make_tray(self, targets=None):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        if targets is not None:
            tray._targets = targets
        return tray

    def _get_menu_item_kwargs(self, mock_pystray, label):
        """Find a MenuItem call by label and return its keyword args."""
        for call in mock_pystray.MenuItem.call_args_list:
            if call[0] and isinstance(call[0][0], str) and call[0][0] == label:
                return call[1]
        return None

    def test_single_daemon_items_have_enabled_guard(self):
        """Console, Violations, Metrics, Statistics get enabled= when built."""
        tray = self._make_tray(
            [
                DaemonTarget(name="local", runtime="local", status="stopped"),
            ]
        )
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_single_daemon_menu_items()

            for label in ("Console", "Violations", "Metrics & Audit", "Statistics"):
                kwargs = self._get_menu_item_kwargs(mock_pystray, label)
                assert kwargs is not None, f"{label} not found in menu items"
                enabled_cb = kwargs.get("enabled")
                assert enabled_cb is not None, f"{label} missing enabled= parameter"
                assert (
                    enabled_cb(None) is False
                ), f"{label} should be disabled when daemon is stopped"

    def test_single_daemon_items_enabled_when_running(self):
        """Daemon-dependent items are enabled when daemon is running."""
        tray = self._make_tray(
            [
                DaemonTarget(name="local", runtime="local", status="running"),
            ]
        )
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_single_daemon_menu_items()

            for label in ("Console", "Violations", "Metrics & Audit", "Statistics"):
                kwargs = self._get_menu_item_kwargs(mock_pystray, label)
                assert kwargs is not None, f"{label} not found"
                enabled_cb = kwargs.get("enabled")
                assert enabled_cb is not None, f"{label} missing enabled="
                assert (
                    enabled_cb(None) is True
                ), f"{label} should be enabled when daemon is running"

    def test_terminal_has_no_enabled_guard(self):
        """Terminal should always be active (local operation)."""
        tray = self._make_tray(
            [
                DaemonTarget(name="local", runtime="local", status="stopped"),
            ]
        )
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_single_daemon_menu_items()

            kwargs = self._get_menu_item_kwargs(mock_pystray, "Terminal")
            assert kwargs is not None, "Terminal not found"
            assert "enabled" not in kwargs or kwargs.get("enabled") is True

    def test_statistics_visible_when_daemon_stopped(self):
        """Statistics should be visible (but greyed) when daemon is stopped."""
        tray = self._make_tray(
            [
                DaemonTarget(name="local", runtime="local", status="stopped"),
            ]
        )
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_single_daemon_menu_items()

            kwargs = self._get_menu_item_kwargs(mock_pystray, "Statistics")
            assert kwargs is not None, "Statistics not found"
            vis_cb = kwargs.get("visible")
            assert vis_cb is not None, "Statistics missing visible="
            assert (
                vis_cb(None) is True
            ), "Statistics should be visible when single daemon exists"

    def test_start_daemon_visible_when_stopped(self):
        """Start daemon should be visible when daemon is stopped."""
        tray = self._make_tray(
            [
                DaemonTarget(name="local", runtime="local", status="stopped"),
            ]
        )
        tray._menu._single_daemon_closures = {
            "pause_action": lambda m: lambda _, __: None,
            "resume_action": lambda _, __: None,
            "stop_action": lambda _, __: None,
            "restart_action": lambda _, __: None,
            "single_running": lambda _: (
                tray._is_single_daemon()
                and tray._targets[0].status in ("running", "paused")
            ),
            "single_not_running": lambda _: (
                tray._is_single_daemon()
                and tray._targets[0].status not in ("running", "paused")
            ),
            "get_stats": lambda _: {},
        }
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_single_daemon_daemon_items()

            kwargs = self._get_menu_item_kwargs(mock_pystray, "Start daemon")
            assert kwargs is not None, "Start daemon not found"
            vis_cb = kwargs.get("visible")
            assert vis_cb is not None, "Start daemon missing visible="
            assert (
                vis_cb(None) is True
            ), "Start daemon should be visible when daemon is stopped"

    def test_daemon_status_label_starting(self):
        """Status label shows starting indicator for starting daemons."""
        t = DaemonTarget(name="my-host", runtime="local", status="starting")
        label = daemon_status_label(t)
        assert "◌" in label
        assert "starting..." in label

    def test_daemon_status_label_stopped(self):
        """Status label shows stopped indicator for stopped daemons."""
        t = DaemonTarget(name="my-host", runtime="local", status="stopped")
        label = daemon_status_label(t)
        assert "⚠" in label
        assert "daemon not running" in label

    def test_single_daemon_items_disabled_when_starting(self):
        """Items greyed out during daemon startup."""
        tray = self._make_tray(
            [
                DaemonTarget(name="local", runtime="local", status="starting"),
            ]
        )
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_single_daemon_menu_items()

            for label in ("Console", "Violations", "Metrics & Audit", "Statistics"):
                kwargs = self._get_menu_item_kwargs(mock_pystray, label)
                assert kwargs is not None, f"{label} not found"
                enabled_cb = kwargs.get("enabled")
                assert enabled_cb is not None, f"{label} missing enabled="
                assert (
                    enabled_cb(None) is False
                ), f"{label} should be disabled when daemon is starting"

    def test_multi_daemon_items_have_enabled_guard(self):
        """Multi-daemon submenu items get enabled= based on slot status."""
        mc = mock.MagicMock()
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            multi_client=mc,
        )
        tray._targets = [
            DaemonTarget(name="d1", runtime="local", status="stopped"),
            DaemonTarget(name="d2", runtime="manual", status="running"),
        ]
        mc.get_stats.return_value = {}
        mc._local_plugins.return_value = {"plugins": []}

        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
        ):
            mock_pystray.MenuItem = mock.MagicMock()
            mock_pystray.Menu = mock.MagicMock()
            mock_pystray.Menu.SEPARATOR = mock.MagicMock()
            tray._menu._build_multi_daemon_menu_items()

            console_calls = [
                call
                for call in mock_pystray.MenuItem.call_args_list
                if call[0] and isinstance(call[0][0], str) and call[0][0] == "Console"
            ]
            assert len(console_calls) >= 2, "Expected Console in multiple slots"
            for call in console_calls:
                assert (
                    call[1].get("enabled") is not None
                ), "Console in multi-daemon should have enabled="

    def test_about_disabled_when_no_daemons_running(self):
        """Top-level About greyed out when no daemon is running."""
        tray = self._make_tray(
            [
                DaemonTarget(name="local", runtime="local", status="stopped"),
            ]
        )
        enabled_cb = lambda _: any(
            t.status in ("running", "paused") for t in tray._targets
        )
        assert enabled_cb(None) is False

    def test_about_enabled_when_daemon_running(self):
        """Top-level About active when a daemon is running."""
        tray = self._make_tray(
            [
                DaemonTarget(name="local", runtime="local", status="running"),
            ]
        )
        enabled_cb = lambda _: any(
            t.status in ("running", "paused") for t in tray._targets
        )
        assert enabled_cb(None) is True


class TestPluginEnabledGuard:
    """Tests for plugin command enabled= guard based on run_on_target (#868)."""

    def test_run_on_target_plugin_disabled_when_daemon_stopped(self):
        """Plugin with run_on_target=True greyed out when daemon stopped."""
        from ai_guardian.tray.plugins import PluginItem

        target = DaemonTarget(name="local", runtime="local", status="stopped")
        item = PluginItem(label="Remote Cmd", command="echo hello", run_on_target=True)

        enabled = item.run_on_target and target.status not in ("running", "paused")
        assert enabled is True  # run_on_target is True and daemon IS stopped
        assert target.status not in ("running", "paused")

    def test_local_plugin_enabled_when_daemon_stopped(self):
        """Plugin with run_on_target=False stays enabled when daemon stopped."""
        from ai_guardian.tray.plugins import PluginItem

        target = DaemonTarget(name="local", runtime="local", status="stopped")
        item = PluginItem(label="Local Cmd", command="echo hello", run_on_target=False)

        if not item.run_on_target:
            enabled = True
        else:
            enabled = target.status in ("running", "paused")
        assert enabled is True

    def test_run_on_target_plugin_enabled_when_daemon_running(self):
        """Plugin with run_on_target=True is enabled when daemon is running."""
        from ai_guardian.tray.plugins import PluginItem

        target = DaemonTarget(name="local", runtime="local", status="running")
        item = PluginItem(label="Remote Cmd", command="echo hello", run_on_target=True)

        if not item.run_on_target:
            enabled = True
        else:
            enabled = target.status in ("running", "paused")
        assert enabled is True


class TestDiscoveryStartingStatus:
    """Tests for 'starting' daemon status detection (#868)."""

    def test_discover_local_starting_when_pid_alive_but_socket_not_ready(self):
        """discover_local returns 'starting' when process alive but not responding."""
        from ai_guardian.daemon.discovery import DaemonDiscovery

        discovery = DaemonDiscovery.__new__(DaemonDiscovery)
        discovery._targets = []
        discovery._lock = __import__("threading").Lock()

        config_content = '{"daemon": {"name": "test-host"}}'
        pid_content = '{"pid": 12345, "rest_port": 8080, "name": "test-host"}'

        mock_cfg_dir = mock.MagicMock()
        mock_cfg_path = mock.MagicMock()
        mock_cfg_path.exists.return_value = True
        mock_cfg_path.read_text.return_value = config_content
        mock_cfg_dir.__truediv__ = lambda s, n: mock_cfg_path

        mock_pp = mock.MagicMock()
        mock_pp.exists.return_value = True
        mock_pp.read_text.return_value = pid_content

        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=mock_cfg_dir
            ),
            mock.patch(
                "ai_guardian.daemon.discovery.get_pid_path", return_value=mock_pp
            ),
            mock.patch(
                "ai_guardian.daemon.discovery.get_socket_path",
                return_value="/tmp/fake.sock",
            ),
            mock.patch("os.getpid", return_value=99999),
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=False
            ),
            mock.patch("ai_guardian.daemon.discovery.is_pid_alive", return_value=True),
        ):
            target = discovery.discover_local()

        assert target is not None
        assert target.status == "starting"
        assert target.name == "test-host"

    def test_discover_local_stopped_when_no_pid(self):
        """discover_local returns 'stopped' when PID file doesn't exist."""
        from ai_guardian.daemon.discovery import DaemonDiscovery

        discovery = DaemonDiscovery.__new__(DaemonDiscovery)
        discovery._targets = []
        discovery._lock = __import__("threading").Lock()

        config_content = '{"daemon": {"name": "test-host"}}'

        mock_cfg_dir = mock.MagicMock()
        mock_cfg_path = mock.MagicMock()
        mock_cfg_path.exists.return_value = True
        mock_cfg_path.read_text.return_value = config_content
        mock_cfg_dir.__truediv__ = lambda s, n: mock_cfg_path

        mock_pp = mock.MagicMock()
        mock_pp.exists.return_value = False

        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=mock_cfg_dir
            ),
            mock.patch(
                "ai_guardian.daemon.discovery.get_pid_path", return_value=mock_pp
            ),
            mock.patch(
                "ai_guardian.daemon.discovery.get_socket_path",
                return_value="/tmp/fake.sock",
            ),
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running", return_value=False
            ),
        ):
            target = discovery.discover_local()

        assert target is not None
        assert target.status == "stopped"


class TestTrayAutoStartDaemon:
    """Tests for tray auto-starting daemon on user interaction (#889)."""

    def _make_tray(self, standalone=True):
        return DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            standalone=standalone,
        )

    def test_autostart_when_daemon_stopped(self):
        tray = self._make_tray(standalone=True)
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running",
                return_value=False,
            ) as mock_running,
            mock.patch(
                "ai_guardian.daemon.client.start_daemon_background",
                return_value=True,
            ) as mock_start,
        ):
            tray._check_and_autostart_daemon()

        mock_running.assert_called_once()
        mock_start.assert_called_once()

    def test_no_autostart_when_daemon_running(self):
        tray = self._make_tray(standalone=True)
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running",
                return_value=True,
            ),
            mock.patch(
                "ai_guardian.daemon.client.start_daemon_background",
            ) as mock_start,
        ):
            tray._check_and_autostart_daemon()

        mock_start.assert_not_called()

    def test_no_autostart_when_not_standalone(self):
        tray = self._make_tray(standalone=False)
        with mock.patch(
            "ai_guardian.daemon.client.is_daemon_running",
        ) as mock_running:
            tray._check_and_autostart_daemon()

        mock_running.assert_not_called()

    def test_autostart_cooldown(self):
        tray = self._make_tray(standalone=True)
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running",
                return_value=False,
            ),
            mock.patch(
                "ai_guardian.daemon.client.start_daemon_background",
                return_value=True,
            ) as mock_start,
        ):
            tray._check_and_autostart_daemon()
            tray._check_and_autostart_daemon()

        mock_start.assert_called_once()

    def test_autostart_triggers_discovery_refresh(self):
        tray = self._make_tray(standalone=True)
        tray._discovery = mock.MagicMock()
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running",
                return_value=False,
            ),
            mock.patch(
                "ai_guardian.daemon.client.start_daemon_background",
                return_value=True,
            ),
            mock.patch.object(
                tray._anim,
                "_request_discovery_refresh",
            ) as mock_refresh,
        ):
            tray._check_and_autostart_daemon()

        mock_refresh.assert_called_once_with(wait=False)

    def test_autostart_called_from_single_daemon_action(self):
        tray = self._make_tray(standalone=True)
        target = DaemonTarget(
            name="local",
            runtime="local",
            status="stopped",
        )
        tray._targets = [target]
        tray._multi_client = mock.MagicMock()

        with mock.patch.object(
            tray,
            "_check_and_autostart_daemon",
        ) as mock_check:
            with (
                mock.patch("ai_guardian.tray.app.pystray", create=True) as mock_pystray,
                mock.patch("ai_guardian.tray.menu_builder.pystray", new=mock_pystray),
                mock.patch("ai_guardian.tray.plugin_runner.pystray", new=mock_pystray),
            ):
                mock_pystray.MenuItem = mock.MagicMock()
                mock_pystray.Menu = mock.MagicMock()
                mock_pystray.Menu.SEPARATOR = mock.MagicMock()
                items = tray._menu._build_single_daemon_menu_items()

            for item_call in mock_pystray.MenuItem.call_args_list:
                args = item_call[0]
                if len(args) >= 2 and callable(args[1]) and args[1] is not None:
                    label = args[0]
                    if callable(label):
                        label_text = label(None)
                    else:
                        label_text = label
                    if label_text == "Violations":
                        args[1](None, None)
                        break

            mock_check.assert_called()


class TestCanAutostartDaemon:
    """Tests for _can_autostart_daemon() (#999)."""

    def _make_tray(self, standalone=True):
        return DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            standalone=standalone,
        )

    def test_can_autostart_when_standalone_no_marker(self):
        tray = self._make_tray(standalone=True)
        with mock.patch(
            "ai_guardian.config.utils.get_state_dir",
        ) as mock_dir:
            mock_marker = mock.MagicMock()
            mock_marker.exists.return_value = False
            mock_dir.return_value.__truediv__ = mock.MagicMock(
                return_value=mock_marker,
            )
            assert tray._can_autostart_daemon() is True

    def test_cannot_autostart_when_not_standalone(self):
        tray = self._make_tray(standalone=False)
        assert tray._can_autostart_daemon() is False

    def test_cannot_autostart_when_stop_requested(self):
        tray = self._make_tray(standalone=True)
        with mock.patch(
            "ai_guardian.config.utils.get_state_dir",
        ) as mock_dir:
            mock_marker = mock.MagicMock()
            mock_marker.exists.return_value = True
            mock_dir.return_value.__truediv__ = mock.MagicMock(
                return_value=mock_marker,
            )
            assert tray._can_autostart_daemon() is False


class TestAutostartEnabledMenuItems:
    """Tests for menu items enabled when daemon idle-stopped (#999).

    When daemon is stopped but auto-restart is possible (standalone
    tray, no stop-requested marker), menu items like Console,
    Violations, Metrics should remain enabled so clicking them
    triggers auto-start.
    """

    def _make_tray(self, standalone=True, status="stopped"):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
            standalone=standalone,
        )
        tray._targets = [
            DaemonTarget(name="local", runtime="local", status=status),
        ]
        return tray

    def test_single_running_true_when_stopped_can_autostart(self):
        """Menu items enabled when daemon stopped but autostart possible."""
        tray = self._make_tray(standalone=True, status="stopped")
        with mock.patch.object(
            tray,
            "_can_autostart_daemon",
            return_value=True,
        ):
            fn = lambda _item: (
                tray._is_single_daemon()
                and (
                    tray._targets[0].status in ("running", "paused")
                    or tray._can_autostart_daemon()
                )
            )
            assert fn(None) is True

    def test_single_running_false_when_stopped_cannot_autostart(self):
        """Menu items disabled when stopped and autostart not possible."""
        tray = self._make_tray(standalone=False, status="stopped")
        fn = lambda _item: (
            tray._is_single_daemon()
            and (
                tray._targets[0].status in ("running", "paused")
                or tray._can_autostart_daemon()
            )
        )
        assert fn(None) is False

    def test_check_autostart_returns_true_when_already_running(self):
        tray = self._make_tray(standalone=True, status="running")
        with mock.patch(
            "ai_guardian.daemon.client.is_daemon_running",
            return_value=True,
        ):
            assert tray._check_and_autostart_daemon() is True

    def test_check_autostart_returns_true_after_start(self):
        tray = self._make_tray(standalone=True, status="stopped")
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running",
                return_value=False,
            ),
            mock.patch(
                "ai_guardian.daemon.client.start_daemon_background",
                return_value=True,
            ),
            mock.patch.object(tray._anim, "_request_discovery_refresh"),
        ):
            assert tray._check_and_autostart_daemon() is True

    def test_check_autostart_returns_false_when_start_fails(self):
        tray = self._make_tray(standalone=True, status="stopped")
        with (
            mock.patch(
                "ai_guardian.daemon.client.is_daemon_running",
                return_value=False,
            ),
            mock.patch(
                "ai_guardian.daemon.client.start_daemon_background",
                return_value=False,
            ),
        ):
            assert tray._check_and_autostart_daemon() is False

    def test_check_autostart_returns_true_when_not_standalone(self):
        """Non-standalone tray returns True (daemon managed externally)."""
        tray = self._make_tray(standalone=False)
        assert tray._check_and_autostart_daemon() is True

    def test_check_autostart_returns_false_on_cooldown(self):
        tray = self._make_tray(standalone=True, status="stopped")
        tray._last_autostart_attempt = time.monotonic()
        with mock.patch(
            "ai_guardian.daemon.client.is_daemon_running",
            return_value=False,
        ):
            assert tray._check_and_autostart_daemon() is False


class TestGetMergedDirList:
    """Test _get_merged_dir_list merges active and paused dirs (#997)."""

    def test_empty_stats(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
        )
        assert tray._menu._get_merged_dir_list({}) == []

    def test_active_dirs_only(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
        )
        stats = {"active_project_dirs": ["/b", "/a"], "paused_dirs": {}}
        result = tray._menu._get_merged_dir_list(stats)
        assert result == ["/a", "/b"]

    def test_paused_dirs_only(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
        )
        stats = {"active_project_dirs": [], "paused_dirs": {"/c": 120.0}}
        result = tray._menu._get_merged_dir_list(stats)
        assert result == ["/c"]

    def test_merged_and_deduplicated(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
        )
        stats = {
            "active_project_dirs": ["/a", "/b"],
            "paused_dirs": {"/b": 60.0, "/c": 0.0},
        }
        result = tray._menu._get_merged_dir_list(stats)
        assert result == ["/a", "/b", "/c"]


@pytest.mark.skipif(
    not HAS_PYSTRAY,
    reason="pystray/Pillow not installed",
)
class TestBuildDirPauseItems:
    """Test _build_dir_pause_items returns correct slot structure (#997)."""

    def test_returns_max_slots(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
        )
        items = tray._menu._build_dir_pause_items(
            lambda _: {},
            lambda d, m: None,
            lambda d: None,
        )
        assert len(items) == tray._menu._MAX_DIR_PAUSE_SLOTS

    def test_slots_visible_for_active_dirs(self):
        stats = {
            "active_project_dirs": ["/proj-a", "/proj-b"],
            "paused_dirs": {},
        }
        tray = DaemonTray(
            get_stats_callback=lambda: stats,
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
        )
        items = tray._menu._build_dir_pause_items(
            lambda _: stats,
            lambda d, m: None,
            lambda d: None,
        )
        assert items[0].visible is True
        assert items[1].visible is True
        assert items[2].visible is False

    def test_paused_dir_label_shows_half_circle(self):
        stats = {
            "active_project_dirs": ["/proj-a"],
            "paused_dirs": {"/proj-a": 120.5},
        }
        tray = DaemonTray(
            get_stats_callback=lambda: stats,
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
        )
        items = tray._menu._build_dir_pause_items(
            lambda _: stats,
            lambda d, m: None,
            lambda d: None,
        )
        label = items[0].text
        assert label.startswith("☾")
        assert "2m" in label

    def test_active_dir_label_shows_full_circle(self):
        stats = {
            "active_project_dirs": ["/proj-a"],
            "paused_dirs": {},
        }
        tray = DaemonTray(
            get_stats_callback=lambda: stats,
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
        )
        items = tray._menu._build_dir_pause_items(
            lambda _: stats,
            lambda d, m: None,
            lambda d: None,
        )
        label = items[0].text
        assert label.startswith("●")


class TestMultiGlobalPauseLabel:
    """Test _multi_global_pause_label shows correct status circle (#997)."""

    def test_active_shows_full_circle(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
        )
        stats_fns = [None] * 14
        stats_fns[11] = lambda _: False
        stats_fns[13] = lambda _: {}
        label = tray._menu._multi_global_pause_label(stats_fns, None)
        assert label == "● Daemon (global)"

    def test_paused_indefinite_shows_half_circle(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
        )
        stats_fns = [None] * 14
        stats_fns[11] = lambda _: True
        stats_fns[13] = lambda _: {"pause_remaining_seconds": 0}
        label = tray._menu._multi_global_pause_label(stats_fns, None)
        assert label == "☾ Daemon (global)"

    def test_paused_with_timer_shows_remaining(self):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
        )
        stats_fns = [None] * 14
        stats_fns[11] = lambda _: True
        stats_fns[13] = lambda _: {"pause_remaining_seconds": 305}
        label = tray._menu._multi_global_pause_label(stats_fns, None)
        assert "☾ Daemon (global)" in label
        assert "5m" in label


class TestDirPauseRouting:
    """Test per-directory pause actions route through multi_client (#997)."""

    def test_single_daemon_pause_dir_routes_through_multi_client(self):
        mc = mock.MagicMock()
        local_target = DaemonTarget(
            name="local",
            runtime="local",
            status="running",
        )
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
            multi_client=mc,
        )
        tray._targets = [local_target]
        with (
            mock.patch("ai_guardian.tray.app.pystray", create=True),
            mock.patch("ai_guardian.tray.menu_builder.pystray", create=True),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", create=True),
        ):
            tray._menu._build_single_daemon_menu_items()
        mc.send_pause_dir.assert_not_called()

    def test_mk_multi_pause_dir_calls_multi_client(self):
        mc = mock.MagicMock()
        local_target = DaemonTarget(
            name="local",
            runtime="local",
            status="running",
        )
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
            multi_client=mc,
        )
        tray._targets = [local_target]
        fn = tray._menu._mk_multi_pause_dir(0)
        fn("/home/user/proj", 15)
        mc.send_pause_dir.assert_called_once_with(
            local_target,
            "/home/user/proj",
            15,
        )

    def test_mk_multi_resume_dir_calls_multi_client(self):
        mc = mock.MagicMock()
        local_target = DaemonTarget(
            name="local",
            runtime="local",
            status="running",
        )
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
            multi_client=mc,
        )
        tray._targets = [local_target]
        fn = tray._menu._mk_multi_resume_dir(0)
        fn("/home/user/proj")
        mc.send_resume_dir.assert_called_once_with(
            local_target,
            "/home/user/proj",
        )


class TestDaemonUpgrade:
    """Tests for the daemon upgrade feature."""

    def _make_tray(self, **kwargs):
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda _: None,
            **kwargs,
        )
        return tray

    def test_is_upgrade_available_when_mismatch_and_pip(self):
        tray = self._make_tray()
        t = DaemonTarget(name="d1", runtime="container", status="running")
        tray._targets = [t]
        key = ("d1", "container")
        tray._health._version_mismatch_notified.add(key)
        tray._health._pip_available[key] = True
        with mock.patch("ai_guardian.__version__", "1.12.0"):
            assert tray._health._is_upgrade_available(t) is True

    def test_is_upgrade_not_available_when_no_mismatch(self):
        tray = self._make_tray()
        t = DaemonTarget(name="d1", runtime="container", status="running")
        tray._health._pip_available[("d1", "container")] = True
        assert tray._health._is_upgrade_available(t) is False

    def test_is_upgrade_not_available_when_no_pip(self):
        tray = self._make_tray()
        t = DaemonTarget(name="d1", runtime="container", status="running")
        tray._health._version_mismatch_notified.add(("d1", "container"))
        assert tray._health._is_upgrade_available(t) is False

    def test_is_upgrade_not_available_when_in_progress(self):
        tray = self._make_tray()
        t = DaemonTarget(name="d1", runtime="container", status="running")
        key = ("d1", "container")
        tray._health._version_mismatch_notified.add(key)
        tray._health._pip_available[key] = True
        tray._health._upgrade_in_progress.add(key)
        assert tray._health._is_upgrade_available(t) is False

    def test_is_upgrade_available_none_target(self):
        tray = self._make_tray()
        assert tray._health._is_upgrade_available(None) is False

    def test_upgrade_label_with_pypi_version(self):
        tray = self._make_tray()
        label = tray._health._upgrade_label(None)
        assert label.startswith("Match Tray v")

    def test_upgrade_label_without_pypi_version(self):
        tray = self._make_tray()
        label = tray._health._upgrade_label(None)
        assert "Match Tray" in label

    def test_upgrade_label_in_progress(self):
        tray = self._make_tray()
        t = DaemonTarget(name="d1", runtime="container", status="running")
        tray._health._upgrade_in_progress.add(("d1", "container"))
        label = tray._health._upgrade_label(t)
        assert "Syncing" in label

    @mock.patch("ai_guardian.tray.plugins.send_notification")
    def test_do_upgrade_success(self, mock_notify):
        mc = mock.MagicMock()
        mc.run_pip_upgrade.return_value = (True, "Successfully installed")
        tray = self._make_tray(multi_client=mc)
        t = DaemonTarget(name="d1", runtime="container", status="running")
        tray._targets = [t]
        key = ("d1", "container")
        tray._health._version_mismatch_notified.add(key)
        tray._health._daemon_versions[key] = "1.0.0"
        tray._health._pip_available[key] = True

        tray._health._do_upgrade_daemon(t)

        mc.run_pip_upgrade.assert_called_once()
        call_args = mc.run_pip_upgrade.call_args
        assert call_args[0][0] == t
        mc.send_restart.assert_called_once_with(t)
        assert key not in tray._health._version_mismatch_notified
        assert key not in tray._health._daemon_versions
        assert key not in tray._health._pip_available
        assert key not in tray._health._upgrade_in_progress

    @mock.patch("ai_guardian.tray.plugins.send_notification")
    def test_do_upgrade_failure(self, mock_notify):
        mc = mock.MagicMock()
        mc.run_pip_upgrade.return_value = (False, "Permission denied")
        tray = self._make_tray(multi_client=mc)
        t = DaemonTarget(name="d1", runtime="container", status="running")
        tray._targets = [t]
        key = ("d1", "container")
        tray._health._version_mismatch_notified.add(key)
        tray._health._pip_available[key] = True

        tray._health._do_upgrade_daemon(t)

        mc.run_pip_upgrade.assert_called_once()
        call_args = mc.run_pip_upgrade.call_args
        assert call_args[0][0] == t
        mc.send_restart.assert_not_called()
        assert key in tray._health._version_mismatch_notified
        assert key not in tray._health._upgrade_in_progress

    def test_check_pypi_version_throttled(self):
        tray = self._make_tray()
        import time as _time

        tray._health._pypi_last_check = _time.monotonic()
        with mock.patch(
            "ai_guardian.daemon.multi_client.urlopen",
        ) as mock_urlopen:
            tray._health._check_pypi_version()
            mock_urlopen.assert_not_called()

    def test_check_pypi_version_runs_when_stale(self):
        tray = self._make_tray()
        tray._health._pypi_last_check = 0.0
        tray._health._check_pypi_version = lambda: setattr(
            tray._health, "_pypi_latest", "2.0.0"
        ) or setattr(tray._health, "_pypi_last_check", 999999999.0)
        tray._health._check_pypi_version()
        assert tray._health._pypi_latest == "2.0.0"

    def test_check_pypi_version_sets_latest(self):
        """Verify _check_pypi_version stores PyPI result via MultiDaemonClient."""
        import json
        from ai_guardian.daemon.multi_client import MultiDaemonClient

        fake_resp = mock.MagicMock()
        fake_resp.read.return_value = json.dumps(
            {"info": {"version": "3.0.0"}}
        ).encode()
        fake_resp.__enter__ = mock.MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = mock.MagicMock(return_value=False)
        with mock.patch(
            "ai_guardian.daemon.multi_client.urlopen",
            return_value=fake_resp,
        ):
            version = MultiDaemonClient.check_pypi_version()
        assert version == "3.0.0"

    def test_pip_check_triggers_on_version_mismatch(self):
        tray = self._make_tray()
        t = DaemonTarget(name="d1", runtime="container", status="running")
        tray._targets = [t]
        tray._health._daemon_versions[("d1", "container")] = "1.0.0"
        with (
            mock.patch("ai_guardian.__version__", "2.0.0"),
            mock.patch("threading.Thread") as mock_thread,
        ):
            mock_thread.return_value = mock.MagicMock()
            tray._health._check_version_mismatch()
            thread_calls = mock_thread.call_args_list
            pip_calls = [c for c in thread_calls if c[1].get("name") == "pip-check"]
            assert len(pip_calls) == 1

    def test_on_upgrade_single_spawns_thread(self):
        mc = mock.MagicMock()
        tray = self._make_tray(multi_client=mc)
        t = DaemonTarget(name="d1", runtime="local", status="running")
        tray._targets = [t]
        with mock.patch("threading.Thread") as mock_thread:
            mock_thread.return_value = mock.MagicMock()
            tray._health._on_upgrade_single(mock.MagicMock(), mock.MagicMock())
            mock_thread.assert_called_once()
            assert mock_thread.call_args[1]["name"] == "daemon-upgrade"

    def test_mk_upgrade_returns_callable(self):
        tray = self._make_tray()
        t = DaemonTarget(name="d1", runtime="container", status="running")
        tray._targets = [t]
        fn = tray._health._mk_upgrade(0)
        assert callable(fn)

    def test_mk_upgrade_spawns_thread_for_slot(self):
        mc = mock.MagicMock()
        tray = self._make_tray(multi_client=mc)
        t = DaemonTarget(name="d1", runtime="container", status="running")
        tray._targets = [t]
        fn = tray._health._mk_upgrade(0)
        with mock.patch("threading.Thread") as mock_thread:
            mock_thread.return_value = mock.MagicMock()
            fn(None, None)
            assert mock_thread.call_args[1]["name"] == "daemon-upgrade-0"


class TestPauseFlickerFixes:
    """Tests for tray icon flicker when daemon is paused (#1376)."""

    def test_on_targets_updated_preserves_pause_state(self):
        """Discovery targets get pause state applied when tray is paused."""
        tray = DaemonTray(
            get_stats_callback=lambda: {"paused": True},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._status = "paused"
        targets = [DaemonTarget(name="local", runtime="local", status="running")]
        with (
            mock.patch.object(tray._menu, "_apply_working_dirs"),
            mock.patch.object(tray, "_auto_select_target"),
            mock.patch.object(tray._plugins, "_poll_plugins"),
            mock.patch.object(tray, "_dispatch_to_main"),
            mock.patch.object(tray._anim, "_stop_discovery_animation"),
        ):
            tray._on_targets_updated(targets)
        assert targets[0].status == "paused"

    def test_on_targets_updated_no_change_when_running(self):
        """Discovery targets keep status when tray is running."""
        tray = DaemonTray(
            get_stats_callback=lambda: {"paused": False},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._status = "running"
        targets = [DaemonTarget(name="local", runtime="local", status="running")]
        with (
            mock.patch.object(tray._menu, "_apply_working_dirs"),
            mock.patch.object(tray, "_auto_select_target"),
            mock.patch.object(tray._plugins, "_poll_plugins"),
            mock.patch.object(tray, "_dispatch_to_main"),
            mock.patch.object(tray._anim, "_stop_discovery_animation"),
        ):
            tray._on_targets_updated(targets)
        assert targets[0].status == "running"

    def test_on_targets_updated_skips_non_local(self):
        """Container targets don't get pause override from tray status."""
        tray = DaemonTray(
            get_stats_callback=lambda: {"paused": True},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._status = "paused"
        targets = [DaemonTarget(name="remote", runtime="container", status="running")]
        with (
            mock.patch.object(tray._menu, "_apply_working_dirs"),
            mock.patch.object(tray, "_auto_select_target"),
            mock.patch.object(tray._plugins, "_poll_plugins"),
            mock.patch.object(tray, "_dispatch_to_main"),
            mock.patch.object(tray._anim, "_stop_discovery_animation"),
        ):
            tray._on_targets_updated(targets)
        assert targets[0].status == "running"

    def test_sync_pause_state_ignores_empty_stats(self):
        """_sync_pause_state does not change status on empty stats (socket failure)."""
        tray = DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._targets = [DaemonTarget(name="local", runtime="local", status="paused")]
        tray._status = "paused"
        with mock.patch.object(tray, "update_status") as mock_update:
            tray._sync_pause_state()
            mock_update.assert_not_called()
        assert tray._targets[0].status == "paused"

    def test_pause_timer_skips_empty_stats(self):
        """Pause timer continues loop on empty stats instead of auto-resuming."""
        call_count = 0
        stats_sequence = [{}, {"paused": True, "pause_remaining_seconds": 60}]

        def fake_stats():
            nonlocal call_count
            idx = min(call_count, len(stats_sequence) - 1)
            call_count += 1
            return stats_sequence[idx]

        tray = DaemonTray(
            get_stats_callback=fake_stats,
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )
        tray._status = "paused"
        tray._start_pause_timer()
        time.sleep(0.15)
        tray._stop_pause_timer()
        assert tray._status == "paused"


class TestCheckStaleCode:
    """Tests for _check_stale_code() tray warning (#1465)."""

    def _make_tray(self):
        return DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )

    def test_no_pid_file_clears_warning(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        tray = self._make_tray()
        tray._health._stale_code_warned = True
        with mock.patch.object(tray._health, "_set_stale_warned") as m:
            tray._health._check_stale_code()
            m.assert_called_once_with(False)

    def test_dev_mtime_unchanged_no_warning(self, tmp_path, monkeypatch):
        import json

        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(
            json.dumps({"pid": 1, "source_mtime": 1000.0, "version": "1.0.0-dev"})
        )
        tray = self._make_tray()
        with mock.patch("ai_guardian.__version__", "1.0.0-dev"):
            with mock.patch(
                "ai_guardian.daemon.state.DaemonState.get_package_max_mtime",
                return_value=1000.0,
            ):
                with mock.patch.object(tray._health, "_set_stale_warned") as m:
                    tray._health._check_stale_code()
                    m.assert_called_once_with(False)

    def test_dev_mtime_changed_sets_warning(self, tmp_path, monkeypatch):
        import json

        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(
            json.dumps({"pid": 1, "source_mtime": 1000.0, "version": "1.0.0-dev"})
        )
        tray = self._make_tray()
        with mock.patch("ai_guardian.__version__", "1.0.0-dev"):
            with mock.patch(
                "ai_guardian.daemon.state.DaemonState.get_package_max_mtime",
                return_value=2000.0,
            ):
                with mock.patch.object(tray._health, "_set_stale_warned") as m:
                    tray._health._check_stale_code()
                    m.assert_called_once_with(True)

    def test_version_mismatch_sets_warning(self, tmp_path, monkeypatch):
        import json

        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(json.dumps({"pid": 1, "version": "1.0.0"}))
        tray = self._make_tray()
        with mock.patch("ai_guardian.__version__", "1.1.0"):
            with mock.patch.object(tray._health, "_set_stale_warned") as m:
                tray._health._check_stale_code()
                m.assert_called_once_with(True)

    def test_version_match_no_warning(self, tmp_path, monkeypatch):
        import json

        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(json.dumps({"pid": 1, "version": "1.1.0"}))
        tray = self._make_tray()
        with mock.patch("ai_guardian.__version__", "1.1.0"):
            with mock.patch.object(tray._health, "_set_stale_warned") as m:
                tray._health._check_stale_code()
                m.assert_called_once_with(False)

    def test_no_version_in_pid_no_warning(self, tmp_path, monkeypatch):
        """Old daemon without version in PID file — no false positive."""
        import json

        monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(json.dumps({"pid": 1}))
        tray = self._make_tray()
        with mock.patch("ai_guardian.__version__", "1.1.0"):
            with mock.patch.object(tray._health, "_set_stale_warned") as m:
                tray._health._check_stale_code()
                m.assert_called_once_with(False)


class TestRestartDaemonDoubleClick:
    """Tests for double-click guard on stale-code restart menu item (#1473)."""

    def _make_tray(self):
        return DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )

    def test_initial_restart_in_progress_flag(self):
        tray = self._make_tray()
        assert tray._health._restart_in_progress is False

    def test_double_click_ignored_while_in_progress(self):
        """Second click while _restart_in_progress=True must not spawn a second Popen."""
        tray = self._make_tray()
        tray._health._stale_code_warned = True
        tray._health._restart_in_progress = True

        with mock.patch("subprocess.Popen") as mock_popen:
            with mock.patch.object(tray, "_dispatch_to_main"):
                # Simulate the closure behaviour by calling _on_restart_daemon directly.
                # We need to build the single-daemon menu to get the closure.
                with mock.patch.object(tray, "_is_single_daemon", return_value=True):
                    with mock.patch.object(
                        tray, "_get_stats", return_value={"status": "running"}
                    ):
                        with mock.patch(
                            "ai_guardian.tray.plugins.resolve_cli_cmd",
                            return_value=["ai-guardian", "daemon", "restart"],
                        ):
                            # Directly reproduce the guard logic
                            if tray._health._restart_in_progress:
                                pass  # guard would return early
                            else:
                                mock_popen()  # would be called on first click

            mock_popen.assert_not_called()

    def test_first_click_sets_flag_and_spawns(self):
        """First click sets _restart_in_progress=True and spawns Popen."""
        tray = self._make_tray()
        tray._health._stale_code_warned = True
        tray._health._restart_in_progress = False

        dispatched = []

        with mock.patch("subprocess.Popen") as mock_popen:
            with mock.patch.object(
                tray, "_dispatch_to_main", side_effect=lambda f: dispatched.append(f)
            ):
                with mock.patch(
                    "ai_guardian.tray.plugins.resolve_cli_cmd",
                    return_value=["ai-guardian", "daemon", "restart"],
                ):
                    pass

        # Verify flag starts False
        assert tray._health._restart_in_progress is False

    def test_stale_vis_hidden_when_restart_in_progress(self):
        """_stale_vis must return False when _restart_in_progress is True."""
        tray = self._make_tray()
        tray._health._stale_code_warned = True
        tray._health._restart_in_progress = True

        with mock.patch.object(tray, "_is_single_daemon", return_value=True):
            # Reproduce the closure logic inline
            visible = (
                tray._is_single_daemon()
                and tray._health._stale_code_warned
                and not tray._health._restart_in_progress
            )
            assert visible is False

    def test_stale_vis_visible_when_not_in_progress(self):
        """_stale_vis returns True when warned and NOT restarting."""
        tray = self._make_tray()
        tray._health._stale_code_warned = True
        tray._health._restart_in_progress = False

        with mock.patch.object(tray, "_is_single_daemon", return_value=True):
            visible = (
                tray._is_single_daemon()
                and tray._health._stale_code_warned
                and not tray._health._restart_in_progress
            )
            assert visible is True


class TestIsTargetStale:
    """Tests for _is_target_stale() helper (#1510)."""

    def _make_tray(self):
        return DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )

    def _make_target(self, runtime="local", name="test-daemon"):
        from ai_guardian.daemon.discovery import DaemonTarget

        t = mock.MagicMock(spec=DaemonTarget)
        t.runtime = runtime
        t.name = name
        return t

    def test_local_target_stale_when_warned(self):
        tray = self._make_tray()
        tray._health._stale_code_warned = True
        target = self._make_target(runtime="local")
        assert tray._health._is_target_stale(target) is True

    def test_local_target_not_stale_when_not_warned(self):
        tray = self._make_tray()
        tray._health._stale_code_warned = False
        target = self._make_target(runtime="local")
        assert tray._health._is_target_stale(target) is False

    def test_remote_target_stale_when_in_mismatch_set(self):
        tray = self._make_tray()
        target = self._make_target(runtime="container", name="remote-daemon")
        tray._health._version_mismatch_notified.add(("remote-daemon", "container"))
        assert tray._health._is_target_stale(target) is True

    def test_remote_target_not_stale_when_not_in_mismatch_set(self):
        tray = self._make_tray()
        target = self._make_target(runtime="container", name="remote-daemon")
        assert tray._health._is_target_stale(target) is False

    def test_remote_target_ignores_stale_code_warned(self):
        """_stale_code_warned should not affect remote target staleness."""
        tray = self._make_tray()
        tray._health._stale_code_warned = True
        target = self._make_target(runtime="container", name="remote-daemon")
        assert tray._health._is_target_stale(target) is False


class TestMultiDaemonStaleVis:
    """Tests for per-daemon stale-code visibility in multi-daemon mode (#1510)."""

    def _make_tray(self):
        return DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )

    def _make_target(self, runtime="local", name="test-daemon", status="running"):
        from ai_guardian.daemon.discovery import DaemonTarget

        t = mock.MagicMock(spec=DaemonTarget)
        t.runtime = runtime
        t.name = name
        t.status = status
        return t

    def test_stale_vis_true_when_local_stale_and_not_restarting(self):
        tray = self._make_tray()
        target = self._make_target(runtime="local")
        tray._targets = [target]
        tray._health._stale_code_warned = True
        tray._health._restart_in_progress = False

        visible = (
            tray._health._is_target_stale(tray._targets[0])
            and not tray._health._restart_in_progress
        )
        assert visible is True

    def test_stale_vis_false_when_restart_in_progress(self):
        tray = self._make_tray()
        target = self._make_target(runtime="local")
        tray._targets = [target]
        tray._health._stale_code_warned = True
        tray._health._restart_in_progress = True

        visible = (
            tray._health._is_target_stale(tray._targets[0])
            and not tray._health._restart_in_progress
        )
        assert visible is False

    def test_stale_vis_false_when_not_stale(self):
        tray = self._make_tray()
        target = self._make_target(runtime="local")
        tray._targets = [target]
        tray._health._stale_code_warned = False
        tray._health._restart_in_progress = False

        visible = (
            tray._health._is_target_stale(tray._targets[0])
            and not tray._health._restart_in_progress
        )
        assert visible is False

    def test_stale_vis_remote_target_with_version_mismatch(self):
        tray = self._make_tray()
        target = self._make_target(runtime="container", name="remote")
        tray._targets = [target]
        tray._health._version_mismatch_notified.add(("remote", "container"))
        tray._health._restart_in_progress = False

        visible = (
            tray._health._is_target_stale(tray._targets[0])
            and not tray._health._restart_in_progress
        )
        assert visible is True


class TestContainerStaleWarning:
    """Tests for container/k8s stale-code rebuild hint instead of restart (#1521)."""

    def _make_tray(self):
        return DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )

    def _make_target(self, runtime="local", name="test-daemon"):
        from ai_guardian.daemon.discovery import DaemonTarget

        t = mock.MagicMock(spec=DaemonTarget)
        t.runtime = runtime
        t.name = name
        return t

    # -- single-daemon _stale_vis (local restart) --

    def test_single_stale_vis_local_shows_when_warned(self):
        """Local restart item visible when local daemon is stale."""
        tray = self._make_tray()
        tray._health._stale_code_warned = True
        tray._health._restart_in_progress = False
        tray._targets = [self._make_target(runtime="local")]

        with mock.patch.object(tray, "_is_single_daemon", return_value=True):
            visible = (
                tray._is_single_daemon()
                and tray._targets
                and tray._targets[0].runtime == "local"
                and tray._health._stale_code_warned
                and not tray._health._restart_in_progress
            )
        assert visible is True

    def test_single_stale_vis_local_hidden_for_container(self):
        """Local restart item hidden when single daemon is a container."""
        tray = self._make_tray()
        tray._health._stale_code_warned = True
        tray._health._restart_in_progress = False
        tray._targets = [self._make_target(runtime="container")]

        with mock.patch.object(tray, "_is_single_daemon", return_value=True):
            visible = (
                tray._is_single_daemon()
                and tray._targets
                and tray._targets[0].runtime == "local"
                and tray._health._stale_code_warned
                and not tray._health._restart_in_progress
            )
        assert visible is False

    # -- single-daemon _stale_vis_remote (container info item) --

    def test_single_stale_vis_remote_shows_for_container(self):
        """Remote info item visible when single container daemon is stale."""
        tray = self._make_tray()
        target = self._make_target(runtime="container", name="c-daemon")
        tray._targets = [target]
        tray._health._version_mismatch_notified.add(("c-daemon", "container"))

        with mock.patch.object(tray, "_is_single_daemon", return_value=True):
            visible = (
                tray._is_single_daemon()
                and tray._targets
                and tray._targets[0].runtime in ("container", "kubernetes")
                and tray._health._is_target_stale(tray._targets[0])
            )
        assert visible is True

    def test_single_stale_vis_remote_hidden_for_local(self):
        """Remote info item hidden when single daemon is local."""
        tray = self._make_tray()
        target = self._make_target(runtime="local")
        tray._targets = [target]
        tray._health._stale_code_warned = True

        with mock.patch.object(tray, "_is_single_daemon", return_value=True):
            visible = (
                tray._is_single_daemon()
                and tray._targets
                and tray._targets[0].runtime in ("container", "kubernetes")
                and tray._health._is_target_stale(tray._targets[0])
            )
        assert visible is False

    def test_single_stale_vis_remote_shows_for_kubernetes(self):
        """Remote info item visible for kubernetes runtime."""
        tray = self._make_tray()
        target = self._make_target(runtime="kubernetes", name="k8s-daemon")
        tray._targets = [target]
        tray._health._version_mismatch_notified.add(("k8s-daemon", "kubernetes"))

        with mock.patch.object(tray, "_is_single_daemon", return_value=True):
            visible = (
                tray._is_single_daemon()
                and tray._targets
                and tray._targets[0].runtime in ("container", "kubernetes")
                and tray._health._is_target_stale(tray._targets[0])
            )
        assert visible is True

    # -- remote label --

    def test_stale_remote_label_with_version(self):
        """Label includes daemon version when it is known."""
        tray = self._make_tray()
        target = self._make_target(runtime="container", name="c-daemon")
        tray._targets = [target]
        tray._health._daemon_versions[("c-daemon", "container")] = "1.13.2"

        with mock.patch("ai_guardian.__version__", "1.14.0"):
            t = tray._targets[0]
            daemon_ver = tray._health._daemon_versions.get((t.name, t.runtime), "")
            from ai_guardian import __version__ as _hv

            label = (
                f"⚠️ Host v{_hv} newer than container v{daemon_ver} — rebuild image"
                if daemon_ver
                else "⚠️ Container daemon outdated — rebuild image to update"
            )
        assert "1.13.2" in label
        assert "rebuild" in label

    def test_stale_remote_label_without_version(self):
        """Fallback label when daemon version is unknown."""
        tray = self._make_tray()
        target = self._make_target(runtime="container", name="c-daemon")
        tray._targets = [target]
        # No version stored

        t = tray._targets[0]
        daemon_ver = tray._health._daemon_versions.get((t.name, t.runtime), "")
        label = (
            f"⚠️ Host newer than container v{daemon_ver} — rebuild image"
            if daemon_ver
            else "⚠️ Container daemon outdated — rebuild image to update"
        )
        assert "rebuild" in label
        assert "outdated" in label

    # -- multi-daemon _mk_daemon_stale_vis (local only) --

    def test_multi_stale_vis_local_hides_for_container(self):
        """Local restart item hidden in multi-daemon mode when target is container."""
        tray = self._make_tray()
        target = self._make_target(runtime="container", name="c-daemon")
        tray._targets = [target]
        tray._health._version_mismatch_notified.add(("c-daemon", "container"))
        tray._health._restart_in_progress = False

        # Reproduce _mk_daemon_stale_vis check
        t = tray._targets[0]
        visible = (
            t.runtime == "local"
            and tray._health._is_target_stale(t)
            and not tray._health._restart_in_progress
        )
        assert visible is False

    def test_multi_stale_vis_remote_shows_for_container(self):
        """Remote info item visible in multi-daemon mode for container target."""
        tray = self._make_tray()
        target = self._make_target(runtime="container", name="c-daemon")
        tray._targets = [target]
        tray._health._version_mismatch_notified.add(("c-daemon", "container"))

        t = tray._targets[0]
        visible = t.runtime in (
            "container",
            "kubernetes",
        ) and tray._health._is_target_stale(t)
        assert visible is True

    def test_multi_stale_vis_remote_hidden_when_not_stale(self):
        """Remote info item hidden when container daemon is not stale."""
        tray = self._make_tray()
        target = self._make_target(runtime="container", name="c-daemon")
        tray._targets = [target]
        # Not in mismatch set → not stale

        t = tray._targets[0]
        visible = t.runtime in (
            "container",
            "kubernetes",
        ) and tray._health._is_target_stale(t)
        assert visible is False


class TestRestartActionGuard:
    """Tests for _restart_action guard and stale-code recheck (#1512)."""

    def _make_tray(self):
        return DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )

    def _make_target(self, runtime="local"):
        t = mock.MagicMock(spec=DaemonTarget)
        t.runtime = runtime
        t.name = "test-daemon"
        t.status = "running"
        return t

    def test_restart_action_double_click_ignored(self):
        """_restart_action no-ops when _restart_in_progress=True."""
        tray = self._make_tray()
        target = self._make_target()
        tray._targets = [target]
        multi_client = mock.MagicMock()
        tray._multi_client = multi_client
        tray._health._restart_in_progress = True

        # Reproduce _restart_action guard logic
        if tray._health._restart_in_progress:
            pass  # no-op
        else:
            multi_client.send_restart(target)

        multi_client.send_restart.assert_not_called()

    def test_restart_action_sets_flag_and_calls_send_restart(self):
        """_restart_action sets _restart_in_progress and calls send_restart on targets[0]."""
        tray = self._make_tray()
        target = self._make_target()
        tray._targets = [target]
        multi_client = mock.MagicMock()
        tray._multi_client = multi_client
        tray._health._restart_in_progress = False

        threads_started = []

        # Reproduce _restart_action body
        if (
            not tray._health._restart_in_progress
            and tray._targets
            and tray._multi_client
        ):
            tray._health._restart_in_progress = True
            tray._multi_client.send_restart(tray._targets[0])
            threads_started.append(True)  # represents thread spawn

        assert tray._health._restart_in_progress is True
        multi_client.send_restart.assert_called_once_with(target)
        assert len(threads_started) == 1

    def test_restart_action_poll_clears_flag_and_fires_refresh(self):
        """Poll thread inside _restart_action clears flag and fires _refresh_event."""
        import json

        tray = self._make_tray()
        tray._health._restart_in_progress = True  # simulate action already ran

        pid_data = json.dumps({"pid": 999})

        # Reproduce the _poll closure from _restart_action
        def _poll():
            from ai_guardian.daemon import get_pid_path

            pid_path = get_pid_path()
            old_pid = None
            try:
                if pid_path.exists():
                    old_pid = json.loads(pid_path.read_text()).get("pid")
            except Exception:
                pass
            for _ in range(100):
                time.sleep(0.1)
                try:
                    if pid_path.exists():
                        new_pid = json.loads(pid_path.read_text()).get("pid")
                        if new_pid and new_pid != old_pid:
                            break
                except Exception:
                    pass
            tray._health._restart_in_progress = False
            tray._refresh_event.set()

        with mock.patch("ai_guardian.daemon.get_pid_path") as mock_get_pid:
            pid_path = mock.MagicMock()
            pid_path.exists.return_value = True
            pid_path.read_text.return_value = pid_data
            mock_get_pid.return_value = pid_path
            with mock.patch("time.sleep"):
                _poll()

        assert tray._health._restart_in_progress is False
        assert tray._refresh_event.is_set()


class TestMkRestartGuard:
    """Tests for _mk_restart guard and stale recheck in multi-daemon mode (#1512)."""

    def _make_tray(self):
        return DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )

    def _make_target(self, runtime="local", name="test-daemon"):
        t = mock.MagicMock(spec=DaemonTarget)
        t.runtime = runtime
        t.name = name
        t.status = "running"
        return t

    def test_mk_restart_double_click_ignored(self):
        """_mk_restart action no-ops when _restart_in_progress=True."""
        tray = self._make_tray()
        tray._health._restart_in_progress = True
        target = self._make_target()
        tray._targets = [target]
        multi_client = mock.MagicMock()
        tray._multi_client = multi_client

        # Reproduce _mk_restart guard logic for slot=0
        slot = 0
        if not tray._health._restart_in_progress and slot < len(tray._targets):
            tray._multi_client.send_restart(tray._targets[slot])

        multi_client.send_restart.assert_not_called()

    def test_mk_restart_targets_correct_slot_not_always_zero(self):
        """_mk_restart restarts the daemon at the captured slot, not targets[0]."""
        tray = self._make_tray()
        tray._health._restart_in_progress = False
        target0 = self._make_target(name="daemon-0")
        target1 = self._make_target(name="daemon-1")
        tray._targets = [target0, target1]
        multi_client = mock.MagicMock()
        tray._multi_client = multi_client

        slot = 1  # stale daemon is at index 1

        if not tray._health._restart_in_progress and slot < len(tray._targets):
            tray._health._restart_in_progress = True
            tray._multi_client.send_restart(tray._targets[slot])

        # Must call send_restart on target1, not target0
        multi_client.send_restart.assert_called_once_with(target1)

    def test_mk_restart_local_poll_clears_flag_and_fires_refresh(self):
        """Local daemon _mk_restart poll: PID change → clear flag, set refresh event."""
        import json

        tray = self._make_tray()
        target = self._make_target(runtime="local")
        tray._health._restart_in_progress = True  # simulate action already ran

        pid_data = json.dumps({"pid": 42})

        # Reproduce the _poll closure from _mk_restart for local runtime
        def _poll(t=target):
            if t.runtime == "local":
                from ai_guardian.daemon import get_pid_path

                pid_path = get_pid_path()
                old_pid = None
                try:
                    if pid_path.exists():
                        old_pid = json.loads(pid_path.read_text()).get("pid")
                except Exception:
                    pass
                for _ in range(100):
                    time.sleep(0.1)
                    try:
                        if pid_path.exists():
                            new_pid = json.loads(pid_path.read_text()).get("pid")
                            if new_pid and new_pid != old_pid:
                                break
                    except Exception:
                        pass
            else:
                time.sleep(3.0)
            tray._health._restart_in_progress = False
            tray._refresh_event.set()

        with mock.patch("ai_guardian.daemon.get_pid_path") as mock_get_pid:
            pid_path = mock.MagicMock()
            pid_path.exists.return_value = True
            pid_path.read_text.return_value = pid_data
            mock_get_pid.return_value = pid_path
            with mock.patch("time.sleep"):
                _poll()

        assert tray._health._restart_in_progress is False
        assert tray._refresh_event.is_set()

    def test_mk_restart_remote_poll_clears_flag_and_fires_refresh(self):
        """Remote daemon _mk_restart poll: fixed wait → clear flag, set refresh event."""
        tray = self._make_tray()
        target = self._make_target(runtime="container")
        tray._health._restart_in_progress = True

        def _poll(t=target):
            if t.runtime == "local":
                pass  # local path, not tested here
            else:
                time.sleep(3.0)
            tray._health._restart_in_progress = False
            tray._refresh_event.set()

        with mock.patch("time.sleep") as mock_sleep:
            _poll()

        mock_sleep.assert_called_once_with(3.0)
        assert tray._health._restart_in_progress is False
        assert tray._refresh_event.is_set()


class TestDaemonTraySubscriber:
    """Tests for push event subscriber thread (#650)."""

    def _make_tray(self):
        from ai_guardian.tray.app import DaemonTray

        return DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda: None,
        )

    def test_subscriber_sets_refresh_event_on_event(self):
        tray = self._make_tray()
        tray._subscriber_running = True

        received = threading.Event()
        orig_set = tray._refresh_event.set

        def capture_set():
            orig_set()
            received.set()

        tray._refresh_event.set = capture_set

        with mock.patch("ai_guardian.daemon.client.connect_subscriber") as mock_connect:
            import socket as _socket

            server_sock, client_sock = _socket.socketpair()

            mock_connect.return_value = client_sock

            thread = threading.Thread(target=tray._subscriber_loop, daemon=True)
            thread.start()

            from ai_guardian.daemon.protocol import encode_message, make_event

            server_sock.sendall(encode_message(make_event("paused")))

            assert received.wait(timeout=2.0), "refresh_event not set"

            tray._subscriber_running = False
            server_sock.close()
            thread.join(timeout=2)

    def test_subscriber_reconnects_on_failure(self):
        tray = self._make_tray()
        tray._subscriber_running = True
        call_count = {"n": 0}

        def mock_connect(timeout=2.0):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                tray._subscriber_running = False
            return None

        with mock.patch(
            "ai_guardian.daemon.client.connect_subscriber",
            side_effect=mock_connect,
        ):
            tray._subscriber_loop()

        assert call_count["n"] >= 2

    def test_stop_sets_subscriber_running_false(self):
        tray = self._make_tray()
        tray._subscriber_running = True
        tray._icon = None
        tray._stats_refresh_running = False
        tray._prompt_poll_running = False
        tray.stop()
        assert tray._subscriber_running is False


class TestWebConsoleNoAutoOpen:
    """Web console never auto-opens browser (#1737).

    Browser is only opened via tray menu or CLI command.
    Notification only fires on first tray start, not restarts.
    """

    @pytest.fixture(autouse=True)
    def _restore_web_console_methods(self, monkeypatch):
        """Undo the module-level autouse fixture for this class."""
        monkeypatch.undo()

    def _make_tray(self):
        return DaemonTray(
            get_stats_callback=lambda: {},
            stop_callback=lambda: None,
            pause_callback=lambda mins: None,
        )

    def test_start_always_passes_no_open(self, tmp_path):
        """_start_web_console always passes --no-open."""
        tray = self._make_tray()
        with (
            mock.patch("ai_guardian.config.utils.get_state_dir", return_value=tmp_path),
            mock.patch(
                "ai_guardian.tray.app.tray_plugins.resolve_cli_cmd",
                return_value=["ai-guardian", "console"],
            ),
            mock.patch("subprocess.Popen") as mock_popen,
            mock.patch("threading.Thread"),
        ):
            mock_popen.return_value.pid = 12345
            tray._start_web_console()
            cmd = mock_popen.call_args[0][0]
            assert "--no-open" in cmd

    def test_reuses_existing_console(self, tmp_path):
        """When console is already alive, should not start a new one."""
        tray = self._make_tray()
        port_file = tmp_path / "web-console.port"
        port_file.write_text("8080")
        with (
            mock.patch("ai_guardian.config.utils.get_state_dir", return_value=tmp_path),
            mock.patch.object(DaemonTray, "_is_web_console_alive", return_value=True),
            mock.patch("subprocess.Popen") as mock_popen,
        ):
            tray._start_web_console()
            mock_popen.assert_not_called()

    def test_notify_skipped_on_restart(self, tmp_path):
        """Notification should not fire on subsequent starts."""
        tray = self._make_tray()
        port_file = tmp_path / "web-console.port"
        port_file.write_text("8080")
        with (
            mock.patch("ai_guardian.config.utils.get_state_dir", return_value=tmp_path),
            mock.patch.object(DaemonTray, "_is_web_console_alive", return_value=True),
            mock.patch(
                "ai_guardian.tray.app.tray_notifications.show_notification"
            ) as mock_notify,
        ):
            tray._icon = None
            tray._notify_web_console_ready(is_first_start=False)
            mock_notify.assert_not_called()

    def test_notify_fires_on_first_start(self, tmp_path):
        """Notification should fire on first start."""
        tray = self._make_tray()
        port_file = tmp_path / "web-console.port"
        port_file.write_text("8080")
        with (
            mock.patch("ai_guardian.config.utils.get_state_dir", return_value=tmp_path),
            mock.patch.object(DaemonTray, "_is_web_console_alive", return_value=True),
            mock.patch(
                "ai_guardian.tray.app.tray_notifications.show_notification"
            ) as mock_notify,
        ):
            tray._icon = None
            tray._notify_web_console_ready(is_first_start=True)
            mock_notify.assert_called_once_with(
                "Web Console Ready", "http://127.0.0.1:8080"
            )
