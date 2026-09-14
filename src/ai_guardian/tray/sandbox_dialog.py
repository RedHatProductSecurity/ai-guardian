"""Small native forms used by tray-managed sandbox actions."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)


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


def _show_tkinter_form(
    title: str, message: str, fields: Iterable[Dict[str, Any]]
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
    result: Dict[str, Any] = {}

    root = tk.Tk()
    root.title(title)
    root.geometry("760x680")
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

    frame.bind("<Configure>", update_scroll_region)
    canvas.bind("<Configure>", resize_form)
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
                state="readonly",
                width=int(field.get("width", 44)),
            )
            if choices and str(default) not in choices:
                variable.set(choices[0])
            control.grid(row=row, column=1, sticky="w", pady=4)
            widgets = [control]
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
                if kind == "directory":
                    selected = filedialog.askdirectory(**options)
                elif field.get("multiple"):
                    selected = filedialog.askopenfilenames(**options)
                else:
                    selected = filedialog.askopenfilename(**options)
                variable.set(_merge_browse_paths(variable.get(), selected))

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

    for field in field_list:
        condition = field.get("enabled_when")
        if not isinstance(condition, dict):
            continue
        dependency = controls.get(str(condition.get("field", "")))
        if dependency:
            dependency[1].trace_add("write", refresh_enabled_states)
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
            if field.get("required") and not value:
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
    title: str, message: str, fields: Iterable[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Run a Tk form outside the tray process to isolate GUI toolkit state."""
    payload = json.dumps(
        {"title": title, "message": message, "fields": tuple(fields)},
        ensure_ascii=False,
    )
    child = (
        "import json, sys; "
        "from ai_guardian.tray.sandbox_dialog import _show_tkinter_form; "
        "p=json.loads(sys.argv[1]); "
        "v=_show_tkinter_form(p['title'], p['message'], p['fields']); "
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


def _show_tkinter_log(title: str, message: str, log_text: str) -> None:
    """Show captured sandbox output in a scrollable Tk window."""
    import tkinter as tk
    from tkinter import ttk

    from ai_guardian.tui.display import _ensure_tcl_library

    _ensure_tcl_library()
    root = tk.Tk()
    root.title(title)
    root.geometry("760x480")
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


def _show_tkinter_log_subprocess(title: str, message: str, log_text: str) -> bool:
    """Run the log dialog outside the tray process."""
    payload = json.dumps(
        {"title": title, "message": message, "log": log_text},
        ensure_ascii=False,
    )
    child = (
        "import json, sys; "
        "from ai_guardian.tray.sandbox_dialog import _show_tkinter_log; "
        "p=json.loads(sys.argv[1]); "
        "_show_tkinter_log(p['title'], p['message'], p['log'])"
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


def show_sandbox_log(title: str, message: str, log_text: str) -> bool:
    """Show captured sandbox output in a modal log dialog."""
    try:
        from ai_guardian.tui.display import _tkinter_available

        if _tkinter_available() and _show_tkinter_log_subprocess(
            title, message, log_text
        ):
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
    return bool(show_dialog(title, f"{message}\n\n{text}"))


def show_sandbox_form(
    title: str, message: str, fields: Iterable[Dict[str, Any]]
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
        return _show_tkinter_form_subprocess(title, message, fields)
    except Exception as exc:
        logger.warning("Sandbox form unavailable: %s", exc)
        return None


__all__ = ["show_sandbox_form", "show_sandbox_log"]
