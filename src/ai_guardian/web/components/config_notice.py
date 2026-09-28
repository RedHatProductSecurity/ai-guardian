"""Configuration provenance notices shared by web-console pages."""

from nicegui import ui

from ai_guardian.web.config_helpers import (
    get_effective_config_scope_notice,
    get_web_config_notice,
)


def _render_config_banner(notice):
    """Render a config notice and return its display data."""
    if notice is None:
        return None

    with ui.card().classes(
        f"w-full {notice['background_class']} {notice['text_class']}"
    ):
        with ui.row().classes("items-center gap-2"):
            ui.icon(notice["icon"])
            ui.label(notice["message"]).classes("text-sm")

    return notice


def create_config_source_banner(config_state: dict):
    """Render a config-source banner when the current target needs one."""
    return _render_config_banner(get_web_config_notice(config_state))


def create_effective_config_scope_banner(project_dir=None):
    """Render the warning for the global-only effective-config view."""
    return _render_config_banner(get_effective_config_scope_notice(project_dir))
