"""
Tray menu plugin loader, command utilities, and plugin menu building.

Loads plugin definitions from JSON files in the tray-plugins directory.
Each daemon reads its own plugins and serves them via the REST API.
Plugin command execution and menu slot constants also live here
(split from tray.py, Issue #1492).
"""

import json
import logging
import os
import platform
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


_PARAM_TYPES = frozenset(
    {
        "string",
        "int",
        "number",
        "boolean",
        "choice",
        "combobox",
        "path-file",
        "path-dir",
    }
)


@dataclass
class PluginParam:
    """Parameter definition for a plugin menu item."""

    name: str
    hint: str = ""
    default: str = ""
    options: Optional[List[str]] = None
    type: str = "string"
    required: bool = True
    pattern: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None


_TARGET_MODES = frozenset({"select", "all", "containers"})


@dataclass
class PluginItem:
    """Menu item within a plugin.

    An item is either a **command item** (has ``command``) or a
    **submenu item** (has ``items`` children or ``import_file``).
    """

    label: str
    command: Union[str, Dict[str, str], None] = None
    type: str = "terminal"
    run_on_target: bool = False
    target: Optional[str] = None
    params: List[PluginParam] = field(default_factory=list)
    items: Optional[List["PluginItem"]] = None
    import_file: Optional[str] = None


@dataclass
class Plugin:
    """Plugin definition with name and menu items."""

    name: str
    items: List[PluginItem] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    scope: str = "daemon"
    id: Optional[str] = None

    @property
    def dedup_key(self) -> str:
        """Deduplication key: ``id`` if set, otherwise ``name``."""
        return self.id if self.id else self.name


