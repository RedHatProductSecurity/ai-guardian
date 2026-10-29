"""Engine Configuration page — scanner engine settings and strategy."""

import asyncio
import json

from nicegui import run, ui

from ai_guardian.scanners.engine_builder import ENGINE_PRESETS, _PYTHON_SCANNER_PRESETS
from ai_guardian.scanners.secret_scanning import DEFAULT_ENGINES
from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.config_helpers import load_web_config, save_web_config

VALID_ENGINE_TYPES = set(ENGINE_PRESETS) | _PYTHON_SCANNER_PRESETS


def _engine_type(engine):
    if isinstance(engine, str):
        return engine
    if isinstance(engine, dict):
        engine_type = engine.get("type")
        return engine_type if isinstance(engine_type, str) else None
    return None


def _toggle_engine(engines, engine_name: str, selected: bool):
    """Add or remove one preset while preserving other advanced engine entries."""
    result = list(engines) if isinstance(engines, list) else list(DEFAULT_ENGINES)
    matching = [entry for entry in result if _engine_type(entry) == engine_name]

    if selected:
        if not matching:
            result.append(engine_name)
        return result

    return [entry for entry in result if _engine_type(entry) != engine_name]


def _get_installed_engine_names(service, daemon_name: str):
    """Read installed preset engines from the selected daemon's About response."""
    if service is None:
        return None
    target = service.get_target_by_name(daemon_name)
    if target is None:
        return None
    about = service.get_daemon_about(target)
    if not isinstance(about, dict):
        return None
    names = about.get("installed_scanners")
    if not isinstance(names, list):
        return None
    return {name for name in names if isinstance(name, str) and name in ENGINE_PRESETS}


async def _save_engine_selection(engine_name: str, selected: bool):
    """Persist one engine selection without replacing unrelated configuration."""
    config = await run.io_bound(load_web_config)
    secret_config = config.get("secret_scanning", {})
    if not isinstance(secret_config, dict):
        secret_config = {}

    engines = secret_config.get("engines", DEFAULT_ENGINES)
    updated_engines = _toggle_engine(engines, engine_name, selected)
    secret_config["engines"] = updated_engines
    config["secret_scanning"] = secret_config
    saved = await run.io_bound(save_web_config, config)
    return bool(saved), updated_engines


