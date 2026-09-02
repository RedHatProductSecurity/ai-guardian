"""Per-IDE session adapter implementations."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from ai_guardian.sessions.base import (
    SessionAdapter,
    extract_tool_result_content,
    truncate,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


class ClaudeSessionAdapter(SessionAdapter):
    name = "claude"
    session_dirs = {
        "env": "CLAUDE_CONFIG_DIR",
        "default_mac": "~/.claude/projects",
        "default_linux": "~/.claude/projects",
        "default_win": "~/.claude/projects",
        "pattern": "*.jsonl",
    }

    def discover(self, project_path=None, limit=100):
        base = self.resolve_session_dir()
        if not base or not base.is_dir():
            return []

        sessions = []
        project_dirs = []

        if project_path:
            encoded = project_path.replace("/", "-")
            if not encoded.startswith("-"):
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
            decoded_path = self.decode_project_name(proj_name)

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
                    meta = self.read_session_meta(jf)
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

    def read_detail(self, session):
        file_path = session.get("file_path", "")
        if not file_path:
            return []

        steps = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    msg_type = d.get("type", "")

                    if msg_type == "custom-title":
                        steps.append(
                            {"type": "title", "content": d.get("customTitle", "")}
                        )
                    elif msg_type == "agent-name":
                        steps.append(
                            {"type": "title", "content": d.get("agentName", "")}
                        )
                    elif msg_type == "ai-title":
                        steps.append({"type": "title", "content": d.get("aiTitle", "")})

                    elif msg_type == "user":
                        content = d.get("message", {}).get("content", "")
                        ts = d.get("timestamp", "")

                        if isinstance(content, list):
                            text_parts = []
                            for c in content:
                                if not isinstance(c, dict):
                                    continue
                                ctype = c.get("type", "")
                                if ctype == "tool_result":
                                    rc_text, tool_id = extract_tool_result_content(c)
                                    steps.append(
                                        {
                                            "type": "tool_result",
                                            "tool_name": "",
                                            "content": rc_text,
                                            "tool_id": tool_id,
                                        }
                                    )
                                else:
                                    text = c.get("text", "")
                                    if text:
                                        text_parts.append(text)
                            if text_parts:
                                steps.append(
                                    {
                                        "type": "user",
                                        "content": " ".join(text_parts),
                                        "timestamp": ts,
                                    }
                                )
                        elif content:
                            steps.append(
                                {
                                    "type": "user",
                                    "content": str(content),
                                    "timestamp": ts,
                                }
                            )

                    elif msg_type == "assistant":
                        msg = d.get("message", {})
                        content_parts = msg.get("content", [])
                        if not isinstance(content_parts, list):
                            content_parts = [
                                {"type": "text", "text": str(content_parts)}
                            ]

                        for part in content_parts:
                            if not isinstance(part, dict):
                                continue
                            part_type = part.get("type", "")

                            if part_type == "text":
                                text = part.get("text", "")
                                if text:
                                    steps.append(
                                        {
                                            "type": "assistant",
                                            "content": text,
                                            "model": msg.get("model", ""),
                                            "usage": msg.get("usage", {}),
                                        }
                                    )
                            elif part_type == "tool_use":
                                steps.append(
                                    {
                                        "type": "tool_use",
                                        "tool_name": part.get("name", ""),
                                        "tool_input": part.get("input", {}),
                                        "tool_id": part.get("id", ""),
                                    }
                                )
                            elif part_type == "tool_result":
                                content = part.get("content", "")
                                if isinstance(content, list):
                                    content = "\n".join(
                                        c.get("text", "")
                                        for c in content
                                        if isinstance(c, dict) and c.get("text")
                                    )
                                steps.append(
                                    {
                                        "type": "tool_result",
                                        "tool_name": part.get("name", ""),
                                        "content": str(content),
                                        "tool_id": part.get("tool_use_id", ""),
                                    }
                                )
                            elif part_type == "thinking":
                                steps.append(
                                    {
                                        "type": "thinking",
                                        "content": part.get("thinking", ""),
                                    }
                                )

                    elif msg_type == "system":
                        subtype = d.get("subtype", "")
                        steps.append(
                            {
                                "type": "system",
                                "content": subtype,
                                "timestamp": d.get("timestamp", ""),
                            }
                        )

        except OSError:
            pass

        return steps

    def read_summary(self, session):
        file_path = session.get("file_path", "")
        if not file_path:
            return session

        meta = self.read_session_meta(Path(file_path))
        result = dict(session)
        result["first_timestamp"] = meta["first_timestamp"]
        result["last_timestamp"] = meta["last_timestamp"]
        result["user_messages"] = meta["user_messages"]
        result["assistant_messages"] = meta["assistant_messages"]
        if not result.get("title"):
            result["title"] = meta["title"]
        if not result.get("model"):
            result["model"] = meta["model"]
        if not result.get("token_usage"):
            result["token_usage"] = meta["token_usage"]
        return result

    def read_messages(self, session, limit=200):
        file_path = session.get("file_path", "")
        if not file_path:
            return []

        messages = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    msg_type = d.get("type", "")

                    if msg_type == "user":
                        content = d.get("message", {}).get("content", "")
                        if isinstance(content, list):
                            text_parts = []
                            for c in content:
                                if not isinstance(c, dict):
                                    continue
                                ctype = c.get("type", "")
                                if ctype == "tool_result":
                                    rc_text, tool_id = extract_tool_result_content(c)
                                    messages.append(
                                        {
                                            "role": "tool_result",
                                            "content": truncate(rc_text, 500),
                                            "timestamp": d.get("timestamp", ""),
                                            "tool_id": tool_id,
                                        }
                                    )
                                else:
                                    text = c.get("text", "")
                                    if text:
                                        text_parts.append(text)
                            content = " ".join(text_parts)
                        if content:
                            messages.append(
                                {
                                    "role": "user",
                                    "content": truncate(str(content), 500),
                                    "timestamp": d.get("timestamp", ""),
                                }
                            )

                    elif msg_type == "assistant":
                        msg = d.get("message", {})
                        content_parts = msg.get("content", [])
                        text = ""
                        if isinstance(content_parts, list):
                            for part in content_parts:
                                if (
                                    isinstance(part, dict)
                                    and part.get("type") == "text"
                                ):
                                    text += part.get("text", "")
                        elif isinstance(content_parts, str):
                            text = content_parts

                        if text:
                            messages.append(
                                {
                                    "role": "assistant",
                                    "content": truncate(text, 500),
                                    "timestamp": "",
                                    "model": msg.get("model", ""),
                                    "usage": msg.get("usage", {}),
                                }
                            )

                    if len(messages) >= limit:
                        break
        except OSError:
            pass

        return messages

    @staticmethod
    def decode_project_name(encoded: str) -> str:
        """Decode Claude's project directory name back to a path."""
        if encoded.startswith("-"):
            return encoded.replace("-", "/")
        return encoded

    @staticmethod
    def read_session_meta(path: Path) -> Dict:
        """Read metadata from a Claude session JSONL file."""
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
        title_priority = 0

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

                    if msg_type == "custom-title":
                        meta["title"] = d.get("customTitle", "")
                        title_priority = 3
                    elif msg_type == "agent-name" and title_priority < 3:
                        meta["title"] = d.get("agentName", "")
                        title_priority = 2
                    elif msg_type == "ai-title" and title_priority < 2:
                        meta["title"] = d.get("aiTitle", "")
                    elif msg_type == "assistant":
                        msg = d.get("message", {})
                        if not meta["model"] and msg.get("model"):
                            meta["model"] = msg["model"]
                        usage = msg.get("usage", {})
                        total_input += usage.get("input_tokens", 0)
                        total_output += usage.get("output_tokens", 0)
                        total_cache_read += usage.get("cache_read_input_tokens", 0)
                        total_cache_create += usage.get(
                            "cache_creation_input_tokens", 0
                        )
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


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------


