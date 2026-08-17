"""Shared step rendering helpers for IDE Sessions and SDK Traces pages."""

import json
import urllib.parse

from nicegui import ui

STEP_ICON_MAP = {
    "user": ("person", "text-blue"),
    "assistant": ("smart_toy", "text-green"),
    "tool_use": ("build", "text-orange"),
    "tool_result": ("output", "text-orange"),
    "thinking": ("psychology", "text-purple"),
    "system": ("settings", "text-grey-6"),
    "title": ("title", "text-grey-6"),
}


def escape_html(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_text_block(text, color="text-grey-6", max_height=None):
    """Render full text in a pre-formatted block, optionally scrollable."""
    height_style = (
        f"max-height: {max_height}px; overflow-y: auto; " if max_height else ""
    )
    ui.html(
        f'<pre style="white-space: pre-wrap; word-break: break-word; '
        f"margin: 2px 0; font-size: 0.75rem; {height_style}"
        f'">{escape_html(text)}</pre>'
    ).classes(color)


def render_content_block(content, tool_input=None, step_type=""):
    """Render content with adaptive height based on line count."""
    if step_type == "tool_use" and tool_input:
        content = json.dumps(tool_input, indent=2, default=str)

    if not content:
        return

    line_count = content.count("\n") + 1
    if line_count <= 10:
        render_text_block(content, max_height=None)
    elif line_count <= 100:
        render_text_block(content, max_height=400)
    else:
        label = f"{line_count} lines — click to expand"
        exp = ui.expansion(label, value=False).classes("w-full").props("dense")
        with exp:
            render_text_block(content, max_height=None)


def render_violation_badge(violation, daemon_name=""):
    """Render a violation type badge with optional link to Violations page."""
    vtype = violation.get("type", violation.get("violation_type", "unknown"))
    msg = violation.get("message", "")

    with ui.row().classes("items-center gap-1"):
        ui.icon("warning").classes("text-red text-xs")
        ui.label(f"{vtype}:").classes("text-xs font-bold text-red")
        if daemon_name:
            vtype_param = urllib.parse.quote(vtype, safe="")
            ui.link(
                "View in Violations",
                f"/{daemon_name}/violations?type={vtype_param}",
            ).classes("text-xs")
    if msg:
        render_text_block(msg, color="text-red")


def render_violation_summary(violations, daemon_name=""):
    """Render a summary card of violations for a session."""
    if not violations:
        return

    count = len(violations)
    with ui.card().classes("w-full bg-red-9 mt-1"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("warning").classes("text-red text-sm")
            ui.label(f"{count} violation{'s' if count != 1 else ''} detected").classes(
                "text-xs font-bold text-red"
            )

        by_type = {}
        for v in violations:
            vtype = v.get("violation_type", "unknown")
            by_type.setdefault(vtype, []).append(v)

        for vtype, items in sorted(by_type.items()):
            with ui.row().classes("items-center gap-1"):
                ui.badge(f"{len(items)} {vtype}", color="red").classes("text-xs")
                if daemon_name:
                    vtype_param = urllib.parse.quote(vtype, safe="")
                    ui.link(
                        "View",
                        f"/{daemon_name}/violations?type={vtype_param}",
                    ).classes("text-xs")


def format_duration(seconds):
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"
