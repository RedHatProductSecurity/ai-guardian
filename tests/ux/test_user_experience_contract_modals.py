"""Modal provider UX contract (#2580).

Manual verification: docs/MODAL_PROVIDERS.md contains the macOS/Linux/Windows
capability matrix and desktop/startup/post-map/monitor checks. These mocked
contracts do not qualify actual visual ordering or authorize a support upload.
"""

import subprocess
from unittest.mock import Mock, patch

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
