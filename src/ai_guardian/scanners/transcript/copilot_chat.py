"""GitHub Copilot Chat (VS Code) transcript adapter — JSONL delta journal files.

VS Code stores Copilot Chat conversation transcripts as JSONL files in
``workspaceStorage/*/chatSessions/*.jsonl`` and
``globalStorage/emptyWindowChatSessions/*.jsonl``.  Each line is a JSON
object using a delta journal format: ``kind:0`` (base snapshot),
``kind:1`` (set mutation), ``kind:2`` (array append).
"""

import glob
import logging
import os
import sys
from typing import Dict, List, Optional

from ai_guardian.scanners.transcript.base import TranscriptAdapter
from ai_guardian.scanners.transcript.common import (
    _get_most_recent_entry,
    _scan_jsonl_incremental,
)

logger = logging.getLogger(__name__)


def _get_vscode_user_dir() -> str:
    """Return the platform-specific VS Code User directory."""
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Code/User")
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        return os.path.join(appdata, "Code", "User")
    else:
        return os.path.expanduser("~/.config/Code/User")


def get_copilot_chat_dirs() -> List[str]:
    """Find directories containing Copilot Chat JSONL session files.

    Checks ``COPILOT_CHAT_DATA_DIR`` env var first, then VS Code's
    ``workspaceStorage/*/chatSessions/`` and
    ``globalStorage/emptyWindowChatSessions/`` directories.

    Returns:
        List of existing directories that contain (or may contain) session files.
    """
    custom = os.environ.get("COPILOT_CHAT_DATA_DIR")
    if custom and os.path.isdir(custom):
        return [custom]

    user_dir = _get_vscode_user_dir()
    dirs: List[str] = []

    ws_pattern = os.path.join(user_dir, "workspaceStorage", "*", "chatSessions")
    dirs.extend(sorted(glob.glob(ws_pattern)))

    global_dir = os.path.join(user_dir, "globalStorage", "emptyWindowChatSessions")
    if os.path.isdir(global_dir):
        dirs.append(global_dir)

    return dirs


def _find_session_file(
    chat_dirs: List[str], session_id: Optional[str] = None
) -> Optional[str]:
    """Locate a specific session JSONL file, or the most recently modified one.

    When *session_id* is provided, searches for ``{session_id}.jsonl``
    across all *chat_dirs*.  Otherwise returns the most recently modified
    ``.jsonl`` file.
    """
    if session_id:
        for d in chat_dirs:
            candidate = os.path.join(d, f"{session_id}.jsonl")
            if os.path.isfile(candidate):
                return candidate

    best: Optional[str] = None
    best_mtime = -1.0
    for d in chat_dirs:
        result = _get_most_recent_entry(
            d,
            match_fn=lambda e: e.is_file() and e.name.endswith(".jsonl"),
            label="Copilot Chat",
        )
        if result:
            path, mtime = result
            if mtime > best_mtime:
                best = path
                best_mtime = mtime

    return best


def _walk_strings(obj) -> List[str]:
    """Recursively collect non-empty string values from a nested structure."""
    texts: List[str] = []
    if isinstance(obj, str):
        if obj:
            texts.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            texts.extend(_walk_strings(v))
    elif isinstance(obj, list):
        for item in obj:
            texts.extend(_walk_strings(item))
    return texts


def _extract_text_from_request(request: dict) -> str:
    """Extract scannable text from a single chat request object."""
    texts: List[str] = []

    msg = request.get("message")
    if isinstance(msg, dict):
        for field in ("text", "prompt", "content"):
            val = msg.get(field)
            if isinstance(val, str) and val:
                texts.append(val)
    elif isinstance(msg, str) and msg:
        texts.append(msg)

    resp = request.get("response")
    if isinstance(resp, dict):
        for field in ("value", "result", "text", "message"):
            val = resp.get(field)
            if isinstance(val, str) and val:
                texts.append(val)
        resp_parts = resp.get("response")
        if isinstance(resp_parts, list):
            for part in resp_parts:
                if isinstance(part, dict):
                    val = part.get("value")
                    if isinstance(val, str) and val:
                        texts.append(val)

    return "\n".join(texts)


def _extract_text_from_chat_entry(entry: dict) -> str:
    """Extract scannable text from a single JSONL delta journal entry.

    Handles ``kind:0`` (base snapshot with requests), ``kind:1`` (set
    mutation), and ``kind:2`` (array append).  Unknown kinds are ignored.
    """
    kind = entry.get("kind")

    if kind == 0:
        v = entry.get("v")
        if not isinstance(v, dict):
            return ""
        requests = v.get("requests")
        if not isinstance(requests, list):
            return ""
        texts: List[str] = []
        for req in requests:
            if isinstance(req, dict):
                extracted = _extract_text_from_request(req)
                if extracted:
                    texts.append(extracted)
        return "\n".join(texts)

    if kind in (1, 2):
        v = entry.get("v")
        if v is None:
            return ""
        found = _walk_strings(v)
        return "\n".join(found) if found else ""

    return ""


def scan_copilot_chat_transcript_incremental(
    transcript_path: str,
    session_id: str,
    secret_config: Optional[Dict] = None,
    pii_config: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    allowed_findings: Optional[set] = None,
) -> list:
    """Incrementally scan a Copilot Chat JSONL session file."""
    return _scan_jsonl_incremental(
        transcript_path,
        pos_key=f"copilot-chat:{session_id}",
        extract_fn=_extract_text_from_chat_entry,
        label="Copilot Chat",
        strip_bom=True,
        secret_config=secret_config,
        pii_config=pii_config,
        hook_context=hook_context,
        allowed_findings=allowed_findings,
    )


class CopilotChatTranscriptAdapter(TranscriptAdapter):
    """Transcript adapter for GitHub Copilot Chat VS Code JSONL session files."""

    @property
    def name(self) -> str:
        return "GitHub Copilot"

    def scan_incremental(
        self,
        hook_data: Dict,
        secret_config: Optional[Dict] = None,
        pii_config: Optional[Dict] = None,
        hook_context: Optional[Dict] = None,
        allowed_findings: Optional[set] = None,
    ) -> List[str]:
        chat_dirs = get_copilot_chat_dirs()
        if not chat_dirs:
            logger.debug("Copilot Chat transcript: no chatSessions directories found")
            return []

        session_id = hook_data.get("sessionId") or hook_data.get("session_id")
        transcript_path = _find_session_file(chat_dirs, session_id)
        if not transcript_path:
            logger.debug("Copilot Chat transcript: no session file found")
            return []

        file_session_id = os.path.splitext(os.path.basename(transcript_path))[0]

        return scan_copilot_chat_transcript_incremental(
            transcript_path,
            file_session_id,
            secret_config=secret_config,
            pii_config=pii_config,
            hook_context=hook_context,
            allowed_findings=allowed_findings,
        )
