"""OpenAI Codex (CLI + Desktop) hook adapter.

Codex uses the same PascalCase format and JSON response structure as
Claude Code, so this adapter extends BaseAgentAdapter.

Codex stores JSONL transcripts at:
    ~/.codex/sessions/YYYY/MM/DD/*.jsonl
"""

import glob
import os
from typing import ClassVar, Dict, FrozenSet, List

from ai_guardian.constants import CODEX_DISPLAY_NAME
from ai_guardian.hook_adapters.base_agent import BaseAgentAdapter


class CodexAdapter(BaseAgentAdapter):
    """Adapter for OpenAI Codex (CLI + Desktop).

    Codex shares Claude Code's hook format (PascalCase events, same
    JSON response structure). Codex command hooks include the documented
    ``model`` field, while explicit ``_ide_type``/environment metadata is
    also supported for forwarded or older payloads.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["codex"]
    AGENT_TYPE: ClassVar[str] = "codex"
    CODEX_HOOK_EVENTS: ClassVar[FrozenSet[str]] = frozenset(
        {
            "PermissionRequest",
            "PreCompact",
            "Interrupt",
            "SubagentStart",
            "SubagentStop",
            "Stop",
            "SessionStart",
            "SessionEnd",
            "PostCompact",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
        }
    )

    # Base directory for Codex session transcripts
    SESSIONS_DIR = os.path.expanduser("~/.codex/sessions")

    @property
    def name(self) -> str:
        return CODEX_DISPLAY_NAME

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        if not isinstance(hook_data, dict):
            return False

        explicit_ide = hook_data.get("_ide_type") or hook_data.get("ide_type")
        if isinstance(explicit_ide, str) and explicit_ide.lower() == "codex":
            return True

        if os.environ.get("AI_GUARDIAN_IDE_TYPE", "").lower() in cls.ENV_ALIASES:
            return True

        for key in ("codex_version", "codexVersion", "codex_hook_version"):
            if hook_data.get(key):
                return True

        for key in ("hook_source", "agent", "agent_name"):
            value = hook_data.get(key)
            if isinstance(value, str) and value.lower() in {
                "codex",
                "codex-cli",
                "openai-codex",
            }:
                return True

        event_name = hook_data.get("hook_event_name") or hook_data.get(
            "hookEventName", ""
        )
        if not isinstance(event_name, str) or event_name not in cls.CODEX_HOOK_EVENTS:
            return False

        # ``model`` is a documented Codex-specific common field. ``turn_id``
        # is the other stable Codex marker for payloads without model metadata;
        # permission_mode alone is intentionally not sufficient because it is
        # also present in Claude-style tool payloads.
        return any(key in hook_data for key in ("model", "turn_id"))

    def get_default_transcript_paths(self) -> List[str]:
        """Return Codex JSONL transcript paths that exist on disk.

        Codex organises sessions by date: ~/.codex/sessions/YYYY/MM/DD/*.jsonl
        Returns all JSONL files sorted by modification time (most recent first)
        so the caller can scan the active session.
        """
        if not os.path.isdir(self.SESSIONS_DIR):
            return []

        pattern = os.path.join(self.SESSIONS_DIR, "**", "*.jsonl")
        files = glob.glob(pattern, recursive=True)
        if not files:
            return []

        # Sort by modification time, most recent first
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        return files
