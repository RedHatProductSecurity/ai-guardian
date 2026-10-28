"""
Popup for collecting tray plugin parameters.

Launched by the tray via `ai-guardian prompt --mode params --params '<json>' --template '<template>'`.

Cascade: tkinter (native popup) → NiceGUI (browser form).

To enable the tkinter popup, install the optional tkinter package:
  - macOS (pyenv): brew install tcl-tk && pyenv install <version> --force
  - UBI / RHEL:    dnf install -y python3-tkinter
  - Debian/Ubuntu: apt install -y python3-tk
  - Windows:       included by default in the python.org installer

tkinter is part of the Python standard library but requires the Tcl/Tk
system library at compile time. When unavailable, NiceGUI is used.
"""

import logging
import os
from typing import Any, Dict, Optional

from ai_guardian.ui.display import get_preferred_ui
from ai_guardian.ui.modal import create_tk_root, run_modal
from ai_guardian.ui.monitor import (
    screen_payload,
    placement_notice,
    tk_scrollable_content,
)
from ai_guardian.tray.dialog_placement import _place_window_on_screen

logger = logging.getLogger(__name__)


# -- tkinter implementation --------------------------------------------------


class _TkinterPromptApp:
    """Native tkinter parameter form (no terminal window)."""

    def __init__(
        self,
        params,
        command_template,
        command_type="terminal",
        extra_vars=None,
        title=None,
        screen_bounds=None,
    ):
        self._params = params
        self._command_template = command_template
        self._command_type = command_type
        self._extra_vars = extra_vars or {}
        self._title = title or "Plugin Parameters"
        self._screen_bounds = screen_bounds
        self._result = None
        self._widgets = {}

    def run(self):
        import platform
        import sys
        import tkinter as tk
        from tkinter import ttk, messagebox

        if not os.environ.get("TCL_LIBRARY"):
            import pathlib

            real_exe = pathlib.Path(sys.executable).resolve()
            tcl_lib = real_exe.parent.parent / "lib" / "tcl8.6"
            if (tcl_lib / "init.tcl").exists():
                os.environ["TCL_LIBRARY"] = str(tcl_lib)

        self._tk = tk
        self._ttk = ttk
        self._messagebox = messagebox

        self._root = create_tk_root()
        self._root.withdraw()  # No first map on the default screen during layout.

        if platform.system() == "Darwin":
            try:
                from AppKit import NSApplication

                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            except Exception:
                pass  # intentionally silent — optional dependency
        self._root.title(self._title)
        self._root.resizable(
            self._screen_bounds is not None, self._screen_bounds is not None
        )
        self._root.protocol("WM_DELETE_WINDOW", self._cancel)
        self._root.bind("<Escape>", lambda e: self._cancel())

        if self._screen_bounds is None:
            frame = ttk.Frame(self._root, padding=16)
            frame.grid(row=0, column=0, sticky="nsew")
        else:
            # A long parameter list must not lose controls when the target work
            # area is smaller than the form. Keep actions outside the viewport.
            frame, btn_frame = tk_scrollable_content(self._root)

        for i, param in enumerate(self._params):
            label_text = param["name"]
            if param.get("required", True):
                label_text = "* " + label_text
            hint = param.get("hint", "")
            if hint:
                label_text += f"  ({hint})"

            ttk.Label(frame, text=label_text).grid(
                row=i,
                column=0,
                sticky="w",
                pady=(8, 2),
            )

            ptype = param.get("type", "string")
            default = self._resolve_default(param.get("default", ""))
            var: Any = None
            widget: Any = None

            if ptype == "boolean":
                var = tk.BooleanVar(value=str(default).lower() == "true")
                widget = ttk.Checkbutton(frame, variable=var)
                widget.grid(row=i, column=1, sticky="w", pady=(8, 2))
                self._widgets[param["name"]] = ("boolean", var)

            elif ptype == "choice" or (ptype == "string" and param.get("options")):
                options = param.get("options", [])
                if not default and options:
                    default = options[0]
                var = tk.StringVar(value=default)
                widget = ttk.OptionMenu(frame, var, default, *options)
                widget.grid(row=i, column=1, sticky="ew", pady=(8, 2))
                self._widgets[param["name"]] = ("choice", var)

            elif ptype == "combobox" and param.get("options"):
                var = tk.StringVar(value=default)
                widget = ttk.Combobox(
                    frame,
                    textvariable=var,
                    values=param["options"],
                )
                widget.grid(row=i, column=1, sticky="ew", pady=(8, 2))
                self._widgets[param["name"]] = ("combobox", var)

            elif ptype in ("int", "number"):
                var = tk.StringVar(value=str(default) if default else "")
                p_min = param.get("min")
                p_max = param.get("max")
                kwargs: Dict[str, Any] = {}
                if p_min is not None:
                    kwargs["from_"] = float(p_min)
                if p_max is not None:
                    kwargs["to"] = float(p_max)
                if kwargs:
                    widget = ttk.Spinbox(
                        frame,
                        textvariable=var,
                        width=20,
                        **kwargs,
                    )
                else:
                    widget = ttk.Entry(frame, textvariable=var, width=30)
                widget.grid(row=i, column=1, sticky="ew", pady=(8, 2))
                self._widgets[param["name"]] = ("entry", var)

            elif ptype in ("path-file", "path-dir"):
                var = tk.StringVar(value=default)
                path_frame = ttk.Frame(frame)
                path_frame.grid(row=i, column=1, sticky="ew", pady=(8, 2))
                entry = ttk.Entry(path_frame, textvariable=var, width=25)
                entry.pack(side="left", fill="x", expand=True)
                browse_btn = ttk.Button(
                    path_frame,
                    text="Browse…",
                    command=self._make_browse_callback(var, ptype),
                )
                browse_btn.pack(side="left", padx=(4, 0))
                self._widgets[param["name"]] = ("entry", var)

            else:
                var = tk.StringVar(value=default)
                widget = ttk.Entry(frame, textvariable=var, width=30)
                widget.grid(row=i, column=1, sticky="ew", pady=(8, 2))
                self._widgets[param["name"]] = ("entry", var)

        frame.columnconfigure(1, weight=1)

        if self._screen_bounds is None:
            btn_frame = ttk.Frame(frame)
            btn_frame.grid(
                row=len(self._params), column=0, columnspan=2, pady=(16, 0), sticky="e"
            )
        ttk.Button(btn_frame, text="Cancel", command=self._cancel).pack(
            side="left",
            padx=(0, 8),
        )
        ttk.Button(btn_frame, text="OK", command=self._submit).pack(
            side="left",
        )

        self._root.bind("<Return>", lambda e: self._submit())

        self._root.update_idletasks()
        self._root.minsize(360, self._root.winfo_reqheight())
        _place_window_on_screen(
            self._root,
            self._screen_bounds,
            (
                self._root.winfo_reqwidth()
                if self._screen_bounds is None
                else frame.winfo_reqwidth() + 24
            ),
            (
                self._root.winfo_reqheight()
                if self._screen_bounds is None
                else frame.winfo_reqheight() + btn_frame.winfo_reqheight() + 24
            ),
        )

        self._root.deiconify()
        self._root.lift()
        self._root.attributes("-topmost", True)
        self._root.after(100, lambda: self._root.attributes("-topmost", False))
        self._root.focus_force()

        self._root.mainloop()
        return self._result

    def _cancel(self):
        self._result = None
        self._root.destroy()

    def _resolve_default(self, value):
        if not value or not self._extra_vars or "{" not in str(value):
            return value
        from ai_guardian.tray.plugins import substitute_params

        return substitute_params(str(value), self._extra_vars)

    def _make_browse_callback(self, var, ptype):
        def _browse():
            from tkinter import filedialog

            _place_window_on_screen(
                self._root,
                self._screen_bounds,
                self._root.winfo_width(),
                self._root.winfo_height(),
            )
            self._root.update_idletasks()
            initial = var.get() or None
            title = "Select directory" if ptype == "path-dir" else "Select file"
            if placement_notice(self._screen_bounds):
                title += " — Move this window to the tray screen"
            if ptype == "path-dir":
                path = filedialog.askdirectory(
                    parent=self._root,
                    initialdir=initial,
                    title=title,
                )
            else:
                path = filedialog.askopenfilename(
                    parent=self._root,
                    initialdir=initial,
                    title=title,
                )
            if path:
                var.set(path)

        return _browse

    def _submit(self):
        import shlex
        from ai_guardian.tray.plugins import (
            PluginParam,
            substitute_params,
            validate_param_value,
        )

        values = {}
        for param in self._params:
            name = param["name"]
            if name not in self._widgets:
                values[name] = param.get("default", "")
                continue
            wtype, var = self._widgets[name]
            if wtype == "boolean":
                values[name] = "true" if var.get() else "false"
            else:
                values[name] = var.get()

        for param in self._params:
            pp = PluginParam(
                name=param["name"],
                type=param.get("type", "string"),
                required=param.get("required", True),
                pattern=param.get("pattern"),
                options=param.get("options"),
                min=float(param["min"]) if param.get("min") is not None else None,
                max=float(param["max"]) if param.get("max") is not None else None,
            )
            valid, err = validate_param_value(pp, values.get(param["name"], ""))
            if not valid:
                _place_window_on_screen(
                    self._root,
                    self._screen_bounds,
                    self._root.winfo_width(),
                    self._root.winfo_height(),
                )
                self._root.update_idletasks()
                self._messagebox.showerror(
                    "Validation Error",
                    err,
                    parent=self._root,
                )
                return

        for param in self._params:
            ptype = param.get("type", "string")
            name = param["name"]
            if ptype in ("path-file", "path-dir") and values.get(name):
                values[name] = shlex.quote(values[name])

        self._result = substitute_params(self._command_template, values)
        self._root.destroy()


