"""Tray pause hierarchy. UI receives display rows, never transport credentials."""

import logging
import math
from copy import copy, deepcopy
from dataclasses import dataclass
from typing import Any

from ai_guardian.daemon.multi_client import MultiDaemonClient
from ai_guardian.sessions.base import resolve_session_title
from ai_guardian.ui.modal import run_modal

logger = logging.getLogger(__name__)

LEGEND = "● Active   ◐ Partially paused   ☾ Paused   ○ Unavailable / offline"
MESSAGE = (
    "Choose a pause duration from a daemon, project-directory or individual-session "
    "row's dropdown. Selecting a duration pauses that row immediately; rows with their own pause offer Resume. "
    "Opening or closing this window changes nothing; actions already taken remain in effect.\n\n"
    "Use Refresh status to update external changes and expiry. "
    "Resume clears only the selected pause layer; global, directory or individual "
    "session pauses may still apply. Directory-wide pause also covers callers without stable session IDs."
)
DURATIONS = {
    "5 minutes": 5,
    "15 minutes": 15,
    "30 minutes": 30,
    "1 hour": 60,
    "Until resume": 0,
}
UNCONFIRMED = (
    "The daemon did not confirm the request. It may be unreachable, the selected "
    "scope may no longer exist, or this operation may be unsupported. "
    "No broader pause or resume was requested."
)


def _same_connection(first, second):
    """Compare routing and trust, not display names or discovery list positions."""
    fields = (
        "runtime",
        "host",
        "port",
        "socket_path",
        "url",
        "container_id",
        "container_engine",
        "pod_name",
        "namespace",
        "context",
        "ssh_id",
        "auth_token",
        "tls",
    )
    return all(getattr(first, name) == getattr(second, name) for name in fields) and (
        first.runtime != "ssh" or first.ssh_tunnel is second.ssh_tunnel
    )


def _has_route(target):
    """Discovery replacements need a real routing identity, never only a name."""
    return target.runtime == "local" or bool(
        target.ssh_id
        or target.container_id
        or target.pod_name
        or target.url
        or target.socket_path
        or target.port
    )


def _refresh_tray(tray):
    tray._menu._invalidate_stats()
    tray._refresh_event.set()
    tray._dispatch_to_main(tray._sync_pause_state)
    tray._dispatch_to_main(tray._refresh_menu)


@dataclass(frozen=True)
class PauseOption:
    scope: str
    identity: str
    label: str
    paused: bool = False
    available: bool = True
    project_dir: str = ""


@dataclass
class DaemonView:
    target: Any
    label: str
    scopes: dict[str, list[PauseOption]]
    source: Any

    def find(self, scope, identity):
        return next(
            (
                option
                for option in self.scopes[scope]
                if option.identity == identity and option.available
            ),
            None,
        )


def _pause_duration(remaining, *, session=False):
    if (
        isinstance(remaining, (int, float))
        and math.isfinite(remaining)
        and remaining > 0
    ):
        return f" ({int(remaining // 60)}m {int(remaining % 60)}s left)"
    return " (until resumed or session ends)" if session else " (until resume)"


