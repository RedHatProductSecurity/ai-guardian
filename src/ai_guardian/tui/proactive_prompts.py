"""Proactive prompt state panel for the TUI console."""

import json
import threading

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Button, Static


class ProactivePromptsContent(Container):
    """Read-only view of the local proactive prompt state file."""

    DEFAULT_CSS = """
    ProactivePromptsContent {
        height: 100%;
    }
    #proactive-header {
        margin: 1 0;
        padding: 1;
        color: $text;
    }
    #proactive-scroll {
        padding: 1;
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Proactive Prompt State[/bold]  "
            "[dim]Read-only view of the local tray state file[/dim]",
            id="proactive-header",
        )
        with VerticalScroll(id="proactive-scroll"):
            yield Static("Loading...", id="proactive-body")
        yield Button("Refresh", id="proactive-refresh")

    def on_mount(self) -> None:
        self._load_state()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "proactive-refresh":
            self._load_state()

    def _load_state(self) -> None:
        body = self.query_one("#proactive-body", Static)
        body.update("[dim]Loading...[/dim]")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            from ai_guardian.tray.proactive_prompt import (
                IDE_SETUP_STATUS_KEY,
                ProactivePromptState,
            )

            state = ProactivePromptState()
            path = state.path
            if not path.exists():
                text = f"State file: {path}\n\n[dim]File does not exist yet.[/dim]"
            else:
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw)
                lines = [f"State file: {path}\n"]

                snapshot = data.get(IDE_SETUP_STATUS_KEY)
                if isinstance(snapshot, dict):
                    checked = snapshot.get("checked_at", "unknown")
                    lines.append(
                        f"[bold]IDE/CLI Setup Status[/bold]  "
                        f"[dim](last sync: {checked})[/dim]\n"
                    )
                    integrations = snapshot.get("integrations", {})
                    if isinstance(integrations, dict):
                        for ide_type, status in sorted(integrations.items()):
                            if not isinstance(status, dict):
                                continue
                            if status.get("healthy"):
                                icon = "[green]✓[/green]"
                                label = "Configured"
                            elif status.get("excluded"):
                                icon = "[yellow]–[/yellow]"
                                label = "Excluded"
                            else:
                                icon = "[red]✗[/red]"
                                label = "Needs setup"
                            lines.append(f"  {icon} {ide_type}: {label}")
                    lines.append("")

                other_keys = [k for k in data if k != IDE_SETUP_STATUS_KEY]
                if other_keys:
                    lines.append("[bold]Other Prompt State[/bold]\n")
                    for key in sorted(other_keys):
                        val = data[key]
                        if isinstance(val, dict):
                            outcome = val.get("outcome", "recorded")
                            lines.append(f"  {key}: {outcome}")
                        else:
                            lines.append(f"  {key}: {val}")

                text = "\n".join(lines)
        except FileNotFoundError:
            text = "[dim]State file not found.[/dim]"
        except Exception as exc:
            text = f"[red]Error loading state: {exc}[/red]"

        try:
            self.app.call_from_thread(self._update_body, text)
        except Exception:
            pass

    def _update_body(self, text: str) -> None:
        body = self.query_one("#proactive-body", Static)
        body.update(text)
