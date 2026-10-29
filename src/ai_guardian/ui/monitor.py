"""Display-only monitor context and placement; safe to load in an isolated child.

No eager package, GUI or third-party imports: support's user-only reviewer loads
this installed file by absolute path and uses only its stdlib helpers. Geometry
uses desktop coordinates (Aqua points,
X11 pixels, per-monitor-aware Win32 pixels), never a later pointer/focus lookup.
"""

import ctypes
import json
import logging
import os
import platform
import subprocess
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)
Rect = tuple[int, int, int, int]

# Shared by both complete Cocoa providers. Resolve inside the native child too:
# launching osascript can take long enough for the desktop topology to change.
COCOA_PLACE_WINDOW = r"""
function placeWindowOnTargetScreen(window, bounds, monitorID) {
    if (!bounds && !monitorID) return;
    var screens = $.NSScreen.screens;
    if (!screens || Number(screens.count) === 0) throw new Error('Display unavailable');
    var main = screens.objectAtIndex(0).frame;
    var chosen = screens.objectAtIndex(0);
    for (var i = 0; i < Number(screens.count); i++) {
        var candidate = screens.objectAtIndex(i), r = candidate.visibleFrame;
        var matches = monitorID
            ? String(ObjC.unwrap(candidate.deviceDescription.objectForKey('NSScreenNumber'))) === monitorID
            : bounds && bounds.length === 4 &&
                Math.abs(Number(r.origin.x) - Number(main.origin.x) - bounds[0]) <= 1 &&
                Math.abs(Number(main.origin.y) + Number(main.size.height) - Number(r.origin.y) - Number(r.size.height) - bounds[1]) <= 1 &&
                Math.abs(Number(r.size.width) - bounds[2]) <= 1 &&
                Math.abs(Number(r.size.height) - bounds[3]) <= 1;
        if (matches) { chosen = candidate; break; }
    }
    var area = chosen.visibleFrame, size = window.frame.size;
    if (Number(size.width) > Number(area.size.width) - 32 ||
        Number(size.height) > Number(area.size.height) - 32) {
        // Before first display this allows the complete scrollable Tk provider.
        // After display the lifecycle treats this as terminal, never a restart.
        throw new Error('Complete native layout does not fit this display');
    }
    window.setFrameOrigin($.NSMakePoint(
        Number(area.origin.x) + (Number(area.size.width) - Number(size.width)) / 2,
        Number(area.origin.y) + (Number(area.size.height) - Number(size.height)) / 2
    ));
}
"""


@dataclass(frozen=True)
class MonitorContext:
    bounds: Rect
    monitor_id: str
    scale: float = 1.0
    enforceable: bool = True
    source: str = "tray"


ScreenBounds = Rect | MonitorContext | dict[str, Any]
_origin: ContextVar[MonitorContext | Rect | None] = ContextVar(
    "modal_monitor", default=None
)


def monitor_json_default(value):
    if isinstance(value, MonitorContext):
        return asdict(value)
    raise TypeError("Value is not serializable")


def restore_context(value):
    """Validate inert display metadata, also accepting internal legacy rectangles."""
    if isinstance(value, MonitorContext):
        return value
    raw = value.get("bounds") if isinstance(value, dict) else value
    if not isinstance(raw, (tuple, list)) or len(raw) != 4:
        return None
    if any(type(v) is not int or abs(v) > 1_000_000 for v in raw):
        return None
    rect: Rect = (raw[0], raw[1], raw[2], raw[3])
    if rect[2] <= 0 or rect[3] <= 0:
        return None
    if not isinstance(value, dict):
        return rect
    name = value.get("monitor_id", "")
    scale = value.get("scale", 1.0)
    if not isinstance(name, str) or len(name) > 200:
        return None
    if type(scale) not in (int, float) or not 0.1 <= scale <= 16:
        return None
    return MonitorContext(
        rect,
        name,
        float(scale),
        value.get("enforceable") is True,
        "unavailable" if value.get("source") == "unavailable" else "tray",
    )


