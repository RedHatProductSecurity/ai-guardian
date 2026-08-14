"""Trace Viewer panel for the TUI console."""

import fnmatch
import threading

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Input, Static, Tree


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
    #traces-tree {
        padding: 1;
        height: 1fr;
    }
    #traces-filter-input {
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
                placeholder="Filter filenames (wildcard: *, ?)",
                id="traces-filter-input",
            )
            yield Button("Refresh", id="traces-refresh", variant="success")
        with VerticalScroll():
            yield Tree("Traces", id="traces-tree")

    def on_mount(self) -> None:
        tree = self.query_one("#traces-tree", Tree)
        tree.show_root = False
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
        if event.input.id == "traces-filter-input":
            self._load_traces()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "traces-filter-input":
            self._load_traces()

    def _load_traces(self) -> None:
        """Load traces in a background thread."""
        tree = self.query_one("#traces-tree", Tree)
        tree.clear()
        tree.root.add_leaf("[dim]Loading...[/dim]")

        filter_input = self.query_one("#traces-filter-input", Input)
        pattern = filter_input.value.strip() if filter_input.value else None

        def _worker():
            from ai_guardian.daemon.traces import list_traces, resolve_trace_dirs

            trace_dirs = resolve_trace_dirs()
            try:
                traces = list_traces(trace_dirs)
            except Exception:
                traces = []

            if pattern:
                traces = _filter_traces(traces, pattern)

            self.app.call_from_thread(self._render_traces, traces)

        threading.Thread(target=_worker, daemon=True).start()

    def _render_traces(self, traces) -> None:
        """Render trace list as a directory tree (called on main thread)."""
        tree = self.query_one("#traces-tree", Tree)
        tree.clear()

        if not traces:
            tree.root.add_leaf("[dim]No trace files found.[/dim]")
            return

        dirs: dict = {}
        for t in traces:
            filename = t.get("filename", "")
            parts = filename.split("/")
            if len(parts) > 1:
                subdir = "/".join(parts[:-1])
            else:
                subdir = ""

            dirs.setdefault(subdir, []).append(t)

        for subdir in sorted(dirs.keys()):
            if subdir:
                parent = tree.root.add(f"[bold]{subdir}/[/bold]")
            else:
                parent = tree.root

            for t in dirs[subdir]:
                label = _format_trace_label(t)
                parent.add_leaf(label)

        tree.root.expand_all()


def _filter_traces(traces, pattern):
    """Filter traces by filename using fnmatch wildcard pattern."""
    if not pattern.startswith("*"):
        pattern = f"*{pattern}*"
    return [t for t in traces if fnmatch.fnmatch(t.get("filename", ""), pattern)]


def _format_trace_label(t):
    active_marker = "[green]●[/green] " if t.get("is_active") else "[dim]○[/dim] "
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

    status = "[green]ACTIVE[/green]" if t.get("is_active") else f"[dim]{stop}[/dim]"

    return (
        f"{active_marker}[bold]{name}[/bold] ({model}) {status}{v_str}  "
        f"{started} | {turns} turns | {total_tok:,} tokens | {duration_str}"
    )


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
