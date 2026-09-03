"""IDE session reader — read and parse session content."""

import logging
from typing import Dict, List

from ai_guardian.sessions.adapters import SESSION_ADAPTERS

logger = logging.getLogger(__name__)


def read_session_summary(session: Dict) -> Dict:
    """Read a session and return enriched summary with messages.

    Takes a session dict from discover_sessions() and returns it
    with additional detail: first/last timestamps, message previews.
    """
    ide = session.get("ide", "")
    adapter = SESSION_ADAPTERS.get(ide)
    if not adapter:
        return dict(session)
    return adapter.read_summary(session)


def read_session_messages(
    session: Dict,
    limit: int = 200,
) -> List[Dict]:
    """Read messages from a session file.

    Returns list of message dicts with role, content preview, timestamp.
    """
    ide = session.get("ide", "")
    adapter = SESSION_ADAPTERS.get(ide)
    if not adapter:
        return []
    return adapter.read_messages(session, limit)


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
    adapter = SESSION_ADAPTERS.get(ide)
    if not adapter:
        return []
    return adapter.read_detail(session)


def read_session_detail_page(
    session: Dict,
    offset: int = 0,
    limit: int = 50,
) -> Dict:
    """Read one bounded page of a session's structured conversation.

    ``offset=-1`` requests the final page, which lets callers display the
    newest steps without first materializing the complete transcript.  The
    returned ``total`` is based on the normalized steps produced by the
    adapter, so it remains consistent across JSON, JSONL, and database-backed
    session formats.
    """
    ide = session.get("ide", "")
    adapter = SESSION_ADAPTERS.get(ide)
    if not adapter:
        return {
            "steps": [],
            "offset": max(0, offset),
            "limit": limit,
            "total": 0,
            "has_more": False,
        }

    safe_limit = max(1, int(limit))
    safe_offset = int(offset)
    steps = adapter.read_detail_page(session, safe_offset, safe_limit)
    total = getattr(steps, "total_count", len(steps))
    page_offset = getattr(steps, "page_offset", max(0, safe_offset))
    summary = dict(session)
    parsed_summary = getattr(steps, "summary", {})
    for key, value in parsed_summary.items():
        if key == "token_usage":
            current = summary.get(key) or {}
            if not current or current == {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            }:
                summary[key] = value
        elif summary.get(key) in (None, "", 0, {}):
            summary[key] = value
    return {
        "steps": list(steps),
        "offset": page_offset,
        "limit": safe_limit,
        "total": total,
        "has_more": page_offset + len(steps) < total,
        "summary": summary,
    }


def match_violations_to_steps(
    steps: List[Dict], violations: List[Dict]
) -> Dict[int, List[Dict]]:
    """Match violations to conversation steps by timestamp proximity.

    For each violation, finds the step with the latest timestamp that is
    at or before the violation timestamp. Multiple violations can map to
    the same step.

    Returns dict mapping step_index -> list of matching violations.
    """
    if not steps or not violations:
        return {}

    step_timestamps = []
    for i, step in enumerate(steps):
        ts = step.get("timestamp", "")
        if ts:
            step_timestamps.append((i, ts))

    if not step_timestamps:
        return {}

    result: Dict[int, List[Dict]] = {}
    for v in violations:
        v_ts = v.get("timestamp", "")
        if not v_ts:
            continue

        best_idx = step_timestamps[0][0]
        for step_idx, step_ts in step_timestamps:
            if step_ts <= v_ts:
                best_idx = step_idx
            else:
                break

        result.setdefault(best_idx, []).append(v)

    return result
