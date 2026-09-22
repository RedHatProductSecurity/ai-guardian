#!/usr/bin/env python3
"""
Logs Tab Content

Display application logs with filtering, refresh, clear, and export functionality.
"""

import re
from pathlib import Path
from typing import List, Tuple, Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Static
from textual.screen import ModalScreen
from textual.binding import Binding

from rich.markup import escape

from ai_guardian.config.utils import get_state_dir


class ConfirmClearModal(ModalScreen):
    """Modal for confirming log file clear."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = """
    ConfirmClearModal {
        align: center middle;
    }

    #modal-container {
        width: 60;
        height: auto;
        background: $panel;
        border: thick $error;
        padding: 1 2;
    }

    #modal-header {
        margin: 0 0 1 0;
        text-align: center;
        color: $error;
    }

    #modal-content {
        margin: 1 0;
        text-align: center;
    }

    #modal-actions {
        margin: 1 0 0 0;
        height: auto;
        align: center middle;
    }

    #modal-actions Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the modal."""
        with Container(id="modal-container"):
            yield Static("[bold]⚠ Clear Log File?[/bold]", id="modal-header")
            yield Static(
                "This will permanently delete all log entries.\n"
                "This action cannot be undone.",
                id="modal-content",
            )
            with Horizontal(id="modal-actions"):
                yield Button("Clear Log", id="confirm-clear", variant="error")
                yield Button("Cancel (ESC)", id="cancel-clear", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "confirm-clear":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        """Dismiss modal on ESC key."""
        self.dismiss(False)


class LogEntry(Static):
    """Display a single log entry with color coding."""

    def __init__(
        self, timestamp: str, module: str, level: str, message: str, *args, **kwargs
    ):
        """Initialize log entry."""
        self.timestamp = timestamp
        self.module = module
        self.level = level
        self.message = message

        # Color code based on level
        level_colors = {
            "DEBUG": "dim",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red bold",
        }
        level_color = level_colors.get(level, "")

        # Format the log line
        log_line = f"[dim]{escape(timestamp)}[/dim] [{level_color}]{level:8}[/{level_color}] [cyan]{escape(module)}[/cyan] {escape(message)}"

        super().__init__(log_line, *args, **kwargs)


class LogsContent(Container):
    """Content widget for Logs tab."""

    CSS = """
    LogsContent {
        height: 100%;
    }

    #logs-header {
        margin: 0 0 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_file = get_state_dir() / "ai-guardian.log"
        self.current_filter = "DEBUG"

    def compose(self) -> ComposeResult:
        """Compose the logs tab content."""
        yield Static(
            "[bold]Application Logs[/bold]  "
            "[dim]r=Refresh  x=Clear  o=Open  f=Filter[/dim]  "
            "[bold green]ALL[/bold green]",
            id="logs-header",
        )
        with VerticalScroll():
            yield Static("", id="logs-display")

    def on_mount(self) -> None:
        """Load logs when mounted."""
        self.load_logs()

    def refresh_content(self) -> None:
        """Refresh logs (called by parent app)."""
        self.load_logs()

    def action_refresh(self) -> None:
        """Refresh action for keybinding."""
        self.load_logs()

    def parse_log_line(self, line: str) -> Optional[Tuple[str, str, str, str]]:
        """
        Parse a log line into components.

        Format: 2026-04-13 12:34:56 - module.name - LEVEL - message

        Returns:
            Tuple of (timestamp, module, level, message) or None if parsing fails
        """
        # Format with version: timestamp - version - module - LEVEL - message
        pattern_v = r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - [^ ]+ - ([^ ]+) - ([A-Z]+) - (.+)$"
        match = re.match(pattern_v, line)
        if match:
            return (
                match.group(1),
                match.group(2),
                match.group(3),
                match.group(4),
            )

        # Legacy format without version: timestamp - module - LEVEL - message
        pattern = r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - ([^ ]+) - ([A-Z]+) - (.+)$"
        match = re.match(pattern, line)
        if match:
            return (
                match.group(1),
                match.group(2),
                match.group(3),
                match.group(4),
            )

        return None

    def _should_show_log(self, level: str, min_level: str) -> bool:
        """
        Determine if a log entry should be shown based on minimum level.

        Args:
            level: The log level of the entry
            min_level: The minimum level to show

        Returns:
            True if the log entry should be shown
        """
        # Log level hierarchy (lower number = more severe)
        level_priority = {
            "DEBUG": 10,
            "INFO": 20,
            "WARNING": 30,
            "ERROR": 40,
            "CRITICAL": 50,
        }

        entry_priority = level_priority.get(level, 0)
        min_priority = level_priority.get(min_level, 0)

        # Show if entry level is >= minimum level (higher severity or equal)
        return entry_priority >= min_priority

    def load_logs(self, filter_level: Optional[str] = None) -> None:
        """
        Read log file and display entries.

        Args:
            filter_level: Minimum log level to show (DEBUG, INFO, WARNING, ERROR, CRITICAL)
                         Shows this level and all higher severity levels
        """
        if filter_level is None:
            filter_level = self.current_filter
        else:
            self.current_filter = filter_level

        logs_display = self.query_one("#logs-display", Static)

        if not self.log_file.exists():
            logs_display.update(
                "No log file found.\n[dim]The log file will be created when ai-guardian runs.[/dim]"
            )
            return

        try:
            lines = self._read_last_n_lines(self.log_file, 500)

            if not lines:
                logs_display.update(
                    "Log file is empty.\n[dim]Log entries will appear here when ai-guardian runs.[/dim]"
                )
                return

            log_entries = []
            for line in lines:
                parsed = self.parse_log_line(line.strip())
                if parsed:
                    timestamp, module, level, message = parsed
                    if not self._should_show_log(level, filter_level):
                        continue
                    log_entries.append((timestamp, module, level, message))

            if not log_entries:
                logs_display.update(
                    f"No log entries at {filter_level} level or above.\n[dim]Try a lower severity level.[/dim]"
                )
                return

            level_colors = {
                "DEBUG": "dim",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red bold",
            }
            output_lines = []
            for timestamp, module, level, message in reversed(log_entries):
                lc = level_colors.get(level, "")
                output_lines.append(
                    f"[dim]{escape(timestamp)}[/dim] [{lc}]{level:8}[/{lc}] [cyan]{escape(module)}[/cyan] {escape(message)}"
                )
            logs_display.update("\n".join(output_lines))

        except Exception as e:
            logs_display.update(f"Error reading log file: {e}")

    def _read_last_n_lines(self, file_path: Path, n: int) -> List[str]:
        """
        Read the last N lines from a file efficiently.

        Args:
            file_path: Path to the file
            n: Number of lines to read

        Returns:
            List of lines (oldest first)
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                # Read all lines (for files under 5MB, this is fine)
                lines = f.readlines()
                return lines[-n:] if len(lines) > n else lines
        except Exception:
            return []

    FILTER_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    BINDINGS = [
        ("f", "cycle_filter", "Filter"),
        ("x", "log_clear", "Clear"),
        ("o", "log_open", "Open"),
    ]

    def action_cycle_filter(self) -> None:
        idx = (
            self.FILTER_LEVELS.index(self.current_filter)
            if self.current_filter in self.FILTER_LEVELS
            else 0
        )
        self.current_filter = self.FILTER_LEVELS[(idx + 1) % len(self.FILTER_LEVELS)]
        self.load_logs(filter_level=self.current_filter)
        labels = {
            "DEBUG": "ALL",
            "INFO": "INFO+",
            "WARNING": "WARN+",
            "ERROR": "ERROR+",
            "CRITICAL": "CRIT",
        }
        self.app.notify(
            f"Filter: {labels[self.current_filter]}", severity="information"
        )
        self._update_header()

    def action_log_clear(self) -> None:
        def handle_clear(confirmed: bool) -> None:
            if confirmed:
                self.clear_log_file()

        self.app.push_screen(ConfirmClearModal(), handle_clear)

    def action_log_open(self) -> None:
        self.open_log_file()

    def _update_header(self) -> None:
        labels = {
            "DEBUG": "ALL",
            "INFO": "INFO+",
            "WARNING": "WARN+",
            "ERROR": "ERROR+",
            "CRITICAL": "CRIT",
        }
        label = labels.get(self.current_filter, "ALL")
        try:
            self.query_one("#logs-header", Static).update(
                f"[bold]Application Logs[/bold]  "
                f"[dim]r=Refresh  x=Clear  o=Open  f=Filter[/dim]  "
                f"[bold green]{label}[/bold green]"
            )
        except Exception:
            pass

    def clear_log_file(self) -> None:
        """Clear the log file."""
        try:
            if self.log_file.exists():
                # Clear the file by truncating it
                with open(self.log_file, "w", encoding="utf-8") as f:
                    pass

                self.load_logs()
                self.app.notify("Log file cleared", severity="information")
            else:
                self.app.notify("No log file to clear", severity="warning")
        except Exception as e:
            self.app.notify(f"Error clearing log file: {str(e)}", severity="error")

    def open_log_file(self) -> None:
        """Open log file in default application, or show path if unavailable."""
        if not self.log_file.exists():
            self.app.notify("No log file found", severity="warning")
            return

        import platform
        import subprocess

        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.Popen(["open", str(self.log_file)])
            elif system == "Linux":
                subprocess.Popen(["xdg-open", str(self.log_file)])
            elif system == "Windows":
                subprocess.Popen(["start", "", str(self.log_file)], shell=True)
            else:
                raise OSError("Unknown platform")
            self.app.notify(f"Opened: {self.log_file}", severity="information")
        except Exception:
            self.app.notify(
                f"Log file: {self.log_file}", severity="information", timeout=10
            )
