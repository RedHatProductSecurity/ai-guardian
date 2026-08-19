"""Config Scanner page — configuration file exfiltration detection."""

import re as re_mod
from datetime import datetime, timedelta, timezone

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.step_render import render_guardian_icon
from ai_guardian.web.components.help_panel import add_help_button, field_help_icon
from ai_guardian.web.config_helpers import load_web_config, save_web_config

DEFAULT_SCANNED_FILES = {
    "AI Agent Config": [
        "CLAUDE.md",
        "AGENTS.md",
        ".claude/CLAUDE.md",
        ".agents/AGENTS.md",
        ".cursorrules",
        ".windsurfrules",
        ".aider.conf.yml",
    ],
    "Skill Files": [
        "**/.claude/skills/**/*.md",
        "**/.agents/skills/**/*.md",
        "**/skills/**/*.md",
    ],
}

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

    result = load_web_violations(violation_type="config_file_exfil")
    if result and result.get("violations"):
        return len(result["violations"])
    return 0


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


def create_config_scanner_page(service, daemon_name: str):
    """Create the Config Scanner page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/config-scanner")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.label("Config File Scanning Settings").classes("text-2xl font-bold")
            add_help_button("config_file_scanning")
        ui.label(
            "Configure detection of configuration file exfiltration attempts."
        ).classes("text-xs text-grey-6")

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)

            with content:
                cs = config.get("config_file_scanning", {})
                if not isinstance(cs, dict):
                    cs = {}

                is_temp, until_dt, reason, is_enabled = _parse_enabled(
                    cs.get("enabled", True)
                )

                def save_enabled(value):
                    cfg = load_web_config()
                    sect = cfg.get("config_file_scanning", {})
                    if not isinstance(sect, dict):
                        sect = {}
                    sect["enabled"] = value
                    cfg["config_file_scanning"] = sect
                    save_web_config(cfg)

                _render_toggle(
                    "Config File Scanning",
                    "Detect attempts to exfiltrate AI agent configuration files.",
                    is_temp,
                    until_dt,
                    reason,
                    is_enabled,
                    save_enabled,
                    refresh,
                )

                total_files = sum(len(v) for v in DEFAULT_SCANNED_FILES.values())
                with ui.card().classes("w-full"):
                    ui.label(f"Default Scanned Files ({total_files} patterns)").classes(
                        "text-lg font-bold"
                    )
                    ui.label("These file patterns are always monitored.").classes(
                        "text-xs text-grey-6"
                    )
                    with ui.scroll_area().classes("w-full").style("max-height: 300px"):
                        for category, files in DEFAULT_SCANNED_FILES.items():
                            ui.label(category).classes("font-bold text-sm mt-2")
                            for f in files:
                                with ui.row().classes("items-center gap-1 ml-4"):
                                    render_guardian_icon()
                                    ui.label(f).classes("text-xs")

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Action Mode").classes("text-lg font-bold")
                        field_help_icon("config_file_scanning")
                    ui.label(
                        "What happens when a config file exfiltration attempt is detected."
                    ).classes("text-xs text-grey-6")
                    action = cs.get("action", "block")
                    act_sel = ui.select(
                        options={
                            "block": "Block — reject operation",
                            "warn": "Warn — allow with warning",
                            "log-only": "Log Only — silent logging",
                        },
                        value=action,
                    ).classes("w-64")

                    async def save_action(e):
                        cfg = await run.io_bound(load_web_config)
                        sect = cfg.get("config_file_scanning", {})
                        if not isinstance(sect, dict):
                            sect = {}
                        sect["action"] = e.value
                        cfg["config_file_scanning"] = sect
                        await run.io_bound(save_web_config, cfg)
                        ui.notify(f"Action: {e.value}", type="positive")

                    act_sel.on_value_change(save_action)

                with ui.card().classes("w-full"):
                    ui.label("Additional Files").classes("text-lg font-bold")
                    ui.label("Custom file paths or glob patterns to monitor.").classes(
                        "text-xs text-grey-6"
                    )

                    additional = cs.get("additional_files", [])
                    if additional:
                        for idx, entry in enumerate(additional):
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon("description").classes("text-blue-4")
                                ui.label(entry).classes("flex-grow text-sm").style(
                                    "font-family: monospace"
                                )

                                async def remove_file(i=idx):
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("config_file_scanning", {})
                                    if not isinstance(sect, dict):
                                        return
                                    items = sect.get("additional_files", [])
                                    if i < len(items):
                                        items.pop(i)
                                        sect["additional_files"] = items
                                        cfg["config_file_scanning"] = sect
                                        await run.io_bound(save_web_config, cfg)
                                        ui.notify("File removed", type="positive")
                                        await refresh()

                                ui.button(
                                    icon="delete", on_click=remove_file, color="red"
                                ).props("flat dense size=sm")
                    else:
                        ui.label("No additional files.").classes("text-grey-6 text-sm")

                    with ui.row().classes("items-center gap-2 mt-2"):
                        file_input = (
                            ui.input(placeholder="Enter file path or glob pattern")
                            .props("dense outlined")
                            .classes("flex-grow")
                        )

                        async def add_file():
                            val = file_input.value.strip()
                            if not val:
                                ui.notify(
                                    "Enter a file path or pattern", type="negative"
                                )
                                return
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("config_file_scanning", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            items = sect.get("additional_files", [])
                            if val in items:
                                ui.notify("File already exists", type="warning")
                                return
                            items.append(val)
                            sect["additional_files"] = items
                            cfg["config_file_scanning"] = sect
                            await run.io_bound(save_web_config, cfg)
                            file_input.value = ""
                            ui.notify(f"Added: {val}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_file).props("dense")

                with ui.card().classes("w-full"):
                    ui.label("Ignore Files").classes("text-lg font-bold")
                    ui.label(
                        "File paths or glob patterns to exclude from scanning."
                    ).classes("text-xs text-grey-6")

                    ignore = cs.get("ignore_files", [])
                    if ignore:
                        for idx, entry in enumerate(ignore):
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon("visibility_off").classes("text-grey-6")
                                ui.label(entry).classes("flex-grow text-sm").style(
                                    "font-family: monospace"
                                )

                                async def remove_ignore(i=idx):
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("config_file_scanning", {})
                                    if not isinstance(sect, dict):
                                        return
                                    items = sect.get("ignore_files", [])
                                    if i < len(items):
                                        items.pop(i)
                                        sect["ignore_files"] = items
                                        cfg["config_file_scanning"] = sect
                                        await run.io_bound(save_web_config, cfg)
                                        ui.notify(
                                            "Ignore pattern removed",
                                            type="positive",
                                        )
                                        await refresh()

                                ui.button(
                                    icon="delete",
                                    on_click=remove_ignore,
                                    color="red",
                                ).props("flat dense size=sm")
                    else:
                        ui.label("No ignore patterns.").classes("text-grey-6 text-sm")

                    with ui.row().classes("items-center gap-2 mt-2"):
                        ign_input = (
                            ui.input(
                                placeholder="Enter file path or glob pattern to ignore"
                            )
                            .props("dense outlined")
                            .classes("flex-grow")
                        )

                        async def add_ignore():
                            val = ign_input.value.strip()
                            if not val:
                                ui.notify("Enter a pattern", type="negative")
                                return
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("config_file_scanning", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            items = sect.get("ignore_files", [])
                            if val in items:
                                ui.notify("Pattern already exists", type="warning")
                                return
                            items.append(val)
                            sect["ignore_files"] = items
                            cfg["config_file_scanning"] = sect
                            await run.io_bound(save_web_config, cfg)
                            ign_input.value = ""
                            ui.notify(f"Added: {val}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_ignore).props("dense")

                # --- Ignore tools ---
                with ui.card().classes("w-full"):
                    ui.label("Ignore Tools").classes("text-lg font-bold")
                    ui.label(
                        "Tool name patterns to exclude from config file scanning."
                    ).classes("text-xs text-grey-6")

                    ignore_tools = cs.get("ignore_tools", [])
                    if ignore_tools:
                        for idx, entry in enumerate(ignore_tools):
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon("build").classes("text-grey-6")
                                ui.label(entry).classes("flex-grow text-sm").style(
                                    "font-family: monospace"
                                )

                                async def remove_ignore_tool(i=idx):
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("config_file_scanning", {})
                                    if not isinstance(sect, dict):
                                        return
                                    items = sect.get("ignore_tools", [])
                                    if i < len(items):
                                        items.pop(i)
                                        sect["ignore_tools"] = items
                                        cfg["config_file_scanning"] = sect
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
                            sect = cfg.get("config_file_scanning", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            items = sect.get("ignore_tools", [])
                            if val in items:
                                ui.notify("Pattern already exists", type="warning")
                                return
                            items.append(val)
                            sect["ignore_tools"] = items
                            cfg["config_file_scanning"] = sect
                            await run.io_bound(save_web_config, cfg)
                            it_input.value = ""
                            ui.notify(f"Added: {val}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_ignore_tool).props(
                            "dense"
                        )

                with ui.card().classes("w-full"):
                    ui.label("Additional Detection Patterns").classes(
                        "text-lg font-bold"
                    )
                    ui.label(
                        "Custom regex patterns for detecting exfiltration attempts."
                    ).classes("text-xs text-grey-6")

                    patterns = cs.get("additional_patterns", [])
                    if patterns:
                        for idx, pat in enumerate(patterns):
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon("code").classes("text-blue-4")
                                ui.label(pat).classes("flex-grow text-sm").style(
                                    "font-family: monospace"
                                )

                                async def remove_pat(i=idx):
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("config_file_scanning", {})
                                    if not isinstance(sect, dict):
                                        return
                                    pats = sect.get("additional_patterns", [])
                                    if i < len(pats):
                                        pats.pop(i)
                                        sect["additional_patterns"] = pats
                                        cfg["config_file_scanning"] = sect
                                        await run.io_bound(save_web_config, cfg)
                                        ui.notify("Pattern removed", type="positive")
                                        await refresh()

                                ui.button(
                                    icon="delete", on_click=remove_pat, color="red"
                                ).props("flat dense size=sm")
                    else:
                        ui.label("No custom patterns.").classes("text-grey-6 text-sm")

                    with ui.row().classes("items-center gap-2 mt-2"):
                        pat_input = (
                            ui.input(placeholder="Enter custom regex pattern")
                            .props("dense outlined")
                            .classes("flex-grow")
                        )

                        async def add_pattern():
                            pattern = pat_input.value.strip()
                            if not pattern:
                                ui.notify("Enter a pattern", type="negative")
                                return
                            try:
                                re_mod.compile(pattern)
                            except re_mod.error as e:
                                ui.notify(f"Invalid regex: {e}", type="negative")
                                return
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("config_file_scanning", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            pats = sect.get("additional_patterns", [])
                            if pattern in pats:
                                ui.notify("Pattern already exists", type="warning")
                                return
                            pats.append(pattern)
                            sect["additional_patterns"] = pats
                            cfg["config_file_scanning"] = sect
                            await run.io_bound(save_web_config, cfg)
                            pat_input.value = ""
                            ui.notify(f"Added: {pattern}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_pattern).props(
                            "dense"
                        )

                with ui.card().classes("w-full"):
                    ui.label("Config Scanning Statistics").classes("text-lg font-bold")
                    total = await run.io_bound(_load_stats)
                    if total is None:
                        ui.label("Violation logging not available.").classes(
                            "text-grey-6 text-sm"
                        )
                    elif total == 0:
                        ui.label(
                            "No config exfiltration attempts detected yet."
                        ).classes("text-grey-6 text-sm")
                    else:
                        ui.label(
                            f"Total config exfiltration attempts: {total}"
                        ).classes("text-sm")

        ui.timer(0.1, refresh, once=True)
