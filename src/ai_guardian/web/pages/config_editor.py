"""Config Editor page — JSON config editor with scope toggle."""

import json
import shutil
from pathlib import Path

from nicegui import run, ui

from ai_guardian.config.utils import CONFIG_READ_ONLY_MESSAGE
from ai_guardian.web.components.config_notice import create_config_source_banner
from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.config_helpers import (
    _get_current_target,
    _is_remote_target,
    _daemon_service,
    get_web_config_state,
    is_web_config_read_only,
)


def _validate_json(text):
    """Validate JSON text. Returns (parsed_dict, error_string)."""
    if not text or not text.strip():
        return None, "Empty content"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    if not isinstance(parsed, dict):
        return None, "Config must be a JSON object (not array or scalar)"
    return parsed, None


def _get_config_path(scope, project_dir=None):
    """Get the config file path for the given scope.

    Args:
        scope: "global" or "project".
        project_dir: Explicit project directory from header selector.
    """
    if scope == "project":
        if project_dir:
            from pathlib import Path

            from ai_guardian.config.utils import _find_config_in_dir

            return _find_config_in_dir(Path(project_dir))
        return None
    from ai_guardian.config.utils import get_config_dir

    return get_config_dir() / "ai-guardian.json"


def _load_config_by_scope(scope):
    """Load config from the specified scope. Returns (content_str, path_str).

    Routes through DaemonService for both local and remote targets.
    """
    target = _get_current_target()
    if target is not None and _daemon_service is not None:
        from ai_guardian.web.config_helpers import _get_remote_project_dir

        project_dir = _get_remote_project_dir()
        cfg = _daemon_service.get_config_scoped(target, scope, project_dir=project_dir)
        label = f"(daemon: {target.name}"
        if project_dir:
            label += f" | project: {project_dir}"
        label += ")"
        if cfg is not None:
            return json.dumps(cfg, indent=2), label
        return "", f"(daemon: {target.name} — unreachable)"

    from ai_guardian.web.config_helpers import _get_remote_project_dir

    path = _get_config_path(scope, _get_remote_project_dir())
    if path is None:
        return "", None
    path_str = str(path)
    if not path.exists():
        return "", path_str
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return json.dumps(data, indent=2), path_str
    except Exception as e:
        return f"// Error: {e}", path_str


def _save_config_with_backup(content_str, path_str):
    """Save config with .json.bak backup. Returns error string or None.

    Routes through DaemonService for both local and remote targets.
    """
    if is_web_config_read_only():
        return CONFIG_READ_ONLY_MESSAGE

    parsed, err = _validate_json(content_str)
    if err:
        return err

    target = _get_current_target()
    if target is not None and _daemon_service is not None:
        from ai_guardian.web.config_helpers import (
            _get_current_scope,
            _get_remote_project_dir,
        )

        scope = _get_current_scope()
        project_dir = _get_remote_project_dir()
        if scope == "project" and project_dir:
            result = _daemon_service.write_config_bulk(
                target, "project", parsed, project_dir=project_dir
            )
        else:
            result = _daemon_service.write_config_bulk(target, "global", parsed)
        if result is None or result.get("status") == "error":
            if isinstance(result, dict) and result.get("message"):
                return result["message"]
            return "Failed to write to daemon"
        return None

    if not path_str:
        return "No config path available"
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, str(path) + ".bak")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2)
        f.write("\n")
    return None


