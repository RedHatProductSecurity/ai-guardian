"""Canonical inventory and matching for supported agent configuration paths.

The setup and MCP registries already know how supported integrations relocate
their user configuration.  This module combines those resolvers with the
documented project-local artifact roots so the tool policy does not maintain a
second collection of unrelated glob patterns.
"""

import logging
import os
import posixpath
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ai_guardian.config.utils import get_project_dir
from ai_guardian.ide_paths import (
    get_explicit_ide_config_path,
    get_ide_home,
)
from ai_guardian.ide_registry import SUPPORTED_IDE_REGISTRY

AGENT_CONFIG_PROTECTION_SECTION = "agent_config_protection"
logger = logging.getLogger(__name__)

_FILE_MUTATION_TOOLS = frozenset(
    {
        "write",
        "edit",
        "notebookedit",
        "delete",
        "remove",
        "removefile",
        "removefiles",
        "move",
        "movefile",
        "rename",
        "renamefile",
        "copy",
        "copyfile",
        "savefile",
        "str-replace-editor",
        "save-file",
        "remove-files",
        "apply_patch",
        "patch",
        "write_file",
        "edit_file",
        "delete_file",
        "move_file",
        "copy_file",
        "rename_file",
        "create_file",
        # Grok's native file mutation name is normalized to Edit by the hook
        # adapter, but direct policy callers can still receive it unchanged.
        "search_replace",
    }
)

SHELL_TOOL_NAMES = frozenset(
    {
        "bash",
        "shell",
        "powershell",
        "pwsh",
        "run_command",
        "shell_exec",
        "send_command_input",
        "launch-process",
        "execute_command",
        "terminal",
        # Grok's native shell tool name; the hook adapter normally maps it to
        # the canonical Bash name before policy evaluation.
        "run_terminal_command",
    }
)

_SHELL_MUTATING_COMMANDS = frozenset(
    {
        "add-content",
        "attrib",
        "chattr",
        "chmod",
        "chown",
        "clear-content",
        "copy",
        "copy-item",
        "cp",
        "curl",
        "dd",
        "del",
        "erase",
        "install",
        "ln",
        "mkdir",
        "mkfile",
        "move",
        "move-item",
        "mv",
        "new-item",
        "nano",
        "node",
        "out-file",
        "perl",
        "powershell",
        "python",
        "python3",
        "rename",
        "rename-item",
        "rm",
        "rmdir",
        "rsync",
        "scp",
        "sed",
        "set-content",
        "tee",
        "touch",
        "truncate",
        "vim",
        "vi",
        "wget",
        "emacs",
        "unlink",
        "write-output",
        "zsh",
    }
)

_SHELL_OPERATORS = frozenset({">", ">>", "<>", "|&"})
_PATH_ARGUMENT_KEYS = (
    "file_path",
    "filePath",
    "path",
    "target",
    "target_path",
    "targetPath",
    "source",
    "source_path",
    "sourcePath",
    "destination",
    "destination_path",
    "destinationPath",
    "new_path",
    "newPath",
    "old_path",
    "oldPath",
    "notebook_path",
    "notebookPath",
    "filename",
    "file",
    "files",
    "file_paths",
    "filePaths",
    "paths",
)

_PROJECT_ARTIFACTS: Dict[str, Tuple[Tuple[str, bool], ...]] = {
    "claude": ((".claude", True), (".mcp.json", False)),
    "cursor": ((".cursor", True),),
    "copilot": ((".github/hooks", True), (".github/skills", True)),
    "grok": ((".grok", True),),
    "codex": ((".codex", True),),
    "windsurf": ((".windsurf", True), (".codeium/windsurf", True)),
    "gemini": ((".gemini", True),),
    "antigravity": ((".agents", True),),
    "cline": ((".clinerules", True),),
    "zoocode": ((".clinerules", True),),
    "kiro": ((".kiro", True),),
    "aiderdesk": ((".aider-desk", True),),
    "openclaw": ((".openclaw", True),),
    "opencode": (
        ("opencode.json", False),
        ("opencode.jsonc", False),
        (".opencode", True),
    ),
    "pi": ((".pi", True),),
    "augment": ((".augment", True),),
    "crush": ((".crush.json", False), (".crush", True)),
    "junie": ((".junie", True),),
}

