"""Goose v1.59 host paths shared by setup, health, and protection inventory.

GOOSE_PATH_ROOT is an absolute process root, not a config directory. Goose
ignores relative values. Plugins and plugin settings do not follow XDG config.
"""

import os
import sys
from pathlib import Path
from typing import Optional

GOOSE_PLUGIN_NAME = "ai-guardian-goose"


def goose_path_root() -> Optional[Path]:
    value = os.environ.get("GOOSE_PATH_ROOT", "")
    return Path(value) if value and Path(value).is_absolute() else None


def goose_config_dir() -> Path:
    root = goose_path_root()
    if root is not None:
        return root / "config"
    if sys.platform == "win32":
        return (
            Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
            / "Block/goose/config"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Block/goose"
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".config"
    return base / "goose"


def goose_plugins_dir() -> Path:
    return (goose_path_root() or Path.home()) / ".agents/plugins"


def goose_hook_path(scope: str = "user", project_dir: Optional[str] = None) -> Path:
    if scope == "project":
        # Construct only: callers apply their own canonical path guards before
        # filesystem access. Do not resolve an untrusted hook working directory.
        project = os.path.join(os.getcwd(), os.path.expanduser(project_dir or "."))
        base = Path(project) / ".agents/plugins"
    elif scope in ("user", "auto"):
        base = goose_plugins_dir()
    else:
        raise ValueError("Goose scope must be 'user', 'project', or 'auto'")
    return base / GOOSE_PLUGIN_NAME / "hooks/hooks.json"


def goose_user_settings_path() -> Path:
    return (goose_path_root() or Path.home()) / ".config/goose/settings.json"
