"""
Textual app for selecting daemon targets for multi-target plugin commands.

Launched by the tray via
``ai-guardian tray-target-select --targets '<json>' --output-file '<path>'``.
Displays a multi-select list of discovered daemons and writes selected
indices to the output file.
"""

import json

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import (
    Button,
    Footer,
    Header,
    SelectionList,
    Static,
)


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
        if pod:
            return f"{name} (k8s: {pod})"
        return f"{name} (k8s)"

    if runtime == "local":
        return f"{name} (local)"

    return f"{name} ({runtime})"


class TrayTargetSelectorApp(App):
    """Interactive multi-select target picker for tray plugin commands."""

    CSS = """
    #selector-container {
        padding: 1 2;
    }
    SelectionList {
        height: auto;
        max-height: 20;
        margin: 1 0;
    }
    #button-row {
        margin: 2 0 0 0;
    }
    #button-row Button {
        margin: 0 1 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, targets: list):
        super().__init__()
        self._targets = targets

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="selector-container"):
            yield Static("[bold]Select targets:[/bold]")
            selections = []
            for i, t in enumerate(self._targets):
                label = _target_label(t)
                selections.append((label, i, True))
            yield SelectionList(*selections, id="target-list")
            with Horizontal(id="button-row"):
                yield Button("Select All", id="select-all-btn")
                yield Button("OK", id="ok-btn", variant="primary")
                yield Button("Cancel", id="cancel-btn")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.exit(result=None)
        elif event.button.id == "ok-btn":
            self._submit()
        elif event.button.id == "select-all-btn":
            sl = self.query_one("#target-list", SelectionList)
            sl.select_all()

    def action_cancel(self) -> None:
        self.exit(result=None)

    def _submit(self) -> None:
        sl = self.query_one("#target-list", SelectionList)
        selected = list(sl.selected)
        if not selected:
            self.notify("Select at least one target", severity="error")
            return
        self.exit(result=json.dumps(selected))
