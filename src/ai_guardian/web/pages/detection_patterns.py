"""Detection Patterns page — read-only view of all detection rules."""

import logging
from collections import Counter

from nicegui import run, ui

from ai_guardian.patterns.lister import DetectionRule
from ai_guardian.patterns.lister import test_rule_matches as _test_rule_matches
from ai_guardian.web.components.header import create_header, create_sidebar

_logger = logging.getLogger(__name__)


def _load_rules():
    from ai_guardian.patterns.lister import PatternLister

    return PatternLister().get_all_rules()


def _refresh_pattern_server_cache():
    """Trigger a pattern server cache refresh (network call).

    Routes through DaemonService for both local and remote targets.
    """
    from ai_guardian.web.config_helpers import (
        _get_current_target,
        _daemon_service,
    )

    target = _get_current_target()
    if target is not None and _daemon_service is not None:
        result = _daemon_service.refresh_pattern_cache(target)
        if result is None:
            return "Pattern cache refresh failed"
        return result.get("result", "done")

    from ai_guardian.daemon.multi_client import MultiDaemonClient

    result = MultiDaemonClient._local_refresh_pattern_cache()
    return result.get("result", "done")


def _truncate(text, maxlen=80):
    if len(text) <= maxlen:
        return text
    return text[: maxlen - 3] + "..."


