"""MCP server configuration for ai-guardian setup."""

import json
import logging
import os
import plistlib
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from xml.parsers.expat import ExpatError

from ai_guardian import __version__
from ai_guardian.opencode_support import detect_opencode_runtime

from ai_guardian.ide_paths import (
    ensure_project_path_no_symlink,
    resolve_ide_config_path,
    resolve_ide_mcp_path,
    resolve_opencode_config_layers,
    write_project_text_no_symlink,
)
from ai_guardian.setup.utils import (
    _create_config_backup,
    _load_cli_config,
    _resolve_binary_path,
    _resolve_opencode_config,
    _strip_jsonc_comments,
)

logger = logging.getLogger(__name__)


def _mcp_schema_error(
    config: Dict[str, Any], config_path: Path, config_key: str
) -> Optional[str]:
    """Return a diagnostic when an MCP container has the wrong shape."""
    if config_key not in config:
        return None
    if isinstance(config[config_key], dict):
        return None
    format_name = {
        ".jsonc": "JSONC",
        ".toml": "TOML",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".plist": "property list",
    }.get(config_path.suffix.lower(), "JSON")
    return (
        f"Invalid {format_name} schema in {config_path}: "
        f"'{config_key}' must be an object/mapping"
    )


def _local_command_diagnostic(command: Any) -> Optional[str]:
    """Reject a Windows compound executable serialized as one argv element."""
    if not isinstance(command, list) or not command:
        return "local servers require a non-empty string command array"
    if any(not isinstance(part, str) or not part.strip() for part in command):
        return "local servers require a non-empty string command array"
    if command[0].rstrip().endswith(" -m ai_guardian"):
        return (
            "local MCP command must separate the executable from '-m ai_guardian' "
            "arguments"
        )
    return None


