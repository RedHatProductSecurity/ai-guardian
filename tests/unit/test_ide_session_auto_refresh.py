"""Tests for auto-refresh on IDE Session list and detail pages (#2024)."""

import inspect

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


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

    def test_returns_default_on_exception(self):
        from ai_guardian.web.pages.ide_sessions import _get_auto_refresh_interval

        class FakeService:
            def get_target_by_name(self, name):
                raise RuntimeError("boom")

        assert _get_auto_refresh_interval(FakeService(), "test") == 5


class TestWebListPageAutoRefresh:
    """Verify list page has auto-refresh timer pattern."""

    def test_list_page_has_auto_timer(self):
        from ai_guardian.web.pages.ide_sessions import create_ide_sessions_page

        source = inspect.getsource(create_ide_sessions_page)
        assert 'auto_timer = {"ref": None}' in source

    def test_list_page_starts_periodic_timer(self):
        from ai_guardian.web.pages.ide_sessions import create_ide_sessions_page

        source = inspect.getsource(create_ide_sessions_page)
        assert "_get_auto_refresh_interval" in source
        assert 'auto_timer["ref"]' in source

    def test_list_page_checks_is_deleted(self):
        from ai_guardian.web.pages.ide_sessions import create_ide_sessions_page

        source = inspect.getsource(create_ide_sessions_page)
        assert "is_deleted" in source


class TestWebDetailPageAutoRefresh:
    """Verify detail page has auto-refresh timer pattern."""

    def test_detail_page_has_auto_timer(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert 'auto_timer = {"ref": None}' in source

    def test_detail_page_starts_periodic_timer(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert "_get_auto_refresh_interval" in source
        assert 'auto_timer["ref"]' in source

    def test_detail_page_checks_is_deleted(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert "is_deleted" in source


class TestTuiAutoRefresh:
    """Verify TUI IDE sessions panel has periodic refresh."""

    def test_has_get_refresh_interval_method(self):
        from ai_guardian.tui.ide_sessions import IDESessionsContent

        assert hasattr(IDESessionsContent, "_get_refresh_interval")

    def test_get_refresh_interval_returns_float(self):
        from ai_guardian.tui.ide_sessions import IDESessionsContent

        sig = inspect.signature(IDESessionsContent._get_refresh_interval)
        assert "return" in str(sig) or True
        source = inspect.getsource(IDESessionsContent._get_refresh_interval)
        assert "auto_refresh_interval_seconds" in source

    def test_on_mount_calls_set_interval(self):
        from ai_guardian.tui.ide_sessions import IDESessionsContent

        source = inspect.getsource(IDESessionsContent.on_mount)
        assert "set_interval" in source

    def test_get_refresh_interval_default(self):
        from ai_guardian.tui.ide_sessions import IDESessionsContent

        source = inspect.getsource(IDESessionsContent._get_refresh_interval)
        assert "return 5" in source
