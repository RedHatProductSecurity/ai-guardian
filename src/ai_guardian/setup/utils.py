"""Shared utility functions for ai-guardian setup modules."""

import platform
import re
import shutil
from pathlib import Path
from typing import Dict, Optional


def _resolve_binary_path() -> str:
    """Resolve absolute path to ai-guardian binary at setup time.

    On Windows, prefers ``pythonw.exe -m ai_guardian`` to avoid console
    window flash on every hook invocation (see issue #902).
    """
    if platform.system() == "Windows":
        pythonw = shutil.which("pythonw")
        if pythonw:
            return f"{pythonw} -m ai_guardian"
    path = shutil.which("ai-guardian")
    if path:
        return path
    return "ai-guardian"


def _is_ai_guardian_command(cmd: str) -> bool:
    """Check if a command string refers to ai-guardian (bare or absolute path).

    Handles commands with trailing arguments like ``--ide cursor``,
    Windows backslash paths, ``.exe`` suffixes, and the
    ``pythonw.exe -m ai_guardian`` invocation used on Windows.
    """
    if not cmd:
        return False
    first_token = cmd.split()[0]
    base = Path(first_token).stem
    if base in ("ai-guardian", "ai-guardian.exe"):
        return True
    if first_token == "ai-guardian" or first_token.endswith(
        ("/ai-guardian", "\\ai-guardian")
    ):
        return True
    if first_token.endswith(("/ai-guardian.exe", "\\ai-guardian.exe")):
        return True
    if "-m" in cmd and "ai_guardian" in cmd:
        return True
    return False


def _walk_commands(obj, predicate, transform, *, copy=True):
    """Walk a config tree, applying *transform* to ``command`` values matching *predicate*.

    Args:
        obj: Config structure (dict, list, or scalar).
        predicate: ``callable(value) -> bool`` — whether to transform this command value.
        transform: ``callable(value) -> new_value``.
        copy: If ``True``, return a new object tree. If ``False``, mutate *obj* in place.
    """
    if isinstance(obj, dict):
        if copy:
            result = {}
            for k, v in obj.items():
                if k == "command" and predicate(v):
                    result[k] = transform(v)
                else:
                    result[k] = _walk_commands(v, predicate, transform, copy=True)
            return result
        else:
            for k, v in obj.items():
                if k == "command" and predicate(v):
                    obj[k] = transform(v)
                else:
                    _walk_commands(v, predicate, transform, copy=False)
    elif isinstance(obj, list):
        if copy:
            return [
                _walk_commands(item, predicate, transform, copy=True) for item in obj
            ]
        else:
            for item in obj:
                _walk_commands(item, predicate, transform, copy=False)
    elif copy:
        return obj


def _substitute_command(obj, abs_path: str, ide_type: str = None):
    """Recursively replace bare 'ai-guardian' command values with abs_path.

    When *ide_type* is provided the ``--ide <name>`` flag is appended so the
    hook command explicitly declares which adapter to use.
    """
    cmd = f"{abs_path} --ide {ide_type}" if ide_type else abs_path
    return _walk_commands(
        obj,
        predicate=lambda v: v in ("ai-guardian", "ai-guardian.exe"),
        transform=lambda _v: cmd,
        copy=True,
    )


def _upgrade_ide_flag(obj, ide_type: str):
    """Add ``--ide <name>`` to existing ai-guardian commands that lack it.

    After merging hooks, pre-existing ai-guardian entries written by an older
    version may not carry the ``--ide`` flag.  This helper walks the merged
    config and upgrades them in place.
    """
    _walk_commands(
        obj,
        predicate=lambda v: isinstance(v, str)
        and _is_ai_guardian_command(v)
        and "--ide" not in v,
        transform=lambda v: f"{v} --ide {ide_type}",
        copy=False,
    )


def _create_vbs_wrapper(cmd: str, config_dir: Path) -> Optional[Path]:
    """Create a VBS wrapper for fully hidden execution on Windows.

    The wrapper uses ``WScript.Shell.Run`` with window style 0 (hidden) so
    that neither ``pythonw.exe`` nor a transient console flash is visible.
    Users can point their hook command to
    ``wscript.exe <path>`` for maximum suppression.

    Returns the path to the generated ``.vbs`` file, or *None* on non-Windows.
    """
    if platform.system() != "Windows":
        return None
    vbs_path = config_dir / "ai-guardian-hook.vbs"
    content = (
        'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run "{cmd}", 0, True\n'
    )
    config_dir.mkdir(parents=True, exist_ok=True)
    vbs_path.write_text(content, encoding="utf-8")
    return vbs_path


def _notify_daemon_reload():
    """Notify daemon to reload config if running. Silent on failure."""
    try:
        from ai_guardian.daemon.client import send_reload_config

        if send_reload_config():
            print("Daemon reloaded with new configuration")
    except Exception:
        pass  # intentionally silent — optional dependency


def _strip_deprecated_config_keys(config: Dict) -> Dict:
    """Remove deprecated config keys so new configs never contain them."""
    ss = config.get("secret_scanning")
    if isinstance(ss, dict):
        ss.pop("pattern_server", None)
    config.pop("pattern_server", None)
    return config


def _strip_jsonc_comments(text: str) -> str:
    """Strip single-line (//) and multi-line (/* */) comments from JSONC.

    Quote-aware: skips // and /* inside JSON string literals.
    """
    result = []
    i = 0
    in_string = False
    while i < len(text):
        c = text[i]
        if in_string:
            result.append(c)
            if c == "\\" and i + 1 < len(text):
                i += 1
                result.append(text[i])
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
            result.append(c)
        elif c == "/" and i + 1 < len(text) and text[i + 1] == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        elif c == "/" and i + 1 < len(text) and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = end + 2 if end != -1 else len(text)
            continue
        else:
            result.append(c)
        i += 1
    stripped = "".join(result)
    stripped = re.sub(r",\s*([}\]])", r"\1", stripped)
    return stripped


def _resolve_opencode_config() -> Path:
    """Find existing OpenCode config or return default path.

    Priority: opencode.json (if exists) > opencode.jsonc (if exists) > new opencode.jsonc.
    """
    base = Path("~/.config/opencode").expanduser()
    for name in ("opencode.json", "opencode.jsonc"):
        candidate = base / name
        if candidate.exists():
            return candidate
    return base / "opencode.jsonc"
