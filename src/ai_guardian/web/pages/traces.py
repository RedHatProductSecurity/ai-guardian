"""Trace Viewer page — conversation traces from GuardedAgent runs."""

import fnmatch
import json
import tempfile
import urllib.parse

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.step_render import (
    escape_html,
    format_duration,
    render_text_block,
    render_violation_badge,
)


def create_traces_page(service, daemon_name: str):
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/traces")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Trace Viewer").classes("text-2xl font-bold")
        ui.label("Conversation traces from GuardedAgent runs.").classes(
            "text-xs text-grey-6"
        )

        try:
            from nicegui import app as _app

            saved_sort = _app.storage.user.get("traces_sort_newest", True)
        except Exception:
            saved_sort = True

        state = {"load_fn": None, "newest_first": saved_sort}

        with ui.row().classes("items-end gap-4 w-full"):
            filter_input = ui.input(
                label="Filter filenames",
                placeholder="Wildcard: *, ?  e.g. triage-*",
            ).classes("flex-grow")

            agent_select = ui.select(
                options={"": "All Agents"},
                value="",
                label="Agent",
            ).classes("w-48")

            async def _on_refresh():
                fn = state["load_fn"]
                if fn:
                    await fn()

            ui.button("Refresh", icon="refresh", on_click=_on_refresh).props(
                "dense outline"
            )

            async def _toggle_sort():
                state["newest_first"] = not state["newest_first"]
                sort_btn.text = (
                    "Showing: Newest ↓"
                    if state["newest_first"]
                    else "Showing: Oldest ↑"
                )
                try:
                    from nicegui import app as _app2

                    _app2.storage.user["traces_sort_newest"] = state["newest_first"]
                except Exception:
                    pass
                fn = state["load_fn"]
                if fn:
                    await fn()

            sort_btn = ui.button(
                "Showing: Newest ↓" if state["newest_first"] else "Showing: Oldest ↑",
                on_click=_toggle_sort,
            ).props("dense outline")

        cards_container = ui.column().classes("w-full gap-2")
        auto_timer = {"ref": None}

        async def load_traces():
            try:
                if ui.context.client.is_deleted:
                    return
                await run.io_bound(service.refresh_targets)
                target = service.get_target_by_name(daemon_name)
                if not target:
                    cards_container.clear()
                    with cards_container:
                        ui.label("Daemon not available.").classes("text-grey-6")
                    return

                agent_filter = agent_select.value or None
                result = await run.io_bound(
                    service.get_daemon_traces, target, agent_filter, None
                )

                traces = (result or {}).get("traces", [])
                pattern = filter_input.value.strip() if filter_input.value else None
                if pattern:
                    traces = _filter_traces(traces, pattern)
                traces.sort(
                    key=lambda t: t.get("started_at", ""),
                    reverse=state["newest_first"],
                )
                _populate_agent_filter(traces, agent_select)
                _render_trace_list(traces, cards_container, daemon_name)

                if auto_timer["ref"] is None:
                    interval = _get_auto_refresh_interval(service, target)
                    auto_timer["ref"] = ui.timer(interval, load_traces)
            except Exception as exc:
                cards_container.clear()
                with cards_container:
                    ui.label(f"Error: {exc}").classes("text-red")

        state["load_fn"] = load_traces
        ui.timer(0.1, load_traces, once=True)


