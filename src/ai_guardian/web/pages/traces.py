"""Trace Viewer page — conversation traces from GuardedAgent runs."""

import urllib.parse

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar


def create_traces_page(service, daemon_name: str):
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/traces")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Trace Viewer").classes("text-2xl font-bold")
        ui.label("Conversation traces from GuardedAgent runs.").classes(
            "text-xs text-grey-6"
        )

        state = {"load_fn": None}

        with ui.row().classes("items-end gap-4 w-full"):
            dir_input = ui.input(
                label="Trace directory (optional)",
                placeholder="Auto-discovered from config",
            ).classes("flex-grow")

            from ai_guardian.web.pages.directory_scan import _open_browse_dialog

            ui.button(
                icon="folder_open",
                on_click=lambda: _open_browse_dialog(dir_input),
            ).props("dense outline")

            agent_select = ui.select(
                options={"": "All Agents"},
                value="",
                label="Agent",
            ).classes("w-48")

            async def _on_refresh():
                if state["load_fn"]:
                    await state["load_fn"]()

            ui.button("Refresh", icon="refresh", on_click=_on_refresh).props(
                "dense outline"
            )

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
                custom_dir = dir_input.value.strip() if dir_input.value else None
                result = await run.io_bound(
                    service.get_daemon_traces, target, agent_filter, custom_dir
                )

                traces = (result or {}).get("traces", [])
                _populate_agent_filter(traces, agent_select)
                _render_trace_list(traces, cards_container, daemon_name, custom_dir)

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
    directory = params.get("directory")

    with ui.column().classes("flex-grow p-6 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.button(
                icon="arrow_back",
                on_click=lambda: _go_back(daemon_name, directory),
            ).props("dense flat")
            header_label = ui.label("Loading...").classes("text-2xl font-bold")

        ui.label(filename).classes("text-xs text-grey-6").style(
            "font-family: monospace; word-break: break-all"
        )

        summary_container = ui.column().classes("w-full")
        turns_container = ui.column().classes("w-full gap-1")
        scroll_anchor = ui.element("div")
        expanded_turns: set = set()

        async def load_detail():
            if ui.context.client.is_deleted:
                return
            await run.io_bound(service.refresh_targets)
            target = service.get_target_by_name(daemon_name)
            if not target:
                header_label.text = "Daemon not available"
                return

            result = await run.io_bound(
                service.get_daemon_trace_detail, target, filename, directory
            )
            if not result or result.get("error"):
                header_label.text = "Trace not found"
                with turns_container:
                    turns_container.clear()
                    err = (result or {}).get("error", "Failed to load trace")
                    ui.label(err).classes("text-red")
                return

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
                _render_token_summary(computed)

            trace = result.get("trace", [])
            computed = result.get("computed", {})
            per_turn = computed.get("per_turn_tokens", [])
            violations_map = {v["turn"]: v for v in computed.get("violations", [])}

            turns_container.clear()
            with turns_container:
                ui.label("Turns").classes("text-lg font-bold")
                for turn_obj in trace:
                    _render_turn_row(turn_obj, per_turn, violations_map, expanded_turns)

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


def _go_back(daemon_name, directory):
    params = f"?directory={urllib.parse.quote(directory, safe='')}" if directory else ""
    ui.navigate.to(f"/{daemon_name}/traces{params}")


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


def _render_trace_list(traces, container, daemon_name, directory=None):
    container.clear()
    if not traces:
        with container:
            ui.label("No trace files found.").classes("text-grey-6")
        return

    with container:
        for t in traces:
            _render_trace_card(t, daemon_name, directory)


