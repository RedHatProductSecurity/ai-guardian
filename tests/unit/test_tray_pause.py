"""Pause modal snapshots and exact-scope routing; no real daemon or UI."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.tray.pause import (
    LEGEND,
    MESSAGE,
    UNCONFIRMED,
    PauseSnapshot,
    open_pause_controls,
)
from tests.fixtures.tray_pause import row_event, pause_values


@pytest.fixture
def pause_tray():
    stats = {
        "paused": False,
        "paused_dirs": {},
        "active_project_dirs": ["/project"],
        "active_sessions": [
            {
                "session_key": "Adapter:first",
                "session_id": "first",
                "agent": "OpenCode",
                "session_title": "Fix A&B",
                "project_dir": "/project",
                "paused": False,
            },
            {
                "session_key": "Adapter:second",
                "session_id": "second",
                "agent": "OpenCode",
                "session_title": "Fix A&B",
                "project_dir": "/project",
                "paused": False,
            },
        ],
    }
    client = Mock()
    client.get_status.side_effect = lambda _: deepcopy(stats)
    tray = SimpleNamespace(
        _targets=[DaemonTarget("selected", "local", status="running")],
        _multi_client=client,
        _get_stats=lambda: deepcopy(stats),
        _menu=Mock(),
        _refresh_event=Mock(),
        _dispatch_to_main=Mock(),
        _sync_pause_state=Mock(),
        _refresh_menu=Mock(),
    )

    def update(scope, paused, *args):
        if scope == "global":
            stats["paused"] = paused
        elif scope == "dir":
            if paused:
                stats["paused_dirs"][args[1]] = 0
            else:
                stats["paused_dirs"].pop(args[1], None)
        else:
            next(s for s in stats["active_sessions"] if s["session_key"] == args[1])[
                "paused"
            ] = paused
        return True

    for scope in ("global", "dir", "session"):
        for action in ("pause", "resume"):
            method = f"send_{action}" + ("" if scope == "global" else f"_{scope}")
            getattr(client, method).side_effect = (
                lambda *args, s=scope, p=action == "pause": update(s, p, *args)
            )
    return tray, stats


@pytest.mark.parametrize(
    "scope,identity",
    [("global", ""), ("dir", "/project"), ("session", "Adapter:first")],
)
@pytest.mark.parametrize("minutes", [0, 5, 15, 30, 60])
@pytest.mark.parametrize(
    "runtime", ["local", "container", "kubernetes", "manual", "ssh"]
)
def test_all_existing_durations_and_scopes_route_exactly(
    pause_tray, scope, identity, minutes, runtime
):
    tray, stats = pause_tray
    tray._targets[0].runtime = runtime
    snapshot = PauseSnapshot(tray)
    view, option, action, duration = snapshot.resolve(
        pause_values(snapshot, scope=scope, identity=identity, minutes=minutes)
    )
    assert "confirmed" in snapshot.request(view, option, action, duration)
    method = "send_pause" + ("" if scope == "global" else f"_{scope}")
    args = (duration,) if scope == "global" else (identity, duration)
    sent = getattr(tray._multi_client, method).call_args.args
    assert sent[0].name == "selected"
    assert sent[1:] == args
    if scope != "global":
        tray._multi_client.send_pause.assert_not_called()
    resumed = PauseSnapshot(tray)
    view, option, action, duration = resumed.resolve(
        pause_values(resumed, scope=scope, identity=identity, action="Resume")
    )
    assert "confirmed" in resumed.request(view, option, action, duration)
    assert PauseSnapshot(tray).views[0].find(scope, identity).paused is False
    tray._menu._invalidate_stats.assert_called()
    tray._refresh_event.set.assert_called()


def test_effective_states_and_own_pause_layers_are_distinct(pause_tray):
    tray, stats = pause_tray
    stats["active_sessions"][0]["paused"] = True
    view = PauseSnapshot(tray).views[0]
    assert view.label.startswith("◐")
    assert view.find("dir", "/project").label.startswith("◐")
    assert view.find("session", "Adapter:first").label.startswith("☾")
    assert view.find("session", "Adapter:second").label.startswith("●")
    stats["paused_dirs"]["/project"] = 0
    view = PauseSnapshot(tray).views[0]
    assert view.find("session", "Adapter:second").label.startswith("☾")
    assert view.find("session", "Adapter:second").paused is False
    stats["paused"] = True
    snapshot = PauseSnapshot(tray)
    assert snapshot.views[0].label.startswith("☾")
    values = pause_values(snapshot, scope="dir", identity="/project", action="Resume")
    assert "confirmed" in snapshot.request(*snapshot.resolve(values))
    assert stats["paused"] and stats["active_sessions"][0]["paused"]
    assert PauseSnapshot(tray).views[0].find("dir", "/project").label.startswith("☾")


def test_duplicate_titles_keep_full_keys_projects_and_literal_ampersands(pause_tray):
    tray, _ = pause_tray
    view = PauseSnapshot(tray).views[0]
    first, second = (
        view.find("session", f"Adapter:{key}") for key in ("first", "second")
    )
    assert first.label != second.label
    assert "Fix A&B" in first.label and "A&&B" not in first.label
    assert "Project: /project" in first.label and "Key: Adapter:first" in first.label


def test_hierarchy_has_actions_at_every_level_but_no_connection_secrets(pause_tray):
    tray, stats = pause_tray
    first = tray._targets[0]
    first.auth_token = "private-display-sentinel"
    first.tls = {"private": "private-tls-sentinel"}
    tray._targets.append(DaemonTarget("selected", "container", container_id="other"))
    snapshot = PauseSnapshot(tray)
    display = snapshot.payload()
    assert [row["level"] for row in display["rows"]] == [0, 1, 2, 2, 0, 1, 2, 2]
    assert all(row["action"] == "Pause" for row in display["rows"])
    for daemon in range(2):
        values = row_event(
            display,
            daemon=daemon,
            scope="session",
            target="Adapter:second",
        )
        view, option, action, duration = snapshot.resolve(values)
        assert view.target.runtime == ("local" if daemon == 0 else "container")
        assert option.identity == "Adapter:second" and duration == 5
    payload = json.dumps(display)
    assert first.auth_token not in payload and "private-tls-sentinel" not in payload
    assert all(glyph in LEGEND for glyph in "●◐☾○")
    assert "Resume clears only the selected pause layer" in MESSAGE


@pytest.mark.parametrize(
    "stats", [{}, {"paused": False}, {"paused": False, "active_sessions": []}]
)
def test_offline_and_older_daemons_have_explicit_unavailable_scopes(pause_tray, stats):
    tray, original = pause_tray
    original.clear()
    original.update(stats)
    snapshot = PauseSnapshot(tray)
    session_fields = [
        option
        for choices in snapshot.views[0].scopes.values()
        for option in choices
        if option.scope == "session"
    ]
    assert session_fields and not session_fields[0].available
    assert session_fields[0].label.startswith("○")
    if stats:
        assert snapshot.views[0].find("global", "") is not None
    else:
        assert snapshot.views[0].label.startswith("○")


@pytest.mark.parametrize(
    "change", ["remove", "endpoint", "session", "state", "ssh_reconnect"]
)
def test_stale_target_or_connection_never_retargets_or_broadens(pause_tray, change):
    tray, stats = pause_tray
    if change == "ssh_reconnect":
        tray._targets[0].runtime = "ssh"
        tray._targets[0].ssh_tunnel = Mock()
    snapshot = PauseSnapshot(tray)
    resolved = snapshot.resolve(
        pause_values(snapshot, scope="session", identity="Adapter:first")
    )
    if change == "remove":
        tray._targets = []
    elif change == "endpoint":
        tray._targets[0].port = 12345
    elif change == "session":
        stats["active_sessions"].pop(0)
    elif change == "state":
        stats["active_sessions"][0]["paused"] = True
    else:
        tray._targets[0].ssh_tunnel = Mock()
    assert "no request was sent" in snapshot.request(*resolved)
    tray._multi_client.send_pause_session.assert_not_called()
    tray._multi_client.send_pause.assert_not_called()


def test_unconfirmed_request_refreshes_without_success_or_fallback(pause_tray):
    tray, _ = pause_tray
    tray._multi_client.send_pause_dir.side_effect = None
    tray._multi_client.send_pause_dir.return_value = False
    snapshot = PauseSnapshot(tray)
    assert (
        snapshot.request(
            *snapshot.resolve(pause_values(snapshot, scope="dir", identity="/project"))
        )
        == UNCONFIRMED
    )
    tray._multi_client.send_pause.assert_not_called()
    tray._dispatch_to_main.assert_any_call(tray._sync_pause_state)
    tray._dispatch_to_main.assert_any_call(tray._refresh_menu)


@pytest.mark.parametrize(
    "field,value",
    [
        ("row", ""),
        ("row", "forged"),
        ("row", None),
        ("minutes", "-1"),
        ("minutes", True),
        ("action", "Resume"),
    ],
)
def test_invalid_selection_is_not_a_global_request(pause_tray, field, value):
    tray, _ = pause_tray
    snapshot = PauseSnapshot(tray)
    values = pause_values(snapshot, scope="session", identity="Adapter:first")
    values[field] = value
    with pytest.raises(ValueError):
        snapshot.resolve(values)
    tray._multi_client.send_pause.assert_not_called()


def test_inline_action_refreshes_same_window_and_old_row_cannot_replay(pause_tray):
    tray, stats = pause_tray

    def provider(name, display, respond, **kwargs):
        assert name == "tkinter" and stats["paused"] is False
        event = row_event(display, minutes=15)
        refreshed = respond(event)
        assert refreshed["rows"][0]["label"].startswith("☾")
        assert refreshed["rows"][0]["action"] == "Resume"
        assert "Pause request confirmed. Status refreshed." in refreshed["feedback"]
        assert "no request was sent" in respond(event)["feedback"]

    with (
        patch("ai_guardian.ui.modal.ui_provider_order", return_value=("tkinter",)),
        patch(
            "ai_guardian.ui.pause_controls.run_pause_provider", side_effect=provider
        ) as show,
    ):
        open_pause_controls(tray, screen_bounds=(100, 0, 800, 600))
    show.assert_called_once()
    assert stats["paused"] is True
    assert tray._multi_client.send_pause.call_count == 1
    tray._multi_client.send_resume.assert_not_called()