def load_plugins(
    plugins_dir: Optional[Path] = None,
    daemon_tags: Optional[List[str]] = None,
) -> List[Plugin]:
    """Load all plugin JSON files from the plugins directory.

    After parsing, ``import`` references are resolved and circular
    imports are detected.

    Args:
        plugins_dir: Directory to scan. Defaults to get_tray_plugins_dir().
        daemon_tags: Daemon tags for filtering imported files.

    Returns:
        List of validated Plugin objects. Malformed files are skipped.
    """
    if plugins_dir is None:
        from ai_guardian.daemon import get_tray_plugins_dir

        plugins_dir = get_tray_plugins_dir()

    if not plugins_dir.is_dir():
        return []

    plugins = []
    for path in sorted(plugins_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping malformed plugin file %s: %s", path.name, e)
            continue

        plugin = _parse_plugin(data, path.name)
        if plugin is not None:
            visited = {str(path.resolve())}
            plugin.items = _resolve_imports(
                plugin.items,
                plugins_dir,
                daemon_tags,
                visited,
            )
            if plugin.items:
                plugins.append(plugin)

    return plugins


def find_project_plugins_dir(
    working_dir: Optional[str] = None,
) -> Optional[Path]:
    """Find project-level tray plugins directory by walking upward.

    Starting from *working_dir*, walks up the directory tree looking for
    ``.ai-guardian/tray-plugins/``.  Stops at the filesystem root.

    Args:
        working_dir: Starting directory.  When ``None``, returns ``None``
            immediately (no project context).

    Returns:
        Path to the project plugins directory, or ``None`` if not found.
    """
    if not working_dir:
        return None

    current = Path(working_dir).resolve()
    while True:
        candidate = current / ".ai-guardian" / "tray-plugins"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _get_bundled_plugins_dir() -> Optional[Path]:
    """Return the path to bundled default plugin templates in the package."""
    try:
        from importlib.resources import files

        d = Path(str(files("ai_guardian") / "templates" / "tray-plugins"))
        return d if d.is_dir() else None
    except Exception:
        return None


_HAS_WEB_CONSOLE = sys.version_info >= (3, 10)


def _load_bundled_plugins(
    daemon_tags: Optional[List[str]] = None,
) -> List[Plugin]:
    """Load bundled default plugins, selecting the right console variant.

    Files named ``*-web.json`` are loaded on Python >= 3.10 (web console).
    Files named ``*-tui.json`` are loaded on Python < 3.10 (TUI fallback).
    Files without a ``-web`` or ``-tui`` suffix are always loaded.
    """
    bundled_dir = _get_bundled_plugins_dir()
    if bundled_dir is None or not bundled_dir.is_dir():
        return []

    skip_suffix = "-tui.json" if _HAS_WEB_CONSOLE else "-web.json"

    plugins = []
    for path in sorted(bundled_dir.glob("*.json")):
        if path.name.endswith(skip_suffix):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping bundled plugin %s: %s", path.name, e)
            continue
        plugin = _parse_plugin(data, path.name)
        if plugin is not None:
            if plugin.items:
                plugins.append(plugin)

    return plugins


def load_merged_plugins(
    working_dir: Optional[str] = None,
    daemon_tags: Optional[List[str]] = None,
) -> List[Plugin]:
    """Load plugins from bundled, user-level, and project-level directories.

    Merge order (higher priority wins by plugin name):
      1. Bundled defaults (shipped with the package)
      2. User-level (``~/.config/ai-guardian/tray-plugins/``)
      3. Project-level (``.ai-guardian/tray-plugins/``)

    Import references in each source resolve relative to their own
    directory.

    Args:
        working_dir: Daemon's working directory for project root detection.
        daemon_tags: Daemon tags for filtering imported files.

    Returns:
        Merged list of Plugin objects.
    """
    from ai_guardian.daemon import get_tray_plugins_dir

    bundled_plugins = _load_bundled_plugins(daemon_tags)

    user_plugins = load_plugins(get_tray_plugins_dir(), daemon_tags)

    project_dir = find_project_plugins_dir(working_dir)
    project_plugins = load_plugins(project_dir, daemon_tags) if project_dir else []

    merged: List[Plugin] = []
    seen_keys: set = set()

    for layer in (project_plugins, user_plugins, bundled_plugins):
        for p in layer:
            key = p.dedup_key
            if key not in seen_keys:
                merged.append(p)
                seen_keys.add(key)

    return merged


def _parse_plugin(data: dict, filename: str) -> Optional[Plugin]:
    """Parse and validate a plugin dict from a JSON file."""
    if not isinstance(data, dict):
        logger.warning("Skipping %s: expected JSON object", filename)
        return None

    name = data.get("name")
    if not name or not isinstance(name, str):
        logger.warning("Skipping %s: missing or invalid 'name'", filename)
        return None

    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        logger.warning("Skipping %s: missing or invalid 'items'", filename)
        return None

    items = []
    for i, raw_item in enumerate(raw_items):
        item = _parse_item(raw_item, filename, i)
        if item is not None:
            items.append(item)

    if not items:
        logger.warning("Skipping %s: no valid items", filename)
        return None

    tags = []
    raw_tags = data.get("tags")
    if isinstance(raw_tags, list):
        tags = [t for t in raw_tags if isinstance(t, str) and t]

    scope = data.get("scope", "daemon")
    if scope not in ("daemon", "global"):
        scope = "daemon"

    plugin_id = data.get("id")
    if plugin_id is not None and (not isinstance(plugin_id, str) or not plugin_id):
        plugin_id = None

    return Plugin(name=name, items=items, tags=tags, scope=scope, id=plugin_id)


def _parse_item(raw: dict, filename: str, index: int) -> Optional[PluginItem]:
    """Parse and validate a single plugin item.

    An item is one of:
    - **command item**: has ``command`` (string or platform map)
    - **inline submenu**: has ``items`` (list of child items)
    - **import submenu**: has ``import`` (filename in tray-plugins/)
    """
    if not isinstance(raw, dict):
        logger.warning("Skipping item %d in %s: not a dict", index, filename)
        return None

    label = raw.get("label")
    if not label or not isinstance(label, str):
        logger.warning("Skipping item %d in %s: missing 'label'", index, filename)
        return None

    command = raw.get("command")
    raw_items = raw.get("items")
    import_ref = raw.get("import")

    has_command = command is not None
    has_items = isinstance(raw_items, list)
    has_import = bool(isinstance(import_ref, str) and import_ref)

    kind_count = sum([has_command, has_items, has_import])
    if kind_count == 0:
        logger.warning(
            "Skipping item %d in %s: must have 'command', 'items', or 'import'",
            index,
            filename,
        )
        return None
    if kind_count > 1:
        logger.warning(
            "Skipping item %d in %s: 'command', 'items', and 'import' are mutually exclusive",
            index,
            filename,
        )
        return None

    if has_items:
        children = []
        for ci, child_raw in enumerate(raw_items):
            child = _parse_item(child_raw, filename, ci)
            if child is not None:
                children.append(child)
        if not children:
            logger.warning(
                "Skipping item %d in %s: no valid child items", index, filename
            )
            return None
        return PluginItem(label=label, items=children)

    if has_import:
        return PluginItem(label=label, import_file=import_ref)

    if not isinstance(command, (str, dict)):
        logger.warning(
            "Skipping item %d in %s: 'command' must be string or object",
            index,
            filename,
        )
        return None

    item_type = raw.get("type", "terminal")
    if item_type not in (
        "terminal",
        "background",
        "notification",
        "clipboard",
        "modal",
    ):
        item_type = "terminal"

    params = []
    for raw_param in raw.get("params", []):
        param = _parse_param(raw_param)
        if param is not None:
            params.append(param)

    run_on_target = bool(raw.get("run_on_target", False))

    target_mode = raw.get("target")
    if target_mode is not None and target_mode not in _TARGET_MODES:
        logger.warning(
            "Ignoring invalid target '%s' in item %d of %s",
            target_mode,
            index,
            filename,
        )
        target_mode = None

    return PluginItem(
        label=label,
        command=command,
        type=item_type,
        run_on_target=run_on_target,
        target=target_mode,
        params=params,
    )


def _parse_param(raw: dict) -> Optional[PluginParam]:
    """Parse a single parameter definition."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not name or not isinstance(name, str):
        return None

    options = raw.get("options") if isinstance(raw.get("options"), list) else None

    param_type = raw.get("type", "string")
    if param_type not in _PARAM_TYPES:
        param_type = "string"
    if options and param_type == "string" and "type" not in raw:
        param_type = "choice"

    required = raw.get("required", True)
    if not isinstance(required, bool):
        required = True

    pattern = raw.get("pattern")
    if not isinstance(pattern, str):
        pattern = None

    p_min = raw.get("min")
    p_max = raw.get("max")
    try:
        p_min = float(p_min) if p_min is not None else None
    except (TypeError, ValueError):
        p_min = None
    try:
        p_max = float(p_max) if p_max is not None else None
    except (TypeError, ValueError):
        p_max = None

    return PluginParam(
        name=name,
        hint=raw.get("hint", ""),
        default=str(raw.get("default", "")),
        options=options,
        type=param_type,
        required=required,
        pattern=pattern,
        min=p_min,
        max=p_max,
    )


def _resolve_imports(
    items: List[PluginItem],
    plugins_dir: Path,
    daemon_tags: Optional[List[str]] = None,
    visited: Optional[Set[str]] = None,
) -> List[PluginItem]:
    """Resolve ``import_file`` references in a list of plugin items.

    Walks the item tree, replacing import references with loaded children.
    Detects circular imports via a visited set.

    Args:
        items: Items to resolve (modified in-place).
        plugins_dir: Directory containing plugin JSON files.
        daemon_tags: Tags for filtering imported files.
        visited: Paths already being processed (circular detection).

    Returns:
        The items list with imports resolved. Items whose imports fail
        are removed.
    """
    if visited is None:
        visited = set()

    resolved: List[PluginItem] = []
    for item in items:
        if item.import_file:
            import_path = (plugins_dir / item.import_file).resolve()
            resolved_dir = str(plugins_dir.resolve()) + os.sep
            if not str(import_path).startswith(resolved_dir):
                logger.warning(
                    "Import path escapes plugins directory: %s",
                    item.import_file,
                )
                continue
            path_key = str(import_path)

            if path_key in visited:
                logger.warning(
                    "Circular import detected: %s",
                    item.import_file,
                )
                continue

            if not import_path.is_file():
                logger.warning(
                    "Import file not found: %s",
                    item.import_file,
                )
                continue

            try:
                data = json.loads(import_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    "Skipping import %s: %s",
                    item.import_file,
                    e,
                )
                continue

            if not isinstance(data, dict):
                logger.warning(
                    "Skipping import %s: expected JSON object",
                    item.import_file,
                )
                continue

            import_tags = data.get("tags")
            if isinstance(import_tags, list) and import_tags:
                daemon_set = set(daemon_tags) if daemon_tags else set()
                if not daemon_set or not daemon_set.intersection(import_tags):
                    continue

            raw_items = data.get("items")
            if not isinstance(raw_items, list) or not raw_items:
                logger.warning(
                    "Skipping import %s: missing or empty 'items'",
                    item.import_file,
                )
                continue

            children = []
            for ci, child_raw in enumerate(raw_items):
                child = _parse_item(child_raw, item.import_file, ci)
                if child is not None:
                    children.append(child)

            if not children:
                continue

            visited.add(path_key)
            children = _resolve_imports(children, plugins_dir, daemon_tags, visited)
            visited.discard(path_key)

            item.items = children
            item.import_file = None
            resolved.append(item)

        elif item.items:
            item.items = _resolve_imports(
                item.items,
                plugins_dir,
                daemon_tags,
                visited,
            )
            if item.items:
                resolved.append(item)
        else:
            resolved.append(item)

    return resolved


def check_circular_imports(
    plugins_dir: Path,
) -> List[str]:
    """Check for circular imports in plugin files without modifying anything.

    Returns:
        List of warning messages for any circular imports found.
    """
    warnings: List[str] = []

    if not plugins_dir.is_dir():
        return warnings

    for path in sorted(plugins_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            continue

        _check_import_chain(
            raw_items,
            plugins_dir,
            {str(path.resolve())},
            path.name,
            warnings,
        )

    return warnings


def _check_import_chain(
    raw_items: list,
    plugins_dir: Path,
    visited: Set[str],
    origin: str,
    warnings: List[str],
) -> None:
    """Recursively walk items looking for circular import chains."""
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        import_ref = raw.get("import")
        if not isinstance(import_ref, str) or not import_ref:
            child_items = raw.get("items")
            if isinstance(child_items, list):
                _check_import_chain(child_items, plugins_dir, visited, origin, warnings)
            continue

        import_path = (plugins_dir / import_ref).resolve()
        path_key = str(import_path)

        if path_key in visited:
            warnings.append(f"{origin} -> {import_ref}")
            continue

        if not import_path.is_file():
            continue

        try:
            data = json.loads(import_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        child_items = data.get("items")
        if not isinstance(child_items, list):
            continue

        visited.add(path_key)
        _check_import_chain(child_items, plugins_dir, visited, origin, warnings)
        visited.discard(path_key)


def filter_plugins_by_tags(
    plugins: List[Plugin],
    daemon_tags: Optional[List[str]] = None,
) -> List[Plugin]:
    """Filter plugins based on tag matching with daemon menu_tags.

    Args:
        plugins: All loaded plugins.
        daemon_tags: Tags configured on the daemon (menu_tags).

    Returns:
        Plugins that match the daemon's tags.
    """
    daemon_set = set(daemon_tags) if daemon_tags else set()
    result = []
    for p in plugins:
        if not p.tags:
            result.append(p)
        elif daemon_set and daemon_set.intersection(p.tags):
            result.append(p)
    return result


def resolve_command(command: Union[str, Dict[str, str]]) -> Optional[str]:
    """Resolve a command spec to a platform-specific string.

    Args:
        command: Either a plain command string or a platform map dict
            with keys like "darwin", "linux", "windows", "default".

    Returns:
        Resolved command string, or None if no match for this platform.
    """
    if isinstance(command, str):
        return command
    if not isinstance(command, dict):
        return None
    system = platform.system().lower()
    if system in command:
        return command[system]
    return command.get("default")


PARAM_PREFIX = "tray."


def substitute_params(template: str, values: Dict[str, str]) -> str:
    """Substitute {tray.param} placeholders in a command template.

    Uses the ``{tray.name}`` namespace to avoid collisions with shell
    variables (``$name``/``${name}``) and other brace patterns in commands.

    Args:
        template: Command string with {tray.name} placeholders.
        values: Mapping of parameter names to values.

    Returns:
        Command with placeholders replaced. Unmatched {tray.*} become empty.
        Non-tray braces like {json} are left untouched.
    """
    result = template
    for key, val in values.items():
        result = result.replace("{" + PARAM_PREFIX + key + "}", val)
    result = re.sub(r"\{" + re.escape(PARAM_PREFIX) + r"(\w+)\}", "", result)
    return result


def validate_param_value(param: PluginParam, value: str) -> Tuple[bool, str]:
    """Validate a parameter value against its type and constraints.

    Returns:
        (is_valid, error_message) — error_message is empty on success.
    """
    if not value and param.required:
        return False, f"'{param.name}' is required"
    if not value:
        return True, ""

    ptype = param.type

    if ptype == "int":
        try:
            n = int(value)
        except ValueError:
            return False, f"'{param.name}' must be an integer"
        if param.min is not None and n < param.min:
            return False, f"'{param.name}' must be >= {param.min:g}"
        if param.max is not None and n > param.max:
            return False, f"'{param.name}' must be <= {param.max:g}"

    elif ptype == "number":
        try:
            n = float(value)
        except ValueError:
            return False, f"'{param.name}' must be a number"
        if param.min is not None and n < param.min:
            return False, f"'{param.name}' must be >= {param.min:g}"
        if param.max is not None and n > param.max:
            return False, f"'{param.name}' must be <= {param.max:g}"

    elif ptype == "boolean":
        if value.lower() not in ("true", "false"):
            return False, f"'{param.name}' must be true or false"

    elif ptype == "choice":
        if param.options and value not in param.options:
            return False, f"'{param.name}' must be one of: {', '.join(param.options)}"

    elif ptype == "string" and param.pattern:
        if not re.fullmatch(param.pattern, value):
            return False, f"'{param.name}' does not match pattern {param.pattern}"

    return True, ""


_TARGET_VARS = frozenset(
    {
        "container_id",
        "container_engine",
        "container_name",
        "host",
        "port",
        "name",
        "pod_name",
        "namespace",
        "working_dir",
    }
)


def substitute_target_vars(template: str, target) -> str:
    """Substitute built-in ``{variable}`` placeholders from a DaemonTarget.

    Target variables use bare names (e.g., ``{container_id}``) without a
    namespace prefix.  They cannot collide with the ``{tray.*}`` user-param
    namespace.

    Args:
        template: Command string with ``{variable}`` placeholders.
        target: A ``DaemonTarget`` instance, or ``None`` for no substitution.

    Returns:
        Command with known target placeholders replaced.  Unknown bare
        ``{name}`` patterns are left untouched.
    """
    if target is None:
        return template
    result = template
    for var_name in _TARGET_VARS:
        placeholder = "{" + var_name + "}"
        if placeholder in result:
            value = getattr(target, var_name, None)
            safe_value = shlex.quote(str(value)) if value is not None else ""
            result = result.replace(placeholder, safe_value)
    return result


_SHELL_OPERATORS = ("&&", "||", "|", ";", ">>", "<<", ">", "<")


def _needs_shell(command_str: str) -> bool:
    """Return True if *command_str* contains shell operators."""
    return any(op in command_str for op in _SHELL_OPERATORS)


def wrap_for_target(cmd_parts: list, target, interactive: bool = True) -> list:
    """Wrap command parts for execution on a DaemonTarget's runtime.

    Args:
        cmd_parts: The command as a list of strings (already shlex-split).
        target: A ``DaemonTarget`` instance.
        interactive: Whether to include ``-it`` flags (True for terminal type).

    Returns:
        Wrapped command parts.  For local runtime, returns *cmd_parts*
        unchanged.
    """
    import shutil

    runtime = target.runtime if target else "local"

    if runtime == "container":
        engine = target.container_engine or "podman"
        cid = target.container_id or ""
        if not cid or not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$", cid):
            logger.warning("run_on_target: invalid container_id, running locally")
            return cmd_parts
        flags = ["-it"] if interactive else []
        return [engine, "exec"] + flags + [cid] + cmd_parts

    if runtime == "kubernetes":
        pod = target.pod_name or ""
        ns = target.namespace or "default"
        if not pod or not re.match(r"^[a-z0-9][a-z0-9.-]{0,252}$", pod):
            logger.warning("run_on_target: invalid pod_name, running locally")
            return cmd_parts
        kube_cli = "oc" if shutil.which("oc") else "kubectl"
        flags = ["-it"] if interactive else []
        return [kube_cli, "exec"] + flags + [pod, "-n", ns, "--"] + cmd_parts

    return cmd_parts


def plugins_to_dict(plugins: List[Plugin]) -> dict:
    """Serialize a list of plugins to a JSON-serializable dict.

    Returns:
        Dict with "plugins" key containing list of plugin dicts.
    """
    result_plugins = []
    for p in plugins:
        d = {
            "name": p.name,
            "items": [_item_to_dict(item) for item in p.items],
        }
        if p.id:
            d["id"] = p.id
        if p.tags:
            d["tags"] = list(p.tags)
        if p.scope != "daemon":
            d["scope"] = p.scope
        result_plugins.append(d)
    return {"plugins": result_plugins}


def _item_to_dict(item: PluginItem) -> dict:
    """Serialize a PluginItem to a dict."""
    d: dict = {"label": item.label}

    if item.import_file:
        d["import"] = item.import_file
        return d

    if item.items is not None:
        d["items"] = [_item_to_dict(child) for child in item.items]
        return d

    d["command"] = item.command
    d["type"] = item.type
    if item.run_on_target:
        d["run_on_target"] = True
    if item.target:
        d["target"] = item.target
    if item.params:
        d["params"] = [_param_to_dict(p) for p in item.params]
    return d


def _param_to_dict(param: PluginParam) -> dict:
    """Serialize a PluginParam to a dict."""
    d = {"name": param.name}
    if param.hint:
        d["hint"] = param.hint
    if param.default:
        d["default"] = param.default
    if param.options:
        d["options"] = param.options
    if param.type != "string":
        d["type"] = param.type
    if not param.required:
        d["required"] = False
    if param.pattern:
        d["pattern"] = param.pattern
    if param.min is not None:
        d["min"] = param.min
    if param.max is not None:
        d["max"] = param.max
    return d


def dict_to_plugins(data: dict) -> List[Plugin]:
    """Deserialize a dict (from REST API) back to Plugin objects.

    Args:
        data: Dict with "plugins" key, as returned by plugins_to_dict().

    Returns:
        List of Plugin objects.
    """
    plugins = []
    for raw in data.get("plugins", []):
        plugin = _parse_plugin(raw, "<api>")
        if plugin is not None:
            plugins.append(plugin)
    return plugins


def _find_icon(filename: str) -> str:
    """Find an icon file in the images directory."""
    from pathlib import Path

    candidates = [
        Path(__file__).resolve().parent.parent / "images" / filename,
        Path(__file__).resolve().parent.parent.parent.parent / "images" / filename,
    ]
    try:
        from importlib.resources import files

        candidates.insert(0, Path(str(files("ai_guardian") / "images" / filename)))
    except Exception:
        pass  # intentionally silent — optional dependency
    for p in candidates:
        if p.exists():
            return str(p)
    return ""


def _subprocess_succeeded(result, operation: str) -> bool:
    """Return whether a UI subprocess completed successfully.

    ``subprocess.run`` returns an integer return code.  The type guard keeps
    lightweight test doubles and alternate subprocess implementations that do
    not expose a return code compatible with the historical success behavior.
    """
    returncode = getattr(result, "returncode", 0)
    if not isinstance(returncode, int) or returncode == 0:
        return True

    stderr = getattr(result, "stderr", "")
    detail = ""
    if isinstance(stderr, str) and stderr.strip():
        detail = f": {stderr.strip().replace(chr(10), ' ')[:200]}"
    logger.warning(
        "%s failed with exit code %s%s",
        operation,
        returncode,
        detail,
    )
    return False


def show_dialog(title: str, message: str) -> bool:
    """Show a modal dialog box. Returns True on success.

    Uses platform-native dialogs: AppleScript on macOS, zenity/kdialog
    on Linux, PowerShell on Windows.
    """
    import subprocess

    system = platform.system()
    try:
        if system == "Darwin":
            from ai_guardian.daemon.multi_client import _escape_for_applescript

            msg = (
                _escape_for_applescript(message)
                .replace("\r", "")
                .replace("\n", '" & return & "')
            )
            ttl = _escape_for_applescript(title).replace("\r", "").replace("\n", " ")
            icon_clause = ""
            icns_path = _find_icon("ai-guardian.icns")
            if icns_path:
                icon_clause = f' with icon file (POSIX file "{icns_path}" as alias)'
            script = (
                f'display dialog "{msg}" with title "{ttl}" '
                f'buttons {{"OK"}} default button "OK"{icon_clause}'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
        elif system == "Linux":
            icon_args = []
            png_path = _find_icon("ai-guardian-320.png")
            if png_path:
                icon_args = ["--icon-name", png_path]
            result = subprocess.run(
                ["zenity", "--info", "--title", title, "--text", message] + icon_args,
                capture_output=True,
                text=True,
                timeout=30,
            )
        elif system == "Windows":
            ttl = title.replace("'", "''")
            msg = message.replace("'", "''")
            ps = (
                "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                f"[System.Windows.Forms.MessageBox]::Show('{msg}', '{ttl}', 'OK', 'Information')"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:
            return False
        return _subprocess_succeeded(result, f"{system} dialog")
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return False


def show_action_dialog(
    title: str,
    message: str,
    action_label: str,
    dismiss_label: Optional[str],
    snooze_options: Iterable[str] = (),
    ide_choices: Iterable[Dict[str, str]] = (),
    profile_choices: Iterable[Dict[str, str]] = (),
) -> Optional[object]:
    """Show an actionable native prompt on macOS.

    This is the last-resort UI for prompts invoked from the macOS tray.  A
    tray process cannot reliably bring a Tkinter window to the foreground, so
    the prompt uses native Cocoa controls when the normal UI tiers are
    unavailable.

    Returns ``"action"``, ``"dismiss"``, or ``"snooze_<option>"`` for a
    simple prompt.  A prompt with IDE or profile choices returns the same
    structured mapping as the other proactive-prompt UI implementations.
    Returns ``None`` when the native prompt could not be launched.
    """
    if platform.system() != "Darwin":
        return None

    ide_choices = tuple(
        choice
        for choice in ide_choices
        if isinstance(choice, dict) and choice.get("ide")
    )
    profile_choices = tuple(
        choice
        for choice in profile_choices
        if isinstance(choice, dict)
        and (choice.get("profile") is not None or choice.get("name"))
    )
    result = _show_native_choice_dialog(
        title,
        message,
        action_label,
        dismiss_label,
        snooze_options,
        ide_choices,
        profile_choices,
    )
    if ide_choices or profile_choices:
        return result
    if isinstance(result, dict):
        return result.get("result", "dismiss")
    return result


def _show_native_choice_dialog(
    title: str,
    message: str,
    action_label: str,
    dismiss_label: Optional[str],
    snooze_options: Iterable[str],
    ide_choices: Iterable[Dict[str, str]],
    profile_choices: Iterable[Dict[str, str]],
) -> Optional[object]:
    """Show a structured proactive prompt using native macOS controls.

    AppleScript's ``display dialog`` has no checkbox or combobox controls.
    Use a small native Cocoa accessory view for the macOS fallback so the
    primary action, per-IDE checkboxes, and snooze selector are visible in the
    same dialog.  If the Cocoa bridge cannot be started, return without
    opening secondary legacy dialogs.
    """
    ide_choices = tuple(ide_choices)
    profile_choices = tuple(profile_choices)
    cocoa_result = _show_native_cocoa_choice_dialog(
        title,
        message,
        action_label,
        dismiss_label,
        snooze_options,
        ide_choices,
        profile_choices,
    )
    if cocoa_result is not None:
        return cocoa_result

    logger.warning(
        "Native macOS setup prompt unavailable; no secondary dialogs will be shown"
    )
    return None


def _show_native_cocoa_choice_dialog(
    title: str,
    message: str,
    action_label: str,
    dismiss_label: Optional[str],
    snooze_options: Iterable[str],
    ide_choices: Iterable[Dict[str, str]],
    profile_choices: Iterable[Dict[str, str]],
) -> Optional[object]:
    """Show the structured prompt with native Cocoa controls on macOS."""
    import subprocess

    ide_choices = tuple(ide_choices)
    profile_choices = tuple(profile_choices)
    options = tuple(str(option) for option in snooze_options if option)
    payload = {
        "title": title,
        "message": message,
        "action_label": action_label,
        "dismiss_label": dismiss_label,
        "snooze_options": options,
        "ide_choices": ide_choices,
        "profile_choices": profile_choices,
    }
    payload_script = json.dumps(payload, ensure_ascii=False)

    # This is intentionally self-contained: the tray can invoke it through
    # the system-provided JXA runtime without adding a PyObjC dependency.
    script = r"""
ObjC.import("Cocoa");
ObjC.import("AppKit");

var payload = PAYLOAD;

function rect(x, y, width, height) {
    return $.NSMakeRect(x, y, width, height);
}

function addLabel(view, text, x, y, width, height, size) {
    var field = $.NSTextField.alloc.initWithFrame(rect(x, y, width, height));
    field.setStringValue(String(text));
    field.setBezeled(false);
    field.setDrawsBackground(false);
    field.setEditable(false);
    field.setSelectable(true);
    field.setFont($.NSFont.systemFontOfSize(size || 13));
    view.addSubview(field);
    return field;
}

function addCheckbox(view, x, y, checked) {
    var checkbox = $.NSButton.alloc.initWithFrame(rect(x, y, 22, 22));
    checkbox.setButtonType(3);
    checkbox.setTitle("");
    checkbox.setState(checked ? 1 : 0);
    view.addSubview(checkbox);
    return checkbox;
}

function addPopup(view, values, x, y, width) {
    var popup = $.NSPopUpButton.alloc.initWithFramePullsDown(
        rect(x, y, width, 24), false
    );
    values.forEach(function(value) {
        popup.addItemWithTitle(String(value));
    });
    if (values.length > 0) {
        popup.selectItemAtIndex(0);
    }
    view.addSubview(popup);
    return popup;
}

var checkboxPairs = [];
ObjC.registerSubclass({
    name: "AIGuardianCheckboxTarget",
    superclass: "NSObject",
    methods: {
        "checkboxChanged:": {
            types: ["void", ["id"]],
            implementation: function(sender) {
                var tag = Number(sender.tag);
                var index = Math.floor(tag / 2);
                var pair = checkboxPairs[index];
                if (!pair) {
                    return;
                }
                if (Number(sender.state) === 1) {
                    if (tag % 2 === 0) {
                        pair.never.setState(0);
                    } else {
                        pair.install.setState(0);
                    }
                } else if (
                    Number(pair.install.state) === 0 &&
                    Number(pair.never.state) === 0
                ) {
                    sender.setState(1);
                }
            },
        },
    },
});

function selectedProfile(profilePopup) {
    if (payload.profile_choices.length === 0) {
        return null;
    }
    var index = Number(profilePopup.indexOfSelectedItem);
    if (index < 0 || index >= payload.profile_choices.length) {
        return null;
    }
    return payload.profile_choices[index].profile;
}

function showDialog() {
    var app = $.NSApplication.sharedApplication;
    app.setActivationPolicy(0);
    app.activateIgnoringOtherApps(true);

    var rowHeight = 28;
    var profileHeight = payload.profile_choices.length > 0 ? 52 : 0;
    var tableHeight = payload.ide_choices.length > 0
        ? 42 + payload.ide_choices.length * rowHeight
        : 0;
    var footerHeight = payload.snooze_options.length > 0 ? 48 : 16;
    var accessoryHeight = profileHeight + tableHeight + footerHeight;
    var accessoryWidth = 820;
    var accessory = $.NSView.alloc.initWithFrame(
        rect(0, 0, accessoryWidth, accessoryHeight)
    );
    var cursor = accessoryHeight - 26;
    var profilePopup = null;
    var checkboxTarget = $.AIGuardianCheckboxTarget.alloc.init;

    if (payload.profile_choices.length > 0) {
        addLabel(accessory, "Security profile", 0, cursor, 160, 22, 13);
        var profileNames = payload.profile_choices.map(function(choice) {
            var label = choice.name || choice.profile || "";
            if (choice.description) {
                label += " — " + choice.description;
            }
            return label;
        });
        profilePopup = addPopup(accessory, profileNames, 170, cursor - 2, 620);
        var standardIndex = payload.profile_choices.findIndex(function(choice) {
            return choice.profile === "@standard";
        });
        if (standardIndex >= 0) {
            profilePopup.selectItemAtIndex(standardIndex);
        }
        cursor -= profileHeight;
    }

    var controls = [];
    if (payload.ide_choices.length > 0) {
        addLabel(accessory, "Integration", 0, cursor, 600, 22, 13);
        addLabel(accessory, "Install now", 625, cursor, 100, 22, 13);
        addLabel(accessory, "Never install", 735, cursor, 100, 22, 13);
        cursor -= rowHeight;
        payload.ide_choices.forEach(function(choice) {
            var label = choice.name || choice.ide || "";
            if (choice.detail) {
                label += " — " + choice.detail;
            }
            addLabel(accessory, label, 0, cursor, 600, 22, 12);
            var install = addCheckbox(accessory, 665, cursor, true);
            var never = addCheckbox(accessory, 775, cursor, false);
            var pairIndex = controls.length;
            install.setTag(pairIndex * 2);
            never.setTag(pairIndex * 2 + 1);
            install.setTarget(checkboxTarget);
            never.setTarget(checkboxTarget);
            install.setAction("checkboxChanged:");
            never.setAction("checkboxChanged:");
            checkboxPairs.push({install: install, never: never});
            controls.push({
                key: choice.ide,
                install: install,
                never: never,
            });
            cursor -= rowHeight;
        });
    }

    var snoozePopup = null;
    if (payload.snooze_options.length > 0) {
        addLabel(accessory, "Later", 0, 12, 80, 22, 13);
        snoozePopup = addPopup(accessory, payload.snooze_options, 90, 10, 170);
    }

    var alert = $.NSAlert.alloc.init;
    var hasDismiss = payload.dismiss_label !== null &&
        String(payload.dismiss_label).length > 0;
    alert.setMessageText(String(payload.title));
    alert.setInformativeText(String(payload.message));
    alert.addButtonWithTitle(String(payload.action_label));
    if (payload.snooze_options.length > 0) {
        alert.addButtonWithTitle("Later");
    }
    if (hasDismiss) {
        alert.addButtonWithTitle(String(payload.dismiss_label));
    }
    alert.setAccessoryView(accessory);
    app.activateIgnoringOtherApps(true);
    var alertWindow = alert.window;
    if (alertWindow) {
        alertWindow.setLevel(3);
        alertWindow.makeKeyAndOrderFront(null);
    }
    var response = Number(alert.runModal);
    var firstButton = 1000;
    var secondButton = 1001;
    var dismissButton = payload.snooze_options.length > 0 ? 1002 : 1001;

    if (payload.snooze_options.length > 0 && response === secondButton) {
        var snoozeIndex = Number(snoozePopup.indexOfSelectedItem);
        return {
            result: "snooze_" + payload.snooze_options[snoozeIndex],
            install: [],
            never: [],
        };
    }

    if (hasDismiss && response === dismissButton) {
        var structured =
            String(payload.dismiss_label) === "Never" &&
            (payload.ide_choices.length > 0 || payload.profile_choices.length > 0);
        return {
            result: structured ? "action" : "dismiss",
            install: [],
            never: structured
                ? payload.ide_choices.map(function(choice) {
                      return choice.ide;
                  })
                : [],
            profile: payload.profile_choices.length > 0 ? null : undefined,
        };
    }
    if (response !== firstButton) {
        return {result: "dismiss", install: [], never: []};
    }

    var install = [];
    var never = [];
    controls.forEach(function(control) {
        var isNever = Number(control.never.state) === 1;
        var isInstall = Number(control.install.state) === 1;
        if (isNever) {
            never.push(control.key);
        } else if (isInstall) {
            install.push(control.key);
        }
    });
    var result = {
        result: "action",
        install: install,
        never: never,
    };
    if (payload.profile_choices.length > 0) {
        result.profile = selectedProfile(profilePopup);
    }
    return result;
}

JSON.stringify(showDialog());
""".replace("PAYLOAD", payload_script)

    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if not _subprocess_succeeded(result, "macOS Cocoa choice dialog"):
            logger.warning(
                "macOS Cocoa choice dialog failed: %s",
                (result.stderr or "").strip(),
            )
            return None
        output = (result.stdout or "").strip().splitlines()
        if not output:
            logger.warning("macOS Cocoa choice dialog returned no result")
            return None
        value = json.loads(output[-1])
        return value if isinstance(value, dict) else None
    except (
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
        OSError,
        FileNotFoundError,
    ) as exc:
        logger.warning("macOS Cocoa choice dialog could not be shown: %s", exc)
        return None


def send_notification(title: str, message: str) -> bool:
    """Show a system notification.

    On macOS, use the same detached ``osascript`` transport as the tray's
    web-console-ready notification. ``display notification`` shows the Script
    Editor icon — custom icons require running from a signed .app bundle.
    On Linux ``--icon`` is passed to ``notify-send``.
    On Windows a custom icon is loaded from PNG for the balloon tip.
    Returns True on success.
    """
    import subprocess

    system = platform.system()
    try:
        if system == "Darwin":
            from ai_guardian.daemon.multi_client import _escape_for_applescript

            safe_title = _escape_for_applescript(title)
            safe_message = _escape_for_applescript(message)
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    f'display notification "{safe_message}" with title "{safe_title}"',
                ]
            )
            return True
        elif system == "Linux":
            icon_args: list[str] = []
            png_path = _find_icon("ai-guardian-320.png")
            if png_path:
                icon_args = ["--icon", png_path]
            result = subprocess.run(
                ["notify-send"] + icon_args + [title, message],
                capture_output=True,
                text=True,
                timeout=5,
            )
        elif system == "Windows":
            ttl = title.replace("'", "''")
            msg = message.replace("'", "''")
            png_path = _find_icon("ai-guardian-320.png")
            if png_path:
                ps_icon_path = png_path.replace("\\", "\\\\").replace("'", "''")
                icon_line = (
                    "try { "
                    f"$bmp = [System.Drawing.Bitmap]::new('{ps_icon_path}'); "
                    "$n.Icon = [System.Drawing.Icon]::FromHandle($bmp.GetHicon()) "
                    "} catch { "
                    "$n.Icon = [System.Drawing.SystemIcons]::Information "
                    "}; "
                )
            else:
                icon_line = "$n.Icon = [System.Drawing.SystemIcons]::Information; "
            ps = (
                "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                "[System.Reflection.Assembly]::LoadWithPartialName('System.Drawing') | Out-Null; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; "
                f"{icon_line}"
                "$n.Visible = $true; "
                f"$n.ShowBalloonTip(5000, '{ttl}', '{msg}', 'Info')"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=10,
            )
        else:
            return False
        return _subprocess_succeeded(result, f"{system} notification")
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return False


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard. Returns True on success."""
    import shutil
    import subprocess

    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["pbcopy"], input=text.encode(), timeout=5)
        elif system == "Linux":
            for cmd in (
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ):
                if shutil.which(cmd[0]):
                    subprocess.run(cmd, input=text.encode(), timeout=5)
                    break
            else:
                return False
        elif system == "Windows":
            subprocess.run(["clip"], input=text.encode(), timeout=5)
        else:
            return False
        return True
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return False


