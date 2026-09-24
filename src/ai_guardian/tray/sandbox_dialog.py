"""Small native forms used by tray-managed sandbox actions."""

from __future__ import annotations

import json
import logging
import os
import platform
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

ScreenBounds = Tuple[int, int, int, int]
_PROGRESS_READY = "__AI_GUARDIAN_SANDBOX_PROGRESS_READY__"
_PROGRESS_READY_TIMEOUT = 5.0


class SandboxProgress:
    """Send live sandbox output to an isolated Tk progress process."""

    def __init__(self, process):
        self._process = process
        self._lock = threading.Lock()
        self._closed = False
        self._failed = False
        self._ready = threading.Event()
        self._ready_success = False
        stream = getattr(process, "stdout", None)
        if stream is None:
            self._ready_success = True
            self._ready.set()
        else:
            threading.Thread(
                target=self._read_ready_signal,
                args=(stream,),
                daemon=True,
                name="sandbox-progress-ready",
            ).start()

    def _read_ready_signal(self, stream) -> None:
        """Wait for the child Tk process to finish initializing its window."""
        try:
            for line in stream:
                if str(line).strip() == _PROGRESS_READY:
                    self._ready_success = True
                    break
        except (OSError, ValueError, TypeError):
            logger.debug("Unable to read sandbox progress readiness", exc_info=True)
        finally:
            self._ready.set()

    def wait_ready(self, timeout: float = _PROGRESS_READY_TIMEOUT) -> bool:
        """Wait for the isolated progress window to become usable."""
        return self._ready.wait(timeout) and self._ready_success

    def _send(self, payload: Dict[str, Any]) -> bool:
        with self._lock:
            if self._closed or self._failed:
                return False
            stream = getattr(self._process, "stdin", None)
            if stream is None:
                self._failed = True
                return False
            try:
                stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
                stream.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                self._failed = True
                logger.warning("Sandbox progress dialog stopped: %s", exc)
                return False
        return True

    def append(self, text) -> None:
        """Forward one captured output chunk without interrupting the command."""
        if text:
            self._send({"type": "output", "text": str(text)})

    def update_status(self, message: str) -> None:
        """Update the visible state without adding a runtime log line."""
        if message:
            self._send({"type": "status", "message": str(message)})

    def _send_terminal(self, payload: Dict[str, Any]) -> bool:
        """Send a terminal dialog update and release the child stdin."""
        with self._lock:
            if self._closed or self._failed:
                return False
            stream = getattr(self._process, "stdin", None)
            if stream is None:
                self._failed = True
                return False
            try:
                stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
                stream.flush()
                stream.close()
            except (BrokenPipeError, OSError, ValueError) as exc:
                self._failed = True
                logger.warning("Sandbox progress dialog could not finish: %s", exc)
                return False
            self._closed = True

        threading.Thread(
            target=self._wait_for_process,
            daemon=True,
            name="sandbox-progress-reaper",
        ).start()
        return True

    def close(self) -> bool:
        """Close the dialog without presenting a completed operation."""
        return self._send_terminal({"type": "close"})

    def finish(self, success: bool, message: str, log_text: str) -> bool:
        """Tell the dialog whether to close or remain open for inspection."""
        return self._send_terminal(
            {
                "type": "complete",
                "success": bool(success),
                "message": str(message),
                "log": str(log_text or ""),
            }
        )

    def _wait_for_process(self) -> None:
        try:
            self._process.wait()
        except (OSError, ValueError):
            logger.debug(
                "Sandbox progress dialog process cleanup failed", exc_info=True
            )


class _FallbackSandboxProgress:
    """Keep sandbox output flowing when no live desktop provider is usable."""

    def __init__(self, title: str, message: str, provider: str):
        self._title = title
        self._provider = provider
        self._closed = False
        self._status = message

    def append(self, _text) -> None:
        """Accept output without duplicating potentially sensitive log text."""

    def update_status(self, message: str) -> None:
        if message and not self._closed:
            self._status = str(message)
            logger.debug("Sandbox progress (%s): %s", self._provider, self._status)

    def close(self) -> bool:
        self._closed = True
        return True

    def finish(self, success: bool, message: str, _log_text: str) -> bool:
        self._closed = True
        logger.debug(
            "Sandbox progress finished (%s, success=%s): %s",
            self._provider,
            success,
            message,
        )
        # Returning False makes failure paths show the captured log through the
        # normal log-dialog fallback instead of silently discarding it.
        return False


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
        event = _current_event(AppKit)
        if event is None:
            return None
        window = event.window()
        if window is None:
            return None
        return window.screen()
    except Exception:
        return None


def _current_event(AppKit):
    """Return AppKit's current event without requiring NSEvent helpers."""
    try:
        return AppKit.NSApplication.sharedApplication().currentEvent()
    except Exception:
        return None


def _mouse_event_types(AppKit):
    """Return AppKit constants representing mouse activation events."""
    names = (
        "NSLeftMouseDown",
        "NSLeftMouseUp",
        "NSRightMouseDown",
        "NSRightMouseUp",
        "NSOtherMouseDown",
        "NSOtherMouseUp",
        "NSEventTypeLeftMouseDown",
        "NSEventTypeLeftMouseUp",
        "NSEventTypeRightMouseDown",
        "NSEventTypeRightMouseUp",
        "NSEventTypeOtherMouseDown",
        "NSEventTypeOtherMouseUp",
    )
    return {
        value
        for name in names
        for value in (getattr(AppKit, name, None),)
        if isinstance(value, (int, float))
    }


