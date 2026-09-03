"""Tests for the web IDE Sessions filters (#2207)."""

import inspect
from unittest.mock import call, patch

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


def test_ide_dropdown_is_searchable():
    from ai_guardian.web.pages.ide_sessions import create_ide_sessions_page

    assert '.props("use-input")' in inspect.getsource(create_ide_sessions_page)


def test_ide_options_start_with_all():
    from ai_guardian.web.pages.ide_sessions import _get_ide_options

    with patch(
        "ai_guardian.sessions.discovery.get_supported_ides",
        return_value=["claude", "cursor"],
    ):
        assert _get_ide_options() == {
            "": "All",
            "claude": "Claude",
            "cursor": "Cursor",
        }


def test_discover_sessions_for_selected_ide():
    from ai_guardian.web.pages.ide_sessions import _discover_sessions

    with patch(
        "ai_guardian.sessions.discovery.discover_sessions",
        return_value=[{"session_id": "one", "ide": "cursor"}],
    ) as discover:
        sessions = _discover_sessions("cursor", 25)

    assert sessions == [{"session_id": "one", "ide": "cursor"}]
    discover.assert_called_once_with("cursor", None, 25)


def test_discover_sessions_for_all_ides_combines_and_limits_by_recency():
    from ai_guardian.web.pages.ide_sessions import _discover_sessions

    discovered = {
        "claude": [{"session_id": "old", "ide": "claude", "modified": 1}],
        "cursor": [
            {"session_id": "new", "ide": "cursor", "modified": 3},
            {"session_id": "middle", "ide": "cursor", "modified": 2},
        ],
    }

    with (
        patch(
            "ai_guardian.sessions.discovery.get_supported_ides",
            return_value=["claude", "cursor"],
        ),
        patch(
            "ai_guardian.sessions.discovery.discover_sessions",
            side_effect=lambda ide, _project, _limit: discovered[ide],
        ) as discover,
    ):
        sessions = _discover_sessions("", 2)

    assert [session["session_id"] for session in sessions] == ["new", "middle"]
    assert discover.call_args_list == [
        call("claude", None, 2),
        call("cursor", None, 2),
    ]


def test_session_local_day_uses_local_timezone():
    from datetime import datetime

    from ai_guardian.web.pages.ide_sessions import _session_local_day

    timestamp = datetime(2025, 6, 15, 13, 45).timestamp()
    assert _session_local_day(timestamp) == datetime.fromtimestamp(timestamp).date()


def test_session_local_day_handles_missing_or_invalid_timestamps():
    from ai_guardian.web.pages.ide_sessions import _session_local_day

    assert _session_local_day(None) is None
    assert _session_local_day("not-a-timestamp") is None


def test_format_day_label_identifies_today_and_yesterday():
    from datetime import date, timedelta

    from ai_guardian.web.pages.ide_sessions import _format_day_label

    assert _format_day_label(date.today()) == "Today"
    assert _format_day_label(date.today() - timedelta(days=1)) == "Yesterday"
