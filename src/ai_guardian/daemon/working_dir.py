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
from typing import Dict, Optional, Tuple

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


def choose_directory(
    current: Optional[str] = None,
    title: str = "Choose Working Directory",
    *,
    screen_bounds=None,
) -> Optional[str]:
    """Open an OS-native directory picker dialog.

    Args:
        current: Directory to start from (shown as default).
        title: Dialog title/description.
        screen_bounds: Optional Tk virtual-screen bounds captured from the
            tray click. Used by the macOS picker when supplied.

    Returns:
        Selected directory path, or None if cancelled.
    """
    system = platform.system()
    try:
        from ai_guardian.tui.display import get_preferred_ui

        if get_preferred_ui() == "headless":
            return None
        if system == "Darwin":
            return _choose_directory_macos(current, title, screen_bounds=screen_bounds)
        elif system == "Linux":
            return _choose_directory_linux(current, title)
        elif system == "Windows":
            return _choose_directory_windows(current, title)
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError) as e:
        logger.debug("Directory picker failed: %s", e)
    return None


def _choose_directory_macos(
    current: Optional[str] = None,
    title: str = "Choose Working Directory",
    *,
    screen_bounds=None,
) -> Optional[str]:
    from ai_guardian.tui.display import _tkinter_available, get_preferred_ui

    if (
        screen_bounds is not None
        and get_preferred_ui() in {"auto", "tkinter"}
        and _tkinter_available()
    ):
        launched, chosen = _choose_directory_tkinter_subprocess(
            current,
            title,
            screen_bounds,
        )
        if launched:
            return chosen

    from ai_guardian.daemon.multi_client import _escape_for_applescript

    escaped_title = _escape_for_applescript(title)
    prompt_clause = f' with prompt "{escaped_title}"'
    default_clause = ""
    if current:
        escaped = _escape_for_applescript(current)
        default_clause = f' default location POSIX file "{escaped}"'
    script = f"POSIX path of (choose folder{prompt_clause}{default_clause})"
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


def _choose_directory_tkinter_subprocess(
    current: Optional[str],
    title: str,
    screen_bounds,
) -> Tuple[bool, Optional[str]]:
    """Run a macOS directory panel from an isolated Tk process.

    The hidden one-pixel parent window is centered on the display captured
    from the tray event. macOS opens the native directory panel relative to
    that parent window, keeping the picker on the same display.
    """
    import json as json_mod
    import sys

    payload = json_mod.dumps(
        {
            "current": current,
            "title": title,
            "screen_bounds": screen_bounds,
        },
        ensure_ascii=False,
    )
    child = (
        "import json, sys; "
        "from ai_guardian.daemon.working_dir import _show_tkinter_directory; "
        "p=json.loads(sys.argv[1]); "
        "v=_show_tkinter_directory(p.get('current'), p['title'], "
        "p.get('screen_bounds')); "
        "print(json.dumps(v, ensure_ascii=False))"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", child, payload],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("Tkinter directory picker could not be shown: %s", exc)
        return False, None
    if result.returncode != 0:
        logger.debug(
            "Tkinter directory picker exited with code %s: %s",
            result.returncode,
            (result.stderr or "").strip()[:200],
        )
        return False, None
    try:
        output = (result.stdout or "").strip().splitlines()
        chosen = json.loads(output[-1]) if output else None
    except (json.JSONDecodeError, IndexError):
        logger.debug("Tkinter directory picker returned invalid output")
        return False, None
    return True, chosen if isinstance(chosen, str) and chosen else None


def _show_tkinter_directory(current, title, screen_bounds):
    """Show the Tk parent for the screen-aware macOS directory panel."""
    import tkinter as tk
    from tkinter import filedialog

    from ai_guardian.tray.dialog_placement import _place_window_on_screen
    from ai_guardian.tui.display import _ensure_tcl_library

    _ensure_tcl_library()
    root = tk.Tk()
    root.title(title)
    root.geometry("1x1")
    _place_window_on_screen(root, screen_bounds, 1, 1)
    root.update_idletasks()
    try:
        root.state("normal")
        root.deiconify()
        root.attributes("-alpha", 0.0)
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    root.lift()
    root.focus_force()
    root.update()
    try:
        selected = filedialog.askdirectory(
            parent=root,
            initialdir=current or None,
            title=title,
        )
    finally:
        try:
            root.attributes("-topmost", False)
        except tk.TclError:
            pass
        root.destroy()
    return selected or None


def _choose_directory_linux(
    current: Optional[str] = None,
    title: str = "Choose Working Directory",
) -> Optional[str]:
    from ai_guardian.tray.plugins import _find_icon

    cmd = [
        "zenity",
        "--file-selection",
        "--directory",
        "--title",
        title,
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


def _choose_directory_windows(
    current: Optional[str] = None,
    title: str = "Choose Working Directory",
) -> Optional[str]:
    start = ""
    if current:
        start = current.replace("'", "''")
    description = title.replace("'", "''")
    ps = (
        "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
        f"$d.Description = '{description}'; "
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
