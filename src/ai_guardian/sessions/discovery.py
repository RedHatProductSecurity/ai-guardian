"""IDE session discovery — locate session files for each supported IDE."""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

SUPPORTED_IDES = [
    "claude",
    "cursor",
    "copilot",
    "codex",
    "windsurf",
    "gemini",
    "cline",
    "kiro",
]

_IDE_SESSION_DIRS = {
    "claude": {
        "env": "CLAUDE_CONFIG_DIR",
        "default_mac": "~/.claude/projects",
        "default_linux": "~/.claude/projects",
        "default_win": "~/.claude/projects",
        "pattern": "*.jsonl",
    },
    "cursor": {
        "env": "CURSOR_DATA_DIR",
        "default_mac": "~/Library/Application Support/Cursor/User/globalStorage",
        "default_linux": "~/.config/Cursor/User/globalStorage",
        "default_win": "%APPDATA%/Cursor/User/globalStorage",
        "file": "state.vscdb",
    },
    "copilot": {
        "env": "COPILOT_CHAT_DATA_DIR",
        "default_mac": "~/Library/Application Support/Code/User",
        "default_linux": "~/.config/Code/User",
        "default_win": "%APPDATA%/Code/User",
        "subdir_glob": "workspaceStorage/*/chatSessions",
        "pattern": "*.jsonl",
    },
    "windsurf": {
        "env": "WINDSURF_TRANSCRIPTS_DIR",
        "default_mac": "~/.windsurf/transcripts",
        "default_linux": "~/.windsurf/transcripts",
        "default_win": "~/.windsurf/transcripts",
        "pattern": "*.jsonl",
    },
    "kiro": {
        "env": "KIRO_SESSIONS_DIR",
        "default_mac": "~/.kiro/sessions/cli",
        "default_linux": "~/.kiro/sessions/cli",
        "default_win": "~/.kiro/sessions/cli",
        "pattern": "*.jsonl",
    },
    "cline": {
        "env": "CLINE_STORAGE_DIR",
        "default_mac": "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev",
        "default_linux": "~/.config/Code/User/globalStorage/saoudrizwan.claude-dev",
        "default_win": "%APPDATA%/Code/User/globalStorage/saoudrizwan.claude-dev",
    },
    "codex": {
        "env": "CODEX_HOME",
        "default_mac": "~/.codex",
        "default_linux": "~/.codex",
        "default_win": "~/.codex",
    },
    "gemini": {
        "env": "GEMINI_CLI_HOME",
        "default_mac": "~/.gemini",
        "default_linux": "~/.gemini",
        "default_win": "~/.gemini",
    },
}


def get_supported_ides() -> List[str]:
    """Return list of supported IDE identifiers."""
    return list(SUPPORTED_IDES)


def get_default_ide(config: Optional[Dict] = None) -> str:
    """Resolve default IDE using config -> auto-detect -> fallback.

    Resolution order:
    1. session_viewer.default_ide in config (explicit)
    2. Auto-detect from installed hooks (which IDE has hooks configured)
    3. First IDE with sessions found on disk
    """
    if config:
        explicit = (
            config.get("session_viewer", {}).get("default_ide", "").strip().lower()
        )
        if explicit and explicit in SUPPORTED_IDES:
            return explicit

    for ide in SUPPORTED_IDES:
        session_dir = _resolve_session_dir(ide)
        if session_dir and session_dir.exists():
            return ide

    return "claude"


