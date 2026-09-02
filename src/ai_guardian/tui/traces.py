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
    #traces-top-input {
        width: 10;
    }
    #traces-page-info {
        width: auto;
        margin: 0 1;
    }
    #traces-export-status {
        margin: 0 1;
        height: auto;
    }
    """

    PAGE_SIZE = 50

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_export_path = None
        self._selected_filename = None
        self._newest_first = True
        self._page = 1
        self._all_traces = []

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Sessions[/bold]\n"
            "[dim]Unified SDK and hook security traces. Non-SDK agents provide "
            "the SDK run_id in hook events or AI_GUARDIAN_RUN_ID.[/dim]",
            id="traces-header",
        )
        with Horizontal():
            yield Input(
                placeholder="Filter filenames (wildcard: *, ?)",
                id="traces-filter-input",
            )
            yield Input(
                value="1000",
                placeholder="Top N",
                id="traces-top-input",
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
        with Horizontal():
            yield Button("◀ Prev", id="traces-prev-page", variant="default")
            yield Static("", id="traces-page-info")
            yield Button("Next ▶", id="traces-next-page", variant="default")
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
            self._page = 1
            self.refresh_content()
        elif event.button.id == "traces-sort-toggle":
            self._newest_first = not self._newest_first
            self._page = 1
            event.button.label = (
                "Showing: Newest ↓" if self._newest_first else "Showing: Oldest ↑"
            )
            self._load_traces()
        elif event.button.id == "traces-prev-page":
            if self._page > 1:
                self._page -= 1
                self._render_current_page()
        elif event.button.id == "traces-next-page":
            total = len(self._all_traces)
            total_pages = max(1, -(-total // self.PAGE_SIZE))
            if self._page < total_pages:
                self._page += 1
                self._render_current_page()
        elif event.button.id == "traces-export-otlp":
            self._export_otlp()
        elif event.button.id == "traces-open-folder":
            if self._last_export_path:
                import os

                from ai_guardian.desktop_utils import open_url

                folder = os.path.dirname(self._last_export_path)
                open_url(f"file://{folder}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id in ("traces-filter-input", "traces-top-input"):
            self._page = 1
            self._load_traces()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "traces-filter-input":
            self._page = 1
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

        top_input = self.query_one("#traces-top-input", Input)
        try:
            limit = int(top_input.value.strip()) if top_input.value.strip() else 1000
        except ValueError:
            limit = 1000

        def _worker():
            from ai_guardian.daemon.traces import list_traces, resolve_trace_dirs

            trace_dirs = resolve_trace_dirs()
            try:
                traces = list_traces(trace_dirs, limit=limit)
            except Exception:
                traces = []

            if pattern:
                traces = _filter_traces(traces, pattern)

            newest = self._newest_first
            self.app.call_from_thread(self._on_traces_loaded, traces, newest)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_traces_loaded(self, traces, newest_first=True) -> None:
        """Store loaded traces and render current page."""
        traces.sort(key=lambda t: t.get("started_at", ""), reverse=newest_first)
        self._all_traces = traces
        total_pages = max(1, -(-len(traces) // self.PAGE_SIZE))
        self._page = max(1, min(self._page, total_pages))
        self._render_current_page()

    def _render_current_page(self) -> None:
        """Render the current page of traces."""
        total = len(self._all_traces)
        total_pages = max(1, -(-total // self.PAGE_SIZE))
        page = self._page
        start = (page - 1) * self.PAGE_SIZE
        page_traces = self._all_traces[start : start + self.PAGE_SIZE]

        self._render_traces(page_traces, self._newest_first)

        page_info = self.query_one("#traces-page-info", Static)
        page_info.update(f"Page {page} of {total_pages} ({total} matches)")

    def _render_traces(self, traces, newest_first=True) -> None:
        """Render trace list as a directory tree (called on main thread)."""
        from ai_guardian.daemon.traces import group_traces_by_run

        tree = self.query_one("#traces-tree", Tree)
        tree.clear()

        if not traces:
            tree.root.add_leaf("[dim]No trace files found.[/dim]")
            return

        traces.sort(key=lambda t: t.get("started_at", ""), reverse=newest_first)
        grouped = group_traces_by_run(traces)
        if not newest_first:
            grouped.sort(key=lambda t: t.get("started_at", ""))

        for item in grouped:
            if item.get("type") == "run_group":
                label = _format_run_group_label(item)
                group_node = tree.root.add(label)
                group_node.data = item
                for t in item.get("traces", []):
                    child_label = _format_trace_label(t)
                    child = group_node.add_leaf(child_label)
                    child.data = t
            else:
                label = _format_trace_label(item)
                node = tree.root.add_leaf(label)
                node.data = item

        tree.root.expand_all()

        first_trace = None
        for item in grouped:
            if item.get("type") == "run_group":
                children = item.get("traces", [])
                if children:
                    first_trace = children[0]
                    break
            else:
                first_trace = item
                break
        if first_trace:
            self._selected_filename = first_trace.get("filename")

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
    display_stop = "interrupted" if stop == "crashed" else stop

    if t.get("is_active"):
        active_marker = "[green]●[/green] "
        status = "[green]ACTIVE[/green]"
    elif display_stop == "error":
        active_marker = "[red]✕[/red] "
        status = "[red]ERROR[/red]"
    elif display_stop == "interrupted":
        active_marker = "[yellow]⚡[/yellow] "
        status = "[yellow]INTERRUPTED[/yellow]"
    else:
        active_marker = "[dim]○[/dim] "
        status = f"[dim]{display_stop}[/dim]"

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


def _format_run_group_label(group):
    """Format a run group label for the TUI tree."""
    run_id = group.get("run_id", "")
    run_label = run_id
    agent_count = group.get("agent_count", 0)
    total_duration = group.get("total_duration", 0)
    total_violations = group.get("total_violations", 0)
    is_active = group.get("is_active", False)
    started = (group.get("started_at") or "")[:19]

    duration_str = _format_duration(total_duration)

    if is_active:
        marker = "[green]●[/green] "
    else:
        marker = "[blue]◆[/blue] "

    v_str = f" [red]({total_violations} violations)[/red]" if total_violations else ""

    return (
        f"{marker}[bold]{run_label}[/bold]  "
        f"{agent_count} agent{'s' if agent_count != 1 else ''}{v_str}  "
        f"{started} | {duration_str}"
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
