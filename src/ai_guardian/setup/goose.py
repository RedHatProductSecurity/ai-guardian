"""Install and inspect the owned Goose Open Plugins command-hook plugin.

Never change Goose's plugin enablement settings, config.yaml, or another
plugin. Project selection is explicit; auto scope is read-only discovery.
"""

import json
import logging
import os
import platform
import shlex
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ai_guardian.constants import GOOSE_MANAGED_HOOK_EVENTS
from ai_guardian.goose_support import (
    GOOSE_PLUGIN_NAME,
    goose_config_dir,
    goose_hook_path,
    goose_user_settings_path,
)
from ai_guardian.setup.utils import _load_cli_config, _resolve_binary_path

MANAGED_MARKER = "ai-guardian-goose-command-hooks"
logger = logging.getLogger(__name__)


def expected_hooks() -> Dict[str, Any]:
    command = f"{shlex.quote(_resolve_binary_path())} --ide goose"
    return {
        event: [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "timeout": 360 if event == "PreToolUse" else 60,
                        **({"on_failure": "block"} if event == "PreToolUse" else {}),
                    }
                ]
            }
        ]
        for event in GOOSE_MANAGED_HOOK_EVENTS
    }


def _load(path: Path) -> Dict[str, Any]:
    config, error = _load_cli_config(path)
    if error:
        # Do not echo config contents in errors or diagnostics.
        logger.warning("Goose configuration is unreadable or malformed")
        raise ValueError("Goose configuration is unreadable or malformed")
    return config if config is not None else {}


def _owned_action(action: Any) -> bool:
    if (
        not isinstance(action, dict)
        or action.get("type") not in (None, "command")
        or not isinstance(action.get("command"), str)
    ):
        return False
    try:
        args = shlex.split(action["command"])
    except ValueError:
        return False
    return bool(
        args and Path(args[0]).name == "ai-guardian" and args[1:] == ["--ide", "goose"]
    )


def _clean_hooks(
    config: Dict[str, Any], *, remove_owned: bool = True
) -> Dict[str, Any]:
    cleaned = deepcopy(config)
    hooks = cleaned.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Goose hooks must be an object")
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            raise ValueError("Goose hook events must contain rule lists")
        remaining = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError("Goose hook rules must contain action lists")
            actions = group["hooks"]
            retained = [
                action
                for action in actions
                if not (remove_owned and _owned_action(action))
            ]
            if retained or not actions:
                if group.get("matcher") is not None and not isinstance(
                    group["matcher"], str
                ):
                    raise ValueError("Goose hook matcher must be a string")
                for action in retained:
                    if not isinstance(action, dict):
                        raise ValueError("Goose hook actions must be objects")
                    action_type = action.get("type")
                    if action_type is not None and not isinstance(action_type, str):
                        raise ValueError("Goose hook action type must be a string")
                    if (
                        action_type not in (None, "command")
                        or action.get("command") is None
                    ):
                        # Goose ignores unsupported actions and absent commands.
                        continue
                    if not isinstance(action["command"], str):
                        raise ValueError("Goose hook command must be a string")
                    timeout = action.get("timeout")
                    if timeout is not None and (
                        type(timeout) is not int or not 0 <= timeout < 2**64
                    ):
                        raise ValueError(
                            "Goose hook timeout must be an unsigned integer"
                        )
                    if (
                        event == "PreToolUse"
                        and "on_failure" in action
                        and action["on_failure"] not in ("allow", "block")
                    ):
                        raise ValueError(
                            "Goose pre-tool hook failure policy is malformed"
                        )
                remaining.append({**group, "hooks": retained})
        if remaining:
            hooks[event] = remaining
        else:
            del hooks[event]
    return cleaned


