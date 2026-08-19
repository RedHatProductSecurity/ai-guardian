"""Prompt Injection Jailbreak page — jailbreak categories and custom patterns."""

import re as re_mod
from datetime import datetime, timedelta, timezone

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.config_helpers import load_web_config, save_web_config

BUILTIN_JAILBREAK_CATEGORIES = {
    "Role-play Attacks": "DAN mode, sudo mode, unrestricted mode prompts",
    "Identity Manipulation": "Attempts to override system identity or role",
    "Constraint Removal": "Requests to ignore rules, bypass filters, remove limits",
    "Hypothetical Framing": "Using fictional scenarios to extract restricted content",
    "System Prompt Extraction": "Attempts to reveal system instructions or configuration",
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


def _load_jailbreak_stats():
    from ai_guardian.web.config_helpers import load_web_violations

    result = load_web_violations(violation_type="jailbreak_detected")
    violations = result.get("violations", []) if result else []
    if not violations:
        return 0, {}
    by_category = {}
    for v in violations:
        blocked = v.get("blocked", {}) or {}
        cat = blocked.get("category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1
    return len(violations), by_category


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


def create_pi_jailbreak_page(service, daemon_name: str):
    """Create the Prompt Injection Jailbreak page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/pi-jailbreak")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Jailbreak Detection").classes("text-2xl font-bold")
        ui.label(
            "Built-in jailbreak categories and custom jailbreak patterns."
        ).classes("text-xs text-grey-6")

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)

            with content:
                pi = config.get("prompt_injection", {})
                if not isinstance(pi, dict):
                    pi = {}

                with ui.card().classes("w-full"):
                    ui.label(
                        f"Built-in Jailbreak Categories ({len(BUILTIN_JAILBREAK_CATEGORIES)})"
                    ).classes("text-lg font-bold")
                    ui.label(
                        "These categories are always active and cannot be modified."
                    ).classes("text-xs text-grey-6")
                    for (
                        category,
                        description,
                    ) in BUILTIN_JAILBREAK_CATEGORIES.items():
                        with ui.row().classes("items-center gap-2 ml-4"):
                            ui.image("/images/tray-icon-16.png").classes("w-4 h-4")
                            ui.label(category).classes("font-bold text-sm")
                            ui.label(f"— {description}").classes("text-xs text-grey-6")

                with ui.card().classes("w-full"):
                    ui.label("Custom Jailbreak Patterns").classes("text-lg font-bold")
                    ui.label(
                        "Custom regex patterns to detect additional jailbreak attempts."
                    ).classes("text-xs text-grey-6")

                    patterns = pi.get("jailbreak_patterns", [])
                    if patterns:
                        for idx, pat in enumerate(patterns):
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon("code").classes("text-blue-4")
                                ui.label(pat).classes("flex-grow text-sm").style(
                                    "font-family: monospace"
                                )

                                async def remove_pat(i=idx):
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("prompt_injection", {})
                                    if not isinstance(sect, dict):
                                        return
                                    pats = sect.get("jailbreak_patterns", [])
                                    if i < len(pats):
                                        pats.pop(i)
                                        sect["jailbreak_patterns"] = pats
                                        cfg["prompt_injection"] = sect
                                        await run.io_bound(save_web_config, cfg)
                                        ui.notify("Pattern removed", type="positive")
                                        await refresh()

                                ui.button(
                                    icon="delete", on_click=remove_pat, color="red"
                                ).props("flat dense size=sm")
                    else:
                        ui.label("No custom jailbreak patterns.").classes(
                            "text-grey-6 text-sm"
                        )

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
                            sect = cfg.get("prompt_injection", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            pats = sect.get("jailbreak_patterns", [])
                            if pattern in pats:
                                ui.notify("Pattern already exists", type="warning")
                                return
                            pats.append(pattern)
                            sect["jailbreak_patterns"] = pats
                            cfg["prompt_injection"] = sect
                            await run.io_bound(save_web_config, cfg)
                            pat_input.value = ""
                            ui.notify(f"Added: {pattern}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_pattern).props(
                            "dense"
                        )

                with ui.card().classes("w-full"):
                    ui.label("Jailbreak Statistics").classes("text-lg font-bold")
                    total, by_category = await run.io_bound(_load_jailbreak_stats)
                    if total is None:
                        ui.label("Violation logging not available.").classes(
                            "text-grey-6 text-sm"
                        )
                    elif total == 0:
                        ui.label("No jailbreak attempts detected yet.").classes(
                            "text-grey-6 text-sm"
                        )
                    else:
                        ui.label(f"Total jailbreak attempts: {total}").classes(
                            "text-sm"
                        )
                        if by_category:
                            ui.label("By category:").classes("text-sm font-bold mt-2")
                            sorted_cats = sorted(
                                by_category.items(),
                                key=lambda x: x[1],
                                reverse=True,
                            )[:5]
                            for cat, count in sorted_cats:
                                with ui.row().classes("items-center gap-2"):
                                    ui.label(f"{cat}:").classes(
                                        "text-sm text-grey-6 w-48"
                                    )
                                    ui.label(str(count)).classes("text-sm font-bold")

        ui.timer(0.1, refresh, once=True)
