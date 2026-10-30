"""Native tool argument normalization and value-free input diagnostics.

Only schema-recognized keys and JSON type labels enter diagnostics. Native
payloads remain in memory; a file alias is never inferred for unrelated tools.
"""

import os
from typing import Any, Dict, Optional, Tuple

from ai_guardian.constants import (
    AUGMENT_TOOL_MAP,
    OPENCODE_EDIT_INPUT_MAP,
    OPENCODE_TOOL_MAP,
)

FILE_TOOLS = frozenset({"Read", "Write", "Edit", "NotebookEdit"})
OPENCODE_FILE_TOOLS = frozenset({"Read", "Write", "Edit"})
FILE_PATH_KEYS = ("path", "filePath", "file_path")
ARGUMENT_KEYS_BY_TOOL = {
    "Read": (*FILE_PATH_KEYS, "offset", "limit"),
    "Write": (*FILE_PATH_KEYS, "content"),
    "Edit": (
        *FILE_PATH_KEYS,
        "oldString",
        "newString",
        "replaceAll",
        "old_string",
        "new_string",
        "replace_all",
    ),
    "NotebookEdit": ("file_path", "cell_id", "cell_type", "edit_mode", "new_source"),
    "Bash": ("command", "description", "timeout", "workdir"),
    "Shell": ("command", "description", "timeout", "workdir"),
}
NATIVE_TOOL_NAMES = frozenset(
    {*OPENCODE_TOOL_MAP, *AUGMENT_TOOL_MAP, *ARGUMENT_KEYS_BY_TOOL}
)
INPUT_FAILURE_LABELS = {
    "missing_argument": "Missing required parameter",
    "empty_argument": "Empty required parameter",
    "invalid_argument": "Invalid required parameter",
    "conflicting_arguments": "Conflicting file path parameters",
    "normalization_failure": "Tool input normalization failed",
    "workspace_unavailable": "Tool workspace is unknown",
}
DIAGNOSTIC_SUBREASONS = frozenset(
    {*INPUT_FAILURE_LABELS, "immutable_protection", "permission_denied"}
)
JSON_TYPES = frozenset(
    {"object", "array", "string", "boolean", "integer", "number", "null", "unknown"}
)


def is_opencode_hook(hook_data: Dict) -> bool:
    return bool(
        hook_data.get("opencode_version")
        or hook_data.get("hook_source") == "opencode"
        or str(hook_data.get("_ide_type", "")).lower() == "opencode"
        or os.environ.get("AI_GUARDIAN_IDE_TYPE", "").lower() == "opencode"
    )


def opencode_native_input(hook_data: Dict) -> Any:
    """Read the host payload, not a possibly conflicting canonical wrapper."""
    tool_use = hook_data.get("tool_use")
    if isinstance(tool_use, dict):
        for key in ("input", "parameters"):
            if key in tool_use:
                return tool_use[key]
    return hook_data.get("tool_input", {})


def opencode_native_name(hook_data: Dict) -> Optional[str]:
    tool_use = hook_data.get("tool_use")
    name = tool_use.get("name") if isinstance(tool_use, dict) else None
    return name if isinstance(name, str) and name else hook_data.get("tool_name")


def _windows_shell_path(value: str) -> str:
    """Resolve OpenCode's drive aliases without interpreting ordinary directories."""
    for prefix in ("/cygdrive/", "/mnt/", "/"):
        if not value.startswith(prefix):
            continue
        tail = value[len(prefix) :]
        if (
            not tail
            or tail[0] not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        ):
            continue
        if len(tail) == 1 or tail[1] == "/":
            return tail[0].upper() + ":/" + tail[2:]
        if prefix == "/" and tail[1:2] == ":" and (len(tail) == 2 or tail[2] in "/\\"):
            return tail[0].upper() + ":/" + tail[3:]
    return value


def effective_file_path(value: Any, cwd: Any = None) -> Optional[str]:
    """Resolve host-relative paths lexically, without opening the target."""
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        return None
    # OpenCode 2.0.24 FileAccess.resolvePath / FSUtil.windowsPath (MIT):
    # https://github.com/anomalyco/opencode/blob/v2.0.24/packages/core/src/file-access.ts
    if os.name == "nt":
        value = _windows_shell_path(value)
        drive, _ = os.path.splitdrive(value)
        if drive and not os.path.isabs(value):
            # A drive-relative target depends on hidden per-drive process CWD.
            return None
    home_relative = value.startswith("~/") or (
        os.name == "nt" and value.startswith("~\\")
    )
    if value == "~" or home_relative:
        home = os.path.expanduser("~")
        if not os.path.isabs(home):
            return None
        value = os.path.join(home, value[2:]) if home_relative else home
    if isinstance(cwd, str) and os.path.isabs(cwd) and "\0" not in cwd:
        return os.path.normpath(os.path.join(cwd, value))
    # Without an authoritative workspace, preserve the native spelling. The
    # bridge rejects unknown runtime workspaces; standalone adapter callers
    # retain their legacy argument representation instead of inventing a base.
    return value


