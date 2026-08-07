#!/usr/bin/env python3
"""
Headless TUI smoke tests.

Verifies AIGuardianTUI can construct, compose, and mount without crashing.
Uses Textual's run_test() — no TTY needed, triggers full lifecycle.

Would have caught #1837 (ImportError: get_config) before release.
"""

import pytest

pytestmark = pytest.mark.skipif(
    not __import__("importlib").util.find_spec("textual"),
    reason="Textual not installed",
)

from ai_guardian.tui.app import AIGuardianTUI, NAV_GROUPS


class TestTUISmokeMount:
    """Smoke tests: TUI app constructs and mounts without errors."""

    @pytest.mark.asyncio
    async def test_console_tui_mounts(self):
        """Verify TUI app can construct and mount without crashing."""
        app = AIGuardianTUI()
        async with app.run_test() as pilot:
            assert pilot.app.is_running

    @pytest.mark.asyncio
    async def test_console_nav_tree_has_entries(self):
        """Verify nav tree populates with at least one entry."""
        app = AIGuardianTUI()
        async with app.run_test() as pilot:
            tree = pilot.app.query_one("#nav-tree")
            assert len(tree.root.children) > 0

    @pytest.mark.asyncio
    async def test_console_content_switcher_exists(self):
        """Verify ContentSwitcher with panels is present."""
        app = AIGuardianTUI()
        async with app.run_test() as pilot:
            switcher = pilot.app.query_one("#panels")
            assert switcher is not None

    @pytest.mark.asyncio
    async def test_console_all_nav_panels_mounted(self):
        """Verify every panel referenced in NAV_GROUPS exists in the DOM."""
        app = AIGuardianTUI()
        async with app.run_test() as pilot:
            for _group_label, items in NAV_GROUPS:
                for _label, panel_id in items:
                    panels = pilot.app.query(f"#{panel_id}")
                    assert len(panels) > 0, f"Panel {panel_id!r} missing from DOM"
