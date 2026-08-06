"""Shared config load/save helpers for web console pages.

Supports Global/Project scope via session state. When a scope is set in
the NiceGUI session (via the header toggle), load/save automatically route
to the correct config file. Backward compatible — defaults to global scope.

Remote daemon support: when the current daemon target is not local,
reads/writes are routed through DaemonService REST calls instead of
the local filesystem. Remote daemons support project scope when a
project directory is selected via the header project selector.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_daemon_service = None
_current_daemon_name = ""
_current_project_dir = ""


def set_daemon_service(service) -> None:
    """Store DaemonService reference for remote config routing.

    Called once during WebConsole.__init__().
    """
    global _daemon_service
    _daemon_service = service


def set_current_daemon_name(name: str) -> None:
    """Store the current daemon name for config routing.

    Called from create_header() on every page load. Uses a module-level
    variable because NiceGUI's app.storage.user is not accessible from
    run.io_bound() thread pool threads.
    """
    global _current_daemon_name
    _current_daemon_name = name


def set_current_project_dir(project_dir: str) -> None:
    """Store the current project directory for remote project scope routing.

    Called from the header project selector on every page load.
    Uses a module-level variable because NiceGUI's app.storage.user
    is not accessible from run.io_bound() thread pool threads.
    """
    global _current_project_dir
    _current_project_dir = project_dir or ""


def _get_daemon_name() -> str:
    """Get the current daemon name."""
    return _current_daemon_name


def _get_remote_project_dir() -> Optional[str]:
    """Get the project directory for remote daemon routing.

    Returns the module-level project dir (thread-safe), or None if empty.
    """
    return _current_project_dir or None


def _get_current_target():
    """Resolve the DaemonTarget for the current page's daemon, or None.

    If the target is not found in the cached list, refreshes discovery
    once and retries.
    """
    if _daemon_service is None:
        return None
    name = _get_daemon_name()
    if not name:
        return None
    target = _daemon_service.get_target_by_name(name)
    if target is None:
        try:
            _daemon_service.refresh_targets()
            target = _daemon_service.get_target_by_name(name)
        except Exception:
            pass
    return target


def _is_remote_target(target) -> bool:
    """Return True if the target exists and is NOT local."""
    return target is not None and target.runtime != "local"


def _is_target_expected() -> bool:
    """Return True if a daemon name is set (page expects a daemon target).

    When True and _get_current_target() returns None, the daemon is
    unreachable — callers should show an error instead of falling back
    to local filesystem data.
    """
    return bool(_daemon_service and _current_daemon_name)


def _get_current_scope() -> str:
    """Derive config scope from project selection.

    If a project directory is selected, scope is "project".
    Otherwise scope is "global".
    """
    return "project" if _current_project_dir else "global"


def _get_project_dir() -> Optional[str]:
    """Get the project directory from NiceGUI session state."""
    try:
        from nicegui import app

        return app.storage.user.get("project_dir")
    except Exception:
        return None


def load_web_config() -> dict:
    """Load merged/effective ai-guardian.json config.

    Always returns merged config (global + project overrides) regardless of
    current scope. The scope only affects where saves go, not what is displayed.
    Returns {} on missing/invalid.

    Routes through DaemonService for both local and remote targets.
    When a project directory is selected, passes it to get merged
    (global + project) config.
    """
    target = _get_current_target()
    if target is not None and _daemon_service is not None:
        project_dir = _get_remote_project_dir()
        result = _daemon_service.get_config_scoped(
            target, "merged", project_dir=project_dir
        )
        return result if result is not None else {}

    if _is_target_expected():
        return {}

    from pathlib import Path

    from ai_guardian.config.utils import get_config_dir
    from ai_guardian.config.writer import _load_json_file

    global_path = get_config_dir() / "ai-guardian.json"
    global_cfg = _load_json_file(global_path)

    project_dir = _get_remote_project_dir()
    if project_dir:
        from ai_guardian.config.utils import _find_config_in_dir

        project_path = _find_config_in_dir(Path(project_dir))
        if project_path:
            project_cfg = _load_json_file(project_path)
            if project_cfg:
                from ai_guardian.config.utils import deep_merge

                return deep_merge(global_cfg, project_cfg)

    return global_cfg


def load_web_config_global() -> dict:
    """Load global config regardless of current scope.

    Used when pages need to show global defaults alongside project overrides.
    Routes through DaemonService for both local and remote targets.
    """
    target = _get_current_target()
    if target is not None and _daemon_service is not None:
        result = _daemon_service.get_config_scoped(target, "global")
        return result if result is not None else {}

    if _is_target_expected():
        return {}

    try:
        from ai_guardian.config.writer import load_scoped_config

        return load_scoped_config("global")
    except Exception:
        pass  # intentionally silent — optional dependency

    from ai_guardian.config.utils import get_config_dir

    path = get_config_dir() / "ai-guardian.json"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass  # intentionally silent — optional dependency
    return {}


def save_web_config(config: dict) -> None:
    """Write config dict to ai-guardian.json for the current scope.

    Routes through DaemonService for both local and remote targets.
    Uses the current scope and project directory selection to determine
    where the config is written. Falls back to direct filesystem write
    when no daemon target is available.
    """
    target = _get_current_target()
    if target is not None and _daemon_service is not None:
        scope = _get_current_scope()
        project_dir = _get_remote_project_dir()
        if scope == "project" and project_dir:
            _daemon_service.write_config_bulk(
                target, "project", config, project_dir=project_dir
            )
        else:
            _daemon_service.write_config_bulk(target, "global", config)
        _invalidate_config_cache_after_save(scope, project_dir)
        return

    if _is_target_expected():
        logger.warning(
            "Cannot save config: daemon '%s' unreachable", _current_daemon_name
        )
        return

    scope = _get_current_scope()
    project_dir = _get_project_dir()

    try:
        from ai_guardian.config.writer import (
            _resolve_config_path,
            _atomic_config_update,
        )

        config_path = _resolve_config_path(scope, project_dir)

        def updater(existing_config):
            existing_config.clear()
            existing_config.update(config)
            return False, f"Saved web config [{scope}]"

        _atomic_config_update(config_path, updater)
        _invalidate_config_cache_after_save(scope, project_dir)
        return
    except Exception:
        pass  # intentionally silent — optional dependency

    from ai_guardian.config.utils import get_config_dir

    path = get_config_dir() / "ai-guardian.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    _invalidate_config_cache_after_save("global", None)


def _invalidate_config_cache_after_save(scope: str, project_dir: Optional[str]) -> None:
    """Invalidate the daemon config cache after a web console save.

    No-op for remote daemons — the REST bulk write triggers reload on the
    remote side.
    """
    target = _get_current_target()
    if _is_remote_target(target):
        return

    try:
        from ai_guardian.config.loaders import _clear_config_cache

        if scope == "project" and project_dir:
            _clear_config_cache(project_key=project_dir)
        else:
            _clear_config_cache()
    except Exception:
        pass  # intentionally silent — optional dependency


def get_web_config_provenance() -> dict:
    """Get provenance information for the current config.

    Routes through DaemonService with project_dir when selected.
    """
    target = _get_current_target()
    if target is not None and _daemon_service is not None:
        project_dir = _get_remote_project_dir()
        result = _daemon_service.get_config_provenance(target, project_dir=project_dir)
        return result if result is not None else {}

    if _is_target_expected():
        return {}

    try:
        from ai_guardian.config.writer import compute_provenance

        return compute_provenance(_get_remote_project_dir())
    except Exception:
        return {}


def get_web_config_scope_label() -> str:
    """Return human-readable label for the current scope."""
    return "Project" if _current_project_dir else "Global"


def load_web_projects() -> list:
    """Get list of tracked project directories for the current daemon target.

    Returns sorted list of project directory paths. Uses /api/stats
    active_project_dirs which is already populated by DaemonState from
    hook requests.
    """
    if _daemon_service is None:
        return []
    name = _get_daemon_name()
    if not name:
        return []
    target = _daemon_service.get_target_by_name(name)
    if target is None:
        return []
    try:
        status = _daemon_service._client.get_status(target)
        if status:
            return sorted(status.get("active_project_dirs") or [])
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Data access helpers — always route through DaemonService.
# MultiDaemonClient handles local (filesystem) vs remote (REST) internally.
# ---------------------------------------------------------------------------


def _get_max_entries() -> int:
    """Read violation_logging.max_entries from config, default 1000."""
    try:
        cfg = load_web_config()
        return cfg.get("violation_logging", {}).get("max_entries", 1000)
    except Exception:
        return 1000


def load_web_violations(
    limit: Optional[int] = None,
    violation_type: Optional[str] = None,
) -> Optional[dict]:
    """Load violations for the current daemon target.

    Uses violation_logging.max_entries from config as default limit.
    """
    if limit is None:
        limit = _get_max_entries()
    target = _get_current_target()
    if target is None or _daemon_service is None:
        if _is_target_expected():
            return {"violations": [], "count": 0}
        return _local_violations(limit, violation_type)
    return _daemon_service.get_daemon_violations(target, limit, violation_type)


def _local_violations(limit, violation_type):
    """Fallback: load violations from local filesystem."""
    try:
        from ai_guardian.daemon.multi_client import MultiDaemonClient

        return MultiDaemonClient._local_violations(limit, violation_type)
    except Exception:
        return {"violations": [], "count": 0}


def load_web_metrics(since_days: Optional[int] = None) -> Optional[dict]:
    """Load metrics for the current daemon target."""
    target = _get_current_target()
    if target is None or _daemon_service is None:
        if _is_target_expected():
            return {"total_violations": 0, "by_type": {}}
        return _local_metrics(since_days)
    return _daemon_service.get_daemon_metrics(target, since_days)


def _local_metrics(since_days):
    """Fallback: load metrics from local filesystem."""
    try:
        from ai_guardian.daemon.multi_client import MultiDaemonClient

        return MultiDaemonClient._local_metrics(since_days)
    except Exception:
        return {"total_violations": 0, "by_type": {}}


def load_web_audit(
    since: str = "30d",
    until: Optional[str] = None,
    violation_type: Optional[str] = None,
    severity: Optional[str] = None,
) -> Optional[dict]:
    """Load audit data for the current daemon target."""
    target = _get_current_target()
    if target is None or _daemon_service is None:
        if _is_target_expected():
            return {"summary": {"total": 0}, "security_posture": "UNKNOWN"}
        return _local_audit(since, until, violation_type, severity)
    return _daemon_service.get_daemon_audit(
        target, since, until, violation_type, severity
    )


def _local_audit(since, until, violation_type, severity):
    """Fallback: load audit from local filesystem."""
    try:
        from ai_guardian.daemon.multi_client import MultiDaemonClient

        return MultiDaemonClient._local_audit(since, until, violation_type, severity)
    except Exception:
        return {"summary": {"total": 0}, "security_posture": "UNKNOWN"}


def load_web_health_check(fix: bool = False) -> Optional[dict]:
    """Run health checks on the current daemon target."""
    target = _get_current_target()
    if target is None or _daemon_service is None:
        if _is_target_expected():
            return None
        return _local_health_check(fix)
    return _daemon_service.get_daemon_health_check(target, fix)


def _local_health_check(fix):
    """Fallback: run health check locally."""
    try:
        from ai_guardian.daemon.multi_client import MultiDaemonClient

        return MultiDaemonClient._local_health_check(fix)
    except Exception:
        return {"checks": [], "version": "unknown"}


def load_web_smoke_test() -> Optional[dict]:
    """Run smoke tests on the current daemon target (or locally)."""
    target = _get_current_target()
    if target is None or _daemon_service is None:
        if _is_target_expected():
            return None
        return _local_smoke_test()
    return _local_smoke_test()


def _local_smoke_test():
    """Run smoke test locally."""
    try:
        from ai_guardian.smoke_test import SmokeTestRunner

        runner = SmokeTestRunner()
        report = runner.run()
        return {
            "phase1_checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "detail": c.detail,
                }
                for c in report.phase1_checks
            ],
            "phase2_results": [
                {
                    "scanner": r.scanner_name,
                    "display_name": r.display_name,
                    "outcome": r.outcome.value,
                    "expected_action": r.expected_action,
                    "detected": r.actual_detected,
                    "message": r.message,
                    "detail": r.detail,
                    "fix_hint": r.fix_hint,
                    "elapsed_ms": r.elapsed_ms,
                }
                for r in report.phase2_results
            ],
            "phase1_passed": report.phase1_passed,
            "version": report.version,
        }
    except Exception:
        return {
            "phase1_checks": [],
            "phase2_results": [],
            "phase1_passed": False,
            "version": "unknown",
        }


def load_web_performance(since_days: int = 30) -> Optional[dict]:
    """Load latency performance data for the current daemon target."""
    target = _get_current_target()
    if target is None or _daemon_service is None:
        if _is_target_expected():
            return None
        return _local_performance(since_days)
    return _daemon_service.get_daemon_performance(target, since_days)


def _local_performance(since_days):
    """Fallback: load performance from local filesystem."""
    try:
        from ai_guardian.daemon.multi_client import MultiDaemonClient

        return MultiDaemonClient._local_performance(since_days)
    except Exception:
        return {"hook_stats": [], "check_stats": [], "invocation_count": 0}


def load_web_logs(
    limit: int = 500,
    level: str = "INFO",
) -> Optional[dict]:
    """Load log entries for the current daemon target.

    Routes through DaemonService for both local and remote targets.
    """
    target = _get_current_target()
    if target is None or _daemon_service is None:
        if _is_target_expected():
            return None
        return _local_logs(limit, level)
    return _daemon_service.get_daemon_logs(target, limit, level)


def _local_logs(limit, level):
    """Fallback: load logs from local filesystem."""
    try:
        from ai_guardian.daemon.multi_client import MultiDaemonClient

        return MultiDaemonClient._local_logs(limit, level)
    except Exception:
        return {"entries": [], "count": 0}


def is_remote_daemon() -> bool:
    """Check if the current daemon target is remote.

    Use for features that have no REST endpoint (latency, logs) to show
    'not available for remote daemons' messages.
    """
    target = _get_current_target()
    return _is_remote_target(target)
