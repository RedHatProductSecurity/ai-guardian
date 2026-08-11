"""Directory Scan page — scan with Allow Always and bulk allowlisting."""

import threading
from collections import defaultdict
from pathlib import Path

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar


def _open_browse_dialog(path_input):
    """Open a server-side directory browser dialog."""
    current = path_input.value.strip() or "."
    try:
        browse_path = Path(current).resolve()
        if not browse_path.is_dir():
            browse_path = browse_path.parent
    except Exception:
        browse_path = Path.cwd()

    state = {"current": browse_path}

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("Browse Directory").classes("text-lg font-bold")
        current_label = (
            ui.label(str(state["current"]))
            .classes("text-xs text-grey-4")
            .style("font-family: monospace; word-break: break-all")
        )

        file_list = ui.column().classes("w-full")

        def refresh_listing():
            file_list.clear()
            p = state["current"]
            current_label.text = str(p)

            with file_list:
                if p.parent != p:
                    ui.button(
                        ".. (parent)",
                        icon="arrow_upward",
                        on_click=lambda: go_to(p.parent),
                    ).props("dense flat no-caps align=left").classes("w-full")

                try:
                    entries = sorted(
                        p.iterdir(),
                        key=lambda e: (not e.is_dir(), e.name.lower()),
                    )
                except PermissionError:
                    ui.label("Permission denied").classes("text-red text-sm")
                    return

                dirs_shown = 0
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    if entry.is_dir():
                        dirs_shown += 1
                        if dirs_shown > 50:
                            ui.label("... and more directories").classes(
                                "text-xs text-grey-6"
                            )
                            break
                        ui.button(
                            entry.name,
                            icon="folder",
                            on_click=lambda e=entry: go_to(e),
                        ).props("dense flat no-caps align=left").classes("w-full")

        def go_to(new_path):
            state["current"] = new_path.resolve()
            refresh_listing()

        with ui.scroll_area().classes("w-full").style("height: 350px"):
            refresh_listing()

        with ui.row().classes("w-full justify-end mt-2"):
            ui.button("Cancel", on_click=dlg.close).props("flat")

            def on_select():
                path_input.value = str(state["current"])
                dlg.close()

            ui.button(
                "Select",
                on_click=on_select,
            ).props("color=positive")

    dlg.open()


def _format_severity(severity):
    from ai_guardian.theme import quasar_severity

    return quasar_severity((severity or "").lower())


from ai_guardian.constants import RULE_ID_LABELS, RULE_ID_TO_VIOLATION_TYPE

MAX_FINDINGS_DISPLAY = 200


def _finding_to_violation(finding):
    """Convert a scanner finding dict to a violation-like dict for rendering."""
    rule_id = finding.get("rule_id", "")
    vtype = RULE_ID_TO_VIOLATION_TYPE.get(rule_id, "unknown")
    details = finding.get("details", {})
    if not isinstance(details, dict):
        details = {}

    blocked = dict(details)
    blocked["file_path"] = finding.get("file_path", "")
    blocked["line_number"] = finding.get("line_number")
    if finding.get("snippet"):
        blocked["matched_text"] = finding["snippet"]
        blocked.setdefault("tool_value", finding["snippet"])
    if vtype in ("prompt_injection", "context_poisoning", "supply_chain"):
        blocked.setdefault("pattern", blocked.get("description", ""))
    if vtype == "ssrf_blocked":
        blocked.setdefault("tool_value", blocked.get("url", ""))

    return {
        "violation_type": vtype,
        "severity": finding.get("severity", "warning"),
        "timestamp": "",
        "blocked": blocked,
        "suggestion": {},
        "context": {},
        "message": finding.get("message", ""),
        "_config_section": finding.get("config_section"),
        "_snippet": finding.get("snippet", ""),
    }


def _group_findings(findings):
    """Group findings by rule_id, returning {rule_id: [findings]}."""
    groups = defaultdict(list)
    for f in findings:
        groups[f.get("rule_id", "unknown")].append(f)
    return dict(groups)


