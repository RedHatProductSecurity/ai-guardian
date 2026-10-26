"""Modal lifecycle and real entry points, without visible desktop or network UI."""

import json
import subprocess
import sys
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from ai_guardian.ui.modal import (
    UIUnavailable,
    create_tk_root,
    run_modal,
    run_modal_child,
    run_modal_subprocess,
    run_native_command,
)


@pytest.fixture
def automatic(monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)


def test_mapped_tk_failure_never_changes_toolkit(automatic, monkeypatch):
    root = Mock()
    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(Tk=lambda: root))
    monkeypatch.setattr("ai_guardian.ui.display._ensure_tcl_library", lambda: None)

    def first():
        create_tk_root()
        root.bind.call_args.args[1](SimpleNamespace(widget=root))
        raise UIUnavailable("A later step failed")

    second = Mock()
    assert (
        run_modal("form", {"tkinter": first, "nicegui": second}, fallback=None) is None
    )
    second.assert_not_called()


@pytest.mark.parametrize("displayed", [False, True])
def test_isolated_child_reports_startup_only_before_mapping(
    displayed, monkeypatch, capsys
):
    root = Mock()
    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(Tk=lambda: root))
    monkeypatch.setattr("ai_guardian.ui.display._ensure_tcl_library", lambda: None)

    def fail():
        create_tk_root()
        if displayed:
            root.bind.call_args.args[1](SimpleNamespace(widget=root))
        raise RuntimeError("Private dialog contents")

    with pytest.raises(SystemExit):
        run_modal_child(fail)
    captured = capsys.readouterr()
    assert ("__AI_GUARDIAN_MODAL_UNAVAILABLE__" in captured.out) is not displayed
    assert "Private dialog contents" not in captured.out + captured.err


@pytest.mark.parametrize(
    "output,unavailable", [("__AI_GUARDIAN_MODAL_UNAVAILABLE__\n", True), ("", False)]
)
def test_child_exit_requires_an_explicit_startup_signal(output, unavailable):
    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 1, output, "private"),
    ):
        with pytest.raises(UIUnavailable if unavailable else RuntimeError):
            run_modal_subprocess(["unused"])


def test_child_interrupted_wait_is_not_unavailability():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("private", 1)):
        with pytest.raises(subprocess.TimeoutExpired):
            run_modal_subprocess(["unused"])


@pytest.mark.parametrize("failure", [FileNotFoundError(), OSError()])
def test_missing_child_executable_is_unavailable(failure):
    with patch("subprocess.run", side_effect=failure), pytest.raises(UIUnavailable):
        run_modal_subprocess(["unused"])


def test_native_unknown_failure_is_not_startup_proof():
    result = subprocess.CompletedProcess([], 1, "", "Unknown failure after display")
    with patch("subprocess.run", return_value=result):
        assert run_native_command(["unused"]) is result


@pytest.mark.parametrize(
    "error",
    [
        "cannot open display: :42",
        "(zenity:1234): Gtk-WARNING **: 12:34:56.789: cannot open display:",
        'qt.qpa.plugin: Could not load the Qt platform plugin "xcb"',
    ],
)
def test_known_native_initialization_failures_are_retryable(error):
    with (
        patch(
            "subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", error)
        ),
        pytest.raises(UIUnavailable),
    ):
        run_native_command(["unused"])


def test_unrelated_native_error_containing_display_words_is_terminal():
    result = subprocess.CompletedProcess(
        [], 1, "", "An unrelated exception quotes cannot open display in the text"
    )
    with patch("subprocess.run", return_value=result):
        assert run_native_command(["unused"]) is result


def test_message_missing_native_continues_to_tk_not_browser(automatic, monkeypatch):
    from ai_guardian.tray.plugins import show_dialog

    tkinter, browser = Mock(return_value=True), Mock()
    monkeypatch.setattr(
        "ai_guardian.tray.dialog_placement.show_tkinter_message_subprocess", tkinter
    )
    monkeypatch.setattr(
        "ai_guardian.tray.dialog_placement.show_nicegui_message_subprocess", browser
    )
    with patch("subprocess.run", side_effect=FileNotFoundError) as native:
        assert show_dialog("Title", "Message")
    assert native.call_count == 2
    tkinter.assert_called_once()
    browser.assert_not_called()


