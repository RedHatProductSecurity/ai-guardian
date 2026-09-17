"""Small native forms used by tray-managed sandbox actions."""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

ScreenBounds = Tuple[int, int, int, int]


def _rect_components(rect) -> Optional[Tuple[float, float, float, float]]:
    """Return an AppKit rectangle as ``(x, y, width, height)``."""
    try:
        origin = rect.origin
        size = rect.size
        return (
            float(origin.x),
            float(origin.y),
            float(size.width),
            float(size.height),
        )
    except (AttributeError, TypeError, ValueError):
        return None


def _point_components(point) -> Optional[Tuple[float, float]]:
    """Return an AppKit point as ``(x, y)``."""
    try:
        return float(point.x), float(point.y)
    except (AttributeError, TypeError, ValueError):
        return None


def _point_in_rect(point, rect) -> bool:
    """Return whether an AppKit point is inside an AppKit rectangle."""
    point_components = _point_components(point)
    rect_components = _rect_components(rect)
    if point_components is None or rect_components is None:
        return False
    point_x, point_y = point_components
    rect_x, rect_y, rect_width, rect_height = rect_components
    return (
        rect_x <= point_x < rect_x + rect_width
        and rect_y <= point_y < rect_y + rect_height
    )


def _tk_screen_bounds(cocoa_rect, cocoa_main_rect) -> Optional[ScreenBounds]:
    """Convert a Cocoa screen rectangle to Tk's top-left coordinate system.

    Cocoa uses a bottom-left origin while Tk uses a top-left origin.  The
    conversion is kept separate from AppKit access so it can be tested without
    a GUI display.
    """
    rect = _rect_components(cocoa_rect)
    main_rect = _rect_components(cocoa_main_rect)
    if rect is None or main_rect is None:
        return None

    x, y, width, height = rect
    main_x, main_y, _main_width, main_height = main_rect
    return (
        int(round(x - main_x)),
        int(round(main_y + main_height - (y + height))),
        int(round(width)),
        int(round(height)),
    )


def _status_item_screen(icon):
    """Return the display containing a macOS pystray status item, if any."""
    if icon is None:
        return None
    try:
        status_item = getattr(icon, "_status_item", None)
        button = status_item.button()
        window = button.window()
        return window.screen()
    except Exception:
        return None


def _event_screen(AppKit):
    """Return the display containing AppKit's current menu event, if any."""
    try:
        # AppKit exposes the current event through NSApplication.  NSEvent's
        # Objective-C class method is not exported by every PyObjC build.
        event = AppKit.NSApplication.sharedApplication().currentEvent()
        if event is None:
            return None
        window = event.window()
        if window is None:
            return None
        return window.screen()
    except Exception:
        return None


def _get_tray_screen_bounds(icon=None) -> Optional[ScreenBounds]:
    """Return the visible bounds of the display containing the tray menu.

    This is intentionally captured by the tray process before a Tk child is
    started.  Importing AppKit in the child before ``tk.Tk()`` can trigger a
    macOS Tk initialization crash, so the child receives plain geometry data.
    The current AppKit event is preferred because its window identifies the
    display that actually dispatched the menu action. The status item's
    window and pointer location are fallbacks for keyboard and automation
    paths. ``None`` preserves the existing window-manager placement fallback.
    """
    if platform.system() != "Darwin":
        return None

    try:
        import AppKit

        screens = tuple(AppKit.NSScreen.screens() or ())
        if len(screens) < 2:
            return None
        # Tk's Aqua virtual-screen origin is based on the display that owns
        # the menu bar, which AppKit exposes as screens[0].  mainScreen can
        # instead be the display containing keyboard focus and is not a safe
        # coordinate-system baseline.
        main_frame = screens[0].frame()
        screen = _event_screen(AppKit)
        if screen is None:
            screen = _status_item_screen(icon)
        if screen is None:
            pointer = AppKit.NSEvent.mouseLocation()
            for candidate in screens:
                if _point_in_rect(pointer, candidate.frame()):
                    screen = candidate
                    break
        if screen is not None:
            return _tk_screen_bounds(screen.visibleFrame(), main_frame)
    except Exception as exc:
        logger.debug("Could not determine the tray display bounds: %s", exc)
    return None


