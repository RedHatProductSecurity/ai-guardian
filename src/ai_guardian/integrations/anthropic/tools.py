"""Built-in tool resolution and client-side executors for GuardedAgent."""

import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback tool type versions (used when SDK auto-detect fails)
# ---------------------------------------------------------------------------

_FALLBACK_TOOL_TYPES: Dict[str, str] = {
    "bash": "bash_20250124",
    "text_editor": "text_editor_20250728",
    "computer": "computer_20251124",
    "web_search": "web_search_20260209",
    "web_fetch": "web_fetch_20260209",
    "code_execution": "code_execution_20260521",
}

_TOOL_NAMES: Dict[str, str] = {
    "bash": "bash",
    "text_editor": "str_replace_based_edit_tool",
    "computer": "computer",
    "web_search": "web_search",
    "web_fetch": "web_fetch",
    "code_execution": "code_execution",
}

SERVER_TOOLS = frozenset({"web_search", "web_fetch", "code_execution"})

_CLIENT_EXECUTOR_NAMES = frozenset(
    {"bash", "text_editor", "str_replace_based_edit_tool", "read_file", "grep", "glob"}
)

_API_NAME_TO_LOGICAL: Dict[str, str] = {v: k for k, v in _TOOL_NAMES.items()}

# ---------------------------------------------------------------------------
# Auto-detect latest tool type versions from installed SDK
# ---------------------------------------------------------------------------

_SDK_CLASS_PATTERNS: Dict[str, re.Pattern] = {
    "bash": re.compile(r"^(?:Beta)?ToolBash(\d{8})Param$"),
    "text_editor": re.compile(r"^(?:Beta)?ToolTextEditor(\d{8})Param$"),
    "computer": re.compile(r"^(?:Beta)?ToolComputer(?:Use)?(\d{8})Param$"),
}

_detected_cache: Dict[str, Optional[str]] = {}


def _discover_tool_type(tool_name: str) -> Optional[str]:
    """Scan the anthropic SDK for the latest param class matching *tool_name*.

    The SDK exports classes like ``ToolBash20250124Param`` — we extract the
    date suffix, pick the highest, and return e.g. ``bash_20250124``.
    """
    if tool_name in _detected_cache:
        return _detected_cache[tool_name]

    pattern = _SDK_CLASS_PATTERNS.get(tool_name)
    if pattern is None:
        _detected_cache[tool_name] = None
        return None

    anthropic_mod = sys.modules.get("anthropic")
    if anthropic_mod is None:
        _detected_cache[tool_name] = None
        return None

    types_mod = getattr(anthropic_mod, "types", None)
    if types_mod is None:
        _detected_cache[tool_name] = None
        return None

    versions: List[str] = []
    for attr_name in dir(types_mod):
        m = pattern.match(attr_name)
        if m:
            versions.append(m.group(1))

    if not versions:
        _detected_cache[tool_name] = None
        return None

    latest = max(versions)
    result = f"{tool_name}_{latest}"
    _detected_cache[tool_name] = result
    logger.debug("Auto-detected %s tool type: %s", tool_name, result)
    return result


def validate_tools(
    resolved_tools: List[Dict[str, Any]],
    model: str = "",
) -> None:
    """Log warnings for tools that have no executor or a version mismatch.

    Called at ``GuardedAgent`` startup so configuration errors surface
    immediately rather than mid-conversation.
    """
    prefix = f"GuardedAgent({model})" if model else "GuardedAgent"

    for tool in resolved_tools:
        name = tool.get("name", "")
        tool_type = tool.get("type", "")

        if not name and not tool_type:
            logger.warning("%s: tool with no name or type: %r", prefix, tool)
            continue

        if name in SERVER_TOOLS or tool_type.startswith(
            ("web_search", "web_fetch", "code_execution")
        ):
            continue

        if name and name not in _CLIENT_EXECUTOR_NAMES:
            logger.warning(
                "%s: tool '%s' has no registered executor "
                "— model calls to it will return an error",
                prefix,
                name,
            )

        logical = _API_NAME_TO_LOGICAL.get(name)
        if logical and tool_type:
            detected = _discover_tool_type(logical)
            if detected and detected != tool_type:
                logger.info(
                    "%s: tool '%s' using %s, SDK has %s",
                    prefix,
                    name,
                    tool_type,
                    detected,
                )


def get_tool_type(
    tool_name: str,
    overrides: Optional[Dict[str, str]] = None,
) -> str:
    """Return the Anthropic type string for a built-in tool.

    Resolution order: explicit *overrides* → SDK auto-detect → fallback.
    """
    if overrides and tool_name in overrides:
        return overrides[tool_name]

    detected = _discover_tool_type(tool_name)
    if detected is not None:
        return detected

    return _FALLBACK_TOOL_TYPES[tool_name]


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