def create_trace_detail_page(service, daemon_name: str):
    """Detail page for a single trace conversation."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/traces")
    create_header(daemon_name, drawer=sidebar)

    params = dict(ui.context.client.request.query_params)
    filename = params.get("file", "")

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

        try:
            from nicegui import app as _app

            saved_sort = _app.storage.user.get("trace_detail_sort_newest", False)
        except Exception:
            saved_sort = False

        summary_container = ui.column().classes("w-full")
        export_container = ui.row().classes("w-full gap-2 items-center")
        turns_container = ui.column().classes("w-full gap-1")
        scroll_anchor = ui.element("div")
        expanded_turns: set = set()
        detail_state = {"result": None, "newest_first": saved_sort}

        async def _export_otlp_json():
            result = detail_state["result"]
            if not result:
                ui.notify("No trace loaded", type="warning")
                return
            try:
                from ai_guardian.scanners.otel_exporter import trace_to_otlp_json

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

                from ai_guardian.scanners.otel_exporter import trace_to_otlp_json

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

        async def load_detail():
            if ui.context.client.is_deleted:
                return
            await run.io_bound(service.refresh_targets)
            target = service.get_target_by_name(daemon_name)
            if not target:
                header_label.text = "Daemon not available"
                return

            result = await run.io_bound(
                service.get_daemon_trace_detail, target, filename, None
            )
            if not result or result.get("error"):
                header_label.text = "Trace not found"
                with turns_container:
                    turns_container.clear()
                    err = (result or {}).get("error", "Failed to load trace")
                    ui.label(err).classes("text-red")
                return

            detail_state["result"] = result
            agent_name = result.get("agent_name", "")
            model = result.get("model", "")
            stop_reason = result.get("stop_reason", "")
            is_active = result.get("is_active", False)

            header_label.text = f"{agent_name} ({model})"

            summary_container.clear()
            with summary_container:
                with ui.row().classes("items-center gap-2"):
                    if is_active:
                        ui.badge("ACTIVE", color="green").classes("text-xs")
                    else:
                        ui.badge(stop_reason or "done", color="grey").classes("text-xs")
                    started = (result.get("started_at") or "")[:19]
                    ui.label(f"Started: {started}").classes("text-xs text-grey-6")

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
                with ui.row().classes("items-center gap-2"):
                    ui.label("Turns").classes("text-lg font-bold")

                    async def _toggle_trace_detail_sort():
                        detail_state["newest_first"] = not detail_state["newest_first"]
                        trace_detail_sort_btn.text = (
                            "Showing: Newest ↓"
                            if detail_state["newest_first"]
                            else "Showing: Oldest ↑"
                        )
                        try:
                            from nicegui import app as _app2

                            _app2.storage.user["trace_detail_sort_newest"] = (
                                detail_state["newest_first"]
                            )
                        except Exception:
                            pass
                        await load_detail()

                    trace_detail_sort_btn = ui.button(
                        (
                            "Showing: Newest ↓"
                            if detail_state["newest_first"]
                            else "Showing: Oldest ↑"
                        ),
                        on_click=_toggle_trace_detail_sort,
                    ).props("dense outline")

                for turn_obj in trace:
                    _render_turn_row(
                        turn_obj, per_turn, violations_map, expanded_turns, daemon_name
                    )

            await ui.run_javascript(
                "(() => {"
                "  const threshold = 150;"
                "  const atBottom = (window.innerHeight + window.scrollY) "
                ">= (document.body.scrollHeight - threshold);"
                "  if (atBottom) window.scrollTo("
                "{top: document.body.scrollHeight, behavior: 'smooth'});"
                "})()"
            )

            if auto_timer["ref"] is None:
                interval = _get_auto_refresh_interval(service, target)
                auto_timer["ref"] = ui.timer(interval, load_detail)

        auto_timer = {"ref": None}
        ui.timer(0.1, load_detail, once=True)


def _get_auto_refresh_interval(service, target):
    try:
        cfg = service.get_daemon_config(target) or {}
        return (
            cfg.get("sdk", {})
            .get("trace_viewer", {})
            .get("auto_refresh_interval_seconds", 5)
        )
    except Exception:
        return 5


def _filter_traces(traces, pattern):
    """Filter traces by filename using fnmatch wildcard pattern."""
    if not pattern.startswith("*"):
        pattern = f"*{pattern}*"
    return [t for t in traces if fnmatch.fnmatch(t.get("filename", ""), pattern)]


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


def _render_trace_list(traces, container, daemon_name):
    container.clear()
    if not traces:
        with container:
            ui.label("No trace files found.").classes("text-grey-6")
        return

    with container:
        for t in traces:
            _render_trace_card(t, daemon_name)


def _render_trace_card(trace, daemon_name):
    agent_name = trace.get("agent_name", "unknown")
    model = trace.get("model", "")
    is_active = trace.get("is_active", False)
    stop_reason = trace.get("stop_reason", "")
    started_at = (trace.get("started_at") or "")[:19]
    total_turns = trace.get("total_turns", 0)
    violation_count = trace.get("violation_count", 0)
    filename = trace.get("filename", "")

    tokens = trace.get("total_tokens", {})
    total_input = tokens.get("input_tokens", 0)
    total_output = tokens.get("output_tokens", 0)
    total_tok = total_input + total_output

    duration = trace.get("duration_seconds", 0)
    duration_str = _format_duration(duration)

    detail_params = f"?file={urllib.parse.quote(filename, safe='/')}"
    detail_url = f"/{daemon_name}/trace-detail{detail_params}"

    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 w-full"):
            if is_active:
                ui.icon("fiber_manual_record").classes("text-green text-xs")
            else:
                ui.icon("check_circle").classes("text-grey-6 text-xs")

            ui.link(agent_name, detail_url).classes(
                "font-bold text-sm text-blue-4 hover:text-blue-3"
            ).style("text-decoration: underline dotted; text-underline-offset: 3px")
            ui.label(f"({model})").classes("text-xs text-grey-6")

            if is_active:
                ui.badge("ACTIVE", color="green").classes("text-xs")
            else:
                ui.badge(stop_reason or "done", color="grey").classes("text-xs")

            if violation_count > 0:
                ui.badge(
                    f"{violation_count} violation{'s' if violation_count != 1 else ''}",
                    color="red",
                ).classes("text-xs")

        with ui.grid(columns=4).classes("gap-1 mt-1"):
            ui.label("Started:").classes("text-xs text-grey-6")
            ui.label(started_at).classes("text-xs")
            ui.label("Turns:").classes("text-xs text-grey-6")
            ui.label(str(total_turns)).classes("text-xs")
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
    total_tok = total.get("input_tokens", 0) + total.get("output_tokens", 0)

    with ui.card().classes("w-full bg-grey-9 mt-2"):
        ui.label("Summary").classes("text-sm font-bold")
        with ui.grid(columns=6).classes("gap-1"):
            ui.label("Turns:").classes("text-xs text-grey-6")
            ui.label(str(total_turns)).classes("text-xs")
            ui.label("Duration:").classes("text-xs text-grey-6")
            ui.label(duration_str).classes("text-xs")
            ui.label("Total:").classes("text-xs text-grey-6")
            ui.label(f"{total_tok:,}").classes("text-xs")
            ui.label("Input:").classes("text-xs text-grey-6")
            ui.label(f"{total.get('input_tokens', 0):,}").classes("text-xs")
            ui.label("Output:").classes("text-xs text-grey-6")
            ui.label(f"{total.get('output_tokens', 0):,}").classes("text-xs")
            ui.label("Cache Hit:").classes("text-xs text-grey-6")
            ui.label(f"{cache_ratio:.1%}").classes("text-xs")
            ui.label("Cache Read:").classes("text-xs text-grey-6")
            ui.label(f"{total.get('cache_read_input_tokens', 0):,}").classes("text-xs")
            ui.label("Cache Create:").classes("text-xs text-grey-6")
            ui.label(f"{total.get('cache_creation_input_tokens', 0):,}").classes(
                "text-xs"
            )


def _render_turn_row(
    turn_obj, per_turn, violations_map, expanded_turns=None, daemon_name=""
):
    """Render a single turn as a row with summary and expandable details."""
    turn_num = turn_obj.get("turn", 0)
    steps = turn_obj.get("steps", [])

    turn_tokens = 0
    for pt in per_turn:
        if pt.get("turn") == turn_num:
            turn_tokens = pt.get("input_tokens", 0) + pt.get("output_tokens", 0)
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
    }
    type_color = type_colors.get(turn_type, "grey")

    icon_map = {
        "system": ("settings", "text-blue"),
        "user": ("person", "text-blue"),
        "response": ("smart_toy", "text-green"),
        "tool_use": ("build", "text-orange"),
        "scan_only": ("security", "text-yellow"),
    }
    icon_name, icon_color = icon_map.get(turn_type, ("help", "text-grey-6"))
    turn_label = _get_turn_label(steps, turn_type)

    with ui.card().classes("w-full py-1 px-2"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.icon(icon_name).classes(f"{icon_color} text-sm")
            ui.label(f"Turn {turn_num}").classes("text-xs font-bold w-16")
            ui.label(turn_label).classes(f"text-xs font-bold {icon_color}")

            if turn_tokens > 0:
                ui.label(f"{turn_tokens:,} tok").classes("text-xs text-grey-6")

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
        exp = ui.expansion("Steps", value=is_open).classes("w-full").props("dense")

        def _on_toggle(e, tn=turn_num):
            if expanded_turns is not None:
                if e.value:
                    expanded_turns.add(tn)
                else:
                    expanded_turns.discard(tn)

        exp.on_value_change(_on_toggle)

        with exp:
            for step in steps:
                _render_step(step, daemon_name)


def _get_turn_label(steps, turn_type):
    """Build a descriptive label for the turn header."""
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
    if "system" in types:
        return "system"
    if "response" in types:
        if any(s.get("type") == "tool_call" for s in steps):
            return "tool_use"
        return "response"
    if "input" in types:
        return "user"
    return "scan_only"


def _get_turn_prompt_preview(steps):
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
        if step.get("type") == "tool_call":
            name = step.get("name", "")
            return f"tool: {name}"

    for step in steps:
        if step.get("type") == "scan":
            violations = step.get("violations", [])
            if violations:
                return f"violation: {violations[0].get('type', '')}"

    return ""


def _render_step(step, daemon_name=""):
    step_type = step.get("type", "")
    step_num = step.get("step", 0)
    icon_map = {
        "system": ("settings", "text-blue"),
        "input": ("input", "text-grey-6"),
        "response": ("chat", "text-green"),
        "tool_call": ("build", "text-orange"),
        "tool_result": ("output", "text-orange"),
        "scan": ("security", "text-yellow"),
        "compaction": ("compress", "text-purple"),
    }
    icon_name, icon_color = icon_map.get(step_type, ("help", "text-grey-6"))

    with ui.row().classes("items-start gap-2 py-1"):
        ui.icon(icon_name).classes(f"{icon_color} text-xs mt-1")
        with ui.column().classes("gap-0 w-full"):
            if step_type == "system":
                ui.label(f"Step {step_num}: system prompt").classes("text-xs font-bold")
                prompt = step.get("user_prompt", "")
                if prompt:
                    _render_text_block(prompt)
                sys_prompt = step.get("system_prompt", "")
                if sys_prompt:
                    _render_text_block(f"System: {sys_prompt}")
            elif step_type == "response":
                text = step.get("text", "")
                signal = step.get("model_signal", "")
                usage = step.get("usage", {})
                tok_info = ""
                if usage:
                    ti = usage.get("input_tokens", 0)
                    to = usage.get("output_tokens", 0)
                    tok_info = f" ({ti + to:,} tok)"
                ui.label(f"Step {step_num}: response [{signal}]{tok_info}").classes(
                    "text-xs font-bold"
                )
                if text:
                    _render_text_block(text)
            elif step_type == "tool_call":
                name = step.get("name", "")
                ui.label(f"Step {step_num}: tool_call {name}").classes(
                    "text-xs font-bold"
                )
                inp = step.get("input", {})
                _render_text_block(str(inp))
            elif step_type == "tool_result":
                name = step.get("name", "")
                output = step.get("output", "")
                ui.label(f"Step {step_num}: tool_result {name}").classes(
                    "text-xs font-bold"
                )
                if output:
                    _render_text_block(str(output))
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
_escape_html = escape_html
_format_duration = format_duration
