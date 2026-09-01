"""Violations page — tabbed browser with details/correlation matching TUI."""

import json
from collections import Counter

from nicegui import run, ui

from ai_guardian.web.components.local_time import (
    inject_local_time_js,
    local_time_label,
)

from ai_guardian.constants import HookEvent, VIOLATION_FILTER_TYPES
from ai_guardian.violations.guidance import get_resolution_instructions
from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.violations.utils import is_temp_path

FILTER_TABS = [("All", None, "Show all violation types")] + list(VIOLATION_FILTER_TYPES)

DETAIL_FIELDS = {
    "tool_permission": [
        ("Tool", "tool_name"),
        ("File", "tool_value"),
        ("File Path", "file_path"),
        ("Line", "line_number"),
        ("Column", "start_column"),
        ("Position", "position"),
        ("Reason", "reason"),
    ],
    "secret_detected": [
        ("File", "file_path"),
        ("Source Command", "source_command"),
        ("Source", "source"),
        ("Line", "line_number"),
        ("Column", "start_column"),
        ("End Line", "end_line"),
        ("Position", "position"),
        ("Type", "secret_type"),
        ("Findings", "total_findings"),
    ],
    "prompt_injection": [
        ("Source", "source"),
        ("File", "file_path"),
        ("Line", "line_number"),
        ("Column", "start_column"),
        ("Position", "position"),
        ("Pattern", "pattern"),
        ("Matched", "matched_text"),
        ("Method", "method"),
        ("Confidence", "confidence"),
    ],
    "secret_redaction": [
        ("Tool", "tool"),
        ("Source Command", "source_command"),
        ("Command", "command"),
        ("File", "file_path"),
        ("Line", "line_number"),
        ("Column", "start_column"),
        ("Count", "redaction_count"),
        ("Types", "redacted_types"),
    ],
    "pii_detected": [
        ("Hook", "hook"),
        ("Tool", "tool"),
        ("Source Command", "source_command"),
        ("Command", "command"),
        ("File", "file_path"),
        ("Line", "line_number"),
        ("Column", "start_column"),
        ("Count", "pii_count"),
        ("Types", "pii_types"),
    ],
    "jailbreak_detected": [
        ("File", "file_path"),
        ("Line", "line_number"),
        ("Column", "start_column"),
        ("Tool", "tool"),
        ("Matched", "matched_text"),
        ("Confidence", "confidence"),
    ],
    "ssrf_blocked": [
        ("Tool", "tool_name"),
        ("URL", "tool_value"),
        ("File", "file_path"),
        ("Line", "line_number"),
        ("Column", "start_column"),
        ("Reason", "reason"),
    ],
    "config_file_exfil": [
        ("File", "file_path"),
        ("Reason", "reason"),
        ("Details", "details"),
    ],
    "directory_blocking": [
        ("File", "file_path"),
        ("Directory", "denied_directory"),
    ],
    "secret_in_transcript": [
        ("File", "file_path"),
        ("Line", "line_number"),
        ("Column", "start_column"),
        ("Type", "secret_type"),
        ("Source", "source"),
    ],
    "pii_in_transcript": [
        ("File", "file_path"),
        ("Line", "line_number"),
        ("Column", "start_column"),
        ("Count", "pii_count"),
        ("Types", "pii_types"),
    ],
    "image_secret_detected": [
        ("File", "file_path"),
        ("Type", "secret_type"),
        ("Source", "source"),
    ],
    "image_pii_detected": [
        ("File", "file_path"),
        ("Count", "pii_count"),
        ("Types", "pii_types"),
    ],
    "code_security": [
        ("File", "file_path"),
        ("Rule", "rule_id"),
        ("Line", "line_number"),
        ("Severity", "severity"),
        ("Reason", "reason"),
    ],
    "offensive_language": [
        ("File", "file_path"),
        ("Rule", "rule_id"),
        ("Category", "category"),
        ("Line", "line_number"),
        ("Matched", "matched_text"),
        ("Suggestion", "suggestion"),
    ],
    "canary_detected": [
        ("File", "file_path"),
        ("Token", "token"),
        ("Description", "description"),
        ("Line", "line_number"),
        ("Matched", "matched_text"),
    ],
    "exfil_detection": [
        ("Command", "command"),
        ("Category", "category"),
        ("Pattern", "pattern"),
        ("Line", "line_number"),
        ("Matched", "matched_text"),
    ],
}


