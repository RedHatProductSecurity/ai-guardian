"""Windsurf (Devin Desktop) transcript adapter — JSONL step files.

Windsurf stores Cascade conversation transcripts as JSONL files at
``~/.windsurf/transcripts/{trajectory_id}.jsonl``.  Each line is a JSON
object with ``type``, ``status``, and type-specific data fields.
"""

import logging
import os
from typing import Dict, List, Optional

from ai_guardian.scanners.transcript.base import TranscriptAdapter
from ai_guardian.scanners.transcript.common import (
    _discover_path,
    _scan_jsonl_incremental,
)

logger = logging.getLogger(__name__)


def get_windsurf_transcripts_dir() -> Optional[str]:
    """Find the Windsurf transcripts directory.

    Checks ``WINDSURF_TRANSCRIPTS_DIR`` env var first, then the default
    ``~/.windsurf/transcripts`` path (same across platforms per Windsurf docs).
    """
    return _discover_path("WINDSURF_TRANSCRIPTS_DIR", "~/.windsurf/transcripts")


_KNOWN_STEP_FIELDS = {
    "user_input": "user_response",
    "planner_response": "response",
    "code_action": "new_content",
}


def _extract_text_from_windsurf_step(step: dict) -> str:
    """Extract scannable text from a single Windsurf JSONL step object.

    Handles known step types via ``_KNOWN_STEP_FIELDS`` mapping and falls
    back to walking the type-named sub-dict for string values.
    """
    step_type = step.get("type")
    if not isinstance(step_type, str):
        return ""

    type_data = step.get(step_type)
    if not isinstance(type_data, dict):
        return ""

    field = _KNOWN_STEP_FIELDS.get(step_type)
    if field is not None:
        text = type_data.get(field)
        return text if isinstance(text, str) else ""

    texts: List[str] = []
    for val in type_data.values():
        if isinstance(val, str) and val:
            texts.append(val)
    return "\n".join(texts)


def scan_windsurf_transcript_incremental(
    transcript_path: str,
    trajectory_id: str,
    secret_config: Optional[Dict] = None,
    pii_config: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    allowed_findings: Optional[set] = None,
) -> list:
    """Incrementally scan a Windsurf transcript JSONL file."""
    return _scan_jsonl_incremental(
        transcript_path,
        pos_key=f"windsurf:{trajectory_id}",
        extract_fn=_extract_text_from_windsurf_step,
        label="Windsurf",
        secret_config=secret_config,
        pii_config=pii_config,
        hook_context=hook_context,
        allowed_findings=allowed_findings,
    )


class WindsurfTranscriptAdapter(TranscriptAdapter):
    """Transcript adapter for Windsurf JSONL step files."""

    @property
    def name(self) -> str:
        return "Windsurf"

    def scan_incremental(
        self,
        hook_data: Dict,
        secret_config: Optional[Dict] = None,
        pii_config: Optional[Dict] = None,
        hook_context: Optional[Dict] = None,
        allowed_findings: Optional[set] = None,
    ) -> List[str]:
        transcripts_dir = get_windsurf_transcripts_dir()
        if not transcripts_dir:
            logger.debug("Windsurf transcript: no transcripts directory found")
            return []

        trajectory_id = hook_data.get("trajectory_id") or hook_data.get("session_id")
        if not trajectory_id:
            logger.debug("Windsurf transcript: no trajectory_id in hook data")
            return []

        transcript_path = os.path.join(transcripts_dir, f"{trajectory_id}.jsonl")
        if not os.path.isfile(transcript_path):
            logger.debug(f"Windsurf transcript file not found: {transcript_path}")
            return []

        return scan_windsurf_transcript_incremental(
            transcript_path,
            trajectory_id,
            secret_config=secret_config,
            pii_config=pii_config,
            hook_context=hook_context,
            allowed_findings=allowed_findings,
        )
