"""Tests for protected developer-session configuration."""

import json

import pytest

from ai_guardian.developer_session import is_trusted_developer_session


def test_only_json_boolean_true_enables_access(monkeypatch):
    monkeypatch.setattr(
        "ai_guardian.developer_session._load_global_config",
        lambda: {"developer_session": {"enabled": True}},
    )
    assert is_trusted_developer_session()


@pytest.mark.parametrize("value", [None, False, "true", "1", 1, "yes"])
def test_missing_or_unexpected_values_are_false(monkeypatch, value):
    monkeypatch.setattr(
        "ai_guardian.developer_session._load_global_config",
        lambda: {"developer_session": {"enabled": value}},
    )
    assert not is_trusted_developer_session()


def test_implicit_source_is_the_global_config_only(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ai_guardian.developer_session.get_config_dir", lambda: tmp_path
    )
    (tmp_path / "ai-guardian.json").write_text(
        json.dumps({"developer_session": {"enabled": True}}), encoding="utf-8"
    )

    assert is_trusted_developer_session()


def test_project_or_overlay_values_are_not_implicit_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ai_guardian.developer_session.get_config_dir", lambda: tmp_path
    )
    (tmp_path / "ai-guardian.json").write_text(
        json.dumps({"developer_session": {"enabled": False}}), encoding="utf-8"
    )
    project_config_dir = tmp_path / "project" / ".ai-guardian"
    project_config_dir.mkdir(parents=True)
    (project_config_dir / "ai-guardian.json").write_text(
        json.dumps({"developer_session": {"enabled": True}}), encoding="utf-8"
    )
    monkeypatch.setenv(
        "AI_GUARDIAN_CONFIG_INLINE",
        json.dumps({"developer_session": {"enabled": True}}),
    )

    assert not is_trusted_developer_session()
