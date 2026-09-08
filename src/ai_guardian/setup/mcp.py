"""MCP server configuration for ai-guardian setup."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from ai_guardian.setup.utils import (
    _resolve_binary_path,
    _resolve_opencode_config,
    _strip_jsonc_comments,
)

logger = logging.getLogger(__name__)

# MCP config locations per IDE
_MCP_IDE_CONFIGS = {
    "claude": {
        "config_file": "~/.claude.json",
        "config_key": "mcpServers",
        "skill_dir": ".claude/skills",
    },
    "cursor": {
        "config_file": "~/.cursor/mcp.json",
        "config_key": "mcpServers",
        "skill_dir": ".cursor/skills",
    },
    "copilot": {
        "config_key": "mcpServers",
        "skill_dir": ".github/skills",
    },
    "codex": {
        "config_file": "~/.codex/config.toml",
        "config_key": "mcp_servers",
        "config_format": "toml",
        "skill_dir": ".codex/skills",
    },
    "windsurf": {
        "config_file": "~/.windsurf/mcp.json",
        "config_key": "mcpServers",
        "skill_dir": ".windsurf/skills",
    },
    "gemini": {
        "config_file": "~/.gemini/settings.json",
        "config_key": "mcpServers",
        "skill_dir": ".gemini/skills",
    },
    "cline": {
        "config_file": "~/.cline/mcp_settings.json",
        "config_key": "mcpServers",
        "skill_dir": ".clinerules/skills",
    },
    "zoocode": {
        "config_file": "~/.cline/mcp_settings.json",
        "config_key": "mcpServers",
        "skill_dir": ".clinerules/skills",
    },
    "augment": {
        "config_file": "~/.augment/settings.json",
        "config_key": "mcpServers",
        "skill_dir": ".augment/skills",
    },
    "kiro": {
        "config_file": "~/.kiro/settings.json",
        "config_key": "mcpServers",
        "skill_dir": ".kiro/skills",
    },
    "junie": {
        "config_file": "~/.junie/mcp.json",
        "config_key": "mcpServers",
        "skill_dir": ".junie/skills",
    },
    "aiderdesk": {
        "config_file": "~/.aider-desk/settings.json",
        "config_key": "mcpServers",
        "skill_dir": ".aider-desk/skills",
    },
    "openclaw": {
        "config_file": "~/.openclaw/settings.json",
        "config_key": "mcpServers",
        "skill_dir": ".openclaw/skills",
    },
    "opencode": {
        "config_file": "~/.config/opencode/opencode.jsonc",
        "config_key": "mcp",
        "skill_dir": ".opencode/skills",
    },
    "crush": {
        "config_file": ".crush.json",
        "config_key": "mcp",
        "skill_dir": ".crush/skills",
    },
}

_MCP_SERVER_ENTRY = {
    "args": ["mcp-server"],
}

_CODEX_MCP_SECTION = "mcp_servers.ai-guardian"
_CODEX_LEGACY_MCP_FILENAME = "codex.json"
_TOML_TABLE_HEADER = re.compile(
    r"^\s*(?P<opening>\[\[?)(?P<name>[^\]]+)(?P<closing>\]\]?)\s*(?:#.*)?$"
)
_TOML_INLINE_MCP_SERVERS = re.compile(r"^\s*mcp_servers\s*=", re.MULTILINE)


def get_codex_mcp_config_path() -> Path:
    """Return Codex's global MCP configuration path.

    Codex uses ``~/.codex/config.toml`` by default and relocates the complete
    user configuration directory when ``CODEX_HOME`` is set.  Project-local
    ``.codex/config.toml`` files are intentionally not returned here: AI
    Guardian installs its MCP server in the global user layer.
    """
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "config.toml"
    return Path.home() / ".codex" / "config.toml"


def get_mcp_config_path(ide_type: str) -> Optional[Path]:
    """Return the effective MCP configuration path for an IDE."""
    if ide_type == "codex":
        return get_codex_mcp_config_path()

    mcp_ide = _MCP_IDE_CONFIGS.get(ide_type)
    if not mcp_ide:
        return None

    config_file = mcp_ide.get("config_file", "")
    if not config_file:
        return None
    if ide_type == "opencode":
        return _resolve_opencode_config()
    return Path(config_file).expanduser()


def _load_toml_text(text: str) -> Dict:
    """Parse TOML using the stdlib parser or the Python 3.9 backport."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore

    return tomllib.loads(text)


