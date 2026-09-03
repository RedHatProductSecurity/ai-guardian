"""
System tray integration using pystray (optional dependency).

Provides a system tray icon with status indicator, violation count, and
menu for pause/resume/quit. Gracefully degrades to no-op if pystray
is not installed.
"""

import logging
import os
import socket
import subprocess
import sys
import threading
import time

from ai_guardian.daemon import is_mcp_installed
from ai_guardian.tray import icons as tray_icons
from ai_guardian.tray import menu as tray_menu
from ai_guardian.tray import notifications as tray_notifications
from ai_guardian.tray import plugins as tray_plugins
from ai_guardian.tray.animation import TrayIconManager
from ai_guardian.tray.health import TrayHealthMonitor
from ai_guardian.tray.menu_builder import TrayMenuBuilder
from ai_guardian.tray.plugin_runner import TrayPluginMenuBuilder

logger = logging.getLogger(__name__)


def _get_tray_lock_path():
    """Get the tray lock file path."""
    from ai_guardian.config.utils import get_state_dir

    return get_state_dir() / "tray.lock"


def _is_tray_running():
    """Check if another tray process is already running.

    Returns the PID (int) of the running tray if found, otherwise False.
    """
    from ai_guardian.daemon import is_pid_alive

    lock_path = _get_tray_lock_path()
    if not lock_path.exists():
        return False
    try:
        pid = int(lock_path.read_text().strip())
        if is_pid_alive(pid):
            return pid
        lock_path.unlink(missing_ok=True)
        return False
    except ValueError:
        lock_path.unlink(missing_ok=True)
        return False


def _write_tray_lock():
    """Write tray lock file with current PID.

    Uses O_CREAT|O_EXCL for atomic creation to prevent concurrent tray
    starts from racing past the _is_tray_running() check.
    """
    from ai_guardian.daemon import is_pid_alive

    lock_path = _get_tray_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        try:
            old_pid = int(lock_path.read_text().strip())
            if is_pid_alive(old_pid):
                raise RuntimeError(f"Tray already starting (pid {old_pid})")
        except (ValueError, OSError):
            pass  # intentionally silent — stale lock cleanup
        lock_path.unlink(missing_ok=True)
        try:
            fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
        except FileExistsError:
            raise RuntimeError("Tray already starting (concurrent lock)")


def _remove_tray_lock():
    """Remove tray lock file."""
    try:
        lock_path = _get_tray_lock_path()
        if lock_path.exists():
            pid = int(lock_path.read_text().strip())
            if pid == os.getpid():
                lock_path.unlink(missing_ok=True)
    except (ValueError, OSError):
        pass  # intentionally silent — stale lock cleanup