class CursorSessionAdapter(SessionAdapter):
    name = "cursor"
    session_dirs = {
        "env": "CURSOR_DATA_DIR",
        "default_mac": "~/Library/Application Support/Cursor/User/globalStorage",
        "default_linux": "~/.config/Cursor/User/globalStorage",
        "default_win": "%APPDATA%/Cursor/User/globalStorage",
        "file": "state.vscdb",
    }

    def discover(self, project_path=None, limit=100):
        session_dir = self.resolve_session_dir()
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
                        "SELECT COUNT(*) FROM cursorDiskKV WHERE key LIKE ?",
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

    def read_detail(self, session):
        file_path = session.get("file_path", "")
        session_id = session.get("session_id", "")
        if not file_path or not session_id:
            return []

        steps = []
        try:
            import sqlite3

            conn = sqlite3.connect(f"file:{file_path}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute(
                "SELECT value FROM cursorDiskKV WHERE key LIKE ?",
                (f"bubbleId:{session_id}:%",),
            )
            bubbles = []
            for (val,) in cur.fetchall():
                try:
                    d = (
                        json.loads(val)
                        if isinstance(val, str)
                        else json.loads(val.decode("utf-8"))
                    )
                    bubbles.append(d)
                except (json.JSONDecodeError, ValueError):
                    continue
            conn.close()

            bubbles.sort(key=lambda b: b.get("createdAt", ""))

            for d in bubbles:
                btype = d.get("type", 0)
                text = d.get("text", "") or ""
                ts = d.get("createdAt", "")

                if btype == 1:
                    if text:
                        steps.append({"type": "user", "content": text, "timestamp": ts})
                elif btype == 2:
                    thinking = d.get("thinking", {})
                    if isinstance(thinking, dict) and thinking.get("content"):
                        steps.append(
                            {"type": "thinking", "content": thinking["content"]}
                        )
                    if text:
                        steps.append(
                            {"type": "assistant", "content": text, "timestamp": ts}
                        )

        except Exception as exc:
            logger.debug("Failed to read Cursor session detail: %s", exc)

        return steps


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------


