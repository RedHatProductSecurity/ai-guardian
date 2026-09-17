"""Global Settings page — all security features with toggles and actions."""

import re
from datetime import datetime, timedelta, timezone

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.help_panel import add_help_button, field_help_icon
from ai_guardian.web.config_helpers import (
    load_web_config,
    save_web_config,
    get_web_config_provenance,
    get_web_config_scope_label,
)

FEATURE_GROUPS = [
    (
        "Scanning",
        [
            (
                "secret_scanning",
                "Secret Scanning",
                "Scan for API keys, tokens, credentials",
            ),
            ("scan_pii", "PII Detection", "GDPR/CCPA compliance scanning"),
            (
                "image_scanning",
                "Image Scanning",
                "OCR-based scanning for secrets and PII in images",
            ),
            (
                "transcript_scanning",
                "Transcript Scanning",
                "Scan conversation for secrets/PII from ! commands",
            ),
        ],
    ),
    (
        "Threat Detection",
        [
            (
                "prompt_injection",
                "Prompt Injection",
                "Detect and block prompt injection attacks",
            ),
            (
                "ssrf_protection",
                "SSRF Protection",
                "Block requests to private networks and metadata",
            ),
            (
                "config_file_scanning",
                "Config File Scanner",
                "Detect credential exfiltration in config files",
            ),
            (
                "context_poisoning",
                "Context Poisoning",
                "Detect context poisoning attempts",
            ),
            (
                "supply_chain",
                "Supply Chain",
                "Detect malicious patterns in agent config files",
            ),
            (
                "code_scanning",
                "Code Security",
                "Python code security scanning (Bandit)",
            ),
            (
                "scan_offensive",
                "Offensive Language",
                "Detect profanity, slurs, and non-inclusive terminology",
            ),
            (
                "canary_detection",
                "Canary Detection",
                "Detect user-registered tripwire values to catch data exfiltration",
            ),
            (
                "exfil_detection",
                "Exfil Detection",
                "Detect bash commands that steal credentials via curl, base64, key files, and cloud metadata",
            ),
        ],
    ),
    (
        "Response Protection",
        [
            (
                "secret_redaction",
                "Secret Redaction",
                "Redact secrets from tool outputs",
            ),
            ("annotations", "Annotations", "Inline suppression for secrets and PII"),
        ],
    ),
    (
        "Access Control",
        [
            ("permissions", "Permissions", "Tool permission enforcement"),
            (
                "security_instructions",
                "Security Instructions",
                "Inject security rules into AI context",
            ),
        ],
    ),
    (
        "Monitoring",
        [
            (
                "violation_logging",
                "Violation Logging",
                "Log blocked operations for audit",
            ),
            (
                "latency_tracking",
                "Latency Tracking",
                "Record per-hook timing to latency.jsonl",
            ),
        ],
    ),
]

FEATURE_ACTIONS = {
    "prompt_injection": {
        "block": "Block",
        "ask": "Ask (block if headless)",
        "ask:warn": "Ask (warn if headless)",
        "ask:log-only": "Ask (log-only if headless)",
        "warn": "Warn",
        "log-only": "Log Only",
    },
    "ssrf_protection": {"block": "Block", "warn": "Warn", "log-only": "Log Only"},
    "config_file_scanning": {
        "block": "Block",
        "ask": "Ask (block if headless)",
        "ask:warn": "Ask (warn if headless)",
        "ask:log-only": "Ask (log-only if headless)",
        "warn": "Warn",
        "log-only": "Log Only",
    },
    "scan_pii": {
        "block": "Block",
        "ask": "Ask (block if headless)",
        "ask:warn": "Ask (warn if headless)",
        "ask:log-only": "Ask (log-only if headless)",
        "redact": "Redact",
        "warn": "Warn",
        "log-only": "Log Only",
    },
    "secret_redaction": {"warn": "Warn", "log-only": "Log Only"},
    "image_scanning": {"block": "Block", "warn": "Warn", "log-only": "Log Only"},
    "context_poisoning": {
        "block": "Block",
        "ask": "Ask (block if headless)",
        "ask:warn": "Ask (warn if headless)",
        "ask:log-only": "Ask (log-only if headless)",
        "warn": "Warn",
        "log-only": "Log Only",
    },
    "supply_chain": {
        "block": "Block",
        "ask": "Ask (block if headless)",
        "ask:warn": "Ask (warn if headless)",
        "ask:log-only": "Ask (log-only if headless)",
        "warn": "Warn",
        "log-only": "Log Only",
    },
    "code_scanning": {
        "block": "Block",
        "ask": "Ask (block if headless)",
        "ask:warn": "Ask (warn if headless)",
        "ask:log-only": "Ask (log-only if headless)",
        "warn": "Warn",
        "log-only": "Log Only",
    },
    "scan_offensive": {
        "block": "Block",
        "ask": "Ask (block if headless)",
        "ask:warn": "Ask (warn if headless)",
        "ask:log-only": "Ask (log-only if headless)",
        "warn": "Warn",
        "log": "Log",
        "log-only": "Log Only",
    },
    "canary_detection": {
        "block": "Block",
        "ask": "Ask (block if headless)",
        "ask:warn": "Ask (warn if headless)",
        "ask:log-only": "Ask (log-only if headless)",
        "warn": "Warn",
        "log-only": "Log Only",
    },
    "exfil_detection": {
        "block": "Block",
        "ask": "Ask (block if headless)",
        "ask:warn": "Ask (warn if headless)",
        "ask:log-only": "Ask (log-only if headless)",
        "warn": "Warn",
        "log-only": "Log Only",
    },
}

