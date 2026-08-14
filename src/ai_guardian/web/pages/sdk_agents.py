"""SDK Agent Profiles page — manage GuardedAgent configuration profiles."""

import copy

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.config_helpers import load_web_config, save_web_config

_COLUMNS = [
    {
        "name": "name",
        "label": "Name",
        "field": "name",
        "align": "left",
        "sortable": True,
    },
    {"name": "model", "label": "Model", "field": "model", "align": "left"},
    {
        "name": "max_turns",
        "label": "Max Turns",
        "field": "max_turns",
        "align": "center",
    },
    {"name": "tools", "label": "Tools", "field": "tools", "align": "left"},
    {"name": "mode", "label": "Mode", "field": "mode", "align": "center"},
    {
        "name": "compact_threshold",
        "label": "Compact Threshold",
        "field": "compact_threshold",
        "align": "center",
    },
    {"name": "actions", "label": "", "field": "actions", "align": "center"},
]

_MODE_OPTIONS = ["direct", "rest"]
_TOOLS_OPTIONS = ["coding", "readonly", "[]"]


def _profiles_to_rows(agents: dict) -> list:
    rows = []
    for name, profile in sorted(agents.items(), key=lambda x: (x[0] != "*", x[0])):
        tools_val = profile.get("tools", "")
        if isinstance(tools_val, list):
            tools_val = ", ".join(str(t) for t in tools_val) if tools_val else "[]"
        rows.append(
            {
                "name": name,
                "model": profile.get("model", ""),
                "max_turns": profile.get("max_turns", ""),
                "tools": str(tools_val),
                "mode": profile.get("mode", "direct"),
                "compact_threshold": profile.get("compact_threshold", ""),
            }
        )
    return rows


def _show_edit_dialog(
    profile_name: str,
    profile: dict,
    on_save,
):
    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label(f"Edit Profile: {profile_name}").classes("text-lg font-bold")

        model_input = ui.input(
            label="Model",
            value=profile.get("model", ""),
        ).classes("w-full")

        max_turns_input = ui.number(
            label="Max Turns",
            value=profile.get("max_turns"),
            min=1,
        ).classes("w-full")

        max_tokens_input = ui.number(
            label="Max Tokens",
            value=profile.get("max_tokens"),
            min=1,
        ).classes("w-full")

        tools_val = profile.get("tools", "")
        if isinstance(tools_val, list):
            tools_val = ", ".join(str(t) for t in tools_val) if tools_val else "[]"
        tools_input = ui.input(
            label="Tools (preset name or comma-separated)",
            value=str(tools_val),
        ).classes("w-full")

        mode_select = ui.select(
            options=_MODE_OPTIONS,
            value=profile.get("mode", "direct"),
            label="Mode",
        ).classes("w-full")

        compact_input = ui.number(
            label="Compact Threshold (0.0 - 1.0)",
            value=profile.get("compact_threshold", 0.8),
            min=0.0,
            max=1.0,
            step=0.05,
        ).classes("w-full")

        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def _save():
                updated = {}
                if model_input.value:
                    updated["model"] = model_input.value
                if max_turns_input.value is not None:
                    updated["max_turns"] = int(max_turns_input.value)
                if max_tokens_input.value is not None:
                    updated["max_tokens"] = int(max_tokens_input.value)
                tv = tools_input.value.strip()
                if tv:
                    if tv in _TOOLS_OPTIONS:
                        updated["tools"] = tv if tv != "[]" else []
                    elif "," in tv:
                        updated["tools"] = [
                            t.strip() for t in tv.split(",") if t.strip()
                        ]
                    else:
                        updated["tools"] = tv
                updated["mode"] = mode_select.value
                if compact_input.value is not None:
                    updated["compact_threshold"] = float(compact_input.value)

                for k, v in profile.items():
                    if k not in updated:
                        updated[k] = v
                dialog.close()
                await on_save(profile_name, updated)

            ui.button("Save", on_click=_save).props("color=primary")

    dialog.open()


def _show_add_dialog(existing_names: set, on_add):
    with ui.dialog() as dialog, ui.card().classes("w-80"):
        ui.label("New Agent Profile").classes("text-lg font-bold")
        name_input = ui.input(label="Profile Name").classes("w-full")
        error_label = ui.label("").classes("text-red text-xs")

        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def _create():
                name = name_input.value.strip()
                if not name:
                    error_label.set_text("Name is required.")
                    return
                if name in existing_names:
                    error_label.set_text(f"Profile '{name}' already exists.")
                    return
                dialog.close()
                await on_add(name)

            ui.button("Create", on_click=_create).props("color=primary")

    dialog.open()


def create_sdk_agents_page(service, daemon_name: str):
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/sdk-agents")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Agent Profiles").classes("text-2xl font-bold")
        ui.label(
            "Configure GuardedAgent profiles. "
            "The * profile provides defaults for all agents."
        ).classes("text-xs text-grey-6")

        table_container = ui.column().classes("w-full gap-2")
        state = {"config": {}, "agents": {}}

        async def _load():
            config = await run.io_bound(load_web_config)
            state["config"] = config
            agents = config.get("sdk", {}).get("agents", {})
            state["agents"] = agents
            _render_table(agents)

        def _render_table(agents: dict):
            table_container.clear()
            rows = _profiles_to_rows(agents)
            with table_container:
                table = (
                    ui.table(
                        columns=_COLUMNS,
                        rows=rows,
                        row_key="name",
                    )
                    .classes("w-full")
                    .props("dense flat bordered")
                )

                table.add_slot(
                    "body-cell-name",
                    r"""
                    <q-td :props="props">
                        <span :class="props.row.name === '*' ? 'font-bold text-blue-4' : ''">
                            {{ props.row.name }}
                        </span>
                    </q-td>
                    """,
                )

                table.add_slot(
                    "body-cell-actions",
                    r"""
                    <q-td :props="props">
                        <q-btn flat dense icon="edit" size="sm"
                               @click="$parent.$emit('edit', props.row)" />
                        <q-btn flat dense icon="delete" size="sm" color="red"
                               v-if="props.row.name !== '*'"
                               @click="$parent.$emit('delete', props.row)" />
                    </q-td>
                    """,
                )

                async def _on_edit(e):
                    row = e.args
                    name = row["name"]
                    profile = copy.deepcopy(state["agents"].get(name, {}))
                    _show_edit_dialog(name, profile, _save_profile)

                async def _on_delete(e):
                    row = e.args
                    name = row["name"]
                    if name == "*":
                        return
                    agents = state["agents"]
                    if name in agents:
                        del agents[name]
                    await _persist_and_reload()

                table.on("edit", _on_edit)
                table.on("delete", _on_delete)

                with ui.row().classes("gap-2 mt-2"):
                    ui.button(
                        "Add Profile",
                        icon="add",
                        on_click=lambda: _show_add_dialog(
                            set(state["agents"].keys()),
                            _add_profile,
                        ),
                    ).props("outline dense")

        async def _save_profile(name: str, updated: dict):
            state["agents"][name] = updated
            await _persist_and_reload()

        async def _add_profile(name: str):
            state["agents"][name] = {"mode": "direct"}
            await _persist_and_reload()

        async def _persist_and_reload():
            config = state["config"]
            sdk = config.setdefault("sdk", {})
            sdk["agents"] = state["agents"]
            await run.io_bound(save_web_config, config)
            ui.notify("Saved", type="positive")
            await _load()

        ui.timer(0.1, _load, once=True)
