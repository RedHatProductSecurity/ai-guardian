"""Tests for the Supply Chain web-console page (#1133)."""

import inspect
from unittest.mock import patch, MagicMock

import pytest


class TestWebPageImport:
    """Verify web page module is importable."""

    @pytest.fixture(autouse=True)
    def _skip_no_nicegui(self):
        pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

    def test_create_function_exists(self):
        from ai_guardian.web.pages.supply_chain import create_supply_chain_page

        assert callable(create_supply_chain_page)

    def test_stats_helper_exists(self):
        from ai_guardian.web.pages.supply_chain import _load_sc_stats

        assert callable(_load_sc_stats)


class TestWebRouteRegistration:
    """Verify route is registered in app.py."""

    @pytest.fixture(autouse=True)
    def _skip_no_nicegui(self):
        pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

    def test_route_in_app_source(self):
        from ai_guardian.web.app import WebConsole

        source = inspect.getsource(WebConsole._register_pages)
        assert "/supply-chain" in source

    def test_route_in_sidebar_nav(self):
        from ai_guardian.web.components.header import NAV_GROUPS

        all_suffixes = [suffix for _, items in NAV_GROUPS for _, suffix in items]
        assert "/supply-chain" in all_suffixes

    def test_supply_chain_in_threat_detection_group(self):
        from ai_guardian.web.components.header import NAV_GROUPS

        nav_dict = {name: items for name, items in NAV_GROUPS}
        threat_labels = [label for label, _ in nav_dict["Threat Detection"]]
        assert "Supply Chain" in threat_labels


class TestLoadScStats:
    """Test _load_sc_stats helper."""

    @pytest.fixture(autouse=True)
    def _skip_no_nicegui(self):
        pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

    def test_no_violations(self):
        from ai_guardian.web.pages.supply_chain import _load_sc_stats

        with patch(
            "ai_guardian.web.config_helpers.load_web_violations",
            return_value={"violations": [], "count": 0},
        ):
            result = _load_sc_stats()
        assert result == 0

    def test_with_violations(self):
        from ai_guardian.web.pages.supply_chain import _load_sc_stats

        with patch(
            "ai_guardian.web.config_helpers.load_web_violations",
            return_value={
                "violations": [
                    {"violation_type": "supply_chain"},
                    {"violation_type": "supply_chain"},
                    {"violation_type": "supply_chain"},
                ],
                "count": 3,
            },
        ):
            result = _load_sc_stats()
        assert result == 3

    def test_no_result_returns_zero(self):
        from ai_guardian.web.pages.supply_chain import _load_sc_stats

        with patch(
            "ai_guardian.web.config_helpers.load_web_violations",
            return_value=None,
        ):
            result = _load_sc_stats()
        assert result == 0
