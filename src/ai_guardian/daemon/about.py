"""Shared About info for daemon, tray, and REST API."""

import platform
import socket
import sys

PROJECT_URL = "https://github.com/RedHatProductSecurity/ai-guardian"


def get_about_info() -> dict:
    """Gather about info for the current process."""
    try:
        from ai_guardian import __version__
    except ImportError:
        __version__ = "unknown"

    py_ver = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )

    system = platform.system()
    if system == "Darwin":
        mac_ver = platform.mac_ver()[0]
        plat_str = (
            f"macOS {mac_ver} {platform.machine()}"
            if mac_ver
            else f"macOS {platform.machine()}"
        )
    else:
        plat_str = f"{system} {platform.release()} {platform.machine()}"

    config_path = None
    try:
        from ai_guardian.config.utils import get_config_dir

        config_path = str(get_config_dir() / "ai-guardian.json")
    except Exception:
        pass  # intentionally silent — optional dependency

    scanners = []
    try:
        from ai_guardian.scanners.manager import ScannerManager
        from ai_guardian.config.loaders import _load_config_file

        cfg_for_scanners, _ = _load_config_file()
        sm = ScannerManager(config=cfg_for_scanners or {})
        for s in sm.list_configured():
            scanners.append(
                {"name": s.name, "version": s.version, "is_default": s.is_default}
            )
    except Exception:
        pass  # intentionally silent — optional dependency

    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"

    name = None
    try:
        from ai_guardian.config.loaders import _load_config_file

        cfg, _ = _load_config_file()
        if cfg:
            name = cfg.get("name")
    except Exception:
        pass  # intentionally silent — daemon comm best-effort

    return {
        "version": __version__,
        "name": name or "ai-guardian",
        "hostname": hostname,
        "python": py_ver,
        "platform": plat_str,
        "config_path": config_path,
        "scanners": scanners,
        "url": PROJECT_URL,
    }


def format_about_text(info: dict) -> str:
    """Format an about info dict into display text."""
    lines = [f"AI Guardian v{info.get('version', 'unknown')}"]

    name = info.get("name")
    hostname = info.get("hostname")
    if name and hostname and name != hostname:
        lines.append(f"Name: {name} ({hostname})")
    elif name:
        lines.append(f"Name: {name}")
    elif hostname:
        lines.append(f"Host: {hostname}")

    lines.append(f"Python: {info.get('python', 'unknown')}")
    lines.append(f"Platform: {info.get('platform', 'unknown')}")

    config_path = info.get("config_path")
    if config_path:
        lines.append(f"Config: {config_path}")

    scanners = info.get("scanners", [])
    if scanners:
        parts = []
        for s in scanners:
            label = f"{s['name']} {s['version']}"
            if s.get("is_default"):
                label += " (default)"
            parts.append(label)
        lines.append(f"Scanners: {', '.join(parts)}")
    else:
        lines.append("Scanners: none installed")

    lines.append("")
    lines.append(info.get("url", PROJECT_URL))

    return "\n".join(lines)
