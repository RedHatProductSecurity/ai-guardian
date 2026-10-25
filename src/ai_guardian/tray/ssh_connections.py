"""SSH tray menus use cached state; every action runs outside the GUI thread."""

import threading


def _worker(callback):
    def action(_icon=None, _item=None):
        threading.Thread(target=callback, daemon=True, name="ssh-tray-action").start()

    return action


def open_enrollment(tray):
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
                        _worker(lambda: open_enrollment(tray)),
                    ),
                ),
            )
        )
    return items
