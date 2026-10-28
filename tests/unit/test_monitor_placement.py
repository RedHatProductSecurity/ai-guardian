"""No desktop/user configuration required for physical-monitor placement."""

import json
import ctypes
import shutil
import subprocess
import sys
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_guardian.ui import monitor


def display(name="secondary", bounds=(-1600, -200, 1600, 860), **kwargs):
    return monitor.MonitorContext(bounds, name, **kwargs)


def test_origin_is_immutable_and_survives_json():
    origin = display(scale=1.5)
    with pytest.raises(FrozenInstanceError):
        origin.monitor_id = "other"
    payload = json.loads(json.dumps(origin, default=monitor.monitor_json_default))
    assert monitor.restore_context(payload) == origin


def test_geometry_tracks_identity_not_later_pointer_or_old_geometry(monkeypatch):
    origin = display()
    moved = display(bounds=(2000, 24, 1600, 876))
    primary = display("primary", (0, 0, 1920, 1040))
    monkeypatch.setattr(monitor, "list_monitors", lambda: (primary, moved))
    assert monitor.resolve_bounds(origin) == moved.bounds


def test_disconnected_monitor_uses_primary_without_reassigning_origin(monkeypatch):
    origin = display()
    primary = display("primary", (0, 30, 1920, 1010))
    monkeypatch.setattr(monitor, "list_monitors", lambda: (primary,))
    assert monitor.resolve_bounds(origin) == primary.bounds
    assert origin.monitor_id == "secondary"


@pytest.mark.parametrize(
    "bounds", [(-1600, 0, 1600, 900), (0, -900, 1600, 900), (1920, 1080, 1000, 700)]
)
def test_window_fits_usable_area_with_frame_margin(monkeypatch, bounds):
    origin = display(bounds=bounds)
    monkeypatch.setattr(monitor, "list_monitors", lambda: (origin,))
    window = Mock()
    assert monitor.place_tk_window(window, origin, 2400, 1800)
    rect = monitor.center_geometry(2400, 1800, bounds, margin=64)
    x, y, w, h = rect
    assert bounds[0] <= x and bounds[1] <= y
    assert x + w <= bounds[0] + bounds[2]
    assert y + h <= bounds[1] + bounds[3]
    window.geometry.assert_called_once_with(f"{w}x{h}+{x}+{y}")


def test_missing_monitor_inventory_does_not_reuse_stale_offscreen_bounds(monkeypatch):
    monkeypatch.setattr(monitor, "list_monitors", lambda: ())
    assert monitor.resolve_bounds(display()) is None


def test_legacy_coordinates_keep_internal_callers_working():
    assert monitor.resolve_bounds((-1600, -200, 1600, 900)) == (-1600, -200, 1600, 900)
    assert monitor.center_geometry(560, 250, (-1600, -200, 1600, 900)) == (
        -1080,
        125,
        560,
        250,
    )


def test_browser_notice_is_explicit_and_never_claims_placement():
    message = monitor.placement_notice(display(), browser=True)
    assert "cannot place" in message
    assert "Move this window" in message
    assert "the screen where you opened the tray action" in message
    assert "secondary" not in message  # platform device IDs are not user guidance


def test_wayland_notice_offers_manual_window_movement():
    message = monitor.placement_notice(display(enforceable=False))
    assert "Move this window" in message


def test_non_tray_dialog_has_no_fabricated_origin():
    assert monitor.placement_notice(None) == ""


def test_windows_capture_uses_tray_rectangle_not_unrelated_pointer(monkeypatch):
    primary = display("primary", (0, 0, 1920, 1040))
    secondary = display()
    monkeypatch.setattr(monitor, "list_monitors", lambda: (primary, secondary))
    monkeypatch.setattr(monitor, "tray_anchor", lambda icon: (-1500, 20))
    assert monitor.capture_monitor(object()) == secondary