_PRESETS: Dict[str, List[str]] = {
    "coding": ["bash", "text_editor", "grep", "glob"],
    "readonly": ["read_file", "grep", "glob"],
    "browser": ["computer", "bash"],
}

# ---------------------------------------------------------------------------
# Custom tool schemas (grep / glob)
# ---------------------------------------------------------------------------

_CUSTOM_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "read_file": {
        "name": "read_file",
        "description": "Read a file from the local filesystem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to read.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (0-based).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read.",
                },
            },
            "required": ["path"],
        },
    },
    "grep": {
        "name": "grep",
        "description": "Search for a pattern in files using regex.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search in. Defaults to cwd.",
                },
                "include": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g. '*.py').",
                },
            },
            "required": ["pattern"],
        },
    },
    "glob": {
        "name": "glob",
        "description": "List files matching a glob pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g. '**/*.py').",
                },
                "path": {
                    "type": "string",
                    "description": "Base directory. Defaults to cwd.",
                },
            },
            "required": ["pattern"],
        },
    },
}


# ---------------------------------------------------------------------------
# Tool resolution
# ---------------------------------------------------------------------------


def resolve_tools(
    tools: Union[str, List[Any]],
    tool_types: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Resolve a tool specification into a list of Anthropic tool dicts.

    *tools* may be:
    - A preset name (``"coding"``, ``"readonly"``, ``"browser"``)
    - A list mixing tool name strings, preset strings, and raw dicts
    """
    if isinstance(tools, str):
        if tools in _PRESETS:
            names = _PRESETS[tools]
        else:
            names = [tools]
        return [_resolve_single(n, tool_types) for n in names]

    result: List[Dict[str, Any]] = []
    for item in tools:
        if isinstance(item, str):
            if item in _PRESETS:
                for name in _PRESETS[item]:
                    result.append(_resolve_single(name, tool_types))
            else:
                result.append(_resolve_single(item, tool_types))
        elif isinstance(item, dict):
            result.append(item)
        else:
            raise ValueError(f"Invalid tool spec: {item!r}")
    return result


def _resolve_single(
    name: str,
    tool_types: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Resolve a single tool name to its Anthropic dict."""
    if name in _CUSTOM_TOOL_SCHEMAS:
        return dict(_CUSTOM_TOOL_SCHEMAS[name])

    if name not in _FALLBACK_TOOL_TYPES:
        raise ValueError(
            f"Unknown tool: {name!r}. "
            f"Known tools: {sorted(_FALLBACK_TOOL_TYPES.keys() | _CUSTOM_TOOL_SCHEMAS.keys())}"
        )

    tool_type = get_tool_type(name, tool_types)
    tool_dict: Dict[str, Any] = {"type": tool_type, "name": _TOOL_NAMES[name]}

    if name == "computer":
        tool_dict["display_width_px"] = 1024
        tool_dict["display_height_px"] = 768

    return tool_dict


def is_server_tool(tool_name: str) -> bool:
    """Return True if *tool_name* is executed server-side by Anthropic."""
    return tool_name in SERVER_TOOLS


# ---------------------------------------------------------------------------
# Client-side tool executors
# ---------------------------------------------------------------------------

_BASH_TIMEOUT = 120


def _resolve_safe_path(raw_path: str, cwd: str) -> Union[Path, str]:
    """Resolve *raw_path* against *cwd*, returning the ``Path`` or an error."""
    resolved = (Path(cwd) / raw_path).resolve()
    if not resolved.is_relative_to(Path(cwd).resolve()):
        return f"Error: path escapes working directory: {raw_path}"
    return resolved


def execute_tool(
    name: str,
    tool_input: Dict[str, Any],
    cwd: Optional[str] = None,
) -> str:
    """Execute a client-side tool and return the result string."""
    cwd = cwd or os.getcwd()

    if name == "bash":
        return _execute_bash(tool_input, cwd)
    if name in ("text_editor", "str_replace_based_edit_tool"):
        return _execute_text_editor(tool_input, cwd)
    if name == "read_file":
        return _execute_read_file(tool_input, cwd)
    if name == "grep":
        return _execute_grep(tool_input, cwd)
    if name == "glob":
        return _execute_glob(tool_input, cwd)

    logger.warning("Tool %r called but has no registered executor", name)
    return f"Error: no executor for tool {name!r}"


def _execute_bash(tool_input: Dict[str, Any], cwd: str) -> str:
    if tool_input.get("restart"):
        return "Shell session restarted."

    command = tool_input.get("command", "")
    if not command:
        return "Error: no command provided."

    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=_BASH_TIMEOUT,
            cwd=cwd,
        )
        output = result.stdout
        if result.stderr:
            output += result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {_BASH_TIMEOUT}s"
    except Exception as e:
        return f"Error executing command: {e}"


