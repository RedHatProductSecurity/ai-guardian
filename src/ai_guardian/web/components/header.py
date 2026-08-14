"""Shared header and navigation components for the web console."""

from nicegui import ui

from ai_guardian import __version__

from ai_guardian.constants import SLUG_TO_CONFIG_SECTION

_show_disabled_scanners = True


def _is_feature_enabled(config, section_key):
    """Check if a feature/scanner is enabled in config."""
    section = config.get(section_key, {})
    if isinstance(section, dict):
        enabled = section.get("enabled", True)
        if isinstance(enabled, dict):
            return bool(enabled.get("value", True))
        return bool(enabled)
    return True


NAV_GROUPS = [
    (
        "Security Overview",
        [
            ("Security Dashboard", ""),
            ("Global Settings", "/settings"),
            ("Health Check", "/health-check"),
        ],
    ),
    (
        "Monitoring",
        [
            ("Violations", "/violations"),
            ("Violation Logging", "/violation-logging"),
            ("Metrics & Audit", "/metrics"),
            ("Performance", "/performance"),
            ("Logs", "/logs"),
        ],
    ),
    (
        "SDK",
        [
            ("Agent Profiles", "/sdk-agents"),
            ("SDK Settings", "/sdk-settings"),
            ("Trace Viewer", "/traces"),
            ("OTEL Export", "/otel-settings"),
        ],
    ),
    (
        "Permissions",
        [
            ("Permission Rules", "/permission-rules"),
            ("MCP Settings", "/mcp-servers"),
            ("Permissions Discovery", "/permissions-discovery"),
            ("Auto Directory Rules", "/auto-directory-rules"),
            ("Directory Rules", "/directory-rules"),
        ],
    ),
    (
        "Secrets",
        [
            ("Secret Scanning", "/secrets"),
            ("Engine Config", "/secret-engines"),
            ("Secret Redaction", "/secret-redaction"),
        ],
    ),
    (
        "Prompt Injection",
        [
            ("Detection", "/pi-detection"),
            ("ML Engines", "/pi-ml-engines"),
            ("Patterns", "/pi-patterns"),
            ("Jailbreak", "/pi-jailbreak"),
            ("Unicode Detection", "/pi-unicode"),
        ],
    ),
    (
        "Threat Detection",
        [
            ("SSRF Protection", "/ssrf"),
            ("Context Poisoning", "/context-poisoning"),
            ("Supply Chain", "/supply-chain"),
            ("Config Scanner", "/config-scanner"),
            ("PII Detection", "/scan-pii"),
            ("Code Security", "/code-security"),
            ("Offensive Language", "/offensive-language"),
            ("Canary Detection", "/canary-detection"),
            ("Exfil Detection", "/exfil-detection"),
            ("Annotations", "/annotations"),
        ],
    ),
    (
        "Configuration",
        [
            ("Security Instructions", "/security-instructions"),
            ("Daemon", "/daemon"),
            ("Config Cache", "/cache-status"),
            ("Remote Configs", "/remote-configs"),
            ("Config File", "/config-file"),
            ("Config Editor", "/config-editor"),
            ("Console Settings", "/console-settings"),
            ("Effective Config", "/config-effective"),
            ("About", "/about"),
        ],
    ),
    (
        "Tools",
        [
            ("Detection Patterns", "/detection-patterns"),
            ("Regex Tester", "/regex-tester"),
            ("Hook Simulator", "/hook-simulator"),
            ("Engine Tester", "/engine-tester"),
            ("Directory Scan", "/directory-scan"),
            ("Scan Configure", "/scan-configure"),
            ("MCP Security", "/mcp-security"),
        ],
    ),
]


def _build_search_index(prefix):
    """Build search index from nav groups and feature toggle metadata."""
    entries = []
    for group_name, items in NAV_GROUPS:
        for label, suffix in items:
            path = f"{prefix}{suffix}"
            search_text = f"{group_name} {label}".lower()
            entries.append((search_text, label, group_name, path))

    try:
        from ai_guardian.web.pages.global_settings import FEATURE_GROUPS

        settings_path = f"{prefix}/settings"
        for fg_group, features in FEATURE_GROUPS:
            for config_key, feat_label, feat_desc in features:
                search_text = (
                    f"{fg_group} {feat_label} {feat_desc} {config_key}"
                ).lower()
                feat_path = f"{settings_path}#feature-{config_key}"
                entries.append(
                    (search_text, feat_label, f"Settings › {fg_group}", feat_path)
                )
    except ImportError:
        pass  # intentionally silent — optional dependency

    return entries