def test_unknown_keyboard_menu_origin_is_explicit_not_pointer_guess(monkeypatch):
    monkeypatch.setattr(
        monitor,
        "list_monitors",
        lambda: (display(), display("other", (0, 0, 1920, 1040))),
    )
    monkeypatch.setattr(monitor, "tray_anchor", lambda icon: None)
    context = monitor.capture_monitor(object())
    assert not context.enforceable
    assert context.source == "unavailable"


def test_single_monitor_keeps_existing_provider_behavior(monkeypatch):
    monkeypatch.setattr(monitor, "list_monitors", lambda: (display(),))
    assert monitor.capture_monitor(object()) is None


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        [0, 0, 0, 600],
        [True, 0, 800, 600],
        [0, 0, 800],
        {"bounds": [0, 0, 800, 600], "scale": "bad"},
        {"bounds": [0, 0, 800, 600], "monitor_id": 42},
    ],
)
def test_invalid_wire_metadata_never_becomes_geometry(value):
    assert monitor.restore_context(value) is None


def test_child_process_receives_monitor_identity_without_gui(monkeypatch):
    from ai_guardian.ui.modal import run_modal_subprocess

    monkeypatch.delenv("_AI_GUARDIAN_MODAL_MONITOR", raising=False)
    origin = display(scale=1.5)
    with monitor.monitor_origin(origin):
        child = run_modal_subprocess(
            [
                sys.executable,
                "-c",
                "import json; from ai_guardian.ui.monitor import current_origin, monitor_json_default; print(json.dumps(current_origin(), default=monitor_json_default))",
            ]
        )
    assert monitor.restore_context(json.loads(child.stdout)) == origin
    assert monitor.current_origin() is None


def test_modal_inherits_origin_for_follow_up_and_resets_after_error(monkeypatch):
    from ai_guardian.ui.modal import run_modal

    monkeypatch.delenv("_AI_GUARDIAN_MODAL_MONITOR", raising=False)
    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "tkinter")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    origin = display()

    def step():
        assert monitor.current_origin() == origin
        assert (
            run_modal("form", {"tkinter": monitor.current_origin}, fallback=None)
            == origin
        )
        raise RuntimeError("terminal failure")

    assert (
        run_modal("form", {"tkinter": step}, fallback=None, screen_bounds=origin)
        is None
    )
    assert monitor.current_origin() is None


def test_windows_inventory_uses_work_area_identity_and_physical_dpi(monkeypatch):
    from ctypes import wintypes as w

    user, dpi = Mock(), Mock()
    user.SetThreadDpiAwarenessContext.return_value = 1234
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda name, **kw: user if name == "user32" else dpi,
        raising=False,
    )
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)

    def info(handle, pointer):
        item = pointer._obj
        item.work = (
            w.RECT(-1600, -200, 0, 660) if handle == 1 else w.RECT(0, 24, 1920, 1040)
        )
        item.device = "secondary" if handle == 1 else "primary"
        item.flags = int(handle == 2)
        return 1

    def density(handle, mode, x, y):
        x._obj.value = y._obj.value = 144 if handle == 1 else 96
        return 0

    user.GetMonitorInfoW.side_effect = info
    dpi.GetDpiForMonitor.side_effect = density
    user.EnumDisplayMonitors.side_effect = lambda dc, clip, callback, data: (
        callback(1, None, None, 0),
        callback(2, None, None, 0),
    )
    primary, secondary = monitor._windows_monitors()
    assert primary.monitor_id == "primary"
    assert secondary.bounds == (-1600, -200, 1600, 860)
    assert secondary.scale == 1.5
    assert user.SetThreadDpiAwarenessContext.call_args.args == (1234,)


