"""Explicit About links: no live windows, browsers or network requests."""

import json
import subprocess
import sys
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_guardian.tray import dialog_placement, plugins

PROFILE_URL = "https://github.com/itdove"
AUTHOR_LINE = "Author: Dominique Vernier (ITDoVe)"
LINKS = (("(ITDoVe)", PROFILE_URL),)


@pytest.fixture
def native_about(monkeypatch):
    """Build the real dialog against inert widgets, including queued WM callbacks."""
    root = Mock()
    ttk = SimpleNamespace(Frame=Mock(), Label=Mock(), Button=Mock())
    tk = SimpleNamespace(Tk=Mock(return_value=root), ttk=ttk, TclError=RuntimeError)
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setattr("ai_guardian.ui.display._ensure_tcl_library", lambda: None)
    monkeypatch.setattr(dialog_placement, "_place_window_on_screen", Mock())
    return root


@pytest.mark.parametrize("system", ["Linux", "Darwin", "Windows"])
def test_about_links_use_an_isolated_tk_dialog_when_available(monkeypatch, system):
    monkeypatch.setattr(plugins.platform, "system", lambda: system)
    monkeypatch.setattr("ai_guardian.ui.display.get_preferred_ui", lambda: "auto")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    show = Mock(return_value=True)
    monkeypatch.setattr(dialog_placement, "show_tkinter_message_subprocess", show)
    assert plugins.show_dialog("About AI Guardian", AUTHOR_LINE, links=LINKS)
    show.assert_called_once_with(
        "About AI Guardian", AUTHOR_LINE, screen_bounds=None, links=LINKS
    )


@pytest.mark.parametrize("tk_available", [False, True])
def test_unavailable_tk_keeps_clickable_about_in_the_browser_tier(
    monkeypatch, tk_available
):
    monkeypatch.setattr(plugins.platform, "system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display.get_preferred_ui", lambda: "auto")
    monkeypatch.setattr(
        "ai_guardian.ui.display._tkinter_available", lambda: tk_available
    )
    show = Mock(return_value=None)
    monkeypatch.setattr(dialog_placement, "show_tkinter_message_subprocess", show)
    monkeypatch.setattr(plugins, "_find_icon", lambda *args: None)
    monkeypatch.setattr(
        plugins, "_linux_dialog_provider_order", lambda: ("zenity", "kdialog")
    )
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("subprocess.run", run)
    browser = Mock()
    monkeypatch.setattr("webbrowser.open", browser)
    assert plugins.show_dialog("About AI Guardian", AUTHOR_LINE, links=LINKS)
    payload = json.loads(run.call_args.args[0][-1])
    assert payload["message"] == AUTHOR_LINE
    assert payload["links"] == [["(ITDoVe)", PROFILE_URL]]
    assert "_show_nicegui_message" in run.call_args.args[0][2]
    assert show.called is tk_available
    browser.assert_not_called()


def test_headless_about_links_do_not_launch_any_ui_or_browser(monkeypatch):
    monkeypatch.setattr("ai_guardian.ui.display.get_preferred_ui", lambda: "headless")
    show = Mock()
    monkeypatch.setattr(dialog_placement, "show_tkinter_message_subprocess", show)
    browser = Mock()
    monkeypatch.setattr("webbrowser.open", browser)
    assert plugins.show_dialog("About AI Guardian", AUTHOR_LINE, links=LINKS) is False
    show.assert_not_called()
    browser.assert_not_called()