@pytest.mark.parametrize("value", [None, {"name": "chosen"}])
def test_sandbox_form_completion_or_cancellation_is_final(automatic, value):
    from ai_guardian.tray.sandbox_dialog import show_sandbox_form

    with (
        patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess",
            return_value=value,
        ),
        patch("ai_guardian.tray.sandbox_dialog._show_nicegui_form") as browser,
    ):
        assert show_sandbox_form("Title", "Message", []) == value
    browser.assert_not_called()


def test_sandbox_form_real_child_startup_failure_preserves_all_fields(automatic):
    from ai_guardian.tray.sandbox_dialog import show_sandbox_form

    fields = [{"name": "policy", "type": "textarea", "default": "complete policy"}]
    failed = subprocess.CompletedProcess(
        [], 1, "__AI_GUARDIAN_MODAL_UNAVAILABLE__\n", "private"
    )
    with (
        patch("subprocess.run", return_value=failed) as child,
        patch(
            "ai_guardian.tray.sandbox_dialog._show_nicegui_form",
            return_value={"policy": "edited"},
        ) as browser,
    ):
        assert show_sandbox_form("Review", "Message", fields) == {"policy": "edited"}
    browser.assert_called_once_with("Review", "Message", fields, screen_bounds=None)
    assert json.loads(child.call_args.args[0][-1])["fields"] == fields
    compile(child.call_args.args[0][2], "<child>", "exec")


@pytest.mark.parametrize("cancel", [False, True])
def test_delete_cancellation_stops_but_missing_native_advances(automatic, cancel):
    from ai_guardian.tray.sandbox_dialog import show_sandbox_confirmation

    with (
        patch(
            "ai_guardian.tray.sandbox_dialog._show_native_confirmation",
            return_value=False if cancel else None,
        ),
        patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_confirmation_subprocess",
            return_value=False,
        ) as tkinter,
        patch("ai_guardian.tray.sandbox_dialog._show_nicegui_confirmation") as browser,
    ):
        assert show_sandbox_confirmation("sandbox", "container") is False
    assert tkinter.call_count == int(not cancel)
    browser.assert_not_called()


def test_review_fallback_preserves_errors_and_explicit_approval(automatic):
    from ai_guardian.tray.sandbox_dialog import show_sandbox_upload_confirmation

    with (
        patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_upload_confirmation_subprocess",
            side_effect=UIUnavailable(),
        ),
        patch(
            "ai_guardian.tray.sandbox_dialog._show_nicegui_confirmation",
            return_value=False,
        ) as browser,
        patch("ai_guardian.tray.sandbox_dialog._show_native_confirmation") as native,
    ):
        assert (
            show_sandbox_upload_confirmation(
                "Full summary", error_lines=("Full error",)
            )
            is False
        )
    native.assert_not_called()
    browser.assert_called_once_with(
        "Confirm OpenShell repository upload",
        "Full summary",
        "Continue upload",
        error_lines=("Full error",),
    )


def test_log_fallback_keeps_the_entire_output(automatic):
    from ai_guardian.tray.sandbox_dialog import show_sandbox_log

    output = "benign log line\n" * 2000
    with (
        patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_log_subprocess",
            side_effect=UIUnavailable(),
        ),
        patch(
            "ai_guardian.tray.sandbox_dialog._show_nicegui_log", return_value=True
        ) as browser,
    ):
        assert show_sandbox_log("Output", "Message", output)
    browser.assert_called_once_with("Output", "Message", output)


