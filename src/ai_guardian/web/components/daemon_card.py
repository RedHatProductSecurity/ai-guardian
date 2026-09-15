"""Daemon status card component for the dashboard."""

from nicegui import ui

_STATUS_STYLE = {
    "running": ("green", "check_circle"),
    "paused": ("amber", "pause_circle"),
    "error": ("red", "error"),
    "unknown": ("grey", "help"),
}


def _status_color_icon(status: str):
    return _STATUS_STYLE.get(status, ("grey", "help"))


def _format_uptime(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    hours = int(seconds / 3600)
    minutes = int((seconds % 3600) / 60)
    return f"{hours}h {minutes}m"


def daemon_card(target, stats: dict, on_click=None):
    """Render a daemon status card.

    Args:
        target: DaemonTarget instance
        stats: Stats dict from get_status() or None
        on_click: Optional callback when card is clicked
    """
    status = "unknown"
    if stats:
        if stats.get("paused"):
            status = "running"
            if stats.get("paused"):
                status = "paused"
        elif stats.get("request_count") is not None:
            status = "running"
    elif target.status:
        status = target.status

    color, icon = _status_color_icon(status)
    display_runtime = getattr(target, "runtime_type", None) or target.runtime

    with (
        ui.card().classes("w-72 cursor-pointer hover:shadow-lg").on("click", on_click)
        if on_click
        else ui.card().classes("w-72")
    ):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.icon(icon).classes(f"text-{color} text-xl")
            ui.label(target.name).classes("text-lg font-bold flex-grow")
            ui.badge(display_runtime, color="blue-grey").classes("text-xs")

        if stats:
            with ui.row().classes("gap-4 text-sm text-grey-6"):
                uptime = stats.get("uptime_seconds", 0)
                ui.label(f"Up: {_format_uptime(uptime)}")
                ui.label(f"Requests: {stats.get('request_count', 0)}")

            with ui.row().classes("gap-4 text-sm"):
                blocked = stats.get("blocked_count", 0)
                violations = stats.get("violation_count", 0)
                if blocked:
                    ui.label(f"Blocked: {blocked}").classes("text-red")
                if violations:
                    ui.label(f"Violations: {violations}").classes("text-amber")
                if not blocked and not violations:
                    ui.label("No violations").classes("text-green")

            version = stats.get("version", "")
            if version:
                ui.label(f"v{version}").classes("text-xs text-grey-7")
        else:
            ui.label("Unable to connect").classes("text-sm text-red")
