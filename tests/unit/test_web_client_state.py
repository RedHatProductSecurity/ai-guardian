"""Tests for NiceGUI client lifecycle compatibility."""

from ai_guardian.web.client_state import is_client_deleted


class _NiceGui30Client:
    def __init__(self, deleted: bool):
        self._deleted = deleted


class _CurrentNiceGuiClient:
    def __init__(self, deleted: bool):
        self.is_deleted = deleted
        self._deleted = not deleted


def test_uses_public_deleted_state_when_available():
    assert is_client_deleted(_CurrentNiceGuiClient(True)) is True
    assert is_client_deleted(_CurrentNiceGuiClient(False)) is False


def test_falls_back_to_nicegui_30_private_state():
    assert is_client_deleted(_NiceGui30Client(True)) is True
    assert is_client_deleted(_NiceGui30Client(False)) is False


def test_unknown_client_is_treated_as_active():
    assert is_client_deleted(object()) is False