def _resolve(value, extra_vars):
    if not value or not extra_vars or "{" not in value:
        return value
    from ai_guardian.tray.plugins import substitute_params

    return substitute_params(value, extra_vars)


# -- NiceGUI fallback -------------------------------------------------------


def _native_file_picker(pick_directory=False, screen_bounds=None):
    """Auxiliary host-path picker; browser controls cannot return absolute paths.

    A NiceGUI parent deliberately delegates Browse to the local OS/Tk chooser,
    not a browser upload control. Cancel never reopens another picker.
    """
    preferred = get_preferred_ui()
    return run_modal(
        "picker",
        {
            "native": lambda: _native_file_picker_impl(pick_directory),
            "tkinter": lambda: _tkinter_file_picker_subprocess(
                pick_directory, screen_bounds=screen_bounds
            ),
        },
        fallback=None,
        screen_bounds=screen_bounds,
        preferred="auto" if preferred == "nicegui" else preferred,
    )


def _native_file_picker_impl(pick_directory=False):
    import platform
    from ai_guardian.ui.modal import run_native_command, UIUnavailable

    system = platform.system()
    try:
        if system == "Darwin":
            kind = "folder" if pick_directory else "file"
            script = f"POSIX path of (choose {kind})"
            result = run_native_command(["osascript", "-e", script])
            if result.returncode == 0:
                return result.stdout.strip()
        elif system == "Linux":
            cmd = ["zenity", "--file-selection"]
            if pick_directory:
                cmd.append("--directory")
            from ai_guardian.tray.plugins import _linux_dialog_provider_order

            commands = {
                "zenity": cmd,
                "kdialog": [
                    "kdialog",
                    "--getexistingdirectory" if pick_directory else "--getopenfilename",
                    ".",
                ],
            }
            for provider in _linux_dialog_provider_order():
                try:
                    result = run_native_command(commands[provider])
                except UIUnavailable:
                    continue
                return result.stdout.strip() or None if result.returncode == 0 else None
            raise UIUnavailable("No native path chooser could start")
        elif system == "Windows":
            if pick_directory:
                ps = (
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
                    "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"
                )
            else:
                ps = (
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "$d = New-Object System.Windows.Forms.OpenFileDialog;"
                    "if ($d.ShowDialog() -eq 'OK') { $d.FileName }"
                )
            result = run_native_command(["powershell", "-NoProfile", "-Command", ps])
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
    except UIUnavailable:
        raise
    return None