def _dump_toml(data: Dict) -> str:
    """Serialize TOML using the project-supported writer dependency."""
    try:
        import tomli_w
    except ImportError as exc:
        raise RuntimeError("TOML writer is unavailable") from exc
    return tomli_w.dumps(data)


def is_codex_mcp_configured(config_path: Optional[Path] = None) -> bool:
    """Return whether the global Codex config contains AI Guardian's server."""
    path = config_path or get_codex_mcp_config_path()
    if not path.is_file():
        return False

    try:
        data = _load_toml_text(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Unable to read Codex MCP config %s: %s", path, exc)
        return False

    mcp_servers = data.get("mcp_servers", {})
    return isinstance(mcp_servers, dict) and "ai-guardian" in mcp_servers


def _toml_table_name(line: str) -> Optional[str]:
    """Return a normalized table name for a TOML table-header line."""
    match = _TOML_TABLE_HEADER.match(line)
    if not match:
        return None
    if match.group("opening") != "[" or match.group("closing") != "]":
        return None

    parts = []
    for part in match.group("name").strip().split("."):
        part = part.strip()
        if len(part) >= 2 and part[0] == part[-1] == '"':
            part = part[1:-1]
        if part:
            parts.append(part)
    return ".".join(parts) or None


def _is_codex_mcp_table(name: Optional[str]) -> bool:
    """Return whether a TOML table is AI Guardian's Codex MCP table."""
    return bool(
        name
        and (name == _CODEX_MCP_SECTION or name.startswith(f"{_CODEX_MCP_SECTION}."))
    )


def _remove_codex_mcp_tables(raw: str) -> Tuple[str, bool]:
    """Remove only AI Guardian's Codex MCP table and nested tables."""
    kept = []
    removing = False
    found = False

    for line in raw.splitlines(keepends=True):
        table_name = _toml_table_name(line)
        if table_name is not None:
            if _is_codex_mcp_table(table_name):
                removing = True
                found = True
                continue
            removing = False
        if not removing:
            kept.append(line)

    return "".join(kept), found


def _codex_mcp_entry(binary_path: str) -> Dict:
    """Build the stdio MCP entry used by Codex."""
    return {"command": binary_path, "args": ["mcp-server"]}


def _legacy_codex_mcp_path() -> Path:
    """Return the pre-85ec72f project-root Codex MCP path."""
    return Path.cwd() / _CODEX_LEGACY_MCP_FILENAME


def _clean_legacy_codex_mcp_entry(
    target_path: Optional[Path] = None, dry_run: bool = False
) -> bool:
    """Remove only the stale AI Guardian entry from project-root ``codex.json``.

    The old installer wrote a JSON ``mcpServers`` entry relative to the
    current directory.  If that file contains other settings or MCP servers,
    they remain untouched.  An empty file is retained as ``{}`` for the same
    conservative behavior used by the other JSON MCP integrations.
    """
    legacy_path = _legacy_codex_mcp_path()
    if not legacy_path.is_file():
        return False

    try:
        config = json.loads(legacy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Unable to read stale Codex MCP config %s: %s", legacy_path, exc)
        return False

    mcp_servers = config.get("mcpServers") if isinstance(config, dict) else None
    if not isinstance(mcp_servers, dict) or "ai-guardian" not in mcp_servers:
        return False

    if dry_run:
        if target_path is None:
            print(f"  MCP: Would remove stale Codex MCP entry from {legacy_path}")
        else:
            print(
                f"  MCP: Would migrate stale Codex MCP entry from {legacy_path} "
                f"to {target_path}"
            )
        return True

    del mcp_servers["ai-guardian"]
    if not mcp_servers:
        config.pop("mcpServers", None)

    try:
        legacy_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "Unable to clean stale Codex MCP config %s: %s", legacy_path, exc
        )
        return False

    if target_path is None:
        print(f"  MCP: Removed stale Codex MCP entry from {legacy_path}")
    else:
        print(
            f"  MCP: Migrated stale Codex MCP entry from {legacy_path} "
            f"to {target_path}"
        )
    return True


def _handle_mcp_setup(
    setup,
    ide_type: str,
    no_mcp: bool = False,
    dry_run: bool = False,
) -> None:
    """Install or remove MCP server config for an IDE."""
    if no_mcp:
        _remove_mcp_config(setup, ide_type, dry_run)
    else:
        _install_mcp_config(setup, ide_type, dry_run)


def _install_mcp_config(setup, ide_type: str, dry_run: bool = False) -> None:
    """Add MCP server entry to IDE config and enable in ai-guardian config."""
    mcp_ide = _MCP_IDE_CONFIGS.get(ide_type)
    if not mcp_ide:
        return

    config_path = get_mcp_config_path(ide_type)
    if config_path is None:
        return

    if ide_type == "codex":
        _install_codex_mcp_config(config_path, dry_run=dry_run)
        return

    if dry_run:
        print(f"  MCP: Would add ai-guardian MCP server to {config_path}")
        return

    # Read or create config file
    config = {}
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                raw = f.read()
            if config_path.suffix == ".jsonc":
                raw = _strip_jsonc_comments(raw)
            if raw.strip():
                config = json.loads(raw)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read config: %s", e)

    # Add MCP server entry with absolute path
    abs_path = _resolve_binary_path()
    key = mcp_ide["config_key"]

    if ide_type == "opencode":
        mcp_entry = {
            "type": "local",
            "command": [abs_path, "mcp-server"],
            "enabled": True,
        }
    else:
        mcp_entry = dict(_MCP_SERVER_ENTRY)
        mcp_entry["command"] = abs_path

    if key not in config:
        config[key] = {}
    config[key]["ai-guardian"] = mcp_entry

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"  MCP: Added ai-guardian MCP server to {config_path}")

    # Warn if MCP entry exists in settings.json (hooks file) for Claude
    if ide_type == "claude":
        settings_path = Path("~/.claude/settings.json").expanduser()
        try:
            if settings_path.exists():
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                if "ai-guardian" in settings.get("mcpServers", {}):
                    print(
                        "  MCP: Warning: ai-guardian MCP entry found in "
                        f"{settings_path} (hooks file).\n"
                        "  MCP servers should be in ~/.claude.json. "
                        "Remove the entry from settings.json to avoid conflicts."
                    )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read config: %s", e)


