"""
Thin client for communicating with the ai-guardian daemon.

Used by hook invocations to forward requests to the running daemon
instead of processing them in-process.
"""

import json
import logging
import os
import platform
import shlex
import socket
import subprocess
import time

from ai_guardian.daemon import get_pid_path, get_socket_path, is_pid_alive
from ai_guardian.daemon.protocol import (
    decode_message,
    encode_message,
    make_hook_request,
    make_ml_detect_request,
    make_pause_dir,
    make_ping,
    make_resume_dir,
    make_sdk_check,
    make_shutdown,
    make_status_request,
    make_reload_config,
    make_subscribe,
)

logger = logging.getLogger(__name__)


def is_daemon_running():
    """Check if the daemon is running by testing PID file and socket connectivity.

    Returns:
        bool: True if daemon is running and responsive
    """
    pid_path = get_pid_path()
    if not pid_path.exists():
        return False

    try:
        pid_info = json.loads(pid_path.read_text())
        pid = pid_info.get("pid", 0)
        if not pid:
            return False

        # Check if process exists
        if not is_pid_alive(pid):
            return False

        # Verify socket connectivity with a ping
        sock = _connect(timeout=1.0)
        if sock is None:
            return False

        try:
            sock.sendall(encode_message(make_ping()))
            response = decode_message(sock, timeout=1.0)
            return response.get("type") == "pong"
        finally:
            sock.close()

    except (json.JSONDecodeError, OSError, Exception):
        return False


def send_hook_request(hook_data, timeout=2.0):
    """Send hook data to daemon and get response.

    Args:
        hook_data: Parsed JSON hook data from IDE
        timeout: Connection + response timeout in seconds

    Returns:
        dict or None: Response with 'output' and 'exit_code', or None on failure
    """
    try:
        sock = _connect(timeout)
        if sock is None:
            return None

        try:
            hook_data = {**hook_data, "_daemon_cwd": os.getcwd()}
            request = make_hook_request(hook_data)
            sock.sendall(encode_message(request))
            response = decode_message(sock, timeout=timeout)

            if response.get("type") == "response":
                return response.get("data")
            return None
        finally:
            sock.close()

    except (socket.error, socket.timeout, ConnectionError, ValueError):
        return None
    except Exception as e:
        logger.debug(f"Daemon request failed: {e}")
        return None


def send_sdk_check(check_type, data, timeout=5.0):
    """Send an SDK security check to the daemon.

    Args:
        check_type: "content", "file", "command", "sanitize", or "violations"
        data: Check-specific parameters
        timeout: Connection + response timeout in seconds

    Returns:
        dict or None: Response with check results, or None on failure
    """
    try:
        sock = _connect(timeout)
        if sock is None:
            return None

        try:
            request = make_sdk_check(check_type, data)
            sock.sendall(encode_message(request))
            response = decode_message(sock, timeout=timeout)

            if response.get("type") == "response":
                return response.get("data")
            return None
        finally:
            sock.close()

    except (socket.error, socket.timeout, ConnectionError, ValueError):
        return None
    except Exception as e:
        logger.debug(f"SDK check request failed: {e}")
        return None


def send_engine_test(engine_name, text, use_pattern_server=False, timeout=30.0):
    """Send engine test request to the daemon.

    Routes the scan through the daemon process so listen mode is used
    for engines that support it (e.g. leaktk).

    Args:
        engine_name: Scanner engine preset name
        text: Content string to scan
        use_pattern_server: Resolve pattern-server config path
        timeout: Connection + response timeout in seconds

    Returns:
        dict or None: EngineTestResult as dict, or None on failure
    """
    try:
        sock = _connect(timeout)
        if sock is None:
            return None

        try:
            from ai_guardian.daemon.protocol import make_engine_test

            request = make_engine_test(engine_name, text, use_pattern_server)
            sock.sendall(encode_message(request))
            response = decode_message(sock, timeout=timeout)

            if response.get("type") == "response":
                return response.get("data")
            return None
        finally:
            sock.close()

    except (socket.error, socket.timeout, ConnectionError, ValueError):
        return None
    except Exception as e:
        logger.debug("Engine test request failed: %s", e)
        return None


