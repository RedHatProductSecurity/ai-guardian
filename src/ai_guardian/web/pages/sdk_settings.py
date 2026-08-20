"""SDK Settings page — scanning and secret redaction toggles."""

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.config_helpers import load_web_config, save_web_config


def create_sdk_settings_page(service, daemon_name: str):
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/sdk-settings")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("SDK Settings").classes("text-2xl font-bold")
        ui.label("Global SDK scanning and secret redaction settings.").classes(
            "text-xs text-grey-6"
        )

        scanning_switch = ui.switch("SDK Scanning enabled").classes("mt-2")
        use_global_switch = ui.switch("Use global config")
        ui.label(
            "When on, SDK uses global ai-guardian.json scanner settings "
            "(per-scanner actions, thresholds, allowlists). "
            "When off, SDK runs standalone."
        ).classes("text-xs text-grey-6 ml-10 -mt-2 max-w-lg")

        redaction_switch = ui.switch("Secret redaction (SDK)")
        ui.label(
            "SDK defaults secret redaction to OFF — redacting content "
            "in the agentic loop breaks code. Traces are always sanitized "
            "regardless."
        ).classes("text-xs text-grey-6 ml-10 -mt-2 max-w-lg")

        saving = {"active": False}

        async def _save_toggle(section_path, value):
            if saving["active"]:
                return
            saving["active"] = True
            try:
                config = await run.io_bound(load_web_config)
                sdk = config.setdefault("sdk", {})
                if section_path == "scanning":
                    sdk["scanning"] = value
                elif section_path == "use_global_config":
                    sdk["use_global_config"] = value
                elif section_path == "secret_redaction.enabled":
                    sr = sdk.setdefault("secret_redaction", {})
                    sr["enabled"] = value
                await run.io_bound(save_web_config, config)
                ui.notify("Saved", type="positive", position="bottom-right")
            except Exception as exc:
                ui.notify(f"Save failed: {exc}", type="negative")
            finally:
                saving["active"] = False

        scanning_switch.on_value_change(lambda e: _save_toggle("scanning", e.value))
        use_global_switch.on_value_change(
            lambda e: _save_toggle("use_global_config", e.value)
        )
        redaction_switch.on_value_change(
            lambda e: _save_toggle("secret_redaction.enabled", e.value)
        )

        async def _load():
            config = await run.io_bound(load_web_config)
            sdk = config.get("sdk", {})
            saving["active"] = True
            scanning_switch.value = sdk.get("scanning", True)
            use_global_switch.value = sdk.get("use_global_config", True)
            sr = sdk.get("secret_redaction", {})
            redaction_switch.value = (
                sr.get("enabled", False) if isinstance(sr, dict) else False
            )
            saving["active"] = False

        ui.timer(0.1, _load, once=True)
