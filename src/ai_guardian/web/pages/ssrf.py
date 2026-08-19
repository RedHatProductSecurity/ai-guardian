"""SSRF Protection page — network request filtering and IP blocking."""

import re as re_mod
from datetime import datetime, timedelta, timezone

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.help_panel import add_help_button, field_help_icon
from ai_guardian.web.config_helpers import load_web_config, save_web_config

CORE_PROTECTIONS = {
    "Private IP Ranges": [
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    ],
    "Cloud Metadata Endpoints": [
        "169.254.169.254",
        "metadata.google.internal",
        "fd00:ec2::254",
    ],
    "Dangerous URL Schemes": [
        "file://",
        "gopher://",
        "ftp://",
        "data://",
        "dict://",
        "ldap://",
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

    result = load_web_violations(violation_type="ssrf_blocked")
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


def create_ssrf_page(service, daemon_name: str):
    """Create the SSRF Protection page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/ssrf")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.label("SSRF Protection Settings").classes("text-2xl font-bold")
            add_help_button("ssrf_protection")
        ui.label(
            "Configure server-side request forgery protection and network filtering."
        ).classes("text-xs text-grey-6")

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)

            with content:
                sp = config.get("ssrf_protection", {})
                if not isinstance(sp, dict):
                    sp = {}

                is_temp, until_dt, reason, is_enabled = _parse_enabled(
                    sp.get("enabled", True)
                )

                def save_enabled(value):
                    cfg = load_web_config()
                    sect = cfg.get("ssrf_protection", {})
                    if not isinstance(sect, dict):
                        sect = {}
                    sect["enabled"] = value
                    cfg["ssrf_protection"] = sect
                    save_web_config(cfg)

                _render_toggle(
                    "SSRF Protection",
                    "Block requests to private networks, cloud metadata, and dangerous schemes.",
                    is_temp,
                    until_dt,
                    reason,
                    is_enabled,
                    save_enabled,
                    refresh,
                )

                total_items = sum(len(v) for v in CORE_PROTECTIONS.values())
                with ui.card().classes("w-full"):
                    ui.label(
                        f"Core Immutable Protections ({total_items} rules)"
                    ).classes("text-lg font-bold")
                    ui.label(
                        "These protections are always active and cannot be overridden."
                    ).classes("text-xs text-grey-6")
                    with ui.scroll_area().classes("w-full").style("max-height: 300px"):
                        for category, items in CORE_PROTECTIONS.items():
                            ui.label(category).classes("font-bold text-sm mt-2")
                            for item in items:
                                with ui.row().classes("items-center gap-1 ml-4"):
                                    ui.image("/images/tray-icon-16.png").classes(
                                        "w-4 h-4"
                                    )
                                    ui.label(item).classes("text-xs")

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Action Mode").classes("text-lg font-bold")
                        field_help_icon("ssrf_protection.action")
                    ui.label("What happens when an SSRF attempt is detected.").classes(
                        "text-xs text-grey-6"
                    )
                    action = sp.get("action", "block")
                    act_sel = ui.select(
                        options={
                            "block": "Block — reject request",
                            "ask": "Ask — prompt user (block if headless)",
                            "ask:warn": "Ask — prompt user (warn if headless)",
                            "ask:log-only": "Ask — prompt user (log-only if headless)",
                            "warn": "Warn — allow with warning",
                            "log-only": "Log Only — silent logging",
                        },
                        value=action,
                    ).classes("w-64")

                    async def save_action(e):
                        cfg = await run.io_bound(load_web_config)
                        sect = cfg.get("ssrf_protection", {})
                        if not isinstance(sect, dict):
                            sect = {}
                        sect["action"] = e.value
                        cfg["ssrf_protection"] = sect
                        await run.io_bound(save_web_config, cfg)
                        ui.notify(f"Action: {e.value}", type="positive")

                    act_sel.on_value_change(save_action)

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Allow Localhost").classes("text-lg font-bold")
                        field_help_icon("ssrf_protection.allow_localhost")
                    ui.label(
                        "Allow requests to localhost and 127.0.0.1 (not recommended)."
                    ).classes("text-xs text-grey-6")
                    lh_sw = ui.switch(
                        "Allow Localhost",
                        value=sp.get("allow_localhost", False),
                    )

                    async def save_localhost(e):
                        cfg = await run.io_bound(load_web_config)
                        sect = cfg.get("ssrf_protection", {})
                        if not isinstance(sect, dict):
                            sect = {}
                        sect["allow_localhost"] = e.value
                        cfg["ssrf_protection"] = sect
                        await run.io_bound(save_web_config, cfg)
                        ui.notify("Saved", type="positive")

                    lh_sw.on_value_change(save_localhost)

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Additional Blocked IPs").classes("text-lg font-bold")
                        field_help_icon("ssrf_protection.additional_blocked_ips")
                    ui.label("Custom IP addresses or CIDR ranges to block.").classes(
                        "text-xs text-grey-6"
                    )

                    blocked_ips = sp.get("additional_blocked_ips", [])
                    if blocked_ips:
                        for idx, ip in enumerate(blocked_ips):
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon("block").classes("text-red")
                                ui.label(ip).classes("flex-grow text-sm").style(
                                    "font-family: monospace"
                                )

                                async def remove_ip(i=idx):
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("ssrf_protection", {})
                                    if not isinstance(sect, dict):
                                        return
                                    items = sect.get("additional_blocked_ips", [])
                                    if i < len(items):
                                        items.pop(i)
                                        sect["additional_blocked_ips"] = items
                                        cfg["ssrf_protection"] = sect
                                        await run.io_bound(save_web_config, cfg)
                                        ui.notify("IP removed", type="positive")
                                        await refresh()

                                ui.button(
                                    icon="delete", on_click=remove_ip, color="red"
                                ).props("flat dense size=sm")
                    else:
                        ui.label("No additional blocked IPs.").classes(
                            "text-grey-6 text-sm"
                        )

                    with ui.row().classes("items-center gap-2 mt-2"):
                        ip_input = (
                            ui.input(placeholder="Enter IP or CIDR (e.g. 10.20.0.0/16)")
                            .props("dense outlined")
                            .classes("flex-grow")
                        )

                        async def add_ip():
                            val = ip_input.value.strip()
                            if not val:
                                ui.notify("Enter an IP or CIDR", type="negative")
                                return
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("ssrf_protection", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            items = sect.get("additional_blocked_ips", [])
                            if val in items:
                                ui.notify("IP already exists", type="warning")
                                return
                            items.append(val)
                            sect["additional_blocked_ips"] = items
                            cfg["ssrf_protection"] = sect
                            await run.io_bound(save_web_config, cfg)
                            ip_input.value = ""
                            ui.notify(f"Added: {val}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_ip).props("dense")

                with ui.card().classes("w-full"):
                    ui.label("Additional Blocked Domains").classes("text-lg font-bold")
                    ui.label("Custom domain names to block.").classes(
                        "text-xs text-grey-6"
                    )

                    blocked_domains = sp.get("additional_blocked_domains", [])
                    if blocked_domains:
                        for idx, domain in enumerate(blocked_domains):
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon("block").classes("text-red")
                                ui.label(domain).classes("flex-grow text-sm").style(
                                    "font-family: monospace"
                                )

                                async def remove_domain(i=idx):
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("ssrf_protection", {})
                                    if not isinstance(sect, dict):
                                        return
                                    items = sect.get("additional_blocked_domains", [])
                                    if i < len(items):
                                        items.pop(i)
                                        sect["additional_blocked_domains"] = items
                                        cfg["ssrf_protection"] = sect
                                        await run.io_bound(save_web_config, cfg)
                                        ui.notify("Domain removed", type="positive")
                                        await refresh()

                                ui.button(
                                    icon="delete",
                                    on_click=remove_domain,
                                    color="red",
                                ).props("flat dense size=sm")
                    else:
                        ui.label("No additional blocked domains.").classes(
                            "text-grey-6 text-sm"
                        )

                    with ui.row().classes("items-center gap-2 mt-2"):
                        dom_input = (
                            ui.input(placeholder="Enter domain (e.g. evil.example.com)")
                            .props("dense outlined")
                            .classes("flex-grow")
                        )

                        async def add_domain():
                            val = dom_input.value.strip()
                            if not val:
                                ui.notify("Enter a domain", type="negative")
                                return
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("ssrf_protection", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            items = sect.get("additional_blocked_domains", [])
                            if val in items:
                                ui.notify("Domain already exists", type="warning")
                                return
                            items.append(val)
                            sect["additional_blocked_domains"] = items
                            cfg["ssrf_protection"] = sect
                            await run.io_bound(save_web_config, cfg)
                            dom_input.value = ""
                            ui.notify(f"Added: {val}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_domain).props("dense")

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Allowed Domains").classes("text-lg font-bold")
                        field_help_icon("ssrf_protection.allowed_domains")
                    ui.label(
                        "Domains explicitly allowed for outbound requests. "
                        "Cannot override immutable core protections."
                    ).classes("text-xs text-grey-6")

                    allowed = sp.get("allowed_domains", [])
                    if allowed:
                        for idx, domain in enumerate(allowed):
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon("check").classes("text-green")
                                ui.label(domain).classes("flex-grow text-sm").style(
                                    "font-family: monospace"
                                )

                                async def remove_allowed(i=idx):
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("ssrf_protection", {})
                                    if not isinstance(sect, dict):
                                        return
                                    items = sect.get("allowed_domains", [])
                                    if i < len(items):
                                        items.pop(i)
                                        sect["allowed_domains"] = items
                                        cfg["ssrf_protection"] = sect
                                        await run.io_bound(save_web_config, cfg)
                                        ui.notify("Domain removed", type="positive")
                                        await refresh()

                                ui.button(
                                    icon="delete",
                                    on_click=remove_allowed,
                                    color="red",
                                ).props("flat dense size=sm")
                    else:
                        ui.label("No allowed domains.").classes("text-grey-6 text-sm")

                    with ui.row().classes("items-center gap-2 mt-2"):
                        allow_input = (
                            ui.input(placeholder="Enter domain (e.g. api.example.com)")
                            .props("dense outlined")
                            .classes("flex-grow")
                        )

                        async def add_allowed():
                            val = allow_input.value.strip()
                            if not val:
                                ui.notify("Enter a domain", type="negative")
                                return
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("ssrf_protection", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            items = sect.get("allowed_domains", [])
                            if val in items:
                                ui.notify("Domain already exists", type="warning")
                                return
                            items.append(val)
                            sect["allowed_domains"] = items
                            cfg["ssrf_protection"] = sect
                            await run.io_bound(save_web_config, cfg)
                            allow_input.value = ""
                            ui.notify(f"Added: {val}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_allowed).props(
                            "dense"
                        )

                # --- Ignore files ---
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Ignore Files").classes("text-lg font-bold")
                        field_help_icon("ssrf_protection.ignore_files")
                    ui.label(
                        "Glob patterns for files to exclude from SSRF checks."
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
                                    sect = cfg.get("ssrf_protection", {})
                                    if not isinstance(sect, dict):
                                        return
                                    items = sect.get("ignore_files", [])
                                    if i < len(items):
                                        items.pop(i)
                                        sect["ignore_files"] = items
                                        cfg["ssrf_protection"] = sect
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
                            ui.input(
                                placeholder="Enter glob pattern (e.g. **/tests/**)"
                            )
                            .props("dense outlined")
                            .classes("flex-grow")
                        )

                        async def add_ignore_file():
                            val = if_input.value.strip()
                            if not val:
                                ui.notify("Enter a pattern", type="negative")
                                return
                            cfg = await run.io_bound(load_web_config)
                            sect = cfg.get("ssrf_protection", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            items = sect.get("ignore_files", [])
                            if val in items:
                                ui.notify("Pattern already exists", type="warning")
                                return
                            items.append(val)
                            sect["ignore_files"] = items
                            cfg["ssrf_protection"] = sect
                            await run.io_bound(save_web_config, cfg)
                            if_input.value = ""
                            ui.notify(f"Added: {val}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_ignore_file).props(
                            "dense"
                        )

                # --- Ignore tools ---
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Ignore Tools").classes("text-lg font-bold")
                        field_help_icon("ssrf_protection.ignore_tools")
                    ui.label("Tool name patterns to exclude from SSRF checks.").classes(
                        "text-xs text-grey-6"
                    )

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
                                    sect = cfg.get("ssrf_protection", {})
                                    if not isinstance(sect, dict):
                                        return
                                    items = sect.get("ignore_tools", [])
                                    if i < len(items):
                                        items.pop(i)
                                        sect["ignore_tools"] = items
                                        cfg["ssrf_protection"] = sect
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
                            sect = cfg.get("ssrf_protection", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            items = sect.get("ignore_tools", [])
                            if val in items:
                                ui.notify("Pattern already exists", type="warning")
                                return
                            items.append(val)
                            sect["ignore_tools"] = items
                            cfg["ssrf_protection"] = sect
                            await run.io_bound(save_web_config, cfg)
                            it_input.value = ""
                            ui.notify(f"Added: {val}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_ignore_tool).props(
                            "dense"
                        )

                with ui.card().classes("w-full"):
                    ui.label("SSRF Statistics").classes("text-lg font-bold")
                    total = await run.io_bound(_load_stats)
                    if total is None:
                        ui.label("Violation logging not available.").classes(
                            "text-grey-6 text-sm"
                        )
                    elif total == 0:
                        ui.label("No SSRF attempts blocked yet.").classes(
                            "text-grey-6 text-sm"
                        )
                    else:
                        ui.label(f"Total SSRF attempts blocked: {total}").classes(
                            "text-sm"
                        )

        ui.timer(0.1, refresh, once=True)
