"""Violation Logging page — full configuration editing."""

import logging
import json
import re
from datetime import datetime, timedelta, timezone

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.help_panel import field_help_icon
from ai_guardian.web.config_helpers import load_web_config

ALL_LOG_TYPES = [
    ("tool_permission", "Tool Permission — blocked tool/skill invocations"),
    ("directory_blocking", "Directory Blocking — protected directory access"),
    ("secret_detected", "Secret Detected — API keys, tokens, credentials"),
    ("secret_redaction", "Secret Redaction — redacted secrets in output"),
    ("prompt_injection", "Prompt Injection — injection/obfuscation attacks"),
    ("jailbreak_detected", "Jailbreak Detected — jailbreak and role-play attempts"),
    ("ssrf_blocked", "SSRF Blocked — requests to private IPs/metadata"),
    ("config_file_exfil", "Config File Exfil — config exfiltration attempts"),
    ("pii_detected", "PII Detected — personal identifiable information"),
    ("secret_in_transcript", "Secret in Transcript — secrets from ! shell commands"),
    ("pii_in_transcript", "PII in Transcript — PII from ! shell commands"),
    (
        "prompt_injection_in_transcript",
        "Injection in Transcript — prompt injection from ! shell commands",
    ),
    ("annotation_suppressed", "Annotation Suppressed — inline suppression applied"),
    (
        "middleware_paused",
        "Middleware Paused — OpenShell requests denied while enforcement is paused",
    ),
    ("image_secret_detected", "Image Secret — secrets found in images via OCR"),
    ("image_pii_detected", "Image PII — PII found in images via OCR"),
]

DURATION_RE = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?$", re.IGNORECASE)


def _parse_duration(text):
    text = text.strip()
    m = DURATION_RE.match(text)
    if not m:
        try:
            return timedelta(minutes=int(text))
        except ValueError:
            return None
    d, h, mi = int(m.group(1) or 0), int(m.group(2) or 0), int(m.group(3) or 0)
    if d == 0 and h == 0 and mi == 0:
        return None
    return timedelta(days=d, hours=h, minutes=mi)


def _save_vlog_config(updates):
    from ai_guardian.web.config_helpers import load_web_config, save_web_config

    config = load_web_config()
    if "violation_logging" not in config:
        config["violation_logging"] = {}
    config["violation_logging"].update(updates)
    save_web_config(config)


def _load_local_stats():
    from ai_guardian.web.config_helpers import load_web_violations

    result = load_web_violations()
    violations = result.get("violations", []) if result else []
    type_counts = {}
    for v in violations:
        vtype = v.get("violation_type", v.get("type", "unknown"))
        type_counts[vtype] = type_counts.get(vtype, 0) + 1
    return {"total": len(violations), "by_type": type_counts}


def _format_remaining(dt):
    remaining = dt - datetime.now(timezone.utc)
    total_secs = max(0, int(remaining.total_seconds()))
    if total_secs == 0:
        return "expired"
    d = total_secs // 86400
    h = (total_secs % 86400) // 3600
    m = (total_secs % 3600) // 60
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    return " ".join(parts) if parts else "<1m"


