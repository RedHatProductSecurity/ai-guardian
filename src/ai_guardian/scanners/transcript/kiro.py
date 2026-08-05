"""Kiro (AWS) transcript adapter — JSONL session files.

Kiro stores CLI conversation transcripts as JSONL files at
``~/.kiro/sessions/cli/<session-id>.jsonl``.  Each line is a JSON
object with a ``type`` field indicating the entry kind (user_message,
agent_message_chunk, tool_call, tool_result).
"""

import logging
import os
from typing import Dict, List, Optional

from ai_guardian.scanners.transcript.base import TranscriptAdapter
from ai_guardian.scanners.transcript.common import (
    _discover_path,
    _get_most_recent_entry,
    _scan_jsonl_incremental,
)

logger = logging.getLogger(__name__)


def get_kiro_sessions_dir() -> Optional[str]:
    """Find the Kiro CLI sessions directory.

    Checks ``KIRO_SESSIONS_DIR`` env var first, then the default
    ``~/.kiro/sessions/cli`` path.
    """
    return _discover_path("KIRO_SESSIONS_DIR", "~/.kiro/sessions/cli")


def _extract_text_from_kiro_entry(entry: dict) -> str:
    """Extract scannable text from a single Kiro JSONL entry.

    Handles known entry types and falls back to extracting the
    ``content`` field for unrecognised types.
    """
    entry_type = entry.get("type")
    if not isinstance(entry_type, str):
        return ""

    if entry_type in ("user_message", "agent_message_chunk"):
        content = entry.get("content")
        return content if isinstance(content, str) else ""

    if entry_type == "tool_call":
        texts: List[str] = []
        args = entry.get("arguments")
        if isinstance(args, dict):
            for field in ("command", "content", "text", "path"):
                val = args.get(field)
                if isinstance(val, str) and val:
                    texts.append(val)
        elif isinstance(args, str) and args:
            texts.append(args)
        return "\n".join(texts)

    if entry_type == "tool_result":
        content = entry.get("content")
        if isinstance(content, str) and content:
            return content
        output = entry.get("output")
        if isinstance(output, str) and output:
            return output
        return ""

    content = entry.get("content")
    if isinstance(content, str) and content:
        return content
    return ""


def get_most_recent_session_file(sessions_dir: str) -> Optional[str]:
    """Find the most recently modified ``.jsonl`` session file."""
    result = _get_most_recent_entry(
        sessions_dir,
        match_fn=lambda e: e.is_file() and e.name.endswith(".jsonl"),
        label="Kiro",
    )
    return result[0] if result else None


def scan_kiro_transcript_incremental(
    transcript_path: str,
    session_id: str,
    secret_config: Optional[Dict] = None,
    pii_config: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    allowed_findings: Optional[set] = None,
) -> list:
    """Incrementally scan a Kiro transcript JSONL file."""
    return _scan_jsonl_incremental(
        transcript_path,
        pos_key=f"kiro:{session_id}",
        extract_fn=_extract_text_from_kiro_entry,
        label="Kiro",
        secret_config=secret_config,
        pii_config=pii_config,
        hook_context=hook_context,
        allowed_findings=allowed_findings,
    )


class KiroTranscriptAdapter(TranscriptAdapter):
    """Transcript adapter for Kiro CLI JSONL session files."""

    @property
    def name(self) -> str:
        return "Kiro"

    def scan_incremental(
        self,
        hook_data: Dict,
        secret_config: Optional[Dict] = None,
        pii_config: Optional[Dict] = None,
        hook_context: Optional[Dict] = None,
        allowed_findings: Optional[set] = None,
    ) -> List[str]:
        sessions_dir = get_kiro_sessions_dir()
        if not sessions_dir:
            logger.debug("Kiro transcript: no sessions directory found")
            return []

        session_id = hook_data.get("session_id")
        transcript_path = None
        if session_id:
            candidate = os.path.join(sessions_dir, f"{session_id}.jsonl")
            if os.path.isfile(candidate):
                transcript_path = candidate

        if not transcript_path:
            transcript_path = get_most_recent_session_file(sessions_dir)

        if not transcript_path:
            logger.debug("Kiro transcript: no session file found")
            return []

        session_id = os.path.splitext(os.path.basename(transcript_path))[0]

        return scan_kiro_transcript_incremental(
            transcript_path,
            session_id,
            secret_config=secret_config,
            pii_config=pii_config,
            hook_context=hook_context,
            allowed_findings=allowed_findings,
        )