def current_origin():
    value = _origin.get()
    if value is None:
        try:
            value = restore_context(
                json.loads(os.environ.get("_AI_GUARDIAN_MODAL_MONITOR", "null"))
            )
        except (ValueError, TypeError):
            return None
    return value


@contextmanager
def monitor_origin(value):
    token = _origin.set(restore_context(value))
    try:
        yield
    finally:
        _origin.reset(token)


def screen_payload(value):
    return asdict(value) if isinstance(value, MonitorContext) else value


def list_monitors() -> tuple[MonitorContext, ...]:
    """Primary first. Inventory failure is not permission to reuse stale geometry."""
    try:
        system = platform.system()
        if system == "Windows":
            return _windows_monitors()
        if system == "Darwin":
            # Never import AppKit into a Tk child before Tk initializes.
            script = """ObjC.import('Cocoa'); var screens=$.NSScreen.screens;
var base=screens.objectAtIndex(0).frame; var result=[];
for(var i=0;i<screens.count;i++) { var s=screens.objectAtIndex(i), r=s.visibleFrame;
result.push({bounds:[Math.round(Number(r.origin.x)-Number(base.origin.x)),
Math.round(Number(base.origin.y)+Number(base.size.height)-Number(r.origin.y)-Number(r.size.height)),
Math.floor(Number(r.size.width)),Math.floor(Number(r.size.height))],monitor_id:String(ObjC.unwrap(s.deviceDescription.objectForKey('NSScreenNumber'))),scale:1,enforceable:true}); }
JSON.stringify(result);"""
            result = subprocess.run(
                ["/usr/bin/osascript", "-l", "JavaScript", "-e", script],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if result.returncode == 0:
                return tuple(
                    c
                    for v in json.loads(result.stdout)
                    if isinstance(c := restore_context(v), MonitorContext)
                )
        if system == "Linux":
            return _linux_monitors()
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
        logger.debug("Display inventory unavailable")
    return ()


def _windows_monitors() -> tuple[MonitorContext, ...]:
    from ctypes import wintypes as w

    class Info(ctypes.Structure):
        _fields_ = [
            ("size", w.DWORD),
            ("frame", w.RECT),
            ("work", w.RECT),
            ("flags", w.DWORD),
            ("device", w.WCHAR * 32),
        ]

    class Device(ctypes.Structure):
        _fields_ = [
            ("size", w.DWORD),
            ("name", w.WCHAR * 32),
            ("description", w.WCHAR * 128),
            ("flags", w.DWORD),
            ("identity", w.WCHAR * 128),
            ("key", w.WCHAR * 128),
        ]

    user = getattr(ctypes, "WinDLL")("user32", use_last_error=True)
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    user.GetMonitorInfoW.argtypes = [w.HANDLE, ctypes.POINTER(Info)]
    user.EnumDisplayDevicesW.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        ctypes.POINTER(Device),
        w.DWORD,
    ]
    entries = []
    callback_type = getattr(ctypes, "WINFUNCTYPE")(
        w.BOOL, w.HANDLE, w.HDC, ctypes.POINTER(w.RECT), w.LPARAM
    )

    def visit(handle, _dc, _rect, _data):
        info = Info()
        info.size = ctypes.sizeof(info)
        if user.GetMonitorInfoW(handle, ctypes.byref(info)):
            r = info.work
            device = Device()
            device.size = ctypes.sizeof(device)
            identity = info.device
            if (
                user.EnumDisplayDevicesW(info.device, 0, ctypes.byref(device), 1)
                and device.identity
            ):
                identity = device.identity
            scale = 1.0
            try:
                dpi_x, dpi_y = w.UINT(), w.UINT()
                shcore = ctypes.WinDLL("shcore")
                shcore.GetDpiForMonitor.argtypes = [
                    w.HANDLE,
                    ctypes.c_int,
                    ctypes.POINTER(w.UINT),
                    ctypes.POINTER(w.UINT),
                ]
                if (
                    shcore.GetDpiForMonitor(
                        handle, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
                    )
                    == 0
                ):
                    scale = dpi_x.value / 96.0 if dpi_x.value else 1.0
            except (OSError, AttributeError):
                logger.debug("Monitor DPI unavailable; using native pixel coordinates")
            entries.append(
                (
                    not bool(info.flags & 1),
                    MonitorContext(
                        (r.left, r.top, r.right - r.left, r.bottom - r.top),
                        identity,
                        scale=scale,
                    ),
                )
            )
        return True

    try:
        user.EnumDisplayMonitors(None, None, callback_type(visit), 0)
    finally:
        if previous:
            user.SetThreadDpiAwarenessContext(previous)
    return tuple(item[1] for item in sorted(entries, key=lambda item: item[0]))


