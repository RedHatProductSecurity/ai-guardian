"""Daemon detail page — builds layout once, updates values on refresh."""

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.components.local_time import inject_local_time_js


def _load_local_daemon_config():
    from ai_guardian.config.loaders import _load_config_file

    cfg, _ = _load_config_file()
    cfg = cfg or {}
    daemon_cfg = cfg.get("daemon", {})
    return {
        "idle_timeout_minutes": daemon_cfg.get("idle_timeout_minutes", 0),
        "client_timeout_seconds": daemon_cfg.get("client_timeout_seconds", 2.0),
        "tray_enabled": daemon_cfg.get("tray", {}).get("enabled", True),
        "tray_auto_install": daemon_cfg.get("tray", {}).get("auto_install", True),
        "terminal_app": daemon_cfg.get("tray", {}).get("terminal_app", ""),
    }


def _save_local_daemon_config(
    idle_timeout,
    client_timeout,
    tray_enabled,
    tray_auto_install,
    terminal_app="",
):
    import json
    from ai_guardian.config.utils import get_config_dir

    config_path = get_config_dir() / "ai-guardian.json"
    if config_path.exists():
        full_config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        full_config = {}

    daemon_config = full_config.get("daemon", {})
    daemon_config["idle_timeout_minutes"] = idle_timeout
    daemon_config["client_timeout_seconds"] = client_timeout
    tray_cfg = daemon_config.get("tray", {})
    tray_cfg["enabled"] = tray_enabled
    tray_cfg["auto_install"] = tray_auto_install
    term_val = (terminal_app or "").strip()
    if term_val:
        tray_cfg["terminal_app"] = term_val
    else:
        tray_cfg.pop("terminal_app", None)
    daemon_config["tray"] = tray_cfg
    daemon_config.pop("mode", None)
    full_config["daemon"] = daemon_config

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(full_config, indent=2) + "\n", encoding="utf-8")

    try:
        from ai_guardian.daemon.client import send_reload_config

        send_reload_config()
    except Exception:
        pass  # intentionally silent — optional dependency


def _is_local_daemon_running():
    try:
        from ai_guardian.daemon.client import is_daemon_running

        return is_daemon_running()
    except Exception:
        return False


def _start_local_daemon():
    try:
        from ai_guardian.daemon.client import start_daemon_background

        return start_daemon_background()
    except Exception:
        return False


def _stop_local_daemon():
    try:
        from ai_guardian.daemon.client import send_shutdown

        return send_shutdown()
    except Exception:
        return False


