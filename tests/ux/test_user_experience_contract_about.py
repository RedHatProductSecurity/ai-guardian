"""About attribution UX. Never open live windows or browsers during tests.

Manual desktop verification:
1. Open About from the global tray menu and from a connected daemon's submenu.
   It must finish opening normally in front, not flash then minimize/drop behind
   other windows after the tray menu closes. Check again after one second on KDE
   Wayland/XWayland. It must not stay always-on-top or steal focus after startup.
2. Expect Author: Dominique Vernier (ITDoVe), with existing
   version/system/scanner/repository details preserved. Older daemons still show it.
3. With Tk available, the author line is a keyboard-focusable link. Clicking it,
   or focusing it and pressing Enter/Space, opens the profile; opening About alone
   must not launch a browser. Closing About must not open the profile either.
4. Without Tk, the native About fallback still shows the same compact attribution.
   The full author-profile URL must not appear in the visible About text.
5. Web Console → About shows Author: Dominique Vernier (ITDoVe) in the Project
   card, opening https://github.com/itdove in a new tab only when selected.
"""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_guardian.tray import dialog_placement, menu_builder


@pytest.mark.parametrize("remote", [False, True])
@pytest.mark.parametrize("per_daemon", [False, True])
def test_about_shows_author_and_profile_without_automatically_opening_it(
    monkeypatch, remote, per_daemon
):
    """USER EXPERIENCE: Open About → author/profile visible; browser stays closed."""
    target = SimpleNamespace(
        name="example-daemon", runtime="container" if remote else "local"
    )
    client = Mock()
    # This older-daemon response intentionally has no author/author_url fields.
    client.get_about.return_value = {
        "version": "1.20.0",
        "python": "3.12",
        "platform": "test",
        "scanners": [],
    }
    tray = SimpleNamespace(
        _targets=[target],
        _multi_client=client,
        _daemon_about_cache={},
        _is_multi_daemon=lambda: False,
    )
    builder = menu_builder.TrayMenuBuilder(tray)
    monkeypatch.setattr(builder, "_capture_tray_screen_bounds", lambda icon: None)
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_config_file", lambda: ({}, None)
    )
    monkeypatch.setattr(
        "ai_guardian.daemon.about.socket.gethostname", lambda: "synthetic-host"
    )
    monkeypatch.setattr(
        "ai_guardian.scanners.manager.ScannerManager.list_configured", lambda self: []
    )
    dialog = Mock(return_value=True)
    monkeypatch.setattr("ai_guardian.tray.plugins.show_dialog", dialog)
    browser = Mock()
    monkeypatch.setattr("webbrowser.open", browser)
    thread = Mock()
    monkeypatch.setattr(menu_builder.threading, "Thread", thread)
    action = builder._on_daemon_about(0) if per_daemon else builder._on_about
    action(None, None)
    thread.call_args.kwargs["target"]()
    dialog.assert_called_once()
    assert "Author: Dominique Vernier (ITDoVe)" in dialog.call_args.args[1]
    assert "https://github.com/itdove" not in dialog.call_args.args[1]
    assert "AI Guardian v" in dialog.call_args.args[1]
    assert (
        "https://github.com/RedHatProductSecurity/ai-guardian"
        in dialog.call_args.args[1]
    )
    assert dialog.call_args.kwargs["links"] == (
        ("(ITDoVe)", "https://github.com/itdove"),
    )
    browser.assert_not_called()


def test_about_stays_visible_when_the_window_manager_releases_the_raising_hint(
    monkeypatch,
):
    """USER EXPERIENCE: About opens → stays visible after its startup hint ends.

    Model a WM that drops the dialog behind other windows when topmost is cleared.
    This is a deterministic activation contract, not live desktop verification.
    """
    state = {"normal": False, "focused": False, "topmost": False}
    root = Mock()

    def deiconify():
        state["normal"] = True

    def focus_force():
        state["focused"] = True

    def attributes(name, value):
        assert name == "-topmost"
        state["topmost"] = value
        if not value:
            state["normal"] = False
            state["focused"] = False

    def mainloop():
        for call in root.after_idle.call_args_list:
            call.args[0]()
        for call in root.after.call_args_list:
            call.args[1]()

    root.deiconify.side_effect = deiconify
    root.focus_force.side_effect = focus_force
    root.attributes.side_effect = attributes
    root.mainloop.side_effect = mainloop
    ttk = SimpleNamespace(Frame=Mock(), Label=Mock(), Button=Mock())
    tk = SimpleNamespace(Tk=Mock(return_value=root), ttk=ttk, TclError=RuntimeError)
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setattr("ai_guardian.ui.display._ensure_tcl_library", lambda: None)
    monkeypatch.setattr(dialog_placement, "_place_window_on_screen", Mock())
    browser = Mock()
    monkeypatch.setattr("webbrowser.open", browser)
    dialog_placement._show_tkinter_message(
        "About AI Guardian",
        "Author: Dominique Vernier (ITDoVe)",
        links=(("(ITDoVe)", "https://github.com/itdove"),),
    )
    assert state == {"normal": True, "focused": True, "topmost": False}
    root.iconify.assert_not_called()
    root.withdraw.assert_called_once()
    browser.assert_not_called()
