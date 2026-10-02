"""Tests for auto-refresh on IDE Session list and detail pages (#2024, #2119)."""

import inspect

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


class TestSessionDetailHeader:
    def test_includes_known_model(self):
        from ai_guardian.web.pages.ide_sessions import _format_session_header

        assert _format_session_header("Fix session title", "gpt-5") == (
            "Fix session title (gpt-5)"
        )

    def test_omits_parentheses_for_unknown_model(self):
        from ai_guardian.web.pages.ide_sessions import _format_session_header

        assert _format_session_header("Fix session title", "") == "Fix session title"

    def test_untitled_session_has_no_empty_parentheses(self):
        from ai_guardian.web.pages.ide_sessions import _format_session_header

        assert _format_session_header("", "") == "Untitled"


class TestWebAutoRefreshInterval:
    """Verify _get_auto_refresh_interval helper exists and works."""

    def test_function_exists(self):
        from ai_guardian.web.pages.ide_sessions import _get_auto_refresh_interval

        assert callable(_get_auto_refresh_interval)

    def test_returns_default_on_no_target(self):
        from ai_guardian.web.pages.ide_sessions import _get_auto_refresh_interval

        class FakeService:
            def get_target_by_name(self, name):
                return None

        assert _get_auto_refresh_interval(FakeService(), "test") == 5

    def test_returns_config_value(self):
        from ai_guardian.web.pages.ide_sessions import _get_auto_refresh_interval

        class FakeService:
            def get_target_by_name(self, name):
                return "target"

            def get_daemon_config(self, target):
                return {"sdk": {"trace_viewer": {"auto_refresh_interval_seconds": 10}}}

        assert _get_auto_refresh_interval(FakeService(), "test") == 10

    def test_top_level_config_overrides_legacy_value(self):
        from ai_guardian.web.pages.ide_sessions import _get_auto_refresh_interval

        class FakeService:
            def get_target_by_name(self, name):
                return "target"

            def get_daemon_config(self, target):
                return {
                    "tracing": {"auto_refresh_interval_seconds": 20},
                    "sdk": {"trace_viewer": {"auto_refresh_interval_seconds": 10}},
                }

        assert _get_auto_refresh_interval(FakeService(), "test") == 20

    def test_returns_default_on_exception(self):
        from ai_guardian.web.pages.ide_sessions import _get_auto_refresh_interval

        class FakeService:
            def get_target_by_name(self, name):
                raise RuntimeError("boom")

        assert _get_auto_refresh_interval(FakeService(), "test") == 5


class TestWebListPageAutoRefresh:
    """Verify list page has auto-refresh timer with pause support."""

    def test_list_page_has_auto_timer(self):
        from ai_guardian.web.pages.ide_sessions import create_ide_sessions_page

        source = inspect.getsource(create_ide_sessions_page)
        assert '"ref": None' in source
        assert '"paused": False' in source

    def test_list_page_starts_periodic_timer(self):
        from ai_guardian.web.pages.ide_sessions import create_ide_sessions_page

        source = inspect.getsource(create_ide_sessions_page)
        assert "_get_auto_refresh_interval" in source
        assert 'auto_timer["ref"]' in source

    def test_list_page_checks_client_lifecycle(self):
        from ai_guardian.web.pages.ide_sessions import create_ide_sessions_page

        source = inspect.getsource(create_ide_sessions_page)
        assert "is_client_deleted" in source

    def test_list_page_has_pause_toggle(self):
        from ai_guardian.web.pages.ide_sessions import create_ide_sessions_page

        source = inspect.getsource(create_ide_sessions_page)
        assert "create_pause_toggle" in source

    def test_list_page_respects_paused_state(self):
        from ai_guardian.web.pages.ide_sessions import create_ide_sessions_page

        source = inspect.getsource(create_ide_sessions_page)
        assert 'auto_timer.get("paused")' in source

    def test_list_controls_do_not_overlap_global_header(self):
        from ai_guardian.web.pages.ide_sessions import create_ide_sessions_page

        source = inspect.getsource(create_ide_sessions_page)
        assert "position: sticky" not in source

    def test_list_page_has_day_navigation(self):
        from ai_guardian.web.pages.ide_sessions import create_ide_sessions_page

        source = inspect.getsource(create_ide_sessions_page)
        assert '"day": date.today()' in source
        assert "_previous_day" in source
        assert "_next_day" in source
        assert "_format_day_label" in source


class TestWebDetailPageAutoRefresh:
    """Verify detail page has auto-refresh timer with pause support."""

    def test_detail_page_has_auto_timer(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert '"ref": None' in source
        assert '"paused": False' in source

    def test_detail_page_starts_periodic_timer(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert "_get_auto_refresh_interval" in source
        assert 'auto_timer["ref"]' in source

    def test_detail_page_checks_client_lifecycle(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert "is_client_deleted" in source

    def test_detail_page_has_pause_toggle(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert "create_pause_toggle" in source

    def test_detail_page_respects_paused_state(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert 'auto_timer.get("paused")' in source

    def test_detail_controls_do_not_overlap_global_header(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert "position: sticky" not in source

    def test_detail_page_renders_bounded_conversation_pages(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert "read_session_detail_page" in source
        assert '"page_size": 50' in source
        assert "Page {detail_state['page']} of {total_pages}" in source

    def test_detail_refresh_skips_unchanged_session_files(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert "_session_file_signature" in source
        assert 'detail_state["file_signature"]' in source
        assert 'detail_state["loaded"]' in source


class TestWebTracesPageAutoRefresh:
    """Verify traces pages have pause support (#2119)."""

    def test_traces_list_has_pause_toggle(self):
        from ai_guardian.web.pages.traces import create_traces_page

        source = inspect.getsource(create_traces_page)
        assert "create_pause_toggle" in source
        assert '"paused": False' in source

    def test_traces_detail_has_pause_toggle(self):
        from ai_guardian.web.pages.traces import create_trace_detail_page

        source = inspect.getsource(create_trace_detail_page)
        assert "create_pause_toggle" in source
        assert '"paused": False' in source


class TestPauseToggleHelper:
    """Verify create_pause_toggle exists in step_render."""

    def test_function_exists(self):
        from ai_guardian.web.components.step_render import create_pause_toggle

        assert callable(create_pause_toggle)

    def test_function_signature(self):
        from ai_guardian.web.components.step_render import create_pause_toggle

        sig = inspect.signature(create_pause_toggle)
        params = list(sig.parameters.keys())
        assert "auto_timer" in params


class TestContentViewerCopyButton:
    """Verify content viewer dialog has copy button (#2119)."""

    def test_show_content_viewer_has_copy(self):
        from ai_guardian.web.components.content_viewer import show_content_viewer

        source = inspect.getsource(show_content_viewer)
        assert "content_copy" in source
        assert "navigator.clipboard.writeText" in source