def _load_mcp_config(
    config_path: Path, mcp_config: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load an MCP file and validate its configured server container."""
    config, error = _load_cli_config(
        config_path, format_name=mcp_config.get("config_format")
    )
    if error or config is None:
        return config, error
    return config, _mcp_schema_error(config, config_path, mcp_config["config_key"])


def _opencode_mcp_generation() -> str:
    """Return the active OpenCode MCP config generation, defaulting to V1."""
    generation = detect_opencode_runtime().get("generation")
    return generation if generation in {"v1", "v2"} else "v1"


def _plugin_mcp_schema_error(
    config: Dict[str, Any], config_path: Path, generation: str
) -> Optional[str]:
    """Validate the direct or versioned MCP container used by plugin CLIs."""
    error = _mcp_schema_error(config, config_path, "mcp")
    if error:
        return error

    mcp = config.get("mcp")
    if not isinstance(mcp, dict):
        return None

    key = "mcp.servers" if generation == "v2" else "mcp"
    container = mcp.get("servers") if generation == "v2" else mcp
    format_name = {
        ".jsonc": "JSONC",
        ".toml": "TOML",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".plist": "property list",
    }.get(config_path.suffix.lower(), "JSON")
    if generation == "v2" and "servers" in mcp and not isinstance(container, dict):
        return (
            f"Invalid {format_name} schema in {config_path}: "
            f"'{key}' must be an object/mapping"
        )
    if isinstance(container, dict) and "ai-guardian" in container:
        if not isinstance(container["ai-guardian"], dict):
            return (
                f"Invalid {format_name} schema in {config_path}: "
                f"'{key}.ai-guardian' must be an object/mapping"
            )
    return None


def _load_opencode_layer_config(
    config_path: Path,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load an OpenCode JSON/JSONC or managed-preference config layer."""
    if config_path.suffix.lower() != ".plist":
        return _load_mcp_config(config_path, _MCP_IDE_CONFIGS["opencode"])

    try:
        with config_path.open("rb") as config_file:
            config = plistlib.load(config_file)
    except (OSError, plistlib.InvalidFileException, ValueError, ExpatError) as exc:
        return (
            None,
            f"Invalid OpenCode managed preference plist in {config_path}: {exc}",
        )

    if not isinstance(config, dict):
        return (
            None,
            f"Invalid OpenCode managed preference plist in {config_path}: "
            "root must be an object/mapping",
        )
    return config, _mcp_schema_error(config, config_path, "mcp")


def _opencode_mcp_registration(
    config: Dict[str, Any], generation: str, config_path: Path
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Return OpenCode's selected registration, layout, and safe diagnostic.

    V2 accepts the supported V1 flat layout in memory. When both layouts name
    the same server, its native ``mcp.servers`` entry takes precedence.
    """
    mcp = config.get("mcp", {})
    if not isinstance(mcp, dict):
        return None, None, None

    if generation == "v2":
        servers = mcp.get("servers", {})
        if not isinstance(servers, dict):
            # The caller's schema check normally catches this; fail closed if
            # a future caller skips it.
            return (
                None,
                "native-v2",
                f"Invalid OpenCode MCP configuration in {config_path}: "
                "'mcp.servers' must be an object/mapping",
            )
        if "ai-guardian" in servers:
            entry = servers["ai-guardian"]
            layout = "native-v2"
        elif "ai-guardian" in mcp:
            entry = mcp["ai-guardian"]
            layout = "legacy-v1"
        else:
            return None, None, None
    else:
        if "ai-guardian" not in mcp:
            return None, None, None
        entry = mcp["ai-guardian"]
        layout = "v1"

    if not isinstance(entry, dict):
        return (
            None,
            layout,
            f"Invalid OpenCode {layout} MCP registration in {config_path}: "
            "'ai-guardian' must be an object/mapping",
        )

    if layout == "native-v2":
        disabled_value = entry.get("disabled", False)
        if not isinstance(disabled_value, bool):
            return (
                None,
                layout,
                f"Invalid OpenCode {layout} MCP registration in {config_path}: "
                "'disabled' must be a boolean",
            )
        if disabled_value:
            return entry, layout, None
    else:
        enabled_value = entry.get("enabled", True)
        if not isinstance(enabled_value, bool):
            return (
                None,
                layout,
                f"Invalid OpenCode {layout} MCP registration in {config_path}: "
                "'enabled' must be a boolean",
            )
        if generation == "v2" and "disabled" in entry:
            disabled_value = entry["disabled"]
            if not isinstance(disabled_value, bool):
                return (
                    None,
                    layout,
                    f"Invalid OpenCode {layout} MCP registration in {config_path}: "
                    "'disabled' must be a boolean",
                )
            if disabled_value:
                return entry, layout, None
        if not enabled_value:
            return entry, layout, None

    server_type = entry.get("type")
    if server_type == "local":
        command = entry.get("command")
        command_diagnostic = _local_command_diagnostic(command)
        if command_diagnostic:
            return (
                None,
                layout,
                f"Invalid OpenCode {layout} MCP registration in {config_path}: "
                f"{command_diagnostic}",
            )
    elif server_type == "remote":
        url = entry.get("url")
        try:
            parsed_url = urlparse(url) if isinstance(url, str) else None
        except ValueError:
            parsed_url = None
        if (
            parsed_url is None
            or parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
        ):
            return (
                None,
                layout,
                f"Invalid OpenCode {layout} MCP registration in {config_path}: "
                "remote servers require an absolute HTTP(S) URL",
            )
    else:
        return (
            None,
            layout,
            f"Invalid OpenCode {layout} MCP registration in {config_path}: "
            "'type' must be 'local' or 'remote'",
        )

    return entry, layout, None


def _verify_opencode_mcp_config(
    scope: str = "user", project_dir: Optional[str] = None
) -> Dict[str, Any]:
    """Verify the effective OpenCode MCP registration without launching it."""
    config_path = get_mcp_config_path("opencode", scope=scope, project_dir=project_dir)
    if config_path is None:
        return {
            "mcp_installed": None,
            "mcp_status": "unsupported",
            "mcp_registration": "none",
            "mcp_config_path": None,
            "mcp_config_scope": "user",
            "mcp_config_source": None,
            "mcp_config_scopes": [],
            "effective_mcp_scope": "not-found",
            "effective_mcp_config_path": None,
        }

    generation = _opencode_mcp_generation()
    project_context = project_dir
    layers = resolve_opencode_config_layers(project_context)
    target_source = (
        "OPENCODE_CONFIG"
        if os.environ.get("OPENCODE_CONFIG")
        else next(
            (
                source
                for layer_scope, source, layer_path in layers
                if layer_scope == "user" and layer_path == config_path
            ),
            "explicit",
        )
    )

    layer_results: List[Dict[str, Any]] = []
    for layer_scope, source, layer_path in layers:
        layer_result: Dict[str, Any] = {
            "scope": layer_scope,
            "source": source,
            "config_path": str(layer_path),
            "exists": layer_path.is_file(),
            "configured": False,
            "status": "missing",
        }
        if layer_path.is_file():
            config, config_error = _load_opencode_layer_config(layer_path)
            if config_error is None and config is not None:
                config_error = _plugin_mcp_schema_error(config, layer_path, generation)
            if config_error:
                layer_result.update({"status": "invalid", "diagnostic": config_error})
            elif config is not None:
                entry, layout, diagnostic = _opencode_mcp_registration(
                    config, generation, layer_path
                )
                if diagnostic:
                    layer_result.update(
                        {
                            "status": "invalid",
                            "diagnostic": diagnostic,
                            "registration_layout": layout,
                        }
                    )
                elif entry is not None:
                    disabled = (
                        entry.get("disabled") is True
                        if layout == "native-v2"
                        else entry.get("enabled") is False
                        or (generation == "v2" and entry.get("disabled") is True)
                    )
                    layer_result.update(
                        {
                            "configured": True,
                            "status": "disabled" if disabled else "healthy",
                            "registration_layout": layout,
                        }
                    )
        layer_results.append(layer_result)

    target_key = os.path.abspath(str(config_path))
    target_result = next(
        (
            layer
            for layer in layer_results
            if os.path.abspath(layer["config_path"]) == target_key
        ),
        {
            "status": "missing",
            "registration_layout": None,
        },
    )

    effective_result = next(
        (
            layer
            for layer in reversed(layer_results)
            if layer.get("status") != "missing"
        ),
        None,
    )
    effective_status = (
        effective_result.get("status", "missing")
        if effective_result is not None
        else "missing"
    )
    result: Dict[str, Any] = {
        "mcp_installed": effective_status == "healthy",
        "mcp_status": effective_status,
        "mcp_registration": "local",
        "mcp_config_path": str(config_path),
        "mcp_config_scope": "user",
        "mcp_config_source": target_source,
        "mcp_target_status": target_result.get("status", "missing"),
        "mcp_target_registration_layout": target_result.get("registration_layout"),
        "mcp_config_scopes": layer_results,
        "effective_mcp_scope": (
            effective_result.get("scope", "not-found")
            if effective_result is not None
            else "not-found"
        ),
        "effective_mcp_source": (
            effective_result.get("source") if effective_result is not None else None
        ),
        "effective_mcp_config_path": (
            effective_result.get("config_path")
            if effective_result is not None
            else None
        ),
        "mcp_registration_layout": (
            effective_result.get("registration_layout")
            if effective_result is not None
            else None
        ),
    }
    if effective_result and effective_result.get("diagnostic"):
        result["mcp_diagnostic"] = effective_result["diagnostic"]
    return result


def _remove_opencode_mcp_entries(config: Dict[str, Any]) -> bool:
    """Remove only AI Guardian's legacy and V2 OpenCode server entries."""
    mcp = config.get("mcp")
    if not isinstance(mcp, dict):
        return False

    changed = "ai-guardian" in mcp
    mcp.pop("ai-guardian", None)

    servers = mcp.get("servers")
    if isinstance(servers, dict) and "ai-guardian" in servers:
        del servers["ai-guardian"]
        changed = True
        if not servers:
            del mcp["servers"]

    if changed and not mcp:
        del config["mcp"]
    return changed


PI_EXTENSION_NAME = "ai-guardian"

# MCP config locations per IDE
_MCP_IDE_CONFIGS: Dict[str, Dict[str, Any]] = {
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
    "grok": {
        "config_file": "~/.grok/config.toml",
        "config_key": "mcp_servers",
        "config_format": "toml",
        "skill_dir": ".grok/skills",
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
    "kilo": {
        "config_file": "~/.config/kilo/kilo.json",
        "config_key": "mcp",
        "skill_dir": ".kilo/skills",
    },
    # Pi's native extension API owns registration; setup does not edit a
    # separate MCP settings file.
    "pi": {
        "config_key": "mcpServers",
        "skill_dir": ".pi/skills",
        "extension_based": True,
        "mcp_client_name": "pi",
    },
    "crush": {
        "config_file": ".crush.json",
        "config_key": "mcp",
        "skill_dir": ".crush/skills",
    },
    "goose": {
        "config_file": "~/.agents/plugins/ai-guardian-goose/.mcp.json",
        "config_key": "mcpServers",
        "skill_dir": ".agents/skills",
    },
    "chatgpt": {
        "plugin_dir": "~/.agents/plugins/ai-guardian-chatgpt",
        "marketplace_file": "~/.agents/plugins/marketplace.json",
        "config_key": "mcpServers",
        "mcp_client_name": "chatgpt-desktop",
        "local_plugin": True,
    },
}

CHATGPT_PLUGIN_NAME = "ai-guardian-chatgpt-advisor"
CHATGPT_PLUGIN_DIRECTORY = "ai-guardian-chatgpt"
CHATGPT_MARKETPLACE_NAME = "ai-guardian-personal"
CHATGPT_MARKETPLACE_DISPLAY_NAME = "AI Guardian Personal Plugins"
CHATGPT_PLUGIN_SOURCE_PATH = f"./{CHATGPT_PLUGIN_DIRECTORY}"
_CHATGPT_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
_CHATGPT_MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
_CHATGPT_PLUGIN_DESCRIPTION = (
    "User-invoked advisory MCP security tools for ChatGPT desktop. "
    "Does not automatically monitor or enforce prompts, tools, or results."
)


def _chatgpt_plugin_dir() -> Path:
    """Return the managed ChatGPT plugin source under the personal marketplace."""
    return Path.home() / ".agents" / "plugins" / CHATGPT_PLUGIN_DIRECTORY


def _chatgpt_marketplace_path() -> Path:
    """Return ChatGPT's documented personal local-marketplace path."""
    return Path.home() / ".agents" / "plugins" / "marketplace.json"


def _chatgpt_paths() -> Dict[str, Path]:
    plugin_dir = _chatgpt_plugin_dir()
    return {
        "plugin_dir": plugin_dir,
        "manifest": plugin_dir / "plugin.json",
        "mcp": plugin_dir / "mcp.json",
        "marketplace": _chatgpt_marketplace_path(),
    }


def _chatgpt_expected_plugin_manifest() -> Dict[str, Any]:
    return {
        "$schema": _CHATGPT_PLUGIN_SCHEMA,
        "name": CHATGPT_PLUGIN_NAME,
        "version": __version__,
        "description": _CHATGPT_PLUGIN_DESCRIPTION,
        "author": {"name": "AI Guardian"},
        "license": "Apache-2.0",
        "extensions": {
            "com.openai": {
                "interface": {
                    "displayName": "AI Guardian Security Advisor",
                    "shortDescription": "User-invoked advisory security checks.",
                    "longDescription": (
                        "Check paths, commands, and MCP trust or sanitize text "
                        "with AI Guardian. Tools are advisory: regular ChatGPT "
                        "mode does not automatically monitor or block prompts, "
                        "tool calls, or results."
                    ),
                    "developerName": "AI Guardian",
                    "category": "Productivity",
                }
            }
        },
    }


def _chatgpt_expected_mcp_config() -> Dict[str, Any]:
    command = _resolved_mcp_command()
    return {
        "$schema": _CHATGPT_MCP_SCHEMA,
        "mcpServers": {
            "ai-guardian": {
                "type": "stdio",
                "command": command[0],
                "args": command[1:],
            }
        },
    }


def _load_chatgpt_json(
    path: Path, label: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load one managed ChatGPT JSON file without echoing its contents."""
    if path.is_symlink():
        return None, f"Refusing to follow a symbolic link for ChatGPT {label}: {path}"
    if not path.exists():
        return None, None
    if not path.is_file():
        return None, f"ChatGPT {label} is not a regular file: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, f"Unable to read valid JSON from ChatGPT {label}: {path}"
    if not isinstance(data, dict):
        return None, f"ChatGPT {label} must have an object at its root: {path}"
    return data, None


def _chatgpt_marketplace_entry_is_owned(entry: Dict[str, Any]) -> bool:
    """Return whether a marketplace entry points at this local plugin source."""
    source = entry.get("source")
    if isinstance(source, str):
        return source == CHATGPT_PLUGIN_SOURCE_PATH
    return (
        isinstance(source, dict)
        and source.get("source") == "local"
        and source.get("path") == CHATGPT_PLUGIN_SOURCE_PATH
    )


def _chatgpt_marketplace_entries(
    marketplace: Dict[str, Any], path: Path
) -> Tuple[Optional[List[Tuple[int, Dict[str, Any]]]], Optional[str]]:
    """Return plugin entries with indexes, rejecting an invalid marketplace list."""
    plugins = marketplace.get("plugins", [])
    if not isinstance(plugins, list) or any(
        not isinstance(plugin, dict) for plugin in plugins
    ):
        return None, f"Invalid ChatGPT marketplace plugin list in {path}"
    return list(enumerate(plugins)), None


def _merge_chatgpt_plugin_manifest(
    existing: Optional[Dict[str, Any]], path: Path
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Update AI Guardian-owned manifest fields and preserve other metadata."""
    manifest = deepcopy(existing) if existing is not None else {}
    if existing is not None and manifest.get("name") != CHATGPT_PLUGIN_NAME:
        return None, f"Refusing to replace a non-AI Guardian plugin manifest: {path}"

    expected = _chatgpt_expected_plugin_manifest()
    for key in ("$schema", "name", "version", "description", "author", "license"):
        manifest[key] = expected[key]

    extensions = manifest.get("extensions", {})
    if not isinstance(extensions, dict):
        return None, f"Invalid ChatGPT plugin extensions object in {path}"
    extensions = deepcopy(extensions)
    openai_extension = extensions.get("com.openai", {})
    if not isinstance(openai_extension, dict):
        return None, f"Invalid ChatGPT OpenAI extension object in {path}"
    openai_extension = deepcopy(openai_extension)
    if "hooks" in openai_extension:
        return None, (
            "The AI Guardian ChatGPT plugin must remain MCP-only; "
            f"remove its existing hook declaration before setup: {path}"
        )
    interface = openai_extension.get("interface", {})
    if not isinstance(interface, dict):
        return None, f"Invalid ChatGPT plugin interface object in {path}"
    interface = deepcopy(interface)
    interface.update(expected["extensions"]["com.openai"]["interface"])
    openai_extension["interface"] = interface
    extensions["com.openai"] = openai_extension
    manifest["extensions"] = extensions
    return manifest, None


def _merge_chatgpt_mcp_config(
    existing: Optional[Dict[str, Any]], path: Path
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Merge the managed stdio server while preserving unrelated MCP entries."""
    config = deepcopy(existing) if existing is not None else {}
    servers = config.get("mcpServers", {})
    if not isinstance(servers, dict):
        return None, f"Invalid ChatGPT MCP server map in {path}"
    expected = _chatgpt_expected_mcp_config()
    config["$schema"] = _CHATGPT_MCP_SCHEMA
    servers = deepcopy(servers)
    servers["ai-guardian"] = expected["mcpServers"]["ai-guardian"]
    config["mcpServers"] = servers
    return config, None


def _merge_chatgpt_marketplace(
    existing: Optional[Dict[str, Any]], path: Path
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Register the local plugin without replacing the user's marketplace."""
    marketplace: Dict[str, Any] = (
        deepcopy(existing)
        if existing is not None
        else {
            "name": CHATGPT_MARKETPLACE_NAME,
            "interface": {"displayName": CHATGPT_MARKETPLACE_DISPLAY_NAME},
            "plugins": [],
        }
    )
    if "name" not in marketplace:
        marketplace["name"] = CHATGPT_MARKETPLACE_NAME
    if not isinstance(marketplace.get("name"), str) or not marketplace.get("name"):
        return None, f"Invalid ChatGPT marketplace name in {path}"

    interface = marketplace.get("interface", {})
    if not isinstance(interface, dict):
        return None, f"Invalid ChatGPT marketplace interface in {path}"
    if "displayName" not in interface:
        interface = deepcopy(interface)
        interface["displayName"] = CHATGPT_MARKETPLACE_DISPLAY_NAME
        marketplace["interface"] = interface

    if "plugins" not in marketplace:
        marketplace["plugins"] = []
    indexed_plugins, error = _chatgpt_marketplace_entries(marketplace, path)
    if error or indexed_plugins is None:
        return None, error
    matches = [
        (index, entry)
        for index, entry in indexed_plugins
        if entry.get("name") == CHATGPT_PLUGIN_NAME
    ]
    if len(matches) > 1:
        return (
            None,
            f"Duplicate AI Guardian plugin entries in ChatGPT marketplace: {path}",
        )

    if matches:
        index, entry = matches[0]
        if not _chatgpt_marketplace_entry_is_owned(entry):
            return None, (
                "The AI Guardian ChatGPT plugin name is already used by a "
                f"different marketplace source: {path}"
            )
        plugin_entry = deepcopy(entry)
        source = plugin_entry.get("source")
        source_config = deepcopy(source) if isinstance(source, dict) else {}
        source_config.update({"source": "local", "path": CHATGPT_PLUGIN_SOURCE_PATH})
        plugin_entry["source"] = source_config
        policy = plugin_entry.get("policy", {})
        if not isinstance(policy, dict):
            return None, f"Invalid AI Guardian marketplace policy in {path}"
        policy = deepcopy(policy)
        policy.update({"installation": "AVAILABLE", "authentication": "ON_INSTALL"})
        plugin_entry["policy"] = policy
        plugin_entry["category"] = "Productivity"
        marketplace["plugins"][index] = plugin_entry
    else:
        marketplace["plugins"].append(
            {
                "name": CHATGPT_PLUGIN_NAME,
                "source": {
                    "source": "local",
                    "path": CHATGPT_PLUGIN_SOURCE_PATH,
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        )
    return marketplace, None


def _apply_chatgpt_file_changes(
    changes: Dict[Path, Optional[str]], setup: Any, operation: str
) -> bool:
    """Back up all changed files before writing or removing any of them."""
    pending: Dict[Path, Optional[str]] = {}
    for path, contents in changes.items():
        if path.is_symlink():
            message = (
                f"Refusing to modify a symbolic link for ChatGPT configuration: {path}"
            )
            print(f"  MCP setup stopped: {message}", file=sys.stderr)
            return False
        if contents is None and not path.exists():
            continue
        if contents is not None and path.is_file():
            try:
                if path.read_text(encoding="utf-8") == contents:
                    continue
            except (OSError, UnicodeError):
                print(
                    f"  MCP setup stopped: Unable to read ChatGPT configuration: {path}",
                    file=sys.stderr,
                )
                return False
        if path.exists() and not path.is_file():
            print(
                f"  MCP setup stopped: ChatGPT configuration is not a regular file: {path}",
                file=sys.stderr,
            )
            return False
        pending[path] = contents

    # Complete every backup before the first file is mutated.
    for path in pending:
        if path.exists() and not _backup_before_write(setup, path, operation):
            return False

    try:
        for path, contents in pending.items():
            if contents is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents, encoding="utf-8")
    except OSError as exc:
        logger.warning("Unable to %s ChatGPT plugin configuration: %s", operation, exc)
        print(
            f"  MCP setup stopped: Unable to {operation} ChatGPT plugin configuration",
            file=sys.stderr,
        )
        return False
    return True


def _install_chatgpt_plugin(setup: Any, dry_run: bool = False) -> bool:
    """Install the desktop-only local plugin and preserve the personal catalog."""
    paths = _chatgpt_paths()
    plugin_dir = paths["plugin_dir"]
    if plugin_dir.is_symlink() or (plugin_dir.exists() and not plugin_dir.is_dir()):
        print(
            f"  MCP setup stopped: ChatGPT plugin path is not a safe directory: {plugin_dir}",
            file=sys.stderr,
        )
        return False
    if dry_run:
        print(
            "  MCP: Would install the ChatGPT desktop-only local plugin and add it "
            f"to {paths['marketplace']}"
        )
        return True

    loaded: Dict[str, Optional[Dict[str, Any]]] = {}
    for key, label in (
        ("manifest", "plugin manifest"),
        ("mcp", "plugin MCP configuration"),
        ("marketplace", "personal marketplace"),
    ):
        loaded[key], error = _load_chatgpt_json(paths[key], label)
        if error:
            print(f"  MCP setup stopped: {error}", file=sys.stderr)
            return False

    manifest, error = _merge_chatgpt_plugin_manifest(
        loaded["manifest"], paths["manifest"]
    )
    if error or manifest is None:
        print(f"  MCP setup stopped: {error}", file=sys.stderr)
        return False
    mcp_config, error = _merge_chatgpt_mcp_config(loaded["mcp"], paths["mcp"])
    if error or mcp_config is None:
        print(f"  MCP setup stopped: {error}", file=sys.stderr)
        return False
    marketplace, error = _merge_chatgpt_marketplace(
        loaded["marketplace"], paths["marketplace"]
    )
    if error or marketplace is None:
        print(f"  MCP setup stopped: {error}", file=sys.stderr)
        return False

    changes: Dict[Path, Optional[str]] = {
        paths["manifest"]: json.dumps(manifest, indent=2) + "\n",
        paths["mcp"]: json.dumps(mcp_config, indent=2) + "\n",
        paths["marketplace"]: json.dumps(marketplace, indent=2) + "\n",
    }
    if not _apply_chatgpt_file_changes(changes, setup, "ChatGPT MCP setup"):
        return False

    print(
        "  MCP: Installed the AI Guardian ChatGPT desktop-only local plugin "
        f"at {plugin_dir}; restart ChatGPT desktop, then install it from the "
        "personal Plugins Directory"
    )
    _register_mcp_identity(_resolve_binary_path())
    return True


def _remove_chatgpt_plugin(setup: Any, dry_run: bool = False) -> bool:
    """Remove only AI Guardian's local package and personal-marketplace entry."""
    paths = _chatgpt_paths()
    plugin_dir = paths["plugin_dir"]
    if plugin_dir.is_symlink() or (plugin_dir.exists() and not plugin_dir.is_dir()):
        print(
            f"  MCP removal stopped: ChatGPT plugin path is not a safe directory: {plugin_dir}",
            file=sys.stderr,
        )
        return False
    if dry_run:
        print(
            "  MCP: Would remove AI Guardian's ChatGPT plugin source and only its "
            f"entry from {paths['marketplace']}"
        )
        return True

    loaded: Dict[str, Optional[Dict[str, Any]]] = {}
    for key, label in (
        ("manifest", "plugin manifest"),
        ("mcp", "plugin MCP configuration"),
        ("marketplace", "personal marketplace"),
    ):
        loaded[key], error = _load_chatgpt_json(paths[key], label)
        if error:
            print(f"  MCP removal stopped: {error}", file=sys.stderr)
            return False

    manifest = loaded["manifest"]
    if manifest is not None and manifest.get("name") != CHATGPT_PLUGIN_NAME:
        print(
            f"  MCP removal stopped: Refusing to remove a non-AI Guardian plugin manifest: {paths['manifest']}",
            file=sys.stderr,
        )
        return False

    marketplace = loaded["marketplace"]
    marketplace_entry_index = None
    if marketplace is not None:
        indexed_plugins, error = _chatgpt_marketplace_entries(
            marketplace, paths["marketplace"]
        )
        if error or indexed_plugins is None:
            print(f"  MCP removal stopped: {error}", file=sys.stderr)
            return False
        matches = [
            (index, entry)
            for index, entry in indexed_plugins
            if entry.get("name") == CHATGPT_PLUGIN_NAME
        ]
        if len(matches) > 1:
            print(
                "  MCP removal stopped: Duplicate AI Guardian plugin entries in "
                f"ChatGPT marketplace: {paths['marketplace']}",
                file=sys.stderr,
            )
            return False
        if matches:
            marketplace_entry_index, entry = matches[0]
            if not _chatgpt_marketplace_entry_is_owned(entry):
                print(
                    "  MCP removal stopped: The AI Guardian ChatGPT plugin name "
                    "points to a different marketplace source",
                    file=sys.stderr,
                )
                return False

    changes: Dict[Path, Optional[str]] = {}
    if manifest is not None:
        changes[paths["manifest"]] = None

    mcp_config = loaded["mcp"]
    if mcp_config is not None:
        servers = mcp_config.get("mcpServers", {})
        if not isinstance(servers, dict):
            print(
                f"  MCP removal stopped: Invalid ChatGPT MCP server map in {paths['mcp']}",
                file=sys.stderr,
            )
            return False
        if "ai-guardian" in servers:
            updated = deepcopy(mcp_config)
            updated_servers = deepcopy(servers)
            del updated_servers["ai-guardian"]
            if updated_servers:
                updated["mcpServers"] = updated_servers
            else:
                updated.pop("mcpServers", None)
            if not updated_servers and set(updated).issubset({"$schema", "mcpServers"}):
                changes[paths["mcp"]] = None
            else:
                changes[paths["mcp"]] = json.dumps(updated, indent=2) + "\n"

    if marketplace is not None and marketplace_entry_index is not None:
        updated_marketplace = deepcopy(marketplace)
        del updated_marketplace["plugins"][marketplace_entry_index]
        changes[paths["marketplace"]] = json.dumps(updated_marketplace, indent=2) + "\n"

    if not changes:
        print("  MCP: AI Guardian ChatGPT plugin was not found; nothing to remove")
        return True
    if not _apply_chatgpt_file_changes(changes, setup, "ChatGPT MCP removal"):
        return False

    try:
        plugin_dir.rmdir()
    except OSError:
        # Preserve any unrelated files left in the plugin directory.
        pass
    print(
        "  MCP: Removed AI Guardian's ChatGPT plugin source and personal-marketplace entry; "
        "the desktop app's cached installation is not managed"
    )
    return True


def _verify_chatgpt_plugin() -> Dict[str, Any]:
    """Verify the local source configuration without claiming host activation."""
    paths = _chatgpt_paths()
    result: Dict[str, Any] = {
        "mcp_installed": False,
        "mcp_status": "missing",
        "mcp_registration": "local-plugin",
        "mcp_config_path": str(paths["mcp"]),
        "mcp_plugin_path": str(paths["plugin_dir"]),
        "mcp_manifest_path": str(paths["manifest"]),
        "mcp_marketplace_path": str(paths["marketplace"]),
        "mcp_plugin_name": CHATGPT_PLUGIN_NAME,
        "mcp_host_installation_status": "unverified",
        "mcp_marketplace_entry": False,
    }
    if paths["plugin_dir"].is_symlink():
        result.update(
            mcp_status="invalid",
            mcp_diagnostic="ChatGPT plugin directory is a symbolic link",
        )
        return result

    loaded: Dict[str, Optional[Dict[str, Any]]] = {}
    for key, label in (
        ("manifest", "plugin manifest"),
        ("mcp", "plugin MCP configuration"),
        ("marketplace", "personal marketplace"),
    ):
        loaded[key], error = _load_chatgpt_json(paths[key], label)
        if error:
            result.update(mcp_status="invalid", mcp_diagnostic=error)
            return result

    marketplace = loaded["marketplace"]
    marketplace_entry: Optional[Dict[str, Any]] = None
    if marketplace is not None:
        indexed_plugins, error = _chatgpt_marketplace_entries(
            marketplace, paths["marketplace"]
        )
        if error or indexed_plugins is None:
            result.update(mcp_status="invalid", mcp_diagnostic=error)
            return result
        matches = [
            entry
            for _, entry in indexed_plugins
            if entry.get("name") == CHATGPT_PLUGIN_NAME
        ]
        if len(matches) > 1:
            result.update(
                mcp_status="invalid",
                mcp_diagnostic="Duplicate AI Guardian plugin entries in ChatGPT marketplace",
            )
            return result
        if matches:
            marketplace_entry = matches[0]
            result["mcp_marketplace_entry"] = True
            if not _chatgpt_marketplace_entry_is_owned(marketplace_entry):
                result.update(
                    mcp_status="invalid",
                    mcp_diagnostic=(
                        "AI Guardian ChatGPT plugin name points to a different "
                        "marketplace source"
                    ),
                )
                return result

    manifest = loaded["manifest"]
    mcp_config = loaded["mcp"]
    if manifest is None or mcp_config is None or marketplace_entry is None:
        result["mcp_diagnostic"] = (
            "ChatGPT plugin source or personal-marketplace entry is missing; "
            "run ai-guardian setup --ide chatgpt"
        )
        return result

    if manifest.get("name") != CHATGPT_PLUGIN_NAME:
        result.update(
            mcp_status="invalid",
            mcp_diagnostic="ChatGPT plugin manifest has an unexpected identity",
        )
        return result
    if manifest.get("version") != __version__:
        result.update(
            mcp_status="stale",
            mcp_diagnostic="ChatGPT plugin source is from a different AI Guardian version",
        )
        return result
    extensions = manifest.get("extensions", {})
    openai_extension = (
        extensions.get("com.openai", {}) if isinstance(extensions, dict) else {}
    )
    if not isinstance(openai_extension, dict) or "hooks" in openai_extension:
        result.update(
            mcp_status="invalid",
            mcp_diagnostic="ChatGPT plugin must remain MCP-only and contain no hooks",
        )
        return result

    servers = mcp_config.get("mcpServers")
    if not isinstance(servers, dict):
        result.update(
            mcp_status="invalid",
            mcp_diagnostic="ChatGPT plugin MCP server map is malformed",
        )
        return result
    server = servers.get("ai-guardian")
    if not isinstance(server, dict):
        result["mcp_diagnostic"] = "ChatGPT plugin's AI Guardian MCP server is missing"
        return result
    expected_server = _chatgpt_expected_mcp_config()["mcpServers"]["ai-guardian"]
    if server != expected_server:
        result.update(
            mcp_status="executable_changed",
            mcp_diagnostic="ChatGPT plugin MCP executable configuration differs from setup",
        )
        return result

    policy = marketplace_entry.get("policy")
    if (
        not isinstance(policy, dict)
        or policy.get("installation") != "AVAILABLE"
        or policy.get("authentication") != "ON_INSTALL"
    ):
        result.update(
            mcp_status="invalid",
            mcp_diagnostic="ChatGPT marketplace entry has an invalid installation policy",
        )
        return result

    result.update(mcp_installed=True, mcp_status="healthy")
    return result


def chatgpt_plugin_has_install_evidence() -> bool:
    """Return whether the personal marketplace references this plugin identity."""
    paths = _chatgpt_paths()
    if paths["manifest"].is_file() or paths["mcp"].is_file():
        return True
    marketplace, error = _load_chatgpt_json(
        paths["marketplace"], "personal marketplace"
    )
    if error or marketplace is None:
        return False
    entries, error = _chatgpt_marketplace_entries(marketplace, paths["marketplace"])
    return (
        not error
        and entries is not None
        and any(entry.get("name") == CHATGPT_PLUGIN_NAME for _, entry in entries)
    )


_MCP_SERVER_ENTRY: Dict[str, object] = {
    "args": ["mcp-server"],
}

_CODEX_MCP_SECTION = "mcp_servers.ai-guardian"
_CODEX_LEGACY_MCP_FILENAME = "codex.json"
_TOML_TABLE_HEADER = re.compile(
    r"^\s*(?P<opening>\[\[?)(?P<name>[^\]]+)(?P<closing>\]\]?)\s*(?:#.*)?$"
)
_TOML_INLINE_MCP_SERVERS = re.compile(r"^\s*mcp_servers\s*=", re.MULTILINE)


def _backup_before_write(setup: Any, config_path: Path, operation: str) -> bool:
    """Back up an existing host config and report a safe write failure."""
    if not config_path.exists():
        return True

    backup_method = getattr(setup, "backup_config", None)
    backup_path: Optional[Path]
    error: Optional[str]
    if callable(backup_method):
        backup_path = backup_method(config_path)
        raw_error = getattr(setup, "_last_backup_error", None)
        error = raw_error if isinstance(raw_error, str) else None
    else:
        backup_path, error = _create_config_backup(config_path)

    if backup_path is None:
        error = (
            error or f"Unable to create backup for existing configuration {config_path}"
        )
        message = f"{operation} stopped before modifying {config_path}: {error}"
        logger.error(message)
        print(f"  {message}", file=sys.stderr)
        return False

    print(f"  MCP: Backup created: {backup_path}")
    return True


def _register_mcp_identity(binary_path: str) -> bool:
    """Record the package identity used by the installed MCP entry point."""
    try:
        from ai_guardian.mcp.identity import register_mcp_identity

        registered = register_mcp_identity(binary_path)
    except Exception as exc:
        logger.error("Unable to register AI Guardian MCP identity: %s", exc)
        registered = False

    if not registered:
        print(
            "  MCP: Warning: identity registration failed; the MCP server will "
            "fail closed until setup succeeds"
        )
    return registered


def get_codex_mcp_config_path() -> Path:
    """Return Codex's global MCP configuration path.

    Codex uses ``~/.codex/config.toml`` by default and relocates the complete
    user configuration directory when ``CODEX_HOME`` is set.  Project-local
    ``.codex/config.toml`` files are intentionally not returned here: AI
    Guardian installs its MCP server in the global user layer.
    """
    path = resolve_ide_mcp_path("codex", "~/.codex/config.toml")
    return path if path is not None else Path("~/.codex/config.toml").expanduser()


def _cursor_project_root(cwd: Optional[str] = None) -> Path:
    """Resolve the workspace root used by Cursor project MCP config."""
    current = Path(cwd or os.getcwd()).expanduser().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    for candidate in (current, *current.parents):
        if (candidate / ".cursor").is_dir():
            return candidate
    return current


def get_pi_extension_dir(
    scope: str = "user", project_dir: Optional[str] = None
) -> Path:
    """Return Pi's managed AI Guardian extension directory.

    Pi discovers extensions from ``<agent-home>/extensions`` and
    ``<project>/.pi/extensions``. The managed extension registers its MCP
    server through Pi's native extension API rather than editing settings.
    """
    if scope == "project":
        if not project_dir:
            raise ValueError("Pi project extension setup requires a project directory")
        return (
            Path(project_dir).expanduser().resolve()
            / ".pi"
            / "extensions"
            / PI_EXTENSION_NAME
        )
    if scope not in ("user", "auto"):
        raise ValueError("Pi scope must be 'user', 'project', or 'auto'")
    path = resolve_ide_config_path(
        "pi",
        "~/.pi/agent/extensions/ai-guardian",
        env_subdir=("extensions", PI_EXTENSION_NAME),
    )
    return Path(path or "~/.pi/agent/extensions/ai-guardian").expanduser()


def get_pi_legacy_extension_path(
    scope: str = "user", project_dir: Optional[str] = None
) -> Path:
    """Return the pre-managed flat Pi extension path."""
    return get_pi_extension_dir(scope=scope, project_dir=project_dir).parent / (
        f"{PI_EXTENSION_NAME}.ts"
    )


def _pi_source_version(source: str) -> Optional[str]:
    """Read the generated package version from a Pi extension source file."""
    marker = "// ai-guardian-generated-version:"
    for line in source.splitlines()[:5]:
        if line.startswith(marker):
            return line.split(":", 1)[1].strip()
    return None


def _pi_expected_binary() -> Tuple[str, List[str]]:
    """Return the pinned executable and arguments embedded in Pi's extension."""
    command = _resolve_binary_path()
    suffix = " -m ai_guardian"
    if command.endswith(suffix):
        return command[: -len(suffix)], ["-m", "ai_guardian"]
    return command, []


def _resolved_mcp_command() -> List[str]:
    """Return an argv-safe MCP command for local JSON configuration."""
    binary = _resolve_binary_path()
    suffix = " -m ai_guardian"
    if binary.endswith(suffix):
        binary = binary[: -len(suffix)]
        return [binary, "-m", "ai_guardian", "mcp-server"]
    return [binary, "mcp-server"]


def verify_pi_mcp_extension(
    scope: str = "user", project_dir: Optional[str] = None
) -> Dict:
    """Return read-only health for Pi's managed native MCP registration.

    The verifier never launches the configured executable.  Runtime identity
    registration and nonce attestation remain enforced by the canonical
    ``ai-guardian mcp-server`` process itself.
    """
    extension_dir = get_pi_extension_dir(scope=scope, project_dir=project_dir)
    extension_path = extension_dir / "index.ts"
    legacy_path = get_pi_legacy_extension_path(scope=scope, project_dir=project_dir)
    base: Dict[str, object] = {
        "mcp_installed": False,
        "mcp_status": "missing",
        "mcp_registration": "extension",
        "mcp_config_path": None,
        "mcp_extension_path": str(extension_path),
        "mcp_package_path": str(extension_dir / "package.json"),
        "mcp_scope": scope,
        "mcp_legacy_path": str(legacy_path),
        "mcp_identity_registered": False,
    }

    if not extension_path.is_file():
        if legacy_path.is_file():
            base["mcp_status"] = "migration_required"
            base["mcp_diagnostic"] = (
                "legacy Pi extension found; rerun setup to migrate it to "
                f"{extension_path}"
            )
        else:
            base["mcp_diagnostic"] = (
                "Pi managed extension is missing; run ai-guardian setup --ide pi "
                "to create "
                f"{extension_path}"
            )
        return base

    try:
        source = extension_path.read_text(encoding="utf-8")
    except OSError:
        base["mcp_status"] = "invalid"
        return base

    source_version = _pi_source_version(source)
    if source_version != __version__:
        base["mcp_status"] = "stale"
        base["mcp_source_version"] = source_version
        base["mcp_diagnostic"] = (
            "Pi extension was generated by a different AI Guardian version; "
            "rerun setup to refresh it"
        )
        return base
    if "const PI_MCP_ENABLED = false;" in source:
        base["mcp_status"] = "disabled"
        base["mcp_disabled"] = True
        base["mcp_installed"] = False
        base["mcp_diagnostic"] = (
            "Pi native MCP registration is disabled; hook protection remains installed"
        )
        return base
    if "const PI_MCP_ENABLED = true;" not in source:
        base["mcp_status"] = "invalid"
        return base
    required_markers = (
        "registerMcpServer",
        "mcp-server",
        'exposure: "direct"',
        "AI_GUARDIAN_PROJECT_DIR: projectDir",
    )
    if any(marker not in source for marker in required_markers):
        base["mcp_status"] = "invalid"
        return base

    expected_binary, expected_args = _pi_expected_binary()
    try:
        binary_match = re.search(r'const GUARDIAN_BINARY = ("[^"]*");', source)
        args_match = re.search(
            r"const GUARDIAN_BINARY_ARGS: string\[\] = (\[[^;]*\]);", source
        )
        rendered_binary = json.loads(binary_match.group(1)) if binary_match else None
        rendered_args = json.loads(args_match.group(1)) if args_match else None
    except (TypeError, ValueError, json.JSONDecodeError):
        rendered_binary = None
        rendered_args = None
    if rendered_binary != expected_binary or rendered_args != expected_args:
        base["mcp_status"] = "executable_changed"
        base["mcp_diagnostic"] = "Pi extension executable pin does not match setup"
        return base

    try:
        from ai_guardian.mcp.identity import (
            _load_verified_manifest,
            get_identity_manifest_path,
        )

        identity_path = get_identity_manifest_path()
        identity_registered = identity_path.is_file()
        identity_valid = identity_registered and _load_verified_manifest() is not None
    except OSError:
        identity_registered = False
        identity_valid = False
    base["mcp_identity_registered"] = identity_registered
    if not identity_registered:
        base["mcp_identity_diagnostic"] = (
            "AI Guardian MCP identity registration is missing"
        )
    elif not identity_valid:
        base["mcp_identity_diagnostic"] = (
            "AI Guardian MCP identity manifest failed verification"
        )

    if not identity_registered:
        base["mcp_status"] = "identity_missing"
        base["mcp_diagnostic"] = "AI Guardian MCP identity registration is missing"
        return base
    if not identity_valid:
        base["mcp_status"] = "identity_invalid"
        base["mcp_diagnostic"] = "AI Guardian MCP identity manifest failed verification"
        return base

    base["mcp_installed"] = True
    base["mcp_status"] = "healthy"
    return base


def get_mcp_config_path(
    ide_type: str,
    scope: str = "user",
    project_dir: Optional[str] = None,
) -> Optional[Path]:
    """Return an IDE's user or project MCP configuration path."""
    if ide_type == "chatgpt":
        return _chatgpt_plugin_dir() / "mcp.json"
    if ide_type == "goose":
        from ai_guardian.goose_support import goose_hook_path

        if scope == "auto":
            from ai_guardian.setup.goose import verify_goose_hooks

            return (
                Path(
                    verify_goose_hooks(scope, project_dir)["config_path"]
                ).parent.parent
                / ".mcp.json"
            )
        return goose_hook_path(scope, project_dir).parent.parent / ".mcp.json"
    if ide_type == "codex":
        return get_codex_mcp_config_path()

    mcp_ide = _MCP_IDE_CONFIGS.get(ide_type)
    if not mcp_ide:
        return None

    if ide_type == "copilot":
        return resolve_ide_mcp_path(ide_type, None)

    config_file = mcp_ide.get("config_file", "")
    if not config_file:
        return None
    if ide_type == "crush" and scope == "project":
        project_root = Path(project_dir).expanduser() if project_dir else Path.cwd()
        return project_root / ".crush.json"
    if ide_type == "cursor":
        if scope == "project":
            # The explicit project argument is the selected workspace. Avoid
            # walking parents, where an unrelated .cursor directory could
            # redirect a project-scoped health lookup. A missing argument is
            # retained for effective-scope discovery from the current cwd.
            project_root = (
                Path(project_dir).expanduser().resolve()
                if project_dir
                else _cursor_project_root()
            )
            return project_root / ".cursor" / "mcp.json"
        if scope not in ("user", "auto"):
            raise ValueError("Cursor scope must be 'user', 'project', or 'auto'")
    if ide_type == "grok" and scope == "project":
        project_root = Path(project_dir).expanduser() if project_dir else Path.cwd()
        return project_root / ".grok" / "config.toml"
    if ide_type == "opencode":
        return _resolve_opencode_config()
    if ide_type == "kilo":
        from ai_guardian.ide_paths import resolve_kilo_config_file

        return resolve_kilo_config_file(scope=scope, project_dir=project_dir)
    return resolve_ide_mcp_path(ide_type, config_file)


def _cursor_mcp_entry_exists(path: Path) -> bool:
    """Check one Cursor MCP file without exposing its contents."""
    if not path.is_file():
        return False
    config, error = _load_mcp_config(path, {"config_key": "mcpServers"})
    if error:
        logger.warning("Unable to verify Cursor MCP config %s: %s", path, error)
        return False
    if config is None:
        return False
    servers = config.get("mcpServers", {}) if isinstance(config, dict) else {}
    return isinstance(servers, dict) and isinstance(servers.get("ai-guardian"), dict)


def verify_cursor_mcp_config(
    scope: str = "auto", project_dir: Optional[str] = None
) -> Dict:
    """Return JSON-safe health information for Cursor MCP layers."""
    if scope == "project":
        # Cursor Cloud Agents do not read a developer's local project MCP
        # file. Cloud MCP servers are configured in Cursor's dashboard/team
        # settings or supplied through the Cloud Agents API, so there is no
        # local file that this verifier can truthfully validate.
        return {
            "mcp_installed": None,
            "mcp_status": "external",
            "mcp_registration": "cursor-cloud",
            "mcp_config_path": None,
            "effective_mcp_config_path": None,
            "config_scopes": [
                {
                    "scope": "project",
                    "config_path": None,
                    "exists": None,
                    "configured": None,
                    "status": "external",
                }
            ],
        }

    if scope == "auto":
        paths: List[Tuple[str, Optional[Path]]] = [
            ("user", get_mcp_config_path("cursor", scope="user")),
            (
                "project",
                get_mcp_config_path("cursor", scope="project", project_dir=project_dir),
            ),
        ]
    else:
        paths = [
            (scope, get_mcp_config_path("cursor", scope=scope, project_dir=project_dir))
        ]

    config_scopes: List[Dict] = []
    for layer_scope, path in paths:
        if path is None:
            config_scopes.append(
                {
                    "scope": layer_scope,
                    "config_path": None,
                    "exists": False,
                    "configured": False,
                    "status": "missing",
                }
            )
            continue
        config, config_error = (
            _load_mcp_config(path, {"config_key": "mcpServers"})
            if path.is_file()
            else (None, None)
        )
        configured = (
            isinstance(config, dict)
            and isinstance(config.get("mcpServers"), dict)
            and isinstance(config["mcpServers"].get("ai-guardian"), dict)
            and config_error is None
        )
        config_scopes.append(
            {
                "scope": layer_scope,
                "config_path": str(path),
                "exists": path.is_file(),
                "configured": configured,
                "status": (
                    "invalid"
                    if config_error
                    else "healthy" if configured else "missing"
                ),
                "diagnostic": config_error,
            }
        )

    configured_layers = [layer for layer in config_scopes if layer["configured"]]
    invalid_layers = [
        layer for layer in config_scopes if layer.get("status") == "invalid"
    ]
    effective_path = (
        configured_layers[0]["config_path"]
        if configured_layers
        else config_scopes[0]["config_path"]
    )
    user_path = next(
        (
            layer["config_path"]
            for layer in config_scopes
            if layer.get("scope") == "user"
        ),
        effective_path,
    )
    result = {
        "mcp_installed": bool(configured_layers) and not invalid_layers,
        "mcp_status": (
            "invalid"
            if invalid_layers
            else ("healthy" if configured_layers else "missing")
        ),
        "mcp_registration": "local",
        "mcp_config_path": user_path if scope == "auto" else effective_path,
        "effective_mcp_config_path": effective_path,
        "config_scopes": config_scopes,
    }
    diagnostics = [
        str(layer["diagnostic"]) for layer in invalid_layers if layer.get("diagnostic")
    ]
    if diagnostics:
        result["mcp_diagnostic"] = "; ".join(diagnostics)
    return result


def verify_mcp_config(
    ide_type: str,
    scope: str = "user",
    project_dir: Optional[str] = None,
) -> Dict:
    """Return read-only health information for a local MCP registration.

    This checks only the host configuration.  It deliberately does not launch
    the configured command, create an identity manifest, or create a runtime
    attestation; those actions belong to MCP server startup.
    """
    if ide_type == "chatgpt":
        return _verify_chatgpt_plugin()
    if ide_type == "pi":
        return verify_pi_mcp_extension(scope=scope, project_dir=project_dir)
    if ide_type == "opencode":
        return _verify_opencode_mcp_config(scope=scope, project_dir=project_dir)

    mcp_ide = _MCP_IDE_CONFIGS.get(ide_type)
    if not mcp_ide:
        return {
            "mcp_installed": None,
            "mcp_status": "unsupported",
            "mcp_registration": "none",
            "mcp_config_path": None,
        }

    config_path = get_mcp_config_path(ide_type, scope=scope, project_dir=project_dir)
    base = {
        "mcp_installed": False,
        "mcp_status": "missing",
        "mcp_registration": "local",
        "mcp_config_path": str(config_path) if config_path else None,
    }
    if config_path is None:
        base["mcp_status"] = "unsupported"
        base["mcp_registration"] = "none"
        return base
    if not config_path.is_file():
        return base

    config, config_error = _load_mcp_config(config_path, mcp_ide)
    if config_error:
        base["mcp_status"] = "invalid"
        base["mcp_diagnostic"] = config_error
        return base
    if config is None:
        return base

    servers = config.get(mcp_ide["config_key"], {})

    if not isinstance(servers, dict):
        base["mcp_status"] = "invalid"
        base["mcp_diagnostic"] = _mcp_schema_error(
            config, config_path, mcp_ide["config_key"]
        )
        return base

    entry = servers.get("ai-guardian")
    if not isinstance(entry, dict):
        return base
    if ide_type == "goose":
        from ai_guardian.setup.goose import (
            validate_goose_mcp_target,
            verify_goose_hooks,
        )

        try:
            validate_goose_mcp_target(config_path)
        except (OSError, ValueError) as exc:
            base["mcp_status"] = "invalid"
            base["mcp_diagnostic"] = str(exc)
            return base
        for server in servers.values():
            if (
                not isinstance(server, dict)
                or not isinstance(server.get("command"), str)
                or not isinstance(server.get("args", []), list)
                or not all(isinstance(arg, str) for arg in server.get("args", []))
                or not isinstance(server.get("env", {}), dict)
                or not all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in server.get("env", {}).items()
                )
                or (
                    server.get("cwd") is not None and not isinstance(server["cwd"], str)
                )
            ):
                base["mcp_status"] = "invalid"
                base["mcp_diagnostic"] = (
                    "Goose plugin MCP server configuration is malformed"
                )
                return base

        hooks = verify_goose_hooks(scope, project_dir)
        if not hooks["healthy"]:
            base["mcp_status"] = "inactive"
            return base
        if entry.get("command") != _resolve_binary_path() or entry.get("args") != [
            "mcp-server"
        ]:
            base["mcp_status"] = "invalid"
            return base
    if ide_type == "kilo":
        command_diagnostic = _local_command_diagnostic(entry.get("command"))
        if command_diagnostic:
            base["mcp_status"] = "invalid"
            base["mcp_diagnostic"] = command_diagnostic
            return base
    disabled = entry.get("enabled") is False
    if disabled:
        base["mcp_status"] = "disabled"
        return base

    base["mcp_installed"] = True
    base["mcp_status"] = "healthy"
    return base


def _load_toml_text(text: str) -> Dict:
    """Parse TOML using the stdlib parser or the Python 3.10 backport."""
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
    """Return whether Codex has an enabled AI Guardian MCP server."""
    path = config_path or get_codex_mcp_config_path()
    if not path.is_file():
        return False

    data, config_error = _load_mcp_config(path, _MCP_IDE_CONFIGS["codex"])
    if config_error or data is None:
        logger.warning("Unable to read Codex MCP config %s: %s", path, config_error)
        return False

    mcp_servers = data.get("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        return False

    entry = mcp_servers.get("ai-guardian")
    if not isinstance(entry, dict):
        return False

    # Codex treats an omitted ``enabled`` key as enabled.  An explicit false
    # value means the server is present but inactive, so setup verification
    # must not report it as healthy.
    return entry.get("enabled", True) is not False


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
    return {
        "command": binary_path,
        "args": ["mcp-server"],
        "enabled": True,
    }


def _legacy_codex_mcp_path() -> Path:
    """Return the pre-85ec72f project-root Codex MCP path."""
    return Path.cwd() / _CODEX_LEGACY_MCP_FILENAME


def _clean_legacy_codex_mcp_entry(
    target_path: Optional[Path] = None,
    dry_run: bool = False,
    setup: Any = None,
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

    config, config_error = _load_cli_config(legacy_path)
    if config_error or config is None:
        logger.warning(
            "Unable to read stale Codex MCP config %s: %s",
            legacy_path,
            config_error,
        )
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

    if not _backup_before_write(setup, legacy_path, "Codex MCP migration"):
        return False

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
    scope: str = "user",
    project_dir: Optional[str] = None,
) -> Optional[bool]:
    """Install or remove MCP server config for an IDE."""
    if no_mcp:
        return _remove_mcp_config(
            setup, ide_type, dry_run, scope=scope, project_dir=project_dir
        )
    return _install_mcp_config(
        setup, ide_type, dry_run, scope=scope, project_dir=project_dir
    )


def _install_mcp_config(
    setup,
    ide_type: str,
    dry_run: bool = False,
    scope: str = "user",
    project_dir: Optional[str] = None,
) -> Optional[bool]:
    """Add MCP server entry to IDE config and enable in ai-guardian config."""
    mcp_ide = _MCP_IDE_CONFIGS.get(ide_type)
    if not mcp_ide:
        return None
    if ide_type == "chatgpt":
        return _install_chatgpt_plugin(setup, dry_run=dry_run)
    generation = _opencode_mcp_generation() if ide_type == "opencode" else None

    if ide_type == "pi":
        if dry_run:
            print(
                "  MCP: Pi uses the managed ai-guardian extension; "
                "no native MCP file would be created"
            )
        else:
            print(
                "  MCP: Pi MCP tools are provided by the managed ai-guardian extension"
            )
            _register_mcp_identity(_resolve_binary_path())
        return None

    if ide_type == "cursor":
        if project_dir and scope == "user":
            scope = "project"
        if scope not in ("user", "project"):
            logger.warning("Cursor MCP setup scope must be 'user' or 'project'")
            return None
        if scope == "project":
            if not project_dir:
                logger.warning("Cursor project MCP setup requires a project directory")
                return None
            project_path = Path(project_dir).expanduser()
            if not project_path.is_dir():
                logger.warning(
                    "Cursor project MCP directory does not exist or is not a "
                    "directory: %s",
                    project_path,
                )
                return None
            project_dir = str(project_path.resolve())
            print(
                "  MCP: Cursor Cloud MCP is managed by the Cursor dashboard/team "
                "settings or Cloud Agents API; project .cursor/mcp.json was "
                "left unchanged"
            )
            return None
        else:
            project_dir = None

    config_path = get_mcp_config_path(ide_type, scope=scope, project_dir=project_dir)
    if config_path is None:
        return None

    if ide_type == "kilo" and scope == "project":
        if not project_dir:
            logger.warning("Kilo project MCP setup requires a project directory")
            return None
        project_root = project_dir
        try:
            ensure_project_path_no_symlink(config_path, project_root)
        except ValueError as exc:
            logger.warning("Kilo MCP setup stopped for unsafe project path: %s", exc)
            print(f"  MCP setup stopped: {exc}", file=sys.stderr)
            return None

    if ide_type == "goose":
        from ai_guardian.setup.goose import validate_goose_mcp_target

        try:
            validate_goose_mcp_target(config_path)
        except (OSError, ValueError):
            logger.warning(
                "Goose MCP setup stopped: managed plugin layout cannot be verified"
            )
            return None

    if ide_type == "codex":
        _install_codex_mcp_config(config_path, dry_run=dry_run, setup=setup)
        return None
    if mcp_ide.get("config_format") == "toml":
        _install_toml_mcp_config(
            config_path,
            mcp_ide["config_key"],
            dry_run=dry_run,
            setup=setup,
        )
        return None

    if dry_run:
        print(f"  MCP: Would add ai-guardian MCP server to {config_path}")
        return None

    # Read or create config file
    config, config_error = _load_mcp_config(config_path, mcp_ide)
    if config_error is None and config is not None:
        if ide_type == "opencode" and generation is not None:
            config_error = _plugin_mcp_schema_error(config, config_path, generation)
        elif ide_type == "kilo":
            config_error = _plugin_mcp_schema_error(config, config_path, "v1")
    if config_error:
        # Never replace a non-empty user config that cannot be parsed or does
        # not have the host's expected MCP container shape.
        logger.warning("Failed to read MCP config %s: %s", config_path, config_error)
        print(f"  MCP setup stopped: {config_error}", file=sys.stderr)
        return None
    if config is None:
        config = {}
    original_config = deepcopy(config)

    # Add MCP server entry with absolute path
    abs_path = _resolve_binary_path()
    key = mcp_ide["config_key"]

    if ide_type in {"opencode", "kilo"}:
        mcp_entry: Dict[str, Any] = {
            "type": "local",
            "command": _resolved_mcp_command(),
        }
        if ide_type == "kilo" or generation == "v1":
            mcp_entry["enabled"] = True
    else:
        mcp_entry = dict(_MCP_SERVER_ENTRY)
        mcp_entry["command"] = abs_path
        if ide_type == "cursor":
            mcp_entry["type"] = "stdio"

    if ide_type == "opencode":
        _remove_opencode_mcp_entries(config)
        mcp_config = config.setdefault("mcp", {})
        if generation == "v2":
            servers = mcp_config.setdefault("servers", {})
            servers["ai-guardian"] = mcp_entry
        else:
            mcp_config["ai-guardian"] = mcp_entry
    elif ide_type == "kilo":
        mcp_config = config.setdefault("mcp", {})
        mcp_config["ai-guardian"] = mcp_entry
    else:
        if key not in config:
            config[key] = {}
        config[key]["ai-guardian"] = mcp_entry

    if config == original_config:
        print(f"  MCP: ai-guardian MCP server already configured in {config_path}")
        _register_mcp_identity(abs_path)
        return None

    if not _backup_before_write(setup, config_path, "MCP setup"):
        return None
    serialized_config = json.dumps(config, indent=2) + "\n"
    if ide_type == "kilo" and scope == "project":
        try:
            write_project_text_no_symlink(config_path, serialized_config, project_root)
        except (OSError, ValueError) as exc:
            logger.warning(
                "Unable to write Kilo project MCP config %s: %s", config_path, exc
            )
            return None
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(serialized_config)

    print(f"  MCP: Added ai-guardian MCP server to {config_path}")
    _register_mcp_identity(abs_path)

    # Warn if MCP entry exists in settings.json (hooks file) for Claude
    if ide_type == "claude":
        raw_settings_path = resolve_ide_config_path(
            "claude", "~/.claude/settings.json", filename="settings.json"
        )
        if raw_settings_path is None:
            return None
        settings_path = Path(raw_settings_path).expanduser()
        if settings_path.exists():
            settings, settings_error = _load_cli_config(settings_path)
            if settings_error:
                logger.warning(
                    "Failed to read config %s: %s", settings_path, settings_error
                )
                return None
            if settings and "ai-guardian" in settings.get("mcpServers", {}):
                print(
                    "  MCP: Warning: ai-guardian MCP entry found in "
                    f"{settings_path} (hooks file).\n"
                    f"  MCP servers should be in {config_path}. "
                    "Remove the entry from settings.json to avoid conflicts."
                )

    return None


def _install_codex_mcp_config(
    config_path: Path, dry_run: bool = False, setup: Any = None
) -> None:
    """Register AI Guardian in Codex's global TOML MCP configuration."""
    if dry_run:
        print(f"  MCP: Would add ai-guardian MCP server to {config_path}")
        _clean_legacy_codex_mcp_entry(target_path=config_path, dry_run=True)
        return

    raw = ""
    if config_path.exists():
        data, config_error = _load_mcp_config(config_path, _MCP_IDE_CONFIGS["codex"])
        if config_error:
            logger.warning(
                "Failed to read Codex config %s: %s", config_path, config_error
            )
            print(f"  MCP setup stopped: {config_error}", file=sys.stderr)
            return
        raw = config_path.read_text(encoding="utf-8")
        if data is None:
            data = {}
    else:
        data = {}

    mcp_servers = data.get("mcp_servers")
    if mcp_servers is not None and not isinstance(mcp_servers, dict):
        logger.warning(
            "Cannot add AI Guardian to Codex config %s: mcp_servers is not a table",
            config_path,
        )
        return

    binary_path = _resolve_binary_path()
    entry = _codex_mcp_entry(binary_path)
    existing_entry = (
        mcp_servers.get("ai-guardian") if isinstance(mcp_servers, dict) else None
    )
    if (
        isinstance(existing_entry, dict)
        and existing_entry.get("command") == binary_path
        and existing_entry.get("args") == ["mcp-server"]
        and existing_entry.get("enabled", True) is not False
    ):
        print(f"  MCP: ai-guardian MCP server already configured in {config_path}")
        _register_mcp_identity(binary_path)
        _clean_legacy_codex_mcp_entry(
            target_path=config_path,
            setup=setup,
        )
        return

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
            if not _backup_before_write(setup, config_path, "Codex MCP setup"):
                return
            config_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to write Codex MCP config %s: %s", config_path, exc)
        return

    print(f"  MCP: Added ai-guardian MCP server to {config_path}")
    _register_mcp_identity(binary_path)
    _clean_legacy_codex_mcp_entry(target_path=config_path, setup=setup)


def _install_toml_mcp_config(
    config_path: Path,
    config_key: str,
    dry_run: bool = False,
    setup: Any = None,
) -> None:
    """Register AI Guardian in a native TOML MCP configuration."""
    if dry_run:
        print(f"  MCP: Would add ai-guardian MCP server to {config_path}")
        return

    raw = ""
    if config_path.exists():
        data, config_error = _load_mcp_config(
            config_path, {"config_key": config_key, "config_format": "toml"}
        )
        if config_error:
            logger.warning(
                "Failed to read MCP config %s: %s", config_path, config_error
            )
            print(f"  MCP setup stopped: {config_error}", file=sys.stderr)
            return
        raw = config_path.read_text(encoding="utf-8")
        if data is None:
            data = {}
    else:
        data = {}

    servers = data.get(config_key)
    if servers is not None and not isinstance(servers, dict):
        logger.warning(
            "Cannot add AI Guardian to %s: %s is not a table", config_path, config_key
        )
        return

    binary_path = _resolve_binary_path()
    entry = {
        "command": binary_path,
        "args": ["mcp-server"],
    }
    existing_entry = servers.get("ai-guardian") if isinstance(servers, dict) else None
    if existing_entry == entry:
        print(f"  MCP: ai-guardian MCP server already configured in {config_path}")
        _register_mcp_identity(binary_path)
        return

    updated_servers = dict(servers or {})
    updated_servers["ai-guardian"] = entry
    updated_data = dict(data)
    updated_data[config_key] = updated_servers
    try:
        updated = _dump_toml(updated_data)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if updated == raw:
            print(f"  MCP: ai-guardian MCP server already configured in {config_path}")
            _register_mcp_identity(binary_path)
            return
        if not _backup_before_write(setup, config_path, "TOML MCP setup"):
            return
        config_path.write_text(updated, encoding="utf-8")
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Failed to write MCP config %s: %s", config_path, exc)
        return

    print(f"  MCP: Added ai-guardian MCP server to {config_path}")
    _register_mcp_identity(_resolve_binary_path())


def _remove_mcp_config(
    setup,
    ide_type: str,
    dry_run: bool = False,
    scope: str = "user",
    project_dir: Optional[str] = None,
) -> Optional[bool]:
    """Remove MCP server entry from IDE config."""
    mcp_ide = _MCP_IDE_CONFIGS.get(ide_type)
    if not mcp_ide:
        return None
    if ide_type == "chatgpt":
        return _remove_chatgpt_plugin(setup, dry_run=dry_run)

    if ide_type == "pi":
        if dry_run:
            print(
                "  MCP: Use `ai-guardian setup --ide pi --no-mcp` to disable "
                "registration in Pi's managed extension; no separate MCP "
                "settings file is removed"
            )
        else:
            print(
                "  MCP: Registration is managed by Pi's extension; run "
                "`ai-guardian setup --ide pi --no-mcp` to disable MCP while "
                "retaining hook protection"
            )
        return None

    if ide_type == "cursor":
        if project_dir and scope == "user":
            scope = "project"
        if scope == "project":
            print(
                "  MCP: Cursor Cloud MCP is managed by the Cursor dashboard/team "
                "settings or Cloud Agents API; no project MCP file was changed"
            )
            return None

    config_path = get_mcp_config_path(ide_type, scope=scope, project_dir=project_dir)
    if config_path is None:
        return None

    if ide_type == "kilo" and scope == "project":
        if not project_dir:
            logger.warning("Kilo project MCP removal requires a project directory")
            return None
        project_root = project_dir
        try:
            ensure_project_path_no_symlink(config_path, project_root)
        except ValueError as exc:
            logger.warning("Kilo MCP removal stopped for unsafe project path: %s", exc)
            print(f"  MCP removal stopped: {exc}", file=sys.stderr)
            return None

    if ide_type == "goose":
        from ai_guardian.setup.goose import validate_goose_mcp_target

        try:
            validate_goose_mcp_target(config_path)
        except (OSError, ValueError):
            logger.warning(
                "Goose MCP removal stopped: managed plugin layout cannot be verified"
            )
            return None

    if ide_type == "codex":
        _remove_codex_mcp_config(config_path, dry_run=dry_run, setup=setup)
        return None
    if mcp_ide.get("config_format") == "toml":
        _remove_toml_mcp_config(
            config_path,
            mcp_ide["config_key"],
            dry_run=dry_run,
            setup=setup,
        )
        return None

    if dry_run:
        print(f"  MCP: Would remove ai-guardian MCP server from {config_path}")
        return None

    if not config_path.exists():
        print("  MCP: No config file found, nothing to remove")
        return None

    config, config_error = _load_mcp_config(config_path, mcp_ide)
    if config_error or config is None:
        logger.warning("Failed to read MCP config %s: %s", config_path, config_error)
        return None

    if ide_type == "opencode":
        if not _remove_opencode_mcp_entries(config):
            print("  MCP: ai-guardian MCP server not found in config")
            return None
        if not _backup_before_write(setup, config_path, "MCP removal"):
            return None
        serialized_config = json.dumps(config, indent=2) + "\n"
        if ide_type == "kilo" and scope == "project":
            write_project_text_no_symlink(config_path, serialized_config, project_root)
        else:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(serialized_config)
        print(f"  MCP: Removed ai-guardian MCP server from {config_path}")
        return None

    key = mcp_ide["config_key"]
    if key in config and "ai-guardian" in config[key]:
        del config[key]["ai-guardian"]
        if not config[key]:
            del config[key]
        if not _backup_before_write(setup, config_path, "MCP removal"):
            return None
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
        print(f"  MCP: Removed ai-guardian MCP server from {config_path}")
    else:
        print("  MCP: ai-guardian MCP server not found in config")

    return None


def _remove_codex_mcp_config(
    config_path: Path, dry_run: bool = False, setup: Any = None
) -> None:
    """Remove AI Guardian from Codex's global TOML MCP configuration."""
    if dry_run:
        print(f"  MCP: Would remove ai-guardian MCP server from {config_path}")
        _clean_legacy_codex_mcp_entry(dry_run=True)
        return

    if not config_path.exists():
        print("  MCP: No config file found, nothing to remove")
        _clean_legacy_codex_mcp_entry(setup=setup)
        return

    data, config_error = _load_mcp_config(config_path, _MCP_IDE_CONFIGS["codex"])
    if config_error or data is None:
        logger.warning("Failed to read Codex config %s: %s", config_path, config_error)
        print(f"  MCP removal stopped: {config_error}", file=sys.stderr)
        return
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read Codex config %s: %s", config_path, exc)
        print(f"  MCP removal stopped: {exc}", file=sys.stderr)
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
                if not isinstance(mcp_servers, dict):
                    return
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
            if not _backup_before_write(setup, config_path, "Codex MCP removal"):
                return
            config_path.write_text(updated, encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write Codex MCP config %s: %s", config_path, exc)
            return
        print(f"  MCP: Removed ai-guardian MCP server from {config_path}")
    else:
        print("  MCP: ai-guardian MCP server not found in config")

    _clean_legacy_codex_mcp_entry(setup=setup)


def _remove_toml_mcp_config(
    config_path: Path,
    config_key: str,
    dry_run: bool = False,
    setup: Any = None,
) -> None:
    """Remove AI Guardian from a native TOML MCP configuration."""
    if dry_run:
        print(f"  MCP: Would remove ai-guardian MCP server from {config_path}")
        return
    if not config_path.exists():
        print("  MCP: No config file found, nothing to remove")
        return

    data, config_error = _load_mcp_config(
        config_path, {"config_key": config_key, "config_format": "toml"}
    )
    if config_error or data is None:
        logger.warning("Failed to read MCP config %s: %s", config_path, config_error)
        print(f"  MCP removal stopped: {config_error}", file=sys.stderr)
        return
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read MCP config %s: %s", config_path, exc)
        print(f"  MCP removal stopped: {exc}", file=sys.stderr)
        return

    servers = data.get(config_key)
    if not isinstance(servers, dict) or "ai-guardian" not in servers:
        print("  MCP: ai-guardian MCP server not found in config")
        return

    updated_data = dict(data)
    updated_servers = dict(servers)
    del updated_servers["ai-guardian"]
    if updated_servers:
        updated_data[config_key] = updated_servers
    else:
        updated_data.pop(config_key, None)
    try:
        updated = _dump_toml(updated_data)
        if not _backup_before_write(setup, config_path, "TOML MCP removal"):
            return
        config_path.write_text(updated, encoding="utf-8")
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Failed to write MCP config %s: %s", config_path, exc)
        return
    print(f"  MCP: Removed ai-guardian MCP server from {config_path}")
