"""Tkinter implementation of the ask dialog.

Native popup dialog for ask mode decisions with pattern editor
and inline config editor.
"""

import platform

from ai_guardian.theme import (
    ANNOTATION_FG,
    CODE_BG,
    ERROR,
    HIGHLIGHT_BG,
    INFO,
    PRIMARY,
    SUCCESS,
    SURFACE,
    TEXT,
    TEXT_DIM,
    TEXT_MUTED,
    WARNING,
    get_image_path,
    violation_badge,
)
from ai_guardian.tui.ask_dialog import (
    AskDecision,
    AskViolationInfo,
    AskResult,
    _write_config_text,
    _write_aiguardignore_text,
    build_dialog_title,
    build_sub_dialog_title,
)
from ai_guardian.tui.display import _ensure_tcl_library


def _configure_theme_styles(style):
    """Configure ttk button styles using the unified theme palette."""
    style.theme_use("clam")

    style.configure("TFrame", background=SURFACE)
    style.configure("TLabel", background=SURFACE, foreground=TEXT)
    style.configure("TLabelframe", background=SURFACE, foreground=TEXT)
    style.configure("TLabelframe.Label", background=SURFACE, foreground=TEXT)
    style.configure("TSeparator", background=SURFACE)

    _btn_styles = {
        "AllowOnce.TButton": SUCCESS,
        "AllowAlways.TButton": PRIMARY,
        "Suppress.TButton": WARNING,
        "IgnoreFile.TButton": INFO,
        "Block.TButton": ERROR,
        "Save.TButton": SUCCESS,
    }
    for name, bg in _btn_styles.items():
        style.configure(name, background=bg, foreground="white")
        style.map(name, background=[("active", bg)])


def _apply_dark_root(root):
    """Apply dark theme to the root window."""
    root.configure(bg=SURFACE)
    try:
        icon_path = get_image_path("tray-icon-32.png")
        if icon_path:
            import tkinter as tk

            icon = tk.PhotoImage(file=str(icon_path))
            root.iconphoto(False, icon)
            root._theme_icon = icon  # prevent GC
    except Exception:
        pass  # intentionally silent — best-effort operation


# Monospace font for code/config editors — computed once at module scope
_CODE_FONT = ("Menlo" if platform.system() == "Darwin" else "Consolas", 11)


def _format_location(v) -> str:
    """Build 'path:line:col' string from a violation info object."""
    loc = v.file_path or ""
    if v.line_number:
        loc += f":{v.line_number}"
        if v.start_column is not None:
            loc += f":{v.start_column + 1}"
    return loc


def _setup_sub_dialog(editor, root):
    """Apply standard boilerplate to a Toplevel sub-dialog."""
    editor.attributes("-topmost", True)
    editor.protocol("WM_DELETE_WINDOW", lambda: (editor.destroy(), root.deiconify()))
    editor.focus_force()
    editor.grab_set()
    editor.configure(bg=SURFACE)

    from tkinter import ttk

    ttk.Style(editor).theme_use("clam")