def test_structured_proactive_startup_fallback_stays_isolated(automatic):
    from ai_guardian.tray.proactive_prompt import ProactivePromptDialog

    dialog = ProactivePromptDialog(
        "Setup", "Message", "Install", "Never", ide_choices=({"ide": "claude"},)
    )
    expected = {"result": "dismiss", "install": [], "never": []}
    with (
        patch(
            "subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(
                    [], 1, "__AI_GUARDIAN_MODAL_UNAVAILABLE__\n", ""
                ),
                subprocess.CompletedProcess([], 0, json.dumps(expected), ""),
            ],
        ) as child,
        patch.object(dialog, "_show_native_fallback") as native,
    ):
        assert dialog.show(tray_safe=True) == expected
    native.assert_not_called()
    assert len(child.call_args_list) == 2
    for call, toolkit in zip(child.call_args_list, ("tkinter", "nicegui")):
        assert "_show_ide_choices_" + toolkit in call.args[0][2]
        assert json.loads(call.args[0][-1])["ide_choices"] == [{"ide": "claude"}]
        compile(call.args[0][2], "<child>", "exec")


@pytest.mark.parametrize("completed", [False, True])
def test_parameter_form_real_tk_initialization_failure_only(automatic, completed):
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    tkinter = pytest.importorskip("tkinter", reason="Tkinter is optional")
    from ai_guardian.ui.tray_prompt import (
        TrayPromptApp,
        _NiceGuiPromptApp,
        _TkinterPromptApp,
    )

    with patch.object(_NiceGuiPromptApp, "run", return_value="chosen") as browser:
        if completed:
            with patch.object(_TkinterPromptApp, "run", return_value=None):
                assert TrayPromptApp([], "echo").run() is None
            browser.assert_not_called()
        else:
            with patch.object(
                tkinter, "Tk", side_effect=tkinter.TclError("No display")
            ):
                assert TrayPromptApp([], "echo").run() == "chosen"
            browser.assert_called_once()


@pytest.mark.parametrize("startup", [False, True])
def test_ask_cli_uses_fallback_not_a_second_prompt_after_completion(
    automatic, startup, capsys
):
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    from ai_guardian.cli_handlers import _handle_prompt_ask
    from ai_guardian.ui.ask_dialog import AskDecision, AskResult

    args = Namespace(
        violation='{"violation_type":"ssrf"}',
        fallback="block",
        timeout=30,
        output_file=None,
    )
    with (
        patch("ai_guardian.ui.ask_dialog._TkinterAskDialog") as tkinter,
        patch("ai_guardian.ui.ask_dialog._NiceGuiAskDialog") as browser,
    ):
        if startup:
            tkinter.return_value.run.side_effect = UIUnavailable()
        else:
            tkinter.return_value.run.return_value = None
        browser.return_value.run.return_value = AskResult(decision=AskDecision.BLOCK)
        assert _handle_prompt_ask(args) == 0
    assert browser.call_count == int(startup)
    assert json.loads(capsys.readouterr().out)["decision"] == "block"


@pytest.mark.parametrize("preference", ["auto", "nicegui", "tkinter", "headless"])
def test_target_selector_only_uses_its_complete_implementation(preference, monkeypatch):
    from ai_guardian.ui.tray_target_selector import TrayTargetSelectorApp

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", preference)
    app = TrayTargetSelectorApp([])
    with patch.object(app, "_run_nicegui", return_value="[0]") as browser:
        assert app.run() == ("[0]" if preference in {"auto", "nicegui"} else None)
    assert browser.call_count == int(preference in {"auto", "nicegui"})


