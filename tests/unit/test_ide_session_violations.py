"""Tests for violation links in IDE Session viewer (#2022)."""

import inspect

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


class TestLoadSessionViolationsExists:
    """Verify _load_session_violations helper exists and filters by session_id."""

    def test_function_exists(self):
        from ai_guardian.web.pages.ide_sessions import _load_session_violations

        assert callable(_load_session_violations)

    def test_filters_by_session_id(self):
        source = inspect.getsource(
            __import__(
                "ai_guardian.web.pages.ide_sessions",
                fromlist=["_load_session_violations"],
            )._load_session_violations
        )
        assert "session_id" in source


class TestRenderStepAcceptsViolations:
    """Verify _render_step accepts violations and daemon_name parameters."""

    def test_signature_has_violations_param(self):
        from ai_guardian.web.pages.ide_sessions import _render_step

        sig = inspect.signature(_render_step)
        assert "violations" in sig.parameters

    def test_signature_has_daemon_name_param(self):
        from ai_guardian.web.pages.ide_sessions import _render_step

        sig = inspect.signature(_render_step)
        assert "daemon_name" in sig.parameters

    def test_renders_violation_badge(self):
        from ai_guardian.web.pages.ide_sessions import _render_step

        source = inspect.getsource(_render_step)
        assert "render_violation_badge" in source

    def test_renders_violation_count_badge(self):
        from ai_guardian.web.pages.ide_sessions import _render_step

        source = inspect.getsource(_render_step)
        assert "violation" in source
        assert "ui.badge" in source


class TestDetailPageUsesMatchViolations:
    """Verify detail page correlates violations to steps."""

    def test_imports_match_violations_to_steps(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert "match_violations_to_steps" in source

    def test_passes_violations_to_render_step(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert "violations_by_step" in source

    def test_handles_reversed_sort_order(self):
        from ai_guardian.web.pages.ide_sessions import (
            create_ide_session_detail_page,
        )

        source = inspect.getsource(create_ide_session_detail_page)
        assert "reversed_map" in source


class TestTuiSessionViolations:
    """Verify TUI IDE sessions panel loads violations."""

    def test_load_violations_method_exists(self):
        from ai_guardian.tui.ide_sessions import IDESessionsContent

        assert hasattr(IDESessionsContent, "_load_session_violations")

    def test_render_violations_method_exists(self):
        from ai_guardian.tui.ide_sessions import IDESessionsContent

        assert hasattr(IDESessionsContent, "_render_detail_with_violations")

    def test_show_detail_calls_load_violations(self):
        from ai_guardian.tui.ide_sessions import IDESessionsContent

        source = inspect.getsource(IDESessionsContent._show_session_detail)
        assert "_load_session_violations" in source

    def test_render_violations_shows_count(self):
        from ai_guardian.tui.ide_sessions import IDESessionsContent

        source = inspect.getsource(IDESessionsContent._render_detail_with_violations)
        assert "Violations:" in source
        assert "bold red" in source
