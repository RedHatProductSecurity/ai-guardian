"""Tests for the violation detail page and updated violation links."""

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.pages.violation_detail import _find_violation_by_id


class TestFindViolationById:
    """Tests for _find_violation_by_id helper."""

    def test_finds_matching_violation(self):
        violations = [
            {"id": "viol_aaa11111", "violation_type": "secret_detected"},
            {"id": "viol_bbb22222", "violation_type": "prompt_injection"},
        ]
        result = _find_violation_by_id(violations, "viol_bbb22222")
        assert result is not None
        assert result["violation_type"] == "prompt_injection"

    def test_returns_none_when_not_found(self):
        violations = [
            {"id": "viol_aaa11111", "violation_type": "secret_detected"},
        ]
        result = _find_violation_by_id(violations, "viol_missing")
        assert result is None

    def test_returns_none_for_empty_list(self):
        assert _find_violation_by_id([], "viol_aaa11111") is None

    def test_skips_violations_without_id(self):
        violations = [
            {"violation_type": "secret_detected"},
            {"id": "viol_bbb22222", "violation_type": "prompt_injection"},
        ]
        result = _find_violation_by_id(violations, "viol_bbb22222")
        assert result is not None
        assert result["violation_type"] == "prompt_injection"

    def test_returns_first_match_on_duplicate_ids(self):
        violations = [
            {"id": "viol_dup00001", "violation_type": "first"},
            {"id": "viol_dup00001", "violation_type": "second"},
        ]
        result = _find_violation_by_id(violations, "viol_dup00001")
        assert result["violation_type"] == "first"


class TestViolationDetailPageImports:
    """Verify violation detail page module can be imported."""

    def test_create_function_exists(self):
        from ai_guardian.web.pages.violation_detail import (
            create_violation_detail_page,
        )

        assert callable(create_violation_detail_page)

    def test_render_function_exists(self):
        from ai_guardian.web.pages.violation_detail import _render_violation_detail

        assert callable(_render_violation_detail)


class TestViolationDetailRoute:
    """Verify violation-detail route is registered in WebConsole."""

    def test_route_registered_in_app(self):
        import inspect

        from ai_guardian.web.app import WebConsole

        source = inspect.getsource(WebConsole._register_pages)
        assert "violation-detail" in source
        assert "create_violation_detail_page" in source


class TestViolationModalOpenAsPage:
    """Verify the modal gains an 'Open as page' link."""

    def test_open_as_page_link_in_source(self):
        import inspect

        from ai_guardian.web.pages.violations import _render_violation_card

        source = inspect.getsource(_render_violation_card)
        assert "Open as page" in source
        assert "violation-detail" in source


class TestViolationBadgeDeepLink:
    """Verify render_violation_badge links to detail page when ID present."""

    def test_badge_source_has_detail_link(self):
        import inspect

        from ai_guardian.web.components.step_render import render_violation_badge

        source = inspect.getsource(render_violation_badge)
        assert "violation-detail" in source
        assert "View detail" in source

    def test_badge_source_has_fallback_link(self):
        import inspect

        from ai_guardian.web.components.step_render import render_violation_badge

        source = inspect.getsource(render_violation_badge)
        assert "View all" in source


class TestViolationSummaryDeepLinks:
    """Verify render_violation_summary links individual violations by ID."""

    def test_summary_source_has_detail_links(self):
        import inspect

        from ai_guardian.web.components.step_render import render_violation_summary

        source = inspect.getsource(render_violation_summary)
        assert "violation-detail" in source

    def test_summary_source_keeps_view_all(self):
        import inspect

        from ai_guardian.web.components.step_render import render_violation_summary

        source = inspect.getsource(render_violation_summary)
        assert "View all" in source
