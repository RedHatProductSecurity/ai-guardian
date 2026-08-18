"""IDE Sessions page — multi-IDE conversation browser."""

import urllib.parse
from datetime import datetime

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.step_render import (
    STEP_ICON_MAP,
    create_sort_toggle,
    escape_html,
    render_content_block,
    render_text_block,
    render_violation_badge,
    render_violation_summary,
)


def create_ide_sessions_page(service, daemon_name: str):
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/ide-sessions")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("IDE Sessions").classes("text-2xl font-bold")
        ui.label("Browse conversations from AI coding assistants.").classes(
            "text-xs text-grey-6"
        )

        try:
            from nicegui import app as _app

            saved_sort = _app.storage.user.get("ide_sessions_sort_newest", True)
        except Exception:
            saved_sort = True

        state = {
            "sessions": [],
            "ide": "",
            "load_fn": None,
            "newest_first": saved_sort,
        }

        with ui.row().classes("items-end gap-4 w-full"):
            ide_options = _get_ide_options()
            ide_select = ui.select(
                options=ide_options,
                value="claude",
                label="IDE",
            ).classes("w-48")

            project_select = ui.select(
                options={"": "All Projects"},
                value="",
                label="Project",
            ).classes("w-64")

            search_input = ui.input(
                label="Search",
                placeholder="Search title, model, session ID...",
            ).classes("flex-grow")

            async def _on_refresh():
                fn = state["load_fn"]
                if fn:
                    await fn()

            ui.button("Refresh", icon="refresh", on_click=_on_refresh).props(
                "dense outline"
            )

            async def _reload_sessions():
                fn = state["load_fn"]
                if fn:
                    await fn()

            create_sort_toggle(state, "ide_sessions_sort_newest", _reload_sessions)

        stats_row = ui.row().classes("w-full gap-4")
        cards_container = ui.column().classes("w-full gap-2")

        async def load_sessions():
            ide = ide_select.value
            if not ide:
                return

            state["ide"] = ide

            from ai_guardian.sessions.discovery import discover_sessions

            all_sessions = await run.io_bound(discover_sessions, ide)
            state["sessions"] = all_sessions

            _populate_project_dropdown(all_sessions, project_select)

            sessions = all_sessions
            proj_filter = project_select.value or ""
            if proj_filter:
                sessions = [s for s in sessions if s.get("project_path") == proj_filter]

            search = (search_input.value or "").strip().lower()
            if search:
                sessions = [
                    s
                    for s in sessions
                    if search in (s.get("title", "") or "").lower()
                    or search in (s.get("session_id", "") or "").lower()
                    or search in (s.get("model", "") or "").lower()
                    or search in (s.get("project_path", "") or "").lower()
                ]

            sessions.sort(
                key=lambda s: s.get("modified", 0),
                reverse=state["newest_first"],
            )
            _render_stats(sessions, stats_row, ide)
            _render_session_list(sessions, cards_container, daemon_name, ide)

        state["load_fn"] = load_sessions

        async def _on_ide_change(e):
            if e.value:
                try:
                    from nicegui import app as _app

                    _app.storage.user["ide_sessions_ide"] = e.value
                except Exception:
                    pass
                await load_sessions()

        ide_select.on_value_change(_on_ide_change)
        project_select.on_value_change(lambda _: load_sessions())
        search_input.on_value_change(lambda _: load_sessions())

        async def _detect_and_load():
            saved_ide = None
            try:
                from nicegui import app as _app

                saved_ide = _app.storage.user.get("ide_sessions_ide")
            except Exception:
                pass

            if saved_ide and saved_ide in _get_ide_options():
                ide_select.value = saved_ide
            else:
                from ai_guardian.sessions.discovery import get_default_ide

                try:
                    target = service.get_target_by_name(daemon_name)
                    if target:
                        config = await run.io_bound(service.get_daemon_config, target)
                    else:
                        config = {}
                except Exception:
                    config = {}

                ide = await run.io_bound(get_default_ide, config or {})
                ide_select.value = ide
            await load_sessions()

        ui.timer(0.1, _detect_and_load, once=True)


def _get_ide_options():
    try:
        from ai_guardian.sessions.discovery import get_supported_ides

        options = {}
        for ide in get_supported_ides():
            options[ide] = ide.title()
        return options
    except Exception:
        return {"claude": "Claude"}


def _populate_project_dropdown(sessions, project_select):
    """Populate project dropdown from discovered sessions."""
    paths = sorted(
        {s.get("project_path", "") for s in sessions if s.get("project_path")}
    )
    options = {"": "All Projects"}
    for p in paths:
        options[p] = _shorten_path(p)
    current = project_select.value
    project_select.options = options
    if current not in options:
        project_select.value = ""
    project_select.update()


