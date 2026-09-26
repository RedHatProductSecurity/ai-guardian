"""MCP server configuration for ai-guardian setup."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ai_guardian import __version__

from ai_guardian.ide_paths import resolve_ide_config_path, resolve_ide_mcp_path
from ai_guardian.setup.utils import (
    _resolve_binary_path,
    _resolve_opencode_config,
    _strip_jsonc_comments,
)

logger = logging.getLogger(__name__)

PI_EXTENSION_NAME = "ai-guardian"
PI_MCP_SDK_VERSION = "1.30.1"
PI_MCP_PACKAGE_NAME = "@modelcontextprotocol/sdk"

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
    # Pi does not expose a native MCP configuration surface.  Its managed
    # extension is the registration boundary instead of a fabricated MCP file.
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
}

_MCP_SERVER_ENTRY: Dict[str, object] = {
    "args": ["mcp-server"],
}

_CODEX_MCP_SECTION = "mcp_servers.ai-guardian"
_CODEX_LEGACY_MCP_FILENAME = "codex.json"
_TOML_TABLE_HEADER = re.compile(
    r"^\s*(?P<opening>\[\[?)(?P<name>[^\]]+)(?P<closing>\]\]?)\s*(?:#.*)?$"
)
_TOML_INLINE_MCP_SERVERS = re.compile(r"^\s*mcp_servers\s*=", re.MULTILINE)


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
    ``<project>/.pi/extensions``.  The extension directory is deliberately
    separate from Pi's native configuration because Pi has no MCP config file.
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
        "~/.pi/agent",
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


def _pi_package_status(extension_dir: Path) -> Tuple[str, bool, Optional[str]]:
    """Validate Pi's pinned SDK manifest and local installation."""
    package_path = extension_dir / "package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "missing", False, None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return "invalid", False, None

    dependencies = package.get("dependencies") if isinstance(package, dict) else None
    declared = (
        isinstance(dependencies, dict)
        and dependencies.get(PI_MCP_PACKAGE_NAME) == PI_MCP_SDK_VERSION
    )
    if not declared:
        return "invalid", False, None

    sdk_package = (
        extension_dir
        / "node_modules"
        / "@modelcontextprotocol"
        / "sdk"
        / "package.json"
    )
    try:
        sdk = json.loads(sdk_package.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return "missing_dependencies", False, str(package_path)
    if not isinstance(sdk, dict) or sdk.get("version") != PI_MCP_SDK_VERSION:
        return "invalid_dependencies", False, str(package_path)
    return "healthy", True, str(package_path)


def verify_pi_mcp_extension(
    scope: str = "user", project_dir: Optional[str] = None
) -> Dict:
    """Return read-only health for Pi's managed MCP extension bridge.

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
            "Pi MCP bridge is disabled; hook protection remains installed"
        )
        return base
    if "const PI_MCP_ENABLED = true;" not in source:
        base["mcp_status"] = "invalid"
        return base
    required_markers = (
        "@modelcontextprotocol/sdk/client/index.js",
        "@modelcontextprotocol/sdk/client/stdio.js",
        "StdioClientTransport",
        "listTools",
        "callTool",
        "mcp-server",
        "mcp__ai-guardian__",
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

    package_status, package_ok, package_path = _pi_package_status(extension_dir)
    base["mcp_package_path"] = package_path or str(extension_dir / "package.json")
    if not package_ok:
        base["mcp_status"] = package_status
        if package_status == "missing_dependencies":
            base["mcp_diagnostic"] = (
                "Install the pinned Pi MCP SDK with "
                "npm install --ignore-scripts --no-audit --no-fund"
            )
        elif package_status == "invalid_dependencies":
            base["mcp_diagnostic"] = (
                "Pi MCP SDK version does not match the pinned 1.30.1 dependency"
            )
        return base

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
    if ide_type == "opencode":
        return _resolve_opencode_config()
    return resolve_ide_mcp_path(ide_type, config_file)


def _cursor_mcp_entry_exists(path: Path) -> bool:
    """Check one Cursor MCP file without exposing its contents."""
    if not path.is_file():
        return False
    try:
        raw = path.read_text(encoding="utf-8")
        config = json.loads(_strip_jsonc_comments(raw)) if raw.strip() else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Unable to verify Cursor MCP config %s: %s", path, exc)
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
        configured = _cursor_mcp_entry_exists(path)
        config_scopes.append(
            {
                "scope": layer_scope,
                "config_path": str(path),
                "exists": path.is_file(),
                "configured": configured,
                "status": "healthy" if configured else "missing",
            }
        )

    configured_layers = [layer for layer in config_scopes if layer["configured"]]
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
    return {
        "mcp_installed": bool(configured_layers),
        "mcp_status": "healthy" if configured_layers else "missing",
        "mcp_registration": "local",
        "mcp_config_path": user_path if scope == "auto" else effective_path,
        "effective_mcp_config_path": effective_path,
        "config_scopes": config_scopes,
    }


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
    if ide_type == "pi":
        return verify_pi_mcp_extension(scope=scope, project_dir=project_dir)

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

    try:
        raw = config_path.read_text(encoding="utf-8")
        if ide_type != "codex" and config_path.suffix == ".jsonc":
            raw = _strip_jsonc_comments(raw)
        if ide_type == "codex":
            config = _load_toml_text(raw)
            servers = config.get("mcp_servers", {})
        else:
            config = json.loads(raw) if raw.strip() else {}
            if not isinstance(config, dict):
                base["mcp_status"] = "invalid"
                return base
            servers = config.get(mcp_ide["config_key"], {})
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        base["mcp_status"] = "invalid"
        return base

    if not isinstance(servers, dict):
        base["mcp_status"] = "invalid"
        return base

    entry = servers.get("ai-guardian")
    if not isinstance(entry, dict):
        return base
    if entry.get("enabled") is False:
        base["mcp_status"] = "disabled"
        return base

    base["mcp_installed"] = True
    base["mcp_status"] = "healthy"
    return base


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
    """Return whether Codex has an enabled AI Guardian MCP server."""
    path = config_path or get_codex_mcp_config_path()
    if not path.is_file():
        return False

    try:
        data = _load_toml_text(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Unable to read Codex MCP config %s: %s", path, exc)
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
    scope: str = "user",
    project_dir: Optional[str] = None,
) -> None:
    """Install or remove MCP server config for an IDE."""
    if no_mcp:
        _remove_mcp_config(
            setup, ide_type, dry_run, scope=scope, project_dir=project_dir
        )
    else:
        _install_mcp_config(
            setup, ide_type, dry_run, scope=scope, project_dir=project_dir
        )


def _install_mcp_config(
    setup,
    ide_type: str,
    dry_run: bool = False,
    scope: str = "user",
    project_dir: Optional[str] = None,
) -> None:
    """Add MCP server entry to IDE config and enable in ai-guardian config."""
    mcp_ide = _MCP_IDE_CONFIGS.get(ide_type)
    if not mcp_ide:
        return

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
        return

    if ide_type == "cursor":
        if project_dir and scope == "user":
            scope = "project"
        if scope not in ("user", "project"):
            logger.warning("Cursor MCP setup scope must be 'user' or 'project'")
            return
        if scope == "project":
            if not project_dir:
                logger.warning("Cursor project MCP setup requires a project directory")
                return
            project_path = Path(project_dir).expanduser()
            if not project_path.is_dir():
                logger.warning(
                    "Cursor project MCP directory does not exist or is not a "
                    "directory: %s",
                    project_path,
                )
                return
            project_dir = str(project_path.resolve())
            print(
                "  MCP: Cursor Cloud MCP is managed by the Cursor dashboard/team "
                "settings or Cloud Agents API; project .cursor/mcp.json was "
                "left unchanged"
            )
            return
        else:
            project_dir = None

    config_path = get_mcp_config_path(ide_type, scope=scope, project_dir=project_dir)
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
            with open(config_path, "r", encoding="utf-8") as f:
                raw = f.read()
            if config_path.suffix == ".jsonc":
                raw = _strip_jsonc_comments(raw)
            if raw.strip():
                config = json.loads(raw)
        except (json.JSONDecodeError, OSError) as e:
            # Never replace a non-empty user config that cannot be parsed.
            logger.warning("Failed to read MCP config %s: %s", config_path, e)
            return

    if not isinstance(config, dict):
        logger.warning("MCP config %s must contain a JSON object", config_path)
        return

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
        if ide_type == "cursor":
            mcp_entry["type"] = "stdio"

    if key not in config:
        config[key] = {}
    config[key]["ai-guardian"] = mcp_entry

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"  MCP: Added ai-guardian MCP server to {config_path}")
    _register_mcp_identity(abs_path)

    # Warn if MCP entry exists in settings.json (hooks file) for Claude
    if ide_type == "claude":
        raw_settings_path = resolve_ide_config_path(
            "claude", "~/.claude/settings.json", filename="settings.json"
        )
        if raw_settings_path is None:
            return
        settings_path = Path(raw_settings_path).expanduser()
        try:
            if settings_path.exists():
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                if "ai-guardian" in settings.get("mcpServers", {}):
                    print(
                        "  MCP: Warning: ai-guardian MCP entry found in "
                        f"{settings_path} (hooks file).\n"
                        f"  MCP servers should be in {config_path}. "
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
    _register_mcp_identity(_resolve_binary_path())
    _clean_legacy_codex_mcp_entry(target_path=config_path)


def _remove_mcp_config(
    setup,
    ide_type: str,
    dry_run: bool = False,
    scope: str = "user",
    project_dir: Optional[str] = None,
) -> None:
    """Remove MCP server entry from IDE config."""
    mcp_ide = _MCP_IDE_CONFIGS.get(ide_type)
    if not mcp_ide:
        return

    if ide_type == "pi":
        if dry_run:
            print(
                "  MCP: Would leave Pi's managed extension in place; "
                "no native MCP file exists"
            )
        else:
            print(
                "  MCP: Pi has no native MCP file; the managed extension remains "
                "for hook protection"
            )
        return

    if ide_type == "cursor":
        if project_dir and scope == "user":
            scope = "project"
        if scope == "project":
            print(
                "  MCP: Cursor Cloud MCP is managed by the Cursor dashboard/team "
                "settings or Cloud Agents API; no project MCP file was changed"
            )
            return

    config_path = get_mcp_config_path(ide_type, scope=scope, project_dir=project_dir)
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
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    key = mcp_ide["config_key"]
    if key in config and "ai-guardian" in config[key]:
        del config[key]["ai-guardian"]
        if not config[key]:
            del config[key]
        with open(config_path, "w", encoding="utf-8") as f:
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
            config_path.write_text(updated, encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write Codex MCP config %s: %s", config_path, exc)
            return
        print(f"  MCP: Removed ai-guardian MCP server from {config_path}")
    else:
        print("  MCP: ai-guardian MCP server not found in config")

    _clean_legacy_codex_mcp_entry()