_GLOBAL_ARTIFACT_ROOTS: Dict[str, Tuple[str, ...]] = {
    "claude": ("~/.claude",),
    "cursor": ("~/.cursor",),
    "copilot": ("~/.github/hooks", "~/.copilot"),
    "grok": ("~/.grok",),
    "codex": ("~/.codex",),
    "windsurf": ("~/.windsurf", "~/.codeium/windsurf"),
    "gemini": ("~/.gemini",),
    "antigravity": ("~/.gemini/config",),
    "cline": ("~/.cline",),
    "zoocode": ("~/.cline",),
    "kiro": ("~/.kiro",),
    "aiderdesk": ("~/.aider-desk",),
    "openclaw": ("~/.openclaw",),
    "opencode": ("~/.config/opencode",),
    "pi": ("~/.pi",),
    "augment": ("~/.augment",),
    "crush": ("~/.config/crush",),
    "junie": ("~/.junie",),
}


@dataclass(frozen=True)
class ProtectedAgentPath:
    """One normalized protected path or directory root."""

    path: str
    integration: str
    scope: str
    recursive: bool = False
    kind: str = "configuration"


def is_shell_tool_name(tool_name: Optional[str]) -> bool:
    """Return whether a tool name executes shell or process commands."""
    return isinstance(tool_name, str) and tool_name.lower() in SHELL_TOOL_NAMES


def is_file_mutation_tool(tool_name: Optional[str]) -> bool:
    """Return whether a tool can mutate a file or directory directly."""
    return isinstance(tool_name, str) and tool_name.lower() in _FILE_MUTATION_TOOLS


def is_agent_config_mutation_tool(tool_name: Optional[str]) -> bool:
    """Return whether *tool_name* needs the agent-config protection check."""
    return is_shell_tool_name(tool_name) or is_file_mutation_tool(tool_name)


def is_agent_config_protection_enabled(config: Optional[Dict]) -> bool:
    """Resolve the protection setting with a secure default.

    This setting is deliberately stricter than the generic feature helper:
    only an actual boolean ``false`` is an explicit opt-out.  Missing sections,
    malformed values, and time-based objects all remain enabled.
    """
    section = (
        config.get(AGENT_CONFIG_PROTECTION_SECTION)
        if isinstance(config, dict)
        else None
    )
    if not isinstance(section, dict):
        return True
    value = section.get("enabled")
    return value if isinstance(value, bool) else True


def _expand_path(value: str) -> str:
    return os.path.expanduser(os.path.expandvars(str(value).strip().strip("'\"")))