@pytest.fixture
def browser_widgets(monkeypatch):
    """Render real browser functions against inert controls; never run a server."""
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

    class Element:
        def __init__(self, *args, **kwargs):
            self.args, self.kwargs = args, kwargs
            self.value = kwargs.get("value")
            self.events = {}
            self.classes = Mock(return_value=self)
            self.style = Mock(return_value=self)
            self.props = Mock(return_value=self)
            self.open = Mock()
            self.close = Mock()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def on(self, event, callback):
            self.events[event] = callback
            return self

    class UI:
        def __init__(self):
            for name in (
                "card",
                "row",
                "label",
                "link",
                "textarea",
                "input",
                "button",
                "dialog",
            ):
                setattr(self, name, Mock(side_effect=Element))
            self.page_function = lambda: None
            self.run_javascript = Mock()
            self.notify = Mock()
            self.timer = Mock()
            self.clipboard = SimpleNamespace(write=Mock())
            self.run = Mock(side_effect=lambda **_kwargs: self.page_function())

        def page(self, _path):
            def register(callback):
                self.page_function = callback
                return callback

            return register

    ui = UI()
    app = SimpleNamespace(on_startup=Mock(), on_disconnect=Mock(), shutdown=Mock())
    monkeypatch.setitem(sys.modules, "nicegui", SimpleNamespace(ui=ui, app=app))
    opener = Mock()
    monkeypatch.setattr("ai_guardian.desktop_utils.open_url", opener)
    monkeypatch.setattr("ai_guardian.ui.modal._find_free_port", lambda: 43123)
    return ui, app, opener, Element


def test_browser_message_renders_explicit_links_without_opening_them(browser_widgets):
    from ai_guardian.tray.dialog_placement import _show_nicegui_message

    ui, app, opener, _ = browser_widgets
    assert _show_nicegui_message(
        "About",
        "Author: Example (Profile)",
        links=(("(Profile)", "https://example.com/profile"),),
    )
    ui.link.assert_called_once_with(
        "(Profile)", "https://example.com/profile", new_tab=True
    )
    opener.assert_not_called()
    app.on_startup.call_args.args[0]()
    opener.assert_called_once_with("http://127.0.0.1:43123")
    assert ui.run.call_args.kwargs["show"] is False
    assert ui.run.call_args.kwargs["host"] == "127.0.0.1"


def test_browser_log_is_complete_readonly_and_copy_is_user_initiated(browser_widgets):
    from ai_guardian.tray.sandbox_dialog import _render_nicegui_log

    ui, _app, _opener, element = browser_widgets
    output = "A complete benign log line\n" * 1000
    text = element()
    ui.textarea.side_effect = None
    ui.textarea.return_value = text
    assert _render_nicegui_log("Output", "Message", output)
    ui.textarea.assert_called_once_with(value=output)
    text.props.assert_called_once_with("readonly")
    ui.clipboard.write.assert_not_called()
    copy = next(
        call.kwargs["on_click"]
        for call in ui.button.call_args_list
        if call.args[0] == "Copy"
    )
    copy()
    ui.clipboard.write.assert_called_once_with(output)


def test_browser_upload_review_retains_error_lines_and_does_not_auto_confirm(
    browser_widgets,
):
    from ai_guardian.tray.sandbox_dialog import _render_nicegui_confirmation

    ui, _app, _opener, _ = browser_widgets
    assert (
        _render_nicegui_confirmation(
            "Review",
            "Complete policy and summary",
            "Continue upload",
            error_lines=("Complete error",),
        )
        is False
    )
    assert [call.args[0] for call in ui.label.call_args_list] == [
        "Review",
        "Complete policy and summary",
        "Complete error",
    ]
    assert [call.args[0] for call in ui.button.call_args_list] == [
        "Cancel",
        "Continue upload",
    ]


@pytest.mark.parametrize("typed,expected", [("wrong", False), ("disposable", True)])
def test_browser_delete_still_requires_the_exact_name(browser_widgets, typed, expected):
    from ai_guardian.tray.sandbox_dialog import _render_nicegui_confirmation

    ui, _app, _opener, element = browser_widgets
    ui.input.side_effect = lambda **kwargs: element(value=typed)

    def interact(**_kwargs):
        ui.page_function()
        next(
            call.kwargs["on_click"]
            for call in ui.button.call_args_list
            if call.args[0] == "Delete sandbox"
        )()

    ui.run.side_effect = interact
    assert (
        _render_nicegui_confirmation(
            "Delete", "Message", "Delete sandbox", expected_text="disposable"
        )
        is expected
    )
    assert ui.notify.call_count == int(not expected)


