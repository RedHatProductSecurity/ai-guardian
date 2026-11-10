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


def test_tray_tk_modal_handoff_restores_foreground_once():
    """USER EXPERIENCE: Tray menu closes -> Tk dialogs stay usable, not topmost.

    This handoff covers Tk-rendered messages/results, plugin and SSH forms,
    proactive prompts and snooze steps, Pause, and sandbox forms/logs/progress/
    confirmations. Support review has its own isolated renderer with the same
    one-shot timing. Native OS dialogs and browser windows keep their provider
    behavior; cancellation and fallback remain covered by the contracts below.
    """
    from types import SimpleNamespace

    from ai_guardian.ui.modal import present_tk_window

    state = {"visible": False, "foreground": False, "topmost": False}
    root = Mock()
    root.winfo_exists.return_value = True
    callbacks = {}
    root.attributes.side_effect = lambda name, value: state.update({"topmost": value})
    root.deiconify.side_effect = lambda: state.update(visible=True)
    root.lift.side_effect = lambda: state.update(visible=True)
    root.focus_force.side_effect = lambda: state.update(foreground=True)
    root.after_idle.side_effect = lambda callback: callbacks.setdefault(
        "idle", callback
    )
    root.after.side_effect = lambda delay, callback: callbacks.setdefault(
        delay, callback
    )
    tk = SimpleNamespace(TclError=type("TclError", (Exception,), {}))

    present_tk_window(root, tk)
    callbacks["idle"]()
    assert state == {"visible": True, "foreground": True, "topmost": True}

    # The tray menu closes and KDE changes stacking; one delayed restore recovers it.
    state["foreground"] = False
    callbacks[200]()
    assert state == {"visible": True, "foreground": True, "topmost": False}
    assert root.focus_force.call_count == 2
    assert root.after.call_count == 1

    # The user can switch away; no repeating callback steals focus again.
    state["foreground"] = False
    assert root.focus_force.call_count == 2


@pytest.mark.parametrize(
    ("preference", "chosen_provider"),
    [("auto", "tkinter"), ("tkinter", "tkinter"), ("nicegui", "nicegui")],
)
def test_sandbox_deletion_uses_copy_capable_providers_and_honors_preference(
    monkeypatch, preference, chosen_provider
):
    """USER EXPERIENCE: Deletion presents Copy in each eligible provider.

    Native single-field prompts are not eligible for this complete interaction.
    Copy-capable form providers preserve exclusive preferences and cancellation.
    """
    from ai_guardian.ui.display import ui_provider_order

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", preference)
    monkeypatch.setattr("ai_guardian.ui.display.platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)

    providers = ui_provider_order("form")
    assert "native" not in providers
    assert providers[0] == chosen_provider

    with (
        patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_confirmation_subprocess",
            return_value=False,
        ) as tkinter,
        patch(
            "ai_guardian.tray.sandbox_dialog._show_nicegui_confirmation",
            return_value=False,
        ) as nicegui,
        patch("ai_guardian.tray.sandbox_dialog._show_native_confirmation") as native,
    ):
        assert (
            sandbox_dialog.show_sandbox_confirmation("random-sandbox-name", "container")
            is False
        )

    assert tkinter.call_count == int(chosen_provider == "tkinter")
    assert nicegui.call_count == int(chosen_provider == "nicegui")
    native.assert_not_called()


def test_sandbox_deletion_advances_after_proven_tk_startup_failure():
    """USER EXPERIENCE: Only a pre-display Tk failure opens the next provider."""
    from ai_guardian.ui.modal import UIUnavailable

    with (
        patch(
            "ai_guardian.ui.modal.ui_provider_order",
            return_value=("tkinter", "nicegui"),
        ),
        patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_confirmation_subprocess",
            side_effect=UIUnavailable("Tk did not start"),
        ) as tkinter,
        patch(
            "ai_guardian.tray.sandbox_dialog._show_nicegui_confirmation",
            return_value=False,
        ) as nicegui,
    ):
        assert (
            sandbox_dialog.show_sandbox_confirmation("exact-name", "container") is False
        )

    tkinter.assert_called_once()
    nicegui.assert_called_once_with(
        "Delete AI Guardian sandbox",
        "Permanently delete sandbox 'exact-name' (container)?\n\n"
        "The runtime sandbox will be removed. Saved host configuration snapshots are kept.",
        "Delete sandbox",
        expected_text="exact-name",
    )


@pytest.mark.parametrize("outcome", ["cancel", "post-display failure"])
def test_sandbox_deletion_cancel_or_visible_failure_never_reopens(
    outcome,
):
    """USER EXPERIENCE: Cancel/visible failure is terminal, never a second prompt."""
    from ai_guardian.ui.modal import UIUnavailable, mark_modal_displayed

    def tkinter_result():
        if outcome == "post-display failure":
            mark_modal_displayed()
            raise UIUnavailable("Tk failed after display")
        return False

    with (
        patch(
            "ai_guardian.ui.modal.ui_provider_order",
            return_value=("tkinter", "nicegui"),
        ),
        patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_confirmation_subprocess",
            side_effect=tkinter_result,
        ) as tkinter,
        patch("ai_guardian.tray.sandbox_dialog._show_nicegui_confirmation") as nicegui,
    ):
        assert (
            sandbox_dialog.show_sandbox_confirmation("exact-name", "container") is False
        )

    tkinter.assert_called_once()
    nicegui.assert_not_called()


