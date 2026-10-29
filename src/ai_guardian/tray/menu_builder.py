"""
Menu construction for the system tray — daemon status, sandbox, IDE setup,
pause-modal entry point, and about menus.

Split from tray.py (Issue #1542). TrayMenuBuilder constructs pystray
MenuItem trees by reading state from DaemonTray and its sub-managers.
"""

import logging
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from ai_guardian.daemon.discovery import should_update_target_name
from ai_guardian.daemon.about import AUTHOR_HANDLE, AUTHOR_URL
from ai_guardian.ide_registry import (
    SANDBOX_CLI_IDE_TYPES_BY_RUNTIME,
    SANDBOX_PI_PROVIDER_CHOICES_BY_RUNTIME,
)
from ai_guardian.openshell_policy import (
    NO_POLICY_CHOICE,
    discover_openshell_policies,
    load_openshell_policy,
    policy_choice_values,
    resolve_openshell_policy_choice,
    summarize_openshell_policy,
)
from ai_guardian.tray import icons as tray_icons
from ai_guardian.tray import menu as tray_menu
from ai_guardian.tray import notifications as tray_notifications
from ai_guardian.tray import openshell_middleware
from ai_guardian.tray import plugins as tray_plugins

logger = logging.getLogger(__name__)


# Keep this aligned with the runtime-specific registry. Claude is installed only
# after runtime ToS consent; OpenCode is bundled in the OpenShell image.
TRAY_OPENSHELL_CLI_CHOICES = SANDBOX_CLI_IDE_TYPES_BY_RUNTIME["openshell"]
TRAY_OPENSHELL_AUTH_CHOICES = ("OAuth", "API key")
TRAY_OPENSHELL_MODE_CHOICES = ("AI Guardian hooks", "Native OpenShell")
TRAY_SANDBOX_CLI_CHOICES_BY_RUNTIME = {
    "container": SANDBOX_CLI_IDE_TYPES_BY_RUNTIME["container"],
    "openshell": TRAY_OPENSHELL_CLI_CHOICES,
}
_SANDBOX_CONFIG_SOURCE_CHOICES = (
    "Host/default",
    "Profile",
    "Host config directory",
    "Latest saved snapshot",
)
_SANDBOX_DEFAULT_CONFIG_SOURCE = _SANDBOX_CONFIG_SOURCE_CHOICES[0]


def _split_form_values(value):
    """Split comma/newline form values while preserving user order."""
    return [
        item.strip()
        for item in str(value or "").replace("\n", ",").split(",")
        if item.strip()
    ]


def _normalize_sandbox_config_source(value):
    """Return a valid initial-config choice for a sandbox form."""
    candidate = str(value or "").strip()
    if candidate in _SANDBOX_CONFIG_SOURCE_CHOICES:
        return candidate
    return _SANDBOX_DEFAULT_CONFIG_SOURCE


try:
    import pystray
except Exception:
    pystray = None


class _SandboxOutput(list):
    """Keep captured output while forwarding it to a live progress dialog."""

    def __init__(self, callback=None):
        super().__init__()
        self.stream_callback = callback

    def append(self, value):
        super().append(value)
        if self.stream_callback is None:
            return
        try:
            self.stream_callback(value)
        except Exception:
            logger.debug("Unable to update sandbox progress dialog", exc_info=True)


