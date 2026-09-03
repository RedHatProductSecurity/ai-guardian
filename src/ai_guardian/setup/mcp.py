"""MCP server configuration for ai-guardian setup."""

import json
import logging
from pathlib import Path

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
        "config_file": "~/.codex/codex.json",
        "config_key": "mcpServers",
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
    "antigravity": {
        "config_file": "~/.gemini/config/mcp_config.json",
        "config_key": "mcpServers",
        "skill_dir": ".agents/skills",
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

    config_file = mcp_ide.get("config_file", "")
    if not config_file:
        return

    if ide_type == "opencode":
        config_path = _resolve_opencode_config()
    else:
        config_path = Path(config_file).expanduser()

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


def _remove_mcp_config(setup, ide_type: str, dry_run: bool = False) -> None:
    """Remove MCP server entry from IDE config."""
    mcp_ide = _MCP_IDE_CONFIGS.get(ide_type)
    if not mcp_ide:
        return

    config_file = mcp_ide.get("config_file", "")
    if not config_file:
        return

    config_path = Path(config_file).expanduser()

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
