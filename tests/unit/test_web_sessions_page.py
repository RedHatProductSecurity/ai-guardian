"""Contracts for the unified web Sessions page."""

import inspect

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


def test_sessions_page_explains_cross_agent_correlation():
    """The page identifies the environment variable required by non-SDK agents."""
    from ai_guardian.web.pages.traces import create_traces_page

    source = inspect.getsource(create_traces_page)
    assert 'ui.label("Sessions")' in source
    assert "AI_GUARDIAN_RUN_ID" in source
    assert "SDK run_id" in source


def test_crashed_trace_is_displayed_as_interrupted():
    """The UI uses a neutral label while preserving the stored API value."""
    from ai_guardian.web.pages.traces import _display_stop_reason

    assert _display_stop_reason("crashed") == "interrupted"
    assert _display_stop_reason("error") == "error"


def test_session_timestamps_use_browser_local_time():
    """Session lists and details convert UTC timestamps in the browser."""
    from ai_guardian.web.pages.traces import (
        _render_run_group_card,
        _render_trace_card,
        _render_trace_list,
        create_trace_detail_page,
    )

    assert "local_time_label" in inspect.getsource(_render_run_group_card)
    assert "local_time_label" in inspect.getsource(_render_trace_card)
    assert "inject_local_time_js" in inspect.getsource(_render_trace_list)
    assert "local_time_label" in inspect.getsource(create_trace_detail_page)
    assert "inject_local_time_js" in inspect.getsource(create_trace_detail_page)


def test_tracing_settings_write_top_level_config():
    """The web UI must not write the deprecated SDK trace_viewer location."""
    from ai_guardian.web.pages.tracing_settings import create_tracing_settings_page

    source = inspect.getsource(create_tracing_settings_page)
    assert 'setdefault("tracing", {})' in source
    assert "trace_viewer" not in source
    assert "auto_refresh_interval_seconds" in source
    assert "trace_cache_retention_days" in source


def test_tracing_settings_number_labels_have_room_to_render():
    """Numeric settings stay wide enough to show their complete labels."""
    from ai_guardian.web.pages.tracing_settings import create_tracing_settings_page

    source = inspect.getsource(create_tracing_settings_page)
    assert source.count('.classes("w-full max-w-md")') == 2
