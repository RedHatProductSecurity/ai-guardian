"""Daemon picker page — select which daemon to view."""

from nicegui import run, ui

from ai_guardian.web.client_state import is_client_deleted
from ai_guardian.web.components.daemon_card import daemon_card
from ai_guardian.web.components.header import create_header


def create_daemon_picker_page(service):
    """Build the daemon picker landing page."""

    create_header()

    with ui.column().classes("w-full p-8 items-center gap-6"):
        ui.label("AI Guardian Web Console").classes("text-3xl font-bold")
        ui.label("Select a daemon to view its dashboard").classes("text-grey-6")

        cards = ui.row().classes("gap-4 flex-wrap justify-center")

        async def refresh():
            if is_client_deleted(ui.context.client):
                return
            cards.clear()
            targets = await run.io_bound(service.refresh_targets)
            statuses = await run.io_bound(service.get_all_daemon_status)

            if not statuses:
                with cards:
                    ui.label(
                        "No daemons discovered. "
                        "Start one with: ai-guardian daemon start"
                    ).classes("text-grey-6")
                return

            with cards:
                for entry in statuses:
                    t = entry["target"]
                    s = entry["status"]
                    daemon_card(
                        t,
                        s,
                        on_click=lambda _t=t: ui.navigate.to(f"/{_t.name}"),
                    )

        ui.timer(10.0, refresh)
