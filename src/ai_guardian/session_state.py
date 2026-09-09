"""
Session state management for cross-invocation tracking.

Provides a unified interface for tracking per-session state across
hook invocations, supporting both daemon mode (in-memory) and local
mode (file-based). Used for security rule injection tracking (#584).
"""

try:
    import fcntl

    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
import json
import logging
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Optional

from ai_guardian.config.utils import get_state_dir

logger = logging.getLogger(__name__)

SESSION_TTL = 86400  # 24 hours
STATE_FILENAME = "session_state.json"


def derive_session_key(hook_data: dict) -> str:
    """Derive a session key from hook data.

    Priority:
    1. session_id (Claude Code provides this)
    2. transcript_path (fallback for older versions)
    3. cwd + 30-minute time bucket (last resort)

    Agents using protojson camelCase payloads (Antigravity) are read from
    their equivalent keys, so distinct sessions never collapse onto the
    time-bucket fallback.
    """
    key = hook_data.get("session_id") or hook_data.get("conversationId")
    if key:
        return key
    key = hook_data.get("transcript_path") or hook_data.get("transcriptPath")
    if key:
        return key
    return f"{os.getcwd()}:{int(time.time() // 1800)}"


class SessionStateManager:
    """Manage per-session state across hook invocations.

    Daemon mode: delegates to DaemonState in-memory store (zero I/O).
    Local mode: uses file-based tracking with secure permissions.
    """

    def __init__(self, daemon_state=None):
        self._daemon_state = daemon_state
        self._state_file: Optional[Path] = None

        if not daemon_state:
            state_dir = get_state_dir()
            state_dir.mkdir(parents=True, exist_ok=True)
            self._state_file = state_dir / STATE_FILENAME

    def should_inject_security(self, session_key: str) -> bool:
        """Check whether security rules should be injected for this session.

        Returns True if:
        - Security has never been injected for this session (first prompt)
        - Session is flagged for re-injection (after a block)
        """
        if not session_key:
            return True

        if self._daemon_state:
            return self._daemon_state.should_inject_security(session_key)

        return self._should_inject_from_file(session_key)

    def mark_security_injected(self, session_key: str) -> None:
        """Mark that security rules have been injected for this session."""
        if not session_key:
            return

        if self._daemon_state:
            self._daemon_state.mark_security_injected(session_key)
            return

        self._update_file(session_key, injected=True, reinject=False)

    def mark_security_reinject(self, session_key: str) -> None:
        """Flag session for security re-injection on next prompt."""
        if not session_key:
            return

        if self._daemon_state:
            self._daemon_state.mark_security_reinject(session_key)
            return

        self._update_file(session_key, reinject=True)

    def has_reinject_pending(self, session_key: str) -> bool:
        """Check if a block-triggered re-injection is pending (but NOT first-prompt injection).

        Used by inject_trigger=after_block_only to skip first-prompt injection.
        """
        if not session_key:
            return False

        if self._daemon_state:
            return self._daemon_state.has_reinject_pending(session_key)

        data = self._read_file()
        if not data:
            return False
        sessions = data.get("sessions", {})
        entry = sessions.get(session_key)
        if entry is None:
            return False
        return bool(entry.get("security_reinject", False))

    def cleanup_session(self, session_key: str) -> None:
        """Remove a session from injection tracking.

        Called on session end to finalize session state.
        """
        if not session_key:
            return

        if self._daemon_state:
            self._daemon_state.cleanup_session_state(session_key)
            return

        if not self._state_file:
            return

        lock_path = str(self._state_file) + ".lock"
        try:
            lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
            try:
                if HAS_FCNTL:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)

                data = self._read_file()
                if data and session_key in data.get("sessions", {}):
                    del data["sessions"][session_key]
                    self._write_file(data)
                    logger.debug(
                        f"Session cleanup: removed state for {session_key[:16]}..."
                    )
            finally:
                if HAS_FCNTL:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
        except OSError as e:
            logger.debug(f"Session state cleanup failed: {e}")

    def _should_inject_from_file(self, session_key: str) -> bool:
        data = self._read_file()
        if not data:
            return True
        sessions = data.get("sessions", {})
        entry = sessions.get(session_key)
        if entry is None:
            return True
        if entry.get("security_reinject", False):
            return True
        return not entry.get("security_injected", False)

    def _update_file(
        self,
        session_key: str,
        injected: Optional[bool] = None,
        reinject: Optional[bool] = None,
    ) -> None:
        if not self._state_file:
            return

        lock_path = str(self._state_file) + ".lock"
        try:
            lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
            try:
                if HAS_FCNTL:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)

                data = self._read_file() or {"sessions": {}}
                sessions = data.setdefault("sessions", {})

                # Auto-prune sessions older than 24h
                now = time.time()
                expired = [
                    k
                    for k, v in sessions.items()
                    if now - v.get("last_activity", 0) > SESSION_TTL
                ]
                for k in expired:
                    del sessions[k]

                entry = sessions.setdefault(session_key, {})
                entry["last_activity"] = now
                if injected is not None:
                    entry["security_injected"] = injected
                if reinject is not None:
                    entry["security_reinject"] = reinject

                self._write_file(data)
            finally:
                if HAS_FCNTL:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
        except OSError as e:
            logger.debug(f"Session state file update failed: {e}")

    def _read_file(self) -> Optional[dict]:
        if not self._state_file or not self._state_file.exists():
            return None
        try:
            content = self._state_file.read_text(encoding="utf-8")
            if not content.strip():
                return None
            return json.loads(content)
        except (json.JSONDecodeError, OSError) as e:
            logger.debug(f"Error reading session state: {e}")
            return None

    def _write_file(self, data: dict) -> None:
        if not self._state_file:
            return
        try:
            content = json.dumps(data)
            parent = self._state_file.parent
            fd, tmp_path = tempfile.mkstemp(
                dir=str(parent), prefix=".sess-", suffix=".tmp"
            )
            closed = False
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
                os.write(fd, content.encode("utf-8"))
                os.close(fd)
                closed = True
                os.replace(tmp_path, str(self._state_file))
            except BaseException:
                if not closed:
                    os.close(fd)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
        except OSError as e:
            logger.debug(f"Error writing session state: {e}")