def _read_view(tray, client, source, index):
    selected = copy(source)
    selected.tls = deepcopy(source.tls)
    try:
        stats = (
            tray._get_stats()
            if selected.runtime == "local"
            else client.get_status(selected)
        )
    except Exception as exc:
        logger.warning("Pause status unavailable (%s)", type(exc).__name__)
        stats = None
    available = (
        isinstance(stats, dict)
        and type(stats.get("paused")) is bool
        and stats.get("error") is None
    )
    stats = stats if available else {}
    globally_paused = stats.get("paused", False)
    paused_dirs = stats.get("paused_dirs")
    paused_dirs = paused_dirs if isinstance(paused_dirs, dict) else {}
    raw_sessions = stats.get("active_sessions")
    sessions = (
        [
            s
            for s in raw_sessions
            if isinstance(s, dict)
            and isinstance(s.get("session_key"), str)
            and s["session_key"].strip()
        ]
        if isinstance(raw_sessions, list)
        else []
    )
    glyph = (
        "○"
        if not available
        else (
            "☾"
            if globally_paused
            else (
                "◐"
                if (paused_dirs or any(s.get("paused") is True for s in sessions))
                else "●"
            )
        )
    )
    label = f"{glyph} {selected.name} ({selected.runtime}) [{index + 1}]"
    global_label = f"{glyph} Daemon (global)" + (
        _pause_duration(stats.get("pause_remaining_seconds")) if globally_paused else ""
    )
    scopes = {
        "global": [PauseOption("global", "", global_label, globally_paused, available)],
        "dir": [],
        "session": [],
    }
    projects = stats.get("active_project_dirs")
    projects = projects if isinstance(projects, list) else []
    directories = sorted(
        {
            p
            for p in [
                *projects,
                *paused_dirs,
                *(s.get("project_dir") for s in sessions),
            ]
            if isinstance(p, str) and p.strip()
        }
    )
    for directory in directories:
        own_pause = directory in paused_dirs
        partial = any(
            s.get("paused") is True and s.get("project_dir") == directory
            for s in sessions
        )
        state = "☾" if globally_paused or own_pause else "◐" if partial else "●"
        notes = []
        if own_pause:
            notes.append("directory pause" + _pause_duration(paused_dirs[directory]))
        if globally_paused:
            notes.append("global pause also applies")
        scopes["dir"].append(
            PauseOption(
                "dir",
                directory,
                f"{state} Project: {directory}"
                + (" — " + "; ".join(notes) if notes else ""),
                own_pause,
            )
        )
    for session in sessions:
        identity = session["session_key"]
        project = session.get("project_dir")
        project = project if isinstance(project, str) else ""
        own_pause = session.get("paused") is True
        directory_paused = project in paused_dirs
        state = "☾" if globally_paused or directory_paused or own_pause else "●"
        name = resolve_session_title(explicit=[session.get("session_title")]) or str(
            session.get("session_id") or identity
        )
        notes = (
            [
                "session pause"
                + _pause_duration(session.get("pause_remaining_seconds"), session=True)
            ]
            if own_pause
            else ["no session pause"]
        )
        if globally_paused:
            notes.append("global pause also applies")
        if directory_paused:
            notes.append("directory pause also applies")
        scopes["session"].append(
            PauseOption(
                "session",
                identity,
                f"{state} Session: {session.get('agent') or 'Hook session'}: {name}\n"
                f"Project: {project or 'unknown'} | Key: {identity}\n"
                + "; ".join(notes),
                own_pause,
                project_dir=project,
            )
        )
    for scope, empty in (
        ("dir", "No tracked project directories"),
        (
            "session",
            (
                "No active sessions with stable hook identities"
                if isinstance(raw_sessions, list)
                else "Session pause is not supported by this daemon"
            ),
        ),
    ):
        if not available or not scopes[scope]:
            scopes[scope] = [
                PauseOption(
                    scope,
                    "",
                    "○ " + (empty if available else "Daemon unavailable / offline"),
                    available=False,
                )
            ]
    if available and _same_connection(source, selected):
        source.status = "paused" if globally_paused else "running"
        if source.runtime == "ssh":
            source.stats = stats
    return DaemonView(selected, label, scopes, source)


