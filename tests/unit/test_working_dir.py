"""Tests for per-daemon working directory state (issue #792)."""

import json
import os
import stat
import sys
from pathlib import Path
from unittest import mock

import pytest

from ai_guardian.daemon.working_dir import (
    choose_directory,
    get_working_dir,
    load_working_dirs,
    save_working_dirs,
    set_working_dir,
    shorten_path,
)


@pytest.fixture
def state_dir(tmp_path):
    """Patch get_state_dir to use a temp directory."""
    with mock.patch(
        "ai_guardian.daemon.working_dir.get_state_dir",
        return_value=tmp_path,
    ):
        yield tmp_path


class TestLoadWorkingDirs:
    def test_returns_empty_when_no_file(self, state_dir):
        assert load_working_dirs() == {}

    def test_returns_persisted_data(self, state_dir):
        data = {"my-daemon": "/home/user/project"}
        (state_dir / "working_dir.json").write_text(json.dumps(data))
        assert load_working_dirs() == data

    def test_malformed_json_returns_empty(self, state_dir):
        (state_dir / "working_dir.json").write_text("{bad json")
        assert load_working_dirs() == {}

    def test_non_dict_returns_empty(self, state_dir):
        (state_dir / "working_dir.json").write_text('"just a string"')
        assert load_working_dirs() == {}

    def test_filters_non_string_values(self, state_dir):
        data = {"good": "/path", "bad_val": 42, "bad_key_type": "/ok"}
        (state_dir / "working_dir.json").write_text(json.dumps(data))
        result = load_working_dirs()
        assert result["good"] == "/path"
        assert "bad_val" not in result

    def test_empty_file_returns_empty(self, state_dir):
        (state_dir / "working_dir.json").write_text("")
        assert load_working_dirs() == {}


class TestSaveWorkingDirs:
    def test_creates_file(self, state_dir):
        save_working_dirs({"daemon-a": "/home/user"})
        path = state_dir / "working_dir.json"
        assert path.exists()
        assert json.loads(path.read_text()) == {"daemon-a": "/home/user"}

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Unix file permissions not applicable on Windows",
    )
    def test_atomic_write_permissions(self, state_dir):
        save_working_dirs({"daemon-a": "/home/user"})
        path = state_dir / "working_dir.json"
        if hasattr(os, "fchmod"):
            mode = stat.S_IMODE(path.stat().st_mode)
            assert mode == (stat.S_IRUSR | stat.S_IWUSR)

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "deep" / "nested"
        with mock.patch(
            "ai_guardian.daemon.working_dir.get_state_dir",
            return_value=nested,
        ):
            save_working_dirs({"d": "/path"})
        assert (nested / "working_dir.json").exists()

    def test_overwrites_existing(self, state_dir):
        save_working_dirs({"a": "/first"})
        save_working_dirs({"a": "/second"})
        assert json.loads((state_dir / "working_dir.json").read_text()) == {
            "a": "/second"
        }


class TestGetWorkingDir:
    def test_returns_stored_dir(self, state_dir):
        (state_dir / "working_dir.json").write_text(
            json.dumps({"my-daemon": "/custom/path"})
        )
        assert get_working_dir("my-daemon") == "/custom/path"

    def test_defaults_to_home(self, state_dir):
        result = get_working_dir("unknown-daemon")
        assert result == str(Path.home())

    def test_defaults_to_home_when_no_file(self, state_dir):
        assert get_working_dir("any") == str(Path.home())


class TestSetWorkingDir:
    def test_set_and_get_roundtrip(self, state_dir):
        set_working_dir("daemon-x", "/my/project")
        assert get_working_dir("daemon-x") == "/my/project"

    def test_multiple_daemons_independent(self, state_dir):
        set_working_dir("daemon-a", "/path/a")
        set_working_dir("daemon-b", "/path/b")
        assert get_working_dir("daemon-a") == "/path/a"
        assert get_working_dir("daemon-b") == "/path/b"

    def test_update_existing(self, state_dir):
        set_working_dir("d", "/first")
        set_working_dir("d", "/second")
        assert get_working_dir("d") == "/second"


class TestShortenPath:
    def test_shortens_home(self):
        home = str(Path.home())
        assert shorten_path(home) == "~"

    def test_shortens_subdir(self):
        home = str(Path.home())
        path = os.path.join(home, "projects", "foo")
        result = shorten_path(path)
        assert result.startswith("~")
        assert "projects" in result
        assert "foo" in result

    def test_leaves_non_home_unchanged(self):
        assert shorten_path("/tmp/other") == "/tmp/other"

    def test_empty_string(self):
        assert shorten_path("") == ""


