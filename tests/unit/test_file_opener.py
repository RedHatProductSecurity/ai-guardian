"""Tests for ai_guardian.ui.file_opener — open files in preferred editor."""

from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.ui.file_opener import _build_editor_command, open_in_editor


class TestBuildEditorCommand:
    """Tests for _build_editor_command()."""

    @patch("ai_guardian.ui.file_opener.shutil.which")
    def test_vscode_with_line_number(self, mock_which):
        mock_which.side_effect = lambda x: "/usr/bin/code" if x == "code" else None
        cmd, name = _build_editor_command("/tmp/test.py", 42)
        assert cmd == ["code", "--goto", "/tmp/test.py:42"]
        assert name == "VS Code"

    @patch("ai_guardian.ui.file_opener.shutil.which")
    def test_vscode_without_line_number(self, mock_which):
        mock_which.side_effect = lambda x: "/usr/bin/code" if x == "code" else None
        cmd, name = _build_editor_command("/tmp/test.py")
        assert cmd == ["code", "--goto", "/tmp/test.py:1"]
        assert name == "VS Code"

    @patch("ai_guardian.ui.file_opener.shutil.which")
    def test_cursor_when_no_vscode(self, mock_which):
        mock_which.side_effect = lambda x: "/usr/bin/cursor" if x == "cursor" else None
        cmd, name = _build_editor_command("/tmp/test.py", 10)
        assert cmd == ["cursor", "--goto", "/tmp/test.py:10"]
        assert name == "Cursor"

    @patch("ai_guardian.ui.file_opener.shutil.which")
    def test_vscode_preferred_over_cursor(self, mock_which):
        mock_which.side_effect = lambda x: (
            f"/usr/bin/{x}" if x in ("code", "cursor") else None
        )
        cmd, name = _build_editor_command("/tmp/test.py", 5)
        assert cmd == ["code", "--goto", "/tmp/test.py:5"]
        assert name == "VS Code"

    @patch("ai_guardian.ui.file_opener.platform.system", return_value="Darwin")
    @patch("ai_guardian.ui.file_opener.shutil.which", return_value=None)
    def test_macos_fallback(self, _mock_which, _mock_system):
        cmd, name = _build_editor_command("/tmp/test.py", 42)
        assert cmd == ["open", "/tmp/test.py"]
        assert name == "system default"

    @patch("ai_guardian.ui.file_opener.platform.system", return_value="Linux")
    @patch("ai_guardian.ui.file_opener.shutil.which", return_value=None)
    def test_linux_fallback(self, _mock_which, _mock_system):
        cmd, name = _build_editor_command("/tmp/test.py", 42)
        assert cmd == ["xdg-open", "/tmp/test.py"]
        assert name == "system default"

    @patch("ai_guardian.ui.file_opener.platform.system", return_value="Windows")
    @patch("ai_guardian.ui.file_opener.shutil.which", return_value=None)
    def test_windows_fallback(self, _mock_which, _mock_system):
        cmd, name = _build_editor_command("/tmp/test.py", 42)
        assert isinstance(cmd, str)
        assert "test.py" in cmd
        assert name == "system default"

    @patch("ai_guardian.ui.file_opener.platform.system", return_value="FreeBSD")
    @patch("ai_guardian.ui.file_opener.shutil.which", return_value=None)
    def test_unsupported_platform_raises(self, _mock_which, _mock_system):
        with pytest.raises(OSError, match="Unsupported platform"):
            _build_editor_command("/tmp/test.py")


class TestOpenInEditor:
    """Tests for open_in_editor()."""

    @patch("ai_guardian.ui.file_opener.subprocess.Popen")
    @patch("ai_guardian.ui.file_opener.shutil.which")
    def test_success_returns_true(self, mock_which, mock_popen):
        mock_which.side_effect = lambda x: "/usr/bin/code" if x == "code" else None
        mock_popen.return_value = MagicMock()
        success, editor = open_in_editor("/tmp/test.py", 42)
        assert success is True
        assert editor == "VS Code"
        mock_popen.assert_called_once()

    @patch("ai_guardian.ui.file_opener.subprocess.Popen", side_effect=FileNotFoundError)
    @patch("ai_guardian.ui.file_opener.shutil.which")
    def test_popen_failure_returns_false(self, mock_which, _mock_popen):
        mock_which.side_effect = lambda x: "/usr/bin/code" if x == "code" else None
        success, editor = open_in_editor("/tmp/test.py", 42)
        assert success is False
        assert editor == ""

    @patch("ai_guardian.ui.file_opener.platform.system", return_value="FreeBSD")
    @patch("ai_guardian.ui.file_opener.shutil.which", return_value=None)
    def test_unsupported_platform_returns_false(self, _mock_which, _mock_system):
        success, editor = open_in_editor("/tmp/test.py")
        assert success is False
        assert editor == ""

    @patch("ai_guardian.ui.file_opener.subprocess.Popen")
    @patch("ai_guardian.ui.file_opener.shutil.which")
    def test_popen_called_non_blocking(self, mock_which, mock_popen):
        mock_which.side_effect = lambda x: "/usr/bin/code" if x == "code" else None
        mock_popen.return_value = MagicMock()
        open_in_editor("/tmp/test.py", 10)
        import subprocess

        call_kwargs = mock_popen.call_args
        assert call_kwargs.kwargs.get("stdin") == subprocess.DEVNULL
        assert call_kwargs.kwargs.get("stdout") == subprocess.DEVNULL
        assert call_kwargs.kwargs.get("stderr") == subprocess.DEVNULL