def _get_resolution_instructions(violation: dict):
    return get_resolution_instructions(violation)


def _format_violation_markdown(v: dict) -> str:
    """Format a violation dict as readable Markdown for clipboard sharing."""
    vtype = v.get("violation_type", v.get("type", "unknown"))
    severity = v.get("severity", "warning")
    timestamp = v.get("timestamp", "")
    blocked = v.get("blocked", {})
    if not isinstance(blocked, dict):
        blocked = {}

    lines = [f"**Type:** {vtype}"]
    lines.append(f"**Severity:** {severity}")

    fields = DETAIL_FIELDS.get(vtype, [])
    for label, key in fields:
        val = blocked.get(key)
        if val is not None:
            if key == "secret_type":
                from ai_guardian.scanners.secret_types import get_secret_type_display

                val = get_secret_type_display(str(val))
            if isinstance(val, list):
                val = ", ".join(str(x) for x in val)
            lines.append(f"**{label}:** {val}")

    if timestamp:
        lines.append(f"**Time:** {timestamp}")

    suggestion = v.get("suggestion", {})
    if isinstance(suggestion, dict) and suggestion.get("rule"):
        lines.append(
            f"**Suggested Rule:**\n```json\n"
            f"{json.dumps(suggestion['rule'], indent=2)}\n```"
        )

    return "\n".join(lines)


def _load_local_violations(limit, violation_type):
    from ai_guardian.violations.logger import ViolationLogger

    vl = ViolationLogger()
    return vl.get_recent_violations(
        limit=limit, violation_type=violation_type, resolved=None
    )


def _violation_matches_dir(v: dict, dir_prefix: str) -> bool:
    """Return True if violation's file_path is under dir_prefix."""
    if not dir_prefix:
        return True
    blocked = v.get("blocked", {})
    if not isinstance(blocked, dict):
        return False
    file_path = blocked.get("file_path", "")
    if not file_path:
        return False
    norm = dir_prefix.rstrip("/")
    return file_path.startswith(norm + "/") or file_path == norm