def discover_sessions(
    ide: str,
    project_path: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Discover sessions for a given IDE.

    Returns list of session metadata dicts sorted by last modified (newest first).
    """
    ide = ide.lower()
    if ide not in SUPPORTED_IDES:
        logger.warning("Unsupported IDE: %s", ide)
        return []

    if ide == "claude":
        return _discover_claude_sessions(project_path, limit)
    if ide == "cursor":
        return _discover_cursor_sessions(project_path, limit)
    if ide == "copilot":
        return _discover_copilot_sessions(project_path, limit)
    if ide == "windsurf":
        return _discover_generic_jsonl_sessions(ide, project_path, limit)
    if ide == "kiro":
        return _discover_generic_jsonl_sessions(ide, project_path, limit)

    return _discover_placeholder_sessions(ide, project_path, limit)


def _resolve_session_dir(ide: str) -> Optional[Path]:
    """Resolve the session storage directory for an IDE."""
    info = _IDE_SESSION_DIRS.get(ide)
    if not info:
        return None

    env_val = os.environ.get(info["env"], "")
    if env_val:
        return Path(os.path.expandvars(env_val)).expanduser()

    import sys

    if sys.platform == "darwin":
        key = "default_mac"
    elif sys.platform == "win32":
        key = "default_win"
    else:
        key = "default_linux"

    default = info.get(key, "")
    if default:
        return Path(os.path.expandvars(default)).expanduser()

    return None


def _discover_claude_sessions(
    project_path: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Discover Claude Code sessions from ~/.claude/projects/."""
    base = _resolve_session_dir("claude")
    if not base or not base.is_dir():
        return []

    sessions = []
    project_dirs = []

    if project_path:
        encoded = project_path.replace("/", "-")
        if encoded.startswith("-"):
            pass
        else:
            encoded = f"-{encoded}"
        target = base / encoded
        if target.is_dir():
            project_dirs.append(target)
    else:
        try:
            project_dirs = [d for d in base.iterdir() if d.is_dir()]
        except OSError:
            return []

    for proj_dir in project_dirs:
        proj_name = proj_dir.name
        decoded_path = _decode_claude_project_name(proj_name)

        try:
            jsonl_files = sorted(
                proj_dir.glob("*.jsonl"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            continue

        for jf in jsonl_files[:limit]:
            session_id = jf.stem
            try:
                stat = jf.stat()
                meta = _read_claude_session_meta(jf)
                sessions.append(
                    {
                        "ide": "claude",
                        "session_id": session_id,
                        "project_path": decoded_path,
                        "project_dir_name": proj_name,
                        "file_path": str(jf),
                        "size_bytes": stat.st_size,
                        "modified": stat.st_mtime,
                        "title": meta.get("title", ""),
                        "model": meta.get("model", ""),
                        "message_count": meta.get("message_count", 0),
                        "token_usage": meta.get("token_usage", {}),
                    }
                )
            except OSError:
                continue

    sessions.sort(key=lambda s: s.get("modified", 0), reverse=True)
    return sessions[:limit]


def _decode_claude_project_name(encoded: str) -> str:
    """Decode Claude's project directory name back to a path."""
    if encoded.startswith("-"):
        return encoded.replace("-", "/")
    return encoded


def _read_claude_session_meta(path: Path) -> Dict:
    """Read minimal metadata from a Claude session JSONL file."""
    meta: Dict = {
        "title": "",
        "model": "",
        "message_count": 0,
        "token_usage": {},
    }

    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_create = 0
    msg_count = 0

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                msg_type = d.get("type", "")

                if msg_type == "ai-title":
                    meta["title"] = d.get("aiTitle", "")

                elif msg_type == "assistant":
                    msg = d.get("message", {})
                    if not meta["model"] and msg.get("model"):
                        meta["model"] = msg["model"]
                    usage = msg.get("usage", {})
                    total_input += usage.get("input_tokens", 0)
                    total_output += usage.get("output_tokens", 0)
                    total_cache_read += usage.get("cache_read_input_tokens", 0)
                    total_cache_create += usage.get("cache_creation_input_tokens", 0)
                    msg_count += 1

                elif msg_type == "user":
                    msg_count += 1
    except OSError:
        pass

    meta["message_count"] = msg_count
    meta["token_usage"] = {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cache_read_input_tokens": total_cache_read,
        "cache_creation_input_tokens": total_cache_create,
    }
    return meta


def _discover_cursor_sessions(
    project_path: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Discover Cursor IDE sessions from state.vscdb."""
    session_dir = _resolve_session_dir("cursor")
    if not session_dir:
        return []

    db_path = session_dir / "state.vscdb"
    if not db_path.exists():
        return []

    sessions = []
    try:
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT key, value FROM cursorDiskKV "
            "WHERE key LIKE 'composerData:%' "
            "ORDER BY key DESC LIMIT ?",
            (limit,),
        )
        for key, value in cursor.fetchall():
            try:
                data = json.loads(value) if isinstance(value, str) else value
                if isinstance(data, bytes):
                    data = json.loads(data.decode("utf-8"))
                session_id = key.split(":", 1)[-1] if ":" in key else key
                sessions.append(
                    {
                        "ide": "cursor",
                        "session_id": session_id,
                        "project_path": data.get("workspacePath", ""),
                        "file_path": str(db_path),
                        "size_bytes": 0,
                        "modified": 0,
                        "title": data.get("name", ""),
                        "model": data.get("model", ""),
                        "message_count": len(data.get("messages", [])),
                        "token_usage": {},
                    }
                )
            except (json.JSONDecodeError, ValueError):
                continue
        conn.close()
    except Exception as exc:
        logger.debug("Failed to read Cursor sessions: %s", exc)

    return sessions[:limit]


def _discover_copilot_sessions(
    project_path: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Discover Copilot Chat sessions from VS Code storage."""
    base = _resolve_session_dir("copilot")
    if not base or not base.is_dir():
        return []

    sessions = []
    patterns = [
        base / "workspaceStorage" / "*" / "chatSessions" / "*.jsonl",
        base / "globalStorage" / "emptyWindowChatSessions" / "*.jsonl",
    ]

    import glob

    for pat in patterns:
        for fpath in glob.glob(str(pat)):
            fp = Path(fpath)
            try:
                stat = fp.stat()
                session_id = fp.stem
                sessions.append(
                    {
                        "ide": "copilot",
                        "session_id": session_id,
                        "project_path": "",
                        "file_path": str(fp),
                        "size_bytes": stat.st_size,
                        "modified": stat.st_mtime,
                        "title": "",
                        "model": "",
                        "message_count": 0,
                        "token_usage": {},
                    }
                )
            except OSError:
                continue

    sessions.sort(key=lambda s: s.get("modified", 0), reverse=True)
    return sessions[:limit]


def _discover_generic_jsonl_sessions(
    ide: str,
    project_path: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Discover sessions from a directory of JSONL files."""
    base = _resolve_session_dir(ide)
    if not base or not base.is_dir():
        return []

    sessions = []
    try:
        jsonl_files = sorted(
            base.rglob("*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []

    for jf in jsonl_files[:limit]:
        try:
            stat = jf.stat()
            sessions.append(
                {
                    "ide": ide,
                    "session_id": jf.stem,
                    "project_path": "",
                    "file_path": str(jf),
                    "size_bytes": stat.st_size,
                    "modified": stat.st_mtime,
                    "title": "",
                    "model": "",
                    "message_count": 0,
                    "token_usage": {},
                }
            )
        except OSError:
            continue

    return sessions[:limit]


def _discover_placeholder_sessions(
    ide: str,
    project_path: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Placeholder for IDEs without full session discovery yet."""
    base = _resolve_session_dir(ide)
    if not base or not base.is_dir():
        return []
    return []