def _is_windows_absolute(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:/", value)) or value.startswith("//")


def _is_absolute_path(value: str) -> bool:
    expanded = _expand_path(value).replace("\\", "/")
    return Path(expanded).is_absolute() or _is_windows_absolute(expanded)


def _normalize_path(value: str, base_dir: str) -> str:
    """Normalize a path for cross-platform comparison without requiring it to exist."""
    expanded = _expand_path(value).replace("\\", "/")
    if _is_windows_absolute(expanded):
        normalized = posixpath.normpath(expanded)
    else:
        path = Path(expanded)
        if not path.is_absolute():
            path = Path(base_dir) / path
        try:
            normalized = path.resolve(strict=False).as_posix()
        except OSError:
            normalized = posixpath.normpath(path.as_posix())
    if normalized != "/":
        normalized = normalized.rstrip("/")
    return normalized.casefold()


def _path_variants(path: str, project_dir: str) -> Tuple[str, ...]:
    """Return textual spellings commonly used by shell commands."""
    normalized = path.replace("\\", "/").casefold()
    variants = {normalized, normalized.replace("/", "\\")}
    try:
        home = Path.home().resolve(strict=False).as_posix().casefold()
        if normalized.startswith(home.rstrip("/") + "/"):
            relative_home = normalized[len(home.rstrip("/")) + 1 :]
            windows_relative_home = relative_home.replace("/", "\\")
            variants.update({f"~/{relative_home}", "~\\" + windows_relative_home})
    except OSError:
        logger.debug("Unable to resolve the current home directory for path variants")
    try:
        project = _normalize_path(project_dir, project_dir)
        if normalized.startswith(project.rstrip("/") + "/"):
            relative = normalized[len(project.rstrip("/")) + 1 :]
            variants.update({relative, f"./{relative}", relative.replace("/", "\\")})
    except (OSError, ValueError):
        logger.debug("Unable to resolve the active project directory for path variants")
    return tuple(item for item in variants if item)


def _safe_path(value: Optional[str], base_dir: str) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return _normalize_path(value, base_dir)


def _iter_nested_path_values(value, key: Optional[str] = None) -> Iterable[str]:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from _iter_nested_path_values(child_value, str(child_key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_nested_path_values(child, key)
    elif key in _PATH_ARGUMENT_KEYS and isinstance(value, str):
        yield value


def _shell_tokens(command: str) -> List[str]:
    normalized = command.replace("\r\n", "\n").replace("\r", "\n").replace("\n", ";")
    for posix in (True, False):
        try:
            lexer = shlex.shlex(
                normalized,
                posix=posix,
                punctuation_chars=";&|()<>`{}",
            )
            lexer.whitespace_split = True
            lexer.commenters = ""
            tokens = list(lexer)
            if tokens:
                return tokens
        except (TypeError, ValueError):
            continue
    return []


def _token_basename(token: str) -> str:
    cleaned = token.strip().strip("'\"").replace("\\", "/")
    return cleaned.rstrip("/").rsplit("/", 1)[-1].casefold()


def _shell_command_mutates(command: str, tokens: Sequence[str]) -> bool:
    if any(token in _SHELL_OPERATORS for token in tokens):
        return True

    lowered = command.casefold()
    if re.search(
        r"\b(?:open|write_text|write_bytes|unlink|rename|replace)\s*\(", lowered
    ):
        return True
    if re.search(r"\b(?:writefile|appendfile|unlink|rename|rm)\s*\(", lowered):
        return True

    for index, token in enumerate(tokens):
        basename = _token_basename(token)
        if basename in _SHELL_MUTATING_COMMANDS:
            if basename in {"sed", "perl"}:
                return any(
                    item in {"-i", "--in-place"} or item.startswith("-i")
                    for item in tokens[index + 1 :]
                )
            return True
        if basename == "git" and index + 1 < len(tokens):
            if tokens[index + 1].casefold() in {"mv", "rm", "config", "clean"}:
                return True
    return False


class AgentConfigInventory:
    """Resolved user and active-workspace agent configuration inventory."""

    def __init__(self, paths: Sequence[ProtectedAgentPath], project_dir: str):
        self.paths = tuple(paths)
        self.project_dir = project_dir

    @property
    def protected_paths(self) -> Tuple[str, ...]:
        """Return normalized protected paths for diagnostics and tests."""
        return tuple(item.path for item in self.paths)

    def match_path(self, candidate: str) -> Optional[ProtectedAgentPath]:
        """Return the inventory item containing *candidate*, if any."""
        candidate_key = _safe_path(candidate, self.project_dir)
        if not candidate_key:
            return None
        for item in self.paths:
            if candidate_key == item.path:
                return item
            if item.recursive and candidate_key.startswith(item.path.rstrip("/") + "/"):
                return item
        return None

    def match_mutation(
        self, tool_name: str, tool_input: Dict, hook_data: Optional[Dict] = None
    ) -> Optional[ProtectedAgentPath]:
        """Return the protected target of a direct or shell mutation."""
        if is_file_mutation_tool(tool_name):
            for value in _iter_nested_path_values(tool_input):
                match = self.match_path(value)
                if match:
                    return match
            return None

        if not is_shell_tool_name(tool_name):
            return None

        command = None
        if isinstance(tool_input, dict):
            for key in (
                "command",
                "commandLine",
                "CommandLine",
                "commandline",
                "script",
                "cmd",
            ):
                if isinstance(tool_input.get(key), str):
                    command = tool_input[key]
                    break
        if command is None and isinstance(hook_data, dict):
            for key in (
                "command",
                "commandLine",
                "CommandLine",
                "commandline",
                "script",
                "cmd",
            ):
                if isinstance(hook_data.get(key), str):
                    command = hook_data[key]
                    break
        if not command:
            return None

        tokens = _shell_tokens(command)
        if not _shell_command_mutates(command, tokens):
            return None

        for token in tokens:
            if token in _SHELL_OPERATORS or token in {";", "&&", "||", "|", "&"}:
                continue
            match = self.match_path(token.strip(",;"))
            if match:
                return match

        expanded_command = _expand_path(command).replace("\\", "/")
        for item in self.paths:
            for variant in _path_variants(item.path, self.project_dir):
                if variant.replace("\\", "/").casefold() in expanded_command.casefold():
                    return item
        return None


def _add_path(
    paths: List[ProtectedAgentPath],
    seen: set,
    value: Optional[str],
    integration: str,
    scope: str,
    project_dir: str,
    *,
    recursive: bool = False,
    kind: str = "configuration",
) -> None:
    if not value:
        return
    normalized = _safe_path(value, project_dir)
    if not normalized:
        return
    identity = (normalized, integration, scope, recursive)
    if identity in seen:
        return
    seen.add(identity)
    paths.append(
        ProtectedAgentPath(
            path=normalized,
            integration=integration,
            scope=scope,
            recursive=recursive,
            kind=kind,
        )
    )


def _add_project_artifacts(
    paths: List[ProtectedAgentPath],
    seen: set,
    project_dir: str,
) -> None:
    for integration in SUPPORTED_IDE_REGISTRY:
        for relative, recursive in _PROJECT_ARTIFACTS.get(integration.key, ()):
            _add_path(
                paths,
                seen,
                _join_project_path(project_dir, relative),
                integration.key,
                "project",
                project_dir,
                recursive=recursive,
                kind="project configuration",
            )


def _join_project_path(project_dir: str, relative: str) -> str:
    if _is_windows_absolute(project_dir):
        return project_dir.rstrip("\\/") + "/" + relative
    return str(Path(project_dir) / relative)


def build_agent_config_inventory(
    project_dir: Optional[str] = None,
) -> AgentConfigInventory:
    """Build the protected user/global and active-project path inventory."""
    raw_project = str(project_dir or get_project_dir())
    if _is_windows_absolute(raw_project.replace("\\", "/")):
        active_project = raw_project.replace("\\", "/").casefold().rstrip("/")
    else:
        active_project = str(Path(raw_project).expanduser().resolve())
    paths: List[ProtectedAgentPath] = []
    seen: set = set()

    # Imports stay local: setup hooks and MCP modules both import ide_paths.
    from ai_guardian.setup.hooks import IDESetup
    from ai_guardian.setup.mcp import get_mcp_config_path, get_pi_extension_dir

    setup = IDESetup()
    global_directory_integrations = {"aiderdesk", "openclaw", "opencode"}
    for integration in SUPPORTED_IDE_REGISTRY:
        key = integration.key
        global_roots = _GLOBAL_ARTIFACT_ROOTS.get(key, ())
        relocated_home = get_ide_home(key)
        if relocated_home is not None:
            global_roots = (str(relocated_home),)
        for root in global_roots:
            _add_path(
                paths,
                seen,
                root,
                key,
                "global",
                active_project,
                recursive=True,
                kind="managed integration root",
            )
        try:
            setup_path = setup.get_config_path(key, scope="user")
        except (OSError, ValueError) as exc:
            logger.warning("Unable to resolve %s user hook path: %s", key, exc)
            setup_path = None

        if key == "pi":
            try:
                _add_path(
                    paths,
                    seen,
                    str(get_pi_extension_dir(scope="user")),
                    key,
                    "global",
                    active_project,
                    recursive=True,
                    kind="managed extension",
                )
            except (OSError, ValueError) as exc:
                logger.warning(
                    "Unable to resolve %s managed extension path: %s", key, exc
                )
        elif setup_path and _is_absolute_path(setup_path):
            _add_path(
                paths,
                seen,
                setup_path,
                key,
                "global",
                active_project,
                recursive=key in global_directory_integrations,
                kind=(
                    "managed integration artifact"
                    if key in global_directory_integrations
                    else "hook configuration"
                ),
            )

        try:
            mcp_path = get_mcp_config_path(key, scope="user")
        except (OSError, ValueError) as exc:
            logger.warning("Unable to resolve %s MCP path: %s", key, exc)
            mcp_path = None
        if key == "crush":
            mcp_path = get_explicit_ide_config_path(key) or Path(
                "~/.config/crush/crush.json"
            )
        if mcp_path and _is_absolute_path(str(mcp_path)):
            _add_path(
                paths,
                seen,
                str(mcp_path),
                key,
                "global",
                active_project,
                kind="MCP configuration",
            )

        if key == "opencode":
            config_path = get_explicit_ide_config_path(key)
            if config_path is None:
                try:
                    from ai_guardian.ide_paths import resolve_opencode_config

                    config_path = resolve_opencode_config()
                except OSError as exc:
                    logger.warning("Unable to resolve OpenCode config path: %s", exc)
                    config_path = None
            if config_path:
                config_dir = Path(config_path).expanduser().parent
                _add_path(
                    paths,
                    seen,
                    str(config_dir / "plugins"),
                    key,
                    "global",
                    active_project,
                    recursive=True,
                    kind="managed plugin",
                )
                _add_path(
                    paths,
                    seen,
                    str(config_dir / "ai-guardian"),
                    key,
                    "global",
                    active_project,
                    recursive=True,
                    kind="managed bridge",
                )

    # Project paths intentionally use the active workspace directly.  No IDE
    # home environment variable is consulted for this layer.
    _add_project_artifacts(paths, seen, active_project)
    return AgentConfigInventory(paths, active_project)


def get_protected_agent_paths(project_dir: Optional[str] = None) -> Tuple[str, ...]:
    """Return the normalized protected paths for the active workspace."""
    return build_agent_config_inventory(project_dir).protected_paths


__all__ = [
    "AGENT_CONFIG_PROTECTION_SECTION",
    "AgentConfigInventory",
    "ProtectedAgentPath",
    "SHELL_TOOL_NAMES",
    "build_agent_config_inventory",
    "get_protected_agent_paths",
    "is_agent_config_mutation_tool",
    "is_agent_config_protection_enabled",
    "is_file_mutation_tool",
    "is_shell_tool_name",
]
