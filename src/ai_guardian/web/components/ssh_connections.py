"""Local-only SSH pairing. Private drafts never become browser element values."""

from nicegui import run, ui

from ai_guardian.daemon.rest_transport import DaemonConnectionError
from ai_guardian.daemon.ssh_storage import SSHConnectionError
from ai_guardian.ui.ssh_pairing import (
    PAIRED_MESSAGE,
    PAIRING_MESSAGE,
    TRUST_LABEL,
    pairing_summary,
)
from ai_guardian.web.client_state import is_client_deleted


def create_ssh_connections(service):
    if not service.allow_ssh_pairing:
        return
    client = ui.context.client
    with ui.card().classes("w-full max-w-3xl gap-3"):
        ui.label("SSH daemon connections").classes("text-xl")
        ui.label(PAIRING_MESSAGE)
        host = ui.input(
            "Known SSH host or alias", placeholder="user@vm.example.internal"
        ).classes("w-full")
        feedback = ui.label("").classes("whitespace-pre-wrap")
        reviewing = None
        # Timer refreshes replace candidate/saved rows, not an active review.
        dialog_area = ui.element("div")

        async def prepare(*, alias=None):
            nonlocal reviewing
            if reviewing or is_client_deleted(client):
                return
            review_token = object()
            reviewing = review_token
            add.disable()
            feedback.set_text("Connecting to SSH daemon...")
            displayed = False
            try:
                if alias is None:
                    pairing = await run.io_bound(
                        service.prepare_ssh_connection, host.value
                    )
                else:
                    pairing = await run.io_bound(
                        service.prepare_discovered_ssh_connection, alias
                    )
                if is_client_deleted(client):
                    return
                feedback.set_text("")
                pending = [pairing]  # Server-side, single-use confirmation state.
                with (
                    dialog_area,
                    ui.dialog().props("persistent") as dialog,
                    ui.card().classes("max-w-3xl"),
                ):
                    ui.label("Verify SSH daemon identity").classes("text-xl")
                    ui.label(pairing_summary(pairing)).classes("whitespace-pre-wrap")
                    consent = ui.checkbox(TRUST_LABEL, value=False)

                    def finish():
                        nonlocal reviewing
                        pending.clear()
                        if reviewing is review_token:
                            reviewing = None
                            add.enable()

                    def cancel():
                        finish()
                        dialog.close()

                    async def enroll():
                        if (
                            not consent.value
                            or not pending
                            or is_client_deleted(client)
                        ):
                            return
                        draft = pending.pop()
                        trust.disable()
                        cancel_button.disable()
                        try:
                            await run.io_bound(service.enroll_ssh_connection, draft)
                            feedback.set_text(PAIRED_MESSAGE)
                        except (SSHConnectionError, DaemonConnectionError) as exc:
                            feedback.set_text(str(exc))
                        finally:
                            finish()
                            dialog.close()

                    trust = ui.button(
                        "Trust and add daemon", on_click=enroll
                    ).bind_enabled_from(consent, "value")
                    cancel_button = ui.button("Cancel", on_click=cancel)
                dialog.on("hide", finish)
                client.on_disconnect(cancel)
                displayed = True
                dialog.open()
            except (SSHConnectionError, DaemonConnectionError) as exc:
                feedback.set_text(str(exc))
            finally:
                if not displayed:
                    reviewing = None
                    add.enable()

        add = ui.button("Add daemon via SSH", on_click=prepare)
        ui.label(
            "Discover SSH aliases locally at startup and refresh. No hosts are contacted until you choose Review discovered daemon; discovery never grants trust."
        )
        discovery_enabled = ui.switch("Discover SSH aliases", value=False)
        alias_prefix = ui.input(
            "Optional alias prefix (empty lists all concrete aliases)",
            value="ai-guardian-",
        ).classes("w-full")
        settings_loaded = False

        async def save_settings():
            settings_button.disable()
            try:
                await run.io_bound(
                    service.save_ssh_alias_settings,
                    discovery_enabled.value,
                    alias_prefix.value,
                )
                feedback.set_text(
                    "SSH alias discovery settings saved. Candidates refresh automatically; saved trust is unchanged."
                )
                await update_saved()
            except SSHConnectionError as exc:
                feedback.set_text(str(exc))
            finally:
                settings_button.enable()

        settings_button = ui.button(
            "Save SSH discovery settings", on_click=save_settings
        )
        candidates = ui.column().classes("w-full")
        saved = ui.column().classes("w-full")

        async def update_saved():
            nonlocal settings_loaded
            if is_client_deleted(client):
                return
            targets = await run.io_bound(service.refresh_targets)
            state = await run.io_bound(service.get_ssh_alias_discovery)
            if is_client_deleted(client):
                return
            if not settings_loaded:
                discovery_enabled.set_value(state["enabled"])
                alias_prefix.set_value(state["alias_prefix"])
                settings_loaded = True
            candidates.clear()
            with candidates:
                if state["enabled"]:
                    ui.label(
                        f"SSH aliases available to pair ({len(state['aliases'])})"
                    ).classes("text-lg")
                    for notice in state["notices"]:
                        ui.label(notice).classes("text-warning")
                    for alias in state["aliases"]:
                        with ui.row().classes("items-center"):
                            ui.label(alias)

                            async def review(alias=alias):
                                await prepare(alias=alias)

                            async def dismiss(alias=alias):
                                try:
                                    await run.io_bound(service.dismiss_ssh_alias, alias)
                                    feedback.set_text(
                                        "SSH alias dismissed. It will not be offered again; manual pairing remains available."
                                    )
                                    await update_saved()
                                except SSHConnectionError as exc:
                                    feedback.set_text(str(exc))

                            ui.button("Review discovered daemon", on_click=review)
                            ui.button("Dismiss alias", on_click=dismiss)
            saved.clear()
            with saved:
                for target in targets:
                    if target.runtime != "ssh" or not target.ssh_id:
                        continue
                    with ui.row().classes("items-center"):
                        ui.label(f"{target.name}: {target.status}")

                        async def remove(target=target):
                            pending = [target.ssh_id]
                            with dialog_area, ui.dialog() as dialog, ui.card():
                                ui.label(f"Remove saved SSH connection {target.name}?")
                                ui.label(
                                    "This removes the saved credential and trust, closes owned tunnels, and dismisses this alias from discovery. The remote daemon is not stopped."
                                )

                                async def confirm():
                                    if not pending or is_client_deleted(client):
                                        return
                                    profile_id = pending.pop()
                                    remove_button.disable()
                                    try:
                                        await run.io_bound(
                                            service.remove_ssh_connection, profile_id
                                        )
                                        feedback.set_text(
                                            "Saved SSH connection removed and alias dismissed. The remote daemon was not stopped."
                                        )
                                    except SSHConnectionError as exc:
                                        feedback.set_text(str(exc))
                                    dialog.close()

                                def cancel():
                                    pending.clear()
                                    dialog.close()

                                remove_button = ui.button(
                                    "Remove connection", on_click=confirm
                                )
                                ui.button("Cancel", on_click=cancel)
                            dialog.open()

                        ui.button("Remove...", on_click=remove)

        ui.timer(5, update_saved, immediate=True)
