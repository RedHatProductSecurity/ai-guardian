"""Prompt Injection Unicode Detection page — unicode attack detection settings."""

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.config_helpers import load_web_config, save_web_config

UNICODE_CHECKS = [
    (
        "detect_zero_width",
        True,
        "Detect Zero-Width Characters",
        "Detect zero-width characters (ZWJ, ZWNJ, ZWSP) used to hide text",
    ),
    (
        "detect_bidi_override",
        True,
        "Detect BiDi Override",
        "Detect bidirectional override characters that reverse text direction",
    ),
    (
        "detect_tag_chars",
        True,
        "Detect Tag Characters",
        "Detect Unicode tag characters (U+E0000-U+E007F) used to embed invisible text",
    ),
    (
        "detect_homoglyphs",
        True,
        "Detect Homoglyphs",
        "Detect visually similar characters from different scripts (e.g., Cyrillic a vs Latin a)",
    ),
    (
        "allow_rtl_languages",
        True,
        "Allow RTL Languages",
        "Allow legitimate right-to-left scripts (Arabic, Hebrew) without triggering BiDi alerts",
    ),
    (
        "allow_emoji",
        True,
        "Allow Emoji",
        "Allow emoji characters that contain zero-width joiners",
    ),
]


def create_pi_unicode_page(service, daemon_name: str):
    """Create the Prompt Injection Unicode Detection page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/pi-unicode")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Unicode Attack Detection").classes("text-2xl font-bold")
        ui.label(
            "Configure detection of Unicode-based prompt injection techniques."
        ).classes("text-xs text-grey-6")

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)

            with content:
                pi = config.get("prompt_injection", {})
                if not isinstance(pi, dict):
                    pi = {}
                ud = pi.get("unicode_detection", {})
                if not isinstance(ud, dict):
                    ud = {}

                with ui.card().classes("w-full"):
                    ui.label("Unicode Detection Settings").classes("text-lg font-bold")
                    ui.label(
                        "Toggle individual Unicode attack detection checks."
                    ).classes("text-xs text-grey-6")

                    for key, default, label, desc in UNICODE_CHECKS:
                        current = ud.get(key, default)
                        with ui.row().classes("items-center gap-2 w-full"):
                            sw = ui.switch(label, value=bool(current)).classes(
                                "flex-grow"
                            )
                            ui.label(desc).classes("text-xs text-grey-6")

                            async def on_change(e, k=key):
                                cfg = await run.io_bound(load_web_config)
                                sect = cfg.get("prompt_injection", {})
                                if not isinstance(sect, dict):
                                    sect = {}
                                usect = sect.get("unicode_detection", {})
                                if not isinstance(usect, dict):
                                    usect = {}
                                usect[k] = e.value
                                sect["unicode_detection"] = usect
                                cfg["prompt_injection"] = sect
                                saved = await run.io_bound(save_web_config, cfg)
                                if not saved:
                                    ui.notify(
                                        "Save failed: configuration is read-only or unavailable",
                                        type="negative",
                                    )
                                    return
                                ui.notify("Saved", type="positive")

                            sw.on_value_change(on_change)

                with ui.card().classes("w-full"):
                    ui.label("Understanding Unicode Attacks").classes(
                        "text-lg font-bold"
                    )
                    ui.label(
                        "Unicode-based attacks exploit invisible or visually ambiguous characters "
                        "to hide malicious instructions within seemingly normal text."
                    ).classes("text-sm")
                    with ui.column().classes("gap-2 mt-2"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("visibility_off").classes("text-red-4")
                            ui.label(
                                "Zero-width characters can embed invisible instructions between visible words."
                            ).classes("text-xs text-grey-6")
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("swap_horiz").classes("text-red-4")
                            ui.label(
                                "Bidirectional overrides can make text appear reversed, "
                                "hiding the true reading order."
                            ).classes("text-xs text-grey-6")
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("label_off").classes("text-red-4")
                            ui.label(
                                "Tag characters from the Supplementary Special-purpose Plane "
                                "can carry entire hidden messages."
                            ).classes("text-xs text-grey-6")
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("text_fields").classes("text-red-4")
                            ui.label(
                                "Homoglyph attacks substitute look-alike characters from "
                                "other scripts to bypass keyword filters."
                            ).classes("text-xs text-grey-6")

        ui.timer(0.1, refresh, once=True)
