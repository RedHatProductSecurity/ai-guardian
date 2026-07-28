"""About page — version, system, and project information."""

import platform
import sys

from nicegui import run, ui

from ai_guardian import __version__
from ai_guardian.web.components.header import create_header, create_sidebar


def create_about_page(service, daemon_name: str):
    """Create the About page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/about")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("About").classes("text-2xl font-bold")
        ui.label("Version and system information.").classes("text-xs text-grey-6")

        with ui.card().classes("w-full"):
            ui.label("AI Guardian").classes("text-lg font-bold")
            _info_row("Version", f"v{__version__}")
            _info_row(
                "Python",
                f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            )
            _info_row("Platform", platform.platform())

        with ui.card().classes("w-full"):
            ui.label("Connected Daemon").classes("text-lg font-bold")

            content = ui.column().classes("w-full gap-1")

            async def _load_daemon_info():
                from ai_guardian.web.config_helpers import load_web_stats

                stats = await run.io_bound(load_web_stats)
                content.clear()
                with content:
                    if stats:
                        _info_row("Name", daemon_name)
                        _info_row("Status", stats.get("status", "unknown"))
                        pid = stats.get("pid")
                        if pid:
                            _info_row("PID", str(pid))
                        projects = stats.get("active_project_dirs", [])
                        if projects:
                            _info_row("Active Projects", str(len(projects)))
                    else:
                        _info_row("Name", daemon_name)
                        _info_row("Status", "unavailable")

            ui.timer(0.1, _load_daemon_info, once=True)

        with ui.card().classes("w-full"):
            ui.label("Project").classes("text-lg font-bold")
            ui.link(
                "GitHub Repository",
                "https://github.com/RedHatProductSecurity/ai-guardian",
                new_tab=True,
            ).classes("text-sm text-blue-4")
            _info_row("License", "Apache-2.0")


def _info_row(label: str, value: str):
    """Render a label-value row."""
    with ui.row().classes("items-center gap-2"):
        ui.label(f"{label}:").classes("text-sm text-grey-6 w-32")
        ui.label(value).classes("text-sm")