def _linux_monitors() -> tuple[MonitorContext, ...]:
    # Independent desktop X connection: no subprocess or Tk on the tray loop.
    # XRandR coordinates match X11 Tk, including mixed display scaling.
    # Wayland may ignore XWayland positions; that context is explicitly qualified.
    if not os.environ.get("DISPLAY"):
        return ()
    from ctypes import c_int, c_ulong, c_void_p, POINTER, byref

    class Info(ctypes.Structure):
        _fields_ = [
            ("name", c_ulong),
            ("primary", c_int),
            ("automatic", c_int),
            ("noutput", c_int),
            ("x", c_int),
            ("y", c_int),
            ("width", c_int),
            ("height", c_int),
            ("mwidth", c_int),
            ("mheight", c_int),
            ("outputs", POINTER(c_ulong)),
        ]

    x = ctypes.CDLL("libX11.so.6")
    randr = ctypes.CDLL("libXrandr.so.2")
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XOpenDisplay.restype = c_void_p
    x.XDefaultRootWindow.argtypes = [c_void_p]
    x.XDefaultRootWindow.restype = c_ulong
    x.XInternAtom.argtypes = [c_void_p, ctypes.c_char_p, c_int]
    x.XInternAtom.restype = c_ulong
    x.XGetAtomName.argtypes = [c_void_p, c_ulong]
    x.XGetAtomName.restype = c_void_p
    x.XFree.argtypes = [c_void_p]
    x.XCloseDisplay.argtypes = [c_void_p]
    x.XGetWindowProperty.argtypes = [
        c_void_p,
        c_ulong,
        c_ulong,
        ctypes.c_long,
        ctypes.c_long,
        c_int,
        c_ulong,
        POINTER(c_ulong),
        POINTER(c_int),
        POINTER(c_ulong),
        POINTER(c_ulong),
        POINTER(c_void_p),
    ]
    randr.XRRGetMonitors.argtypes = [c_void_p, c_ulong, c_int, POINTER(c_int)]
    randr.XRRGetMonitors.restype = POINTER(Info)
    randr.XRRFreeMonitors.argtypes = [POINTER(Info)]
    randr.XRRQueryVersion.argtypes = [c_void_p, POINTER(c_int), POINTER(c_int)]
    connection = x.XOpenDisplay(None)
    if not connection:
        return ()
    infos = None
    try:
        major, minor = c_int(), c_int()
        if not randr.XRRQueryVersion(connection, byref(major), byref(minor)) or (
            major.value,
            minor.value,
        ) < (1, 5):
            return ()  # Avoid a fatal X error on pre-1.5 display servers.
        root = x.XDefaultRootWindow(connection)

        def prop(window, name):
            atom = x.XInternAtom(connection, name.encode("ascii"), True)
            if not atom:
                return ()
            actual, count, remaining = c_ulong(), c_ulong(), c_ulong()
            fmt, data = c_int(), c_void_p()
            status = x.XGetWindowProperty(
                connection,
                window,
                atom,
                0,
                4096,
                False,
                0,
                byref(actual),
                byref(fmt),
                byref(count),
                byref(remaining),
                byref(data),
            )
            try:
                if status == 0 and data and fmt.value == 32:
                    values = ctypes.cast(data, POINTER(c_ulong))
                    return tuple(values[i] for i in range(min(count.value, 4096)))
                return ()
            finally:
                if data:
                    x.XFree(data)

        areas = prop(root, "_NET_WORKAREA")
        desktop = prop(root, "_NET_CURRENT_DESKTOP")
        start = 4 * (desktop[0] if desktop else 0)
        work = areas[start : start + 4]
        count = c_int()
        infos = randr.XRRGetMonitors(connection, root, True, byref(count))
        entries = []
        for i in range(min(count.value, 128)) if infos else ():
            info = infos[i]
            name_pointer = x.XGetAtomName(connection, info.name)
            try:
                name = (
                    ctypes.string_at(name_pointer).decode("utf-8", errors="replace")
                    if name_pointer
                    else str(info.name)
                )
            finally:
                if name_pointer:
                    x.XFree(name_pointer)
            bounds = (info.x, info.y, info.width, info.height)
            if len(work) == 4:
                left, top = max(info.x, work[0]), max(info.y, work[1])
                right, bottom = min(info.x + info.width, work[0] + work[2]), min(
                    info.y + info.height, work[1] + work[3]
                )
                if right > left and bottom > top:
                    bounds = (left, top, right - left, bottom - top)
            entries.append(
                (
                    not bool(info.primary),
                    MonitorContext(
                        bounds,
                        name,
                        enforceable=not bool(os.environ.get("WAYLAND_DISPLAY"))
                        and len(work) == 4,
                    ),
                )
            )
        return tuple(item[1] for item in sorted(entries, key=lambda item: item[0]))
    finally:
        if infos:
            randr.XRRFreeMonitors(infos)
        x.XCloseDisplay(connection)


