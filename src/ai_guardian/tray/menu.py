"""
Tray menu building helpers — labels, launchers, and status formatting.

Split from tray.py (Issue #1492) to separate menu construction helpers
from tray lifecycle. All functions are stateless.
"""

import logging

logger = logging.getLogger(__name__)

PANEL_TO_WEB_PATH = {
    "panel-violations": "violations",
    "panel-metrics": "metrics",
    "panel-health-check": "health-check",
}

REFRESH_INTERVAL = 10
WAKE_GAP_THRESHOLD = 30
MAX_DAEMON_SLOTS = 8
MAX_DIR_PAUSE_SLOTS = 16
AUTOSTART_COOLDOWN = 5.0


def about_label(_item=None):
    """Build About menu label with tray version."""
    try:
        from ai_guardian import __version__

        return f"About — v{__version__}"
    except ImportError:
        return "About"


def build_about_text():
    """Build the About dialog text with tray process info."""
    from ai_guardian.daemon.about import get_about_info, format_about_text

    return format_about_text(get_about_info())


def daemon_status_label(
    target,
    has_paused_dirs=False,
    active_project_dir=None,
    project_count=0,
    forwarding_failed=False,
):
    """Format a daemon target into a status header label."""
    from ai_guardian.daemon.working_dir import shorten_path

    if target.status == "running" and has_paused_dirs:
        status_icon = "◐"
    else:
        status_icon = {
            "running": "●",
            "paused": "☾",
            "starting": "◌",
            "stopped": "⚠",
            "error": "✗",
            "unknown": "○",
        }.get(target.status, "○")
    if target.runtime == "container" and target.container_engine:
        runtime = f" ({target.container_engine})"
    elif target.runtime == "kubernetes":
        k8s_parts = ["kubernetes"]
        ctx = getattr(target, "context", None)
        if ctx:
            k8s_parts.append(ctx)
        ns = getattr(target, "namespace", None)
        if ns:
            k8s_parts.append(ns)
        runtime = f" ({'/'.join(k8s_parts)})"
    elif target.runtime != "local":
        runtime = f" ({target.runtime})"
    else:
        runtime = ""
    forwarding_badge = " ⚠" if forwarding_failed else ""
    label = f"{status_icon} {target.name}{runtime}{forwarding_badge}"
    if target.status == "stopped":
        label += " — daemon not running"
    elif target.status == "starting":
        label += " — starting..."
    elif active_project_dir:
        short = shorten_path(active_project_dir)
        if len(short) > 40:
            short = short[:37] + "..."
        label += f" — {short}"
        if project_count > 1:
            label += f" (+{project_count - 1} more)"
    elif getattr(target, "working_dir", None):
        short = shorten_path(target.working_dir)
        if len(short) > 40:
            short = short[:37] + "..."
        label += f" — {short}"
    return label


def launch_console(panel=None):
    """Launch the ai-guardian console in a new terminal window."""
    from ai_guardian.daemon.multi_client import _launch_in_terminal
    from ai_guardian.tray.plugins import resolve_cli_cmd

    cmd_parts = resolve_cli_cmd("console")
    if panel:
        cmd_parts.extend(["--panel", panel])
    _launch_in_terminal(cmd_parts)


def launch_shell(cwd=None):
    """Launch the user's default shell in a new terminal window."""
    import os
    import platform

    from ai_guardian.daemon.multi_client import _launch_in_terminal

    if platform.system() == "Windows":
        shell = os.environ.get("COMSPEC", "cmd.exe")
    else:
        shell = os.environ.get("SHELL", "/bin/sh")
    _launch_in_terminal([shell], keep_open=True, cwd=cwd)


def launch_doctor():
    """Launch ai-guardian doctor in a new terminal window."""
    from ai_guardian.daemon.multi_client import _launch_in_terminal
    from ai_guardian.tray.plugins import resolve_cli_cmd

    _launch_in_terminal(resolve_cli_cmd("doctor"), keep_open=True)


def launch_ide_setup(ide_key):
    """Launch ai-guardian setup --ide <name> in a new terminal window."""
    from ai_guardian.daemon.multi_client import _launch_in_terminal
    from ai_guardian.tray.plugins import resolve_cli_cmd

    _launch_in_terminal(
        resolve_cli_cmd("setup", "--ide", ide_key),
        keep_open=True,
    )


def launch_create_config():
    """Launch ai-guardian setup --create-config in a new terminal."""
    from ai_guardian.daemon.multi_client import _launch_in_terminal
    from ai_guardian.tray.plugins import resolve_cli_cmd

    _launch_in_terminal(
        resolve_cli_cmd("setup", "--create-config"),
        keep_open=True,
    )


def open_web_console(daemon_name="", page=""):
    """Open the web console for a specific daemon and optional page."""
    from ai_guardian.config.utils import get_state_dir
    from ai_guardian.desktop_utils import open_url

    port_file = get_state_dir() / "web-console.port"
    try:
        port = int(port_file.read_text().strip())
        path = f"/{daemon_name}" if daemon_name else ""
        if page:
            path = f"{path}/{page}"
        open_url(f"http://127.0.0.1:{port}{path}")
    except (ValueError, OSError):
        pass
