"""Canonical path resolution for supported IDE and agent integrations.

The integrations expose different environment-variable contracts.  Keeping the
contracts here prevents setup, MCP registration, auditing, and session helpers
from each implementing a slightly different interpretation of an IDE home.
Project-local paths are deliberately handled by their callers and never pass
through these user-home resolvers.
"""

import os
from pathlib import Path
from typing import Dict, Optional, Tuple

# Values are ordered by precedence.  The first non-empty variable wins.
IDE_HOME_ENV_VARS: Dict[str, Tuple[str, ...]] = {
    "claude": ("CLAUDE_CONFIG_DIR",),
    "codex": ("CODEX_HOME",),
    "cursor": ("CURSOR_CONFIG_DIR",),
    "copilot": ("COPILOT_HOME",),
    "gemini": ("GEMINI_CLI_HOME",),
    "cline": ("CLINE_DATA_DIR",),
    "zoocode": ("CLINE_DATA_DIR",),
    "kiro": ("KIRO_HOME",),
    "junie": ("JUNIE_HOME",),
    "aiderdesk": ("AIDER_DESK_DIR", "AIDER_DESK_HOME_DIR"),
    "openclaw": ("OPENCLAW_STATE_DIR", "OPENCLAW_HOME"),
    "opencode": ("OPENCODE_CONFIG_DIR",),
}

# These variables name a complete configuration file rather than a home
# directory.  They take precedence over the corresponding home directory.
IDE_CONFIG_FILE_ENV_VARS: Dict[str, str] = {
    "openclaw": "OPENCLAW_CONFIG_PATH",
    "opencode": "OPENCODE_CONFIG",
    "crush": "CRUSH_GLOBAL_CONFIG",
}

# Public alias for documentation and callers that want to enumerate the
# supported relocation variables without depending on a private registry.
SUPPORTED_IDE_HOME_ENV_VARS = IDE_HOME_ENV_VARS


def _expand_path(value: str) -> Path:
    """Expand environment variables and ``~`` in an environment path."""
    return Path(os.path.expandvars(value)).expanduser()


def _first_env_path(ide_type: str) -> Tuple[Optional[str], Optional[Path]]:
    """Return the first configured home variable and its expanded path."""
    for env_var in IDE_HOME_ENV_VARS.get(ide_type, ()):
        value = os.environ.get(env_var)
        if value:
            return env_var, _expand_path(value)
    return None, None


def get_active_ide_home_env_var(ide_type: str) -> Optional[str]:
    """Return the environment variable currently selecting an IDE home."""
    env_var, _ = _first_env_path(ide_type)
    return env_var


def get_ide_home(ide_type: str) -> Optional[Path]:
    """Return an IDE's effective relocated user configuration root.

    Some products expose a process root whose configuration lives in a child
    directory.  ``GEMINI_CLI_HOME`` is the root containing ``.gemini`` and
    ``OPENCLAW_HOME`` is the root containing ``.openclaw``; the returned path is
    the effective configuration root used by the rest of this module.
    """
    env_var, path = _first_env_path(ide_type)
    if path is None:
        return None

    if ide_type == "gemini":
        path = path / ".gemini"
    elif ide_type == "openclaw" and env_var == "OPENCLAW_HOME":
        path = path / ".openclaw"
    return path


def get_explicit_ide_config_path(ide_type: str) -> Optional[Path]:
    """Return an explicitly configured IDE config file, when supported."""
    env_var = IDE_CONFIG_FILE_ENV_VARS.get(ide_type)
    if not env_var:
        return None
    value = os.environ.get(env_var)
    return _expand_path(value) if value else None