def _read_pid_from_file():
    """Read daemon PID from PID file.

    Returns:
        int or None: The PID, or None if unreadable
    """
    from ai_guardian.daemon import get_pid_path

    pid_path = get_pid_path()
    try:
        if pid_path.exists():
            return json.loads(pid_path.read_text()).get("pid")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def wait_for_process_death(pid, timeout=5.0):
    """Wait for a process to exit.

    Args:
        pid: Process ID to wait for
        timeout: Maximum seconds to wait

    Returns:
        bool: True if process died within timeout
    """
    from ai_guardian.daemon import is_pid_alive

    if pid is None:
        return True
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_pid_alive(pid):
            return True
        time.sleep(0.1)
    return not is_pid_alive(pid)


def send_shutdown(timeout=2.0):
    """Send shutdown request to the daemon.

    Args:
        timeout: Connection + response timeout in seconds

    Returns:
        bool: True if shutdown was acknowledged
    """
    try:
        sock = _connect(timeout=timeout)
        if sock is None:
            return False

        try:
            sock.sendall(encode_message(make_shutdown()))
            response = decode_message(sock, timeout=timeout)
            return response.get("type") == "response"
        finally:
            sock.close()
    except Exception:
        return False


def send_status_request(timeout=2.0):
    """Request daemon status/stats.

    Args:
        timeout: Connection + response timeout in seconds

    Returns:
        dict or None: Daemon stats, or None on failure
    """
    try:
        sock = _connect(timeout=timeout)
        if sock is None:
            return None

        try:
            sock.sendall(encode_message(make_status_request()))
            response = decode_message(sock, timeout=timeout)
            if response.get("type") == "response":
                return response.get("data")
            return None
        finally:
            sock.close()
    except Exception:
        return None


def send_reload_config(timeout=2.0):
    """Request daemon to reload its configuration.

    Args:
        timeout: Connection + response timeout in seconds

    Returns:
        bool: True if reload was acknowledged
    """
    try:
        sock = _connect(timeout=timeout)
        if sock is None:
            return False

        try:
            sock.sendall(encode_message(make_reload_config()))
            response = decode_message(sock, timeout=timeout)
            return response.get("type") == "response"
        finally:
            sock.close()
    except Exception:
        return False


def send_pause_dir(directory, minutes=0, timeout=2.0):
    """Pause scanning for a specific project directory.

    Args:
        directory: Absolute path of the project directory
        minutes: Pause duration in minutes. 0 = indefinite.
        timeout: Connection + response timeout in seconds

    Returns:
        dict or None: Response data, or None on failure
    """
    try:
        sock = _connect(timeout=timeout)
        if sock is None:
            return None

        try:
            sock.sendall(encode_message(make_pause_dir(directory, minutes)))
            response = decode_message(sock, timeout=timeout)
            if response.get("type") == "response":
                return response.get("data")
            return None
        finally:
            sock.close()
    except Exception:
        return None


def send_resume_dir(directory, timeout=2.0):
    """Resume scanning for a specific project directory.

    Args:
        directory: Absolute path of the project directory
        timeout: Connection + response timeout in seconds

    Returns:
        dict or None: Response data, or None on failure
    """
    try:
        sock = _connect(timeout=timeout)
        if sock is None:
            return None

        try:
            sock.sendall(encode_message(make_resume_dir(directory)))
            response = decode_message(sock, timeout=timeout)
            if response.get("type") == "response":
                return response.get("data")
            return None
        finally:
            sock.close()
    except Exception:
        return None


def send_ml_detect(content, source_type="user_prompt", timeout=2.0):
    """Send ML detection request to daemon.

    Args:
        content: Text to classify for prompt injection
        source_type: "user_prompt" or "file_content"
        timeout: Connection + response timeout in seconds

    Returns:
        dict or None: Detection result with 'available', 'is_injection',
                      'confidence', etc., or None if daemon unreachable
    """
    try:
        sock = _connect(timeout=timeout)
        if sock is None:
            return None

        try:
            sock.sendall(encode_message(make_ml_detect_request(content, source_type)))
            response = decode_message(sock, timeout=timeout)
            if response.get("type") == "response":
                return response.get("data")
            return None
        finally:
            sock.close()
    except Exception:
        return None


