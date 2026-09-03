"""Trace Viewer page — conversation traces from GuardedAgent runs."""

import fnmatch
import json
import tempfile
import urllib.parse
from datetime import date, datetime, timedelta, timezone

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.local_time import (
    inject_local_time_js,
    local_time_label,
)
from ai_guardian.web.components.content_viewer import render_view_button
from ai_guardian.web.components.step_render import (
    compute_context_tokens,
    create_pause_toggle,
    create_sort_toggle,
    format_duration,
    format_token_count,
    render_guardian_icon,
    render_text_block,
    render_violation_badge,
)


def _display_stop_reason(stop_reason: str) -> str:
    """Use a neutral UI label for traces that were not finalized."""
    return "interrupted" if stop_reason == "crashed" else stop_reason


def create_traces_page(service, daemon_name: str):
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/traces")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Sessions").classes("text-2xl font-bold")
        ui.label(
            "Unified SDK and hook security traces across all discovered daemons. "
            "Non-SDK agents provide the SDK run_id in hook events or "
            "AI_GUARDIAN_RUN_ID for correlation."
        ).classes("text-xs text-grey-6")

        try:
            from nicegui import app as _app

            saved_sort = _app.storage.user.get("traces_sort_newest", True)
        except Exception:
            saved_sort = True

        PAGE_SIZE = 50
        state = {
            "load_fn": None,
            "newest_first": saved_sort,
            "page": 1,
            "day": date.today(),
        }
        expanded_runs: set = set()

        auto_timer = {"ref": None, "paused": False}

        with (
            ui.row()
            .classes("items-end gap-4 w-full")
            .style("position: sticky; top: 0; z-index: 10; background: #121212")
        ):
            filter_input = ui.input(
                label="Filter filenames",
                placeholder="Wildcard: *, ?  e.g. triage-*",
            ).classes("flex-grow")

            agent_select = ui.select(
                options={"": "All Agents"},
                value="",
                label="Agent",
            ).classes("w-48")

            daemon_select = ui.select(
                options={"": "All Daemons"},
                value="",
                label="Daemon",
            ).classes("w-48")

            top_input = (
                ui.number(label="Top", value=1000, min=10, max=10000, step=100)
                .classes("w-24")
                .props("dense")
            )

            async def _on_refresh():
                state["page"] = 1
                fn = state["load_fn"]
                if fn:
                    await fn()

            ui.button("Refresh", icon="refresh", on_click=_on_refresh).props(
                "dense outline"
            )

            async def _reload_traces():
                state["page"] = 1
                fn = state["load_fn"]
                if fn:
                    await fn()

            create_sort_toggle(state, "traces_sort_newest", _reload_traces)
            create_pause_toggle(auto_timer)

        with (
            ui.row()
            .classes("items-center gap-2 w-full")
            .style("position: sticky; top: 48px; z-index: 9; background: #121212")
        ):

            async def _previous_day():
                state["day"] -= timedelta(days=1)
                state["page"] = 1
                fn = state["load_fn"]
                if fn:
                    await fn()

            async def _next_day():
                if state["day"] < date.today():
                    state["day"] += timedelta(days=1)
                    state["page"] = 1
                    fn = state["load_fn"]
                    if fn:
                        await fn()

            async def _today():
                state["day"] = date.today()
                state["page"] = 1
                fn = state["load_fn"]
                if fn:
                    await fn()

            previous_day_btn = ui.button("◀ Day", on_click=_previous_day).props(
                "dense outline"
            )
            day_label = ui.label().classes("text-sm font-bold")
            next_day_btn = ui.button("Day ▶", on_click=_next_day).props("dense outline")
            ui.button("Today", on_click=_today).props("dense flat")

            async def _prev_page():
                if state["page"] > 1:
                    state["page"] -= 1
                    fn = state["load_fn"]
                    if fn:
                        await fn()

            async def _next_page():
                state["page"] += 1
                fn = state["load_fn"]
                if fn:
                    await fn()

            prev_btn = ui.button("◀ Prev", on_click=_prev_page).props("dense outline")
            page_label = ui.label("").classes("text-xs text-grey-5")
            next_btn = ui.button("Next ▶", on_click=_next_page).props("dense outline")

        cards_container = ui.column().classes("w-full gap-2")

        async def load_traces():
            try:
                if ui.context.client.is_deleted:
                    return
                await run.io_bound(service.refresh_targets)

                agent_filter = agent_select.value or None
                limit = int(top_input.value or 1000)
                result = await run.io_bound(
                    service.get_all_daemon_traces, agent_filter, limit
                )

                traces = (result or {}).get("traces", [])
                total_on_disk = (result or {}).get("total_count", len(traces))
                pattern = filter_input.value.strip() if filter_input.value else None
                if pattern:
                    traces = _filter_traces(traces, pattern)

                daemon_filter = daemon_select.value or None
                if daemon_filter:
                    traces = [
                        t for t in traces if t.get("daemon_source") == daemon_filter
                    ]

                traces.sort(
                    key=lambda t: t.get("started_at", ""),
                    reverse=state["newest_first"],
                )
                _populate_agent_filter(traces, agent_select)
                _populate_daemon_filter(traces, daemon_select)

                from ai_guardian.daemon.traces import group_traces_by_run

                grouped = group_traces_by_run(traces)
                selected_day = state["day"]
                grouped = [
                    group
                    for group in grouped
                    if _trace_local_day(group.get("started_at")) == selected_day
                ]
                if not state["newest_first"]:
                    grouped.sort(key=lambda t: t.get("started_at", ""))

                total_matches = len(grouped)
                total_pages = max(1, -(-total_matches // PAGE_SIZE))
                state["page"] = max(1, min(state["page"], total_pages))
                page = state["page"]
                start = (page - 1) * PAGE_SIZE
                page_items = grouped[start : start + PAGE_SIZE]

                _render_trace_list(
                    page_items, cards_container, daemon_name, expanded_runs
                )

                day_label.set_text(_format_day_label(selected_day))
                next_day_btn.set_enabled(selected_day < date.today())
                previous_day_btn.set_enabled(True)
                prev_btn.set_enabled(page > 1)
                next_btn.set_enabled(page < total_pages)
                daemon_count = len(service.targets)
                parts = [
                    f"Page {page} of {total_pages}"
                    f" ({total_matches} matches from {daemon_count} daemon"
                    f"{'s' if daemon_count != 1 else ''})"
                ]
                if total_on_disk > len((result or {}).get("traces", [])):
                    parts.append(f" — showing top {limit} of {total_on_disk}")
                page_label.set_text("".join(parts))

                if auto_timer["ref"] is None and not auto_timer.get("paused"):
                    target = service.get_target_by_name(daemon_name)
                    interval = (
                        _get_auto_refresh_interval(service, target) if target else 5
                    )
                    auto_timer["ref"] = ui.timer(interval, load_traces)
            except Exception as exc:
                cards_container.clear()
                with cards_container:
                    ui.label(f"Error: {exc}").classes("text-red")

        state["load_fn"] = load_traces

        async def _on_filter_change():
            state["page"] = 1
            await load_traces()

        filter_input.on_value_change(lambda _: _on_filter_change())
        top_input.on_value_change(lambda _: _on_filter_change())
        daemon_select.on_value_change(lambda _: _on_filter_change())

        ui.timer(0.1, load_traces, once=True)


def create_trace_detail_page(service, daemon_name: str):
    """Detail page for a single trace conversation."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/traces")
    create_header(daemon_name, drawer=sidebar)

    params = dict(ui.context.client.request.query_params)
    filename = params.get("file", "")
    source_daemon = params.get("daemon", daemon_name)

    with ui.column().classes("flex-grow p-6 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.button(
                icon="arrow_back",
                on_click=lambda: ui.navigate.to(f"/{daemon_name}/traces"),
            ).props("dense flat")
            header_label = ui.label("Loading...").classes("text-2xl font-bold")

        with ui.row().classes("items-center gap-1"):
            ui.label(filename).classes("text-xs text-grey-6").style(
                "font-family: monospace; word-break: break-all"
            )
            ui.button(
                icon="content_copy",
                on_click=lambda fn=filename: (
                    ui.run_javascript(f"navigator.clipboard.writeText({fn!r})"),
                    ui.notify("Copied", position="bottom", type="positive"),
                ),
            ).props("dense flat size=xs color=grey-7").tooltip("Copy filename")
            if source_daemon:
                ui.badge(f"daemon: {source_daemon}", color="blue-grey").classes(
                    "text-xs"
                )

        try:
            from nicegui import app as _app

            saved_sort = _app.storage.user.get("trace_detail_sort_newest", False)
        except Exception:
            saved_sort = False

        summary_container = ui.column().classes("w-full")
        export_container = ui.row().classes("w-full gap-2 items-center")
        expanded_turns: set = set()
        detail_state = {"result": None, "newest_first": saved_sort, "load_fn": None}

        async def _export_otlp_json():
            result = detail_state["result"]
            if not result:
                ui.notify("No trace loaded", type="warning")
                return
            try:
                from ai_guardian.observability.otel_exporter import trace_to_otlp_json

                otlp = trace_to_otlp_json(result)
                tmp = tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".otlp.json",
                    prefix="ai-guardian-trace-",
                    delete=False,
                )
                json.dump(otlp, tmp, indent=2)
                tmp.close()
                ui.download(tmp.name)
                ui.notify(f"Exported to {tmp.name}")
            except Exception as exc:
                ui.notify(f"Export failed: {exc}", type="negative")

        async def _send_to_collector():
            result = detail_state["result"]
            if not result:
                ui.notify("No trace loaded", type="warning")
                return
            try:
                import requests as req

                from ai_guardian.observability.otel_exporter import trace_to_otlp_json

                otlp = trace_to_otlp_json(result)
                endpoint = endpoint_input.value.strip()
                if not endpoint:
                    ui.notify("Enter collector endpoint", type="warning")
                    return
                url = endpoint.rstrip("/") + "/v1/traces"
                resp = await run.io_bound(
                    lambda: req.post(
                        url,
                        json=otlp,
                        headers={"Content-Type": "application/json"},
                        timeout=30,
                    )
                )
                resp.raise_for_status()
                ui.notify(f"Sent to {url} (HTTP {resp.status_code})")
            except Exception as exc:
                ui.notify(f"Send failed: {exc}", type="negative")

        with export_container:
            ui.button(
                "Export OTLP JSON",
                icon="download",
                on_click=_export_otlp_json,
            ).props("dense outline")
            endpoint_input = (
                ui.input(
                    placeholder="http://collector:4318",
                )
                .classes("w-64")
                .props("dense")
            )
            ui.button(
                "Send to Collector",
                icon="send",
                on_click=_send_to_collector,
            ).props("dense outline")

        auto_timer = {"ref": None, "paused": False}

        with (
            ui.row()
            .classes("items-center gap-2")
            .style("position: sticky; top: 0; z-index: 10; background: #121212")
        ):
            ui.label("Turns").classes("text-lg font-bold")

            async def _reload_trace_detail():
                fn = detail_state["load_fn"]
                if fn:
                    await fn()

            create_sort_toggle(
                detail_state, "trace_detail_sort_newest", _reload_trace_detail
            )
            create_pause_toggle(auto_timer)

        turns_container = ui.column().classes("w-full gap-1")
        dialog_host = ui.element("div")
        scroll_anchor = ui.element("div")

        async def load_detail():
            if ui.context.client.is_deleted:
                return
            await run.io_bound(service.refresh_targets)

            result = await run.io_bound(
                service.get_daemon_trace_detail_hybrid,
                source_daemon,
                daemon_name,
                filename,
            )
            if not result or result.get("error"):
                header_label.text = "Trace not found"
                with turns_container:
                    turns_container.clear()
                    err = (result or {}).get("error", "")
                    msg = err or (
                        "Trace unavailable — source daemon offline"
                        " and trace not cached."
                    )
                    ui.label(msg).classes("text-red")
                return

            detail_state["result"] = result
            agent_name = result.get("agent_name", "")
            model = result.get("model", "")
            stop_reason = _display_stop_reason(result.get("stop_reason", ""))
            is_active = result.get("is_active", False)

            header_label.text = f"{agent_name} ({model})"

            summary_container.clear()
            with summary_container:
                with ui.row().classes("items-center gap-2"):
                    if is_active:
                        ui.badge("ACTIVE", color="green").classes("text-xs")
                    elif stop_reason == "error":
                        ui.badge(stop_reason.upper(), color="red").classes("text-xs")
                    elif stop_reason == "interrupted":
                        ui.badge("INTERRUPTED", color="orange").classes(
                            "text-xs"
                        ).tooltip("Recording ended without a SessionEnd event")
                    else:
                        ui.badge(stop_reason or "done", color="grey").classes("text-xs")
                    fragment_count = result.get("fragment_count", 1)
                    if fragment_count > 1:
                        ui.badge(
                            f"{fragment_count} fragments", color="blue-grey"
                        ).classes("text-xs")
                    ui.label("Started:").classes("text-xs text-grey-6")
                    local_time_label(result.get("started_at") or "")

                computed = result.get("computed", {})
                total_turns = len(result.get("trace", []))
                _render_token_summary(computed, total_turns)

            trace = result.get("trace", [])
            computed = result.get("computed", {})
            per_turn = computed.get("per_turn_tokens", [])
            violations_map = {v["turn"]: v for v in computed.get("violations", [])}

            if detail_state["newest_first"]:
                trace = list(reversed(trace))

            turns_container.clear()
            with turns_container:
                for turn_obj in trace:
                    _render_turn_row(
                        turn_obj,
                        per_turn,
                        violations_map,
                        expanded_turns,
                        daemon_name,
                        dialog_host=dialog_host,
                    )

            inject_local_time_js()

            await ui.run_javascript(
                "(() => {"
                "  const threshold = 150;"
                "  const atBottom = (window.innerHeight + window.scrollY) "
                ">= (document.body.scrollHeight - threshold);"
                "  if (atBottom) window.scrollTo("
                "{top: document.body.scrollHeight, behavior: 'smooth'});"
                "})()"
            )

            if auto_timer["ref"] is None and not auto_timer.get("paused"):
                detail_target = service.get_target_by_name(
                    source_daemon
                ) or service.get_target_by_name(daemon_name)
                interval = (
                    _get_auto_refresh_interval(service, detail_target)
                    if detail_target
                    else 5
                )
                auto_timer["ref"] = ui.timer(interval, load_detail)

        detail_state["load_fn"] = load_detail
        ui.timer(0.1, load_detail, once=True)


def _get_auto_refresh_interval(service, target):
    try:
        from ai_guardian.config.loaders import resolve_tracing_config

        cfg = service.get_daemon_config(target) or {}
        return resolve_tracing_config(cfg)["auto_refresh_interval_seconds"]
    except Exception:
        return 5


def _filter_traces(traces, pattern):
    """Filter traces by filename using fnmatch wildcard pattern."""
    if not pattern.startswith("*"):
        pattern = f"*{pattern}*"
    return [t for t in traces if fnmatch.fnmatch(t.get("filename", ""), pattern)]


def _trace_local_day(started_at):
    """Return the local calendar day for a trace's ISO timestamp."""
    if not started_at or not isinstance(started_at, str):
        return None
    try:
        timestamp = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone().date()
    except (TypeError, ValueError, OverflowError):
        return None


def _format_day_label(selected_day):
    """Format the selected day for the Sessions navigator."""
    today = date.today()
    if selected_day == today:
        return "Today"
    if selected_day == today - timedelta(days=1):
        return "Yesterday"
    return selected_day.strftime("%a, %b %d, %Y").replace(" 0", " ")


def _populate_agent_filter(traces, agent_select):
    names = sorted({t.get("agent_name", "") for t in traces if t.get("agent_name")})
    options = {"": "All Agents"}
    for name in names:
        options[name] = name
    current = agent_select.value
    agent_select.options = options
    if current not in options:
        agent_select.value = ""
    agent_select.update()


def _populate_daemon_filter(traces, daemon_select):
    """Populate daemon filter dropdown from trace daemon_source values."""
    names = sorted(
        {t.get("daemon_source", "") for t in traces if t.get("daemon_source")}
    )
    options = {"": "All Daemons"}
    for name in names:
        options[name] = name
    current = daemon_select.value
    daemon_select.options = options
    if current not in options:
        daemon_select.value = ""
    daemon_select.update()


def _render_trace_list(items, container, daemon_name, expanded_runs=None):
    container.clear()
    if not items:
        with container:
            ui.label("No trace files found.").classes("text-grey-6")
        return

    with container:
        for item in items:
            if item.get("type") == "run_group":
                _render_run_group_card(item, daemon_name, expanded_runs)
            else:
                _render_trace_card(item, daemon_name)

    inject_local_time_js()


def _render_run_group_card(group, daemon_name, expanded_runs=None):
    """Render a collapsible run group card with aggregate stats."""
    run_id = group.get("run_id", "")
    agent_count = group.get("agent_count", 0)
    total_duration = group.get("total_duration", 0)
    total_violations = group.get("total_violations", 0)
    is_active = group.get("is_active", False)
    started_at = group.get("started_at") or ""
    child_traces = group.get("traces", [])

    daemon_sources = sorted(
        {t.get("daemon_source", "") for t in child_traces if t.get("daemon_source")}
    )

    duration_str = _format_duration(total_duration)

    is_open = expanded_runs is not None and run_id in expanded_runs

    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 w-full"):
            if is_active:
                ui.icon("fiber_manual_record").classes("text-green text-xs")
            else:
                ui.icon("account_tree").classes("text-blue-4 text-xs")

            ui.label(run_id).classes("font-bold text-sm text-blue-4").style(
                "font-family: monospace; word-break: break-all"
            )
            ui.label(f"{agent_count} agent{'s' if agent_count != 1 else ''}").classes(
                "text-xs text-grey-5"
            )
            ui.label(duration_str).classes("text-xs text-grey-5")

            for ds in daemon_sources:
                ui.badge(ds, color="blue-grey").classes("text-xs")

            if is_active:
                ui.badge("ACTIVE", color="green").classes("text-xs")

            if total_violations > 0:
                ui.badge(
                    f"{total_violations} violation{'s' if total_violations != 1 else ''}",
                    color="red",
                ).classes("text-xs")

            local_time_label(started_at)

        exp = ui.expansion("Traces", value=is_open).classes("w-full").props("dense")

        def _on_toggle(e, rid=run_id):
            if expanded_runs is not None:
                if e.value:
                    expanded_runs.add(rid)
                else:
                    expanded_runs.discard(rid)

        exp.on_value_change(_on_toggle)

        with exp:
            for t in child_traces:
                seq = t.get("run_sequence")
                seq_label = f"seq={seq}" if seq is not None else ""
                with ui.row().classes("items-center gap-1 w-full"):
                    if seq_label:
                        ui.badge(seq_label, color="grey").classes("text-xs")
                _render_trace_card(t, daemon_name)


def _render_trace_card(trace, daemon_name):
    agent_name = trace.get("agent_name", "unknown")
    model = trace.get("model", "")
    is_active = trace.get("is_active", False)
    stop_reason = _display_stop_reason(trace.get("stop_reason", ""))
    started_at = trace.get("started_at") or ""
    total_turns = trace.get("total_turns", 0)
    violation_count = trace.get("violation_count", 0)
    filename = trace.get("filename", "")
    daemon_source = trace.get("daemon_source", "")
    fragment_count = trace.get("fragment_count", 1)

    tokens = trace.get("total_tokens", {})
    total_input = tokens.get("input_tokens", 0)
    total_output = tokens.get("output_tokens", 0)
    total_tok = total_input + total_output
    context_tok = compute_context_tokens(tokens)

    duration = trace.get("duration_seconds", 0)
    duration_str = _format_duration(duration)

    source_daemon = daemon_source or daemon_name
    detail_params = (
        f"?file={urllib.parse.quote(filename, safe='/')}"
        f"&daemon={urllib.parse.quote(source_daemon, safe='')}"
    )
    detail_url = f"/{daemon_name}/trace-detail{detail_params}"

    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 w-full"):
            if is_active:
                ui.icon("fiber_manual_record").classes("text-green text-xs")
            elif stop_reason == "error":
                ui.icon("error_outline").classes("text-red text-xs")
            elif stop_reason == "interrupted":
                ui.icon("pan_tool").classes("text-orange text-xs")
            else:
                ui.icon("check_circle").classes("text-grey-6 text-xs")

            ui.link(agent_name, detail_url).classes(
                "font-bold text-sm text-blue-4 hover:text-blue-3"
            ).style("text-decoration: underline dotted; text-underline-offset: 3px")
            ui.label(f"({model})").classes("text-xs text-grey-6")

            if daemon_source:
                ui.badge(daemon_source, color="blue-grey").classes("text-xs").tooltip(
                    "Source daemon"
                )

            if is_active:
                ui.badge("ACTIVE", color="green").classes("text-xs")
            elif stop_reason == "error":
                ui.badge(stop_reason.upper(), color="red").classes("text-xs")
            elif stop_reason == "interrupted":
                ui.badge("INTERRUPTED", color="orange").classes("text-xs").tooltip(
                    "Recording ended without a SessionEnd event"
                )
            else:
                ui.badge(stop_reason or "done", color="grey").classes("text-xs")

            if violation_count > 0:
                ui.badge(
                    f"{violation_count} violation{'s' if violation_count != 1 else ''}",
                    color="red",
                ).classes("text-xs")
            if fragment_count > 1:
                ui.badge(f"{fragment_count} fragments", color="blue-grey").classes(
                    "text-xs"
                )

        with ui.grid(columns=4).classes("gap-1 mt-1"):
            ui.label("Started:").classes("text-xs text-grey-6")
            local_time_label(started_at)
            ui.label("Turns:").classes("text-xs text-grey-6")
            ui.label(str(total_turns)).classes("text-xs")
            if context_tok:
                ui.label("Context:").classes("text-xs text-grey-6")
                ui.label(format_token_count(context_tok)).classes("text-xs")
            ui.label("Tokens:").classes("text-xs text-grey-6")
            ui.label(f"{total_tok:,}").classes("text-xs")
            ui.label("Duration:").classes("text-xs text-grey-6")
            ui.label(duration_str).classes("text-xs")
            ui.label("File:").classes("text-xs text-grey-6")
            ui.label(filename).classes("text-xs").style(
                "font-family: monospace; word-break: break-all"
            )


def _render_token_summary(computed, total_turns=0):
    total = computed.get("total_tokens", {})
    cache_ratio = computed.get("cache_hit_ratio", 0)
    duration = computed.get("duration_seconds", 0)
    duration_str = _format_duration(duration) if duration else "—"
    context_tok = compute_context_tokens(total)

    with ui.card().classes("w-full bg-grey-9 mt-2"):
        ui.label("Summary").classes("text-sm font-bold")
        with ui.grid(columns=6).classes("gap-1"):
            ui.label("Turns:").classes("text-xs text-grey-6")
            ui.label(str(total_turns)).classes("text-xs")
            ui.label("Duration:").classes("text-xs text-grey-6")
            ui.label(duration_str).classes("text-xs")
            ui.label("Context:").classes("text-xs text-grey-6")
            ui.label(format_token_count(context_tok)).classes("text-xs")
            ui.label("Input:").classes("text-xs text-grey-6")
            ui.label(format_token_count(total.get("input_tokens", 0))).classes(
                "text-xs"
            )
            ui.label("Cache Read:").classes("text-xs text-grey-6")
            ui.label(
                format_token_count(total.get("cache_read_input_tokens", 0))
            ).classes("text-xs")
            ui.label("Cache Create:").classes("text-xs text-grey-6")
            ui.label(
                format_token_count(total.get("cache_creation_input_tokens", 0))
            ).classes("text-xs")
            ui.label("Output:").classes("text-xs text-grey-6")
            ui.label(format_token_count(total.get("output_tokens", 0))).classes(
                "text-xs"
            )
            ui.label("Cache Hit:").classes("text-xs text-grey-6")
            ui.label(f"{cache_ratio:.1%}").classes("text-xs")


def _collect_turn_violations(steps):
    """Collect all violations from scan steps in a turn.

    Returns list of (violation_dict, step_num) tuples.
    """
    result = []
    for step in steps:
        if step.get("type") == "scan":
            step_num = step.get("step", 0)
            for v in step.get("violations", []):
                result.append((v, step_num))
    return result


def _render_turn_row(
    turn_obj,
    per_turn,
    violations_map,
    expanded_turns=None,
    daemon_name="",
    dialog_host=None,
):
    """Render a single turn as a row with summary and expandable details."""
    turn_num = turn_obj.get("turn", 0)
    steps = turn_obj.get("steps", [])

    turn_tokens = 0
    turn_context = 0
    turn_output = 0
    for pt in per_turn:
        if pt.get("turn") == turn_num:
            turn_output = pt.get("output_tokens", 0)
            turn_tokens = pt.get("input_tokens", 0) + turn_output
            turn_context = compute_context_tokens(pt)
            break

    has_violations = turn_num in violations_map
    prompt_preview = _get_turn_prompt_preview(steps)
    turn_type = _get_turn_type(steps)

    type_colors = {
        "system": "blue",
        "user": "primary",
        "response": "green",
        "tool_use": "orange",
        "scan_only": "yellow",
        "error": "red",
    }
    type_color = type_colors.get(turn_type, "grey")

    icon_map = {
        "system": ("settings", "text-blue"),
        "user": ("person", "text-blue"),
        "response": ("smart_toy", "text-green"),
        "tool_use": ("build", "text-orange"),
        "scan_only": (None, "text-yellow"),
        "error": ("error_outline", "text-red"),
    }
    icon_name, icon_color = icon_map.get(turn_type, ("help", "text-grey-6"))
    turn_label = _get_turn_label(steps, turn_type)

    turn_violations = _collect_turn_violations(steps)
    has_error = any(s.get("type") == "error" for s in steps)

    with ui.card().classes("w-full py-1 px-2"):
        with ui.row().classes("items-center gap-2 w-full"):
            if icon_name is None:
                render_guardian_icon()
            else:
                ui.icon(icon_name).classes(f"{icon_color} text-sm")
            ui.label(f"Turn {turn_num}").classes("text-xs font-bold w-16")
            ui.label(turn_label).classes(f"text-xs font-bold {icon_color}")

            if turn_context > 0:
                ui.label(
                    f"Context: {format_token_count(turn_context)} | "
                    f"Output: {format_token_count(turn_output)}"
                ).classes("text-xs text-grey-6")
            elif turn_tokens > 0:
                ui.label(f"{turn_tokens:,} tok").classes("text-xs text-grey-6")

            if has_error:
                ui.badge("ERROR", color="red").classes("text-xs")

            if has_violations:
                vc = len(violations_map[turn_num].get("violations", []))
                ui.badge(
                    f"{vc} violation{'s' if vc != 1 else ''}",
                    color="red",
                ).classes("text-xs")

            ui.label(prompt_preview).classes("text-xs text-grey-4 flex-grow").style(
                "white-space: nowrap; overflow: hidden; text-overflow: ellipsis"
            )

        is_open = expanded_turns is not None and turn_num in expanded_turns
        exp = ui.expansion(value=is_open).classes("w-full").props("dense")

        with exp.add_slot("header"):
            with ui.row().classes("items-center gap-1"):
                ui.label(f"Steps ({len(steps)})").classes("text-sm")
                for v, step_num in turn_violations:
                    _render_step_violation_badge(
                        v, step_num, turn_num, exp, daemon_name
                    )

        def _on_toggle(e, tn=turn_num):
            if expanded_turns is not None:
                if e.value:
                    expanded_turns.add(tn)
                else:
                    expanded_turns.discard(tn)

        exp.on_value_change(_on_toggle)

        with exp:
            for step in steps:
                _render_step(step, daemon_name, turn_num, dialog_host)


def _get_turn_label(steps, turn_type):
    """Build a descriptive label for the turn header."""
    if turn_type == "error":
        for s in steps:
            if s.get("type") == "error":
                return f"Error: {s.get('message', 'unknown')[:80]}"
        return "Error"
    if turn_type == "system":
        return "System"
    if turn_type == "user":
        return "User"
    if turn_type == "tool_use":
        tool_names = [s.get("name", "") for s in steps if s.get("type") == "tool_call"]
        tool_names = [n for n in tool_names if n]
        if tool_names:
            unique = list(dict.fromkeys(tool_names))
            return f"Tool Call: {', '.join(unique[:3])}"
        return "Tool Use"
    if turn_type == "response":
        return "Assistant"
    if turn_type == "scan_only":
        scanned = [s.get("scanned", "") for s in steps if s.get("type") == "scan"]
        scanned = [s for s in scanned if s]
        if scanned:
            return f"Scan: {', '.join(scanned[:2])}"
        return "Scan"
    return turn_type.title()


def _get_turn_type(steps):
    types = {s.get("type") for s in steps}
    if "error" in types:
        return "error"
    if "system" in types:
        return "system"
    if "response" in types:
        if any(s.get("type") == "tool_call" for s in steps):
            return "tool_use"
        return "response"
    # Hook traces do not contain model response events, but their tool calls
    # are still the primary activity for the turn.  Classify them before the
    # prompt/input fallback so the Sessions page does not call them scan-only.
    if "tool_call" in types:
        return "tool_use"
    if "input" in types or "prompt" in types:
        return "user"
    return "scan_only"


def _get_turn_prompt_preview(steps):
    for step in steps:
        if step.get("type") == "error":
            return _truncate(step.get("message", ""), 120)

    for step in steps:
        if step.get("type") == "system":
            prompt = step.get("user_prompt") or step.get("system_prompt") or ""
            return _truncate(prompt, 120)

    for step in steps:
        if step.get("type") == "response":
            text = step.get("text", "")
            if text:
                return _truncate(text, 120)

    for step in steps:
        if step.get("type") == "prompt":
            return _truncate(step.get("text", ""), 120)

    for step in steps:
        if step.get("type") == "tool_call":
            name = step.get("name", "")
            return f"tool: {name}"

    for step in steps:
        if step.get("type") == "scan":
            violations = step.get("violations", [])
            if violations:
                return f"violation: {violations[0].get('type', '')}"

    return ""


def _render_step_violation_badge(
    violation, step_num, turn_num, expansion, daemon_name=""
):
    """Render a clickable violation badge in the Steps header."""
    vtype = violation.get("type", violation.get("violation_type", "unknown"))
    vid = violation.get("id", "")
    action = violation.get("action", "block")
    color = "red" if action == "block" else "orange"

    step_el_id = f"step-{turn_num}-{step_num}"
    badge = ui.badge(vtype, color=color).classes("text-xs cursor-pointer")
    if vid:
        badge.tooltip(vid)

    async def _scroll_to_step(exp=expansion, sid=step_el_id):
        if not exp.value:
            exp.set_value(True)
            await ui.run_javascript("await new Promise(r => setTimeout(r, 100))")
        await ui.run_javascript(
            f"document.getElementById('{sid}')"
            f"?.scrollIntoView({{behavior: 'smooth', block: 'center'}})"
        )

    badge.on("click.stop", _scroll_to_step)


def _get_tool_result_output(step):
    """Return output from either the SDK or legacy hook trace schema."""
    return step.get("output", step.get("content", ""))


def _format_tool_result_output(output):
    """Format structured tool results as valid, readable JSON."""
    if isinstance(output, dict):
        return json.dumps(output, indent=2, default=str)
    return str(output)


def _render_step(step, daemon_name="", turn_num=0, dialog_host=None):
    step_type = step.get("type", "")
    step_num = step.get("step", 0)
    icon_map = {
        "system": ("settings", "text-blue"),
        "input": ("input", "text-grey-6"),
        "prompt": ("person", "text-blue"),
        "response": ("chat", "text-green"),
        "tool_call": ("build", "text-orange"),
        "tool_result": ("output", "text-orange"),
        "scan": (None, "text-yellow"),
        "compaction": ("compress", "text-purple"),
        "error": ("error_outline", "text-red"),
    }
    icon_name, icon_color = icon_map.get(step_type, ("help", "text-grey-6"))

    step_el_id = f"step-{turn_num}-{step_num}"
    with ui.element("div").props(f'id="{step_el_id}"'):
        with ui.row().classes("items-start gap-2 py-1"):
            if icon_name is None:
                render_guardian_icon("mt-1")
            else:
                ui.icon(icon_name).classes(f"{icon_color} text-xs mt-1")
            with ui.column().classes("gap-0 w-full"):
                if step_type == "system":
                    ui.label(f"Step {step_num}: system prompt").classes(
                        "text-xs font-bold"
                    )
                    prompt = step.get("user_prompt", "")
                    if prompt:
                        _render_text_block(prompt)
                    sys_prompt = step.get("system_prompt", "")
                    if sys_prompt:
                        _render_text_block(f"System: {sys_prompt}")
                elif step_type == "prompt":
                    text = step.get("text", "")
                    ui.label(f"Step {step_num}: user prompt").classes(
                        "text-xs font-bold"
                    )
                    if text:
                        if len(text) > 200 or text.count("\n") > 5:
                            render_view_button("User Prompt", text, dialog_host)
                        _render_text_block(text)
                elif step_type == "response":
                    text = step.get("text", "")
                    signal = step.get("model_signal", "")
                    usage = step.get("usage", {})
                    tok_info = ""
                    if usage:
                        ctx = compute_context_tokens(usage)
                        to = usage.get("output_tokens", 0)
                        if ctx:
                            tok_info = (
                                f" (Context: {format_token_count(ctx)}"
                                f" | Output: {format_token_count(to)})"
                            )
                        else:
                            ti = usage.get("input_tokens", 0)
                            tok_info = f" ({ti + to:,} tok)"
                    ui.label(f"Step {step_num}: response [{signal}]{tok_info}").classes(
                        "text-xs font-bold"
                    )
                    if text:
                        if len(text) > 200 or text.count("\n") > 5:
                            render_view_button(
                                f"Response [{signal}]", text, dialog_host
                            )
                        _render_text_block(text)
                elif step_type == "tool_call":
                    name = step.get("name", "")
                    ui.label(f"Step {step_num}: tool_call {name}").classes(
                        "text-xs font-bold"
                    )
                    inp = step.get("input", {})
                    inp_text = (
                        json.dumps(inp, indent=2, default=str)
                        if isinstance(inp, dict)
                        else str(inp)
                    )
                    if len(inp_text) > 200 or inp_text.count("\n") > 5:
                        render_view_button(f"Tool Call: {name}", inp_text, dialog_host)
                    _render_text_block(inp_text)
                elif step_type == "tool_result":
                    name = step.get("name", "")
                    # Hook traces originally used ``content`` while SDK traces
                    # use ``output``.  Read both so existing trace files remain
                    # fully visible after the unified Sessions rollout.
                    output = _get_tool_result_output(step)
                    ui.label(f"Step {step_num}: tool_result {name}").classes(
                        "text-xs font-bold"
                    )
                    if output:
                        output_text = _format_tool_result_output(output)
                        if len(output_text) > 200 or output_text.count("\n") > 5:
                            render_view_button(
                                f"Tool Result: {name}", output_text, dialog_host
                            )
                        _render_text_block(output_text)
                elif step_type == "scan":
                    scanned = step.get("scanned", "")
                    violations = step.get("violations", [])
                    if violations:
                        ui.label(f"Step {step_num}: scan {scanned}").classes(
                            "text-xs font-bold text-red"
                        )
                        for v in violations:
                            render_violation_badge(v, daemon_name)
                    else:
                        ui.label(f"Step {step_num}: scan {scanned} (clean)").classes(
                            "text-xs"
                        )
                elif step_type == "error":
                    msg = step.get("message", "")
                    ui.label(f"Step {step_num}: error").classes(
                        "text-xs font-bold text-red"
                    )
                    if msg:
                        _render_text_block(msg)
                elif step_type == "compaction":
                    before = step.get("tokens_before", 0)
                    after = step.get("tokens_after", 0)
                    ui.label(
                        f"Step {step_num}: compaction {before:,} -> {after:,}"
                    ).classes("text-xs font-bold text-purple")
                else:
                    ui.label(f"Step {step_num}: {step_type}").classes("text-xs")


def _truncate(text, max_len=120):
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


_render_text_block = render_text_block
_format_duration = format_duration
