"""Effective Config page — merged configuration with per-key provenance."""

from nicegui import run, ui

from ai_guardian.web.components.header import create_header, create_sidebar


def _load_effective_data(project_dir=None):
    """Load merged config, provenance, and project config.

    Includes auto-generated directory rules with 'generated' provenance.
    For remote daemons, fetches via DaemonService REST API.

    Args:
        project_dir: Project directory for multi-project daemon routing.

    Returns (merged_config, provenance, project_config, error).
    """
    from ai_guardian.web.config_helpers import (
        _get_current_target,
        _is_remote_target,
        _daemon_service,
    )

    target = _get_current_target()
    if _is_remote_target(target):
        if project_dir:
            merged = _daemon_service.get_config_scoped(
                target, "merged", project_dir=project_dir
            )
            provenance = _daemon_service.get_config_provenance(
                target, project_dir=project_dir
            )
        else:
            merged = _daemon_service.get_config_scoped(target, "global")
            provenance = {}
        return merged or {}, provenance or {}, {}, None

    try:
        from ai_guardian.config.writer import (
            load_scoped_config,
            compute_detailed_provenance,
            _mark_all_provenance,
        )

        merged = load_scoped_config("merged", project_dir)
        if project_dir:
            provenance = compute_detailed_provenance(project_dir)
            project = load_scoped_config("project", project_dir)
        else:
            provenance = _mark_all_provenance(merged or {}, "global", True)
            project = {}

        _inject_generated_rules(merged, provenance)

        return merged, provenance, project, None
    except Exception as e:
        return None, None, None, str(e)


def _inject_generated_rules(merged, provenance):
    """Run auto-generation and inject generated rules into merged config and provenance."""
    if not merged:
        return
    auto_config = (merged.get("permissions") or {}).get("auto_directory_rules", {})
    if not auto_config.get("enabled"):
        return
    try:
        from ai_guardian.tools.directory_rules import (
            DirectoryRuleGenerator,
            insert_generated_rules,
        )

        generator = DirectoryRuleGenerator(merged)
        generated_rules = generator.generate_directory_rules()
        if not generated_rules:
            return
        insert_generated_rules(merged, generated_rules)

        dir_prov = provenance.get("directory_rules")
        if isinstance(dir_prov, dict):
            rules_prov = dir_prov.get("rules")
            if isinstance(rules_prov, list):
                for rule in generated_rules:
                    rules_prov.append({"value": rule, "source": "generated"})
            else:
                dir_prov["rules"] = [
                    {"value": r, "source": "generated"} for r in generated_rules
                ]
    except Exception:
        pass


def _get_active_project_dirs(service, daemon_name: str):
    """Get list of active project directories from daemon stats."""
    try:
        if not service:
            return []
        target = service.get_target_by_name(daemon_name)
        if not target:
            return []
        status = service._client.get_status(target)
        if status:
            return status.get("active_project_dirs") or []
    except Exception:
        pass  # intentionally silent — best-effort operation
    return []


def _resolve_project_root(working_dir):
    """Resolve git root from a working directory."""
    if not working_dir:
        return None
    try:
        from ai_guardian.scanners.gitleaks import find_project_root

        root = find_project_root(working_dir)
        return str(root) if root else working_dir
    except Exception:
        return working_dir


def _provenance_color(source: str) -> str:
    """CSS color for a provenance source."""
    if source == "project":
        return "blue"
    if source == "generated":
        return "amber-8"
    return "grey-6"


def _provenance_label(source: str) -> str:
    if source == "project":
        return "Project"
    if source == "generated":
        return "Generated"
    return "Global"