def connect_subscriber(timeout=2.0):
    """Connect to daemon as a push event subscriber (#650).

    Returns a connected socket that receives length-prefixed JSON event
    messages whenever daemon state changes. Caller owns the socket and
    must close it when done.

    Returns:
        socket.socket or None: Subscribed socket, or None on failure
    """
    sock = None
    try:
        sock = _connect(timeout=timeout)
        if sock is None:
            return None

        sock.sendall(encode_message(make_subscribe()))
        response = decode_message(sock, timeout=timeout)

        if (
            response.get("type") == "response"
            and response.get("data", {}).get("status") == "subscribed"
        ):
            return sock

        sock.close()
        return None
    except Exception:
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        return None


def start_daemon_background():
    """Start daemon as a background process for lazy start in auto mode.

    Respects the stop-requested marker written by ``daemon stop``.

    Returns:
        bool: True if daemon started successfully
    """
    try:
        # Honour explicit stop — don't auto-restart (#775)
        from ai_guardian.daemon import get_state_dir

        marker = get_state_dir() / "daemon.stop-requested"
        if marker.exists():
            logger.debug("Skipping auto-start: stop-requested marker present")
            return False

        if is_daemon_running():
            logger.warning("Daemon already running, refusing to start duplicate")
            return False

        # Find the ai-guardian command
        cmd = _find_executable()
        daemon_cmd = cmd + ["daemon", "start"]
        logger.info(f"Starting daemon: {' '.join(daemon_cmd)}")

        # Start detached daemon process
        if platform.system() == "Darwin":
            # On macOS, use osascript to launch with GUI session access
            # so the system tray icon can attach to the menu bar
            cmd_str = " ".join(shlex.quote(arg) for arg in daemon_cmd)
            script = f'do shell script "{cmd_str} &> /dev/null &"'
            subprocess.Popen(
                ["osascript", "-e", script],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif platform.system() == "Windows":
            subprocess.Popen(
                daemon_cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(
                    subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
                ),
            )
        else:
            subprocess.Popen(
                daemon_cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        # Wait for daemon to become ready
        sock_path = get_socket_path()
        for _ in range(30):  # up to 3 seconds
            time.sleep(0.1)
            if sock_path.exists() or _tcp_pid_has_port():
                if is_daemon_running():
                    logger.info("Daemon started in background")
                    return True

        logger.warning("Daemon start timed out after 3s")
        return False

    except Exception as e:
        logger.debug(f"Failed to start daemon: {e}")
        return False


def _connect(timeout):
    """Connect to daemon socket (Unix or TCP).

    Args:
        timeout: Connection timeout in seconds

    Returns:
        socket.socket or None: Connected socket, or None on failure
    """
    if platform.system() == "Windows":
        return _connect_tcp(timeout)
    return _connect_unix(timeout)


def _connect_unix(timeout):
    """Connect to Unix domain socket."""
    sock_path = get_socket_path()
    if not sock_path.exists():
        return None

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(str(sock_path))
        return sock
    except (socket.error, OSError):
        return None


def _connect_tcp(timeout):
    """Connect to TCP socket (read port from PID file)."""
    pid_path = get_pid_path()
    if not pid_path.exists():
        return None

    try:
        pid_info = json.loads(pid_path.read_text())
        port = pid_info.get("port")
        if not port:
            return None

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(("127.0.0.1", port))
        return sock
    except (socket.error, OSError, json.JSONDecodeError):
        return None


def _find_executable():
    """Find the ai-guardian command.

    Returns:
        list: Command to invoke ai-guardian
    """
    from ai_guardian.daemon import get_executable_command

    return get_executable_command()


def _tcp_pid_has_port():
    """Check if PID file contains a TCP port (for Windows)."""
    try:
        pid_path = get_pid_path()
        if not pid_path.exists():
            return False
        pid_info = json.loads(pid_path.read_text())
        return "port" in pid_info
    except Exception:
        return False
