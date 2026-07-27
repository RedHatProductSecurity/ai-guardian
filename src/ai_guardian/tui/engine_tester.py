"""
Engine Tester Panel

Test strings against individual scanner engines to compare detection
across engines and debug pattern differences.
"""

import threading

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Static, Button, Select, TextArea, Checkbox

from ai_guardian.tui.utils import quiet_logging


class EngineTesterContent(ScrollableContainer):
    """Interactive engine tester for comparing scanner engine detection."""

    CSS = """
    HookSimulatorContent, EngineTesterContent {
        overflow-x: hidden;
    }

    #et-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    .et-section {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    .et-section-title {
        margin: 0 0 1 0;
        text-style: bold;
    }

    .et-row {
        margin: 0 0 1 0;
        height: auto;
    }

    .et-row Select {
        width: 40;
    }

    .et-label {
        width: 16;
        margin: 0 1 0 0;
    }

    #et-input-area {
        height: 10;
        margin: 0 0 1 0;
    }

    #et-run-btn {
        margin: 0 2 0 0;
    }

    #et-summary {
        margin: 0 0 1 0;
    }

    #et-details {
        margin: 0;
    }
    """

    # Placeholder used at compose time; replaced with real engines in on_mount
    _PLACEHOLDER_OPTIONS = [("(loading...)", "__loading__")]

    _STRATEGY_OPTIONS = [
        ("From config", "__config__"),
        ("first-match", "first-match"),
        ("any-match", "any-match"),
        ("consensus", "consensus"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Engine Tester[/bold]  "
            "[dim]Test strings against scanner engines[/dim]",
            id="et-header",
        )

        with Container(id="et-input-section", classes="et-section"):
            yield Static("Input", classes="et-section-title")

            with Vertical(classes="et-row"):
                yield Static("Engine")
                yield Select(
                    self._PLACEHOLDER_OPTIONS,
                    value="__loading__",
                    id="et-engine-select",
                    allow_blank=False,
                )

            with Vertical(classes="et-row"):
                yield Static("Strategy")
                yield Select(
                    self._STRATEGY_OPTIONS,
                    value="__config__",
                    id="et-strategy-select",
                    allow_blank=False,
                )

            yield Static(
                "[dim]Test String — paste text to scan for secrets[/dim]",
                classes="et-row",
            )
            yield TextArea(id="et-input-area")

            with Horizontal(classes="et-row"):
                yield Checkbox(
                    "Use pattern server config",
                    id="et-pattern-server",
                    value=False,
                )

            with Horizontal(classes="et-row"):
                yield Button(
                    "Test",
                    variant="primary",
                    id="et-run-btn",
                )
                yield Button(
                    "Test All Engines",
                    variant="default",
                    id="et-run-all-btn",
                )

        with Container(id="et-results-section", classes="et-section"):
            yield Static("Results", classes="et-section-title")
            yield Static("", id="et-summary")
            yield Static("", id="et-details")

    def on_mount(self) -> None:
        self.query_one("#et-results-section").display = False
        self._populate_engines()
        self._populate_strategy()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "et-run-btn":
            self._run_single()
        elif event.button.id == "et-run-all-btn":
            self._run_all()

    def refresh_content(self) -> None:
        self._populate_engines()
        self._populate_strategy()
        self._clear_results()

    def action_refresh(self) -> None:
        self.refresh_content()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _get_engine_options():
        try:
            from ai_guardian.scanners.engine_tester import get_available_engines

            engines = get_available_engines()
        except Exception:
            engines = []
        return [(name, name) for name in engines]

    def _populate_engines(self):
        options = self._get_engine_options()
        select = self.query_one("#et-engine-select", Select)
        select.set_options(options)
        if options:
            select.value = options[0][1]

    def _populate_strategy(self):
        try:
            from ai_guardian.scanners.engine_tester import get_configured_strategy

            cfg_strategy = get_configured_strategy()
        except Exception:
            cfg_strategy = "first-match"
        options = [
            (f"From config ({cfg_strategy})", "__config__"),
            ("first-match", "first-match"),
            ("any-match", "any-match"),
            ("consensus", "consensus"),
        ]
        select = self.query_one("#et-strategy-select", Select)
        select.set_options(options)
        select.value = "__config__"

    def _clear_results(self):
        self.query_one("#et-results-section").display = False
        self.query_one("#et-summary", Static).update("")
        self.query_one("#et-details", Static).update("")

    def _get_input(self):
        return self.query_one("#et-input-area", TextArea).text

    def _use_pattern_server(self):
        return self.query_one("#et-pattern-server", Checkbox).value

    def _get_strategy(self) -> str:
        val = self.query_one("#et-strategy-select", Select).value
        if val == "__config__":
            try:
                from ai_guardian.scanners.engine_tester import get_configured_strategy

                return get_configured_strategy()
            except Exception:
                return "first-match"
        return val

    def _show_running(self, label: str):
        section = self.query_one("#et-results-section")
        section.display = True
        self.query_one("#et-summary", Static).update(
            f"[yellow]Running {label}...[/yellow]"
        )
        self.query_one("#et-details", Static).update("")

    def _run_single(self):
        sel = self.query_one("#et-engine-select", Select)
        engine = sel.value
        if engine is Select.BLANK or engine == "__none__":
            self._show_error(
                "No engine available. Install one with: "
                "ai-guardian scanner install gitleaks"
            )
            return

        text = self._get_input()
        if not text.strip():
            self._show_error("Enter text to test.")
            return

        self._show_running(engine)
        use_ps = self._use_pattern_server()

        def worker():
            try:
                with quiet_logging():
                    from ai_guardian.scanners.engine_tester import test_engine

                    result = test_engine(engine, text, use_pattern_server=use_ps)
                    self.app.call_from_thread(self._display_single, result)
            except Exception as exc:
                self.app.call_from_thread(self._show_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _run_all(self):
        text = self._get_input()
        if not text.strip():
            self._show_error("Enter text to test.")
            return

        strategy = self._get_strategy()
        self._show_running("all engines")
        use_ps = self._use_pattern_server()

        def worker():
            try:
                with quiet_logging():
                    from ai_guardian.scanners.engine_tester import (
                        test_all_engines,
                        apply_strategy,
                    )

                    results = test_all_engines(text, use_pattern_server=use_ps)
                    verdict = apply_strategy(strategy, results)
                    self.app.call_from_thread(
                        self._display_comparison, results, verdict
                    )
            except Exception as exc:
                self.app.call_from_thread(self._show_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _display_single(self, result):
        section = self.query_one("#et-results-section")
        section.display = True

        if result.error and not result.found:
            self.query_one("#et-summary", Static).update(
                f"[bold]{result.engine}[/bold]: " f"[red]ERROR[/red] — {result.error}"
            )
            self.query_one("#et-details", Static).update("")
            return

        if result.found:
            status = (
                f"[red]FOUND ({len(result.secrets)} secret"
                f"{'s' if len(result.secrets) != 1 else ''})[/red]"
            )
        else:
            status = "[green]NOT FOUND[/green]"

        mode = (
            f"  [italic]{result.scan_mode}[/italic]"
            if result.scan_mode != "subprocess"
            else ""
        )
        self.query_one("#et-summary", Static).update(
            f"[bold]{result.engine}[/bold]: {status}  "
            f"[dim]({result.scan_time_ms:.0f}ms)[/dim]{mode}"
        )

        lines = []
        for s in result.secrets:
            parts = []
            if s.rule_id:
                parts.append(f"[bold]Rule:[/bold] {s.rule_id}")
            parts.append(f"[bold]Line:[/bold] {s.line_number}")
            if s.description:
                parts.append(s.description)
            lines.append("  " + "  ".join(parts))
        self.query_one("#et-details", Static).update("\n".join(lines))

    def _display_comparison(self, results, verdict=None):
        section = self.query_one("#et-results-section")
        section.display = True

        if not results:
            self.query_one("#et-summary", Static).update(
                "[yellow]No engines installed.[/yellow]"
            )
            self.query_one("#et-details", Static).update("")
            return

        self.query_one("#et-summary", Static).update(
            "[bold]All Engines Comparison[/bold]"
        )

        lines = []
        for r in results:
            if r.error and not r.found:
                status = f"[red]ERROR[/red] — {r.error}"
            elif r.found:
                count = len(r.secrets)
                rules = ", ".join(s.rule_id for s in r.secrets if s.rule_id)
                status = (
                    f"[red]FOUND[/red] {count} secret"
                    f"{'s' if count != 1 else ''}"
                    f"  [dim]{rules}[/dim]"
                )
            else:
                status = "[green]NOT FOUND[/green]"

            mode = f", {r.scan_mode}" if r.scan_mode != "subprocess" else ""
            lines.append(
                f"  [bold]{r.engine:<14}[/bold] {status}  "
                f"[dim]({r.scan_time_ms:.0f}ms{mode})[/dim]"
            )

        if verdict:
            lines.append("")
            lines.append("─" * 50)
            decision = (
                "[red]BLOCKED[/red]" if verdict.blocked else "[green]ALLOWED[/green]"
            )
            detail = (
                f"{verdict.engines_with_secrets}/{verdict.total_engines} "
                f"engines found secrets"
            )
            if verdict.consensus_threshold is not None:
                detail += f" (threshold: {verdict.consensus_threshold})"
            lines.append(
                f"  [bold]Strategy:[/bold] {verdict.strategy}  →  "
                f"{decision}  [dim]({detail})[/dim]"
            )

        self.query_one("#et-details", Static).update("\n".join(lines))

    def _show_error(self, msg: str):
        section = self.query_one("#et-results-section")
        section.display = True
        self.query_one("#et-summary", Static).update(f"[red]{msg}[/red]")
        self.query_one("#et-details", Static).update("")