def test_browser_snooze_close_is_final_without_a_second_server(browser_widgets):
    from ai_guardian.tray.proactive_prompt import ProactivePromptDialog

    ui, _app, _opener, element = browser_widgets
    dialog = element()
    ui.dialog.side_effect = None
    ui.dialog.return_value = dialog
    choose = Mock()
    prompt = ProactivePromptDialog(
        "Setup",
        "Message",
        "Install",
        "Never",
        snooze_options=("6h", "1d"),
        two_step_snooze=True,
    )
    prompt._open_nicegui_snooze(choose)
    dialog.events["hide"]()
    ui.button.call_args_list[-1].kwargs["on_click"]()
    choose.assert_called_once_with("snooze_6h")
    ui.run.assert_not_called()


def test_macos_complete_setup_prefers_cocoa_even_with_screen_bounds(
    automatic, monkeypatch
):
    from ai_guardian.tray.proactive_prompt import ProactivePromptDialog

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    prompt = ProactivePromptDialog(
        "Setup",
        "Message",
        "Install",
        "Never",
        ide_choices=({"ide": "claude"},),
        screen_bounds=(1920, 0, 1920, 1080),
    )
    with (
        patch.object(
            prompt, "_show_native_fallback", return_value={"result": "dismiss"}
        ) as native,
        patch.object(prompt, "_show_tkinter_subprocess") as tkinter,
    ):
        assert prompt.show(tray_safe=True) == {"result": "dismiss"}
    native.assert_called_once()
    tkinter.assert_not_called()


def test_browser_host_path_browse_cancel_does_not_open_tk(automatic, monkeypatch):
    from ai_guardian.ui.tray_prompt import _native_file_picker

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "nicegui")
    with (
        patch(
            "subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "")
        ) as native,
        patch("ai_guardian.ui.tray_prompt._tkinter_file_picker_subprocess") as tkinter,
    ):
        assert _native_file_picker() is None
    native.assert_called_once()
    tkinter.assert_not_called()


def test_hidden_parent_file_panel_failure_is_not_reported_as_startup(
    monkeypatch, capsys
):
    from ai_guardian.ui.tray_prompt import _show_tkinter_file_picker

    root = Mock()
    filedialog = SimpleNamespace(
        askopenfilename=Mock(side_effect=RuntimeError("Private panel error"))
    )
    tkinter = SimpleNamespace(Tk=lambda: root, filedialog=filedialog)
    monkeypatch.setitem(sys.modules, "tkinter", tkinter)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", filedialog)
    monkeypatch.setattr("ai_guardian.ui.display._ensure_tcl_library", lambda: None)
    with pytest.raises(SystemExit):
        run_modal_child(_show_tkinter_file_picker)
    assert "__AI_GUARDIAN_MODAL_UNAVAILABLE__" not in capsys.readouterr().out
    root.destroy.assert_called_once()


def test_browser_launch_latches_visibility_across_callback_contexts(
    browser_widgets, capsys
):
    from contextvars import Context
    from ai_guardian.ui.modal import run_nicegui_modal

    ui, app, _opener, _ = browser_widgets

    def start(**_kwargs):
        Context().run(app.on_startup.call_args.args[0])
        raise RuntimeError("Private browser failure")

    ui.run.side_effect = start
    with pytest.raises(SystemExit):
        run_modal_child(lambda: run_nicegui_modal("Review"))
    assert "__AI_GUARDIAN_MODAL_UNAVAILABLE__" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "kind,answer",
    [("form", {"policy": "edited"}), ("confirmation", False), ("log", True)],
)
def test_sandbox_browser_has_a_fresh_child_and_complete_stdin_payload(kind, answer):
    from ai_guardian.tray.sandbox_dialog import _run_sandbox_browser

    payload = {"title": "Review", "message": "Benign policy line\n" * 20000}
    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, json.dumps(answer), ""),
    ) as child:
        assert _run_sandbox_browser(kind, payload) == answer
    command = child.call_args.args[0]
    assert command[:2] == [sys.executable, "-c"]
    assert len(command) == 3  # no review content in argv
    assert f"_render_nicegui_{kind}" in command[2]
    assert json.loads(child.call_args.kwargs["input"]) == payload
    assert child.call_args.kwargs["encoding"] == "utf-8"
    assert child.call_args.kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    assert child.call_args.kwargs["timeout"] is None
    compile(command[2], "<child>", "exec")