def create_detection_patterns_page(service, daemon_name: str):
    """Create the Detection Patterns page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/detection-patterns")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Detection Patterns").classes("text-2xl font-bold")
        ui.label(
            "Read-only view of all detection rules across TOML files "
            "and hardcoded self-protection patterns."
        ).classes("text-xs text-grey-6")

        filter_state = {
            "category": "all",
            "source": "all",
            "search": "",
            "mode": "search",
        }

        with ui.row().classes("items-center gap-4 w-full"):
            cat_select = (
                ui.select(
                    options={"all": "All Categories"},
                    value="all",
                    label="Category",
                )
                .props("dense outlined")
                .classes("w-48")
            )

            src_select = (
                ui.select(
                    options={"all": "All Sources"},
                    value="all",
                    label="Source",
                )
                .props("dense outlined")
                .classes("w-48")
            )

            mode_toggle = ui.toggle(
                {
                    "search": "Search Rules",
                    "test": "Test Match",
                },
                value="search",
            ).props("dense no-caps")

            search_input = (
                ui.input(placeholder="Search by ID, description, or pattern...")
                .props("dense outlined clearable")
                .classes("flex-grow")
            )

            refresh_status = ui.label("").classes("text-xs text-grey-6")

            async def _on_refresh():
                refresh_status.text = "Refreshing..."
                result = await run.io_bound(_refresh_pattern_server_cache)
                refresh_status.text = result
                await refresh()

            ui.button(
                "Refresh Patterns",
                on_click=_on_refresh,
                icon="refresh",
            ).props(
                "dense flat no-caps"
            ).classes("ml-2")

        mode_hint = ui.label("").classes("text-xs text-grey-6 -mt-2")

        content = ui.column().classes("w-full gap-4")

        def _update_mode_hint():
            if filter_state["mode"] == "test":
                mode_hint.text = (
                    "Test Match mode: enter sample text to see which "
                    "regex/literal rules would detect it "
                    "(only regex and literal match types are testable)"
                )
                search_input.props(
                    remove="placeholder",
                    add='placeholder="Enter text to test against patterns..."',
                )
            else:
                mode_hint.text = ""
                search_input.props(
                    remove="placeholder",
                    add='placeholder="Search by ID, description, or pattern..."',
                )

        async def refresh():
            all_rules = await run.io_bound(_load_rules)

            counts = Counter(r.category for r in all_rules)
            categories = sorted(counts.keys())

            cat_opts = {"all": f"All Categories ({len(all_rules)})"}
            for c in categories:
                cat_opts[c] = f"{c} ({counts[c]})"
            cat_select.options = cat_opts
            cat_select.update()

            src_counts = Counter(r.source for r in all_rules)
            src_opts = {"all": f"All Sources ({len(all_rules)})"}
            for s in sorted(src_counts.keys()):
                src_opts[s] = f"{s} ({src_counts[s]})"
            src_select.options = src_opts
            src_select.update()

            _render_table(all_rules)

        def _apply_filters(rules):
            filtered = rules
            cat = filter_state["category"]
            if cat != "all":
                filtered = [r for r in filtered if r.category == cat]
            src = filter_state["source"]
            if src != "all":
                filtered = [r for r in filtered if r.source == src]
            q = filter_state["search"].strip()
            if q:
                if filter_state["mode"] == "test":
                    filtered = [r for r in filtered if _test_rule_matches(r, q)]
                else:
                    ql = q.lower()
                    filtered = [
                        r
                        for r in filtered
                        if ql in r.id.lower()
                        or ql in r.description.lower()
                        or ql in r.pattern.lower()
                        or ql in r.category.lower()
                        or ql in r.group.lower()
                    ]
            return filtered

        all_rules_cache: list[DetectionRule] = []

        def _render_table(all_rules):
            all_rules_cache.clear()
            all_rules_cache.extend(all_rules)
            _do_render()

        def _do_render():
            filtered = _apply_filters(all_rules_cache)
            is_test = filter_state["mode"] == "test"
            q = filter_state["search"].strip()
            content.clear()
            with content:
                if is_test and q:
                    ui.label(f"{len(filtered)} rule(s) match your test text").classes(
                        "text-sm font-bold text-orange"
                    )
                else:
                    ui.label(
                        f"Showing {len(filtered)} of " f"{len(all_rules_cache)} rules"
                    ).classes("text-sm text-grey-6")

                columns = [
                    {
                        "name": "id",
                        "label": "ID",
                        "field": "id",
                        "sortable": True,
                        "align": "left",
                    },
                    {
                        "name": "category",
                        "label": "Category",
                        "field": "category",
                        "sortable": True,
                        "align": "left",
                    },
                    {
                        "name": "group",
                        "label": "Group",
                        "field": "group",
                        "sortable": True,
                        "align": "left",
                    },
                    {
                        "name": "match_type",
                        "label": "Type",
                        "field": "match_type",
                        "sortable": True,
                        "align": "left",
                    },
                    {
                        "name": "pattern",
                        "label": "Pattern",
                        "field": "pattern",
                        "align": "left",
                    },
                    {
                        "name": "description",
                        "label": "Description",
                        "field": "description",
                        "align": "left",
                    },
                    {
                        "name": "source",
                        "label": "Source",
                        "field": "source",
                        "sortable": True,
                        "align": "left",
                    },
                    {
                        "name": "severity",
                        "label": "Severity",
                        "field": "severity",
                        "sortable": True,
                        "align": "left",
                    },
                ]

                rows = []
                for r in filtered:
                    rows.append(
                        {
                            "id": r.id,
                            "category": r.category,
                            "group": r.group,
                            "match_type": r.match_type,
                            "pattern": _truncate(r.pattern),
                            "full_pattern": r.pattern,
                            "description": r.description,
                            "source": r.source,
                            "severity": r.severity,
                        }
                    )

                table = (
                    ui.table(
                        columns=columns,
                        rows=rows,
                        row_key="id",
                        pagination={"rowsPerPage": 50, "sortBy": "category"},
                    )
                    .classes("w-full")
                    .props("dense flat bordered wrap-cells")
                )

                table.add_slot(
                    "body-cell-pattern",
                    r"""
                    <q-td :props="props">
                        <q-tooltip>{{ props.row.full_pattern }}</q-tooltip>
                        <span style="font-family: monospace; font-size: 0.8em;">
                            {{ props.value }}
                        </span>
                    </q-td>
                """,
                )

                table.add_slot(
                    "body-cell-severity",
                    r"""
                    <q-td :props="props">
                        <q-badge v-if="props.value === 'immutable'"
                                 color="red" :label="props.value" />
                        <q-badge v-else-if="props.value === 'overridable'"
                                 color="blue" :label="props.value" />
                        <span v-else class="text-grey-6">
                            {{ props.value || '—' }}
                        </span>
                    </q-td>
                """,
                )

                table.add_slot(
                    "body-cell-source",
                    r"""
                    <q-td :props="props">
                        <q-badge v-if="props.value === 'hardcoded'"
                                 color="amber" text-color="black"
                                 :label="props.value" />
                        <q-badge v-else-if="props.value.startsWith('server:')"
                                 color="green"
                                 :label="props.value" />
                        <q-badge v-else color="teal"
                                 :label="props.value" />
                    </q-td>
                """,
                )

                ui.label(
                    "User-configurable patterns (allowlists, custom patterns) "
                    "can be edited on their respective pages."
                ).classes("text-xs text-grey-6 mt-2")

        def on_filter_change():
            filter_state["category"] = cat_select.value
            filter_state["source"] = src_select.value
            filter_state["search"] = search_input.value or ""
            _do_render()

        def on_mode_change(e):
            filter_state["mode"] = e.value
            _update_mode_hint()
            _do_render()

        cat_select.on_value_change(lambda _: on_filter_change())
        src_select.on_value_change(lambda _: on_filter_change())
        search_input.on_value_change(lambda _: on_filter_change())
        mode_toggle.on_value_change(on_mode_change)

        ui.timer(0.1, refresh, once=True)
