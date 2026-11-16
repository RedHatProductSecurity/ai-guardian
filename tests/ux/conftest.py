"""Opt-in fixtures for isolated CLI daemon transport contracts."""

import threading
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def disable_trusted_session_finding_override(monkeypatch):
    """Keep UX contracts independent of the user's protected global config."""
    monkeypatch.setattr(
        "ai_guardian.hook_processing.is_non_blocking_findings_enabled",
        lambda: False,
    )


@pytest.fixture
def cli_connect(monkeypatch):
    """Track only the test thread; background callers get no daemon connection."""
    owner = threading.current_thread()
    connection = mock.Mock(return_value=None)

    def connect_in_test_thread(*args, **kwargs):
        if threading.current_thread() is not owner:
            return None
        return connection(*args, **kwargs)

    monkeypatch.setattr("ai_guardian.daemon.client._connect", connect_in_test_thread)
    return connection
