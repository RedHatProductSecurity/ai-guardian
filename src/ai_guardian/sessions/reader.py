"""IDE session reader — read and parse session content."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def read_session_summary(session: Dict) -> Dict:
    """Read a session and return enriched summary with messages.

    Takes a session dict from discover_sessions() and returns it
    with additional detail: first/last timestamps, message previews.
    """
    ide = session.get("ide", "")
    if ide == "claude":
        return _read_claude_session(session)
    if ide in ("cursor", "copilot"):
        result = dict(session)
        steps = read_session_detail(session)
        user_count = sum(1 for s in steps if s.get("type") == "user")
        asst_count = sum(1 for s in steps if s.get("type") == "assistant")
        result["user_messages"] = user_count
        result["assistant_messages"] = asst_count
        result["first_timestamp"] = ""
        result["last_timestamp"] = ""
        return result
    return session


def read_session_messages(
    session: Dict,
    limit: int = 200,
) -> List[Dict]:
    """Read messages from a session file.

    Returns list of message dicts with role, content preview, timestamp.
    """
    ide = session.get("ide", "")
    if ide == "claude":
        return _read_claude_messages(session, limit)
    return []


def _read_claude_session(session: Dict) -> Dict:
    """Enrich a Claude session dict with parsed metadata."""
    file_path = session.get("file_path", "")
    if not file_path:
        return session

    result = dict(session)
    first_ts = ""
    last_ts = ""
    user_count = 0
    assistant_count = 0

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
                ts = d.get("timestamp", "")

                if ts:
                    if not first_ts:
                        first_ts = ts
                    last_ts = ts

                if msg_type == "user":
                    user_count += 1
                elif msg_type == "assistant":
                    assistant_count += 1
    except OSError:
        pass

    result["first_timestamp"] = first_ts
    result["last_timestamp"] = last_ts
    result["user_messages"] = user_count
    result["assistant_messages"] = assistant_count
    return result


def _read_claude_messages(session: Dict, limit: int = 200) -> List[Dict]:
    """Read messages from a Claude session JSONL file."""
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
                        content = " ".join(
                            c.get("text", "") for c in content if isinstance(c, dict)
                        )
                    messages.append(
                        {
                            "role": "user",
                            "content": _truncate(str(content), 500),
                            "timestamp": d.get("timestamp", ""),
                        }
                    )

                elif msg_type == "assistant":
                    msg = d.get("message", {})
                    content_parts = msg.get("content", [])
                    text = ""
                    if isinstance(content_parts, list):
                        for part in content_parts:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text += part.get("text", "")
                    elif isinstance(content_parts, str):
                        text = content_parts

                    if text:
                        messages.append(
                            {
                                "role": "assistant",
                                "content": _truncate(text, 500),
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


def read_session_detail(session: Dict) -> List[Dict]:
    """Read full structured conversation from a session file.

    Returns list of step dicts, each with:
    - type: user | assistant | tool_use | tool_result | system | title
    - content: text content
    - timestamp: ISO timestamp (if available)
    - model: model name (assistant only)
    - usage: token usage dict (assistant only)
    - tool_name: tool name (tool_use/tool_result only)
    - tool_input: tool input dict (tool_use only)
    """
    ide = session.get("ide", "")
    if ide == "claude":
        return _read_claude_detail(session)
    if ide == "cursor":
        return _read_cursor_detail(session)
    if ide == "copilot":
        return _read_copilot_detail(session)
    return []


def _read_claude_detail(session: Dict) -> List[Dict]:
    """Read full conversation detail from Claude session JSONL."""
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

                if msg_type == "ai-title":
                    steps.append(
                        {
                            "type": "title",
                            "content": d.get("aiTitle", ""),
                        }
                    )

                elif msg_type == "user":
                    content = d.get("message", {}).get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            c.get("text", "") for c in content if isinstance(c, dict)
                        )
                    steps.append(
                        {
                            "type": "user",
                            "content": str(content),
                            "timestamp": d.get("timestamp", ""),
                        }
                    )

                elif msg_type == "assistant":
                    msg = d.get("message", {})
                    content_parts = msg.get("content", [])
                    if not isinstance(content_parts, list):
                        content_parts = [{"type": "text", "text": str(content_parts)}]

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


def _read_cursor_detail(session: Dict) -> List[Dict]:
    """Read conversation from Cursor state.vscdb bubbles."""
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
                    steps.append({"type": "thinking", "content": thinking["content"]})
                if text:
                    steps.append(
                        {"type": "assistant", "content": text, "timestamp": ts}
                    )

    except Exception as exc:
        logger.debug("Failed to read Cursor session detail: %s", exc)

    return steps


def _read_copilot_detail(session: Dict) -> List[Dict]:
    """Read conversation from Copilot Chat delta journal JSONL."""
    file_path = session.get("file_path", "")
    if not file_path:
        return []

    steps = []
    requests_state = []

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
                        msg = req.get("message", {})
                        text = msg.get("text", "")
                        if text:
                            steps.append({"type": "user", "content": text})
                        result = req.get("result", {})
                        if isinstance(result, dict):
                            metadata = result.get("metadata", {})
                            if isinstance(metadata, dict):
                                for cb in metadata.get("codeBlocks", []):
                                    code = cb.get("code", "")
                                    if code:
                                        steps.append(
                                            {
                                                "type": "assistant",
                                                "content": code,
                                            }
                                        )
                        requests_state.append(req)

                elif kind == 1:
                    key_path = d.get("k", [])
                    val = d.get("v")
                    if (
                        len(key_path) >= 3
                        and key_path[0] == "requests"
                        and key_path[2] == "result"
                        and isinstance(val, dict)
                    ):
                        metadata = val.get("metadata", {})
                        if isinstance(metadata, dict):
                            for cb in metadata.get("codeBlocks", []):
                                code = cb.get("code", "")
                                if code:
                                    steps.append(
                                        {
                                            "type": "assistant",
                                            "content": code,
                                        }
                                    )
                            message = val.get("message", "")
                            if message:
                                steps.append(
                                    {
                                        "type": "assistant",
                                        "content": message,
                                    }
                                )

                elif kind == 2:
                    key_path = d.get("k", [])
                    val = d.get("v")
                    if key_path == ["requests"] and isinstance(val, dict):
                        msg = val.get("message", {})
                        text = msg.get("text", "") if isinstance(msg, dict) else ""
                        if text:
                            steps.append({"type": "user", "content": text})

    except OSError:
        pass

    return steps


def _truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
