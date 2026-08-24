"""
AI Guardian Daemon Service.

Long-running daemon that processes hook requests over Unix socket (or TCP on
Windows), eliminating per-invocation Python startup overhead and enabling
cross-hook state sharing between PreToolUse and PostToolUse events.
"""

import os
import shutil
import sys

from ai_guardian.config.utils import get_config_dir, get_state_dir

DEFAULT_REST_PORT = 63152
DEFAULT_WEB_CONSOLE_PORT = 0

_current_daemon_state = None


def set_daemon_state(state):
    """Set the process-global DaemonState instance (one per daemon process)."""
    global _current_daemon_state
    _current_daemon_state = state


def get_daemon_state():
    """Get the process-global DaemonState instance, or None."""
    return _current_daemon_state


def is_pid_alive(pid):
    """Check if a process with the given PID is running.

    Args:
        pid: Process ID to check

    Returns:
        bool: True if the process exists
    """
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return False


def is_pid_active(pid):
    """Check if a PID belongs to a live (non-zombie) process.

    Extends is_pid_alive() with zombie detection on Linux (/proc) and
    macOS/BSD (ps).
    """
    if not is_pid_alive(pid):
        return False
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("State:"):
                    return "Z" not in line
    except (FileNotFoundError, PermissionError, OSError):
        pass
    try:
        import subprocess

        result = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            state = result.stdout.strip()
            return bool(state) and "Z" not in state
    except (subprocess.TimeoutExpired, OSError):
        pass
    return is_pid_alive(pid)


def get_executable_command():
    """Resolve the command to launch ai-guardian.

    Tries multiple strategies to find a working Python installation.

    Returns:
        list: Command list, e.g. ['/usr/local/bin/ai-guardian'] or
              ['/path/to/python', '-m', 'ai_guardian']
    """
    # 1. Check if ai-guardian executable exists (best option)
    ag_path = shutil.which("ai-guardian")
    if ag_path:
        return [os.path.abspath(ag_path)]

    # 2. Try to find python in PATH
    python_exe = shutil.which("python")
    if python_exe:
        return [os.path.abspath(python_exe), "-m", "ai_guardian"]

    # 3. Try python3 as fallback
    python_exe = shutil.which("python3")
    if python_exe:
        return [os.path.abspath(python_exe), "-m", "ai_guardian"]

    # 4. Use sys.executable as last resort (may be wrong with uv tool install,
    # but better than nothing if PATH isn't set up)
    return [sys.executable, "-m", "ai_guardian"]


def get_socket_path():
    """Get the Unix socket path for daemon IPC."""
    return get_state_dir() / "daemon.sock"


def get_pid_path():
    """Get the PID file path for daemon process tracking."""
    return get_state_dir() / "daemon.pid"


def get_pause_path():
    """Get the pause state file path for persisting pause across restarts."""
    return get_state_dir() / "daemon.paused"


def get_auth_token_path():
    """Get the path for the auto-generated REST API auth token."""
    return get_state_dir() / "daemon.token"


def get_tray_targets_path():
    """Get the path for manual tray daemon targets config."""
    return get_config_dir() / "tray-targets.json"


def get_tray_plugins_dir():
    """Get the directory for tray plugin JSON files."""
    return get_config_dir() / "tray-plugins"


_IDE_MCP_CONFIGS = [
    ("~/.claude.json", "mcpServers"),
    ("~/.claude/settings.json", "mcpServers"),
    ("~/.cursor/mcp.json", "mcpServers"),
    ("~/.windsurf/mcp.json", "mcpServers"),
    ("~/.gemini/settings.json", "mcpServers"),
    ("~/.cline/mcp_settings.json", "mcpServers"),
    ("~/.augment/settings.json", "mcpServers"),
    ("~/.kiro/settings.json", "mcpServers"),
    ("~/.junie/mcp.json", "mcpServers"),
    ("~/.aider-desk/settings.json", "mcpServers"),
    ("~/.openclaw/settings.json", "mcpServers"),
]


def get_local_menu_tags():
    """Get menu_tags from the local daemon config for plugin filtering."""
    try:
        from ai_guardian.config.loaders import _load_config_file

        cfg, _ = _load_config_file()
        if cfg:
            tags = cfg.get("menu_tags")
            if isinstance(tags, list):
                return [t for t in tags if isinstance(t, str) and t]
    except Exception:
        pass  # intentionally silent — optional dependency
    return []


def is_mcp_installed():
    """Check if ai-guardian MCP server is configured in any supported IDE."""
    import json
    from pathlib import Path

    for config_file, key in _IDE_MCP_CONFIGS:
        try:
            path = Path(config_file).expanduser()
            if path.exists():
                config = json.loads(path.read_text(encoding="utf-8"))
                if "ai-guardian" in config.get(key, {}):
                    return True
        except Exception:
            continue
    return False
