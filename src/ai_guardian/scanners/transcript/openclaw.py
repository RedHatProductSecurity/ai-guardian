"""OpenClaw transcript adapter — JSONL transcript files.

OpenClaw stores conversation transcripts as JSONL files at
``~/.openclaw/transcripts/YYYY-MM-DD/<session>/transcript.jsonl``.
Each line is a JSON object with a ``role`` field (user/assistant/tool)
and ``content`` (string or structured).
"""

import logging
import os
from typing import Dict, List, Optional

from ai_guardian.scanners.transcript.base import TranscriptAdapter
from ai_guardian.scanners.transcript.common import (
    _discover_path,
    _get_most_recent_entry,
    _get_transcript_path,
    _scan_jsonl_incremental,
)

logger = logging.getLogger(__name__)


def get_openclaw_transcripts_dir() -> Optional[str]:
    """Find the OpenClaw transcripts directory.

    Checks ``OPENCLAW_STATE_DIR`` env var first, then the default
    ``~/.openclaw/transcripts`` path.
    """
    return _discover_path("OPENCLAW_STATE_DIR", "~/.openclaw/transcripts")


def _extract_text_from_openclaw_entry(entry: dict) -> str:
    """Extract scannable text from a single OpenClaw JSONL entry.

    Handles ``content`` as string or structured object, plus ``output``
    and ``arguments`` fields for tool entries.
    """
    texts: List[str] = []

    content = entry.get("content")
    if isinstance(content, str) and content:
        texts.append(content)
    elif isinstance(content, dict):
        for field in ("text", "content", "value", "message"):
            val = content.get(field)
            if isinstance(val, str) and val:
                texts.append(val)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                text = block.get("text") or block.get("content", "")
                if isinstance(text, str) and text:
                    texts.append(text)

    output = entry.get("output")
    if isinstance(output, str) and output:
        texts.append(output)

    args = entry.get("arguments")
    if isinstance(args, dict):
        for field in ("command", "content", "text", "path"):
            val = args.get(field)
            if isinstance(val, str) and val:
                texts.append(val)
    elif isinstance(args, str) and args:
        texts.append(args)

    return "\n".join(texts)


def get_most_recent_transcript(transcripts_dir: str) -> Optional[str]:
    """Find the most recently modified ``transcript.jsonl`` file.

    Walks date directories (``YYYY-MM-DD/``) and session subdirectories
    to find the newest transcript.
    """
    try:
        date_dirs = sorted(os.listdir(transcripts_dir), reverse=True)
    except OSError as e:
        logger.debug(f"OpenClaw transcripts listing error: {e}")
        return None

    for date_dir in date_dirs:
        date_path = os.path.join(transcripts_dir, date_dir)
        if not os.path.isdir(date_path):
            continue
        result = _get_most_recent_entry(
            date_path,
            match_fn=lambda e: e.is_dir(),
            label="OpenClaw",
            mtime_fn=lambda e: os.path.getmtime(
                os.path.join(e.path, "transcript.jsonl")
            ),
        )
        if result:
            return os.path.join(result[0], "transcript.jsonl")


def scan_openclaw_transcript_incremental(
    transcript_path: str,
    session_id: str,
    secret_config: Optional[Dict] = None,
    pii_config: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    allowed_findings: Optional[set] = None,
) -> list:
    """Incrementally scan an OpenClaw transcript JSONL file."""
    return _scan_jsonl_incremental(
        transcript_path,
        pos_key=f"openclaw:{session_id}",
        extract_fn=_extract_text_from_openclaw_entry,
        label="OpenClaw",
        secret_config=secret_config,
        pii_config=pii_config,
        hook_context=hook_context,
        allowed_findings=allowed_findings,
    )


class OpenClawTranscriptAdapter(TranscriptAdapter):
    """Transcript adapter for OpenClaw JSONL transcript files."""

    @property
    def name(self) -> str:
        return "OpenClaw"

    def can_scan(
        self,
        hook_data: Dict,
        adapter=None,
    ) -> bool:
        # OpenClaw shares KiroAdapter (no dedicated hook adapter), so the
        # base class adapter.name matching won't work. Use the env var instead.
        ide_type = os.environ.get("AI_GUARDIAN_IDE_TYPE", "").lower()
        if ide_type != "openclaw":
            return False
        return not _get_transcript_path(hook_data)

    def scan_incremental(
        self,
        hook_data: Dict,
        secret_config: Optional[Dict] = None,
        pii_config: Optional[Dict] = None,
        hook_context: Optional[Dict] = None,
        allowed_findings: Optional[set] = None,
    ) -> List[str]:
        transcripts_dir = get_openclaw_transcripts_dir()
        if not transcripts_dir:
            logger.debug("OpenClaw transcript: no transcripts directory found")
            return []

        session_id = hook_data.get("session_id")
        transcript_path = None

        if session_id:
            try:
                for date_dir in sorted(os.listdir(transcripts_dir), reverse=True):
                    candidate = os.path.join(
                        transcripts_dir, date_dir, session_id, "transcript.jsonl"
                    )
                    if os.path.isfile(candidate):
                        transcript_path = candidate
                        break
            except OSError:
                pass

        if not transcript_path:
            transcript_path = get_most_recent_transcript(transcripts_dir)

        if not transcript_path:
            logger.debug("OpenClaw transcript: no transcript file found")
            return []

        if not session_id:
            parts = transcript_path.split(os.sep)
            session_id = parts[-2] if len(parts) >= 2 else "unknown"

        return scan_openclaw_transcript_incremental(
            transcript_path,
            session_id,
            secret_config=secret_config,
            pii_config=pii_config,
            hook_context=hook_context,
            allowed_findings=allowed_findings,
        )
