"""SSH tray menus use cached state; every action runs outside the GUI thread."""

import threading


def _worker(callback):
    def action(_icon=None, _item=None):
        threading.Thread(target=callback, daemon=True, name="ssh-tray-action").start()

    return action


def open_enrollment(tray, *, screen_bounds=None, alias=None):
    from ai_guardian.daemon.rest_transport import DaemonConnectionError
    from ai_guardian.daemon.ssh_storage import SSHConnectionError
    from ai_guardian.ui.forms import run_form_flow
    from ai_guardian.ui.ssh_pairing import (
        PAIRED_MESSAGE,
        PAIRING_MESSAGE,
        TRUST_LABEL,
        pairing_summary,
    )

    def enroll(form):
        host = alias
        if host is None:
            values = form(
                "Add daemon via SSH",
                PAIRING_MESSAGE,
                [
                    {
                        "name": "host",
                        "label": "Known SSH host or alias",
                        "required": True,
                    }
                ],
                submit_label="Connect",
            )
            if not values or not isinstance(values.get("host"), str):
                return
            host = values["host"].strip()
            if not host:
                return
        try:
            manager = tray._discovery.ssh_manager
            pairing = (
                manager.prepare(host)
                if alias is None
                else manager.prepare_discovered(alias)
            )
            consent = form(
                "Verify SSH daemon identity",
                pairing_summary(pairing),
                [
                    {
                        "name": "trust",
                        "label": TRUST_LABEL,
                        "type": "bool",
                        "default": False,
                        "required": True,
                    }
                ],
                submit_label="Trust and add daemon",
            )
            if not consent or consent.get("trust") is not True:
                return
            manager.enroll(pairing)
            tray._refresh_event.set()
            form("Add daemon via SSH", PAIRED_MESSAGE, [], submit_label="Close")
        except (SSHConnectionError, DaemonConnectionError) as exc:
            form("Add daemon via SSH", str(exc), [], submit_label="Close")

    return run_form_flow(enroll, screen_bounds=screen_bounds)


def open_management(tray):
    """Keep the explicit management picker separate from modal enrollment."""
    from ai_guardian.tray import menu
    from ai_guardian.tray.plugins import show_dialog

    if tray._ensure_web_console_ready():
        menu.open_web_console()
    else:
        show_dialog(
            "Add daemon via SSH",
            "The Web Console is unavailable. Open the local Web Console to pair or remove SSH daemon connections.",
        )


def build_items(tray, pystray):
    from ai_guardian.daemon.ssh_tunnel import POLLING_ERROR
    from ai_guardian.tray import menu
    from ai_guardian.tray.plugins import show_dialog

    items = []
    for target in tray._targets:
        if target.runtime != "ssh":
            continue

        def control(minutes, target=target):
            if tray._multi_client:
                if minutes:
                    tray._multi_client.send_pause(target, minutes)
                else:
                    tray._multi_client.send_resume(target)
                tray._refresh_event.set()

        def status(target=target):
            message = target.error_message or f"{target.name}: {target.status}"
            if (
                target.name in getattr(tray, "_ask_forwarding_failed", set())
                and POLLING_ERROR not in message
            ):
                message += "\n" + POLLING_ERROR
            show_dialog("SSH daemon", message)

        def console(target=target):
            if tray._ensure_web_console_ready():
                menu.open_web_console(target.name)

        items.append(
            pystray.MenuItem(
                lambda _item, target=target: tray._menu._version_annotated_label(
                    target
                ),
                pystray.Menu(
                    pystray.MenuItem("Status", _worker(status)),
                    pystray.MenuItem(
                        "Pause...",
                        pystray.Menu(
                            pystray.MenuItem(
                                "5 minutes", _worker(lambda control=control: control(5))
                            ),
                            pystray.MenuItem(
                                "30 minutes",
                                _worker(lambda control=control: control(30)),
                            ),
                            pystray.MenuItem(
                                "Resume", _worker(lambda control=control: control(0))
                            ),
                        ),
                        enabled=lambda _item, target=target: target.status
                        in {"running", "paused"},
                    ),
                    pystray.MenuItem("Web Console", _worker(console)),
                    pystray.MenuItem(
                        "Manage SSH connection...",
                        _worker(lambda: open_management(tray)),
                    ),
                ),
            )
        )
    return [*items, *build_candidate_items(tray, pystray)]


def build_candidate_items(tray, pystray):
    """A pending-enrollment indicator, with no network/disk work in callbacks."""
    from ai_guardian.daemon.ssh_storage import SSHConnectionError
    from ai_guardian.tray.plugins import show_dialog

    state = getattr(getattr(tray, "_discovery", None), "ssh_alias_discovery", {})
    if not isinstance(state, dict) or not state.get("enabled"):
        return []
    children = []
    for alias in state["aliases"]:

        def review(icon=None, item=None, alias=alias):
            # The tray callback captures monitor bounds before launching its worker.
            tray._on_add_ssh_daemon(icon, item, alias=alias)

        def dismiss(alias=alias):
            try:
                tray._discovery.ssh_manager.dismiss_alias(alias)
                tray._refresh_event.set()
            except SSHConnectionError as exc:
                show_dialog("SSH alias discovery", str(exc))

        children.append(
            pystray.MenuItem(
                alias,
                pystray.Menu(
                    pystray.MenuItem("Review discovered daemon", review),
                    pystray.MenuItem("Dismiss alias", _worker(dismiss)),
                ),
            )
        )
    if state["notices"]:
        notices = "\n".join(state["notices"])
        children.append(
            pystray.MenuItem(
                "SSH alias discovery notice",
                _worker(lambda: show_dialog("SSH alias discovery", notices)),
            )
        )
    label = f"SSH aliases available to pair ({len(state['aliases'])})"
    return [
        pystray.MenuItem(
            label, pystray.Menu(*children) if children else None, enabled=bool(children)
        )
    ]
