"""Formatted content viewer modal for JSON/code content in session detail views."""

import json
import re


def detect_content_type(text):
    """Auto-detect content format from text content.

    Returns one of: 'json', 'python', 'javascript', 'yaml', 'plain'.
    """
    stripped = text.strip()

    if stripped.startswith(("{", "[")):
        try:
            json.loads(stripped)
            return "json"
        except (json.JSONDecodeError, ValueError):
            pass

    if re.search(
        r"^(function |const |let |var |import .+ from ['\"]|export |=>)", stripped, re.M
    ):
        return "javascript"

    if re.search(
        r"^(def |class |import |from .+ import |if __name__|@\w+)", stripped, re.M
    ):
        return "python"

    if re.search(r"^[\w_]+:\s*\S", stripped, re.M) and not re.search(
        r"[{}\[\]]", stripped[:200]
    ):
        return "yaml"

    return "plain"


def format_content(text, content_type):
    """Format content based on detected type. Returns (formatted_text, language)."""
    if content_type == "json":
        try:
            parsed = json.loads(text.strip())
            return json.dumps(parsed, indent=2, default=str), "json"
        except (json.JSONDecodeError, ValueError):
            return text, "json"
    if content_type == "python":
        return text, "python"
    if content_type == "javascript":
        return text, "javascript"
    if content_type == "yaml":
        return text, "yaml"
    return text, None


def show_content_viewer(title, raw_text, dialog_host=None):
    """Open a dialog modal with formatted, syntax-highlighted content.

    Args:
        dialog_host: stable container outside any auto-refresh zone.
            When provided, the dialog is created inside it so that
            container.clear() cycles do not destroy an open dialog.
    """
    from nicegui import ui

    content_type = detect_content_type(raw_text)
    formatted, language = format_content(raw_text, content_type)
    line_count = formatted.count("\n") + 1

    if dialog_host is not None:
        dialog_host.clear()
        ctx = dialog_host
    else:
        from contextlib import nullcontext

        ctx = nullcontext()

    with ctx:
        with (
            ui.dialog().props("persistent") as dialog,
            ui.card()
            .classes("w-full")
            .style(
                "max-width: 80vw; max-height: 90vh; overflow: hidden; display: flex; "
                "flex-direction: column"
            ),
        ):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(title).classes("text-lg font-bold")
                    ui.badge(content_type).classes("text-xs")
                    ui.label(f"{line_count} lines").classes("text-xs text-grey-6")
                ui.button(icon="close", on_click=dialog.close).props("flat dense round")

            with ui.scroll_area().classes("w-full flex-grow").style("max-height: 75vh"):
                if language:
                    ui.code(formatted, language=language).classes("w-full")
                else:
                    ui.html(
                        f'<pre style="white-space: pre-wrap; word-break: break-word; '
                        f'font-size: 0.8rem; line-height: 1.4">'
                        f"{_escape_html(formatted)}</pre>"
                    ).classes("w-full")

    dialog.open()


def render_view_button(title, raw_text, dialog_host=None):
    """Render a small 'View Formatted' button that opens the content viewer."""
    from nicegui import ui

    ui.button(
        "View Formatted",
        icon="code",
        on_click=lambda t=title, r=raw_text, h=dialog_host: show_content_viewer(
            t, r, h
        ),
    ).props("dense flat size=sm color=grey-7").tooltip(
        "Open in formatted viewer with syntax highlighting"
    )


def _escape_html(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )
