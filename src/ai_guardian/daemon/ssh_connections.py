"""Tray/Web-owned SSH connection workers. Discovery itself never waits on SSH."""

import logging
import threading
import time

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.daemon.rest_transport import DaemonConnectionError
from ai_guardian.daemon.ssh_config import DEFAULT_SETTINGS, load_settings, scan_aliases
from ai_guardian.daemon.ssh_storage import SSHConnectionError, SSHStore
from ai_guardian.daemon.ssh_tunnel import (
    IDENTITY_CHANGED,
    OFFLINE_ERROR,
    SSHTunnel,
    probe_destination,
    stop_owned_process,
)

logger = logging.getLogger(__name__)
CANDIDATE_ERROR = "This SSH alias is no longer available to pair. Refresh discovery, or use Add daemon via SSH for an explicitly chosen destination."


class _Connection:
    def __init__(self, profile):
        self.profile = profile
        self.stop = threading.Event()
        self.target = DaemonTarget(
            name=profile.name,
            runtime="ssh",
            status="starting",
            ssh_id=profile.id,
            error_message="Connecting to SSH daemon...",
        )
        self.thread = None
        self.tunnel = None

    def close(self):
        self.stop.set()
        tunnel = self.tunnel or self.target.ssh_tunnel
        if tunnel is not None:
            tunnel.close()
        self.target.ssh_tunnel = None
        self.target.status = "offline"
        self.target.stats = None


