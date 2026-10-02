"""Console Settings page — editor theme, color theme, and display preferences."""

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.help_panel import field_help_icon
from ai_guardian.web.config_helpers import load_web_config, save_web_config

EDITOR_THEMES = {
    "monokai": "Monokai (dark)",
    "vscode_dark": "VS Code Dark",
    "dracula": "Dracula",
    "github_light": "GitHub Light",
}

THEME_DESCRIPTIONS = {
    "monokai": "Classic dark theme with warm accent colors — popular default for many editors.",
    "vscode_dark": "Dark theme matching Visual Studio Code's default dark color scheme.",
    "dracula": "Dark theme with vibrant purple, pink, and cyan highlights.",
    "github_light": "Light theme matching GitHub's code viewing style — good for bright environments.",
}

COLOR_THEMES = {
    "default": "Default (Blue)",
    "classic_green": "Classic Green",
    "high_contrast": "High Contrast",
    "solarized": "Solarized",
}

COLOR_THEME_DESCRIPTIONS = {
    "default": "Material dark theme with blue accents — the standard AI Guardian look.",
    "classic_green": "Original AI Guardian brand palette with green primary color.",
    "high_contrast": "Maximum contrast for accessibility — meets WCAG AA standards.",
    "solarized": "Solarized dark variant with teal and warm accents — easy on the eyes.",
}

UI_TOOLKITS = {
    "auto": "Auto (cascade)",
    "tkinter": "Tkinter (native)",
    "nicegui": "NiceGUI (browser)",
    "headless": "Headless (no UI)",
}

UI_TOOLKIT_DESCRIPTIONS = {
    "auto": "Cascade: tkinter → NiceGUI → headless.",
    "tkinter": "Native OS popup dialog. Requires Tcl/Tk system library.",
    "nicegui": "Browser-based dialog on a local port.",
    "headless": "No interactive dialogs. Ask actions use their configured fallback (block/warn/log-only).",
}


def create_console_settings_page(service, daemon_name: str):
    """Create the Console Settings page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/console-settings")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.label("Console Settings").classes("text-2xl font-bold")
            field_help_icon("console")
        ui.label("Configure console display preferences.").classes(
            "text-xs text-grey-6"
        )

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)

            with content:
                with ui.card().classes("w-full"):
                    ui.label("Color Theme").classes("text-lg font-bold")
                    ui.label(
                        "UI color palette for the web console and ask dialogs."
                    ).classes("text-xs text-grey-6")

                    color_current = config.get("console", {}).get(
                        "preferred_theme", "default"
                    )
                    color_sel = ui.select(
                        options=COLOR_THEMES,
                        value=color_current,
                    ).classes("w-64")

                    color_desc_label = ui.label(
                        COLOR_THEME_DESCRIPTIONS.get(color_current, "")
                    ).classes("text-sm text-grey-4 mt-1")

                    async def save_color_theme(e):
                        cfg = await run.io_bound(load_web_config)
                        console = cfg.get("console", {})
                        if not isinstance(console, dict):
                            console = {}
                        console["preferred_theme"] = e.value
                        cfg["console"] = console
                        await run.io_bound(save_web_config, cfg)
                        from ai_guardian.theme import set_active_theme

                        set_active_theme(e.value)
                        ui.notify(
                            f"Color theme: "
                            f"{COLOR_THEMES.get(e.value, e.value)}. "
                            f"Reloading...",
                            type="positive",
                        )
                        await ui.run_javascript(
                            "setTimeout(() => location.reload(), 500)"
                        )

                    color_sel.on_value_change(save_color_theme)

                with ui.card().classes("w-full"):
                    ui.label("Editor Theme").classes("text-lg font-bold")
                    ui.label("Theme used for JSON editors in the console.").classes(
                        "text-xs text-grey-6"
                    )

                    current = config.get("console", {}).get("editor_theme", "monokai")
                    theme_sel = ui.select(
                        options=EDITOR_THEMES,
                        value=current,
                    ).classes("w-64")

                    desc_label = ui.label(THEME_DESCRIPTIONS.get(current, "")).classes(
                        "text-sm text-grey-4 mt-1"
                    )

                    async def save_theme(e):
                        desc_label.text = THEME_DESCRIPTIONS.get(e.value, "")
                        cfg = await run.io_bound(load_web_config)
                        console = cfg.get("console", {})
                        if not isinstance(console, dict):
                            console = {}
                        console["editor_theme"] = e.value
                        cfg["console"] = console
                        await run.io_bound(save_web_config, cfg)
                        ui.notify(
                            f"Theme: {EDITOR_THEMES.get(e.value, e.value)}",
                            type="positive",
                        )

                    theme_sel.on_value_change(save_theme)

                with ui.card().classes("w-full"):
                    ui.label("Preferred UI Toolkit").classes("text-lg font-bold")
                    ui.label(
                        "UI toolkit for interactive dialogs (tray-prompt, "
                        "ask-prompt). Override with env var "
                        "AI_GUARDIAN_PREFERRED_UI."
                    ).classes("text-xs text-grey-6")

                    ui_current = config.get("console", {}).get("preferred_ui", "auto")
                    if ui_current not in UI_TOOLKITS:
                        ui_current = "nicegui"
                    ui_sel = ui.select(
                        options=UI_TOOLKITS,
                        value=ui_current,
                    ).classes("w-64")

                    ui_desc_label = ui.label(
                        UI_TOOLKIT_DESCRIPTIONS.get(ui_current, "")
                    ).classes("text-sm text-grey-4 mt-1")

                    async def save_ui_pref(e):
                        ui_desc_label.text = UI_TOOLKIT_DESCRIPTIONS.get(e.value, "")
                        cfg = await run.io_bound(load_web_config)
                        console = cfg.get("console", {})
                        if not isinstance(console, dict):
                            console = {}
                        console["preferred_ui"] = e.value
                        cfg["console"] = console
                        await run.io_bound(save_web_config, cfg)
                        ui.notify(
                            f"UI: {UI_TOOLKITS.get(e.value, e.value)}",
                            type="positive",
                        )

                    ui_sel.on_value_change(save_ui_pref)

        ui.timer(0.1, refresh, once=True)