def _execute_text_editor(tool_input: Dict[str, Any], cwd: str) -> str:
    command = tool_input.get("command", "")
    raw_path = tool_input.get("path", "")

    if not raw_path:
        return "Error: path is required."

    resolved = _resolve_safe_path(raw_path, cwd)
    if isinstance(resolved, str):
        return resolved

    if command == "view":
        if not resolved.exists():
            return f"Error: {raw_path} does not exist."
        if resolved.is_dir():
            entries = sorted(str(p.relative_to(resolved)) for p in resolved.iterdir())
            return "\n".join(entries) if entries else "(empty directory)"
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"Error reading {raw_path}: {e}"
        view_range = tool_input.get("view_range")
        if view_range and isinstance(view_range, list) and len(view_range) == 2:
            lines = text.splitlines(keepends=True)
            start, end = max(1, view_range[0]), min(len(lines), view_range[1])
            text = "".join(lines[start - 1 : end])
        return text or "(empty file)"

    if command == "create":
        file_text = tool_input.get("file_text", "")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(file_text, encoding="utf-8")
        return f"Created {raw_path}"

    if command == "str_replace":
        if not resolved.exists():
            return f"Error: {raw_path} does not exist."
        old_str = tool_input.get("old_str", "")
        new_str = tool_input.get("new_str", "")
        try:
            content = resolved.read_text(encoding="utf-8")
        except Exception as e:
            return f"Error reading {raw_path}: {e}"
        count = content.count(old_str)
        if count == 0:
            return f"Error: old_str not found in {raw_path}"
        if count > 1:
            return f"Error: old_str found {count} times in {raw_path} (must be unique)"
        content = content.replace(old_str, new_str, 1)
        resolved.write_text(content, encoding="utf-8")
        return f"Replaced in {raw_path}"

    if command == "insert":
        if not resolved.exists():
            return f"Error: {raw_path} does not exist."
        insert_line = tool_input.get("insert_line", 0)
        insert_text = tool_input.get("new_str", tool_input.get("insert_text", ""))
        try:
            lines = resolved.read_text(encoding="utf-8").splitlines(keepends=True)
        except Exception as e:
            return f"Error reading {raw_path}: {e}"
        insert_line = max(0, min(insert_line, len(lines)))
        if not insert_text.endswith("\n"):
            insert_text += "\n"
        lines.insert(insert_line, insert_text)
        resolved.write_text("".join(lines), encoding="utf-8")
        return f"Inserted at line {insert_line} in {raw_path}"

    return f"Error: unknown text_editor command: {command!r}"


def _execute_read_file(tool_input: Dict[str, Any], cwd: str) -> str:
    raw_path = tool_input.get("path", "")
    if not raw_path:
        return "Error: path is required."

    resolved = _resolve_safe_path(raw_path, cwd)
    if isinstance(resolved, str):
        return resolved

    if not resolved.exists():
        return f"Error: {raw_path} does not exist."
    if resolved.is_dir():
        entries = sorted(str(p.relative_to(resolved)) for p in resolved.iterdir())
        return "\n".join(entries) if entries else "(empty directory)"

    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading {raw_path}: {e}"

    offset = tool_input.get("offset", 0)
    limit = tool_input.get("limit")
    if not offset and limit is None:
        return text or "(empty file)"

    lines = text.splitlines(keepends=True)
    if offset:
        lines = lines[offset:]
    if limit is not None:
        lines = lines[:limit]

    return "".join(lines) or "(empty file)"


def _execute_grep(tool_input: Dict[str, Any], cwd: str) -> str:
    from ai_guardian.patterns.language import SKIP_DIRS

    pattern = tool_input.get("pattern", "")
    if not pattern:
        return "Error: pattern is required."

    search_path = tool_input.get("path", ".")
    safe = _resolve_safe_path(search_path, cwd)
    if isinstance(safe, str):
        return safe

    exclude_flags = [f"--exclude-dir={d}" for d in SKIP_DIRS if "*" not in d]
    include_flags = (
        [f"--include={tool_input['include']}"] if tool_input.get("include") else []
    )
    cmd = ["grep", "-rn"] + exclude_flags + include_flags + [pattern, search_path]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        return result.stdout or "(no matches)"
    except subprocess.TimeoutExpired:
        return "Error: grep timed out"
    except Exception as e:
        return f"Error running grep: {e}"


def _execute_glob(tool_input: Dict[str, Any], cwd: str) -> str:
    from ai_guardian.patterns.language import SKIP_DIRS

    pattern = tool_input.get("pattern", "")
    if not pattern:
        return "Error: pattern is required."

    base = _resolve_safe_path(tool_input.get("path", "."), cwd)
    if isinstance(base, str):
        return base

    try:
        matches = sorted(
            str(p.relative_to(base))
            for p in base.glob(pattern)
            if p.is_file() and not any(ex in p.parts for ex in SKIP_DIRS)
        )
    except Exception as e:
        return f"Error: {e}"

    if not matches:
        return "(no matches)"
    return "\n".join(matches[:1000])
