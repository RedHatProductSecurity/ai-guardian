"""Opt-in fixtures for isolated CLI daemon transport contracts."""

import threading
from unittest import mock

import pytest


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