def tray_anchor(icon):
    """Use the tray/menu's own geometry, not focus or a keyboard user's pointer."""
    if platform.system() == "Windows" and icon is not None:
        from ctypes import wintypes as w

        class Identifier(ctypes.Structure):
            _fields_ = [
                ("size", w.DWORD),
                ("hwnd", w.HWND),
                ("uid", w.UINT),
                ("guid", ctypes.c_byte * 16),
            ]

        identifier = Identifier()
        identifier.size = ctypes.sizeof(identifier)
        identifier.hwnd = getattr(icon, "_hwnd", None)
        identifier.uid = id(icon) & 0xFFFFFFFF
        rect = w.RECT()
        shell = ctypes.WinDLL("shell32")
        user = ctypes.WinDLL("user32")
        user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        try:
            if (
                shell.Shell_NotifyIconGetRect(
                    ctypes.byref(identifier), ctypes.byref(rect)
                )
                == 0
            ):
                return ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        finally:
            if previous:
                user.SetThreadDpiAwarenessContext(previous)
    elif platform.system() == "Linux":
        try:
            from gi.repository import Gtk

            # pystray._menu is the abstract menu model, not a GTK window.
            menu = getattr(icon, "_menu_handle", None)
            if menu is not None and hasattr(menu, "get_mapped") and menu.get_mapped():
                window = menu.get_window()
                if window is not None:
                    ok, x, y = window.get_origin()
                    if ok:
                        scale = window.get_scale_factor()
                        return x * scale, y * scale
            # GTK can unmap the popup before activation, especially with a
            # keyboard. A local StatusIcon still supplies its own rectangle.
            status_icon = getattr(icon, "_status_icon", None)
            if status_icon is not None:
                geometry = status_icon.get_geometry()
                if geometry and geometry[0]:
                    _ok, screen, rect, _orientation = geometry
                    scale = screen.get_root_window().get_scale_factor()
                    return (rect.x + rect.width / 2) * scale, (
                        rect.y + rect.height / 2
                    ) * scale
            event = Gtk.get_current_event()
            # Keyboard activation must never use unrelated pointer coordinates.
            if event is not None and "button" in str(event.type).lower():
                ok, x, y = event.get_root_coords()
                if ok:
                    from gi.repository import Gdk

                    scale = Gdk.get_default_root_window().get_scale_factor()
                    return x * scale, y * scale
        except (ImportError, ValueError, AttributeError, TypeError, RuntimeError):
            logger.debug("Tray host does not expose menu geometry")
    return None


