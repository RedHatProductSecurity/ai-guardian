"""Explicit About links: no live windows, browsers or network requests."""

import json
import sys
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
def test_unavailable_tk_keeps_the_native_about_message_and_compact_attribution(
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
    assert AUTHOR_LINE in run.call_args.args[0]
    assert PROFILE_URL not in run.call_args.args[0]
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
