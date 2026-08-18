"""
Thread-safe in-memory state for the daemon process.

Manages cross-hook correlation contexts, config caching with auto-reload,
compiled regex pattern caching, and activity tracking for idle timeout.
"""

import hashlib
import json
import logging
import os
import re
import stat
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ai_guardian.config.loaders import _clear_config_cache
from ai_guardian.config.utils import get_config_dir, get_state_dir, _find_config_in_dir

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_TTL = 300.0  # 5 minutes
DEFAULT_IDLE_TIMEOUT = 0.0  # disabled — daemon runs until explicit stop or crash
CONFIG_CHECKSUM_INTERVAL = 60.0  # check checksum every 60s
SESSION_TTL = 86400  # 24 hours
PROJECT_CONFIG_TTL = 86400  # 24 hours — prune stale project entries
PERSIST_DEBOUNCE = 2.0  # seconds before writing to disk
DAEMON_SESSIONS_FILENAME = "daemon_sessions.json"
DAEMON_PAUSE_FILENAME = "daemon.paused"

DEFAULT_TRAY_REGISTRATION_TTL = 120.0  # seconds


@dataclass
class PendingPrompt:
    """Ask prompt queued for host tray pickup (#1342)."""

    prompt_id: str
    violation: dict
    fallback_action: str
    timeout_seconds: int
    created_at: float
    decision_event: threading.Event = field(default_factory=threading.Event)
    result: Optional[dict] = None


