"""Headless daemon inventory and action routing shared by host clients.

This module deliberately contains no tray UI imports. Inventory records expose
only display-safe target metadata; connection credentials stay in the
``DaemonTarget`` retained by the service.
"""

import logging
import threading
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional
from uuid import uuid4

from ai_guardian.daemon.discovery import DaemonDiscovery, DaemonTarget
from ai_guardian.daemon.multi_client import MultiDaemonClient

logger = logging.getLogger(__name__)

_CORE_OPERATIONS = frozenset({"status", "pause", "resume", "reload"})
_DIRECTORY_OPERATIONS = frozenset({"pause_directory", "resume_directory"})
_SESSION_OPERATIONS = frozenset({"pause_session", "resume_session"})
_EXEC_OPERATIONS = frozenset({"stop", "restart"})

_RUNTIME_OPERATIONS = {
    "local": _CORE_OPERATIONS
    | _DIRECTORY_OPERATIONS
    | _SESSION_OPERATIONS
    | _EXEC_OPERATIONS,
    "container": _CORE_OPERATIONS
    | _DIRECTORY_OPERATIONS
    | _SESSION_OPERATIONS
    | _EXEC_OPERATIONS,
    "kubernetes": _CORE_OPERATIONS
    | _DIRECTORY_OPERATIONS
    | _SESSION_OPERATIONS
    | _EXEC_OPERATIONS,
    "manual": _CORE_OPERATIONS | _DIRECTORY_OPERATIONS | _SESSION_OPERATIONS,
    "ssh": _CORE_OPERATIONS
    | _DIRECTORY_OPERATIONS
    | _SESSION_OPERATIONS
    | _EXEC_OPERATIONS,
}

_OPERATION_METHODS = {
    "pause": ("send_pause", ("minutes",)),
    "resume": ("send_resume", ()),
    "pause_directory": ("send_pause_dir", ("directory", "minutes")),
    "resume_directory": ("send_resume_dir", ("directory",)),
    "pause_session": ("send_pause_session", ("session_key", "minutes")),
    "resume_session": ("send_resume_session", ("session_key",)),
    "reload": ("send_reload", ()),
    "stop": ("send_stop", ()),
    "restart": ("send_restart", ()),
}

_ACTIVE_STATUSES = frozenset({"running", "paused"})
_KNOWN_STATUSES = frozenset(
    {"running", "paused", "starting", "stopped", "offline", "error", "unknown"}
)


@dataclass(frozen=True)
class TargetInventoryEntry:
    """Display-safe inventory data for one discovered daemon target."""

    target_id: str
    name: str
    runtime: str
    runtime_type: Optional[str]
    status: str
    availability: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class TargetActionResult:
    """Result of a broker-safe action request, without transport diagnostics."""

    status: str
    value: Any = None
    reason: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"


