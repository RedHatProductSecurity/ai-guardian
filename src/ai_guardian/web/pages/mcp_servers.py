"""MCP Settings page — proactive check level and support bundle config.

MCP permission rules have been consolidated into the Permission Rules page.
"""

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.config_helpers import load_web_config, save_web_config


# Keep _get_mcp_rules for backward compatibility (used by tests)
def _get_mcp_rules(config):
    """Extract permission rules where matcher starts with mcp__."""
    permissions = config.get("permissions", {})
    if not isinstance(permissions, dict):
        return []
    rules = permissions.get("rules", [])
    return [r for r in rules if r.get("matcher", "").startswith("mcp__")]


def create_mcp_servers_page(service, daemon_name: str):
    """Create the MCP Settings page (proactive level + support bundle)."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/mcp-servers")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("MCP Settings").classes("text-2xl font-bold")
        ui.label(
            "Configure MCP server proactive security checks "
            "and support bundle export."
        ).classes("text-xs text-grey-6")

        content = ui.column().classes("w-full gap-4")

        async def refresh():
            content.clear()
            config = await run.io_bound(load_web_config)

            with content:
                # Proactive Level
                with ui.card().classes("w-full"):
                    ui.label("Proactive Check Level").classes("text-lg font-bold")
                    ui.label(
                        "Controls how aggressively MCP tools "
                        "perform security checks. Paused skips action-gating; hooks still enforce."
                    ).classes("text-xs text-grey-6")
                    mcp_cfg = config.get("mcp_server", {})
                    level = (
                        mcp_cfg.get("proactive_level", "low")
                        if isinstance(mcp_cfg, dict)
                        else "low"
                    )
                    sel = ui.select(
                        options={
                            "low": "Low \u2014 check only when asked",
                            "medium": "Medium \u2014 check unfamiliar paths/commands",
                            "high": "High \u2014 check everything",
                            "paused": "Paused \u2014 skip checks; hooks still enforce",
                        },
                        value=level,
                    ).classes("w-96")

                    async def save_level(e):
                        cfg = await run.io_bound(load_web_config)
                        if "mcp_server" not in cfg or not isinstance(
                            cfg["mcp_server"], dict
                        ):
                            cfg["mcp_server"] = {}
                        cfg["mcp_server"]["proactive_level"] = e.value
                        await run.io_bound(save_web_config, cfg)
                        ui.notify(
                            f"Proactive level: {e.value}",
                            type="positive",
                        )

                    sel.on_value_change(save_level)

                # Support Bundle
                with ui.card().classes("w-full"):
                    ui.label("Support Bundle Export").classes("text-lg font-bold")
                    support = config.get("support", {})
                    dest_val = (
                        support.get("export_destination", "")
                        if isinstance(support, dict)
                        else ""
                    )
                    ttl_val = (
                        support.get("bundle_ttl_minutes", 30)
                        if isinstance(support, dict)
                        else 30
                    )

                    dest = (
                        ui.input(
                            label="Destination",
                            value=dest_val,
                            placeholder="~/support-bundles or s3://bucket/prefix/",
                        )
                        .props("outlined dense")
                        .classes("w-full")
                    )
                    ttl = (
                        ui.input(
                            label="Bundle TTL (minutes)",
                            value=str(ttl_val),
                            placeholder="30",
                        )
                        .props("outlined dense")
                        .classes("w-48")
                    )

                    async def save_support():
                        cfg = await run.io_bound(load_web_config)
                        if "support" not in cfg or not isinstance(cfg["support"], dict):
                            cfg["support"] = {}
                        cfg["support"]["export_destination"] = dest.value.strip()
                        try:
                            cfg["support"]["bundle_ttl_minutes"] = int(ttl.value)
                        except (ValueError, TypeError):
                            cfg["support"]["bundle_ttl_minutes"] = 30
                        await run.io_bound(save_web_config, cfg)
                        ui.notify("Support config saved", type="positive")

                    ui.button("Save", icon="save", on_click=save_support).props("dense")

                # Link to Permission Rules for MCP rule management
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("info").classes("text-blue")
                        ui.label(
                            "MCP permission rules are now managed in the "
                        ).classes("text-sm")
                        ui.link(
                            "Permission Rules",
                            f"/{daemon_name}/permission-rules",
                        ).classes("text-sm font-bold")
                        ui.label("page.").classes("text-sm")

        ui.timer(0.1, refresh, once=True)