def create_violations_page(service, daemon_name: str):
    """Build the violations page with filter tabs and detail modals."""

    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/violations")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-2"):
        ui.label("Violations").classes("text-2xl font-bold")
        ui.label(
            "Historical log of blocked operations. "
            "Click Details for resolution instructions."
        ).classes("text-xs text-grey-6")

        active_filter = {"vtype": None}
        active_dir_filter = {"dir": None}
        cached_violations: list = []

        filter_options = {label: vtype for label, vtype, _ in FILTER_TABS}

        with ui.row().classes("items-end gap-2 flex-wrap"):
            filter_select = ui.select(
                options=["All"],
                value="All",
                label="Filter by type",
            ).classes("w-64")

            dir_select = (
                ui.select(
                    options={"": "All Directories"},
                    value="",
                    label="Filter by directory",
                    with_input=True,
                    new_value_mode="add-unique",
                )
                .props("clearable")
                .classes("w-80")
            )

            def open_browse_dialog():
                from ai_guardian.web.pages.directory_scan import _open_browse_dialog

                proxy = ui.input(value=active_dir_filter["dir"] or "").style(
                    "display:none"
                )

                async def _on_path_selected(e):
                    path = (e.value or "").strip()
                    active_dir_filter["dir"] = path or None
                    opts = dict(dir_select.options)
                    if path and path not in opts:
                        opts[path] = path
                        dir_select.options = opts
                    dir_select.value = path
                    dir_select.update()
                    await load_violations()

                proxy.on_value_change(_on_path_selected)
                _open_browse_dialog(proxy)

            ui.button(
                "Browse...",
                icon="folder_open",
                on_click=open_browse_dialog,
            ).props("dense outline")

        async def on_filter_change(e):
            active_filter["vtype"] = filter_options.get(e.value)
            _render_filtered()

        filter_select.on_value_change(on_filter_change)

        async def on_dir_filter_change(e):
            val = e.value or ""
            active_dir_filter["dir"] = val.strip() if val else None
            _render_filtered()

        dir_select.on_value_change(on_dir_filter_change)

        async def _populate_dir_options():
            from ai_guardian.web.config_helpers import load_web_projects

            dirs = await run.io_bound(load_web_projects)
            opts = {"": "All Directories"}
            for d in dirs:
                opts[d] = d
            dir_select.options = opts
            dir_select.update()

        cards_container = ui.column().classes("w-full gap-1")

        def _update_filter_counts():
            type_counts = Counter(
                v.get("violation_type", "") for v in cached_violations
            )
            opts = {"All": f"All ({len(cached_violations)})"}
            for label, vt, _ in FILTER_TABS:
                if vt is not None:
                    opts[label] = f"{label} ({type_counts.get(vt, 0)})"
            sorted_opts = {"All": opts["All"]}
            for k in sorted(k for k in opts if k != "All"):
                sorted_opts[k] = opts[k]
            filter_select.options = sorted_opts
            filter_select.update()

        def _render_filtered():
            cards_container.clear()
            vtype = active_filter["vtype"]
            dir_filter = active_dir_filter["dir"]

            filtered = [
                v
                for v in cached_violations
                if (not vtype or v.get("violation_type") == vtype)
                and (not dir_filter or _violation_matches_dir(v, dir_filter))
            ]
            filtered.sort(key=lambda v: v.get("timestamp", ""), reverse=True)

            with cards_container:
                if not filtered:
                    ui.label("No violations found.").classes("text-grey-6 mt-4")
                    return
                ui.label(f"{len(filtered)} violations").classes("text-xs text-grey-6")
                for v in filtered:
                    _render_violation_card(v, service, daemon_name)

            inject_local_time_js()

        async def load_violations():
            await run.io_bound(service.refresh_targets)
            target = service.get_target_by_name(daemon_name)

            cached_violations.clear()
            if target:
                if target.runtime == "local":
                    raw = await run.io_bound(_load_local_violations, 500, None)
                else:
                    raw = await run.io_bound(
                        service.get_daemon_violations, target, 500, None
                    )
                if raw:
                    vlist = raw if isinstance(raw, list) else raw.get("violations", [])
                    cached_violations.extend(vlist)

            _update_filter_counts()
            _render_filtered()

        with ui.row().classes("gap-2"):
            ui.button(
                "Refresh",
                icon="refresh",
                on_click=load_violations,
            ).props("dense outline")
            ui.button(
                "Scan File/Directory",
                icon="search",
                on_click=lambda: ui.navigate.to(f"/{daemon_name}/directory-scan"),
            ).props("dense outline color=positive")

        ui.timer(0.15, _populate_dir_options, once=True)
        ui.timer(0.1, load_violations, once=True)


_ALLOWLIST_TYPES = frozenset(
    {
        "secret_detected",
        "pii_detected",
        "prompt_injection",
        "jailbreak_detected",
        "directory_blocking",
        "ssrf_blocked",
        "config_file_exfil",
        "context_poisoning",
        "supply_chain",
        "code_security",
        "offensive_language",
        "canary_detected",
        "exfil_detection",
        "tool_permission",
    }
)


