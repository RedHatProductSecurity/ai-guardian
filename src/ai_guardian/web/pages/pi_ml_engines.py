"""ML Prompt Injection Engines — configure ML engines, strategy, and fallback."""

import json
import subprocess
import sys

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.config_helpers import load_web_config, save_web_config

VALID_ML_ENGINE_TYPES = {"llm-guard"}


def _validate_ml_engines_json(text):
    """Validate ML engines JSON, returning (parsed_list, error_string)."""
    text = text.strip()
    if not text:
        return [], None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    if not isinstance(data, list):
        return None, "Engines must be a JSON array"
    for i, engine in enumerate(data):
        if not isinstance(engine, dict):
            return None, f"Engine {i + 1}: must be an object with 'type' and 'model'"
        etype = engine.get("type")
        if not etype:
            return None, f"Engine {i + 1}: missing 'type' field"
        if etype not in VALID_ML_ENGINE_TYPES:
            return None, f"Engine {i + 1}: unknown type '{etype}'"
        if not engine.get("model"):
            return None, f"Engine {i + 1}: missing 'model' field"
        threshold = engine.get("threshold")
        if threshold is not None:
            if not isinstance(threshold, (int, float)):
                return None, f"Engine {i + 1}: threshold must be a number"
            if not 0.0 <= threshold <= 1.0:
                return None, f"Engine {i + 1}: threshold must be 0.0-1.0"
    return data, None


def _load_ml_status():
    """Check ML availability and model download status."""
    try:
        from ai_guardian.scanners.ml_detection import (
            is_ml_available,
            list_registered_models,
        )

        available = is_ml_available()
        models = list_registered_models()
        return available, models
    except Exception:
        return False, []