def _validate_engines_json(text):
    """Validate engines JSON, returning (parsed_list, error_string)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    if not isinstance(data, list):
        return None, "Engines must be a JSON array"
    for i, engine in enumerate(data):
        if isinstance(engine, str):
            if engine not in VALID_ENGINE_TYPES:
                return None, f"Engine {i}: unknown type '{engine}'"
        elif isinstance(engine, dict):
            etype = engine.get("type")
            if not etype:
                return None, f"Engine {i}: missing 'type' field"
            if etype not in VALID_ENGINE_TYPES:
                return None, f"Engine {i}: unknown type '{etype}'"
        else:
            return None, f"Engine {i}: must be a string or object"
    return data, None


def create_secret_engines_page(service, daemon_name: str):
    """Create the Engine Configuration page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/secret-engines")
    create_header(daemon_name, drawer=sidebar)
    config_save_lock = asyncio.Lock()

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Engine Configuration").classes("text-2xl font-bold")
        ui.label("Configure secret scanning engines and execution strategy.").classes(
            "text-xs text-grey-6"
        )

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)
            installed_engines = await run.io_bound(
                _get_installed_engine_names, service, daemon_name
            )

            with content:
                ss = config.get("secret_scanning", {})
                if not isinstance(ss, dict):
                    ss = {}
                strategy = ss.get("execution_strategy", "first-match")
                threshold = ss.get("consensus_threshold", 2)

                # Execution strategy
                with ui.card().classes("w-full"):
                    ui.label("Execution Strategy").classes("text-lg font-bold")
                    ui.label(
                        "How multiple scanner engines coordinate detection."
                    ).classes("text-xs text-grey-6")

                    strat_sel = ui.select(
                        options={
                            "first-match": "First Match — stop at first engine finding",
                            "any-match": "Any Match — block if ANY engine finds secrets",
                            "consensus": "Consensus — block if N engines agree",
                        },
                        value=strategy,
                    ).classes("w-96")

                    threshold_row = ui.row().classes("items-center gap-2")
                    with threshold_row:
                        ui.label("Consensus Threshold:").classes("text-sm")
                        thresh_input = (
                            ui.input(
                                value=str(threshold),
                            )
                            .props("dense outlined type=number")
                            .classes("w-24")
                        )
                    threshold_row.set_visibility(strategy == "consensus")

                    async def save_strategy(e):
                        async with config_save_lock:
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("secret_scanning", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            sect["execution_strategy"] = e.value
                            cfg["secret_scanning"] = sect
                            await run.io_bound(save_web_config, cfg)
                        threshold_row.set_visibility(e.value == "consensus")
                        ui.notify(f"Strategy: {e.value}", type="positive")

                    strat_sel.on_value_change(save_strategy)

                    async def save_threshold():
                        try:
                            val = int(thresh_input.value)
                        except (ValueError, TypeError):
                            ui.notify("Invalid threshold", type="negative")
                            return
                        async with config_save_lock:
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("secret_scanning", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            sect["consensus_threshold"] = val
                            cfg["secret_scanning"] = sect
                            await run.io_bound(save_web_config, cfg)
                        ui.notify(f"Threshold: {val}", type="positive")

                    ui.button(
                        "Save Threshold",
                        icon="save",
                        on_click=save_threshold,
                    ).props("dense flat").bind_visibility_from(threshold_row, "visible")

                # Engines editor
                with ui.card().classes("w-full"):
                    ui.label("Engines").classes("text-lg font-bold")
                    ui.label(
                        "The default engine list includes built-in TOML patterns. "
                        "Clear its checkbox to opt out; changes save automatically "
                        "to the selected configuration scope."
                    ).classes("text-xs text-grey-6")

                    engines = ss.get("engines", DEFAULT_ENGINES)
                    if not isinstance(engines, list):
                        engines = []
                    configured_names = {
                        name
                        for name in (_engine_type(engine) for engine in engines)
                        if name
                    }
                    selectable_names = (
                        {"toml-patterns"}
                        | (installed_engines or set())
                        | (configured_names & VALID_ENGINE_TYPES)
                    )

                    if installed_engines is None:
                        ui.label(
                            "Installed scanner inventory is unavailable from this "
                            "daemon. Existing selections are shown; other installed "
                            "engines cannot be added here."
                        ).classes("text-xs text-amber-9")

                    status_label = ui.label(
                        f"Valid JSON — {len(engines)} engine(s)"
                    ).classes("text-xs text-green")
                    engines_text = json.dumps(engines, indent=2)
                    json_dirty = False

                    for engine_name in [
                        "toml-patterns",
                        *sorted(ENGINE_PRESETS),
                    ]:
                        if engine_name not in selectable_names:
                            continue

                        if engine_name == "toml-patterns":
                            display_name = "Built-in TOML patterns"
                            availability = "built-in"
                        elif installed_engines is None:
                            display_name = engine_name
                            availability = "configured"
                        elif engine_name in installed_engines:
                            display_name = engine_name
                            availability = "installed"
                        else:
                            display_name = engine_name
                            availability = "configured, not detected as installed"

                        checkbox = ui.checkbox(
                            f"{display_name} ({availability})",
                            value=engine_name in configured_names,
                        ).props("dense")

                        async def on_engine_change(
                            event, name=engine_name, control=checkbox
                        ):
                            nonlocal json_dirty
                            selected = bool(event.value)
                            if json_dirty:
                                control.value = not selected
                                ui.notify(
                                    "Save or reload the advanced JSON before "
                                    "changing engine selections.",
                                    type="warning",
                                )
                                return

                            async with config_save_lock:
                                saved, updated = await _save_engine_selection(
                                    name, selected
                                )

                            if not saved:
                                control.value = not selected
                                ui.notify(
                                    "Engine selection could not be saved.",
                                    type="negative",
                                )
                                return

                            if (
                                not selected
                                and installed_engines is not None
                                and name != "toml-patterns"
                                and name not in installed_engines
                            ):
                                control.disable()

                            editor.value = json.dumps(updated, indent=2)
                            json_dirty = False
                            status_label.text = f"Valid JSON — {len(updated)} engine(s)"
                            status_label.classes(replace="text-xs text-green")
                            action = "added to" if selected else "removed from"
                            ui.notify(
                                f"{name} {action} secret scanning configuration",
                                type="positive",
                            )

                        checkbox.on_value_change(on_engine_change)

                    with ui.expansion("Advanced JSON editor", icon="code").classes(
                        "w-full"
                    ):
                        editor = (
                            ui.textarea(value=engines_text)
                            .props("outlined autogrow")
                            .classes("w-full")
                            .style("font-family: monospace; min-height: 150px")
                        )

                        def on_edit(e):
                            nonlocal json_dirty
                            json_dirty = True
                            parsed, err = _validate_engines_json(e.args)
                            if err:
                                status_label.text = err
                                status_label.classes(replace="text-xs text-red")
                            else:
                                status_label.text = (
                                    f"Valid JSON — {len(parsed)} engine(s)"
                                )
                                status_label.classes(replace="text-xs text-green")

                        editor.on("update:model-value", on_edit)

                        with ui.row().classes("gap-2 mt-2"):

                            async def save_engines():
                                nonlocal json_dirty
                                parsed, err = _validate_engines_json(editor.value)
                                if err:
                                    ui.notify(err, type="negative")
                                    return
                                async with config_save_lock:
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("secret_scanning", {})
                                    if not isinstance(sect, dict):
                                        sect = {}
                                    sect["engines"] = parsed
                                    cfg["secret_scanning"] = sect
                                    saved = await run.io_bound(save_web_config, cfg)
                                if not saved:
                                    ui.notify(
                                        "Engine configuration could not be saved.",
                                        type="negative",
                                    )
                                    return
                                json_dirty = False
                                await refresh()
                                ui.notify(
                                    f"Saved {len(parsed)} engine(s)",
                                    type="positive",
                                )

                            async def reload_engines():
                                await refresh()
                                ui.notify("Engines reloaded", type="positive")

                            ui.button("Save", icon="save", on_click=save_engines).props(
                                "dense"
                            )
                            ui.button(
                                "Reload",
                                icon="refresh",
                                on_click=reload_engines,
                            ).props("dense flat")

                # Reference
                with ui.card().classes("w-full"):
                    ui.label("Engine Reference").classes("text-sm font-bold")
                    ui.label(
                        f"Valid engine types: {', '.join(sorted(VALID_ENGINE_TYPES))}"
                    ).classes("text-xs text-grey-6")
                    ui.label("Simple format:").classes("text-xs text-grey-6 mt-1")
                    ui.code(
                        '["gitleaks", "betterleaks"]',
                        language="json",
                    ).classes("text-xs")
                    ui.label("Advanced format:").classes("text-xs text-grey-6 mt-1")
                    ui.code(
                        "[\n"
                        '  {"type": "gitleaks", "ignore_files": ["*.test"]},\n'
                        '  {"type": "trufflehog", "binary": "/usr/local/bin/trufflehog"}\n'
                        "]",
                        language="json",
                    ).classes("text-xs")

        ui.timer(0.1, refresh, once=True)