def _disabled_reason(path: Path, project_dir: Optional[str]) -> Optional[str]:
    config = _load(goose_config_dir() / "config.yaml")
    plugins = config.get("plugins", {})
    if not isinstance(plugins, dict):
        return "Goose plugin enablement configuration is malformed"
    entry = plugins.get(str(path.parent.parent), {})
    if not isinstance(entry, dict):
        return "Goose plugin enablement entry is malformed"
    if entry.get("enabled") is False:
        return "Goose plugin is disabled in user configuration"
    if "enabled" in entry and not isinstance(entry["enabled"], bool):
        return "Goose plugin enablement entry is malformed"
    if os.environ.get("PLUGINS"):
        return "Goose environment plugin override cannot be verified"
    paths = [goose_user_settings_path()]
    if project_dir:
        project_settings = Path(project_dir).expanduser() / ".config/goose"
        paths.extend(
            [
                project_settings / "settings.json",
                project_settings / "settings.local.json",
            ]
        )
    # Local settings override project settings, which override user settings.
    settings_layers = [_load(settings_path) for settings_path in paths]
    for settings in reversed(settings_layers):
        disabled = settings.get("disabledPlugins", [])
        enabled = settings.get("enabledPlugins", [])
        if (
            not isinstance(disabled, list)
            or not isinstance(enabled, list)
            or not all(isinstance(name, str) for name in [*disabled, *enabled])
        ):
            return "Goose plugin settings are malformed"
        if GOOSE_PLUGIN_NAME in disabled:
            return "Goose plugin is disabled in effective plugin settings"
        if GOOSE_PLUGIN_NAME in enabled:
            break
    return None


def _check_manifest_location(root: Path) -> None:
    # Goose reads these ahead of plugin.json. Do not create a second manifest
    # which would silently be ignored, or overwrite an existing user manifest.
    if any(
        (root / relative).exists()
        for relative in (
            ".goose-plugin/plugin.json",
            ".plugin/plugin.json",
        )
    ):
        raise ValueError("Goose plugin has an unmanaged overriding manifest")
    if any(
        target.is_symlink()
        for target in (
            root,
            root / "hooks",
            root / "hooks/hooks.json",
            root / "plugin.json",
        )
    ):
        raise ValueError("Goose managed plugin paths must not be symbolic links")


def validate_goose_mcp_target(path: Path) -> None:
    """Only write/verify our default MCP file, not a linked/custom plugin layout."""
    root = path.parent
    _check_manifest_location(root)
    if path.is_symlink():
        raise ValueError("Goose managed MCP path must not be a symbolic link")
    manifest = _load(root / "plugin.json")
    if (
        manifest.get("name") != GOOSE_PLUGIN_NAME
        or manifest.get("_ai_guardian_managed") != MANAGED_MARKER
    ):
        raise ValueError("Goose managed plugin manifest is missing or changed")
    if manifest.get("mcpServers") is not None:
        # Custom/exclusive/inline configurations can shadow the default file.
        # Do not rewrite them or claim to have verified their merged behavior.
        raise ValueError("Custom Goose manifest MCP configuration cannot be verified")


