"""Annotations page — inline and block annotation suppression settings."""

import re as re_mod
from datetime import datetime, timedelta, timezone

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.config_helpers import load_web_config, save_web_config

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


def _render_alias_list(title, desc, config_section, config_key, refresh_fn):
    with ui.card().classes("w-full"):
        ui.label(title).classes("text-lg font-bold")
        ui.label(desc).classes("text-xs text-grey-6")

        cfg = load_web_config()
        sect = cfg.get("annotations", {})
        if not isinstance(sect, dict):
            sect = {}
        aliases = sect.get(config_key, [])

        if aliases:
            for idx, alias in enumerate(aliases):
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.icon("label").classes("text-blue-4")
                    ui.label(alias).classes("flex-grow text-sm").style(
                        "font-family: monospace"
                    )

                    async def remove_alias(i=idx):
                        cfg2 = await run.io_bound(load_web_config)
                        sect2 = cfg2.get("annotations", {})
                        if not isinstance(sect2, dict):
                            return
                        items = sect2.get(config_key, [])
                        if i < len(items):
                            items.pop(i)
                            sect2[config_key] = items
                            cfg2["annotations"] = sect2
                            await run.io_bound(save_web_config, cfg2)
                            ui.notify("Alias removed", type="positive")
                            await refresh_fn()

                    ui.button(icon="delete", on_click=remove_alias, color="red").props(
                        "flat dense size=sm"
                    )
        else:
            ui.label("No aliases configured.").classes("text-grey-6 text-sm")

        with ui.row().classes("items-center gap-2 mt-2"):
            alias_input = (
                ui.input(placeholder="Enter alias")
                .props("dense outlined")
                .classes("flex-grow")
            )

            async def add_alias(inp=alias_input):
                val = inp.value.strip()
                if not val:
                    ui.notify("Enter an alias", type="negative")
                    return
                cfg2 = await run.io_bound(load_web_config)
                sect2 = cfg2.get("annotations", {})
                if not isinstance(sect2, dict):
                    sect2 = {}
                items = sect2.get(config_key, [])
                if val in items:
                    ui.notify("Alias already exists", type="warning")
                    return
                items.append(val)
                sect2[config_key] = items
                cfg2["annotations"] = sect2
                await run.io_bound(save_web_config, cfg2)
                inp.value = ""
                ui.notify(f"Added: {val}", type="positive")
                await refresh_fn()

            ui.button("Add", icon="add", on_click=add_alias).props("dense")


def create_annotations_page(service, daemon_name: str):
    """Create the Annotations page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/annotations")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Annotation Settings").classes("text-2xl font-bold")
        ui.label(
            "Configure inline and block annotation markers for suppressing detections."
        ).classes("text-xs text-grey-6")

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)

            with content:
                an = config.get("annotations", {})
                if not isinstance(an, dict):
                    an = {}

                is_temp, until_dt, reason, is_enabled = _parse_enabled(
                    an.get("enabled", True)
                )

                def save_enabled(value):
                    cfg = load_web_config()
                    sect = cfg.get("annotations", {})
                    if not isinstance(sect, dict):
                        sect = {}
                    sect["enabled"] = value
                    cfg["annotations"] = sect
                    save_web_config(cfg)

                _render_toggle(
                    "Annotations",
                    "Allow inline and block annotations to suppress secret and PII detections.",
                    is_temp,
                    until_dt,
                    reason,
                    is_enabled,
                    save_enabled,
                    refresh,
                )

                with ui.card().classes("w-full"):
                    ui.label("Built-in Markers (Always Active)").classes(
                        "text-lg font-bold"
                    )
                    ui.label(
                        "These markers are hardcoded and cannot be removed."
                    ).classes("text-xs text-grey-6")
                    with ui.column().classes("gap-1 ml-4 mt-2"):
                        with ui.row().classes("items-center gap-1"):
                            ui.image("/images/tray-icon-16.png").classes("w-4 h-4")
                            ui.label("Inline: # ai-guardian:allow").classes(
                                "text-xs"
                            ).style("font-family: monospace")
                        with ui.row().classes("items-center gap-1"):
                            ui.image("/images/tray-icon-16.png").classes("w-4 h-4")
                            ui.label(
                                "Block: # ai-guardian:begin-allow ... # ai-guardian:end-allow"
                            ).classes("text-xs").style("font-family: monospace")
                    ui.label(
                        "Note: Prompt injection, jailbreak, and config exfiltration "
                        "detections cannot be suppressed via annotations."
                    ).classes("text-xs text-amber-8 mt-2 ml-4")

                _render_alias_list(
                    "Inline Allow Aliases (secrets + PII)",
                    "Additional comment markers that act as inline allow annotations.",
                    "annotations",
                    "inline_allow",
                    refresh,
                )

                _render_alias_list(
                    "Inline Allow Secrets Aliases",
                    "Comment markers for suppressing only secret detections (default includes gitleaks:allow).",
                    "annotations",
                    "inline_allow_secrets",
                    refresh,
                )

                _render_alias_list(
                    "Block Begin Aliases",
                    "Additional markers for beginning a block-level allow region.",
                    "annotations",
                    "block_begin",
                    refresh,
                )

                _render_alias_list(
                    "Block End Aliases",
                    "Additional markers for ending a block-level allow region.",
                    "annotations",
                    "block_end",
                    refresh,
                )

        ui.timer(0.1, refresh, once=True)
