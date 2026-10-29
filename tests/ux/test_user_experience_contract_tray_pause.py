"""Inline tray pause hierarchy (#2620), without changing live protection.

Manual desktop checks: docs/MODAL_PROVIDERS.md. Confirm daemon -> project ->
session rows, per-row duration/Resume dropdowns, inherited state, expiry,
Refresh/Close/Escape and one persistent window on macOS, Windows and Linux.
Rows must appear before expanding detailed help. Check initial geometry without
monitor context, and confirm Show help/Help neither pauses nor opens another UI.
Mocked contracts do not qualify actual desktop appearance or focus.
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.tray.pause import LEGEND, open_pause_controls
from ai_guardian.ui.modal import UIUnavailable, mark_modal_displayed
from ai_guardian.ui.pause_controls import _row_choices, _row_placeholder
from tests.fixtures.tray_pause import row_event


@pytest.fixture
def pause_ui(monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("ai_guardian.ui.display._tkinter_available", lambda: True)
    stats = {
        "paused": False,
        "active_project_dirs": ["/project"],
        "paused_dirs": {},
        "active_sessions": [
            {
                "session_key": "Adapter:known",
                "agent": "OpenCode",
                "project_dir": "/project",
                "paused": False,
            }
        ],
    }
    tray = SimpleNamespace(
        _targets=[DaemonTarget("workstation", "local")],
        _get_stats=lambda: deepcopy(stats),
        _multi_client=Mock(),
        _menu=Mock(),
        _refresh_event=Mock(),
        _dispatch_to_main=Mock(),
        _refresh_menu=Mock(),
        _sync_pause_state=Mock(),
    )

    def pause(_target, minutes):
        stats["paused"] = True
        return True

    tray._multi_client.send_pause.side_effect = pause
    with patch(
        "ai_guardian.ui.pause_controls.run_pause_provider", return_value=None
    ) as show:
        yield SimpleNamespace(tray=tray, stats=stats, show=show)


def test_open_close_never_changes_pause_state_or_opens_another_provider(pause_ui):
    """USER EXPERIENCE: inspect hierarchy, then Close/Escape -> no request."""
    open_pause_controls(pause_ui.tray)
    assert pause_ui.stats["paused"] is False
    pause_ui.tray._multi_client.send_pause.assert_not_called()
    pause_ui.tray._multi_client.send_resume.assert_not_called()
    pause_ui.show.assert_called_once()
    assert pause_ui.show.call_args.args[0] == "tkinter"
    payload = pause_ui.show.call_args.args[1]
    assert payload["legend"] == LEGEND
    assert [(r["scope"], r["level"], r["action"]) for r in payload["rows"]] == [
        ("global", 0, "Pause"),
        ("dir", 1, "Pause"),
        ("session", 2, "Pause"),
    ]
    assert payload["durations"] == {
        "5 minutes": 5,
        "15 minutes": 15,
        "30 minutes": 30,
        "1 hour": 60,
        "Until resume": 0,
    }
    assert all(
        _row_choices(payload, row) == payload["durations"] for row in payload["rows"]
    )
    assert all(_row_placeholder(row) == "Pause for…" for row in payload["rows"])


def test_unavailable_rows_do_not_offer_duration_or_resume_choices(pause_ui):
    """USER EXPERIENCE: offline/unsupported row -> inert unavailable dropdown."""
    open_pause_controls(pause_ui.tray)
    payload = pause_ui.show.call_args.args[1]
    row = {**payload["rows"][0], "available": False}
    assert _row_choices(payload, row) == {}
    assert _row_placeholder(row) == "Unavailable"
    pause_ui.tray._multi_client.send_pause.assert_not_called()


def test_startup_failure_preserves_entire_hierarchy_and_monitor(pause_ui):
    """USER EXPERIENCE: proven pre-display Tk failure -> complete browser UI."""
    pause_ui.show.side_effect = [UIUnavailable(), None]
    bounds = (1920, 0, 1920, 1080)
    open_pause_controls(pause_ui.tray, screen_bounds=bounds)
    assert [call.args[0] for call in pause_ui.show.call_args_list] == [
        "tkinter",
        "nicegui",
    ]
    first, second = pause_ui.show.call_args_list
    assert first.args[1] == second.args[1]
    assert first.kwargs == second.kwargs == {"screen_bounds": bounds}


@pytest.mark.parametrize("preference", ["tkinter", "nicegui", "headless"])
def test_preferences_are_exclusive_and_headless_is_inert(
    pause_ui, monkeypatch, preference
):
    """USER EXPERIENCE: explicit toolkit never falls back; headless stays inert."""
    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", preference)
    pause_ui.show.side_effect = UIUnavailable()
    open_pause_controls(pause_ui.tray)
    assert pause_ui.show.call_count == int(preference != "headless")
    if preference != "headless":
        assert pause_ui.show.call_args.args[0] == preference
    pause_ui.tray._multi_client.send_pause.assert_not_called()
    pause_ui.tray._multi_client.get_status.assert_not_called()


@pytest.mark.parametrize("error", [UIUnavailable(), RuntimeError("unknown visibility")])
def test_post_display_failure_never_reopens_in_another_toolkit(pause_ui, error):
    """USER EXPERIENCE: visible window fails -> terminal, not a replacement."""

    def fail(*args, **kwargs):
        mark_modal_displayed()
        raise error

    pause_ui.show.side_effect = fail
    open_pause_controls(pause_ui.tray)
    pause_ui.show.assert_called_once()


@pytest.mark.parametrize(
    "scope,target",
    [("global", None), ("dir", "/project"), ("session", "Adapter:known")],
)
def test_each_level_has_its_own_pause_resume_action_in_same_window(
    pause_ui, scope, target
):
    """USER EXPERIENCE: select a row duration -> that row offers Resume in-place."""

    def update(_target, identity, minutes=None):
        if scope == "dir":
            pause_ui.stats["paused_dirs"][identity] = 0
        else:
            pause_ui.stats["active_sessions"][0]["paused"] = True
        return True

    if scope != "global":
        getattr(pause_ui.tray._multi_client, f"send_pause_{scope}").side_effect = update

    def show(provider, display, respond, **kwargs):
        event = row_event(display, scope=scope, target=target, minutes=30)
        refreshed = respond(event)
        assert "Pause request confirmed. Status refreshed." == refreshed["feedback"]
        assert (
            row_event(refreshed, scope=scope, target=target, action="Resume")["row"]
            != event["row"]
        )
        row = next(
            row
            for row in refreshed["rows"]
            if row["id"]
            == row_event(refreshed, scope=scope, target=target, action="Resume")["row"]
        )
        assert _row_choices(refreshed, row) == {"Resume": "resume"}
        assert _row_placeholder(row) == "Resume…"
        assert "no request was sent" in respond(event)["feedback"]  # stale DOM event

    pause_ui.show.side_effect = show
    open_pause_controls(pause_ui.tray)
    pause_ui.show.assert_called_once()
    if scope != "global":
        pause_ui.tray._multi_client.send_pause.assert_not_called()


def test_multi_daemon_hierarchy_never_retargets_after_discovery_reorders(pause_ui):
    """USER EXPERIENCE: every daemon has a top-level row; clicked source stays fixed."""
    remote = DaemonTarget("remote", "manual", port=45678)
    pause_ui.tray._targets.append(remote)
    remote_stats = {"paused": False, "paused_dirs": {"/remote-project": 0}}
    pause_ui.tray._multi_client.get_status.side_effect = lambda _: deepcopy(
        remote_stats
    )

    def pause(target, minutes):
        assert target.port == remote.port and minutes == 15
        remote_stats["paused"] = True
        return True

    pause_ui.tray._multi_client.send_pause.side_effect = pause

    def show(provider, display, respond, **kwargs):
        headers = [row for row in display["rows"] if row["level"] == 0]
        assert headers[0]["label"].startswith("●")
        assert headers[1]["label"].startswith("◐")
        event = row_event(display, daemon=1, minutes=15)
        pause_ui.tray._targets.reverse()
        updated = respond(event)
        assert updated["rows"][0]["label"].startswith("☾ remote")

    pause_ui.show.side_effect = show
    open_pause_controls(pause_ui.tray)
    assert pause_ui.stats["paused"] is False and remote_stats["paused"] is True
