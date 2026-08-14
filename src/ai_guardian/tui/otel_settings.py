"""OTEL Export Settings panel for the TUI console."""

import json
import logging
import threading

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Input, Label, Select, Static, Switch

from ai_guardian.config.utils import get_config_dir

logger = logging.getLogger(__name__)

FORMAT_OPTIONS = [
    ("OTLP JSON", "otlp-json"),
    ("OTLP Protobuf", "otlp-proto"),
]


def _load_otel_config() -> dict:
    config_dir = get_config_dir()
    config_path = config_dir / "ai-guardian.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config.get("sdk", {}).get("otel", {})
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
    sdk = config.setdefault("sdk", {})
    sdk["otel"] = otel_cfg
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


class OtelSettingsContent(Container):
    """Content widget for OTEL Export settings."""

    DEFAULT_CSS = """
    OtelSettingsContent {
        height: 100%;
    }
    #otel-header {
        margin: 1 0;
        padding: 1;
        color: $text;
    }
    #otel-status {
        margin: 0 1;
        height: auto;
    }
    .otel-field-row {
        height: auto;
        margin: 0 1;
        padding: 0 1;
    }
    .otel-field-label {
        width: 20;
        padding: 1 0;
    }
    .otel-field-input {
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]OTEL Export Settings[/bold]\n"
            "[dim]Configure OpenTelemetry live span export during agent runs.\n"
            "Env vars: OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME, "
            "OTEL_EXPORTER_OTLP_HEADERS[/dim]",
            id="otel-header",
        )
        with VerticalScroll():
            with Horizontal(classes="otel-field-row"):
                yield Label("Enabled", classes="otel-field-label")
                yield Switch(id="otel-enabled", value=False)

            with Horizontal(classes="otel-field-row"):
                yield Label("Endpoint", classes="otel-field-label")
                yield Input(
                    placeholder="http://localhost:4318",
                    id="otel-endpoint",
                    classes="otel-field-input",
                )

            with Horizontal(classes="otel-field-row"):
                yield Label("Service Name", classes="otel-field-label")
                yield Input(
                    placeholder="ai-guardian-sdk",
                    id="otel-service-name",
                    classes="otel-field-input",
                )

            with Horizontal(classes="otel-field-row"):
                yield Label("Export Format", classes="otel-field-label")
                yield Select(
                    FORMAT_OPTIONS,
                    value="otlp-json",
                    id="otel-format",
                )

            with Horizontal(classes="otel-field-row"):
                yield Label("Auth Header", classes="otel-field-label")
                yield Input(
                    placeholder="Authorization=Bearer <token>",
                    id="otel-auth-header",
                    classes="otel-field-input",
                )

            with Horizontal():
                yield Button("Save", id="otel-save", variant="success")
                yield Button("Test Connection", id="otel-test", variant="default")

        yield Static("", id="otel-status")

    def on_mount(self) -> None:
        self._load_config()

    def refresh_content(self) -> None:
        self._load_config()

    def _load_config(self) -> None:
        cfg = _load_otel_config()
        self.query_one("#otel-enabled", Switch).value = cfg.get("enabled", False)
        self.query_one("#otel-endpoint", Input).value = cfg.get(
            "endpoint", "http://localhost:4318"
        )
        self.query_one("#otel-service-name", Input).value = cfg.get(
            "service_name", "ai-guardian-sdk"
        )
        self.query_one("#otel-format", Select).value = cfg.get(
            "export_format", "otlp-json"
        )
        headers = cfg.get("headers", {})
        if headers:
            header_str = ", ".join(f"{k}={v}" for k, v in headers.items())
            self.query_one("#otel-auth-header", Input).value = header_str
        else:
            self.query_one("#otel-auth-header", Input).value = ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "otel-save":
            self._save_config()
        elif event.button.id == "otel-test":
            self._test_connection()

    def _save_config(self) -> None:
        status = self.query_one("#otel-status", Static)
        try:
            headers = {}
            header_str = self.query_one("#otel-auth-header", Input).value.strip()
            if header_str:
                for pair in header_str.split(","):
                    pair = pair.strip()
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        headers[k.strip()] = v.strip()

            cfg = {
                "enabled": self.query_one("#otel-enabled", Switch).value,
                "endpoint": self.query_one("#otel-endpoint", Input).value.strip()
                or "http://localhost:4318",
                "service_name": self.query_one(
                    "#otel-service-name", Input
                ).value.strip()
                or "ai-guardian-sdk",
                "export_format": self.query_one("#otel-format", Select).value,
            }
            if headers:
                cfg["headers"] = headers

            _save_otel_config(cfg)
            status.update("[green]Configuration saved[/green]")
            self.app.notify("OTEL settings saved")
        except Exception as exc:
            status.update(f"[red]Save failed: {exc}[/red]")

    def _test_connection(self) -> None:
        status = self.query_one("#otel-status", Static)
        endpoint = self.query_one("#otel-endpoint", Input).value.strip()
        if not endpoint:
            status.update("[red]Enter an endpoint first[/red]")
            return
        status.update("[dim]Testing connection...[/dim]")

        def _worker():
            import requests

            url = endpoint.rstrip("/") + "/v1/traces"
            try:
                resp = requests.post(
                    url,
                    json={"resourceSpans": []},
                    headers={"Content-Type": "application/json"},
                    timeout=5,
                )
                msg = f"[green]Connected: HTTP {resp.status_code}[/green]"
            except requests.ConnectionError:
                msg = f"[red]Connection refused: {url}[/red]"
            except Exception as exc:
                msg = f"[red]Error: {exc}[/red]"
            self.app.call_from_thread(status.update, msg)

        threading.Thread(target=_worker, daemon=True).start()