def _shorten_path(path):
    """Shorten a path for dropdown display."""
    parts = path.rstrip("/").split("/")
    if len(parts) <= 3:
        return path
    return f".../{'/'.join(parts[-2:])}"


def _render_stats(sessions, container, ide):
    container.clear()
    if not sessions:
        return

    total = len(sessions)
    total_tokens = sum(
        s.get("token_usage", {}).get("input_tokens", 0)
        + s.get("token_usage", {}).get("output_tokens", 0)
        for s in sessions
    )
    projects = len(
        {s.get("project_path", "") for s in sessions if s.get("project_path")}
    )
    models = sorted({s.get("model", "") for s in sessions if s.get("model")})

    with container:
        with ui.card().classes("bg-grey-9"):
            with ui.row().classes("gap-6"):
                _stat_chip("Sessions", str(total))
                _stat_chip("Projects", str(projects))
                _stat_chip("Total Tokens", f"{total_tokens:,}")
                _stat_chip("Models", ", ".join(models) if models else "—")


_TOOLTIPS = {
    "Sessions": "Number of conversation sessions found for this IDE",
    "Projects": "Distinct project directories with sessions",
    "Total Tokens": "Sum of input + output tokens across all listed sessions",
    "Models": "LLM models used across all listed sessions",
    "Project:": "Working directory this session was started in",
    "Modified:": "Last time the session file was written to",
    "Messages:": "Total user + assistant messages in the session",
    "Tokens:": "Input + output tokens consumed by the session (sent to and received from the API)",
    "Cache Read:": "Prompt tokens served from cache instead of reprocessed — saves cost but still counted toward context",
    "Cache Create:": "Prompt tokens written into cache for reuse by subsequent turns",
    "Size:": "Session file size on disk",
    "Input:": "Tokens sent to the model (prompt, context, tool results)",
    "Output:": "Tokens generated by the model (responses, tool calls)",
    "Total:": "Input + output tokens combined",
    "Started:": "Timestamp of the first message in the session",
    "Last:": "Timestamp of the most recent message in the session",
    "Context:": "Percentage of the model's context window used by this session",
    "Mode:": "Cursor composer mode (agent, edit, etc.)",
}


def _stat_chip(label, value):
    with ui.column().classes("gap-0"):
        lbl = ui.label(label).classes("text-xs text-grey-6")
        tip = _TOOLTIPS.get(label)
        if tip:
            lbl.tooltip(tip)
        ui.label(value).classes("text-sm font-bold")


def _tlabel(text):
    """Render a grey label with tooltip from _TOOLTIPS dict."""
    lbl = ui.label(text).classes("text-xs text-grey-6")
    tip = _TOOLTIPS.get(text)
    if tip:
        lbl.tooltip(tip)
    return lbl


def _render_session_list(sessions, container, daemon_name, ide):
    container.clear()
    if not sessions:
        with container:
            ui.label("No sessions found.").classes("text-grey-6")
        return

    with container:
        for s in sessions:
            _render_session_card(s, daemon_name, ide)


def _render_session_card(session, daemon_name, ide):
    title = session.get("title", "") or "Untitled"
    model = session.get("model", "") or ""
    session_id = session.get("session_id", "")
    project_path = session.get("project_path", "") or ""
    msg_count = session.get("message_count", 0)
    tokens = session.get("token_usage", {})
    total_input = tokens.get("input_tokens", 0)
    total_output = tokens.get("output_tokens", 0)
    total_tok = total_input + total_output
    cache_read = tokens.get("cache_read_input_tokens", 0)
    ctx_pct = session.get("context_usage_percent", 0)
    mode = session.get("mode", "")

    modified = session.get("modified", 0)
    date_str = ""
    if modified:
        try:
            dt = datetime.fromtimestamp(modified)
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            pass

    size_bytes = session.get("size_bytes", 0)
    size_str = _format_size(size_bytes) if size_bytes else ""

    file_path = session.get("file_path", "")
    detail_params = urllib.parse.urlencode(
        {"file": file_path, "session": session_id, "ide": ide}
    )
    detail_url = f"/{daemon_name}/ide-session-detail?{detail_params}"

    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.icon("terminal").classes("text-blue text-sm")
            ui.link(title, detail_url).classes(
                "font-bold text-sm text-blue-4 hover:text-blue-3"
            ).style("text-decoration: underline dotted; text-underline-offset: 3px")
            if model:
                ui.label(f"({model})").classes("text-xs text-grey-6")
            ui.label(ide.title()).classes("text-xs").style(
                "background: #37474f; padding: 1px 6px; border-radius: 4px"
            )

        with ui.grid(columns=4).classes("gap-1 mt-1"):
            if project_path:
                _tlabel("Project:")
                ui.label(project_path).classes("text-xs").style(
                    "font-family: monospace; word-break: break-all"
                )
            if date_str:
                _tlabel("Modified:")
                ui.label(date_str).classes("text-xs")
            _tlabel("Messages:")
            ui.label(str(msg_count)).classes("text-xs")
            if total_tok:
                _tlabel("Tokens:")
                ui.label(f"{total_tok:,}").classes("text-xs")
            if cache_read:
                _tlabel("Cache Read:")
                ui.label(f"{cache_read:,}").classes("text-xs")
            if ctx_pct:
                _tlabel("Context:")
                ui.label(f"{ctx_pct:.1f}%").classes("text-xs")
            if mode:
                _tlabel("Mode:")
                ui.label(mode).classes("text-xs")
            if size_str:
                _tlabel("Size:")
                ui.label(size_str).classes("text-xs")

        with ui.row().classes("items-center gap-1 mt-1"):
            ui.label(session_id).classes("text-xs text-grey-7").style(
                "font-family: monospace"
            )
            ui.button(
                icon="content_copy",
                on_click=lambda sid=session_id: (
                    ui.run_javascript(f"navigator.clipboard.writeText({sid!r})"),
                    ui.notify("Copied", position="bottom", type="positive"),
                ),
            ).props("dense flat size=xs color=grey-7").tooltip("Copy session ID")