def _tkinter_file_picker_subprocess(pick_directory=False, screen_bounds=None):
    import json
    import sys
    from ai_guardian.ui.modal import run_modal_subprocess

    child = (
        "import json, sys; "
        "from ai_guardian.ui.tray_prompt import _show_tkinter_file_picker; "
        "from ai_guardian.ui.modal import run_modal_child; "
        "p=json.loads(sys.argv[1]); "
        "run_modal_child(lambda: _show_tkinter_file_picker(p['directory'], p['screen_bounds']))"
    )
    result = run_modal_subprocess(
        [
            sys.executable,
            "-c",
            child,
            json.dumps(
                {
                    "directory": pick_directory,
                    "screen_bounds": screen_payload(screen_bounds),
                }
            ),
        ]
    )
    output = (result.stdout or "").strip().splitlines()
    value = json.loads(output[-1]) if output else None
    return value if isinstance(value, str) and value else None


def _show_tkinter_file_picker(pick_directory=False, screen_bounds=None):
    import tkinter as tk
    from tkinter import filedialog
    from ai_guardian.ui.modal import mark_modal_displayed

    root = create_tk_root()
    root.withdraw()
    from ai_guardian.ui.monitor import place_tk_window

    place_tk_window(root, screen_bounds, 1, 1)
    root.update_idletasks()
    try:
        if screen_bounds is not None:
            # Native file panels choose their owner's monitor, not necessarily
            # the geometry of a never-mapped withdrawn root.
            try:
                root.attributes("-alpha", 0.0)
                root.deiconify()
                root.lift()
                root.update()
            except tk.TclError:
                logger.debug("Picker owner cannot use a transparent placement hint")
        choose = (
            filedialog.askdirectory if pick_directory else filedialog.askopenfilename
        )
        # The native panel does not map its withdrawn parent. After entering it,
        # visibility is unknown and a failure cannot authorize another picker.
        mark_modal_displayed()
        title = "Select directory" if pick_directory else "Select file"
        if placement_notice(screen_bounds):
            title += " — Move this window to the tray screen"
        return choose(parent=root, title=title) or None
    finally:
        root.destroy()