class PauseSnapshot:
    """Displayed row allowlist bound to exact connections and control identities."""

    def __init__(self, tray, client=None, *, generation=0):
        self.tray = tray
        self.client = client or tray._multi_client or MultiDaemonClient()
        self.views = [
            _read_view(tray, self.client, target, index)
            for index, target in enumerate(tuple(tray._targets))
        ]
        self.rows = {}
        self._tokens = {}
        for view in self.views:
            for options in view.scopes.values():
                for option in options:
                    token = f"{generation}:{len(self.rows)}"
                    self.rows[token] = view, option
                    self._tokens[id(option)] = token

    def payload(self, feedback=""):
        """Only inert display values cross the child/browser boundary."""
        rows = []

        def append(view, option, level):
            rows.append(
                {
                    "id": self._tokens[id(option)],
                    "scope": option.scope,
                    "label": (
                        view.label + "\n" + option.label if level == 0 else option.label
                    ),
                    "level": level,
                    "available": option.available,
                    "action": "Resume" if option.paused else "Pause",
                }
            )

        for view in self.views:
            append(view, view.scopes["global"][0], 0)
            projects, sessions = view.scopes["dir"], view.scopes["session"]
            for project in projects:
                append(view, project, 1)
                for session in sessions:
                    if project.identity and session.project_dir == project.identity:
                        append(view, session, 2)
            for session in sessions:
                if not any(
                    p.identity and p.identity == session.project_dir for p in projects
                ):
                    append(view, session, 1)
        return {
            "message": MESSAGE,
            "legend": LEGEND,
            "rows": rows,
            "durations": DURATIONS,
            "feedback": feedback,
            "session_lifetime": "Individual-session pauses also end on SessionEnd, inactivity expiry or daemon restart.",
        }

    def resolve(self, event):
        selected = self.rows.get(event.get("row"))
        if selected is None:
            raise ValueError("The selected row is no longer available.")
        view, option = selected
        action, minutes = event.get("action"), event.get("minutes")
        if not option.available or action != ("Resume" if option.paused else "Pause"):
            raise ValueError("The selected pause action is unavailable.")
        if action == "Pause" and (
            type(minutes) is not int or minutes not in DURATIONS.values()
        ):
            raise ValueError("Choose a pause duration.")
        return view, option, action, minutes if action == "Pause" else None

    def request(self, view, option, action, minutes):
        """Recheck the displayed connection and identity without widening scope."""
        if not any(
            (current is view.source or _has_route(view.target))
            and _same_connection(current, view.target)
            for current in self.tray._targets
        ):
            _refresh_tray(self.tray)
            return "The selected daemon connection changed or was removed. Refresh status; no request was sent."
        current = _read_view(self.tray, self.client, view.target, 0).find(
            option.scope, option.identity
        )
        if current is None or current.paused != option.paused:
            _refresh_tray(self.tray)
            return "The selected target or pause state changed. Refresh status; no request was sent."
        try:
            verb = action.lower()
            send = getattr(
                self.client,
                f"send_{verb}"
                + ("" if option.scope == "global" else f"_{option.scope}"),
            )
            args = (
                (view.target,)
                if option.scope == "global"
                else (view.target, option.identity)
            )
            confirmed = send(*args, minutes) if action == "Pause" else send(*args)
            after = _read_view(self.tray, self.client, view.target, 0).find(
                option.scope, option.identity
            )
            confirmed = bool(
                confirmed and after is not None and after.paused == (action == "Pause")
            )
        except Exception as exc:
            logger.warning("Pause control request failed (%s)", type(exc).__name__)
            confirmed = False
        finally:
            _refresh_tray(self.tray)
        return (
            f"{action} request confirmed. Status refreshed."
            if confirmed
            else UNCONFIRMED
        )


def open_pause_controls(tray, *, screen_bounds=None):
    """Keep the entire inline interaction in one isolated provider/window."""
    from ai_guardian.ui.pause_controls import run_pause_provider

    def show(provider):
        generation = 0
        snapshot = PauseSnapshot(tray, generation=generation)

        def respond(event):
            nonlocal snapshot, generation
            if event.get("action") == "Refresh status":
                _refresh_tray(tray)
                feedback = "Status refreshed. No pause state was changed."
            else:
                try:
                    selection = snapshot.resolve(event)
                except (ValueError, TypeError):
                    feedback = "This row or action is unavailable. Status refreshed; no request was sent."
                else:
                    feedback = snapshot.request(*selection)
            generation += 1
            snapshot = PauseSnapshot(tray, generation=generation)
            return snapshot.payload(feedback)

        return run_pause_provider(
            provider, snapshot.payload(), respond, screen_bounds=screen_bounds
        )

    return run_modal(
        "form",
        {"tkinter": lambda: show("tkinter"), "nicegui": lambda: show("nicegui")},
        fallback=None,
        screen_bounds=screen_bounds,
    )