def create_config_editor_page(service, daemon_name: str):
    """Create the Config Editor page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/config-editor")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Config Editor").classes("text-2xl font-bold")
        ui.label("Edit configuration files with JSON validation.").classes(
            "text-xs text-grey-6"
        )
        config_banner = ui.column().classes("w-full")

        from ai_guardian.web.config_helpers import _get_remote_project_dir

        project_dir = _get_remote_project_dir()
        initial_scope = "project" if project_dir else "global"
        state = {
            "scope": initial_scope,
            "path": None,
            "read_only": False,
            "config_source": "",
        }

        with ui.card().classes("w-full"):
            scope_sel = None
            if project_dir:
                ui.label("Scope").classes("text-lg font-bold")
                scope_sel = ui.select(
                    options={"global": "Global", "project": project_dir},
                    value=initial_scope,
                ).classes("w-auto min-w-[200px]")

            path_label = (
                ui.label("")
                .classes("text-sm text-grey-4")
                .style("font-family: monospace")
            )

        with ui.card().classes("w-full"):
            ui.label("Editor").classes("text-lg font-bold")
            status_label = ui.label("").classes("text-sm")
            # Defer codemirror initialization to avoid duplicate ESM module
            # warnings when navigating between config pages (issue #1102)
            editor_container = ui.column().classes("w-full")
            editor = None
            save_button = None

            def apply_read_only_state():
                if not state["read_only"]:
                    return
                if editor is not None:
                    editor.props("readonly")
                if save_button is not None:
                    save_button.set_enabled(False)

            async def init_editor():
                nonlocal editor
                with editor_container:
                    editor = (
                        ui.codemirror(
                            "",
                            language="JSON",
                            theme="dracula",
                            line_wrapping=True,
                        )
                        .classes("w-full")
                        .style("min-height: 500px")
                    )
                    if state["read_only"]:
                        editor.props("readonly")
                    editor.on_value_change(on_editor_change)
                return editor

        with ui.row().classes("gap-2"):

            async def do_save():
                nonlocal editor
                if state["read_only"]:
                    ui.notify(CONFIG_READ_ONLY_MESSAGE, type="warning")
                    return
                if editor is None:
                    await init_editor()

                with ui.dialog() as dlg, ui.card():
                    ui.label("Save Configuration?").classes("font-bold")
                    ui.label(
                        "This will create a backup (.json.bak) and "
                        "overwrite the config file."
                    ).classes("text-sm")
                    ui.label(f"File: {state['path']}").classes(
                        "text-xs text-grey-6"
                    ).style("font-family: monospace")

                    with ui.row().classes("gap-2 mt-2"):

                        async def confirm_save():
                            err = await run.io_bound(
                                _save_config_with_backup,
                                editor.value,
                                state["path"],
                            )
                            dlg.close()
                            if err:
                                ui.notify(f"Error: {err}", type="negative")
                            else:
                                ui.notify("Saved", type="positive")

                        ui.button("Save", on_click=confirm_save, color="green").props(
                            "dense"
                        )
                        ui.button("Cancel", on_click=dlg.close).props("dense flat")

                dlg.open()

            save_button = ui.button("Save", icon="save", on_click=do_save).props(
                "dense"
            )

            async def do_reload():
                nonlocal editor
                if editor is None:
                    await init_editor()

                text, path_str = await run.io_bound(
                    _load_config_by_scope, state["scope"]
                )
                state["path"] = path_str
                path_label.text = f"File: {path_str or 'N/A'}"
                editor.value = text
                _update_validation(text)
                ui.notify("Reloaded from disk", type="positive")

            ui.button("Reload", icon="refresh", on_click=do_reload).props("dense")

        def _update_validation(text):
            _, err = _validate_json(text)
            if err:
                status_label.text = f"Invalid: {err}"
                status_label.classes(replace="text-sm text-red")
            else:
                status_label.text = "Valid JSON"
                status_label.classes(replace="text-sm text-green")

        def on_editor_change(e):
            _update_validation(e.value)

        async def load_scope(scope_val=None):
            nonlocal editor
            if editor is None:
                await init_editor()

            sc = scope_val or (scope_sel.value if scope_sel else state["scope"])
            state["scope"] = sc
            config_state = await run.io_bound(get_web_config_state)
            state["read_only"] = bool(config_state.get("read_only", False))
            state["config_source"] = config_state.get("source", "")
            config_banner.clear()
            with config_banner:
                create_config_source_banner(config_state)
            apply_read_only_state()
            text, path_str = await run.io_bound(_load_config_by_scope, sc)
            state["path"] = path_str
            path_label.text = f"File: {path_str or 'N/A'}"
            editor.value = text
            _update_validation(text)

        if scope_sel is not None:

            async def on_scope_change(e):
                await load_scope(e.value)

            scope_sel.on_value_change(on_scope_change)

        ui.timer(0.1, load_scope, once=True)