class CopilotSessionAdapter(SessionAdapter):
    name = "copilot"
    session_dirs = {
        "env": "COPILOT_CHAT_DATA_DIR",
        "default_mac": "~/Library/Application Support/Code/User",
        "default_linux": "~/.config/Code/User",
        "default_win": "%APPDATA%/Code/User",
        "subdir_glob": "workspaceStorage/*/chatSessions",
        "pattern": "*.jsonl",
    }

    def discover(self, project_path=None, limit=100):
        base = self.resolve_session_dir()
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
                    meta = self._read_session_meta(fp)
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

    def read_detail(self, session):
        file_path = session.get("file_path", "")
        if not file_path:
            return []

        steps = []
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
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
                        for req in v.get("requests", []):
                            self._extract_request(req, steps)
                    elif kind == 1:
                        key_path = d.get("k", [])
                        val = d.get("v")
                        if (
                            len(key_path) >= 3
                            and key_path[0] == "requests"
                            and key_path[2] == "result"
                            and isinstance(val, dict)
                        ):
                            self._extract_result(val, steps)
                    elif kind == 2:
                        key_path = d.get("k", [])
                        val = d.get("v")
                        if (
                            len(key_path) == 3
                            and key_path[0] == "requests"
                            and key_path[2] == "response"
                        ):
                            self._extract_response_parts(val, steps)
                        elif key_path == ["requests"] and isinstance(val, dict):
                            self._extract_request(val, steps)

        except OSError:
            pass

        return steps

    @staticmethod
    def _read_session_meta(path: Path) -> Dict:
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

    @staticmethod
    def _extract_request(req, steps):
        msg = req.get("message", {})
        text = msg.get("text", "") if isinstance(msg, dict) else ""
        if text:
            steps.append({"type": "user", "content": text})
        result = req.get("result")
        if isinstance(result, dict):
            CopilotSessionAdapter._extract_result(result, steps)
        for resp_part in req.get("response", []):
            if isinstance(resp_part, dict):
                CopilotSessionAdapter._extract_response_part(resp_part, steps)

    @staticmethod
    def _extract_result(result, steps):
        metadata = result.get("metadata", {})
        if not isinstance(metadata, dict):
            return
        for cb in metadata.get("codeBlocks", []):
            code = cb.get("code", "")
            if code:
                steps.append({"type": "assistant", "content": code})

    @staticmethod
    def _extract_response_parts(val, steps):
        if isinstance(val, list):
            for part in val:
                if isinstance(part, dict):
                    CopilotSessionAdapter._extract_response_part(part, steps)
        elif isinstance(val, dict):
            CopilotSessionAdapter._extract_response_part(val, steps)

    @staticmethod
    def _extract_response_part(part, steps):
        part_kind = part.get("kind", "")
        value = part.get("value", "")

        if part_kind == "thinking":
            if isinstance(value, str) and value.strip():
                steps.append({"type": "thinking", "content": value})
        elif part_kind == "markdownContent" or (
            not part_kind and isinstance(value, str)
        ):
            if value.strip():
                steps.append({"type": "assistant", "content": value})
        elif part_kind == "inlineReference":
            pass
        elif part_kind == "mcpServersStarting":
            pass
        elif isinstance(value, str) and value.strip():
            steps.append({"type": "assistant", "content": value})


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------


