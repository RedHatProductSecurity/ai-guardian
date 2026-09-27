"""Tests for the trusted developer-session runtime parameter."""

import pytest

from ai_guardian.developer_session import (
    DEVELOPER_SESSION_ENV,
    is_trusted_developer_session,
)


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " true "])
def test_known_enabled_values_are_true(value):
    assert is_trusted_developer_session(value)


@pytest.mark.parametrize("value", [None, "", "0", "yes", "true-ish", True, 1])
def test_missing_or_unexpected_values_are_false(value):
    assert not is_trusted_developer_session(value)


def test_environment_value_is_the_only_implicit_source(monkeypatch):
    monkeypatch.delenv(DEVELOPER_SESSION_ENV, raising=False)
    assert not is_trusted_developer_session()

    monkeypatch.setenv(DEVELOPER_SESSION_ENV, "1")
    assert is_trusted_developer_session()
