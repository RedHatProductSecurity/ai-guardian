"""Trace Viewer panel for the TUI console."""

import fnmatch
import json
import tempfile
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
    #traces-export-status {
        margin: 0 1;
        height: auto;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_export_path = None
        self._selected_filename = None
        self._newest_first = True

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
            yield Button(
                "Showing: Newest ↓", id="traces-sort-toggle", variant="default"
            )
            yield Button("Export OTLP", id="traces-export-otlp", variant="default")
            yield Button(
                "Open Folder",
                id="traces-open-folder",
                variant="default",
                disabled=True,
            )
        yield Static("", id="traces-export-status")
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
        elif event.button.id == "traces-sort-toggle":
            self._newest_first = not self._newest_first
            event.button.label = (
                "Showing: Newest ↓" if self._newest_first else "Showing: Oldest ↑"
            )
            self._load_traces()
        elif event.button.id == "traces-export-otlp":
            self._export_otlp()
        elif event.button.id == "traces-open-folder":
            if self._last_export_path:
                import os

                from ai_guardian.desktop_utils import open_url

                folder = os.path.dirname(self._last_export_path)
                open_url(f"file://{folder}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "traces-filter-input":
            self._load_traces()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "traces-filter-input":
            self._load_traces()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        node = event.node
        if node.data and isinstance(node.data, dict):
            self._selected_filename = node.data.get("filename")

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

            newest = self._newest_first
            self.app.call_from_thread(self._render_traces, traces, newest)

        threading.Thread(target=_worker, daemon=True).start()

    def _render_traces(self, traces, newest_first=True) -> None:
        """Render trace list as a directory tree (called on main thread)."""
        tree = self.query_one("#traces-tree", Tree)
        tree.clear()

        if not traces:
            tree.root.add_leaf("[dim]No trace files found.[/dim]")
            return

        traces.sort(key=lambda t: t.get("started_at", ""), reverse=newest_first)

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
                node = parent.add_leaf(label)
                node.data = t

        tree.root.expand_all()

        if traces:
            self._selected_filename = traces[0].get("filename")

    def _export_otlp(self) -> None:
        """Export the most recent (or selected) trace as OTLP JSON."""
        status = self.query_one("#traces-export-status", Static)
        status.update("[dim]Exporting...[/dim]")

        def _worker():
            try:
                from ai_guardian.daemon.traces import (
                    read_trace_detail,
                    resolve_trace_dirs,
                )
                from ai_guardian.observability.otel_exporter import trace_to_otlp_json

                trace_dirs = resolve_trace_dirs()
                if not trace_dirs:
                    self.app.call_from_thread(
                        status.update, "[red]No trace directory found[/red]"
                    )
                    return

                filename = self._selected_filename
                if not filename:
                    self.app.call_from_thread(
                        status.update, "[red]No trace selected[/red]"
                    )
                    return

                detail = read_trace_detail(trace_dirs, filename)
                if not detail:
                    self.app.call_from_thread(
                        status.update,
                        f"[red]Could not read trace: {filename}[/red]",
                    )
                    return

                otlp = trace_to_otlp_json(detail)
                tmp = tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".otlp.json",
                    prefix="ai-guardian-trace-",
                    delete=False,
                )
                json.dump(otlp, tmp, indent=2)
                tmp.close()
                self._last_export_path = tmp.name

                self.app.call_from_thread(self._on_export_complete, tmp.name)
            except Exception as exc:
                self.app.call_from_thread(
                    status.update, f"[red]Export failed: {exc}[/red]"
                )

        threading.Thread(target=_worker, daemon=True).start()

    def _on_export_complete(self, path: str) -> None:
        status = self.query_one("#traces-export-status", Static)
        status.update(f"[green]Exported to {path}[/green]")
        open_btn = self.query_one("#traces-open-folder", Button)
        open_btn.disabled = False
        self.app.notify(f"OTLP JSON exported to {path}")


def _filter_traces(traces, pattern):
    """Filter traces by filename using fnmatch wildcard pattern."""
    if not pattern.startswith("*"):
        pattern = f"*{pattern}*"
    return [t for t in traces if fnmatch.fnmatch(t.get("filename", ""), pattern)]


def _fmt_tok(n):
    """Format token count with k/M suffix."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        s = f"{n / 1000:.1f}"
        if s.endswith(".0"):
            s = s[:-2]
        return f"{s}k"
    s = f"{n / 1_000_000:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return f"{s}M"


def _format_trace_label(t):
    name = t.get("agent_name", "unknown")
    model = t.get("model", "")
    turns = t.get("total_turns", 0)
    started = (t.get("started_at") or "")[:19]
    stop = t.get("stop_reason", "")

    if t.get("is_active"):
        active_marker = "[green]●[/green] "
        status = "[green]ACTIVE[/green]"
    elif stop in ("error", "crashed"):
        active_marker = "[red]✕[/red] "
        status = f"[red]{stop.upper()}[/red]"
    elif stop == "interrupted":
        active_marker = "[yellow]⚡[/yellow] "
        status = "[yellow]INTERRUPTED[/yellow]"
    else:
        active_marker = "[dim]○[/dim] "
        status = f"[dim]{stop}[/dim]"

    tokens = t.get("total_tokens", {})
    total_input = tokens.get("input_tokens", 0)
    total_output = tokens.get("output_tokens", 0)
    cache_read = tokens.get("cache_read_input_tokens", 0)
    cache_create = tokens.get("cache_creation_input_tokens", 0)
    context = total_input + cache_read + cache_create

    duration = t.get("duration_seconds", 0)
    duration_str = _format_duration(duration)

    violations = t.get("violation_count", 0)
    v_str = f" [red]({violations} violations)[/red]" if violations else ""

    return (
        f"{active_marker}[bold]{name}[/bold] ({model}) {status}{v_str}  "
        f"{started} | {turns} turns | ctx:{_fmt_tok(context)} | {duration_str}"
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
