"""Desktop shortcut and autostart integration for the ai-guardian tray."""

import logging
import os
import platform
import shlex
import shutil
import stat
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


def get_desktop_integration():
    """Return the platform-appropriate DesktopIntegration instance."""
    system = platform.system()
    if system == "Linux":
        return LinuxDesktop()
    if system == "Darwin":
        return MacOSDesktop()
    if system == "Windows":
        return WindowsDesktop()
    return _UnsupportedDesktop()


def _get_executable_command():
    """Resolve the command to launch ai-guardian tray."""
    from ai_guardian.daemon import get_executable_command

    return get_executable_command()


def _find_banner_icon():
    """Find the full-color ai-guardian banner image for desktop shortcuts."""
    import importlib.resources

    try:
        ref = importlib.resources.files("ai_guardian") / "images" / "ai-guardian.png"
        with importlib.resources.as_file(ref) as p:
            if p.exists():
                return str(p)
    except Exception:
        pass  # intentionally silent — resource loading best-effort

    src_dir = Path(__file__).resolve().parent.parent
    for candidate in [
        src_dir / "images" / "ai-guardian.png",
        src_dir.parent.parent / "images" / "ai-guardian.png",
    ]:
        if candidate.exists():
            return str(candidate)
    return None


def _prepare_icon(size=256):
    """Generate a square icon from the bundled banner and cache it in state dir.

    Returns the path to the cached icon, or None if the source icon is missing.
    """
    from ai_guardian.config.utils import get_state_dir

    state_dir = get_state_dir()
    cached = state_dir / f"icon-{size}.png"
    if cached.exists():
        return cached

    source_path = _find_banner_icon()
    if source_path is None:
        return None

    try:
        from PIL import Image

        img = Image.open(source_path).convert("RGBA")
        w, h = img.size
        shield_size = min(w, h)
        left = (w - shield_size) // 2
        img = img.crop((left, 0, left + shield_size, shield_size))
        img = img.resize((size, size), Image.LANCZOS)

        state_dir.mkdir(parents=True, exist_ok=True)
        img.save(str(cached), "PNG")
        return cached
    except Exception:
        logger.debug("Failed to prepare icon", exc_info=True)
        return None


def _prepare_ico():
    """Generate a .ico file for Windows from the cached PNG icon."""
    from ai_guardian.config.utils import get_state_dir

    state_dir = get_state_dir()
    ico_path = state_dir / "icon.ico"
    if ico_path.exists():
        return ico_path

    png_path = _prepare_icon(256)
    if png_path is None:
        return None

    try:
        from PIL import Image

        img = Image.open(str(png_path))
        state_dir.mkdir(parents=True, exist_ok=True)
        img.save(
            str(ico_path),
            format="ICO",
            sizes=[(256, 256), (48, 48), (32, 32), (16, 16)],
        )
        return ico_path
    except Exception:
        logger.debug("Failed to prepare .ico", exc_info=True)
        return None


class DesktopIntegration(ABC):
    @abstractmethod
    def shortcut_exists(self) -> bool: ...

    @abstractmethod
    def autostart_exists(self) -> bool: ...

    @abstractmethod
    def install_shortcut(self) -> bool: ...

    @abstractmethod
    def install_autostart(self) -> bool: ...

    @abstractmethod
    def uninstall_shortcut(self) -> bool: ...

    @abstractmethod
    def uninstall_autostart(self) -> bool: ...


class _UnsupportedDesktop(DesktopIntegration):
    def shortcut_exists(self):
        return False

    def autostart_exists(self):
        return False

    def install_shortcut(self):
        logger.warning("Desktop shortcuts not supported on %s", platform.system())
        return False

    def install_autostart(self):
        return False

    def uninstall_shortcut(self):
        return False

    def uninstall_autostart(self):
        return False