# ---------------------------------------------------------------------------
# Plugin menu constants and command execution helpers
# Split from tray.py (Issue #1492)
# ---------------------------------------------------------------------------

_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*\.json$")


def list_plugin_files(
    working_dir: Optional[str] = None,
) -> List[Dict[str, Union[str, bool]]]:
    """List all plugin files with source and status metadata.

    Returns a list of dicts with keys: filename, source, enabled, plugin_name.
    Sources: "bundled", "user", "project".
    """
    from ai_guardian.daemon import get_tray_plugins_dir

    result: List[Dict[str, Union[str, bool]]] = []
    seen_ids: set = set()

    def _scan_dir(directory: Path, source: str) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.iterdir()):
            if path.name.startswith("."):
                continue
            is_disabled = path.name.endswith(".json.disabled")
            is_json = path.name.endswith(".json")
            if not is_json and not is_disabled:
                continue
            base_name = path.name[: -len(".disabled")] if is_disabled else path.name
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                plugin_name = data.get("name", base_name)
                plugin_id = data.get("id", plugin_name)
            except (json.JSONDecodeError, OSError):
                plugin_name = base_name
                plugin_id = base_name
            if plugin_id in seen_ids:
                continue
            seen_ids.add(plugin_id)
            result.append(
                {
                    "filename": path.name,
                    "source": source,
                    "enabled": not is_disabled,
                    "plugin_name": plugin_name,
                }
            )

    project_dir = find_project_plugins_dir(working_dir)
    if project_dir:
        _scan_dir(project_dir, "project")

    _scan_dir(get_tray_plugins_dir(), "user")

    bundled_dir = _get_bundled_plugins_dir()
    if bundled_dir:
        _scan_dir(bundled_dir, "bundled")

    return result