def _ensure_system_gi():
    """Make system GObject Introspection visible in isolated environments.

    uv tool install creates an isolated Python env that can't see system
    site-packages. Detect system gi location via the system Python and
    add its parent directory to sys.path so pystray can use AppIndicator.
    """
    import platform

    if platform.system() != "Linux":
        return
    try:
        import gi  # noqa: F401

        return
    except ImportError:
        pass  # intentionally silent — optional dependency
    for python in ("/usr/bin/python3", "/usr/bin/python", "python3", "python"):
        try:
            result = subprocess.run(
                [
                    python,
                    "-c",
                    "import gi; import os; print(os.path.dirname(gi.__path__[0]))",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                site_dir = result.stdout.strip()
                if site_dir not in sys.path:
                    sys.path.insert(0, site_dir)
                    try:
                        import gi  # noqa: F401

                        logger.info("System gi found at %s", site_dir)
                        return
                    except ImportError:
                        sys.path.remove(site_dir)
        except (OSError, subprocess.TimeoutExpired):
            continue


_ensure_system_gi()

try:
    import pystray
    from PIL import Image, ImageDraw

    HAS_PYSTRAY = True
except Exception:
    HAS_PYSTRAY = False


def _suppress_gtk_stderr():
    """Redirect stderr fd to suppress C-level GTK warnings during init."""
    import platform

    if platform.system() != "Linux":
        return None
    try:
        import os

        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        saved_fd = os.dup(2)
        os.dup2(devnull_fd, 2)
        os.close(devnull_fd)
        return saved_fd
    except OSError:
        return None


def _restore_stderr(saved_fd):
    """Restore stderr after GTK init completes."""
    if saved_fd is not None:
        try:
            import os

            os.dup2(saved_fd, 2)
            os.close(saved_fd)
        except OSError:
            pass  # intentionally silent — best-effort operation


def _check_gi_available():
    """Check if GObject Introspection is available (required for tray on Linux).

    Without gi, pystray falls back from AppIndicator3 to the Xorg backend
    which crashes on Wayland sessions.
    """
    try:
        import gi  # noqa: F401

        return True
    except ImportError:
        return False


def is_tray_available():
    """Check if system tray can be displayed (dependencies + display)."""
    if not HAS_PYSTRAY:
        return False
    import os
    import platform

    if os.environ.get("DISPLAY") is None and os.environ.get("WAYLAND_DISPLAY") is None:
        if platform.system() == "Linux":
            return False
    if platform.system() == "Linux":
        if not _check_gi_available():
            logger.warning(
                "GObject Introspection (gi) not available — tray requires it on Linux. "
                "This often happens with 'uv tool install' (isolated environment). "
                "Fix: reinstall with --venv flag: install.sh --venv"
            )
            return False
        if not _check_gnome_appindicator():
            return False
    return True


def _check_gnome_appindicator():
    """Check if GNOME has the AppIndicator extension enabled.

    Returns True if not GNOME, or if the extension is enabled.
    Returns False if GNOME is detected without the extension.
    """
    import os
    import shutil
    import subprocess

    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    if "GNOME" not in desktop.upper():
        return True

    if not shutil.which("gnome-extensions"):
        return True

    try:
        result = subprocess.run(
            ["gnome-extensions", "list", "--enabled"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if "appindicatorsupport@rgcjonas.gmail.com" in result.stdout:
            return True
    except (subprocess.TimeoutExpired, OSError):
        return True

    logger.warning(
        "GNOME detected but AppIndicator extension not enabled — "
        "tray icon will not appear. Fix: "
        "sudo dnf install gnome-shell-extension-appindicator.noarch && "
        "log out/in, then: gnome-extensions enable "
        "appindicatorsupport@rgcjonas.gmail.com"
    )
    return False


class DaemonTray:
    """System tray icon for ai-guardian daemon."""

    _has_web_console = sys.version_info >= (3, 10)

    def __init__(
        self,
        get_stats_callback,
        stop_callback,
        pause_callback,
        discovery=None,
        multi_client=None,
        standalone=False,
    ):
        """Initialize tray icon.

        Args:
            get_stats_callback: Callable returning daemon stats dict
            stop_callback: Callable to stop the daemon
            pause_callback: Callable to toggle pause/resume
            discovery: Optional DaemonDiscovery for multi-daemon support
            multi_client: Optional MultiDaemonClient for action routing
            standalone: True when running as standalone tray (not embedded in daemon)
        """
        self._get_stats = get_stats_callback
        self._stop = stop_callback
        self._pause = pause_callback
        self._discovery = discovery
        self._multi_client = multi_client
        self._standalone = standalone
        self._icon = None
        self._thread = None
        self._pause_timer = None
        self._status = "running"
        self._proactive_level = self._read_proactive_level()
        self._mcp_installed_local = is_mcp_installed()
        self._mcp_installed = self._mcp_installed_local
        self._mcp_installed_per_daemon = {}
        self._targets = []
        self._active_target = None
        self._menu = TrayMenuBuilder(self)
        self._plugins = TrayPluginMenuBuilder(self)
        self._health = TrayHealthMonitor(self)
        self._daemon_about_cache = {}
        self._anim = TrayIconManager(self)
        self._refresh_event = threading.Event()
        self._web_proc = None
        self._web_console_first_start = True
        self._last_autostart_attempt = 0.0
        self._last_stats_snapshot = None

        # Push event subscriber (#650)
        self._subscriber_running = False

        # Remote ask prompt forwarding (#1342)
        self._in_flight_prompts = set()
        self._prompt_poll_running = False
        self._PROMPT_POLL_INTERVAL = 2.5
        self._ask_forwarding_targets: set = set()  # registered successfully
        self._ask_forwarding_failed: set = (
            set()
        )  # remote running but registration failed

        # Remote trace cache (#2188)
        self._trace_catchup_done: set = set()

    def start(self):
        """Start tray icon in a background thread.

        Returns True if started, False if already running or unavailable.
        """
        if not HAS_PYSTRAY:
            logger.info("System tray not available (install pystray and Pillow)")
            return False

        if _is_tray_running():
            logger.info("System tray already running (pid in tray.lock), skipping")
            return False

        _write_tray_lock()

        self._thread = threading.Thread(target=self._run, daemon=True, name="tray-icon")
        self._thread.start()
        return True

    def run_blocking(self):
        """Run tray icon on the current thread (blocks).

        Required on macOS where AppKit needs the main thread.
        Returns True if started, False if already running or unavailable.
        """
        if not HAS_PYSTRAY:
            logger.info("System tray not available")
            return False

        existing_pid = _is_tray_running()
        if existing_pid:
            logger.info(
                "System tray already running (pid %s in tray.lock), skipping",
                existing_pid,
            )
            return False

        _write_tray_lock()

        self._run()

    def stop(self):
        """Stop tray icon."""
        self._anim._stop_discovery_animation()
        self._stats_refresh_running = False
        self._subscriber_running = False
        self._prompt_poll_running = False
        self._unregister_wake_handler()
        self._stop_web_console()
        if self._discovery:
            self._discovery.stop()
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass  # intentionally silent — cleanup best-effort
        _remove_tray_lock()

    def _stop_web_console(self):
        """Stop the web console subprocess if we started it."""
        proc = getattr(self, "_web_proc", None)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        from ai_guardian.config.utils import get_state_dir

        port_file = get_state_dir() / "web-console.port"
        try:
            port_file.unlink(missing_ok=True)
        except OSError:
            pass  # intentionally silent — cleanup best-effort

    from ai_guardian.tray.menu import AUTOSTART_COOLDOWN as _AUTOSTART_COOLDOWN

    def _can_autostart_daemon(self):
        """Check if daemon auto-restart is possible.

        Returns True when the tray is standalone and no stop-requested
        marker exists (user explicitly stopped the daemon).
        """
        if not self._standalone:
            return False
        try:
            from ai_guardian.config.utils import get_state_dir

            marker = get_state_dir() / "daemon.stop-requested"
            return not marker.exists()
        except Exception:
            return False

    def _check_and_autostart_daemon(self):
        """Auto-start local daemon if stopped (idle timeout or crash).

        Only runs in standalone tray mode. Respects stop-requested
        marker and cooldown. A paused daemon is still running and
        is not restarted.

        Returns True if daemon is running after this call.
        """
        if not self._standalone:
            return True
        try:
            from ai_guardian.daemon.client import is_daemon_running

            if is_daemon_running():
                return True
        except Exception:
            return False
        now = time.monotonic()
        if now - self._last_autostart_attempt < self._AUTOSTART_COOLDOWN:
            return False
        self._last_autostart_attempt = now
        try:
            from ai_guardian.daemon.client import start_daemon_background

            if start_daemon_background():
                logger.info("Auto-started daemon from tray interaction")
                self._anim._request_discovery_refresh(wait=False)
                return True
        except Exception:
            pass  # intentionally silent — optional dependency
        return False

    def update_status(self, status):
        """Update tray icon status and manage pause timer.

        Args:
            status: "running", "paused", or "error"
        """
        prev = self._status
        self._status = status
        self._anim._invalidate_discovery_frames()
        if self._icon:
            self._dispatch_to_main(
                lambda: setattr(self._icon, "icon", self._create_icon())
            )
        if status == "paused" and prev != "paused":
            self._start_pause_timer()
        elif status != "paused" and prev == "paused":
            self._stop_pause_timer()

    def flash_reload(self):
        """Record config reload (no visual change with monochrome icons)."""
        pass

    @staticmethod
    def _ensure_macos_activation_policy():
        """Set NSApplicationActivationPolicyAccessory and bundle identity on macOS.

        When launched from an .app bundle wrapper, the process may lose
        its Info.plist association after exec, so LSUIElement=True has no
        effect.  Setting the policy explicitly ensures the status bar
        icon appears regardless of launch method (issue #691).

        Also sets the process bundle identifier to match the installed
        .app so macOS notification center displays the AI Guardian icon
        instead of the generic Python icon (issue #769).
        """
        import platform

        if platform.system() != "Darwin":
            return
        try:
            import AppKit
            import Foundation

            info = Foundation.NSBundle.mainBundle().infoDictionary()
            if info.get("CFBundleIdentifier") is None:
                info["CFBundleIdentifier"] = "com.itdove.ai-guardian.tray"
                info["CFBundleName"] = "AI Guardian Tray"
            app = AppKit.NSApplication.sharedApplication()
            app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
            try:
                from ai_guardian.tray.plugins import _find_icon

                icns_path = _find_icon("ai-guardian.icns")
                if icns_path:
                    icon_image = AppKit.NSImage.alloc().initWithContentsOfFile_(
                        icns_path
                    )
                    if icon_image:
                        app.setApplicationIconImage_(icon_image)
            except Exception:
                pass  # intentionally silent — optional dependency
        except Exception:
            pass  # intentionally silent — optional dependency

    def _run(self):
        """Run tray icon (blocking, called in thread)."""
        self._ensure_macos_activation_policy()
        menu = pystray.Menu(
            *self._menu._build_single_daemon_menu_items(),
            *self._plugins._build_single_daemon_plugin_items(),
            *self._menu._build_single_daemon_daemon_items(),
            *self._menu._build_multi_daemon_menu_items(),
            pystray.Menu.SEPARATOR,
            *self._plugins._build_global_plugin_items(),
            *self._menu._build_ide_setup_menu_items(),
            pystray.MenuItem("Restart", self._on_restart_tray),
            pystray.MenuItem("Quit", self._on_quit),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                tray_menu.about_label,
                self._menu._on_about,
                enabled=lambda _: (
                    any(t.status in ("running", "paused") for t in self._targets)
                    or self._can_autostart_daemon()
                ),
            ),
        )
        self._icon = pystray.Icon(
            "ai-guardian", self._create_icon(), "AI Guardian Tray", menu
        )
        if self._discovery:
            self._anim._is_initial_discovery = True
            self._anim._discovery_in_progress = True
            self._anim._start_discovery_animation(delay=0)
            self._discovery.start_background_discovery(self._on_targets_updated)
            self._discovery.start_container_event_stream(
                callback=lambda: self._refresh_event.set()
            )
        self._start_stats_refresh()
        self._start_subscriber()
        self._start_prompt_poll()
        self._start_web_console()
        self._register_wake_handler()
        import platform

        if platform.system() == "Linux":
            saved_fd = _suppress_gtk_stderr()
            threading.Timer(0.5, _restore_stderr, args=[saved_fd]).start()
            self._icon.run()
        else:
            self._icon.run()

    def _create_icon(self):
        """Create tray icon from monochrome shield template images."""
        icon_path = tray_icons.find_tray_icon_path()
        img = None
        if icon_path is not None:
            try:
                img = Image.open(icon_path).convert("RGBA")
            except Exception:
                pass
        if img is None:
            img = tray_icons.create_fallback_icon(22)
        if tray_icons.needs_dark_icon():
            img = tray_icons.invert_icon(img)
        if self._status == "paused":
            img = tray_icons.apply_paused_dimming(img)
        if self._health._stale_code_warned:
            img = tray_icons.apply_stale_overlay(img)
        return img

    def _rebuild_tray(self):
        """Rebuild tray icon and menu after system wake."""
        if not self._icon:
            return
        try:
            self._icon.icon = self._create_icon()
            self._icon.update_menu()
            logger.info("Tray icon rebuilt after system wake")
        except Exception as e:
            logger.debug("Failed to rebuild tray icon: %s", e)

    def _on_change_proactive(self, level):
        """Change MCP proactive check level in config file."""
        try:
            import json
            from ai_guardian.config.utils import get_config_dir

            config_path = get_config_dir() / "ai-guardian.json"
            if config_path.exists():
                config = json.loads(config_path.read_text(encoding="utf-8"))
            else:
                config = {}

            if "mcp_server" not in config:
                config["mcp_server"] = {}
            config["mcp_server"]["proactive_level"] = level

            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(config, indent=2) + "\n", encoding="utf-8"
            )
            self._proactive_level = level
            logger.info(f"MCP proactive level changed to '{level}'")
        except Exception as e:
            logger.debug(f"Failed to change proactive level: {e}")

    @staticmethod
    def _read_proactive_level():
        """Read current MCP proactive level from config file."""
        try:
            import json
            from ai_guardian.config.utils import get_config_dir

            config_path = get_config_dir() / "ai-guardian.json"
            if config_path.exists():
                config = json.loads(config_path.read_text(encoding="utf-8"))
                return config.get("mcp_server", {}).get("proactive_level", "low")
        except Exception:
            pass  # intentionally silent — optional dependency
        return "medium"

    def _is_mcp_for_current_target(self):
        """Check MCP installed status for the current single-daemon target."""
        if not self._targets:
            return self._mcp_installed_local
        target = self._targets[0]
        key = (target.name, target.runtime)
        return self._mcp_installed_per_daemon.get(key, self._mcp_installed_local)

    def _is_mcp_for_slot(self, idx):
        """Check MCP installed status for a multi-daemon slot."""
        if idx >= len(self._targets):
            return self._mcp_installed_local
        target = self._targets[idx]
        key = (target.name, target.runtime)
        return self._mcp_installed_per_daemon.get(key, self._mcp_installed_local)

    def _start_web_console(self):
        """Start the web console server as a subprocess.

        Always passes ``--no-open`` — browser is never opened
        automatically.  Users open the console via the tray menu
        or ``ai-guardian console --web`` (#1737).
        """
        from ai_guardian.config.utils import get_state_dir

        port_file = get_state_dir() / "web-console.port"
        if port_file.exists():
            if self._is_web_console_alive(port_file):
                logger.debug("Web console already running, reusing")
                return
            try:
                port_file.unlink()
            except OSError:
                pass  # intentionally silent — cleanup best-effort
        try:
            cmd = tray_plugins.resolve_cli_cmd("console") + ["--web", "--no-open"]
            logger.debug("Starting web console with command: %s", cmd)
            self._web_proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(
                "Web console started (pid %d, cmd: %s)", self._web_proc.pid, cmd[0]
            )
            is_first = self._web_console_first_start
            self._web_console_first_start = False
            threading.Thread(
                target=self._notify_web_console_ready,
                args=(is_first,),
                daemon=True,
                name="web-console-notify",
            ).start()
        except Exception as e:
            logger.error(
                "Web console failed to start: %s (cmd: %s)",
                e,
                cmd if "cmd" in locals() else "N/A",
            )

    def _notify_web_console_ready(self, is_first_start=True):
        """Wait for web console to be ready, update menu, then notify.

        Args:
            is_first_start: When True, send a desktop notification.
                When False (daemon restart), skip the notification (#1737).
        """
        from ai_guardian.config.utils import get_state_dir

        port_file = get_state_dir() / "web-console.port"
        for _ in range(30):
            if port_file.exists() and self._is_web_console_alive(port_file):
                if self._icon:
                    self._icon.update_menu()
                if is_first_start:
                    try:
                        port = int(port_file.read_text().strip())
                        tray_notifications.show_notification(
                            "Web Console Ready",
                            f"http://127.0.0.1:{port}",
                        )
                    except (ValueError, OSError):
                        pass  # intentionally silent — invalid value uses default
                return
            time.sleep(1)

    @staticmethod
    def _is_web_console_alive(port_file):
        """Check if the web console at the port file is reachable."""
        import socket

        try:
            port = int(port_file.read_text().strip())
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect(("127.0.0.1", port))
            sock.close()
            return True
        except (ValueError, OSError):
            return False

    @staticmethod
    def _is_web_console_ready():
        """Check if web console is running and reachable."""
        from ai_guardian.config.utils import get_state_dir

        port_file = get_state_dir() / "web-console.port"
        if not port_file.exists():
            return False
        return DaemonTray._is_web_console_alive(port_file)

    def _ensure_web_console_ready(self):
        """Restart web console if dead, wait briefly, return readiness."""
        if self._is_web_console_ready():
            return True
        logger.info("Web console not ready, attempting restart")
        self._start_web_console()
        for _ in range(5):
            time.sleep(1)
            if self._is_web_console_ready():
                return True
        logger.warning("Web console did not become ready after restart attempt")
        return False

    def _start_pause_timer(self):
        """Start a background thread that updates the countdown and auto-resumes.

        Uses PyObjCTools.AppHelper.callAfter() to dispatch UI updates
        (update_menu, icon change) to the main thread on macOS.
        """
        self._pause_timer_running = True

        def _tick():
            import time

            while self._pause_timer_running and self._status == "paused":
                stats = self._get_stats()
                if not stats:
                    time.sleep(1)
                    continue
                remaining = stats.get("pause_remaining_seconds", 0)
                still_paused = stats.get("paused", False)
                if remaining <= 0 and self._status == "paused" and not still_paused:
                    self._status = "running"
                    self._dispatch_to_main(self._refresh_icon_running)
                    break
                self._dispatch_to_main(self._refresh_menu)
                time.sleep(1)

        self._pause_timer = threading.Thread(
            target=_tick, daemon=True, name="pause-timer"
        )
        self._pause_timer.start()

    @staticmethod
    def _dispatch_to_main(func):
        """Dispatch a callable to the GUI main loop.

        macOS: uses PyObjCTools.AppHelper.callAfter.
        Linux: uses GLib.idle_add to schedule on the GTK main loop,
               avoiding thread-safety issues that cause blank menu text.
        Other: calls directly.
        """
        try:
            from PyObjCTools.AppHelper import callAfter

            callAfter(func)
            return
        except ImportError:
            pass  # intentionally silent — optional dependency
        try:
            import platform

            if platform.system() == "Linux":
                from gi.repository import GLib

                GLib.idle_add(func)
                return
        except (ImportError, ValueError):
            pass  # intentionally silent — optional dependency
        try:
            func()
        except Exception:
            pass  # intentionally silent — optional dependency

    def _refresh_menu(self):
        """Refresh the tray menu (must be called on main thread)."""
        if self._icon:
            try:
                self._icon.update_menu()
            except Exception:
                pass  # intentionally silent — best-effort operation

    def _refresh_menu_if_changed(self):
        """Refresh the tray menu only if stats changed.

        GNOME's AppIndicator rebuilds the entire DBus menu tree on
        update_menu(), causing a visible blank flash.  Skip the call
        when nothing has changed.
        """
        snapshot = self._build_stats_snapshot()
        if snapshot == self._last_stats_snapshot:
            return
        self._last_stats_snapshot = snapshot
        self._refresh_menu()

    def _build_stats_snapshot(self):
        """Build a hashable snapshot of menu-relevant state."""
        try:
            stats = self._get_stats()
            paused_dirs = stats.get("paused_dirs") or {}
            return (
                stats.get("request_count"),
                stats.get("blocked_count"),
                stats.get("warning_count"),
                stats.get("violation_count"),
                stats.get("paused"),
                stats.get("pause_remaining_seconds", 0) // 5,
                stats.get("config_error"),
                self._status,
                len(self._targets),
                tuple((t.name, t.status) for t in self._targets),
                tuple(sorted(paused_dirs.keys())) if paused_dirs else (),
            )
        except Exception:
            return None

    def _refresh_icon_running(self):
        """Refresh icon and menu to reflect resumed state (main thread)."""
        self._status = "running"
        if self._icon:
            self._icon.icon = self._create_icon()
        self._refresh_menu()

    def _stop_pause_timer(self):
        """Stop the pause countdown timer."""
        self._pause_timer_running = False
        self._pause_timer = None

    def _sync_pause_state(self):
        """Sync tray status from daemon stats (handles external pause/resume)."""
        if self._is_multi_daemon():
            self._update_global_pause_status()
            return
        stats = self._get_stats()
        if not stats:
            return
        is_paused = stats.get("paused", False)
        if is_paused and self._status != "paused":
            self.update_status("paused")
        elif not is_paused and self._status == "paused":
            self.update_status("running")
        if self._targets:
            self._targets[0].status = "paused" if is_paused else "running"

    def _update_global_pause_status(self):
        """Set tray icon to paused only when ALL daemons are paused."""
        if not self._targets:
            return
        all_paused = True
        for t in self._targets:
            if t.status not in ("running", "paused"):
                continue
            if self._multi_client:
                stats = self._multi_client.get_status(t) or {}
            else:
                stats = self._get_stats()
            target_paused = stats.get("paused", False)
            t.status = "paused" if target_paused else "running"
            if not target_paused:
                all_paused = False
        if all_paused:
            self.update_status("paused")
        else:
            self.update_status("running")

    def _register_wake_handler(self):
        """Register OS-level wake notification handler.

        On macOS, subscribes to NSWorkspaceDidWakeNotification for
        immediate wake detection.  Other platforms rely on timer gap
        detection in _start_stats_refresh().
        """
        import platform

        self._wake_observer = None
        if platform.system() != "Darwin":
            return
        try:
            from AppKit import NSWorkspace

            center = NSWorkspace.sharedWorkspace().notificationCenter()

            def _on_wake(notification):
                logger.info("macOS wake notification received")
                self._dispatch_to_main(self._rebuild_tray)

            token = center.addObserverForName_object_queue_usingBlock_(
                "NSWorkspaceDidWakeNotification",
                None,
                None,
                _on_wake,
            )
            self._wake_observer = (center, token)
            logger.debug("Registered macOS wake notification handler")
        except Exception:
            logger.debug("macOS wake handler unavailable, using timer fallback")

    def _unregister_wake_handler(self):
        """Remove OS-level wake notification observer."""
        if getattr(self, "_wake_observer", None) is None:
            return
        try:
            center, token = self._wake_observer
            center.removeObserver_(token)
        except Exception:
            pass  # intentionally silent — best-effort operation
        self._wake_observer = None

    def _start_stats_refresh(self):
        """Start a background thread that refreshes menu counters periodically."""
        self._stats_refresh_running = True
        self._last_refresh_wallclock = time.time()

        def _refresh():
            while self._stats_refresh_running:
                self._refresh_event.wait(timeout=tray_menu.REFRESH_INTERVAL)
                self._refresh_event.clear()
                now = time.time()
                elapsed = now - self._last_refresh_wallclock
                self._last_refresh_wallclock = now

                if elapsed > tray_menu.WAKE_GAP_THRESHOLD:
                    logger.info(
                        "System wake detected (%.1fs gap), rebuilding tray",
                        elapsed,
                    )
                    self._dispatch_to_main(self._rebuild_tray)

                if self._stats_refresh_running and self._icon:
                    try:
                        self._dispatch_to_main(self._sync_pause_state)
                        self._health._check_config_error_notification()
                        self._health._check_version_mismatch()
                        self._health._check_stale_code()
                        self._health._check_pypi_version()
                        self._health._check_self_upgrade_notification()
                        self._health._check_ide_setup_notification()
                        self._plugins._poll_plugins()
                        self._anim._request_discovery_refresh(wait=False)
                        self._register_tray_with_remotes()
                        self._dispatch_to_main(self._refresh_menu_if_changed)
                    except Exception:
                        logger.debug("Stats refresh tick failed", exc_info=True)

        thread = threading.Thread(target=_refresh, daemon=True, name="stats-refresh")
        thread.start()

    def _start_subscriber(self):
        """Start background thread subscribing to daemon push events (#650)."""
        self._subscriber_running = True
        thread = threading.Thread(
            target=self._subscriber_loop, daemon=True, name="daemon-subscriber"
        )
        thread.start()

    def _subscriber_sleep(self, seconds):
        """Sleep in 0.1s slices, returning True if subscriber was stopped."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and self._subscriber_running:
            time.sleep(0.1)
        return not self._subscriber_running

    def _subscriber_loop(self):
        """Connect as subscriber, listen for events, trigger refresh."""
        from ai_guardian.daemon.client import connect_subscriber
        from ai_guardian.daemon.protocol import decode_message

        RECONNECT_DELAY = 5.0

        while self._subscriber_running:
            sock = connect_subscriber(timeout=2.0)
            if sock is None:
                if self._subscriber_sleep(RECONNECT_DELAY):
                    return
                continue

            logger.info("Subscribed to daemon push events")
            try:
                while self._subscriber_running:
                    try:
                        msg = decode_message(sock, timeout=300.0)
                        if msg.get("type") == "event":
                            logger.debug("Push event: %s", msg.get("event", "?"))
                            self._refresh_event.set()
                    except socket.timeout:
                        continue
            except (ConnectionError, OSError, ValueError):
                logger.debug("Subscriber connection lost, will reconnect")
            finally:
                try:
                    sock.close()
                except OSError:
                    pass

            if self._subscriber_running:
                self._subscriber_sleep(RECONNECT_DELAY)

    def _on_targets_updated(self, targets):
        """Callback from background discovery with updated target list."""
        self._anim._discovery_in_progress = False
        self._anim._stop_discovery_animation()
        self._anim._is_initial_discovery = False
        self._targets = targets
        if self._status == "paused":
            for t in self._targets:
                if t.runtime == "local" and t.status == "running":
                    t.status = "paused"
        self._menu._apply_working_dirs()
        self._auto_select_target()
        self._plugins._poll_plugins()
        self._anim._refreshing_from_discovery = True
        self._dispatch_to_main(self._anim._refresh_menu_and_clear_discovery_flag)
        logger.info(f"Discovery updated: {len(targets)} target(s) found")
        for t in targets:
            logger.info(f"  {t.name} ({t.runtime}) status={t.status} port={t.port}")
        self._register_tray_with_remotes()
        self._catchup_remote_traces()

    def _catchup_remote_traces(self):
        """Catch-up pull for newly discovered remote daemons (#2188)."""
        if not self._multi_client:
            return
        for target in self._targets:
            if (
                target.runtime in ("container", "kubernetes", "manual")
                and target.status == "running"
                and target.name not in self._trace_catchup_done
            ):
                self._trace_catchup_done.add(target.name)
                threading.Thread(
                    target=self._do_catchup_pull,
                    args=(target,),
                    daemon=True,
                    name=f"trace-catchup-{target.name}",
                ).start()

    def _do_catchup_pull(self, target):
        """Background thread: pull existing traces from a remote daemon."""
        try:
            from ai_guardian.daemon.trace_sync import (
                catchup_pull,
                cleanup_stale_cache,
            )

            catchup_pull(self._multi_client, target)
            retention = self._read_trace_cache_retention()
            cleanup_stale_cache(retention)
        except Exception:
            logger.debug("Trace catch-up failed for %s", target.name, exc_info=True)

    def _read_trace_cache_retention(self) -> int:
        """Read trace_cache_retention_days from config."""
        try:
            from ai_guardian.config.loaders import _load_tracing_config

            return _load_tracing_config()["trace_cache_retention_days"]
        except Exception:
            return 90

    def _auto_select_target(self):
        """Auto-select the best running daemon target.

        Prefers: current selection (if still running) > running local > first running.
        """
        if self._active_target and self._active_target.status in ("running", "paused"):
            for t in self._targets:
                if (
                    t.name == self._active_target.name
                    and t.runtime == self._active_target.runtime
                ):
                    self._active_target = t
                    return

        for t in self._targets:
            if t.runtime == "local" and t.status in ("running", "paused"):
                self._active_target = t
                return

        for t in self._targets:
            if t.status in ("running", "paused"):
                self._active_target = t
                return

        if self._targets:
            self._active_target = self._targets[0]
        else:
            self._active_target = None

    # --- Remote ask prompt forwarding (#1342) ---

    def _register_tray_with_remotes(self):
        """Register this tray with remote daemons for ask dialog forwarding."""
        if not self._multi_client:
            return
        registered = set()
        failed = set()
        for target in self._targets:
            if (
                target.runtime in ("container", "kubernetes", "manual")
                and target.status == "running"
            ):
                tray_host = self._resolve_tray_host(target)
                try:
                    local_port = self._get_local_daemon_port()
                    ok = self._multi_client.register_tray(target, tray_host, local_port)
                    if ok:
                        registered.add(target.name)
                        logger.info(
                            "Ask forwarding registered with %s (host=%s)",
                            target.name,
                            tray_host,
                        )
                    else:
                        failed.add(target.name)
                        logger.warning(
                            "Ask forwarding registration FAILED for %s — "
                            "container may be running old code without /api/register-tray",
                            target.name,
                        )
                except Exception as e:
                    failed.add(target.name)
                    logger.warning(
                        "Ask forwarding registration error for %s: %s", target.name, e
                    )
        self._ask_forwarding_targets = registered
        self._ask_forwarding_failed = failed

    @staticmethod
    def _resolve_tray_host(target):
        """Determine host address the remote daemon can use to reach this tray."""
        if target.runtime == "container":
            return "host.docker.internal"
        return "127.0.0.1"

    @staticmethod
    def _get_local_daemon_port() -> int:
        """Read the local daemon's REST port from the PID file."""
        try:
            import json as _json

            from ai_guardian.daemon import DEFAULT_REST_PORT, get_pid_path

            pid_path = get_pid_path()
            if pid_path.exists():
                pid_info = _json.loads(pid_path.read_text())
                return int(pid_info.get("rest_port", DEFAULT_REST_PORT))
            return DEFAULT_REST_PORT
        except Exception:
            return 0

    def _start_prompt_poll(self):
        """Start background thread that fast-polls remote daemons for pending ask prompts."""
        self._prompt_poll_running = True

        def _poll():
            while self._prompt_poll_running:
                time.sleep(self._PROMPT_POLL_INTERVAL)
                if not self._prompt_poll_running:
                    break
                try:
                    self._poll_remote_prompts()
                except Exception as e:
                    logger.debug("Prompt poll error: %s", e)

        thread = threading.Thread(target=_poll, daemon=True, name="prompt-poll")
        thread.start()

    def _poll_remote_prompts(self):
        """Check remote daemons for pending ask prompts and show dialogs."""
        if not self._multi_client:
            return
        for target in self._targets:
            if target.runtime not in ("container", "kubernetes", "manual"):
                continue
            if target.status != "running":
                continue
            try:
                prompts = self._multi_client.get_pending_prompts(target)
            except Exception as e:
                logger.debug("get_pending_prompts failed for %s: %s", target.name, e)
                continue
            if not prompts:
                continue
            logger.info(
                "Found %d pending ask prompt(s) on %s", len(prompts), target.name
            )
            for prompt_data in prompts:
                self._handle_remote_prompt(target, prompt_data)

    def _handle_remote_prompt(self, target, prompt_data):
        """Show ask dialog for a remote daemon's pending prompt."""
        prompt_id = prompt_data.get("prompt_id")
        if not prompt_id or prompt_id in self._in_flight_prompts:
            return
        self._in_flight_prompts.add(prompt_id)

        def _show_and_respond():
            try:
                from ai_guardian.tui.ask_dialog import (
                    AskViolationInfo,
                    _show_via_subprocess,
                    _map_fallback_to_decision,
                )

                logger.info(
                    "Remote ask prompt %s received from %s — showing dialog",
                    prompt_id,
                    target.name,
                )

                v = prompt_data.get("violation", {})
                violation = AskViolationInfo(
                    violation_type=v.get("violation_type", ""),
                    summary=v.get("summary", ""),
                    matched_text=v.get("matched_text", ""),
                    config_section=v.get("config_section", ""),
                    error_message=v.get("error_message", ""),
                    matched_pattern=v.get("matched_pattern", ""),
                    file_path=v.get("file_path"),
                    line_number=v.get("line_number"),
                    start_column=v.get("start_column"),
                    project_path=v.get("project_path"),
                    session_id=v.get("session_id"),
                    tool_name=v.get("tool_name"),
                    hook_event=v.get("hook_event"),
                    finding_index=v.get("finding_index"),
                    total_findings=v.get("total_findings"),
                )

                fallback = prompt_data.get("fallback_action", "block")
                timeout = prompt_data.get("timeout_seconds", 300)

                # macOS only: pystray runs as NSApplicationActivationPolicyAccessory
                # (no dock icon). On macOS 14+, activateIgnoringOtherApps_ is deprecated
                # so tkinter subprocesses can't steal focus. Force NiceGUI browser tab
                # which is always foreground regardless of parent activation policy.
                # On Linux/Windows, pystray is a regular process — tkinter works fine,
                # so let preferred_ui auto-select (tkinter/NiceGUI/Textual per config).
                import platform as _platform

                extra_env = {}
                if _platform.system() == "Darwin":
                    # pystray = NSApplicationActivationPolicyAccessory on macOS 14+:
                    # tkinter subprocesses can't steal focus (activateIgnoringOtherApps_
                    # deprecated). Skip tkinter; preferred_ui otherwise respected
                    # (NiceGUI browser tab, Textual, etc.).
                    extra_env["AI_GUARDIAN_NO_TKINTER"] = "1"
                    logger.info(
                        "Remote ask %s: macOS — tkinter suppressed, using preferred_ui",
                        prompt_id,
                    )
                else:
                    logger.info(
                        "Remote ask %s: using preferred_ui auto-selection", prompt_id
                    )
                result = _show_via_subprocess(
                    violation, fallback, timeout, extra_env=extra_env or None
                )
                logger.info(
                    "Remote ask %s: subprocess returned decision=%s",
                    prompt_id,
                    result.decision.value if result else "None (fallback)",
                )

                if result is None:
                    decision = _map_fallback_to_decision(fallback)
                    decision_data = {"decision": decision.value}
                else:
                    # config_saved / source_annotation_saved are intentionally
                    # False: the subprocess ran on the host (wrong machine).
                    # The triggering daemon owns its own filesystem — hook_processing
                    # checks `not config_saved` and saves the pattern/annotation
                    # locally when it processes the returned AskResult (#1342).
                    decision_data = {
                        "decision": result.decision.value,
                        "allowlist_pattern": result.allowlist_pattern,
                        "config_saved": False,
                        "config_path": None,
                        "source_annotation_saved": False,
                        "ignore_path": result.ignore_path,
                        "ignore_scanner_types": result.ignore_scanner_types,
                    }

                self._multi_client.send_prompt_decision(
                    target, prompt_id, decision_data
                )
            except Exception as e:
                logger.warning("Failed to handle remote prompt %s: %s", prompt_id, e)
            finally:
                self._in_flight_prompts.discard(prompt_id)

        threading.Thread(
            target=_show_and_respond,
            daemon=True,
            name=f"remote-prompt-{prompt_id[:8]}",
        ).start()

    def _get_active_stats(self):
        """Get stats from the active target (local or remote).

        Also updates the target name from the REST API response if
        the daemon reports a configured name.
        """
        if (
            self._multi_client
            and self._active_target
            and self._active_target.runtime != "local"
        ):
            result = self._multi_client.get_status(self._active_target)
            if result and result.get("name"):
                self._active_target.name = result["name"]
            return result or {}
        return self._get_stats()

    def _is_multi_daemon(self):
        """True when multiple daemons are discovered (nested submenu layout)."""
        return len(self._targets) != 1

    def _is_single_daemon(self):
        """True when exactly one daemon is discovered (flat layout)."""
        return len(self._targets) == 1

    def _get_target_stats(self, target):
        """Get live stats dict for a specific daemon target."""
        if self._multi_client and target.runtime != "local":
            return self._multi_client.get_status(target) or {}
        return self._get_stats()

    def _target_has_paused_dirs(self, target):
        """Check whether a daemon target has any paused directories."""
        stats = self._get_target_stats(target)
        return bool(stats.get("paused_dirs"))

    def _on_restart_tray(self, icon, item):
        """Restart the tray process."""
        import subprocess

        cmd = tray_plugins.resolve_cli_cmd("tray", "start")
        logger.debug("Restarting tray with command: %s", cmd)
        self.stop()
        self._stop()
        try:
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as e:
            logger.error("Failed to restart tray: %s (cmd: %s)", e, cmd)

    def _on_quit(self, icon, item):
        self.stop()
        self._stop()
