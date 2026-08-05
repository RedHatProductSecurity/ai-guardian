"""CLI and daemon handler functions for AI Guardian.

These functions were extracted from hook_processing.py to reduce
cross-module coupling. They handle CLI subcommands and daemon
configuration — not hook processing logic.
"""

import json
import logging
import os
import sys
from pathlib import Path

from ai_guardian.config.loaders import _load_config_file
from ai_guardian.constants import ViolationType

logger = logging.getLogger(__name__)


def _format_duration_ago(secs):
    """Format a duration in seconds as a human-readable 'X ago' string.

    Args:
        secs: Number of seconds (int or float)

    Returns:
        str: Formatted string like '30s ago', '5m ago', '2h ago', '3d ago'
    """
    secs = int(secs)
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _handle_violations_command(args):
    """
    Handle the violations subcommand.

    Args:
        args: Parsed command-line arguments

    Returns:
        int: Exit code (0 for success, 1 for error)
    """
    from ai_guardian.violations.logger import ViolationLogger

    violation_logger = ViolationLogger()

    # Handle --clear
    if args.clear:
        if args.yes:
            confirm = "y"
        else:
            confirm = input("Are you sure you want to clear all violations? [y/N] ")
        if confirm.lower() == "y":
            if violation_logger.clear_log():
                print("Violations log cleared successfully")
                return 0
            else:
                print("Error: Failed to clear violations log", file=sys.stderr)
                return 1
        else:
            print("Cancelled")
            return 0

    # Handle --export
    if args.export:
        export_path = Path(args.export)
        if violation_logger.export_violations(export_path, violation_type=args.type):
            print(f"Violations exported to {export_path}")
            return 0
        else:
            print(
                f"Error: Failed to export violations to {export_path}", file=sys.stderr
            )
            return 1

    # Display violations
    violations = violation_logger.get_recent_violations(
        limit=args.limit,
        violation_type=args.type,
        resolved=False,  # Only show unresolved violations by default
    )

    if not violations:
        print("No recent violations found")
        return 0

    # Format and display violations
    print(f"\nRecent Violations (last {len(violations)}):\n")

    for v in violations:
        timestamp = v.get("timestamp", "Unknown")
        vtype = v.get("violation_type", "unknown").upper().replace("_", " ")
        severity = v.get("severity", "warning").upper()
        blocked = v.get("blocked", {})
        suggestion = v.get("suggestion", {})

        # Format severity with color indicators
        severity_indicator = {"WARNING": "⚠", "HIGH": "🔴", "CRITICAL": "🔒"}.get(
            severity, "•"
        )

        print(f"[{timestamp}] {severity_indicator} {vtype} ({severity.lower()})")

        # Display blocked details based on violation type
        if v.get("violation_type") == ViolationType.TOOL_PERMISSION:
            tool_name = blocked.get("tool_name", "Unknown")
            tool_value = blocked.get("tool_value", "")
            reason = blocked.get("reason", "")
            print(f"  Tool: {tool_name}/{tool_value}")
            if blocked.get("file_path"):
                print(f"  File: {blocked['file_path']}")
            print(f"  Reason: {reason}")

        elif v.get("violation_type") == ViolationType.DIRECTORY_BLOCKING:
            file_path = blocked.get("file_path", "Unknown")
            denied_dir = blocked.get("denied_directory", "")
            print(f"  File: {file_path}")
            print(f"  Denied by: {denied_dir}/.ai-read-deny")

        elif v.get("violation_type") == ViolationType.SECRET_DETECTED:
            source = blocked.get("source", "unknown")
            file_path = blocked.get("file_path")
            if file_path:
                location = f"  File: {file_path}"
                line_number = blocked.get("line_number")
                if line_number:
                    end_line = blocked.get("end_line")
                    start_col = blocked.get("start_column")
                    if end_line and end_line != line_number:
                        location += f" (lines {line_number}-{end_line})"
                    elif start_col is not None:
                        location += f" (line {line_number}, col {start_col + 1})"
                    else:
                        location += f" (line {line_number})"
                print(location)
            else:
                print(f"  Source: {source}")
            from ai_guardian.scanners.secret_types import get_secret_type_display

            secret_type = blocked.get("secret_type", "Unknown")
            print(f"  Secret type: {get_secret_type_display(secret_type)}")

        elif v.get("violation_type") in (
            ViolationType.PROMPT_INJECTION,
            ViolationType.JAILBREAK_DETECTED,
        ):
            source = blocked.get("source", "unknown")
            pattern = blocked.get("pattern", "Unknown")
            print(
                f"  Type: {'Jailbreak' if v.get('violation_type') == ViolationType.JAILBREAK_DETECTED else 'Injection'}"
            )
            if blocked.get("file_path"):
                print(f"  File: {blocked['file_path']}")
            else:
                print(f"  Source: {source}")
            print(f"  Pattern: {pattern}")

        # Display suggestion
        action = suggestion.get("action", "")
        if action:
            print(f"  → Suggestion: {action}")

        print()

    print("To allow blocked operations, run: ai-guardian console (when available)")
    print("Or manually edit: ~/.config/ai-guardian/ai-guardian.json\n")

    return 0