def test_windows_keyboard_anchor_is_shell_icon_rect_with_same_dpi_space(monkeypatch):
    monkeypatch.setattr(monitor.platform, "system", lambda: "Windows")
    user, shell = Mock(), Mock()
    user.SetThreadDpiAwarenessContext.return_value = 1234
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda name, **kw: user if name == "user32" else shell,
        raising=False,
    )
    icon = SimpleNamespace(_hwnd=99)

    def rect(identifier, output):
        assert identifier._obj.hwnd == 99
        assert identifier._obj.uid == id(icon) & 0xFFFFFFFF
        output._obj.left, output._obj.right = -1540, -1500
        output._obj.top, output._obj.bottom = 0, 40
        return 0

    shell.Shell_NotifyIconGetRect.side_effect = rect
    assert monitor.tray_anchor(icon) == (-1520, 20)
    user.GetCursorPos.assert_not_called()
    assert user.SetThreadDpiAwarenessContext.call_args.args == (1234,)


def test_macos_inventory_is_isolated_from_tk_and_preserves_logical_points(monkeypatch):
    monkeypatch.setattr(monitor.platform, "system", lambda: "Darwin")
    value = display("42", (-1600, -880, 1600, 860))
    run = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, json.dumps([value], default=monitor.monitor_json_default), ""
        )
    )
    monkeypatch.setattr(monitor.subprocess, "run", run)
    assert monitor.list_monitors() == (value,)
    assert run.call_args.args[0][:3] == ["/usr/bin/osascript", "-l", "JavaScript"]
    assert "visibleFrame" in run.call_args.args[0][-1]


def test_linux_inventory_uses_randr_not_subprocess_and_intersects_reserved_area(
    monkeypatch,
):
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    x, randr = Mock(), Mock()
    monkeypatch.setattr(ctypes, "CDLL", lambda name: randr if "Xrandr" in name else x)
    x.XOpenDisplay.return_value = 1
    x.XDefaultRootWindow.return_value = 2
    atoms = {"_NET_WORKAREA": 3, "_NET_CURRENT_DESKTOP": 4}
    x.XInternAtom.side_effect = lambda conn, name, exists: atoms.get(name.decode(), 0)
    buffers = []

    def prop(
        conn,
        window,
        atom,
        offset,
        length,
        delete,
        req,
        actual,
        fmt,
        count,
        remaining,
        data,
    ):
        values = (
            (ctypes.c_ulong * 4)(0, 24, 4480, 1416)
            if atom == 3
            else (ctypes.c_ulong * 1)(0)
        )
        buffers.append(values)
        fmt._obj.value = 32
        count._obj.value = len(values)
        data._obj.value = ctypes.addressof(values)
        return 0

    def monitors(conn, root, active, count):
        info_type = randr.XRRGetMonitors.restype._type_
        values = (info_type * 2)()
        for i, (name, primary, x_pos, width, height) in enumerate(
            [(10, 1, 0, 1920, 1080), (11, 0, 1920, 2560, 1440)]
        ):
            item = values[i]
            item.name, item.primary, item.x, item.width, item.height = (
                name,
                primary,
                x_pos,
                width,
                height,
            )
        count._obj.value = 2
        buffers.append(values)
        return values

    def name(conn, atom):
        value = ctypes.create_string_buffer(b"primary" if atom == 10 else b"secondary")
        buffers.append(value)
        return ctypes.addressof(value)

    x.XGetWindowProperty.side_effect = prop
    x.XGetAtomName.side_effect = name
    randr.XRRGetMonitors.side_effect = monitors

    def version(connection, major, minor):
        major._obj.value, minor._obj.value = 1, 5
        return 1

    randr.XRRQueryVersion.side_effect = version
    primary, secondary = monitor._linux_monitors()
    assert primary.bounds == (0, 24, 1920, 1056)
    assert secondary.bounds == (1920, 24, 2560, 1416)
    assert secondary.monitor_id == "secondary" and secondary.enforceable
    randr.XRRFreeMonitors.assert_called_once()
    x.XCloseDisplay.assert_called_once_with(1)