ACTION_DEFAULTS = {
    "prompt_injection": "block",
    "ssrf_protection": "block",
    "config_file_scanning": "block",
    "scan_pii": "block",
    "secret_redaction": "warn",
    "image_scanning": "block",
    "context_poisoning": "warn",
    "supply_chain": "block",
    "code_scanning": "warn",
    "scan_offensive": "log",
    "canary_detection": "block",
    "exfil_detection": "block",
}

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


def _get_enabled(config, section):
    if section == "permissions":
        return config.get("permissions", {}).get("enabled", True)
    if section == "security_instructions":
        si = config.get("security_instructions", {})
        if isinstance(si, dict):
            return si.get("inject_on_prompt", True)
        return True
    if section == "annotations":
        return config.get("annotations", {}).get("enabled", True)
    default_enabled = False if section == "latency_tracking" else True
    val = config.get(section, {})
    if isinstance(val, dict):
        enabled = val.get("enabled", default_enabled)
        if isinstance(enabled, dict):
            disabled_until = enabled.get("disabled_until")
            if disabled_until:
                try:
                    dt = datetime.fromisoformat(disabled_until.replace("Z", "+00:00"))
                    if datetime.now(timezone.utc) < dt:
                        return "temp_disabled", dt, enabled.get("reason", "")
                except (ValueError, TypeError):
                    pass  # intentionally silent — invalid value uses default
                return True, None, ""
            return enabled.get("value", default_enabled), None, ""
        return enabled, None, ""
    return default_enabled, None, ""


def _get_action(config, section):
    val = config.get(section, {})
    if isinstance(val, dict):
        return val.get("action", ACTION_DEFAULTS.get(section, "block"))
    return ACTION_DEFAULTS.get(section, "block")


def _format_remaining(dt):
    remaining = dt - datetime.now(timezone.utc)
    total = max(0, int(remaining.total_seconds()))
    if total == 0:
        return "expired"
    d = total // 86400
    h = (total % 86400) // 3600
    m = (total % 3600) // 60
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    return " ".join(parts) if parts else "<1m"


def _set_feature_enabled(section, value):
    config = load_web_config()
    if section == "permissions":
        if "permissions" not in config:
            config["permissions"] = {}
        config["permissions"]["enabled"] = value
    elif section == "security_instructions":
        if "security_instructions" not in config:
            config["security_instructions"] = {}
        config["security_instructions"]["inject_on_prompt"] = value
    else:
        sect = config.get(section, {})
        if not isinstance(sect, dict):
            sect = {}
        sect["enabled"] = value
        config[section] = sect
    save_web_config(config)


def _set_feature_action(section, action_value):
    config = load_web_config()
    sect = config.get(section, {})
    if not isinstance(sect, dict):
        sect = {}
    sect["action"] = action_value
    config[section] = sect
    save_web_config(config)


