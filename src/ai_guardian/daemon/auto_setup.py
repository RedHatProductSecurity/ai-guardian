"""First-run auto-setup for tray shortcut, autostart, and tray launch."""

import logging
import os
import platform
import subprocess
import sys

logger = logging.getLogger(__name__)

_CI_ENV_VARS = (
    "CI",
    "GITHUB_ACTIONS",
    "JENKINS_URL",
    "GITLAB_CI",
    "CIRCLECI",
    "TRAVIS",
    "BUILDKITE",
    "CODEBUILD_BUILD_ID",
    "TF_BUILD",
)


def _is_ci_environment():
    """Return True if running in a CI/CD environment."""
    return any(os.environ.get(var) for var in _CI_ENV_VARS)


def _is_headless():
    """Return True if no graphical display is available."""
    if platform.system() == "Linux":
        return not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
    return False


def _is_auto_install_disabled(config):
    """Return True if auto_install is explicitly disabled in config."""
    if config is None:
        return False
    tray_config = config.get("daemon", {}).get("tray", {})
    auto_install = tray_config.get("auto_install", True)
    if isinstance(auto_install, bool):
        return not auto_install
    if isinstance(auto_install, dict):
        from ai_guardian.config.utils import is_feature_enabled

        return not is_feature_enabled(auto_install, default=True)
    return False


def _is_first_run():
    """Return True if tray shortcut and autostart are not yet installed."""
    from ai_guardian.daemon.desktop import get_desktop_integration, _UnsupportedDesktop

    desktop = get_desktop_integration()
    if isinstance(desktop, _UnsupportedDesktop):
        return False
    return not desktop.shortcut_exists() and not desktop.autostart_exists()


def _start_tray_background():
    """Launch tray process in the background."""
    from ai_guardian.daemon import get_executable_command

    cmd = get_executable_command() + ["tray", "start"]
    logger.debug("Starting tray: %s", " ".join(cmd))

    kwargs = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if platform.system() == "Windows":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen(cmd, **kwargs)
    return True


def notify_ide_setup_needed(runtime="local"):
    """Notify CLI users when detected IDE hooks are not configured."""
    if runtime != "local":
        return
    try:
        from ai_guardian.setup.hooks import IDESetup

        setup = IDESetup()
        unconfigured = [
            ide_type
            for ide_type in setup.list_detected_ides()
            if not setup.check_hooks_for_ide(ide_type, integrity=True)[0]
        ]
        if not unconfigured:
            return

        names = [setup.IDE_CONFIGS[ide].get("name", ide) for ide in unconfigured]
        if sys.stdin.isatty():
            logger.info("IDE setup needed: %s", ", ".join(names))
            print(
                "AI Guardian: detected "
                + ", ".join(names)
                + ". Run `ai-guardian setup` to enable protection.",
                file=sys.stderr,
            )
        else:
            logger.info(
                "IDE setup needed for %s; run `ai-guardian setup` to enable protection",
                ", ".join(names),
            )
    except Exception as exc:
        logger.warning("Unable to notify about IDE setup: %s", exc)


def auto_setup_tray():
    """Auto-install tray shortcut, autostart, and start tray on first run.

    Called from _ensure_daemon_started() in cli.py. Silent and non-blocking —
    never raises, never prints to stdout.
    """
    try:
        if _is_ci_environment():
            logger.debug("Auto-setup: skipped (CI environment)")
            return

        if _is_headless():
            logger.debug("Auto-setup: skipped (headless)")
            return

        config = None
        try:
            from ai_guardian.config.loaders import _load_config_file

            config, _ = _load_config_file()
        except Exception:
            pass  # intentionally silent — best-effort operation

        if _is_auto_install_disabled(config):
            logger.debug("Auto-setup: skipped (disabled in config)")
            return

        from ai_guardian.tray.app import is_tray_available

        if not is_tray_available():
            logger.debug("Auto-setup: skipped (tray not available)")
            return

        if not _is_first_run():
            return

        from ai_guardian.daemon.desktop import get_desktop_integration

        desktop = get_desktop_integration()

        if desktop.install_shortcut():
            logger.info("First run: installed tray desktop shortcut")
        if desktop.install_autostart():
            logger.info("First run: installed tray autostart")

        from ai_guardian.tray.app import _is_tray_running

        if not _is_tray_running():
            _start_tray_background()
            logger.info("First run: started tray in background")

    except Exception:
        logger.debug("Auto-setup: failed", exc_info=True)
