"""Tests for violations page refresh button (#1390)."""

import inspect
from unittest.mock import MagicMock, patch

import pytest


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