class LinuxDesktop(DesktopIntegration):
    SHORTCUT_DIR = Path("~/.local/share/applications").expanduser()
    AUTOSTART_DIR = Path("~/.config/autostart").expanduser()
    FILENAME = "ai-guardian-tray.desktop"

    @property
    def shortcut_path(self):
        return self.SHORTCUT_DIR / self.FILENAME

    @property
    def autostart_path(self):
        return self.AUTOSTART_DIR / self.FILENAME

    def shortcut_exists(self):
        return self.shortcut_path.exists()

    def autostart_exists(self):
        return self.autostart_path.exists()

    def _build_desktop_entry(self, autostart=False):
        cmd = _get_executable_command()
        exec_line = " ".join(cmd) + " tray start"
        icon_path = _prepare_icon()

        lines = [
            "[Desktop Entry]",
            "Type=Application",
            "Name=AI Guardian Tray",
            "Comment=Security tray for AI coding agents",
            f"Exec={exec_line}",
            "Terminal=false",
            "Categories=Development;Security;",
            "StartupNotify=false",
        ]
        if icon_path:
            lines.append(f"Icon={icon_path}")
        if autostart:
            lines.append("X-GNOME-Autostart-enabled=true")
        return "\n".join(lines) + "\n"

    def install_shortcut(self):
        try:
            self.SHORTCUT_DIR.mkdir(parents=True, exist_ok=True)
            self.shortcut_path.write_text(self._build_desktop_entry())
            self.shortcut_path.chmod(self.shortcut_path.stat().st_mode | stat.S_IXUSR)
            return True
        except OSError:
            logger.debug("Failed to install Linux shortcut", exc_info=True)
            return False

    def install_autostart(self):
        try:
            self.AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
            self.autostart_path.write_text(self._build_desktop_entry(autostart=True))
            self.autostart_path.chmod(self.autostart_path.stat().st_mode | stat.S_IXUSR)
            return True
        except OSError:
            logger.debug("Failed to install Linux autostart", exc_info=True)
            return False

    def uninstall_shortcut(self):
        if not self.shortcut_path.exists():
            return False
        try:
            self.shortcut_path.unlink()
            return True
        except OSError:
            return False

    def uninstall_autostart(self):
        if not self.autostart_path.exists():
            return False
        try:
            self.autostart_path.unlink()
            return True
        except OSError:
            return False