def _render_trace_card(trace, daemon_name, directory=None):
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

    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 w-full"):
            if is_active:
                ui.icon("fiber_manual_record").classes("text-green text-xs")
            else:
                ui.icon("check_circle").classes("text-grey-6 text-xs")

            ui.label(agent_name).classes("font-bold text-sm")
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

        def _navigate(fn=filename, d=directory):
            params = f"?file={urllib.parse.quote(fn, safe='/')}"
            if d:
                params += f"&directory={urllib.parse.quote(d, safe='/')}"
            ui.navigate.to(f"/{daemon_name}/trace-detail{params}")

        ui.button(
            "View Details",
            icon="visibility",
            on_click=_navigate,
        ).props(
            "dense flat size=sm"
        ).classes("mt-1")


def _render_token_summary(computed):
    total = computed.get("total_tokens", {})
    cost = computed.get("cost_estimate_usd", 0)
    cache_ratio = computed.get("cache_hit_ratio", 0)

    with ui.card().classes("w-full bg-grey-9 mt-2"):
        ui.label("Token Summary").classes("text-sm font-bold")
        with ui.grid(columns=6).classes("gap-1"):
            ui.label("Input:").classes("text-xs text-grey-6")
            ui.label(f"{total.get('input_tokens', 0):,}").classes("text-xs")
            ui.label("Output:").classes("text-xs text-grey-6")
            ui.label(f"{total.get('output_tokens', 0):,}").classes("text-xs")
            ui.label("Cost:").classes("text-xs text-grey-6")
            ui.label(f"${cost:.4f}").classes("text-xs")
            ui.label("Cache Read:").classes("text-xs text-grey-6")
            ui.label(f"{total.get('cache_read_input_tokens', 0):,}").classes("text-xs")
            ui.label("Cache Create:").classes("text-xs text-grey-6")
            ui.label(f"{total.get('cache_creation_input_tokens', 0):,}").classes(
                "text-xs"
            )
            ui.label("Cache Hit:").classes("text-xs text-grey-6")
            ui.label(f"{cache_ratio:.1%}").classes("text-xs")


def _render_turn_row(turn_obj, per_turn, violations_map, expanded_turns=None):
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

    with ui.card().classes("w-full py-1 px-2"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.label(f"Turn {turn_num}").classes("text-xs font-bold w-16")
            ui.badge(turn_type, color=type_color).classes("text-xs")

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
                _render_step(step)


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


def _render_step(step):
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
        with ui.column().classes("gap-0"):
            if step_type == "system":
                ui.label(f"Step {step_num}: system prompt").classes("text-xs font-bold")
                prompt = step.get("user_prompt", "")
                if prompt:
                    ui.label(_truncate(prompt, 300)).classes("text-xs text-grey-6")
                sys_prompt = step.get("system_prompt", "")
                if sys_prompt:
                    ui.label(f"System: {_truncate(sys_prompt, 200)}").classes(
                        "text-xs text-grey-6"
                    )
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
                    ui.label(_truncate(text, 300)).classes("text-xs text-grey-6")
            elif step_type == "tool_call":
                name = step.get("name", "")
                ui.label(f"Step {step_num}: tool_call {name}").classes(
                    "text-xs font-bold"
                )
                inp = step.get("input", {})
                ui.label(_truncate(str(inp), 200)).classes("text-xs text-grey-6")
            elif step_type == "tool_result":
                name = step.get("name", "")
                output = step.get("output", "")
                ui.label(f"Step {step_num}: tool_result {name}").classes(
                    "text-xs font-bold"
                )
                if output:
                    ui.label(_truncate(str(output), 300)).classes("text-xs text-grey-6")
            elif step_type == "scan":
                scanned = step.get("scanned", "")
                violations = step.get("violations", [])
                if violations:
                    ui.label(f"Step {step_num}: scan {scanned}").classes(
                        "text-xs font-bold text-red"
                    )
                    for v in violations:
                        vtype = v.get("type", "unknown")
                        msg = v.get("message", "")
                        ui.label(f"  {vtype}: {_truncate(msg, 150)}").classes(
                            "text-xs text-red"
                        )
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


def _truncate(text, max_len=200):
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _format_duration(seconds):
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"