def _render_violation_card(v: dict, service=None, daemon_name: str = ""):
    vtype = v.get("violation_type", v.get("type", "unknown"))
    severity = v.get("severity", "warning")
    timestamp = v.get("timestamp", "")
    daemon = v.get("_daemon", "")
    blocked = v.get("blocked", {})
    if not isinstance(blocked, dict):
        blocked = {}
    suggestion = v.get("suggestion", {})
    if not isinstance(suggestion, dict):
        suggestion = {}
    resolved = v.get("resolved", False)
    context = v.get("context", {})
    if not isinstance(context, dict):
        context = {}

    from ai_guardian.theme import quasar_severity, violation_badge

    sev_color = quasar_severity(severity)
    sev_icon = {"critical": "error", "high": "warning", "warning": "info"}.get(
        severity, "help"
    )
    v_icon, _ = violation_badge(vtype)

    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.icon(sev_icon).classes(f"text-{sev_color}")
            vtype_display = vtype.upper().replace("_", " ")
            ui.label(f"{v_icon} {vtype_display}").classes("font-bold text-sm")
            ui.badge(severity, color=sev_color).classes("text-xs")
            if resolved:
                ui.badge("RESOLVED", color="green").classes("text-xs")
            if daemon:
                ui.badge(daemon, color="blue-grey").classes("text-xs")
            local_time_label(timestamp).classes("ml-auto")

        fields = DETAIL_FIELDS.get(vtype, [])
        if fields:
            with ui.grid(columns=2).classes("gap-1 mt-1"):
                for label, key in fields:
                    val = blocked.get(key)
                    if val is not None:
                        ui.label(f"{label}:").classes("text-xs text-grey-6")
                        display = str(val)
                        if key == "secret_type":
                            from ai_guardian.scanners.secret_types import (
                                get_secret_type_display,
                            )

                            display = get_secret_type_display(display)
                        if key == "start_column" and isinstance(val, int):
                            display = str(val + 1)
                        if isinstance(val, list):
                            display = ", ".join(str(x) for x in val)
                        if isinstance(val, float):
                            display = f"{val:.2f}"
                        if len(display) > 100:
                            display = display[:97] + "..."
                        ui.label(display).classes("text-xs")

        if vtype == "tool_permission" and suggestion.get("rule"):
            ui.label("Suggested rule:").classes("text-xs text-grey-6 mt-1")
            ui.code(json.dumps(suggestion["rule"], indent=2), language="json").classes(
                "text-xs"
            )

        tool_use_id = context.get("tool_use_id")
        hook_event = context.get("hook_event", "")
        has_pretool = bool(context.get("pretool_context"))
        if tool_use_id and has_pretool:
            try:
                hook_label = HookEvent(hook_event).display_name
            except ValueError:
                hook_label = hook_event
            ui.label(f"Correlation: {tool_use_id[:16]}... ({hook_label})").classes(
                "text-xs text-grey-7 mt-1"
            )

        with ui.row().classes("gap-2 mt-1"):

            def show_details(violation=v):
                with ui.dialog() as dialog, ui.card().classes("w-[600px]"):
                    ui.label("Violation Details").classes("text-lg font-bold")
                    violation_json = json.dumps(
                        violation,
                        indent=2,
                        default=str,
                    )
                    ui.code(
                        violation_json,
                        language="json",
                    ).classes("max-h-[300px] overflow-auto text-xs")

                    with ui.row().classes("gap-2 mt-1"):
                        ui.button(
                            "Copy JSON",
                            icon="data_object",
                            on_click=lambda vj=violation_json: (
                                ui.run_javascript(
                                    f"navigator.clipboard.writeText({json.dumps(vj)})"
                                )
                            ),
                        ).props("flat dense size=sm")
                        violation_md = _format_violation_markdown(violation)
                        ui.button(
                            "Copy as Markdown",
                            icon="article",
                            on_click=lambda md=violation_md: (
                                ui.run_javascript(
                                    f"navigator.clipboard.writeText({json.dumps(md)})"
                                )
                            ),
                        ).props("flat dense size=sm")

                    ui.separator()
                    ui.label("How to Resolve").classes("font-bold mt-2")
                    instructions, snippet = _get_resolution_instructions(violation)
                    ui.label(instructions).classes("text-sm")
                    if snippet:
                        ui.code(snippet, language="json").classes("text-xs mt-1")
                        ui.button(
                            "Copy Config",
                            icon="content_copy",
                            on_click=lambda s=snippet: ui.run_javascript(
                                f"navigator.clipboard.writeText({json.dumps(s)})"
                            ),
                        ).props("flat dense size=sm")

                    v_id = violation.get("id")
                    if v_id:
                        detail_url = f"/{daemon_name}/violation-detail?id={v_id}"
                        ui.link(
                            "Open as page ↗",
                            detail_url,
                        ).classes("text-xs text-blue-4 mt-1")

                    with ui.row().classes("w-full justify-between mt-2"):
                        if vtype in _ALLOWLIST_TYPES and service is not None:

                            async def on_always_allow(
                                dlg=dialog,
                                viol=violation,
                                svc=service,
                                dname=daemon_name,
                            ):
                                await _show_allow_always_flow(
                                    dlg,
                                    viol,
                                    svc,
                                    dname,
                                )

                            ui.button(
                                "Always Allow...",
                                icon="check_circle",
                                on_click=on_always_allow,
                            ).props("color=positive dense size=sm")

                        blocked_data = violation.get("blocked", {})
                        v_file_path = (
                            blocked_data.get("file_path", "")
                            if isinstance(blocked_data, dict)
                            else ""
                        )
                        if v_file_path:
                            from ai_guardian.tui.source_annotator import (
                                get_comment_prefix,
                            )

                            v_line_number = (
                                blocked_data.get("line_number")
                                if isinstance(blocked_data, dict)
                                else None
                            )
                            if (
                                v_line_number
                                and get_comment_prefix(v_file_path) is not None
                                and not is_temp_path(v_file_path)
                            ):

                                def on_suppress_source(viol=violation):
                                    _show_suppress_in_source_flow(viol)

                                ui.button(
                                    "Suppress in Source...",
                                    icon="code",
                                    on_click=on_suppress_source,
                                ).props("color=warning dense size=sm")
                            elif v_line_number:
                                ui.label("Temp file — use config editor").classes(
                                    "text-xs text-grey-6"
                                )

                            def on_ignore_file(viol=violation):
                                _show_ignore_file_flow(viol)

                            ui.button(
                                "Ignore File...",
                                icon="block",
                                on_click=on_ignore_file,
                            ).props("color=warning dense size=sm")

                        ui.button("Close", on_click=dialog.close)
                dialog.open()

            ui.button(
                "Details",
                icon="info",
                on_click=show_details,
            ).props("flat dense size=sm")

            if has_pretool:

                def show_correlated(ctx=context, tid=tool_use_id):
                    pretool = ctx.get("pretool_context", {})
                    with ui.dialog() as dialog, ui.card().classes("w-[600px]"):
                        ui.label("Correlated PreToolUse Context").classes(
                            "text-lg font-bold"
                        )
                        ui.label(f"Correlation ID: {tid}").classes(
                            "text-xs text-grey-6"
                        )
                        ui.code(
                            json.dumps(pretool, indent=2, default=str),
                            language="json",
                        ).classes("max-h-[400px] overflow-auto text-xs")
                        ui.button("Close", on_click=dialog.close).classes("mt-2")
                    dialog.open()

                ui.button(
                    "Correlated",
                    icon="link",
                    on_click=show_correlated,
                ).props("flat dense size=sm")