def _install_codex_mcp_config(config_path: Path, dry_run: bool = False) -> None:
    """Register AI Guardian in Codex's global TOML MCP configuration."""
    if dry_run:
        print(f"  MCP: Would add ai-guardian MCP server to {config_path}")
        _clean_legacy_codex_mcp_entry(target_path=config_path, dry_run=True)
        return

    raw = ""
    if config_path.exists():
        try:
            raw = config_path.read_text(encoding="utf-8")
            data = _load_toml_text(raw) if raw.strip() else {}
        except (OSError, ValueError) as exc:
            logger.warning("Failed to read Codex config %s: %s", config_path, exc)
            return
    else:
        data = {}

    mcp_servers = data.get("mcp_servers")
    if mcp_servers is not None and not isinstance(mcp_servers, dict):
        logger.warning(
            "Cannot add AI Guardian to Codex config %s: mcp_servers is not a table",
            config_path,
        )
        return

    entry = _codex_mcp_entry(_resolve_binary_path())
    try:
        if _TOML_INLINE_MCP_SERVERS.search(raw):
            updated_data = dict(data)
            updated_mcp_servers = dict(mcp_servers or {})
            updated_mcp_servers["ai-guardian"] = entry
            updated_data["mcp_servers"] = updated_mcp_servers
            updated = _dump_toml(updated_data)
        else:
            without_existing, _ = _remove_codex_mcp_tables(raw)
            section = _dump_toml({"mcp_servers": {"ai-guardian": entry}})
            prefix = without_existing.rstrip("\n")
            updated = section if not prefix else f"{prefix}\n\n{section}"
    except (RuntimeError, ValueError, TypeError) as exc:
        logger.warning("Failed to build Codex MCP config %s: %s", config_path, exc)
        return

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if updated != raw:
            config_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to write Codex MCP config %s: %s", config_path, exc)
        return

    print(f"  MCP: Added ai-guardian MCP server to {config_path}")
    _clean_legacy_codex_mcp_entry(target_path=config_path)


