"""Proactive prompt state page — read-only view of the local state file."""

import json

from nicegui import run, ui

from ai_guardian.cli_runtime import runtime_activation_info, runtime_activation_label
from ai_guardian.ide_registry import SUPPORTED_IDE_REGISTRY
from ai_guardian.tray.proactive_prompt import (
    IDE_SETUP_STATUS_KEY,
    ProactivePromptState,
    reset_ide_setup_state,
    sync_ide_setup_state,
)
from ai_guardian.web.components.header import create_header, create_sidebar


def _load_proactive_prompt_file():
    """Load the local proactive prompt state file for display."""
    path = ProactivePromptState().path
    info = {
        "path": str(path),
        "exists": False,
        "content": None,
        "error": None,
        "data": None,
    }

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return info
    except OSError as exc:
        info["error"] = f"Unable to read state file: {exc}"
        return info

    info["exists"] = True
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        info["content"] = raw
        info["error"] = (
            f"Invalid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        )
    else:
        if isinstance(data, dict):
            info["data"] = data
        else:
            info["data"] = {}
            info["error"] = "State file must contain a JSON object"
        info["content"] = json.dumps(data, indent=2)
    return info


def _sync_proactive_prompt_file():
    """Refresh the state file from locally detected IDE configurations."""
    return sync_ide_setup_state()


def _reset_proactive_prompt_file(ide_type):
    """Clear one IDE's saved proactive setup decisions."""
    return reset_ide_setup_state(ide_type)


def _current_ide_status_rows(snapshot):
    """Build separate configuration and runtime rows for detected integrations."""
    integrations = snapshot.get("integrations", {})
    tray_status = snapshot.get("tray_status", {})
    if not isinstance(integrations, dict):
        integrations = {}
    if not isinstance(tray_status, dict):
        tray_status = {}

    rows = []
    for integration in SUPPORTED_IDE_REGISTRY:
        ide_type = integration.key
        status = integrations.get(ide_type)
        if not isinstance(status, dict):
            status = {}
        tray_entry = tray_status.get(ide_type)
        if not isinstance(tray_entry, dict):
            tray_entry = {}
        detected = (
            ide_type in integrations
            or tray_entry.get("ide_detected") is True
            or tray_entry.get("cli") == "installed"
        )
        if not detected:
            continue

        if status.get("healthy") is True:
            configuration_status = (
                "Configured (last verified)"
                if status.get("verification_skipped")
                else "Configured"
            )
        elif status.get("error"):
            configuration_status = "Check failed"
        elif status.get("excluded"):
            configuration_status = (
                "Excluded (last verified)"
                if status.get("verification_skipped")
                else "Excluded (needs setup)"
            )
        else:
            configuration_status = {
                "configured": "Configured",
                "needs_setup": "Needs setup",
                "unknown": "Check unavailable",
                "not_detected": "Not detected",
            }.get(tray_entry.get("setup"), "Needs setup")

        activation = status.get("runtime_activation")
        if not isinstance(activation, dict):
            activation = tray_entry.get("runtime_activation")
        if not isinstance(activation, dict):
            activation = runtime_activation_info(integration, status, detected=detected)

        details = []
        events = status.get("events", {})
        if isinstance(events, dict):
            details.extend(
                f"{event}: {event_status}"
                for event, event_status in events.items()
                if event_status != "healthy"
            )
        obsolete = status.get("obsolete", [])
        if isinstance(obsolete, (list, tuple, set)):
            details.extend(f"{event}: obsolete" for event in obsolete)
        if status.get("error"):
            details.append(str(status["error"]))
        if status.get("verification_skipped"):
            details.append(
                "not rechecked: "
                + str(status.get("verification_skip_reason", "automatic exclusion"))
            )
        activation_status = activation.get("status")
        if activation_status in {"unverified", "failed", "unknown"}:
            reason = activation.get("reason")
            if isinstance(reason, str) and reason:
                details.append(f"Runtime: {reason}")

        rows.append(
            {
                "ide": ide_type,
                "integration": status.get("name", integration.display_name),
                "configuration_status": configuration_status,
                "runtime_activation": runtime_activation_label(activation_status),
                "details": ", ".join(details) or "—",
                "config_path": status.get("config_path") or "—",
            }
        )
    return rows


def create_proactive_prompts_page(service, daemon_name: str):
    """Create the read-only proactive prompt state page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/proactive-prompts")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Proactive Prompt State").classes("text-2xl font-bold")
        ui.label(
            "Read-only view of the local tray state file. This is separate from "
            "ai-guardian.json and is not included when sharing configuration."
        ).classes("text-xs text-grey-6")

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            info = await run.io_bound(_load_proactive_prompt_file)

            with content:
                with ui.card().classes("w-full"):
                    ui.label("State File").classes("text-lg font-bold")
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("check_circle" if info["exists"] else "info").classes(
                            "text-green" if info["exists"] else "text-blue"
                        )
                        ui.label(info["path"]).classes("text-sm text-grey-4").style(
                            "font-family: monospace"
                        )

                if info["error"]:
                    ui.label(info["error"]).classes("text-red text-sm")

                snapshot = (info["data"] or {}).get(IDE_SETUP_STATUS_KEY)
                if isinstance(snapshot, dict):
                    with ui.card().classes("w-full"):
                        ui.label("Current IDE/CLI Reality").classes("text-lg font-bold")
                        ui.label(
                            f"Last synchronized: {snapshot.get('checked_at', 'unknown')}"
                        ).classes("text-xs text-grey-6")
                        ui.label(
                            "Configuration health and runtime activation are separate. "
                            "Unverified is not a configuration fault; it means no "
                            "runtime signal confirmed the host loaded or invoked AI "
                            "Guardian. CLI version checks are not activation proof."
                        ).classes("text-xs text-grey-6")
                        rows = _current_ide_status_rows(snapshot)
                        if rows:
                            table = (
                                ui.table(
                                    columns=[
                                        {
                                            "name": "ide",
                                            "label": "IDE",
                                            "field": "ide",
                                            "align": "left",
                                        },
                                        {
                                            "name": "integration",
                                            "label": "Integration",
                                            "field": "integration",
                                            "align": "left",
                                        },
                                        {
                                            "name": "configuration_status",
                                            "label": "Configuration status",
                                            "field": "configuration_status",
                                            "align": "left",
                                        },
                                        {
                                            "name": "runtime_activation",
                                            "label": "Runtime activation",
                                            "field": "runtime_activation",
                                            "align": "left",
                                        },
                                        {
                                            "name": "details",
                                            "label": "Details",
                                            "field": "details",
                                            "align": "left",
                                        },
                                        {
                                            "name": "config_path",
                                            "label": "Configuration path",
                                            "field": "config_path",
                                            "align": "left",
                                        },
                                        {
                                            "name": "actions",
                                            "label": "",
                                            "field": "actions",
                                            "align": "right",
                                        },
                                    ],
                                    rows=rows,
                                )
                                .classes("w-full")
                                .props("flat bordered dense")
                            )
                            table.add_slot(
                                "body-cell-actions",
                                r"""
                                <q-td :props="props">
                                    <q-btn flat dense label="Reset" color="orange"
                                           size="sm"
                                           @click="$parent.$emit('reset', props.row)"
                                           title="Reset this IDE's proactive setup decisions" />
                                </q-td>
                                """,
                            )

                            async def _on_reset(event):
                                row = event.args
                                ide_type = row.get("ide")
                                if not ide_type:
                                    return
                                name = row.get("integration", ide_type)
                                with ui.dialog() as confirm, ui.card():
                                    ui.label(
                                        f"Reset proactive setup decisions for {name}?"
                                    ).classes("text-lg")
                                    ui.label(
                                        "This removes its saved Never install choice "
                                        "and related prompt history. It does not "
                                        "change IDE hooks."
                                    ).classes("text-sm text-grey-6")
                                    with ui.row().classes("justify-end gap-2 mt-4"):
                                        ui.button(
                                            "Cancel", on_click=confirm.close
                                        ).props("flat")

                                        async def _do_reset():
                                            confirm.close()
                                            result = await run.io_bound(
                                                _reset_proactive_prompt_file,
                                                ide_type,
                                            )
                                            if result.get("error"):
                                                ui.notify(
                                                    f"Unable to reset {name}: "
                                                    f"{result['error']}",
                                                    type="negative",
                                                )
                                            else:
                                                ui.notify(
                                                    f"Reset proactive setup decisions "
                                                    f"for {name}",
                                                    type="positive",
                                                )
                                            await refresh()

                                        ui.button("Reset", on_click=_do_reset).props(
                                            "color=orange"
                                        )
                                confirm.open()

                            table.on("reset", _on_reset)
                        else:
                            ui.label(
                                "No installed IDE/CLI integrations found."
                            ).classes("text-grey-6 text-sm")
                        ui.label(
                            "The ide_setup_<combination> entries below are prompt "
                            "history; they do not represent current hook status."
                        ).classes("text-xs text-grey-6")
                else:
                    with ui.card().classes("w-full"):
                        ui.label("Current IDE/CLI Reality").classes("text-lg font-bold")
                        ui.label(
                            "Not synchronized yet. Use the sync button to compare "
                            "installed integrations with their current hook files."
                        ).classes("text-grey-6 text-sm")
                        ui.label(
                            "Existing ide_setup_<combination> entries are prompt "
                            "history, not current hook status."
                        ).classes("text-xs text-grey-6")

                if not info["exists"]:
                    ui.label(
                        "No proactive prompt state file exists yet. It will be "
                        "created after a prompt decision is saved."
                    ).classes("text-grey-6 text-sm")
                else:
                    with ui.card().classes("w-full"):
                        ui.label("JSON Contents").classes("text-lg font-bold")
                        ui.codemirror(
                            info["content"] or "",
                            language="JSON",
                            theme="dracula",
                        ).classes("w-full").props("readonly")

        async def sync():
            result = await run.io_bound(_sync_proactive_prompt_file)
            if result.get("error"):
                ui.notify(
                    f"Unable to sync IDE setup state: {result['error']}",
                    type="negative",
                )
            else:
                count = len(result.get("installed", []))
                ui.notify(
                    f"IDE setup state synchronized ({count} integration(s))",
                    type="positive",
                )
            await refresh()

        with ui.row().classes("gap-2"):
            ui.button("Refresh", icon="refresh", on_click=refresh).props("dense")
            ui.button(
                "Sync with current IDE/CLI configuration",
                icon="sync",
                on_click=sync,
            ).props("color=primary")

        ui.timer(0.1, refresh, once=True)
