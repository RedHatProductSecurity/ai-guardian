"""
Menu construction for the system tray — single-daemon, multi-daemon,
directory pause, IDE setup, and about menus.

Split from tray.py (Issue #1542). TrayMenuBuilder constructs pystray
MenuItem trees by reading state from DaemonTray and its sub-managers.
"""

import logging
import threading
import time

from ai_guardian.tray import icons as tray_icons
from ai_guardian.tray import menu as tray_menu
from ai_guardian.tray import notifications as tray_notifications
from ai_guardian.tray import plugins as tray_plugins

logger = logging.getLogger(__name__)

try:
    import pystray
except Exception:
    pystray = None


class TrayMenuBuilder:
    """Constructs pystray menu item trees for the system tray."""

    from ai_guardian.tray.menu import (
        MAX_DAEMON_SLOTS as _MAX_DAEMON_SLOTS,
        MAX_DIR_PAUSE_SLOTS as _MAX_DIR_PAUSE_SLOTS,
    )

    def __init__(self, tray):
        self._tray = tray
        self._single_daemon_closures = {}

    def _on_about(self, icon, item):
        """Show About info via OS dialog."""

        def _show():
            try:
                from ai_guardian.tray.plugins import show_dialog

                text = tray_menu.build_about_text()
                if self._tray._is_multi_daemon():
                    text += self._format_daemon_list()
                show_dialog("About AI Guardian", text)
            except Exception:
                pass  # intentionally silent — optional dependency

        threading.Thread(target=_show, daemon=True, name="about-dialog").start()

    def _daemon_about_label(self, slot):
        """Build About menu label with daemon version for a specific slot."""

        def _label(_item=None):
            if slot >= len(self._tray._targets):
                return "About"
            target = self._tray._targets[slot]
            key = (target.name, target.runtime)
            version = self._tray._health._daemon_versions.get(key, "")
            if version:
                return f"About — v{version}"
            return "About"

        return _label

    def _on_daemon_about(self, slot):
        """Show About info for a specific daemon via OS dialog."""

        def action(_, __):
            if slot >= len(self._tray._targets):
                return
            target = self._tray._targets[slot]

            def _show():
                try:
                    from ai_guardian.tray.plugins import show_dialog

                    info = self._tray._daemon_about_cache.get(slot)
                    if info is None and self._tray._multi_client:
                        info = self._tray._multi_client.get_about(target)
                        if info:
                            self._tray._daemon_about_cache[slot] = info
                    if info:
                        from ai_guardian.daemon.about import format_about_text

                        text = format_about_text(info)
                    else:
                        text = tray_menu.build_about_text()
                    show_dialog(f"About {target.name}", text)
                except Exception:
                    pass  # intentionally silent — optional dependency

            threading.Thread(
                target=_show, daemon=True, name="daemon-about-dialog"
            ).start()

        return action

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

    def _pause_menu_label(self):
        return "Pause..."

    def _resume_menu_label(self):
        stats = self._tray._get_stats()
        remaining = stats.get("pause_remaining_seconds", 0)
        if remaining > 0:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            return f"Resume ({mins}m {secs}s left)"
        return "Resume (paused)"

    def _get_merged_dir_list(self, stats):
        """Merge active project dirs and paused dirs into a sorted list."""
        active = set(stats.get("active_project_dirs") or [])
        paused = set(stats.get("paused_dirs") or {})
        return sorted(active | paused)

    def _multi_global_pause_label(self, stats_fns, _item):
        """Format global pause label with status circle for multi-daemon."""
        is_paused = stats_fns[11](_item)
        if is_paused:
            stats = stats_fns[13](_item)
            remaining = stats.get("pause_remaining_seconds", 0)
            if remaining > 0:
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                return f"☾ Daemon (global) ({mins}m {secs}s)"
            return "☾ Daemon (global)"
        return "● Daemon (global)"

    def _mk_multi_pause_dir(self, slot):
        """Create a pause_dir callback for a multi-daemon slot."""

        def pause_dir_fn(directory, minutes):
            if slot < len(self._tray._targets) and self._tray._multi_client:
                self._tray._multi_client.send_pause_dir(
                    self._tray._targets[slot],
                    directory,
                    minutes,
                )

        return pause_dir_fn

    def _mk_multi_resume_dir(self, slot):
        """Create a resume_dir callback for a multi-daemon slot."""

        def resume_dir_fn(directory):
            if slot < len(self._tray._targets) and self._tray._multi_client:
                self._tray._multi_client.send_resume_dir(
                    self._tray._targets[slot],
                    directory,
                )

        return resume_dir_fn

    def _build_dir_pause_items(self, get_stats_fn, pause_dir_fn, resume_dir_fn):
        """Build pre-allocated per-directory pause/resume menu items.

        Returns a list of pystray.MenuItem, one per slot, each with a
        submenu for duration options or resume. Uses visibility lambdas
        to show only slots with actual directories.
        """
        from ai_guardian.daemon.working_dir import shorten_path

        items = []
        for i in range(self._MAX_DIR_PAUSE_SLOTS):
            slot = i

            def _dir_at(s, stats, slot=slot):
                dirs = self._get_merged_dir_list(stats)
                if slot < len(dirs):
                    return dirs[slot]
                return None

            def _is_visible(_item, slot=slot):
                stats = get_stats_fn(_item)
                return _dir_at(None, stats, slot) is not None

            def _label(_item, slot=slot):
                stats = get_stats_fn(_item)
                d = _dir_at(None, stats, slot)
                if d is None:
                    return ""
                paused_dirs = stats.get("paused_dirs") or {}
                short = shorten_path(d)
                if len(short) > 40:
                    short = "..." + short[-37:]
                if d in paused_dirs:
                    remaining = paused_dirs[d]
                    if remaining > 0:
                        mins = int(remaining // 60)
                        secs = int(remaining % 60)
                        return f"☾ {short} ({mins}m {secs}s)"
                    return f"☾ {short}"
                return f"● {short}"

            def _is_paused(_item, slot=slot):
                stats = get_stats_fn(_item)
                d = _dir_at(None, stats, slot)
                if d is None:
                    return False
                return d in (stats.get("paused_dirs") or {})

            def _is_active(_item, slot=slot):
                stats = get_stats_fn(_item)
                d = _dir_at(None, stats, slot)
                if d is None:
                    return False
                return d not in (stats.get("paused_dirs") or {})

            def _mk_dir_pause(minutes, slot=slot):
                def action(_, __):
                    stats = get_stats_fn(None)
                    d = _dir_at(None, stats, slot)
                    if d:
                        pause_dir_fn(d, minutes)

                return action

            def _mk_dir_resume(slot=slot):
                def action(_, __):
                    stats = get_stats_fn(None)
                    d = _dir_at(None, stats, slot)
                    if d:
                        resume_dir_fn(d)

                return action

            def _full_path_label(_item, slot=slot):
                stats = get_stats_fn(_item)
                d = _dir_at(None, stats, slot)
                return shorten_path(d) if d else ""

            items.append(
                pystray.MenuItem(
                    _label,
                    pystray.Menu(
                        pystray.MenuItem(
                            _full_path_label,
                            None,
                            enabled=False,
                        ),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem(
                            "5 minutes",
                            _mk_dir_pause(5),
                            visible=_is_active,
                        ),
                        pystray.MenuItem(
                            "15 minutes",
                            _mk_dir_pause(15),
                            visible=_is_active,
                        ),
                        pystray.MenuItem(
                            "30 minutes",
                            _mk_dir_pause(30),
                            visible=_is_active,
                        ),
                        pystray.MenuItem(
                            "1 hour",
                            _mk_dir_pause(60),
                            visible=_is_active,
                        ),
                        pystray.MenuItem(
                            "Until resume",
                            _mk_dir_pause(0),
                            visible=_is_active,
                        ),
                        pystray.MenuItem(
                            "Resume",
                            _mk_dir_resume(),
                            visible=_is_paused,
                        ),
                    ),
                    visible=_is_visible,
                )
            )
        return items

    def _version_annotated_label(self, target):
        """Format daemon label with version mismatch indicator if needed."""
        stats = self._tray._get_target_stats(target)
        active_dirs = stats.get("active_project_dirs") or []
        label = tray_menu.daemon_status_label(
            target,
            has_paused_dirs=bool(stats.get("paused_dirs")),
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

    def _working_dir_menu_label(self, slot):
        """Format the Working Dir menu item label for a daemon slot."""
        from ai_guardian.daemon.working_dir import shorten_path

        if slot < len(self._tray._targets):
            wd = getattr(self._tray._targets[slot], "working_dir", None)
            if wd:
                short = shorten_path(wd)
                if len(short) > 50:
                    short = short[:47] + "..."
                return f"Working Dir: {short}"
        return "Working Dir: ~"

    def _mk_change_working_dir(self, slot):
        """Create a click handler that opens a directory picker for a slot."""

        def action(_, __):
            if slot >= len(self._tray._targets):
                return
            t = self._tray._targets[slot]
            current = getattr(t, "working_dir", None)
            threading.Thread(
                target=self._pick_working_dir,
                args=(t, current),
                daemon=True,
                name="working-dir-picker",
            ).start()

        return action

    def _pick_working_dir(self, target, current):
        """Run directory picker in background thread and persist result."""
        from ai_guardian.daemon.working_dir import choose_directory, set_working_dir

        chosen = choose_directory(current)
        if chosen:
            target.working_dir = chosen
            set_working_dir(target.name, chosen)
            self._tray._refresh_event.set()

    def _apply_working_dirs(self):
        """Populate target.working_dir from persisted state after discovery."""
        from ai_guardian.daemon.working_dir import get_working_dir

        for t in self._tray._targets:
            if not getattr(t, "working_dir", None):
                t.working_dir = get_working_dir(t.name)

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
                if (
                    self._tray._has_web_console
                    and self._tray._ensure_web_console_ready()
                ):
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

        def _pause_action(minutes):
            def action(_, __):
                self._tray._check_and_autostart_daemon()
                if self._tray._targets:
                    t = self._tray._targets[0]
                    if self._tray._multi_client:
                        self._tray._multi_client.send_pause(t, minutes)
                    else:
                        self._tray._pause(minutes)
                    self._tray.update_status("paused")

            return action

        def _resume_action(_, __):
            self._tray._check_and_autostart_daemon()
            if self._tray._targets:
                t = self._tray._targets[0]
                if self._tray._multi_client:
                    self._tray._multi_client.send_resume(t)
                else:
                    self._tray._pause(0)
                self._tray.update_status("running")

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

        _cache = {"stats": {}, "time": 0}

        def _get_stats(_item):
            import time as time_mod

            now = time_mod.monotonic()
            if now - _cache["time"] < 2.0:
                return _cache["stats"]
            if not self._tray._targets:
                return {}
            target = self._tray._targets[0]
            if self._tray._multi_client and target.runtime != "local":
                result = self._tray._multi_client.get_status(target)
                if result and result.get("name"):
                    target.name = result["name"]
                _cache["stats"] = result or {}
            else:
                _cache["stats"] = self._tray._get_stats()
            stats = _cache["stats"]
            if stats:
                key = (target.name, target.runtime)
                if "mcp_installed" in stats:
                    self._tray._mcp_installed_per_daemon[key] = stats["mcp_installed"]
                if "version" in stats:
                    self._tray._health._daemon_versions[key] = stats["version"]
            _cache["time"] = now
            return stats

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
            "pause_action": _pause_action,
            "resume_action": _resume_action,
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
                lambda _: f"MCP Proactive: {self._tray._proactive_level}",
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
            pystray.MenuItem("Terminal", _open_shell(), visible=_single_vis),
        ]

    def _build_single_daemon_daemon_items(self):
        """Build daemon operation items for single-daemon mode.

        Pause/Resume and Start/Stop/Restart grouped together without
        internal separators. Separated from preceding items by a
        separator. Must be called after _build_single_daemon_menu_items().
        """
        c = self._single_daemon_closures
        _pause_action = c["pause_action"]
        _resume_action = c["resume_action"]
        _stop_action = c["stop_action"]
        _restart_action = c["restart_action"]
        _single_running = c["single_running"]
        _single_not_running = c["single_not_running"]
        _get_stats = c["get_stats"]

        def _global_pause_label(_item):
            stats = _get_stats(_item)
            if stats.get("paused"):
                remaining = stats.get("pause_remaining_seconds", 0)
                if remaining > 0:
                    mins = int(remaining // 60)
                    secs = int(remaining % 60)
                    return f"☾ Daemon (global) ({mins}m {secs}s)"
                return "☾ Daemon (global)"
            return "● Daemon (global)"

        def _global_is_paused(_item):
            return _get_stats(_item).get("paused", False)

        def _global_is_active(_item):
            return not _get_stats(_item).get("paused", False)

        def _pause_dir_action(directory, minutes):
            if self._tray._targets and self._tray._multi_client:
                self._tray._multi_client.send_pause_dir(
                    self._tray._targets[0],
                    directory,
                    minutes,
                )

        def _resume_dir_action(directory):
            if self._tray._targets and self._tray._multi_client:
                self._tray._multi_client.send_resume_dir(
                    self._tray._targets[0],
                    directory,
                )

        dir_pause_items = self._build_dir_pause_items(
            _get_stats,
            _pause_dir_action,
            _resume_dir_action,
        )

        def _has_dirs(_item):
            stats = _get_stats(_item)
            return bool(self._get_merged_dir_list(stats))

        return [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Pause...",
                pystray.Menu(
                    pystray.MenuItem(
                        _global_pause_label,
                        pystray.Menu(
                            pystray.MenuItem(
                                "5 minutes",
                                _pause_action(5),
                                visible=_global_is_active,
                            ),
                            pystray.MenuItem(
                                "15 minutes",
                                _pause_action(15),
                                visible=_global_is_active,
                            ),
                            pystray.MenuItem(
                                "30 minutes",
                                _pause_action(30),
                                visible=_global_is_active,
                            ),
                            pystray.MenuItem(
                                "1 hour",
                                _pause_action(60),
                                visible=_global_is_active,
                            ),
                            pystray.MenuItem(
                                "Until resume",
                                _pause_action(0),
                                visible=_global_is_active,
                            ),
                            pystray.MenuItem(
                                "Resume",
                                _resume_action,
                                visible=_global_is_paused,
                            ),
                        ),
                    ),
                    pystray.Menu.SEPARATOR,
                    *dir_pause_items,
                ),
                visible=_single_running,
            ),
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
        """Build fixed-slot menu items with per-daemon action submenus.

        Each daemon gets its own submenu with Console, Pause, Restart, etc.
        pystray on macOS requires items defined at build time, so we
        pre-allocate slots with dynamic text/visibility lambdas.

        Only visible when 2+ daemons are discovered.
        """
        items = []
        for i in range(self._MAX_DAEMON_SLOTS):
            idx = i

            def make_label(_item, slot=idx):
                if slot >= len(self._tray._targets):
                    return ""
                return self._version_annotated_label(self._tray._targets[slot])

            def make_visible(_item, slot=idx):
                return self._tray._is_multi_daemon() and slot < len(self._tray._targets)

            def _mk_open_panel(panel=None, slot=idx):
                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if (
                        panel
                        and self._tray._has_web_console
                        and self._tray._ensure_web_console_ready()
                    ):
                        web_page = tray_menu.PANEL_TO_WEB_PATH.get(panel, "")
                        daemon_name = (
                            self._tray._targets[slot].name
                            if slot < len(self._tray._targets)
                            else ""
                        )
                        tray_menu.open_web_console(daemon_name, web_page)
                        return
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.open_console(t, panel)
                        else:
                            tray_menu.launch_console(panel)

                return action

            def _mk_web_console_action(slot=idx):
                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if (
                        self._tray._has_web_console
                        and self._tray._ensure_web_console_ready()
                    ):
                        if slot < len(self._tray._targets):
                            tray_menu.open_web_console(self._tray._targets[slot].name)
                        return
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.open_console(t)
                        else:
                            tray_menu.launch_console()

                return action

            def _mk_web_console_visible(slot=idx):
                def check(_):
                    return self._tray._has_web_console and slot < len(
                        self._tray._targets
                    )

                return check

            def _mk_open_shell(slot=idx):
                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.open_shell(t)
                        else:
                            tray_menu.launch_shell(
                                cwd=getattr(t, "working_dir", None),
                            )

                return action

            def _mk_doctor(slot=idx):
                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.open_doctor(t)
                        else:
                            tray_menu.launch_doctor()

                return action

            def _mk_pause(minutes, slot=idx):
                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.send_pause(t, minutes)
                        else:
                            self._tray._pause(minutes)
                        self._tray._update_global_pause_status()

                return action

            def _mk_resume(slot=idx):
                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.send_resume(t)
                        else:
                            self._tray._pause(0)
                        self._tray._update_global_pause_status()

                return action

            def _mk_stop(slot=idx):
                def action(_, __):
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.send_stop(t)

                return action

            def _mk_restart(slot=idx):
                def action(_, __):
                    if self._tray._health._restart_in_progress:
                        return
                    if slot >= len(self._tray._targets):
                        return
                    t = self._tray._targets[slot]
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
                    if slot >= len(self._tray._targets):
                        return False
                    t = self._tray._targets[slot]
                    return (
                        t.runtime == "local"
                        and self._tray._health._is_target_stale(t)
                        and not self._tray._health._restart_in_progress
                    )

                return check

            def _mk_daemon_stale_vis_remote(slot=idx):
                def check(_item):
                    if slot >= len(self._tray._targets):
                        return False
                    t = self._tray._targets[slot]
                    return t.runtime in (
                        "container",
                        "kubernetes",
                    ) and self._tray._health._is_target_stale(t)

                return check

            def _mk_stale_remote_label(slot=idx):
                def label(_item):
                    from ai_guardian import __version__ as _hv

                    if slot >= len(self._tray._targets):
                        return "⚠️ Container daemon outdated — rebuild image"
                    t = self._tray._targets[slot]
                    daemon_ver = self._tray._health._daemon_versions.get(
                        (t.name, t.runtime), ""
                    )
                    if daemon_ver:
                        return f"⚠️ Host v{_hv} newer than container v{daemon_ver} — rebuild image"
                    return "⚠️ Container daemon outdated — rebuild image"

                return label

            def _mk_stats(slot=idx):
                _cache = {"stats": {}, "time": 0}

                def _get(_item):
                    import time as time_mod

                    now = time_mod.monotonic()
                    if now - _cache["time"] < 2.0:
                        return _cache["stats"]
                    if slot >= len(self._tray._targets):
                        return {}
                    target = self._tray._targets[slot]
                    if self._tray._multi_client and target.runtime != "local":
                        result = self._tray._multi_client.get_status(target)
                        if result and result.get("name"):
                            target.name = result["name"]
                        _cache["stats"] = result or {}
                    else:
                        _cache["stats"] = self._tray._get_stats()
                    stats = _cache["stats"]
                    if stats:
                        key = (target.name, target.runtime)
                        if "mcp_installed" in stats:
                            self._tray._mcp_installed_per_daemon[key] = stats[
                                "mcp_installed"
                            ]
                        if "version" in stats:
                            self._tray._health._daemon_versions[key] = stats["version"]
                    _cache["time"] = now
                    return stats

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

                def is_paused(_item):
                    return _get(_item).get("paused", False)

                def resume_label(_item):
                    s = _get(_item)
                    remaining = s.get("pause_remaining_seconds", 0)
                    if remaining > 0:
                        mins = int(remaining // 60)
                        secs = int(remaining % 60)
                        return f"Resume ({mins}m {secs}s left)"
                    return "Resume (paused)"

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
                    is_paused,
                    resume_label,
                    _get,
                )

            stats_fns = _mk_stats()

            def _is_slot_running(_item, slot=idx):
                if slot >= len(self._tray._targets):
                    return False
                if self._tray._targets[slot].status in ("running", "paused"):
                    return True
                return self._tray._can_autostart_daemon()

            multi_plugin_items = self._tray._plugins._build_multi_daemon_plugin_slots(
                idx
            )

            items.append(
                pystray.MenuItem(
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
                                pystray.MenuItem(
                                    stats_fns[8], None, visible=stats_fns[9]
                                ),
                                pystray.Menu.SEPARATOR,
                                pystray.MenuItem(stats_fns[10], None),
                            ),
                            enabled=_is_slot_running,
                        ),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem(
                            lambda _: f"MCP Proactive: {self._tray._proactive_level}",
                            pystray.Menu(
                                pystray.MenuItem(
                                    "low",
                                    lambda _, __: self._tray._on_change_proactive(
                                        "low"
                                    ),
                                    checked=lambda _: self._tray._proactive_level
                                    == "low",
                                    radio=True,
                                ),
                                pystray.MenuItem(
                                    "medium",
                                    lambda _, __: self._tray._on_change_proactive(
                                        "medium"
                                    ),
                                    checked=lambda _: self._tray._proactive_level
                                    == "medium",
                                    radio=True,
                                ),
                                pystray.MenuItem(
                                    "high",
                                    lambda _, __: self._tray._on_change_proactive(
                                        "high"
                                    ),
                                    checked=lambda _: self._tray._proactive_level
                                    == "high",
                                    radio=True,
                                ),
                            ),
                            visible=lambda _i, s=idx: self._tray._is_mcp_for_slot(s),
                            enabled=_is_slot_running,
                        ),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem(
                            lambda _i, s=idx: self._working_dir_menu_label(s),
                            self._mk_change_working_dir(idx),
                        ),
                        pystray.MenuItem("Terminal", _mk_open_shell()),
                        pystray.Menu.SEPARATOR,
                        *multi_plugin_items,
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem(
                            "Pause...",
                            pystray.Menu(
                                pystray.MenuItem(
                                    lambda _i, _sf=stats_fns: (
                                        self._multi_global_pause_label(_sf, _i)
                                    ),
                                    pystray.Menu(
                                        pystray.MenuItem(
                                            "5 minutes",
                                            _mk_pause(5),
                                            visible=lambda _i, _sf=stats_fns: (
                                                not _sf[11](_i)
                                            ),
                                        ),
                                        pystray.MenuItem(
                                            "15 minutes",
                                            _mk_pause(15),
                                            visible=lambda _i, _sf=stats_fns: (
                                                not _sf[11](_i)
                                            ),
                                        ),
                                        pystray.MenuItem(
                                            "30 minutes",
                                            _mk_pause(30),
                                            visible=lambda _i, _sf=stats_fns: (
                                                not _sf[11](_i)
                                            ),
                                        ),
                                        pystray.MenuItem(
                                            "1 hour",
                                            _mk_pause(60),
                                            visible=lambda _i, _sf=stats_fns: (
                                                not _sf[11](_i)
                                            ),
                                        ),
                                        pystray.MenuItem(
                                            "Until resume",
                                            _mk_pause(0),
                                            visible=lambda _i, _sf=stats_fns: (
                                                not _sf[11](_i)
                                            ),
                                        ),
                                        pystray.MenuItem(
                                            "Resume",
                                            _mk_resume(),
                                            visible=lambda _i, _sf=stats_fns: (
                                                _sf[11](_i)
                                            ),
                                        ),
                                    ),
                                ),
                                pystray.Menu.SEPARATOR,
                                *self._build_dir_pause_items(
                                    stats_fns[13],
                                    self._mk_multi_pause_dir(idx),
                                    self._mk_multi_resume_dir(idx),
                                ),
                            ),
                            visible=_is_slot_running,
                        ),
                        pystray.MenuItem(
                            "Start daemon",
                            _mk_restart(),
                            visible=lambda _i, s=idx: (
                                s < len(self._tray._targets)
                                and self._tray._targets[s].status
                                not in ("running", "paused")
                            ),
                        ),
                        pystray.MenuItem(
                            lambda _i, s=idx: self._tray._health._upgrade_label(
                                (
                                    self._tray._targets[s]
                                    if s < len(self._tray._targets)
                                    else None
                                ),
                            ),
                            self._tray._health._mk_upgrade(idx),
                            visible=lambda _i, s=idx: (
                                s < len(self._tray._targets)
                                and self._tray._health._is_upgrade_available(
                                    self._tray._targets[s]
                                )
                            ),
                        ),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem(
                            self._daemon_about_label(idx),
                            self._on_daemon_about(idx),
                            enabled=_is_slot_running,
                        ),
                    ),
                    visible=make_visible,
                )
            )
        return items

    def _build_ide_setup_menu_items(self):
        """Build the top-level 'Local Setup...' submenu.

        Always visible regardless of daemon count. Contains config
        creation and per-IDE hook setup entries.
        """
        from ai_guardian.setup import IDESetup

        def _mk_ide_action(k):
            def action(_, __):
                tray_menu.launch_ide_setup(k)

            return action

        ide_items = [
            pystray.MenuItem("IDE Hooks (required)", None),
        ]
        for ide_key, ide_cfg in IDESetup.IDE_CONFIGS.items():
            ide_items.append(
                pystray.MenuItem(f"  {ide_cfg['name']}", _mk_ide_action(ide_key))
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
                "Local Setup...",
                pystray.Menu(*ide_items),
            ),
        ]