class SSHConnectionManager:
    def __init__(self, store=None):
        self.store = store or SSHStore()
        self._connections = {}
        self._probes = {}
        self._enrolling = set()
        self._lock = threading.RLock()
        self._alias_lock = threading.Lock()
        self._alias_discovery: dict = {**DEFAULT_SETTINGS, "aliases": (), "notices": ()}
        self._closed = False

    @property
    def alias_discovery(self):
        """Cached display-safe data; tray menu building must not touch disk."""
        return dict(self._alias_discovery)

    def refresh_aliases(self, *, wait=False):
        """Local opt-in scan only. Saved profiles keep their independent workers."""
        from ai_guardian.daemon.ssh_storage import STORAGE_ERROR

        # Discovery refreshes are single-flight even if a filesystem is slow.
        # An explicit review waits for fresh state rather than probing stale data.
        if not self._alias_lock.acquire(blocking=wait):
            return self.alias_discovery
        try:
            closed_at_start = self._closed
            if closed_at_start:
                return self.alias_discovery
            settings = load_settings()
            aliases: tuple[str, ...] = ()
            notices: tuple[str, ...] = ()
            result = (
                scan_aliases(prefix=settings["alias_prefix"])
                if settings["enabled"]
                else None
            )
            with self._lock:
                if result is not None:
                    notices = result.notices
                    try:
                        paired = {
                            p.destination.rsplit("@", 1)[-1].casefold()
                            for p in self.store.load()
                        }
                        aliases = tuple(
                            alias
                            for alias in result.aliases
                            if alias.casefold() not in paired
                            and not self.store.is_dismissed(alias)
                        )
                    except SSHConnectionError:
                        notices = (*notices, STORAGE_ERROR)
                if self._closed:
                    aliases = ()
                self._alias_discovery = {
                    **settings,
                    "aliases": aliases,
                    "notices": notices,
                }
                return dict(self._alias_discovery)
        finally:
            self._alias_lock.release()

    def prepare_discovered(self, alias):
        # A stale browser/menu action is not authority to probe a new destination.
        state = self.refresh_aliases(wait=True)
        if alias not in state["aliases"]:
            raise SSHConnectionError(CANDIDATE_ERROR)
        return self.prepare(alias)

    def dismiss_alias(self, alias):
        with self._lock:
            if alias not in self._alias_discovery["aliases"]:
                raise SSHConnectionError(CANDIDATE_ERROR)
            self.store.dismiss(alias)
            self._alias_discovery = {
                **self._alias_discovery,
                "aliases": tuple(
                    value
                    for value in self._alias_discovery["aliases"]
                    if value != alias
                ),
            }

    def prepare(self, host, *, cancelled=None):
        """Probe only a user-entered destination; never save or trust it here."""
        with self._lock:
            if self._closed or (cancelled is not None and cancelled.is_set()):
                raise SSHConnectionError(OFFLINE_ERROR)

        def on_process(process, active):
            with self._lock:
                if not active:
                    self._probes.pop(process, None)
                elif self._closed or (cancelled is not None and cancelled.is_set()):
                    stop_owned_process(process)
                    raise SSHConnectionError(OFFLINE_ERROR)
                else:
                    self._probes[process] = cancelled

        pairing = probe_destination(host, on_process=on_process)
        with self._lock:
            if self._closed or (cancelled is not None and cancelled.is_set()):
                raise SSHConnectionError(OFFLINE_ERROR)
        return pairing

    def enroll(self, pairing):
        """Called only after the UI's explicit certificate/identity confirmation."""
        tunnel = SSHTunnel(pairing, self.store)
        with self._lock:
            if self._closed:
                raise SSHConnectionError(OFFLINE_ERROR)
            self._enrolling.add(tunnel)
        try:
            tunnel.start()
            with self._lock:
                if self._closed:
                    raise SSHConnectionError(OFFLINE_ERROR)
            tunnel.request("GET", "/api/stats")  # Authenticate before saving pairing.
            with self._lock:
                if self._closed:
                    raise SSHConnectionError(OFFLINE_ERROR)
                self.store.create(pairing.profile)
        finally:
            tunnel.close()
            with self._lock:
                self._enrolling.discard(tunnel)
        self.refresh()

    def remove(self, profile_id):
        with self._lock:
            profile = next((p for p in self.store.load() if p.id == profile_id), None)
            if profile is not None:
                # Record the user's removal before deleting trust (crash-safe order).
                self.store.dismiss(profile.destination)
            self.store.remove(profile_id)
            connection = self._connections.pop(profile_id, None)
            if connection is not None:
                self._close_connection(connection)

    def _close_connection(self, connection):
        connection.close()
        for process, cancelled in list(self._probes.items()):
            if cancelled is connection.stop:
                stop_owned_process(process)

    def refresh(self):
        with self._lock:
            if self._closed:
                return []
            try:
                profiles = {profile.id: profile for profile in self.store.load()}
            except SSHConnectionError as exc:
                for connection in self._connections.values():
                    self._close_connection(connection)
                self._connections.clear()
                return [
                    DaemonTarget(
                        name="ssh-connections",
                        runtime="ssh",
                        status="error",
                        error_message=str(exc),
                    )
                ]
            for key in list(self._connections):
                if profiles.get(key) != self._connections[key].profile:
                    self._close_connection(self._connections.pop(key))
            for key, profile in profiles.items():
                if key not in self._connections:
                    connection = _Connection(profile)
                    from ai_guardian.daemon.ssh_commands import SSHCommands

                    connection.target.ssh_commands = SSHCommands(
                        profile, self.store, connection.stop
                    )
                    self._connections[key] = connection
                    connection.thread = threading.Thread(
                        target=self._run,
                        args=(connection,),
                        daemon=True,
                        name="ssh-daemon",
                    )
                    connection.thread.start()
            return [connection.target for connection in self._connections.values()]

    def _run(self, connection):
        target = connection.target
        delay = 2.0
        while not connection.stop.is_set():
            tunnel = None
            try:
                pairing = self.prepare(
                    connection.profile.destination, cancelled=connection.stop
                )
                if pairing.profile != connection.profile:
                    raise SSHConnectionError(IDENTITY_CHANGED)
                if connection.stop.is_set():
                    break
                tunnel = SSHTunnel(pairing, self.store, saved=True)
                connection.tunnel = tunnel
                if connection.stop.is_set():
                    break
                tunnel.start()
                if connection.stop.is_set():
                    break
                target.ssh_tunnel = tunnel
                while not connection.stop.is_set():
                    stats = tunnel.request("GET", "/api/stats")
                    if connection.stop.is_set():
                        break
                    stats = self._stats_with_mcp_state(tunnel, stats)
                    if connection.stop.is_set():
                        break
                    target.stats = stats
                    if pairing.cli is not None:
                        # Publish context only after TLS identity AND daemon auth.
                        target.ssh_commands.cli = dict(pairing.cli)
                    target.status = (
                        "paused" if stats.get("paused", False) else "running"
                    )
                    target.error_message = None
                    target.last_seen = time.monotonic()
                    delay = 2.0
                    if connection.stop.wait(5):
                        break
            except (SSHConnectionError, DaemonConnectionError) as exc:
                target.status = "error" if str(exc) == IDENTITY_CHANGED else "offline"
                target.error_message = str(exc)
                target.stats = None
                logger.debug("SSH daemon connection unavailable")
                if str(exc) == IDENTITY_CHANGED:
                    connection.stop.set()
            except OSError:
                target.status = "offline"
                target.error_message = OFFLINE_ERROR
                target.stats = None
                logger.debug("SSH daemon transport unavailable")
            finally:
                target.ssh_tunnel = None
                if tunnel is not None:
                    tunnel.close()
                connection.tunnel = None
            if connection.stop.wait(delay):
                break
            delay = min(delay * 2, 60.0)

    @staticmethod
    def _stats_with_mcp_state(tunnel, stats):
        """Older daemons already expose global MCP config, but not new stats.

        Do this in the connection worker using its authenticated generation,
        never while rendering the menu or via workstation/project settings.
        A failed optional query must not disconnect an otherwise healthy VM.
        """
        levels = ("low", "medium", "high", "paused")
        if stats.get("mcp_installed") is not True or (
            stats.get("mcp_proactive_level") in levels
            and isinstance(stats.get("mcp_enabled"), bool)
        ):
            return stats
        try:
            config = tunnel.request("GET", "/api/config?scope=global")
        except (SSHConnectionError, DaemonConnectionError, OSError):
            logger.debug("SSH daemon MCP configuration is unavailable")
            return stats
        if not isinstance(config, dict) or config.get("error") or "features" in config:
            return stats
        mcp = config.get("mcp_server", {})
        if not isinstance(mcp, dict):
            return stats
        level = mcp.get("proactive_level", "low")
        enabled = mcp.get("enabled", True)
        if level not in levels or not isinstance(enabled, bool):
            return stats
        return {**stats, "mcp_proactive_level": level, "mcp_enabled": enabled}

    def close(self):
        with self._lock:
            self._closed = True
            self._alias_discovery = {**self._alias_discovery, "aliases": ()}
            for connection in self._connections.values():
                self._close_connection(connection)
            for tunnel in self._enrolling:
                tunnel.close()
            for process in self._probes:
                stop_owned_process(process)
            self._connections.clear()
