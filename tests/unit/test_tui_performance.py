"""Tests for the TUI performance panel's empty-state guidance."""

from types import SimpleNamespace

from ai_guardian.tui.performance import _empty_latency_message


def test_empty_latency_message_explains_paused_daemon():
    message = _empty_latency_message(SimpleNamespace(paused=True))

    assert "Latency collection is paused" in message
    assert "trigger a new hook" in message


def test_empty_latency_message_keeps_enablement_guidance():
    message = _empty_latency_message(SimpleNamespace(paused=False))

    assert "Enable in Settings above" in message