def _init_scope_state():
    """Initialize scope session state if not set."""
    try:
        from nicegui import app

        if "config_scope" not in app.storage.user:
            app.storage.user["config_scope"] = "global"
        if "project_dir" not in app.storage.user:
            app.storage.user["project_dir"] = None
    except Exception:
        pass  # intentionally silent — optional dependency


def create_header(daemon_name: str = "", drawer=None):
    """Create the shared header bar showing current daemon and scope toggle.

    Args:
        daemon_name: Name of the active daemon (empty for picker page).
        drawer: Optional left_drawer instance — adds a hamburger toggle.
    """
    from ai_guardian.theme import apply_quasar_theme

    apply_quasar_theme()
    _init_scope_state()

    from ai_guardian.web.config_helpers import (
        set_current_daemon_name,
        set_current_project_dir,
    )

    set_current_daemon_name(daemon_name)

    try:
        from nicegui import app

        set_current_project_dir(app.storage.user.get("project_dir") or "")
    except Exception:
        set_current_project_dir("")

    with ui.header().classes("items-center justify-between bg-blue-grey-10"):
        with ui.row().classes("items-center gap-4"):
            if drawer is not None:
                ui.button(icon="menu", on_click=drawer.toggle).props(
                    "flat round color=white"
                )
            ui.image("/images/ai-guardian-320.png").classes("w-8 h-8")
            ui.link("AI Guardian", "/").classes(
                "text-xl font-bold text-white no-underline"
            )
            ui.label(f"v{__version__}").classes("text-grey-6 text-xs")
            if daemon_name:
                ui.label("|").classes("text-grey-6")
                ui.label(daemon_name).classes("text-white font-bold")
            _create_project_selector(daemon_name)
        with ui.row().classes("gap-2 items-center"):
            if daemon_name:
                _create_scanner_toggle()
                _create_nav_menu(daemon_name)
            else:
                ui.link("Select Daemon", "/").classes("text-white no-underline")