def get_bundled_templates() -> List[Dict[str, str]]:
    """Return bundled plugin templates as a list of {filename, name, content}."""
    bundled_dir = _get_bundled_plugins_dir()
    if bundled_dir is None or not bundled_dir.is_dir():
        return []
    templates = []
    for path in sorted(bundled_dir.glob("*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            templates.append(
                {
                    "filename": path.name,
                    "name": data.get("name", path.stem),
                    "content": raw,
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return templates


def save_user_plugin(filename: str, content: dict) -> Tuple[bool, str]:
    """Save a plugin JSON file to the user plugins directory.

    Returns (success, message).
    """
    from ai_guardian.daemon import get_tray_plugins_dir

    if not _SAFE_FILENAME_RE.match(filename):
        return (
            False,
            "Invalid filename — use alphanumeric, hyphens, dots, ending in .json",
        )

    plugins_dir = get_tray_plugins_dir()
    plugins_dir.mkdir(parents=True, exist_ok=True)

    if not isinstance(content, dict) or "name" not in content:
        return False, "Plugin must be a JSON object with a 'name' field"

    plugin = _parse_plugin(content, filename)
    if plugin is None:
        return False, "Invalid plugin structure"

    path = plugins_dir / filename
    try:
        path.write_text(
            json.dumps(content, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        return False, f"Write failed: {e}"

    return True, f"Saved {filename}"


def delete_user_plugin(filename: str) -> Tuple[bool, str]:
    """Delete a plugin file from the user plugins directory.

    Returns (success, message). Refuses to delete bundled plugins.
    """
    from ai_guardian.daemon import get_tray_plugins_dir

    if not _SAFE_FILENAME_RE.match(filename) and not filename.endswith(
        ".json.disabled"
    ):
        return False, "Invalid filename"

    path = get_tray_plugins_dir() / filename
    if not path.is_file():
        return False, f"File not found: {filename}"

    try:
        path.unlink()
    except OSError as e:
        return False, f"Delete failed: {e}"

    return True, f"Deleted {filename}"


def toggle_user_plugin(filename: str, enabled: bool) -> Tuple[bool, str]:
    """Enable or disable a user plugin by renaming .json ↔ .json.disabled.

    Returns (success, message).
    """
    from ai_guardian.daemon import get_tray_plugins_dir

    plugins_dir = get_tray_plugins_dir()

    if enabled:
        src = plugins_dir / (filename + ".disabled")
        dst = plugins_dir / filename
        if not src.is_file():
            if (plugins_dir / filename).is_file():
                return True, "Already enabled"
            return False, f"File not found: {filename}.disabled"
    else:
        src = plugins_dir / filename
        dst = plugins_dir / (filename + ".disabled")
        if not src.is_file():
            if (plugins_dir / (filename + ".disabled")).is_file():
                return True, "Already disabled"
            return False, f"File not found: {filename}"

    try:
        src.rename(dst)
    except OSError as e:
        return False, f"Toggle failed: {e}"

    state = "enabled" if enabled else "disabled"
    return True, f"Plugin {state}: {filename}"


MAX_PLUGIN_SLOTS = 8
MAX_ITEMS_PER_PLUGIN = 12
MAX_SUBMENU_ITEMS = 8
MAX_SUBMENU_DEPTH = 2
MAX_GLOBAL_PLUGIN_SLOTS = 4
MAX_GLOBAL_ITEMS_PER_PLUGIN = 12


def get_python_executable():
    """Get the best available Python executable path."""
    import shutil

    python_exe = shutil.which("python")
    if python_exe:
        return python_exe
    python_exe = shutil.which("python3")
    if python_exe:
        return python_exe
    return sys.executable


def resolve_cli_cmd(*args):
    """Build command list for running ai-guardian with given arguments.

    Uses absolute path to python to ensure it works in subprocesses that
    may not have the same PATH (e.g., Terminal.app on macOS).
    """
    import shutil

    ag_path = shutil.which("ai-guardian")
    if ag_path:
        return [ag_path] + list(args)
    python_exe = get_python_executable()
    return [python_exe, "-m", "ai_guardian"] + list(args)


def resolve_plugin_ai_guardian(command_str, run_on_target, target):
    """Replace bare ``ai-guardian`` with absolute python path.

    Skipped for remote targets (container / kubernetes) where the
    command must resolve via PATH on the remote host.
    """
    is_remote = (
        run_on_target
        and target
        and getattr(target, "runtime", "local") in ("container", "kubernetes")
    )
    if is_remote:
        return command_str

    stripped = command_str.lstrip()
    if stripped == "ai-guardian" or stripped.startswith("ai-guardian "):
        python_exe = get_python_executable()
        resolved = shlex.quote(python_exe) + " -m ai_guardian"
        return resolved + stripped[len("ai-guardian") :]
    return command_str


def poll_output_file(output_path, tmpdir, timeout=300, interval=0.5):
    """Poll for an output file, read its content, and clean up.

    Returns the stripped file content, or ``None`` if the file was not
    created before *timeout* seconds elapsed.
    """
    import shutil
    import time

    elapsed = 0.0
    while elapsed < timeout:
        if os.path.exists(output_path):
            try:
                with open(output_path) as f:
                    content = f.read().strip()
            except OSError:
                content = ""
            shutil.rmtree(tmpdir, ignore_errors=True)
            return content
        time.sleep(interval)
        elapsed += interval
    shutil.rmtree(tmpdir, ignore_errors=True)
    return None


def execute_plugin_command(
    command_str,
    item_type,
    target=None,
    run_on_target=False,
    label=None,
):
    """Execute a plugin command with optional target context."""
    import subprocess

    from ai_guardian.daemon.multi_client import _launch_in_terminal

    command_str = substitute_target_vars(command_str, target)
    if target and getattr(target, "working_dir", None):
        command_str = substitute_params(
            command_str,
            {"working_dir": target.working_dir},
        )

    command_str = resolve_plugin_ai_guardian(command_str, run_on_target, target)

    if _needs_shell(command_str):
        cmd_parts = ["sh", "-c", command_str]
    else:
        try:
            cmd_parts = shlex.split(command_str)
        except ValueError:
            logger.warning("Malformed plugin command: %s", command_str)
            return

    if run_on_target and target:
        cmd_parts = wrap_for_target(
            cmd_parts,
            target,
            interactive=(item_type == "terminal"),
        )

    is_remote = (
        run_on_target
        and target
        and getattr(target, "runtime", "local") in ("container", "kubernetes")
    )
    if item_type != "terminal" and not is_remote:
        shell = os.environ.get("SHELL", "/bin/bash")
        cmd_parts = [shell, "-lc", command_str]

    try:
        if item_type == "terminal":
            _launch_in_terminal(cmd_parts, keep_open=True)
        elif item_type == "notification":
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=60,
            )
            send_notification("AI Guardian", result.stdout.strip() or "(no output)")
        elif item_type == "clipboard":
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=60,
            )
            copy_to_clipboard(result.stdout.strip())
        elif item_type == "modal":
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = result.stdout.strip()
            err = result.stderr.strip()
            if err:
                if result.returncode != 0:
                    output = (
                        err if not output else (output + "\n\n--- stderr ---\n" + err)
                    )
                else:
                    output = (output + "\n" + err).strip() if output else err
            show_dialog(label or "AI Guardian", output or "(no output)")
        else:
            subprocess.run(cmd_parts, timeout=60)
    except Exception:
        pass