class _NiceGuiPromptApp:
    """Browser-based parameter form using NiceGUI (Python >= 3.10)."""

    def __init__(
        self,
        params,
        command_template,
        command_type="terminal",
        extra_vars=None,
        title=None,
        screen_bounds=None,
    ):
        self._params = params
        self._command_template = command_template
        self._command_type = command_type
        self._extra_vars = extra_vars or {}
        self._title = title or "Plugin Parameters"
        self._screen_bounds = screen_bounds
        self._result = None

    def run(self):
        from nicegui import app, ui

        result_holder: Dict[str, Optional[str]] = {"value": None}
        params = self._params
        extra_vars = self._extra_vars
        form_title = self._title
        command_template = self._command_template
        widgets: Dict[str, tuple[str, Any]] = {}

        @ui.page("/")
        def _form_page():
            ui.query("body").style("background: #1a1a2e")

            with (
                ui.card()
                .classes("mx-auto mt-8")
                .style("min-width: 400px; max-width: 600px")
            ):
                ui.label(form_title).classes("text-xl font-bold")
                ui.separator()

                for param in params:
                    label_text = param["name"]
                    if param.get("required", True):
                        label_text = "* " + label_text
                    hint = param.get("hint", "")

                    ptype = param.get("type", "string")
                    default = _resolve(
                        param.get("default", ""),
                        extra_vars,
                    )

                    if ptype == "boolean":
                        val = str(default).lower() == "true"
                        w = ui.switch(label_text, value=val)
                        if hint:
                            ui.label(hint).classes("text-xs text-grey-6")
                        widgets[param["name"]] = ("boolean", w)

                    elif ptype == "choice" or (
                        ptype == "string" and param.get("options")
                    ):
                        options = param.get("options", [])
                        if not default and options:
                            default = options[0]
                        ui.label(label_text).classes("text-sm mt-2")
                        if hint:
                            ui.label(hint).classes("text-xs text-grey-6")
                        w = ui.select(
                            options=options,
                            value=default,
                        ).classes("w-full")
                        widgets[param["name"]] = ("choice", w)

                    elif ptype == "combobox" and param.get("options"):
                        ui.label(label_text).classes("text-sm mt-2")
                        if hint:
                            ui.label(hint).classes("text-xs text-grey-6")
                        w = ui.select(
                            options=param["options"],
                            value=default or None,
                            with_input=True,
                            new_value_mode="add-unique",
                        ).classes("w-full")
                        widgets[param["name"]] = ("combobox", w)

                    elif ptype in ("int", "number"):
                        ui.label(label_text).classes("text-sm mt-2")
                        if hint:
                            ui.label(hint).classes("text-xs text-grey-6")
                        kwargs = {}
                        if param.get("min") is not None:
                            kwargs["min"] = float(param["min"])
                        if param.get("max") is not None:
                            kwargs["max"] = float(param["max"])
                        num_val = None
                        if default:
                            try:
                                num_val = float(default)
                            except (ValueError, TypeError):
                                pass  # intentionally silent — invalid value uses default
                        w = ui.number(
                            value=num_val,
                            **kwargs,
                        ).classes("w-full")
                        widgets[param["name"]] = ("number", w)

                    elif ptype in ("path-file", "path-dir"):
                        placeholder = hint or (
                            "Enter file path"
                            if ptype == "path-file"
                            else "Enter directory path"
                        )
                        ui.label(label_text).classes("text-sm mt-2")
                        with ui.row().classes("w-full items-center"):
                            w = ui.input(
                                value=default or "",
                                placeholder=placeholder,
                            ).classes("flex-grow")
                            pick_dir = ptype == "path-dir"

                            async def _browse(
                                inp=w,
                                is_dir=pick_dir,
                            ):
                                from nicegui import run as ng_run

                                path = await ng_run.io_bound(
                                    _native_file_picker,
                                    is_dir,
                                    self._screen_bounds,
                                )
                                if path:
                                    inp.set_value(path)

                            ui.button(
                                "Browse…",
                                on_click=_browse,
                            ).props("flat dense")
                        widgets[param["name"]] = ("entry", w)

                    else:
                        placeholder = hint or ""
                        ui.label(label_text).classes("text-sm mt-2")
                        w = ui.input(
                            value=default or "",
                            placeholder=placeholder,
                        ).classes("w-full")
                        widgets[param["name"]] = ("entry", w)

                ui.separator()
                with ui.row().classes("w-full justify-end"):
                    ui.button(
                        "Cancel",
                        on_click=lambda: _cancel(),
                    ).props("flat")
                    ui.button(
                        "OK",
                        on_click=lambda: _submit(),
                        color="primary",
                    )

        finished = {"done": False}

        def _close_and_shutdown():
            finished["done"] = True
            ui.run_javascript("window.close()")
            ui.timer(0.5, app.shutdown, once=True)

        def _cancel():
            result_holder["value"] = None
            _close_and_shutdown()

        def _submit():
            import shlex
            from ai_guardian.tray.plugins import (
                PluginParam,
                substitute_params,
                validate_param_value,
            )

            values = {}
            for param in params:
                name = param["name"]
                if name not in widgets:
                    values[name] = param.get("default", "")
                    continue
                wtype, w = widgets[name]
                if wtype == "boolean":
                    values[name] = "true" if w.value else "false"
                elif wtype == "number":
                    values[name] = str(int(w.value)) if w.value is not None else ""
                else:
                    values[name] = str(w.value) if w.value is not None else ""

            for param in params:
                pp = PluginParam(
                    name=param["name"],
                    type=param.get("type", "string"),
                    required=param.get("required", True),
                    pattern=param.get("pattern"),
                    options=param.get("options"),
                    min=(float(param["min"]) if param.get("min") is not None else None),
                    max=(float(param["max"]) if param.get("max") is not None else None),
                )
                valid, err = validate_param_value(
                    pp,
                    values.get(param["name"], ""),
                )
                if not valid:
                    from nicegui import ui as _ui

                    _ui.notify(err, type="negative")
                    return

            for param in params:
                ptype = param.get("type", "string")
                name = param["name"]
                if ptype in ("path-file", "path-dir") and values.get(name):
                    values[name] = shlex.quote(values[name])

            result_holder["value"] = substitute_params(
                command_template,
                values,
            )
            _close_and_shutdown()

        def _on_disconnect():
            if not finished["done"]:
                result_holder["value"] = None
            app.shutdown()

        app.on_disconnect(_on_disconnect)
        from ai_guardian.ui.modal import run_nicegui_modal

        run_nicegui_modal(form_title, dark=True, screen_bounds=self._screen_bounds)
        return result_holder["value"]


