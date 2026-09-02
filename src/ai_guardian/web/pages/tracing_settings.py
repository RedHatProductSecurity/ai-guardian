"""Unified tracing settings page for the web console."""

from nicegui import run, ui

from ai_guardian.config.loaders import resolve_tracing_config
from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.config_helpers import load_web_config, save_web_config


def create_tracing_settings_page(service, daemon_name: str):
    """Render controls that write only the top-level tracing section."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/tracing-settings")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Tracing Settings").classes("text-2xl font-bold")
        ui.label("Unified SDK and hook trace recording and retention.").classes(
            "text-xs text-grey-6"
        )
        enabled = ui.switch("Record SDK and hook traces")
        refresh = ui.number(
            "Auto-refresh interval (seconds)", value=5, min=1, max=300, step=1
        ).classes("w-full max-w-md")
        retention = ui.number(
            "Remote trace cache retention (days)",
            value=90,
            min=1,
            max=3650,
            step=1,
        ).classes("w-full max-w-md")
        ui.label(
            "Disabling recording does not affect security scanning, OTEL export, "
            "or existing traces."
        ).classes("text-xs text-grey-6")

        saving = {"active": False}

        async def _save(key, value):
            if saving["active"]:
                return
            saving["active"] = True
            try:
                config = await run.io_bound(load_web_config)
                config.setdefault("tracing", {})[key] = value
                await run.io_bound(save_web_config, config)
                ui.notify("Saved", type="positive", position="bottom-right")
            except Exception as exc:
                ui.notify(f"Save failed: {exc}", type="negative")
            finally:
                saving["active"] = False

        enabled.on_value_change(lambda event: _save("enabled", event.value))
        refresh.on_value_change(
            lambda event: _save("auto_refresh_interval_seconds", int(event.value))
        )
        retention.on_value_change(
            lambda event: _save("trace_cache_retention_days", int(event.value))
        )

        async def _load():
            config = await run.io_bound(load_web_config)
            tracing = resolve_tracing_config(config)
            saving["active"] = True
            enabled.value = tracing["enabled"]
            refresh.value = tracing["auto_refresh_interval_seconds"]
            retention.value = tracing["trace_cache_retention_days"]
            saving["active"] = False

        ui.timer(0.1, _load, once=True)