def test_author_link_is_transferred_to_the_tk_child_without_a_shell(monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(dialog_placement.subprocess, "run", run)
    assert dialog_placement.show_tkinter_message_subprocess(
        "About AI Guardian", AUTHOR_LINE, links=LINKS
    )
    payload = json.loads(run.call_args.args[0][-1])
    assert payload["message"] == AUTHOR_LINE
    assert payload["links"] == [["(ITDoVe)", PROFILE_URL]]
    assert PROFILE_URL not in payload["message"]
    assert "links=p.get('links', ())" in run.call_args.args[0][2]
    assert run.call_args.kwargs.get("shell", False) is False


def test_tk_message_has_no_user_reading_deadline(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(dialog_placement.subprocess, "run", run)

    assert dialog_placement.show_tkinter_message_subprocess("About", AUTHOR_LINE)

    assert run.call_args.kwargs["timeout"] is None


@pytest.mark.parametrize(
    ("stdout", "expected", "stage"),
    [
        ("", None, "before display"),
        ("ai-guardian-message-ready\n", False, "after display"),
    ],
)
def test_tk_failure_allows_fallback_only_before_mapping(
    monkeypatch, caplog, stdout, expected, stage
):
    run = Mock(return_value=subprocess.CompletedProcess([], 1, stdout, AUTHOR_LINE))
    monkeypatch.setattr(dialog_placement.subprocess, "run", run)

    with caplog.at_level("DEBUG", logger=dialog_placement.__name__):
        assert (
            dialog_placement.show_tkinter_message_subprocess("About", AUTHOR_LINE)
            is expected
        )

    assert stage in caplog.text
    assert AUTHOR_LINE not in caplog.text


def test_tk_launch_error_allows_fallback_without_logging_the_payload(
    monkeypatch, caplog
):
    run = Mock(side_effect=OSError(AUTHOR_LINE))
    monkeypatch.setattr(dialog_placement.subprocess, "run", run)

    with caplog.at_level("DEBUG", logger=dialog_placement.__name__):
        assert (
            dialog_placement.show_tkinter_message_subprocess("About", AUTHOR_LINE)
            is None
        )

    assert "OSError" in caplog.text
    assert AUTHOR_LINE not in caplog.text


@pytest.mark.parametrize("stdout", ["", "ai-guardian-message-ready\n"])
def test_interrupted_tk_wait_never_opens_a_native_replacement(
    monkeypatch, caplog, stdout
):
    monkeypatch.setattr(plugins.platform, "system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display.get_preferred_ui", lambda: "auto")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    run = Mock(
        side_effect=subprocess.TimeoutExpired(
            AUTHOR_LINE, 3600, output=stdout, stderr=AUTHOR_LINE
        )
    )
    monkeypatch.setattr(dialog_placement.subprocess, "run", run)

    with caplog.at_level("DEBUG", logger=dialog_placement.__name__):
        assert plugins.show_dialog("About", AUTHOR_LINE, links=LINKS) is False

    run.assert_called_once()
    assert "interrupted" in caplog.text
    assert AUTHOR_LINE not in caplog.text


def test_tk_reports_readiness_once_and_only_when_the_completed_root_maps(native_about):
    root = native_about
    ready = Mock()
    dialog_placement._show_tkinter_message("About", AUTHOR_LINE, on_ready=ready)
    ready.assert_not_called()
    bindings = {call.args[0]: call.args[1] for call in root.bind.call_args_list}
    bindings["<Map>"](SimpleNamespace(widget=Mock()))
    ready.assert_not_called()
    bindings["<Map>"](SimpleNamespace(widget=root))
    bindings["<Map>"](SimpleNamespace(widget=root))
    ready.assert_called_once_with()
    calls = [call[0] for call in root.mock_calls]
    assert calls.index("bind") < calls.index("deiconify")


def test_tk_child_command_connects_mapping_to_the_captured_readiness_marker(
    monkeypatch, native_about
):
    """Execute the real child command against inert widgets, never a display."""
    root = native_about

    def mainloop():
        bindings = {call.args[0]: call.args[1] for call in root.bind.call_args_list}
        bindings["<Map>"](SimpleNamespace(widget=root))
        bindings["<Map>"](SimpleNamespace(widget=root))

    root.mainloop.side_effect = mainloop
    captured = []

    def run(command, **kwargs):
        output = StringIO()
        with monkeypatch.context() as child, redirect_stdout(output):
            child.setattr(sys, "argv", ["-c", command[-1]])
            exec(command[2], {})
        captured.append(output.getvalue())
        return subprocess.CompletedProcess(command, 0, output.getvalue(), "")

    monkeypatch.setattr(dialog_placement.subprocess, "run", run)

    assert dialog_placement.show_tkinter_message_subprocess(
        "About", AUTHOR_LINE, links=LINKS
    )
    assert captured == ["ai-guardian-message-ready\n"]
    root.title.assert_called_once_with("About")


@pytest.mark.parametrize("event", ["<Button-1>", "<Return>", "<space>"])
def test_author_profile_opens_only_on_click_or_keyboard_activation(monkeypatch, event):
    root = Mock()
    labels = []

    def label(*args, **kwargs):
        widget = Mock()
        labels.append((kwargs["text"], widget))
        return widget

    ttk = SimpleNamespace(Frame=Mock(), Label=label, Button=Mock())
    tk = SimpleNamespace(Tk=Mock(return_value=root), ttk=ttk, TclError=RuntimeError)
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setattr("ai_guardian.ui.display._ensure_tcl_library", lambda: None)
    monkeypatch.setattr(dialog_placement, "_place_window_on_screen", Mock())
    browser = Mock()
    monkeypatch.setattr("webbrowser.open", browser)
    message = (
        f"AI Guardian vtest\n{AUTHOR_LINE}\nhttps://example.com/not-a-requested-link"
    )
    dialog_placement._show_tkinter_message("About AI Guardian", message, links=LINKS)
    browser.assert_not_called()
    author = next(widget for text, widget in labels if text == AUTHOR_LINE)
    author.configure.assert_called_with(
        foreground="#2563eb", cursor="hand2", takefocus=True
    )
    bindings = {call.args[0]: call.args[1] for call in author.bind.call_args_list}
    bindings[event](None)
    browser.assert_called_once_with(PROFILE_URL)
    for text, widget in labels:
        if text != AUTHOR_LINE:
            widget.bind.assert_not_called()


def test_about_maps_finished_layout_before_requesting_focus_and_modal_grab(
    native_about,
):
    root = native_about
    dialog_placement._show_tkinter_message(
        "About AI Guardian", AUTHOR_LINE, links=LINKS
    )
    root.withdraw.assert_called_once()
    root.deiconify.assert_called_once()
    root.focus_force.assert_not_called()
    root.grab_set.assert_not_called()
    calls = [call[0] for call in root.mock_calls]
    assert (
        calls.index("withdraw")
        < calls.index("update_idletasks")
        < calls.index("deiconify")
        < calls.index("after_idle")
        < calls.index("mainloop")
    )
    root.after_idle.call_args.args[0]()
    root.focus_force.assert_called_once()
    root.grab_set.assert_called_once()


def test_about_restores_foreground_after_releasing_the_temporary_topmost_hint(
    native_about,
):
    root = native_about
    dialog_placement._show_tkinter_message(
        "About AI Guardian", AUTHOR_LINE, links=LINKS
    )
    root.attributes.assert_called_with("-topmost", True)
    delay, finish_startup = root.after.call_args.args
    assert delay == 200
    root.reset_mock()
    finish_startup()
    assert [call[0] for call in root.mock_calls] == [
        "winfo_exists",
        "attributes",
        "winfo_exists",
        "deiconify",
        "lift",
        "focus_force",
        "grab_set",
    ]
    root.attributes.assert_called_once_with("-topmost", False)
    # One-shot callbacks, not a loop that steals focus when the user switches away.
    root.after.assert_not_called()
    root.after_idle.assert_not_called()


def test_about_still_requests_foreground_when_the_wm_rejects_topmost(native_about):
    root = native_about
    root.attributes.side_effect = RuntimeError("Unsupported raising hint")
    dialog_placement._show_tkinter_message(
        "About AI Guardian", AUTHOR_LINE, links=LINKS
    )
    root.deiconify.assert_called_once()
    root.after_idle.call_args.args[0]()
    root.after.call_args.args[1]()
    assert root.focus_force.call_count == 2
    assert root.grab_set.call_count == 2


def test_about_startup_callbacks_ignore_a_window_closed_before_they_run(native_about):
    root = native_about
    dialog_placement._show_tkinter_message(
        "About AI Guardian", AUTHOR_LINE, links=LINKS
    )
    focus = root.after_idle.call_args.args[0]
    finish_startup = root.after.call_args.args[1]
    root.reset_mock()
    root.winfo_exists.return_value = False
    focus()
    finish_startup()
    root.deiconify.assert_not_called()
    root.lift.assert_not_called()
    root.focus_force.assert_not_called()
    root.grab_set.assert_not_called()
    root.attributes.assert_not_called()


def test_about_startup_tolerates_a_window_closed_during_a_focus_request(native_about):
    root = native_about
    root.focus_force.side_effect = RuntimeError("Window closed")
    dialog_placement._show_tkinter_message(
        "About AI Guardian", AUTHOR_LINE, links=LINKS
    )
    root.after_idle.call_args.args[0]()
    root.after.call_args.args[1]()
    root.mainloop.assert_called_once()
