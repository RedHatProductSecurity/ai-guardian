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
    result = dict(session)
    steps = read_session_detail(session)
    if not steps:
        return result
    user_count = sum(1 for s in steps if s.get("type") == "user")
    asst_count = sum(1 for s in steps if s.get("type") == "assistant")
    result["user_messages"] = user_count
    result["assistant_messages"] = asst_count
    timestamps = [s.get("timestamp", "") for s in steps if s.get("timestamp")]
    result["first_timestamp"] = timestamps[0] if timestamps else ""
    result["last_timestamp"] = timestamps[-1] if timestamps else ""
    return result


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

    from ai_guardian.sessions.discovery import _read_claude_session_meta

    meta = _read_claude_session_meta(Path(file_path))
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
                        text_parts = []
                        for c in content:
                            if not isinstance(c, dict):
                                continue
                            ctype = c.get("type", "")
                            if ctype == "tool_result":
                                rc_text, tool_id = _extract_tool_result_content(c)
                                messages.append(
                                    {
                                        "role": "tool_result",
                                        "content": _truncate(rc_text, 500),
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
    if ide == "codex":
        return _read_codex_detail(session)
    if ide == "gemini":
        return _read_gemini_detail(session)
    if ide == "cline":
        return _read_cline_detail(session)
    if ide == "windsurf":
        return _read_windsurf_detail(session)
    if ide == "kiro":
        return _read_kiro_detail(session)
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
                    ts = d.get("timestamp", "")

                    if isinstance(content, list):
                        text_parts = []
                        for c in content:
                            if not isinstance(c, dict):
                                continue
                            ctype = c.get("type", "")
                            if ctype == "tool_result":
                                rc_text, tool_id = _extract_tool_result_content(c)
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
    """Read conversation from Copilot Chat delta journal JSONL.

    Copilot uses a delta journal format:
    - kind=0: base snapshot with initial requests
    - kind=1: set mutation at path (e.g. ['requests', 0, 'result'])
    - kind=2: array append at path (e.g. ['requests', 0, 'response'])
    """
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
                        _extract_copilot_request(req, steps)

                elif kind == 1:
                    key_path = d.get("k", [])
                    val = d.get("v")
                    if (
                        len(key_path) >= 3
                        and key_path[0] == "requests"
                        and key_path[2] == "result"
                        and isinstance(val, dict)
                    ):
                        _extract_copilot_result(val, steps)

                elif kind == 2:
                    key_path = d.get("k", [])
                    val = d.get("v")
                    if (
                        len(key_path) == 3
                        and key_path[0] == "requests"
                        and key_path[2] == "response"
                    ):
                        _extract_copilot_response_parts(val, steps)
                    elif key_path == ["requests"] and isinstance(val, dict):
                        _extract_copilot_request(val, steps)

    except OSError:
        pass

    return steps


def _extract_copilot_request(req, steps):
    """Extract user message from a Copilot request object."""
    msg = req.get("message", {})
    text = msg.get("text", "") if isinstance(msg, dict) else ""
    if text:
        steps.append({"type": "user", "content": text})
    result = req.get("result")
    if isinstance(result, dict):
        _extract_copilot_result(result, steps)
    for resp_part in req.get("response", []):
        if isinstance(resp_part, dict):
            _extract_copilot_response_part(resp_part, steps)


def _extract_copilot_result(result, steps):
    """Extract assistant content from a Copilot result delta."""
    metadata = result.get("metadata", {})
    if not isinstance(metadata, dict):
        return
    for cb in metadata.get("codeBlocks", []):
        code = cb.get("code", "")
        if code:
            steps.append({"type": "assistant", "content": code})


def _extract_copilot_response_parts(val, steps):
    """Extract response parts from a kind=2 append."""
    if isinstance(val, list):
        for part in val:
            if isinstance(part, dict):
                _extract_copilot_response_part(part, steps)
    elif isinstance(val, dict):
        _extract_copilot_response_part(val, steps)


def _extract_copilot_response_part(part, steps):
    """Extract a single Copilot response part."""
    part_kind = part.get("kind", "")
    value = part.get("value", "")

    if part_kind == "thinking":
        if isinstance(value, str) and value.strip():
            steps.append({"type": "thinking", "content": value})
    elif part_kind == "markdownContent" or (not part_kind and isinstance(value, str)):
        if value.strip():
            steps.append({"type": "assistant", "content": value})
    elif part_kind == "inlineReference":
        pass
    elif part_kind == "mcpServersStarting":
        pass
    elif isinstance(value, str) and value.strip():
        steps.append({"type": "assistant", "content": value})


def _read_codex_detail(session: Dict) -> List[Dict]:
    """Read conversation from Codex CLI JSONL session."""
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
                                            "user" if role == "user" else "assistant"
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


def _read_gemini_detail(session: Dict) -> List[Dict]:
    """Read conversation from Gemini CLI session JSON/JSONL."""
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


def _read_cline_detail(session: Dict) -> List[Dict]:
    """Read conversation from Cline task directory."""
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


def _read_windsurf_detail(session: Dict) -> List[Dict]:
    """Read conversation from Windsurf Cascade JSONL transcript."""
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


def _read_kiro_detail(session: Dict) -> List[Dict]:
    """Read conversation from Kiro CLI JSONL session."""
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


def _extract_tool_result_content(block: dict) -> tuple:
    """Extract (text, tool_use_id) from a tool_result content block."""
    rc = block.get("content", "")
    if isinstance(rc, list):
        rc = "\n".join(
            p.get("text", "") for p in rc if isinstance(p, dict) and p.get("text")
        )
    return str(rc), block.get("tool_use_id", "")


def _truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