def resolve_ide_config_path(
    ide_type: str,
    default_path: Optional[str],
    *,
    filename: Optional[str] = None,
    env_subdir: Tuple[str, ...] = (),
    allow_env: bool = True,
) -> Optional[str]:
    """Resolve a user-level setup path while preserving default spellings.

    ``default_path`` is returned unchanged when no relocation variable is set;
    this preserves the existing CLI/API representation (including ``~``) while
    still resolving custom values to a concrete path.  Callers handling
    project scope should pass ``allow_env=False``.
    """
    if default_path is None:
        return None

    if allow_env:
        explicit_config = get_explicit_ide_config_path(ide_type)
        if ide_type == "opencode" and explicit_config is not None and env_subdir:
            # An explicit OpenCode config file relocates the adjacent plugin
            # directory with it.  OPENCODE_CONFIG_DIR is handled as a home
            # directory below, while OPENCODE_CONFIG remains the stronger
            # complete-file override.
            return str(explicit_config.parent.joinpath(*env_subdir))
        home = get_ide_home(ide_type)
        if home is not None:
            path = home.joinpath(*env_subdir)
            if filename:
                path /= filename
            return str(path)
    return default_path


def resolve_ide_mcp_path(ide_type: str, default_path: Optional[str]) -> Optional[Path]:
    """Resolve the global MCP configuration path for an IDE.

    Existing no-environment defaults are intentionally retained.  Environment
    variables only select the corresponding IDE's user layer; project layers
    are selected by ``setup.mcp.get_mcp_config_path`` before calling here.
    """
    if ide_type == "opencode":
        return resolve_opencode_config()

    if ide_type == "copilot":
        # Copilot CLI does not expose a default global MCP file in the same
        # way as the other integrations, but COPILOT_HOME owns its optional
        # user-level mcp-config.json when explicitly configured.
        home = get_ide_home(ide_type)
        return home / "mcp-config.json" if home is not None else None

    if default_path is None:
        return None

    if ide_type == "crush":
        explicit = get_explicit_ide_config_path(ide_type)
        if explicit is not None:
            return explicit

    if ide_type == "openclaw":
        explicit = get_explicit_ide_config_path(ide_type)
        if explicit is not None:
            return explicit

    home = get_ide_home(ide_type)
    if home is None:
        return Path(default_path).expanduser()

    if ide_type == "claude":
        # Claude's global MCP/state file is adjacent to settings.json inside
        # CLAUDE_CONFIG_DIR when that variable is set.
        return home / ".claude.json"
    if ide_type == "cursor":
        return home / "mcp.json"
    if ide_type in ("codex",):
        return home / "config.toml"
    if ide_type == "gemini":
        return home / "settings.json"
    if ide_type in ("cline", "zoocode"):
        return home / "mcp_settings.json"
    if ide_type == "kiro":
        return home / "settings" / "mcp.json"
    if ide_type == "junie":
        return home / "mcp.json"
    if ide_type == "aiderdesk":
        return home / "settings.json"
    if ide_type == "openclaw":
        return home / "settings.json"

    return Path(default_path).expanduser()


def resolve_opencode_config() -> Path:
    """Resolve OpenCode's active config file.

    An explicit ``OPENCODE_CONFIG`` file wins, followed by an existing JSON
    file in ``OPENCODE_CONFIG_DIR`` (or the historical default directory), and
    finally a new JSONC path in that directory.
    """
    explicit = get_explicit_ide_config_path("opencode")
    if explicit is not None:
        return explicit

    base = get_ide_home("opencode") or Path("~/.config/opencode").expanduser()
    for name in ("opencode.json", "opencode.jsonc"):
        candidate = base / name
        if candidate.exists():
            return candidate
    return base / "opencode.jsonc"


def resolve_ide_session_dir(
    ide_type: str, default_path: str, *, subdir: Tuple[str, ...] = ()
) -> Path:
    """Resolve a session directory for an IDE home variable."""
    home = get_ide_home(ide_type)
    if home is not None:
        return home.joinpath(*subdir)
    return Path(os.path.expandvars(default_path)).expanduser()


def resolve_ide_skill_dir(ide_type: str, default_path: str) -> Path:
    """Resolve a user's skill directory while keeping project paths separate."""
    home = get_ide_home(ide_type)
    if home is not None:
        return home / "skills"
    return Path(os.path.expandvars(default_path)).expanduser()