def _event_is_mouse_activation(event, AppKit) -> bool:
    """Return whether an event represents a pointer-driven menu activation."""
    if event is None:
        return False
    try:
        return event.type() in _mouse_event_types(AppKit)
    except Exception:
        return False


def _screen_containing_point(point, screens):
    """Return the screen containing an AppKit global point, if any."""
    for screen in screens:
        try:
            if _point_in_rect(point, screen.frame()):
                return screen
        except (AttributeError, TypeError, ValueError):
            continue
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
        event = _current_event(AppKit)
        screen = _event_screen(AppKit)
        pointer = AppKit.NSEvent.mouseLocation()
        pointer_screen = _screen_containing_point(pointer, screens)
        # A nested NSMenu action can retain a window from the previous menu
        # event. For an actual pointer activation, the global mouse location
        # identifies the display where the user selected the item and is more
        # reliable than that stale window.
        if _event_is_mouse_activation(event, AppKit) and pointer_screen is not None:
            screen = pointer_screen
        if screen is None:
            screen = _status_item_screen(icon)
        if screen is None:
            screen = pointer_screen
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
    controls: Dict[str, Tuple[str, tk.Variable]] = {}
    control_widgets: Dict[str, list[ttk.Widget]] = {}
    field_labels: Dict[str, list[ttk.Label]] = {}
    enabled_states: Dict[str, bool] = {}
    dynamic_defaults: Dict[str, str] = {}
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
    variable: tk.Variable
    control: ttk.Widget
    widgets: list[ttk.Widget]
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

            def browse_image(variable: tk.Variable = variable) -> None:
                _show_local_image_picker(root, variable, screen_bounds)

            browse_button = ttk.Button(
                control_frame,
                text="Browse...",
                command=browse_image,
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
        """Refresh dependent choices and enable or disable dependent fields."""
        for field in field_list:
            name = str(field.get("name", ""))
            choices_spec = field.get("choices_by")
            if isinstance(choices_spec, dict):
                dependency = controls.get(str(choices_spec.get("field", "")))
                choices_by_value = choices_spec.get("values")
                if dependency and isinstance(choices_by_value, dict):
                    choices = choices_by_value.get(str(dependency[1].get()), ())
                    if isinstance(choices, (list, tuple, set)):
                        normalized_choices = [str(choice) for choice in choices]
                        for widget in control_widgets.get(name, ()):
                            widget.configure({"values": normalized_choices})
                        if (
                            field.get("clear_when_choice_invalid")
                            and str(controls[name][1].get()) not in normalized_choices
                        ):
                            controls[name][1].set(
                                normalized_choices[0] if normalized_choices else ""
                            )
            editable_spec = field.get("editable_by")
            if isinstance(editable_spec, dict):
                dependency = controls.get(str(editable_spec.get("field", "")))
                editable_by_value = editable_spec.get("values")
                if dependency and isinstance(editable_by_value, dict):
                    editable = bool(
                        editable_by_value.get(str(dependency[1].get()), False)
                    )
                    for widget in control_widgets.get(name, ()):
                        widget.configure(
                            {"state": "normal" if editable else "readonly"}
                        )
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
            if not enabled and field.get("clear_when_disabled"):
                controls[name][1].set("")
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
            updated = _dynamic_default_value(specification, str(dependency[1].get()))
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


def _set_text_wrap(text, enabled: bool) -> None:
    """Switch a Tk text widget between wrapped and horizontally scrollable text."""
    text.configure(wrap="word" if enabled else "none")


def _show_tkinter_progress(
    title: str,
    message: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> None:
    """Show live sandbox output and keep failed operations available."""
    import tkinter as tk
    from tkinter import ttk

    from ai_guardian.tui.display import _ensure_tcl_library

    _ensure_tcl_library()
    updates: queue.Queue[Dict[str, Any]] = queue.Queue()
    log_parts: list[str] = []
    completed = False
    root = tk.Tk()
    root.title(title)
    root.geometry("760x480")
    _place_window_on_screen(root, screen_bounds, 760, 480)
    root.minsize(520, 280)

    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)
    frame.rowconfigure(2, weight=1)
    frame.columnconfigure(0, weight=1)

    ttk.Label(frame, text=message, justify="left", wraplength=700).grid(
        row=0, column=0, sticky="w", pady=(0, 4)
    )
    status = tk.StringVar(value="Running...")
    ttk.Label(frame, textvariable=status, justify="left").grid(
        row=1, column=0, sticky="w", pady=(0, 10)
    )

    log_frame = ttk.Frame(frame)
    log_frame.grid(row=2, column=0, sticky="nsew")
    log_frame.rowconfigure(0, weight=1)
    log_frame.columnconfigure(0, weight=1)
    text = tk.Text(log_frame, wrap="none", state="disabled")
    text.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=text.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    horizontal_scrollbar = ttk.Scrollbar(
        log_frame,
        orient="horizontal",
        command=text.xview,
    )
    horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
    text.configure(
        xscrollcommand=horizontal_scrollbar.set,
        yscrollcommand=scrollbar.set,
    )

    wrap_lines = tk.BooleanVar(master=root, value=False)

    def toggle_wrap() -> None:
        _set_text_wrap(text, wrap_lines.get())

    ttk.Checkbutton(
        frame,
        text="Wrap lines",
        variable=wrap_lines,
        command=toggle_wrap,
    ).grid(row=3, column=0, sticky="w", pady=(8, 0))

    def replace_log(value: str) -> None:
        text.configure(state="normal")
        text.delete("1.0", "end")
        if value:
            text.insert("1.0", value)
        text.configure(state="disabled")
        text.see("end")

    def append_log(value: str) -> None:
        log_parts.append(value)
        text.configure(state="normal")
        text.insert("end", value)
        text.configure(state="disabled")
        text.see("end")

    copy_status = tk.StringVar()

    def copy() -> None:
        copy_status.set(_copy_sandbox_log("".join(log_parts), clipboard_owner=root))

    ttk.Label(frame, textvariable=copy_status, justify="left").grid(
        row=4, column=0, sticky="w", pady=(8, 0)
    )

    def close() -> None:
        root.destroy()

    button_frame = ttk.Frame(frame)
    button_frame.grid(row=5, column=0, sticky="e", pady=(12, 0))
    ttk.Button(button_frame, text="Copy", command=copy).pack(side="left")
    ttk.Button(button_frame, text="Close", command=close).pack(side="left", padx=(8, 0))
    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<Escape>", lambda _event: close())

    def read_updates() -> None:
        try:
            for line in sys.stdin:
                try:
                    updates.put(json.loads(line))
                except json.JSONDecodeError:
                    logger.debug("Ignoring malformed sandbox progress update")
        finally:
            updates.put({"type": "eof"})

    def poll_updates() -> None:
        nonlocal completed
        try:
            while True:
                update = updates.get_nowait()
                update_type = update.get("type")
                if update_type == "output":
                    append_log(str(update.get("text") or ""))
                elif update_type == "status":
                    status.set(str(update.get("message") or "Running..."))
                elif update_type == "close":
                    completed = True
                    root.after(0, close)
                elif update_type == "complete":
                    completed = True
                    final_log = update.get("log")
                    if isinstance(final_log, str) and final_log != "".join(log_parts):
                        log_parts[:] = [final_log]
                        replace_log(final_log)
                    message = str(update.get("message") or "")
                    if update.get("success"):
                        status.set(message or "Completed.")
                        root.after(150, close)
                    else:
                        status.set(message or "Operation failed. Review output.")
                elif update_type == "eof" and not completed:
                    status.set("Operation ended before completion.")
        except queue.Empty:
            pass

        try:
            if root.winfo_exists():
                root.after(50, poll_updates)
        except tk.TclError:
            pass

    threading.Thread(
        target=read_updates,
        daemon=True,
        name="sandbox-progress-reader",
    ).start()
    root.after(50, poll_updates)
    root.lift()
    root.focus_force()
    try:
        root.grab_set()
        root.attributes("-topmost", True)
        root.after(150, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        # Some desktop environments reject modal/topmost hints. The progress
        # window remains usable as an ordinary window in that case.
        pass
    root.update_idletasks()
    print(_PROGRESS_READY, flush=True)
    root.mainloop()


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
    horizontal_scrollbar = ttk.Scrollbar(
        log_frame,
        orient="horizontal",
        command=text.xview,
    )
    horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
    text.configure(
        xscrollcommand=horizontal_scrollbar.set,
        yscrollcommand=scrollbar.set,
    )
    text.insert("1.0", log_text or "(no output)")
    text.configure(state="disabled")
    copy_status = tk.StringVar()

    def copy() -> None:
        copy_status.set(_copy_sandbox_log(log_text, clipboard_owner=root))

    wrap_lines = tk.BooleanVar(master=root, value=False)

    def toggle_wrap() -> None:
        _set_text_wrap(text, wrap_lines.get())

    ttk.Checkbutton(
        frame,
        text="Wrap lines",
        variable=wrap_lines,
        command=toggle_wrap,
    ).grid(row=2, column=0, sticky="w", pady=(8, 0))
    ttk.Label(frame, textvariable=copy_status, justify="left").grid(
        row=3, column=0, sticky="w", pady=(8, 0)
    )

    def close() -> None:
        root.destroy()

    button_frame = ttk.Frame(frame)
    button_frame.grid(row=4, column=0, sticky="e", pady=(12, 0))
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


def _show_tkinter_progress_subprocess(
    title: str,
    message: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> Optional[SandboxProgress]:
    """Start the live progress window outside the tray process."""
    payload = json.dumps(
        {"title": title, "message": message, "screen_bounds": screen_bounds},
        ensure_ascii=False,
    )
    child = (
        "import json; "
        "from ai_guardian.tray.sandbox_dialog import _show_tkinter_progress; "
        "p=json.loads(__import__('sys').argv[1]); "
        "_show_tkinter_progress(p['title'], p['message'], "
        "screen_bounds=p.get('screen_bounds'))"
    )
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", child, payload],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        logger.warning("Sandbox progress dialog could not be shown: %s", exc)
        return None
    progress = SandboxProgress(process)
    if not progress.wait_ready():
        progress.close()
        terminate = getattr(process, "terminate", None)
        if callable(terminate):
            terminate()
        return None
    return progress


def _field_enabled(field: Dict[str, Any], values: Dict[str, Any]) -> bool:
    """Return whether a sandbox form field is active for current values."""
    condition = field.get("enabled_when")
    if not isinstance(condition, dict):
        return True
    actual = values.get(str(condition.get("field", "")))
    expected = condition.get("values", condition.get("equals"))
    if isinstance(expected, (list, tuple, set)):
        return actual in expected
    return expected is None or actual == expected


def _field_choices(field: Dict[str, Any], values: Dict[str, Any]):
    """Return the currently applicable choices for a form field."""
    choices = field.get("choices", ())
    choices_spec = field.get("choices_by")
    if isinstance(choices_spec, dict):
        selected = values.get(str(choices_spec.get("field", "")))
        choices_by_value = choices_spec.get("values")
        if isinstance(choices_by_value, dict):
            choices = choices_by_value.get(selected, choices)
    if not isinstance(choices, (list, tuple, set)):
        return ()
    return tuple(str(choice) for choice in choices)


def _form_label(field: Dict[str, Any]) -> str:
    """Build a consistent label for the non-Tk sandbox form providers."""
    label = str(field.get("label", field.get("name", "")))
    return f"{label} *" if field.get("required") else label


def _find_free_port() -> int:
    """Return an available loopback port for a temporary browser dialog."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _textual_available_for_current_process() -> bool:
    """Return whether this process can run Textual without opening a terminal."""
    from ai_guardian.tui.display import _textual_available

    return _textual_available()


def _show_nicegui_form(
    title: str,
    message: str,
    fields: Iterable[Dict[str, Any]],
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> Optional[Dict[str, Any]]:
    """Show the sandbox form in a browser using NiceGUI."""
    del screen_bounds
    from nicegui import app, ui

    field_list = tuple(fields)
    result_holder: Dict[str, Any] = {"value": None}
    widgets: Dict[str, Tuple[str, Any]] = {}
    enabled_states: Dict[str, bool] = {}

    def collect_values() -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        for field in field_list:
            name = str(field.get("name", ""))
            kind, widget = widgets[name]
            value = widget.value
            if kind == "bool":
                values[name] = bool(value)
            elif value is None:
                values[name] = ""
            else:
                values[name] = str(value).strip()
        return values

    def close() -> None:
        ui.run_javascript("window.close()")
        ui.timer(0.1, app.shutdown, once=True)

    def submit() -> None:
        values = collect_values()
        missing = [
            str(field.get("label", field.get("name", "")))
            for field in field_list
            if field.get("required")
            and _field_enabled(field, values)
            and not values.get(str(field.get("name", "")))
        ]
        if missing:
            ui.notify("Required: " + ", ".join(missing), type="negative")
            return
        result_holder["value"] = values
        close()

    @ui.page("/")
    def _form_page() -> None:
        ui.query("body").style("background: #1a1a2e")
        with (
            ui.card()
            .classes("mx-auto mt-8")
            .style("min-width: 460px; max-width: 760px")
        ):
            ui.label(title).classes("text-xl font-bold")
            ui.label(message).classes("whitespace-pre-wrap")
            ui.separator()
            for field in field_list:
                name = str(field.get("name", ""))
                kind = field.get("type", "text")
                default = field.get("default", "")
                label = _form_label(field)
                current_values = {
                    other_name: str(other.get("default", ""))
                    for other in field_list
                    if (other_name := str(other.get("name", "")))
                }
                if kind == "bool":
                    widget = ui.checkbox(label, value=bool(default))
                    widgets[name] = ("bool", widget)
                elif kind == "choice":
                    choices = list(_field_choices(field, current_values))
                    if field.get("editable"):
                        widget = ui.select(
                            options=choices,
                            value=str(default) if default else None,
                            label=label,
                            with_input=True,
                            new_value_mode="add-unique",
                        ).classes("w-full")
                    else:
                        widget = ui.select(
                            options=choices,
                            value=str(default) if default in choices else None,
                            label=label,
                        ).classes("w-full")
                    widgets[name] = ("choice", widget)
                else:
                    widget = ui.input(
                        label=label,
                        value="" if default is None else str(default),
                    ).classes("w-full")
                    widgets[name] = ("text", widget)
                help_text = field.get("help")
                if help_text:
                    ui.label(str(help_text)).classes("text-xs text-grey-6")

            def refresh() -> None:
                values = collect_values()
                for field in field_list:
                    name = str(field.get("name", ""))
                    enabled = _field_enabled(field, values)
                    enabled_states[name] = enabled
                    widget = widgets[name][1]
                    if enabled:
                        widget.enable()
                    else:
                        if field.get("clear_when_disabled"):
                            widget.set_value(
                                False if widgets[name][0] == "bool" else ""
                            )
                        widget.disable()

            for _kind, widget in widgets.values():
                widget.on_value_change(lambda _event: refresh())
            refresh()
            ui.separator()
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=close).props("flat")
                ui.button("Continue", on_click=submit, color="primary")

    port = _find_free_port()
    from ai_guardian.desktop_utils import open_url

    url = f"http://127.0.0.1:{port}"
    app.on_startup(lambda: open_url(url))
    ui.run(
        host="127.0.0.1",
        port=port,
        title=title,
        dark=True,
        show=False,
        reload=False,
    )
    return result_holder["value"]


def _show_textual_form(
    title: str,
    message: str,
    fields: Iterable[Dict[str, Any]],
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> Optional[Dict[str, Any]]:
    """Show the sandbox form in a terminal using Textual."""
    del screen_bounds
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal
    from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, Select

    field_list = tuple(fields)
    widget_ids = {
        str(field.get("name", "")): f"sandbox-field-{index}"
        for index, field in enumerate(field_list)
    }

    class _SandboxFormApp(App):
        CSS = """
        #form-container { padding: 1 2; }
        .field-row { margin: 1 0 0 0; }
        .field-row Input, .field-row Select { width: 100%; }
        #button-row { margin: 2 0 0 0; }
        #button-row Button { margin: 0 1 0 0; }
        """

        BINDINGS = [("escape", "cancel", "Cancel")]

        def compose(self_inner) -> ComposeResult:
            yield Header(show_clock=False)
            with Container(id="form-container"):
                yield Label(f"[bold]{title}[/bold]")
                yield Label(message)
                for field in field_list:
                    name = str(field.get("name", ""))
                    kind = field.get("type", "text")
                    default = field.get("default", "")
                    with Container(classes="field-row"):
                        yield Label(_form_label(field))
                        if kind == "bool":
                            yield Checkbox(
                                "",
                                value=bool(default),
                                id=widget_ids[name],
                            )
                        elif kind == "choice" and not field.get("editable"):
                            choices = _field_choices(
                                field,
                                {
                                    other_name: str(other.get("default", ""))
                                    for other in field_list
                                    if (other_name := str(other.get("name", "")))
                                },
                            )
                            value = (
                                str(default)
                                if str(default) in choices
                                else Select.BLANK
                            )
                            yield Select(
                                [(choice, choice) for choice in choices],
                                value=value,
                                id=widget_ids[name],
                            )
                        else:
                            yield Input(
                                value="" if default is None else str(default),
                                id=widget_ids[name],
                            )
                        if field.get("help"):
                            yield Label(f"[dim]{field['help']}[/dim]")
                with Horizontal(id="button-row"):
                    yield Button("Continue", id="continue-btn", variant="primary")
                    yield Button("Cancel", id="cancel-btn")
            yield Footer()

        def _collect(self_inner) -> Dict[str, Any]:
            values: Dict[str, Any] = {}
            for field in field_list:
                name = str(field.get("name", ""))
                widget = self_inner.query_one(f"#{widget_ids[name]}")
                if isinstance(widget, Checkbox):
                    values[name] = bool(widget.value)
                elif isinstance(widget, Select):
                    values[name] = (
                        "" if widget.value is Select.BLANK else str(widget.value)
                    )
                else:
                    values[name] = widget.value.strip()
            return values

        def on_button_pressed(self_inner, event) -> None:
            if event.button.id == "cancel-btn":
                self_inner.exit(result=None)
                return
            values = self_inner._collect()
            missing = [
                str(field.get("label", field.get("name", "")))
                for field in field_list
                if field.get("required")
                and _field_enabled(field, values)
                and not values.get(str(field.get("name", "")))
            ]
            if missing:
                self_inner.notify("Required: " + ", ".join(missing), severity="error")
                return
            self_inner.exit(result=values)

        def action_cancel(self_inner) -> None:
            self_inner.exit(result=None)

    return _SandboxFormApp().run()


def _show_textual_form_terminal(
    title: str,
    message: str,
    fields: Iterable[Dict[str, Any]],
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> Optional[Dict[str, Any]]:
    """Run the Textual form in a newly opened terminal and wait for its result."""
    from ai_guardian.daemon.multi_client import _launch_in_terminal
    from ai_guardian.tray.plugins import poll_output_file

    tmpdir = tempfile.mkdtemp(prefix="ai-guardian-sandbox-form-")
    output_path = str(Path(tmpdir) / "values.json")
    payload = json.dumps(
        {"title": title, "message": message, "fields": tuple(fields)},
        ensure_ascii=False,
    )
    child = (
        "import json,sys; "
        "from ai_guardian.tray.sandbox_dialog import _show_textual_form; "
        "p=json.loads(sys.argv[1]); "
        "v=_show_textual_form(p['title'],p['message'],p['fields']); "
        "open(sys.argv[2],'w',encoding='utf-8').write("
        "json.dumps(v,ensure_ascii=False) if v is not None else '')"
    )
    command = [sys.executable, "-c", child, payload, output_path]
    if not _launch_in_terminal(command, keep_open=False, clear=True):
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)
        return None
    output = poll_output_file(output_path, tmpdir)
    if not output:
        return None
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        logger.warning("Textual sandbox form returned invalid JSON")
        return None
    return value if isinstance(value, dict) else None


def _show_native_confirmation(
    title: str,
    message: str,
    confirm_label: str,
    *,
    expected_text: Optional[str] = None,
) -> Optional[bool]:
    """Show a native confirmation, returning ``None`` if no provider starts."""
    system = platform.system()
    try:
        if system == "Darwin":
            from ai_guardian.daemon.multi_client import _escape_for_applescript

            escaped_message = (
                _escape_for_applescript(message)
                .replace("\r", "")
                .replace("\n", '" & return & "')
            )
            escaped_title = _escape_for_applescript(title).replace("\n", " ")
            escaped_confirm = _escape_for_applescript(confirm_label)
            buttons = '{"Cancel", "' + escaped_confirm + '"}'
            answer = ' default answer ""' if expected_text is not None else ""
            script = (
                f'display dialog "{escaped_message}" with title "{escaped_title}"'
                f'{answer} buttons {buttons} default button "{escaped_confirm}"'
                f' cancel button "Cancel"'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return False
            output = (result.stdout or "").strip()
            if expected_text is None:
                return f"button returned: {confirm_label}" in output
            marker = "text returned:"
            returned = (
                output.split(marker, 1)[1].split(",", 1)[0].strip()
                if marker in output
                else ""
            )
            return returned == expected_text

        if system == "Linux":
            commands = []
            if expected_text is None:
                commands = [
                    [
                        "zenity",
                        "--question",
                        "--title",
                        title,
                        "--text",
                        message,
                        "--ok-label",
                        confirm_label,
                        "--cancel-label",
                        "Cancel",
                    ],
                    ["kdialog", "--title", title, "--yesno", message],
                ]
            else:
                prompt = f"{message}\n\nType {expected_text} to confirm:"
                commands = [
                    [
                        "zenity",
                        "--entry",
                        "--title",
                        title,
                        "--text",
                        prompt,
                        "--ok-label",
                        confirm_label,
                        "--cancel-label",
                        "Cancel",
                    ],
                    ["kdialog", "--title", title, "--inputbox", prompt, ""],
                ]
            for command in commands:
                try:
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                except (FileNotFoundError, OSError):
                    continue
                if result.returncode != 0:
                    return False
                if expected_text is None:
                    return True
                return (result.stdout or "").strip() == expected_text
            return None

        if system == "Windows":
            escaped_title = title.replace("'", "''")
            escaped_message = message.replace("'", "''")
            if expected_text is None:
                script = (
                    "Add-Type -AssemblyName PresentationFramework; "
                    f"$r=[System.Windows.MessageBox]::Show('{escaped_message}',"
                    f"'{escaped_title}','YesNo'); Write-Output $r"
                )
            else:
                script = (
                    "Add-Type -AssemblyName Microsoft.VisualBasic; "
                    f"$r=[Microsoft.VisualBasic.Interaction]::InputBox('{escaped_message}',"
                    f"'{escaped_title}',''); Write-Output $r"
                )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return None
            if expected_text is None:
                return (result.stdout or "").strip().casefold() == "yes"
            return (result.stdout or "").strip() == expected_text
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("Native sandbox confirmation unavailable: %s", exc)
        return None
    return None


def _show_nicegui_confirmation(
    title: str,
    message: str,
    confirm_label: str,
    *,
    expected_text: Optional[str] = None,
) -> bool:
    """Show an actionable confirmation in a browser using NiceGUI."""
    from nicegui import app, ui

    result_holder = {"value": False}
    expected_input: Dict[str, Any] = {"widget": None}

    def close() -> None:
        ui.run_javascript("window.close()")
        ui.timer(0.1, app.shutdown, once=True)

    def confirm() -> None:
        if expected_text is not None:
            value = expected_input["widget"].value
            if str(value or "").strip() != expected_text:
                ui.notify("The sandbox name does not match.", type="negative")
                return
        result_holder["value"] = True
        close()

    @ui.page("/")
    def _confirmation_page() -> None:
        with (
            ui.card()
            .classes("mx-auto mt-8")
            .style("min-width: 460px; max-width: 760px")
        ):
            ui.label(title).classes("text-xl font-bold")
            ui.label(message).classes("whitespace-pre-wrap")
            if expected_text is not None:
                expected_input["widget"] = ui.input(
                    label=f"Type {expected_text} to confirm"
                ).classes("w-full")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=close).props("flat")
                ui.button(confirm_label, on_click=confirm, color="primary")

    port = _find_free_port()
    from ai_guardian.desktop_utils import open_url

    url = f"http://127.0.0.1:{port}"
    app.on_startup(lambda: open_url(url))
    ui.run(
        host="127.0.0.1", port=port, title=title, dark=True, show=False, reload=False
    )
    return bool(result_holder["value"])


def _show_textual_confirmation(
    title: str,
    message: str,
    confirm_label: str,
    *,
    expected_text: Optional[str] = None,
) -> bool:
    """Show an actionable confirmation in a Textual terminal."""
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, Footer, Header, Input, Label

    class _ConfirmationApp(App):
        def compose(self_inner) -> ComposeResult:
            yield Header(show_clock=False)
            with Vertical(id="confirmation-body"):
                yield Label(f"[bold]{title}[/bold]")
                yield Label(message)
                if expected_text is not None:
                    yield Input(
                        placeholder=f"Type {expected_text} to confirm", id="name"
                    )
                with Horizontal(id="confirmation-buttons"):
                    yield Button(confirm_label, id="confirm-btn", variant="error")
                    yield Button("Cancel", id="cancel-btn")
            yield Footer()

        def on_button_pressed(self_inner, event) -> None:
            if event.button.id == "cancel-btn":
                self_inner.exit(result=False)
                return
            if expected_text is not None:
                value = self_inner.query_one("#name", Input).value.strip()
                if value != expected_text:
                    self_inner.notify(
                        "The sandbox name does not match.", severity="error"
                    )
                    return
            self_inner.exit(result=True)

    return bool(_ConfirmationApp().run())


def _show_textual_confirmation_terminal(
    title: str,
    message: str,
    confirm_label: str,
    *,
    expected_text: Optional[str] = None,
) -> bool:
    """Run a Textual confirmation in a terminal and wait for its result."""
    from ai_guardian.daemon.multi_client import _launch_in_terminal
    from ai_guardian.tray.plugins import poll_output_file

    tmpdir = tempfile.mkdtemp(prefix="ai-guardian-confirmation-")
    output_path = str(Path(tmpdir) / "result")
    payload = json.dumps(
        {
            "title": title,
            "message": message,
            "confirm_label": confirm_label,
            "expected_text": expected_text,
        },
        ensure_ascii=False,
    )
    child = (
        "import json,sys; "
        "from ai_guardian.tray.sandbox_dialog import _show_textual_confirmation; "
        "p=json.loads(sys.argv[1]); "
        "v=_show_textual_confirmation(p['title'],p['message'],p['confirm_label'],"
        "expected_text=p.get('expected_text')); "
        "open(sys.argv[2],'w').write('1' if v else '0')"
    )
    command = [sys.executable, "-c", child, payload, output_path]
    if not _launch_in_terminal(command, keep_open=False, clear=True):
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)
        return False
    return poll_output_file(output_path, tmpdir) == "1"


def show_sandbox_progress(
    title: str,
    message: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> Optional[Any]:
    """Start sandbox progress using the configured provider cascade."""
    try:
        from ai_guardian.tui.display import select_ui_provider

        provider = select_ui_provider("stream", screen_bounds=screen_bounds)
        if provider == "tkinter":
            if screen_bounds is None:
                progress = _show_tkinter_progress_subprocess(title, message)
            else:
                progress = _show_tkinter_progress_subprocess(
                    title,
                    message,
                    screen_bounds=screen_bounds,
                )
            if progress is not None:
                return progress
        if provider != "headless":
            logger.info(
                "Sandbox progress has no live %s implementation; using captured-output fallback",
                provider,
            )
            return _FallbackSandboxProgress(title, message, provider)
        return _FallbackSandboxProgress(title, message, provider)
    except Exception as exc:
        logger.warning("Sandbox progress dialog unavailable: %s", exc)
        return _FallbackSandboxProgress(title, message, "headless")


def show_sandbox_log(
    title: str,
    message: str,
    log_text: str,
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> bool:
    """Show captured sandbox output in a modal log dialog."""
    try:
        from ai_guardian.tui.display import select_ui_provider

        provider = select_ui_provider("stream", screen_bounds=screen_bounds)
        if provider == "tkinter":
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

    try:
        from ai_guardian.tui.display import select_ui_provider

        if select_ui_provider("stream", screen_bounds=screen_bounds) == "headless":
            logger.warning("Sandbox log unavailable: no interactive UI provider")
            return False
    except Exception:
        return False

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
        from ai_guardian.tui.display import select_ui_provider

        message = (
            f"Permanently delete sandbox '{name}' ({runtime})?\n\n"
            "The runtime sandbox will be removed. Saved host configuration "
            "snapshots are kept."
        )
        provider = select_ui_provider("action", screen_bounds=screen_bounds)
        if provider == "tkinter":
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
        if provider == "native":
            result = _show_native_confirmation(
                "Delete AI Guardian sandbox",
                message,
                "Delete sandbox",
                expected_text=name,
            )
            return bool(result) if result is not None else False
        if provider == "nicegui":
            return _show_nicegui_confirmation(
                "Delete AI Guardian sandbox",
                message,
                "Delete sandbox",
                expected_text=name,
            )
        if provider == "textual":
            if _textual_available_for_current_process():
                return _show_textual_confirmation(
                    "Delete AI Guardian sandbox",
                    message,
                    "Delete sandbox",
                    expected_text=name,
                )
            return _show_textual_confirmation_terminal(
                "Delete AI Guardian sandbox",
                message,
                "Delete sandbox",
                expected_text=name,
            )
        return False
    except Exception as exc:
        logger.warning("Sandbox confirmation unavailable: %s", exc)
        return False


def _show_tkinter_upload_confirmation(
    title: str,
    message: str,
    *,
    error_lines: Iterable[str] = (),
    screen_bounds: Optional[ScreenBounds] = None,
) -> bool:
    """Show an upload summary and require explicit confirmation."""
    import tkinter as tk
    from tkinter import ttk

    from ai_guardian.tui.display import _ensure_tcl_library

    _ensure_tcl_library()
    root = tk.Tk()
    root.title(title)
    root.geometry("720x360")
    _place_window_on_screen(root, screen_bounds, 720, 360)
    root.minsize(560, 280)
    root.resizable(True, True)
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)

    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    message_text = tk.Text(frame, wrap="word", height=14, state="normal")
    message_text.grid(row=0, column=0, sticky="nsew")
    message_scrollbar = ttk.Scrollbar(
        frame,
        orient="vertical",
        command=message_text.yview,
    )
    message_scrollbar.grid(row=0, column=1, sticky="ns")
    horizontal_scrollbar = ttk.Scrollbar(
        frame,
        orient="horizontal",
        command=message_text.xview,
    )
    horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
    message_text.configure(
        xscrollcommand=horizontal_scrollbar.set,
        yscrollcommand=message_scrollbar.set,
    )
    error_lines = set(error_lines)
    message_text.tag_configure("error", foreground="#b00020")
    for line in message.splitlines() or ("",):
        message_text.insert(
            "end",
            f"{line}\n",
            "error" if line in error_lines else (),
        )
    message_text.configure(state="disabled")

    confirmed = False

    def cancel() -> None:
        root.destroy()

    def continue_upload() -> None:
        nonlocal confirmed
        confirmed = True
        root.destroy()

    wrap_lines = tk.BooleanVar(master=root, value=True)

    def toggle_wrap() -> None:
        _set_text_wrap(message_text, wrap_lines.get())

    ttk.Checkbutton(
        frame,
        text="Wrap lines",
        variable=wrap_lines,
        command=toggle_wrap,
    ).grid(row=2, column=0, sticky="w", pady=(8, 0))

    button_frame = ttk.Frame(frame)
    button_frame.grid(row=3, column=0, sticky="e", pady=(18, 0))
    ttk.Button(button_frame, text="Cancel", command=cancel).pack(side="left")
    ttk.Button(
        button_frame,
        text="Continue upload",
        command=continue_upload,
    ).pack(side="left", padx=(8, 0))
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.bind("<Escape>", lambda _event: cancel())
    root.bind("<Return>", lambda _event: continue_upload())
    root.lift()
    root.focus_force()
    try:
        root.grab_set()
        root.attributes("-topmost", True)
        root.after(150, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        # Some desktop environments reject modal/topmost hints. The upload
        # confirmation remains usable as an ordinary window in that case.
        pass
    root.mainloop()
    return confirmed


def _show_tkinter_upload_confirmation_subprocess(
    title: str,
    message: str,
    *,
    error_lines: Iterable[str] = (),
    screen_bounds: Optional[ScreenBounds] = None,
) -> bool:
    """Run upload confirmation outside the tray process."""
    payload = json.dumps(
        {
            "title": title,
            "message": message,
            "error_lines": tuple(error_lines),
            "screen_bounds": screen_bounds,
        },
        ensure_ascii=False,
    )
    child = (
        "import json, sys; "
        "from ai_guardian.tray.sandbox_dialog import "
        "_show_tkinter_upload_confirmation; "
        "p=json.loads(sys.argv[1]); "
        "v=_show_tkinter_upload_confirmation(p['title'], p['message'], "
        "error_lines=p.get('error_lines', ()), "
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
        logger.warning("Sandbox upload confirmation could not be shown: %s", exc)
        return False
    if process.returncode != 0:
        logger.warning(
            "Sandbox upload confirmation exited with code %s",
            process.returncode,
        )
        return False
    return (process.stdout or "").strip().splitlines()[-1:] == ["1"]


def show_sandbox_upload_confirmation(
    message: str,
    *,
    error_lines: Iterable[str] = (),
    screen_bounds: Optional[ScreenBounds] = None,
) -> bool:
    """Confirm an OpenShell repository upload before transfer begins."""
    try:
        from ai_guardian.tui.display import select_ui_provider

        title = "Confirm OpenShell repository upload"
        provider = select_ui_provider("action", screen_bounds=screen_bounds)
        if provider == "tkinter":
            if screen_bounds is None:
                return _show_tkinter_upload_confirmation_subprocess(
                    title,
                    message,
                    error_lines=error_lines,
                )
            return _show_tkinter_upload_confirmation_subprocess(
                title,
                message,
                error_lines=error_lines,
                screen_bounds=screen_bounds,
            )
        if provider == "native":
            result = _show_native_confirmation(title, message, "Continue upload")
            return bool(result) if result is not None else False
        if provider == "nicegui":
            return _show_nicegui_confirmation(title, message, "Continue upload")
        if provider == "textual":
            if _textual_available_for_current_process():
                return _show_textual_confirmation(title, message, "Continue upload")
            return _show_textual_confirmation_terminal(
                title,
                message,
                "Continue upload",
            )
        return False
    except Exception as exc:
        logger.warning("Sandbox upload confirmation unavailable: %s", exc)
        return False


def show_sandbox_form(
    title: str,
    message: str,
    fields: Iterable[Dict[str, Any]],
    *,
    screen_bounds: Optional[ScreenBounds] = None,
) -> Optional[Dict[str, Any]]:
    """Show a sandbox form using the configured provider cascade."""
    try:
        from ai_guardian.tui.display import select_ui_provider

        field_list = list(fields)
        provider = select_ui_provider("form", screen_bounds=screen_bounds)
        if provider == "nicegui":
            return _show_nicegui_form(
                title,
                message,
                field_list,
                screen_bounds=screen_bounds,
            )
        if provider == "textual":
            if _textual_available_for_current_process():
                return _show_textual_form(
                    title,
                    message,
                    field_list,
                    screen_bounds=screen_bounds,
                )
            return _show_textual_form_terminal(
                title,
                message,
                field_list,
                screen_bounds=screen_bounds,
            )
        if provider == "headless":
            logger.warning("Sandbox form unavailable: preferred UI is headless")
            return None
        if provider != "tkinter":
            logger.warning(
                "Sandbox form unavailable: unsupported provider %s", provider
            )
            return None
        # pystray owns the process' native event loop.  Creating and destroying
        # Tk widgets in the tray callback thread can terminate the tray on
        # some Linux/GTK combinations, so keep the form in a short-lived child
        # process on every platform.
        if screen_bounds is None:
            return _show_tkinter_form_subprocess(title, message, field_list)
        return _show_tkinter_form_subprocess(
            title,
            message,
            field_list,
            screen_bounds=screen_bounds,
        )
    except Exception as exc:
        logger.warning("Sandbox form unavailable: %s", exc)
        return None


__all__ = [
    "show_sandbox_confirmation",
    "show_sandbox_form",
    "show_sandbox_log",
    "show_sandbox_progress",
    "show_sandbox_upload_confirmation",
]
