"""NiceGUI (browser-based) implementation of the ask dialog.

Browser popup dialog for ask mode decisions with pattern editor
and inline config editor using CodeMirror.
"""

import platform

from ai_guardian.theme import (
    quasar_button,
    quasar_color,
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


def _show_nicegui_config_editor(dialog_self, app, save_pat, config_section):
    """Show a NiceGUI config editor dialog with the pattern inserted in memory."""
    import json as json_mod
    from nicegui import ui
    from ai_guardian.tui.pattern_editor import (
        prepare_config_with_pattern,
        get_config_scope_options,
    )

    project_dir = getattr(dialog_self, "_violation", None)
    project_dir = getattr(project_dir, "project_path", None) if project_dir else None
    scope_options = get_config_scope_options(project_dir=project_dir)
    scope_map = {label: path_str for label, path_str in scope_options}
    selected = {"path": scope_options[0][1]}

    json_text, _line_number = prepare_config_with_pattern(
        save_pat,
        config_section,
        config_path=selected["path"],
    )

    with (
        ui.dialog().props("persistent maximized") as editor_dlg,
        ui.card().classes("w-full h-full"),
    ):
        ui.label(
            build_sub_dialog_title(
                "Config Editor — ai-guardian.json", dialog_self._violation
            )
        ).classes("text-lg font-bold")
        v = dialog_self._violation
        if v.file_path:
            line_info = f":{v.line_number}" if v.line_number else ""
            if v.start_column is not None and v.line_number:
                line_info += f":{v.start_column + 1}"
            ui.label(f"Source: {v.file_path}{line_info}").classes("text-sm text-grey-6")
        ui.label(
            "Review the full config with the inserted pattern. Save to persist or Cancel to discard."
        ).classes("text-sm text-grey-6")
        ui.separator()

        ui.label("Save to:").classes("font-bold text-sm")
        scope_radio = ui.radio(
            scope_map,
            value=scope_options[0][0],
        ).props("dense")

        def on_scope_change(e):
            selected["path"] = scope_map[e.value]
            new_text, _ = prepare_config_with_pattern(
                save_pat,
                config_section,
                config_path=selected["path"],
            )
            editor.value = new_text

        scope_radio.on_value_change(on_scope_change)

        editor = (
            ui.codemirror(
                json_text,
                language="JSON",
                theme="dracula",
                line_wrapping=True,
            )
            .classes("w-full flex-grow")
            .style("min-height: 400px")
        )

        editor_status = ui.label("Valid JSON").classes("text-sm text-green")

        def on_editor_change(e):
            try:
                json_mod.loads(e.value)
                editor_status.text = "Valid JSON"
                editor_status.classes(replace="text-sm text-green")
            except json_mod.JSONDecodeError as exc:
                editor_status.text = f"Invalid JSON: {exc}"
                editor_status.classes(replace="text-sm text-red")

        editor.on_value_change(on_editor_change)

        with ui.row().classes("w-full justify-end mt-2"):

            def on_cancel():
                editor_dlg.close()

            def on_save():
                text = editor.value
                try:
                    json_mod.loads(text)
                except json_mod.JSONDecodeError as exc:
                    editor_status.text = f"Invalid JSON: {exc}"
                    editor_status.classes(replace="text-sm text-red")
                    return
                if _write_config_text(text, config_path_str=selected["path"]):
                    dialog_self._result = AskResult(
                        decision=AskDecision.ALLOW_ALWAYS,
                        allowlist_pattern=save_pat,
                        config_saved=True,
                        config_path=selected["path"],
                    )
                    ui.run_javascript("window.close()")
                    app.shutdown()
                else:
                    editor_status.text = "Failed to write config file"
                    editor_status.classes(replace="text-sm text-red")

            ui.button("Cancel", on_click=on_cancel).props("flat")
            ui.button("Save", on_click=on_save).props(f"color={quasar_button('save')}")

    editor_dlg.open()


def _show_nicegui_suppress_in_source(dialog_self, app, v):
    """Show source annotation preview in NiceGUI."""
    from nicegui import ui
    from ai_guardian.tui.source_annotator import (
        prepare_annotation,
        write_annotated_source,
    )

    result = prepare_annotation(v.file_path, v.line_number or 1)
    if result is None:
        ui.notify("Cannot annotate this file type", type="warning")
        return

    modified_content, highlight_line, annotation_type = result
    ann_label = (
        "inline" if annotation_type == "inline" else "block (begin-allow/end-allow)"
    )

    with (
        ui.dialog().props("persistent maximized") as dlg,
        ui.card().classes("w-full h-full"),
    ):
        ui.label(
            build_sub_dialog_title(f"Suppress in Source — {ann_label}", v)
        ).classes("text-lg font-bold")
        line_info = f":{v.line_number}" if v.line_number else ""
        if v.start_column is not None and v.line_number:
            line_info += f":{v.start_column + 1}"
        ui.label(f"File: {v.file_path}{line_info}").classes("text-sm text-grey-6")
        ui.label("Review the annotated source. Save to write the file.").classes(
            "text-sm text-grey-6"
        )
        ui.separator()

        editor = (
            ui.codemirror(
                modified_content,
                language="Python" if v.file_path.endswith(".py") else None,
                theme="dracula",
                line_wrapping=True,
            )
            .classes("w-full flex-grow")
            .style("min-height: 400px")
        )

        status = ui.label("").classes("text-sm")

        with ui.row().classes("w-full justify-end mt-2"):
            ui.button("Cancel", on_click=dlg.close).props("flat")

            def on_save():
                if write_annotated_source(v.file_path, editor.value):
                    dialog_self._result = AskResult(
                        decision=AskDecision.SUPPRESS_IN_SOURCE,
                        source_annotation_saved=True,
                    )
                    ui.run_javascript("window.close()")
                    app.shutdown()
                else:
                    status.text = "Failed to write file"
                    status.classes(replace="text-sm text-red")

            ui.button("Save", on_click=on_save).props(f"color={quasar_button('save')}")

    dlg.open()


def _show_nicegui_ignore_file(dialog_self, app, v):
    """Show ignore file editor in NiceGUI."""
    from nicegui import ui
    from ai_guardian.tui.ignore_file_editor import (
        SCOPE_THIS_SCANNER,
        SCOPE_ALL_SCANNERS,
        SCANNER_LABELS,
        resolve_scanner_types,
        validate_ignore_path,
        suggest_ignore_path,
    )
    from ai_guardian.aiguardignore import generate_aiguardignore_preview

    rel_path = suggest_ignore_path(v.file_path)
    scanner_label = SCANNER_LABELS.get(v.config_section, v.config_section)

    with ui.dialog().props("persistent") as dlg, ui.card().classes("w-full max-w-xl"):
        ui.label(
            build_sub_dialog_title("Ignore File — .aiguardignore.toml", v)
        ).classes("text-lg font-bold")
        line_info = f":{v.line_number}" if v.line_number else ""
        if v.start_column is not None and v.line_number:
            line_info += f":{v.start_column + 1}"
        ui.label(f"File: {v.file_path}{line_info}").classes("text-sm text-grey-6")
        ui.separator()

        ui.label("Path pattern (editable):").classes("font-bold text-sm mt-2")
        path_input = (
            ui.input(value=rel_path)
            .props("dense outlined")
            .classes("w-full")
            .style("font-family: monospace")
        )
        path_status = ui.label("").classes("text-sm")

        ui.label("Scope:").classes("font-bold text-sm mt-2")
        scope_radio = ui.radio(
            {
                SCOPE_THIS_SCANNER: f"This scanner only ({scanner_label})",
                SCOPE_ALL_SCANNERS: "All scanners",
            },
            value=SCOPE_THIS_SCANNER,
        )

        ui.label("Preview:").classes("font-bold text-sm mt-2")
        preview_code = ui.code("").classes("w-full")

        def update_preview():
            path = path_input.value.strip()
            valid, msg = validate_ignore_path(path)
            if not valid:
                path_status.text = f"❌ {msg}"
                path_status.classes(replace="text-sm text-red")
                return
            path_status.text = f"✅ {msg}"
            path_status.classes(replace="text-sm text-green")
            scanner_types = resolve_scanner_types(
                scope_radio.value, v.config_section, None
            )
            try:
                toml_text, _ = generate_aiguardignore_preview(path, scanner_types)
                preview_code.set_content(toml_text)
            except Exception:
                pass  # intentionally silent — preview generation best-effort

        path_input.on_value_change(lambda _: update_preview())
        scope_radio.on_value_change(lambda _: update_preview())
        update_preview()

        with ui.row().classes("w-full justify-end mt-4"):
            ui.button("Cancel", on_click=dlg.close).props("flat")

            def on_confirm():
                path = path_input.value.strip()
                valid, msg = validate_ignore_path(path)
                if not valid:
                    path_status.text = f"❌ {msg}"
                    path_status.classes(replace="text-sm text-red")
                    return
                scanner_types = resolve_scanner_types(
                    scope_radio.value, v.config_section, None
                )
                dlg.close()

                toml_text, line_number = generate_aiguardignore_preview(
                    path, scanner_types
                )

                with (
                    ui.dialog().props("persistent maximized") as editor_dlg,
                    ui.card().classes("w-full h-full"),
                ):
                    ui.label(
                        build_sub_dialog_title("Config Editor — .aiguardignore.toml", v)
                    ).classes("text-lg font-bold")
                    ui.label("Review the file. Save to persist.").classes(
                        "text-sm text-grey-6"
                    )
                    ui.separator()

                    toml_editor = (
                        ui.codemirror(
                            toml_text,
                            theme="dracula",
                            line_wrapping=True,
                        )
                        .classes("w-full flex-grow")
                        .style("min-height: 400px")
                    )

                    editor_status = ui.label("").classes("text-sm")

                    with ui.row().classes("w-full justify-end mt-2"):
                        ui.button("Cancel", on_click=editor_dlg.close).props("flat")

                        def on_save():
                            if _write_aiguardignore_text(toml_editor.value):
                                dialog_self._result = AskResult(
                                    decision=AskDecision.IGNORE_FILE,
                                    ignore_path=path,
                                    ignore_scanner_types=scanner_types,
                                    config_saved=True,
                                )
                                ui.run_javascript("window.close()")
                                app.shutdown()
                            else:
                                editor_status.text = (
                                    "Failed to write .aiguardignore.toml"
                                )
                                editor_status.classes(replace="text-sm text-red")

                        ui.button("Save", on_click=on_save).props(
                            f"color={quasar_button('save')}"
                        )

                editor_dlg.open()

            ui.button("Add to .aiguardignore.toml", on_click=on_confirm).props(
                f"color={quasar_button('save')}"
            )

    dlg.open()


class _NiceGuiAskDialog:
    """Browser-based ask dialog using NiceGUI."""

    def __init__(self, violation: AskViolationInfo, timeout_seconds: int = 300):
        self._violation = violation
        self._timeout = timeout_seconds
        self._result = AskResult(decision=AskDecision.BLOCK)

    def run(self) -> AskResult:
        from nicegui import ui, app

        port = self._find_free_port()
        v = self._violation
        dialog_self = self

        @ui.page("/")
        def main_page():
            from ai_guardian.tui.pattern_editor import (
                validate_pattern,
                generate_config_preview,
                suggest_pattern,
                get_pattern_type_for_section,
                PATTERN_TYPES,
            )

            ptype = get_pattern_type_for_section(v.config_section)
            ptype_label = PATTERN_TYPES.get(ptype, ptype)

            with ui.card().classes("w-full max-w-2xl mx-auto mt-8"):
                icon, badge_color = violation_badge(v.violation_type)
                with ui.row().classes("items-center"):
                    ui.label(icon).classes("text-2xl")
                    ui.label(build_dialog_title(v)).classes("text-xl font-bold")
                    if v.total_findings and v.total_findings > 1:
                        remaining = v.total_findings - (v.finding_index or 0) - 1
                        counter = f"{v.finding_index + 1} of {v.total_findings}"
                        if remaining > 0:
                            counter += f" ({remaining} more)"
                        ui.badge(counter, color="info").classes("ml-2")
                ui.separator()

                with ui.card_section():
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f"Type: {icon} {v.violation_type}").classes("text-sm")
                        ui.badge(
                            v.violation_type, color=quasar_color(badge_color)
                        ).classes("text-xs")
                    if v.hook_event:
                        ui.label(f"Hook: {v.hook_event}").classes("text-sm")
                    ui.label(f"Summary: {v.summary}").classes("text-sm")
                    if v.file_path:
                        loc = v.file_path
                        if v.line_number:
                            loc += f":{v.line_number}"
                            if v.start_column is not None:
                                loc += f":{v.start_column + 1}"
                        ui.label(f"Location: {loc}").classes("text-sm")

                with ui.card_section():
                    ui.label("Matched Text").classes("font-bold")
                    ui.code(v.matched_text[:500]).classes("w-full")

                with ui.row().classes("w-full justify-between mt-4"):

                    def decide(decision):
                        dialog_self._result = AskResult(decision=decision)
                        ui.run_javascript("window.close()")
                        app.shutdown()

                    ui.button(
                        "Allow Once", on_click=lambda: decide(AskDecision.ALLOW_ONCE)
                    ).props(f"color={quasar_button('allow_once')}")

                    def show_editor():
                        with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl"):
                            ui.label(
                                build_sub_dialog_title("Allow Always — Edit Pattern", v)
                            ).classes("text-lg font-bold")
                            if v.file_path:
                                line_info = f":{v.line_number}" if v.line_number else ""
                                if v.start_column is not None and v.line_number:
                                    line_info += f":{v.start_column + 1}"
                                ui.label(f"File: {v.file_path}{line_info}").classes(
                                    "text-sm text-grey-6"
                                )
                            ui.separator()

                            ui.label("Matched text (reference):").classes(
                                "font-bold text-sm"
                            )
                            ui.code(v.matched_text[:200]).classes("w-full")

                            ui.label(f"Pattern ({ptype_label}):").classes(
                                "font-bold text-sm mt-2"
                            )
                            pattern_input = (
                                ui.input(
                                    value=(
                                        suggest_pattern(
                                            v.matched_text, v.config_section
                                        )
                                        if v.matched_text
                                        else ""
                                    ),
                                )
                                .props("dense outlined")
                                .classes("w-full")
                                .style("font-family: monospace")
                            )

                            status_label = ui.label("").classes("text-sm")
                            preview_code = ui.code("").classes("w-full")

                            def do_test():
                                pat = pattern_input.value.strip()
                                valid, msg = validate_pattern(
                                    pat, ptype, v.matched_text
                                )
                                if valid:
                                    status_label.text = f"✅ PASS: {msg}"
                                    status_label.classes(replace="text-sm text-green")
                                    preview_code.set_content(
                                        generate_config_preview(pat, v.config_section)
                                    )
                                else:
                                    status_label.text = f"❌ FAIL: {msg}"
                                    status_label.classes(replace="text-sm text-red")

                            ui.button(
                                "Test Pattern", on_click=do_test, icon="play_arrow"
                            ).props("dense")
                            do_test()
                            pattern_input.on_value_change(lambda _: do_test())

                            with ui.row().classes("w-full justify-end mt-4"):
                                ui.button("Cancel", on_click=dlg.close).props("flat")

                                def on_confirm():
                                    pat = pattern_input.value.strip()
                                    valid, _ = validate_pattern(
                                        pat, ptype, v.matched_text
                                    )
                                    if not valid:
                                        status_label.text = (
                                            "❌ FAIL: Fix the pattern before confirming"
                                        )
                                        status_label.classes(replace="text-sm text-red")
                                        return
                                    dlg.close()
                                    _show_nicegui_config_editor(
                                        dialog_self, app, pat, v.config_section
                                    )

                                ui.button(
                                    "Add to Allowlist", on_click=on_confirm
                                ).props(f"color={quasar_button('save')}")

                        dlg.open()

                    ui.button("Allow Always...", on_click=show_editor).props(
                        f"color={quasar_button('allow_always')}"
                    )

                    if v.file_path:

                        def view_file():
                            from ai_guardian.tui.file_opener import open_in_editor

                            open_in_editor(v.file_path, v.line_number)

                        ui.button("View File", on_click=view_file).props(
                            f"color={quasar_button('view_file')}"
                        )

                        from ai_guardian.tui.source_annotator import get_comment_prefix

                        if get_comment_prefix(v.file_path) is not None:

                            def show_suppress_source():
                                _show_nicegui_suppress_in_source(dialog_self, app, v)

                            ui.button(
                                "Suppress in Source...", on_click=show_suppress_source
                            ).props(f"color={quasar_button('suppress_in_source')}")

                        def show_ignore_file():
                            _show_nicegui_ignore_file(dialog_self, app, v)

                        ui.button("Ignore File...", on_click=show_ignore_file).props(
                            f"color={quasar_button('ignore_file')}"
                        )

                    ui.button(
                        "Block", on_click=lambda: decide(AskDecision.BLOCK)
                    ).props(f"color={quasar_button('block')}")
                    if v.total_findings and v.total_findings > 1:
                        ui.button(
                            "Block All", on_click=lambda: decide(AskDecision.BLOCK_ALL)
                        ).props(f"color={quasar_button('block')}")

            # Auto-dismiss: block after timeout if user doesn't respond
            if dialog_self._timeout > 0:

                def _auto_block():
                    if dialog_self._result is None:
                        dialog_self._result = AskResult(decision=AskDecision.BLOCK)
                    app.shutdown()

                ui.timer(dialog_self._timeout, _auto_block, once=True)

        import subprocess as _sp

        front_app = None
        if platform.system() == "Darwin":
            try:
                front_app = _sp.run(
                    [
                        "osascript",
                        "-e",
                        'tell application "System Events" to get name of first application process whose frontmost is true',
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                ).stdout.strip()
            except Exception:
                pass  # intentionally silent — best-effort operation

        # show=True: NiceGUI opens the browser after the server is ready,
        # avoiding the race condition from webbrowser.open() before ui.run().
        ui.run(
            port=port, show=True, reload=False, dark=True, title=build_dialog_title(v)
        )

        if front_app and platform.system() == "Darwin":
            try:
                _sp.run(
                    ["osascript", "-e", f'tell application "{front_app}" to activate'],
                    capture_output=True,
                    timeout=3,
                )
            except Exception:
                pass  # intentionally silent — best-effort operation

        return self._result

    @staticmethod
    def _find_free_port():
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]
