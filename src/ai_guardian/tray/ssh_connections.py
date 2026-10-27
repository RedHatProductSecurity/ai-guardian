"""SSH tray menus use cached state; every action runs outside the GUI thread."""

import threading
from copy import copy


def target_action(tray, target, callback):
    """Capture the selected connection generation before leaving the GUI thread."""

    def action(icon=None, _item=None):
        from ai_guardian.tray.dialog_placement import _get_tray_screen_bounds
        from ai_guardian.tray.plugins import show_dialog

        bounds = _get_tray_screen_bounds(icon)
        selected = copy(target)

        def run():
            from ai_guardian.daemon.ssh_storage import SSHConnectionError
            from ai_guardian.daemon.rest_transport import DaemonConnectionError

            try:
                if not any(item is target for item in tray._targets):
                    raise SSHConnectionError(
                        "This SSH connection was removed. Refresh the tray and select a saved connection."
                    )
                result = callback(selected)
                if result is False:
                    raise SSHConnectionError(
                        selected.error_message
                        or "The VM did not confirm the action. Check its connection and daemon version; no workstation action was requested."
                    )
            except (SSHConnectionError, DaemonConnectionError, OSError) as exc:
                show_dialog(target.name, str(exc), screen_bounds=bounds)
            finally:
                tray._refresh_event.set()

        threading.Thread(target=run, daemon=True, name="ssh-tray-action").start()

    return action


def _worker(callback):
    def action(_icon=None, _item=None):
        threading.Thread(target=callback, daemon=True, name="ssh-tray-action").start()

    return action


def open_discovery_settings(tray, *, screen_bounds=None):
    """Complete native-capable settings flow; called only from a tray worker."""
    from ai_guardian.daemon.ssh_config import load_settings, save_settings
    from ai_guardian.daemon.ssh_storage import SSHConnectionError
    from ai_guardian.ui.forms import run_form_flow

    def settings(form):
        current = load_settings()
        values = form(
            "Discover SSH aliases",
            "Discovery lists local SSH aliases at startup and refresh. It does not contact hosts or grant trust. "
            "Connecting and trusting a daemon still requires explicit identity review.\n\n"
            "Choose whether discovery is enabled, then continue to the optional prefix. "
            "Nothing is saved until Save; Cancel or Close leaves settings unchanged.",
            [
                {
                    "name": "enabled",
                    "label": "Enable SSH alias discovery",
                    "type": "bool",
                    "default": current["enabled"],
                }
            ],
            submit_label="Continue",
        )
        if not values or type(values.get("enabled")) is not bool:
            return
        enabled = values["enabled"]
        prefix = current["alias_prefix"]
        message = (
            f"SSH alias discovery: {'enabled' if enabled else 'disabled'}.\n\n"
            "Use an optional literal prefix, for example guardian-. Leave it empty to list all supported concrete aliases without renaming them.\n\n"
            "Save updates both workstation settings, not a selected remote daemon or project. "
            "Saved pairings and existing connections are unchanged. Cancel or Close saves nothing."
        )
        error = ""
        while True:
            values = form(
                "Discover SSH aliases",
                message + error,
                [
                    {
                        "name": "alias_prefix",
                        "label": "Optional alias prefix (empty lists all supported concrete aliases)",
                        "default": prefix,
                    }
                ],
                submit_label="Save",
            )
            if values is None or not isinstance(values.get("alias_prefix"), str):
                return
            prefix = values["alias_prefix"]
            try:
                save_settings(enabled, prefix)
            except SSHConnectionError as exc:
                error = "\n\n" + str(exc)
                continue
            tray._refresh_event.set()
            form(
                "Discover SSH aliases",
                "SSH alias discovery settings saved. Candidates refresh automatically; saved trust is unchanged.",
                [],
                submit_label="Close",
            )
            return

    return run_form_flow(settings, screen_bounds=screen_bounds)


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
    """SSH daemon entries now come from the shared per-daemon menu builder."""
    return build_candidate_items(tray, pystray)


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
    if not children:
        return []
    label = (
        f"SSH aliases available to pair ({len(state['aliases'])})"
        if state["aliases"]
        else "SSH alias discovery notice"
    )
    return [
        pystray.MenuItem(
            label, pystray.Menu(*children) if children else None, enabled=bool(children)
        )
    ]