async def _show_allow_always_flow(parent_dialog, violation, service, daemon_name):
    """Open pattern editor for allowlisting, rescanning file if needed."""
    blocked = violation.get("blocked", {})
    if not isinstance(blocked, dict):
        blocked = {}

    vtype = violation.get("violation_type", violation.get("type", ""))
    file_path = blocked.get("file_path") or ""
    line_number = blocked.get("line_number", 0)
    sub_type = blocked.get("secret_type", "")
    start_column = blocked.get("start_column")
    end_column = blocked.get("end_column")

    from ai_guardian.tui.pattern_editor import config_section_for_violation

    config_section = config_section_for_violation(vtype)
    if not config_section:
        ui.notify(f"No config section for type: {vtype}", type="warning")
        return

    matched_text = _extract_matched_from_violation(violation)

    if not matched_text and file_path:
        target = service.get_target_by_name(daemon_name)
        if not target:
            ui.notify("Daemon not available", type="negative")
            return

        try:
            result = await run.io_bound(
                lambda t=target, fp=file_path, ln=line_number, vt=vtype, st=sub_type, sc=start_column, ec=end_column: (
                    service.get_violation_context(
                        t,
                        fp,
                        ln,
                        vt,
                        st,
                        start_column=sc,
                        end_column=ec,
                    )
                ),
            )
        except TypeError:
            result = await run.io_bound(
                service.get_violation_context,
                target,
                file_path,
                line_number,
                vtype,
                sub_type,
            )

        if result is None:
            ui.notify("Failed to contact daemon", type="negative")
            return

        status = result.get("status", "")
        if status == "file_not_found":
            ui.notify(
                result.get("message", "File no longer exists"),
                type="warning",
            )
            return
        if status == "not_found":
            ui.notify(
                result.get("message", "Violation no longer present"),
                type="warning",
            )
            return
        if status == "found":
            matched_text = result.get("matched_text", "")

    if not matched_text:
        ui.notify("No matched text available for this violation", type="warning")
        return

    _show_pattern_editor_dialog(matched_text, config_section, file_path)