def _format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


async def _load_session_violations(service, daemon_name, session_id):
    """Load violations correlated with a session by session_id.

    NOTE: Fetches the 1000 most recent violations and filters client-side.
    Older sessions on high-activity daemons may show fewer violations than
    actually occurred if total violation count exceeds this limit.
    """
    if not session_id:
        return []
    try:
        await run.io_bound(service.refresh_targets)
        target = service.get_target_by_name(daemon_name)
        if not target:
            return []
        result = await run.io_bound(service.get_daemon_violations, target, 1000)
        all_violations = (result or {}).get("violations", [])
        return [
            v
            for v in all_violations
            if v.get("context", {}).get("session_id") == session_id
        ]
    except Exception:
        return []


def create_ide_session_detail_page(service, daemon_name: str):
    """Detail page for a single IDE session — step-by-step conversation view."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/ide-sessions")
    create_header(daemon_name, drawer=sidebar)

    params = dict(ui.context.client.request.query_params)
    file_path = params.get("file", "")
    session_id = params.get("session", "")
    ide = params.get("ide", "claude")

    with ui.column().classes("flex-grow p-6 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.button(
                icon="arrow_back",
                on_click=lambda: ui.navigate.to(f"/{daemon_name}/ide-sessions"),
            ).props("dense flat")
            header_label = ui.label("Loading...").classes("text-2xl font-bold")

        with ui.row().classes("items-center gap-1"):
            ui.label(session_id).classes("text-xs text-grey-6").style(
                "font-family: monospace; word-break: break-all"
            )
            ui.button(
                icon="content_copy",
                on_click=lambda sid=session_id: (
                    ui.run_javascript(f"navigator.clipboard.writeText({sid!r})"),
                    ui.notify("Copied", position="bottom", type="positive"),
                ),
            ).props("dense flat size=xs color=grey-7").tooltip("Copy session ID")

        try:
            from nicegui import app as _app

            saved_sort = _app.storage.user.get("ide_session_detail_sort_newest", False)
        except Exception:
            saved_sort = False

        detail_state = {"newest_first": saved_sort, "load_fn": None}

        summary_container = ui.column().classes("w-full")
        violations_container = ui.column().classes("w-full")

        with ui.row().classes("items-center gap-2 w-full"):
            ui.label("Conversation").classes("text-lg font-bold")

            async def _reload_detail():
                fn = detail_state["load_fn"]
                if fn:
                    await fn()

            create_sort_toggle(
                detail_state, "ide_session_detail_sort_newest", _reload_detail
            )

        steps_container = ui.column().classes("w-full gap-1")

        async def load_detail():
            if not file_path:
                header_label.text = "No session file specified"
                return

            from ai_guardian.sessions.reader import (
                match_violations_to_steps,
                read_session_detail,
                read_session_summary,
            )

            session = {
                "ide": ide,
                "file_path": file_path,
                "session_id": session_id,
            }

            summary = await run.io_bound(read_session_summary, session)
            detail_steps = await run.io_bound(read_session_detail, session)

            title = summary.get("title", "") or "Untitled"
            model = summary.get("model", "") or ""
            header_label.text = f"{title} ({model})"

            summary_container.clear()
            with summary_container:
                _render_session_summary(summary)

            violations_container.clear()
            session_violations = await _load_session_violations(
                service, daemon_name, session_id
            )
            if session_violations:
                with violations_container:
                    render_violation_summary(session_violations, daemon_name)

            violations_by_step = match_violations_to_steps(
                detail_steps, session_violations
            )

            if detail_state["newest_first"]:
                n = len(detail_steps)
                detail_steps = list(reversed(detail_steps))
                reversed_map = {}
                for orig_idx, viols in violations_by_step.items():
                    reversed_map[n - 1 - orig_idx] = viols
                violations_by_step = reversed_map

            steps_container.clear()
            with steps_container:
                if not detail_steps:
                    ui.label("No conversation data found.").classes("text-grey-6")
                else:
                    for i, step in enumerate(detail_steps):
                        _render_step(
                            step, i, violations_by_step.get(i, []), daemon_name
                        )

        detail_state["load_fn"] = load_detail
        ui.timer(0.1, load_detail, once=True)


def _render_session_summary(summary):
    """Render session metadata summary card."""
    tokens = summary.get("token_usage", {})
    total_in = tokens.get("input_tokens", 0)
    total_out = tokens.get("output_tokens", 0)
    cache_read = tokens.get("cache_read_input_tokens", 0)
    cache_create = tokens.get("cache_creation_input_tokens", 0)
    user_msgs = summary.get("user_messages", 0)
    asst_msgs = summary.get("assistant_messages", 0)
    first_ts = (summary.get("first_timestamp", "") or "")[:19]
    last_ts = (summary.get("last_timestamp", "") or "")[:19]

    with ui.card().classes("w-full bg-grey-9"):
        ui.label("Session Summary").classes("text-sm font-bold")
        with ui.grid(columns=6).classes("gap-1"):
            _tlabel("Input:")
            ui.label(f"{total_in:,}").classes("text-xs")
            _tlabel("Output:")
            ui.label(f"{total_out:,}").classes("text-xs")
            _tlabel("Total:")
            ui.label(f"{total_in + total_out:,}").classes("text-xs")
            _tlabel("Cache Read:")
            ui.label(f"{cache_read:,}").classes("text-xs")
            _tlabel("Cache Create:")
            ui.label(f"{cache_create:,}").classes("text-xs")
            _tlabel("Messages:")
            ui.label(f"{user_msgs} user / {asst_msgs} assistant").classes("text-xs")
            if first_ts:
                _tlabel("Started:")
                ui.label(first_ts).classes("text-xs")
            if last_ts:
                _tlabel("Last:")
                ui.label(last_ts).classes("text-xs")


def _render_step(step, index, violations=None, daemon_name=""):
    """Render a single conversation step with optional violation badges."""
    step_type = step.get("type", "")
    icon_name, icon_color = STEP_ICON_MAP.get(step_type, ("help", "text-grey-6"))

    with ui.card().classes("w-full py-1 px-2"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.icon(icon_name).classes(f"{icon_color} text-sm")

            if step_type == "user":
                ts = (step.get("timestamp", "") or "")[:19]
                ui.label("User").classes("text-xs font-bold text-blue")
                if ts:
                    ui.label(ts).classes("text-xs text-grey-6")

            elif step_type == "assistant":
                model = step.get("model", "")
                usage = step.get("usage", {})
                tok_in = usage.get("input_tokens", 0)
                tok_out = usage.get("output_tokens", 0)
                ui.label("Assistant").classes("text-xs font-bold text-green")
                if model:
                    ui.label(f"({model})").classes("text-xs text-grey-6")
                if tok_in or tok_out:
                    ui.label(f"{tok_in + tok_out:,} tok").classes("text-xs text-grey-6")

            elif step_type == "tool_use":
                tool_name = step.get("tool_name", "")
                ui.label(f"Tool Call: {tool_name}").classes(
                    "text-xs font-bold text-orange"
                )

            elif step_type == "tool_result":
                tool_name = step.get("tool_name", "")
                label = f"Tool Result: {tool_name}" if tool_name else "Tool Result"
                ui.label(label).classes("text-xs font-bold text-orange")

            elif step_type == "thinking":
                ui.label("Thinking").classes("text-xs font-bold text-purple")

            elif step_type == "system":
                subtype = step.get("content", "")
                ui.label(f"System: {subtype}").classes("text-xs text-grey-6")

            elif step_type == "title":
                ui.label(f"Title: {step.get('content', '')}").classes(
                    "text-xs font-bold"
                )

            if violations:
                vc = len(violations)
                ui.badge(
                    f"{vc} violation{'s' if vc != 1 else ''}",
                    color="red",
                ).classes("text-xs")

        if violations:
            for v in violations:
                render_violation_badge(v, daemon_name)

        render_content_block(
            step.get("content", ""),
            tool_input=step.get("tool_input"),
            step_type=step_type,
        )