class TestChooseDirectory:
    @mock.patch("ai_guardian.daemon.working_dir.platform.system", return_value="Darwin")
    @mock.patch(
        "ai_guardian.daemon.working_dir._choose_directory_tkinter_subprocess",
        return_value=(True, "/Users/dev/secondary-project"),
    )
    def test_macos_tray_picker_uses_captured_screen_bounds(self, picker, _mock_sys):
        bounds = (1920, 37, 2560, 1380)
        result = choose_directory(
            "/Users/dev",
            screen_bounds=bounds,
        )

        assert result == "/Users/dev/secondary-project"
        picker.assert_called_once_with(
            "/Users/dev",
            "Choose Working Directory",
            bounds,
        )

    @mock.patch("ai_guardian.daemon.working_dir.platform.system", return_value="Darwin")
    @mock.patch("ai_guardian.daemon.working_dir.subprocess.run")
    def test_macos_returns_path(self, mock_run, _mock_sys):
        mock_run.return_value = mock.Mock(returncode=0, stdout="/Users/dev/project\n")
        result = choose_directory("/Users/dev")
        assert result == "/Users/dev/project"
        assert mock_run.called
        call_args = mock_run.call_args
        assert "osascript" in call_args[0][0]

    @mock.patch("ai_guardian.daemon.working_dir.platform.system", return_value="Darwin")
    @mock.patch("ai_guardian.daemon.working_dir.subprocess.run")
    def test_macos_cancel_returns_none(self, mock_run, _mock_sys):
        mock_run.return_value = mock.Mock(returncode=1, stdout="")
        result = choose_directory()
        assert result is None

    @mock.patch("ai_guardian.daemon.working_dir.platform.system", return_value="Linux")
    @mock.patch("ai_guardian.daemon.working_dir.subprocess.run")
    @mock.patch("ai_guardian.tray.plugins._find_icon", return_value="")
    def test_linux_returns_path(self, _icon, mock_run, _mock_sys):
        mock_run.return_value = mock.Mock(returncode=0, stdout="/home/user/project\n")
        result = choose_directory()
        assert result == "/home/user/project"

    @mock.patch("ai_guardian.daemon.working_dir.platform.system", return_value="Linux")
    @mock.patch("ai_guardian.daemon.working_dir.subprocess.run")
    @mock.patch("ai_guardian.tray.plugins._find_icon", return_value="")
    def test_linux_cancel_returns_none(self, _icon, mock_run, _mock_sys):
        mock_run.return_value = mock.Mock(returncode=1, stdout="")
        result = choose_directory()
        assert result is None

    @mock.patch(
        "ai_guardian.daemon.working_dir.platform.system", return_value="Windows"
    )
    @mock.patch("ai_guardian.daemon.working_dir.subprocess.run")
    def test_windows_returns_path(self, mock_run, _mock_sys):
        mock_run.return_value = mock.Mock(
            returncode=0, stdout="C:\\Users\\dev\\project\n"
        )
        result = choose_directory()
        assert result == "C:\\Users\\dev\\project"

    @mock.patch(
        "ai_guardian.daemon.working_dir.platform.system", return_value="FreeBSD"
    )
    def test_unsupported_returns_none(self, _mock_sys):
        assert choose_directory() is None

    @mock.patch("ai_guardian.daemon.working_dir.platform.system", return_value="Darwin")
    @mock.patch(
        "ai_guardian.daemon.working_dir.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_error_returns_none(self, _mock_run, _mock_sys):
        assert choose_directory() is None

    @mock.patch("ai_guardian.daemon.working_dir.platform.system", return_value="Darwin")
    @mock.patch("ai_guardian.daemon.working_dir.subprocess.run")
    def test_macos_with_current_dir(self, mock_run, _mock_sys):
        mock_run.return_value = mock.Mock(returncode=0, stdout="/new/path\n")
        choose_directory("/current/dir")
        call_args = mock_run.call_args[0][0]
        script = call_args[2]
        assert "default location" in script
        assert "/current/dir" in script


# Import lazy to keep test_working_dir focused
def _find_icon_patch():
    """Stub for _find_icon import in choose_directory Linux path."""
    return ""