def create_directory_scan_page(service, daemon_name: str):
    """Create the Directory Scan page with Allow Always support."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/directory-scan")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Directory Scan").classes("text-2xl font-bold")
        ui.label(
            "Scan directories for security issues. "
            "Use Allow Always to add allowlist patterns."
        ).classes("text-xs text-grey-6")

        with ui.card().classes("w-full"):
            ui.label("Scan Configuration").classes("text-lg font-bold")
            with ui.row().classes("items-center gap-2 w-full"):
                path_input = (
                    ui.input(
                        label="File or Directory Path",
                        value=str(Path.home()),
                    )
                    .props("dense outlined")
                    .classes("flex-grow")
                    .style("font-family: monospace")
                )
                ui.button(
                    icon="folder_open",
                    on_click=lambda: _open_browse_dialog(path_input),
                ).props("dense flat")

            with ui.row().classes("items-center gap-4"):
                recursive_check = ui.checkbox("Recursive", value=True)
                config_only_check = ui.checkbox("Config files only", value=False)
                skip_hidden_check = ui.checkbox(
                    "Skip hidden directories (starting with .)",
                    value=True,
                )

        results_container = ui.column().classes("w-full gap-4")

        all_findings = []
        cancel_event = threading.Event()

        with ui.row().classes("items-center gap-2"):
            scan_btn = ui.button(
                "Scan",
                icon="search",
            ).props("dense")
            stop_btn = ui.button(
                "Stop",
                icon="stop",
            ).props("dense color=negative")
            stop_btn.set_visibility(False)

        progress_state = {"file": "", "index": 0, "total": 0}

        async def do_scan():
            path = path_input.value.strip()
            if not path:
                ui.notify("Enter a path to scan", type="negative")
                return

            cancel_event.clear()
            scan_btn.disable()
            stop_btn.set_visibility(True)
            results_container.clear()
            with results_container:
                with ui.column().classes("w-full gap-2 py-4"):
                    with ui.row().classes("items-center gap-4"):
                        ui.spinner("dots", size="lg")
                        progress_label = ui.label(f"Scanning {path}...").classes(
                            "text-grey-4"
                        )
                    progress_bar = ui.linear_progress(
                        value=0, show_value=False
                    ).classes("w-full")
                    progress_file = (
                        ui.label("")
                        .classes("text-xs text-grey-6")
                        .style(
                            "font-family: monospace; "
                            "max-width: 500px; "
                            "overflow: hidden; "
                            "text-overflow: ellipsis; "
                            "white-space: nowrap"
                        )
                    )

            def update_progress():
                if progress_state["total"] > 0:
                    progress_label.text = (
                        f"Scanning... "
                        f"{progress_state['index']}"
                        f"/{progress_state['total']} files"
                    )
                    progress_bar.value = (
                        progress_state["index"] / progress_state["total"]
                    )
                    progress_file.text = progress_state["file"]

            progress_timer = ui.timer(
                0.2,
                update_progress,
            )

            try:
                await run.io_bound(service.refresh_targets)
                target = service.get_target_by_name(daemon_name)

                if target and target.runtime != "local":
                    result = await run.io_bound(service.scan_path, target, path)
                else:
                    result = await run.io_bound(
                        _local_scan_with_progress,
                        path,
                        recursive_check.value,
                        config_only_check.value,
                        progress_state,
                        cancel_event,
                        skip_hidden_check.value,
                    )

                progress_timer.deactivate()

                if result is None:
                    results_container.clear()
                    with results_container:
                        ui.label(
                            "Scan failed — check the path and " "daemon status."
                        ).classes("text-red")
                    return

                findings = result.get("findings", [])
                elapsed_ms = result.get("scan_time_ms", 0)
                cancelled = result.get("cancelled", False)
                all_findings.clear()
                all_findings.extend(findings)

                _render_results(
                    results_container,
                    findings,
                    elapsed_ms,
                    daemon_name,
                    incomplete=cancelled,
                    service=service,
                )
            except Exception as exc:
                progress_timer.deactivate()
                results_container.clear()
                with results_container:
                    ui.label(f"Scan error: {exc}").classes("text-red")
            finally:
                scan_btn.enable()
                stop_btn.set_visibility(False)

        def do_stop():
            cancel_event.set()

        scan_btn.on_click(do_scan)
        stop_btn.on_click(do_stop)


def _local_scan_with_progress(
    path,
    recursive,
    config_only,
    progress_state,
    cancel_event=None,
    skip_hidden=True,
):
    """Local scan with progress updates and cancellation support."""
    import time
    from pathlib import Path as P
    from ai_guardian.scanners.file_scanner import FileScanner
    from ai_guardian.tui.pattern_editor import config_section_for_rule_id
    from ai_guardian.web.config_helpers import load_web_config

    def on_progress(file_path, index, total):
        progress_state["file"] = file_path
        progress_state["index"] = index
        progress_state["total"] = total

    config = load_web_config()
    scanner = FileScanner(config)
    start = time.monotonic()

    if not recursive and P(path).is_dir():
        findings = []
        for f in sorted(P(path).resolve().iterdir()):
            if cancel_event and cancel_event.is_set():
                break
            if f.is_file():
                findings.extend(
                    scanner.scan_directory(
                        str(f),
                        config_only=config_only,
                        progress_callback=on_progress,
                        cancel_event=cancel_event,
                        skip_hidden=skip_hidden,
                    )
                )
    else:
        findings = scanner.scan_directory(
            path,
            config_only=config_only,
            progress_callback=on_progress,
            cancel_event=cancel_event,
            skip_hidden=skip_hidden,
        )

    elapsed_ms = round((time.monotonic() - start) * 1000)
    cancelled = cancel_event.is_set() if cancel_event else False

    base = P(path).resolve()
    if base.is_file():
        base = base.parent
    for f in findings:
        f["config_section"] = config_section_for_rule_id(f.get("rule_id", ""))
        fp = f.get("file_path", "")
        if fp and not P(fp).is_absolute():
            f["file_path"] = str(base / fp)

    return {
        "findings": findings,
        "scanned_files": progress_state.get("total", len(findings)),
        "scan_time_ms": elapsed_ms,
        "cancelled": cancelled,
    }


def _render_results(
    container,
    findings,
    elapsed_ms,
    daemon_name,
    incomplete=False,
    service=None,
):
    """Render scan results using the same cards as the violations page."""
    from ai_guardian.web.pages.violations import _render_violation_card

    container.clear()

    with container:
        count = len(findings)

        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-4"):
                ui.label("Results").classes("text-lg font-bold")
                ui.label(f"Findings: {count}").classes("text-sm font-bold")
                ui.label(f"Elapsed: {elapsed_ms}ms").classes("text-xs text-grey-6")
                if incomplete:
                    ui.badge(
                        "SCAN INCOMPLETE — stopped by user",
                        color="amber",
                    ).classes("text-xs")

        if not findings:
            ui.label("No issues found.").classes("text-grey-6 text-sm")
            return

        truncated = count > MAX_FINDINGS_DISPLAY
        display = findings[:MAX_FINDINGS_DISPLAY]
        groups = _group_findings(display)

        for rule_id, group_findings in sorted(groups.items()):
            label = RULE_ID_LABELS.get(rule_id, rule_id)
            config_section = group_findings[0].get("config_section")

            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.label(f"{label} ({len(group_findings)})").classes(
                        "text-base font-bold"
                    )

                    if config_section:
                        ui.button(
                            "Allow All of Type",
                            icon="playlist_add_check",
                            on_click=lambda cs=config_section, gf=group_findings: _show_allow_all_dialog(
                                cs, gf
                            ),
                        ).props("dense flat color=positive size=sm")

                        has_files = any(f.get("file_path") for f in group_findings)
                        if has_files:
                            ui.button(
                                "Ignore All Files",
                                icon="block",
                                on_click=lambda cs=config_section, gf=group_findings: _show_ignore_all_files_dialog(
                                    cs, gf
                                ),
                            ).props("dense flat color=warning size=sm")

                ui.separator()

                for f in group_findings:
                    v = _finding_to_violation(f)
                    _render_violation_card(
                        v,
                        service=service,
                        daemon_name=daemon_name,
                    )

        if truncated:
            ui.label(f"Showing {MAX_FINDINGS_DISPLAY} of {count} findings.").classes(
                "text-xs text-amber mt-2"
            )


def _show_allow_all_dialog(config_section, findings):
    """Bulk Allow All of Type — show matched texts and suggest pattern."""
    from ai_guardian.tui.pattern_editor import (
        validate_pattern,
        generate_config_preview,
        suggest_pattern,
        get_pattern_type_for_section,
        PATTERN_TYPES,
    )

    ptype = get_pattern_type_for_section(config_section)
    ptype_label = PATTERN_TYPES.get(ptype, ptype)
    snippets = [f.get("snippet", "") for f in findings if f.get("snippet")]

    first_snippet = snippets[0] if snippets else ""
    suggested = suggest_pattern(first_snippet, config_section) if first_snippet else ""

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl"):
        ui.label(f"Allow All of Type — {len(findings)} findings").classes(
            "text-lg font-bold"
        )
        ui.separator()

        ui.label(f"Matched texts ({len(snippets)} unique):").classes(
            "font-bold text-sm"
        )
        with ui.scroll_area().classes("w-full").style("max-height: 150px"):
            for s in snippets[:20]:
                ui.label(s[:200]).classes("text-xs").style("font-family: monospace")
            if len(snippets) > 20:
                ui.label(f"... and {len(snippets) - 20} more").classes(
                    "text-xs text-grey-6"
                )

        ui.label(f"Pattern ({ptype_label}):").classes("font-bold text-sm mt-2")
        pattern_input = (
            ui.input(
                value=suggested,
            )
            .props("dense outlined")
            .classes("w-full")
            .style("font-family: monospace")
        )

        status_label = ui.label("").classes("text-sm")
        preview_code = ui.code("").classes("w-full")

        def do_test():
            pat = pattern_input.value.strip()
            valid, msg = validate_pattern(pat, ptype, first_snippet)
            if valid:
                status_label.text = f"PASS: {msg}"
                status_label.classes(replace="text-sm text-green")
                preview_code.set_content(generate_config_preview(pat, config_section))
            else:
                status_label.text = f"FAIL: {msg}"
                status_label.classes(replace="text-sm text-red")

        ui.button(
            "Test Pattern",
            on_click=do_test,
            icon="play_arrow",
        ).props("dense")
        do_test()
        pattern_input.on_value_change(lambda _: do_test())

        with ui.row().classes("w-full justify-end mt-4"):
            ui.button("Cancel", on_click=dlg.close).props("flat")

            def on_confirm():
                pat = pattern_input.value.strip()
                valid, _ = validate_pattern(pat, ptype, first_snippet)
                if not valid:
                    status_label.text = "FAIL: Fix the pattern before confirming"
                    status_label.classes(replace="text-sm text-red")
                    return
                dlg.close()
                from ai_guardian.web.pages.violations import (
                    _show_config_editor_dialog,
                )

                _show_config_editor_dialog(pat, config_section)

            ui.button(
                "Add to Allowlist",
                on_click=on_confirm,
            ).props("color=positive")

    dlg.open()


def _show_ignore_all_files_dialog(config_section, findings):
    """Bulk Ignore All Files of Type — add to .aiguardignore.toml."""
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
    from ai_guardian.tui.ask_dialog import _write_aiguardignore_text

    file_paths = list(
        set(f.get("file_path", "") for f in findings if f.get("file_path"))
    )
    if not file_paths:
        ui.notify("No file paths in these findings", type="warning")
        return

    first_path = file_paths[0]
    rel_path = suggest_ignore_path(first_path)
    scanner_label = SCANNER_LABELS.get(config_section, config_section)

    with (
        ui.dialog().props("persistent") as ignore_dlg,
        ui.card().classes("w-full max-w-xl"),
    ):
        ui.label(f"Ignore Files — {len(file_paths)} files").classes("text-lg font-bold")
        ui.separator()

        if len(file_paths) > 1:
            ui.label(
                f"Files: {', '.join(suggest_ignore_path(p) for p in file_paths[:5])}"
            ).classes("text-xs text-grey-6")

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
                scope_radio.value, config_section, None
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
            ui.button("Cancel", on_click=ignore_dlg.close).props("flat")

            def on_confirm():
                path = path_input.value.strip()
                valid, msg = validate_ignore_path(path)
                if not valid:
                    path_status.text = f"❌ {msg}"
                    path_status.classes(replace="text-sm text-red")
                    return
                scanner_types = resolve_scanner_types(
                    scope_radio.value, config_section, None
                )
                ignore_dlg.close()

                toml_text, _ln = generate_aiguardignore_preview(path, scanner_types)
                with (
                    ui.dialog().props("persistent maximized") as editor_dlg,
                    ui.card().classes("w-full h-full"),
                ):
                    ui.label("Config Editor — .aiguardignore.toml").classes(
                        "text-lg font-bold"
                    )
                    ui.separator()
                    toml_editor = (
                        ui.codemirror(toml_text, theme="dracula", line_wrapping=True)
                        .classes("w-full flex-grow")
                        .style("min-height: 400px")
                    )
                    editor_status = ui.label("").classes("text-sm")
                    with ui.row().classes("w-full justify-end mt-2"):
                        ui.button("Cancel", on_click=editor_dlg.close).props("flat")

                        def on_save():
                            if _write_aiguardignore_text(toml_editor.value):
                                ui.notify(
                                    "Path saved to .aiguardignore.toml", type="positive"
                                )
                                editor_dlg.close()
                            else:
                                editor_status.text = (
                                    "Failed to write .aiguardignore.toml"
                                )
                                editor_status.classes(replace="text-sm text-red")

                        ui.button("Save", on_click=on_save).props("color=positive")
                editor_dlg.open()

            ui.button("Add to .aiguardignore.toml", on_click=on_confirm).props(
                "color=positive"
            )

    ignore_dlg.open()