def _remove_mcp_config(setup, ide_type: str, dry_run: bool = False) -> None:
    """Remove MCP server entry from IDE config."""
    mcp_ide = _MCP_IDE_CONFIGS.get(ide_type)
    if not mcp_ide:
        return

    config_path = get_mcp_config_path(ide_type)
    if config_path is None:
        return

    if ide_type == "codex":
        _remove_codex_mcp_config(config_path, dry_run=dry_run)
        return

    if dry_run:
        print(f"  MCP: Would remove ai-guardian MCP server from {config_path}")
        return

    if not config_path.exists():
        print("  MCP: No config file found, nothing to remove")
        return

    try:
        with open(config_path, "r") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    key = mcp_ide["config_key"]
    if key in config and "ai-guardian" in config[key]:
        del config[key]["ai-guardian"]
        if not config[key]:
            del config[key]
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
        print(f"  MCP: Removed ai-guardian MCP server from {config_path}")
    else:
        print("  MCP: ai-guardian MCP server not found in config")


def _remove_codex_mcp_config(config_path: Path, dry_run: bool = False) -> None:
    """Remove AI Guardian from Codex's global TOML MCP configuration."""
    if dry_run:
        print(f"  MCP: Would remove ai-guardian MCP server from {config_path}")
        _clean_legacy_codex_mcp_entry(dry_run=True)
        return

    if not config_path.exists():
        print("  MCP: No config file found, nothing to remove")
        _clean_legacy_codex_mcp_entry()
        return

    try:
        raw = config_path.read_text(encoding="utf-8")
        data = _load_toml_text(raw) if raw.strip() else {}
    except (OSError, ValueError) as exc:
        logger.warning("Failed to read Codex config %s: %s", config_path, exc)
        return

    mcp_servers = data.get("mcp_servers")
    if mcp_servers is not None and not isinstance(mcp_servers, dict):
        logger.warning(
            "Cannot remove AI Guardian from Codex config %s: "
            "mcp_servers is not a table",
            config_path,
        )
        return

    found = isinstance(mcp_servers, dict) and "ai-guardian" in mcp_servers
    try:
        if _TOML_INLINE_MCP_SERVERS.search(raw):
            if found:
                updated_data = dict(data)
                updated_mcp_servers = dict(mcp_servers)
                updated_mcp_servers.pop("ai-guardian", None)
                updated_data["mcp_servers"] = updated_mcp_servers
                updated = _dump_toml(updated_data)
            else:
                updated = raw
        else:
            updated, table_found = _remove_codex_mcp_tables(raw)
            found = found or table_found
    except (RuntimeError, ValueError, TypeError) as exc:
        logger.warning("Failed to update Codex MCP config %s: %s", config_path, exc)
        return

    if found and updated != raw:
        try:
            config_path.write_text(updated, encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write Codex MCP config %s: %s", config_path, exc)
            return
        print(f"  MCP: Removed ai-guardian MCP server from {config_path}")
    else:
        print("  MCP: ai-guardian MCP server not found in config")

    _clean_legacy_codex_mcp_entry()
