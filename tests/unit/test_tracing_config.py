"""Tests for unified tracing configuration and legacy compatibility."""

from unittest.mock import patch

from ai_guardian.config.loaders import _load_tracing_config, resolve_tracing_config


def test_tracing_defaults_enabled():
    assert resolve_tracing_config({}) == {
        "enabled": True,
        "auto_refresh_interval_seconds": 5,
        "trace_cache_retention_days": 90,
    }


def test_legacy_sdk_trace_viewer_is_supported():
    config = {
        "sdk": {
            "trace_viewer": {
                "enabled": False,
                "auto_refresh_interval_seconds": 10,
                "trace_cache_retention_days": 30,
            }
        }
    }
    assert resolve_tracing_config(config) == {
        "enabled": False,
        "auto_refresh_interval_seconds": 10,
        "trace_cache_retention_days": 30,
    }


def test_top_level_tracing_overrides_legacy_values():
    config = {
        "tracing": {"enabled": False, "trace_cache_retention_days": 7},
        "sdk": {
            "trace_viewer": {
                "enabled": True,
                "auto_refresh_interval_seconds": 10,
                "trace_cache_retention_days": 30,
            }
        },
    }
    assert resolve_tracing_config(config) == {
        "enabled": False,
        "auto_refresh_interval_seconds": 10,
        "trace_cache_retention_days": 7,
    }


@patch("ai_guardian.config.loaders._load_config_file")
def test_loader_uses_defaults_on_config_error(mock_load):
    mock_load.return_value = (None, "invalid config")
    assert _load_tracing_config()["enabled"] is True
