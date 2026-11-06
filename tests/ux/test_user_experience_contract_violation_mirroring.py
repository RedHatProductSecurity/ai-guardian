"""UX contract for opt-in remote violation history mirroring (#2633).

Scenario:
1. A user explicitly enables remote mirroring in Violation Logging settings.
2. The tray imports curated summaries from reachable remote daemons.
3. Local history identifies the remote source and links back when its record is
   addressable, while keeping the mirrored copy read-only.

Expected experience:
- The setting is off in fresh configs and profiles.
- No violation content, context, or suggestion is copied into the local mirror.
- The Console labels mirrored records read-only and never offers source mutation.
- A source link is offered only while the source daemon is available and the
  record has a source ID.

Manual verification:
1. Enable "Mirror remote violations" on the receiving daemon only.
2. Generate a remote violation, then refresh the receiving daemon's Violations page.
3. Confirm source attribution and the source-record link; stop the source daemon
   and confirm the mirrored copy remains visible without a source link.
4. Type a partial source name in "Filter by daemon" and confirm matching is
   case-insensitive and composes with the type and directory filters.
5. Clear the daemon search and confirm All Sources returns without changing the
   type or directory filters. Choose an exact source and confirm same-named sources
   remain distinguishable.
6. Refresh and confirm each source shows Running, Paused, Offline, or Unknown based
   on current discovery/status; an undiscoverable historical source is Unknown.
   Confirm availability refresh does not clear the selected filters.
7. Confirm Always Allow, Ignore File, and Suppress in Source are absent for the
   mirrored record, and that disabling the setting stops further imports.
"""

import inspect

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.daemon.violation_mirroring import is_remote_mirroring_enabled
from ai_guardian.web.components import violation_mirror
from ai_guardian.web.pages import violation_detail, violations


def test_fresh_configuration_is_opt_in():
    """USER EXPERIENCE: a fresh installation never imports remote history."""
    assert is_remote_mirroring_enabled({"violation_logging": {}}) is False
    assert (
        is_remote_mirroring_enabled(
            {"violation_logging": {"mirror_remote_violations": False}}
        )
        is False
    )
    assert (
        is_remote_mirroring_enabled(
            {"violation_logging": {"mirror_remote_violations": True}}
        )
        is True
    )


def test_console_exposes_read_only_attribution_and_conditional_source_link():
    """USER EXPERIENCE: mirrors are attributed and have no local mutation path."""
    attribution_source = inspect.getsource(violation_mirror.render_mirror_attribution)
    list_source = inspect.getsource(violations._render_violation_card)
    detail_source = inspect.getsource(violation_detail._render_violation_detail)
    settings_source = inspect.getsource(violations._show_allow_always_flow)

    assert "REMOTE · READ ONLY" in attribution_source
    assert "Open source record ↗" in attribution_source
    link_source = inspect.getsource(violation_mirror.mirror_source_link)
    assert 'target.status not in ("running", "paused")' in link_source
    assert "len(matches) != 1" in link_source
    assert "not mirrored" in list_source
    assert "not mirrored" in detail_source
    assert "is_mirrored_violation(violation)" in settings_source
    assert "Always Allow..." in list_source
    assert "Ignore File..." in list_source
    assert "Suppress in Source..." in list_source


def test_violation_page_supports_typed_search_and_exact_source_selection():
    """USER EXPERIENCE: typed search and exact selection filter distinct sources."""
    page_source = inspect.getsource(violations.create_violations_page)
    identity_source = inspect.getsource(violations._violation_source_identity)
    filter_source = inspect.getsource(violations._violation_matches_source_filter)

    assert 'label="Filter by daemon"' in page_source
    assert 'label="Select exact source"' in page_source
    assert "ui.input(" in page_source
    assert "on_value_change(on_source_query_change)" in page_source
    assert 'active_source_query["query"]' in page_source
    assert "with_input=True" in page_source
    assert '.props("clearable")' in page_source
    assert "active_source_filter" in page_source
    assert "selected_source=source_filter" in page_source
    assert 'v.get("violation_type") == vtype' in page_source
    assert "_violation_matches_dir(v, dir_filter)" in page_source
    assert "casefold()" in filter_source
    assert 'source_key = mirror.get("source_key")' in identity_source
    assert "identity[:8]" in identity_source
    assert "_sort_violation_sources" in page_source


def test_source_availability_is_refreshed_and_unknown_stays_distinct():
    """USER EXPERIENCE: options show refreshed status without guessing offline."""
    page_source = inspect.getsource(violations.create_violations_page)
    availability_source = inspect.getsource(violations._daemon_source_availability)
    mapping_source = inspect.getsource(violations._source_availability_by_identity)

    assert "service.refresh_targets" in page_source
    assert "service.get_all_daemon_status" in page_source
    assert 'source_availability.get(key, "Unknown")' in page_source
    assert '"Running"' in availability_source
    assert '"Paused"' in availability_source
    assert '"Offline"' in availability_source
    assert '"Unknown"' in availability_source
    assert "_source_key(target)" in mapping_source
    assert 'source_select.value = selected_source or ""' in page_source
    assert 'active_source_filter["source"] not in source_counts' not in page_source
    assert 'active_source_filter["source"] = None' in page_source
    assert "if not query:" in page_source


def test_console_setting_explains_summary_only_copying_and_opt_in():
    """USER EXPERIENCE: users can opt in with an explicit privacy explanation."""
    from ai_guardian.web.pages import violation_logging

    source = inspect.getsource(violation_logging.create_violation_logging_page)
    save_source = inspect.getsource(violation_logging._save_remote_mirroring_config)
    assert "Mirror remote violations" in source
    assert "Raw blocked content" in source
    assert "read-only" in source
    assert 'global_vlog.get("mirror_remote_violations") is True' in source
    assert "load_web_config_global()" in save_source
    assert 'scope="global"' in save_source
