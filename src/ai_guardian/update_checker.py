"""Version update checking and self-upgrade for ai-guardian.

Centralizes install method detection, PyPI version checking, upgrade
command building, and self-upgrade orchestration. Used by both CLI
(check-update / upgrade subcommands) and tray (self-upgrade menu item).
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_PYPI_URL = "https://pypi.org/pypi/ai-guardian/json"
_PYPI_TIMEOUT = 5
_UPGRADE_TIMEOUT = 120
_CACHE_FILENAME = "update_check.json"


def detect_install_method() -> str:
    """Detect how ai-guardian was installed.

    Returns one of: "uv", "pipx", "venv-pip", "user-pip", "system-pip",
    or "unknown".
    """
    exe = shutil.which("ai-guardian")

    if exe:
        try:
            real = os.path.realpath(exe)
            if "/uv/tools/" in real or "\\uv\\tools\\" in real:
                return "uv"
            if "/pipx/venvs/" in real or "\\pipx\\venvs\\" in real:
                return "pipx"
        except (OSError, ValueError):
            pass

    if sys.prefix != sys.base_prefix:
        return "venv-pip"

    try:
        import ai_guardian as _ag

        mod_file = getattr(_ag, "__file__", "") or ""
        if ".local" in mod_file:
            return "user-pip"
    except ImportError:
        pass

    return "system-pip"


def _get_cached_install_method() -> Optional[str]:
    """Read cached install method from state dir."""
    try:
        cache = UpdateCheckCache.load()
        if cache and cache.install_method:
            return cache.install_method
    except Exception:
        pass
    return None


def fetch_pypi_versions(include_prerelease: bool = False) -> Optional[List[str]]:
    """Fetch all ai-guardian versions from PyPI.

    Returns versions sorted newest-first, or None on network error.
    Pre-release versions are filtered out unless include_prerelease is True.
    """
    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:
        logger.debug("packaging not available, falling back to simple fetch")
        return _fetch_latest_only()

    try:
        req = Request(_PYPI_URL, headers={"Accept": "application/json"})
        with urlopen(req, timeout=_PYPI_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except (URLError, OSError, ValueError, TimeoutError):
        return None

    releases = data.get("releases", {})
    versions = []
    for ver_str in releases:
        try:
            v = Version(ver_str)
        except InvalidVersion:
            continue
        if not include_prerelease and (v.is_prerelease or v.is_devrelease):
            continue
        if not releases[ver_str]:
            continue
        versions.append(v)

    versions.sort(reverse=True)
    return [str(v) for v in versions]


def _fetch_latest_only() -> Optional[List[str]]:
    """Fallback when packaging is unavailable — return only the latest version."""
    try:
        req = Request(_PYPI_URL, headers={"Accept": "application/json"})
        with urlopen(req, timeout=_PYPI_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            ver = data.get("info", {}).get("version")
            return [ver] if ver else None
    except (URLError, OSError, ValueError, TimeoutError):
        return None


def get_latest_version(include_prerelease: bool = False) -> Optional[str]:
    """Get the latest ai-guardian version from PyPI.

    Returns the version string, or None on failure.
    """
    versions = fetch_pypi_versions(include_prerelease=include_prerelease)
    if versions:
        return versions[0]
    return None


def is_upgrade_available(current_version: str, latest_version: Optional[str]) -> bool:
    """Check if latest_version is newer than current_version.

    Handles dev suffixes (e.g. "1.18.0-dev" is treated as < "1.18.0").
    Returns False if latest_version is None.
    """
    if not latest_version:
        return False

    try:
        from packaging.version import InvalidVersion, Version

        current = Version(current_version.replace("-dev", ".dev0"))
        latest = Version(latest_version)
        return latest > current
    except (ImportError, InvalidVersion):
        pass

    cur = current_version.split("-")[0]
    return latest_version != cur


@dataclass
class UpdateCheckCache:
    """Cached PyPI version check result, persisted in the state directory."""

    latest_version: Optional[str] = None
    checked_at: float = 0.0
    install_method: str = ""

    def save(self) -> None:
        """Write cache to state dir."""
        try:
            from ai_guardian.config.utils import get_state_dir

            state_dir = get_state_dir()
            state_dir.mkdir(parents=True, exist_ok=True)
            cache_file = state_dir / _CACHE_FILENAME
            cache_file.write_text(json.dumps(asdict(self)), encoding="utf-8")
        except (OSError, ValueError) as exc:
            logger.debug("Failed to write update cache: %s", exc)

    @classmethod
    def load(cls) -> Optional["UpdateCheckCache"]:
        """Read cache from state dir. Returns None if missing or corrupt."""
        try:
            from ai_guardian.config.utils import get_state_dir

            cache_file = get_state_dir() / _CACHE_FILENAME
            if not cache_file.exists():
                return None
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return cls(
                latest_version=data.get("latest_version"),
                checked_at=float(data.get("checked_at", 0)),
                install_method=data.get("install_method", ""),
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def is_stale(self, max_age_seconds: int) -> bool:
        """Return True if cache is older than max_age_seconds."""
        return (time.time() - self.checked_at) > max_age_seconds


def build_upgrade_command(
    install_method: str, version: Optional[str] = None
) -> List[str]:
    """Build the upgrade command for the detected install method.

    Never includes sudo. Returns the command as a list of strings.
    """
    pkg = f"ai-guardian=={version}" if version else "ai-guardian"

    if install_method == "uv":
        cmd = ["uv", "tool", "install", "--force", pkg]
    elif install_method == "pipx":
        if version:
            cmd = ["pipx", "install", "--force", pkg]
        else:
            cmd = ["pipx", "upgrade", "ai-guardian"]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", pkg]

    return cmd


@dataclass
class UpgradeResult:
    """Result of a self-upgrade attempt."""

    success: bool = False
    output: str = ""
    new_version: Optional[str] = None
    command: List[str] = field(default_factory=list)
    permission_error: bool = False


def run_self_upgrade(
    version: Optional[str] = None, dry_run: bool = False
) -> UpgradeResult:
    """Upgrade the local ai-guardian installation.

    Args:
        version: Specific version to install, or None for latest.
        dry_run: If True, return the command without executing.

    Returns:
        UpgradeResult with success status and output.
    """
    method = detect_install_method()
    cmd = build_upgrade_command(method, version=version)
    result = UpgradeResult(command=cmd)

    if dry_run:
        result.output = " ".join(cmd)
        result.success = True
        return result

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_UPGRADE_TIMEOUT,
        )
        result.output = proc.stdout + proc.stderr
        result.success = proc.returncode == 0

        if proc.returncode != 0 and (
            "permission" in result.output.lower()
            or "errno 13" in result.output.lower()
            or "access is denied" in result.output.lower()
        ):
            result.permission_error = True
            result.output = f"Permission denied. Run manually:\n  sudo {' '.join(cmd)}"

        if result.success:
            try:
                from importlib.metadata import version as pkg_version

                result.new_version = pkg_version("ai-guardian")
            except Exception:
                pass

    except subprocess.TimeoutExpired:
        result.output = f"Upgrade timed out after {_UPGRADE_TIMEOUT}s"
    except FileNotFoundError:
        result.output = f"Command not found: {cmd[0]}"
    except PermissionError:
        result.permission_error = True
        result.output = f"Permission denied. Run manually:\n  sudo {' '.join(cmd)}"

    return result


def perform_full_upgrade(
    version: Optional[str] = None,
    force: bool = False,
    restart_daemon: bool = True,
) -> UpgradeResult:
    """Orchestrate a full upgrade: upgrade package, then restart daemon.

    Does NOT handle tray re-exec — that is the tray's responsibility.

    Args:
        version: Specific version, or None for latest.
        force: If True, skip active session warning.
        restart_daemon: If True, stop and restart the daemon after upgrade.

    Returns:
        UpgradeResult with success status and output.
    """
    if not force:
        active = _get_active_session_count()
        if active > 0:
            logger.warning(
                "%d active session(s). Upgrade will restart daemon "
                "and briefly pause protection.",
                active,
            )

    result = run_self_upgrade(version=version)

    if result.success and restart_daemon:
        if not _restart_daemon():
            result.success = False
            result.output = (
                result.output.rstrip()
                + "\nPackage upgraded, but the daemon failed to restart."
            )

    return result


def _get_active_session_count() -> int:
    """Count active daemon sessions. Returns 0 if daemon not running."""
    try:
        from ai_guardian.daemon.client import send_hook_request

        resp = send_hook_request({"command": "stats"}, timeout=3)
        if isinstance(resp, dict):
            return resp.get("active_sessions", 0)
    except Exception:
        pass
    return 0


def _restart_daemon() -> bool:
    """Stop and restart the daemon. Returns True on success."""
    try:
        from ai_guardian.daemon import is_pid_alive
        from ai_guardian.daemon.client import is_daemon_running

        if not is_daemon_running():
            return True

        logger.info("Stopping daemon for upgrade...")
        subprocess.run(
            [sys.executable, "-m", "ai_guardian", "daemon", "stop"],
            capture_output=True,
            text=True,
            timeout=15,
        )

        logger.info("Starting daemon...")
        subprocess.run(
            [sys.executable, "-m", "ai_guardian", "daemon", "start"],
            capture_output=True,
            text=True,
            timeout=15,
        )

        for _ in range(10):
            time.sleep(0.5)
            if is_daemon_running():
                logger.info("Daemon restarted successfully")
                return True

        logger.warning("Daemon did not restart within 5 seconds")
        return False

    except Exception as exc:
        logger.warning("Daemon restart failed: %s", exc)
        return False