def _extract_matched_from_violation(violation: dict) -> str:
    """Extract matched text directly from violation data without rescanning.

    Returns the best available text for pattern editor pre-population.
    For file-based violations where no text is stored (e.g. secret_detected),
    returns "" so the caller falls through to a file rescan.
    """
    blocked = violation.get("blocked", {})
    if not isinstance(blocked, dict):
        blocked = {}
    vtype = violation.get("violation_type", "")

    if blocked.get("matched_text"):
        return str(blocked["matched_text"])

    if blocked.get("context_snippet"):
        return str(blocked["context_snippet"])

    if blocked.get("pattern_hint"):
        return str(blocked["pattern_hint"])

    if vtype == "tool_permission":
        tool = blocked.get("tool_name", "")
        value = blocked.get("tool_value", "")
        if tool and value:
            return f"{tool}:{value}"
        return tool or value or ""

    if vtype == "ssrf_blocked":
        url = blocked.get("tool_value", "") or blocked.get("url", "")
        if not url:
            reason = blocked.get("reason", "")
            import re

            m = re.search(r"https?://\S+", reason)
            if m:
                url = m.group(0)
        return url

    if vtype == "directory_blocking":
        return blocked.get("denied_directory", "") or blocked.get("file_path", "")

    if vtype in (
        "prompt_injection",
        "jailbreak_detected",
        "context_poisoning",
        "supply_chain",
    ):
        return blocked.get("pattern", "")

    if vtype == "code_security":
        return blocked.get("rule_id", "") or blocked.get("file_path", "")

    if vtype == "offensive_language":
        return blocked.get("matched_text", "") or blocked.get("rule_id", "")

    if vtype == "canary_detected":
        return blocked.get("matched_text", "") or blocked.get("token", "")

    if vtype == "exfil_detection":
        return blocked.get("matched_text", "") or blocked.get("pattern", "")

    if vtype == "pii_detected":
        pii_types = blocked.get("pii_types", [])
        if isinstance(pii_types, list) and pii_types:
            return ", ".join(str(t) for t in pii_types)
        return ""

    return ""


