"""
Per-daemon working directory state.

Stores each daemon's working directory in a JSON file under the state
directory.  The tray owns this state — daemons themselves do not read it.
"""

import json
import logging
import os
import platform
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

from ai_guardian.config.utils import get_state_dir

logger = logging.getLogger(__name__)

WORKING_DIR_FILENAME = "working_dir.json"


def _state_path() -> Path:
    return get_state_dir() / WORKING_DIR_FILENAME


def load_working_dirs() -> Dict[str, str]:
    """Load persisted working directories for all daemons."""
    path = _state_path()
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return {}
        data = json.loads(content)
        if not isinstance(data, dict):
            return {}
        return {
            k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)
        }
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Could not load working dirs: %s", e)
        return {}


def save_working_dirs(data: Dict[str, str]) -> None:
    """Atomically write working directories to disk."""
    path = _state_path()
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(parent),
        prefix=".working-dir-",
        suffix=".tmp",
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


def get_working_dir(name: str) -> str:
    """Get a daemon's working directory, defaulting to home."""
    dirs = load_working_dirs()
    return dirs.get(name, str(Path.home()))


def set_working_dir(name: str, path: str) -> None:
    """Set and immediately persist a daemon's working directory."""
    dirs = load_working_dirs()
    dirs[name] = path
    save_working_dirs(dirs)


def shorten_path(path: str) -> str:
    """Shorten an absolute path using ~ for the home directory."""
    try:
        home = str(Path.home())
        if path == home:
            return "~"
        if path.startswith(home + os.sep):
            return "~" + path[len(home) :]
    except RuntimeError:
        pass  # intentionally silent — best-effort operation
    return path


def choose_directory(current: Optional[str] = None) -> Optional[str]:
    """Open an OS-native directory picker dialog.

    Args:
        current: Directory to start from (shown as default).

    Returns:
        Selected directory path, or None if cancelled.
    """
    system = platform.system()
    try:
        if system == "Darwin":
            return _choose_directory_macos(current)
        elif system == "Linux":
            return _choose_directory_linux(current)
        elif system == "Windows":
            return _choose_directory_windows(current)
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError) as e:
        logger.debug("Directory picker failed: %s", e)
    return None


def _choose_directory_macos(current: Optional[str] = None) -> Optional[str]:
    default_clause = ""
    if current:
        from ai_guardian.daemon.multi_client import _escape_for_applescript

        escaped = _escape_for_applescript(current)
        default_clause = f' default location POSIX file "{escaped}"'
    script = f"POSIX path of (choose folder{default_clause})"
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        return None
    chosen = result.stdout.strip().rstrip("/")
    return chosen or None


def _choose_directory_linux(current: Optional[str] = None) -> Optional[str]:
    from ai_guardian.tray.plugins import _find_icon

    cmd = [
        "zenity",
        "--file-selection",
        "--directory",
        "--title",
        "Choose Working Directory",
    ]
    icon_path = _find_icon("ai-guardian-320.png")
    if icon_path:
        cmd.extend(["--window-icon", icon_path])
    if current:
        cmd.extend(["--filename", current + "/"])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        return None
    chosen = result.stdout.strip()
    return chosen or None


def _choose_directory_windows(current: Optional[str] = None) -> Optional[str]:
    start = ""
    if current:
        start = current.replace("'", "''")
    ps = (
        "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$d.Description = 'Choose Working Directory'; "
        f"$d.SelectedPath = '{start}'; "
        "$d.ShowNewFolderButton = $true; "
        "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath } else { '' }"
    )
    result = subprocess.run(
        ["powershell", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        return None
    chosen = result.stdout.strip()
    return chosen or None
