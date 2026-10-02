"""NiceGUI target selector for multi-target tray plugin commands."""

import json


def _target_label(target: dict) -> str:
    """Build a display label for a target dict."""
    name = target.get("name", "unknown")
    runtime = target.get("runtime", "unknown")
    display_runtime = target.get("runtime_type") or runtime

    if runtime == "container":
        if display_runtime != "container":
            return f"{name} ({display_runtime})"
        cname = target.get("container_name")
        if cname and cname != name:
            return f"{name} (container: {cname})"
        return f"{name} (container)"

    if runtime == "kubernetes":
        pod = target.get("pod_name") or ""
        return f"{name} (k8s: {pod})" if pod else f"{name} (k8s)"

    if runtime == "local":
        return f"{name} (local)"

    return f"{name} ({runtime})"


class TrayTargetSelectorApp:
    """Interactive multi-select target picker backed by NiceGUI."""

    def __init__(self, targets: list):
        self._targets = targets

    def run(self):
        from nicegui import app, ui

        result_holder = {"value": None}
        finished = {"done": False}
        checkboxes = []

        def close() -> None:
            finished["done"] = True
            ui.run_javascript("window.close()")
            ui.timer(0.5, app.shutdown, once=True)

        def cancel() -> None:
            result_holder["value"] = None
            close()

        def select_all() -> None:
            for checkbox in checkboxes:
                checkbox.set_value(True)

        def submit() -> None:
            selected = [
                index for index, checkbox in enumerate(checkboxes) if checkbox.value
            ]
            if not selected:
                ui.notify("Select at least one target", type="negative")
                return
            result_holder["value"] = json.dumps(selected)
            close()

        def on_disconnect() -> None:
            if not finished["done"]:
                result_holder["value"] = None
            app.shutdown()

        @ui.page("/")
        def target_page() -> None:
            ui.query("body").style("background: #1a1a2e")
            with (
                ui.card()
                .classes("mx-auto mt-8")
                .style("min-width: 420px; max-width: 720px")
            ):
                ui.label("Select targets").classes("text-xl font-bold")
                for target in self._targets:
                    checkbox = ui.checkbox(_target_label(target), value=True)
                    checkboxes.append(checkbox)
                with ui.row().classes("w-full justify-end"):
                    ui.button("Cancel", on_click=cancel).props("flat")
                    ui.button("Select all", on_click=select_all).props("flat")
                    ui.button("OK", on_click=submit, color="primary")

        from ai_guardian.desktop_utils import open_url
        from ai_guardian.ui.tray_prompt import _find_free_port

        app.on_disconnect(on_disconnect)
        port = _find_free_port()
        app.on_startup(lambda: open_url(f"http://127.0.0.1:{port}"))
        ui.run(
            host="127.0.0.1",
            port=port,
            title="Select targets",
            dark=True,
            show=False,
            reload=False,
        )
        return result_holder["value"]