def _show_pattern_editor_dialog(
    matched_text: str, config_section: str, file_path: str = ""
):
    """Open inline pattern editor dialog for allowlisting."""
    from ai_guardian.tui.pattern_editor import (
        validate_pattern,
        generate_config_preview,
        suggest_pattern,
        get_pattern_type_for_section,
        PATTERN_TYPES,
    )

    ptype = get_pattern_type_for_section(config_section)
    ptype_label = PATTERN_TYPES.get(ptype, ptype)

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl"):
        ui.label("Allow Always — Edit Pattern").classes("text-lg font-bold")
        ui.separator()

        ui.label("Matched text (reference):").classes("font-bold text-sm")
        ui.code(matched_text[:500]).classes("w-full")

        ui.label(f"Pattern ({ptype_label}):").classes("font-bold text-sm mt-2")
        pattern_input = (
            ui.input(
                value=(
                    suggest_pattern(matched_text, config_section)
                    if matched_text
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
            valid, msg = validate_pattern(pat, ptype, matched_text)
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
                valid, _ = validate_pattern(pat, ptype, matched_text)
                if not valid:
                    status_label.text = "FAIL: Fix the pattern before confirming"
                    status_label.classes(replace="text-sm text-red")
                    return
                dlg.close()
                _show_config_editor_dialog(pat, config_section, file_path)

            ui.button(
                "Add to Allowlist",
                on_click=on_confirm,
            ).props("color=positive")

    dlg.open()


def _show_config_editor_dialog(save_pat: str, config_section: str, file_path: str = ""):
    """Show config editor with pattern inserted for review and save."""
    import json as json_mod
    from ai_guardian.tui.pattern_editor import (
        prepare_config_with_pattern,
        get_config_scope_options,
    )
    from ai_guardian.tui.ask_dialog import _write_config_text
    from ai_guardian.web.config_helpers import (
        _get_remote_project_dir,
        load_web_projects,
    )

    project_dir = _get_remote_project_dir()
    active_dirs = load_web_projects()

    if not project_dir and file_path and active_dirs:
        for d in active_dirs:
            if file_path.startswith(d.rstrip("/") + "/"):
                project_dir = d
                break

    scope_options = get_config_scope_options(
        project_dir=project_dir,
        active_project_dirs=active_dirs,
    )
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
        ui.label("Config Editor — ai-guardian.json").classes("text-lg font-bold")
        ui.label(
            "Review the config with the inserted pattern. "
            "Save to persist or Cancel to discard."
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
            ui.button("Cancel", on_click=editor_dlg.close).props("flat")

            def on_save():
                text = editor.value
                try:
                    json_mod.loads(text)
                except json_mod.JSONDecodeError as exc:
                    editor_status.text = f"Invalid JSON: {exc}"
                    editor_status.classes(replace="text-sm text-red")
                    return
                if _write_config_text(text, config_path_str=selected["path"]):
                    editor_dlg.close()
                    ui.notify(
                        "Pattern saved to config",
                        type="positive",
                    )
                else:
                    editor_status.text = "Failed to write config file"
                    editor_status.classes(replace="text-sm text-red")

            ui.button("Save", on_click=on_save).props("color=positive")

    editor_dlg.open()


def _show_suppress_in_source_flow(violation):
    """Show source annotation preview for a violation."""
    from nicegui import ui
    from ai_guardian.tui.source_annotator import (
        prepare_annotation,
        write_annotated_source,
    )

    blocked = violation.get("blocked", {})
    file_path = blocked.get("file_path", "") if isinstance(blocked, dict) else ""
    line_number = (
        (blocked.get("line_number", 1) or 1) if isinstance(blocked, dict) else 1
    )

    result = prepare_annotation(file_path, line_number)
    if result is None:
        ui.notify("Cannot annotate this file type", type="warning")
        return

    modified_content, highlight_line, annotation_type = result
    ann_label = (
        "inline" if annotation_type == "inline" else "block (begin-allow/end-allow)"
    )
    line_info = f" — Line {line_number}" if line_number > 1 else ""

    with (
        ui.dialog().props("persistent maximized") as dlg,
        ui.card().classes("w-full h-full"),
    ):
        ui.label(f"Suppress in Source — {ann_label}").classes("text-lg font-bold")
        ui.label(f"File: {file_path}{line_info}").classes("text-sm text-grey-6")
        ui.label("Review the annotated source. Save to write the file.").classes(
            "text-sm text-grey-6"
        )
        ui.separator()

        lang = None
        if file_path.endswith((".py", ".pyw", ".pyi")):
            lang = "Python"
        elif file_path.endswith((".js", ".mjs", ".cjs")):
            lang = "JavaScript"
        elif file_path.endswith((".ts", ".tsx")):
            lang = "TypeScript"
        elif file_path.endswith((".yml", ".yaml")):
            lang = "YAML"
        elif file_path.endswith(".json"):
            lang = "JSON"

        editor = (
            ui.codemirror(
                modified_content,
                language=lang,
                theme="dracula",
                line_wrapping=False,
            )
            .classes("w-full flex-grow")
            .style("min-height: 400px")
        )

        ui.add_css("""
            .cm-content .ai-guardian-annotation { color: #4EC9B0 !important; font-weight: bold; }
        """)

        async def _scroll_to_line():
            if highlight_line > 1:
                await ui.run_javascript(f"""
                    const editors = document.querySelectorAll('.cm-editor');
                    const cm = editors[editors.length - 1];
                    if (cm && cm.cmView && cm.cmView.view) {{
                        const view = cm.cmView.view;
                        const line = view.state.doc.line({highlight_line});
                        view.dispatch({{
                            selection: {{anchor: line.from}},
                            scrollIntoView: true,
                        }});
                    }}
                    """)

        ui.timer(0.5, _scroll_to_line, once=True)

        status = ui.label("").classes("text-sm")

        with ui.row().classes("w-full justify-end mt-2"):
            ui.button("Cancel", on_click=dlg.close).props("flat")

            def on_save():
                if write_annotated_source(file_path, editor.value):
                    ui.notify("Annotation saved to source file", type="positive")
                    dlg.close()
                else:
                    status.text = "Failed to write file"
                    status.classes(replace="text-sm text-red")

            ui.button("Save", on_click=on_save).props("color=positive")

    dlg.open()


def _show_ignore_file_flow(violation):
    """Show ignore file editor for a violation."""
    from nicegui import ui
    from ai_guardian.tui.ignore_file_editor import (
        SCOPE_THIS_SCANNER,
        SCOPE_ALL_SCANNERS,
        SCANNER_LABELS,
        resolve_scanner_types,
        validate_ignore_path,
        suggest_ignore_path,
    )
    from ai_guardian.tui.pattern_editor import config_section_for_violation
    from ai_guardian.aiguardignore import generate_aiguardignore_preview
    from ai_guardian.tui.ask_dialog import _write_aiguardignore_text

    blocked = violation.get("blocked", {})
    file_path = blocked.get("file_path", "") if isinstance(blocked, dict) else ""
    vtype = violation.get("violation_type", "")
    config_section = config_section_for_violation(vtype)
    if not config_section:
        ui.notify(f"No config section for: {vtype}", type="warning")
        return

    rel_path = suggest_ignore_path(file_path)
    scanner_label = SCANNER_LABELS.get(config_section, config_section)

    with ui.dialog().props("persistent") as dlg, ui.card().classes("w-full max-w-xl"):
        ui.label("Ignore File — .aiguardignore.toml").classes("text-lg font-bold")
        ui.label(f"File: {file_path}").classes("text-sm text-grey-6")
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
            ui.button("Cancel", on_click=dlg.close).props("flat")

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
                dlg.close()

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

    dlg.open()