def create_sidebar(daemon_name: str, current: str = ""):
    """Create a slide-out navigation drawer for a specific daemon.

    Returns the ``ui.left_drawer`` instance so callers can pass it to
    ``create_header(drawer=...)`` for the hamburger toggle button.
    """
    prefix = f"/{daemon_name}"
    search_index = _build_search_index(prefix)

    try:
        from nicegui import app as _app

        initial_open = _app.storage.user.get("sidebar_open", False)
    except Exception:
        initial_open = False

    drawer = (
        ui.left_drawer(value=initial_open)
        .classes("bg-blue-grey-10 p-2 gap-2")
        .props("width=224 bordered")
    )

    def _persist_state(e):
        try:
            from nicegui import app as _app2

            _app2.storage.user["sidebar_open"] = e.value
        except Exception:
            pass

    drawer.on_value_change(_persist_state)

    with drawer:
        search_input = (
            ui.input(placeholder="Search settings...")
            .props("dense outlined clearable")
            .classes("w-full")
            .style("color: white; --q-color-primary: #78909c;")
        )

        nav_container = (
            ui.column()
            .classes("w-full gap-0 overflow-y-auto")
            .style("flex: 1; min-height: 0;")
        )
        active_link = None
        group_labels = []
        group_items = []
        with nav_container:
            for group_name, items in NAV_GROUPS:
                g_label = ui.label(group_name).classes(
                    "text-xs text-grey-6 font-bold uppercase mt-4 mb-1 px-2"
                )
                g_links = []
                for label, suffix in items:
                    path = f"{prefix}{suffix}"
                    classes = "w-full no-underline rounded px-2 py-1 text-sm "
                    if current == path:
                        classes += "bg-blue-grey-8 text-white font-bold"
                    else:
                        classes += "text-grey-4 hover:bg-blue-grey-9"
                    config_section = SLUG_TO_CONFIG_SECTION.get(suffix)
                    link = ui.link(label, path).classes(classes)
                    if config_section:
                        g_links.append((link, config_section))
                    else:
                        g_links.append(None)
                    if current == path:
                        active_link = link
                group_labels.append(g_label)
                group_items.append(g_links)

        async def _apply_scanner_filter():
            """Load config and hide disabled scanner nav items."""
            try:
                from nicegui import run

                from ai_guardian.web.config_helpers import load_web_config

                config = await run.io_bound(load_web_config)
            except Exception:
                return

            for g_label, g_links in zip(group_labels, group_items):
                visible_count = 0
                for entry in g_links:
                    if entry is None:
                        visible_count += 1
                        continue
                    link, config_section = entry
                    enabled = _is_feature_enabled(config, config_section)
                    if enabled or _show_disabled_scanners:
                        visible_count += 1
                    else:
                        link.set_visibility(False)
                g_label.set_visibility(visible_count > 0)

        ui.timer(0.1, _apply_scanner_filter, once=True)

        if active_link:
            ui.run_javascript("""
                setTimeout(() => {
                    const activeLink = document.querySelector('.bg-blue-grey-8');
                    if (activeLink) {
                        activeLink.scrollIntoView({
                            behavior: 'smooth',
                            block: 'center'
                        });
                    }
                }, 100);
            """)

        results_container = (
            ui.column()
            .classes("w-full gap-0 overflow-y-auto")
            .style("flex: 1; min-height: 0;")
        )
        results_container.set_visibility(False)

        result_elements = []
        with results_container:
            no_results_label = ui.label("No matching settings").classes(
                "text-xs text-grey-6 px-2 mt-4"
            )
            for search_text, label, group_name, path in search_index:
                with ui.column().classes(
                    "w-full gap-0 px-1 py-1 rounded hover:bg-blue-grey-9"
                ) as row:
                    ui.label(group_name).classes("text-xs text-grey-7")
                    link_classes = "w-full no-underline text-sm "
                    if current == path:
                        link_classes += "text-white font-bold active-search-result"
                    else:
                        link_classes += "text-grey-4"
                    ui.link(label, path).classes(link_classes)
                result_elements.append((search_text, row))

        def on_search(e):
            query = (e.value or "").strip().lower()
            if not query:
                nav_container.set_visibility(True)
                results_container.set_visibility(False)
                if active_link:
                    ui.run_javascript("""
                        setTimeout(() => {
                            const activeLink = document.querySelector('.bg-blue-grey-8');
                            if (activeLink) {
                                activeLink.scrollIntoView({
                                    behavior: 'smooth',
                                    block: 'center'
                                });
                            }
                        }, 100);
                    """)
                return

            nav_container.set_visibility(False)
            results_container.set_visibility(True)

            any_visible = False
            for search_text, row in result_elements:
                match = query in search_text
                row.set_visibility(match)
                if match:
                    any_visible = True

            no_results_label.set_visibility(not any_visible)

            ui.run_javascript("""
                setTimeout(() => {
                    const activeResult = document.querySelector('.active-search-result');
                    if (activeResult && activeResult.closest('[style*="display: none"]') === null) {
                        activeResult.scrollIntoView({
                            behavior: 'smooth',
                            block: 'center'
                        });
                    }
                }, 100);
            """)

        search_input.on_value_change(on_search)

    return drawer


def _create_nav_menu(daemon_name: str):
    """Create the header navigation dropdown menu."""
    prefix = f"/{daemon_name}"

    with ui.button("Quick Links", icon="link").props("flat color=white"):
        with ui.menu().classes("bg-blue-grey-9"):
            ui.menu_item(
                "Dashboard",
                on_click=lambda: ui.navigate.to(prefix),
            )
            ui.menu_item(
                "Violations",
                on_click=lambda: ui.navigate.to(f"{prefix}/violations"),
            )
            ui.menu_item(
                "Logs",
                on_click=lambda: ui.navigate.to(f"{prefix}/logs"),
            )
            ui.menu_item(
                "Health Check",
                on_click=lambda: ui.navigate.to(f"{prefix}/health-check"),
            )
            ui.separator()
            with ui.item().classes("cursor-pointer"):
                with ui.item_section():
                    ui.item_label("Settings")
                with ui.item_section().props("side"):
                    ui.icon("chevron_right").classes("text-grey-4")
                with (
                    ui.menu()
                    .props("anchor='top end' self='top start'")
                    .classes("bg-blue-grey-9")
                ):
                    ui.menu_item(
                        "Global Settings",
                        on_click=lambda: ui.navigate.to(f"{prefix}/settings"),
                    )
                    ui.menu_item(
                        "Config Editor",
                        on_click=lambda: ui.navigate.to(f"{prefix}/config-editor"),
                    )
                    ui.menu_item(
                        "Console Settings",
                        on_click=lambda: ui.navigate.to(f"{prefix}/console-settings"),
                    )
            ui.menu_item(
                "Metrics",
                on_click=lambda: ui.navigate.to(f"{prefix}/metrics"),
            )
            ui.separator()
            ui.menu_item(
                "About",
                on_click=lambda: ui.navigate.to(f"{prefix}/about"),
            )


