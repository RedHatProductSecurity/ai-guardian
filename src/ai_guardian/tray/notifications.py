"""
Tray notification, version checking, and upgrade utility functions.

Split from tray.py (Issue #1492) to separate health monitoring helpers
from tray lifecycle and menu construction.

All functions are stateless or static — state management remains on DaemonTray.
"""

import logging

logger = logging.getLogger(__name__)


def show_notification(title, message):
    """Show a desktop notification."""
    import platform
    import subprocess

    system = platform.system()
    try:
        if system == "Darwin":
            from ai_guardian.daemon.multi_client import _escape_for_applescript

            safe_title = _escape_for_applescript(title)
            safe_msg = _escape_for_applescript(message)
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    f'display notification "{safe_msg}" with title "{safe_title}"',
                ]
            )
        elif system == "Linux":
            subprocess.Popen(["notify-send", title, message])
        elif system == "Windows":
            safe_title = title.replace("'", "''").replace("`", "``").replace("$", "`$")
            safe_msg = message.replace("'", "''").replace("`", "``").replace("$", "`$")
            ps = (
                "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                "[System.Reflection.Assembly]::LoadWithPartialName('System.Drawing') | Out-Null; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; "
                "$n.Icon = [System.Drawing.SystemIcons]::Information; "
                "$n.Visible = $true; "
                f"$n.ShowBalloonTip(5000, '{safe_title}', '{safe_msg}', 'Info')"
            )
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps])
    except OSError:
        pass


def send_config_error_notification():
    """Send config error OS notification (runs in background thread)."""
    try:
        from ai_guardian.tray.plugins import send_notification as _notify

        _notify(
            "AI Guardian",
            "Config error detected — run Doctor from tray menu for details",
        )
    except Exception:
        pass


def parse_version_tuple(version_str):
    """Parse version string into (major, minor, patch) tuple.

    Handles formats like '1.9.0', 'v1.9.0', '1.9.0-dev'.
    Returns None if parsing fails.
    """
    import re

    if not version_str or version_str == "unknown":
        return None
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", version_str)
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def send_version_mismatch_notification(daemon_name, daemon_version, tray_version):
    """Send version mismatch OS notification (runs in background thread)."""
    try:
        from ai_guardian.tray.plugins import send_notification as _notify

        _notify(
            "AI Guardian",
            f"Daemon '{daemon_name}' is running v{daemon_version} — "
            f"upgrade to v{tray_version} recommended",
        )
    except Exception:
        pass


def format_time_ago(seconds):
    """Format a duration in seconds as a human-readable 'X ago' string."""
    if seconds is None:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"