@pytest.mark.parametrize(
    "answer,approved",
    [(True, True), (False, False), (None, False), (1, False), ("true", False)],
)
def test_isolated_browser_confirmation_requires_an_exact_boolean(answer, approved):
    from ai_guardian.tray.sandbox_dialog import _show_nicegui_confirmation

    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, json.dumps(answer), ""),
    ) as child:
        assert (
            _show_nicegui_confirmation("Review", "Full policy", "Replace policy")
            is approved
        )
    assert (
        json.loads(child.call_args.kwargs["input"])["confirm_label"] == "Replace policy"
    )


def test_large_complete_payload_crosses_an_actual_child_without_argv_limits():
    payload = {"log": "Benign complete log café\n" * 20000}
    command = [
        sys.executable,
        "-c",
        "import json, sys; from ai_guardian.ui.modal import run_modal_child; p=json.load(sys.stdin); run_modal_child(lambda: p)",
    ]
    result = run_modal_subprocess(
        command, input_text=json.dumps(payload, ensure_ascii=False)
    )
    assert json.loads(result.stdout) == payload


@pytest.mark.parametrize("status,advanced", [("unavailable", True), ("failed", False)])
def test_cocoa_reports_only_pre_display_initialization_failure_as_retryable(
    automatic, monkeypatch, status, advanced
):
    from ai_guardian.tray.proactive_prompt import ProactivePromptDialog

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    prompt = ProactivePromptDialog(
        "Setup",
        "Message",
        "Install",
        "Never",
        ide_choices=({"ide": "claude"},),
        two_step_snooze=True,
    )
    with (
        patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                [], 0, json.dumps({"modal_status": status}), ""
            ),
        ) as native,
        patch.object(
            prompt, "_show_tkinter_subprocess", return_value={"result": "dismiss"}
        ) as tkinter,
        patch.object(prompt, "_show_ui_subprocess") as browser,
    ):
        assert prompt.show(tray_safe=True) == (
            {"result": "dismiss"} if advanced else "snooze_1h"
        )
    assert tkinter.call_count == int(advanced)
    browser.assert_not_called()
    script = native.call_args.args[0][-1]
    assert script.index("try {") < script.index('ObjC.import("Cocoa")')
    assert "placeWindowOnTargetScreen(delayWindow)" in script
    assert script.index(
        "interactionStarted = true;", script.index("var alertWindow")
    ) < script.index("alertWindow.makeKeyAndOrderFront")


@pytest.mark.parametrize("system", ["Darwin", "Windows", "Linux"])
def test_native_destructive_confirmation_explains_the_required_name(
    system, monkeypatch
):
    from ai_guardian.tray.sandbox_dialog import _show_native_confirmation

    monkeypatch.setattr("platform.system", lambda: system)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    with patch(
        "subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "")
    ) as native:
        assert (
            _show_native_confirmation(
                "Delete sandbox",
                "Permanent deletion",
                "Delete sandbox",
                expected_text="disposable",
            )
            is False
        )
    assert "Type disposable to confirm:" in " ".join(native.call_args.args[0])
    if system == "Linux":
        assert native.call_args.args[0][0] == "kdialog"


def test_kdialog_action_menu_preserves_every_snooze_choice(automatic, monkeypatch):
    from ai_guardian.tray.proactive_prompt import ProactivePromptDialog

    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    prompt = ProactivePromptDialog(
        "Upgrade", "Message", "Update", "Never", snooze_options=("1h", "6h")
    )
    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, "snooze_6h\n", ""),
    ) as native:
        assert prompt.show(tray_safe=True) == "snooze_6h"
    command = native.call_args.args[0]
    assert command[0] == "kdialog"
    assert "--menu" in command
    assert command[command.index("action") :] == [
        "action",
        "Update",
        "snooze_1h",
        "Later (1h)",
        "snooze_6h",
        "Later (6h)",
        "dismiss",
        "Never",
    ]
