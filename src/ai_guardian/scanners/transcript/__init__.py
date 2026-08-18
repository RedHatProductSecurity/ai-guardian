"""Transcript scanning subpackage — per-IDE adapters for incremental scanning.

Provides a polymorphic TranscriptAdapter interface and concrete adapters
for JSONL (Claude Code, Copilot, Codex), Copilot Chat (VS Code JSONL
delta journal), OpenCode (SQLite), Cursor (SQLite),
Cline/ZooCode (JSON array), Kiro (JSONL), Windsurf (JSONL),
AiderDesk (Markdown), and OpenClaw (JSONL).
"""

from ai_guardian.scanners.transcript.aiderdesk import (
    AiderDeskTranscriptAdapter,
    scan_aiderdesk_transcript_incremental,
)
from ai_guardian.scanners.transcript.base import TranscriptAdapter
from ai_guardian.scanners.transcript.common import (
    _discover_path,
    _extract_secret_type_from_error,
    _finding_fingerprint,
    _get_transcript_path,
    _load_seen_findings,
    _load_transcript_positions,
    _log_transcript_violation,
    _save_seen_findings,
    _save_transcript_positions,
    _scan_transcript_text,
    _scan_with_position_tracking,
    parse_transcript_token_usage,
)
from ai_guardian.scanners.transcript.cline import (
    ClineTranscriptAdapter,
    scan_cline_transcript_incremental,
)
from ai_guardian.scanners.transcript.copilot_chat import (
    CopilotChatTranscriptAdapter,
    scan_copilot_chat_transcript_incremental,
)
from ai_guardian.scanners.transcript.cursor import (
    CursorTranscriptAdapter,
    scan_cursor_transcript_incremental,
)
from ai_guardian.scanners.transcript.jsonl import (
    JsonlTranscriptAdapter,
    _advance_transcript_position,
    _extract_text_from_transcript_line,
    scan_transcript_incremental,
)
from ai_guardian.scanners.transcript.kiro import (
    KiroTranscriptAdapter,
    scan_kiro_transcript_incremental,
)
from ai_guardian.scanners.transcript.opencode import (
    OpenCodeTranscriptAdapter,
    scan_opencode_transcript_incremental,
)
from ai_guardian.scanners.transcript.openclaw import (
    OpenClawTranscriptAdapter,
    scan_openclaw_transcript_incremental,
)
from ai_guardian.scanners.transcript.windsurf import (
    WindsurfTranscriptAdapter,
    scan_windsurf_transcript_incremental,
)

TRANSCRIPT_ADAPTERS = [
    AiderDeskTranscriptAdapter(),
    OpenClawTranscriptAdapter(),
    ClineTranscriptAdapter(),
    CopilotChatTranscriptAdapter(),
    KiroTranscriptAdapter(),
    WindsurfTranscriptAdapter(),
    JsonlTranscriptAdapter(),
    OpenCodeTranscriptAdapter(),
    CursorTranscriptAdapter(),
]

__all__ = [
    "TranscriptAdapter",
    "TRANSCRIPT_ADAPTERS",
    "AiderDeskTranscriptAdapter",
    "ClineTranscriptAdapter",
    "CopilotChatTranscriptAdapter",
    "KiroTranscriptAdapter",
    "OpenClawTranscriptAdapter",
    "WindsurfTranscriptAdapter",
    "_advance_transcript_position",
    "_discover_path",
    "_extract_secret_type_from_error",
    "_extract_text_from_transcript_line",
    "_finding_fingerprint",
    "_get_transcript_path",
    "_load_seen_findings",
    "_load_transcript_positions",
    "_log_transcript_violation",
    "_save_seen_findings",
    "_save_transcript_positions",
    "_scan_transcript_text",
    "_scan_with_position_tracking",
    "parse_transcript_token_usage",
    "scan_cline_transcript_incremental",
    "scan_copilot_chat_transcript_incremental",
    "scan_cursor_transcript_incremental",
    "scan_aiderdesk_transcript_incremental",
    "scan_kiro_transcript_incremental",
    "scan_openclaw_transcript_incremental",
    "scan_opencode_transcript_incremental",
    "scan_transcript_incremental",
    "scan_windsurf_transcript_incremental",
]