def create_global_settings_page(service, daemon_name: str):
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/settings")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.label("Global Settings").classes("text-2xl font-bold")
            add_help_button("global_settings")

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)

            provenance = await run.io_bound(get_web_config_provenance)
            scope_label = get_web_config_scope_label()

            with content:
                with ui.row().classes("items-center gap-2"):
                    from ai_guardian.web.config_helpers import (
                        _get_current_target,
                        _is_remote_target,
                    )

                    _target = _get_current_target()
                    if _is_remote_target(_target):
                        path_label = f"Config: (remote: {_target.name})"
                    else:
                        from ai_guardian.config.utils import get_config_dir

                        path_label = f"Config: {get_config_dir() / 'ai-guardian.json'}"
                    ui.label(path_label).classes("text-xs text-grey-6")
                    ui.badge(
                        scope_label,
                        color="green" if scope_label == "Global" else "blue",
                    ).classes("text-xs")

                # --- On Scan Error ---
                with ui.card().classes("w-full"):
                    on_scan_error = config.get("on_scan_error", "allow")
                    with ui.row().classes("items-center gap-4"):
                        ui.label("On Scan Error:").classes("text-sm font-bold")
                        field_help_icon("on_scan_error")
                        sel = ui.select(
                            options={
                                "allow": "Allow (fail-open)",
                                "block": "Block (fail-closed)",
                            },
                            value=on_scan_error,
                        ).classes("w-48")

                        async def save_err(e):
                            cfg = await run.io_bound(load_web_config)
                            cfg["on_scan_error"] = e.value
                            saved = await run.io_bound(save_web_config, cfg)
                            if not saved:
                                ui.notify(
                                    "Save failed: configuration is read-only or unavailable",
                                    type="negative",
                                )
                                return
                            ui.notify("Saved", type="positive")

                        sel.on_value_change(save_err)

                    ui.markdown(
                        "Controls what happens when a scanner itself crashes.\n\n"
                        "- **allow** (default) — fail-open: log a warning, let the operation through. "
                        "Best for development and low-friction workflows.\n"
                        "- **block** — fail-closed: block the operation if *any* scanner fails. "
                        "Safer but a scanner bug = blocked workflow.\n\n"
                        "**Applies to all scanners:** secret, PII, prompt injection, "
                        "Bandit, canary, exfil, etc. "
                        "Recommended: `allow` for dev, `block` for production/compliance environments."
                    ).classes("text-xs text-gray-600 mt-2")

                # --- Feature Groups ---
                for group_name, features in FEATURE_GROUPS:
                    with ui.card().classes("w-full"):
                        ui.label(group_name).classes("text-lg font-bold")

                        for section, label, desc in features:
                            ui.separator().classes("my-1")
                            ui.html(f'<div id="feature-{section}"></div>')
                            raw = _get_enabled(config, section)
                            if isinstance(raw, tuple) and len(raw) == 3:
                                is_temp = raw[0] == "temp_disabled"
                                until = raw[1]
                                reason = raw[2]
                                is_enabled = bool(raw[0]) if not is_temp else False
                            else:
                                is_temp = False
                                until = None
                                reason = ""
                                is_enabled = (
                                    bool(raw[0])
                                    if isinstance(raw, tuple)
                                    else bool(raw)
                                )

                            if is_temp and until:
                                with ui.row().classes("items-center gap-2 w-full"):
                                    ui.icon("timer").classes("text-amber")
                                    ui.label(label).classes(
                                        "font-bold text-sm flex-grow"
                                    )
                                    remaining = _format_remaining(until)
                                    ui.badge(
                                        f"TEMP DISABLED — {remaining}",
                                        color="amber",
                                    ).classes("text-xs")
                                ui.label(desc).classes("text-xs text-grey-6 ml-8")
                                if reason:
                                    ui.label(f"Reason: {reason}").classes(
                                        "text-xs text-grey-7 ml-8"
                                    )

                                async def do_reenable(sec=section):
                                    await run.io_bound(_set_feature_enabled, sec, True)
                                    ui.notify(f"{sec}: re-enabled", type="positive")
                                    await refresh()

                                ui.button(
                                    "Re-enable Now",
                                    icon="play_arrow",
                                    color="green",
                                    on_click=do_reenable,
                                ).props("dense size=sm").classes("ml-8")
                            else:
                                with ui.row().classes("items-center gap-2 w-full"):
                                    sw = ui.switch(label, value=is_enabled).classes(
                                        "flex-grow"
                                    )
                                    sect_prov = provenance.get(section, {})
                                    prov_src = (
                                        sect_prov
                                        if isinstance(sect_prov, str)
                                        else (
                                            sect_prov.get("enabled", "global")
                                            if isinstance(sect_prov, dict)
                                            else "global"
                                        )
                                    )
                                    if prov_src == "project":
                                        ui.badge("P", color="blue").props(
                                            "dense"
                                        ).classes("text-xs")
                                    ui.label(desc).classes("text-xs text-grey-6")
                                    field_help_icon(section)

                                    async def on_toggle(e, sec=section):
                                        await run.io_bound(
                                            _set_feature_enabled, sec, e.value
                                        )
                                        ui.notify(
                                            f"{sec}: {'enabled' if e.value else 'disabled'}",
                                            type="positive",
                                        )

                                    sw.on_value_change(on_toggle)

                                with ui.row().classes("items-center gap-2 ml-8"):
                                    dur = (
                                        ui.input(placeholder="e.g. 30m, 2h, 1d")
                                        .props("dense outlined")
                                        .classes("w-32")
                                    )
                                    rsn = (
                                        ui.input(placeholder="Reason")
                                        .props("dense outlined")
                                        .classes("w-40")
                                    )

                                    async def do_temp(sec=section, d=dur, r=rsn):
                                        delta = _parse_duration(d.value or "30m")
                                        if not delta:
                                            ui.notify(
                                                "Invalid duration (e.g. 30m, 2h, 1d)",
                                                type="negative",
                                            )
                                            return
                                        until_ts = (
                                            datetime.now(timezone.utc) + delta
                                        ).strftime("%Y-%m-%dT%H:%M:%SZ")
                                        entry = {
                                            "value": False,
                                            "disabled_until": until_ts,
                                        }
                                        rv = r.value.strip()
                                        if rv:
                                            entry["reason"] = rv
                                        await run.io_bound(
                                            _set_feature_enabled, sec, entry
                                        )
                                        ui.notify(
                                            f"{sec}: temp disabled for {d.value or '30m'}",
                                            type="warning",
                                        )
                                        await refresh()

                                    ui.button(
                                        "Temp Disable",
                                        icon="timer",
                                        on_click=do_temp,
                                    ).props("dense size=sm")

                            # Action dropdown
                            if section in FEATURE_ACTIONS:
                                current_action = _get_action(config, section)
                                with ui.row().classes("items-center gap-2 ml-8 mt-1"):
                                    ui.label("Action:").classes("text-sm text-grey-6")
                                    field_help_icon(f"{section}.action")
                                    act_sel = ui.select(
                                        options=FEATURE_ACTIONS[section],
                                        value=current_action,
                                    ).classes("w-36")

                                    async def on_action(e, sec=section):
                                        await run.io_bound(
                                            _set_feature_action, sec, e.value
                                        )
                                        ui.notify(
                                            f"{sec} action: {e.value}",
                                            type="positive",
                                        )

                                    act_sel.on_value_change(on_action)

                                    act_prov = provenance.get(section, {})
                                    act_prov_src = (
                                        act_prov.get("action", "global")
                                        if isinstance(act_prov, dict)
                                        else "global"
                                    )
                                    if act_prov_src == "project":
                                        ui.badge("P", color="blue").props(
                                            "dense"
                                        ).classes("text-xs")

                                        async def do_reset(sec=section):
                                            from ai_guardian.config.writer import (
                                                delete_project_override,
                                            )

                                            await run.io_bound(
                                                delete_project_override,
                                                sec,
                                                "action",
                                            )
                                            ui.notify(
                                                f"Reset {sec}.action to global default",
                                                type="info",
                                            )
                                            await refresh()

                                        ui.button(
                                            "Reset",
                                            icon="undo",
                                            color="grey",
                                            on_click=do_reset,
                                        ).props("dense flat size=sm")

        async def _refresh_and_scroll():
            await refresh()
            await ui.run_javascript(
                "if (location.hash) {"
                "  const el = document.querySelector(location.hash);"
                '  if (el) el.scrollIntoView({behavior: "smooth", block: "center"});'
                "}"
            )

        ui.timer(0.1, _refresh_and_scroll, once=True)
