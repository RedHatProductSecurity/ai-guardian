"""
Daemon service layer for the web console.

Wraps MultiDaemonClient and DaemonDiscovery to provide a unified
interface for web pages to query and control daemons.
"""

import logging
from typing import List, Optional

from ai_guardian.daemon.discovery import DaemonDiscovery, DaemonTarget
from ai_guardian.daemon.multi_client import MultiDaemonClient

logger = logging.getLogger(__name__)


class DaemonService:
    """Provides daemon data and control for web console pages."""

    def __init__(self):
        self._discovery = DaemonDiscovery()
        self._client = MultiDaemonClient()
        self._targets: List[DaemonTarget] = []

    def refresh_targets(self) -> List[DaemonTarget]:
        self._targets = self._discovery.discover_all()
        return self._targets

    @property
    def targets(self) -> List[DaemonTarget]:
        return self._targets

    def get_target_by_name(self, name: str) -> Optional[DaemonTarget]:
        for t in self._targets:
            if t.name == name:
                return t
        return None

    def get_all_daemon_status(self) -> list:
        results = []
        for target in self._targets:
            try:
                status = self._client.get_status(target)
            except Exception:
                status = None
            results.append({"target": target, "status": status})
        return results

    def get_daemon_config(self, target: DaemonTarget) -> Optional[dict]:
        try:
            return self._client.get_config(target)
        except Exception:
            return None

    def get_daemon_violations(
        self,
        target: DaemonTarget,
        limit: int = 50,
        violation_type: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            return self._client.get_violations(
                target, limit=limit, violation_type=violation_type
            )
        except Exception:
            return None

    def get_violation_context(
        self,
        target: DaemonTarget,
        file_path: str,
        line_number: int,
        violation_type: str,
        secret_type: str = "",
        start_column: Optional[int] = None,
        end_column: Optional[int] = None,
    ) -> Optional[dict]:
        try:
            return self._client.get_violation_context(
                target,
                file_path,
                line_number,
                violation_type,
                secret_type,
                start_column=start_column,
                end_column=end_column,
            )
        except Exception:
            return None

    def get_daemon_metrics(
        self,
        target: DaemonTarget,
        since_days: Optional[int] = None,
    ) -> Optional[dict]:
        try:
            return self._client.get_metrics(target, since_days=since_days)
        except Exception:
            return None

    def get_daemon_audit(
        self,
        target: DaemonTarget,
        since: str = "30d",
        until: Optional[str] = None,
        violation_type: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            return self._client.get_audit(
                target,
                since=since,
                until=until,
                violation_type=violation_type,
                severity=severity,
            )
        except Exception:
            return None

    def get_daemon_logs(
        self,
        target: DaemonTarget,
        limit: int = 500,
        level: str = "INFO",
    ) -> Optional[dict]:
        try:
            return self._client.get_logs(target, limit=limit, level=level)
        except Exception:
            return None

    def refresh_pattern_cache(
        self,
        target: DaemonTarget,
    ) -> Optional[dict]:
        try:
            return self._client.refresh_pattern_cache(target)
        except Exception:
            return None

    def get_daemon_health_check(
        self,
        target: DaemonTarget,
        fix: bool = False,
    ) -> Optional[dict]:
        try:
            return self._client.get_health_check(target, fix=fix)
        except Exception:
            return None

    def get_daemon_smoke_test(self, target: DaemonTarget) -> Optional[dict]:
        try:
            return self._client.get_smoke_test(target)
        except Exception:
            return None

    def get_mcp_audit(self, target: DaemonTarget) -> Optional[dict]:
        try:
            return self._client.get_mcp_audit(target)
        except Exception:
            return None

    def get_daemon_performance(
        self,
        target: DaemonTarget,
        since_days: int = 30,
    ) -> Optional[dict]:
        try:
            return self._client.get_performance(target, since_days=since_days)
        except Exception:
            return None

    def get_daemon_traces(
        self,
        target: DaemonTarget,
        agent_name: Optional[str] = None,
        directory: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            return self._client.get_traces(
                target, agent_name=agent_name, directory=directory
            )
        except Exception:
            return None

    def get_daemon_trace_detail(
        self,
        target: DaemonTarget,
        filename: str,
        directory: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            return self._client.get_trace_detail(target, filename, directory=directory)
        except Exception:
            return None

    def pause_daemon(self, target: DaemonTarget, minutes: int) -> bool:
        try:
            return self._client.send_pause(target, minutes)
        except Exception:
            return False

    def resume_daemon(self, target: DaemonTarget) -> bool:
        try:
            return self._client.send_resume(target)
        except Exception:
            return False

    def scan_path(
        self,
        target: DaemonTarget,
        path: str,
    ) -> Optional[dict]:
        try:
            return self._client.scan_path(target, path)
        except Exception:
            return None

    def get_cache_status(
        self,
        target: DaemonTarget,
    ) -> Optional[dict]:
        try:
            return self._client.get_cache_status(target)
        except Exception:
            return None

    def reload_daemon(self, target: DaemonTarget) -> bool:
        try:
            if target.runtime == "local":
                from ai_guardian.daemon.client import send_reload_config

                return send_reload_config()
            result = self._client._rest_request(target, "POST", "/api/reload")
            return result is not None
        except Exception:
            return False

    def get_config_scoped(
        self,
        target: DaemonTarget,
        scope: str = "merged",
        project_dir: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            return self._client.get_config_scoped(target, scope, project_dir)
        except Exception:
            return None

    def get_config_provenance(
        self,
        target: DaemonTarget,
        project_dir: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            return self._client.get_config_provenance(target, project_dir)
        except Exception:
            return None

    def write_config(
        self,
        target: DaemonTarget,
        scope: str,
        section: str,
        key: Optional[str],
        value,
        project_dir: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            return self._client.write_config(
                target,
                scope,
                section,
                key,
                value,
                project_dir,
            )
        except Exception:
            return None

    def write_config_bulk(
        self,
        target: DaemonTarget,
        scope: str,
        config: dict,
        project_dir: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            return self._client.write_config_bulk(target, scope, config, project_dir)
        except Exception:
            return None

    def delete_config_override(
        self,
        target: DaemonTarget,
        section: str,
        key: Optional[str] = None,
        project_dir: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            return self._client.delete_config_override(
                target,
                section,
                key,
                project_dir,
            )
        except Exception:
            return None
