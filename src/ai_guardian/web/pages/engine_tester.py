"""Engine Tester page — test strings against scanner engines."""

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar

STRATEGY_OPTIONS = {
    "from-config": "From Config",
    "first-match": "First Match",
    "any-match": "Any Match",
    "consensus": "Consensus",
}


def _get_engines():
    try:
        from ai_guardian.scanners.engine_tester import get_available_engines

        return get_available_engines()
    except Exception:
        return []


def _get_strategy():
    try:
        from ai_guardian.scanners.engine_tester import get_configured_strategy

        return get_configured_strategy()
    except Exception:
        return "first-match"


def _run_single_test(engine_name, text, use_pattern_server):
    from ai_guardian.scanners.engine_tester import test_engine

    return test_engine(engine_name, text, use_pattern_server)


def _run_all_tests(text, use_pattern_server):
    from ai_guardian.scanners.engine_tester import test_all_engines

    return test_all_engines(text, use_pattern_server)


def _run_strategy(strategy_name, results):
    from ai_guardian.scanners.engine_tester import apply_strategy

    if strategy_name == "from-config":
        strategy_name = _get_strategy()
    return apply_strategy(strategy_name, results)


def create_engine_tester_page(service, daemon_name: str):
    """Create the Engine Tester page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/engine-tester")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Engine Tester").classes("text-2xl font-bold")
        ui.label("Test strings against installed scanner engines.").classes(
            "text-xs text-grey-6"
        )

        with ui.card().classes("w-full"):
            ui.label("Configuration").classes("text-lg font-bold")

            engines = _get_engines()
            engine_options = {e: e for e in engines} if engines else {}

            with ui.row().classes("items-center gap-4 flex-wrap"):
                engine_sel = ui.select(
                    label="Engine",
                    options=engine_options,
                    value=engines[0] if engines else None,
                ).classes("w-48")

                strategy_sel = ui.select(
                    label="Strategy",
                    options=STRATEGY_OPTIONS,
                    value="from-config",
                ).classes("w-48")

                ps_check = ui.checkbox("Use pattern server config", value=False)

            text_input = (
                ui.textarea(
                    label="Test String",
                    placeholder=(
                        "Enter text to scan for secrets...\n"
                        "Example: pk_test_1234567890abcdef"  # nosecret
                    ),
                )
                .props("outlined")
                .classes("w-full")
                .style("font-family: monospace; min-height: 150px")
            )

        results_container = ui.column().classes("w-full gap-4")

        async def do_test():
            if not engine_sel.value:
                ui.notify("No engine selected", type="negative")
                return
            txt = text_input.value or ""
            if not txt:
                ui.notify("Enter test text", type="negative")
                return

            ui.notify("Testing...", type="info")
            result = await run.io_bound(
                _run_single_test,
                engine_sel.value,
                txt,
                ps_check.value,
            )

            results_container.clear()
            with results_container:
                with ui.card().classes("w-full"):
                    ui.label("Result").classes("text-lg font-bold")
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f"Engine: {result.engine}").classes(
                            "font-bold text-sm"
                        )
                        if result.found:
                            ui.badge("FOUND", color="red").classes("text-sm")
                        else:
                            ui.badge("NOT FOUND", color="green").classes("text-sm")
                        ui.label(f"{result.scan_time_ms:.0f}ms").classes(
                            "text-xs text-grey-6"
                        )
                        mode_color = {"listen": "green", "daemon": "blue"}.get(
                            result.scan_mode, "grey"
                        )
                        ui.badge(result.scan_mode, color=mode_color).classes("text-xs")

                    if result.error:
                        ui.label(f"Error: {result.error}").classes("text-sm text-red")

                    if result.secrets:
                        ui.label(f"Secrets ({len(result.secrets)}):").classes(
                            "font-bold text-sm mt-2"
                        )
                        for s in result.secrets:
                            with ui.row().classes("items-center gap-2 ml-4"):
                                ui.icon("key").classes("text-amber")
                                rule = getattr(s, "rule_id", "unknown")
                                desc = getattr(s, "description", "")
                                ui.label(rule).classes("text-sm font-bold").style(
                                    "font-family: monospace"
                                )
                                if desc:
                                    ui.label(desc).classes("text-xs text-grey-6")

        async def do_test_all():
            txt = text_input.value or ""
            if not txt:
                ui.notify("Enter test text", type="negative")
                return

            ui.notify("Testing all engines...", type="info")
            results = await run.io_bound(_run_all_tests, txt, ps_check.value)

            results_container.clear()
            with results_container:
                with ui.card().classes("w-full"):
                    ui.label("All Engines").classes("text-lg font-bold")

                    rows = []
                    for r in results:
                        rows.append(
                            {
                                "engine": r.engine,
                                "found": "FOUND" if r.found else "NOT FOUND",
                                "secrets": len(r.secrets),
                                "time_ms": r.scan_time_ms,
                                "mode": r.scan_mode,
                                "error": r.error or "",
                            }
                        )

                    ui.table(
                        columns=[
                            {
                                "name": "engine",
                                "label": "Engine",
                                "field": "engine",
                            },
                            {"name": "found", "label": "Result", "field": "found"},
                            {
                                "name": "secrets",
                                "label": "Secrets",
                                "field": "secrets",
                            },
                            {
                                "name": "time_ms",
                                "label": "Time (ms)",
                                "field": "time_ms",
                            },
                            {"name": "mode", "label": "Mode", "field": "mode"},
                            {"name": "error", "label": "Error", "field": "error"},
                        ],
                        rows=rows,
                        row_key="engine",
                    ).classes("w-full")

                strategy = strategy_sel.value
                verdict = await run.io_bound(_run_strategy, strategy, results)
                if verdict:
                    with ui.card().classes("w-full"):
                        ui.label("Strategy Verdict").classes("text-lg font-bold")
                        with ui.row().classes("items-center gap-2"):
                            ui.label(f"Strategy: {verdict.strategy}").classes("text-sm")
                            if verdict.blocked:
                                ui.badge("BLOCKED", color="red").classes("text-sm")
                            else:
                                ui.badge("ALLOWED", color="green").classes("text-sm")
                            ui.label(
                                f"Engines with secrets: "
                                f"{verdict.engines_with_secrets}/"
                                f"{verdict.total_engines}"
                            ).classes("text-xs text-grey-6")

        with ui.row().classes("gap-2"):
            ui.button(
                "Test Engine",
                icon="play_arrow",
                on_click=do_test,
            ).props("dense")
            ui.button(
                "Test All",
                icon="playlist_play",
                on_click=do_test_all,
            ).props("dense")
