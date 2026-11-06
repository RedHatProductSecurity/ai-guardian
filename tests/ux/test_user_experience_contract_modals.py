"""Modal provider UX contract (#2580).

Manual verification: docs/MODAL_PROVIDERS.md contains the macOS/Linux/Windows
capability matrix and desktop/startup/post-map/monitor checks. These mocked
contracts do not qualify actual visual ordering or authorize a support upload.
"""

import subprocess
from unittest.mock import Mock, call, patch

import pytest

from ai_guardian.tray import sandbox_dialog
from ai_guardian.tray.plugins import show_dialog
from ai_guardian.tray.proactive_prompt import ProactivePromptDialog


@pytest.mark.parametrize("preference", ["tkinter", "nicegui"])
def test_explicit_message_preference_is_exclusive_even_on_failure(
    monkeypatch, preference
):
    """USER EXPERIENCE: Chosen UI cannot start → no surprise alternative toolkit."""
    from ai_guardian.ui.modal import UIUnavailable

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", preference)
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    with (
        patch("ai_guardian.tray.plugins._show_native_message") as native,
        patch(
            "ai_guardian.tray.dialog_placement.show_tkinter_message_subprocess",
            side_effect=UIUnavailable(),
        ) as tkinter,
        patch(
            "ai_guardian.tray.dialog_placement.show_nicegui_message_subprocess",
            side_effect=UIUnavailable(),
        ) as browser,
    ):
        assert show_dialog("Information", "Benign message") is False
    native.assert_not_called()
    assert tkinter.call_count == int(preference == "tkinter")
    assert browser.call_count == int(preference == "nicegui")


def test_headless_is_noninteractive_and_never_approves_a_mutation(monkeypatch):
    """USER EXPERIENCE: Headless → no desktop/browser, no deletion/upload/selection.

    Ask retains its configured security fallback; support retains its separate
    native-consent refusal. Neither permission model is changed by provider order.
    """
    from ai_guardian.daemon.working_dir import choose_directory
    from ai_guardian.ui.tray_target_selector import TrayTargetSelectorApp

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "headless")
    with (
        patch("subprocess.run") as child,
        patch("subprocess.Popen") as live,
        patch("webbrowser.open") as browser,
    ):
        assert show_dialog("Information", "Message") is False
        assert (
            ProactivePromptDialog("Action", "Message", "Go", "Cancel").show(
                tray_safe=True
            )
            == "dismiss"
        )
        assert sandbox_dialog.show_sandbox_form("Form", "Message", []) is None
        assert (
            sandbox_dialog.show_sandbox_confirmation("disposable", "container") is False
        )
        assert (
            sandbox_dialog.show_sandbox_upload_confirmation("Complete review") is False
        )
        assert (
            sandbox_dialog.show_sandbox_policy_confirmation("Complete policy") is False
        )
        assert sandbox_dialog.show_sandbox_log("Output", "Message", "Full log") is False
        assert choose_directory() is None
        assert TrayTargetSelectorApp([]).run() is None
        progress = sandbox_dialog.show_sandbox_progress("Progress", "Message")
        assert progress.finish(False, "Failed", "Full log") is False
    child.assert_not_called()
    live.assert_not_called()
    browser.assert_not_called()


def test_sandbox_create_form_restores_focus_after_kde_tray_menu_handoff(
    monkeypatch,
):
    """USER EXPERIENCE: KDE closes the tray menu -> Create sandbox stays usable.

    The Tk form receives one temporary raising hint and one delayed focus restore.
    Escape remains an ordinary cancellation and does not switch providers.
    Manual verification must record the KDE/Plasma version and X11/Wayland session;
    this mocked contract does not qualify actual desktop focus behavior.
    """
    import sys
    from types import SimpleNamespace

    root = Mock()
    root.winfo_exists.return_value = True
    ttk = SimpleNamespace(
        Button=Mock(return_value=Mock()),
        Combobox=Mock(return_value=Mock()),
        Frame=Mock(return_value=Mock()),
        Label=Mock(return_value=Mock()),
        Scrollbar=Mock(return_value=Mock()),
    )
    tk = SimpleNamespace(
        Canvas=Mock(return_value=Mock()),
        StringVar=Mock(return_value=Mock()),
        TclError=type("TclError", (Exception,), {}),
        filedialog=SimpleNamespace(),
        ttk=ttk,
    )

    def run_form():
        delay, restore_focus = root.after.call_args.args
        assert delay == 200
        restore_focus()
        escape = next(
            entry.args[1]
            for entry in root.bind.call_args_list
            if entry.args[0] == "<Escape>"
        )
        escape(None)

    root.mainloop.side_effect = run_form
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setattr(sandbox_dialog, "create_tk_root", lambda: root)
    monkeypatch.setattr(sandbox_dialog, "_place_window_on_screen", Mock())
    monkeypatch.setattr("ai_guardian.ui.display._ensure_tcl_library", lambda: None)

    result = sandbox_dialog._show_tkinter_form(
        "Create sandbox",
        "Choose a runtime",
        [
            {
                "name": "runtime",
                "type": "choice",
                "choices": ("container", "openshell"),
                "default": "container",
            }
        ],
    )

    assert result is None
    assert root.attributes.call_args_list == [
        call("-topmost", True),
        call("-topmost", False),
    ]
    assert root.lift.call_count == 2
    assert root.focus_force.call_count == 2
    root.after.assert_called_once()
    root.destroy.assert_called_once()