def capture_monitor(icon=None):
    monitors = list_monitors()
    if len(monitors) == 1:
        return None  # Preserve ordinary single-monitor provider/WM behavior.
    try:
        anchor = tray_anchor(icon)
    except (OSError, AttributeError, TypeError, ValueError):
        anchor = None
    if anchor is not None and monitors:
        x, y = anchor
        # Work areas exclude the panel itself; use the nearest work area.
        return min(
            monitors,
            key=lambda m: max(m.bounds[0] - x, 0, x - (m.bounds[0] + m.bounds[2])) ** 2
            + max(m.bounds[1] - y, 0, y - (m.bounds[1] + m.bounds[3])) ** 2,
        )
    # An unavailable origin is explicit, not a claim that primary is the tray.
    fallback = monitors[0].bounds if monitors else (0, 0, 800, 600)
    return MonitorContext(fallback, "", enforceable=False, source="unavailable")


def _resolve_monitor(value):
    context = restore_context(value if value is not None else current_origin())
    if isinstance(context, MonitorContext):
        monitors = list_monitors()
        if not monitors:
            return None
        return next(
            (
                m
                for m in monitors
                if m.monitor_id and m.monitor_id == context.monitor_id
            ),
            monitors[0],
        )
    return context


def resolve_bounds(value):
    context = _resolve_monitor(value)
    return context.bounds if isinstance(context, MonitorContext) else context


def center_geometry(width, height, bounds, *, margin=0):
    context = restore_context(bounds)
    if context is None:
        return None
    x, y, sw, sh = context.bounds if isinstance(context, MonitorContext) else context
    width, height = min(max(1, int(width)), max(1, sw - margin)), min(
        max(1, int(height)), max(1, sh - margin)
    )
    return x + (sw - width) // 2, y + (sh - height) // 2, width, height


def prepare_tk_display():
    """Tk and Win32 monitor capture must use the same physical-pixel space."""
    if platform.system() == "Windows":
        try:
            user = ctypes.WinDLL("user32")
            user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (OSError, AttributeError):
            logger.debug("Per-monitor DPI awareness unavailable")


def place_tk_window(window, value, width, height):
    context = restore_context(value if value is not None else current_origin())
    active = _resolve_monitor(context)
    bounds = active.bounds if isinstance(active, MonitorContext) else active
    margin = round(64 * active.scale) if isinstance(active, MonitorContext) else 0
    geometry = center_geometry(width, height, bounds, margin=margin)
    if geometry is None:
        if isinstance(context, MonitorContext):
            # No stale coordinates: small, WM-positioned, resizable recovery UI.
            window.geometry(f"{min(width, 800)}x{min(height, 600)}")
            window.title(
                f"{window.title()} — Display unavailable; move window to a visible screen"
            )
            # Do not let a later fixed minimum prevent the user's recovery move
            # or resize when the desktop cannot report its current work area.
            window.after_idle(lambda: _fit_tk_window(window, 320, 200))
        return False  # Let the WM choose a visible position, never stale coordinates.
    if placement_notice(context) or placement_notice(active):
        window.title(f"{window.title()} — Move this window to the tray screen")
    x, y, width, height = geometry
    window.geometry(f"{width}x{height}+{x}+{y}")
    if isinstance(context, MonitorContext):
        # Apply after the caller has installed any fixed minimum. Content frames
        # retain their scrollbars; controls must not force the outer window offscreen.
        window.after_idle(
            lambda: _fit_tk_window(
                window,
                width,
                height,
                (max(1, bounds[2] - margin), max(1, bounds[3] - margin)),
            )
        )
    return True


