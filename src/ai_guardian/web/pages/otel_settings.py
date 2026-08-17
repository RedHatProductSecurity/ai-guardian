"""OTEL Export Settings page — configure OpenTelemetry live span export."""

import json
import logging

from nicegui import run, ui

from ai_guardian.config.utils import get_config_dir
from ai_guardian.web.components.header import create_header, create_sidebar

logger = logging.getLogger(__name__)


def _load_otel_config() -> dict:
    config_dir = get_config_dir()
    config_path = config_dir / "ai-guardian.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config.get("otel", {})
        except Exception as e:
            logger.warning("Failed to read otel config: %s", e)
    return {}


def _save_otel_config(otel_cfg: dict) -> None:
    config_dir = get_config_dir()
    config_path = config_dir / "ai-guardian.json"
    config = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            pass
    config["otel"] = otel_cfg
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def create_otel_settings_page(service, daemon_name: str):
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/otel-settings")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("OTEL Export Settings").classes("text-2xl font-bold")
        ui.label("Configure OpenTelemetry live span export during agent runs.").classes(
            "text-xs text-grey-6"
        )

        cfg = _load_otel_config()

        with ui.card().classes("w-full max-w-xl"):
            ui.label("Live Export Configuration").classes("text-lg font-bold")

            enabled = ui.switch(
                "Enable live OTEL export", value=cfg.get("enabled", False)
            )

            endpoint = ui.input(
                label="Collector Endpoint",
                value=cfg.get("endpoint", "http://localhost:4318"),
                placeholder="http://localhost:4318",
            ).classes("w-full")
            ui.label("Override: OTEL_EXPORTER_OTLP_ENDPOINT").classes(
                "text-xs text-grey-6 -mt-2"
            )

            service_name = ui.input(
                label="Service Name",
                value=cfg.get("service_name", "ai-guardian"),
                placeholder="ai-guardian",
            ).classes("w-full")
            ui.label("Override: OTEL_SERVICE_NAME").classes("text-xs text-grey-6 -mt-2")

            export_format = ui.select(
                label="Export Format",
                options={"otlp-json": "OTLP JSON", "otlp-proto": "OTLP Protobuf"},
                value=cfg.get("export_format", "otlp-json"),
            ).classes("w-48")

            headers = cfg.get("headers", {})
            header_str = (
                ", ".join(f"{k}={v}" for k, v in headers.items()) if headers else ""
            )
            auth_header = ui.input(
                label="Auth Headers",
                value=header_str,
                placeholder="Authorization=Bearer <token>",
            ).classes("w-full")
            ui.label(
                "Format: key=value,key=value — Override: OTEL_EXPORTER_OTLP_HEADERS"
            ).classes("text-xs text-grey-6 -mt-2")

        status_label = ui.label("").classes("text-sm")

        with ui.row().classes("gap-2"):

            async def _save():
                try:
                    hdrs = {}
                    hval = auth_header.value.strip()
                    if hval:
                        for pair in hval.split(","):
                            pair = pair.strip()
                            if "=" in pair:
                                k, v = pair.split("=", 1)
                                hdrs[k.strip()] = v.strip()

                    new_cfg = {
                        "enabled": enabled.value,
                        "endpoint": endpoint.value.strip() or "http://localhost:4318",
                        "service_name": service_name.value.strip() or "ai-guardian",
                        "export_format": export_format.value,
                    }
                    if hdrs:
                        new_cfg["headers"] = hdrs

                    await run.io_bound(lambda: _save_otel_config(new_cfg))
                    status_label.text = "Configuration saved"
                    status_label.classes("text-green", remove="text-red")
                    ui.notify("OTEL settings saved")
                except Exception as exc:
                    status_label.text = f"Save failed: {exc}"
                    status_label.classes("text-red", remove="text-green")

            ui.button("Save", icon="save", on_click=_save).props("outline")

            async def _test():
                ep = endpoint.value.strip()
                if not ep:
                    ui.notify("Enter an endpoint first", type="warning")
                    return
                url = ep.rstrip("/") + "/v1/traces"
                status_label.text = "Testing connection..."
                status_label.classes(remove="text-green text-red")
                try:
                    import requests

                    resp = await run.io_bound(
                        lambda: requests.post(
                            url,
                            json={"resourceSpans": []},
                            headers={"Content-Type": "application/json"},
                            timeout=5,
                        )
                    )
                    status_label.text = f"Connected: HTTP {resp.status_code}"
                    status_label.classes("text-green", remove="text-red")
                except Exception as exc:
                    status_label.text = f"Connection failed: {exc}"
                    status_label.classes("text-red", remove="text-green")

            ui.button("Test Connection", icon="wifi_tethering", on_click=_test).props(
                "outline"
            )