def test_sandbox_form_uses_only_the_next_provider_on_tk_startup_failure():
    """USER EXPERIENCE: Tk fails before display -> next eligible provider runs once."""
    from ai_guardian.ui.modal import UIUnavailable

    result = {"runtime": "container"}
    with (
        patch(
            "ai_guardian.ui.modal.ui_provider_order",
            return_value=("tkinter", "nicegui"),
        ) as order,
        patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess",
            side_effect=UIUnavailable("Tk did not start"),
        ) as tkinter,
        patch(
            "ai_guardian.tray.sandbox_dialog._show_nicegui_form",
            return_value=result,
        ) as browser,
    ):
        assert sandbox_dialog.show_sandbox_form("Create", "Choose", []) == result

    order.assert_called_once()
    tkinter.assert_called_once_with("Create", "Choose", [])
    browser.assert_called_once_with("Create", "Choose", [], screen_bounds=None)


@pytest.mark.parametrize("outcome", ["cancel", "post-display failure"])
def test_sandbox_form_cancel_or_post_display_failure_never_reopens_in_browser(
    outcome,
):
    """USER EXPERIENCE: Cancel or a visible Tk failure is terminal, not a retry."""
    from ai_guardian.ui.modal import UIUnavailable, mark_modal_displayed

    def tkinter_result():
        if outcome == "post-display failure":
            mark_modal_displayed()
            raise UIUnavailable("Tk failed after display")
        return None

    with (
        patch(
            "ai_guardian.ui.modal.ui_provider_order",
            return_value=("tkinter", "nicegui"),
        ),
        patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess",
            side_effect=tkinter_result,
        ) as tkinter,
        patch("ai_guardian.tray.sandbox_dialog._show_nicegui_form") as browser,
    ):
        assert sandbox_dialog.show_sandbox_form("Create", "Choose", []) is None

    tkinter.assert_called_once_with("Create", "Choose", [])
    browser.assert_not_called()


def test_sandbox_form_nicegui_provider_keeps_the_complete_field_payload():
    """USER EXPERIENCE: Explicit browser provider keeps the form and its result."""
    fields = [
        {
            "name": "policy_yaml",
            "type": "textarea",
            "default": "version: 1",
            "required": True,
        }
    ]
    result = {"policy_yaml": "version: 1"}
    with (
        patch(
            "ai_guardian.ui.modal.ui_provider_order", return_value=("nicegui",)
        ) as order,
        patch(
            "ai_guardian.tray.sandbox_dialog._show_nicegui_form",
            return_value=result,
        ) as browser,
        patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess"
        ) as tkinter,
    ):
        assert (
            sandbox_dialog.show_sandbox_form("Review policy", "Complete YAML", fields)
            == result
        )

    order.assert_called_once()
    browser.assert_called_once_with(
        "Review policy", "Complete YAML", fields, screen_bounds=None
    )
    tkinter.assert_not_called()


@pytest.mark.parametrize("returncode", [0, 1])
def test_native_dismissal_does_not_open_a_rich_replacement(monkeypatch, returncode):
    """USER EXPERIENCE: Read, then dismiss a native message → the action ends."""
    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    with (
        patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], returncode, "", ""),
        ) as native,
        patch(
            "ai_guardian.tray.dialog_placement.show_tkinter_message_subprocess"
        ) as tkinter,
        patch(
            "ai_guardian.tray.dialog_placement.show_nicegui_message_subprocess"
        ) as browser,
    ):
        assert show_dialog("Information", "Message")
    native.assert_called_once()
    assert native.call_args.kwargs["timeout"] is None
    tkinter.assert_not_called()
    browser.assert_not_called()


def test_snooze_step_failure_after_mapping_does_not_restart_the_setup_prompt(
    monkeypatch,
):
    """USER EXPERIENCE: Setup was visible → a failed Later step never changes UI.

    In two-step flows the safe result is the shortest snooze, not installation,
    and the original setup dialog is not reopened in a browser.
    """
    from types import SimpleNamespace
    from ai_guardian.ui.modal import UIUnavailable, create_tk_root
    import sys

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    root = Mock()
    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(Tk=lambda: root))
    monkeypatch.setattr("ai_guardian.ui.display._ensure_tcl_library", lambda: None)
    prompt = ProactivePromptDialog(
        "Setup",
        "Message",
        "Install",
        "Never",
        ide_choices=({"ide": "claude"},),
        two_step_snooze=True,
    )

    def first():
        create_tk_root()
        root.bind.call_args.args[1](SimpleNamespace(widget=root))
        raise UIUnavailable("Second step initialization failed")

    with (
        patch.object(prompt, "_show_ide_choices_tkinter", side_effect=first),
        patch.object(prompt, "_show_ide_choices_nicegui") as browser,
    ):
        assert prompt.show() == "snooze_1h"
    browser.assert_not_called()
