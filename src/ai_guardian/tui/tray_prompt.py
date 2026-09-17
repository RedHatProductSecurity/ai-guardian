"""
Popup for collecting tray plugin parameters.

Launched by the tray via `ai-guardian prompt --mode params --params '<json>' --template '<template>'`.

Cascade: tkinter (native popup) → NiceGUI (browser form) → Textual (terminal).

To enable the tkinter popup, install the optional tkinter package:
  - macOS (pyenv): brew install tcl-tk && pyenv install <version> --force
  - UBI / RHEL:    dnf install -y python3-tkinter
  - Debian/Ubuntu: apt install -y python3-tk
  - Windows:       included by default in the python.org installer

tkinter is part of the Python standard library but requires the Tcl/Tk
system library at compile time.  When unavailable NiceGUI (Python 3.10+)
or the Textual fallback is used automatically.
"""

import logging
import os

from ai_guardian.tui.display import (
    _tkinter_available,
    _nicegui_available,
    get_preferred_ui,
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

        self._root = tk.Tk()

        if platform.system() == "Darwin":
            try:
                from AppKit import NSApplication

                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            except Exception:
                pass  # intentionally silent — optional dependency
        self._root.title(self._title)
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self._cancel)
        self._root.bind("<Escape>", lambda e: self._cancel())

        frame = ttk.Frame(self._root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")

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
                kwargs = {}
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

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(
            row=len(self._params),
            column=0,
            columnspan=2,
            pady=(16, 0),
            sticky="e",
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
            self._root.winfo_reqwidth(),
            self._root.winfo_reqheight(),
        )

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

            initial = var.get() or None
            if ptype == "path-dir":
                path = filedialog.askdirectory(
                    parent=self._root,
                    initialdir=initial,
                )
            else:
                path = filedialog.askopenfilename(
                    parent=self._root,
                    initialdir=initial,
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


# -- Textual fallback --------------------------------------------------------


class _TextualPromptApp:
    """Textual TUI fallback (requires a terminal window)."""

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

    def run(self):
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Container, Horizontal
        from textual.widgets import (
            Button,
            Checkbox,
            Footer,
            Header,
            Input,
            Label,
            Select,
            Static,
        )

        params = self._params
        command_template = self._command_template
        extra_vars = self._extra_vars
        form_title = self._title or "Plugin Parameters"

        class _App(App):
            CSS = """
            #form-container { padding: 1 2; }
            .param-row { margin: 1 0 0 0; }
            .param-row Label { margin: 0 0 0 0; }
            .param-row Input, .param-row Select { width: 100%; }
            #button-row { margin: 2 0 0 0; }
            #button-row Button { margin: 0 1 0 0; }
            """
            BINDINGS = [Binding("escape", "cancel", "Cancel")]

            def compose(self_inner) -> ComposeResult:
                yield Header(show_clock=False)
                with Container(id="form-container"):
                    yield Static(f"[bold]{form_title}[/bold]")
                    for param in params:
                        with Container(classes="param-row"):
                            label_text = param["name"]
                            if param.get("required", True):
                                label_text = "* " + label_text
                            if param.get("hint"):
                                label_text += f"  [dim]({param['hint']})[/dim]"
                            yield Label(label_text)

                            ptype = param.get("type", "string")
                            widget_id = f"param-{param['name']}"

                            if ptype == "boolean":
                                dv = _resolve(
                                    param.get("default", "false"),
                                    extra_vars,
                                )
                                yield Checkbox(
                                    "",
                                    value=dv.lower() == "true",
                                    id=widget_id,
                                )
                            elif ptype == "choice" or (
                                ptype == "string" and param.get("options")
                            ):
                                options = [(o, o) for o in param["options"]]
                                default = _resolve(
                                    param.get(
                                        "default",
                                        param["options"][0],
                                    ),
                                    extra_vars,
                                )
                                yield Select(
                                    options,
                                    value=default,
                                    id=widget_id,
                                )
                            else:
                                placeholder = param.get("hint", "")
                                if ptype == "path-file":
                                    suffix = " [file path]"
                                    placeholder = (
                                        placeholder + suffix
                                        if placeholder
                                        else "Enter file path"
                                    )
                                elif ptype == "path-dir":
                                    suffix = " [directory path]"
                                    placeholder = (
                                        placeholder + suffix
                                        if placeholder
                                        else "Enter directory path"
                                    )
                                elif ptype == "combobox" and param.get("options"):
                                    sug = ", ".join(param["options"])
                                    placeholder = (
                                        f"{placeholder} [{sug}]" if placeholder else sug
                                    )
                                yield Input(
                                    value=_resolve(
                                        param.get("default", ""),
                                        extra_vars,
                                    ),
                                    placeholder=placeholder,
                                    id=widget_id,
                                )
                    with Horizontal(id="button-row"):
                        yield Button(
                            "Submit",
                            id="submit-btn",
                            variant="primary",
                        )
                        yield Button("Cancel", id="cancel-btn")
                yield Footer()

            def on_button_pressed(self_inner, event):
                if event.button.id == "cancel-btn":
                    self_inner.exit(result=None)
                elif event.button.id == "submit-btn":
                    self_inner._do_submit()

            def action_cancel(self_inner):
                self_inner.exit(result=None)

            def _do_submit(self_inner):
                import shlex
                from ai_guardian.tray.plugins import (
                    PluginParam,
                    substitute_params,
                    validate_param_value,
                )

                values = {}
                for param in params:
                    wid = f"param-{param['name']}"
                    try:
                        widget = self_inner.query_one(f"#{wid}")
                    except Exception:
                        values[param["name"]] = param.get("default", "")
                        continue
                    if isinstance(widget, Checkbox):
                        values[param["name"]] = "true" if widget.value else "false"
                    elif isinstance(widget, Select):
                        val = widget.value
                        values[param["name"]] = (
                            str(val) if val is not Select.BLANK else ""
                        )
                    else:
                        values[param["name"]] = widget.value

                for param in params:
                    pp = PluginParam(
                        name=param["name"],
                        type=param.get("type", "string"),
                        required=param.get("required", True),
                        pattern=param.get("pattern"),
                        options=param.get("options"),
                        min=(
                            float(param["min"])
                            if param.get("min") is not None
                            else None
                        ),
                        max=(
                            float(param["max"])
                            if param.get("max") is not None
                            else None
                        ),
                    )
                    valid, err = validate_param_value(
                        pp,
                        values.get(param["name"], ""),
                    )
                    if not valid:
                        self_inner.notify(err, severity="error")
                        return

                for param in params:
                    ptype = param.get("type", "string")
                    name = param["name"]
                    if ptype in ("path-file", "path-dir") and values.get(name):
                        values[name] = shlex.quote(values[name])

                final = substitute_params(command_template, values)
                self_inner.exit(result=final)

        return _App().run()


def _resolve(value, extra_vars):
    if not value or not extra_vars or "{" not in value:
        return value
    from ai_guardian.tray.plugins import substitute_params

    return substitute_params(value, extra_vars)


# -- NiceGUI fallback -------------------------------------------------------


def _find_free_port():
    """Find an available TCP port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _native_file_picker(pick_directory=False):
    """Open a platform-native file/directory picker, return selected path or None."""
    import platform
    import subprocess

    system = platform.system()
    try:
        if system == "Darwin":
            kind = "folder" if pick_directory else "file"
            script = f"POSIX path of (choose {kind})"
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        elif system == "Linux":
            cmd = ["zenity", "--file-selection"]
            if pick_directory:
                cmd.append("--directory")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return result.stdout.strip()
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
            result = subprocess.run(
                ["powershell", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass  # intentionally silent — subprocess may fail
    return None


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

        result_holder = {"value": None}
        params = self._params
        extra_vars = self._extra_vars
        form_title = self._title
        command_template = self._command_template
        widgets = {}

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
        port = _find_free_port()

        from ai_guardian.desktop_utils import open_url

        url = f"http://127.0.0.1:{port}"
        app.on_startup(lambda: open_url(url))

        ui.run(
            host="127.0.0.1",
            port=port,
            title=form_title,
            dark=True,
            show=False,
            reload=False,
        )
        return result_holder["value"]


# -- Public API --------------------------------------------------------------


class TrayPromptApp:
    """Parameter form: tkinter → NiceGUI (browser) → Textual (terminal).

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
        preferred = get_preferred_ui()
        if preferred == "headless":
            self.needs_terminal = False
        elif preferred == "textual":
            self.needs_terminal = True
        elif preferred in ("tkinter", "nicegui"):
            self.needs_terminal = False
        else:
            self.needs_terminal = not _tkinter_available() and not _nicegui_available()

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

        if preferred == "tkinter":
            return _TkinterPromptApp(*args).run()
        if preferred == "nicegui":
            return _NiceGuiPromptApp(*args).run()
        if preferred == "textual":
            return _TextualPromptApp(*args).run()

        if _tkinter_available():
            try:
                return _TkinterPromptApp(*args).run()
            except Exception:
                logger.warning("tkinter failed at runtime, falling back")
        if _nicegui_available():
            return _NiceGuiPromptApp(*args).run()
        return _TextualPromptApp(*args).run()

    def _resolve_default(self, value):
        """Resolve {tray.*} variables in a param default value."""
        return _resolve(value, self._extra_vars)
