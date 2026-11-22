"""Tests for CLI version and runtime activation status separation."""

import pytest

from ai_guardian.cli_runtime import runtime_activation_info
from ai_guardian.ide_registry import SUPPORTED_IDE_REGISTRY, get_ide_integration


@pytest.mark.parametrize(
    "integration",
    [item for item in SUPPORTED_IDE_REGISTRY if item.cli_capable],
    ids=lambda item: item.key,
)
def test_detected_cli_defaults_to_unverified_activation(integration):
    """A detected CLI and healthy saved setup are not runtime load evidence."""
    activation = runtime_activation_info(
        integration,
        {"healthy": True, "cli": {"version": "9.9.9"}},
        detected=True,
    )

    assert activation["status"] == "unverified"
    expected_reason = integration.runtime_verification_note or (
        "AI Guardian has no runtime signal confirming a live hook invocation "
        "or plugin load. Unverified is not a configuration fault, and CLI version "
        "checks are not proof."
    )
    assert activation["reason"] == expected_reason


def test_kilo_plugin_runtime_caveat_is_preserved():
    integration = get_ide_integration("kilo")

    activation = runtime_activation_info(
        integration, {"plugin_runtime_status": "unverified"}, detected=True
    )

    assert activation == {
        "status": "unverified",
        "reason": integration.runtime_verification_note,
    }


@pytest.mark.parametrize(
    ("detected", "expected"),
    [(False, "not_detected"), (None, "unknown")],
)
def test_activation_status_reports_detection_state(detected, expected):
    integration = get_ide_integration("claude")

    assert runtime_activation_info(integration, detected=detected)["status"] == expected


def test_non_cli_integration_is_not_applicable():
    integration = get_ide_integration("cursor")

    assert runtime_activation_info(integration, detected=True) == {
        "status": "not_applicable",
        "reason": "This integration does not expose a local CLI runtime.",
    }


@pytest.mark.parametrize("status", ["verified", "failed"])
def test_explicit_runtime_result_is_used(status):
    integration = get_ide_integration("claude")
    reason = f"host explicitly reported {status}"

    activation = runtime_activation_info(
        integration,
        {"runtime_activation": {"status": status, "reason": reason}},
        detected=True,
    )

    assert activation == {"status": status, "reason": reason}
