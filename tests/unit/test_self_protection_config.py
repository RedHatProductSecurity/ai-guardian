"""Tests for the host-CLI self-protection configuration helper."""

import pytest

from ai_guardian.self_protection import is_host_agent_cli_protection_enabled


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"self_protection": None},
        {"self_protection": {"block_host_agent_cli": "false"}},
        {"self_protection": {"block_host_agent_cli": 0}},
        {"self_protection": {"block_host_agent_cli": {"value": False}}},
    ],
)
def test_host_cli_protection_defaults_enabled_for_missing_or_invalid_config(config):
    assert is_host_agent_cli_protection_enabled(config) is True


def test_host_cli_protection_accepts_only_explicit_boolean_false_as_opt_out():
    assert (
        is_host_agent_cli_protection_enabled(
            {"self_protection": {"block_host_agent_cli": False}}
        )
        is False
    )
    assert (
        is_host_agent_cli_protection_enabled(
            {"self_protection": {"block_host_agent_cli": True}}
        )
        is True
    )
