"""Pi transcript adapter for JSONL session files."""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from ai_guardian.ide_paths import get_ide_home
from ai_guardian.scanners.transcript.base import TranscriptAdapter
from ai_guardian.scanners.transcript.common import (
    _get_transcript_path,
    _scan_jsonl_incremental,
)

logger = logging.getLogger(__name__)


def _pi_sessions_dir() -> Optional[Path]:
    """Return Pi's session root, honoring its documented session override."""
    configured = os.environ.get("PI_CODING_AGENT_SESSION_DIR")
    if configured:
        return Path(os.path.expandvars(configured)).expanduser()

    home = get_ide_home("pi")
    if home is not None:
        return home / "sessions"
    return Path("~/.pi/agent/sessions").expanduser()


def _most_recent_pi_session() -> Optional[str]:
    """Find the newest Pi JSONL session file when a hook omits its path."""
    sessions_dir = _pi_sessions_dir()
    if not sessions_dir or not sessions_dir.is_dir():
        return None

    try:
        candidates = [path for path in sessions_dir.rglob("*.jsonl") if path.is_file()]
        if not candidates:
            return None
        return str(max(candidates, key=lambda path: path.stat().st_mtime))
    except OSError:
        return None


def _content_text(content) -> List[str]:
    """Extract text and tool arguments from Pi message content blocks."""
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []

    texts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text" and isinstance(block.get("text"), str):
            texts.append(block["text"])
        elif block_type == "thinking" and isinstance(block.get("thinking"), str):
            texts.append(block["thinking"])
        elif block_type == "toolCall":
            name = block.get("name", "")
            arguments = block.get("arguments", {})
            texts.append(json.dumps({"name": name, "arguments": arguments}))
    return texts


def _extract_text_from_pi_entry(entry: dict) -> str:
    """Extract scannable content from one Pi session entry."""
    entry_type = entry.get("type")
    if entry_type == "message" and isinstance(entry.get("message"), dict):
        message = entry["message"]
        texts = _content_text(message.get("content"))
        return "\n".join(text for text in texts if text)

    if entry_type in ("custom_message", "compaction", "branch_summary"):
        value = entry.get("content") or entry.get("summary")
        return value if isinstance(value, str) else ""

    return ""


def scan_pi_transcript_incremental(
    transcript_path: str,
    secret_config: Optional[Dict] = None,
    pii_config: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    allowed_findings: Optional[set] = None,
) -> List[str]:
    """Incrementally scan a Pi JSONL session file."""
    return _scan_jsonl_incremental(
        transcript_path,
        pos_key=f"pi:{transcript_path}",
        extract_fn=_extract_text_from_pi_entry,
        label="Pi",
        secret_config=secret_config,
        pii_config=pii_config,
        hook_context=hook_context,
        allowed_findings=allowed_findings,
    )


class PiTranscriptAdapter(TranscriptAdapter):
    """Transcript adapter for Pi's v3 JSONL session format."""

    @property
    def name(self) -> str:
        return "Pi"

    def can_scan(self, hook_data: Dict, adapter=None) -> bool:
        return bool(adapter and adapter.name == self.name)

    def scan_incremental(
        self,
        hook_data: Dict,
        secret_config: Optional[Dict] = None,
        pii_config: Optional[Dict] = None,
        hook_context: Optional[Dict] = None,
        allowed_findings: Optional[set] = None,
    ) -> List[str]:
        transcript_path = _get_transcript_path(hook_data) or _most_recent_pi_session()
        if not transcript_path:
            logger.debug("Pi transcript: no session file found")
            return []

        return scan_pi_transcript_incremental(
            transcript_path,
            secret_config=secret_config,
            pii_config=pii_config,
            hook_context=hook_context,
            allowed_findings=allowed_findings,
        )