def _fmt_uptime(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    return f"{int(seconds / 3600)}h {int((seconds % 3600) / 60)}m"


STAT_KEYS = [
    ("version", "Version"),
    ("uptime_seconds", "Uptime"),
    ("paused", "Paused"),
    ("request_count", "Requests"),
    ("blocked_count", "Blocked"),
    ("warning_count", "Warnings"),
    ("log_only_count", "Log Only"),
    ("violation_count", "Violations"),
    ("mcp_installed", "MCP Installed"),
    ("pause_remaining_seconds", "Pause Remaining"),
]


def create_daemon_detail_page(service, daemon_name: str):
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/daemon")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label(f"Daemon: {daemon_name}").classes("text-2xl font-bold")

        # --- Status Card (values updated on refresh) ---
        with ui.card().classes("w-full"):
            ui.label("Status").classes("text-lg font-bold")
            stat_labels = {}
            with ui.grid(columns=2).classes("gap-2 text-sm"):
                for key, display in STAT_KEYS:
                    ui.label(f"{display}:").classes("text-grey-6")
                    lbl = ui.label("—").classes("font-bold")
                    stat_labels[key] = lbl

        # --- Info Card (built once on first refresh) ---
        info_container = ui.column().classes("w-full")

        # --- Controls Card (rebuilt on refresh for pause/resume state) ---
        with ui.card().classes("w-full"):
            ui.label("Controls").classes("text-lg font-bold")
            controls_container = ui.column().classes("gap-2")

        # --- Config Card (built once on first refresh) ---
        config_container = ui.column().classes("w-full")

        # --- Features Card (built once on first refresh) ---
        features_container = ui.column().classes("w-full")

        # --- Violations Card (updated on refresh) ---
        with ui.card().classes("w-full"):
            ui.label("Recent Violations").classes("text-lg font-bold")
            violations_container = ui.column().classes("w-full")

        _info_built = {"done": False}

        async def refresh():
            if ui.context.client.is_deleted:
                return
            await run.io_bound(service.refresh_targets)
            target = service.get_target_by_name(daemon_name)
            if not target:
                for lbl in stat_labels.values():
                    lbl.text = "—"
                return

            stats = None
            all_status = await run.io_bound(service.get_all_daemon_status)
            for entry in all_status:
                if entry["target"].name == daemon_name:
                    stats = entry["status"]
                    break

            # Update stat labels (no rebuild)
            if stats:
                for key, _ in STAT_KEYS:
                    val = stats.get(key)
                    lbl = stat_labels[key]
                    if key == "uptime_seconds":
                        lbl.text = _fmt_uptime(val or 0)
                    elif key == "pause_remaining_seconds":
                        if val and val > 0:
                            lbl.text = _fmt_uptime(val)
                            lbl.set_visibility(True)
                            stat_labels[key].set_visibility(True)
                        else:
                            lbl.text = "—"
                    elif key == "paused":
                        lbl.text = "Yes" if val else "No"
                    elif key == "mcp_installed":
                        lbl.text = "Yes" if val else "No"
                    elif val is not None:
                        lbl.text = str(val)
                    else:
                        lbl.text = "—"
            else:
                for lbl in stat_labels.values():
                    lbl.text = "—"

            # Build info, config, features once
            if not _info_built["done"] and target:
                _info_built["done"] = True

                # Info card
                with info_container:
                    with ui.card().classes("w-full"):
                        ui.label("Info").classes("text-lg font-bold")
                        with ui.grid(columns=2).classes("gap-1 text-sm"):
                            ui.label("Runtime:").classes("text-grey-6")
                            ui.label(target.runtime)
                            if target.host:
                                ui.label("Host:").classes("text-grey-6")
                                ui.label(target.host)
                            if target.port:
                                ui.label("Port:").classes("text-grey-6")
                                ui.label(str(target.port))
                            if target.runtime == "local":
                                from ai_guardian.daemon import get_socket_path

                                ui.label("Socket:").classes("text-grey-6")
                                ui.label(str(get_socket_path()))

                # Config card (local only)
                if target.runtime == "local":
                    daemon_cfg = await run.io_bound(_load_local_daemon_config)
                    with config_container:
                        with ui.card().classes("w-full"):
                            ui.label("Configuration").classes("text-lg font-bold")
                            ui.label(
                                "Changes are saved to config and"
                                " daemon is reloaded automatically."
                            ).classes("text-xs text-grey-6")

                            with ui.column().classes("gap-3 mt-2"):
                                with ui.row().classes("items-center gap-2"):
                                    cfg_idle = (
                                        ui.number(
                                            label="Idle Timeout (minutes)",
                                            value=daemon_cfg["idle_timeout_minutes"],
                                            min=0,
                                            step=5,
                                        )
                                        .props("dense outlined")
                                        .classes("w-40")
                                    )
                                    ui.label("0 = never auto-stop").classes(
                                        "text-xs text-grey-6"
                                    )

                                cfg_client = (
                                    ui.number(
                                        label="Client Timeout (seconds)",
                                        value=daemon_cfg["client_timeout_seconds"],
                                        min=0.5,
                                        max=10.0,
                                        step=0.5,
                                    )
                                    .props("dense outlined")
                                    .classes("w-40")
                                )

                                cfg_tray = ui.switch(
                                    "System Tray",
                                    value=daemon_cfg["tray_enabled"],
                                )
                                cfg_auto_install = ui.switch(
                                    "Auto-Install Tray",
                                    value=daemon_cfg["tray_auto_install"],
                                )
                                cfg_terminal_app = (
                                    ui.input(
                                        label="Terminal App",
                                        value=daemon_cfg.get("terminal_app", ""),
                                        placeholder="auto-detect",
                                    )
                                    .props("dense outlined")
                                    .classes("w-40")
                                    .tooltip(
                                        "macOS: app name (iTerm). "
                                        "Linux: binary (alacritty). "
                                        "Windows: exe (wt). "
                                        "Empty = auto-detect"
                                    )
                                )

                                async def do_save_config(
                                    idle=cfg_idle,
                                    client=cfg_client,
                                    tray=cfg_tray,
                                    auto=cfg_auto_install,
                                    term=cfg_terminal_app,
                                ):
                                    try:
                                        await run.io_bound(
                                            _save_local_daemon_config,
                                            int(idle.value or 0),
                                            float(client.value or 2.0),
                                            tray.value,
                                            auto.value,
                                            term.value or "",
                                        )
                                        ui.notify(
                                            "Daemon config saved",
                                            type="positive",
                                        )
                                    except Exception as e:
                                        ui.notify(
                                            f"Save failed: {e}",
                                            type="negative",
                                        )

                                ui.button(
                                    "Save",
                                    icon="save",
                                    on_click=do_save_config,
                                ).props("dense")

                # Features card
                cfg = await run.io_bound(service.get_daemon_config, target)
                features = (cfg or {}).get("features", {})
                if features:
                    with features_container:
                        with ui.card().classes("w-full"):
                            ui.label("Features").classes("text-lg font-bold")
                            labels = {
                                "secret_scanning": "Secret Scanning",
                                "scan_pii": "PII Detection",
                                "prompt_injection": "Prompt Injection",
                                "config_scanning": "Config Scanner",
                                "ssrf_protection": "SSRF Protection",
                                "violation_logging": "Violation Logging",
                                "secret_redaction": "Secret Redaction",
                                "permissions": "Permissions",
                                "security_instructions": "Security Instructions",
                                "mcp_server": "MCP Server",
                                "transcript_scanning": "Transcript Scanning",
                                "image_scanning": "Image Scanning",
                            }
                            with ui.grid(columns=2).classes("gap-1"):
                                for key, label in labels.items():
                                    enabled = features.get(key, False)
                                    icon = "check_circle" if enabled else "cancel"
                                    color = "text-green" if enabled else "text-red"
                                    with ui.row().classes("items-center gap-1"):
                                        ui.icon(icon).classes(f"{color} text-sm")
                                        ui.label(label).classes("text-sm")

                            scanner_actions = features.get("scanner_actions", {})
                            proactive = features.get("proactive_level", "low")
                            unique_actions = (
                                sorted(set(scanner_actions.values()))
                                if scanner_actions
                                else ["block"]
                            )
                            actions_summary = ", ".join(unique_actions)
                            with ui.row().classes("gap-4 text-sm text-grey-6 mt-1"):
                                ui.label(f"Actions: {actions_summary}")
                                ui.label(f"Proactive level: {proactive}")

            # Rebuild controls only (small section)
            controls_container.clear()
            paused = stats and stats.get("paused")
            with controls_container:
                if paused:

                    async def do_resume():
                        ok = await run.io_bound(service.resume_daemon, target)
                        ui.notify(
                            "Resumed" if ok else "Failed",
                            type="positive" if ok else "negative",
                        )
                        await refresh()

                    ui.button(
                        "Resume",
                        icon="play_arrow",
                        color="green",
                        on_click=do_resume,
                    )
                else:
                    with ui.row().classes("items-center gap-2"):
                        pause_input = (
                            ui.number(
                                label="Minutes",
                                value=30,
                                min=0,
                                max=1440,
                                step=5,
                            )
                            .props("dense outlined")
                            .classes("w-28")
                        )
                        ui.label("0 = indefinite").classes("text-xs text-grey-6")

                        async def do_pause(inp=pause_input):
                            minutes = int(inp.value or 30)
                            ok = await run.io_bound(
                                service.pause_daemon,
                                target,
                                minutes,
                            )
                            msg = (
                                "indefinitely" if minutes == 0 else f"for {minutes} min"
                            )
                            ui.notify(
                                f"Paused {msg}" if ok else "Failed",
                                type="positive" if ok else "negative",
                            )
                            await refresh()

                        ui.button(
                            "Pause",
                            icon="pause",
                            color="amber",
                            on_click=do_pause,
                        )

                with ui.row().classes("gap-2"):

                    async def do_reload():
                        ok = await run.io_bound(service.reload_daemon, target)
                        ui.notify(
                            "Config reloaded" if ok else "Failed",
                            type="positive" if ok else "negative",
                        )

                    ui.button(
                        "Reload Config",
                        icon="refresh",
                        on_click=do_reload,
                    )

                    if target.runtime == "local":
                        running = await run.io_bound(_is_local_daemon_running)

                        async def do_start():
                            ok = await run.io_bound(_start_local_daemon)
                            ui.notify(
                                "Started" if ok else "Failed",
                                type="positive" if ok else "negative",
                            )
                            await refresh()

                        async def do_stop():
                            ok = await run.io_bound(_stop_local_daemon)
                            ui.notify(
                                "Stopped" if ok else "Failed",
                                type="positive" if ok else "negative",
                            )
                            await refresh()

                        if running:
                            ui.button(
                                "Stop",
                                icon="stop",
                                color="red",
                                on_click=do_stop,
                            )
                        else:
                            ui.button(
                                "Start",
                                icon="play_arrow",
                                color="green",
                                on_click=do_start,
                            )

            # Update violations (small table)
            violations_container.clear()
            v_data = await run.io_bound(service.get_daemon_violations, target, 10)
            vlist = (v_data or {}).get("violations", [])
            with violations_container:
                if vlist:
                    table = ui.table(
                        columns=[
                            {
                                "name": "timestamp",
                                "label": "Time",
                                "field": "timestamp",
                            },
                            {"name": "type", "label": "Type", "field": "type"},
                            {
                                "name": "severity",
                                "label": "Severity",
                                "field": "severity",
                            },
                            {
                                "name": "action",
                                "label": "Action",
                                "field": "action",
                            },
                        ],
                        rows=vlist,
                        row_key="timestamp",
                    ).classes("w-full")
                    table.add_slot(
                        "body-cell-timestamp",
                        '<td><span class="utc-timestamp" '
                        'data-utc="{{props.value}}">'
                        "{{props.value.slice(0, 19)}}"
                        "</span></td>",
                    )
                    inject_local_time_js()
                else:
                    ui.label("No recent violations").classes("text-sm text-grey-6")

        ui.timer(10.0, refresh)