class DaemonState:
    """Thread-safe in-memory state for the daemon process."""

    def __init__(
        self,
        config_path=None,
        idle_timeout=DEFAULT_IDLE_TIMEOUT,
        context_ttl=DEFAULT_CONTEXT_TTL,
        sessions_file=None,
        pause_file=None,
    ):
        self._lock = threading.Lock()

        # Source file mtime tracking for dev-mode auto-restart (#1223)
        self._source_mtime = 0.0

        # Cross-hook correlation: "session_id:tool_use_id" -> PreToolUse data
        self._hook_contexts = {}
        self._context_ttl = context_ttl

        # Compiled regex cache: pattern_string -> re.Pattern
        self._compiled_patterns = {}

        # Config caching
        self._config = None
        self._config_path = config_path or self._default_config_path()
        self._config_mtime = 0.0
        self._config_checksum = ""
        self._last_checksum_check = 0.0

        # Activity tracking
        self._last_activity = time.monotonic()
        self._idle_timeout = idle_timeout

        # Stats
        self._request_count = 0
        self._blocked_count = 0
        self._warning_count = 0
        self._log_only_count = 0
        self._started_at = time.time()

        # Severity tracking (blocked=critical, warning=warning)
        self._critical_count = 0
        self._warning_severity_count = 0

        # Ask dialog tracking (#1159)
        self._ask_dialog_count = 0
        self._ask_dialog_total_ms = 0.0

        # Last block tracking
        self._last_block_type = None
        self._last_block_time = None  # monotonic timestamp

        # Paused state (for tray Pause/Resume)
        self._paused = False
        self._paused_until = 0.0  # monotonic timestamp, 0 = not time-limited

        # Per-directory pause (#958)
        self._paused_dirs = {}  # project_dir -> monotonic timestamp (0 = indefinite)

        # Config reload tracking (#610)
        self._last_config_reload_at = None  # unix timestamp

        # Project config tracking (#617)
        self._project_config_mtimes = {}  # project_dir -> mtime
        self._project_config_paths = {}  # project_dir -> config_path str
        self._project_dir_last_seen = {}  # project_dir -> monotonic timestamp
        self._last_project_config_reload_at = None  # unix timestamp

        # Config error tracking (#742)
        self._config_error = None  # error message string or None

        # Security injection tracking (#584)
        self._security_injected_sessions = set()
        self._security_reinject_sessions = set()

        # Allowed transcript findings (#1364) — prevents re-alerting on
        # secrets/PII that were allowed via ask dialog
        self._allowed_findings = {}  # session_id -> set of fingerprints

        # Tray registration for remote ask forwarding (#1342)
        self._registered_tray = None  # {"host", "port", "registered_at"}
        self._tray_registration_ttl = DEFAULT_TRAY_REGISTRATION_TTL

        # Pending ask prompts waiting for host tray decision (#1342)
        self._pending_prompts = {}  # prompt_id -> PendingPrompt
        self._pending_prompts_lock = threading.Lock()
        self._prompt_counter = 0

        # Pushed traces from container SDK (#1951)
        self._pushed_traces = {}  # filename -> trace_doc dict
        self._pushed_traces_lock = threading.Lock()

        # Pause state persistence (#1319)
        self._pause_file = pause_file or self._default_pause_path()

        # Session persistence (#592)
        self._sessions_file = sessions_file or self._default_sessions_path()
        self._session_last_activity = {}  # session_key -> unix timestamp
        self._sessions_dirty = False
        self._debounce_timer = None

        # MCP installed detection (#756)
        self._mcp_installed = self._check_mcp_installed()

        # Bootstrap session tracking (#1394) — in-memory only, flushed on restart
        self._seen_sessions: set = set()

        # OTEL hook emitters (#1998) — per-session, flushed on SessionEnd
        self._otel_emitters = {}  # session_id -> HookOtelEmitter

        # State change observers (#650) — push notifications to subscribers
        self._state_observers = []
        self._state_observers_lock = threading.Lock()

        # Listen mode manager (#1590) — persistent leaktk process
        self._listen_manager = None

        # ML engine manager (#185) — lazy-loaded on first ml_detect request
        self._ml_engine_manager = None
        self._ml_load_attempted = False
        self._ml_load_error = None
        self._ml_load_event = threading.Event()

        # Initial config load
        self._reload_config()

        # Load persisted session state
        self._load_sessions()

        # Restore pause state from disk (#1319)
        self._load_pause_state()

    @staticmethod
    def _default_config_path():
        return get_config_dir() / "ai-guardian.json"

    @staticmethod
    def _default_sessions_path():
        return get_state_dir() / DAEMON_SESSIONS_FILENAME

    @staticmethod
    def _default_pause_path():
        return get_state_dir() / DAEMON_PAUSE_FILENAME

    # --- Cross-hook correlation ---

    def store_pretooluse_context(self, session_id, tool_use_id, context):
        """Store PreToolUse context for later PostToolUse correlation.

        Args:
            session_id: IDE session identifier
            tool_use_id: Tool use identifier
            context: Dict with PreToolUse scan results and metadata
        """
        if not session_id or not tool_use_id:
            return
        key = f"{session_id}:{tool_use_id}"
        with self._lock:
            self._hook_contexts[key] = {
                "context": context,
                "timestamp": time.monotonic(),
            }

    def get_pretooluse_context(self, session_id, tool_use_id):
        """Retrieve PreToolUse context for PostToolUse correlation.

        Args:
            session_id: IDE session identifier
            tool_use_id: Tool use identifier

        Returns:
            dict or None: PreToolUse context if found and not expired
        """
        if not session_id or not tool_use_id:
            return None
        key = f"{session_id}:{tool_use_id}"
        with self._lock:
            entry = self._hook_contexts.get(key)
            if entry is None:
                return None
            age = time.monotonic() - entry["timestamp"]
            if age > self._context_ttl:
                del self._hook_contexts[key]
                return None
            return entry["context"]

    def cleanup_expired_contexts(self):
        """Remove expired cross-hook correlation entries and stale project configs."""
        now = time.monotonic()
        with self._lock:
            expired = [
                k
                for k, v in self._hook_contexts.items()
                if now - v["timestamp"] > self._context_ttl
            ]
            for key in expired:
                del self._hook_contexts[key]
            if expired:
                logger.debug(f"Cleaned up {len(expired)} expired hook contexts")
        self._cleanup_stale_project_configs()
        self.cleanup_expired_prompts()

    def cleanup_session_contexts(self, session_id):
        """Remove all hook contexts for a specific session.

        Called on session end to clean up accumulated PreToolUse contexts.

        Returns:
            int: Number of contexts removed
        """
        if not session_id:
            return 0
        prefix = f"{session_id}:"
        with self._lock:
            keys_to_remove = [k for k in self._hook_contexts if k.startswith(prefix)]
            for key in keys_to_remove:
                del self._hook_contexts[key]
            if keys_to_remove:
                logger.debug(
                    f"Cleaned up {len(keys_to_remove)} contexts for session {session_id[:16]}..."
                )
            return len(keys_to_remove)

    def is_new_session(self, session_id: str, cwd: str) -> bool:
        """Detect a new session and register it for bootstrap scanning.

        Uses session_id as key; falls back to f"cwd:{cwd}" for IDEs without
        a session_id. In-memory only — flushed on daemon restart so each new
        daemon start re-scans config files.

        Returns True the first time this session is seen, False thereafter.
        """
        key = session_id if session_id else f"cwd:{cwd}"
        with self._lock:
            if key in self._seen_sessions:
                return False
            self._seen_sessions.add(key)
            return True

    def cleanup_session_state(self, session_key):
        """Remove a session from security injection tracking.

        Called on session end to finalize session state.
        """
        if not session_key:
            return
        with self._lock:
            self._security_injected_sessions.discard(session_key)
            self._security_reinject_sessions.discard(session_key)
            self._session_last_activity.pop(session_key, None)
            self._allowed_findings.pop(session_key, None)
        self._schedule_persist()

    # --- OTEL hook emitters (#1998) ---

    _OTEL_DISABLED = object()

    def get_otel_emitter(self, session_id):
        """Get or create an OTEL emitter for a session.

        Returns None if OTEL is not enabled.
        """
        if not session_id:
            return None
        with self._lock:
            cached = self._otel_emitters.get(session_id)
            if cached is self._OTEL_DISABLED:
                return None
            if cached is not None:
                return cached
        try:
            from ai_guardian.config.loaders import _load_otel_config
            from ai_guardian.scanners.otel_exporter import HookOtelEmitter

            config = _load_otel_config()
            emitter = HookOtelEmitter(config)
            if not emitter.enabled:
                with self._lock:
                    self._otel_emitters.setdefault(session_id, self._OTEL_DISABLED)
                return None
            with self._lock:
                if session_id not in self._otel_emitters:
                    self._otel_emitters[session_id] = emitter
                return self._otel_emitters[session_id]
        except Exception:
            logger.debug("Failed to create OTEL emitter", exc_info=True)
            return None

    def flush_otel_emitter(self, session_id, *, adapter_name=None, token_usage=None):
        """Flush and remove the OTEL emitter for a session."""
        if not session_id:
            return
        with self._lock:
            emitter = self._otel_emitters.pop(session_id, None)
        if emitter is not None and emitter is not self._OTEL_DISABLED:
            try:
                emitter.flush(
                    session_id=session_id,
                    adapter_name=adapter_name,
                    token_usage=token_usage,
                )
            except Exception:
                logger.debug("OTEL session flush failed", exc_info=True)

    # --- Allowed transcript findings (#1364) ---

    def add_allowed_finding(self, session_id, fingerprint):
        """Record an allowed finding to suppress transcript scanner re-alerts.

        Args:
            session_id: IDE session identifier
            fingerprint: Finding fingerprint (from _finding_fingerprint())
        """
        if not session_id or not fingerprint:
            return
        with self._lock:
            if session_id not in self._allowed_findings:
                self._allowed_findings[session_id] = set()
            self._allowed_findings[session_id].add(fingerprint)

    def get_allowed_findings(self, session_id):
        """Return set of allowed finding fingerprints for a session.

        Args:
            session_id: IDE session identifier

        Returns:
            Set of fingerprint strings (copy, safe for concurrent use).
        """
        if not session_id:
            return set()
        with self._lock:
            return set(self._allowed_findings.get(session_id, ()))

    # --- Tray registration & prompt queue (#1342) ---

    def register_tray(self, host, port):
        """Register a host tray for ask dialog forwarding."""
        with self._lock:
            self._registered_tray = {
                "host": host,
                "port": int(port),
                "registered_at": time.monotonic(),
            }
        logger.info("Tray registered: %s:%s", host, port)

    def unregister_tray(self):
        """Clear tray registration."""
        with self._lock:
            self._registered_tray = None
        logger.info("Tray unregistered")

    def is_tray_registered(self):
        """Check if a host tray is registered and TTL has not expired."""
        with self._lock:
            if self._registered_tray is None:
                return False
            age = time.monotonic() - self._registered_tray["registered_at"]
            if age > self._tray_registration_ttl:
                self._registered_tray = None
                return False
            return True

    # --- State change observers (#650) ---

    def add_state_observer(self, callback):
        """Register a callback invoked on state changes.

        Callback signature: (event_type: str, data: dict). Must be non-blocking.
        """
        with self._state_observers_lock:
            self._state_observers.append(callback)

    def remove_state_observer(self, callback):
        """Unregister a state observer."""
        with self._state_observers_lock:
            try:
                self._state_observers.remove(callback)
            except ValueError:
                pass

    def _notify_state_changed(self, event_type, data=None):
        """Fire all registered state observers. Best-effort, non-blocking."""
        with self._state_observers_lock:
            observers = list(self._state_observers)
        for cb in observers:
            try:
                cb(event_type, data or {})
            except Exception as e:
                logger.debug("State observer error: %s", e)

    def queue_prompt(self, violation_dict, fallback_action, timeout_seconds):
        """Queue an ask prompt for host tray pickup.

        Returns a PendingPrompt whose decision_event the caller should wait on.
        """
        with self._pending_prompts_lock:
            self._prompt_counter += 1
            prompt_id = f"prompt-{self._prompt_counter}"
            pending = PendingPrompt(
                prompt_id=prompt_id,
                violation=violation_dict,
                fallback_action=fallback_action,
                timeout_seconds=timeout_seconds,
                created_at=time.monotonic(),
            )
            self._pending_prompts[prompt_id] = pending
        logger.info("Queued ask prompt %s for tray pickup", prompt_id)
        return pending

    def get_pending_prompts(self):
        """Return list of pending prompts that are not yet resolved or expired."""
        now = time.monotonic()
        result = []
        with self._pending_prompts_lock:
            for p in self._pending_prompts.values():
                if p.result is not None:
                    continue
                if now - p.created_at > p.timeout_seconds:
                    continue
                result.append(
                    {
                        "prompt_id": p.prompt_id,
                        "violation": p.violation,
                        "fallback_action": p.fallback_action,
                        "timeout_seconds": p.timeout_seconds,
                        "age_seconds": round(now - p.created_at, 1),
                    }
                )
        return result

    def resolve_prompt(self, prompt_id, decision_dict):
        """Deliver a tray decision for a pending prompt.

        Returns True if the prompt was found and resolved.
        """
        with self._pending_prompts_lock:
            pending = self._pending_prompts.get(prompt_id)
            if pending is None or pending.result is not None:
                return False
            pending.result = decision_dict
            pending.decision_event.set()
        logger.info("Resolved prompt %s: %s", prompt_id, decision_dict.get("decision"))
        return True

    def cleanup_expired_prompts(self):
        """Remove expired pending prompts and unblock their waiting threads."""
        now = time.monotonic()
        with self._pending_prompts_lock:
            expired = [
                pid
                for pid, p in self._pending_prompts.items()
                if now - p.created_at > p.timeout_seconds
            ]
            for pid in expired:
                prompt = self._pending_prompts.pop(pid)
                prompt.decision_event.set()
            if expired:
                logger.debug("Cleaned up %d expired pending prompts", len(expired))

    # --- Pushed traces for container SDK (#1951) ---

    def store_pushed_trace(self, filename, trace_doc):
        """Store a trace document pushed via POST /api/traces."""
        with self._pushed_traces_lock:
            self._pushed_traces[filename] = trace_doc

    def get_pushed_traces(self):
        """Return a copy of all pushed traces."""
        with self._pushed_traces_lock:
            return dict(self._pushed_traces)

    def get_pushed_trace(self, filename):
        """Return a specific pushed trace by filename."""
        with self._pushed_traces_lock:
            return self._pushed_traces.get(filename)

    def remove_pushed_traces(self, filenames):
        """Remove pushed traces by filename."""
        with self._pushed_traces_lock:
            for fn in filenames:
                self._pushed_traces.pop(fn, None)

    # --- Security injection tracking (#584) ---

    def should_inject_security(self, session_key):
        """Check if security rules should be injected for this session.

        Returns True on first prompt or if re-injection is flagged.
        """
        if not session_key:
            return True
        with self._lock:
            if session_key in self._security_reinject_sessions:
                return True
            return session_key not in self._security_injected_sessions

    def mark_security_injected(self, session_key):
        """Mark that security rules have been injected for this session."""
        if not session_key:
            return
        with self._lock:
            self._security_injected_sessions.add(session_key)
            self._security_reinject_sessions.discard(session_key)
            self._session_last_activity[session_key] = time.time()
        self._schedule_persist()

    def mark_security_reinject(self, session_key):
        """Flag session for security re-injection on next prompt."""
        if not session_key:
            return
        with self._lock:
            self._security_reinject_sessions.add(session_key)
            self._session_last_activity[session_key] = time.time()
        self._schedule_persist()

    def has_reinject_pending(self, session_key):
        """Check if a block-triggered re-injection is pending (not first-prompt).

        Used by inject_trigger=after_block_only.
        """
        if not session_key:
            return False
        with self._lock:
            return session_key in self._security_reinject_sessions

    # --- Config caching with auto-reload ---

    def get_config(self):
        """Get cached config, reloading if file changed.

        Uses mtime check on every call (fast) and periodic checksum
        verification for edge cases.

        Returns:
            dict or None: Parsed config, or None if no config file
        """
        with self._lock:
            reloaded = self._reload_config() if self._check_config_reload() else False
            config = self._config
            listen_mgr = self._listen_manager if reloaded else None
        if reloaded:
            self._restart_listen_manager(listen_mgr)
            self._notify_state_changed("config_reloaded")
        return config

    def force_reload_config(self):
        """Force config reload regardless of mtime/checksum."""
        _clear_config_cache()
        with self._lock:
            reloaded = self._reload_config()
            listen_mgr = self._listen_manager if reloaded else None
            logger.info("Config force-reloaded (global + per-project caches cleared)")
        if reloaded:
            self._restart_listen_manager(listen_mgr)
            self._notify_state_changed("config_reloaded")

    def _check_config_reload(self):
        """Check if config file has changed (must be called with lock held).

        Returns:
            bool: True if config should be reloaded
        """
        try:
            if not self._config_path.exists():
                if self._config is not None:
                    logger.info("Config file removed, clearing cached config")
                    return True
                return False

            stat = os.stat(self._config_path)
            current_mtime = stat.st_mtime

            # Fast path: mtime changed
            if current_mtime != self._config_mtime:
                logger.info("Config file mtime changed, reloading")
                return True

            # Periodic checksum verification
            now = time.monotonic()
            if now - self._last_checksum_check > CONFIG_CHECKSUM_INTERVAL:
                self._last_checksum_check = now
                current_checksum = self._compute_config_checksum()
                if current_checksum != self._config_checksum:
                    logger.info("Config file checksum changed, reloading")
                    return True

            return False
        except OSError:
            return False

    def _reload_config(self):
        """Reload config from disk (must be called with lock held).

        Returns:
            bool: True if config was successfully reloaded
        """
        try:
            if not self._config_path.exists():
                self._config = None
                self._config_mtime = 0.0
                self._config_checksum = ""
                return False

            content = self._config_path.read_text(encoding="utf-8")
            self._config = json.loads(content)
            stat = os.stat(self._config_path)
            self._config_mtime = stat.st_mtime
            self._config_checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
            self._last_checksum_check = time.monotonic()

            # Invalidate compiled pattern cache on config change
            self._compiled_patterns.clear()

            self._last_config_reload_at = time.time()

            self._config_error = None
            self._mcp_installed = self._check_mcp_installed()

            logger.info(f"Config loaded from {self._config_path}")
            return True
        except (json.JSONDecodeError, OSError) as e:
            self._config_error = str(e)
            logger.error(f"Failed to reload config: {e}")
            return False

    def _compute_config_checksum(self):
        """Compute SHA256 of config file content."""
        try:
            content = self._config_path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        except OSError:
            return ""

    @staticmethod
    def _check_mcp_installed():
        """Check if ai-guardian MCP server is configured in any supported IDE."""
        from ai_guardian.daemon import is_mcp_installed

        return is_mcp_installed()

    # --- Project config tracking (#617) ---

    def check_project_config(self, project_dir):
        """Check if a project config has changed and track the reload.

        Called by the daemon server on each hook request with the client's CWD.
        Detects mtime changes on the project's ai-guardian config file and
        fires the reload callback (tray flash) when changes occur.

        Args:
            project_dir: Absolute path string of the project directory
        """
        if not project_dir:
            return

        project_dir = str(project_dir)
        config_path = _find_config_in_dir(Path(project_dir))

        with self._lock:
            self._project_dir_last_seen[project_dir] = time.monotonic()

            if not config_path:
                if project_dir not in self._project_config_paths:
                    self._project_config_paths[project_dir] = None
                return

            try:
                current_mtime = os.stat(config_path).st_mtime
            except OSError:
                return

            config_path_str = str(config_path)
            prev_mtime = self._project_config_mtimes.get(project_dir)
            prev_path = self._project_config_paths.get(project_dir)

            changed = (
                (prev_mtime is not None and current_mtime != prev_mtime)
                or (prev_path is not None and config_path_str != prev_path)
                or (prev_path is None and project_dir in self._project_config_paths)
            )

            self._project_config_mtimes[project_dir] = current_mtime
            self._project_config_paths[project_dir] = config_path_str

            if changed:
                self._last_project_config_reload_at = time.time()
                self._compiled_patterns.clear()
                logger.info(f"Project config changed: {config_path}")

        if changed:
            self._notify_state_changed("config_reloaded")

    def _cleanup_stale_project_configs(self):
        """Remove project config entries not seen for PROJECT_CONFIG_TTL.

        Also cleans stale per-project cache entries in gitleaks_config,
        aiguardignore, and config_loaders modules (#1227).
        """
        now = time.monotonic()
        with self._lock:
            stale = [
                d
                for d, last_seen in self._project_dir_last_seen.items()
                if now - last_seen > PROJECT_CONFIG_TTL
            ]
            for d in stale:
                self._project_config_mtimes.pop(d, None)
                self._project_config_paths.pop(d, None)
                self._project_dir_last_seen.pop(d, None)
            if stale:
                logger.debug(f"Pruned {len(stale)} stale project config entries")

        if stale:
            import importlib

            for mod_name in ("gitleaks_config", "aiguardignore", "config_loaders"):
                try:
                    mod = importlib.import_module(f"ai_guardian.{mod_name}")
                    mod.cleanup_stale_entries(PROJECT_CONFIG_TTL)
                except Exception:
                    pass

    # --- Compiled regex pattern cache ---

    def get_compiled_pattern(self, pattern):
        """Get a compiled regex pattern, using cache.

        Args:
            pattern: Regex pattern string

        Returns:
            re.Pattern or None: Compiled pattern, or None on invalid regex
        """
        with self._lock:
            if pattern in self._compiled_patterns:
                return self._compiled_patterns[pattern]
            try:
                compiled = re.compile(pattern)
                self._compiled_patterns[pattern] = compiled
                return compiled
            except re.error as e:
                logger.warning(f"Invalid regex pattern '{pattern}': {e}")
                return None

    # --- Activity tracking ---

    def record_activity(self):
        """Record that a request was processed (resets idle timer)."""
        with self._lock:
            self._last_activity = time.monotonic()
            self._request_count += 1

    def record_blocked(self, violation_type=None):
        """Record that a request was blocked (operation denied).

        Args:
            violation_type: Optional violation type string (e.g. 'secret_detected')
        """
        with self._lock:
            self._blocked_count += 1
            self._critical_count += 1
            if violation_type:
                self._last_block_type = violation_type
            self._last_block_time = time.monotonic()

    def record_warning(self):
        """Record that a warning was shown to the user (threat detected, allowed)."""
        with self._lock:
            self._warning_count += 1
            self._warning_severity_count += 1

    def record_log_only(self):
        """Record a silently logged violation (no user-visible message)."""
        with self._lock:
            self._log_only_count += 1

    def record_ask_dialog(self, wait_ms):
        """Record an ask dialog interaction with its wait time in milliseconds."""
        with self._lock:
            self._ask_dialog_count += 1
            self._ask_dialog_total_ms += wait_ms

    def is_idle_timeout_expired(self):
        """Check if daemon has been idle longer than the timeout.

        Returns:
            bool: True if idle timeout has expired
        """
        if self._idle_timeout <= 0:
            return False  # Disabled
        with self._lock:
            elapsed = time.monotonic() - self._last_activity
            return elapsed > self._idle_timeout

    # --- Pause/resume ---

    @property
    def paused(self):
        with self._lock:
            if not self._paused:
                return False
            # Check if time-limited pause has expired
            if self._paused_until > 0 and time.monotonic() >= self._paused_until:
                self._paused = False
                self._paused_until = 0.0
                logger.info("Pause expired, resuming")
                return False
            return True

    def pause(self, duration_minutes=0):
        """Pause all hook scanning.

        Args:
            duration_minutes: Pause duration in minutes. 0 = indefinite.
        """
        with self._lock:
            self._paused = True
            if duration_minutes > 0:
                self._paused_until = time.monotonic() + duration_minutes * 60
                logger.info(f"Daemon paused for {duration_minutes} minutes")
            else:
                self._paused_until = 0.0
                logger.info("Daemon paused indefinitely")
        self._persist_pause_state()
        self._notify_state_changed("paused", {"minutes": duration_minutes})

    def resume(self):
        """Resume hook scanning."""
        with self._lock:
            self._paused = False
            self._paused_until = 0.0
            logger.info("Daemon resumed")
        self._persist_pause_state()
        self._notify_state_changed("resumed")

    def pause_remaining_seconds(self):
        """Get remaining seconds of a time-limited pause."""
        with self._lock:
            return self._pause_remaining_locked()

    # --- Per-directory pause/resume (#958) ---

    def pause_dir(self, directory, duration_minutes=0):
        """Pause scanning for a specific project directory.

        Args:
            directory: Absolute path string of the project directory
            duration_minutes: Pause duration in minutes. 0 = indefinite.
        """
        directory = os.path.realpath(directory)
        with self._lock:
            if duration_minutes > 0:
                self._paused_dirs[directory] = time.monotonic() + duration_minutes * 60
                logger.info(
                    "Directory paused for %d minutes: %s",
                    duration_minutes,
                    directory,
                )
            else:
                self._paused_dirs[directory] = 0.0
                logger.info("Directory paused indefinitely: %s", directory)
        self._persist_pause_state()
        self._notify_state_changed(
            "dir_paused", {"dir": directory, "minutes": duration_minutes}
        )

    def resume_dir(self, directory):
        """Resume scanning for a specific project directory.

        Args:
            directory: Absolute path string of the project directory
        """
        directory = os.path.realpath(directory)
        with self._lock:
            removed = self._paused_dirs.pop(directory, None)
            if removed is not None:
                logger.info("Directory resumed: %s", directory)
            else:
                logger.debug("Directory was not paused: %s", directory)
        self._persist_pause_state()
        self._notify_state_changed("dir_resumed", {"dir": directory})

    def is_dir_paused(self, directory):
        """Check if scanning is paused for a specific directory.

        Handles expiration of time-limited per-directory pauses.

        Args:
            directory: Absolute path string of the project directory

        Returns:
            bool: True if the directory is paused
        """
        if not directory:
            return False
        directory = os.path.realpath(directory)
        with self._lock:
            until = self._paused_dirs.get(directory)
            if until is None:
                return False
            if until > 0 and time.monotonic() >= until:
                del self._paused_dirs[directory]
                logger.info("Directory pause expired: %s", directory)
                return False
            return True

    def get_paused_dirs(self):
        """Get a snapshot of all paused directories with remaining seconds.

        Expired entries are cleaned up during iteration.

        Returns:
            dict: {directory: remaining_seconds} where 0 means indefinite
        """
        with self._lock:
            return self._get_paused_dirs_locked()

    # --- Pause persistence (#1319) ---

    def _load_pause_state(self):
        """Restore pause state from disk on startup."""
        try:
            if not self._pause_file or not Path(self._pause_file).exists():
                return
            content = Path(self._pause_file).read_text(encoding="utf-8")
            if not content.strip():
                return
            data = json.loads(content)
            now = time.time()
            mono_now = time.monotonic()

            g = data.get("global", {})
            if g.get("paused"):
                until_wall = g.get("until", 0.0)
                if until_wall > 0 and now >= until_wall:
                    logger.info("Persisted global pause expired, not restoring")
                else:
                    self._paused = True
                    if until_wall > 0:
                        remaining = max(0, until_wall - now)
                        self._paused_until = mono_now + remaining
                    else:
                        self._paused_until = 0.0
                    logger.info("Restored global pause from disk")

            dirs = data.get("dirs", {})
            for directory, info in dirs.items():
                until_wall = info.get("until", 0.0)
                if until_wall > 0 and now >= until_wall:
                    continue
                if until_wall > 0:
                    remaining = max(0, until_wall - now)
                    self._paused_dirs[directory] = mono_now + remaining
                else:
                    self._paused_dirs[directory] = 0.0
            if self._paused_dirs:
                logger.info(
                    "Restored %d paused dir(s) from disk", len(self._paused_dirs)
                )
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("Could not load persisted pause state: %s", e)

    def _persist_pause_state(self):
        """Write current pause state to disk."""
        if not self._pause_file:
            return
        with self._lock:
            now = time.time()
            mono_now = time.monotonic()

            global_until = 0.0
            if self._paused and self._paused_until > 0:
                global_until = now + (self._paused_until - mono_now)

            dirs = {}
            for directory, until_mono in self._paused_dirs.items():
                if until_mono > 0:
                    dirs[directory] = {"until": now + (until_mono - mono_now)}
                else:
                    dirs[directory] = {"until": 0.0}

            data = {
                "global": {"paused": self._paused, "until": global_until},
                "dirs": dirs,
            }

        self._atomic_write_json(self._pause_file, data, ".daemon-pause-")

    @staticmethod
    def is_paused_on_disk(cwd=None, pause_file=None):
        """Check if scanning is paused by reading the persisted pause file.

        For use by the CLI direct-mode fallback when daemon is unavailable.

        Args:
            cwd: Optional working directory to check per-directory pause
            pause_file: Optional override for pause file path

        Returns:
            bool: True if globally paused or cwd is directory-paused
        """
        try:
            path = (
                Path(pause_file)
                if pause_file
                else get_state_dir() / DAEMON_PAUSE_FILENAME
            )
            if not path.exists():
                return False
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                return False
            data = json.loads(content)
            now = time.time()

            g = data.get("global", {})
            if g.get("paused"):
                until_wall = g.get("until", 0.0)
                if until_wall <= 0 or now < until_wall:
                    return True

            if cwd:
                cwd = os.path.realpath(cwd)
                dirs = data.get("dirs", {})
                info = dirs.get(cwd)
                if info is not None:
                    until_wall = info.get("until", 0.0)
                    if until_wall <= 0 or now < until_wall:
                        return True

            return False
        except (json.JSONDecodeError, OSError):
            return False

    # --- Stats ---

    def get_stats(self):
        """Get daemon statistics.

        Returns:
            dict: Stats including uptime, request count, violation count,
                  severity breakdown, and last block info
        """
        with self._lock:
            uptime = time.time() - self._started_at
            violations = (
                self._blocked_count + self._warning_count + self._log_only_count
            )

            last_block_seconds_ago = None
            if self._last_block_time is not None:
                last_block_seconds_ago = time.monotonic() - self._last_block_time

            last_reload_seconds_ago = None
            if self._last_config_reload_at is not None:
                last_reload_seconds_ago = time.time() - self._last_config_reload_at

            last_project_reload_seconds_ago = None
            if self._last_project_config_reload_at is not None:
                last_project_reload_seconds_ago = (
                    time.time() - self._last_project_config_reload_at
                )

            return {
                "version": self._get_version(),
                "uptime_seconds": uptime,
                "request_count": self._request_count,
                "blocked_count": self._blocked_count,
                "warning_count": self._warning_count,
                "log_only_count": self._log_only_count,
                "violation_count": violations,
                "critical_count": self._critical_count,
                "warning_severity_count": self._warning_severity_count,
                "last_block_type": self._last_block_type,
                "last_block_seconds_ago": last_block_seconds_ago,
                "active_contexts": len(self._hook_contexts),
                "cached_patterns": len(self._compiled_patterns),
                "config_loaded": self._config is not None,
                "paused": self._paused,
                "pause_remaining_seconds": self._pause_remaining_locked(),
                "started_at": self._started_at,
                "last_config_reload_at": self._last_config_reload_at,
                "last_config_reload_seconds_ago": last_reload_seconds_ago,
                "last_project_config_reload_at": self._last_project_config_reload_at,
                "last_project_config_reload_seconds_ago": last_project_reload_seconds_ago,
                "project_configs_tracked": len(self._project_config_mtimes),
                "config_error": self._config_error,
                "mcp_installed": self._mcp_installed,
                "paused_dirs": self._get_paused_dirs_locked(),
                "active_project_dirs": sorted(
                    self._project_dir_last_seen.keys(),
                    key=lambda d: self._project_dir_last_seen[d],
                    reverse=True,
                ),
                "most_recent_project_dir": (
                    max(
                        self._project_dir_last_seen,
                        key=self._project_dir_last_seen.get,
                    )
                    if self._project_dir_last_seen
                    else None
                ),
                "ml_model_loaded": self._ml_engine_manager is not None,
                "ml_load_error": self._ml_load_error,
                "ask_dialog_count": self._ask_dialog_count,
                "ask_dialog_total_ms": round(self._ask_dialog_total_ms, 1),
            }

    def get_project_cache_status(self):
        """Get per-project config cache details for diagnostics.

        Returns:
            dict with 'projects' list and 'summary' metadata.
        """
        from ai_guardian.config.loaders import _caches as config_caches

        now_mono = time.monotonic()
        now_unix = time.time()
        projects = []

        with self._lock:
            for project_dir in sorted(self._project_dir_last_seen):
                last_seen = self._project_dir_last_seen[project_dir]
                config_path = self._project_config_paths.get(project_dir)
                config_mtime = self._project_config_mtimes.get(project_dir)

                cache_key = config_path if config_path else "__global__"
                cached = config_caches.get(cache_key)

                entry = {
                    "project_dir": project_dir,
                    "config_path": config_path,
                    "config_mtime": config_mtime,
                    "last_seen_seconds_ago": round(now_mono - last_seen, 1),
                    "has_project_override": config_path is not None,
                }

                if cached:
                    gp = cached.global_path
                    entry["global_config_path"] = str(gp) if gp else None
                    entry["global_config_mtime"] = cached.global_mtime
                    pp = cached.project_path
                    entry["cached_project_path"] = str(pp) if pp else None
                    entry["cached_project_mtime"] = cached.project_mtime
                    entry["cache_last_accessed_seconds_ago"] = round(
                        now_mono - cached.last_accessed, 1
                    )

                projects.append(entry)

        return {
            "projects": projects,
            "total_tracked": len(projects),
            "last_project_config_reload_at": self._last_project_config_reload_at,
            "timestamp": now_unix,
        }

    @staticmethod
    def _get_version():
        try:
            from ai_guardian import __version__

            return __version__
        except ImportError:
            return "unknown"

    # Directories (relative to package root) whose changes require daemon restart
    _DAEMON_SOURCE_DIRS = frozenset(
        {
            "daemon",
            "hook_adapters",
            "hook_events",
            "patterns",
            "scanners",
            "config",
            "integrations",
        }
    )
    # Top-level files (no subdirectory) that require daemon restart
    _DAEMON_SOURCE_FILES = frozenset(
        {
            "hook_processing.py",
            "sdk.py",
            "constants.py",
            "annotations.py",
            "aiguardignore.py",
            "response_format.py",
            "allowlist_utils.py",
            "ask_mode.py",
        }
    )

    @classmethod
    def get_package_max_mtime(cls) -> float:
        """Get max mtime of daemon-relevant .py files in the ai_guardian package.

        Only scans files that require a daemon restart when changed — excludes
        tui/, web/, cli.py, setup.py, doctor.py, etc. (#1465).
        """
        try:
            import ai_guardian

            pkg_dir = Path(ai_guardian.__file__).parent
            max_mtime = 0.0
            for py_file in pkg_dir.rglob("*.py"):
                rel = py_file.relative_to(pkg_dir)
                parts = rel.parts
                # Top-level file — include only if in the allow-list
                if len(parts) == 1:
                    if parts[0] not in cls._DAEMON_SOURCE_FILES:
                        continue
                else:
                    # Subdirectory file — include only if the top-level dir matches
                    if parts[0] not in cls._DAEMON_SOURCE_DIRS:
                        continue
                try:
                    mtime = py_file.stat().st_mtime
                    if mtime > max_mtime:
                        max_mtime = mtime
                except OSError:
                    continue
            return max_mtime
        except Exception:
            return 0.0

    def record_source_mtime(self):
        """Record current package source mtime at daemon startup."""
        self._source_mtime = self.get_package_max_mtime()

    def get_config_error(self):
        """Get current config error message, if any."""
        with self._lock:
            return self._config_error

    # --- Listen mode management (#1590) ---

    @staticmethod
    def _restart_listen_manager(mgr):
        """Restart a listen manager outside the state lock.

        Called after config reload so the potentially blocking process
        wait does not hold self._lock.
        """
        if mgr is None:
            return
        try:
            mgr.restart()
        except Exception as e:
            logger.debug(f"Error restarting listen manager: {e}")

    def stop_listen_manager(self):
        """Stop the listen manager if it was created. Safe to call during shutdown."""
        if self._listen_manager is not None:
            self._listen_manager.stop()

    def get_listen_manager(self):
        """Get or lazily create the ListenModeManager for persistent leaktk."""
        with self._lock:
            if self._listen_manager is None:
                from ai_guardian.scanners.listen_mode import ListenModeManager

                self._listen_manager = ListenModeManager()
            return self._listen_manager

    # --- ML engine management (#185) ---

    def get_ml_engine_manager(self):
        """Get or lazily load ML engine manager. Thread-safe.

        Returns:
            MLEngineManager or None if unavailable
        """
        with self._lock:
            if self._ml_engine_manager is not None:
                return self._ml_engine_manager
            if self._ml_load_attempted:
                # Another thread is loading — wait for it to finish
                self._lock.release()
                try:
                    self._ml_load_event.wait(timeout=60)
                finally:
                    self._lock.acquire()
                return self._ml_engine_manager
            self._ml_load_attempted = True

        try:
            from ai_guardian.scanners.ml_detection import (
                is_ml_available,
                MLEngineManager,
                ensure_model_downloaded,
            )

            if not is_ml_available():
                with self._lock:
                    self._ml_load_error = (
                        "ML dependencies not available (onnxruntime required)"
                    )
                return None

            config = self.get_config() or {}
            pi_config = config.get("prompt_injection", {})
            engines_config = pi_config.get("ml_engines", [])

            if not engines_config:
                with self._lock:
                    self._ml_load_error = (
                        "No ml_engines configured in prompt_injection config"
                    )
                return None

            if pi_config.get("auto_download_model", True):
                for eng in engines_config:
                    model = eng.get("model", "")
                    if model:
                        downloaded, msg = ensure_model_downloaded(model)
                        if downloaded:
                            logger.info(f"Auto-downloaded ML model: {msg}")

            strategy = pi_config.get("ml_strategy", "any-match")
            consensus_threshold = pi_config.get("consensus_threshold", 2)

            manager = MLEngineManager(
                engines_config,
                strategy=strategy,
                consensus_threshold=consensus_threshold,
            )

            if not manager.available:
                with self._lock:
                    self._ml_load_error = "No ML engines loaded: " + "; ".join(
                        manager.load_errors
                    )
                return None

            with self._lock:
                self._ml_engine_manager = manager
                self._ml_load_error = None
            logger.info(
                f"ML engine manager loaded: {len(manager.engines)} engines, "
                f"strategy={strategy}"
            )
            return manager
        except Exception as e:
            with self._lock:
                self._ml_load_error = str(e)
            logger.warning(f"Failed to load ML engine manager: {e}")
            return None
        finally:
            self._ml_load_event.set()

    def reload_ml_engines(self):
        """Force reload of ML engines (after model download or config change)."""
        with self._lock:
            self._ml_engine_manager = None
            self._ml_load_attempted = False
            self._ml_load_error = None
            self._ml_load_event = threading.Event()

    def get_ml_status(self):
        """Get ML engine status for reporting."""
        with self._lock:
            if self._ml_engine_manager is not None:
                status = self._ml_engine_manager.get_status()
                status["ml_available"] = True
                return status
            return {
                "ml_available": False,
                "ml_engines_loaded": 0,
                "ml_engines_total": 0,
                "ml_load_error": self._ml_load_error,
            }

    @staticmethod
    def _atomic_write_json(path, data, prefix):
        """Atomically write JSON data to a file with owner-only permissions."""
        try:
            parent = Path(path).parent
            parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(data)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(parent), prefix=prefix, suffix=".tmp"
            )
            closed = False
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
                os.write(fd, content.encode("utf-8"))
                os.close(fd)
                closed = True
                os.replace(tmp_path, str(path))
            except BaseException:
                if not closed:
                    os.close(fd)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
        except OSError as e:
            logger.debug("Error writing %s: %s", path, e)

    def _pause_remaining_locked(self):
        """Get remaining pause seconds (must be called with lock held)."""
        if not self._paused or self._paused_until <= 0:
            return 0.0
        remaining = self._paused_until - time.monotonic()
        return max(0.0, remaining)

    def _get_paused_dirs_locked(self):
        """Get paused dirs snapshot (must be called with lock held).

        Returns:
            dict: {directory: remaining_seconds} where 0 means indefinite.
                  Expired entries are cleaned up.
        """
        now = time.monotonic()
        result = {}
        expired = []
        for d, until in self._paused_dirs.items():
            if until > 0 and now >= until:
                expired.append(d)
            elif until > 0:
                result[d] = until - now
            else:
                result[d] = 0.0
        for d in expired:
            del self._paused_dirs[d]
        return result

    # --- Session persistence (#592) ---

    def _load_sessions(self):
        """Load persisted session state from disk on startup."""
        try:
            if not self._sessions_file or not self._sessions_file.exists():
                return
            content = self._sessions_file.read_text(encoding="utf-8")
            if not content.strip():
                return
            data = json.loads(content)
            sessions = data.get("sessions", {})

            now = time.time()
            for key, entry in sessions.items():
                last_activity = entry.get("last_activity", 0)
                if now - last_activity > SESSION_TTL:
                    continue
                if entry.get("security_injected", False):
                    self._security_injected_sessions.add(key)
                if entry.get("security_reinject", False):
                    self._security_reinject_sessions.add(key)
                self._session_last_activity[key] = last_activity

            loaded = len(self._security_injected_sessions)
            logger.info(
                f"Loaded {loaded} persisted session(s) from {self._sessions_file}"
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.debug(f"Could not load persisted sessions: {e}")

    def _schedule_persist(self):
        """Schedule a debounced write of session state to disk."""
        with self._lock:
            self._sessions_dirty = True
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(
                PERSIST_DEBOUNCE, self._persist_sessions
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _persist_sessions(self):
        """Write current session state to disk (called by debounce timer)."""
        with self._lock:
            if not self._sessions_dirty:
                return
            self._sessions_dirty = False
            data = self._build_sessions_dict_locked()

        self._write_sessions_file(data)

    def flush_sessions(self):
        """Force-write pending session state to disk (for clean shutdown)."""
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
            if not self._sessions_dirty:
                return
            self._sessions_dirty = False
            data = self._build_sessions_dict_locked()

        self._write_sessions_file(data)

    def _build_sessions_dict_locked(self):
        """Build serializable session dict (must be called with lock held)."""
        now = time.time()
        sessions = {}
        all_keys = self._security_injected_sessions | self._security_reinject_sessions
        for key in all_keys:
            last_activity = self._session_last_activity.get(key, now)
            if now - last_activity > SESSION_TTL:
                continue
            sessions[key] = {
                "security_injected": key in self._security_injected_sessions,
                "security_reinject": key in self._security_reinject_sessions,
                "last_activity": last_activity,
            }
        return {"sessions": sessions, "version": 1}

    def _write_sessions_file(self, data):
        """Atomic write of session data to disk."""
        if not self._sessions_file:
            return
        self._atomic_write_json(self._sessions_file, data, ".daemon-sess-")