@pytest.mark.parametrize(
    ("clipboard_result", "expected_message", "expected_type"),
    [
        (True, "Sandbox name copied to clipboard.", "positive"),
        (
            False,
            "Could not copy sandbox name; check browser clipboard permissions or copy it manually.",
            "negative",
        ),
    ],
)
def test_sandbox_browser_copy_feedback_does_not_confirm_or_close(
    monkeypatch, clipboard_result, expected_message, expected_type
):
    """USER EXPERIENCE: Copy gives truthful feedback and leaves deletion pending."""
    import asyncio
    import sys
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    buttons = {}
    labels = []
    inputs = []
    pages = []

    class Widget:
        value = ""

        def classes(self, *_args, **_kwargs):
            return self

        def style(self, *_args, **_kwargs):
            return self

        def props(self, *_args, **_kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def register_page(_path):
        def decorate(callback):
            pages.append(callback)
            return callback

        return decorate

    def add_button(label, *, on_click, **_kwargs):
        buttons[label] = on_click
        return Widget()

    ui = SimpleNamespace(
        page=register_page,
        card=Widget,
        row=Widget,
        label=lambda text: labels.append(text) or Widget(),
        input=lambda **kwargs: inputs.append(kwargs) or Widget(),
        button=add_button,
        run_javascript=AsyncMock(return_value=clipboard_result),
        notify=Mock(),
        timer=Mock(),
    )
    app = SimpleNamespace(shutdown=Mock())
    monkeypatch.setitem(sys.modules, "nicegui", SimpleNamespace(app=app, ui=ui))

    def display_page(*_args, **_kwargs):
        pages[0]()

    monkeypatch.setattr(sandbox_dialog, "run_nicegui_modal", display_page)
    name = 'sandbox / "random"'

    result = sandbox_dialog._render_nicegui_confirmation(
        "Delete sandbox",
        f"Permanently delete '{name}'?",
        "Delete sandbox",
        expected_text=name,
    )
    asyncio.run(buttons["Copy"]())

    assert result is False
    assert "Sandbox name to copy:" in labels
    assert name in labels
    assert inputs == [{"label": f"Type {name} to confirm"}]
    assert "Delete sandbox" in buttons
    assert "Cancel" in buttons
    ui.run_javascript.assert_awaited_once()
    ui.notify.assert_called_once_with(expected_message, type=expected_type)
    ui.timer.assert_not_called()
    app.shutdown.assert_not_called()


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
        root.after_idle.call_args.args[0]()
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
    assert root.lift.call_count == 3
    assert root.focus_force.call_count == 2
    root.after.assert_called_once()
    root.destroy.assert_called_once()


def test_conditional_required_consent_blocks_only_the_matching_cli(monkeypatch):
    """USER EXPERIENCE: Codex stays usable; Claude requires explicit TOS consent.

    Manual check: open Create sandbox with Codex selected and verify submission is
    available. Select Claude and verify submission stays disabled until its terms
    checkbox is selected. Switch back to Codex and verify the consent is cleared
    and the form can be submitted.
    """
    import sys
    from types import ModuleType

    class TracedVariable:
        def __init__(self, value):
            self.value = value
            self.callbacks = []

        def get(self):
            return self.value

        def set(self, value):
            self.value = value
            for callback in self.callbacks:
                callback()

        def trace_add(self, _mode, callback):
            self.callbacks.append(callback)

    root = Mock()
    string_variables = []
    boolean_variables = []
    buttons = []
    tk = ModuleType("tkinter")
    tk.Tk = Mock(return_value=root)
    tk.Canvas = Mock(return_value=Mock())
    tk.Text = Mock(return_value=Mock())
    tk.TclError = type("TclError", (Exception,), {})
    tk.filedialog = ModuleType("tkinter.filedialog")

    def make_variable(value, collection):
        variable = TracedVariable(value)
        collection.append(variable)
        return variable

    tk.StringVar = Mock(
        side_effect=lambda value="", **_kwargs: make_variable(value, string_variables)
    )
    tk.BooleanVar = Mock(
        side_effect=lambda value=False, **_kwargs: make_variable(
            value, boolean_variables
        )
    )
    ttk = ModuleType("tkinter.ttk")

    def make_button(*_args, **_kwargs):
        button = Mock()
        buttons.append(button)
        return button

    for name in (
        "Button",
        "Checkbutton",
        "Combobox",
        "Entry",
        "Frame",
        "Label",
        "Scrollbar",
    ):
        setattr(
            ttk, name, make_button if name == "Button" else Mock(return_value=Mock())
        )
    tk.ttk = ttk

    def exercise_submit_gate():
        submit = buttons[-1]
        assert submit.state.call_args_list == [call(["!disabled"])]
        string_variables[0].set("claude")
        assert submit.state.call_args_list[-1] == call(["disabled"])
        boolean_variables[0].set(True)
        assert submit.state.call_args_list[-1] == call(["!disabled"])
        string_variables[0].set("codex")
        assert boolean_variables[0].get() is False
        assert submit.state.call_args_list[-1] == call(["!disabled"])

    root.mainloop.side_effect = exercise_submit_gate
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", tk.filedialog)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setattr("ai_guardian.ui.display._ensure_tcl_library", lambda: None)
    monkeypatch.setattr(sandbox_dialog, "_place_window_on_screen", Mock())
    monkeypatch.setattr(sandbox_dialog, "_present_tk_sandbox_form", Mock())

    result = sandbox_dialog._show_tkinter_form(
        "Create sandbox",
        "Select a CLI and confirm its terms when required",
        [
            {
                "name": "cli",
                "type": "choice",
                "choices": ("codex", "claude"),
                "default": "codex",
            },
            {
                "name": "accept_claude_tos",
                "label": "Accept Claude terms",
                "type": "bool",
                "default": False,
                "required": True,
                "enabled_when": {"field": "cli", "values": ("claude",)},
                "clear_when_disabled": True,
            },
        ],
        submit_label="Create sandbox",
    )

    assert result is None


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