class _TkinterAskDialog:
    """Native tkinter dialog for ask mode decisions."""

    def __init__(self, violation: AskViolationInfo, timeout_seconds: int = 300):
        self._violation = violation
        self._timeout = timeout_seconds
        self._result = AskResult(decision=AskDecision.BLOCK)

    def run(self) -> AskResult:
        import tkinter as tk
        from tkinter import ttk

        _ensure_tcl_library()

        root = tk.Tk()

        if platform.system() == "Darwin":
            try:
                from AppKit import NSApplication

                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            except Exception:
                pass  # intentionally silent — optional dependency

        root.title(build_dialog_title(self._violation))
        root.resizable(False, False)
        root.protocol(
            "WM_DELETE_WINDOW", lambda: self._on_decision(root, AskDecision.BLOCK)
        )
        root.bind("<Escape>", lambda e: self._on_decision(root, AskDecision.BLOCK))

        root.attributes("-topmost", True)

        style = ttk.Style(root)
        _configure_theme_styles(style)
        _apply_dark_root(root)

        main = ttk.Frame(root, padding=15)
        main.pack(fill="both", expand=True)

        v = self._violation
        icon, badge_color = violation_badge(v.violation_type)
        header_frame = ttk.Frame(main)
        header_frame.pack(fill="x")
        tk.Label(
            header_frame,
            text=f"{icon} ",
            font=("", 16),
            bg=SURFACE,
            fg=badge_color,
        ).pack(side="left")
        ttk.Label(header_frame, text="Violation Detected", font=("", 14, "bold")).pack(
            side="left"
        )
        if v.total_findings and v.total_findings > 1:
            remaining = v.total_findings - (v.finding_index or 0) - 1
            counter_text = f"  ({v.finding_index + 1} of {v.total_findings}"
            if remaining > 0:
                counter_text += f", {remaining} more"
            counter_text += ")"
            ttk.Label(header_frame, text=counter_text, font=("", 11)).pack(
                side="left", padx=(5, 0)
            )
        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=(5, 10))

        info_frame = ttk.LabelFrame(main, text="Details", padding=10)
        info_frame.pack(fill="x", pady=(0, 10))

        details = [
            ("Type", f"{icon} {v.violation_type}"),
        ]
        if v.hook_event:
            details.append(("Hook", v.hook_event))
        details.append(("Summary", v.summary))
        if v.file_path:
            details.append(("Location", _format_location(v)))

        for label, value in details:
            row = ttk.Frame(info_frame)
            row.pack(fill="x", pady=1)
            ttk.Label(
                row, text=f"{label}:", font=("", 0, "bold"), width=12, anchor="w"
            ).pack(side="left")
            ttk.Label(row, text=value, wraplength=600).pack(
                side="left", fill="x", expand=True
            )

        text_frame = ttk.LabelFrame(main, text="Matched Text", padding=5)
        text_frame.pack(fill="x", pady=(0, 10))
        matched_display = tk.Text(
            text_frame,
            height=3,
            width=60,
            wrap="word",
            state="normal",
            background=CODE_BG,
            foreground=TEXT_MUTED,
        )
        matched_display.insert("1.0", v.matched_text[:500])
        matched_display.config(state="disabled")
        matched_display.pack(fill="x")

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=(5, 0))

        ttk.Button(
            btn_frame,
            text="Allow Once",
            style="AllowOnce.TButton",
            command=lambda: self._on_decision(root, AskDecision.ALLOW_ONCE),
        ).pack(side="left", padx=(0, 5))

        ttk.Button(
            btn_frame,
            text="Allow Always...",
            style="AllowAlways.TButton",
            command=lambda: self._on_allow_always(root),
        ).pack(side="left", padx=5)

        if v.file_path:
            ttk.Button(
                btn_frame,
                text="View File",
                command=lambda: self._on_view_file(),
            ).pack(side="left", padx=5)

            from ai_guardian.tui.source_annotator import get_comment_prefix

            if get_comment_prefix(v.file_path) is not None:
                ttk.Button(
                    btn_frame,
                    text="Suppress in Source...",
                    style="Suppress.TButton",
                    command=lambda: self._on_suppress_in_source(root),
                ).pack(side="left", padx=5)

            ttk.Button(
                btn_frame,
                text="Ignore File...",
                style="IgnoreFile.TButton",
                command=lambda: self._on_ignore_file(root),
            ).pack(side="left", padx=5)

        if v.total_findings and v.total_findings > 1:
            ttk.Button(
                btn_frame,
                text="Block All",
                style="Block.TButton",
                command=lambda: self._on_decision(root, AskDecision.BLOCK_ALL),
            ).pack(side="right", padx=(5, 0))
        ttk.Button(
            btn_frame,
            text="Block",
            style="Block.TButton",
            command=lambda: self._on_decision(root, AskDecision.BLOCK),
        ).pack(side="right")

        if self._timeout > 0:
            root.after(
                self._timeout * 1000, lambda: self._on_decision(root, AskDecision.BLOCK)
            )

        root.mainloop()
        return self._result

    def _on_decision(self, root, decision: AskDecision):
        self._result = AskResult(decision=decision)
        root.destroy()

    def _on_view_file(self):
        from ai_guardian.tui.file_opener import open_in_editor

        open_in_editor(self._violation.file_path, self._violation.line_number)

    def _show_config_editor(self, root, save_pat):
        """Show a full config editor with the pattern inserted in memory."""
        import tkinter as tk
        from tkinter import ttk

        from ai_guardian.tui.pattern_editor import (
            prepare_config_with_pattern,
            get_config_scope_options,
        )

        v = self._violation
        scope_options = get_config_scope_options(project_dir=v.project_path)
        selected_path = scope_options[0][1]
        json_text, line_number = prepare_config_with_pattern(
            save_pat,
            v.config_section,
            config_path=selected_path,
        )

        editor = tk.Toplevel(root)
        editor.title(
            build_sub_dialog_title("Config Editor — ai-guardian.json", self._violation)
        )
        editor.resizable(True, True)
        editor.geometry("700x500")
        _setup_sub_dialog(editor, root)

        frame = ttk.Frame(editor, padding=10)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Review Config", font=("", 14, "bold")).pack(anchor="w")
        if v.file_path:
            ttk.Label(
                frame, text=f"Source: {_format_location(v)}", wraplength=650
            ).pack(anchor="w", pady=(0, 5))
        ttk.Label(
            frame,
            text="The pattern has been inserted below. Review the full config, then Save or Cancel.",
            wraplength=650,
        ).pack(anchor="w", pady=(0, 5))
        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(0, 5))

        if len(scope_options) > 1:
            scope_frame = ttk.LabelFrame(frame, text="Save to", padding=5)
            scope_frame.pack(fill="x", pady=(0, 5))
            scope_var = tk.StringVar(value=selected_path)
            for label, path_str in scope_options:
                ttk.Radiobutton(
                    scope_frame,
                    text=f"{label} ({path_str})",
                    variable=scope_var,
                    value=path_str,
                ).pack(anchor="w")

            def _on_scope_change(*_args):
                nonlocal json_text, line_number, selected_path
                selected_path = scope_var.get()
                json_text, line_number = prepare_config_with_pattern(
                    save_pat,
                    v.config_section,
                    config_path=selected_path,
                )
                config_text.config(state="normal")
                config_text.delete("1.0", "end")
                config_text.insert("1.0", json_text)
                config_text.tag_add(
                    "highlight", f"{line_number}.0", f"{line_number}.end"
                )
                config_text.tag_config("highlight", background=HIGHLIGHT_BG)
                config_text.see(f"{line_number}.0")
                config_text.update_idletasks()

            scope_var.trace_add("write", _on_scope_change)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(side="bottom", fill="x", pady=(5, 0))

        status_var = tk.StringVar(value="Valid JSON")
        status_label = tk.Label(
            frame,
            textvariable=status_var,
            font=("", 11),
            anchor="w",
            fg=SUCCESS,
            bg=SURFACE,
        )
        status_label.pack(side="bottom", fill="x")

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill="both", expand=True, pady=(0, 5))

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")

        config_text = tk.Text(
            text_frame,
            wrap="none",
            undo=True,
            font=_CODE_FONT,
            yscrollcommand=scrollbar.set,
        )
        config_text.pack(fill="both", expand=True)
        scrollbar.config(command=config_text.yview)

        config_text.insert("1.0", json_text)
        config_text.update_idletasks()
        config_text.mark_set("insert", f"{line_number}.0")
        config_text.see(f"{line_number}.0")
        config_text.tag_add("highlight", f"{line_number}.0", f"{line_number}.end")
        config_text.tag_config("highlight", background=HIGHLIGHT_BG)

        def on_save():
            import json as json_mod

            text = config_text.get("1.0", "end-1c")
            try:
                json_mod.loads(text)
            except json_mod.JSONDecodeError as e:
                status_var.set(f"Invalid JSON: {e}")
                status_label.config(fg=ERROR)
                return
            if _write_config_text(text, config_path_str=selected_path):
                self._result = AskResult(
                    decision=AskDecision.ALLOW_ALWAYS,
                    allowlist_pattern=save_pat,
                    config_saved=True,
                    config_path=selected_path,
                )
                editor.destroy()
                root.destroy()
            else:
                status_var.set("Failed to write config file")
                status_label.config(fg=ERROR)

        def on_cancel():
            editor.destroy()
            root.deiconify()

        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="right")
        ttk.Button(btn_frame, text="Save", command=on_save, style="Save.TButton").pack(
            side="right", padx=(0, 5)
        )

    def _on_allow_always(self, root):
        """Open the pattern editor and process the result."""
        import tkinter as tk
        from tkinter import ttk

        from ai_guardian.tui.pattern_editor import (
            validate_pattern,
            generate_config_preview,
            suggest_pattern,
            get_pattern_type_for_section,
            PATTERN_TYPES,
        )

        v = self._violation
        ptype = get_pattern_type_for_section(v.config_section)
        ptype_label = PATTERN_TYPES.get(ptype, ptype)

        root.withdraw()
        editor = tk.Toplevel(root)
        editor.title(
            build_sub_dialog_title("Allow Always — Edit Pattern", self._violation)
        )
        editor.resizable(False, False)
        _setup_sub_dialog(editor, root)

        frame = ttk.Frame(editor, padding=15)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame, text="Allow Always — Edit Pattern", font=("", 12, "bold")
        ).pack(anchor="w")
        if v.file_path:
            ttk.Label(frame, text=f"File: {_format_location(v)}", wraplength=500).pack(
                anchor="w", pady=(0, 5)
            )
        ttk.Label(
            frame,
            text=f"Edit the {ptype_label.lower()} below to match this text. The pattern will be added to the allowlist.",
            wraplength=500,
        ).pack(anchor="w", pady=(0, 5))
        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(0, 10))

        ttk.Label(frame, text="Matched text (reference):", font=("", 0, "bold")).pack(
            anchor="w"
        )
        matched_display = tk.Text(
            frame, height=2, width=60, wrap="word", state="normal"
        )
        matched_display.insert("1.0", v.matched_text[:500])
        matched_display.config(
            state="disabled", background=CODE_BG, foreground=TEXT_MUTED
        )
        matched_display.pack(fill="x", pady=(0, 10))

        ttk.Label(frame, text=f"Pattern ({ptype_label}):", font=("", 0, "bold")).pack(
            anchor="w"
        )
        pattern_var = tk.StringVar(
            value=(
                suggest_pattern(v.matched_text, v.config_section)
                if v.matched_text
                else ""
            )
        )
        pattern_entry = ttk.Entry(frame, textvariable=pattern_var, width=60)
        pattern_entry.pack(fill="x", pady=(0, 5))

        test_frame = ttk.Frame(frame)
        test_frame.pack(fill="x", pady=(0, 10))

        status_var = tk.StringVar(value="")
        status_label = tk.Label(
            test_frame,
            textvariable=status_var,
            font=("", 11, "bold"),
            anchor="w",
            bg=SURFACE,
        )
        status_label.pack(side="right", fill="x", expand=True, padx=(10, 0))

        def do_test():
            pat = pattern_var.get().strip()
            valid, msg = validate_pattern(pat, ptype, v.matched_text)
            if valid:
                status_var.set(f"✅ PASS: {msg}")
                status_label.config(fg=SUCCESS)
                preview_text.config(state="normal")
                preview_text.delete("1.0", "end")
                preview_text.insert(
                    "1.0", generate_config_preview(pat, v.config_section)
                )
                preview_text.config(state="disabled")
            else:
                status_var.set(f"❌ FAIL: {msg}")
                status_label.config(fg=ERROR)

        ttk.Button(test_frame, text="Test Pattern", command=do_test).pack(side="left")

        ttk.Label(frame, text="Config preview:", font=("", 0, "bold")).pack(anchor="w")
        preview_text = tk.Text(frame, height=6, width=60, wrap="word", state="disabled")
        preview_text.pack(fill="x", pady=(0, 10))

        do_test()

        _debounce_id = [None]

        def _on_pattern_change(*_args):
            if _debounce_id[0] is not None:
                editor.after_cancel(_debounce_id[0])
            _debounce_id[0] = editor.after(300, do_test)

        pattern_var.trace_add("write", _on_pattern_change)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x")

        def on_confirm():
            pat = pattern_var.get().strip()
            valid, _ = validate_pattern(pat, ptype, v.matched_text)
            if not valid:
                status_var.set("❌ FAIL: Fix the pattern before confirming")
                status_label.config(fg=ERROR)
                return
            editor.destroy()
            self._show_config_editor(root, pat)

        def on_cancel():
            editor.destroy()
            root.deiconify()

        ttk.Button(
            btn_frame, text="Add to Allowlist", command=on_confirm, style="Save.TButton"
        ).pack(side="right", padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="right")

    def _on_suppress_in_source(self, root):
        """Open source annotation preview editor."""
        import tkinter as tk
        from tkinter import ttk

        from ai_guardian.tui.source_annotator import (
            prepare_annotation,
            write_annotated_source,
        )

        v = self._violation
        violation_line = v.line_number or 1
        result = prepare_annotation(v.file_path, violation_line)
        if result is None:
            return

        modified_content, highlight_line, annotation_type = result

        root.withdraw()
        editor = tk.Toplevel(root)
        ann_label = (
            "inline" if annotation_type == "inline" else "block (begin-allow/end-allow)"
        )
        editor.title(
            build_sub_dialog_title(f"Suppress in Source — {ann_label}", self._violation)
        )
        editor.resizable(True, True)
        editor.geometry("800x550")
        _setup_sub_dialog(editor, root)

        frame = ttk.Frame(editor, padding=10)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame, text=f"Suppress in Source — {ann_label}", font=("", 14, "bold")
        ).pack(anchor="w")
        ttk.Label(frame, text=f"File: {_format_location(v)}", wraplength=700).pack(
            anchor="w", pady=(0, 5)
        )
        ttk.Label(
            frame,
            text="Review the annotated source below. Save to write the file.",
            wraplength=700,
        ).pack(anchor="w", pady=(0, 5))
        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(0, 5))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(side="bottom", fill="x", pady=(5, 0))

        status_var = tk.StringVar(value="")
        status_label = tk.Label(
            frame, textvariable=status_var, font=("", 11), anchor="w", bg=SURFACE
        )
        status_label.pack(side="bottom", fill="x")

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill="both", expand=True, pady=(0, 5))

        yscrollbar = ttk.Scrollbar(text_frame, orient="vertical")
        yscrollbar.pack(side="right", fill="y")

        xscrollbar = ttk.Scrollbar(text_frame, orient="horizontal")
        xscrollbar.pack(side="bottom", fill="x")

        gutter = tk.Text(
            text_frame,
            width=5,
            padx=4,
            takefocus=0,
            border=0,
            state="disabled",
            wrap="none",
            font=_CODE_FONT,
            background=CODE_BG,
            foreground=TEXT_DIM,
        )
        gutter.pack(side="left", fill="y")

        source_text = tk.Text(
            text_frame,
            wrap="none",
            undo=True,
            font=_CODE_FONT,
            yscrollcommand=yscrollbar.set,
            xscrollcommand=xscrollbar.set,
        )
        source_text.pack(fill="both", expand=True)

        def _sync_scroll(*args):
            source_text.yview(*args)
            gutter.yview(*args)

        yscrollbar.config(command=_sync_scroll)
        xscrollbar.config(command=source_text.xview)

        def _on_source_yscroll(*args):
            yscrollbar.set(*args)
            gutter.yview_moveto(args[0])

        source_text.config(yscrollcommand=_on_source_yscroll)

        source_text.insert("1.0", modified_content)

        line_count = int(source_text.index("end-1c").split(".")[0])
        gutter.config(state="normal")
        gutter.insert("1.0", "\n".join(str(i) for i in range(1, line_count + 1)))
        gutter.config(state="disabled")

        source_text.tag_add("highlight", f"{highlight_line}.0", f"{highlight_line}.end")
        source_text.tag_config("highlight", background=HIGHLIGHT_BG)

        source_text.tag_config("annotation", foreground=ANNOTATION_FG)
        for marker in [
            "ai-guardian:allow",
            "ai-guardian:begin-allow",
            "ai-guardian:end-allow",
        ]:
            search_start = "1.0"
            while True:
                pos = source_text.search(marker, search_start, stopindex="end")
                if not pos:
                    break
                end_pos = f"{pos}+{len(marker)}c"
                source_text.tag_add("annotation", pos, end_pos)
                search_start = end_pos

        source_text.update_idletasks()
        source_text.yview_moveto(1.0)
        source_text.update_idletasks()
        source_text.mark_set("insert", f"{highlight_line}.0")
        source_text.see(f"{highlight_line}.0")

        def on_save():
            text = source_text.get("1.0", "end-1c")
            if write_annotated_source(v.file_path, text):
                self._result = AskResult(
                    decision=AskDecision.SUPPRESS_IN_SOURCE,
                    source_annotation_saved=True,
                )
                editor.destroy()
                root.destroy()
            else:
                status_var.set("Failed to write file")
                status_label.config(fg=ERROR)

        def on_cancel():
            editor.destroy()
            root.deiconify()

        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="right")
        ttk.Button(btn_frame, text="Save", command=on_save, style="Save.TButton").pack(
            side="right", padx=(0, 5)
        )

    def _on_ignore_file(self, root):
        """Open ignore file path/scope editor."""
        import tkinter as tk
        from tkinter import ttk

        from ai_guardian.tui.ignore_file_editor import (
            SCOPE_THIS_SCANNER,
            SCOPE_ALL_SCANNERS,
            SCOPE_SELECT_SCANNERS,
            SCANNER_LABELS,
            resolve_scanner_types,
            validate_ignore_path,
            suggest_ignore_path,
        )
        from ai_guardian.aiguardignore import (
            SCANNER_TYPES,
            generate_aiguardignore_preview,
        )

        v = self._violation
        rel_path = suggest_ignore_path(v.file_path)

        root.withdraw()
        editor = tk.Toplevel(root)
        editor.title(
            build_sub_dialog_title("Ignore File — .aiguardignore.toml", self._violation)
        )
        editor.resizable(True, True)
        editor.geometry("700x550")
        _setup_sub_dialog(editor, root)

        frame = ttk.Frame(editor, padding=10)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame, text="Ignore File — .aiguardignore.toml", font=("", 14, "bold")
        ).pack(anchor="w")
        ttk.Label(frame, text=f"File: {_format_location(v)}", wraplength=650).pack(
            anchor="w", pady=(0, 5)
        )
        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(0, 10))

        ttk.Label(frame, text="Path pattern (editable):", font=("", 0, "bold")).pack(
            anchor="w"
        )
        path_var = tk.StringVar(value=rel_path)
        path_entry = ttk.Entry(frame, textvariable=path_var, width=60)
        path_entry.pack(fill="x", pady=(0, 5))

        path_status_var = tk.StringVar(value="")
        path_status_label = tk.Label(
            frame, textvariable=path_status_var, font=("", 11), anchor="w", bg=SURFACE
        )
        path_status_label.pack(fill="x", pady=(0, 5))

        ttk.Label(frame, text="Scope:", font=("", 0, "bold")).pack(anchor="w")
        scope_var = tk.StringVar(value=SCOPE_THIS_SCANNER)
        scanner_label = SCANNER_LABELS.get(v.config_section, v.config_section)

        scope_frame = ttk.Frame(frame)
        scope_frame.pack(fill="x", pady=(0, 5))
        ttk.Radiobutton(
            scope_frame,
            text=f"This scanner only ({scanner_label})",
            variable=scope_var,
            value=SCOPE_THIS_SCANNER,
        ).pack(anchor="w")
        ttk.Radiobutton(
            scope_frame,
            text="All scanners",
            variable=scope_var,
            value=SCOPE_ALL_SCANNERS,
        ).pack(anchor="w")
        ttk.Radiobutton(
            scope_frame,
            text="Select scanners...",
            variable=scope_var,
            value=SCOPE_SELECT_SCANNERS,
        ).pack(anchor="w")

        scanner_vars = {}
        scanner_frame = ttk.LabelFrame(frame, text="Scanners", padding=5)
        for st in sorted(SCANNER_TYPES):
            var = tk.BooleanVar(value=(st == v.config_section))
            scanner_vars[st] = var
            ttk.Checkbutton(
                scanner_frame, text=SCANNER_LABELS.get(st, st), variable=var
            ).pack(anchor="w")

        ttk.Label(frame, text="Preview:", font=("", 0, "bold")).pack(anchor="w")
        preview_text = tk.Text(frame, height=8, width=60, wrap="word", state="disabled")
        preview_text.pack(fill="both", expand=True, pady=(0, 5))

        def update_preview(*_args):
            path = path_var.get().strip()
            valid, msg = validate_ignore_path(path)
            if not valid:
                path_status_var.set(f"❌ {msg}")
                path_status_label.config(fg=ERROR)
                return
            path_status_var.set(f"✅ {msg}")
            path_status_label.config(fg=SUCCESS)

            show_select = scope_var.get() == SCOPE_SELECT_SCANNERS
            if show_select:
                scanner_frame.pack(
                    fill="x",
                    pady=(0, 5),
                    before=(
                        preview_text.master if hasattr(preview_text, "master") else None
                    ),
                )
            else:
                scanner_frame.pack_forget()

            selected = [st for st, var in scanner_vars.items() if var.get()]
            scanner_types = resolve_scanner_types(
                scope_var.get(), v.config_section, selected
            )

            try:
                toml_text, _ = generate_aiguardignore_preview(path, scanner_types)
                preview_text.config(state="normal")
                preview_text.delete("1.0", "end")
                preview_text.insert("1.0", toml_text)
                preview_text.config(state="disabled")
            except Exception:
                pass  # intentionally silent — preview generation best-effort

        path_var.trace_add("write", update_preview)
        scope_var.trace_add("write", update_preview)
        for var in scanner_vars.values():
            var.trace_add("write", update_preview)
        update_preview()

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=(5, 0))

        def on_confirm():
            path = path_var.get().strip()
            valid, msg = validate_ignore_path(path)
            if not valid:
                path_status_var.set(f"❌ {msg}")
                path_status_label.config(fg=ERROR)
                return
            selected = [st for st, var in scanner_vars.items() if var.get()]
            scanner_types = resolve_scanner_types(
                scope_var.get(), v.config_section, selected
            )
            editor.destroy()
            self._show_aiguardignore_editor(root, path, scanner_types)

        def on_cancel():
            editor.destroy()
            root.deiconify()

        ttk.Button(
            btn_frame,
            text="Add to .aiguardignore.toml",
            command=on_confirm,
            style="Save.TButton",
        ).pack(side="right", padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="right")

    def _show_aiguardignore_editor(self, root, path, scanner_types):
        """Show a full TOML editor for .aiguardignore.toml."""
        import tkinter as tk
        from tkinter import ttk

        from ai_guardian.aiguardignore import generate_aiguardignore_preview

        toml_text, line_number = generate_aiguardignore_preview(path, scanner_types)

        editor = tk.Toplevel(root)
        editor.title(
            build_sub_dialog_title(
                "Config Editor — .aiguardignore.toml", self._violation
            )
        )
        editor.resizable(True, True)
        editor.geometry("700x500")
        _setup_sub_dialog(editor, root)

        frame = ttk.Frame(editor, padding=10)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame, text="Config Editor — .aiguardignore.toml", font=("", 14, "bold")
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="Review the file. Save to persist the change.",
            wraplength=650,
        ).pack(anchor="w", pady=(0, 5))
        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(0, 5))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(side="bottom", fill="x", pady=(5, 0))

        status_var = tk.StringVar(value="")
        status_label = tk.Label(
            frame, textvariable=status_var, font=("", 11), anchor="w", bg=SURFACE
        )
        status_label.pack(side="bottom", fill="x")

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill="both", expand=True, pady=(0, 5))

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")

        config_text = tk.Text(
            text_frame,
            wrap="none",
            undo=True,
            font=_CODE_FONT,
            yscrollcommand=scrollbar.set,
        )
        config_text.pack(fill="both", expand=True)
        scrollbar.config(command=config_text.yview)

        config_text.insert("1.0", toml_text)
        config_text.mark_set("insert", f"{line_number}.0")
        config_text.see(f"{line_number}.0")
        config_text.tag_add("highlight", f"{line_number}.0", f"{line_number}.end")
        config_text.tag_config("highlight", background=HIGHLIGHT_BG)

        def on_save():
            text = config_text.get("1.0", "end-1c")
            if _write_aiguardignore_text(text):
                self._result = AskResult(
                    decision=AskDecision.IGNORE_FILE,
                    ignore_path=path,
                    ignore_scanner_types=scanner_types,
                    config_saved=True,
                )
                editor.destroy()
                root.destroy()
            else:
                status_var.set("Failed to write .aiguardignore.toml")
                status_label.config(fg=ERROR)

        def on_cancel():
            editor.destroy()
            root.deiconify()

        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="right")
        ttk.Button(btn_frame, text="Save", command=on_save, style="Save.TButton").pack(
            side="right", padx=(0, 5)
        )
