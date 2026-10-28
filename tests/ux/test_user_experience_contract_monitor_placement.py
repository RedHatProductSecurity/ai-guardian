"""Tray action monitor UX (#2581); physical desktop qualification is separate.

Manual procedure and platform/provider limits: docs/MODAL_PROVIDERS.md.
No real GUI, source daemon, user configuration, approval or upload is used here.
"""

import json
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_guardian.ui import monitor


@pytest.fixture
def origin(monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    monkeypatch.delenv("_AI_GUARDIAN_MODAL_MONITOR", raising=False)
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    return monitor.MonitorContext((-1600, -200, 1600, 860), "secondary")


@pytest.mark.parametrize("system", ["Darwin", "Linux", "Windows"])
def test_unpositioned_native_messages_and_pickers_are_not_eligible(
    origin, monkeypatch, system
):
    """USER EXPERIENCE: placement-capable Tk precedes an unpositioned native panel."""
    from ai_guardian.tray.plugins import show_dialog
    from ai_guardian.daemon import working_dir

    monkeypatch.setattr("platform.system", lambda: system)
    native = Mock(side_effect=AssertionError("Unpositioned panel must not open"))
    tk = Mock(return_value=True)
    picker = Mock(return_value=(True, "/chosen"))
    monkeypatch.setattr("ai_guardian.tray.plugins._show_native_message", native)
    monkeypatch.setattr(
        "ai_guardian.tray.dialog_placement.show_tkinter_message_subprocess", tk
    )
    monkeypatch.setattr(working_dir, "_choose_directory_tkinter_subprocess", picker)
    assert show_dialog("Information", "Full message", screen_bounds=origin)
    assert working_dir.choose_directory(screen_bounds=origin) == "/chosen"
    tk.assert_called_once_with("Information", "Full message", screen_bounds=origin)
    assert picker.call_args.args[-1] is origin
    native.assert_not_called()


def test_startup_fallback_retains_monitor_but_cancel_never_opens_browser(
    origin, monkeypatch
):
    """USER EXPERIENCE: startup failure keeps origin; dismissal never retries."""
    from ai_guardian.ui.forms import run_form_flow
    from ai_guardian.ui.modal import UIUnavailable

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    origin = monitor.MonitorContext((1920, 24, 2560, 1416), "secondary")
    native = Mock(side_effect=UIUnavailable())
    tk = Mock(return_value=None)
    browser = Mock()
    monkeypatch.setattr("ai_guardian.ui.forms.NativeForm", lambda **kw: native)
    monkeypatch.setattr(
        "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess", tk
    )
    monkeypatch.setattr("ai_guardian.tray.sandbox_dialog._show_nicegui_form", browser)
    assert (
        run_form_flow(
            lambda form: form("Choose", "Complete review", []), screen_bounds=origin
        )
        is None
    )
    assert tk.call_args.kwargs["screen_bounds"] is origin
    browser.assert_not_called()


def test_browser_has_explicit_manual_move_fallback_not_a_false_placement_claim(
    origin, monkeypatch
):
    """USER EXPERIENCE: browser reuse/compositor restriction → visible move guidance."""
    pytest.importorskip("nicegui")
    from ai_guardian.ui.modal import run_nicegui_modal

    app, ui = Mock(), Mock()
    monkeypatch.setitem(sys.modules, "nicegui", SimpleNamespace(app=app, ui=ui))
    run_nicegui_modal("Review", screen_bounds=origin)
    html = ui.add_head_html.call_args.args[0]
    assert "The browser cannot place this dialog" in html
    assert "Move this window to the screen where you opened the tray action" in html
    assert "secondary" not in html
    assert "moveTo" not in html
    assert ui.run.call_args.kwargs["show"] is False


def test_delayed_support_worker_and_all_review_stages_keep_click_origin(
    origin, monkeypatch
):
    """USER EXPERIENCE: moving focus/pointer during collection never redirects review."""
    from ai_guardian.tray import support
    from ai_guardian.reporting import github_support

    queued = []
    thread = Mock()
    thread.side_effect = lambda **kw: SimpleNamespace(
        start=lambda: queued.append(kw["target"])
    )
    monkeypatch.setattr(support.threading, "Thread", thread)
    monkeypatch.setattr(support, "_review_lock", threading.Lock())
    monkeypatch.setattr("ai_guardian.ui.display.get_preferred_ui", lambda: "auto")
    monkeypatch.delenv("AI_GUARDIAN_NO_TKINTER", raising=False)
    requests = []

    def collect(**kwargs):
        assert monitor.current_origin() == origin
        for mode in ("delivery", "bundle", "upload", "approve", "result"):
            github_support.review_dialog({"mode": mode, "request_id": "request"})
        return {"status": "error", "error_code": "cancelled"}

    def child(command, **kwargs):
        request = json.loads(kwargs["input"])
        requests.append(request)
        return subprocess.CompletedProcess(command, 0, "null", "")

    monkeypatch.setattr(support, "_run_support_flow", collect)
    monkeypatch.setattr(
        github_support,
        "subprocess",
        SimpleNamespace(run=child, SubprocessError=subprocess.SubprocessError),
    )
    monkeypatch.setattr("ai_guardian.ui.display._ensure_tcl_library", lambda: None)
    assert support.open_support_dialog(screen_bounds=origin)
    assert not requests  # No collection/dialog on the tray event loop.
    queued[0]()
    assert len(requests) == 5
    assert all(monitor.restore_context(r["screen_bounds"]) == origin for r in requests)
    assert all("approval" not in r for r in requests)
    assert monitor.current_origin() is None


def test_support_child_previews_use_original_monitor_not_moved_parent(
    origin, monkeypatch
):
    """USER EXPERIENCE: View and result windows retain the action, not later focus."""
    from ai_guardian.ui import support_review

    place = Mock()
    monkeypatch.setattr(
        support_review, "_monitor_helpers", lambda: {"place_tk_window": place}
    )
    window = Mock()
    support_review._place_review_window(
        window, {"screen_bounds": monitor.screen_payload(origin)}, 900, 650
    )
    assert place.call_args.args == (window, monitor.screen_payload(origin), 900, 650)


def test_disconnected_monitor_falls_back_visible_and_wayland_is_explicit(
    origin, monkeypatch
):
    """USER EXPERIENCE: missing monitor → primary work area; restricted WM → move hint."""
    primary = monitor.MonitorContext((0, 24, 1920, 1016), "primary")
    monkeypatch.setattr(monitor, "list_monitors", lambda: (primary,))
    window = Mock()
    assert monitor.place_tk_window(window, origin, 900, 650)
    window.geometry.assert_called_once_with("900x650+510+207")
    unavailable = monitor.MonitorContext(origin.bounds, "secondary", enforceable=False)
    monitor.place_tk_window(window, unavailable, 900, 650)
    assert "Move this window to the tray screen" in window.title.call_args.args[0]


def test_actual_support_view_entry_positions_before_presenting(origin, monkeypatch):
    """USER EXPERIENCE: the real View entry retains context before its first map."""
    from ai_guardian.ui import support_review

    parent, window, ttk = Mock(), Mock(), Mock()
    tk = SimpleNamespace(Toplevel=Mock(return_value=window), BooleanVar=Mock(), ttk=ttk)
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(
        sys.modules, "tkinter.scrolledtext", SimpleNamespace(ScrolledText=Mock())
    )
    monkeypatch.setattr(
        support_review,
        "read_preview",
        lambda *a, **kw: SimpleNamespace(text="full", next_offset=None, total_bytes=4),
    )
    events = []
    monkeypatch.setattr(
        support_review,
        "_place_review_window",
        lambda w, request, width, height: events.append(
            ("place", request["screen_bounds"], width, height)
        ),
    )
    monkeypatch.setattr(
        support_review, "_present_window", lambda w: events.append(("present",))
    )
    payload = monitor.screen_payload(origin)
    support_review._show_file_preview(
        parent,
        {
            "screen_bounds": payload,
            "temp_path": "unused",
            "files": [{"name": "doctor.json"}],
        },
        "doctor.json",
    )
    assert events == [("place", payload, 900, 650), ("present",)]
    window.withdraw.assert_called_once()
    parent.wait_window.assert_called_once_with(window)


def test_long_plugin_parameters_map_after_placement_with_scrollbars_and_reserved_actions(
    origin, monkeypatch
):
    """USER EXPERIENCE: small/scaled monitor → all fields remain reachable, not clipped."""
    from ai_guardian.ui import tray_prompt

    root, frame, buttons, canvas, ttk, messagebox, shell = (Mock() for _ in range(7))
    frame.winfo_reqwidth.return_value, frame.winfo_reqheight.return_value = 700, 1600
    buttons.winfo_reqheight.return_value = 50
    root.winfo_reqheight.return_value = 500
    ttk.Frame.side_effect = [shell, frame, buttons]
    tk = SimpleNamespace(
        ttk=ttk,
        messagebox=messagebox,
        Canvas=Mock(return_value=canvas),
        StringVar=Mock(),
    )
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setattr(tray_prompt, "create_tk_root", lambda: root)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    events = []
    root.withdraw.side_effect = lambda: events.append("withdraw")
    root.deiconify.side_effect = lambda: events.append("map")
    place = Mock(side_effect=lambda *args: events.append("place"))
    monkeypatch.setattr(tray_prompt, "_place_window_on_screen", place)
    app = tray_prompt._TkinterPromptApp(
        [{"name": "first"}, {"name": "second"}], "benign", screen_bounds=origin
    )
    assert app.run() is None
    assert events == ["withdraw", "place", "map"]
    place.assert_called_once_with(root, origin, 724, 1674)
    assert ttk.Frame.call_args.args == (shell,)  # actions outside the scrolling body
    buttons.grid.assert_called_once_with(
        row=2, column=0, columnspan=2, pady=(12, 0), sticky="ew"
    )
    assert ttk.Scrollbar.call_count == 2
    canvas.create_window.assert_called_once_with((0, 0), window=frame, anchor="nw")
    root.resizable.assert_called_once_with(True, True)


def test_plugin_browse_revalidates_origin_and_restricted_picker_has_visible_guidance(
    origin, monkeypatch
):
    """USER EXPERIENCE: Browse after moving a form keeps the click origin/WM guidance."""
    from ai_guardian.ui import tray_prompt

    restricted = monitor.MonitorContext(
        origin.bounds, origin.monitor_id, enforceable=False
    )
    picker = Mock(return_value="/selected")
    monkeypatch.setitem(
        sys.modules, "tkinter.filedialog", SimpleNamespace(askdirectory=picker)
    )
    tk = SimpleNamespace(filedialog=SimpleNamespace(askdirectory=picker))
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    root, variable = Mock(), Mock()
    variable.get.return_value = "/current"
    root.winfo_width.return_value, root.winfo_height.return_value = 900, 700
    place = Mock()
    monkeypatch.setattr(tray_prompt, "_place_window_on_screen", place)
    app = tray_prompt._TkinterPromptApp([], "benign", screen_bounds=restricted)
    app._root = root
    app._make_browse_callback(variable, "path-dir")()
    place.assert_called_once_with(root, restricted, 900, 700)
    picker.assert_called_once_with(
        parent=root,
        initialdir="/current",
        title="Select directory — Move this window to the tray screen",
    )
    variable.set.assert_called_once_with("/selected")


def test_sandbox_browse_has_a_positioned_owner_and_does_not_follow_later_focus(
    origin, monkeypatch
):
    """USER EXPERIENCE: sandbox Browse → an owned panel on the frozen action monitor."""
    from ai_guardian.tray import sandbox_dialog

    root, ttk, canvas, variable, error = (Mock() for _ in range(5))
    variable.get.return_value = "/current"
    root.winfo_width.return_value, root.winfo_height.return_value = 700, 620
    picker = Mock(return_value="/selected")
    tk = SimpleNamespace(
        ttk=ttk,
        Canvas=Mock(return_value=canvas),
        StringVar=Mock(side_effect=[variable, error]),
        filedialog=SimpleNamespace(askdirectory=picker),
    )
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setattr(sandbox_dialog, "create_tk_root", lambda: root)
    monkeypatch.setattr(sandbox_dialog, "_browse_initialdir", lambda path: path)
    place = Mock()
    monkeypatch.setattr(sandbox_dialog, "_place_window_on_screen", place)
    callbacks = {}

    def button(*args, **kwargs):
        callbacks[kwargs["text"]] = kwargs["command"]
        return Mock()

    ttk.Button.side_effect = button
    root.mainloop.side_effect = lambda: callbacks["Browse..."]()
    assert (
        sandbox_dialog._show_tkinter_form(
            "Choose",
            "Complete fields",
            [{"name": "directory", "type": "directory"}],
            screen_bounds=origin,
        )
        is None
    )
    assert place.call_args.args == (root, origin, 700, 620)
    picker.assert_called_once_with(
        title="Select a path", parent=root, initialdir="/current"
    )
    variable.set.assert_called_once_with("/selected")


@pytest.mark.parametrize("mode", ["upload", "approve"])
def test_small_support_review_keeps_unchecked_consent_and_actions_outside_scrollable_content(
    origin, monkeypatch, mode
):
    """USER EXPERIENCE: small/scaled screen → scrollable full review, visible fresh consent."""
    from ai_guardian.ui import support_review

    root, ttk, canvas, consent, text = (Mock() for _ in range(5))
    consent.get.return_value = False
    tk = SimpleNamespace(
        Tk=Mock(return_value=root),
        ttk=ttk,
        Canvas=Mock(return_value=canvas),
        BooleanVar=Mock(return_value=consent),
    )
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(
        sys.modules,
        "tkinter.scrolledtext",
        SimpleNamespace(ScrolledText=Mock(return_value=text)),
    )
    monkeypatch.setattr(support_review, "_style_window", lambda root: None)
    monkeypatch.setattr(support_review, "_place_review_window", Mock())
    request = {
        "mode": mode,
        "screen_bounds": monitor.screen_payload(origin),
        "account": "synthetic",
        "warning": "Public review",
        "category": "Bug Reports",
        "title": "Chosen title",
        "context_redactions": 0,
        "files": [],
        "body": "Complete review",
        "request_id": "request",
    }
    assert support_review.show_review(request) is None
    tk.BooleanVar.assert_called_once_with(value=False)
    consent.set.assert_not_called()
    canvas.create_window.assert_called_once()
    assert ttk.Scrollbar.call_count == 2
    publish = next(
        c
        for c in ttk.Button.call_args_list
        if c.kwargs.get("text") in {"Create Gist", "Publish publicly"}
    )
    assert publish.kwargs["state"] == "disabled"
    assert ttk.Checkbutton.call_args.kwargs["variable"] is consent
    assert any(
        "approve" in str(c.kwargs.get("text", "")) for c in ttk.Label.call_args_list
    )
    text.insert.assert_called_once_with("1.0", "Complete review")