class DaemonTargetService:
    """Own daemon discovery and route a small, explicit set of headless actions.

    The tray uses this class as its ``MultiDaemonClient`` facade too, so its
    existing target actions continue through the same transport implementation.
    Broker callers should use :meth:`get_inventory` and :meth:`route`; those APIs
    never serialize a ``DaemonTarget`` or accept an arbitrary target endpoint.
    """

    def __init__(
        self,
        config=None,
        discovery: Optional[DaemonDiscovery] = None,
        client: Optional[MultiDaemonClient] = None,
    ):
        self.discovery = (
            discovery if discovery is not None else DaemonDiscovery(config=config)
        )
        self._client = client if client is not None else MultiDaemonClient()
        self._target_lock = threading.RLock()
        self._targets_by_id: Dict[str, DaemonTarget] = {}
        self._route_snapshots: Dict[str, DaemonTarget] = {}
        self._observed_capabilities: Dict[str, frozenset[str]] = {}

    def __getattr__(self, name: str) -> Any:
        """Keep existing tray client calls on the shared transport instance."""
        return getattr(self._client, name)

    def refresh_inventory(self) -> tuple[TargetInventoryEntry, ...]:
        """Run discovery and return its display-safe inventory."""
        self.discovery.discover_all()
        return self.get_inventory()

    def get_inventory(self) -> tuple[TargetInventoryEntry, ...]:
        """Return the latest inventory, invalidating IDs for replaced targets."""
        targets = tuple(self.discovery.targets)
        with self._target_lock:
            previous = {
                id(target): (target_id, target, self._route_snapshots[target_id])
                for target_id, target in self._targets_by_id.items()
                if target_id in self._route_snapshots
            }
            targets_by_id: Dict[str, DaemonTarget] = {}
            route_snapshots: Dict[str, DaemonTarget] = {}
            capabilities_by_id: Dict[str, frozenset[str]] = {}
            entries: list[TargetInventoryEntry] = []

            for target in targets:
                prior = previous.get(id(target))
                if (
                    prior is not None
                    and prior[1] is target
                    and self._same_route(target, prior[2])
                ):
                    target_id = prior[0]
                    observed = self._observed_capabilities.get(target_id, frozenset())
                    capabilities_by_id[target_id] = observed
                else:
                    target_id = uuid4().hex
                targets_by_id[target_id] = target
                route_snapshots[target_id] = self._route_snapshot(target)
                entries.append(self._inventory_entry(target_id, target))

            self._targets_by_id = targets_by_id
            self._route_snapshots = route_snapshots
            self._observed_capabilities = capabilities_by_id
            return tuple(entries)

    def close(self) -> None:
        """Stop discovery workers owned by this service."""
        self.discovery.stop()

    def _inventory_entry(
        self, target_id: str, target: DaemonTarget
    ) -> TargetInventoryEntry:
        runtime_operations = _RUNTIME_OPERATIONS.get(target.runtime)
        status = target.status if target.status in _KNOWN_STATUSES else "unknown"
        capabilities: tuple[str, ...]
        if runtime_operations is None:
            availability = "unsupported"
            capabilities = ()
        else:
            availability = self._availability(status)
            if status not in _ACTIVE_STATUSES:
                capabilities = ("status",)
            else:
                observed = self._observed_capabilities.get(target_id, frozenset())
                available = set(runtime_operations & _CORE_OPERATIONS)
                available.update(runtime_operations & _EXEC_OPERATIONS)
                available.update(runtime_operations & observed)
                capabilities = tuple(sorted(available))

        return TargetInventoryEntry(
            target_id=target_id,
            name=target.name if isinstance(target.name, str) else "Daemon",
            runtime=target.runtime,
            runtime_type=target.runtime_type,
            status=status,
            availability=availability,
            capabilities=capabilities,
        )

    @staticmethod
    def _availability(status: str) -> str:
        if status in _ACTIVE_STATUSES:
            return "available"
        if status in {"offline", "error"}:
            return "offline"
        if status == "stopped":
            return "stopped"
        if status == "starting":
            return "starting"
        return "unknown"

    def _resolve_target(
        self, target_id: str
    ) -> tuple[Optional[DaemonTarget], Optional[str]]:
        with self._target_lock:
            target = self._targets_by_id.get(target_id)
        if target is None:
            return None, "target_not_found"
        if not self._is_current_target(target_id, target):
            with self._target_lock:
                self._targets_by_id.pop(target_id, None)
                self._route_snapshots.pop(target_id, None)
                self._observed_capabilities.pop(target_id, None)
            return None, "stale_target"
        return target, None

    @staticmethod
    def _route_snapshot(target: DaemonTarget) -> DaemonTarget:
        # Keep a private binding to endpoint and trust state; never expose it in
        # inventory records or route results.
        return replace(target, tls=deepcopy(target.tls))

    @staticmethod
    def _same_route(first: DaemonTarget, second: DaemonTarget) -> bool:
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
        return all(
            getattr(first, field) == getattr(second, field) for field in fields
        ) and (
            first.runtime != "ssh"
            or (
                first.ssh_tunnel is second.ssh_tunnel
                and first.ssh_commands is second.ssh_commands
            )
        )

    def _is_current_target(self, target_id: str, target: DaemonTarget) -> bool:
        with self._target_lock:
            if self._targets_by_id.get(target_id) is not target:
                return False
            snapshot = self._route_snapshots.get(target_id)
        return (
            snapshot is not None
            and self._same_route(target, snapshot)
            and any(current is target for current in self.discovery.targets)
        )

    def _probe_status(
        self, target_id: str, target: DaemonTarget
    ) -> tuple[TargetActionResult, Optional[dict[str, Any]]]:
        try:
            status = self.get_status(target)
        except Exception as exc:
            logger.warning("Daemon target status probe failed (%s)", type(exc).__name__)
            status = None

        if not isinstance(status, dict) or status.get("error") is not None:
            target.status = "offline"
            with self._target_lock:
                self._observed_capabilities.pop(target_id, None)
            return (
                TargetActionResult(status="unavailable", reason="target_offline"),
                None,
            )

        observed: set[str] = set()
        if isinstance(status.get("paused_dirs"), dict) or isinstance(
            status.get("active_project_dirs"), list
        ):
            observed.update(_DIRECTORY_OPERATIONS)
        if isinstance(status.get("pause_control_sessions"), list) or isinstance(
            status.get("active_sessions"), list
        ):
            observed.update(_SESSION_OPERATIONS)

        paused = status.get("paused")
        target.status = (
            "paused"
            if type(paused) is bool and paused
            else ("running" if type(paused) is bool else "unknown")
        )
        with self._target_lock:
            self._observed_capabilities[target_id] = frozenset(observed)
        return TargetActionResult(status="completed", value=status), status

    @staticmethod
    def _valid_arguments(operation: str, arguments: dict[str, Any]) -> bool:
        method = _OPERATION_METHODS.get(operation)
        if method is None:
            return operation == "status" and not arguments
        names = method[1]
        if set(arguments) != set(names):
            return False
        if "minutes" in names:
            minutes = arguments["minutes"]
            if type(minutes) is not int or minutes < 0:
                return False
        for name in ("directory", "session_key"):
            if name in names:
                value = arguments[name]
                if not isinstance(value, str) or not value.strip():
                    return False
        return True

    def route(
        self, target_id: object, operation: object, **arguments: Any
    ) -> TargetActionResult:
        """Route one allowlisted action to a currently discovered target.

        Mutating actions require a fresh positive status probe. Runtime support,
        current availability, and action parameters are checked before dispatch;
        there is no fallback to another target or transport.
        """
        if not isinstance(target_id, str) or not isinstance(operation, str):
            return TargetActionResult("invalid_request", reason="invalid_arguments")
        target, resolution_error = self._resolve_target(target_id)
        if target is None:
            resolution_error = resolution_error or "target_not_found"
            return TargetActionResult(resolution_error, reason=resolution_error)

        runtime_operations = _RUNTIME_OPERATIONS.get(target.runtime)
        if runtime_operations is None:
            return TargetActionResult("unsupported", reason="runtime_not_supported")
        if operation not in runtime_operations:
            return TargetActionResult("unsupported", reason="operation_not_supported")
        if not self._valid_arguments(operation, arguments):
            return TargetActionResult("invalid_request", reason="invalid_arguments")

        if operation == "status":
            result, _ = self._probe_status(target_id, target)
            return result

        probe_result, status = self._probe_status(target_id, target)
        if not probe_result.succeeded:
            return probe_result
        if not self._is_current_target(target_id, target):
            return TargetActionResult("stale_target", reason="stale_target")
        if status is None or type(status.get("paused")) is not bool:
            return TargetActionResult("unavailable", reason="target_status_unknown")

        entry = self._inventory_entry(target_id, target)
        if operation not in entry.capabilities:
            return TargetActionResult("unsupported", reason="capability_unavailable")

        method_name, argument_names = _OPERATION_METHODS[operation]
        method = getattr(self, method_name)
        try:
            value = method(target, *(arguments[name] for name in argument_names))
        except Exception as exc:
            logger.warning(
                "Daemon target action %s failed (%s)", operation, type(exc).__name__
            )
            return TargetActionResult("failed", reason="action_failed")
        if value is not True:
            return TargetActionResult("failed", value=value, reason="action_failed")
        return TargetActionResult("completed", value=value)