class MacOSDesktop(DesktopIntegration):
    APP_DIR = Path("~/Applications").expanduser()
    APP_NAME = "AI Guardian Tray.app"
    LAUNCHD_DIR = Path("~/Library/LaunchAgents").expanduser()
    PLIST_NAME = "com.itdove.ai-guardian.tray.plist"

    @property
    def app_path(self):
        return self.APP_DIR / self.APP_NAME

    @property
    def plist_path(self):
        return self.LAUNCHD_DIR / self.PLIST_NAME

    def shortcut_exists(self):
        return self.app_path.exists()

    def autostart_exists(self):
        return self.plist_path.exists()

    @staticmethod
    def _find_icns():
        """Find the ai-guardian.icns file for the .app bundle."""
        from ai_guardian.tray.plugins import _find_icon

        path = _find_icon("ai-guardian.icns")
        return path if path else None

    def install_shortcut(self):
        try:
            contents = self.app_path / "Contents"
            macos_dir = contents / "MacOS"
            resources_dir = contents / "Resources"

            macos_dir.mkdir(parents=True, exist_ok=True)
            resources_dir.mkdir(parents=True, exist_ok=True)

            script_path = macos_dir / "ai-guardian-tray"
            cmd = shlex.join(_get_executable_command() + ["tray", "start"])
            script_path.write_text(
                "#!/bin/sh\n"
                "for d in /opt/homebrew/bin /opt/homebrew/sbin "
                '/usr/local/bin /usr/local/sbin "$HOME/.local/bin"; do\n'
                '    case ":${PATH:-}:" in *":$d:"*) ;; '
                '*) PATH="$d${PATH:+:$PATH}" ;; esac\n'
                "done\n"
                "export PATH\n"
                f'exec {cmd} "$@"\n'
            )
            script_path.chmod(
                script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )

            icns_path = self._find_icns()
            icon_file = None
            if icns_path:
                shutil.copy2(str(icns_path), str(resources_dir / "ai-guardian.icns"))
                icon_file = "ai-guardian.icns"
            else:
                fallback = _prepare_icon()
                if fallback:
                    shutil.copy2(str(fallback), str(resources_dir / "icon.png"))
                    icon_file = "icon.png"

            import plistlib

            info_plist = {
                "CFBundleName": "AI Guardian Tray",
                "CFBundleDisplayName": "AI Guardian Tray",
                "CFBundleIdentifier": "com.itdove.ai-guardian.tray",
                "CFBundleVersion": "1.0",
                "CFBundlePackageType": "APPL",
                "CFBundleExecutable": "ai-guardian-tray",
                "LSUIElement": True,
                "NSPrincipalClass": "NSApplication",
            }
            if icon_file:
                info_plist["CFBundleIconFile"] = icon_file

            with open(contents / "Info.plist", "wb") as f:
                plistlib.dump(info_plist, f)

            return True
        except OSError:
            logger.debug("Failed to install macOS app bundle", exc_info=True)
            return False

    def install_autostart(self):
        try:
            self.LAUNCHD_DIR.mkdir(parents=True, exist_ok=True)

            cmd = _get_executable_command() + ["tray", "start"]

            import plistlib

            augmented_path = os.pathsep.join(
                filter(
                    None,
                    [
                        "/opt/homebrew/bin",
                        "/opt/homebrew/sbin",
                        "/usr/local/bin",
                        "/usr/local/sbin",
                        str(Path.home() / ".local" / "bin"),
                        os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
                    ],
                )
            )
            plist_data = {
                "Label": "com.itdove.ai-guardian.tray",
                "ProgramArguments": cmd,
                "RunAtLoad": True,
                "KeepAlive": False,
                "EnvironmentVariables": {"PATH": augmented_path},
            }

            with open(self.plist_path, "wb") as f:
                plistlib.dump(plist_data, f)

            return True
        except OSError:
            logger.debug("Failed to install macOS autostart", exc_info=True)
            return False

    def uninstall_shortcut(self):
        if not self.app_path.exists():
            return False
        try:
            shutil.rmtree(self.app_path)
            return True
        except OSError:
            return False

    _OLD_PLIST_NAME = "com.ai-guardian.tray.plist"

    def uninstall_autostart(self):
        removed = False
        for name in (self.PLIST_NAME, self._OLD_PLIST_NAME):
            path = self.LAUNCHD_DIR / name
            if not path.exists():
                continue
            try:
                subprocess.run(
                    ["launchctl", "unload", str(path)],
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass  # intentionally silent — best-effort operation
            try:
                path.unlink()
                removed = True
            except OSError:
                pass  # intentionally silent — subprocess may fail
        return removed


class WindowsDesktop(DesktopIntegration):
    LNK_NAME = "AI Guardian Tray.lnk"

    @property
    def _start_menu_dir(self):
        appdata = os.environ.get("APPDATA", "")
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"

    @property
    def _startup_dir(self):
        appdata = os.environ.get("APPDATA", "")
        return (
            Path(appdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )

    @property
    def shortcut_path(self):
        return self._start_menu_dir / self.LNK_NAME

    @property
    def autostart_path(self):
        return self._startup_dir / self.LNK_NAME

    def shortcut_exists(self):
        return self.shortcut_path.exists()

    def autostart_exists(self):
        return self.autostart_path.exists()

    def _create_lnk(self, lnk_path):
        cmd = _get_executable_command()
        ico_path = _prepare_ico()

        if len(cmd) == 1:
            target = cmd[0]
            arguments = "tray start"
        else:
            pythonw = Path(cmd[0]).with_name("pythonw.exe")
            target = str(pythonw) if pythonw.is_file() else cmd[0]
            arguments = "-m ai_guardian tray start"

        lnk_path.parent.mkdir(parents=True, exist_ok=True)

        def _ps_escape(s):
            return str(s).replace("'", "''")

        ps_lines = [
            "$WshShell = New-Object -ComObject WScript.Shell",
            f"$Shortcut = $WshShell.CreateShortcut('{_ps_escape(lnk_path)}')",
            f"$Shortcut.TargetPath = '{_ps_escape(target)}'",
            f"$Shortcut.Arguments = '{_ps_escape(arguments)}'",
            "$Shortcut.WindowStyle = 7",
        ]
        if ico_path:
            ps_lines.append(f"$Shortcut.IconLocation = '{_ps_escape(ico_path)}'")
        ps_lines.append("$Shortcut.Save()")

        ps_script = "; ".join(ps_lines)
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                timeout=10,
            )
            return lnk_path.exists()
        except Exception:
            logger.debug("Failed to create Windows shortcut", exc_info=True)
            return False

    def install_shortcut(self):
        return self._create_lnk(self.shortcut_path)

    def install_autostart(self):
        return self._create_lnk(self.autostart_path)

    def uninstall_shortcut(self):
        if not self.shortcut_path.exists():
            return False
        try:
            self.shortcut_path.unlink()
            return True
        except OSError:
            return False

    def uninstall_autostart(self):
        if not self.autostart_path.exists():
            return False
        try:
            self.autostart_path.unlink()
            return True
        except OSError:
            return False