class TrayMenuBuilder:
    """Constructs pystray menu item trees for the system tray."""

    def __init__(self, tray):
        self._tray = tray
        self._single_daemon_closures = {}
        self._stats_cache = {}
        self._pause_dialog_lock = threading.Lock()
        self._sandbox_create_lock = threading.Lock()
        self._sandbox_create_in_progress = False

    def _target_at(self, slot):
        """SSH menus bind a connection object; legacy menus retain dynamic slots."""
        if not isinstance(slot, int):
            return slot
        return self._tray._targets[slot] if slot < len(self._tray._targets) else None

    def _ssh_action(self, target, callback):
        from ai_guardian.tray.ssh_connections import target_action

        return target_action(self._tray, target, callback)

    def _support_menu_item(self, target, *, flat=False, visible=None):
        """Bind the displayed source; capture its current SSH generation on click."""
        from copy import copy, deepcopy

        selected = copy(target)
        selected.tls = deepcopy(target.tls)
        client = self._tray._multi_client

        def launch(_icon, _item):
            clicked = copy(selected)
            if selected.runtime == "ssh":
                # Discovery keeps this saved target object across connects and
                # reconnects. Its render-time tunnel may be absent/already closed
                # even while status polling succeeds on the new verified tunnel.
                # Bind that generation now, never after the worker has started or
                # by looking up a replacement target with the same display name.
                clicked.ssh_tunnel = (
                    target.ssh_tunnel
                    if target.ssh_id == selected.ssh_id
                    and any(item is target for item in self._tray._targets)
                    else None
                )
            return tray_menu.launch_support(
                target=clicked,
                client=client,
                **self._screen_bounds_kwargs(self._capture_tray_screen_bounds(_icon)),
            )

        options = {"visible": visible} if visible is not None else {}
        return pystray.MenuItem(
            (
                f"Contact supports — {selected.name} (daemon)"
                if flat
                else "Contact supports"
            ),
            launch,
            **options,
        )

    def _open_ssh_panel(self, target, panel=None):
        from ai_guardian.daemon.ssh_storage import SSHConnectionError

        if not self._tray._ensure_web_console_ready():
            raise SSHConnectionError(
                "The workstation Console is unavailable. Start the local Web Console and retry; no remote browser was launched."
            )
        if (
            tray_menu.open_web_console(
                target.name, tray_menu.PANEL_TO_WEB_PATH.get(panel, "") if panel else ""
            )
            is False
        ):
            raise SSHConnectionError(
                "The workstation Console is unavailable. Start the local Web Console and retry; no remote browser was launched."
            )

    def _on_about(self, icon, item):
        """Show About info via OS dialog."""

        screen_bounds = self._capture_tray_screen_bounds(icon)
        target = None
        if len(self._tray._targets) == 1:
            target = self._tray._targets[0]

        def _show():
            try:
                from ai_guardian.tray.plugins import show_dialog

                title = "About AI Guardian"
                if target and target.runtime != "local":
                    info = None
                    if self._tray._multi_client:
                        info = self._tray._multi_client.get_about(target)
                    if info:
                        from ai_guardian.daemon.about import format_about_text

                        title = f"About {target.name}"
                        text = format_about_text(info)
                    else:
                        title, text = self._format_unavailable_remote_about(target)
                else:
                    text = tray_menu.build_about_text()
                    if self._tray._is_multi_daemon():
                        text = self._format_local_about_text(text)
                        text += self._format_daemon_list()
                show_dialog(
                    title,
                    text,
                    links=((f"({AUTHOR_HANDLE})", AUTHOR_URL),),
                    **self._screen_bounds_kwargs(screen_bounds),
                )
            except Exception:
                pass  # intentionally silent — optional dependency

        threading.Thread(target=_show, daemon=True, name="about-dialog").start()

    def _daemon_about_label(self, slot):
        """Build About menu label with daemon version for a specific slot."""

        def _label(_item=None):
            target = self._target_at(slot)
            if target is None:
                return "About"
            key = (target.name, target.runtime)
            version = self._tray._health._daemon_versions.get(key, "")
            if version:
                return f"About — v{version}"
            return "About"

        return _label

    def _on_daemon_about(self, slot):
        """Show About info for a specific daemon via OS dialog."""

        def action(icon, __):
            target = self._target_at(slot)
            if target is None:
                return
            if target.runtime == "ssh":
                from copy import copy

                target = copy(target)
            screen_bounds = self._capture_tray_screen_bounds(icon)

            def _show():
                try:
                    from ai_guardian.tray.plugins import show_dialog

                    info = (
                        self._tray._daemon_about_cache.get(slot)
                        if isinstance(slot, int)
                        else None
                    )
                    if info is None and self._tray._multi_client:
                        info = self._tray._multi_client.get_about(target)
                        if info and isinstance(slot, int):
                            self._tray._daemon_about_cache[slot] = info
                    if info:
                        from ai_guardian.daemon.about import format_about_text

                        text = format_about_text(info)
                    elif target.runtime != "local":
                        _, text = self._format_unavailable_remote_about(target)
                    else:
                        text = tray_menu.build_about_text()
                    show_dialog(
                        f"About {target.name}",
                        text,
                        links=((f"({AUTHOR_HANDLE})", AUTHOR_URL),),
                        **self._screen_bounds_kwargs(screen_bounds),
                    )
                except Exception:
                    pass  # intentionally silent — optional dependency

            threading.Thread(
                target=_show, daemon=True, name="daemon-about-dialog"
            ).start()

        return action

    @staticmethod
    def _format_local_about_text(text):
        """Identify About fields that describe the local tray process."""
        return f"Local tray (this process):\n{text}"

    def _format_unavailable_remote_about(self, target):
        """Format a clear fallback when a remote daemon has no About data."""
        return (
            f"About {target.name}",
            "Remote daemon information is unavailable.\n\n"
            + self._format_local_about_text(tray_menu.build_about_text()),
        )

    def _format_daemon_list(self):
        """Format connected daemons list for multi-daemon About."""
        if not self._tray._targets:
            return ""
        lines = [f"\nDaemons: {len(self._tray._targets)} connected"]
        for target in self._tray._targets:
            key = (target.name, target.runtime)
            ver = self._tray._health._daemon_versions.get(key, "?")
            if target.status == "running" and self._tray._target_has_paused_dirs(
                target
            ):
                icon = "◐"
            else:
                icon = {"running": "●", "paused": "☾", "stopped": "⚠"}.get(
                    target.status, "○"
                )
            suffix = ""
            if key in self._tray._health._version_mismatch_notified:
                suffix = " ⟳"
            lines.append(f"  {icon} {target.name} v{ver}{suffix}")
        return "\n".join(lines)

    def _mcp_proactive_label(self, slot=None):
        """Show the effective MCP level for the selected daemon."""
        if slot is not None and not isinstance(slot, int):
            stats = slot.stats or {}
            installed = stats.get("mcp_installed")
            if installed is False:
                return "MCP: not installed"
            if stats.get("mcp_enabled") is False:
                return "MCP: disabled"
            level = stats.get("mcp_proactive_level", "unavailable")
            if slot.status == "paused" and level != "unavailable":
                level = "paused"
            return f"MCP Proactive: {level}"
        paused = False
        if slot is None:
            try:
                paused = bool(self._tray._get_stats().get("paused", False))
            except Exception as exc:
                logger.debug("Unable to read daemon pause state for MCP menu: %s", exc)
                paused = getattr(self._tray, "_status", "") == "paused"
        elif slot < len(self._tray._targets):
            paused = self._tray._targets[slot].status == "paused"
        level = "paused" if paused else self._tray._proactive_level
        return f"MCP Proactive: {level}"

    def _proactive_for_slot(self, slot):
        if isinstance(slot, int):
            return self._tray._proactive_level
        return (slot.stats or {}).get("mcp_proactive_level")

    def _proactive_available(self, slot):
        return isinstance(slot, int) or (
            (slot.stats or {}).get("mcp_installed") is True
            and (slot.stats or {}).get("mcp_enabled", True) is True
            and self._proactive_for_slot(slot) in ("low", "medium", "high", "paused")
        )

    def _mk_proactive_change(self, slot, level):
        if isinstance(slot, int):
            return lambda _, __: self._tray._on_change_proactive(level)

        def change(target):
            if not self._proactive_available(target):
                return False
            result = self._tray._multi_client.write_config(
                target, "global", "mcp_server", "proactive_level", level
            )
            return bool(
                isinstance(result, dict)
                and result.get("status") == "ok"
                and not result.get("error")
            )

        return self._ssh_action(slot, change)

    def _invalidate_stats(self, target=None):
        """Discard snapshots before native rendering or after a scoped request."""
        if target is None:
            self._stats_cache.clear()
        else:
            self._stats_cache.pop(id(target), None)

    def _get_menu_stats(self, target):
        """Share one target snapshot across headers, status, and scope controls."""
        now = time.monotonic()
        cached = self._stats_cache.get(id(target))
        if cached is not None and cached[0] is target and now - cached[1] < 2.0:
            return cached[2]
        stats = self._tray._get_target_stats(target) or {}
        if stats and should_update_target_name(target, stats.get("name")):
            target.name = stats["name"]
        if "paused" in stats and target.status in ("running", "paused"):
            target.status = "paused" if stats["paused"] else "running"
        key = (target.name, target.runtime)
        if "mcp_installed" in stats:
            self._tray._mcp_installed_per_daemon[key] = stats["mcp_installed"]
        if "version" in stats:
            self._tray._health._daemon_versions[key] = stats["version"]
        self._stats_cache[id(target)] = (target, now, stats)
        return stats

    def _get_slot_stats(self, slot):
        target = self._target_at(slot)
        if target is None:
            return {}
        return self._get_menu_stats(target)

    def _version_annotated_label(self, target):
        """Format daemon label with version mismatch indicator if needed."""
        stats = self._get_menu_stats(target)
        active_dirs = stats.get("active_project_dirs") or []
        active_sessions = stats.get("active_sessions") or []
        label = tray_menu.daemon_status_label(
            target,
            has_paused_dirs=bool(stats.get("paused_dirs")),
            has_paused_sessions=any(
                session.get("paused")
                for session in active_sessions
                if isinstance(session, dict)
            ),
            active_project_dir=active_dirs[0] if active_dirs else None,
            project_count=len(active_dirs),
            forwarding_failed=target.name in self._tray._ask_forwarding_failed,
        )
        key = (target.name, target.runtime)
        if key in self._tray._health._version_mismatch_notified:
            daemon_ver = self._tray._health._daemon_versions.get(key, "")
            if daemon_ver:
                label += f" — v{daemon_ver} ⟳"
        return label

    def _daemon_status_details(self, slot):
        """Return dynamic status text used by each daemon's Status submenu."""
        target = self._target_at(slot)
        if target is None:
            return (
                "Daemon: unavailable",
                "○ Unknown",
                "Runtime: unknown",
                "Daemon target is no longer available.",
                (),
            )

        stats = getattr(target, "stats", None)
        if target.status in ("running", "paused"):
            try:
                stats = self._get_menu_stats(target)
            except Exception:
                stats = {}
        has_paused_dirs = isinstance(stats, dict) and bool(stats.get("paused_dirs"))
        active_sessions = (
            stats.get("active_sessions", []) if isinstance(stats, dict) else []
        )
        has_paused_sessions = any(
            session.get("paused")
            for session in active_sessions
            if isinstance(session, dict)
        )
        key = (target.name, target.runtime)
        status, reason, warnings = tray_menu.daemon_status_explanation(
            target,
            has_paused_dirs=has_paused_dirs,
            has_paused_sessions=has_paused_sessions,
            forwarding_failed=target.name
            in getattr(self._tray, "_ask_forwarding_failed", set()),
            version_mismatch=key
            in getattr(self._tray._health, "_version_mismatch_notified", set()),
        )
        if target.runtime == "ssh" and target.name in getattr(
            self._tray, "_ask_forwarding_failed", set()
        ):
            from ai_guardian.daemon.ssh_tunnel import POLLING_ERROR

            warnings = (*warnings, POLLING_ERROR)
        runtime = getattr(target, "runtime_type", None) or target.runtime
        if runtime != target.runtime:
            runtime = f"{runtime} ({target.runtime})"
        return (
            f"Daemon: {target.name}",
            status,
            f"Runtime: {runtime}",
            reason,
            warnings,
        )

    def _build_daemon_status_menu_item(self, slot, *, visible=None):
        """Build a per-daemon status explanation and symbol legend."""

        def _line(index):
            def label(_item, index=index):
                return self._daemon_status_details(slot)[index]

            return label

        def warning_label(_item):
            warnings = self._daemon_status_details(slot)[4]
            return "Warnings: " + " | ".join(warnings)

        def warnings_visible(_item):
            return bool(self._daemon_status_details(slot)[4])

        legend = pystray.Menu(
            pystray.MenuItem("● Running", None, enabled=False),
            pystray.MenuItem("◐ Partially paused", None, enabled=False),
            pystray.MenuItem("☾ Paused", None, enabled=False),
            pystray.MenuItem("◌ Starting or recovering", None, enabled=False),
            pystray.MenuItem("⚠ Stopped or not running", None, enabled=False),
            pystray.MenuItem("○ Offline — reconnecting", None, enabled=False),
            pystray.MenuItem("✗ Error", None, enabled=False),
            pystray.MenuItem("○ Unknown", None, enabled=False),
        )
        menu_kwargs = {} if visible is None else {"visible": visible}
        return pystray.MenuItem(
            "Status",
            pystray.Menu(
                pystray.MenuItem(_line(0), None, enabled=False),
                pystray.MenuItem(_line(1), None, enabled=False),
                pystray.MenuItem(_line(2), None, enabled=False),
                pystray.MenuItem(_line(3), None, enabled=False),
                pystray.MenuItem(
                    warning_label,
                    None,
                    enabled=False,
                    visible=warnings_visible,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Symbol legend", legend),
            ),
            **menu_kwargs,
        )

    def _working_dir_menu_label(self, slot):
        """Format the Working Dir menu item label for a daemon slot."""
        from ai_guardian.daemon.working_dir import shorten_path

        target = self._target_at(slot)
        if target is not None:
            wd = getattr(target, "working_dir", None)
            if wd:
                short = wd if target.runtime == "ssh" else shorten_path(wd)
                if len(short) > 50:
                    short = short[:47] + "..."
                return f"Working Dir: {short}"
        return "Working Dir: ~"

    def _mk_change_working_dir(self, slot):
        """Create a click handler that opens a directory picker for a slot."""

        def action(icon, __):
            t = self._target_at(slot)
            if t is None:
                return
            current = getattr(t, "working_dir", None)
            threading.Thread(
                target=self._pick_working_dir,
                args=(t, current, self._capture_tray_screen_bounds(icon)),
                daemon=True,
                name="working-dir-picker",
            ).start()

        return action

    def _pick_working_dir(self, target, current, screen_bounds=None):
        """Run directory picker in background thread and persist result."""
        from ai_guardian.daemon.working_dir import choose_directory, set_working_dir

        if target.runtime == "ssh":
            from ai_guardian.ui.forms import run_form_flow
            import posixpath

            def choose(form):
                message = "Enter an absolute directory on the VM for Terminal and maintenance commands. This does not select a workstation folder or change the daemon's configuration scope."
                while True:
                    values = form(
                        "Working directory — " + target.name,
                        message,
                        [
                            {
                                "name": "directory",
                                "label": "VM directory (empty uses remote home)",
                                "default": current or "",
                            }
                        ],
                        submit_label="Save",
                    )
                    if values is None:
                        return None
                    path = values.get("directory", "").strip()
                    if not path or (
                        posixpath.isabs(path)
                        and not any(ord(c) < 32 or ord(c) == 127 for c in path)
                    ):
                        return path
                    message = "Choose an absolute directory on the VM, or leave it empty to use its home directory."

            chosen = run_form_flow(choose, screen_bounds=screen_bounds)
            if chosen is not None and any(t is target for t in self._tray._targets):
                target.working_dir = chosen or None
                set_working_dir(target.name, chosen)
                self._tray._refresh_event.set()
            return

        chosen = choose_directory(
            current,
            **self._screen_bounds_kwargs(screen_bounds),
        )
        if chosen:
            target.working_dir = chosen
            self._tray._active_target = target
            set_working_dir(target.name, chosen)
            self._tray._refresh_event.set()

    def _mk_cursor_cloud_setup_action(self):
        """Create a handler that selects a workspace for Cursor Cloud setup."""

        def action(icon, __):
            current = None
            if self._tray._targets:
                current = getattr(self._tray._targets[0], "working_dir", None)
            threading.Thread(
                target=self._pick_cursor_cloud_project,
                args=(current, self._capture_tray_screen_bounds(icon)),
                daemon=True,
                name="cursor-cloud-project-picker",
            ).start()

        return action

    def _pick_cursor_cloud_project(self, current=None, screen_bounds=None):
        """Select a workspace, then launch explicit Cursor project setup."""
        from ai_guardian.daemon.working_dir import choose_directory

        chosen = choose_directory(
            current,
            title="Choose Cursor Cloud project directory",
            **self._screen_bounds_kwargs(screen_bounds),
        )
        if chosen:
            tray_menu.launch_ide_setup("cursor", scope="project", project_dir=chosen)

    def _apply_working_dirs(self):
        """Populate target.working_dir from persisted state after discovery."""
        from ai_guardian.daemon.working_dir import get_working_dir, load_working_dirs

        ssh_dirs = (
            load_working_dirs()
            if any(t.runtime == "ssh" for t in self._tray._targets)
            else {}
        )

        for t in self._tray._targets:
            if t.runtime == "ssh":
                # No saved selection means the SSH user's home, not Path.home()
                # on this workstation. Also clear an inherited pre-fix default.
                t.working_dir = ssh_dirs.get(t.name) or None
            elif not getattr(t, "working_dir", None):
                t.working_dir = get_working_dir(t.name)

    @staticmethod
    def _sandbox_runtime(target):
        """Return the logical sandbox runtime for a discovered target."""
        return getattr(target, "runtime_type", None) or getattr(target, "runtime", None)

    def _sandbox_target_at(self, slot):
        """Return a target slot when it represents a supported sandbox."""
        target = self._target_at(slot)
        if target is None:
            return None
        if self._sandbox_runtime(target) not in {"container", "openshell"}:
            return None
        return target

    def _sandbox_is_openshell(self, slot):
        """Return whether a target slot represents an OpenShell sandbox."""
        target = self._sandbox_target_at(slot)
        return bool(target and self._sandbox_runtime(target) == "openshell")

    def _sandbox_is_running(self, slot):
        """Return whether a sandbox target can accept an interactive session."""
        target = self._sandbox_target_at(slot)
        return bool(target and target.status in ("running", "paused"))

    def _mk_sandbox_connect_action(self, slot):
        """Create the canonical sandbox connect action for a target slot."""
        return self._mk_sandbox_command_action(
            slot,
            "connect",
            lambda target: [target.name],
        )

    def _start_sandbox_form(
        self,
        title,
        message,
        fields,
        callback,
        *,
        name="sandbox-form",
        icon=None,
        screen_bounds=None,
        on_cancel=None,
        on_error=None,
    ):
        """Show a sandbox form away from the tray callback thread."""
        if screen_bounds is None:
            screen_bounds = self._capture_sandbox_screen_bounds(icon)

        def run_form():
            try:
                from ai_guardian.tray.sandbox_dialog import show_sandbox_form

                if screen_bounds is None:
                    values = show_sandbox_form(title, message, fields)
                else:
                    values = show_sandbox_form(
                        title,
                        message,
                        fields,
                        screen_bounds=screen_bounds,
                    )
                if values is not None:
                    callback(values, screen_bounds=screen_bounds)
                elif on_cancel is not None:
                    on_cancel()
            except Exception:
                logger.exception("Sandbox form action failed")
                if on_error is not None:
                    on_error()

        threading.Thread(target=run_form, daemon=True, name=name).start()

    def _begin_sandbox_create(self):
        """Reserve the single tray sandbox creation flow."""
        with self._sandbox_create_lock:
            if self._sandbox_create_in_progress:
                return False
            self._sandbox_create_in_progress = True
            return True

    def _end_sandbox_create(self):
        """Release the tray sandbox creation flow reservation."""
        with self._sandbox_create_lock:
            self._sandbox_create_in_progress = False

    def _sandbox_create_is_in_progress(self):
        """Return whether a tray sandbox creation flow is active."""
        with self._sandbox_create_lock:
            return self._sandbox_create_in_progress

    @staticmethod
    def _capture_tray_screen_bounds(icon=None):
        """Capture the display containing the tray menu before worker dispatch."""
        from ai_guardian.tray.dialog_placement import _get_tray_screen_bounds

        return _get_tray_screen_bounds(icon)

    @staticmethod
    def _capture_sandbox_screen_bounds(icon=None):
        """Backward-compatible alias for sandbox display capture tests."""
        return TrayMenuBuilder._capture_tray_screen_bounds(icon)

    @staticmethod
    def _screen_bounds_kwargs(screen_bounds):
        """Build optional dialog placement kwargs without changing fallbacks."""
        return {"screen_bounds": screen_bounds} if screen_bounds is not None else {}

    @staticmethod
    def _sandbox_error(title, message, *, screen_bounds=None):
        """Show a best-effort error for invalid tray form input."""
        from ai_guardian.tray.plugins import show_dialog

        show_dialog(
            title, message, **TrayMenuBuilder._screen_bounds_kwargs(screen_bounds)
        )

    @staticmethod
    def _format_upload_size(size):
        """Format byte count for the repository upload summary."""
        value = float(size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024

    @staticmethod
    def _sandbox_image_status(image):
        """Inspect local image availability without pulling or probing remote registries."""
        if not image:
            return "No image override; runtime default will be used."
        engine = os.environ.get("CONTAINER_ENGINE", "podman")
        try:
            result = subprocess.run(
                [engine, "image", "exists", image],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "Local image check unavailable; remote pull not probed."
        if result.returncode == 0:
            return "Found locally."
        if image.startswith(("localhost/", "localhost:", "127.0.0.1/", "127.0.0.1:")):
            return "Missing locally; this local image reference will likely fail."
        return "Not found locally; remote pull not probed."

    @staticmethod
    def _sandbox_progress_update(progress, message):
        """Update a live sandbox dialog without making it a hard dependency."""
        if progress is None:
            return
        update_status = getattr(progress, "update_status", None)
        if callable(update_status):
            update_status(message)

    @staticmethod
    def _sandbox_progress_close(progress):
        """Close a preparation dialog before showing the next state."""
        if progress is None:
            return
        close = getattr(progress, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _sandbox_repo_upload_summary(repo, *, progress=None):
        """Inspect repository size and remote classification without uploading."""
        path = Path(repo).expanduser()
        if not path.is_dir():
            return None

        TrayMenuBuilder._sandbox_progress_update(
            progress, "Scanning repository files..."
        )
        total_size = 0
        file_count = 0
        pending = [path]
        while pending:
            directory = pending.pop()
            try:
                entries = tuple(os.scandir(directory))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        file_count += 1
                        total_size += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue

        TrayMenuBuilder._sandbox_progress_update(progress, "Checking Git remote...")
        source = "Not a Git repository"
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            remote = (result.stdout or "").strip()
            if result.returncode == 0 and remote:
                if remote.startswith("git@"):
                    host = remote.split("@", 1)[1].split(":", 1)[0]
                else:
                    host = urlparse(remote).hostname or "remote"
                source = (
                    "GitHub repository"
                    if host.casefold() == "github.com"
                    else f"Git remote: {host}"
                )
            elif (path / ".git").exists():
                source = "Git repository (no origin remote)"
        except (OSError, subprocess.TimeoutExpired):
            if (path / ".git").exists():
                source = "Git repository (remote unavailable)"

        return {
            "path": str(path),
            "size": total_size,
            "files": file_count,
            "source": source,
        }

    @staticmethod
    def _openshell_policy_paths(values):
        """Resolve the selected policy profile and any manually entered overlays."""
        options = discover_openshell_policies()
        selected = resolve_openshell_policy_choice(values.get("policy"), options)
        paths = []
        if selected is not None:
            if not selected.is_file():
                raise ValueError(f"OpenShell policy file not found: {selected}")
            load_openshell_policy(selected)
            paths.append(selected)
        for value in _split_form_values(values.get("policies")):
            path = Path(value).expanduser()
            if not path.is_file():
                raise ValueError(f"OpenShell policy file not found: {path}")
            load_openshell_policy(path)
            paths.append(path)
        return paths

    @staticmethod
    def _is_native_openshell(values):
        """Return whether a form value set selects the native OpenShell path."""
        mode = str(values.get("openshell_mode") or "").strip().casefold()
        return str(
            values.get("runtime") or "openshell"
        ).strip().casefold() == "openshell" and mode in {
            "native",
            "native openshell",
            "native-openshell",
        }

    def _sandbox_upload_confirmation_message(self, values, summary):
        """Build safe command and parameter preview for an OpenShell upload."""
        from ai_guardian.sandbox import DEFAULT_OPENSHELL_IMAGE

        runtime = str(values.get("runtime") or "openshell")
        name = str(values.get("name") or "")
        cli = str(values.get("cli") or "claude")
        repo = summary["path"]
        native = self._is_native_openshell(values)
        image = summary.get("image") or (
            "OpenShell default" if native else DEFAULT_OPENSHELL_IMAGE
        )
        image_status = summary.get("image_status")
        if not image_status:
            image_status = (
                "OpenShell resolves this image/base."
                if native and str(values.get("image") or "").strip()
                else (
                    "OpenShell resolves the default workload image."
                    if native
                    else self._sandbox_image_status(image)
                )
            )
        if native:
            command = [
                "openshell",
                "sandbox",
                "create",
                "--detach",
                "--name",
                name,
                "--upload",
                f"{repo}:/sandbox/repo",
            ]
            if str(values.get("image") or "").strip():
                command.extend(["--from", image])
        else:
            command = [
                "ai-guardian",
                "sandbox",
                "create",
                "--runtime",
                runtime,
                "--name",
                name,
                "--cli",
                cli,
                "--repo",
                repo,
            ]
            if str(values.get("image") or "").strip():
                command.extend(["--base", image])
            profile = str(values.get("profile") or "").strip()
            if profile:
                command.extend(["--profile", profile])
            agent = str(values.get("agent") or "").strip()
            if cli == "opencode" and agent:
                command.extend(["--opencode-agent-profile", agent])
            model = str(values.get("model") or "").strip()
            if model:
                command.extend(["--model", model])
        providers = [
            item.strip()
            for item in str(values.get("providers") or "").replace("\n", ",").split(",")
            if item.strip()
        ]
        for provider in providers:
            command.extend(["--provider", provider])
        try:
            policies = self._openshell_policy_paths(values)
        except ValueError:
            policies = []
        for policy in policies:
            if native:
                command.extend(["--policy", "<composed-policy>"])
                break
            command.extend(["--policy", str(policy)])
        if (
            _normalize_sandbox_config_source(values.get("config_source"))
            == "Latest saved snapshot"
        ):
            command.extend(["--restore-config", "latest"])

        environment_count = len(
            [
                item
                for item in str(values.get("environment") or "")
                .replace("\n", ",")
                .split(",")
                if item.strip()
            ]
        )
        label_count = len(
            [
                item
                for item in str(values.get("labels") or "")
                .replace("\n", ",")
                .split(",")
                if item.strip()
            ]
        )
        warning = ""
        if summary["size"] >= 100 * 1024 * 1024:
            warning = "\nWarning: large upload; transfer may take a while."
        return (
            "OpenShell will upload this directory to /sandbox/repo.\n\n"
            f"Path: {summary['path']}\n"
            f"Size: {self._format_upload_size(summary['size'])} "
            f"({summary['files']:,} files)\n"
            f"Source: {summary['source']}\n"
            f"Image: {image}\n"
            f"Image status: {image_status}\n"
            f"Environment entries: {environment_count} (values hidden)\n"
            f"Runtime labels: {label_count}\n\n"
            "Command preview:\n"
            f"{shlex.join(command)}\n\n"
            "Continue upload?"
            f"{warning}"
        )

    def _confirm_sandbox_upload(
        self, values, repo, *, screen_bounds=None, progress=None
    ):
        """Confirm an OpenShell repository upload before starting runtime work."""
        summary = self._sandbox_repo_upload_summary(repo, progress=progress)
        if summary is None:
            self._sandbox_error(
                "Create AI Guardian sandbox",
                f"Repository directory does not exist: {repo}",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            return False
        from ai_guardian.sandbox import DEFAULT_OPENSHELL_IMAGE

        image = str(values.get("image") or "").strip() or DEFAULT_OPENSHELL_IMAGE
        summary["image"] = image
        if self._is_native_openshell(values):
            summary["image"] = (
                image if str(values.get("image") or "").strip() else "OpenShell default"
            )
            summary["image_status"] = (
                "OpenShell resolves the default workload image."
                if not str(values.get("image") or "").strip()
                else "OpenShell resolves this image/base."
            )
            image_error = False
        else:
            self._sandbox_progress_update(progress, "Checking local container image...")
            summary["image_status"] = self._sandbox_image_status(image)
            image_error = summary["image_status"].startswith("Missing locally;")
        error_lines = (
            (f"Image status: {summary['image_status']}",) if image_error else ()
        )
        try:
            from ai_guardian.tray.sandbox_dialog import (
                show_sandbox_upload_confirmation,
            )

            self._sandbox_progress_update(progress, "Ready for upload confirmation.")
            self._sandbox_progress_close(progress)
            return show_sandbox_upload_confirmation(
                self._sandbox_upload_confirmation_message(values, summary),
                error_lines=error_lines,
                **self._screen_bounds_kwargs(screen_bounds),
            )
        except Exception:
            logger.exception("Unable to show sandbox upload confirmation")
            return False

    def _reopen_sandbox_create_form(self, values, screen_bounds, *, on_finished=None):
        """Reopen create form after upload confirmation cancellation."""

        def complete(next_values, *, screen_bounds=None):
            self._complete_sandbox_create_form(
                next_values,
                screen_bounds=screen_bounds,
                on_finished=on_finished,
            )

        self._start_sandbox_form(
            "Create AI Guardian sandbox",
            "Choose the sandbox runtime and initial configuration. Creation "
            "runs in the background; failures show the captured runtime log.",
            self._sandbox_create_fields(values),
            complete,
            name="sandbox-create-form",
            screen_bounds=screen_bounds,
            on_cancel=on_finished,
            on_error=on_finished,
        )

    @staticmethod
    def _show_sandbox_progress(title, message, *, screen_bounds=None, on_connect=None):
        """Start an isolated live progress dialog when the desktop supports it."""
        try:
            from ai_guardian.tray.sandbox_dialog import show_sandbox_progress

            options = TrayMenuBuilder._screen_bounds_kwargs(screen_bounds)
            if on_connect is not None:
                options["on_connect"] = on_connect
            return show_sandbox_progress(title, message, **options)
        except Exception:
            logger.exception("Unable to show sandbox progress dialog")
            return None

    def _mk_sandbox_create_action(self):
        """Create the main-menu callback for sandbox creation."""

        def action(icon, __):
            if not self._begin_sandbox_create():
                return

            def complete(values, *, screen_bounds=None):
                self._complete_sandbox_create_form(
                    values,
                    screen_bounds=screen_bounds,
                    on_finished=self._end_sandbox_create,
                )

            try:
                self._start_sandbox_form(
                    "Create AI Guardian sandbox",
                    "Choose the sandbox runtime and initial configuration. Creation "
                    "runs in the background; failures show the captured runtime log.",
                    # The complete form is built in one place so its defaults stay
                    # aligned with the current environment at click time.
                    self._sandbox_create_fields(),
                    complete,
                    name="sandbox-create-form",
                    icon=icon,
                    on_cancel=self._end_sandbox_create,
                    on_error=self._end_sandbox_create,
                )
            except Exception:
                self._end_sandbox_create()
                raise

        return action

    def _sandbox_create_fields(self, values=None):
        """Return the create form fields used by the main tray menu."""
        form_values = values if isinstance(values, dict) else {}
        config_source_value = form_values.get("config_source")
        if not config_source_value:
            if form_values.get("profile"):
                config_source_value = "Profile"
            elif form_values.get("config_dir"):
                config_source_value = "Host config directory"
        config_source = _normalize_sandbox_config_source(config_source_value)
        runtime = form_values.get(
            "runtime", os.environ.get("AI_GUARDIAN_SANDBOX_RUNTIME", "openshell")
        )
        if runtime not in {"container", "openshell"}:
            runtime = "openshell"
        cli_choices = TRAY_SANDBOX_CLI_CHOICES_BY_RUNTIME[runtime]
        policy_options = discover_openshell_policies() if runtime == "openshell" else ()
        policy_choices = policy_choice_values(policy_options)
        policy_default = str(
            form_values.get(
                "policy", os.environ.get("AI_GUARDIAN_OPEN_SHELL_POLICY", "")
            )
            or NO_POLICY_CHOICE
        )
        configured_policy = policy_default
        if configured_policy:
            configured_path = Path(configured_policy).expanduser()
            for option in policy_options:
                try:
                    matches = configured_path.resolve() == option.path.resolve()
                except OSError:
                    matches = configured_path == option.path
                if matches:
                    policy_default = option.display
                    break
            else:
                policy_default = configured_policy
        mode_default = str(
            form_values.get(
                "openshell_mode",
                os.environ.get(
                    "AI_GUARDIAN_OPEN_SHELL_SANDBOX_MODE",
                    TRAY_OPENSHELL_MODE_CHOICES[0],
                ),
            )
            or TRAY_OPENSHELL_MODE_CHOICES[0]
        )
        if mode_default not in TRAY_OPENSHELL_MODE_CHOICES:
            mode_default = TRAY_OPENSHELL_MODE_CHOICES[0]
        default_cli = "codex"
        cli = form_values.get("cli") or os.environ.get("AI_GUARDIAN_CLI", default_cli)
        if cli not in cli_choices:
            cli = default_cli
        opencode_agent = form_values.get(
            "agent", os.environ.get("AI_GUARDIAN_OPENCODE_AGENT", "")
        )
        agent_provider = form_values.get(
            "agent_provider", os.environ.get("AI_GUARDIAN_AGENT_PROVIDER", "")
        )
        repo_default = form_values.get("repo") or os.environ.get(
            "AI_GUARDIAN_SANDBOX_REPO"
        )
        if not repo_default:
            target = getattr(self._tray, "_active_target", None)
            if target is None and len(self._tray._targets) == 1:
                target = self._tray._targets[0]
            repo_default = getattr(target, "working_dir", None)
        if not repo_default:
            repo_default = os.path.expanduser("~")
        profile_choices = ("", "@minimal", "@standard", "@strict", "@moderator")
        opencode_agent_choices = ("", "build", "plan", "claude")
        agent_provider_choices = SANDBOX_PI_PROVIDER_CHOICES_BY_RUNTIME[runtime]
        if agent_provider not in agent_provider_choices:
            agent_provider = ""
        model_default = form_values.get("model") or os.environ.get(
            "AI_GUARDIAN_OPEN_SHELL_MODEL", ""
        )
        openshell_auth_default = form_values.get(
            "openshell_auth", os.environ.get("AI_GUARDIAN_OPEN_SHELL_AUTH", "")
        )
        normalized_auth_default = (
            str(openshell_auth_default)
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        if normalized_auth_default in {"api_key", "apikey"}:
            openshell_auth_default = "API key"
        else:
            openshell_auth_default = "OAuth"
        providers_default = form_values.get("providers", "")
        from ai_guardian.sandbox import _generated_openshell_name

        name_default = _generated_openshell_name(cli)
        fields = [
            {
                "name": "runtime",
                "label": "Runtime",
                "type": "choice",
                "choices": ("container", "openshell"),
                "default": runtime,
                "required": True,
                "help": "Use Docker/Podman or NVIDIA OpenShell.",
            },
            {
                "name": "openshell_mode",
                "label": "OpenShell sandbox mode",
                "type": "choice",
                "choices": TRAY_OPENSHELL_MODE_CHOICES,
                "default": mode_default,
                "help": (
                    "Native OpenShell leaves image, hooks, and daemon setup to "
                    "OpenShell; AI Guardian hooks uses the managed support image."
                ),
                "enabled_when": {"field": "runtime", "values": ("openshell",)},
                "clear_when_disabled": True,
            },
            {
                "name": "cli",
                "label": "CLI",
                "type": "choice",
                "choices": cli_choices,
                "choices_by": {
                    "field": "runtime",
                    "values": TRAY_SANDBOX_CLI_CHOICES_BY_RUNTIME,
                },
                "clear_when_choice_invalid": True,
                "default": cli,
                "required": True,
                "help": "Select the CLI to configure in the sandbox.",
            },
            {
                "name": "accept_claude_tos",
                "label": "I accept Anthropic's Claude Code Terms of Service",
                "type": "bool",
                "default": form_values.get("accept_claude_tos") is True,
                "required": True,
                "help": (
                    "AI Guardian managed images do not bundle Claude Code. "
                    "For non-interactive startup, check only after accepting "
                    "Anthropic's terms: "
                    "https://www.anthropic.com/legal/consumer-terms. "
                    "Without consent, startup skips installation."
                ),
                "enabled_when": {"field": "cli", "values": ("claude",)},
                "clear_when_disabled": True,
            },
            {
                "name": "openshell_auth",
                "label": "Codex authentication",
                "type": "choice",
                "choices": TRAY_OPENSHELL_AUTH_CHOICES,
                "default": openshell_auth_default,
                "required": True,
                "help": (
                    "OAuth uses the codex profile and ai-guardian-codex; API key "
                    "uses the openai profile and ai-guardian-openai."
                ),
                "enabled_when": (
                    {"field": "runtime", "values": ("openshell",)},
                    {"field": "openshell_mode", "values": ("AI Guardian hooks",)},
                    {"field": "cli", "values": ("codex",)},
                ),
            },
            {
                "name": "name",
                "label": "Sandbox name",
                "default": name_default,
                "dynamic_default": {
                    "field": "cli",
                    "prefix": "ag-",
                    "value_max_length": 8,
                    "separator": "",
                    "suffix": "",
                },
                "required": True,
                "help": (
                    "Base name; a local timestamp suffix is added only when "
                    "this name is already in use."
                ),
            },
            {
                "name": "agent",
                "label": "OpenCode agent profile",
                "type": "choice",
                "choices": opencode_agent_choices,
                "editable": True,
                "default": opencode_agent,
                "required": True,
                "help": (
                    "Required when CLI is opencode; choose a common profile or "
                    "type a custom name. Passed as opencode --agent NAME."
                ),
                "enabled_when": {"field": "cli", "values": ("opencode",)},
            },
            {
                "name": "agent_provider",
                "label": "Pi provider",
                "type": "choice",
                "choices": agent_provider_choices,
                "editable": runtime == "container",
                "editable_by": {
                    "field": "runtime",
                    "values": {"container": True, "openshell": False},
                },
                "choices_by": {
                    "field": "runtime",
                    "values": SANDBOX_PI_PROVIDER_CHOICES_BY_RUNTIME,
                },
                "clear_when_choice_invalid": True,
                "clear_when_disabled": True,
                "default": agent_provider,
                "help": (
                    "Provider selected by Pi. Anthropic is implemented; direct "
                    "API OpenAI is experimental. ChatGPT/Codex OAuth uses the "
                    "native codex CLI instead."
                    if runtime == "openshell"
                    else "Provider selected by Pi; add a provider-specific "
                    "integration before advertising another choice."
                ),
                "enabled_when": {"field": "cli", "values": ("pi",)},
            },
            {
                "name": "repo",
                "label": "Repository",
                "type": "directory",
                "default": repo_default,
            },
            {
                "name": "config_source",
                "label": "Initial config",
                "type": "choice",
                "choices": _SANDBOX_CONFIG_SOURCE_CHOICES,
                "default": config_source,
                "required": True,
                "help": (
                    "Choose one source: use host/default settings, a profile, a "
                    "host config directory, or the latest saved snapshot."
                ),
            },
            {
                "name": "profile",
                "label": "Profile",
                "type": "choice",
                "choices": profile_choices,
                "editable": True,
                "default": form_values.get("profile", ""),
                "required": True,
                "help": (
                    "Choose a built-in profile or type a custom profile name/path."
                ),
                "enabled_when": {
                    "field": "config_source",
                    "values": ("Profile",),
                },
                "clear_when_disabled": True,
            },
            {
                "name": "config_dir",
                "label": "Host config directory",
                "type": "directory",
                "default": form_values.get("config_dir", ""),
                "required": True,
                "help": "Directory containing the initial ai-guardian.json.",
                "enabled_when": {
                    "field": "config_source",
                    "values": ("Host config directory",),
                },
                "clear_when_disabled": True,
            },
            {
                "name": "image",
                "label": "Image / base",
                "type": "image",
                "default": form_values.get("image", ""),
                "help": (
                    "Leave empty to use the runtime default. Browse lists local "
                    "AI Guardian images; local tags use registry/name:tag, "
                    "for example localhost/ai-guardian-openshell:dev."
                ),
            },
            {
                "name": "model",
                "label": "Inference model",
                "default": model_default,
                "help": "CLI model or OpenShell inference model; empty uses the default.",
                "enabled_when": {"field": "runtime", "values": ("openshell",)},
                "clear_when_disabled": True,
            },
            {
                "name": "policies",
                "label": "Additional policy files",
                "type": "file",
                "multiple": True,
                "default": form_values.get("policies", ""),
                "help": (
                    "Optional custom OpenShell overlays; separate paths with commas "
                    "or newlines."
                ),
                "enabled_when": {"field": "runtime", "values": ("openshell",)},
                "clear_when_disabled": True,
            },
            {
                "name": "policy",
                "label": "OpenShell policy profile",
                "type": "choice",
                "choices": policy_choices,
                "editable": True,
                "default": policy_default,
                "help": (
                    "Optional discovered policy profile. Each choice shows its "
                    "validation state and top-level sections; custom paths are "
                    "also accepted."
                ),
                "enabled_when": {"field": "runtime", "values": ("openshell",)},
                "clear_when_disabled": True,
                "choices_by": {
                    "field": "runtime",
                    "values": {
                        "container": (NO_POLICY_CHOICE,),
                        "openshell": policy_choices,
                    },
                },
                "clear_when_choice_invalid": True,
            },
            {
                "name": "providers",
                "label": "OpenShell provider override",
                "type": "text",
                "default": providers_default,
                "help": (
                    "Optional existing provider instance; leave empty to use the "
                    "Codex authentication selection above. Separate multiple "
                    "providers with commas or newlines."
                ),
                "enabled_when": {"field": "runtime", "values": ("openshell",)},
                "clear_when_disabled": True,
            },
            {
                "name": "environment",
                "label": "Environment",
                "default": "",
                "help": "KEY=VALUE entries; separate values with commas or newlines.",
            },
            {
                "name": "labels",
                "label": "Runtime labels",
                "default": "",
                "help": "Runtime KEY=VALUE labels; separate values with commas or newlines.",
            },
            {
                "name": "port",
                "label": "Host port",
                "default": "",
                "help": (
                    "Container host port 1-65535; empty means runtime-selected. "
                    "OpenShell uses the gateway-selected service port."
                ),
                "enabled_when": {"field": "runtime", "values": ("container",)},
            },
        ]
        if values:
            for field in fields:
                name = field.get("name")
                if (
                    name != "config_source"
                    and name in values
                    and values[name] is not None
                ):
                    field["default"] = values[name]
        return fields

    def _complete_sandbox_create_form(
        self, values, *, screen_bounds=None, on_finished=None
    ):
        """Validate create form values and launch the selected command."""

        def finish_flow():
            if on_finished is not None:
                on_finished()

        runtime = values.get("runtime")
        name = str(values.get("name") or "").strip()
        profile = str(values.get("profile") or "").strip()
        config_dir = str(values.get("config_dir") or "").strip() or None
        openshell_mode = str(
            values.get("openshell_mode") or TRAY_OPENSHELL_MODE_CHOICES[0]
        ).strip()
        config_source_value = values.get("config_source")
        if not config_source_value:
            if profile:
                config_source_value = "Profile"
            elif config_dir:
                config_source_value = "Host config directory"
        config_source = _normalize_sandbox_config_source(config_source_value)
        restore = config_source == "Latest saved snapshot"
        if restore and profile:
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "A saved configuration snapshot cannot be combined with a profile.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            finish_flow()
            return
        if profile and config_source != "Profile":
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "Select Profile as the initial config source or clear the profile field.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            finish_flow()
            return
        if config_dir and config_source != "Host config directory":
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "Select Host config directory as the initial config source or clear the directory field.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            finish_flow()
            return
        if config_source == "Profile" and not profile:
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "Choose a profile for the selected initial config source.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            finish_flow()
            return
        if config_source == "Host config directory" and not config_dir:
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "Choose a host config directory for the selected initial config source.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            finish_flow()
            return
        if runtime not in {"container", "openshell"} or not name:
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "A valid runtime and sandbox name are required.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            finish_flow()
            return
        if restore:
            from ai_guardian.sandbox import _load_snapshot_config

            try:
                _load_snapshot_config(name, "latest", runtime=runtime)
            except ValueError as exc:
                self._sandbox_error(
                    "Create AI Guardian sandbox",
                    str(exc),
                    **self._screen_bounds_kwargs(screen_bounds),
                )
                finish_flow()
                return

        opencode_agent = str(values.get("agent") or "").strip() or None
        agent_provider = str(values.get("agent_provider") or "").strip() or None
        cli_value = str(values.get("cli") or "").strip() or None
        cli = cli_value or "codex"
        native_openshell = runtime == "openshell" and openshell_mode.casefold() in {
            "native",
            "native openshell",
            "native-openshell",
        }
        openshell_auth = None
        if runtime == "openshell" and cli == "codex" and not native_openshell:
            from ai_guardian.sandbox import _normalize_openshell_auth_mode

            try:
                openshell_auth = _normalize_openshell_auth_mode(
                    values.get("openshell_auth") or "oauth"
                )
            except ValueError as exc:
                self._sandbox_error(
                    "Create AI Guardian sandbox",
                    str(exc),
                    **self._screen_bounds_kwargs(screen_bounds),
                )
                finish_flow()
                return
        supported_cli_types = SANDBOX_CLI_IDE_TYPES_BY_RUNTIME.get(runtime, ())
        if cli not in supported_cli_types:
            self._sandbox_error(
                "Create AI Guardian sandbox",
                f"CLI '{cli}' is not supported for {runtime} sandboxes.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            finish_flow()
            return
        if agent_provider and cli != "pi":
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "A Pi provider can only be selected when CLI is pi.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            finish_flow()
            return
        agent_profile = opencode_agent if cli == "opencode" else None
        if cli == "opencode" and not agent_profile:
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "An OpenCode agent profile is required when CLI is opencode.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            finish_flow()
            return
        repo = str(values.get("repo") or "").strip() or None
        image = str(values.get("image") or "").strip() or None
        model = str(values.get("model") or "").strip() or None
        profile_value = profile or None
        policies = str(values.get("policies") or "").strip()
        policy_paths = []
        if runtime == "openshell":
            try:
                policy_paths = self._openshell_policy_paths(values)
            except ValueError as exc:
                self._sandbox_error(
                    "Create AI Guardian sandbox",
                    str(exc),
                    **self._screen_bounds_kwargs(screen_bounds),
                )
                finish_flow()
                return
        if (policies or values.get("policy")) and runtime != "openshell":
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "Policy files are supported for OpenShell sandboxes only.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            finish_flow()
            return
        providers = str(values.get("providers") or "").strip()
        provider_names = []
        for provider in providers.replace("\n", ",").split(","):
            provider = provider.strip()
            if provider:
                provider_names.append(provider)
        environment_values = []
        environment = str(values.get("environment") or "").strip()
        for entry in environment.replace("\n", ",").split(","):
            entry = entry.strip()
            if entry:
                environment_values.append(entry)
        if cli == "claude" and values.get("accept_claude_tos") is True:
            environment_values = [
                entry
                for entry in environment_values
                if entry.partition("=")[0].strip().casefold()
                != "accept_proprietary_tos"
            ]
            environment_values.append("ACCEPT_PROPRIETARY_TOS=true")
        labels = str(values.get("labels") or "").strip()
        label_values = []
        for label in labels.replace("\n", ",").split(","):
            label = label.strip()
            if label:
                if "=" not in label or not label.split("=", 1)[0].strip():
                    self._sandbox_error(
                        "Create AI Guardian sandbox",
                        "Labels must use KEY=VALUE entries separated by commas.",
                        **self._screen_bounds_kwargs(screen_bounds),
                    )
                    finish_flow()
                    return
                label_values.append(label)
        port = str(values.get("port") or "").strip()
        port_value = None
        if port:
            if runtime != "container":
                self._sandbox_error(
                    "Create AI Guardian sandbox",
                    "Host port is supported for container sandboxes only.",
                    **self._screen_bounds_kwargs(screen_bounds),
                )
                finish_flow()
                return
            try:
                if not 1 <= int(port) <= 65535:
                    raise ValueError
            except ValueError:
                self._sandbox_error(
                    "Create AI Guardian sandbox",
                    "Host port must be an integer between 1 and 65535.",
                    **self._screen_bounds_kwargs(screen_bounds),
                )
                finish_flow()
                return
            port_value = int(port)

        if runtime == "openshell" and repo:
            confirmed = self._confirm_sandbox_upload(
                values,
                repo,
                screen_bounds=screen_bounds,
            )
            if not confirmed:
                reopen_kwargs = (
                    {"on_finished": on_finished} if on_finished is not None else {}
                )
                self._reopen_sandbox_create_form(values, screen_bounds, **reopen_kwargs)
                return

        self._run_sandbox_create(
            SimpleNamespace(
                sandbox_command="create",
                runtime=runtime,
                container_engine=None,
                openshell_cli=None,
                name=name,
                cli=cli,
                opencode_agent=agent_profile,
                agent_provider=agent_provider,
                profile=profile_value,
                restore_config="latest" if restore else None,
                fresh_config=config_source == "Host/default",
                config_dir=config_dir,
                repo=repo,
                port=port_value,
                image=image,
                model=model,
                api_key=None,
                openshell_mode=openshell_mode,
                openshell_auth=openshell_auth,
                environment=environment_values,
                policy=[str(path) for path in policy_paths],
                provider=provider_names,
                label=label_values,
                command_args=[],
            ),
            **self._screen_bounds_kwargs(screen_bounds),
        )
        finish_flow()

    def _run_sandbox_create(self, args, *, screen_bounds=None):
        """Create a sandbox in-process and stream output to an isolated dialog."""
        runtime = str(getattr(args, "runtime", None) or "auto-detected")
        on_connect = None
        if runtime in {"container", "openshell"}:
            target = SimpleNamespace(
                name=args.name,
                runtime=runtime,
                runtime_type=runtime,
                container_engine=getattr(args, "container_engine", None),
            )

            def connect_created_sandbox():
                return tray_menu.launch_sandbox_command(
                    target,
                    "connect",
                    [target.name],
                    keep_open=True,
                )

            on_connect = connect_created_sandbox

        progress = self._show_sandbox_progress(
            f"Creating sandbox '{args.name}'",
            f"Operation: create\nRuntime: {runtime}\n"
            "Command is running; output appears below.",
            screen_bounds=screen_bounds,
            on_connect=on_connect,
        )
        output = _SandboxOutput(progress.append if progress else None)
        try:
            from ai_guardian.sandbox import create_sandbox

            result = create_sandbox(args, interactive=False, output=output)
        except Exception as exc:
            logger.exception("Tray sandbox creation failed")
            output.append(f"Error: {exc}\n")
            result = 1

        log_text = "".join(output).strip()
        if result != 0:
            try:
                from ai_guardian.tray.sandbox_dialog import show_sandbox_log

                if not log_text:
                    log_text = f"Sandbox creation failed with exit code {result}."
                message = f"Unable to create sandbox '{args.name}'."
                if progress is None or not progress.finish(False, message, log_text):
                    show_sandbox_log(
                        "Sandbox creation failed",
                        message,
                        log_text,
                        **self._screen_bounds_kwargs(screen_bounds),
                    )
            except Exception:
                logger.exception("Unable to show sandbox creation log")
            return

        if progress is not None:
            progress.finish(
                True,
                f"Sandbox '{args.name}' created.",
                log_text,
                show_connect=on_connect is not None,
            )
        tray_notifications.show_notification(
            "AI Guardian",
            f"Sandbox created: {args.name}",
        )
        if self._tray._discovery:
            self._tray._discovery.request_refresh(wait=False)

    def _run_openshell_middleware_readiness(self, *, screen_bounds=None):
        """Probe configured middleware endpoints and report live identity."""
        try:
            readiness = openshell_middleware.check_openshell_middleware()
            report = openshell_middleware.format_middleware_readiness(readiness)
            from ai_guardian.tray.sandbox_dialog import show_sandbox_log

            show_sandbox_log(
                "OpenShell middleware readiness",
                "The check reads middleware endpoints from gateway TOML and probes "
                "their gRPC Describe identity; gateway activation is shown separately.",
                report,
                **self._screen_bounds_kwargs(screen_bounds),
            )
        except Exception as exc:
            logger.exception("OpenShell middleware readiness check failed")
            self._sandbox_error(
                "OpenShell middleware readiness",
                f"Unable to check OpenShell middleware readiness: {exc}",
                **self._screen_bounds_kwargs(screen_bounds),
            )

    def _mk_openshell_middleware_readiness_action(self):
        """Create a tray action that probes gateway-configured middleware."""

        def action(icon, __):
            screen_bounds = self._capture_sandbox_screen_bounds(icon)
            threading.Thread(
                target=self._run_openshell_middleware_readiness,
                kwargs=self._screen_bounds_kwargs(screen_bounds),
                daemon=True,
                name="openshell-middleware-readiness",
            ).start()

        return action

    @staticmethod
    def _openshell_sandbox_label(record):
        return f"{record['name']} ({record.get('phase', 'unknown')})"

    def _openshell_policy_apply_fields(self, records, sandbox_name=None):
        """Return the form used to select a sandbox and a policy overlay."""
        options = discover_openshell_policies()
        sandbox_choices = tuple(
            self._openshell_sandbox_label(record) for record in records
        )
        if not sandbox_choices:
            sandbox_choices = ("",)
        return [
            {
                "name": "sandbox",
                "label": "OpenShell sandbox",
                "type": "choice",
                "choices": sandbox_choices,
                "editable": sandbox_name is None,
                "default": sandbox_choices[0],
                "required": True,
                "help": (
                    "This menu is scoped to the selected OpenShell sandbox."
                    if sandbox_name is not None
                    else "Eligible live sandboxes are listed with their current "
                    "phase; you may type a name if it was created after this list "
                    "loaded."
                ),
            },
            {
                "name": "policy",
                "label": "Policy profile",
                "type": "choice",
                "width": 68,
                "choices": policy_choice_values(options),
                "editable": True,
                "default": NO_POLICY_CHOICE,
                "required": True,
                "help": (
                    "Choose a discovered profile or enter a policy file path. "
                    "The overlay merges into the sandbox base; the confirmation "
                    "preview shows the complete policy before replacement."
                ),
            },
        ]

    @staticmethod
    def _openshell_selected_sandbox_name(value, records):
        candidate = str(value or "").strip()
        for record in records:
            if candidate == TrayMenuBuilder._openshell_sandbox_label(record):
                return record["name"]
        return candidate

    def _complete_openshell_policy_form(self, values, records, *, screen_bounds=None):
        """Prepare, confirm, and apply a complete policy to one sandbox."""
        name = self._openshell_selected_sandbox_name(values.get("sandbox"), records)
        if not name:
            self._sandbox_error(
                "Apply OpenShell policy",
                "An OpenShell sandbox name is required.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            return

        try:
            policy_paths = self._openshell_policy_paths(
                {"policy": values.get("policy"), "policies": ""}
            )
        except ValueError as exc:
            self._sandbox_error(
                "Apply OpenShell policy",
                str(exc),
                **self._screen_bounds_kwargs(screen_bounds),
            )
            return
        if not policy_paths:
            self._sandbox_error(
                "Apply OpenShell policy",
                "Select a valid OpenShell policy profile before continuing.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            return

        temporary_dir = None
        try:
            from ai_guardian.sandbox import (
                _write_edited_openshell_policy,
                apply_openshell_policy,
                get_openshell_base_policy,
                prepare_openshell_policy_update,
            )

            args = SimpleNamespace(openshell_cli=None)
            policy_path, temporary_dir, current, updated = (
                prepare_openshell_policy_update(args, name, policy_paths)
            )
            complete_policy_yaml = policy_path.read_text(encoding="utf-8").rstrip()
            selected_profiles = ", ".join(str(path) for path in policy_paths)
            message = (
                f"Sandbox: {name}\n\n"
                f"Selected policy profile: {selected_profiles}\n\n"
                f"Current policy: {summarize_openshell_policy(current)}\n"
                f"Initial merged policy: {summarize_openshell_policy(updated)}\n\n"
                "Edit the complete merged YAML below if you wish. It includes the "
                "current sandbox base policy and selected profile overlay. Clicking "
                "Replace policy validates and applies exactly the edited document."
            )
            from ai_guardian.tray.sandbox_dialog import show_sandbox_form

            editor_message = message
            while True:
                editor_values = show_sandbox_form(
                    "Apply OpenShell policy",
                    editor_message,
                    [
                        {
                            "name": "policy_yaml",
                            "label": "Complete merged policy (YAML)",
                            "type": "textarea",
                            "width": 64,
                            "height": 20,
                            "default": complete_policy_yaml,
                            "required": True,
                            "help": (
                                "Make any desired edits. The full document is "
                                "validated before OpenShell replaces the policy."
                            ),
                        }
                    ],
                    submit_label="Replace policy",
                    **self._screen_bounds_kwargs(screen_bounds),
                )
                if editor_values is None:
                    return
                complete_policy_yaml = str(editor_values.get("policy_yaml") or "")
                try:
                    updated = _write_edited_openshell_policy(
                        policy_path,
                        name,
                        current,
                        complete_policy_yaml,
                    )
                except ValueError as exc:
                    editor_message = (
                        f"{message}\n\nPolicy validation failed: {exc}\n"
                        "Your edits are preserved. Correct the YAML and click "
                        "Replace policy again, or cancel without applying."
                    )
                    continue
                break

            output = _SandboxOutput()
            result = apply_openshell_policy(args, name, policy_path, output=output)
            log_text = "".join(output).strip()
            if result == 0:
                try:
                    applied = get_openshell_base_policy(args, name)
                    verification = (
                        "OpenShell accepted and loaded the resulting policy.\n"
                        f"Result: {summarize_openshell_policy(applied)}"
                    )
                except Exception as exc:
                    verification = (
                        "OpenShell policy set returned success, but the follow-up "
                        f"policy read failed: {exc}"
                    )
                tray_notifications.show_notification(
                    "AI Guardian", f"OpenShell policy applied: {name}"
                )
                from ai_guardian.tray.sandbox_dialog import show_sandbox_log

                show_sandbox_log(
                    "OpenShell policy applied",
                    f"Complete policy applied to '{name}'.",
                    verification,
                    **self._screen_bounds_kwargs(screen_bounds),
                )
            else:
                from ai_guardian.tray.sandbox_dialog import show_sandbox_log

                show_sandbox_log(
                    "OpenShell policy failed",
                    f"Unable to apply a policy to '{name}'.",
                    log_text or f"OpenShell exited with code {result}.",
                    **self._screen_bounds_kwargs(screen_bounds),
                )
        except Exception as exc:
            logger.exception("OpenShell policy application failed")
            self._sandbox_error(
                "Apply OpenShell policy",
                f"Unable to prepare the complete policy: {exc}",
                **self._screen_bounds_kwargs(screen_bounds),
            )
        finally:
            if temporary_dir is not None:
                import shutil

                shutil.rmtree(temporary_dir, ignore_errors=True)

    def _mk_openshell_policy_apply_action(self, slot=None):
        """Create an action that applies policy to an optionally selected target."""

        def action(icon, __):
            screen_bounds = self._capture_sandbox_screen_bounds(icon)
            sandbox_name = None
            if slot is not None:
                target = self._sandbox_target_at(slot)
                if target is None or not self._sandbox_is_openshell(slot):
                    return
                sandbox_name = target.name

            def load_form():
                try:
                    from ai_guardian.sandbox import list_openshell_sandboxes

                    records = list_openshell_sandboxes(
                        SimpleNamespace(openshell_cli=None)
                    )
                    if sandbox_name is not None:
                        records = [
                            record
                            for record in records
                            if record.get("name") == sandbox_name
                        ]
                        if not records:
                            self._sandbox_error(
                                "Apply OpenShell policy",
                                f"OpenShell sandbox '{sandbox_name}' is no longer "
                                "available.",
                                **self._screen_bounds_kwargs(screen_bounds),
                            )
                            return
                except Exception as exc:
                    logger.exception("OpenShell sandbox discovery failed")
                    self._sandbox_error(
                        "Apply OpenShell policy",
                        f"Unable to list OpenShell sandboxes: {exc}",
                        **self._screen_bounds_kwargs(screen_bounds),
                    )
                    return

                self._start_sandbox_form(
                    "Apply OpenShell policy",
                    "Select a sandbox and a validated policy profile. Existing policy "
                    "controls are preserved by composing a complete replacement.",
                    self._openshell_policy_apply_fields(records, sandbox_name),
                    lambda values, **kwargs: self._complete_openshell_policy_form(
                        values, records, **kwargs
                    ),
                    name="openshell-policy-apply-form",
                    screen_bounds=screen_bounds,
                )

            threading.Thread(
                target=load_form,
                daemon=True,
                name="openshell-policy-discovery",
            ).start()

        return action

    def _build_openshell_middleware_menu_items(self):
        """Build the standalone middleware readiness action."""
        return [
            pystray.MenuItem(
                "Check middleware readiness...",
                self._mk_openshell_middleware_readiness_action(),
            )
        ]

    @staticmethod
    def _sandbox_operation_parts(operation):
        """Normalize a lifecycle operation and an optional config verb."""
        if isinstance(operation, (tuple, list)):
            return [str(part) for part in operation]
        return [str(operation)]

    def _sandbox_command_args(self, target, operation, command_args):
        """Build the argparse-compatible namespace used by sandbox helpers."""
        parts = self._sandbox_operation_parts(operation)
        runtime = self._sandbox_runtime(target)
        if runtime not in {"container", "openshell"} or not target.name:
            return None

        values = [str(value) for value in (command_args or ())]
        snapshot = "latest"
        if "--snapshot" in values:
            snapshot_index = values.index("--snapshot") + 1
            if snapshot_index < len(values):
                snapshot = values[snapshot_index]

        option_values = {}
        for option in ("tail", "source", "level", "since"):
            option_name = f"--{option}"
            if option_name in values:
                option_index = values.index(option_name) + 1
                if option_index < len(values):
                    option_values[option] = values[option_index]

        return SimpleNamespace(
            sandbox_command=parts[0],
            sandbox_config_command=parts[1] if len(parts) > 1 else None,
            runtime=runtime,
            container_engine=getattr(target, "container_engine", None),
            container_name=getattr(target, "container_name", None),
            openshell_cli=None,
            name=target.name,
            container_id=getattr(target, "container_id", None),
            snapshot=snapshot,
            json_output=False,
            command_args=[],
            follow="--follow" in values,
            tail=option_values.get("tail"),
            source=option_values.get("source"),
            level=option_values.get("level"),
            since=option_values.get("since"),
        )

    def _run_sandbox_command(
        self, target, operation, command_args=None, *, screen_bounds=None
    ):
        """Run a non-interactive sandbox action and show useful output."""
        parts = self._sandbox_operation_parts(operation)
        args = self._sandbox_command_args(target, operation, command_args)
        if args is None:
            return

        progress = None
        if parts[0] == "delete":
            runtime = self._sandbox_runtime(target) or "auto-detected"
            progress = self._show_sandbox_progress(
                f"Deleting sandbox '{target.name}'",
                f"Operation: delete\nRuntime: {runtime}\n"
                "Command is running; output appears below.",
                screen_bounds=screen_bounds,
            )
        output = _SandboxOutput(progress.append if progress else None)
        try:
            from ai_guardian.sandbox import run_sandbox_command

            result = run_sandbox_command(args, output=output)
        except Exception as exc:
            logger.exception("Tray sandbox command failed")
            output.append(f"Error: {exc}\n")
            result = 1

        log_text = "".join(output).strip()
        if parts[0] == "delete":
            if result != 0:
                if not log_text:
                    log_text = f"Sandbox command exited with code {result}."
                message = (
                    f"Unable to run {' '.join(parts)} for sandbox '{target.name}'."
                )
                try:
                    from ai_guardian.tray.sandbox_dialog import show_sandbox_log

                    if progress is None or not progress.finish(
                        False, message, log_text
                    ):
                        show_sandbox_log(
                            "Sandbox command failed",
                            message,
                            log_text,
                            **self._screen_bounds_kwargs(screen_bounds),
                        )
                except Exception:
                    logger.exception("Unable to show sandbox deletion log")
            else:
                if progress is not None:
                    progress.finish(True, f"Sandbox '{target.name}' deleted.", log_text)
                tray_notifications.show_notification(
                    "AI Guardian",
                    f"Sandbox delete: {target.name}",
                )

            if result == 0 and self._tray._discovery:
                self._tray._discovery.request_refresh(wait=False)
            return

        show_log = result != 0 or parts[0] in {"status", "logs", "config"}
        if show_log:
            try:
                from ai_guardian.tray.sandbox_dialog import show_sandbox_log

                if not log_text:
                    log_text = f"Sandbox command exited with code {result}."
                if result == 0:
                    title = f"Sandbox {parts[0]}"
                    message = f"Output from sandbox '{target.name}'."
                else:
                    title = "Sandbox command failed"
                    message = (
                        f"Unable to run {' '.join(parts)} for sandbox "
                        f"'{target.name}'."
                    )
                show_sandbox_log(
                    title,
                    message,
                    log_text,
                    **self._screen_bounds_kwargs(screen_bounds),
                )
            except Exception:
                logger.exception("Unable to show sandbox command log")
        else:
            tray_notifications.show_notification(
                "AI Guardian",
                f"Sandbox {parts[0]}: {target.name}",
            )

        if result == 0 and self._tray._discovery:
            self._tray._discovery.request_refresh(wait=False)

    def _start_sandbox_command(
        self, target, operation, command_args=None, *, screen_bounds=None
    ):
        """Run a non-interactive sandbox action away from the tray callback."""
        thread_options = {}
        if screen_bounds is not None:
            thread_options["kwargs"] = {"screen_bounds": screen_bounds}
        thread = threading.Thread(
            target=self._run_sandbox_command,
            args=(target, operation, command_args),
            daemon=True,
            name="sandbox-command",
            **thread_options,
        )
        thread.start()
        return thread

    def _mk_sandbox_command_action(
        self, slot, operation, arguments=None, *, keep_open=True
    ):
        """Create a menu callback for a command using the selected target."""

        def action(icon, __):
            target = self._sandbox_target_at(slot)
            if target is None:
                return
            screen_bounds = self._capture_sandbox_screen_bounds(icon)
            command_args = arguments(target) if callable(arguments) else arguments
            parts = self._sandbox_operation_parts(operation)
            if parts[0] in {"connect", "exec"}:
                tray_menu.launch_sandbox_command(
                    target,
                    operation,
                    command_args or (),
                    keep_open=keep_open,
                )
            else:
                self._start_sandbox_command(
                    target,
                    operation,
                    command_args,
                    **self._screen_bounds_kwargs(screen_bounds),
                )

        return action

    def _mk_sandbox_exec_action(self, slot):
        """Create a callback that prompts for an exec command."""

        def action(icon, __):
            target = self._sandbox_target_at(slot)
            if target is None:
                return

            def complete(values, *, screen_bounds=None):
                command = str(values.get("command") or "").strip()
                try:
                    command_args = shlex.split(command) if command else []
                except ValueError as exc:
                    self._sandbox_error(
                        "Sandbox exec",
                        f"Invalid command: {exc}",
                        **self._screen_bounds_kwargs(screen_bounds),
                    )
                    return
                args = [target.name]
                if command_args:
                    args.extend(["--", *command_args])
                tray_menu.launch_sandbox_command(target, "exec", args, keep_open=True)

            self._start_sandbox_form(
                "Execute in sandbox",
                "Enter a command to run inside the sandbox.",
                [
                    {
                        "name": "command",
                        "label": "Command",
                        "default": "/bin/bash -l",
                        "help": "Leave empty to use the sandbox login shell.",
                    }
                ],
                complete,
                name="sandbox-exec-form",
                icon=icon,
            )

        return action

    def _mk_sandbox_logs_action(self, slot):
        """Create a callback that prompts for optional log filters."""

        def action(icon, __):
            target = self._sandbox_target_at(slot)
            if target is None:
                return

            def complete(values, *, screen_bounds=None):
                args = [target.name]
                if values.get("follow"):
                    args.append("--follow")
                for option in ("tail", "source", "level", "since"):
                    value = str(values.get(option) or "").strip()
                    if value:
                        args.extend([f"--{option}", value])
                if values.get("follow"):
                    tray_menu.launch_sandbox_command(
                        target, "logs", args, keep_open=True
                    )
                else:
                    self._start_sandbox_command(
                        target,
                        "logs",
                        args,
                        **self._screen_bounds_kwargs(screen_bounds),
                    )

            self._start_sandbox_form(
                "Sandbox logs",
                "Choose optional filters. Followed output opens in a terminal; "
                "one-shot output opens in a log window.",
                [
                    {
                        "name": "follow",
                        "label": "Follow output",
                        "type": "bool",
                        "default": False,
                    },
                    {"name": "tail", "label": "Tail lines", "default": ""},
                    {"name": "source", "label": "OpenShell source", "default": ""},
                    {"name": "level", "label": "OpenShell level", "default": ""},
                    {"name": "since", "label": "OpenShell since", "default": ""},
                ],
                complete,
                name="sandbox-logs-form",
                icon=icon,
            )

        return action

    def _mk_sandbox_restore_action(self, slot):
        """Create a callback that prompts for a snapshot selector."""

        def action(icon, __):
            target = self._sandbox_target_at(slot)
            if target is None:
                return

            def complete(values, *, screen_bounds=None):
                snapshot = str(values.get("snapshot") or "latest").strip()
                self._start_sandbox_command(
                    target,
                    ("config", "restore"),
                    [target.name, "--snapshot", snapshot],
                    **self._screen_bounds_kwargs(screen_bounds),
                )

            self._start_sandbox_form(
                "Restore sandbox configuration",
                "Enter latest or a timestamp from the saved snapshot list.",
                [
                    {
                        "name": "snapshot",
                        "label": "Snapshot",
                        "default": "latest",
                        "required": True,
                    }
                ],
                complete,
                name="sandbox-config-restore-form",
                icon=icon,
            )

        return action

    def _mk_sandbox_delete_action(self, slot):
        """Create a delete action protected by an isolated confirmation."""

        def action(icon, __):
            # Capture the click display before any worker dispatch. This is
            # especially important for the nested OpenShell management menu,
            # whose AppKit menu window may no longer be current by the time
            # the confirmation subprocess is started.
            screen_bounds = self._capture_sandbox_screen_bounds(icon)
            target = self._sandbox_target_at(slot)
            if target is None:
                return

            def confirm_and_delete():
                try:
                    from ai_guardian.tray.sandbox_dialog import (
                        show_sandbox_confirmation,
                    )

                    runtime = self._sandbox_runtime(target) or "unknown"
                    if show_sandbox_confirmation(
                        target.name,
                        runtime,
                        **self._screen_bounds_kwargs(screen_bounds),
                    ):
                        self._start_sandbox_command(
                            target,
                            "delete",
                            [target.name],
                            **self._screen_bounds_kwargs(screen_bounds),
                        )
                except Exception:
                    logger.exception("Sandbox delete confirmation failed")

            threading.Thread(
                target=confirm_and_delete,
                daemon=True,
                name="sandbox-delete-confirmation",
            ).start()

        return action

    def _build_sandbox_manage_menu_item(self, slot):
        """Build the per-target sandbox management submenu."""

        def visible(_item, slot=slot):
            return self._sandbox_target_at(slot) is not None

        def target_running(_item, slot=slot):
            target = self._sandbox_target_at(slot)
            return bool(target and target.status in ("running", "paused"))

        def target_not_running(_item, slot=slot):
            target = self._sandbox_target_at(slot)
            return bool(target and target.status not in ("running", "paused"))

        target_name = lambda target: [target.name]
        config_menu = pystray.Menu(
            pystray.MenuItem(
                "Save",
                self._mk_sandbox_command_action(slot, ("config", "save"), target_name),
                enabled=target_running,
            ),
            pystray.MenuItem(
                "List",
                self._mk_sandbox_command_action(slot, ("config", "list"), target_name),
            ),
            pystray.MenuItem(
                "Restore...",
                self._mk_sandbox_restore_action(slot),
                enabled=target_running,
            ),
        )
        return pystray.MenuItem(
            "Manage sandbox",
            pystray.Menu(
                pystray.MenuItem(
                    "Status",
                    self._mk_sandbox_command_action(slot, "status", target_name),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Apply policy to sandbox...",
                    self._mk_openshell_policy_apply_action(slot),
                    visible=lambda _item, slot=slot: self._sandbox_is_openshell(slot),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Start",
                    self._mk_sandbox_command_action(slot, "start", target_name),
                    enabled=target_not_running,
                    visible=lambda _item, slot=slot: (
                        self._sandbox_runtime(self._sandbox_target_at(slot))
                        == "openshell"
                    ),
                ),
                pystray.MenuItem(
                    "Stop",
                    self._mk_sandbox_command_action(slot, "stop", target_name),
                    enabled=target_running,
                ),
                pystray.MenuItem(
                    "Restart",
                    self._mk_sandbox_command_action(slot, "restart", target_name),
                ),
                pystray.MenuItem(
                    "Connect",
                    self._mk_sandbox_connect_action(slot),
                    enabled=target_running,
                    visible=lambda _item, slot=slot: not self._sandbox_is_openshell(
                        slot
                    ),
                ),
                pystray.MenuItem(
                    "Exec...",
                    self._mk_sandbox_exec_action(slot),
                    enabled=target_running,
                ),
                pystray.MenuItem(
                    "Logs...",
                    self._mk_sandbox_logs_action(slot),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Config", config_menu),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Delete...",
                    self._mk_sandbox_delete_action(slot),
                ),
            ),
            visible=visible,
        )

    def _build_sandbox_create_menu_items(self):
        """Build the always-available main-menu sandbox create action."""
        return [
            pystray.MenuItem(
                "Create sandbox...",
                self._mk_sandbox_create_action(),
                enabled=lambda _item: not self._sandbox_create_is_in_progress(),
            )
        ]

    def _stopped_container_targets(self):
        """Return stopped container-engine sandboxes for the start menu."""
        return tuple(
            sorted(
                (
                    target
                    for target in getattr(self._tray, "_stopped_container_targets", ())
                    if self._sandbox_runtime(target) in {"container", "openshell"}
                ),
                key=lambda target: target.name.casefold(),
            )
        )

    def _mk_sandbox_start_container_action(self, target):
        """Create the main-menu action for one stopped container."""

        def action(icon, __):
            screen_bounds = self._capture_sandbox_screen_bounds(icon)
            self._start_sandbox_command(
                target,
                "start",
                [target.name],
                **self._screen_bounds_kwargs(screen_bounds),
            )

        return action

    def _build_sandbox_start_menu_items(self):
        """Build the main-menu submenu for stopped container-engine sandboxes."""
        targets = self._stopped_container_targets()
        items = [
            pystray.MenuItem(
                f"{target.name} ({self._sandbox_runtime(target)})",
                self._mk_sandbox_start_container_action(target),
            )
            for target in targets
        ]
        if not items:
            items = [
                pystray.MenuItem(
                    "No stopped containers",
                    None,
                    enabled=False,
                )
            ]

        return [
            pystray.MenuItem(
                "Start stopped sandbox...",
                pystray.Menu(*items),
                visible=lambda _item: bool(self._stopped_container_targets()),
            )
        ]

    def _build_single_daemon_menu_items(self):
        """Build flat menu items for single-daemon mode.

        When exactly one daemon is discovered, all submenu items are
        promoted to the top level. Visible only when len(targets) == 1.
        """

        def _single_vis(_item):
            return self._tray._is_single_daemon()

        def _single_vis_refresh(_item):
            return self._tray._is_single_daemon()

        def _single_running(_item):
            if not self._tray._is_single_daemon():
                return False
            if self._tray._targets[0].status in ("running", "paused"):
                return True
            return self._tray._can_autostart_daemon()

        def _single_not_running(_item):
            return self._tray._is_single_daemon() and self._tray._targets[
                0
            ].status not in (
                "running",
                "paused",
            )

        def _header_label(_item):
            if not self._tray._targets:
                return ""
            return self._version_annotated_label(self._tray._targets[0])

        def _open_panel(panel=None):
            def action(_, __):
                self._tray._check_and_autostart_daemon()
                if self._tray._ensure_web_console_ready():
                    web_page = (
                        tray_menu.PANEL_TO_WEB_PATH.get(panel, "") if panel else ""
                    )
                    daemon_name = (
                        self._tray._targets[0].name if self._tray._targets else ""
                    )
                    tray_menu.open_web_console(daemon_name, web_page)
                    return
                if self._tray._targets:
                    t = self._tray._targets[0]
                    if self._tray._multi_client:
                        self._tray._multi_client.open_console(t, panel)
                    else:
                        tray_menu.launch_console(panel)

            return action

        def _open_shell():
            def action(_, __):
                self._tray._check_and_autostart_daemon()
                if self._tray._targets:
                    t = self._tray._targets[0]
                    if self._tray._multi_client:
                        self._tray._multi_client.open_shell(t)
                    else:
                        tray_menu.launch_shell(
                            cwd=getattr(t, "working_dir", None),
                        )

            return action

        if self._sandbox_is_openshell(0):
            shell_item = pystray.MenuItem(
                "Connect",
                self._mk_sandbox_connect_action(0),
                visible=_single_vis,
                enabled=lambda _item: self._sandbox_is_running(0),
            )
        else:
            shell_item = pystray.MenuItem(
                "Terminal",
                _open_shell(),
                visible=_single_vis,
            )

        def _open_doctor():
            def action(_, __):
                self._tray._check_and_autostart_daemon()
                if self._tray._targets:
                    t = self._tray._targets[0]
                    if self._tray._multi_client:
                        self._tray._multi_client.open_doctor(t)
                    else:
                        tray_menu.launch_doctor()

            return action

        def _stop_action(_, __):
            if self._tray._targets and self._tray._multi_client:
                self._tray._multi_client.send_stop(self._tray._targets[0])

        def _restart_action(_, __):
            if self._tray._health._restart_in_progress:
                return
            if not (self._tray._targets and self._tray._multi_client):
                return
            self._tray._health._restart_in_progress = True
            self._tray._dispatch_to_main(self._tray._refresh_menu)
            self._tray._multi_client.send_restart(self._tray._targets[0])

            def _poll():
                import json as _json

                from ai_guardian.daemon import get_pid_path

                pid_path = get_pid_path()
                old_pid = None
                try:
                    if pid_path.exists():
                        old_pid = _json.loads(pid_path.read_text()).get("pid")
                except Exception:
                    pass
                for _ in range(100):
                    time.sleep(0.1)
                    try:
                        if pid_path.exists():
                            new_pid = _json.loads(pid_path.read_text()).get("pid")
                            if new_pid and new_pid != old_pid:
                                break
                    except Exception:
                        pass
                self._tray._health._restart_in_progress = False
                self._tray._refresh_event.set()

            threading.Thread(target=_poll, daemon=True, name="restart-poll").start()

        def _get_stats(_item):
            return self._get_slot_stats(0)

        def _s_requests(_item):
            s = _get_stats(_item)
            return f"Requests: {s.get('request_count', 0):,}"

        def _s_blocked(_item):
            s = _get_stats(_item)
            b = s.get("blocked_count", 0)
            t = s.get("request_count", 0)
            if t > 0:
                return f"Blocked: {b:,} ({b/t*100:.1f}%)"
            return f"Blocked: {b:,}"

        def _s_warned(_item):
            s = _get_stats(_item)
            return f"Warned: {s.get('warning_count', 0):,}"

        def _s_logged(_item):
            s = _get_stats(_item)
            return f"Logged: {s.get('log_only_count', 0):,}"

        def _s_violations(_item):
            s = _get_stats(_item)
            return f"Violations: {s.get('violation_count', 0):,}"

        def _s_critical(_item):
            s = _get_stats(_item)
            return f"  Critical: {s.get('critical_count', 0):,}"

        def _s_warning_sev(_item):
            s = _get_stats(_item)
            return f"  Warning: {s.get('warning_severity_count', 0):,}"

        def _s_last_block(_item):
            s = _get_stats(_item)
            bt = s.get("last_block_type")
            ba = s.get("last_block_seconds_ago")
            if bt is None:
                return "Last block: none"
            return f"Last block: {bt} {tray_notifications.format_time_ago(ba)}"

        def _s_ask_dialogs(_item):
            s = _get_stats(_item)
            count = s.get("ask_dialog_count", 0)
            total_ms = s.get("ask_dialog_total_ms", 0)
            if total_ms >= 1000:
                return f"Ask dialogs: {count:,} (wait: {total_ms / 1000:.1f}s)"
            return f"Ask dialogs: {count:,} (wait: {total_ms:.0f}ms)"

        def _s_ask_dialogs_visible(_item):
            s = _get_stats(_item)
            return s.get("ask_dialog_count", 0) > 0

        def _s_config_reload(_item):
            s = _get_stats(_item)
            ago = s.get("last_config_reload_seconds_ago")
            if ago is not None:
                return f"Config reloaded: {tray_notifications.format_time_ago(ago)}"
            return "Config: loaded"

        self._single_daemon_closures = {
            "stop_action": _stop_action,
            "restart_action": _restart_action,
            "single_running": _single_running,
            "single_not_running": _single_not_running,
            "get_stats": _get_stats,
        }

        def _stale_vis(_item):
            if not self._tray._is_single_daemon() or not self._tray._targets:
                return False
            return (
                self._tray._targets[0].runtime == "local"
                and self._tray._health._stale_code_warned
                and not self._tray._health._restart_in_progress
            )

        def _stale_vis_remote(_item):
            if not self._tray._is_single_daemon() or not self._tray._targets:
                return False
            t = self._tray._targets[0]
            return t.runtime in (
                "container",
                "kubernetes",
            ) and self._tray._health._is_target_stale(t)

        def _stale_remote_label(_item):
            from ai_guardian import __version__ as _hv

            if self._tray._targets:
                t = self._tray._targets[0]
                daemon_ver = self._tray._health._daemon_versions.get(
                    (t.name, t.runtime), ""
                )
                if daemon_ver:
                    return f"⚠️ Host v{_hv} newer than container v{daemon_ver} — rebuild image"
            return "⚠️ Container daemon outdated — rebuild image to update"

        def _on_restart_daemon(_icon, _item):
            if self._tray._health._restart_in_progress:
                return
            self._tray._health._restart_in_progress = True
            self._tray._dispatch_to_main(self._tray._refresh_menu)

            import json as _json

            from ai_guardian.daemon import get_pid_path

            pid_path = get_pid_path()
            old_pid = None
            try:
                if pid_path.exists():
                    old_pid = _json.loads(pid_path.read_text()).get("pid")
            except Exception:
                pass

            cmd = tray_plugins.resolve_cli_cmd("daemon", "restart")
            import subprocess as _sp

            try:
                _sp.Popen(
                    cmd,
                    stdin=_sp.DEVNULL,
                    stdout=_sp.DEVNULL,
                    stderr=_sp.DEVNULL,
                    start_new_session=True,
                )
            except OSError as e:
                logger.error("Failed to restart daemon: %s", e)
                self._tray._health._restart_in_progress = False
                self._tray._dispatch_to_main(self._tray._refresh_menu)
                return

            def _poll_for_new_daemon():
                for _ in range(100):
                    time.sleep(0.1)
                    try:
                        if pid_path.exists():
                            new_pid = _json.loads(pid_path.read_text()).get("pid")
                            if new_pid and new_pid != old_pid:
                                break
                    except Exception:
                        pass

                self._tray._health._restart_in_progress = False
                self._tray._refresh_event.set()

            threading.Thread(
                target=_poll_for_new_daemon, daemon=True, name="restart-poll"
            ).start()

        pause_item = self._build_pause_menu_item(visible=_single_vis)

        return [
            pystray.MenuItem(
                "⚠️ Daemon running old code — click to restart",
                _on_restart_daemon,
                visible=_stale_vis,
            ),
            pystray.MenuItem(
                _stale_remote_label,
                None,
                visible=_stale_vis_remote,
                enabled=False,
            ),
            pystray.MenuItem(_header_label, None, visible=_single_vis_refresh),
            self._build_daemon_status_menu_item(
                0,
                visible=lambda _item: self._tray._is_single_daemon(),
            ),
            pause_item,
            shell_item,
            self._build_sandbox_manage_menu_item(0),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Console",
                _open_panel(None),  # None means main console page
                visible=_single_vis,
                enabled=_single_running,
            ),
            pystray.MenuItem(
                "Violations",
                _open_panel("panel-violations"),
                visible=_single_vis,
                enabled=_single_running,
            ),
            pystray.MenuItem(
                "Metrics & Audit",
                _open_panel("panel-metrics"),
                visible=_single_vis,
                enabled=_single_running,
            ),
            pystray.MenuItem(
                "Statistics",
                pystray.Menu(
                    pystray.MenuItem(_s_requests, None),
                    pystray.MenuItem(_s_blocked, None),
                    pystray.MenuItem(_s_warned, None),
                    pystray.MenuItem(_s_logged, None),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(_s_violations, None),
                    pystray.MenuItem(_s_critical, None),
                    pystray.MenuItem(_s_warning_sev, None),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(_s_last_block, None),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        _s_ask_dialogs, None, visible=_s_ask_dialogs_visible
                    ),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(_s_config_reload, None),
                ),
                visible=_single_vis,
                enabled=_single_running,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: self._mcp_proactive_label(),
                pystray.Menu(
                    pystray.MenuItem(
                        "low",
                        lambda _, __: self._tray._on_change_proactive("low"),
                        checked=lambda _: self._tray._proactive_level == "low",
                        radio=True,
                    ),
                    pystray.MenuItem(
                        "medium",
                        lambda _, __: self._tray._on_change_proactive("medium"),
                        checked=lambda _: self._tray._proactive_level == "medium",
                        radio=True,
                    ),
                    pystray.MenuItem(
                        "high",
                        lambda _, __: self._tray._on_change_proactive("high"),
                        checked=lambda _: self._tray._proactive_level == "high",
                        radio=True,
                    ),
                    pystray.MenuItem(
                        "paused",
                        lambda _, __: self._tray._on_change_proactive("paused"),
                        checked=lambda _: self._tray._proactive_level == "paused",
                        radio=True,
                    ),
                ),
                visible=lambda _: _single_vis(_)
                and self._tray._is_mcp_for_current_target(),
                enabled=_single_running,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: self._working_dir_menu_label(0),
                self._mk_change_working_dir(0),
                visible=_single_vis,
            ),
            *(
                [
                    self._support_menu_item(
                        self._tray._targets[0], flat=True, visible=_single_vis
                    )
                ]
                if self._tray._targets
                else []
            ),
        ]

    def _build_pause_menu_item(self, *, visible=lambda _: True):
        """One action, not a nested duration/scope menu."""
        return pystray.MenuItem("Pause...", self._on_pause_controls, visible=visible)

    def _on_pause_controls(self, icon, _item):
        if not self._pause_dialog_lock.acquire(blocking=False):
            return
        screen_bounds = self._capture_tray_screen_bounds(icon)

        def show():
            try:
                from ai_guardian.tray.pause import open_pause_controls

                open_pause_controls(self._tray, screen_bounds=screen_bounds)
            except Exception as exc:
                logger.warning("Pause controls ended (%s)", type(exc).__name__)
            finally:
                self._pause_dialog_lock.release()

        try:
            threading.Thread(target=show, daemon=True, name="pause-controls").start()
        except (OSError, RuntimeError):
            self._pause_dialog_lock.release()
            logger.warning("Pause controls worker could not start")

    def _build_single_daemon_daemon_items(self):
        """Build daemon operation items for single-daemon mode.

        Start/Stop/Restart actions follow the single-daemon menu. Must be called
        after _build_single_daemon_menu_items().
        """
        c = self._single_daemon_closures
        _stop_action = c["stop_action"]
        _restart_action = c["restart_action"]
        _single_not_running = c["single_not_running"]

        return [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start daemon", _restart_action, visible=_single_not_running
            ),
            pystray.MenuItem(
                lambda _: self._tray._health._upgrade_label(
                    self._tray._targets[0] if self._tray._targets else None,
                ),
                self._tray._health._on_upgrade_single,
                visible=lambda _: (
                    self._tray._is_single_daemon()
                    and self._tray._targets
                    and self._tray._health._is_upgrade_available(self._tray._targets[0])
                ),
            ),
            pystray.MenuItem(
                lambda _: self._tray._health._self_upgrade_label(),
                self._tray._health._on_self_upgrade,
                visible=lambda _: self._tray._health._is_self_upgrade_available(),
            ),
        ]

    def _build_multi_daemon_menu_items(self):
        """Build per-daemon action submenus for every discovered daemon.

        Each daemon gets its own submenu with Console, Pause, Restart, etc.
        The tray rebuilds this part of the menu when discovery changes the
        number of targets, so there is no fixed daemon-count limit.

        Only visible when 2+ daemons are discovered.
        """
        items = []
        for i in range(len(self._tray._targets)):
            target = self._tray._targets[i]
            idx = target if target.runtime == "ssh" else i

            def make_label(_item, slot=idx):
                t = self._target_at(slot)
                if t is None:
                    return ""
                return self._version_annotated_label(t)

            def make_visible(_item, slot=idx):
                return (
                    self._tray._is_multi_daemon() and self._target_at(slot) is not None
                )

            def _mk_open_panel(panel=None, slot=idx, selected=target):
                if not isinstance(slot, int):
                    return self._ssh_action(
                        slot, lambda t: self._open_ssh_panel(t, panel)
                    )

                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if panel and self._tray._ensure_web_console_ready():
                        web_page = tray_menu.PANEL_TO_WEB_PATH.get(panel, "")
                        daemon_name = (
                            selected.name if slot < len(self._tray._targets) else ""
                        )
                        tray_menu.open_web_console(daemon_name, web_page)
                        return
                    if slot < len(self._tray._targets):
                        t = selected
                        if self._tray._multi_client:
                            self._tray._multi_client.open_console(t, panel)
                        else:
                            tray_menu.launch_console(panel)

                return action

            def _mk_web_console_action(slot=idx, selected=target):
                if not isinstance(slot, int):
                    return self._ssh_action(slot, self._open_ssh_panel)

                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if self._tray._ensure_web_console_ready():
                        if slot < len(self._tray._targets):
                            tray_menu.open_web_console(selected.name)
                        return
                    if slot < len(self._tray._targets):
                        t = selected
                        if self._tray._multi_client:
                            self._tray._multi_client.open_console(t)
                        else:
                            tray_menu.launch_console()

                return action

            def _mk_web_console_visible(slot=idx):
                def check(_):
                    return self._target_at(slot) is not None

                return check

            def _mk_open_shell(slot=idx, selected=target):
                if not isinstance(slot, int):
                    return self._ssh_action(slot, self._tray._multi_client.open_shell)

                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if slot < len(self._tray._targets):
                        t = selected
                        if self._tray._multi_client:
                            self._tray._multi_client.open_shell(t)
                        else:
                            tray_menu.launch_shell(
                                cwd=getattr(t, "working_dir", None),
                            )

                return action

            if self._sandbox_is_openshell(idx):
                shell_item = pystray.MenuItem(
                    "Connect",
                    self._mk_sandbox_connect_action(idx),
                    enabled=lambda _item, slot=idx: self._sandbox_is_running(slot),
                )
            else:
                shell_item = pystray.MenuItem("Terminal", _mk_open_shell())

            def _mk_doctor(slot=idx, selected=target):
                if not isinstance(slot, int):
                    return self._ssh_action(slot, self._tray._multi_client.open_doctor)

                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if slot < len(self._tray._targets):
                        t = selected
                        if self._tray._multi_client:
                            self._tray._multi_client.open_doctor(t)
                        else:
                            tray_menu.launch_doctor()

                return action

            def _mk_stop(slot=idx, selected=target):
                if not isinstance(slot, int):
                    return self._ssh_action(slot, self._tray._multi_client.send_stop)

                def action(_, __):
                    if slot < len(self._tray._targets):
                        t = selected
                        if self._tray._multi_client:
                            self._tray._multi_client.send_stop(t)

                return action

            def _mk_restart(slot=idx, selected=target):
                if not isinstance(slot, int):
                    return self._ssh_action(slot, self._tray._multi_client.send_restart)

                def action(_, __):
                    if self._tray._health._restart_in_progress:
                        return
                    if slot >= len(self._tray._targets):
                        return
                    t = selected
                    if not self._tray._multi_client:
                        return
                    self._tray._health._restart_in_progress = True
                    self._tray._dispatch_to_main(self._tray._refresh_menu)
                    self._tray._multi_client.send_restart(t)

                    def _poll(target=t):
                        if target.runtime == "local":
                            import json as _json

                            from ai_guardian.daemon import get_pid_path

                            pid_path = get_pid_path()
                            old_pid = None
                            try:
                                if pid_path.exists():
                                    old_pid = _json.loads(pid_path.read_text()).get(
                                        "pid"
                                    )
                            except Exception:
                                pass
                            for _ in range(100):
                                time.sleep(0.1)
                                try:
                                    if pid_path.exists():
                                        new_pid = _json.loads(pid_path.read_text()).get(
                                            "pid"
                                        )
                                        if new_pid and new_pid != old_pid:
                                            break
                                except Exception:
                                    pass
                        else:
                            time.sleep(3.0)
                        self._tray._health._restart_in_progress = False
                        self._tray._refresh_event.set()

                    threading.Thread(
                        target=_poll, daemon=True, name="restart-poll"
                    ).start()

                return action

            def _mk_daemon_stale_vis(slot=idx):
                def check(_item):
                    t = self._target_at(slot)
                    if t is None:
                        return False
                    return (
                        t.runtime == "local"
                        and self._tray._health._is_target_stale(t)
                        and not self._tray._health._restart_in_progress
                    )

                return check

            def _mk_daemon_stale_vis_remote(slot=idx):
                def check(_item):
                    t = self._target_at(slot)
                    if t is None:
                        return False
                    return t.runtime in (
                        "container",
                        "kubernetes",
                    ) and self._tray._health._is_target_stale(t)

                return check

            def _mk_stale_remote_label(slot=idx):
                def label(_item):
                    from ai_guardian import __version__ as _hv

                    t = self._target_at(slot)
                    if t is None:
                        return "⚠️ Container daemon outdated — rebuild image"
                    daemon_ver = self._tray._health._daemon_versions.get(
                        (t.name, t.runtime), ""
                    )
                    if daemon_ver:
                        return f"⚠️ Host v{_hv} newer than container v{daemon_ver} — rebuild image"
                    return "⚠️ Container daemon outdated — rebuild image"

                return label

            def _mk_stats(slot=idx):
                def _get(_item):
                    return self._get_slot_stats(slot)

                def requests(_item):
                    s = _get(_item)
                    return f"Requests: {s.get('request_count', 0):,}"

                def blocked(_item):
                    s = _get(_item)
                    b = s.get("blocked_count", 0)
                    t = s.get("request_count", 0)
                    if t > 0:
                        return f"Blocked: {b:,} ({b/t*100:.1f}%)"
                    return f"Blocked: {b:,}"

                def warned(_item):
                    s = _get(_item)
                    return f"Warned: {s.get('warning_count', 0):,}"

                def logged(_item):
                    s = _get(_item)
                    return f"Logged: {s.get('log_only_count', 0):,}"

                def violations(_item):
                    s = _get(_item)
                    return f"Violations: {s.get('violation_count', 0):,}"

                def critical(_item):
                    s = _get(_item)
                    return f"  Critical: {s.get('critical_count', 0):,}"

                def warning_sev(_item):
                    s = _get(_item)
                    return f"  Warning: {s.get('warning_severity_count', 0):,}"

                def last_block(_item):
                    s = _get(_item)
                    bt = s.get("last_block_type")
                    ba = s.get("last_block_seconds_ago")
                    if bt is None:
                        return "Last block: none"
                    return f"Last block: {bt} {tray_notifications.format_time_ago(ba)}"

                def ask_dialogs(_item):
                    s = _get(_item)
                    count = s.get("ask_dialog_count", 0)
                    total_ms = s.get("ask_dialog_total_ms", 0)
                    if total_ms >= 1000:
                        return f"Ask dialogs: {count:,} (wait: {total_ms / 1000:.1f}s)"
                    return f"Ask dialogs: {count:,} (wait: {total_ms:.0f}ms)"

                def ask_dialogs_visible(_item):
                    try:
                        return int(_get(_item).get("ask_dialog_count", 0)) > 0
                    except (TypeError, ValueError):
                        return False

                def config_reload(_item):
                    s = _get(_item)
                    ago = s.get("last_config_reload_seconds_ago")
                    if ago is not None:
                        return f"Config reloaded: {tray_notifications.format_time_ago(ago)}"
                    return "Config: loaded"

                return (
                    requests,
                    blocked,
                    warned,
                    logged,
                    violations,
                    critical,
                    warning_sev,
                    last_block,
                    ask_dialogs,
                    ask_dialogs_visible,
                    config_reload,
                )

            stats_fns = _mk_stats()

            def _is_slot_running(_item, slot=idx):
                t = self._target_at(slot)
                if t is None:
                    return False
                if t.status in ("running", "paused"):
                    return True
                return t.runtime != "ssh" and self._tray._can_autostart_daemon()

            multi_plugin_items = self._tray._plugins._build_multi_daemon_plugin_slots(
                target
            )

            status_item = self._build_daemon_status_menu_item(idx)

            daemon_item = pystray.MenuItem(
                make_label,
                pystray.Menu(
                    pystray.MenuItem(
                        "⚠️ Running old code — click to restart",
                        _mk_restart(),
                        visible=_mk_daemon_stale_vis(),
                    ),
                    pystray.MenuItem(
                        _mk_stale_remote_label(),
                        None,
                        visible=_mk_daemon_stale_vis_remote(),
                        enabled=False,
                    ),
                    status_item,
                    shell_item,
                    self._build_sandbox_manage_menu_item(idx),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        "Console",
                        _mk_web_console_action(idx),
                        visible=_mk_web_console_visible(idx),
                        enabled=_is_slot_running,
                    ),
                    pystray.MenuItem(
                        "Violations",
                        _mk_open_panel("panel-violations"),
                        enabled=_is_slot_running,
                    ),
                    pystray.MenuItem(
                        "Metrics & Audit",
                        _mk_open_panel("panel-metrics"),
                        enabled=_is_slot_running,
                    ),
                    pystray.MenuItem(
                        "Statistics",
                        pystray.Menu(
                            pystray.MenuItem(stats_fns[0], None),
                            pystray.MenuItem(stats_fns[1], None),
                            pystray.MenuItem(stats_fns[2], None),
                            pystray.MenuItem(stats_fns[3], None),
                            pystray.Menu.SEPARATOR,
                            pystray.MenuItem(stats_fns[4], None),
                            pystray.MenuItem(stats_fns[5], None),
                            pystray.MenuItem(stats_fns[6], None),
                            pystray.Menu.SEPARATOR,
                            pystray.MenuItem(stats_fns[7], None),
                            pystray.Menu.SEPARATOR,
                            pystray.MenuItem(stats_fns[8], None, visible=stats_fns[9]),
                            pystray.Menu.SEPARATOR,
                            pystray.MenuItem(stats_fns[10], None),
                        ),
                        enabled=_is_slot_running,
                    ),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        lambda _i, s=idx: self._mcp_proactive_label(s),
                        pystray.Menu(
                            pystray.MenuItem(
                                "Remote MCP state unavailable; reconnect or upgrade the daemon. If MCP is not installed, run setup on the VM.",
                                None,
                                enabled=False,
                                visible=lambda _, s=idx: not isinstance(s, int)
                                and not self._proactive_available(s),
                            ),
                            pystray.MenuItem(
                                "low",
                                self._mk_proactive_change(idx, "low"),
                                checked=lambda _, s=idx: self._proactive_for_slot(s)
                                == "low",
                                enabled=lambda _, s=idx: self._proactive_available(s),
                                radio=True,
                            ),
                            pystray.MenuItem(
                                "medium",
                                self._mk_proactive_change(idx, "medium"),
                                checked=lambda _, s=idx: self._proactive_for_slot(s)
                                == "medium",
                                enabled=lambda _, s=idx: self._proactive_available(s),
                                radio=True,
                            ),
                            pystray.MenuItem(
                                "high",
                                self._mk_proactive_change(idx, "high"),
                                checked=lambda _, s=idx: self._proactive_for_slot(s)
                                == "high",
                                enabled=lambda _, s=idx: self._proactive_available(s),
                                radio=True,
                            ),
                            pystray.MenuItem(
                                "paused",
                                self._mk_proactive_change(idx, "paused"),
                                checked=lambda _, s=idx: self._proactive_for_slot(s)
                                == "paused",
                                enabled=lambda _, s=idx: self._proactive_available(s),
                                radio=True,
                            ),
                        ),
                        visible=lambda _i, s=idx: not isinstance(s, int)
                        or self._tray._is_mcp_for_slot(s),
                        enabled=_is_slot_running,
                    ),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        lambda _i, s=idx: self._working_dir_menu_label(s),
                        self._mk_change_working_dir(target),
                    ),
                    pystray.Menu.SEPARATOR,
                    *multi_plugin_items,
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        "Start daemon",
                        _mk_restart(),
                        visible=lambda _i, s=idx: (
                            self._target_at(s) is not None
                            and self._target_at(s).status not in ("running", "paused")
                        ),
                    ),
                    pystray.MenuItem(
                        lambda _i, s=idx: self._tray._health._upgrade_label(
                            self._target_at(s),
                        ),
                        self._tray._health._mk_upgrade(target),
                        visible=lambda _i, s=idx: (
                            self._target_at(s) is not None
                            and self._tray._health._is_upgrade_available(
                                self._target_at(s)
                            )
                        ),
                    ),
                    pystray.Menu.SEPARATOR,
                    self._support_menu_item(target, flat=len(self._tray._targets) == 1),
                    pystray.MenuItem(
                        self._daemon_about_label(target),
                        self._on_daemon_about(target),
                        enabled=_is_slot_running,
                    ),
                    *self._ssh_management_items(target),
                ),
                visible=make_visible,
            )
            if target.runtime == "ssh" and len(self._tray._targets) == 1:
                items.append(pystray.MenuItem(make_label, None))
                for item in daemon_item.submenu.items:
                    items.append(item)
                    if item is status_item:
                        items.append(self._build_pause_menu_item())
            else:
                items.append(daemon_item)
        if len(self._tray._targets) != 1:
            items.append(
                self._build_pause_menu_item(visible=lambda _: bool(self._tray._targets))
            )
        return items

    def _ssh_management_items(self, target):
        if target.runtime != "ssh":
            return []
        from ai_guardian.tray.ssh_connections import open_management

        return [
            pystray.MenuItem(
                "Remote CLI unavailable — start the daemon and reconnect, or use Terminal",
                None,
                enabled=False,
                visible=lambda _: target.ssh_commands is None
                or target.ssh_commands.cli is None,
            ),
            pystray.MenuItem(
                "Manage SSH connection...",
                self._ssh_action(target, lambda _: open_management(self._tray)),
            ),
        ]

    def _build_ide_setup_menu_items(self):
        """Build the top-level IDE/CLI setup submenu.

        Always visible regardless of daemon count. Groups the on-demand hook
        health check with targeted per-IDE setup and config creation so the
        three user flows are discoverable in one place.
        """
        from ai_guardian.setup import IDESetup

        def _mk_ide_action(k):
            def action(_, __):
                tray_menu.launch_ide_setup(k)

            return action

        ide_items = [
            pystray.MenuItem(
                "Check hooks/MCP installation...",
                self._tray._health._on_check_ide_setup,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Manual setup (specific IDE)", None),
        ]

        def _ide_display_name(ide_key, ide_cfg):
            return "Cursor IDE/CLI" if ide_key == "cursor" else ide_cfg["name"]

        # Dummy Agent is an internal hook-testing harness, not a user-facing
        # IDE/CLI integration with a manual setup flow.
        manual_setup_configs = [
            item for item in IDESetup.IDE_CONFIGS.items() if item[0] != "dummy-agent"
        ]
        for ide_key, ide_cfg in sorted(
            manual_setup_configs,
            key=lambda item: _ide_display_name(*item).casefold(),
        ):
            ide_label = _ide_display_name(ide_key, ide_cfg)
            ide_items.append(
                pystray.MenuItem(f"  {ide_label}", _mk_ide_action(ide_key))
            )
            if ide_key == "cursor":
                ide_items.append(
                    pystray.MenuItem(
                        "  Cursor Cloud (project setup)...",
                        self._mk_cursor_cloud_setup_action(),
                    )
                )
        ide_items.extend(
            [
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Configuration", None),
                pystray.MenuItem(
                    "  Create Config...",
                    lambda _, __: tray_menu.launch_create_config(),
                ),
            ]
        )

        return [
            pystray.MenuItem(
                "IDE/CLI Setup...",
                pystray.Menu(*ide_items),
            ),
        ]
