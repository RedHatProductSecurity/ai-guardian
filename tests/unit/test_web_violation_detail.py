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

    def test_immutable_detail_gates_override_actions(self):
        import inspect

        from ai_guardian.web.pages.violation_detail import _render_violation_detail

        source = inspect.getsource(_render_violation_detail)
        assert "if immutable:" in source
        assert "if not immutable and vtype in _ALLOWLIST_TYPES" in source


class TestViolationModalOpenAsPage:
    """Verify the modal gains an 'Open as page' link."""

    def test_open_as_page_link_in_source(self):
        import inspect

        from ai_guardian.web.pages.violations import _render_violation_card

        source = inspect.getsource(_render_violation_card)
        assert "Open as page" in source
        assert "violation-detail" in source

    def test_violation_card_announces_resolution_guidance(self):
        import inspect

        from ai_guardian.web.pages.violations import _render_violation_card

        source = inspect.getsource(_render_violation_card)
        assert "Resolution guidance: open Details" in source

    def test_canary_has_no_suppression_action(self):
        from ai_guardian.web.pages.violations import _ALLOWLIST_TYPES

        assert "canary_detected" not in _ALLOWLIST_TYPES

    def test_immutable_markdown_omits_suggested_rule(self):
        from ai_guardian.web.pages.violations import _format_violation_markdown

        markdown = _format_violation_markdown(
            {
                "violation_type": "tool_permission",
                "blocked": {"is_immutable": True},
                "suggestion": {
                    "rule": {
                        "matcher": "Bash",
                        "mode": "allow",
                        "patterns": ["safe-command"],
                    }
                },
            }
        )

        assert "Suggested Rule" not in markdown
        assert "safe-command" not in markdown

    def test_immutable_card_gates_override_actions(self):
        import inspect

        from ai_guardian.web.pages.violations import _render_violation_card

        source = inspect.getsource(_render_violation_card)
        assert "not is_immutable_violation(violation)" in source
        assert "if immutable:" in source


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


def test_input_diagnostic_detail_renders_safe_fields_and_keeps_immutable_actions_hidden():
    from unittest.mock import patch

    from ai_guardian.web.pages.violation_detail import _render_violation_detail

    violation = {
        "id": "viol_2627abcd",
        "violation_type": "tool_permission",
        "blocked": {
            "tool_name": "Read",
            "is_immutable": True,
            "input_diagnostics": {
                "schema_version": 1,
                "subreason": "missing_argument",
                "native_tool_name": "read",
                "canonical_tool_name": "Read",
                "expected_field": "path",
                "argument_shape": {"limit": "integer"},
                "raw_payload": "PRIVATE_PAYLOAD",
            },
        },
        "context": {"message_id": "msg_2627test", "host_version": "2.0.24"},
    }
    with (
        patch("ai_guardian.web.pages.violation_detail.ui") as ui,
        patch("ai_guardian.web.pages.violation_detail.local_time_label"),
        patch("ai_guardian.web.pages.violations.ui", ui),
    ):
        _render_violation_detail(violation, None, "local")
    labels = [str(call.args[0]) for call in ui.label.call_args_list if call.args]
    assert "missing_argument" in labels
    assert "msg_2627test" in labels
    assert "2.0.24" in labels
    assert "unknown" in labels
    assert "PRIVATE_PAYLOAD" not in str(ui.mock_calls)
    buttons = [call.args[0] for call in ui.button.call_args_list if call.args]
    assert "Always Allow..." not in buttons
    assert "Suppress in Source..." not in buttons
    # View/copy projection must not mutate the persisted compatibility record.
    assert violation["blocked"]["input_diagnostics"]["raw_payload"] == "PRIVATE_PAYLOAD"
