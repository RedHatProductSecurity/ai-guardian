"""Tests for protected developer-session configuration."""

import json
from pathlib import Path

import pytest

from ai_guardian.developer_session import (
    is_non_blocking_findings_enabled,
    is_trusted_developer_session,
    should_downgrade_blocking_finding,
)


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
        json.dumps(
            {
                "developer_session": {
                    "enabled": False,
                    "non_blocking_findings": False,
                }
            }
        ),
        encoding="utf-8",
    )
    project_config_dir = tmp_path / "project" / ".ai-guardian"
    project_config_dir.mkdir(parents=True)
    (project_config_dir / "ai-guardian.json").write_text(
        json.dumps(
            {
                "developer_session": {
                    "enabled": True,
                    "non_blocking_findings": True,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "AI_GUARDIAN_CONFIG_INLINE",
        json.dumps(
            {
                "developer_session": {
                    "enabled": True,
                    "non_blocking_findings": True,
                }
            }
        ),
    )

    assert not is_trusted_developer_session()
    assert not is_non_blocking_findings_enabled()


@pytest.mark.parametrize(
    "config,expected",
    [
        ({"developer_session": {"enabled": True, "non_blocking_findings": True}}, True),
        (
            {"developer_session": {"enabled": False, "non_blocking_findings": True}},
            False,
        ),
        ({"developer_session": {"enabled": True}}, False),
        (
            {"developer_session": {"enabled": True, "non_blocking_findings": "true"}},
            False,
        ),
        (
            {"developer_session": {"enabled": "true", "non_blocking_findings": True}},
            False,
        ),
        ({"developer_session": []}, False),
        (None, False),
    ],
)
def test_non_blocking_findings_requires_both_explicit_global_booleans(
    monkeypatch, config, expected
):
    monkeypatch.setattr(
        "ai_guardian.developer_session._load_global_config", lambda: config
    )
    assert is_non_blocking_findings_enabled() is expected


@pytest.mark.parametrize(
    "enabled,action,detected,scan_error,expected",
    [
        (True, "block", True, None, True),
        (False, "block", True, None, False),
        (True, "warn", True, None, False),
        (True, "log-only", True, None, False),
        (True, "ask", True, None, False),
        (True, "redact", True, None, False),
        (True, "block", False, None, False),
        (True, "block", True, "synthetic scan failure", False),
    ],
)
def test_only_successful_block_findings_are_eligible_for_downgrade(
    enabled, action, detected, scan_error, expected
):
    assert (
        should_downgrade_blocking_finding(
            enabled=enabled,
            action=action,
            detected=detected,
            scan_error=scan_error,
        )
        is expected
    )


def test_generated_and_example_configs_default_non_blocking_findings_off():
    from ai_guardian.setup.config import _get_default_config_template

    assert _get_default_config_template()["developer_session"] == {
        "enabled": False,
        "non_blocking_findings": False,
    }

    project_root = Path(__file__).resolve().parents[2]
    for profile in ("minimal", "moderator", "standard", "strict"):
        config = json.loads(
            (
                project_root
                / "src"
                / "ai_guardian"
                / "templates"
                / "profiles"
                / f"{profile}.json"
            ).read_text(encoding="utf-8")
        )
        assert config["developer_session"]["non_blocking_findings"] is False

    example = json.loads(
        (project_root / "ai-guardian-example.json").read_text(encoding="utf-8")
    )
    assert example["developer_session"]["non_blocking_findings"] is False

    schema = json.loads(
        (
            project_root
            / "src"
            / "ai_guardian"
            / "schemas"
            / "ai-guardian-config.schema.json"
        ).read_text(encoding="utf-8")
    )
    option = schema["properties"]["developer_session"]["properties"][
        "non_blocking_findings"
    ]
    assert option["type"] == "boolean"
    assert option["default"] is False
