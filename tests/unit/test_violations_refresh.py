"""Tests for violations page refresh button (#1390)."""

import inspect
from unittest.mock import MagicMock, patch

import pytest


class TestTUIViolationsRefreshButton:
    """Test refresh button in TUI violations page."""

    def test_compose_yields_refresh_button(self):
        """ViolationsContent.compose source contains refresh-violations button."""
        from ai_guardian.tui.violations import ViolationsContent

        source = inspect.getsource(ViolationsContent.compose)
        assert "refresh-violations" in source
        assert '"Refresh"' in source

    def test_on_button_pressed_handles_refresh(self):
        """Pressing refresh-violations calls load_all_filters and notifies."""
        from ai_guardian.tui.violations import ViolationsContent

        source = inspect.getsource(ViolationsContent.on_button_pressed)
        assert "refresh-violations" in source
        assert "load_all_filters" in source
        assert "Violations refreshed" in source

    def test_refresh_handler_calls_load_all_filters(self):
        """Verify on_button_pressed dispatches to load_all_filters for refresh."""
        from ai_guardian.tui.violations import ViolationsContent
        from textual.widgets import Button

        with patch("ai_guardian.tui.violations.ViolationLogger"):
            content = ViolationsContent()

        content.load_all_filters = MagicMock()
        mock_app = MagicMock()
        content._app = mock_app

        event = MagicMock()
        event.button = MagicMock(spec=Button)
        event.button.id = "refresh-violations"

        with patch.object(
            type(content), "app", new_callable=lambda: property(lambda self: self._app)
        ):
            content.on_button_pressed(event)

        content.load_all_filters.assert_called_once()
        mock_app.notify.assert_called_once_with(
            "Violations refreshed", severity="information"
        )


class TestWebViolationsRefreshButton:
    """Test refresh button in web console violations page."""

    @pytest.fixture(autouse=True)
    def _require_nicegui(self):
        pytest.importorskip("nicegui", reason="NiceGUI not available")

    def test_create_violations_page_has_refresh_button(self):
        """Verify violations page source includes refresh button creation."""
        from ai_guardian.web.pages.violations import create_violations_page

        source = inspect.getsource(create_violations_page)
        assert '"Refresh"' in source
        assert '"refresh"' in source
        assert "load_violations" in source

    def test_refresh_button_before_timer(self):
        """Refresh button and load_violations wired in create_violations_page."""
        from ai_guardian.web.pages.violations import create_violations_page

        source = inspect.getsource(create_violations_page)
        refresh_pos = source.index('"Refresh"')
        timer_pos = source.index("ui.timer")
        assert refresh_pos < timer_pos
