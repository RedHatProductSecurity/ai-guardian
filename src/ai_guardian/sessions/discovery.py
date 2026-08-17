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
        "default_mac": "~/.codex/sessions",
        "default_linux": "~/.codex/sessions",
        "default_win": "~/.codex/sessions",
    },
    "gemini": {
        "env": "GEMINI_CLI_HOME",
        "default_mac": "~/.gemini/tmp",
        "default_linux": "~/.gemini/tmp",
        "default_win": "~/.gemini/tmp",
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
    if ide == "codex":
        return _discover_codex_sessions(project_path, limit)
    if ide == "gemini":
        return _discover_gemini_sessions(project_path, limit)
    if ide == "cline":
        return _discover_cline_sessions(project_path, limit)
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
    """Read metadata from a Claude session JSONL file.

    Returns title, model, message_count, token_usage, plus
    first/last timestamps and user/assistant message counts.
    """
    meta: Dict = {
        "title": "",
        "model": "",
        "message_count": 0,
        "token_usage": {},
        "first_timestamp": "",
        "last_timestamp": "",
        "user_messages": 0,
        "assistant_messages": 0,
    }

    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_create = 0
    user_count = 0
    assistant_count = 0

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
                ts = d.get("timestamp", "")

                if ts:
                    if not meta["first_timestamp"]:
                        meta["first_timestamp"] = ts
                    meta["last_timestamp"] = ts

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
                    assistant_count += 1

                elif msg_type == "user":
                    user_count += 1
    except OSError:
        pass

    meta["message_count"] = user_count + assistant_count
    meta["user_messages"] = user_count
    meta["assistant_messages"] = assistant_count
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
    """Discover Cursor IDE sessions from state.vscdb composerHeaders table."""
    session_dir = _resolve_session_dir("cursor")
    if not session_dir:
        return []

    db_path = session_dir / "state.vscdb"
    if not db_path.exists():
        return []

    sessions = []
    try:
        import sqlite3

        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = conn.cursor()

        cur.execute(
            "SELECT composerId, workspaceId, createdAt, lastUpdatedAt, value "
            "FROM composerHeaders "
            "WHERE composerId != 'empty-state-draft' "
            "ORDER BY lastUpdatedAt DESC LIMIT ?",
            (limit,),
        )
        for (
            composer_id,
            workspace_id,
            created_at,
            updated_at,
            value_str,
        ) in cur.fetchall():
            try:
                header = json.loads(value_str) if isinstance(value_str, str) else {}
            except (json.JSONDecodeError, ValueError):
                header = {}

            name = header.get("name", "")
            workspace_info = header.get("workspaceIdentifier", {})
            ws_uri = workspace_info.get("uri", {})
            ws_path = ws_uri.get("fsPath", "") if isinstance(ws_uri, dict) else ""

            if project_path and ws_path and project_path not in ws_path:
                continue

            bubble_count = 0
            try:
                cur.execute(
                    "SELECT COUNT(*) FROM cursorDiskKV " "WHERE key LIKE ?",
                    (f"bubbleId:{composer_id}:%",),
                )
                row = cur.fetchone()
                if row:
                    bubble_count = row[0]
            except Exception:
                pass

            modified_ts = (updated_at or 0) / 1000.0

            mode = header.get("unifiedMode", "")
            ctx_pct = header.get("contextUsagePercent", 0)

            sessions.append(
                {
                    "ide": "cursor",
                    "session_id": composer_id,
                    "project_path": ws_path,
                    "file_path": str(db_path),
                    "size_bytes": 0,
                    "modified": modified_ts,
                    "title": name or header.get("subtitle", ""),
                    "model": "",
                    "message_count": bubble_count,
                    "token_usage": {},
                    "context_usage_percent": ctx_pct,
                    "mode": mode or "",
                }
            )

        conn.close()
    except Exception as exc:
        logger.debug("Failed to read Cursor sessions: %s", exc)

    return sessions[:limit]


def _discover_copilot_sessions(
    project_path: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Discover Copilot Chat sessions from VS Code delta journal files."""
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
                meta = _read_copilot_session_meta(fp)
                sessions.append(
                    {
                        "ide": "copilot",
                        "session_id": session_id,
                        "project_path": "",
                        "file_path": str(fp),
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


def _read_copilot_session_meta(path: Path) -> Dict:
    """Read metadata from a Copilot Chat delta journal JSONL."""
    meta: Dict = {"title": "", "model": "", "message_count": 0, "token_usage": {}}
    total_prompt = 0
    total_completion = 0
    request_count = 0

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                kind = d.get("kind", -1)
                if kind == 0:
                    v = d.get("v", {})
                    reqs = v.get("requests", [])
                    request_count += len(reqs)
                    for req in reqs:
                        msg = req.get("message", {})
                        if not meta["title"] and msg.get("text"):
                            meta["title"] = msg["text"][:80]
                        if not meta["model"] and req.get("modelId"):
                            meta["model"] = req["modelId"]
                elif kind == 1:
                    key_path = d.get("k", [])
                    val = d.get("v")
                    if (
                        len(key_path) == 3
                        and key_path[0] == "requests"
                        and key_path[2] == "promptTokens"
                    ):
                        total_prompt += val or 0
                    elif (
                        len(key_path) == 3
                        and key_path[0] == "requests"
                        and key_path[2] == "completionTokens"
                    ):
                        total_completion += val or 0
                elif kind == 2:
                    key_path = d.get("k", [])
                    if key_path == ["requests"]:
                        request_count += 1
    except OSError:
        pass

    meta["message_count"] = request_count
    meta["token_usage"] = {
        "input_tokens": total_prompt,
        "output_tokens": total_completion,
    }
    return meta


def _discover_codex_sessions(
    project_path: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Discover Codex CLI sessions from ~/.codex/sessions/."""
    base = _resolve_session_dir("codex")
    if not base or not base.is_dir():
        return []

    sessions = []
    try:
        jsonl_files = sorted(
            base.rglob("*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        zst_files = sorted(
            base.rglob("*.jsonl.zst"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []

    for jf in list(jsonl_files) + list(zst_files):
        if len(sessions) >= limit:
            break
        try:
            stat = jf.stat()
            meta = _read_codex_session_meta(jf)
            sessions.append(
                {
                    "ide": "codex",
                    "session_id": jf.stem.replace(".jsonl", ""),
                    "project_path": meta.get("cwd", ""),
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


def _read_codex_session_meta(path: Path) -> Dict:
    """Read metadata from a Codex session JSONL file."""
    meta: Dict = {
        "title": "",
        "model": "",
        "cwd": "",
        "message_count": 0,
        "token_usage": {},
    }
    if str(path).endswith(".zst"):
        return meta

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

                rtype = d.get("type", "")
                if rtype == "session_meta":
                    payload = d.get("payload", {})
                    meta["cwd"] = payload.get("cwd", "")
                    meta["model"] = payload.get("model", "")
                elif rtype == "response_item":
                    payload = d.get("payload", {})
                    if payload.get("role") in ("user", "assistant"):
                        msg_count += 1
                        if not meta["title"] and payload.get("role") == "user":
                            content = payload.get("content", [])
                            if isinstance(content, list):
                                for c in content:
                                    if isinstance(c, dict) and c.get("text"):
                                        meta["title"] = c["text"][:80]
                                        break
                            elif isinstance(content, str):
                                meta["title"] = content[:80]
    except OSError:
        pass

    meta["message_count"] = msg_count
    return meta


def _discover_gemini_sessions(
    project_path: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Discover Gemini CLI sessions from ~/.gemini/tmp/<hash>/chats/."""
    base = _resolve_session_dir("gemini")
    if not base or not base.is_dir():
        return []

    sessions = []
    try:
        session_files = sorted(
            list(base.rglob("session-*.json")) + list(base.rglob("session-*.jsonl")),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []

    for sf in session_files[:limit]:
        try:
            stat = sf.stat()
            project_hash_dir = sf.parent.parent.name
            sessions.append(
                {
                    "ide": "gemini",
                    "session_id": sf.stem,
                    "project_path": project_hash_dir,
                    "file_path": str(sf),
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


def _discover_cline_sessions(
    project_path: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Discover Cline sessions from ~/.cline/data/tasks/ or globalStorage."""
    sessions = []

    search_dirs = []
    cline_home = Path("~/.cline/data/tasks").expanduser()
    if cline_home.is_dir():
        search_dirs.append(cline_home)

    legacy = _resolve_session_dir("cline")
    if legacy:
        legacy_tasks = legacy / "tasks"
        if legacy_tasks.is_dir() and legacy_tasks != cline_home:
            search_dirs.append(legacy_tasks)

    for tasks_dir in search_dirs:
        try:
            task_dirs = sorted(
                [d for d in tasks_dir.iterdir() if d.is_dir()],
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            continue

        for td in task_dirs[:limit]:
            api_hist = td / "api_conversation_history.json"
            if not api_hist.exists():
                continue
            try:
                stat = api_hist.stat()
                meta = _read_cline_task_meta(td)
                sessions.append(
                    {
                        "ide": "cline",
                        "session_id": td.name,
                        "project_path": meta.get("workspace", ""),
                        "file_path": str(td),
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


def _read_cline_task_meta(task_dir: Path) -> Dict:
    """Read metadata from a Cline task directory."""
    meta: Dict = {
        "title": "",
        "model": "",
        "workspace": "",
        "message_count": 0,
        "token_usage": {},
    }

    metadata_file = task_dir / "task_metadata.json"
    if metadata_file.exists():
        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                md = json.load(f)
            meta["title"] = md.get("task", "")[:80]
            meta["model"] = md.get("model", "")
            meta["workspace"] = md.get("workspace", "")
            total_in = md.get("tokensIn", 0) or 0
            total_out = md.get("tokensOut", 0) or 0
            meta["token_usage"] = {
                "input_tokens": total_in,
                "output_tokens": total_out,
            }
        except (json.JSONDecodeError, OSError):
            pass

    api_hist = task_dir / "api_conversation_history.json"
    if api_hist.exists():
        try:
            with open(api_hist, "r", encoding="utf-8") as f:
                messages = json.load(f)
            if isinstance(messages, list):
                meta["message_count"] = len(messages)
                if not meta["title"] and messages:
                    first = messages[0]
                    if isinstance(first, dict) and first.get("role") == "user":
                        content = first.get("content", "")
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("text"):
                                    meta["title"] = c["text"][:80]
                                    break
                        elif isinstance(content, str):
                            meta["title"] = content[:80]
        except (json.JSONDecodeError, OSError):
            pass

    return meta


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
