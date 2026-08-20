"""Tray Plugins page — manage tray menu plugin JSON files."""

import json

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar

_COLUMNS = [
    {
        "name": "plugin_name",
        "label": "Name",
        "field": "plugin_name",
        "align": "left",
        "sortable": True,
    },
    {"name": "source", "label": "Source", "field": "source", "align": "center"},
    {"name": "enabled", "label": "Status", "field": "enabled", "align": "center"},
    {"name": "filename", "label": "File", "field": "filename", "align": "left"},
    {"name": "actions", "label": "", "field": "actions", "align": "center"},
]


def _show_editor_dialog(filename, content_str, on_save):
    with ui.dialog() as dialog, ui.card().classes("w-[600px]"):
        ui.label(f"Edit Plugin: {filename}").classes("text-lg font-bold")
        editor = (
            ui.textarea(value=content_str)
            .classes("w-full font-mono text-xs")
            .props("rows=20 outlined")
        )
        error_label = ui.label("").classes("text-red text-xs")

        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def _save():
                try:
                    parsed = json.loads(editor.value)
                except json.JSONDecodeError as exc:
                    error_label.set_text(f"Invalid JSON: {exc}")
                    return
                dialog.close()
                await on_save(filename, parsed)

            ui.button("Save", on_click=_save).props("color=primary")

    dialog.open()


def _show_new_dialog(templates, on_create):
    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label("New Plugin").classes("text-lg font-bold")

        name_input = ui.input(label="Plugin Name").classes("w-full")
        filename_input = ui.input(label="Filename (e.g. my-plugin.json)").classes(
            "w-full"
        )

        template_names = ["(blank)"] + [t["name"] for t in templates]
        template_select = ui.select(
            options=template_names,
            value="(blank)",
            label="Start from template",
        ).classes("w-full")

        error_label = ui.label("").classes("text-red text-xs")

        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def _create():
                name = name_input.value.strip()
                fname = filename_input.value.strip()
                if not name:
                    error_label.set_text("Plugin name required.")
                    return
                if not fname:
                    fname = name.lower().replace(" ", "-") + ".json"
                if not fname.endswith(".json"):
                    fname += ".json"

                sel = template_select.value
                if sel and sel != "(blank)":
                    tmpl = next((t for t in templates if t["name"] == sel), None)
                    if tmpl:
                        try:
                            content = json.loads(tmpl["content"])
                        except (json.JSONDecodeError, KeyError):
                            content = {"name": name, "items": []}
                    else:
                        content = {"name": name, "items": []}
                    content["name"] = name
                else:
                    content = {
                        "name": name,
                        "items": [
                            {
                                "label": "Example Command",
                                "command": "echo hello",
                                "type": "notification",
                            }
                        ],
                    }

                dialog.close()
                await on_create(fname, content)

            ui.button("Create", on_click=_create).props("color=primary")

    dialog.open()


def _show_view_dialog(plugin_name, items):
    with ui.dialog() as dialog, ui.card().classes("w-[500px]"):
        ui.label(f"Menu Preview: {plugin_name}").classes("text-lg font-bold")

        def _render_items(item_list, depth=0):
            for item in item_list:
                prefix = "  " * depth
                label = item.get("label", "?")
                if "items" in item and isinstance(item["items"], list):
                    ui.label(f"{prefix}📂 {label}").classes("font-mono text-sm")
                    _render_items(item["items"], depth + 1)
                elif "command" in item:
                    cmd = item["command"]
                    if isinstance(cmd, dict):
                        cmd = cmd.get("default", str(cmd))
                    itype = item.get("type", "terminal")
                    ui.label(f"{prefix}▸ {label}  [{itype}]").classes(
                        "font-mono text-sm"
                    )
                    ui.label(f"{prefix}  $ {cmd}").classes(
                        "font-mono text-xs text-grey-6"
                    )

        with ui.scroll_area().classes("max-h-[400px] w-full"):
            _render_items(items)

        ui.button("Close", on_click=dialog.close).props("flat").classes("mt-2")

    dialog.open()