def _get_daemon_mode(config=None):
    """Deprecated: daemon mode is no longer used. Always returns 'auto'.

    Kept for backward compatibility with existing imports.
    """
    return "auto"


def _get_client_timeout(config=None):
    """Get daemon client timeout from config.

    Args:
        config: Pre-loaded config dict (skips _load_config_file when provided)

    Returns:
        float: Timeout in seconds (default 2.0, range 0.5-10.0)
    """
    try:
        if config is None:
            config, _ = _load_config_file()
        if config:
            daemon_config = config.get("daemon", {})
            timeout = daemon_config.get("client_timeout_seconds", 2.0)
            try:
                timeout = float(timeout)
            except (TypeError, ValueError):
                return 2.0
            return max(0.5, min(10.0, timeout))
    except Exception:
        pass  # intentionally silent — best-effort operation
    return 2.0


def _set_daemon_mode_in_config(mode):
    """Deprecated: daemon mode is no longer used. No-op.

    Kept for backward compatibility with existing imports.
    """
    pass


def _handle_daemon_command(args):
    """Handle daemon subcommands (start, stop, status, restart)."""
    cmd = getattr(args, "daemon_command", None)

    if cmd == "start":
        # Clear stop-requested marker so auto-start resumes (#775)
        try:
            from ai_guardian.daemon import get_state_dir

            marker = get_state_dir() / "daemon.stop-requested"
            if marker.exists():
                marker.unlink(missing_ok=True)
                logger.info("Cleared stop-requested marker (explicit daemon start)")
        except OSError:
            pass  # intentionally silent — best-effort operation

        if args.background:
            from ai_guardian.daemon.client import start_daemon_background

            if start_daemon_background():
                print("ai-guardian daemon started")
                return 0
            else:
                print("Failed to start daemon in background", file=sys.stderr)
                return 1
        else:
            from ai_guardian.daemon.server import DaemonServer

            idle_timeout = (
                args.idle_timeout if args.idle_timeout is not None else 0
            ) * 60
            server = DaemonServer(
                idle_timeout=idle_timeout,
            )
            try:
                server.start()
            except RuntimeError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
            return 0

    elif cmd == "stop":
        from ai_guardian.daemon.client import is_daemon_running, send_shutdown
        from ai_guardian.daemon import get_pid_path, get_state_dir

        # Write stop-requested marker so auto-start is suppressed briefly
        try:
            marker = get_state_dir() / "daemon.stop-requested"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
        except OSError:
            pass  # intentionally silent — best-effort operation

        if not is_daemon_running():
            # Clean up stale lock file even when daemon isn't running
            lock_path = str(get_pid_path()) + ".lock"
            if os.path.exists(lock_path):
                try:
                    os.unlink(lock_path)
                except OSError:
                    pass  # intentionally silent — best-effort operation
            print("ai-guardian daemon is not running")
            return 0

        if send_shutdown(timeout=_get_client_timeout()):
            print("ai-guardian daemon stopped")
            return 0
        else:
            print("Failed to stop daemon", file=sys.stderr)
            return 1

    elif cmd == "status":
        from ai_guardian.daemon.client import is_daemon_running, send_status_request
        from ai_guardian.daemon import get_pid_path, get_socket_path, is_pid_alive

        if not is_daemon_running():
            pid_path = get_pid_path()
            if pid_path.exists():
                try:
                    pid_info = json.loads(pid_path.read_text())
                    pid = pid_info.get("pid", 0)
                    if pid and is_pid_alive(pid):
                        print(
                            f"ai-guardian daemon: process alive (pid {pid}) but not responsive"
                        )
                        return 1
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read config: %s", e)

            print("ai-guardian daemon: not running")
            return 1

        stats = send_status_request(timeout=_get_client_timeout())
        if stats:
            uptime = stats.get("uptime_seconds", 0)
            hours = int(uptime // 3600)
            minutes = int((uptime % 3600) // 60)
            uptime_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"

            pid_path = get_pid_path()
            pid = "unknown"
            try:
                pid_info = json.loads(pid_path.read_text())
                pid = pid_info.get("pid", "unknown")
            except Exception:
                pass  # intentionally silent — best-effort operation

            blocked = stats.get("blocked_count", 0)
            req_count = stats.get("request_count", 0)
            paused = ""
            if stats.get("paused"):
                remaining = stats.get("pause_remaining_seconds", 0)
                if remaining > 0:
                    mins = int(remaining // 60)
                    secs = int(remaining % 60)
                    paused = f" (PAUSED — {mins}m {secs}s left)"
                else:
                    paused = " (PAUSED — indefinite)"

            reload_ago = stats.get("last_config_reload_seconds_ago")
            if reload_ago is not None:
                config_str = f"loaded (last reload: {_format_duration_ago(reload_ago)})"
            else:
                config_str = "loaded"

            print(f"ai-guardian daemon: running (pid {pid}){paused}")
            print(f"Uptime: {uptime_str}")
            print(f"Hooks processed: {req_count} ({blocked} blocked)")
            print(f"Config: {config_str}")

            sock_path = get_socket_path()
            if sock_path.exists():
                print(f"Socket: {sock_path}")
            elif stats.get("port"):
                print(f"TCP: 127.0.0.1:{stats['port']}")

            project_count = stats.get("project_configs_tracked", 0)
            project_reload_ago = stats.get("last_project_config_reload_seconds_ago")
            if project_count > 0:
                if project_reload_ago is not None:
                    print(
                        f"Project configs tracked: {project_count} (last reload: {_format_duration_ago(project_reload_ago)})"
                    )
                else:
                    print(f"Project configs tracked: {project_count}")

            # Per-directory pauses (#958)
            paused_dirs = stats.get("paused_dirs", {})
            if paused_dirs:
                print(f"Paused directories: {len(paused_dirs)}")
                for d, remaining in paused_dirs.items():
                    if remaining > 0:
                        mins = int(remaining // 60)
                        secs = int(remaining % 60)
                        print(f"  {d} ({mins}m {secs}s left)")
                    else:
                        print(f"  {d} (indefinite)")

            print(f"Active contexts: {stats.get('active_contexts', 0)}")
            print(f"Cached patterns: {stats.get('cached_patterns', 0)}")
        else:
            print("ai-guardian daemon: running (could not fetch stats)")
        return 0

    elif cmd == "restart":
        from ai_guardian.daemon.client import is_daemon_running, send_shutdown

        if is_daemon_running():
            send_shutdown(timeout=_get_client_timeout())
            import time

            time.sleep(0.5)

        args.daemon_command = "start"
        args.background = True
        if not hasattr(args, "idle_timeout"):
            args.idle_timeout = None
        if not hasattr(args, "no_tray"):
            args.no_tray = False
        return _handle_daemon_command(args)

    elif cmd == "reload":
        from ai_guardian.daemon.client import is_daemon_running, send_reload_config

        if not is_daemon_running():
            print("ai-guardian daemon is not running", file=sys.stderr)
            return 1

        if send_reload_config(timeout=_get_client_timeout()):
            print("ai-guardian daemon: config reloaded")
            return 0
        else:
            print("Failed to reload daemon config", file=sys.stderr)
            return 1

    elif cmd == "pause":
        from ai_guardian.daemon.client import is_daemon_running, send_pause_dir

        if not is_daemon_running():
            print("ai-guardian daemon is not running", file=sys.stderr)
            return 1

        directory = getattr(args, "dir", None)
        minutes = getattr(args, "minutes", 0)

        if directory:
            directory = os.path.realpath(directory)
            result = send_pause_dir(directory, minutes, timeout=_get_client_timeout())
            if result and result.get("status") == "dir_paused":
                dur = f" for {minutes} minutes" if minutes > 0 else " indefinitely"
                print(f"ai-guardian daemon: scanning paused{dur} for {directory}")
                return 0
            else:
                print("Failed to pause directory scanning", file=sys.stderr)
                return 1
        else:
            # Global pause via existing socket protocol
            from ai_guardian.daemon.protocol import encode_message, PROTOCOL_VERSION
            from ai_guardian.daemon.client import _connect
            from ai_guardian.daemon.protocol import decode_message

            try:
                sock = _connect(timeout=_get_client_timeout())
                if sock is None:
                    print("Failed to connect to daemon", file=sys.stderr)
                    return 1
                msg = {
                    "version": PROTOCOL_VERSION,
                    "type": "pause",
                    "data": {"minutes": minutes},
                }
                sock.sendall(encode_message(msg))
                response = decode_message(sock, timeout=_get_client_timeout())
                sock.close()
                if response.get("type") == "response":
                    dur = f" for {minutes} minutes" if minutes > 0 else " indefinitely"
                    print(f"ai-guardian daemon: scanning paused{dur}")
                    return 0
            except Exception:
                pass  # intentionally silent — best-effort operation
            print("Failed to pause daemon", file=sys.stderr)
            return 1

    elif cmd == "resume":
        from ai_guardian.daemon.client import is_daemon_running, send_resume_dir

        if not is_daemon_running():
            print("ai-guardian daemon is not running", file=sys.stderr)
            return 1

        directory = getattr(args, "dir", None)

        if directory:
            directory = os.path.realpath(directory)
            result = send_resume_dir(directory, timeout=_get_client_timeout())
            if result and result.get("status") == "dir_resumed":
                print(f"ai-guardian daemon: scanning resumed for {directory}")
                return 0
            else:
                print("Failed to resume directory scanning", file=sys.stderr)
                return 1
        else:
            # Global resume via existing socket protocol
            from ai_guardian.daemon.protocol import encode_message, PROTOCOL_VERSION
            from ai_guardian.daemon.client import _connect
            from ai_guardian.daemon.protocol import decode_message

            try:
                sock = _connect(timeout=_get_client_timeout())
                if sock is None:
                    print("Failed to connect to daemon", file=sys.stderr)
                    return 1
                msg = {"version": PROTOCOL_VERSION, "type": "resume"}
                sock.sendall(encode_message(msg))
                response = decode_message(sock, timeout=_get_client_timeout())
                sock.close()
                if response.get("type") == "response":
                    print("ai-guardian daemon: scanning resumed")
                    return 0
            except Exception:
                pass  # intentionally silent — best-effort operation
            print("Failed to resume daemon", file=sys.stderr)
            return 1

    elif cmd == "reset":
        import signal
        import time

        from ai_guardian.daemon import (
            get_pid_path,
            get_socket_path,
            get_state_dir,
            is_pid_alive,
        )

        state_dir = get_state_dir()
        pid_path = get_pid_path()
        sock_path = get_socket_path()
        lock_path = str(pid_path) + ".lock"
        marker_path = state_dir / "daemon.stop-requested"
        pause_path = state_dir / "daemon.paused"

        actions = []

        # Kill daemon process if running
        pid = None
        if pid_path.exists():
            try:
                pid_info = json.loads(pid_path.read_text())
                pid = pid_info.get("pid", 0)
            except (json.JSONDecodeError, OSError):
                pid = None

        if pid and is_pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass  # intentionally silent — process may have exited

            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and is_pid_alive(pid):
                time.sleep(0.2)

            if is_pid_alive(pid):
                try:
                    if sys.platform == "win32":
                        os.kill(pid, signal.SIGTERM)
                    else:
                        os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass  # intentionally silent — process may have exited
                time.sleep(0.5)
                actions.append(
                    f"Stopping daemon process (pid {pid})... killed (SIGKILL)"
                )
            else:
                actions.append(f"Stopping daemon process (pid {pid})... stopped")

        # Clean up state files
        for path, label in [
            (pid_path, "daemon.pid"),
            (lock_path, "daemon.pid.lock"),
            (sock_path, "daemon.sock"),
            (marker_path, "daemon.stop-requested"),
            (pause_path, "daemon.paused"),
        ]:
            p = Path(path) if isinstance(path, str) else path
            if p.exists():
                try:
                    p.unlink()
                    actions.append(f"Removed {label}")
                except OSError:
                    pass  # intentionally silent — cleanup best-effort

        if not actions:
            print("No daemon state to reset")
        else:
            for a in actions:
                print(a)
            print(
                "Daemon reset complete. Start again with: ai-guardian daemon start -b"
            )
        return 0

    else:
        print(
            "Usage: ai-guardian daemon {start|stop|status|restart|reload|pause|resume|reset}"
        )
        return 1


def _handle_tray_command(args):
    """Handle the standalone tray subcommand (Issue #527)."""
    if getattr(args, "uninstall", False):
        return _handle_tray_uninstall()
    if getattr(args, "install", False):
        return _handle_tray_install(getattr(args, "autostart", False))

    tray_command = getattr(args, "tray_command", None)

    if tray_command == "stop":
        return _handle_tray_stop()

    if tray_command == "restart":
        _handle_tray_stop()
        args.tray_command = "start"
        if not getattr(args, "background", False):
            args.background = True
        return _handle_tray_start(args)

    if tray_command is None or tray_command == "start":
        return _handle_tray_start(args)

    print("Usage: ai-guardian tray {start|stop|restart}")
    return 1


def _handle_tray_install(autostart=False):
    """Create a desktop shortcut and optionally enable autostart."""
    from ai_guardian.daemon.desktop import get_desktop_integration

    desktop = get_desktop_integration()

    if desktop.shortcut_exists():
        print("Desktop shortcut already exists.")
    else:
        if desktop.install_shortcut():
            print("Created AI Guardian shortcut in Applications menu.")
        else:
            print("Failed to create desktop shortcut.", file=sys.stderr)
            return 1

    if autostart:
        if desktop.autostart_exists():
            print("Autostart already configured.")
        else:
            if desktop.install_autostart():
                print("Configured to start on login.")
            else:
                print("Failed to configure autostart.", file=sys.stderr)
                return 1
    return 0


def _handle_tray_uninstall():
    """Remove desktop shortcut and autostart configuration."""
    from ai_guardian.daemon.desktop import get_desktop_integration

    desktop = get_desktop_integration()

    removed_shortcut = desktop.uninstall_shortcut()
    removed_autostart = desktop.uninstall_autostart()

    if removed_shortcut:
        print("Removed desktop shortcut.")
    if removed_autostart:
        print("Removed autostart configuration.")
    if not removed_shortcut and not removed_autostart:
        print("No desktop shortcut or autostart found.")
    return 0


def _handle_tray_stop():
    """Stop the running standalone tray.

    Waits for the process to exit after sending SIGTERM so that a
    subsequent ``tray start`` does not race against a dying process.
    """
    from ai_guardian.tray.app import _get_tray_lock_path
    from ai_guardian.daemon import is_pid_alive

    lock_path = _get_tray_lock_path()
    if not lock_path.exists():
        print("ai-guardian tray is not running")
        return 1

    import os
    import signal
    import time

    try:
        pid = int(lock_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if not is_pid_alive(pid):
                break
            time.sleep(0.1)
        else:
            try:
                force = getattr(signal, "SIGKILL", signal.SIGTERM)
                os.kill(pid, force)
            except ProcessLookupError:
                pass  # intentionally silent — process may have exited

        lock_path.unlink(missing_ok=True)
        print(f"ai-guardian tray stopped (pid {pid})")
        return 0
    except ProcessLookupError:
        print("ai-guardian tray is not running (stale lock file removed)")
        lock_path.unlink(missing_ok=True)
        return 1
    except (ValueError, OSError) as e:
        print(f"Failed to stop tray: {e}", file=sys.stderr)
        return 1


def _handle_tray_start(args):
    """Start the standalone multi-daemon tray client."""
    import subprocess

    from ai_guardian.daemon.path_env import ensure_scanner_path

    ensure_scanner_path()

    if getattr(args, "background", False):
        from ai_guardian.daemon import get_executable_command

        cmd = get_executable_command() + ["tray", "start"]
        if getattr(args, "no_discover", False):
            cmd.append("--no-discover")
        try:
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            print("ai-guardian tray started in background")
            return 0
        except OSError as e:
            print(f"Failed to start tray in background: {e}", file=sys.stderr)
            return 1

    from ai_guardian.tray.app import DaemonTray, is_tray_available, _is_tray_running
    from ai_guardian.daemon.discovery import DaemonDiscovery
    from ai_guardian.daemon.multi_client import MultiDaemonClient

    if not is_tray_available():
        import platform

        msg = "System tray not available."
        if platform.system() == "Linux":
            try:
                import gi  # noqa: F401
            except ImportError:
                msg += (
                    "\nGObject Introspection (gi) is not available in this Python environment."
                    "\nThis is common with 'uv tool install' which creates an isolated env."
                    "\nFix: reinstall with --venv: curl -fsSL .../install.sh | bash -s -- --venv"
                )
        msg += "\nRun 'ai-guardian doctor' for details."
        print(msg, file=sys.stderr)
        return 1

    try:
        if sys.stdin.isatty():
            from ai_guardian.daemon.desktop import get_desktop_integration

            desktop = get_desktop_integration()
            if not desktop.shortcut_exists():
                answer = (
                    input("No desktop shortcut found. Create one? [Y/n] ")
                    .strip()
                    .lower()
                )
                if answer in ("", "y", "yes"):
                    if desktop.install_shortcut():
                        print("Created AI Guardian shortcut in Applications menu.")
                        answer = input("Start on login? [y/N] ").strip().lower()
                        if answer in ("y", "yes"):
                            if desktop.install_autostart():
                                print("Configured to start on login.")
    except Exception:
        pass  # intentionally silent — best-effort operation

    config = {}
    try:
        cfg, _err = _load_config_file()
        if cfg:
            config = cfg
    except Exception:
        pass  # intentionally silent — best-effort operation

    no_discover = getattr(args, "no_discover", False)

    if no_discover:
        disc_config = dict(config)
        disc_config.setdefault("daemon", {}).setdefault("tray", {})
        disc_config["daemon"]["tray"]["discover_containers"] = False
        disc_config["daemon"]["tray"]["discover_kubernetes"] = False
        discovery = DaemonDiscovery(config=disc_config)
    else:
        discovery = DaemonDiscovery(config=config)

    multi_client = MultiDaemonClient()

    from ai_guardian.daemon.client import send_status_request

    get_stats = lambda: send_status_request() or {}

    from ai_guardian.daemon.discovery import DaemonTarget

    _local_target = DaemonTarget("local", "local")

    def _pause_callback(mins):
        if mins > 0:
            multi_client.send_pause(_local_target, mins)
        else:
            multi_client.send_resume(_local_target)

    tray = DaemonTray(
        get_stats_callback=get_stats,
        stop_callback=lambda: None,
        pause_callback=_pause_callback,
        discovery=discovery,
        multi_client=multi_client,
        standalone=True,
    )

    existing_pid = _is_tray_running()
    if existing_pid:
        print(f"Tray is already running (pid {existing_pid})")
        return 0

    print("ai-guardian tray started (multi-daemon mode)")
    tray.run_blocking()
    return 0


def _handle_prompt(args):
    """Handle the unified prompt subcommand (Issue #1143).

    Dispatches to params mode (tray plugin parameter form) or ask mode
    (violation decision dialog) based on --mode flag.
    """
    if args.mode == "params":
        return _handle_prompt_params(args)
    return _handle_prompt_ask(args)


def _handle_prompt_params(args):
    """Handle prompt --mode params: collect params and output resolved command."""
    import json
    import logging as log_mod
    import os
    import tempfile

    prompt_logger = log_mod.getLogger("ai_guardian.prompt")

    if not args.params:
        prompt_logger.error("--params is required for mode=params")
        return 1
    if not args.template:
        prompt_logger.error("--template is required for mode=params")
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        prompt_logger.error("Invalid params JSON: %s", e)
        return 1

    if not isinstance(params, list):
        prompt_logger.error("--params must be a JSON array")
        return 1

    try:
        from ai_guardian.tui.tray_prompt import TrayPromptApp
    except ImportError as e:
        prompt_logger.error("UI dependencies not available: %s", e)
        return 1

    extra_vars = {}
    raw_extra = getattr(args, "extra_vars", None)
    if raw_extra and isinstance(raw_extra, str):
        try:
            extra_vars = json.loads(raw_extra)
            if not isinstance(extra_vars, dict):
                extra_vars = {}
        except (json.JSONDecodeError, TypeError):
            extra_vars = {}

    app = TrayPromptApp(
        params=params,
        command_template=args.template,
        command_type=getattr(args, "type", "terminal"),
        extra_vars=extra_vars,
        title=getattr(args, "title", None),
    )

    if app.needs_terminal and not sys.stdin.isatty():
        prompt_logger.error(
            "tkinter/NiceGUI not available and no interactive terminal for Textual fallback"
        )
        return 1

    result = app.run()

    output_file = getattr(args, "output_file", None)

    if result is None:
        if output_file:
            tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(output_file))
            os.close(tmp_fd)
            os.replace(tmp_path, output_file)
        return 0

    if output_file:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(output_file))
        os.write(tmp_fd, result.encode("utf-8"))
        os.close(tmp_fd)
        os.replace(tmp_path, output_file)
    else:
        print(result)

    return 0


def _handle_prompt_ask(args):
    """Handle prompt --mode ask: show ask dialog and write result to file."""
    import json
    import logging as log_mod
    import os
    import tempfile

    prompt_logger = log_mod.getLogger("ai_guardian.prompt")

    if not args.violation:
        prompt_logger.error("--violation is required for mode=ask")
        return 1

    try:
        violation_data = json.loads(args.violation)
    except json.JSONDecodeError as e:
        prompt_logger.error("Invalid violation JSON: %s", e)
        return 1

    try:
        from ai_guardian.tui.ask_dialog import (
            AskViolationInfo,
            _TkinterAskDialog,
            _NiceGuiAskDialog,
            _TextualAskDialog,
            _map_fallback_to_decision,
            AskResult,
        )
        from ai_guardian.tui.display import (
            _tkinter_available,
            _nicegui_available,
            get_preferred_ui,
        )
    except ImportError as e:
        prompt_logger.error("UI dependencies not available: %s", e)
        return 1

    violation = AskViolationInfo(
        violation_type=violation_data.get("violation_type", ""),
        summary=violation_data.get("summary", ""),
        matched_text=violation_data.get("matched_text", ""),
        config_section=violation_data.get("config_section", ""),
        error_message=violation_data.get("error_message", ""),
        matched_pattern=violation_data.get("matched_pattern", ""),
        file_path=violation_data.get("file_path"),
        line_number=violation_data.get("line_number"),
        start_column=violation_data.get("start_column"),
        project_path=violation_data.get("project_path"),
        session_id=violation_data.get("session_id"),
        tool_name=violation_data.get("tool_name"),
        hook_event=violation_data.get("hook_event"),
        finding_index=violation_data.get("finding_index"),
        total_findings=violation_data.get("total_findings"),
    )

    if violation.project_path:
        from ai_guardian.config.utils import (
            set_project_dir_override,
            clear_project_dir_override,
        )

        set_project_dir_override(violation.project_path)

    try:
        fallback = getattr(args, "fallback", "block")
        timeout = int(getattr(args, "timeout", 300))

        preferred = get_preferred_ui()
        result = None

        if preferred == "headless":
            pass
        elif preferred == "tkinter":
            if _tkinter_available():
                try:
                    result = _TkinterAskDialog(violation, timeout).run()
                except Exception as e:
                    prompt_logger.warning("tkinter ask dialog failed: %s", e)
        elif preferred == "nicegui":
            if _nicegui_available():
                try:
                    result = _NiceGuiAskDialog(violation, timeout).run()
                except Exception as e:
                    prompt_logger.warning("NiceGUI ask dialog failed: %s", e)
        elif preferred == "textual":
            if sys.stdin.isatty():
                try:
                    result = _TextualAskDialog(violation, timeout).run()
                except Exception as e:
                    prompt_logger.warning("Textual ask dialog failed: %s", e)
        else:
            if _tkinter_available():
                try:
                    result = _TkinterAskDialog(violation, timeout).run()
                except Exception as e:
                    prompt_logger.warning("tkinter ask dialog failed: %s", e)

            if result is None and _nicegui_available():
                try:
                    result = _NiceGuiAskDialog(violation, timeout).run()
                except Exception as e:
                    prompt_logger.warning("NiceGUI ask dialog failed: %s", e)

            if result is None and sys.stdin.isatty():
                try:
                    result = _TextualAskDialog(violation, timeout).run()
                except Exception as e:
                    prompt_logger.warning("Textual ask dialog failed: %s", e)

        if result is None:
            decision = _map_fallback_to_decision(fallback)
            result = AskResult(decision=decision)

        output = json.dumps(
            {
                "decision": result.decision.value,
                "allowlist_pattern": result.allowlist_pattern,
                "config_saved": getattr(result, "config_saved", False),
                "source_annotation_saved": getattr(
                    result, "source_annotation_saved", False
                ),
                "ignore_path": getattr(result, "ignore_path", None),
                "ignore_scanner_types": getattr(result, "ignore_scanner_types", None),
            }
        )

        output_file = getattr(args, "output_file", None)
        if output_file:
            tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(output_file))
            os.write(tmp_fd, output.encode("utf-8"))
            os.close(tmp_fd)
            os.replace(tmp_path, output_file)
        else:
            print(output)

        return 0
    finally:
        if violation.project_path:
            clear_project_dir_override()


def _handle_tray_target_select(args):
    """Handle the tray-target-select subcommand: pick daemon targets."""
    import json
    import logging as log_mod
    import os
    import tempfile

    sel_logger = log_mod.getLogger("ai_guardian.tray_target_select")

    try:
        targets = json.loads(args.targets)
    except json.JSONDecodeError as e:
        sel_logger.error("Invalid targets JSON: %s", e)
        return 1

    if not isinstance(targets, list):
        sel_logger.error("--targets must be a JSON array")
        return 1

    if not sys.stdin.isatty():
        sel_logger.error("tray-target-select requires an interactive terminal")
        return 1

    try:
        from ai_guardian.tui.tray_target_selector import TrayTargetSelectorApp
    except ImportError as e:
        sel_logger.error("TUI dependencies not available: %s", e)
        return 1

    app = TrayTargetSelectorApp(targets=targets)
    result = app.run()

    output_file = getattr(args, "output_file", None)

    if result is None:
        if output_file:
            tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(output_file))
            os.close(tmp_fd)
            os.replace(tmp_path, output_file)
        return 0

    if output_file:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(output_file))
        os.write(tmp_fd, result.encode("utf-8"))
        os.close(tmp_fd)
        os.replace(tmp_path, output_file)
    else:
        print(result)

    return 0