def verify_goose_hooks(
    scope: str = "user", project_dir: Optional[str] = None
) -> Dict[str, Any]:
    workspace = str(Path(project_dir or Path.cwd()).expanduser().resolve())
    path = goose_hook_path(scope, project_dir)
    layers = [goose_hook_path("user"), goose_hook_path("project", workspace)]
    auto_scope = scope == "auto"
    if auto_scope:
        scope = "user"
    if auto_scope and layers[1].parent.parent.is_dir():
        # Project plugins win by name; a malformed project plugin must not
        # silently inherit the user's healthy state.
        path = layers[1]
        scope = "project"
        try:
            # Goose removes config-disabled candidates before deduplicating
            # names. A disabled project copy does not shadow an enabled user copy.
            if (
                _disabled_reason(path, workspace)
                == "Goose plugin is disabled in user configuration"
            ):
                path = layers[0]
                scope = "user"
        except (OSError, ValueError):
            # Validation below reports the actual unhealthy configuration.
            logger.debug("Unable to determine effective Goose plugin enablement")
    result: Dict[str, Any] = {
        "ide": "goose",
        "config_path": str(path),
        "scope": scope,
        "healthy": False,
        "events": {},
        "obsolete": [],
        "diagnostics": [],
        "config_layers": [
            {"path": str(layer), "exists": layer.is_file()} for layer in layers
        ],
    }
    if platform.system() == "Windows":
        result["diagnostics"].append(
            "Goose command hooks require POSIX sh; native Windows is not qualified"
        )
    try:
        _check_manifest_location(path.parent.parent)
        config = _load(path)
        hooks = config.get("hooks", {})
        _clean_hooks(config, remove_owned=False)  # Validate before claiming health.
        expected = expected_hooks()
        for event in GOOSE_MANAGED_HOOK_EVENTS:
            groups = hooks.get(event, [])
            if not groups:
                status = "missing"
            elif expected[event][0] in groups:
                status = "healthy"
            else:
                status = "changed"
            result["events"][event] = status
        result["obsolete"] = [
            event
            for event, groups in hooks.items()
            if event not in expected
            and any(
                _owned_action(action) for group in groups for action in group["hooks"]
            )
        ]
        manifest = _load(path.parent.parent / "plugin.json")
        if (
            manifest.get("name") != GOOSE_PLUGIN_NAME
            or manifest.get("_ai_guardian_managed") != MANAGED_MARKER
        ):
            result["diagnostics"].append(
                "Goose managed plugin manifest is missing or changed"
            )
        disabled = _disabled_reason(path, workspace)
        if disabled:
            result["diagnostics"].append(disabled)
    except (OSError, ValueError):
        result["diagnostics"].append(
            "Goose plugin configuration is unreadable or malformed"
        )
    result["healthy"] = (
        bool(result["events"])
        and all(status == "healthy" for status in result["events"].values())
        and not result["diagnostics"]
        and not result["obsolete"]
    )
    return result


def setup_goose_hooks(setup, path: Path, dry_run: bool = False) -> Tuple[bool, str]:
    if platform.system() == "Windows":
        return (
            False,
            "Goose command hooks require POSIX sh; native Windows is not qualified",
        )
    try:
        from ai_guardian import __version__

        manifest_path = path.parent.parent / "plugin.json"
        _check_manifest_location(path.parent.parent)
        manifest = _load(manifest_path)
        existing = _load(path)
        if manifest and (
            manifest.get("name") != GOOSE_PLUGIN_NAME
            or manifest.get("_ai_guardian_managed") != MANAGED_MARKER
        ):
            return False, "Refusing to replace a user-owned Goose plugin manifest"
        if not manifest and path.parent.parent.exists():
            groups = existing.get("hooks", {})
            if not isinstance(groups, dict) or not any(
                _owned_action(action)
                for entries in groups.values()
                if isinstance(entries, list)
                for group in entries
                if isinstance(group, dict)
                if isinstance(group.get("hooks"), list)
                for action in group["hooks"]
            ):
                return (
                    False,
                    "Refusing to replace an unrecognized Goose plugin directory",
                )
        merged = _clean_hooks(existing)
        for event, groups in expected_hooks().items():
            merged["hooks"][event] = groups + merged["hooks"].get(event, [])
        manifest.update(
            {
                "name": GOOSE_PLUGIN_NAME,
                "version": __version__,
                "description": "AI Guardian Goose pre-tool enforcement and lifecycle observation",
                "_ai_guardian_managed": MANAGED_MARKER,
            }
        )
        changes = [
            (target, value)
            for target, value in ((path, merged), (manifest_path, manifest))
            if _load(target) != value
        ]
        if dry_run:
            return (
                True,
                f"[DRY RUN] Would configure Goose plugin at {path.parent.parent}",
            )
        for target, _ in changes:
            ok, _, error = setup._backup_before_write(
                target, operation="Goose plugin setup"
            )
            if not ok:
                return False, error or "Unable to back up Goose plugin configuration"
        for target, value in changes:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        return (
            True,
            f"Goose plugin configured at {path.parent.parent}; restart Goose. Only PreToolUse enforces decisions.",
        )
    except (OSError, ValueError):
        logger.warning("Goose plugin setup could not complete")
        return (
            False,
            "Goose setup stopped: plugin configuration is unreadable, malformed, or unwritable",
        )