def _fit_tk_window(window, width, height, maximum=None):
    try:
        if window.winfo_exists():
            minimum = window.minsize()
            window.minsize(min(minimum[0], width), min(minimum[1], height))
            window.resizable(True, True)
            if maximum is not None:
                window.maxsize(*maximum)
    except Exception as exc:
        # Delayed, non-security GUI teardown; Tk may already be destroyed.
        logger.debug(
            "Window placement constraints unavailable (%s)", type(exc).__name__
        )


def tk_scrollable_content(window, *, padding=16, style=None, fit_width=False):
    """Keep full form/review content reachable with a permanently reserved footer.

    Runtime-only stdlib Tk imports also work in support's isolated reviewer.
    No fields, values, consent defaults, event loop or provider policy live here.
    Width-fitting content wraps labels instead of pushing inline controls beyond
    the viewport; other callers retain the existing two-axis scrolling behavior.
    """
    import tkinter as tk
    from tkinter import ttk

    options = {"style": style} if style else {}
    shell = ttk.Frame(window, padding=padding, **options)
    shell.grid(row=0, column=0, sticky="nsew")
    window.rowconfigure(0, weight=1)
    window.columnconfigure(0, weight=1)
    shell.rowconfigure(0, weight=1)
    shell.columnconfigure(0, weight=1)
    canvas = tk.Canvas(shell, highlightthickness=0)
    canvas.grid(row=0, column=0, sticky="nsew")
    vertical = ttk.Scrollbar(shell, command=canvas.yview)
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal = ttk.Scrollbar(shell, orient="horizontal", command=canvas.xview)
    horizontal.grid(row=1, column=0, sticky="ew")
    if fit_width:
        horizontal.grid_remove()
    canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    body = ttk.Frame(canvas, **options)
    item = canvas.create_window((0, 0), window=body, anchor="nw")

    def resize(_event=None):
        canvas.itemconfigure(
            item,
            width=(
                max(1, canvas.winfo_width())
                if fit_width
                else max(body.winfo_reqwidth(), canvas.winfo_width())
            ),
            height=max(body.winfo_reqheight(), canvas.winfo_height()),
        )
        canvas.configure(scrollregion=canvas.bbox("all"))

    body.bind("<Configure>", resize)
    canvas.bind("<Configure>", resize)

    def reveal(event):
        widget = event.widget
        if not str(widget).startswith(str(body) + "."):
            return
        # Tab traversal must not focus an entry outside the viewport.
        for offset, extent, start, visible, total, move in (
            (
                widget.winfo_rootx() - body.winfo_rootx(),
                widget.winfo_width(),
                canvas.canvasx(0),
                canvas.winfo_width(),
                body.winfo_width(),
                canvas.xview_moveto,
            ),
            (
                widget.winfo_rooty() - body.winfo_rooty(),
                widget.winfo_height(),
                canvas.canvasy(0),
                canvas.winfo_height(),
                body.winfo_height(),
                canvas.yview_moveto,
            ),
        ):
            if offset < start or offset + extent > start + visible:
                move(max(0, offset - 8) / max(1, total))

    window.bind("<FocusIn>", reveal, add="+")
    footer = ttk.Frame(shell, **options)
    footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
    return body, footer


def placement_notice(value, *, browser=False):
    context = restore_context(value)
    if context is None:
        return ""
    if browser:
        return "The browser cannot place this dialog on the tray's physical screen automatically. Move this window to the screen where you opened the tray action before continuing."
    if isinstance(context, MonitorContext) and not context.enforceable:
        return "This desktop does not expose or enforce the tray monitor's position. Move this window to the physical screen where you opened the tray action before continuing."
    return ""
