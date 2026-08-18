"""IDE Sessions panel for the TUI console."""

import threading
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Input, Select, Static, Tree


class IDESessionsContent(Container):
    """Content widget for the IDE Sessions panel."""

    DEFAULT_CSS = """
    IDESessionsContent {
        height: 100%;
    }
    #ide-sessions-header {
        margin: 1 0;
        padding: 1;
        color: $text;
    }
    #ide-sessions-tree {
        padding: 1;
        height: 1fr;
    }
    #ide-sessions-filter {
        width: 1fr;
    }
    #ide-sessions-detail {
        margin: 0 1;
        height: auto;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sessions = []
        self._selected_session = None
        self._newest_first = True

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]IDE Sessions[/bold]\n"
            "[dim]Browse conversations from AI coding assistants.[/dim]",
            id="ide-sessions-header",
        )
        with Horizontal():
            yield Select(
                _get_ide_options(),
                value="claude",
                id="ide-sessions-ide-select",
            )
            yield Input(
                placeholder="Filter by project or title...",
                id="ide-sessions-filter",
            )
            yield Button("Refresh", id="ide-sessions-refresh", variant="success")
            yield Button(
                "Showing: Newest ↓", id="ide-sessions-sort-toggle", variant="default"
            )
        yield Static("", id="ide-sessions-detail")
        with VerticalScroll():
            yield Tree("Sessions", id="ide-sessions-tree")

    def on_mount(self) -> None:
        tree = self.query_one("#ide-sessions-tree", Tree)
        tree.show_root = False
        self._detect_default_ide()
        self.set_interval(self._get_refresh_interval(), self._load_sessions)

    def refresh_content(self) -> None:
        self._load_sessions()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ide-sessions-refresh":
            self.refresh_content()
        elif event.button.id == "ide-sessions-sort-toggle":
            self._newest_first = not self._newest_first
            event.button.label = (
                "Showing: Newest ↓" if self._newest_first else "Showing: Oldest ↑"
            )
            self._apply_filter()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "ide-sessions-ide-select":
            self._load_sessions()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "ide-sessions-filter":
            self._apply_filter()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        node = event.node
        if node.data and isinstance(node.data, dict):
            self._selected_session = node.data
            self._show_session_detail(node.data)

    def _detect_default_ide(self) -> None:
        def _worker():
            from ai_guardian.sessions.discovery import get_default_ide

            try:
                from ai_guardian.config.loaders import get_config

                config = get_config()
            except Exception:
                config = {}

            ide = get_default_ide(config)
            self.app.call_from_thread(self._set_ide_and_load, ide)

        threading.Thread(target=_worker, daemon=True).start()

    def _get_refresh_interval(self) -> float:
        try:
            from ai_guardian.config.loaders import get_config

            cfg = get_config()
            return (
                cfg.get("sdk", {})
                .get("trace_viewer", {})
                .get("auto_refresh_interval_seconds", 5)
            )
        except Exception:
            return 5

    def _set_ide_and_load(self, ide: str) -> None:
        try:
            select = self.query_one("#ide-sessions-ide-select", Select)
            select.value = ide
            self._load_sessions()
        except Exception:
            pass

    def _load_sessions(self) -> None:
        select = self.query_one("#ide-sessions-ide-select", Select)
        ide = select.value
        if not ide:
            return

        tree = self.query_one("#ide-sessions-tree", Tree)
        tree.clear()
        tree.root.add_leaf("[dim]Loading...[/dim]")

        def _worker():
            from ai_guardian.sessions.discovery import discover_sessions

            try:
                sessions = discover_sessions(str(ide))
            except Exception:
                sessions = []

            self.app.call_from_thread(self._render_sessions, sessions)

        threading.Thread(target=_worker, daemon=True).start()

    def _render_sessions(self, sessions) -> None:
        self._sessions = sessions
        self._apply_filter()

    def _apply_filter(self) -> None:
        tree = self.query_one("#ide-sessions-tree", Tree)
        tree.clear()

        filter_input = self.query_one("#ide-sessions-filter", Input)
        query = (filter_input.value or "").strip().lower()

        filtered = self._sessions
        if query:
            filtered = [
                s
                for s in self._sessions
                if query in (s.get("title", "") or "").lower()
                or query in (s.get("project_path", "") or "").lower()
                or query in (s.get("session_id", "") or "").lower()
                or query in (s.get("model", "") or "").lower()
            ]

        filtered.sort(
            key=lambda s: s.get("modified", 0),
            reverse=self._newest_first,
        )

        if not filtered:
            tree.root.add_leaf("[dim]No sessions found.[/dim]")
            return

        projects = {}
        for s in filtered:
            proj = s.get("project_path", "") or "No project"
            projects.setdefault(proj, []).append(s)

        for proj in sorted(projects.keys()):
            parent = tree.root.add(f"[bold]{proj}[/bold]")
            for s in projects[proj]:
                label = _format_session_label(s)
                node = parent.add_leaf(label)
                node.data = s

        tree.root.expand_all()

    def _show_session_detail(self, session) -> None:
        detail = self.query_one("#ide-sessions-detail", Static)
        title = session.get("title", "") or "Untitled"
        model = session.get("model", "") or "unknown"
        msgs = session.get("message_count", 0)
        tokens = session.get("token_usage", {})
        total_in = tokens.get("input_tokens", 0)
        total_out = tokens.get("output_tokens", 0)
        cache_read = tokens.get("cache_read_input_tokens", 0)
        cache_create = tokens.get("cache_creation_input_tokens", 0)
        context = total_in + cache_read + cache_create
        sid = session.get("session_id", "")

        lines = [
            f"[bold]{title}[/bold] ({model})",
            f"Session: {sid}",
            f"Context: {_fmt_tok(context)} | Input: {_fmt_tok(total_in)} "
            f"| Cache Read: {_fmt_tok(cache_read)} "
            f"| Cache Create: {_fmt_tok(cache_create)} "
            f"| Output: {_fmt_tok(total_out)}",
            f"Messages: {msgs}",
        ]

        if sid:
            self._load_session_violations(sid, detail, lines)
        else:
            detail.update("\n".join(lines))

    def _load_session_violations(self, session_id, detail_widget, base_lines):
        def _worker():
            try:
                from ai_guardian.violations.logger import ViolationLogger

                violations = ViolationLogger().get_recent_violations(
                    limit=1000, session_id=session_id
                )
            except Exception:
                violations = []
            self.app.call_from_thread(
                self._render_detail_with_violations,
                detail_widget,
                base_lines,
                violations,
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _render_detail_with_violations(self, detail_widget, base_lines, violations):
        lines = list(base_lines)
        if violations:
            by_type = {}
            for v in violations:
                vtype = v.get("violation_type", "unknown")
                by_type.setdefault(vtype, []).append(v)
            parts = [
                f"{len(items)} {vtype}" for vtype, items in sorted(by_type.items())
            ]
            lines.append(
                f"[bold red]Violations: {len(violations)}[/bold red] ({', '.join(parts)})"
            )
        detail_widget.update("\n".join(lines))


def _get_ide_options():
    from ai_guardian.sessions.discovery import get_supported_ides

    return [(ide.title(), ide) for ide in get_supported_ides()]


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


def _format_session_label(session):
    title = session.get("title", "") or "Untitled"
    model = session.get("model", "") or ""
    msgs = session.get("message_count", 0)
    tokens = session.get("token_usage", {})
    total_in = tokens.get("input_tokens", 0)
    cache_read = tokens.get("cache_read_input_tokens", 0)
    cache_create = tokens.get("cache_creation_input_tokens", 0)
    context = total_in + cache_read + cache_create

    modified = session.get("modified", 0)
    if modified:
        try:
            dt = datetime.fromtimestamp(modified)
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            date_str = ""
    else:
        date_str = ""

    model_str = f" ({model})" if model else ""
    ctx_str = f" ctx:{_fmt_tok(context)}" if context else ""

    return f"[bold]{title}[/bold]{model_str} | {msgs} msgs{ctx_str} | {date_str}"