class CodexSessionAdapter(SessionAdapter):
    name = "codex"
    session_dirs = {
        "env": "CODEX_HOME",
        "default_mac": "~/.codex/sessions",
        "default_linux": "~/.codex/sessions",
        "default_win": "~/.codex/sessions",
    }

    def discover(self, project_path=None, limit=100):
        base = self.resolve_session_dir()
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
                meta = self._read_session_meta(jf)
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

    def read_detail(self, session):
        file_path = session.get("file_path", "")
        if not file_path or file_path.endswith(".zst"):
            return []

        steps = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    rtype = d.get("type", "")
                    payload = d.get("payload", {})

                    if rtype == "session_meta":
                        cwd = payload.get("cwd", "")
                        if cwd:
                            steps.append({"type": "system", "content": f"cwd: {cwd}"})
                    elif rtype == "response_item":
                        role = payload.get("role", "")
                        content = payload.get("content", [])
                        if isinstance(content, str):
                            content = [{"type": "text", "text": content}]

                        for part in content if isinstance(content, list) else []:
                            if not isinstance(part, dict):
                                continue
                            ptype = part.get("type", "")

                            if ptype in ("input_text", "text"):
                                text = part.get("text", "")
                                if text:
                                    steps.append(
                                        {
                                            "type": (
                                                "user"
                                                if role == "user"
                                                else "assistant"
                                            ),
                                            "content": text,
                                        }
                                    )
                            elif ptype == "function_call":
                                steps.append(
                                    {
                                        "type": "tool_use",
                                        "tool_name": part.get("name", ""),
                                        "tool_input": part.get("arguments", {}),
                                    }
                                )
                            elif ptype == "function_call_output":
                                output = part.get("output", "")
                                steps.append(
                                    {
                                        "type": "tool_result",
                                        "content": str(output),
                                    }
                                )
                            elif ptype == "reasoning":
                                text = part.get("text", "")
                                if text:
                                    steps.append({"type": "thinking", "content": text})
        except OSError:
            pass

        return steps

    @staticmethod
    def _is_injected_instructions(text: str) -> bool:
        """Return whether text is heading-style injected session instructions."""
        normalized = text.lstrip().lower()
        return normalized.startswith("#") and (
            "agents.md" in normalized or "instructions" in normalized
        )

    @staticmethod
    def _read_session_meta(path: Path) -> Dict:
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
                                            text = c["text"]
                                            if not CodexSessionAdapter._is_injected_instructions(
                                                text
                                            ):
                                                meta["title"] = text[:80]
                                                break
                                elif isinstance(content, str):
                                    if not CodexSessionAdapter._is_injected_instructions(
                                        content
                                    ):
                                        meta["title"] = content[:80]
        except OSError:
            pass

        meta["message_count"] = msg_count
        return meta


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


