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
4. Use "Filter by daemon" to isolate the remote source; confirm same-named sources
   remain distinguishable.
5. Confirm Always Allow, Ignore File, and Suppress in Source are absent for the
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


def test_violation_page_filters_sources_without_collapsing_same_names():
    """USER EXPERIENCE: the source filter distinguishes remote daemon identities."""
    page_source = inspect.getsource(violations.create_violations_page)
    identity_source = inspect.getsource(violations._violation_source_identity)

    assert 'label="Filter by daemon"' in page_source
    assert "with_input=True" in page_source
    assert "active_source_filter" in page_source
    assert "source_filter" in page_source
    assert 'source_key = mirror.get("source_key")' in identity_source
    assert "identity[:8]" in identity_source
    assert "_sort_violation_sources" in page_source


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