# -- Public API --------------------------------------------------------------


class TrayPromptApp:
    """Parameter form: tkinter → NiceGUI (browser).

    The ``needs_terminal`` attribute is set after construction so callers
    can decide whether to launch in a terminal window or as a headless
    subprocess.  Both tkinter and NiceGUI run without a terminal.
    """

    def __init__(
        self,
        params,
        command_template,
        command_type="terminal",
        extra_vars=None,
        title=None,
        screen_bounds=None,
    ):
        self._params = params
        self._command_template = command_template
        self._command_type = command_type
        self._extra_vars = extra_vars or {}
        self._title = title
        self._screen_bounds = screen_bounds
        self._result = None
        # Both supported providers run without a terminal. Keep the
        # attribute for callers that still inspect it.
        self.needs_terminal = False

    def run(self):
        args = (
            self._params,
            self._command_template,
            self._command_type,
            self._extra_vars,
            self._title,
            self._screen_bounds,
        )
        preferred = get_preferred_ui()

        if preferred == "headless":
            raise RuntimeError("preferred_ui is headless — no interactive UI available")

        return run_modal(
            "form",
            {
                "tkinter": lambda: _TkinterPromptApp(*args).run(),
                "nicegui": lambda: _NiceGuiPromptApp(*args).run(),
            },
            fallback=None,
            screen_bounds=self._screen_bounds,
            preferred=preferred,
        )

    def _resolve_default(self, value):
        """Resolve {tray.*} variables in a param default value."""
        return _resolve(value, self._extra_vars)
