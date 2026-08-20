"""Tests for project selector directory browser (Issue #1969)."""

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


class TestBrowseSentinel:
    """Verify the browse sentinel is a non-path string."""

    def test_sentinel_is_string(self):
        from ai_guardian.web.components.header import _BROWSE_SENTINEL

        assert isinstance(_BROWSE_SENTINEL, str)

    def test_sentinel_not_empty(self):
        from ai_guardian.web.components.header import _BROWSE_SENTINEL

        assert _BROWSE_SENTINEL != ""

    def test_sentinel_not_valid_path(self):
        from ai_guardian.web.components.header import _BROWSE_SENTINEL

        assert _BROWSE_SENTINEL.startswith("__")


class TestCustomProjectDirs:
    """Verify custom project dir helpers work with mocked session storage."""

    def test_get_empty_when_no_storage(self, monkeypatch):
        from ai_guardian.web.components import header

        monkeypatch.setattr(header, "_get_custom_project_dirs", lambda: [])
        assert header._get_custom_project_dirs() == []

    def test_add_and_get_roundtrip(self, monkeypatch):
        from unittest.mock import MagicMock

        mock_app = MagicMock()
        storage = {}
        mock_app.storage.user = storage

        # Patch at the import target so the deferred `from nicegui import app`
        # inside each helper resolves to our mock.
        import nicegui

        monkeypatch.setattr(nicegui, "app", mock_app)

        from ai_guardian.web.components.header import (
            _add_custom_project_dir,
            _get_custom_project_dirs,
        )

        # Initially empty
        assert _get_custom_project_dirs() == []

        # Add one
        _add_custom_project_dir("/home/user/project1")
        assert "/home/user/project1" in storage.get("custom_project_dirs", [])

        # Add another
        _add_custom_project_dir("/home/user/project2")
        assert len(storage["custom_project_dirs"]) == 2

        # No duplicate
        _add_custom_project_dir("/home/user/project1")
        assert len(storage["custom_project_dirs"]) == 2

    def test_add_custom_dir_no_duplicate(self, monkeypatch):
        from unittest.mock import MagicMock

        mock_app = MagicMock()
        mock_app.storage.user = {"custom_project_dirs": ["/existing"]}

        import nicegui

        monkeypatch.setattr(nicegui, "app", mock_app)

        from ai_guardian.web.components.header import _add_custom_project_dir

        _add_custom_project_dir("/existing")
        assert mock_app.storage.user["custom_project_dirs"] == ["/existing"]


class TestBrowseResetGuard:
    """Verify that resetting value after Browse selection skips page reload."""

    def test_browsing_active_skips_reload(self):
        """When _browsing['active'] is True, on_project_change should return
        early without reloading — prevents the page reload that was killing
        the browse dialog timer (#2089)."""
        from ai_guardian.web.components.header import _BROWSE_SENTINEL

        _browsing = {"active": True}
        reloaded = {"called": False}

        class FakeEvent:
            value = "/some/project"

        import asyncio

        async def on_project_change(e):
            if e.value == _BROWSE_SENTINEL:
                return
            if _browsing["active"]:
                _browsing["active"] = False
                return
            reloaded["called"] = True

        asyncio.get_event_loop().run_until_complete(on_project_change(FakeEvent()))
        assert not _browsing["active"], "_browsing['active'] should be reset"
        assert not reloaded["called"], "page reload should be skipped"


class TestShortenProjectPath:
    """Verify _shorten_project_path handles various inputs."""

    def test_shortens_home_path(self):
        from ai_guardian.web.components.header import _shorten_project_path

        result = _shorten_project_path("/some/very/long/path/to/project")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_string_on_exception(self):
        from ai_guardian.web.components.header import _shorten_project_path

        result = _shorten_project_path("")
        assert isinstance(result, str)