def _render_tree(
    config: dict, provenance: dict, parent_element, diff_only: bool = False
):
    """Recursively render config tree with provenance badges."""
    for key in sorted(config.keys()):
        if key.startswith("_"):
            continue
        value = config[key]
        prov = provenance.get(key)

        if diff_only and not _has_project_override(prov):
            continue

        if isinstance(value, dict) and isinstance(prov, dict):
            with parent_element:
                with ui.expansion(key, icon="folder").classes("w-full"):
                    inner = ui.column().classes("pl-4 w-full gap-0")
                    _render_tree(value, prov, inner, diff_only)
        elif isinstance(value, list):
            with parent_element:
                with ui.expansion(key, icon="list").classes("w-full"):
                    inner = ui.column().classes("pl-4 w-full gap-0")
                    if isinstance(prov, list):
                        for entry in prov:
                            item_val = entry.get("value", "")
                            item_src = entry.get("source", "global")
                            if diff_only and item_src != "project":
                                continue
                            with inner:
                                with ui.row().classes("items-center gap-2"):
                                    ui.label(f"- {item_val}").classes(
                                        "text-sm font-mono"
                                    )
                                    ui.badge(
                                        _provenance_label(item_src),
                                        color=_provenance_color(item_src),
                                    ).props("dense").classes("text-xs")
                    else:
                        label = _provenance_label(prov or "global")
                        color = _provenance_color(prov or "global")
                        for item in value:
                            with inner:
                                with ui.row().classes("items-center gap-2"):
                                    ui.label(f"- {item}").classes("text-sm font-mono")
                                    ui.badge(label, color=color).props("dense").classes(
                                        "text-xs"
                                    )
        else:
            src = prov if isinstance(prov, str) else "global"
            if diff_only and src != "project":
                continue
            with parent_element:
                with ui.row().classes("items-center gap-2 py-0.5"):
                    ui.label(f"{key}:").classes("text-sm font-bold font-mono")
                    ui.label(str(value)).classes("text-sm font-mono")
                    ui.badge(
                        _provenance_label(src),
                        color=_provenance_color(src),
                    ).props("dense").classes("text-xs")


def _has_project_override(prov) -> bool:
    """Check if a provenance entry contains any project-level values."""
    if prov == "project":
        return True
    if isinstance(prov, dict):
        return any(_has_project_override(v) for v in prov.values())
    if isinstance(prov, list):
        return any(e.get("source") == "project" for e in prov if isinstance(e, dict))
    return False


def _shorten_path(path: str) -> str:
    """Shorten a path for display in the selector."""
    try:
        from ai_guardian.daemon.working_dir import shorten_path

        return shorten_path(path)
    except Exception:
        return path


def create_config_effective_page(service, daemon_name: str):
    """Create the Effective Config page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/config-effective")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Effective Configuration").classes("text-2xl font-bold")
        ui.label(
            "Merged configuration from all sources "
            "(global + project) with per-key provenance."
        ).classes("text-xs text-grey-6")

        from ai_guardian.web.config_helpers import _get_remote_project_dir

        with ui.row().classes("items-center gap-4"):
            view_toggle = ui.toggle(
                {False: "Show All", True: "Overrides Only"},
                value=False,
            ).props("dense")

            ui.button(icon="refresh", on_click=lambda: refresh()).props(
                "dense flat round"
            ).tooltip("Refresh")

        content = ui.column().classes("w-full gap-1")

        async def refresh():
            content.clear()
            selected_dir = _get_remote_project_dir()
            proj_dir = _resolve_project_root(selected_dir) if selected_dir else None

            merged, provenance, project_cfg, error = await run.io_bound(
                _load_effective_data, proj_dir
            )

            with content:
                if error:
                    with ui.card().classes("w-full"):
                        ui.label("Error").classes("text-lg font-bold text-red")
                        ui.label(error).classes("text-sm text-red")
                    return

                if not merged:
                    ui.label(
                        "No configuration found. Using built-in defaults."
                    ).classes("text-sm text-grey-6")
                    return

                diff_only = view_toggle.value

                if diff_only and not project_cfg:
                    ui.label(
                        "No project overrides — using global config only."
                    ).classes("text-sm text-grey-6")
                    return

                with ui.card().classes("w-full"):
                    tree_container = ui.column().classes("w-full gap-0")
                    _render_tree(merged, provenance or {}, tree_container, diff_only)

        view_toggle.on_value_change(lambda _: refresh())
        ui.timer(0.1, refresh, once=True)
