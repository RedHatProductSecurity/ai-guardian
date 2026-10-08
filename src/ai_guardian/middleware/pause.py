"""Pause state shared by the daemon and standalone middleware runtimes.

The daemon owns ``daemon.paused``.  A standalone middleware instance owns
``middleware.paused``.  Both files use wall-clock expiry so that a control
decision survives a process restart and can be observed by another process.
The middleware checks the daemon response as well, which also covers a
separately hosted daemon that cannot share the local state directory.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

MAX_MIDDLEWARE_PAUSE_MINUTES = 1440
MIDDLEWARE_PAUSE_FILENAME = "middleware.paused"


class MiddlewarePauseStateError(RuntimeError):
    """Raised when an operator-managed middleware pause file is invalid."""


@dataclass(frozen=True)
class MiddlewarePauseStatus:
    """Effective pause state for one middleware scope."""

    paused: bool = False
    source: str = "none"
    scope: Optional[str] = None
    project_dir: Optional[str] = None
    remaining_seconds: float = 0.0
    until: Optional[float] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe diagnostic representation."""

        result: Dict[str, Any] = {
            "paused": self.paused,
            "source": self.source,
            "remaining_seconds": round(max(0.0, self.remaining_seconds), 3),
        }
        if self.scope is not None:
            result["scope"] = self.scope
        if self.project_dir is not None:
            result["project_dir"] = self.project_dir
        if self.until is not None and self.until > 0:
            result["until"] = self.until
        if self.reason:
            result["reason"] = self.reason
        return result


def normalize_project_dir(project_dir: Optional[str]) -> Optional[str]:
    """Normalize a configured project scope without inventing one."""

    if not project_dir:
        return None
    return os.path.realpath(os.path.expanduser(project_dir))


def default_daemon_pause_path() -> Path:
    """Return the daemon pause file used for shared local control."""

    from ai_guardian.daemon import get_state_dir

    return get_state_dir() / "daemon.paused"


def default_middleware_pause_path() -> Path:
    """Return the standalone middleware pause file."""

    configured = os.environ.get("AI_GUARDIAN_MIDDLEWARE_PAUSE_FILE")
    if configured:
        return Path(configured).expanduser()
    from ai_guardian.daemon import get_state_dir

    return get_state_dir() / MIDDLEWARE_PAUSE_FILENAME


