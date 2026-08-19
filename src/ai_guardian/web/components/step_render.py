"""Shared step rendering helpers for IDE Sessions and SDK Traces pages."""

import json
import urllib.parse

from nicegui import ui

_GUARDIAN_ICON_B64 = "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAABuklEQVR4nG2TO2tVURCFvzn35ibGB3YSBcELKWxsQrS1CNpo4Q+wsxGs/AOpbAQLC7HUX2ChNiktFIV01iHkgXko4vsdl6zrOnCMGRiYWWet2Xv2zClJJ4ELwAngAHAEGAP2Afv5a5+Br8BPYAv4BCwDj/vAOeAm8AR4F8Iv4CPwIQUOAQeBfuLjwFXgh4EB8KyqzrLLJPk2VNXWHt+eWtskH5PUkzSQNCFpXNIlYNPuONhEOL20iW8wsqrakaSq+p0TpjoHTlXV9+CNOZL4p0BMEZ4C1oA3wdcknQdeAht0rG9RlBXsCnAdOAzsBHsIvAbuADcktbj8Bu6nqsqFjgHfMlZPouKOLwLvgWG4xnu+wSow7QfK6B5U1ZKkdeBVTjpaVS8kbbtIuNPWNsBCFuZyVfmEZT9Uev0S3wi2WlVvzY1moQlwC7gtaZgp+Hrr2ZFB4sqkhuZaY22TyvNZzeeSZkwEVjJr+0rEM+aEO29t4wYz47n0vCjpGuB+3YZ9O9hiOHPtXrTDHxWSNCnprpchdl/SvU7ub5NdzX9FEs9KetQROp7di7u7SGXP2/y0pDOd3P9Lu3Aj+wNyeh1fmZqHzAAAAABJRU5ErkJggg=="  # noqa: E501
_GUARDIAN_ICON_SRC = f"data:image/png;base64,{_GUARDIAN_ICON_B64}"


def render_guardian_icon(extra_classes=""):
    """Render the ai-guardian logo inline (base64, no HTTP request, no blink)."""
    ui.html(
        f'<div style="width: 14px; height: 14px; display: inline-block; '
        "vertical-align: middle; background-color: #42a5f5; "
        f"-webkit-mask-image: url('{_GUARDIAN_ICON_SRC}'); "
        f"mask-image: url('{_GUARDIAN_ICON_SRC}'); "
        'mask-size: contain; -webkit-mask-size: contain"></div>'
    ).classes(extra_classes)


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
        .replace("'", "&#x27;")
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


def render_content_block(
    content, tool_input=None, step_type="", step_label="", dialog_host=None
):
    """Render content with adaptive height based on line count."""
    if step_type == "tool_use" and tool_input:
        content = json.dumps(tool_input, indent=2, default=str)

    if not content:
        return

    line_count = content.count("\n") + 1

    if line_count > 5 or len(content) > 200:
        from ai_guardian.web.components.content_viewer import render_view_button

        render_view_button(step_label or step_type or "Content", content, dialog_host)

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
    """Render a violation type badge with link to detail page (by ID) or filtered list."""
    vtype = violation.get("type", violation.get("violation_type", "unknown"))
    msg = violation.get("message", "")
    vid = violation.get("id", "")

    with ui.row().classes("items-center gap-1"):
        ui.icon("warning").classes("text-red text-xs")
        ui.label(f"{vtype}:").classes("text-xs font-bold text-red")
        if daemon_name:
            if vid:
                ui.link(
                    "View detail",
                    f"/{daemon_name}/violation-detail?id={vid}",
                ).classes("text-xs").tooltip("Open violation detail page")
            else:
                vtype_param = urllib.parse.quote(vtype, safe="")
                ui.link(
                    "View all",
                    f"/{daemon_name}/violations?type={vtype_param}",
                ).classes("text-xs").tooltip(f"Show all {vtype} violations")
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
            with ui.row().classes("items-center gap-1 flex-wrap"):
                ui.badge(f"{len(items)} {vtype}", color="red").classes("text-xs")
                if daemon_name:
                    for item in items:
                        vid = item.get("id", "")
                        if vid:
                            short_id = vid[-8:] if len(vid) > 8 else vid
                            ui.link(
                                short_id,
                                f"/{daemon_name}/violation-detail?id={vid}",
                            ).classes("text-xs").style(
                                "font-family: monospace"
                            ).tooltip(
                                f"View {vtype} violation {vid}"
                            )
                    vtype_param = urllib.parse.quote(vtype, safe="")
                    ui.link(
                        "View all",
                        f"/{daemon_name}/violations?type={vtype_param}",
                    ).classes("text-xs").tooltip(f"Show all {vtype} violations")


def create_sort_toggle(state, storage_key, reload_fn):
    """Create a sort order toggle button with persistent preference.

    Args:
        state: dict with a "newest_first" key (mutated in place).
        storage_key: NiceGUI app.storage.user key for persistence.
        reload_fn: async callable to refresh the view after toggling.

    Returns:
        The NiceGUI button element.
    """

    async def _toggle():
        state["newest_first"] = not state["newest_first"]
        btn.text = "Showing: Newest ↓" if state["newest_first"] else "Showing: Oldest ↑"
        try:
            from nicegui import app as _app

            _app.storage.user[storage_key] = state["newest_first"]
        except Exception:
            pass
        if reload_fn:
            await reload_fn()

    btn = ui.button(
        "Showing: Newest ↓" if state["newest_first"] else "Showing: Oldest ↑",
        on_click=_toggle,
    ).props("dense outline")
    return btn


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


def format_token_count(n):
    """Format token count with k/M suffix for readability."""
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


def compute_context_tokens(tokens_dict):
    """Compute context size: input + cache_read + cache_create."""
    return (
        tokens_dict.get("input_tokens", 0)
        + tokens_dict.get("cache_read_input_tokens", 0)
        + tokens_dict.get("cache_creation_input_tokens", 0)
    )
