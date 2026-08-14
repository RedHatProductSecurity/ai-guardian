"""MCP Security page — read-only MCP security audit results."""

import logging

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar

logger = logging.getLogger(__name__)


def _run_audit_via_service(service, daemon_name: str):
    """Run MCP audit through DaemonService (handles local and remote)."""
    try:
        target = service.get_target_by_name(daemon_name)
        if target:
            return service.get_mcp_audit(target)
    except Exception as e:
        logger.debug("MCP audit via daemon failed: %s", e)
    return None


def create_mcp_security_page(service, daemon_name: str):
    """Create the MCP Security audit page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/mcp-security")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("MCP Security Audit").classes("text-2xl font-bold")
        ui.label("Scan MCP server configurations for security issues.").classes(
            "text-xs text-grey-6"
        )

        content = ui.column().classes("w-full gap-4")

        async def run_audit():
            content.clear()
            with content:
                ui.label("Running audit...").classes("text-grey-6")

            data = await run.io_bound(_run_audit_via_service, service, daemon_name)

            content.clear()
            with content:
                if data is None or "error" in (data or {}):
                    with ui.card().classes("w-full"):
                        ui.label("Audit Unavailable").classes("text-lg font-bold")
                        err = (data or {}).get("error", "Unknown error")
                        ui.label(f"MCP audit could not be loaded: {err}").classes(
                            "text-sm text-grey-6"
                        )
                    return

                servers = data.get("servers", [])
                findings = data.get("findings", [])
                trusted = data.get("trusted", 0)
                untrusted = data.get("untrusted", 0)
                scan_ms = data.get("scan_time_ms")

                # Summary
                with ui.card().classes("w-full"):
                    ui.label("Scan Summary").classes("text-lg font-bold")

                    with ui.row().classes("items-center gap-4"):
                        ui.label(f"Servers: {len(servers)} total").classes("text-sm")
                        if trusted:
                            ui.badge(f"{trusted} trusted", color="green").classes(
                                "text-xs"
                            )
                        if untrusted:
                            ui.badge(f"{untrusted} untrusted", color="red").classes(
                                "text-xs"
                            )

                    if findings:
                        sev_counts = {}
                        for f in findings:
                            s = f.get("severity", "info").lower()
                            sev_counts[s] = sev_counts.get(s, 0) + 1
                        parts = []
                        for s in ["critical", "high", "medium", "low", "info"]:
                            if s in sev_counts:
                                parts.append(f"{sev_counts[s]} {s}")
                        ui.label(f"Findings: {', '.join(parts)}").classes("text-sm")
                    else:
                        ui.label("No issues found.").classes("text-sm text-green")

                    if scan_ms is not None:
                        ui.label(f"Scan time: {scan_ms}ms").classes(
                            "text-xs text-grey-6"
                        )

                # Servers
                with ui.card().classes("w-full"):
                    ui.label("Discovered Servers").classes("text-lg font-bold")
                    if servers:
                        with ui.grid(columns="180px 120px 120px 100px 80px").classes(
                            "w-full gap-y-2 gap-x-4 items-center"
                        ):
                            for h in (
                                "Server",
                                "IDE",
                                "Command",
                                "Trust",
                                "Env Vars",
                            ):
                                ui.label(h).classes("text-xs text-grey-6 font-bold")

                            for srv in servers:
                                name = srv.get("name", "")
                                is_trusted = srv.get("is_trusted", False)
                                ide_configs = srv.get("ide_configs", [])

                                if ide_configs:
                                    for i, ic in enumerate(ide_configs):
                                        if i == 0:
                                            ui.label(name).classes("font-bold text-sm")
                                        else:
                                            ui.label("").classes("text-sm")
                                        ui.label(ic.get("ide", "")).classes("text-xs")
                                        cmd = ic.get("command", "")
                                        if len(cmd) > 15:
                                            cmd = cmd.rsplit("/", 1)[-1][:15]
                                        ui.label(cmd).classes("text-xs text-grey-6")
                                        if i == 0:
                                            trust_color = (
                                                "green" if is_trusted else "red"
                                            )
                                            trust_label = (
                                                "trusted" if is_trusted else "untrusted"
                                            )
                                            ui.badge(
                                                trust_label, color=trust_color
                                            ).classes("text-xs")
                                        else:
                                            ui.label("").classes("text-xs")
                                        env_count = len(ic.get("env_var_names", []))
                                        ui.label(
                                            str(env_count) if env_count else "—"
                                        ).classes("text-xs text-grey-6")
                                else:
                                    ui.label(name).classes("font-bold text-sm")
                                    ide_names = srv.get("ide_sources", [])
                                    ui.label(", ".join(ide_names) or "—").classes(
                                        "text-xs"
                                    )
                                    cmd = srv.get("command", "")
                                    ui.label(
                                        cmd if len(cmd) <= 15 else cmd[:12] + "..."
                                    ).classes("text-xs text-grey-6")
                                    trust_color = "green" if is_trusted else "red"
                                    trust_label = (
                                        "trusted" if is_trusted else "untrusted"
                                    )
                                    ui.badge(trust_label, color=trust_color).classes(
                                        "text-xs"
                                    )
                                    ui.label("—").classes("text-xs text-grey-6")
                    else:
                        ui.label(
                            "No MCP servers found in IDE configuration files."
                        ).classes("text-grey-6 text-sm")

                # Findings
                if findings:
                    with ui.card().classes("w-full"):
                        ui.label("Findings").classes("text-lg font-bold")
                        sev_colors = {
                            "critical": "red",
                            "high": "orange",
                            "medium": "amber",
                            "low": "blue-grey",
                            "info": "grey",
                        }
                        sev_icons = {
                            "critical": "error",
                            "high": "warning",
                            "medium": "info",
                            "low": "help",
                            "info": "help_outline",
                        }
                        for finding in findings:
                            sev = finding.get("severity", "info").lower()
                            msg = finding.get("message", "")
                            srv_name = finding.get("server_name", "")
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.icon(sev_icons.get(sev, "help")).classes(
                                    f"text-{sev_colors.get(sev, 'grey')}"
                                )
                                ui.badge(
                                    sev.upper(),
                                    color=sev_colors.get(sev, "grey"),
                                ).classes("text-xs")
                                if srv_name:
                                    ui.label(srv_name).classes("font-bold text-xs")
                                ui.label(msg).classes("text-sm flex-grow")
                            ui.separator().classes("my-1")

                # Run audit button
                ui.button("Run Audit", icon="refresh", on_click=run_audit).props(
                    "dense"
                ).classes("mt-2")

        ui.timer(0.1, run_audit, once=True)