def create_tray_plugins_page(service, daemon_name: str):
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/tray-plugins")
    create_header(daemon_name, drawer=sidebar)

    target = service.get_target_by_name(daemon_name)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Tray Plugins").classes("text-2xl font-bold")
        ui.label(
            "Manage custom tray menu plugins. "
            "Bundled plugins are read-only; user plugins can be edited or deleted."
        ).classes("text-xs text-grey-6")

        table_container = ui.column().classes("w-full gap-2")
        state = {"files": [], "plugins": [], "templates": []}

        async def _load():
            data = await run.io_bound(service.get_tray_plugins, target)
            if data:
                state["files"] = data.get("files", [])
                state["plugins"] = data.get("plugins", [])
            else:
                state["files"] = []
                state["plugins"] = []

            tmpl_data = await run.io_bound(service.get_tray_plugin_templates, target)
            state["templates"] = tmpl_data.get("templates", []) if tmpl_data else []
            _render_table()

        def _render_table():
            table_container.clear()
            rows = state["files"]
            with table_container:
                table = (
                    ui.table(columns=_COLUMNS, rows=rows, row_key="filename")
                    .classes("w-full")
                    .props("dense flat bordered")
                )

                table.add_slot(
                    "body-cell-enabled",
                    r"""
                    <q-td :props="props">
                        <q-badge :color="props.row.enabled ? 'green' : 'grey'"
                                 :label="props.row.enabled ? 'Enabled' : 'Disabled'" />
                    </q-td>
                    """,
                )

                table.add_slot(
                    "body-cell-source",
                    r"""
                    <q-td :props="props">
                        <q-badge :color="props.row.source === 'bundled' ? 'blue'
                                         : props.row.source === 'project' ? 'purple'
                                         : 'orange'"
                                 :label="props.row.source" />
                    </q-td>
                    """,
                )

                table.add_slot(
                    "body-cell-actions",
                    r"""
                    <q-td :props="props">
                        <q-btn flat dense icon="visibility" size="sm"
                               @click="$parent.$emit('view', props.row)"
                               title="Preview menu" />
                        <q-btn flat dense icon="edit" size="sm"
                               v-if="props.row.source === 'user'"
                               @click="$parent.$emit('edit', props.row)"
                               title="Edit" />
                        <q-btn flat dense size="sm"
                               :icon="props.row.enabled ? 'toggle_on' : 'toggle_off'"
                               :color="props.row.enabled ? 'green' : 'grey'"
                               v-if="props.row.source === 'user'"
                               @click="$parent.$emit('toggle', props.row)"
                               title="Toggle" />
                        <q-btn flat dense icon="delete" size="sm" color="red"
                               v-if="props.row.source === 'user'"
                               @click="$parent.$emit('delete', props.row)"
                               title="Delete" />
                    </q-td>
                    """,
                )

                async def _on_view(e):
                    row = e.args
                    name = row.get("plugin_name", row.get("filename", "?"))
                    plugin = next(
                        (p for p in state["plugins"] if p.get("name") == name),
                        None,
                    )
                    items = plugin.get("items", []) if plugin else []
                    _show_view_dialog(name, items)

                async def _on_edit(e):
                    row = e.args
                    fname = row["filename"]
                    plugin = next(
                        (
                            p
                            for p in state["plugins"]
                            if p.get("name") == row.get("plugin_name")
                        ),
                        None,
                    )
                    content_str = json.dumps(plugin, indent=2) if plugin else "{}"
                    _show_editor_dialog(fname, content_str, _save_plugin)

                async def _on_toggle(e):
                    row = e.args
                    fname = row["filename"]
                    new_enabled = not row.get("enabled", True)
                    base = (
                        fname[: -len(".disabled")]
                        if fname.endswith(".disabled")
                        else fname
                    )
                    result = await run.io_bound(
                        service.toggle_tray_plugin, target, base, new_enabled
                    )
                    if result and result.get("status") != "error":
                        ui.notify(
                            "Enabled" if new_enabled else "Disabled",
                            type="positive",
                        )
                        await _load()
                    else:
                        msg = result.get("message", "Failed") if result else "Failed"
                        ui.notify(msg, type="negative")

                async def _on_delete(e):
                    row = e.args
                    fname = row["filename"]
                    with ui.dialog() as confirm, ui.card():
                        ui.label(f"Delete {fname}?").classes("text-lg")
                        with ui.row().classes("justify-end gap-2 mt-4"):
                            ui.button("Cancel", on_click=confirm.close).props("flat")

                            async def _do_delete():
                                confirm.close()
                                result = await run.io_bound(
                                    service.delete_tray_plugin, target, fname
                                )
                                if result and result.get("status") != "error":
                                    ui.notify("Deleted", type="positive")
                                    await _load()
                                else:
                                    msg = (
                                        result.get("message", "Failed")
                                        if result
                                        else "Failed"
                                    )
                                    ui.notify(msg, type="negative")

                            ui.button("Delete", on_click=_do_delete).props("color=red")
                    confirm.open()

                table.on("view", _on_view)
                table.on("edit", _on_edit)
                table.on("toggle", _on_toggle)
                table.on("delete", _on_delete)

                with ui.row().classes("gap-2 mt-2"):
                    ui.button(
                        "New Plugin",
                        icon="add",
                        on_click=lambda: _show_new_dialog(
                            state["templates"], _create_plugin
                        ),
                    ).props("outline dense")
                    ui.button(
                        "Refresh",
                        icon="refresh",
                        on_click=_load,
                    ).props("outline dense")

        async def _save_plugin(filename, content):
            result = await run.io_bound(
                service.save_tray_plugin, target, filename, content
            )
            if result and result.get("status") != "error":
                ui.notify("Saved", type="positive")
                await _load()
            else:
                msg = result.get("message", "Save failed") if result else "Save failed"
                ui.notify(msg, type="negative")

        async def _create_plugin(filename, content):
            await _save_plugin(filename, content)

        ui.timer(0.1, _load, once=True)