def _coerce_until(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _entry_status(
    entry: Any,
    *,
    source: str,
    scope: str,
    project_dir: Optional[str],
    now: float,
) -> MiddlewarePauseStatus:
    if not isinstance(entry, Mapping) or not entry.get("paused"):
        return MiddlewarePauseStatus()
    until = _coerce_until(entry.get("until"))
    if until > 0 and now >= until:
        return MiddlewarePauseStatus()
    remaining = max(0.0, until - now) if until > 0 else 0.0
    reason = entry.get("reason")
    return MiddlewarePauseStatus(
        paused=True,
        source=source,
        scope=scope,
        project_dir=project_dir,
        remaining_seconds=remaining,
        until=until if until > 0 else None,
        reason=str(reason) if reason else None,
    )


def _status_from_document(
    document: Mapping[str, Any],
    *,
    source: str,
    project_dir: Optional[str],
    now: Optional[float] = None,
) -> MiddlewarePauseStatus:
    """Read global/project entries from either daemon or middleware format."""

    current_time = time.time() if now is None else now
    global_status = _entry_status(
        document.get("global"),
        source=source,
        scope="global",
        project_dir=None,
        now=current_time,
    )
    if global_status.paused:
        return global_status

    if project_dir:
        projects = document.get("projects")
        if not isinstance(projects, Mapping):
            # The daemon calls this collection ``dirs`` for historical
            # compatibility.  Accept both shapes for cross-process reads.
            projects = document.get("dirs")
        if isinstance(projects, Mapping):
            project_status = _entry_status(
                projects.get(project_dir),
                source=source,
                scope="project",
                project_dir=project_dir,
                now=current_time,
            )
            if project_status.paused:
                return project_status
    return MiddlewarePauseStatus()


def _read_document(
    path: Path,
    *,
    source: str,
    project_dir: Optional[str],
    fail_closed: bool,
) -> MiddlewarePauseStatus:
    if not path.exists():
        return MiddlewarePauseStatus()
    try:
        raw = path.read_text(encoding="utf-8")
        document = json.loads(raw)
        if not isinstance(document, Mapping):
            raise ValueError("pause state must contain a JSON object")
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Unable to read %s pause state %s: %s", source, path, exc)
        if fail_closed:
            return MiddlewarePauseStatus(
                paused=True,
                source=source,
                scope="global",
                remaining_seconds=0.0,
                reason="middleware_pause_state_unavailable",
            )
        return MiddlewarePauseStatus()
    return _status_from_document(document, source=source, project_dir=project_dir)


def effective_pause_status(
    project_dir: Optional[str] = None,
    *,
    daemon_pause_file: Optional[Path] = None,
    middleware_pause_file: Optional[Path] = None,
) -> MiddlewarePauseStatus:
    """Return the effective pause, preferring daemon control over local state.

    A global daemon pause applies to every middleware instance.  A project
    daemon pause applies only when the instance was started with that project
    scope.  Standalone middleware state is evaluated only after daemon state,
    so resuming a local instance cannot accidentally override a paused daemon.
    """

    normalized_project = normalize_project_dir(project_dir)
    daemon_status = _read_document(
        Path(daemon_pause_file or default_daemon_pause_path()),
        source="daemon",
        project_dir=normalized_project,
        fail_closed=True,
    )
    if daemon_status.paused:
        return daemon_status
    return _read_document(
        Path(middleware_pause_file or default_middleware_pause_path()),
        source="middleware",
        project_dir=normalized_project,
        fail_closed=True,
    )


class MiddlewarePauseStore:
    """Persist and query the standalone middleware pause control state."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path or default_middleware_pause_path()).expanduser()

    def status(self, project_dir: Optional[str] = None) -> MiddlewarePauseStatus:
        """Return only the local middleware state from this store."""

        normalized_project = normalize_project_dir(project_dir)
        if not self.path.exists():
            return MiddlewarePauseStatus()
        try:
            document = self._load()
        except MiddlewarePauseStateError as exc:
            logger.warning(
                "Unable to read middleware pause state %s: %s", self.path, exc
            )
            return MiddlewarePauseStatus(
                paused=True,
                source="middleware",
                scope="global",
                reason="middleware_pause_state_unavailable",
            )
        return _status_from_document(
            document,
            source="middleware",
            project_dir=normalized_project,
        )

    def pause(
        self,
        minutes: float = 0,
        *,
        project_dir: Optional[str] = None,
        reason: str = "operator",
    ) -> MiddlewarePauseStatus:
        """Pause the global or configured project middleware scope."""

        duration = self._validate_minutes(minutes)
        normalized_project = normalize_project_dir(project_dir)
        document = self._load_for_update()
        entry = {
            "paused": True,
            "until": time.time() + duration * 60 if duration > 0 else 0.0,
            "reason": reason,
        }
        if normalized_project:
            projects = document.setdefault("projects", {})
            if not isinstance(projects, dict):
                raise MiddlewarePauseStateError(
                    "projects pause state must be an object"
                )
            projects[normalized_project] = entry
        else:
            document["global"] = entry
        document["version"] = 1
        self._write(document)
        return self.status(normalized_project)

    def resume(self, *, project_dir: Optional[str] = None) -> MiddlewarePauseStatus:
        """Resume the global or configured project middleware scope idempotently."""

        normalized_project = normalize_project_dir(project_dir)
        document = self._load_for_update()
        if normalized_project:
            projects = document.get("projects")
            if isinstance(projects, dict):
                projects.pop(normalized_project, None)
                if not projects:
                    document.pop("projects", None)
        else:
            document.pop("global", None)
        document["version"] = 1
        if document.get("global") or document.get("projects"):
            self._write(document)
        else:
            try:
                self.path.unlink(missing_ok=True)
            except OSError as exc:
                raise MiddlewarePauseStateError(
                    f"unable to remove middleware pause state {self.path}: {exc}"
                ) from exc
        return self.status(normalized_project)

    def _load_for_update(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"version": 1}
        return self._load()

    def _load(self) -> Dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MiddlewarePauseStateError(str(exc)) from exc
        if not isinstance(value, dict):
            raise MiddlewarePauseStateError("pause state must contain a JSON object")
        return value

    def _write(self, document: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=str(self.path.parent), text=True
        )
        try:
            try:
                os.chmod(temporary_name, 0o600)
            except OSError:
                logger.warning(
                    "Unable to restrict middleware pause state: %s", self.path
                )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(document, handle, sort_keys=True)
                handle.write("\n")
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass  # intentionally silent — cleanup best-effort
            raise

    @staticmethod
    def _validate_minutes(minutes: float) -> float:
        if isinstance(minutes, bool):
            raise ValueError("minutes must be a number between 0 and 1440")
        try:
            duration = float(minutes)
        except (TypeError, ValueError) as exc:
            raise ValueError("minutes must be a number between 0 and 1440") from exc
        if (
            not math.isfinite(duration)
            or duration < 0
            or duration > MAX_MIDDLEWARE_PAUSE_MINUTES
        ):
            raise ValueError("minutes must be a number between 0 and 1440")
        return duration


__all__ = [
    "MAX_MIDDLEWARE_PAUSE_MINUTES",
    "MIDDLEWARE_PAUSE_FILENAME",
    "MiddlewarePauseStateError",
    "MiddlewarePauseStatus",
    "MiddlewarePauseStore",
    "default_daemon_pause_path",
    "default_middleware_pause_path",
    "effective_pause_status",
    "normalize_project_dir",
]
