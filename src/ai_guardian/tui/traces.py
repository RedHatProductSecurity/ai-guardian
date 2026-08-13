"""Trace Viewer panel for the TUI console."""

import os
import threading

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Input, Static


class TracesContent(Container):
    """Content widget for the Trace Viewer panel."""

    DEFAULT_CSS = """
    TracesContent {
        height: 100%;
    }
    #traces-header {
        margin: 1 0;
        padding: 1;
        color: $text;
    }
    #traces-list {
        padding: 1;
    }
    #traces-dir-input {
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Trace Viewer[/bold]\n"
            "[dim]Conversation traces from GuardedAgent runs.[/dim]",
            id="traces-header",
        )
        with Horizontal():
            yield Input(
                placeholder="Trace directory (auto-discovered from config)",
                id="traces-dir-input",
            )
            yield Button("Refresh", id="traces-refresh", variant="success")
        with VerticalScroll():
            yield Static("Loading...", id="traces-list")

    def on_mount(self) -> None:
        self._load_traces()

    def refresh_content(self) -> None:
        self._load_traces()

    def action_refresh(self) -> None:
        self.refresh_content()
        self.app.notify("Traces refreshed")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "traces-refresh":
            self.refresh_content()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "traces-dir-input":
            self._load_traces()

    def _load_traces(self) -> None:
        """Load traces in a background thread."""
        list_widget = self.query_one("#traces-list", Static)
        list_widget.update("[dim]Loading...[/dim]")

        dir_input = self.query_one("#traces-dir-input", Input)
        custom_dir = dir_input.value.strip() if dir_input.value else None

        def _worker():
            from ai_guardian.daemon.traces import list_traces, resolve_trace_dirs

            if custom_dir:
                trace_dirs = [custom_dir]
            else:
                trace_dirs = resolve_trace_dirs()
            try:
                traces = list_traces(trace_dirs)
            except Exception:
                traces = []
            self.app.call_from_thread(self._render_traces, traces)

        threading.Thread(target=_worker, daemon=True).start()

    def _render_traces(self, traces) -> None:
        """Render trace list (called on main thread)."""
        list_widget = self.query_one("#traces-list", Static)

        if not traces:
            list_widget.update("[dim]No trace files found.[/dim]")
            return

        lines = []
        for t in traces:
            active_marker = (
                "[green]●[/green] " if t.get("is_active") else "[dim]○[/dim] "
            )
            name = t.get("agent_name", "unknown")
            model = t.get("model", "")
            turns = t.get("total_turns", 0)
            started = (t.get("started_at") or "")[:19]
            stop = t.get("stop_reason", "")

            tokens = t.get("total_tokens", {})
            total_input = tokens.get("input_tokens", 0)
            total_output = tokens.get("output_tokens", 0)
            total_tok = total_input + total_output

            duration = t.get("duration_seconds", 0)
            duration_str = _format_duration(duration)

            violations = t.get("violation_count", 0)
            v_str = f" [red]({violations} violations)[/red]" if violations else ""

            status = (
                "[green]ACTIVE[/green]" if t.get("is_active") else f"[dim]{stop}[/dim]"
            )

            lines.append(
                f"{active_marker}[bold]{name}[/bold] ({model}) {status}{v_str}\n"
                f"  Started: {started} | {turns} turns | "
                f"{total_tok:,} tokens | {duration_str}"
            )

        list_widget.update("\n\n".join(lines))


def _format_duration(seconds):
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"