def test_linux_keyboard_uses_mapped_menu_not_pointer(monkeypatch):
    monkeypatch.setattr(monitor.platform, "system", lambda: "Linux")
    window = Mock()
    window.get_origin.return_value = (True, 1000, 10)
    window.get_scale_factor.return_value = 2
    menu = Mock()
    menu.get_mapped.return_value = True
    menu.get_window.return_value = window
    gtk = Mock()
    monkeypatch.setitem(sys.modules, "gi.repository", SimpleNamespace(Gtk=gtk))
    abstract = Mock()
    assert monitor.tray_anchor(SimpleNamespace(_menu_handle=menu, _menu=abstract)) == (
        2000,
        20,
    )
    assert not abstract.mock_calls
    gtk.get_current_event.assert_not_called()


def test_linux_unmapped_keyboard_menu_uses_status_icon_geometry(monkeypatch):
    monkeypatch.setattr(monitor.platform, "system", lambda: "Linux")
    menu, status, screen, gtk = Mock(), Mock(), Mock(), Mock()
    menu.get_mapped.return_value = False
    screen.get_root_window.return_value.get_scale_factor.return_value = 2
    status.get_geometry.return_value = (
        True,
        screen,
        SimpleNamespace(x=1000, y=0, width=24, height=24),
        None,
    )
    monkeypatch.setitem(sys.modules, "gi.repository", SimpleNamespace(Gtk=gtk))
    assert monitor.tray_anchor(
        SimpleNamespace(_menu_handle=menu, _status_icon=status)
    ) == (2024, 24)
    gtk.get_current_event.assert_not_called()


def test_linux_remote_keyboard_activation_does_not_use_pointer(monkeypatch):
    monkeypatch.setattr(monitor.platform, "system", lambda: "Linux")
    event = Mock()
    event.type = "KEY_PRESS"
    gtk = Mock()
    gtk.get_current_event.return_value = event
    monkeypatch.setitem(sys.modules, "gi.repository", SimpleNamespace(Gtk=gtk))
    assert monitor.tray_anchor(SimpleNamespace()) is None
    event.get_root_coords.assert_not_called()


def test_native_form_revalidates_origin_before_each_step(monkeypatch):
    from ai_guardian.ui import native_form

    monkeypatch.setattr(native_form.platform, "system", lambda: "Windows")
    origin = display(bounds=(1920, 0, 1920, 1040))
    moved = display(bounds=(-2560, 24, 2560, 1416))
    monkeypatch.setattr(monitor, "list_monitors", lambda: (moved,))
    run = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, '{"modal_status":"complete","value":{}}', ""
        )
    )
    monkeypatch.setattr(native_form, "run_native_command", run)
    assert (
        native_form.NativeForm(screen_bounds=origin)("Review", "Full content", []) == {}
    )
    payload = json.loads(run.call_args.kwargs["input_text"])
    assert payload["screen_bounds"] == list(moved.bounds)
    assert payload["monitor_id"] == origin.monitor_id
    script = run.call_args.args[0][-1]
    assert "SetThreadDpiAwarenessContext" in script
    assert "StartPosition = 'Manual'" in script
    assert "AutoScrollMinSize" in script
    assert "[System.Windows.Forms.Screen]::AllScreens" in script
    assert "[GuardianDpi]::Identity($candidate.DeviceName)" in script
    assert "$area = $screen.WorkingArea" in script


