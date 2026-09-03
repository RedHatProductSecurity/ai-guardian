"""
Health monitoring for the system tray — version checks, stale code,
config error notifications, and daemon upgrade management.

Split from tray.py (Issue #1542). TrayHealthMonitor holds version mismatch,
upgrade, and notification state. It receives a back-reference to DaemonTray.
"""

import logging
import threading

from ai_guardian.tray import notifications as tray_notifications
from ai_guardian.tray import plugins as tray_plugins

logger = logging.getLogger(__name__)


class TrayHealthMonitor:
    """Monitors daemon health: version mismatches, stale code, config errors."""

    def __init__(self, tray):
        self._tray = tray
        self._config_error_notified = False
        self._version_mismatch_notified = set()
        self._daemon_versions = {}
        self._stale_code_warned = False
        self._restart_in_progress = False
        self._pip_available = {}
        self._pypi_latest = None
        self._pypi_last_check = 0.0
        self._upgrade_in_progress = set()
        self._self_upgrade_in_progress = False
        self._upgrade_notified_version = None
        self._upgrade_prompt_in_progress = False
        self._ide_setup_prompt_in_progress = False

    def _check_config_error_notification(self):
        """Show OS notification once when a config error is detected."""
        stats = self._tray._get_stats()
        config_error = stats.get("config_error")
        if config_error and not self._config_error_notified:
            self._config_error_notified = True
            threading.Thread(
                target=tray_notifications.send_config_error_notification,
                daemon=True,
                name="config-error-notify",
            ).start()
        elif not config_error and self._config_error_notified:
            self._config_error_notified = False

    def _check_version_mismatch(self):
        """Check each daemon's version against the tray version and warn on mismatch."""
        try:
            from ai_guardian import __version__ as tray_version
        except ImportError:
            return

        tray_tuple = tray_notifications.parse_version_tuple(tray_version)
        if tray_tuple is None:
            return

        for target in self._tray._targets:
            if target.status not in ("running", "paused"):
                continue
            key = (target.name, target.runtime)
            daemon_version = self._daemon_versions.get(key)
            if daemon_version is None:
                continue

            daemon_tuple = tray_notifications.parse_version_tuple(daemon_version)
            if daemon_tuple is None:
                continue

            if daemon_tuple < tray_tuple:
                if key not in self._version_mismatch_notified:
                    self._version_mismatch_notified.add(key)
                    name = target.name
                    threading.Thread(
                        target=tray_notifications.send_version_mismatch_notification,
                        args=(name, daemon_version, tray_version),
                        daemon=True,
                        name="version-mismatch-notify",
                    ).start()
                if key not in self._pip_available:
                    threading.Thread(
                        target=self._check_pip_available_for_target,
                        args=(target,),
                        daemon=True,
                        name="pip-check",
                    ).start()
            elif key in self._version_mismatch_notified:
                self._version_mismatch_notified.discard(key)

    def _check_stale_code(self):
        """Warn in tray when daemon runs stale source code (#1465).

        Check 1 (dev only): source file mtime changed since daemon started.
        Check 2 (all versions): PID-file version differs from installed version.
        Sets _stale_code_warned and refreshes the icon when state changes.
        """
        try:
            import json as _json

            from ai_guardian import __version__
            from ai_guardian.daemon import get_pid_path

            pid_path = get_pid_path()
            if not pid_path.exists():
                self._set_stale_warned(False)
                return

            try:
                pid_info = _json.loads(pid_path.read_text())
            except Exception:
                return

            stale = False

            # Check 1: dev mtime
            if __version__.endswith("-dev"):
                pid_mtime = pid_info.get("source_mtime", 0.0)
                if pid_mtime:
                    from ai_guardian.daemon.state import DaemonState

                    current_mtime = DaemonState.get_package_max_mtime()
                    if current_mtime > pid_mtime:
                        stale = True

            # Check 2: installed version vs daemon version
            if not stale:
                daemon_version = pid_info.get("version", "")
                if daemon_version and daemon_version != __version__:
                    stale = True

            self._set_stale_warned(stale)

        except Exception:
            pass  # intentionally silent — best-effort check

    def _set_stale_warned(self, stale: bool):
        """Update _stale_code_warned and refresh icon/menu if state changed."""
        if stale == self._stale_code_warned:
            return
        self._stale_code_warned = stale
        self._tray._anim._invalidate_discovery_frames()
        if self._tray._icon:
            self._tray._dispatch_to_main(
                lambda: (
                    setattr(self._tray._icon, "icon", self._tray._create_icon()),
                    self._tray._icon.update_menu(),
                )
            )

    def _is_target_stale(self, target) -> bool:
        """Return True if a specific daemon target is running stale code."""
        if target.runtime == "local":
            return self._stale_code_warned
        return (target.name, target.runtime) in self._version_mismatch_notified

    def _check_pypi_version(self):
        """Fetch latest version from PyPI (throttled to every 300s)."""
        import time as _time

        now = _time.monotonic()
        if now - self._pypi_last_check < 300:
            return
        self._pypi_last_check = now
        try:
            from ai_guardian.daemon.multi_client import MultiDaemonClient

            version = MultiDaemonClient.check_pypi_version()
            if version:
                self._pypi_latest = version
        except (OSError, ValueError, KeyError):
            pass  # intentionally silent — best-effort operation

    def _check_pip_available_for_target(self, target):
        """Check pip availability on a target (runs in background thread)."""
        key = (target.name, target.runtime)
        try:
            if self._tray._multi_client:
                available = self._tray._multi_client.check_pip_available(target)
            else:
                import subprocess as _sp

                python_exe = tray_plugins.get_python_executable()
                result = _sp.run(
                    [python_exe, "-m", "pip", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                available = result.returncode == 0
            self._pip_available[key] = available
        except Exception:
            self._pip_available[key] = False

    def _is_upgrade_available(self, target):
        """Return True if target has a version mismatch and pip is available.

        Only offers upgrade if tray version is installable (not a dev version).
        """
        if not target:
            return False
        key = (target.name, target.runtime)
        # Don't offer upgrade if tray is running a dev version (not on PyPI)
        try:
            from ai_guardian import __version__ as tray_version

            if "-dev" in tray_version or "dev" in tray_version.lower():
                return False
        except ImportError:
            return False
        return (
            key in self._version_mismatch_notified
            and self._pip_available.get(key, False)
            and key not in self._upgrade_in_progress
        )

    def _upgrade_label(self, target):
        """Dynamic label for the sync-to-tray-version menu item."""
        if target:
            key = (target.name, target.runtime)
            if key in self._upgrade_in_progress:
                return "Syncing…"
        try:
            from ai_guardian import __version__ as tray_version

            return f"Match Tray v{tray_version}"
        except ImportError:
            return "Match Tray Version"

    def _do_upgrade_daemon(self, target):
        """Sync daemon version to match tray version (runs in background thread)."""
        key = (target.name, target.runtime)
        self._upgrade_in_progress.add(key)
        self._tray._dispatch_to_main(self._tray._refresh_menu)

        # Get tray version to sync to
        try:
            from ai_guardian import __version__ as tray_version
        except ImportError:
            tray_version = None

        try:
            from ai_guardian.tray.plugins import send_notification

            send_notification(
                "AI Guardian",
                (
                    f"Syncing ai-guardian on '{target.name}' to v{tray_version}…"
                    if tray_version
                    else f"Syncing ai-guardian on '{target.name}'…"
                ),
            )
        except Exception:
            pass  # intentionally silent — optional dependency

        success = False
        output = ""
        try:
            if self._tray._multi_client:
                success, output = self._tray._multi_client.run_pip_upgrade(
                    target, tray_version
                )
            else:
                import subprocess as _sp

                python_exe = tray_plugins.get_python_executable()
                # Install specific version to match tray
                if tray_version:
                    cmd = [
                        python_exe,
                        "-m",
                        "pip",
                        "install",
                        f"ai-guardian=={tray_version}",
                    ]
                else:
                    cmd = [
                        python_exe,
                        "-m",
                        "pip",
                        "install",
                        "--upgrade",
                        "ai-guardian",
                    ]
                result = _sp.run(cmd, capture_output=True, text=True, timeout=120)
                success = result.returncode == 0
                output = result.stdout + result.stderr
        except Exception as exc:
            output = str(exc)

        try:
            from ai_guardian.tray.plugins import send_notification

            if success:
                send_notification(
                    "AI Guardian",
                    f"Version sync complete on '{target.name}'. Restarting daemon…",
                )
                if self._tray._multi_client:
                    self._tray._multi_client.send_restart(target)
                self._version_mismatch_notified.discard(key)
                self._daemon_versions.pop(key, None)
                self._pip_available.pop(key, None)
            else:
                first_line = (
                    output.strip().split("\n")[-1][:120] if output else "unknown error"
                )
                send_notification(
                    "AI Guardian",
                    f"Version sync failed on '{target.name}': {first_line}",
                )
        except Exception:
            pass  # intentionally silent — daemon comm best-effort
        finally:
            self._upgrade_in_progress.discard(key)
            self._tray._dispatch_to_main(self._tray._refresh_menu)

    def _on_upgrade_single(self, _icon, _item):
        """Click handler for single-daemon Upgrade menu item."""
        if self._tray._targets:
            target = self._tray._targets[0]
            threading.Thread(
                target=self._do_upgrade_daemon,
                args=(target,),
                daemon=True,
                name="daemon-upgrade",
            ).start()

    def _mk_upgrade(self, slot):
        """Factory returning a click handler for multi-daemon Upgrade item."""

        def action(_, __):
            if slot < len(self._tray._targets):
                target = self._tray._targets[slot]
                threading.Thread(
                    target=self._do_upgrade_daemon,
                    args=(target,),
                    daemon=True,
                    name=f"daemon-upgrade-{slot}",
                ).start()

        return action

    # --- Self-upgrade (local installation → latest PyPI) ---

    def _is_self_upgrade_available(self):
        """Return True if PyPI has a newer version than the local install."""
        if self._self_upgrade_in_progress:
            return False
        if not self._pypi_latest:
            return False
        try:
            from ai_guardian import __version__

            if "-dev" in __version__ or "dev" in __version__.lower():
                return False
            from ai_guardian.update_checker import is_upgrade_available

            return is_upgrade_available(__version__, self._pypi_latest)
        except (ImportError, Exception):
            return False

    def _has_local_daemon(self):
        """Return whether this tray controls a local daemon installation."""
        return self._tray._standalone or any(
            target.runtime == "local" for target in self._tray._targets
        )

    def _get_unconfigured_ides(self):
        """Return installed IDEs that do not yet use ai-guardian hooks."""
        try:
            from ai_guardian.setup.hooks import IDESetup

            setup = IDESetup()
            unconfigured = []
            for ide_type in setup.list_detected_ides():
                configured, _ = setup.check_hooks_for_ide(ide_type)
                if not configured:
                    unconfigured.append(ide_type)
            return unconfigured
        except Exception as exc:
            logger.warning("Unable to check IDE setup status: %s", exc)
            return []

    def _check_ide_setup_notification(self):
        """Prompt local-daemon users to configure detected IDE integrations."""
        if not self._has_local_daemon() or self._ide_setup_prompt_in_progress:
            return

        unconfigured = self._get_unconfigured_ides()
        if not unconfigured:
            return

        from ai_guardian.setup.hooks import IDESetup
        from ai_guardian.tray.proactive_prompt import (
            ProactivePromptDialog,
            ProactivePromptState,
        )

        names = [IDESetup.IDE_CONFIGS[ide].get("name", ide) for ide in unconfigured]
        prompt_key = "ide_setup_" + "_".join(sorted(unconfigured))
        state = ProactivePromptState()
        if not state.available(prompt_key):
            return

        self._ide_setup_prompt_in_progress = True

        def _show_prompt():
            try:
                if len(names) == 1:
                    message = (
                        f"{names[0]} was detected but is not protected by AI Guardian.\n\n"
                        "Set up its security hooks now?"
                    )
                else:
                    message = (
                        "These IDEs were detected but are not protected by AI Guardian:\n"
                        + "\n".join(f"• {name}" for name in names)
                        + "\n\nSet up their security hooks now?"
                    )
                dialog = ProactivePromptDialog(
                    title="Set Up AI Guardian",
                    message=message,
                    action_label="Set Up Now",
                    dismiss_label="Don't Ask Again",
                    snooze_options=("1h", "6h", "1d", "1w"),
                )
                result = dialog.show(tray_safe=True)
                state.record(prompt_key, result)
                if result == "action":
                    from ai_guardian.setup import setup_hooks

                    for ide_type in unconfigured:
                        setup_hooks(ide_type=ide_type, interactive=False)
            except Exception as exc:
                logger.warning("IDE setup prompt failed: %s", exc)
            finally:
                self._ide_setup_prompt_in_progress = False

        threading.Thread(
            target=_show_prompt,
            daemon=True,
            name="ide-setup-prompt",
        ).start()

    def _self_upgrade_label(self):
        """Dynamic label for the self-upgrade menu item."""
        if self._self_upgrade_in_progress:
            return "Upgrading…"
        return f"Upgrade to v{self._pypi_latest}" if self._pypi_latest else "Upgrade"

    def _do_self_upgrade(self):
        """Run self-upgrade in a background thread, then re-exec tray."""
        import os
        import sys

        self._self_upgrade_in_progress = True
        self._tray._dispatch_to_main(self._tray._refresh_menu)

        try:
            from ai_guardian.tray.plugins import send_notification
            from ai_guardian.update_checker import perform_full_upgrade

            result = perform_full_upgrade(force=True, restart_daemon=True)

            if result.success:
                send_notification(
                    "AI Guardian Updated",
                    f"Upgraded to v{result.new_version or self._pypi_latest}. "
                    "Restarting tray…",
                )
                import time

                time.sleep(1)
                os.execv(sys.executable, [sys.executable] + sys.argv)
            elif result.permission_error:
                send_notification(
                    "Upgrade Failed — Permission Denied",
                    result.output,
                )
            else:
                send_notification(
                    "Upgrade Failed",
                    result.output[:200],
                )
        except Exception as exc:
            logger.warning("Self-upgrade failed: %s", exc)
        finally:
            self._self_upgrade_in_progress = False
            self._tray._dispatch_to_main(self._tray._refresh_menu)

    def _on_self_upgrade(self, _icon, _item):
        """Click handler for self-upgrade menu item."""
        threading.Thread(
            target=self._do_self_upgrade,
            daemon=True,
            name="self-upgrade",
        ).start()

    def _check_self_upgrade_notification(self):
        """Show a persistent upgrade prompt when a new version is detected."""
        if not self._has_local_daemon() or not self._is_self_upgrade_available():
            return
        if self._upgrade_prompt_in_progress:
            return

        try:
            from ai_guardian.config.loaders import _load_update_checking_config

            cfg = _load_update_checking_config()
            if isinstance(cfg, tuple):
                cfg = cfg[0]
            if not cfg.get("notify", True):
                return
        except Exception:
            pass

        from ai_guardian.tray.proactive_prompt import (
            ProactivePromptDialog,
            ProactivePromptState,
        )

        version = self._pypi_latest
        prompt_key = f"upgrade_v{version}"
        state = ProactivePromptState()
        if not state.available(prompt_key):
            return

        self._upgrade_notified_version = version
        self._upgrade_prompt_in_progress = True

        def _show_prompt():
            try:
                from ai_guardian import __version__ as current_version

                dialog = ProactivePromptDialog(
                    title="AI Guardian Update Available",
                    message=(
                        f"A new version is available: v{current_version} → v{version}\n\n"
                        "Upgrade now to get the latest security and reliability fixes."
                    ),
                    action_label="Upgrade Now",
                    dismiss_label="Skip This Version",
                    snooze_options=("1h", "6h", "1d", "1w"),
                )
                result = dialog.show()
                state.record(prompt_key, result)
                if result == "action":
                    self._do_self_upgrade()
            except Exception as exc:
                logger.warning("Upgrade prompt failed: %s", exc)
            finally:
                self._upgrade_prompt_in_progress = False

        threading.Thread(
            target=_show_prompt,
            daemon=True,
            name="upgrade-prompt",
        ).start()