def _install_onnxruntime():
    """Install onnxruntime via pip. Returns (success, message)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "onnxruntime"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True, "onnxruntime installed successfully"
        return False, result.stderr.strip()[:300] or "Install failed"
    except Exception as e:
        return False, str(e)


def _download_ml_model():
    """Download the default ML model. Returns (success, message)."""
    try:
        from ai_guardian.scanners.ml_detection import download_model

        download_model()
        return True, "Model downloaded successfully"
    except Exception as e:
        return False, str(e)


def create_pi_ml_engines_page(service, daemon_name: str):
    """Create the ML Prompt Injection Engines page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/pi-ml-engines")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("ML Prompt Injection Engines").classes("text-2xl font-bold")
        ui.label(
            "Configure ML-based prompt injection detection engines and execution strategy."
        ).classes("text-xs text-grey-6")

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)

            with content:
                pi = config.get("prompt_injection", {})
                if not isinstance(pi, dict):
                    pi = {}

                engines = pi.get("ml_engines", [])
                detector = pi.get("detector", "heuristic")

                available, models = await run.io_bound(_load_ml_status)
                deps_ok = available
                model_ok = bool(models) and all(m.get("downloaded") for m in models)
                config_ok = bool(engines)
                detector_ok = detector in ("ml", "hybrid")

                # --- Setup Wizard ---
                with ui.card().classes("w-full"):
                    ui.label("ML Engine Setup").classes("text-lg font-bold")

                    # Step 1: Dependencies
                    with ui.row().classes("items-center gap-3 mt-2"):
                        if deps_ok:
                            ui.icon("check_circle").classes("text-green")
                            ui.label(
                                "Step 1: Dependencies — onnxruntime installed"
                            ).classes("text-sm flex-grow")
                        else:
                            ui.icon("warning").classes("text-orange")
                            ui.label(
                                "Step 1: Dependencies — onnxruntime not installed"
                            ).classes("text-sm flex-grow")

                            async def install_onnxruntime():
                                ui.notify("Installing onnxruntime...", type="ongoing")
                                ok, msg = await run.io_bound(_install_onnxruntime)
                                if ok:
                                    ui.notify(msg, type="positive")
                                else:
                                    ui.notify(msg, type="negative")
                                await refresh()

                            ui.button(
                                "Install onnxruntime",
                                icon="download",
                                on_click=install_onnxruntime,
                            ).props("dense")

                    # Step 2: Model
                    with ui.row().classes("items-center gap-3 mt-1"):
                        if model_ok:
                            ui.icon("check_circle").classes("text-green")
                            ui.label("Step 2: Model — downloaded").classes(
                                "text-sm flex-grow"
                            )
                        else:
                            ui.icon("warning").classes("text-orange")
                            ui.label("Step 2: Model — not downloaded").classes(
                                "text-sm flex-grow"
                            )

                            async def download_model_action():
                                ui.notify("Downloading ML model...", type="ongoing")
                                ok, msg = await run.io_bound(_download_ml_model)
                                if ok:
                                    ui.notify(msg, type="positive")
                                else:
                                    ui.notify(msg, type="negative")
                                await refresh()

                            ui.button(
                                "Download Model",
                                icon="cloud_download",
                                on_click=download_model_action,
                            ).props("dense")

                    # Step 3: Configuration
                    with ui.row().classes("items-center gap-3 mt-1"):
                        if config_ok:
                            ui.icon("check_circle").classes("text-green")
                            ui.label(
                                f"Step 3: Configuration — {len(engines)} engine(s) configured"
                            ).classes("text-sm")
                        else:
                            ui.icon("warning").classes("text-orange")
                            ui.label(
                                "Step 3: Configuration — no engines configured"
                            ).classes("text-sm")

                    # Step 4: Detector
                    detector_path = f"/{daemon_name}/pi-detection"
                    with ui.row().classes("items-center gap-3 mt-1"):
                        if detector_ok:
                            ui.icon("check_circle").classes("text-green")
                            ui.label(f"Step 4: Detector — set to '{detector}'").classes(
                                "text-sm flex-grow"
                            )
                        else:
                            ui.icon("warning").classes("text-orange")
                            ui.label(
                                f"Step 4: Detector — '{detector}', change to 'ml' or 'hybrid'"
                            ).classes("text-sm flex-grow")
                            ui.button(
                                "Go to Detector Settings",
                                icon="open_in_new",
                                on_click=lambda: ui.navigate.to(detector_path),
                            ).props("dense flat")

                    # Overall status
                    ui.separator().classes("mt-2")
                    if deps_ok and model_ok and config_ok and detector_ok:
                        ui.label("Status: READY").classes(
                            "text-sm font-bold text-green mt-1"
                        )
                    else:
                        reasons = []
                        if not deps_ok:
                            reasons.append("dependency missing")
                        if not model_ok:
                            reasons.append("model not downloaded")
                        if not config_ok:
                            reasons.append("no engines configured")
                        if not detector_ok:
                            reasons.append("detector not set to ml/hybrid")
                        ui.label(f"Status: NOT READY ({', '.join(reasons)})").classes(
                            "text-sm font-bold text-orange mt-1"
                        )

                # --- ML Strategy ---
                with ui.card().classes("w-full"):
                    ui.label("Execution Strategy").classes("text-lg font-bold")
                    ui.label("How multiple ML engines coordinate detection.").classes(
                        "text-xs text-grey-6"
                    )

                    strategy = pi.get("ml_strategy", "any-match")
                    strat_sel = ui.select(
                        options={
                            "first-match": "First Match — use first engine result",
                            "any-match": "Any Match — flag if ANY engine detects",
                            "consensus": "Consensus — flag if N engines agree",
                        },
                        value=strategy,
                    ).classes("w-96")

                    threshold_row = ui.row().classes("items-center gap-2")
                    ct = pi.get("consensus_threshold", 2)
                    with threshold_row:
                        ui.label("Consensus Threshold:").classes("text-sm")
                        thresh_input = (
                            ui.input(
                                value=str(ct),
                            )
                            .props("dense outlined type=number")
                            .classes("w-24")
                        )
                    threshold_row.set_visibility(strategy == "consensus")

                    async def save_strategy(e):
                        cfg = await run.io_bound(load_web_config)
                        sect = cfg.get("prompt_injection", {})
                        if not isinstance(sect, dict):
                            sect = {}
                        sect["ml_strategy"] = e.value
                        cfg["prompt_injection"] = sect
                        await run.io_bound(save_web_config, cfg)
                        threshold_row.set_visibility(e.value == "consensus")
                        ui.notify(f"Strategy: {e.value}", type="positive")

                    strat_sel.on_value_change(save_strategy)

                    async def save_threshold():
                        try:
                            val = int(thresh_input.value)
                            if val < 1:
                                ui.notify(
                                    "Threshold must be at least 1", type="negative"
                                )
                                return
                        except (ValueError, TypeError):
                            ui.notify("Invalid threshold", type="negative")
                            return
                        cfg = await run.io_bound(load_web_config)
                        sect = cfg.get("prompt_injection", {})
                        if not isinstance(sect, dict):
                            sect = {}
                        sect["consensus_threshold"] = val
                        cfg["prompt_injection"] = sect
                        await run.io_bound(save_web_config, cfg)
                        ui.notify(f"Threshold: {val}", type="positive")

                    ui.button(
                        "Save Threshold",
                        icon="save",
                        on_click=save_threshold,
                    ).props("dense flat").bind_visibility_from(threshold_row, "visible")

                # --- Fallback ---
                with ui.card().classes("w-full"):
                    ui.label("Fallback on Error").classes("text-lg font-bold")
                    ui.label(
                        "What happens when ML detection is unavailable "
                        "(daemon not running, model not loaded)."
                    ).classes("text-xs text-grey-6")

                    fallback = pi.get("fallback_on_error", "heuristic")
                    fb_sel = ui.select(
                        options={
                            "heuristic": "Heuristic — fall back to pattern detection",
                            "block": "Block — fail closed (reject input)",
                            "allow": "Allow — fail open (accept input)",
                        },
                        value=fallback,
                    ).classes("w-96")

                    async def save_fallback(e):
                        cfg = await run.io_bound(load_web_config)
                        sect = cfg.get("prompt_injection", {})
                        if not isinstance(sect, dict):
                            sect = {}
                        sect["fallback_on_error"] = e.value
                        cfg["prompt_injection"] = sect
                        await run.io_bound(save_web_config, cfg)
                        ui.notify(f"Fallback: {e.value}", type="positive")

                    fb_sel.on_value_change(save_fallback)

                # --- ML Engines Editor ---
                with ui.card().classes("w-full"):
                    ui.label("ML Engines").classes("text-lg font-bold")
                    ui.label(
                        "Configure which ML engines to use for detection."
                    ).classes("text-xs text-grey-6")

                    if not deps_ok or not model_ok:
                        ui.label(
                            "Complete Steps 1-2 before configuring engines."
                        ).classes("text-sm text-orange")

                    engines_text = json.dumps(engines, indent=2) if engines else "[]"

                    editor = (
                        ui.textarea(
                            value=engines_text,
                        )
                        .props("outlined autogrow")
                        .classes("w-full")
                        .style("font-family: monospace; min-height: 150px")
                    )

                    count = len(engines)
                    status_label = ui.label(f"Valid JSON — {count} engine(s)").classes(
                        "text-xs text-green"
                    )

                    def on_edit(e):
                        parsed, err = _validate_ml_engines_json(e.args)
                        if err:
                            status_label.text = err
                            status_label.classes(replace="text-xs text-red")
                        else:
                            status_label.text = f"Valid JSON — {len(parsed)} engine(s)"
                            status_label.classes(replace="text-xs text-green")

                    editor.on("update:model-value", on_edit)

                    with ui.row().classes("gap-2 mt-2"):

                        async def save_engines():
                            parsed, err = _validate_ml_engines_json(editor.value)
                            if err:
                                ui.notify(err, type="negative")
                                return
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("prompt_injection", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            sect["ml_engines"] = parsed
                            cfg["prompt_injection"] = sect
                            saved = await run.io_bound(save_web_config, cfg)
                            if not saved:
                                ui.notify(
                                    "Save failed: configuration is read-only or unavailable",
                                    type="negative",
                                )
                                return
                            ui.notify(f"Saved {len(parsed)} engine(s)", type="positive")
                            await refresh()

                        async def reload_engines():
                            await refresh()
                            ui.notify("Engines reloaded", type="positive")

                        ui.button("Save", icon="save", on_click=save_engines).props(
                            "dense"
                        )
                        ui.button(
                            "Reload", icon="refresh", on_click=reload_engines
                        ).props("dense flat")

                # --- Reference ---
                with ui.card().classes("w-full"):
                    ui.label("ML Engine Reference").classes("text-sm font-bold")
                    ui.label(
                        f"Valid engine types: {', '.join(sorted(VALID_ML_ENGINE_TYPES))}"
                    ).classes("text-xs text-grey-6")
                    ui.label(
                        "Engine format (each entry requires type and model):"
                    ).classes("text-xs text-grey-6 mt-1")
                    ui.code(
                        "[\n"
                        "  {\n"
                        '    "type": "llm-guard",\n'
                        '    "model": "protectai/deberta-v3-base-prompt-injection-v2",\n'
                        '    "threshold": 0.85\n'
                        "  }\n"
                        "]",
                        language="json",
                    ).classes("text-xs")
                    ui.label(
                        "threshold is optional (default: 0.85, range: 0.0-1.0)"
                    ).classes("text-xs text-grey-6 mt-1")
                    ui.label(
                        "Requires: onnxruntime (included on Python < 3.13) and ai-guardian ml download"
                    ).classes("text-xs text-grey-6")

        ui.timer(0.1, refresh, once=True)
