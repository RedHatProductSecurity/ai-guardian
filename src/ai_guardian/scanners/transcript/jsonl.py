"""JSONL transcript adapter — Claude Code, Copilot CLI, Codex."""

try:
    import fcntl

    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

from ai_guardian.config.utils import get_state_dir
from ai_guardian.scanners.transcript.base import TranscriptAdapter
from ai_guardian.scanners.transcript.common import (
    _get_transcript_path,
    _load_transcript_positions,
    _save_transcript_positions,
    _scan_jsonl_incremental,
)


def _extract_text_from_transcript_line(line_data: dict) -> str:
    """Extract scannable text content from a transcript JSONL line.

    Defensively handles various JSONL formats from different IDEs.
    """
    texts = []

    message = line_data.get("message")
    if isinstance(message, dict):
        content = message.get("content", "")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))

    content = line_data.get("content")
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                text = block.get("text") or block.get("content", "")
                if text:
                    texts.append(text)

    text = line_data.get("text")
    if isinstance(text, str):
        texts.append(text)

    for field in ("result", "output", "stdout"):
        val = line_data.get(field)
        if isinstance(val, str):
            texts.append(val)

    return "\n".join(t for t in texts if t)


def scan_transcript_incremental(
    transcript_path: str,
    secret_config: Optional[Dict] = None,
    pii_config: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    allowed_findings: Optional[set] = None,
) -> list:
    """Incrementally scan a JSONL transcript file for secrets and PII.

    Reads only new bytes since the last recorded position. Extracts text
    content from JSONL lines and runs through available scanners.

    Prompt injection scanning is intentionally excluded — conversation
    history naturally contains patterns that trigger false positives.
    """
    if not os.path.exists(transcript_path):
        logger.debug(f"Transcript file does not exist: {transcript_path}")
        return []

    return _scan_jsonl_incremental(
        transcript_path,
        pos_key=transcript_path,
        extract_fn=_extract_text_from_transcript_line,
        label="JSONL",
        secret_config=secret_config,
        pii_config=pii_config,
        hook_context=hook_context,
        allowed_findings=allowed_findings,
    )


def _advance_transcript_position(hook_data: dict) -> None:
    """Advance JSONL transcript position to current file size after PostToolUse.

    Prevents stale warnings when the next session rescans unscanned tail bytes.
    Only advances entries that scan_transcript_incremental has already
    initialized — never creates new entries.

    Uses file locking (where available) for atomic read-modify-write.
    """
    transcript_path = _get_transcript_path(hook_data)
    if not transcript_path:
        return
    try:
        file_size = os.path.getsize(transcript_path)
    except OSError:
        return

    state_dir = get_state_dir()
    lock_file = state_dir / "transcript_positions.lock"

    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(lock_file, "w") as lf:
            if _HAS_FCNTL:
                fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                positions = _load_transcript_positions()
                if transcript_path not in positions:
                    return
                if file_size > positions[transcript_path]:
                    positions[transcript_path] = file_size
                    _save_transcript_positions(positions)
            finally:
                if _HAS_FCNTL:
                    fcntl.flock(lf, fcntl.LOCK_UN)
    except OSError as e:
        logger.debug(f"Failed to advance transcript position: {e}")


class JsonlTranscriptAdapter(TranscriptAdapter):
    """Transcript adapter for JSONL-based transcripts (Claude Code, Copilot, Codex)."""

    @property
    def name(self) -> str:
        return "JSONL"

    def can_scan(self, hook_data: Dict, adapter=None) -> bool:
        return bool(_get_transcript_path(hook_data))

    def scan_incremental(
        self,
        hook_data: Dict,
        secret_config: Optional[Dict] = None,
        pii_config: Optional[Dict] = None,
        hook_context: Optional[Dict] = None,
        allowed_findings: Optional[set] = None,
    ) -> List[str]:
        transcript_path = _get_transcript_path(hook_data)
        if not transcript_path:
            return []

        return scan_transcript_incremental(
            transcript_path,
            secret_config=secret_config,
            pii_config=pii_config,
            hook_context=hook_context,
            allowed_findings=allowed_findings,
        )
