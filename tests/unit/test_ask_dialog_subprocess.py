"""Tests for the ask dialog's subprocess command resolution."""

from unittest import mock

from ai_guardian.tui.ask_dialog import AskViolationInfo, _show_via_subprocess


def test_ask_subprocess_uses_current_interpreter_not_path_ai_guardian(tmp_path):
    violation = AskViolationInfo(
        violation_type="test",
        summary="test summary",
        matched_text="test",
        config_section="",
    )
    process = mock.Mock(returncode=0)
    process.communicate.return_value = (None, b"")

    with (
        mock.patch("sys.executable", "/daemon/venv/bin/python"),
        mock.patch("tempfile.mkdtemp", return_value=str(tmp_path)),
        mock.patch("shutil.which", return_value="/old/bin/ai-guardian") as which,
        mock.patch("subprocess.Popen", return_value=process) as popen,
        mock.patch("shutil.rmtree"),
    ):
        result = _show_via_subprocess(violation, "block", timeout_seconds=1)

    assert result is None
    command = popen.call_args[0][0]
    assert command[:6] == [
        "/daemon/venv/bin/python",
        "-m",
        "ai_guardian",
        "prompt",
        "--mode",
        "ask",
    ]
    which.assert_not_called()