@pytest.mark.skipif(
    shutil.which("node") is None, reason="JavaScript runtime unavailable"
)
def test_cocoa_child_revalidates_each_window_after_startup_and_hotplug():
    # Execute the exact shared provider helper with inert Cocoa geometry. This
    # tests its logic, not physical Apple rendering/focus or ObjC bridge behavior.
    script = monitor.COCOA_PLACE_WINDOW + r"""
function screen(id, x, y, w, h) {
    const frame = {origin:{x:x, y:y}, size:{width:w, height:h}};
    return {frame:frame, visibleFrame:frame, deviceDescription:{objectForKey:()=>({value:id})}};
}
const ObjC = {unwrap:value=>value.value};
let inventory = [screen('primary',0,0,1920,1040), screen('secondary',-1600,1080,1600,860)];
const $ = {NSScreen:{get screens(){return {count:inventory.length,objectAtIndex:i=>inventory[i]};}}, NSMakePoint:(x,y)=>[x,y]};
const positions = [];
const window = {frame:{size:{width:600,height:400}},setFrameOrigin:p=>positions.push(p)};
const stale = [-1600,-200,1600,860];
placeWindowOnTargetScreen(window,stale,'secondary');
inventory[1] = screen('secondary',1920,-900,2560,1400);
placeWindowOnTargetScreen(window,stale,'secondary');
inventory.pop();
placeWindowOnTargetScreen(window,stale,'secondary');
inventory[0] = screen('primary',0,0,120,120);
let rejected = false;
try { placeWindowOnTargetScreen(window,stale,'secondary'); } catch (e) { rejected = true; }
console.log(JSON.stringify({positions:positions,rejected:rejected}));
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == {
        "positions": [[-1100, 1310], [2900, -400], [660, 320]],
        "rejected": True,
    }


def test_support_reviewer_loads_shared_placement_without_importing_package():
    from ai_guardian.ui import support_review

    helper = support_review._monitor_helpers()
    context = helper["restore_context"](monitor.screen_payload(display()))
    assert context.monitor_id == "secondary"
    assert context.bounds == (-1600, -200, 1600, 860)


def test_scrollable_content_resizes_and_reveals_keyboard_focus(monkeypatch):
    window, shell, canvas, body, footer, ttk = (Mock() for _ in range(6))
    ttk.Frame.side_effect = [shell, body, footer]
    monkeypatch.setitem(
        sys.modules,
        "tkinter",
        SimpleNamespace(ttk=ttk, Canvas=Mock(return_value=canvas)),
    )
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    assert monitor.tk_scrollable_content(window) == (body, footer)

    body.winfo_reqwidth.return_value, body.winfo_reqheight.return_value = 900, 1600
    canvas.winfo_width.return_value, canvas.winfo_height.return_value = 700, 600
    body.bind.call_args.args[1]()
    canvas.itemconfigure.assert_called_once_with(
        canvas.create_window.return_value, width=900, height=1600
    )
    canvas.configure.assert_called_with(scrollregion=canvas.bbox.return_value)

    body.winfo_width.return_value, body.winfo_height.return_value = 900, 1600
    body.winfo_rootx.return_value, body.winfo_rooty.return_value = 100, 200
    canvas.canvasx.return_value, canvas.canvasy.return_value = 0, 0
    entry = Mock()
    entry.winfo_rootx.return_value, entry.winfo_rooty.return_value = 850, 1500
    entry.winfo_width.return_value, entry.winfo_height.return_value = 100, 40

    class Child:
        def __str__(self):
            return str(body) + ".entry"

        def __getattr__(self, name):
            return getattr(entry, name)

    reveal = window.bind.call_args.args[1]
    reveal(SimpleNamespace(widget=Child()))
    canvas.xview_moveto.assert_called_once_with((750 - 8) / 900)
    canvas.yview_moveto.assert_called_once_with((1300 - 8) / 1600)

    canvas.xview_moveto.reset_mock()
    canvas.yview_moveto.reset_mock()
    reveal(SimpleNamespace(widget=footer))
    canvas.xview_moveto.assert_not_called()
    canvas.yview_moveto.assert_not_called()


def test_linux_older_randr_server_is_checked_before_monitor_request(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")
    x, randr = Mock(), Mock()
    monkeypatch.setattr(ctypes, "CDLL", lambda name: randr if "Xrandr" in name else x)
    x.XOpenDisplay.return_value = 1
    randr.XRRQueryVersion.return_value = 0
    assert monitor._linux_monitors() == ()
    randr.XRRGetMonitors.assert_not_called()
    x.XCloseDisplay.assert_called_once_with(1)


def test_inventory_failure_with_a_valid_anchor_is_still_explicit(monkeypatch):
    monkeypatch.setattr(monitor, "list_monitors", lambda: ())
    monkeypatch.setattr(monitor, "tray_anchor", lambda icon: (1920, 20))
    assert monitor.capture_monitor(object()).source == "unavailable"


def test_geometry_uses_current_dpi_without_rescaling_physical_coordinates(monkeypatch):
    captured = display(scale=1.0)
    current = display(bounds=(-2560, -100, 2560, 1440), scale=2.0)
    monkeypatch.setattr(monitor, "list_monitors", lambda: (current,))
    window = Mock()
    monitor.place_tk_window(window, captured, 4000, 3000)
    x, y, width, height = monitor.center_geometry(
        4000, 3000, current.bounds, margin=128
    )
    window.geometry.assert_called_once_with(f"{width}x{height}+{x}+{y}")
    window.minsize.return_value = (4000, 3000)
    window.after_idle.call_args.args[0]()
    window.minsize.assert_called_with(width, height)
    window.maxsize.assert_called_once_with(2432, 1312)


def test_unavailable_inventory_uses_wm_position_not_stale_offset(monkeypatch):
    monkeypatch.setattr(monitor, "list_monitors", lambda: ())
    window = Mock()
    assert monitor.place_tk_window(window, display(), 960, 820) is False
    window.geometry.assert_called_once_with("800x600")
    assert "Display unavailable" in window.title.call_args.args[0]
    window.minsize.return_value = (960, 820)
    window.after_idle.call_args.args[0]()
    window.minsize.assert_called_with(320, 200)
    window.resizable.assert_called_once_with(True, True)
    window.maxsize.assert_not_called()


def test_target_selector_cli_restores_complete_monitor_context(monkeypatch):
    from argparse import Namespace
    from ai_guardian.cli_handlers import _handle_tray_target_select

    origin = display(scale=1.5)
    selector = Mock()
    selector.return_value.run.return_value = None
    monkeypatch.setattr(
        "ai_guardian.ui.tray_target_selector.TrayTargetSelectorApp", selector
    )
    args = Namespace(
        targets="[]",
        screen_bounds=json.dumps(origin, default=monitor.monitor_json_default),
        output_file=None,
    )
    assert _handle_tray_target_select(args) == 0
    selector.assert_called_once_with(targets=[], screen_bounds=origin)


def test_plugin_selector_subprocess_and_later_output_retain_origin(monkeypatch):
    from ai_guardian.tray.plugin_runner import TrayPluginMenuBuilder
    from ai_guardian.tray import plugin_runner

    origin = display()
    target = Mock()
    tray = Mock()
    tray._targets = [target]
    builder = TrayPluginMenuBuilder(tray)
    monkeypatch.setattr(
        builder,
        "_serialize_targets_for_selector",
        lambda: [{"name": "chosen", "runtime": "local"}],
    )
    execute = Mock()
    monkeypatch.setattr(builder, "_execute_multi_target_command", execute)
    monkeypatch.setattr(
        plugin_runner.tray_plugins,
        "resolve_cli_cmd",
        lambda *args: ["guardian"] + list(args),
    )
    monkeypatch.setattr(
        plugin_runner.tray_plugins, "poll_output_file", lambda *args: "[0]"
    )
    monkeypatch.setattr(
        plugin_runner.tray_plugins, "resolve_command", lambda command: command
    )
    process = Mock()
    launch = Mock(return_value=process)
    monkeypatch.setattr(subprocess, "Popen", launch)
    queued = []
    monkeypatch.setattr(
        plugin_runner.threading,
        "Thread",
        lambda **kw: SimpleNamespace(start=lambda: queued.append(kw["target"])),
    )
    item = SimpleNamespace(
        params=[], command="benign", type="modal", run_on_target=False, label="Output"
    )
    builder._execute_plugin_with_target_select(item, screen_bounds=origin)
    command = launch.call_args.args[0]
    assert (
        monitor.restore_context(
            json.loads(command[command.index("--screen-bounds") + 1])
        )
        == origin
    )
    execute.assert_not_called()
    queued[0]()
    execute.assert_called_once_with(
        [target],
        "benign",
        "modal",
        run_on_target=False,
        label="Output",
        screen_bounds=origin,
    )
