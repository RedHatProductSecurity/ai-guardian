"""Tests for the configuration and CLI protection Web settings."""

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.pages.global_settings import (
    _get_developer_session_enabled,
    _set_developer_session_enabled,
)


def test_developer_session_defaults_to_disabled():
    assert _get_developer_session_enabled({}) is False


def test_developer_session_reads_only_boolean_true():
    assert (
        _get_developer_session_enabled({"developer_session": {"enabled": True}}) is True
    )
    assert (
        _get_developer_session_enabled({"developer_session": {"enabled": "true"}})
        is False
    )


def test_developer_session_save_preserves_other_config():
    config = {"permissions": {"enabled": True}}

    updated = _set_developer_session_enabled(config, True)

    assert updated is config
    assert updated["permissions"] == {"enabled": True}
    assert updated["developer_session"] == {"enabled": True}


def test_developer_session_save_coerces_switch_value():
    config = {}

    _set_developer_session_enabled(config, 0)

    assert config["developer_session"]["enabled"] is False
