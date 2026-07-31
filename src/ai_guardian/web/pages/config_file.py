"""Config File page — read-only view of configuration files."""

import json

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.config_helpers import (
    _get_current_target,
    _is_remote_target,
    _daemon_service,
)


def _load_config_files():
    """Load both global and project config file info.

    Routes through DaemonService for both local and remote targets.
    Uses the selected project directory from the header selector.
    """
    from ai_guardian.web.config_helpers import _get_remote_project_dir

    target = _get_current_target()
    project_dir = _get_remote_project_dir()
    if target is not None and _daemon_service is not None:
        return _load_daemon_config_files(target)
    return _load_local_config_files(project_dir)


def _load_daemon_config_files(target):
    """Load config from daemon (local or remote) via DaemonService."""
    from ai_guardian.web.config_helpers import _get_remote_project_dir

    project_dir = _get_remote_project_dir()

    result = {
        "global_path": f"(daemon: {target.name})",
        "global_exists": False,
        "global_content": None,
        "project_path": project_dir,
        "project_exists": False,
        "project_content": None,
    }

    global_cfg = _daemon_service.get_config_scoped(target, "global")
    if global_cfg is not None:
        result["global_exists"] = True
        result["global_content"] = json.dumps(global_cfg, indent=2)

    if project_dir:
        project_cfg = _daemon_service.get_config_scoped(
            target, "project", project_dir=project_dir
        )
        if project_cfg:
            result["project_exists"] = True
            result["project_content"] = json.dumps(project_cfg, indent=2)

    return result


def _load_local_config_files(project_dir=None):
    """Load config from local filesystem.

    Args:
        project_dir: Explicit project directory from header selector.
            When set, looks for config in that directory.
            When None (Global only), no project config is shown.
    """
    from pathlib import Path

    from ai_guardian.config.utils import get_config_dir

    global_path = get_config_dir() / "ai-guardian.json"

    project_path = None
    if project_dir:
        from ai_guardian.config.utils import _find_config_in_dir

        project_path = _find_config_in_dir(Path(project_dir))

    result = {
        "global_path": str(global_path),
        "global_exists": global_path.exists(),
        "global_content": None,
        "project_path": str(project_path) if project_path else None,
        "project_exists": bool(project_path and project_path.exists()),
        "project_content": None,
    }

    if result["global_exists"]:
        try:
            with open(global_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            result["global_content"] = json.dumps(data, indent=2)
        except Exception as e:
            result["global_content"] = f"Error reading file: {e}"

    if result["project_exists"] and project_path:
        try:
            with open(project_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            result["project_content"] = json.dumps(data, indent=2)
        except Exception as e:
            result["project_content"] = f"Error reading file: {e}"

    return result


def create_config_file_page(service, daemon_name: str):
    """Create the Config File page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/config-file")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Config File Viewer").classes("text-2xl font-bold")
        ui.label("Read-only view of current configuration files.").classes(
            "text-xs text-grey-6"
        )

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            info = await run.io_bound(_load_config_files)

            with content:
                with ui.card().classes("w-full"):
                    ui.label("Config Sources").classes("text-lg font-bold")
                    with ui.column().classes("gap-2"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon(
                                "check_circle" if info["global_exists"] else "cancel"
                            ).classes(
                                "text-green" if info["global_exists"] else "text-red"
                            )
                            ui.label("Global:").classes("font-bold text-sm")
                            ui.label(info["global_path"]).classes(
                                "text-sm text-grey-4"
                            ).style("font-family: monospace")

                        if info["project_path"]:
                            with ui.row().classes("items-center gap-2"):
                                ui.icon(
                                    "check_circle"
                                    if info["project_exists"]
                                    else "cancel"
                                ).classes(
                                    "text-green"
                                    if info["project_exists"]
                                    else "text-red"
                                )
                                ui.label("Project:").classes("font-bold text-sm")
                                ui.label(info["project_path"]).classes(
                                    "text-sm text-grey-4"
                                ).style("font-family: monospace")

                if info["global_exists"] and info["global_content"]:
                    with ui.card().classes("w-full"):
                        ui.label("Global Configuration").classes("text-lg font-bold")
                        ui.codemirror(
                            info["global_content"],
                            language="JSON",
                            theme="dracula",
                        ).classes("w-full").props("readonly")

                if info["project_path"]:
                    with ui.card().classes("w-full"):
                        ui.label(
                            f"Project Configuration — {info['project_path']}"
                        ).classes("text-lg font-bold")
                        if info["project_exists"] and info["project_content"]:
                            ui.codemirror(
                                info["project_content"],
                                language="JSON",
                                theme="dracula",
                            ).classes("w-full").props("readonly")
                        else:
                            ui.label("No project configuration file found.").classes(
                                "text-grey-6 text-sm"
                            )

                ui.button("Refresh", icon="refresh", on_click=refresh).props("dense")

        ui.timer(0.1, refresh, once=True)
