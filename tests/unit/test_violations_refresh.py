"""Tests for violations page refresh button (#1390)."""

import inspect
from types import SimpleNamespace
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

    def test_partial_source_search_is_case_insensitive_and_respects_identity(self):
        from ai_guardian.web.pages.violations import (
            _violation_matches_source_filter,
            _violation_source_identity,
        )

        first = {
            "mirror": {
                "read_only": True,
                "source_daemon": "Shared Agent",
                "source_runtime": "ssh",
                "source_key": "a" * 64,
            }
        }
        second = {
            "mirror": {
                "read_only": True,
                "source_daemon": "Shared Agent",
                "source_runtime": "ssh",
                "source_key": "b" * 64,
            }
        }
        first_key, _ = _violation_source_identity(first, "receiver", local_daemon=True)
        second_key, _ = _violation_source_identity(
            second, "receiver", local_daemon=True
        )

        assert _violation_matches_source_filter(
            first,
            "receiver",
            local_daemon=True,
            selected_source=None,
            query="sHaReD aGeNt",
        )
        assert _violation_matches_source_filter(
            second,
            "receiver",
            local_daemon=True,
            selected_source=None,
            query="shared agent",
        )
        assert _violation_matches_source_filter(
            first,
            "receiver",
            local_daemon=True,
            selected_source=first_key,
            query="SHARED",
        )
        assert not _violation_matches_source_filter(
            second,
            "receiver",
            local_daemon=True,
            selected_source=first_key,
            query="SHARED",
        )
        assert first_key != second_key

    def test_source_availability_distinguishes_live_offline_and_unknown(self):
        from ai_guardian.web.pages.violations import (
            _daemon_source_availability,
            _source_availability_by_identity,
        )
        from ai_guardian.daemon.violation_mirroring import _source_key

        running = SimpleNamespace(
            name="Shared Agent", runtime="ssh", status="running", ssh_id="one"
        )
        paused = SimpleNamespace(
            name="Shared Agent", runtime="ssh", status="running", ssh_id="two"
        )
        starting = SimpleNamespace(
            name="Historical Agent", runtime="ssh", status="starting"
        )
        malformed = SimpleNamespace(name="Malformed", runtime="ssh", status=[])

        assert _daemon_source_availability(running, {"running": True}) == "Running"
        assert (
            _daemon_source_availability(paused, {"running": True, "paused": True})
            == "Paused"
        )
        assert _daemon_source_availability(running, None) == "Offline"
        assert _daemon_source_availability(starting, None) == "Unknown"
        assert _daemon_source_availability(malformed, {"status": []}) == "Unknown"

        availability = _source_availability_by_identity(
            [
                {"target": running, "status": {"running": True}},
                {"target": paused, "status": {"running": True, "paused": True}},
            ],
            current_target=running,
            daemon_name="Shared Agent",
        )
        assert availability[f"remote:{_source_key(running)}"] == "Running"
        assert availability[f"remote:{_source_key(paused)}"] == "Paused"
        assert availability["daemon:Shared Agent"] == "Running"
        assert availability.get("remote:missing", "Unknown") == "Unknown"