def create_violation_logging_page(service, daemon_name: str):
    """Build the violation logging configuration page."""

    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/violation-logging")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Violation Logging Settings").classes("text-2xl font-bold")

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)
            vlog = config.get("violation_logging", {})

            enabled_raw = vlog.get("enabled", True)
            is_temp = False
            disabled_until = None
            if isinstance(enabled_raw, dict):
                disabled_until_str = enabled_raw.get("disabled_until")
                if disabled_until_str:
                    try:
                        disabled_until = datetime.fromisoformat(
                            disabled_until_str.replace("Z", "+00:00")
                        )
                        if datetime.now(timezone.utc) < disabled_until:
                            is_temp = True
                    except (ValueError, TypeError):
                        pass  # intentionally silent — invalid value uses default
                if not is_temp:
                    enabled_raw = enabled_raw.get("value", True)

            is_enabled = not is_temp and bool(enabled_raw)
            max_entries = vlog.get("max_entries", 1000)
            retention_days = vlog.get("retention_days", 30)
            log_types = vlog.get("log_types", [t for t, _ in ALL_LOG_TYPES])

            with content:
                # --- Enable/Disable Toggle ---
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Violation Logging").classes("text-lg font-bold")
                        field_help_icon("violation_logging")
                    ui.label(
                        "Log blocked operations to JSONL file for audit and review"
                    ).classes("text-xs text-grey-6")

                    if is_temp and disabled_until:
                        remaining = _format_remaining(disabled_until)
                        reason = ""
                        if isinstance(vlog.get("enabled"), dict):
                            reason = vlog["enabled"].get("reason", "")
                        with ui.row().classes("items-center gap-2 mt-2"):
                            ui.icon("timer").classes("text-amber")
                            ui.label(f"TEMP DISABLED — {remaining} left").classes(
                                "text-amber font-bold"
                            )
                            if reason:
                                ui.label(f"({reason})").classes("text-xs text-grey-6")

                        async def do_reenable():
                            await run.io_bound(_save_vlog_config, {"enabled": True})
                            ui.notify("Re-enabled", type="positive")
                            await refresh()

                        ui.button(
                            "Re-enable Now",
                            icon="play_arrow",
                            color="green",
                            on_click=do_reenable,
                        ).props("dense size=sm")
                    else:
                        switch = ui.switch("Enabled", value=is_enabled)

                        async def on_toggle(e):
                            await run.io_bound(_save_vlog_config, {"enabled": e.value})
                            ui.notify(
                                "Enabled" if e.value else "Disabled",
                                type="positive",
                            )

                        switch.on_value_change(on_toggle)

                        with ui.row().classes("items-center gap-2 mt-2"):
                            dur_input = (
                                ui.input(
                                    placeholder="e.g. 30m, 2h, 1d",
                                )
                                .props("dense outlined")
                                .classes("w-36")
                            )
                            rsn_input = (
                                ui.input(
                                    placeholder="Reason (optional)",
                                )
                                .props("dense outlined")
                                .classes("w-48")
                            )

                            async def do_temp_disable(d=dur_input, r=rsn_input):
                                delta = _parse_duration(d.value or "30m")
                                if not delta:
                                    ui.notify(
                                        "Invalid duration (e.g. 30m, 2h, 1d)",
                                        type="negative",
                                    )
                                    return
                                until = (datetime.now(timezone.utc) + delta).strftime(
                                    "%Y-%m-%dT%H:%M:%SZ"
                                )
                                entry = {"value": False, "disabled_until": until}
                                reason = r.value.strip()
                                if reason:
                                    entry["reason"] = reason
                                await run.io_bound(
                                    _save_vlog_config, {"enabled": entry}
                                )
                                ui.notify(
                                    f"Temp disabled for {d.value or '30m'}",
                                    type="warning",
                                )
                                await refresh()

                            ui.button(
                                "Temp Disable",
                                icon="timer",
                                on_click=do_temp_disable,
                            ).props("dense size=sm")

                # --- Retention Settings ---
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Retention Settings").classes("text-lg font-bold")
                        field_help_icon("violation_logging.max_entries")

                    with ui.row().classes("items-center gap-4"):
                        ui.label("Max Entries:").classes("text-sm")
                        max_input = (
                            ui.number(
                                value=max_entries,
                                min=1,
                                step=1,
                            )
                            .props("dense outlined")
                            .classes("w-32")
                        )

                        async def save_max(e, inp=max_input):
                            try:
                                val = int(inp.value)
                                if val < 1:
                                    raise ValueError
                                await run.io_bound(
                                    _save_vlog_config, {"max_entries": val}
                                )
                                ui.notify(f"Max entries: {val}", type="positive")
                            except (ValueError, TypeError):
                                ui.notify(
                                    "Must be a positive integer",
                                    type="negative",
                                )

                        max_input.on("blur", save_max)

                    with ui.row().classes("items-center gap-4 mt-2"):
                        ui.label("Retention Days:").classes("text-sm")
                        ret_input = (
                            ui.number(
                                value=retention_days,
                                min=1,
                                step=1,
                            )
                            .props("dense outlined")
                            .classes("w-32")
                        )

                        async def save_ret(e, inp=ret_input):
                            try:
                                val = int(inp.value)
                                if val < 1:
                                    raise ValueError
                                await run.io_bound(
                                    _save_vlog_config,
                                    {"retention_days": val},
                                )
                                ui.notify(
                                    f"Retention: {val} days",
                                    type="positive",
                                )
                            except (ValueError, TypeError):
                                ui.notify(
                                    "Must be a positive integer",
                                    type="negative",
                                )

                        ret_input.on("blur", save_ret)

                # --- Log Types ---
                with ui.card().classes("w-full"):
                    ui.label("Violation Types to Log").classes("text-lg font-bold")
                    ui.label(
                        "Uncheck types to stop logging specific categories. "
                        "Empty selection logs all types."
                    ).classes("text-xs text-grey-6")

                    checkboxes = {}
                    for log_type, description in ALL_LOG_TYPES:
                        checked = log_type in log_types
                        cb = ui.checkbox(description, value=checked).classes("text-sm")
                        checkboxes[log_type] = cb

                        async def on_type_change(e, cbs=checkboxes):
                            enabled_types = [lt for lt, c in cbs.items() if c.value]
                            await run.io_bound(
                                _save_vlog_config,
                                {"log_types": enabled_types},
                            )
                            ui.notify(
                                f"Log types updated " f"({len(enabled_types)} enabled)",
                                type="positive",
                            )

                        cb.on_value_change(on_type_change)

                # --- Statistics ---
                with ui.card().classes("w-full"):
                    ui.label("Log Statistics").classes("text-lg font-bold")
                    stats = await run.io_bound(_load_local_stats)
                    ui.label(f"Total logged violations: {stats['total']}").classes(
                        "text-sm"
                    )
                    if stats["by_type"]:
                        rows = [
                            {"type": k, "count": v}
                            for k, v in sorted(
                                stats["by_type"].items(),
                                key=lambda x: x[1],
                                reverse=True,
                            )
                        ]
                        ui.table(
                            columns=[
                                {
                                    "name": "type",
                                    "label": "Type",
                                    "field": "type",
                                    "sortable": True,
                                },
                                {
                                    "name": "count",
                                    "label": "Count",
                                    "field": "count",
                                    "sortable": True,
                                },
                            ],
                            rows=rows,
                            row_key="type",
                        ).classes("w-full max-w-md")

        ui.timer(0.1, refresh, once=True)