class GeminiSessionAdapter(SessionAdapter):
    name = "gemini"
    session_dirs = {
        "env": "GEMINI_CLI_HOME",
        "default_mac": "~/.gemini/tmp",
        "default_linux": "~/.gemini/tmp",
        "default_win": "~/.gemini/tmp",
    }

    def discover(self, project_path=None, limit=100):
        base = self.resolve_session_dir()
        if not base or not base.is_dir():
            return []

        sessions = []
        try:
            session_files = sorted(
                list(base.rglob("session-*.json"))
                + list(base.rglob("session-*.jsonl")),
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

    def read_detail(self, session):
        file_path = session.get("file_path", "")
        if not file_path:
            return []

        steps = []
        try:
            if file_path.endswith(".jsonl"):
                with open(file_path, "r", encoding="utf-8") as f:
                    records = [json.loads(line) for line in f if line.strip()]
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    records = data
                elif isinstance(data, dict):
                    records = data.get("messages", data.get("turns", [data]))
                else:
                    records = []

            for record in records:
                if not isinstance(record, dict):
                    continue
                role = record.get("role", "")
                parts = record.get("parts", record.get("content", []))
                if isinstance(parts, str):
                    parts = [{"text": parts}]
                if not isinstance(parts, list):
                    continue

                for part in parts:
                    if not isinstance(part, dict):
                        continue

                    text = part.get("text", "")
                    if text:
                        if role == "user":
                            steps.append({"type": "user", "content": text})
                        elif role in ("model", "assistant"):
                            steps.append({"type": "assistant", "content": text})
                        elif role == "system":
                            steps.append({"type": "system", "content": text})

                    fn_call = part.get("functionCall", {})
                    if fn_call:
                        steps.append(
                            {
                                "type": "tool_use",
                                "tool_name": fn_call.get("name", ""),
                                "tool_input": fn_call.get("args", {}),
                            }
                        )

                    fn_resp = part.get("functionResponse", {})
                    if fn_resp:
                        steps.append(
                            {
                                "type": "tool_result",
                                "tool_name": fn_resp.get("name", ""),
                                "content": json.dumps(
                                    fn_resp.get("response", {}), default=str
                                ),
                            }
                        )

                    thought = part.get("thought", "")
                    if thought:
                        steps.append({"type": "thinking", "content": thought})

        except (OSError, json.JSONDecodeError):
            pass

        return steps


# ---------------------------------------------------------------------------
# Cline
# ---------------------------------------------------------------------------


class ClineSessionAdapter(SessionAdapter):
    name = "cline"
    session_dirs = {
        "env": "CLINE_STORAGE_DIR",
        "default_mac": "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev",
        "default_linux": "~/.config/Code/User/globalStorage/saoudrizwan.claude-dev",
        "default_win": "%APPDATA%/Code/User/globalStorage/saoudrizwan.claude-dev",
    }

    def discover(self, project_path=None, limit=100):
        sessions = []

        search_dirs = []
        cline_home = Path("~/.cline/data/tasks").expanduser()
        if cline_home.is_dir():
            search_dirs.append(cline_home)

        legacy = self.resolve_session_dir()
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
                    meta = self._read_task_meta(td)
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

    def read_detail(self, session):
        task_dir = session.get("file_path", "")
        if not task_dir:
            return []

        api_hist = Path(task_dir) / "api_conversation_history.json"
        if not api_hist.exists():
            return []

        steps = []
        try:
            with open(api_hist, "r", encoding="utf-8") as f:
                messages = json.load(f)

            if not isinstance(messages, list):
                return []

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role", "")
                content = msg.get("content", "")

                if isinstance(content, str):
                    if content:
                        step_type = "user" if role == "user" else "assistant"
                        steps.append({"type": step_type, "content": content})
                    continue

                if not isinstance(content, list):
                    continue

                for part in content:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type", "")

                    if ptype == "text":
                        text = part.get("text", "")
                        if text:
                            step_type = "user" if role == "user" else "assistant"
                            steps.append({"type": step_type, "content": text})
                    elif ptype == "tool_use":
                        steps.append(
                            {
                                "type": "tool_use",
                                "tool_name": part.get("name", ""),
                                "tool_input": part.get("input", {}),
                            }
                        )
                    elif ptype == "tool_result":
                        result_content = part.get("content", "")
                        if isinstance(result_content, list):
                            result_content = "\n".join(
                                c.get("text", "")
                                for c in result_content
                                if isinstance(c, dict) and c.get("text")
                            )
                        steps.append(
                            {
                                "type": "tool_result",
                                "tool_name": part.get("name", ""),
                                "content": str(result_content),
                            }
                        )
                    elif ptype == "thinking":
                        steps.append(
                            {"type": "thinking", "content": part.get("thinking", "")}
                        )
        except (OSError, json.JSONDecodeError):
            pass

        return steps

    @staticmethod
    def _read_task_meta(task_dir: Path) -> Dict:
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


# ---------------------------------------------------------------------------
# Windsurf
# ---------------------------------------------------------------------------


class WindsurfSessionAdapter(SessionAdapter):
    name = "windsurf"
    session_dirs = {
        "env": "WINDSURF_TRANSCRIPTS_DIR",
        "default_mac": "~/.windsurf/transcripts",
        "default_linux": "~/.windsurf/transcripts",
        "default_win": "~/.windsurf/transcripts",
        "pattern": "*.jsonl",
    }

    def discover(self, project_path=None, limit=100):
        return self._discover_generic_jsonl(project_path, limit)

    def read_detail(self, session):
        file_path = session.get("file_path", "")
        if not file_path:
            return []

        steps = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    msg_type = d.get("type", "")

                    if msg_type == "user_input":
                        text = d.get("user_response", "")
                        if text:
                            steps.append({"type": "user", "content": text})
                    elif msg_type == "planner_response":
                        text = d.get("response", "")
                        if text:
                            steps.append({"type": "assistant", "content": text})
                    elif msg_type == "code_action":
                        content = d.get("new_content", "")
                        if content:
                            steps.append(
                                {
                                    "type": "tool_use",
                                    "tool_name": "code_action",
                                    "content": content,
                                }
                            )
                    else:
                        sub = d.get(msg_type, {})
                        if isinstance(sub, dict):
                            for v in sub.values():
                                if isinstance(v, str) and v.strip():
                                    steps.append({"type": "assistant", "content": v})
                                    break
        except OSError:
            pass

        return steps


# ---------------------------------------------------------------------------
# Kiro
# ---------------------------------------------------------------------------


class KiroSessionAdapter(SessionAdapter):
    name = "kiro"
    session_dirs = {
        "env": "KIRO_SESSIONS_DIR",
        "default_mac": "~/.kiro/sessions/cli",
        "default_linux": "~/.kiro/sessions/cli",
        "default_win": "~/.kiro/sessions/cli",
        "pattern": "*.jsonl",
    }

    def discover(self, project_path=None, limit=100):
        return self._discover_generic_jsonl(project_path, limit)

    def read_detail(self, session):
        file_path = session.get("file_path", "")
        if not file_path:
            return []

        steps = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    msg_type = d.get("type", "")

                    if msg_type == "user_message":
                        text = d.get("content", "")
                        if text:
                            steps.append({"type": "user", "content": text})
                    elif msg_type == "agent_message_chunk":
                        text = d.get("content", "")
                        if text:
                            steps.append({"type": "assistant", "content": text})
                    elif msg_type == "tool_call":
                        args = d.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except (json.JSONDecodeError, ValueError):
                                pass
                        steps.append(
                            {
                                "type": "tool_use",
                                "tool_name": d.get("name", ""),
                                "tool_input": args,
                            }
                        )
                    elif msg_type == "tool_result":
                        content = d.get("content", d.get("output", ""))
                        steps.append(
                            {
                                "type": "tool_result",
                                "tool_name": d.get("name", ""),
                                "content": str(content),
                            }
                        )
        except OSError:
            pass

        return steps


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SESSION_ADAPTERS: Dict[str, SessionAdapter] = {}
for _adapter in [
    ClaudeSessionAdapter(),
    CursorSessionAdapter(),
    CopilotSessionAdapter(),
    CodexSessionAdapter(),
    WindsurfSessionAdapter(),
    GeminiSessionAdapter(),
    ClineSessionAdapter(),
    KiroSessionAdapter(),
]:
    SESSION_ADAPTERS[_adapter.name] = _adapter
