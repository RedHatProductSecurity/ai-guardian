"""
Daemon server for ai-guardian.

Listens on a Unix domain socket (or TCP on Windows), accepts hook requests,
processes them via process_hook_data(), and manages lifecycle including
idle timeout and graceful shutdown.
"""

import json
import logging
import os
import platform
import signal
import socket
import threading

from ai_guardian.daemon import (
    get_pid_path,
    get_socket_path,
    is_pid_alive,
    is_pid_active,
)
from ai_guardian.daemon.protocol import (
    decode_message,
    encode_message,
    make_event,
    make_pong,
    make_response,
)
from ai_guardian.daemon.state import DaemonState

logger = logging.getLogger(__name__)

IDLE_CHECK_INTERVAL = 60  # seconds


# Kept as module-level alias for backward compatibility
_is_pid_alive = is_pid_alive


class DaemonServer:
    """Long-running daemon server for ai-guardian."""

    def __init__(self, idle_timeout=0.0, use_tcp=False, enable_rest_api=True):
        """Initialize daemon server.

        Args:
            idle_timeout: Seconds of inactivity before auto-stop (0 to disable)
            use_tcp: Force TCP mode (auto-detected on Windows)
            enable_rest_api: Enable REST API for tray/remote queries
        """
        self._use_tcp = use_tcp or (platform.system() == "Windows")
        self._enable_rest_api = enable_rest_api
        self._server_socket = None
        self._running = False
        self._shutdown_event = threading.Event()
        self._ready_event = threading.Event()
        self._stop_lock = threading.Lock()
        self._rest_api = None
        self._rest_port = 0
        self._tcp_port = 0
        self.state = DaemonState(idle_timeout=idle_timeout)

        # Push notification subscribers (#650)
        self._subscribers = []
        self._subscribers_lock = threading.Lock()
        self.state.add_state_observer(self._broadcast_event)

        from ai_guardian.daemon import set_daemon_state

        set_daemon_state(self.state)

    def start(self):
        """Start the daemon server (blocking).

        Sets up signal handlers, creates socket, and enters accept loop.
        The daemon runs headless — use 'ai-guardian tray' for the system
        tray client.
        """
        from ai_guardian.daemon.path_env import ensure_scanner_path

        ensure_scanner_path()

        self._cleanup_stale()
        self._acquire_pid_lock()
        self._setup_signals()
        self._server_socket = self._setup_socket()
        self._running = True

        # Record source file mtime for dev-mode auto-restart (#1223)
        self.state.record_source_mtime()

        if self._enable_rest_api:
            self._start_rest_api()

        # Write PID file once with all info (pid, rest_port, name, tcp_port)
        self._write_pid_file()

        idle_thread = threading.Thread(
            target=self._idle_check_loop, daemon=True, name="idle-checker"
        )
        idle_thread.start()

        sock_info = self._socket_info()
        name_info = f", name={self._name}" if hasattr(self, "_name") else ""
        logger.info(f"Daemon started (pid {os.getpid()}, {sock_info}{name_info})")
        print(f"ai-guardian daemon started (pid {os.getpid()}, {sock_info}{name_info})")
        print("Use 'ai-guardian tray' to start the system tray client")

        self._ready_event.set()

        try:
            self._accept_loop()
        except Exception as e:
            logger.error(f"Daemon accept loop error: {e}")
        finally:
            self.stop()

    def stop(self):
        """Graceful shutdown (idempotent, thread-safe)."""
        with self._stop_lock:
            if not self._running:
                # start() may have created state files before setting
                # _running — clean them up even on the early-return path
                self._cleanup_state_files()
                return
            self._running = False

        self._shutdown_event.set()
        logger.info("Daemon shutting down...")

        from ai_guardian.daemon import set_daemon_state

        set_daemon_state(None)

        # Flush pending session state to disk before cleanup (#592)
        try:
            self.state.flush_sessions()
        except Exception as e:
            logger.debug(f"Error flushing session state: {e}")

        # Stop persistent listen-mode process (#1590)
        try:
            self.state.stop_listen_manager()
        except Exception as e:
            logger.debug(f"Error stopping listen manager: {e}")

        # Close all subscriber connections (#650)
        with self._subscribers_lock:
            for sock in self._subscribers:
                try:
                    sock.close()
                except OSError:
                    pass
            self._subscribers.clear()

        # Close server socket to unblock accept()
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass  # intentionally silent — daemon comm best-effort
            self._server_socket = None

        # Stop REST API before removing files
        if self._rest_api:
            try:
                self._rest_api.stop()
            except Exception:
                pass  # intentionally silent — cleanup best-effort

        self._cleanup_state_files()
        logger.info("Daemon stopped")

    def _cleanup_state_files(self):
        """Remove socket, PID, and lock files (idempotent).

        PID is deleted first so that _cleanup_stale() in a concurrently starting
        daemon sees no PID file and skips the recycled-PID path. The client-side
        restart loop also uses PID existence as the authoritative "old daemon is
        fully gone" signal, so deleting it first narrows the race window.
        """
        get_pid_path().unlink(missing_ok=True)
        if not self._use_tcp:
            get_socket_path().unlink(missing_ok=True)
        lock_path = getattr(self, "_lock_path", None)
        if lock_path:
            try:
                os.unlink(lock_path)
            except OSError:
                pass  # intentionally silent — cleanup best-effort

    def _setup_socket(self):
        """Create and bind the server socket."""
        if self._use_tcp:
            return self._setup_tcp_socket()
        return self._setup_unix_socket()

    def _setup_unix_socket(self):
        """Create Unix domain socket."""
        sock_path = get_socket_path()
        sock_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing socket file
        if sock_path.exists():
            sock_path.unlink()

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(str(sock_path))
        sock.listen(5)
        sock.settimeout(1.0)  # Allow periodic shutdown checks

        # Owner-only permissions
        os.chmod(str(sock_path), 0o600)
        return sock

    def _setup_tcp_socket(self):
        """Create TCP socket on localhost (Windows fallback)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))  # OS assigns port
        sock.listen(5)
        sock.settimeout(1.0)

        self._tcp_port = sock.getsockname()[1]
        logger.info(f"TCP socket bound to 127.0.0.1:{self._tcp_port}")
        return sock

    def _accept_loop(self):
        """Main accept loop — blocks until stop() is called."""
        while self._running:
            try:
                client_sock, addr = self._server_socket.accept()
                thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock,),
                    daemon=True,
                    name="client-handler",
                )
                thread.start()
            except socket.timeout:
                continue  # Check self._running
            except OSError:
                if self._running:
                    logger.error("Socket accept error")
                break

    def _handle_client(self, client_sock):
        """Handle a single client connection."""
        is_subscriber = False
        try:
            request = decode_message(client_sock, timeout=5.0)
            msg_type = request.get("type", "")

            if msg_type == "hook":
                response_data = self._handle_hook_request(request.get("data", {}))
                response = make_response(response_data)
            elif msg_type == "ping":
                response = make_pong()
            elif msg_type == "shutdown":
                response = make_response({"status": "shutting_down"})
                client_sock.sendall(encode_message(response))
                client_sock.close()
                self.stop()
                return
            elif msg_type == "subscribe":
                response = make_response({"status": "subscribed"})
                client_sock.sendall(encode_message(response))
                self._add_subscriber(client_sock)
                is_subscriber = True
                return
            elif msg_type == "status":
                response = make_response(self.state.get_stats())
            elif msg_type == "pause":
                minutes = request.get("data", {}).get("minutes", 0)
                self.state.pause(minutes)
                response = make_response({"status": "paused", "minutes": minutes})
            elif msg_type == "resume":
                self.state.resume()
                response = make_response({"status": "resumed"})
            elif msg_type == "pause_dir":
                data = request.get("data", {})
                directory = data.get("dir", "")
                minutes = data.get("minutes", 0)
                if not directory:
                    response = make_response({"error": "dir is required"})
                else:
                    self.state.pause_dir(directory, minutes)
                    response = make_response(
                        {
                            "status": "dir_paused",
                            "dir": directory,
                            "minutes": minutes,
                        }
                    )
            elif msg_type == "resume_dir":
                data = request.get("data", {})
                directory = data.get("dir", "")
                if not directory:
                    response = make_response({"error": "dir is required"})
                else:
                    self.state.resume_dir(directory)
                    response = make_response(
                        {
                            "status": "dir_resumed",
                            "dir": directory,
                        }
                    )
            elif msg_type == "reload_config":
                self.state.force_reload_config()
                response = make_response({"status": "config_reloaded"})
            elif msg_type == "ml_detect":
                data = request.get("data", {})
                content = data.get("content", "")
                if not content:
                    response = make_response({"error": "content is required"})
                else:
                    manager = self.state.get_ml_engine_manager()
                    if manager is None:
                        ml_status = self.state.get_ml_status()
                        response = make_response(
                            {
                                "available": False,
                                "error": ml_status.get(
                                    "ml_load_error", "ML model not available"
                                ),
                            }
                        )
                    else:
                        result = manager.detect(content)
                        response = make_response(result)
            elif msg_type == "sdk_check":
                data = request.get("data", {})
                response_data = self._handle_sdk_check(data)
                response = make_response(response_data)
            elif msg_type == "engine_test":
                data = request.get("data", {})
                response_data = self._handle_engine_test(data)
                response = make_response(response_data)
            elif msg_type == "ml_status":
                response = make_response(self.state.get_ml_status())
            else:
                response = make_response({"error": f"Unknown message type: {msg_type}"})

            client_sock.sendall(encode_message(response))
        except (ConnectionError, ValueError, OSError) as e:
            logger.debug(f"Client connection error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error handling client: {e}")
        finally:
            if not is_subscriber:
                try:
                    client_sock.close()
                except OSError:
                    pass  # intentionally silent — cleanup best-effort

    # --- Push notification subscribers (#650) ---

    _MAX_SUBSCRIBERS = 32

    def _add_subscriber(self, sock):
        """Register a socket for push event notifications."""
        sock.settimeout(5.0)
        with self._subscribers_lock:
            if len(self._subscribers) >= self._MAX_SUBSCRIBERS:
                logger.warning(
                    "Subscriber limit reached (%d), rejecting", self._MAX_SUBSCRIBERS
                )
                sock.close()
                return
            self._subscribers.append(sock)
            count = len(self._subscribers)
        logger.info("Subscriber connected (total: %d)", count)

    def _remove_subscriber(self, sock):
        """Remove a disconnected subscriber socket."""
        with self._subscribers_lock:
            try:
                self._subscribers.remove(sock)
            except ValueError:
                pass
        try:
            sock.close()
        except OSError:
            pass

    def _broadcast_event(self, event_type, data=None):
        """Send event to all subscribers, removing broken connections."""
        if not self._subscribers:
            return
        msg = encode_message(make_event(event_type, data))
        dead = []
        with self._subscribers_lock:
            for sock in list(self._subscribers):
                try:
                    sock.sendall(msg)
                except (OSError, socket.timeout):
                    dead.append(sock)
        for sock in dead:
            self._remove_subscriber(sock)

    def _handle_hook_request(self, hook_data):
        """Process a hook request through existing ai-guardian logic.

        Args:
            hook_data: Parsed JSON hook data from IDE

        Returns:
            dict: Response with 'output' and 'exit_code'
        """
        cwd = hook_data.pop("_daemon_cwd", None)
        try:
            self.state.check_project_config(cwd)
        except Exception:
            pass

        if self.state.paused:
            return self._paused_hook_response(hook_data)

        self.state.record_activity()

        # Per-directory pause (#958): skip scanning if this directory is paused
        if cwd and self.state.is_dir_paused(cwd):
            return self._paused_hook_response(hook_data)
        if cwd:
            from ai_guardian.config.utils import (
                set_project_dir_override,
                clear_project_dir_override,
            )

            set_project_dir_override(cwd)

        try:
            self.state.get_config()

            from ai_guardian import process_hook_data

            result = process_hook_data(hook_data, daemon_state=self.state)
        finally:
            if cwd:
                clear_project_dir_override()

        # Track stats
        exit_code = result.get("exit_code", 0)
        violation_type = result.get("_violation_type")
        if exit_code != 0 or result.get("_blocked"):
            self.state.record_blocked(violation_type=violation_type)
            session_key = hook_data.get("session_id") or hook_data.get(
                "transcript_path"
            )
            if session_key:
                self.state.mark_security_reinject(session_key)
        elif result.get("_warning"):
            self.state.record_warning()
        elif result.get("_log_only"):
            for _ in range(result["_log_only"]):
                self.state.record_log_only()

        # Strip internal metadata before returning to client
        result.pop("_blocked", None)
        result.pop("_warning", None)
        result.pop("_log_only", None)
        result.pop("_violation_type", None)
        return result

    def _paused_hook_response(self, hook_data):
        """Return a paused response, still injecting security instructions."""
        from ai_guardian import inject_security_only

        result = inject_security_only(hook_data, daemon_state=self.state)
        return result if result is not None else {"output": "{}", "exit_code": 0}

    def _handle_sdk_check(self, data):
        """Process an SDK security check request.

        Calls the same detection functions as _DirectSession but within
        the daemon process, benefiting from cached config and state.

        Args:
            data: Dict with check_type and check-specific parameters

        Returns:
            dict: Result with blocked, detected, violation_type, message, details
        """
        self.state.record_activity()
        check_type = data.get("check_type", "")

        try:
            from ai_guardian.sdk import _DirectSession

            session = _DirectSession(action="log", config=self.state.get_config())

            if check_type == "content":
                result = session.check_content(
                    data.get("text", ""),
                    filename=data.get("filename", "input"),
                )
            elif check_type == "file":
                result = session.check_file(
                    data.get("file_path", ""),
                    content=data.get("content"),
                )
            elif check_type == "command":
                result = session.check_command(data.get("command", ""))
            elif check_type == "sanitize":
                sanitized = session.sanitize(data.get("text", ""))
                return {"data": sanitized}
            elif check_type == "violations":
                violations = session.get_violations(
                    tool_use_id=data.get("tool_use_id"),
                    session_id=data.get("session_id"),
                    violation_type=data.get("violation_type"),
                    limit=data.get("limit", 50),
                )
                return {"data": {"violations": violations}}
            else:
                return {"error": f"Unknown check_type: {check_type}"}

            return {
                "data": {
                    "blocked": result.blocked,
                    "detected": result.detected,
                    "violation_type": result.violation_type,
                    "message": result.message,
                    "details": result.details,
                }
            }
        except Exception as e:
            logger.error(f"SDK check failed: {e}")
            return {"error": str(e)}

    def _handle_engine_test(self, data):
        """Run an engine test inside the daemon process.

        Benefits from listen mode for engines that support it (e.g. leaktk),
        giving accurate latency measurements.
        """
        self.state.record_activity()
        engine_name = data.get("engine", "")
        text = data.get("text", "")
        use_pattern_server = data.get("use_pattern_server", False)

        if not engine_name or not text:
            return {"error": "engine and text are required"}

        try:
            from ai_guardian.scanners.engine_tester import (
                _result_to_dict,
                test_engine,
            )

            result = test_engine(engine_name, text, use_pattern_server)
            return _result_to_dict(result)
        except Exception as e:
            logger.error("Engine test failed: %s", e)
            return {"error": str(e)}

    def _idle_check_loop(self):
        """Background thread: check idle timeout and cleanup expired contexts."""
        while not self._shutdown_event.is_set():
            self._shutdown_event.wait(IDLE_CHECK_INTERVAL)
            if self._shutdown_event.is_set():
                break

            self.state.cleanup_expired_contexts()

            if self.state.is_idle_timeout_expired():
                logger.info("Idle timeout reached, shutting down daemon")
                self.stop()
                break

    def _setup_signals(self):
        """Set up signal handlers for graceful shutdown."""
        if threading.current_thread() is not threading.main_thread():
            return
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
        except (OSError, ValueError):
            pass  # Signals not available (e.g., non-main thread on some platforms)

    def _signal_handler(self, signum, frame):
        """Handle SIGTERM/SIGINT for graceful shutdown."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.stop()

    def _write_pid_file(self):
        """Write PID file with process info."""
        pid_path = get_pid_path()
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_info = {"pid": os.getpid()}
        if self._use_tcp and self._tcp_port:
            pid_info["port"] = self._tcp_port
        if self._rest_port:
            pid_info["rest_port"] = self._rest_port
        if hasattr(self, "_name") and self._name:
            pid_info["name"] = self._name
        if self.state._source_mtime:
            pid_info["source_mtime"] = self.state._source_mtime
        try:
            from ai_guardian import __version__

            pid_info["version"] = __version__
        except ImportError:
            pass
        pid_path.write_text(json.dumps(pid_info))
        os.chmod(str(pid_path), 0o600)

    def _start_rest_api(self):
        """Start the REST API server for tray/remote queries."""
        try:
            from ai_guardian.daemon.rest_api import DaemonRestAPI
            from ai_guardian.daemon import DEFAULT_REST_PORT
            from ai_guardian.config.loaders import _load_config_file

            full_cfg = {}
            daemon_cfg = {}
            try:
                cfg, _err = _load_config_file()
                if cfg:
                    full_cfg = cfg
                    daemon_cfg = cfg.get("daemon", {})
            except Exception:
                pass  # intentionally silent — optional dependency

            import socket as socket_mod

            self._name = full_cfg.get("name") or socket_mod.gethostname()
            cfg_port = daemon_cfg.get("rest_port", DEFAULT_REST_PORT)

            default_host = "127.0.0.1"
            if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
                default_host = "0.0.0.0"
            host = daemon_cfg.get("rest_host", default_host)
            auth_token = daemon_cfg.get("auth_token")

            for port in range(cfg_port, cfg_port + 10):
                try:
                    self._rest_api = DaemonRestAPI(
                        state=self.state,
                        host=host,
                        port=port,
                        name=self._name,
                        auth_token=auth_token,
                    )
                    self._rest_port = self._rest_api.start()
                    if port != cfg_port:
                        logger.warning(
                            f"REST API port {cfg_port} in use, bound to {port} instead"
                        )
                    else:
                        logger.info(f"REST API started on port {self._rest_port}")
                    return
                except OSError:
                    logger.debug(f"REST API port {port} in use, trying next")
                    self._rest_api = None

            logger.warning(
                f"REST API failed to bind on ports {cfg_port}-{cfg_port + 9}; "
                "REST features (cache status, violations, web console) will be unavailable"
            )
        except Exception as e:
            logger.warning(f"REST API failed to start: {e}")

    def _acquire_pid_lock(self):
        """Atomically create a lock file to prevent concurrent daemon starts.

        Uses O_CREAT|O_EXCL for atomic creation — the first process wins,
        all others get FileExistsError immediately. This closes the TOCTOU
        race between _cleanup_stale() and _write_pid_file() that allowed
        multiple daemons to start simultaneously in containers.
        """
        pid_path = get_pid_path()
        lock_path = str(pid_path) + ".lock"
        try:
            fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            self._lock_path = lock_path
        except FileExistsError:
            try:
                lock_content = open(lock_path).read().strip()
                lock_pid = int(lock_content) if lock_content else 0
                if lock_pid and is_pid_active(lock_pid):
                    raise RuntimeError(
                        f"Another daemon is starting (pid {lock_pid}). "
                        f"Stop it first with: ai-guardian daemon stop"
                    )
                os.unlink(lock_path)
                fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self._lock_path = lock_path
            except (FileExistsError, RuntimeError):
                raise
            except Exception:
                raise RuntimeError(
                    "Another daemon start is in progress. "
                    "Stop it first with: ai-guardian daemon stop"
                )

    def _cleanup_stale(self):
        """Clean up stale socket and PID files from crashed daemon.

        Handles PID recycling in containers: when the PID is alive but
        belongs to a different process (not our daemon), we verify via
        socket connectivity before concluding the daemon is running.

        NEVER deletes PID/socket files when the daemon process is alive
        and the socket exists — doing so orphans a hung but recoverable daemon.
        """
        pid_path = get_pid_path()
        sock_path = get_socket_path()

        if pid_path.exists():
            try:
                pid_info = json.loads(pid_path.read_text())
                old_pid = pid_info.get("pid", 0)
                if old_pid and _is_pid_alive(old_pid):
                    if self._is_old_daemon_responsive():
                        raise RuntimeError(
                            f"Daemon already running (pid {old_pid}). "
                            f"Stop it first with: ai-guardian daemon stop"
                        )
                    # Process is alive but not responsive. Check if socket exists.
                    # If socket exists: daemon is hung, DO NOT delete files (orphans process)
                    # If socket missing: PID recycled (not our daemon), safe to clean up
                    if sock_path.exists():
                        raise RuntimeError(
                            f"Daemon process {old_pid} is alive but unresponsive "
                            f"(socket exists but ping failed). Kill it manually: kill {old_pid}"
                        )
                    # Socket doesn't exist — PID belongs to a different process (recycled)
                    logger.info(
                        f"Cleaned up stale PID file (pid {old_pid}, "
                        f"process exists but is not ai-guardian daemon)"
                    )
                else:
                    logger.info(f"Cleaned up stale PID file (pid {old_pid})")
                pid_path.unlink()
            except (json.JSONDecodeError, OSError):
                pid_path.unlink(missing_ok=True)

        # Clean up stale lock file from crashed prior start (including zombies)
        lock_path = str(pid_path) + ".lock"
        if os.path.exists(lock_path):
            try:
                lock_content = open(lock_path).read().strip()
                lock_pid = int(lock_content) if lock_content else 0
                if not lock_pid or not is_pid_active(lock_pid):
                    os.unlink(lock_path)
                    logger.info("Cleaned up stale daemon lock file")
            except (ValueError, OSError):
                try:
                    os.unlink(lock_path)
                except OSError:
                    pass  # intentionally silent — stale lock cleanup

        # Only clean socket if PID file was successfully removed (daemon is dead)
        if sock_path.exists() and not self._use_tcp and not pid_path.exists():
            sock_path.unlink()
            logger.info("Cleaned up stale socket file")

    def _is_old_daemon_responsive(self):
        """Check if an existing daemon responds on the socket."""
        from ai_guardian.daemon.protocol import make_ping

        try:
            sock_path = get_socket_path()
            if self._use_tcp:
                pid_path = get_pid_path()
                pid_info = json.loads(pid_path.read_text())
                port = pid_info.get("port")
                if not port:
                    return False
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                sock.connect(("127.0.0.1", port))
            else:
                if not sock_path.exists():
                    return False
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                sock.connect(str(sock_path))
            try:
                from ai_guardian.daemon.protocol import decode_message, encode_message

                sock.sendall(encode_message(make_ping()))
                response = decode_message(sock, timeout=1.0)
                return response.get("type") == "pong"
            finally:
                sock.close()
        except Exception:
            return False

    def _socket_info(self):
        """Get human-readable socket info string."""
        if self._use_tcp:
            return f"tcp://127.0.0.1:{self._tcp_port}"
        return f"unix://{get_socket_path()}"