def _center_window_geometry(
    window_width: int, window_height: int, screen_bounds
) -> Optional[Tuple[int, int, int, int]]:
    """Return centered ``(x, y, width, height)`` geometry for a screen."""
    try:
        screen_x, screen_y, screen_width, screen_height = (
            int(value) for value in screen_bounds
        )
        window_width = min(max(1, int(window_width)), screen_width)
        window_height = min(max(1, int(window_height)), screen_height)
    except (TypeError, ValueError):
        return None
    if screen_width <= 0 or screen_height <= 0:
        return None

    return (
        screen_x + (screen_width - window_width) // 2,
        screen_y + (screen_height - window_height) // 2,
        window_width,
        window_height,
    )


def _place_window_on_screen(
    window, screen_bounds, window_width: int, window_height: int
) -> bool:
    """Center a Tk window on explicit screen bounds when available."""
    geometry = _center_window_geometry(window_width, window_height, screen_bounds)
    if geometry is None:
        return False
    x, y, width, height = geometry
    # The leading plus introduces an absolute virtual-screen coordinate. A
    # negative value therefore needs the ``+-N`` form; ``-N`` means an offset
    # from the right or bottom edge in Tk geometry syntax.
    window.geometry(f"{width}x{height}+{x}+{y}")
    return True


