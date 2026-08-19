"""Secret Redaction page — redaction configuration and statistics."""

import re as re_mod
from datetime import datetime, timedelta, timezone

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.step_render import render_guardian_icon
from ai_guardian.web.components.help_panel import add_help_button, field_help_icon
from ai_guardian.web.config_helpers import load_web_config, save_web_config

PROTECTED_TYPES = {
    "API Keys & Tokens": [
        "OpenAI API Key (sk-...)",
        "OpenAI Project Key (sk-proj-...)",
        "GitHub Personal Token (ghp_...)",
        "GitHub OAuth Token (gho_...)",
        "GitHub Refresh Token (ghr_...)",
        "GitHub Secret Token (ghs_...)",
        "Anthropic API Key (sk-ant-...)",
        "GitLab Personal Token (glpat-...)",
        "Slack Token (xox-...)",
        "Google OAuth Token (ya29...)",
        "Google API Key (AIza...)",
        "npm Token (npm_...)",
        "PyPI Token (pypi-...)",
    ],
    "Cloud Credentials": [
        "AWS Access Key (AKIA...)",
        "AWS Secret Key (aws_secret_access_key=...)",
        "Azure Client Secret",
    ],
    "Payment & Services": [
        "Stripe Secret Key (sk_live_...)",
        "Stripe Test Secret Key (sk_test_...)",
        "Stripe Public Key (pk_live_...)",
        "Stripe Test Public Key (pk_test_...)",
        "Stripe Restricted Key (rk_live_...)",
        "Stripe Test Restricted Key (rk_test_...)",
        "Twilio API Key (SK...)",
        "SendGrid API Key (SG...)",
        "Mailgun API Key (key-...)",
    ],
    "Sensitive Data": [
        "Private Keys (PEM format)",
        "Environment Variable assignments",
        "Exported Environment Variables",
        "JSON API Key fields",
        "JSON Token fields",
        "JSON Password fields",
        "JSON Secret fields",
        "YAML/Config passwords",
        "HTTP Bearer Token (Authorization header)",
        "API Key Header (X-API-Key)",
        "Auth Token Header (X-Auth-Token)",
    ],
    "Connection Strings": [
        "MongoDB Connection String",
        "MySQL Connection String",
        "PostgreSQL Connection String",
        "Redis Connection String",
    ],
    "Generic Secrets": [
        "Hex Secret (with context keyword)",
        "Very Long Hex Secret (100+ chars)",
        "Base64 Secret (with context keyword)",
        "Very Long Base64 Secret (100+ chars)",
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
    """Parse an enabled value, returning (is_temp, until_dt, reason, is_enabled)."""
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


def _load_redaction_stats():
    """Load redaction statistics from violation logger."""
    from ai_guardian.web.config_helpers import load_web_violations

    result = load_web_violations(violation_type="secret_detected")
    violations = result.get("violations", []) if result else []
    if not violations:
        return 0, {}
    by_type = {}
    for v in violations:
        blocked = v.get("blocked", {}) or {}
        stype = blocked.get("secret_type", "unknown")
        by_type[stype] = by_type.get(stype, 0) + 1
    return len(violations), by_type


def _render_toggle(
    label, desc, is_temp, until_dt, reason, is_enabled, save_fn, refresh_fn
):
    """Render a toggle card with temp-disable support."""
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


def create_secret_redaction_page(service, daemon_name: str):
    """Create the Secret Redaction page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/secret-redaction")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.label("Secret Redaction Settings").classes("text-2xl font-bold")
            add_help_button("secret_redaction")
        ui.label("Configure how secrets are redacted from tool outputs.").classes(
            "text-xs text-grey-6"
        )

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)

            with content:
                sr = config.get("secret_redaction", {})
                if not isinstance(sr, dict):
                    sr = {}

                # --- Redaction toggle with temp-disable ---
                is_temp, until_dt, reason, is_enabled = _parse_enabled(
                    sr.get("enabled", False)
                )

                def save_redaction(value):
                    cfg = load_web_config()
                    sect = cfg.get("secret_redaction", {})
                    if not isinstance(sect, dict):
                        sect = {}
                    sect["enabled"] = value
                    cfg["secret_redaction"] = sect
                    save_web_config(cfg)

                _render_toggle(
                    "Secret Redaction",
                    "Redact detected secrets instead of blocking the operation.",
                    is_temp,
                    until_dt,
                    reason,
                    is_enabled,
                    save_redaction,
                    refresh,
                )

                # --- Protected types with scrollbar ---
                total_patterns = sum(len(v) for v in PROTECTED_TYPES.values())
                with ui.card().classes("w-full"):
                    ui.label(
                        f"Protected Secret Types ({total_patterns} patterns)"
                    ).classes("text-lg font-bold")
                    with ui.scroll_area().classes("w-full").style("max-height: 300px"):
                        for category, types in PROTECTED_TYPES.items():
                            ui.label(category).classes("font-bold text-sm mt-2")
                            for t in types:
                                with ui.row().classes("items-center gap-1 ml-4"):
                                    render_guardian_icon()
                                    ui.label(t).classes("text-xs")

                # --- Action mode ---
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Action Mode").classes("text-lg font-bold")
                        field_help_icon("secret_redaction")
                    ui.label(
                        "What happens when a secret is detected and redacted."
                    ).classes("text-xs text-grey-6")
                    action = sr.get("action", "warn")
                    act_sel = ui.select(
                        options={
                            "log-only": "Log Only — redact silently",
                            "warn": "Warn — redact and notify",
                        },
                        value=action,
                    ).classes("w-64")

                    async def save_action(e):
                        cfg = await run.io_bound(load_web_config)
                        sect = cfg.get("secret_redaction", {})
                        if not isinstance(sect, dict):
                            sect = {}
                        sect["action"] = e.value
                        cfg["secret_redaction"] = sect
                        await run.io_bound(save_web_config, cfg)
                        ui.notify(f"Action: {e.value}", type="positive")

                    act_sel.on_value_change(save_action)

                # --- Redaction options ---
                with ui.card().classes("w-full"):
                    ui.label("Redaction Options").classes("text-lg font-bold")

                    pf = ui.switch(
                        "Preserve Format",
                        value=sr.get("preserve_format", True),
                    )
                    ui.label(
                        "Show visible prefix/suffix for debugging (e.g., sk-***-xyz)."
                    ).classes("text-xs text-grey-6 ml-12")

                    lr = ui.switch(
                        "Log Redactions",
                        value=sr.get("log_redactions", True),
                    )
                    ui.label(
                        "Record all redactions in violation log for audit trail."
                    ).classes("text-xs text-grey-6 ml-12")

                    async def save_pf(e):
                        cfg = await run.io_bound(load_web_config)
                        sect = cfg.get("secret_redaction", {})
                        if not isinstance(sect, dict):
                            sect = {}
                        sect["preserve_format"] = e.value
                        cfg["secret_redaction"] = sect
                        await run.io_bound(save_web_config, cfg)
                        ui.notify("Saved", type="positive")

                    async def save_lr(e):
                        cfg = await run.io_bound(load_web_config)
                        sect = cfg.get("secret_redaction", {})
                        if not isinstance(sect, dict):
                            sect = {}
                        sect["log_redactions"] = e.value
                        cfg["secret_redaction"] = sect
                        await run.io_bound(save_web_config, cfg)
                        ui.notify("Saved", type="positive")

                    pf.on_value_change(save_pf)
                    lr.on_value_change(save_lr)

                # --- Additional patterns ---
                with ui.card().classes("w-full"):
                    ui.label("Additional Redaction Patterns").classes(
                        "text-lg font-bold"
                    )
                    ui.label(
                        "Custom regex patterns for organization-specific secrets."
                    ).classes("text-xs text-grey-6")

                    patterns = sr.get("additional_patterns", [])
                    if patterns:
                        for idx, pat in enumerate(patterns):
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon("code").classes("text-blue-4")
                                ui.label(pat).classes("flex-grow text-sm").style(
                                    "font-family: monospace"
                                )

                                async def remove_pat(i=idx):
                                    cfg = await run.io_bound(load_web_config)
                                    sect = cfg.get("secret_redaction", {})
                                    if not isinstance(sect, dict):
                                        return
                                    pats = sect.get("additional_patterns", [])
                                    if i < len(pats):
                                        pats.pop(i)
                                        sect["additional_patterns"] = pats
                                        cfg["secret_redaction"] = sect
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
                            sect = cfg.get("secret_redaction", {})
                            if not isinstance(sect, dict):
                                sect = {}
                            pats = sect.get("additional_patterns", [])
                            if pattern in pats:
                                ui.notify("Pattern already exists", type="warning")
                                return
                            pats.append(pattern)
                            sect["additional_patterns"] = pats
                            cfg["secret_redaction"] = sect
                            await run.io_bound(save_web_config, cfg)
                            pat_input.value = ""
                            ui.notify(f"Added: {pattern}", type="positive")
                            await refresh()

                        ui.button("Add", icon="add", on_click=add_pattern).props(
                            "dense"
                        )

                # --- Statistics ---
                with ui.card().classes("w-full"):
                    ui.label("Redaction Statistics").classes("text-lg font-bold")
                    total, by_type = await run.io_bound(_load_redaction_stats)
                    if total is None:
                        ui.label("Violation logging not available.").classes(
                            "text-grey-6 text-sm"
                        )
                    elif total == 0:
                        ui.label("No secrets redacted yet.").classes(
                            "text-grey-6 text-sm"
                        )
                    else:
                        ui.label(f"Total secrets detected: {total}").classes("text-sm")
                        if by_type:
                            ui.label("Top secret types:").classes(
                                "text-sm font-bold mt-2"
                            )
                            sorted_types = sorted(
                                by_type.items(), key=lambda x: x[1], reverse=True
                            )[:5]
                            for stype, count in sorted_types:
                                with ui.row().classes("items-center gap-2"):
                                    ui.label(f"{stype}:").classes(
                                        "text-sm text-grey-6 w-48"
                                    )
                                    ui.label(str(count)).classes("text-sm font-bold")

        ui.timer(0.1, refresh, once=True)
