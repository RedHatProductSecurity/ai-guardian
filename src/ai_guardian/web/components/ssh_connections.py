"""Local-only SSH pairing. Private drafts never become browser element values."""

from nicegui import run, ui

from ai_guardian.daemon.rest_transport import DaemonConnectionError
from ai_guardian.daemon.ssh_storage import SSHConnectionError
from ai_guardian.web.client_state import is_client_deleted

PAIRING_MESSAGE = "Only pair a host you are authorized to manage. OpenSSH uses your existing configuration and agent. Unknown or changed host keys are not accepted automatically."
TRUST_LABEL = "I confirm this SSH destination and daemon certificate identity"


def pairing_summary(pairing):
    profile = pairing.profile
    return (
        f"SSH destination: {profile.destination}\nDaemon: {pairing.daemon_name}\n"
        f"Remote loopback port: {pairing.port}\nTLS server identity: {profile.server_name}\n"
        f"Certificate SHA-256: {profile.certificate_sha256}\n\n"
        "Certificate trust and the authorized daemon credential came through host-key-verified SSH. "
        "Only the daemon credential and certificate trust are saved; no SSH private key or password is stored. "
        "Changed identities require a new, explicit pairing."
    )


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

        async def prepare():
            add.disable()
            feedback.set_text("Connecting to SSH daemon...")
            try:
                pairing = await run.io_bound(service.prepare_ssh_connection, host.value)
                if is_client_deleted(client):
                    return
                feedback.set_text("")
                pending = [pairing]  # Server-side, single-use confirmation state.
                with (
                    ui.dialog().props("persistent") as dialog,
                    ui.card().classes("max-w-3xl"),
                ):
                    ui.label("Verify SSH daemon identity").classes("text-xl")
                    ui.label(pairing_summary(pairing)).classes("whitespace-pre-wrap")
                    consent = ui.checkbox(TRUST_LABEL, value=False)

                    def cancel():
                        pending.clear()
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
                            feedback.set_text(
                                "SSH daemon paired. The connection is saved and reconnects automatically."
                            )
                        except (SSHConnectionError, DaemonConnectionError) as exc:
                            feedback.set_text(str(exc))
                        finally:
                            dialog.close()

                    trust = ui.button(
                        "Trust and add daemon", on_click=enroll
                    ).bind_enabled_from(consent, "value")
                    cancel_button = ui.button("Cancel", on_click=cancel)
                dialog.open()
            except (SSHConnectionError, DaemonConnectionError) as exc:
                feedback.set_text(str(exc))
            finally:
                add.enable()

        add = ui.button("Add daemon via SSH", on_click=prepare)
        saved = ui.column().classes("w-full")

        async def update_saved():
            if is_client_deleted(client):
                return
            targets = await run.io_bound(service.refresh_targets)
            saved.clear()
            with saved:
                for target in targets:
                    if target.runtime != "ssh" or not target.ssh_id:
                        continue
                    with ui.row().classes("items-center"):
                        ui.label(f"{target.name}: {target.status}")

                        async def remove(target=target):
                            pending = [target.ssh_id]
                            with ui.dialog() as dialog, ui.card():
                                ui.label(f"Remove saved SSH connection {target.name}?")
                                ui.label(
                                    "This removes the saved credential and trust and closes owned tunnels. The remote daemon is not stopped."
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
                                            "Saved SSH connection removed. The remote daemon was not stopped."
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
