"""Tests for privacy-preserving secret redaction history statistics."""

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.violations.counter import ViolationCounter
from ai_guardian.web.pages.secret_redaction import _load_redaction_stats


def test_redaction_stats_use_aggregate_secret_counter(monkeypatch):
    """Sensitive history keeps aggregate counts, not per-finding details."""
    monkeypatch.setattr(
        ViolationCounter,
        "get_counters",
        lambda self: {
            "violation_totals": {
                "secret_detected": 7,
                "pii_detected": 3,
                "sensitive_finding": 99,
            }
        },
    )

    assert _load_redaction_stats() == (7, {})
