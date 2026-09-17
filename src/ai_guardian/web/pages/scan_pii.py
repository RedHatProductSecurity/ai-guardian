"""PII Scanning page — personally identifiable information detection settings."""

import re as re_mod
from datetime import datetime, timedelta, timezone

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.help_panel import add_help_button, field_help_icon
from ai_guardian.web.config_helpers import load_web_config, save_web_config

PHASE1_PII_TYPES = [
    ("ssn", "Social Security Number"),
    ("credit_card", "Credit Card Number"),
    ("phone", "Phone Number (US)"),
    ("email", "Email Address"),
    ("us_passport", "US Passport Number"),
    ("iban", "International Bank Account Number"),
    ("intl_phone", "International Phone Number"),
]

PHASE2_PII_TYPES = [
    ("medical_id", "Medical ID / Health Record"),
    ("passport", "International Passport"),
    ("canada_sin", "Canada Social Insurance Number"),
    ("uk_nin", "UK National Insurance Number"),
    ("india_aadhaar", "India Aadhaar Number"),
    ("address", "Physical Address"),
]

ALL_PII_TYPES = PHASE1_PII_TYPES + PHASE2_PII_TYPES

DURATION_RE = re_mod.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?$", re_mod.IGNORECASE)


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


def _parse_enabled(raw):
    if isinstance(raw, dict):
        disabled_until = raw.get("disabled_until")
        if disabled_until:
            try:
                until_dt = datetime.fromisoformat(disabled_until.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < until_dt:
                    return True, until_dt, raw.get("reason", ""), False
            except (ValueError, TypeError):
                pass  # intentionally silent — invalid value uses default
        return False, None, "", bool(raw.get("value", True))
    return False, None, "", bool(raw)


def _load_stats():
    from ai_guardian.web.config_helpers import load_web_violations

    result = load_web_violations(violation_type="pii_detected")
    if result and result.get("violations"):
        return len(result["violations"])
    return 0


def _format_expiration(valid_until):
    if not valid_until:
        return None
    try:
        dt = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if datetime.now(timezone.utc) >= dt:
        return "EXPIRED", "red"
    remaining = _format_remaining(dt)
    return f"expires {remaining}", "amber"


def _get_pattern_text(entry):
    if isinstance(entry, dict):
        return entry.get("pattern", str(entry))
    return str(entry)


def _render_toggle(
    label, desc, is_temp, until_dt, reason, is_enabled, save_fn, refresh_fn
):
    with ui.card().classes("w-full"):
        if is_temp and until_dt:
            remaining = _format_remaining(until_dt)
            with ui.row().classes("items-center gap-2 w-full"):
                ui.icon("timer").classes("text-amber")
                ui.label(label).classes("font-bold text-sm flex-grow")
                ui.badge(f"TEMP DISABLED — {remaining}", color="amber").classes(
                    "text-xs"
                )
            ui.label(desc).classes("text-xs text-grey-6 ml-8")
            if reason:
                ui.label(f"Reason: {reason}").classes("text-xs text-grey-7 ml-8")

            async def do_reenable():
                await run.io_bound(save_fn, True)
                ui.notify(f"{label} re-enabled", type="positive")
                await refresh_fn()

            ui.button(
                "Re-enable Now", icon="play_arrow", color="green", on_click=do_reenable
            ).props("dense size=sm").classes("ml-8")
        else:
            with ui.row().classes("items-center gap-2 w-full"):
                sw = ui.switch(label, value=bool(is_enabled)).classes("flex-grow")
                ui.label(desc).classes("text-xs text-grey-6")

                async def on_toggle(e):
                    await run.io_bound(save_fn, e.value)
                    ui.notify(
                        f"{label} {'enabled' if e.value else 'disabled'}",
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

                async def do_temp(d=dur, r=rsn):
                    delta = _parse_duration(d.value or "30m")
                    if not delta:
                        ui.notify(
                            "Invalid duration (e.g. 30m, 2h, 1d)", type="negative"
                        )
                        return
                    until_ts = (datetime.now(timezone.utc) + delta).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                    entry = {"value": False, "disabled_until": until_ts}
                    rv = r.value.strip()
                    if rv:
                        entry["reason"] = rv
                    await run.io_bound(save_fn, entry)
                    ui.notify(
                        f"{label} temp disabled for {d.value or '30m'}", type="warning"
                    )
                    await refresh_fn()

                ui.button("Temp Disable", icon="timer", on_click=do_temp).props(
                    "dense size=sm"
                )


def create_scan_pii_page(service, daemon_name: str):
    """Create the PII Scanning page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/scan-pii")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.label("PII Scanning Settings").classes("text-2xl font-bold")
            add_help_button("scan_pii")
        ui.label(
            "Configure detection and handling of personally identifiable information."
        ).classes("text-xs text-grey-6")

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)

            with content:
                sp = config.get("scan_pii", {})
                if not isinstance(sp, dict):
                    sp = {}

                is_temp, until_dt, reason, is_enabled = _parse_enabled(
                    sp.get("enabled", True)
                )

                def save_enabled(value):
                    cfg = load_web_config()
                    sect = cfg.get("scan_pii", {})
                    if not isinstance(sect, dict):
                        sect = {}
                    sect["enabled"] = value
                    cfg["scan_pii"] = sect
                    save_web_config(cfg)

                _render_toggle(
                    "PII Scanning",
                    "Detect personally identifiable information in tool inputs and outputs.",
                    is_temp,
                    until_dt,
                    reason,
                    is_enabled,
                    save_enabled,
                    refresh,
                )

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Action Mode").classes("text-lg font-bold")
                        field_help_icon("scan_pii")
                    ui.label("What happens when PII is detected.").classes(
                        "text-xs text-grey-6"
                    )
                    action = sp.get("action", "redact")
                    act_sel = ui.select(
                        options={
                            "block": "Block — reject operation",
                            "ask": "Ask — interactive prompt (block if headless)",
                            "ask:warn": "Ask — interactive prompt (warn if headless)",
                            "ask:log-only": "Ask — interactive prompt (log-only if headless)",
                            "redact": "Redact — mask PII values",
                            "warn": "Warn — allow with warning",
                            "log-only": "Log Only — silent logging",
                        },
                        value=action,
                    ).classes("w-64")

                    async def save_action(e):
                        cfg = await run.io_bound(load_web_config)
                        sect = cfg.get("scan_pii", {})
                        if not isinstance(sect, dict):
                            sect = {}
                        sect["action"] = e.value
                        cfg["scan_pii"] = sect
                        await run.io_bound(save_web_config, cfg)
                        ui.notify(f"Action: {e.value}", type="positive")

                    act_sel.on_value_change(save_action)

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("PII Types").classes("text-lg font-bold")
                        field_help_icon("scan_pii.pii_types")
                    ui.label("Select which PII types to detect.").classes(
                        "text-xs text-grey-6"
                    )

                    enabled_types = sp.get("pii_types", [k for k, _ in ALL_PII_TYPES])
                    if not isinstance(enabled_types, list):
                        enabled_types = [k for k, _ in ALL_PII_TYPES]

                    ui.label("Phase 1 — Core PII Types").classes(
                        "font-bold text-sm mt-2"
                    )
                    for key, label in PHASE1_PII_TYPES:
                        cb = ui.checkbox(label, value=key in enabled_types)

                        async def on_pii_change(e, k=key):
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("scan_pii", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            current = sect.get(
                                "pii_types", [t for t, _ in ALL_PII_TYPES]
                            )
                            if not isinstance(current, list):
                                current = [t for t, _ in ALL_PII_TYPES]
                            if e.value and k not in current:
                                current.append(k)
                            elif not e.value and k in current:
                                current.remove(k)
                            sect["pii_types"] = current
                            cfg["scan_pii"] = sect
                            saved = await run.io_bound(save_web_config, cfg)
                            if not saved:
                                ui.notify(
                                    "Save failed: configuration is read-only or unavailable",
                                    type="negative",
                                )
                                return
                            ui.notify("Saved", type="positive")

                        cb.on_value_change(on_pii_change)

                    ui.label("Phase 2 — Extended PII Types").classes(
                        "font-bold text-sm mt-2"
                    )
                    for key, label in PHASE2_PII_TYPES:
                        cb = ui.checkbox(label, value=key in enabled_types)

                        async def on_pii_change2(e, k=key):
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("scan_pii", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            current = sect.get(
                                "pii_types", [t for t, _ in ALL_PII_TYPES]
                            )
                            if not isinstance(current, list):
                                current = [t for t, _ in ALL_PII_TYPES]
                            if e.value and k not in current:
                                current.append(k)
                            elif not e.value and k in current:
                                current.remove(k)
                            sect["pii_types"] = current
                            cfg["scan_pii"] = sect
                            saved = await run.io_bound(save_web_config, cfg)
                            if not saved:
                                ui.notify(
                                    "Save failed: configuration is read-only or unavailable",
                                    type="negative",
                                )
                                return
                            ui.notify("Saved", type="positive")

                        cb.on_value_change(on_pii_change2)

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Ignore Files").classes("text-lg font-bold")
                        field_help_icon("scan_pii.ignore_files")
                    ui.label(
                        "Glob patterns for files to exclude from PII scanning."
                    ).classes("text-xs text-grey-6")

                    ignore_files = sp.get("ignore_files", [])
                    if ignore_files:
                        for idx, entry in enumerate(ignore_files):
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon("visibility_off").classes("text-grey-6")
                                ui.label(entry).classes("flex-grow text-sm").style(
                                    "font-family: monospace"
                                )

                                async def remove_ignore_file(i=idx):
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("scan_pii", {})
                                    if not isinstance(sect, dict):
                                        return
                                    items = sect.get("ignore_files", [])
                                    if i < len(items):
                                        items.pop(i)
                                        sect["ignore_files"] = items
                                        cfg["scan_pii"] = sect
                                        await run.io_bound(save_web_config, cfg)
                                        ui.notify(
                                            "File pattern removed", type="positive"
                                        )
                                        await refresh()

                                ui.button(
                                    icon="delete",
                                    on_click=remove_ignore_file,
                                    color="red",
                                ).props("flat dense size=sm")
                    else:
                        ui.label("No ignore file patterns.").classes(
                            "text-grey-6 text-sm"
                        )

                    with ui.row().classes("items-center gap-2 mt-2"):
                        if_input = (
                            ui.input(placeholder="Enter glob pattern (e.g. *.log)")
                            .props("dense outlined")
                            .classes("flex-grow")
                        )

                        async def add_ignore_file():
                            val = if_input.value.strip()
                            if not val:
                                ui.notify("Enter a pattern", type="negative")
                                return
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("scan_pii", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            items = sect.get("ignore_files", [])
                            if val in items:
                                ui.notify("Pattern already exists", type="warning")
                                return
                            items.append(val)
                            sect["ignore_files"] = items
                            cfg["scan_pii"] = sect
                            await run.io_bound(save_web_config, cfg)
                            if_input.value = ""
                            ui.notify(f"Added: {val}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_ignore_file).props(
                            "dense"
                        )

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Ignore Tools").classes("text-lg font-bold")
                        field_help_icon("scan_pii.ignore_tools")
                    ui.label(
                        "Tool name patterns to exclude from PII scanning."
                    ).classes("text-xs text-grey-6")

                    ignore_tools = sp.get("ignore_tools", [])
                    if ignore_tools:
                        for idx, entry in enumerate(ignore_tools):
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon("build").classes("text-grey-6")
                                ui.label(entry).classes("flex-grow text-sm").style(
                                    "font-family: monospace"
                                )

                                async def remove_ignore_tool(i=idx):
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("scan_pii", {})
                                    if not isinstance(sect, dict):
                                        return
                                    items = sect.get("ignore_tools", [])
                                    if i < len(items):
                                        items.pop(i)
                                        sect["ignore_tools"] = items
                                        cfg["scan_pii"] = sect
                                        await run.io_bound(save_web_config, cfg)
                                        ui.notify(
                                            "Tool pattern removed", type="positive"
                                        )
                                        await refresh()

                                ui.button(
                                    icon="delete",
                                    on_click=remove_ignore_tool,
                                    color="red",
                                ).props("flat dense size=sm")
                    else:
                        ui.label("No ignore tool patterns.").classes(
                            "text-grey-6 text-sm"
                        )

                    with ui.row().classes("items-center gap-2 mt-2"):
                        it_input = (
                            ui.input(
                                placeholder="Enter tool name pattern (e.g. mcp__*)"
                            )
                            .props("dense outlined")
                            .classes("flex-grow")
                        )

                        async def add_ignore_tool():
                            val = it_input.value.strip()
                            if not val:
                                ui.notify("Enter a pattern", type="negative")
                                return
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("scan_pii", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            items = sect.get("ignore_tools", [])
                            if val in items:
                                ui.notify("Pattern already exists", type="warning")
                                return
                            items.append(val)
                            sect["ignore_tools"] = items
                            cfg["scan_pii"] = sect
                            await run.io_bound(save_web_config, cfg)
                            it_input.value = ""
                            ui.notify(f"Added: {val}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_ignore_tool).props(
                            "dense"
                        )

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Allowlist Patterns").classes("text-lg font-bold")
                        field_help_icon("scan_pii.allowlist_patterns")
                    ui.label(
                        "Regex patterns for known-safe PII values. "
                        "Supports optional expiration via valid_until."
                    ).classes("text-xs text-grey-6")

                    allowlist = sp.get("allowlist_patterns", [])
                    if allowlist:
                        for idx, entry in enumerate(allowlist):
                            pat_text = _get_pattern_text(entry)
                            valid_until = (
                                entry.get("valid_until")
                                if isinstance(entry, dict)
                                else None
                            )
                            exp_info = _format_expiration(valid_until)

                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon("check").classes("text-green")
                                ui.label(pat_text).classes("flex-grow text-sm").style(
                                    "font-family: monospace"
                                )
                                if exp_info:
                                    exp_text, exp_color = exp_info
                                    ui.badge(exp_text, color=exp_color).classes(
                                        "text-xs"
                                    )

                                async def remove_allowlist(i=idx):
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("scan_pii", {})
                                    if not isinstance(sect, dict):
                                        return
                                    pats = sect.get("allowlist_patterns", [])
                                    if i < len(pats):
                                        pats.pop(i)
                                        sect["allowlist_patterns"] = pats
                                        cfg["scan_pii"] = sect
                                        await run.io_bound(save_web_config, cfg)
                                        ui.notify("Pattern removed", type="positive")
                                        await refresh()

                                ui.button(
                                    icon="delete",
                                    on_click=remove_allowlist,
                                    color="red",
                                ).props("flat dense size=sm")
                    else:
                        ui.label("No allowlist patterns.").classes(
                            "text-grey-6 text-sm"
                        )

                    with ui.row().classes("items-center gap-2 mt-2"):
                        al_input = (
                            ui.input(placeholder="Enter regex pattern")
                            .props("dense outlined")
                            .classes("flex-grow")
                        )
                        al_exp = (
                            ui.input(
                                placeholder="valid_until (e.g. 2025-12-31T23:59:59Z)"
                            )
                            .props("dense outlined")
                            .classes("w-64")
                        )

                        async def add_allowlist_pat():
                            pattern = al_input.value.strip()
                            if not pattern:
                                ui.notify("Enter a pattern", type="negative")
                                return
                            try:
                                re_mod.compile(pattern)
                            except re_mod.error as e:
                                ui.notify(f"Invalid regex: {e}", type="negative")
                                return
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("scan_pii", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            pats = sect.get("allowlist_patterns", [])
                            existing = [_get_pattern_text(p) for p in pats]
                            if pattern in existing:
                                ui.notify("Pattern already exists", type="warning")
                                return
                            exp_val = al_exp.value.strip()
                            if exp_val:
                                try:
                                    datetime.fromisoformat(
                                        exp_val.replace("Z", "+00:00")
                                    )
                                except (ValueError, TypeError):
                                    ui.notify("Invalid date format", type="negative")
                                    return
                                pats.append(
                                    {"pattern": pattern, "valid_until": exp_val}
                                )
                            else:
                                pats.append(pattern)
                            sect["allowlist_patterns"] = pats
                            cfg["scan_pii"] = sect
                            await run.io_bound(save_web_config, cfg)
                            al_input.value = ""
                            al_exp.value = ""
                            ui.notify(f"Added: {pattern}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_allowlist_pat).props(
                            "dense"
                        )

                with ui.card().classes("w-full"):
                    ui.label("PII Scanning Statistics").classes("text-lg font-bold")
                    total = await run.io_bound(_load_stats)
                    if total is None:
                        ui.label("Violation logging not available.").classes(
                            "text-grey-6 text-sm"
                        )
                    elif total == 0:
                        ui.label("No PII detected yet.").classes("text-grey-6 text-sm")
                    else:
                        ui.label(f"Total PII detections: {total}").classes("text-sm")

        ui.timer(0.1, refresh, once=True)
