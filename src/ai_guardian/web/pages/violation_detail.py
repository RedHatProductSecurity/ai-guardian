"""Violation detail page — dedicated view with deep-link support."""

import json

from nicegui import run, ui

from ai_guardian.constants import HookEvent
from ai_guardian.violations.guidance import get_resolution_instructions
from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.local_time import (
    inject_local_time_js,
    local_time_label,
)
from ai_guardian.web.pages.violations import (
    DETAIL_FIELDS,
    _ALLOWLIST_TYPES,
    _format_violation_markdown,
    _load_local_violations,
    _show_allow_always_flow,
    _show_ignore_file_flow,
    _show_suppress_in_source_flow,
)


def _find_violation_by_id(violations, violation_id):
    """Find a violation by its ID in a list of violation dicts."""
    for v in violations:
        if v.get("id") == violation_id:
            return v
    return None


def create_violation_detail_page(service, daemon_name: str):
    """Build a dedicated violation detail page, accessible via deep-link."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/violations")
    create_header(daemon_name, drawer=sidebar)

    params = dict(ui.context.client.request.query_params)
    violation_id = params.get("id", "")

    with ui.column().classes("flex-grow p-6 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.button(
                icon="arrow_back",
                on_click=lambda: ui.navigate.to(f"/{daemon_name}/violations"),
            ).props("dense flat")
            header_label = ui.label("Violation Detail").classes("text-2xl font-bold")

        if not violation_id:
            ui.label("No violation ID specified.").classes("text-red mt-4")
            return

        ui.label(f"ID: {violation_id}").classes("text-xs text-grey-6").style(
            "font-family: monospace"
        )

        content_container = ui.column().classes("w-full gap-4")

        async def load_violation():
            await run.io_bound(service.refresh_targets)
            target = service.get_target_by_name(daemon_name)

            all_violations = []
            if target:
                if target.runtime == "local":
                    raw = await run.io_bound(_load_local_violations, 5000, None)
                else:
                    raw = await run.io_bound(
                        service.get_daemon_violations, target, 5000, None
                    )
                if raw:
                    vlist = raw if isinstance(raw, list) else raw.get("violations", [])
                    all_violations.extend(vlist)

            violation = _find_violation_by_id(all_violations, violation_id)

            content_container.clear()
            with content_container:
                if not violation:
                    ui.label(f"Violation {violation_id} not found.").classes(
                        "text-red mt-2"
                    )
                    ui.label(
                        "It may have been rotated out of the log or the ID is invalid."
                    ).classes("text-xs text-grey-6")
                    return

                header_label.text = f"Violation Detail — {violation_id}"
                _render_violation_detail(violation, service, daemon_name)

            inject_local_time_js()

        ui.timer(0.1, load_violation, once=True)


def _render_violation_detail(v: dict, service, daemon_name: str):
    """Render full violation details inline on the page."""
    vtype = v.get("violation_type", v.get("type", "unknown"))
    severity = v.get("severity", "warning")
    timestamp = v.get("timestamp", "")
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

    # --- Header ---
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.icon(sev_icon).classes(f"text-{sev_color} text-lg")
            vtype_display = vtype.upper().replace("_", " ")
            ui.label(f"{v_icon} {vtype_display}").classes("font-bold text-lg")
            ui.badge(severity, color=sev_color).classes("text-xs")
            if resolved:
                ui.badge("RESOLVED", color="green").classes("text-xs")

        with ui.row().classes("items-center gap-2 mt-1"):
            ui.label("Time:").classes("text-xs text-grey-6")
            local_time_label(timestamp).classes("text-xs")

    # --- Blocked details ---
    fields = DETAIL_FIELDS.get(vtype, [])
    if fields:
        with ui.card().classes("w-full"):
            ui.label("Details").classes("text-sm font-bold")
            with ui.grid(columns=2).classes("gap-2 mt-1"):
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
                        ui.label(display).classes("text-xs").style(
                            "word-break: break-all"
                        )

    # --- Suggested rule ---
    if vtype == "tool_permission" and suggestion.get("rule"):
        with ui.card().classes("w-full"):
            ui.label("Suggested Rule").classes("text-sm font-bold")
            ui.code(json.dumps(suggestion["rule"], indent=2), language="json").classes(
                "text-xs mt-1"
            )

    # --- Context ---
    session_id = context.get("session_id")
    project_path = context.get("project_path")
    ide_type = context.get("ide_type")
    tool_use_id = context.get("tool_use_id")
    hook_event = context.get("hook_event", "")

    context_items = []
    if session_id:
        context_items.append(("Session ID", session_id))
    if project_path:
        context_items.append(("Project", project_path))
    if ide_type:
        context_items.append(("IDE", ide_type))
    if tool_use_id:
        context_items.append(("Tool Use ID", tool_use_id))
    if hook_event:
        try:
            hook_label = HookEvent(hook_event).display_name
        except ValueError:
            hook_label = hook_event
        context_items.append(("Hook Event", hook_label))

    if context_items:
        with ui.card().classes("w-full"):
            ui.label("Context").classes("text-sm font-bold")
            with ui.grid(columns=2).classes("gap-2 mt-1"):
                for label, val in context_items:
                    ui.label(f"{label}:").classes("text-xs text-grey-6")
                    ui.label(str(val)).classes("text-xs").style(
                        "font-family: monospace; word-break: break-all"
                    )

    # --- Resolution instructions ---
    with ui.card().classes("w-full"):
        ui.label("How to Resolve").classes("text-sm font-bold")
        instructions, snippet = get_resolution_instructions(v)
        ui.label(instructions).classes("text-sm mt-1")
        if snippet:
            ui.code(snippet, language="json").classes("text-xs mt-1")

    # --- Resolution status ---
    if resolved:
        with ui.card().classes("w-full"):
            ui.label("Resolution").classes("text-sm font-bold")
            resolved_at = v.get("resolved_at", "")
            resolved_action = v.get("resolved_action", "")
            resolved_note = v.get("resolved_note", "")
            with ui.grid(columns=2).classes("gap-2 mt-1"):
                if resolved_action:
                    ui.label("Action:").classes("text-xs text-grey-6")
                    ui.label(resolved_action).classes("text-xs")
                if resolved_at:
                    ui.label("Resolved at:").classes("text-xs text-grey-6")
                    ui.label(resolved_at).classes("text-xs")
                if resolved_note:
                    ui.label("Note:").classes("text-xs text-grey-6")
                    ui.label(resolved_note).classes("text-xs")

    # --- Actions ---
    with ui.row().classes("gap-2 mt-2"):
        violation_json = json.dumps(v, indent=2, default=str)
        ui.button(
            "Copy JSON",
            icon="data_object",
            on_click=lambda vj=violation_json: ui.run_javascript(
                f"navigator.clipboard.writeText({json.dumps(vj)})"
            ),
        ).props("flat dense size=sm")

        violation_md = _format_violation_markdown(v)
        ui.button(
            "Copy as Markdown",
            icon="article",
            on_click=lambda md=violation_md: ui.run_javascript(
                f"navigator.clipboard.writeText({json.dumps(md)})"
            ),
        ).props("flat dense size=sm")

        if vtype in _ALLOWLIST_TYPES and service is not None:

            async def on_always_allow(viol=v, svc=service, dname=daemon_name):
                await _show_allow_always_flow(None, viol, svc, dname)

            ui.button(
                "Always Allow...",
                icon="check_circle",
                on_click=on_always_allow,
            ).props("color=positive dense size=sm")

        blocked_data = v.get("blocked", {})
        v_file_path = (
            blocked_data.get("file_path", "") if isinstance(blocked_data, dict) else ""
        )
        if v_file_path:
            from ai_guardian.tui.source_annotator import get_comment_prefix

            v_line_number = (
                blocked_data.get("line_number")
                if isinstance(blocked_data, dict)
                else None
            )
            if v_line_number and get_comment_prefix(v_file_path) is not None:

                def on_suppress_source(viol=v):
                    _show_suppress_in_source_flow(viol)

                ui.button(
                    "Suppress in Source...",
                    icon="code",
                    on_click=on_suppress_source,
                ).props("color=warning dense size=sm")

            def on_ignore_file(viol=v):
                _show_ignore_file_flow(viol)

            ui.button(
                "Ignore File...",
                icon="block",
                on_click=on_ignore_file,
            ).props("color=warning dense size=sm")

    # --- Raw JSON (collapsible) ---
    with ui.expansion("Raw JSON", icon="data_object").classes("w-full").props("dense"):
        ui.code(violation_json, language="json").classes(
            "max-h-[400px] overflow-auto text-xs"
        )

    # --- Link to violations list ---
    with ui.row().classes("gap-2 mt-2"):
        ui.link(
            "← Back to Violations",
            f"/{daemon_name}/violations",
        ).classes("text-sm text-blue-4")

        if session_id:
            ui.label("·").classes("text-grey-6")
            ui.link(
                "View Session",
                f"/{daemon_name}/ide-sessions",
            ).classes("text-sm text-blue-4")
