"""Tests for violation badges next to Steps header in trace viewer (#2021)."""

import inspect

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.pages.traces import _collect_turn_violations


class TestCollectTurnViolations:
    """Tests for _collect_turn_violations helper."""

    def test_empty_steps(self):
        assert _collect_turn_violations([]) == []

    def test_no_scan_steps(self):
        steps = [
            {"type": "input", "step": 0},
            {"type": "response", "step": 1},
        ]
        assert _collect_turn_violations(steps) == []

    def test_scan_step_without_violations(self):
        steps = [
            {"type": "scan", "step": 2, "scanned": "agent_response", "violations": []},
        ]
        assert _collect_turn_violations(steps) == []

    def test_single_violation(self):
        violation = {"type": "secret_detected", "id": "viol_001", "action": "block"}
        steps = [
            {"type": "scan", "step": 5, "violations": [violation]},
        ]
        result = _collect_turn_violations(steps)
        assert len(result) == 1
        assert result[0] == (violation, 5)

    def test_multiple_violations_same_step(self):
        v1 = {"type": "secret_detected", "id": "viol_001", "action": "block"}
        v2 = {"type": "secret_detected", "id": "viol_002", "action": "block"}
        steps = [
            {"type": "scan", "step": 5, "violations": [v1, v2]},
        ]
        result = _collect_turn_violations(steps)
        assert len(result) == 2
        assert result[0] == (v1, 5)
        assert result[1] == (v2, 5)

    def test_violations_across_multiple_scan_steps(self):
        v1 = {"type": "prompt_injection", "id": "viol_010", "action": "block"}
        v2 = {"type": "secret_detected", "id": "viol_011", "action": "warn"}
        steps = [
            {"type": "input", "step": 0},
            {"type": "scan", "step": 2, "violations": [v1]},
            {"type": "response", "step": 3},
            {"type": "scan", "step": 5, "violations": [v2]},
        ]
        result = _collect_turn_violations(steps)
        assert len(result) == 2
        assert result[0] == (v1, 2)
        assert result[1] == (v2, 5)

    def test_scan_step_missing_violations_key(self):
        steps = [
            {"type": "scan", "step": 3, "scanned": "tool_result"},
        ]
        assert _collect_turn_violations(steps) == []

    def test_step_num_defaults_to_zero(self):
        violation = {"type": "prompt_injection", "id": "viol_099"}
        steps = [
            {"type": "scan", "violations": [violation]},
        ]
        result = _collect_turn_violations(steps)
        assert result[0] == (violation, 0)


class TestStepViolationBadgeRendering:
    """Source-inspection tests for the violation badge rendering functions."""

    def test_render_step_violation_badge_exists(self):
        from ai_guardian.web.pages.traces import _render_step_violation_badge

        assert callable(_render_step_violation_badge)

    def test_badge_uses_violation_type(self):
        from ai_guardian.web.pages.traces import _render_step_violation_badge

        source = inspect.getsource(_render_step_violation_badge)
        assert "violation_type" in source

    def test_badge_color_varies_by_action(self):
        from ai_guardian.web.pages.traces import _render_step_violation_badge

        source = inspect.getsource(_render_step_violation_badge)
        assert '"red"' in source
        assert '"orange"' in source
        assert "action" in source

    def test_badge_has_tooltip_for_id(self):
        from ai_guardian.web.pages.traces import _render_step_violation_badge

        source = inspect.getsource(_render_step_violation_badge)
        assert "tooltip" in source

    def test_badge_scrolls_to_step(self):
        from ai_guardian.web.pages.traces import _render_step_violation_badge

        source = inspect.getsource(_render_step_violation_badge)
        assert "scrollIntoView" in source

    def test_badge_stops_click_propagation(self):
        from ai_guardian.web.pages.traces import _render_step_violation_badge

        source = inspect.getsource(_render_step_violation_badge)
        assert "click.stop" in source


class TestStepElementIds:
    """Verify steps have scroll-target element IDs."""

    def test_render_step_creates_element_id(self):
        from ai_guardian.web.pages.traces import _render_step

        source = inspect.getsource(_render_step)
        assert "step_el_id" in source
        assert '"step-{turn_num}-{step_num}"' in source or "step-{turn_num}" in source

    def test_render_step_accepts_turn_num(self):
        from ai_guardian.web.pages.traces import _render_step

        sig = inspect.signature(_render_step)
        assert "turn_num" in sig.parameters


class TestRunGroupRendering:
    """Source-inspection tests for run group rendering in the trace list."""

    def test_render_run_group_card_exists(self):
        from ai_guardian.web.pages.traces import _render_run_group_card

        assert callable(_render_run_group_card)

    def test_run_group_shows_run_id(self):
        from ai_guardian.web.pages.traces import _render_run_group_card

        source = inspect.getsource(_render_run_group_card)
        assert "run_id" in source

    def test_run_group_shows_agent_count(self):
        from ai_guardian.web.pages.traces import _render_run_group_card

        source = inspect.getsource(_render_run_group_card)
        assert "agent_count" in source

    def test_run_group_shows_violations(self):
        from ai_guardian.web.pages.traces import _render_run_group_card

        source = inspect.getsource(_render_run_group_card)
        assert "total_violations" in source

    def test_run_group_has_expansion(self):
        from ai_guardian.web.pages.traces import _render_run_group_card

        source = inspect.getsource(_render_run_group_card)
        assert "expansion" in source

    def test_run_group_renders_child_traces(self):
        from ai_guardian.web.pages.traces import _render_run_group_card

        source = inspect.getsource(_render_run_group_card)
        assert "_render_trace_card" in source

    def test_trace_list_dispatches_on_type(self):
        from ai_guardian.web.pages.traces import _render_trace_list

        source = inspect.getsource(_render_trace_list)
        assert "run_group" in source
        assert "_render_run_group_card" in source


class TestExpansionHeaderBadges:
    """Verify expansion header includes violation badges."""

    def test_turn_row_uses_custom_header(self):
        from ai_guardian.web.pages.traces import _render_turn_row

        source = inspect.getsource(_render_turn_row)
        assert "add_slot" in source
        assert '"header"' in source

    def test_turn_row_shows_step_count(self):
        from ai_guardian.web.pages.traces import _render_turn_row

        source = inspect.getsource(_render_turn_row)
        assert "Steps (" in source

    def test_turn_row_collects_violations(self):
        from ai_guardian.web.pages.traces import _render_turn_row

        source = inspect.getsource(_render_turn_row)
        assert "_collect_turn_violations" in source

    def test_turn_row_renders_badges(self):
        from ai_guardian.web.pages.traces import _render_turn_row

        source = inspect.getsource(_render_turn_row)
        assert "_render_step_violation_badge" in source
