"""AiderDesk transcript adapter — Markdown chat history files.

AiderDesk (and the underlying Aider CLI) stores conversation transcripts
as append-only Markdown files, typically ``.aider.chat.history.md`` in the
project root.  The format uses ``####`` H4 headings for user messages,
bare text for assistant responses, and ``>`` blockquotes for system/cost
messages.
"""

import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from ai_guardian.scanners.transcript.base import TranscriptAdapter
from ai_guardian.scanners.transcript.common import (
    _get_transcript_path,
    _scan_transcript_text,
    _scan_with_position_tracking,
)

logger = logging.getLogger(__name__)

_H4_RE = re.compile(r"^####\s+")
_SESSION_HEADER_RE = re.compile(r"^#\s+aider chat started at\s+")


def get_aiderdesk_history_path() -> Optional[str]:
    """Find the AiderDesk/Aider chat history file.

    Checks ``AIDER_CHAT_HISTORY_FILE`` env var first, then looks for
    ``.aider.chat.history.md`` in the current working directory.
    """
    custom = os.environ.get("AIDER_CHAT_HISTORY_FILE")
    if custom and os.path.isfile(custom):
        return custom

    default = os.path.join(os.getcwd(), ".aider.chat.history.md")
    if os.path.isfile(default):
        return default

    return None


def _extract_text_from_markdown(content: str) -> str:
    """Extract scannable text from Aider Markdown transcript content.

    Strips session headers (``# aider chat started at ...``) and cost
    blockquotes (``> Tokens: ...``) but keeps user messages, assistant
    responses, and code blocks.
    """
    lines = content.split("\n")
    texts: List[str] = []
    for line in lines:
        if _SESSION_HEADER_RE.match(line):
            continue
        if line.startswith("> Tokens:") or line.startswith("> Cost:"):
            continue
        if line.startswith("####"):
            line = _H4_RE.sub("", line)
        texts.append(line)
    return "\n".join(texts)


def read_aiderdesk_transcript(
    history_path: str,
    byte_offset: int = 0,
) -> Tuple[str, int]:
    """Read new content from an Aider chat history Markdown file.

    Uses byte offset for incremental reading (file is append-only).

    Returns:
        Tuple of (extracted_text, new_byte_offset).
    """
    try:
        file_size = os.path.getsize(history_path)
        if file_size <= byte_offset:
            return "", byte_offset

        with open(history_path, "rb") as f:
            if byte_offset > 0:
                f.seek(byte_offset)
            raw = f.read()
            new_offset = f.tell()

        new_content = raw.decode("utf-8", errors="replace")
        extracted = _extract_text_from_markdown(new_content)
        return extracted, new_offset
    except OSError as e:
        logger.debug(f"AiderDesk transcript read error: {e}")
        return "", byte_offset


def scan_aiderdesk_transcript_incremental(
    history_path: str,
    secret_config: Optional[Dict] = None,
    pii_config: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    allowed_findings: Optional[set] = None,
) -> list:
    """Incrementally scan an AiderDesk/Aider Markdown transcript file."""
    pos_key = f"aiderdesk:{os.path.basename(history_path)}"

    combined_text = _scan_with_position_tracking(
        pos_key,
        reader_fn=lambda offset: read_aiderdesk_transcript(history_path, offset),
        label="AiderDesk",
    )

    if not combined_text:
        return []

    return _scan_transcript_text(
        combined_text,
        pos_key,
        secret_config,
        pii_config,
        hook_context,
        allowed_findings=allowed_findings,
    )


class AiderDeskTranscriptAdapter(TranscriptAdapter):
    """Transcript adapter for AiderDesk Markdown chat history files."""

    @property
    def name(self) -> str:
        return "AiderDesk"

    def can_scan(
        self,
        hook_data: Dict,
        adapter=None,
    ) -> bool:
        # AiderDesk shares KiroAdapter (no dedicated hook adapter), so the
        # base class adapter.name matching won't work. Use the env var instead.
        ide_type = os.environ.get("AI_GUARDIAN_IDE_TYPE", "").lower()
        if ide_type != "aiderdesk":
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
        history_path = get_aiderdesk_history_path()
        if not history_path:
            logger.debug("AiderDesk transcript: no history file found")
            return []

        return scan_aiderdesk_transcript_incremental(
            history_path,
            secret_config=secret_config,
            pii_config=pii_config,
            hook_context=hook_context,
            allowed_findings=allowed_findings,
        )
