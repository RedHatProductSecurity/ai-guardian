"""Compliance audit logging page for the web console."""

from datetime import datetime, timezone

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.help_panel import field_help_icon
from ai_guardian.web.config_helpers import load_web_config, save_web_config


def _save_audit_config(updates):
    config = load_web_config()
    section = config.setdefault("audit_logging", {})
    if not isinstance(section, dict):
        section = {}
        config["audit_logging"] = section
    section.update(updates)
    save_web_config(config)


def _save_compliance_flag(key, value):
    config = load_web_config()
    section = config.setdefault("audit_logging", {})
    if not isinstance(section, dict):
        section = {}
        config["audit_logging"] = section
    compliance = section.setdefault("compliance_mode", {})
    if not isinstance(compliance, dict):
        compliance = {}
        section["compliance_mode"] = compliance
    compliance[key] = value
    save_web_config(config)


def _enabled_value(raw):
    if isinstance(raw, dict):
        disabled_until = raw.get("disabled_until")
        if disabled_until:
            try:
                disabled_at = datetime.fromisoformat(
                    disabled_until.replace("Z", "+00:00")
                )
                if datetime.now(timezone.utc) < disabled_at:
                    return False
            except (TypeError, ValueError):
                pass
        return bool(raw.get("value", True))
    return bool(raw)


def create_audit_logging_page(service, daemon_name: str):
    """Build the compliance audit logging settings page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/audit-logging")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Compliance Audit Logging").classes("text-2xl font-bold")
        ui.label(
            "Record sanitized final hook decisions separately from violations.jsonl. "
            "Raw prompts and tool output are never persisted."
        ).classes("text-sm text-grey-6")

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)
            audit = config.get("audit_logging", {})
            if not isinstance(audit, dict):
                audit = {}
            compliance = audit.get("compliance_mode", {})
            if not isinstance(compliance, dict):
                compliance = {}

            enabled = _enabled_value(audit.get("enabled", False))
            log_all = bool(audit.get("log_all_tool_calls", True))
            masking = bool(audit.get("sensitive_data_masking", True))
            max_entries = audit.get("max_entries", 10000)
            retention_days = audit.get("retention_days", 90)
            export_format = audit.get("export_format", "json")
            if export_format not in ("json", "csv"):
                export_format = "json"

            with content:
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Audit Trail").classes("text-lg font-bold")
                        field_help_icon("audit_logging")
                    switch = ui.switch("Enabled", value=enabled)

                    async def on_enabled(event):
                        await run.io_bound(_save_audit_config, {"enabled": event.value})
                        ui.notify(
                            (
                                "Audit logging enabled"
                                if event.value
                                else "Audit logging disabled"
                            ),
                            type="positive",
                        )

                    switch.on_value_change(on_enabled)

                    log_all_checkbox = ui.checkbox(
                        "Log allowed tool calls as well as non-allow decisions",
                        value=log_all,
                    )

                    async def on_log_all(event):
                        await run.io_bound(
                            _save_audit_config, {"log_all_tool_calls": event.value}
                        )

                    log_all_checkbox.on_value_change(on_log_all)

                    masking_checkbox = ui.checkbox(
                        "Mask secrets and PII before writing records",
                        value=masking,
                    )

                    async def on_masking(event):
                        await run.io_bound(
                            _save_audit_config,
                            {"sensitive_data_masking": event.value},
                        )

                    masking_checkbox.on_value_change(on_masking)

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Compliance Markers").classes("text-lg font-bold")
                        field_help_icon("audit_logging.compliance_mode")
                    for key, label in (
                        ("soc2", "SOC 2"),
                        ("gdpr", "GDPR processing activity"),
                        ("hipaa", "HIPAA access log"),
                    ):
                        checkbox = ui.checkbox(
                            label, value=bool(compliance.get(key, False))
                        )

                        async def on_compliance(event, compliance_key=key):
                            await run.io_bound(
                                _save_compliance_flag,
                                compliance_key,
                                event.value,
                            )

                        checkbox.on_value_change(on_compliance)

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Retention and Export").classes("text-lg font-bold")
                        field_help_icon("audit_logging.retention_days")

                    max_input = (
                        ui.number(value=max_entries, min=1, step=1)
                        .props("dense outlined")
                        .classes("w-40")
                    )
                    ui.label("Max entries").classes("text-sm")

                    async def save_max(_event, inp=max_input):
                        try:
                            value = int(inp.value)
                            if value < 1:
                                raise ValueError
                        except (TypeError, ValueError):
                            ui.notify(
                                "Max entries must be a positive integer",
                                type="negative",
                            )
                            return
                        await run.io_bound(_save_audit_config, {"max_entries": value})
                        ui.notify(f"Max entries: {value}", type="positive")

                    max_input.on("blur", save_max)

                    retention_input = (
                        ui.number(value=retention_days, min=1, step=1)
                        .props("dense outlined")
                        .classes("w-40")
                    )
                    ui.label("Retention days").classes("text-sm")

                    async def save_retention(_event, inp=retention_input):
                        try:
                            value = int(inp.value)
                            if value < 1:
                                raise ValueError
                        except (TypeError, ValueError):
                            ui.notify(
                                "Retention days must be a positive integer",
                                type="negative",
                            )
                            return
                        await run.io_bound(
                            _save_audit_config, {"retention_days": value}
                        )
                        ui.notify(f"Retention: {value} days", type="positive")

                    retention_input.on("blur", save_retention)

                    format_select = ui.select(
                        {"JSON": "json", "CSV": "csv"},
                        value=export_format,
                        label="Export format",
                    ).props("dense outlined")

                    async def save_format(event):
                        await run.io_bound(
                            _save_audit_config, {"export_format": event.value}
                        )
                        ui.notify(f"Export format: {event.value}", type="positive")

                    format_select.on_value_change(save_format)

                    output_input = (
                        ui.input(
                            label="Output file",
                            value=audit.get("output_file") or "",
                            placeholder="Defaults to the state directory audit.jsonl",
                        )
                        .props("dense outlined")
                        .classes("w-full")
                    )

                    async def save_output(_event, inp=output_input):
                        await run.io_bound(
                            _save_audit_config,
                            {"output_file": inp.value.strip() or None},
                        )
                        ui.notify("Audit output path saved", type="positive")

                    output_input.on("blur", save_output)

        ui.timer(0.1, refresh, once=True)