def valid_workspace(value: Any) -> Optional[str]:
    """Accept bounded absolute workspace metadata, never stringify payloads."""
    if (
        isinstance(value, str)
        and 0 < len(value) <= 4096
        and value.isprintable()
        and os.path.isabs(value)
    ):
        return value
    return None


def _file_target(
    tool_input: Any, keys: Tuple[str, ...], cwd: Any
) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(tool_input, dict):
        return "invalid_argument", None
    present = [key for key in keys if key in tool_input]
    if not present:
        return "missing_argument", None
    targets = []
    for key in present:
        value = tool_input[key]
        if isinstance(value, str) and not value.strip():
            return "empty_argument", None
        target = effective_file_path(value, cwd)
        if target is None:
            return "invalid_argument", None
        targets.append(target)
    if len({os.path.normcase(target) for target in targets}) != 1:
        return "conflicting_arguments", None
    return None, targets[0]


def normalize_opencode_input(
    tool_name: Optional[str], tool_input: Any, cwd: Any = None
) -> Dict:
    normalized = dict(tool_input) if isinstance(tool_input, dict) else {}
    if tool_name not in OPENCODE_FILE_TOOLS:
        return normalized
    failure, target = _file_target(tool_input, FILE_PATH_KEYS, cwd)
    # Preserve native aliases in this private in-memory copy. A conflicting or
    # malformed canonical value must not become a fallback target for scanning.
    normalized["file_path"] = target if failure is None else None
    if tool_name == "Edit":
        for native_key, canonical_key in OPENCODE_EDIT_INPUT_MAP.items():
            if canonical_key not in normalized and native_key in normalized:
                normalized[canonical_key] = normalized[native_key]
    return normalized


def file_input_failure(
    tool_name: str,
    raw_input: Any,
    normalized: Dict,
    cwd: Any = None,
    *,
    opencode: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    keys = (
        FILE_PATH_KEYS
        if opencode and tool_name in OPENCODE_FILE_TOOLS
        else ("file_path",)
    )
    failure, target = _file_target(raw_input, keys, cwd)
    if failure:
        return failure, None
    if effective_file_path(normalized.get("file_path"), cwd) != target:
        return "normalization_failure", target
    return None, target


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "unknown"


def build_input_diagnostics(
    hook_data: Dict,
    tool_name: str,
    subreason: str,
    *,
    normalized_input: Any,
    target_known: bool = False,
) -> Dict:
    opencode = is_opencode_hook(hook_data)
    raw_input = opencode_native_input(hook_data) if opencode else normalized_input
    native = (
        opencode_native_name(hook_data)
        if opencode
        else hook_data.get("toolName") or hook_data.get("tool_name")
    )
    if not opencode:
        for container_key in ("tool_use", "tool", "toolCall", "tool_info"):
            container = hook_data.get(container_key)
            if isinstance(container, dict) and isinstance(container.get("name"), str):
                native = container["name"]
                break
    recognized = ARGUMENT_KEYS_BY_TOOL.get(tool_name, ())
    shape = {
        key: json_type(raw_input[key])
        for key in recognized
        if isinstance(raw_input, dict) and key in raw_input
    }
    expected = (
        "file_path"
        if tool_name in FILE_TOOLS
        else "command" if tool_name in {"Bash", "Shell"} else None
    )
    if opencode and tool_name in OPENCODE_FILE_TOOLS:
        version = hook_data.get("opencode_version", "")
        major = version.split(".")[0] if isinstance(version, str) else ""
        expected = "path" if major == "2" else "filePath" if major == "1" else None
    return {
        "schema_version": 1,
        "subreason": (
            subreason if subreason in DIAGNOSTIC_SUBREASONS else "permission_denied"
        ),
        "native_tool_name": (
            native if isinstance(native, str) and native in NATIVE_TOOL_NAMES else None
        ),
        "canonical_tool_name": (
            tool_name if tool_name in ARGUMENT_KEYS_BY_TOOL else None
        ),
        "expected_field": expected,
        "input_type": json_type(raw_input),
        "argument_shape": shape,
        "unrecognized_argument_count": (
            min(10000, len(raw_input) - len(shape))
            if isinstance(raw_input, dict)
            else 0
        ),
        "target_status": "known" if target_known else "unknown",
    }