def _scroll_canvas(event, canvas) -> str:
    """Scroll a Tk canvas for native mouse-wheel events."""
    button = getattr(event, "num", None)
    delta = getattr(event, "delta", 0)
    if button == 4:
        units = -1
    elif button == 5:
        units = 1
    elif delta:
        delta = int(delta)
        magnitude = max(1, abs(delta) // 120)
        units = -magnitude if delta > 0 else magnitude
    else:
        return "break"
    canvas.yview_scroll(units, "units")
    return "break"


def _merge_browse_paths(current: str, selected) -> str:
    """Append selected paths to a comma-separated form field."""
    existing = [
        path.strip()
        for path in str(current or "").replace("\n", ",").split(",")
        if path.strip()
    ]
    if isinstance(selected, str):
        selected = [selected] if selected else []
    for path in selected or ():
        path = str(path).strip()
        if path and path not in existing:
            existing.append(path)
    return ", ".join(existing)


def _browse_selection(current: str, selected, kind: str) -> str:
    """Apply a file or directory browser selection to a form field."""
    if kind == "directory":
        selected_path = str(selected or "").strip()
        return selected_path or str(current or "")
    return _merge_browse_paths(current, selected)


def _browse_initialdir(value: str) -> Optional[str]:
    """Return a usable initial directory for a path browser."""
    first_path = str(value or "").replace("\n", ",").split(",", 1)[0].strip()
    if not first_path:
        return None
    candidate = Path(first_path).expanduser()
    if candidate.is_dir():
        return str(candidate)
    parent = candidate.parent
    return str(parent) if parent.is_dir() else None


def _dynamic_default_value(specification: Dict[str, Any], value: str) -> Optional[str]:
    """Build a dependent default value from the selected field value."""
    value = str(value or "").strip()
    if not value:
        return None
    max_length = specification.get("value_max_length")
    if isinstance(max_length, int) and max_length > 0:
        value = value[:max_length]
    separator = str(specification.get("separator", "-"))
    return (
        f"{specification.get('prefix', '')}{value}"
        f"{separator}{specification.get('suffix', '')}"
    )


def _local_image_choices():
    """Return locally available AI Guardian support-image references.

    The image browser runs in the short-lived form process, so an unavailable
    or disconnected container engine must only result in an empty list.  The
    explicit image field remains available for custom images and OpenShell
    Dockerfile paths.
    """
    configured_engine = os.environ.get("CONTAINER_ENGINE")
    engines = [configured_engine] if configured_engine else ["podman", "docker"]
    choices = []
    for engine in engines:
        if not engine:
            continue
        try:
            result = subprocess.run(
                [
                    engine,
                    "image",
                    "ls",
                    "--filter",
                    "label=ai-guardian.support-image=true",
                    "--format",
                    "{{.Repository}}:{{.Tag}}",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode != 0:
            continue
        for line in (result.stdout or "").splitlines():
            image = line.strip()
            if not image or image.startswith("<none>") or image in choices:
                continue
            choices.append(image)
    return choices


def _show_local_image_picker(
    parent, variable, screen_bounds: Optional[ScreenBounds] = None
) -> None:
    """Let the user select a labeled local AI Guardian image."""
    import tkinter as tk
    from tkinter import ttk

    choices = _local_image_choices()
    dialog = tk.Toplevel(parent)
    dialog.title("Select local AI Guardian image")
    dialog.geometry("620x300")
    _place_window_on_screen(dialog, screen_bounds, 620, 300)
    dialog.minsize(440, 220)
    dialog.transient(parent)
    dialog.rowconfigure(1, weight=1)
    dialog.columnconfigure(0, weight=1)

    ttk.Label(
        dialog,
        text=(
            "Images labeled ai-guardian.support-image=true are shown. "
            "Custom references can be typed in the form."
        ),
        justify="left",
        wraplength=580,
    ).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))

    list_frame = ttk.Frame(dialog, padding=(12, 0, 12, 0))
    list_frame.grid(row=1, column=0, sticky="nsew")
    list_frame.rowconfigure(0, weight=1)
    list_frame.columnconfigure(0, weight=1)
    listbox = tk.Listbox(list_frame, exportselection=False)
    listbox.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    listbox.configure(yscrollcommand=scrollbar.set)
    for image in choices:
        listbox.insert(tk.END, image)

    current = str(variable.get() or "")
    if current in choices:
        listbox.selection_set(choices.index(current))
        listbox.see(choices.index(current))
    elif choices:
        listbox.selection_set(0)

    status = "" if choices else "No labeled local AI Guardian images were found."
    ttk.Label(dialog, text=status, foreground="#666666").grid(
        row=2, column=0, sticky="w", padx=12, pady=(8, 0)
    )

    buttons = ttk.Frame(dialog, padding=12)
    buttons.grid(row=3, column=0, sticky="ew")
    buttons.columnconfigure(0, weight=1)

    def close() -> None:
        dialog.destroy()

    def select() -> None:
        selected = listbox.curselection()
        if selected:
            variable.set(listbox.get(selected[0]))
        close()

    ttk.Button(buttons, text="Cancel", command=close).grid(row=0, column=0, sticky="w")
    ttk.Button(
        buttons,
        text="Select",
        command=select,
        state="normal" if choices else "disabled",
    ).grid(row=0, column=1, sticky="e", padx=(8, 0))
    listbox.bind("<Double-Button-1>", lambda _event: select())
    dialog.bind("<Return>", lambda _event: select())
    dialog.bind("<Escape>", lambda _event: close())
    dialog.protocol("WM_DELETE_WINDOW", close)
    try:
        dialog.grab_set()
    except tk.TclError:
        # Some desktop environments reject nested grabs; the picker remains
        # usable as a transient window in that case.
        pass


def _show_tkinter_form(
    title: str,
    message: str,
    fields: Iterable[Dict[str, Any]],
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> Optional[Dict[str, Any]]:
    """Show a blocking Tk form and return its values, or ``None`` on cancel."""
    import tkinter as tk
    from tkinter import filedialog, ttk

    from ai_guardian.tui.display import _ensure_tcl_library

    _ensure_tcl_library()
    field_list = tuple(fields)
    controls = {}
    control_widgets = {}
    field_labels = {}
    enabled_states = {}
    dynamic_defaults = {}
    result: Dict[str, Any] = {}

    root = tk.Tk()
    root.title(title)
    root.geometry("760x680")
    _place_window_on_screen(root, screen_bounds, 760, 680)
    root.minsize(620, 380)
    root.resizable(True, True)
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)
    container = ttk.Frame(root, padding=12)
    container.grid(row=0, column=0, sticky="nsew")
    container.rowconfigure(0, weight=1)
    container.columnconfigure(0, weight=1)
    canvas = tk.Canvas(container, highlightthickness=0)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    canvas.configure(yscrollcommand=scrollbar.set)
    frame = ttk.Frame(canvas, padding=4)
    frame_window = canvas.create_window((0, 0), window=frame, anchor="nw")
    frame.columnconfigure(1, weight=1)

    def update_scroll_region(_event=None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    def resize_form(event) -> None:
        canvas.itemconfigure(frame_window, width=event.width)

    def scroll_form(event):
        return _scroll_canvas(event, canvas)

    frame.bind("<Configure>", update_scroll_region)
    canvas.bind("<Configure>", resize_form)
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        root.bind(sequence, scroll_form, add="+")
    ttk.Label(frame, text=message, justify="left", wraplength=600).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 14)
    )

    row = 1
    for field in field_list:
        name = str(field.get("name", ""))
        label = str(field.get("label", name))
        if field.get("required"):
            label += " *"
        label_widget = ttk.Label(frame, text=label)
        label_widget.grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
        field_labels[name] = [label_widget]

        kind = field.get("type", "text")
        default = field.get("default", "")
        if kind == "bool":
            variable = tk.BooleanVar(value=bool(default))
            control = ttk.Checkbutton(frame, variable=variable)
            control.grid(row=row, column=1, sticky="w", pady=4)
            widgets = [control]
        elif kind == "choice":
            choices = [str(choice) for choice in field.get("choices", ())]
            variable = tk.StringVar(value=str(default))
            control = ttk.Combobox(
                frame,
                textvariable=variable,
                values=choices,
                state="normal" if field.get("editable") else "readonly",
                width=int(field.get("width", 44)),
            )
            if choices and str(default) not in choices and not field.get("editable"):
                variable.set(choices[0])
            control.grid(row=row, column=1, sticky="w", pady=4)
            widgets = [control]
        elif kind == "image":
            variable = tk.StringVar(value="" if default is None else str(default))
            control_frame = ttk.Frame(frame)
            control_frame.grid(row=row, column=1, sticky="ew", pady=4)
            control = ttk.Entry(
                control_frame,
                textvariable=variable,
                width=int(field.get("width", 44)),
            )
            control.grid(row=0, column=0, sticky="ew")
            control_frame.columnconfigure(0, weight=1)
            browse_button = ttk.Button(
                control_frame,
                text="Browse...",
                command=lambda variable=variable: _show_local_image_picker(
                    root, variable, screen_bounds
                ),
            )
            browse_button.grid(row=0, column=1, padx=(6, 0))
            widgets = [control, browse_button]
        elif kind in {"file", "directory"}:
            variable = tk.StringVar(value="" if default is None else str(default))
            control_frame = ttk.Frame(frame)
            control_frame.grid(row=row, column=1, sticky="ew", pady=4)
            control = ttk.Entry(
                control_frame,
                textvariable=variable,
                width=int(field.get("width", 44)),
                show="*" if field.get("secret") else "",
            )
            control.grid(row=0, column=0, sticky="ew")
            control_frame.columnconfigure(0, weight=1)

            def browse(variable=variable, field=field, kind=kind):
                options = {"title": field.get("browse_title", "Select a path")}
                initialdir = _browse_initialdir(variable.get())
                if initialdir:
                    options["initialdir"] = initialdir
                if kind == "directory":
                    selected = filedialog.askdirectory(**options)
                elif field.get("multiple"):
                    selected = filedialog.askopenfilenames(**options)
                else:
                    selected = filedialog.askopenfilename(**options)
                variable.set(_browse_selection(variable.get(), selected, kind))

            browse_button = ttk.Button(control_frame, text="Browse...", command=browse)
            browse_button.grid(row=0, column=1, padx=(6, 0))
            widgets = [control, browse_button]
        else:
            variable = tk.StringVar(value="" if default is None else str(default))
            control = ttk.Entry(
                frame,
                textvariable=variable,
                width=int(field.get("width", 52)),
                show="*" if field.get("secret") else "",
            )
            control.grid(row=row, column=1, sticky="ew", pady=4)
            widgets = [control]
        controls[name] = (kind, variable)
        control_widgets[name] = widgets
        enabled_states[name] = True
        if isinstance(field.get("dynamic_default"), dict):
            dynamic_defaults[name] = str(variable.get())

        help_text = field.get("help")
        if help_text:
            help_label = ttk.Label(
                frame,
                text=str(help_text),
                justify="left",
                wraplength=460,
            )
            help_label.grid(row=row + 1, column=1, sticky="w", pady=(0, 4))
            field_labels[name].append(help_label)
            row += 2
        else:
            row += 1

    def refresh_enabled_states(*_args) -> None:
        """Enable or disable fields whose validity depends on another field."""
        for field in field_list:
            name = str(field.get("name", ""))
            condition = field.get("enabled_when")
            enabled = True
            if isinstance(condition, dict):
                dependency = controls.get(str(condition.get("field", "")))
                if dependency:
                    dependency_value = dependency[1].get()
                    expected = condition.get("values", condition.get("equals"))
                    if isinstance(expected, (list, tuple, set)):
                        enabled = dependency_value in expected
                    elif expected is not None:
                        enabled = dependency_value == expected
            enabled_states[name] = enabled
            for widget in control_widgets.get(name, ()):
                widget.state(["!disabled"] if enabled else ["disabled"])
            for widget in field_labels.get(name, ()):
                widget.state(["!disabled"] if enabled else ["disabled"])

    def refresh_dynamic_defaults(*_args) -> None:
        """Update untouched defaults that depend on another field."""
        for field in field_list:
            name = str(field.get("name", ""))
            specification = field.get("dynamic_default")
            if not isinstance(specification, dict):
                continue
            dependency = controls.get(str(specification.get("field", "")))
            target = controls.get(name)
            if not dependency or not target:
                continue
            target_variable = target[1]
            if str(target_variable.get()) != dynamic_defaults.get(name):
                continue
            updated = _dynamic_default_value(specification, dependency[1].get())
            if updated is None:
                continue
            target_variable.set(updated)
            dynamic_defaults[name] = updated

    for field in field_list:
        condition = field.get("enabled_when")
        if not isinstance(condition, dict):
            continue
        dependency = controls.get(str(condition.get("field", "")))
        if dependency:
            dependency[1].trace_add("write", refresh_enabled_states)
    for field in field_list:
        specification = field.get("dynamic_default")
        if not isinstance(specification, dict):
            continue
        dependency = controls.get(str(specification.get("field", "")))
        if dependency:
            dependency[1].trace_add("write", refresh_dynamic_defaults)
    refresh_enabled_states()

    error = tk.StringVar()
    error_row = row
    ttk.Label(frame, textvariable=error, foreground="#b00020").grid(
        row=error_row, column=0, columnspan=2, sticky="w", pady=(4, 0)
    )

    def submit() -> None:
        values: Dict[str, Any] = {}
        missing = []
        for field in field_list:
            name = str(field.get("name", ""))
            kind, variable = controls[name]
            value = variable.get()
            if not enabled_states.get(name, True):
                value = False if kind == "bool" else ""
            if kind != "bool" and isinstance(value, str):
                value = value.strip()
            values[name] = value
            if field.get("required") and enabled_states.get(name, True) and not value:
                missing.append(str(field.get("label", name)))
        if missing:
            error.set("Required: " + ", ".join(missing))
            return
        result.update(values)
        root.destroy()

    def cancel() -> None:
        root.destroy()

    button_row = error_row + 1
    ttk.Button(frame, text="Cancel", command=cancel).grid(
        row=button_row, column=0, sticky="w", pady=(14, 0)
    )
    ttk.Button(frame, text="Continue", command=submit).grid(
        row=button_row, column=1, sticky="e", pady=(14, 0)
    )
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.bind("<Escape>", lambda _event: cancel())
    root.bind("<Return>", lambda _event: submit())
    root.lift()
    root.focus_force()
    try:
        root.grab_set()
        root.attributes("-topmost", True)
        root.after(150, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        # Some desktop environments reject transient/topmost hints.  The form
        # remains usable as an ordinary modal window in that case.
        pass
    root.mainloop()
    return result or None


def _show_tkinter_form_subprocess(
    title: str,
    message: str,
    fields: Iterable[Dict[str, Any]],
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> Optional[Dict[str, Any]]:
    """Run a Tk form outside the tray process to isolate GUI toolkit state."""
    payload = json.dumps(
        {
            "title": title,
            "message": message,
            "fields": tuple(fields),
            "screen_bounds": screen_bounds,
        },
        ensure_ascii=False,
    )
    child = (
        "import json, sys; "
        "from ai_guardian.tray.sandbox_dialog import _show_tkinter_form; "
        "p=json.loads(sys.argv[1]); "
        "v=_show_tkinter_form(p['title'], p['message'], p['fields'], "
        "screen_bounds=p.get('screen_bounds')); "
        "print(json.dumps(v, ensure_ascii=False) if v is not None else '')"
    )
    try:
        process = subprocess.run(
            [sys.executable, "-c", child, payload],
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Sandbox form could not be shown: %s", exc)
        return None
    if process.returncode != 0:
        detail = (process.stderr or "").strip()
        logger.warning(
            "Sandbox form exited with code %s%s",
            process.returncode,
            f": {detail[:200]}" if detail else "",
        )
        return None
    output = (process.stdout or "").strip().splitlines()
    if not output:
        return None
    try:
        value = json.loads(output[-1])
    except json.JSONDecodeError:
        logger.warning("Sandbox form returned invalid JSON")
        return None
    return value if isinstance(value, dict) else None


def _show_tkinter_log(
    title: str,
    message: str,
    log_text: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> None:
    """Show captured sandbox output in a scrollable Tk window."""
    import tkinter as tk
    from tkinter import ttk

    from ai_guardian.tui.display import _ensure_tcl_library

    _ensure_tcl_library()
    root = tk.Tk()
    root.title(title)
    root.geometry("760x480")
    _place_window_on_screen(root, screen_bounds, 760, 480)
    root.minsize(520, 280)

    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)
    frame.rowconfigure(1, weight=1)
    frame.columnconfigure(0, weight=1)

    ttk.Label(frame, text=message, justify="left", wraplength=700).grid(
        row=0, column=0, sticky="w", pady=(0, 10)
    )
    log_frame = ttk.Frame(frame)
    log_frame.grid(row=1, column=0, sticky="nsew")
    log_frame.rowconfigure(0, weight=1)
    log_frame.columnconfigure(0, weight=1)
    text = tk.Text(log_frame, wrap="none", state="normal")
    text.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=text.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    text.configure(yscrollcommand=scrollbar.set)
    text.insert("1.0", log_text or "(no output)")
    text.configure(state="disabled")
    copy_status = tk.StringVar()

    def copy() -> None:
        copy_status.set(_copy_sandbox_log(log_text, clipboard_owner=root))

    ttk.Label(frame, textvariable=copy_status, justify="left").grid(
        row=2, column=0, sticky="w", pady=(8, 0)
    )

    def close() -> None:
        root.destroy()

    button_frame = ttk.Frame(frame)
    button_frame.grid(row=3, column=0, sticky="e", pady=(12, 0))
    ttk.Button(button_frame, text="Copy", command=copy).pack(side="left")
    ttk.Button(button_frame, text="Close", command=close).pack(side="left", padx=(8, 0))
    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<Escape>", lambda _event: close())
    root.lift()
    root.focus_force()
    try:
        root.grab_set()
        root.attributes("-topmost", True)
        root.after(150, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        # Some desktop environments reject transient/topmost hints.  The log
        # remains usable as an ordinary window in that case.
        pass
    root.mainloop()


def _show_tkinter_confirmation(
    title: str,
    message: str,
    expected_name: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> bool:
    """Show a destructive-action confirmation requiring the sandbox name."""
    import tkinter as tk
    from tkinter import ttk

    from ai_guardian.tui.display import _ensure_tcl_library

    _ensure_tcl_library()
    root = tk.Tk()
    root.title(title)
    root.geometry("560x250")
    _place_window_on_screen(root, screen_bounds, 560, 250)
    root.minsize(480, 220)
    root.resizable(True, False)
    root.columnconfigure(0, weight=1)

    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(0, weight=1)

    ttk.Label(frame, text=message, justify="left", wraplength=510).grid(
        row=0, column=0, sticky="w", pady=(0, 14)
    )
    ttk.Label(frame, text="Type the sandbox name to confirm:").grid(
        row=1, column=0, sticky="w"
    )
    name = tk.StringVar()
    entry = ttk.Entry(frame, textvariable=name)
    entry.grid(row=2, column=0, sticky="ew", pady=(4, 0))
    error = tk.StringVar()
    ttk.Label(frame, textvariable=error, foreground="#b00020").grid(
        row=3, column=0, sticky="w", pady=(6, 0)
    )

    confirmed = False

    def cancel() -> None:
        root.destroy()

    def confirm() -> None:
        nonlocal confirmed
        if name.get().strip() != expected_name:
            error.set("The sandbox name does not match.")
            entry.focus_set()
            return
        confirmed = True
        root.destroy()

    button_frame = ttk.Frame(frame)
    button_frame.grid(row=4, column=0, sticky="e", pady=(14, 0))
    ttk.Button(button_frame, text="Cancel", command=cancel).pack(side="left")
    ttk.Button(button_frame, text="Delete sandbox", command=confirm).pack(
        side="left", padx=(8, 0)
    )
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.bind("<Escape>", lambda _event: cancel())
    root.bind("<Return>", lambda _event: confirm())
    root.lift()
    root.focus_force()
    entry.focus_set()
    try:
        root.grab_set()
        root.attributes("-topmost", True)
        root.after(150, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        # Some desktop environments reject transient/topmost hints.  The
        # confirmation remains usable as an ordinary modal window in that case.
        pass
    root.mainloop()
    return confirmed


def _show_tkinter_confirmation_subprocess(
    title: str,
    message: str,
    expected_name: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> bool:
    """Run a destructive-action confirmation outside the tray process."""
    payload = json.dumps(
        {
            "title": title,
            "message": message,
            "expected_name": expected_name,
            "screen_bounds": screen_bounds,
        },
        ensure_ascii=False,
    )
    child = (
        "import json, sys; "
        "from ai_guardian.tray.sandbox_dialog import _show_tkinter_confirmation; "
        "p=json.loads(sys.argv[1]); "
        "v=_show_tkinter_confirmation(p['title'], p['message'], p['expected_name'], "
        "screen_bounds=p.get('screen_bounds')); "
        "print('1' if v else '0')"
    )
    try:
        process = subprocess.run(
            [sys.executable, "-c", child, payload],
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Sandbox confirmation could not be shown: %s", exc)
        return False
    if process.returncode != 0:
        detail = (process.stderr or "").strip()
        logger.warning(
            "Sandbox confirmation exited with code %s%s",
            process.returncode,
            f": {detail[:200]}" if detail else "",
        )
        return False
    return (process.stdout or "").strip().splitlines()[-1:] == ["1"]


def _copy_sandbox_log(log_text: str, clipboard_owner=None) -> str:
    """Copy sandbox output and return a short status message for the dialog."""
    text = log_text or ""

    # The log dialog runs in a child Tk process.  Prefer its clipboard owner so
    # the copy works even when xclip/xsel/wl-copy are not installed.  OSC 52
    # cannot be used from this process because its stdout is captured by the
    # tray while the dialog is running.
    if clipboard_owner is not None:
        try:
            clipboard_owner.clipboard_clear()
            clipboard_owner.clipboard_append(text)
            clipboard_owner.update()
            return "Copied to clipboard (Tkinter)."
        except Exception as exc:
            logger.debug("Tkinter clipboard copy failed: %s", exc)

    try:
        from ai_guardian.tui.app import copy_to_system_clipboard

        error, method = copy_to_system_clipboard(text)
        if error is None:
            return f"Copied to clipboard ({method})."
        return f"Copy failed: {error}"
    except Exception as exc:
        logger.warning("Sandbox log could not be copied: %s", exc)
        return f"Copy failed: {exc}"


def _show_tkinter_log_subprocess(
    title: str,
    message: str,
    log_text: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> bool:
    """Run the log dialog outside the tray process."""
    payload = json.dumps(
        {
            "title": title,
            "message": message,
            "log": log_text,
            "screen_bounds": screen_bounds,
        },
        ensure_ascii=False,
    )
    child = (
        "import json, sys; "
        "from ai_guardian.tray.sandbox_dialog import _show_tkinter_log; "
        "p=json.loads(sys.argv[1]); "
        "_show_tkinter_log(p['title'], p['message'], p['log'], "
        "screen_bounds=p.get('screen_bounds'))"
    )
    try:
        process = subprocess.run(
            [sys.executable, "-c", child, payload],
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Sandbox log dialog could not be shown: %s", exc)
        return False
    if process.returncode != 0:
        detail = (process.stderr or "").strip()
        logger.warning(
            "Sandbox log dialog exited with code %s%s",
            process.returncode,
            f": {detail[:200]}" if detail else "",
        )
        return False
    return True


def show_sandbox_log(
    title: str,
    message: str,
    log_text: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> bool:
    """Show captured sandbox output in a modal log dialog."""
    try:
        from ai_guardian.tui.display import _tkinter_available

        if _tkinter_available():
            if screen_bounds is None:
                shown = _show_tkinter_log_subprocess(title, message, log_text)
            else:
                shown = _show_tkinter_log_subprocess(
                    title,
                    message,
                    log_text,
                    screen_bounds=screen_bounds,
                )
            if shown:
                return True
    except Exception as exc:
        logger.warning("Sandbox log dialog unavailable: %s", exc)

    # Keep a useful fallback for systems without Tk or when the child process
    # cannot initialize a display.  Native simple dialogs may truncate very
    # long output, so retain the beginning and end of the captured log.
    from ai_guardian.tray.plugins import show_dialog

    text = str(log_text or "(no output)")
    if len(text) > 6000:
        text = text[:3000] + "\n... output truncated ...\n" + text[-3000:]
    if screen_bounds is None:
        return bool(show_dialog(title, f"{message}\n\n{text}"))
    return bool(
        show_dialog(
            title,
            f"{message}\n\n{text}",
            screen_bounds=screen_bounds,
        )
    )


def show_sandbox_confirmation(
    name: str,
    runtime: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> bool:
    """Confirm permanent deletion without exposing tray GUI toolkit state."""
    try:
        from ai_guardian.tui.display import _tkinter_available

        if not _tkinter_available():
            logger.warning("Sandbox confirmation unavailable: tkinter is not installed")
            return False
        message = (
            f"Permanently delete sandbox '{name}' ({runtime})?\n\n"
            "The runtime sandbox will be removed. Saved host configuration "
            "snapshots are kept."
        )
        if screen_bounds is None:
            return _show_tkinter_confirmation_subprocess(
                "Delete AI Guardian sandbox", message, name
            )
        return _show_tkinter_confirmation_subprocess(
            "Delete AI Guardian sandbox",
            message,
            name,
            screen_bounds=screen_bounds,
        )
    except Exception as exc:
        logger.warning("Sandbox confirmation unavailable: %s", exc)
        return False


def show_sandbox_form(
    title: str,
    message: str,
    fields: Iterable[Dict[str, Any]],
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> Optional[Dict[str, Any]]:
    """Show a native sandbox form from a tray worker thread."""
    try:
        from ai_guardian.tui.display import _tkinter_available

        if not _tkinter_available():
            logger.warning("Sandbox form unavailable: tkinter is not installed")
            return None
        # pystray owns the process' native event loop.  Creating and destroying
        # Tk widgets in the tray callback thread can terminate the tray on
        # some Linux/GTK combinations, so keep the form in a short-lived child
        # process on every platform.
        if screen_bounds is None:
            return _show_tkinter_form_subprocess(title, message, fields)
        return _show_tkinter_form_subprocess(
            title,
            message,
            fields,
            screen_bounds=screen_bounds,
        )
    except Exception as exc:
        logger.warning("Sandbox form unavailable: %s", exc)
        return None


__all__ = ["show_sandbox_confirmation", "show_sandbox_form", "show_sandbox_log"]
