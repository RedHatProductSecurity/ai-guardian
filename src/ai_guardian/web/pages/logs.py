"""Logs page — log viewer with level filtering, clear, and source navigation."""

import platform
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar

LEVEL_PRIORITY = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

LEVEL_COLORS = {
    "DEBUG": "#888",
    "INFO": "#4caf50",
    "WARNING": "#ff9800",
    "ERROR": "#f44336",
    "CRITICAL": "#f44336",
}


def _parse_log_line(line: str) -> Optional[Tuple[str, str, str, str]]:
    parts = line.split(" - ")
    if len(parts) >= 4:
        timestamp = parts[0].strip()
        if len(parts) == 5:
            module = parts[2].strip()
            level = parts[3].strip()
            message = parts[4].strip()
        else:
            module = parts[1].strip()
            level = parts[2].strip()
            message = parts[3].strip()
        if level in LEVEL_PRIORITY:
            return (timestamp, module, level, message)
    return None


def _should_show(level: str, min_level: str) -> bool:
    return LEVEL_PRIORITY.get(level, 0) >= LEVEL_PRIORITY.get(min_level, 0)


def _read_last_n_lines(file_path: Path, n: int) -> List[str]:
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return lines[-n:] if len(lines) > n else lines
    except OSError:
        return []


def _get_log_path() -> Path:
    from ai_guardian.config.utils import get_state_dir

    return get_state_dir() / "ai-guardian.log"


def _clear_log_file():
    path = _get_log_path()
    if path.exists():
        with open(path, "w") as f:
            pass
    return True


def _open_log_file():
    path = _get_log_path()
    if not path.exists():
        return False
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", str(path)])
        elif system == "Linux":
            subprocess.Popen(["xdg-open", str(path)])
        elif system == "Windows":
            subprocess.Popen(["start", "", str(path)], shell=True)
        else:
            return False
        return True
    except OSError:
        return False


def create_logs_page(service, daemon_name: str):
    """Build the log viewer page with filtering, clear, and open."""

    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/logs")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Logs").classes("text-2xl font-bold")

        from ai_guardian.web.config_helpers import is_remote_daemon

        is_remote = is_remote_daemon()

        with ui.row().classes("gap-4 items-end"):
            level_select = ui.select(
                options={
                    "DEBUG": "All (DEBUG+)",
                    "INFO": "INFO+",
                    "WARNING": "WARNING+",
                    "ERROR": "ERROR+",
                    "CRITICAL": "CRITICAL only",
                },
                value="INFO",
                label="Log Level",
            ).classes("w-48")
            ui.button(
                "Refresh",
                icon="refresh",
                on_click=lambda: load_logs(),
            )
            if not is_remote:
                ui.button(
                    "Open File",
                    icon="open_in_new",
                    on_click=lambda: _handle_open(),
                ).props("flat")

                async def _handle_clear():
                    with ui.dialog() as dialog, ui.card():
                        ui.label("Clear Log File?").classes("text-lg font-bold")
                        ui.label(
                            "This will permanently delete all log entries. "
                            "This action cannot be undone."
                        ).classes("text-sm text-red")

                        with ui.row().classes("gap-2 mt-4"):

                            async def confirm():
                                await run.io_bound(_clear_log_file)
                                dialog.close()
                                ui.notify("Log file cleared", type="positive")
                                await load_logs()

                            ui.button(
                                "Clear Log",
                                icon="delete",
                                color="red",
                                on_click=confirm,
                            )
                            ui.button(
                                "Cancel",
                                on_click=dialog.close,
                            )
                    dialog.open()

                ui.button(
                    "Clear",
                    icon="delete",
                    color="red",
                    on_click=_handle_clear,
                ).props("flat")

        def _handle_open():
            ok = _open_log_file()
            if not ok:
                log_path = _get_log_path()
                ui.notify(f"Log file: {log_path}", type="info")

        log_path_label = ui.label("").classes("text-xs text-grey-7")
        content = ui.column().classes("w-full gap-0")

        async def load_logs():
            content.clear()
            from ai_guardian.web.config_helpers import load_web_logs

            min_level = level_select.value
            result = await run.io_bound(load_web_logs, 500, min_level)

            if result is None:
                with content:
                    ui.label("Failed to load logs.").classes("text-grey-6")
                return

            log_path_str = result.get("log_path", "")
            if log_path_str:
                log_path_label.text = f"File: {log_path_str}"

            entries = result.get("entries", [])

            with content:
                ui.label(f"{len(entries)} entries (showing {min_level}+)").classes(
                    "text-xs text-grey-6 mb-2"
                )

                if not entries:
                    ui.label("No log entries match the filter.").classes("text-grey-6")
                    return

                parts = []
                for entry in reversed(entries):
                    ts = entry.get("timestamp", "")
                    mod = entry.get("module", "")
                    lvl = entry.get("level", "DEBUG")
                    msg = entry.get("message", "")
                    color = LEVEL_COLORS.get(lvl, "#888")
                    ts_html = f'<span style="color:#666">{ts}</span> ' if ts else ""
                    mod_html = (
                        f'<span style="color:#4fc3f7">{mod}</span> ' if mod else ""
                    )
                    lvl_short = {"WARNING": "WARN", "CRITICAL": "CRIT"}.get(lvl, lvl)
                    bold = " font-weight:bold;" if lvl == "CRITICAL" else ""
                    lvl_html = (
                        f'<span style="color:{color};{bold}">' f"{lvl_short}</span>"
                    )
                    safe_msg = (
                        msg.replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                    )
                    parts.append(f"{ts_html}{mod_html}{lvl_html} {safe_msg}")

                html = "<br>".join(parts)
                ui.html(
                    f'<pre style="font-family:monospace;font-size:12px;'
                    f"line-height:1.4;max-height:600px;overflow:auto;"
                    f"background:#1a1a2e;padding:12px;border-radius:8px;"
                    f'color:#e0e0e0">{html}</pre>'
                )

        level_select.on_value_change(lambda: load_logs())
        ui.timer(0.1, load_logs, once=True)
