"""Tests for performance page — latency tracking settings for remote daemons (#1363)."""

from unittest import mock

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


class TestLoadLatencyConfig:
    """_load_latency_config routes through load_web_config (works for remote)."""

    def test_returns_latency_tracking_section(self):
        with mock.patch(
            "ai_guardian.web.config_helpers.load_web_config",
            return_value={
                "latency_tracking": {
                    "enabled": True,
                    "max_entries": 10000,
                    "retention_days": 14,
                }
            },
        ):
            from ai_guardian.web.pages.performance import _load_latency_config

            cfg = _load_latency_config()
            assert cfg["enabled"] is True
            assert cfg["max_entries"] == 10000
            assert cfg["retention_days"] == 14

    def test_returns_empty_dict_when_no_section(self):
        with mock.patch(
            "ai_guardian.web.config_helpers.load_web_config",
            return_value={},
        ):
            from ai_guardian.web.pages.performance import _load_latency_config

            cfg = _load_latency_config()
            assert cfg == {}


class TestSaveLatencyConfig:
    """_save_latency_config uses save_web_config (routes through DaemonService)."""

    def test_merges_into_latency_tracking(self):
        existing = {"latency_tracking": {"enabled": False, "max_entries": 5000}}
        saved = {}

        def fake_save(config):
            saved.update(config)

        with (
            mock.patch(
                "ai_guardian.web.config_helpers.load_web_config",
                return_value=existing,
            ),
            mock.patch(
                "ai_guardian.web.config_helpers.save_web_config",
                side_effect=fake_save,
            ),
        ):
            from ai_guardian.web.pages.performance import _save_latency_config

            _save_latency_config({"enabled": True})
            assert saved["latency_tracking"]["enabled"] is True
            assert saved["latency_tracking"]["max_entries"] == 5000

    def test_creates_section_if_missing(self):
        saved = {}

        def fake_save(config):
            saved.update(config)

        with (
            mock.patch(
                "ai_guardian.web.config_helpers.load_web_config",
                return_value={},
            ),
            mock.patch(
                "ai_guardian.web.config_helpers.save_web_config",
                side_effect=fake_save,
            ),
        ):
            from ai_guardian.web.pages.performance import _save_latency_config

            _save_latency_config({"retention_days": 7})
            assert saved["latency_tracking"]["retention_days"] == 7


class TestPageImport:
    """Performance page module imports and exposes create function."""

    def test_create_performance_page_exists(self):
        from ai_guardian.web.pages.performance import create_performance_page

        assert callable(create_performance_page)


class TestRemoteVisibilityLogic:
    """Settings panel visible for remote, Clear Log hidden for remote."""

    def test_settings_expansion_always_visible(self):
        """Settings expansion must not use set_visibility to hide for remote."""
        import inspect
        from ai_guardian.web.pages.performance import create_performance_page

        source = inspect.getsource(create_performance_page)
        settings_idx = source.index('"Settings"')
        settings_line = source[max(0, settings_idx - 200) : settings_idx + 200]
        assert "set_visibility" not in settings_line

    def test_clear_log_gated_by_is_remote(self):
        """Verify Clear Log button is inside 'if not _is_remote' block."""
        import inspect
        from ai_guardian.web.pages.performance import create_performance_page

        source = inspect.getsource(create_performance_page)
        clear_idx = source.index("Clear Log")
        preceding = source[:clear_idx]
        last_if_not_remote = preceding.rfind("if not _is_remote")
        assert (
            last_if_not_remote != -1
        ), "Clear Log should be inside 'if not _is_remote'"


def test_empty_performance_message_explains_paused_daemon():
    from ai_guardian.web.pages.performance import _latency_empty_message

    message = _latency_empty_message({"paused": True})

    assert "Latency collection is paused" in message
    assert "trigger another hook" in message


def test_empty_performance_message_keeps_enablement_guidance():
    from ai_guardian.web.pages.performance import _latency_empty_message

    message = _latency_empty_message({"paused": False})

    assert "Enable latency tracking in Settings above" in message