def _create_scope_toggle():
    """Create the Global/Project scope toggle in the header."""
    try:
        from nicegui import app

        current = app.storage.user.get("config_scope", "global")
    except Exception:
        current = "global"

    with ui.row().classes("items-center gap-1 ml-4"):
        ui.label("|").classes("text-grey-6")
        ui.label("Scope:").classes("text-grey-4 text-xs")

        scope_toggle = (
            ui.toggle(
                {
                    "global": "Global",
                    "project": "Project",
                },
                value=current,
            )
            .props(
                "dense size=sm color=blue-grey-6 text-color=white toggle-color=blue-6"
            )
            .classes("text-xs")
        )

        async def on_scope_change(e):
            try:
                from nicegui import app as _app

                _app.storage.user["config_scope"] = e.value
                await ui.run_javascript("location.reload()")
            except Exception:
                pass  # intentionally silent — optional dependency

        scope_toggle.on_value_change(on_scope_change)


def _create_project_selector(daemon_name: str):
    """Create a project directory selector for daemon config pages.

    Shows for all daemons (local and remote). Populates from the daemon's
    tracked project directories (active_project_dirs from /api/stats).
    Stores selection in session state and reloads the page on change.
    """
    if not daemon_name:
        return

    try:
        from nicegui import app, run

        current = app.storage.user.get("project_dir") or ""
    except Exception:
        return

    from ai_guardian.web.config_helpers import (
        load_web_projects,
        set_current_project_dir,
    )

    with ui.row().classes("items-center gap-1 ml-2"):
        ui.label("|").classes("text-grey-6")
        ui.label("Project:").classes("text-grey-4 text-xs")

        initial_options = {"": "Global only"}
        if current:
            initial_options[current] = _shorten_project_path(current)

        project_select = (
            ui.select(
                initial_options,
                value=current,
                label=None,
            )
            .props(
                "dense outlined dark options-dense"
                " popup-content-class='bg-blue-grey-9'"
            )
            .classes("min-w-[200px] text-xs")
        )

        async def _populate():
            dirs = await run.io_bound(load_web_projects)
            options = {"": "Global only"}
            for d in dirs:
                options[d] = _shorten_project_path(d)
            project_select.options = options
            project_select.update()
            if current and current not in options:
                project_select.value = ""

        async def on_project_change(e):
            try:
                from nicegui import app as _app

                val = e.value or ""
                _app.storage.user["project_dir"] = val
                set_current_project_dir(val)
                await ui.run_javascript("location.reload()")
            except Exception:
                pass

        project_select.on_value_change(on_project_change)
        ui.timer(0.1, _populate, once=True)


def _create_scanner_toggle():
    """Create the show/hide disabled scanners toggle in the header."""
    global _show_disabled_scanners

    with ui.row().classes("items-center gap-1"):
        ui.label("|").classes("text-grey-6")
        switch = (
            ui.switch("Show disabled", value=_show_disabled_scanners)
            .props("dense dark color=blue-grey-6")
            .classes("text-xs text-grey-4")
        )

        async def on_toggle(e):
            global _show_disabled_scanners
            _show_disabled_scanners = e.value
            await ui.run_javascript("location.reload()")

        switch.on_value_change(on_toggle)


def _shorten_project_path(path: str) -> str:
    """Shorten a project path for display in the selector."""
    try:
        from ai_guardian.daemon.working_dir import shorten_path

        return shorten_path(path)
    except Exception:
        return path
